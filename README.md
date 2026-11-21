# Hikvision ASMP Tools

**海康 ASMP 批量登记工具 · Python 2.1**

[![Build](https://github.com/szrd2026/hikvision-asmp-tools/actions/workflows/build.yml/badge.svg)](https://github.com/szrd2026/hikvision-asmp-tools/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/szrd2026/hikvision-asmp-tools)](https://github.com/szrd2026/hikvision-asmp-tools/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

[English](README.en.md) · [下载](https://github.com/szrd2026/hikvision-asmp-tools/releases/latest) · [安装说明](docs/installation.md) · [从旧版升级](docs/migration.md) · [开发文档](docs/development.md)

将 Excel/WPS 中的一列序列号转换为 ASMP 收货登记。可以先只读查询型号和保修资料，再逐条提交，并在本地保留可核对的登记记录。

2.0 使用 **Python + PySide6 + QtWebEngine + SQLite** 重写，Windows、Linux 和 macOS 共用界面、网页登录与业务代码。运行时不再依赖 PowerShell、WinForms、.NET 或 Microsoft WebView2。

本项目是非官方工具，与海康威视没有隶属或背书关系。使用自己的授权 ASMP 账号操作。

![Python 2.1 界面，未包含真实账号或设备资料](docs/screenshot-python.png)

## 功能

- **官方网页登录**：在独立官网窗口完成登录，自动取得会话令牌并检查认证；保留手动粘贴令牌入口。
- **只读查询**：显示型号、保修截止、保修情况和产品客户资料，不创建维修登记。
- **批量登记**：支持换行、制表符、中英文逗号和分号，同一批次自动去重。
- **返回方式**：选择寄回送修点或寄回客户；寄回客户时从官网加载省市区并填写详细地址。
- **设置记忆**：编辑后自动保存，显示保存状态，下次启动恢复登记设置。
- **送修客户历史**：可输入新名称或在下拉框中选择最近使用的客户，支持按名称搜索和删除历史。
- **故障描述历史**：可直接输入或选择已成功登记的描述，按使用次数排序，也可删除不需要的历史项。
- **逐条结果**：后台线程执行网络请求，界面显示进度；停止后不再开始后续提交，已发出的请求等待结果。
- **防重复记录**：SQLite 在提交前保存意图；超时或响应异常时停止，并将记录保留为待核对。
- **历史核对**：按序列号筛选、导出 CSV，在官网查明结果后更新本地待核对状态。
- **旧版迁移**：兼容原配置字段及原四列 CSV，保留历史成功记录，不重复导入。

## 下载与运行

从 [Releases](https://github.com/szrd2026/hikvision-asmp-tools/releases/latest) 选择对应系统和架构的附件。完整解压原生运行包即可运行，**不需要安装 Python**。GitHub 自动生成的 “Source code” 附件是源码，不是可运行程序。

| 平台 | 附件后缀 | 启动方式 |
| --- | --- | --- |
| Windows 10/11 x86_64 | `windows-x86_64.zip` | 解压后运行 `HikvisionASMP.exe`，保留 `_internal` 文件夹 |
| Linux x86_64 | `linux-x86_64.tar.gz` | 解压后运行 `./HikvisionASMP`；构建基线为 Ubuntu 22.04 |
| macOS Intel | `macos-x86_64.zip` | 解压后运行 `HikvisionASMP.app`；macOS 14+ |
| macOS Apple Silicon | `macos-arm64.zip` | 解压后运行 `HikvisionASMP.app`；macOS 14+ |

下载页只列出实际提供的构建产物；对应目标的自动构建结果见 [Actions](https://github.com/szrd2026/hikvision-asmp-tools/actions/workflows/build.yml)。原生包尚未使用维护者的发布证书签名；macOS 包的本地临时签名不等于 Developer ID 签名或公证。系统要求、校验和及源码运行方法见 [安装说明](docs/installation.md)。

## 快速开始

1. 点击 **官方网页登录**，在 `asmp.hikvision.com` 页面内自行输入账号、密码和验证码，等待“登录有效”。
2. 填写送修客户、联系人、电话和故障资料，并确认**返回方式**。选择“寄回客户”时，点击“加载省市区”，依次选择省、市、区并填写详细地址。
3. 仅复制 Excel/WPS 的**序列号列**，粘贴到左侧输入框。
4. 点击 **仅查询资料** 检查型号和保修信息。
5. 确认要创建登记后，点击 **开始提交登记**。软件对每个序列号创建一份登记。
6. 查看逐条结果及 **提交记录**；需要停止时点击 **停止**。

登记设置在停止编辑约 0.6 秒后自动保存，查询、提交前及正常关闭时也会保存；界面显示“设置已自动保存到本机”即表示写入成功。登录令牌不保存。

填完送修客户并离开输入框或按回车后，名称会加入本机历史，最多保留最近使用的 50 项。可以输入部分名称搜索或展开下拉框选择。点击客户栏旁的“删除历史”会移除当前名称的历史建议。选择客户后，请核对表单中的联系人、电话和退回地址。

故障描述下拉框按**成功登记的设备数**降序排列，同次数时最近使用的在前。失败、仅查询、跳过及待核对不计数；人工核对为已登记后计入。选择描述后点击“删除历史”可移除该历史项，不改动当前输入和提交记录；以后再次成功使用该描述会从 1 次重新累计。2.0 未记录逐次故障描述，升级后无法恢复此前的使用次数。

账号固定为“本地服务”时，软件也必须选择“本地服务”；需要手工选择更换方式的一年包换登记，请在官网处理。

## 待核对记录

**超时并不等于登记失败。** 服务器可能已经创建工单，但软件没有收到响应。2.0 会保留待核对记录并阻止直接重试，即使取消“跳过以前已成功登记”也不会绕过。

先到官网“历史数据”查明，再在记录页选择 **核对：已登记** 或 **核对：未登记**，填写说明。旧 CSV 中缺少明确拒绝依据的“失败”记录也按待核对处理。

本地记录只覆盖当前数据目录，不能识别另一台电脑或网页上的全部操作。详细行为见 [升级与数据说明](docs/migration.md)。

## 登录与本地数据

- 登录窗口使用内存浏览器会话；程序只读取业务所需 Cookie，不读取账号或密码，不将令牌写入配置或日志。
- 每次任务检查认证；登录失效会停止任务，再登录后重新启动。
- 配置、SQLite 记录及日志默认保存在系统用户数据目录。原生包可通过 `portable-mode.txt` 使用程序旁的 `data` 文件夹，操作及迁移方法见 [安装说明](docs/installation.md)。备份前关闭程序。
- 日志保留步骤、序列号和必要结果，不保存完整业务报文。

| 系统 | 默认数据目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\HikvisionASMP` |
| macOS | `~/Library/Application Support/HikvisionASMP` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/HikvisionASMP` |

配置和迁移方法见 [数据说明](docs/migration.md)。

## 验证范围

核心与 Qt 界面回归测试使用模拟 HTTP 请求，不创建真实维修登记；原生构建还会检查打包后的窗口和本地 Chromium 渲染。Windows 的真实账号登录和真实设备只读查询已经验证。

CI 构建成功表示对应环境的自动化测试与离线启动检查通过，不代表每个系统上都完成了真实 ASMP 业务验证。真实维修登记提交尚未做实单验证。

## 开发与贡献

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python run.py --smoke-test
python tools/build.py
```

先创建虚拟环境，或使用 `python setup_env.py` 初始化运行依赖。Windows、macOS 和 Linux 的完整命令、目录结构及打包方法见 [开发文档](docs/development.md)。贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。

历史 PowerShell 实现位于 [`legacy/powershell`](https://github.com/szrd2026/hikvision-asmp-tools/tree/main/legacy/powershell)，不进入 Python 发布包；已发布的 1.0 版本仍可在旧 Release 中找到。

## 许可

项目代码使用 [MIT](LICENSE)。Qt、Chromium 等依赖保留各自许可，来源与随包说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。ASMP 网页接口并非公开版本化 API，官网更新时可能需要调整客户端。
