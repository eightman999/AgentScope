"""LLM callからaction/dispatch/observationを追跡する限定的な静的解析。"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re

from agentscope.acquisition.git_snapshot import Snapshot
from agentscope.analysis.inventory import Inventory
from agentscope.analysis.search import SearchHit
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph


@dataclass
class TraceResult:
    matched_files: list[str] = field(default_factory=list)
    coverage: str = "partial"
    uncertainties: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "matched_files": self.matched_files,
            "coverage": self.coverage,
            "uncertainties": self.uncertainties,
        }


MODEL_TERMS = re.compile(
    r"\b(model|llm|openai|anthropic|ollama|complete|completion|generate|invoke|chat)\b",
    re.IGNORECASE,
)
ACTION_TERMS = re.compile(
    r"\b(choose_action|select_action|next_action|action|plan|planner)\b",
    re.IGNORECASE,
)
DISPATCH_TERMS = re.compile(
    r"\b(dispatch|execute_tool|run_tool|tool_registry|tool_calls?|TOOLS)\b",
    re.IGNORECASE,
)
OBSERVATION_TERMS = re.compile(
    r"\b(observe|observation|feedback|result|state)\b",
    re.IGNORECASE,
)
LOOP_TERMS = re.compile(r"\b(while|for|replan|retry|budget|done|termination)\b", re.IGNORECASE)
GOAL_TERMS = re.compile(r"\b(goal|objective|target)\b", re.IGNORECASE)


def _line_hit(
    path: str,
    lines: list[str],
    pattern: re.Pattern[str],
    *,
    line_offset: int = 0,
) -> SearchHit | None:
    for line_no, line in enumerate(lines, 1):
        if pattern.search(line):
            return SearchHit(path, line_no + line_offset, line[:1000])
    return None


def _add_fact(
    *,
    graph: FactGraph,
    ledger: EvidenceLedger,
    hit: SearchHit,
    kind: str,
    node_id: str,
    claim_key: str,
    commit_sha: str,
    reason: str,
) -> None:
    evidence = ledger.add(
        claim_key=claim_key,
        source_kind="repository",
        file=hit.path,
        start_line=hit.line,
        end_line=hit.line,
        excerpt=hit.text,
        commit_sha=commit_sha,
        reason=reason,
        confidence="medium",
    )
    graph.add_node(
        node_id=node_id,
        kind=kind,
        label=kind,
        evidence_ids=[evidence.id],
    )


def _connect_function(
    *,
    path: str,
    lines: list[str],
    label: str,
    graph: FactGraph,
    ledger: EvidenceLedger,
    commit_sha: str,
    result: TraceResult,
    line_offset: int = 0,
) -> None:
    text = "\n".join(lines)
    model_hit = _line_hit(path, lines, MODEL_TERMS, line_offset=line_offset)
    if not model_hit:
        return
    model_id = f"model_call:{path}:{model_hit.line}"
    _add_fact(
        graph=graph,
        ledger=ledger,
        hit=model_hit,
        kind="model_call",
        node_id=model_id,
        claim_key="trace.model_call",
        commit_sha=commit_sha,
        reason=f"{label} contains a model or LLM call candidate.",
    )
    output_hit = model_hit
    output_id = f"model_output:{path}:{model_hit.line}"
    _add_fact(
        graph=graph,
        ledger=ledger,
        hit=output_hit,
        kind="model_output",
        node_id=output_id,
        claim_key="trace.model_output",
        commit_sha=commit_sha,
        reason="The model call produces an output candidate.",
    )
    graph.add_edge(
        source=model_id,
        target=output_id,
        kind="returns",
        evidence_ids=graph.nodes[output_id].evidence_ids,
    )

    action_hit = _line_hit(path, lines, ACTION_TERMS, line_offset=line_offset)
    has_action = bool(action_hit and ("action" in text.lower() or "choose" in text.lower()))
    action_id: str | None = None
    if has_action and action_hit:
        action_id = f"action_selector:{path}:{action_hit.line}"
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=action_hit,
            kind="action_selector",
            node_id=action_id,
            claim_key="trace.action_selector",
            commit_sha=commit_sha,
            reason="Model output is associated with an action-selection candidate.",
        )
        graph.add_edge(
            source=output_id,
            target=action_id,
            kind="controls",
            evidence_ids=graph.nodes[action_id].evidence_ids,
        )

    dispatch_hit = _line_hit(path, lines, DISPATCH_TERMS, line_offset=line_offset)
    dispatch_id: str | None = None
    if dispatch_hit and action_id:
        dispatch_id = f"dispatcher:{path}:{dispatch_hit.line}"
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=dispatch_hit,
            kind="dispatcher",
            node_id=dispatch_id,
            claim_key="trace.dispatch",
            commit_sha=commit_sha,
            reason="An action candidate is passed to a tool dispatcher.",
        )
        graph.add_edge(
            source=action_id,
            target=dispatch_id,
            kind="dispatches",
            evidence_ids=graph.nodes[dispatch_id].evidence_ids,
        )

    observation_hit = _line_hit(path, lines, OBSERVATION_TERMS, line_offset=line_offset)
    observation_id: str | None = None
    if observation_hit and dispatch_id:
        observation_id = f"observation:{path}:{observation_hit.line}"
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=observation_hit,
            kind="observation",
            node_id=observation_id,
            claim_key="trace.observation",
            commit_sha=commit_sha,
            reason="Tool result or environment observation is retained.",
        )
        graph.add_edge(
            source=dispatch_id,
            target=observation_id,
            kind="observes",
            evidence_ids=graph.nodes[observation_id].evidence_ids,
        )

    loop_hit = _line_hit(path, lines, LOOP_TERMS, line_offset=line_offset)
    if loop_hit and observation_id:
        replan_id = f"replanner:{path}:{loop_hit.line}"
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=loop_hit,
            kind="replanner",
            node_id=replan_id,
            claim_key="trace.replan",
            commit_sha=commit_sha,
            reason="A loop, retry, or replan candidate can react to the observation.",
        )
        graph.add_edge(
            source=observation_id,
            target=replan_id,
            kind="replans",
            evidence_ids=graph.nodes[replan_id].evidence_ids,
        )

    if loop_hit:
        loop_id = f"loop:{path}:{loop_hit.line}"
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=loop_hit,
            kind="loop",
            node_id=loop_id,
            claim_key="trace.loop",
            commit_sha=commit_sha,
            reason="A loop, retry, or termination control-flow candidate exists.",
        )
    goal_hit = _line_hit(path, lines, GOAL_TERMS, line_offset=line_offset)
    if goal_hit:
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=goal_hit,
            kind="goal",
            node_id=f"goal:{path}:{goal_hit.line}",
            claim_key="trace.goal",
            commit_sha=commit_sha,
            reason="An explicit goal or objective candidate exists.",
        )
    termination_hit = _line_hit(
        path,
        lines,
        re.compile(r"\b(return|finish|done|termination|stop)\b", re.IGNORECASE),
        line_offset=line_offset,
    )
    if termination_hit:
        _add_fact(
            graph=graph,
            ledger=ledger,
            hit=termination_hit,
            kind="termination",
            node_id=f"termination:{path}:{termination_hit.line}",
            claim_key="trace.termination",
            commit_sha=commit_sha,
            reason="A termination or return path candidate exists.",
        )


def _python_functions(source: str) -> list[tuple[str, int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    functions: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_line = getattr(node, "end_lineno", node.lineno)
        functions.append((node.name, node.lineno, min(end_line, len(lines))))
    return functions


def trace_call_graph(
    snapshot: Snapshot,
    inventory: Inventory,
    ledger: EvidenceLedger,
    graph: FactGraph,
    *,
    commit_sha: str,
    target_path: str | None = None,
) -> TraceResult:
    result = TraceResult(coverage=inventory.coverage)
    code_records = [
        record
        for record in inventory.files
        if record.language in {"python", "javascript", "typescript", "rust", "go", "java", "kotlin", "swift"}
    ]
    if target_path:
        code_records = [record for record in code_records if record.path == target_path]
    for record in code_records:
        path = snapshot.root / Path(record.path)
        try:
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
        except (OSError, UnicodeDecodeError):
            result.uncertainties.append(f"could not parse {record.path}")
            continue
        before = len(graph.nodes)
        if record.language == "python":
            functions = _python_functions(source)
            if not functions:
                result.uncertainties.append(f"Python AST unavailable for {record.path}")
                _connect_function(
                    path=record.path,
                    lines=lines[:200],
                    label=record.path,
                    graph=graph,
                    ledger=ledger,
                    commit_sha=commit_sha,
                    result=result,
                    line_offset=0,
                )
            for name, start, end in functions:
                _connect_function(
                    path=record.path,
                    lines=lines[start - 1 : end],
                    label=name,
                    graph=graph,
                    ledger=ledger,
                    commit_sha=commit_sha,
                    result=result,
                    line_offset=start - 1,
                )
        else:
            _connect_function(
                path=record.path,
                lines=lines[:200],
                label=record.path,
                graph=graph,
                ledger=ledger,
                commit_sha=commit_sha,
                result=result,
                line_offset=0,
            )
            if record.language not in {"javascript", "typescript"}:
                result.uncertainties.append(
                    f"limited lexical call graph for {record.language}: {record.path}"
                )
        if len(graph.nodes) > before:
            result.matched_files.append(record.path)
    if result.uncertainties:
        result.coverage = "partial"
    return result
