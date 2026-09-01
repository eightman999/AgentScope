"""5種類のYes/No/Unknown判定。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.analysis.provenance import ProvenanceFacts
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph
from agentscope.domain.scoring import _coverage_evidence


CLASSIFICATION_KEYS = (
    "ai_assisted_development",
    "agentic_runtime",
    "mcp_tooling",
    "formal_github_fork",
    "derived_concept",
)


@dataclass(frozen=True)
class Classification:
    key: str
    value: str
    confidence: str
    rationale_ja: str
    evidence_ids: list[str]
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ids(
    ledger: EvidenceLedger,
    artifacts: ArtifactStore,
    commit_sha: str,
    prefixes: tuple[str, ...],
    *,
    key: str,
    message: str,
) -> list[str]:
    result = [
        item.id
        for item in ledger.all()
        if item.claim_key.startswith(prefixes)
    ]
    if result:
        return list(dict.fromkeys(result[:6]))
    return [
        _coverage_evidence(
            artifacts=artifacts,
            ledger=ledger,
            commit_sha=commit_sha,
            claim_key=f"classification.{key}",
            message=message,
        )
    ]


def calculate_classifications(
    *,
    graph: FactGraph,
    ledger: EvidenceLedger,
    artifacts: ArtifactStore,
    commit_sha: str,
    facts: dict[str, Any],
) -> list[Classification]:
    result: list[Classification] = []
    provenance = facts.get("provenance")
    ai_signals = facts.get("ai_signals") or []
    ai_ids = _ids(
        ledger,
        artifacts,
        commit_sha,
        (
            "provenance.ai_assisted",
            "provenance.ai_assisted.weak",
            "provenance.ai_assisted.coverage",
        ),
        key="ai_assisted_development",
        message="Bounded Git provenance was inspected but no explicit AI assistance signal was available.",
    )
    if ai_signals:
        ai = ("yes", "high", "Git provenance contains an explicit AI assistance signal.")
    elif isinstance(provenance, ProvenanceFacts) and provenance.available:
        if provenance.weak_ai_signals:
            ai = ("unknown", "low", "An AI-related contributor or commit name is only a weak signal; explicit AI assistance was not established.")
        else:
            ai = ("unknown", "low", "No explicit AI signal was found in the bounded Git history; contributor names alone are not proof.")
    else:
        ai = ("unknown", "unknown", "Git provenance was unavailable or incomplete.")
    result.append(Classification("ai_assisted_development", ai[0], ai[1], ai[2], ai_ids))

    has_agent_path = (
        graph.has_node_kind("model_call")
        and graph.has_edge_kind("controls")
        and graph.has_edge_kind("dispatches")
        and graph.has_edge_kind("observes")
        and graph.has_edge_kind("replans")
    )
    agent_ids = list(
        dict.fromkeys(
            graph.edge_evidence("controls", "dispatches", "observes", "replans")
            + graph.node_evidence("model_call")
        )
    )
    if not agent_ids:
        agent_ids = _ids(
            ledger,
            artifacts,
            commit_sha,
            ("trace.",),
            key="agentic_runtime",
            message="The bounded call graph did not provide a runtime Agentic path.",
        )
    if has_agent_path:
        runtime = ("yes", "high", "A model-controlled action path reaches dispatch, observation, and replanning.")
    elif graph.has_node_kind("model_call") and facts.get("cap_call_graph"):
        runtime = ("no", "medium", "A model call was found, but the required runtime control and feedback path was not traced.")
    elif facts.get("cap_call_graph"):
        runtime = ("no", "medium", "The bounded call graph found no model-controlled runtime path.")
    else:
        runtime = ("unknown", "unknown", "Runtime call graph coverage is incomplete.")
    result.append(Classification("agentic_runtime", runtime[0], runtime[1], runtime[2], agent_ids))

    tooling_ids = _ids(
        ledger,
        artifacts,
        commit_sha,
        ("candidate.tooling", "trace.dispatch"),
        key="mcp_tooling",
        message="MCP/tooling coverage was insufficient to classify the runtime surface.",
    )
    tooling_hits = int(facts.get("tooling_hits", 0) or 0)
    if facts.get("tooling_surface") is True:
        tooling = ("yes", "medium", "A runtime tool or MCP surface candidate was found; runtime dispatch is separately scored.")
    elif facts.get("cap_tooling") and facts.get("inventory_coverage") == "full":
        tooling = ("no", "medium", "No MCP or runtime tool surface was found in the complete bounded scan.")
    elif facts.get("cap_tooling"):
        tooling = ("unknown", "low", "The tooling scan completed with partial repository coverage.")
    else:
        tooling = ("unknown", "unknown", "Tooling inspection was not completed.")
    result.append(Classification("mcp_tooling", tooling[0], tooling[1], tooling[2], tooling_ids))

    metadata = facts.get("github_metadata")
    fork_ids = _ids(
        ledger,
        artifacts,
        commit_sha,
        ("provenance.github_fork", "provenance.github_metadata"),
        key="formal_github_fork",
        message="GitHub fork metadata was unavailable.",
    )
    if metadata is not None and getattr(metadata, "available", False):
        data = getattr(metadata, "data", None) or {}
        fork = data.get("fork")
        if fork is True:
            formal = ("yes", "high", "GitHub repository metadata reports fork=true.")
        elif fork is False:
            formal = ("no", "high", "GitHub repository metadata reports fork=false.")
        else:
            formal = ("unknown", "low", "GitHub metadata did not contain a boolean fork field.")
    else:
        formal = ("unknown", "unknown", "GitHub repository metadata could not be retrieved.")
    result.append(Classification("formal_github_fork", formal[0], formal[1], formal[2], fork_ids))

    concept_ids = _ids(
        ledger,
        artifacts,
        commit_sha,
        ("provenance.derived_concept",),
        key="derived_concept",
        message="No explicit derived-concept evidence was available in the bounded scan.",
    )
    derived_hits = int(facts.get("derived_hits", 0) or 0)
    if derived_hits:
        concept = ("yes", "medium", "An explicit known-project or derived-concept reference was found.")
    elif facts.get("cap_concept_lineage") and facts.get("inventory_coverage") == "full":
        concept = ("no", "low", "No explicit known-project or derived-concept reference was found in the complete scan.")
    elif facts.get("cap_concept_lineage"):
        concept = ("unknown", "low", "The concept scan completed with partial repository coverage.")
    else:
        concept = ("unknown", "unknown", "Derived-concept inspection was not completed.")
    result.append(
        Classification(
            "derived_concept",
            concept[0],
            concept[1],
            concept[2],
            concept_ids,
            label="Karpathy/autoresearch" if derived_hits else None,
        )
    )
    return result
