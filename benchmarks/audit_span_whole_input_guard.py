"""Close two-route whole-call input guard span observations as ordinary data only.

Vetted no-follow reads, JSON/input/execution checks are retained in this new
source. No retained Python, tensor library, model or scheduler executes.
Balanced complete-call measurements remain separate from production authority.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import itertools
import statistics
import struct
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
SCHEMA = 'span-whole-input-guard-qualification/v1'
AUDIT_SCHEMA = 'span-whole-input-guard-archive-review/v1'
ROUTES = ('baseline', 'whole_input')
CUDA_LANES = tuple(route + '_cuda' for route in ROUTES)
CPU_LANES = tuple(route + '_cpu_opt_out' for route in ROUTES)
ORDER_SCHEDULE = tuple(tuple(order) for order in itertools.permutations(CUDA_LANES)) * 6
EVIDENCE_LIMITS = {'max_files': 1024, 'max_file_bytes': 8 * 1024**2,
                   'max_total_bytes': 64 * 1024**2, 'result_included_in_limits': True}
FIXED_FIXTURES = {
    768: ('9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b',
          '1b29ffd8b62d628aa8d6823f5e5a2b702a710357add2f4337b6243b7ca117090'),
    4096: ('04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7',
           '2c4e4ac0053871c902c5aebb423ee2ccd1345fa46ad6c28234a45b10eaada388')}
CONFIG_SHA256 = 'c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575'


def pin_shape(value):
    assert type(value) is dict and set(value) == {'path', 'bytes', 'sha256'}
    assert type(value['path']) is str and '\x00' not in value['path']
    path = Path(value['path'])
    assert path.is_absolute() and str(path) == value['path'] and '..' not in path.parts and path.is_relative_to(ROOT)
    assert type(value['bytes']) is int and 0 < value['bytes'] <= MAX_FILE
    assert type(value['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', value['sha256'])
    return value


def _finite_seconds(value):
    assert type(value) is float and math.isfinite(value) and 0 < value <= 120
    return value


def _float32(value):
    assert type(value) is float and math.isfinite(value)
    packed = struct.pack('<f', value)
    assert struct.unpack('<f', packed)[0] == value
    return packed


def _f32_tree(value):
    if type(value) is list:
        assert value
        for item in value: _f32_tree(item)
    else:
        _float32(value)


def checkpoint_anchor(checkpoint, dimension):
    """Independently derive immutable logical f32 bytes; never restore a model."""
    config, state = checkpoint['config'], checkpoint['model_state']
    assert type(config['latent_dimension']) is int and config['latent_dimension'] == dimension
    assert config['device'] == 'cpu' and config['dtype'] == 'float32'
    assert type(state) is dict and 1 <= len(state) <= 4096
    digest, byte_count, largest, layouts = hashlib.sha256(), 0, 0, []
    for name in sorted(state):
        assert type(name) is str and 0 < len(name) <= 1024
        dimensions = shape(state[name])
        count = math.prod(dimensions)
        assert type(count) is int and count > 0
        pending = [state[name]]
        while pending:
            value = pending.pop()
            if type(value) is list:
                pending.extend(reversed(value))
            else:
                digest.update(_float32(value)); byte_count += 4
                assert byte_count <= 64 * 1024**2
        largest = max(largest, count)
        layouts.append((name, dimensions, count))
    return {'anchor_sha256': digest.hexdigest(), 'reference_bytes': byte_count,
            'tensor_count': len(layouts), 'largest_tensor_elements': largest, 'layouts': layouts}


def check_tensor_receipts(profile, checkpoint_sha256, anchor):
    """Join every lane's reference/value receipts to the fixed CP bytes."""
    device, cuda = profile['device'], profile['optimized']
    assert type(cuda) is bool
    reference, comparison = profile['reference_byte_currentness'], profile['owned_tensor_currentness']
    authority(reference); authority(comparison)
    dimension = profile['dimension']
    assert reference['schema'] == f'native-{dimension}-owned-reference-byte-currentness/v1'
    assert reference['origin'] == ('independently_restored_validated_cpu_checkpoint_model_before_upload' if dimension == 768 else
                                   'independently_restored_validated_cpu_checkpoint_model')
    assert reference['checkpoint_sha256'] == checkpoint_sha256
    assert reference['anchor_sha256'] == anchor['anchor_sha256']
    assert type(reference['reference_bytes']) is int and reference['reference_bytes'] == anchor['reference_bytes']
    assert reference['reference_device'] == device
    assert reference['comparison'] == 'complete_immutable_float32_bytes_including_signed_zero'
    assert reference['anchor_identity_checked'] is reference['metadata_and_reservation_checked_before_allocation'] is True
    assert type(reference['device_to_cpu_reference_transfers']) is int and reference['device_to_cpu_reference_transfers'] == int(cuda)
    assert type(reference['cpu_byte_materializations']) is int and reference['cpu_byte_materializations'] == 1
    assert comparison['schema'] == 'owned-tensor-bitwise-value-guard/v1'
    assert comparison['comparison_device'] == device
    assert type(comparison['tensor_count']) is int and comparison['tensor_count'] == anchor['tensor_count']
    assert type(comparison['state_and_reference_bytes']) is int and comparison['state_and_reference_bytes'] == 2 * anchor['reference_bytes']
    assert all(comparison[name] is True for name in ('all_current_values_checked', 'finite_values_checked', 'signed_zero_checked'))
    assert comparison['mode'] == ('cuda_bitwise_single_host_decision' if cuda else 'cpu_reference_checks')
    assert comparison['cuda_integer_view_equality'] is comparison['cuda_current_finiteness_implied_by_reference_bits'] is cuda
    assert type(comparison['host_decision_count']) is int and comparison['host_decision_count'] == (1 if cuda else 4 * anchor['tensor_count'])
    _plain_count(comparison['comparison_chunk_elements'], anchor['largest_tensor_elements'])
    _plain_count(comparison['comparison_reduction_scalars'], anchor['tensor_count'] if cuda else 0)
    _plain_count(comparison['comparison_temporary_bound_bytes'], anchor['largest_tensor_elements'] * 8 + anchor['tensor_count'] * 4)
    assert comparison['autocast_configuration_consulted'] is False
    assert comparison['implementation'] == {'schema': 'owned-tensor-bitwise-guard-implementation/v1',
        'source_sha256': '6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34',
        'comparison': 'finite-float32-exact-bits-with-reference-finiteness/v1'}


def paired_summaries(trials):
    """Recompute exact balanced order, route samples, and paired ratios."""
    assert type(trials) is list and len(trials) == 12
    samples = {lane: [] for lane in CUDA_LANES}
    positions = {lane: dict.fromkeys(('first', 'second'), 0) for lane in CUDA_LANES}
    for index, (trial, order) in enumerate(zip(trials, ORDER_SCHEDULE)):
        assert type(trial) is dict and type(trial['trial']) is int and trial['trial'] == index
        assert type(trial['order']) is list and tuple(trial['order']) == order
        assert type(trial['observations']) is dict and set(trial['observations']) == set(CUDA_LANES)
        for position, lane in enumerate(order):
            value = trial['observations'][lane]['unprofiled_cuda_elapsed_seconds']
            samples[lane].append(_finite_seconds(value))
            positions[lane][('first', 'second')[position]] += 1
    assert all(value == {'first': 6, 'second': 6} for value in positions.values())
    result = {'samples_seconds': samples,
              'median_seconds': {lane: statistics.median(values) for lane, values in samples.items()}}
    ratios = [left / right for left, right in zip(samples[CUDA_LANES[0]], samples[CUDA_LANES[1]])]
    result['paired_baseline_over_whole_input_ratios'] = ratios
    result['median_baseline_over_whole_input_ratio'] = result['median_seconds'][CUDA_LANES[0]] / result['median_seconds'][CUDA_LANES[1]]
    result['paired_baseline_over_whole_input_min_ratio'] = min(ratios)
    result['paired_baseline_over_whole_input_max_ratio'] = max(ratios)
    return result, positions


def check_timing_entry(entry, raw):
    assert type(raw) is dict and set(raw) == {'trials', 'samples_seconds', 'median_seconds'}
    assert wire(raw['trials']) == wire(entry['trials'])
    recomputed, positions = paired_summaries(entry['trials'])
    for field, value in recomputed.items():
        assert wire(entry[field]) == wire(value)
    for field in ('samples_seconds', 'median_seconds'):
        assert wire(raw[field]) == wire(recomputed[field])
    return recomputed, positions


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


def result_authority(value):
    # Only the producer envelope can assert successful byte/numeric closure.
    # Every nested qualified/proof/performance flag retains the false policy.
    assert type(value) is dict and value['qualified'] is True and value['error'] is None
    authority({key: child for key, child in value.items() if key != 'qualified'})


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


def _check_parent_execution_scope(report, scope, *, dimension, count, cuda, profile, inputs, candidate=False):
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



# Immutable supported algorithm inventory; all copies remain ordinary data.
FIXED_SOURCES = {'resource_scheduler': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py', 'f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa'), 'legal_span_formula': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_formula.py', '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'), 'legal_span_dimensions': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_dimensions.py', '5ba50db7475c23d7376c0918a02a3740783dc86996e396f532c365f544372b7d'), 'legal_span_device_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_device_inference.py', '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5'), 'legal_span_device_batch_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_device_batch_inference.py', '5c916e7ab3b52f908731a6bab5dce83a31a7b6ad269445281c89ecd5cee07133'), 'legal_span_device_bitwise_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_device_bitwise_inference.py', 'd1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91'), 'legal_span_4096': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_4096.py', 'c488d2aa11b0dbf6e1da76a06cb6360e55396026a8d496316479568168561e92'), 'legal_span_4096_device_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_4096_device_inference.py', '658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8'), 'legal_span_4096_bitwise_device_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_4096_bitwise_device_inference.py', '90d2a06081b4391216fb63cc82968b0c8ea1ff8138d564448281b5e3b2b88595'), 'legal_span_4096_bitwise_device_inference_v2': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_4096_bitwise_device_inference_v2.py', '14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3'), 'legal_span_cached_input_device_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_cached_input_device_inference.py', 'ec07cb2d502c0e1aedbdb3c11d29348fbddf438982dfbab4c07368a85391eb70'), 'input_content_guard': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/input_content_guard.py', 'aa3fefbe8a1ab4d81bf61ae9edf395a9070b3c0f94b728ee6fa5ddca0c81c325'), 'owned_tensor_value_guard': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/owned_tensor_value_guard.py', 'c07a55647317f541307a8d8e1024add78072bfaf53b04030862412e915d7adc5'), 'owned_tensor_bitwise_guard': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/owned_tensor_bitwise_guard.py', '6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34'), 'checkpoint_content_guard': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/checkpoint_content_guard.py', '5461672516b4a60938b036d558192e8db328fdd00d20cda76b7448dea09c706c'), 'runtime_telemetry': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py', '542f705867b93fcb138a117e1f5c97a144ad6635dc92c37bc5034eee5065ef63'), 'proof_resource_safety': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py', '16a24648b5625f9abb379cf3c4a189e9b05e3c32cc7d1f6812e7c94b475ae921'), 'legal_formula_codec': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py', 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290'), 'legal_ir_grammar_decoder': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py', '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd'), 'legal_ir_family_evaluator': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_family_evaluator.py', '3b6cd3a6fade78fed275a478f010329e5d030a250b914c4b46ab0f0d77b9d5ab'), 'snapshot_evaluator': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/snapshot_evaluator.py', '1aa122f14dc52a4a5cb161bc2c40862334f7b216210bfcdb42fd5989b69761e6'), 'legal_span_whole_input_guard_device_inference': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_whole_input_guard_device_inference.py', '398611f204ce27194d6a0c5b739ad13d1387feeb626d250995ac97de42d17b20'), 'benchmark': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/qualify_span_whole_input_guard.py', '454110e3fee76e2ac0b27c05989edbc677e95f94d6962e5ba3a807aaa2c798c0'), 'trained_helpers': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/qualify_bitwise_trained_head_devices.py', '29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110'), 'dimension_helpers': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/profile_dimension_guard_costs_v6.py', 'c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0'), 'coordinator_helpers': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/qualify_formula_guard_coordinator.py', 'e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8'), 'cleanup_helper': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/qualify_native_768_device.py', '73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c'), 'synthetic_helpers': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/qualify_synthetic_4096_head_device_v2.py', 'a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36'), 'compatibility_probe_helpers': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/probe_cached_span_device_candidate_v2.py', '4a5e5a6c633f20c6886bbeecdf9bbc45b23c5c784d8fd5d55543acb18932ecc5'), 'comparison_helpers': ('/home/barberb/lift_coding/external/ipfs_datasets/benchmarks/qualify_span_inference_candidates.py', 'a558fd42438f4471268d7d7c8f87f62ca0024570001c59bf3f5736328ff22258'), 'tree_pin': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/logic/autoformal/tree_pin.py', '587165942fb06ea9effc836b555e0ac0606c5876b013a374a1e76d25ee069e4d'), 'canonical_contracts': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/logic/legal_ir/canonical_contracts.py', 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b'), 'cid_utils': ('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/utils/cid_utils.py', '190fa0c6958b212d3c7b55dec9c92056c9b73259da6d8e576c4f5b70928cc1bf')}
PARENT_IMPLEMENTATIONS = {768: {'batched_implementation': {'native_checkpoint_producers': {'native_checkpoint_producers': {'base_span': {'canonical': 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b', 'codec': 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290', 'grammar': '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd', 'span': '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'}, 'dimensions_sha256': '5ba50db7475c23d7376c0918a02a3740783dc86996e396f532c365f544372b7d'}, 'source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5'}, 'resident_source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5', 'source_sha256': '5c916e7ab3b52f908731a6bab5dce83a31a7b6ad269445281c89ecd5cee07133'}, 'bitwise_session_implementation': {'bitwise_guard_implementation': {'comparison': 'finite-float32-exact-bits-with-reference-finiteness/v1', 'schema': 'owned-tensor-bitwise-guard-implementation/v1', 'source_sha256': '6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34'}, 'boundary_consolidation_performed': False, 'inherited_batched_implementation': {'native_checkpoint_producers': {'native_checkpoint_producers': {'base_span': {'canonical': 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b', 'codec': 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290', 'grammar': '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd', 'span': '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'}, 'dimensions_sha256': '5ba50db7475c23d7376c0918a02a3740783dc86996e396f532c365f544372b7d'}, 'source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5'}, 'resident_source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5', 'source_sha256': '5c916e7ab3b52f908731a6bab5dce83a31a7b6ad269445281c89ecd5cee07133'}, 'native_cuda_qualified': False, 'performance_qualified': False, 'production_admission': False, 'proof_authority': False, 'schema': 'native-768-bitwise-checkpoint-anchor-session-implementation/v1', 'source_sha256': 'd1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91', 'source_verification_success_cached': False}, 'implementation': {'native_checkpoint_producers': {'base_span': {'canonical': 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b', 'codec': 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290', 'grammar': '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd', 'span': '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'}, 'dimensions_sha256': '5ba50db7475c23d7376c0918a02a3740783dc86996e396f532c365f544372b7d'}, 'source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5'}}, 4096: {'implementation': {'bitwise_guard_implementation': {'comparison': 'finite-float32-exact-bits-with-reference-finiteness/v1', 'schema': 'owned-tensor-bitwise-guard-implementation/v1', 'source_sha256': '6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34'}, 'bitwise_guard_source_sha256': '6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34', 'boundary_consolidation_performed': False, 'duplicate_transitive_verification_in_pure_check': False, 'inherited_methods_identity_checked': ['__init__', '_poll', '_pure_check', '_check', '_policy', '_lease_binding', '_reference_byte_plan', '_reference_state_bytes', '_check_reference_anchor', '_operation', 'checkpoint', 'describe', '_description', '_admit_batch_memory', '_decision', 'decode_formal_logic', 'infer', '_synchronize', 'close', '__enter__', '__exit__'], 'inherited_session_implementation': {'native4096_checkpoint_producer': {'base_span': {'canonical': 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b', 'codec': 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290', 'grammar': '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd', 'span': '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'}, 'native4096_sha256': 'c488d2aa11b0dbf6e1da76a06cb6360e55396026a8d496316479568168561e92'}, 'owned_tensor_value_guard_sha256': 'c07a55647317f541307a8d8e1024add78072bfaf53b04030862412e915d7adc5', 'reused_cpu_decision_cache_primitives': {'native_checkpoint_producers': {'native_checkpoint_producers': {'base_span': {'canonical': 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b', 'codec': 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290', 'grammar': '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd', 'span': '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'}, 'dimensions_sha256': '5ba50db7475c23d7376c0918a02a3740783dc86996e396f532c365f544372b7d'}, 'source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5'}, 'resident_source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5', 'source_sha256': '5c916e7ab3b52f908731a6bab5dce83a31a7b6ad269445281c89ecd5cee07133'}, 'reused_precision_tensor_primitives': {'native_checkpoint_producers': {'base_span': {'canonical': 'd66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b', 'codec': 'f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290', 'grammar': '0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd', 'span': '60e509fc5018584d19530dd6f9b8423f163cb7baec60f5736d849995bca61185'}, 'dimensions_sha256': '5ba50db7475c23d7376c0918a02a3740783dc86996e396f532c365f544372b7d'}, 'source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5'}, 'source_sha256': '658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8'}, 'inherited_session_source_sha256': '658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8', 'native_cuda_qualified': False, 'original_public_source_verification': 'inherited_check_before_pure_check', 'performance_qualified': False, 'production_admission': False, 'proof_authority': False, 'schema': 'native-4096-bitwise-device-session-implementation/v2', 'source_sha256': '14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3', 'source_verification_success_cached': False}}}
CACHE_IMPLEMENTATION = {'change_scope': 'request_local_cached_row_binding_only_unused_digest', 'checkpoint_and_receipt_digests_retained': True, 'execution_attestation': False, 'existing_selected_route_changed': False, 'inherited_numerical_cache_checks_retained': True, 'input_guard_implementation': {'atom_array_snapshot_per_scalar_freeze': False, 'comparison': 'immutable-input-structural-content-with-canonical-json-fallback/v1', 'current_content_fully_compared': True, 'dictionary_order_ignored': True, 'exact_builtin_atom_types': True, 'finite_float_required': True, 'list_tuple_equivalence': True, 'schema': 'input-content-guard-implementation/v1', 'signed_zero_checked': True, 'source_and_callable_bindings_checked': True, 'source_sha256': 'aa3fefbe8a1ab4d81bf61ae9edf395a9070b3c0f94b728ee6fa5ddca0c81c325', 'standard_path_canonical_json_serialized': False, 'standard_path_digest_computed': False, 'success_or_revision_cached': False}, 'native_leanstral_outputs_qualified': False, 'performance_qualified': False, 'production_qualified': False, 'proof_authority': False, 'schema': 'native-span-cached-input-implementation/v1', 'source_sha256': 'ec07cb2d502c0e1aedbdb3c11d29348fbddf438982dfbab4c07368a85391eb70', 'source_verification_success_cached': False}
FIXTURE_PATHS = {768: ('native-768-device-qualification-20261004-04/diagnostic-native768-head.json', 'dimension-768-guard-cost-profile-20261004-03/dimension-inference-inputs.json'), 4096: ('native-4096-synthetic-head-device-v2-qualification-20261004-04/synthetic-untrained-checkpoint.json', 'dimension-4096-guard-cost-profile-20261004-04/dimension-inference-inputs.json')}


def _plain_count(value, expected=None, maximum=1000000):
    assert type(value) is int and 0 <= value <= maximum
    if expected is not None: assert value == expected
    return value


def _zero_resources(value):
    assert type(value) is dict and type(value['allocated']) is dict
    assert set(value['allocated']) == {'cpu_slots', 'memory_mb'}
    for count in value['allocated'].values(): _plain_count(count, 0)
    for key in ('active_lease_count', 'active_root_lease_count', 'active_child_lease_count',
                'allocated_gpu_memory_mb', 'allocated_unified_memory_mb',
                'allocated_child_process_slots', 'waiting_request_count'):
        _plain_count(value[key], 0)


def _live_resources(value):
    assert type(value['allocated']) is dict and set(value['allocated']) == {'cpu_slots', 'memory_mb'}
    _plain_count(value['allocated']['cpu_slots'], 2); _plain_count(value['allocated']['memory_mb'], 2048)
    for key, expected in (('active_lease_count', 3), ('active_root_lease_count', 1),
                          ('active_child_lease_count', 2), ('allocated_gpu_memory_mb', 512),
                          ('allocated_unified_memory_mb', 2560), ('allocated_child_process_slots', 0),
                          ('waiting_request_count', 0)):
        _plain_count(value[key], expected)








def _parent_profile(profile, dimension, cuda, route, *, public=False):
    authority(profile)
    assert route in ROUTES and type(cuda) is type(public) is bool
    normalized = deepcopy(profile)
    if route == 'whole_input':
        parent = ('native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1' if dimension == 768 else
                  'native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2') if cuda else (
                  'native-768-source-span-batched-device-float32-cpu-decisions/v1' if dimension == 768 else
                  'native-4096-source-span-batched-device-float32-cpu-decisions/v2')
        candidate = f'native-{dimension}-owned-bitwise-whole-call-input/v1'
        assert profile['whole_input_guard_inherited_profile_id'] == parent
        assert profile['whole_input_guard_profile_id'] == profile['session_profile_id'] == candidate
        assert profile['profile_id'] == (candidate if cuda else parent)
        assert wire(profile['whole_input_guard_implementation']) == wire(_whole_input_implementation())
        if public:
            assert wire(profile['whole_input_guard_currentness']) == wire(WHOLE_INPUT_CURRENTNESS)
            normalized.pop('whole_input_guard_currentness')
        else:
            assert 'whole_input_guard_currentness' not in profile
        for name in ('whole_input_guard_inherited_profile_id', 'whole_input_guard_profile_id', 'whole_input_guard_implementation'):
            normalized.pop(name)
        normalized['profile_id'] = parent
        normalized['session_profile_id'] = ('native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1' if dimension == 768 else
                                           'native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2')
    else:
        assert 'whole_input_guard_implementation' not in profile and 'whole_input_guard_currentness' not in profile
    for name, expected in PARENT_IMPLEMENTATIONS[dimension].items():
        assert wire(profile[name]) == wire(expected)
    return normalized


def check_execution_scope(report, scope, *, dimension, count, cuda, profile, inputs, route):
    # Validate independently before reducing the candidate IDs to the unchanged
    # inherited scope. The saved public receipt must identify this same owner.
    expected = _parent_profile(profile, dimension, cuda, route)
    actual = _parent_profile(report['execution_profile'], dimension, cuda, route, public=True)
    assert wire(actual) == wire(expected)
    normalized_report = deepcopy(report); normalized_report['execution_profile'] = actual
    _check_parent_execution_scope(normalized_report, scope, dimension=dimension, count=count, cuda=cuda,
                                  profile=expected, inputs=inputs, candidate=False)


def _rounded32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def check_public_numeric(report, logits, inputs):
    """Join exposed decisions/offsets to saved numeric scores, no model replay."""
    fields = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
    optional = ('object', 'conditions', 'exceptions', 'temporal')
    for row, values, text in zip(report['rows'], logits, inputs['texts']):
        _f32_tree(list(values.values()))
        assert row['status'] in ('decoded', 'abstained')
        diagnostics = row.get('span_diagnostics')
        if row['status'] == 'decoded':
            assert type(diagnostics) is dict
        else:
            assert row['canonical_ir'] is row['formula_text'] is None and row['formal_outputs'] == []
        if diagnostics is None: continue
        modality = values['modality'][0]
        assert error(diagnostics['modality_logits'], modality) <= 5e-5
        rank = sorted(range(3), key=lambda index: (-modality[index], index))
        margins = [_rounded32(modality[rank[0]] - modality[rank[1]])]
        if row['canonical_ir'] is not None:
            assert row['canonical_ir']['rules'][0]['modality'] == ('O', 'P', 'F')[rank[0]]
        tokens = list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))
        facets = diagnostics['facets']; assert type(facets) is dict and set(facets) <= set(fields)
        for field, facet in facets.items():
            index = fields.index(field)
            present = True
            if field in optional:
                scores = values['presence'][0][optional.index(field)]
                present = scores[1] > scores[0]
                presence_margin = abs(_rounded32(scores[1] - scores[0]))
                margins.append(presence_margin)
                assert abs(facet['presence_logit_margin'] - presence_margin) <= 5e-5
            assert facet['present'] is present
            if not present:
                assert all(facet[key] is None for key in ('token_start', 'token_end_inclusive', 'char_start', 'char_end', 'text', 'span_logit_margin'))
                continue
            pairs = [(left, right) for left in range(len(tokens)) for right in range(left, len(tokens))]
            sums = [_rounded32(values['start'][0][index][left] + values['end'][0][index][right]) for left, right in pairs]
            ranking = sorted(range(len(sums)), key=lambda i: (-sums[i], i))
            left, right = pairs[ranking[0]]
            for key, expected in (('token_start', left), ('token_end_inclusive', right),
                                   ('char_start', tokens[left].start()), ('char_end', tokens[right].end())):
                assert type(facet[key]) is int and facet[key] == expected
            assert facet['text'] == text[tokens[left].start():tokens[right].end()]
            margin = _rounded32(sums[ranking[0]] - sums[ranking[1]]) if len(sums) > 1 else None
            assert facet['span_logit_margin'] is None if margin is None else abs(facet['span_logit_margin'] - margin) <= 5e-5
            if margin is not None: margins.append(margin)
        if row['status'] == 'decoded':
            assert set(facets) == set(fields)
            rule = {'modality': ('O', 'P', 'F')[rank[0]]}
            for field in fields:
                facet = facets[field]
                atom = facet['text'] if facet['present'] else ''
                rule[field] = ([atom] if facet['present'] else []) if field in ('conditions', 'exceptions', 'temporal') else atom
            assert wire(row['canonical_ir']) == wire({'rules': [rule]})
            assert type(row['formal_outputs']) is list and len(row['formal_outputs']) == 1
            formal = row['formal_outputs'][0]
            assert wire(formal['payload']) == wire(rule)
            display = json.dumps({'rules': [rule]}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            assert row['formula_text'] == formal['formula_text'] == display
            assert formal['family'] == 'deontic' and formal['format'] == 'typed-deontic-rule/v1'
            assert formal['origin'] == 'learned_source_span_formula_decoder'
            assert type(row['minimum_decision_logit_margin']) is float and math.isfinite(row['minimum_decision_logit_margin'])
            assert abs(row['minimum_decision_logit_margin'] - min(margins)) <= 5e-5
    decoded = sum(row['status'] == 'decoded' for row in report['rows'])
    _plain_count(report['decoded_count'], decoded)
    assert report['status'] == ('decoded' if decoded == len(report['rows']) else 'partial' if decoded else 'abstained')


class Archive:
    def __init__(self, root, result, raw):
        self.root, self.pins, self.used, self.bytes = root, {}, set(), len(raw)
        declared = result['evidence_files_except_result']
        assert type(declared) is list and len(declared) == 207
        for item in declared:
            pin_shape(item); path = Path(item['path'])
            assert path.parent == root and path.name != 'result.json' and item['path'] not in self.pins
            self.bytes += item['bytes']; assert self.bytes <= EVIDENCE_LIMITS['max_total_bytes']
            self.pins[item['path']] = item
        _plain_count(result['evidence_bytes_except_result'], self.bytes-len(raw), maximum=EVIDENCE_LIMITS['max_total_bytes'])
        assert _inventory(root) == set(self.pins) | {str(root/'result.json')}
        for item in self.pins.values(): assert pin(item['path'], read(item['path'])) == item

    def use(self, declared, filename, *, json_value=True):
        pin_shape(declared)
        path = str(self.root/filename)
        assert declared['path'] == path and self.pins.get(path) == declared and path not in self.used
        self.used.add(path)
        raw = read(path); assert pin(path, raw) == declared
        return strict(raw) if json_value else raw

    def close(self):
        assert self.used == set(self.pins)
        for item in self.pins.values(): assert pin(item['path'], read(item['path'])) == item
        assert _inventory(self.root) == self.used | {str(self.root/'result.json')}


def _sources(archive, result, dimension, current_check):
    sources = result['source_pins']
    assert type(sources) is list and len(sources) == len(FIXED_SOURCES) == 33
    current = []
    for index, (item, (role, (path, digest))) in enumerate(zip(sources, FIXED_SOURCES.items())):
        assert set(item) == {'role', 'current', 'retained_copy'} and item['role'] == role
        pin_shape(item['current']); pin_shape(item['retained_copy'])
        assert item['current']['path'] == path and item['current']['sha256'] == digest
        assert item['current']['bytes'] == item['retained_copy']['bytes']
        raw = archive.use(item['retained_copy'], f'{index:02d}-{Path(path).name}', json_value=False)
        assert hashlib.sha256(raw).hexdigest() == digest
        if current_check:
            assert pin(path, read(path, readonly=False)) == item['current']; current.append(item['current'])
    config = result['shared_configuration']
    assert config['role'] == 'configuration'
    assert config['current']['path'] == str(ROOT/'artifacts/codebase_ir_terminal_bench/successor-expansion-resources-20261003-01/configuration.json')
    assert config['current']['sha256'] == CONFIG_SHA256
    entries = [config]
    fixtures = result['fixture_pins']
    assert type(fixtures) is list and len(fixtures) == 2
    cp, inputs = None, None
    for item, role, filename, relative, digest in zip(fixtures, ('checkpoint', 'inputs'), ('checkpoint.json', 'inputs.json'),
                                                  FIXTURE_PATHS[dimension], FIXED_FIXTURES[dimension]):
        assert set(item) == {'role', 'current', 'retained_copy'} and item['role'] == role
        assert item['current']['path'] == str(ROOT/'artifacts/codebase_ir_terminal_bench'/relative)
        assert item['current']['sha256'] == digest
        entries.append(item)
        value = archive.use(item['retained_copy'], filename)
        if role == 'checkpoint': cp = value
        else: inputs = value
    for item in entries:
        pin_shape(item['current']); pin_shape(item['retained_copy'])
        assert item['current']['sha256'] == item['retained_copy']['sha256'] and item['current']['bytes'] == item['retained_copy']['bytes']
        if current_check:
            assert pin(item['current']['path'], read(item['current']['path'], readonly=False)) == item['current']
            current.append(item['current'])
    configuration = archive.use(config['retained_copy'], 'configuration.json')
    assert configuration['lease_ttl_seconds'] == 120 and configuration['auto_renew_leases'] is True
    return cp, inputs, current


def _inputs(inputs, dimension):
    assert type(inputs['dimension']) is int and inputs['dimension'] == dimension
    assert type(inputs['texts']) is type(inputs['vectors']) is list and len(inputs['texts']) == len(inputs['vectors']) == 32
    for text, vector in zip(inputs['texts'], inputs['vectors']):
        assert type(text) is str and 0 < len(text) <= 4096 and 1 <= len(re.findall(r'\w+|[^\w\s]', text, re.UNICODE)) <= 64
        assert type(vector) is list and len(vector) == dimension
        for value in vector:
            assert type(value) is float and math.isfinite(value) and math.isfinite(struct.unpack('<f', struct.pack('<f', value))[0])
    if dimension == 768:
        assert type(inputs['receipts']) is type(inputs['receipt_pins']) is list and len(inputs['receipts']) == len(inputs['receipt_pins']) == 32
        for receipt, digest in zip(inputs['receipts'], inputs['receipt_pins']):
            assert type(digest) is str and digest == hashlib.sha256(wire(receipt)).hexdigest()


def _lease(value, *, pid, parent, cuda, root=False):
    assert type(value['lease_id']) is str and re.fullmatch(r'[0-9a-f]{32}', value['lease_id'])
    _plain_count(value['owner_pid'], pid, maximum=2**31)
    assert value['parent_lease_id'] == parent and value['lane'] == 'snapshot_evaluation'
    assert value['released'] is value['cancelled'] is False and value['requires_gpu'] is cuda
    for key, expected in (('cpu_slots', 2 if root else 1), ('memory_mb', 2048 if root else 1024),
        ('gpu_memory_mb', 512 if root else 256 if cuda else 0), ('unified_memory_mb', 2560 if root else 1280 if cuda else 0),
        ('child_process_slots', 0)):
        _plain_count(value[key], expected)
    assert type(value['acquired_at']) is float and math.isfinite(value['acquired_at']) and value['acquired_at'] > 0
    assert type(value['wait_seconds']) is float and math.isfinite(value['wait_seconds']) and value['wait_seconds'] >= 0


def _constructors(result, dimension):
    records = result['constructor_observations']
    assert type(records) is list and len(records) == 4
    children = result['owned_children']; assert type(children) is list and len(children) == 4
    assert [row['lane'] for row in children] == list(CPU_LANES+CUDA_LANES)
    assert len({row['admission']['lease_id'] for row in children}) == 4
    parent = result['admission']; _lease(parent, pid=result['pid'], parent=None, cuda=True, root=True)
    admissions = {}
    for label, receipt, child in zip(CPU_LANES+CUDA_LANES, records, children):
        assert child['release_observed'] is True
        _lease(child['admission'], pid=result['pid'], parent=parent['lease_id'], cuda=label.endswith('_cuda'))
        admissions[label] = child['admission']
        assert receipt['route'] == label and type(receipt['dimension']) is int and receipt['dimension'] == dimension
        assert receipt['checkpoint_sha256'] == result['checkpoint_sha256']
        assert receipt['started'] is receipt['completed'] is receipt['profile_restored'] is True
        _plain_count(receipt['native_restore_attempts'], 1); _plain_count(receipt['native_restore_completions'], 1)
        assert receipt['source_role'] == ('legal_span_device_inference' if dimension == 768 else 'legal_span_4096')
        assert receipt['method'] == ('_restore' if dimension == 768 else '_restore_for_inference')
        assert receipt['observation_scope'] == 'source_bound_native_model_restore_during_constructor_only'
        assert wire(result['lanes'][label]['constructor']) == wire(receipt)
    return admissions


def _native_controls(result, dimension, admissions):
    controls = result['native_controls']
    assert type(controls) is list and len(controls) == len(NATIVE_CONTROL_SCHEDULE)
    for row, expected in zip(controls, NATIVE_CONTROL_SCHEDULE):
        authority(row)
        assert row['control'] == expected and row['route'] == 'whole_input_cuda' and row['refused'] is True
        assert type(row['refusal']) is str and row['refusal']
        calls = _plain_count(row['actual_model_forward_calls'], maximum=1024)
        if expected == 'actual_owned_child_cancel_after_measurements':
            assert calls == 0 and row['before_forward_refusal'] is True and row['post_forward_callback_executed'] is False
            assert row['refusal'] == ('768D device lease revoked or expired' if dimension == 768
                                      else 'native4096 device lease revoked or expired')
            assert row['child_cancel_requested'] is True and row['released_before_close'] is False
            assert row['owned_child_lease_id'] == admissions['whole_input_cuda']['lease_id']
            _live_resources(row['resources_after_cancel_before_close'])
            assert row['scope'] == 'actual_owned_child_only_revocation_after_all_public_measurements_and_state_joins'
        else:
            assert row['original_input_guard_snapshot_identities_restored'] is row['cpu_cuda_rng_unchanged'] is True
            assert row['fresh_input_guard_constructor_observed'] is True
            replacement = expected in ('paired_input_guard_reference_after_forward', 'valid_input_guard_snapshot_after_forward',
                                       'paired_input_guard_nested_array_after_forward')
            _plain_count(row['input_guard_constructor_calls'], 2 if replacement else 1)
            assert row['input_guard_constructor_source_role'] == 'input_content_guard'
            assert row['input_guard_constructor_source_sha256'] == FIXED_SOURCES['input_content_guard'][1]
            assert row['input_guard_constructor_method'] == 'InputContentGuard.__init__'
            assert row['replacement_guard_current_content_matches'] is (True if replacement else None)
            assert row['original_nested_reference_wrapper_identities_restored'] is (True if expected == 'paired_input_guard_nested_array_after_forward' else None)
            assert row['refusal'] == ('checkpoint content changed' if expected in NATIVE_CONTROL_SCHEDULE[:2] else
                                      'whole-input independent local guard or immutable snapshot changed')
            assert row['scope'] == 'source_bound_local_input_guard_and_actual_caller_aliases_after_observed_forward_only'
            assert calls > 0 and row['post_forward_callback_executed'] is True and row['before_forward_refusal'] is False


def review(root, expected_result_sha256, check_current_sources=False):
    assert type(check_current_sources) is bool
    assert type(expected_result_sha256) is str and re.fullmatch(r'[0-9a-f]{64}', expected_result_sha256)
    root = Path(root).absolute()
    raw = read(root/'result.json'); result_pin = pin(root/'result.json', raw)
    assert result_pin['sha256'] == expected_result_sha256
    result = strict(raw)
    assert result['schema'] == SCHEMA and result['qualified'] is True and result['error'] is None
    result_authority(result)
    dimension, cohort = result['dimension'], result['cohort']
    assert type(dimension) is int and dimension in FIXED_FIXTURES and type(cohort) is str and cohort in ('A', 'B')
    assert all(result[key] is False for key in ('performance_qualified', 'proof_authority', 'execution_attestation',
        'production_qualified', 'selected_existing_profile_changed', 'native_leanstral_outputs_qualified',
        'trained4096_qualification_established', 'encoder_execution_performed', 'shared_configuration_changed',
        'native_due_renewal_qualified', 'native_lease_expiry_qualified'))
    _plain_count(result['public_return_count'], 84); _plain_count(result['complete_four_logit_snapshot_count'], 84)
    _plain_count(result['timed_return_count'], 72)
    assert type(result['numeric_tolerance_absolute']) is float and result['numeric_tolerance_absolute'] == 5e-5
    assert result['evidence_limits'] == EVIDENCE_LIMITS and all(type(result['evidence_limits'][key]) is int for key in ('max_files', 'max_file_bytes', 'max_total_bytes'))
    assert result['evidence_limits']['result_included_in_limits'] is True
    _plain_count(result['max_seconds_after_admission'], 120)
    assert type(result['admission_timeout_seconds']) is int and 1 <= result['admission_timeout_seconds'] <= 60
    _plain_count(result['paired_samples_per_route_per_count'], 12)
    assert type(result['elapsed_seconds_after_admission']) is float and 0 < result['elapsed_seconds_after_admission'] <= 120
    assert result['actual_cuda_execution'] is result['hardware']['actual_initial_cuda_kernel'] is True
    _plain_count(result['hardware']['device_index'], maximum=63)
    assert result['safe_owned_cleanup_established'] is result['root_release_observed'] is result['current_sources_fixtures_configuration_unchanged'] is True
    for key in ('optimizer_constructor_calls', 'optimizer_steps', 'new_training_fits', 'training_mode_true_calls'):
        _plain_count(result[key], 0)
    _plain_count(result['native_model_restore_attempts'], 4); _plain_count(result['native_model_restore_completions'], 4)
    for key in ('gpu_allocated_before_producer_imports_bytes', 'gpu_allocated_before_owned_sessions_bytes',
                'gpu_allocated_after_framework_workspace_clear_bytes'):
        _plain_count(result[key], 0)
    _plain_count(result['gpu_peak_allocated_bytes'], maximum=512*1024**2)
    _zero_resources(result['resources_before']); _zero_resources(result['resources_after'])
    assert wire(result['ambient_reserved']) == wire({**result['ambient_before'], 'num_threads': 1})
    assert wire(result['ambient_after_owned_cleanup_before_restore']) == wire(result['ambient_reserved'])
    assert wire(result['ambient_after_thread_restore']) == wire(result['ambient_before'])
    assert result['ambient_reserved']['default_dtype'] == 'torch.float32' and result['ambient_reserved']['default_device'] == 'cpu'
    assert result['ambient_reserved']['cuda_matmul_allow_tf32'] is False and result['ambient_reserved']['float32_matmul_precision'] == 'highest'
    assert result['ambient_reserved']['autocast_cpu_enabled'] is result['ambient_reserved']['autocast_cuda_enabled'] is False
    for key, expected in {
        'timing_scope': 'complete_guarded_public_call_and_completion_sync_input_copy_before_interval_no_profiler',
        'span_numeric_scope': 'one_separate_complete_checked_four_logit_snapshot_after_every_public_return_outside_timing',
        'counter_scope': 'constructors_CPU_references_CUDA_warmups_controls_and_separate_numeric_only_not_timed_CUDA',
        'baseline_lease_poll_scope': 'already_read_only_cancellation_poll_no_inline_renewal_elimination_claim',
        'historical_receipt_scope': 'retained_content_pin_only_no_new_encoder_or_signature_execution'}.items():
        assert result[key] == expected
    archive = Archive(root, result, raw)
    cp, inputs, current = _sources(archive, result, dimension, check_current_sources)
    _inputs(inputs, dimension)
    assert wire(result['physical_input_limits']) == wire({'rows': 32, 'source_characters_each': 4096, 'source_tokens_each': 64,
        'latent_width': dimension, 'checked_before_admission': True, 'no_source_or_latent_truncation': True})
    authority(result['constructor_observations'])
    native_implementation = (PARENT_IMPLEMENTATIONS[dimension]['implementation']['native_checkpoint_producers'] if dimension == 768 else
                             PARENT_IMPLEMENTATIONS[dimension]['implementation']['inherited_session_implementation']['native4096_checkpoint_producer'])
    assert wire(cp['implementation']) == wire(native_implementation)
    assert wire(cp['progress']) == wire(result['retained_progress'])
    _plain_count(cp['progress']['optimizer_steps'], 1 if dimension == 768 else 0)
    assert result['checkpoint_sha256'] == FIXED_FIXTURES[dimension][0]
    model_wire = wire(cp['model_state'])
    assert result['expected_model_pin'] == {'bytes': len(model_wire), 'sha256': hashlib.sha256(model_wire).hexdigest()}
    anchor = checkpoint_anchor(cp, dimension)
    assert set(result['lanes']) == set(CPU_LANES+CUDA_LANES) and set(result['counts']) == {'1', '16', '32'}
    admissions = _constructors(result, dimension)
    live = result['two_way_admission']
    assert live['both_gpu_children_live'] is True and set(live['child_leases']) == set(CUDA_LANES)
    for label in CUDA_LANES: assert wire(live['child_leases'][label]) == wire(admissions[label])
    _live_resources(live['resources'])
    canonical, numeric = {}, {}
    maximum_errors = dict.fromkeys(OUTPUTS, 0.)
    public_count = 0

    def observe(label, count, entry, stem, timed):
        nonlocal public_count
        cuda, route = label.endswith('_cuda'), label.removesuffix('_cuda').removesuffix('_cpu_opt_out')
        authority(entry)
        report = archive.use(entry['report'], stem+'-report.json')
        logits = archive.use(entry['four_logits'], stem+'-four-logits.json')
        authority(report); authority(logits)
        check_input_bindings(report, logits, inputs, count, result['checkpoint_sha256'])
        check_public_numeric(report, logits, inputs)
        check_execution_scope(report, entry['four_logit_scope'], dimension=dimension, count=count,
            cuda=cuda, profile=result['lanes'][label]['profile'], inputs=inputs, route=route)
        assert wire(report['execution_profile']['resource_lease']) == wire(admissions[label])
        check_tensor_receipts(report['execution_profile'], result['checkpoint_sha256'], anchor)
        if label == 'baseline_cpu_opt_out': canonical[count], numeric[count] = decisions(report), logits
        assert wire(decisions(report)) == wire(canonical[count])
        assert entry['complete_decisions_match_original_CPU'] is entry['cpu_cuda_rng_unchanged'] is True
        assert entry['included_in_paired_timing'] is timed and entry['python_call_profiler_attached_during_public_call'] is (not timed)
        elapsed = entry['unprofiled_cuda_elapsed_seconds']
        if cuda: _finite_seconds(elapsed)
        else: assert elapsed is None
        assert 'lease_check_observation' not in entry and 'numeric_lease_check_observation' not in entry
        errors = {name: max(error(left[name], right[name]) for left, right in zip(numeric[count], logits)) for name in OUTPUTS}
        assert wire(entry['four_logit_max_abs_errors']) == wire(errors) and all(value <= 5e-5 for value in errors.values())
        for name, value in errors.items(): maximum_errors[name] = max(maximum_errors[name], value)
        public_count += 1

    for label in CPU_LANES+CUDA_LANES:
        lane, cuda = result['lanes'][label], label.endswith('_cuda')
        assert wire(lane['state_before']) == wire(lane['state_after']) == wire(result['expected_model_pin'])
        assert wire(lane['profile']['resource_lease']) == wire(admissions[label])
        assert lane['profile']['checkpoint_sha256'] == result['checkpoint_sha256']
        assert lane['profile']['device'] == (f"cuda:{result['hardware']['device_index']}" if cuda else 'cpu')
        check_tensor_receipts(lane['profile'], result['checkpoint_sha256'], anchor)
        _parent_profile(lane['profile'], dimension, cuda, label.removesuffix('_cuda').removesuffix('_cpu_opt_out'))
        assert 'lease_constructor_observation' not in lane
        if cuda:
            assert lane['counts'] == {} and set(lane['warmups']) == {'1', '16', '32'}
            for count in (1, 16, 32): observe(label, count, lane['warmups'][str(count)], f'{label}-{count}-warmup', False)
        else:
            assert set(lane['counts']) == {'1', '16', '32'} and 'warmups' not in lane
            for count in (1, 16, 32): observe(label, count, lane['counts'][str(count)], f'{label}-{count}', False)
    summaries = {}
    for count in (1, 16, 32):
        entry = result['counts'][str(count)]
        raw_timing = archive.use(entry['raw_timing_evidence'], f'{count}-raw-two-way-timings.json')
        summary, positions = check_timing_entry(entry, raw_timing)
        summaries[str(count)] = summary
        _plain_count(entry['sample_count_each_route'], 12)
        assert entry['order_schedule'] == 'both_permutations_repeated_six_times'
        for field in ('first_position_each_route', 'second_position_each_route'): _plain_count(entry[field], 6)
        for trial in entry['trials']:
            for label in trial['order']:
                observe(label, count, trial['observations'][label], f"{count}-trial{trial['trial']:02d}-{label}", True)
    _native_controls(result, dimension, admissions)
    _plain_count(public_count, 84)
    archive.close()
    assert pin(root/'result.json', read(root/'result.json')) == result_pin
    if check_current_sources:
        assert len(current) == 36
        for item in current: assert pin(item['path'], read(item['path'], readonly=False)) == item
    return {'schema': AUDIT_SCHEMA, 'qualified': True, 'closed_artifacts_consistent': True, 'error': None,
        'dimension': dimension, 'cohort': cohort, 'result_pin': result_pin, 'expected_result_sha256': expected_result_sha256,
        'retained_pins': [result_pin, *archive.pins.values()], 'bounded_archive_files': len(archive.pins)+1,
        'bounded_archive_bytes': archive.bytes, 'check_current_sources': check_current_sources,
        'current_sources_verified': check_current_sources, 'current_source_pins': current,
        'public_reports': 84, 'complete_four_logit_snapshots': 84, 'timed_public_reports': 72,
        'CPU_reference_reports': 6, 'CUDA_warmup_reports': 6, 'recomputed_timing_summaries': summaries,
        'recomputed_four_logit_max_abs_errors': maximum_errors,
        'numeric_scope': 'saved_complete_float32_panels_and_public_diagnostics_no_model_replay',
        'timing_scope': 'source_bound_balanced_unprofiled_complete_call_intervals_only_no_universal_or_default_gain',
        **dict.fromkeys(('recurrent_model_replayed', 'retained_python_executed', 'tensor_library_imported',
            'model_executed', 'scheduler_executed', 'performance_qualified', 'execution_attestation', 'proof_authority',
            'production_qualified', 'selected_existing_profile_changed', 'native_due_renewal_qualified',
            'native_lease_expiry_qualified', 'native_leanstral_outputs_qualified', 'trained4096_qualification_established'), False)}


def audit(root, expected_result_sha256, check_current_sources=False):
    try:
        return review(root, expected_result_sha256, check_current_sources)
    except (AssertionError, ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, OverflowError, RecursionError) as error:
        return {'schema': AUDIT_SCHEMA, 'qualified': False, 'closed_artifacts_consistent': False,
                'error': {'type': type(error).__name__, 'message': str(error)}}


# Exact source-bound candidate policy, independently reconstructed as ordinary data.
def _whole_input_implementation():
    return {'schema': 'native-span-whole-call-input-implementation/v1',
        'source_sha256': FIXED_SOURCES['legal_span_whole_input_guard_device_inference'][1],
        'profiles': {str(d): f'native-{d}-owned-bitwise-whole-call-input/v1' for d in (768, 4096)},
        'input_guard_implementation': deepcopy(CACHE_IMPLEMENTATION['input_guard_implementation']),
        'inherited_owner_source_sha256': {'768': FIXED_SOURCES['legal_span_device_bitwise_inference'][1],
            '4096': FIXED_SOURCES['legal_span_4096_bitwise_device_inference_v2'][1]},
        'source_bound_decode_adaptations': deepcopy(DECODE_ADAPTATIONS),
        'change_scope': 'outer_whole_call_input_guard_only_independent_local_immutable_snapshot',
        'checkpoint_receipt_policy_lease_and_result_guards_retained': True,
        'row_cache_and_numerical_paths_retained': True, 'all_existing_boundary_and_per_row_polls_retained': True,
        'nested_reference_wrapper_field_identities_bound': True,
        'atom_array_scalar_snapshot_traversal_performed': False,
        'copied_decode_globals_are_private_and_source_bound': True,
        **dict.fromkeys(('source_verification_success_cached', 'boundary_consolidation_performed',
            'cached_row_input_substitution_performed', 'lease_cadence_substitution_performed',
            'existing_selected_route_changed', 'performance_qualified', 'native_leanstral_outputs_qualified',
            'trained4096_qualification_established', 'production_qualified', 'proof_authority', 'execution_attestation'), False)}
WHOLE_INPUT_CURRENTNESS = {'schema': 'span-whole-call-input-currentness/v1', 'guard_object_and_immutable_snapshot_identities_checked': True, 'nested_reference_wrapper_field_identities_checked': True, 'atom_array_scalar_reference_nodes_traversed': False, 'comparison': 'immutable-input-structural-content-with-canonical-json-fallback/v1', 'scope': 'independent_function_local_guard_and_snapshot_checked_before_and_after_full_call', 'fast_comparison': True, 'standard_finite_input_snapshot_canonical_json_serialized': False, 'proof_authority': False, 'execution_attestation': False}
DECODE_ADAPTATIONS = [{'source_role': 'legal_span_device_inference', 'class': 'DeviceDimensionalSpanSession', 'method': 'decode_formal_logic', 'source_sha256': '4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5', 'closed_ast_substitution_counts': {'outer_input_constructor': 1, 'final_input_comparison': 1, 'public_input_profile': 1, 'resident_opt_out': 0}, 'original_method_ast_sha256': '86cf95061707f4c4b1e3d6c56aec010891854b3441a29979a57463e339120a14', 'adapted_method_ast_sha256': '52c38955979a7485a94ba5a2d61e71c5899b30c9187fa08e0aa70661957f4cf3'}, {'source_role': 'legal_span_device_batch_inference', 'class': 'DeviceBatchedDimensionalSpanSession', 'method': 'decode_formal_logic', 'source_sha256': '5c916e7ab3b52f908731a6bab5dce83a31a7b6ad269445281c89ecd5cee07133', 'closed_ast_substitution_counts': {'outer_input_constructor': 1, 'final_input_comparison': 1, 'public_input_profile': 1, 'resident_opt_out': 1}, 'original_method_ast_sha256': '258cbc150232a52f6ac1799b4ce2233702bb8d634b1839c8129a689ff85731b3', 'adapted_method_ast_sha256': '5a0c21edfc947868880d71324885e70c27bdb3d4cd752ad68216d82e72de3338'}, {'source_role': 'legal_span_4096_device_inference', 'class': 'DeviceLeanstral4096SpanSession', 'method': 'decode_formal_logic', 'source_sha256': '658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8', 'closed_ast_substitution_counts': {'outer_input_constructor': 1, 'final_input_comparison': 1, 'public_input_profile': 1, 'resident_opt_out': 0}, 'original_method_ast_sha256': '42afd6fe9ce573099e3556c17532ef46394e6b88a3bfb41b9d7bb4b1296c7d4d', 'adapted_method_ast_sha256': 'e37b0d50d4f547fbfcd888efadd6fce8a69cc6524c1a32e70ece86032b35533f'}]
NATIVE_CONTROL_SCHEDULE = ('caller_input_alias_after_forward', 'caller_source_alias_after_forward',
    'paired_input_guard_reference_after_forward', 'input_guard_canonical_snapshot_after_forward',
    'input_guard_fast_mode_alias_after_forward', 'valid_input_guard_snapshot_after_forward',
    'paired_input_guard_nested_array_after_forward',
    'actual_owned_child_cancel_after_measurements')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--expected-result-sha256', required=True)
    parser.add_argument('--check-current-sources', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.expected_result_sha256, args.check_current_sources)
    with args.output.open('xb') as stream: stream.write(wire(result))
    args.output.chmod(0o444)
    print(json.dumps({'qualified': result['qualified'], 'error': result['error']}))
    raise SystemExit(0 if result['qualified'] else 1)

