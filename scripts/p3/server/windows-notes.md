# Windows Server 备选方案（未实测）

Linux 是主路径；如果最终买了 Windows Server，按下面的差异执行。架构不变：一个地址、
按访问者隔离运行时、共享口令、本地模型代理。

## 差异清单

| 项目 | Linux | Windows |
|---|---|---|
| 服务托管 | systemd | NSSM（`nssm install RoadChat`）或计划任务 |
| 反代 + 口令 | nginx + `auth_basic` | nginx for Windows 或 Caddy（`basicauth`） |
| 证书 | certbot | win-acme 或 Caddy 自动 HTTPS |
| 专用账户 | `useradd roadchat` | `New-LocalUser roadchat`，服务以此账户登录 |
| 可写目录 | `/srv/road/work`（700） | `C:\road\work`，ACL 只给 roadchat |
| 只读共享 | root 755 | `C:\road\app`、`C:\road\specs` 只给读取 |
| 进程树停止 | `killpg` | 代码里已保留 `taskkill /T` |
| 夜间重启 | systemd timer | 计划任务 `Restart-Service RoadChat` 04:00 |

## 步骤

1. 安装 Node 24（dsh 要求 ≥ 24.9.0）、Python 3.12（勾选 Add to PATH）、Git。
2. `npm i -g @deepseek-ai/dsh`，`dsh --version`。
3. `New-LocalUser roadchat -NoPassword`（或设强口令），建 `C:\road\{app,specs,work}`，
   `icacls` 收紧：work 只给 roadchat 完全控制，app/specs 只读。
4. 仓库放 `C:\road\app`，规范库放 `C:\road\specs\guifanchaxun`，`data\` 一并 rsync。
5. 配置：`C:\road\etc\config.json`、`roadchat.env`、`proxy.env`（含真实 key，ACL 只给管理员）。
6. 设机器级环境变量 `ROAD_EXPERT_CONFIG`、`DEEPSEEK_BASE_URL=http://127.0.0.1:8096`；
   `DEEPSEEK_API_KEY` 只在代理服务里配成真实值，前端服务用占位值。
7. NSSM 注册两个服务：
   - RoadModelProxy：`python -X utf8 C:\road\app\scripts\p3\proxy\model_proxy.py --port 8096`
   - RoadChat：`python -X utf8 C:\road\app\scripts\p3\chat\app.py --host 127.0.0.1 --port 8095 --home C:\road\work`
8. nginx/Caddy 反代 443 → 127.0.0.1:8095，加共享口令与 `proxy_buffering off`。
9. 计划任务每天 04:00 重启 RoadChat。
10. 验收项与 Linux 完全相同（见 ADR 0005）。

已知风险：Windows 下 `roadchat` 账户的 ACL 边界比 Linux 更容易配错；规范工具
`guifanchaxun` 在 Windows 上原本就验证过，这一点反而比 Linux 稳。两条路都要以
「门槛脚本」结果为准，不靠推断。
