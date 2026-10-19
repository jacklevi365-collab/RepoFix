import unittest
from router import matches

class IndependentTests(unittest.TestCase):
    def test_case_0(self):
        self.assertTrue(matches("/users/","users"))
    def test_case_1(self):
        self.assertFalse(matches("/users","/users/1"))
    def test_case_2(self):
        self.assertTrue(matches("/",""))
    def test_case_3(self):
        self.assertFalse(matches("/a//b","/a/b"))
