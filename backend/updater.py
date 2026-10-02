"""Independent root update service; only signed application releases are executable."""

import json
import os
import pwd
import re
import shutil
import socket
import socketserver
import stat
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from update_package import MAX_PACKAGE, unpack, version

STATE = Path(os.environ.get("EMMC_UPDATE_STATE", "/var/lib/emmc-updater"))
RUNTIME = Path(os.environ.get("EMMC_UPDATE_RUNTIME", "/run/emmc-updater"))
SOCKET = RUNTIME / "control.sock"
APP = Path(os.environ.get("EMMC_APP", "/opt/emmc-studio"))
UPLOADS = Path(os.environ.get("EMMC_WEB_STATE", "/var/lib/emmc-web")) / "uploads"
REPOSITORY = "JasonYANG170/eMMC-Studio"


def worker(method):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(30)
        connection.connect(
            os.environ.get("EMMC_WORKER_SOCKET", "/run/emmc-worker/control.sock")
        )
        connection.sendall((json.dumps({"method": method}) + "\n").encode())
        answer = json.loads(connection.makefile("rb").readline(1024 * 1024))
    if not answer["ok"]:
        raise ValueError(answer["error"])
    return answer["result"]


def current_version():
    return (APP / "VERSION").read_text().strip()


def latest():
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
        headers={
            "User-Agent": "eMMC-Studio-Updater",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("版本接口响应过大")
    release = json.loads(data)
    tag = release["tag_name"]
    version(tag.removeprefix("v"))
    name = "eMMC-Studio-update.tar.gz"
    expected = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
    asset = next(
        (
            x
            for x in release["assets"]
            if x["name"] == name and x["browser_download_url"] == expected
        ),
        None,
    )
    if not asset or not 0 < asset["size"] <= MAX_PACKAGE:
        raise ValueError("最新 Release 尚未提供兼容的升级包")
    return {
        "version": tag.removeprefix("v"),
        "current": current_version(),
        "available": version(tag.removeprefix("v")) > version(current_version()),
        "url": expected,
        "size": asset["size"],
        "notes": release.get("body", "")[:12000],
        "release_url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
    }


class Updates:
    def __init__(self):
        STATE.mkdir(parents=True, exist_ok=True)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = False
        self.path = STATE / "status.json"
        self.data = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"state": "idle", "phase": "等待升级"}
        )
        if self.data["state"] == "running":
            self.save(
                state="interrupted",
                phase="升级服务曾中断，请检查当前版本后重试",
                finished=time.time(),
            )
        (RUNTIME / "maintenance").unlink(missing_ok=True)
        try:
            worker("upgrade_unfreeze")
        except (OSError, ValueError):
            pass

    def save(self, **values):
        with self.lock:
            self.data.update(values)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, ensure_ascii=False))
            temporary.chmod(0o600)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)

    def status(self):
        with self.lock:
            return {
                "current": current_version(),
                "repository": REPOSITORY,
                "task": dict(self.data),
            }

    def submit(self, args):
        if args.get("source") not in ("online", "local") or not isinstance(
            args.get("reinstall", False), bool
        ):
            raise ValueError("升级参数无效")
        token = args.get("upload", "")
        if args["source"] == "local" and not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("本地升级包上传标识无效")
        with self.lock:
            if self.active or self.data["state"] == "running":
                raise ValueError("已有升级任务正在执行")
            self.data = {
                "id": uuid.uuid4().hex,
                "source": args["source"],
                "state": "running",
                "phase": "准备升级包",
                "progress": 0,
                "created": time.time(),
                "from": current_version(),
            }
            self.save()
            self.active = True
            threading.Thread(
                target=self.install, args=(dict(args),), daemon=False
            ).start()
            return self.status()

    def install(self, args):
        folder = STATE / self.data["id"]
        marker = RUNTIME / "maintenance"
        frozen = False
        try:
            folder.mkdir(mode=0o700)
            if (
                shutil.disk_usage(STATE).free < 768 * 1024 * 1024
                or shutil.disk_usage("/opt").free < 768 * 1024 * 1024
            ):
                raise ValueError("升级需要暂存区和 /opt 各至少 768 MiB 可用空间")
            package = folder / "update.tar.gz"
            if args["source"] == "online":
                release = latest()
                self.save(to=release["version"], phase="下载官方升级包")
                request = urllib.request.Request(
                    release["url"], headers={"User-Agent": "eMMC-Studio-Updater"}
                )
                with urllib.request.urlopen(
                    request, timeout=30
                ) as source, package.open("wb") as output:
                    received, deadline = 0, time.monotonic() + 300
                    while chunk := source.read(256 * 1024):
                        received += len(chunk)
                        if received > release["size"] or time.monotonic() > deadline:
                            raise ValueError("下载大小或时间超出限制")
                        output.write(chunk)
                        self.save(progress=int(received * 40 / release["size"]))
                    if received != release["size"]:
                        raise ValueError("升级包下载不完整")
            else:
                token = args["upload"]
                metadata = json.loads((UPLOADS / (token + ".json")).read_text())
                descriptor = os.open(
                    UPLOADS / token, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                )
                with os.fdopen(descriptor, "rb") as source, package.open(
                    "wb"
                ) as output:
                    info = os.fstat(source.fileno())
                    if (
                        not metadata.get("complete")
                        or not stat.S_ISREG(info.st_mode)
                        or not 0 < info.st_size <= MAX_PACKAGE
                        or info.st_size != metadata.get("size")
                    ):
                        raise ValueError("本地升级包未上传完成或大小无效")
                    shutil.copyfileobj(source, output, 256 * 1024)
            self.save(phase="验证官方签名与程序清单", progress=45)
            meta, app = unpack(
                package,
                folder / "verified",
                current_version(),
                args.get("reinstall", False),
            )
            if args["source"] == "online" and meta["version"] != release["version"]:
                raise ValueError("签名版本与 Release 版本不一致")
            self.save(
                to=meta["version"], phase="检查磁盘任务并暂停任务提交", progress=60
            )
            marker.touch(mode=0o640)
            worker("upgrade_freeze")
            frozen = True
            self.save(phase="安装程序、重启服务并检查健康状态", progress=70)
            # This daemon is independent of web/worker. The installer never restarts it.
            with (STATE / "install.log").open("wb") as log:
                process = subprocess.Popen(
                    ["/bin/sh", str(app / "deploy/install.sh"), "--skip-apt"],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=app,
                )
                result = process.wait()
            if result:
                raise ValueError(
                    "安装或健康检查失败，安装器已尝试恢复旧版；详见 /var/lib/emmc-updater/install.log"
                )
            self.save(
                state="completed", phase="升级完成", progress=100, finished=time.time()
            )
        except Exception as error:
            self.save(
                state="failed", phase="升级失败", error=str(error), finished=time.time()
            )
        finally:
            marker.unlink(missing_ok=True)
            if frozen:
                try:
                    worker("upgrade_unfreeze")
                except Exception:
                    pass
            shutil.rmtree(folder, ignore_errors=True)
            with self.lock:
                self.active = False

    def request(self, request):
        method = request.get("method")
        if method == "status":
            return self.status()
        if method == "check":
            return latest()
        if method == "install":
            return self.submit(request.get("args", {}))
        raise ValueError("升级操作不在允许清单内")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(35)
        try:
            raw = self.rfile.readline(8193)
            if len(raw) > 8192:
                raise ValueError("请求过大")
            result = {
                "ok": True,
                "result": self.server.updates.request(json.loads(raw)),
            }
        except Exception as error:
            result = {"ok": False, "error": str(error)}
        self.wfile.write((json.dumps(result, ensure_ascii=False) + "\n").encode())


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    os.umask(0o027)
    updates = Updates()
    SOCKET.unlink(missing_ok=True)
    server = Server(str(SOCKET), Handler)
    server.updates = updates
    os.chown(SOCKET, 0, pwd.getpwnam("emmc-web").pw_gid)
    os.chmod(SOCKET, 0o660)
    server.serve_forever()
