"""Owned temporary paths verify mount cache invalidation after card replacement."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import worker


class MediaMountTests(unittest.TestCase):
    def test_new_identity_or_generation_cannot_reuse_old_mount(self):
        for media in [("emmc:new", "1"), ("emmc:old", "2")]:
            with self.subTest(media=media), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / "mounts").mkdir()
                disk = dict(
                    identity=media[0], protected=False, block_info={"diskseq": media[1]}
                )
                region = dict(
                    path="/dev/test-partition",
                    identity=media[0],
                    region="partition",
                    fstype="ext4",
                )
                manager = worker.Manager.__new__(worker.Manager)
                manager.mounts = {
                    region["path"]: {
                        "root": root / "old",
                        "rw": False,
                        "media": ("emmc:old", "1"),
                    }
                }
                with patch.object(worker, "RUNTIME", root), patch.object(
                    worker, "resolve_region", return_value=(disk, region)
                ), patch.object(worker, "host_mounts", return_value=[]), patch.object(
                    worker, "run", return_value=""
                ) as run:
                    current = manager.mount(region)
                    self.assertNotEqual(current, root / "old")
                    self.assertEqual(
                        run.call_args_list[0].args[0], ["umount", str(root / "old")]
                    )
                    self.assertEqual(manager.mounts[region["path"]]["media"], media)
                    count = run.call_count
                    self.assertEqual(manager.mount(region), current)
                    self.assertEqual(run.call_count, count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
