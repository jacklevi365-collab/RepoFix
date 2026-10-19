"""Atomic round-boundary checkpoints; ambiguous work must not be replayed."""

import json
import os
from contextlib import contextmanager
from pathlib import Path


class UnsafeResume(RuntimeError):
    pass


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def save_checkpoint(path, **state):
    write_json(path, {"schema_version": 1, **state})


def load_checkpoint(path):
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise UnsafeResume(
            "Checkpoint is missing or incomplete; automatic replay is refused"
        ) from None
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or state.get("phase") not in {"ready", "finished"}
    ):
        raise UnsafeResume(
            "An API call or tool round may have been in flight; inspect the trace before restarting"
        )
    return state


@contextmanager
def run_lock(folder):
    import fcntl

    with (Path(folder) / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UnsafeResume("Run is already active; concurrent resume is refused") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
