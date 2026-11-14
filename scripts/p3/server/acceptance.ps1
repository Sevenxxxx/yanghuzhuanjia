#Requires -RunAsAdministrator
<#
  上线门槛自检（Windows）。全部 ✓ 再把口令发给同事。
  用法：.\acceptance.ps1
#>
[CmdletBinding()]
param(
    [string]$AppDir = 'C:\road\app',
    [string]$WorkDir = 'C:\road\work',
    [string]$EtcDir = 'C:\road\etc',
    [int]$ChatPort = 8095,
    [int]$ProxyPort = 8096
)

$ErrorActionPreference = 'Continue'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$ConfigPath = Join-Path $RepoRoot 'deploy.json'
if (Test-Path $ConfigPath) {
    $Deploy = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Deploy.paths.app) { $AppDir = [Environment]::ExpandEnvironmentVariables($Deploy.paths.app) }
    if ($Deploy.paths.work) { $WorkDir = [Environment]::ExpandEnvironmentVariables($Deploy.paths.work) }
    if ($Deploy.paths.etc) { $EtcDir = [Environment]::ExpandEnvironmentVariables($Deploy.paths.etc) }
}
$script:pass = 0
$script:fail = 0

function Check([string]$name, [scriptblock]$test) {
    try {
        $result = & $test
        if ($result -eq $false) { throw '返回 false' }
        Write-Host "  [OK] $name" -ForegroundColor Green
        $script:pass++
    } catch {
        Write-Host "  [!!] $name -> $($_.Exception.Message)" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host '== 1. 程序 ==' -ForegroundColor Cyan
Check 'dsh 已安装' {
    $version = dsh --version 2>&1
    if ($LASTEXITCODE -ne 0) { return $false }
    return [bool]$version
}
Check 'node >= 24.9' {
    $parts = (node --version).TrimStart('v').Split('.')
    ([int]$parts[0] -gt 24) -or ([int]$parts[0] -eq 24 -and [int]$parts[1] -ge 9)
}
Check 'python 依赖（pymupdf / pillow）' {
    python -c 'import fitz, PIL' | Out-Null
    return $LASTEXITCODE -eq 0
}

Write-Host '== 2. 项目工具 ==' -ForegroundColor Cyan
$probeStore = Join-Path $WorkDir 'acceptance-store'
Check 'road.py --doctor' {
    Push-Location $AppDir
    try {
        $env:ROAD_EXPERT_CONFIG = Join-Path $EtcDir 'config.json'
        $out = python -X utf8 scripts\road.py --store $probeStore --doctor 2>&1
        $LASTEXITCODE -eq 0 -and ($out -join '') -match '"ok": true'
    } finally { Pop-Location }
}
Check '规范检索一条' {
    Push-Location $AppDir
    try {
        $request = '{"op":"spec-search","query":"沥青路面养护"}'
        $out = $request | python -X utf8 scripts\road.py --store $probeStore - 2>&1
        $LASTEXITCODE -eq 0 -and ($out -join '') -match '"ok": true'
    } finally { Pop-Location }
}

Write-Host '== 3. 服务 ==' -ForegroundColor Cyan
Check "前端健康检查（127.0.0.1:$ChatPort）" {
    $state = Invoke-RestMethod "http://127.0.0.1:$ChatPort/api/health" -TimeoutSec 10
    return $state.ok -eq $true
}
Check "代理转发（127.0.0.1:$ProxyPort/models）" {
    $code = (Invoke-WebRequest "http://127.0.0.1:$ProxyPort/models" -TimeoutSec 30 -UseBasicParsing).StatusCode
    return $code -eq 200
}
foreach ($task in @('RoadChat', 'RoadModelProxy', 'RoadCaddy')) {
    Check "计划任务 $task 运行中" {
        (Get-ScheduledTask -TaskName $task -ErrorAction Stop).State -in @('Running', 'Ready')
    }
}

Write-Host '== 4. 权限与密钥 ==' -ForegroundColor Cyan
Check '程序目录对 roadchat 不可写' {
    $acl = (Get-Acl $AppDir).Access | Where-Object { $_.IdentityReference -like '*roadchat*' }
    -not ($acl | Where-Object { $_.FileSystemRights -match 'Write|Modify|FullControl' -and $_.AccessControlType -eq 'Allow' })
}
Check '真实 key 不在前端 env' {
    -not ((Get-Content (Join-Path $EtcDir 'roadchat.env') -Raw) -match 'DEEPSEEK_API_KEY=sk-')
}
Check '日志里没有 key' {
    -not (Select-String -Path 'C:\road\logs\*.log' -Pattern 'sk-[A-Za-z0-9]{20,}' -ErrorAction SilentlyContinue)
}
Check '防火墙已放行 8443' {
    [bool](Get-NetFirewallRule -DisplayName '*8443*' -ErrorAction SilentlyContinue)
}

Write-Host ''
if ($script:fail -gt 0) {
    Write-Host "结果：$script:pass 项通过，$script:fail 项失败" -ForegroundColor Red
    Write-Host '先修失败项，再把口令发出去。' -ForegroundColor Red
    exit 1
}
Write-Host "结果：$script:pass 项全部通过。下一步：双浏览器各问一句、停止互不影响、三条攻击演练。" -ForegroundColor Green
