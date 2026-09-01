"""LLM provider boundary。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelProviderError(RuntimeError):
    """local modelまたはmock providerの失敗。"""


@dataclass(frozen=True)
class ModelContext:
    prompt: str
    state: dict[str, Any]
    tool_catalog: list[dict[str, Any]]


class ModelProvider(Protocol):
    def complete_action(self, context: ModelContext) -> Any:
        """Action schema候補を返す。"""

