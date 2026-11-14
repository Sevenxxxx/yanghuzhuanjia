#Requires -RunAsAdministrator
<#
  一次性初始化 Windows Server 2022（轻量应用服务器）。
  装 Node 24、Python 3.12、dsh、Python 依赖；建目录与专用账户；收紧 ACL。
  用法：在管理员 PowerShell 里执行
      Set-ExecutionPolicy -Scope Process Bypass -Force
      .\bootstrap-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$AppDir = 'C:\road\app',
    [string]$SpecDir = 'C:\road\specs',
    [string]$WorkDir = 'C:\road\work',
    [string]$EtcDir = 'C:\road\etc',
    [string]$NodeGlobal = 'C:\road\node-global',
    [string]$ServiceUser = 'roadchat'
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

if ($Deploy) {
    if ($Deploy.paths.app) { $AppDir = $Deploy.paths.app }
    if ($Deploy.paths.specs) { $SpecDir = $Deploy.paths.specs }
    if ($Deploy.paths.work) { $WorkDir = $Deploy.paths.work }
    if ($Deploy.paths.etc) { $EtcDir = $Deploy.paths.etc }
    if ($Deploy.paths.node_global) { $NodeGlobal = $Deploy.paths.node_global }
    if ($Deploy.service_user) { $ServiceUser = $Deploy.service_user }
}

function Step([string]$text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = ($machine, $user, $NodeGlobal) -join ';'
}

Step '目录'
foreach ($dir in @($AppDir, $SpecDir, $WorkDir, $EtcDir, $NodeGlobal, 'C:\road\bin', 'C:\road\logs')) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Step 'Node 24（dsh 要求 >= 24.9，Node 20 已停止维护）'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    $index = Invoke-RestMethod 'https://nodejs.org/dist/index.json' -TimeoutSec 30
    $lts = $index | Where-Object { $_.version -match '^v24\.' -and $_.lts } | Select-Object -First 1
    $msi = Join-Path $env:TEMP "node-$($lts.version)-x64.msi"
    Write-Host "下载 $($lts.version)"
    Invoke-WebRequest "https://nodejs.org/dist/$($lts.version)/node-$($lts.version)-x64.msi" -OutFile $msi -TimeoutSec 300
    Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait
    Refresh-Path
}
Write-Host "node $(node --version)"

Step 'Python 3.12'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    $html = (Invoke-WebRequest 'https://www.python.org/ftp/python/' -UseBasicParsing -TimeoutSec 30).Content
    $versions = [regex]::Matches($html, 'href="(3\.12\.\d+)/"') | ForEach-Object { [version]$_.Groups[1].Value }
    $latest = ($versions | Sort-Object -Descending | Select-Object -First 1).ToString()
    $exe = Join-Path $env:TEMP "python-$latest-amd64.exe"
    Write-Host "下载 Python $latest"
    Invoke-WebRequest "https://www.python.org/ftp/python/$latest/python-$latest-amd64.exe" -OutFile $exe -TimeoutSec 300
    Start-Process $exe -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1' -Wait
    Refresh-Path
}
Write-Host "python $(python --version 2>&1)"

Step 'Python 依赖（规范原页渲染、照片）'
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pymupdf pillow

Step 'dsh（装到独立 prefix，避免只有管理员账户能看到）'
$env:npm_config_prefix = $NodeGlobal
npm install -g @deepseek-ai/dsh
if ($LASTEXITCODE -ne 0) { throw 'dsh 安装失败' }
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($machinePath -notlike "*$NodeGlobal*") {
    [Environment]::SetEnvironmentVariable('Path', "$machinePath;$NodeGlobal", 'Machine')
}
Refresh-Path
Write-Host "dsh $(dsh --version)"

Step "服务账户 $ServiceUser"
if (-not (Get-LocalUser -Name $ServiceUser -ErrorAction SilentlyContinue)) {
    $alphabet = (48..57) + (65..90) + (97..122)
    $password = -join (1..28 | ForEach-Object { [char]($alphabet | Get-Random) })
    New-LocalUser -Name $ServiceUser -Password (ConvertTo-SecureString $password -AsPlainText -Force) `
        -PasswordNeverExpires -UserMayNotChangePassword -Description 'road maintenance chat service' | Out-Null
    Set-Content -Path (Join-Path $EtcDir "$ServiceUser-password.txt") -Value $password -Encoding utf8
    Write-Host "已创建，口令存在 $EtcDir\$ServiceUser-password.txt（注册任务时用）"
} else {
    Write-Host '账户已存在，跳过'
}

Step 'ACL：工作目录可写，程序与规范库只读'
icacls $WorkDir /grant "${ServiceUser}:(OI)(CI)M" | Out-Null
foreach ($readonlyDir in @($AppDir, $SpecDir)) {
    icacls $readonlyDir /grant "${ServiceUser}:(OI)(CI)RX" | Out-Null
}

Step '防火墙'
function Ensure-Rule([string]$name, [int]$port) {
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow | Out-Null
    }
}
Ensure-Rule 'RoadChat 8443（试用）' 8443
Ensure-Rule 'RoadChat 80（HTTP）' 80
Ensure-Rule 'RoadChat 443（域名）' 443

Write-Host @"

系统层完成。接下来：
  1. 把仓库放到 $AppDir，规范库放到 $SpecDir\guifanchaxun（含 guifansrc 与 library_data）
  2. 仓库根目录的 deploy.json 已填好（password / api_key / domain 都在那里）
  3. 管理员 PowerShell 执行 .\install-chat.ps1
  4. 执行 .\acceptance.ps1 过门槛
"@ -ForegroundColor Green
