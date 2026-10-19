"""Load a small literal-only .env format without evaluating shell syntax."""
import os
import re
from pathlib import Path

ALLOWED = {'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'REPOFIX_INPUT_RMB_PER_MILLION',
           'REPOFIX_OUTPUT_RMB_PER_MILLION'}


def load_env_file(path='.env'):
    file = Path(path)
    if not file.exists():
        return
    for number, line in enumerate(file.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or key not in ALLOWED:
            raise ValueError(f'Invalid or unsupported setting in env file at line {number}')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed quote in env file at line {number}')
            value = value[1:-1]
        os.environ.setdefault(key, value)
