"""AgentScope benchmarkの決定論的な集計とエラー分類。"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Iterable, Mapping, Sequence

from agentscope.benchmark.schema import (
    BENCHMARK_CATEGORIES,
    BenchmarkCase,
)
from agentscope.domain.classifications import CLASSIFICATION_KEYS
from agentscope.domain.scoring import SCORE_KEYS


MODEL_LABEL_VALUES = ("yes", "no", "unknown")
MATRIX_GOLD_VALUES = ("yes", "no", "unknown", "ambiguous")
MATRIX_PREDICTED_VALUES = ("yes", "no", "unknown", "missing")


@dataclass(frozen=True)
class BenchmarkPrediction:
    """1 case分の監査結果。reportがない失敗も明示的に保持する。"""

    case_id: str
    status: str
    report_path: str | None = None
    report: dict[str, Any] | None = None
    error: str | None = None

    @property
    def commit_sha(self) -> str | None:
        if not isinstance(self.report, dict):
            return None
        subject = self.report.get("subject")
        if not isinstance(subject, dict):
            return None
        value = subject.get("commit_sha")
        return value if isinstance(value, str) else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return _round(numerator / denominator)


def _empty_matrix() -> dict[str, dict[str, int]]:
    return {
        gold: {predicted: 0 for predicted in MATRIX_PREDICTED_VALUES}
        for gold in MATRIX_GOLD_VALUES
    }


def _report_prediction(
    prediction: BenchmarkPrediction | None,
    key: str,
    *,
    expected_commit_sha: str | None = None,
) -> tuple[str, list[str]]:
    if prediction is None or not isinstance(prediction.report, dict):
        return "missing", []
    if (
        expected_commit_sha is not None
        and prediction.commit_sha is not None
        and prediction.commit_sha.lower() != expected_commit_sha.lower()
    ):
        return "missing", []
    classifications = prediction.report.get("classifications")
    if not isinstance(classifications, dict):
        return "missing", []
    item = classifications.get(key)
    if not isinstance(item, dict):
        return "missing", []
    value = item.get("value")
    if value not in MODEL_LABEL_VALUES:
        return "missing", []
    evidence_by_id = {
        evidence.get("id"): evidence
        for evidence in prediction.report.get("evidence", [])
        if isinstance(evidence, dict) and isinstance(evidence.get("id"), str)
    }
    refs = [
        evidence_by_id[evidence_id].get("display_ref", "")
        for evidence_id in item.get("evidence_ids", [])
        if evidence_id in evidence_by_id
    ]
    return value, [ref for ref in refs if ref]


def _human_evidence_refs(case: BenchmarkCase, key: str) -> list[str]:
    label = case.human_labels.get(key)
    if label is None:
        return []
    return [item.display_ref for item in label.evidence]


def _classification_summary(
    cases: Sequence[BenchmarkCase],
    predictions: Mapping[str, BenchmarkPrediction],
    key: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    matrix = _empty_matrix()
    annotated_n = 0
    evaluated_n = 0
    missing_n = 0
    stale_commit_n = 0
    ambiguous_n = 0
    unknown_gold_n = 0
    tp = fp = tn = fn = 0
    abstain_positive = abstain_negative = 0
    resolved_n = 0
    positive_prediction_n = 0
    false_positive_cases: list[dict[str, Any]] = []
    false_negative_cases: list[dict[str, Any]] = []
    abstained_positive_cases: list[dict[str, Any]] = []

    for case in cases:
        label = case.human_labels.get(key)
        if label is None:
            continue
        annotated_n += 1
        gold = label.value
        prediction = predictions.get(case.id)
        if (
            prediction is not None
            and isinstance(prediction.report, dict)
            and prediction.commit_sha is not None
            and prediction.commit_sha.lower() != case.commit_sha.lower()
        ):
            stale_commit_n += 1
        predicted, predicted_refs = _report_prediction(
            prediction,
            key,
            expected_commit_sha=case.commit_sha,
        )
        if gold in MATRIX_GOLD_VALUES:
            matrix[gold][predicted] += 1
        if gold == "ambiguous":
            ambiguous_n += 1
            continue
        if gold == "unknown":
            unknown_gold_n += 1
            continue
        if predicted == "missing":
            missing_n += 1
            continue
        evaluated_n += 1
        if predicted in {"yes", "no"}:
            resolved_n += 1
        if predicted == "yes":
            positive_prediction_n += 1
        if gold == "yes" and predicted == "yes":
            tp += 1
        elif gold == "no" and predicted == "yes":
            fp += 1
            false_positive_cases.append(
                _error_case(case, key, gold, predicted, prediction, predicted_refs)
            )
        elif gold == "no" and predicted == "no":
            tn += 1
        elif gold == "yes" and predicted == "no":
            fn += 1
            false_negative_cases.append(
                _error_case(case, key, gold, predicted, prediction, predicted_refs)
            )
        elif gold == "yes" and predicted == "unknown":
            abstain_positive += 1
            abstained_positive_cases.append(
                _error_case(case, key, gold, predicted, prediction, predicted_refs)
            )
        elif gold == "no" and predicted == "unknown":
            abstain_negative += 1

    gold_positive = tp + fn + abstain_positive
    gold_negative = fp + tn + abstain_negative
    resolved_positive_denominator = tp + fp
    resolved_recall_denominator = tp + fn
    summary: dict[str, Any] = {
        "axis": key,
        "annotated_n": annotated_n,
        "evaluated_n": evaluated_n,
        "missing_prediction_n": missing_n,
        "stale_commit_prediction_n": stale_commit_n,
        "ambiguous_gold_n": ambiguous_n,
        "unknown_gold_n": unknown_gold_n,
        "gold_positive_n": gold_positive,
        "gold_negative_n": gold_negative,
        "resolved_n": resolved_n,
        "abstention_n": abstain_positive + abstain_negative,
        "positive_prediction_n": positive_prediction_n,
        "confusion_matrix": matrix,
        "counts": {
            "true_positive": tp,
            "false_positive": fp,
            "true_negative": tn,
            "false_negative": fn,
            "abstained_positive": abstain_positive,
            "abstained_negative": abstain_negative,
        },
        "rates": {
            # precisionはモデルがyes/noを返した範囲で計算する。
            "precision": _ratio(tp, resolved_positive_denominator),
            # recall/fnrは安全側に、positiveへのUnknown棄権も未検出として数える。
            "recall": _ratio(tp, gold_positive),
            "false_positive_rate": _ratio(fp, gold_negative),
            "false_negative_rate": _ratio(fn + abstain_positive, gold_positive),
            "selective_recall": _ratio(tp, resolved_recall_denominator),
            "selective_accuracy": _ratio(tp + tn, resolved_n),
            "coverage": _ratio(resolved_n, evaluated_n),
            "abstention_rate": _ratio(abstain_positive + abstain_negative, evaluated_n),
        },
    }
    return summary, {
        "false_positive": false_positive_cases,
        "false_negative": false_negative_cases,
        "abstained_positive": abstained_positive_cases,
    }


def _error_case(
    case: BenchmarkCase,
    key: str,
    gold: str,
    predicted: str,
    prediction: BenchmarkPrediction | None,
    predicted_refs: list[str],
) -> dict[str, Any]:
    return {
        "id": case.id,
        "category": case.category,
        "axis": key,
        "gold": gold,
        "predicted": predicted,
        "report_path": prediction.report_path if prediction else None,
        "human_evidence": _human_evidence_refs(case, key),
        "predicted_evidence": predicted_refs,
        "human_rationale": case.human_labels[key].rationale,
    }


def _category_summary(
    cases: Sequence[BenchmarkCase],
    predictions: Mapping[str, BenchmarkPrediction],
    key: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for category in BENCHMARK_CATEGORIES:
        subset = [case for case in cases if case.category == category]
        summary, _ = _classification_summary(subset, predictions, key)
        result[category] = summary
    return result


def _score_summary(
    cases: Sequence[BenchmarkCase],
    predictions: Mapping[str, BenchmarkPrediction],
    key: str,
) -> dict[str, Any]:
    expected: list[float] = []
    actual: list[float] = []
    missing = 0
    for case in cases:
        if key not in case.human_scores:
            continue
        expected_value = case.human_scores[key]
        prediction = predictions.get(case.id)
        actual_value: object = None
        if (
            prediction is not None
            and isinstance(prediction.report, dict)
            and prediction.commit_sha is not None
            and prediction.commit_sha.lower() == case.commit_sha.lower()
        ):
            for item in prediction.report.get("scores", []):
                if isinstance(item, dict) and item.get("key") == key:
                    actual_value = item.get("score")
                    break
        if (
            not isinstance(actual_value, (int, float))
            or isinstance(actual_value, bool)
            or not 0.0 <= float(actual_value) <= 10.0
        ):
            missing += 1
            continue
        expected.append(expected_value)
        actual.append(float(actual_value))
    if not expected:
        return {"axis": key, "n": 0, "missing_prediction_n": missing, "mae": None, "rmse": None, "mean_signed_error": None}
    errors = [actual_value - expected_value for actual_value, expected_value in zip(actual, expected)]
    return {
        "axis": key,
        "n": len(expected),
        "missing_prediction_n": missing,
        "mae": _round(sum(abs(error) for error in errors) / len(errors)),
        "rmse": _round(sqrt(sum(error * error for error in errors) / len(errors))),
        "mean_signed_error": _round(sum(errors) / len(errors)),
    }


def compute_benchmark_metrics(
    cases: Sequence[BenchmarkCase],
    predictions: Mapping[str, BenchmarkPrediction],
    *,
    dataset_path: str | None = None,
    dataset_sha256: str | None = None,
) -> dict[str, Any]:
    """report結果とgold labelを比較し、JSON保存可能なdictを返す。"""

    classification_metrics: dict[str, Any] = {}
    error_cases: dict[str, Any] = {}
    by_category: dict[str, Any] = {}
    for key in CLASSIFICATION_KEYS:
        summary, errors = _classification_summary(cases, predictions, key)
        classification_metrics[key] = summary
        error_cases[key] = errors
        by_category[key] = _category_summary(cases, predictions, key)

    score_metrics = {
        key: _score_summary(cases, predictions, key) for key in SCORE_KEYS
    }
    completed = sum(
        1 for case in cases if predictions.get(case.id) and predictions[case.id].report is not None
    )
    return {
        "schema_version": "0.1",
        "dataset": {
            "path": dataset_path,
            "sha256": dataset_sha256,
            "case_n": len(cases),
            "category_counts": {
                category: sum(1 for case in cases if case.category == category)
                for category in BENCHMARK_CATEGORIES
            },
            "annotation_status_counts": {
                status: sum(1 for case in cases if case.annotation_status == status)
                for status in ("adjudicated", "draft", "pending")
            },
            "labeled_case_n": sum(1 for case in cases if case.human_labels),
        },
        "predictions": {
            "case_n": len(predictions),
            "completed_report_n": completed,
            "missing_report_n": len(cases) - completed,
        },
        "protocol": {
            "primary_axis": "agentic_runtime",
            "binary_gold_values": ["yes", "no"],
            "unknown_prediction_policy": "abstention; conservative recall/fnr count positive abstentions as missed",
            "ambiguous_gold_policy": "excluded from binary precision/recall and retained in confusion matrix",
            "score_policy": "MAE/RMSE only where both human score and numeric report score exist",
        },
        "primary": classification_metrics["agentic_runtime"],
        "classifications": classification_metrics,
        "by_category": by_category,
        "scores": score_metrics,
        "errors": error_cases,
    }


def validate_prediction_row(row: object, *, context: str = "result") -> dict[str, Any]:
    """runner成果物の1行を検証する。未知キーを許さず壊れた再開を防ぐ。"""

    if not isinstance(row, dict):
        raise ValueError(f"{context} must be an object")
    allowed = {
        "id",
        "status",
        "report_path",
        "actual_commit_sha",
        "error",
    }
    extra = set(row) - allowed
    if extra:
        raise ValueError(f"{context} contains unknown keys: {sorted(extra)}")
    case_id = row.get("id")
    status = row.get("status")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError(f"{context}.id is required")
    if status not in {"completed", "failed", "stale_commit", "skipped"}:
        raise ValueError(f"{context}.status is invalid")
    for key in ("report_path", "actual_commit_sha", "error"):
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{context}.{key} must be a string or null")
    if status == "completed" and not isinstance(row.get("report_path"), str):
        raise ValueError(f"{context}.completed requires report_path")
    return dict(row)
