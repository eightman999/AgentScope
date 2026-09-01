"""Agent loopの永続化可能なstate。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Hypothesis:
    id: str
    text: str
    status: str = "open"


@dataclass
class ActionRecord:
    step: int
    kind: str
    tool: str | None
    arguments: dict[str, Any]
    result: str
    selected_by_model: bool = True


@dataclass
class AuditState:
    run_id: str
    input_url: str
    canonical_url: str
    commit_sha: str
    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    visited_files: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    action_history: list[ActionRecord] = field(default_factory=list)
    budget_remaining: int = 14
    termination: str | None = None
    status: str = "running"

    @classmethod
    def initial(
        cls,
        *,
        run_id: str,
        input_url: str,
        canonical_url: str,
        commit_sha: str,
        budget: int = 14,
    ) -> "AuditState":
        return cls(
            run_id=run_id,
            input_url=input_url,
            canonical_url=canonical_url,
            commit_sha=commit_sha,
            hypotheses=[
                Hypothesis("h1", "This may be a fixed workflow"),
                Hypothesis("h2", "There may be external agent control via MCP"),
            ],
            unknowns=[
                "Who chooses the next action?",
                "Is there environment feedback?",
                "Is there formal fork or derived provenance?",
            ],
            budget_remaining=budget,
        )

    def add_evidence_ids(self, evidence_ids: list[str]) -> None:
        for evidence_id in evidence_ids:
            if evidence_id not in self.evidence_ids:
                self.evidence_ids.append(evidence_id)

    def add_observation(self, text: str, *, max_items: int = 20) -> None:
        self.observations.append(text)
        if len(self.observations) > max_items:
            del self.observations[:-max_items]

    def add_visited_file(self, path: str) -> None:
        if path not in self.visited_files:
            self.visited_files.append(path)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

