import tempfile
import unittest
from pathlib import Path
from repofix.evaluation import assess, run_checks
from repofix.workspace import snapshot, export_patch, integrity_violations
from test_core import TrustedFixtureRunner


def result(successful, ids=('a', 'b'), **changes):
    checks = {'test_ids': list(ids), 'tests_run': len(ids), 'collection_errors': [],
              'skipped': [], 'expected_failures': [], 'successful': successful}
    checks.update(changes)
    return {'exit_code': 0 if successful else 1, 'timed_out': False, 'checks': checks}


class EvaluationTests(unittest.TestCase):
    def test_test_output_without_newline_does_not_hide_result_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repo').mkdir()
            (root / 'checks').mkdir()
            (root / 'checks/test_case.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): print("progress", end="")\n')
            run = run_checks(TrustedFixtureRunner(root / 'repo', root / 'checks'))
            self.assertEqual(run['checks']['tests_run'], 1)

    def test_same_count_different_cases_is_rejected(self):
        self.assertEqual(assess(result(False), result(True, ('a', 'c')))['reason'], 'test_set_changed')

    def test_even_one_new_skip_is_rejected(self):
        self.assertEqual(assess(result(False), result(True, skipped=['a']))['reason'], 'newly_skipped_tests')

    def test_zero_tests_import_errors_timeouts_and_prepassing_baseline(self):
        for original, candidate, reason in [
            (result(False), result(True, ()), 'candidate_invalid_suite'),
            (result(False, collection_errors=['missing dependency']), result(True), 'baseline_collection_error'),
            ({**result(False), 'timed_out': True}, result(True), 'baseline_timeout'),
            (result(True), result(True), 'baseline_not_failing'),
            (result(False), result(False), 'candidate_tests_failed'),
            (result(False), result(True, expected_failures=['a']), 'new_expected_failures'),
        ]:
            with self.subTest(reason=reason):
                self.assertEqual(assess(original, candidate)['reason'], reason)

    def test_harness_distinguishes_import_error_from_test_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repo').mkdir()
            (root / 'checks').mkdir()
            test = root / 'checks/test_case.py'
            test.write_text('import missing_repofix_test_dependency\n')
            run = run_checks(TrustedFixtureRunner(root / 'repo', root / 'checks'))
            self.assertTrue(run['checks']['collection_errors'])
            test.write_text('import unittest\nclass T(unittest.TestCase):\n def test_bug(self): self.assertEqual(1, 2)\n')
            run = run_checks(TrustedFixtureRunner(root / 'repo', root / 'checks'))
            self.assertFalse(run['checks']['collection_errors'])
            self.assertEqual(len(run['checks']['failures']), 1)

    def test_harness_loads_stdlib_before_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repo').mkdir()
            (root / 'checks').mkdir()
            (root / 'repo/unittest.py').write_text('raise RuntimeError("shadowed")\n')
            (root / 'checks/test_case.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
            run = run_checks(TrustedFixtureRunner(root / 'repo', root / 'checks'))
            self.assertTrue(run['checks']['successful'])

    def test_existing_test_deletion_and_added_config_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'source').mkdir()
            (root / 'source/test_old.py').write_text('old test\n')
            snapshot(root / 'source', root / 'work')
            (root / 'work/test_old.py').unlink()
            (root / 'work/conftest.py').write_text('# bypass\n')
            (root / 'work/test_reproduction.py').write_text('# permitted new test\n')
            export_patch(root / 'work', root / 'patch.diff')
            self.assertEqual(integrity_violations(root / 'work'), ['conftest.py', 'test_old.py'])
