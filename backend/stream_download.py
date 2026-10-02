"""Bounded socket streaming. No image/archive files are created by this worker."""

import hashlib, io, json, os, struct, tarfile, threading, time, uuid
from pathlib import Path
from core import (
    StorageError,
    resolve_region,
    bounds,
    pinned_open,
    safe_path,
    token_path,
)

CHUNK = 256 * 1024


class StreamDownloads:
    def __init__(self, manager):
        self.manager = manager
        self.tickets = {}
        self.lock = threading.RLock()

    def prepare(self, args):
        op = args.get("op")
        if op not in ("range_export", "file_export", "backup_export", "backup"):
            raise StorageError("此操作不支持流式下载")
        if op == "backup" and args.get("storage") != "browser":
            raise StorageError("流式备份仅用于下载到电脑")
        if op != "backup_export":
            d, r = resolve_region(args["target"], args.get("identity"))
            if args.get("identity") != d["identity"]:
                raise StorageError("必须提供准确的设备身份")
            if op == "range_export":
                bounds(args.get("offset", 0), args["length"], r["size"], r["size"])
            if (
                op == "backup"
                and args.get("full")
                and (d["kind"] != "emmc" or r["region"] != "user")
            ):
                raise StorageError("完整备份需选择 eMMC 用户区")
        else:
            token_path(self.manager.db.parent / "backups", args["backup"]).joinpath(
                "manifest.json"
            ).read_text()
        with self.lock:
            for token, ticket in list(self.tickets.items()):
                if ticket["expires"] < time.time() and not ticket["active"]:
                    job = self.manager.get_job(ticket["job"])
                    if job["state"] == "queued":
                        job.update(
                            state="cancelled",
                            phase="下载链接已过期",
                            finished=time.time(),
                            cancellable=False,
                        )
                        self.manager.save(job)
                    self.manager.cancels.pop(ticket["job"], None)
                    del self.tickets[token]
            if len(self.tickets) >= 64:
                raise StorageError("下载链接过多，请稍后重试")
            token = uuid.uuid4().hex
            jid = uuid.uuid4().hex
            job = {
                "id": jid,
                "op": op,
                "title": args.get("title", op),
                "state": "queued",
                "created": time.time(),
                "progress": 0,
                "bytes": 0,
                "total": 0,
                "speed": 0,
                "phase": "等待浏览器连接",
                "logs": [],
                "target": args.get("target"),
                "cancellable": True,
                "result": {"stream": token},
            }
            self.manager.save(job)
            self.manager.cancels[jid] = threading.Event()
            self.tickets[token] = {
                "job": jid,
                "args": dict(args),
                "expires": time.time() + 3600,
                "active": False,
            }
            return job

    def send(self, token, pipe):
        token_path(Path("/"), token)  # validate opaque identifier
        with self.lock:
            ticket = self.tickets.get(token)
            if not ticket or ticket["expires"] < time.time():
                raise StorageError("下载链接已过期，请重新发起导出")
            if ticket["active"]:
                raise StorageError("该下载正在传输")
            event = self.manager.cancels.get(ticket["job"])
            if event and event.is_set():
                raise StorageError("下载任务已取消")
            ticket["active"] = True
        m = self.manager
        args = ticket["args"]
        op = args["op"]
        job = m.get_job(ticket["job"])
        keys = []
        fds = []
        started = False
        header_sent = False
        last = [0]
        done = [0]
        total = [0]
        start = time.monotonic()
        event = event or threading.Event()
        m.cancels[job["id"]] = event

        def progress(n, phase):
            done[0] += n
            job.update(
                bytes=done[0],
                total=total[0],
                progress=round(done[0] / max(total[0], 1) * 100, 2),
                phase=phase,
                speed=int(done[0] / max(time.monotonic() - start, 0.001)),
            )
            if time.monotonic() - last[0] > 0.4 or done[0] == total[0]:
                last[0] = time.monotonic()
                m.save(job)

        class Writer:
            def write(self, data):
                if event.is_set():
                    raise StorageError("下载已取消")
                for pos in range(0, len(data), CHUNK):
                    block = data[pos : pos + CHUNK]
                    pipe.write(struct.pack("!I", len(block)))
                    pipe.write(block)
                pipe.flush()
                return len(data)

            def flush(self):
                pipe.flush()

        class Reader:
            def __init__(self, source, length, phase):
                self.source = source
                self.left = length
                self.digest = hashlib.sha256()
                self.phase = phase

            def read(self, n=-1):
                if event.is_set():
                    raise StorageError("下载已取消")
                n = min(CHUNK, self.left, n if n >= 0 else CHUNK)
                if not n:
                    return b""
                data = self.source.read(n)
                if len(data) != n:
                    raise StorageError("源设备提前结束，下载不完整")
                self.left -= n
                self.digest.update(data)
                progress(n, self.phase)
                return data

        def open_region(r):
            source = os.fdopen(pinned_open(r["path"], os.O_RDONLY), "rb", buffering=0)
            fds.append(source)
            return source

        def header(name, length=None):
            nonlocal header_sent
            pipe.write(
                (
                    json.dumps({"ok": True, "name": name, "length": length}) + "\n"
                ).encode()
            )
            pipe.flush()
            header_sent = True

        def add_file(archive, name, reader, length):
            entry = tarfile.TarInfo(name)
            entry.size = length
            entry.mode = 0o600
            entry.mtime = int(time.time())
            archive.addfile(entry, reader)

        try:
            if op == "backup_export":
                manifest = json.loads(
                    token_path(m.db.parent / "backups", args["backup"])
                    .joinpath("manifest.json")
                    .read_text()
                )
                if manifest.get("storage") == "usb":
                    d, r = resolve_region(
                        manifest["storage_target"], manifest["storage_identity"]
                    )
                    keys = [d["identity"]]
            else:
                d, r = resolve_region(args["target"], args["identity"])
                keys = [d["identity"]]
            m.acquire(keys)
            started = True
            job.update(
                state="running",
                started=time.time(),
                finished=None,
                error=None,
                phase="流式下载",
                progress=0,
                bytes=0,
            )
            m.save(job)
            writer = Writer()
            if op in ("range_export", "file_export"):
                if op == "range_export":
                    off, length = bounds(
                        args.get("offset", 0), args["length"], r["size"], r["size"]
                    )
                    source = open_region(r)
                    source.seek(off)
                    name = f'{r["name"]}-{off}.bin'
                else:
                    root = m.mount(r, False)
                    path = safe_path(root, args["path"])
                    if not path.is_file():
                        raise StorageError("只能下载普通文件")
                    source = open(path, "rb")
                    fds.append(source)
                    length = os.fstat(source.fileno()).st_size
                    name = path.name
                total[0] = length
                reader = Reader(source, length, "直接传输到浏览器")
                header(name, length)
                while reader.left:
                    writer.write(reader.read(CHUNK))
                result = {"sha256": reader.digest.hexdigest(), "stream": token}
            elif op == "backup":
                regions = (
                    [r]
                    if not args.get("full")
                    else [
                        x
                        for x in d["regions"]
                        if x["region"] in ("user", "boot0", "boot1")
                    ]
                )
                sources = [(area, open_region(area)) for area in regions]
                manifest = {
                    "version": 1,
                    "created": time.time(),
                    "identity": d["identity"],
                    "model": d["model"],
                    "disk_size": d["size"],
                    "table": d["table"],
                    "full": bool(args.get("full")),
                    "storage": "browser",
                    "regions": [],
                }
                if d["kind"] == "emmc":
                    manifest["extcsd"] = m.extcsd(d["path"], locked=True)
                total[0] = sum(area["size"] for area in regions)
                compressed = bool(args.get("gzip"))
                header(
                    "emmc-backup-"
                    + job["id"][:8]
                    + (".tar.gz" if compressed else ".tar")
                )
                with tarfile.open(
                    fileobj=writer,
                    mode="w|gz" if compressed else "w|",
                    **({"compresslevel": 1} if compressed else {}),
                ) as archive:
                    for area, source in sources:
                        reader = Reader(
                            source, area["size"], "流式备份 " + area["region"]
                        )
                        filename = area["region"] + ".img"
                        add_file(archive, filename, reader, area["size"])
                        digest = reader.digest.hexdigest()
                        manifest["regions"].append(
                            {
                                "region": area["region"],
                                "name": area["name"],
                                "size": area["size"],
                                "file": filename,
                                "compressed": False,
                                "sha256": digest,
                                "file_sha256": digest,
                            }
                        )
                    data = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
                    add_file(archive, "manifest.json", io.BytesIO(data), len(data))
                result = {"stream": token, "manifest": manifest}
            else:
                folder = m.backup_files(manifest)
                files = [folder / area["file"] for area in manifest["regions"]]
                total[0] = sum(path.stat().st_size for path in files)
                header("emmc-backup-" + args["backup"][:8] + ".tar")
                with tarfile.open(fileobj=writer, mode="w|") as archive:
                    for area, path in zip(manifest["regions"], files):
                        source = open(path, "rb")
                        fds.append(source)
                        length = os.fstat(source.fileno()).st_size
                        reader = Reader(source, length, "传输备份包")
                        add_file(archive, path.name, reader, length)
                        if reader.digest.hexdigest() != area["file_sha256"]:
                            raise StorageError("备份镜像校验不一致")
                    data = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
                    add_file(archive, "manifest.json", io.BytesIO(data), len(data))
                result = {"stream": token, "backup": args["backup"]}
            pipe.write(struct.pack("!I", 0))
            pipe.write((json.dumps({"ok": True}) + "\n").encode())
            pipe.flush()
            job.update(
                state="completed",
                phase="已传输到浏览器",
                progress=100,
                result=result,
                cancellable=False,
                finished=time.time(),
            )
            m.save(job)
        except Exception as error:
            job.update(
                state=(
                    "cancelled"
                    if event.is_set()
                    or isinstance(error, (BrokenPipeError, ConnectionResetError))
                    else "failed"
                ),
                phase="传输中断",
                error=str(error),
                cancellable=False,
                finished=time.time(),
            )
            m.save(job)
            if header_sent:
                try:
                    pipe.write(struct.pack("!I", 0))
                    pipe.write(
                        (json.dumps({"ok": False, "error": str(error)}) + "\n").encode()
                    )
                    pipe.flush()
                except OSError:
                    pass
            else:
                raise
        finally:
            for source in fds:
                source.close()
            if started:
                m.release(keys)
            with self.lock:
                ticket["active"] = False
            m.cancels.pop(job["id"], None)
