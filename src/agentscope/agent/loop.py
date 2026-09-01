"""modelがtoolを選択するAgent loop。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.agent.action import Action, ActionValidationError, parse_action
from agentscope.agent.policy import check_finish, missing_capabilities
from agentscope.agent.prompt import build_model_context
from agentscope.agent.tools import AuditToolContext, ToolRegistry, ToolValidationError
from agentscope.domain.state import ActionRecord
from agentscope.domain.unknowns import add_model_output_integrity_evidence
from agentscope.model.provider import ModelContext, ModelProvider, ModelProviderError


@dataclass
class AgentLoopResult:
    context: AuditToolContext
    events: list[dict[str, Any]]


class AgentLoop:
    def __init__(
        self,
        *,
        context: AuditToolContext,
        provider: ModelProvider,
        registry: ToolRegistry,
        artifacts: ArtifactStore,
    ) -> None:
        self.context = context
        self.provider = provider
        self.registry = registry
        self.artifacts = artifacts
        self.events: list[dict[str, Any]] = []

    def _persist(self) -> None:
        self.artifacts.write_json("state.json", self.context.state.to_dict())
        self.artifacts.write_jsonl("audit_trace.jsonl", self.events)

    def _event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self._persist()

    def _model_context(self, prompt_suffix: str = "") -> ModelContext:
        facts = dict(self.context.facts)
        facts["missing_capabilities"] = missing_capabilities(self.context.facts)
        state = self.context.state.to_dict()
        state["missing_capabilities"] = facts["missing_capabilities"]
        state["readable_paths"] = self.context.inventory.paths()[:120]
        model_context = build_model_context(
            state=state,
            tool_catalog=self.registry.catalog(),
            observations=self.context.state.observations,
            facts=facts,
        )
        if prompt_suffix:
            return ModelContext(
                prompt=model_context.prompt + "\n\n" + prompt_suffix,
                state=model_context.state,
                tool_catalog=model_context.tool_catalog,
            )
        return model_context

    def _mark_evaluation_unknown(self, reason: str) -> None:
        safe_reason = " ".join(str(reason).split())[:500]
        evidence_id = add_model_output_integrity_evidence(
            ledger=self.context.ledger,
            artifacts=self.artifacts,
            commit_sha=self.context.state.commit_sha,
            reason=safe_reason,
        )
        self.context.facts["evaluation_unknown"] = True
        evidence_ids = self.context.facts.setdefault(
            "evaluation_unknown_evidence_ids", []
        )
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
        unknown = f"Model output integrity failure: {safe_reason}"
        if unknown not in self.context.state.unknowns:
            self.context.state.unknowns.append(unknown)

    @staticmethod
    def _has_suspicious_evaluation_fields(raw: Any) -> bool:
        candidate = raw
        if isinstance(raw, str):
            try:
                candidate = json.loads(raw)
            except json.JSONDecodeError:
                return False
        if not isinstance(candidate, dict):
            return False
        return bool(
            set(candidate)
            & {
                "evidence_id",
                "evidence_ids",
                "score",
                "scores",
                "classification",
                "classifications",
            }
        )

    def _call_and_validate(self) -> Action | None:
        base_context = self._model_context()
        try:
            raw = self.provider.complete_action(base_context)
        except ModelProviderError as exc:
            self._mark_evaluation_unknown(f"model provider failed: {exc}")
            self._event(
                {
                    "event": "model_error",
                    "step": len(self.context.state.action_history) + 1,
                    "error": str(exc),
                }
            )
            self.context.state.termination = "FAILED"
            self.context.state.status = "failed"
            return None
        try:
            action = parse_action(raw)
        except ActionValidationError as exc:
            if self._has_suspicious_evaluation_fields(raw):
                self._mark_evaluation_unknown(
                    f"model action contained evaluation fields rejected by schema: {exc}"
                )
                self.context.state.termination = "INSUFFICIENT_EVIDENCE"
                self.context.state.status = "completed"
                self._event(
                    {
                        "event": "model_output_integrity_rejected",
                        "step": len(self.context.state.action_history) + 1,
                        "attempt": 1,
                        "error": str(exc),
                    }
                )
                return None
            self._event(
                {
                    "event": "model_action_rejected",
                    "step": len(self.context.state.action_history) + 1,
                    "attempt": 1,
                    "raw": raw if isinstance(raw, (dict, str, list, int, float, bool)) else str(raw),
                    "error": str(exc),
                }
            )
            retry_context = self._model_context(
                "前回のactionはschema検証で拒否されました。修正理由: "
                + str(exc)
                + "。今回だけstrict JSONで再出力してください。"
            )
            try:
                retry_raw = self.provider.complete_action(retry_context)
            except ModelProviderError as retry_exc:
                self._mark_evaluation_unknown(
                    f"model provider failed after schema retry: {retry_exc}"
                )
                self._event(
                    {
                        "event": "model_error",
                        "step": len(self.context.state.action_history) + 1,
                        "attempt": 2,
                        "error": str(retry_exc),
                    }
                )
                self.context.state.termination = "FAILED"
                self.context.state.status = "failed"
                return None
            try:
                action = parse_action(retry_raw)
            except ActionValidationError as retry_exc:
                self._mark_evaluation_unknown(
                    f"model action remained invalid after one retry: {retry_exc}"
                )
                self._event(
                    {
                        "event": "model_action_rejected",
                        "step": len(self.context.state.action_history) + 1,
                        "attempt": 2,
                        "raw": (
                            retry_raw
                            if isinstance(retry_raw, (dict, str, list, int, float, bool))
                            else str(retry_raw)
                        ),
                        "error": str(retry_exc),
                    }
                )
                self.context.state.termination = "FAILED"
                self.context.state.status = "failed"
                return None
            self._event(
                {
                    "event": "model_action_accepted",
                    "step": len(self.context.state.action_history) + 1,
                    "attempt": 2,
                    "action": action.raw,
                }
            )
            return action
        self._event(
            {
                "event": "model_action_accepted",
                "step": len(self.context.state.action_history) + 1,
                "attempt": 1,
                "action": action.raw,
            }
        )
        return action

    def _record_action(
        self,
        *,
        step: int,
        action: Action,
        result: str,
    ) -> None:
        self.context.state.action_history.append(
            ActionRecord(
                step=step,
                kind=action.kind,
                tool=action.tool,
                arguments=action.arguments,
                result=result[:2000],
                selected_by_model=True,
            )
        )

    def _handle_finish(self, action: Action, step: int) -> bool:
        check = check_finish(self.context.facts, action.decision or "")
        missing = sorted(set(check.missing) | set(action.missing_unknowns))
        if action.decision == "ENOUGH_EVIDENCE" and not check.accepted:
            message = (
                "ENOUGH_EVIDENCE rejected by controller; missing capabilities: "
                + ", ".join(missing)
            )
            self.context.state.add_observation(message)
            self.context.state.unknowns.extend(
                item for item in missing if item not in self.context.state.unknowns
            )
            self._record_action(step=step, action=action, result=message)
            self._event(
                {
                    "event": "finish_rejected",
                    "step": step,
                    "decision": action.decision,
                    "missing": missing,
                }
            )
            return False
        self.context.state.termination = action.decision
        self.context.state.status = "completed"
        self._record_action(step=step, action=action, result=action.reason)
        self._event(
            {
                "event": "finish_accepted",
                "step": step,
                "decision": action.decision,
                "reason": action.reason,
                "missing": missing,
            }
        )
        return True

    def run(self) -> AgentLoopResult:
        self._persist()
        while self.context.state.budget_remaining > 0 and not self.context.state.termination:
            step = len(self.context.state.action_history) + 1
            action = self._call_and_validate()
            if action is None:
                break
            if action.kind == "finish":
                self.context.state.budget_remaining -= 1
                if self._handle_finish(action, step):
                    self._persist()
                    break
                if self.context.state.budget_remaining <= 0:
                    self.context.state.termination = "INSUFFICIENT_EVIDENCE"
                    self.context.state.status = "completed"
                    self._event(
                        {
                            "event": "budget_exhausted",
                            "step": step,
                            "missing": missing_capabilities(self.context.facts),
                        }
                    )
                self._persist()
                continue
            try:
                result = self.registry.call(action.tool or "", action.arguments)
                self.context.state.add_evidence_ids(result.evidence_ids)
                self.context.state.add_observation(result.observation[:6000])
                result_text = result.observation
                self._event(
                    {
                        "event": "tool_result",
                        "step": step,
                        "tool": action.tool,
                        "evidence_ids": result.evidence_ids,
                        "observation": result.observation[:6000],
                    }
                )
                if action.tool == "finish_audit":
                    finish_action = Action(
                        kind="finish",
                        decision=result.metadata.get("decision"),
                        reason=str(result.metadata.get("reason", "")),
                        missing_unknowns=list(
                            result.metadata.get("missing_unknowns", [])
                        ),
                        raw=action.raw,
                    )
                    self.context.state.budget_remaining -= 1
                    if self._handle_finish(finish_action, step):
                        self._persist()
                        break
                    if self.context.state.budget_remaining <= 0:
                        self.context.state.termination = "INSUFFICIENT_EVIDENCE"
                        self.context.state.status = "completed"
                        self._event(
                            {
                                "event": "budget_exhausted",
                                "step": step,
                                "missing": missing_capabilities(self.context.facts),
                            }
                        )
                    self._persist()
                    continue
            except ToolValidationError as exc:
                result_text = f"tool failed: {type(exc).__name__}: {exc}"
                self._mark_evaluation_unknown(
                    f"model selected invalid tool arguments: {exc}"
                )
                self.context.state.add_observation(result_text)
                self._event(
                    {
                        "event": "model_output_integrity_rejected",
                        "step": step,
                        "tool": action.tool,
                        "error": result_text,
                    }
                )
                self._record_action(step=step, action=action, result=result_text)
                self.context.state.termination = "INSUFFICIENT_EVIDENCE"
                self.context.state.status = "completed"
                self._persist()
                break
            except Exception as exc:
                result_text = f"tool failed: {type(exc).__name__}: {exc}"
                self.context.state.add_observation(result_text)
                self._event(
                    {
                        "event": "tool_error",
                        "step": step,
                        "tool": action.tool,
                        "error": result_text,
                    }
                )
            self._record_action(step=step, action=action, result=result_text)
            self.context.state.budget_remaining -= 1
            if self.context.state.budget_remaining <= 0:
                self.context.state.termination = "INSUFFICIENT_EVIDENCE"
                self.context.state.status = "completed"
                self._event(
                    {
                        "event": "budget_exhausted",
                        "step": step,
                        "missing": missing_capabilities(self.context.facts),
                    }
                )
            self._persist()
        if not self.context.state.termination:
            self.context.state.termination = "INSUFFICIENT_EVIDENCE"
            self.context.state.status = "completed"
            self._event(
                {
                    "event": "loop_stopped",
                    "reason": "no accepted finish decision",
                    "missing": missing_capabilities(self.context.facts),
                }
            )
        self._persist()
        return AgentLoopResult(context=self.context, events=self.events)
