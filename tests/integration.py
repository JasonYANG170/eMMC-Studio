"""Run as root on Linux. Destructive tests target ONLY owned temporary loop devices."""

import gzip, json, os, shutil, sys, tempfile, time, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import run, sha_file, StorageError


def main():
    if os.getuid() != 0:
        raise RuntimeError("root required")
    temp = Path(tempfile.mkdtemp(prefix="emmc-test-"))
    loops = []
    try:
        for name in ("source", "target"):
            image = temp / (name + ".img")
            with open(image, "wb") as f:
                f.truncate(128 * 1024 * 1024)
            loops.append(
                run(["losetup", "--find", "--show", "--partscan", str(image)]).strip()
            )
        os.environ["EMMC_TEST_DEVICES"] = ",".join(loops)
        os.environ["EMMC_WORKER_STATE"] = str(temp / "state")
        os.environ["EMMC_WEB_STATE"] = str(temp / "web")
        os.environ["EMMC_RUNTIME"] = str(temp / "run")
        import worker
        from core import inventory, resolve_region

        m = worker.Manager()

        def disk(path):
            return next(d for d in inventory() if d["path"] == path)

        def do(op, target, **kwargs):
            d, r = resolve_region(target)
            if op == "file_write":
                kwargs["edit_mode"] = True
            job = m.submit(dict(op=op, target=target, identity=d["identity"], **kwargs))
            for _ in range(600):
                j = m.get_job(job["id"])
                if j["state"] not in ("queued", "running"):
                    if j["state"] != "completed":
                        raise AssertionError(json.dumps(j))
                    return j["result"]
                time.sleep(0.1)
            raise AssertionError("job timeout")

        # Real partition tools and filesystem mounts, without touching any MMC device.
        src, dst = loops
        do("partition", src, action="new_table", table="gpt")
        do("partition", src, action="create", start=2048, size=196608)
        r = next(r for r in disk(src)["regions"] if r["region"] == "partition")
        part = r["path"]
        do("format", part, filesystem="ext4", label="TEST")
        do("file_write", part, action="mkdir", path="hello")
        do(
            "file_write",
            part,
            action="text",
            path="hello/message.txt",
            text="你好 eMMC\n",
            overwrite=False,
        )
        identity = disk(src)["identity"]
        assert (
            m.fs_text(
                {"target": part, "identity": identity, "path": "hello/message.txt"}
            )["text"]
            == "你好 eMMC\n"
        )
        do(
            "file_write",
            part,
            action="rename",
            path="hello/message.txt",
            destination="hello/renamed.txt",
        )
        do("file_export", part, path="hello/renamed.txt")
        do("file_write", part, action="delete", path="hello/renamed.txt")
        do("resize", part, size=131072)
        do("resize", part, size=196608)
        before = m.hex_read(
            {"target": src, "identity": identity, "offset": 104857600, "length": 512}
        )
        result = do(
            "hex_write",
            src,
            offset=104857600,
            hex="a5" * 512,
            expected_sha256=before["sha256"],
        )
        do("undo_hex", src, snapshot=result["snapshot"])
        assert (
            m.hex_read(
                {
                    "target": src,
                    "identity": identity,
                    "offset": 104857600,
                    "length": 512,
                }
            )["hex"]
            == before["hex"]
        )
        backup = do("backup", src, gzip=True, storage="local", full=False)
        browser_backup = do("backup", src, gzip=True, storage="browser", full=False)
        assert browser_backup["download"]
        assert (
            worker.WEBSTATE / "downloads" / browser_backup["download"]
        ).stat().st_size > 0
        assert m.jobs()[0]["bytes"] == m.jobs()[0]["total"] > 0
        import tarfile

        with tarfile.open(
            worker.WEBSTATE / "downloads" / browser_backup["download"]
        ) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            item = manifest["regions"][0]
            with gzip.GzipFile(fileobj=archive.extractfile(item["file"])) as image:
                import hashlib

                digest = hashlib.sha256()
                while chunk := image.read(4 * 1024 * 1024):
                    digest.update(chunk)
                assert digest.hexdigest() == sha_file(src)
        do("clone", dst, source=src, source_identity=identity)
        assert sha_file(src) == sha_file(dst)
        do("restore", dst, backup=backup["backup"], backup_region="user")
        assert sha_file(src) == sha_file(dst)
        job = m.submit({"op": "backup_export", "backup": backup["backup"]})
        while (j := m.get_job(job["id"]))["state"] in ("queued", "running"):
            time.sleep(0.1)
        assert j["state"] == "completed", j
        token = j["result"]["download"]
        f = worker.WEBSTATE / "downloads" / token
        upload = uuid.uuid4().hex
        u = worker.WEBSTATE / "uploads" / upload
        shutil.copyfile(f, u)
        u.with_suffix(".json").write_text(
            json.dumps({"complete": True, "size": u.stat().st_size})
        )
        jid = m.submit({"op": "import_backup", "upload": upload})["id"]
        while (j := m.get_job(jid))["state"] in ("queued", "running"):
            time.sleep(0.1)
        assert j["state"] == "completed", j
        # A gzip size mismatch must not perform any write.
        u2 = uuid.uuid4().hex
        p = worker.WEBSTATE / "uploads" / u2
        with gzip.open(p, "wb") as f:
            f.write(b"x" * 8192)
        p.with_suffix(".json").write_text(
            json.dumps({"complete": True, "size": p.stat().st_size})
        )
        unchanged = sha_file(dst)
        jid = m.submit(
            {
                "op": "restore",
                "target": dst,
                "identity": disk(dst)["identity"],
                "confirm": dst,
                "upload": u2,
                "gzip": True,
                "image_size": 4096,
            }
        )["id"]
        while (j := m.get_job(jid))["state"] in ("queued", "running"):
            time.sleep(0.1)
        assert j["state"] == "failed" and sha_file(dst) == unchanged
        # Check non-GPT layout, boot flag, modification, deletion, formatting variants.
        do("partition", dst, action="new_table", table="dos")
        do("partition", dst, action="create", start=2048, size=196608)
        part = next(
            r["path"] for r in disk(dst)["regions"] if r["region"] == "partition"
        )
        for fs in ("vfat", "exfat", "ntfs"):
            do("format", part, filesystem=fs, label="TEST")
        do(
            "partition",
            dst,
            action="modify",
            index=1,
            label="",
            type="c",
            bootable=True,
        )
        do(
            "partition",
            dst,
            action="modify",
            index=1,
            label="",
            type="c",
            bootable=False,
        )
        result = do("partition", dst, action="delete", index=1)
        do("restore_table", dst, snapshot=result["table_snapshot"])
        assert disk(dst)["table"]["partitions"]
        for bad in [
            dict(op="clone", source=dst, source_identity=disk(dst)["identity"]),
            dict(op="hex_write", offset=-1, hex="00"),
        ]:
            try:
                rejected = m.submit(
                    dict(target=dst, identity=disk(dst)["identity"], confirm=dst, **bad)
                )
            except StorageError:
                pass
            else:
                assert bad["op"] == "hex_write"  # validated inside its job
                while (j := m.get_job(rejected["id"]))["state"] in (
                    "queued",
                    "running",
                ):
                    time.sleep(0.1)
                assert j["state"] == "failed"
        # Real external mount, conflict and available-space guards.
        sourcepart = next(
            r["path"] for r in disk(src)["regions"] if r["region"] == "partition"
        )
        external = temp / "external"
        external.mkdir()
        m.check_unused(disk(src))
        run(["mount", "-o", "ro,noload", sourcepart, str(external)])
        try:
            try:
                m.check_unused(disk(src))
            except StorageError:
                pass
            else:
                raise AssertionError("external mount accepted")
        finally:
            run(["umount", str(external)])
        m.acquire([identity])
        try:
            try:
                m.submit(
                    {"op": "backup", "target": src, "identity": identity, "full": False}
                )
            except StorageError:
                pass
            else:
                raise AssertionError("concurrent job accepted")
        finally:
            m.release([identity])
        try:
            m.ensure_space(temp, 2**62)
        except StorageError:
            pass
        else:
            raise AssertionError("insufficient space accepted")
        targetpart = next(
            r["path"] for r in disk(dst)["regions"] if r["region"] == "partition"
        )
        try:
            m.submit(
                {
                    "op": "clone",
                    "target": targetpart,
                    "identity": disk(dst)["identity"],
                    "confirm": targetpart,
                    "source": src,
                    "source_identity": identity,
                }
            )
        except StorageError:
            pass
        else:
            raise AssertionError("insufficient target accepted")
        # File writes require explicit editing mode without typed target confirmation.
        jid = m.submit(
            {
                "op": "file_write",
                "target": sourcepart,
                "identity": identity,
                "confirm": sourcepart,
                "action": "mkdir",
                "path": "blocked",
            }
        )["id"]
        while (j := m.get_job(jid))["state"] in ("queued", "running"):
            time.sleep(0.1)
        assert j["state"] == "failed"
        print(
            "PASS: GPT/MBR, ext4/FAT32/exFAT/NTFS, files, resize, hex rollback, clone, backup/import/restore, gzip precheck"
        )
        # Restart state marks in-flight jobs interrupted.
        m.save({"id": "test-interrupted", "state": "running", "created": 0})
        assert worker.Manager().get_job("test-interrupted")["state"] == "interrupted"
    finally:
        # Verify explicit test ownership before any loop detach or cleanup.
        if "m" in locals():
            for mounted in list(m.mounts.values()):
                run(["umount", str(mounted["root"])], accepted=(0, 32))
        for device in loops:
            backing = run(["losetup", "-n", "-O", "BACK-FILE", device]).strip()
            if not Path(backing).resolve().is_relative_to(temp.resolve()):
                raise RuntimeError("unexpected backing file")
            run(["losetup", "-d", device])
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
