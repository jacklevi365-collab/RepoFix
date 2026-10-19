"""Check the published package includes its local workbench and no run secrets."""

import sys
import zipfile
from pathlib import PurePosixPath

with zipfile.ZipFile(sys.argv[1]) as wheel:
    names = set(wheel.namelist())
required = {
    "repofix/cli.py",
    "repofix/agent.py",
    "repofix/static/index.html",
    "repofix/static/app.js",
    "repofix/static/submission.mjs",
    "repofix/static/style.css",
}
if not required.issubset(names):
    raise SystemExit("Wheel is missing required runtime files")
for name in names:
    if any(
        part in {".git", ".venv", "runs", "node_modules"} or part.startswith(".env")
        for part in PurePosixPath(name).parts
    ):
        raise SystemExit("Wheel contains a private or generated directory")
print("Wheel runtime assets verified; no environment files or run directories packaged.")
