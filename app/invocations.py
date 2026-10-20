"""Local, metadata-only cloud attempt ledger, matching Android's file grouping."""
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sqlite3
import re


@dataclass(frozen=True)
class InvocationRecord:
    id: str
    task_id: str
    source_display_name: str
    provider_id: str
    model_id: str
    completed_at_millis: int
    duration_millis: int
    request_count: int
    billable_audio_millis: int
    status: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_price_version: str | None = None
    cost_currency_code: str | None = None
    estimated_cost_micros: int | None = None
    error_code: str | None = None


def estimate_cost(model, input_tokens, output_tokens, audio_millis):
    if model == "qwen-audio-3.1-asr-flash-filetrans" and all(v is not None and v >= 0 for v in (input_tokens, output_tokens)):
        amount = Decimal(input_tokens) * Decimal("0.8") + Decimal(output_tokens) * Decimal("2.7")
        version = "qwen-audio-3.1-filetrans-cn-token-2026-10-09-v1"
    elif model == "paraformer-v2" and audio_millis > 0:
        amount = Decimal(audio_millis) * Decimal("0.08")
        version = "paraformer-v2-cn-duration-2026-10-09-v1"
    else:
        return None, None, None
    return version, "CNY", int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def safe_error(code):
    return code if code and re.fullmatch(r"(?:QWEN|FILETRANS)_(?:HTTP_[1-5][0-9]{2}|NETWORK_ERROR|RESPONSE_INVALID|EMPTY_TRANSCRIPT|POLL_TIMEOUT|SUBMISSION_UNCERTAIN|TASK_EXPIRED)", code) else "FILETRANS_FAILED"


class InvocationStore:
    def __init__(self, root):
        self.path = Path(root) / "asr_invocations.sqlite3"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=.2)
        connection.row_factory = sqlite3.Row
        try:
            self._initialize(connection)
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def _initialize(connection):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("调用记录数据库版本不兼容")
        if version == 0:
            numeric = {"completed_at_millis", "duration_millis", "request_count", "billable_audio_millis", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_micros"}
            fields = [f'{name} {"INTEGER" if name in numeric else "TEXT"}{" PRIMARY KEY" if name == "id" else ""}' for name in InvocationRecord.__dataclass_fields__]
            connection.execute("CREATE TABLE IF NOT EXISTS invocations (" + ",".join(fields) + ")")
            connection.execute("CREATE INDEX IF NOT EXISTS invocation_time ON invocations(completed_at_millis DESC,id DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS invocation_task ON invocations(task_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS invocation_model ON invocations(provider_id,model_id)")
            connection.execute("PRAGMA user_version=1")
            connection.commit()

    def record(self, record):
        data = asdict(record)
        data["error_code"] = safe_error(record.error_code) if record.error_code else None
        connection = self._connect()
        try:
            with connection:
                connection.execute("INSERT INTO invocations (" + ",".join(data) + ") VALUES (" + ",".join("?" for _ in data) + ")", list(data.values()))
        finally:
            connection.close()

    def count_files(self):
        connection = self._connect()
        try:
            return connection.execute("SELECT COUNT(DISTINCT CASE WHEN trim(task_id)='' THEN id ELSE task_id END) FROM invocations").fetchone()[0]
        finally:
            connection.close()

    def groups(self):
        connection = self._connect()
        try:
            # Aggregate in SQLite: GUI never loads every raw retry fact.
            complete = lambda key: f'CASE WHEN COUNT({key})=COUNT(*) THEN SUM({key}) END AS {key}'
            sums = [f'SUM({key}) AS {key}' for key in ("request_count", "duration_millis")]
            sums += [complete(key) for key in ("input_tokens", "output_tokens", "total_tokens", "estimated_cost_micros")]
            sql = """WITH facts AS (
                SELECT *, CASE WHEN trim(task_id)='' THEN id ELSE task_id END AS group_key FROM invocations
            ), latest AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY group_key ORDER BY completed_at_millis DESC,id DESC) AS rn FROM facts
            ), totals AS (SELECT group_key,""" + ",".join(sums) + """,
                CASE WHEN COUNT(DISTINCT cost_currency_code)=1 THEN MAX(cost_currency_code) END AS cost_currency_code
                FROM facts GROUP BY group_key)
                SELECT l.group_key,l.source_display_name,l.provider_id,l.model_id,l.completed_at_millis,l.status,l.error_code,
                t.request_count,t.duration_millis,t.input_tokens,t.output_tokens,t.total_tokens,t.estimated_cost_micros,t.cost_currency_code
                FROM latest l JOIN totals t ON l.group_key=t.group_key WHERE l.rn=1 ORDER BY l.completed_at_millis DESC,l.id DESC"""
            return [dict(row) for row in connection.execute(sql)]
        finally:
            connection.close()


def usage_label(record):
    if record.get("total_tokens") is not None:
        return f'Token：{record["total_tokens"]}'
    if any(record.get(key) is not None for key in ("input_tokens", "output_tokens")):
        return f'输入 Token：{record.get("input_tokens") if record.get("input_tokens") is not None else "未提供"} · 输出 Token：{record.get("output_tokens") if record.get("output_tokens") is not None else "未提供"}'
    return "Token：服务未提供"


def cost_label(record):
    if record.get("estimated_cost_micros") is None or record.get("cost_currency_code") != "CNY":
        return "费用估算：暂无费用数据"
    amount = format(Decimal(record["estimated_cost_micros"]) / 1_000_000, ".6f").rstrip("0").rstrip(".")
    return f"费用估算：≈ ¥{amount}（估算）"


def error_label(code):
    if code.endswith(("HTTP_401", "HTTP_403")):
        return "鉴权、权限或地域不匹配"
    if code.endswith("HTTP_429"):
        return "服务限流或额度不足"
    if "HTTP_5" in code:
        return "服务暂不可用"
    return {"QWEN_NETWORK_ERROR": "网络不可用", "QWEN_RESPONSE_INVALID": "响应格式异常", "QWEN_EMPTY_TRANSCRIPT": "未返回转写文字", "FILETRANS_POLL_TIMEOUT": "云端仍在处理，可继续读取", "FILETRANS_SUBMISSION_UNCERTAIN": "提交状态待核对，已阻止重复提交", "FILETRANS_TASK_EXPIRED": "结果已过期，需重新转写"}.get(code, "云端转写请求失败")
