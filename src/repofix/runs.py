"""Reusable task lifecycle for CLI, experiments and the local API."""
import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from .agent import Agent
from .checkpoint import UnsafeResume, load_checkpoint, run_lock, write_json
from .budget import BudgetExceeded, Ledger
from .config import load_env_file
from .evaluation import run_checks, assess, assess_regression
from .preflight import prepare_baseline
from .provider import DeepSeek, ScriptedDemo
from .sandbox import DockerRunner
from .workspace import export_patch, snapshot, patched_workspace, integrity_violations, git, snapshot_committed, directory_fingerprint


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
    regression_tests: list[str] | None = None
    tool_mode: str = 'shell'
    context_mode: str = 'full'
    context_bytes: int = 100000

    def __post_init__(self):
        for name in ('repo', 'issue', 'output', 'env_file'):
            setattr(self, name, Path(getattr(self, name)))
        if self.verification is not None:
            self.verification = Path(self.verification)
        if self.max_steps < 1 or self.context_bytes < 1:
            raise ValueError('Step and context limits must be positive')
        if self.tool_mode not in {'shell','structured'}:
            raise ValueError('Unsupported tool mode')
        if self.context_mode not in {'full', 'compact'}:
            raise ValueError('Unsupported context mode')
        if not all(math.isfinite(value) and value > 0 for value in (self.task_budget, self.total_budget)):
            raise ValueError('Budget limits must be finite and positive')


def run_task(spec,on_event=None,resume_folder=None):
    if resume_folder:
        folder=Path(resume_folder).resolve()
        if not folder.is_dir():
            raise ValueError('Run directory does not exist')
    else:
        name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        folder=Path(spec.output).resolve()/name
        folder.mkdir(parents=True)
    with run_lock(folder):
        return _run_task(spec,on_event,resume_folder,folder)


def _run_task(spec,on_event,resume_folder,folder):
    DockerRunner.check(spec.image)
    issue = Path(spec.issue).read_text()
    if len(issue.encode()) > 32000 or spec.max_steps < 1:
        raise ValueError('Issue must be at most 32 KB and max_steps must be positive')
    if spec.verification and not Path(spec.verification).is_dir():
        raise ValueError('Verification directory does not exist')
    if resume_folder:
        folder=Path(resume_folder).resolve()
        load_checkpoint(folder / 'checkpoint.json')
        record=json.loads((folder / 'request.json').read_text())
        if spec.verification and directory_fingerprint(spec.verification)!=record['verification_sha256']:
            raise UnsafeResume('Independent verification files changed; automatic resume is refused')
        run_id=folder.name
        output=folder.parent
        report=json.loads((folder / 'report.json').read_text())
        report.update(status='error',verification='not_run',resume_count=report.get('resume_count',0)+1)
        for key in ('regression','regression_result','verification_result','verification_reason','error','resolved','has_patch'):
            report.pop(key,None)
    else:
        run_id=folder.name
        output=folder.parent
        normalized={key:str(value.resolve()) if isinstance(value,Path) else value for key,value in asdict(spec).items()}
        record={'spec':normalized,'verification_sha256':directory_fingerprint(spec.verification) if spec.verification else None}
        write_json(folder/'request.json',record)
        (folder/'issue.md').write_text(issue)
        report={'schema_version':1,'run_id':run_id,'task_id':spec.task_id,
            'started_at':datetime.now(timezone.utc).isoformat(),'resume_count':0,
            'provider':'scripted-demo' if spec.demo else 'deepseek',
            'evidence_type':'scripted' if spec.demo else 'model','status':'error','verification':'not_run',
            'issue_sha256':hashlib.sha256(issue.encode()).hexdigest(),
            'config':{'image':spec.image,'max_steps':spec.max_steps,'task_budget_rmb':spec.task_budget,'total_budget_rmb':spec.total_budget}}
    ledger=Ledger(output/'budget.sqlite',spec.total_budget)
    started=time.monotonic()
    factory = lambda path, verification=None: DockerRunner(path, spec.image, verification)
    try:
        if not resume_folder:
            snapshot(spec.repo, folder / 'workspace')
        source_tree=git(folder/'workspace','rev-parse','HEAD^{tree}').strip()
        if resume_folder and source_tree!=report['source_tree']:
            raise UnsafeResume('Committed source changed; automatic resume is refused')
        report['source_tree']=source_tree
        baseline = None
        if spec.verification and not resume_folder:
            precheck = prepare_baseline(spec.repo, spec.verification, folder / 'baseline', factory, spec.regression_tests)
            baseline = precheck['baseline_result']
            report['baseline_result'] = baseline
            report['regression_baseline_result']=precheck.get('regression_baseline_result')
            report['preflight'] = {key: value for key, value in precheck.items() if key not in {'baseline_result','regression_baseline_result'}}
            if not precheck['ready']:
                report.update(status='preflight_failed', verification_reason=precheck['reason'])
                return _finish(folder, report, ledger, started)
        if spec.verification and resume_folder:
            baseline=report['baseline_result']
            precheck={'regression_baseline_result':report['regression_baseline_result']}
        write_json(folder/'report.json',report)
        if not spec.demo:
            load_env_file(spec.env_file)
        provider = ScriptedDemo() if spec.demo else DeepSeek(ledger, run_id, spec.task_budget)
        if resume_folder and not spec.demo:
            expected=report['config']
            if report['provider']!=provider.model or expected['input_rmb_per_million']!=provider.input_price or expected['output_rmb_per_million']!=provider.output_price:
                raise UnsafeResume('Model or pricing changed; create a new run for a different configuration')
        report['provider'] = 'scripted-demo' if spec.demo else provider.model
        if not spec.demo:
            report['config'].update(input_rmb_per_million=provider.input_price,
                                    output_rmb_per_million=provider.output_price,
                                    max_output_tokens=provider.max_tokens, thinking='disabled')
        report['config'].update(context_mode=spec.context_mode, context_bytes=spec.context_bytes, tool_mode=spec.tool_mode,max_steps=spec.max_steps)
        write_json(folder/'report.json',report)
        agent = Agent(provider, factory(folder / 'workspace'), folder / 'trace.jsonl', spec.max_steps,
                      context_bytes=spec.context_bytes, context_mode=spec.context_mode, on_event=on_event, tool_mode=spec.tool_mode)
        if resume_folder and spec.demo:
            # The deterministic fixture indexes its response by completed round.
            provider.step=load_checkpoint(folder/'checkpoint.json')['next_step']
        report.update(agent.run(issue,resume=bool(resume_folder)))
        changed = export_patch(folder / 'workspace', folder / 'patch.diff')
        report['has_patch'] = changed
        if not changed and report['status'] == 'candidate':
            report['status'] = 'no_patch'
        violations = integrity_violations(folder / 'workspace')
        report['integrity_violations'] = violations
        if violations:
            report.update(status='policy_violation', verification='not_run')
        elif changed and spec.verification:
            target=folder/('verification-'+uuid.uuid4().hex[:8])
            snapshot_committed(folder/'baseline',target)
            import subprocess
            subprocess.run(['git','-C',str(target),'apply','--',str(folder/'patch.diff')],check=True,capture_output=True,timeout=30)
            result = run_checks(factory(target, spec.verification))
            assessment = assess(baseline, result)
            report.update(verification=assessment['status'], verification_reason=assessment['reason'],
                          verification_result=result)
            regression=run_checks(factory(target),regression=True,selectors=spec.regression_tests)
            report['regression_result']=regression
            report['regression']=assess_regression(precheck['regression_baseline_result'],regression)
    except UnsafeResume as exc:
        report.update(status='resume_refused',error=str(exc))
    except BudgetExceeded as exc:
        report.update(status='budget_limit', error=str(exc))
    except Exception as exc:
        report.update(status='error', error=f'{type(exc).__name__}: {exc}')
    return _finish(folder, report, ledger, started)


def _finish(folder, report, ledger, started):
    report['estimated_cost_rmb'] = ledger.spent(report['run_id'])
    report['duration_seconds'] = round(time.monotonic() - started, 3)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    report['wall_duration_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(report['started_at'])).total_seconds()
    trace = folder / 'trace.jsonl'
    events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    model_events = [event for event in events if event['kind'] == 'model']
    report['model_responses'] = len(model_events)
    report['tool_calls'] = sum(event['kind'] == 'tool' for event in events)
    report['usage'] = {key: sum(event.get('usage', {}).get(key, 0) for event in model_events)
                       for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    report['resolved'] = report['status'] == 'candidate' and report['verification'] == 'passed' and report.get('regression',{}).get('status')!='failed'
    if (folder / 'workspace' / '.git').is_dir() and not (folder / 'patch.diff').exists():
        try:
            export_patch(folder / 'workspace', folder / 'patch.diff')
        except Exception:
            pass
    write_json(folder/'report.json',report)
    return {'output': str(folder), **report}


def resume_task(folder,max_steps=None,on_event=None):
    folder=Path(folder).resolve()
    record=json.loads((folder/'request.json').read_text())
    spec=RunSpec(**record['spec'])
    # Resume uses the saved issue and existing ledger; original input can move.
    spec.issue=folder/'issue.md'
    spec.output=folder.parent
    if max_steps is not None:
        spec.max_steps=max_steps
    if spec.max_steps<1:
        raise ValueError('max_steps must be positive')
    return run_task(spec,on_event=on_event,resume_folder=folder)
