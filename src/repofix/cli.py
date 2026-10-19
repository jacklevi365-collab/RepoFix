import argparse
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import load_env_file
from .agent import Agent
from .budget import BudgetExceeded, Ledger
from .provider import DeepSeek, ScriptedDemo
from .sandbox import DockerRunner
from .workspace import export_patch, snapshot, patched_workspace, integrity_violations
from .evaluation import run_checks, assess
from .preflight import prepare_baseline


class PreflightFailed(RuntimeError):
    """A structured preflight failure has already been recorded."""


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return number


def main():
    parser = argparse.ArgumentParser(description='RepoFix Python issue repair agent')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor', help='Check Docker daemon; does not invoke the model')
    preflight = sub.add_parser('preflight', help='Check reproducible test failure without model calls')
    preflight.add_argument('--repo', type=Path, required=True)
    preflight.add_argument('--verification', type=Path, required=True)
    preflight.add_argument('--image', default='python:3.11-slim')
    preflight.add_argument('--output', type=Path, default=Path('runs'))
    run = sub.add_parser('run')
    run.add_argument('--repo', type=Path, required=True)
    run.add_argument('--issue', type=Path, required=True)
    run.add_argument('--output', type=Path, default=Path('runs'))
    run.add_argument('--image', default='python:3.11-slim')
    run.add_argument('--max-steps', type=int, default=12)
    run.add_argument('--task-budget', type=positive, default=2.0)
    run.add_argument('--total-budget', type=positive, default=100.0)
    run.add_argument('--demo', action='store_true', help='Scripted tinybug fixture; no model calls')
    run.add_argument('--verification', type=Path)
    run.add_argument('--env-file', type=Path, default=Path('.env'))
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            DockerRunner.check()
            print('Docker daemon available. Prepare the chosen image before running tasks.')
            return
        DockerRunner.check(args.image)
        if args.action == 'preflight':
            if not args.verification.is_dir():
                raise ValueError('Verification directory does not exist')
            folder = args.output.resolve() / ('preflight-' + uuid.uuid4().hex[:12])
            folder.mkdir(parents=True)
            factory = lambda path, verification=None: DockerRunner(path, args.image, verification)
            result = prepare_baseline(args.repo, args.verification, folder / 'baseline', factory)
            result['estimated_cost_rmb'] = 0
            (folder / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({'output': str(folder), **result}, ensure_ascii=False, indent=2))
            if not result['ready']:
                raise SystemExit(1)
            return
        if args.max_steps < 1:
            raise ValueError('--max-steps must be positive')
        issue = args.issue.read_text()
        if len(issue.encode()) > 32000:
            raise ValueError('Issue must be at most 32 KB')
        if args.verification and not args.verification.is_dir():
            raise ValueError('Verification directory does not exist')
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        ledger = Ledger(output / 'budget.sqlite', args.total_budget)
        if not args.demo:
            load_env_file(args.env_file)
        provider = ScriptedDemo() if args.demo else DeepSeek(ledger, run_id, args.task_budget)
        folder = output / run_id
        folder.mkdir()
        report = {'run_id': run_id, 'provider': 'scripted-demo' if args.demo else provider.model,
                  'status': 'error', 'verification': 'not_run'}
        factory = lambda path, verification=None: DockerRunner(path, args.image, verification)
        try:
            snapshot(args.repo, folder / 'workspace')
            baseline = None
            if args.verification:
                precheck = prepare_baseline(args.repo, args.verification, folder / 'baseline', factory)
                baseline = precheck['baseline_result']
                report['baseline_result'] = baseline
                report['preflight'] = {key: value for key, value in precheck.items() if key != 'baseline_result'}
                if not precheck['ready']:
                    report.update(status='preflight_failed', verification_reason=precheck['reason'])
                    raise PreflightFailed(precheck['reason'])
            agent = Agent(provider, factory(folder / 'workspace'), folder / 'trace.jsonl', args.max_steps)
            report.update(agent.run(issue))
            changed = export_patch(folder / 'workspace', folder / 'patch.diff')
            report['has_patch'] = changed
            if not changed and report['status'] == 'candidate':
                report['status'] = 'no_patch'
            violations = integrity_violations(folder / 'workspace')
            report['integrity_violations'] = violations
            if violations:
                report.update(status='policy_violation', verification='not_run')
            elif changed and args.verification:
                patched_workspace(args.repo, folder / 'patch.diff', folder / 'verification-workspace')
                result = run_checks(factory(folder / 'verification-workspace', args.verification))
                assessment = assess(baseline, result)
                report['baseline_result'], report['verification_result'] = baseline, result
                report['verification'] = assessment['status']
                report['verification_reason'] = assessment['reason']
        except PreflightFailed:
            pass
        except BudgetExceeded as exc:
            report.update(status='budget_limit', error=str(exc))
        except Exception as exc:
            report.update(status='error', error=f'{type(exc).__name__}: {exc}')
        finally:
            report['estimated_cost_rmb'] = ledger.spent(run_id)
            if (folder / 'workspace' / '.git').is_dir() and not (folder / 'patch.diff').exists():
                try:
                    export_patch(folder / 'workspace', folder / 'patch.diff')
                except Exception:
                    pass
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({'output': str(folder), **report}, ensure_ascii=False, indent=2))
        if report['status'] != 'candidate' or report['verification'] == 'failed':
            raise SystemExit(1)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, f'RepoFix: {exc}\n')
