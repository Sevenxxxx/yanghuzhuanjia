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

if ($Deploy) {
    if ($Deploy.paths.app) { $AppDir = $Deploy.paths.app }
    if ($Deploy.paths.work) { $WorkDir = $Deploy.paths.work }
    if ($Deploy.paths.etc) { $EtcDir = $Deploy.paths.etc }
    if ($Deploy.paths.specs) { $SpecDir = $Deploy.paths.specs }
    if ($Deploy.service_user) { $ServiceUser = $Deploy.service_user }
    if ($Deploy.domain) { $Domain = $Deploy.domain }
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
    spec_skill           = "$SpecDir\guifanchaxun\tools\guifan-chaxun"
    tool_timeout_seconds = 45
    privacy_default      = 'restricted'
}
Set-Content -Path (Join-Path $EtcDir 'config.json') -Value ($config | ConvertTo-Json) -Encoding utf8

Set-Content -Path (Join-Path $EtcDir 'roadchat.env') -Encoding utf8 -Value @(
    'DEEPSEEK_API_KEY=proxy-held'
    "ROAD_CHAT_PATCH=$EtcDir\proxy.patch.yml"
    "ROAD_EXPERT_CONFIG=$EtcDir\config.json"
    "ROAD_CHAT_PASSWORD=$GatePassword"
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

Step '启动脚本'
Set-Content -Path 'C:\road\bin\run-chat.ps1' -Encoding utf8 -Value @"
`$ErrorActionPreference = 'Stop'
Get-Content '$EtcDir\roadchat.env' | ForEach-Object {
    if (`$_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1].Trim(), `$matches[2].Trim(), 'Process') }
}
Set-Location '$AppDir'
& python -X utf8 '$AppDir\scripts\p3\chat\app.py' --host 127.0.0.1 --port $ChatPort --home '$WorkDir'
"@
Set-Content -Path 'C:\road\bin\run-proxy.ps1' -Encoding utf8 -Value @"
`$ErrorActionPreference = 'Stop'
Get-Content '$EtcDir\proxy.env' | ForEach-Object {
    if (`$_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1].Trim(), `$matches[2].Trim(), 'Process') }
}
& python -X utf8 '$AppDir\scripts\p3\proxy\model_proxy.py' --port $ProxyPort --upstream https://api.deepseek.com/anthropic --usage-log 'C:\road\logs\usage.log'
"@

Step '计划任务'
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
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Password -RunLevel Limited
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal -User $user -Password $password | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal | Out-Null
    }
    Start-ScheduledTask -TaskName $name
}
Register-LongRunning 'RoadModelProxy' 'C:\road\bin\run-proxy.ps1' '' ''
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

Write-Host @"

已启动。检查：
  Invoke-RestMethod http://127.0.0.1:$ChatPort/api/health
  Get-ScheduledTask -TaskName RoadChat,RoadModelProxy,RoadCaddy | Select TaskName,State
$(if ($UseHttps) { "  试用地址： https://<公网IP>:8443/   （自签证书，浏览器会提示不安全）" } else { "  地址： http://<公网IP>:$HttpPort/   （纯 HTTP；口令与内容在链路上是明文）" })
$(if ($Domain) { if ($UseHttps) { "  域名地址： https://$Domain/   （Caddy 自动申请证书，需要 80 端口可达）" } else { "  域名地址： http://${Domain}:$HttpPort/   （需要控制台放行该端口；用 80 需备案）" } })
完成后再跑 acceptance.ps1。
"@ -ForegroundColor Green
