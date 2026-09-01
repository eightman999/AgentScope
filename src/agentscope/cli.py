"""AgentScope CLI。"""

from __future__ import annotations

import argparse
import sys

from agentscope.application import audit_url
from agentscope.acquisition.github_url import GitHubUrlError
from agentscope.model.provider import ModelProviderError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentscope",
        description="Evidence-first audit of agentic behavior in a GitHub repository.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="audit one public GitHub repository")
    audit.add_argument("url", help="public https://github.com/owner/repository URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "audit":
        return 2
    try:
        result = audit_url(args.url)
    except (GitHubUrlError, ModelProviderError, OSError, RuntimeError, ValueError) as exc:
        print(f"AgentScopeを開始できません: {exc}", file=sys.stderr)
        return 2
    print(result.artifacts.path("report.md").read_text(encoding="utf-8"), end="")
    print(f"\nartifact: {result.artifacts.root}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
