"""Cache cleanup uses temporary directories only; never opens a disk device."""

import json, os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
with tempfile.TemporaryDirectory() as bootstrap:
    os.environ.update(
        EMMC_WORKER_STATE=bootstrap + "/worker",
        EMMC_WEB_STATE=bootstrap + "/web",
        EMMC_RUNTIME=bootstrap + "/run",
    )
    import worker, web


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(worker, k, self.root / v)
            for k, v in [("STATE", "worker"), ("WEBSTATE", "web"), ("RUNTIME", "run")]
        ]
        for p in self.patches:
            p.start()
        self.m = worker.Manager()
        self.cache = self.m.cache

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def job(self, state="completed"):
        j = dict(
            id=uuid.uuid4().hex,
            op="backup",
            title="temporary-cache-test",
            created=time.time(),
            finished=time.time(),
            state=state,
        )
        self.m.save(j)
        return j

    def file(self, kind="downloads", complete=True):
        token = uuid.uuid4().hex
        root = worker.STATE / kind if kind == "snapshots" else worker.WEBSTATE / kind
        p = root / token
        if kind == "snapshots":
            p.mkdir()
            (p / "bytes.bin").write_bytes(b"original")
            meta = p / "meta.json"
        else:
            p.write_bytes(b"cache-only")
            meta = p.with_suffix(".json")
        meta.write_text(
            json.dumps(
                dict(
                    kind="hex",
                    created=time.time(),
                    complete=complete,
                    name="temporary-file",
                )
            )
        )
        return p, next(i for i in self.cache.inventory()["items"] if i["id"] == token)

    def test_01_selective_cleanup_preserves_backups_and_credentials(self):
        saved = worker.STATE / "backups" / uuid.uuid4().hex
        saved.mkdir()
        (saved / "image").write_bytes(b"backup")
        auth = worker.WEBSTATE / "auth.json"
        auth.write_text("protected")
        paths = []
        items = []
        for kind in ("snapshots", "downloads", "uploads"):
            p, i = self.file(kind)
            paths.append(p)
            items.append(i)
        unused, _ = self.file()
        result = self.cache.execute({"items": items})
        self.assertEqual(len(result["removed"]), 3)
        self.assertGreater(result["freed"], 0)
        self.assertTrue(all(not p.exists() for p in paths))
        self.assertTrue(unused.exists())
        self.assertEqual(auth.read_text(), "protected")
        self.assertEqual((saved / "image").read_bytes(), b"backup")

    def test_02_more_than_one_hundred_jobs_and_active_retention(self):
        for _ in range(105):
            self.job()
        queued = self.job("queued")
        running = self.job("running")
        result = self.cache.clear_jobs({"all": True})
        self.assertEqual(len(result["removed"]), 105)
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(
            {j["id"] for j in self.cache.all_jobs()}, {queued["id"], running["id"]}
        )

    def test_03_in_use_and_recent_upload_retained(self):
        p, item = self.file("uploads", False)
        self.assertTrue(item["locked"])
        self.assertEqual(len(self.cache.execute({"items": [item]})["skipped"]), 1)
        os.utime(p, (time.time() - 600, time.time() - 600))
        item = next(i for i in self.cache.inventory()["items"] if i["id"] == p.name)
        self.assertFalse(item["locked"])
        self.m.busy.add("test-disk")
        self.assertEqual(len(self.cache.execute({"items": [item]})["skipped"]), 1)
        self.m.busy.clear()
        self.assertEqual(len(self.cache.execute({"items": [item]})["removed"]), 1)

    def test_04_changed_file_is_not_deleted(self):
        p, item = self.file()
        p.write_bytes(b"changed-file-content")
        result = self.cache.execute({"items": [item]})
        self.assertEqual(len(result["skipped"]), 1)
        self.assertTrue(p.exists())

    def test_05_path_and_symlink_rejected(self):
        from core import StorageError

        for bad in [
            {"kind": "downloads", "id": "../auth.json"},
            {"kind": "backups", "id": "a" * 32},
        ]:
            with self.assertRaises(StorageError):
                self.cache.execute({"items": [bad]})
        p, item = self.file()
        p.unlink()
        p.symlink_to(worker.STATE / "jobs.sqlite")
        self.assertFalse(
            any(i["id"] == p.name for i in self.cache.inventory()["items"])
        )
        self.assertEqual(len(self.cache.execute({"items": [item]})["removed"]), 0)

    def test_06_stream_ticket_retention_and_revocation(self):
        j = self.job()
        token = uuid.uuid4().hex
        self.m.streams.tickets[token] = {"job": j["id"], "active": True}
        self.assertEqual(len(self.cache.clear_jobs({"all": True})["removed"]), 0)
        self.m.streams.tickets[token]["active"] = False
        self.assertEqual(len(self.cache.clear_jobs({"all": True})["removed"]), 1)
        self.assertNotIn(token, self.m.streams.tickets)

    def test_07_api_auth_csrf_and_cleanup(self):
        with patch.object(web, "STATE", worker.WEBSTATE), patch.object(
            web, "AUTH", worker.WEBSTATE / "auth.json"
        ), patch.object(
            web,
            "rpc",
            side_effect=lambda op, args=None: self.m.request(
                {"method": op, "args": args or {}}
            ),
        ):
            client = web.app.test_client()
            web.failures.clear()
            self.assertEqual(client.get("/api/v1/cache").status_code, 401)
            self.assertEqual(
                client.post("/api/v1/cache/clear", json={"items": []}).status_code, 401
            )
            web.set_password("emmc-admin", "test1234")
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "emmc-admin", "password": "test1234"},
            )
            csrf = login.json["csrf"]
            p, item = self.file()
            self.assertEqual(
                client.post("/api/v1/cache/clear", json={"items": [item]}).status_code,
                403,
            )
            self.assertEqual(client.get("/api/v1/cache").status_code, 200)
            result = client.post(
                "/api/v1/cache/clear",
                json={"items": [item]},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(result.status_code, 200)
            self.assertFalse(p.exists())
            self.job()
            result = client.post(
                "/api/v1/jobs/clear", json={"all": True}, headers={"X-CSRF-Token": csrf}
            )
            self.assertEqual(len(result.json["removed"]), 1)

    def test_08_orphan_file_cleanup(self):
        p, item = self.file()
        p.with_suffix(".json").unlink()
        item = next(i for i in self.cache.inventory()["items"] if i["id"] == p.name)
        self.assertEqual(item["name"], "无元数据暂存文件")
        self.assertEqual(len(self.cache.execute({"items": [item]})["removed"]), 1)

    def test_09_active_http_download_protected(self):
        with patch.object(web, "STATE", worker.WEBSTATE), patch.object(
            web, "AUTH", worker.WEBSTATE / "auth.json"
        ), patch.object(
            web,
            "rpc",
            side_effect=lambda op, args=None: self.m.request(
                {"method": op, "args": args or {}}
            ),
        ):
            web.set_password("emmc-admin", "test1234")
            web.failures.clear()
            client = web.app.test_client()
            r = client.post(
                "/api/v1/auth/login",
                json={"username": "emmc-admin", "password": "test1234"},
            )
            csrf = r.json["csrf"]
            p, item = self.file()
            download = client.get("/api/v1/downloads/" + p.name, buffered=False)
            self.assertTrue(web.cache_readers.get(p.name))
            self.assertTrue(
                next(
                    i
                    for i in client.get("/api/v1/cache").json["items"]
                    if i["id"] == p.name
                )["locked"]
            )
            result = client.post(
                "/api/v1/cache/clear",
                json={"items": [item]},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(len(result.json["skipped"]), 1)
            self.assertTrue(p.exists())
            download.close()
            self.assertFalse(web.cache_readers.get(p.name))
            result = client.post(
                "/api/v1/cache/clear",
                json={"items": [item]},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(len(result.json["removed"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
