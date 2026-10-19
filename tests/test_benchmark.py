import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.benchmark import load_manifest, run_batch, summarize
from test_core import ROOT, TrustedFixtureRunner


class BenchmarkTests(unittest.TestCase):
    def test_three_pinned_upstream_regressions_are_valid(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("repofix.benchmark.DockerRunner") as runner,
        ):
            runner.side_effect = lambda path, image, verification=None: TrustedFixtureRunner(
                path, verification
            )
            report = run_batch(ROOT / "benchmarks/real/manifest.json", Path(tmp), mode="reference")
            self.assertEqual(report["summary"]["passed_count"], 3)
            self.assertEqual(report["provenance"], "public-upstream-history")
            self.assertIsNone(report["summary"]["model_success_rate"])
            self.assertTrue(all(item["source"]["base_commit"] for item in report["results"]))

    def test_all_reference_patches_reproduce_and_fix_the_development_tasks(self):
        manifest = ROOT / "benchmarks/dev/manifest.json"
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("repofix.benchmark.DockerRunner") as runner,
        ):
            runner.side_effect = lambda path, image, verification=None: TrustedFixtureRunner(
                path, verification
            )
            report = run_batch(manifest, Path(tmp), mode="reference")
            self.assertEqual(report["summary"]["task_count"], 5)
            self.assertEqual(report["summary"]["passed_count"], 5, report)
            self.assertIsNone(report["summary"]["model_success_rate"])
            self.assertEqual(report["summary"]["reference_validation_rate"], 1)
            self.assertEqual(report["summary"]["estimated_cost_rmb"], 0)
            self.assertEqual(report["provenance"], "synthetic")

    def test_failures_are_in_model_metric_denominator(self):
        results = [
            {"status": "candidate", "resolved": True},
            {"status": "budget_limit", "resolved": False},
        ]
        self.assertEqual(summarize(results, "model")["model_success_rate"], 0.5)
        self.assertIsNone(summarize(results, "reference")["model_success_rate"])

    def test_duplicate_ids_and_unknown_selection_fail_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "tasks.json"
            data = json.loads((ROOT / "benchmarks/dev/manifest.json").read_text())
            data["tasks"] = [{"id": "same"}, {"id": "same"}]
            manifest.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_manifest(manifest)
            with self.assertRaises(ValueError):
                run_batch(
                    ROOT / "benchmarks/dev/manifest.json",
                    Path(tmp),
                    task_ids=["unknown"],
                )
