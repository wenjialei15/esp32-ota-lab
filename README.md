# ESP32 OTA Lab

无需硬件的 ESP32 固件升级实验。ESP-IDF 编译出真实的 ESP32 镜像，Espressif QEMU 运行固件和引导程序，Python 本地服务接收遥测并按需下发候选镜像。

[打开 GitHub Pages 交互演示](https://wenjialei15.github.io/esp32-ota-lab/) · [端到端测试](https://github.com/wenjialei15/esp32-ota-lab/actions) · MIT

在线页面在浏览器中模拟实验过程。本地 QEMU 实验会执行真实的固件、Flash 分区、NVS 和 HTTP 请求。

## 本地运行

1. 安装并激活 [ESP-IDF v5.5.3](https://github.com/espressif/esp-idf/releases/tag/v5.5.3)。在已激活的终端里按 [Espressif QEMU 安装说明](https://docs.espressif.com/projects/esp-idf/en/v5.5.3/esp32/api-guides/tools/qemu.html) 安装 `qemu-xtensa`。安装后重新激活 ESP-IDF 环境，使 Espressif 版 `qemu-system-xtensa` 进入 PATH。
2. 克隆仓库，在已激活 ESP-IDF 的终端运行：

```bash
git clone https://github.com/wenjialei15/esp32-ota-lab.git
cd esp32-ota-lab
python -m ota_lab build
python -m ota_lab verify
```

主机服务只用 Python 标准库。默认在 `127.0.0.1:8765` 监听，虚拟机通过 QEMU 的用户态网关 `10.0.2.2` 访问。若端口已占用，在两个命令的子命令前传入相同的 `--port 8766`。若 QEMU 不在 PATH 中，可给 `verify` 或 `run` 传入 `--qemu` 和可执行文件路径。

Windows 上建议将 ESP-IDF、工具链和项目放在纯英文路径，以兼容 Xtensa 链接器。如果 QEMU 启动时报缺少 `libiconv-2.dll`，可把 Git for Windows 安装目录下的 `mingw64\bin` 加到当前终端的 PATH，再运行验证。

构建结果位于 `.build/`。端到端验证结束后，在 `.build/qemu.log` 查看完整串口输出。每次启动实验会从基线镜像创建一份临时 Flash；同一次实验内，OTA 重启和回滚共用这份 Flash。

## 验证顺序

| 场景 | 验证结果 |
| --- | --- |
| 启动 `1.0.0` | 从 `ota_0` 启动，遥测到达本地 HTTP 服务 |
| 服务断连 | 固件把读数写入 NVS，恢复后按序补传；服务端丢弃一次确认响应，重发的数据按设备和序号去重 |
| 镜像下载中断 | HTTP 提前结束，固件保留当前启动分区 |
| 正常升级至 `1.1.0` | 下载到 `ota_1`，重启自检通过并确认 |
| 下发 `1.2.0` | 候选在 `ota_0` 自检失败，引导程序回滚至已确认的 `1.1.0`，之后遥测序号继续递增 |

## 手动操作

```bash
python -m ota_lab run
```

另开终端访问 `http://127.0.0.1:8765/api/lab` 查看遥测、下载次数和当前服务状态。Windows PowerShell 示例：

```powershell
$lab = 'http://127.0.0.1:8765/api/lab'
Invoke-RestMethod $lab
Invoke-RestMethod $lab -Method Post -ContentType 'application/json' -Body '{"offline":true}'
Invoke-RestMethod $lab -Method Post -ContentType 'application/json' -Body '{"offline":false}'
Invoke-RestMethod $lab -Method Post -ContentType 'application/json' -Body '{"offer":"1.1.0"}'
# 等到串口中出现 TRIAL_CONFIRMED 再下发故障版本
Invoke-RestMethod $lab -Method Post -ContentType 'application/json' -Body '{"offer":"1.2.0"}'
```

还可以提交 `{"truncate":true,"offer":"1.1.0"}` 中断镜像传输，再提交 `{"truncate":false}` 恢复。服务端控制入口和镜像只在本机回环地址开放。

## 实现

- [分区表](firmware/partitions.csv)定义两个 OTA 应用槽、OTA 元数据和 NVS 数据区。ESP-IDF 的引导程序在候选首次启动后等待应用确认。固件在试启动时检查 NVS 和模拟采样，再确认镜像或请求回滚。
- [遥测队列](firmware/main/queue.c)保存最多 16 条温度读数。队列满时覆盖最早一条并累计丢弃数。上报成功后才从队列移除，服务端按 `device` 与 `sequence` 去重。
- [HTTP 和 OTA 客户端](firmware/main/transport.c)只处理版本递增的候选，核对镜像中的项目名和版本，再由 ESP-IDF 检查并切换启动分区。已拒绝的实验镜像版本记录在 NVS。
- 模拟固件使用 QEMU 的 OpenETH 和模拟温度，OTA 走回环实验环境中的 HTTP。仓库用途是可复现的本机实验。

## 测试

```bash
python -m unittest discover -s tests -v
python -m ota_lab verify
```
