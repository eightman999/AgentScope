from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agentscope.acquisition.artifacts import ArtifactStore
from agentscope.application import audit_local_directory

from tests.helpers import complete_script, fixture, mock_provider


class _SubprocessMonitor:
    """対象repo実行の混入を実プロセス呼び出しで検出する。"""

    allowed_git_subcommands = {"log", "remote"}
    forbidden_executables = {
        "bash",
        "bun",
        "cargo",
        "gradle",
        "make",
        "mvn",
        "node",
        "npm",
        "pip",
        "pip3",
        "pnpm",
        "pytest",
        "python",
        "python3",
        "ruby",
        "sh",
        "yarn",
    }

    def __init__(self, real_run):
        self.real_run = real_run
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        argv = [str(item) for item in args]
        self.calls.append(argv)
        executable = Path(argv[0]).name if argv else ""
        if executable in self.forbidden_executables:
            raise AssertionError(f"forbidden target executable was invoked: {argv}")
        if executable != "git" or len(argv) < 2:
            raise AssertionError(f"unexpected subprocess during audit: {argv}")
        if argv[1] not in self.allowed_git_subcommands:
            raise AssertionError(f"unapproved git subprocess during audit: {argv}")
        return self.real_run(args, **kwargs)


class SubprocessMonitorTests(unittest.TestCase):
    def test_audit_does_not_execute_target_setup_package_or_test_files(self) -> None:
        real_run = subprocess.run
        monitor = _SubprocessMonitor(real_run)
        with tempfile.TemporaryDirectory() as directory:
            with patch("subprocess.run", side_effect=monitor):
                result = audit_local_directory(
                    fixture("execution_traps"),
                    artifacts=ArtifactStore.create(Path(directory), "run"),
                    provider=mock_provider(complete_script()),
                )

        self.assertEqual(result.report["runtime"]["termination"], "ENOUGH_EVIDENCE")
        self.assertGreaterEqual(len(monitor.calls), 2)
        self.assertTrue(all(call[0] == "git" for call in monitor.calls))
        self.assertTrue(all(call[1] in {"log", "remote"} for call in monitor.calls))
        self.assertIn("setup.py", result.context.inventory.paths())
        self.assertIn("package.json", result.context.inventory.paths())
        self.assertIn("tests/test_trap.py", result.context.inventory.paths())


if __name__ == "__main__":
    unittest.main()
