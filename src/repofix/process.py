import subprocess
import tempfile


def execute(argv, timeout=60, limit=16000):
    """Spool output to disk so a verbose process cannot fill controller memory."""
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                argv,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            code, timed_out = result.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = 124, True
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - limit))
        text = output.read(limit).decode("utf-8", errors="replace")
        return {
            "exit_code": code,
            "timed_out": timed_out,
            "output": text,
            "truncated": size > limit,
        }
