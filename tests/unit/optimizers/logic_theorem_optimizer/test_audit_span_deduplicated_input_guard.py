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

SOURCE = Path(__file__).resolve().parents[4] / 'benchmarks/audit_span_deduplicated_input_guard.py'
SPEC = importlib.util.spec_from_file_location('_ordinary_span_deduplicated_input_reader', SOURCE)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


def trials():
    result = []
    for index, order in enumerate(reader.ORDER_SCHEDULE):
        seconds = {reader.CUDA_LANES[0]: float(index+1), reader.CUDA_LANES[1]: float(12-index), reader.CUDA_LANES[2]: 6.5}
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
    assert summary['median_baseline_over_whole_input_ratio'] == 1.
    assert statistics.median(summary['paired_baseline_over_whole_input_ratios']) != 1.
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


@pytest.mark.parametrize('field', ['samples_seconds', 'median_seconds', 'median_baseline_over_whole_input_ratio',
    'paired_baseline_over_whole_input_ratios', 'paired_baseline_over_whole_input_min_ratio', 'paired_baseline_over_whole_input_max_ratio',
    'median_baseline_over_deduplicated_ratio', 'paired_baseline_over_deduplicated_ratios',
    'paired_baseline_over_deduplicated_min_ratio', 'paired_baseline_over_deduplicated_max_ratio',
    'median_whole_input_over_deduplicated_ratio', 'paired_whole_input_over_deduplicated_ratios',
    'paired_whole_input_over_deduplicated_min_ratio', 'paired_whole_input_over_deduplicated_max_ratio'])
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


def test_three_child_envelope_charges_exact_root_reservation():
    value = {'allocated': {'cpu_slots': 3, 'memory_mb': 3072}, 'active_lease_count': 4,
        'active_root_lease_count': 1, 'active_child_lease_count': 3, 'allocated_gpu_memory_mb': 768,
        'allocated_unified_memory_mb': 3840, 'allocated_child_process_slots': 0, 'waiting_request_count': 0}
    reader._live_resources(value)
    value['allocated']['cpu_slots'] = 1
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










def old_profile(dimension, cuda):
    # Read retained ordinary JSON only; fixture is historical data, not executable code.
    namespace = reader.ROOT/'artifacts/codebase_ir_terminal_bench'/f'cached-span-native-compatibility-20261004-0{2 if dimension == 768 else 3}'
    data = json.loads((namespace/'result.json').read_text())
    return deepcopy(data['lanes']['baseline_cuda' if cuda else 'baseline_cpu_opt_out']['profile'])








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
    for index in range(292):
        path = root/f'{index:03d}.json'; path.write_bytes(b'{}'); path.chmod(0o444)
        declarations.append(reader.pin(path, b'{}'))
    archive = reader.Archive(root, {'evidence_files_except_result': declarations,
        'evidence_bytes_except_result': 584}, b'{}')
    assert archive.use(declarations[0], '000.json') == {}
    with pytest.raises(AssertionError): archive.use(declarations[0], '001.json')
    with pytest.raises(AssertionError): archive.use(declarations[0], '000.json')
    with pytest.raises(AssertionError): archive.close()
    for index in range(1,292): archive.use(declarations[index], f'{index:03d}.json')
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
    assert len(reader.FIXED_SOURCES) == 34 and len(set(path for path,digest in reader.FIXED_SOURCES.values())) == 34
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


def whole_profile(dimension, cuda, *, public=False, route="whole_input"):
    profile = old_profile(dimension, cuda); parent = profile['profile_id']
    candidate = f'native-{dimension}-owned-bitwise-' + ('deduplicated-' if route == 'deduplicated' else '') + 'whole-call-input/v1'
    profile.update(whole_input_guard_inherited_profile_id=parent,
        whole_input_guard_profile_id=candidate, session_profile_id=candidate,
        whole_input_guard_implementation=reader._whole_input_implementation(route))
    if cuda: profile['profile_id'] = candidate
    if public: profile['whole_input_guard_currentness'] = deepcopy(reader.WHOLE_INPUT_CURRENTNESS)
    return profile


@pytest.mark.parametrize('dimension,cuda,route', itertools.product((768,4096),(False,True),('whole_input','deduplicated')))
def test_whole_guard_capability_and_actual_public_receipts_are_independently_bound(dimension, cuda, route):
    ctor = reader._parent_profile(whole_profile(dimension,cuda,route=route),dimension,cuda,route)
    public = reader._parent_profile(whole_profile(dimension,cuda,public=True,route=route),dimension,cuda,route,public=True)
    assert reader.wire(ctor) == reader.wire(public) == reader.wire(old_profile(dimension,cuda))


def test_generic_description_cannot_claim_a_completed_public_input_check():
    with pytest.raises(AssertionError): reader._parent_profile(whole_profile(768,True,public=True),768,True,'whole_input')
    with pytest.raises(KeyError): reader._parent_profile(whole_profile(768,True),768,True,'whole_input',public=True)


@pytest.mark.parametrize('mutation', ['wrong_parent', 'wrong_owner', 'wrong_helper', 'wrong_adaptation',
    'unchecked_root', 'unchecked_nested', 'scalar_walk', 'fast_int_alias', 'wrong_scope', 'canonical_digest', 'proof'])
def test_whole_guard_receipt_cannot_substitute_source_snapshot_or_scope(mutation):
    profile = whole_profile(768,True,public=True)
    implementation, current = profile['whole_input_guard_implementation'], profile['whole_input_guard_currentness']
    if mutation == 'wrong_parent': profile['whole_input_guard_inherited_profile_id'] = 'other'
    elif mutation == 'wrong_owner': implementation['source_sha256'] = '0'*64
    elif mutation == 'wrong_helper': implementation['input_guard_implementation']['source_sha256'] = '0'*64
    elif mutation == 'wrong_adaptation': implementation['source_bound_decode_adaptations'][0]['adapted_method_ast_sha256'] = '0'*64
    elif mutation == 'unchecked_root': current['guard_object_and_immutable_snapshot_identities_checked'] = False
    elif mutation == 'unchecked_nested': current['nested_reference_wrapper_field_identities_checked'] = False
    elif mutation == 'scalar_walk': current['atom_array_scalar_reference_nodes_traversed'] = True
    elif mutation == 'fast_int_alias': current['fast_comparison'] = 1
    elif mutation == 'wrong_scope': current['scope'] = 'whole_job_integrity_proven'
    elif mutation == 'canonical_digest': current['standard_finite_input_snapshot_canonical_json_serialized'] = True
    else: current['proof_authority'] = True
    with pytest.raises(AssertionError): reader._parent_profile(profile,768,True,'whole_input',public=True)


def native_controls(dimension=768):
    resources = {'allocated': {'cpu_slots': 3, 'memory_mb': 3072}, 'active_lease_count': 4,
        'active_root_lease_count': 1, 'active_child_lease_count': 3, 'allocated_gpu_memory_mb': 768,
        'allocated_unified_memory_mb': 3840, 'allocated_child_process_slots': 0, 'waiting_request_count': 0}
    records = []
    schedule = [(route,control) for route in ('whole_input_cuda','deduplicated_cuda') for control in reader.NATIVE_CONTROL_SCHEDULE[:-1]]
    schedule += [(route,reader.NATIVE_CONTROL_SCHEDULE[-1]) for route in ('whole_input_cuda','deduplicated_cuda')]
    for route,control in schedule:
        row = {'control':control,'route':route,'refused':True,'proof_authority':False,'execution_attestation':False}
        if control == 'actual_owned_child_cancel_after_measurements':
            row.update(actual_model_forward_calls=0,before_forward_refusal=True,post_forward_callback_executed=False,
                refusal='768D device lease revoked or expired' if dimension == 768 else 'native4096 device lease revoked or expired',
                child_cancel_requested=True,released_before_close=False,owned_child_lease_id=route+'-child',
                resources_after_cancel_before_close=deepcopy(resources),
                scope='actual_owned_child_only_revocation_after_all_public_measurements_and_state_joins')
        else:
            replacement = control in ('paired_input_guard_reference_after_forward','valid_input_guard_snapshot_after_forward',
                                       'paired_input_guard_nested_array_after_forward')
            row.update(actual_model_forward_calls=1,before_forward_refusal=False,post_forward_callback_executed=True,
                refusal='checkpoint content changed' if control in reader.NATIVE_CONTROL_SCHEDULE[:2] else
                        'whole-input independent local guard or immutable snapshot changed',
                fresh_input_guard_constructor_observed=True,input_guard_constructor_calls=2 if replacement else 1,
                input_guard_constructor_source_role='input_content_guard',
                input_guard_constructor_source_sha256=reader.FIXED_SOURCES['input_content_guard'][1],
                input_guard_constructor_method='InputContentGuard.__init__',
                original_input_guard_snapshot_identities_restored=True,replacement_guard_current_content_matches=True if replacement else None,
                original_nested_reference_wrapper_identities_restored=True if control == 'paired_input_guard_nested_array_after_forward' else None,
                cpu_cuda_rng_unchanged=True,
                scope='source_bound_local_input_guard_and_actual_caller_aliases_after_observed_forward_only')
        records.append(row)
    return records


@pytest.mark.parametrize('dimension',[768,4096])
def test_actual_guard_alias_and_revocation_controls_join_exact_local_custody_scope(dimension):
    reader._native_controls({'native_controls':native_controls(dimension)},dimension,{'whole_input_cuda':{'lease_id':'whole_input_cuda-child'},'deduplicated_cuda':{'lease_id':'deduplicated_cuda-child'}})


def test_original_4096_cancel_literal_cannot_be_replaced_by_cadence_literal():
    records = native_controls(4096); records[-1]['refusal'] = '4096D device lease revoked or expired'
    with pytest.raises(AssertionError): reader._native_controls({'native_controls':records},4096,{'whole_input_cuda':{'lease_id':'whole_input_cuda-child'},'deduplicated_cuda':{'lease_id':'deduplicated_cuda-child'}})


@pytest.mark.parametrize('field,value', [('actual_model_forward_calls',0),('input_guard_constructor_calls',True),
    ('fresh_input_guard_constructor_observed',False),('input_guard_constructor_source_sha256','0'*64),
    ('original_input_guard_snapshot_identities_restored',False),('cpu_cuda_rng_unchanged',False),('scope','timed_or_background')])
def test_native_post_forward_control_cannot_forge_constructor_or_restoration(field,value):
    records = native_controls(); records[0][field] = value
    with pytest.raises(AssertionError): reader._native_controls({'native_controls':records},768,{'whole_input_cuda':{'lease_id':'whole_input_cuda-child'},'deduplicated_cuda':{'lease_id':'deduplicated_cuda-child'}})


def test_paired_nested_reference_control_requires_complete_restoration():
    records = native_controls(); records[6]['original_nested_reference_wrapper_identities_restored'] = None
    with pytest.raises(AssertionError): reader._native_controls({'native_controls':records},768,{'whole_input_cuda':{'lease_id':'whole_input_cuda-child'},'deduplicated_cuda':{'lease_id':'deduplicated_cuda-child'}})


@pytest.mark.parametrize('mutation', ['other_route_controls', 'cancel_lease_alias', 'missing_dedup_nested_control'])
def test_candidate_control_panels_cannot_be_reused_across_route_custody(mutation):
    records = native_controls()
    if mutation == 'other_route_controls':
        for row in records[7:14]: row['route'] = 'whole_input_cuda'
    elif mutation == 'cancel_lease_alias': records[-1]['owned_child_lease_id'] = 'whole_input_cuda-child'
    else: records[13]['control'] = 'valid_input_guard_snapshot_after_forward'
    with pytest.raises(AssertionError): reader._native_controls({'native_controls':records},768,
        {'whole_input_cuda':{'lease_id':'whole_input_cuda-child'},'deduplicated_cuda':{'lease_id':'deduplicated_cuda-child'}})


@pytest.mark.parametrize('field,value', [('original_record_count',92),('checked_record_count',98),
    ('removed_duplicate_record_count',True),('original_distinct_key_count',98),('checked_distinct_key_count',98),
    ('key_policy','equal_code_objects'),('first_record_preserved',False),('wrapped_binding_inventory_deduplicated',True),
    ('freshness_success_cached',True),('keyset_and_order_admission_scope','cached_revision_authority')])
def test_deduplicated_descriptor_cannot_drop_distinct_bindings_or_bless_success_cache(field,value):
    profile = whole_profile(4096,True,public=True,route='deduplicated')
    profile['whole_input_guard_implementation']['binding_inventory_deduplication'][field] = value
    with pytest.raises(AssertionError): reader._parent_profile(profile,4096,True,'deduplicated',public=True)


def inventory_sources():
    # Checked current source bytes are ordinary AST input, never imported here.
    return {role: Path(reader.FIXED_SOURCES[role][0]).read_bytes() for role in reader.BINDING_SOURCE_ROLES}


def test_declared_inventory_is_independently_reconstructed_without_retained_execution():
    actual = reader._binding_inventory_from_sources(inventory_sources())
    assert actual == reader.DEDUP_BINDING_POLICY
    assert actual['original_record_count'] == 98 and actual['checked_record_count'] == 92
    assert actual['removed_duplicate_record_count'] == 6 and actual['wrapped_binding_inventory_deduplicated'] is False


@pytest.mark.parametrize('mutation', ['missing_source', 'wrong_source_bytes', 'wrong_frozen_flag', 'bool_int_alias', 'missing_infer_alias'])
def test_inventory_ast_refuses_missing_sources_and_unsupported_declared_generation(monkeypatch, mutation):
    sources = inventory_sources()
    if mutation == 'missing_source':
        sources.pop(reader.BINDING_SOURCE_ROLES[0])
    elif mutation == 'wrong_source_bytes':
        sources[reader.BINDING_SOURCE_ROLES[0]] += b'\n'
    else:
        role = reader.BINDING_SOURCE_ROLES[0] if mutation != 'missing_infer_alias' else 'legal_span_device_inference'
        raw = sources[role]
        if mutation == 'wrong_frozen_flag': raw = raw.replace(b'frozen=True, slots=True',b'frozen=False, slots=True')
        elif mutation == 'bool_int_alias': raw = raw.replace(b'frozen=True, slots=True',b'frozen=1, slots=True')
        else: raw = raw.replace(b'infer = decode_formal_logic',b'infer = missing_method')
        assert raw != sources[role]
        sources[role] = raw
        fixed = dict(reader.FIXED_SOURCES); fixed[role] = (fixed[role][0],hashlib.sha256(raw).hexdigest())
        monkeypatch.setattr(reader,'FIXED_SOURCES',fixed)
    with pytest.raises(AssertionError):
        assert reader._binding_inventory_from_sources(sources) == reader.DEDUP_BINDING_POLICY
