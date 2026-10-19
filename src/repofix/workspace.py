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


def snapshot_committed(source, target):
    """Materialize committed source, excluding side effects from baseline tests."""
    import tarfile
    import tempfile
    from pathlib import PurePosixPath
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary)
        with (folder/'source.tar').open('wb') as archive:
            subprocess.run(['git','-C',str(source),'archive','HEAD'],stdout=archive,
                           stderr=subprocess.PIPE,check=True,timeout=30)
        clean=folder/'clean'
        clean.mkdir()
        with tarfile.open(folder/'source.tar') as archive:
            for member in archive:
                relative=PurePosixPath(member.name)
                if relative.is_absolute() or '..' in relative.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsupported path in committed snapshot')
                destination=clean/str(relative)
                if member.isdir():
                    destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as data, destination.open('wb') as file:
                        shutil.copyfileobj(data,file)
                    destination.chmod(0o755 if member.mode & 0o111 else 0o644)
        snapshot(clean,target)


def directory_fingerprint(path):
    import hashlib
    digest=hashlib.sha256()
    for file in sorted(Path(path).rglob('*')):
        relative=file.relative_to(path)
        if '__pycache__' in relative.parts or file.suffix=='.pyc':
            continue
        if file.is_symlink():
            raise ValueError('Verification symlinks are unsupported')
        if file.is_file():
            digest.update(str(relative).encode()+b'\0')
            digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()
