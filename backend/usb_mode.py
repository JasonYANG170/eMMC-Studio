"""Fixed USB role operations, serialized with all storage jobs."""

import json
from pathlib import Path
import threading
import time
import uuid
from core import StorageError, run


class UsbModeControl:
    def __init__(self, manager):
        self.manager = manager

    def controller(self):
        modes = list(Path("/sys/kernel/debug/usb").glob("*/mode"))
        if len(modes) != 1:
            raise StorageError("无法确定唯一 OTG 控制器")
        return modes[0]

    def status(self):
        try:
            mode = self.controller().read_text().strip()
            available = Path("/etc/systemd/system/emmc-usb-network.service").exists()
        except (OSError, StorageError):
            mode, available = "unknown", False
        addresses = json.loads(run(["ip", "-j", "-4", "address"], timeout=5))
        links = [
            f'http://{a["local"]}/'
            for interface in addresses
            if interface["ifname"] not in ("lo", "emmcusb0")
            for a in interface.get("addr_info", [])
            if a.get("scope") == "global"
        ]
        return dict(
            mode=mode,
            available=available,
            switching=self.manager.usb_switching,
            alternate_urls=links,
            usb_url="http://172.30.77.1/",
        )

    def check_mounts(self):
        # Include host mounts and the worker's private file-browser mounts.
        for table in ["/proc/self/mountinfo", "/proc/1/mountinfo"]:
            for line in Path(table).read_text().splitlines():
                fields = line.split()
                device = Path("/sys/dev/block", fields[2]).resolve()
                if any(p.startswith("usb") for p in device.parts):
                    raise StorageError("USB 存储仍有挂载，请先安全卸载后再切换")
        for line in Path("/proc/swaps").read_text().splitlines()[1:]:
            source = Path(line.split()[0]).resolve()
            device = Path("/sys/class/block", source.name).resolve()
            if any(p.startswith("usb") for p in device.parts):
                raise StorageError("USB 存储正在用于交换空间，不能切换")

    def submit(self, args):
        if args.get("mode") not in ("host", "device"):
            raise StorageError("USB 模式仅支持 host 或 device")
        if args.get("acknowledged") is not True:
            raise StorageError("请确认已使用以太网或独立串口连接")
        m = self.manager
        with m.guard:
            if (
                m.usb_switching
                or m.upgrade_frozen
                or Path("/run/emmc-updater/maintenance").exists()
            ):
                raise StorageError("服务正在切换或升级，请稍后重试")
            with m.db_lock, m.connect() as connection:
                active = any(
                    json.loads(row[0])["state"] in ("queued", "running")
                    for row in connection.execute("SELECT data FROM jobs")
                )
            if m.busy or active:
                raise StorageError(
                    "存在进行中的任务，请结束传输或克隆后再切换 USB 模式"
                )
            if not self.status()["available"]:
                raise StorageError("USB 网卡服务尚未安装，无法切换")
            self.check_mounts()
            job = dict(
                id=uuid.uuid4().hex,
                op="usb_mode",
                title="切换 USB 模式",
                state="queued",
                created=time.time(),
                progress=0,
                bytes=0,
                total=1,
                speed=0,
                phase="等待切换 USB 模式",
                logs=[],
                cancellable=True,
            )
            m.usb_switching = True
            try:
                m.save(job)
                event = threading.Event()
                m.cancels[job["id"]] = event
                threading.Thread(
                    target=m.execute,
                    args=(job, dict(args, op="usb_mode"), [], event),
                    daemon=True,
                ).start()
            except Exception:
                m.usb_switching = False
                raise
            return job

    def change(self, args, job, progress, cancel):
        progress(0, 1, "即将切换 USB 模式，请使用其他连接方式")
        # Give the HTTP response time to reach a browser on the USB network.
        for _ in range(30):
            if cancel():
                raise StorageError("USB 模式切换已取消")
            time.sleep(0.1)
        self.check_mounts()
        controller = self.controller()
        job["cancellable"] = False
        self.manager.save(job)
        if args["mode"] == "host":
            run(
                ["systemctl", "disable", "--now", "emmc-usb-network.service"],
                timeout=30,
            )
            controller.write_text("host")
        else:
            controller.write_text("device")
            run(["systemctl", "enable", "emmc-usb-network.service"], timeout=30)
            run(["systemctl", "restart", "emmc-usb-network.service"], timeout=30)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            actual = controller.read_text().strip()
            interfaces = json.loads(run(["ip", "-j", "-4", "address"], timeout=5))
            network_ready = any(
                interface["ifname"] == "emmcusb0"
                and any(
                    address.get("local") == "172.30.77.1"
                    for address in interface.get("addr_info", [])
                )
                for interface in interfaces
            )
            service_ready = args["mode"] == "host" or (
                run(
                    ["systemctl", "is-active", "emmc-usb-network.service"],
                    accepted=(0, 3),
                    timeout=5,
                ).strip()
                == "active"
                and network_ready
            )
            if actual == args["mode"] and service_ready:
                progress(1, 1, "USB 模式已切换")
                return dict(mode=actual)
            time.sleep(0.25)
        raise StorageError("USB 模式切换未完成，请通过串口查看服务日志")
