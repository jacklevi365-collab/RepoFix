import os
import re
import shutil
import subprocess
from pathlib import Path


def git(workspace, *args):
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(workspace), *args],
                            capture_output=True, text=True, check=False, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def snapshot(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_dir() or target == source or source in target.parents:
        raise ValueError('Source must exist and output must be outside the source repository')
    # No symlinks: do not copy references to files outside the intended repository.
    for parent, directories, files in os.walk(source, followlinks=False):
        directories[:] = [d for d in directories if d not in {'.git', '.venv', '__pycache__', 'runs'}]
        for name in directories + files:
            if (Path(parent) / name).is_symlink():
                raise ValueError(f'Symlinks are unsupported in v0.1: {name}')
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', '.env', '.env.*', '.venv', '__pycache__', 'runs'))
    git(target, 'init', '-q')
    git(target, 'add', '-A')
    git(target, '-c', 'user.name=RepoFix', '-c', 'user.email=repofix@localhost',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Baseline', '--allow-empty')


def export_patch(workspace, destination):
    git(workspace, 'add', '-N', '.')
    patch = git(workspace, 'diff', '--binary', 'HEAD', '--', '.')
    Path(destination).write_text(patch)
    return bool(patch)


def verify(source, patch, target, verification, runner_factory, command):
    """Fresh source + delivered patch; never execute in the agent's used workspace."""
    snapshot(source, target)
    subprocess.run(['git', '-C', str(target), 'apply', '--', str(Path(patch).resolve())],
                   check=True, capture_output=True, timeout=30)
    # Detect broken verification environments before accepting a repaired candidate.
    result = runner_factory(target, verification=verification).run(command, timeout=60)
    return result


def verification_passed(baseline, candidate):
    """Fail closed on zero tests, skipped-only runs and import failures.

    v0.1 accepts unittest output; custom verification commands must also emit
    its test-count summary. This is not protection against adversarial output.
    """
    def count(result):
        matches = re.findall(r'^Ran (\d+) tests? in ', result['output'], re.MULTILINE)
        return int(matches[-1]) if matches else 0

    if baseline['timed_out'] or candidate['timed_out']:
        return False
    if baseline['exit_code'] == 0 or candidate['exit_code'] != 0:
        return False
    expected, actual = count(baseline), count(candidate)
    if expected == 0 or actual != expected:
        return False
    if any(error in baseline['output'] + candidate['output']
           for error in ('ModuleNotFoundError', 'ImportError', '_FailedTest')):
        return False
    skipped = re.search(r'OK \(skipped=(\d+)\)', candidate['output'])
    return not skipped or int(skipped.group(1)) < actual
