# 串口与 SSH 命令行

从 eMMC Studio 1.1.0 开始，安装包同时提供 `emmc-studio`。在设备的串口终端或 SSH 中登录 Linux 后运行：

```sh
sudo emmc-studio --help
sudo emmc-studio devices
sudo emmc-studio system
```

使用 Linux 管理员权限，不需要网页账号或会话；普通用户使用 `sudo`，root 可以省略。CLI 通过受限 Unix socket 连接现有 `emmc-worker`，共用系统盘保护、设备身份核验、任务互斥、文件路径限制、BOOT 临时解除/恢复只读、原始字节及分区表快照。网页服务关闭时 CLI 仍可使用，工作进程必须运行。

**写入命令会执行指定操作，不要求再次输入目标标识。请先运行 `devices` 查看实际设备路径，不要照抄下面的设备编号。** SD 系统盘禁止破坏性修改，CLI 没有绕过保护的 `--force`。所有文件参数都是设备本机路径，串口本身不会自动把电脑上的文件传到设备；电脑文件可先通过 SCP、U 盘或网页上传。

## 参数、进度与后台任务

全局参数放在子命令前：

```sh
sudo emmc-studio --json devices
sudo emmc-studio --dry-run partition create /dev/mmcblk2 --start 1MiB --size 100MiB
sudo emmc-studio --no-wait backup create /dev/mmcblk2boot0
```

- `--json`：标准输出为 JSON，进度和目标提示写入标准错误，方便脚本处理。
- `--dry-run`：查看准备提交的存储任务参数，不提交任务、不暂存输入文件。只做 CLI 参数转换及设备发现，不等同于工作进程的完整容量、挂载和空间预检。任务取消、备份删除、任务/缓存清理不支持该参数，会拒绝执行。
- `--no-wait`：提交后台任务后立即返回 ID。默认等待任务结束并显示阶段、百分比及速度。
- `--socket PATH`：指定 Unix socket，通常无需修改。
- `--version`：查看应用版本；每层子命令都支持 `--help`。

裸数字表示字节；`KiB/MiB/GiB` 为 1024 进制，`KB/MB/GB` 为 1000 进制。支持 `1.5GiB` 等精确换算，必须转换为整数个字节。分区起点和大小需按 1 MiB 对齐。

普通后台任务中按 Ctrl+C 只退出等待，任务继续运行，可再次查询或取消；**流式导出必须保持 CLI 连接，Ctrl+C 会中断传输**。流式导出与 `--no-wait` 不能同时使用。返回码：0 成功，1 权限/连接/存储/任务失败，2 命令参数错误，130 Ctrl+C。

## 磁盘与分区

```sh
sudo emmc-studio info /dev/mmcblk2
sudo emmc-studio extcsd /dev/mmcblk2
sudo emmc-studio partition --help

# 以下命令会修改磁盘布局或内容。
sudo emmc-studio partition table /dev/mmcblk2 gpt
sudo emmc-studio partition create /dev/mmcblk2 --start 1MiB --size 100MiB
sudo emmc-studio partition modify /dev/mmcblk2 1 --label DATA
sudo emmc-studio partition format /dev/mmcblk2p1 ext4 --label DATA
sudo emmc-studio partition resize /dev/mmcblk2p1 --size 200MiB
sudo emmc-studio partition delete /dev/mmcblk2 1
```

分区表支持 `gpt/mbr`；格式化支持 `ext4/fat32/exfat/ntfs`。卷标沿用网页后端的最多 11 字符规则。`resize --size` 指新的分区总大小，只支持离线 ext4 调整，不移动分区起点。

`partition modify` 可用 `--type HEX_OR_GUID`，MBR 使用 `--bootable` / `--no-bootable`。省略名称或启动标志时保留原值。`info` 显示完整磁盘和区域原始信息，`extcsd` 输出设备寄存器报告。

## 分区内文件

```sh
sudo emmc-studio files ls /dev/mmcblk2p1 /
sudo emmc-studio files cat /dev/mmcblk2p1 config.txt
sudo emmc-studio files get /dev/mmcblk2p1 config.txt --output /root/config.txt
sudo emmc-studio files mkdir /dev/mmcblk2p1 documents
sudo emmc-studio files put /dev/mmcblk2p1 documents/data.bin --input /root/data.bin
sudo emmc-studio files text-put /dev/mmcblk2p1 config.txt --input /root/config.txt --overwrite
sudo emmc-studio files mv /dev/mmcblk2p1 documents/data.bin documents/new.bin
sudo emmc-studio files rm /dev/mmcblk2p1 documents/new.bin
```

浏览默认只读。明确调用写入子命令即进入该次操作的编辑模式，结束后卸载写挂载。`text-put` 限制 UTF-8 文本不超过 2 MiB，覆盖时核对原内容摘要；大文件用 `put/get`。文件路径由 worker 限制在选定分区内，拒绝路径越界和符号链接逃逸。

本机输入文件通过最多 256 KiB 的块流式暂存到上传目录，检查 SD 可用空间；完成后会留在上传缓存，后续可清理。直接输出的下载文件不经过网页下载缓存。

## 原始字节与 BOOT

```sh
sudo emmc-studio hex read /dev/mmcblk2boot0 --offset 0 --length 64B
sudo emmc-studio hex read /dev/mmcblk2boot0 --offset 3MiB --length 64KiB
sudo emmc-studio hex export /dev/mmcblk2boot0 --output /root/boot0.bin
sudo emmc-studio hex export /dev/mmcblk2boot0 --offset 3MiB --length 1MiB --output /root/boot0-tail.bin

# 写入会显示原值/新值，核对原摘要，保存快照并读回校验。
sudo emmc-studio hex write /dev/mmcblk2boot0 --offset 3MiB --data '01 02 ff'
sudo emmc-studio hex write /dev/mmcblk2boot0 --offset 3MiB --input /root/patch.bin
sudo emmc-studio hex undo /dev/mmcblk2boot0 SNAPSHOT_ID
```

十六进制预览和每次修改最多 64 KiB；完整读取使用 `hex export`，没有 64 KiB 的导出范围限制。省略导出长度时，从指定偏移导出到区域末尾。BOOT 软件只读由 worker 在写入期间临时解除，成功或失败后恢复。CLI 不提供 RPMB 密钥烧录或永久写保护操作。

流式输出先保存同目录临时文件；收到完整数据、成功结束帧并检查长度与可用源摘要后才生成最终文件。默认不覆盖已有文件，显式使用 `--overwrite` 才替换；失败时清除临时文件，保留原目标。拒绝把导出直接写到块设备、目录或符号链接。

## 克隆、备份与恢复

```sh
# USB 整盘到 eMMC；不会自动裁剪，源目标不可相同或重叠。
sudo emmc-studio clone /dev/sda /dev/mmcblk2

# 保存到 SD 备份库，或另一块 USB 文件系统分区。
sudo emmc-studio backup create /dev/mmcblk2 --full --gzip
sudo emmc-studio backup create /dev/mmcblk2 --full --usb /dev/sda1
sudo emmc-studio backup list

# 直接流式输出 tar/tar.gz；不会先在备份库创建一份大镜像。
sudo emmc-studio backup create /dev/mmcblk2 --full --gzip --output /root/emmc-full.tar.gz
sudo emmc-studio backup export BACKUP_ID --output /root/backup.tar
sudo emmc-studio backup import /root/emmc-full.tar.gz

# 恢复命令会覆盖目标。完整恢复必须选择用户区，含两个 BOOT 区。
sudo emmc-studio backup restore /dev/mmcblk2 BACKUP_ID --full
sudo emmc-studio backup restore /dev/mmcblk2boot0 BACKUP_ID
sudo emmc-studio backup restore-image /dev/mmcblk2 /root/user.img
sudo emmc-studio backup restore-image /dev/mmcblk2 user.img --usb /dev/sda1
sudo emmc-studio backup restore-image /dev/mmcblk2boot0 /root/boot0.img.gz --gzip --image-size 4MiB
sudo emmc-studio backup delete BACKUP_ID
```

完整备份包含用户区、BOOT0/BOOT1、容量和分区表、EXT_CSD 与 SHA-256。流式备份输出是包含区域原始镜像及 manifest 的 tar，`--gzip` 压缩 tar 传输。输出 `/root/...` 仍占用设备 SD 空间，可改为已经挂载的 USB 上的普通文件路径；串口命令不会把输出文件自动下载到电脑。

本机镜像恢复和备份包导入会先暂存文件，保证后台任务不依赖 CLI 保持连接；也可用 `restore-image --usb` 从另一 USB 分区读镜像，避免本机镜像暂存。压缩原始镜像需明确解压后的大小。完整备份包请先导入再用备份 ID 恢复，不把 tar 当原始镜像使用。普通 USB 整盘克隆不推断 BOOT 内容；USB 备份的删除仍需在该 USB 的文件管理中执行。

## 任务、缓存与快照

```sh
sudo emmc-studio jobs list
sudo emmc-studio jobs show JOB_ID
sudo emmc-studio jobs wait JOB_ID
sudo emmc-studio jobs cancel JOB_ID
sudo emmc-studio jobs clear JOB_ID
sudo emmc-studio jobs clear --all

sudo emmc-studio cache list
sudo emmc-studio cache clear uploads UPLOAD_ID
sudo emmc-studio cache clear downloads --all
sudo emmc-studio cache clear snapshots SNAPSHOT_ID
sudo emmc-studio snapshots list
sudo emmc-studio snapshots restore-table /dev/mmcblk2 SNAPSHOT_ID
```

任务和缓存清理共用网页的锁及版本核验；运行中的任务、活跃传输和受保护缓存不会被强制清理。分区表回退和字节回退需使用对应目标的快照，不能跨设备使用。

## 安装与故障排查

升级到 1.1.0 或更高版本即可安装 CLI，命令入口为 `/usr/local/bin/emmc-studio`，代码在 `/opt/emmc-studio/backend/cli.py`。

```sh
curl -fL https://raw.githubusercontent.com/JasonYANG170/eMMC-Studio/main/install.sh -o /tmp/emmc-studio-install.sh
sudo sh /tmp/emmc-studio-install.sh
sudo emmc-studio --version
sudo systemctl status emmc-worker
sudo journalctl -u emmc-worker -b
```

使用原有系统部署方法即可，无需另装 Python 包。命令不存在时检查安装版本和 `/usr/local/bin` 是否在 PATH 中；socket 连接失败时检查 worker 服务。CLI 不重置网页密码、不启动第二个工作进程，不自行绕过 disk identity、挂载状态或 BOOT 保护。

## 独立应用升级

串口或 SSH 可使用 `sudo emmc-studio upgrade check` 检测版本、`upgrade online` 在线升级、`upgrade import /path/eMMC-Studio-update.tar.gz` 离线升级、`upgrade status` 查看状态。支持 `--no-wait`、`--json` 和 `--dry-run`。同版本需在子命令后显式添加 `--reinstall`。详见 [应用升级教程](UPGRADE.md)。
