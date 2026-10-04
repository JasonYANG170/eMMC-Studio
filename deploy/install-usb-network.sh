#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo 'Run with sudo.' >&2
  exit 1
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
apt-get update
apt-get install -y --no-install-recommends dnsmasq-base
modprobe libcomposite
mountpoint -q /sys/kernel/config || mount -t configfs configfs /sys/kernel/config
mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug
install -d /usr/local/lib/emmc-studio-usb
install -m 0644 "$script_dir/usb-network.py" /usr/local/lib/emmc-studio-usb/usb-network.py
install -m 0644 "$script_dir/emmc-usb-network.service" /etc/systemd/system/emmc-usb-network.service
systemctl daemon-reload
systemctl enable emmc-usb-network.service
systemctl restart emmc-usb-network.service
echo 'USB network enabled. Connect the OTG data port, then open http://172.30.77.1/'
