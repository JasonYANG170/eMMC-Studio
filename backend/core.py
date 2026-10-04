"""Device policy, bounded I/O and Linux storage discovery. No shell execution."""

import base64
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
from pathlib import Path

BLOCK = 4 * 1024 * 1024
HEX_LIMIT = 65536
TEXT_LIMIT = 2 * 1024 * 1024
_table_lock = threading.Lock()
_table_busy = set()
_table_retry = {}


def partition_table(path, identity, generation):
    """A stalled media read must not block discovery of replacement cards."""
    key = (path, identity, generation)
    with _table_lock:
        if (
            key in _table_busy
            or len(_table_busy) >= 4
            or time.monotonic() < _table_retry.get(key, 0)
        ):
            return None
        _table_busy.add(key)
    process = None
    deferred = False
    stalled = False
    try:
        process = subprocess.Popen(
            ["sfdisk", "--json", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, _ = process.communicate(timeout=3)
        if process.returncode == 0:
            table = json.loads(stdout)["partitiontable"]
            return table
    except subprocess.TimeoutExpired:
        stalled = True
        process.kill()
        deferred = True

        def reap():
            try:
                process.communicate()
            finally:
                with _table_lock:
                    _table_busy.discard(key)

        threading.Thread(target=reap, daemon=True).start()
    except (OSError, ValueError, KeyError):
        pass
    finally:
        with _table_lock:
            if not deferred:
                _table_busy.discard(key)
            # Limit retries against failing media; fresh CID/diskseq bypasses this.
            if stalled:
                _table_retry[key] = time.monotonic() + 30
            else:
                _table_retry.pop(key, None)
            if len(_table_retry) > 64:
                expired = [
                    k
                    for k, deadline in _table_retry.items()
                    if deadline < time.monotonic()
                ]
                for old in expired:
                    _table_retry.pop(old, None)
    return None


class StorageError(Exception):
    pass


def run(args, input=None, accepted=(0,), timeout=120):
    p = subprocess.run(
        [str(x) for x in args],
        input=input,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if p.returncode not in accepted:
        raise StorageError(
            (p.stderr or p.stdout or f"{args[0]} failed").strip()[-4000:]
        )
    return p.stdout


def read(path, default=""):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


def number(value, minimum=0, maximum=2**63 - 1):
    if isinstance(value, bool):
        raise StorageError("参数必须是整数")
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise StorageError("参数必须是整数")
    if str(value).strip() not in (str(n), f"+{n}") and not isinstance(value, int):
        raise StorageError("参数必须是整数")
    if not minimum <= n <= maximum:
        raise StorageError("参数超出允许范围")
    return n


def safe_path(root, relative, allow_missing=False):
    root = Path(root).resolve()
    rel = Path(str(relative).lstrip("/"))
    if ".." in rel.parts or "\x00" in str(relative):
        raise StorageError("路径越界")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise StorageError("不允许通过符号链接访问")
    target = current.resolve(strict=not allow_missing)
    if target != root and root not in target.parents:
        raise StorageError("路径越界")
    return target


def token_path(root, token):
    if not re.fullmatch(r"[a-f0-9]{32}", str(token)):
        raise StorageError("无效文件标识")
    p = Path(root) / token
    if p.is_symlink():
        raise StorageError("文件不能是符号链接")
    return p


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(BLOCK):
            h.update(chunk)
    return h.hexdigest()


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get("children", []))


def inventory():
    data = json.loads(
        run(
            [
                "lsblk",
                "-b",
                "-J",
                "-o",
                "NAME,KNAME,PATH,SIZE,TYPE,FSTYPE,LABEL,UUID,RO,MOUNTPOINTS,MODEL,TRAN,SERIAL,PKNAME,START,PARTTYPE,PARTLABEL,PARTUUID",
            ]
        )
    )
    rows = list(flatten(data["blockdevices"]))
    protected = set()
    by_name = {r["kname"]: r for r in rows}
    for r in rows:
        mounts = r.get("mountpoints") or []
        if any(m in ("/", "/boot", "/usr", "/var", "/var/log.hdd") for m in mounts):
            n = r["kname"]
            while n:
                protected.add(n)
                n = by_name.get(n, {}).get("pkname")
    disks = []
    for r in data["blockdevices"]:
        name = r["kname"]
        if (
            name.startswith(("zram", "ram"))
            or r["type"] not in ("disk", "loop")
            or "boot" in name
        ):
            continue
        sysdev = Path("/sys/class/block") / name / "device"
        card_type = read(sysdev / "type")
        cid = read(sysdev / "cid")
        kind = (
            "emmc"
            if card_type == "MMC"
            else (
                "sd"
                if card_type == "SD"
                else "usb" if r.get("tran") == "usb" else r["type"]
            )
        )
        test_devices = os.environ.get("EMMC_TEST_DEVICES", "").split(",")
        if kind == "loop" and r["path"] not in test_devices:
            continue
        ident = (
            cid
            or r.get("serial")
            or (r["path"] + ":" + read(f"/sys/class/block/{name}/diskseq", "unknown"))
        )
        disk = dict(
            r,
            kind=kind,
            cid=cid,
            identity=f"{kind}:{ident}",
            protected=name in protected,
            writable=kind in ("emmc", "usb", "loop")
            and name not in protected
            and not r["ro"],
            model=(read(sysdev / "name") or r.get("model") or name).replace(
                "\ufffd", ""
            ),
            sector_size=int(
                read(f"/sys/class/block/{name}/queue/logical_block_size", "512")
            ),
        )
        disk["regions"] = [dict(r, region="user", disk=name, identity=disk["identity"])]
        for i in (0, 1):
            bn = name + f"boot{i}"
            if Path("/sys/class/block", bn).exists():
                disk["regions"].append(
                    {
                        "name": bn,
                        "kname": bn,
                        "path": "/dev/" + bn,
                        "size": int(read(f"/sys/class/block/{bn}/size")) * 512,
                        "type": "boot",
                        "region": f"boot{i}",
                        "disk": name,
                        "ro": read(f"/sys/class/block/{bn}/ro", "1") == "1",
                        "force_ro": read(f"/sys/class/block/{bn}/force_ro"),
                        "mountpoints": [],
                        "identity": disk["identity"],
                    }
                )
        for p in flatten(r.get("children", [])):
            if p["type"] == "part":
                disk["regions"].append(
                    dict(p, region="partition", disk=name, identity=disk["identity"])
                )
        disk["rpmb"] = {
            "path": f"/dev/{name}rpmb",
            "available": Path(f"/dev/{name}rpmb").exists(),
            "size": int(read(sysdev / "raw_rpmb_size_mult", "0"), 0) * 128 * 1024,
            "note": "RPMB 需专用认证协议，不能作为普通磁盘读写",
        }
        disk["health"] = {
            "life_time": read(sysdev / "life_time"),
            "pre_eol": read(sysdev / "pre_eol_info"),
            "manufacturer": read(sysdev / "manfid"),
            "revision": read(sysdev / "rev"),
        }
        disk["table"] = partition_table(
            r["path"], disk["identity"], read(f"/sys/class/block/{name}/diskseq")
        )
        disk["topology"] = str(sysdev.resolve())
        controller = sysdev.resolve().parent.parent.parent
        disk["hotplug"] = {
            "polling": (controller / "of_node/broken-cd").exists(),
            "non_removable": (controller / "of_node/non-removable").exists(),
        }
        host = sysdev.resolve().parent.name
        ios = (
            read(Path("/sys/kernel/debug") / host / "ios")
            if re.fullmatch(r"mmc\d+", host)
            else ""
        )
        disk["mmc_link"] = {
            "host": host if ios else "",
            "ios": dict(
                (key.strip(), value.strip())
                for line in ios.splitlines()
                if ":" in line
                for key, value in [line.split(":", 1)]
            ),
        }
        disk["card_info"] = {
            key: read(sysdev / key)
            for key in (
                "type",
                "name",
                "serial",
                "date",
                "manfid",
                "oemid",
                "hwrev",
                "fwrev",
                "prv",
                "rev",
                "cid",
                "csd",
                "ocr",
                "rca",
                "dsr",
                "erase_size",
                "preferred_erase_size",
                "rel_sectors",
                "enhanced_area_offset",
                "enhanced_area_size",
                "cmdq_en",
                "ffu_capable",
            )
        }
        blockpath = Path("/sys/class/block") / name
        disk["block_info"] = {
            key: read(blockpath / key)
            for key in ("dev", "removable", "ro", "diskseq", "stat")
        }
        disk["queue_info"] = {
            key: read(blockpath / "queue" / key)
            for key in (
                "logical_block_size",
                "physical_block_size",
                "minimum_io_size",
                "optimal_io_size",
                "rotational",
                "scheduler",
                "read_ahead_kb",
                "nr_requests",
                "max_sectors_kb",
                "discard_granularity",
                "discard_max_bytes",
                "write_cache",
            )
        }
        disks.append(disk)
    return disks


def resolve_region(path, identity=None, write=False, disks=None):
    for disk in disks if disks is not None else inventory():
        for region in disk["regions"]:
            if region["path"] == path:
                if identity is not None and identity != disk["identity"]:
                    raise StorageError("设备身份已变化，请重新选择")
                if write and not disk["writable"]:
                    raise StorageError("系统磁盘或不支持的目标禁止写入")
                if region["region"] == "partition" and write and region.get("ro"):
                    raise StorageError("分区处于只读状态")
                return disk, region
    raise StorageError("设备不存在或不在允许范围内")


def check_overlap(source_disk, target_disk):
    if source_disk["path"] == target_disk["path"]:
        raise StorageError("源和目标属于同一磁盘，禁止重叠复制")


def bounds(offset, length, size, limit=None):
    offset, length = number(offset), number(length, 1)
    if limit and length > limit:
        raise StorageError("请求长度超过限制")
    if offset + length > size:
        raise StorageError("范围超出设备容量")
    return offset, length


def pinned_open(path, mode):
    fd = os.open(path, mode | os.O_NOFOLLOW)
    st = os.fstat(fd)
    if not stat.S_ISBLK(st.st_mode):
        os.close(fd)
        raise StorageError("目标必须是块设备")
    return fd


@contextlib.contextmanager
def boot_writable(region):
    control = Path("/sys/class/block", region["kname"], "force_ro")
    isboot = region["region"] in ("boot0", "boot1")
    previous = read(control) if isboot else None
    try:
        if isboot:
            control.write_text("0")
        yield
    finally:
        if isboot and control.exists():
            control.write_text(previous or "1")


def copy_stream(
    source,
    target,
    length,
    progress,
    cancelled=lambda: False,
    verify=False,
    target_offset=0,
):
    """Bounded memory; short reads fail rather than silently shortening a clone."""
    h = hashlib.sha256()
    done = 0
    target.seek(target_offset)
    while done < length:
        if cancelled():
            raise StorageError("任务已取消；已写入内容不会自动回滚")
        chunk = source.read(min(BLOCK, length - done))
        if not chunk:
            raise StorageError("源数据提前结束")
        view = memoryview(chunk)
        while view:
            written = target.write(view)
            if not written:
                raise StorageError("目标写入失败")
            view = view[written:]
        h.update(chunk)
        done += len(chunk)
        progress(done, length, "复制")
    target.flush()
    os.fsync(target.fileno())
    digest = h.hexdigest()
    if verify:
        target.seek(target_offset)
        check = hashlib.sha256()
        done = 0
        while done < length:
            if cancelled():
                raise StorageError("校验已取消；写入已经完成")
            chunk = target.read(min(BLOCK, length - done))
            if not chunk:
                raise StorageError("目标读回提前结束")
            check.update(chunk)
            done += len(chunk)
            progress(done, length, "读回校验")
        if check.hexdigest() != digest:
            raise StorageError("读回校验失败")
    return digest


def host_mounts(path):
    """Check the host namespace as well as the worker's private mounts."""
    device = os.stat(path).st_rdev
    key = f"{os.major(device)}:{os.minor(device)}"
    return [
        line.split()[4]
        for line in read("/proc/1/mountinfo").splitlines()
        if len(line.split()) > 4 and line.split()[2] == key
    ]
