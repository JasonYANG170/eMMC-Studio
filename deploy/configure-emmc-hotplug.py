#!/usr/bin/env python3
"""Enable polling only for a non-system, 8-bit eMMC reader controller."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

HIGH_SPEED_PROPERTIES = (
    "mmc-hs400-enhanced-strobe",
    "mmc-hs400-1_8v",
    "mmc-hs400-1_2v",
    "mmc-hs200-1_8v",
    "mmc-hs200-1_2v",
    "mmc-ddr-1_8v",
    "mmc-ddr-1_2v",
    "mmc-ddr-3_3v",
)


def configure_reader_dtb(stage, node, compatible=False):
    """Polling preserves speed unless a compatibility trial is requested."""
    properties = subprocess.check_output(
        ["fdtget", "-p", str(stage), node], text=True
    ).splitlines()
    removed = (
        ("non-removable", *HIGH_SPEED_PROPERTIES) if compatible else ("non-removable",)
    )
    for property_name in removed:
        if property_name in properties:
            subprocess.run(
                ["fdtput", "-d", str(stage), node, property_name], check=True
            )
    added = (
        ("broken-cd", "cap-mmc-highspeed", "no-mmc-hs400")
        if compatible
        else ("broken-cd",)
    )
    for property_name in added:
        subprocess.run(["fdtput", str(stage), node, property_name], check=True)
    if compatible:
        for property_name, value in (
            ("max-frequency", 52000000),
            ("post-power-on-delay-ms", 200),
        ):
            subprocess.run(
                ["fdtput", "-t", "i", str(stage), node, property_name, str(value)],
                check=True,
            )
    properties = subprocess.check_output(
        ["fdtget", "-p", str(stage), node], text=True
    ).splitlines()
    assert "non-removable" not in properties and "broken-cd" in properties
    if compatible:
        assert not any(p in properties for p in HIGH_SPEED_PROPERTIES)
        assert (
            subprocess.check_output(
                ["fdtget", "-t", "i", str(stage), node, "max-frequency"], text=True
            ).strip()
            == "52000000"
        )


def configure(compatible=False):
    if os.geteuid() != 0:
        raise SystemExit("Run as root")
    jobs = Path("/var/lib/emmc-worker/jobs.sqlite")
    if jobs.exists():
        with sqlite3.connect("file:" + str(jobs) + "?mode=ro", uri=True) as db:
            if any(
                json.loads(row[0])["state"] in ("queued", "running")
                for row in db.execute("select data from jobs")
            ):
                raise SystemExit(
                    "Disk tasks are active; finish them before configuring hotplug"
                )
    candidates = []
    for host in Path("/sys/class/mmc_host").glob("*"):
        controller = host.resolve().parent.parent
        node = controller / "of_node"
        if (node / "bus-width").exists() and int.from_bytes(
            (node / "bus-width").read_bytes(), "big"
        ) == 8:
            candidates.append(controller)
    if len(candidates) != 1:
        raise SystemExit("Expected exactly one 8-bit eMMC reader controller")
    controller = candidates[0]
    for line in Path("/proc/1/mountinfo").read_text().splitlines():
        fields = line.split()
        device = Path("/sys/dev/block", fields[2]).resolve()
        if controller in device.parents:
            raise SystemExit(
                "eMMC is mounted; safely unmount it before configuring hotplug"
            )
    node = (
        "/"
        + (controller / "of_node")
        .resolve()
        .relative_to("/sys/firmware/devicetree/base")
        .as_posix()
    )
    env = Path("/boot/armbianEnv.txt")
    content = env.read_text()
    values = dict(
        line.split("=", 1)
        for line in content.splitlines()
        if "=" in line and not line.startswith("#")
    )
    fdtfile = values.get("fdtfile", "")
    if not fdtfile or ".." in Path(fdtfile).parts or Path(fdtfile).is_absolute():
        raise SystemExit("Cannot determine the active Armbian DTB safely")
    source = Path("/boot/dtb", fdtfile).resolve(strict=True)
    source.relative_to(Path("/boot").resolve())
    destination_name = str(Path(fdtfile).parent / "emmc-studio-hotplug.dtb")
    destination = Path("/boot/dtb", destination_name)
    backup = Path("/boot/emmc-studio-hotplug-backup-" + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    shutil.copy2(env, backup / "armbianEnv.txt")
    shutil.copy2(source, backup / "original.dtb")
    stage = destination.with_suffix(".dtb.new")
    shutil.copy2(source, stage)
    configure_reader_dtb(stage, node, compatible)
    subprocess.run(
        ["dtc", "-I", "dtb", "-O", "dtb", "-o", "/dev/null", str(stage)],
        check=True,
        stderr=subprocess.DEVNULL,
    )
    os.replace(stage, destination)
    lines = [line for line in content.splitlines() if not line.startswith("fdtfile=")]
    lines.append("fdtfile=" + destination_name)
    temporary = env.with_suffix(".hotplug-new")
    temporary.write_text("\n".join(lines) + "\n")
    shutil.copymode(env, temporary)
    os.replace(temporary, env)
    os.sync()
    print(
        json.dumps(
            dict(
                controller=controller.name,
                node=node,
                dtb=destination_name,
                rollback=str(backup / "armbianEnv.txt"),
                rollback_dtb=str(backup / "original.dtb"),
                compatible=compatible,
                reboot_required=True,
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compatible",
        action="store_true",
        help="Trial 52 MHz MMC high-speed mode; not a proven hotplug fix",
    )
    configure(parser.parse_args().compatible)
