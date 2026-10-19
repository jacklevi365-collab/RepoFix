import unittest
from paging import paginate

class IndependentTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(paginate(list(range(5)),1,2),[0,1])
    def test_case_1(self):
        self.assertEqual(paginate(list(range(5)),3,2),[4])
    def test_case_2(self):
        self.assertEqual(paginate([],1,2),[])
    def test_case_3(self):
        with self.assertRaises(ValueError): paginate([1],0,2)
