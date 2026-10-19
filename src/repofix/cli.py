import argparse
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .agent import Agent
from .budget import BudgetExceeded, Ledger
from .provider import DeepSeek, ScriptedDemo
from .sandbox import DockerRunner
from .workspace import export_patch, snapshot, verify, verification_passed


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return number


def main():
    parser = argparse.ArgumentParser(description='RepoFix Python issue repair agent')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor', help='Check Docker daemon; does not invoke the model')
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
    run.add_argument('--verify-command', default='python -m unittest discover -s /verification -v')
    args = parser.parse_args()
    try:
        DockerRunner.check()
        if args.action == 'doctor':
            print('Docker daemon available. Prepare the chosen image before running tasks.')
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
        provider = ScriptedDemo() if args.demo else DeepSeek(ledger, run_id, args.task_budget)
        folder = output / run_id
        folder.mkdir()
        report = {'run_id': run_id, 'provider': 'scripted-demo' if args.demo else provider.model,
                  'status': 'error', 'verification': 'not_run'}
        factory = lambda path, verification=None: DockerRunner(path, args.image, verification)
        try:
            snapshot(args.repo, folder / 'workspace')
            agent = Agent(provider, factory(folder / 'workspace'), folder / 'trace.jsonl', args.max_steps)
            report.update(agent.run(issue))
            changed = export_patch(folder / 'workspace', folder / 'patch.diff')
            report['has_patch'] = changed
            if not changed and report['status'] == 'candidate':
                report['status'] = 'no_patch'
            if changed and args.verification:
                # The original must fail independent tests; the candidate must pass.
                snapshot(args.repo, folder / 'baseline')
                baseline = factory(folder / 'baseline', args.verification).run(args.verify_command, timeout=60)
                result = verify(args.repo, folder / 'patch.diff', folder / 'verification-workspace',
                                args.verification, factory, args.verify_command)
                report['baseline_result'], report['verification_result'] = baseline, result
                report['verification'] = 'passed' if verification_passed(baseline, result) else 'failed'
                # Limited to this task's supplied checks; not a general correctness claim.
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
