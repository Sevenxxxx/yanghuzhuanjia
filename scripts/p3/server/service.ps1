#Requires -RunAsAdministrator
<#
  启停与状态：三个计划任务按依赖顺序管理，并清理残留的 dsh 运行时。
  用法：
      .\service.ps1 status
      .\service.ps1 stop
      .\service.ps1 start
      .\service.ps1 restart
#>
[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'restart', 'status')][string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'

# 启动顺序：代理 → 聊天 → 反代；停止顺序相反
$StartOrder = @('RoadModelProxy', 'RoadChat', 'RoadCaddy')
$StopOrder = @('RoadCaddy', 'RoadChat', 'RoadModelProxy')

function Get-Runtimes {
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*--profile road-sdk*' }
}

function Show-Status {
    Write-Host "`n== 计划任务 ==" -ForegroundColor Cyan
    foreach ($name in $StartOrder) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { Write-Host ("  {0,-16} 未注册" -f $name) -ForegroundColor DarkYellow; continue }
        $info = Get-ScheduledTaskInfo -TaskName $name
        $color = if ($task.State -eq 'Running') { 'Green' } else { 'DarkYellow' }
        Write-Host ("  {0,-16} {1,-10} 上次运行 {2} 结果 {3}" -f $name, $task.State, $info.LastRunTime, $info.LastTaskResult) -ForegroundColor $color
    }

    Write-Host "`n== 健康检查 ==" -ForegroundColor Cyan
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8095/api/health' -TimeoutSec 5
        Write-Host ("  聊天服务 ok={0} 访问者={1} 就绪={2} 会话={3}" -f $health.ok, $health.visitors, $health.ready, $health.sessions) -ForegroundColor Green
    } catch {
        Write-Host '  聊天服务无响应' -ForegroundColor Red
    }
    try {
        $code = (Invoke-WebRequest 'http://127.0.0.1:8096/models' -TimeoutSec 10 -UseBasicParsing).StatusCode
        Write-Host "  模型代理 HTTP $code" -ForegroundColor Green
    } catch {
        Write-Host '  模型代理无响应' -ForegroundColor Red
    }

    $runtimes = Get-Runtimes
    Write-Host "`n== dsh 运行时 ==" -ForegroundColor Cyan
    if (-not $runtimes) {
        Write-Host '  当前没有（没人说话时正常）' -ForegroundColor DarkGray
    } else {
        foreach ($item in $runtimes) {
            $process = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
            $memory = if ($process) { [int]($process.WorkingSet64 / 1MB) } else { 0 }
            Write-Host ("  pid {0}  {1} MB" -f $item.ProcessId, $memory)
        }
    }
}

function Wait-Healthy([int]$seconds = 40) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8095/api/health' -TimeoutSec 3
            if ($health.ok) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

switch ($Action) {
    'start' {
        foreach ($name in $StartOrder) {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            if (-not $task) { Write-Host "  跳过未注册的 $name" -ForegroundColor DarkYellow; continue }
            if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName $name }
            Write-Host "  已启动 $name"
        }
        if (Wait-Healthy) {
            Write-Host '服务已就绪：http://127.0.0.1:8095/api/health 正常' -ForegroundColor Green
        } else {
            Write-Host '40 秒内没等到健康响应，跑 status 看原因' -ForegroundColor Red
        }
    }
    'stop' {
        foreach ($name in $StopOrder) {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            if (-not $task) { continue }
            if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskName $name }
            Write-Host "  已停止 $name"
        }
        Start-Sleep -Seconds 2
        # 任务停止是直接终止进程，dsh 子进程可能残留，这里补一刀
        $leftovers = Get-Runtimes
        foreach ($item in $leftovers) {
            Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
        }
        if ($leftovers) {
            Write-Host ("  清理了 {0} 个残留的 dsh 运行时" -f $leftovers.Count) -ForegroundColor DarkYellow
        }
        Write-Host '已全部停止（数据在 C:\road\work，未删除）' -ForegroundColor Green
    }
    'restart' {
        & $PSCommandPath -Action stop
        Start-Sleep -Seconds 1
        & $PSCommandPath -Action start
    }
    'status' {
        Show-Status
    }
}
