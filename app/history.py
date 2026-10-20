"""Local history ownership. Never deletes source media or exported documents."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import sqlite3


class HistoryStore:
    PAGE_SIZE = 100

    def __init__(self, root: Path):
        self.root = Path(root)
        self.database = self.root / "history.sqlite3"

    @contextmanager
    def connection(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=0.2)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise sqlite3.DatabaseError("历史数据库来自较新版本，请使用新版软件打开")
            if version == 0:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT NOT NULL,
                completed TEXT NOT NULL, mode TEXT NOT NULL, model TEXT NOT NULL,
                language TEXT NOT NULL, duration REAL NOT NULL,
                original TEXT NOT NULL, final TEXT NOT NULL, edited TEXT,
                segments TEXT NOT NULL, outputs TEXT NOT NULL, search_text TEXT NOT NULL)""")
                connection.execute("CREATE INDEX IF NOT EXISTS history_completed ON records(completed DESC)")
                connection.execute("PRAGMA user_version=1")
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, result):
        if not result.text.strip() or not result.source_path:
            raise ValueError("历史记录缺少文稿或源文件位置")
        original = result.original_text or result.text
        with self.connection() as connection:
            # Re-delivering a completion event must not duplicate or overwrite an edited record.
            connection.execute("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                result.history_id, str(result.source_path), Path(result.source_path).name,
                datetime.now().astimezone().isoformat(), result.mode, result.model,
                result.language, result.duration, original, result.text, None,
                json.dumps(result.segments, ensure_ascii=False),
                json.dumps([str(path) for path in result.files], ensure_ascii=False),
                "\n".join((Path(result.source_path).name, original, result.text)),
            ))

    @staticmethod
    def _record(row):
        record = dict(row)
        record["warnings"] = []
        record["invalid"] = not any(isinstance(record[key], str) and record[key].strip() for key in ("original", "final"))
        try:
            record["segments"] = json.loads(record["segments"])
            if not isinstance(record["segments"], list):
                raise ValueError("文稿结构无效")
            for segment in record["segments"]:
                start, end = float(segment["start"]), float(segment["end"])
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start or not isinstance(segment["text"], str):
                    raise ValueError("时间片段无效")
        except (ValueError, TypeError, KeyError):
            record["segments"] = []
            record["warnings"].append("时间片段损坏，文字仍可查看和导出；无法导出 SRT。")
        try:
            record["outputs"] = json.loads(record["outputs"])
            if not isinstance(record["outputs"], list) or not all(isinstance(path, str) for path in record["outputs"]):
                raise ValueError("路径信息无效")
        except (ValueError, TypeError):
            record["outputs"] = []
            record["warnings"].append("原导出路径信息损坏，可重新导出。")
        return record

    def get(self, record_id):
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ValueError("这条历史记录已被删除")
        return self._record(row)

    @staticmethod
    def _filter(keyword, period):
        conditions, args = [], []
        if keyword.strip():
            conditions.append("instr(lower(search_text), lower(?)) > 0")
            args.append(keyword.strip())
        now = datetime.now().astimezone()
        if period != "全部时间":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) if period == "今天" else now - timedelta(days=7 if period == "近 7 天" else 30)
            conditions.append("completed >= ?")
            args.append(start.isoformat())
        clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        return clause, args

    def query(self, keyword="", period="全部时间", limit=PAGE_SIZE):
        clause, args = self._filter(keyword, period)
        with self.connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM records" + clause, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM records" + clause + " ORDER BY completed DESC, id DESC LIMIT ?", (*args, limit)).fetchall()
        return [self._record(row) for row in rows], total

    def query_cards(self, keyword="", period="全部时间", limit=PAGE_SIZE):
        """List navigation never materializes entire transcripts or subtitle JSON."""
        clause, args = self._filter(keyword, period)
        with self.connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM records" + clause, args).fetchone()[0]
            rows = connection.execute("""SELECT id, source, name, completed, mode, model,
                language, duration, substr(coalesce(edited, final), 1, 240) AS final,
                (trim(original)='' AND trim(final)='') AS invalid
                FROM records""" + clause + " ORDER BY completed DESC, id DESC LIMIT ?",
                (*args, limit)).fetchall()
        return [dict(row, edited=None, warnings=[], outputs=[], segments=[]) for row in rows], total

    def all_matching_ids(self, keyword="", period="全部时间"):
        clause, args = self._filter(keyword, period)
        with self.connection() as connection:
            return {row["id"] for row in connection.execute("SELECT id FROM records" + clause, args)}

    def edit(self, record_id, text):
        record = self.get(record_id)
        with self.connection() as connection:
            connection.execute("UPDATE records SET edited=?, search_text=? WHERE id=?", (
                text, "\n".join((record["name"], record["original"], record["final"], text)), record_id))

    def relink(self, record_id, source):
        source = Path(source)
        if not source.is_file():
            raise ValueError("所选原文件不存在")
        with self.connection() as connection:
            connection.execute("UPDATE records SET source=? WHERE id=?", (str(source.resolve()), record_id))

    def add_export(self, record_id, target):
        record = self.get(record_id)
        outputs = list(dict.fromkeys([*record["outputs"], str(Path(target).resolve())]))
        with self.connection() as connection:
            connection.execute("UPDATE records SET outputs=? WHERE id=?", (json.dumps(outputs, ensure_ascii=False), record_id))

    def invalid_ids(self):
        with self.connection() as connection:
            return {row["id"] for row in connection.execute("SELECT id FROM records WHERE trim(original)='' AND trim(final)=''")}

    def delete(self, record_ids):
        with self.connection() as connection:
            connection.executemany("DELETE FROM records WHERE id=?", ((value,) for value in record_ids))
        for record_id in record_ids:
            # Thumbnail names are derived, never supplied by the source filename.
            import hashlib
            thumbnail = self.root / "thumbnails" / (hashlib.sha256(record_id.encode()).hexdigest() + ".png")
            thumbnail.unlink(missing_ok=True)
