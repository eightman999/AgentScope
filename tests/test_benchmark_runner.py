from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentscope.benchmark.runner import (
    BenchmarkRunError,
    load_predictions,
    run_benchmark,
    score_benchmark,
)


SHA = "0123456789abcdef0123456789abcdef01234567"


def _dataset_case() -> dict[str, object]:
    return {
        "id": "fixture-agent",
        "url": "https://github.com/fixture/repository",
        "commit_sha": SHA,
        "category": "clearly_agentic",
        "annotation_status": "adjudicated",
        "human_labels": {
            "agentic_runtime": {
                "value": "yes",
                "confidence": "high",
                "rationale": "test",
                "evidence": [
                    {
                        "source_kind": "repository",
                        "file": "README.md",
                        "start_line": 1,
                        "end_line": 1,
                        "excerpt": "agent",
                        "reason": "test",
                        "commit_sha": SHA,
                    }
                ],
            }
        },
        "human_scores": {},
        "annotation": {"annotator": "test"},
    }


def _report() -> dict[str, object]:
    return {
        "subject": {"commit_sha": SHA},
        "classifications": {
            "agentic_runtime": {"value": "yes", "evidence_ids": ["e1"]}
        },
        "evidence": [{"id": "e1", "display_ref": "README.md:1"}],
        "scores": [],
    }


class BenchmarkRunnerTests(unittest.TestCase):
    def _dataset(self, directory: Path) -> Path:
        path = directory / "dataset.jsonl"
        path.write_text(
            json.dumps(_dataset_case(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def test_dry_run_selects_cases_without_creating_audit_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = self._dataset(root)
            output = root / "run"
            result = run_benchmark(dataset, output, dry_run=True)

            self.assertEqual(result["selected_ids"], ["fixture-agent"])
            self.assertFalse(output.exists())

    def test_score_loads_saved_reports_and_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = self._dataset(root)
            run_dir = root / "run"
            report_path = run_dir / "artifacts" / "fixture-agent" / "report.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps(_report()), encoding="utf-8")
            (run_dir / "results.jsonl").write_text(
                json.dumps(
                    {
                        "id": "fixture-agent",
                        "status": "completed",
                        "report_path": "artifacts/fixture-agent/report.json",
                        "actual_commit_sha": SHA,
                        "error": None,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            metrics = score_benchmark(dataset, run_dir / "results.jsonl")

            self.assertEqual(metrics["primary"]["counts"]["true_positive"], 1)
            self.assertTrue((run_dir / "benchmark-report.json").is_file())
            self.assertTrue((run_dir / "benchmark-report.md").is_file())

    def test_report_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "run" / "results.jsonl"
            results.parent.mkdir(parents=True)
            results.write_text(
                json.dumps(
                    {
                        "id": "fixture-agent",
                        "status": "completed",
                        "report_path": "../report.json",
                        "actual_commit_sha": SHA,
                        "error": None,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BenchmarkRunError, "escapes benchmark run"):
                load_predictions(results)


if __name__ == "__main__":
    unittest.main()
