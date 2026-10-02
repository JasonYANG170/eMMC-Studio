#!/bin/sh
# Download a verified prebuilt release, then run its local installer.
set -eu
version=latest
download_only=''
check_only=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version) [ "$#" -ge 2 ] || exit 2; version=$2; shift 2 ;;
        --download-only) [ "$#" -ge 2 ] || exit 2; download_only=$2; shift 2 ;;
        --check) check_only=1; shift ;;
        --help) echo 'Usage: sudo sh install.sh [--version v1.0.0] [--check] [--download-only DIR]'; exit 0 ;;
        *) echo "未知参数：$1" >&2; exit 2 ;;
    esac
done
if [ "$version" != latest ]; then
    printf '%s\n' "$version" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([-][A-Za-z0-9.-]+)?$' || { echo '版本格式应为 v1.0.0。' >&2; exit 2; }
fi
if [ -z "$download_only" ]; then
    [ "$(id -u)" = 0 ] || { echo '请使用 sudo sh install.sh。' >&2; exit 1; }
fi
for tool in curl python3 sha256sum tar; do
    command -v "$tool" >/dev/null || { echo "请先安装 $tool。" >&2; exit 1; }
done
repo=https://github.com/JasonYANG170/eMMC-Studio/releases
if [ "$version" = latest ]; then base="$repo/latest/download"; else base="$repo/download/$version"; fi
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
fetch() { curl --proto '=https' --tlsv1.2 --fail --location --retry 3 --connect-timeout 15 --max-time 600 "$1" -o "$2"; }
echo "下载预构建安装包：$version"
fetch "$base/eMMC-Studio.tar.gz" "$work/eMMC-Studio.tar.gz"
fetch "$base/SHA256SUMS" "$work/SHA256SUMS"
digest=$(awk '$2 == "eMMC-Studio.tar.gz" {print $1}' "$work/SHA256SUMS")
printf '%s\n' "$digest" | grep -Eq '^[a-fA-F0-9]{64}$' || { echo '校验清单格式无效。' >&2; exit 1; }
(cd "$work" && printf '%s  eMMC-Studio.tar.gz\n' "$digest" | sha256sum -c -)
mkdir "$work/extracted"
python3 - "$work/eMMC-Studio.tar.gz" <<'PY'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    members = archive.getmembers()
    if len(members) > 5000 or sum(m.size for m in members) > 512 * 1024 * 1024:
        raise SystemExit('安装包内容超出限制')
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'eMMC-Studio' or not (member.isfile() or member.isdir()):
            raise SystemExit('安装包包含不安全路径或链接')
PY
tar -xzf "$work/eMMC-Studio.tar.gz" -C "$work/extracted" --no-same-owner --no-same-permissions
if [ -n "$download_only" ]; then
    mkdir -p "$download_only"
    cp "$work/eMMC-Studio.tar.gz" "$work/SHA256SUMS" "$download_only/"
    echo "安装包已校验并保存至 $download_only，未修改服务或磁盘。"
elif [ "$check_only" = 1 ]; then
    sh "$work/extracted/eMMC-Studio/deploy/install.sh" --check
else
    sh "$work/extracted/eMMC-Studio/deploy/install.sh"
fi
