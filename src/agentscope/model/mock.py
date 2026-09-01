"""fixture用のmock model provider。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from agentscope.model.provider import ModelContext, ModelProviderError


ScriptItem = dict[str, Any] | Callable[[ModelContext], dict[str, Any]]


class MockModelProvider:
    """live modelと同じinterfaceでactionを返す。"""

    def __init__(self, script: Iterable[ScriptItem]) -> None:
        self._script = list(script)
        self.calls: list[ModelContext] = []
        self._index = 0

    def complete_action(self, context: ModelContext) -> dict[str, Any]:
        self.calls.append(context)
        if self._index >= len(self._script):
            raise ModelProviderError("mock action script was exhausted")
        item = self._script[self._index]
        self._index += 1
        return item(context) if callable(item) else dict(item)

