"""Strict, signed application packages. The trust anchor is shipped with the app."""

import hashlib
import gzip
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAlL/RTe5u+ANVX9rsAaGmn1YJU3iEMFTWz1TpWcvEGs0=
-----END PUBLIC KEY-----
"""
MAX_PACKAGE = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
REQUIRED = {
    "VERSION",
    "backend/web.py",
    "backend/worker.py",
    "backend/cli.py",
    "backend/updater.py",
    "backend/update_package.py",
    "deploy/install.sh",
    "dist/index.html",
}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("版本号无效")
    return tuple(map(int, value.split(".")))


def verify_signature(manifest, signature):
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        for name, data in (
            ("key", PUBLIC_KEY),
            ("manifest", manifest),
            ("signature", signature),
        ):
            (folder / name).write_bytes(data)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(folder / "key"),
                "-rawin",
                "-in",
                str(folder / "manifest"),
                "-sigfile",
                str(folder / "signature"),
            ],
            capture_output=True,
            timeout=15,
        )
        if result.returncode:
            raise ValueError("升级包签名验证失败：仅支持官方签名升级包")


def unpack(package, destination, current, reinstall=False):
    """Verify before extracting any executable. Never use tar.extractall."""
    package, destination = Path(package), Path(destination)
    if not 0 < package.stat().st_size <= MAX_PACKAGE:
        raise ValueError("升级包大小必须在 1–128 MiB 范围内")
    destination.mkdir(parents=True, exist_ok=True)

    # Parse only ordinary fixed-name outer headers. Generic tar readers may allocate
    # huge unsigned PAX metadata or seek through a compression bomb before verification.
    def header(source, name, limit, exact=False):
        try:
            member = tarfile.TarInfo.frombuf(source.read(512), "utf-8", "strict")
        except (tarfile.HeaderError, UnicodeError) as error:
            raise ValueError("升级包头无效") from error
        if member.name != name or not member.isfile():
            raise ValueError("升级包文件清单无效")
        if not 0 < member.size <= limit or (exact and member.size != limit):
            raise ValueError("升级包超出大小限制")
        return member.size

    def content(source, size):
        data = source.read(size)
        if len(data) != size:
            raise ValueError("升级包不完整")
        return data

    def padding(source, size):
        if any(content(source, (-size) % 512)):
            raise ValueError("升级包填充无效")

    with gzip.open(package, "rb") as source:
        count = header(source, "manifest.json", 16384)
        raw = content(source, count)
        padding(source, count)
        count = header(source, "manifest.sig", 64, exact=True)
        signature = content(source, count)
        padding(source, count)
        verify_signature(raw, signature)
        meta = json.loads(raw)
        if meta.get("schema") != 1 or meta.get("platform") != "linux-systemd-debian":
            raise ValueError("升级包平台或格式不兼容")
        target = version(meta.get("version"))
        if target < version(current) or (target == version(current) and not reinstall):
            raise ValueError("版本没有更新；同版本需要明确选择重新安装，不支持降级")
        if version(current) < version(meta.get("minimum_version")):
            raise ValueError("当前版本过旧，请先使用一键部署脚本升级")
        payload = destination / "payload.tar.gz"
        digest = hashlib.sha256()
        count = header(source, "payload.tar.gz", MAX_PACKAGE)
        remaining = count
        with payload.open("wb") as output:
            while remaining:
                chunk = content(source, min(remaining, 1024 * 1024))
                remaining -= len(chunk)
                digest.update(chunk)
                output.write(chunk)
        padding(source, count)
        trailer = source.read(65537)
        if len(trailer) > 65536 or any(trailer):
            raise ValueError("升级包包含多余内容")
        if digest.hexdigest() != meta.get(
            "sha256"
        ) or payload.stat().st_size != meta.get("size"):
            raise ValueError("升级包内容校验失败")
    app = destination / "app"
    app.mkdir()
    with tarfile.open(payload, "r:gz") as archive:
        seen, total = set(), 0
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or len(member.name) > 512
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or not member.name.startswith("eMMC-Studio/")
                or member.name in seen
            ):
                raise ValueError("程序包包含不安全或重复的路径")
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED or len(seen) > 4096:
                raise ValueError("程序包解压后超出限制")
            relative = str(path.relative_to("eMMC-Studio"))
            if relative not in {"README.md", "README_en.md", "VERSION"} and path.parts[
                1
            ] not in {
                "backend",
                "deploy",
                "docs",
                "dist",
            }:
                raise ValueError("程序包包含未允许的目录")
            output = app / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, output.open(
                "wb"
            ) as target_file:
                while chunk := source.read(1024 * 1024):
                    target_file.write(chunk)
            output.chmod(0o755 if output.suffix == ".sh" else 0o644)
        if not REQUIRED.issubset({p.removeprefix("eMMC-Studio/") for p in seen}):
            raise ValueError("程序包缺少必要文件")
    if (app / "VERSION").read_text().strip() != meta["version"]:
        raise ValueError("程序版本与签名清单不一致")
    return meta, app
