# 当前接手状态：南枫转写

> 更新日期：2026-07-17
> 适用分支：`main`（本次迁移建立的首个本地 Git 快照）  
> 当前平台事实：Windows 源码已验证；macOS 尚未实施。

## 先读什么

1. `AGENTS.md`
2. 本文件
3. `docs/chatgpt-project-context.md`
4. `git status --short`

本项目不是视频下载器，也不是南枫记。不要从其他项目带入下载、登录、Android 或记账逻辑。

## 已实现

- Python + PySide6 桌面工作台：批量添加文件和文件夹、拖入导入、逐项选择、队列状态、总进度、总剩余时间。
- 本地转写：faster-whisper + FFmpeg；导出 TXT、Markdown、SRT、DOCX。
- 可选“翻译润色”：通过文本 API 整理成现代简体中文；没有 API Key 时不能把它当成纯本地能力。
- 模型选项按 `base -> small -> medium -> large-v3`；默认 `medium`，语言默认中文，模式默认 GPU 优先。
- 既有结果处理：Yes 覆盖后继续；No 标记“已存在”并继续剩余任务。
- 输出路径和文件名已做 Windows 长路径保护。

## 最近完成：性能优化

- 新增 `TranscriptionSession`，整个队列复用模型与 GPU 推理管线。
- GPU 使用 `BatchedInferencePipeline`，默认 `batch_size=8`、`beam_size=3`，按 `8 -> 4 -> 2 -> 普通 GPU -> CPU` 受控降级。
- 只在明确 CUDA/cuBLAS/cuDNN/GPU 运行时错误时回退 CPU；CPU 使用 `int8` 并复用模型。
- `TranscribeWorker` 仅创建一个会话；停止后不再启动下一项。

## 最近完成：安装版启动修复与 GitHub 首版

- 修复 PyInstaller 安装版点击“开始转写”后可能停在主线程、没有进入 Worker 的问题。
- 冻结版不再通过 `find_spec` 扫描已打包依赖和外部 NVIDIA Python 包；保留 PATH 与系统 CUDA DLL 检测。
- 新增冻结运行时回归测试，并为依赖扫描、GPU 检测和 Worker 启动增加诊断日志。
- GitHub Windows 首版使用 `v1.0.0`，当前安装资产为 `NanfengTranscriber_Windows_v1.0.0_Setup_20260718_162709.zip`。

## 最近验证

### 已在真实 Windows 环境验证

- RTX 4090、`medium`、中文、GPU 优先、关闭润色、三个固定样本：`130.499 秒 -> 28.403 秒`，改善 `78.2%`。
- CPU 稳定 / int8：25 秒真实样本完成，耗时 `6.906 秒`。
- PyInstaller 性能版 EXE 已短暂启动，标题为 `南枫转写`。
- 修复后的 Windows Setup 使用真实 payload 做过无系统写入模拟，主 EXE 与 FFmpeg 能复制到目标目录；尚未做实际安装。

### 已在自动化或源码层验证

- `python -m unittest discover -s tests -v`：13 个测试通过。
- `python -m compileall app tests tools`：通过。
- `TranscribeWorker` 与 `TranscriptionSession` 导入通过。
- 无界面窗口构造检查通过；它不替代人工可视 UI 验收。
- GitHub 首版 PyInstaller EXE 已启动验证：进程正常响应、标题正确，FFmpeg/FFprobe 均包含在运行目录中。
- 当前安装 ZIP 已检查，仅包含 `南枫转写_Setup.exe` 与安装说明；ZIP SHA-256 为 `EE86E9596AF081857877C8694973B7F8DA94D2FC916DE95EED089DAB2F5F4DB0`。

## 已知边界与风险

1. 批量管线不能传中文 `initial_prompt`：faster-whisper 会将其注入每个批次窗口，实测会造成提示词泄漏和漏字。GPU 批量路径因此优先原始转写正确性。
2. 批量原始转写不能保证繁体、英文、文言自动转为现代简体中文；需要时开启“翻译润色”并配置 API。
3. 其他显卡、低显存设备与超长音频的实际批量降级和停止响应尚未实测。
4. Windows Setup 仍未做代码签名，可能触发 SmartScreen；IExpress 只是现有兼容交付方案，不应当作 macOS 打包方案。
5. 当前 PyInstaller spec 引用了 `..\\JHlib\\ffmpeg`，该外部 Windows 依赖不在 Git 迁移包内。

## Mac 迁移的下一件最小任务

先不要直接打包 `.app`。在 Mac 上完成以下最小闭环：

1. 检查 macOS 架构、Python、pip、FFmpeg/FFprobe、PySide6、faster-whisper、ctranslate2、huggingface_hub、python-docx、PyInstaller。
2. 将 Windows 路径、FFmpeg 查找、CUDA/DLL 逻辑隔离为平台适配层。
3. 生成 `.command` 启动脚本，修复权限、隔离环境和换行问题后确认窗口能打开。
4. 仅在 `.command` 跑通后才考虑 PyInstaller `.app`、ad-hoc codesign 和 ZIP。

完整可复制提示词见 `docs/MAC_CODEX_START_PROMPT.md`。
