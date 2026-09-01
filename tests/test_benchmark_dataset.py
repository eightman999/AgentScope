from __future__ import annotations

from pathlib import Path
import unittest

from agentscope.benchmark.schema import category_counts, load_dataset


DATASET = Path(__file__).parents[1] / "benchmarks" / "dataset.jsonl"


class BenchmarkDatasetTests(unittest.TestCase):
    def test_initial_real_dataset_is_balanced_and_pinned(self) -> None:
        cases = load_dataset(DATASET)
        self.assertEqual(len(cases), 30)
        self.assertEqual(set(category_counts(cases).values()), {6})
        self.assertTrue(all(len(case.commit_sha) == 40 for case in cases))
        self.assertTrue(all(case.annotation_status == "draft" for case in cases))
        self.assertTrue(all("agentic_runtime" in case.human_labels for case in cases))
        self.assertNotIn(
            "https://github.com/eightman999/autoresearch-naval",
            {case.url for case in cases},
        )


if __name__ == "__main__":
    unittest.main()
