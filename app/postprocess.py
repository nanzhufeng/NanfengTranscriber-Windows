from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Callable


CancelCallback = Callable[[], bool]
ProgressCallback = Callable[[dict[str, object]], None]


class TextPostprocessError(RuntimeError):
    """Raised when AI translation/polishing cannot run."""


API_TIMEOUT_SECONDS = 120


def _split_text(text: str, max_chars: int = 6000) -> list[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if current and current_len + len(paragraph) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [text.strip()]


def _request_chat_completion(prompt: str, text: str) -> str:
    api_key = os.environ.get("NANZHU_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TextPostprocessError(
            "未配置翻译润色 API。请设置 NANZHU_TEXT_API_KEY 或 OPENAI_API_KEY 后再开启翻译润色。"
        )

    base_url = os.environ.get("NANZHU_TEXT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("NANZHU_TEXT_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": text,
            },
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise TextPostprocessError(
                f"翻译润色 API 鉴权失败（HTTP {exc.code}）。请检查 API Key、服务地址和账号权限。"
            ) from exc
        raise TextPostprocessError(f"翻译润色 API 返回错误（HTTP {exc.code}）。请稍后重试。") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise TextPostprocessError(
            f"翻译润色 API 请求超时（{API_TIMEOUT_SECONDS} 秒）。请检查网络或稍后重试。"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise TextPostprocessError(
                f"翻译润色 API 请求超时（{API_TIMEOUT_SECONDS} 秒）。请检查网络或稍后重试。"
            ) from exc
        raise TextPostprocessError("翻译润色 API 连接失败。请检查网络和服务地址。") from exc
    except Exception as exc:
        raise TextPostprocessError(f"翻译润色 API 调用失败：{exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TextPostprocessError("翻译润色 API 返回格式异常，未找到正文内容。") from exc
    if not isinstance(content, str) or not content.strip():
        raise TextPostprocessError("翻译润色 API 返回空内容，请重试或更换模型。")
    return content.strip()


def polish_to_simplified_chinese(
    text: str,
    title: str,
    progress_callback: ProgressCallback,
    cancel_callback: CancelCallback | None = None,
) -> str:
    source_text = text.strip()
    if not source_text:
        return text

    prompt = (
        "你是专业的中文转写稿整理助手。"
        "任务：把音视频转写稿整理为现代简体中文。"
        "要求：1. 英文、繁体中文、文言表达要翻译或改写成自然简体中文；"
        "2. 修正常见同音错字、断句和标点；"
        "3. 不添加原文没有的新观点；"
        "4. 保留人名、地名、专有名词和数字；"
        "5. 只输出整理后的正文，不要解释。"
    )
    chunks = _split_text(source_text)
    polished: list[str] = []
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        if cancel_callback and cancel_callback():
            raise RuntimeError("用户已停止翻译润色。")
        progress_callback(
            {
                "status": "polishing",
                "progress": 98,
                "eta": f"正在翻译润色 {index}/{total}",
                "notice": f"正在翻译润色《{title}》：{index}/{total}",
            }
        )
        polished.append(_request_chat_completion(prompt, chunk))
    return "\n\n".join(part for part in polished if part.strip())
