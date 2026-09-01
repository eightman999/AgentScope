from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.application import audit_local_directory

from tests.helpers import (
    complete_script,
    fixture,
    insufficient_script,
    metadata_source,
    mock_provider,
    provenance_runner,
)


GOLDEN = Path(__file__).parent / "golden"


class GoldenReportTests(unittest.TestCase):
    def _audit(self, name: str):
        metadata = None
        git_runner = None
        dynamic = False
        script = None
        if name == "dynamic_agent":
            dynamic = True
        elif name == "mcp_only":
            metadata = metadata_source(fork=False)
        elif name == "ai_assisted_non_agent":
            metadata = metadata_source(fork=False)
            git_runner = provenance_runner(ai_signal=True)
        elif name == "fork_derived":
            metadata = metadata_source(fork=True, parent="karpathy/autoresearch")
            git_runner = provenance_runner()
        elif name == "insufficient":
            script = insufficient_script()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return audit_local_directory(
            fixture(name),
            artifacts=ArtifactStore.create(Path(directory.name), "run"),
            provider=mock_provider(
                script if script is not None else complete_script(dynamic_selection=dynamic)
            ),
            metadata_source=metadata,
            git_runner=git_runner,
        )

    def test_fixture_reports_match_golden_classification_and_scores(self) -> None:
        for golden_path in sorted(GOLDEN.glob("*.json")):
            with self.subTest(fixture=golden_path.stem):
                expected = json.loads(golden_path.read_text(encoding="utf-8"))
                actual = self._audit(golden_path.stem).report
                self.assertEqual(
                    actual["runtime"]["termination"],
                    expected["runtime"]["termination"],
                )
                actual_scores = {
                    item["key"]: {"score": item["score"], "state": item["state"]}
                    for item in actual["scores"]
                }
                self.assertEqual(actual_scores, expected["scores"])
                actual_classifications = {
                    key: item["value"]
                    for key, item in actual["classifications"].items()
                }
                self.assertEqual(actual_classifications, expected["classifications"])


if __name__ == "__main__":
    unittest.main()
