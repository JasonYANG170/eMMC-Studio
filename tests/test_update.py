"""Signed package security and independent updater failure/state tests."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import update_package as packages


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory()
        cls.key = Path(cls.keys.name) / "key.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(cls.key)],
            check=True,
            capture_output=True,
        )
        cls.public = subprocess.check_output(
            ["openssl", "pkey", "-in", str(cls.key), "-pubout"]
        )

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.anchor = patch.object(packages, "PUBLIC_KEY", self.public)
        self.anchor.start()

    def tearDown(self):
        self.anchor.stop()
        self.temp.cleanup()

    def bundle(
        self,
        extra=None,
        metadata=None,
        tamper=False,
        omit=None,
        script=b"#!/bin/sh\nexit 0\n",
    ):
        payload = self.root / "payload.tar.gz"
        with tarfile.open(payload, "w:gz") as archive:
            for name in sorted(packages.REQUIRED - {omit}):
                data = (
                    b"1.2.0\n"
                    if name == "VERSION"
                    else script if name == "deploy/install.sh" else b"test"
                )
                info = tarfile.TarInfo("eMMC-Studio/" + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b"bad") if extra.isfile() else None)
        meta = {
            "version": "1.2.0",
            "minimum_version": "1.1.0",
            "platform": "linux-systemd-debian",
            "schema": 1,
            "size": payload.stat().st_size,
            "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        }
        meta.update(metadata or {})
        manifest = self.root / "manifest"
        signature = self.root / "signature"
        manifest.write_bytes(json.dumps(meta).encode())
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(self.key),
                "-rawin",
                "-in",
                str(manifest),
                "-out",
                str(signature),
            ],
            check=True,
            capture_output=True,
        )
        bundle = self.root / "update.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            for name, data in (
                ("manifest.json", manifest.read_bytes() + (b" " if tamper else b"")),
                ("manifest.sig", signature.read_bytes()),
                ("payload.tar.gz", payload.read_bytes()),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return bundle

    def unpack(self, bundle, current="1.1.0", reinstall=False):
        return packages.unpack(bundle, self.root / "verified", current, reinstall)

    def test_valid_package(self):
        meta, app = self.unpack(self.bundle())
        self.assertEqual(meta["version"], "1.2.0")
        self.assertEqual((app / "VERSION").read_text().strip(), "1.2.0")

    def test_tampered_manifest(self):
        with self.assertRaisesRegex(ValueError, "签名"):
            self.unpack(self.bundle(tamper=True))

    def test_untrusted_signer(self):
        bundle = self.bundle()
        with patch.object(
            packages, "PUBLIC_KEY", b"invalid key"
        ), self.assertRaisesRegex(ValueError, "签名"):
            self.unpack(bundle)

    def test_payload_digest(self):
        with self.assertRaisesRegex(ValueError, "校验"):
            self.unpack(self.bundle(metadata={"sha256": "0" * 64}))

    def test_platform(self):
        with self.assertRaisesRegex(ValueError, "平台"):
            self.unpack(self.bundle(metadata={"platform": "windows"}))

    def test_old_current(self):
        with self.assertRaisesRegex(ValueError, "过旧"):
            self.unpack(self.bundle(), current="1.0.0")

    def test_downgrade(self):
        with self.assertRaisesRegex(ValueError, "降级"):
            self.unpack(self.bundle(), current="1.3.0", reinstall=True)

    def test_same_version_rejected(self):
        with self.assertRaisesRegex(ValueError, "重新安装"):
            self.unpack(self.bundle(), current="1.2.0")

    def test_explicit_reinstall(self):
        self.unpack(self.bundle(), current="1.2.0", reinstall=True)

    def test_missing_file(self):
        with self.assertRaisesRegex(ValueError, "缺少"):
            self.unpack(self.bundle(omit="backend/worker.py"))

    def test_traversal_duplicate_symlink(self):
        for name, kind in (
            ("eMMC-Studio/../../escaped", tarfile.REGTYPE),
            ("eMMC-Studio/VERSION", tarfile.REGTYPE),
            ("eMMC-Studio/backend/link", tarfile.SYMTYPE),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as output:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = 3 if kind == tarfile.REGTYPE else 0
                info.linkname = "/etc/passwd"
                with self.assertRaisesRegex(ValueError, "路径"):
                    packages.unpack(
                        self.bundle(extra=info), Path(output) / "verified", "1.1.0"
                    )
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_expansion_limit(self):
        bundle = self.bundle()
        with patch.object(packages, "MAX_EXPANDED", 4), self.assertRaisesRegex(
            ValueError, "限制"
        ):
            self.unpack(bundle)


@unittest.skipUnless(sys.platform == "linux", "Linux updater service")
class UpdaterTests(PackageTests):
    def setUp(self):
        super().setUp()
        import updater

        self.updater = updater
        self.state = self.root / "state"
        self.runtime = self.root / "run"
        self.app = self.root / "installed"
        self.uploads = self.root / "uploads"
        self.app.mkdir()
        self.uploads.mkdir()
        (self.app / "VERSION").write_text("1.1.0")
        self.patches = [
            patch.object(updater, "STATE", self.state),
            patch.object(updater, "RUNTIME", self.runtime),
            patch.object(updater, "APP", self.app),
            patch.object(updater, "UPLOADS", self.uploads),
            patch.object(updater, "worker", return_value={"ok": True}),
            patch.object(
                updater.shutil,
                "disk_usage",
                return_value=shutil._ntuple_diskusage(10**10, 0, 10**10),
            ),
        ]
        for item in self.patches:
            item.start()
        self.manager = updater.Updates()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        super().tearDown()

    def stage(self, **kwargs):
        token = "a" * 32
        file = self.uploads / token
        shutil.copyfile(self.bundle(**kwargs), file)
        file.with_suffix(".json").write_text(
            json.dumps({"size": file.stat().st_size, "complete": True})
        )
        return {"source": "local", "upload": token}

    def run_install(self, args):
        self.manager.data = {"id": "testjob", "state": "running", "from": "1.1.0"}
        self.manager.install(args)
        return self.manager.status()["task"]

    def test_actual_installer_process(self):
        script = f"#!/bin/sh\nprintf '1.2.0' > '{self.app / 'VERSION'}'\n".encode()
        result = self.run_install(self.stage(script=script))
        self.assertEqual(result["state"], "completed")
        self.assertEqual(self.manager.status()["current"], "1.2.0")
        self.assertFalse((self.runtime / "maintenance").exists())

    def test_failed_installer_status_cleanup(self):
        result = self.run_install(self.stage(script=b"#!/bin/sh\nexit 1\n"))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(self.manager.status()["current"], "1.1.0")
        self.assertFalse((self.runtime / "maintenance").exists())

    def test_busy_disks_refuse_install(self):
        sentinel = self.root / "installer-ran"
        args = self.stage(script=f"#!/bin/sh\ntouch '{sentinel}'\n".encode())
        with patch.object(self.updater, "worker", side_effect=ValueError("busy")):
            self.assertEqual(self.run_install(args)["error"], "busy")
            self.assertFalse(sentinel.exists())

    def test_incomplete_upload(self):
        args = self.stage()
        (self.uploads / (args["upload"] + ".json")).write_text('{"complete":false}')
        self.assertEqual(self.run_install(args)["state"], "failed")

    def test_interrupted_restart(self):
        self.manager.data = {"state": "running", "id": "previous"}
        self.manager.save()
        restarted = self.updater.Updates()
        self.assertEqual(restarted.status()["task"]["state"], "interrupted")

    def test_upgrade_conflict(self):
        self.manager.data["state"] = "running"
        with self.assertRaisesRegex(ValueError, "正在执行"):
            self.manager.submit({"source": "online"})

    def test_space(self):
        args = self.stage()
        with patch.object(
            self.updater.shutil,
            "disk_usage",
            return_value=shutil._ntuple_diskusage(10, 9, 1),
        ):
            self.assertEqual(self.run_install(args)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
