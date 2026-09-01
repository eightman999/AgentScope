"""FactGraphとEvidenceLedgerからの決定論的score計算。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.analysis.provenance import ProvenanceFacts
from agentscope.analysis.verification import VerificationFacts
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph
from agentscope.domain.unknowns import model_output_integrity_evidence_ids


SCORE_KEYS = (
    "originality",
    "agenticity",
    "dynamic_tool_selection",
    "feedback_adaptation",
    "goal_directed_loop",
    "verification",
    "agent_tooling",
)

SCORE_LABELS = {
    "originality": "Originality / 自作度",
    "agenticity": "Agenticity",
    "dynamic_tool_selection": "Dynamic tool selection",
    "feedback_adaptation": "Feedback adaptation",
    "goal_directed_loop": "Goal-directed loop",
    "verification": "Verification",
    "agent_tooling": "Agent tooling",
}


@dataclass(frozen=True)
class ScoreItem:
    key: str
    label: str
    score: float | None
    state: str
    confidence: str
    rationale_ja: str
    evidence_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coverage_evidence(
    *,
    artifacts: ArtifactStore,
    ledger: EvidenceLedger,
    commit_sha: str,
    claim_key: str,
    message: str,
) -> str:
    path = "provenance/coverage.txt"
    destination = artifacts.path(path)
    content = destination.read_text(encoding="utf-8") if destination.exists() else ""
    line = len(content.splitlines()) + 1
    content += message.rstrip() + "\n"
    artifacts.write_text(path, content)
    return ledger.add(
        claim_key=claim_key,
        source_kind="derived_manifest",
        file=path,
        start_line=line,
        end_line=line,
        excerpt=message.rstrip(),
        commit_sha=commit_sha,
        reason=message.rstrip(),
        confidence="unknown",
    ).id


def _evidence(
    *,
    ledger: EvidenceLedger,
    artifacts: ArtifactStore,
    commit_sha: str,
    claim_key: str,
    prefixes: tuple[str, ...],
    message: str,
) -> list[str]:
    ids = [item.id for item in ledger.all() if item.claim_key.startswith(prefixes)]
    if ids:
        return list(dict.fromkeys(ids[:6]))
    return [
        _coverage_evidence(
            artifacts=artifacts,
            ledger=ledger,
            commit_sha=commit_sha,
            claim_key=claim_key,
            message=message,
        )
    ]


def _graph_evidence(graph: FactGraph, *kinds: str) -> list[str]:
    return list(
        dict.fromkeys(
            graph.edge_evidence(*kinds) + graph.node_evidence(*kinds)
        )
    )


def _item(
    *,
    key: str,
    score: float | None,
    state: str,
    confidence: str,
    rationale: str,
    evidence_ids: list[str],
) -> ScoreItem:
    if score is not None and not 0.0 <= score <= 10.0:
        raise ValueError(f"score out of range for {key}: {score}")
    if state not in {"confirmed", "negative", "unknown"}:
        raise ValueError(f"invalid score state: {state}")
    return ScoreItem(
        key=key,
        label=SCORE_LABELS[key],
        score=score,
        state=state,
        confidence=confidence,
        rationale_ja=rationale,
        evidence_ids=evidence_ids,
    )


def _complete_coverage(facts: dict[str, Any], extra_key: str | None = None) -> bool:
    if facts.get("inventory_coverage", "full") != "full":
        return False
    return extra_key is None or facts.get(extra_key, "full") == "full"


def calculate_scores(
    *,
    graph: FactGraph,
    ledger: EvidenceLedger,
    artifacts: ArtifactStore,
    commit_sha: str,
    facts: dict[str, Any],
) -> list[ScoreItem]:
    if facts.get("evaluation_unknown"):
        evidence_ids = model_output_integrity_evidence_ids(
            ledger=ledger,
            artifacts=artifacts,
            commit_sha=commit_sha,
            reason="Model output integrity failure propagated to every score axis.",
        )
        return [
            _item(
                key=key,
                score=None,
                state="unknown",
                confidence="unknown",
                rationale="モデル出力の整合性を検証できないため、この評価軸はUnknownです。",
                evidence_ids=evidence_ids,
            )
            for key in SCORE_KEYS
        ]
    items: list[ScoreItem] = []

    metadata = facts.get("github_metadata")
    provenance = facts.get("provenance")
    fork_value = None
    if metadata is not None and getattr(metadata, "available", False):
        fork_value = (getattr(metadata, "data", None) or {}).get("fork")
    derived_hits = int(facts.get("derived_hits", 0) or 0)
    originality_ids = _evidence(
        ledger=ledger,
        artifacts=artifacts,
        commit_sha=commit_sha,
        claim_key="score.originality",
        prefixes=("provenance.",),
        message="Originality evidence was insufficient in the bounded provenance scan.",
    )
    if fork_value is True:
        originality = (2.0, "negative", "high", "Formal fork metadata lowers the evidence-based originality estimate.")
    elif fork_value is False and derived_hits:
        originality = (4.5, "confirmed", "medium", "The repository is not a formal fork, but an explicit derived concept was found.")
    elif fork_value is False and isinstance(provenance, ProvenanceFacts) and provenance.available:
        originality = (7.0, "confirmed", "medium", "No formal fork was reported and bounded Git provenance was available.")
    elif isinstance(provenance, ProvenanceFacts) and provenance.available:
        originality = (None, "unknown", "low", "Git provenance exists but formal fork metadata is unavailable.")
    else:
        originality = (None, "unknown", "unknown", "Formal lineage and provenance could not be established.")
    items.append(
        _item(
            key="originality",
            score=originality[0],
            state=originality[1],
            confidence=originality[2],
            rationale=originality[3],
            evidence_ids=originality_ids,
        )
    )

    has_model = graph.has_node_kind("model_call")
    has_control = graph.has_edge_kind("controls")
    has_dispatch = graph.has_edge_kind("dispatches")
    has_observation = graph.has_edge_kind("observes")
    has_replan = graph.has_edge_kind("replans")
    trace_ids = _graph_evidence(graph, "controls", "dispatches", "observes", "replans", "model_call")
    if not trace_ids:
        trace_ids = _evidence(
            ledger=ledger,
            artifacts=artifacts,
            commit_sha=commit_sha,
            claim_key="score.agenticity",
            prefixes=("trace.",),
            message="No call/data-flow trace was available for Agenticity.",
        )
    if has_model and has_control and has_dispatch and has_observation and has_replan:
        agenticity = (9.0, "confirmed", "high", "Model control, dispatch, observation, and replanning form one traced path.")
    elif has_model and has_control and has_dispatch:
        agenticity = (6.0, "confirmed", "medium", "Model-controlled dispatch is visible, but feedback adaptation is incomplete.")
    elif has_model:
        agenticity = (2.0, "negative", "medium", "A model call exists, but runtime action control is not traced.")
    elif facts.get("cap_call_graph") and _complete_coverage(facts, "trace_coverage"):
        agenticity = (0.0, "negative", "medium", "The bounded call graph found no model-controlled runtime path.")
    else:
        agenticity = (None, "unknown", "unknown", "The runtime call graph was not sufficiently inspected.")
    items.append(
        _item(
            key="agenticity",
            score=agenticity[0],
            state=agenticity[1],
            confidence=agenticity[2],
            rationale=agenticity[3],
            evidence_ids=trace_ids,
        )
    )

    tooling_ids = _evidence(
        ledger=ledger,
        artifacts=artifacts,
        commit_sha=commit_sha,
        claim_key="score.dynamic_tool_selection",
        prefixes=("trace.action_selector", "trace.dispatch", "candidate.tooling"),
        message="Dynamic tool-selection evidence was not found.",
    )
    tooling_hits = int(facts.get("tooling_hits", 0) or 0)
    if has_control and has_dispatch and has_replan and tooling_hits:
        dynamic = (9.0, "confirmed", "high", "A model-controlled tool dispatch is connected to a replanning path.")
    elif has_control and has_dispatch:
        dynamic = (7.0, "confirmed", "medium", "Model-controlled dispatch is traced, but observed variation is not established.")
    elif tooling_hits:
        dynamic = (3.0, "negative", "low", "Tooling candidates exist, but dynamic model selection is not traced.")
    elif facts.get("cap_tooling") and _complete_coverage(facts):
        dynamic = (0.0, "negative", "medium", "The bounded tooling scan found no tool-selection surface.")
    else:
        dynamic = (None, "unknown", "unknown", "Tool-selection coverage is incomplete.")
    items.append(
        _item(
            key="dynamic_tool_selection",
            score=dynamic[0],
            state=dynamic[1],
            confidence=dynamic[2],
            rationale=dynamic[3],
            evidence_ids=tooling_ids,
        )
    )

    feedback_ids = _graph_evidence(graph, "observes", "replans")
    if not feedback_ids:
        feedback_ids = _evidence(
            ledger=ledger,
            artifacts=artifacts,
            commit_sha=commit_sha,
            claim_key="score.feedback_adaptation",
            prefixes=("trace.observation", "trace.replan"),
            message="Feedback adaptation evidence was not found.",
        )
    if has_observation and has_replan:
        feedback = (9.0, "confirmed", "high", "An observation is connected to a replanning edge.")
    elif has_observation:
        feedback = (3.0, "negative", "medium", "An observation candidate exists without a traced replanning edge.")
    elif facts.get("cap_call_graph") and _complete_coverage(facts, "trace_coverage"):
        feedback = (0.0, "negative", "medium", "No observation-to-replanning path was found.")
    else:
        feedback = (None, "unknown", "unknown", "Feedback coverage is incomplete.")
    items.append(
        _item(
            key="feedback_adaptation",
            score=feedback[0],
            state=feedback[1],
            confidence=feedback[2],
            rationale=feedback[3],
            evidence_ids=feedback_ids,
        )
    )

    goal_ids = _graph_evidence(graph, "goal", "loop", "termination", "replans")
    if not goal_ids:
        goal_ids = _evidence(
            ledger=ledger,
            artifacts=artifacts,
            commit_sha=commit_sha,
            claim_key="score.goal_directed_loop",
            prefixes=("trace.goal", "trace.loop", "trace.termination"),
            message="Goal-directed loop evidence was not found.",
        )
    has_goal = graph.has_node_kind("goal")
    has_loop = graph.has_node_kind("loop")
    has_termination = graph.has_node_kind("termination")
    if has_goal and has_loop and has_termination and has_replan:
        goal = (9.0, "confirmed", "high", "Goal, loop, termination, and replanning candidates are connected in the trace.")
    elif has_loop and has_termination:
        goal = (5.0, "confirmed", "medium", "Loop and termination are visible, but explicit goal-directed adaptation is incomplete.")
    elif facts.get("cap_call_graph") and _complete_coverage(facts, "trace_coverage"):
        goal = (0.0, "negative", "medium", "No complete goal-directed loop was found.")
    else:
        goal = (None, "unknown", "unknown", "Goal-loop coverage is incomplete.")
    items.append(
        _item(
            key="goal_directed_loop",
            score=goal[0],
            state=goal[1],
            confidence=goal[2],
            rationale=goal[3],
            evidence_ids=goal_ids,
        )
    )

    verification = facts.get("verification")
    verification_ids = _evidence(
        ledger=ledger,
        artifacts=artifacts,
        commit_sha=commit_sha,
        claim_key="score.verification",
        prefixes=("verification.",),
        message="Verification evidence was not found in the bounded scan.",
    )
    if isinstance(verification, VerificationFacts):
        test_count = len(verification.test_files)
        ci_count = len(verification.ci_files)
        assertions = verification.assertion_hits
        if test_count and ci_count and assertions:
            verification_score = (9.5, "confirmed", "high", "Tests, CI, and assertions are all present in the bounded scan.")
        elif test_count and (ci_count or assertions):
            verification_score = (7.0, "confirmed", "medium", "Tests plus one additional verification signal are present.")
        elif test_count or ci_count or assertions:
            verification_score = (4.0, "confirmed", "low", "A limited verification signal is present.")
        elif facts.get("cap_verification") and _complete_coverage(facts):
            verification_score = (0.0, "negative", "medium", "No test, CI, or assertion candidate was found.")
        else:
            verification_score = (None, "unknown", "unknown", "Verification coverage is incomplete.")
    else:
        verification_score = (None, "unknown", "unknown", "Verification inspection was not completed.")
    items.append(
        _item(
            key="verification",
            score=verification_score[0],
            state=verification_score[1],
            confidence=verification_score[2],
            rationale=verification_score[3],
            evidence_ids=verification_ids,
        )
    )

    agent_tool_ids = _evidence(
        ledger=ledger,
        artifacts=artifacts,
        commit_sha=commit_sha,
        claim_key="score.agent_tooling",
        prefixes=("candidate.tooling", "trace.dispatch", "trace.action_selector"),
        message="Agent tooling evidence was not found.",
    )
    if tooling_hits and has_dispatch and has_control:
        agent_tooling = (8.0, "confirmed", "high", "Tool candidates and a model-controlled dispatcher are both traced.")
    elif tooling_hits:
        agent_tooling = (4.0, "confirmed", "low", "A tool surface exists, but agent-controlled dispatch is not established.")
    elif facts.get("cap_tooling") and _complete_coverage(facts):
        agent_tooling = (0.0, "negative", "medium", "No runtime tool surface was found in the bounded scan.")
    else:
        agent_tooling = (None, "unknown", "unknown", "Agent tooling coverage is incomplete.")
    items.append(
        _item(
            key="agent_tooling",
            score=agent_tooling[0],
            state=agent_tooling[1],
            confidence=agent_tooling[2],
            rationale=agent_tooling[3],
            evidence_ids=agent_tool_ids,
        )
    )
    return items
