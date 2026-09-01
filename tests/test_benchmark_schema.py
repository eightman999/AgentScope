from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentscope.benchmark.schema import (
    BenchmarkSchemaError,
    category_counts,
    load_dataset,
)


SHA = "0123456789abcdef0123456789abcdef01234567"


def _evidence() -> dict[str, object]:
    return {
        "source_kind": "repository",
        "file": "README.md",
        "start_line": 1,
        "end_line": 1,
        "excerpt": "This repository is an agent.",
        "reason": "The README states the runtime scope.",
        "commit_sha": SHA,
    }


def _label(value: str = "yes") -> dict[str, object]:
    return {
        "value": value,
        "confidence": "high",
        "rationale": "固定commit上の明示的な根拠がある。",
        "evidence": [_evidence()],
    }


def _case(case_id: str = "fixture-agent") -> dict[str, object]:
    return {
        "id": case_id,
        "url": "https://github.com/fixture/repository.git",
        "commit_sha": SHA,
        "category": "clearly_agentic",
        "annotation_status": "adjudicated",
        "human_labels": {"agentic_runtime": _label()},
        "human_scores": {"agenticity": 9.0},
        "annotation": {
            "annotator": "test",
            "adjudicator": "test",
            "annotated_at": "2026-09-02T00:00:00Z",
            "protocol_version": "0.1",
            "score_evidence": {"agenticity": [_evidence()]},
        },
    }


class BenchmarkSchemaTests(unittest.TestCase):
    def _write(self, rows: list[dict[str, object]]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "dataset.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path

    def test_loads_canonical_url_labels_scores_and_category_counts(self) -> None:
        case = _case()
        second = _case("fixture-mcp")
        second["category"] = "mcp_tooling_only"
        second["human_labels"] = {"agentic_runtime": _label("no")}
        cases = load_dataset(self._write([case, second]))

        self.assertEqual(cases[0].url, "https://github.com/fixture/repository")
        self.assertEqual(cases[0].human_labels["agentic_runtime"].evidence[0].display_ref, "README.md:1")
        self.assertEqual(cases[0].human_scores["agenticity"], 9.0)
        self.assertEqual(category_counts(cases), {
            "clearly_agentic": 1,
            "llm_non_agent": 0,
            "mcp_tooling_only": 1,
            "ai_assisted_only": 0,
            "hard_case": 0,
        })

    def test_pending_case_must_not_have_human_labels(self) -> None:
        case = _case()
        case["annotation_status"] = "pending"
        with self.assertRaisesRegex(BenchmarkSchemaError, "pending case"):
            load_dataset(self._write([case]))

    def test_evidence_commit_and_unknown_axis_are_rejected(self) -> None:
        case = _case()
        evidence = _evidence()
        evidence["commit_sha"] = "f" * 40
        case["human_labels"] = {"agentic_runtime": _label() | {"evidence": [evidence]}}
        with self.assertRaisesRegex(BenchmarkSchemaError, "evidence commit"):
            load_dataset(self._write([case]))

        case = _case("fixture-unknown-axis")
        case["human_labels"] = {"not_an_axis": _label()}
        with self.assertRaisesRegex(BenchmarkSchemaError, "unknown axes"):
            load_dataset(self._write([case]))

    def test_duplicate_ids_and_missing_evidence_are_rejected(self) -> None:
        with self.assertRaisesRegex(BenchmarkSchemaError, "duplicate dataset case id"):
            load_dataset(self._write([_case(), _case()]))

        case = _case("fixture-no-evidence")
        case["human_labels"] = {"agentic_runtime": _label() | {"evidence": []}}
        with self.assertRaisesRegex(BenchmarkSchemaError, "evidence must contain"):
            load_dataset(self._write([case]))

    def test_score_without_score_evidence_is_rejected(self) -> None:
        case = _case("fixture-score-without-evidence")
        case["annotation"] = {"annotator": "test"}
        with self.assertRaisesRegex(BenchmarkSchemaError, "requires score_evidence"):
            load_dataset(self._write([case]))


if __name__ == "__main__":
    unittest.main()
