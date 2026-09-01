"""repositoryの安全なファイルinventory。"""

from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
import os

from agentscope.acquisition.git_snapshot import Snapshot, SnapshotLimits
from agentscope.domain.evidence import normalize_relative_path


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    language: str | None
    readable: bool = True
    skip_reason: str | None = None


@dataclass
class Inventory:
    files: list[FileRecord]
    skipped: list[FileRecord]
    total_bytes: int
    coverage: str

    def paths(self) -> list[str]:
        return [item.path for item in self.files]

    def to_dict(self) -> dict[str, object]:
        return {
            "files": [item.__dict__ for item in self.files],
            "skipped": [item.__dict__ for item in self.skipped],
            "total_bytes": self.total_bytes,
            "coverage": self.coverage,
        }


_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
}


def language_for(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return _LANGUAGES.get(suffix)


def _is_binary(path: Path, sample_size: int = 4096) -> bool:
    try:
        sample = path.read_bytes()[:sample_size]
    except OSError:
        return True
    return b"\x00" in sample or (
        bool(sample) and sample.count(b"\n") == 0 and not mimetypes.guess_type(path.name)[0]
    )


def build_inventory(snapshot: Snapshot, limits: SnapshotLimits | None = None) -> Inventory:
    limits = limits or SnapshotLimits()
    files: list[FileRecord] = []
    skipped: list[FileRecord] = []
    total_bytes = 0
    root = snapshot.root.resolve()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            name for name in dirnames if name != ".git" and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            relative = path.relative_to(root).as_posix()
            try:
                relative = normalize_relative_path(relative)
                stat = path.lstat()
            except (OSError, ValueError):
                skipped.append(
                    FileRecord(relative, 0, language_for(relative), False, "unreadable path")
                )
                continue
            if path.is_symlink():
                skipped.append(
                    FileRecord(relative, stat.st_size, language_for(relative), False, "symlink")
                )
                continue
            if len(files) + len(skipped) >= limits.max_files:
                skipped.append(
                    FileRecord(relative, stat.st_size, language_for(relative), False, "file limit")
                )
                continue
            if stat.st_size > limits.max_file_bytes:
                skipped.append(
                    FileRecord(relative, stat.st_size, language_for(relative), False, "file too large")
                )
                continue
            if total_bytes + stat.st_size > limits.max_total_bytes:
                skipped.append(
                    FileRecord(relative, stat.st_size, language_for(relative), False, "total size limit")
                )
                continue
            if _is_binary(path):
                skipped.append(
                    FileRecord(relative, stat.st_size, language_for(relative), False, "binary")
                )
                continue
            files.append(FileRecord(relative, stat.st_size, language_for(relative)))
            total_bytes += stat.st_size
    coverage = "full" if not skipped else "partial"
    return Inventory(files=files, skipped=skipped, total_bytes=total_bytes, coverage=coverage)

