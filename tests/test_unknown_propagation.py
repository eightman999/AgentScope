from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.application import audit_local_directory
from agentscope.model.mock import MockModelProvider

from tests.helpers import action, fixture


class UnknownPropagationTests(unittest.TestCase):
    def _audit(self, script):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_local_directory(
                fixture("dynamic_agent"),
                artifacts=ArtifactStore.create(Path(directory), "run"),
                provider=MockModelProvider(script),
            )
            # ArtifactStoreは呼び出し元が保持するため、検査用に内容を複製する。
            report = result.report
            trace = result.artifacts.path("audit_trace.jsonl").read_text(encoding="utf-8")
            integrity = result.artifacts.path(
                "provenance/model-output-integrity.txt"
            ).read_text(encoding="utf-8")
            return report, trace, integrity

    def _assert_evaluation_is_unknown(self, report: dict[str, object]) -> None:
        self.assertEqual(report["runtime"]["termination"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["runtime"]["status"], "completed")
        for item in report["scores"]:
            self.assertIsNone(item["score"])
            self.assertEqual(item["state"], "unknown")
            self.assertEqual(item["confidence"], "unknown")
        for item in report["classifications"].values():
            self.assertEqual(item["value"], "unknown")
            self.assertEqual(item["confidence"], "unknown")

    def test_nonexistent_model_selected_path_propagates_unknown(self) -> None:
        report, trace, integrity = self._audit(
            [action("read_file", {"path": "does-not-exist.py"})]
        )
        self._assert_evaluation_is_unknown(report)
        self.assertIn("model_output_integrity_rejected", trace)
        self.assertIn("does-not-exist.py", integrity)

    def test_invalid_model_selected_range_propagates_unknown(self) -> None:
        report, trace, integrity = self._audit(
            [action("read_file", {"path": "README.md", "start_line": 0})]
        )
        self._assert_evaluation_is_unknown(report)
        self.assertIn("model_output_integrity_rejected", trace)
        self.assertIn("start_line", integrity)

    def test_forged_evidence_id_stops_without_a_retry_and_propagates_unknown(self) -> None:
        forged = action("read_file", {"path": "README.md"})
        forged["evidence_ids"] = ["e999"]
        report, trace, integrity = self._audit([forged])
        self._assert_evaluation_is_unknown(report)
        self.assertIn("model_output_integrity_rejected", trace)
        self.assertIn("evidence", integrity)


if __name__ == "__main__":
    unittest.main()
