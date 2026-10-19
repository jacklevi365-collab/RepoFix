import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from repofix.budget import BudgetExceeded, Ledger


class BudgetTests(unittest.TestCase):
    def test_summary_separates_unresolved_reservations_from_settled_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "budget.sqlite")
            first = ledger.reserve("a", 0.6, 2)
            ledger.settle(first, 0.1)
            ledger.reserve("b", 0.4, 2)
            summary = ledger.summary()
            self.assertAlmostEqual(summary["estimated_total_rmb"], 0.5)
            self.assertAlmostEqual(summary["reserved_rmb"], 0.4)
            self.assertAlmostEqual(summary["settled_rmb"], 0.1)
            self.assertEqual(summary["unsettled_requests"], 1)
            self.assertEqual(ledger.summary("a")["request_reservations"], 1)

    def test_concurrent_requests_cannot_both_reserve_beyond_the_shared_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "budget.sqlite", total_limit=1)
            barrier = Barrier(2)

            def reserve(name):
                barrier.wait()
                try:
                    ledger.reserve(name, 0.6, 1)
                    return True
                except BudgetExceeded:
                    return False

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(reserve, ["a", "b"]))
            self.assertEqual(sum(results), 1)
            self.assertAlmostEqual(ledger.summary()["estimated_total_rmb"], 0.6)
