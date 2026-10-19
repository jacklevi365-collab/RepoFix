"""Local-only FastAPI task service. Install the optional web dependencies."""

import asyncio
import json
import fcntl
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .benchmark import load_manifest
from .jobs import JobStore, QueueFull
from .budget import Ledger
from .runs import RunSpec, run_task


class SubmitJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=80)
    mode: Literal["demo", "model"] = "demo"
    context_mode: Literal["full", "compact"] = "full"
    tool_mode: Literal["shell", "structured"] = "structured"
    max_steps: int = Field(default=12, ge=1, le=30)
    task_budget: float = Field(default=2.0, gt=0, le=5, allow_inf_nan=False)


def create_app(root=None, output=None, executor=run_task):
    root = Path(root or Path.cwd()).resolve()
    output = Path(output or root / "runs").resolve()
    output.mkdir(parents=True, exist_ok=True)
    store = JobStore(output / "jobs.sqlite")
    catalog = {}
    for filename in ("benchmarks/dev/manifest.json", "benchmarks/real/manifest.json"):
        path = root / filename
        if path.exists():
            dataset = load_manifest(path)
            catalog.update(
                {
                    item["id"]: {
                        **item,
                        "provenance": dataset.get("provenance"),
                        "split": dataset["split"],
                    }
                    for item in dataset["tasks"]
                }
            )
    catalog["demo-tinybug"] = {
        "repo": root / "examples/tinybug/repo",
        "issue": root / "examples/tinybug/issue.md",
        "verification": root / "examples/tinybug/verification",
        "image": "python:3.11-slim",
    }

    @asynccontextmanager
    async def lifespan(app):
        lock = (output / "server.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError(
                "Another RepoFix server already owns this output directory"
            ) from None
        store.recover()
        app.state.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="repofix")
        try:
            yield
        finally:
            app.state.pool.shutdown(wait=True, cancel_futures=True)
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    app = FastAPI(title="RepoFix Local API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    app.state.store = store
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(static / "index.html")

    @app.get("/api/experiments")
    def experiments():
        results = []
        for path in sorted(
            output.glob("batch-*/summary.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:20]:
            if output not in path.resolve().parents:
                continue
            try:
                data = json.loads(path.read_text())
                if not isinstance(data.get("summary"), dict):
                    continue
                results.append(
                    {
                        key: data.get(key)
                        for key in ("name", "mode", "split", "provenance", "summary")
                    }
                )
            except (OSError, ValueError):
                continue
        return results

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin requests are disabled"}, status_code=403)
        return await call_next(request)

    def require_job(job_id):
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    def work(job_id, payload):
        if not store.start(job_id):
            return
        store.emit(job_id, {"kind": "lifecycle", "stage": "running"})
        try:
            task = catalog[payload["task_id"]]
            result = executor(
                RunSpec(
                    repo=task["repo"],
                    issue=task["issue"],
                    verification=task["verification"],
                    output=output,
                    image=task["image"],
                    demo=payload["mode"] == "demo",
                    context_mode=payload["context_mode"],
                    tool_mode=payload["tool_mode"],
                    max_steps=payload["max_steps"],
                    task_budget=payload["task_budget"],
                    total_budget=100,
                    env_file=root / ".env",
                    task_id=payload["task_id"],
                    regression_tests=task.get("regression_tests"),
                ),
                on_event=lambda event: store.emit(job_id, event),
            )
            store.finish(job_id, result)
            store.emit(
                job_id,
                {"kind": "lifecycle", "stage": "completed", "status": result["status"]},
            )
        except Exception as exc:
            store.finish(
                job_id,
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                status="error",
            )
            store.emit(job_id, {"kind": "lifecycle", "stage": "error"})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "scope": "local", "budget_limit_rmb": 100}

    @app.get("/api/budget")
    def budget():
        return Ledger(output / "budget.sqlite", 100).summary()

    @app.get("/api/catalog")
    def tasks():
        return [
            {
                "id": name,
                "description": task["issue"].read_text(),
                "demo_available": name == "demo-tinybug",
                "provenance": task.get("provenance", "scripted-demo"),
                "split": task.get("split", "demonstration"),
            }
            for name, task in catalog.items()
        ]

    @app.get("/api/jobs")
    def jobs():
        return store.list()

    @app.post("/api/jobs", status_code=202)
    def submit(
        payload: SubmitJob,
        idempotency_key: str | None = Header(default=None, max_length=128),
    ):
        data = payload.model_dump()
        if payload.task_id not in catalog:
            raise HTTPException(404, "Unknown task")
        if payload.mode == "demo" and payload.task_id != "demo-tinybug":
            raise HTTPException(422, "Scripted demo only supports demo-tinybug")
        try:
            job, created = store.create(data, idempotency_key)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except QueueFull as exc:
            raise HTTPException(429, str(exc)) from None
        if created:
            app.state.pool.submit(work, job["id"], data)
        return job

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return require_job(job_id)

    @app.delete("/api/jobs/{job_id}")
    def cancel(job_id: str):
        require_job(job_id)
        if not store.cancel(job_id):
            raise HTTPException(409, "Only queued jobs can be cancelled")
        return store.get(job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, request: Request, after: int = 0):
        require_job(job_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor") from None

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                items = store.events(job_id, cursor)
                for item in items:
                    cursor = item["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(item['event'], ensure_ascii=False)}\n\n"
                if len(items) < 100 and store.get(job_id)["status"] not in {
                    "queued",
                    "running",
                }:
                    yield "event: done\ndata: {}\n\n"
                    return
                if not items:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/jobs/{job_id}/artifacts/{name}")
    def artifact(job_id: str, name: str):
        job = require_job(job_id)
        if name not in {"patch.diff", "report.json", "trace.jsonl"} or not job.get("result", {}):
            raise HTTPException(404, "Artifact not found")
        folder = Path(job["result"].get("output", output / "missing")).resolve()
        if output not in folder.parents:
            raise HTTPException(403, "Artifact path outside output root")
        path = folder / name
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")
        return FileResponse(path, media_type="text/plain", filename=name)

    return app
