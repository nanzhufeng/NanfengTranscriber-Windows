"""Standalone JSON-lines worker for native Transformers Qwen ASR/alignment."""
import json
import sys
import wave
from pathlib import Path


def emit(message):
    print(json.dumps(message, ensure_ascii=False), flush=True)


def aligned_words(text, words, offset, end):
    """Keep the original punctuation/spaces and reject unusable timestamps."""
    matches = []
    cursor = 0
    for word in words:
        token = word["text"].strip()
        if not token:
            continue
        position = text.casefold().find(token.casefold(), cursor)
        if position < 0 or text[cursor:position].strip(" \t\r\n，。！？、；：,.!?;:—-（）()\"“”‘’'"):
            raise RuntimeError("对齐文字与原稿不一致，为避免丢字未生成字幕。")
        start_time = offset + max(0, float(word["start_time"]))
        end_time = min(end, offset + float(word["end_time"]))
        if end_time <= start_time:
            raise RuntimeError("对齐器返回无效时间，请关闭精确字幕或更换模式重试。")
        matches.append((position, start_time, end_time))
        cursor = position + len(token)
    if not matches or text[cursor:].strip(" \t\r\n，。！？、；：,.!?;:—-（）()\"“”‘’'"):
        raise RuntimeError("对齐结果缺少文字，为避免丢字未生成字幕。")
    result = []
    for i, (position, start, finish) in enumerate(matches):
        next_position = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        content = text[position:next_position].rstrip()
        if position and text[position - 1].isspace():
            content = " " + content
        result.append({"text": content, "start": start, "end": finish})
    return result


class LocalEngine:
    def __init__(self):
        self.models = {}

    def load(self, repo, device, cache, aligner=False, progress=3):
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoProcessor, AutoModelForMultimodalLM, AutoModelForTokenClassification
        key = (repo, device)
        if key in self.models:
            return self.models[key]
        patterns = ["*.json", "*.safetensors", "*.txt", "*.jinja"]
        emit({"status": "loading_model", "progress": progress, "eta": "检查本地模型缓存", "notice": f"正在检查 {repo}，缺少文件时下载，完成后本地复用。"})
        try:
            path = snapshot_download(repo, cache_dir=cache, local_files_only=True, allow_patterns=patterns)
        except Exception as exc:
            from huggingface_hub.errors import LocalEntryNotFoundError
            if not isinstance(exc, LocalEntryNotFoundError):
                raise
            emit({"status": "downloading_model", "progress": progress, "eta": f"首次下载 {repo}"})
            path = snapshot_download(repo, cache_dir=cache, allow_patterns=patterns)
        emit({"status": "loading_model", "progress": progress, "eta": "加载字幕对齐器" if aligner else "加载中文精确模型"})
        processor = AutoProcessor.from_pretrained(path, local_files_only=True)
        cls = AutoModelForTokenClassification if aligner else AutoModelForMultimodalLM
        model = cls.from_pretrained(path, dtype=torch.float32 if device == "cpu" else torch.bfloat16,
                                   local_files_only=True).to(device).eval()
        self.models[key] = (processor, model)
        return processor, model

    def transcribe(self, request):
        import numpy as np
        import torch
        device = request["device"]
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
            emit({"status": "loading_model", "progress": 3, "eta": "使用 CPU", "force_cpu": True,
                  "notice": "中文精确环境未检测到可用 CUDA，使用 CPU 转写（速度较慢）。"})
        processor, model = self.load(request["model"], device, request["cache"])
        language = {"中文": "Chinese", "英文": "English", "日语": "Japanese", "韩语": "Korean", "自动识别": None}.get(request["language"])
        result = []
        # Bounded reads avoid materializing long videos into RAM; offsets stay on the source timeline.
        with wave.open(request["audio"], "rb") as audio:
            rate = audio.getframerate()
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise ValueError("中文精确需要单声道 PCM16 音频。")
            total = audio.getnframes()
            while audio.tell() < total:
                start_frame = audio.tell()
                pcm = audio.readframes(rate * 30)
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
                if len(samples) > rate * 20 and audio.tell() < total:
                    # Prefer a low-energy boundary in the final 10 seconds.
                    energies = [(float(np.mean(samples[i:i + rate // 5] ** 2)), i)
                                for i in range(rate * 20, len(samples) - rate // 5, rate // 5)]
                    if energies:
                        _, boundary = min(energies)
                        boundary += rate // 10
                        samples = samples[:boundary]
                        audio.setpos(start_frame + boundary)
                offset = start_frame / rate
                end = (start_frame + len(samples)) / rate
                if np.max(np.abs(samples), initial=0) < 0.0001:
                    continue
                emit({"status": "transcribing", "progress": max(3, min(94, int(start_frame / max(total, 1) * 94))), "eta": "中文精确识别中"})
                inputs = processor.apply_transcription_request(audio=[samples], sampling_rate=rate, language=language).to(model.device, model.dtype)
                with torch.inference_mode():
                    output = model.generate(**inputs, max_new_tokens=1024, do_sample=False)
                generated = output[:, inputs["input_ids"].shape[1]:]
                if generated.shape[1] >= 1024:
                    raise RuntimeError("识别文字达到上限，为避免漏字已停止；请将该片段拆短后重试。")
                parsed = processor.decode(generated, return_format="parsed")[0]
                text = parsed["transcription"].strip()
                if not text:
                    continue
                entry = {"start": offset, "end": end, "text": text}
                if request["align"]:
                    detected = language or parsed["language"]
                    allowed = {"Chinese", "English", "Cantonese", "French", "German", "Italian", "Japanese", "Korean", "Portuguese", "Russian", "Spanish"}
                    if detected not in allowed:
                        raise RuntimeError(f"对齐器不支持识别语言 {detected}，请改用通用快速，或关闭 SRT 导出。")
                    emit({"status": "aligning", "progress": min(95, int(audio.tell() / max(total, 1) * 94)), "eta": "字幕时间对齐中"})
                    align_processor, align_model = self.load(request["aligner"], device, request["cache"], True,
                                                            min(94, int(audio.tell() / max(total, 1) * 94)))
                    aligned, word_lists = align_processor.prepare_forced_aligner_inputs(audio=[samples], transcript=text, language=detected, sampling_rate=rate)
                    aligned = aligned.to(align_model.device, align_model.dtype)
                    with torch.inference_mode():
                        predictions = align_model(**aligned)
                    words = align_processor.decode_forced_alignment(logits=predictions.logits, input_ids=aligned["input_ids"], word_lists=word_lists, timestamp_token_id=align_model.config.timestamp_token_id)[0]
                    if not words:
                        raise RuntimeError("字幕时间对齐失败；请改用通用快速，或关闭 SRT 导出。")
                    entry["words"] = aligned_words(text, words, offset, end)
                result.append(entry)
        return result

    def align_segments(self, request):
        import numpy as np
        import torch
        device = request["device"]
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
        processor, model = self.load(request["aligner"], device, request["cache"], True, 95)
        language_map = {"中文": "Chinese", "zh": "Chinese", "英文": "English", "en": "English",
                        "日语": "Japanese", "ja": "Japanese", "韩语": "Korean", "ko": "Korean",
                        "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
                        "ru": "Russian", "es": "Spanish", "yue": "Cantonese"}
        result = []
        with wave.open(request["audio"], "rb") as audio:
            rate = audio.getframerate()
            for index, segment in enumerate(request["segments"]):
                language = language_map.get(segment.get("language")) or language_map.get(request["language"])
                if not language:
                    raise RuntimeError("精确字幕对齐不支持该语言，请关闭精确字幕后使用快速模式的原生时间戳。")
                start = max(0, float(segment["start"]))
                end = min(audio.getnframes() / rate, float(segment["end"]))
                if end <= start or end - start > 300:
                    raise RuntimeError("字幕片段时间无效或超过对齐器的五分钟上限。")
                audio.setpos(round(start * rate))
                samples = np.frombuffer(audio.readframes(round((end - start) * rate)), dtype=np.int16).astype(np.float32) / 32768
                emit({"status": "aligning", "progress": 95, "eta": f"字幕对齐 {index + 1}/{len(request['segments'])}"})
                inputs, word_lists = processor.prepare_forced_aligner_inputs(audio=[samples], transcript=segment["text"], language=language, sampling_rate=rate)
                inputs = inputs.to(model.device, model.dtype)
                with torch.inference_mode():
                    predictions = model(**inputs)
                words = processor.decode_forced_alignment(logits=predictions.logits, input_ids=inputs["input_ids"], word_lists=word_lists, timestamp_token_id=model.config.timestamp_token_id)[0]
                if not words:
                    raise RuntimeError("精确字幕时间对齐失败，请关闭精确字幕后重试。")
                result.append({**segment, "words": aligned_words(segment["text"], words, start, end)})
        return result


def main():
    engine = LocalEngine()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            emit({"result": engine.align_segments(request) if "segments" in request else engine.transcribe(request)})
        except Exception as exc:
            emit({"error": f"中文精确失败：{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
