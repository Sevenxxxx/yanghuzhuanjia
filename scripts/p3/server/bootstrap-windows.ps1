#Requires -RunAsAdministrator
<#
  一次性初始化 Windows Server 2022（轻量应用服务器）。
  校验 Node（服务器自备）、装 Python 3.12 与 Git、Python 依赖；建目录与专用账户；收紧 ACL；放行防火墙。
  dsh 不在这里装，见部署指南第 4 步（你自己用 npm 装到默认位置）。
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
    [string]$ServiceUser = 'roadchat'
)

$ErrorActionPreference = 'Stop'

function Step([string]$text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }
function Expand-DeployPath([string]$value) {
    if (-not $value) { return $value }
    return [Environment]::ExpandEnvironmentVariables($value).TrimEnd('\')
}

function Grant-Traverse([string]$target, [string]$user) {
    # 目标在某个用户目录下时，给「穿越」权限（不给列目录），否则服务账户进不去
    $profileRoot = [Environment]::GetFolderPath('UserProfile')
    if (-not $target.StartsWith($profileRoot, [StringComparison]::OrdinalIgnoreCase)) { return }
    $current = $profileRoot
    icacls $profileRoot /grant "${user}:(X)" | Out-Null
    $relative = $target.Substring($profileRoot.Length).TrimStart('\')
    $parts = $relative.Split('\')
    for ($i = 0; $i -lt $parts.Count - 1; $i++) {
        $current = Join-Path $current $parts[$i]
        if (Test-Path $current) { icacls $current /grant "${user}:(X)" | Out-Null }
    }
}


# 单独把脚本传到服务器时，deploy.json 放在它旁边；在仓库里跑则用仓库根那份
$ConfigPath = Join-Path $PSScriptRoot 'deploy.json'
if (-not (Test-Path $ConfigPath)) {
    $RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
    $ConfigPath = Join-Path $RepoRoot 'deploy.json'
}
if (Test-Path $ConfigPath) {
    $Deploy = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "使用配置：$ConfigPath" -ForegroundColor DarkGray
} else {
    $Deploy = $null
}

if ($Deploy) {
    if ($Deploy.paths.app) { $AppDir = Expand-DeployPath $Deploy.paths.app }
    if ($Deploy.paths.specs) { $SpecDir = Expand-DeployPath $Deploy.paths.specs }
    if ($Deploy.paths.work) { $WorkDir = Expand-DeployPath $Deploy.paths.work }
    if ($Deploy.paths.etc) { $EtcDir = Expand-DeployPath $Deploy.paths.etc }
    if ($Deploy.service_user) { $ServiceUser = $Deploy.service_user }
}
Write-Host "仓库：$AppDir"
Write-Host "规范库：$SpecDir"

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = ($machine, $user) -join ';'
}

Step '目录'
foreach ($dir in @($AppDir, $SpecDir, $WorkDir, $EtcDir, 'C:\road\bin', 'C:\road\logs')) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Step 'Node（服务器自备，只校验版本）'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw '找不到 node：请先装 Node 24（dsh 要求 >= 24.9），或自行恢复安装再跑本脚本'
}
$nodeVersion = [version]((node --version).TrimStart('v'))
if ($nodeVersion -lt [version]'24.9.0') {
    throw "Node 版本过低（$nodeVersion）：dsh 要求 >= 24.9，请先升级 Node"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw '找不到 npm：Node 安装不完整' }
Write-Host "node $(node --version) / npm $(npm --version)"

Step 'Python 3.12'
$needPython = $true
if (Get-Command python -ErrorAction SilentlyContinue) {
    try {
        $pyVersion = (& python -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $pyVersion -match '^3\.(12|1[3-9])$') { $needPython = $false }
    } catch { $needPython = $true }
}
if ($needPython) {
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

Step 'Git（后面用 git clone 拉仓库与规范工具）'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $release = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest' -TimeoutSec 30
    $asset = $release.assets | Where-Object { $_.name -match '^Git-.*-64-bit\.exe$' } | Select-Object -First 1
    if (-not $asset) { throw '找不到 Git for Windows 安装包' }
    $installer = Join-Path $env:TEMP $asset.name
    Write-Host "下载 $($asset.name)"
    Invoke-WebRequest $asset.browser_download_url -OutFile $installer -TimeoutSec 600
    Start-Process $installer -ArgumentList '/VERYSILENT /NORESTART /NOCANCEL /SP-' -Wait
    Refresh-Path
}
Write-Host "git $(git --version)"

Step 'Python 依赖（规范原页渲染、照片）'
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pymupdf pillow

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
    Grant-Traverse $readonlyDir $ServiceUser
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


Step '系统检查：Defender 排除与页面文件'
if (Get-Command Add-MpPreference -ErrorAction SilentlyContinue) {
    foreach ($exclusion in @($WorkDir, $AppDir)) {
        if (Test-Path $exclusion) {
            try {
                Add-MpPreference -ExclusionPath $exclusion -ErrorAction Stop
                Write-Host "Defender 已排除：$exclusion"
            } catch {
                Write-Host "Defender 排除失败（可能被篡改保护限制）：$exclusion" -ForegroundColor DarkYellow
            }
        }
    }
} else {
    Write-Host '未检测到 Windows Defender，跳过排除' -ForegroundColor DarkYellow
}

$pageFiles = Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue
$autoManaged = (Get-CimInstance Win32_ComputerSystem).AutomaticManagedPagefile
if ($pageFiles) {
    $totalMb = ($pageFiles | Measure-Object -Property AllocatedBaseSize -Sum).Sum
    $detail = ($pageFiles | ForEach-Object { "$($_.Name) $($_.AllocatedBaseSize)MB" }) -join '；'
    Write-Host "页面文件：$detail（自动管理：$autoManaged）"
    if ($totalMb -lt 4096) {
        Write-Host '页面文件小于 4GB：内存吃紧时容易被杀进程，建议按部署指南设为 4–8GB（需重启）' -ForegroundColor Yellow
    }
} else {
    Write-Host '没有检测到页面文件：内存吃紧时可能被杀进程，建议按部署指南设置 4–8GB（需重启）' -ForegroundColor Yellow
}

Write-Host @"

系统层完成。接下来：
  1. 把仓库放到 $AppDir，规范库放到 $SpecDir\guifanchaxun（含 guifansrc 与 library_data）
  2. 用 npm 装 dsh（部署指南第 4 步，默认位置即可；Node 用你服务器上已有的）
  3. git clone 仓库与规范工具，补 deploy.json 和两个数据目录
  4. 管理员 PowerShell 执行 .\install-chat.ps1
  5. 执行 .\acceptance.ps1 过门槛
"@ -ForegroundColor Green
