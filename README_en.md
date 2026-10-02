[简体中文](README.md) | [English](README_en.md)

# eMMC Studio

A Chinese-language eMMC disk management workspace for the local network. Manage the eMMC user area, BOOT0/BOOT1, partitions, and USB storage in a browser. The frontend uses React, TypeScript, and Vite; the backend uses Flask and Waitress. An unprivileged user serves the web interface, while a separate root worker performs disk operations.

Listens on **0.0.0.0:80** by default. Open `http://<device-IP>/`. Supports mobile browsers and follows the system light/dark theme.

Serial and SSH command-line access is available from version 1.1.0: `sudo emmc-studio --help`. See the [CLI guide](docs/CLI.md). The CLI and web interface share disk protection rules and task records.

![Workspace](docs/images/overview-dark.png)

## Features

| Section | Pages and capabilities |
| ---------- | ----------------------------------------------------------------------------------------------- |
| Devices and disks | CPU, memory, temperature, disk, and network dashboards; disk overview; identifiers, CID manufacturer, EXT_CSD, lifetime ranges, and transfer protocols |
| Data operations | GPT/MBR management, formatting, offline ext4 resizing with drag previews; file management; HEX/ASCII sector editing; cloning and recovery; backup library |
| Maintenance and settings | Persistent tasks, progress, and cancellation; separate cache cleanup; password and theme settings |

- The system SD card cannot be selected as a write, format, or recovery target. eMMC is identified by CID and device topology rather than a fixed `mmcblk2` name.
- The user area and both BOOT areas are displayed separately, each with its own address space. Software read-only protection is restored after BOOT writes complete or fail.
- Range, area, and complete backups can be **streamed directly to your computer**, without first staging an image on the SD card. They can also be saved to SD/USB storage.
- Supports ext4, FAT32, exFAT, and NTFS. Resizing supports ext4 only, does not move partition start offsets, and does not resize extended MBR layouts.
- Text editing is limited to 2 MiB; each byte-edit operation is limited to 64 KiB. Areas are read on demand, with 256 B previews per page and direct page navigation.
- Complete backups include area images, metadata, and SHA-256 checksums. Capacity is checked before recovery, followed by read-back verification.
- Passwords contain 8–128 characters and are stored as scrypt hashes with random salts. Uses HttpOnly/SameSite cookies, CSRF protection, and login rate limiting.

## Deployment requirements

- Debian 12/13, Ubuntu, or compatible Armbian using systemd and apt. At least 1 GiB of RAM is recommended.
- Root/sudo access, an available port 80, and access to GitHub and system package repositories.
- The kernel must already recognize the storage devices. Use `lsblk` to identify eMMC, the system disk, and USB storage first. The web interface does not replace kernel drivers.
- Basic tools: curl, ca-certificates, and python3. Install them with:

```sh
sudo apt-get update
sudo apt-get install -y curl ca-certificates python3
```

**Installation itself does not partition, format, or write to eMMC.** Formatting, cloning, recovery, and byte saves in the web interface overwrite the selected region. Check the target and range before submitting.

## Method 1: One-command deployment (recommended)

Release packages are built by GitHub Actions. The device **does not need Node.js and does not compile the frontend**. The script downloads a prebuilt package, verifies SHA-256, checks archive paths, and installs dependencies and two services enabled at boot.

Run in an SSH or serial terminal on the device:

```sh
curl -fL --proto '=https' \
  https://raw.githubusercontent.com/JasonYANG170/eMMC-Studio/main/install.sh \
  -o /tmp/emmc-studio-install.sh
sudo sh /tmp/emmc-studio-install.sh
```

Install a specific version:

```sh
sudo sh /tmp/emmc-studio-install.sh --version v1.0.0
```

Download and verify only, without installing:

```sh
sh /tmp/emmc-studio-install.sh --version v1.0.0 --download-only "$HOME/emmc-studio-package"
```

Check only the package, system environment, task state, and port:

```sh
sudo sh /tmp/emmc-studio-install.sh --check
```

| Option | Description |
| --------------------- | ------------------------------------ |
| `--version v1.0.0` | Install the specified release; defaults to the latest stable release |
| `--download-only DIR` | Download the verified package and manifest without changing services |
| `--check` | Download, verify, and perform predeployment checks only |
| `--help` | Show usage |

If a release package is not available yet, wait for [Actions](https://github.com/JasonYANG170/eMMC-Studio/actions) to finish or deploy from source. SHA-256 verifies download integrity; trust in the publisher still relies on this repository and HTTPS.

## Method 2: Manually install a release package

Download `eMMC-Studio.tar.gz` and `SHA256SUMS` from [Releases](https://github.com/JasonYANG170/eMMC-Studio/releases), then copy them into the same directory on the device:

```sh
sha256sum -c SHA256SUMS
tar -xzf eMMC-Studio.tar.gz
cd eMMC-Studio
sudo sh deploy/install.sh
```

Use `sudo sh deploy/install.sh --check` to check the environment. For an offline device with dependencies already installed, use `sudo sh deploy/install.sh --skip-apt`. Flask/Waitress and disk utilities are still checked, and installation exits if dependencies are missing.

## Method 3: Build on a computer, then deploy to the device

The build computer needs Git, **Node.js 22.12+**, and**Python 3.11+**. Windows, macOS, and Linux can build the project; the target runtime must be Linux.

```sh
git clone https://github.com/JasonYANG170/eMMC-Studio.git
cd eMMC-Studio
npm ci
npm run build
npm run test:frontend
python scripts/package_release.py
```

On Windows, `py -3` can replace `python`. Outputs are `release/eMMC-Studio.tar.gz` and `release/SHA256SUMS`. Do not copy the computer's node_modules or local runtime state.

```sh
scp release/eMMC-Studio.tar.gz release/SHA256SUMS user@设备IP:/tmp/
ssh user@设备IP
cd /tmp
sha256sum -c SHA256SUMS
tar -xzf eMMC-Studio.tar.gz
cd eMMC-Studio
sudo sh deploy/install.sh
```

Alternatively, copy the built `backend/`, `dist/`, `deploy/`, `README.md`, and `VERSION`, then run the installer. A source download without a build lacks dist and cannot be installed directly.

## First login

1. The installation terminal displays a **one-time administrator setup code**. Save this output and do not publish it.
2. Run `hostname -I` to find the device address, then open `http://<device-IP>/` in a browser.
3. Enter the setup code and create an administrator password of 8–128 characters. The default username is `emmc-admin`.
4. After login, check the model, capacity, CID, system protection, and BOOT status under Disk details.

There is no built-in default password. Only a digest of the setup code is stored, and the code expires after initialization. Updates preserve the existing administrator. HTTP on port 80 is intended for a trusted LAN; use an HTTPS reverse proxy or VPN across untrusted networks.

## Updates and maintenance

### Updating

Run the one-command script again or install a new release package. Administrator settings, backups, snapshots, and task records are preserved. Updates are refused while tasks are queued or running; retry when they finish.

The installer stages the new application, stops accepting tasks and checks again, then replaces the application and starts services. On failure it attempts to restore the old application and services. After success, the old application remains at `/opt/emmc-studio.previous.<timestamp>.<pid>` for administrator review and cleanup. This copy does not include state data under `/var/lib`.

### Paths and logs

| Path | Contents |
| ------------------------------- | ------------------------------------ |
| `/opt/emmc-studio/backend` | Python service source |
| `/opt/emmc-studio/dist` | Built web interface |
| `/opt/emmc-studio/deploy` | Installation, checking, initialization, and removal scripts |
| `/var/lib/emmc-web` | Administrator hash, session keys, uploads, and history exports |
| `/var/lib/emmc-worker` | Backups, snapshots, and SQLite task records |
| `/run/emmc-worker/control.sock` | Restricted worker interface |

```sh
systemctl status emmc-worker emmc-web --no-pager
journalctl -u emmc-worker -u emmc-web -n 100 --no-pager
sudo systemctl restart emmc-worker emmc-web
```

Wait for tasks to finish before restarting manually. A restart marks unfinished tasks as interrupted and does not automatically resume writes. Cache cleanup does not delete regular backups or accounts; deleting a snapshot removes its corresponding rollback copy.

### Uninstalling

```sh
sudo sh /opt/emmc-studio/deploy/uninstall.sh
```

Stops and removes the systemd services while **preserving the application, administrator, and all backup data**. Permanent data deletion requires a separate administrator action.

## Troubleshooting

- **Web interface unavailable:** Check the device IP, network, TCP port 80 firewall rules, and service logs. The installer refuses to continue if nginx, Apache, or another service already occupies port 80.
- **eMMC not found:** Check lsblk, dmesg, and MMC drivers. This project does not export multiple disks through USB Gadget or modify OTG configuration.
- **BOOT file editing unavailable:** BOOT0/BOOT1 normally lack a conventional filesystem; use sector editing. Software cannot disable permanent hardware protection, and this tool does not expose permanent configuration operations.
- **Offset 3 MiB and length 4 MiB exceeds the range:** Length is measured from the offset. Starting at 3 MiB in a 4 MiB area leaves only 1 MiB. To read the whole area, use offset 0 and length 4 MiB, or select the entire area.
- **Lifetime 0x01:** A/B indicate an estimated 0–10% lifetime consumption; PRE_EOL 0x01 indicates spare-block consumption below 80%. These are ranges, not precise remaining-life figures, and do not identify the NAND die model or MLC/TLC type.
- **No download:** Use Chrome, Edge, or Firefox. Some embedded browsers cancel attachment downloads. Interrupted streaming downloads must be restarted; resumable downloads are not supported.
- **Forgotten password:** From a root terminal, move `/var/lib/emmc-web/auth.json` to a secure backup location, then rerun the installer to generate a one-time setup code. Do not publish password files or session keys. Existing backups and task records are preserved.

## Development and testing

Use `npm run dev` for local previews. Copy `.env.example` to `.env.local` and set `EMMC_DEV_API` to your backend; the default proxy target is `http://127.0.0.1:80`. When the development proxy connects to a real backend, web operations still affect the disks managed by that backend.

```text
src/                  React 页面、主题、区域图与字节编辑器
public/               图标和主题初始化
backend/              Web API、工作进程、策略与流式传输
deploy/               systemd、本地安装、初始化、检查和卸载
scripts/              前端测试与发布打包
tests/                策略、认证、缓存、临时 loop 与流式测试
docs/                 架构、验证范围、发布说明和截图
.github/workflows/    CI 构建验证与 Release
install.sh            一键安装入口
```

```sh
npm run build
npm run test:frontend
python tests/test_core.py
python tests/test_deploy.py
npm run format
python -m pip install -r requirements-dev.txt
python -m black backend deploy scripts tests
```

After installing Linux development dependencies, run `test_auth_linux.py`, `test_cache_linux.py`, and `test_extcsd_lock.py` separately. The following integration tests require root, loop devices, and mounting support. They operate only on temporary images they create and do not overwrite MMC storage:

```sh
sudo python3 tests/integration.py
sudo python3 tests/test_stream_linux.py
```

See [docs/VALIDATION.md](docs/VALIDATION.md) for validation coverage and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for permissions and workflows. For a release, update VERSION and push the corresponding `v<version>` tag. After validation, Actions produces the installation package and SHA-256 manifest.
