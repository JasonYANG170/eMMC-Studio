# 应用升级

eMMC Studio 1.2.0 起提供独立应用升级服务，Web 与串口/SSH CLI 使用同一套升级流程。只更新 `/opt/emmc-studio` 的应用程序、CLI 启动器及服务配置，不修改固件、分区表、eMMC 用户区或 BOOT 区。

## Web 操作

管理员登录后，进入 **维护与设置 → 应用升级**。

- **在线升级**：点击“检查更新”，查看最新稳定版本，点击“下载并升级”。设备必须能够通过 HTTPS 访问 GitHub API 和 Release 下载域名。
- **本地导入**：在电脑上下载官方 Release 的 `eMMC-Studio-update.tar.gz`，选择此文件并点击“导入并升级”。设备无需联网，签名在本地验证。普通部署包 `eMMC-Studio.tar.gz` 不能用于此入口。
- 同版本默认不安装。如需修复安装，勾选“允许重新安装同版本”。不支持降级。

页面每两秒读取独立升级状态。服务重启期间会暂时断开，恢复后继续显示结果；完成后点击“刷新页面加载新版”。关闭浏览器不会取消已提交的升级。

## 串口 / SSH CLI

在设备 Linux 终端执行：

```sh
sudo emmc-studio upgrade check
sudo emmc-studio upgrade online
sudo emmc-studio upgrade import /path/eMMC-Studio-update.tar.gz
sudo emmc-studio upgrade status
sudo emmc-studio --no-wait upgrade online
sudo emmc-studio --json upgrade status
# 明确重新安装同版本
sudo emmc-studio upgrade import /path/eMMC-Studio-update.tar.gz --reinstall
```

默认等待并显示阶段进度。按 Ctrl+C 只退出等待，后台升级继续；可重新执行 `upgrade status` 查看。`--dry-run` 不上传或执行升级。

## 旧版初始化

1.0.x / 1.1.x 尚无升级服务，需要先使用 [一键部署教程](../README.md) 或解压部署包后运行 `sudo sh deploy/install.sh`，安装 1.2.0 或以上版本。此后可以独立在线/离线升级。

## 校验、状态与恢复

- 升级包使用 Ed25519 签名，内含版本、兼容平台、最小版本、程序包长度和 SHA-256。固定可信公钥随安装程序提供，不信任上传包自带的公钥。
- 仅支持 Linux systemd Debian/Ubuntu/Armbian，当前程序为架构无关的 Python 与预构建网页；不在设备上运行前端构建工具。新增系统依赖的版本需要先使用部署脚本安装依赖。
- 上传包最大 128 MiB；暂存区和 `/opt` 各需至少 768 MiB 可用空间。下载、复制、解包按块处理。
- 安装前原子关闭磁盘任务提交入口，发现任何等待中/运行中任务或占用时拒绝升级。安装时短暂重启 Web 和存储 worker，升级服务自身保持运行。
- 管理员密码、会话密钥、备份及历史任务留在 `/var/lib`。安装器在启动或健康检查失败时尝试恢复旧版程序和服务配置；成功后旧版保留在 `/opt/emmc-studio.previous.*`。
- 状态：`/var/lib/emmc-updater/status.json`；安装日志：`/var/lib/emmc-updater/install.log`。`sudo journalctl -u emmc-updater` 查看升级服务日志。
- 若断电或升级服务意外停止，下次启动将记录为中断，不自动继续安装。检查 `upgrade status`、三个服务和当前版本；必要时用部署包重新安装。断电不能保证 shell 回滚已完成。
- `sudo systemctl status emmc-updater emmc-worker emmc-web` 检查服务。卸载脚本停止三个服务，保留程序和状态。

## CI 发布与签名密钥

推送与 `VERSION` 相符的 `vX.Y.Z` 标签触发 `.github/workflows/release.yml`。通过前后端检查和 loop 设备集成测试后，发布普通部署包、SHA256SUMS、独立升级包及签名清单。

仓库 Actions secret `EMMC_UPDATE_SIGNING_KEY` 保存 Ed25519 PEM 私钥，只在标签发布作业使用。`scripts/package_update.py --key <私钥文件>` 生成升级包并核对公钥。私钥不进入仓库、部署包或设备；不要更换密钥，除非先安排可信公钥迁移。
