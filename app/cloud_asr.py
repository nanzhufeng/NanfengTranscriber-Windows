"""DashScope file transcription, matching the Android task/resume protocol."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib import request, error, parse
from uuid import uuid4

BASE = "https://dashscope.aliyuncs.com/api/v1/"
from .model_modes import CLOUD_MODELS as MODELS


class CloudAsrError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def trusted_resource(url):
    try:
        p = parse.urlsplit(url)
        return (p.scheme == "https" and not p.username and not p.password
                and p.port in (None, 443) and (p.hostname or "").endswith(".aliyuncs.com")
                and ".oss-" in (p.hostname or ""))
    except ValueError:
        return False


class DashScopeClient:
    def __init__(self, key, cancel=lambda: False):
        self.key, self.cancel = key, cancel
        self.opener = request.build_opener(NoRedirect())

    def check_cancel(self):
        if self.cancel():
            from .transcriber import TranscribeStopped
            raise TranscribeStopped("已停止；已提交的云端任务可能继续计费，重试将优先恢复该任务。")

    def exchange(self, path, payload=None, headers=None):
        self.check_cancel()
        h = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        h.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(BASE + path, data=body, headers=h)
        try:
            with self.opener.open(req, timeout=20) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError()
            return json.loads(raw)
        except error.HTTPError as exc:
            message = {401: "API Key 无效，请在设置中重新填写百炼 API Key。", 403: "无调用权限或余额不足，请检查百炼账户。",
                       404: "云端任务或模型不存在，请检查百炼模型权限后重试。", 429: "百炼请求过于频繁，请稍后重试。"}.get(exc.code, "百炼服务暂时不可用，请稍后重试。")
            raise CloudAsrError(message, exc.code) from None
        except (error.URLError, OSError):
            raise CloudAsrError("连接百炼失败或超时，请检查网络后重试。") from None
        except (ValueError, KeyError, TypeError):
            raise CloudAsrError("百炼返回格式异常，请稍后重试。") from None

    def upload(self, audio, model):
        policy = self.exchange("uploads?action=getPolicy&model=" + model).get("data", {})
        host, directory = policy.get("upload_host", ""), policy.get("upload_dir", "").strip("/")
        if not trusted_resource(host) or not re.fullmatch(r"[A-Za-z0-9_./-]+", directory) or ".." in directory.split("/"):
            raise CloudAsrError("百炼临时上传地址无效，请重试。")
        name = uuid4().hex + ".wav"
        key = directory + "/" + name
        boundary = "nf-" + uuid4().hex
        fields = {"OSSAccessKeyId": policy.get("oss_access_key_id"), "Signature": policy.get("signature"),
                  "policy": policy.get("policy"), "x-oss-object-acl": policy.get("x_oss_object_acl"),
                  "x-oss-forbid-overwrite": policy.get("x_oss_forbid_overwrite"), "key": key, "success_action_status": "200"}
        if any(not isinstance(v, str) or not v for v in fields.values()):
            raise CloudAsrError("百炼上传授权返回格式异常。")
        prefix = b"".join((f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode() for k, v in fields.items())
        prefix += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()
        def chunks():
            yield prefix
            with audio.open("rb") as stream:
                while data := stream.read(128 * 1024):
                    self.check_cancel()
                    yield data
            yield suffix
        req = request.Request(host, data=chunks(), method="POST", headers={
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Content-Length": str(len(prefix) + audio.stat().st_size + len(suffix))})
        try:
            with self.opener.open(req, timeout=30) as response:
                response.read(1024)
        except (error.URLError, OSError):
            raise CloudAsrError("音频上传失败，请检查网络后重试。") from None
        return "oss://" + key

    def submit(self, model, url, language):
        from .transcriber import _resolve_language
        language = _resolve_language(language) if language else None
        parameters = {"channel_id": [0]}
        if language and language != "auto":
            parameters["language_hints"] = [language]
        data = self.exchange("services/audio/asr/transcription", {
            "model": model, "input": {"file_urls": [url]}, "parameters": parameters},
            {"X-DashScope-Async": "enable", "X-DashScope-OssResourceResolve": "enable"})
        output = data.get("output", {})
        task_id = output.get("task_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id) or output.get("task_status") not in {"PENDING", "RUNNING", "SUCCEEDED"}:
            raise CloudAsrError("云端提交结果未确认，请核对百炼任务记录，避免重复计费。")
        return task_id

    def result(self, url):
        if not trusted_resource(url):
            raise CloudAsrError("百炼结果地址无效，已停止读取。")
        self.check_cancel()
        try:
            with self.opener.open(request.Request(url), timeout=20) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError()
            return parse_transcript(json.loads(raw))
        except (error.URLError, OSError):
            raise CloudAsrError("读取云端结果失败，请检查网络后重试；已提交任务不会重复创建。") from None
        except (ValueError, KeyError, TypeError):
            raise CloudAsrError("云端字幕格式异常，请稍后重试。") from None


def parse_transcript(data):
    transcripts = data["transcripts"]
    if len(transcripts) != 1 or transcripts[0]["channel_id"] != 0:
        raise ValueError("Unexpected channels")
    result = []
    for sentence in transcripts[0]["sentences"]:
        start, end = float(sentence["begin_time"]), float(sentence["end_time"])
        if not (0 <= start <= end < float("inf")) or not isinstance(sentence["text"], str):
            raise ValueError("Invalid sentence")
        if sentence["text"].strip():
            result.append({"start": start / 1000, "end": end / 1000, "text": sentence["text"].strip()})
    if not result:
        raise CloudAsrError("没有识别到可导出的文字。")
    return result


def transcribe_cloud(audio, options, progress, cancelled, client=None, poll_interval=2):
    model = MODELS[options.model_size]
    if not options.cloud_api_key.strip():
        raise CloudAsrError("未配置百炼 API Key，请在设置中填写后重试。")
    client = client or DashScopeClient(options.cloud_api_key, cancelled or (lambda: False))
    digest = hashlib.sha256()
    with Path(audio).open("rb") as stream:
        while data := stream.read(256 * 1024):
            client.check_cancel()
            digest.update(data)
    digest.update((model + "|" + options.language + "|" + hashlib.sha256(options.cloud_api_key.encode()).hexdigest()).encode())
    root = Path(options.cloud_state_dir)
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / (digest.hexdigest() + ".json")
    try:
        if state_path.exists() and state_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError()
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except (ValueError, OSError):
        raise CloudAsrError("云端任务恢复记录损坏，请先核对百炼任务记录。") from None
    def save():
        pending = state_path.with_suffix(".part")
        pending.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(pending, state_path)
    if not isinstance(state, dict) or (state.get("task_id") and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(state["task_id"]))):
        raise CloudAsrError("云端任务恢复记录无效，请先核对百炼任务记录。")
    if "segments" in state:
        return state["segments"]
    if not state.get("task_id"):
        if state.get("submission_pending"):
            raise CloudAsrError("上次云端提交结果未确认，请先核对百炼任务记录，避免重复计费。")
        progress({"status": "transcribing", "notice": "正在上传音频到阿里云百炼…", "progress": 5})
        url = client.upload(Path(audio), model)
        client.check_cancel()
        state = {"submission_pending": True, "model": model}
        save()
        try:
            task_id = client.submit(model, url, options.language)
        except CloudAsrError as exc:
            if exc.status and 400 <= exc.status < 500:
                state = {}
                save()
            raise
        state = {"task_id": task_id, "model": model}
        save()
    for _ in range(900):
        client.check_cancel()
        try:
            response = client.exchange("tasks/" + state["task_id"])
        except CloudAsrError as exc:
            if exc.status == 404:
                state = {}
                save()
                raise CloudAsrError("云端任务已过期；再次重试将重新提交，可能再次计费。") from None
            raise
        output = response.get("output", {})
        if output.get("task_id") != state["task_id"]:
            raise CloudAsrError("云端任务返回编号异常，请稍后重试。")
        status = output.get("task_status")
        if status in {"FAILED", "CANCELED"}:
            state = {}
            save()
            raise CloudAsrError("云端文件转写失败或已取消，请检查音频后重试。")
        if status == "SUCCEEDED":
            results = output.get("results", [])
            if len(results) != 1 or results[0].get("subtask_status") != "SUCCEEDED":
                state = {}
                save()
                raise CloudAsrError("云端无法完成此音频，请检查格式及权限。")
            segments = client.result(results[0].get("transcription_url", ""))
            usage = response.get("usage", {})
            usage = {k: usage[k] for k in ("duration", "input_tokens", "output_tokens", "total_tokens")
                     if isinstance(usage.get(k), (int, float)) and 0 <= usage[k] < float("inf")}
            state.update(segments=segments, usage=usage)
            save()
            return segments
        if status not in {"PENDING", "RUNNING"}:
            raise CloudAsrError("云端任务状态异常，请稍后重试。")
        progress({"status": "transcribing", "notice": "云端正在转写，可停止后稍后重试以恢复任务。", "progress": 20, "eta": "-"})
        until = time.monotonic() + poll_interval
        while time.monotonic() < until:
            client.check_cancel()
            time.sleep(min(.1, max(0, until - time.monotonic())))
    raise CloudAsrError("云端转写等待超时，请稍后重试以恢复已有任务。")
