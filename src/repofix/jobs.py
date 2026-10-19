"""Durable local job queue and replayable event log."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class QueueFull(RuntimeError):
    pass


class JobStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE, payload TEXT,
                    status TEXT, created_at TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, data TEXT);
                CREATE INDEX IF NOT EXISTS events_job ON events(job_id,seq);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self, payload, request_key=None):
        encoded = json.dumps(payload, sort_keys=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if request_key:
                existing = db.execute('SELECT * FROM jobs WHERE request_key=?', (request_key,)).fetchone()
                if existing:
                    if existing['payload'] != encoded:
                        raise ValueError('Idempotency key already used for a different request')
                    return self._decode(existing), False
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 20:
                raise QueueFull('Local queue is full')
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                       (job_id, request_key, encoded, 'queued', datetime.now(timezone.utc).isoformat(), None))
        return self.get(job_id), True

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        data = dict(row)
        data['payload'] = json.loads(data['payload'])
        data['result'] = json.loads(data['result']) if data['result'] else None
        data.pop('request_key', None)
        return data

    def get(self, job_id):
        with self.connect() as db:
            return self._decode(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [self._decode(row) for row in db.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50')]

    def start(self, job_id):
        with self.connect() as db:
            return bool(db.execute("UPDATE jobs SET status='running' WHERE id=? AND status='queued'", (job_id,)).rowcount)

    def finish(self, job_id, result, status='completed'):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,result=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False), job_id))

    def cancel(self, job_id):
        with self.connect() as db:
            return bool(db.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status='queued'", (job_id,)).rowcount)

    def recover(self):
        # Do not silently repeat paid calls or unknown in-flight shell commands.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('queued','running')")

    def emit(self, job_id, data):
        with self.connect() as db:
            db.execute('INSERT INTO events(job_id,data) VALUES(?,?)', (job_id,json.dumps(data,ensure_ascii=False)))

    def events(self, job_id, after=0):
        with self.connect() as db:
            return [{'seq':row['seq'],'event':json.loads(row['data'])} for row in db.execute(
                'SELECT seq,data FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100', (job_id,after))]
