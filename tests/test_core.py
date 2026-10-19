import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.agent import Agent
from repofix.budget import BudgetExceeded, Ledger
from repofix.provider import DeepSeek, ScriptedDemo
from repofix.process import execute
from repofix.workspace import snapshot, export_patch, patched_workspace, integrity_violations
from repofix.evaluation import run_checks, assess

ROOT = Path(__file__).resolve().parents[1]


class TrustedFixtureRunner:
    """Host execution is test-only and restricted to our scripted fixture."""
    def __init__(self, workspace, verification=None):
        self.workspace = workspace
        self.verification = verification

    def run(self, command, timeout=30):
        command = command.replace('/workspace', str(self.workspace))
        if self.verification:
            command = command.replace('/verification', str(self.verification))
        return execute(['sh', '-c', 'cd "$1" && ' + command, 'fixture', str(self.workspace)], timeout)


class CoreTests(unittest.TestCase):
    def test_scripted_repair_and_fresh_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = ROOT / 'examples/tinybug/repo'
            before = (source / 'stats.py').read_text()
            snapshot(source, folder / 'workspace')
            agent = Agent(ScriptedDemo(), TrustedFixtureRunner(folder / 'workspace'), folder / 'trace.jsonl')
            report = agent.run('Fix mean')
            self.assertEqual(report['status'], 'candidate')
            self.assertTrue(export_patch(folder / 'workspace', folder / 'patch.diff'))
            patched_workspace(source, folder / 'patch.diff', folder / 'fresh')
            result = run_checks(TrustedFixtureRunner(folder / 'fresh', ROOT / 'examples/tinybug/verification'))
            baseline = run_checks(TrustedFixtureRunner(source, ROOT / 'examples/tinybug/verification'))
            self.assertEqual(assess(baseline, result)['status'], 'passed')
            self.assertEqual(result['exit_code'], 0, result)
            self.assertEqual((source / 'stats.py').read_text(), before)
            events = [json.loads(line) for line in (folder / 'trace.jsonl').read_text().splitlines()]
            tools = [e for e in events if e['kind'] == 'tool']
            self.assertNotEqual(tools[1]['result']['exit_code'], 0)
            self.assertEqual(tools[-1]['result']['exit_code'], 0)

    def test_budget_reservations_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'budget.sqlite'
            ledger = Ledger(path, 1)
            call = ledger.reserve('first', .6, .8)
            with self.assertRaises(BudgetExceeded):
                Ledger(path, 1).reserve('second', .5, 1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve('first', .3, .8)
            ledger.settle(call, .1)
            ledger.reserve('second', .5, 1)
            self.assertAlmostEqual(ledger.spent('first'), .1)

    def test_transport_failure_keeps_reservation_and_does_not_retry(self):
        env = {'DEEPSEEK_API_KEY': 'not-real', 'REPOFIX_INPUT_RMB_PER_MILLION': '2',
               'REPOFIX_OUTPUT_RMB_PER_MILLION': '3'}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env):
            ledger = Ledger(Path(tmp) / 'budget.sqlite')
            provider = DeepSeek(ledger, 'run')
            with patch('urllib.request.urlopen', side_effect=TimeoutError) as http:
                with self.assertRaises(TimeoutError):
                    provider.complete([], [])
            self.assertEqual(http.call_count, 1)
            self.assertGreater(ledger.spent('run'), 0)

    def test_process_timeout_and_output_bound(self):
        result = execute(['python3', '-c', 'import time; print("x",flush=True); time.sleep(3)'], timeout=.1)
        self.assertTrue(result['timed_out'])
        result = execute(['python3', '-c', 'print("x"*1000)'], limit=40)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['output']), 40)

    def test_snapshot_rejects_outside_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (source / 'external').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                snapshot(source, root / 'target')

    def test_new_files_exported_in_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            snapshot(source, root / 'work')
            (root / 'work/new.py').write_text('answer = 42\n')
            self.assertTrue(export_patch(root / 'work', root / 'patch.diff'))
            self.assertIn('new.py', (root / 'patch.diff').read_text())

    def test_step_limit_stops_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Runner:
                def run(self, command):
                    return {'exit_code': 0, 'output': ''}
            report = Agent(ScriptedDemo(), Runner(), Path(tmp) / 'trace', max_steps=1).run('fix')
            self.assertEqual(report['status'], 'step_limit')


if __name__ == '__main__':
    unittest.main()
