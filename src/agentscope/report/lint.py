"""reportをfail-closedで検証する。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentscope.domain.evidence import (
    EVIDENCE_CONFIDENCES,
    EVIDENCE_SOURCE_KINDS,
    Evidence,
    EvidenceError,
    normalize_relative_path,
)


class ReportLintError(ValueError):
    """report contractに違反。"""


REQUIRED_SCORE_KEYS = {
    "originality",
    "agenticity",
    "dynamic_tool_selection",
    "feedback_adaptation",
    "goal_directed_loop",
    "verification",
    "agent_tooling",
}
REQUIRED_CLASSIFICATION_KEYS = {
    "ai_assisted_development",
    "agentic_runtime",
    "mcp_tooling",
    "formal_github_fork",
    "derived_concept",
}
_INTERNAL_MARKERS = re.compile(r"ROOT_COUNTRY|FROM\(.*未確定|<UNRESOLVED>|\bUNRESOLVED\b")


def _resolve_evidence_path(
    file: str,
    *,
    snapshot_root: Path,
    artifact_root: Path,
) -> Path:
    try:
        normalized = normalize_relative_path(file)
    except EvidenceError as exc:
        raise ReportLintError(f"invalid evidence path: {file}") from exc
    base = artifact_root if normalized.startswith("provenance/") else snapshot_root
    candidate = (base / normalized).resolve()
    base_resolved = base.resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise ReportLintError(f"evidence path escapes root: {file}")
    return candidate


def _check_evidence(
    item: dict[str, Any],
    *,
    snapshot_root: Path,
    artifact_root: Path,
    commit_sha: str,
) -> None:
    required = {
        "id",
        "claim_key",
        "source_kind",
        "file",
        "start_line",
        "end_line",
        "display_ref",
        "excerpt",
        "excerpt_sha256",
        "commit_sha",
        "reason",
        "confidence",
    }
    if set(item) != required:
        raise ReportLintError(f"evidence keys do not match: {item.get('id')}")
    if item["commit_sha"] != commit_sha:
        raise ReportLintError(f"evidence commit mismatch: {item['id']}")
    if not isinstance(item["id"], str) or not re.fullmatch(r"e[1-9][0-9]*", item["id"]):
        raise ReportLintError(f"invalid evidence id: {item['id']}")
    if item["source_kind"] not in EVIDENCE_SOURCE_KINDS:
        raise ReportLintError(f"invalid evidence source kind: {item['id']}")
    if (
        not isinstance(item["claim_key"], str)
        or not item["claim_key"]
        or not isinstance(item["file"], str)
        or not isinstance(item["excerpt"], str)
        or not isinstance(item["reason"], str)
        or not item["reason"]
        or item["confidence"] not in EVIDENCE_CONFIDENCES
    ):
        raise ReportLintError(f"invalid evidence field: {item['id']}")
    if not isinstance(item["start_line"], int) or not isinstance(item["end_line"], int):
        raise ReportLintError(f"invalid line type: {item['id']}")
    if item["start_line"] < 1 or item["end_line"] < item["start_line"]:
        raise ReportLintError(f"invalid line range: {item['id']}")
    expected_ref = f"{item['file']}:{item['start_line']}"
    if item["display_ref"] != expected_ref:
        raise ReportLintError(f"invalid display ref: {item['id']}")
    if (
        not isinstance(item["excerpt_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", item["excerpt_sha256"])
        or Evidence.hash_excerpt(item["excerpt"]) != item["excerpt_sha256"]
    ):
        raise ReportLintError(f"excerpt hash mismatch: {item['id']}")
    path = _resolve_evidence_path(
        item["file"],
        snapshot_root=snapshot_root,
        artifact_root=artifact_root,
    )
    if not path.is_file():
        raise ReportLintError(f"evidence file not found: {item['file']}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportLintError(f"evidence file is unreadable: {item['file']}") from exc
    selected = lines[item["start_line"] - 1 : item["end_line"]]
    if len(selected) != item["end_line"] - item["start_line"] + 1:
        raise ReportLintError(f"evidence line range is outside file: {item['id']}")
    if "\n".join(selected) != item["excerpt"]:
        raise ReportLintError(f"evidence excerpt does not match: {item['id']}")
    if _INTERNAL_MARKERS.search(item["excerpt"]):
        raise ReportLintError(f"internal marker leaked into evidence: {item['id']}")


def lint_report(
    report: dict[str, Any],
    *,
    snapshot_root: Path,
    artifact_root: Path,
) -> None:
    for key in ("schema_version", "subject", "runtime", "scores", "classifications", "evidence", "unknowns", "action_trace_ref"):
        if key not in report:
            raise ReportLintError(f"missing report key: {key}")
    if report["schema_version"] != "0.1":
        raise ReportLintError("unsupported report schema_version")
    subject = report["subject"]
    if not isinstance(subject, dict):
        raise ReportLintError("subject must be an object")
    commit_sha = subject.get("commit_sha") if isinstance(subject, dict) else None
    if not isinstance(commit_sha, str) or not commit_sha:
        raise ReportLintError("subject.commit_sha is required")
    if not isinstance(report["runtime"], dict):
        raise ReportLintError("runtime must be an object")
    if not isinstance(report["action_trace_ref"], str) or not report["action_trace_ref"]:
        raise ReportLintError("action_trace_ref is required")
    if not isinstance(report["unknowns"], list) or not all(
        isinstance(item, str) for item in report["unknowns"]
    ):
        raise ReportLintError("unknowns must be an array of strings")
    evidence_items = report["evidence"]
    if not isinstance(evidence_items, list):
        raise ReportLintError("evidence must be an array")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for item in evidence_items:
        if not isinstance(item, dict):
            raise ReportLintError("evidence item must be an object")
        _check_evidence(
            item,
            snapshot_root=snapshot_root,
            artifact_root=artifact_root,
            commit_sha=commit_sha,
        )
        if item["id"] in evidence_by_id:
            raise ReportLintError(f"duplicate evidence id: {item['id']}")
        evidence_by_id[item["id"]] = item

    scores = report["scores"]
    if not isinstance(scores, list):
        raise ReportLintError("scores must be an array")
    score_keys = {
        item.get("key")
        for item in scores
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    if score_keys != REQUIRED_SCORE_KEYS:
        raise ReportLintError(f"score keys mismatch: {score_keys}")
    for item in scores:
        if not isinstance(item, dict):
            raise ReportLintError("score item must be an object")
        if not isinstance(item.get("key"), str) or not isinstance(item.get("label"), str):
            raise ReportLintError("score key and label are required")
        score = item.get("score")
        if score is not None and (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 0.0 <= score <= 10.0
        ):
            raise ReportLintError(f"score out of range: {item.get('key')}")
        if item.get("state") not in {"confirmed", "negative", "unknown"}:
            raise ReportLintError(f"invalid score state: {item.get('key')}")
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or not ids or not all(
            isinstance(evidence_id, str) for evidence_id in ids
        ):
            raise ReportLintError(f"score has no evidence: {item.get('key')}")
        if any(evidence_id not in evidence_by_id for evidence_id in ids):
            raise ReportLintError(f"score has unknown evidence: {item.get('key')}")
        if item.get("state") == "unknown" and score is not None:
            raise ReportLintError(f"unknown score must be null: {item.get('key')}")

    classifications = report["classifications"]
    if not isinstance(classifications, dict):
        raise ReportLintError("classifications must be an object")
    if set(classifications) != REQUIRED_CLASSIFICATION_KEYS:
        raise ReportLintError("classification keys mismatch")
    for key, item in classifications.items():
        if not isinstance(item, dict) or item.get("value") not in {"yes", "no", "unknown"}:
            raise ReportLintError(f"invalid classification: {key}")
        if item.get("confidence") not in EVIDENCE_CONFIDENCES:
            raise ReportLintError(f"invalid classification confidence: {key}")
        if not isinstance(item.get("rationale_ja"), str) or not item["rationale_ja"]:
            raise ReportLintError(f"classification rationale is required: {key}")
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or not ids or not all(
            isinstance(evidence_id, str) for evidence_id in ids
        ):
            raise ReportLintError(f"classification has no evidence: {key}")
        if any(evidence_id not in evidence_by_id for evidence_id in ids):
            raise ReportLintError(f"classification has unknown evidence: {key}")
