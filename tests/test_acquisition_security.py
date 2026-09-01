from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

from agentscope.acquisition.github_url import parse_github_url
from agentscope.acquisition.git_snapshot import (
    AcquisitionError,
    GitSnapshotSource,
    run_git,
)


class _RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self.server.redirect_hits += 1
        self.send_response(302)
        self.send_header("Location", self.server.redirect_location)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return None


class _SinkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self.server.sink_hits += 1
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return None


class AcquisitionSecurityTests(unittest.TestCase):
    def test_clone_command_rejects_http_redirects(self) -> None:
        calls: list[list[str]] = []

        def runner(args: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(list(args))
            if args[1] == "clone":
                Path(args[-1]).mkdir()
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="a" * 40, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "snapshot"
            snapshot = GitSnapshotSource(runner=runner).acquire(
                parse_github_url("https://github.com/fixture/repository"),
                destination,
            )

        self.assertEqual(snapshot.commit_sha, "a" * 40)
        self.assertEqual(calls[0][0:4], ["git", "clone", "-c", "http.followRedirects=false"])
        self.assertEqual(calls[1], ["git", "rev-parse", "HEAD"])

    def test_real_git_clone_does_not_follow_redirect_to_other_host(self) -> None:
        sink = ThreadingHTTPServer(("127.0.0.1", 0), _SinkHandler)
        sink.sink_hits = 0
        sink_thread = threading.Thread(target=sink.serve_forever, daemon=True)
        sink_thread.start()

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        redirect.redirect_hits = 0
        redirect.redirect_location = (
            f"http://localhost:{sink.server_address[1]}/repo.git"
        )
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        try:
            ref = SimpleNamespace(
                clone_url=f"http://127.0.0.1:{redirect.server_address[1]}/repo.git"
            )
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(AcquisitionError):
                    GitSnapshotSource().acquire(ref, Path(directory) / "snapshot")
            self.assertGreaterEqual(redirect.redirect_hits, 1)
            self.assertEqual(sink.sink_hits, 0)
        finally:
            redirect.shutdown()
            redirect.server_close()
            sink.shutdown()
            sink.server_close()
            redirect_thread.join(timeout=2)
            sink_thread.join(timeout=2)

    def test_git_allowlist_rejects_unapproved_subcommands(self) -> None:
        with self.assertRaises(AcquisitionError):
            run_git(["git", "status"])


if __name__ == "__main__":
    unittest.main()
