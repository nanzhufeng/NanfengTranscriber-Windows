# macOS 后续迁移提示（未实施）

这是未来平台任务的提示，不是当前 Windows 软件合同，也不代表已有 Mac 交付。

接手时先读 AGENTS、[当前合同](CONTRACTS.md)、[架构入口](context.md) 和 [当前状态](PROJECT_STATUS.md)，检查受影响源码与 Git 范围。新平台独立确认 Python/Qt、两种本地模型、对齐器、FFmpeg、CPU/GPU 支持和目标架构，不把 Windows 成功视作 Mac 成功。

- 从源码适配，不复用 EXE、BAT、Windows PowerShell、D 盘、CUDA DLL 探测或外部 JHlib 盘符。
- 输出使用用户目录，FFmpeg/FFprobe 使用 Mac 可用路径；不存在便明确提示。
- 保留队列、停止、四种格式、保存路径设置与可选文本 API 的现有语义；先验证可靠 CPU 路径，再确认其他加速后端。
- Qwen 的独立环境安装需另行适配，不执行 Windows 嵌入 Python 安装脚本。
- 先源码/.command 再 .app，逐层验证受控样本、重启、停止和导出；开发 ad-hoc 签名只能标记开发验证，不能冒充正式发行签名。
- 正式交付按当前产品交付标准核对正式发行签名及平台要求；Windows 未签名例外不适用于 Mac。

不自动移除用户主设备隔离、系统安全保护或历史数据；不得未经授权运行卸载、清数据或全局清理。
