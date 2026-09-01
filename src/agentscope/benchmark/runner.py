"""実在GitHub repositoryを順次監査する再開可能なbenchmark runner。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
from typing import Any, Iterable

from agentscope.acquisition.git_snapshot import AcquisitionError, SnapshotLimits
from agentscope.application import audit_url
from agentscope.benchmark.metrics import (
    BenchmarkPrediction,
    compute_benchmark_metrics,
    validate_prediction_row,
)
from agentscope.benchmark.report import render_benchmark_markdown
from agentscope.benchmark.schema import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkCase,
    BenchmarkSchemaError,
    dataset_sha256,
    load_dataset,
)


class BenchmarkRunError(RuntimeError):
    """benchmark実行成果物またはrun設定が不正。"""


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkRunError(f"JSON artifact could not be read: {path}") from exc
    if not isinstance(raw, dict):
        raise BenchmarkRunError(f"JSON artifact must be an object: {path}")
    return raw


def _read_result_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchmarkRunError(f"results file could not be read: {path}") from exc
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            row = validate_prediction_row(raw, context=f"results line {line_number}")
        except (json.JSONDecodeError, ValueError) as exc:
            raise BenchmarkRunError(f"invalid results line {line_number}") from exc
        case_id = row["id"]
        if case_id in rows:
            raise BenchmarkRunError(f"duplicate results case id: {case_id}")
        rows[case_id] = row
    return rows


def _safe_existing_report_path(root: Path, report_path: object) -> Path | None:
    if not isinstance(report_path, str) or not report_path:
        return None
    candidate = (root / report_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise BenchmarkRunError("existing report path escapes benchmark run")
    return candidate


def _select_cases(
    cases: list[BenchmarkCase],
    *,
    limit: int | None,
    ids: set[str] | None,
) -> list[BenchmarkCase]:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise BenchmarkRunError("limit must be a positive integer")
    selected = [case for case in cases if ids is None or case.id in ids]
    if ids:
        missing = ids - {case.id for case in cases}
        if missing:
            raise BenchmarkRunError(f"unknown benchmark case ids: {sorted(missing)}")
    return selected[:limit] if limit is not None else selected


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / "manifest.json"


def _ensure_manifest(
    *,
    output_dir: Path,
    dataset_path: Path,
    digest: str,
    cases: list[BenchmarkCase],
) -> dict[str, Any]:
    path = _manifest_path(output_dir)
    if path.exists():
        manifest = _read_json(path)
        if manifest.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
            raise BenchmarkRunError("unsupported benchmark run schema_version")
        if manifest.get("dataset_sha256") != digest:
            raise BenchmarkRunError(
                "dataset digest differs from existing run; choose a new output directory"
            )
        return manifest
    manifest = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": digest,
        "case_n": len(cases),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "runner": "agentscope.benchmark.runner",
    }
    _write_json(path, manifest)
    return manifest


def _next_run_id(artifacts_dir: Path, case: BenchmarkCase) -> str:
    base = f"{case.id}-{case.commit_sha[:12]}"
    candidate = base
    index = 2
    while (artifacts_dir / candidate).exists():
        candidate = f"{base}-retry{index}"
        index += 1
    return candidate


def _result_row(
    *,
    case: BenchmarkCase,
    status: str,
    report_path: str | None = None,
    actual_commit_sha: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "id": case.id,
        "status": status,
        "report_path": report_path,
        "actual_commit_sha": actual_commit_sha,
        "error": error,
    }


def run_benchmark(
    dataset_path: Path,
    output_dir: Path,
    *,
    limit: int | None = None,
    ids: Iterable[str] | None = None,
    resume: bool = True,
    dry_run: bool = False,
    limits: SnapshotLimits | None = None,
) -> dict[str, Any]:
    """dataset順に監査し、各caseの完了直後にresults.jsonlを更新する。"""

    try:
        cases = load_dataset(dataset_path)
        digest = dataset_sha256(dataset_path)
    except BenchmarkSchemaError as exc:
        raise BenchmarkRunError(str(exc)) from exc
    id_set = set(ids) if ids is not None else None
    selected = _select_cases(cases, limit=limit, ids=id_set)
    if dry_run:
        return {
            "output_dir": str(output_dir),
            "dataset_sha256": digest,
            "selected_ids": [case.id for case in selected],
            "dry_run": True,
        }

    # ArtifactStoreは安全境界のため絶対pathを返す。呼び出し側が
    # `benchmarks/runs/...` のような相対outputを指定しても、report登録時の
    # relative_to()が同じrootを参照するよう、実行開始時に正規化する。
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_manifest(
        output_dir=output_dir,
        dataset_path=dataset_path,
        digest=digest,
        cases=cases,
    )
    results_path = output_dir / "results.jsonl"
    result_rows = _read_result_rows(results_path)
    unknown_result_ids = set(result_rows) - {case.id for case in cases}
    if unknown_result_ids:
        raise BenchmarkRunError(
            f"results contain unknown case ids: {sorted(unknown_result_ids)}"
        )
    artifacts_dir = output_dir / "artifacts"
    limits = limits or SnapshotLimits()
    if (
        not isinstance(limits.max_steps, int)
        or isinstance(limits.max_steps, bool)
        or limits.max_steps < 1
    ):
        raise BenchmarkRunError("max_steps must be a positive integer")
    resumed_n = 0

    for case in selected:
        old = result_rows.get(case.id)
        old_path = _safe_existing_report_path(
            output_dir,
            old.get("report_path") if old else None,
        )
        if (
            resume
            and old
            and old.get("status") == "completed"
            and old_path is not None
            and old_path.is_file()
        ):
            resumed_n += 1
            continue
        run_id = _next_run_id(artifacts_dir, case)
        report_path: str | None = None
        try:
            result = audit_url(
                case.url,
                output_base=artifacts_dir,
                limits=limits,
                run_id=run_id,
                expected_commit_sha=case.commit_sha,
            )
            report_path = result.artifacts.path("report.json").relative_to(output_dir).as_posix()
            row = _result_row(
                case=case,
                status="completed",
                report_path=report_path,
                actual_commit_sha=result.report["subject"]["commit_sha"],
            )
        except AcquisitionError as exc:
            message = str(exc)
            row = _result_row(
                case=case,
                status="stale_commit" if "expected commit" in message else "failed",
                error=message,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            row = _result_row(case=case, status="failed", error=str(exc))
        result_rows[case.id] = row
        _write_jsonl(
            results_path,
            [result_rows[case.id] for case in cases if case.id in result_rows],
        )

    return {
        "output_dir": str(output_dir),
        "results_path": str(results_path),
        "dataset_sha256": digest,
        "selected_n": len(selected),
        "completed_n": sum(
            1
            for case in selected
            if result_rows.get(case.id, {}).get("status") == "completed"
        ),
        "failed_n": sum(
            1
            for case in selected
            if result_rows.get(case.id, {}).get("status") in {"failed", "stale_commit"}
        ),
        "resumed_n": resumed_n,
    }


def load_predictions(results_path: Path) -> dict[str, BenchmarkPrediction]:
    """results.jsonlからreportを読み、metrics用predictionへ変換する。"""

    if not results_path.is_file():
        raise BenchmarkRunError(f"results file does not exist: {results_path}")
    rows = _read_result_rows(results_path)
    root = results_path.parent.resolve()
    predictions: dict[str, BenchmarkPrediction] = {}
    for case_id, row in rows.items():
        report: dict[str, Any] | None = None
        report_path = row.get("report_path")
        if row["status"] == "completed":
            if not isinstance(report_path, str) or not report_path:
                raise BenchmarkRunError(f"completed result has no report_path: {case_id}")
            candidate = (root / report_path).resolve()
            if candidate != root and root not in candidate.parents:
                raise BenchmarkRunError(f"report path escapes benchmark run: {case_id}")
            report = _read_json(candidate)
        predictions[case_id] = BenchmarkPrediction(
            case_id=case_id,
            status=row["status"],
            report_path=report_path,
            report=report,
            error=row.get("error"),
        )
    return predictions


def score_benchmark(
    dataset_path: Path,
    results_path: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """実行済みreportsを再実行せず、決定論的に集計する。"""

    try:
        cases = load_dataset(dataset_path)
        digest = dataset_sha256(dataset_path)
    except BenchmarkSchemaError as exc:
        raise BenchmarkRunError(str(exc)) from exc
    run_dir = results_path.parent
    manifest = _read_json(_manifest_path(run_dir)) if _manifest_path(run_dir).exists() else None
    if manifest is not None and manifest.get("dataset_sha256") != digest:
        raise BenchmarkRunError("dataset digest differs from benchmark results")
    predictions = load_predictions(results_path)
    unknown_result_ids = set(predictions) - {case.id for case in cases}
    if unknown_result_ids:
        raise BenchmarkRunError(
            f"results contain unknown case ids: {sorted(unknown_result_ids)}"
        )
    metrics = compute_benchmark_metrics(
        cases,
        predictions,
        dataset_path=str(dataset_path.resolve()),
        dataset_sha256=digest,
    )
    destination = output_dir or run_dir
    _write_json(destination / "benchmark-report.json", metrics)
    (destination / "benchmark-report.md").parent.mkdir(parents=True, exist_ok=True)
    temporary = (destination / "benchmark-report.md").with_suffix(".md.tmp")
    temporary.write_text(render_benchmark_markdown(metrics), encoding="utf-8")
    temporary.replace(destination / "benchmark-report.md")
    return metrics
