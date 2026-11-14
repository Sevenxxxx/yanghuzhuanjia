# Windows Server 2022 部署手册（备选路径，已是当前选择）

Linux 那套（`bootstrap-linux.sh` / `install-app.sh`）在 Windows 上不能用；这里是对应的三支脚本。
架构与安全取舍与 Linux 相同，见 [ADR 0005](../../../docs/decisions/0005-server-deployment.md)。

## 为什么可以选 Windows

- 整个项目本来就跑在 Windows 上，`app.py` 的 Windows 分支（`cmd /c`、`taskkill /T`）是原生路径；
- `guifanchaxun` 是原生 Windows 项目，不需要赌 Linux 兼容性；
- 代价：内存更吃紧、服务托管要用计划任务、证书要靠 Caddy 而不是 certbot。

## 三支脚本

| 脚本 | 作用 | 何时跑 |
|---|---|---|
| [bootstrap-windows.ps1](bootstrap-windows.ps1) | 装 Node 24、Python 3.12、dsh、PyMuPDF/Pillow；建目录、建 `roadchat` 账户、收紧 ACL、放行防火墙 | 新机器一次 |
| [install-chat.ps1](install-chat.ps1) | 写配置、生成启动脚本、注册三个计划任务（聊天/代理/Caddy）、装 Caddy 并校验配置 | 每次换 key / 改域名 / 重装 |
| [acceptance.ps1](acceptance.ps1) | 上线门槛自检（程序、工具、服务、权限、密钥） | 每次部署后 |

## 步骤

```powershell
# 0. 先填配置：仓库根的 deploy.example.json 复制成 deploy.json
#    password / api_key / domain 都在里面；deploy.json 不会提交
Copy-Item deploy.example.json deploy.json
notepad deploy.json

# 以管理员身份打开 PowerShell
Set-ExecutionPolicy -Scope Process Bypass -Force

# 1. 系统层（一次）
cd C:\road\server
.\bootstrap-windows.ps1

# 2. 放仓库与规范库
#    C:\road\app                ← 本项目（含 .agents/skills 与 data/）
#    C:\road\specs\guifanchaxun ← 工具 + guifansrc + library_data

# 3. 配置 + 服务
.\install-chat.ps1   # key、端口、域名、路径全部来自 deploy.json

# 4. 门槛
.\acceptance.ps1
```

全部 ✓ 之后，用 `https://<公网IP>:8443/` 试用（自签证书，浏览器提示不安全点继续）。
域名备案下来后，重跑 `.\install-chat.ps1`（先把 `deploy.json` 的 `domain` 填上），Caddy 自动申请证书。

## 目录与账户

| 路径 | 说明 |
|---|---|
| `C:\road\app` | 项目仓库，`roadchat` 只读 |
| `C:\road\specs\guifanchaxun` | 规范库，只读 |
| `C:\road\work` | 运行时数据（会话、咨询记录），`roadchat` 可写 |
| `C:\road\etc` | `config.json`、`roadchat.env`、`proxy.env`、`proxy.patch.yml` |
| `C:\road\bin` | `run-chat.ps1`、`run-proxy.ps1`（计划任务调它们） |
| `C:\road\logs` | 代理用量、运行日志 |
| `C:\road\node-global` | dsh 的全局安装目录（避免只有管理员可见） |

`roadchat` 是专用本地账户，没有管理员权限；真实 API key 只在 `proxy.env`，其 ACL 只给
Administrators 与 SYSTEM——agent 以 `roadchat` 运行，读不到。

## 服务怎么起的

三个计划任务，开机自启、失败后每分钟重试：

| 任务 | 以谁运行 | 跑什么 |
|---|---|---|
| `RoadChat` | `roadchat` | `run-chat.ps1` → `python app.py --host 127.0.0.1 --port 8095` |
| `RoadModelProxy` | SYSTEM | `run-proxy.ps1` → `model_proxy.py --port 8096` |
| `RoadCaddy` | SYSTEM | `caddy run --config C:\road\caddy\Caddyfile` |

查看状态：`Get-ScheduledTask -TaskName RoadChat,RoadModelProxy,RoadCaddy | Select TaskName,State`

## 已知坑（都踩过了）

1. **脚本必须存成 UTF-8 with BOM**。Windows PowerShell 5.1 读无 BOM 的文件会按 GBK 解码，
   中文会让引号错位、整份脚本解析失败。三支脚本已经是 BOM 版本；以后用记事本改完要另存为
   「UTF-8 带 BOM」。
2. **Node 必须 ≥ 24.9**：dsh 的 `engines` 写死，Node 20 装上也被拒；`bootstrap` 装的是 24。
3. **`dsh` 别用管理员身份装**：npm 全局默认装到 `%APPDATA%\npm`，`roadchat` 看不见；
   脚本装到 `C:\road\node-global` 并写进系统 PATH。
4. **不要用 `certbot`**：Windows 上没有可用路径，用 Caddy（自带 ACME）。
5. **RDP 3389 只在必要时开**，并限制来源 IP；`install-chat.ps1` 不会自动放开它。
6. 域名备案前，`:8443` + 自签证书可用；备案后再加域名块。
