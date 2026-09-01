from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.acquisition.github_url import GitHubUrlError, parse_github_url
from agentscope.domain.evidence import EvidenceError, EvidenceLedger


class UrlAndEvidenceTests(unittest.TestCase):
    def test_github_url_is_canonicalized_and_restricted(self) -> None:
        ref = parse_github_url("https://github.com/eightman999/autoresearch-naval.git")
        self.assertEqual(ref.canonical_url, "https://github.com/eightman999/autoresearch-naval")
        self.assertEqual(ref.api_path, "/repos/eightman999/autoresearch-naval")
        for value in (
            "http://github.com/a/b",
            "https://example.com/a/b",
            "https://github.com/a/b/tree/main",
            "https://github.com/a/b?x=1",
            "https://user:pass@github.com/a/b",
        ):
            with self.subTest(value=value), self.assertRaises(GitHubUrlError):
                parse_github_url(value)

    def test_evidence_rejects_traversal_and_hash_is_deterministic(self) -> None:
        with self.assertRaises(EvidenceError):
            EvidenceLedger().add(
                claim_key="x",
                source_kind="repository",
                file="../secret",
                start_line=1,
                end_line=1,
                excerpt="secret",
                commit_sha="sha",
                reason="test",
            )
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore.create(Path(directory), "run")
            path = store.write_text("provenance/coverage.txt", "line\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "line\n")
            self.assertEqual(store.path("provenance/coverage.txt"), path)
            with self.assertRaises(ValueError):
                store.path("../outside")


if __name__ == "__main__":
    unittest.main()
