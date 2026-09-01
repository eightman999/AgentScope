"""ベンチマーク集計結果の人間向けMarkdown。"""

from __future__ import annotations

from typing import Any

from agentscope.domain.classifications import CLASSIFICATION_KEYS
from agentscope.domain.scoring import SCORE_KEYS, SCORE_LABELS


CLASSIFICATION_LABELS = {
    "ai_assisted_development": "AI-assisted development",
    "agentic_runtime": "Agentic runtime",
    "mcp_tooling": "MCP/tooling",
    "formal_github_fork": "Formal GitHub fork",
    "derived_concept": "Derived concept",
}


def _number(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.3f}"
    return str(value)


def _percent(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value) * 100:.1f}%"
    return str(value)


def _metric_line(summary: dict[str, Any]) -> str:
    rates = summary["rates"]
    counts = summary["counts"]
    return (
        f"n={summary['evaluated_n']}, TP={counts['true_positive']}, "
        f"FP={counts['false_positive']}, TN={counts['true_negative']}, "
        f"FN={counts['false_negative']}, "
        f"precision={_percent(rates['precision'])}, "
        f"recall={_percent(rates['recall'])}, "
        f"FPR={_percent(rates['false_positive_rate'])}, "
        f"FNR={_percent(rates['false_negative_rate'])}, "
        f"coverage={_percent(rates['coverage'])}, "
        f"abstention={_percent(rates['abstention_rate'])}"
    )


def _error_table(
    title: str,
    rows: list[dict[str, Any]],
) -> list[str]:
    lines = [f"### {title}", "", "| case | category | gold | prediction | human evidence | AgentScope evidence |", "| --- | --- | --- | --- | --- | --- |"]
    if not rows:
        lines.append("| — | — | — | — | — | — |")
        return lines + [""]
    for row in rows:
        human = "、".join(row.get("human_evidence", [])) or "—"
        predicted = "、".join(row.get("predicted_evidence", [])) or "—"
        lines.append(
            f"| {row['id']} | {row['category']} | {row['gold']} | "
            f"{row['predicted']} | {human} | {predicted} |"
        )
    return lines + [""]


def render_benchmark_markdown(metrics: dict[str, Any]) -> str:
    dataset = metrics["dataset"]
    predictions = metrics["predictions"]
    primary = metrics["primary"]
    lines = [
        "# AgentScope benchmark report",
        "",
        f"- dataset: `{dataset.get('path') or 'unknown'}`",
        f"- dataset SHA-256: `{dataset.get('sha256') or 'unknown'}`",
        f"- cases: {dataset['case_n']}",
        f"- labeled cases: {dataset['labeled_case_n']}",
        f"- completed reports: {predictions['completed_report_n']}",
        f"- missing reports: {predictions['missing_report_n']}",
        "",
        "## Primary metric: Agentic runtime",
        "",
        "Unknown prediction is abstention. Precision is calculated on resolved yes predictions; recall and FNR conservatively count an abstained positive as missed. Ambiguous human labels are excluded from binary rates.",
        "",
        f"**Overall:** {_metric_line(primary)}",
        "",
        "| category | n | precision | recall | false-positive rate | false-negative rate | coverage | abstention |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, summary in metrics["by_category"]["agentic_runtime"].items():
        rates = summary["rates"]
        lines.append(
            f"| {category} | {summary['evaluated_n']} | "
            f"{_percent(rates['precision'])} | {_percent(rates['recall'])} | "
            f"{_percent(rates['false_positive_rate'])} | "
            f"{_percent(rates['false_negative_rate'])} | "
            f"{_percent(rates['coverage'])} | {_percent(rates['abstention_rate'])} |"
        )
    lines.extend(["", "## 5分類の指標", "", "| axis | n | precision | recall | FP | FN | coverage | abstention |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for key in CLASSIFICATION_KEYS:
        summary = metrics["classifications"][key]
        rates = summary["rates"]
        counts = summary["counts"]
        lines.append(
            f"| {CLASSIFICATION_LABELS[key]} | {summary['evaluated_n']} | "
            f"{_percent(rates['precision'])} | {_percent(rates['recall'])} | "
            f"{counts['false_positive']} | {counts['false_negative']} | "
            f"{_percent(rates['coverage'])} | {_percent(rates['abstention_rate'])} |"
        )
    lines.extend(["", "## 7軸scoreの一致", "", "| axis | n | MAE | RMSE | mean signed error |", "| --- | ---: | ---: | ---: | ---: |"])
    for key in SCORE_KEYS:
        item = metrics["scores"][key]
        lines.append(
            f"| {SCORE_LABELS[key]} | {item['n']} | {_number(item['mae'])} | "
            f"{_number(item['rmse'])} | {_number(item['mean_signed_error'])} |"
        )
    lines.extend(["", "## 層別内訳", ""])
    for category, count in dataset["category_counts"].items():
        lines.append(f"- `{category}`: {count}")
    lines.extend(["", "## Confusion matrix: Agentic runtime", "", "| gold \\ prediction | yes | no | unknown | missing |", "| --- | ---: | ---: | ---: | ---: |"])
    for gold, row in primary["confusion_matrix"].items():
        lines.append(
            f"| {gold} | {row['yes']} | {row['no']} | {row['unknown']} | {row['missing']} |"
        )
    lines.extend(["", "## Error analysis", ""])
    lines.extend(_error_table("False positives", metrics["errors"]["agentic_runtime"]["false_positive"]))
    lines.extend(_error_table("False negatives", metrics["errors"]["agentic_runtime"]["false_negative"]))
    lines.extend(_error_table("Positive abstentions", metrics["errors"]["agentic_runtime"]["abstained_positive"]))
    lines.extend(["## Protocol", "", f"- primary axis: `{metrics['protocol']['primary_axis']}`", f"- Unknown policy: {metrics['protocol']['unknown_prediction_policy']}", f"- ambiguous policy: {metrics['protocol']['ambiguous_gold_policy']}", f"- score policy: {metrics['protocol']['score_policy']}", ""])
    return "\n".join(lines)
