#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || exit 1
systemctl disable --now emmc-web emmc-worker
rm -f /etc/systemd/system/emmc-web.service /etc/systemd/system/emmc-worker.service
if [ ! -L /usr/local/bin/emmc-studio ] && [ -f /usr/local/bin/emmc-studio ] && grep -q '^# eMMC Studio CLI launcher$' /usr/local/bin/emmc-studio; then
    rm -f /usr/local/bin/emmc-studio
fi
systemctl daemon-reload
echo '服务已卸载。保留 /opt/emmc-studio 和 /var/lib/emmc-* 中的源码、密码、备份及任务记录。'
