# ADR 0002：P3 本机单实例 Web

日期：2026-11-11。用户明确要求「开始 P3，先在这台电脑试」。上一版 [ADR 0001](0001-personal-runtime.md) 的个人版假设到此仍对咨询工具成立，本 ADR 只记录新增的 Web 入口及其边界。

## 背景

用户要自己先用上「一个 Web」，随后再部署到服务器、再邀请同事。第一步的范围因此只有一个人、一台机器、一个实例。原计划里的 Tailscale、按人隔离、每人一个 home 都不在本步。

## 决定

1. **专用实例，独立 home 与端口**：`%USERPROFILE%\dsh-roads\home`，默认端口 8090，监听本机局域网 IPv4（默认 `192.168.1.5`），回环访问仍可用。不动 3080 开发 GUI 的 profile 与会话。
2. **默认 agent 是「道路养护专家」**：`scripts/p3/road_expert.patch.yml` 在 profile patch 层声明 `preset-road` 并设为默认；插件面只有咨询需要的（pwsh、文件读写、搜索、skill、提问、todo、present、web、compaction），不含 bash、计划模式、subagent/workflow、schedule、goal、插件管理。
3. **模型走 `deepseek-account`**，与 3080 一致；权限保持 `danger-full-access`，因为 `road.py` 必须写仓库外存储。
4. **凭据不复制、不共享**：实例首次使用需在页面里自行登录 DeepSeek 账号。实测把 3080 的 `.credentials.yaml` 复制过去后，账号路由仍报 `ACCOUNT_SIGN_IN_REQUIRED`（记录里 `payload` 为空），复制只会多一份密钥副本，故取消。
5. **咨询记录沿用我的个人存储**（`%LOCALAPPDATA%\RoadMaintenanceExpert\2f50959555be`）：本阶段使用者是我本人，记录应当连续；按人隔离是服务器阶段的需求。
6. **不改 `src/roadexpert/`**；只新增 `scripts/p3/`（preset、启动器、手册）与回归测试。版本记 0.1.9。

## 代价与已接受的限制

- 局域网内是明文 HTTP，bearer cookie 会以明文经过同一网段；cookie 有效期设为 7 天。仅限内网自用。
- 实例是「一把钥匙」：所有打开同一链接的浏览器共享 owner Peer，彼此能看到同一份会话。本阶段只有我一个人，不构成问题，但**不能把这套直接给同事共用**。
- `danger-full-access` 意味着经该实例的 agent 能读写本机文件；使用者是我本人。
- 账号额度与 3080 共用同一个 DeepSeek 账号。

## 实现中确认的事实（后续排查用）

- `dsh web --host <局域网 IP>` 合法；`/` 的浏览器认证对**回环来源直接放行**，所以本机 curl 无法验证 token 交换，只有另一台机器能验。
- `DETACHED_PROCESS` 会让 Node 写到重定向文件里的 `console` 输出丢失（URL 行不落盘）；改用 `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` 后既脱离父控制台又能正常写日志。
- 新 home 的账号路由必须交互登录；headless 用同一个 home 也无法替代登录。

## 回滚

`python -X utf8 scripts/p3/local_web.py reset --yes`：停进程并删除整个 `%USERPROFILE%\dsh-roads`。仓库内的 `scripts/p3/` 与文档改动可单独回退，不影响 3080 开发 GUI 与咨询存储。

## 服务器阶段的差异

到服务器上至少要改：home 放持久目录；反向代理 + TLS 终结，`--trusted-host` 加对外域名，实例仍只监听回环；**每个同事一个实例**（独立 home、端口、咨询存储），不要共用；权限收紧并把 `road.py` 存储纳入可写范围。
