from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.git_snapshot import local_snapshot
from agentscope.analysis.control_flow import trace_call_graph
from agentscope.analysis.inventory import build_inventory
from agentscope.analysis.search import search_code
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph

from tests.helpers import fixture


class StaticAnalysisTests(unittest.TestCase):
    def test_dynamic_trace_uses_real_source_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifacts = ArtifactStore.create(Path(directory), "run")
            snapshot = local_snapshot(fixture("dynamic_agent"), commit_sha="fixture-sha")
            inventory = build_inventory(snapshot)
            ledger = EvidenceLedger()
            graph = FactGraph()
            result = trace_call_graph(
                snapshot,
                inventory,
                ledger,
                graph,
                commit_sha="fixture-sha",
            )
            self.assertIn("agent.py", result.matched_files)
            self.assertTrue(graph.has_edge_kind("controls"))
            self.assertTrue(graph.has_edge_kind("dispatches"))
            self.assertTrue(graph.has_edge_kind("observes"))
            self.assertTrue(graph.has_edge_kind("replans"))
            source_lines = (fixture("dynamic_agent") / "agent.py").read_text(encoding="utf-8").splitlines()
            for evidence in ledger.all():
                if evidence.file == "agent.py":
                    self.assertEqual(source_lines[evidence.start_line - 1], evidence.excerpt)

    def test_fixed_workflow_has_model_candidate_but_no_runtime_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = local_snapshot(fixture("fixed_workflow"), commit_sha="fixture-sha")
            inventory = build_inventory(snapshot)
            ledger = EvidenceLedger()
            graph = FactGraph()
            trace_call_graph(snapshot, inventory, ledger, graph, commit_sha="fixture-sha")
            self.assertTrue(graph.has_node_kind("model_call"))
            self.assertFalse(graph.has_edge_kind("controls"))
            self.assertFalse(graph.has_edge_kind("dispatches"))

    def test_search_respects_path_filter_and_does_not_execute_source(self) -> None:
        snapshot = local_snapshot(fixture("prompt_injection"), commit_sha="fixture-sha")
        inventory = build_inventory(snapshot)
        hits = search_code(snapshot, inventory, "arbitrary commands", paths=["README.md"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].path, "README.md")

    def test_search_preserves_long_source_lines_for_evidence_lint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_line = "needle " + ("x" * 1200)
            (root / "long.txt").write_text(source_line + "\n", encoding="utf-8")
            snapshot = local_snapshot(root, commit_sha="fixture-sha")
            inventory = build_inventory(snapshot)
            hits = search_code(snapshot, inventory, "needle")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].text, source_line)


if __name__ == "__main__":
    unittest.main()
