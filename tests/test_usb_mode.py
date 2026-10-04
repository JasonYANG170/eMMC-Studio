"""USB role policy tests; no real mode changes or block-device writes."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import StorageError
from usb_mode import UsbModeControl


class UsbPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manager = MagicMock()
        self.manager.guard = threading.RLock()
        self.manager.usb_switching = False
        self.manager.upgrade_frozen = False
        self.manager.busy = set()
        self.connection = self.manager.connect.return_value.__enter__.return_value
        self.connection.execute.return_value = []
        self.usb = UsbModeControl(self.manager)

    def submit(self, **args):
        with patch.object(
            self.usb, "status", return_value={"available": True}
        ), patch.object(self.usb, "check_mounts"), patch("usb_mode.threading.Thread"):
            return self.usb.submit(dict(mode="host", acknowledged=True, **args))

    def test_invalid_parameters(self):
        for args in [
            {},
            {"mode": "shell", "acknowledged": True},
            {"mode": "host", "acknowledged": "true"},
        ]:
            with self.assertRaises(StorageError):
                self.usb.submit(args)
        self.manager.save.assert_not_called()

    def test_active_task_and_busy_disk(self):
        self.connection.execute.return_value = [(json.dumps({"state": "running"}),)]
        with self.assertRaises(StorageError):
            self.submit()
        self.connection.execute.return_value = []
        self.manager.busy = {"usb:disk"}
        with self.assertRaises(StorageError):
            self.submit()
        self.manager.save.assert_not_called()

    def test_task_freezes_new_operations(self):
        job = self.submit()
        self.assertTrue(self.manager.usb_switching)
        self.assertEqual(job["op"], "usb_mode")
        with self.assertRaises(StorageError):
            self.submit()

    def test_usb_mount_is_rejected_in_both_namespaces(self):
        with patch("usb_mode.Path") as path:
            path.return_value.read_text.side_effect = [
                "",
                "1 2 8:1 / /media/usb rw - ext4 /dev/sda1 rw\n",
            ]
            path.return_value.resolve.return_value = Path(
                "/sys/devices/usb1/block/sda/sda1"
            )
            with self.assertRaises(StorageError):
                self.usb.check_mounts()

    def test_cancel_before_switch_executes_no_command(self):
        with patch("usb_mode.run") as run:
            with self.assertRaises(StorageError):
                self.usb.change({"mode": "host"}, {}, MagicMock(), lambda: True)
            run.assert_not_called()

    def test_host_switch_uses_fixed_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            mode = Path(folder) / "mode"
            mode.write_text("device")
            with patch.object(self.usb, "controller", return_value=mode), patch.object(
                self.usb, "check_mounts"
            ), patch("usb_mode.time.sleep"), patch("usb_mode.run") as run:
                run.return_value = "[]"
                result = self.usb.change(
                    {"mode": "host"}, {}, MagicMock(), lambda: False
                )
                self.assertEqual(result["mode"], "host")
                self.assertEqual(
                    run.call_args_list[0].args[0],
                    ["systemctl", "disable", "--now", "emmc-usb-network.service"],
                )

    def test_device_ready_uses_netlink_address(self):
        with tempfile.TemporaryDirectory() as folder:
            mode = Path(folder) / "mode"
            mode.write_text("host")

            def command(args, **kwargs):
                if args[0] == "ip":
                    return json.dumps(
                        [
                            {
                                "ifname": "emmcusb0",
                                "addr_info": [{"local": "172.30.77.1"}],
                            }
                        ]
                    )
                return "active" if args[1] == "is-active" else ""

            with patch.object(self.usb, "controller", return_value=mode), patch.object(
                self.usb, "check_mounts"
            ), patch("usb_mode.time.sleep"), patch("usb_mode.run", side_effect=command):
                self.assertEqual(
                    self.usb.change({"mode": "device"}, {}, MagicMock(), lambda: False),
                    {"mode": "device"},
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
