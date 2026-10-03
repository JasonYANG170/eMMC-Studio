"""Linux dependency test; execute separately with Debian's Flask installed."""

import hashlib, json, os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["EMMC_WEB_STATE"] = cls.temp.name
        import web

        cls.web = web
        web.app.config["TESTING"] = True
        cls.client = web.app.test_client()
        (Path(cls.temp.name) / "setup.hash").write_text(
            hashlib.sha256(b"test-only-code").hexdigest()
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_01_unauthenticated_denied(self):
        self.assertEqual(self.client.get("/api/v1/devices").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/system").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/upgrade").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/v1/upgrade/install", json={"source": "online"}
            ).status_code,
            401,
        )

    def test_02_setup_and_cookie(self):
        response = self.client.post(
            "/api/v1/auth/setup",
            json={"code": "test-only-code", "password": "temporary-test-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        AuthTests.csrf = response.json["csrf"]
        self.assertFalse((Path(self.temp.name) / "setup.hash").exists())

    def test_03_csrf_and_cross_origin(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/upgrade/install", json={"source": "online"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/v1/auth/logout", json={}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/logout",
                json={},
                headers={"X-CSRF-Token": self.csrf, "Origin": "http://evil.test"},
            ).status_code,
            403,
        )

    def test_04_chunk_upload_offset(self):
        r = self.client.post(
            "/api/v1/uploads",
            json={"name": "x.img", "size": 6},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(r.status_code, 200)
        uid = r.json["id"]
        r = self.client.put(
            "/api/v1/uploads/" + uid + "?offset=0",
            data=b"abc",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json["complete"])
        self.assertEqual(
            self.client.put(
                "/api/v1/uploads/" + uid + "?offset=0",
                data=b"abc",
                headers={"X-CSRF-Token": self.csrf},
            ).status_code,
            400,
        )
        r = self.client.put(
            "/api/v1/uploads/" + uid + "?offset=3",
            data=b"def",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertTrue(r.json["complete"])
        self.assertEqual(r.json["sha256"], hashlib.sha256(b"abcdef").hexdigest())

    def test_04b_system_and_download(self):
        r = self.client.get("/api/v1/system")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json["memory"]["total"], 0)
        self.assertGreater(r.json["cpu"]["cores"], 0)
        token = "a" * 32
        folder = Path(self.temp.name) / "downloads"
        (folder / token).write_bytes(b"backup-test-content")
        (folder / (token + ".json")).write_text(
            json.dumps({"name": "backup.tar", "size": 19})
        )
        r = self.client.get("/api/v1/downloads/" + token)
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(r.data, b"backup-test-content")
        r.close()

    def test_05_password_and_rate_limit(self):
        r = self.client.post(
            "/api/v1/auth/password",
            json={
                "old": "temporary-test-password",
                "password": "changed-test-password",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(r.status_code, 200)
        self.client.post(
            "/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": self.csrf}
        )
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    "/api/v1/auth/login",
                    json={"username": "emmc-admin", "password": "wrong"},
                ).status_code,
                401,
            )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login",
                json={"username": "emmc-admin", "password": "changed-test-password"},
            ).status_code,
            400,
        )

    def test_06_first_login_requires_password_change(self):
        from unittest.mock import patch

        self.web.failures.clear()
        auth = self.web.auth_data()
        auth["must_change"] = True
        self.web.AUTH.write_text(json.dumps(auth))
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "emmc-admin", "password": "changed-test-password"},
        )
        self.assertTrue(response.json["must_change"])
        token = response.json["csrf"]
        self.assertEqual(self.client.get("/api/v1/devices").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/jobs").status_code, 403)
        response = self.client.post(
            "/api/v1/auth/password",
            json={"old": "changed-test-password", "password": "final-test-password"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get("/api/v1/auth/status").json["must_change"])
        with patch.object(self.web, "rpc", return_value={"disks": []}):
            self.assertEqual(self.client.get("/api/v1/devices").status_code, 200)

    def test_07_password_length_boundary(self):
        token = self.client.get("/api/v1/auth/status").json["csrf"]
        version = self.web.auth_data()["version"]
        for value in ("1234567", "x" * 129):
            r = self.client.post(
                "/api/v1/auth/password",
                json={"old": "final-test-password", "password": value},
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(r.status_code, 400)
            self.assertEqual(self.web.auth_data()["version"], version)
        r = self.client.post(
            "/api/v1/auth/password",
            json={"old": "final-test-password", "password": "test1234"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.web.verify_password("test1234", self.web.auth_data()))

    def test_08_hash_storage_and_legacy_upgrade(self):
        from unittest.mock import patch
        import stat

        with tempfile.TemporaryDirectory() as folder, patch.object(
            self.web, "AUTH", Path(folder) / "auth.json"
        ):
            a = self.web.set_password("emmc-admin", "test1234")
            b = self.web.set_password("emmc-admin", "test1234")
            self.assertNotEqual(a["salt"], b["salt"])
            self.assertNotEqual(a["hash"], b["hash"])
            self.assertNotIn("test1234", self.web.AUTH.read_text())
            self.assertEqual(stat.S_IMODE(self.web.AUTH.stat().st_mode), 0o600)
            self.assertEqual(b["scrypt"], self.web.PASSWORD_SCRYPT)
            self.assertFalse(self.web.verify_password("wrong123", b))
            legacy = dict(
                username="emmc-admin",
                salt="ab" * 16,
                hash=self.web.password_hash("test1234", "ab" * 16),
                version="legacy-version",
                must_change=False,
            )
            self.web.save_auth(legacy)
            self.web.failures.clear()
            r = self.web.app.test_client().post(
                "/api/v1/auth/login",
                json={"username": "emmc-admin", "password": "test1234"},
            )
            self.assertEqual(r.status_code, 200)
            upgraded = self.web.auth_data()
            self.assertEqual(upgraded["scrypt"], self.web.PASSWORD_SCRYPT)
            self.assertEqual(upgraded["version"], "legacy-version")
            self.assertTrue(self.web.verify_password("test1234", upgraded))

    def test_09_setup_eight_characters(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder, patch.object(
            self.web, "STATE", Path(folder)
        ), patch.object(self.web, "AUTH", Path(folder) / "auth.json"):
            (Path(folder) / "setup.hash").write_text(
                hashlib.sha256(b"test-only-code").hexdigest()
            )
            self.web.failures.clear()
            client = self.web.app.test_client()
            self.assertEqual(
                client.post(
                    "/api/v1/auth/setup",
                    json={"code": "test-only-code", "password": "1234567"},
                ).status_code,
                400,
            )
            self.assertFalse(self.web.AUTH.exists())
            self.assertEqual(
                client.post(
                    "/api/v1/auth/setup",
                    json={"code": "test-only-code", "password": "test1234"},
                ).status_code,
                200,
            )
            self.assertEqual(self.web.auth_data()["algorithm"], "scrypt")

    def test_10_auth_rename_is_durable(self):
        from unittest.mock import patch
        import stat

        synced = []
        real_fsync = os.fsync

        def sync(fd):
            synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            real_fsync(fd)

        with tempfile.TemporaryDirectory() as folder, patch.object(
            self.web, "AUTH", Path(folder) / "auth.json"
        ), patch.object(self.web.os, "fsync", side_effect=sync):
            self.web.save_auth({"version": "test-durable"})
            self.assertEqual(synced, [False, True])
            self.assertEqual(self.web.auth_data(), {"version": "test-durable"})
            self.assertEqual(list(Path(folder).glob(".auth-*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
