"""CLI units, command policy and bounded/atomic stream protocol tests."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import cli


class FakeClient:
    def __init__(self):
        self.calls = []
        self.disk = {
            "path": "/dev/test",
            "identity": "CID-original",
            "kind": "emmc",
            "size": 64 * 1024**2,
            "table": {
                "label": "gpt",
                "partitions": [{"node": "/dev/testp1", "name": "keep-name"}],
            },
            "regions": [
                {"path": "/dev/test", "region": "user", "size": 64 * 1024**2},
                {"path": "/dev/testboot0", "region": "boot0", "size": 4 * 1024**2},
            ],
        }

    def rpc(self, method, args=None):
        self.calls.append((method, args))
        if method == "inventory":
            return {"disks": [self.disk]}
        if method == "hex":
            return {"hex": "aa" * args["length"], "sha256": "before-hash"}
        if method == "submit":
            return {"id": "job-id", "state": "queued"}
        if method == "job":
            return {"id": "job-id", "state": "completed", "progress": 100}
        raise AssertionError(method)


class CLICommands(unittest.TestCase):
    def command(self, *args):
        return cli.parser().parse_args(list(args))

    def test_exact_units(self):
        for text, expected in (
            ("4MiB", 4194304),
            ("1.5GiB", 1610612736),
            ("4MB", 4000000),
            ("512", 512),
            (" 0.5 KiB ", 512),
        ):
            self.assertEqual(cli.size(text), expected)
        for text in ("-1", "1.5B", "4MIBB", "nan", "1e9", "999999999999999999999GiB"):
            with self.assertRaises(argparse.ArgumentTypeError):
                cli.size(text)

    def test_partition_units_are_bytes_not_sectors_and_dry_run_does_not_submit(self):
        client = FakeClient()
        result = cli.execute(
            client,
            self.command(
                "--dry-run",
                "partition",
                "create",
                "/dev/test",
                "--start",
                "1MiB",
                "--size",
                "16MiB",
            ),
        )
        self.assertEqual(result["request"]["start"], 2048)
        self.assertEqual(result["request"]["size"], 32768)
        self.assertFalse(result["submitted"])
        self.assertEqual(result["request"]["identity"], "CID-original")
        self.assertNotIn("submit", [x[0] for x in client.calls])
        with self.assertRaises(cli.CLIError):
            cli.sectors(cli.size("1MB"))

    def test_unmodified_partition_label_is_preserved(self):
        result = cli.execute(
            FakeClient(),
            self.command(
                "--dry-run", "partition", "modify", "/dev/test", "1", "--type", "8300"
            ),
        )
        self.assertEqual(result["request"]["label"], "keep-name")

    def test_missing_device_is_rejected(self):
        with self.assertRaises(cli.CLIError):
            cli.execute(
                FakeClient(),
                self.command("--dry-run", "partition", "table", "/dev/unknown", "gpt"),
            )

    def test_full_restore_cannot_be_mislabelled_as_boot_only(self):
        with self.assertRaises(cli.CLIError):
            cli.execute(
                FakeClient(),
                self.command(
                    "--dry-run",
                    "backup",
                    "restore",
                    "/dev/testboot0",
                    "backup-id",
                    "--full",
                ),
            )

    def test_image_dry_run_does_not_stage_input(self):
        with patch.object(cli, "upload", side_effect=AssertionError("must not stage")):
            result = cli.execute(
                FakeClient(),
                self.command(
                    "--dry-run", "backup", "restore-image", "/dev/test", "missing.img"
                ),
            )
        self.assertEqual(result["input"], "missing.img")

    def test_hex_write_uses_original_hash_and_preview(self):
        client = FakeClient()
        with contextlib.redirect_stderr(io.StringIO()) as output:
            cli.execute(
                client,
                self.command(
                    "--no-wait",
                    "hex",
                    "write",
                    "/dev/testboot0",
                    "--offset",
                    "3MiB",
                    "--data",
                    "01 02 ff",
                ),
            )
        request = next(args for method, args in client.calls if method == "submit")
        self.assertEqual(request["offset"], 3145728)
        self.assertEqual(request["expected_sha256"], "before-hash")
        self.assertIn("新值：0102ff", output.getvalue())

    def test_hex_write_cap_and_export_remaining_region(self):
        with self.assertRaises(cli.CLIError):
            cli.execute(
                FakeClient(),
                self.command(
                    "--dry-run", "hex", "write", "/dev/test", "--data", "00" * 65537
                ),
            )
        result = cli.execute(
            FakeClient(),
            self.command(
                "--dry-run",
                "hex",
                "export",
                "/dev/testboot0",
                "--offset",
                "3MiB",
                "--output",
                "boot.bin",
            ),
        )
        self.assertEqual(result["request"]["length"], 1024**2)

    def test_gzip_restore_requires_uncompressed_size(self):
        with self.assertRaises(cli.CLIError):
            cli.execute(
                FakeClient(),
                self.command(
                    "--dry-run",
                    "backup",
                    "restore-image",
                    "/dev/test",
                    "data.img.gz",
                    "--gzip",
                ),
            )

    def test_failed_job_has_non_success_result(self):
        client = FakeClient()
        client.rpc = lambda *args: {
            "id": "a",
            "state": "failed",
            "error": "system disk protected",
            "progress": 0,
        }
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(cli.CLIError):
            cli.wait_job(client, "a", 0)

    def test_permission_and_destructive_dry_run_gate(self):
        with patch.object(
            os, "geteuid", return_value=1000, create=True
        ), contextlib.redirect_stderr(io.StringIO()), patch.object(
            cli.Client, "rpc", side_effect=AssertionError("no connection")
        ):
            self.assertEqual(cli.main(["devices"]), 1)
        with patch.object(
            os, "geteuid", return_value=0, create=True
        ), contextlib.redirect_stderr(io.StringIO()), patch.object(
            cli.Client, "rpc", side_effect=AssertionError("no write")
        ):
            self.assertEqual(cli.main(["--dry-run", "backup", "delete", "a"]), 1)


class FakeConnection:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def makefile(self, mode):
        return io.BytesIO(self.data)


class CLIStreams(unittest.TestCase):
    def stream(self, data, declared=None, trailer=None):
        metadata = {"ok": True, "length": len(data) if declared is None else declared}
        return (
            json.dumps(metadata).encode()
            + b"\n"
            + struct.pack("!I", len(data))
            + data
            + struct.pack("!I", 0)
            + json.dumps(trailer or {"ok": True}).encode()
            + b"\n"
        )

    def receive(self, data, destination, **kwargs):
        client = cli.Client("test")
        with patch.object(
            client, "connect", return_value=FakeConnection(data)
        ), contextlib.redirect_stderr(io.StringIO()):
            return client.stream("token", destination, **kwargs)

    def test_atomic_success_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "data.bin"
            result = self.receive(self.stream(b"test bytes"), target)
            self.assertEqual(target.read_bytes(), b"test bytes")
            self.assertEqual(
                result["sha256"], hashlib.sha256(b"test bytes").hexdigest()
            )
            with self.assertRaises(cli.CLIError):
                self.receive(self.stream(b"replace"), target)
            self.assertEqual(target.read_bytes(), b"test bytes")

    def test_failed_trailer_length_and_connection_leave_original_untouched(self):
        invalid = [
            self.stream(b"partial", trailer={"ok": False, "error": "device unplugged"}),
            self.stream(b"partial", declared=100),
            self.stream(b"partial")[:-15],
            b'{"ok":true}\n' + struct.pack("!I", cli.CHUNK + 1),
        ]
        for data in invalid:
            with self.subTest(data=data[:20]), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "existing"
                target.write_bytes(b"keep")
                with self.assertRaises(cli.CLIError):
                    self.receive(data, target, overwrite=True)
                self.assertEqual(target.read_bytes(), b"keep")
                self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_source_digest_mismatch_never_publishes_final_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "image.bin"
            client = cli.Client("test")
            with patch.object(
                client, "connect", return_value=FakeConnection(self.stream(b"tampered"))
            ), patch.object(
                cli, "wait_job", return_value={"result": {"sha256": "0" * 64}}
            ), self.assertRaises(
                cli.CLIError
            ):
                client.stream("token", target, job_id="job")
            self.assertFalse(target.exists())
            self.assertFalse(list(Path(folder).iterdir()))


if __name__ == "__main__":
    unittest.main()
