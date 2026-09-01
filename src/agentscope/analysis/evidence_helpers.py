"""detector hitを行単位Evidenceへ変換する小さな共通部品。"""

from __future__ import annotations

from agentscope.domain.evidence import Evidence, EvidenceLedger
from agentscope.analysis.search import SearchHit


def add_hit_evidence(
    ledger: EvidenceLedger,
    hit: SearchHit,
    *,
    claim_key: str,
    commit_sha: str,
    reason: str,
    confidence: str = "medium",
    source_kind: str = "repository",
) -> Evidence:
    return ledger.add(
        claim_key=claim_key,
        source_kind=source_kind,
        file=hit.path,
        start_line=hit.line,
        end_line=hit.line,
        excerpt=hit.text,
        commit_sha=commit_sha,
        reason=reason,
        confidence=confidence,
    )
