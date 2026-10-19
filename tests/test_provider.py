import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from repofix.budget import Ledger
from repofix.provider import DeepSeek
from repofix.agent import Agent


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.environment=patch.dict(os.environ,{'DEEPSEEK_API_KEY':'fixture-key',
            'REPOFIX_INPUT_RMB_PER_MILLION':'2','REPOFIX_OUTPUT_RMB_PER_MILLION':'3'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.ledger=Ledger(Path(self.tmp.name)/'budget.sqlite')

    def test_official_style_tool_response_usage_and_request_body(self):
        response={'id':'fixture-response','model':'fixture-model','choices':[{'finish_reason':'tool_calls',
            'message':{'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function',
                'function':{'name':'shell','arguments':'{"command":"ls"}'}}]}}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
        provider=DeepSeek(self.ledger,'task')
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as http:
            message,usage=provider.complete([{'role':'user','content':'fix'}],[])
        payload=json.loads(http.call_args.args[0].data)
        self.assertEqual(payload['thinking'],{'type':'disabled'})
        self.assertEqual(message['tool_calls'][0]['id'],'c1')
        self.assertEqual(usage['total_tokens'],120)
        self.assertAlmostEqual(self.ledger.spent('task'),.00026)
        self.assertEqual(provider.last_response_metadata['model'],'fixture-model')
        self.assertEqual(http.call_count,1)

    def test_http_error_has_no_key_or_body_and_keeps_reservation(self):
        provider=DeepSeek(self.ledger,'task')
        error=urllib.error.HTTPError('https://api.deepseek.com/chat/completions',401,'fixture secret body',None,None)
        with patch('urllib.request.urlopen',side_effect=error),self.assertRaises(RuntimeError) as caught:
            provider.complete([],[])
        self.assertNotIn('fixture-key',str(caught.exception))
        self.assertNotIn('fixture secret body',str(caught.exception))
        self.assertGreater(self.ledger.spent('task'),0)

    def test_truncated_tool_call_is_never_executed(self):
        class Truncated:
            last_response_metadata={'finish_reason':'length'}
            def complete(self,messages,tools):
                return {'role':'assistant','tool_calls':[{'id':'c','function':{'name':'shell','arguments':'{"command":"bad'}}]},{}
        with patch('repofix.agent.RepositoryTools') as tools:
            report=Agent(Truncated(),None,Path(self.tmp.name)/'trace.jsonl').run('fix')
            tools.return_value.execute.assert_not_called()
        self.assertEqual(report['status'],'model_output_limit')
