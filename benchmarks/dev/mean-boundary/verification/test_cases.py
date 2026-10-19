import unittest
from stats import mean

class IndependentTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(mean([7]),7)
    def test_case_1(self):
        self.assertEqual(mean([-2,-4]),-3)
    def test_case_2(self):
        self.assertEqual(mean([2,4,6]),4)
    def test_case_3(self):
        with self.assertRaises(ValueError): mean([])
