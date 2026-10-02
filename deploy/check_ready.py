"""Read-only upgrade checks; do not interrupt live storage jobs."""

import json
import socket
import sqlite3
import subprocess
from pathlib import Path
from contextlib import closing


def active(service):
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", service], check=False
        ).returncode
        == 0
    )


def check_jobs(database, worker_active):
    if not worker_active or not database.exists():
        return
    with closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as connection:
        jobs = [
            json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")
        ]
    if any(job.get("state") in {"queued", "running"} for job in jobs):
        raise RuntimeError("有等待或运行中的存储任务，请在任务完成后重试升级。")


def main():
    check_jobs(Path("/var/lib/emmc-worker/jobs.sqlite"), active("emmc-worker"))
    if not active("emmc-web"):
        with socket.socket() as probe:
            try:
                probe.bind(("0.0.0.0", 80))
            except OSError as error:
                raise RuntimeError(
                    "80 端口已被其他服务占用，请先调整该服务。"
                ) from error
    print("部署检查通过：无进行中的存储任务，80 端口可用或由现有服务使用。")


if __name__ == "__main__":
    main()
