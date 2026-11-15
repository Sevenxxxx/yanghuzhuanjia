# 部署指南：Windows Server 2022

按顺序做完这九步即可。预计 **1.5–2 小时**，其中一半是传 4.2GB 规范库。
每一步都写了「做完应该看到什么」，对不上就停下来看第 10 节排查。

架构与取舍见 [ADR 0005](decisions/0005-server-deployment.md)；脚本清单见
[server/README.md](../scripts/p3/server/README.md)。

---

## 0. 动手前先准备好这些

| 项目 | 说明 |
|---|---|
| 服务器公网 IP | 腾讯云控制台首页能看到 |
| 管理员密码 | 买的时候设置的；忘了就在控制台重置 |
| `deploy.json` | 本机仓库根目录，**`api_key` 已填真实值**（`password` 默认 `yhg`） |
| 规范库 | 本机的 `guifanchaxun` 目录，含 `guifansrc`（3.79GB）与 `library_data`（0.42GB） |
| 上传通道 | 代码走 git clone；`deploy.json` 与 4.2GB 数据用远程桌面的磁盘映射（见第 2 节） |

先确认本机这两项：

```powershell
Test-Path .\deploy.json                          # True
(Get-Content .\deploy.json -Raw | ConvertFrom-Json).api_key   # 以 sk- 开头
```

---

## 1. 打开控制台防火墙（两层，都要开）

先搞清楚哪个端口是干什么的——**8091 是你本机开发用的，服务器上不用它**：

| 端口 | 在哪里 | 干什么 | 要不要对外 |
|---|---|---|---|
| 8091 | 你本机 | 本机聊天页（`http://192.168.1.5:8091/`） | 与服务器无关 |
| 8095 | 服务器内部 | 聊天服务本体（只听 `127.0.0.1`） | **不对外**，脚本默认 |
| 8096 | 服务器内部 | 模型代理（只听 `127.0.0.1`，持有真 key） | **不对外** |
| **8443** | 对外 | **当前模式**：Caddy 的 HTTP 入口（`http_port`） | 要开 |
| 443 / 80 | 对外 | 以后切 HTTPS 时用（`https: true`） | 可以先不开 |

请求路径是：浏览器 → `http://IP:8443` → Caddy → `http://127.0.0.1:8095` → 聊天服务。
8095/8096 永远只在服务器内部。

> **当前是纯 HTTP**：`deploy.json` 里 `"https": false`。口令和咨询内容在链路上是明文，
> 只适合试用期、且别在对话里放涉密或个人信息。域名现在就能用：`http://你的域名:8443/`
> （DNS 解析到这台机器、控制台放行 8443 即可；用 80 才需要备案）。
> 备案下来后把 `https` 改成 `true`、`domain` 填好，重跑 `install-chat.ps1`，Caddy 会自动申请证书并
> 把地址变成 `https://你的域名/`（不带端口、无证书警告）。

腾讯云轻量有**自己的防火墙**，和 Windows 防火墙是两回事。先开控制台这一层：

| 端口 | 用途 | 建议 |
|---|---|---|
| 3389 | 远程桌面 | **只放行你自己的 IP**，不要 0.0.0.0/0 |
| 8443 | 试用地址（当前 HTTP 入口） | 放行全部，方便同事访问 |
| 443 | 以后 HTTPS 用 | 可以等切 HTTPS 再开 |

控制台路径：轻量应用服务器 → 你的实例 → 防火墙 → 添加规则。

**做完应该看到**：三条规则都在列表里，3389 的来源是你的 IP。

---

## 2. 连上服务器

控制台点「登录」→ 直接进网页终端；或本机 `mstsc` 输 IP 连远程桌面。

确认系统版本：

```powershell
(Get-CimInstance Win32_OperatingSystem).Caption   # 应含 Windows Server 2022
```

---

### 文件怎么传上去（三种方式，按需选）

**方式 1：远程桌面的驱动器映射（推荐，不用装任何软件）**

本机打开 `mstsc` → 输入 IP → 点「显示选项」→「本地资源」→「详细信息」→ 勾选「驱动器」→ 连接。
进入服务器后，打开「此电脑」，会多出一个 `\\tsclient\C` 之类的盘符，那就是**你本机的 C 盘**。
直接在里面复制粘贴文件即可，4GB 的规范库也走这条路。

**方式 2：剪贴板**

远程桌面默认共享剪贴板：本机复制文本，服务器里粘贴。适合 `deploy.json` 这种几十行的小文件。

**方式 3：WinSCP（可选，需要先在服务器上开 SSH）**

WinSCP 是**装在你本机**的图形化传输工具（像资源管理器，但是连远程机器），服务器上**不用装**。
但它走 SFTP（22 端口），而 Windows Server 2022 默认**没有启用** OpenSSH Server，所以要先在服务器上：

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-NetFirewallRule -DisplayName 'RoadChat SSH 22' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow
```

然后在**本机**装 WinSCP，主机填服务器 IP、用户名密码与远程桌面相同、端口 22、协议 SFTP。

> 只为了传两个文件的话，方式 1 更省事；方式 3 多了 22 端口的暴露面，用完可以把 sshd 停掉。

---

## 3. 系统初始化（约 5–15 分钟）

先跑初始化：它会装 Python 3.12 与 Git、校验 Node 版本（Node 由服务器自备）。

在服务器上以**管理员身份**打开 PowerShell，然后从本机传**两个文件**上去：

```
本机  scripts\p3\server\bootstrap-windows.ps1   →  C:\road\bootstrap-windows.ps1
本机  deploy.json（仓库根）                      →  C:\road\deploy.json
```

`deploy.json` 必须一起传：初始化要按里面的 `paths` 建桌面目录。脚本会先找自己同目录的
`deploy.json`，找不到再找仓库根的那份。

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd C:\road
.\bootstrap-windows.ps1
```

它会做：校验 Node（服务器自备）、装 Git、Python 3.12、PyMuPDF/Pillow；
建 `roadchat` 账户（口令写在 `C:\road\etc\roadchat-password.txt`）；收紧 ACL；放行 Windows 防火墙 80/443/8443；
最后做两项系统检查——给 `C:\road\work`、仓库目录、规范库目录加 Defender 排除，检查页面文件是否 ≥ 4GB（不够会提示怎么设）。

**做完应该看到**：

```
node v24.x.x（或你自备的更高版本）
python Python 3.12.x
git version 2.x
系统层完成。接下来：...
```

注意：**这一步不装 dsh**，下一步单独装。

---

## 4. 安装 dsh（约 1 分钟，自己执行）

dsh 是官方 npm 包，装到**默认位置**即可（`%APPDATA%\npm`），不要装进 `C:\road`：

```powershell
npm install -g @deepseek-ai/dsh
dsh --version                      # 打印版本号即成功
Get-Command dsh | Select Source    # 默认在 C:\Users\<你>\AppData\Roaming\npm\dsh.cmd
```

> **包名别写错**：npm 上叫 `dsh` 的是另一个项目（"A shell written in JavaScript"），
> 我们的包是 **`@deepseek-ai/dsh`**。想锁版本就 `npm install -g @deepseek-ai/dsh@0.2.2-rc.1`。

- 必须 **Node ≥ 24.9**（第 3 步已装好）；
- 装完当前窗口就能用；新开的窗口因为系统 PATH 已包含该目录，也能找到；
- `install-chat.ps1` 会自动把它所在目录写进系统 PATH，并给 `roadchat` 读+执行权限
  （只给「穿越」上级目录的权限，不会让服务账户看见你的用户目录内容）。

**第一次对话会慢 10–20 秒**：服务在为该访问者生成 `road-sdk` profile 并启动运行时，
位置在 `C:\road\work\visitors\<访问者id>\home\profiles\road-sdk\`，之后就好了。

**装坏了怎么办**：

| 现象 | 处理 |
|---|---|
| `dsh` 不是内部或外部命令 | 重开 PowerShell；仍不行看 `%APPDATA%\npm\dsh.cmd` 在不在 |
| npm 卡住或网络错 | 重试；或加 `--registry=https://registry.npmjs.org` |
| 报 engines 不匹配 | `node -v` 必须 ≥ 24.9，否则回第 3 步 |

---


> **路径说明**：`deploy.json` 里的 `%USERPROFILE%` 会被脚本展开成当前用户目录，
> 所以两台机器可以用同一份配置。仓库与规范库放桌面时，脚本会自动给 `roadchat`
> 对上级目录的「穿越」权限（只穿越、不列目录），否则服务账户进不去桌面。
> 如果这台机器的桌面被重定向到别处，把 `paths` 直接写成实际绝对路径即可。

## 5. git clone 拉仓库（约 1 分钟）

仓库现在是**公开**的，直接 clone，不需要任何凭证：

```powershell
git clone https://github.com/Sevenxxxx/yanghuzhuanjia.git "$env:USERPROFILE\Desktop\yanghuzhuanjia"

Test-Path "$env:USERPROFILE\Desktop\yanghuzhuanjia\scripts\p3\chat\app.py"    # True
```

> 仓库放在桌面；运行时数据（会话、咨询记录）仍在 `C:\road\work`，两者分开。

> 如果哪天仓库改回私有，用 fine-grained PAT（只勾这个仓库、权限只给 `Contents: Read`）：
> `git clone https://<你的PAT>@github.com/Sevenxxxx/yanghuzhuanjia.git "$env:USERPROFILE\Desktop\yanghuzhuanjia"`

`deploy.json` **不在仓库里**（被 gitignore），clone 完必须补上。第 3 步已经把它放在
`C:\road\deploy.json`，直接复制过去最省事：

```powershell
Copy-Item C:\road\deploy.json "$env:USERPROFILE\Desktop\yanghuzhuanjia\deploy.json"
```

没有那份的话，用下面任一方式补：

- **A**：用远程桌面磁盘映射，把本机的 `deploy.json` 拖到 `桌面\yanghuzhuanjia\deploy.json`；
- **B**：服务器上直接写，把 `api_key` 换成真实值（注意 PowerShell 里反斜杠要写两个）：

```powershell
notepad "$env:USERPROFILE\Desktop\yanghuzhuanjia\deploy.json"
```

粘贴下面内容，保存成 **UTF-8**：

```json
{
  "password": "yhg",
  "api_key": "sk-替换成你的 key",
  "domain": "你的域名",
  "https": false,
  "http_port": 8443,
  "service_user": "roadchat",
  "paths": {
    "app": "%USERPROFILE%\\Desktop\\yanghuzhuanjia",
    "specs": "%USERPROFILE%\\Desktop\\guifanchaxun",
    "work": "C:\\road\\work",
    "etc": "C:\\road\\etc"
  }
}
```

```powershell
Test-Path "$env:USERPROFILE\Desktop\yanghuzhuanjia\deploy.json"    # True
```

---

## 6. clone 规范工具，再补两个数据目录（约 40–90 分钟）

规范工具也有远程仓库，先 clone：

```powershell
git clone https://github.com/Sevenxxxx/guifanchaxun.git "$env:USERPROFILE\Desktop\guifanchaxun"
```

但 `guifansrc\`（3.79GB）和 `library_data\`（0.42GB）**都不在 git 里**（被 gitignore），
必须另外传（用第 2 节的远程桌面磁盘映射）：

```
本机 guifanchaxun\guifansrc      →  %USERPROFILE%\Desktop\guifanchaxun\guifansrc
本机 guifanchaxun\library_data  →  %USERPROFILE%\Desktop\guifanchaxun\library_data
```

**建议**：这一步和第 7、8 步并行——传大文件不占终端，另开窗口继续往下做。

传完给规范库补一条 Defender 排除（`bootstrap` 执行时这个目录还不存在，会被跳过）：

```powershell
Add-MpPreference -ExclusionPath "$env:USERPROFILE\Desktop\guifanchaxun"
```

> 如果 `guifanchaxun` 仓库不是公开的，clone 会要求凭证，用同前的 fine-grained PAT 即可。

> 以后更新：`cd "$env:USERPROFILE\Desktop\yanghuzhuanjia"; git pull`，再
> `cd scripts\p3\server; .\service.ps1 restart`（见第 12 节）。数据目录不在 git 里，不会被覆盖。

---

## 7. 改规范库自己的配置（1 分钟，**必做**）

打开 `%USERPROFILE%\Desktop\guifanchaxun\tools\guifan-chaxun\config.json`，把两个路径改成服务器上的：

```json
{
  "library_dir": "C:\\Users\\<你的用户名>\\Desktop\\guifanchaxun\\guifansrc",
  "data_dir": "C:\\Users\\<你的用户名>\\Desktop\\guifanchaxun\\library_data"
}
```

其它字段（`tesseract_cmd` 等）保持原样——我们不走 OCR，路径不存在也不影响。

> 这里必须写**真实绝对路径**（`C:\Users\Administrator\Desktop\...`），这个工具不展开 `%USERPROFILE%`；
> 我们自己的 `deploy.json` 则可以写 `%USERPROFILE%`，由脚本展开。

**做完应该看到**：文件里两个路径变成 `C:\Users\Administrator\Desktop\guifanchaxun\...`（按你的用户名）。

---

## 8. 装服务并启动（约 3–5 分钟）

```powershell
cd "$env:USERPROFILE\Desktop\yanghuzhuanjia\scripts\p3\server"
.\install-chat.ps1
```

它从 `deploy.json` 读 `api_key`、`password`、`domain`、端口与路径，然后：
写 `C:\road\etc\` 四个配置 → 生成两个启动脚本 → 注册三个计划任务 → 下载 Caddy → 校验 Caddyfile → 启动。

> **Caddy 是什么**：一个用 Go 写的 Web 服务器兼反向代理，和 nginx 干同一件事，但单文件、
> 自带 HTTPS（自动申请与续期证书）。选它是因为 Windows 上 nginx + certbot 那套很别扭：
> certbot 没有官方 Windows 支持，而 Caddy 把 ACME 内置了。它在这里只做三件事：
> ① 对外入口（当前 HTTP 8443；切 HTTPS 后走 443）；② 把请求转给只听回环的聊天服务（8095）；
> ③ 流式回答不缓冲（配置里的 `flush_interval -1`）。
> 安装位置 `C:\road\caddy\caddy.exe`，配置 `C:\road\caddy\Caddyfile`，由计划任务 `RoadCaddy` 守着。

**做完应该看到**：

```
Caddyfile 校验通过
已启动。检查：
  地址： http://<公网IP>:8443/   （纯 HTTP；口令与内容在链路上是明文）
```

> 如果 `deploy.json` 里 `https: true`，这里打印的会是 `https://...:8443/`（自签证书）或域名地址。

马上验证一下：

```powershell
Invoke-RestMethod http://127.0.0.1:8095/api/health
Get-ScheduledTask -TaskName RoadChat,RoadModelProxy,RoadCaddy | Select TaskName,State
```

**期望**：health 返回 `ok: True`；三个任务都是 `Running`。`online` 是当前占用的在线名额
（上限 8），`visitors` 是见过的浏览器数，两者不必相等。

---

## 9. 过门槛（约 1 分钟，**全绿才继续**）

```powershell
.\acceptance.ps1
```

检查项：程序版本、`road.py --doctor`、一条规范检索、前端健康、代理转发、三个任务、目录权限、真实 key 不在前端 env、日志无 key、防火墙。

**期望最后一行**：`结果：N 项全部通过`。

任何一项 `[!!]` 都不要把口令发出去，按第 10 节排查。

---

## 10. 试用与交付

1. 浏览器打开 `http://<公网IP>:8443/`（有域名就用 `http://你的域名:8443/`）；
2. 输入 `deploy.json` 里的口令 → 进入聊天页；
3. 发一句话确认能回答；发一张照片确认能识别；
4. 把 [onboarding.md](../scripts/p3/server/onboarding.md) 填上地址发给同事。

想切 HTTPS 时（备案下来、或你愿意先让浏览器提示证书不安全）：

```powershell
# 1) deploy.json 里把 "https" 改成 true，domain 填好
# 2) 进脚本目录重跑安装
cd "$env:USERPROFILE\Desktop\yanghuzhuanjia\scripts\p3\server"
.\install-chat.ps1
```

Caddy 会自动完成 ACME 签发，之后同事改用 `https://你的域名/`（不带端口、无证书警告），
原来的 8443 自签入口仍然可用作备用。

---

## 11. 出问题怎么查

| 现象 | 先看什么 | 常见原因 |
|---|---|---|
| 浏览器连不上 8443 | 控制台防火墙 | 控制台没放行 8443（Windows 防火墙脚本已放行） |
| RoadChat 日志报 `Set-Location` 拒绝访问 | 安装时输出的「服务账户可访问仓库」是否为 OK | 桌面被重定向或 ACL 未生效；重跑 install-chat 看自检结果 |
| 页面能开但登录后一直转圈 | `Get-ScheduledTaskInfo -TaskName RoadChat` | 任务没起来；看 `C:\road\logs` 与任务「上次运行结果」 |
| 回答是「模型没有返回内容」 | `Get-ScheduledTask -TaskName RoadModelProxy` | 代理没起，或 `proxy.env` 的 key 不对 |
| `bootstrap` 报找不到 node | 重开 PowerShell | 新装的 PATH 只对新进程生效 |
| 脚本一打开就报语法错、中文乱码 | 文件是否 BOM | 用记事本另存为「UTF-8 带 BOM」，否则 5.1 按 GBK 解码 |
| 规范检索失败 | `%USERPROFILE%\Desktop\guifanchaxun\tools\guifan-chaxun\config.json` | 第 7 步的两个路径没改 |
| 提示 `dsh` 需要更高 Node | `node -v` | 必须 ≥ 24.9；重跑 bootstrap |
| 8443 证书告警 | 只有 `https: true` 时才有 | 自签证书的正常提示；域名证书生效后消失 |
| 改了 `http_port` 后打不开 | 控制台防火墙 + `acceptance.ps1` | 新端口要同时在控制台和 Windows 防火墙放行 |
| 8443 打不开但任务显示 Running | `C:\road\caddy\caddy.exe validate --config C:\road\caddy\Caddyfile` | 端口被占、Caddyfile 写坏；也可以在控制台手动 `caddy run` 看报错 |

看日志：

```powershell
Get-ChildItem C:\road\logs
Get-Content C:\road\logs\usage.log -Tail 20      # 代理调用记录
Get-Content C:\road\logs\*.log -Tail 50
```

重启某个服务：

```powershell
Stop-ScheduledTask -TaskName RoadChat; Start-ScheduledTask -TaskName RoadChat
```

---

## 12. 启动、停止与查看状态

服务由三个计划任务组成，**开机自动启动**，平时不用管：

| 任务 | 作用 | 启动顺序 |
|---|---|---|
| `RoadModelProxy` | 模型代理（持有真实 key） | 1 |
| `RoadChat` | 聊天服务（127.0.0.1:8095） | 2 |
| `RoadCaddy` | 对外入口（HTTP 8443 / 以后 HTTPS 443） | 3 |

### 用脚本操作（推荐）

```powershell
cd C:\Users\<你>\Desktop\yanghuzhuanjia\scripts\p3\server

.\service.ps1 status     # 看三个任务、健康检查、运行时进程与内存
.\service.ps1 stop       # 反序停止，并清理残留的 dsh 运行时
.\service.ps1 start      # 正序启动，等健康检查通过
.\service.ps1 restart    # 先停后起
```

`status` 会打印类似：

```
== 计划任务 ==
  RoadModelProxy   Running    上次运行 ... 结果 0
  RoadChat         Running    上次运行 ... 结果 0
  RoadCaddy        Running    上次运行 ... 结果 0

== 健康检查 ==
  聊天服务 ok=True 在线=1/8 访问者=3 就绪=1 会话=5
  模型代理 HTTP 200

== dsh 运行时 ==
  pid 4321  194 MB
```

### 不想用脚本时的手动命令

```powershell
# 停止（顺序：入口 → 聊天 → 代理）
Stop-ScheduledTask -TaskName RoadCaddy
Stop-ScheduledTask -TaskName RoadChat
Stop-ScheduledTask -TaskName RoadModelProxy

# 启动（顺序反过来）
Start-ScheduledTask -TaskName RoadModelProxy
Start-ScheduledTask -TaskName RoadChat
Start-ScheduledTask -TaskName RoadCaddy

# 单独看某一个
Get-ScheduledTask -TaskName RoadChat | Select State
Get-ScheduledTaskInfo -TaskName RoadChat
```

> 任务停止是「直接终止进程」，聊天服务的 dsh 子进程可能残留，表现为
> `Get-Process node` 里还有几个。`service.ps1 stop` 会自动清；手动停的话用
> `Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*--profile road-sdk*' }` 找出来再 `Stop-Process`。

### 关掉开机自启（维护时）

```powershell
Disable-ScheduledTask -TaskName RoadChat,RoadModelProxy,RoadCaddy
# 恢复
Enable-ScheduledTask  -TaskName RoadChat,RoadModelProxy,RoadCaddy
```

**停止不会丢数据**：会话与咨询记录在 `C:\road\work`，上传的照片也在那里；
重新 `start` 后访问者会重新建立运行时（第一次对话慢 10–20 秒）。

### 需要重启整个服务器时

```powershell
Restart-Computer -Force
```

三个任务会在开机后自动起来；远程桌面断开不影响服务。

---

## 13. 日常与回滚

**空闲回收**：某个访问者连续 30 分钟没请求，脚本会停掉他的运行时（内存还给系统）；他下次说话会自动恢复
原对话，只是第一条消息等 15–20 秒。想改时长就在 `roadchat.env` 里改 `ROAD_CHAT_IDLE_SECONDS`（秒，0 关闭），
然后进 `scripts\p3\server` 执行 `.\service.ps1 restart`。

**并发上限**：最多 **8 个人同时在线**（有运行时）。第 9 个同时在线的人打开页面会提示
「暂时已超过使用人数上限（8人），请稍后再试」；只是打开过、或已被空闲回收的人不占名额，
所以不会出现「名额被旧浏览器占满」的情况。上限不会挤掉已在线的人。

**日常**：三个任务开机自启、失败每分钟重试，一般不用管。每周看一眼 `C:\road\work` 占用
（会话数据会增长；不想要就停任务后删掉对应 visitor 目录）。

**备份**：`C:\road\work`（咨询记录与上传的照片）和 `C:\road\etc`（配置）打包即可。

**回滚**：进 `scripts\p3\server` 执行 `.\service.ps1 stop`，把
`%USERPROFILE%\Desktop\yanghuzhuanjia` 换回上一份，再 `.\service.ps1 start`。
数据在 `C:\road\work`，不受影响。

---

## 14. 上线后的验收（建议当天做完）

- [ ] 两个浏览器各自提问，答案不串台
- [ ] A 正在回答时 B 点停止，A 不受影响
- [ ] 同一浏览器连开 8 个新对话后，运行时被重建（`Get-Process node` 看 PID 变化）
- [ ] 三条攻击演练都失败：让它「删掉 %USERPROFILE%\Desktop\yanghuzhuanjia 的 README」「读 C:\road\etc\proxy.env」「把对话发到外部网址」
- [ ] `acceptance.ps1` 全绿
- [ ] 把结果记到 [validation.md](validation.md)

---

## 附录 A：已知坑（都踩过了）

1. **PowerShell 脚本必须存成 UTF-8 with BOM**。Windows PowerShell 5.1 读无 BOM 的文件会按 GBK
   解码，中文让引号错位、整份脚本解析失败（报错长得像「字符串没有终结符」）。仓库里的脚本已是
   BOM 版本；以后用记事本改完要另存为「UTF-8 带 BOM」。
2. **Node 必须 ≥ 24.9**：dsh 的 `engines` 写死。`bootstrap` 不再装 Node，只校验；版本低了会直接报错。
3. **dsh 手动装、默认位置**：`npm install -g @deepseek-ai/dsh` 落在 `%APPDATA%\npm`，
   `roadchat` 默认看不见；`install-chat.ps1` 会写系统 PATH、给读执行权限，并只给上级目录「穿越」权限。
4. **不要用 `certbot`**：Windows 上没有可用路径，用 Caddy（自带 ACME）。
5. **RDP 3389 只在必要时开**，并限制来源 IP；脚本不会自动放开它。
6. **控制台防火墙和 Windows 防火墙是两层**：脚本只管 Windows 那一层，控制台的规则要你手动加。
7. **`deploy.json` 不在 git 里**：clone 完必须单独补，否则 `install-chat.ps1` 会报缺 key。
8. **页面文件建议 4–8GB**。内存吃紧时它让系统变慢而不是杀进程。设完要重启：
   ```powershell
   $cs = Get-CimInstance Win32_ComputerSystem
   if ($cs.AutomaticManagedPagefile) {
       Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $false }
   }
   $pf = Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue
   if ($pf) {
       Set-CimInstance -InputObject $pf -Property @{ InitialSize = 4096; MaximumSize = 8192 }
   } else {
       New-CimInstance -ClassName Win32_PageFileSetting `
           -Property @{ Name = 'C:\pagefile.sys'; InitialSize = 4096; MaximumSize = 8192 }
   }
   Restart-Computer
   ```

---

## 附录 B：管理员自查入口（dsh 自带 Web）

这是**给你自己**检查服务器、管理文件用的，不是同事入口。同事继续用 `http://域名:8443/`。

1. RDP 进服务器，管理员 PowerShell；
2. 用自己的**管理 key**（和产品 key 分开，见下表）设进环境变量：

```powershell
$env:DEEPSEEK_API_KEY = 'sk-你的管理key'
dsh web --host 127.0.0.1 --port 3080
```

3. 它会打印一个带 token 的地址，在**服务器上的 Edge** 里打开 `http://127.0.0.1:3080/?token=...`；
4. 用完 `Ctrl+C` 关掉。

**三条规矩**

- 只绑 `127.0.0.1`。那个 token 地址等价于服务器的管理员 shell，**不要外发、不要截图**；
- 不要在界面里改 `C:\road\work`（同事的咨询数据）；
- 想从笔记本直接用：装 Tailscale，把 `--host` 换成 Tailscale 的 IP，走加密内网。

**两把 key 的分工**

| 用途 | key 放哪 | 谁读 |
|---|---|---|
| 产品（同事用） | `C:\road\etc\proxy.env`（ACL 仅管理员/SYSTEM） | `RoadModelProxy` |
| 你的 `dsh web` | `C:\Users\Administrator\.dsh\.credentials.yaml` 的 `refs.DEEPSEEK_API_KEY`，或用户环境变量 | 你自己启动的 dsh |

两把互不影响：轮换产品 key 只需改 `proxy.env` 并重启 `RoadModelProxy`；换管理 key 改凭据文件即可。
