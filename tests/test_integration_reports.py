from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.application import audit_local_directory

from tests.helpers import complete_script, fixture, metadata_source, mock_provider, provenance_runner


class IntegrationReportTests(unittest.TestCase):
    def _audit(self, name: str, *, metadata=None, git_runner=None, dynamic=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return audit_local_directory(
            fixture(name),
            artifacts=ArtifactStore.create(Path(directory.name), "run"),
            provider=mock_provider(complete_script(dynamic_selection=dynamic)),
            metadata_source=metadata,
            git_runner=git_runner,
        )

    def test_dynamic_agent_gets_separate_runtime_and_tool_evidence(self) -> None:
        result = self._audit("dynamic_agent", dynamic=True)
        report = result.report
        self.assertEqual(report["runtime"]["termination"], "ENOUGH_EVIDENCE")
        self.assertEqual(report["classifications"]["agentic_runtime"]["value"], "yes")
        self.assertEqual(report["classifications"]["mcp_tooling"]["value"], "yes")
        self.assertEqual(report["scores"][-1]["key"], "agent_tooling")
        self.assertEqual(len(result.context.state.action_history), 9)
        self.assertTrue(result.artifacts.path("report.md").is_file())
        self.assertTrue(result.artifacts.path("report.json").is_file())
        self.assertTrue(result.artifacts.path("audit_trace.jsonl").is_file())
        for item in report["scores"]:
            self.assertTrue(item["evidence_ids"])
        for item in report["classifications"].values():
            self.assertTrue(item["evidence_ids"])

    def test_ai_assistance_does_not_imply_agentic_runtime(self) -> None:
        result = self._audit(
            "ai_assisted_non_agent",
            metadata=metadata_source(fork=False),
            git_runner=provenance_runner(ai_signal=True),
        )
        self.assertEqual(result.report["classifications"]["ai_assisted_development"]["value"], "yes")
        self.assertEqual(result.report["classifications"]["agentic_runtime"]["value"], "no")
        self.assertEqual(result.report["classifications"]["formal_github_fork"]["value"], "no")

    def test_mcp_only_is_not_agentic_runtime(self) -> None:
        result = self._audit("mcp_only", metadata=metadata_source(fork=False))
        self.assertEqual(result.report["classifications"]["mcp_tooling"]["value"], "yes")
        self.assertEqual(result.report["classifications"]["agentic_runtime"]["value"], "no")

    def test_derived_concept_and_fork_are_distinct(self) -> None:
        result = self._audit(
            "fork_derived",
            metadata=metadata_source(fork=False),
            git_runner=provenance_runner(),
        )
        self.assertEqual(result.report["classifications"]["formal_github_fork"]["value"], "no")
        self.assertEqual(result.report["classifications"]["derived_concept"]["value"], "yes")
        self.assertEqual(result.report["classifications"]["derived_concept"]["label"], "Karpathy/autoresearch")

    def test_api_unavailable_is_unknown_not_no(self) -> None:
        result = self._audit("insufficient")
        self.assertEqual(result.report["classifications"]["formal_github_fork"]["value"], "unknown")
        self.assertEqual(result.report["classifications"]["ai_assisted_development"]["value"], "unknown")


if __name__ == "__main__":
    unittest.main()
