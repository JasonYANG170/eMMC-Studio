"""Wrap a prebuilt deployment archive in an Ed25519-signed offline update package."""

import argparse
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True, help="CI signing secret PEM file")
    parser.add_argument("--output", default="release")
    args = parser.parse_args()
    folder = Path(args.output)
    payload = folder / "eMMC-Studio.tar.gz"
    meta = {
        "schema": 1,
        "platform": "linux-systemd-debian",
        "version": Path("VERSION").read_text().strip(),
        "minimum_version": "1.1.0",
        "size": payload.stat().st_size,
        "sha256": hashlib.file_digest(payload.open("rb"), "sha256").hexdigest(),
    }
    manifest = folder / "update-manifest.json"
    manifest.write_text(
        json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    signature = folder / "update-manifest.sig"
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            args.key,
            "-rawin",
            "-in",
            str(manifest),
            "-out",
            str(signature),
        ],
        check=True,
    )
    # Fail CI if a misconfigured signing secret does not match the shipped trust anchor.
    import sys

    sys.path.insert(0, str(Path("backend").resolve()))
    from update_package import verify_signature

    verify_signature(manifest.read_bytes(), signature.read_bytes())
    with tarfile.open(folder / "eMMC-Studio-update.tar.gz", "w:gz") as archive:
        for file, name in (
            (manifest, "manifest.json"),
            (signature, "manifest.sig"),
            (payload, "payload.tar.gz"),
        ):
            info = archive.gettarinfo(str(file), name)
            info.uid = info.gid = info.mtime = 0
            info.mode = 0o644
            with file.open("rb") as source:
                archive.addfile(info, source)
    print("Created verified signed eMMC-Studio-update.tar.gz")


if __name__ == "__main__":
    main()
