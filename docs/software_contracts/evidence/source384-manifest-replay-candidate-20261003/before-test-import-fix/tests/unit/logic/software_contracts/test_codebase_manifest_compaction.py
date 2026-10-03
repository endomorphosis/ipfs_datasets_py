"""Exact immutable compaction never supplies source or proof authority."""
from dataclasses import replace
from types import MappingProxyType
import json

import pytest

from test_codebase_manifest_memo import empty_cache, specimen
from ipfs_datasets_py.logic.software_contracts import codebase_ir as owner
from ipfs_datasets_py.logic.software_contracts import content


def repeated_specimen(specimen):
    value, _ = specimen()
    original = owner.CodebaseIRManifest.from_dict(value)
    symbol = value['semantic_state']['symbols'][0]
    symbol['metadata']['repeat_a'] = {'long_key_for_identity': ['a non-interned longer string', True, 1, None]}
    symbol['metadata']['repeat_b'] = json.loads(json.dumps(symbol['metadata']['repeat_a']))
    symbol['metadata']['typed'] = [[True], [1], [False], [0]]
    state = replace(original.semantic_state, symbols=(replace(original.semantic_state.symbols[0],
        metadata=symbol['metadata']), *original.semantic_state.symbols[1:]))
    manifest = replace(original, semantic_state=state)
    return manifest.to_dict(), manifest.cid


def test_compact_private_graph_has_exact_bytes_and_less_retained_memory(specimen):
    value, cid = repeated_specimen(specimen)
    original = owner.CodebaseIRManifest.from_dict(value)
    compact = owner._manifest_compact(original)
    raw = content.canonical_dag_json_bytes(value)
    key = (raw, owner._manifest_producer_key(), content._memo_registration_key())
    assert compact is not original
    assert compact.semantic_state.symbols[0] is not original.semantic_state.symbols[0]
    assert content.canonical_dag_json_bytes(compact.to_dict()) == raw
    assert compact.cid == original.cid == cid
    assert owner._manifest_retained_bytes(key, compact) < owner._manifest_retained_bytes(key, original)
    metadata = compact.semantic_state.symbols[0].metadata
    assert metadata['repeat_a'] is metadata['repeat_b']
    assert metadata['typed'][0] is not metadata['typed'][1]
    assert metadata['typed'][2] is not metadata['typed'][3]
    assert type(metadata['typed'][0][0]) is bool
    assert type(metadata['typed'][1][0]) is int


def test_cold_and_warm_outputs_keep_private_records_and_canonical_key(specimen):
    value, cid = repeated_specimen(specimen)
    cold = owner._reconstruct_manifest(value, cid)
    key, (private, identity, size) = next(iter(owner._MANIFEST_MEMO.items()))
    assert key[0] == content.canonical_dag_json_bytes(value)
    assert identity == cid and size == owner._MANIFEST_MEMO_SIZE
    assert cold is not private
    assert cold.semantic_state.symbols[0] is not private.semantic_state.symbols[0]
    detached = cold.to_dict()
    detached['semantic_state']['symbols'][0]['metadata']['repeat_a']['long_key_for_identity'].append('changed')
    object.__setattr__(cold.semantic_state.symbols[0], 'qualified_name', 'changed')
    object.__setattr__(cold.snapshot.entries[0], 'source_cid', content.cid_for_bytes(b'changed'))
    warm = owner._reconstruct_manifest(value, cid)
    assert content.canonical_dag_json_bytes(warm.to_dict()) == key[0]
    assert warm is not private and warm is not cold
    assert warm.semantic_state.symbols[0].metadata is private.semantic_state.symbols[0].metadata
    with pytest.raises(TypeError):
        warm.semantic_state.symbols[0].metadata['repeat_a']['long_key_for_identity'][0] = 'changed'


def test_equal_records_are_never_interned_and_container_order_is_preserved(specimen):
    value, _ = specimen()
    one = owner.CodebaseUnit.from_dict(value['units'][0])
    two = owner.CodebaseUnit.from_dict(value['units'][0])
    compact, token = owner._manifest_compact_value((one, two), {}, {})
    assert token is None and compact[0] == compact[1]
    assert compact[0] is not compact[1] and compact[0] is not one and compact[1] is not two
    maps = (MappingProxyType({'b': (2, 1), 'a': True}), MappingProxyType({'a': True, 'b': (2, 1)}))
    compact, _ = owner._manifest_compact_value(maps, {}, {})
    assert list(compact[0]) == ['b', 'a'] and list(compact[1]) == ['a', 'b']
    assert compact[0]['b'] == (2, 1)


@pytest.mark.parametrize('bad', [[1], {'x': 1}, MappingProxyType({'nested': []})])
def test_mutable_corruption_is_refused_not_frozen_into_admissibility(specimen, bad):
    value, _ = specimen()
    manifest = owner.CodebaseIRManifest.from_dict(value)
    object.__setattr__(manifest.semantic_state.symbols[0], 'metadata', bad)
    with pytest.raises(TypeError):owner._manifest_compact(manifest)
    assert not owner._MANIFEST_MEMO


def test_record_objects_cannot_be_smuggled_into_shared_json(specimen):
    value, _ = specimen(); manifest = owner.CodebaseIRManifest.from_dict(value)
    symbol = manifest.semantic_state.symbols[0]
    object.__setattr__(symbol, 'metadata', MappingProxyType({'record': manifest.units[0]}))
    with pytest.raises(TypeError):owner._manifest_compact(manifest)


def test_custom_scalar_equality_is_not_executed():
    class Custom(str):
        def __hash__(self):raise AssertionError('custom hash must not run')
        def __eq__(self, other):raise AssertionError('custom equality must not run')
    with pytest.raises(TypeError):owner._manifest_compact_value(Custom('value'), {}, {})
    with pytest.raises(TypeError):owner._manifest_compact_value(MappingProxyType({1: 'not-a-string-key'}), {}, {})


@pytest.mark.parametrize('warm', [False, True])
@pytest.mark.parametrize('helper', ['_manifest_compact', '_manifest_compact_value'])
def test_custom_compactor_binding_bypasses_memo(specimen, monkeypatch, warm, helper):
    value, cid = repeated_specimen(specimen)
    if warm:owner._reconstruct_manifest(value, cid)
    def forbidden(*args):raise AssertionError('custom helper must not execute')
    monkeypatch.setattr(owner, helper, forbidden)
    assert owner._manifest_producer_key() is None
    assert owner._reconstruct_manifest(value, cid).cid == cid
    assert owner._MANIFEST_MEMO_STATS['hits'] == 0
    assert owner._MANIFEST_MEMO_STATS['bypasses'] == 1


def test_intern_tables_are_per_call_and_have_no_recursive_closure():
    def make():return MappingProxyType({'repeat': tuple(['not globally interned string '+str(12345)])})
    a, _ = owner._manifest_compact_value(make(), {}, {})
    b, _ = owner._manifest_compact_value(make(), {}, {})
    assert a == b and a is not b and a['repeat'] is not b['repeat']
    assert owner._manifest_compact.__closure__ is None
    assert owner._manifest_compact_value.__closure__ is None
