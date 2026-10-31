# v2.0.0 · Python 跨平台重构

2.0 将 PowerShell/WinForms 程序完整重写为 Python + PySide6 + QtWebEngine + SQLite。原有配置范围、固定字段及“每个序列号一份登记”的行为保留，界面、登录与业务代码共用于 Windows、Linux 和 macOS。

## 新增

- 在官方网页内完成登录，自动获取并验证会话令牌。
- 只读查询、逐条型号与保修结果表、后台任务及停止操作。
- SQLite 提交意图、历史记录、筛选导出和人工核对事件。
- 原有配置和四列 CSV 的事务迁移与增量导入。
- 四目标原生构建、打包后的离线 Chromium 启动检查及 SHA-256 文件。

## 修复与保护

- 超时、断线和异常响应不再直接作为可重试失败；结果不明确时保留待核对记录。
- 历史成功不会被后一次失败覆盖；待核对记录始终优先保护。
- 提交前持久保存意图，写入失败不发送；提交不自动重放。
- 识别认证失效并停止任务，校验权限、网点能力及产品条件。
- 保留查询返回的产品、质检、附件和物料字段；不保存明文令牌或完整业务报文。
- 旧版缺少明确拒绝依据的失败记录按待核对处理，避免迁移后重复登记。

## 下载与升级

选择 Release 页面实际提供的对应平台附件，完整解压。原生包包含 Python 运行时，源码包需要自行安装依赖。

- Windows：运行 `HikvisionASMP.exe`，保留 `_internal`。
- Linux x86_64：构建基线 Ubuntu 22.04。
- macOS：区分 Intel 与 Apple Silicon，当前依赖要求 macOS 14+；临时签名不等于 Developer ID 签名或公证。

升级前关闭 1.x，保留原配置和 CSV，按 [升级说明](docs/migration.md) 迁移。历史 PowerShell 实现归档在 `legacy/powershell/`；[1.0 发布记录](https://github.com/szrd2026/hikvision-asmp-tools/releases/tag/v1.0.0) 保留。

## 验证范围

核心与 Qt 界面测试使用模拟请求；原生构建检查打包后的窗口和离线 Chromium。Windows 真实账号登录、真实设备只读查询已验证。真实维修登记提交尚未做实单验证，CI 成功不等于每个平台的真实 ASMP 业务验证。

平台构建结果见 [Actions](https://github.com/szrd2026/hikvision-asmp-tools/actions/workflows/build.yml)。安装、校验和及源代码运行方式见 [README](README.md)。
