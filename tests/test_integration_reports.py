from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.github_metadata import GitHubMetadataSource
from agentscope.acquisition.github_url import parse_github_url
from agentscope.application import audit_local_directory

from tests.helpers import (
    complete_script,
    fixture,
    insufficient_script,
    metadata_source,
    mock_provider,
    provenance_runner,
)


class IntegrationReportTests(unittest.TestCase):
    def _audit(
        self,
        name: str,
        *,
        metadata=None,
        git_runner=None,
        dynamic=False,
        script=None,
    ):
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
        self.assertRegex(report["subject"]["audited_at"], r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T")
        self.assertEqual(report["tool_sequence"][-1], "finish")
        self.assertTrue(report["hypotheses"])
        self.assertIn("## tool sequence", result.artifacts.path("report.md").read_text(encoding="utf-8"))
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

    def test_ai_named_contributor_is_weak_not_explicit_assistance(self) -> None:
        result = self._audit(
            "ai_assisted_non_agent",
            metadata=metadata_source(fork=False),
            git_runner=provenance_runner(weak_ai_signal=True),
        )
        self.assertEqual(
            result.report["classifications"]["ai_assisted_development"]["value"],
            "unknown",
        )
        self.assertIn(
            "weak signal",
            result.report["classifications"]["ai_assisted_development"]["rationale_ja"],
        )

    def test_mcp_only_is_not_agentic_runtime(self) -> None:
        result = self._audit("mcp_only", metadata=metadata_source(fork=False))
        self.assertEqual(result.report["classifications"]["mcp_tooling"]["value"], "yes")
        self.assertEqual(result.report["classifications"]["agentic_runtime"]["value"], "no")

    def test_model_selected_tool_sequence_changes_with_observation(self) -> None:
        dynamic = self._audit("dynamic_agent", dynamic=True)
        fixed = self._audit("fixed_workflow")
        dynamic_tools = [item.tool for item in dynamic.context.state.action_history]
        fixed_tools = [item.tool for item in fixed.context.state.action_history]
        self.assertEqual(dynamic_tools[1:3], ["inspect_tooling", "inspect_llm_calls"])
        self.assertEqual(fixed_tools[1:3], ["inspect_llm_calls", "inspect_tooling"])
        self.assertNotEqual(dynamic_tools, fixed_tools)

    def test_derived_concept_and_fork_are_distinct(self) -> None:
        result = self._audit(
            "fork_derived",
            metadata=metadata_source(fork=False),
            git_runner=provenance_runner(),
        )
        self.assertEqual(result.report["classifications"]["formal_github_fork"]["value"], "no")
        self.assertEqual(result.report["classifications"]["derived_concept"]["value"], "yes")
        self.assertEqual(result.report["classifications"]["derived_concept"]["label"], "Karpathy/autoresearch")

        fork_result = self._audit(
            "fork_derived",
            metadata=metadata_source(
                fork=True,
                parent="karpathy/autoresearch",
            ),
            git_runner=provenance_runner(),
        )
        self.assertEqual(
            fork_result.report["classifications"]["formal_github_fork"]["value"],
            "yes",
        )
        self.assertEqual(
            fork_result.report["classifications"]["derived_concept"]["value"],
            "yes",
        )

    def test_api_unavailable_is_unknown_not_no(self) -> None:
        result = self._audit("insufficient")
        self.assertEqual(result.report["classifications"]["formal_github_fork"]["value"], "unknown")
        self.assertEqual(result.report["classifications"]["ai_assisted_development"]["value"], "unknown")

    def test_insufficient_evidence_is_explicit(self) -> None:
        result = self._audit("insufficient", script=insufficient_script())
        self.assertEqual(result.report["runtime"]["termination"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result.report["runtime"]["status"], "completed")
        self.assertTrue(result.report["unknowns"])
        for item in result.report["scores"]:
            self.assertIsNone(item["score"])
            self.assertEqual(item["state"], "unknown")
        for item in result.report["classifications"].values():
            self.assertEqual(item["value"], "unknown")

    def test_metadata_http_error_is_materialized_without_false_defaults(self) -> None:
        class ErrorResponse:
            status = 429

            def read(self):
                return b'{"message":"rate limited"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        with tempfile.TemporaryDirectory() as directory:
            artifacts = ArtifactStore.create(Path(directory), "run")
            result = GitHubMetadataSource(
                opener=lambda request, timeout: ErrorResponse()
            ).fetch_repository(parse_github_url("https://github.com/fixture/repository"), artifacts)
            self.assertFalse(result.available)
            self.assertEqual(result.status, 429)
            error_artifact = artifacts.path("provenance/github-repository-error.txt")
            self.assertIn("http_status=429", error_artifact.read_text(encoding="utf-8"))
            self.assertIsNone(result.data)


if __name__ == "__main__":
    unittest.main()
