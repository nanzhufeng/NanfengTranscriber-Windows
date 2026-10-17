"""The two user-facing local transcription modes and fixed aligner."""

LOCAL_MODE_OPTIONS = ["中文精确", "通用快速"]
CLOUD_MODELS = {"高精度 Qwen": "qwen-audio-3.1-asr-flash-filetrans", "低成本 Paraformer": "paraformer-v2"}
MODE_OPTIONS = LOCAL_MODE_OPTIONS + list(CLOUD_MODELS)
QWEN_MODEL = "Qwen/Qwen3-ASR-1.7B-hf"
ALIGNER_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
FAST_MODEL = "large-v3-turbo"
MODE_MODEL_LABELS = {
    "中文精确": "Qwen3-ASR-1.7B",
    "通用快速": "Whisper large-v3-turbo",
    **CLOUD_MODELS,
}


def model_for_mode(value: str) -> str:
    if value in CLOUD_MODELS:
        return CLOUD_MODELS[value]
    if value in ("中文精确", "qwen3-asr"):
        return "qwen3-asr"
    if value in ("通用快速", "turbo", "base", "small", "medium", "large-v3"):
        return "turbo"
    raise ValueError(f"未知转写模式：{value}")


def mode_description(value: str) -> tuple[str, str]:
    if value in CLOUD_MODELS:
        return (f"{value}：通过阿里云百炼进行文件转写，音频将上传云端，可能产生费用。",
                f"真实模型：{CLOUD_MODELS[value]} · 使用设置中的百炼 API Key")
    if model_for_mode(value) == "qwen3-asr":
        return (
            "中文精确：优先处理中文口播、方言与中英混合，忠实保留原话；导出字幕时增加时间对齐，耗时较多。",
            "真实模型：Qwen3-ASR-1.7B · 字幕对齐：Qwen3-ForcedAligner-0.6B（按需加载）",
        )
    return (
        "通用快速：适合日常批量和多语言素材，优先处理速度；使用词级时间戳生成短字幕。",
        "真实模型：Whisper large-v3-turbo · 本地 faster-whisper 引擎",
    )
