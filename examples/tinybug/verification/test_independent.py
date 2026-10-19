import unittest
from stats import mean


class IndependentTests(unittest.TestCase):
    def test_singleton(self):
        self.assertEqual(mean([7]), 7)

    def test_negative(self):
        self.assertEqual(mean([-2, -4]), -3)

    def test_empty(self):
        with self.assertRaises(ValueError):
            mean([])
