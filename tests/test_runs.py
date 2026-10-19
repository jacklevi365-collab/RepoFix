import tempfile
import json
import shlex
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.runs import RunSpec, run_task, resume_task
from repofix.provider import ScriptedDemo
from test_core import ROOT, TrustedFixtureRunner


class RunTests(unittest.TestCase):
    def test_invalid_limits_are_rejected_before_execution(self):
        for options in ({'context_bytes': 0}, {'task_budget': float('nan')}, {'max_steps': 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                RunSpec(repo=Path('.'), issue=Path('issue.md'), **options)

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
            self.assertEqual(report['model_responses'], 5)
            self.assertEqual(report['tool_calls'], 4)
            self.assertEqual(report['usage']['total_tokens'], 0)
            self.assertTrue((Path(report['output']) / 'report.json').is_file())


    def test_independent_pass_cannot_hide_an_introduced_regression(self):
        class BrokenRepair(ScriptedDemo):
            def complete(self,messages,tools):
                step=self.step
                message,usage=super().complete(messages,tools)
                if step==2:
                    call=message['tool_calls'][0]['function']
                    args=json.loads(call['arguments'])
                    edit='from pathlib import Path; p=Path("stats.py"); p.write_text(p.read_text().replace("return value", "return 0"))'
                    args['command']+='; python -c '+shlex.quote(edit)
                    call['arguments']=json.dumps(args)
                return message,usage
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'source'
            source.mkdir()
            (source/'stats.py').write_text((ROOT/'examples/tinybug/repo/stats.py').read_text()+'\ndef identity(value):\n    return value\n')
            (source/'test_other.py').write_text('import unittest\nfrom stats import identity\nclass T(unittest.TestCase):\n def test_identity(self): self.assertEqual(identity(9),9)\n')
            with patch('repofix.runs.DockerRunner') as runner,patch('repofix.runs.ScriptedDemo',BrokenRepair):
                runner.side_effect=lambda path,image,verification=None: TrustedFixtureRunner(path,verification)
                report=run_task(RunSpec(repo=source,issue=ROOT/'examples/tinybug/issue.md',
                    verification=ROOT/'examples/tinybug/verification',output=root/'runs',demo=True))
            self.assertEqual(report['verification'],'passed')
            self.assertEqual(report['regression']['status'],'failed')
            self.assertFalse(report['resolved'])


    def test_resume_keeps_run_id_history_and_budget_ledger(self):
        with tempfile.TemporaryDirectory() as tmp,patch('repofix.runs.DockerRunner') as runner:
            runner.side_effect=lambda path,image,verification=None: TrustedFixtureRunner(path,verification)
            first=run_task(RunSpec(repo=ROOT/'examples/tinybug/repo',issue=ROOT/'examples/tinybug/issue.md',
                verification=ROOT/'examples/tinybug/verification',output=Path(tmp),demo=True,max_steps=1))
            self.assertEqual(first['status'],'step_limit')
            result=resume_task(first['output'],max_steps=5)
            self.assertEqual(result['run_id'],first['run_id'])
            self.assertEqual(result['resume_count'],1)
            self.assertEqual(result['config']['max_steps'],5)
            self.assertTrue(result['resolved'])
            self.assertEqual(result['tool_calls'],4)
            self.assertEqual(result['model_responses'],5)
            self.assertEqual(len(list(Path(tmp).glob('budget.sqlite'))),1)


    def test_resume_does_not_reset_a_paid_task_budget(self):
        class PaidFixture:
            model='fixture-model'
            input_price=1
            output_price=1
            max_tokens=64
            def __init__(self,ledger,run_id,task_budget):
                self.ledger,self.run_id,self.limit=ledger,run_id,task_budget
            def complete(self,messages,tools):
                self.ledger.reserve(self.run_id,.6,self.limit)
                return {'role':'assistant','tool_calls':[{'id':'once','function':{'name':'shell','arguments':'{"command":"true"}'}}]},{}
        with tempfile.TemporaryDirectory() as tmp,patch('repofix.runs.DockerRunner') as runner,patch('repofix.runs.DeepSeek',PaidFixture),patch('repofix.runs.load_env_file'):
            runner.side_effect=lambda path,image,verification=None: TrustedFixtureRunner(path,verification)
            first=run_task(RunSpec(repo=ROOT/'examples/tinybug/repo',issue=ROOT/'examples/tinybug/issue.md',
                output=Path(tmp),max_steps=1,task_budget=1))
            result=resume_task(first['output'],max_steps=2)
            self.assertEqual(result['status'],'budget_limit')
            self.assertAlmostEqual(result['estimated_cost_rmb'],.6)
            self.assertEqual(result['tool_calls'],1)
