"""Sequential, budget-sharing experiments with explicit evidence provenance."""
import hashlib
import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from .evaluation import assess, run_checks
from .preflight import prepare_baseline
from .runs import RunSpec, run_task
from .sandbox import DockerRunner
from .workspace import patched_workspace, integrity_violations


def load_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or data.get('split') not in {'development', 'evaluation'}:
        raise ValueError('Unsupported task manifest schema or split')
    if not data.get('tasks'):
        raise ValueError('Task set must not be empty')
    seen, tasks = set(), []
    for item in data['tasks']:
        task = dict(item)
        name = task.get('id', '')
        if not re.fullmatch('[a-zA-Z0-9_-]+', name) or name in seen:
            raise ValueError('Invalid or duplicate task id')
        seen.add(name)
        for field in ('repo', 'issue', 'verification', 'reference_patch'):
            if field not in task:
                raise ValueError('Task is missing required path: ' + field)
            task[field] = (path.parent / task[field]).resolve()
            if not task[field].exists():
                raise ValueError('Missing task file or directory: ' + field)
        for relative, expected in task.get('source', {}).get('files_sha256', {}).items():
            file = (task['repo'] / relative).resolve()
            if task['repo'] not in file.parents or not file.is_file():
                raise ValueError('Invalid pinned source path')
            if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise ValueError('Pinned task source was modified: ' + name)
        task.setdefault('image', 'python:3.11-slim')
        tasks.append(task)
    data['tasks'] = tasks
    return data


def summarize(results, mode):
    # Always include failed tasks in the denominator; never count oracle/scripted
    # verification as model performance.
    count = len(results)
    passed = sum(bool(r.get('resolved')) for r in results)
    return {'task_count': count, 'passed_count': passed,
            'status_counts': dict(Counter(r['status'] for r in results)),
            'model_success_rate': passed / count if mode == 'model' and count else None,
            'reference_validation_rate': passed / count if mode == 'reference' and count else None,
            'estimated_cost_rmb': round(sum(r.get('estimated_cost_rmb', 0) for r in results), 6),
            'duration_seconds': round(sum(r.get('duration_seconds', 0) for r in results), 3)}


def run_batch(manifest, output=Path('runs'), mode='preflight', task_ids=None,
              task_budget=2.0, total_budget=100.0, max_steps=12, env_file=Path('.env'), context_mode='full'):
    if mode not in {'preflight', 'reference', 'model'}:
        raise ValueError('Unsupported batch mode')
    data = load_manifest(manifest)
    tasks = data['tasks']
    if task_ids:
        unknown = set(task_ids) - {task['id'] for task in tasks}
        if unknown:
            raise ValueError('Unknown task ids: ' + ', '.join(sorted(unknown)))
        tasks = [task for task in tasks if task['id'] in task_ids]
    output = Path(output).resolve()
    folder = output / ('batch-' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    results = []
    for task in tasks:
        started = time.monotonic()
        result = {'task_id': task['id'], 'status': 'error', 'resolved': False,
                  'evidence_type': mode, 'estimated_cost_rmb': 0}
        try:
            if mode == 'model':
                result = run_task(RunSpec(repo=task['repo'], issue=task['issue'],
                    verification=task['verification'], output=output, image=task['image'],
                    max_steps=max_steps, task_budget=task_budget, total_budget=total_budget,
                    env_file=env_file, task_id=task['id'], context_mode=context_mode))
            else:
                DockerRunner.check(task['image'])
                task_folder = folder / task['id']
                factory = lambda path, verification=None: DockerRunner(path, task['image'], verification)
                precheck = prepare_baseline(task['repo'], task['verification'], task_folder / 'baseline', factory)
                result.update(preflight=precheck, status='ready' if precheck['ready'] else 'preflight_failed')
                if mode == 'reference' and precheck['ready']:
                    target = task_folder / 'reference'
                    patched_workspace(task['repo'], task['reference_patch'], target)
                    violations = integrity_violations(target)
                    checks = run_checks(factory(target, task['verification']))
                    assessment = assess(precheck['baseline_result'], checks)
                    result.update(verification=assessment, verification_result=checks,
                                  integrity_violations=violations, status='validated' if assessment['status'] == 'passed' and not violations else 'reference_failed')
                    result['resolved'] = result['status'] == 'validated'
        except Exception as exc:
            result.update(status='error', error=f'{type(exc).__name__}: {exc}')
        if task.get('source'):
            result['source'] = {key: value for key, value in task['source'].items() if key != 'files_sha256'}
        result['duration_seconds'] = round(time.monotonic() - started, 3)
        results.append(result)
        # Persist partial results after every task so interrupted experiments are inspectable.
        report = {'schema_version': 1, 'name': data['name'], 'split': data['split'],
                  'provenance': data.get('provenance', 'unspecified'), 'mode': mode,
                  'manifest_sha256': hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),
                  'summary': summarize(results, mode), 'results': results}
        (folder / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return {'output': str(folder), **report}
