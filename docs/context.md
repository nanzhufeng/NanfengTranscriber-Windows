# 南枫转写 Windows：架构与开发入口

产品行为的唯一正文是 [CONTRACTS.md](CONTRACTS.md)，动态验证见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。本页只维护结构与依赖方向。

| 职责 | 唯一所有者 | 消费者/公开入口 |
|---|---|---|
| 产品名、版本、开发时间、仓库 | `app/assets/product.json` | `app/product_info.py`、关于窗口、Inno 构建 |
| 两种本地/两种云端模式、模型显示与旧值兼容 | `app/model_modes.py` | 主模式输入框、队列、转写会话 |
| 队列、QSettings、窗口与完成反馈 | `app/main.py` | 文件/文件夹/拖放、开始/停止、设置 |
| 本地历史快照、筛选、编辑与删除边界 | `app/history.py` | 完成事件、历史页面；SQLite v1 |
| 嵌入播放器、全屏、续播与画面内控件 | `app/media_player.py` | 历史核对页；复用 Qt Multimedia，不新增运行时 |
| 历史日期卡片、详情、重新导出与媒体核对 | `app/history_ui.py` | 侧栏历史入口、右侧页面栈 |
| 单文件转写用例、输出命名、GPU 探测、字幕 | `app/transcriber.py` | Worker、已有结果检查、开发 QA CLI |
| 独立进程与本地 JSON 协议 | `app/qwen_bridge.py` | Qwen 识别、快速模式精确对齐 |
| Qwen 模型加载、识别与对齐 | `app/qwen_worker.py` | 独立 Python stdin/stdout；不依赖 Qt |
| 百炼文件转写、任务恢复与协议校验 | `app/cloud_asr.py` | 转写 Session，复用原有导出/历史 |
| Windows 用户加密 API Key | `app/cloud_credentials.py` | 设置与批次启动，不进入文稿/恢复文件 |
| 后台文件发现与时长探测 | `app/media_probe.py` | 工作台添加文件，持久索引通知 |
| 可选文本 API 与中文错误 | `app/postprocess.py` | TXT/Markdown/DOCX 的润色文本 |
| 主环境/独立模型环境/打包工具版本 | 三份 `requirements*.txt` | 源码安装、运行环境安装、构建 |
| 构建、安装与资源 | `scripts/build_windows_app.ps1`、`build_windows_installer_inno.ps1`、`installer/*.iss` | 当前 Windows 正式路径 |

数据流：`start.py → MainWindow → TranscribeWorker → TranscriptionSession → transcribe_file → 文档文件 → 队列反馈/定位`。

GUI 与运行时是单向依赖：版本和模型目录不依赖 Qt；推理核心不读取界面状态。既有结果检查和导出共用 `resolve_output_directory`；UI GPU 预检查复用 `gpu_libraries_available`。

## 开发验证

```powershell
python -m pip install -r requirements.txt
python tools/check_project_contracts.py
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s tests
```

构建环境另用 `requirements-build.txt`。Qwen 使用独立环境及 `requirements-qwen.txt`，Torch 版本和 CUDA wheel 索引由 `scripts/setup_qwen_runtime.ps1` 定义。不要把 Qwen/Torch 安装进主包构建环境。

```powershell
./scripts/build_windows_app.ps1
./build_windows_installer_inno.ps1 -ValidateOnly
./build_windows_installer_inno.ps1
```

构建使用固定缓存并隔离 PATH；Inno 从冻结版自己的 metadata 取版本，与源码核对，不接受错配版本。`-SourceAppPath` 可显式选择应用目录；`-ValidateOnly` 只读校验，不创建安装包。PS1 使用 UTF-8 BOM 兼容 Windows PowerShell 5 和 PowerShell 7。

所有 UI 资源归本项目 `app/assets`；FFmpeg/FFprobe 构建输入仍为仓库外 `../JHlib/ffmpeg`，打包到 `tools/ffmpeg`。缺失是构建条件缺口，不能伪造已包含。

历史设计、性能与旧交接见 [HISTORY.md](HISTORY.md)，不作为当前默认模型、发布形式或签名规则。macOS 迁移尚未实施，见 [迁移提示](MAC_CODEX_START_PROMPT.md)。
