"""監査run artifactの安全な書き込み。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any

from agentscope.domain.evidence import normalize_relative_path


@dataclass
class ArtifactStore:
    root: Path

    @classmethod
    def create(cls, base_dir: Path, run_id: str) -> "ArtifactStore":
        base_dir.mkdir(parents=True, exist_ok=True)
        root = base_dir / run_id
        root.mkdir(parents=True, exist_ok=False)
        (root / "provenance").mkdir()
        return cls(root=root)

    def path(self, relative_path: str) -> Path:
        normalized = normalize_relative_path(relative_path)
        candidate = (self.root / normalized).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("artifact path escapes run directory")
        return candidate

    def write_text(self, relative_path: str, content: str) -> Path:
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
        return destination

    def write_json(self, relative_path: str, value: Any) -> Path:
        return self.write_text(
            relative_path,
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def write_jsonl(self, relative_path: str, rows: list[dict[str, Any]]) -> Path:
        content = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        )
        return self.write_text(relative_path, content)


def default_artifact_base() -> Path:
    """ユーザーの既存データを壊さないAgentScope専用保存先。"""

    if Path.home().joinpath("Library").is_dir():
        return Path.home() / "Library" / "Application Support" / "AgentScope" / "runs"
    return Path.home() / ".local" / "share" / "agentscope" / "runs"


def temporary_artifact_store() -> ArtifactStore:
    base = Path(tempfile.mkdtemp(prefix="agentscope-runs-"))
    return ArtifactStore.create(base, "run")
