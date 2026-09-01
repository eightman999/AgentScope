"""検証可能な行単位の証拠台帳。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Iterable


class EvidenceError(ValueError):
    """Evidenceの構造または参照が不正。"""


def normalize_relative_path(value: str) -> str:
    """絶対pathとsnapshot外への脱出を拒否してPOSIX相対pathを返す。"""

    if not isinstance(value, str) or not value:
        raise EvidenceError("file path must be a non-empty string")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~"):
        raise EvidenceError("absolute paths are not allowed")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise EvidenceError("path traversal is not allowed")
    if not parts:
        raise EvidenceError("empty relative path")
    return "/".join(parts)


@dataclass(frozen=True)
class Evidence:
    """対象行またはmaterialized artifactの検証済み引用。"""

    id: str
    claim_key: str
    source_kind: str
    file: str
    start_line: int
    end_line: int
    display_ref: str
    excerpt: str
    excerpt_sha256: str
    commit_sha: str
    reason: str
    confidence: str = "medium"

    @staticmethod
    def hash_excerpt(excerpt: str) -> str:
        return hashlib.sha256(excerpt.encode("utf-8")).hexdigest()

    @classmethod
    def create(
        cls,
        *,
        evidence_id: str,
        claim_key: str,
        source_kind: str,
        file: str,
        start_line: int,
        end_line: int,
        excerpt: str,
        commit_sha: str,
        reason: str,
        confidence: str = "medium",
    ) -> "Evidence":
        normalized = normalize_relative_path(file)
        if start_line < 1 or end_line < start_line:
            raise EvidenceError("invalid line range")
        if not claim_key or not reason:
            raise EvidenceError("claim_key and reason are required")
        if confidence not in {"high", "medium", "low", "unknown"}:
            raise EvidenceError("invalid evidence confidence")
        return cls(
            id=evidence_id,
            claim_key=claim_key,
            source_kind=source_kind,
            file=normalized,
            start_line=start_line,
            end_line=end_line,
            display_ref=f"{normalized}:{start_line}",
            excerpt=excerpt,
            excerpt_sha256=cls.hash_excerpt(excerpt),
            commit_sha=commit_sha,
            reason=reason,
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class EvidenceLedger:
    """run内で採番されたEvidenceを重複なく保持する。"""

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}
        self._next_id = 1

    def add(
        self,
        *,
        claim_key: str,
        source_kind: str,
        file: str,
        start_line: int,
        end_line: int,
        excerpt: str,
        commit_sha: str,
        reason: str,
        confidence: str = "medium",
    ) -> Evidence:
        evidence_id = f"e{self._next_id}"
        self._next_id += 1
        evidence = Evidence.create(
            evidence_id=evidence_id,
            claim_key=claim_key,
            source_kind=source_kind,
            file=file,
            start_line=start_line,
            end_line=end_line,
            excerpt=excerpt,
            commit_sha=commit_sha,
            reason=reason,
            confidence=confidence,
        )
        self._items[evidence.id] = evidence
        return evidence

    def add_existing(self, evidence: Evidence) -> Evidence:
        if evidence.id in self._items:
            raise EvidenceError(f"duplicate evidence id: {evidence.id}")
        self._items[evidence.id] = evidence
        suffix = evidence.id[1:]
        if suffix.isdigit():
            self._next_id = max(self._next_id, int(suffix) + 1)
        return evidence

    def get(self, evidence_id: str) -> Evidence:
        try:
            return self._items[evidence_id]
        except KeyError as exc:
            raise EvidenceError(f"unknown evidence id: {evidence_id}") from exc

    def ids(self) -> set[str]:
        return set(self._items)

    def all(self) -> list[Evidence]:
        return list(self._items.values())

    def for_claim(self, claim_key: str) -> list[Evidence]:
        return [item for item in self._items.values() if item.claim_key == claim_key]

    def matching(self, prefixes: Iterable[str]) -> list[Evidence]:
        prefix_tuple = tuple(prefixes)
        return [
            item
            for item in self._items.values()
            if item.claim_key.startswith(prefix_tuple)
        ]

