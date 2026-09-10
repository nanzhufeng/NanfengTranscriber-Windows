# 当前接手状态：南枫转写

> 更新日期：2026-09-10
> 适用分支：`main`（对应 GitHub Windows 仓库 `nanzhufeng/NanfengTranscriber-Windows`）
> 当前平台事实：Windows 源码已验证；macOS 尚未实施。

## 先读什么

1. `AGENTS.md`
2. `docs/context.md`
3. `docs/development-experience-audit.md`
4. 本文件
5. `docs/chatgpt-project-context.md`
6. `git status --short`

本项目不是视频下载器，也不是南枫记。不要从其他项目带入下载、登录、Android 或记账逻辑。

## 2026-09-10：可选视频子文件夹（源码变更）

- 默认直接把 TXT、Markdown、SRT、DOCX 保存到所选输出目录，保留视频文件名。
- 设置新增“新建视频同名子文件夹”，默认关闭，保存后跨启动恢复；开启后沿用按视频分目录。
- 实际导出与已有结果检查使用相同开关；不迁移或删除历史输出。
- 36 项自动测试通过，覆盖两种输出结构、设置持久化、已有结果跳过；未重新打包或发布，未进行真实媒体转写验收。
- 上下文门禁已尝试执行，但本机缺少 `.codex/bin/codex_thread_token_audit.py`，未能完成统计。

## 2026-09-10：SRT 时间线与短字幕（源码变更）

- 导出 SRT 时启用并保留模型逐词时间戳；按句末、停顿、24 字符上限和 5 秒上限拆分字幕，裁剪相邻重叠时间以防叠加。
- 无逐词时间戳的兼容输入只在原片段时间内按文字比例拆分，该回退不是精确逐词对齐。
- 39 项回归测试、编译和差异检查通过；新增长字幕拆分、停顿及时间重叠测试。尚未用真实媒体和播放器验证或重新打包。

## 2026-09-10：保存到视频所在目录（源码变更）

- 设置新增“保存到视频所在目录”，默认不勾选，继续使用主界面指定路径；勾选后每项分别使用源视频父目录。
- 与“新建视频同名子文件夹”组合生效并持久化。导出和已有结果检查共用 `resolve_output_directory`，源目录模式不创建指定输出目录。
- 40 项测试、编译和差异检查通过；四种目录组合使用隔离样本完成实际文档导出。尚未重新打包或做真实视频端到端验收。

## Windows v1.0.3 发布验证

- 40 项自动测试通过。首次打包复现 QtCore DLL 加载失败；隔离 PATH 后重新构建成功，已通过隐藏窗口枚举确认标题“南枫转写”及进程响应。
- Windows SAPI 生成的独立中文样本通过 medium CPU/GPU 转写并输出短条 SRT；CPU 保留句间停顿。属于合成语音实际推理验证，不等同于人工真实视频播放器验收。
- 最终安装包 `NanfengTranscriber-Windows-v1.0.3-Setup.exe`：SHA-256 `51D9645999178D78FE490CB55E9B8C74A2ECB3631967F57AFA8F72EA82ED005D`。隔离安装、启动、媒体工具执行、退出、卸载均通过，原安装登记已恢复。发布合同 14 项通过。
- 发布等价源码界面预览位于 `docs/preview-v1.0.3.png`，使用隔离演示数据。
- 凭据模式扫描未发现命中；Release 只上传 Setup EXE，不上传测试媒体或日志。

## 已实现

- Python + PySide6 桌面工作台：批量添加文件和文件夹、拖入导入、逐项选择、队列状态、总进度、总剩余时间。
- 本地转写：faster-whisper + FFmpeg；导出 TXT、Markdown、SRT、DOCX。
- 可选“翻译润色”：通过文本 API 整理成现代简体中文；没有 API Key 时不能把它当成纯本地能力。
- 模型选项按 `base -> small -> medium -> large-v3`；默认 `medium`，语言默认中文，模式默认 GPU 优先。
- 既有结果处理：Yes 覆盖后继续；No 标记“已存在”并继续剩余任务。
- 输出路径和文件名已做 Windows 长路径保护。
- Whisper 模型成功下载后长期保存在 `%LOCALAPPDATA%\NanfengTranscriber\models`，跨软件启动、升级和重装复用；缓存损坏时自动联网修复。

## 最近完成：性能优化

- 新增 `TranscriptionSession`，整个队列复用模型与 GPU 推理管线。
- GPU 使用 `BatchedInferencePipeline`，默认 `batch_size=8`、`beam_size=3`，按 `8 -> 4 -> 2 -> 普通 GPU -> CPU` 受控降级。
- 只在明确 CUDA/cuBLAS/cuDNN/GPU 运行时错误时回退 CPU；CPU 使用 `int8` 并复用模型。
- `TranscribeWorker` 仅创建一个会话；停止后不再启动下一项。

## 最近完成：安装版启动修复与 GitHub 首版

- 修复 PyInstaller 安装版点击“开始转写”后可能停在主线程、没有进入 Worker 的问题。
- 冻结版不再通过 `find_spec` 扫描已打包依赖和外部 NVIDIA Python 包；保留 PATH 与系统 CUDA DLL 检测。
- 新增冻结运行时回归测试，并为依赖扫描、GPU 检测和 Worker 启动增加诊断日志。
- GitHub Windows 仓库固定命名为 `nanzhufeng/NanfengTranscriber-Windows`；首版为 `v1.0.0`，下一次正式发布目标为 `v1.0.1`（设置记忆、逐项定位、结束反馈）。
- 跨平台仓库必须在名称中明确平台：Windows 使用 `NanfengTranscriber-Windows`，Android 使用 `NanfengTranscriber-Android`；应用内产品名统一为“南枫转写”。

## 最近完成：正式开发经验沉淀

- 新增 `docs/context.md`，作为当前技术栈、目录结构和工程事实入口。
- 新增 `docs/development-experience-audit.md`，记录最终基准、反馈—原因—实现—验证矩阵、失败经验和遗留风险。
- 新增已有结果回归测试，锁定“选择 No 跳过已有结果后继续剩余任务”的队列合同。
- 更新用户级 `nanzhufeng-tool-standard`，补充批量媒体/本地 AI 运行时、性能、交付、正式复盘模板和 Release 合同检查脚本。

## 最近完成：API、DPI、安装器与模型缓存

- `app/postprocess.py` 已区分缺 Key、401/403 鉴权失败、请求超时、连接失败、空内容和格式异常；不再回显服务端原始响应。
- 新增 100%、125%、150%、200% 四档 Windows UI 截图基线、生成脚本与 SHA-256 清单测试。
- 新增 Inno Setup 6 工程和构建脚本；用户级 Inno 编译器路径和注册表路径均可自动发现。
- Inno 安装器已在独立临时目录完成静默安装、主 EXE 检查、卸载和残留清理。
- 模型缓存改为用户级持久目录；首次成功后写完成标记，后续强制本地加载，损坏时只联网修复一次。

## 最近完成：设置记忆、逐项定位与结束反馈

- 保存位置、模型、语言、GPU/CPU 模式、TXT/Markdown/SRT/DOCX 和翻译润色选项已通过用户级 `QSettings` 持久化，重启后恢复上次设置；转写队列本身不持久化。
- 列表最右侧新增居中的“定位”图标按钮：完成后优先在文件管理器中选中实际导出文件，尚未导出时定位源媒体文件。
- 转写批次结束后显示结果摘要：全部成功为绿色提示，存在失败或无文字时为红色提示，主动停止使用中性提示。
- 源媒体路径与实际导出文件路径已拆分为独立数据角色，错误文本不再覆盖定位依据。
- Windows 定位调用使用 `explorer.exe /select, <完整路径>` 的独立参数形式，避免中文或空格路径被 Explorer 误解析。
- 结束反馈改为“转写结果”统计面板，按成功、失败、跳过、停止分色统计，跳过已有结果会计入本次汇总。

## 最近完成：完成提示音与通知设置

- 侧栏新增“设置”入口，设置通过用户级 `QSettings` 持久化。
- 批次有成功、失败或无文字结果时，默认播放约 0.3 秒的低音量双音提示；成功与失败采用不同音调，主动停止不播放提示音。
- 设置可单独开关：完成提示音、批次结束结果摘要、完成后自动打开目录；自动打开默认关闭，避免打断工作流。启用后会在资源管理器中定位并选中本批次最近完成的实际导出文件，而非只打开输出根目录。
- 提示音在内存中生成，不依赖联网、额外音频文件或大型多媒体运行库；Windows 使用 `winsound`，其他平台回退到 Qt 系统提示音。

## 本次发布：Windows v1.0.2

- 发布标签：`v1.0.2`；应用内产品名保持“南枫转写”，仓库与发布资产明确标注 Windows。
- 已生成可点击安装程序：`NanfengTranscriber_Windows_v1.0.2_Setup_20260823_185621.exe`。
- Setup EXE SHA-256：`41B2B7CBA3FC3240CC95BF4F68BFE99ED2F6DFBA65867779853D3C15479E091E`。
- GitHub Release 只上传 Windows Setup EXE，不再上传 ZIP 或额外 TXT；安装说明保留在 README。已在独立临时目录静默安装、验证主 EXE、FFmpeg、FFprobe 和窗口标题，随后卸载并确认无残留文件。

## 最近验证

### 已在真实 Windows 环境验证

- RTX 4090、`medium`、中文、GPU 优先、关闭润色、三个固定样本：`130.499 秒 -> 28.403 秒`，改善 `78.2%`。
- CPU 稳定 / int8：25 秒真实样本完成，耗时 `6.906 秒`。
- PyInstaller 性能版 EXE 已短暂启动，标题为 `南枫转写`。
- 已从本轮最新源码重建 PyInstaller 目录，主 EXE 实际启动后标题正确且界面响应正常。
- 新 Inno Setup 安装包已在独立临时目录完成静默安装、启动、卸载和残留清理。

### 已在自动化或源码层验证

- `python -m unittest discover -s tests -v`：36 项通过，包含 API、DPI、Inno、直接 EXE 发布合同、持久模型缓存、设置记忆、逐项定位、结束反馈、完成声音、自动定位和无音轨诊断回归。
- `python -m compileall app tests tools`：通过。
- `TranscribeWorker` 与 `TranscriptionSession` 导入通过。
- 无界面窗口构造检查通过；它不替代人工可视 UI 验收。
- `启动南枫转写_Windows_源码测试.bat` 冒烟通过：Python 进程保持运行，日志写入 `app started`，未闪退；新增定位列已完成 offscreen 布局检查。
- GitHub 首版 PyInstaller EXE 已启动验证：进程正常响应、标题正确，FFmpeg/FFprobe 均包含在运行目录中。
- 当前待发布安装程序使用平台明确的 Setup EXE；SHA-256 见“本次发布：Windows v1.0.2”。

## 已知边界与风险

1. 批量管线不能传中文 `initial_prompt`：faster-whisper 会将其注入每个批次窗口，实测会造成提示词泄漏和漏字。GPU 批量路径因此优先原始转写正确性。
2. 批量原始转写不能保证繁体、英文、文言自动转为现代简体中文；需要时开启“翻译润色”并配置 API。
3. 其他显卡、低显存设备与超长音频的实际批量降级和停止响应尚未实测。
4. Windows Setup 仍未做代码签名，可能触发 SmartScreen；正式构建入口已换为 Inno Setup，IExpress 仅保留历史回退。
5. 当前 PyInstaller spec 引用了 `..\\JHlib\\ffmpeg`，该外部 Windows 依赖不在 Git 迁移包内。
6. API 测试目前是模拟服务；真实 API 费用、限流和服务波动仍需单独验证。
7. 多 DPI 基线为 offscreen 固定截图；真实多显示器跨屏缩放仍未验证。
8. 新安装包尚未在全新、无 Python 和开发工具的 Windows 电脑上做外部验收。

## Mac 迁移的下一件最小任务

先不要直接打包 `.app`。在 Mac 上完成以下最小闭环：

1. 检查 macOS 架构、Python、pip、FFmpeg/FFprobe、PySide6、faster-whisper、ctranslate2、huggingface_hub、python-docx、PyInstaller。
2. 将 Windows 路径、FFmpeg 查找、CUDA/DLL 逻辑隔离为平台适配层。
3. 生成 `.command` 启动脚本，修复权限、隔离环境和换行问题后确认窗口能打开。
4. 仅在 `.command` 跑通后才考虑 PyInstaller `.app`、ad-hoc codesign 和 ZIP。

完整可复制提示词见 `docs/MAC_CODEX_START_PROMPT.md`。
