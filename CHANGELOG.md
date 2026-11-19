# 变更记录

版本号以 `src/roadexpert/__init__.py` 为准；详细验证记录见 [docs/validation.md](docs/validation.md)。


## 0.4.18（2026-11-19）

- 聊天进程开启 `PYTHONFAULTHANDLER`：原生级崩溃（访问冲突等）也会在 `.err.log` 留下 traceback，
  补上 11-18 那次「只有一行分隔线、没有异常栈」的取证空白。
- `chat-run.log` 的退出行同时记退出码与时间，便于把「进程什么时候死的」和看门狗日志对齐。

## 0.4.17（2026-11-19）

- 修「服务挂了没人拉起」：新增 `RoadChatWatchdog` 计划任务，每 5 分钟查一次 `/api/health`，
  不健康就重启 `RoadChat`。2026-11-18 02:49 聊天进程退出后，任务停在 `Ready`、`RoadCaddy` 一直 502，
  页面登录不了却没人发现——计划任务的「失败自动重启」在进程被外部终止时没有触发。
- `run-chat.ps1` 改为 stdout／stderr 分开写 `chat-<时间戳>.out.log` / `.err.log`，并在 `chat-run.log`
  记退出码：以前两路混写同一文件，崩溃 traceback 被编码搅乱，查不出原因。
- `acceptance.ps1` 增加「看门狗已注册」检查。

## 0.4.16（2026-11-15）

- 改口令即生效：`rc_auth` cookie 的签名密钥改为「`auth.key` + 当前口令派生值」，改 `deploy.json`
  的 `password` 并重启后，所有旧 cookie 立刻失效，已登录的浏览器被要求重新输口令。
- 以前 cookie 只与 `auth.key` 有关、7 天有效：换口令后旧浏览器仍能免密用上一周，等于换口令没把人挡在门外。

## 0.4.15（2026-11-15）

- 部署配置改为**启动时直接读 `deploy.json`**：`max_visitors` 与 `password` 以它为准，优先级高于
  `roadchat.env` 里的同名环境变量。改完 `deploy.json` 只需重启（`service.ps1 restart` 或重启
  `RoadChat` 任务）即生效，不必重跑安装脚本。
- 修的是「设了 `max_visitors` 却不起作用」：以前这两个值只在安装时写进 `roadchat.env`，
  只重启服务不会重读 `deploy.json`，看起来像参数无效。
- 并发上限仍然只限制**同时在线、已拉起运行时**的访问者，不是登录名额；超出者在点新对话或发消息时被挡。

## 0.4.14（2026-11-15）

- 重建阈值由 8 个新对话改为 **5 个**，更快回收会话堆积（代价：新对话后第一条消息等 15–20 秒的次数变多）。

## 0.4.13（2026-11-15）

- 重建阈值的边界对齐文档：同一访问者开到**第 8 个**新对话时重建运行时（此前要到第 9 个）。
  内存控制不变，只是文案、验收项与实际行为一致。

## 0.4.12（2026-11-15）

- 修复聊天页「运行时启动失败：初始化 SDK profile 失败」：dsh 装在用户 `%APPDATA%\npm` 时，
  `roadchat` 对该目录只拿到穿越（`X`），而 Node 解析模块路径要对沿途每一层做 `stat`/`realpath`，
  直接 `EPERM`。改为对该层目录本身给读+穿越（`RX`，不继承，子目录仍不可读）。
- `acceptance.ps1` 新增「服务账户能初始化 dsh（realpath 不报 EPERM）」检查，并支持 `deploy.json`
  的 `service_user`；这类失败以前要等页面上报才发现。

## 0.4.11（2026-11-15）

- 修复 `install-chat.ps1` 的服务账户自检一直失败：`if (...) {...} else {...} | Out-File` 在
  PowerShell 5.1 是解析错误（不能使用空管道元素），每次安装都报 `ParserError`，看起来像 ACL 仍不通过。
  改为 `& { ... } | Out-File` 后，自检真的以 `roadchat` 身份访问仓库与规范库并打印结论。
- 自检没写出结果时明确提示，不再静默当作通过。
- 重跑安装前先清理上次遗留的 chat／proxy／caddy 进程：旧进程占着 8095／8096／8443 会让新任务起不来、
  `RoadCaddy` 退出码 1，表现为「装了好几次都没成功」。
- 模型代理 `/models` 改为本地应答：上游是 Anthropic 兼容端点，没有该接口，原实现转发过去 404，
  使 `acceptance.ps1` 的「代理转发」一项必然失败；顺带作为代理存活探测点。

## 0.4.10（2026-11-15）

- 并发上限可配置：`deploy.json` 新增 `max_visitors`（默认 8），换算到 `roadchat.env` 的
  `ROAD_CHAT_MAX_VISITORS`；`/api/health` 返回 `limit`，`service.ps1 status` 显示 `在线=x/limit`。
- 非正数或非法值回落到 8。

## 0.4.9（2026-11-15）

- 修复 `roadchat` 无法进入桌面仓库（`Set-Location` 报拒绝访问）：上级目录的授权从「仅穿越」
  （`X`）改为「读+执行」（`RX`），并在安装时用服务账户**真的测一次**能否访问仓库与规范库。
- `run-chat.ps1` 日志开头记录运行身份与 `Test-Path` 结果，便于定位权限问题。

## 0.4.8（2026-11-15）

- 修复 `RoadChat` 计划任务启动即退出：非管理员账户运行「不论是否登录」的计划任务需要
  **批量登录权限**（`SeBatchLogonRight`），`install-chat.ps1` 现在会自动授予。
- `run-chat.ps1` 现在把输出写到 `C:\road\work\logs\chat-run.log`；安装脚本启动后自检 40 秒，
  没起来就打印任务结果码与日志尾部，不再「装完看起来成功但服务其实没起」。

## 0.4.7（2026-11-15）

- 修复 `install-chat.ps1` 注册 `RoadChat` 计划任务时报 `AmbiguousParameterSet`：
  `Register-ScheduledTask` 的 `-Principal` 与 `-User/-Password` 属于不同参数集，不能同时传。
- 补服务账户的读权限：`roadchat` 需要读 `C:\road\etc` 的配置与 `C:\road\bin` 的启动脚本，
  否则计划任务启动后读不到 env、拿不到配置（`proxy.env` 仍只给管理员/SYSTEM）。

## 0.4.6（2026-11-15）

- `bootstrap-windows.ps1` 的 Defender 排除增加**规范库目录**（`Desktop\guifanchaxun`），
  避免首次读取/渲染 3.79GB PDF 时被实时扫描拖慢。

## 0.4.5（2026-11-15）

- 修复部署脚本：Python 3.12 的部分后续版本只发源码包（没有 `-amd64.exe`），原逻辑固定取最新版会 404。
  现在逐个 HEAD 探测，取最新的带 Windows 安装包的版本（当前为 3.12.10），并保留手动兜底提示。
- Git 自动安装失败时给出可读提示与下载地址，不再抛出原始 API 错误。

## 0.4.4（2026-11-14）

- 部署前优化：`install-chat.ps1` 拒绝占位 api_key（含「替换/你的/your」等字样），避免拿假 key 上线；
  `service.ps1 status` 显示在线名额 `online/8`。
- 部署指南：第 4 步补「包名别写成 dsh」的提醒与锁版本写法；第 8 步解释 `online` 与 `visitors` 的区别；
  新增附录 B——管理员 `dsh web` 自查入口与两把 key 的分工。
- `deploy.example.json` 的说明区分产品 key 与管理 key。

## 0.4.3（2026-11-14）

- 聊天页标题栏右侧新增「新对话」按钮：停掉正在进行的回答、清空当前对话、向服务要一个新会话，
  按钮在请求期间禁用，避免连点。

## 0.4.2（2026-11-14）

- 并发上限改为按**在线**计：只有挂着运行时的访问者占名额，最多 8 个；打开过页面或已被空闲回收的不占。
  这样不会因为「有人换过浏览器」把名额用光。
- `/api/health` 增加 `online` 字段；`/api/new` 在满员时直接返回 503 与提示文案。

## 0.4.1（2026-11-14）

- 新增**空闲回收**：访问者连续 30 分钟无请求即停运行时，会话保留，下次说话自动恢复（`ROAD_CHAT_IDLE_SECONDS` 可调，0 关闭）。
- 新增**并发上限 8 人**：第 9 个访问者收到 503 与「暂时已超过使用人数上限（8人），请稍后再试」。
- 重建阈值 20 → 8，运行时不再越养越胖。
- `bootstrap-windows.ps1` 增加 Defender 排除与页面文件检查；`install-chat.ps1` 写入空闲回收时长。
- 新增 PowerShell BOM 守卫测试，防止脚本被存成无 BOM 后在 5.1 上解析失败。

## 0.4.0（2026-11-14）

- 新增 Windows Server 2022 部署套件：`bootstrap-windows.ps1`、`install-chat.ps1`、`acceptance.ps1`、`service.ps1`，
  以及九步上线的部署指南。
- 手填项集中到仓库根 `deploy.json`（gitignore）：口令、API key、域名、`%USERPROFILE%` 路径。
- 仓库与规范库默认放桌面，运行时数据留在 `C:\road`；服务账户只拿到「穿越」权限。
- 删除从未在 Linux 验证的部署脚本与三份早期记录（要点并入验证记录的「历史档案」），
  `windows-notes` 并入部署指南附录。
- 聊天服务收敛：合并 cookie 构造、抽出事件翻译、新增 `--version`；页面抽出统一的 `apiJson`。
- 文档重整：README / 交接 / 架构 / 已知限制 / ADR 0005 对齐「Windows 单目标」。

## 0.3.0（2026-11-13）

- 聊天前端改为按访问者隔离运行时：`rc_vid` cookie，每人独立 `DSH_HOME` 与咨询目录；停止只影响自己。
- 新增本地模型代理（真实 API key 只在代理进程）与口令门槛（默认 `yhg`，可配置、空值关闭）。
- Linux 分支的进程组停止、`ROAD_EXPERT_CONFIG`、部署级 patch（`ROAD_CHAT_PATCH`）。

## 0.2.0（2026-11-11）

- 纯聊天前端（`scripts/p3/chat/`）：单页、Apple 设计体系、发图、提问卡片、停止键、过程折叠。
- 排版器支持标题、列表、表格、引用、链接、任务列表与上下标。

## 0.1.x（2026-10 — 11）

- 咨询 CLI 与 `road-diagnosis` 技能：多轮、风险筛查、规范回源、案例审核、本地资料库、照片、方向比较、
  三种专项草稿、按需 Word 与交付检查。
- 临时状态 24 小时清理、显式保存/恢复、备份与导出。
