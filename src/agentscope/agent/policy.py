"""finish gateと調査coverage。"""

from __future__ import annotations

from dataclasses import dataclass


REQUIRED_CAPABILITIES = {
    "readme",
    "llm_calls",
    "tooling",
    "control_flow",
    "call_graph",
    "git_provenance",
    "github_metadata",
    "verification",
    "concept_lineage",
}


@dataclass(frozen=True)
class FinishCheck:
    accepted: bool
    missing: list[str]


def missing_capabilities(facts: dict[str, object]) -> list[str]:
    return sorted(
        capability
        for capability in REQUIRED_CAPABILITIES
        if facts.get(f"cap_{capability}") is not True
    )


def check_finish(facts: dict[str, object], decision: str) -> FinishCheck:
    missing = missing_capabilities(facts)
    if decision == "INSUFFICIENT_EVIDENCE":
        return FinishCheck(accepted=True, missing=missing)
    return FinishCheck(accepted=not missing, missing=missing)

