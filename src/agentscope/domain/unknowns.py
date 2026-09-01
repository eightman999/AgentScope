"""評価全体をUnknownへ落とすための共有証拠処理。"""

from __future__ import annotations

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.domain.evidence import EvidenceLedger


_INTEGRITY_CLAIM = "evaluation.model_output_integrity"
_INTEGRITY_PATH = "provenance/model-output-integrity.txt"


def _single_line(value: str) -> str:
    return " ".join(str(value).split())[:500] or "unspecified model output integrity failure"


def add_model_output_integrity_evidence(
    *,
    ledger: EvidenceLedger,
    artifacts: ArtifactStore,
    commit_sha: str,
    reason: str,
) -> str:
    """model出力の整合性違反をmaterializeし、検証済みevidence IDを返す。"""

    message = f"evaluation=unknown; reason={_single_line(reason)}"
    destination = artifacts.path(_INTEGRITY_PATH)
    content = destination.read_text(encoding="utf-8") if destination.exists() else ""
    line_no = len(content.splitlines()) + 1
    artifacts.write_text(_INTEGRITY_PATH, content + message + "\n")
    evidence = ledger.add(
        claim_key=_INTEGRITY_CLAIM,
        source_kind="derived_manifest",
        file=_INTEGRITY_PATH,
        start_line=line_no,
        end_line=line_no,
        excerpt=message,
        commit_sha=commit_sha,
        reason="Model output integrity could not be established; evaluation is Unknown.",
        confidence="unknown",
    )
    return evidence.id


def model_output_integrity_evidence_ids(
    *,
    ledger: EvidenceLedger,
    artifacts: ArtifactStore,
    commit_sha: str,
    reason: str,
) -> list[str]:
    """既存の整合性evidenceを再利用し、無ければ1件materializeする。"""

    existing = [item.id for item in ledger.all() if item.claim_key == _INTEGRITY_CLAIM]
    if existing:
        return [existing[-1]]
    return [
        add_model_output_integrity_evidence(
            ledger=ledger,
            artifacts=artifacts,
            commit_sha=commit_sha,
            reason=reason,
        )
    ]
