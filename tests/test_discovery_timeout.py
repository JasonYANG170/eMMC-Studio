"""A stuck partition-table process cannot hold device discovery indefinitely."""

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import core


class DiscoveryTimeoutTests(unittest.TestCase):
    def setUp(self):
        core._table_busy.clear()
        core._table_retry.clear()

    def test_healthy_table_remains_available(self):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (
            json.dumps({"partitiontable": {"label": "gpt"}}),
            "",
        )
        with patch.object(core.subprocess, "Popen", return_value=process):
            for _ in range(2):
                self.assertEqual(
                    core.partition_table("/dev/test", "card", "1"), {"label": "gpt"}
                )
        self.assertFalse(core._table_busy)
        self.assertFalse(core._table_retry)

    def test_timeout_is_deferred_and_new_generation_is_independent(self):
        process = MagicMock()
        process.communicate.side_effect = subprocess.TimeoutExpired("sfdisk", 3)
        with patch.object(
            core.subprocess, "Popen", return_value=process
        ) as popen, patch.object(core.threading, "Thread") as thread:
            self.assertIsNone(core.partition_table("/dev/test", "old-card", "1"))
            process.kill.assert_called_once()
            thread.return_value.start.assert_called_once()
            self.assertIsNone(core.partition_table("/dev/test", "old-card", "1"))
            self.assertEqual(popen.call_count, 1)
            self.assertIsNone(core.partition_table("/dev/test", "new-card", "2"))
            self.assertEqual(popen.call_count, 2)

    def test_new_partition_table_is_visible_immediately_after_blank_disk(self):
        blank = MagicMock(returncode=1)
        blank.communicate.return_value = ("", "No partition table")
        created = MagicMock(returncode=0)
        created.communicate.return_value = (
            json.dumps({"partitiontable": {"label": "gpt"}}),
            "",
        )
        with patch.object(core.subprocess, "Popen", side_effect=[blank, created]):
            self.assertIsNone(core.partition_table("/dev/test", "same-card", "1"))
            self.assertFalse(core._table_retry)
            self.assertEqual(
                core.partition_table("/dev/test", "same-card", "1"), {"label": "gpt"}
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
