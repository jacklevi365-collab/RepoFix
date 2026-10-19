import os
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


def patched_workspace(source, patch, target):
    """Apply the delivered patch to a fresh snapshot, never reuse agent state."""
    snapshot(source, target)
    subprocess.run(['git', '-C', str(target), 'apply', '--', str(Path(patch).resolve())],
                   check=True, capture_output=True, timeout=30)


def integrity_violations(workspace):
    """Existing tests cannot change; dependency/test configuration cannot be added."""
    original = set(git(workspace, 'ls-tree', '-r', '--name-only', '-z', 'HEAD').split('\0'))
    changed = git(workspace, 'diff', '--name-only', '-z', 'HEAD').split('\0')
    violations = []
    for name in filter(None, changed):
        path = Path(name)
        test = ('tests' in path.parts or 'test' in path.parts or path.name == 'tests.py'
                or path.name.startswith('test_') or path.name.endswith('_test.py'))
        config = (path.name in {'pyproject.toml', 'setup.py', 'setup.cfg', 'pytest.ini',
                  'tox.ini', 'conftest.py', 'Pipfile', 'Pipfile.lock', 'poetry.lock', 'uv.lock',
                  'sitecustomize.py', 'usercustomize.py'}
                  or path.name.startswith('requirements') and path.suffix in {'.txt', '.in'})
        if config or test and name in original:
            violations.append(name)
    return sorted(violations)
