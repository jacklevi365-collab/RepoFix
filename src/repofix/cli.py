import argparse
import json
import math
import uuid
from pathlib import Path
from .runs import RunSpec, run_task
from .benchmark import run_batch
from .sandbox import DockerRunner
from .preflight import prepare_baseline


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
    batch = sub.add_parser('batch', help='Run a task manifest with shared budget accounting')
    batch.add_argument('--manifest', type=Path, default=Path('benchmarks/dev/manifest.json'))
    batch.add_argument('--output', type=Path, default=Path('runs'))
    batch.add_argument('--mode', choices=['preflight', 'reference', 'model'], default='preflight')
    batch.add_argument('--task', action='append', dest='task_ids')
    batch.add_argument('--max-steps', type=int, default=12)
    batch.add_argument('--task-budget', type=positive, default=2.0)
    batch.add_argument('--total-budget', type=positive, default=100.0)
    batch.add_argument('--env-file', type=Path, default=Path('.env'))
    batch.add_argument('--context-mode', choices=['full', 'compact'], default='full')
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
    run.add_argument('--context-mode', choices=['full', 'compact'], default='full')
    run.add_argument('--context-bytes', type=int, default=100000)
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            DockerRunner.check()
            print('Docker daemon available. Prepare the chosen image before running tasks.')
            return
        if args.action == 'batch':
            result = run_batch(**{key: value for key, value in vars(args).items() if key != 'action'})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            success = all(item['status'] == 'ready' if args.mode == 'preflight' else item.get('resolved')
                          for item in result['results'])
            if not success:
                raise SystemExit(1)
            return
        if args.action == 'preflight':
            DockerRunner.check(args.image)
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
        result = run_task(RunSpec(**{key: value for key, value in vars(args).items() if key != 'action'}))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result['status'] != 'candidate' or result['verification'] == 'failed':
            raise SystemExit(1)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, f'RepoFix: {exc}\n')
