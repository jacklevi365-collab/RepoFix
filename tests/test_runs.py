import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.runs import RunSpec, run_task
from test_core import ROOT, TrustedFixtureRunner


class RunTests(unittest.TestCase):
    def test_task_report_is_reproducible_and_labels_scripted_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch('repofix.runs.DockerRunner') as runner:
            runner.side_effect = lambda path, image, verification=None: TrustedFixtureRunner(path, verification)
            report = run_task(RunSpec(repo=ROOT / 'examples/tinybug/repo',
                                     issue=ROOT / 'examples/tinybug/issue.md',
                                     verification=ROOT / 'examples/tinybug/verification',
                                     output=Path(tmp), demo=True, task_id='tinybug'))
            self.assertTrue(report['resolved'])
            self.assertEqual(report['evidence_type'], 'scripted')
            self.assertEqual(len(report['source_tree']), 40)
            self.assertEqual(len(report['issue_sha256']), 64)
            self.assertGreater(report['duration_seconds'], 0)
            self.assertEqual(report['estimated_cost_rmb'], 0)
            self.assertTrue((Path(report['output']) / 'report.json').is_file())
