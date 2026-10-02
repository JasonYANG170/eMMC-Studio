import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import (
    StorageError,
    bounds,
    check_overlap,
    resolve_region,
    safe_path,
    token_path,
    copy_stream,
    number,
)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.disk = {
            "path": "/dev/mmcblk0",
            "identity": "sd:system",
            "writable": False,
            "regions": [{"path": "/dev/mmcblk0", "size": 10000, "region": "user"}],
        }

    def test_system_disk_readable_but_never_writable(self):
        self.assertEqual(
            resolve_region("/dev/mmcblk0", "sd:system", disks=[self.disk])[0], self.disk
        )
        with self.assertRaises(StorageError):
            resolve_region("/dev/mmcblk0", "sd:system", True, [self.disk])

    def test_replacement_device_rejected(self):
        with self.assertRaises(StorageError):
            resolve_region("/dev/mmcblk0", "sd:changed", False, [self.disk])

    def test_unknown_node_rejected(self):
        with self.assertRaises(StorageError):
            resolve_region("/dev/sda", disks=[self.disk])

    def test_same_disk_clone_rejected(self):
        with self.assertRaises(StorageError):
            check_overlap(self.disk, self.disk)

    def test_range_boundaries(self):
        self.assertEqual(bounds(0, 512, 512, 65536), (0, 512))
        for off, size in [(-1, 1), (0, 0), (1, 512), (0, 65537)]:
            with self.assertRaises(StorageError):
                bounds(off, size, 65536 if size == 65537 else 512, 65536)

    def test_strict_integer(self):
        for v in [True, "1.2", "-1", "0x10", None]:
            with self.assertRaises(StorageError):
                number(v)

    def test_traversal_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            (root / "inside").write_text("x")
            self.assertEqual(safe_path(root, "inside"), root / "inside")
            with self.assertRaises(StorageError):
                safe_path(root, "../outside", True)
            if os.name != "nt":
                (root / "link").symlink_to(Path(tmp))
                with self.assertRaises(StorageError):
                    safe_path(root, "link/outside", True)

    def test_token_validation(self):
        with self.assertRaises(StorageError):
            token_path("/tmp", "../../etc/passwd")

    def test_short_source_fails(self):
        with tempfile.TemporaryFile() as t:
            with self.assertRaises(StorageError):
                copy_stream(io.BytesIO(b"abc"), t, 4, lambda *a: None)

    def test_copy_readback_and_cancel(self):
        data = b"hello\x00" * 1000
        with tempfile.TemporaryFile() as t:
            digest = copy_stream(
                io.BytesIO(data), t, len(data), lambda *a: None, verify=True
            )
            import hashlib

            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryFile() as t:
            with self.assertRaises(StorageError):
                copy_stream(
                    io.BytesIO(data), t, len(data), lambda *a: None, lambda: True
                )


if __name__ == "__main__":
    unittest.main()
