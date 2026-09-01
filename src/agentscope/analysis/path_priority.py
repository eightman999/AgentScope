"""repository inventory・解析で共有するruntimeファイル優先順位。"""

from __future__ import annotations

from pathlib import Path
import re


def runtime_path_priority(path: str) -> int:
    """runtime本体をtests/examplesや生成物より先に選ぶ決定論的な順位。"""

    normalized = path.replace("\\", "/").strip("/").lower()
    parts = set(normalized.split("/"))
    name = Path(normalized).name
    score = 0

    if "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
        score -= 260
    if any(
        marker in part
        for part in parts
        for marker in ("example", "sample", "demo")
    ):
        score -= 220
    if parts & {"docs", "doc", "notebooks", "benchmark", "benchmarks", "fixtures"}:
        score -= 100
    if ".github" in parts:
        score -= 80
    if parts & {"node_modules", ".venv", "venv", "dist", "build", "site-packages"}:
        score -= 90
    if "templates" in parts or any("{{" in part or "}}" in part for part in parts):
        score -= 180

    if "src" in parts:
        score += 120
    if "packages" in parts or "libs" in parts or "lib" in parts:
        score += 80
    if parts & {
        "agent",
        "agents",
        "runtime",
        "executor",
        "executors",
        "graph",
        "graphs",
        "workflow",
        "workflows",
        "loop",
        "loops",
        "tool",
        "tools",
        "model",
        "models",
        "llm",
    }:
        score += 35
    if re.search(r"(?:agent|executor|runtime|graph|workflow|loop|tool|model|llm)", name):
        score += 20
    return score


def is_runtime_path(path: str) -> bool:
    """実行時本体としてpositive control-flowの根拠に使えるpathか判定する。"""

    normalized = path.replace("\\", "/").strip("/").lower()
    parts = set(normalized.split("/"))
    name = Path(normalized).name
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    if parts & {
        "tests",
        "test",
        "examples",
        "example",
        "samples",
        "sample",
        "demos",
        "demo",
        "docs",
        "doc",
        "notebooks",
        "fixtures",
        "templates",
    }:
        return False
    return not any(
        marker in part
        for part in parts
        for marker in ("-tests", "-examples", "-samples", "-demos")
    )
