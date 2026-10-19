import unittest
from more_itertools import split_before,split_after,split_when,split_at
class SplitRegression(unittest.TestCase):
    def test_empty_before(self):
        for limit in (-1,0,1):
            with self.subTest(limit=limit): self.assertEqual(list(split_before([],bool,maxsplit=limit)),[])
    def test_empty_after(self):
        self.assertEqual(list(split_after(iter([]),bool,maxsplit=0)),[])
    def test_empty_when(self):
        self.assertEqual(list(split_when('',lambda a,b:a!=b,maxsplit=0)),[])
    def test_nonempty_and_split_at_compatibility(self):
        self.assertEqual(list(split_before([1,2],bool,maxsplit=0)),[[1,2]])
        self.assertEqual(list(split_after([1,2],bool,maxsplit=0)),[[1,2]])
        self.assertEqual(list(split_when([1,2],lambda a,b:True,maxsplit=0)),[[1,2]])
        self.assertEqual(list(split_at([],bool,maxsplit=0)),[[]])
