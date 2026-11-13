#!/usr/bin/env bash
# 在已跑过 bootstrap-linux.sh、且仓库与规范库已就位之后运行（root）。
# 安装 systemd 服务、nginx 站点与共享口令。
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/road/app}"
ETC_DIR="${ETC_DIR:-/etc/road-chat}"
WORK_DIR="${WORK_DIR:-/srv/road/work}"
DOMAIN="${DOMAIN:?请设置域名，例如 DOMAIN=road.example.com}"
SERVICE_USER="${SERVICE_USER:-roadchat}"
BASIC_USER="${BASIC_USER:-team}"
BASIC_PASS="${BASIC_PASS:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 root 运行" >&2
  exit 1
fi
if [[ ! -f "${APP_DIR}/scripts/p3/chat/app.py" ]]; then
  echo "仓库不在 ${APP_DIR}" >&2
  exit 1
fi
if [[ ! -f "${ETC_DIR}/roadchat.env" || ! -f "${ETC_DIR}/proxy.env" ]]; then
  echo "缺少 ${ETC_DIR}/roadchat.env 或 proxy.env（见 README）" >&2
  exit 1
fi

echo "== 服务 =="
install -m 644 "${APP_DIR}/scripts/p3/server/systemd/road-chat.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/scripts/p3/server/systemd/model-proxy.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/scripts/p3/server/systemd/road-chat-restart.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/scripts/p3/server/systemd/road-chat-restart.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now model-proxy.service road-chat.service
systemctl enable --now road-chat-restart.timer

echo "== 共享口令 =="
if [[ -z "${BASIC_PASS}" ]]; then
  BASIC_PASS="$(openssl rand -base64 12)"
fi
printf '%s:%s\n' "${BASIC_USER}" "$(openssl passwd -apr1 "${BASIC_PASS}")" > /etc/nginx/road.htpasswd
chmod 640 /etc/nginx/road.htpasswd
chown root:www-data /etc/nginx/road.htpasswd

echo "== nginx =="
sed "s/__DOMAIN__/${DOMAIN}/g" "${APP_DIR}/scripts/p3/server/nginx/road-chat.conf.tpl" \
  > /etc/nginx/sites-available/road-chat
ln -sf /etc/nginx/sites-available/road-chat /etc/nginx/sites-enabled/road-chat
nginx -t
systemctl reload nginx

echo
echo "部署完成。"
echo "  地址： https://${DOMAIN}/"
echo "  口令： ${BASIC_USER} / ${BASIC_PASS}   （请立刻保存，之后不再显示）"
echo "  证书： certbot --nginx -d ${DOMAIN}"
echo "  自检： ${APP_DIR}/scripts/p3/server/health.sh"
