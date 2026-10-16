"""Replay retained source artifacts inside one genuine native owned child.

The unchanged parent owns admission, process custody, sealing and release.
This worker opens no catalog, generates no embeddings and confers no authority.
"""
from __future__ import annotations

from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tempfile
import time
from types import CodeType, FunctionType


HELPER_RELATIVE = 'docs/autoencoders/evidence/legal-relational-target-contract-20261016/run_qualification.py'
HELPER_SHA256 = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
INPUT_SCHEMA = 'legal-retained-source-corpus-reuse-inputs/v1'
REPORT_SCHEMA = 'legal-retained-source-corpus-reuse/v1'
SELECTED_SCHEMA = 'legal-retained-source-companions/v1'
HISTORICAL_REVISION = '5016b86a273ce5e4ffd066c5ae9f5fe494dd417e'
MANIFEST_SHA256 = '0c6c05582fda19f36c75b166c5c1afecdab156241ce73728f564802b52eacac6'
RELEASE_ID = 'hf:justicedao/ipfs_uscode@' + HISTORICAL_REVISION + '#manifest-sha256:' + MANIFEST_SHA256
OUTPUT_NAMES = ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')
CHECKS = ('inventory_and_frozen_partitions', 'captured_source_version',
    'original_package_binding', 'complete_ordered_source_rows',
    'declared_physical_source_companions', 'closing_custody_and_runtime_guards')
MAX_METADATA = 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_SELECTED_ROWS = 256
MAX_DENIAL_EVENTS = 64
MAX_DENIAL_JOURNAL_BYTES = 256 * 1024
URLLIB3_CONNECTION_PATH = '/home/barberb/.local/lib/python3.12/site-packages/urllib3/util/connection.py'
URLLIB3_CONNECTION_SHA256 = '2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74'
NETWORK_EVENTS = frozenset({'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
    'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'})
FALSE_FLAGS = dict.fromkeys(('authority_granted', 'admitted', 'formalized',
    'training_eligible', 'gold_eligible', 'source_authority_authenticated',
    'source_semantics_verified', 'legal_meanings_reviewed', 'training_performed',
    'models_loaded', 'embedding_inference_performed', 'Lean_executed',
    'Lean_admitted', 'publication_performed', 'database_opened'), False)


class ReplayFailure(RuntimeError):
    pass


class NativeWriteAudit:
    """Deny external writes and retain bounded actual refusals privately.

    An integer open argument is an already-held descriptor, not a pathname.
    Its live /proc link, physical path and file identity must all agree with
    one ordinary single-link file beneath this exact native attempt.
    """

    def __init__(self, attempt, q, directories, attempts):
        self.attempt, self.q, self.directories, self.attempts = attempt, q, directories, attempts
        self.events, self.event_count, self.journal_bytes = [], 0, 0
        self.journal_path = attempt / 'logs' / 'runtime-denials.jsonl'
        q.directory_guard(directories)
        self.fd = os.open(self.journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.file_id = (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino)
        self.journal_incomplete = False

    def _ordinary_native_path(self, spelling, held_fd=None):
        if type(spelling) not in (str, bytes):
            return False
        path = Path(os.fsdecode(spelling))
        if not path.is_absolute() or str(path) != os.path.normpath(str(path)) or not path.is_relative_to(self.attempt):
            return False
        try:
            self.q.directory_guard(self.directories)
            self.q.physical_parents(path)
            if held_fd is None:
                if not path.exists() and not path.is_symlink():
                    return True
                info = path.lstat()
                return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            before = os.fstat(held_fd)
            current = path.lstat()
            after = os.fstat(held_fd)
            return (stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and self.q.identity(before) == self.q.identity(current) == self.q.identity(after))
        except (OSError, ValueError, self.q.QualificationFailure):
            return False

    def _write_is_native(self, value):
        if type(value) is int:
            if value < 0:
                return False
            try:
                spelling = os.readlink('/proc/self/fd/' + str(value))
            except OSError:
                return False
            return self._ordinary_native_path(spelling, held_fd=value)
        return self._ordinary_native_path(value)

    def _journal_current(self):
        before, current = os.fstat(self.fd), self.journal_path.lstat()
        self.q.physical_parents(self.journal_path)
        return (stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and (before.st_dev, before.st_ino) == self.file_id
            and self.q.identity(before) == self.q.identity(current))

    def _append(self, value):
        raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
            separators=(',', ':')).encode('ascii') + b'\n'
        if len(raw) > 8192 or self.journal_bytes + len(raw) > MAX_DENIAL_JOURNAL_BYTES:
            self.journal_incomplete = True
            return
        need(self._journal_current(), 'denial journal physical custody changed')
        offset = 0
        while offset < len(raw):
            written = os.write(self.fd, raw[offset:])
            need(written > 0, 'short denial journal write')
            offset += written
        self.journal_bytes += len(raw)
        os.fsync(self.fd)

    def deny(self, kind, event, args):
        self.attempts[kind] += 1
        self.event_count += 1
        frames, frame = [], sys._getframe(1)
        for _ in range(12):
            if frame is None:
                break
            frames.append({'filename': str(frame.f_code.co_filename)[:1024],
                'function': str(frame.f_code.co_name)[:160], 'line': frame.f_lineno})
            frame = frame.f_back
        value = {'index': self.event_count, 'kind': kind, 'event': event, 'caller_frames': frames}
        if event == 'open' and len(args) == 3:
            path, mode, flags = args
            value.update(path_type=type(path).__name__,
                path=(os.fsdecode(path)[:2048] if type(path) in (str, bytes) else path if type(path) is int else None),
                mode=(mode[:32] if type(mode) is str else None), flags=(flags if type(flags) is int else None))
        if len(self.events) < MAX_DENIAL_EVENTS:
            self.events.append(value)
            self._append(value)
        else:
            self.journal_incomplete = True
        raise ReplayFailure('actual runtime operation refused: ' + kind)

    def __call__(self, event, args):
        if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
            self.deny('network', event, args)
        if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
            self.deny('child_process', event, args)
        if event == 'sqlite3.connect':
            self.deny('database', event, args)
        if event == 'open' and len(args) == 3:
            path, mode, flags = args
            writes = (type(mode) is str and any(symbol in mode for symbol in 'wax+')) or (
                type(flags) is int and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writes and not self._write_is_native(path):
                self.deny('external_write', event, args)

    def evidence(self):
        return {'counts': dict(self.attempts), 'recorded_event_count': len(self.events),
            'actual_denial_count': self.event_count, 'complete': not self.journal_incomplete,
            'events': list(self.events), 'journal': {'path': str(self.journal_path), 'bytes': self.journal_bytes},
            'all_actual_denials_remain_disqualifying': True}

    def failure_fallback(self, stage, error, report_error):
        self._append({'schema': 'legal-source-reuse-failure-report-fallback/v1',
            'failure_stage': stage, 'original_error_type': type(error).__name__,
            'report_write_error_type': type(report_error).__name__, 'guard_attempts': dict(self.attempts),
            'arbitrary_exception_values_omitted': True, 'all_checks_complete': False})

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class ImportOnlyIPv6ProbeAudit(NativeWriteAudit):
    """Admit the exact genuine urllib3 import-time local capability probe.

    This permits one unconnected IPv6 stream socket and its single loopback
    bind during the checked source-binding import. It permits no DNS, connect,
    listening, sending or general socket creation. Actual denials still fail.
    Neither urllib3 nor the real socket implementation is patched or replaced.
    """

    def __init__(self, attempt, q, directories, attempts, pins):
        super().__init__(attempt, q, directories, attempts)
        need(pins.get(URLLIB3_CONNECTION_PATH) == URLLIB3_CONNECTION_SHA256,
            'exact genuine urllib3 probe source pin required')
        self.probe_raw = q.snapshot(Path(URLLIB3_CONNECTION_PATH), 4 * 1024 * 1024)
        need(q.sha(self.probe_raw) == URLLIB3_CONNECTION_SHA256, 'genuine urllib3 probe source differs')
        self.module_code = compile(self.probe_raw, URLLIB3_CONNECTION_PATH, 'exec', dont_inherit=True, optimize=0)
        codes = [item for item in self.module_code.co_consts if isinstance(item, CodeType)
            and item.co_name == '_has_ipv6' and item.co_qualname == '_has_ipv6']
        need(len(codes) == 1, 'unique genuine urllib3 capability code required')
        self.probe_code = codes[0]
        self.socket_module, self.socket_class = socket, socket.socket
        self.window_open, self.window_started, self.window_closed = False, False, False
        self.probe_socket, self.creations, self.binds = None, 0, 0
        self.observed_network_events, self.allowed_probe_events = Counter(), []
        self.closed_descriptor_verified, self.module_identity_verified = False, False

    def begin_binding_import(self):
        need(not self.window_started and 'urllib3.util.connection' not in sys.modules,
            'fresh single source-binding capability window required')
        self.window_started, self.window_open = True, True

    def _genuine_probe_frame(self):
        if not self.window_open:
            return None
        module = sys.modules.get('urllib3.util.connection')
        if module is None or module.__dict__.get('__file__') != URLLIB3_CONNECTION_PATH:
            return None
        globals_ = module.__dict__
        function = globals_.get('_has_ipv6')
        if (type(function) is not FunctionType or function.__globals__ is not globals_
                or function.__code__ != self.probe_code or function.__code__.co_filename != URLLIB3_CONNECTION_PATH
                or globals_.get('socket') is not self.socket_module
                or socket.socket is not self.socket_class
                or not getattr(globals_.get('__spec__'), '_initializing', False)):
            return None
        frame = sys._getframe(1)
        for _ in range(12):
            if frame is None:
                return None
            if frame.f_code is function.__code__:
                parent = frame.f_back
                if (frame.f_globals is globals_ and type(frame.f_locals.get('host')) is str
                        and frame.f_locals['host'] == '::1' and parent is not None
                        and parent.f_globals is globals_ and parent.f_code == self.module_code
                        and parent.f_code.co_filename == URLLIB3_CONNECTION_PATH):
                    return frame
                return None
            frame = frame.f_back
        return None

    def _allow_exact_probe(self, event, args):
        frame = self._genuine_probe_frame()
        if frame is None:
            return False
        if event == 'socket.__new__':
            if (len(args) != 4 or self.creations or self.binds or self.probe_socket is not None
                    or frame.f_locals.get('sock') is not None
                    or type(args[0]) is not self.socket_class
                    or any(type(value) is not int for value in args[1:])
                    or tuple(args[1:]) != (int(socket.AF_INET6), int(socket.SOCK_STREAM), 0)):
                return False
            self.probe_socket, self.creations = args[0], 1
            self.allowed_probe_events.append({'event': event, 'operation': 'import_only_ipv6_capability_creation',
                'family': 'AF_INET6', 'type': 'SOCK_STREAM', 'protocol': 0,
                'genuine_caller_code_and_module_identity_verified': True})
            return True
        if event == 'socket.bind':
            if (len(args) != 2 or self.creations != 1 or self.binds
                    or args[0] is not self.probe_socket or frame.f_locals.get('sock') is not self.probe_socket
                    or type(args[1]) is not tuple or len(args[1]) != 2
                    or type(args[1][0]) is not str or args[1][0] != '::1'
                    or type(args[1][1]) is not int or args[1][1] != 0
                    or self.probe_socket.family != socket.AF_INET6
                    or self.probe_socket.type != socket.SOCK_STREAM or self.probe_socket.proto != 0):
                return False
            self.binds = 1
            self.allowed_probe_events.append({'event': event, 'operation': 'import_only_ipv6_loopback_capability_bind',
                'address': ['::1', 0], 'same_captured_socket_verified': True,
                'genuine_caller_code_and_module_identity_verified': True})
            return True
        return False

    def __call__(self, event, args):
        if event in NETWORK_EVENTS:
            self.observed_network_events[event] += 1
            if event in {'socket.__new__', 'socket.bind'} and self._allow_exact_probe(event, args):
                return
        super().__call__(event, args)

    def end_binding_import(self):
        need(self.window_open and self.window_started and not self.window_closed,
            'active single capability window required')
        self.window_open, self.window_closed = False, True
        need(socket.socket is self.socket_class
            and self.q.snapshot(Path(URLLIB3_CONNECTION_PATH), 4 * 1024 * 1024) == self.probe_raw,
            'genuine probe implementation changed during import')
        module = sys.modules.get('urllib3.util.connection')
        need(module is not None and module.__dict__.get('__file__') == URLLIB3_CONNECTION_PATH,
            'genuine capability module did not complete import')
        function = module.__dict__.get('_has_ipv6')
        need(type(function) is FunctionType and function.__globals__ is module.__dict__
            and function.__code__ == self.probe_code and function.__code__.co_filename == URLLIB3_CONNECTION_PATH
            and not getattr(module.__dict__.get('__spec__'), '_initializing', True),
            'genuine capability function identity changed at import completion')
        self.module_identity_verified = True
        need(self.creations in (0, 1) and self.binds in (0, 1) and self.binds <= self.creations,
            'capability event population exceeds its exact bound')
        need(self.probe_socket is None if self.creations == 0 else
            type(self.probe_socket) is self.socket_class and self.socket_class.fileno(self.probe_socket) == -1,
            'capability socket remains open after definition import')
        self.closed_descriptor_verified = True

    def verify_closed(self):
        need(self.window_closed and not self.window_open and self.closed_descriptor_verified
            and self.module_identity_verified, 'capability window closeout incomplete')
        if self.probe_socket is not None:
            need(self.socket_class.fileno(self.probe_socket) == -1, 'capability socket reopened')
        need(sum(self.observed_network_events.values()) == len(self.allowed_probe_events) + self.attempts['network'],
            'observed capability and denied network events are not fully accounted')

    def evidence(self):
        result = super().evidence()
        result['counter_scope'] = 'counts cover disallowed operations; every observed network event is separately accounted'
        result['import_only_ipv6_capability_profile'] = {
            'source': {'path': URLLIB3_CONNECTION_PATH, 'sha256': URLLIB3_CONNECTION_SHA256, 'bytes': len(self.probe_raw)},
            'window': 'cold_source_binding_owner_import only', 'window_started': self.window_started,
            'window_open': self.window_open, 'window_closed': self.window_closed,
            'creation_count': self.creations, 'bind_count': self.binds,
            'allowed_events': list(self.allowed_probe_events),
            'all_observed_network_event_counts': dict(sorted(self.observed_network_events.items())),
            'captured_socket_closed_verified': self.closed_descriptor_verified,
            'genuine_module_function_and_code_verified': self.module_identity_verified,
            'SDK_or_socket_functions_patched': False,
            'network_or_OS_isolation_attested': False}
        return result


def need(condition, message):
    if not condition:
        raise ReplayFailure(message)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')


def bootstrap_snapshot(path, maximum):
    """Read only bounded bootstrap metadata before the reused helper exists."""
    path = Path(path)
    need(path.is_absolute(), 'absolute bootstrap path required')
    for parent in (path.parent, *path.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), 'physical bootstrap parents required')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and 0 < before.st_size <= maximum, 'bounded bootstrap input required')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
        item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    need(len(raw) == before.st_size and identity(before) == identity(after)
        == identity(path.lstat()), 'bootstrap input changed')
    return raw


def artifact(value, maximum, q):
    need(type(value) is dict and set(value) == {'path', 'sha256', 'bytes'},
        'closed artifact descriptor required')
    need(type(value['path']) is str and Path(value['path']).is_absolute()
        and str(Path(value['path'])) == value['path'] and '..' not in Path(value['path']).parts,
        'absolute ordinary artifact path required')
    need(type(value['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', value['sha256'])
        and type(value['bytes']) is int and 0 < value['bytes'] <= maximum,
        'bounded artifact identity required')
    q.physical_parents(Path(value['path']))
    return dict(value)


def file_identity(path, q):
    path = Path(path)
    q.physical_parents(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        'single-link ordinary input required')
    return q.identity(info)


def fingerprint(reference, q):
    """Stream a bounded exact artifact without retaining another large buffer."""
    path = Path(reference['path'])
    before = file_identity(path, q)
    need(before[3] == reference['bytes'], 'input size differs')
    digest, count = hashlib.sha256(), 0
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        need(q.identity(os.fstat(stream.fileno())) == before, 'input identity differs at open')
        while raw := stream.read(1024 * 1024):
            count += len(raw)
            need(count <= reference['bytes'], 'input exceeds its declared bound')
            digest.update(raw)
        need(q.identity(os.fstat(stream.fileno())) == before, 'input changed during fingerprint')
    need(file_identity(path, q) == before and count == reference['bytes']
        and digest.hexdigest() == reference['sha256'], 'input fingerprint differs')
    return before


def directory_identity(path, q):
    path = Path(path)
    q.physical_parents(path / '__physical_directory_only__')
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode), 'ordinary input directory required')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns)


def save_output(path, value, q, directories, output_budget):
    q.directory_guard(directories)
    need(path.parent in directories, 'stable native output root required')
    raw = wire(value) + b'\n'
    need(output_budget['bytes'] + len(raw) <= MAX_OUTPUT_BYTES, 'complete output exceeds aggregate bound')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    need(q.snapshot(path, MAX_OUTPUT_BYTES) == raw, 'complete output readback differs')
    output_budget['bytes'] += len(raw)
    return {'path': str(path), 'sha256': q.sha(raw), 'bytes': len(raw)}


def main():
    need(len(sys.argv) == 3 and not sys.flags.optimize and sys.dont_write_bytecode,
        'native request, descriptor and nonoptimized no-bytecode Python required')
    request_path, input_path = map(Path, sys.argv[1:])
    request_raw = bootstrap_snapshot(request_path, MAX_METADATA)
    request = json.loads(request_raw)
    need(type(request) is dict and request.get('schema') == 'owned-validation-request/v1',
        'native request schema differs')
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    need(root.is_absolute() and root == Path.cwd(), 'selected checkout differs')
    helper_path = root / HELPER_RELATIVE
    helper_raw = bootstrap_snapshot(helper_path, 4 * 1024 * 1024)
    need(hashlib.sha256(helper_raw).hexdigest() == HELPER_SHA256
        and request['source_sha256'].get(str(helper_path)) == HELPER_SHA256,
        'reused guard helper differs')
    q = type(sys)('_retained_source_corpus_original_guards')
    q.__file__ = str(helper_path)
    exec(compile(helper_raw, str(helper_path), 'exec', dont_inherit=True, optimize=0), q.__dict__)
    original_forbidden_roots = sorted(q.FORBIDDEN_ROOTS)
    # The real source-package owner imports publisher definitions. Keep those
    # genuine optional definitions, while denying all network/process use.
    # This is a declared worker import profile; no native policy is changed.
    q.FORBIDDEN_ROOTS = q.FORBIDDEN_ROOTS - {'huggingface_hub'}
    # Strictly decode bootstrap metadata again through the unchanged helper.
    request = q.decode(request_raw)
    pins = request['source_sha256']
    need(str(Path(__file__).absolute()) in pins and str(input_path) in pins,
        'worker and independent input descriptor pins required')
    need(request['selected_checks'] == list(CHECKS), 'complete named replay checks required')
    need(request['argv'][1:] == ['-B', str(Path(__file__).absolute()), str(request_path), str(input_path)],
        'native child arguments differ')
    layout = {name: str(attempt / name) for name in OUTPUT_NAMES}
    need(request['outputs'] == layout and request['declared_external_writable_paths'] == []
        and request['process_scope'] == 'isolated_process_group', 'native output layout differs')
    directories = {}
    for path in (attempt, *(Path(value) for value in layout.values())):
        q.physical_parents(path / '__native_directory_only__')
        info = path.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0, 'private native directories required')
        directories[path] = (info.st_dev, info.st_ino)
    need(os.environ.get('TMPDIR') == layout['tmp'] and os.environ.get('XDG_CACHE_HOME') == layout['cache']
        and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1', 'native redirects differ')
    redirects = dict(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'], SQLITE_TMPDIR=layout['db'],
        XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'], HF_HUB_CACHE=layout['cache'],
        HUGGINGFACE_HUB_CACHE=layout['cache'], HF_DATASETS_CACHE=layout['cache'],
        TRANSFORMERS_CACHE=layout['cache'], SENTENCE_TRANSFORMERS_HOME=layout['cache'])
    os.environ.update(redirects, IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0', HF_HUB_OFFLINE='1',
        HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', BLIS_NUM_THREADS='1',
        VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = layout['tmp']
    report = dict(schema=REPORT_SCHEMA, worker_generation='v03', status='failed', all_checks_complete=False,
        request_sha256=q.sha(request_raw), input_descriptor_sha256=pins[str(input_path)],
        checks=[{'name': name, 'status': 'not_run'} for name in CHECKS],
        original_guard_helper={'path': str(helper_path), 'sha256': HELPER_SHA256},
        source_reuse_import_profile={'original_forbidden_roots': original_forbidden_roots,
            'current_forbidden_roots': sorted(q.FORBIDDEN_ROOTS),
            'only_allowed_optional_sdk_root': 'huggingface_hub',
            'genuine_urllib3_import_only_ipv6_capability_probe':
                'One checked genuine AF_INET6/SOCK_STREAM creation and same-object bind(::1,0), closed before source reads.',
            'identical_original_import_guard_claimed': False,
            'publisher_or_hub_client_construction_requested_by_worker': False,
            'hub_upload_or_download_requested_by_worker': False},
        historical_dataset_revision=HISTORICAL_REVISION,
        native_parent_owns_admission_supervision_seal_and_release=True,
        seccomp_invoked=False, os_network_isolation_attested=False,
        seccomp_omission_reason='The existing resolver may spawn ldconfig, incompatible with this one-child profile.',
        scope='Retained published source/package integrity and exposed source companions; no normative targets.',
        **FALSE_FLAGS)
    attempts = {'network': 0, 'child_process': 0, 'external_write': 0, 'database': 0}
    finder, audit_state, stage = None, None, 'bootstrap_source_guard'
    output_budget = {'bytes': 0}
    started = time.monotonic()
    try:
        q.code_guard(pins)
        q.no_forbidden_modules()
        need(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
            'cold product import required')
        root_identity = directory_identity(root, q)
        input_raw = q.snapshot(input_path, MAX_METADATA)
        need(q.sha(input_raw) == pins[str(input_path)], 'independent descriptor differs')
        input_identity = file_identity(input_path, q)
        inputs = q.decode(input_raw)
        need(type(inputs) is dict and set(inputs) == {'schema', 'inventory', 'partitions',
            'captured_version_report', 'package', 'selected_legal_ids'} and inputs['schema'] == INPUT_SCHEMA,
            'closed reuse input schema required')
        inventory_ref = artifact(inputs['inventory'], 64 * 1024 * 1024, q)
        partition_ref = artifact(inputs['partitions'], 64 * 1024 * 1024, q)
        captured_ref = artifact(inputs['captured_version_report'], MAX_METADATA, q)
        package = inputs['package']
        need(type(package) is dict and set(package) == {'path', 'manifest', 'expected_file_count', 'expected_total_bytes'}
            and package['expected_file_count'] == 103 and package['expected_total_bytes'] == 263671066,
            'exact retained package descriptor required')
        package_root = Path(package['path'])
        need(type(package['path']) is str and package_root.is_absolute()
            and str(package_root) == package['path'] and '..' not in package_root.parts,
            'ordinary retained package path required')
        need(type(package['manifest']) is dict and set(package['manifest']) == {'sha256', 'bytes'},
            'closed package manifest identity required')
        artifact({'path': str(package_root / 'source-export.json'), **package['manifest']}, 4 * 1024 * 1024, q)
        selected_ids = inputs['selected_legal_ids']
        need(type(selected_ids) is list and len(selected_ids) == len(set(selected_ids)) == 3
            and all(type(value) is str and 0 < len(value.encode('utf-8')) <= 4096 for value in selected_ids),
            'three exact declared legal IDs required')
        need(not package_root.is_relative_to(attempt) and not attempt.is_relative_to(package_root)
            and all(not Path(ref['path']).is_relative_to(attempt) for ref in (inventory_ref, partition_ref, captured_ref)),
            'input/output namespaces must be separate')
        sys.path.insert(0, str(root))
        finder = q.PinnedProductFinder(root, pins)
        sys.meta_path.insert(0, finder)

        audit_state = ImportOnlyIPv6ProbeAudit(attempt, q, directories, attempts, pins)
        sys.addaudithook(audit_state)
        stage = 'cold_pyarrow_import'
        import pyarrow as arrow
        need(not any(attempts.values()), 'denied cold Arrow import operation occurred even if suppressed')
        arrow.set_cpu_count(1)
        arrow.set_io_thread_count(1)
        stage = 'cold_inventory_owner_import'
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_inventory import load_uscode_source_inventory
        need(not any(attempts.values()), 'denied cold inventory import operation occurred even if suppressed')
        stage = 'cold_partition_owner_import'
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_partitions import load_source_partitions
        need(not any(attempts.values()), 'denied cold partition import operation occurred even if suppressed')
        stage = 'cold_source_binding_owner_import'
        audit_state.begin_binding_import()
        from ipfs_datasets_py.duckdb_control.source_corpus_binding import (
            SourceCorpusBinding, SourceCorpusBindingError, validate_source_version)
        audit_state.end_binding_import()
        audit_state.verify_closed()
        need(not any(attempts.values()), 'denied cold binding import operation occurred even if suppressed')
        stage = 'cold_source_row_owner_import'
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_corpus_rows import ROW_FIELDS
        need(not any(attempts.values()), 'denied cold source row import operation occurred even if suppressed')
        q.no_forbidden_modules()
        q.product_origins(root, pins, finder)
        input_refs = (inventory_ref, partition_ref, captured_ref)
        input_witnesses = {ref['path']: fingerprint(ref, q) for ref in input_refs}
        package_root_witness = directory_identity(package_root, q)

        stage = CHECKS[0]
        inventory = load_uscode_source_inventory(inventory_ref['path'], expected_sha256=inventory_ref['sha256'],
            expected_size_bytes=inventory_ref['bytes'])
        partitions = load_source_partitions(partition_ref['path'], expected_sha256=partition_ref['sha256'],
            expected_size_bytes=partition_ref['bytes'], inventory=inventory)
        inventory_summary, partition_summary = inventory.summary(), partitions.verification_summary()
        need(inventory_summary['release_id'] == RELEASE_ID and inventory_summary['declared_row_count'] == 62931
            and inventory_summary['declared_corpus_shards'] == 16 and inventory_summary['declared_corpus_closure_verified'] is True,
            'retained inventory population or provenance differs')
        report.update(inventory=inventory_ref, inventory_summary=inventory_summary,
            partitions=partition_ref, partition_summary=partition_summary)
        report['checks'][0]['status'] = 'passed'
        del partitions, inventory
        gc.collect()

        stage = CHECKS[1]
        baseline = q.decode(q.snapshot(Path(captured_ref['path']), MAX_METADATA))
        captured_version = baseline['version_after_reopen']
        need(baseline['input_package'] == str(package_root)
            and captured_version['package_manifest_artifact'] == package['manifest']
            and captured_version['row_count'] == 62931, 'captured source package differs')
        detached = {key: value for key, value in captured_version.items() if key != 'package_directory'}
        validated = validate_source_version(detached)
        need(wire(validated) == wire(detached), 'captured public source version changed')
        refusals = {}
        for name in ('detached_authority_promotion', 'detached_version_id_substitution', 'detached_manifest_commitment_substitution'):
            changed = json.loads(wire(detached))
            if name == 'detached_authority_promotion':
                changed['qualification']['source_authority_authenticated'] = True
            elif name == 'detached_version_id_substitution':
                changed['version_id'] = 'sha256:' + '0' * 64
            else:
                changed['package_manifest_artifact']['sha256'] = '0' * 64
            try:
                validate_source_version(changed)
            except SourceCorpusBindingError:
                refusals[name] = 'refused'
            else:
                raise ReplayFailure('public source owner accepted changed detached commitment')
        report.update(captured_version_report=captured_ref, source_version=detached,
            public_owner_refusals=refusals)
        report['checks'][1]['status'] = 'passed'

        stage = CHECKS[2]
        binding = SourceCorpusBinding(captured_version, package_root)
        selected_rows, selected_counts = [], Counter()
        status_counts, embedding_counts, split_counts, alias_counts = Counter(), Counter(), Counter(), Counter()
        unique_inputs, eligible_rows, row_count, row_digest = set(), 0, 0, hashlib.sha256()
        with binding:
            need(binding.file_count == package['expected_file_count'] and binding.total_bytes == package['expected_total_bytes']
                and binding.manifest_artifact == package['manifest'], 'bound package closure differs')
            metadata = binding.manifest['metadata']
            need(metadata['release']['repo_id'] == 'justicedao/ipfs_uscode'
                and metadata['release']['revision'] == HISTORICAL_REVISION
                and metadata['release']['manifest']['sha256'] == MANIFEST_SHA256
                and metadata['inventory'] == {key: inventory_ref[key] for key in ('sha256', 'bytes')}
                and metadata['source_partitions'] == {key: partition_ref[key] for key in ('sha256', 'bytes')},
                'bound package provenance differs from retained artifacts')
            files = binding.file_descriptors
            package_witnesses = {item['relative_path']: file_identity(package_root / item['relative_path'], q) for item in files}
            report['package'] = dict(package, verified_file_count=binding.file_count,
                verified_total_bytes=binding.total_bytes, row_digest=binding.row_digest,
                file_descriptors=list(files))
            report['checks'][2]['status'] = 'passed'

            stage = CHECKS[3]
            selected_bytes = 0
            for row in binding.iter_rows():
                need(set(row) == {'ordinal', *ROW_FIELDS} and row['ordinal'] == row_count,
                    'complete physical source columns or ordering differ')
                need(row['admitted'] is False and row['formalized'] is False
                    and row['formalization_status'] == 'not_observed', 'source row authority changed')
                row_digest.update(wire(row) + b'\n')
                row_count += 1
                status_counts[row['source_status']] += 1
                embedding_counts[row['embedding_status']] += 1
                split_counts[row['split']] += 1
                alias_counts[row['eligible_alias_count']] += 1
                if row['source_eligible']:
                    eligible_rows += 1
                    unique_inputs.add(row['input_id'])
                if row['legal_id'] in selected_ids:
                    selected_bytes += len(wire(row))
                    need(len(selected_rows) < MAX_SELECTED_ROWS and selected_bytes <= MAX_OUTPUT_BYTES // 2,
                        'complete selected physical population exceeds source companion bound')
                    selected_rows.append(row)
                    selected_counts[row['legal_id']] += 1
            need(row_count == 62931 == binding.row_count and row_digest.hexdigest() == binding.row_digest,
                'complete ordered source digest differs')
            need(dict(split_counts) == partition_summary['partition_counts'],
                'original frozen source split totals differ')
            report['row_population'] = {'physical_rows': row_count, 'ordered_row_digest': row_digest.hexdigest(),
                'source_status_counts': dict(sorted(status_counts.items())),
                'embedding_status_counts': dict(sorted(embedding_counts.items())),
                'split_counts': [{'split': key, 'rows': value} for key, value in sorted(split_counts.items(), key=lambda pair: str(pair[0]))],
                'eligible_alias_count_distribution': [{'eligible_alias_count': key, 'rows': value} for key, value in sorted(alias_counts.items())],
                'source_eligible_physical_rows': eligible_rows, 'unique_eligible_input_ids': len(unique_inputs),
                'additional_eligible_alias_occurrences': eligible_rows - len(unique_inputs)}
            report['checks'][3]['status'] = 'passed'

            stage = CHECKS[4]
            report['selected_companions'] = {'requested_legal_ids': selected_ids, 'physical_rows': len(selected_rows),
                'counts': [{'legal_id': value, 'physical_rows': selected_counts[value],
                    'status': 'found_exposed_engineering_source' if selected_counts[value] else 'missing'} for value in selected_ids],
                'selection_policy': 'Exact declared legal_id equality; all matching physical occurrences; no fallback, normalization or deduplication.',
                'exposure_status': 'exposed', 'original_split_membership_preserved': True,
                'text_coordinate_space': 'exact published text field; distinct from official HTML/USLM and normalized visible text',
                'normative_target_selected': False, 'gold_mask': 0, 'training_mask': 0}
            report['checks'][4]['status'] = 'passed'
            stage = CHECKS[5]
            binding.verify_current()
            need(directory_identity(package_root, q) == package_root_witness
                and all(file_identity(package_root / name, q) == witness for name, witness in package_witnesses.items()),
                'package physical custody changed')
        try:
            binding.source_version
        except SourceCorpusBindingError:
            refusals['expired_binding_access'] = 'refused'
        else:
            raise ReplayFailure('expired public source binding remained usable')
        need(q.snapshot(request_path, MAX_METADATA) == request_raw
            and q.snapshot(input_path, MAX_METADATA) == input_raw and file_identity(input_path, q) == input_identity,
            'native request or input descriptor changed')
        need(all(fingerprint(ref, q) == input_witnesses[ref['path']] for ref in input_refs),
            'readonly artifact custody changed')
        q.code_guard(pins)
        q.directory_guard(directories)
        q.no_forbidden_modules()
        report['loaded_product_source_origins'] = q.product_origins(root, pins, finder)
        need(Path.cwd() == root and directory_identity(root, q) == root_identity,
            'source checkout physical identity changed')
        need(tempfile.tempdir == layout['tmp'] and all(os.environ.get(key) == value for key, value in redirects.items()),
            'native writable redirects changed')
        need(arrow.cpu_count() == arrow.io_thread_count() == 1, 'Arrow thread limits changed')
        audit_state.verify_closed()
        need(not any(attempts.values()), 'denied runtime attempt occurred even if suppressed')
        need(not any(name == 'duckdb' or name.startswith('duckdb.') or name == '_duckdb'
            or name.startswith('_duckdb.') for name in sys.modules), 'DuckDB engine definition loaded unexpectedly')
        report['checks'][5]['status'] = 'passed'
        stage = 'native_output_commit'
        companions = dict(schema=SELECTED_SCHEMA, source_version_id=detached['version_id'],
            package_manifest=package['manifest'], historical_dataset_revision=HISTORICAL_REVISION,
            requested_legal_ids=selected_ids, row_fields=['ordinal', *ROW_FIELDS], rows=selected_rows,
            exposure_status='exposed', original_split_membership_preserved=True,
            text_coordinate_space='exact decoded record_json.text; normalization none; distinct from official HTML/USLM',
            gold_mask=0, training_mask=0, **FALSE_FLAGS)
        report['selected_source_artifact'] = save_output(Path(layout['exports']) / 'selected-source-companions.json',
            companions, q, directories, output_budget)
        report.update(status='pass', all_checks_complete=True, guard_attempts=attempts,
            runtime_denial_evidence=audit_state.evidence(),
            elapsed_seconds=time.monotonic() - started, input_fingerprints_and_physical_witnesses_unchanged=True,
            package_physical_witnesses_unchanged=True, source_pins_unchanged=True,
            dependency_versions={'pyarrow': arrow.__version__, 'numpy': getattr(sys.modules.get('numpy'), '__version__', None),
                'huggingface_hub': getattr(sys.modules.get('huggingface_hub'), '__version__', None),
                'requests': getattr(sys.modules.get('requests'), '__version__', None),
                'urllib3': getattr(sys.modules.get('urllib3'), '__version__', None), 'python': sys.version},
            optional_sdk_definition_presence={'huggingface_hub': 'huggingface_hub' in sys.modules,
                'requests': 'requests' in sys.modules},
            database_engine_definition_presence={'duckdb': 'duckdb' in sys.modules, '_duckdb': '_duckdb' in sys.modules},
            hub_sdk_definition_modules_loaded=sorted(name for name in sys.modules
                if name == 'huggingface_hub' or name.startswith('huggingface_hub.')),
            arrow_thread_limits={'cpu': arrow.cpu_count(), 'io': arrow.io_thread_count()},
            limitations=['This verifies retained published source artifacts, not current Hub payloads or official-source authority.',
                'Selected companions are exposed engineering source inputs, not reviewed interpretations or normative gold.',
                'Original dataset revision, split, alias and embedding observations remain historical and unchanged.',
                'Python network/process auditing and readonly fingerprints are cooperative controls, not OS isolation or a filesystem quota.',
                'The actual genuine urllib3 import-only IPv6 loopback capability probe is explicitly admitted and counted; no zero-network-event claim is made.',
                'Only the genuine native parent can establish resource release and durable process closeout.'])
        report_ref = save_output(Path(layout['exports']) / 'source-corpus-reuse.json', report, q, directories, output_budget)
        print(json.dumps({'status': 'pass', 'report': report_ref, 'physical_rows': row_count,
            'selected_physical_rows': len(selected_rows), 'output_bytes': output_budget['bytes']}, sort_keys=True))
        return 0
    except BaseException as error:
        for check in report['checks']:
            if check['name'] == stage and check['status'] != 'passed':
                check['status'] = 'failed'
            elif check['status'] == 'not_run':
                check['blocked_by_failed_stage'] = stage
        report.update(status='failed', all_checks_complete=False, failure_stage=stage,
            error_type=type(error).__name__, arbitrary_exception_values_omitted=True,
            guard_attempts=attempts, elapsed_seconds=time.monotonic() - started)
        if audit_state is not None:
            report['runtime_denial_evidence'] = audit_state.evidence()
        report['product_origin_diagnostics_at_failure'] = q.product_diagnostics(root, pins, finder)
        try:
            q.code_guard(pins)
            report['final_source_pins_unchanged'] = True
        except BaseException:
            report['final_source_pins_unchanged'] = False
        try:
            save_output(Path(layout['logs']) / 'source-corpus-reuse-failed.json', report, q, directories, output_budget)
        except BaseException as report_error:
            try:
                if audit_state is not None:
                    audit_state.failure_fallback(stage, error, report_error)
                sys.stderr.write(json.dumps({'failure_stage': stage, 'original_error_type': type(error).__name__,
                    'failure_report_error_type': type(report_error).__name__, 'all_checks_complete': False}, sort_keys=True) + '\n')
            except BaseException:
                pass  # Never replace the original replay failure with diagnostic failure.
        raise ReplayFailure('retained source corpus replay failed at ' + stage
            + ' (' + type(error).__name__ + ')') from None
    finally:
        if audit_state is not None:
            audit_state.close()


if __name__ == '__main__':
    raise SystemExit(main())
