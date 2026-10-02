"""Local administrator CLI; storage operations always use the existing worker."""

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import sys
import tempfile
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from i18n import t, set_language, localize_status

CHUNK = 256 * 1024
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class CLIError(Exception):
    pass


@contextlib.contextmanager
def local_source(filename):
    fd = os.open(filename, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise CLIError(t("输入必须是普通文件，不能是块设备或管道"))
        yield source


def size(value):
    """Exact bytes; bare numbers are bytes, IEC and decimal units are distinct."""
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(B|KiB|MiB|GiB|TiB|KB|MB|GB|TB)?\s*", value, re.I
    )
    if not match:
        raise argparse.ArgumentTypeError(t("大小应为字节数或 64KiB、4MiB、1.5GiB 等"))
    powers = {
        "b": 1,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
    }
    try:
        result = Decimal(match[1]) * powers[(match[2] or "B").lower()]
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError(t("大小无效")) from error
    if result != result.to_integral_value() or result > 2**63 - 1:
        raise argparse.ArgumentTypeError(t("必须是整数个字节，且不超过 2^63-1"))
    return int(result)


def sectors(value):
    if value % (1024 * 1024):
        raise CLIError(t("分区起点和大小必须按 1 MiB 对齐"))
    return value // 512


def human(value):
    value = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}"
        value /= 1024


def json_line(source):
    data = source.readline(8 * 1024 * 1024 + 1)
    if not data.endswith(b"\n") or len(data) > 8 * 1024 * 1024:
        raise CLIError(t("工作进程返回不完整或过大的响应"))
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise CLIError(t("工作进程响应格式错误")) from error
    if not isinstance(result, dict):
        raise CLIError(t("工作进程响应格式错误"))
    if not result.get("ok"):
        raise CLIError(result.get("error", t("操作失败")))
    return result


class Client:
    def __init__(self, path):
        self.path = path

    def connect(self, method, args):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(180)
            connection.connect(self.path)
            connection.sendall(
                (
                    json.dumps({"method": method, "args": args}, ensure_ascii=False)
                    + "\n"
                ).encode()
            )
            return connection
        except BaseException:
            connection.close()
            raise

    def rpc(self, method, args=None):
        with self.connect(method, args or {}) as connection, connection.makefile(
            "rb"
        ) as source:
            return json_line(source)["result"]

    def stream(self, token, destination, overwrite=False, job_id=None):
        """Commit output only after the framing, trailer and length pass checks."""
        destination = Path(destination).absolute()
        if destination.is_symlink() or (
            destination.exists() and not destination.is_file()
        ):
            raise CLIError(t("输出目标必须是普通文件，不能是块设备、目录或符号链接"))
        if destination.exists() and not overwrite:
            raise CLIError(t("输出文件已存在；需要覆盖时使用 --overwrite"))
        temporary = None
        try:
            with self.connect(
                "stream_download", {"token": token}
            ) as connection, connection.makefile("rb") as source:
                metadata = json_line(source)
                with tempfile.NamedTemporaryFile(
                    prefix=".emmc-partial-", dir=destination.parent, delete=False
                ) as output:
                    temporary = Path(output.name)
                    count, digest, last = 0, hashlib.sha256(), 0
                    while True:
                        header = source.read(4)
                        if len(header) != 4:
                            raise CLIError(t("下载连接提前结束，未保存为最终文件"))
                        length = struct.unpack("!I", header)[0]
                        if not length:
                            json_line(source)
                            break
                        if length > CHUNK:
                            raise CLIError(t("下载块超过 256 KiB"))
                        data = source.read(length)
                        if len(data) != length:
                            raise CLIError(t("下载连接提前结束，未保存为最终文件"))
                        output.write(data)
                        digest.update(data)
                        count += length
                        if time.monotonic() - last > 1:
                            print(t(f"已接收 {human(count)}"), file=sys.stderr)
                            last = time.monotonic()
                    if (
                        metadata.get("length") is not None
                        and count != metadata["length"]
                    ):
                        raise CLIError(t("接收长度与声明不符"))
                    output.flush()
                    os.fsync(output.fileno())
            completed = wait_job(self, job_id) if job_id else None
            if completed:
                expected = completed.get("result", {}).get("sha256")
                if expected and expected != digest.hexdigest():
                    raise CLIError(t("下载 SHA-256 与源数据不一致"))
            if overwrite:
                os.replace(temporary, destination)
            else:
                # Atomic no-clobber: refuse files created after the initial check.
                os.link(temporary, destination)
                temporary.unlink()
            result = {
                "file": str(destination),
                "size": count,
                "sha256": digest.hexdigest(),
            }
            if completed:
                result["job"] = completed
            return result
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def upload(filename):
    """Stage local regular files in the worker's existing bounded upload store."""
    import pwd

    with local_source(filename) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise CLIError(t("输入必须是普通文件，不能是块设备或管道"))
        folder = Path(os.environ.get("EMMC_WEB_STATE", "/var/lib/emmc-web")) / "uploads"
        if shutil.disk_usage(folder).free < info.st_size + 64 * 1024 * 1024:
            raise CLIError(t("暂存空间不足，需额外保留 64 MiB"))
        token = uuid.uuid4().hex
        path = folder / token
        meta = path.with_suffix(".json")
        group = pwd.getpwnam("emmc-web").pw_gid
        data = {
            "name": Path(filename).name,
            "size": info.st_size,
            "complete": False,
            "created": time.time(),
        }
        try:
            with path.open("xb") as target:
                os.chmod(path, 0o640)
                os.chown(path, 0, group)
                meta.write_text(json.dumps(data), encoding="utf-8")
                os.chmod(meta, 0o640)
                os.chown(meta, 0, group)
                copied = 0
                while chunk := source.read(CHUNK):
                    copied += len(chunk)
                    if copied > info.st_size:
                        raise CLIError(t("输入文件在暂存期间发生变化"))
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            after = os.fstat(source.fileno())
            if copied != info.st_size or after.st_mtime_ns != info.st_mtime_ns:
                raise CLIError(t("输入文件在暂存期间发生变化"))
            data["complete"] = True
            meta.write_text(json.dumps(data), encoding="utf-8")
            return token
        except BaseException:
            path.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            raise


def target_args(client, target):
    for disk in client.rpc("inventory")["disks"]:
        for region in disk["regions"]:
            if region["path"] == target:
                return {"target": target, "identity": disk["identity"]}, disk, region
    raise CLIError(t(f"找不到存储区域：{target}；请先运行 devices"))


def wait_job(client, jid, interval=1):
    previous = None
    try:
        while True:
            job = client.rpc("job", {"id": jid})
            current = (job["state"], job.get("phase"), job.get("progress"))
            if current != previous:
                print(
                    f"{jid}  {job.get('progress', 0):6.2f}%  {t(job.get('phase', job['state']))}  {human(job.get('speed'))}/s",
                    file=sys.stderr,
                )
                previous = current
            if job["state"] in TERMINAL:
                if job["state"] != "completed":
                    raise CLIError(
                        t(f"任务 {jid} {job['state']}：{t(job.get('error', ''))}")
                    )
                return job
            time.sleep(interval)
    except KeyboardInterrupt:
        print(
            t(
                f"\n已停止等待；任务 {jid} 继续运行。查看：emmc-studio jobs show {jid}；取消：emmc-studio jobs cancel {jid}"
            ),
            file=sys.stderr,
        )
        raise


class LocalizedHelpFormatter(argparse.HelpFormatter):
    def start_section(self, heading):
        super().start_section(
            t(
                {"positional arguments": "位置参数", "options": "选项"}.get(
                    heading, heading
                )
            )
        )

    def _format_usage(self, usage, actions, groups, prefix):
        return super()._format_usage(usage, actions, groups, prefix or t("用法："))


class LocalizedParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", LocalizedHelpFormatter)
        super().__init__(*args, **kwargs)
        for action in self._actions:
            if isinstance(action, argparse._HelpAction):
                action.help = t("显示帮助信息并退出")


def parser():
    p = LocalizedParser(
        prog="emmc-studio",
        description=t("eMMC Studio 串口 / SSH 本地管理命令（使用 sudo）"),
        epilog=t(
            "大小单位：B、KiB、MiB、GiB 或 KB、MB、GB；默认字节。写入命令会直接执行，不要求输入设备标识。"
        ),
    )
    p.add_argument(
        "--lang",
        choices=("auto", "zh-CN", "en"),
        default="auto",
        help=t("语言：auto 跟随系统，zh-CN 中文，en 英文；也可设置 EMMC_STUDIO_LANG"),
    )
    p.add_argument(
        "--json", action="store_true", help=t("输出机器可读 JSON；进度写入 stderr")
    )
    p.add_argument(
        "--no-wait", action="store_true", help=t("提交后台任务后立即返回 ID")
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=t("仅显示任务请求，不提交或暂存文件；并非完整磁盘预检"),
    )
    p.add_argument(
        "--socket",
        default=os.environ.get("EMMC_WORKER_SOCKET", "/run/emmc-worker/control.sock"),
        help=t("工作进程 Unix socket"),
    )
    p.add_argument(
        "--version",
        action="version",
        help=t("显示版本号并退出"),
        version="eMMC Studio "
        + (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip(),
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help=t("所有磁盘、区域和分区"))
    sub.add_parser("system", help=t("CPU、内存、网络等系统信息"))
    for name, help_text in (
        ("info", t("磁盘/区域完整信息")),
        ("extcsd", t("eMMC EXT_CSD 原始信息")),
    ):
        sub.add_parser(name, help=help_text).add_argument("target")

    def group(name, help_text):
        return sub.add_parser(name, help=help_text).add_subparsers(
            dest="action", required=True
        )

    def area(actions, name, help_text):
        item = actions.add_parser(name, help=help_text)
        item.add_argument(
            "target",
            help=t("devices 中的区域路径，例如 /dev/mmcblk2boot0；编号动态发现"),
        )
        return item

    upgrade = group("upgrade", t("独立应用升级：在线 GitHub Release 或本地官方签名包"))
    upgrade.add_parser("check", help=t("在线检测最新版本"))
    upgrade.add_parser("status", help=t("当前版本与持久化升级状态"))
    for operation in ("online", "import"):
        item = upgrade.add_parser(
            operation,
            help=t("在线升级") if operation == "online" else t("导入本地升级包"),
        )
        if operation == "import":
            item.add_argument("input", help=t("官方 eMMC-Studio-update.tar.gz"))
        item.add_argument(
            "--reinstall", action="store_true", help=t("允许重新安装同版本；仍禁止降级")
        )

    parts = group("partition", t("分区表、建立/删除/修改分区、格式化和 ext4 调整"))
    area(parts, "table", t("建立分区表（会破坏现有布局）")).add_argument(
        "table", choices=("gpt", "mbr")
    )
    item = area(parts, "create", t("建立分区（起点/大小为字节，1 MiB 对齐）"))
    item.add_argument("--start", type=size, required=True)
    item.add_argument("--size", type=size, required=True)
    area(parts, "delete", t("删除分区")).add_argument("index", type=int)
    item = area(parts, "modify", t("修改名称、类型和 MBR 启动标志"))
    item.add_argument("index", type=int)
    item.add_argument("--label")
    item.add_argument("--type")
    item.add_argument("--bootable", action=argparse.BooleanOptionalAction, default=None)
    item = area(parts, "format", t("格式化指定分区"))
    item.add_argument("filesystem", choices=("ext4", "fat32", "exfat", "ntfs"))
    item.add_argument("--label", default="")
    area(parts, "resize", t("调整 ext4 分区总大小，不移动起点")).add_argument(
        "--size", type=size, required=True
    )

    files = group("files", t("分区内文件操作（路径由工作进程限制在分区内）"))
    for name in ("ls", "cat", "get", "put", "text-put", "mkdir", "rm", "mv"):
        item = area(files, name, name)
        (
            item.add_argument("path", nargs="?", default="")
            if name == "ls"
            else item.add_argument("path")
        )
        if name == "get":
            item.add_argument("--output", required=True)
        if name in ("put", "text-put"):
            item.add_argument("--input", required=True, help=t("设备本机文件路径"))
        if name in ("get", "put", "text-put"):
            item.add_argument("--overwrite", action="store_true")
        if name == "mv":
            item.add_argument("destination")

    hexes = group("hex", t("原始字节查看、编辑、回退及流式导出"))
    for name in ("read", "write", "export", "undo"):
        item = area(hexes, name, name)
        if name == "undo":
            item.add_argument("snapshot")
            continue
        item.add_argument("--offset", type=size, default=0)
        if name == "write":
            values = item.add_mutually_exclusive_group(required=True)
            values.add_argument("--data", help=t("十六进制字节，例如 '01 02 ff'"))
            values.add_argument("--input", help=t("最多 64 KiB 的本机二进制文件"))
        else:
            item.add_argument(
                "--length",
                type=size,
                default=256 if name == "read" else None,
                help=t("read 最大 64 KiB；export 默认整个剩余区域"),
            )
        if name == "export":
            item.add_argument("--output", required=True)
            item.add_argument("--overwrite", action="store_true")

    item = sub.add_parser("clone", help=t("整盘或分区克隆，源目标身份自动重新发现"))
    item.add_argument("source")
    item.add_argument("target")
    backups = group("backup", t("备份库、流式备份、导入导出及恢复"))
    backups.add_parser("list")
    item = area(backups, "create", t("创建备份；--output 直接流式写入本机文件"))
    item.add_argument("--full", action="store_true")
    item.add_argument("--gzip", action="store_true")
    item.add_argument("--usb", help=t("USB 文件系统分区，省略则存入 SD 备份库"))
    item.add_argument("--output", help=t("直接输出 tar/tar.gz，不在备份库暂存"))
    item.add_argument("--overwrite", action="store_true")
    item = backups.add_parser("export")
    item.add_argument("id")
    item.add_argument("--output", required=True)
    item.add_argument("--overwrite", action="store_true")
    backups.add_parser("import").add_argument("input", help=t("本机 tar/tar.gz 备份包"))
    backups.add_parser("delete").add_argument("id")
    item = area(backups, "restore", t("从备份库恢复指定区域或完整 eMMC"))
    item.add_argument("id")
    item.add_argument("--full", action="store_true")
    item = area(backups, "restore-image", t("从本机文件或另一 USB 分区内镜像恢复"))
    item.add_argument("input")
    item.add_argument("--usb", help=t("镜像所在 USB 分区；input 为该分区内路径"))
    item.add_argument("--gzip", action="store_true")
    item.add_argument("--image-size", type=size, help=t("gzip 解压后大小（必填）"))

    jobs = group("jobs", t("查看、等待、取消和清除任务记录"))
    jobs.add_parser("list")
    for name in ("show", "wait", "cancel"):
        jobs.add_parser(name).add_argument("id")
    item = jobs.add_parser("clear")
    item.add_argument("ids", nargs="*")
    item.add_argument(
        "--all", action="store_true", help=t("仅清除已结束且未被下载占用的任务")
    )
    cache = group("cache", t("查看/清理快照、导出及上传缓存"))
    cache.add_parser("list")
    item = cache.add_parser("clear")
    item.add_argument("kind", choices=("snapshots", "downloads", "uploads"))
    item.add_argument("ids", nargs="*")
    item.add_argument("--all", action="store_true")
    snaps = group("snapshots", t("快照列表及分区表回退"))
    snaps.add_parser("list")
    area(snaps, "restore-table", t("从原表快照恢复分区表")).add_argument("id")
    return p


def execute(client, args):
    command, action = args.command, getattr(args, "action", None)
    if command == "upgrade":
        updater = Client(
            os.environ.get("EMMC_UPDATE_SOCKET", "/run/emmc-updater/control.sock")
        )
        if action in ("check", "status"):
            return updater.rpc(action)
        request = {
            "source": "online" if action == "online" else "local",
            "reinstall": args.reinstall,
        }
        if args.dry_run:
            return {
                "operation": "application_upgrade",
                "request": request,
                "submitted": False,
            }
        if action == "import":
            from update_package import MAX_PACKAGE

            with local_source(args.input) as source:
                if os.fstat(source.fileno()).st_size > MAX_PACKAGE:
                    raise CLIError(t("升级包不能超过 128 MiB"))
            request["upload"] = upload(args.input)
        result = updater.rpc("install", request)
        if args.no_wait:
            return result
        task_id = result["task"]["id"]
        while True:
            result = updater.rpc("status")
            if result["task"].get("id") != task_id:
                raise CLIError(t("升级任务状态已变化，请查看 upgrade status"))
            print(
                f"{result['task'].get('progress', 0)}% {t(result['task']['phase'])}",
                file=sys.stderr,
            )
            if result["task"]["state"] != "running":
                if result["task"]["state"] != "completed":
                    raise CLIError(result["task"].get("error", result["task"]["phase"]))
                return result
            time.sleep(2)
    if command == "devices":
        return client.rpc("inventory")
    if command == "system":
        from system_info import system_info

        return system_info()
    if command == "jobs":
        if action == "list":
            return client.rpc("jobs")
        if action == "wait":
            return wait_job(client, args.id)
        if action == "clear":
            if not args.ids and not args.all:
                raise CLIError(t("指定任务 ID 或 --all"))
            return client.rpc("jobs_clear", {"ids": args.ids, "all": args.all})
        return client.rpc("job" if action == "show" else "cancel", {"id": args.id})
    if command == "cache":
        data = client.rpc("cache_list")
        if action == "list":
            return data
        if not args.ids and not args.all:
            raise CLIError(t("指定缓存 ID 或 --all"))
        rows = [
            r
            for r in data["items"]
            if r["kind"] == args.kind and (args.all or r["id"] in args.ids)
        ]
        if not args.all and set(args.ids) != {r["id"] for r in rows}:
            raise CLIError(t("缓存 ID 不存在或类型不符"))
        return client.rpc("cache_clear", {"items": rows})
    if command == "snapshots" and action == "list":
        return client.rpc("snapshots")
    if command == "backup" and action in ("list", "delete"):
        return (
            client.rpc("backups")
            if action == "list"
            else client.rpc("backup_delete", {"id": args.id, "confirm": args.id})
        )
    request, disk, region = ({}, None, None)
    if hasattr(args, "target"):
        request, disk, region = target_args(client, args.target)
    if command == "info":
        return {"disk": disk, "region": region}
    if command == "extcsd":
        return client.rpc("extcsd", request)
    pending_upload = None
    if command == "partition":
        request["op"] = "partition"
        if action == "table":
            request.update(
                action="new_table", table="dos" if args.table == "mbr" else "gpt"
            )
        elif action == "create":
            request.update(
                action="create", start=sectors(args.start), size=sectors(args.size)
            )
        elif action in ("delete", "modify"):
            request.update(action=action, index=args.index)
            if action == "modify":
                part = next(
                    (
                        p
                        for p in (disk.get("table") or {}).get("partitions", [])
                        if re.search(r"p?" + str(args.index) + r"$", p["node"])
                    ),
                    None,
                )
                if not part:
                    raise CLIError(t("分区不存在"))
                if args.label is None and args.type is None and args.bootable is None:
                    raise CLIError(
                        t("至少指定 --label、--type 或 --bootable/--no-bootable")
                    )
                request.update(
                    label=(
                        args.label if args.label is not None else part.get("name", "")
                    ),
                    type=args.type or "",
                    bootable=(
                        args.bootable
                        if args.bootable is not None
                        else bool(part.get("bootable"))
                    ),
                )
        elif action == "format":
            request.update(
                op="format",
                filesystem="vfat" if args.filesystem == "fat32" else args.filesystem,
                label=args.label,
            )
        else:
            request.update(op="resize", size=sectors(args.size))
    elif command == "files":
        request["path"] = args.path
        if action in ("ls", "cat"):
            return client.rpc("files" if action == "ls" else "text", request)
        if action == "get":
            request["op"] = "file_export"
        else:
            request.update(
                op="file_write",
                action={
                    "put": "upload",
                    "text-put": "text",
                    "mv": "rename",
                    "rm": "delete",
                }.get(action, action),
                edit_mode=True,
            )
            if action == "mv":
                request["destination"] = args.destination
            if action in ("put", "text-put"):
                request["overwrite"] = args.overwrite
                if action == "put":
                    pending_upload = args.input
                else:
                    with local_source(args.input) as source:
                        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                            raise CLIError(t("文本输入必须是普通文件"))
                        data = source.read(2 * 1024 * 1024 + 1)
                    if len(data) > 2 * 1024 * 1024:
                        raise CLIError(t("文本编辑最多 2 MiB"))
                    request["text"] = data.decode("utf-8")
                    if args.overwrite:
                        request["expected_sha256"] = client.rpc("text", {**request})[
                            "sha256"
                        ]
    elif command == "hex":
        if action == "undo":
            request.update(op="undo_hex", snapshot=args.snapshot)
        else:
            request["offset"] = args.offset
            if action == "read":
                request["length"] = args.length
                return client.rpc("hex", request)
            if action == "export":
                request.update(
                    op="range_export",
                    length=(
                        args.length
                        if args.length is not None
                        else region["size"] - args.offset
                    ),
                )
            else:
                if args.input:
                    with local_source(args.input) as source:
                        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                            raise CLIError(t("原始字节输入必须是普通文件"))
                        data = source.read(65537)
                else:
                    data = bytes.fromhex(args.data)
                if not 0 < len(data) <= 65536:
                    raise CLIError(t("每次原始写入应为 1–65536 字节"))
                before = client.rpc("hex", {**request, "length": len(data)})
                print(
                    t("目标 ")
                    + args.target
                    + t(f"，偏移 {args.offset}，长度 {len(data)} 字节\n原值：")
                    + before["hex"]
                    + t("\n新值：")
                    + data.hex(),
                    file=sys.stderr,
                )
                request.update(
                    op="hex_write", hex=data.hex(), expected_sha256=before["sha256"]
                )
    elif command == "clone":
        source, _, _ = target_args(client, args.source)
        request.update(
            op="clone", source=args.source, source_identity=source["identity"]
        )
    elif command == "backup":
        if getattr(args, "full", False) and (
            disk["kind"] != "emmc" or region["region"] != "user"
        ):
            raise CLIError(t("完整备份/恢复必须选择 eMMC 用户区"))
        if action == "create":
            if args.usb and args.output:
                raise CLIError(t("--usb 和 --output 不能同时指定"))
            request.update(
                op="backup",
                full=args.full,
                gzip=args.gzip,
                storage="browser" if args.output else "local",
            )
            if args.usb:
                source, _, _ = target_args(client, args.usb)
                request.update(
                    storage="usb",
                    storage_target=args.usb,
                    storage_identity=source["identity"],
                )
        elif action == "export":
            request.update(op="backup_export", backup=args.id)
        elif action == "import":
            request.update(op="import_backup")
            pending_upload = args.input
        elif action == "restore":
            request.update(
                op="restore_full" if args.full else "restore",
                backup=args.id,
                backup_region=region["region"],
            )
        else:
            request.update(op="restore", gzip=args.gzip)
            if args.gzip:
                if not args.image_size:
                    raise CLIError(t("gzip 镜像需要 --image-size（解压后字节数）"))
                request["image_size"] = args.image_size
            if args.usb:
                source, _, _ = target_args(client, args.usb)
                request.update(
                    image_source="usb",
                    image_partition=args.usb,
                    image_identity=source["identity"],
                    image_path=args.input,
                )
            else:
                pending_upload = args.input
    elif command == "snapshots":
        request.update(op="restore_table", snapshot=args.id)
    output = getattr(args, "output", None)
    if args.dry_run:
        return {
            "request": request,
            "input": pending_upload,
            "output": output,
            "submitted": False,
        }
    if output and args.no_wait:
        raise CLIError(t("流式输出需要保持终端连接，不能使用 --no-wait"))
    if pending_upload:
        request["upload"] = upload(pending_upload)
    request["title"] = "CLI: " + command + (" " + action if action else "")
    print(
        t("目标：")
        + request.get("target", request.get("backup", t("备份库")))
        + t("；操作：")
        + request["op"],
        file=sys.stderr,
    )
    if output:
        job = client.rpc("stream_prepare", request)
        print(t("任务 ID：") + job["id"], file=sys.stderr)
        try:
            result = client.stream(
                job["result"]["stream"], output, args.overwrite, job["id"]
            )
            completed = result.pop("job")
            return {"job": completed, "output": result}
        except BaseException:
            try:
                client.rpc("cancel", {"id": job["id"]})
            except Exception:
                pass
            raise
    job = client.rpc("submit", request)
    print(t("任务 ID：") + job["id"], file=sys.stderr)
    return job if args.no_wait else wait_job(client, job["id"])


def display(result, args):
    if args.json or args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "devices":
        for disk in result["disks"]:
            print(
                f"{disk['path']}  {disk.get('model', '')}  {human(disk['size'])}  {disk['identity']}"
                + (t("  [系统盘·受保护]") if disk.get("protected") else "")
            )
            for region in disk["regions"]:
                print(
                    f"  {region['path']:<24} {region['region']:<10} {human(region['size']):>12}  {region.get('fstype') or ''}"
                )
    elif args.command == "hex" and args.action == "read":
        data = bytes.fromhex(result["hex"])
        for start in range(0, len(data), 16):
            row = data[start : start + 16]
            print(
                f"{result['offset'] + start:012x}  {row.hex(' '):47}  "
                + "".join(chr(x) if 32 <= x < 127 else "." for x in row)
            )
        print("SHA-256: " + result["sha256"])
    elif args.command == "extcsd":
        print(result)
    elif args.command == "files" and args.action == "cat":
        print(result["text"], end="")
    else:
        print(json.dumps(localize_status(result), ensure_ascii=False, indent=2))


def main(argv=None):
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument(
        "--lang", choices=("auto", "zh-CN", "en"), default=None
    )
    preference, _ = language_parser.parse_known_args(argv)
    set_language(preference.lang)
    args = parser().parse_args(argv)
    try:
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise CLIError(
                t("本地 CLI 需要 Linux 管理员权限，请使用 sudo emmc-studio …")
            )
        if args.dry_run and (
            args.command in ("jobs", "cache")
            and args.action in ("clear", "cancel")
            or args.command == "backup"
            and args.action == "delete"
        ):
            raise CLIError(t("该即时清理/取消命令不支持 --dry-run，不会执行"))
        display(execute(Client(args.socket), args), args)
        return 0
    except KeyboardInterrupt:
        return 130
    except (CLIError, OSError, ValueError) as error:
        message = t(str(error))
        if (
            isinstance(error, (FileNotFoundError, ConnectionRefusedError))
            and args.socket in message
        ):
            message += t("；请检查 sudo systemctl status emmc-worker")
        print(
            (
                json.dumps({"ok": False, "error": message}, ensure_ascii=False)
                if args.json
                else t("错误：") + message
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
