"""Zero-model integration check for the structured tools and patch delivery."""

import json
import uuid
from pathlib import Path
from repofix.evaluation import run_checks, assess
from repofix.sandbox import DockerRunner
from repofix.tools import RepositoryTools
from repofix.workspace import snapshot, export_patch, patched_workspace

root = Path(__file__).resolve().parents[1]
folder = root / "runs" / ("structured-smoke-" + uuid.uuid4().hex[:8])
source = root / "examples/tinybug/repo"
verification = root / "examples/tinybug/verification"
DockerRunner.check("python:3.11-slim")
snapshot(source, folder / "workspace")
tools = RepositoryTools(DockerRunner(folder / "workspace"), mode="structured")
results = []
for name, args in [
    ("list_files", {}),
    ("read_file", {"path": "stats.py"}),
    ("search_text", {"query": "len(values)"}),
    (
        "replace_text",
        {
            "path": "stats.py",
            "old": "sum(values) / (len(values) - 1)",
            "new": "sum(values) / len(values)",
        },
    ),
]:
    result = tools.execute(name, args)
    results.append({"tool": name, "result": result})
    if result["exit_code"]:
        raise RuntimeError(result["output"])
export_patch(folder / "workspace", folder / "patch.diff")
snapshot(source, folder / "baseline")
baseline = run_checks(DockerRunner(folder / "baseline", verification=verification))
patched_workspace(source, folder / "patch.diff", folder / "fresh")
fixed = run_checks(DockerRunner(folder / "fresh", verification=verification))
report = {
    "evidence_type": "controller-smoke",
    "model_calls": 0,
    "estimated_cost_rmb": 0,
    "tools": results,
    "verification": assess(baseline, fixed),
}
(folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
print(json.dumps({"output": str(folder), "verification": report["verification"]}))
if report["verification"]["status"] != "passed":
    raise SystemExit(1)
