"""Run only frozen export test targets inside the existing native child.

The parent launcher owns admission, process supervision, durability and release.
This driver grants no authority and performs no corpus acquisition or training.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_JUNIT_BYTES = 8 * 1024 * 1024
MAX_CASES = 20_000
OUTPUT_NAMES = ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')
FORBIDDEN_ROOTS = frozenset({'torch', 'transformers', 'sentence_transformers',
    'tensorflow', 'jax', 'jaxlib', 'onnxruntime', 'vllm', 'diffusers', 'accelerate',
    'huggingface_hub', 'datasets'})


class QualificationFailure(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise QualificationFailure(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def physical_parents(path):
    need(path.is_absolute(), 'absolute path required')
    for parent in (path.parent, *path.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), 'unaliased physical parents required')


def snapshot(path, maximum, *, allow_empty=False):
    path = Path(path)
    physical_parents(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and (0 if allow_empty else 1) <= before.st_size <= maximum,
            'bounded single-link regular input required')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    need(len(raw) == before.st_size and identity(before) == identity(after)
        == identity(path.lstat()), 'input changed while reading')
    return raw


def decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, 'duplicate metadata key refused')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _:
        (_ for _ in ()).throw(QualificationFailure('nonfinite metadata refused')))


def code_guard(pins):
    need(type(pins) is dict and 0 < len(pins) <= 256, 'finite native source pins required')
    for spelling, digest in pins.items():
        need(type(spelling) is str and type(digest) is str
            and re.fullmatch(r'[0-9a-f]{64}', digest), 'exact source descriptor required')
        # Empty hash-only initializer inputs are allowed; executable modules
        # separately require a positive checked source buffer in the finder.
        need(sha(snapshot(Path(spelling), MAX_SOURCE_BYTES, allow_empty=True)) == digest,
            'frozen source pin differs')


def directory_guard(directories):
    for path, expected in directories.items():
        physical_parents(path / '__directory_identity_only__')
        info = path.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0
            and (info.st_dev, info.st_ino) == expected,
            'native output directory identity changed')


def save(path, value, directories):
    directory_guard(directories)
    need(path.parent in directories, 'receipt must use one stable native output root')
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
        allow_nan=False) + '\n').encode('utf-8')
    need(len(raw) <= MAX_METADATA_BYTES, 'qualification receipt exceeds byte bound')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    need(snapshot(path, MAX_METADATA_BYTES) == raw, 'qualification receipt readback differs')
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


class BufferLoader(importlib.abc.Loader):
    def __init__(self, path, raw, finder):
        self.path, self.raw, self.finder = path, raw, finder

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.raw, str(self.path), 'exec', dont_inherit=True, optimize=0), module.__dict__)
        self.finder.loaded[module.__name__] = {'path': str(self.path), 'sha256': sha(self.raw)}


class DiscoveryOnlyLoader(importlib.abc.Loader):
    def __init__(self, finder):
        self.finder = finder

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.finder.refused.append(module.__name__)
        raise ImportError('discovery-only router probe cannot execute a router body')


class PinnedProductFinder(importlib.abc.MetaPathFinder):
    """Preserve real module discovery and compile only admitted source bytes."""
    def __init__(self, root, pins):
        self.root, self.pins = root, pins
        self.loaded, self.namespaces, self.refused, self.router_probes = {}, {}, [], []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition('.')[0] in FORBIDDEN_ROOTS:
            self.refused.append(fullname)
            raise ImportError('model or Hub SDK import refused')
        if fullname != 'ipfs_datasets_py' and not fullname.startswith('ipfs_datasets_py.'):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            self.refused.append(fullname)
            raise ImportError('product module not found in selected checkout')
        if fullname == 'ipfs_datasets_py.ipfs_backend_router':
            # The unchanged root initializer uses find_spec for capability
            # discovery. Preserve that result without executing the router.
            self.router_probes.append({'module': fullname, 'origin': spec.origin})
            spec.loader = DiscoveryOnlyLoader(self)
            return spec
        if spec.origin is None and spec.submodule_search_locations is not None:
            locations = [Path(p) for p in spec.submodule_search_locations]
            need(bool(locations) and all(self.root in p.parents for p in locations),
                'namespace origin outside selected checkout')
            for location in locations:
                physical_parents(location / '__namespace_identity_only__')
            self.namespaces[fullname] = [str(p) for p in locations]
            return spec
        source = Path(spec.origin or '')
        if not (source.is_absolute() and source.suffix == '.py'
                and self.root in source.parents and str(source) in self.pins):
            self.refused.append(fullname)
            raise ImportError('product source outside frozen pin map')
        raw = snapshot(source, MAX_SOURCE_BYTES)
        need(sha(raw) == self.pins[str(source)], 'executed product buffer differs from source pin')
        spec.loader = BufferLoader(source, raw, self)
        return spec


def product_origins(root, pins, finder):
    result = {}
    for name, module in tuple(sys.modules.items()):
        if name != 'ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):
            continue
        spelling = module.__dict__.get('__file__')
        if spelling is None:
            need(name in finder.namespaces and list(module.__path__) == finder.namespaces[name],
                'unqualified product namespace')
            continue
        path = Path(spelling)
        need(path.is_absolute() and path.suffix == '.py' and root in path.parents
            and str(path) in pins and finder.loaded.get(name)
            == {'path': str(path), 'sha256': pins[str(path)]},
            'loaded product did not execute its frozen source buffer')
        result[name] = finder.loaded[name]
    need(not finder.refused, 'a forbidden import was attempted, even if suppressed')
    return result


def no_forbidden_modules():
    need(not any(name.partition('.')[0] in FORBIDDEN_ROOTS for name in sys.modules),
        'model or Hub SDK module loaded')


def covers(target, nodeid):
    return nodeid == target or nodeid.startswith(target + '::') or nodeid.startswith(target + '[')


class CollectionEvidence:
    """Read-only pytest observations; no selection, fixtures or assertions changed."""
    def __init__(self, root, selected, pins):
        self.root, self.selected, self.pins = root, selected, pins
        self.nodeids, self.modules, self.calls, self.unsuccessful = [], {}, [], []

    def pytest_collection_finish(self, session):
        need(0 < len(session.items) <= MAX_CASES, 'positive bounded pytest collection required')
        for item in session.items:
            nodeid = item.nodeid
            need(any(covers(target, nodeid) for target in self.selected), 'pytest collected an unselected target')
            path = Path(item.path)
            need(self.root in path.parents and str(path) in self.pins, 'collected test source is not pinned')
            relative = path.relative_to(self.root).as_posix()
            names = self.modules.setdefault(relative, set())
            names.update((relative[:-3].replace('/', '.'), item.module.__name__))
            self.nodeids.append(nodeid)
        need(len(self.nodeids) == len(set(self.nodeids)), 'duplicate collected test node IDs')

    def pytest_runtest_logreport(self, report):
        if report.failed or report.skipped:
            self.unsuccessful.append({'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome})
        if report.when == 'call' and report.passed:
            self.calls.append(report.nodeid)


def junit_evidence(path, evidence):
    raw = snapshot(path, MAX_JUNIT_BYTES)
    cases = list(ET.fromstring(raw).iter('testcase'))
    need(0 < len(cases) <= MAX_CASES, 'positive bounded JUnit testcase population required')
    identifiers, by_module = [], Counter()
    for case in cases:
        classname, name = case.get('classname'), case.get('name')
        need(type(classname) is str and type(name) is str
            and 0 < len(classname) <= 8192 and 0 < len(name) <= 8192, 'bounded JUnit testcase ID required')
        need(not any(case.find(key) is not None for key in ('failure', 'error', 'skipped')),
            'JUnit failure, error or skip refused')
        modules = [module for module, prefixes in evidence.modules.items()
            if any(classname == prefix or classname.startswith(prefix + '.') for prefix in prefixes)]
        need(len(modules) == 1, 'JUnit testcase module is missing or ambiguous')
        by_module[modules[0]] += 1
        identifiers.append({'classname': classname, 'name': name})
    keys = [(row['classname'], row['name']) for row in identifiers]
    need(len(keys) == len(set(keys)) == len(evidence.nodeids) == len(evidence.calls)
        and set(evidence.calls) == set(evidence.nodeids) and not evidence.unsuccessful,
        'JUnit, collection and successful call populations differ')
    coverage = {target: sum(covers(target, nodeid) for nodeid in evidence.nodeids)
        for target in evidence.selected}
    need(all(count > 0 for count in coverage.values()), 'selected target has no executed testcase')
    return {'file': {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)},
        'case_count': len(cases), 'unique_testcase_ids': identifiers,
        'counts_by_module': dict(sorted(by_module.items())), 'selected_target_coverage': coverage,
        'failures': 0, 'errors': 0, 'skipped': 0}


def main():
    need(len(sys.argv) == 2 and not sys.flags.optimize, 'one native request and nonoptimized Python required')
    request_path = Path(sys.argv[1])
    request_raw = snapshot(request_path, MAX_METADATA_BYTES)
    request = decode(request_raw)
    need(type(request) is dict and request.get('schema') == 'owned-validation-request/v1', 'native request schema differs')
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    need(root.is_absolute() and root == Path.cwd(), 'selected checkout cwd differs')
    physical_parents(root / '__root_identity_only__')
    root_identity = (root.lstat().st_dev, root.lstat().st_ino)
    layout = {name: str(attempt / name) for name in OUTPUT_NAMES}
    need(request['outputs'] == layout and request['declared_external_writable_paths'] == []
        and request['process_scope'] == 'isolated_process_group', 'exact native writable layout required')
    directories = {}
    for path in (attempt, *(Path(p) for p in layout.values())):
        physical_parents(path / '__directory_identity_only__')
        info = path.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0, 'private native output directories required')
        directories[path] = (info.st_dev, info.st_ino)
    pins, selected = request['source_sha256'], request['selected_checks']
    need(type(selected) is list and 0 < len(selected) <= 256 and len(selected) == len(set(selected)),
        'unique selected pytest targets required')
    for target in selected:
        need(type(target) is str and target and not target.startswith('-'), 'explicit pytest target required')
        test_path = Path(target.split('::', 1)[0])
        need(not test_path.is_absolute() and '..' not in test_path.parts and test_path.suffix == '.py'
            and str(root / test_path) in pins, 'selected test module must have a frozen source pin')
    need(type(pins) is dict and str(Path(__file__).absolute()) in pins
        and str(root / 'pytest.ini') in pins, 'driver and pytest configuration pins required')
    need(sys.dont_write_bytecode and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' and os.environ.get('TMPDIR') == layout['tmp']
        and os.environ.get('XDG_CACHE_HOME') == layout['cache'], 'native writable redirects differ')
    redirects = dict(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'], SQLITE_TMPDIR=layout['db'],
        XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'], HF_HUB_CACHE=layout['cache'],
        HUGGINGFACE_HUB_CACHE=layout['cache'], HF_DATASETS_CACHE=layout['cache'],
        TRANSFORMERS_CACHE=layout['cache'], SENTENCE_TRANSFORMERS_HOME=layout['cache'])
    os.environ.update(redirects, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTEST_ADDOPTS='', PYTEST_PLUGINS='',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0', IPFS_AUTO_INSTALL='false',
        IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0', HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        MKL_NUM_THREADS='1', BLIS_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = layout['tmp']
    logs, exports = Path(layout['logs']), Path(layout['exports'])
    receipt = {'schema': 'legal-primary-graph-export-qualification/v1', 'status': 'failed',
        'request_sha256': sha(request_raw), 'selected_checks': selected, 'completed_checks': [],
        'all_checks_complete': False, 'authority_granted': False, 'admitted': False,
        'formalized': False, 'source_semantics_verified': False, 'legal_meanings_reviewed': False,
        'training_performed': False, 'models_loaded': False, 'Lean_executed': False,
        'native_parent_owns_admission_supervision_seal_and_release': True,
        'scope': 'selected standalone synthetic-fixture pytest targets only; no original corpus acquisition',
        'writable_path_redirections': redirects}
    started, stage = time.monotonic(), 'source_preflight'
    attempts = {'network': 0, 'child_process': 0}
    finder = None
    try:
        code_guard(pins)
        no_forbidden_modules()
        need(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
            'fresh product import process required')
        # Let normal Python discovery see the actual checkout. No namespace
        # shells, fake optional modules or import fallback bodies are installed.
        sys.path.insert(0, str(root))
        finder = PinnedProductFinder(root, pins)
        sys.meta_path.insert(0, finder)
        def audit(event, args):
            if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                    'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
                attempts['network'] += 1
                raise QualificationFailure('network operation refused during export qualification')
            if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
                attempts['child_process'] += 1
                raise QualificationFailure('extra child process refused during export qualification')
        sys.addaudithook(audit)
        stage = 'dependency_thread_limits'
        import pyarrow as arrow
        arrow.set_cpu_count(1)
        arrow.set_io_thread_count(1)
        stage = 'selected_pytest_targets'
        import pytest
        arguments = ['-c', str(root / 'pytest.ini'), '-o',
            'addopts=-q --tb=short --strict-markers --import-mode=importlib',
            '--noconftest', '--disable-warnings', '-p',
            'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest',
            '--basetemp=' + str(Path(layout['pytest']) / 'basetemp'),
            '--junitxml=' + str(exports / 'junit.xml'), '-o',
            'cache_dir=' + str(Path(layout['cache']) / 'pytest'), *selected]
        receipt['pytest_arguments'] = arguments
        evidence = CollectionEvidence(root, selected, pins)
        code = pytest.main(arguments, plugins=[evidence])
        receipt['pytest_exit_code'] = int(code)
        need(int(code) == 0, 'selected pytest targets failed')
        stage = 'junit_and_closing_guards'
        receipt['junit'] = junit_evidence(exports / 'junit.xml', evidence)
        need(snapshot(request_path, MAX_METADATA_BYTES) == request_raw, 'native request changed')
        code_guard(pins)
        directory_guard(directories)
        no_forbidden_modules()
        receipt['loaded_product_source_origins'] = product_origins(root, pins, finder)
        need(Path.cwd() == root and (root.lstat().st_dev, root.lstat().st_ino) == root_identity,
            'source checkout identity changed')
        need(tempfile.tempdir == layout['tmp'] and all(os.environ.get(k) == v for k, v in redirects.items()),
            'native writable redirects changed')
        need(arrow.cpu_count() == arrow.io_thread_count() == 1, 'Arrow thread limits changed')
        need(not any(attempts.values()), 'network or extra process attempt occurred, even if suppressed')
        receipt.update(status='pass', completed_checks=list(selected), all_checks_complete=True,
            elapsed_seconds=time.monotonic() - started, guard_attempts=attempts,
            product_router_discovery_only=finder.router_probes,
            natural_product_namespaces=finder.namespaces,
            dependency_versions={'pytest': pytest.__version__, 'pyarrow': arrow.__version__,
                'numpy': getattr(sys.modules.get('numpy'), '__version__', None)},
            arrow_thread_limits={'cpu': arrow.cpu_count(), 'io': arrow.io_thread_count()},
            limitations=['This is test execution evidence, not legal meaning, review, training or Lean authority.',
                'Test and fixture writes use explicit native paths and redirects; the native profile is cooperative, not a kernel filesystem quota or sandbox.',
                'Python socket/process audit events are denied; this is not an OS network-isolation attestation.',
                'Product Python modules execute checked source buffers; external dependency versions do not attest distribution integrity.',
                'Only the native parent can assert final process closeout, artifact durability and resource release.'])
        pin = save(logs / 'qualification.json', receipt, directories)
        print(json.dumps({'status': 'pass', 'receipt': pin, 'test_cases': receipt['junit']['case_count']}, sort_keys=True))
        return 0
    except BaseException as error:
        receipt.update(status='failed', all_checks_complete=False, completed_checks=[],
            failure_stage=stage, error_type=type(error).__name__,
            elapsed_seconds=time.monotonic() - started, guard_attempts=attempts,
            error='Qualification failed; exception values omitted from metadata.')
        try:
            code_guard(pins)
            receipt['final_source_pins_unchanged'] = True
        except BaseException:
            receipt['final_source_pins_unchanged'] = False
        save(logs / 'qualification-failed.json', receipt, directories)
        raise QualificationFailure('export qualification failed at ' + stage
            + ' (' + type(error).__name__ + ')') from None


if __name__ == '__main__':
    raise SystemExit(main())
