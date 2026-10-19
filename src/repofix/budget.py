import math
import sqlite3


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Reserve before HTTP; ambiguous failures retain the full reservation."""
    def __init__(self, path, total_limit=100.0):
        self.path, self.total_limit = path, total_limit
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, run TEXT, amount REAL, state TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, run, amount, task_limit):
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Reservation must be finite and positive")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COALESCE(SUM(amount),0) FROM calls").fetchone()[0]
            task = db.execute("SELECT COALESCE(SUM(amount),0) FROM calls WHERE run=?", (run,)).fetchone()[0]
            if total + amount > self.total_limit or task + amount > task_limit:
                raise BudgetExceeded("Next call exceeds configured estimated budget")
            return db.execute("INSERT INTO calls(run,amount,state) VALUES(?,?,?)",
                              (run, amount, "reserved")).lastrowid

    def settle(self, call_id, amount):
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid actual cost")
        with self.connect() as db:
            db.execute("UPDATE calls SET amount=?,state='settled' WHERE id=?", (amount, call_id))

    def spent(self, run):
        with self.connect() as db:
            return db.execute("SELECT COALESCE(SUM(amount),0) FROM calls WHERE run=?", (run,)).fetchone()[0]
