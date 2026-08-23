# 南枫转写 Windows：项目 Context

> 更新时间：2026-07-19
> 当前事实优先级：代码与 Git 状态 > 本文件 > `CURRENT_HANDOFF.md` > `chatgpt-project-context.md` > 历史计划文档。

## 1. 项目定位

`南枫转写` 是面向影视、动画和 VFX 工作流的本地优先批量音视频转写桌面工具。当前仓库是 **Windows 版**，不是视频下载器、Android App 或南枫记。

- 应用内名称：`南枫转写`
- Windows 仓库：`nanzhufeng/NanfengTranscriber-Windows`（Private）
- Android 预留命名：`nanzhufeng/NanfengTranscriber-Android`
- Windows Release：`南枫转写 Windows v1.0.2`
- 当前安装资产：`NanfengTranscriber_Windows_v1.0.2_Setup_20260823_185621.zip`
- 默认输出：存在 D 盘时使用 `D:\南枫转写`，否则使用用户 Downloads 下的 `南枫转写`

平台必须在仓库、Release 和交付产物名称中明确；应用内产品名保持一致。

## 2. 技术栈

| 层级 | 技术与用途 |
| --- | --- |
| 语言 | Python 3.11+；当前 Windows 开发环境曾使用 Python 3.13 |
| 桌面 UI | PySide6，`QMainWindow` + 表格工作台 + `QThread` 后台任务 |
| 语音识别 | faster-whisper，底层使用 CTranslate2 |
| GPU 推理 | `BatchedInferencePipeline`，CUDA / cuBLAS / cuDNN 可选 |
| CPU 推理 | CTranslate2 `int8` 稳定模式 |
| 媒体处理 | FFmpeg / FFprobe，提取 16 kHz 单声道 WAV |
| 文档导出 | TXT、Markdown、SRT；DOCX 由 python-docx 生成 |
| 翻译润色 | Python 标准库 `urllib` 调用 OpenAI 兼容的 Chat Completions API |
| 打包 | PyInstaller 目录版；Inno Setup 6 生成标准 Windows 安装包；IExpress 仅保留历史回退脚本 |
| 测试 | Python `unittest`，覆盖冻结运行时、Worker、输出、API、模型持久缓存、安装器合同和 DPI 基线 |
| 版本与发布 | Git、GitHub CLI、GitHub Private Repository、GitHub Release |

直接依赖记录在 `requirements.txt`：

```text
PySide6
faster-whisper
python-docx
```

PyInstaller 还显式收集 `ctranslate2`、`huggingface_hub`、`tokenizers` 和 `docx` 的子模块及资源。

## 3. 运行架构

```text
start.py
  -> app.main.main()
     -> MainWindow（UI、队列、表格、状态、已有结果决策）
     -> TranscribeWorker / QThread（逐项执行并支持停止）
        -> TranscriptionSession（队列级模型与推理管线复用）
           -> FFmpeg 提取音频
           -> faster-whisper 转写
           -> 可选 postprocess 翻译润色
           -> TXT / MD / SRT / DOCX 导出
```

关键运行规则：

- 模型顺序：`base -> small -> medium -> large-v3`，默认 `medium`。
- 语言默认中文；原始识别与“翻译润色为现代简体中文”是两个独立阶段。
- 模式默认 `GPU 优先`，也支持 `CPU 稳定`。
- GPU 使用 `float16`、`beam_size=3`，批量大小按 `8 -> 4 -> 2 -> 普通 GPU -> CPU` 受控降级。
- 一个队列复用同一 `TranscriptionSession`，避免每个文件重复加载模型。
- 模型下载目录固定为 `%LOCALAPPDATA%\NanfengTranscriber\models`；也可用 `NANFENG_TRANSCRIBER_MODEL_DIR` 覆盖。成功下载后跨启动本地复用，缓存损坏才联网修复。
- 用户点击停止后，不再启动下一项；当前不可安全中断的阶段结束后退出。
- 已存在结果选择 Yes 时覆盖并继续；选择 No 时标记“已存在”并继续剩余项目。
- `safe_output_stem` 通过截断和短 hash 规避 Windows `WinError 206`。

## 4. 目录结构

```text
VideoTranscriber/
├─ start.py                         # Python 主入口
├─ requirements.txt                 # 直接 Python 依赖
├─ README.md                        # 用户安装与运行说明
├─ AGENTS.md                        # 当前项目协作约束
├─ 南枫转写_Windows.spec            # PyInstaller Windows 配置
├─ build_windows_installer_inno.ps1 # 当前 Inno Setup 安装包构建入口
├─ build_windows_installer.ps1      # 旧 IExpress 回退脚本
├─ 启动南枫转写_Windows.bat         # 普通源码启动入口
├─ 启动南枫转写_Windows_源码测试.bat # 保留控制台的诊断启动入口
├─ app/
│  ├─ main.py                       # PySide6 UI、队列、线程与状态管理
│  ├─ transcriber.py                # FFmpeg、模型、推理、降级与导出
│  ├─ postprocess.py                # 可选 API 翻译/润色
│  └─ assets/                       # 运行时图标
├─ assets/                          # 原始/打包图标副本
├─ installer/
│  ├─ install.cmd                   # 安装器启动桥接
│  ├─ install.ps1                   # 旧 IExpress 安装桥接
│  ├─ Install-Readme.zh-CN.txt       # 中文优先的安装说明模板
│  └─ NanfengTranscriber-Windows.iss # Inno Setup 工程
├─ tests/
│  ├─ test_frozen_runtime.py        # PyInstaller 冻结运行时回归
│  ├─ test_existing_outputs.py      # 已有结果跳过后继续剩余队列
│  ├─ test_transcribe_worker.py     # 队列 Worker 与停止行为
│  ├─ test_transcriber_outputs.py   # 输出结构和错误行为
│  ├─ test_transcription_session.py # 模型缓存、GPU 批量与降级
│  ├─ test_postprocess.py            # API 鉴权、超时与响应合同
│  ├─ test_inno_installer.py         # Inno 安装器结构合同
│  ├─ test_ui_baselines.py           # 截图基线清单完整性
│  └─ ui_baselines/windows/          # 100%/125%/150%/200% 截图
├─ tools/
│  ├─ benchmark_transcription.py    # CPU/GPU 性能基准
│  └─ capture_ui_baselines.py       # 多 DPI 基线生成器
└─ docs/
   ├─ context.md                    # 当前项目事实入口（本文件）
   ├─ development-experience-audit.md # 正式经验审计与证据矩阵
   ├─ CURRENT_HANDOFF.md            # 动态接手状态与下一步
   ├─ chatgpt-project-context.md    # 产品、UI 与历史经验详述
   ├─ MAC_CODEX_START_PROMPT.md     # macOS 迁移启动提示词
   ├─ RELEASE_NOTES_v1.0.0.md       # Windows v1.0.0 发布说明
   └─ superpowers/                  # 性能方案、计划和基准证据
```

构建目录、模型缓存、日志、ZIP 和 EXE 产物不纳入 Git。

## 5. 核心模块职责

### `app/main.py`

- 构建浅色青绿色工作台 UI。
- 管理文件/文件夹添加、拖入、列表选择和逐项模型/语言。
- 管理已有结果弹窗、依赖安装、GPU 预检查、状态颜色、进度和剩余时间。
- 使用 `TranscribeWorker` 与 `QThread` 避免长任务阻塞主界面。

### `app/transcriber.py`

- 定位 FFmpeg / FFprobe 并提取音频。
- 管理 `TranscriptionSession`、模型缓存、GPU 批量推理和 CPU 回退。
- 生成 TXT、Markdown、SRT、DOCX。
- 处理无文字、用户停止、长路径、模型下载和运行时错误。

### `app/postprocess.py`

- 仅在用户开启“翻译润色”时调用文本 API。
- 默认模型：`gpt-4o-mini`。
- 环境变量：`NANZHU_TEXT_API_KEY` 或 `OPENAI_API_KEY`；可选 `NANZHU_TEXT_BASE_URL`、`NANZHU_TEXT_MODEL`。
- 音视频本身不上传；只把转写文字分块发送给配置的文本 API。

## 6. 开发、测试与打包

源码运行：

```powershell
python -m pip install -r requirements.txt
python start.py
```

最小自动化验证：

```powershell
python -m unittest discover -s tests -v
python -m py_compile app/main.py app/transcriber.py app/postprocess.py start.py
```

Windows 目录版构建：

```powershell
python -m PyInstaller --noconfirm --distpath dist_release_<时间> --workpath build_<时间> "南枫转写_Windows.spec"
```

可点击安装包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_installer_inno.ps1
```

旧 `build_windows_installer.ps1` 仅用于 IExpress 回退，不再作为正式构建入口。

交付时必须实际检查 EXE 能启动、窗口标题为“南枫转写”、FFmpeg/FFprobe 存在，并核对安装 ZIP 的文件名、大小和 SHA-256。

## 7. 当前验证状态

### 已在真实 Windows 环境验证

- RTX 4090、`medium`、中文、GPU 优先、关闭润色的三样本耗时从 `130.499 秒` 降至 `28.403 秒`。
- CPU `int8` 对 25 秒样本完成转写，耗时 `6.906 秒`。
- PyInstaller EXE 可启动、界面响应正常、标题正确。
- Windows v1.0.0 新安装 ZIP 已完成本机构建和验收，SHA-256 为 `17F4611F31CA3912D426CFB511364862D76F3835EF978FD61CBAFC03F7CD17B4`。
- GitHub README 和 Release 默认展示当前版本的软件界面预览；预览图使用无隐私内容的固定 UI 基线，Release 资产名为 `NanfengTranscriber_Windows_UI_Preview.png`。

### 已自动化验证

- 27 项自动回归通过，覆盖已有结果续跑、API 缺 Key/401/超时/空响应、模型跨会话本地复用与缓存修复、Inno 工程合同、中文安装说明、四档 DPI 截图清单。
- 核心 Python 模块编译通过。
- 冻结运行时能够跳过不必要的依赖扫描并进入 Worker。
- Inno Setup 6.7.3 已编译 132 MB 级安装器，并在独立临时目录完成静默安装、主 EXE 检查和卸载。
- 100%、125%、150%、200% 四档 Qt offscreen 截图已生成并人工检查中文字体和主要布局。

### 尚未充分验证

- Windows Setup 尚未在一台全新、无开发环境的电脑上做完整实际安装验收。
- API 回归使用模拟响应；尚未用真实付费 API 账号做稳定性与费用验收。
- DPI 基线是固定 offscreen 渲染，尚未覆盖真实多显示器跨屏缩放切换。
- 低显存 NVIDIA GPU、其他显卡和超长音频的实际降级表现未覆盖。
- 安装包没有商业代码签名，可能触发 SmartScreen。
- macOS 版本尚未实现；Android 版不属于本仓库。

## 8. 已知边界

- PyInstaller spec 仍引用仓库外的 `..\JHlib\ffmpeg`，换机器构建前必须准备 FFmpeg 或改为项目内依赖。
- 首次使用模型需要联网下载；之后从用户级持久缓存复用。模型文件不进入 Git 或安装包。
- GPU 不是硬要求，CUDA 运行库不完整时应明确提示并回退 CPU。
- `BatchedInferencePipeline` 不传中文 `initial_prompt`，避免提示词在批次中泄漏和污染识别结果。
- 翻译润色依赖外部 API，不属于完全离线能力，也不能承诺自动理解所有古文或专业术语。
- 正式安装构建已切换到 Inno Setup；旧 IExpress 脚本仅保留回退。当前安装 ZIP 来自本轮最新源码，并已完成真实临时安装、启动和卸载验证。

## 9. 后续接手顺序

1. 读取 `AGENTS.md` 和本文件。
2. 查看 `git status --short`、最近提交和 `docs/CURRENT_HANDOFF.md`。
3. 需要复用开发经验或核对证据等级时读取 `docs/development-experience-audit.md`。
4. 需要理解 UI/产品历史时再读 `docs/chatgpt-project-context.md`。
5. 修改前先复现或定位当前事实；不要从视频下载器、南枫记或 Android 项目复用未经核对的假设。
6. 先做源码和最小测试验证，再构建 EXE；只有 EXE 验证通过后才更新安装包和 Release。

当前没有自动任务。新接手者应先报告状态，再根据明确需求继续开发。
