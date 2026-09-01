"""ベンチマークデータセットと人手アノテーションの厳格な契約。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from agentscope.acquisition.github_url import parse_github_url
from agentscope.domain.classifications import CLASSIFICATION_KEYS
from agentscope.domain.evidence import EVIDENCE_CONFIDENCES, EvidenceError, normalize_relative_path
from agentscope.domain.scoring import SCORE_KEYS


BENCHMARK_SCHEMA_VERSION = "0.1"
BENCHMARK_CATEGORIES = (
    "clearly_agentic",
    "llm_non_agent",
    "mcp_tooling_only",
    "ai_assisted_only",
    "hard_case",
)
HUMAN_LABEL_VALUES = {"yes", "no", "unknown", "ambiguous"}
ANNOTATION_STATUSES = {"pending", "draft", "adjudicated"}
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


class BenchmarkSchemaError(ValueError):
    """ベンチマークJSONLが契約に適合しない。"""


def _object(value: object, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkSchemaError(f"{context} must be an object")
    return value


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkSchemaError(f"{field} must be a non-empty string")
    return value


def _strict_keys(value: dict[str, Any], allowed: set[str], *, context: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise BenchmarkSchemaError(
            f"{context} contains unknown keys: {sorted(extra)}"
        )


@dataclass(frozen=True)
class HumanEvidence:
    """人手ラベルを支える固定commit上の行単位証拠。"""

    source_kind: str
    file: str
    start_line: int
    end_line: int
    excerpt: str
    reason: str
    commit_sha: str

    @classmethod
    def from_dict(cls, raw_value: object, *, context: str) -> "HumanEvidence":
        raw = _object(raw_value, context=context)
        _strict_keys(
            raw,
            {
                "source_kind",
                "file",
                "start_line",
                "end_line",
                "excerpt",
                "reason",
                "commit_sha",
            },
            context=context,
        )
        source_kind = _required_string(raw.get("source_kind"), field=f"{context}.source_kind")
        if source_kind not in {"repository", "git", "github_api", "derived_manifest"}:
            raise BenchmarkSchemaError(f"{context}.source_kind is not supported")
        try:
            file = normalize_relative_path(
                _required_string(raw.get("file"), field=f"{context}.file")
            )
        except EvidenceError as exc:
            raise BenchmarkSchemaError(f"{context}.file is not a safe relative path") from exc
        start_line = raw.get("start_line")
        end_line = raw.get("end_line")
        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or start_line < 1
            or end_line < start_line
        ):
            raise BenchmarkSchemaError(f"{context} has an invalid line range")
        excerpt = _required_string(raw.get("excerpt"), field=f"{context}.excerpt")
        reason = _required_string(raw.get("reason"), field=f"{context}.reason")
        commit_sha = _required_string(raw.get("commit_sha"), field=f"{context}.commit_sha")
        if not _SHA_RE.fullmatch(commit_sha):
            raise BenchmarkSchemaError(f"{context}.commit_sha must be a 40-character SHA")
        return cls(
            source_kind=source_kind,
            file=file,
            start_line=start_line,
            end_line=end_line,
            excerpt=excerpt,
            reason=reason,
            commit_sha=commit_sha.lower(),
        )

    @property
    def display_ref(self) -> str:
        return f"{self.file}:{self.start_line}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "excerpt": self.excerpt,
            "reason": self.reason,
            "commit_sha": self.commit_sha,
        }


@dataclass(frozen=True)
class HumanLabel:
    value: str
    confidence: str
    rationale: str
    evidence: tuple[HumanEvidence, ...]

    @classmethod
    def from_dict(cls, raw_value: object, *, context: str) -> "HumanLabel":
        raw = _object(raw_value, context=context)
        _strict_keys(raw, {"value", "confidence", "rationale", "evidence"}, context=context)
        value = _required_string(raw.get("value"), field=f"{context}.value")
        if value not in HUMAN_LABEL_VALUES:
            raise BenchmarkSchemaError(f"{context}.value is not a supported human label")
        confidence = _required_string(raw.get("confidence"), field=f"{context}.confidence")
        if confidence not in EVIDENCE_CONFIDENCES:
            raise BenchmarkSchemaError(f"{context}.confidence is not supported")
        rationale = _required_string(raw.get("rationale"), field=f"{context}.rationale")
        raw_evidence = raw.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise BenchmarkSchemaError(f"{context}.evidence must contain at least one item")
        evidence = tuple(
            HumanEvidence.from_dict(item, context=f"{context}.evidence[{index}]")
            for index, item in enumerate(raw_evidence)
        )
        return cls(
            value=value,
            confidence=confidence,
            rationale=rationale,
            evidence=evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    url: str
    commit_sha: str
    category: str
    annotation_status: str
    human_labels: dict[str, HumanLabel]
    human_scores: dict[str, float]
    annotation: dict[str, Any]
    notes: str | None = None

    @classmethod
    def from_dict(cls, raw_value: object, *, context: str = "case") -> "BenchmarkCase":
        raw = _object(raw_value, context=context)
        _strict_keys(
            raw,
            {
                "id",
                "url",
                "commit_sha",
                "category",
                "annotation_status",
                "human_labels",
                "human_scores",
                "annotation",
                "notes",
            },
            context=context,
        )
        case_id = _required_string(raw.get("id"), field=f"{context}.id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,99}", case_id):
            raise BenchmarkSchemaError(
                f"{context}.id must be a lowercase benchmark slug (2-100 chars)"
            )
        url = _required_string(raw.get("url"), field=f"{context}.url")
        try:
            ref = parse_github_url(url)
        except (TypeError, ValueError) as exc:
            raise BenchmarkSchemaError(f"{context}.url is not a public GitHub repository URL") from exc
        commit_sha = _required_string(raw.get("commit_sha"), field=f"{context}.commit_sha")
        if not _SHA_RE.fullmatch(commit_sha):
            raise BenchmarkSchemaError(f"{context}.commit_sha must be a 40-character SHA")
        category = _required_string(raw.get("category"), field=f"{context}.category")
        if category not in BENCHMARK_CATEGORIES:
            raise BenchmarkSchemaError(f"{context}.category is not supported")
        annotation_status = _required_string(
            raw.get("annotation_status"), field=f"{context}.annotation_status"
        )
        if annotation_status not in ANNOTATION_STATUSES:
            raise BenchmarkSchemaError(f"{context}.annotation_status is not supported")

        raw_labels = raw.get("human_labels", {})
        raw_labels = _object(raw_labels, context=f"{context}.human_labels")
        unknown_labels = set(raw_labels) - set(CLASSIFICATION_KEYS)
        if unknown_labels:
            raise BenchmarkSchemaError(
                f"{context}.human_labels contains unknown axes: {sorted(unknown_labels)}"
            )
        human_labels = {
            key: HumanLabel.from_dict(value, context=f"{context}.human_labels.{key}")
            for key, value in raw_labels.items()
        }
        for key, label in human_labels.items():
            for evidence in label.evidence:
                if evidence.commit_sha != commit_sha.lower():
                    raise BenchmarkSchemaError(
                        f"{context}.human_labels.{key} evidence commit does not match case commit"
                    )
        if annotation_status == "pending" and human_labels:
            raise BenchmarkSchemaError(
                f"{context}.pending case cannot contain human_labels"
            )

        raw_scores = raw.get("human_scores", {})
        raw_scores = _object(raw_scores, context=f"{context}.human_scores")
        unknown_scores = set(raw_scores) - set(SCORE_KEYS)
        if unknown_scores:
            raise BenchmarkSchemaError(
                f"{context}.human_scores contains unknown axes: {sorted(unknown_scores)}"
            )
        human_scores: dict[str, float] = {}
        for key, value in raw_scores.items():
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0.0 <= float(value) <= 10.0
            ):
                raise BenchmarkSchemaError(f"{context}.human_scores.{key} must be between 0 and 10")
            human_scores[key] = float(value)

        annotation = raw.get("annotation", {})
        annotation = _object(annotation, context=f"{context}.annotation")
        _strict_keys(
            annotation,
            {"annotator", "adjudicator", "annotated_at", "protocol_version", "agreement"},
            context=f"{context}.annotation",
        )
        if human_labels and not isinstance(annotation.get("annotator"), str):
            raise BenchmarkSchemaError(f"{context}.annotation.annotator is required for labels")
        notes = raw.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise BenchmarkSchemaError(f"{context}.notes must be a string when present")
        return cls(
            id=case_id,
            url=ref.canonical_url,
            commit_sha=commit_sha.lower(),
            category=category,
            annotation_status=annotation_status,
            human_labels=human_labels,
            human_scores=human_scores,
            annotation=dict(annotation),
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "commit_sha": self.commit_sha,
            "category": self.category,
            "annotation_status": self.annotation_status,
            "human_labels": {
                key: value.to_dict() for key, value in self.human_labels.items()
            },
            "human_scores": dict(self.human_scores),
            "annotation": dict(self.annotation),
            **({"notes": self.notes} if self.notes is not None else {}),
        }


def load_dataset(path: Path) -> list[BenchmarkCase]:
    """JSONLを読み込み、重複IDと全スキーマ違反をfail-closedで拒否する。"""

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchmarkSchemaError(f"dataset could not be read: {path}") from exc
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkSchemaError(
                f"dataset line {line_number} is not valid JSON: {exc.msg}"
            ) from exc
        case = BenchmarkCase.from_dict(raw, context=f"dataset line {line_number}")
        if case.id in seen:
            raise BenchmarkSchemaError(f"duplicate dataset case id: {case.id}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise BenchmarkSchemaError("dataset must contain at least one case")
    return cases


def dataset_sha256(path: Path) -> str:
    """データセットのバイト列digest。行順・空白変更も検出する。"""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def category_counts(cases: Iterable[BenchmarkCase]) -> dict[str, int]:
    counts = {category: 0 for category in BENCHMARK_CATEGORIES}
    for case in cases:
        counts[case.category] += 1
    return counts
