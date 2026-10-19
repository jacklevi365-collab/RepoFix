import unittest
from billing import total
from decimal import Decimal

class IndependentTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(total(["0.1","0.2"]),Decimal("0.3"))
    def test_case_1(self):
        self.assertEqual(total([]),Decimal(0))
    def test_case_2(self):
        self.assertEqual(total(["10.25","-0.25"]),Decimal("10.00"))
