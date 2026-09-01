"""llama.cppを介したlocal-only model provider。"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from agentscope.model.manifest import ModelManifest
from agentscope.model.provider import ModelContext, ModelProviderError


class LocalLlamaCppProvider:
    def __init__(
        self,
        *,
        model_path: Path,
        manifest: ModelManifest,
        binary_path: str | Path | None = None,
        schema_path: Path | None = None,
        timeout: int = 120,
    ) -> None:
        self.model_path = model_path
        self.manifest = manifest
        self.binary_path = str(
            binary_path or shutil.which("llama-cli") or shutil.which("llama") or ""
        )
        self.schema_path = schema_path
        self.timeout = timeout
        if not self.binary_path:
            raise ModelProviderError("llama.cpp executable was not found")
        if not self.model_path.is_file():
            raise ModelProviderError(f"local model artifact was not found: {self.model_path}")

    def complete_action(self, context: ModelContext) -> dict[str, Any]:
        command = [
            self.binary_path,
            "-m",
            str(self.model_path),
            "-p",
            context.prompt,
            "-n",
            "384",
            "--temp",
            "0.2",
            "--seed",
            "42",
        ]
        if self.schema_path:
            try:
                schema_text = self.schema_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ModelProviderError("action schema could not be read") from exc
            command.extend(["--json-schema", schema_text])
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ModelProviderError(f"llama.cpp inference failed: {exc}") from exc
        if completed.returncode != 0:
            raise ModelProviderError(completed.stderr.strip() or "llama.cpp returned an error")
        raw = completed.stdout.strip()
        if not raw:
            raise ModelProviderError("llama.cpp returned an empty action")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelProviderError("llama.cpp output was not strict JSON") from exc
        if not isinstance(parsed, dict):
            raise ModelProviderError("llama.cpp action must be a JSON object")
        return parsed

