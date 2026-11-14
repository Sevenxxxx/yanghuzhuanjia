# 服务器端脚本（Windows Server 2022）

第一次部署按 [部署指南](../../../docs/部署指南-Windows服务器.md) 一步步做；这里是脚本清单。

| 脚本 | 作用 | 何时跑 |
|---|---|---|
| [bootstrap-windows.ps1](bootstrap-windows.ps1) | 校验 Node（服务器自备）、装 Python 3.12 / Git / PyMuPDF / Pillow；建目录、建 `roadchat` 账户、收紧 ACL、放行防火墙 | 新机器一次 |
| [install-chat.ps1](install-chat.ps1) | 写配置、生成启动脚本、注册三个计划任务（聊天 / 代理 / Caddy）、装 Caddy 并校验 | 每次换 key、改域名或重装 |
| [acceptance.ps1](acceptance.ps1) | 上线门槛自检（程序、工具、服务、权限、密钥、防火墙） | 每次部署后，全绿才发口令 |
| [service.ps1](service.ps1) | `status` / `start` / `stop` / `restart`，按依赖顺序启停并清理残留运行时 | 日常运维 |
| [proxy.patch.yml](proxy.patch.yml) | 让 dsh 走本地模型代理的 profile patch | 由 `roadchat.env` 引用 |
| [onboarding.md](onboarding.md) | 发给同事的一页说明 | 上线后 |

架构与取舍见 [ADR 0005](../../../docs/decisions/0005-server-deployment.md)。

> 部署目标只有 Windows。如果以后改回 Linux，需要重做这一层脚本（systemd / 反向代理 / 证书）。
