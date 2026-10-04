"""Ordinary cached-span reader controls; no tensor/model/scheduler execution.

The numeric fixtures below are authored ordinary data, not native model
outputs. Actual retained namespaces are audited separately by the root owner.
"""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat

import pytest


PACKAGE = Path(__file__).resolve().parents[4]
READER_PATH = PACKAGE / 'benchmarks/audit_cached_span_device_probe.py'
PRODUCER_PATH = PACKAGE / 'benchmarks/probe_cached_span_device_candidate_v2.py'
PRODUCER_SHA256 = '4a5e5a6c633f20c6886bbeecdf9bbc45b23c5c784d8fd5d55543acb18932ecc5'
CHECKPOINT_SHA256 = 'a' * 64


@pytest.fixture
def reader():
    specification = importlib.util.spec_from_file_location('_ordinary_cached_span_control', READER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _tokens(text):
    return [{'text': item.group(), 'start': item.start(), 'end': item.end()}
            for item in re.finditer(r'\w+|[^\w\s]', text, re.UNICODE)]


def _fixture(count=1, dimension=768):
    inputs = {'dimension': dimension,
              'texts': [f'Agent α shall file #{index}.' for index in range(32)],
              'vectors': [[index / 64.0] + [0.0] * (dimension - 1) for index in range(32)]}
    rows, logits = [], []
    for text, vector in zip(inputs['texts'][:count], inputs['vectors'][:count]):
        tokens = _tokens(text)
        rows.append({'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                     'latent_sha256': hashlib.sha256(_wire(vector)).hexdigest(),
                     'formula_text': 'O(file(agent))', 'formal_outputs': {'fol': 'O(file(agent))'},
                     'minimum_decision_logit_margin': .5,
                     'span_diagnostics': {'tokens': tokens, 'modality_logits': [.25, .5, -.75],
                         'facets': {'action': {'presence_logit_margin': .5, 'span_logit_margin': .25,
                                              'present': True, 'text': 'file', 'start': 14, 'end': 18}}},
                     'proof_authority': False, 'training_executed': False})
        starts = [[[index / 16.0 for index in range(len(tokens))] for _ in range(6)]]
        logits.append({'modality': [[.25, .5, -.75]],
                       'presence': [[[.25, -.25] for _ in range(4)]],
                       'start': starts, 'end': deepcopy(starts)})
    report = {'checkpoint_sha256': CHECKPOINT_SHA256, 'input_dimension': dimension, 'rows': rows,
              'cuda_executed': False, 'execution_profile': {'device': 'cpu'},
              'actual_forward_batches': count, 'proof_authority': False}
    return report, logits, inputs


@pytest.mark.parametrize('dimension', (768, 4096))
@pytest.mark.parametrize('count', (1, 16, 32))
def test_authored_input_hash_tokens_and_all_four_shapes_join(reader, count, dimension):
    report, logits, inputs = _fixture(count, dimension)
    before = deepcopy((report, logits, inputs))
    reader.check_input_bindings(report, logits, inputs, count, CHECKPOINT_SHA256)
    assert (report, logits, inputs) == before
    for row, text in zip(logits, inputs['texts'][:count]):
        assert reader.shape(row['modality']) == (1, 3)
        assert reader.shape(row['presence']) == (1, 4, 2)
        assert reader.shape(row['start']) == reader.shape(row['end']) == (1, 6, len(_tokens(text)))


@pytest.mark.parametrize('fault', (
    'source_hash', 'latent_hash', 'checkpoint_hash', 'dimension', 'token_text', 'token_start', 'token_end',
    'token_missing', 'report_row_missing', 'numeric_row_missing', 'modality_shape', 'presence_shape',
    'start_facets', 'end_tokens', 'missing_output', 'nan', 'inf', 'integer', 'boolean'))
def test_independent_input_token_shape_and_finite_mutations_refuse(reader, fault):
    report, logits, inputs = _fixture()
    if fault == 'source_hash': report['rows'][0]['source_sha256'] = '0' * 64
    elif fault == 'latent_hash': report['rows'][0]['latent_sha256'] = '0' * 64
    elif fault == 'checkpoint_hash': report['checkpoint_sha256'] = '0' * 64
    elif fault == 'dimension': report['input_dimension'] = 4096
    elif fault.startswith('token_'):
        tokens = report['rows'][0]['span_diagnostics']['tokens']
        if fault == 'token_missing': tokens.pop()
        else:
            field = fault.removeprefix('token_')
            tokens[0][field] = 'different' if field == 'text' else tokens[0][field] + 1
    elif fault == 'report_row_missing': report['rows'].pop()
    elif fault == 'numeric_row_missing': logits.pop()
    elif fault == 'modality_shape': logits[0]['modality'][0].pop()
    elif fault == 'presence_shape': logits[0]['presence'][0].append([.25, -.25])
    elif fault == 'start_facets': logits[0]['start'][0].pop()
    elif fault == 'end_tokens':
        for row in logits[0]['end'][0]: row.pop()
    elif fault == 'missing_output': del logits[0]['end']
    else:
        logits[0]['modality'][0][0] = {'nan': float('nan'), 'inf': float('inf'), 'integer': 1, 'boolean': True}[fault]
    with pytest.raises(AssertionError):
        reader.check_input_bindings(report, logits, inputs, 1, CHECKPOINT_SHA256)


@pytest.mark.parametrize('count', (True, False, 1.0, 0, 2, 33))
def test_counts_require_plain_supported_integer(reader, count):
    report, logits, inputs = _fixture()
    with pytest.raises(AssertionError):
        reader.check_input_bindings(report, logits, inputs, count, CHECKPOINT_SHA256)


@pytest.mark.parametrize('changed_input', ('text', 'latent_float64_small', 'latent_signed_zero'))
def test_changed_declared_inputs_are_not_accepted_by_unchanged_report_hashes(reader, changed_input):
    report, logits, inputs = _fixture()
    if changed_input == 'text': inputs['texts'][0] += '!'
    elif changed_input == 'latent_float64_small': inputs['vectors'][0][0] += 1e-100
    else: inputs['vectors'][0][1] = -0.0
    with pytest.raises(AssertionError):
        reader.check_input_bindings(report, logits, inputs, 1, CHECKPOINT_SHA256)


def test_canonical_decisions_exclude_only_declared_runtime_and_finite_diagnostics(reader):
    original, _, _ = _fixture()
    alternate = deepcopy(original)
    alternate.update(cuda_executed=True, execution_profile={'device': 'cuda:0'}, actual_forward_batches=1,
                     device_to_cpu_head_transfers=4, cpu_head_output_materializations=4)
    row = alternate['rows'][0]
    row['minimum_decision_logit_margin'] = .75
    row['span_diagnostics']['modality_logits'] = [.5, .75, -.5]
    row['span_diagnostics']['facets']['action']['presence_logit_margin'] = .875
    assert reader.decisions(original) == reader.decisions(alternate)
    assert original['rows'][0]['minimum_decision_logit_margin'] == .5


@pytest.mark.parametrize('field', ('formula_text', 'formal_outputs', 'source_sha256', 'latent_sha256', 'tokens', 'facet_present', 'proof_authority'))
def test_canonical_semantic_source_token_and_authority_fields_remain_visible(reader, field):
    original, _, _ = _fixture()
    alternate = deepcopy(original)
    row = alternate['rows'][0]
    if field == 'tokens': row['span_diagnostics']['tokens'][0]['start'] = 1
    elif field == 'facet_present': row['span_diagnostics']['facets']['action']['present'] = False
    else: row[field] = True if field == 'proof_authority' else {'fol': 'P(other)'} if field == 'formal_outputs' else 'changed'
    assert reader.decisions(original) != reader.decisions(alternate)


@pytest.mark.parametrize('value', (True, 0, float('nan'), float('inf')))
def test_invalid_margin_cannot_be_hidden_by_canonicalization(reader, value):
    report, _, _ = _fixture()
    report['rows'][0]['minimum_decision_logit_margin'] = value
    with pytest.raises(AssertionError): reader.decisions(report)


def _execution_fixture(dimension, cuda, candidate, count=16):
    report, _, inputs = _fixture(count, dimension)
    device = 'cuda:0' if cuda else 'cpu'
    base = ('native-768-source-span-batched-device-float32-cpu-decisions/v1' if dimension == 768
            else 'native-4096-source-span-batched-device-float32-cpu-decisions/v2')
    session = ('native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1' if dimension == 768
               else 'native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2')
    cached = f'native{dimension}-owned-bitwise-cached-input/v1'
    profile = {'dimension': dimension, 'optimized': cuda, 'dtype': 'float32', 'stored_checkpoint_device': 'cpu',
               'device': device, 'profile_id': cached if cuda and candidate else session if cuda else base,
               'session_profile_id': session, 'inherited_profile_id': base,
               'canonical_decision_device': 'resident_cpu' if dimension == 768 and not cuda else 'cpu',
               'numerical_batching': 'one_complete_valid_source_batch' if cuda else 'singleton_cpu_opt_out',
               'checkpoint_sha256': CHECKPOINT_SHA256, 'proof_authority': False}
    if candidate:
        profile.update(cached_input_profile_id=cached, inherited_cached_input_profile_id=session if cuda else base)
    token_counts = [len(_tokens(text)) for text in inputs['texts'][:count]]
    ambient = {'cuda_matmul_allow_tf32': False, 'float32_matmul_precision': 'highest',
               'cudnn': {'allow_tf32': True, 'benchmark': False}}
    precision = {'device': device, 'persistent_flags_mutated': False, 'scoped_cudnn': cuda}
    if cuda:
        precision.update(profile_id='native-768-source-span-device-strict-cuda-float32/v2' if dimension == 768
                         else 'native-4096-source-span-strict-cuda-float32/v1',
            ambient_flags_restored=True, synchronized_before_restore=True,
            requires_owned_process_without_unrelated_concurrent_cudnn=True,
            ambient_policy=ambient, effective_policy={**ambient, 'cudnn': {**ambient['cudnn'], 'allow_tf32': False}})
    else:
        precision['profile_id'] = 'native-768-source-span-device-float32/v1' if dimension == 768 else base
    if dimension == 4096:
        precision['precision_scope_helper_profile_id'] = ('native-768-source-span-device-strict-cuda-float32/v2' if cuda
                                                          else 'native-768-source-span-device-float32/v1')
    profile.update(strict_cuda_gru_profile_id='native-768-source-span-device-strict-cuda-float32/v2' if dimension == 768
                   else 'native-4096-source-span-strict-cuda-float32/v1',
        precision_policy={'persistent_flags_mutated': False,
            'requires_owned_process_without_unrelated_concurrent_cudnn': cuda,
            'cuda_gru_allow_tf32': False if cuda else None,
            'ambient_at_admission': deepcopy(ambient) if cuda else None})
    forwards = [{'rows': len(tokens), 'native_input_dimension': dimension, 'input_device': device,
                 'output_devices': dict.fromkeys(('modality', 'presence', 'start', 'end'), device),
                 'output_dtype': 'float32', 'gru_executed': True, 'source_tokens': tokens,
                 'gru_precision': deepcopy(precision)}
                for tokens in ([token_counts] if cuda else [[value] for value in token_counts])]
    memory = {'gpu_working_set_bytes': 1024, 'host_working_set_bytes': 2048}
    report.update(execution_profile=deepcopy(profile), cuda_executed=cuda, numerical_batching=cuda,
                  canonical_decision_device='cpu', valid_source_count=count,
                  cpu_head_output_materializations=4 if cuda else 0, device_to_cpu_head_transfers=4 if cuda else 0,
                  actual_forward_batches=deepcopy(forwards),
                  schema='native-768-source-span-batched-device-inference/v1' if dimension == 768
                  else 'native-4096-source-span-device-inference/v1')
    if cuda: report['batch_memory_bound'] = deepcopy(memory)
    if dimension == 768:
        scope = {'scope': 'separate_checked_private_four_logit_forward_outside_public_timing',
                 'coverage': 'one_snapshot_per_lane_per_count', 'entry_and_exit_owned_checks': True,
                 'singletons': not cuda, 'batch_memory_bound': memory, 'observations': deepcopy(forwards)}
    else:
        def singleton(items):
            return {'scope': 'benchmark_only_checked_private_forward', 'entry_and_exit_owned_session_checks': True,
                    'public_cpu_opt_out_still_uses_singletons': True, 'batch_memory_bound': deepcopy(memory),
                    'observations': deepcopy(items)}
        scope = (singleton(forwards) if cuda else {'separate_checked_private_four_logits': True, 'singletons': True,
                                                   'observations': [singleton([item]) for item in forwards]})
    return report, scope, profile, inputs


@pytest.mark.parametrize('dimension', (768, 4096))
@pytest.mark.parametrize('cuda', (False, True))
@pytest.mark.parametrize('candidate', (False, True))
@pytest.mark.parametrize('count', (1, 16, 32))
def test_authored_public_private_execution_metadata_joins_exact_lane(reader, dimension, cuda, candidate, count):
    report, scope, profile, inputs = _execution_fixture(dimension, cuda, candidate, count)
    before = deepcopy((report, scope, profile, inputs))
    reader.check_execution_scope(report, scope, dimension=dimension, count=count, cuda=cuda,
                                 profile=profile, inputs=inputs, candidate=candidate)
    assert (report, scope, profile, inputs) == before


@pytest.mark.parametrize('dimension', (768, 4096))
@pytest.mark.parametrize('fault', ('profile_device', 'public_device', 'public_batch_device', 'output_device',
    'forward_dimension', 'forward_rows_bool', 'token_width', 'gru_scope', 'gru_profile_missing',
    'ambient_restore', 'completion_sync', 'effective_tf32', 'missing_numeric_observation', 'numeric_device',
    'numeric_entry', 'numeric_scope', 'transfer_bool', 'memory_float', 'profile_inherited',
    'profile_tf32', 'profile_owned_process', 'admission_policy'))
def test_contradictory_public_numeric_device_token_and_precision_metadata_refuses(reader, dimension, fault):
    report, scope, profile, inputs = _execution_fixture(dimension, True, True)
    forward = report['actual_forward_batches'][0]
    if fault == 'profile_device':
        profile['device'] = report['execution_profile']['device'] = 'cpu'
    elif fault == 'public_device': report['execution_profile']['device'] = 'cpu'
    elif fault == 'public_batch_device': forward['input_device'] = 'cpu'
    elif fault == 'output_device': forward['output_devices']['end'] = 'cpu'
    elif fault == 'forward_dimension': forward['native_input_dimension'] = 384
    elif fault == 'forward_rows_bool': forward['rows'] = True
    elif fault == 'token_width': forward['source_tokens'][-1] += 1
    elif fault == 'gru_scope': forward['gru_precision']['scoped_cudnn'] = False
    elif fault == 'gru_profile_missing': del forward['gru_precision']['profile_id']
    elif fault == 'ambient_restore': forward['gru_precision']['ambient_flags_restored'] = False
    elif fault == 'completion_sync': forward['gru_precision']['synchronized_before_restore'] = False
    elif fault == 'effective_tf32': forward['gru_precision']['effective_policy']['cudnn']['allow_tf32'] = True
    elif fault == 'missing_numeric_observation': scope['observations'].clear()
    elif fault == 'numeric_device': scope['observations'][0]['input_device'] = 'cpu'
    elif fault == 'numeric_entry': scope['entry_and_exit_owned_checks' if dimension == 768 else 'entry_and_exit_owned_session_checks'] = False
    elif fault == 'numeric_scope': scope['scope'] = 'unverified_other_scope'
    elif fault == 'transfer_bool': report['device_to_cpu_head_transfers'] = True
    elif fault == 'memory_float': scope['batch_memory_bound']['gpu_working_set_bytes'] = 1024.0
    elif fault == 'profile_tf32':
        profile['precision_policy']['cuda_gru_allow_tf32'] = report['execution_profile']['precision_policy']['cuda_gru_allow_tf32'] = True
    elif fault == 'profile_owned_process':
        profile['precision_policy']['requires_owned_process_without_unrelated_concurrent_cudnn'] = report['execution_profile']['precision_policy']['requires_owned_process_without_unrelated_concurrent_cudnn'] = False
    elif fault == 'admission_policy':
        profile['precision_policy']['ambient_at_admission']['cudnn']['allow_tf32'] = False
        report['execution_profile']['precision_policy']['ambient_at_admission']['cudnn']['allow_tf32'] = False
    else:
        profile['inherited_profile_id'] = report['execution_profile']['inherited_profile_id'] = 'other-profile'
    with pytest.raises((AssertionError, KeyError)):
        reader.check_execution_scope(report, scope, dimension=dimension, count=16, cuda=True,
                                     profile=profile, inputs=inputs, candidate=True)


@pytest.mark.parametrize('fault', ('missing_singleton', 'nested_device', 'nested_entry', 'wrong_singletons'))
def test_4096_cpu_numeric_singletons_are_each_checked(reader, fault):
    report, scope, profile, inputs = _execution_fixture(4096, False, True)
    if fault == 'missing_singleton': scope['observations'].pop()
    elif fault == 'nested_device': scope['observations'][-1]['observations'][0]['input_device'] = 'cuda:0'
    elif fault == 'nested_entry': scope['observations'][-1]['entry_and_exit_owned_session_checks'] = False
    else: scope['singletons'] = 1
    with pytest.raises(AssertionError):
        reader.check_execution_scope(report, scope, dimension=4096, count=16, cuda=False,
                                     profile=profile, inputs=inputs, candidate=True)


@pytest.mark.parametrize('field', ('proof_authority', 'execution_attestation', 'performance_qualified',
    'production_qualified', 'native_leanstral_outputs_qualified', 'trained4096_qualification_established'))
@pytest.mark.parametrize('value', (True, 0, None))
def test_coherent_nested_authority_cannot_become_valid_by_cpu_cuda_agreement(reader, field, value):
    original, _, _ = _fixture()
    alternate = deepcopy(original)
    for report in (original, alternate): report['rows'][0]['formal_outputs'][field] = value
    assert reader.decisions(original) == reader.decisions(alternate)
    with pytest.raises(AssertionError): reader.authority(original)


def test_recursive_authority_accepts_plain_diagnostics_but_retains_node_depth_and_finite_bounds(reader):
    reader.authority({'rows': [{'proof_authority': False, 'output': {'x': .125, 'selected': True}}]})
    with pytest.raises(AssertionError): reader.authority({'x': [1]}, budget=[2])
    deep = None
    for _ in range(66): deep = [deep]
    with pytest.raises(AssertionError): reader.authority(deep)
    with pytest.raises(AssertionError): reader.authority({'x': float('nan')})


@pytest.mark.parametrize('raw', (b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"x":-Infinity}', b'{"nested":[1e999]}', b'{"x":-1e999}', b'not-json'))
def test_json_duplicate_keys_constants_and_overflow_are_refused(reader, raw):
    with pytest.raises((AssertionError, ValueError)):
        reader.strict(raw)


def test_wire_pin_and_finite_json_have_exact_independent_bytes(reader, tmp_path):
    value = {'b': [0.0, -0.0, .125], 'a': 'α'}
    raw = reader.wire(value)
    assert raw == b'{"a":"\\u03b1","b":[0.0,-0.0,0.125]}'
    assert reader.strict(raw) == value
    assert reader.pin(tmp_path/'ordinary.json', raw) == {
        'path': str((tmp_path/'ordinary.json').absolute()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    with pytest.raises(ValueError): reader.wire({'x': float('nan')})


@pytest.mark.parametrize('pair', (([[1.0, 2.0]], [[1.25, 1.5]]), ([[-0.0]], [[0.0]])))
def test_numeric_error_is_independently_recomputed(reader, pair):
    left, right = pair
    assert reader.error(left, right) == max(abs(a-b) for row_a, row_b in zip(left, right) for a, b in zip(row_a, row_b))


@pytest.mark.parametrize('right', ([], [[1.0, 2.0]], [[True]], [[float('nan')]]))
def test_numeric_error_refuses_missing_shapes_types_and_nonfinite(reader, right):
    with pytest.raises(AssertionError): reader.error([[1.0]], right)


def _file(root, name='ordinary.json', raw=b'{"ordinary":true}', mode=0o444):
    path = root/name
    path.write_bytes(raw)
    path.chmod(mode)
    return path


def test_read_accepts_exact_readonly_regular_file_and_explicit_current_source(reader, tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    path = _file(tmp_path)
    assert reader.read(path) == b'{"ordinary":true}'
    path.chmod(0o644)
    with pytest.raises(AssertionError): reader.read(path)
    assert reader.read(path, readonly=False) == b'{"ordinary":true}'


@pytest.mark.parametrize('kind', ('empty', 'oversize', 'directory', 'fifo', 'symlink', 'hardlink', 'parent_symlink', 'outside_root'))
def test_nonordinary_unbounded_aliased_or_outside_reads_refuse(reader, tmp_path, monkeypatch, kind):
    inside = tmp_path/'inside'; inside.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    monkeypatch.setattr(reader, 'ROOT', inside)
    monkeypatch.setattr(reader, 'MAX_FILE', 64)
    path = inside/'entry.json'
    if kind == 'empty': _file(inside, path.name, b'')
    elif kind == 'oversize': _file(inside, path.name, b'x'*65)
    elif kind == 'directory': path.mkdir()
    elif kind == 'fifo': os.mkfifo(path)
    elif kind == 'symlink': path.symlink_to(_file(inside, 'target.json'))
    elif kind == 'hardlink': os.link(_file(inside, 'target.json'), path)
    elif kind == 'parent_symlink':
        actual = inside/'actual'; actual.mkdir(); _file(actual)
        (inside/'parent').symlink_to(actual, target_is_directory=True)
        path = inside/'parent/ordinary.json'
    else: path = _file(outside)
    with pytest.raises((AssertionError, OSError)): reader.read(path)


@pytest.mark.parametrize('replacement', ('different_inode', 'symlink'))
def test_open_time_leaf_substitution_cannot_bypass_initial_pin(reader, tmp_path, monkeypatch, replacement):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    path, other = _file(tmp_path), _file(tmp_path, 'other.json', b'{"ordinary":false}')
    original_open = os.open
    changed = False
    def open_after_swap(name, flags, *args, **kwargs):
        nonlocal changed
        if (Path(name) == path or (Path(name).name == path.name and kwargs.get('dir_fd') is not None)) and not changed:
            changed = True
            # Retain the old inode elsewhere so this race control cannot
            # accidentally reuse its inode number when creating the new leaf.
            path.rename(tmp_path/'original-renamed.json')
            if replacement == 'symlink': path.symlink_to(other)
            else: _file(tmp_path)
        return original_open(name, flags, *args, **kwargs)
    with monkeypatch.context() as temporary:
        temporary.setattr(reader.os, 'open', open_after_swap)
        with pytest.raises((AssertionError, OSError)): reader.read(path)
    assert changed


def test_mutation_after_open_is_detected_by_final_file_and_path_identity(reader, tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    path = _file(tmp_path)
    original_fstat, calls, identity = os.fstat, 0, path.stat()
    def fstat_then_mutate(descriptor):
        nonlocal calls
        observed = original_fstat(descriptor)
        if stat.S_ISREG(observed.st_mode) and (observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino):
            calls += 1
            if calls == 2:
                path.chmod(0o644)
                path.write_bytes(b'{"changed":true}')
        return observed
    with monkeypatch.context() as temporary:
        temporary.setattr(reader.os, 'fstat', fstat_then_mutate)
        with pytest.raises(AssertionError): reader.read(path)
    assert calls == 2


@pytest.mark.parametrize('replacement', ('symlink', 'ordinary_directory'))
def test_parent_substitution_after_admitted_directory_fd_refuses(reader, tmp_path, monkeypatch, replacement):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    parent, alternate = tmp_path/'parent', tmp_path/'alternate'
    parent.mkdir(); alternate.mkdir()
    path = _file(parent)
    _file(alternate, path.name, b'{"ordinary":false}')
    original_open, changed = os.open, False
    def open_after_parent_swap(name, flags, *args, **kwargs):
        nonlocal changed
        if Path(name).name == path.name and kwargs.get('dir_fd') is not None and not changed:
            changed = True
            parent.rename(tmp_path/'old-parent')
            if replacement == 'symlink': parent.symlink_to(alternate, target_is_directory=True)
            else:
                parent.mkdir()
                _file(parent, path.name, b'{"ordinary":false}')
        return original_open(name, flags, *args, **kwargs)
    with monkeypatch.context() as temporary:
        temporary.setattr(reader.os, 'open', open_after_parent_swap)
        with pytest.raises((AssertionError, OSError)): reader.read(path)
    assert changed


def test_inventory_is_streaming_and_refuses_after_first_over_budget_entry(reader, tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    paths = [_file(tmp_path, f'{index}.json') for index in range(5)]
    assert reader._inventory(tmp_path, max_files=5) == {str(path) for path in paths}
    original_scandir, yielded = os.scandir, []
    class ObservedDirectory:
        def __init__(self, directory): self.actual = original_scandir(directory)
        def __enter__(self):
            self.actual.__enter__()
            return self
        def __exit__(self, *args): return self.actual.__exit__(*args)
        def __iter__(self): return self
        def __next__(self):
            entry = next(self.actual)
            yielded.append(entry.name)
            return entry
    with monkeypatch.context() as temporary:
        temporary.setattr(reader.os, 'scandir', ObservedDirectory)
        with pytest.raises(AssertionError): reader._inventory(tmp_path, max_files=2)
    assert len(yielded) == 3


@pytest.mark.parametrize('limit', (True, False, 0, 1025, 1.0))
def test_inventory_limit_is_plain_and_bounded(reader, tmp_path, monkeypatch, limit):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    with pytest.raises(AssertionError): reader._inventory(tmp_path, max_files=limit)


def test_audit_missing_or_malformed_ordinary_data_returns_structured_refusal(reader, tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    missing = reader.audit(tmp_path, '0'*64)
    assert missing['qualified'] is missing['closed_artifacts_consistent'] is False and missing['error']['type'] == 'FileNotFoundError'
    raw = b'{"schema":"wrong"}'
    _file(tmp_path, 'result.json', raw)
    refused = reader.audit(tmp_path, hashlib.sha256(raw).hexdigest())
    assert refused['qualified'] is refused['closed_artifacts_consistent'] is False and refused['error'] is not None


def test_reader_source_uses_only_ordinary_dependencies_and_performs_no_evidence_import():
    tree = ast.parse(READER_PATH.read_bytes(), filename=str(READER_PATH))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom): imports.add(node.module.split('.')[0])
    assert imports <= {'argparse', 'copy', 'hashlib', 'json', 'math', 'os', 'pathlib', 're', 'stat'}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', '__import__'} for node in ast.walk(tree))


def test_held_producer_source_keeps_gc_before_framework_cleanup_and_diagnostic_scope():
    raw = PRODUCER_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256
    tree = ast.parse(raw, filename=str(PRODUCER_PATH))
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
    collector = [node for node in ast.walk(run) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == 'gc' and node.func.attr == 'collect']
    cleanup = [node for node in ast.walk(run) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and isinstance(node.func.value, ast.Name) and node.func.value.id == 'cleanup' and node.func.attr == '_cleanup_owned_cuda']
    assert len(collector) == len(cleanup) == 1 and collector[0].lineno < cleanup[0].lineno
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {'step', 'fit', 'train', 'backward'} for node in ast.walk(tree))
    assert any(isinstance(node, ast.Constant) and node.value == 'one_uninstrumented_complete_call_per_CUDA_route_count_no_repeatability_claim' for node in ast.walk(tree))
