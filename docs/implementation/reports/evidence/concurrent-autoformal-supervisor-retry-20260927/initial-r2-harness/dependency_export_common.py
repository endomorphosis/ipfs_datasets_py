"""Independent export owner helpers, copied from reviewed R2 preparation.

No selected snapshot is required to import this module. It uses the existing
canonical dependency only for resource admission; exported code is never run.
"""
import hashlib
import ctypes
import signal
import time
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
ACCELERATE = ROOT / 'ipfs_accelerate_py'
HERE = Path(__file__).resolve().parent
LEDGER = ROOT / 'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
GIT_ENV = ('GIT_INDEX_FILE', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR',
           'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES')
FILES = ('native_supervisor_driver.py', 'parent_harness.py', 'training_lane.py',
         'conversion_lane.py', 'frozen-config.json', 'smoke_resource_common.py',
         'native_guard_child.py', 'run_native_smoke_reserved.py')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def reference(path):
    path = Path(path).absolute()
    require(path.resolve(strict=True) == path, 'aliased source or artifact')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), 'nonregular source or artifact')
        raw = stream.read()
        after = os.fstat(stream.fileno())
    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    require(identity(before) == identity(after) == identity(path.stat(follow_symlinks=False)),
            'source or artifact changed during read')
    return raw, {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def ref(path):
    return reference(path)[1]


def exact(rows):
    return all(ref(row['path']) == row for row in rows)


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    require(len(raw) <= 8_000_000, 'receipt exceeds 8 MB')
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return ref(path)


def durable(root):
    directories = [Path(root)]
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            continue
        if path.is_dir():
            directories.append(path)
        elif path.is_file():
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def environment(attempt):
    env = dict(os.environ)
    for name in (*GIT_ENV, 'PYTHONPATH', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'HF_TOKEN',
                 'HUGGING_FACE_HUB_TOKEN', 'HUGGINGFACE_HUB_TOKEN'):
        env.pop(name, None)
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0',
               HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', HF_HOME=str(attempt / 'hub'),
               HUGGINGFACE_HUB_CACHE=str(attempt / 'hub/hub'), HF_DATASETS_CACHE=str(attempt / 'hub/datasets'),
               TMPDIR=str(attempt / 'tmp'), TMP=str(attempt / 'tmp'), TEMP=str(attempt / 'tmp'),
               XDG_CACHE_HOME=str(attempt / 'cache'), OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='',
               IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA='0', IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE='0',
               IPFS_ACCELERATE_AGENT_WORKTREE_POOL_ENABLED='0', ELAN_TOOLCHAIN='leanprover/lean4:v4.26.0')
    return env


class ScopedSources:
    def __init__(self):
        self.rows = {}
        owner = self
        class Loader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                raw, row = reference(self.path)
                owner.add(row)
                return compile(raw, self.path, 'exec', dont_inherit=True)
        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                package = fullname.split('.')[0]
                if package not in {'ipfs_datasets_py', 'ipfs_accelerate_py'}:
                    return None
                root = ROOT / package if package == 'ipfs_datasets_py' else ACCELERATE / package
                spec = importlib.machinery.PathFinder.find_spec(fullname, path)
                if spec is None:
                    raise ModuleNotFoundError('No module named ' + repr(fullname), name=fullname)
                if spec.origin is None:
                    require(all(Path(p).resolve().is_relative_to(root) for p in spec.submodule_search_locations or ()),
                            'foreign namespace package')
                    return spec
                origin = Path(spec.origin).resolve()
                require(origin.is_relative_to(root) and origin.suffix == '.py', 'foreign project loader')
                spec.loader = Loader(fullname, str(origin))
                return spec
        sys.meta_path.insert(0, Finder())
        def audit(event, args):
            if event != 'exec' or not args:
                return
            name = getattr(args[0], 'co_filename', '')
            if not name or name.startswith('<'):
                return
            path = Path(name).absolute()
            if path.suffix == '.py' and (path.is_relative_to(ROOT) or path.is_relative_to(HERE)):
                owner.add(ref(path))
            elif any(part in {'HACC', 'hallucinate_app', 'ipfs_datasets_py', 'ipfs_accelerate_py'} for part in path.parts):
                require(False, 'foreign project execution')
        sys.addaudithook(audit)
    def add(self, row):
        require(self.rows.setdefault(row['path'], row) == row, 'source changed before reuse')
    def verify(self):
        require(exact(self.rows.values()), 'executed canonical source changed')
        return sorted(self.rows.values(), key=lambda row: row['path'])


def bootstrap(sources):
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ACCELERATE), str(ROOT)]
    path = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py'
    raw, row = reference(path)
    sources.add(row)
    namespace = {'__name__': '_concurrent_smoke_network_guard', '__file__': str(path), '__package__': ''}
    exec(compile(raw, str(path), 'exec'), namespace)
    return namespace['_deny_network']()


class Descendants:
    """PID+birth fencing includes children that create new sessions or double-fork.

    This owner is a Linux subreaper, so otherwise orphaned descendants return
    here. Existing unrelated process groups are never signaled.
    """
    def __init__(self, process):
        self.process = process
        self.known = {}
        libc = ctypes.CDLL(None, use_errno=True)
        require(libc.prctl(36, 1, 0, 0, 0) == 0, 'cannot install child subreaper')
        current = ctypes.c_int()
        require(libc.prctl(37, ctypes.byref(current), 0, 0, 0) == 0 and current.value == 1,
                'child subreaper was not established')
    def observe(self):
        rows = {}
        entries = list(Path('/proc').iterdir())
        require(len(entries) <= 100_000, 'process inventory bound exceeded')
        for path in entries:
            if path.name.isdecimal():
                row = self.process(int(path.name))
                if row:
                    rows[row['pid']] = row
        selected = {os.getpid()}
        changed = True
        while changed:
            changed = False
            for pid, row in rows.items():
                owned = self.known.get(pid) == row['birth'] or row['parent_pid'] in selected
                if owned and pid not in selected:
                    selected.add(pid)
                    self.known[pid] = row['birth']
                    changed = True
        return [rows[pid] for pid in sorted(selected) if pid != os.getpid()]
    def living(self):
        return [row for row in self.observe() if row['state'] != 'Z']
    def signal(self, sig):
        for row in reversed(self.living()):
            current = self.process(row['pid'])
            if current and current['birth'] == row['birth']:
                try:
                    os.kill(row['pid'], sig)
                except ProcessLookupError:
                    pass
    def reap(self, child):
        # Let Popen preserve the root child's true wait status before reaping
        # adopted descendants. It may still be running at this boundary.
        child.poll()
        if child.returncode is None:
            return
        while True:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
                if not pid:
                    return
            except ChildProcessError:
                return
    def settle(self, child):
        if self.living():
            self.signal(signal.SIGTERM)
            deadline = time.monotonic() + 2
            while self.living() and time.monotonic() < deadline:
                child.poll()
                time.sleep(.05)
        deadline = time.monotonic() + 8
        while self.living() and time.monotonic() < deadline:
            self.signal(signal.SIGKILL)
            child.poll()
            time.sleep(.05)
        child.wait(timeout=2)
        self.reap(child)
        require(not self.living(), 'owned descendant termination is unconfirmed')

