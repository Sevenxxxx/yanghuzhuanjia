# 变更记录

版本号以 `src/roadexpert/__init__.py` 为准；详细验证记录见 [docs/validation.md](docs/validation.md)。


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
