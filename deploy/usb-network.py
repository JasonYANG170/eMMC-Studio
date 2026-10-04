#!/usr/bin/env python3
"""Optional Windows USB network transport; never exposes block devices."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

GADGET = Path("/sys/kernel/config/usb_gadget/emmc_studio")
INTERFACE = "emmcusb0"


def write(path, value):
    path.write_text(str(value))


def stop():
    if (GADGET / "UDC").exists():
        write(GADGET / "UDC", "")


def start():
    if GADGET.exists():
        stop()
    controllers = list(Path("/sys/class/udc").glob("*"))
    if not controllers:
        modes = list(Path("/sys/kernel/debug/usb").glob("*/mode"))
        if len(modes) != 1:
            raise RuntimeError(
                "Cannot identify one OTG controller; configure peripheral mode first"
            )
        write(modes[0], "device")
        for _ in range(100):
            controllers = list(Path("/sys/class/udc").glob("*"))
            if controllers:
                break
            time.sleep(0.1)
    if len(controllers) != 1:
        raise RuntimeError("Expected exactly one available USB device controller")
    GADGET.mkdir(exist_ok=True)
    for link in [GADGET / "configs/c.1/rndis.usb0", GADGET / "os_desc/c.1"]:
        if link.is_symlink():
            link.unlink()
    # Linux Foundation composite gadget IDs, for this development prototype.
    write(GADGET / "idVendor", "0x1d6b")
    write(GADGET / "idProduct", "0x0104")
    write(GADGET / "bcdUSB", "0x0200")
    write(GADGET / "bcdDevice", "0x0100")
    write(GADGET / "bDeviceClass", "0xEF")
    write(GADGET / "bDeviceSubClass", "0x02")
    write(GADGET / "bDeviceProtocol", "0x01")
    identity = hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()
    strings = GADGET / "strings/0x409"
    strings.mkdir(exist_ok=True)
    write(strings / "serialnumber", identity[:16])
    write(strings / "manufacturer", "eMMC Studio")
    write(strings / "product", "eMMC Studio USB Network")
    config = GADGET / "configs/c.1"
    config.mkdir(exist_ok=True)
    (config / "strings/0x409").mkdir(exist_ok=True)
    write(config / "strings/0x409/configuration", "USB network")
    write(config / "MaxPower", "250")
    function = GADGET / "functions/rndis.usb0"
    function.mkdir(exist_ok=True)
    write(
        function / "dev_addr",
        "02:" + ":".join(identity[i : i + 2] for i in range(0, 10, 2)),
    )
    write(
        function / "host_addr",
        "06:" + ":".join(identity[i : i + 2] for i in range(0, 10, 2)),
    )
    write(GADGET / "os_desc/use", "1")
    write(GADGET / "os_desc/b_vendor_code", "0xcd")
    write(GADGET / "os_desc/qw_sign", "MSFT100")
    write(function / "os_desc/interface.rndis/compatible_id", "RNDIS")
    write(function / "os_desc/interface.rndis/sub_compatible_id", "5162001")
    for link, target in [
        (config / "rndis.usb0", function),
        (GADGET / "os_desc/c.1", config),
    ]:
        if not link.is_symlink():
            link.symlink_to(target)
    write(GADGET / "UDC", controllers[0].name)
    for _ in range(100):
        current_interface = (function / "ifname").read_text().strip()
        if Path("/sys/class/net", current_interface).exists():
            break
        time.sleep(0.1)
    if subprocess.run(["which", "nmcli"], stdout=subprocess.DEVNULL).returncode == 0:
        subprocess.run(
            ["nmcli", "device", "set", current_interface, "managed", "no"], check=True
        )
    if current_interface != INTERFACE:
        subprocess.run(["ip", "link", "set", current_interface, "down"], check=True)
        subprocess.run(
            ["ip", "link", "set", current_interface, "name", INTERFACE], check=True
        )
    if subprocess.run(["which", "nmcli"], stdout=subprocess.DEVNULL).returncode == 0:
        subprocess.run(
            ["nmcli", "device", "set", INTERFACE, "managed", "no"], check=True
        )
    subprocess.run(
        ["ip", "address", "replace", "172.30.77.1/24", "dev", INTERFACE], check=True
    )
    subprocess.run(["ip", "link", "set", INTERFACE, "up"], check=True)
    print("eMMC Studio USB address: http://172.30.77.1/", flush=True)
    os.execv(
        "/usr/sbin/dnsmasq",
        [
            "dnsmasq",
            "--keep-in-foreground",
            "--conf-file=/dev/null",
            "--port=0",
            "--no-hosts",
            "--no-resolv",
            "--bind-interfaces",
            "--interface=" + INTERFACE,
            "--dhcp-range=172.30.77.2,172.30.77.2,255.255.255.0,12h",
            "--dhcp-option=3",
            "--dhcp-option=6",
            "--dhcp-authoritative",
            "--dhcp-leasefile=/run/emmc-usb-network/leases",
            "--log-dhcp",
        ],
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["stop"]:
        stop()
    elif sys.argv[1:] == ["start"]:
        start()
    else:
        raise SystemExit("Usage: usb-network.py start|stop")
