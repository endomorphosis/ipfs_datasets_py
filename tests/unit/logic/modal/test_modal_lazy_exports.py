"""Cold-process modal public API compatibility and structural target invariants."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def _cold(code: str) -> None:
    # Preserve the package actually selected by this test process, including
    # an isolated test checkout. Never rely on the unrelated editable install.
    spec = importlib.util.find_spec("ipfs_datasets_py")
    assert spec is not None and spec.submodule_search_locations
    package_parent = str(Path(next(iter(spec.submodule_search_locations))).parent)
    env = {**os.environ, "PYTHONPATH": package_parent, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", code], cwd=package_parent, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_package_and_directory_inspection_do_not_import_unrequested_integrations():
    _cold('''
import sys
import ipfs_datasets_py.logic.modal as modal
before = set(sys.modules)
assert {'DeterministicModalCompiler', 'repair_decompiler_round_trip', 'LeanstralAuditWorker', 'compiler', 'decompiler_repairs'} <= set(dir(modal))
assert set(sys.modules) == before
assert not any(name.startswith('ipfs_datasets_py.logic.modal.') for name in sys.modules)
assert 'torch' not in sys.modules and 'symai' not in sys.modules
try:
    modal.this_export_does_not_exist
except AttributeError:
    pass
else:
    raise AssertionError('unknown export unexpectedly resolved')
assert set(sys.modules) == before
''')


def test_structural_decompiler_submodule_does_not_load_optional_torch_or_audit_services():
    _cold('''
import sys
from ipfs_datasets_py.logic.modal.decompiler_repairs import repair_decompiler_round_trip
from ipfs_datasets_py.logic.modal import repair_decompiler_round_trip as public
assert public is repair_decompiler_round_trip
loaded = {name for name in sys.modules if name.startswith('ipfs_datasets_py.logic.modal.')}
assert loaded == {'ipfs_datasets_py.logic.modal.decompiler_repairs'}, loaded
assert 'torch' not in sys.modules and 'symai' not in sys.modules
''')


def test_every_historical_export_star_import_and_submodule_identity_are_preserved():
    _cold('''
import hashlib, importlib, json
import ipfs_datasets_py.logic.modal as modal
sha = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
# Snapshots of the historical eager API, including its nine non-__all__ exports
# and three duplicate __all__ entries. These guard public names and origins.
assert sha(modal.__all__) == '1fdd09fca349ee5a88525d570e32f581601f2877ca84352e05bad1b65685a103'
assert sha(modal._LAZY_EXPORTS) == '46b03ed52af75c70bdb30132cb1c04e6a5f552bcd082d9c30fb5c31500f8f97e'
assert sha(modal._LAZY_MODULES) == 'ea8da185c436926d024239c771f91fd43c2c6c4cce617caa4873f127376f7f48'
assert len(modal.__all__) == 255 and len(set(modal.__all__)) == 252
namespace = {}
exec('from ipfs_datasets_py.logic.modal import *', namespace)
for name, (module, attribute) in modal._LAZY_EXPORTS.items():
    expected = getattr(importlib.import_module(module, modal.__name__), attribute)
    assert getattr(modal, name) is expected, name
    assert modal.__dict__[name] is expected, name
    if name in modal.__all__:
        assert namespace[name] is expected, name
for name, module in modal._LAZY_MODULES.items():
    assert getattr(modal, name) is importlib.import_module(module, modal.__name__), name
''')


def test_explicit_from_import_of_historical_nonstar_export_is_preserved():
    _cold('''
from ipfs_datasets_py.logic.modal import LeanstralAuditPolicyConfig
from ipfs_datasets_py.logic.modal.leanstral_audit_policy import LeanstralAuditPolicyConfig as direct
assert LeanstralAuditPolicyConfig is direct
''')


def test_concurrent_first_access_returns_original_export_object():
    _cold('''
from concurrent.futures import ThreadPoolExecutor
import ipfs_datasets_py.logic.modal as modal
with ThreadPoolExecutor(max_workers=4) as pool:
    values = list(pool.map(lambda _: modal.repair_decompiler_round_trip, range(16)))
from ipfs_datasets_py.logic.modal.decompiler_repairs import repair_decompiler_round_trip
assert all(value is repair_decompiler_round_trip for value in values)
''')


def test_structural_target_bytes_match_prechange_golden_and_remain_source_copy_safe():
    _cold('''
import hashlib, json, sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import build_decompiler_structural_learning_target
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
sample = build_us_code_sample(title='qualification-fixture', section='20', text='The officer shall retain the file for at least 20 days.')
assert 'ipfs_datasets_py.logic.modal' not in sys.modules
first = build_decompiler_structural_learning_target(sample, source_text=sample.text)
second = build_decompiler_structural_learning_target(sample, source_text=sample.text)
assert first == second
payload = json.dumps(first, sort_keys=True, separators=(',', ':'))
assert hashlib.sha256(payload.encode()).hexdigest() == 'bf3756f2482da9819dc6920a65f6aad69be4ad8e627e4d11853239c485a162e5'
assert first['source_copy_policy'] == 'hash_only' and len(first['formula_targets']) == 1
assert sample.text not in payload
assert 'torch' not in sys.modules and 'symai' not in sys.modules
''')
