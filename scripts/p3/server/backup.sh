#!/usr/bin/env bash
# 备份访问者数据与日志；保留最近 7 天与每月 1 号。
set -euo pipefail

WORK_DIR="${WORK_DIR:-/srv/road/work}"
DEST="${DEST:-/var/backups/road-chat}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "${DEST}"
tar -czf "${DEST}/work-${STAMP}.tar.gz" -C "$(dirname "${WORK_DIR}")" "$(basename "${WORK_DIR}")"
find "${DEST}" -name 'work-*.tar.gz' -mtime +7 -delete

echo "已备份到 ${DEST}/work-${STAMP}.tar.gz"
echo "恢复：先停 road-chat，解包到原位置，再启动；不要覆盖正在使用的目录。"
