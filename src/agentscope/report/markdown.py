"""日本語Markdown report。"""

from __future__ import annotations

from typing import Any


def _score_text(score: float | None) -> str:
    return "?" if score is None else f"{score:.1f}"


def render_markdown(report: dict[str, Any]) -> str:
    subject = report["subject"]
    runtime = report["runtime"]
    lines = [
        "# AgentScope audit report",
        "",
        f"- 対象: {subject['canonical_url']}",
        f"- commit: {subject['commit_sha']}",
        f"- snapshot coverage: {subject['snapshot_coverage']}",
        f"- model: {runtime['model_id']}",
        f"- runtime: {runtime['engine']}",
        f"- termination: {runtime['termination']}",
        "",
        "## 評価score",
        "",
        "| 評価score | score / 10 | 状態 | confidence | 根拠 |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for item in report["scores"]:
        refs = "、".join(
            report_evidence_ref(report, evidence_id)
            for evidence_id in item["evidence_ids"]
        )
        lines.append(
            f"| {item['label']} | {_score_text(item['score'])} | "
            f"{item['state']} | {item['confidence']} | {refs} |"
        )
    lines.extend(["", "## 区別", "", "| 判定 | 結果 | confidence | 根拠 |", "| --- | --- | --- | --- |"])
    labels = {
        "ai_assisted_development": "AI-assisted development",
        "agentic_runtime": "Agentic runtime",
        "mcp_tooling": "MCP/tooling",
        "formal_github_fork": "Formal GitHub fork",
        "derived_concept": "Derived concept",
    }
    for key in (
        "ai_assisted_development",
        "agentic_runtime",
        "mcp_tooling",
        "formal_github_fork",
        "derived_concept",
    ):
        item = report["classifications"][key]
        value = item["value"]
        if key == "derived_concept" and value == "yes" and item.get("label"):
            value = f"yes — {item['label']}"
        refs = "、".join(
            report_evidence_ref(report, evidence_id)
            for evidence_id in item["evidence_ids"]
        )
        lines.append(f"| {labels[key]} | {value} | {item['confidence']} | {refs} |")
    lines.extend(
        [
            "",
            "## 根拠",
            "",
        ]
    )
    for evidence in report["evidence"]:
        excerpt = evidence["excerpt"].replace("\n", " / ")
        lines.append(
            f"- {evidence['id']} {evidence['display_ref']}: "
            f"{evidence['reason']} — {excerpt}"
        )
    lines.extend(["", "## unknowns", ""])
    if report["unknowns"]:
        lines.extend(f"- {item}" for item in report["unknowns"])
    else:
        lines.append("- なし")
    lines.extend(["", "## 実行trace", "", f"- 詳細: {report['action_trace_ref']}"])
    return "\n".join(lines) + "\n"


def report_evidence_ref(report: dict[str, Any], evidence_id: str) -> str:
    for item in report["evidence"]:
        if item["id"] == evidence_id:
            return item["display_ref"]
    return f"missing-evidence:{evidence_id}"

