"""Agentic実装候補を探す決定論的detector。"""

from __future__ import annotations

from dataclasses import dataclass

from agentscope.acquisition.git_snapshot import Snapshot, SnapshotLimits
from agentscope.analysis.inventory import Inventory
from agentscope.analysis.search import SearchHit, search_code


@dataclass
class DetectorResult:
    category: str
    hits: list[SearchHit]
    coverage: str

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "hits": [hit.__dict__ for hit in self.hits],
            "coverage": self.coverage,
        }


PATTERNS: dict[str, list[str]] = {
    "llm_calls": [
        "openai",
        "anthropic",
        "generativeai",
        "ollama",
        "llama",
        "chat.completions",
        "responses.create",
        "generate(",
        "completion",
        "model.invoke",
        "transformers",
    ],
    "tooling": [
        "mcp",
        "tool_calls",
        "function_call",
        "register_tool",
        "add_tool",
        "@tool",
        "dispatcher",
        "dispatch(",
        "tool_registry",
        "tools=",
    ],
    "control_flow": [
        "planner",
        "replan",
        "while ",
        "for ",
        "retry",
        "budget",
        "termination",
        "state",
        "unknown",
        "observation",
        "feedback",
    ],
    "concept_lineage": [
        "karpathy/autoresearch",
        "autoresearch",
    ],
}


def detect(
    snapshot: Snapshot,
    inventory: Inventory,
    category: str,
    *,
    max_hits: int = 80,
    limits: SnapshotLimits | None = None,
) -> DetectorResult:
    if category not in PATTERNS:
        raise ValueError(f"unknown detector category: {category}")
    hits: list[SearchHit] = []
    seen: set[tuple[str, int]] = set()
    for query in PATTERNS[category]:
        for hit in search_code(
            snapshot,
            inventory,
            query,
            max_hits=max_hits,
            limits=limits,
        ):
            key = (hit.path, hit.line)
            if key not in seen:
                seen.add(key)
                hits.append(hit)
            if len(hits) >= max_hits:
                break
        if len(hits) >= max_hits:
            break
    return DetectorResult(
        category=category,
        hits=hits,
        coverage=inventory.coverage,
    )
