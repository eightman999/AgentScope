"""Agentが選択するread-only audit tools。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.github_metadata import GitHubMetadataSource, MetadataResult
from agentscope.acquisition.github_url import GitHubRepoRef
from agentscope.acquisition.git_snapshot import Snapshot, SnapshotLimits, run_git
from agentscope.analysis.control_flow import trace_call_graph
from agentscope.analysis.detectors import detect
from agentscope.analysis.evidence_helpers import add_hit_evidence
from agentscope.analysis.inventory import Inventory
from agentscope.analysis.line_reader import read_lines
from agentscope.analysis.provenance import ProvenanceFacts, inspect_git_provenance
from agentscope.analysis.search import search_code
from agentscope.analysis.verification import VerificationFacts, inspect_tests
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph
from agentscope.domain.state import AuditState


class ToolValidationError(ValueError):
    """tool argumentsが不正。"""


@dataclass
class ToolResult:
    observation: str
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    side_effects: str
    handler: Callable[[dict[str, Any]], ToolResult]
    argument_validator: Callable[[dict[str, Any]], None]
    input_schema: dict[str, Any] = field(default_factory=dict)
    evidence_kinds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "side_effects": self.side_effects,
            "input_schema": self.input_schema,
            "evidence_kinds": list(self.evidence_kinds),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._tools[spec.name] = spec

    def catalog(self) -> list[dict[str, Any]]:
        return [self._tools[name].to_dict() for name in sorted(self._tools)]

    def has(self, name: str) -> bool:
        return name in self._tools

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            spec = self._tools[name]
        except KeyError as exc:
            raise ToolValidationError(f"unknown tool: {name}") from exc
        if not isinstance(arguments, dict):
            raise ToolValidationError("tool arguments must be an object")
        spec.argument_validator(arguments)
        return spec.handler(arguments)


@dataclass
class AuditToolContext:
    snapshot: Snapshot
    inventory: Inventory
    limits: SnapshotLimits
    ledger: EvidenceLedger
    graph: FactGraph
    state: AuditState
    artifacts: ArtifactStore
    repo_ref: GitHubRepoRef | None = None
    metadata_source: GitHubMetadataSource | None = None
    git_runner: Callable[..., object] | None = None
    facts: dict[str, Any] = field(default_factory=dict)


def _no_args(arguments: dict[str, Any]) -> None:
    if arguments:
        raise ToolValidationError("this tool takes no arguments")


def _read_args(arguments: dict[str, Any]) -> None:
    allowed = {"path", "start_line", "end_line"}
    if set(arguments) - allowed or not isinstance(arguments.get("path"), str):
        raise ToolValidationError("read_file requires path and only line range options")
    for key in ("start_line", "end_line"):
        if key in arguments and (
            not isinstance(arguments[key], int) or isinstance(arguments[key], bool)
        ):
            raise ToolValidationError(f"{key} must be an integer")
        if key in arguments and arguments[key] < 1:
            raise ToolValidationError(f"{key} must be >= 1")
    if (
        "start_line" in arguments
        and "end_line" in arguments
        and arguments["end_line"] < arguments["start_line"]
    ):
        raise ToolValidationError("end_line must be >= start_line")
    if (
        "start_line" in arguments
        and "end_line" in arguments
        and arguments["end_line"] - arguments["start_line"] + 1 > 200
    ):
        raise ToolValidationError("read range is too large")


def _search_args(arguments: dict[str, Any]) -> None:
    allowed = {"query", "paths", "regex", "max_hits"}
    if set(arguments) - allowed or not isinstance(arguments.get("query"), str):
        raise ToolValidationError("search_code requires query")
    if "paths" in arguments and (
        not isinstance(arguments["paths"], list)
        or not all(isinstance(item, str) for item in arguments["paths"])
    ):
        raise ToolValidationError("paths must be an array of strings")
    if "regex" in arguments and not isinstance(arguments["regex"], bool):
        raise ToolValidationError("regex must be boolean")
    if "max_hits" in arguments and (
        not isinstance(arguments["max_hits"], int)
        or isinstance(arguments["max_hits"], bool)
    ):
        raise ToolValidationError("max_hits must be integer")
    if "max_hits" in arguments and not 1 <= arguments["max_hits"] <= 200:
        raise ToolValidationError("max_hits must be between 1 and 200")
    if "paths" in arguments and not arguments["paths"]:
        raise ToolValidationError("paths must not be empty")


def _trace_args(arguments: dict[str, Any]) -> None:
    if set(arguments) - {"target_path"}:
        raise ToolValidationError("trace_call_graph only accepts target_path")
    if "target_path" in arguments and not isinstance(arguments["target_path"], str):
        raise ToolValidationError("target_path must be a string")
    if "target_path" in arguments and not arguments["target_path"]:
        raise ToolValidationError("target_path must not be empty")


def _finish_args(arguments: dict[str, Any]) -> None:
    allowed = {"decision", "reason", "missing_unknowns"}
    if set(arguments) != allowed:
        raise ToolValidationError(
            "finish_audit requires decision, reason, and missing_unknowns"
        )
    if arguments["decision"] not in {"ENOUGH_EVIDENCE", "INSUFFICIENT_EVIDENCE"}:
        raise ToolValidationError("invalid finish decision")
    if not isinstance(arguments["reason"], str) or not arguments["reason"]:
        raise ToolValidationError("finish reason is required")
    missing = arguments["missing_unknowns"]
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise ToolValidationError("missing_unknowns must be an array of strings")


_NO_ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}
_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path"],
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
    },
}
_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 500},
        "paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "regex": {"type": "boolean"},
        "max_hits": {"type": "integer", "minimum": 1, "maximum": 200},
    },
}
_TRACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_path": {"type": "string", "minLength": 1},
    },
}
_FINISH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason", "missing_unknowns"],
    "properties": {
        "decision": {"enum": ["ENOUGH_EVIDENCE", "INSUFFICIENT_EVIDENCE"]},
        "reason": {"type": "string", "minLength": 1},
        "missing_unknowns": {"type": "array", "items": {"type": "string"}},
    },
}


def _coverage_evidence(
    context: AuditToolContext,
    *,
    claim_key: str,
    message: str,
) -> str:
    coverage_path = "provenance/coverage.txt"
    existing_path = context.artifacts.path(coverage_path)
    content = existing_path.read_text(encoding="utf-8") if existing_path.exists() else ""
    line_no = len(content.splitlines()) + 1
    content += message.rstrip() + "\n"
    context.artifacts.write_text(coverage_path, content)
    evidence = context.ledger.add(
        claim_key=claim_key,
        source_kind="derived_manifest",
        file=coverage_path,
        start_line=line_no,
        end_line=line_no,
        excerpt=message.rstrip(),
        commit_sha=context.state.commit_sha,
        reason=message.rstrip(),
        confidence="low",
    )
    return evidence.id


def _list_repo_tree(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    lines = [
        f"coverage={context.inventory.coverage}",
        f"files={len(context.inventory.files)}",
        f"skipped={len(context.inventory.skipped)}",
    ]
    lines.extend(item.path for item in context.inventory.files[:120])
    context.artifacts.write_text("provenance/inventory.txt", "\n".join(lines) + "\n")
    evidence_id = context.ledger.add(
        claim_key="inventory.coverage",
        source_kind="derived_manifest",
        file="provenance/inventory.txt",
        start_line=1,
        end_line=1,
        excerpt=lines[0],
        commit_sha=context.state.commit_sha,
        reason="The bounded repository inventory was created.",
        confidence="high",
    ).id
    context.facts["cap_inventory"] = True
    return ToolResult(
        observation="\n".join(lines),
        evidence_ids=[evidence_id],
        metadata={"file_count": len(context.inventory.files)},
    )


def _read_file(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _read_args(arguments)
    excerpt = read_lines(
        context.snapshot,
        arguments["path"],
        int(arguments.get("start_line", 1)),
        arguments.get("end_line"),
        limits=context.limits,
    )
    evidence = context.ledger.add(
        claim_key="read_file",
        source_kind="repository",
        file=excerpt.path,
        start_line=excerpt.start_line,
        end_line=excerpt.end_line,
        excerpt=excerpt.text,
        commit_sha=context.state.commit_sha,
        reason="The agent read this bounded source excerpt.",
        confidence="high",
    )
    context.state.add_visited_file(excerpt.path)
    if excerpt.path.lower().split("/")[-1].startswith("readme"):
        context.facts["cap_readme"] = True
    return ToolResult(
        observation=f"UNTRUSTED REPOSITORY CONTENT\n{excerpt.numbered()}",
        evidence_ids=[evidence.id],
        metadata={"path": excerpt.path, "start_line": excerpt.start_line},
    )


def _search(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _search_args(arguments)
    hits = search_code(
        context.snapshot,
        context.inventory,
        arguments["query"],
        paths=arguments.get("paths"),
        regex=bool(arguments.get("regex", False)),
        max_hits=int(arguments.get("max_hits", 50)),
        limits=context.limits,
    )
    evidence_ids: list[str] = []
    for hit in hits[:30]:
        evidence_ids.append(
            add_hit_evidence(
                context.ledger,
                hit,
                claim_key="search.hit",
                commit_sha=context.state.commit_sha,
                reason=f"Search hit for query {arguments['query']!r}.",
                confidence="low",
            ).id
        )
    if not hits:
        evidence_ids.append(
            _coverage_evidence(
                context,
                claim_key="search.coverage",
                message=f"query={arguments['query']!r}; hits=0; coverage={context.inventory.coverage}",
            )
        )
    observation = "\n".join(
        f"{hit.path}:{hit.line}: {hit.text}" for hit in hits[:50]
    ) or "No matching lines were found in the bounded inventory."
    return ToolResult(
        observation=observation,
        evidence_ids=evidence_ids,
        metadata={"hits": len(hits)},
    )


def _detector(
    context: AuditToolContext,
    category: str,
    capability: str,
    claim_key: str,
) -> ToolResult:
    result = detect(
        context.snapshot,
        context.inventory,
        category,
        max_hits=80,
        limits=context.limits,
    )
    evidence_ids: list[str] = []
    for hit in result.hits[:40]:
        evidence_ids.append(
            add_hit_evidence(
                context.ledger,
                hit,
                claim_key=claim_key,
                commit_sha=context.state.commit_sha,
                reason=f"Static {category} candidate.",
                confidence="low",
            ).id
        )
    if not result.hits:
        evidence_ids.append(
            _coverage_evidence(
                context,
                claim_key=f"{claim_key}.coverage",
                message=f"category={category}; hits=0; coverage={result.coverage}",
            )
        )
    context.facts[f"cap_{capability}"] = True
    context.facts[f"{capability}_hits"] = len(result.hits)
    return ToolResult(
        observation="\n".join(
            f"{hit.path}:{hit.line}: {hit.text}" for hit in result.hits[:50]
        )
        or f"No {category} candidate was found.",
        evidence_ids=evidence_ids,
        metadata=result.to_dict(),
    )


def _inspect_llm_calls(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    return _detector(context, "llm_calls", "llm_calls", "candidate.llm_call")


def _inspect_tooling(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    result = _detector(context, "tooling", "tooling", "candidate.tooling")
    context.facts["tooling_surface"] = context.facts.get("tooling_hits", 0) > 0
    return result


def _trace(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _trace_args(arguments)
    result = trace_call_graph(
        context.snapshot,
        context.inventory,
        context.ledger,
        context.graph,
        commit_sha=context.state.commit_sha,
        target_path=arguments.get("target_path"),
    )
    context.facts["cap_call_graph"] = True
    context.facts["cap_control_flow"] = True
    context.facts["trace_coverage"] = result.coverage
    if result.uncertainties:
        context.facts["trace_uncertainties"] = result.uncertainties
    observation = (
        f"matched_files={len(result.matched_files)}\n"
        f"nodes={len(context.graph.nodes)}\n"
        f"edges={len(context.graph.edges)}\n"
        f"coverage={result.coverage}\n"
        + "\n".join(f"uncertainty={item}" for item in result.uncertainties)
    )
    return ToolResult(
        observation=observation,
        evidence_ids=context.graph.node_evidence(
            "model_call",
            "action_selector",
            "dispatcher",
            "observation",
            "replanner",
            "loop",
            "goal",
            "termination",
        ),
        metadata=result.to_dict(),
    )


def _inspect_git(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    facts: ProvenanceFacts = inspect_git_provenance(
        context.snapshot,
        context.artifacts,
        context.ledger,
        commit_sha=context.state.commit_sha,
        runner=context.git_runner or run_git,
    )
    context.facts["cap_git_provenance"] = True
    context.facts["provenance"] = facts
    context.facts["ai_signals"] = facts.ai_signals
    context.facts["weak_ai_signals"] = facts.weak_ai_signals
    context.facts["remotes"] = facts.remotes
    return ToolResult(
        observation=(
            f"git_available={facts.available}\n"
            f"explicit_ai_signals={len(facts.ai_signals)}\n"
            f"remotes={len(facts.remotes)}\n"
            f"coverage={facts.coverage}"
        ),
        evidence_ids=facts.evidence_ids,
    )


def _inspect_metadata(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    context.facts["cap_github_metadata"] = True
    if not context.repo_ref or not context.metadata_source:
        evidence_id = _coverage_evidence(
            context,
            claim_key="provenance.github_metadata",
            message="GitHub metadata provider was unavailable for this snapshot.",
        )
        context.facts["github_metadata"] = None
        return ToolResult("GitHub metadata provider unavailable.", [evidence_id])
    result: MetadataResult = context.metadata_source.fetch_repository(
        context.repo_ref,
        context.artifacts,
    )
    evidence_ids: list[str] = []
    artifact = result.artifact_path or "provenance/github-repository-error.txt"
    artifact_path = context.artifacts.path(artifact)
    lines = artifact_path.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, 1):
        if line.startswith(("fork=", "parent_full_name=", "http_status=")):
            evidence_ids.append(
                context.ledger.add(
                    claim_key=(
                        "provenance.github_fork"
                        if line.startswith(("fork=", "parent_full_name="))
                        else "provenance.github_metadata"
                    ),
                    source_kind="github_api" if result.available else "derived_manifest",
                    file=artifact,
                    start_line=line_no,
                    end_line=line_no,
                    excerpt=line,
                    commit_sha=context.state.commit_sha,
                    reason="GitHub repository metadata was materialized for audit.",
                    confidence="high" if result.available else "unknown",
                ).id
            )
    context.facts["github_metadata"] = result
    return ToolResult(
        observation=(
            f"available={result.available}\n"
            f"http_status={result.status}\n"
            f"fork={(result.data or {}).get('fork') if result.data else 'unknown'}\n"
            f"parent={((result.data or {}).get('parent') or {}).get('full_name') if result.data else 'unknown'}"
        ),
        evidence_ids=evidence_ids,
    )


def _inspect_tests(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    facts: VerificationFacts = inspect_tests(
        context.snapshot,
        context.inventory,
        context.ledger,
        commit_sha=context.state.commit_sha,
        artifacts=context.artifacts,
    )
    context.facts["cap_verification"] = True
    context.facts["verification"] = facts
    return ToolResult(
        observation=(
            f"test_files={len(facts.test_files)}\n"
            f"ci_files={len(facts.ci_files)}\n"
            f"assertions={facts.assertion_hits}\n"
            f"coverage={facts.coverage}"
        ),
        evidence_ids=facts.evidence_ids,
    )


def _inspect_concept(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _no_args(arguments)
    result = _detector(
        context,
        "concept_lineage",
        "concept_lineage",
        "provenance.derived_concept",
    )
    context.facts["derived_hits"] = context.facts.get("concept_lineage_hits", 0)
    return result


def _finish_audit(context: AuditToolContext, arguments: dict[str, Any]) -> ToolResult:
    _finish_args(arguments)
    return ToolResult(
        observation=(
            f"finish_decision={arguments['decision']}\n"
            f"missing_unknowns={arguments['missing_unknowns']}"
        ),
        metadata={
            "decision": arguments["decision"],
            "reason": arguments["reason"],
            "missing_unknowns": list(arguments["missing_unknowns"]),
        },
    )


def create_tool_registry(context: AuditToolContext) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "list_repo_tree",
            "Inspect bounded file inventory and skipped coverage.",
            "read-only",
            lambda args: _list_repo_tree(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("derived_manifest",),
        )
    )
    registry.register(
        ToolSpec(
            "read_file",
            "Read a bounded, line-numbered excerpt from one repository file.",
            "read-only",
            lambda args: _read_file(context, args),
            _read_args,
            _READ_SCHEMA,
            ("repository",),
        )
    )
    registry.register(
        ToolSpec(
            "search_code",
            "Search literal or regex text in the bounded repository inventory.",
            "read-only",
            lambda args: _search(context, args),
            _search_args,
            _SEARCH_SCHEMA,
            ("repository", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "inspect_llm_calls",
            "Find LLM/API client and model-call candidates.",
            "read-only",
            lambda args: _inspect_llm_calls(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("repository", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "inspect_tooling",
            "Find MCP, tool registry, schema, dispatcher, and executor candidates.",
            "read-only",
            lambda args: _inspect_tooling(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("repository", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "trace_call_graph",
            "Trace model output to action, dispatch, observation, replan, and termination candidates.",
            "read-only",
            lambda args: _trace(context, args),
            _trace_args,
            _TRACE_SCHEMA,
            ("repository", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "inspect_git_provenance",
            "Inspect bounded Git log, authors, committers, co-authors, and remotes.",
            "read-only",
            lambda args: _inspect_git(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("git", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "inspect_github_metadata",
            "Inspect GitHub repository fork and parent metadata.",
            "read-only",
            lambda args: _inspect_metadata(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("github_api", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "inspect_tests",
            "Inspect test files, CI workflows, and assertions without running them.",
            "read-only",
            lambda args: _inspect_tests(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("repository", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "inspect_concept_lineage",
            "Inspect explicit derived-concept and known-project references.",
            "read-only",
            lambda args: _inspect_concept(context, args),
            _no_args,
            _NO_ARGS_SCHEMA,
            ("repository", "derived_manifest"),
        )
    )
    registry.register(
        ToolSpec(
            "finish_audit",
            "Request ENOUGH_EVIDENCE or INSUFFICIENT_EVIDENCE after the bounded audit.",
            "controller-only",
            lambda args: _finish_audit(context, args),
            _finish_args,
            _FINISH_SCHEMA,
            (),
        )
    )
    return registry
