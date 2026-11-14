# ADR 0005：部署到私有服务器（一个地址、按访问者隔离运行时）

日期：2026-11-13。承接 [ADR 0003](0003-chat-frontend.md)：把纯聊天前端搬到私有服务器，让同事试用。

## 背景

用户要一个**地址**给同事用，而不是每人一个链接。同时明确两条硬要求：停止键不能影响别人；会话不能只增不减。v1 不做账号体系，先把「多人同时用」跑稳，账号级数据隔离留到 v2。

## 决定

1. **一个地址 + 一把共享口令**：nginx 反代，`auth_basic` 挡住陌生人；口令用 `htpasswd` 管理，换人改一行。
2. **按访问者隔离运行时**：服务端用 `rc_vid`（HttpOnly cookie，服务端下发）识别访问者；每人一个 `DshRuntime`，独立 `DSH_HOME`、独立 `LOCALAPPDATA`（因此咨询目录也分开）、独立子进程。
3. **停止只影响自己**：停止键重启该访问者的运行时并用 `session/resume` 修复被中断的轮次；其他访问者的运行时不受影响。
4. **不做空闲回收**（用户决定暂缓）：运行时在服务进程存活期间保留；用两个不需要判断空闲的回收点兜住增长——同一访问者累计 20 个新对话且空闲时重建运行时；每天 04:00 重启整个服务。
5. **真 key 不进 agent 环境**：新增本地模型代理（`scripts/p3/proxy/model_proxy.py`），真实 key 只在 root 属主的代理进程里；dsh 拿到占位 token，`DEEPSEEK_BASE_URL` 指向代理。
6. **写入面收敛**：仓库与规范库 root 所有、只读；`roadchat` 用户只能写 `/srv/road/work`；dsh 侧权限预设 `workspace-write` + `additionalWritableRoots=/srv/road/work`，无可用后端时 `SANDBOX_UNAVAILABLE` 失败关闭。
7. **配置在仓库外**：`ROAD_EXPERT_CONFIG` 指向 `/etc/road-chat/config.json`，不改 tracked 的示例文件。

## 安全边界（必须如实说明）

- 能保证：改不了仓库与系统文件、拿不到真实 API key、出网受主机防火墙限制。
- **不能**保证：agent 不执行命令、不读它权限内的文件。dsh 沙箱只约束**文件写入**，读取与网络不在其保证范围。
- v1 的访问者之间不是安全边界：同一 `roadchat` 用户下，agent 理论上能读到其他访问者的目录。真正的隔离在 v2（每账号独立 OS 用户/容器）。

## v2 触发与做法

触发：同事要求留存记录，或提出「别人不能看到我的东西」。做法：登录页 + 账户表（`hashlib.scrypt`、HMAC 签名 cookie），登录后请求转到该账户自己的服务实例（独立 OS 用户、独立 home/咨询目录/运行时/代理配额），nginx 退化为纯 TLS 入口。

## 验证方式

- 本机单测覆盖：池化（同 id 复用、不同 id 独立）、停止只影响自己、20 次重建、重建期间不重建。
- 服务器验收：两浏览器不串台、A 停止不影响 B、20 次重建、攻击演练三条、日志无 key。
- 未验证项在 [validation](../validation.md) 中逐条列出，不提前写成通过。

## 已知限制

- 内存随访问者人数线性增长（每个活跃运行时约 0.4–0.5GB），建议 ≤6 人、8GB 内存。
- 规范工具 `guifanchaxun` 只在 Windows 验证过，Linux 首次运行是首要风险。
- 记录默认 24 小时清理；不做保存与 Word 下载；不做按人计费。
- 夜间重启会中断当时正在跑的回答（04:00 通常无人使用）。

## 变更（2026-11-14）

- **系统改 Windows Server 2022**：`guifanchaxun` 是原生 Windows 项目，Linux 首次运行风险未消除；
  部署层改用 PowerShell + 计划任务 + Caddy，脚本见 `scripts/p3/server/`，手册见
  [部署指南](../部署指南-Windows服务器.md)。
- **仓库与规范库放桌面**，运行时数据留在 `C:oad`；`deploy.json` 支持 `%USERPROFILE%` 展开。
- **试用期允许纯 HTTP**：`https=false` 时 Caddy 只开一个 HTTP 端口；切 HTTPS 改一个字段重跑。
- **Linux 部署脚本移出仓库**：从未在 Linux 验证，保留会误导；若要回到 Linux，需重做部署层。
- 手填项（口令、API key、域名、路径）集中到仓库根 `deploy.json`（gitignore），本机与服务端共用。
