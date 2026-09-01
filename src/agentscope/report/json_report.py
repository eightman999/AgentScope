"""domain結果をreport.jsonの形へ変換する。"""

from __future__ import annotations

from typing import Any

from agentscope.domain.classifications import Classification
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph
from agentscope.domain.scoring import ScoreItem
from agentscope.domain.state import AuditState


def build_report(
    *,
    state: AuditState,
    scores: list[ScoreItem],
    classifications: list[Classification],
    ledger: EvidenceLedger,
    graph: FactGraph,
    model_id: str,
    model_sha256: str | None,
    engine: str,
    snapshot_coverage: str,
    runtime_version: str | None = None,
    runtime_error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "subject": {
            "input_url": state.input_url,
            "canonical_url": state.canonical_url,
            "commit_sha": state.commit_sha,
            "snapshot_coverage": snapshot_coverage,
        },
        "runtime": {
            "model_id": model_id,
            "model_sha256": model_sha256,
            "engine": engine,
            "runtime_version": runtime_version,
            "steps_used": len(state.action_history),
            "termination": state.termination,
            "status": state.status,
            "error": runtime_error,
        },
        "scores": [item.to_dict() for item in scores],
        "classifications": {
            item.key: {
                "value": item.value,
                "confidence": item.confidence,
                "rationale_ja": item.rationale_ja,
                "evidence_ids": item.evidence_ids,
                **({"label": item.label} if item.label else {}),
            }
            for item in classifications
        },
        "evidence": [item.to_dict() for item in ledger.all()],
        "unknowns": list(dict.fromkeys(state.unknowns)),
        "action_trace_ref": "audit_trace.jsonl",
        "fact_graph": graph.to_dict(),
    }
