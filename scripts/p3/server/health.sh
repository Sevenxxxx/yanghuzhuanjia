#!/usr/bin/env bash
# 服务自检：systemd 状态、健康检查、端口、运行时进程数。
set -uo pipefail

echo "== systemd =="
systemctl --no-pager --lines=0 status road-chat.service model-proxy.service 2>&1 | sed -n '1,20p'
echo
echo "== 健康检查 =="
curl -fsS --max-time 5 http://127.0.0.1:8095/api/health || echo "前端未响应"
echo
echo "== 代理 =="
curl -fsS --max-time 5 -o /dev/null -w "proxy /models -> %{http_code}\n" http://127.0.0.1:8096/models || echo "代理未响应"
echo
echo "== 监听端口 =="
ss -lntp 2>/dev/null | grep -E ':8095|:8096|:443' || true
echo
echo "== 运行时进程 =="
pgrep -af 'lib/bin.js|dsh' | head -20 || echo "没有运行时进程（没人说话时正常）"
echo
echo "== 工作目录占用 =="
du -sh /srv/road/work 2>/dev/null || true
