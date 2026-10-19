import unittest
from more_itertools import bucket
class BucketRegression(unittest.TestCase):
    def test_false_callable_rejects(self):
        class Allowed(set):
            def __call__(self,key): return key in self
        b=bucket([10,20,11],key=lambda x:x,validator=Allowed())
        self.assertEqual(list(b[10]),[])
        self.assertNotIn(10,b)
        self.assertEqual(list(b),[])
    def test_false_callable_can_accept_selected_keys(self):
        class Validator:
            def __bool__(self): return False
            def __call__(self,key): return key%2==0
        b=bucket([1,2,3],key=lambda x:x,validator=Validator())
        self.assertEqual(list(b[1]),[])
        self.assertEqual(list(b[2]),[2])
    def test_default_validator(self):
        b=bucket([1,2],key=lambda x:x)
        self.assertEqual(list(b[1]),[1])
