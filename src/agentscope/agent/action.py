"""model actionのstrict schema validation。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


class ActionValidationError(ValueError):
    """model actionがschemaに適合しない。"""


@dataclass(frozen=True)
class Action:
    kind: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    hypothesis: str = ""
    focus: list[str] = field(default_factory=list)
    decision: str | None = None
    reason: str = ""
    missing_unknowns: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ActionValidationError(f"action is not JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ActionValidationError("action must be a JSON object")
    return raw


def _strict_keys(raw: dict[str, Any], allowed: set[str]) -> None:
    extra = set(raw) - allowed
    if extra:
        raise ActionValidationError(f"unknown action properties: {sorted(extra)}")


def _strings(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ActionValidationError(f"{field_name} must be an array of strings")
    return list(value)


def parse_action(raw_value: Any) -> Action:
    raw = _object(raw_value)
    kind = raw.get("kind")
    if kind == "tool_call":
        _strict_keys(raw, {"kind", "tool", "arguments", "hypothesis", "focus"})
        tool = raw.get("tool")
        arguments = raw.get("arguments")
        if not isinstance(tool, str) or not tool:
            raise ActionValidationError("tool_call.tool must be a non-empty string")
        if not isinstance(arguments, dict):
            raise ActionValidationError("tool_call.arguments must be an object")
        hypothesis = raw.get("hypothesis", "")
        if not isinstance(hypothesis, str):
            raise ActionValidationError("hypothesis must be a string")
        focus = _strings(raw.get("focus", []), "focus")
        return Action(
            kind=kind,
            tool=tool,
            arguments=dict(arguments),
            hypothesis=hypothesis,
            focus=focus,
            raw=raw,
        )
    if kind == "finish":
        _strict_keys(raw, {"kind", "decision", "reason", "missing_unknowns"})
        decision = raw.get("decision")
        reason = raw.get("reason")
        if decision not in {"ENOUGH_EVIDENCE", "INSUFFICIENT_EVIDENCE"}:
            raise ActionValidationError("invalid finish decision")
        if not isinstance(reason, str) or not reason:
            raise ActionValidationError("finish.reason is required")
        missing = _strings(raw.get("missing_unknowns"), "missing_unknowns")
        return Action(
            kind=kind,
            decision=decision,
            reason=reason,
            missing_unknowns=missing,
            raw=raw,
        )
    raise ActionValidationError("kind must be tool_call or finish")

