"""Verify the explicitly selected published dependency; never select a fallback."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
PLANNED_ROOT = ROOT / 'workspace/test-logs/federal-corpus-audits/concurrent-autoformal-dependency-20260927/capture-r1/published-source'
GIT_ENV = ('GIT_INDEX_FILE', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR',
           'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def bounded_file(path, limit=8_000_000):
    path = Path(path).absolute()
    require(path.resolve(strict=True) == path, 'aliased dependency artifact')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'dependency artifact exceeds bound')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    require(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.stat()),
            'dependency artifact changed during observation')
    return raw


def read_binding(config_path):
    config = json.loads(bounded_file(config_path))
    binding = config.get('accelerate_dependency')
    require(isinstance(binding, dict), 'explicit accelerate dependency is required')
    for key in ('source_commit', 'snapshot_commit'):
        require(isinstance(binding.get(key), str) and re.fullmatch(r'[0-9a-f]{40}', binding[key]),
                'unfilled or invalid dependency ' + key)
    require(isinstance(binding.get('manifest_sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', binding['manifest_sha256']), 'unfilled dependency manifest SHA')
    require(binding.get('root') == str(PLANNED_ROOT), 'dependency root differs from explicit owned selection')
    require(binding.get('manifest_path') == str(PLANNED_ROOT.parent / 'dependency-manifest.json'),
            'dependency manifest is outside its selected capture')
    return dict(binding)


def verify_binding(binding):
    root = Path(binding['root'])
    require(root.resolve(strict=True) == root and root.is_dir(), 'selected dependency root is aliased or absent')
    raw = bounded_file(binding['manifest_path'])
    require(hashlib.sha256(raw).hexdigest() == binding['manifest_sha256'], 'dependency manifest changed')
    manifest = json.loads(raw)
    require(manifest.get('schema') == 'autoformal-published-dependency-manifest/v1', 'unknown dependency manifest')
    for key in ('source_commit', 'snapshot_commit'):
        require(manifest.get(key) == binding[key], 'dependency commit binding changed: ' + key)
    require(manifest.get('snapshot_root') == str(root), 'dependency snapshot root changed')
    require(manifest.get('source_root') == str(ROOT / 'ipfs_accelerate_py'), 'dependency source tree changed')
    rows = manifest.get('files')
    require(isinstance(rows, list) and 1 <= len(rows) <= 5000, 'invalid dependency file inventory')
    expected = set()
    total = 0
    for row in rows:
        relative = row['path']
        path = Path(relative)
        require(isinstance(relative, str) and path.as_posix() == relative and not path.is_absolute()
                and '..' not in path.parts and '.git' not in path.parts and relative not in expected,
                'unsafe or duplicate dependency inventory path')
        expected.add(relative)
        content = bounded_file(root / relative)
        require(type(row.get('bytes')) is int and len(content) == row['bytes']
                and hashlib.sha256(content).hexdigest() == row['sha256'], 'dependency file changed: ' + relative)
        total += len(content)
    require(total <= 180_000_000 and total == manifest.get('committed_bytes'), 'dependency source byte bound differs')
    actual = set()
    for directory, names, files in os.walk(root, followlinks=False):
        if Path(directory) == root:
            names[:] = [name for name in names if name != '.git']
        for name in names:
            require(not (Path(directory) / name).is_symlink(), 'dependency directory is aliased')
        for name in files:
            path = Path(directory) / name
            require(not path.is_symlink(), 'dependency file is aliased')
            actual.add(path.relative_to(root).as_posix())
    require(actual == expected, 'dependency file set changed')
    require('ipfs_accelerate_py/__init__.py' in expected, 'selected package is missing')
    env = {key: value for key, value in os.environ.items() if key not in GIT_ENV}
    env.update(GIT_NO_LAZY_FETCH='1', GIT_LFS_SKIP_SMUDGE='1')
    head = subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', 'rev-parse', '--verify', 'HEAD'],
                                   cwd=root, env=env, timeout=15, text=True).strip()
    require(head == binding['snapshot_commit'], 'dependency snapshot HEAD changed')
    return {'root': str(root), 'source_commit': binding['source_commit'], 'snapshot_commit': head,
            'manifest_sha256': binding['manifest_sha256'], 'file_count': len(rows), 'source_bytes': total}
