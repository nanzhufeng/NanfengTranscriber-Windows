# 南枫转写：ChatGPT 项目开发上下文与经验文档

> 更新时间：2026-07-15  
> 用途：这是给 ChatGPT / Codex 延续理解 `南枫转写` 的项目级上下文文档。未来为南烛枫继续设计、排错、打包、迁移 Mac 版或提出同类工具建议前，应先阅读本文件，再结合南烛枫长期工具软件偏好。
> 重要更正：本文件描述的是 **视频转文字桌面工具**，不是 `南枫记` 记账 App，也不是 `南烛枫视频下载器`。
> 当前工程事实优先读取 `docs/context.md`；本文件主要保留产品、UI 和历史经验细节。

## 1. 一句话定位

`南枫转写` 是一个面向南烛枫影视/动画/VFX 工作流的 **本地优先批量音视频转写工具**。

它的目标不是做云端协作平台，也不是简单命令行封装，而是提供一个可直接工作的桌面工作台：批量导入视频/音频，选择模型、语言和 CPU/GPU 模式，转写为 TXT、Markdown、SRT、DOCX，并可选进行“转写后翻译/润色”为现代简体中文。

## 2. 当前工程事实

| 项目 | 当前事实 |
| --- | --- |
| 项目路径 | `D:\CodexProjects\江湖工具箱\VideoTranscriber` |
| 主要语言 / UI | Python + PySide6 |
| 主入口 | `start.py` |
| 核心 UI | `app/main.py` |
| 转写核心 | `app/transcriber.py` |
| 转写后处理 | `app/postprocess.py` |
| 依赖 | `PySide6`、`faster-whisper`、`python-docx` |
| 外部工具 | FFmpeg / FFprobe，优先查找项目或 `JHlib\ffmpeg` |
| Windows 交付 | PyInstaller 目录包、便携 zip、可点击安装 zip 均已生成过 |
| Windows GitHub 仓库 | `nanzhufeng/NanfengTranscriber-Windows` |
| 最新可点击安装包 | `NanfengTranscriber_Windows_v1.0.0_Setup_20260719_001129.zip` |

平台命名是长期约束：Windows 仓库使用 `NanfengTranscriber-Windows`，Android 仓库使用 `NanfengTranscriber-Android`。应用内产品名均保持“南枫转写”，平台差异由仓库、Release 和安装产物名称表达。

## 3. 产品形态与 UI 方向

当前 UI 已按南烛枫长期工具标准形成工作台结构：

- 左侧栏：品牌、输出格式、操作流程、打开输出目录。
- 主控制区：保存位置、模型、语言、运行模式、导出格式、添加文件/文件夹。
- 操作条：开始转写、停止、清空队列、全选、反选。
- 主表格：序号、选择、状态、文件名、时长、语言、模型、进度、耗时、剩余、输出路径。
- 底部状态区：FFmpeg 状态、队列数量、复制/依赖安装/运行反馈、总剩余时间、总进度。

视觉方向与视频下载器同属南烛枫工具体系，但已经做了差异化：视频转文字更偏青绿色、浅色工作台、平面系统感；避免大面积深色块、营销首页和过度装饰。

长期 UI 经验：

- 列表默认居中，包括表头、状态、选择框、文本、进度、耗时和路径。
- 表格内容过长时使用 tooltip，不靠拉大窗口硬撑。
- 状态要有颜色区分：等待、加载模型、转写中、完成、失败、已存在、无文字、已停止。
- 复制提示使用底部独立 toast 区域，不应撑高窗口或改变底部布局。
- 添加文件/文件夹按钮大小统一；支持文件夹拖入，自动导入其中支持的视频/音频。
- 所有下拉框都应点击整个选框打开，不只靠右侧箭头；避免系统默认下拉箭头显得廉价。

## 4. 已实现能力

### 4.1 批量导入

支持添加单个/多个文件、添加文件夹，以及拖拽视频或音频文件到窗口。

支持格式包括：

- 视频：MP4、MOV、MKV、AVI、M4V、WMV、FLV、WEBM。
- 音频：MP3、WAV、M4A、AAC、FLAC、OGG。

### 4.2 模型和语言

模型顺序应严格按低到高：

1. `base`
2. `small`
3. `medium`
4. `large-v3`

当前默认模型为 `medium`。原因是 `small` 对中文短视频口播和复杂语音效果不够稳，`large-v3` 成本和等待更高，`medium` 是速度和准确率的折中默认。

语言默认应为中文。中文、古文、英文内容的目标方向是尽量输出现代简体中文；原始转写和转写后润色需要区分。

### 4.3 运行模式

支持：

- `GPU 优先`
- `CPU 稳定`

默认是 `GPU 优先`，但必须保守处理 GPU 环境：

- 如果缺 CUDA / cuBLAS / cuDNN，自动提示并回退 CPU。
- 如果 GPU 模型加载实际失败，当前项改用 CPU 重试，后续任务也应自动使用 CPU。
- 不应让用户卡在“加载模型”没有反馈。
- 首次使用模型可能需要联网下载，状态栏应明确显示“下载模型 / 加载模型”。成功后长期保存在 `%LOCALAPPDATA%\NanfengTranscriber\models`，以后启动只读本地缓存；可用 `NANFENG_TRANSCRIBER_MODEL_DIR` 覆盖。

### 4.4 输出格式

当前支持：

- TXT
- Markdown
- SRT
- DOCX

TXT / Markdown 偏阅读，会合并过碎的 Whisper segment；SRT 保留字幕节奏。

DOCX 依赖 `python-docx`。如果缺依赖，应明确提示或自动安装，而不是报模糊错误。

### 4.5 转写后翻译/润色

已单独加入“翻译润色”能力。该模块通过文本 API 将转写稿整理为现代简体中文。

环境变量：

- `NANZHU_TEXT_API_KEY`
- 或 `OPENAI_API_KEY`
- 可选 `NANZHU_TEXT_BASE_URL`
- 可选 `NANZHU_TEXT_MODEL`

默认关闭条件：没有可用 API Key 时不应默认勾选。开启但没有 API Key 时，应在开始前阻止并明确说明。

API 合同：401/403 必须提示检查 Key、服务地址和账号权限；超时、连接失败、空内容、异常格式分别报告；任何错误都不能回显 Key 或完整服务响应。

### 4.6 已存在结果处理

开始转写前会检查目标导出文件是否已存在。

期望行为：

- 选择 Yes：覆盖已存在结果并继续。
- 选择 No：跳过这些已存在结果，标记为“已存在”，继续处理剩余项目。

这是之前反复修过的关键流程：点击 No 后不能只改状态而不启动剩余任务。

### 4.7 路径与文件名

默认输出路径：

- D 盘存在时：`D:\南枫转写`
- 否则：用户 Downloads 下的 `南枫转写`

文件名和目录必须处理 Windows 长路径风险。当前采用 `safe_output_stem` 截断并加短 hash，避免 `WinError 206 文件名或扩展名太长`。

输出结构是按每个源文件创建安全文件夹，里面放对应格式结果。

### 4.8 安装与打包

项目已经历三类交付方式：

1. 源码 bat 测试。
2. PyInstaller 便携目录 + zip。
3. Windows 可点击安装包 zip。

用户明确要“可点击安装”的压缩包时，不是便携 zip，而是 zip 内含平台名明确的 Setup EXE 和中文优先的 `安装说明.txt`。

已生成过：

- 便携包：`南枫转写_Windows_便携包_<构建时间>.zip`
- 可点击安装包：`NanfengTranscriber_Windows_v1.0.0_Setup_<构建时间>.zip`
- 当前标准构建脚本：`build_windows_installer_inno.ps1`，工程为 `installer/NanfengTranscriber-Windows.iss`。
- `build_windows_installer.ps1` 与 `installer/install.*` 仅保留为旧 IExpress 回退。

IExpress 对大 payload 不稳定，曾出现生成了 exe 但返回码/流程不可靠的情况。当前正式路径已经切换到 Inno Setup 6；构建后必须做临时安装、主 EXE 检查和卸载验证。

## 5. 当前技术结构

### 5.1 `app/main.py`

负责 PySide6 UI、队列、表格、拖拽、依赖安装、GPU 预检查、已有结果处理、线程管理和状态反馈。

关键点：

- `TranscribeWorker` 在后台线程逐项处理。
- 表格行内可独立选择语言和模型。
- `DependencyInstallWorker` 可自动安装缺失依赖。
- `QProgressDialog` 用于依赖安装进度，不应反复弹黑色控制台。
- 状态栏和 toast 负责低打扰反馈。

### 5.2 `app/transcriber.py`

负责：

- 查找 FFmpeg。
- 提取音频为 16k 单声道 wav。
- 调用 `faster-whisper`。
- CPU/GPU 模型加载和回退。
- 输出 TXT / MD / SRT / DOCX。
- 处理无文字、停止、路径安全、模型下载提示和用户级持久模型缓存。

### 5.3 `app/postprocess.py`

负责可选的转写后翻译/润色。

原则：

- 不新增原文没有的新观点。
- 修正常见同音错字、断句和标点。
- 英文、繁体、文言表达尽量转成自然现代简体中文。
- 保留人名、地名、专有名词和数字。

## 6. 已验证事实与待验证点

### 已确认

- 源码 bat 路径可启动。
- PyInstaller exe 曾验证可启动，窗口标题为 `南枫转写`。
- 便携 zip 内含 exe、说明和 `_internal` 依赖。
- 可点击安装 zip 内含平台名明确的 Setup EXE 和中文优先的说明文件。
- GPU 缺运行库时需要自动回退 CPU，而不是卡住。
- 路径过长需要短文件名策略。

### 待验证或需持续注意

- 真实长批量任务下，`medium` 模型首次下载和加载仍可能等待较久，必须保留明确状态反馈。
- GPU 环境随机器差异大，不能承诺所有 Windows 机器可用 GPU。
- 旧 IExpress 安装路径只保留历史回退；正式 Windows 安装构建使用 Inno Setup 6。
- API、DPI 和 Inno 已建立自动/本机验证；真实 API 服务、真实多显示器 DPI 和全新 Windows 电脑仍是下一层验收。
- “转写后翻译/润色”依赖外部文本 API，不能当作完全本地功能宣传。
- Mac 版迁移不能照搬 Windows 路径、bat、exe、IExpress 或 `.dll` 检测逻辑。

## 7. Mac 版迁移经验

如果未来要让 Codex 在 Mac 上重做版本，提示词必须明确：

- 这是 `南枫转写`，不是视频下载器，也不是南枫记。
- 保持 Windows 最新版 UI 结构和功能逻辑，不重做成另一个软件。
- 先检查 macOS、架构、Python、pip、ffmpeg/ffprobe、PySide6、faster-whisper、ctranslate2、huggingface_hub、python-docx、PyInstaller。
- 先生成 `.command` 启动脚本并测试能打开，再打包 `.app`。
- macOS 路径必须改为 Mac 风格，例如 `~/Library/Application Support/...`、`/opt/homebrew/bin/ffmpeg`、`/usr/local/bin/ffmpeg`。
- `.command` 需要处理 `chmod +x`、`xattr -dr com.apple.quarantine`、CRLF 换行。
- `.app` 生成后要本机验证、ad-hoc codesign，再压 zip。

## 8. 未来开发建议

未来 ChatGPT / Codex 接手本项目时，应按以下顺序工作：

1. 先读本文和当前代码，不要从南枫记或视频下载器的上下文误迁移。
2. 先 bat / 源码启动验证，再 exe / 安装包。
3. UI 修改优先保持当前工作台结构，不重做成营销页。
4. 对长任务必须给明确状态：依赖安装、下载模型、加载模型、提取音频、转写、润色、完成、失败。
5. 对失败要给可操作原因：缺依赖、GPU 不可用、无文字、路径过长、API Key 缺失、模型下载中。
6. 不要用宽泛 try/except 吞掉错误，应把关键错误转成用户能理解的状态。
7. 包装输出必须说明是便携包还是安装包，避免再次把“解压运行”误当“点击安装”。

## 9. 给 ChatGPT 的长期经验

南烛枫做这类工具时，最在意的是：

- 先能跑通，再美化，再打包。
- 先 bat 测试，再 exe / 安装包。
- UI 是真实工作台，不是展示页。
- 批量任务必须有清晰队列、状态、总进度和剩余时间。
- 所有列表默认居中。
- 不要默认使用廉价系统控件样式。
- 失败要可解释，用户能知道下一步怎么处理。
- 能本地处理就本地处理；需要外部 API 的能力要明确标注。
- 打包交付要给明确路径，并说明用户如何安装或运行。

## 10. 2026-07-15 性能优化当前状态

### 已实现

- 转写核心新增队列级 `TranscriptionSession`。同一队列内按模型、设备、计算类型复用 faster-whisper 模型，队列结束后释放。
- GPU 优先路径使用 `BatchedInferencePipeline`：默认 `batch_size=8`、`beam_size=3`，遇到批处理资源错误按 `8 -> 4 -> 2 -> 普通 GPU` 降级；只有明确 GPU 运行库错误才回退 CPU。
- `TranscribeWorker` 只创建一个会话并传给整个队列，停止后不会继续启动下一项。
- 新增 `tests/` 与 `tools/benchmark_transcription.py`，用于锁定会话复用、降级、停止、导出和固定样本性能。

### 已在当前 Windows 机器验证

- 自动化：`python -m unittest discover -s tests -v`，9 个测试通过。
- 源码：编译、核心导入和无界面窗口构造检查通过。
- GPU：RTX 4090 上三个固定样本从 130.499 秒降到 28.403 秒，改善 78.2%；优化后无运行错误。
- CPU：25 秒真实样本在 `CPU 稳定 / int8` 下完成，耗时 6.906 秒。

### 重要质量边界

- faster-whisper 的批量管线会把 `initial_prompt` 发送到每个窗口；在本项目实测会出现提示词泄漏与文字缺失。批量路径因此不使用该提示词，避免损坏原始转写。
- 批量路径不能承诺将繁体、英文或文言自动稳定变成现代简体中文；该需求应通过已存在的“翻译润色”模块和文本 API 完成。
- 本轮没有重新打包 EXE 或安装包。性能优化已经在源码层验证，打包交付须在后续单独执行并复测。

## 11. 2026-07-15 性能版 Windows 交付

- 已使用当前 `南枫转写_Windows.spec` 重新构建性能优化后的 PyInstaller 目录包。
- 便携目录：`dist_release_<构建时间>\\南枫转写`。
- 便携 EXE 已本机启动验证，窗口标题确认是 `南枫转写`；检查后已关闭测试进程。
- FFmpeg 和转写图标资源已包含在便携目录。
- 首次性能版安装器存在通配符复制错误，未把主 EXE 写入安装目录；该文件不再作为交付版本。
- 当前可点击安装 ZIP：`NanfengTranscriber_Windows_v1.0.0_Setup_20260719_001129.zip`，内含平台名明确的 Setup EXE 与中文优先的 `安装说明.txt`，SHA-256 为 `17F4611F31CA3912D426CFB511364862D76F3835EF978FD61CBAFC03F7CD17B4`。
- 已在独立临时目录执行真实安装，安装后的主 EXE 可启动且响应正常；随后完成静默卸载和目录清理。文件未做数字签名，Windows 可能显示 SmartScreen 提示。
