from __future__ import annotations

from pathlib import Path
import unittest

from agentscope.benchmark.schema import category_counts, load_dataset
from agentscope.domain.classifications import CLASSIFICATION_KEYS
from agentscope.domain.scoring import SCORE_KEYS


DATASET = Path(__file__).parents[1] / "benchmarks" / "dataset.jsonl"


class BenchmarkDatasetTests(unittest.TestCase):
    def test_initial_real_dataset_is_balanced_and_pinned(self) -> None:
        cases = load_dataset(DATASET)
        self.assertEqual(len(cases), 30)
        self.assertEqual(set(category_counts(cases).values()), {6})
        self.assertTrue(all(len(case.commit_sha) == 40 for case in cases))
        self.assertTrue(all(case.annotation_status == "draft" for case in cases))
        self.assertTrue(
            all(set(case.human_labels) == set(CLASSIFICATION_KEYS) for case in cases)
        )
        scored = [case for case in cases if case.human_scores]
        self.assertEqual(len(scored), 29)
        self.assertTrue(
            all(
                set(case.human_scores) == set(SCORE_KEYS)
                and set(case.annotation["score_evidence"]) == set(SCORE_KEYS)
                for case in scored
            )
        )
        self.assertNotIn(
            "https://github.com/eightman999/autoresearch-naval",
            {case.url for case in cases},
        )


if __name__ == "__main__":
    unittest.main()
