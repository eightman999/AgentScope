"""test・CI・assertion候補を調べる。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.git_snapshot import Snapshot
from agentscope.analysis.evidence_helpers import add_hit_evidence
from agentscope.analysis.inventory import Inventory
from agentscope.analysis.search import SearchHit, search_code
from agentscope.domain.evidence import EvidenceLedger


@dataclass
class VerificationFacts:
    test_files: list[str] = field(default_factory=list)
    ci_files: list[str] = field(default_factory=list)
    assertion_hits: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    coverage: str = "partial"


def _first_line(snapshot: Snapshot, relative_path: str) -> str | None:
    try:
        lines = (snapshot.root / Path(relative_path)).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return lines[0] if lines else None


def inspect_tests(
    snapshot: Snapshot,
    inventory: Inventory,
    ledger: EvidenceLedger,
    *,
    commit_sha: str,
    artifacts: ArtifactStore | None = None,
) -> VerificationFacts:
    facts = VerificationFacts(coverage=inventory.coverage)
    for record in inventory.files:
        lower = record.path.lower()
        if (
            "test" in lower
            or lower.startswith("spec/")
            or lower.endswith("_spec.py")
            or lower.endswith(".spec.ts")
            or lower.endswith(".test.ts")
        ):
            facts.test_files.append(record.path)
            first_line = _first_line(snapshot, record.path)
            if first_line is not None:
                evidence = add_hit_evidence(
                    ledger,
                    SearchHit(record.path, 1, first_line),
                    claim_key="verification.tests",
                    commit_sha=commit_sha,
                    reason="A test-like file is present in the repository inventory.",
                    confidence="medium",
                )
                facts.evidence_ids.append(evidence.id)
        if lower.startswith(".github/workflows/") or lower in {
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            "circle.yml",
        }:
            facts.ci_files.append(record.path)
            first_line = _first_line(snapshot, record.path)
            if first_line is not None:
                evidence = add_hit_evidence(
                    ledger,
                    SearchHit(record.path, 1, first_line),
                    claim_key="verification.ci",
                    commit_sha=commit_sha,
                    reason="A CI workflow candidate is present.",
                    confidence="medium",
                )
                facts.evidence_ids.append(evidence.id)
    assertion_hits = search_code(
        snapshot,
        inventory,
        "assert",
        max_hits=50,
    )
    facts.assertion_hits = len(assertion_hits)
    for hit in assertion_hits[:20]:
        evidence = add_hit_evidence(
            ledger,
            hit,
            claim_key="verification.assertion",
            commit_sha=commit_sha,
            reason="An assertion or assertion-like verification candidate was found.",
            confidence="low",
        )
        facts.evidence_ids.append(evidence.id)
    if not facts.evidence_ids:
        coverage_text = (
            "No test, CI, or assertion candidate was found in the bounded inventory.\n"
        )
        if artifacts:
            artifacts.write_text("provenance/verification-coverage.txt", coverage_text)
        evidence = ledger.add(
            claim_key="verification.coverage",
            source_kind="derived_manifest",
            file="provenance/verification-coverage.txt",
            start_line=1,
            end_line=1,
            excerpt=coverage_text.rstrip(),
            commit_sha=commit_sha,
            reason="Verification coverage was inspected but no candidate was found.",
            confidence="low" if facts.coverage == "full" else "unknown",
        )
        facts.evidence_ids.append(evidence.id)
    return facts
