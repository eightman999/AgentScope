"""Pythonの限定的なinterprocedural data-flow解析。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from agentscope.acquisition.git_snapshot import Snapshot
from agentscope.analysis.control_flow import (
    _add_fact,
    _node_hit,
    rank_code_records,
)
from agentscope.analysis.inventory import FileRecord
from agentscope.analysis.path_priority import is_runtime_path, runtime_path_priority
from agentscope.domain.evidence import EvidenceLedger
from agentscope.domain.facts import FactGraph


@dataclass(frozen=True)
class FunctionInfo:
    """リポジトリ内で解決可能なPython関数の位置情報。"""

    key: str
    module: str
    path: str
    lines: tuple[str, ...]
    node: ast.FunctionDef | ast.AsyncFunctionDef
    qualname: str
    class_name: str | None
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class _SourceFile:
    path: str
    lines: tuple[str, ...]
    tree: ast.Module
    module: str
    imports: dict[str, str]


@dataclass(frozen=True)
class _Flow:
    model_sources: frozenset[str] = frozenset()
    dispatch_sources: frozenset[str] = frozenset()
    observation_sources: frozenset[str] = frozenset()
    replan_sources: frozenset[str] = frozenset()


def _merge(*flows: _Flow) -> _Flow:
    return _Flow(
        model_sources=frozenset(source for flow in flows for source in flow.model_sources),
        dispatch_sources=frozenset(source for flow in flows for source in flow.dispatch_sources),
        observation_sources=frozenset(
            source for flow in flows for source in flow.observation_sources
        ),
        replan_sources=frozenset(source for flow in flows for source in flow.replan_sources),
    )


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ""


def _call_name(node: ast.Call) -> str:
    return _unparse(node.func)


def _final_name(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower()


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    arguments = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    if node.args.vararg:
        arguments.append(node.args.vararg)
    if node.args.kwarg:
        arguments.append(node.args.kwarg)
    return tuple(argument.arg for argument in arguments)


def _module_name(path: str) -> str:
    return Path(path).with_suffix("").as_posix().replace("/", ".")


def _imports(tree: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                result[local] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                result[local] = f"{module}.{alias.name}" if module else alias.name
    return result


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, *, path: str, lines: tuple[str, ...], module: str) -> None:
        self.path = path
        self.lines = lines
        self.module = module
        self.scope: list[str] = []
        self.classes: list[str] = []
        self.functions: list[FunctionInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.classes.append(node.name)
        for child in node.body:
            self.visit(child)
        self.classes.pop()
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node)

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = ".".join([*self.scope, node.name])
        self.functions.append(
            FunctionInfo(
                key=f"{self.path}:{qualname}",
                module=self.module,
                path=self.path,
                lines=self.lines,
                node=node,
                qualname=qualname,
                class_name=".".join(self.classes) if self.classes else None,
                parameters=_parameters(node),
            )
        )
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()


class PythonFunctionIndex:
    """ファイル・関数・importを保持する小さなリポジトリ内index。"""

    def __init__(
        self,
        snapshot: Snapshot,
        records: list[FileRecord | object],
        *,
        uncertainties: list[str],
    ) -> None:
        self.snapshot = snapshot
        self.files: dict[str, _SourceFile] = {}
        self.functions: list[FunctionInfo] = []
        self.by_name: dict[str, list[FunctionInfo]] = {}
        self.uncertainties = uncertainties

        python_records = [
            record
            for record in records
            if getattr(record, "language", None) == "python"
            and is_runtime_path(str(getattr(record, "path", "")))
        ]
        for record in rank_code_records(python_records):
            path = str(getattr(record, "path", ""))
            source_path = snapshot.root / Path(path)
            try:
                source = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self.uncertainties.append(f"could not index Python file: {path}")
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                self.uncertainties.append(f"Python AST unavailable for interprocedural index: {path}")
                continue
            source_file = _SourceFile(
                path=path,
                lines=tuple(source.splitlines()),
                tree=tree,
                module=_module_name(path),
                imports=_imports(tree),
            )
            self.files[path] = source_file
            collector = _FunctionCollector(
                path=path,
                lines=source_file.lines,
                module=source_file.module,
            )
            collector.visit(tree)
            for info in collector.functions:
                self.functions.append(info)
                self.by_name.setdefault(info.node.name, []).append(info)
        self.functions.sort(
            key=lambda info: (
                -runtime_path_priority(info.path),
                info.path,
                info.node.lineno,
                getattr(info.node, "col_offset", 0),
            )
        )

    def resolve(self, call: ast.Call, caller: FunctionInfo) -> FunctionInfo | None:
        """単純なlocal/import/self呼び出しだけを解決する。"""

        func = call.func
        if isinstance(func, ast.Name):
            candidates = list(self.by_name.get(func.id, []))
            imported = self.files.get(caller.path)
            if imported and func.id in imported.imports:
                imported_candidates = self._module_candidates(imported.imports[func.id], func.id)
                if imported_candidates:
                    candidates = imported_candidates
            return self._choose(candidates, caller)

        if not isinstance(func, ast.Attribute):
            return None
        receiver = func.value
        method = func.attr
        if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"}:
            candidates = [
                info
                for info in self.by_name.get(method, [])
                if info.class_name == caller.class_name
            ]
            return self._choose(candidates, caller)

        if isinstance(receiver, ast.Name):
            imported = self.files.get(caller.path)
            if imported and receiver.id in imported.imports:
                candidates = self._module_candidates(imported.imports[receiver.id], method)
                return self._choose(candidates, caller)
            if any(
                term in receiver.id.lower()
                for term in ("model", "llm", "client", "openai", "anthropic", "ollama")
            ):
                return None

        # 任意のオブジェクト型を名前だけで推測すると、model.replan()を
        # 同名のlocal関数へ誤解決する。self/import以外は曖昧な
        # method callとして扱い、flow edgeを捏造しない。
        return None

    def _module_candidates(self, imported_name: str, name: str) -> list[FunctionInfo]:
        module_name = imported_name.rsplit(".", 1)[0] if "." in imported_name else imported_name
        return [
            info
            for info in self.by_name.get(name, [])
            if info.module == module_name
            or info.module.endswith(f".{module_name}")
            or info.module.endswith(f".{imported_name.rsplit('.', 1)[0]}")
        ]

    @staticmethod
    def _choose(candidates: list[FunctionInfo], caller: FunctionInfo) -> FunctionInfo | None:
        if not candidates:
            return None
        same_scope = [
            info
            for info in candidates
            if info.path == caller.path
            and (
                info.class_name == caller.class_name
                or info.qualname.rsplit(".", 1)[0] == caller.qualname.rsplit(".", 1)[0]
            )
        ]
        if len(same_scope) == 1:
            return same_scope[0]
        if len(candidates) == 1:
            return candidates[0]
        same_module = [info for info in candidates if info.module == caller.module]
        if len(same_module) == 1:
            return same_module[0]
        return None


def _is_model_call(name: str) -> bool:
    lower = name.lower()
    final = _final_name(lower)
    if final in {
        "create",
        "create_stream",
        "generate",
        "generate_stream",
        "complete",
        "acomplete",
        "completion",
        "chat",
        "invoke",
        "ainvoke",
        "request",
        "request_model",
        "model_request",
    }:
        receiver = lower.rsplit(".", 1)[0] if "." in lower else lower
        return bool(
            any(term in receiver for term in ("model", "llm", "openai", "anthropic", "ollama", "chat", "completion"))
            or receiver in {"model", "llm", "client"}
        )
    if final in {"model", "llm"} or lower.endswith("_model") or lower.endswith("_llm"):
        return True
    if final in {"choose_action", "select_action", "next_action", "replan", "predict", "decide"}:
        receiver = lower.rsplit(".", 1)[0] if "." in lower else ""
        return bool(any(term in receiver for term in ("model", "llm", "agent")))
    return bool(any(term in lower for term in ("model_request", "request_model", "llm_call")))


def _is_explicit_dispatch(name: str) -> bool:
    return _final_name(name) in {
        "dispatch",
        "execute_tool",
        "execute_tool_call",
        "run_tool",
        "call_tool",
        "dispatch_tool",
        "tool_registry",
        "tool_call",
        "tool_calls",
    }


def _is_dispatch(name: str, flow: _Flow, argument_text: str) -> bool:
    if not flow.model_sources:
        return False
    lower = name.lower()
    final = _final_name(lower)
    if _is_explicit_dispatch(lower):
        return True
    if final in {"send_message", "send_request"}:
        return True
    if final in {"execute", "run", "stream", "submit", "invoke", "ainvoke", "call"}:
        return bool(
            any(term in lower for term in ("tool", "agent", "executor", "workbench", "runner", "function"))
            or re_like_action(argument_text)
        )
    if final in {"tool", "agent", "executor", "runner"}:
        return True
    return False


def re_like_action(text: str) -> bool:
    lower = text.lower()
    return bool(
        any(
            token in lower
            for token in (
                "action",
                "tool_call",
                "toolcall",
                "function_call",
                "functioncall",
                "response.content",
                "chat_message",
                "message",
            )
        )
    )


def _is_explicit_observation(name: str) -> bool:
    final = _final_name(name)
    return final in {
        "observe",
        "record_observation",
        "observe_result",
        "process_tool_result",
        "handle_tool_result",
        "add_tool_result",
        "receive_observation",
    }


def _is_observation_constructor(name: str) -> bool:
    lower = _final_name(name)
    return any(
        term in lower
        for term in (
            "tooloutput",
            "toolresult",
            "toolreturn",
            "functionexecutionresult",
            "toolcallsummary",
            "resultmessage",
        )
    )


def _is_observation_name(name: str) -> bool:
    lower = name.lower()
    return bool(
        any(
            token in lower
            for token in ("observation", "feedback", "tool_result", "function_result", "result")
        )
    )


def _is_observation_sink(receiver: str, name: str) -> bool:
    lower = f"{receiver}.{name}".lower()
    return bool(any(token in lower for token in ("message", "history", "memory", "observation", "feedback", "result")))


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_target_names(item))
        return names
    return []


def _target_key(target: ast.AST) -> str:
    if isinstance(target, (ast.Name, ast.Attribute, ast.Subscript)):
        return _unparse(target)
    return ""


class _Engine:
    def __init__(
        self,
        *,
        index: PythonFunctionIndex,
        graph: FactGraph,
        ledger: EvidenceLedger,
        commit_sha: str,
        uncertainties: list[str],
    ) -> None:
        self.index = index
        self.graph = graph
        self.ledger = ledger
        self.commit_sha = commit_sha
        self.uncertainties = uncertainties
        self.cache: dict[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], _Flow] = {}
        self.active: set[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = set()
        self.invocations = 0
        self.max_invocations = 20_000
        self.max_depth = 8

    def analyze(self, info: FunctionInfo, inputs: dict[str, _Flow], stack: tuple[str, ...]) -> _Flow:
        signature = tuple(
            sorted(
                (
                    name,
                    tuple(
                        sorted(
                            (
                                *flow.model_sources,
                                *flow.dispatch_sources,
                                *flow.observation_sources,
                                *flow.replan_sources,
                            )
                        )
                    ),
                )
                for name, flow in inputs.items()
                if flow != _Flow()
            )
        )
        cache_key = (info.key, signature)
        if cache_key in self.cache:
            return self.cache[cache_key]
        if cache_key in self.active:
            self.uncertainties.append(f"recursive local call was not expanded: {info.key}")
            return _Flow()
        if len(stack) >= self.max_depth:
            self.uncertainties.append(f"interprocedural depth limit reached at: {info.key}")
            return _Flow()
        self.invocations += 1
        if self.invocations > self.max_invocations:
            self.uncertainties.append("interprocedural invocation budget exhausted")
            return _Flow()

        self.active.add(cache_key)
        run = _FunctionRun(engine=self, info=info, inputs=inputs, stack=(*stack, info.key))
        flow = run.run()
        self.active.remove(cache_key)
        self.cache[cache_key] = flow
        return flow

    def bind(self, call: ast.Call, caller: FunctionInfo, callee: FunctionInfo, flows: list[_Flow]) -> dict[str, _Flow]:
        parameters = list(callee.parameters)
        if callee.class_name and isinstance(call.func, ast.Attribute) and parameters:
            parameters = parameters[1:]
        bound: dict[str, _Flow] = {}
        for index, flow in enumerate(flows[: len(call.args)]):
            if index >= len(parameters):
                break
            bound[parameters[index]] = flow
        for offset, keyword in enumerate(call.keywords, start=len(call.args)):
            if keyword.arg is None or keyword.arg not in parameters:
                continue
            if offset < len(flows):
                bound[keyword.arg] = flows[offset]
        return bound

    def add_function_node(self, info: FunctionInfo) -> str:
        node_id = f"function:{info.key}"
        _add_fact(
            graph=self.graph,
            ledger=self.ledger,
            hit=_node_hit(info.path, list(info.lines), info.node),
            kind="function",
            node_id=node_id,
            claim_key="trace.function",
            commit_sha=self.commit_sha,
            reason="A repository-local Python function participates in the interprocedural call graph.",
        )
        return node_id

    def add_call_edge(self, caller: FunctionInfo, call: ast.Call, callee: FunctionInfo) -> None:
        source_id = self.add_function_node(caller)
        target_id = self.add_function_node(callee)
        hit = _node_hit(caller.path, list(caller.lines), call)
        evidence = self.ledger.add(
            claim_key="trace.call",
            source_kind="repository",
            file=hit.path,
            start_line=hit.line,
            end_line=hit.line,
            excerpt=hit.text,
            commit_sha=self.commit_sha,
            reason="A repository-local call site was resolved to a concrete function target.",
            confidence="medium",
        )
        self.graph.add_edge(
            source=source_id,
            target=target_id,
            kind="calls",
            evidence_ids=[evidence.id],
        )

    def add_node(
        self,
        info: FunctionInfo,
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
            hit=_node_hit(info.path, list(info.lines), node),
            kind=kind,
            node_id=node_id,
            claim_key=claim_key,
            commit_sha=self.commit_sha,
            reason=reason,
        )


class _FunctionRun:
    def __init__(
        self,
        *,
        engine: _Engine,
        info: FunctionInfo,
        inputs: dict[str, _Flow],
        stack: tuple[str, ...],
    ) -> None:
        self.engine = engine
        self.info = info
        self.stack = stack
        self.variables: dict[str, _Flow] = {"self": inputs.get("self", _Flow()), **inputs}
        self.action_selectors: dict[str, str] = {}
        self.latest_observations: set[str] = {
            source for flow in inputs.values() for source in flow.observation_sources
        }
        self.return_flow = _Flow()
        self.side_model_sources: set[str] = set()
        self.side_dispatch_sources: set[str] = set()
        self.side_observation_sources: set[str] = set()
        self.side_replan_sources: set[str] = set()
        self.has_loop = False

    def run(self) -> _Flow:
        for statement in self.info.node.body:
            self._statement(statement)
        return _merge(
            self.return_flow,
            _Flow(
                model_sources=frozenset(self.side_model_sources),
                dispatch_sources=frozenset(self.side_dispatch_sources),
                observation_sources=frozenset(self.side_observation_sources),
                replan_sources=frozenset(self.side_replan_sources),
            ),
        )

    def _node(self, node: ast.AST, *, kind: str, node_id: str, claim_key: str, reason: str) -> None:
        self.engine.add_node(
            self.info,
            node,
            kind=kind,
            node_id=node_id,
            claim_key=claim_key,
            reason=reason,
        )

    def _selector(self, node: ast.AST, sources: frozenset[str]) -> str:
        selector_id = f"action_selector:{self.info.path}:{getattr(node, 'lineno', 1)}"
        self._node(
            node,
            kind="action_selector",
            node_id=selector_id,
            claim_key="trace.action_selector",
            reason="A model-derived value is used as an action-selection candidate across a function boundary.",
        )
        for source in sources:
            self.engine.graph.add_edge(
                source=source,
                target=selector_id,
                kind="controls",
                evidence_ids=self.engine.graph.nodes[selector_id].evidence_ids,
            )
        return selector_id

    def _replan(self, node: ast.AST, model_sources: frozenset[str], observations: set[str]) -> frozenset[str]:
        if not model_sources or not observations:
            return frozenset()
        replanner_id = f"replanner:{self.info.path}:{getattr(node, 'lineno', 1)}"
        self._node(
            node,
            kind="replanner",
            node_id=replanner_id,
            claim_key="trace.replan",
            reason="A model-controlled step is repeated after an executable observation.",
        )
        for observation_id in observations:
            self.engine.graph.add_edge(
                source=observation_id,
                target=replanner_id,
                kind="replans",
                evidence_ids=self.engine.graph.nodes[replanner_id].evidence_ids,
            )
        self.side_replan_sources.update(model_sources)
        return model_sources

    def _observe(self, node: ast.AST, flow: _Flow) -> _Flow:
        if not flow.dispatch_sources:
            return flow
        observation_id = f"observation:{self.info.path}:{getattr(node, 'lineno', 1)}"
        self._node(
            node,
            kind="observation",
            node_id=observation_id,
            claim_key="trace.observation",
            reason="A model-controlled dispatcher result reaches an executable observation boundary.",
        )
        for source in flow.dispatch_sources:
            self.engine.graph.add_edge(
                source=source,
                target=observation_id,
                kind="observes",
                evidence_ids=self.engine.graph.nodes[observation_id].evidence_ids,
            )
        self.latest_observations.add(observation_id)
        self.side_observation_sources.add(observation_id)
        return _merge(flow, _Flow(observation_sources=frozenset({observation_id})))

    def _model(self, node: ast.Call, *, capture: bool, argument_flow: _Flow) -> _Flow:
        line = int(getattr(node, "lineno", 1))
        column = int(getattr(node, "col_offset", 0))
        model_id = f"model_call:{self.info.path}:{line}:{column}"
        self._node(
            node,
            kind="model_call",
            node_id=model_id,
            claim_key="trace.model_call",
            reason=f"{self.info.qualname} contains an executable model/API call candidate.",
        )
        if argument_flow.dispatch_sources:
            argument_flow = self._observe(node, argument_flow)
        if not capture:
            return _Flow()
        output_id = f"model_output:{self.info.path}:{line}:{column}"
        self._node(
            node,
            kind="model_output",
            node_id=output_id,
            claim_key="trace.model_output",
            reason="The model/API result is consumed by an enclosing expression.",
        )
        self.engine.graph.add_edge(
            source=model_id,
            target=output_id,
            kind="returns",
            evidence_ids=self.engine.graph.nodes[output_id].evidence_ids,
        )
        self.side_model_sources.add(output_id)
        replan_sources: frozenset[str] = frozenset()
        if self.latest_observations:
            replan_sources = self._replan(node, frozenset({output_id}), self.latest_observations)
        return _Flow(model_sources=frozenset({output_id}), replan_sources=replan_sources)

    def _dispatch(
        self,
        node: ast.Call,
        flow: _Flow,
        arguments: list[ast.AST],
        argument_flows: list[_Flow],
    ) -> _Flow:
        selector_ids: list[str] = []
        for argument, argument_flow in zip(arguments, argument_flows):
            if not argument_flow.model_sources:
                continue
            text = _unparse(argument)
            if isinstance(argument, ast.Name) and argument.id in self.action_selectors:
                selector_id = self.action_selectors[argument.id]
            else:
                selector_id = self._selector(node, argument_flow.model_sources)
            if selector_id not in selector_ids:
                selector_ids.append(selector_id)
        if not selector_ids:
            return _Flow()
        dispatcher_id = f"dispatcher:{self.info.path}:{getattr(node, 'lineno', 1)}"
        self._node(
            node,
            kind="dispatcher",
            node_id=dispatcher_id,
            claim_key="trace.dispatch",
            reason="A model-derived action reaches an executable tool/agent dispatcher.",
        )
        for selector_id in selector_ids:
            self.engine.graph.add_edge(
                source=selector_id,
                target=dispatcher_id,
                kind="dispatches",
                evidence_ids=self.engine.graph.nodes[dispatcher_id].evidence_ids,
            )
        self.side_dispatch_sources.add(dispatcher_id)
        return _Flow(dispatch_sources=frozenset({dispatcher_id}))

    def _expr(self, node: ast.AST | None, *, capture: bool) -> _Flow:
        if node is None:
            return _Flow()
        if isinstance(node, ast.Name):
            return self.variables.get(node.id, _Flow())
        if isinstance(node, ast.Call):
            return self._call(node, capture=capture)
        if isinstance(node, ast.Attribute):
            key = _unparse(node)
            return _merge(self.variables.get(key, _Flow()), self._expr(node.value, capture=False))
        if isinstance(node, ast.Subscript):
            return _merge(
                self._expr(node.value, capture=False),
                self._expr(node.slice, capture=False),
            )
        if isinstance(node, ast.NamedExpr):
            flow = self._expr(node.value, capture=True)
            self._assign(node.target, flow, node)
            return flow
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            flow_parts: list[_Flow] = []
            for generator in node.generators:
                iterable_flow = self._expr(generator.iter, capture=False)
                self._assign(generator.target, iterable_flow, generator)
                flow_parts.append(iterable_flow)
                for condition in generator.ifs:
                    flow_parts.append(self._expr(condition, capture=False))
            flow_parts.append(self._expr(node.elt, capture=capture))
            return _merge(*flow_parts)
        if isinstance(node, ast.DictComp):
            flow_parts = []
            for generator in node.generators:
                iterable_flow = self._expr(generator.iter, capture=False)
                self._assign(generator.target, iterable_flow, generator)
                flow_parts.append(iterable_flow)
                flow_parts.extend(self._expr(condition, capture=False) for condition in generator.ifs)
            flow_parts.extend(
                (self._expr(node.key, capture=capture), self._expr(node.value, capture=capture))
            )
            return _merge(*flow_parts)
        if isinstance(node, ast.Constant):
            return _Flow()
        return _merge(
            *(
                self._expr(child, capture=capture)
                for child in ast.iter_child_nodes(node)
                if isinstance(child, ast.expr)
            )
        )

    def _call(self, node: ast.Call, *, capture: bool) -> _Flow:
        name = _call_name(node)
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        argument_flows = [self._expr(argument, capture=True) for argument in arguments]
        receiver = _unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
        receiver_flow = (
            self._expr(node.func.value, capture=False)
            if isinstance(node.func, ast.Attribute)
            else _Flow()
        )
        # values()/items()/iter() 等のコンテナ操作では、model-derived valueが
        # 引数ではなくreceiver側にある。ここを引き継がないと、コンテナ経由の
        # tool callを「固定値」と誤認してしまう。
        argument_flow = _merge(receiver_flow, *argument_flows)
        argument_text = " ".join(_unparse(argument) for argument in arguments)

        # tool(...) のようにmodel outputからlookupしたcallableは、
        # local関数名と衝突し得るためresolverより先にdispatchとする。
        if (
            isinstance(node.func, ast.Name)
            and node.func.id.lower() in {"tool", "agent", "executor", "runner"}
            and argument_flow.model_sources
        ):
            return self._dispatch(node, argument_flow, arguments, argument_flows)

        if _is_model_call(name):
            return self._model(node, capture=capture, argument_flow=argument_flow)

        if _is_dispatch(name, argument_flow, argument_text):
            return self._dispatch(node, argument_flow, arguments, argument_flows)

        callee = self.engine.index.resolve(node, self.info)
        if callee is not None:
            self.engine.add_call_edge(self.info, node, callee)
            inputs = self.engine.bind(node, self.info, callee, argument_flows)
            callee_flow = self.engine.analyze(callee, inputs, self.stack)
            if self.has_loop and callee_flow.model_sources and callee_flow.observation_sources:
                self._replan(node, callee_flow.model_sources, set(callee_flow.observation_sources))
            self.latest_observations.update(callee_flow.observation_sources)
            return callee_flow

        if _is_explicit_observation(name):
            return self._observe(node, argument_flow)

        if _is_observation_constructor(name) and argument_flow.dispatch_sources:
            return self._observe(node, argument_flow)

        final = _final_name(name)
        if final in {"append", "extend", "add", "update", "setdefault"}:
            receiver_flow = (
                self._expr(node.func.value, capture=False)
                if isinstance(node.func, ast.Attribute)
                else _Flow()
            )
            merged = _merge(receiver_flow, argument_flow)
            receiver_name = receiver or ""
            if merged.dispatch_sources and _is_observation_sink(receiver_name, final):
                merged = self._observe(node, merged)
            if receiver_name:
                self.variables[receiver_name] = merged
            return merged

        if argument_flow.dispatch_sources and _is_observation_sink(receiver, final):
            return self._observe(node, argument_flow)
        return argument_flow

    def _assign(self, target: ast.AST, flow: _Flow, node: ast.AST) -> None:
        names = _target_names(target)
        if names:
            for name in names:
                assigned = flow
                if flow.dispatch_sources and _is_observation_name(name):
                    assigned = self._observe(node, flow)
                self.variables[name] = assigned
                if assigned.model_sources and _is_action_name(name):
                    selector_id = self.action_selectors.get(name)
                    if selector_id is None:
                        selector_id = self._selector(node, assigned.model_sources)
                    self.action_selectors[name] = selector_id
        else:
            key = _target_key(target)
            if key:
                assigned = flow
                if flow.dispatch_sources and _is_observation_name(key):
                    assigned = self._observe(node, flow)
                self.variables[key] = assigned
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    self.variables[target.value.id] = _merge(
                        self.variables.get(target.value.id, _Flow()),
                        assigned,
                    )

    def _statement(self, statement: ast.stmt) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(statement, ast.Assign):
            flow = self._expr(statement.value, capture=True)
            for target in statement.targets:
                self._assign(target, flow, statement)
            return
        if isinstance(statement, ast.AnnAssign):
            self._assign(statement.target, self._expr(statement.value, capture=True), statement)
            return
        if isinstance(statement, ast.AugAssign):
            key = _target_key(statement.target)
            flow = _merge(self.variables.get(key, _Flow()), self._expr(statement.value, capture=True))
            self._assign(statement.target, flow, statement)
            return
        if isinstance(statement, ast.Expr):
            self._expr(statement.value, capture=False)
            return
        if isinstance(statement, ast.Return):
            self.return_flow = _merge(self.return_flow, self._expr(statement.value, capture=True))
            return
        if isinstance(statement, (ast.Break, ast.Continue, ast.Raise)):
            return
        if isinstance(statement, ast.If):
            self._expr(statement.test, capture=False)
            for child in statement.body:
                self._statement(child)
            for child in statement.orelse:
                self._statement(child)
            return
        if isinstance(statement, (ast.While, ast.For, ast.AsyncFor)):
            self.has_loop = True
            if isinstance(statement, ast.While):
                self._expr(statement.test, capture=False)
            else:
                self._assign(statement.target, self._expr(statement.iter, capture=False), statement)
            for child in statement.body:
                self._statement(child)
            for child in statement.orelse:
                self._statement(child)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                flow = self._expr(item.context_expr, capture=True)
                if item.optional_vars:
                    self._assign(item.optional_vars, flow, item.context_expr)
            for child in statement.body:
                self._statement(child)
            return
        if isinstance(statement, ast.Try):
            for child in statement.body:
                self._statement(child)
            for handler in statement.handlers:
                if handler.type:
                    self._expr(handler.type, capture=False)
                for child in handler.body:
                    self._statement(child)
            for child in statement.orelse:
                self._statement(child)
            for child in statement.finalbody:
                self._statement(child)
            return
        if isinstance(statement, ast.Match):
            self._expr(statement.subject, capture=False)
            for case in statement.cases:
                self._expr(case.guard, capture=False)
                for child in case.body:
                    self._statement(child)
            return
        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.stmt):
                self._statement(child)
            elif isinstance(child, ast.expr):
                self._expr(child, capture=False)


def _is_action_name(name: str) -> bool:
    lower = name.lower()
    return bool(
        lower in {"action", "tool_call", "toolcall", "function_call", "functioncall"}
        or any(lower.startswith(prefix) or lower.endswith(prefix) for prefix in ("action_", "tool_call_", "function_call_"))
    )


def _function_signal(info: FunctionInfo) -> bool:
    for node in ast.walk(info.node):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if _is_model_call(name) or _is_explicit_dispatch(name) or _is_explicit_observation(name):
            return True
    return bool(
        any(
            token in info.qualname.lower()
            for token in ("agent", "model", "llm", "tool", "executor", "runner", "loop", "graph", "step")
        )
    )


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _simple_string_aliases(tree: ast.Module) -> dict[str, set[str]]:
    """graphのentrypoint等に使われる単純な文字列aliasだけを解決する。"""

    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = _literal_string(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.setdefault(target.id, set()).add(value)
        elif isinstance(node, ast.AnnAssign):
            value = _literal_string(node.value)
            if value is not None and isinstance(node.target, ast.Name):
                aliases.setdefault(node.target.id, set()).add(value)
    return aliases


def _referenced_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
    }


def _function_has_model_call(info: FunctionInfo) -> bool:
    return any(
        isinstance(node, ast.Call) and _is_model_call(_call_name(node))
        for node in ast.walk(info.node)
    )


def _function_has_tool_call_state(info: FunctionInfo) -> bool:
    for node in ast.walk(info.node):
        if isinstance(node, ast.Attribute) and node.attr in {"tool_call", "tool_calls"}:
            return True
        if isinstance(node, ast.Name) and node.id.lower() in {
            "tool_call",
            "tool_calls",
            "function_call",
            "function_calls",
        }:
            return True
    return False


def _model_node_ids_for_path(
    graph: FactGraph,
    ledger: EvidenceLedger,
    path: str,
) -> list[str]:
    result: list[str] = []
    for node in graph.nodes.values():
        if node.kind not in {"model_call", "model_output"}:
            continue
        if any(ledger.get(evidence_id).file == path for evidence_id in node.evidence_ids):
            result.append(node.id)
    return result


def _add_framework_node(
    *,
    source_file: _SourceFile,
    node: ast.AST,
    graph: FactGraph,
    ledger: EvidenceLedger,
    commit_sha: str,
    node_id: str,
    kind: str,
    claim_key: str,
    reason: str,
) -> None:
    _add_fact(
        graph=graph,
        ledger=ledger,
        hit=_node_hit(source_file.path, list(source_file.lines), node),
        kind=kind,
        node_id=node_id,
        claim_key=claim_key,
        commit_sha=commit_sha,
        reason=reason,
    )


def _trace_graph_executor_contracts(
    *,
    index: PythonFunctionIndex,
    graph: FactGraph,
    ledger: EvidenceLedger,
    commit_sha: str,
) -> None:
    """graph builderとexecutorの抽象化を、明示された配線だけで追う。

    LangGraph系の実装では、modelを呼ぶnode、tool node、conditional route、
    graph edgeが別の関数・別の抽象化層に分かれる。ここでは「tool_callsを
    検査するrouteがmodel nodeからtool nodeへ分岐し、tool nodeからentrypoint
    へ戻る」という契約を証拠付きで復元する。文字列の共起だけでは契約を
    成立させず、同一Python module内の実行可能AST配線を要求する。
    """

    for source_file in index.files.values():
        calls = [node for node in ast.walk(source_file.tree) if isinstance(node, ast.Call)]
        function_infos = [info for info in index.functions if info.path == source_file.path]
        model_function_names = {
            info.node.name for info in function_infos if _function_has_model_call(info)
        }
        route_functions = {
            info.node.name: info
            for info in function_infos
            if _function_has_tool_call_state(info)
        }
        if not model_function_names or not route_functions:
            continue

        aliases = _simple_string_aliases(source_file.tree)
        graph_nodes: dict[str, tuple[ast.Call, set[str]]] = {}
        model_graph_nodes: set[str] = set()
        tool_graph_nodes: set[str] = set()
        edge_calls: list[tuple[ast.Call, str, set[str]]] = []
        conditional_calls: list[tuple[ast.Call, str, set[str]]] = []

        for call in calls:
            final = _final_name(_call_name(call))
            if final == "add_node" and len(call.args) >= 2:
                label = _literal_string(call.args[0])
                if label is None:
                    continue
                names = _referenced_names(call.args[1])
                graph_nodes[label] = (call, names)
                lower_label = label.lower()
                lower_names = {name.lower() for name in names}
                if (
                    any(token in lower_label for token in ("tool", "executor", "dispatch"))
                    or any(
                        any(token in name for token in ("tool", "executor", "dispatch"))
                        for name in lower_names
                    )
                ):
                    tool_graph_nodes.add(label)
                if (
                    any(token in lower_label for token in ("agent", "model", "llm"))
                    or names & model_function_names
                ):
                    model_graph_nodes.add(label)
            elif final == "add_edge" and len(call.args) >= 2:
                source = _literal_string(call.args[0])
                if source is None:
                    continue
                target = _literal_string(call.args[1])
                targets = {target} if target is not None else set()
                if isinstance(call.args[1], ast.Name):
                    targets.update(aliases.get(call.args[1].id, set()))
                edge_calls.append((call, source, targets))
            elif final == "add_conditional_edges" and len(call.args) >= 2:
                source = _literal_string(call.args[0])
                if source is None:
                    continue
                route_names = _referenced_names(call.args[1])
                conditional_calls.append((call, source, route_names))

        if not model_graph_nodes or not tool_graph_nodes or not conditional_calls:
            continue
        loop_calls = [
            (call, source, targets)
            for call, source, targets in edge_calls
            if source in tool_graph_nodes
            and targets & (model_graph_nodes | set(aliases) | {"agent", "model"})
        ]
        if not loop_calls:
            continue

        model_ids = _model_node_ids_for_path(graph, ledger, source_file.path)
        if not model_ids:
            continue
        for conditional_call, source, route_names in conditional_calls:
            if source not in model_graph_nodes:
                continue
            route_has_tool_state = any(name in route_functions for name in route_names)
            if not route_has_tool_state:
                continue
            loop_call, _, _ = loop_calls[0]
            line = int(getattr(conditional_call, "lineno", 1))
            selector_id = f"framework_action_selector:{source_file.path}:{line}"
            _add_framework_node(
                source_file=source_file,
                node=conditional_call,
                graph=graph,
                ledger=ledger,
                commit_sha=commit_sha,
                node_id=selector_id,
                kind="action_selector",
                claim_key="trace.framework_action_selector",
                reason="A graph conditional route inspects model tool-call state before selecting a tool node.",
            )
            selector_evidence = graph.nodes[selector_id].evidence_ids
            for model_id in model_ids:
                graph.add_edge(
                    source=model_id,
                    target=selector_id,
                    kind="controls",
                    evidence_ids=selector_evidence,
                )
            dispatcher_id = f"framework_dispatcher:{source_file.path}:{line}"
            _add_framework_node(
                source_file=source_file,
                node=conditional_call,
                graph=graph,
                ledger=ledger,
                commit_sha=commit_sha,
                node_id=dispatcher_id,
                kind="dispatcher",
                claim_key="trace.framework_dispatch",
                reason="The graph route sends model tool-call state to a registered tool/executor node.",
            )
            dispatcher_evidence = graph.nodes[dispatcher_id].evidence_ids
            graph.add_edge(
                source=selector_id,
                target=dispatcher_id,
                kind="dispatches",
                evidence_ids=dispatcher_evidence,
            )
            observation_line = int(getattr(loop_call, "lineno", 1))
            observation_id = f"framework_observation:{source_file.path}:{observation_line}"
            _add_framework_node(
                source_file=source_file,
                node=loop_call,
                graph=graph,
                ledger=ledger,
                commit_sha=commit_sha,
                node_id=observation_id,
                kind="observation",
                claim_key="trace.framework_observation",
                reason="A graph edge returns from the tool node to the model entrypoint after tool execution.",
            )
            observation_evidence = graph.nodes[observation_id].evidence_ids
            graph.add_edge(
                source=dispatcher_id,
                target=observation_id,
                kind="observes",
                evidence_ids=observation_evidence,
            )
            replanner_id = f"framework_replanner:{source_file.path}:{observation_line}"
            _add_framework_node(
                source_file=source_file,
                node=loop_call,
                graph=graph,
                ledger=ledger,
                commit_sha=commit_sha,
                node_id=replanner_id,
                kind="replanner",
                claim_key="trace.framework_replan",
                reason="The graph edge feeds the tool result back into the model entrypoint for another step.",
            )
            graph.add_edge(
                source=observation_id,
                target=replanner_id,
                kind="replans",
                evidence_ids=graph.nodes[replanner_id].evidence_ids,
            )


def trace_python_interprocedural(
    snapshot: Snapshot,
    records: list[FileRecord | object],
    ledger: EvidenceLedger,
    graph: FactGraph,
    *,
    commit_sha: str,
    uncertainties: list[str],
    target_path: str | None = None,
) -> set[str]:
    """runtime優先の関数indexを作り、local call/data-flowをFactGraphへ追加する。"""

    index = PythonFunctionIndex(snapshot, records, uncertainties=uncertainties)
    engine = _Engine(
        index=index,
        graph=graph,
        ledger=ledger,
        commit_sha=commit_sha,
        uncertainties=uncertainties,
    )
    relevant: set[str] = {
        info.key for info in index.functions if _function_signal(info)
    }
    changed = True
    while changed:
        changed = False
        for info in index.functions:
            if info.key in relevant:
                continue
            for node in ast.walk(info.node):
                if not isinstance(node, ast.Call):
                    continue
                callee = index.resolve(node, info)
                if callee is not None and callee.key in relevant:
                    relevant.add(info.key)
                    changed = True
                    break

    analyzed_paths: set[str] = set()
    entries = [info for info in index.functions if info.key in relevant]
    if target_path:
        entries = [info for info in entries if info.path == target_path]
    for info in entries:
        engine.analyze(info, {}, ())
        analyzed_paths.add(info.path)

    _trace_graph_executor_contracts(
        index=index,
        graph=graph,
        ledger=ledger,
        commit_sha=commit_sha,
    )

    return analyzed_paths
