import json
import tempfile
import unittest
from pathlib import Path
from repofix.agent import Agent
from repofix.checkpoint import UnsafeResume, load_checkpoint, run_lock
from repofix.workspace import snapshot,snapshot_committed


class CheckpointTests(unittest.TestCase):
    def test_resume_uses_completed_tool_result_without_replaying_command(self):
        calls=[]
        class Runner:
            def run(self,command):
                calls.append(command)
                return {'exit_code':0,'output':'done'}
        class Provider:
            def complete(self,messages,tools):
                if not any(message['role']=='tool' for message in messages):
                    return {'role':'assistant','tool_calls':[{'id':'c1','function':{'name':'shell','arguments':json.dumps({'command':'one-time-action'})}}]},{}
                return {'role':'assistant','content':'finished'},{}
        with tempfile.TemporaryDirectory() as tmp:
            trace=Path(tmp)/'trace.jsonl'
            self.assertEqual(Agent(Provider(),Runner(),trace,max_steps=1).run('fix')['status'],'step_limit')
            self.assertEqual(load_checkpoint(trace.parent/'checkpoint.json')['phase'],'ready')
            result=Agent(Provider(),Runner(),trace,max_steps=2).run('fix',resume=True)
            self.assertEqual(result['status'],'candidate')
            self.assertEqual(calls,['one-time-action'])
            # A completed model response can be re-verified without a paid call.
            result=Agent(None,None,trace).run('fix',resume=True)
            self.assertEqual(result['status'],'candidate')

    def test_ambiguous_tool_round_refuses_replay(self):
        class Provider:
            def complete(self,messages,tools):
                return {'role':'assistant','tool_calls':[{'id':'c','function':{'name':'shell','arguments':'{"command":"write"}'}}]},{}
        class Runner:
            def run(self,command):
                raise RuntimeError('Interrupted after unknown side effect')
        with tempfile.TemporaryDirectory() as tmp:
            trace=Path(tmp)/'trace.jsonl'
            with self.assertRaises(RuntimeError):
                Agent(Provider(),Runner(),trace).run('fix')
            with self.assertRaises(UnsafeResume):
                Agent(None,None,trace).run('fix',resume=True)

    def test_committed_snapshot_ignores_mutated_baseline_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'source').mkdir()
            (root/'source/code.py').write_text('original\n')
            snapshot(root/'source',root/'baseline')
            (root/'baseline/code.py').write_text('test side effect\n')
            snapshot_committed(root/'baseline',root/'clean')
            self.assertEqual((root/'clean/code.py').read_text(),'original\n')


    def test_run_lock_refuses_concurrent_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            with run_lock(Path(tmp)),self.assertRaises(UnsafeResume):
                with run_lock(Path(tmp)):
                    pass
