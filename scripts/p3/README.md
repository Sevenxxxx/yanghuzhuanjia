# P3 本机 Web 入口（道路养护专家）

这里有两套入口，共用同一份专家职责说明（[road_expert.patch.yml](road_expert.patch.yml)）：

| 入口 | 长什么样 | 用什么 |
|---|---|---|
| [dsh Web 实例](local_web.py) | dsh 自带界面（带侧栏、设置） | 账号登录路由，端口 8090 |
| [纯聊天前端](chat/app.py) | 只有一个聊天区和输入框，能发图片 | SDK stdio + API key，端口 8091 |

纯聊天前端是为「不显示其他界面」做的，取舍见 [ADR 0003](../docs/decisions/0003-chat-frontend.md)；
视觉规范按 Apple 设计体系（HIG）落地，token 与约束见 [ADR 0004](../docs/decisions/0004-ui-apple-design.md)。
两者互不干扰，可以同时跑。

## 纯聊天前端

**双击仓库根目录的 [启动咨询助手.cmd](../../启动咨询助手.cmd) 就行**：已在运行就直接打开页面，
没运行就后台启动、等它就绪后自动开浏览器。启动后任务栏里那个最小化的窗口就是服务本身，
关掉窗口即停止（也可以 Ctrl+C）。

下面是等价的命令行方式：

```powershell
python -X utf8 scripts/p3/chat/app.py
```

- 默认端口 8091，监听本机局域网 IPv4；本机也用它打开，`127.0.0.1:8091` 连不上。
- **按访问者隔离运行时**：服务端给每个浏览器下发 `rc_vid` cookie，每个访问者一个独立
  dsh 运行时，数据在 `%USERPROFILE%\dsh-roads\visitors\<id>\`（`home` 是 DSH_HOME，
  `localappdata` 是咨询目录）。所以某人点停止只重启他自己的运行时，不影响别人。
- 每个访问者首次说话时才初始化 `road-sdk` profile 并拉起运行时（约 10–20 秒），
  之后常驻；同一访问者累计开 20 个新对话且当前空闲时，后台重建他的运行时。
- 模型 key 读取顺序：环境变量 `DEEPSEEK_API_KEY` 优先，其次
  `%USERPROFILE%\.dsh\.credentials.yaml` 的 `refs`。服务器上应指向本地模型代理，
  真 key 不出现在前端进程里（见 [ADR 0005](../docs/decisions/0005-server-deployment.md)）。
- 每次打开页面都是**新对话**：页面向 `POST /api/new` 取一个新会话 id，转录只存在内存里，
  刷新或重开即空白；服务端的会话文件留在 home，不自动清理。
- **停止**：回答过程中输入框右侧的发送键会变成方块停止键，点它即停止（`POST /api/stop`）。
  因为 SDK 协议没有 cancel，实际做法是重启**这个访问者自己的**运行时并用 `session/resume`
  修复被中断的轮次：他自己下一条消息等约 10–20 秒，别人的会话完全不受影响。
- 打开新对话会**作废上一轮**：旧对话的进行中轮次不再阻塞新对话，挂在旧会话上的提问按协议
  回 `{cancelled: true}`。所以刷新之后不会再出现「上一轮还在回答」把新对话卡住。
- 监听地址默认取局域网 IPv4，并优先 `192.168`（避开 VPN 常见的 `10.x` 虚拟网卡）；
  地址会打印在启动行里，以它为准。
- 运行时日志：`%USERPROFILE%\dsh-roads\logs\runtime-<访问者>.log`；健康检查
  `GET /api/health` 返回访问者数、就绪数与累计会话数。
- 页面只有：标题、对话区、输入框、图片预览、发送按钮。提问以卡片形式在对话里回答。
- 另一台电脑要访问 8091，需要管理员加一条入站规则：

```powershell
New-NetFirewallRule -DisplayName "road-chat-8091" -Direction Inbound -Protocol TCP `
  -LocalPort 8091 -Action Allow -RemoteAddress 192.168.1.0/24
```

不想加规则时，先 `local_web.py down` 让出已放行的 8090，再用
`python -X utf8 scripts/p3/chat/app.py --port 8090` 启动前端。

已知限制：服务本身没有登录鉴权，同网段可访问并消耗模型额度；回答按整段出现，没有逐字流式；
`--host` 换地址后旧的浏览器缓存转录不受影响，但服务端会话仍在同一 home。

## dsh Web 实例

在仓库外起一个专用的 dsh Web 实例：默认 agent 是「道路养护专家」，独立 home、独立端口，
不动现有 3080 开发 GUI、不改项目仓库。这一层是服务器部署的雏形，服务器阶段复用同一份
[preset](road_expert.patch.yml) 与 [启动脚本](local_web.py)。

### 前置

- `dsh` 在 PATH 上（本机为 `C:\Users\Seven\.dsh\bin\dsh.cmd`，源码 checkout 已构建）。
- 项目仓库在 `C:\Users\Seven\Desktop\yanghuzhuanjia`，`config.example.json` 里的
  `spec_skill` 指向可用的规范库。
- 一个能登录的 DeepSeek 账号：实例走 `deepseek-account` 路由，不是 API key。

### 启动

```powershell
python -X utf8 scripts/p3/local_web.py up
```

默认端口 8090，监听地址自动取本机局域网 IPv4（取不到则 127.0.0.1）。输出里的 `url`
就是带一次性 token 的入口。

```powershell
python -X utf8 scripts/p3/local_web.py status   # 进程、端口、当前链接
python -X utf8 scripts/p3/local_web.py url      # 只要链接
python -X utf8 scripts/p3/local_web.py down     # 停止
python -X utf8 scripts/p3/local_web.py reset --yes  # 停止并删除整个实例目录
```

### 第一次使用

1. 在本机浏览器打开 `up` 给出的 `url`。
2. 页面首次需要**登录 DeepSeek 账号**（模型页或登录提示）。这个实例的凭据是独立的，
   与 3080 开发 GUI 的登录互不影响；额度是同一个账号。
3. 新建会话默认就是「道路养护专家」，工作目录应为项目根；让它 `skill` 列出技能时
   应能看到 `road-diagnosis`。

### 另一台局域网电脑

同一 Wi-Fi 下直接用同一个 `url`。本机也用这个局域网地址打开（实例只绑 `192.168.1.5`，
`127.0.0.1:8090` 连不上）。token 每个浏览器换一次 cookie，cookie 有效期 7 天；换浏览器或
清理 cookie 后重新 `url` 取链接。地址或端口变了（DHCP 换 IP、重启换了端口），旧 cookie
失效，重新 `up` 后取新链接即可。

### 数据位置

| 内容 | 位置 |
|---|---|
| 会话、附件、凭据 | `%USERPROFILE%\dsh-roads\home\` |
| 启动日志（含 token） | `%USERPROFILE%\dsh-roads\logs\web.log` |
| 实例状态 | `%USERPROFILE%\dsh-roads\state.json` |
| 咨询记录与 Word 导出 | `%LOCALAPPDATA%\RoadMaintenanceExpert\2f50959555be`（与 3080 共用） |
| 规范库 | `C:\Users\Seven\Desktop\guifanchaxun`（只读） |

日志里的 token 等同于登录凭据，不要外发。

### 故障排查

| 现象 | 处理 |
|---|---|
| `已有进程在监听` | 先 `status`；确实要重启就 `down`，或换 `--port` |
| `等待实例就绪超时` | 看 `logs\web.log` 末尾；常见是端口被占或 profile patch 写错 |
| 页面 401 / 一直要求登录 | token 是一次性的：重新 `url` 取当前链接 |
| 能开页面但模型不可用 | 该实例没登录，或账号额度用尽；到模型页登录 |
| 图片发不上去 | 单张 ≤50 MiB、每条消息 ≤20 张；确认路由仍声明图片能力 |
| Word 生成失败 | 检查文档 Python：`%USERPROFILE%\.cache\codex-runtimes\...\python.exe` |
| 注销后实例没了 | 本脚本用独立隐藏控制台启动，正常情况下不随登录会话结束；需要开机常驻时改用计划任务 |
| 想回到 3080 开发 GUI 试 | 把 `road_expert.patch.yml` 的 `insert` 段贴进 3080 profile 的 patch 层，会话里手选「道路养护专家」 |

### 到服务器上要改的

1. `--home` 指到服务器上的持久目录，别放 `%USERPROFILE%`。
2. 用反向代理 + TLS 终结，`--trusted-host` 加上对外域名；实例本身仍只监听回环。
3. 每个同事一个实例（独立 home、独立端口、独立咨询存储），不要多人共用同一个 home。
4. 权限从 `danger-full-access` 收紧，并把 `road.py` 的存储目录纳入可写范围。
5. 纯聊天前端上线前要补登录鉴权，否则同网段任何人都能用掉模型额度。
