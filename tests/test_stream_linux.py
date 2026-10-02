"""Socket + authenticated HTTP streaming against owned temporary loop devices only."""

import gzip, hashlib, io, json, os, shutil, socket, sys, tarfile, tempfile, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import run, inventory


def main():
    temp = Path(tempfile.mkdtemp(prefix="emmc-stream-test-"))
    loop = None
    server = None
    manager = None
    try:
        image = temp / "source.img"
        with open(image, "wb") as f:
            f.truncate(128 * 1024 * 1024)
            f.write(os.urandom(1024 * 1024))
        loop = run(["losetup", "--find", "--show", "--partscan", str(image)]).strip()
        os.environ.update(
            EMMC_TEST_DEVICES=loop,
            EMMC_WORKER_STATE=str(temp / "state"),
            EMMC_WEB_STATE=str(temp / "web"),
            EMMC_RUNTIME=str(temp / "run"),
            EMMC_WORKER_SOCKET=str(temp / "control.sock"),
        )
        import worker, web

        manager = worker.Manager()
        server = worker.Server(str(temp / "control.sock"), worker.Handler)
        server.manager = manager
        threading.Thread(target=server.serve_forever, daemon=True).start()
        web.app.config["TESTING"] = True
        client = web.app.test_client()
        d = next(d for d in inventory() if d["path"] == loop)
        target = {"target": loop, "identity": d["identity"]}
        assert client.get("/api/v1/streams/" + "a" * 32).status_code == 401
        web.set_password("emmc-admin", "test-stream-password")
        csrf = client.post(
            "/api/v1/auth/login",
            json={"username": "emmc-admin", "password": "test-stream-password"},
        ).json["csrf"]
        headers = {"X-CSRF-Token": csrf}

        def prepare(op, **extra):
            response = client.post(
                "/api/v1/jobs", json={**target, "op": op, **extra}, headers=headers
            )
            assert response.status_code == 202, response.data
            return response.json

        def completed(job, state="completed"):
            for _ in range(200):
                current = manager.get_job(job["id"])
                if current["state"] not in ("running", "queued"):
                    assert current["state"] == state, current
                    return current
                time.sleep(0.01)
            raise AssertionError("stream did not finish")

        original_downloads = list(worker.WEBSTATE.joinpath("downloads").iterdir())
        original_backups = list(worker.STATE.joinpath("backups").iterdir())
        job = prepare("range_export", offset=37, length=2 * 1024 * 1024 + 3)
        response = client.get(
            "/api/v1/streams/" + job["result"]["stream"], buffered=False
        )
        assert (
            response.status_code == 200
            and response.content_length == 2 * 1024 * 1024 + 3
        )
        digest = hashlib.sha256()
        count = 0
        for block in response.response:
            assert len(block) <= 256 * 1024
            digest.update(block)
            count += len(block)
        response.close()
        assert count == 2 * 1024 * 1024 + 3
        with open(image, "rb") as f:
            f.seek(37)
            expected = hashlib.sha256(f.read(count)).hexdigest()
        assert digest.hexdigest() == expected == completed(job)["result"]["sha256"]
        assert (
            list(worker.WEBSTATE.joinpath("downloads").iterdir()) == original_downloads
        )
        assert not manager.busy

        def mutate(op, node, **extra):
            current = next(x for x in inventory() if x["path"] == loop)
            mutation = manager.submit(
                {
                    "op": op,
                    "target": node,
                    "identity": current["identity"],
                    "confirm": node,
                    **extra,
                }
            )
            for _ in range(500):
                result = manager.get_job(mutation["id"])
                if result["state"] not in ("running", "queued"):
                    assert result["state"] == "completed", result
                    return
                time.sleep(0.01)
            raise AssertionError("filesystem fixture did not finish")

        mutate("partition", loop, action="new_table", table="gpt")
        mutate("partition", loop, action="create", start=2048, size=196608)
        part = next(x for x in inventory() if x["path"] == loop)["regions"][1]["path"]
        mutate("format", part, filesystem="ext4", label="STREAM")
        mutate(
            "file_write",
            part,
            edit_mode=True,
            action="text",
            path="hello.txt",
            text="流式文件测试",
            overwrite=False,
        )
        filejob = prepare("file_export", target=part, path="hello.txt")
        response = client.get(
            "/api/v1/streams/" + filejob["result"]["stream"], buffered=False
        )
        assert b"".join(response.response) == "流式文件测试".encode()
        response.close()
        completed(filejob)
        job = prepare("backup", storage="browser", gzip=True, full=False)
        response = client.get(
            "/api/v1/streams/" + job["result"]["stream"], buffered=False
        )
        assert (
            response.content_length is None
            and ".tar.gz" in response.headers["Content-Disposition"]
        )
        packed = b"".join(response.response)
        response.close()
        completed(job)
        with tarfile.open(fileobj=io.BytesIO(packed), mode="r:*") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            area = manifest["regions"][0]
            assert area["compressed"] is False
            digest = hashlib.sha256()
            with archive.extractfile(area["file"]) as source:
                while block := source.read(256 * 1024):
                    digest.update(block)
            assert digest.hexdigest() == area["sha256"] == area["file_sha256"]
        assert list(worker.STATE.joinpath("backups").iterdir()) == original_backups
        assert (
            list(worker.WEBSTATE.joinpath("downloads").iterdir()) == original_downloads
        )
        # New outer-gzip archives are accepted by the existing restore/import pipeline.
        upload = "e" * 32
        (worker.WEBSTATE / "uploads" / upload).write_bytes(packed)
        (worker.WEBSTATE / "uploads" / (upload + ".json")).write_text(
            json.dumps({"complete": True, "size": len(packed)})
        )
        imported = manager.import_backup(
            {"upload": upload}, lambda *a: None, lambda: False
        )
        assert (
            worker.STATE / "backups" / imported["backup"] / area["file"]
        ).stat().st_size == 128 * 1024 * 1024
        exported = prepare("backup_export", backup=imported["backup"])
        response = client.get(
            "/api/v1/streams/" + exported["result"]["stream"], buffered=False
        )
        exported_tar = temp / "exported.tar"
        with open(exported_tar, "wb") as out:
            for block in response.response:
                out.write(block)
        response.close()
        completed(exported)
        with tarfile.open(exported_tar) as archive:
            assert "manifest.json" in archive.getnames()
        assert (
            list(worker.WEBSTATE.joinpath("downloads").iterdir()) == original_downloads
        )
        # Back pressure keeps a root disk lock, and another stream cannot take it.
        job = prepare("range_export", offset=0, length=16 * 1024 * 1024)
        response = client.get(
            "/api/v1/streams/" + job["result"]["stream"], buffered=False
        )
        other = prepare("range_export", offset=0, length=512)
        denied = client.get("/api/v1/streams/" + other["result"]["stream"])
        assert denied.status_code == 400
        assert manager.busy
        assert (
            client.post(
                "/api/v1/jobs/" + job["id"] + "/cancel", json={}, headers=headers
            ).status_code
            == 200
        )
        response.close()
        completed(job, "cancelled")
        assert not manager.busy
        queued = prepare("range_export", offset=0, length=512)
        client.post(
            "/api/v1/jobs/" + queued["id"] + "/cancel", json={}, headers=headers
        )
        assert manager.get_job(queued["id"])["state"] == "cancelled"
        assert (
            client.get("/api/v1/streams/" + queued["result"]["stream"]).status_code
            == 400
        )
        assert client.get("/api/v1/streams/not-a-token").status_code == 400
        invalid = client.post(
            "/api/v1/jobs",
            json={
                **target,
                "identity": "wrong",
                "op": "range_export",
                "offset": 0,
                "length": 512,
            },
            headers=headers,
        )
        assert invalid.status_code == 400
        print(
            "PASS: authenticated streaming, exact bytes, gzip tar checksums/import, no image staging, conflict, disconnect/cancel, queued cancellation, identity/token protection"
        )
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if loop:
            if manager:
                for entry in list(manager.mounts.values()):
                    run(["umount", str(entry["root"])])
            backing = run(["losetup", "-n", "-O", "BACK-FILE", loop]).strip()
            assert Path(backing).resolve().is_relative_to(temp.resolve())
            run(["losetup", "-d", loop])
        assert temp.resolve().name.startswith("emmc-stream-test-")
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
