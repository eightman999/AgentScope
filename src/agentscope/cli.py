"""AgentScope CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from agentscope.application import audit_url
from agentscope.acquisition.github_url import GitHubUrlError
from agentscope.acquisition.git_snapshot import SnapshotLimits
from agentscope.benchmark.runner import BenchmarkRunError, run_benchmark, score_benchmark
from agentscope.benchmark.schema import BenchmarkSchemaError, category_counts, load_dataset
from agentscope.model.provider import ModelProviderError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentscope",
        description="Evidence-first audit of agentic behavior in a GitHub repository.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="audit one public GitHub repository")
    audit.add_argument("url", help="public https://github.com/owner/repository URL")
    benchmark = subparsers.add_parser(
        "benchmark",
        help="run and score a fixed-SHA repository benchmark",
    )
    benchmark_subparsers = benchmark.add_subparsers(
        dest="benchmark_command", required=True
    )
    validate = benchmark_subparsers.add_parser(
        "validate", help="validate benchmark JSONL annotations"
    )
    validate.add_argument("dataset", type=Path)
    run = benchmark_subparsers.add_parser(
        "run", help="audit benchmark cases in dataset order"
    )
    run.add_argument("dataset", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--limit", type=int)
    run.add_argument("--ids", nargs="+", metavar="CASE_ID")
    run.add_argument("--max-steps", type=int, default=14)
    run.add_argument(
        "--snapshot-base",
        type=Path,
        help="reuse fixed-SHA checkouts under <base>/<case>-<sha12>/snapshot",
    )
    run.add_argument(
        "--no-resume",
        action="store_true",
        help="rerun completed cases into a new artifact attempt",
    )
    run.add_argument("--dry-run", action="store_true")
    score = benchmark_subparsers.add_parser(
        "score", help="score saved reports without running repositories"
    )
    score.add_argument("dataset", type=Path)
    score.add_argument("--results", type=Path, required=True)
    score.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "benchmark":
        try:
            if args.benchmark_command == "validate":
                cases = load_dataset(args.dataset)
                print(
                    json.dumps(
                        {
                            "dataset": str(args.dataset),
                            "case_n": len(cases),
                            "category_counts": category_counts(cases),
                            "labeled_case_n": sum(
                                1 for case in cases if case.human_labels
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.benchmark_command == "run":
                result = run_benchmark(
                    args.dataset,
                    args.output,
                    limit=args.limit,
                    ids=args.ids,
                    resume=not args.no_resume,
                    dry_run=args.dry_run,
                    limits=SnapshotLimits(max_steps=args.max_steps),
                    snapshot_base=args.snapshot_base,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1 if result.get("failed_n", 0) else 0
            if args.benchmark_command == "score":
                metrics = score_benchmark(
                    args.dataset,
                    args.results,
                    args.output,
                )
                destination = args.output or args.results.parent
                print((destination / "benchmark-report.md").read_text(encoding="utf-8"), end="")
                print(f"benchmark report: {destination / 'benchmark-report.json'}", file=sys.stderr)
                return 0
        except (BenchmarkSchemaError, BenchmarkRunError, OSError, ValueError) as exc:
            print(f"ベンチマークを開始できません: {exc}", file=sys.stderr)
            return 2
        return 2
    if args.command != "audit":
        return 2
    try:
        result = audit_url(args.url)
    except (GitHubUrlError, ModelProviderError, OSError, RuntimeError, ValueError) as exc:
        print(f"AgentScopeを開始できません: {exc}", file=sys.stderr)
        return 2
    print(result.artifacts.path("report.md").read_text(encoding="utf-8"), end="")
    print(f"\nartifact: {result.artifacts.root}", file=sys.stderr)
    return 1 if result.report["runtime"].get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
