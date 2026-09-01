from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.git_snapshot import SnapshotLimits, local_snapshot
from agentscope.analysis.inventory import build_inventory
from agentscope.analysis.line_reader import ReadFileError, read_lines
from agentscope.analysis.search import search_code
from agentscope.application import audit_local_directory
from agentscope.model.mock import MockModelProvider
from agentscope.report.lint import ReportLintError, lint_report

from tests.helpers import action, fixture, finish


class SecurityAndReportTests(unittest.TestCase):
    def test_path_and_range_guards_reject_unsafe_read(self) -> None:
        snapshot = local_snapshot(fixture("insufficient"), commit_sha="fixture-sha")
        with self.assertRaises((ReadFileError, ValueError)):
            read_lines(snapshot, "../README.md")
        with self.assertRaises(ReadFileError):
            read_lines(snapshot, "README.md", start_line=0)
        with self.assertRaises(ReadFileError):
            read_lines(snapshot, "README.md", start_line=1, end_line=201)

    def test_symlink_and_binary_are_partial_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "text.txt").write_text("text\n", encoding="utf-8")
            (root / "binary.bin").write_bytes(b"\x00\x01\x02")
            (root / "link.txt").symlink_to(root / "text.txt")
            inventory = build_inventory(local_snapshot(root), SnapshotLimits())
            skipped = {item.path: item.skip_reason for item in inventory.skipped}
            self.assertEqual(inventory.coverage, "partial")
            self.assertEqual(skipped["binary.bin"], "binary")
            self.assertEqual(skipped["link.txt"], "symlink")

    def test_oversized_file_is_excluded_from_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            limits = SnapshotLimits()
            (root / "large.txt").write_bytes(b"x" * (limits.max_file_bytes + 1))
            inventory = build_inventory(local_snapshot(root), limits)
            skipped = {item.path: item.skip_reason for item in inventory.skipped}
            self.assertEqual(inventory.coverage, "partial")
            self.assertEqual(skipped["large.txt"], "file too large")

    def test_malformed_utf8_and_search_guards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.py").write_bytes(b"valid\n\xff\n")
            snapshot = local_snapshot(root)
            inventory = build_inventory(snapshot, SnapshotLimits())
            self.assertEqual(inventory.coverage, "partial")
            self.assertEqual(inventory.skipped[0].skip_reason, "malformed utf-8")
            with self.assertRaises(ValueError):
                search_code(snapshot, inventory, "x", paths=["../broken.py"])
            with self.assertRaises(ValueError):
                search_code(snapshot, inventory, "[", regex=True)

    def test_report_lint_fails_closed_on_line_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = audit_local_directory(
                fixture("dynamic_agent"),
                artifacts=ArtifactStore.create(Path(directory), "run"),
                provider=MockModelProvider(
                    [
                        action("read_file", {"path": "README.md"}),
                        action("inspect_llm_calls"),
                        action("inspect_tooling"),
                        action("trace_call_graph"),
                        action("inspect_git_provenance"),
                        action("inspect_github_metadata"),
                        action("inspect_tests"),
                        action("inspect_concept_lineage"),
                        finish(),
                    ]
                ),
            )
            broken = dict(result.report)
            broken["evidence"] = [dict(item) for item in result.report["evidence"]]
            broken["evidence"][0]["excerpt"] = "forged"
            with self.assertRaises(ReportLintError):
                lint_report(
                    broken,
                    snapshot_root=result.context.snapshot.root,
                    artifact_root=result.artifacts.root,
                )


if __name__ == "__main__":
    unittest.main()
