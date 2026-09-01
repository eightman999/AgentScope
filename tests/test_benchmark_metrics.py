from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentscope.benchmark.metrics import (
    BenchmarkPrediction,
    compute_benchmark_metrics,
)
from agentscope.benchmark.report import render_benchmark_markdown
from agentscope.benchmark.schema import BenchmarkCase


SHA = "0123456789abcdef0123456789abcdef01234567"


def _evidence() -> dict[str, object]:
    return {
        "source_kind": "repository",
        "file": "README.md",
        "start_line": 1,
        "end_line": 1,
        "excerpt": "runtime evidence",
        "reason": "test evidence",
        "commit_sha": SHA,
    }


def _label(value: str) -> dict[str, object]:
    return {
        "value": value,
        "confidence": "high",
        "rationale": "test label",
        "evidence": [_evidence()],
    }


def _case(case_id: str, value: str, category: str = "clearly_agentic") -> BenchmarkCase:
    return BenchmarkCase.from_dict(
        {
            "id": case_id,
            "url": f"https://github.com/fixture/{case_id}",
            "commit_sha": SHA,
            "category": category,
            "annotation_status": "adjudicated",
            "human_labels": {"agentic_runtime": _label(value)},
            "human_scores": {"agenticity": 8.0},
            "annotation": {
                "annotator": "test",
                "score_evidence": {"agenticity": [_evidence()]},
            },
        }
    )


def _report(value: str, score: float = 8.0) -> dict[str, object]:
    return {
        "subject": {"commit_sha": SHA},
        "classifications": {
            "agentic_runtime": {
                "value": value,
                "evidence_ids": ["e1"],
            }
        },
        "evidence": [{"id": "e1", "display_ref": "agent.py:10"}],
        "scores": [{"key": "agenticity", "score": score}],
    }


class BenchmarkMetricsTests(unittest.TestCase):
    def test_unknown_is_reported_as_abstention_not_false_positive_or_no(self) -> None:
        cases = [
            _case("positive-hit", "yes"),
            _case("positive-abstain", "yes"),
            _case("negative-fp", "no"),
            _case("negative-hit", "no"),
            _case("ambiguous", "ambiguous", "hard_case"),
        ]
        predictions = {
            "positive-hit": BenchmarkPrediction("positive-hit", "completed", report=""),
            "positive-abstain": BenchmarkPrediction("positive-abstain", "completed", report=_report("unknown")),
            "negative-fp": BenchmarkPrediction("negative-fp", "completed", report=_report("yes")),
            "negative-hit": BenchmarkPrediction("negative-hit", "completed", report=_report("no")),
            "ambiguous": BenchmarkPrediction("ambiguous", "completed", report=_report("yes")),
        }
        # The first report intentionally has an incomplete classification object and
        # is therefore treated as a missing prediction, not as a forced label.
        metrics = compute_benchmark_metrics(cases, predictions)
        primary = metrics["primary"]

        self.assertEqual(primary["confusion_matrix"]["yes"]["missing"], 1)
        self.assertEqual(primary["counts"]["true_positive"], 0)
        self.assertEqual(primary["counts"]["false_positive"], 1)
        self.assertEqual(primary["counts"]["abstained_positive"], 1)
        self.assertEqual(primary["counts"]["false_negative"], 0)
        self.assertEqual(primary["ambiguous_gold_n"], 1)
        self.assertEqual(primary["missing_prediction_n"], 1)
        self.assertEqual(primary["rates"]["recall"], 0.0)
        self.assertEqual(primary["rates"]["false_negative_rate"], 1.0)
        self.assertIn("positive-abstain", metrics["errors"]["agentic_runtime"]["abstained_positive"][0]["id"])

    def test_score_metrics_and_markdown_include_errors(self) -> None:
        cases = [_case("score-case", "yes")]
        predictions = {
            "score-case": BenchmarkPrediction(
                "score-case", "completed", report=_report("yes", score=6.0), report_path="artifacts/score/report.json"
            )
        }
        metrics = compute_benchmark_metrics(cases, predictions)
        self.assertEqual(metrics["scores"]["agenticity"]["mae"], 2.0)
        self.assertEqual(metrics["scores"]["agenticity"]["rmse"], 2.0)
        markdown = render_benchmark_markdown(metrics)
        self.assertIn("precision=100.0%", markdown)
        self.assertIn("False positives", markdown)
        self.assertIn("Agentic runtime", markdown)

    def test_metrics_are_json_serializable(self) -> None:
        case = _case("json-case", "no", "llm_non_agent")
        metrics = compute_benchmark_metrics(
            [case],
            {"json-case": BenchmarkPrediction("json-case", "failed", error="network")},
        )
        encoded = json.dumps(metrics, ensure_ascii=False)
        self.assertIn('"schema_version": "0.1"', encoded)


if __name__ == "__main__":
    unittest.main()
