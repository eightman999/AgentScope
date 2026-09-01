"""AgentScopeのaudit application service。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from typing import Any, Callable

from agentscope.acquisition.artifacts import (
    ArtifactStore,
    default_artifact_base,
)
from agentscope.acquisition.github_metadata import GitHubMetadataSource
from agentscope.acquisition.github_url import GitHubRepoRef, parse_github_url
from agentscope.acquisition.git_snapshot import (
    GitSnapshotSource,
    Snapshot,
    SnapshotLimits,
    local_snapshot,
)
from agentscope.agent.loop import AgentLoop, AgentLoopResult
from agentscope.agent.prompt import PROMPT_VERSION
from agentscope.agent.tools import AuditToolContext, create_tool_registry
from agentscope.analysis.inventory import Inventory, build_inventory
from agentscope.domain.classifications import calculate_classifications
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph
from agentscope.domain.scoring import calculate_scores
from agentscope.domain.state import AuditState
from agentscope.model.local import LocalLlamaCppProvider
from agentscope.model.manifest import ModelManifest, load_manifest
from agentscope.model.provider import ModelProvider, ModelProviderError
from agentscope.report.json_report import build_report
from agentscope.report.lint import lint_report
from agentscope.report.markdown import render_markdown


@dataclass
class AuditResult:
    report: dict[str, Any]
    artifacts: ArtifactStore
    context: AuditToolContext


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_sha256(path: Path) -> str | None:
    return _sha256(path) if path.is_file() else None


def _resource_root() -> Path:
    source_root = Path(__file__).resolve().parents[2]
    configured_root = os.environ.get("AGENTSCOPE_RESOURCE_ROOT")
    if configured_root:
        configured = Path(configured_root).expanduser().resolve()
        if configured.is_dir():
            return configured
    candidates = (
        source_root / "resources",
        Path(sys.prefix) / "share" / "agentscope" / "resources",
        Path.cwd() / "resources",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def _runtime_version(binary_path: str) -> str:
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or not lines:
        return "unknown"
    for line in lines:
        if line.lower().startswith("version:"):
            return line[:500]
    return lines[0][:500]


def _model_provider(resource_root: Path) -> tuple[ModelProvider, str, str | None, str, str]:
    manifest = load_manifest(resource_root / "model-manifest.json")
    model_path = resource_root / "models" / manifest.artifact
    schema_path = resource_root / "action-schema.json"
    provider = LocalLlamaCppProvider(
        model_path=model_path,
        manifest=manifest,
        schema_path=schema_path,
        grammar_path=resource_root / "action-grammar.gbnf",
        tool_grammar_path=resource_root / "tool-action-grammar.gbnf",
        finish_grammar_path=resource_root / "finish-action-grammar.gbnf",
    )
    model_sha256 = _sha256(model_path)
    if model_path.stat().st_size != manifest.model_size_bytes:
        raise ModelProviderError("local model size does not match the manifest")
    if manifest.model_sha256 and manifest.model_sha256.lower() != model_sha256:
        raise ModelProviderError("local model checksum does not match the manifest")
    return (
        provider,
        manifest.model_id,
        model_sha256,
        manifest.runtime,
        _runtime_version(provider.binary_path),
    )


def _run_id(ref: GitHubRepoRef, requested: str | None = None) -> str:
    if requested is not None:
        if not requested or "/" in requested or "\\" in requested or requested in {".", ".."}:
            raise ValueError("run_id must be a non-empty relative name")
        return requested
    return f"{ref.owner}-{ref.repo}-{uuid.uuid4().hex[:8]}"


def _prepare_context(
    *,
    raw_url: str,
    ref: GitHubRepoRef,
    snapshot: Snapshot,
    artifacts: ArtifactStore,
    limits: SnapshotLimits,
    provider: ModelProvider,
    metadata_source: GitHubMetadataSource | None,
    git_runner: Callable[..., object] | None,
) -> tuple[AuditToolContext, Inventory]:
    inventory = build_inventory(snapshot, limits)
    state = AuditState.initial(
        run_id=artifacts.root.name,
        input_url=raw_url,
        canonical_url=ref.canonical_url,
        commit_sha=snapshot.commit_sha,
        budget=limits.max_steps,
    )
    ledger = EvidenceLedger()
    graph = FactGraph()
    context = AuditToolContext(
        snapshot=snapshot,
        inventory=inventory,
        limits=limits,
        ledger=ledger,
        graph=graph,
        state=state,
        artifacts=artifacts,
        repo_ref=ref,
        metadata_source=metadata_source,
        git_runner=git_runner,
        facts={
            "inventory_coverage": inventory.coverage,
            "inventory_file_count": len(inventory.files),
        },
    )
    artifacts.write_json("inventory.json", inventory.to_dict())
    artifacts.write_json(
        "subject.json",
        {
            "input_url": raw_url,
            "canonical_url": ref.canonical_url,
            "commit_sha": snapshot.commit_sha,
            "snapshot_coverage": snapshot.coverage,
        },
    )
    return context, inventory


def audit_snapshot(
    *,
    raw_url: str,
    ref: GitHubRepoRef,
    snapshot: Snapshot,
    artifacts: ArtifactStore,
    provider: ModelProvider,
    metadata_source: GitHubMetadataSource | None = None,
    limits: SnapshotLimits | None = None,
    model_id: str = "mock",
    model_sha256: str | None = None,
    engine: str = "mock",
    runtime_version: str | None = None,
    git_runner: Callable[..., object] | None = None,
    audited_at: str | None = None,
) -> AuditResult:
    limits = limits or SnapshotLimits()
    audited_at = audited_at or datetime.now(timezone.utc).isoformat()
    context, _ = _prepare_context(
        raw_url=raw_url,
        ref=ref,
        snapshot=snapshot,
        artifacts=artifacts,
        limits=limits,
        provider=provider,
        metadata_source=metadata_source,
        git_runner=git_runner,
    )
    resource_root = _resource_root()
    artifacts.write_json(
        "run-manifest.json",
        {
            "schema_version": "0.1",
            "prompt_version": PROMPT_VERSION,
            "action_schema_sha256": _optional_sha256(resource_root / "action-schema.json"),
            "action_grammar_sha256": _optional_sha256(resource_root / "action-grammar.gbnf"),
            "tool_action_grammar_sha256": _optional_sha256(resource_root / "tool-action-grammar.gbnf"),
            "finish_action_grammar_sha256": _optional_sha256(resource_root / "finish-action-grammar.gbnf"),
            "report_schema_sha256": _optional_sha256(resource_root / "report-schema.json"),
            "subject": {
                "input_url": raw_url,
                "canonical_url": ref.canonical_url,
                "commit_sha": snapshot.commit_sha,
                "snapshot_coverage": snapshot.coverage,
                "audited_at": audited_at,
            },
            "runtime": {
                "model_id": model_id,
                "model_sha256": model_sha256,
                "engine": engine,
                "runtime_version": runtime_version,
            },
        },
    )
    registry = create_tool_registry(context)
    loop = AgentLoop(
        context=context,
        provider=provider,
        registry=registry,
        artifacts=artifacts,
    )
    loop_result: AgentLoopResult = loop.run()
    scores = calculate_scores(
        graph=context.graph,
        ledger=context.ledger,
        artifacts=artifacts,
        commit_sha=context.state.commit_sha,
        facts=context.facts,
    )
    classifications = calculate_classifications(
        graph=context.graph,
        ledger=context.ledger,
        artifacts=artifacts,
        commit_sha=context.state.commit_sha,
        facts=context.facts,
    )
    report = build_report(
        state=loop_result.context.state,
        scores=scores,
        classifications=classifications,
        ledger=context.ledger,
        graph=context.graph,
        model_id=model_id,
        model_sha256=model_sha256,
        engine=engine,
        runtime_version=runtime_version,
        audited_at=audited_at,
        snapshot_coverage=snapshot.coverage,
    )
    lint_report(
        report,
        snapshot_root=snapshot.root,
        artifact_root=artifacts.root,
    )
    artifacts.write_json("report.json", report)
    artifacts.write_text("report.md", render_markdown(report))
    return AuditResult(report=report, artifacts=artifacts, context=context)


def audit_url(
    raw_url: str,
    *,
    output_base: Path | None = None,
    limits: SnapshotLimits | None = None,
    run_id: str | None = None,
    expected_commit_sha: str | None = None,
) -> AuditResult:
    ref = parse_github_url(raw_url)
    limits = limits or SnapshotLimits()
    base = output_base or default_artifact_base()
    artifacts = ArtifactStore.create(base, _run_id(ref, run_id))
    snapshot_destination = artifacts.root / "snapshot"
    snapshot = GitSnapshotSource(limits=limits).acquire(
        ref,
        snapshot_destination,
        expected_commit_sha=expected_commit_sha,
    )
    provider, model_id, model_sha256, engine, runtime_version = _model_provider(_resource_root())
    return audit_snapshot(
        raw_url=raw_url,
        ref=ref,
        snapshot=snapshot,
        artifacts=artifacts,
        provider=provider,
        metadata_source=GitHubMetadataSource(),
        limits=limits,
        model_id=model_id,
        model_sha256=model_sha256,
        engine=engine,
        runtime_version=runtime_version,
    )


def audit_local_directory(
    root: Path,
    *,
    raw_url: str = "https://github.com/fixture/repository",
    commit_sha: str = "fixture-sha",
    artifacts: ArtifactStore | None = None,
    provider: ModelProvider,
    metadata_source: GitHubMetadataSource | None = None,
    limits: SnapshotLimits | None = None,
    model_id: str = "mock",
    model_sha256: str | None = None,
    engine: str = "mock",
    runtime_version: str | None = None,
    git_runner: Callable[..., object] | None = None,
    audited_at: str | None = None,
) -> AuditResult:
    ref = parse_github_url(raw_url)
    store = artifacts or ArtifactStore.create(default_artifact_base(), _run_id(ref))
    snapshot = local_snapshot(root, commit_sha=commit_sha)
    return audit_snapshot(
        raw_url=raw_url,
        ref=ref,
        snapshot=snapshot,
        artifacts=store,
        provider=provider,
        metadata_source=metadata_source,
        limits=limits,
        model_id=model_id,
        model_sha256=model_sha256,
        engine=engine,
        runtime_version=runtime_version,
        git_runner=git_runner,
        audited_at=audited_at,
    )
