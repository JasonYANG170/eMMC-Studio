"""Initialize with a one-time setup code; preserve any existing account."""

import hashlib, os, pwd, secrets
from pathlib import Path

state = Path("/var/lib/emmc-web")
if not (state / "auth.json").exists():
    code = secrets.token_urlsafe(24)
    p = state / "setup.hash"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(hashlib.sha256(code.encode()).hexdigest())
    p.chmod(0o600)
    u = pwd.getpwnam("emmc-web")
    os.chown(p, u.pw_uid, u.pw_gid)
    print("一次性管理员设置码：" + code)
    print("请在网页创建 emmc-admin 密码（8–128 个字符）。")
else:
    print("保留现有管理员账号和密码。")
