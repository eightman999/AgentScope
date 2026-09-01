from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentscope.model.local import LocalLlamaCppProvider
from agentscope.model.manifest import ModelManifestError, load_manifest
from agentscope.agent.prompt import build_model_context


class ModelRuntimeTests(unittest.TestCase):
    def test_manifest_has_verified_artifact_contract(self) -> None:
        manifest = load_manifest(Path("resources/model-manifest.json"))
        self.assertEqual(manifest.format, "GGUF")
        self.assertEqual(manifest.runtime, "llama.cpp")
        self.assertGreater(manifest.model_size_bytes, 0)
        self.assertRegex(manifest.model_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertFalse(manifest.weights_in_source_control)
        self.assertTrue(manifest.release_bundle_required)

    def test_manifest_rejects_unsafe_artifact_and_wrong_schema(self) -> None:
        raw = json.loads(Path("resources/model-manifest.json").read_text(encoding="utf-8"))
        for field, value in (("schema_version", "9.9"), ("artifact", "../model.gguf")):
            candidate = dict(raw)
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ModelManifestError):
                load_manifest_from_dict(candidate)

    def test_filtered_grammar_limits_tools_and_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.gguf"
            model_path.write_bytes(b"placeholder")
            resource_root = Path("resources")
            provider = LocalLlamaCppProvider(
                model_path=model_path,
                manifest=load_manifest(resource_root / "model-manifest.json"),
                binary_path="llama-cli",
                tool_grammar_path=resource_root / "tool-action-grammar.gbnf",
            )
            readme_grammar = provider._filtered_tool_grammar(
                ["readme"], readable_paths=["README.md", "src/main.py"]
            )
            self.assertIn("toolcall ::= toolplain | toolread | toolsearch", readme_grammar)
            self.assertIn('readargs ::= "{" ws "\\\"path\\\"" ws ":" ws pathvalue ws "}"', readme_grammar)
            self.assertIn('plainname ::= "\\\"list_repo_tree\\\""', readme_grammar)
            self.assertIn('pathvalue ::= "\\\"README.md\\\""', readme_grammar)
            self.assertNotIn('pathvalue ::= "\\\"unknown\\\""', readme_grammar)
            readme_after_inventory = provider._filtered_tool_grammar(
                ["readme"],
                include_list_repo_tree=False,
                readable_paths=["README.md", "src/main.py"],
            )
            self.assertIn("toolcall ::= toolread | toolsearch", readme_after_inventory)
            self.assertNotIn('"list_repo_tree"', readme_after_inventory)
            self.assertNotIn('"\\\"src/main.py\\\""', readme_after_inventory)

            visited_read_grammar = provider._filtered_tool_grammar(
                ["readme", "llm_calls"],
                include_list_repo_tree=False,
                readable_paths=["README.md", "src/main.py"],
                visited_paths=["README.md"],
            )
            self.assertNotIn('"\\\"README.md\\\""', visited_read_grammar)
            self.assertNotIn("toolread", visited_read_grammar.splitlines()[1])

            llm_grammar = provider._filtered_tool_grammar(["llm_calls"])
            self.assertIn("toolcall ::= toolplain", llm_grammar)
            self.assertIn('plainname ::= "\\\"inspect_llm_calls\\\""', llm_grammar)
            self.assertNotIn("inspect_tooling", llm_grammar.split("plainname ::= ", 1)[1].splitlines()[0])

    def test_model_context_bounds_large_internal_state(self) -> None:
        context = build_model_context(
            state={
                "evidence_ids": [f"evidence-{index}" for index in range(1000)],
                "visited_files": [f"file-{index}.py" for index in range(500)],
                "unknowns": [f"unknown-{index}" for index in range(100)],
                "action_history": [],
            },
            tool_catalog=[],
            observations=[],
            facts={},
        )

        self.assertLess(len(context.prompt), 20_000)
        self.assertIn('"evidence_ids_total": 1000', context.prompt)
        self.assertIn('"evidence-999"', context.prompt)
        self.assertNotIn('"evidence-0"', context.prompt)


def load_manifest_from_dict(raw: dict[str, object]):
    from agentscope.model.manifest import ModelManifest

    return ModelManifest.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
