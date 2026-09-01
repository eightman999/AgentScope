"""GitHub public metadataを取得し、取得失敗をUnknownへ伝播させる。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.github_url import GitHubRepoRef


@dataclass(frozen=True)
class MetadataResult:
    available: bool
    status: int | None
    data: dict[str, Any] | None
    artifact_path: str | None
    error: str | None = None


def _parent_full_name(parent: object) -> object:
    if isinstance(parent, dict):
        return parent.get("full_name")
    return None


class GitHubMetadataSource:
    def __init__(
        self,
        *,
        timeout: int = 20,
        max_response_bytes: int = 2_000_000,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or timeout < 1
            or not isinstance(max_response_bytes, int)
            or isinstance(max_response_bytes, bool)
            or max_response_bytes < 1
        ):
            raise ValueError("metadata timeout and response limit must be positive integers")
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.opener = opener or urlopen

    def fetch_repository(
        self,
        ref: GitHubRepoRef,
        artifacts: ArtifactStore,
    ) -> MetadataResult:
        endpoint = f"https://api.github.com{ref.api_path}"
        request = Request(
            endpoint,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "AgentScope/0.1",
            },
        )
        status: int | None = None
        retrieved_at = datetime.now(timezone.utc).isoformat()
        body_sha256: str | None = None
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read()
            if not isinstance(status, int) or not 200 <= status < 300:
                raise ValueError(f"GitHub metadata returned HTTP status {status}")
            if not isinstance(body, bytes) or len(body) > self.max_response_bytes:
                raise ValueError("GitHub metadata response exceeds the read limit")
            body_sha256 = hashlib.sha256(body).hexdigest()
            raw = body.decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("GitHub repository response is not an object")
            artifacts.write_text("provenance/github-repository.json", raw + "\n")
            evidence_lines = [
                f"endpoint={endpoint}",
                f"target_url={ref.canonical_url}",
                f"http_status={status}",
                f"retrieved_at={retrieved_at}",
                f"body_sha256={body_sha256}",
                f"fork={parsed.get('fork')!r}",
                f"parent_full_name={_parent_full_name(parsed.get('parent'))!r}",
                f"html_url={parsed.get('html_url')!r}",
            ]
            artifacts.write_text(
                "provenance/github-repository-evidence.txt",
                "\n".join(evidence_lines) + "\n",
            )
            return MetadataResult(
                available=True,
                status=status,
                data=parsed,
                artifact_path="provenance/github-repository-evidence.txt",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            artifacts.write_text(
                "provenance/github-repository-error.txt",
                "\n".join(
                    [
                        f"endpoint={endpoint}",
                        f"target_url={ref.canonical_url}",
                        f"http_status={status}",
                        f"retrieved_at={retrieved_at}",
                        f"body_sha256={body_sha256}",
                        f"error={exc}",
                    ]
                )
                + "\n",
            )
            return MetadataResult(
                available=False,
                status=status,
                data=None,
                artifact_path="provenance/github-repository-error.txt",
                error=str(exc),
            )
