[简体中文](README.md) | [English](README_en.md)

# eMMC Studio

局域网 eMMC 磁盘管理工作台，通过浏览器管理 eMMC 用户区、BOOT0/BOOT1、分区和 USB 存储。React + TypeScript + Vite 前端，Flask + Waitress 后端；普通用户提供网页，独立 root 工作进程执行磁盘操作。

![工作空间](docs/images/overview-dark.png)

## 部署要求

- Debian 12/13、Ubuntu 或兼容 Armbian，使用 systemd 与 apt；建议至少 1 GiB 内存。
- root/sudo 权限，可用的 80 端口，设备能够访问 GitHub 和系统软件源。
- 内核已经识别存储设备；先用 `lsblk` 确认 eMMC、系统盘和 USB。网页不能替代内核驱动。
- 基础工具：curl、ca-certificates、python3。安装方法：

```sh
sudo apt-get update
sudo apt-get install -y curl ca-certificates python3
```

## 方法一：脚本一键部署（推荐）

发布包由 GitHub Actions 构建，设备**不需要 Node.js，不在设备上编译前端**。脚本下载预构建包，核对 SHA-256，检查归档路径，安装依赖与三个开机自启服务（Web、磁盘工作进程与独立升级服务）。

在设备 SSH 或串口终端执行：

```sh
curl -fL --proto '=https' \
  https://raw.githubusercontent.com/JasonYANG170/eMMC-Studio/main/install.sh \
  -o /tmp/emmc-studio-install.sh
sudo sh /tmp/emmc-studio-install.sh
```

## 方法二：手动安装发布包

从 [Releases](https://github.com/JasonYANG170/eMMC-Studio/releases) 下载 `eMMC-Studio.tar.gz` 与 `SHA256SUMS`，复制到设备同一目录：

```sh
sha256sum -c SHA256SUMS
tar -xzf eMMC-Studio.tar.gz
cd eMMC-Studio
sudo sh deploy/install.sh
```

检查环境用 `sudo sh deploy/install.sh --check`。离线且已安装依赖时，可用 `sudo sh deploy/install.sh --skip-apt`；仍会检查 Flask/Waitress 和磁盘工具，缺少依赖时退出。

## 方法三：电脑构建源码，再部署到设备

电脑需要 Git、**Node.js 22.12+**、**Python 3.11+**。Windows/macOS/Linux 均可构建，目标运行环境必须是 Linux。

```sh
git clone https://github.com/JasonYANG170/eMMC-Studio.git
cd eMMC-Studio
npm ci
npm run build
npm run test:frontend
python scripts/package_release.py
```

Windows 可用 `py -3` 替代 `python`。产物是 `release/eMMC-Studio.tar.gz` 和 `release/SHA256SUMS`，不要复制电脑上的 node_modules 或本地运行状态。

```sh
scp release/eMMC-Studio.tar.gz release/SHA256SUMS user@设备IP:/tmp/
ssh user@设备IP
cd /tmp
sha256sum -c SHA256SUMS
tar -xzf eMMC-Studio.tar.gz
cd eMMC-Studio
sudo sh deploy/install.sh
```

也可直接复制构建后的 `backend/`、`dist/`、`deploy/`、`README.md`、`VERSION`，再执行安装脚本。仅下载源码尚未构建时缺少 dist，不能直接安装。

## 首次登录

1. 安装终端显示**一次性管理员设置码**，保存本次输出，不要公开。
2. 用 `hostname -I` 查看设备地址，浏览器打开 `http://设备IP/`。
3. 输入设置码，创建 8–128 字符管理员密码，默认用户名 `emmc-admin`。
4. 登录后在“磁盘详情”核对型号、容量、CID、系统保护及 BOOT 状态。

### 卸载

```sh
sudo sh /opt/emmc-studio/deploy/uninstall.sh
```

停止并移除 systemd 服务，**保留程序、管理员和所有备份数据**。永久删除数据需要管理员另行处理。


