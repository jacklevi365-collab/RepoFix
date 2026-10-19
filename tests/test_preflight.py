import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.cli import main
from repofix.preflight import prepare_baseline
from test_core import TrustedFixtureRunner


class PreflightTests(unittest.TestCase):
    def prepare(self, code):
        folder = Path(self.tmp.name)
        repo, checks = folder / "repo", folder / "checks"
        repo.mkdir()
        checks.mkdir()
        (checks / "test_precheck.py").write_text(code)
        return repo, checks

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_existing_success_and_missing_dependencies_block_run(self):
        repo, checks = self.prepare(
            "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n"
        )
        report = prepare_baseline(
            repo, checks, Path(self.tmp.name) / "baseline", TrustedFixtureRunner
        )
        self.assertFalse(report["ready"])
        self.assertEqual(report["reason"], "baseline_not_failing")

    def test_import_error_is_environment_failure(self):
        repo, checks = self.prepare("import missing_repofix_dependency\n")
        report = prepare_baseline(
            repo, checks, Path(self.tmp.name) / "baseline", TrustedFixtureRunner
        )
        self.assertEqual(report["reason"], "baseline_collection_error")

    def test_cli_never_calls_model_on_failed_preflight(self):
        repo, checks = self.prepare(
            "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n"
        )
        issue = Path(self.tmp.name) / "issue.md"
        issue.write_text("Fix this issue")
        output = Path(self.tmp.name) / "runs"
        argv = [
            "repofix",
            "run",
            "--repo",
            str(repo),
            "--issue",
            str(issue),
            "--verification",
            str(checks),
            "--output",
            str(output),
        ]
        with (
            patch("sys.argv", argv),
            patch("repofix.runs.DockerRunner") as runner,
            patch("repofix.runs.DeepSeek") as provider,
        ):
            provider.return_value.model = "fake-deepseek"
            runner.side_effect = lambda path, image, verification=None: TrustedFixtureRunner(
                path, verification
            )
            with patch("builtins.print"), self.assertRaises(SystemExit) as exit:
                main()
            self.assertEqual(exit.exception.code, 1)
            provider.return_value.complete.assert_not_called()
        report = json.loads(next(output.glob("*/report.json")).read_text())
        self.assertEqual(report["status"], "preflight_failed")
        self.assertEqual(report["estimated_cost_rmb"], 0)
