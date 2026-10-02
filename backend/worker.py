"""Privileged, fixed-operation worker. Unix socket accessible only to emmc-web."""

import base64
import contextlib
import gzip
import hashlib
import json
import os
import pwd
import re
import shutil
import socketserver
import sqlite3
import socket
import struct
import threading
import time
import uuid
from pathlib import Path
from core import *
from stream_download import StreamDownloads
from cache_cleanup import CacheCleanup

STATE = Path(os.environ.get("EMMC_WORKER_STATE", "/var/lib/emmc-worker"))
WEBSTATE = Path(os.environ.get("EMMC_WEB_STATE", "/var/lib/emmc-web"))
RUNTIME = Path(os.environ.get("EMMC_RUNTIME", "/run/emmc-worker"))
SOCKET = RUNTIME / "control.sock"


class Manager:
    def __init__(self):
        for p in (
            STATE,
            STATE / "backups",
            STATE / "snapshots",
            WEBSTATE / "downloads",
            WEBSTATE / "uploads",
            RUNTIME / "mounts",
        ):
            p.mkdir(parents=True, exist_ok=True)
        self.db = STATE / "jobs.sqlite"
        self.db_lock = threading.RLock()
        self.guard = threading.RLock()
        self.busy = set()
        self.upgrade_frozen = False
        self.cancels = {}
        self.mounts = {}
        self.streams = StreamDownloads(self)
        self.cache = CacheCleanup(self, STATE, WEBSTATE)
        with self.connect() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )
            for row in c.execute("SELECT id,data FROM jobs").fetchall():
                d = json.loads(row[1])
                if d["state"] in ("queued", "running"):
                    d.update(
                        state="interrupted",
                        error="设备或服务重启，任务已中断；不会自动继续写入",
                        finished=time.time(),
                    )
                    c.execute(
                        "UPDATE jobs SET data=? WHERE id=?", (json.dumps(d), row[0])
                    )

    @contextlib.contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, job):
        with self.db_lock, self.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?,?)",
                (job["id"], json.dumps(job, ensure_ascii=False)),
            )

    def jobs(self):
        with self.db_lock, self.connect() as c:
            return sorted(
                [json.loads(r[0]) for r in c.execute("SELECT data FROM jobs")],
                key=lambda x: x["created"],
                reverse=True,
            )[:100]

    def get_job(self, jid):
        with self.db_lock, self.connect() as c:
            row = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise StorageError("任务不存在")
        return json.loads(row[0])

    def acquire(self, keys):
        with self.guard:
            if self.upgrade_frozen or Path("/run/emmc-updater/maintenance").exists():
                raise StorageError("应用正在升级，暂时不能提交存储操作")
            if set(keys) & self.busy:
                raise StorageError("磁盘正在执行其他操作，请等待任务结束")
            self.busy.update(keys)

    def release(self, keys):
        with self.guard:
            self.busy.difference_update(keys)

    def extcsd(self, path, locked=False):
        d, r = resolve_region(path)
        if d["kind"] != "emmc" or r["region"] != "user":
            raise StorageError("仅 eMMC 用户区支持 EXT_CSD")
        if not locked:
            self.acquire([d["identity"]])
        try:
            return run(["mmc", "extcsd", "read", path])
        finally:
            if not locked:
                self.release([d["identity"]])

    def check_unused(self, disk):
        # Worker owns a private mount namespace; never force-unmount other users.
        for r in disk["regions"]:
            path = r["path"]
            managed = self.mounts.get(path)
            if managed:
                run(["umount", str(managed["root"])])
                self.mounts.pop(path, None)
            mounts = run(
                ["findmnt", "-rn", "-S", path, "-o", "TARGET"], accepted=(0, 1)
            ).strip()
            if host_mounts(path):
                raise StorageError(f"{path} 在主机命名空间被挂载，拒绝原始写入")
            if mounts:
                raise StorageError(f"{path} 已被其他程序挂载：{mounts}")
        # Swap and open block-device holders also count as users.
        swaps = read("/proc/swaps")
        for r in disk["regions"]:
            if r["path"] in swaps or list(
                Path("/sys/class/block", r["kname"], "holders").glob("*")
            ):
                raise StorageError("设备正被交换空间或其他块设备使用")
            if run(["fuser", r["path"]], accepted=(0, 1)).strip():
                raise StorageError("块设备正被其他进程打开，不能进行原始读写")

    def mount(self, region, writable=False):
        path = region["path"]
        d, r = resolve_region(path, region["identity"], write=writable)
        if d["protected"] or r["region"] != "partition":
            raise StorageError("只能浏览非系统磁盘中的文件系统分区")
        if r.get("fstype") not in ("ext2", "ext3", "ext4", "vfat", "exfat", "ntfs"):
            raise StorageError("该文件系统不支持文件管理")
        old = self.mounts.get(path)
        if old and old["rw"] == writable:
            return old["root"]
        if old:
            run(["umount", str(old["root"])])
            self.mounts.pop(path, None)
        if (
            host_mounts(path)
            or run(
                ["findmnt", "-rn", "-S", path, "-o", "TARGET"], accepted=(0, 1)
            ).strip()
        ):
            raise StorageError("分区已被其他程序挂载，不能由网页接管")
        root = (
            RUNTIME
            / "mounts"
            / hashlib.sha256((d["identity"] + path).encode()).hexdigest()[:24]
        )
        root.mkdir(exist_ok=True)
        opts = "rw,nosuid,nodev,noexec" if writable else "ro,nosuid,nodev,noexec"
        if not writable and r.get("fstype") in ("ext3", "ext4"):
            opts += ",noload"
        run(["mount", "-o", opts, path, str(root)])
        self.mounts[path] = {"root": root, "rw": writable}
        return root

    def fs_list(self, args):
        d, r = resolve_region(args["target"], args["identity"])
        self.acquire([d["identity"]])
        try:
            root = self.mount(r, False)
            folder = safe_path(root, args.get("path", ""))
            if not folder.is_dir():
                raise StorageError("不是目录")
            entries = []
            for f in sorted(
                folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())
            ):
                s = f.lstat()
                entries.append(
                    {
                        "name": f.name,
                        "directory": stat.S_ISDIR(s.st_mode),
                        "symlink": f.is_symlink(),
                        "size": s.st_size,
                        "modified": s.st_mtime,
                    }
                )
                if len(entries) > 10000:
                    raise StorageError("目录条目超过 10000，请使用更细的目录")
            return {
                "entries": entries,
                "path": str(folder.relative_to(root)),
                "readonly": True,
            }
        finally:
            self.release([d["identity"]])

    def fs_text(self, args):
        d, r = resolve_region(args["target"], args["identity"])
        self.acquire([d["identity"]])
        try:
            root = self.mount(r, False)
            f = safe_path(root, args["path"])
            if not f.is_file() or f.stat().st_size > TEXT_LIMIT:
                raise StorageError("文本编辑只支持不超过 2 MiB 的普通文件")
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeError:
                raise StorageError("该文件不是 UTF-8 文本，请使用下载或扇区编辑")
            return {"text": text, "sha256": sha_file(f)}
        finally:
            self.release([d["identity"]])

    def hex_read(self, args):
        d, r = resolve_region(args["target"], args["identity"])
        self.acquire([d["identity"]])
        try:
            off, length = bounds(
                args.get("offset", 0), args.get("length", 512), r["size"], HEX_LIMIT
            )
            fd = pinned_open(r["path"], os.O_RDONLY)
            try:
                data = os.pread(fd, length, off)
            finally:
                os.close(fd)
            if len(data) != length:
                raise StorageError("设备读取不完整")
            return {
                "hex": data.hex(),
                "offset": off,
                "length": length,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        finally:
            self.release([d["identity"]])

    def backups(self):
        result = []
        for entry in (STATE / "backups").glob("*/manifest.json"):
            try:
                m = json.loads(entry.read_text())
                m["id"] = entry.parent.name
                result.append(m)
            except (OSError, ValueError):
                pass
        return sorted(result, key=lambda x: x["created"], reverse=True)

    def submit(self, args):
        op = args.get("op")
        allowed = (
            "backup",
            "clone",
            "restore",
            "restore_full",
            "partition",
            "format",
            "resize",
            "hex_write",
            "file_write",
            "file_export",
            "range_export",
            "backup_export",
            "import_backup",
            "restore_table",
            "undo_hex",
        )
        if op not in allowed:
            raise StorageError("不支持的操作")
        readops = ("backup", "file_export", "range_export", "backup_export")
        keys = []
        if op not in ("backup_export", "import_backup"):
            d, r = resolve_region(
                args["target"], args.get("identity"), write=op not in readops
            )
            if args.get("identity") != d["identity"]:
                raise StorageError("必须提供准确的设备身份")
            keys.append(d["identity"])
            if op == "clone":
                sd, sr = resolve_region(args["source"], args.get("source_identity"))
                if args.get("source_identity") != sd["identity"]:
                    raise StorageError("必须提供源设备身份")
                check_overlap(sd, d)
                if sr["size"] > r["size"]:
                    raise StorageError("源容量大于目标，禁止自动裁剪")
                if r["region"] in ("boot0", "boot1") or sr["region"] in (
                    "boot0",
                    "boot1",
                ):
                    raise StorageError("BOOT 区请使用备份恢复功能")
                if (r["region"] == "user") != (sr["region"] == "user"):
                    raise StorageError("整盘必须对应整盘，分区必须对应分区")
                keys.append(sd["identity"])
            if args.get("storage") == "usb":
                sd, sr = resolve_region(
                    args["storage_target"], args["storage_identity"], write=True
                )
                if sd["kind"] != "usb" or sr["region"] != "partition":
                    raise StorageError("备份存储必须是 USB 文件系统分区")
                if sd["identity"] in keys:
                    raise StorageError("不能把备份写入源磁盘")
                keys.append(sd["identity"])
            if args.get("image_source") == "usb":
                sd, sr = resolve_region(args["image_partition"], args["image_identity"])
                if sd["kind"] != "usb" or sd["identity"] in keys:
                    raise StorageError("镜像必须来自另一块 USB 存储")
                keys.append(sd["identity"])
        if op in ("backup_export", "restore", "restore_full") and args.get("backup"):
            manifest = json.loads(
                token_path(STATE / "backups", args["backup"])
                .joinpath("manifest.json")
                .read_text()
            )
            if manifest.get("storage") == "usb":
                sd, sr = resolve_region(
                    manifest["storage_target"], manifest["storage_identity"]
                )
                if sd["identity"] in keys:
                    raise StorageError("备份不能与恢复目标处于同一磁盘")
                keys.append(sd["identity"])
        self.acquire(keys)
        job = {
            "id": uuid.uuid4().hex,
            "op": op,
            "title": args.get("title", op),
            "state": "queued",
            "created": time.time(),
            "progress": 0,
            "bytes": 0,
            "total": 0,
            "speed": 0,
            "phase": "等待",
            "logs": [],
            "target": args.get("target"),
            "cancellable": True,
        }
        self.save(job)
        event = threading.Event()
        self.cancels[job["id"]] = event
        threading.Thread(
            target=self.execute, args=(job, args, keys, event), daemon=True
        ).start()
        return job

    def execute(self, job, args, keys, event):
        last = [0, 0]
        start = time.monotonic()

        def progress(done, total, phase):
            now = time.monotonic()
            if phase != job["phase"]:
                job["logs"].append({"time": time.time(), "message": phase})
                job["logs"] = job["logs"][-100:]
            job.update(
                bytes=done,
                total=total,
                progress=round(done / max(total, 1) * 100, 2),
                phase=phase,
                speed=int(done / max(now - start, 0.001)),
            )
            if now - last[0] > 0.4 or done == total:
                last[0] = now
                self.save(job)

        try:
            job.update(state="running", started=time.time())
            self.save(job)
            result = self.perform(args, job, progress, event.is_set)
            job.update(state="completed", progress=100, phase="完成", result=result)
        except Exception as e:
            job.update(
                state="cancelled" if event.is_set() else "failed",
                error=str(e),
                phase="已取消" if event.is_set() else "失败",
            )
            job["logs"].append({"time": time.time(), "message": str(e)})
        finally:
            job["finished"] = time.time()
            job["cancellable"] = False
            self.save(job)
            self.release(keys)
            self.cancels.pop(job["id"], None)

    def uploaded(self, args):
        p = token_path(WEBSTATE / "uploads", args["upload"])
        meta = p.with_suffix(".json")
        if not p.is_file() or not meta.exists():
            raise StorageError("上传文件不存在")
        m = json.loads(meta.read_text())
        if not m.get("complete") or p.stat().st_size != m["size"]:
            raise StorageError("上传尚未完成")
        return p

    def source_image(self, args):
        if args.get("backup"):
            m = json.loads(
                token_path(STATE / "backups", args["backup"])
                .joinpath("manifest.json")
                .read_text()
            )
            item = next(
                (r for r in m["regions"] if r["region"] == args.get("backup_region")),
                None,
            )
            if not item:
                raise StorageError("备份中没有该区域")
            p = safe_path(self.backup_files(m), item["file"])
            if sha_file(p) != item["file_sha256"]:
                raise StorageError("备份文件校验失败")
            args.update(
                gzip=item["compressed"],
                image_size=item["size"],
                expected_image_sha256=item["sha256"],
            )
            return p
        if args.get("image_source") == "usb":
            d, r = resolve_region(args["image_partition"], args["image_identity"])
            root = self.mount(r, False)
            p = safe_path(root, args["image_path"])
            if not p.is_file():
                raise StorageError("镜像路径不是文件")
            return p
        return self.uploaded(args)

    def ensure_space(self, folder, size):
        if shutil.disk_usage(folder).free < size + 64 * 1024 * 1024:
            raise StorageError("存储空间不足（需要额外保留 64 MiB）")

    def table_snapshot(self, disk):
        sid = uuid.uuid4().hex
        folder = STATE / "snapshots" / sid
        folder.mkdir()
        dump = run(["sfdisk", "--dump", disk["path"]], accepted=(0, 1))
        (folder / "table.txt").write_text(dump)
        gpt = disk.get("table") and disk["table"]["label"] == "gpt"
        head_length = 34 * 512 if gpt else 512
        tail_length = 33 * 512 if gpt else 0
        fd = pinned_open(disk["path"], os.O_RDONLY)
        try:
            (folder / "head.bin").write_bytes(os.pread(fd, head_length, 0))
            if tail_length:
                (folder / "tail.bin").write_bytes(
                    os.pread(fd, tail_length, disk["size"] - tail_length)
                )
        finally:
            os.close(fd)
        (folder / "meta.json").write_text(
            json.dumps(
                {
                    "disk": disk["identity"],
                    "size": disk["size"],
                    "created": time.time(),
                    "kind": "table",
                    "head_length": head_length,
                    "tail_length": tail_length,
                }
            )
        )
        return sid

    def reread(self, disk):
        run(["blockdev", "--rereadpt", disk["path"]])
        run(["udevadm", "settle"], timeout=30)

    def export(self, src, name, progress, cancel):
        token = uuid.uuid4().hex
        out = WEBSTATE / "downloads" / token
        self.ensure_space(out.parent, src.stat().st_size)
        try:
            with open(src, "rb") as s, open(out, "w+b") as t:
                digest = copy_stream(s, t, src.stat().st_size, progress, cancel)
            out.chmod(0o640)
            out.with_suffix(".json").write_text(
                json.dumps({"name": name, "size": out.stat().st_size, "sha256": digest})
            )
            return {"download": token, "name": name, "sha256": digest}
        except Exception:
            out.unlink(missing_ok=True)
            raise

    def backup_files(self, manifest):
        folder = Path(manifest["location"])
        if manifest.get("storage") == "usb":
            d, r = resolve_region(
                manifest["storage_target"], manifest["storage_identity"]
            )
            root = self.mount(r, False)
            folder = safe_path(root, manifest["relative_location"])
        return folder

    def perform(self, args, job, progress, cancel):
        op = args["op"]
        if op == "import_backup":
            return self.import_backup(args, progress, cancel)
        if op == "backup_export":
            manifest = json.loads(
                token_path(STATE / "backups", args["backup"])
                .joinpath("manifest.json")
                .read_text()
            )
            import tarfile

            token = uuid.uuid4().hex
            out = WEBSTATE / "downloads" / token
            folder = self.backup_files(manifest)
            files = list(folder.iterdir())
            total = sum(f.stat().st_size for f in files)
            self.ensure_space(out.parent, total)
            done = 0
            reported = 0

            class DownloadReader:
                def __init__(self, source):
                    self.source = source

                def read(self, length=-1):
                    nonlocal done, reported
                    if cancel():
                        raise StorageError("导出已取消")
                    chunk = self.source.read(length)
                    done += len(chunk)
                    if done - reported >= BLOCK or done == total:
                        reported = done
                        progress(done, total, "打包浏览器下载")
                    return chunk

            progress(0, total, "打包浏览器下载")
            try:
                with tarfile.open(out, "w") as archive:
                    for f in files:
                        if cancel():
                            raise StorageError("导出已取消")
                        with open(f, "rb") as source:
                            archive.addfile(
                                archive.gettarinfo(str(f), arcname=f.name),
                                DownloadReader(source),
                            )
            except Exception:
                out.unlink(missing_ok=True)
                raise
            out.chmod(0o640)
            out.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "name": f'emmc-backup-{args["backup"][:8]}.tar',
                        "size": out.stat().st_size,
                    }
                )
            )
            return {"download": token}
        disk, region = resolve_region(
            args["target"],
            args["identity"],
            write=op not in ("backup", "file_export", "range_export"),
        )
        if op == "backup":
            result = self.backup(args, disk, region, job, progress, cancel)
            if args.get("storage") == "browser":
                result.update(
                    self.perform(
                        {"op": "backup_export", "backup": result["backup"]},
                        job,
                        progress,
                        cancel,
                    )
                )
            return result
        if op == "file_export":
            root = self.mount(region, False)
            p = safe_path(root, args["path"])
            if not p.is_file():
                raise StorageError("只能导出普通文件")
            return self.export(p, p.name, progress, cancel)
        if op == "range_export":
            off, length = bounds(
                args.get("offset", 0), args["length"], region["size"], 64 * 1024 * 1024
            )
            token = uuid.uuid4().hex
            out = WEBSTATE / "downloads" / token
            self.ensure_space(out.parent, length)
            fd = pinned_open(region["path"], os.O_RDONLY)
            try:
                with os.fdopen(fd, "rb", buffering=0) as s, open(out, "w+b") as t:
                    s.seek(off)
                    digest = copy_stream(s, t, length, progress, cancel)
                out.chmod(0o640)
                out.with_suffix(".json").write_text(
                    json.dumps({"name": f'{region["name"]}-{off}.bin', "size": length})
                )
                return {"download": token, "sha256": digest}
            except Exception:
                out.unlink(missing_ok=True)
                raise
        if op == "file_write":
            if args.get("edit_mode") is not True:
                raise StorageError("请先开启文件编辑模式")
            job["cancellable"] = False
            self.save(job)
            root = self.mount(region, True)
            try:
                return self.file_write(args, root)
            finally:
                os.sync()
                run(["umount", str(root)])
                self.mounts.pop(region["path"], None)
        self.check_unused(disk)
        if op in ("restore", "clone"):
            if region["region"] == "user":
                snapshot = self.table_snapshot(disk)
            else:
                snapshot = None
            if op == "clone":
                sd, sr = resolve_region(args["source"], args["source_identity"])
                self.check_unused(sd)
                source = os.fdopen(
                    pinned_open(sr["path"], os.O_RDONLY), "rb", buffering=0
                )
                length = sr["size"]
            else:
                if args.get("backup") and args.get("backup_region") != region["region"]:
                    raise StorageError("备份区域与目标区域类型不一致")
                p = self.source_image(args)
                if args.get("gzip"):
                    length = number(args["image_size"], 1, region["size"])
                    h = hashlib.sha256()
                    actual = 0
                    with gzip.open(p, "rb") as precheck:
                        while chunk := precheck.read(BLOCK):
                            if cancel():
                                raise StorageError("镜像预校验已取消")
                            h.update(chunk)
                            actual += len(chunk)
                            progress(actual, length, "镜像预校验")
                            if actual > length:
                                raise StorageError("解压镜像大于声明大小，未执行写入")
                    if actual != length:
                        raise StorageError("解压镜像长度与声明不符，未执行写入")
                    if (
                        args.get("expected_image_sha256")
                        and h.hexdigest() != args["expected_image_sha256"]
                    ):
                        raise StorageError("备份数据校验失败")
                    source = gzip.open(p, "rb")
                else:
                    length = p.stat().st_size
                    source = open(p, "rb")
                    if (
                        args.get("expected_image_sha256")
                        and sha_file(p) != args["expected_image_sha256"]
                    ):
                        source.close()
                        raise StorageError("备份数据校验失败")
                if not 0 < length <= region["size"]:
                    source.close()
                    raise StorageError("镜像大于目标或为空")
            with source, boot_writable(region):
                with os.fdopen(
                    pinned_open(region["path"], os.O_RDWR), "r+b", buffering=0
                ) as t:
                    digest = copy_stream(
                        source, t, length, progress, cancel, verify=True
                    )
                    if op == "restore" and source.read(1):
                        raise StorageError("解压镜像大于声明大小，写入范围已停止")
            if region["region"] == "user":
                self.reread(disk)
            return {"sha256": digest, "written": length, "table_snapshot": snapshot}
        if op == "restore_full":
            return self.restore_full(args, disk, progress, cancel)
        if op in ("hex_write", "undo_hex"):
            job["cancellable"] = False
            self.save(job)
            off = number(args.get("offset", 0))
            if op == "undo_hex":
                folder = token_path(STATE / "snapshots", args["snapshot"])
                meta = json.loads((folder / "meta.json").read_text())
                if (
                    meta["disk"] != disk["identity"]
                    or meta["target"] != region["path"]
                    or meta.get("kind") != "hex"
                ):
                    raise StorageError("回退记录与目标不匹配")
                data = (folder / "before.bin").read_bytes()
                off = meta["offset"]
                expected = meta["after_sha256"]
            else:
                try:
                    data = bytes.fromhex(args["hex"])
                except ValueError:
                    raise StorageError("十六进制数据无效")
                expected = args.get("expected_sha256")
                if not expected:
                    raise StorageError("需要提供编辑前的数据校验值")
            off, length = bounds(off, len(data), region["size"], HEX_LIMIT)
            sid = uuid.uuid4().hex
            folder = STATE / "snapshots" / sid
            folder.mkdir()
            with boot_writable(region), os.fdopen(
                pinned_open(region["path"], os.O_RDWR), "r+b", buffering=0
            ) as t:
                t.seek(off)
                before = t.read(length)
                if hashlib.sha256(before).hexdigest() != expected:
                    raise StorageError("目标内容已变化，重新读取后再编辑")
                (folder / "before.bin").write_bytes(before)
                (folder / "meta.json").write_text(
                    json.dumps(
                        {
                            "disk": disk["identity"],
                            "target": region["path"],
                            "offset": off,
                            "size": length,
                            "after_sha256": hashlib.sha256(data).hexdigest(),
                            "created": time.time(),
                            "kind": "hex",
                        }
                    )
                )
                t.seek(off)
                t.write(data)
                t.flush()
                os.fsync(t.fileno())
                t.seek(off)
                if t.read(length) != data:
                    raise StorageError("写入读回校验失败")
            if region["region"] == "user":
                self.reread(disk)
            return {"snapshot": sid, "written": length, "offset": off}
        if op == "restore_table":
            job["cancellable"] = False
            self.save(job)
            folder = token_path(STATE / "snapshots", args["snapshot"])
            meta = json.loads((folder / "meta.json").read_text())
            if (
                region["region"] != "user"
                or meta["disk"] != disk["identity"]
                or meta["size"] != disk["size"]
                or meta.get("kind") != "table"
            ):
                raise StorageError("分区表快照与目标不匹配")
            sid = self.table_snapshot(disk)
            with os.fdopen(
                pinned_open(disk["path"], os.O_RDWR), "r+b", buffering=0
            ) as t:
                spans = [("head", 0)]
                if meta.get("tail_length"):
                    spans.append(("tail", disk["size"] - meta["tail_length"]))
                for name, off in spans:
                    t.seek(off)
                    t.write((folder / (name + ".bin")).read_bytes())
                t.flush()
                os.fsync(t.fileno())
            self.reread(disk)
            return {"table_snapshot": sid}
        if op == "partition":
            return self.partition(args, disk, region, job)
        if op == "format":
            if region["region"] != "partition":
                raise StorageError("格式化必须选择分区")
            fs = args["filesystem"]
            label = str(args.get("label", ""))
            if not re.fullmatch(r"[\w .-]{0,11}", label, re.UNICODE):
                raise StorageError("卷标仅允许 11 位以内的字母、数字、空格、点和横线")
            commands = {
                "ext4": ["mkfs.ext4", "-F", "-L", label],
                "vfat": ["mkfs.vfat", "-F", "32", "-n", label],
                "exfat": ["mkfs.exfat", "-L", label],
                "ntfs": ["mkfs.ntfs", "-F", "-Q", "-L", label],
            }
            if fs not in commands:
                raise StorageError("不支持的文件系统")
            job["cancellable"] = False
            self.save(job)
            output = run(commands[fs] + [region["path"]], timeout=600)
            return {"output": output[-4000:]}
        if op == "resize":
            return self.resize(args, disk, region, job)
        raise StorageError("操作不存在")

    def partition(self, args, disk, region, job):
        if region["region"] != "user":
            raise StorageError("分区表操作必须选择整盘用户区")
        sid = self.table_snapshot(disk)
        action = args["action"]
        job["cancellable"] = False
        self.save(job)
        if action == "new_table":
            table = args["table"]
            if table not in ("gpt", "dos"):
                raise StorageError("分区表类型无效")
            run(["sfdisk", disk["path"]], input=f"label: {table}\n")
        elif action == "create":
            start = number(args["start"], 2048)
            size = number(args["size"], 2048)
            if start % 2048 or size % 2048:
                raise StorageError("分区起点和大小必须按 1 MiB 对齐")
            end = start + size
            if end > disk["size"] // 512 - (
                34 if disk["table"] and disk["table"]["label"] == "gpt" else 0
            ):
                raise StorageError("分区超过可用容量")
            for p in (disk["table"] or {}).get("partitions", []):
                if start < p["start"] + p["size"] and p["start"] < end:
                    raise StorageError("与已有分区重叠")
            if not disk["table"]:
                raise StorageError("请先建立分区表")
            if (
                disk["table"]["label"] == "dos"
                and len(disk["table"].get("partitions", [])) >= 4
            ):
                raise StorageError(
                    "本工具只创建最多四个 MBR 主分区，已有扩展分区可查看和备份"
                )
            typ = "L"
            run(
                ["sfdisk", "--append", disk["path"]],
                input=f"start={start},size={size},type={typ}\n",
            )
        elif action in ("delete", "modify"):
            index = number(args["index"], 1, 128)
            parts = (disk["table"] or {}).get("partitions", [])
            if not any(re.search(r"p?" + str(index) + r"$", p["node"]) for p in parts):
                raise StorageError("分区不存在")
            if action == "delete":
                run(["sfdisk", "--delete", disk["path"], str(index)])
            else:
                label = str(args.get("label", ""))
                if len(label) > 36 or "\x00" in label or "\n" in label:
                    raise StorageError("分区名称无效")
                if disk["table"]["label"] == "gpt":
                    run(["sfdisk", "--part-label", disk["path"], str(index), label])
                typ = str(args.get("type", ""))
                if typ:
                    if not re.fullmatch(
                        r"[a-fA-F0-9]{1,4}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}",
                        typ,
                    ):
                        raise StorageError("分区类型必须是十六进制代码或 GUID")
                    run(["sfdisk", "--part-type", disk["path"], str(index), typ])
                if disk["table"]["label"] == "dos":
                    active = [
                        str(int(re.search(r"(\d+)$", p["node"]).group(1)))
                        for p in parts
                        if p.get("bootable")
                        and int(re.search(r"(\d+)$", p["node"]).group(1)) != index
                    ]
                    if args.get("bootable"):
                        active.append(str(index))
                    if active:
                        run(["sfdisk", "--activate", disk["path"]] + active)
                    else:
                        # No arguments means list, not clear: edit the MBR boot flags directly.
                        with os.fdopen(
                            pinned_open(disk["path"], os.O_RDWR), "r+b", buffering=0
                        ) as f:
                            for i in range(4):
                                f.seek(446 + i * 16)
                                f.write(b"\x00")
                            f.flush()
                            os.fsync(f.fileno())
        else:
            raise StorageError("分区操作无效")
        self.reread(disk)
        return {
            "table_snapshot": sid,
            "table": json.loads(run(["sfdisk", "--json", disk["path"]]))[
                "partitiontable"
            ],
        }

    def resize(self, args, disk, region, job):
        if region["region"] != "partition" or region.get("fstype") != "ext4":
            raise StorageError("只支持离线调整 ext4 分区")
        newsize = number(args["size"], 2048)
        index = number(re.search(r"(\d+)$", region["name"]).group(1), 1)
        if newsize % 2048:
            raise StorageError("大小必须按 1 MiB 对齐")
        part = next(
            p for p in disk["table"]["partitions"] if p["node"] == region["path"]
        )
        end = part["start"] + newsize
        if end > disk["size"] // 512 - (34 if disk["table"]["label"] == "gpt" else 0):
            raise StorageError("超过磁盘末尾")
        for p in disk["table"]["partitions"]:
            if (
                p["node"] != region["path"]
                and part["start"] < p["start"] + p["size"]
                and p["start"] < end
            ):
                raise StorageError("调整后与其他分区重叠")
        sid = self.table_snapshot(disk)
        job["cancellable"] = False
        self.save(job)
        run(["e2fsck", "-f", "-p", region["path"]], accepted=(0, 1), timeout=1200)
        if newsize < part["size"]:
            run(["resize2fs", region["path"], str(newsize // 2) + "K"], timeout=1200)
        run(
            ["sfdisk", "-N", str(index), disk["path"]],
            input=f'start={part["start"]},size={newsize},type={part["type"]}\n',
        )
        self.reread(disk)
        if newsize >= part["size"]:
            run(["resize2fs", region["path"]], timeout=1200)
        return {"table_snapshot": sid, "size": newsize * 512}

    def file_write(self, args, root):
        action = args["action"]
        p = safe_path(
            root, args["path"], allow_missing=action in ("mkdir", "text", "upload")
        )
        if p == root:
            raise StorageError("不能修改挂载根目录")
        if action == "mkdir":
            p.mkdir()
        elif action == "delete":
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        elif action == "rename":
            dest = safe_path(root, args["destination"], True)
            if dest.exists():
                raise StorageError("目标名称已存在")
            p.rename(dest)
        elif action in ("text", "upload"):
            if p.exists() and not p.is_file():
                raise StorageError("目标不是普通文件")
            if p.exists() and not args.get("overwrite"):
                raise StorageError("文件已存在，请确认覆盖")
            if (
                args.get("expected_sha256")
                and p.exists()
                and sha_file(p) != args["expected_sha256"]
            ):
                raise StorageError("文件已变化，请重新读取")
            temp = p.parent / (".emmc-" + uuid.uuid4().hex)
            try:
                if action == "text":
                    data = str(args["text"]).encode("utf-8")
                    if len(data) > TEXT_LIMIT:
                        raise StorageError("文本超过 2 MiB")
                    self.ensure_space(p.parent, len(data))
                    temp.write_bytes(data)
                else:
                    src = self.uploaded(args)
                    self.ensure_space(p.parent, src.stat().st_size)
                    shutil.copyfile(src, temp)
                if p.exists():
                    os.chmod(temp, p.stat().st_mode & 0o777)
                with open(temp, "rb") as f:
                    os.fsync(f.fileno())
                os.replace(temp, p)
            finally:
                temp.unlink(missing_ok=True)
        else:
            raise StorageError("文件操作无效")
        return {"path": str(p.relative_to(root)), "action": action}

    def backup(self, args, disk, region, job, progress, cancel):
        self.check_unused(disk)
        regions = (
            disk["regions"][:3]
            if args.get("full") and disk["kind"] == "emmc"
            else [region]
        )
        if args.get("full") and region["region"] != "user":
            raise StorageError("完整备份必须选择 eMMC 用户区")
        # Explicit region types avoid accidentally including filesystem partitions twice.
        if args.get("full"):
            regions = [
                r for r in disk["regions"] if r["region"] in ("user", "boot0", "boot1")
            ]
        bid = uuid.uuid4().hex
        catalog = STATE / "backups" / bid
        catalog.mkdir()
        folder = catalog
        storage = args.get("storage", "local")
        if storage not in ("local", "usb", "browser"):
            raise StorageError("备份存储类型不支持")
        if storage == "usb":
            sd, sr = resolve_region(
                args["storage_target"], args["storage_identity"], write=True
            )
            root = self.mount(sr, True)
            folder = root / "emmc-backups" / bid
            folder.mkdir(parents=True)
        self.ensure_space(
            folder, sum(r["size"] for r in regions) * (2 if storage == "browser" else 1)
        )
        manifest = {
            "version": 1,
            "created": time.time(),
            "identity": disk["identity"],
            "model": disk["model"],
            "disk_size": disk["size"],
            "table": disk["table"],
            "full": bool(args.get("full")),
            "storage": storage,
            "location": str(folder),
            "regions": [],
        }
        if disk["kind"] == "emmc":
            manifest["extcsd"] = self.extcsd(disk["path"], locked=True)
        if storage == "usb":
            manifest.update(
                storage_target=args["storage_target"],
                storage_identity=args["storage_identity"],
                relative_location=f"emmc-backups/{bid}",
            )
        try:
            for r in regions:
                compressed = bool(args.get("gzip"))
                filename = r["region"] + ".img" + (".gz" if compressed else "")
                output = folder / filename
                h = hashlib.sha256()
                done = 0
                fd = pinned_open(r["path"], os.O_RDONLY)
                with os.fdopen(fd, "rb", buffering=0) as s, open(
                    output, "wb"
                ) as underlying:
                    t = (
                        gzip.GzipFile(fileobj=underlying, mode="wb", compresslevel=1)
                        if compressed
                        else underlying
                    )
                    try:
                        while done < r["size"]:
                            if cancel():
                                raise StorageError("备份已取消")
                            chunk = s.read(min(BLOCK, r["size"] - done))
                            if not chunk:
                                raise StorageError("源设备提前结束")
                            h.update(chunk)
                            t.write(chunk)
                            done += len(chunk)
                            progress(done, r["size"], "备份 " + r["region"])
                    finally:
                        if compressed:
                            t.close()
                    underlying.flush()
                    os.fsync(underlying.fileno())
                manifest["regions"].append(
                    {
                        "region": r["region"],
                        "name": r["name"],
                        "size": r["size"],
                        "file": filename,
                        "compressed": compressed,
                        "sha256": h.hexdigest(),
                        "file_sha256": sha_file(output),
                    }
                )
            (folder / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            if folder != catalog:
                (catalog / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2)
                )
        except Exception:
            (folder / "INCOMPLETE").write_text("备份未完成，不可用于恢复")
            raise
        finally:
            if storage == "usb":
                os.sync()
                run(["umount", str(root)])
                self.mounts.pop(args["storage_target"], None)
        return {"backup": bid, "manifest": manifest}

    def restore_full(self, args, disk, progress, cancel):
        if disk["kind"] != "emmc":
            raise StorageError("完整恢复只支持 eMMC")
        manifest = json.loads(
            token_path(STATE / "backups", args["backup"])
            .joinpath("manifest.json")
            .read_text()
        )
        folder = self.backup_files(manifest)
        if not manifest.get("full"):
            raise StorageError("该备份不是完整备份")
        if {r["region"] for r in manifest["regions"]} != {"user", "boot0", "boot1"}:
            raise StorageError("完整备份必须包含用户区及两个 BOOT 区")
        targets = {r["region"]: r for r in disk["regions"]}
        # Verify every backup before the first write.
        for item in manifest["regions"]:
            r = targets.get(item["region"])
            if not r or item["size"] > r["size"]:
                raise StorageError("备份区域与目标容量不兼容")
            p = safe_path(folder, item["file"])
            if sha_file(p) != item["file_sha256"]:
                raise StorageError("备份文件 SHA-256 校验失败")
            reader = gzip.open(p, "rb") if item["compressed"] else open(p, "rb")
            with reader:
                h = hashlib.sha256()
                length = 0
                while chunk := reader.read(BLOCK):
                    if cancel():
                        raise StorageError("恢复校验已取消")
                    h.update(chunk)
                    length += len(chunk)
                    progress(length, item["size"], "预校验 " + item["region"])
                    if length > item["size"]:
                        raise StorageError("备份解压长度不符")
                if length != item["size"] or h.hexdigest() != item["sha256"]:
                    raise StorageError("备份数据不完整")
        sid = self.table_snapshot(disk)
        for item in manifest["regions"]:
            r = targets[item["region"]]
            p = safe_path(folder, item["file"])
            with (
                gzip.open(p, "rb") if item["compressed"] else open(p, "rb")
            ) as s, boot_writable(r), os.fdopen(
                pinned_open(r["path"], os.O_RDWR), "r+b", buffering=0
            ) as t:
                digest = copy_stream(s, t, item["size"], progress, cancel, verify=True)
                if digest != item["sha256"]:
                    raise StorageError("恢复校验不一致")
        self.reread(disk)
        return {"table_snapshot": sid, "regions": len(manifest["regions"])}

    def import_backup(self, args, progress, cancel):
        import tarfile

        src = self.uploaded(args)
        bid = uuid.uuid4().hex
        folder = STATE / "backups" / bid
        folder.mkdir()
        try:
            with tarfile.open(src, "r:*") as archive:
                members = archive.getmembers()
                if len(members) > 6 or any(
                    not x.isfile() or Path(x.name).name != x.name for x in members
                ):
                    raise StorageError(
                        "备份包只能包含区域镜像和 manifest.json，不允许目录或链接"
                    )
                item = next((m for m in members if m.name == "manifest.json"), None)
                if not item or item.size > 1024 * 1024:
                    raise StorageError("缺少有效的备份清单")
                manifest = json.loads(archive.extractfile(item).read())
                if manifest.get("version") != 1 or not isinstance(
                    manifest.get("regions"), list
                ):
                    raise StorageError("备份版本不支持")
                areas = manifest["regions"]
                if not 1 <= len(areas) <= 3 or len({r["region"] for r in areas}) != len(
                    areas
                ):
                    raise StorageError("备份区域清单无效")
                expected = {"manifest.json"}
                for r in areas:
                    if (
                        r["region"] not in ("user", "boot0", "boot1", "partition")
                        or Path(r["file"]).name != r["file"]
                    ):
                        raise StorageError("备份文件名无效")
                    if not re.fullmatch(
                        r"(user|boot0|boot1|partition)\.img(\.gz)?", r["file"]
                    ):
                        raise StorageError("区域镜像文件名无效")
                    number(r["size"], 1)
                    if not all(
                        re.fullmatch("[0-9a-f]{64}", str(r[k]))
                        for k in ("sha256", "file_sha256")
                    ):
                        raise StorageError("校验清单无效")
                    expected.add(r["file"])
                if {x.name for x in members} != expected or len(members) != len(
                    expected
                ):
                    raise StorageError("备份包文件清单不一致")
                self.ensure_space(folder, sum(x.size for x in members))
                for r in areas:
                    member = next(x for x in members if x.name == r["file"])
                    with archive.extractfile(member) as s, open(
                        folder / r["file"], "w+b"
                    ) as t:
                        digest = copy_stream(s, t, member.size, progress, cancel)
                    if digest != r["file_sha256"]:
                        raise StorageError("备份包中的镜像校验失败")
                manifest.update(
                    storage="local",
                    location=str(folder),
                    created=time.time(),
                    imported=True,
                )
                for k in ("storage_target", "storage_identity", "relative_location"):
                    manifest.pop(k, None)
                (folder / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2)
                )
            return {"backup": bid, "regions": len(areas)}
        except Exception:
            shutil.rmtree(folder)
            raise

    def request(self, req):
        op = req.get("method")
        args = req.get("args", {})
        if op in ("upgrade_freeze", "upgrade_unfreeze"):
            if not req.get("_root_peer"):
                raise StorageError("升级维护仅允许 root 工作进程调用")
            with self.guard:
                if op == "upgrade_freeze":
                    with self.db_lock, self.connect() as connection:
                        active = any(
                            json.loads(row[0])["state"] in ("queued", "running")
                            for row in connection.execute("SELECT data FROM jobs")
                        )
                    if self.busy or active:
                        raise StorageError("存在进行中的磁盘任务，请完成后再升级")
                    self.upgrade_frozen = True
                else:
                    self.upgrade_frozen = False
            return {"ok": True}
        if op == "stream_prepare":
            with self.guard:
                return self.streams.prepare(args)
        if op == "cache_list":
            return self.cache.inventory()
        if op == "cache_clear":
            return self.cache.execute(args)
        if op == "jobs_clear":
            return self.cache.clear_jobs(args)
        if op == "inventory":
            return {
                "disks": inventory(),
                "busy": list(self.busy),
                "local_free": shutil.disk_usage(STATE).free,
            }
        if op == "extcsd":
            return self.extcsd(args["target"])
        if op == "jobs":
            return self.jobs()
        if op == "job":
            return self.get_job(args["id"])
        if op == "submit":
            with self.guard:
                return self.submit(args)
        if op == "cancel":
            job = self.get_job(args["id"])
            if not job["cancellable"]:
                raise StorageError("此阶段不能取消")
            event = self.cancels.get(args["id"])
            if event:
                event.set()
            if job["state"] == "queued" and job.get("result", {}).get("stream"):
                job.update(
                    state="cancelled",
                    phase="已取消",
                    finished=time.time(),
                    cancellable=False,
                )
                self.save(job)
            return {"ok": True}
        if op == "files":
            return self.fs_list(args)
        if op == "text":
            return self.fs_text(args)
        if op == "hex":
            return self.hex_read(args)
        if op == "backups":
            return self.backups()
        if op == "snapshots":
            rows = []
            for p in (STATE / "snapshots").glob("*/meta.json"):
                m = json.loads(p.read_text())
                m["id"] = p.parent.name
                rows.append(m)
            return sorted(rows, key=lambda x: x["created"], reverse=True)[:100]
        if op == "backup_delete":
            folder = token_path(STATE / "backups", args["id"])
            if args.get("confirm") != args["id"]:
                raise StorageError("删除确认不正确")
            if any(j["state"] in ("queued", "running") for j in self.jobs()):
                raise StorageError("任务运行期间不能删除备份")
            m = json.loads((folder / "manifest.json").read_text())
            if m["storage"] == "usb":
                raise StorageError("USB 备份请在文件管理中删除")
            shutil.rmtree(folder)
            return {"ok": True}
        raise StorageError("请求不在允许清单内")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(180)
        try:
            line = self.rfile.readline(8 * 1024 * 1024 + 1)
            if len(line) > 8 * 1024 * 1024:
                raise StorageError("请求过大")
            req = json.loads(line)
            req["_root_peer"] = (
                struct.unpack(
                    "3i",
                    self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
                )[1]
                == 0
            )
            if req.get("method") == "stream_download":
                self.server.manager.streams.send(req["args"]["token"], self.wfile)
                return
            answer = {"ok": True, "result": self.server.manager.request(req)}
        except Exception as e:
            answer = {"ok": False, "error": str(e)}
        self.wfile.write((json.dumps(answer, ensure_ascii=False) + "\n").encode())


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    os.umask(0o027)
    m = Manager()
    SOCKET.unlink(missing_ok=True)
    server = Server(str(SOCKET), Handler)
    server.manager = m
    if not os.environ.get("EMMC_TEST_DEVICES"):
        group = pwd.getpwnam("emmc-web").pw_gid
        os.chown(SOCKET, 0, group)
        os.chown(RUNTIME, 0, group)
        os.chmod(RUNTIME, 0o750)
    os.chmod(SOCKET, 0o660)
    server.serve_forever()
