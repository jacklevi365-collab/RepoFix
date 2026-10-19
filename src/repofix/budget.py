import math
import sqlite3


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Reserve before HTTP; ambiguous failures retain the full reservation."""

    def __init__(self, path, total_limit=100.0):
        self.path, self.total_limit = path, total_limit
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, run TEXT, amount REAL, state TEXT)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, run, amount, task_limit):
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Reservation must be finite and positive")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COALESCE(SUM(amount),0) FROM calls").fetchone()[0]
            task = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM calls WHERE run=?", (run,)
            ).fetchone()[0]
            if total + amount > self.total_limit or task + amount > task_limit:
                raise BudgetExceeded("Next call exceeds configured estimated budget")
            return db.execute(
                "INSERT INTO calls(run,amount,state) VALUES(?,?,?)",
                (run, amount, "reserved"),
            ).lastrowid

    def settle(self, call_id, amount):
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid actual cost")
        with self.connect() as db:
            db.execute(
                "UPDATE calls SET amount=?,state='settled' WHERE id=?",
                (amount, call_id),
            )

    def spent(self, run):
        with self.connect() as db:
            return db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM calls WHERE run=?", (run,)
            ).fetchone()[0]

    def summary(self, run=None):
        where, parameters = (" WHERE run=?", (run,)) if run is not None else ("", ())
        with self.connect() as db:
            rows = db.execute(
                "SELECT state,COUNT(*),COALESCE(SUM(amount),0) FROM calls"
                + where
                + " GROUP BY state",
                parameters,
            ).fetchall()
        counts = {state: count for state, count, _ in rows}
        amounts = {state: amount for state, _, amount in rows}
        return {
            "estimated_total_rmb": sum(amounts.values()),
            "reserved_rmb": amounts.get("reserved", 0),
            "settled_rmb": amounts.get("settled", 0),
            "request_reservations": sum(counts.values()),
            "unsettled_requests": counts.get("reserved", 0),
            "limit_rmb": self.total_limit,
        }
