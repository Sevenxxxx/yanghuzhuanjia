# ADR 0003：纯聊天前端（自建页面 + SDK 后端）

日期：2026-11-11。用户要求「做一个新的 webui，不显示其他界面，就纯聊天 + 能放图片」。这是 [ADR 0002](0002-p3-local-web.md) 之后同一阶段内的界面替换，仍限本机与内网自用。

## 为什么不是 dsh 插件

先按宿主规范查过实现层，三条约束决定了插件做不到：

- `root` 槽是 `single` 且已被 shell 占用；`single` 槽二次注册直接抛 `single slot "..." already has a registration`（`packages/client/ui-slots/src/index.ts:1254`），没有隐藏/移除 API。
- 插件规范（`cordis-plugin-development/references/ui-plugin.md`）明确禁止替换 app root、在 `document.body` 追加第二个应用，也禁止读别的插件 DOM／样式来估算位置。
- 主题样式是 CSS modules，类名哈希化，按版本漂移，靠 CSS 硬藏不可维护。

结论：要「只有一个聊天区」，只能自建页面。

## 决定

1. **链路**：浏览器 → `scripts/p3/chat/app.py`（HTTP + SSE）→ `dsh --profile road-sdk`（stdio、按换行分帧的 JSON-RPC）→ `scripts/road.py`。
2. **profile 独立**：在试用 home 下新建 `road-sdk`（随附 `sdk` 模板初始化），patch 由 `road_expert.patch.yml` 生成：部署级 `system-prompt.personaPrefix` 承担专家职责，并关闭插件管理、计划模式、子代理、定时任务、goal 等与咨询无关的工具。**不搬 `preset-road`**——SDK 的根 agent 不走 preset，搬过来只会一直 pending 等 Web 端才有的 `agentPresets` 服务（实测每次启动刷一条警告）。
3. **模型走 API key**（`deepseek-official` / `deepseek-flash`）：SDK 无法复用账号登录，用户已同意按 token 计费；key 先读环境变量，再读 `.credentials.yaml` 的 `refs`。
4. **页面自持**：单文件 HTML/CSS/JS，只有标题、对话区、输入框、图片预览；转录只存内存。
5. **每次进页面都是新对话**：页面打开时 `POST /api/new` 取一个新会话 id（`web-<12位>`），运行时在第一次提问时创建该会话；同时**作废上一轮**——旧的进行中轮次不再阻塞新对话，挂在旧会话上的提问按协议回 `{cancelled: true}`。页面不持久化转录，刷新或重开即空白。服务端不做多用户、不做账号。

## 已接受的限制

- 服务本身**没有登录鉴权**，绑定局域网地址后同一网段可访问并消耗模型额度；只在内网自用。
- 刷新或关闭页面即丢弃当前对话（页面不存转录），服务端的会话文件仍留在 home 里，不做自动清理。
- 旧轮次被作废时，若模型正在生成，SDK 协议没有 cancel 方法；点「停止」的做法是**重启运行时**再用 `session/resume` 修复被中断的轮次。代价是约 10–20 秒不可用（期间的发送会等待），并且会中断同一运行时上其它标签页正在跑的轮次；收益是真正停住生成、上下文保留、同一会话立刻能继续问。
- 协议只推送持久事件，没有 token 级流式；页面按助手消息整段出现，中间以「正在查阅」指示。
- 审批通道不启用（`approvalRequests` 关闭，权限为 `danger-full-access`），因为无 GUI 应答方时审批会被判 unavailable；代价是文件写入不逐次询问，依靠 persona 与 AGENTS.md 约束。
- 图片只支持 PNG/JPEG/WebP/GIF，单条消息 ≤20 张、单张 ≤50 MiB（宿主的附件上限）。
- 用户提问（`ask_user_question`）以卡片形式在页面内回答；页面关闭或刷新会留下未答提问，重开服务即丢弃。

## 回滚

停掉 `chat/app.py` 即可；它不写仓库，数据只在 `%USERPROFILE%\dsh-roads`（home、日志）。dsh Web 实例（[ADR 0002](0002-p3-local-web.md)，端口 8090）不受影响，可继续用。
