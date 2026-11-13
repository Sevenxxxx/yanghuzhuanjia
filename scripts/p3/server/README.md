# 服务器部署手册（Linux 主路径）

目标：一个域名、一个地址，同事输共享口令使用；每个访问者一个独立运行时，彼此不干扰。
架构与安全取舍见 [ADR 0005](../../../docs/decisions/0005-server-deployment.md)。

## 前置：要搬上去的四块东西

服务器上跑的东西分四层，前三层是程序与数据，第四层是部署配置。缺任何一块都起不来。

| # | 东西 | 从哪来 | 大小 | 注意 |
|---|---|---|---|---|
| 1 | Node 20 + `@deepseek-ai/dsh` | `bootstrap-linux.sh` 自动装（npm 全局） | 数百 MB | Ubuntu 自带的 Node 是 18，不够；不要用 `apt install dsh`（不存在） |
| 2 | `guifanchaxun` 工具 | `git clone`（远程 `Sevenxxxx/guifanchaxun`） | 约 20 MB | clone 只有代码 |
| 2a | 规范 PDF 原件 `guifansrc/` | **单独 rsync** | **3.79 GB** | 被 gitignore，不在仓库里 |
| 2b | 索引 `library_data/` | **单独 rsync** | **0.42 GB** | 也不在 git 里 |
| 2c | 该工具的 `config.json` | 手工改 | 1 个文件 | 现在是 Windows 绝对路径，必须改成服务器路径；`tesseract_cmd` 可不管（本项目不调 OCR 维护命令） |
| 3 | 本项目（含 skill 与 `data/`） | **rsync/scp**（本项目**没有 git 远程**，clone 不了） | 约 45 MB | `data/library/` 被 gitignore，rsync 会带上；`temp/` 不要带 |
| 3a | Python 依赖 | `pip install pymupdf pillow` | 约 100 MB | 规范原页渲染、照片 |
| 4 | `/etc/road-chat/` 配置 | 见第 3 节 | 4 个文件 | `config.json`、`roadchat.env`、`proxy.env`、`proxy.patch.yml` |
| 4a | systemd / nginx / 证书 | `install-app.sh` + `certbot` | — | 共享口令也在这里生成 |
| 4b | 真实 API key | 只进 `proxy.env` | — | 建议单独申请、设预算上限，试完轮换 |

其它前置条件：Ubuntu 24.04 LTS（root 或 sudo）、域名已解析到服务器且 80/443 可通。

## 1. 系统初始化

```bash
sudo APP_DIR=/srv/road/app bash scripts/p3/server/bootstrap-linux.sh
```

装好 Python、Node 20、`@deepseek-ai/dsh`、nginx、certbot、`roadchat` 用户与目录。

## 2. 放仓库与规范库

```bash
# 仓库（含 .agents/skills 与 data/）
sudo rsync -a --exclude temp/ ./ /srv/road/app/
# 规范库（只读，约 0.4GB）
sudo rsync -a --exclude .git/ /path/to/guifanchaxun/ /srv/road/specs/guifanchaxun/
sudo chown -R root:root /srv/road/app /srv/road/specs
sudo chmod -R a-w /srv/road/app /srv/road/specs
```

## 3. 三个配置文件（都在 `/etc/road-chat`）

`config.json`：

```json
{
  "spec_skill": "/srv/road/specs/guifanchaxun/tools/guifan-chaxun",
  "tool_timeout_seconds": 45,
  "privacy_default": "restricted"
}
```

`roadchat.env`（前端服务，key 用占位值即可）：

```
DEEPSEEK_API_KEY=proxy-held
ROAD_CHAT_PATCH=/srv/road/app/scripts/p3/server/proxy.patch.yml
ROAD_EXPERT_CONFIG=/etc/road-chat/config.json
ROAD_CHAT_COOKIE_SECURE=1
```

> 注意：`DEEPSEEK_BASE_URL` 对 dsh 的 Messages 适配器**不生效**（实测过），必须用
> `ROAD_CHAT_PATCH` 指向 `proxy.patch.yml`；否则前端会带着占位 key 直连官方接口，
> 表现为「模型没有返回内容」。

`proxy.env`（代理服务，真实 key；权限 600）：

```
DEEPSEEK_API_KEY=sk-真实值
```

```bash
sudo chown root:root /etc/road-chat/*.env /etc/road-chat/config.json
sudo chmod 600 /etc/road-chat/proxy.env
sudo chmod 640 /etc/road-chat/roadchat.env
sudo chown root:roadchat /etc/road-chat/roadchat.env
```

## 4. 装服务与反代

```bash
sudo DOMAIN=road.example.com bash scripts/p3/server/install-app.sh
sudo certbot --nginx -d road.example.com
```

脚本会打印共享口令（`team / …`），只显示一次。

## 5. 先过门槛，再加同事

```bash
sudo bash scripts/p3/server/acceptance.sh
```

一次跑完：程序安装、`road.py --doctor`、一条 `spec-search`、两个服务、代理转发、nginx 配置、
目录权限、日志里有没有 key。**全部 ✓ 才继续**；有 ✗ 就按提示修，不要先把口令发出去。

规范工具是原 Windows 项目，Linux 首次运行是首要风险；`acceptance.sh` 里第二组失败就转
[Windows 备选](windows-notes.md)。

## 6. 验收（见 ADR 0005 第 7 节）

给同事的口径直接发 [onboarding.md](onboarding.md)。

- 两个浏览器各自提问，答案不串台；
- A 正在长回答时 B 点停止，A 不受影响；
- 同一访问者连续开 20 个新对话后运行时被重建（`pgrep -af dsh` 看到新进程）；
- 攻击演练三条（删仓库、读密钥、外发）全部失败；
- `grep -r "sk-" /var/log /srv/road/work` 无命中。

## 7. 日常

```bash
systemctl status road-chat
journalctl -u road-chat -n 100 --no-pager
bash scripts/p3/server/backup.sh     # 备份访问者数据
bash scripts/p3/server/health.sh     # 自检
```

夜间 04:00 自动重启一次，清掉累积会话；访问者下一条消息会重建自己的运行时（约 10–20 秒）。
