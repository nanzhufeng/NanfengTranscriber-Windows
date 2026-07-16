# 南烛枫 - 视频转文字

面向影视、动画与 VFX 工作流的本地优先批量音视频转写工具。当前 Windows 源码版基于 Python、PySide6、faster-whisper 和 FFmpeg，支持 TXT、Markdown、SRT、DOCX 与可选的转写后翻译/润色。

## 当前状态

- Windows 性能版已完成模型复用和 GPU 批量推理；在 RTX 4090 的固定三样本基准中，队列耗时从 130.499 秒降至 28.403 秒。
- 当前源码包含 Windows 实现和接手文档；macOS 版本尚未实现。
- 详细状态见 `docs/CURRENT_HANDOFF.md`，产品与历史事实见 `docs/chatgpt-project-context.md`。

## Git 迁移到 Mac

解压迁移包后，在 macOS 终端执行：

```bash
git clone --branch main "南烛枫视频转文字.bundle" VideoTranscriber
cd VideoTranscriber
git status --short
```

然后在 Mac 的 Codex 中打开该目录，并粘贴 `docs/MAC_CODEX_START_PROMPT.md` 的内容。

不要把 Windows 的 `dist*`、`WindowsSetup*`、EXE、ZIP 或本地模型缓存迁移到 Mac；它们不属于源码，也不能作为 macOS 验证依据。

## Windows 源码验证

```powershell
python -m unittest discover -s tests -v
python -m compileall app tests tools
python start.py
```

Windows 下可通过 `启动南烛枫视频转文字_源码测试.bat` 启动源码版本。macOS 必须先做 `.command` 启动验证，不能使用该 BAT 文件。
