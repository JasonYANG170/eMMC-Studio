"""Unprivileged HTTP application; all device access goes through the worker."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import threading
import time
import struct
from functools import wraps
from werkzeug.utils import secure_filename
from pathlib import Path
from urllib.parse import urlsplit, quote
from flask import (
    Flask,
    request,
    jsonify,
    session,
    send_from_directory,
    send_file,
    Response,
)
from core import StorageError, number, token_path, sha_file
from system_info import system_info

STATE = Path(os.environ.get("EMMC_WEB_STATE", "/var/lib/emmc-web"))
SOCKET = os.environ.get("EMMC_WORKER_SOCKET", "/run/emmc-worker/control.sock")
STATIC = Path(
    os.environ.get("EMMC_STATIC", str(Path(__file__).resolve().parent.parent / "dist"))
)
STATE.mkdir(parents=True, exist_ok=True)
for directory in ("uploads", "downloads"):
    (STATE / directory).mkdir(exist_ok=True)
AUTH = STATE / "auth.json"
SECRET = STATE / "session.key"
if not SECRET.exists():
    SECRET.write_text(secrets.token_hex(32))
    SECRET.chmod(0o600)
app = Flask(__name__, static_folder=None)
app.secret_key = SECRET.read_text()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=3600 * 8,
)
failures = {}
auth_lock = threading.RLock()
upload_locks = {}
upload_guard = threading.RLock()
cache_guard = threading.RLock()
cache_readers = {}


def cache_serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with cache_guard:
            return fn(*args, **kwargs)

    return wrapped


def rpc(method, args=None, socket_path=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(180)
        s.connect(socket_path or SOCKET)
        s.sendall(
            (
                json.dumps({"method": method, "args": args or {}}, ensure_ascii=False)
                + "\n"
            ).encode()
        )
        with s.makefile("rb") as f:
            data = f.readline(16 * 1024 * 1024)
    response = json.loads(data)
    if not response["ok"]:
        raise StorageError(response["error"])
    return response["result"]


def auth_data():
    return json.loads(AUTH.read_text()) if AUTH.exists() else None


LEGACY_SCRYPT = {"n": 16384, "r": 8, "p": 1}
PASSWORD_SCRYPT = {"n": 32768, "r": 8, "p": 3}


def password_hash(password, salt, params=None):
    return hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        **(params or LEGACY_SCRYPT),
        dklen=32,
        maxmem=64 * 1024 * 1024
    ).hex()


def verify_password(password, data):
    return len(password) <= 128 and hmac.compare_digest(
        password_hash(password, data["salt"], data.get("scrypt")), data["hash"]
    )


def save_auth(data):
    tmp = AUTH.with_name(".auth-" + secrets.token_hex(12) + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, AUTH)
        # Persist the renamed directory entry before reporting success.
        directory_fd = os.open(AUTH.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def secure_hash_fields(password):
    salt = secrets.token_hex(16)
    return {
        "algorithm": "scrypt",
        "scrypt": dict(PASSWORD_SCRYPT),
        "salt": salt,
        "hash": password_hash(password, salt, PASSWORD_SCRYPT),
    }


def set_password(username, password):
    if not 8 <= len(password) <= 128:
        raise StorageError("密码长度应为 8–128 个字符")
    if username not in ("admin", "emmc-admin"):
        raise StorageError("管理员用户名无效")
    data = {
        "username": username,
        **secure_hash_fields(password),
        "version": secrets.token_hex(16),
        "must_change": False,
    }
    save_auth(data)
    return data


def logged_in():
    a = auth_data()
    return bool(
        a
        and session.get("user") == a["username"]
        and session.get("version") == a["version"]
    )


def body():
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        raise StorageError("请求必须为 JSON 对象")
    return b


@app.before_request
def guard():
    if request.path.startswith("/api/"):
        public = ("/api/v1/auth/status", "/api/v1/auth/login", "/api/v1/auth/setup")
        if request.path not in public and not logged_in():
            return jsonify(error="请先登录"), 401
        if (
            logged_in()
            and auth_data().get("must_change")
            and request.path
            not in (*public, "/api/v1/auth/password", "/api/v1/auth/logout")
        ):
            return jsonify(error="首次登录必须修改密码"), 403
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                return jsonify(error="请求来源不匹配"), 403
            if request.path not in public and not hmac.compare_digest(
                request.headers.get("X-CSRF-Token", ""), session.get("csrf", "!")
            ):
                return jsonify(error="请求验证失败，请重新登录"), 403


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'"
    )
    response.headers["Cache-Control"] = (
        "no-store" if request.path.startswith("/api/") else "no-cache"
    )
    return response


@app.errorhandler(StorageError)
def storage_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(413)
def too_large(e):
    return jsonify(error="单个上传块不能超过 8 MiB"), 413


@app.errorhandler(Exception)
def unexpected(e):
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    app.logger.exception("request failed")
    return jsonify(error="服务暂时不可用，请查看任务记录或服务日志"), 500


@app.get("/api/v1/auth/status")
def status():
    a = auth_data()
    return jsonify(
        configured=AUTH.exists(),
        authenticated=logged_in(),
        csrf=session.get("csrf") if logged_in() else None,
        username=a["username"] if a else "emmc-admin",
        must_change=a.get("must_change", False) if logged_in() else False,
    )


def rate_check():
    key = request.remote_addr or "local"
    now = time.time()
    attempts = [t for t in failures.get(key, []) if t > now - 300]
    failures[key] = attempts
    if len(attempts) >= 5:
        raise StorageError("尝试过于频繁，请五分钟后再试")
    if len(failures) > 1024:
        failures.clear()
    return key


@app.post("/api/v1/auth/setup")
def setup():
    with auth_lock:
        key = rate_check()
        if AUTH.exists():
            raise StorageError("管理员已经初始化")
        b = body()
        bootstrap = STATE / "setup.hash"
        supplied = hashlib.sha256(str(b.get("code", "")).encode()).hexdigest()
        if not bootstrap.exists() or not hmac.compare_digest(
            supplied, bootstrap.read_text().strip()
        ):
            failures[key].append(time.time())
            raise StorageError("一次性设置码不正确")
        a = set_password("emmc-admin", str(b.get("password", "")))
        bootstrap.unlink()
        session.clear()
        session.update(
            user=a["username"], version=a["version"], csrf=secrets.token_hex(24)
        )
        session.permanent = True
        return jsonify(
            ok=True, csrf=session["csrf"], username=a["username"], must_change=False
        )


@app.post("/api/v1/auth/login")
def login():
    with auth_lock:
        key = rate_check()
        a = auth_data()
        b = body()
        password = str(b.get("password", ""))
        if (
            len(password) > 128
            or not a
            or b.get("username") != a["username"]
            or not verify_password(password, a)
        ):
            failures[key].append(time.time())
            return jsonify(error="用户名或密码不正确"), 401
        if a.get("scrypt") != PASSWORD_SCRYPT:
            a.update(secure_hash_fields(password))
            save_auth(a)
        failures.pop(key, None)
        session.clear()
        session.update(
            user=a["username"], version=a["version"], csrf=secrets.token_hex(24)
        )
        session.permanent = True
        return jsonify(
            ok=True,
            csrf=session["csrf"],
            username=a["username"],
            must_change=a.get("must_change", False),
        )


@app.post("/api/v1/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.post("/api/v1/auth/password")
def change_password():
    with auth_lock:
        b = body()
        a = auth_data()
        if not verify_password(str(b.get("old", "")), a):
            raise StorageError("当前密码不正确")
        a = set_password(a["username"], str(b["password"]))
        session["version"] = a["version"]
        return jsonify(ok=True)


@app.get("/api/v1/system")
def system_status():
    return jsonify(system_info())


@app.get("/api/v1/devices")
def devices():
    return jsonify(rpc("inventory"))


@app.get("/api/v1/extcsd")
def extcsd():
    return jsonify(text=rpc("extcsd", request.args.to_dict()))


@app.get("/api/v1/files")
def files():
    return jsonify(rpc("files", request.args.to_dict()))


@app.get("/api/v1/text")
def text():
    return jsonify(rpc("text", request.args.to_dict()))


@app.get("/api/v1/hex")
def hex_read():
    return jsonify(rpc("hex", request.args.to_dict()))


@app.get("/api/v1/jobs")
def jobs():
    return jsonify(jobs=rpc("jobs"))


@app.post("/api/v1/jobs")
def submit():
    args = body()
    direct = args.get("op") in ("range_export", "file_export", "backup_export") or (
        args.get("op") == "backup" and args.get("storage") == "browser"
    )
    return jsonify(rpc("stream_prepare" if direct else "submit", args)), 202


@app.get("/api/v1/streams/<token>")
def stream_download(token):
    token_path(Path("/"), token)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    source = None
    try:
        connection.settimeout(180)
        connection.connect(SOCKET)
        connection.sendall(
            (
                json.dumps({"method": "stream_download", "args": {"token": token}})
                + "\n"
            ).encode()
        )
        source = connection.makefile("rb")
        metadata = json.loads(source.readline(1024 * 1024))
        if not metadata.get("ok"):
            raise StorageError(metadata.get("error", "下载失败"))
    except Exception:
        if source is not None:
            source.close()
        connection.close()
        raise

    def close_stream():
        source.close()
        connection.close()

    def exact(n):
        data = source.read(n)
        if len(data) != n:
            raise RuntimeError("下载连接提前结束")
        return data

    def chunks():
        try:
            while True:
                length = struct.unpack("!I", exact(4))[0]
                if length == 0:
                    result = json.loads(source.readline(1024 * 1024))
                    if not result.get("ok"):
                        raise RuntimeError(result.get("error", "下载中断"))
                    break
                if length > 256 * 1024:
                    raise RuntimeError("下载块超过上限")
                yield exact(length)
        finally:
            close_stream()

    response = Response(
        chunks(),
        mimetype="application/octet-stream",
        headers={"X-Accel-Buffering": "no"},
    )
    response.call_on_close(close_stream)
    response.headers.set(
        "Content-Disposition",
        "attachment",
        filename=secure_filename(metadata["name"]) or "download.bin",
    )
    response.headers["Content-Disposition"] += "; filename*=UTF-8''" + quote(
        metadata["name"], safe=""
    )
    if metadata.get("length") is not None:
        response.content_length = metadata["length"]
    return response


@app.post("/api/v1/jobs/<jid>/cancel")
def cancel(jid):
    return jsonify(rpc("cancel", {"id": jid}))


@app.post("/api/v1/jobs/clear")
def clear_jobs():
    return jsonify(rpc("jobs_clear", body()))


@app.get("/api/v1/cache")
def cache_inventory():
    data = rpc("cache_list")
    with cache_guard:
        for item in data["items"]:
            if item["kind"] == "downloads" and cache_readers.get(item["id"]):
                item.update(locked=True, reason="导出文件正在下载")
    return jsonify(data)


@app.post("/api/v1/cache/clear")
@cache_serialized
def clear_cache():
    args = body()
    items = args.get("items")
    if not isinstance(items, list):
        raise StorageError("清理项目无效")
    protected = [
        i
        for i in items
        if isinstance(i, dict)
        and i.get("kind") == "downloads"
        and cache_readers.get(i.get("id"))
    ]
    result = rpc("cache_clear", {"items": [i for i in items if i not in protected]})
    result["skipped"].extend(
        dict(kind=i["kind"], id=i["id"], reason="导出文件正在下载") for i in protected
    )
    return jsonify(result)


@app.get("/api/v1/events")
def events():
    def stream():
        # Reconnectable snapshots; an SSE connection consumes one Waitress thread.
        for _ in range(60):
            try:
                payload = {"jobs": rpc("jobs")}
            except Exception:
                payload = {"error": "任务服务暂时不可用"}
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            time.sleep(2)

    return Response(
        stream(), mimetype="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@app.get("/api/v1/backups")
def backups():
    return jsonify(backups=rpc("backups"), snapshots=rpc("snapshots"))


@app.post("/api/v1/backups/<bid>/delete")
def delete_backup(bid):
    return jsonify(rpc("backup_delete", dict(body(), id=bid)))


@app.post("/api/v1/uploads")
@cache_serialized
def create_upload():
    b = body()
    size = number(b["size"], 1)
    name = Path(str(b["name"])).name[:200]
    if shutil.disk_usage(STATE).free < size + 64 * 1024 * 1024:
        raise StorageError("暂存空间不足")
    token = secrets.token_hex(16)
    p = token_path(STATE / "uploads", token)
    p.touch(mode=0o640)
    p.with_suffix(".json").write_text(
        json.dumps({"name": name, "size": size, "received": 0, "complete": False})
    )
    return jsonify(id=token, received=0)


@app.get("/api/v1/uploads/<token>")
def upload_status(token):
    p = token_path(STATE / "uploads", token)
    return jsonify(json.loads(p.with_suffix(".json").read_text()))


@app.put("/api/v1/uploads/<token>")
@cache_serialized
def upload_chunk(token):
    p = token_path(STATE / "uploads", token)
    with upload_guard:
        lock = upload_locks.setdefault(token, threading.Lock())
    with lock:
        meta = p.with_suffix(".json")
        m = json.loads(meta.read_text())
        offset = number(request.args.get("offset", 0))
        if m["complete"]:
            raise StorageError("文件已上传完成")
        if p.stat().st_size != offset:
            raise StorageError("上传偏移不一致，请查询进度后重试")
        chunk = request.get_data()
        if not chunk or offset + len(chunk) > m["size"]:
            raise StorageError("上传块长度无效")
        with open(p, "ab") as f:
            f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        m["received"] = offset + len(chunk)
        m["complete"] = m["received"] == m["size"]
        if m["complete"]:
            m["sha256"] = sha_file(p)
        tmp = meta.with_suffix(".tmp")
        tmp.write_text(json.dumps(m))
        os.replace(tmp, meta)
        return jsonify(m)


@app.get("/api/v1/downloads/<token>")
@cache_serialized
def download(token):
    p = token_path(STATE / "downloads", token)
    m = json.loads(p.with_suffix(".json").read_text())
    response = send_file(
        p, as_attachment=True, download_name=m["name"], conditional=True
    )
    cache_readers[token] = cache_readers.get(token, 0) + 1

    def finished():
        with cache_guard:
            remaining = cache_readers.get(token, 1) - 1
            if remaining:
                cache_readers[token] = remaining
            else:
                cache_readers.pop(token, None)

    response.direct_passthrough = False
    response.call_on_close(finished)
    return response


@app.get("/api/v1/upgrade")
def upgrade_status():
    return jsonify(rpc("status", socket_path="/run/emmc-updater/control.sock"))


@app.post("/api/v1/upgrade/check")
def upgrade_check():
    return jsonify(rpc("check", socket_path="/run/emmc-updater/control.sock"))


@app.post("/api/v1/upgrade/install")
@cache_serialized
def upgrade_install():
    return jsonify(rpc("install", body(), socket_path="/run/emmc-updater/control.sock"))


@app.get("/api/v1/settings")
def settings():
    entries = []
    for kind in ("uploads", "downloads"):
        for p in (STATE / kind).glob("*.json"):
            m = json.loads(p.read_text())
            m.update(id=p.stem, kind=kind)
            entries.append(m)
    return jsonify(
        username=auth_data()["username"],
        free=shutil.disk_usage(STATE).free,
        temporary=entries,
        version=(Path(__file__).resolve().parents[1] / "VERSION").read_text().strip(),
    )


@app.post("/api/v1/temporary/<kind>/<token>/delete")
@cache_serialized
def delete_temporary(kind, token):
    if kind not in ("uploads", "downloads"):
        raise StorageError("类型无效")
    token_path(STATE / kind, token)
    if kind == "downloads" and cache_readers.get(token):
        raise StorageError("导出文件正在下载")
    item = next(
        (
            i
            for i in rpc("cache_list")["items"]
            if i["kind"] == kind and i["id"] == token
        ),
        None,
    )
    if not item:
        raise StorageError("暂存文件不存在")
    if item["locked"]:
        raise StorageError(item["reason"])
    return jsonify(rpc("cache_clear", {"items": [item]}))


@app.get("/")
@app.get("/<path:path>")
def static(path="index.html"):
    if path.startswith("api/"):
        return jsonify(error="接口不存在"), 404
    if (STATIC / path).is_file():
        return send_from_directory(STATIC, path)
    return send_from_directory(STATIC, "index.html")


if __name__ == "__main__":
    from waitress import serve

    serve(
        app,
        host=os.environ.get("EMMC_BIND", "0.0.0.0"),
        port=int(os.environ.get("EMMC_PORT", "80")),
        threads=16,
        max_request_body_size=8 * 1024 * 1024,
        channel_timeout=180,
        outbuf_high_watermark=1024 * 1024,
        outbuf_overflow=4 * 1024 * 1024,
    )
