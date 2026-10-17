"""User-bound Windows DPAPI storage; credentials never enter history or logs."""
import base64
import ctypes
import os
from ctypes import wintypes

KEY = "credentials/dashscope_key_dpapi"


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(raw, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("当前系统不支持 Windows 密钥保护，请使用 DASHSCOPE_API_KEY 环境变量。")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("无法使用当前 Windows 用户保护或读取 API Key，请重新保存。")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


def is_configured(settings):
    return bool(os.environ.get("DASHSCOPE_API_KEY", "").strip() or settings.value(KEY, ""))


def read_api_key(settings):
    override = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if override:
        return override
    value = settings.value(KEY, "")
    if not value:
        return ""
    try:
        return _crypt(base64.b64decode(value), decrypt=True).decode("utf-8")
    except Exception:
        raise RuntimeError("已保存的百炼 API Key 无法读取，请在设置中重新填写。") from None


def save_api_key(settings, value):
    value = value.strip()
    if value:
        settings.setValue(KEY, base64.b64encode(_crypt(value.encode())).decode("ascii"))
    else:
        settings.remove(KEY)
    settings.sync()
