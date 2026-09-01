from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.git_snapshot import local_snapshot
from agentscope.analysis.control_flow import trace_call_graph
from agentscope.analysis.inventory import build_inventory
from agentscope.application import audit_local_directory
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph

from tests.helpers import complete_script, fixture, mock_provider


class AdversarialPrecisionTests(unittest.TestCase):
    def _trace(self, name: str) -> FactGraph:
        snapshot = local_snapshot(fixture(name), commit_sha="fixture-sha")
        graph = FactGraph()
        trace_call_graph(
            snapshot,
            build_inventory(snapshot),
            EvidenceLedger(),
            graph,
            commit_sha="fixture-sha",
        )
        return graph

    def test_discarded_model_return_does_not_control_fixed_dispatch(self) -> None:
        graph = self._trace("fixed_model_output_discarded")

        self.assertTrue(graph.has_node_kind("model_call"))
        self.assertFalse(graph.has_node_kind("model_output"))
        self.assertFalse(
            graph.has_edge_kind("controls", "dispatches", "observes", "replans")
        )

    def test_comment_only_agent_vocabulary_is_ignored(self) -> None:
        graph = self._trace("comment_keywords_only")

        self.assertFalse(graph.has_node_kind("model_call"))
        self.assertFalse(
            graph.has_edge_kind("controls", "dispatches", "observes", "replans")
        )

    def test_adversarial_negative_fixture_is_not_agentic_in_full_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = audit_local_directory(
                fixture("fixed_model_output_discarded"),
                artifacts=ArtifactStore.create(Path(directory), "run"),
                provider=mock_provider(complete_script()),
            )

        self.assertEqual(
            result.report["classifications"]["agentic_runtime"]["value"],
            "no",
        )
        agenticity = next(
            item for item in result.report["scores"] if item["key"] == "agenticity"
        )
        self.assertEqual(agenticity["score"], 2.0)

    def test_generic_derived_word_is_not_known_concept_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as artifacts_directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "This implementation is derived from a generic prior version.\n",
                encoding="utf-8",
            )
            result = audit_local_directory(
                root,
                artifacts=ArtifactStore.create(Path(artifacts_directory), "run"),
                provider=mock_provider(complete_script()),
            )

        self.assertEqual(
            result.report["classifications"]["derived_concept"]["value"],
            "no",
        )


if __name__ == "__main__":
    unittest.main()
