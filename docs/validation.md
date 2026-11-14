# 验证记录与交付审计

本文件集中维护有日期的验证和历史处理记录；最新复验置于最前。旧路径、旧测试数量和历史人工查看不能作为新版本验证。运行命令与接手入口见 [交接.md](交接.md)。

## 2026-11-14：0.4.4 部署前优化

| 改动 | 原因 |
|---|---|
| `install-chat.ps1` 拒绝占位 api_key | `sk-替换成你的 key` 也能过 `^sk-` 检查，会带着假 key 上线 |
| `service.ps1 status` 显示 `online/8` | 上限改为按在线计后，运维需要直接看到名额占用 |
| 指南第 4 步补包名提醒 | 用户曾写成 `npm i -g dsh`（那是另一个包） |
| 指南第 8 步解释 `online` 与 `visitors` | 两者含义不同，避免误读 |
| 新增附录 B | 管理员 `dsh web` 入口 + 产品/管理两把 key 的分工 |

验证：四个 PowerShell 脚本 5.1 解析通过；unittest 203 项通过；`check_docs` 通过。
未验证：占位 key 拒绝逻辑在真实 deploy.json 上的报错文案（单看代码分支）。

本文件集中维护有日期的验证和历史处理记录；最新复验置于最前。旧路径、旧测试数量和历史人工查看不能作为新版本验证。运行命令与接手入口见 [交接.md](交接.md)。

## 2026-11-14：0.4.3 标题栏「新对话」按钮

| 检查 | 结果 |
|---|---|
| 行为（无头浏览器 + 桩 fetch） | 预置一条旧消息 → 点按钮：旧内容清空、空态重新出现、`/api/new` 被调用、按钮恢复可用（`before=true;after=false;emptyState=true;calls=/api/health,/api/new,/api/new`） |
| 视觉 | 宽屏 900px 截图确认按钮在标题栏右侧、标题仍居中（`logs\ui-newchat.png`） |
| 语法 | 页面脚本 `node --check` 通过 |
| 单测 | 203 项通过；`check_docs` 通过 |

未验证：窄屏（320–375px）下标题与按钮是否挤在一起；触屏点击手感。

本文件集中维护有日期的验证和历史处理记录；最新复验置于最前。旧路径、旧测试数量和历史人工查看不能作为新版本验证。运行命令与接手入口见 [交接.md](交接.md)。

## 2026-11-14：0.4.2 并发上限改为「在线」计

0.4.1 的上限按「见过的浏览器」累计，导致名额会被旧浏览器占满。改为按在线（持有运行时）计：
`ChatService.online_slot()` 在起运行时分配名额，`_kill_runtime()` 释放；`/api/new` 在满员时返回 503。

| 检查 | 结果 |
|---|---|
| 单测 | 203 项通过（上限相关 5 项重写：名额分配、第 9 人拒绝、回收释放、已在线者仍可新建对话、reaper 释放名额） |
| 端到端 | 连开 9 个浏览器会话全部 200，`/api/health` 显示 `online=0, visitors=9`——不再按累计浏览器计数 |
| 未验证 | 8 个**真实运行时**同时在线的拒绝路径（需要 8 次真实启动，单测覆盖逻辑） |

本文件集中维护有日期的验证和历史处理记录；最新复验置于最前。旧路径、旧测试数量和历史人工查看不能作为新版本验证。运行命令与接手入口见 [交接.md](交接.md)。

## 2026-11-14：0.4.1 内存控制（空闲回收与并发上限）

用户反馈服务器内存紧张，确认做 A/B/D/E/F/G/I 七项（不做「过期访客腾位」与「运行时堆上限」）。

| 项 | 内容 |
|---|---|
| A | 空闲回收：访问者 30 分钟无请求 → 停运行时，保留会话；下次说话 `session/resume` 恢复（首条等 15–20 秒） |
| B | 并发上限 8：第 9 个访问者 503 +「暂时已超过使用人数上限（8人），请稍后再试」 |
| D | 重建阈值 20 → 8 |
| E | 上限保持 8，不静默淘汰在线者 |
| F | `bootstrap-windows.ps1` 给 `C:\road\work` 与仓库目录加 Defender 排除 |
| G | `bootstrap-windows.ps1` 检查页面文件是否 ≥ 4GB，不够给出设置命令（需重启） |
| I | 文档、CHANGELOG、版本号同步到 0.4.1 |

验证：unittest 200 项通过（新增空闲回收 4 项、上限/回收 3 项、PowerShell BOM 守卫 2 项）；`check_docs` 通过。
未验证：真实服务器上的内存曲线（回收前后 RSS）、`Add-MpPreference` 是否被篡改保护拦住、页面文件检查在目标机上的输出。

本文件集中维护有日期的验证和历史处理记录；最新复验置于最前。旧路径、旧测试数量和历史人工查看不能作为新版本验证。运行命令与接手入口见 [交接.md](交接.md)。

## 2026-11-14：仓库整理与 0.4.0

删除过时文件、重整文档、收敛聊天服务代码，按 0.4.0 发布。

- 删除：Linux 部署脚本 11 个（从未在 Linux 验证，部署改走 Windows）、早期记录 3 份（要点并入「历史档案」）、
  `windows-notes.md`（并入部署指南附录）、本地 `scripts/p3/chat/config.json`（口令只留 `deploy.json` 一个真源）。
- 新增：`scripts/p3/server/README.md`（脚本索引）、`CHANGELOG.md`、部署指南附录 A（已知坑）。
- 更新：README / 交接 / 架构 / 已知限制 / ADR 0005 / p3 README / AGENTS 对齐 Windows 单目标。
- 代码：`app.py` 合并 cookie 构造、抽出事件分发、加 `--version`；`page.html` 抽出 `apiJson` 统一 401 处理。
- 验证：unittest 192 项通过（新增 5 项事件翻译）、`check_docs` 通过；`v0.4.0` 已打 tag。
- **本机模型回归未通过**：登录页 / 口令（错 401、对 200）/ 登录后进聊天页 / 新建会话都正常，但真实问答返回
  「模型没有返回内容」。直连官方接口核对：`GET /models` 与 `POST /chat/completions` 均返回 401
  `Authentication Fails, Your api key: ****ce6e is invalid`——**本地 `DEEPSEEK_API_KEY` 已失效**，不是代码问题。
  因此「停止后继续」的完整链路与回答内容本身**本轮未验证**，等换有效 key 后补测。

## 2026-11-14（夜）：手填项集中到根目录 deploy.json

用户希望口令、API key 这类手填值只有一个位置。新增根目录 [deploy.example.json](../deploy.example.json)（入库），复制成 `deploy.json` 后填写；`deploy.json` 已进 `.gitignore`，不入库、不推送。

接入方式：聊天服务新增 `--config`（`启动咨询助手.cmd` 自动带 `deploy.json`）；`install-chat.ps1` 从同一个文件取 `api_key`、`password`、`domain`、端口、路径与账户，缺 key 时直接报错并提示位置。

| 检查 | 结果 |
|---|---|
| 单测 | 新增 deploy 形状配置用例，187 项通过 |
| 端到端 | 用 `deploy.json`（password=test123）起服务：输 `yhg` → 401，输 `test123` → 200 |
| 文件安全 | `git check-ignore deploy.json` 命中；`deploy.example.json` 才入库 |
| PS 脚本 | 改后仍通过 PowerShell 5.1 解析（BOM 保留） |

未验证：Windows Server 上 `install-chat.ps1` 从 `deploy.json` 读值并写 env 的完整链路。

## 2026-11-14（晚）：改用 Windows Server 2022，补 PowerShell 部署套件

用户把服务器系统改成 Windows Server 2022，原先只写了 Linux 脚本。补三支 PowerShell：
`bootstrap-windows.ps1`（Node 24 / Python 3.12 / dsh / 依赖 / 账户 / ACL / 防火墙）、
`install-chat.ps1`（配置、启动脚本、三个计划任务、Caddy 反代与自签证书）、
`acceptance.ps1`（门槛自检，与 Linux 版一一对应）。

| 检查 | 结果 |
|---|---|
| 三支脚本语法 | 用 PowerShell 5.1 的 `Parser::ParseFile` 逐个解析通过 |
| **踩到并修掉** | 无 BOM 的 UTF-8 在 5.1 里按 GBK 解码，中文使引号错位、整份脚本解析失败 → 三支统一存成 UTF-8 with BOM，`.gitattributes` 增加 `*.ps1 text eol=crlf` |
| 又修掉 | ACL 里用本地化组名 `Administrators` 不可靠，改成 SID `*S-1-5-32-544` / `*S-1-5-18` |
| 版本解析 | 实测 `nodejs.org/dist/index.json` 取到 v24.22.3、`python.org/ftp/python/` 取到 3.12.16，脚本里的解析逻辑可用 |
| Caddy 配置 | 生成逻辑改成按行拼接（原来的 `\n` 在 PowerShell 双引号里不会换行），`caddy validate` 在安装时兜底 |

未验证：三支脚本在真实 Windows Server 上执行、计划任务以 `roadchat` 身份登录并启动、Caddy 自签证书在 8443 的表现、`acceptance.ps1` 全绿。

## 2026-11-14：页面访问口令

用户要求加一道「简单输入密码」的关卡，默认口令 `yhg`，配置里留可改的占位，改成空就免口令。

实现：`scripts/p3/chat/config.json` 的 `password` 为口令（示例 `config.example.json` 入库，实际文件 gitignore）；环境变量 `ROAD_CHAT_PASSWORD` 优先，空值表示关闭。登录页与聊天页同款 Apple token；通过后下发 HMAC 签名的 `rc_auth` cookie（7 天），密钥存 `dsh-roads/auth.key`，重启不失效；同 IP 一分钟错 5 次返回 429。接口未登录一律 401，页面收到 401 自动回登录页。

| 检查 | 结果 |
|---|---|
| 单测 | 新增 8 项（口令解析 5 项含 BOM、cookie 签名 4 项），`test_p3_chat` 35 项通过 |
| 端到端 | 未登录 `/` → 登录页；未登录 `/api/new` → 401；错口令 → 401；口令 `yhg` → 200 并下发 `rc_auth`+`rc_vid`；登录后 `/` → 聊天页；`/api/new` → 会话 id |
| 空口令 | `{"password": ""}` 时 `/` 直接是聊天页（截图 `logs\ui-login.png` 为登录页） |
| 发现并修掉 | 记事本另存 UTF-8 带 BOM 会让 JSON 解析失败而回落成默认口令，改为 `utf-8-sig` 读取 |

未验证：服务器上经 nginx 的登录链路、多标签页共享 cookie、7 天后过期表现。

## 2026-11-14：买服务器前的选型与 Node 版本修正

| 事项 | 结果 |
|---|---|
| 运行时内存实测 | 一个 dsh 运行时 **194 MB**（Windows WorkingSet），Python 前端 25 MB → 4GB 机器可承载 6–10 个访问者，此前按 500MB/人 估的 8GB 建议收回 |
| **Node 版本** | **修正**：dsh 的 `engines` 是 `>=24.9.0`，而脚本按 Node 20 安装——装上也会被拒；Node 20 已于 2026-04-30 EOL。`bootstrap-linux.sh` 改装 Node 24，`acceptance.sh` 的门槛改成 `>= 24.9`，README 与 Windows 备选同步 |
| 系统镜像选择 | 建议 Ubuntu 24.04 LTS（脚本与 Python 3.12 假设验证过）；26.04 LTS 更新但把「首次在 Linux 运行」再叠一层新变量 |
| 脚本语法 | `bootstrap-linux.sh`、`acceptance.sh` 改后 `bash -n` 仍通过；版本判断表达式单独用本机 node 26 验证为 0 |

## 2026-11-13（晚）：买服务器前的预检与两处修正

用户准备购买服务器，先做能离线做的事：

| 检查/修正 | 结果 |
|---|---|
| 五个服务器脚本 `bash -n`（用 Git Bash 5.3 的 bash 解析，不执行） | bootstrap / install-app / backup / health / acceptance 全部通过 |
| nginx 模板 `http2 on;` | **修正**：该指令要 nginx ≥1.25.1，Ubuntu 24.04 带的是 1.24，`nginx -t` 会直接报错；改回 `listen 443 ssl http2;` |
| `roadchat.env` 的模型接线 | **修正**：原示例写的是 `DEEPSEEK_BASE_URL`，实测 dsh 的 Messages 适配器不读它；改为 `ROAD_CHAT_PATCH` 指向 `proxy.patch.yml`，并写明不加会表现成「模型没有返回内容」 |
| 新增 `server/acceptance.sh` | 把上线门槛合成一条命令：程序、`road.py --doctor`、一条 `spec-search`、两个服务、代理转发、`nginx -t`、目录权限、日志无 key；有失败项则退出码 1 |
| 新增 `server/onboarding.md` | 给同事的一页说明（能做什么、不能做什么、记录 24h、停止键代价、数据边界） |

仍未验证（服务器到手后才能做）：`acceptance.sh` 的真实执行、`nginx -t`、systemd 启停、`guifanchaxun` 在 Linux 上运行、`sudo -u` 越权实测、攻击演练三条、20 次重建的真实轮次。

## 2026-11-13：服务器化（按访问者隔离运行时）

按 [ADR 0005](decisions/0005-server-deployment.md) 实现：一个地址、共享口令、每个访问者一个独立 dsh 运行时；停止只影响自己；不做空闲回收（用户决定），用「20 个新对话后重建」与「夜间重启」兜底；真 API key 移入本地模型代理。

**代码**：`chat/app.py` 改为运行时池（cookie `rc_vid` 标识访问者，独立 `DSH_HOME` 与 `LOCALAPPDATA`）；Linux 用 `start_new_session` + `os.killpg` 杀进程组；`ROAD_CHAT_PATCH` 支持部署级 patch；模型返回为空时明确报错而不是静默结束。新增 `proxy/model_proxy.py`、`server/`（bootstrap、install、systemd、nginx、备份、自检、Windows 备选）。`road.py` 支持 `ROAD_EXPERT_CONFIG`；`road_expert.patch.yml` 补 `tool-bash`/`tool-pwsh` 平台互斥。

| 检查 | 本轮结果与范围 |
|---|---|
| `python -X utf8 -m unittest discover -s tests` | 177 项通过（新增 8 项：池化、停止隔离、20 次重建、代理路径、配置优先级、shell 工具平台门控） |
| `python -X utf8 scripts/check_docs.py` | 通过（23 份文档、99 条链接、版本 0.3.0） |
| 双访问者并发 | 两个 cookie 各自提问，均得到回答；并发完成 14.1 秒；`/api/health` 显示 `visitors=2, ready=2` |
| 停止隔离 | A 回答中 B 提问 → B 6.8 秒答完；A 停止后 B 再问 → 1.0 秒答完，B 未受影响 |
| 模型代理 | `/models` 200；`/v1/messages` 经代理转发成功（dsh 只拿占位 token）；未允许路径 404 |
| 端到端（经代理） | dsh → 代理 → `api.deepseek.com/anthropic/v1/messages`，回答「测试」；`ROAD_CHAT_PATCH` 生效 |

未验证（不得写成通过）：
- 服务器脚本没有在本机执行过——本机没有 bash、也没有 WSL，`bash -n` 与 systemd/nginx 配置只能在服务器上验；
- `guifanchaxun` 在 Linux 上未运行过（首要风险，已写成上线门槛）；
- 服务器上的隔离实测（`sudo -u` 读他人目录、攻击演练三条）、域名证书、`certbot` 与 nginx SSE 行为；
- 20 次重建只有单测覆盖，未在真实服务里跑满 20 轮；
- 夜间重启 timer 未部署验证。

## 2026-11-11：0.2.0 纯聊天前端

用户要求「新的 webui，不显示其他界面，就纯聊天 + 能放图片」。先核对宿主约束：`single` 槽只能有一个占位者、二次注册直接抛错，插件规范禁止替换 app root 与读他人 DOM／样式，CSS modules 类名哈希；因此改为自建前端，取舍见 [ADR 0003](decisions/0003-chat-frontend.md)。

- 新增 `scripts/p3/chat/app.py`：HTTP + SSE 薄服务，驱动 `dsh --profile road-sdk` 的 stdio JSON-RPC（initialize / session/query / session/resume / user-question/ask）；从 `road_expert.patch.yml` 生成 SDK profile 的 patch（部署级 persona + 咨询配置 + 关闭插件管理、计划模式、子代理、定时任务、goal）。
- 新增 `scripts/p3/chat/page.html`：单文件页面，只有标题、对话、输入框、图片预览与发送；助手回答按持久消息整段出现，提问以卡片形式回答；转录存 localStorage。
- 模型改走 `deepseek-official` + `DEEPSEEK_API_KEY`（用户已同意按 token 计费）；会话固定 `road-web`，重启前 resume。

| 检查 | 本轮结果与范围 |
|---|---|
| `python -X utf8 -m unittest tests.test_p3_chat` | 11 项通过（patch 生成、persona 去缩进、事件取文、key 读取） |
| `python -X utf8 -m unittest discover -s tests` | 142 项通过 |
| `python -X utf8 scripts/check_docs.py` | 通过 |
| 真实一轮（文字） | 「沥青路面网状裂缝先做什么」→ 实际调用 `road.py`、回源 JTG 5142 第 6.1／6.2 节并实际查看渲染页、给出条件化方向与缺口，1669 字 |
| 真实一轮（图片） | 合成 900×600 路面示意图 → 模型实际描述可见形态、登记 5 条图片观察、拒绝推断病害类型，831 字 |
| 提问通道 | 首轮咨询中真实收到 `user-question/ask`（3 个问题，含选项），SSE 断开后该轮等待不结束——证明通道生效，也证明未答提问会挂住 |

未验证：浏览器里的实际观感与移动端排版、提问卡片的点击回答过程（只验了服务端收发与挂起）、另一台局域网电脑接入、`export docx` + `delivery-check` 在该前端下的完整交付、Word 实际渲染。服务本身没有登录鉴权。本轮未提交、未推送、未安装依赖、未修改原规范项目。

> 2026-11-11 晚：按用户要求改为「每次进页面都是新对话」——新增 `POST /api/new` 分配会话，页面不再持久化转录（刷新即空白），服务端去掉固定会话与启动 resume。重跑单测与文档检查；页面观感仍未实际查看。
>
> 2026-11-11 深夜修复（用户截图反馈「上一轮还在回答，等它结束再发」）：原来一轮对话的锁是**全局一把**，任何一轮卡住（典型是等用户回答提问）就把整个服务卡死。改为按会话隔离的锁，并在开新对话时作废所有进行中的轮次、把旧会话挂起的提问回 `{cancelled: true}`。复现验证：旧会话停在提问等待时，新会话 4.4 秒正常回答「nihao」。同轮发现并修掉两处：① SDK profile 里的 `preset-road` 一直 pending（等 Web 端才有的 `agentPresets` 服务），已从生成的 patch 中移除，启动警告消失；② 自动选监听地址时被 VPN 的 `10.10.1.1` 抢到，改为 `192.168` 优先，避免书签地址漂移。
>
> 2026-11-12 清晨：新增双击启动脚本 `启动咨询助手.cmd`（已在运行则直接开页面，否则后台启动并等待就绪）。实测冷启动 75 秒内监听 `192.168.1.5:8091` 且健康检查通过；再次双击 0.3 秒返回「已在运行」。批处理正文改为纯 ASCII——UTF-8 中文在 cmd 的 OEM 代码页下会被误解析成命令。
>
> 2026-11-12 上午：界面按 Apple HIG 重做（[ADR 0004](decisions/0004-ui-apple-design.md)）：语义色 token、系统字体、系统蓝、毛玻璃导航与输入栏、iMessage 式气泡、分组卡片式提问、深浅色两套、390px 手机版。用 Chrome headless 截图核对：桌面浅色／深色各一张、390px 宽一张，发现并修掉两处（深色下选项与输入框与卡片同色而隐形；390px 下无横向溢出）。截图仅作观感核对，未在真实 iPhone 或 Safari 上验证；`backdrop-filter`／`color-mix` 有回退但未逐浏览器实测。
>
> 2026-11-12 晚：规范引用只写编号、没有规范名称。核查确认两个原因：书架标题是 `154-公路沥青路面养护技术规范-JTG5142-2019` 这种带序号与编号的串，而 `spec-search` 的命中行只带 `book_id`、不带名称；技能与 AGENTS 也没有引用格式要求。修复三层：① `specs.py` 增 `standard_name`／`display_std_no`／`citation_of`，`spec-list`／`spec-search`／`spec-read` 都返回可直接使用的 `citation`（如《公路沥青路面养护技术规范》（JTG 5142—2019）：补字母与数字间空格、还原 JTG/T、年份用破折号）；② SKILL 第 6 步与 AGENTS「咨询与证据」加入「首次出现必须写《全名》（编号，年号）」；③ `delivery_check` 增 `standard_citation_name_missing` 疑点，只查每个标准号的首次出现，后文允许「同规范」或简称。实测同一问题的回答已写成《公路沥青路面养护技术规范》（JTG 5142—2019）第 6.2.7 条。单测 163 项通过（新增 14 项），文档检查通过。
>
> 2026-11-12 夜：纯聊天前端加「过程」展示并把正文字号对齐 dsh。后端把 `session.event` 翻译成 `trace` 事件：`user/message` 的注入来源（AGENTS.md／runtime-context／skill-catalog／time-context）→「上下文注入」，`assistant/message` 的 reasoning 块 →「思考」，`tool/call` ＋ `tool/result` →「动作＋目标」并在返回后置为次要态。实测一轮规范查询：`trace` 50 条、`assistant` 1 条、`done` 1 条，内容与 dsh 的过程行一致（加载技能 road-diagnosis、读取 operations.md、运行命令 spec-search…）。字号按 `ui-theme` 的 `--dsh-content-font-size` 默认 14px 重排，ADR 0004 记为该规范里唯一刻意偏离 HIG 的地方。单测 167 项通过（新增 4 项事件翻译），截图复核 `logs\ui-trace.png`；真机与 Safari 仍未验证。
>
> 2026-11-12 深夜：过程列表改成可折叠。运行中自动展开并显示「正在执行… 已用 N 秒」，本轮结束（`done` 或错误）折叠为「已完成，用时 X 分 Y 秒」，第二行是「执行了命令 ×2、文件 ×4…」的种类摘要；点标题展开/收起，单条「思考」也可点击从两行展开为全文。前端脚本用 `node --check` 过语法检查，两种状态各截图核对（`logs\ui-trace.png`）；折叠交互与计时未做浏览器自动化点击验证，需在页面上实际点一次。
>
> 2026-11-12 深夜（表格）：用户截图指出回答里露出 `|---|---|`。原因是页面排版函数只认标题、列表、粗体、行内代码与代码块，不认 Markdown 表格，于是分隔行原样显示。按真实 `format()` 源码在 Node 里跑样例验证后，补了表格解析（表头 + 分隔行 + 数据行，单元格保留行内粗体/代码）与卡片式样式（表头浅底、行间分隔线、容器随内容收缩、窄屏横向滚动）。截图 `logs\ui-table.png` 复核。仍不处理：有序列表（`1.`）按段落显示，表格内的对齐标记（`:---:`）忽略。
>
> 2026-11-12 深夜（输入栏）：① 输入框左侧「＋」与右侧发送键原先比文字低 2px（文本框 36px、按钮 32px 且底对齐），加 `margin-bottom: 2px` 后与文字视觉居中，截图 `logs\ui-composer-zoom.png` 复核。② 增加停止：回答中发送键变方块停止键，`POST /api/stop`。第一次实现只作废本地等待，实测同一会话的下一句会排在后台那一轮之后——**281.7 秒、58k 字**才轮到；改为杀掉运行时并用 `session/resume` 修复被中断的轮次。首版 `kill()` 只杀 `cmd` 外壳，留下 node 孤儿占住会话（日志里出现 EPIPE 与两个运行时并存），改为 `taskkill /T` 杀进程树后：停止在 0.2 秒内断开 SSE，12 秒后同一会话重发 6.4 秒答完，且停止前那句「我的现场编号是 A7」在续问里仍被正确答出，上下文保留。单测 169 项通过（新增停止/重启用例）。
>
> 2026-11-12 深夜（滚动）：用户反馈发送后页面不跳到最下面。原因是旧逻辑只在「距底部 160px 内」才滚动，正在看上文时发送就不动。改成记录跟随状态：发送时强制贴底，流式追加只在原本贴底时跟随，手动上翻不打断。验证方式：把页面复制一份、用桩替换 `fetch`，程序化把内容撑到 2400px、滚到顶部后触发表单提交，读回 `scrollTop`——结果 `top=2337 max=2337 atBottom=true`，确实跳到了底部。
>
> 2026-11-12 深夜（上下标）：用户截图里表格出现 `L<sub>k</sub>` 原文。模型在回答里写了 HTML 下标，而排版器把 `<` 整体转义成 `&lt;`，标签就成了文字。修复：排版器只放开 `<sub>`／`<sup>` 两种标签（文本仍先整体转义，因此 `<script>`、`<sub><img …></sub>` 等仍按文字显示），行内代码里的标记保持原样，并补了上下标样式。用真实 `format()` 在 Node 里跑了 5 组样例（下标、上标、script、嵌套 img、代码块内标记）确认输出，截图 `logs\ui-sub.png` 复核表格里的 `L_k` 显示。单测仍 169 项通过（本次只改前端，未动 Python）。
>
> 2026-11-12 深夜（排版器梳理）：用户问「异常字符是不是没渲染好」，于是把模型输出里会出现的 Markdown 全部跑了一遍审计。原实现只认标题、无序列表、表格、粗体、行内代码、代码块，其余原样显示：有序列表变成段落、`>` 引用露出 `&gt;`、`[文字]（url）` 原样、`---` 显示成三个横线、`~~删除~~` 原样、`- [ ]` 露出方括号、`~~~` 围栏不认、表格里的 `\|` 把单元格切坏、嵌套列表丢层级。重写为更完整的子集：有序／无序列表与嵌套、引用、分隔线、任务列表、`~~~` 围栏、链接与图片降级、斜体、删除线、`<br>` 等白名单标签、表格转义竖线。外链只放行 `http(s)`／`mailto` 且拒绝含引号的 URL，远程图片不自动加载。用真实 `format()` 跑 18 组样例逐条核对输出，整页渲染截图 `logs\ui-render.png`。仍不支持：自定义 HTML 块、公式、脚注、setext 标题、表格列对齐、单元格内多行——清单写进 ADR 0004「渲染能力」。

## 2026-11-11：0.1.9 P3 本机单实例 Web

用户要求「开始 P3，先在这台电脑试，也会用另一台局域网电脑进来」，不使用 Tailscale。范围与取舍见 [ADR 0002](decisions/0002-p3-local-web.md)。

- 新增 `scripts/p3/road_expert.patch.yml`：默认「道路养护专家」preset（persona + 咨询所需工具，不含 bash、计划模式、subagent、schedule、goal、插件管理）；`scripts/p3/local_web.py` 起停独立 home 与端口；`scripts/p3/README.md` 是运维手册。
- 实例：home `%USERPROFILE%\dsh-roads\home`，默认端口 8090，监听本机局域网 IPv4 `192.168.1.5`；咨询记录仍写 `%LOCALAPPDATA%\RoadMaintenanceExpert\2f50959555be`。3080 开发 GUI 与两个 home 互不影响。
- 实测并修掉两个坑：`DETACHED_PROCESS` 会让 Node 写到重定向文件的 URL 行丢失，改用 `CREATE_NO_WINDOW|CREATE_NEW_PROCESS_GROUP`；`authorizeIndex` 对回环来源直接放行，所以本机 curl 无法验证 token 交换，必须用另一台机器验。
- 未复制 3080 的 `.credentials.yaml`：复制后账号路由仍报 `ACCOUNT_SIGN_IN_REQUIRED`（记录里 `payload` 为空），实例首次需自行登录。

| 检查 | 本轮结果与范围 |
|---|---|
| `python -X utf8 -m unittest tests.test_p3_local_web` | 14 项通过；仅覆盖启动器纯函数与 preset 文本 |
| `python -X utf8 -m unittest discover -s tests` | 131 项通过（原 117 项＋14 项） |
| `python -X utf8 scripts/check_docs.py` | 通过；版本 0.1.9／v1.2 一致 |
| `python -X utf8 scripts/check_local.py` | 通过（真实规范查询／回源／渲染，合成咨询） |
| `python -X utf8 scripts/check_trial.py` | 通过（合成问答／恢复／导出／备份；按既定策略清理过期状态） |
| `python -X utf8 scripts/check_advice.py` | 通过（分领域分析、专项导出、过时拒绝） |
| `python -X utf8 scripts/check_media_delivery.py` | 通过（合成图片与 Word；不自动渲染查看） |
| `python -X utf8 scripts/check_delivery.py` | 通过（交付检查、绑定与历史标注） |
| `local_web.py up` 实机 | 实例在 `192.168.1.5:8090` 监听，日志落出带 token 的 URL，无启动诊断 |
| `dsh --profile web --dump-config`（该 home） | 组合通过，`preset-road` 与 `default: road` 生效 |

未验证：该实例尚未登录 DeepSeek 账号，模型与图片链路、多轮与恢复、规范回源、Word 导出与 `delivery-check` 都没有在浏览器里实际跑过；另一台局域网电脑的 token 交换、cookie 与访问也未实测。上述任一项未做即保留未验证，不以「服务已监听」代替。本轮未提交、未推送、未安装依赖、未修改原规范项目、未读取 `temp/` 附件。

## 2026-11-05：0.1.8 本地资料库最小版本

> 2026-11-06 用户选择将《道路养护 AI 技术专家——项目总体方案与 Codex 开发交接文档.md》保留在 `docs/`；已同步 AGENTS、README、交接、总方案内部链接及 `check_docs.py` 的产品文档路径，文档检查恢复通过。

按用户决定：规范架继续用 guifanchaxun，不复制规范正文；教材、论文、案例原文统一放 `data/library/`，按页读取和检索；先清空之前收集的全部案例。

- 新增 `library.py` 与 `library-add／list／source／toc／read／search／render／rebuild`：只接收本机绝对路径 PDF，复制到 `data/library/<library_id>/`，生成 `pages.json`、`source.txt`、`source.json`，记录页数、字符数、SHA-256、来源和版权依据；支持按类型／主题列表、字面检索、按页读取、PDF 书签目录和页面渲染。
- 清理：删除 `data/cases/incoming`、`rejected`、`history`、`sources` 及临时研究目录；`data/cases/index.json` 保留为空。`case-list` 实测 `incoming=0、verified=0、rejected=0`。
- 迁移：0007 会议论文按 `case_source` 进入资料库，`library_id=CASE-PAV-SUB-0007`，4 页、7962 个正文字符、`printed_page_offset=300`；PDF、文本和分页文本本地保存，`data/library/` 整体 gitignore。
- 论文：新增 6 篇开放获取论文（`type=paper`，合计 1 个 case_source＋6 篇论文）：

| library_id | 来源 | 页数／正文字符 | 用途 |
|---|---|---|---|
| PAPER-PIPELINE-COLLAPSE-2024 | Scientific Reports 14:17717，DOI 10.1038/s41598-024-68824-7 | 16／53601 | 地下管线渗漏诱发塌陷的模型试验机理 |
| PAPER-KARST-GROUTING-2026 | PLOS ONE 21(5):e0348701，DOI 10.1371/journal.pone.0348701 | 21／51835 | 岩溶地区注浆碎石桩复合地基现场试验 |
| PAPER-PAVEMENT-RF-2026 | Applied Sciences 16(7):3343，DOI 10.3390/app16073343 | 27／76486 | 高速公路沥青路面养护决策与随机森林 |
| PAPER-SLOPE-RAIN-2024 | Applied Sciences 14(4):1394，DOI 10.3390/app14041394 | 19／47224 | 降雨条件下顺层边坡失稳案例 |
| PAPER-BRIDGE-PIER-2025 | IABSE Congress Ghent 2025／arXiv:2508.17110 | 8／23017 | 砌体桥墩缺陷监测、评估与数值分析 |
| PAPER-BRIDGE-SCOUR-2025 | ICSE-12（ISSMGE 公开论文） | 16／21408 | 局部冲刷导致桥墩安全渐进降低案例 |

- 资料库当前 7 条：1 条 `case_source`＋6 篇论文；没有教材。`library-search` 按标题命中优先、每个来源最多 2 条摘录返回；实测 `scour` 先返回桥墩冲刷论文，`karst` 先返回岩溶注浆论文，`rainfall` 先返回边坡降雨论文。

| 检查 | 本轮结果与范围 |
|---|---|
| `python -X utf8 -m unittest discover -s tests` | 117 项通过（原 112 项＋5 项资料库回归），退出 0 |
| `python -X utf8 scripts/check_docs.py` | 19 份 Markdown、70 条本地链接通过；版本 0.1.8／v1.2 一致 |
| `python -X utf8 scripts/check_local.py` | 通过；真实规范查询／回源／渲染、空案例、多轮、备份恢复 |
| `python -X utf8 scripts/check_trial.py` | 通过；合成问答／关闭／复述／导出／备份恢复 |
| `python -X utf8 scripts/check_advice.py` | 通过；3 个分析模板、9 份专项导出及过时拒绝 |
| `python -X utf8 scripts/check_delivery.py` | 通过；检查范围、过时拒绝、历史标注、绑定及 Word 校验 |
| `python -X utf8 scripts/check_media_delivery.py` | 通过；2 张合成图、副本清理、原图不变 |
| 技能结构校验 | Skill is valid |

未验证：资料库 7 条中 6 篇为英文开放获取论文，尚无教材；PDF 文本层、表格、公式、扫描页未系统测试；`library-search` 为字面检索，不做同义词、语义排序或 OCR；`library-render` 未做实际逐页查看。论文的工程适用性、数据和结论未独立复核；资料原文不是规范或审核结论，不能替代 case_refs、规范回源或专业审核。本轮未提交、未推送、未安装依赖、未修改原规范项目、未读取 `temp/` 附件。

## 2026-11-05：0.1.7 路面沉陷候选案例库（专业资料）

> 2026-11-05 晚用户要求清理全部案例；本节所述 5 条案例及原文副本已删除，保留记录用于历史审计。当前案例库为空；0007 原文已迁入 `data/library/` 作为 `case_source`。

本轮先做路面沉陷案例库：新增 `case-list`、`case-show`、`case-source`、`case-source-read`、`case-source-search`、`case-search scope=candidate/all`、`case-reject`，并在 `answer.case_refs` 与交付检查中阻止候选案例进入引用。首轮导入的 5 条新闻／政务报道因缺少检测、监测或试验数据，已按“专业性不足”拒绝并保留记录；随后导入 5 条专业资料候选案例（`incoming`，`pending_review`）。0007 的全文（PDF、文本、分页、SHA-256）存到 `data/cases/sources/CASE-PAV-SUB-0007/`，该目录已 gitignore，仅本地使用。可引用 `verified` 库仍为空，本轮没有做人工专业审核。

| case_id | 来源 | 等级 | 要点 |
|---|---|---|---|
| CASE-PAV-SUB-0001 | [城市道桥与防洪 2025(10):42-46](http://csdqyfh.ijournals.cn/csdqyfh/article/abstract/250160) | S2（摘要） | 四川水库影响区；厚层粉土、破损暗沟渗流、水库水位与污水抽排 |
| CASE-PAV-SUB-0007 | [8iYGEC 会议论文（TU Graz 仓库）](https://repository.tugraz.at/publications/marc21/jmnxa-vj417/files/8iYGEC_Paper_ID_73_Canto.pdf?download=1) | S2（全文） | 南非 N1 公路白云岩塌陷；深部岩溶沟槽、岩面热力图、300m×10m 压密注浆网格 |
| CASE-PAV-SUB-0008 | [工业建筑 2025,55(12):167-172](http://gyjz.ic-mag.com/cn/article/doi/10.3724/j.gyjzG25031002) | S2（摘要） | 西南某市管网渗漏地面塌陷；管-井侵蚀空洞、四阶段演化 |
| CASE-PAV-SUB-0009 | [交通科技 2024(6)](https://wap.cnki.net/touch/web/Journal/Article/SKQB202406009.html) | S2（摘要） | 城市道路岩溶地基；深溶洞袖阀管注浆、洞顶高压旋喷、浅土洞明挖回填；监测达标 |
| CASE-PAV-SUB-0010 | [热带地理 2021,41(4)](https://cnki.sris.com.tw/KCMS/detail/detail.aspx?filename=RDDD202104014&dbcode=CJFD&dbname=CJFD2021) | S2（摘要） | 广州夏茅村覆盖型岩溶塌陷；土洞、地下水位、钻孔桩触发；地下水监测＋灌浆 |

已拒绝的 5 条（CASE-PAV-SUB-0002～0006）均为新闻或政务报道，S3，缺少检测、监测或试验数据；拒绝原因保存在 `data/cases/rejected/`，旧版本在 `history/`。它们不再参与候选检索，也不进入 `verified`。

候选案例文件在 `data/cases/incoming/`；`case-list` 可看摘要、来源和全文可用性，`case-show` 看全文，`case-search scope=candidate` 返回最多 3 条并标记 `unverified_candidate`，排序先精确标签、后同义词匹配。候选不进入派生索引，不能写入 `case_refs`。0007 可用 `case-source` 看元数据（4 页、8050 字符、全文），`case-source-read` 按页读取，`case-source-search` 字面检索；其余 4 条 `case-source` 返回 `available=false`、`abstract_only`。

| 检查 | 本轮结果与范围 |
|---|---|
| `python -X utf8 -m unittest discover -s tests` | 112 项通过（原 104 项＋8 项候选／全文来源回归），退出 0 |
| `python -X utf8 scripts/check_docs.py` | 19 份 Markdown、70 条本地链接通过；版本 0.1.7／v1.2 一致 |
| `python -X utf8 scripts/check_local.py` | 通过；真实规范查询／回源／渲染、空可引用案例、多轮、备份恢复 |
| `python -X utf8 scripts/check_trial.py` | 通过；合成问答／关闭／复述／导出／备份恢复 |
| `python -X utf8 scripts/check_advice.py` | 通过；3 个分析模板、9 份专项导出及过时拒绝 |
| `python -X utf8 scripts/check_delivery.py` | 通过；检查范围、过时拒绝、历史标注、绑定及 Word 校验 |
| `python -X utf8 scripts/check_media_delivery.py` | 通过；2 张合成图、副本清理、原图不变 |
| 技能结构校验 | Skill is valid |

候选案例计数：`incoming=5`、`verified=0`、`rejected=5`；其中 1 条有本地全文（0007，4 页），4 条仅摘要。按标签“沉陷”查候选返回 3 条（上限），默认 `verified` 查询返回 `no_qualified_cases`。

未验证：5 条候选均未经人工专业审核；0007 已读会议论文全文并保存本地副本，其余 4 条仅读公开摘要，未取得全文；摘要级案例缺少完整设计参数、检测数据和长期复查；病因、处治和结果沿用来源，未独立核实；0009 仅有短期监测结果。全文副本仅本地、已 gitignore，版权和许可由使用者核对；`case-source-read/search` 不解析图表、扫描件或 OCR，不证明原文支持当前判断。没有真实弹窗、Word 渲染或工程专业评价。候选案例不能替代机理库、规范判断或现场核查。本轮未提交、未推送、未安装依赖、未修改原规范项目、未读取 `temp/` 附件。

## 2026-11-04：0.1.6 问题决策影响（B4）

本轮只实现 B4：待答问题逐题记录 `decision_impact`，写明不同答案会改变什么判断或下一步；没有实现来源状态、检索日志、交接结构等其他建议，也没有改变风险规则、知识卡或案例库。

- `question-ask` 现在要求 `decision_impact` 与 fields 一一对应，缺失、错位、空文本均拒绝且不写入；`briefing.next_questions` 返回通用默认提示，模型须结合本例改写。
- 旧式 `answer.questions` 未提供时使用该字段的默认答案影响；报告“信息缺口与追问”和续办摘要显示该文本。旧记录无需迁移。
- 程序只检查字段完整性、对应关系和长度，不验证分支是否正确、问题是否最优，也不是定量信息价值。

| 检查 | 本轮结果与范围 |
|---|---|
| `python -X utf8 -m unittest discover -s tests` | 104 项通过（原 101 项＋3 项决策影响回归），退出 0 |
| `python -X utf8 scripts/check_docs.py` | 19 份 Markdown、70 条本地链接通过；版本 0.1.6／v1.2 一致 |
| `python -X utf8 scripts/check_local.py` | 通过；真实规范查询／回源／渲染、空案例、多轮、备份恢复；上游 4 个文件指纹不变 |
| `python -X utf8 scripts/check_trial.py` | 通过；合成问答／关闭／复述／导出／备份恢复；默认库清理后现存会话 0 |
| `python -X utf8 scripts/check_advice.py` | 通过；3 个分析模板、9 份专项导出及过时拒绝 |
| `python -X utf8 scripts/check_delivery.py` | 通过；检查范围、过时拒绝、历史标注、绑定及 Word 校验 |
| `python -X utf8 scripts/check_media_delivery.py` | 通过；2 张合成图、副本清理、原图不变 |
| 技能结构校验 | Skill is valid |

默认库中原有 1 个 2026-11-02 写入、已于 2026-11-04 07:35（+08）过期的临时会话及孤立证据；按既定策略在 `check_trial.py` 的首次默认调用中被清理，未手工删除有效记录。五套集成均返回 `artifacts_retained=false`。

未验证：真实弹窗显示与真人提交、Word 实际渲染逐页核对、工程专业审核、问题选择质量。决策影响文本由宿主撰写，程序不证明其正确。本轮未提交、未推送、未安装依赖、未修改原规范项目、未读取 `temp/` 附件。

## 2026-11-02：文档修复与精简

保留中文文件名 docs/交接.md，修复旧链接及接手模板；总方案集中目标、需求和阶段路线，AGENTS 集中执行约束，README 集中用户用法，交接集中当前版本、环境和近期三项任务。模块入口移至架构，历史测试和清理细节留在本文件。候选任务补充范围、验收及依赖，不作为本轮新功能授权。

新增 scripts/check_docs.py，仅用标准库只读检查项目 Markdown 的本地链接、锚点、代码围栏，以及交接的实现版本／产品基线与各自来源是否一致；不联网、不调用咨询 CLI、不访问咨询存储或附件。它不验证外部网址、任意纯文本路径或文档语义。

| 本轮检查 | 结果及范围 |
|---|---|
| 文档检查 | 19 份 Markdown 的本地链接、锚点、围栏及版本一致性通过；旧文件名引用已清除 |
| 检查器错误分支 | 内存模拟不存在的链接、错误锚点、未闭合围栏、版本不一致，均被检出；未写测试资料到文件 |
| 单元测试 | 101 项通过，退出 0 |
| check_local.py | 通过；指定上游文件指纹不变，不代表全库审计 |
| check_trial.py | 通过；过期清理后默认现存会话计数 0，随后比较区间既有 JSON 不变 |
| check_advice.py | 通过；分领域与专项交付流程 |
| check_media_delivery.py | 通过；合成原图不变、临时副本清理及 Word 生成 |
| check_delivery.py | 通过；检查不改写有效咨询、疑点定位、过时拒绝、历史标注、内容／范围绑定及 Word 媒体校验 |
| 技能结构校验 | Skill is valid；本轮未修改技能正文或参考 |

五套集成均返回 artifacts_retained=false。默认库检查沿用既定过期清理策略，不描述为绝对只读。Agent 对照修改前内容复查关键约束与产品范围；没有重做 Word 逐页查看、真实弹窗点击、工程专业审核或现场效果评价。

本轮仅修改文档并新增文档维护检查脚本，没有修改咨询业务代码、既有测试、知识卡或配置，没有创建新的磁盘文档对照目录；未读取遗留附件正文、重试历史清理、改原规范项目、安装依赖、提交或发布。

## 2026-11-01：0.1.5 交接文档整理与基线复验

本次仅修改文档：补充 AGENTS.md 执行约定及当前交接页，纠正根产品文档中的旧状态与规划目录，统一 README、架构、限制和操作参考的表述。实现版本仍为 0.1.5，产品基线仍为 v1.2，没有修改业务代码、测试或知识卡。

| 检查 | 本轮结果与范围 |
|---|---|
| Python | 3.12.10 |
| `python -X utf8 -m unittest discover -s tests -v` | 101 项通过，退出 0 |
| `python -X utf8 scripts/check_local.py` | 通过；指定上游 SKILL.md、config.json、scripts/spec.py、bookshelf.json 指纹不变 |
| `python -X utf8 scripts/check_trial.py` | 通过；默认 doctor 通过，清理后默认存储现存会话计数 0，随后指纹比较区间既有 JSON 不变 |
| `python -X utf8 scripts/check_advice.py` | 通过；3 个分析模板、9 份专项导出及过时拒绝 |
| `python -X utf8 scripts/check_media_delivery.py` | 通过；2 张合成图、4 类 Word，原图不变、临时副本清理 |
| `python -X utf8 scripts/check_delivery.py` | 通过；有效咨询不被检查改写、疑点定位、过时拒绝、历史标注、内容／范围绑定和 Word 校验 |
| 技能结构校验 | 本机系统 skill-creator 的 quick_validate.py 返回 Skill is valid；不证明咨询或工程质量 |

五套集成均返回 `artifacts_retained=false`。check_trial 的默认 doctor 先执行既定 24 小时临时过期清理，再比较剩余 JSON 指纹；不能据此声称整个调用绝对只读。上游指纹结论只覆盖列出的四个文件，不扩大为全库逐文件审计。

Agent 审查范围：对照当前源码、脚本和文档，复核版本／功能／目录、权限、存储、导出范围及下一步授权边界。确认普通完整咨询 JSON 仍含原话和历史，Markdown／Word 可能含续办与前次意见；历史模式不是脱敏开关。备份仅复制已保存咨询及关联资料。文档据此澄清行为，没有改变现行实现。9 份改动文档的本地 Markdown 链接、锚点及代码围栏检查通过，技能参考修改后再次通过结构校验。

未验证：本轮没有实际查看规范原页、重做 Word 逐页渲染、操作真实问题弹窗、工程专业审核、现场验证或完整语义一致性评价。0.1.4 的视觉核验仍只是历史证据。

未执行旧清理脚本或重试遗留 QA 删除；未读取仓库 temp/ 附件正文，未修改原规范项目、安装依赖、提交、连接远程或发布。当前 Git 无首次提交，因此文档复查使用实际文件对照，不以空 git diff 作为无改动证据。

本轮对照用的 8 份旧文档副本在审查结束后尝试清理；命令包含固定目录与重解析点校验，但自动审批以 `blocked by policy` 拒绝，未给具体原因，命令未启动。未换工具绕过；副本仍保留，副本目录为 `C:/Users/Seven/AppData/Local/Temp/roadexpert-handoff-review-a8efdf8784704afa88bdb950ec1789f1`，仅含当时修改前的 8 份项目文档，不影响文档与代码验证结果。

## 个人版 0.1.0 历史验证（2026-10-20）

日期：2026-10-20。产品基线v1.2；交付截止 dsh 后台之前。这里只把可执行开发验证标为完成，不把专业审阅、真实案例或用户反馈推定完成。

## 已执行检查

| 检查 | 结果及范围 |
|---|---|
| 单元与回归 | unittest 40项通过；其中一项覆盖15个标记合成风险情境，不把它们算成真实工程评价 |
| Skill 结构 | 系统 skill-creator 的 quick_validate.py 返回 Skill is valid；不证明技能决策质量 |
| 本机功能 | check_local.py 真实调用本地规范库，完成13类操作及备份校验、恢复图片；没有模型 API |
| 当前 Codex 调用 | 实际读项目 Skill／请求参考并执行 CLI，不仅检查文件存在 |
| 原页与引用 | 主 Agent 实际查看JTG 5120—2021第14页，核对3.3.2，保存条件化适用声明并绑定答案 |
| 数据恢复 | 新进程 resume，备份清单验证；图片按恢复目录解析；单元检查原图片不存在时恢复仍有效 |
| 原项目边界 | 所列原规范关键文件前后指纹不变，未调用维护或原 img |
| 开发自查 | 修复上游参数顺序兼容、事实值借用依据、旧适用性复用、案例变化、备份路径和历史权限撤销问题，回归通过 |
| 流程对照 | 事后非盲自评（结论见下方「历史档案」）；没有独立性能／专业质量结论 |

检查命令：

    python -X utf8 -m unittest discover -s tests -v
    python -X utf8 scripts/check_local.py
    python -X utf8 C:/Users/Seven/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/road-diagnosis

## 需求与证据矩阵

| 需求 | 实现与证明 | 结论 |
|---|---|---|
| 当前入口与资产盘点 | P0 环境检查（结论见「历史档案」）、doctor 和真实 CLI 调用 | 开发完成；自动目录刷新未独立观察 |
| 关键追问、停止及候选分析 | Skill、4张草稿卡、briefing、answer与未知不重问测试 | 可试用；专业质量未验证 |
| 逐轮风险、纠正与来源 | risk.py、15情境、多轮与纠正回归、当前合成咨询 | 对应流程通过；真实识别率未知 |
| 规范查询、回源和适用性 | Specs固定入口、实际原页、具名审阅与claims绑定 | 技术流程通过；语义及效力不作全面认证 |
| 空库与案例审核 | 空库联调、隔离发布/撤回/旧索引/引用回归 | 机制完成；没有真实可引用案例 |
| 保存、恢复和导出 | 修订快照、完整性、冲突锁、备份恢复与示例记录 | 对应操作通过 |
| 权限与注入 | 受限输出、授权撤销覆盖历史、固定操作、字面查询、恶意来源作为数据的回归 | CLI边界通过；不证明宿主全面隔离 |
| 使用说明及限制 | README、operations、known-limitations及产品实施记录 | 已交付 |
| 不进入后台／页面 | 无相关服务、API密钥或前端目录 | 范围遵守 |
| 专业审阅、真实闭环、用户反馈 | 当前不存在对应证据 | 明确未验证，未冒充完成 |

## 历史档案（2026-10）

2026-11-14 整理仓库时删除了三份早期记录（`docs/host-usage-check.md`、`docs/workflow-comparison.md`、
`docs/local-validation.json`），要点如下，细节不再单独维护：

- **环境基线（2026-10-20）**：Python 3.12.10、Git 2.55、Node 可用；业务代码只用标准库，未新增依赖。
  原工具 doctor 全通过（PyMuPDF、Office 文档依赖、COM、Tesseract 与中文包）；书目 13 项不等于逐本核验。
  当时确认「只读入口」边界：list/toc/clause/grep/read 可用，index/ocr/remove/set-page/cleanup 等维护命令不可调用。
- **流程对照（事后非盲自评）**：同一段合成输入下比较「常规回答」与「项目工具流程」，结论是后者在
  追问、来源与边界上更可追溯；作者自己说明这不是随机对照、不能用来宣称诊断质量提升。
- **示例资产**：旧验证记录曾用独立 `--store` 保存一份 12 修订的合成咨询，原文件已在 2026-10-25 授权清理中删除，
  不能按旧路径恢复；需要示例时跑当前合成检查脚本重新生成。

## 历史合成示例（原文件已清理）

以下编号和路径仅记录 2026-10-20 当时检查，原文件已在 2026-10-25 授权清理中删除，不能继续作为可恢复示例。记录全部为合成输入，规范页面是真实本地来源，仅用来验证工具和条件化引用。

- 咨询编号：bf76403cf5c440fb89e3250283d63675。
- 修订：12，包含多轮、事实纠正、空库查询、实际看图审阅和已绑定意见。
- 独立验证存储：C:\Users\Seven\AppData\Local\RoadMaintenanceExpert\2f50959555be\validation\codex-demo-20261020。
- 报告：上述目录 exports/bf76403cf5c440fb89e3250283d63675/r12/consultation.md。
- 当时示例使用独立 --store，不混入日常咨询列表；现已不能按此目录恢复，需要示例时运行当前合成检查脚本。

2026-10-20 最终检查时，独立副本的 backup-verify、resume 及图片定位通过，报告当时存在。工具和标准的完整原文留在仓库外，不把证据原文复制到项目记录里。

## 未完成的评价与后续

专业人员审阅知识／规则／典型输出、真实工程后续验证、用户试用反馈、独立同信息模型比较、更多领域与30～50题扩展均需后续材料或评价，不在本次开发成果中虚构。P0～P2可开发工具已交付，P2“实际效果成熟”尚未证明，不自动进入P3。

本轮没有提交、推送、发布、安装额外依赖或修改全局客户端配置。后续若需版本提交，按用户请求另行审查。

## 补充信息弹窗约定更新（2026-10-25）

- 修改范围：项目 Skill 的追问交互和 README 使用说明。优先使用宿主可用的结构化提问工具，通常先问一个问题；保留正文降级、紧急提示先行、未知不重问、实际回答通过 turn 保存等约定。此次未修改 Python 业务逻辑。
- 自动验证：Skill quick_validate 返回 Skill is valid；unittest 40 项通过；check_local.py 本机集成通过，含规范查询／回源／渲染、空案例库、多轮、导出与备份恢复，所检查原规范文件指纹不变。
- Agent 文本自查：核对了工具和模式可用性、单题单一事实、中性选项、未回复／未提交预选项不作事实、unknown 不作否认、异步真实答复后再继续依赖判断。此项不是人工或专业审核。
- 未验证：本轮未进行用户实际弹窗选择到咨询保存的端到端交互，也未验证其他已打开聊天是否重新加载 Skill；自动测试不证明弹窗显示或技能执行质量。此前发现的默认存储路径重定向问题不在本次修改范围，本机集成使用仓库外隔离目录。
- 联调结果：C:\Users\Seven\AppData\Local\Temp\roadexpert-functional-r8m2zm8j\functional-result.json。输入为全合成资料；原页仅渲染，没有在本轮声明看图或专业核验。

## 个人试用版 0.1.1：存储、问诊、沉陷意见与恢复（2026-10-25）

用户授权开发选项 1／2／3／4。本轮保持 P0～P2 范围，未提交、推送或发布。

### 改动与核验

| 项目 | 实现 | 本轮验证 |
|---|---|---|
| 默认存储 | 保留 Windows 普通目录与应用缓存的合并视图；只接受路径结构与文件身份都匹配的 LocalCache 映射；继续拒绝越界、子路径符号链接和目录联接 | 默认 doctor 通过；6 份既有咨询通过完整性读取，原 JSON 前后指纹一致；未搬移、删除或改写记录；隔离模拟合法／非法映射与修订文件链接 |
| 弹窗问诊 | question-ask 保存待答问题；宿主显示；turn.question_responses 保存真实提交；question-close 区分未答；直接文字补充可关闭对应待答项 | 合成测试覆盖中断、未知、自由补充、未提交、重复提交、迟到回复、纠正、跨咨询 ID 和过期修订；真实问题工具已发起并收到用户“既要简短，也要完整分析”的答复，该偏好只用于技能，未写入工程事实 |
| 沉陷意见 | 增加 pavement-subsidence-v1 约定与字段检查：事实联系和缺口、区分线索、不同核查结果的后续方向；导出保留这些内容；同一份回答先摘要再完整分析 | 合成意见缺少关键分析字段时拒绝保存；完整字段能保存、导出；Agent 阅读导出文本自查。知识与工程内容仍待专业审核 |
| 历史恢复 | 摘要包含上次意见是否过时、新增原话、纠正、前后两份意见变化、信息缺口、待答与核查事项；兼容旧式追问记录；获准列表显示标题 | 独立 CLI 进程恢复、旧格式兼容、备份后恢复一致；受限及撤销授权的历史摘要／标题不外露；核查完成情况不自动推断 |

### 自动检查

- `python -X utf8 -m unittest discover -s tests -v`：56 项全部通过（原有40项＋本轮16项）。
- Skill `quick_validate.py`：Skill is valid。
- `python -X utf8 scripts/check_local.py`：本机规范查询、回源、渲染、空库、多轮、导出与备份恢复通过；所检查原规范文件指纹不变。
- `python -X utf8 scripts/check_trial.py`：19 次跨进程操作完成；默认存储、既有记录完整性、全合成问诊、沉陷意见、纠正、恢复、导出、备份及恢复通过。

结果文件（均在仓库外）：

- 本机规范联调：`C:\Users\Seven\AppData\Local\Temp\roadexpert-functional-q_zj1haz\functional-result.json`。
- 新流程联调：`C:\Users\Seven\AppData\Local\RoadMaintenanceExpert\synthetic-trial-_0rc2ptu\trial-result.json`。
- 全合成咨询编号：`6123508f2c7f494a8431dd096232d479`，独立存储，不混入日常咨询列表。

### 验证边界

- 已收到真实问题工具的用户答复；未通过 UI 自动化核验弹窗外观，工程问题的“真人点击→咨询入库”完整链路尚未以真实咨询验证。程序写入与恢复链路使用合成输入验证。
- 既有资料仅在本地做完整性读取和指纹比较，没有向模型返回其原文。未证明跨用户、其他打包方式或所有系统重定向均兼容。
- 本轮没有人类工程专业审核、现场检测、真实后续结果或独立诊断质量评价；字段齐全和自动测试通过不代表工程判断正确。原页在联调中只渲染，不声明本轮已看图。
- Agent 自查发现并处理了旧式追问在恢复摘要中遗漏的问题，并补回归测试；同步将合成示例中混合已知／未知的原话拆分保存，避免把整句都标为 known。

## 个人试用版 0.1.2：按需保存与旧数据清理状态（2026-10-25）

用户明确授权改为按需保存，并清理已有记录。功能修改已完成；首次删除被执行环境拦截，后续已完成清理，见本文件末尾补记。

### 已实现并验证

- start 默认 temporary；保留当次多轮、风险、待答与证据状态，不进入历史列表、不要求用户记编号。最后写入后24小时过期，后续调用清理；明确结束时 finish 清理，未增加后台定时任务。
- save 要求真实用户明确请求的声明及依据，转为 saved 后才进入历史列表；保存不更改外发权限。export 需要明确用户请求，保留导出文件但不自动归档会话。
- backup 仅复制已保存咨询及关联证据／导出，不夹带其他临时记录。清理临时状态时保留其他会话仍引用的证据和图片，不根据 receipt 中 source_path 删除规范源文件。
- 原56项与新增8项保留策略回归，共64项 unittest 全部通过。修复了备份测试中主动保存后继续使用旧 revision 的问题后重新通过。
- check_local.py 和 check_trial.py 均通过；默认 doctor 返回0.1.2、temporary、24小时。两套集成检查现在使用自有临时目录，在退出时自动删除自身测试数据，返回 artifacts_retained=false；旧版历史样例不受该自动测试清理影响。
- Skill quick_validate 通过。清理脚本 PowerShell 语法解析和只读预览通过。没有本轮工程专业审核或新的现场效果验证。

### 首次旧数据清理尝试（历史状态，后续结果见补记）

- 已盘点本项目默认记录目录、Windows 对应应用缓存、旧咨询处理副本、合成测试与测试备份，预览39个逻辑路径；包含Windows别名，不能据此声称有39份独立数据。
- 批量固定父目录删除命令和随后单个固定测试目录的小范围删除均被自动审批拒绝，工具只返回 `blocked by policy`，未提供具体原因。两条命令均未启动，没有旧数据删除成功的证据。
- 随后只读复核仍有6份默认咨询，文件仍在。原始附件、原规范库、Documents 中已单独交付的Word文档及Codex聊天记录不在清理范围。
- 已提供 scripts/clear_local_records.ps1：无参数仅预览；用户在本机PowerShell传 -Execute 才永久清理列出的项目记录、缓存、库外导出副本与测试备份。检查固定父目录、路径解析、符号链接／联接及占用锁；实际删除尚未运行验证。脚本执行后仍需检查剩余路径与默认咨询数。
- 本轮未提交或推送代码；没有改写原规范项目。

### 清理完成补记（2026-10-25）

- 用户再次明确要求“清理旧记录”后，重新读取脚本并预览；核验固定父目录、路径解析、链接／联接和占用锁后执行 `scripts/clear_local_records.ps1 -Execute`，退出码0。
- 原39个逻辑路径中删除32个，其余7个因对应别名已清理而不存在。清理后再次预览 LogicalPathCount=0；普通目录及Windows应用缓存对应项目存储中的剩余记录文件数=0。旧咨询、关联证据副本、项目存储内导出、处理缓存、测试及备份均在核定范围内清除。
- 对2份原始附件、1份独立交付文档及原规范工具的配置和脚本，共5个受保护文件做清理前后SHA-256比较，全部不变。未清理Codex聊天记录、项目源码或规范源库。
- 本轮仅执行数据清理并同步文档，没有修改程序行为；核验采用清理结果、二次预览、文件计数和受保护文件指纹，不重新生成咨询测试数据。历史验证中的样例路径已失效，保留历史检查结论但不能再恢复那些样例。

## 0.1.3 分领域咨询与按需交付（2026-10-29）

用户表示开发选项1、2已完成，本轮授权为3、4。本轮仅推进坑槽裂缝、边坡、桥涵分析及按需交付，不重做前两项，也不据此宣称本轮验证了它们。

- 新增 pavement-distress-v1、slope-instability-v1、bridge-culvert-v1：检查领域上下文、候选推理与区分线索、核查结果分支，未知可以明确保留。旧沉陷模板与无模板接口保留。新增一张坑槽裂缝草稿卡，总计5张，既有边坡、桥涵卡关联对应模板；没有升级专业审核状态。
- answer.deliverables 支持现场处置建议、检测委托要点、部门回复草稿；export.kind 按需导出一种 Markdown／JSON。拒绝无意见、无对应内容、非法类型和过时意见；失败不创建导出目录。专项交付包含当前事实来源、风险、规范摘录／页码／适用性／核验范围及边界，不自动夹带全部原话和历史；不自动归档或外发。
- 自动验证：python -X utf8 -m unittest discover -s tests -v，共74项通过，其中新增10项回归覆盖模板不匹配、上下文缺失、推理与分支缺失、未知事实引用、交付字段类型、三种导出及来源核验保留、过时拒绝、显式请求与已有安全关口。
- 本机集成：check_local.py 通过，真实本地规范查询、原页读取和渲染、空案例、多轮、导出、备份等链路可用，upstream_fingerprints_unchanged=true；check_trial.py 通过，既有咨询JSON保持不变。两套检查均返回 artifacts_retained=false。
- 新增 check_advice.py 通过真实 stdin CLI 验证三类新增分析及九份专项导出、知识卡路由、最新信息更新后的过时拒绝、临时咨询不入历史及明确导出文件不随 finish 删除。测试自有目录退出时全部清除，artifacts_retained=false。
- 技能 quick_validate 通过。代码自查将规范依据共用渲染，避免专项交付丢失核验范围；不按标题切割用户自由文本，不为专项文件生成完整历史报告。
- 人工范围：阅读实现和合成输出断言、技能路由及文档自查；没有现场验收、工程专业审核、真实病因正确性盲评或本轮弹窗实际点击验收。没有Word/PDF新增输出、提交、推送或发布。

## 0.1.4 照片辅助观察 Word按需导出 处理方向比较（2026-10-29）

用户选择后续开发选项1、3、4。本轮增加照片辅助观察、Word按需导出及条件化方向比较；没有增加调查任务完成跟踪。

- 照片：photo-add／photo-show／photo-observe。多图登记、JPEG／PNG／WEBP解码、尺寸与文件大小限制、去除EXIF等源元信息、归属与副本指纹检查；保留用户提供的地点／时间／方向及未知，不推断GPS。实际查看后才能记录带图中区域、限制、查看者及时间适用性的观察。图片观察与用户陈述、系统假设分开，不虚构用户turn。当前／历史时间声明需依据；未确认默认unknown。
- 续办与生命周期：新照片或观察使旧意见过时，规范适用性需重新核对。照片副本位于本次sessions目录，临时结束／过期清理沿用原策略，原附件不改动。主动保存后纳入独立备份恢复；图片无法解除旧风险触发。受限会话不能通过照片接口泄露内容。
- 方向比较：answer.comparison，2至5个实际方向，条件、当前有效事实、缺失证据、可能优势、限制与下一步；缺证据可以全部保持待查。不允许自动评分、概率或批准标签；规范判断仍使用claims及合格审阅。比较进入完整及专项文件，事实引用在正文显示为可读内容。
- Word：export(format=docx)仍要求user_requested=true，include_photos=true另须真实附图要求；支持完整意见、现场建议、检测委托要点、部门回复草稿。生成所选Word，不自动另附全历史JSON、不归档或上传；无有效意见、意见过时或文档运行环境缺失时拒绝。照片嵌入后不依赖临时副本继续存在。正文来源状态使用中文，比较表可编辑、跨页重复表头并尽量保持单行完整；标题黑色无装饰线，图片按比例缩放，带说明与页码。
- 自动验证：python -X utf8 -m unittest discover -s tests -v，共88项通过（原74项加14项）。覆盖照片登记不等于看图、元信息清理、坏格式及旧修订拒绝、跨会话／撤权／指纹变化、观察与用户turn区分、未知不升级、图片不解除旧风险、照片使意见过时与规范再审阅、原图保护、照片独立备份恢复、比较字段／事实／评分约束、Word按需与过时拒绝、附图选择及清理后文件仍可用、运行环境缺失与标题边框回归。
- 本机集成：check_local.py、check_trial.py、check_advice.py通过；真实规范工具链仍可用，原规范源指纹不变，既有咨询JSON不变。新增check_media_delivery.py通过真实stdin入口验证两张横／竖合成图片、照片观察、方向比较、四种嵌图Word及临时副本清理；合成原图哈希不变，无自动归档。
- 排版核验：捆绑文档运行环境生成DOCX。render_docx.py因缺少LibreOffice soffice.exe无法使用，改用本机Microsoft Word只读打开并导出PDF，再用捆绑Python的PDFium生成页面图片查看。修复默认Title蓝色底边及比较表同一行跨页拆分后，复核四种最终样例，共20页（完整意见7、部门回复4、现场建议4、检测委托5）；检查标题、中文、表头、行内容、横／竖图、图注和页码，未见文字裁切、重叠或图片失真。普通CLI导出仍返回待渲染检查，不伪称程序自动完成看图。
- 技能quick_validate通过。人工范围为实现及技能自查、合成文档排版核对；没有现场照片病因准确性验收、专业工程审核、真实处治效果验证或本轮问题弹窗点击验收。未修改原规范项目、安装依赖、调用独立模型API、提交或发布。
- 本轮QA在仓库外保留合成Word／PDF／页面图片供检查。交付前核验固定Temp父目录、四个明确创建的QA路径及全部后代无重解析点后，清理命令被自动审批拒绝，仅返回blocked by policy，没有提供具体原因，命令未启动。四个目录仍为 C:/Users/Seven/AppData/Local/Temp/roadexpert-media-qa-20261029-01、同前缀02／03／04；仅含本轮合成测试文件，没有真实咨询或规范源。未改用其他工具绕过拒绝。默认集成检查及单元测试自有TemporaryDirectory仍正常清理自身文件；工具验证过临时照片副本清理、明确导出保留和原图不变。验证结论保留于本文，不将测试图片当真实案例。

## 0.1.5 交付前一致性检查（2026-10-30）

用户选择本轮开发选项4。新增只读delivery-check并接入export；未开发检测报告解读、调查结果跟进或多时点照片趋势判断。

- 检查范围：最新意见、有效事实引用、规范原页及必要原页图片指纹、审阅适用性、案例查询及当前版本、照片归属与副本、所选专项内容和附图要求。明确错误阻止当前交付，失败不创建或覆盖目标文件；没有意见、过时意见或撤回案例不再作为普通完整意见导出。
- 文字提示：数值与单位、标准号、条号未直接匹配当前已知文字事实或有效审阅时，返回字段位置与摘录；正文明确选用比较表中证据不足／当前不支持的方向时提示可能冲突。仅扫描本次所选内容及共用部分，不把无关专项草稿疑点混入。复杂语义、单位换算、工程含义和规范现行性由宿主另核，不把没有警告称为审核通过。
- 导出边界：默认仍仅在用户明确要求时生成文件；检查不归档、不发消息、不调用模型或联网。export自动重查，可用expected_check_sha256绑定修订、内容、来源状态、kind／format及附图范围；导出期间锁定咨询，待答问题等状态变化也会使旧检查失效。历史追溯仅在明确history_only要求下生成独立文件名并标注非当前交付，不可用于Word或专项意见。
- Word发布：在临时DOCX中核对嵌入媒体字节集合与本次所需照片、所需图注文本存在，之后才替换目标。图片不对应、结构损坏或图注缺失时拒绝交付并清理临时文件。该检查不证明图片解释、图注语义和排版正确；仍返回待渲染核对状态。
- 单元测试：python -X utf8 -m unittest discover -s tests -v，共101项通过（原88项加13项）。覆盖只读及人工边界、空／旧意见阻止和显式历史标注、检查后内容／来源／范围／待答记录变化、规范源变化后不覆盖旧导出、缺失／未查看照片、数值条文疑点定位与有来源文字匹配、所选范围、明确比较冲突及否定、受限检查内容不返回、无效事实引用、Word错误照片或缺图注不发布。旧历史导出回归改为先断言普通交付拒绝，再明确历史请求，保留原追溯语义。
- 本机集成：check_local.py、check_trial.py、check_advice.py、check_media_delivery.py、check_delivery.py五套均通过。真实本地规范查询／读取／渲染、问答恢复、多领域及三种专项导出、两张横／竖合成图与四种Word导出、检查疑点／过时拒绝／历史标注／绑定检查后导出均可用。原规范源指纹不变，既有咨询JSON不变；全部自有合成临时测试返回artifacts_retained=false。
- 技能quick_validate通过。人工范围为代码与技能工作流自查、合成检查返回值及文件结构核对；没有新增Word版式，本轮未重做0.1.4的页面图片视觉验收，没有工程专业审核、真实全文矛盾识别率验收或现场验证。未重试上一轮被阻止的旧QA目录删除，没有修改原规范项目、安装依赖、提交或发布。
