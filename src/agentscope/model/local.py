"""llama.cppを介したlocal-only model provider。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
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
        grammar_path: Path | None = None,
        tool_grammar_path: Path | None = None,
        finish_grammar_path: Path | None = None,
        timeout: int = 120,
    ) -> None:
        self.model_path = model_path
        self.manifest = manifest
        self.binary_path = str(
            binary_path or shutil.which("llama-cli") or shutil.which("llama") or ""
        )
        self.schema_path = schema_path
        self.grammar_path = grammar_path
        self.tool_grammar_path = tool_grammar_path
        self.finish_grammar_path = finish_grammar_path
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
            "/no_think\n" + context.prompt,
            "-n",
            "256",
            "--ctx-size",
            "8192",
            "--temp",
            "0.0",
            "--seed",
            "42",
            "--no-display-prompt",
            "--no-show-timings",
            "--single-turn",
            "--jinja",
            "--reasoning",
            "off",
            "--no-perf",
            "--log-disable",
            "--simple-io",
        ]
        missing_capabilities = context.state.get("missing_capabilities")
        inline_grammar: str | None = None
        selected_grammar = self.grammar_path
        if missing_capabilities and self.tool_grammar_path:
            history = context.state.get("action_history", [])
            inventory_seen = any(
                isinstance(item, dict) and item.get("tool") == "list_repo_tree"
                for item in history
            )
            inline_grammar = self._filtered_tool_grammar(
                missing_capabilities,
                include_list_repo_tree=not inventory_seen,
            )
            selected_grammar = None
        elif self.finish_grammar_path and not missing_capabilities:
            selected_grammar = self.finish_grammar_path
        if inline_grammar is not None:
            command.extend(["--grammar", inline_grammar])
        elif selected_grammar:
            if not selected_grammar.is_file():
                raise ModelProviderError("action grammar could not be read")
            command.extend(["--grammar-file", str(selected_grammar)])
        elif self.schema_path:
            if not self.schema_path.is_file():
                raise ModelProviderError("action schema could not be read")
            command.extend(["--json-schema-file", str(self.schema_path)])
        with tempfile.TemporaryDirectory(prefix="agentscope-llama-") as temporary_directory:
            output_path = Path(temporary_directory) / "action.json"
            command.extend(["--output", str(output_path)])
            try:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    check=False,
                    timeout=self.timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ModelProviderError(f"llama.cpp inference failed: {exc}") from exc
            if completed.returncode != 0:
                error_text = completed.stderr.decode("utf-8", errors="replace").strip()
                raise ModelProviderError(error_text or "llama.cpp returned an error")
            try:
                transcript = output_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ModelProviderError("llama.cpp output file could not be read") from exc
        marker = "Assistant:\n"
        if not transcript.startswith("User:\n") or marker not in transcript:
            raise ModelProviderError("llama.cpp output framing was not recognized")
        raw = transcript.split(marker, 1)[1].strip()
        if "<think>" in raw or "</think>" in raw:
            raise ModelProviderError("llama.cpp returned reasoning text with the action")
        if not raw:
            raise ModelProviderError("llama.cpp returned an empty action")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelProviderError("llama.cpp output was not strict JSON") from exc
        if not isinstance(parsed, dict):
            raise ModelProviderError("llama.cpp action must be a JSON object")
        return parsed

    def _filtered_tool_grammar(
        self,
        missing_capabilities: object,
        *,
        include_list_repo_tree: bool = True,
    ) -> str:
        if not self.tool_grammar_path or not self.tool_grammar_path.is_file():
            raise ModelProviderError("tool action grammar could not be read")
        if not isinstance(missing_capabilities, list):
            raise ModelProviderError("missing_capabilities must be an array")
        capability_tools = {
            "readme": {"read_file"},
            "llm_calls": {"inspect_llm_calls"},
            "tooling": {"inspect_tooling"},
            "control_flow": {"trace_call_graph"},
            "call_graph": {"trace_call_graph"},
            "git_provenance": {"inspect_git_provenance"},
            "github_metadata": {"inspect_github_metadata"},
            "verification": {"inspect_tests"},
            "concept_lineage": {"inspect_concept_lineage"},
        }
        allowed: set[str] = set()
        for capability in missing_capabilities:
            if isinstance(capability, str):
                allowed.update(capability_tools.get(capability, set()))
        if "readme" in missing_capabilities:
            allowed.add("search_code")
            if include_list_repo_tree:
                allowed.add("list_repo_tree")
        if not allowed:
            raise ModelProviderError("no model tool is eligible for the missing capabilities")
        grammar = self.tool_grammar_path.read_text(encoding="utf-8")
        branches: set[str] = set()
        if "read_file" in allowed:
            branches.add("toolread")
        if "search_code" in allowed:
            branches.add("toolsearch")
        if "trace_call_graph" in allowed:
            branches.add("tooltrace")
        plain_tools = sorted(
            allowed
            - {"read_file", "search_code", "trace_call_graph"}
        )
        if plain_tools:
            branches.add("toolplain")
        grammar = re.sub(
            r"^toolcall ::= .*?$",
            "toolcall ::= " + " | ".join(sorted(branches)),
            grammar,
            count=1,
            flags=re.MULTILINE,
        )
        if plain_tools:
            names = " | ".join(
                '"' + '\\"' + name + '\\"' + '"' for name in plain_tools
            )
            grammar, plain_count = re.subn(
                r"^plainname ::= .*?$",
                f"plainname ::= {names}",
                grammar,
                count=1,
                flags=re.MULTILINE,
            )
            if plain_count != 1:
                raise ModelProviderError("tool grammar did not contain plainname rule")
        return grammar
