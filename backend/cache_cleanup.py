"""Fixed-path cleanup of history and expendable files; never accepts user paths."""

import json, re, shutil, time
from pathlib import Path
from core import StorageError, token_path

KINDS = ("jobs", "snapshots", "downloads", "uploads")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")


class CacheCleanup:
    def __init__(self, manager, state, webstate):
        self.m = manager
        self.state = Path(state)
        self.webstate = Path(webstate)

    def all_jobs(self):
        with self.m.db_lock, self.m.connect() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT data FROM jobs")]

    def inventory(self):
        jobs = self.all_jobs()
        busy = bool(self.m.busy) or any(j["state"] not in TERMINAL for j in jobs)
        rows = []
        with self.m.streams.lock:
            active = {t["job"] for t in self.m.streams.tickets.values() if t["active"]}
        for j in jobs:
            locked = j["state"] not in TERMINAL or j["id"] in active
            rows.append(
                dict(
                    kind="jobs",
                    id=j["id"],
                    name=j.get("title", j["op"]),
                    created=j["created"],
                    target=j.get("target", ""),
                    size=0,
                    state=j["state"],
                    locked=locked,
                    reason="任务尚未结束或下载正在传输" if locked else "",
                    stamp=str(j.get("finished", j["created"])),
                )
            )
        for kind in ("snapshots", "downloads", "uploads"):
            root = self.state / kind if kind == "snapshots" else self.webstate / kind
            for entry in root.iterdir():
                if not re.fullmatch("[a-f0-9]{32}", entry.name) or entry.is_symlink():
                    continue
                try:
                    meta = (
                        entry / "meta.json"
                        if kind == "snapshots"
                        else entry.with_suffix(".json")
                    )
                    if meta.is_symlink():
                        continue
                    try:
                        info = json.loads(meta.read_text()) if meta.exists() else {}
                    except ValueError:
                        info = {}
                    if not isinstance(info, dict):
                        info = {}
                    stat = entry.stat()
                    files = list(entry.rglob("*")) if entry.is_dir() else [entry, meta]
                    if any(p.is_symlink() for p in files):
                        continue
                    size = sum(p.stat().st_size for p in files if p.is_file())
                    # Recent unfinished uploads may still be receiving their next chunk.
                    uploading = (
                        kind == "uploads"
                        and not info.get("complete")
                        and time.time() - stat.st_mtime < 300
                    )
                    rows.append(
                        dict(
                            kind=kind,
                            id=entry.name,
                            name=info.get("name")
                            or (
                                "原始字节快照"
                                if info.get("kind") == "hex"
                                else (
                                    "分区表快照"
                                    if kind == "snapshots"
                                    else "无元数据暂存文件"
                                )
                            ),
                            created=info.get("created", stat.st_mtime),
                            target=info.get("target", info.get("disk", "")),
                            size=size,
                            state="",
                            locked=busy or uploading,
                            reason=(
                                "存储任务或下载尚未结束"
                                if busy
                                else "近 5 分钟有未完成上传" if uploading else ""
                            ),
                            stamp=f"{meta.stat().st_mtime_ns if meta.exists() else 0}:{stat.st_mtime_ns}:{size}",
                        )
                    )
                except (OSError, ValueError):
                    continue
        return {
            "items": sorted(rows, key=lambda r: r["created"], reverse=True),
            "free": shutil.disk_usage(self.webstate).free,
        }

    def clear_jobs(self, args):
        with self.m.guard, self.m.streams.lock:
            current = {
                j["id"]: j for j in self.inventory()["items"] if j["kind"] == "jobs"
            }
            ids = list(current) if args.get("all") else args.get("ids", [])
            if not isinstance(ids, list) or any(
                not isinstance(x, str) or not re.fullmatch("[a-f0-9]{32}", x)
                for x in ids
            ):
                raise StorageError("任务标识无效")
            return self.execute(
                {
                    "items": [
                        {"kind": "jobs", "id": i, "stamp": current[i]["stamp"]}
                        for i in ids
                        if i in current
                    ]
                }
            )

    def execute(self, args):
        items = args.get("items")
        if not isinstance(items, list) or len(items) > 10000:
            raise StorageError("清理项目无效或过多")
        if any(
            not isinstance(x, dict)
            or x.get("kind") not in KINDS
            or not isinstance(x.get("id"), str)
            or not re.fullmatch("[a-f0-9]{32}", x["id"])
            for x in items
        ):
            raise StorageError("清理类型或标识无效")
        with self.m.guard, self.m.streams.lock:
            current = {(r["kind"], r["id"]): r for r in self.inventory()["items"]}
            removed = []
            skipped = []
            freed = 0
            for item in {(i["kind"], i["id"]): i for i in items}.values():
                key = (item["kind"], item["id"])
                row = current.get(key)
                reason = (
                    "项目已不存在"
                    if not row
                    else (
                        row["reason"]
                        if row["locked"]
                        else (
                            "项目已变化，请刷新后重选"
                            if str(item.get("stamp")) != row["stamp"]
                            else ""
                        )
                    )
                )
                if reason:
                    skipped.append(dict(kind=key[0], id=key[1], reason=reason))
                    continue
                if key[0] == "jobs":
                    with self.m.db_lock, self.m.connect() as c:
                        c.execute("DELETE FROM jobs WHERE id=?", (key[1],))
                    for token, ticket in list(self.m.streams.tickets.items()):
                        if ticket["job"] == key[1]:
                            del self.m.streams.tickets[token]
                    self.m.cancels.pop(key[1], None)
                else:
                    root = (
                        self.state / key[0]
                        if key[0] == "snapshots"
                        else self.webstate / key[0]
                    )
                    path = token_path(root, key[1])
                    if key[0] == "snapshots":
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                        path.with_suffix(".json").unlink(missing_ok=True)
                    freed += row["size"]
                removed.append(dict(kind=key[0], id=key[1]))
            if any(r["kind"] == "jobs" for r in removed):
                with self.m.db_lock, self.m.connect() as c:
                    c.execute("VACUUM")
            return dict(
                ok=True,
                removed=removed,
                skipped=skipped,
                freed=freed,
                free=shutil.disk_usage(self.webstate).free,
            )
