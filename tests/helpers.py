"""監査integration test用のfixtureとprovider補助。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agentscope.acquisition.github_metadata import GitHubMetadataSource
from agentscope.model.mock import MockModelProvider


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


def action(tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "tool_call",
        "tool": tool,
        "arguments": arguments or {},
        "hypothesis": "監査対象の次の証拠を確認する",
        "focus": ["agentic_runtime"],
    }


def finish(decision: str = "ENOUGH_EVIDENCE") -> dict[str, Any]:
    return {
        "kind": "finish",
        "decision": decision,
        "reason": "必須の監査領域を調査した",
        "missing_unknowns": [],
    }


def complete_script(*, dynamic_selection: bool = False) -> list[dict[str, Any] | Any]:
    def choose_after_read(context: Any) -> dict[str, Any]:
        observations = "\n".join(context.state.get("observations", []))
        if dynamic_selection and "dynamic agent" in observations.lower():
            return action("inspect_tooling")
        return action("inspect_llm_calls")

    second = choose_after_read if dynamic_selection else action("inspect_llm_calls")
    third = action("inspect_llm_calls") if dynamic_selection else action("inspect_tooling")
    return [
        action("read_file", {"path": "README.md", "start_line": 1, "end_line": 40}),
        second,
        third,
        action("trace_call_graph"),
        action("inspect_git_provenance"),
        action("inspect_github_metadata"),
        action("inspect_tests"),
        action("inspect_concept_lineage"),
        finish(),
    ]


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def metadata_source(*, fork: bool, parent: str | None = None) -> GitHubMetadataSource:
    payload: dict[str, Any] = {
        "full_name": "fixture/repository",
        "fork": fork,
        "html_url": "https://github.com/fixture/repository",
    }
    if parent is not None:
        payload["parent"] = {"full_name": parent}
    return GitHubMetadataSource(opener=lambda request, timeout: FakeResponse(payload))


def provenance_runner(*, ai_signal: bool = False):
    def run(args: list[str], *, cwd: Path, timeout: int) -> Any:
        if args[1] == "log":
            body = "commit=fixture\nAuthor=Fixture <fixture@example.com>\nCommitter=Fixture <fixture@example.com>\n"
            if ai_signal:
                body += "Co-authored-by: Claude <noreply@anthropic.com>\n"
            body += "---\n"
            return SimpleNamespace(returncode=0, stdout=body, stderr="")
        if args[1] == "remote":
            return SimpleNamespace(
                returncode=0,
                stdout="origin https://github.com/fixture/repository.git (fetch)\n",
                stderr="",
            )
        raise AssertionError(f"unexpected git command: {args}")

    return run


def mock_provider(script: list[dict[str, Any] | Any]) -> MockModelProvider:
    return MockModelProvider(script)
