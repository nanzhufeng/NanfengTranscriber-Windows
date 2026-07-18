# Mac Codex 启动提示词

将下面内容完整粘贴给 Mac 上的 Codex：

```text
请基于当前 Git 仓库继续开发「南枫转写」的 macOS 版本。

这是批量视频/音频转文字桌面工具，不是视频下载器，也不是南枫记。保留 Windows 最新源码的工作台 UI、批量队列、导出格式和交互原则；不要重做成其他产品。

开始时必须：
1. 先读取 AGENTS.md、docs/CURRENT_HANDOFF.md、docs/chatgpt-project-context.md。
2. 先执行 git status --short，只报告当前进度、已修改文件、最近验证结果、下一件最小可验收任务；不要立刻改代码。
3. 检查 macOS 版本与架构、Python、pip、ffmpeg、ffprobe、PySide6、faster-whisper、ctranslate2、huggingface_hub、python-docx、PyInstaller。

平台改造要求：
- 不得复用 Windows 的 EXE、IExpress、BAT、PowerShell 安装器、D: 路径、CUDA DLL 检测或 ..\\JHlib\\ffmpeg 路径。
- 默认输出目录应使用用户目录下的明确文件夹，例如 ~/Movies/南枫转写；所有路径用 pathlib 处理。
- FFmpeg/FFprobe 先检查 PATH、/opt/homebrew/bin、/usr/local/bin；缺失时给出明确提示，不静默失败。
- GPU 不得假设 CUDA 可用。先验证 current ctranslate2/faster-whisper 在该 Mac、该架构上的真实支持；未验证前默认可靠 CPU 路径，并在 UI 中说明状态。
- 保留 TXT、Markdown、SRT、DOCX；保留可选 API 翻译润色，不要把它宣传为本地自动翻译。
- 保留性能优化结构：队列级 TranscriptionSession、GPU 批处理与受控降级。不要重新把 initial_prompt 传给 BatchedInferencePipeline；该行为会污染转录结果。

交付顺序：
1. 先生成可执行 .command 启动脚本。
2. 处理 chmod +x、xattr -dr com.apple.quarantine、LF 换行、虚拟环境和依赖检测。
3. 用 .command 实机打开窗口并验证一个短音视频的 CPU 转写、TXT/SRT/DOCX 导出和停止行为。
4. 仅在上述验证通过后，用 PyInstaller 生成 .app，做 ad-hoc codesign，再生成可传输 zip。

验证状态必须分开记录：已实现、仅测试通过、已在真实 Mac 验证、待验证风险。完成每步后更新 docs/CURRENT_HANDOFF.md，并给出下一步最小任务。
```
