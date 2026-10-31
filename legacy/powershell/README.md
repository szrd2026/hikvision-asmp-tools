# PowerShell 历史实现

此目录保留 Python 2.0 重构前的 Windows 实现，包括未单独发布的 1.1 迭代、WebView2 登录代码、原构建脚本和测试。它不属于当前运行时，也不进入 Python 原生包。

新功能和修复请使用根目录的 Python 项目，见 [当前 README](../../README.md)。已经发布的旧版可在 [v1.0.0 Release](https://github.com/szrd2026/hikvision-asmp-tools/releases/tag/v1.0.0) 查找。

本归档面向代码参考，不继续维护或验证旧依赖。`lib/` 中 WebView2 SDK 文件来自微软 NuGet，来源及许可证保留在相邻文件中。归档不包含本地令牌、真实配置、日志或业务记录。

旧数据迁移方法见 [升级说明](../../docs/migration.md)。迁移前关闭旧版，不要同时用两个版本登记同一批设备。
