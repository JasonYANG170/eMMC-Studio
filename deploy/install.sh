#!/bin/sh
# Install a prebuilt distribution on Debian/Armbian; never change disk layouts.
set -eu
umask 022
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
check_only=0
skip_apt=0
for option in "$@"; do
    case "$option" in
        --check) check_only=1 ;;
        --skip-apt) skip_apt=1 ;;
        *) echo "Usage: sudo sh deploy/install.sh [--check] [--skip-apt]" >&2; exit 2 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo '请使用 sudo 或 root 运行。' >&2; exit 1; }
[ -d /run/systemd/system ] || { echo '需要正在运行的 Linux systemd。' >&2; exit 1; }
command -v apt-get >/dev/null || { echo '仅支持 Debian/Ubuntu/Armbian 的 apt 系统。' >&2; exit 1; }
command -v python3 >/dev/null || { echo '请先安装 python3。' >&2; exit 1; }
[ ! -L /opt/emmc-studio ] || { echo '/opt/emmc-studio 不允许是符号链接。' >&2; exit 1; }
if [ -e /usr/local/bin/emmc-studio ] || [ -L /usr/local/bin/emmc-studio ]; then
    [ ! -L /usr/local/bin/emmc-studio ] && [ -f /usr/local/bin/emmc-studio ] && grep -q '^# eMMC Studio CLI launcher$' /usr/local/bin/emmc-studio || { echo 'emmc-studio 命令已被其他文件占用，拒绝覆盖。' >&2; exit 1; }
fi
for file in dist/index.html backend/web.py backend/worker.py backend/cli.py docs/CLI.md deploy/emmc-studio-cli.sh deploy/initialize.py deploy/check_ready.py deploy/emmc-web.service deploy/emmc-worker.service README.md VERSION; do
    [ -f "$file" ] || { echo "缺少 $file；源码需要先在电脑运行 npm ci && npm run build。" >&2; exit 1; }
done
exec 9>/run/lock/emmc-studio-install.lock
flock -n 9 || { echo '另一个安装进程正在运行。' >&2; exit 1; }
python3 deploy/check_ready.py
[ "$check_only" = 0 ] || exit 0
if [ "$skip_apt" = 0 ]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-flask python3-waitress parted gdisk dosfstools exfatprogs ntfs-3g e2fsprogs mmc-utils psmisc util-linux
fi
python3 -c 'import flask, waitress'
for tool in lsblk blockdev sfdisk partprobe sgdisk mkfs.ext4 e2fsck resize2fs mkfs.vfat mkfs.exfat mkfs.ntfs mmc fuser; do
    command -v "$tool" >/dev/null || { echo "缺少依赖命令：$tool" >&2; exit 1; }
done
getent group emmc-web >/dev/null || groupadd --system emmc-web
getent passwd emmc-web >/dev/null || useradd --system --gid emmc-web --home /var/lib/emmc-web --shell /usr/sbin/nologin emmc-web
install -d -o emmc-web -g emmc-web -m 0750 /var/lib/emmc-web /var/lib/emmc-web/uploads /var/lib/emmc-web/downloads
install -d -o root -g emmc-web -m 0750 /var/lib/emmc-worker
work=$(mktemp -d /opt/.emmc-studio-install.XXXXXX)
web_was_active=0
worker_was_active=0
switched=0
completed=0
systemctl is-active --quiet emmc-web && web_was_active=1 || true
systemctl is-active --quiet emmc-worker && worker_was_active=1 || true
cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    set +e
    recovery_failed=0
    if [ "$completed" = 0 ]; then
        if [ "$switched" = 1 ]; then
            systemctl stop emmc-web emmc-worker
            if [ -e /opt/emmc-studio ]; then
                mv /opt/emmc-studio "$work/failed-app" || recovery_failed=1
            fi
            if [ -d "$work/previous" ]; then
                mv "$work/previous" /opt/emmc-studio || recovery_failed=1
            fi
            for service in emmc-web emmc-worker; do
                if [ -f "$work/$service.service" ]; then
                    cp "$work/$service.service" "/etc/systemd/system/$service.service"
                else
                    rm -f "/etc/systemd/system/$service.service"
                fi
            done
            if [ -f "$work/emmc-studio-cli.sh" ]; then
                cp "$work/emmc-studio-cli.sh" /usr/local/bin/emmc-studio
            else
                rm -f /usr/local/bin/emmc-studio
            fi
            systemctl daemon-reload
        fi
        [ "$worker_was_active" = 0 ] || systemctl start emmc-worker
        [ "$web_was_active" = 0 ] || systemctl start emmc-web
        echo '安装未完成；原有管理员、备份和任务数据保留。' >&2
    fi
    if [ "$recovery_failed" = 0 ]; then
        rm -rf -- "$work"
    else
        echo "恢复未完成，程序副本保留在 $work，请人工检查。" >&2
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
install -d -m 0755 "$work/app/backend" "$work/app/dist" "$work/app/deploy" "$work/app/docs"
cp backend/*.py "$work/app/backend/"
cp -R dist/. "$work/app/dist/"
cp deploy/*.sh deploy/*.py deploy/*.service "$work/app/deploy/"
cp README.md VERSION "$work/app/"
cp docs/CLI.md "$work/app/docs/"
chmod -R go-w "$work/app"
for service in emmc-web emmc-worker; do
    [ ! -f "/etc/systemd/system/$service.service" ] || cp "/etc/systemd/system/$service.service" "$work/"
done
[ ! -f /usr/local/bin/emmc-studio ] || cp /usr/local/bin/emmc-studio "$work/emmc-studio-cli.sh"
# Close job admission, then recheck in case a job began during dependency installation.
[ "$web_was_active" = 0 ] || systemctl stop emmc-web
python3 deploy/check_ready.py
[ "$worker_was_active" = 0 ] || systemctl stop emmc-worker
[ ! -e /opt/emmc-studio ] || mv /opt/emmc-studio "$work/previous"
switched=1
mv "$work/app" /opt/emmc-studio
cp deploy/emmc-*.service /etc/systemd/system/
python3 deploy/initialize.py
install -d -m 0755 /usr/local/bin
install -m 0755 deploy/emmc-studio-cli.sh /usr/local/bin/emmc-studio
systemctl daemon-reload
systemctl enable emmc-worker emmc-web
systemctl restart emmc-worker
systemctl restart emmc-web
sleep 2
systemctl is-active --quiet emmc-worker
systemctl is-active --quiet emmc-web
python3 -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1/api/v1/auth/status", timeout=10); assert r.status == 200'
/usr/local/bin/emmc-studio --json devices >/dev/null
if [ -d "$work/previous" ]; then
    backup="/opt/emmc-studio.previous.$(date +%Y%m%d%H%M%S).$$"
    mv "$work/previous" "$backup"
    echo "旧版程序保留在 $backup（不包含 /var/lib 中的状态数据）。"
fi
completed=1
echo "eMMC Studio $(cat VERSION) 已启动，监听 0.0.0.0:80，已设为开机启动。"
echo "浏览器打开 http://<设备IP>/；设备地址：$(hostname -I 2>/dev/null || true)"
