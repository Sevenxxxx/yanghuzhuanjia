#!/usr/bin/env bash
# 上线门槛自检：不通过就不要把口令发给同事。
# 用法：sudo bash scripts/p3/server/acceptance.sh
set -uo pipefail

APP_DIR="${APP_DIR:-/srv/road/app}"
WORK_DIR="${WORK_DIR:-/srv/road/work}"
SERVICE_USER="${SERVICE_USER:-roadchat}"
pass=0
fail=0

check() {
  local name="$1"
  shift
  if output="$("$@" 2>&1)"; then
    printf '  ✓ %s\n' "${name}"
    pass=$((pass + 1))
  else
    printf '  ✗ %s\n    %s\n' "${name}" "$(printf '%s' "${output}" | head -3)"
    fail=$((fail + 1))
  fi
}

echo "== 1. 程序 =="
check "dsh 已安装" dsh --version
check "node >= 20" node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'
check "python 依赖（pymupdf / pillow）" python3 -c 'import fitz, PIL'

echo "== 2. 项目工具（以 ${SERVICE_USER} 身份）=="
check "road.py --doctor" sudo -u "${SERVICE_USER}" env -C "${APP_DIR}" python3 -X utf8 scripts/road.py --doctor
check "规范检索一条" bash -c "printf '%s' '{\"op\":\"spec-search\",\"query\":\"沥青路面养护\"}' | sudo -u '${SERVICE_USER}' env -C '${APP_DIR}' python3 -X utf8 scripts/road.py -"

echo "== 3. 服务 =="
check "road-chat 运行中" systemctl is-active --quiet road-chat.service
check "model-proxy 运行中" systemctl is-active --quiet model-proxy.service
check "前端健康检查" curl -fsS --max-time 5 http://127.0.0.1:8095/api/health
check "代理转发（/models）" bash -c 'code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 http://127.0.0.1:8096/models); [ "$code" = "200" ]'
check "nginx 配置" nginx -t
check "夜间重启 timer" systemctl is-enabled --quiet road-chat-restart.timer

echo "== 4. 权限 =="
check "工作目录归 ${SERVICE_USER} 且 700" bash -c "stat -c '%U %a' '${WORK_DIR}' | grep -qx '${SERVICE_USER} 700'"
check "仓库对 ${SERVICE_USER} 不可写" bash -c "! sudo -u '${SERVICE_USER}' test -w '${APP_DIR}'"
check "规范库对 ${SERVICE_USER} 不可写" bash -c "! sudo -u '${SERVICE_USER}' test -w '${APP_DIR}/../specs'"
check "真实 key 不在前端 env 里" bash -c "! grep -q '^DEEPSEEK_API_KEY=sk-' /etc/road-chat/roadchat.env"
check "日志里没有 key" bash -c "! grep -rq 'sk-[A-Za-z0-9]\\{20,\\}' /var/log/road-chat /srv/road/work 2>/dev/null"

echo
printf '结果：%d 项通过，%d 项失败\n' "${pass}" "${fail}"
if [[ "${fail}" -gt 0 ]]; then
  echo "先修失败项再发口令。规范工具在 Linux 上不通时，转 windows-notes.md。" >&2
  exit 1
fi
echo "门槛通过。下一步按 README 第 6 节做双浏览器与攻击演练。"
