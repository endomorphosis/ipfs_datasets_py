"""Target-independent source interventions and explicit numerical provenance."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / 'scripts/ops/autoencoder/evaluate_gte_native_source_controls.py'
spec = importlib.util.spec_from_file_location('_test_native_source_controls', SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def rows():
    result = []
    for index in range(4):
        vector = [float(index), float(index + 1)]
        result.append({'id': str(index), 'source_sha256': subject.digest(str(index)),
            **{key: {'input_vector': vector[:], 'input_sha256': subject.digest(vector)}
               for key in ('generation_input', 'native_generation_input')}})
    return result


def runtime(tmp_path):
    refs = {}
    for name in ('checkpoint', 'manifest', 'config', 'training_report', 'reload_verification'):
        refs[name] = subject.write(tmp_path / (name + '.json'), {'kind': name})
    implementations = []
    for name in ('run_gte_precise_interface_training.py', 'gte_precise_gradient_clipping.py', 'cli.py', 'trainer.py'):
        p = tmp_path / name
        p.write_text('# no execution\n')
        implementations.append(subject.file_ref(p))
    data = {'schema': 'gte-precise-interface-runtime-receipt/v1', 'completed': True,
        'training_executed': True, 'inner_implementation_pins_alone_are_complete': False,
        'configured_bound_relaxed': False, 'original_source_files_modified': False,
        'proof_authority': False, 'source_fidelity_qualified': False,
        'algorithm': 'cpu-float32-gradient-float64-l2-clip-with-four-epsilon-margin/v1',
        'gradient_dtype': 'float32', 'norm_dtype': 'float64', 'optimizer_steps': 1,
        'clipping_calls': [{'algorithm': 'cpu-float32-gradient-float64-l2-clip-with-four-epsilon-margin/v1',
            'gradient_tensor_count': 4, 'norm_before': 2.0, 'norm_after': 0.99999,
            'max_norm': 1.0, 'scale': 0.49999}],
        'result': {'primary_start': 'original_initialization', 'optimizer_steps': 1,
                   'manifest_sha256': refs['manifest']['sha256']},
        'implementation_files': implementations, **refs}
    return data


@pytest.mark.parametrize('donor', [True, False])
def test_cross_source_is_bijection_and_preserves_receiving_source(donor):
    source = rows()
    before = deepcopy(source)
    outputs = [subject.intervention_input(source, i, 'cross_source', donor=donor) for i in range(4)]
    assert {r['donor']['id'] for _, r in outputs} == {r['id'] for r in source}
    for i, (vector, receipt) in enumerate(outputs):
        assert receipt['receiving_id'] == source[i]['id']
        assert receipt['receiving_source_sha256'] == source[i]['source_sha256']
        assert receipt['donor']['source_sha256'] != receipt['receiving_source_sha256']
        assert subject.digest(vector) == receipt['donor']['input_sha256'] == receipt['effective_input_sha256']
        assert receipt['target_access'] is False
    assert source == before


def test_zero_coordinates_do_not_claim_disabled_architecture():
    vector, receipt = subject.intervention_input(rows(), 1, 'zero', donor=False)
    assert vector == [0.0, 0.0]
    assert receipt['zero_input_is_disabled_context'] is False
    assert receipt['donor'] is None


def test_source_returns_owned_input():
    source = rows()
    vector, receipt = subject.intervention_input(source, 1, 'source', donor=False)
    vector[0] = -9
    assert source[1]['native_generation_input']['input_vector'][0] == 1.0
    assert receipt['original_input_sha256'] == receipt['effective_input_sha256']


def test_cross_source_rejects_same_source_identity():
    source = rows()[:1]
    with pytest.raises(ValueError, match='distinct'):
        subject.intervention_input(source, 0, 'cross_source', donor=False)


def test_reference_fields_cannot_change_interventions():
    source = rows()
    expected = [subject.intervention_input(source, i, 'cross_source', donor=False) for i in range(4)]
    for row in source:
        row['reference'] = {'target': {'do_not_read': row['id']}}
    assert [subject.intervention_input(source, i, 'cross_source', donor=False) for i in range(4)] == expected


def test_full_outer_runtime_is_admitted(tmp_path):
    data = runtime(tmp_path)
    ref = subject.write(tmp_path / 'runtime.json', data)
    loaded, refs = subject.runtime_receipt(ref, expected_start='original_initialization')
    assert loaded == data and len(refs) == 10


@pytest.mark.parametrize('mutation', ['missing_adapter', 'wrong_start', 'unbounded_gradient', 'inner_only'])
def test_bad_runtime_is_rejected(tmp_path, mutation):
    data = runtime(tmp_path)
    if mutation == 'missing_adapter':
        data['implementation_files'] = data['implementation_files'][1:]
    elif mutation == 'wrong_start':
        data['result']['primary_start'] = 'authenticated_aligned_generation'
    elif mutation == 'unbounded_gradient':
        data['clipping_calls'][0]['norm_after'] = 1.001
    else:
        data['inner_implementation_pins_alone_are_complete'] = True
    ref = subject.write(tmp_path / 'runtime.json', data)
    with pytest.raises(ValueError):
        subject.runtime_receipt(ref, expected_start='original_initialization')


def test_runtime_rejects_modified_numerical_implementation(tmp_path):
    data = runtime(tmp_path)
    ref = subject.write(tmp_path / 'runtime.json', data)
    Path(data['implementation_files'][1]['path']).write_text('# modified\n')
    with pytest.raises(ValueError, match='changed'):
        subject.runtime_receipt(ref, expected_start='original_initialization')


def test_pinned_file_tampering_rejected(tmp_path):
    ref = subject.write(tmp_path / 'a.json', {'x': 1})
    Path(ref['path']).write_text(json.dumps({'x': 2}))
    with pytest.raises(ValueError, match='changed'):
        subject.read_ref(ref)
