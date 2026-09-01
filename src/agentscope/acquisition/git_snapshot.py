"""GitHub repositoryを固定SHAのread-only snapshotとして取得する。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

from agentscope.acquisition.github_url import GitHubRepoRef


class AcquisitionError(RuntimeError):
    """repository取得またはGit metadata取得の失敗。"""


@dataclass(frozen=True)
class Snapshot:
    root: Path
    commit_sha: str
    coverage: str = "full"


@dataclass(frozen=True)
class SnapshotLimits:
    max_files: int = 10_000
    max_file_bytes: int = 2_000_000
    max_total_bytes: int = 50_000_000
    max_lines: int = 100_000
    max_steps: int = 14


def _safe_env() -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL")
        if key in os.environ
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    return env


def run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """許可されたgit argvだけを実行する。shell=Trueは使わない。"""

    if not args or args[0] != "git":
        raise AcquisitionError("only git commands are allowed")
    allowed = {
        "clone",
        "rev-parse",
        "log",
        "remote",
        "show",
        "ls-tree",
    }
    if len(args) < 2 or args[1] not in allowed:
        raise AcquisitionError(f"git subcommand is not allowed: {args[1:]}")
    try:
        return subprocess.run(
            list(args),
            cwd=cwd,
            env=_safe_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcquisitionError(f"git command failed: {exc}") from exc


class GitSnapshotSource:
    def __init__(self, *, limits: SnapshotLimits | None = None) -> None:
        self.limits = limits or SnapshotLimits()

    def acquire(self, ref: GitHubRepoRef, destination: Path) -> Snapshot:
        if destination.exists():
            raise AcquisitionError("snapshot destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = run_git(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--no-tags",
                "--no-recurse-submodules",
                ref.clone_url,
                str(destination),
            ],
            timeout=180,
        )
        if result.returncode != 0:
            raise AcquisitionError(result.stderr.strip() or "git clone failed")
        sha_result = run_git(["git", "rev-parse", "HEAD"], cwd=destination)
        if sha_result.returncode != 0:
            raise AcquisitionError("could not resolve snapshot commit")
        sha = sha_result.stdout.strip()
        if len(sha) < 7 or any(char not in "0123456789abcdef" for char in sha.lower()):
            raise AcquisitionError("git returned an invalid commit SHA")
        return Snapshot(root=destination, commit_sha=sha, coverage="partial")


def local_snapshot(root: Path, *, commit_sha: str = "fixture-sha") -> Snapshot:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise AcquisitionError(f"snapshot root is not a directory: {root}")
    return Snapshot(root=resolved, commit_sha=commit_sha, coverage="full")


def cleanup_snapshot(snapshot: Snapshot) -> None:
    """テスト用の明示的cleanup。監査runのartifactは削除しない。"""

    if snapshot.root.name == "snapshot" and snapshot.root.exists():
        shutil.rmtree(snapshot.root)
