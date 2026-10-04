# Windows USB 直连

此功能为可选项，用于 Windows 上位机通过 USB 访问 eMMC Studio 的 HTTP API 和 SSH/CLI。
当前已在 NanoPi R28S / RK3528、Armbian vendor 6.1.172 与 Windows 上实测。

## 安装

在已安装 eMMC Studio 的设备上执行：

```bash
sudo bash deploy/install-usb-network.sh
```

通过 OTG 数据口连接电脑。Windows 应识别为 `Remote NDIS Compatible Device`，自动获取地址：

| 用途             | 地址                                              |
| ---------------- | ------------------------------------------------- |
| 设备 USB 地址    | `172.30.77.1/24`                                  |
| Windows USB 地址 | `172.30.77.2/24`，自动分配                        |
| 网页             | `http://172.30.77.1/`                             |
| HTTP API         | `http://172.30.77.1/api/v1`                       |
| SSH              | `ssh root@172.30.77.1`，使用设备现有 SSH 登录凭据 |

浏览器继续使用已有管理员账号登录。上位机需要遵守现有 Cookie、CSRF 和登录限制；
镜像下载使用现有流式接口，任务进度使用 SSE。USB 通道不提供默认网关或 DNS，避免改变电脑的互联网路由。

## 检查

网页的“克隆与恢复”和“设置”页提供 USB 模式切换按钮。
Host 模式用于 U 盘克隆与 USB 外设；Device 模式用于 Windows 上位机 USB 直连。
通过 USB 网页连接时禁止切换 Host，需先改用网页显示的以太网地址。
切换前必须结束任务并安全卸载 USB 存储；后端检查正在执行的任务、挂载和交换空间。
切换结果写入任务记录。Device 启用 USB 网卡服务的开机启动，Host 停用该服务的开机启动。

设备端：

```bash
systemctl status emmc-usb-network
journalctl -u emmc-usb-network --no-pager -n 30
ip -4 address show emmcusb0
cat /sys/class/udc/*/state
```

Windows PowerShell：

```powershell
Get-NetAdapter | Where-Object InterfaceDescription -Match 'Remote NDIS'
curl.exe http://172.30.77.1/api/v1/auth/status
ssh root@172.30.77.1
```

本机地址需避免与已有 VPN 或局域网网段冲突。当前脚本默认用于一台设备直连一台电脑。
本次实测连接速度为 USB 2.0 High-Speed；这代表协商速度，不代表镜像传输实测速率。

## 停用和卸载

从串口或以太网登录后执行以下命令，USB 连接会断开：

```bash
sudo systemctl disable --now emmc-usb-network
sudo rm -f /etc/systemd/system/emmc-usb-network.service
sudo rm -f /usr/local/lib/emmc-studio-usb/usb-network.py
sudo systemctl daemon-reload
```

恢复当前设备的 OTG Host 模式：

```bash
echo host | sudo tee /sys/kernel/debug/usb/fe500000.dwc3/mode
```

脚本在服务启动时切换 OTG 角色，不修改 DTB。它创建 USB RNDIS 网卡，不导出磁盘块设备。
使用 Linux Foundation 复合 Gadget VID/PID 进行本机开发验证；生产产品发布前应配置有权使用的 USB VID/PID。

实现参考：[Linux ConfigFS USB Gadget 文档](https://kernel.org/doc/html/next/usb/gadget_configfs.html)、
[Microsoft RNDIS 文档](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/remote-ndis--rndis-2)。
