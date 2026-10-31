# 开发、测试与原生构建

## 环境

Python 3.11+，原生构建使用 Python 3.13。依赖版本固定在 [`requirements.txt`](../requirements.txt) 和 [`requirements-dev.txt`](../requirements-dev.txt)。当前 PySide6 公开 wheel 要求 macOS 14+；Linux x86_64 构建使用 Ubuntu 22.04。

Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run.py
.\.venv\Scripts\python.exe -m pytest -q
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python run.py
.venv/bin/python -m pytest -q
```

Linux 构建及测试依赖见 [工作流](../.github/workflows/build.yml)。无图形桌面的 Linux CI 使用 Xvfb，不访问真实 ASMP 账号。

## 模块边界

| 模块 | 责任 |
| --- | --- |
| `models.py` | 设置、输入、权限条件及网页报文规则 |
| `config.py` | 系统数据目录、旧配置迁移、原子保存 |
| `api.py` | 接口允许列表、HTTPS 请求、业务与协议结果分类 |
| `journal.py` | SQLite 提交意图、结果、审计、CSV 迁移与导出 |
| `engine.py` | 查询、逐条提交、停止及防重流程 |
| `ui/` | Qt 主窗口、官网登录窗口、工作线程 |
| `app.py` | 启动、单实例保护、迁移和启动检查 |

业务模块不依赖 GUI。网络客户端通过工厂注入，测试使用 `httpx.MockTransport`。SQLite 使用 WAL、FULL synchronous 和提交前的事务；每次尝试独立保留状态，未知结果不能作为明确拒绝处理。

完整设计说明见 [重构说明](python-refactor.md)。

## 验证

```bash
python -m pytest -q
python run.py --smoke-test
python run.py --browser-smoke
```

- 核心测试使用模拟响应，覆盖权限、报文、成功/失效/拒绝、超时、重定向、异常响应、防重、停止、存储故障及旧数据迁移。
- Qt 界面测试使用真实工作线程驱动模拟业务，检查结果表、控件恢复、关闭和令牌隐藏。
- `--smoke-test` 在独立临时目录检查界面、配置保存和离线 Chromium 渲染，不发送业务请求。
- `--browser-smoke` 只加载 ASMP 官方页面，不登录、不登记；依赖网络，未作为 CI 必须步骤。
- Windows 真实登录和设备只读查询已验证。实单提交未做生产验证；CI 的离线启动成功不代表真实业务成功。

显式 smoke 测试可结合 `--data-dir` 指定测试目录。原生包在该目录写入 `smoke-result.json`；窗口模式的启动日志写入 `smoke-console.log`。这些诊断文件不包含令牌。

## 打包

在目标操作系统的虚拟环境中执行：

```bash
python tools/build.py
```

构建器依次运行测试、生成源码归档、调用 PyInstaller、验证原生窗口和离线浏览器，再生成当前平台包及 SHA-256。已单独运行测试时可使用 `--skip-tests`；`--source-only` 仅生成源码包。

| 平台 | 输出 |
| --- | --- |
| Windows | `Hikvision-ASMP-v2.1.0-windows-x86_64.zip` |
| Linux | `Hikvision-ASMP-v2.1.0-linux-x86_64.tar.gz` |
| macOS | `Hikvision-ASMP-v2.1.0-macos-{x86_64,arm64}.zip` |
| 源码 | `Hikvision-ASMP-v2.1.0-source.zip` |

每个包附独立 `.sha256`。构建目录位于 `build/`，归档位于 `dist/`，均不提交 Git。

Windows 构建为子进程隔离 PATH 和 Qt 路径，避免把其他工具的同名 DLL（例如 ICU）收集进程序；不修改系统环境。macOS 使用 ditto 保留框架符号链接和元数据，并合并 QtWebEngineProcess 所需 entitlements。

需要 macOS Developer ID 签名时，使用本机已配置的身份：

```bash
python tools/build.py --codesign-identity "Developer ID Application: YOUR NAME (TEAMID)"
```

公证由维护者使用自己的 Apple 开发者配置完成。没有传入身份时，只使用本地临时签名，不声明已完成公开分发签名。

## GitHub Actions 与发布

[`build.yml`](../.github/workflows/build.yml) 对 Windows、Ubuntu 22.04、macOS Intel 和 macOS Apple Silicon 分别运行原生构建。成功产物上传为 Actions artifacts；工作流本身不自动创建 Release。

维护者发布时：

1. 确认版本号、更新日志、文档及 CI 状态。
2. 确认归档不含配置、SQLite、日志、令牌或虚拟环境。
3. 创建对应 Git tag / GitHub Release，上传已完成检查的原生包、源码包及校验文件。
4. 记录目标平台的构建和实际业务验证范围，未完成的验证不写成已支持。

## 修改业务规则

ASMP 使用未版本化网页接口。调整字段或认证流程时，先保留脱敏的接口结构和网页依据，再更新模型和模拟测试。不要通过真实批量提交来验证不确定的报文。网络不明确、写记录失败和登录失效必须继续保持停止/待核对行为。
