import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.experiments import plan_matrix, execute_matrix
from test_core import ROOT


class ExperimentTests(unittest.TestCase):
    def test_default_plan_has_four_profiles_and_does_not_call_models(self):
        with (
            patch("repofix.experiments.DeepSeek") as provider,
            patch("repofix.experiments.run_batch") as batch,
        ):
            plan = plan_matrix(ROOT / "benchmarks/real/manifest.json")
        self.assertEqual(plan["tasks_per_profile"], 3)
        self.assertEqual(plan["maximum_estimated_rmb"], 24)
        self.assertFalse(plan["model_executed"])
        provider.assert_not_called()
        batch.assert_not_called()

    def test_over_budget_or_missing_configuration_blocks_before_preflight(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("repofix.experiments.DeepSeek") as provider,
            patch("repofix.experiments.run_batch") as batch,
            patch("repofix.experiments.load_env_file"),
        ):
            with self.assertRaises(ValueError):
                execute_matrix(ROOT / "benchmarks/real/manifest.json", Path(tmp), task_budget=10)
            provider.assert_not_called()
            provider.side_effect = ValueError("Missing model configuration")
            with self.assertRaises(ValueError):
                execute_matrix(ROOT / "benchmarks/real/manifest.json", Path(tmp))
            batch.assert_not_called()

    def test_execution_preserves_all_profiles_and_links_their_raw_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observed = []

            def batch(manifest, output, mode, **options):
                if mode == "preflight":
                    return {"output": str(root / "preflight"), "results": [{"status": "ready"}]}
                observed.append(options)
                folder = root / f"batch-{len(observed)}"
                folder.mkdir()
                (folder / "summary.json").write_text("{}")
                return {
                    "output": str(folder),
                    "summary": {
                        "task_count": 3,
                        "passed_count": 1,
                        "model_attempted_tasks": 3,
                        "model_success_rate": 1 / 3,
                        "estimated_cost_rmb": 0.1,
                        "duration_seconds": 2,
                    },
                }

            with (
                patch("repofix.experiments.DeepSeek") as provider,
                patch("repofix.experiments.load_env_file"),
                patch("repofix.experiments.run_batch", side_effect=batch),
            ):
                report = execute_matrix(ROOT / "benchmarks/real/manifest.json", root)
            provider.return_value.complete.assert_not_called()
            self.assertEqual(len(observed), 4)
            self.assertEqual(
                {(item["tool_mode"], item["context_mode"]) for item in observed},
                {
                    ("shell", "full"),
                    ("shell", "compact"),
                    ("structured", "full"),
                    ("structured", "compact"),
                },
            )
            self.assertTrue(all(item["total_budget"] == 100 for item in observed))
            self.assertEqual(report["status"], "completed")
            comparison = (Path(report["output"]) / "comparison.md").read_text()
            self.assertIn("../batch-1/summary.json", comparison)
            self.assertIn("33.3%", comparison)
