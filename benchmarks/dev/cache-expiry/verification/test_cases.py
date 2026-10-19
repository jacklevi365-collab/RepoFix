import unittest
from cache import Cache

class IndependentTests(unittest.TestCase):
    def test_case_0(self):
        c=Cache(); c.put("a",7,10); self.assertIsNone(c.get("a",10)); self.assertNotIn("a",c.entries)
    def test_case_1(self):
        c=Cache(); c.put("a",7,10); self.assertEqual(c.get("a",9),7)
    def test_case_2(self):
        self.assertIsNone(Cache().get("missing",0))
