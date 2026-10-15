"""Fresh reasoning imports preserve public objects without optional runtimes."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


# Frozen from the original literal __all__ in commit
# 9ff4d29ea36d5a495d7f9f321fb1d9def73aa98e, before the lazy-import repair.
# Original reasoning/__init__.py: 40,876 bytes, SHA256
# 83380d7c173252bfec336a913a928a277ebee40d55d0e18d9f34c6ab3c8325ea.
# Hash recipe: UTF8 json.dumps(names, ensure_ascii=False, separators=(",", ":")).
ORIGINAL_EXPORT_COUNT = 553
ORIGINAL_ORDERED_EXPORT_SHA256 = (
    "a44ecf830d0e118dda180866b6f4e95e8acdbfd620f7d4ff0e3725f883dee54d"
)


PROGRAM = r"""
import builtins
import hashlib
import importlib
import json
import os
import subprocess
import sys
import types

package = 'ipfs_datasets_py.logic.integration.reasoning'
mode = sys.argv[1]
expected_count = int(sys.argv[2])
expected_digest = sys.argv[3]
forbidden_prefixes = ('symai', 'torch', 'transformers', 'tensorflow')
assert not any(
    name == prefix or name.startswith(prefix + '.')
    for name in sys.modules for prefix in forbidden_prefixes
), 'optional runtime loaded before the guarded import'
assert package not in sys.modules, 'reasoning must start cold'
optional_attempts, process_attempts, mutation_attempts = [], [], []
original_import = builtins.__import__

def forbidden_name(name):
    return any(name == prefix or name.startswith(prefix + '.')
               for prefix in forbidden_prefixes)

def guarded_import(name, *args, **kwargs):
    if forbidden_name(name):
        optional_attempts.append(name)
        raise AssertionError('optional runtime import during reasoning replay: ' + name)
    return original_import(name, *args, **kwargs)

class OptionalImportGuard:
    def find_spec(self, fullname, path=None, target=None):
        if forbidden_name(fullname):
            optional_attempts.append(fullname)
            raise AssertionError('optional importlib lookup during reasoning replay: ' + fullname)
        return None

def forbidden_process(*args, **kwargs):
    process_attempts.append('Popen')
    raise AssertionError('reasoning import must not launch a process')

write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
mutation_events = {
    'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.symlink',
    'os.link', 'os.truncate', 'os.chmod', 'os.utime',
}

def audit(event, args):
    if event == 'open':
        _, access_mode, flags = args
        if ((isinstance(access_mode, str) and any(c in access_mode for c in 'wax+'))
                or (isinstance(flags, int) and flags & write_flags)):
            mutation_attempts.append(event)
            raise AssertionError('reasoning import must not write configuration or cache files')
    elif event in mutation_events:
        mutation_attempts.append(event)
        raise AssertionError('reasoning import must not mutate the filesystem: ' + event)
    elif event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
        process_attempts.append(event)
        raise AssertionError('reasoning import must not start a process: ' + event)

builtins.__import__ = guarded_import
sys.meta_path.insert(0, OptionalImportGuard())
subprocess.Popen = forbidden_process
sys.dont_write_bytecode = True
sys.addaudithook(audit)

if mode == 'package':
    reasoning = importlib.import_module(package)
    assert not any(name.startswith(package + '.') for name in sys.modules)
    before = set(sys.modules)
    visible = dir(reasoning)
    assert set(reasoning.__all__) <= set(visible)
    assert set(sys.modules) == before, 'dir must not import public owners'
    try:
        getattr(reasoning, 'not_a_reasoning_export_for_this_regression')
    except AttributeError:
        pass
    else:
        raise AssertionError('unknown reasoning names must raise AttributeError')
    assert set(sys.modules) == before, 'unknown names must not import owners'
elif mode == 'symbols':
    leaf = importlib.import_module(package + '.legal_ir_symbols')
    reasoning = importlib.import_module(package)
    from ipfs_datasets_py.logic.integration.reasoning import (
        LegalIRSymbolTableBuilder, LegalIRSymbolKind,
        normalize_legal_symbol_name, resolve_legal_ir_symbol,
    )
    assert LegalIRSymbolTableBuilder is leaf.LegalIRSymbolTableBuilder
    assert LegalIRSymbolKind is leaf.LegalIRSymbolKind
    assert normalize_legal_symbol_name is leaf.normalize_legal_symbol_name
    assert resolve_legal_ir_symbol is leaf.resolve_legal_ir_symbol
    assert normalize_legal_symbol_name(' Agency  NAME ') == 'agency name'
    builder = LegalIRSymbolTableBuilder(symbol_table_id='cold-authored-symbols')
    scope = builder.add_document_scope('authored:doc')
    definition = builder.add_definition(
        'Agency', LegalIRSymbolKind.DEFINED_TERM,
        symbol_id='authored:agency', scope_id=scope.scope_id,
        document_id='authored:doc',
    )
    builder.add_reference(
        'agency', LegalIRSymbolKind.DEFINED_TERM,
        reference_id='authored:reference', scope_id=scope.scope_id,
        document_id='authored:doc',
    )
    table = builder.to_symbol_table()
    assert table.resolved and len(table.resolutions) == 1
    assert table.resolutions[0].symbol_ids == (definition.symbol_id,)
    assert {name for name in sys.modules if name.startswith(package + '.')} <= {
        package + '.legal_ir_symbols', package + '.legal_ir_source_maps',
    }
elif mode == 'source_maps':
    leaf = importlib.import_module(package + '.legal_ir_source_maps')
    reasoning = importlib.import_module(package)
    from ipfs_datasets_py.logic.integration.reasoning import (
        LegalIRSourceMapBuilder, LegalIRTokenSpan,
        build_legal_ir_source_map, trace_legal_ir_fact,
    )
    assert LegalIRSourceMapBuilder is leaf.LegalIRSourceMapBuilder
    assert LegalIRTokenSpan is leaf.LegalIRTokenSpan
    assert build_legal_ir_source_map is leaf.build_legal_ir_source_map
    assert trace_legal_ir_fact is leaf.trace_legal_ir_fact
    assert LegalIRTokenSpan(1, 3).to_dict() == {'start_token': 1, 'end_token': 3}
    builder = LegalIRSourceMapBuilder(source_map_id='cold-authored-source-map')
    source = builder.add_source_document('authored:doc', 'Agency keeps records.')
    assert source.normalized_text == 'Agency keeps records.'
    assert type(builder.to_source_map()) is leaf.LegalIRSourceMap
    assert {name for name in sys.modules if name.startswith(package + '.')} == {
        package + '.legal_ir_source_maps',
    }
elif mode.startswith('early_override:'):
    _, function_name, kind = mode.split(':')
    routes = {
        'legal_ir_view_contracts': 'LegalIRViewContract',
        'legal_ir_semantic_diff': 'LegalIRSemanticDiffEngine',
        'legal_ir_rule_distillation': 'LegalIRRuleDistillationConfig',
        'legal_ir_build_manifest': 'LegalIRBuildManifest',
    }
    reasoning = importlib.import_module(package)
    assert package + '.' + function_name not in sys.modules
    if kind == 'sentinel':
        override = object()
    elif kind == 'callable':
        override = lambda: 'authored caller replacement'
    elif kind == 'none':
        override = None
    else:
        assert kind == 'module'
        override = types.ModuleType(package + '.' + function_name)
    setattr(reasoning, function_name, override)
    public_type = getattr(reasoning, routes[function_name])
    leaf = importlib.import_module(package + '.' + function_name)
    assert public_type is getattr(leaf, routes[function_name])
    assert getattr(reasoning, function_name) is override
    assert vars(reasoning)[function_name] is override
    public_type = reasoning.LegalIRInteropEnvelope
    interop = importlib.import_module(package + '.legal_ir_interop')
    assert public_type is interop.LegalIRInteropEnvelope
    assert getattr(reasoning, function_name) is override
elif mode in {'direct_owner_first', 'public_export_first'}:
    reasoning = importlib.import_module(package)
    # These are legacy public functions whose names also identify real child
    # modules. Import order must not turn a function into a module object.
    routes = (
        ('legal_ir_view_contracts', 'LegalIRViewContract'),
        ('legal_ir_semantic_diff', 'LegalIRSemanticDiffEngine'),
        ('legal_ir_rule_distillation', 'LegalIRRuleDistillationConfig'),
        ('legal_ir_build_manifest', 'LegalIRBuildManifest'),
    )
    leaves = {}
    for function_name, other_export in routes:
        if mode == 'public_export_first':
            public_type = getattr(reasoning, other_export)
        leaf = importlib.import_module(package + '.' + function_name)
        public_function = getattr(reasoning, function_name)
        assert public_function is getattr(leaf, function_name), function_name
        assert callable(public_function), function_name
        if mode == 'direct_owner_first':
            public_type = getattr(reasoning, other_export)
        assert public_type is getattr(leaf, other_export)
        leaves[function_name] = leaf
    for function_name, leaf in leaves.items():
        assert getattr(reasoning, function_name) is getattr(leaf, function_name)
    # This name occurred in two original import groups; retain its final binding.
    schema = importlib.import_module(package + '.legal_ir_schema_evolution')
    assert reasoning.LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION is schema.LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION
    # Explicit module-attribute replacement is also legacy Python behavior.
    # Loading another real owner must not restore over a caller's functions.
    overrides = {}
    for function_name in leaves:
        override = lambda name=function_name: name
        overrides[function_name] = override
        setattr(reasoning, function_name, override)
        assert getattr(reasoning, function_name) is override
    interop_name = package + '.legal_ir_interop'
    assert interop_name not in sys.modules, 'override control needs an unloaded owner'
    public_type = reasoning.LegalIRInteropEnvelope
    interop = importlib.import_module(interop_name)
    assert public_type is interop.LegalIRInteropEnvelope
    for function_name, override in overrides.items():
        assert getattr(reasoning, function_name) is override, function_name
        assert getattr(reasoning, function_name)() == function_name
else:
    raise AssertionError('unknown cold-import scenario: ' + mode)

names = list(reasoning.__all__)
assert len(names) == len(set(names)) == expected_count
encoded = json.dumps(names, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
assert hashlib.sha256(encoded).hexdigest() == expected_digest, 'legacy export names/order changed'
assert not optional_attempts, optional_attempts
assert not process_attempts, process_attempts
assert not mutation_attempts, mutation_attempts
assert not any(forbidden_name(name) for name in sys.modules)
print(json.dumps({
    'scenario': mode, 'export_count': len(names),
    'optional_import_attempts': optional_attempts,
    'process_attempts': process_attempts, 'filesystem_mutations': mutation_attempts,
}))
"""


def cold_import(tmp_path, scenario):
    root = Path(__file__).resolve().parents[4]
    inherited = os.environ.get("PYTHONPATH", "")
    paths = [str(root)]
    if inherited:
        paths.append(inherited)
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            PROGRAM,
            scenario,
            str(ORIGINAL_EXPORT_COUNT),
            ORIGINAL_ORDERED_EXPORT_SHA256,
        ],
        cwd=tmp_path,
        env=dict(
            os.environ,
            PYTHONPATH=os.pathsep.join(paths),
            PYTHONDONTWRITEBYTECODE="1",
            IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
            IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
        ),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "scenario": scenario,
        "export_count": ORIGINAL_EXPORT_COUNT,
        "optional_import_attempts": [],
        "process_attempts": [],
        "filesystem_mutations": [],
    }
    assert list(tmp_path.iterdir()) == []


def test_reasoning_public_names_dir_and_unknown_attribute_are_inert(tmp_path):
    cold_import(tmp_path, "package")


@pytest.mark.parametrize("leaf", ["symbols", "source_maps"])
def test_pure_legal_leaf_imports_preserve_real_public_objects(tmp_path, leaf):
    cold_import(tmp_path, leaf)


@pytest.mark.parametrize("order", ["direct_owner_first", "public_export_first"])
def test_legacy_public_functions_survive_actual_owner_import_order(tmp_path, order):
    cold_import(tmp_path, order)


@pytest.mark.parametrize("kind", ["sentinel", "callable", "none", "module"])
@pytest.mark.parametrize("name", [
    "legal_ir_view_contracts", "legal_ir_semantic_diff",
    "legal_ir_rule_distillation", "legal_ir_build_manifest",
])
def test_early_caller_override_survives_first_actual_owner_import(tmp_path, name, kind):
    cold_import(tmp_path, "early_override:" + name + ":" + kind)
