#Requires -RunAsAdministrator
<#
  安装并启动聊天服务：配置、启动脚本、计划任务、Caddy 反代与证书。
  前提：bootstrap-windows.ps1 已跑完，仓库与规范库已就位。
  用法：
      .\install-chat.ps1 -ApiKey 'sk-...' [-Domain road.example.com]
#>
[CmdletBinding()]
param(
    [string]$ApiKey = '',
    [string]$Domain = '',
    [switch]$Https,
    [int]$HttpPort = 0,
    [int]$MaxVisitors = 8,
    [string]$AppDir = 'C:\road\app',
    [string]$WorkDir = 'C:\road\work',
    [string]$EtcDir = 'C:\road\etc',
    [string]$SpecDir = 'C:\road\specs',
    [string]$ServiceUser = 'roadchat',
    [int]$ChatPort = 8095,
    [int]$ProxyPort = 8096
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$ConfigPath = Join-Path $RepoRoot 'deploy.json'
if (Test-Path $ConfigPath) {
    $Deploy = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "使用配置：$ConfigPath" -ForegroundColor DarkGray
} else {
    $Deploy = $null
}

function Step([string]$text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }
function Expand-DeployPath([string]$value) {
    if (-not $value) { return $value }
    return [Environment]::ExpandEnvironmentVariables($value).TrimEnd('\')
}

function Grant-Traverse([string]$target, [string]$user) {
    # 目标在用户目录下时，逐级给读+执行（RX）；只给 X 时部分系统上仍会被拒
    $profileRoot = [Environment]::GetFolderPath('UserProfile')
    if (-not $target.StartsWith($profileRoot, [StringComparison]::OrdinalIgnoreCase)) { return }
    $chain = @($profileRoot)
    $current = $profileRoot
    $relative = $target.Substring($profileRoot.Length).TrimStart('\')
    $parts = $relative.Split('\')
    for ($i = 0; $i -lt $parts.Count - 1; $i++) {
        $current = Join-Path $current $parts[$i]
        if (Test-Path $current) { $chain += $current }
    }
    foreach ($dir in $chain) {
        icacls $dir /grant "${user}:(RX)" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "给 $dir 授权失败（icacls 退出码 $LASTEXITCODE）" -ForegroundColor DarkYellow
        }
    }
}

function Test-AsServiceUser([string]$path, [string]$password) {
    # 用服务账户真的试一次「能不能访问这个目录」
    $out = Join-Path $WorkDir 'acl-check.txt'
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    $cred = New-Object System.Management.Automation.PSCredential($ServiceUser, (ConvertTo-SecureString $password -AsPlainText -Force))
    $script = "if (Test-Path '$path') { 'OK' } else { 'DENIED' } | Out-File -FilePath '$out' -Encoding utf8"
    try {
        Start-Process powershell -Credential $cred -ArgumentList '-NoProfile', '-WindowStyle', 'Hidden', '-Command', $script -Wait -ErrorAction Stop
    } catch {
        Write-Host "无法以 $ServiceUser 身份启动测试进程：$($_.Exception.Message)" -ForegroundColor DarkYellow
        return
    }
    if (Test-Path $out) {
        $result = (Get-Content $out -Raw).Trim()
        if ($result -eq 'OK') {
            Write-Host "服务账户可访问仓库：$path" -ForegroundColor Green
        } else {
            Write-Host "服务账户仍无法访问仓库：$path（检查桌面是否被重定向）" -ForegroundColor Red
        }
        Remove-Item $out -Force -ErrorAction SilentlyContinue
    }
}


if ($Deploy) {
    if ($Deploy.paths.app) { $AppDir = Expand-DeployPath $Deploy.paths.app }
    if ($Deploy.paths.work) { $WorkDir = Expand-DeployPath $Deploy.paths.work }
    if ($Deploy.paths.etc) { $EtcDir = Expand-DeployPath $Deploy.paths.etc }
    if ($Deploy.paths.specs) { $SpecDir = Expand-DeployPath $Deploy.paths.specs }
    if ($Deploy.service_user) { $ServiceUser = $Deploy.service_user }
    if ($Deploy.domain) { $Domain = $Deploy.domain }
    if ($Deploy.max_visitors) { $MaxVisitors = [int]$Deploy.max_visitors }
    if ($null -ne $Deploy.https) { $Https = [bool]$Deploy.https }
    if ($Deploy.http_port) { $HttpPort = [int]$Deploy.http_port }
    if (-not $ApiKey -and $Deploy.api_key) { $ApiKey = $Deploy.api_key }
    $GatePassword = if ($null -ne $Deploy.password) { [string]$Deploy.password } else { 'yhg' }
} else {
    $GatePassword = 'yhg'
}
$UseHttps = $Https.IsPresent
if ($HttpPort -le 0) { $HttpPort = 8443 }
if (-not $ApiKey) { throw '没有 API key：在 deploy.json 里填 api_key，或用 -ApiKey 传入' }
if ($ApiKey -notmatch '^sk-') { throw "api_key 看起来不像真的（当前：$($ApiKey.Substring(0, [Math]::Min(6, $ApiKey.Length)))…）" }
if ($ApiKey -match '替换|你的|your|xxx|placeholder') {
    throw 'deploy.json 的 api_key 还是占位值，请填真实 key（DeepSeek 控制台 → API keys）'
}

foreach ($path in @("$AppDir\scripts\p3\chat\app.py", "$AppDir\scripts\p3\proxy\model_proxy.py")) {
    if (-not (Test-Path $path)) { throw "缺少 $path；先把仓库放到 $AppDir" }
}
Step '检查 dsh'
$dshCommand = Get-Command dsh -ErrorAction SilentlyContinue
if (-not $dshCommand) {
    throw '找不到 dsh：先执行 npm install -g @deepseek-ai/dsh，再重跑本脚本'
}
$dshDir = Split-Path $dshCommand.Source -Parent
Write-Host "dsh: $($dshCommand.Source)"

# 服务以 roadchat 身份运行，要能找到并读取 dsh（默认装在当前用户 %APPDATA%\npm 下）
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($machinePath -notlike "*$dshDir*") {
    [Environment]::SetEnvironmentVariable('Path', "$machinePath;$dshDir", 'Machine')
    Write-Host "已把 $dshDir 写入系统 PATH"
}
icacls $dshDir /grant "${ServiceUser}:(OI)(CI)RX" | Out-Null

# dsh 在某个用户目录下时，只给「穿越」权限，不给列目录，避免暴露该用户资料
$profileRoot = [Environment]::GetFolderPath('UserProfile')
if ($dshDir.StartsWith($profileRoot, [StringComparison]::OrdinalIgnoreCase)) {
    foreach ($ancestor in @($profileRoot, (Join-Path $profileRoot 'AppData'), (Join-Path $profileRoot 'AppData\Roaming'))) {
        if (Test-Path $ancestor) { icacls $ancestor /grant "${ServiceUser}:(X)" | Out-Null }
    }
    Write-Host "已给 $ServiceUser 穿越 $profileRoot 的权限（仅穿越，不能列目录）"
}
if (-not (Test-Path (Join-Path $EtcDir "$ServiceUser-password.txt"))) {
    throw "缺少 $EtcDir\$ServiceUser-password.txt；先跑 bootstrap-windows.ps1"
}
$servicePassword = (Get-Content (Join-Path $EtcDir "$ServiceUser-password.txt") -Raw).Trim()

Step '配置文件'
$config = @{
    spec_skill           = "$SpecDir\tools\guifan-chaxun"
    tool_timeout_seconds = 45
    privacy_default      = 'restricted'
}
Set-Content -Path (Join-Path $EtcDir 'config.json') -Value ($config | ConvertTo-Json) -Encoding utf8

Set-Content -Path (Join-Path $EtcDir 'roadchat.env') -Encoding utf8 -Value @(
    'DEEPSEEK_API_KEY=proxy-held'
    "ROAD_CHAT_PATCH=$EtcDir\proxy.patch.yml"
    "ROAD_EXPERT_CONFIG=$EtcDir\config.json"
    "ROAD_CHAT_PASSWORD=$GatePassword"
    "ROAD_CHAT_MAX_VISITORS=$MaxVisitors"
    'ROAD_CHAT_IDLE_SECONDS=1800'
)
Set-Content -Path (Join-Path $EtcDir 'proxy.env') -Encoding utf8 -Value "DEEPSEEK_API_KEY=$ApiKey"
Set-Content -Path (Join-Path $EtcDir 'proxy.patch.yml') -Encoding utf8 -Value @(
    '# 让 dsh 走本地代理，真实 key 只在代理进程里'
    '- id: llm-deepseek'
    '  name: "@deepseek-ai/dsh-llm-deepseek-api-key"'
    '  config:'
    "    baseURL: http://127.0.0.1:$ProxyPort"
)

# 真实 key 只有管理员与 SYSTEM 能读；roadchat 读不到
# 用 SID 而不是本地化组名，中文版 Windows 也不会失配
icacls (Join-Path $EtcDir 'proxy.env') /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null

Step '权限：服务账户可读配置、启动脚本、仓库与规范库'
# 服务以 roadchat 身份启动：要能读配置文件与启动脚本，读得到仓库与规范库
icacls $EtcDir /grant "${ServiceUser}:(OI)(CI)RX" | Out-Null
foreach ($configFile in @('config.json', 'roadchat.env', 'proxy.patch.yml')) {
    $configPath = Join-Path $EtcDir $configFile
    if (Test-Path $configPath) {
        icacls $configPath /grant "${ServiceUser}:RX" | Out-Null
    }
}
# proxy.env 的 ACL 已在上面收紧（仅 Administrators/SYSTEM），这里不碰它
$binDir = 'C:\road\bin'
if (Test-Path $binDir) { icacls $binDir /grant "${ServiceUser}:(OI)(CI)RX" /T | Out-Null }

foreach ($readonlyDir in @($AppDir, $SpecDir)) {
    if (-not (Test-Path $readonlyDir)) { continue }
    icacls $readonlyDir /grant "${ServiceUser}:(OI)(CI)RX" | Out-Null
    Grant-Traverse $readonlyDir $ServiceUser
}
Test-AsServiceUser $AppDir $servicePassword
Test-AsServiceUser $SpecDir $servicePassword

Step '启动脚本'
Set-Content -Path 'C:\road\bin\run-chat.ps1' -Encoding utf8 -Value @"
`$ErrorActionPreference = 'Stop'
`$logDir = Join-Path '$WorkDir' 'logs'
New-Item -ItemType Directory -Force -Path `$logDir | Out-Null
`$log = Join-Path `$logDir 'chat-run.log'
"=== `$(Get-Date -Format o) start user=`$([Environment]::UserName) ===" | Out-File `$log -Append -Encoding utf8
"Test-Path repo: `$(Test-Path '$AppDir') / spec: `$(Test-Path '$SpecDir')" | Out-File `$log -Append -Encoding utf8
try {
    Get-Content '$EtcDir\roadchat.env' | ForEach-Object {
        if (`$_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1].Trim(), `$matches[2].Trim(), 'Process') }
    }
    Set-Location '$AppDir'
    & python -X utf8 '$AppDir\scripts\p3\chat\app.py' --host 127.0.0.1 --port $ChatPort --home '$WorkDir' *>> `$log
} catch {
    `$_ | Out-File `$log -Append -Encoding utf8
    exit 1
}
"@
Set-Content -Path 'C:\road\bin\run-proxy.ps1' -Encoding utf8 -Value @"
`$ErrorActionPreference = 'Stop'
Get-Content '$EtcDir\proxy.env' | ForEach-Object {
    if (`$_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1].Trim(), `$matches[2].Trim(), 'Process') }
}
& python -X utf8 '$AppDir\scripts\p3\proxy\model_proxy.py' --port $ProxyPort --upstream https://api.deepseek.com/anthropic --usage-log 'C:\road\logs\usage.log'
"@

Step '计划任务'

function Grant-BatchLogon([string]$account) {
    # 计划任务「不论用户是否登录都运行」用的是批量登录权限，普通账户默认没有
    $cfg = Join-Path $env:TEMP ("secpol-" + [guid]::NewGuid().ToString("N") + ".cfg")
    $db = Join-Path $env:TEMP ("secpol-" + [guid]::NewGuid().ToString("N") + ".sdb")
    secedit /export /cfg $cfg | Out-Null
    $lines = Get-Content $cfg
    $right = $lines | Where-Object { $_ -match '^SeBatchLogonRight' }
    if ($right) {
        if ($right -notmatch [regex]::Escape($account)) {
            $lines = $lines -replace [regex]::Escape($right), ($right.TrimEnd() + ",$account")
        }
    } else {
        $lines = @($lines) + "SeBatchLogonRight = $account"
    }
    Set-Content -Path $cfg -Value $lines -Encoding unicode
    secedit /configure /db $db /cfg $cfg /areas USER_RIGHTS | Out-Null
    Remove-Item $cfg, $db -Force -ErrorAction SilentlyContinue
}

function Register-LongRunning([string]$name, [string]$script, [string]$user, [string]$password) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $script"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
    if ($password) {
        # 用 -User/-Password 就不能再传 -Principal，两者属于不同参数集
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
            -User $user -Password $password | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal | Out-Null
    }
    Start-ScheduledTask -TaskName $name
}
Register-LongRunning 'RoadModelProxy' 'C:\road\bin\run-proxy.ps1' '' ''
Grant-BatchLogon "$env:COMPUTERNAME\$ServiceUser"
Register-LongRunning 'RoadChat' 'C:\road\bin\run-chat.ps1' $ServiceUser $servicePassword

Step 'Caddy 反向代理'
$caddyDir = 'C:\road\caddy'
if (-not (Test-Path (Join-Path $caddyDir 'caddy.exe'))) {
    New-Item -ItemType Directory -Force -Path $caddyDir | Out-Null
    $release = Invoke-RestMethod 'https://api.github.com/repos/caddyserver/caddy/releases/latest' -TimeoutSec 30
    $asset = $release.assets | Where-Object { $_.name -like '*windows_amd64.zip' } | Select-Object -First 1
    $zip = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest $asset.browser_download_url -OutFile $zip -TimeoutSec 300
    Expand-Archive -Path $zip -DestinationPath $caddyDir -Force
}

$lines = @()
if ($UseHttps) {
    if ($Domain) {
        $lines += "$Domain {"
        $lines += "    reverse_proxy 127.0.0.1:$ChatPort {"
        $lines += '        flush_interval -1'
        $lines += '    }'
        $lines += '}'
    }
    $lines += ':8443 {'
    $lines += '    tls internal'
    $lines += "    reverse_proxy 127.0.0.1:$ChatPort {"
    $lines += '        flush_interval -1'
    $lines += '    }'
    $lines += '}'
} else {
    # 纯 HTTP：不写主机名，避免 Caddy 自动跳 HTTPS；域名与 IP 都走同一个端口
    $lines += ":$HttpPort {"
    $lines += "    reverse_proxy 127.0.0.1:$ChatPort {"
    $lines += '        flush_interval -1'
    $lines += '    }'
    $lines += '}'
}
Set-Content -Path 'C:\road\caddy\Caddyfile' -Encoding utf8 -Value $lines
& 'C:\road\caddy\caddy.exe' validate --config 'C:\road\caddy\Caddyfile' --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddyfile 校验失败' }

Step '启动 Caddy'
if (Get-ScheduledTask -TaskName 'RoadCaddy' -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName 'RoadCaddy' -Confirm:$false
}
$action = New-ScheduledTaskAction -Execute 'C:\road\caddy\caddy.exe' -Argument 'run --config C:\road\caddy\Caddyfile'
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'RoadCaddy' -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName 'RoadCaddy'

Step '启动自检'
$healthy = $false
$deadline = (Get-Date).AddSeconds(40)
do {
    Start-Sleep -Seconds 2
    try {
        $state = Invoke-RestMethod "http://127.0.0.1:$ChatPort/api/health" -TimeoutSec 3
        if ($state.ok) { $healthy = $true; break }
    } catch { }
} while ((Get-Date) -lt $deadline)

if (-not $healthy) {
    $info = Get-ScheduledTaskInfo -TaskName 'RoadChat' -ErrorAction SilentlyContinue
    Write-Host "聊天服务 40 秒内没起来（LastTaskResult=$($info.LastTaskResult)）" -ForegroundColor Red
    $runLog = Join-Path $WorkDir 'logs\chat-run.log'
    if (Test-Path $runLog) {
        Write-Host "--- $runLog ---" -ForegroundColor DarkYellow
        Get-Content $runLog -Tail 20
    } else {
        Write-Host '没有运行日志：任务可能根本没启动，检查「上次运行结果」与 roadchat 的登录权限。' -ForegroundColor DarkYellow
    }
} else {
    Write-Host '聊天服务已就绪。' -ForegroundColor Green
}

Write-Host @"

已启动。检查：
  Invoke-RestMethod http://127.0.0.1:$ChatPort/api/health
  Get-ScheduledTask -TaskName RoadChat,RoadModelProxy,RoadCaddy | Select TaskName,State
$(if ($UseHttps) { "  试用地址： https://<公网IP>:8443/   （自签证书，浏览器会提示不安全）" } else { "  地址： http://<公网IP>:$HttpPort/   （纯 HTTP；口令与内容在链路上是明文；并发上限 $MaxVisitors 人）" })
$(if ($Domain) { if ($UseHttps) { "  域名地址： https://$Domain/   （Caddy 自动申请证书，需要 80 端口可达）" } else { "  域名地址： http://${Domain}:$HttpPort/   （需要控制台放行该端口；用 80 需备案）" } })
完成后再跑 acceptance.ps1。
"@ -ForegroundColor Green
