"""Portable ordinary-data controls; root owns all model/native qualifications."""
from copy import deepcopy
import ast
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import statistics
import struct
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[4] / 'benchmarks/audit_span_inference_candidates.py'
SPEC = importlib.util.spec_from_file_location('_ordinary_span_candidates_reader', SOURCE)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


def trials():
    result = []
    for index, order in enumerate(reader.ORDER_SCHEDULE):
        seconds = {reader.CUDA_LANES[0]: float(index+1), reader.CUDA_LANES[1]: float(12-index),
                   reader.CUDA_LANES[2]: float(index+2)}
        result.append({'trial': index, 'order': list(order), 'observations': {
            lane: {'unprofiled_cuda_elapsed_seconds': seconds[lane]} for lane in order}})
    return result


def timing():
    rows = trials(); summaries, _ = reader.paired_summaries(rows)
    entry = {'trials': rows, **summaries}
    raw = {key: deepcopy(entry[key]) for key in ('trials', 'samples_seconds', 'median_seconds')}
    return entry, raw


def test_ratio_of_medians_and_paired_ratios_are_distinct_closed_algorithms():
    entry, raw = timing()
    summary, positions = reader.check_timing_entry(entry, raw)
    assert summary['median_baseline_over_cached_input_ratio'] == 1.
    assert statistics.median(summary['paired_baseline_over_cached_input_ratios']) != 1.
    assert set(summary['samples_seconds']) == set(reader.CUDA_LANES)
    assert all(value == {'first': 4, 'second': 4, 'third': 4} for value in positions.values())


@pytest.mark.parametrize('mutation', ['short', 'wrong_index', 'bool_index', 'duplicate_order', 'missing_lane', 'zero', 'nan', 'bool_seconds'])
def test_balanced_timing_refuses_incomplete_or_mislabeled_samples(mutation):
    rows = trials()
    if mutation == 'short': rows.pop()
    elif mutation == 'wrong_index': rows[0]['trial'] = 1
    elif mutation == 'bool_index': rows[0]['trial'] = False
    elif mutation == 'duplicate_order': rows[1]['order'] = rows[0]['order']
    elif mutation == 'missing_lane': rows[0]['observations'].pop(reader.CUDA_LANES[0])
    else:
        rows[0]['observations'][reader.CUDA_LANES[0]]['unprofiled_cuda_elapsed_seconds'] = {'zero': 0., 'nan': math.nan, 'bool_seconds': True}[mutation]
    with pytest.raises((AssertionError, KeyError)): reader.paired_summaries(rows)


@pytest.mark.parametrize('field', ['samples_seconds', 'median_seconds', 'median_baseline_over_cached_input_ratio',
    'paired_baseline_over_cached_input_ratios', 'paired_baseline_over_cached_input_min_ratio', 'paired_baseline_over_cached_input_max_ratio'])
def test_recomputed_numeric_summaries_cannot_be_replaced(field):
    entry, raw = timing()
    value = entry[field]
    if isinstance(value, dict): value[reader.CUDA_LANES[0]] = [1.] if isinstance(value[reader.CUDA_LANES[0]], list) else 1.
    elif isinstance(value, list): value[0] += .1
    else: entry[field] = value+.1
    with pytest.raises(AssertionError): reader.check_timing_entry(entry, raw)


def test_raw_timing_must_join_exact_trial_panels():
    entry, raw = timing(); raw['trials'][0]['observations'][reader.CUDA_LANES[0]]['other_report'] = 'aliased'
    with pytest.raises(AssertionError): reader.check_timing_entry(entry, raw)


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"nested":{"x":1e999}}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_duplicate_and_nonfinite_json_refused(raw):
    with pytest.raises((AssertionError, ValueError)): reader.strict(raw)


@pytest.mark.parametrize('value', [True, 1., -1, None, '0'])
def test_plain_resource_counts_refuse_alias_types(value):
    with pytest.raises(AssertionError): reader._plain_count(value)


def resource_zero():
    return {'allocated': {'cpu_slots': 0, 'memory_mb': 0}, **dict.fromkeys((
        'active_lease_count', 'active_root_lease_count', 'active_child_lease_count',
        'allocated_gpu_memory_mb', 'allocated_unified_memory_mb', 'allocated_child_process_slots', 'waiting_request_count'), 0)}


@pytest.mark.parametrize('field', ['cpu_slots', 'memory_mb', 'active_lease_count', 'allocated_gpu_memory_mb', 'allocated_unified_memory_mb'])
def test_cleanup_plain_zero_counts_cannot_be_false_or_float(field):
    for replacement in (False, 0., 1):
        value = resource_zero()
        target = value['allocated'] if field in value['allocated'] else value
        target[field] = replacement
        with pytest.raises(AssertionError): reader._zero_resources(value)


def test_live_root_reservation_is_not_sum_of_borrowed_children():
    value = {'allocated': {'cpu_slots': 4, 'memory_mb': 4096}, 'active_lease_count': 4,
        'active_root_lease_count': 1, 'active_child_lease_count': 3, 'allocated_gpu_memory_mb': 768,
        'allocated_unified_memory_mb': 4864, 'allocated_child_process_slots': 0, 'waiting_request_count': 0}
    reader._live_resources(value)
    value['allocated']['cpu_slots'] = 3
    with pytest.raises(AssertionError): reader._live_resources(value)


@pytest.mark.parametrize('dimension', [768, 4096])
def test_checkpoint_anchor_uses_sorted_exact_f32_bytes_and_signed_zero(dimension):
    checkpoint = {'config': {'latent_dimension': dimension, 'dtype': 'float32', 'device': 'cpu'},
                  'model_state': {'z': [[1., -0.]], 'a': [2.]}}
    anchor = reader.checkpoint_anchor(checkpoint, dimension)
    assert anchor['anchor_sha256'] == hashlib.sha256(struct.pack('<3f', 2., 1., -0.)).hexdigest()
    assert anchor['reference_bytes'] == 12 and anchor['tensor_count'] == 2
    checkpoint['model_state']['z'][0][1] = 0.
    assert reader.checkpoint_anchor(checkpoint, dimension)['anchor_sha256'] != anchor['anchor_sha256']


@pytest.mark.parametrize('value', [math.nan, math.inf, .1, True, 1, 1e300])
def test_checkpoint_and_saved_numeric_values_require_finite_exact_float32(value):
    with pytest.raises((AssertionError, OverflowError)): reader._float32(value)


def lease_observation(candidate=True, phase='separate_numeric_snapshot'):
    checks = [{'index': 0, 'outcome': 'valid_non_due', 'read_lock_segments': 2,
               'persist_requested_lock_segments': 0, 'fsync_calls': 0, 'replace_calls': 0}] if candidate else []
    return {'schema': 'source-bound-lease-cadence-call-observation/v1',
        'scope': 'main_thread_helper_check_only_no_background_or_timed_interval_attestation',
        'source_role': 'authenticated_lease_heartbeat', 'source_sha256': reader.FIXED_SOURCES['authenticated_lease_heartbeat'][1],
        'phase': phase, 'thread_id': 123, 'checks': checks,
        'generator_segment_scope': 'call_events_include_contextmanager_resume_segments_not_transaction_count',
        'background_threads_observed': False, 'timed_cuda_interval_observed': False,
        'execution_attestation': False, 'proof_authority': False, 'performance_qualified': False,
        'profile_restored': True, 'check_count': len(checks), 'valid_non_due_count': len(checks),
        'due_renewal_count': 0, 'refusal_count': 0}


def test_nondue_peer_race_writer_intent_is_not_a_durable_write():
    observed = lease_observation(); observed['checks'][0]['persist_requested_lock_segments'] = 1
    assert reader.check_lease_observation(observed, phase='separate_numeric_snapshot', candidate=True)['valid_non_due'] == 1


@pytest.mark.parametrize('field,value', [('fsync_calls', 1), ('replace_calls', 1), ('index', True), ('read_lock_segments', 0)])
def test_nondue_observation_has_real_read_and_no_durable_writes(field, value):
    observed = lease_observation(); observed['checks'][0][field] = value
    with pytest.raises(AssertionError): reader.check_lease_observation(observed, phase='separate_numeric_snapshot', candidate=True)


@pytest.mark.parametrize('field,value', [('source_sha256', '0'*64), ('check_count', True), ('profile_restored', False),
    ('background_threads_observed', True), ('phase', 'timed')])
def test_lease_observer_scope_and_source_are_not_inferred(field, value):
    observed = lease_observation(); observed[field] = value
    with pytest.raises(AssertionError): reader.check_lease_observation(observed, phase='separate_numeric_snapshot', candidate=True)


def old_profile(dimension, cuda):
    # Read retained ordinary JSON only; fixture is historical data, not executable code.
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench'/f'cached-span-native-compatibility-20261004-0{2 if dimension == 768 else 3}'
    data = json.loads((namespace/'result.json').read_text())
    return deepcopy(data['lanes']['baseline_cuda' if cuda else 'baseline_cpu_opt_out']['profile'])


def cadence_profile(dimension, cuda):
    profile = old_profile(dimension, cuda); parent = profile['profile_id']
    candidate = f'native-{dimension}-owned-bitwise-lease-heartbeat/v1'
    profile.update(lease_heartbeat_inherited_profile_id=parent, lease_heartbeat_profile_id=candidate,
        session_profile_id=candidate, lease_heartbeat_implementation=reader._cadence_implementation(),
        authenticated_lease_heartbeat_object_and_snapshot_identities_checked=True,
        lease_currentness={'schema': 'span-authenticated-lease-currentness/v1',
            'authenticated_read_completed_at_last_poll': True, 'renewed_at_last_completed_poll': False,
            'observation_scope': 'most_recent_completed_owned_poll_only_no_whole_call_or_execution_attestation'})
    if cuda: profile['profile_id'] = candidate
    return profile


@pytest.mark.parametrize('dimension,cuda', itertools.product((768,4096),(False,True)))
def test_cadence_receipt_normalizes_only_after_full_independent_binding(dimension, cuda):
    profile = cadence_profile(dimension, cuda)
    normalized = reader._parent_profile(profile, dimension, cuda, 'lease_cadence')
    assert reader.wire(normalized) == reader.wire(old_profile(dimension, cuda))


@pytest.mark.parametrize('mutation', ['wrong_profile', 'wrong_parent', 'wrong_owner_sha', 'wrong_helper_sha', 'missing_read', 'bool_renewal', 'whole_call_claim'])
def test_cadence_receipt_cannot_substitute_parent_source_or_whole_call_authority(mutation):
    profile = cadence_profile(768, True)
    if mutation == 'wrong_profile': profile['lease_heartbeat_profile_id'] = 'original'
    elif mutation == 'wrong_parent': profile['lease_heartbeat_inherited_profile_id'] = 'original'
    elif mutation == 'wrong_owner_sha': profile['lease_heartbeat_implementation']['source_sha256'] = '0'*64
    elif mutation == 'wrong_helper_sha': profile['lease_heartbeat_implementation']['authenticated_lease_heartbeat_implementation']['source_sha256'] = '0'*64
    elif mutation == 'missing_read': profile['lease_currentness']['authenticated_read_completed_at_last_poll'] = False
    elif mutation == 'bool_renewal': profile['lease_currentness']['renewed_at_last_completed_poll'] = 0
    else: profile['lease_currentness']['observation_scope'] = 'whole_job_no_IO'
    with pytest.raises(AssertionError): reader._parent_profile(profile, 768, True, 'lease_cadence')


@pytest.mark.parametrize('dimension', [768,4096])
def test_public_and_numeric_input_joins_use_exact_original_rows(dimension):
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench'/f'cached-span-native-compatibility-20261004-0{2 if dimension == 768 else 3}'
    inputs = json.loads((namespace/'inputs.json').read_text())
    report = json.loads((namespace/'baseline_cpu_opt_out-1-report.json').read_text())
    logits = json.loads((namespace/'baseline_cpu_opt_out-1-four-logits.json').read_text())
    reader.check_input_bindings(report, logits, inputs, 1, reader.FIXED_FIXTURES[dimension][0])
    reader.check_public_numeric(report, logits, inputs)
    report['rows'][0]['latent_sha256'] = '0'*64
    with pytest.raises(AssertionError): reader.check_input_bindings(report, logits, inputs, 1, reader.FIXED_FIXTURES[dimension][0])


@pytest.mark.parametrize('mutation', ['source', 'token', 'shape', 'modality', 'facet_offset', 'f64'])
def test_coordinated_numeric_or_input_mutation_is_refused(mutation):
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench/cached-span-native-compatibility-20261004-02'
    inputs = json.loads((namespace/'inputs.json').read_text())
    report = json.loads((namespace/'baseline_cpu_opt_out-1-report.json').read_text())
    logits = json.loads((namespace/'baseline_cpu_opt_out-1-four-logits.json').read_text())
    if mutation == 'source': report['rows'][0]['source_sha256'] = '0'*64
    elif mutation == 'token': report['rows'][0]['span_diagnostics']['tokens'][0]['start'] = 1
    elif mutation == 'shape': logits[0]['start'][0][0].pop()
    elif mutation == 'modality': logits[0]['modality'][0][0] += 1.
    elif mutation == 'facet_offset': report['rows'][0]['span_diagnostics']['facets']['actor']['char_start'] = 0
    else: logits[0]['presence'][0][0][0] = .1
    with pytest.raises((AssertionError, TypeError)):
        reader.check_input_bindings(report, logits, inputs, 1, reader.FIXED_FIXTURES[768][0])
        reader.check_public_numeric(report, logits, inputs)


@pytest.mark.parametrize('flag', ['proof_authority', 'native_leanstral_outputs_qualified', 'performance_qualified',
                                 'execution_attestation', 'fresh_encoder_execution_qualified'])
def test_nested_authority_cannot_upgrade_ordinary_comparisons(flag):
    with pytest.raises(AssertionError): reader.authority({'rows': [{'extra': {flag: True}}]})


def test_archive_requires_unique_canonical_panel_and_final_closed_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    root = tmp_path/'archive'; root.mkdir(); (root/'result.json').write_bytes(b'{}'); (root/'result.json').chmod(0o444)
    declarations = []
    for index in range(291):
        path = root/f'{index:03d}.json'; path.write_bytes(b'{}'); path.chmod(0o444)
        declarations.append(reader.pin(path, b'{}'))
    archive = reader.Archive(root, {'evidence_files_except_result': declarations,
        'evidence_bytes_except_result': 582}, b'{}')
    assert archive.use(declarations[0], '000.json') == {}
    with pytest.raises(AssertionError): archive.use(declarations[0], '001.json')
    with pytest.raises(AssertionError): archive.use(declarations[0], '000.json')
    with pytest.raises(AssertionError): archive.close()
    for index in range(1,291): archive.use(declarations[index], f'{index:03d}.json')
    archive.close()


@pytest.mark.parametrize('mutation', ['writeable', 'symlink', 'hardlink'])
def test_ordinary_reader_refuses_unowned_leaf_metadata(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    path = tmp_path/'record.json'; path.write_bytes(b'{}'); path.chmod(0o444)
    if mutation == 'writeable': path.chmod(0o644)
    elif mutation == 'symlink': target = tmp_path/'target'; path.rename(target); path.symlink_to(target)
    else: (tmp_path/'alias').hardlink_to(path)
    with pytest.raises(AssertionError): reader.read(path)


def test_structured_audit_refuses_malformed_or_wrong_external_result(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'ROOT', tmp_path)
    path = tmp_path/'result.json'; path.write_bytes(b'{"schema":"other"}'); path.chmod(0o444)
    refused = reader.audit(tmp_path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert refused['qualified'] is refused['closed_artifacts_consistent'] is False
    assert reader.audit(tmp_path, '0'*64)['qualified'] is False
    assert reader.audit(tmp_path, '0'*64, 1)['qualified'] is False


def test_reader_source_imports_and_supported_inventory_are_model_free():
    tree = ast.parse(SOURCE.read_text())
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(name and name.split('.')[0] in ('torch','numpy','ipfs_datasets_py') for name in imported)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('exec','eval','compile') for node in ast.walk(tree))
    assert len(reader.FIXED_SOURCES) == 33 and len(set(path for path,digest in reader.FIXED_SOURCES.values())) == 33
    assert all(len(digest) == 64 for path,digest in reader.FIXED_SOURCES.values())


@pytest.mark.parametrize('dimension', [768, 4096])
def test_currentness_receipts_join_independently_derived_checkpoint_bytes(dimension):
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench'/f'cached-span-native-compatibility-20261004-0{2 if dimension == 768 else 3}'
    checkpoint = json.loads((namespace/'checkpoint.json').read_text())
    anchor = reader.checkpoint_anchor(checkpoint, dimension)
    reader.check_tensor_receipts(old_profile(dimension, False), reader.FIXED_FIXTURES[dimension][0], anchor)
    reader.check_tensor_receipts(old_profile(dimension, True), reader.FIXED_FIXTURES[dimension][0], anchor)


@pytest.mark.parametrize('mutation', ['anchor_digest', 'byte_count', 'cpu_device', 'chunk_count', 'reduction_count', 'host_decisions', 'wrong_origin', 'missing_finite'])
def test_reference_and_value_receipt_mutations_cannot_stand_in_for_checkpoint(mutation):
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench/cached-span-native-compatibility-20261004-02'
    checkpoint = json.loads((namespace/'checkpoint.json').read_text())
    anchor = reader.checkpoint_anchor(checkpoint, 768)
    profile = old_profile(768, True)
    if mutation == 'anchor_digest': profile['reference_byte_currentness']['anchor_sha256'] = '0'*64
    elif mutation == 'byte_count': profile['reference_byte_currentness']['reference_bytes'] += 4
    elif mutation == 'cpu_device': profile['owned_tensor_currentness']['comparison_device'] = 'cpu'
    elif mutation == 'chunk_count': profile['owned_tensor_currentness']['comparison_chunk_elements'] = 1
    elif mutation == 'reduction_count': profile['owned_tensor_currentness']['comparison_reduction_scalars'] = True
    elif mutation == 'host_decisions': profile['owned_tensor_currentness']['host_decision_count'] = 92
    elif mutation == 'wrong_origin': profile['reference_byte_currentness']['origin'] = 'mutable_reference'
    else: profile['owned_tensor_currentness']['finite_values_checked'] = False
    with pytest.raises(AssertionError): reader.check_tensor_receipts(profile, reader.FIXED_FIXTURES[768][0], anchor)


@pytest.mark.parametrize('mutation', ['canonical_and_payload', 'missing_decoded_facet', 'missing_decoded_diagnostics', 'abstained_with_payload', 'display', 'minimum_margin', 'decoded_count'])
def test_coherent_public_decision_forgery_cannot_escape_numeric_and_copied_span_join(mutation):
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench/cached-span-native-compatibility-20261004-02'
    inputs = json.loads((namespace/'inputs.json').read_text())
    report = json.loads((namespace/'baseline_cpu_opt_out-1-report.json').read_text())
    logits = json.loads((namespace/'baseline_cpu_opt_out-1-four-logits.json').read_text())
    row = report['rows'][0]
    if mutation == 'canonical_and_payload':
        row['canonical_ir']['rules'][0]['actor'] = 'another actor'
        row['formal_outputs'][0]['payload']['actor'] = 'another actor'
    elif mutation == 'missing_decoded_facet': row['span_diagnostics']['facets'].pop('temporal')
    elif mutation == 'missing_decoded_diagnostics': row.pop('span_diagnostics')
    elif mutation == 'abstained_with_payload': row['status'] = 'abstained'
    elif mutation == 'display': row['formula_text'] = row['formal_outputs'][0]['formula_text'] = 'same forged display'
    elif mutation == 'minimum_margin': row['minimum_decision_logit_margin'] = 1.
    else: report['decoded_count'] = True
    with pytest.raises(AssertionError): reader.check_public_numeric(report, logits, inputs)


@pytest.mark.parametrize('placement', ['native_control', 'trial_metadata', 'count_metadata'])
def test_only_top_producer_byte_closure_can_be_qualified_true(placement):
    result = {'qualified': True, 'error': None, 'native_controls': [{'proof_authority': False}],
              'counts': {'1': {'trials': [{'metadata': {'proof_authority': False}}], 'performance_qualified': False}}}
    reader.result_authority(result)
    target = result['native_controls'][0] if placement == 'native_control' else (
        result['counts']['1']['trials'][0]['metadata'] if placement == 'trial_metadata' else result['counts']['1'])
    target['proof_authority'] = True
    with pytest.raises(AssertionError): reader.result_authority(result)
