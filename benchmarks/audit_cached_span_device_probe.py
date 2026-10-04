"""Ordinary byte/decision/four-logit audit; no retained Python or model runs."""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

ROOT = Path('/home/barberb/lift_coding')
MAX_FILE = 8*1024**2
OUTPUTS = ('modality', 'presence', 'start', 'end')
AUTHORITY_FALSE = frozenset(('qualified', 'admitted', 'formalized', 'roundtrip_ok', 'proof_authority',
    'semantic_correctness_verified', 'semantic_qualification', 'production_admission', 'production_qualified',
    'performance_qualified', 'execution_attestation', 'promotion_performed', 'publication_performed',
    'training_executed', 'target_access', 'teacher_forcing', 'kernel_resource_enforcement',
    'native_cuda_qualified', 'native_bitwise_session_cuda_qualified', 'bitwise_session_performance_qualified',
    'trusted_native_owner_verified', 'native_leanstral_encoder_available', 'native_leanstral_head_qualified',
    'native_leanstral_outputs_qualified', 'trained4096_qualification_established', 'existing_selected_route_changed',
    'source_semantics_verified', 'fresh_encoder_execution_qualified', 'native_encoder_origin_authenticated',
    'universal_speedup_claimed', 'foreign_process_actions', 'mutation_revision_authority', 'lake_executed'))


def _directory_fd(path):
    path = Path(path).absolute()
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            assert component not in ('.', '..')
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _parent_unchanged(path, descriptor, before):
    after = os.fstat(descriptor)
    following = _directory_fd(path)
    try:
        current = os.fstat(following)
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) == (current.st_dev, current.st_ino)
    finally:
        os.close(following)


def read(path, readonly=True):
    path = Path(path).absolute()
    assert path.resolve(strict=True) == path and path.is_relative_to(ROOT)
    parent = _directory_fd(path.parent)
    try:
        parent_before = os.fstat(parent)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_FILE
        assert not readonly or not before.st_mode & 0o222
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            assert (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
            raw = stream.read(MAX_FILE + 1)
            finished = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _parent_unchanged(path.parent, parent, parent_before)
    finally:
        os.close(parent)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink, s.st_mode)
    assert identity(before) == identity(opened) == identity(finished) == identity(after) and len(raw) == before.st_size
    return raw


def _inventory(root, max_files=1024):
    root = Path(root).absolute()
    assert type(max_files) is int and 1 <= max_files <= 1024
    assert root.resolve(strict=True) == root and root.is_relative_to(ROOT)
    descriptor = _directory_fd(root)
    try:
        before, names = os.fstat(descriptor), set()
        with os.scandir(descriptor) as entries:
            for entry in entries:
                assert len(names) < max_files
                name = entry.name
                assert type(name) is str and name not in ('.', '..') and '/' not in name and '\\' not in name
                assert name not in names
                names.add(name)
        _parent_unchanged(root, descriptor, before)
    finally:
        os.close(descriptor)
    return {str(root/name) for name in names}


def pin(path, raw):
    return {'path': str(Path(path).absolute()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def strict(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            assert key not in value
            value[key] = item
        return value
    def number(text):
        value = float(text)
        assert math.isfinite(value)
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_float=number,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('finite JSON required')))


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def authority(value, budget=None, depth=0):
    """Retained ordinary reports cannot acquire authority by agreement."""
    if budget is None: budget = [1000000]
    budget[0] -= 1
    assert budget[0] >= 0 and depth <= 64
    if type(value) is dict:
        for key, child in value.items():
            assert type(key) is str
            if key in AUTHORITY_FALSE: assert child is False
            authority(child, budget, depth+1)
    elif type(value) is list:
        for child in value: authority(child, budget, depth+1)
    else:
        assert type(value) in (type(None), bool, int, float, str)
        if type(value) is float: assert math.isfinite(value)


def check_forward_batches(batches, token_counts, *, dimension, cuda, device):
    assert type(dimension) is int and dimension in (768, 4096) and type(cuda) is bool
    assert type(token_counts) is list and 1 <= len(token_counts) <= 32
    assert all(type(value) is int and value > 0 for value in token_counts)
    assert type(batches) is list and len(batches) == (1 if cuda else len(token_counts))
    expected_tokens = [token_counts] if cuda else [[value] for value in token_counts]
    for forward, tokens in zip(batches, expected_tokens):
        authority(forward)
        assert type(forward['rows']) is int and forward['rows'] == len(tokens)
        assert type(forward['native_input_dimension']) is int and forward['native_input_dimension'] == dimension
        assert forward['input_device'] == device and forward['output_devices'] == dict.fromkeys(OUTPUTS, device)
        assert forward['output_dtype'] == 'float32' and forward['gru_executed'] is True
        assert wire(forward['source_tokens']) == wire(tokens)
        precision = forward['gru_precision']
        assert precision['device'] == device and precision['persistent_flags_mutated'] is False
        assert precision['scoped_cudnn'] is cuda
        if cuda:
            expected_profile = ('native-768-source-span-device-strict-cuda-float32/v2' if dimension == 768 else
                                'native-4096-source-span-strict-cuda-float32/v1')
            assert precision['profile_id'] == expected_profile
            assert precision['ambient_flags_restored'] is True and precision['synchronized_before_restore'] is True
            assert precision['requires_owned_process_without_unrelated_concurrent_cudnn'] is True
            ambient, effective = precision['ambient_policy'], precision['effective_policy']
            assert ambient['cuda_matmul_allow_tf32'] is False and ambient['float32_matmul_precision'] == 'highest'
            assert wire(effective) == wire({**ambient, 'cudnn': {**ambient['cudnn'], 'allow_tf32': False}})
            if dimension == 4096:
                assert precision['precision_scope_helper_profile_id'] == 'native-768-source-span-device-strict-cuda-float32/v2'
        else:
            assert precision['profile_id'] == ('native-768-source-span-device-float32/v1' if dimension == 768 else
                                              'native-4096-source-span-batched-device-float32-cpu-decisions/v2')
            if dimension == 4096:
                assert precision['precision_scope_helper_profile_id'] == 'native-768-source-span-device-float32/v1'


def _memory_bound(value):
    assert type(value) is dict and set(value) == {'gpu_working_set_bytes', 'host_working_set_bytes'}
    assert type(value['gpu_working_set_bytes']) is int and 0 < value['gpu_working_set_bytes'] <= 256*1024**2
    assert type(value['host_working_set_bytes']) is int and 0 < value['host_working_set_bytes'] <= 1024*1024**2


def check_execution_scope(report, scope, *, dimension, count, cuda, profile, inputs, candidate=False):
    """Join saved lane/public/private-forward claims without model replay."""
    assert type(count) is int and count in (1, 16, 32) and type(candidate) is bool
    authority(report); authority(scope); authority(profile)
    assert type(profile['dimension']) is int and profile['dimension'] == dimension
    assert profile['optimized'] is cuda and profile['dtype'] == 'float32' and profile['stored_checkpoint_device'] == 'cpu'
    device = profile['device']
    assert device == 'cpu' if not cuda else type(device) is str and re.fullmatch(r'cuda:(?:[0-9]|[1-5][0-9]|6[0-3])', device)
    base = ('native-768-source-span-batched-device-float32-cpu-decisions/v1' if dimension == 768 else
            'native-4096-source-span-batched-device-float32-cpu-decisions/v2')
    session = ('native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1' if dimension == 768 else
               'native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2')
    cached = f'native{dimension}-owned-bitwise-cached-input/v1'
    assert profile['profile_id'] == (cached if cuda and candidate else session if cuda else base)
    assert profile['session_profile_id'] == session and profile['inherited_profile_id'] == base
    assert profile['strict_cuda_gru_profile_id'] == ('native-768-source-span-device-strict-cuda-float32/v2' if dimension == 768 else
                                                    'native-4096-source-span-strict-cuda-float32/v1')
    assert profile['canonical_decision_device'] == ('resident_cpu' if dimension == 768 and not cuda else 'cpu')
    assert profile['numerical_batching'] == ('one_complete_valid_source_batch' if cuda else 'singleton_cpu_opt_out')
    policy = profile['precision_policy']
    assert policy['persistent_flags_mutated'] is False and policy['requires_owned_process_without_unrelated_concurrent_cudnn'] is cuda
    assert policy['cuda_gru_allow_tf32'] is (False if cuda else None)
    if candidate:
        assert profile['cached_input_profile_id'] == cached
        assert profile['inherited_cached_input_profile_id'] == (session if cuda else base)
    assert wire(report['execution_profile']) == wire(profile)
    assert report['cuda_executed'] is cuda and report['numerical_batching'] is cuda
    assert report['canonical_decision_device'] == 'cpu'
    assert report['checkpoint_sha256'] == profile['checkpoint_sha256']
    assert type(report['input_dimension']) is int and report['input_dimension'] == dimension
    assert report['schema'] == ('native-768-source-span-batched-device-inference/v1' if dimension == 768 else
                                'native-4096-source-span-device-inference/v1')
    for key in ('cpu_head_output_materializations', 'device_to_cpu_head_transfers'):
        assert type(report[key]) is int and report[key] == (4 if cuda else 0)
    if cuda or dimension == 4096:
        assert type(report['valid_source_count']) is int and report['valid_source_count'] == count
    token_counts = [len(list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))) for text in inputs['texts'][:count]]
    check_forward_batches(report['actual_forward_batches'], token_counts, dimension=dimension, cuda=cuda, device=device)
    if cuda:
        assert wire(report['actual_forward_batches'][0]['gru_precision']['ambient_policy']) == wire(policy['ambient_at_admission'])
    if 'batch_memory_bound' in report: _memory_bound(report['batch_memory_bound'])
    if dimension == 768:
        assert scope['scope'] == 'separate_checked_private_four_logit_forward_outside_public_timing'
        assert scope['coverage'] == 'one_snapshot_per_lane_per_count' and scope['entry_and_exit_owned_checks'] is True
        assert scope['singletons'] is (not cuda)
        _memory_bound(scope['batch_memory_bound'])
        observed = scope['observations']
    elif cuda:
        assert scope['scope'] == 'benchmark_only_checked_private_forward'
        assert scope['entry_and_exit_owned_session_checks'] is True and scope['public_cpu_opt_out_still_uses_singletons'] is True
        _memory_bound(scope['batch_memory_bound'])
        observed = scope['observations']
    else:
        assert scope['separate_checked_private_four_logits'] is True and scope['singletons'] is True
        assert type(scope['observations']) is list and len(scope['observations']) == count
        observed = []
        for singleton in scope['observations']:
            assert singleton['scope'] == 'benchmark_only_checked_private_forward'
            assert singleton['entry_and_exit_owned_session_checks'] is True and singleton['public_cpu_opt_out_still_uses_singletons'] is True
            _memory_bound(singleton['batch_memory_bound'])
            assert type(singleton['observations']) is list and len(singleton['observations']) == 1
            observed.extend(singleton['observations'])
    check_forward_batches(observed, token_counts, dimension=dimension, cuda=cuda, device=device)
    if cuda: assert wire(report['batch_memory_bound']) == wire(scope['batch_memory_bound'])


def marker(value):
    assert value is None or type(value) is float and math.isfinite(value)
    return None if value is None else {'known_finite_numeric_diagnostic_value_excluded': True}


def decisions(value):
    value = deepcopy(value)
    for key in ('execution_profile', 'actual_forward_batches', 'cuda_executed', 'numerical_batching',
        'batch_memory_bound', 'cpu_head_output_materializations', 'device_to_cpu_head_transfers',
        'canonical_decision_device', 'valid_source_count'):
        value.pop(key, None)
    for row in value['rows']:
        if 'minimum_decision_logit_margin' in row: row['minimum_decision_logit_margin'] = marker(row['minimum_decision_logit_margin'])
        diagnostics = row.get('span_diagnostics')
        if diagnostics is None: continue
        if 'modality_logits' in diagnostics:
            assert len(diagnostics['modality_logits']) == 3
            diagnostics['modality_logits'] = [marker(item) for item in diagnostics['modality_logits']]
        for facet in diagnostics['facets'].values():
            for key in ('presence_logit_margin', 'span_logit_margin'):
                if key in facet: facet[key] = marker(facet[key])
    return value


def shape(value):
    if type(value) is list:
        assert value
        children = [shape(item) for item in value]
        assert all(item == children[0] for item in children)
        return (len(value),)+children[0]
    assert type(value) is float and math.isfinite(value)
    return ()


def error(left, right):
    if type(left) is list:
        assert type(right) is list and len(left) == len(right) and left
        return max(error(a, b) for a, b in zip(left, right))
    assert type(left) is type(right) is float and math.isfinite(left) and math.isfinite(right)
    return abs(left-right)


def check_input_bindings(report, logits, inputs, count, checkpoint_sha256):
    assert type(count) is int and count in (1, 16, 32)
    assert type(report['rows']) is list and type(logits) is list
    assert len(report['rows']) == len(logits) == count
    assert report['checkpoint_sha256'] == checkpoint_sha256
    assert report['input_dimension'] == inputs['dimension']
    for row, values, text, vector in zip(report['rows'], logits, inputs['texts'], inputs['vectors']):
        assert row['source_sha256'] == hashlib.sha256(text.encode('utf-8')).hexdigest()
        assert row['latent_sha256'] == hashlib.sha256(wire(vector)).hexdigest()
        tokens = list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))
        assert tokens and set(values) == set(OUTPUTS)
        assert shape(values['modality']) == (1, 3)
        assert shape(values['presence']) == (1, 4, 2)
        assert shape(values['start']) == shape(values['end']) == (1, 6, len(tokens))
        diagnostics = row.get('span_diagnostics')
        if diagnostics is not None:
            assert diagnostics['tokens'] == [{'text': token.group(), 'start': token.start(), 'end': token.end()} for token in tokens]


def review(namespace, expected, check_current_sources=True):
    root = Path(namespace).absolute()
    raw = read(root/'result.json'); result_pin = pin(root/'result.json', raw)
    assert result_pin['sha256'] == expected
    result = strict(raw)
    assert result['schema'] == 'cached-span-native-compatibility-probe/v1' and result['qualified'] is True and result['error'] is None
    assert type(result['dimension']) is int and result['dimension'] in (768, 4096)
    assert all(result[key] is False for key in ('performance_qualified', 'proof_authority', 'execution_attestation',
        'production_qualified', 'selected_existing_profile_changed', 'native_leanstral_outputs_qualified',
        'trained4096_qualification_established', 'encoder_execution_performed', 'shared_configuration_changed'))
    assert all(type(result[key]) is int and result[key] == 12 for key in ('public_return_count', 'complete_four_logit_snapshot_count'))
    assert result['numeric_tolerance_absolute'] == 5e-5
    assert result['actual_cuda_execution'] is True and result['hardware']['actual_initial_cuda_kernel'] is True
    assert result['safe_owned_cleanup_established'] is True and result['root_release_observed'] is True
    assert 0 < result['elapsed_seconds_after_admission'] <= 120
    for key in ('optimizer_constructor_calls', 'optimizer_steps', 'new_training_fits', 'training_mode_true_calls'):
        assert type(result[key]) is int and result[key] == 0
    retained = {}
    for declared in result['evidence_files_except_result']:
        assert set(declared) == {'path', 'bytes', 'sha256'} and type(declared['bytes']) is int
        path = Path(declared['path']); assert path.parent == root and path.name != 'result.json' and str(path) not in retained
        assert pin(path, read(path)) == declared
        retained[str(path)] = declared
    actual = _inventory(root)
    assert actual == set(retained)|{str(root/'result.json')}
    assert len(actual) == 58 and sum(item['bytes'] for item in retained.values()) == result['evidence_bytes_except_result']
    assert sum(item['bytes'] for item in retained.values())+len(raw) <= 64*1024**2
    def value(declared):
        assert retained.get(declared['path']) == declared
        return strict(read(declared['path']))
    current = []
    sources = {item['role']: item for item in result['source_pins']}
    assert len(sources) == len(result['source_pins']) == 30
    assert sources['resource_scheduler']['current']['sha256'] == 'f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa'
    assert sources['legal_span_cached_input_device_inference']['current']['sha256'] == 'ec07cb2d502c0e1aedbdb3c11d29348fbddf438982dfbab4c07368a85391eb70'
    assert sources['input_content_guard']['current']['sha256'] == 'aa3fefbe8a1ab4d81bf61ae9edf395a9070b3c0f94b728ee6fa5ddca0c81c325'
    assert sources['dimension_helpers']['current']['sha256'] == result['dimension_helper_source_sha256'] == 'c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0'
    for item in [*result['source_pins'], result['shared_configuration'], *result['fixture_pins']]:
        assert retained.get(item['retained_copy']['path']) == item['retained_copy']
        assert item['current']['sha256'] == item['retained_copy']['sha256'] and item['current']['bytes'] == item['retained_copy']['bytes']
        if check_current_sources:
            assert pin(item['current']['path'], read(item['current']['path'], readonly=False)) == item['current']
            current.append(item['current'])
    assert result['shared_configuration']['current']['sha256'] == 'c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575'
    fixtures = {item['role']: item for item in result['fixture_pins']}
    cp, inputs = value(fixtures['checkpoint']['retained_copy']), value(fixtures['inputs']['retained_copy'])
    expected_cp = ('9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b' if result['dimension'] == 768 else
                   '04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7')
    expected_inputs = ('1b29ffd8b62d628aa8d6823f5e5a2b702a710357add2f4337b6243b7ca117090' if result['dimension'] == 768 else
                       '2c4e4ac0053871c902c5aebb423ee2ccd1345fa46ad6c28234a45b10eaada388')
    assert fixtures['checkpoint']['current']['sha256'] == result['checkpoint_sha256'] == expected_cp
    assert fixtures['inputs']['current']['sha256'] == expected_inputs
    assert cp['progress'] == result['retained_progress'] and cp['progress']['optimizer_steps'] == (1 if result['dimension'] == 768 else 0)
    assert result['expected_model_pin'] == {'bytes': len(wire(cp['model_state'])), 'sha256': hashlib.sha256(wire(cp['model_state'])).hexdigest()}
    assert len(inputs['texts']) == len(inputs['vectors']) == 32 and inputs['dimension'] == result['dimension']
    assert set(result['lanes']) == {'baseline_cpu_opt_out', 'candidate_cpu_opt_out', 'baseline_cuda', 'candidate_cuda'}
    numeric, canonical, maximum_errors = {}, {}, dict.fromkeys(OUTPUTS, 0.)
    for label in ('baseline_cpu_opt_out', 'candidate_cpu_opt_out', 'baseline_cuda', 'candidate_cuda'):
        lane = result['lanes'][label]
        assert lane['state_before'] == lane['state_after'] == result['expected_model_pin']
        assert set(lane['counts']) == {'1', '16', '32'}
        if label.startswith('candidate'):
            implementation = lane['profile']['cached_input_implementation']
            assert implementation['source_sha256'] == sources['legal_span_cached_input_device_inference']['current']['sha256']
            assert all(implementation[key] is False for key in ('performance_qualified', 'production_qualified', 'proof_authority', 'execution_attestation', 'existing_selected_route_changed'))
        for count in (1, 16, 32):
            entry = lane['counts'][str(count)]; report, logits = value(entry['report']), value(entry['four_logits'])
            check_input_bindings(report, logits, inputs, count, expected_cp)
            check_execution_scope(report, entry['four_logit_scope'], dimension=result['dimension'], count=count,
                cuda=label.endswith('_cuda'), profile=lane['profile'], inputs=inputs, candidate=label.startswith('candidate'))
            assert report['cuda_executed'] is label.endswith('_cuda')
            if label == 'baseline_cpu_opt_out': canonical[count], numeric[count] = decisions(report), logits
            assert decisions(report) == canonical[count]
            assert entry['complete_decisions_match_original_CPU'] is entry['cpu_cuda_rng_unchanged'] is True
            errors = {}
            for name in OUTPUTS:
                assert all(set(row) == set(OUTPUTS) for row in logits)
                errors[name] = max(error(left[name], right[name]) for left, right in zip(numeric[count], logits))
                assert errors[name] <= 5e-5
                assert all(shape(row[name]) == shape(ref[name]) for row, ref in zip(logits, numeric[count]))
                maximum_errors[name] = max(maximum_errors[name], errors[name])
            assert errors == entry['four_logit_max_abs_errors']
            elapsed = entry['unprofiled_cuda_elapsed_seconds']
            assert (type(elapsed) is float and 0 < elapsed < 120) if label.endswith('_cuda') else elapsed is None
    assert len(result['owned_children']) == 4 and all(item['release_observed'] is True for item in result['owned_children'])
    resources = result['resources_after']
    assert resources['allocated'] == {'cpu_slots': 0, 'memory_mb': 0} and all(type(item) is int for item in resources['allocated'].values())
    assert all(type(resources[key]) is int and resources[key] == 0 for key in ('active_lease_count', 'active_root_lease_count',
        'active_child_lease_count', 'allocated_gpu_memory_mb', 'allocated_unified_memory_mb', 'allocated_child_process_slots', 'waiting_request_count'))
    assert type(result['gpu_allocated_after_framework_workspace_clear_bytes']) is int and result['gpu_allocated_after_framework_workspace_clear_bytes'] == 0
    assert type(result['gpu_peak_allocated_bytes']) is int and 0 <= result['gpu_peak_allocated_bytes'] <= 512*1024**2
    assert result['current_sources_fixtures_configuration_unchanged'] is True
    assert pin(root/'result.json', read(root/'result.json')) == result_pin
    return {'schema': 'cached-span-native-probe-ordinary-review/v1', 'qualified': True, 'closed_artifacts_consistent': True,
        'error': None, 'result_pin': result_pin, 'expected_result_sha256': expected, 'dimension': result['dimension'],
        'retained_pins': [result_pin, *retained.values()], 'bounded_archive_files': len(actual),
        'bounded_archive_bytes': sum(item['bytes'] for item in retained.values())+len(raw),
        'current_sources_verified': check_current_sources, 'check_current_sources': check_current_sources,
        'current_source_pins': current, 'public_reports': 12, 'complete_four_logit_snapshots': 12,
        'recomputed_four_logit_max_abs_errors': maximum_errors, 'recurrent_model_replayed': False,
        'retained_python_executed': False, 'tensor_library_imported': False, 'model_executed': False,
        'performance_qualified': False, 'execution_attestation': False, 'proof_authority': False, 'production_qualified': False,
        'native_leanstral_outputs_qualified': False, 'trained4096_qualification_established': False}


def audit(root, expected_result_sha256, *, check_current_sources=False):
    try: return review(root, expected_result_sha256, check_current_sources)
    except BaseException as error:
        return {'qualified': False, 'closed_artifacts_consistent': False, 'error': {'type': type(error).__name__, 'message': str(error)}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--expected-result-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    result = audit(args.root, args.expected_result_sha256, check_current_sources=True)
    with args.output.open('xb') as stream: stream.write(wire(result))
    args.output.chmod(0o444)
    print(json.dumps({'qualified': result['qualified'], 'error': result['error']}))
    raise SystemExit(0 if result['qualified'] else 1)
