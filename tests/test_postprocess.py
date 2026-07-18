from __future__ import annotations

import io
import json
import os
import socket
import unittest
import urllib.error
from unittest.mock import patch

from app import postprocess


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class TextPostprocessRequestTests(unittest.TestCase):
    def test_missing_api_key_is_rejected_before_network_request(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(postprocess.TextPostprocessError, "未配置翻译润色 API"):
                postprocess._request_chat_completion("提示", "正文")
        urlopen.assert_not_called()

    def test_request_uses_configured_auth_base_url_and_model(self) -> None:
        env = {
            "NANZHU_TEXT_API_KEY": "secret-test-key",
            "NANZHU_TEXT_BASE_URL": "https://example.test/v1/",
            "NANZHU_TEXT_MODEL": "test-model",
        }
        response = FakeResponse({"choices": [{"message": {"content": "  已润色  "}}]})
        with patch.dict(os.environ, env, clear=True), patch(
            "urllib.request.urlopen", return_value=response
        ) as urlopen:
            result = postprocess._request_chat_completion("提示", "正文")

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, "已润色")
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-test-key")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], postprocess.API_TIMEOUT_SECONDS)

    def test_authentication_error_is_actionable_and_does_not_leak_key(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"invalid secret-test-key"}'),
        )
        with patch.dict(os.environ, {"NANZHU_TEXT_API_KEY": "secret-test-key"}, clear=True), patch(
            "urllib.request.urlopen", side_effect=error
        ):
            with self.assertRaises(postprocess.TextPostprocessError) as caught:
                postprocess._request_chat_completion("提示", "正文")

        message = str(caught.exception)
        self.assertIn("鉴权失败", message)
        self.assertIn("HTTP 401", message)
        self.assertNotIn("secret-test-key", message)

    def test_socket_timeout_has_dedicated_message(self) -> None:
        with patch.dict(os.environ, {"NANZHU_TEXT_API_KEY": "test-key"}, clear=True), patch(
            "urllib.request.urlopen", side_effect=socket.timeout("timed out")
        ):
            with self.assertRaisesRegex(postprocess.TextPostprocessError, "请求超时"):
                postprocess._request_chat_completion("提示", "正文")

    def test_url_error_wrapping_timeout_has_dedicated_message(self) -> None:
        error = urllib.error.URLError(socket.timeout("timed out"))
        with patch.dict(os.environ, {"NANZHU_TEXT_API_KEY": "test-key"}, clear=True), patch(
            "urllib.request.urlopen", side_effect=error
        ):
            with self.assertRaisesRegex(postprocess.TextPostprocessError, "请求超时"):
                postprocess._request_chat_completion("提示", "正文")

    def test_empty_content_is_rejected(self) -> None:
        response = FakeResponse({"choices": [{"message": {"content": "   "}}]})
        with patch.dict(os.environ, {"NANZHU_TEXT_API_KEY": "test-key"}, clear=True), patch(
            "urllib.request.urlopen", return_value=response
        ):
            with self.assertRaisesRegex(postprocess.TextPostprocessError, "返回空内容"):
                postprocess._request_chat_completion("提示", "正文")

    def test_missing_choices_is_reported_without_echoing_response(self) -> None:
        response = FakeResponse({"unexpected": "private response content"})
        with patch.dict(os.environ, {"NANZHU_TEXT_API_KEY": "test-key"}, clear=True), patch(
            "urllib.request.urlopen", return_value=response
        ):
            with self.assertRaises(postprocess.TextPostprocessError) as caught:
                postprocess._request_chat_completion("提示", "正文")

        self.assertIn("返回格式异常", str(caught.exception))
        self.assertNotIn("private response content", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
