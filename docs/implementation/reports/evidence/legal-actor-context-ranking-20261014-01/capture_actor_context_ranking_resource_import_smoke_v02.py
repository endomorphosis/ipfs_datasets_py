"""Guarded import-only smoke; requires a separate, actual source-review gate.

Run only after review with: python -I -S -B <this file>.  This script has no
owner, adoption, watchdog, client, sampler, census or admission mode.  The three
native package initializer files are custody pins and never execute.

V02 preserves V01's actual refusal.  It authenticates CPython dataclasses'
definition-only generated module and factory, while still forbidding every
native resource constructor and method body.
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
SELF = ROOT / 'capture_actor_context_ranking_resource_import_smoke_v02.py'
HELPER = ROOT / 'bootstrap_actor_context_ranking_resources_v02.py'
MANIFEST = ROOT / 'resource-source-snapshot-v01.json'
BOOTSTRAP_REVIEW = ROOT / 'resource-bootstrap-source-independent-review-v02.json'
SOURCE_GATE = ROOT / 'resource-bootstrap-smoke-source-independent-review-v02.json'
OUTPUT = ROOT / 'resource-bootstrap-import-smoke-v02.json'
DATACLASSES = Path('/usr/lib/python3.12/dataclasses.py')
PRIOR_SMOKE = ROOT / 'resource-bootstrap-import-smoke-v01.json'
PRIOR_REVIEW = ROOT / 'resource-bootstrap-smoke-source-independent-review-v01.json'
FIXED = {
    HELPER: (6599, 'e1847c2723216b4f2a06ee9da80adfeb8121e94e0b2442da0d2f95e2288d7be1'),
    MANIFEST: (4678, 'fbbbc82c791998e4498a30226cc8f61a17bd7ce46f57229629710631af9761b2'),
    BOOTSTRAP_REVIEW: (25630, '7aa5d74d7e805d122f74c6ac1941736636ad0f9a59409c7777a6d60845c59ebd'),
    DATACLASSES: (61753, '0e449d55d6206b0022f541ba32be88fafc934ff71d9aa65f31f101ca6147f2ae'),
    PRIOR_SMOKE: (8911, '7df903a5325095ef56180a0737f68315d146fdaf97a0288952c635f6eccc0183'),
    PRIOR_REVIEW: (12057, '17c13625a518242da0b8018f46ae2840b3ec19226a49b1df90cde8379a20d2b2'),
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
GENERATED_METHOD_NAMES = frozenset({'__init__', '__repr__', '__eq__', '__hash__',
                                    '__setattr__', '__delattr__'})


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
    require(sys.version_info[:2] == (3, 12) and sys.flags.isolated == 1 and sys.flags.no_site == 1
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
    prior, _ = public_JSON(PRIOR_SMOKE)
    require(prior.get('passed') is False and prior.get('bootstrap_calls') == 1
            and prior.get('source_qualification') == descriptors[str(PRIOR_REVIEW)]
            and prior.get('source_profile_guard_active_at_close') is False,
            'actual_prior_refused_smoke_custody_required')
    gate, gate_pin = public_JSON(SOURCE_GATE)
    _, self_pin = raw_source(SELF)
    require(gate.get('schema') == 'actor-context-ranking-resource-bootstrap-smoke-source-independent-review/v1'
            and gate.get('passed') is True and gate.get('findings') == []
            and gate.get('producer') == self_pin
            and gate.get('bootstrap') == descriptors[str(HELPER)]
            and gate.get('bootstrap_source_review') == descriptors[str(BOOTSTRAP_REVIEW)]
            and gate.get('snapshot_manifest') == descriptors[str(MANIFEST)]
            and gate.get('dataclasses_source') == descriptors[str(DATACLASSES)]
            and gate.get('prior_failed_smoke') == descriptors[str(PRIOR_SMOKE)]
            and gate.get('prior_source_review') == descriptors[str(PRIOR_REVIEW)],
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


def checked_create_fn():
    """Authenticate the loaded stdlib function against its pinned raw source."""
    data, descriptor = raw_source(DATACLASSES)
    require((descriptor['bytes'], descriptor['sha256']) == FIXED[DATACLASSES],
            'dataclasses_raw_source_changed')
    expected_module = compile(data, str(DATACLASSES), 'exec', dont_inherit=True, optimize=0)
    matches = [c for c in expected_module.co_consts
               if isinstance(c, types.CodeType) and c.co_name == '_create_fn']
    require(len(matches) == 1, 'one_pinned_dataclasses_create_fn_required')
    module = sys.modules['dataclasses']
    function = module.__dict__.get('_create_fn')
    require(str(Path(module.__file__).resolve()) == str(DATACLASSES)
            and type(function) is types.FunctionType
            and function.__globals__ is module.__dict__
            and function.__code__ == matches[0]
            and function.__code__.co_filename == str(DATACLASSES)
            and function.__code__.co_flags == 3,
            'loaded_dataclasses_create_fn_must_equal_pinned_code')
    return module.__dict__, matches[0]


def definition_only_dataclass_text(text, method, local_names):
    """Validate only executed definition scaffolding, never allow method bodies."""
    require(type(text) is str and len(text) <= 131072
            and method in GENERATED_METHOD_NAMES and len(local_names) <= 512
            and all(type(n) is str and n.isidentifier() for n in local_names),
            'bounded_dataclass_definition_inputs_required')
    syntax = ast.parse(text, filename='<string>', mode='exec')
    require(len(syntax.body) == 1 and type(syntax.body[0]) is ast.FunctionDef,
            'one_generated_factory_definition_required')
    outer = syntax.body[0]
    require(outer.name == '__create_fn__' and not outer.decorator_list
            and outer.returns is None and outer.type_comment is None
            and not outer.type_params and len(outer.body) == 2,
            'definition_only_outer_factory_required')
    args = outer.args
    require(not args.posonlyargs and not args.kwonlyargs and not args.defaults
            and not args.kw_defaults and args.vararg is None and args.kwarg is None
            and [a.arg for a in args.args] == local_names
            and all(a.annotation is None and a.type_comment is None for a in args.args),
            'factory_arguments_must_be_plain_caller_local_names')
    inner, returned = outer.body
    require(type(inner) is ast.FunctionDef and inner.name == method
            and not inner.decorator_list and inner.type_comment is None
            and not inner.type_params and type(returned) is ast.Return
            and type(returned.value) is ast.Name and returned.value.id == method,
            'factory_must_only_define_and_return_native_method')
    # Definitions evaluate defaults/annotations, but not the method body.
    # Only plain names/constants are needed by the six pinned dataclass methods.
    values = list(inner.args.defaults) + [v for v in inner.args.kw_defaults if v is not None]
    values += [a.annotation for a in (inner.args.posonlyargs + inner.args.args + inner.args.kwonlyargs)
               if a.annotation is not None]
    if inner.args.vararg is not None and inner.args.vararg.annotation is not None:
        values.append(inner.args.vararg.annotation)
    if inner.args.kwarg is not None and inner.args.kwarg.annotation is not None:
        values.append(inner.args.kwarg.annotation)
    if inner.returns is not None:
        values.append(inner.returns)
    require(all(type(v) in (ast.Name, ast.Constant) for v in values),
            'generated_signature_may_not_execute_expressions')
    code = compile(text, '<string>', 'exec', dont_inherit=True, optimize=0)
    factories = [c for c in code.co_consts if isinstance(c, types.CodeType)]
    require(len(factories) == 1 and factories[0].co_name == '__create_fn__',
            'one_exact_compiled_factory_required')
    methods = [c for c in factories[0].co_consts if isinstance(c, types.CodeType)]
    require(len(methods) == 1 and methods[0].co_name == method,
            'one_unexecuted_compiled_native_method_required')
    return code, factories[0], methods[0]


class Guard(importlib.abc.MetaPathFinder):
    def __init__(self, descriptors, allowed, classes, resource_paths):
        self.readable = set(descriptors)
        self.allowed = allowed
        self.classes = classes
        self.resource_paths = resource_paths
        self.stdlib = Path(sysconfig.get_path('stdlib')).resolve()
        self.dataclasses = str(Path(sys.modules['dataclasses'].__file__).resolve())
        self.dataclasses_globals, self.create_fn_code = checked_create_fn()
        self.zip_paths = {str(Path(p).resolve()) for p in sys.path if p.endswith('.zip')}
        self.phase = 'guarded_import'
        self.receipt_fd = None
        self.receipt_creations = 0
        self.bootstrap_calls = 0
        self.resource_module_calls = {}
        self.resource_class_calls = {}
        self.dataclass_function_factories = 0
        self.dataclass_definition_modules = 0
        self.dataclass_methods_defined = 0
        self.pending_dataclass_definitions = {}
        self.dataclass_definition_proofs = []
        self.refused_frames = []
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

    def dataclass_definition_frame(self, frame, event, returned):
        """Allow only exact _create_fn definition scaffolding, never its method."""
        code = frame.f_code
        if code.co_filename != '<string>' or code.co_name not in ('<module>', '__create_fn__'):
            return False
        caller = frame.f_back
        require(caller is not None and caller.f_code == self.create_fn_code
                and caller.f_code.co_filename == self.dataclasses
                and caller.f_globals is self.dataclasses_globals
                and type(self.dataclasses_globals.get('_create_fn')) is types.FunctionType
                and self.dataclasses_globals['_create_fn'].__code__ == self.create_fn_code,
                'generated_definition_requires_authenticated_stdlib_caller')
        values = caller.f_locals
        module = frame.f_globals.get('__name__')
        require(module in MODULES and frame.f_globals is sys.modules[module].__dict__
                and values.get('globals') is frame.f_globals
                and type(values.get('locals')) is dict and type(values.get('ns')) is dict,
                'generated_definition_resource_namespace_mismatch')
        key = id(caller)
        if code.co_name == '<module>' and event == 'call':
            require(key not in self.pending_dataclass_definitions
                    and values['ns'] is frame.f_locals and not values['ns'],
                    'fresh_definition_only_exec_namespace_required')
            text, method = values.get('txt'), values.get('name')
            expected, factory, native_method = definition_only_dataclass_text(
                text, method, list(values['locals']))
            require(code == expected, 'generated_module_must_equal_exact_caller_text')
            self.pending_dataclass_definitions[key] = dict(
                module=module, method=method, module_code=expected,
                factory_code=factory, method_code=native_method,
                text_sha256=hashlib.sha256(text.encode()).hexdigest())
            self.dataclass_definition_modules += 1
            return True
        proof = self.pending_dataclass_definitions.get(key)
        require(type(proof) is dict and proof['module'] == module
                and type(values.get('txt')) is str
                and hashlib.sha256(values['txt'].encode()).hexdigest() == proof['text_sha256'],
                'existing_exact_generated_definition_required')
        factory = values['ns'].get('__create_fn__')
        require(set(values['ns']) == {'__create_fn__'} and type(factory) is types.FunctionType
                and factory.__globals__ is frame.f_globals
                and factory.__code__ == proof['factory_code'],
                'generated_namespace_must_only_hold_exact_factory')
        if code.co_name == '<module>':
            require(event == 'return' and code == proof['module_code']
                    and values['ns'] is frame.f_locals,
                    'exact_definition_only_module_return_required')
        else:
            require(code == proof['factory_code'], 'exact_registered_factory_code_required')
            if event == 'call':
                self.dataclass_function_factories += 1
            else:
                require(type(returned) is types.FunctionType
                        and returned.__name__ == proof['method']
                        and returned.__globals__ is frame.f_globals
                        and returned.__code__ == proof['method_code'],
                        'factory_must_return_unexecuted_exact_native_method')
                require(len(self.dataclass_definition_proofs) < 512,
                        'bounded_generated_definition_proofs_required')
                self.dataclass_definition_proofs.append(dict(
                    module=module, method=proof['method'],
                    generated_text_sha256=proof['text_sha256']))
                self.dataclass_methods_defined += 1
                del self.pending_dataclass_definitions[key]
        return True

    def remember_refused_frame(self, frame):
        if len(self.refused_frames) >= 4:
            return
        def public_name(value):
            return value if (type(value) is str and len(value) <= 160
                             and all(c.isalnum() or c in '._<>' for c in value)) else 'other'
        caller = frame.f_back
        kind = lambda path: ('qualified_resource_source' if path in self.resource_paths else
                             'stdlib_dataclass_generated' if path == '<string>' else 'other')
        self.refused_frames.append(dict(
            event_code_name=public_name(frame.f_code.co_name),
            filename_kind=kind(frame.f_code.co_filename),
            module=frame.f_globals.get('__name__') if frame.f_globals.get('__name__') in MODULES else 'other',
            code_first_line=frame.f_code.co_firstlineno,
            code_bytecode_sha256=hashlib.sha256(frame.f_code.co_code).hexdigest(),
            caller_code_name=public_name(caller.f_code.co_name) if caller is not None else 'none',
            caller_filename_kind=('pinned_stdlib_dataclasses' if caller is not None
                                  and caller.f_code.co_filename == self.dataclasses else 'other')))

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
        try:
            if self.dataclass_definition_frame(frame, event, arg):
                return
        except Exception:
            self.remember_refused_frame(frame)
            raise
        self.remember_refused_frame(frame)
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
    require(not guard.pending_dataclass_definitions
            and guard.dataclass_definition_modules == guard.dataclass_function_factories
            == guard.dataclass_methods_defined > 0,
            'complete_definition_factory_return_accounting_required')
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
        stdlib_dataclass_definition_modules=guard.dataclass_definition_modules,
        stdlib_dataclass_methods_defined_not_called=guard.dataclass_methods_defined,
        stdlib_dataclass_definition_proofs=guard.dataclass_definition_proofs,
        refused_resource_frames=guard.refused_frames,
        prior_failed_smoke=descriptors[str(PRIOR_SMOKE)],
        prior_source_review=descriptors[str(PRIOR_REVIEW)],
        pinned_dataclasses_source=descriptors[str(DATACLASSES)],
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
