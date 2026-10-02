"""Read-only Linux telemetry for the unprivileged web service."""

import json, os, platform, shutil, socket, threading, time
from pathlib import Path
from core import read, run

_lock = threading.Lock()
_previous = None


def system_info():
    global _previous
    now = time.monotonic()
    cpu = [int(x) for x in read("/proc/stat").splitlines()[0].split()[1:9]]
    total = sum(cpu)
    idle = cpu[3] + cpu[4]
    interfaces = json.loads(run(["ip", "-j", "address", "show"]))
    network = []
    for item in interfaces:
        name = item["ifname"]
        base = Path("/sys/class/net") / name
        network.append(
            {
                "name": name,
                "state": item.get("operstate"),
                "mac": item.get("address"),
                "addresses": [
                    a["local"] + "/" + str(a["prefixlen"])
                    for a in item.get("addr_info", [])
                ],
                "rx_bytes": int(read(base / "statistics/rx_bytes", "0")),
                "tx_bytes": int(read(base / "statistics/tx_bytes", "0")),
                "speed_mbps": read(base / "speed"),
                "mtu": item.get("mtu"),
            }
        )
    with _lock:
        old = _previous
        usage = None
        if old and total > old["total"]:
            usage = round(
                max(
                    0,
                    min(100, 100 * (1 - (idle - old["idle"]) / (total - old["total"]))),
                ),
                1,
            )
        for n in network:
            previous = (old or {}).get("network", {}).get(n["name"])
            elapsed = now - old["time"] if old else 0
            for direction in ("rx", "tx"):
                n[direction + "_rate"] = (
                    max(
                        0,
                        round(
                            (n[direction + "_bytes"] - previous[direction + "_bytes"])
                            / elapsed
                        ),
                    )
                    if previous and elapsed > 0
                    else None
                )
        _previous = {
            "total": total,
            "idle": idle,
            "time": now,
            "network": {n["name"]: n for n in network},
        }
    memory = {
        k: int(v.split()[0]) * 1024
        for k, v in (line.split(":", 1) for line in read("/proc/meminfo").splitlines())
    }
    cpuinfo = read("/proc/cpuinfo")
    model = read("/sys/firmware/devicetree/base/model").rstrip("\0")
    cpu_model = next(
        (
            line.split(":", 1)[1].strip()
            for line in cpuinfo.splitlines()
            if line.startswith(("model name", "Hardware"))
        ),
        platform.machine(),
    )
    temperatures = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            temperatures.append(
                {
                    "name": read(zone / "type"),
                    "celsius": int(read(zone / "temp")) / 1000,
                }
            )
        except ValueError:
            pass
    filesystems = []
    for mount in ("/", "/boot"):
        if Path(mount).exists():
            u = shutil.disk_usage(mount)
            filesystems.append(
                {"mount": mount, "total": u.total, "used": u.used, "free": u.free}
            )
    return {
        "hostname": socket.gethostname(),
        "model": model,
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "os": platform.freedesktop_os_release().get("PRETTY_NAME", "Linux"),
        "uptime": float(read("/proc/uptime").split()[0]),
        "cpu": {
            "model": cpu_model,
            "cores": os.cpu_count(),
            "usage": usage,
            "load": list(os.getloadavg()),
            "temperatures": temperatures,
        },
        "memory": {
            "total": memory["MemTotal"],
            "available": memory.get("MemAvailable", memory["MemFree"]),
            "used": memory["MemTotal"] - memory.get("MemAvailable", memory["MemFree"]),
            "swap_total": memory.get("SwapTotal", 0),
            "swap_used": memory.get("SwapTotal", 0) - memory.get("SwapFree", 0),
        },
        "filesystems": filesystems,
        "network": network,
        "sampled_at": time.time(),
    }
