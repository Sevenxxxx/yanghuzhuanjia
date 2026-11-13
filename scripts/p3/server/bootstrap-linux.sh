#!/usr/bin/env bash
# 一次性初始化（Ubuntu 24.04 LTS）。需要 root。
# 只装系统依赖、建用户与目录；仓库/规范库/密钥的摆放见 README。
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/road/app}"
SPEC_DIR="${SPEC_DIR:-/srv/road/specs}"
WORK_DIR="${WORK_DIR:-/srv/road/work}"
ETC_DIR="${ETC_DIR:-/etc/road-chat}"
SERVICE_USER="${SERVICE_USER:-roadchat}"
NODE_MAJOR="${NODE_MAJOR:-20}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 root 运行" >&2
  exit 1
fi

echo "== 系统依赖 =="
apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-pip nginx certbot python3-certbot-nginx \
  git rsync curl ca-certificates ufw

echo "== Node ${NODE_MAJOR} + dsh =="
curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
apt-get install -y nodejs
npm install -g @deepseek-ai/dsh
dsh --version

echo "== 用户与目录 =="
id -u "${SERVICE_USER}" >/dev/null 2>&1 || \
  useradd --system --create-home --home-dir "/var/lib/${SERVICE_USER}" --shell /usr/sbin/nologin "${SERVICE_USER}"

install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 700 "${WORK_DIR}"
install -d -m 755 "${APP_DIR}" "${SPEC_DIR}"
install -d -m 750 "${ETC_DIR}"
install -d -m 755 /var/log/road-chat

echo "== Python 依赖（规范原页渲染、照片） =="
python3 -m pip install --break-system-packages pymupdf pillow

echo
echo "已完成系统层。接下来按 scripts/p3/server/README.md："
echo "  1) 把项目仓库放到 ${APP_DIR}（git clone 或 rsync，含 .agents/skills）"
echo "  2) 把规范库放到 ${SPEC_DIR}/guifanchaxun（只读）"
echo "  3) 写 ${ETC_DIR}/config.json（spec_skill 指向 ${SPEC_DIR}/guifanchaxun/tools/guifan-chaxun）"
echo "  4) 写 ${ETC_DIR}/roadchat.env 与 ${ETC_DIR}/proxy.env"
echo "  5) 运行 install-app.sh 安装服务与 nginx"
