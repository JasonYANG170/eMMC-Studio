"""Regression: backup already owns the disk lock when reading EXT_CSD."""

import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


class LockTests(unittest.TestCase):
    def test_nested_snapshot_keeps_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "EMMC_WORKER_STATE": tmp + "/state",
                    "EMMC_WEB_STATE": tmp + "/web",
                    "EMMC_RUNTIME": tmp + "/run",
                },
            ):
                import worker

                m = worker.Manager()
                d = {"kind": "emmc", "identity": "test-card"}
                r = {"region": "user"}
                with patch.object(
                    worker, "resolve_region", return_value=(d, r)
                ), patch.object(worker, "run", return_value="EXT_CSD snapshot"):
                    m.acquire(["test-card"])
                    self.assertEqual(
                        m.extcsd("/dev/test", locked=True), "EXT_CSD snapshot"
                    )
                    self.assertIn("test-card", m.busy)
                    with self.assertRaises(worker.StorageError):
                        m.extcsd("/dev/test")
                    m.release(["test-card"])
                    self.assertEqual(m.extcsd("/dev/test"), "EXT_CSD snapshot")
                    self.assertFalse(m.busy)


if __name__ == "__main__":
    unittest.main()
