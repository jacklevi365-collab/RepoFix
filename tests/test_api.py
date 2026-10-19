import tempfile
import time
import unittest
from pathlib import Path
from repofix.jobs import JobStore
from test_core import ROOT
try:
    from fastapi.testclient import TestClient
    from repofix.api import create_app
except ImportError:
    TestClient = None


class JobStoreTests(unittest.TestCase):
    def test_idempotency_cancel_and_interrupted_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=JobStore(Path(tmp)/'jobs.sqlite')
            first,created=store.create({'task_id':'a'},'same')
            second,created_again=store.create({'task_id':'a'},'same')
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(first['id'],second['id'])
            with self.assertRaises(ValueError):
                store.create({'task_id':'different'},'same')
            self.assertTrue(store.cancel(first['id']))
            self.assertFalse(store.start(first['id']))
            pending,_=store.create({'task_id':'b'})
            store.start(pending['id'])
            JobStore(Path(tmp)/'jobs.sqlite').recover()
            self.assertEqual(store.get(pending['id'])['status'],'interrupted')
            self.assertEqual(store.get(first['id'])['status'],'cancelled')


@unittest.skipIf(TestClient is None,'Optional web dependencies are not installed')
class ApiTests(unittest.TestCase):
    def test_async_submission_event_replay_and_artifact_download(self):
        calls=[]
        def execute(spec,on_event):
            calls.append(spec)
            on_event({'kind':'tool','result':{'exit_code':0}})
            folder=spec.output/'fixture'
            folder.mkdir(exist_ok=True)
            (folder/'patch.diff').write_text('fixture patch')
            return {'status':'candidate','verification':'passed','resolved':True,'output':str(folder)}
        with tempfile.TemporaryDirectory() as tmp:
            app=create_app(ROOT,Path(tmp),executor=execute)
            with TestClient(app,base_url='http://localhost') as client:
                self.assertEqual(client.get('/').status_code,200)
                self.assertIn('RepoFix',client.get('/').text)
                self.assertEqual(client.get('/static/app.js').status_code,200)
                self.assertEqual(client.get('/api/experiments').json(),[])
                payload={'task_id':'demo-tinybug','mode':'demo'}
                response=client.post('/api/jobs',json=payload,headers={'Idempotency-Key':'once'})
                self.assertEqual(response.status_code,202)
                job_id=response.json()['id']
                duplicate=client.post('/api/jobs',json=payload,headers={'Idempotency-Key':'once'})
                self.assertEqual(duplicate.json()['id'],job_id)
                for _ in range(100):
                    job=client.get('/api/jobs/'+job_id).json()
                    if job['status']=='completed': break
                    time.sleep(.01)
                self.assertEqual(job['status'],'completed')
                self.assertEqual(len(calls),1)
                events=client.get(f'/api/jobs/{job_id}/events').text
                self.assertIn('"kind": "tool"',events)
                self.assertIn('event: done',events)
                self.assertEqual(client.get(f'/api/jobs/{job_id}/artifacts/patch.diff').text,'fixture patch')
                self.assertEqual(client.get(f'/api/jobs/{job_id}/artifacts/.env').status_code,404)

    def test_rejects_foreign_origin_unknown_task_and_extra_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(ROOT,Path(tmp)),base_url='http://localhost') as client:
                self.assertEqual(client.post('/api/jobs',json={'task_id':'demo-tinybug'},headers={'Origin':'https://foreign.example'}).status_code,403)
                self.assertEqual(client.post('/api/jobs',json={'task_id':'unknown'}).status_code,404)
                self.assertEqual(client.post('/api/jobs',json={'task_id':'demo-tinybug','repo':'/etc'}).status_code,422)
                self.assertEqual(client.get('/api/health',headers={'Host':'foreign.example'}).status_code,400)
