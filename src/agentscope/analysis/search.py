"""安全なliteral/regex検索。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from agentscope.acquisition.git_snapshot import Snapshot, SnapshotLimits
from agentscope.analysis.inventory import Inventory


@dataclass(frozen=True)
class SearchHit:
    path: str
    line: int
    text: str

    @property
    def display_ref(self) -> str:
        return f"{self.path}:{self.line}"


def search_code(
    snapshot: Snapshot,
    inventory: Inventory,
    query: str,
    *,
    paths: list[str] | None = None,
    regex: bool = False,
    max_hits: int = 50,
    limits: SnapshotLimits | None = None,
) -> list[SearchHit]:
    limits = limits or SnapshotLimits()
    if not isinstance(query, str) or not query or len(query) > 500:
        raise ValueError("query must be a non-empty string up to 500 characters")
    if max_hits < 1 or max_hits > 200:
        raise ValueError("max_hits must be between 1 and 200")
    allowed_paths = set(paths) if paths else set(inventory.paths())
    pattern = re.compile(query, re.IGNORECASE) if regex else None
    hits: list[SearchHit] = []
    for record in inventory.files:
        if record.path not in allowed_paths:
            continue
        if len(hits) >= max_hits:
            break
        path = snapshot.root / Path(record.path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        if len(lines) > limits.max_lines:
            continue
        for line_no, line in enumerate(lines, 1):
            matched = bool(pattern.search(line)) if pattern else query.casefold() in line.casefold()
            if matched:
                hits.append(SearchHit(record.path, line_no, line[:1000]))
                if len(hits) >= max_hits:
                    break
    return hits

