import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace

from app.invocations import InvocationRecord, InvocationStore, estimate_cost, cost_label, usage_label


class InvocationTests(unittest.TestCase):
    def test_mobile_price_examples_and_missing_usage(self):
        self.assertEqual(estimate_cost("qwen-audio-3.1-asr-flash-filetrans", 1_000_000, 1_000_000, 0),
                         ("qwen-audio-3.1-filetrans-cn-token-2026-10-09-v1", "CNY", 3_500_000))
        self.assertEqual(estimate_cost("paraformer-v2", None, None, 60_000),
                         ("paraformer-v2-cn-duration-2026-10-09-v1", "CNY", 4800))
        self.assertEqual(estimate_cost("paraformer-v2", None, None, 0), (None, None, None))
        self.assertEqual(estimate_cost("qwen-audio-3.1-asr-flash-filetrans", None, 100, 60_000), (None, None, None))

    def test_file_group_uses_latest_status_and_complete_sums_after_restart(self):
        with TemporaryDirectory() as directory:
            store = InvocationStore(Path(directory))
            record = InvocationRecord(id="1", task_id="file-a", source_display_name="demo.wav", provider_id="QWEN",
                model_id="qwen-audio-3.1-asr-flash-filetrans", completed_at_millis=1000, duration_millis=30,
                request_count=1, billable_audio_millis=0, status="SUCCEEDED", input_tokens=5, output_tokens=6,
                total_tokens=11, cost_price_version="version", cost_currency_code="CNY", estimated_cost_micros=20)
            store.record(record)
            store.record(replace(record, id="2", completed_at_millis=2000, duration_millis=70,
                                 status="FAILED", input_tokens=None, total_tokens=None, estimated_cost_micros=None,
                                 error_code="Bearer private-key and private transcript"))
            store.record(replace(record, id="3", task_id="", completed_at_millis=1500))
            groups = InvocationStore(Path(directory)).groups()
            self.assertEqual(store.count_files(), 2)
            self.assertEqual(groups[0]["status"], "FAILED")
            self.assertEqual(groups[0]["request_count"], 2)
            self.assertEqual(groups[0]["duration_millis"], 100)
            self.assertIsNone(groups[0]["input_tokens"])
            self.assertEqual(groups[0]["output_tokens"], 12)
            self.assertEqual(cost_label(groups[0]), "费用估算：暂无费用数据")
            self.assertNotIn("private-key", json.dumps(groups))
            self.assertIn("未提供", usage_label(groups[0]))
            self.assertEqual(groups[1]["group_key"], "3")
            with self.assertRaises(Exception):
                store.record(record)  # Same immutable fact cannot be overwritten.

    def test_money_format_matches_mobile_without_claiming_settlement(self):
        self.assertEqual(cost_label({"estimated_cost_micros": 4800, "cost_currency_code": "CNY"}), "费用估算：≈ ¥0.0048（估算）")
        self.assertEqual(cost_label({"estimated_cost_micros": 1, "cost_currency_code": "USD"}), "费用估算：暂无费用数据")
        self.assertEqual(cost_label({"estimated_cost_micros": 1_000_000, "cost_currency_code": "CNY"}), "费用估算：≈ ¥1（估算）")


if __name__ == "__main__":
    unittest.main()
