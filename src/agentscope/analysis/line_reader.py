"""line-numbered read-only file access。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentscope.acquisition.git_snapshot import Snapshot, SnapshotLimits
from agentscope.domain.evidence import EvidenceError, normalize_relative_path


class ReadFileError(ValueError):
    """指定されたファイルを安全に読めない。"""


@dataclass(frozen=True)
class LineExcerpt:
    path: str
    start_line: int
    end_line: int
    text: str

    def numbered(self) -> str:
        lines = self.text.splitlines()
        return "\n".join(
            f"{line_no}: {line}" for line_no, line in enumerate(lines, self.start_line)
        )


def _resolve(snapshot: Snapshot, relative_path: str) -> tuple[str, Path]:
    normalized = normalize_relative_path(relative_path)
    root = snapshot.root.resolve()
    candidate = (root / normalized).resolve()
    if candidate != root and root not in candidate.parents:
        raise ReadFileError("path escapes snapshot")
    if not candidate.exists() or not candidate.is_file():
        raise ReadFileError(f"file not found: {normalized}")
    if candidate.is_symlink():
        raise ReadFileError("symlinks are not readable")
    return normalized, candidate


def read_lines(
    snapshot: Snapshot,
    relative_path: str,
    start_line: int = 1,
    end_line: int | None = None,
    *,
    limits: SnapshotLimits | None = None,
) -> LineExcerpt:
    limits = limits or SnapshotLimits()
    if start_line < 1:
        raise ReadFileError("start_line must be >= 1")
    normalized, path = _resolve(snapshot, relative_path)
    if path.stat().st_size > limits.max_file_bytes:
        raise ReadFileError("file exceeds read limit")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReadFileError(f"file is not readable text: {normalized}") from exc
    lines = content.splitlines()
    if len(lines) > limits.max_lines:
        raise ReadFileError("file exceeds line limit")
    if end_line is None:
        end_line = min(len(lines), start_line + 119)
    if end_line < start_line:
        raise ReadFileError("end_line must be >= start_line")
    if end_line - start_line + 1 > 200:
        raise ReadFileError("read range is too large")
    selected = lines[start_line - 1 : end_line]
    actual_end = start_line + len(selected) - 1
    if not selected:
        raise ReadFileError("requested range is empty")
    return LineExcerpt(
        path=normalized,
        start_line=start_line,
        end_line=actual_end,
        text="\n".join(selected),
    )

