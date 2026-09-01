from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.git_snapshot import SnapshotLimits, local_snapshot
from agentscope.analysis.control_flow import rank_code_records, trace_call_graph
from agentscope.analysis.detectors import detect
from agentscope.analysis.inventory import FileRecord, build_inventory
from agentscope.analysis.search import search_code
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph

from tests.helpers import fixture


class StaticAnalysisTests(unittest.TestCase):
    def test_runtime_files_are_ranked_before_tests_and_examples(self) -> None:
        records = [
            FileRecord("tests/test_agent.py", 1, "python"),
            FileRecord("examples/agent.py", 1, "python"),
            FileRecord("src/runtime/agent.py", 1, "python"),
            FileRecord("libs/cli/js-examples/src/agent/graph.py", 1, "python"),
            FileRecord("libs/langgraph/langgraph/graph/state.py", 1, "python"),
        ]

        ranked = rank_code_records(records)

        self.assertEqual(
            [record.path for record in ranked],
            [
                "src/runtime/agent.py",
                "libs/langgraph/langgraph/graph/state.py",
                "libs/cli/js-examples/src/agent/graph.py",
                "examples/agent.py",
                "tests/test_agent.py",
            ],
        )

    def test_inventory_budget_prefers_runtime_before_total_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "src" / "runtime").mkdir(parents=True)
            (root / "docs" / "readme.md").write_text("d" * 20, encoding="utf-8")
            (root / "src" / "runtime" / "agent.py").write_text("x" * 20, encoding="utf-8")

            inventory = build_inventory(
                local_snapshot(root, commit_sha="fixture-sha"),
                SnapshotLimits(max_total_bytes=25),
            )

            self.assertEqual([record.path for record in inventory.files], ["src/runtime/agent.py"])

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
            self.assertEqual(result.priority_files, ["agent.py"])
            self.assertTrue(graph.has_edge_kind("controls"))
            self.assertTrue(graph.has_edge_kind("dispatches"))
            self.assertTrue(graph.has_edge_kind("observes"))
            self.assertTrue(graph.has_edge_kind("replans"))
            source_lines = (fixture("dynamic_agent") / "agent.py").read_text(encoding="utf-8").splitlines()
            for evidence in ledger.all():
                if evidence.file == "agent.py":
                    self.assertEqual(source_lines[evidence.start_line - 1], evidence.excerpt)

    def test_cross_file_trace_follows_model_value_through_helpers(self) -> None:
        snapshot = local_snapshot(fixture("cross_file_agent"), commit_sha="fixture-sha")
        inventory = build_inventory(snapshot)
        ledger = EvidenceLedger()
        graph = FactGraph()

        result = trace_call_graph(snapshot, inventory, ledger, graph, commit_sha="fixture-sha")

        self.assertIn("runner.py", result.matched_files)
        self.assertTrue(graph.has_edge_kind("calls"))
        self.assertTrue(graph.has_ordered_edge_path("controls", "dispatches", "observes", "replans"))
        self.assertEqual(result.coverage, "full")

    def test_graph_executor_contract_connects_registered_nodes(self) -> None:
        snapshot = local_snapshot(fixture("graph_executor_agent"), commit_sha="fixture-sha")
        inventory = build_inventory(snapshot)
        ledger = EvidenceLedger()
        graph = FactGraph()

        trace_call_graph(snapshot, inventory, ledger, graph, commit_sha="fixture-sha")

        self.assertTrue(graph.has_ordered_edge_path("controls", "dispatches", "observes", "replans"))
        contract_evidence = [
            evidence
            for evidence in ledger.all()
            if evidence.claim_key.startswith("trace.framework_")
        ]
        self.assertTrue(contract_evidence)
        self.assertTrue(
            all(evidence.display_ref.startswith("runtime.py:") for evidence in contract_evidence)
        )

    def test_ordered_path_does_not_combine_disconnected_edges(self) -> None:
        graph = FactGraph()
        graph.add_node(node_id="model:a", kind="model_output", label="model", evidence_ids=[])
        graph.add_node(node_id="selector:a", kind="action_selector", label="selector", evidence_ids=[])
        graph.add_node(node_id="selector:b", kind="action_selector", label="selector", evidence_ids=[])
        graph.add_node(node_id="dispatcher:b", kind="dispatcher", label="dispatcher", evidence_ids=[])
        graph.add_node(node_id="observation:b", kind="observation", label="observation", evidence_ids=[])
        graph.add_node(node_id="replanner:b", kind="replanner", label="replanner", evidence_ids=[])
        graph.add_edge(source="model:a", target="selector:a", kind="controls", evidence_ids=[])
        graph.add_edge(source="selector:b", target="dispatcher:b", kind="dispatches", evidence_ids=[])
        graph.add_edge(source="dispatcher:b", target="observation:b", kind="observes", evidence_ids=[])
        graph.add_edge(source="observation:b", target="replanner:b", kind="replans", evidence_ids=[])

        self.assertFalse(
            graph.has_ordered_edge_path("controls", "dispatches", "observes", "replans")
        )

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

    def test_tooling_detector_ignores_docs_notebooks_and_comment_only_hits(self) -> None:
        snapshot = local_snapshot(fixture("comment_keywords_only"), commit_sha="fixture-sha")
        inventory = build_inventory(snapshot)

        result = detect(snapshot, inventory, "tooling")

        self.assertEqual(result.hits, [])


if __name__ == "__main__":
    unittest.main()
