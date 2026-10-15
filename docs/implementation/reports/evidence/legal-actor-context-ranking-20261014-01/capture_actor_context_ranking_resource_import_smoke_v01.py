"""Guarded import-only smoke; requires a separate, actual source-review gate.

Run only after review with: python -I -S -B <this file>.  This script has no
owner, adoption, watchdog, client, sampler, census or admission mode.  The three
native package initializer files are custody pins and never execute.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import stat
import sys
import sysconfig
import types


ROOT = Path(__file__).resolve().parent
SELF = ROOT / 'capture_actor_context_ranking_resource_import_smoke_v01.py'
HELPER = ROOT / 'bootstrap_actor_context_ranking_resources_v02.py'
MANIFEST = ROOT / 'resource-source-snapshot-v01.json'
BOOTSTRAP_REVIEW = ROOT / 'resource-bootstrap-source-independent-review-v02.json'
SOURCE_GATE = ROOT / 'resource-bootstrap-smoke-source-independent-review-v01.json'
OUTPUT = ROOT / 'resource-bootstrap-import-smoke-v01.json'
FIXED = {
    HELPER: (6599, 'e1847c2723216b4f2a06ee9da80adfeb8121e94e0b2442da0d2f95e2288d7be1'),
    MANIFEST: (4678, 'fbbbc82c791998e4498a30226cc8f61a17bd7ce46f57229629710631af9761b2'),
    BOOTSTRAP_REVIEW: (25630, '7aa5d74d7e805d122f74c6ac1941736636ad0f9a59409c7777a6d60845c59ebd'),
}
PACKAGES = ('ipfs_datasets_py', 'ipfs_datasets_py.optimizers',
            'ipfs_datasets_py.optimizers.logic_theorem_optimizer')
PREFIX = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/'
MODULES = {PACKAGES[-1] + '.' + name: PREFIX + name + '.py'
           for name in ('runtime_telemetry', 'proof_resource_safety', 'resource_scheduler')}
BANNED_ROOTS = frozenset({
    'torch', 'numpy', 'scipy', 'pandas', 'sklearn', 'jax', 'jaxlib', 'tensorflow',
    'keras', 'transformers', 'sentence_transformers', 'huggingface_hub',
    'datasets', 'accelerate', 'safetensors', 'onnx', 'onnxruntime', 'cupy',
    'numba', 'triton', 'requests', 'httpx', 'aiohttp', 'boto3', 'botocore',
})
PRELOAD_STDLIB = (
    'contextlib', 'copy', 'dataclasses', 'enum', 'fcntl', 'threading', 'time',
    'tempfile', 'uuid', 'collections', 'collections.abc', 'datetime', 'typing',
    'subprocess', 'shutil', 'math',
)


class SmokeRefusal(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise SmokeRefusal(code)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_public_JSON_key')
        result[key] = value
    return result


def reject_constant(_):
    raise SmokeRefusal('nonfinite_public_JSON_constant')


def raw_source(path):
    path = Path(path)
    before = path.lstat()
    require(path.resolve(strict=True) == path and stat.S_ISREG(before.st_mode)
            and not path.is_symlink(), 'physical_public_source_required')
    data = path.read_bytes()
    after = path.lstat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(before) == identity(after), 'public_source_changed_during_read')
    descriptor = dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return data, descriptor


def public_JSON(path):
    data, descriptor = raw_source(path)
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant), descriptor


def require_descriptor(descriptor):
    require(type(descriptor) is dict and set(descriptor) == {'path', 'bytes', 'sha256'},
            'full_public_descriptor_required')
    require(type(descriptor['path']) is str and type(descriptor['bytes']) is int
            and descriptor['bytes'] >= 0 and type(descriptor['sha256']) is str,
            'typed_public_descriptor_required')
    data, actual = raw_source(Path(descriptor['path']))
    require(actual == descriptor, 'public_descriptor_changed')
    return data


def input_closure():
    require(sys.flags.isolated == 1 and sys.flags.no_site == 1
            and sys.dont_write_bytecode and sys.flags.optimize == 0,
            'fresh_python_I_S_B_without_optimization_required')
    require(Path(__file__).resolve() == SELF, 'fixed_smoke_source_path_required')
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), 'exclusive_smoke_receipt_required')
    require(not any(n == PACKAGES[0] or n.startswith(PACKAGES[0] + '.') for n in sys.modules),
            'fresh_resource_namespace_required')
    require(not any(n.split('.')[0] in BANNED_ROOTS for n in sys.modules),
            'preloaded_numerical_or_SDK_module_refused')
    require(all(n.split('.')[0] in sys.stdlib_module_names
                or n.split('.')[0] in sys.builtin_module_names or n == '__main__'
                for n in sys.modules), 'preloaded_nonstdlib_namespace_refused')
    descriptors = {}
    for path, expected in FIXED.items():
        _, descriptor = raw_source(path)
        require((descriptor['bytes'], descriptor['sha256']) == expected, 'fixed_smoke_input_changed')
        descriptors[str(path)] = descriptor
    manifest, _ = public_JSON(MANIFEST)
    require(manifest.get('schema') == 'actor-context-ranking-resource-source-snapshot/v1'
            and manifest.get('file_count') == 6 and type(manifest.get('files')) is dict
            and len(manifest['files']) == 6, 'closed_six_file_manifest_required')
    expected = {name.replace('.', '/') + '/__init__.py' for name in PACKAGES} | set(MODULES.values())
    require(set(manifest['files']) == expected, 'manifest_roster_changed')
    for relative, row in manifest['files'].items():
        require(type(row) is dict and set(row) == {'origin', 'snapshot', 'initializer_custody_only'},
                'closed_manifest_row_required')
        require(row['initializer_custody_only'] is relative.endswith('/__init__.py'),
                'initializer_custody_label_changed')
        require(row['origin']['path'] == str(ROOT / 'datasets' / relative)
                and row['snapshot']['path'] == str(ROOT / 'resource-source-v01' / relative),
                'fixed_manifest_source_paths_required')
        for kind in ('origin', 'snapshot'):
            require_descriptor(row[kind])
            descriptors[row[kind]['path']] = row[kind]
        require(row['origin']['bytes'] == row['snapshot']['bytes']
                and row['origin']['sha256'] == row['snapshot']['sha256'], 'snapshot_origin_mismatch')
    bootstrap_review, _ = public_JSON(BOOTSTRAP_REVIEW)
    require(bootstrap_review.get('passed') is True and bootstrap_review.get('findings') == []
            and bootstrap_review.get('bootstrap') == descriptors[str(HELPER)]
            and bootstrap_review.get('snapshot_manifest') == descriptors[str(MANIFEST)],
            'actual_clean_bootstrap_source_review_required')
    gate, gate_pin = public_JSON(SOURCE_GATE)
    _, self_pin = raw_source(SELF)
    require(gate.get('schema') == 'actor-context-ranking-resource-bootstrap-smoke-source-independent-review/v1'
            and gate.get('passed') is True and gate.get('findings') == []
            and gate.get('producer') == self_pin
            and gate.get('bootstrap') == descriptors[str(HELPER)]
            and gate.get('bootstrap_source_review') == descriptors[str(BOOTSTRAP_REVIEW)]
            and gate.get('snapshot_manifest') == descriptors[str(MANIFEST)],
            'actual_independent_smoke_source_gate_required')
    descriptors[str(SELF)] = self_pin
    require(type(gate.get('artifacts')) is dict
            and all(gate['artifacts'].get(p) == d for p, d in descriptors.items()),
            'complete_smoke_source_gate_artifact_map_required')
    descriptors[str(SOURCE_GATE)] = gate_pin
    return manifest, descriptors


def allowed_resource_codes(manifest):
    """Compile for code comparison only; execute no resource statements here."""
    allowed = {}
    classes = {}
    all_paths = {row['snapshot']['path'] for row in manifest['files'].values()}
    for name, relative in MODULES.items():
        path = Path(manifest['files'][relative]['snapshot']['path'])
        data = require_descriptor(manifest['files'][relative]['snapshot'])
        syntax = ast.parse(data, filename=str(path))
        names = {n.name for n in syntax.body if isinstance(n, ast.ClassDef)}
        code = compile(data, str(path), 'exec', dont_inherit=True, optimize=0)
        allowed[code] = ('module', name)
        for child in code.co_consts:
            if isinstance(child, types.CodeType) and child.co_name in names and not child.co_flags & 2:
                allowed[child] = ('class', name)
                classes[child] = child.co_name
        require(len([c for c in classes if c.co_filename == str(path)]) == len(names),
                'exact_resource_class_body_roster_required')
    return allowed, classes, all_paths


class Guard(importlib.abc.MetaPathFinder):
    def __init__(self, descriptors, allowed, classes, resource_paths):
        self.readable = set(descriptors)
        self.allowed = allowed
        self.classes = classes
        self.resource_paths = resource_paths
        self.stdlib = Path(sysconfig.get_path('stdlib')).resolve()
        self.dataclasses = str(Path(sys.modules['dataclasses'].__file__).resolve())
        self.zip_paths = {str(Path(p).resolve()) for p in sys.path if p.endswith('.zip')}
        self.phase = 'guarded_import'
        self.receipt_fd = None
        self.receipt_creations = 0
        self.bootstrap_calls = 0
        self.resource_module_calls = {}
        self.resource_class_calls = {}
        self.dataclass_function_factories = 0
        self.forbidden_events = []
        self.initial_sys_path = list(sys.path)
        self.audit_probes = 0

    def refuse(self, code):
        self.forbidden_events.append(code)
        raise SmokeRefusal(code)

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split('.')[0]
        if root in BANNED_ROOTS:
            self.refuse('numerical_or_SDK_import_refused')
        if root == PACKAGES[0]:
            if fullname not in MODULES:
                self.refuse('unknown_resource_namespace_import_refused')
        elif root not in sys.stdlib_module_names and root not in sys.builtin_module_names:
            self.refuse('nonstdlib_import_refused')
        return None

    def audit(self, event, args):
        if event == 'actor_context_ranking_resource_smoke.guard_probe':
            self.audit_probes += 1
        if event == 'import':
            self.find_spec(args[0])
        if event == 'open':
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if isinstance(path, int):
                if not (self.phase == 'receipt' and path == self.receipt_fd and writing):
                    self.refuse('unqualified_descriptor_open_refused')
                return
            if not isinstance(path, (str, bytes, os.PathLike)):
                self.refuse('nonphysical_open_refused')
            decoded = os.fsdecode(path)
            if not os.path.isabs(decoded):
                self.refuse('relative_file_or_endpoint_open_refused')
            lexical = os.path.normpath(decoded)
            if writing:
                required = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if not (self.phase == 'receipt' and lexical == str(OUTPUT)
                        and self.receipt_creations == 0 and isinstance(flags, int)
                        and flags & required == required):
                    self.refuse('filesystem_write_refused')
                self.receipt_creations += 1
            else:
                def permitted(candidate):
                    return (candidate in self.readable or candidate in self.zip_paths
                            or self.stdlib == Path(candidate) or self.stdlib in Path(candidate).parents
                            or self.phase == 'receipt' and candidate in (str(OUTPUT), str(ROOT)))
                # Reject unknown/proc/sys/private paths before resolving or
                # inspecting their endpoint metadata, then fence symlink targets.
                if not permitted(lexical):
                    self.refuse('unqualified_file_or_endpoint_read_refused')
                if not permitted(str(Path(lexical).resolve())):
                    self.refuse('unqualified_file_or_endpoint_target_refused')
        if event in {'os.listdir', 'os.scandir'}:
            self.refuse('directory_census_refused')
        if (event.startswith(('socket.', 'subprocess.', 'pty.', 'ctypes.'))
                or event in {'os.system', 'os.fork', 'os.forkpty', 'os.posix_spawn',
                             'os.exec', 'os.spawn', 'os.startfile'}):
            self.refuse('network_or_process_action_refused')
        mutations = {'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown',
                     'os.link', 'os.symlink', 'os.truncate', 'os.utime', 'os.chdir',
                     'os.putenv', 'os.unsetenv', 'shutil.copyfile', 'shutil.copymode', 'shutil.copystat'}
        if event in mutations:
            if not (event == 'os.chmod' and self.phase == 'receipt'
                    and args[0] == self.receipt_fd and args[1] == 0o444):
                self.refuse('filesystem_or_environment_mutation_refused')

    def profile(self, frame, event, arg):
        if event not in ('call', 'return'):
            return
        code = frame.f_code
        filename = code.co_filename
        module = frame.f_globals.get('__name__')
        if event == 'call' and filename == str(HELPER) and code.co_name == 'bootstrap':
            self.bootstrap_calls += 1
            require(self.bootstrap_calls == 1, 'bootstrap_must_be_called_exactly_once')
        if filename not in self.resource_paths and module not in MODULES:
            return
        if code in self.allowed:
            kind, expected_module = self.allowed[code]
            if module != expected_module:
                self.refuse('resource_frame_module_identity_changed')
            if event == 'call':
                counts = self.resource_module_calls if kind == 'module' else self.resource_class_calls
                key = expected_module if kind == 'module' else expected_module + '.' + self.classes[code]
                counts[key] = counts.get(key, 0) + 1
                if counts[key] != 1:
                    self.refuse('resource_module_or_class_body_reexecuted')
            elif kind == 'class':
                if not (frame.f_locals.get('__module__') == expected_module
                        and frame.f_locals.get('__qualname__') == self.classes[code]):
                    self.refuse('resource_class_body_identity_changed')
            return
        # dataclasses._create_fn calls its generated function-definition factory.
        # It creates methods but does not call a native dataclass __init__.
        caller = frame.f_back
        if (filename == '<string>' and code.co_name == '__create_fn__'
                and caller is not None and caller.f_code.co_name == '_create_fn'
                and str(Path(caller.f_code.co_filename).resolve()) == self.dataclasses):
            if event == 'call':
                self.dataclass_function_factories += 1
            return
        self.refuse('resource_function_method_constructor_or_sampler_call_refused')


def source_fences(descriptors):
    for descriptor in descriptors.values():
        require_descriptor(descriptor)


def capture(manifest, descriptors, guard):
    source_fences(descriptors)
    data = require_descriptor(descriptors[str(HELPER)])
    name = 'actor_context_ranking_resource_smoke_helper'
    require(name not in sys.modules, 'fresh_helper_namespace_required')
    helper = types.ModuleType(name)
    helper.__file__ = str(HELPER)
    helper.__package__ = ''
    helper.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(HELPER))
    sys.modules[name] = helper
    exec(compile(data, str(HELPER), 'exec', dont_inherit=True, optimize=0), helper.__dict__)
    package, scheduler, report = helper.bootstrap()
    require(guard.bootstrap_calls == 1, 'one_actual_bootstrap_call_required')
    expected_names = set(PACKAGES) | set(MODULES)
    actual_names = {n for n in sys.modules if n == PACKAGES[0] or n.startswith(PACKAGES[0] + '.')}
    require(actual_names == expected_names, 'exact_six_resource_namespace_members_required')
    require(type(package) is types.ModuleType and package is sys.modules[PACKAGES[-1]]
            and type(scheduler) is types.ModuleType
            and scheduler is sys.modules[PACKAGES[-1] + '.resource_scheduler'], 'returned_module_identity_changed')
    namespace = {}
    for name in PACKAGES:
        module = sys.modules[name]
        origin = ROOT / 'resource-source-v01' / (name.replace('.', '/') + '/__init__.py')
        require(module.__dict__.get('__resource_namespace_shell__') is True
                and module.__dict__.get('__file__') == str(origin)
                and module.__dict__.get('__package__') == name
                and module.__dict__.get('__path__') == [str(origin.parent)]
                and module.__spec__.origin == 'explicit-inert-resource-namespace-shell'
                and module.__spec__.loader is None
                and module.__spec__.submodule_search_locations == [str(origin.parent)],
                'inert_package_shell_changed')
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            require(sys.modules[parent].__dict__.get(child) is module, 'package_parent_link_changed')
        namespace[name] = dict(kind='custody_only_namespace_shell', file=str(origin))
    for name, relative in MODULES.items():
        module = sys.modules[name]
        origin = ROOT / 'resource-source-v01' / relative
        require(module.__dict__.get('__file__') == str(origin)
                and module.__dict__.get('__package__') == name.rpartition('.')[0]
                and module.__spec__.origin == str(origin)
                and type(module.__spec__.loader) is helper.CheckedSourceLoader
                and module.__dict__.get('__loader__') is module.__spec__.loader,
                'exact_resource_module_origin_required')
        namespace[name] = dict(kind='executed_exact_native_source', file=str(origin))
    expected_report = dict(schema='actor-context-ranking-resource-namespace-bootstrap/v1',
        package_initializers_executed=False, package_initializer_files_custody_pinned=3,
        native_package_init_equivalence_claimed=False, router_deps_imported=False,
        exact_source_bytes_compiled_directly=True, bytecode_cache_reads_by_resource_loader=False,
        canonical_inert_package_shell_count=3, executed_unchanged_resource_source_count=3,
        resource_source_root=str(ROOT / 'resource-source-v01'), sys_path_source_root_added=False,
        model_calls=0, scheduler_client_constructed=False, shared_state_read_by_bootstrap=False)
    require(type(report) is dict and report == expected_report
            and all(type(report[k]) is type(v) for k, v in expected_report.items()),
            'exact_bootstrap_report_required')
    require(set(guard.resource_module_calls) == set(MODULES)
            and all(n == 1 for n in guard.resource_module_calls.values()), 'three_actual_module_frames_required')
    require(len(guard.resource_class_calls) == len(guard.classes)
            and all(n == 1 for n in guard.resource_class_calls.values()), 'all_native_class_definition_frames_required')
    require(not any(n.split('.')[0] in BANNED_ROOTS for n in sys.modules), 'numerical_or_SDK_namespace_loaded')
    require('ipfs_datasets_py.router_deps' not in sys.modules and not guard.forbidden_events,
            'forbidden_import_or_resource_event_observed')
    require(sys.path == guard.initial_sys_path and guard in sys.meta_path,
            'source_path_or_import_guard_changed')
    source_fences(descriptors)
    return report, namespace


def write_receipt(result, guard):
    raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    guard.phase = 'receipt'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(OUTPUT, flags, 0o444)
    guard.receipt_fd = fd
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
        os.fchmod(fd, 0o444)
        os.fsync(fd)
        require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o444, 'frozen_smoke_receipt_required')
    finally:
        os.close(fd)
        guard.receipt_fd = None
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    actual, descriptor = raw_source(OUTPUT)
    require(actual == raw, 'smoke_receipt_readback_changed')
    print(json.dumps(dict(passed=result['passed'], receipt=descriptor), sort_keys=True))


def main():
    manifest, descriptors = input_closure()
    # Only stdlib is preloaded; these imports execute no resource source.
    for name in PRELOAD_STDLIB:
        importlib.import_module(name)
    require(not any(n.split('.')[0] in BANNED_ROOTS for n in sys.modules), 'stdlib_preload_crossed_boundary')
    allowed, classes, paths = allowed_resource_codes(manifest)
    guard = Guard(descriptors, allowed, classes, paths)
    sys.meta_path.insert(0, guard)
    sys.addaudithook(guard.audit)
    profiler = guard.profile
    sys.setprofile(profiler)
    report = namespace = None
    findings = []
    exception_class = None
    try:
        sys.audit('actor_context_ranking_resource_smoke.guard_probe')
        require(guard.audit_probes == 1, 'audit_guard_not_installed')
        report, namespace = capture(manifest, descriptors, guard)
        sys.audit('actor_context_ranking_resource_smoke.guard_probe')
        require(guard.audit_probes == 2, 'audit_guard_not_active_at_close')
    except Exception as error:
        exception_class = type(error).__name__
        findings.append(error.code if isinstance(error, SmokeRefusal) else 'unexpected_guarded_import_exception')
    profile_still_active = sys.getprofile() is profiler
    if not profile_still_active:
        findings.append('source_profile_guard_no_longer_active')
    passed = not findings and not guard.forbidden_events
    result = dict(schema='actor-context-ranking-resource-bootstrap-import-smoke/v1',
        passed=passed, findings=findings,
        scope='Guarded import-only; no native client, endpoint, capacity or admission qualification.',
        exception_class=exception_class, bootstrap_report=report, resource_namespace=namespace,
        bootstrap_calls=guard.bootstrap_calls, resource_module_frames=guard.resource_module_calls,
        resource_class_definition_frames=guard.resource_class_calls,
        stdlib_dataclass_method_definition_factories=guard.dataclass_function_factories,
        source_profile_guard_active_at_close=profile_still_active,
        audit_guard_probes=guard.audit_probes,
        forbidden_events=list(guard.forbidden_events), package_initializers_executed=False,
        initializers_custody_only=3, native_package_init_equivalence_claimed=False,
        source_fences_before_and_after_passed=not findings, owner_adoption_watchdog_imports=0,
        resource_constructor_method_sampler_calls=0 if passed else None,
        scheduler_or_ledger_body_reads=0 if passed else None,
        census_calls=0 if passed else None, resource_API_calls=0 if passed else None,
        model_calls=0 if passed else None, numerical_or_SDK_imports=0 if passed else None,
        network_or_subprocess_calls=0 if passed else None,
        source_qualification=descriptors[str(SOURCE_GATE)],
        artifacts=descriptors)
    write_receipt(result, guard)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
