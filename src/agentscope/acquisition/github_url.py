"""GitHub URLの正規化と入力境界。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit


class GitHubUrlError(ValueError):
    """許可されないGitHub URL。"""


_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str
    canonical_url: str

    @property
    def clone_url(self) -> str:
        return f"{self.canonical_url}.git"

    @property
    def api_path(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"


def parse_github_url(raw_url: str) -> GitHubRepoRef:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise GitHubUrlError("GitHub repository URL is required")
    value = raw_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise GitHubUrlError("only https GitHub URLs are accepted")
    if parsed.username or parsed.password or parsed.port:
        raise GitHubUrlError("credentials and custom ports are not accepted")
    if parsed.query or parsed.fragment:
        raise GitHubUrlError("query strings and fragments are not accepted")
    if (parsed.hostname or "").lower() != "github.com":
        raise GitHubUrlError("only github.com is accepted")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise GitHubUrlError("URL must contain exactly owner/repository")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or not _PART_RE.fullmatch(owner) or not _PART_RE.fullmatch(repo):
        raise GitHubUrlError("owner and repository contain invalid characters")
    if owner in {".", ".."} or repo in {".", ".."}:
        raise GitHubUrlError("invalid owner or repository")
    return GitHubRepoRef(
        owner=owner,
        repo=repo,
        canonical_url=f"https://github.com/{owner}/{repo}",
    )
