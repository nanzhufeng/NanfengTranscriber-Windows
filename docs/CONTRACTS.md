# 当前软件合同

本页按当前代码归纳产品行为；版本取 `app/assets/product.json`，证据见 [当前状态](PROJECT_STATUS.md)。历史记录见 [HISTORY.md](HISTORY.md)。新增或改动合同必须同步所有者、消费者和行为检查。

## 产品与入口

- Windows 本地批量音视频转写；支持添加文件、递归添加文件夹及拖放。支持格式由 `SUPPORTED_EXTENSIONS` 定义，不扩大为下载、登录或云端音频转写。
- 主入口 `start.py`，推荐 BAT `启动最新界面_Windows.bat`；`--check` 只验证启动依赖。其他源码 BAT 保留兼容，名称中的“测试设置”仍打开工作台。
- 可启动的勾选项目是等待、失败、已停止和无文字；完成/已存在不是再次启动候选。全选/反选可能勾选已存在项，但不会因此重新启动它。
- 队列不持久化。一个批次拥有一个 `TranscriptionSession`，逐项处理；停止阻止后续项。模型下载/加载等阻塞阶段不承诺立即返回，独立 Qwen 进程只由本任务终止。

## 模型与兼容

| 用户模式 | 识别模型 | SRT |
|---|---|---|
| 中文精确 | Qwen3-ASR-1.7B | 导出时调用 Qwen3-ForcedAligner-0.6B |
| 通用快速 | Whisper large-v3-turbo / faster-whisper | 默认词时间戳；设置可启用上述精确对齐器 |

只有两种可选模式、两套识别权重和一个固定对齐器。旧 `base/small/medium/large-v3` 及 `turbo` 输入映射到快速模式；`qwen3-asr` 映射中文精确。旧名称在兼容测试中出现，不代表仍可选。

新设置默认中文精确、中文、GPU 快速；旧未知模型设置回退通用快速，旧 GPU 优先显示值回退 GPU 快速。主模式框收起仅中文名，展开显示实际模型名；队列表格模式框使用中文名及悬停说明。

## 设置协议

组织/应用 ID 为 `Nanzhufeng/NanfengTranscriber`，属于稳定兼容身份，不随界面名称变化。

| QSettings 键 | 新设置默认值/语义 |
|---|---|
| `transcription/output_dir` | 有 D 盘用 `D:/南枫转写`，否则用户 Downloads/南枫转写 |
| `transcription/model` | 中文精确；历史值按上述兼容规则读取 |
| `transcription/language` | 中文；另有自动识别、英文、日语、韩语 |
| `transcription/compute_mode` | GPU 快速；另有 CPU 稳定 |
| `transcription/{export_txt,export_md,export_srt,export_docx}` | 四项均为 true |
| `transcription/polish` | 键不存在时按环境中是否存在 API Key 默认；已有键读取用户保存值 |
| `preferences/completion_sound` | true |
| `preferences/completion_dialog` | true |
| `preferences/auto_open_output` | false |
| `preferences/create_video_subfolder` | false |
| `preferences/save_beside_video` | false |
| `preferences/precision_subtitles` | false |

主界面选项即时保存；设置对话框仅保存/接受后写回，取消或关闭不写入。两个保存位置单选互斥；功能审阅可反复折叠。JSON 协议、QSettings 键和缓存目录不可因整理擅自改名。

## 输出与已有结果

- 基础目录在软件指定路径与每个源文件父目录之间二选一；子目录开关独立生效，共四种组合。不开子目录时直接写入基础目录。
- 文件名和子目录名都使用 `safe_output_stem`，非法字符清理，超长名称裁剪并附短哈希；“视频同名”不承诺逐字保留非法/超长名称。
- GUI 至少选一个格式，否则阻止启动。已有结果检查只检查本次选中的后缀；任一已存在便询问，Yes 覆盖并继续，No 跳过该项目并继续剩余队列。
- TXT/Markdown 原文采用可读片段合并；Markdown 原文带时间表格。润色后 TXT/Markdown/DOCX 使用处理后文字，SRT 始终使用原始识别片段及时间线。
- SRT 以 24 字、5 秒、停顿和句末阈值拆分，排序并裁剪相邻重叠，过滤无有效时长的条目。没有词对齐时只在原片段范围内比例分配，不宣称精确逐词时间。
- 无识别片段以“无文字/失败说明”反馈，不生成伪文字。导出不是事务：后续格式失败时先前已写文件可能留存；不以整体失败为由自动删除真实输出。
- 定位优先已生成文件，其次源媒体。结束自动定位只在有成功且无失败、无文字或停止时执行，选中最近结果。主动停止不播放完成音。

## 运行环境、进度与回退

- 环境安装脚本以临时 Python 文件执行校验，成功/失败均清理；`-VerifyOnly` 仅校验已有 Python 与模型依赖，不下载或安装依赖。校验通过后写入就绪标记。

- 源码 Qwen 环境优先显式 `NANFENG_QWEN_PYTHON`，否则 `.runtime/qwen`；冻结版在用户级 `NanfengTranscriber/runtimes/qwen`。冻结版默认需要 `runtime.ready`，显式覆盖保留现有例外。
- 主安装包不含 Torch/CUDA 或模型权重。首次需 Qwen 的冻结任务提示打开安装 BAT；完成后用户再次点击开始。嵌入 Python 3.13.3、Torch 2.11.0 cu128、其余版本见 `requirements-qwen.txt`。
- 默认模型缓存 `%LOCALAPPDATA%/NanfengTranscriber/models`，`NANFENG_TRANSCRIBER_MODEL_DIR` 可覆盖。成功后优先本地；损坏/缺失时可联网修复。升级不删除或复制旧缓存。
- Whisper：CUDA float16 / CPU int8；批量按 8→4→2→普通 GPU 降级，只有明确 GPU 运行库错误回退 CPU。GPU 批量不传中文 initial_prompt。非 GPU 媒体/业务错误不吞成 CPU 回退。
- Qwen：CUDA 不可用时显式通知并用 CPU；不承诺所有 CUDA/OOM 异常都自动回退。识别按最多 30 秒块及低能量边界处理；字幕失败明确报错。日语精确对齐额外分词依赖未验收。
- DLL 预检查和实际运行时共用探测；文件存在仅是预检查，真实 GPU 成功仍以推理结果为准。冻结版不扫描外部 Python 的 NVIDIA 包。
- 真实阶段包括等待、提取、下载、加载、转写、字幕对齐、润色及完成/失败/无文字/已停止/已存在。当前总进度聚合对字幕对齐阶段有缺口，见审计，不伪称全阶段单调。

## 联网与诊断

- 本地识别/对齐不上传音频。可选润色通过 `NANZHU_TEXT_API_KEY` 优先、`OPENAI_API_KEY` 备用调用文本 API；发送识别文本和源文件标题，不发送音视频文件。
- 未配置 Key 默认关闭；用户保存或手动开启却无 Key 时阻止 GUI 启动并提示，不静默假装润色成功。
- 默认文本服务地址/模型及 120 秒超时由 `app/postprocess.py` 定义，环境变量可覆盖。鉴权、网络、超时、空响应和格式错误提供中文说明，不回显 Key 或服务端原始响应。
- 运行日志是诊断辅助，写日志失败不改变转写；日志、用户路径、模型、测试音频和凭据均不作发布附件。

## 界面与平台

- 浅灰页面底、无描边白色分区、浅灰输入；彩色按钮保留蓝色主操作、浅橙/浅紫导入和红色停止。绿色仅用于成功等真实状态语义。
- 控件反馈服从同一轮廓；开关鼠标焦点无额外外圈，键盘焦点可见；下拉框再次点触发处关闭，Esc/选择关闭。布局不借整理重设计。
- 自有图标/箭头归 `app/assets`；外部成熟资源授权保留。当前软件仅验收 Windows，Mac 提示是规划，不能据跨平台分支宣称已支持 macOS。

## 构建、发布与验证

- 当前构建 `scripts/build_windows_app.ps1`，固定 `build` 与 `dist_release_current`，隔离 PATH 防止外来 ICU DLL。FFmpeg 是已声明的外部构建输入。
- Inno 从冻结版 product.json 读取版本并与源码/显式参数比对，缺失或错配即停止；版本不能悄悄默认 1.0.0。只读 `-ValidateOnly` 可在编译前检查。
- 正式资产名 `NanfengTranscriber-Windows-v<version>-Setup.exe`，必要 SHA256SUMS；Windows 默认未签名，实际状态如实披露。README 展示当前真实截图，Release 不展示截图。
- 最终 README、元数据和收据更新后再运行 `tools/check_project_contracts.py`、完整测试、相关构建/安装检查。冻结最终文件后记录字节和 SHA-256，若重建需重新验证；远端核对标签提交、发布状态、文件名/大小/摘要。
- 验证等级分别是源码/自动测试、冻结版、隔离安装、真实媒体/API和发布。历史测试计数和截图不是当前通过证明。已发布收据不可由源码整理覆盖改写。
