import copy
import unittest
from repofix.context import compact_messages, message_bytes


class ContextTests(unittest.TestCase):
    def test_compression_preserves_message_protocol_and_latest_tool_result(self):
        messages = [{'role':'system','content':'rules'},{'role':'user','content':'issue'},
                    {'role':'assistant','tool_calls':[{'id':'old','function':{'name':'shell','arguments':'{}'}}]},
                    {'role':'tool','tool_call_id':'old','content':'HEAD'+ 'x'*20000+'TEST_FAILURE'},
                    {'role':'assistant','tool_calls':[{'id':'new','function':{'name':'shell','arguments':'{}'}}]},
                    {'role':'tool','tool_call_id':'new','content':'latest'+ 'y'*5000}]
        original = copy.deepcopy(messages)
        compacted, stats = compact_messages(messages, 20000)
        self.assertLess(message_bytes(compacted), message_bytes(messages))
        self.assertEqual(messages, original)
        self.assertEqual([m['role'] for m in compacted], [m['role'] for m in messages])
        self.assertEqual(compacted[3]['tool_call_id'], 'old')
        self.assertIn('TEST_FAILURE', compacted[3]['content'])
        self.assertEqual(compacted[-1], original[-1])
        self.assertEqual(stats['trimmed_results'], 1)

    def test_small_context_is_unchanged(self):
        messages=[{'role':'user','content':'short'}]
        compacted,stats=compact_messages(messages,10000)
        self.assertEqual(compacted,messages)
        self.assertEqual(stats['trimmed_results'],0)
