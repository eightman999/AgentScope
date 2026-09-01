from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.application import audit_local_directory
from agentscope.agent.action import ActionValidationError, parse_action
from agentscope.model.mock import MockModelProvider

from tests.helpers import action, fixture, finish


class AgentLoopTests(unittest.TestCase):
    def test_strict_action_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ActionValidationError):
            parse_action({"kind": "finish", "decision": "ENOUGH_EVIDENCE", "reason": "x", "missing_unknowns": [], "score": 10})

    def test_invalid_model_action_retries_once_then_stops(self) -> None:
        provider = MockModelProvider(
            [
                {"kind": "tool_call", "tool": "read_file", "arguments": {}, "unexpected": True},
                {"kind": "tool_call", "tool": "read_file", "arguments": {"path": "README.md"}},
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = audit_local_directory(
                fixture("insufficient"),
                artifacts=ArtifactStore.create(Path(directory), "run"),
                provider=provider,
            )
            events = result.artifacts.path("audit_trace.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "model_action_rejected"', events)
            self.assertIn('"attempt": 2', events)
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(result.report["runtime"]["status"], "failed")

    def test_finish_audit_tool_is_controller_gated(self) -> None:
        script = [
            {"kind": "tool_call", "tool": "finish_audit", "arguments": {"decision": "ENOUGH_EVIDENCE", "reason": "早すぎる", "missing_unknowns": []}},
            finish("INSUFFICIENT_EVIDENCE"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = audit_local_directory(
                fixture("insufficient"),
                artifacts=ArtifactStore.create(Path(directory), "run"),
                provider=MockModelProvider(script),
            )
            self.assertEqual(result.report["runtime"]["termination"], "INSUFFICIENT_EVIDENCE")
            trace = result.artifacts.path("audit_trace.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "finish_rejected"', trace)


if __name__ == "__main__":
    unittest.main()
