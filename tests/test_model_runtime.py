from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentscope.model.local import LocalLlamaCppProvider
from agentscope.model.manifest import ModelManifestError, load_manifest


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
            readme_grammar = provider._filtered_tool_grammar(["readme"])
            self.assertIn("toolcall ::= toolplain | toolread | toolsearch", readme_grammar)
            self.assertIn('readargs ::= "{" ws "\\\"path\\\"" ws ":" ws string ws "}"', readme_grammar)
            self.assertIn('plainname ::= "\\\"list_repo_tree\\\""', readme_grammar)

            llm_grammar = provider._filtered_tool_grammar(["llm_calls"])
            self.assertIn("toolcall ::= toolplain", llm_grammar)
            self.assertIn('plainname ::= "\\\"inspect_llm_calls\\\""', llm_grammar)
            self.assertNotIn("inspect_tooling", llm_grammar.split("plainname ::= ", 1)[1].splitlines()[0])


def load_manifest_from_dict(raw: dict[str, object]):
    from agentscope.model.manifest import ModelManifest

    return ModelManifest.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
