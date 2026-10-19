import argparse
import json
import math
import uuid
from pathlib import Path
from .runs import RunSpec, run_task, resume_task
from .benchmark import run_batch
from .budget import Ledger
from .experiments import plan_matrix, execute_matrix
from .sandbox import DockerRunner
from .preflight import prepare_baseline


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be finite and positive")
    return number


def main():
    parser = argparse.ArgumentParser(description="RepoFix Python issue repair agent")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="Check Docker daemon; does not invoke the model")
    preflight = sub.add_parser(
        "preflight", help="Check reproducible test failure without model calls"
    )
    preflight.add_argument("--repo", type=Path, required=True)
    preflight.add_argument("--verification", type=Path, required=True)
    preflight.add_argument("--image", default="python:3.11-slim")
    preflight.add_argument("--output", type=Path, default=Path("runs"))
    batch = sub.add_parser("batch", help="Run a task manifest with shared budget accounting")
    batch.add_argument("--manifest", type=Path, default=Path("benchmarks/dev/manifest.json"))
    batch.add_argument("--output", type=Path, default=Path("runs"))
    batch.add_argument("--mode", choices=["preflight", "reference", "model"], default="preflight")
    batch.add_argument("--task", action="append", dest="task_ids")
    batch.add_argument("--max-steps", type=int, default=12)
    batch.add_argument("--task-budget", type=positive, default=2.0)
    batch.add_argument("--total-budget", type=positive, default=100.0)
    batch.add_argument("--env-file", type=Path, default=Path(".env"))
    batch.add_argument("--tool-mode", choices=["shell", "structured"], default="shell")
    batch.add_argument("--context-mode", choices=["full", "compact"], default="full")
    serve = sub.add_parser("serve", help="Run the local API (install web extra)")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--root", type=Path, default=Path.cwd())
    resume = sub.add_parser("resume", help="Resume a safe completed-round checkpoint")
    resume.add_argument("--run-dir", type=Path, required=True)
    resume.add_argument("--max-steps", type=int)
    budget = sub.add_parser(
        "budget", help="Inspect estimates and unresolved reservations without model calls"
    )
    budget.add_argument("--output", type=Path, default=Path("runs"))
    budget.add_argument("--total-budget", type=positive, default=100.0)
    matrix = sub.add_parser(
        "matrix", help="Plan a 2x2 experiment; --execute explicitly enables paid calls"
    )
    matrix.add_argument("--manifest", type=Path, default=Path("benchmarks/real/manifest.json"))
    matrix.add_argument("--output", type=Path, default=Path("runs"))
    matrix.add_argument("--task-budget", type=positive, default=2.0)
    matrix.add_argument("--max-steps", type=int, default=12)
    matrix.add_argument("--env-file", type=Path, default=Path(".env"))
    matrix.add_argument("--execute", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--issue", type=Path, required=True)
    run.add_argument("--output", type=Path, default=Path("runs"))
    run.add_argument("--image", default="python:3.11-slim")
    run.add_argument("--max-steps", type=int, default=12)
    run.add_argument("--task-budget", type=positive, default=2.0)
    run.add_argument("--total-budget", type=positive, default=100.0)
    run.add_argument("--demo", action="store_true", help="Scripted tinybug fixture; no model calls")
    run.add_argument("--verification", type=Path)
    run.add_argument("--env-file", type=Path, default=Path(".env"))
    run.add_argument("--tool-mode", choices=["shell", "structured"], default="shell")
    run.add_argument("--context-mode", choices=["full", "compact"], default="full")
    run.add_argument("--context-bytes", type=int, default=100000)
    args = parser.parse_args()
    try:
        if args.action == "serve":
            try:
                import uvicorn
                from .api import create_app
            except ImportError:
                raise ValueError('Install optional dependencies: pip install -e ".[web]"') from None
            uvicorn.run(create_app(args.root), host="127.0.0.1", port=args.port)
            return
        if args.action == "matrix":
            result = (
                execute_matrix(
                    args.manifest, args.output, args.task_budget, args.max_steps, args.env_file
                )
                if args.execute
                else plan_matrix(args.manifest, args.task_budget)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.action == "budget":
            args.output.mkdir(parents=True, exist_ok=True)
            print(
                json.dumps(
                    Ledger(args.output / "budget.sqlite", args.total_budget).summary(), indent=2
                )
            )
            return
        if args.action == "doctor":
            DockerRunner.check()
            print("Docker daemon available. Prepare the chosen image before running tasks.")
            return
        if args.action == "batch":
            result = run_batch(
                **{key: value for key, value in vars(args).items() if key != "action"}
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            success = all(
                item["status"] == "ready" if args.mode == "preflight" else item.get("resolved")
                for item in result["results"]
            )
            if not success:
                raise SystemExit(1)
            return
        if args.action == "preflight":
            DockerRunner.check(args.image)
            if not args.verification.is_dir():
                raise ValueError("Verification directory does not exist")
            folder = args.output.resolve() / ("preflight-" + uuid.uuid4().hex[:12])
            folder.mkdir(parents=True)

            def factory(path, verification=None):
                return DockerRunner(path, args.image, verification)

            result = prepare_baseline(args.repo, args.verification, folder / "baseline", factory)
            result["estimated_cost_rmb"] = 0
            (folder / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({"output": str(folder), **result}, ensure_ascii=False, indent=2))
            if not result["ready"]:
                raise SystemExit(1)
            return
        if args.action == "resume":
            result = resume_task(args.run_dir, args.max_steps)
        else:
            result = run_task(
                RunSpec(**{key: value for key, value in vars(args).items() if key != "action"})
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if (
            result["status"] != "candidate"
            or result["verification"] == "failed"
            or result.get("regression", {}).get("status") == "failed"
        ):
            raise SystemExit(1)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, f"RepoFix: {exc}\n")
