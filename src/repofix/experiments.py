"""Explicitly executed 2x2 experiments; planning never calls a model."""

import math
import uuid
from pathlib import Path
from .benchmark import load_manifest, run_batch
from .budget import Ledger
from .checkpoint import write_json
from .config import load_env_file
from .provider import DeepSeek

PROFILES = [
    {"name": "baseline", "tool_mode": "shell", "context_mode": "full"},
    {"name": "context", "tool_mode": "shell", "context_mode": "compact"},
    {"name": "tools", "tool_mode": "structured", "context_mode": "full"},
    {"name": "combined", "tool_mode": "structured", "context_mode": "compact"},
]


def plan_matrix(manifest, task_budget=2.0):
    if not math.isfinite(task_budget) or task_budget <= 0:
        raise ValueError("Task budget must be finite and positive")
    data = load_manifest(manifest)
    count = len(data["tasks"])
    return {
        "name": data["name"],
        "split": data["split"],
        "provenance": data.get("provenance"),
        "tasks_per_profile": count,
        "profile_count": len(PROFILES),
        "profiles": PROFILES,
        "maximum_estimated_rmb": count * len(PROFILES) * task_budget,
        "model_executed": False,
    }


def execute_matrix(
    manifest, output=Path("runs"), task_budget=2.0, max_steps=12, env_file=Path(".env")
):
    if not 1 <= max_steps <= 30:
        raise ValueError("Matrix max_steps must be between 1 and 30")
    plan = plan_matrix(manifest, task_budget)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(output / "budget.sqlite", 100)
    available = 100 - ledger.summary()["estimated_total_rmb"]
    if plan["maximum_estimated_rmb"] > available:
        raise ValueError("Planned per-task caps exceed remaining shared estimated budget")
    load_env_file(env_file)
    # Constructor validation is free. Invalid/missing configuration stops here.
    DeepSeek(ledger, "matrix-configuration-check", task_budget)
    preflight = run_batch(manifest, output, mode="preflight")
    if not all(item["status"] == "ready" for item in preflight["results"]):
        raise ValueError("Task environment preflight failed; inspect " + preflight["output"])
    folder = output / ("matrix-" + uuid.uuid4().hex[:12])
    folder.mkdir()
    report = {
        "schema_version": 1,
        "plan": plan,
        "status": "running",
        "preflight_output": preflight["output"],
        "results": [],
    }
    write_json(folder / "comparison.json", report)
    for profile in PROFILES:
        result = run_batch(
            manifest,
            output,
            mode="model",
            task_budget=task_budget,
            total_budget=100,
            max_steps=max_steps,
            env_file=env_file,
            tool_mode=profile["tool_mode"],
            context_mode=profile["context_mode"],
        )
        report["results"].append(
            {"profile": profile, "batch_output": result["output"], "summary": result["summary"]}
        )
        write_json(folder / "comparison.json", report)
    report["status"] = "completed"
    report["model_executed"] = any(
        item["summary"]["model_attempted_tasks"] for item in report["results"]
    )
    write_json(folder / "comparison.json", report)
    lines = [
        "# RepoFix strategy comparison",
        "",
        "Dataset provenance: " + str(plan["provenance"]) + ". Split: " + plan["split"] + ".",
        "All tasks, including failures, remain in the denominator. Public historical tasks may be memorized.",
        "",
        "| Profile | Tasks | Resolved | Attempted | Rate | Estimated RMB | Seconds |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["results"]:
        s = item["summary"]
        rate = (
            "not evaluated" if s["model_success_rate"] is None else f"{s['model_success_rate']:.1%}"
        )
        lines.append(
            f"| [{item['profile']['name']}](../{Path(item['batch_output']).name}/summary.json) | {s['task_count']} | {s['passed_count']} | {s['model_attempted_tasks']} | {rate} | {s['estimated_cost_rmb']:.4f} | {s['duration_seconds']:.2f} |"
        )
    (folder / "comparison.md").write_text("\n".join(lines) + "\n")
    return {"output": str(folder), **report}
