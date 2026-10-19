"""Reusable task lifecycle for CLI, experiments and the local API."""
import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .agent import Agent
from .budget import BudgetExceeded, Ledger
from .config import load_env_file
from .evaluation import run_checks, assess
from .preflight import prepare_baseline
from .provider import DeepSeek, ScriptedDemo
from .sandbox import DockerRunner
from .workspace import export_patch, snapshot, patched_workspace, integrity_violations, git


@dataclass
class RunSpec:
    repo: Path
    issue: Path
    output: Path = Path('runs')
    image: str = 'python:3.11-slim'
    max_steps: int = 12
    task_budget: float = 2.0
    total_budget: float = 100.0
    demo: bool = False
    verification: Path | None = None
    env_file: Path = Path('.env')
    task_id: str | None = None
    context_mode: str = 'full'
    context_bytes: int = 100000

    def __post_init__(self):
        for name in ('repo', 'issue', 'output', 'env_file'):
            setattr(self, name, Path(getattr(self, name)))
        if self.verification is not None:
            self.verification = Path(self.verification)
        if self.max_steps < 1 or self.context_bytes < 1:
            raise ValueError('Step and context limits must be positive')
        if self.context_mode not in {'full', 'compact'}:
            raise ValueError('Unsupported context mode')
        if not all(math.isfinite(value) and value > 0 for value in (self.task_budget, self.total_budget)):
            raise ValueError('Budget limits must be finite and positive')


def run_task(spec, on_event=None):
    DockerRunner.check(spec.image)
    issue = Path(spec.issue).read_text()
    if len(issue.encode()) > 32000 or spec.max_steps < 1:
        raise ValueError('Issue must be at most 32 KB and max_steps must be positive')
    if spec.verification and not Path(spec.verification).is_dir():
        raise ValueError('Verification directory does not exist')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    output = Path(spec.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    folder = output / run_id
    folder.mkdir()
    ledger = Ledger(output / 'budget.sqlite', spec.total_budget)
    started = time.monotonic()
    report = {'schema_version': 1, 'run_id': run_id, 'task_id': spec.task_id,
              'started_at': datetime.now(timezone.utc).isoformat(),
              'provider': 'scripted-demo' if spec.demo else 'deepseek',
              'evidence_type': 'scripted' if spec.demo else 'model',
              'status': 'error', 'verification': 'not_run',
              'issue_sha256': hashlib.sha256(issue.encode()).hexdigest(),
              'config': {'image': spec.image, 'max_steps': spec.max_steps,
                         'task_budget_rmb': spec.task_budget, 'total_budget_rmb': spec.total_budget}}
    factory = lambda path, verification=None: DockerRunner(path, spec.image, verification)
    try:
        snapshot(spec.repo, folder / 'workspace')
        report['source_tree'] = git(folder / 'workspace', 'rev-parse', 'HEAD^{tree}').strip()
        baseline = None
        if spec.verification:
            precheck = prepare_baseline(spec.repo, spec.verification, folder / 'baseline', factory)
            baseline = precheck['baseline_result']
            report['baseline_result'] = baseline
            report['preflight'] = {key: value for key, value in precheck.items() if key != 'baseline_result'}
            if not precheck['ready']:
                report.update(status='preflight_failed', verification_reason=precheck['reason'])
                return _finish(folder, report, ledger, started)
        if not spec.demo:
            load_env_file(spec.env_file)
        provider = ScriptedDemo() if spec.demo else DeepSeek(ledger, run_id, spec.task_budget)
        report['provider'] = 'scripted-demo' if spec.demo else provider.model
        if not spec.demo:
            report['config'].update(input_rmb_per_million=provider.input_price,
                                    output_rmb_per_million=provider.output_price,
                                    max_output_tokens=provider.max_tokens, thinking='disabled')
        report['config'].update(context_mode=spec.context_mode, context_bytes=spec.context_bytes)
        agent = Agent(provider, factory(folder / 'workspace'), folder / 'trace.jsonl', spec.max_steps,
                      context_bytes=spec.context_bytes, context_mode=spec.context_mode, on_event=on_event)
        report.update(agent.run(issue))
        changed = export_patch(folder / 'workspace', folder / 'patch.diff')
        report['has_patch'] = changed
        if not changed and report['status'] == 'candidate':
            report['status'] = 'no_patch'
        violations = integrity_violations(folder / 'workspace')
        report['integrity_violations'] = violations
        if violations:
            report.update(status='policy_violation', verification='not_run')
        elif changed and spec.verification:
            patched_workspace(spec.repo, folder / 'patch.diff', folder / 'verification-workspace')
            result = run_checks(factory(folder / 'verification-workspace', spec.verification))
            assessment = assess(baseline, result)
            report.update(verification=assessment['status'], verification_reason=assessment['reason'],
                          verification_result=result)
    except BudgetExceeded as exc:
        report.update(status='budget_limit', error=str(exc))
    except Exception as exc:
        report.update(status='error', error=f'{type(exc).__name__}: {exc}')
    return _finish(folder, report, ledger, started)


def _finish(folder, report, ledger, started):
    report['estimated_cost_rmb'] = ledger.spent(report['run_id'])
    report['duration_seconds'] = round(time.monotonic() - started, 3)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    trace = folder / 'trace.jsonl'
    events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    model_events = [event for event in events if event['kind'] == 'model']
    report['model_responses'] = len(model_events)
    report['tool_calls'] = sum(event['kind'] == 'tool' for event in events)
    report['usage'] = {key: sum(event.get('usage', {}).get(key, 0) for event in model_events)
                       for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    report['resolved'] = report['status'] == 'candidate' and report['verification'] == 'passed'
    if (folder / 'workspace' / '.git').is_dir() and not (folder / 'patch.diff').exists():
        try:
            export_patch(folder / 'workspace', folder / 'patch.diff')
        except Exception:
            pass
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return {'output': str(folder), **report}
