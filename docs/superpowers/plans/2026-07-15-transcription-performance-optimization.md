# 转录性能均衡优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 UI、导出结构和队列操作的前提下，通过队列级模型复用、GPU 批量推理和受控降级，使固定三文件基准队列总耗时至少降低 30%。

**Architecture:** 在 `app/transcriber.py` 新增队列级 `TranscriptionSession`，集中拥有模型缓存、`BatchedInferencePipeline`、批量大小记忆和 GPU/CPU 降级状态；`TranscribeWorker` 每次队列只创建一个会话并传给所有文件。文件级音频提取和导出逻辑保持原位，推理调用改由会话执行。

**Tech Stack:** Python 3.13、PySide6、faster-whisper 1.2.1、CTranslate2 4.8.1、FFmpeg、标准库 `unittest`、Windows RTX 4090 CUDA 环境。

## Global Constraints

- 项目根目录固定为 `D:\CodexProjects\江湖工具箱\VideoTranscriber`。
- 不改 UI 布局、默认 `medium` 模型、输出目录结构、文件命名、已有结果跳过逻辑和翻译/润色模块。
- 首版不做多文件并发，不新增性能设置，不改 FFmpeg 音频提取方式。
- GPU 使用 `float16`，CPU 使用 `int8`；默认 `batch_size=8`、`beam_size=3`。
- 只有显存/批处理资源错误才按 `8 -> 4 -> 2 -> 普通 GPU` 降级；只有明确 CUDA/cuBLAS/cuDNN/GPU 运行时错误才回退 CPU；普通媒体或业务错误原样抛出。
- 当前目录不是 Git 仓库。每个任务以“测试通过 + 变更文件清单”作为 checkpoint，不初始化 Git、不伪造 commit。
- 所有自动化测试必须在无真实 GPU、无模型下载条件下运行；真实 GPU 仅用于最后基准验证。

---

### Task 1: 建立可重复的性能基准

**Files:**
- Create: `tools/benchmark_transcription.py`
- Create on execution: `docs/superpowers/benchmarks/2026-07-15-baseline.json`

- [ ] **Step 1: 编写固定样本基准脚本**

脚本固定使用以下三个只读样本：

```python
SAMPLES = [
    Path(r"D:\南烛枫视频下载器\Douyin\美静讲故事1\2021-12-24 加油小公主的看过了 ，这几个字最适合女孩取#名字#取名 #家有萌娃 #易学 #豆荚小助手 #上热门.mp4"),
    Path(r"D:\南烛枫视频下载器\Douyin\美静讲故事1\2022-01-11 大舍大得小舍小得#修行 #出马 #中华文化 #禅修 #宝宝起名 #好运.mp4"),
    Path(r"D:\南烛枫视频下载器\Douyin\美静讲故事1\2022-01-13 离婚到底是因为婚姻有裂痕还是小三真新鲜#出马 #出马 #八字 #出轨 #2022 #内容太过真实.mp4"),
]
```

脚本要求：

1. 接收 `--label` 与 `--result` 参数。
2. 使用 `medium`、`中文`、`GPU 优先`，仅启用 TXT，关闭润色。
3. 使用 `TemporaryDirectory` 存放导出结果，不污染用户正式输出目录。
4. 在优化前没有 `TranscriptionSession` 时直接逐文件调用 `transcribe_file`；优化后检测到该类时，只创建一次会话并传给三个文件。
5. 记录每个文件耗时、队列总耗时、状态、转写字符数、前 500 字抽查文本、进程峰值 GPU 显存、Python/faster-whisper/ctranslate2 版本。
6. 任一文件失败时写入 JSON 错误详情并返回非零退出码，不把失败基准当作有效性能数据。

- [ ] **Step 2: 运行优化前基准**

Run:

```powershell
python tools\benchmark_transcription.py --label baseline --result docs\superpowers\benchmarks\2026-07-15-baseline.json
```

Expected: 三个文件均成功，JSON 包含 `total_seconds`、`peak_gpu_memory_mb` 和三个 `samples`；命令退出码为 0。

- [ ] **Step 3: 检查基准有效性**

Run:

```powershell
python -m json.tool docs\superpowers\benchmarks\2026-07-15-baseline.json > $null
```

Expected: 退出码为 0。若 GPU 实际回退 CPU，停止性能实施并先修复 GPU 环境，不能用 CPU 基准冒充 GPU 基准。

**Checkpoint:** 只新增基准脚本和基准 JSON；尚未修改生产转写逻辑。

---

### Task 2: 用测试锁定模型复用契约

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_transcription_session.py`
- Modify: `app/transcriber.py:1-30,333-450`

- [ ] **Step 1: 先写失败测试**

测试使用可注入的假模型类，覆盖：

```python
class FakeModel:
    created: list[tuple[str, str, str]] = []

    def __init__(self, model_size, *, device, compute_type):
        self.created.append((model_size, device, compute_type))


def test_same_runtime_is_loaded_once(self):
    session = TranscriptionSession(
        model_class=FakeModel,
        batched_pipeline_class=FakePipeline,
    )
    first = session.get_runtime(self.gpu_options, self.progress)
    second = session.get_runtime(self.gpu_options, self.progress)
    self.assertIs(first.model, second.model)
    self.assertEqual(FakeModel.created, [("medium", "cuda", "float16")])


def test_different_models_have_separate_cache_entries(self):
    session = TranscriptionSession(
        model_class=FakeModel,
        batched_pipeline_class=FakePipeline,
    )
    session.get_runtime(self.gpu_options, self.progress)
    session.get_runtime(replace(self.gpu_options, model_size="small"), self.progress)
    session.get_runtime(self.gpu_options, self.progress)
    self.assertEqual(len(FakeModel.created), 2)
```

Run:

```powershell
python -m unittest tests.test_transcription_session -v
```

Expected: FAIL，原因是 `TranscriptionSession` 尚不存在。

- [ ] **Step 2: 实现最小队列级会话和缓存**

在 `app/transcriber.py` 新增：

```python
@dataclass
class LoadedRuntime:
    model: Any
    pipeline: Any | None
    device: str
    compute_type: str


class TranscriptionSession:
    def __init__(self, model_class=None, batched_pipeline_class=None) -> None:
        self._model_class = model_class
        self._batched_pipeline_class = batched_pipeline_class
        self._runtimes: dict[tuple[str, str, str], LoadedRuntime] = {}
        self._preferred_batch_sizes: dict[tuple[str, str, str], int] = {}
        self._force_cpu = False

    def get_runtime(
        self,
        options: TranscribeOptions,
        progress_callback: ProgressCallback,
    ) -> LoadedRuntime:
        ...

    def close(self) -> None:
        self._runtimes.clear()
        self._preferred_batch_sizes.clear()
        gc.collect()
```

实现约束：

- 实际 faster-whisper 类延迟导入，避免单元测试加载模型。
- 缓存键严格为 `(model_size, device, compute_type)`，语言不进入缓存键。
- `CPU 稳定` 或 `_force_cpu=True` 时选择 `cpu/int8`，否则选择 `cuda/float16`。
- 保留 `_add_nvidia_dll_directories()` 与 `_has_windows_cuda_runtime()` 检查。
- GPU 模型加载错误只在 `_is_gpu_runtime_error()` 为真时切换 CPU；其他异常原样抛出。
- `close()` 只释放本会话持有对象，不修改用户文件和全局设置。

- [ ] **Step 3: 运行模型缓存测试**

Run:

```powershell
python -m unittest tests.test_transcription_session -v
```

Expected: 模型复用相关测试 PASS。

**Checkpoint:** `TranscriptionSession` 已能复用模型，但生产 `transcribe_file` 尚未切换到批量推理。

---

### Task 3: 以 TDD 实现 GPU 批量推理和受控降级

**Files:**
- Modify: `tests/test_transcription_session.py`
- Modify: `app/transcriber.py:333-450`

- [ ] **Step 1: 写批量推理与降级失败测试**

新增四组契约：

1. GPU 首次使用 `batch_size=8`、`beam_size=3`。
2. 假管线在 8 抛 `CUDA out of memory`、在 4 成功时，尝试顺序严格为 `[8, 4]`。
3. 上一文件在 4 成功后，下一文件直接从 4 开始，不重复尝试 8。
4. `ValueError("invalid media")` 不得降级或回退 CPU，必须原样抛出。

关键测试结构：

```python
def test_gpu_batch_size_falls_back_and_is_remembered(self):
    FakePipeline.failures = {8: RuntimeError("CUDA out of memory")}
    session = self.make_session()
    first = session.transcribe_audio(self.audio, 30.0, self.gpu_options, self.progress)
    second = session.transcribe_audio(self.audio, 30.0, self.gpu_options, self.progress)
    self.assertEqual(FakePipeline.batch_calls, [8, 4, 4])
    self.assertTrue(first)
    self.assertTrue(second)


def test_non_gpu_error_is_not_swallowed(self):
    FakePipeline.failures = {8: ValueError("invalid media")}
    with self.assertRaisesRegex(ValueError, "invalid media"):
        self.make_session().transcribe_audio(
            self.audio, 30.0, self.gpu_options, self.progress
        )
```

Run:

```powershell
python -m unittest tests.test_transcription_session -v
```

Expected: 新测试 FAIL，原因是批量推理接口尚未实现。

- [ ] **Step 2: 实现错误分类和统一推理入口**

在 `app/transcriber.py` 新增并作为唯一判定入口：

```python
def _is_gpu_runtime_error(error_text: str) -> bool:
    message = error_text.lower()
    return any(
        keyword in message
        for keyword in ("cuda", "cublas", "cudnn", "cudart", "gpu")
    )


def _is_gpu_batch_resource_error(error_text: str) -> bool:
    message = error_text.lower()
    return any(
        keyword in message
        for keyword in (
            "out of memory",
            "cuda_error_out_of_memory",
            "failed to allocate",
            "cublas_status_alloc_failed",
            "allocation failed",
        )
    )
```

新增 `TranscriptionSession.transcribe_audio(...)`：

- 构建现有语言、VAD、temperature、简体中文 initial prompt 参数。
- `beam_size` 从 5 改为 3。
- GPU 依次尝试当前已记忆批量大小或 `8, 4, 2`。
- `BatchedInferencePipeline.transcribe(..., batch_size=batch_size, **kwargs)` 返回的延迟迭代器必须在 `try` 内完整遍历，因为 CUDA 错误可能在迭代时才发生。
- 某次失败后丢弃该次不完整 segments，再从当前文件开头重试，不能混合两次结果。
- 三档批量都发生资源错误后使用同一 GPU 模型执行普通 `model.transcribe(...)`。
- 明确 GPU 运行时错误时设置 `_force_cpu=True`，发出带 `force_cpu=True` 的现有进度通知，再用缓存的 CPU/int8 模型重试。
- 普通错误立即抛出。
- 每个 segment 继续调用取消检查和现有进度计算。

- [ ] **Step 3: 运行会话全部测试**

Run:

```powershell
python -m unittest tests.test_transcription_session -v
```

Expected: 模型复用、批量大小、降级顺序、错误透传全部 PASS。

**Checkpoint:** 批量推理核心已通过无 GPU 单元测试；尚未接入 Worker。

---

### Task 4: 接入文件级转写与队列 Worker

**Files:**
- Create: `tests/test_transcribe_worker.py`
- Modify: `app/transcriber.py:393-470`
- Modify: `app/main.py:35-47,164-240`

- [ ] **Step 1: 写会话生命周期和停止行为失败测试**

测试契约：

1. `transcribe_file(..., session=session)` 使用传入会话且不自行关闭。
2. 未传 session 时创建临时会话，并在成功或异常后关闭。
3. `TranscribeWorker` 整个队列只创建一个会话。
4. 用户停止后不启动下一文件，`all_done` 只发送一次。

使用 `unittest.mock.patch` 替换模型、音频提取和 `transcribe_file`，不打开 GUI 窗口、不访问真实媒体。

Run:

```powershell
python -m unittest tests.test_transcribe_worker -v
```

Expected: FAIL，原因是当前函数不接受 `session`，Worker 也不持有会话。

- [ ] **Step 2: 修改 `transcribe_file` 的兼容签名**

签名调整为：

```python
def transcribe_file(
    source: Path,
    options: TranscribeOptions,
    progress_callback: ProgressCallback,
    cancel_callback: CancelCallback | None = None,
    session: TranscriptionSession | None = None,
) -> TranscribeResult:
```

行为要求：

- 音频提取完成后调用 `active_session.transcribe_audio(...)`。
- `session is None` 时创建临时会话，并在 `finally` 中关闭，保留其他调用方兼容性。
- 传入会话时由 Worker 负责关闭，`transcribe_file` 不越权释放。
- TXT、Markdown、SRT、DOCX、润色及输出路径代码不改。

- [ ] **Step 3: 让 Worker 一次队列只创建一个会话**

`app/main.py`：

- 导入 `TranscriptionSession`。
- 删除本地重复 `_is_gpu_runtime_error()`。
- `run()` 开始时创建 `session = TranscriptionSession()`。
- 每个 `transcribe_file` 调用都传 `session=session`。
- 删除 Worker 内第二套 GPU 失败后 CPU 重跑分支，回退统一由会话负责。
- 使用 `try/finally` 保证停止、失败和完成都调用 `session.close()`，随后仅发送一次 `all_done`。

- [ ] **Step 4: 运行 Worker 与会话测试**

Run:

```powershell
python -m unittest tests.test_transcription_session tests.test_transcribe_worker -v
```

Expected: 全部 PASS；停止测试证明第二个文件未被调用。

**Checkpoint:** 生产队列已经使用单一会话；UI 信号名称和表格逻辑未改。

---

### Task 5: 锁定导出回归和源码启动

**Files:**
- Create: `tests/test_transcriber_outputs.py`
- Modify only if test exposes regression: `app/transcriber.py`

- [ ] **Step 1: 添加输出回归测试**

使用临时目录、假会话和固定 segments：

```python
SEGMENTS = [
    {"start": 0.0, "end": 1.2, "text": "大家好。"},
    {"start": 1.2, "end": 3.4, "text": "这是转写测试。"},
]
```

覆盖：

- TXT、Markdown、SRT、DOCX 均生成在 `output_dir/safe_stem/`。
- 文件名与优化前一致。
- SRT 时间码和 Markdown 结构不变。
- 会话返回空 segments 时仍显示现有“没有识别到可导出的文字”错误。

- [ ] **Step 2: 运行完整自动化测试**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: 全部 PASS，无真实模型下载、无 GPU 依赖。

- [ ] **Step 3: 做语法和导入检查**

Run:

```powershell
python -m compileall app tests tools
python -c "from app.main import TranscribeWorker; from app.transcriber import TranscriptionSession; print('imports OK')"
```

Expected: 两条命令退出码均为 0，输出 `imports OK`。

- [ ] **Step 4: 启动源码 BAT 做最小界面验证**

Run:

```powershell
Start-Process -FilePath '.\启动南烛枫视频转文字_源码测试.bat'
```

人工检查：窗口能打开、标题和现有 UI 不变、无闪退。完成后正常关闭窗口，不扩大 UI 测试范围。

**Checkpoint:** 自动化回归、导入和源码启动均通过；仍未宣称真实转写性能达标。

---

### Task 6: 真实 GPU 性能与质量验收

**Files:**
- Create on execution: `docs/superpowers/benchmarks/2026-07-15-optimized.json`
- Modify: `docs/superpowers/specs/2026-07-15-transcription-performance-optimization-design.md`
- Modify: `docs/chatgpt-project-context.md`

- [ ] **Step 1: 运行优化后相同基准**

Run:

```powershell
python tools\benchmark_transcription.py --label optimized --result docs\superpowers\benchmarks\2026-07-15-optimized.json
```

Expected: 三个相同样本均成功，GPU 未回退 CPU，命令退出码为 0。

- [ ] **Step 2: 计算总耗时改善率**

Run:

```powershell
python -c "import json; from pathlib import Path; b=json.loads(Path(r'docs/superpowers/benchmarks/2026-07-15-baseline.json').read_text(encoding='utf-8')); o=json.loads(Path(r'docs/superpowers/benchmarks/2026-07-15-optimized.json').read_text(encoding='utf-8')); gain=(b['total_seconds']-o['total_seconds'])/b['total_seconds']*100; print(f'{gain:.1f}%'); raise SystemExit(0 if gain >= 30 else 1)"
```

Expected: 输出不低于 `30.0%`，退出码为 0。

- [ ] **Step 3: 抽查质量与边界行为**

对比两个 JSON 中每个样本的 `text_preview`：

- 人名、数字、核心句意无明显退化。
- 允许标点、分段和少量同音词差异。
- 测试一次“停止”，确认当前批次返回后退出且不启动下一文件。
- 将模式切到 `CPU 稳定`，用 25 秒样本验证 CPU/int8 路径能完成；不重复跑完整 20 分钟 CPU 基准。

- [ ] **Step 4: 更新项目事实文档**

在设计文档和 `docs/chatgpt-project-context.md` 中明确分栏记录：

- 已实现：模型复用、GPU 批量推理、自动降级。
- 自动化测试通过：列出测试命令和数量。
- 本机真实验证：RTX 4090、三样本总耗时、改善率、峰值显存。
- 待验证风险：其他显卡的实际降级档位、超长音频表现。
- 不得把源码测试通过写成安装包已更新；本任务不打包 EXE。

## Completion Stop Condition

满足以下条件立即停止扩大范围：

1. `python -m unittest discover -s tests -v` 全部通过。
2. 源码 BAT 可启动且 UI 无变化。
3. 三个固定样本优化后总耗时降低至少 30%。
4. 文本抽查无明显质量下降。
5. GPU 回退、CPU 路径和停止行为完成最小验证。

若改善率不足 30%，只记录测量结果并返回设计阶段评估“音频预提取流水线”；不得在本轮直接加入多文件并发。

## 执行状态（2026-07-15）

- [x] 固定三样本基准、优化前 JSON 与优化后 JSON 已生成。
- [x] 建立会话缓存、GPU 批量推理、受控降级和 Worker 生命周期测试。
- [x] 保持既有导出回归，完整测试、编译、导入和无界面窗口构造检查通过。
- [x] RTX 4090 三样本基准：130.499 秒 -> 28.403 秒，改善 78.2%，达到至少 30% 的验收线。
- [x] CPU / int8 使用 25 秒真实样本完成最小验证。
- [x] 性能与质量边界已写回设计和项目上下文文档。
- [ ] 未进行新的 EXE / 安装包构建；该事项不属于本轮性能优化范围。
