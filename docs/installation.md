# 安装与运行

## 原生运行包

在 [Releases](https://github.com/szrd2026/hikvision-asmp-tools/releases/latest) 选择对应系统和架构的附件。每个归档旁附 `.sha256` 文件；下载页没有对应平台附件时，可从源码运行或在目标系统构建。

### Windows

1. 下载 `Hikvision-ASMP-v2.0.0-windows-x86_64.zip`。
2. 完整解压到本地文件夹，保留 `_internal`。
3. 运行 `HikvisionASMP.exe`。不需要安装 Python、PowerShell 模块或 WebView2。

目标为 Windows 10/11 x86_64。发布包尚未使用维护者的代码签名证书。

### macOS

选择 Intel 的 `macos-x86_64.zip` 或 Apple Silicon 的 `macos-arm64.zip`，解压后打开 `.app`。当前依赖的公开 wheel 要求 macOS 14+。

构建器使用临时签名，发布包没有 Developer ID 签名或 Apple 公证。需要受管理或公开分发的签名包时，使用自己的 Developer ID 构建并完成公证；构建参数见 [开发文档](development.md)。

### Linux

解压 `linux-x86_64.tar.gz`，进入目录运行 `./HikvisionASMP`。原生构建基线为 Ubuntu 22.04 x86_64；其他发行版可能需要补充相应的图形、NSS、音频和字体库。

Ubuntu 22.04 常用运行依赖：

```bash
sudo apt-get update
sudo apt-get install libegl1 libopengl0 libnss3 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxcomposite1 \
  libxdamage1 libxrandr2 libxtst6 libasound2 libgbm1 fonts-noto-cjk
```

应用使用 QtWebEngine 默认沙箱，不自动修改系统安全设置。Linux ARM 暂不提供原生构建任务。

## 校验下载

将下载文件的 SHA-256 与对应 `.sha256` 内容比较：

```powershell
# Windows
Get-FileHash .\Hikvision-ASMP-v2.0.0-windows-x86_64.zip -Algorithm SHA256
```

```bash
# Linux
sha256sum Hikvision-ASMP-v2.0.0-linux-x86_64.tar.gz

# macOS：替换为已下载的实际文件名
shasum -a 256 Hikvision-ASMP-v2.0.0-macos-arm64.zip
```

## 从源码运行

需要 Python 3.11+，建议 3.13。GitHub 的 Source code 附件和项目提供的 `source.zip` 都需要安装运行依赖。

Windows：

```powershell
git clone https://github.com/szrd2026/hikvision-asmp-tools.git
cd hikvision-asmp-tools
python setup_env.py
.\Start-Submit.bat
```

macOS / Linux：

```bash
git clone https://github.com/szrd2026/hikvision-asmp-tools.git
cd hikvision-asmp-tools
python3 setup_env.py
bash Start-Submit.sh
```

初始化脚本只创建项目自己的 `.venv`，不向系统 Python 安装应用依赖。源码启动器使用该虚拟环境；原生运行包不需要此步骤。

## 首次使用与常见问题

- 登录官网后等待“登录有效”。令牌失效时重新登录，不需要打开 F12。
- 提交前可以用“仅查询资料”检查设备；该按钮不创建维修登记。
- 程序提示已在运行时，使用现有窗口，或先关闭旧窗口。同一个数据目录只允许一个实例。
- 数据和日志保存在系统用户目录，详见 [迁移与备份](migration.md)。
- 官网加载失败时先检查访问 `https://asmp.hikvision.com/sr/` 的网络条件，再点击重新载入。网页接口或认证流程改变时可能需要更新软件。
- 记录为“待核对”时先查官网历史数据，不直接重试。
