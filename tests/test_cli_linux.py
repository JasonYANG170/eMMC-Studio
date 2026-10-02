"""Real CLI subprocess + worker socket integration, only owned loop images."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    assert os.geteuid() == 0, "root required for disposable loop tests"
    temp = Path(tempfile.mkdtemp(prefix="emmc-cli-test-"))
    loops, manager, server = [], None, None
    try:
        for name in ("source", "target"):
            image = temp / (name + ".img")
            with image.open("wb") as stream:
                stream.truncate(192 * 1024**2)
            loop = subprocess.check_output(
                ["losetup", "--find", "--show", "--partscan", str(image)], text=True
            ).strip()
            backing = subprocess.check_output(
                ["losetup", "-n", "-O", "BACK-FILE", loop], text=True
            ).strip()
            assert Path(backing).resolve() == image.resolve()
            loops.append(loop)
        os.environ.update(
            EMMC_TEST_DEVICES=",".join(loops),
            EMMC_WORKER_STATE=str(temp / "state"),
            EMMC_WEB_STATE=str(temp / "web"),
            EMMC_RUNTIME=str(temp / "run"),
        )
        import worker

        manager = worker.Manager()
        endpoint = str(temp / "control.sock")
        server = worker.Server(endpoint, worker.Handler)
        server.manager = manager
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def command(*args, ok=True, lang="zh-CN"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend/cli.py"),
                    "--lang",
                    lang,
                    "--socket",
                    endpoint,
                    "--json",
                    *args,
                ],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if ok:
                assert result.returncode == 0, result.stderr
                return json.loads(result.stdout)
            assert result.returncode == 1, (result.stdout, result.stderr)
            return result.stderr

        source, target = loops
        from cli import Client

        root_client = Client(endpoint)
        try:
            manager.request({"method": "upgrade_freeze", "_root_peer": False})
            raise AssertionError("unprivileged maintenance accepted")
        except worker.StorageError:
            pass
        manager.busy.add("test-busy")
        try:
            root_client.rpc("upgrade_freeze")
            raise AssertionError("busy maintenance accepted")
        except Exception as error:
            assert "任务" in str(error)
        manager.busy.clear()
        root_client.rpc("upgrade_freeze")
        assert "升级" in command("partition", "table", source, "gpt", ok=False)
        assert "upgrade in progress" in command(
            "partition", "table", source, "gpt", ok=False, lang="en"
        )
        assert not manager.jobs()
        root_client.rpc("upgrade_unfreeze")
        info = command("devices")
        assert {source, target} <= {d["path"] for d in info["disks"]}
        dry = command("--dry-run", "partition", "table", source, "gpt")
        assert not dry["submitted"] and not manager.jobs()
        command("partition", "table", source, "gpt")
        command("partition", "create", source, "--start", "1MiB", "--size", "100MiB")
        part = next(
            r["path"]
            for r in command("info", source)["disk"]["regions"]
            if r["region"] == "partition"
        )
        command("partition", "format", part, "ext4", "--label", "CLITEST")
        command("partition", "resize", part, "--size", "120MiB")
        command("files", "mkdir", part, "hello")
        text = temp / "message.txt"
        text.write_text("你好 CLI\n", encoding="utf-8")
        command("files", "text-put", part, "hello/message.txt", "--input", str(text))
        assert (
            command("files", "cat", part, "hello/message.txt")["text"] == "你好 CLI\n"
        )
        output = temp / "download.txt"
        command("files", "get", part, "hello/message.txt", "--output", str(output))
        assert output.read_bytes() == text.read_bytes()
        command("files", "mv", part, "hello/message.txt", "hello/renamed.txt")
        assert "路径越界" in command("files", "ls", part, "../", ok=False)
        command("files", "rm", part, "hello/renamed.txt")
        changed = command(
            "hex", "write", target, "--offset", "32MiB", "--data", "01 02 ff"
        )
        snapshot = changed["result"]["snapshot"]
        assert (
            command("hex", "read", target, "--offset", "32MiB", "--length", "3B")["hex"]
            == "0102ff"
        )
        command("hex", "undo", target, snapshot)
        assert (
            command("hex", "read", target, "--offset", "32MiB", "--length", "3B")["hex"]
            == "000000"
        )
        raw = temp / "range.bin"
        exported = command(
            "hex",
            "export",
            target,
            "--offset",
            "32MiB",
            "--length",
            "4MiB",
            "--output",
            str(raw),
        )
        assert raw.stat().st_size == 4 * 1024**2
        assert (
            exported["output"]["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
        )
        assert "同" in command("clone", source, source, ok=False)
        command("clone", source, target)
        archive = temp / "backup.tar.gz"
        command("backup", "create", source, "--gzip", "--output", str(archive))
        imported = command("backup", "import", str(archive))
        bid = imported["result"]["backup"]
        command("backup", "restore", target, bid)
        assert (
            hashlib.sha256((temp / "source.img").read_bytes()).digest()
            == hashlib.sha256((temp / "target.img").read_bytes()).digest()
        )
        command("backup", "delete", bid)
        command("cache", "clear", "uploads", "--all")
        command("jobs", "clear", "--all")
        assert not command("jobs", "list")
        print(
            "PASS: real CLI/socket GPT, ext4 resize, files, bounds, hex/undo/export, clone, gzip backup/import/restore and cleanup; only temporary loop devices used."
        )
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if manager:
            for mount in list(manager.mounts.values()):
                subprocess.run(["umount", str(mount["root"])], check=True)
        for loop in reversed(loops):
            subprocess.run(["losetup", "-d", loop], check=True)
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
