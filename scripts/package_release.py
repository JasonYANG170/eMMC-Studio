"""Build a deployment archive from an explicit allowlist; never include runtime state."""

import argparse
import hashlib
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="release")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not (root / "dist/index.html").is_file():
        parser.error("Run npm ci and npm run build first")
    files = [root / "README.md", root / "VERSION"]
    files += sorted((root / "backend").glob("*.py"))
    files += sorted(
        p for p in (root / "deploy").iterdir() if p.suffix in {".sh", ".py", ".service"}
    )
    files += sorted(p for p in (root / "dist").rglob("*") if p.is_file())
    archive = output / "eMMC-Studio.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for path in files:
            if path.is_symlink():
                raise ValueError(f"Refusing symlink: {path}")
            info = package.gettarinfo(
                str(path), "eMMC-Studio/" + path.relative_to(root).as_posix()
            )
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = "root"
            info.mode = 0o755 if path.suffix == ".sh" else 0o644
            with path.open("rb") as content:
                package.addfile(info, content)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Created {archive.name} ({archive.stat().st_size:,} bytes) and SHA256SUMS")


if __name__ == "__main__":
    main()
