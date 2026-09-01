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
MODEL_CALL_TERMS = re.compile(
    r"\b(?:model|llm|openai|anthropic|ollama)\b\s*(?:\.[A-Za-z_$][\w$]*\s*)*\(|"
    r"\b(?:complete|completion|generate|invoke|chat)\s*\(",
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


@dataclass(frozen=True)
class _Flow:
    """式の値がどの実行時値から来たかを表す保守的なflow summary。"""

    model_sources: frozenset[str] = frozenset()
    dispatch_sources: frozenset[str] = frozenset()
    replan_sources: frozenset[str] = frozenset()
    observation_sources: frozenset[str] = frozenset()


def _merge_flow(*flows: _Flow) -> _Flow:
    return _Flow(
        model_sources=frozenset(
            source for flow in flows for source in flow.model_sources
        ),
        dispatch_sources=frozenset(
            source for flow in flows for source in flow.dispatch_sources
        ),
        replan_sources=frozenset(
            source for flow in flows for source in flow.replan_sources
        ),
        observation_sources=frozenset(
            source for flow in flows for source in flow.observation_sources
        ),
    )


def _line_hit(
    path: str,
    lines: list[str],
    pattern: re.Pattern[str],
    *,
    line_offset: int = 0,
) -> SearchHit | None:
    for line_no, line in enumerate(lines, 1):
        if pattern.search(line):
            return SearchHit(path, line_no + line_offset, line)
    return None


def _node_hit(path: str, lines: list[str], node: ast.AST) -> SearchHit:
    line_no = max(1, int(getattr(node, "lineno", 1)))
    if lines:
        line_no = min(line_no, len(lines))
        text = lines[line_no - 1]
    else:
        text = ""
    return SearchHit(path, line_no, text)


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


def _is_action_name(name: str) -> bool:
    return bool(re.search(r"(?:^|_)(action|plan|tool_call)(?:$|_)", name, re.IGNORECASE))


def _is_goal_name(name: str) -> bool:
    return bool(re.fullmatch(r"(?:goal|objective|target)", name, re.IGNORECASE))


def _call_name(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except (AttributeError, ValueError):
        return ""


def _is_model_call_name(name: str) -> bool:
    return bool(MODEL_CALL_TERMS.search(f"{name}("))


def _is_dispatch_call_name(name: str) -> bool:
    final_name = name.rsplit(".", 1)[-1]
    return bool(
        re.fullmatch(
            r"(?:dispatch|execute_tool|run_tool|call_tool|dispatch_tool|tool_registry)",
            final_name,
            re.IGNORECASE,
        )
    )


def _is_observation_call_name(name: str) -> bool:
    final_name = name.rsplit(".", 1)[-1]
    return bool(
        re.fullmatch(r"(?:observe|record_observation|observe_result)", final_name, re.IGNORECASE)
    )


def _is_replan_call_name(name: str) -> bool:
    return bool(re.search(r"\breplan\b", name, re.IGNORECASE))


class _PythonFlowAnalyzer:
    """Python AST上で、関数内の明示された値の流れだけを追跡する。"""

    def __init__(
        self,
        *,
        path: str,
        lines: list[str],
        graph: FactGraph,
        ledger: EvidenceLedger,
        commit_sha: str,
        scope: ast.AST,
        scope_name: str,
    ) -> None:
        self.path = path
        self.lines = lines
        self.graph = graph
        self.ledger = ledger
        self.commit_sha = commit_sha
        self.scope = scope
        self.scope_name = scope_name
        self.variables: dict[str, _Flow] = {}
        self.action_selectors: dict[str, str] = {}
        self.latest_observation: str | None = None
        self.goal_added = False
        self.replan_lines: dict[str, ast.AST] = {}

    def _add_node(
        self,
        node: ast.AST,
        *,
        kind: str,
        node_id: str,
        claim_key: str,
        reason: str,
    ) -> None:
        _add_fact(
            graph=self.graph,
            ledger=self.ledger,
            hit=_node_hit(self.path, self.lines, node),
            kind=kind,
            node_id=node_id,
            claim_key=claim_key,
            commit_sha=self.commit_sha,
            reason=reason,
        )

    def _add_goal(self, node: ast.AST) -> None:
        if self.goal_added:
            return
        self.goal_added = True
        self._add_node(
            node,
            kind="goal",
            node_id=f"goal:{self.path}:{getattr(node, 'lineno', 1)}",
            claim_key="trace.goal",
            reason="An explicit goal or objective candidate exists in executable Python code.",
        )

    def _add_loop(self, node: ast.AST) -> None:
        self._add_node(
            node,
            kind="loop",
            node_id=f"loop:{self.path}:{getattr(node, 'lineno', 1)}",
            claim_key="trace.loop",
            reason="A Python loop provides an executable iteration boundary.",
        )

    def _add_termination(self, node: ast.AST) -> None:
        self._add_node(
            node,
            kind="termination",
            node_id=f"termination:{self.path}:{getattr(node, 'lineno', 1)}",
            claim_key="trace.termination",
            reason="An executable return or termination path exists.",
        )

    def _add_model_call(self, node: ast.Call, *, capture_output: bool) -> _Flow:
        line = int(getattr(node, "lineno", 1))
        column = int(getattr(node, "col_offset", 0))
        model_id = f"model_call:{self.path}:{line}:{column}"
        self._add_node(
            node,
            kind="model_call",
            node_id=model_id,
            claim_key="trace.model_call",
            reason=f"{self.scope_name} contains an executable model or LLM call candidate.",
        )
        if not capture_output:
            return _Flow()
        output_id = f"model_output:{self.path}:{line}:{column}"
        self._add_node(
            node,
            kind="model_output",
            node_id=output_id,
            claim_key="trace.model_output",
            reason="The model call result is consumed by an enclosing executable expression.",
        )
        self.graph.add_edge(
            source=model_id,
            target=output_id,
            kind="returns",
            evidence_ids=self.graph.nodes[output_id].evidence_ids,
        )
        replan_sources = (
            frozenset({output_id})
            if _is_replan_call_name(_call_name(node))
            else frozenset()
        )
        self.replan_lines[output_id] = node
        return _Flow(model_sources=frozenset({output_id}), replan_sources=replan_sources)

    def _ensure_selector(self, node: ast.AST, model_sources: frozenset[str]) -> str:
        line = int(getattr(node, "lineno", 1))
        selector_id = f"action_selector:{self.path}:{line}"
        self._add_node(
            node,
            kind="action_selector",
            node_id=selector_id,
            claim_key="trace.action_selector",
            reason="A model-derived value is used as an action-selection candidate.",
        )
        for source in model_sources:
            self.graph.add_edge(
                source=source,
                target=selector_id,
                kind="controls",
                evidence_ids=self.graph.nodes[selector_id].evidence_ids,
            )
        return selector_id

    def _ensure_replan(self, node: ast.AST, flow: _Flow) -> None:
        if not self.latest_observation or not flow.replan_sources:
            return
        for source in flow.replan_sources:
            replan_node = self.replan_lines.get(source, node)
            line = int(getattr(replan_node, "lineno", getattr(node, "lineno", 1)))
            replanner_id = f"replanner:{self.path}:{line}"
            self._add_node(
                replan_node,
                kind="replanner",
                node_id=replanner_id,
                claim_key="trace.replan",
                reason="A model-derived action is recomputed after an executable observation.",
            )
            self.graph.add_edge(
                source=self.latest_observation,
                target=replanner_id,
                kind="replans",
                evidence_ids=self.graph.nodes[replanner_id].evidence_ids,
            )

    @staticmethod
    def _target_names(target: ast.AST) -> list[str]:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names: list[str] = []
            for item in target.elts:
                names.extend(_PythonFlowAnalyzer._target_names(item))
            return names
        return []

    def _assign(self, target: ast.AST, flow: _Flow, node: ast.AST) -> None:
        for name in self._target_names(target):
            self.variables[name] = flow
            if _is_action_name(name) and flow.model_sources:
                self.action_selectors[name] = self._ensure_selector(node, flow.model_sources)
                self._ensure_replan(node, flow)
            elif _is_action_name(name):
                self.action_selectors.pop(name, None)

    def _process_call(self, node: ast.Call, *, capture_output: bool) -> _Flow:
        name = _call_name(node)
        arguments = (*node.args, *(keyword.value for keyword in node.keywords))
        if _is_model_call_name(name):
            for argument in arguments:
                self._process_expr(argument, capture_model_output=False)
            return self._add_model_call(node, capture_output=capture_output)

        if _is_dispatch_call_name(name):
            argument_flows = [
                self._process_expr(argument, capture_model_output=True)
                for argument in arguments
            ]
            flow = _merge_flow(*argument_flows)
            if not flow.model_sources:
                return _Flow()
            selector_ids: list[str] = []
            for argument, argument_flow in zip(arguments, argument_flows):
                if not argument_flow.model_sources:
                    continue
                if isinstance(argument, ast.Name) and argument.id in self.action_selectors:
                    selector_id = self.action_selectors[argument.id]
                else:
                    selector_id = self._ensure_selector(node, argument_flow.model_sources)
                if selector_id not in selector_ids:
                    selector_ids.append(selector_id)
            if not selector_ids:
                return _Flow()
            line = int(getattr(node, "lineno", 1))
            dispatcher_id = f"dispatcher:{self.path}:{line}"
            self._add_node(
                node,
                kind="dispatcher",
                node_id=dispatcher_id,
                claim_key="trace.dispatch",
                reason="A model-derived action value is passed to an executable tool dispatcher.",
            )
            for selector_id in selector_ids:
                self.graph.add_edge(
                    source=selector_id,
                    target=dispatcher_id,
                    kind="dispatches",
                    evidence_ids=self.graph.nodes[dispatcher_id].evidence_ids,
                )
            self._ensure_replan(node, flow)
            return _Flow(dispatch_sources=frozenset({dispatcher_id}))

        if _is_observation_call_name(name):
            argument_flows = [
                self._process_expr(argument, capture_model_output=False)
                for argument in arguments
            ]
            flow = _merge_flow(*argument_flows)
            if not flow.dispatch_sources:
                return _Flow()
            line = int(getattr(node, "lineno", 1))
            observation_id = f"observation:{self.path}:{line}"
            self._add_node(
                node,
                kind="observation",
                node_id=observation_id,
                claim_key="trace.observation",
                reason="A dispatcher result is retained by an executable observation call.",
            )
            for source in flow.dispatch_sources:
                self.graph.add_edge(
                    source=source,
                    target=observation_id,
                    kind="observes",
                    evidence_ids=self.graph.nodes[observation_id].evidence_ids,
                )
            self.latest_observation = observation_id
            return _Flow(observation_sources=frozenset({observation_id}))

        child_flows = [
            self._process_expr(argument, capture_model_output=capture_output)
            for argument in arguments
        ]
        return _merge_flow(*child_flows)

    def _process_expr(self, node: ast.AST | None, *, capture_model_output: bool) -> _Flow:
        if node is None:
            return _Flow()
        if isinstance(node, ast.Name):
            if _is_goal_name(node.id):
                self._add_goal(node)
            return self.variables.get(node.id, _Flow())
        if isinstance(node, ast.Call):
            return self._process_call(node, capture_output=capture_model_output)
        if isinstance(node, ast.Attribute):
            return self._process_expr(node.value, capture_model_output=False)
        if isinstance(node, ast.Subscript):
            return _merge_flow(
                self._process_expr(node.value, capture_model_output=False),
                self._process_expr(node.slice, capture_model_output=False),
            )
        if isinstance(node, ast.NamedExpr):
            flow = self._process_expr(node.value, capture_model_output=True)
            self._assign(node.target, flow, node)
            return flow
        if isinstance(node, ast.Constant):
            return _Flow()
        child_flows: list[_Flow] = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                child_flows.append(
                    self._process_expr(child, capture_model_output=capture_model_output)
                )
        return _merge_flow(*child_flows)

    def _process_block(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self._process_statement(statement)

    def _process_statement(self, statement: ast.stmt) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(statement, ast.Assign):
            flow = self._process_expr(statement.value, capture_model_output=True)
            for target in statement.targets:
                self._assign(target, flow, statement)
            return
        if isinstance(statement, ast.AnnAssign):
            flow = self._process_expr(statement.value, capture_model_output=True)
            self._assign(statement.target, flow, statement)
            return
        if isinstance(statement, ast.AugAssign):
            target_name = next(iter(self._target_names(statement.target)), "")
            flow = _merge_flow(
                self.variables.get(target_name, _Flow()),
                self._process_expr(statement.value, capture_model_output=True),
            )
            self._assign(statement.target, flow, statement)
            return
        if isinstance(statement, ast.Expr):
            self._process_expr(statement.value, capture_model_output=False)
            return
        if isinstance(statement, ast.Return):
            self._process_expr(statement.value, capture_model_output=False)
            self._add_termination(statement)
            return
        if isinstance(statement, (ast.Break, ast.Continue, ast.Raise)):
            self._add_termination(statement)
            return
        if isinstance(statement, ast.If):
            self._process_expr(statement.test, capture_model_output=False)
            self._process_block(statement.body)
            self._process_block(statement.orelse)
            return
        if isinstance(statement, (ast.While, ast.For, ast.AsyncFor)):
            self._add_loop(statement)
            if isinstance(statement, ast.While):
                self._process_expr(statement.test, capture_model_output=False)
            else:
                self._process_expr(statement.iter, capture_model_output=False)
                self._assign(statement.target, _Flow(), statement)
            self._process_block(statement.body)
            self._process_block(statement.orelse)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._process_expr(item.context_expr, capture_model_output=False)
                if item.optional_vars:
                    self._assign(item.optional_vars, _Flow(), item.context_expr)
            self._process_block(statement.body)
            return
        if isinstance(statement, ast.Try):
            self._process_block(statement.body)
            for handler in statement.handlers:
                if handler.type:
                    self._process_expr(handler.type, capture_model_output=False)
                self._process_block(handler.body)
            self._process_block(statement.orelse)
            self._process_block(statement.finalbody)
            return
        if isinstance(statement, ast.Match):
            self._process_expr(statement.subject, capture_model_output=False)
            for case in statement.cases:
                self._process_expr(case.guard, capture_model_output=False)
                self._process_block(case.body)
            return
        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.stmt):
                self._process_statement(child)
            elif isinstance(child, ast.expr):
                self._process_expr(child, capture_model_output=False)

    def run(self) -> None:
        if isinstance(self.scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = [
                *self.scope.args.posonlyargs,
                *self.scope.args.args,
                *self.scope.args.kwonlyargs,
            ]
            if self.scope.args.vararg:
                arguments.append(self.scope.args.vararg)
            if self.scope.args.kwarg:
                arguments.append(self.scope.args.kwarg)
            for argument in arguments:
                if _is_goal_name(argument.arg):
                    self._add_goal(self.scope)
                    break
            self._process_block(self.scope.body)
        elif isinstance(self.scope, ast.Module):
            self._process_block(self.scope.body)


def _mask_non_code(lines: list[str]) -> list[str]:
    """コメントと文字列を空白化し、lexical fallbackの誤検出を抑える。"""

    masked: list[str] = []
    block_comment = False
    quote: str | None = None
    for original in lines:
        output: list[str] = []
        index = 0
        while index < len(original):
            if block_comment:
                end = original.find("*/", index)
                if end < 0:
                    output.extend(" " for _ in original[index:])
                    index = len(original)
                else:
                    output.extend(" " for _ in original[index : end + 2])
                    index = end + 2
                    block_comment = False
                continue
            if quote:
                if original[index] == "\\":
                    output.append(" ")
                    if index + 1 < len(original):
                        output.append(" ")
                        index += 2
                    else:
                        index += 1
                elif original[index] == quote:
                    output.append(" ")
                    quote = None
                    index += 1
                else:
                    output.append(" ")
                    index += 1
                continue
            if original.startswith("/*", index):
                output.extend((" ", " "))
                block_comment = True
                index += 2
                continue
            if original.startswith("//", index) or original[index] == "#":
                output.extend(" " for _ in original[index:])
                index = len(original)
                continue
            if original[index] in {"'", '"', "`"}:
                quote = original[index]
                output.append(" ")
                index += 1
                continue
            output.append(original[index])
            index += 1
        masked.append("".join(output))
        if quote and not original.endswith("\\"):
            quote = None
    return masked


def _masked_line_hit(
    path: str,
    original_lines: list[str],
    masked_lines: list[str],
    pattern: re.Pattern[str],
    *,
    line_offset: int = 0,
) -> SearchHit | None:
    for line_no, line in enumerate(masked_lines, 1):
        if pattern.search(line):
            original = original_lines[line_no - 1] if line_no <= len(original_lines) else ""
            return SearchHit(path, line_no + line_offset, original)
    return None


def _connect_lexical_scope(
    *,
    path: str,
    lines: list[str],
    language: str,
    graph: FactGraph,
    ledger: EvidenceLedger,
    commit_sha: str,
    result: TraceResult,
    line_offset: int = 0,
) -> None:
    """非Pythonは候補のみ記録し、データフローedgeを単語の共起から推測しない。"""

    masked_lines = _mask_non_code(lines)
    model_hit = _masked_line_hit(
        path,
        lines,
        masked_lines,
        MODEL_CALL_TERMS,
        line_offset=line_offset,
    )
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
        reason=f"{language} lexical analysis found a model-call candidate.",
    )
    result.uncertainties.append(
        f"limited lexical data-flow for {language}: {path}; runtime edges were not inferred"
    )


def _python_tree(source: str) -> ast.Module | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return tree


def _python_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return sorted(
        [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ],
        key=lambda node: (node.lineno, getattr(node, "col_offset", 0)),
    )


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
            tree = _python_tree(source)
            if tree is None:
                result.uncertainties.append(f"Python AST unavailable for {record.path}")
                _connect_lexical_scope(
                    path=record.path,
                    lines=lines[:200],
                    language=record.language,
                    graph=graph,
                    ledger=ledger,
                    commit_sha=commit_sha,
                    result=result,
                )
            else:
                functions = _python_functions(tree)
                if functions:
                    for function in functions:
                        _PythonFlowAnalyzer(
                            path=record.path,
                            lines=lines,
                            graph=graph,
                            ledger=ledger,
                            commit_sha=commit_sha,
                            scope=function,
                            scope_name=function.name,
                        ).run()
                else:
                    _PythonFlowAnalyzer(
                        path=record.path,
                        lines=lines,
                        graph=graph,
                        ledger=ledger,
                        commit_sha=commit_sha,
                        scope=tree,
                        scope_name=record.path,
                    ).run()
        else:
            _connect_lexical_scope(
                path=record.path,
                lines=lines[:200],
                language=record.language,
                graph=graph,
                ledger=ledger,
                commit_sha=commit_sha,
                result=result,
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
