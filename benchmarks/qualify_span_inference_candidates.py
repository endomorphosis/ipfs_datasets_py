"""Bounded original-bitwise/cache/authenticated-cadence span comparison.

Each invocation owns one dimension and one fresh A/B cohort. All public calls
retain exact decisions and a separate guarded complete four-logit snapshot.
CUDA intervals have no Python observer attached. Cadence adds fresh authority
and due renewal to an already read-only baseline poll; it does not claim that
the baseline performed nondue durable writes. Ordinary artifacts confer no
execution attestation, proof, encoder provenance or production promotion.
"""
from contextlib import contextmanager
from copy import deepcopy
import argparse
import gc
import hashlib
import importlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import re
import statistics
import struct
import sys
import threading
import time
import traceback

SCHEMA = 'span-inference-candidates-qualification/v1'
PREFIX = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
ROOT = Path('/home/barberb/lift_coding')
BASE = ROOT/'artifacts/codebase_ir_terminal_bench'
PACKAGE = ROOT/'external/ipfs_datasets'
CONFIG = BASE/'successor-expansion-resources-20261003-01/configuration.json'
CONFIG_SHA = 'c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575'
HEARTBEAT_SHA = '584ddf7f8274481940ff48648da5947d08ba42534cf46157da3591a4ac634b30'
CADENCE_SHA = 'c1b8263bcc06e978efea616c9915a3986b7da5d3bc587badb38e815331758c1f'
HELPERS = {
    'trained_helpers': ('qualify_bitwise_trained_head_devices', '29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110'),
    'dimension_helpers': ('profile_dimension_guard_costs_v6', 'c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0'),
    'coordinator_helpers': ('qualify_formula_guard_coordinator', 'e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8'),
    'cleanup_helper': ('qualify_native_768_device', '73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c'),
    'synthetic_helpers': ('qualify_synthetic_4096_head_device_v2', 'a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36'),
    'compatibility_probe_helpers': ('probe_cached_span_device_candidate_v2', '4a5e5a6c633f20c6886bbeecdf9bbc45b23c5c784d8fd5d55543acb18932ecc5')}
CPU_LANES = ('baseline_cpu_opt_out', 'cached_input_cpu_opt_out', 'lease_cadence_cpu_opt_out')
CUDA_LANES = ('baseline_cuda', 'cached_input_cuda', 'lease_cadence_cuda')
COUNTS, PAIRS, MAX_SECONDS = (1, 16, 32), 12, 120
ORDERS = tuple(itertools.permutations(CUDA_LANES))*2
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 1024, 8*1024**2, 64*1024**2
ROOT_RAM, ROOT_GPU, ROOT_UNIFIED = 4096, 768, 4864
CHILD_RAM, CHILD_GPU, CHILD_UNIFIED = 1024, 256, 1280
HEARTBEAT_FIELDS = ('_lease', '_scheduler', '_lease_binding', '_scheduler_binding', '_config_binding',
                    '_ancestry', '_renewal_fraction', '_interval', '_process', '_thread')


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _require(condition, message):
    if not condition: raise ValueError(message)


def _load_helper(name, expected):
    path = Path(__file__).with_name(name+'.py')
    before = path.read_bytes()
    _require(hashlib.sha256(before).hexdigest() == expected, 'pinned current helper differs: '+name)
    specification = importlib.util.spec_from_file_location('_span_candidates_'+name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    _require(path.read_bytes() == before, 'ordinary helper changed during import: '+name)
    return module, path


def _bound_inputs(inputs, dimension):
    _require(type(inputs) is dict and type(inputs['dimension']) is int and inputs['dimension'] == dimension
             and type(inputs['texts']) is list and type(inputs['vectors']) is list
             and len(inputs['texts']) == len(inputs['vectors']) == 32, 'fixed complete32-row native inputs required')
    for text, vector in zip(inputs['texts'], inputs['vectors']):
        _require(type(text) is str and 0 < len(text) <= 4096
                 and 1 <= len(list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))) <= 64,
                 'bounded physical source and real tokens required before admission')
        _require(type(vector) is list and len(vector) == dimension
                 and all(type(value) is float and math.isfinite(value) for value in vector),
                 'complete finite exact native-width float inputs required')
        for value in vector: struct.pack('<f', value)
    return {'rows': 32, 'source_characters_each': 4096, 'source_tokens_each': 64, 'latent_width': dimension,
            'checked_before_admission': True, 'no_source_or_latent_truncation': True}


@contextmanager
def _lease_observer(heartbeat, resources, *, phase):
    """Source-bound synchronous checks only, not timed or background I/O."""
    code = heartbeat.AuthenticatedLeaseHeartbeat.check.__code__
    locked = resources.GlobalResourceScheduler._locked_state
    while getattr(locked, '__wrapped__', None) is not None: locked = locked.__wrapped__
    locked_code, previous, thread_id = locked.__code__, sys.getprofile(), threading.get_ident()
    checks, active = [], {}
    def observe(frame, event, arg):
        if event == 'call' and frame.f_code is code:
            _require(threading.get_ident() == thread_id and len(checks) < 256, 'bounded own-thread lease checks required')
            row = {'index': len(checks), 'outcome': None, 'read_lock_segments': 0,
                   'persist_requested_lock_segments': 0, 'fsync_calls': 0, 'replace_calls': 0}
            checks.append(row); active[id(frame)] = row
        elif event == 'return' and frame.f_code is code:
            _require(id(frame) in active, 'lease helper check return has no call')
            active.pop(id(frame))['outcome'] = 'renewed_due' if arg is True else 'valid_non_due' if arg is False else 'refused'
        elif event == 'call' and frame.f_code is locked_code and active:
            persist = frame.f_locals.get('persist', True)
            _require(type(persist) is bool, 'plain persistence observation required')
            for row in active.values(): row['persist_requested_lock_segments' if persist else 'read_lock_segments'] += 1
        elif event == 'c_call' and active:
            field = 'fsync_calls' if arg is os.fsync else 'replace_calls' if arg is os.replace else None
            if field is not None:
                for row in active.values(): row[field] += 1
        if previous is not None: previous(frame, event, arg)
    receipt = {'schema': 'source-bound-lease-cadence-call-observation/v1',
        'scope': 'main_thread_helper_check_only_no_background_or_timed_interval_attestation',
        'source_role': 'authenticated_lease_heartbeat', 'source_sha256': HEARTBEAT_SHA, 'phase': phase,
        'thread_id': thread_id, 'checks': checks,
        'generator_segment_scope': 'call_events_include_contextmanager_resume_segments_not_transaction_count',
        'background_threads_observed': False, 'timed_cuda_interval_observed': False,
        'execution_attestation': False, 'proof_authority': False, 'performance_qualified': False}
    sys.setprofile(observe)
    try: yield receipt
    finally:
        sys.setprofile(previous)
        _require(not active and all(row['outcome'] is not None for row in checks), 'lease observation did not close')
        receipt.update(check_count=len(checks), valid_non_due_count=sum(row['outcome'] == 'valid_non_due' for row in checks),
            due_renewal_count=sum(row['outcome'] == 'renewed_due' for row in checks),
            refusal_count=sum(row['outcome'] == 'refused' for row in checks), profile_restored=sys.getprofile() is previous)
        _require(receipt['profile_restored'] is True and all(row['fsync_calls'] == row['replace_calls'] == 0
                 for row in checks if row['outcome'] == 'valid_non_due'), 'nondue mutation or unclosed observer')


@contextmanager
def _restore_observer(torch, module, method_name, receipt):
    function = getattr(module, method_name)
    code, previous = function.__code__, sys.getprofile()
    def observe(frame, event, arg):
        if frame.f_code is code:
            if event == 'call': receipt['native_restore_attempts'] += 1
            elif event == 'return' and isinstance(arg, torch.nn.Module): receipt['native_restore_completions'] += 1
        if previous is not None: previous(frame, event, arg)
    sys.setprofile(observe)
    try: yield
    finally:
        sys.setprofile(previous)
        receipt['profile_restored'] = sys.getprofile() is previous


def _numeric_snapshot(torch, modules, lane, inputs, count, trained, dimension_helper, synthetic):
    span, batch = modules['legal_span_formula'], modules['legal_span_device_batch_inference']
    if lane.dimension == 768:
        return trained._span_logits(torch, span, batch, lane, inputs, count, singleton=not lane.owner._optimized)
    records = [{'tokens': span.tokenize_source(text), 'latent': vector}
               for text, vector in zip(inputs['texts'][:count], inputs['vectors'][:count])]
    if lane.owner._optimized:
        raw, scope = synthetic._checked_private_logits(torch, span, lane.owner, records)
        return dimension_helper._rows_from_batched_logits(raw, [len(row['tokens']) for row in records]), scope
    values, scopes = [], []
    for item in records:
        raw, scope = synthetic._checked_private_logits(torch, span, lane.owner, [item])
        values.extend(dimension_helper._rows_from_batched_logits(raw, [len(item['tokens'])]))
        scopes.append(scope)
    return values, {'singletons': True, 'separate_checked_private_four_logits': True, 'observations': scopes}


def _native_controls(lanes, inputs, cancellation, heartbeat, resources):
    """Own token/helper/caller aliases only; final owned revocation then close."""
    controls = []
    for label in ('cached_input_cuda', 'lease_cadence_cuda'):
        lane, authored = lanes[label], deepcopy(inputs)
        owner, previous, forward_calls = lane.owner, sys.getprofile(), 0
        code = owner._model.forward.__func__.__code__
        def observe(frame, event, arg):
            nonlocal forward_calls
            if event == 'call' and frame.f_code is code: forward_calls += 1
            if previous is not None: previous(frame, event, arg)
        def mutate_input(): authored['vectors'][0][0] += .25
        cancellation.owner, cancellation.family, cancellation.action = owner, 'span', mutate_input
        try:
            sys.setprofile(observe)
            options = {} if lane.dimension == 4096 else {'embedding_receipts': authored['receipts'][:1],
                                                        'expected_receipt_sha256s': authored['receipt_pins'][:1]}
            owner.decode_formal_logic(authored['texts'][:1], authored['vectors'][:1], **options)
        except (ValueError, RuntimeError, TimeoutError) as error:
            _require('changed' in str(error).lower() and forward_calls > 0 and cancellation.triggered,
                     'caller input mutation refused at an unexpected boundary')
            controls.append({'control': 'caller_input_alias_after_forward', 'route': label, 'refused': True,
                'refusal': str(error), 'actual_model_forward_calls': forward_calls, 'before_forward_refusal': False,
                'post_forward_callback_executed': True, 'scope': 'actual_authored_caller_container_alias_outer_input_guard_retained'})
        else: raise ValueError('span candidate accepted caller input alias after forward')
        finally: sys.setprofile(previous); cancellation.clear()
        lane.describe()
    lane, owner = lanes['lease_cadence_cuda'], lanes['lease_cadence_cuda'].owner
    for kind, callback in (('lease_key', False), ('lease_key', True), ('helper', False), ('helper', True)):
        previous, forward_calls = sys.getprofile(), 0
        code = owner._model.forward.__func__.__code__
        old_key = owner._lease.lease_key
        saved = (owner._heartbeat_owner, owner._heartbeat_snapshot, owner._heartbeat_snapshot_identity)
        def observe(frame, event, arg):
            nonlocal forward_calls
            if event == 'call' and frame.f_code is code: forward_calls += 1
            if previous is not None: previous(frame, event, arg)
        def mutate():
            if kind == 'lease_key': owner._lease.lease_key = 'incorrect_'+old_key
            else:
                helper = heartbeat.AuthenticatedLeaseHeartbeat(owner._lease)
                owner._heartbeat_owner = helper
                if callback:
                    snapshot = (helper, *(getattr(helper, name) for name in HEARTBEAT_FIELDS))
                    owner._heartbeat_snapshot = owner._heartbeat_snapshot_identity = snapshot
        if callback: cancellation.owner, cancellation.family, cancellation.action = owner, 'span', mutate
        else: mutate()
        observation = None
        try:
            sys.setprofile(observe)
            with _lease_observer(heartbeat, resources, phase='native_lease_custody_control') as observation: lane.call(inputs, 1)
        except (ValueError, RuntimeError, TimeoutError) as error:
            _require(any(word in str(error).lower() for word in ('lease', 'heartbeat', 'changed'))
                     and (forward_calls > 0 if callback else forward_calls == 0)
                     and cancellation.triggered is callback, 'native span lease custody refused at unexpected boundary')
            controls.append({'control': ('paired_helper_snapshot_after_forward' if callback else 'valid_helper_replacement_before_forward')
                if kind == 'helper' else ('local_lease_key_alias_after_forward' if callback else 'local_lease_key_alias_before_forward'),
                'route': 'lease_cadence_cuda', 'refused': True, 'refusal': str(error), 'actual_model_forward_calls': forward_calls,
                'before_forward_refusal': not callback, 'post_forward_callback_executed': callback,
                'persisted_lease_metadata_modified': False, 'original_bindings_restored': True,
                'lease_check_observation': deepcopy(observation),
                'scope': 'candidate_owned_local_aliases_only_original_bindings_restored_no_persisted_authority_change'})
        else: raise ValueError('span cadence accepted local lease/helper custody mutation')
        finally:
            sys.setprofile(previous); owner._lease.lease_key = old_key
            owner._heartbeat_owner, owner._heartbeat_snapshot, owner._heartbeat_snapshot_identity = saved
            cancellation.clear()
        lane.describe()
    return controls


def _cancel_after_measurements(lane, inputs, heartbeat, resources):
    owner, previous, forward_calls = lane.owner, sys.getprofile(), 0
    code = owner._model.forward.__func__.__code__
    def observe(frame, event, arg):
        nonlocal forward_calls
        if event == 'call' and frame.f_code is code: forward_calls += 1
        if previous is not None: previous(frame, event, arg)
    _require(owner._lease.cancel() is True and not owner._lease.released, 'actual own child cancellation required')
    snapshot, observation = owner._scheduler.snapshot(), None
    try:
        sys.setprofile(observe)
        with _lease_observer(heartbeat, resources, phase='native_owned_child_cancel_control') as observation: lane.call(inputs, 1)
    except (ValueError, RuntimeError, TimeoutError) as error:
        _require(str(error) == f'{lane.dimension}D device lease revoked or expired'
                 and forward_calls == 0, 'actual revoked child was not refused before forward')
        return {'control': 'actual_owned_child_cancel_after_measurements', 'route': 'lease_cadence_cuda', 'refused': True,
            'refusal': str(error), 'actual_model_forward_calls': 0, 'before_forward_refusal': True,
            'post_forward_callback_executed': False, 'child_cancel_requested': True,
            'owned_child_lease_id': owner._lease.lease_id, 'released_before_close': False,
            'resources_after_cancel_before_close': snapshot, 'lease_check_observation': deepcopy(observation),
            'scope': 'actual_owned_child_only_revocation_after_all_public_measurements_and_state_joins'}
    else: raise ValueError('span cadence accepted actual own child cancellation')
    finally: sys.setprofile(previous)


def run(args):
    _require(type(args.dimension) is int and args.dimension in (768, 4096)
             and type(args.cohort) is str and args.cohort in ('A', 'B'), 'exact dimension/cohort required')
    _require(type(args.admission_timeout_seconds) is int and 1 <= args.admission_timeout_seconds <= 60, 'admission1..60seconds required')
    _require(type(args.namespace) is str and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', args.namespace), 'fresh relative namespace required')
    _require(len(CADENCE_SHA) == 64 and all(value in '0123456789abcdef' for value in CADENCE_SHA), 'final cadence source pin required')
    output = BASE/args.namespace; output.mkdir()
    result = {'schema': SCHEMA, 'qualified': False, 'error': None, 'dimension': args.dimension, 'cohort': args.cohort,
        'performance_qualified': False, 'proof_authority': False, 'execution_attestation': False,
        'production_qualified': False, 'selected_existing_profile_changed': False, 'native_leanstral_outputs_qualified': False,
        'trained4096_qualification_established': False, 'native_due_renewal_qualified': False, 'native_lease_expiry_qualified': False,
        'source_pins': [], 'fixture_pins': [], 'lanes': {}, 'counts': {}, 'owned_children': [], 'constructor_observations': [],
        'public_return_count': 0, 'complete_four_logit_snapshot_count': 0, 'timed_return_count': 0,
        'numeric_tolerance_absolute': 5e-5, 'encoder_execution_performed': False, 'shared_configuration_changed': False,
        'actual_cuda_execution': False, 'max_seconds_after_admission': MAX_SECONDS,
        'admission_timeout_seconds': args.admission_timeout_seconds, 'paired_samples_per_route_per_count': PAIRS,
        'timing_scope': 'complete_guarded_public_call_and_completion_sync_input_copy_before_interval_no_profiler',
        'span_numeric_scope': 'one_separate_complete_checked_four_logit_snapshot_after_every_public_return_outside_timing',
        'counter_scope': 'constructors_CPU_references_CUDA_warmups_controls_and_separate_numeric_only_not_timed_CUDA',
        'lease_observation_scope': 'main_thread_selected_helper_check_only_no_timed_background_or_execution_attestation',
        'baseline_lease_poll_scope': 'already_read_only_cancellation_poll_no_inline_renewal_elimination_claim',
        'historical_receipt_scope': 'retained_content_pin_only_no_new_encoder_or_signature_execution',
        'pid': os.getpid(), 'observed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    counters = dict.fromkeys(('optimizer_constructor_calls', 'optimizer_steps', 'new_training_fits', 'training_mode_true_calls'), 0)
    scheduler = parent = torch = device = cancel = evidence = None
    old_threads = admitted = None; safe_close = True
    staged, active, references, numeric_references, helpers = [], [], {}, {}, {}
    owner = lane = probe = product = None
    started = time.monotonic()
    try:
        helper_paths = {}
        for role, (name, sha) in HELPERS.items(): helpers[role], helper_paths[role] = _load_helper(name, sha)
        trained, dimension_helper, coordinator = (helpers[key] for key in ('trained_helpers', 'dimension_helpers', 'coordinator_helpers'))
        synthetic, cleanup, prior = (helpers[key] for key in ('synthetic_helpers', 'cleanup_helper', 'compatibility_probe_helpers'))
        evidence = trained.Evidence(output)
        names = (*prior.MODULES, 'authenticated_lease_heartbeat', 'legal_span_lease_heartbeat_device_inference')
        paths = {name: PACKAGE/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/(name+'.py') for name in names}
        paths.update({'benchmark': Path(__file__).absolute(), **helper_paths,
            'tree_pin': PACKAGE/'ipfs_datasets_py/logic/autoformal/tree_pin.py',
            'canonical_contracts': PACKAGE/'ipfs_datasets_py/logic/legal_ir/canonical_contracts.py',
            'cid_utils': PACKAGE/'ipfs_datasets_py/utils/cid_utils.py'})
        fixed = {**prior.FIXED, 'authenticated_lease_heartbeat': HEARTBEAT_SHA,
                 'legal_span_lease_heartbeat_device_inference': CADENCE_SHA,
                 **{role: sha for role, (_, sha) in HELPERS.items()}}
        _require(len(paths) == 33, 'exact33 producer source roles required')
        for index, (name, path) in enumerate(paths.items()):
            _, entry = evidence.retain(f'{index:02d}-{path.name}', path, name, fixed.get(name))
            result['source_pins'].append(entry); staged.append(entry)
        raw, configuration = evidence.retain('configuration.json', CONFIG, 'configuration', CONFIG_SHA)
        result['shared_configuration'] = configuration; staged.append(configuration)
        cp_path, cp_sha, input_path, input_sha = prior.FIXTURES[args.dimension]
        cp_raw, cp_entry = evidence.retain('checkpoint.json', BASE/cp_path, 'checkpoint', cp_sha)
        input_raw, input_entry = evidence.retain('inputs.json', BASE/input_path, 'inputs', input_sha)
        result['fixture_pins'] = [cp_entry, input_entry]; staged.extend(result['fixture_pins'])
        checkpoint, inputs = json.loads(cp_raw), json.loads(input_raw)
        result['physical_input_limits'] = _bound_inputs(inputs, args.dimension)
        result['retained_progress'] = deepcopy(checkpoint['progress'])
        _require(checkpoint['progress']['optimizer_steps'] == (1 if args.dimension == 768 else 0), 'fixed retained progress differs')
        result['checkpoint_sha256'] = cp_sha
        state_wire = trained._wire(checkpoint['model_state'])
        result['expected_model_pin'] = {'bytes': len(state_wire), 'sha256': hashlib.sha256(state_wire).hexdigest()}
        _require(not any(PREFIX+name in sys.modules for name in names if name != 'resource_scheduler'), 'fresh producer process required')
        resources = importlib.import_module(PREFIX+'resource_scheduler')
        config = json.loads(raw)
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(**config['persisted_config'],
            state_path=config['state_path'], lease_ttl_seconds=config['lease_ttl_seconds'], auto_renew_leases=config['auto_renew_leases']))
        result['resources_before'] = scheduler.snapshot()
        parent = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=4, memory_mb=ROOT_RAM,
            gpu_memory_mb=ROOT_GPU, unified_memory_mb=ROOT_UNIFIED, requires_gpu=True,
            timeout=args.admission_timeout_seconds, request_id=args.namespace)
        admitted = time.monotonic(); result['admission'] = parent.to_dict()
        print('ADMITTED', parent.lease_id, flush=True)
        cancel = trained.Cancellation(parent, admitted+MAX_SECONDS)
        import torch as actual_torch
        torch = actual_torch
        result['cuda_initialized_after_scheduler_admission'] = torch.cuda.is_initialized()
        _require(torch.cuda.is_available(), 'actual CUDA required')
        device = torch.cuda.current_device()
        result['gpu_allocated_before_producer_imports_bytes'] = torch.cuda.memory_allocated(device)
        _require(result['gpu_allocated_before_producer_imports_bytes'] == 0, 'telemetry context must contain zero model allocations')
        old_threads = torch.get_num_threads(); result['ambient_before'] = coordinator._settings(torch)
        torch.set_num_threads(1); result['ambient_reserved'] = coordinator._settings(torch)
        _require(result['ambient_reserved'] == {**result['ambient_before'], 'num_threads': 1}, 'only one reserved CPU thread may change')
        _require(sys.getprofile() is None, 'fresh uninstrumented worker required')
        modules = {name: importlib.import_module(PREFIX+name) for name in names}
        _require(all(Path(module.__file__).absolute() == paths[name] for name, module in modules.items()), 'producer imported from different source')
        _require(torch.cuda.memory_allocated(device) == 0 and coordinator._settings(torch) == result['ambient_reserved'], 'producer imports changed CUDA allocation/policy')
        for entry in staged: _require(coordinator._pin(entry['current']['path']) == entry['current'], 'source changed before model construction')
        result['hardware'] = {'torch': str(torch.__version__), 'cuda_runtime': torch.version.cuda, 'device_index': device,
            'name': torch.cuda.get_device_name(device), 'capability': list(torch.cuda.get_device_capability(device)),
            'actual_initial_cuda_kernel': synthetic._initial_kernel(torch, device) == [4.]}
        gpu_free, gpu_total = torch.cuda.mem_get_info(device)
        result['hardware'].update(gpu_free_bytes=gpu_free, gpu_total_bytes=gpu_total)
        _require(result['hardware']['actual_initial_cuda_kernel'] is True, 'actual initial kernel differs')
        result['gpu_allocated_before_owned_sessions_bytes'] = torch.cuda.memory_allocated(device)
        _require(result['gpu_allocated_before_owned_sessions_bytes'] == 0, 'initial kernel left allocated tensors')
        torch.cuda.reset_peak_memory_stats(device)
        heartbeat, cadence = modules['authenticated_lease_heartbeat'], modules['legal_span_lease_heartbeat_device_inference']
        cached = modules['legal_span_cached_input_device_inference']
        classes = ({'baseline': cached._BASE_768, 'cached_input': cached.InputCachedDeviceDimensionalSpanSession,
                    'lease_cadence': cadence.DeviceBitwiseDimensionalSpanSession} if args.dimension == 768 else
                   {'baseline': cached._BASE_4096, 'cached_input': cached.InputCachedDeviceLeanstral4096SpanSession,
                    'lease_cadence': cadence.BitwiseDeviceLeanstral4096SpanSession})

        def construct(label):
            nonlocal owner, lane
            cancel.poll()
            optimized, route = label.endswith('_cuda'), label.rsplit('_cuda', 1)[0] if label.endswith('_cuda') else label.removesuffix('_cpu_opt_out')
            options = dict(expected_checkpoint_sha256=cp_sha, optimized=optimized, scheduler=scheduler, parent_lease=parent,
                cancel_event=cancel, admission_timeout_seconds=args.admission_timeout_seconds, max_seconds=MAX_SECONDS,
                memory_mb=CHILD_RAM, gpu_memory_mb=CHILD_GPU, unified_memory_mb=CHILD_UNIFIED)
            if args.dimension == 4096: options['synthetic_unreceipted'] = True
            restore_module = modules['legal_span_device_inference'] if args.dimension == 768 else modules['legal_span_4096']
            method = '_restore' if args.dimension == 768 else '_restore_for_inference'
            receipt = {'route': label, 'dimension': args.dimension, 'checkpoint_sha256': cp_sha,
                'started': True, 'completed': False, 'native_restore_attempts': 0, 'native_restore_completions': 0,
                'source_role': 'legal_span_device_inference' if args.dimension == 768 else 'legal_span_4096',
                'method': method, 'observation_scope': 'source_bound_native_model_restore_during_constructor_only'}
            result['constructor_observations'].append(receipt)
            try:
                with dimension_helper._forbidden_calls(torch, modules, counters):
                    with _restore_observer(torch, restore_module, method, receipt):
                        with _lease_observer(heartbeat, resources, phase='constructor') as lease_observation:
                            owner = classes[route](deepcopy(checkpoint), **options)
                _require(receipt['native_restore_attempts'] == receipt['native_restore_completions'] == 1, 'one validated private model restore required')
                _require(coordinator._settings(torch) == result['ambient_reserved'], 'constructor changed ambient policy')
                lane = dimension_helper.DimensionLane(owner, args.dimension); active.append(lane)
                child = {'lane': label, 'admission': lane.child_lease.to_dict(), 'release_observed': False}
                result['owned_children'].append(child)
                receipt['completed'] = True
                record = result['lanes'][label] = {'constructor': deepcopy(receipt), 'profile': lane.describe(),
                    'state_before': trained._state_pin(owner, 'span'), 'counts': {},
                    'lease_constructor_observation': deepcopy(lease_observation)}
                _require(record['state_before'] == result['expected_model_pin'], 'restored model differs from fixed checkpoint')
                owner = None
                return lane
            except BaseException:
                if owner is not None:
                    owner.close(); owner = None
                raise

        def observe_call(label, lane, count, stem, *, timed=False):
            cancel.poll()
            authored = deepcopy(inputs)
            cpu_rng, gpu_rng = torch.get_rng_state(), torch.cuda.get_rng_state(device)
            torch.cuda.synchronize(device)
            begin = time.monotonic()
            if timed:
                _require(sys.getprofile() is None, 'timed CUDA cannot have Python observer')
                # DimensionLane.call performs its own input copy. Prepare the
                # exact caller containers here, outside the measured interval.
                texts, vectors = authored['texts'][:count], authored['vectors'][:count]
                options = {} if args.dimension == 4096 else {'embedding_receipts': authored['receipts'][:count],
                                                            'expected_receipt_sha256s': authored['receipt_pins'][:count]}
                begin = time.monotonic()
                report = lane.owner.decode_formal_logic(texts, vectors, **options)
            else:
                with dimension_helper._forbidden_calls(torch, modules, counters):
                    with _lease_observer(heartbeat, resources, phase='public_reference_or_warmup') as lease_observation:
                        report = lane.call(authored, count)
            torch.cuda.synchronize(device)
            elapsed = time.monotonic()-begin
            _require(type(elapsed) is float and math.isfinite(elapsed) and 0 < elapsed <= MAX_SECONDS, 'positive completed public interval required')
            _require(torch.equal(cpu_rng, torch.get_rng_state()) and torch.equal(gpu_rng, torch.cuda.get_rng_state(device)), 'public inference changed RNG')
            observed = {'report': evidence.json(stem+'-report.json', report), 'four_logits': None,
                'complete_decisions_match_original_CPU': label != 'baseline_cpu_opt_out', 'cpu_cuda_rng_unchanged': True,
                'included_in_paired_timing': timed, 'python_call_profiler_attached_during_public_call': not timed,
                'unprofiled_cuda_elapsed_seconds': elapsed if label.endswith('_cuda') else None}
            result['public_return_count'] += 1; result['timed_return_count'] += int(timed)
            if not timed: observed['lease_check_observation'] = deepcopy(lease_observation)
            canonical = trained._decisions(report, 'span')
            if label == 'baseline_cpu_opt_out': references[count] = canonical
            _require(canonical == references[count] and report['cuda_executed'] is label.endswith('_cuda'), 'complete public canonical/device equality differs')
            observed['complete_decisions_match_original_CPU'] = True
            with dimension_helper._forbidden_calls(torch, modules, counters):
                with _lease_observer(heartbeat, resources, phase='separate_numeric_snapshot') as numeric_lease_observation:
                    values, scope = _numeric_snapshot(torch, modules, lane, authored, count, trained, dimension_helper, synthetic)
            _require(torch.equal(cpu_rng, torch.get_rng_state()) and torch.equal(gpu_rng, torch.cuda.get_rng_state(device)), 'checked numeric snapshot changed RNG')
            if label == 'baseline_cpu_opt_out': numeric_references[count] = values
            observed.update(four_logits=evidence.json(stem+'-four-logits.json', values), four_logit_scope=scope,
                numeric_lease_check_observation=deepcopy(numeric_lease_observation))
            result['complete_four_logit_snapshot_count'] += 1
            errors = trained._four_errors(numeric_references[count], values)
            observed['four_logit_max_abs_errors'] = errors
            cancel.poll()
            return observed

        for label in CPU_LANES:
            lane = construct(label)
            for count in COUNTS:
                result['lanes'][label]['counts'][str(count)] = observe_call(label, lane, count, f'{label}-{count}')
            result['lanes'][label]['state_after'] = trained._state_pin(lane.owner, 'span')
            _require(result['lanes'][label]['state_after'] == result['expected_model_pin'] and lane.owner._checkpoint == checkpoint, 'CPU model/checkpoint changed')
            lane.close(torch, device); lane = None
        gpu_lanes = {}
        for label in CUDA_LANES:
            lane = gpu_lanes[label] = construct(label)
            result['lanes'][label]['warmups'] = {}
            for count in COUNTS:
                result['lanes'][label]['warmups'][str(count)] = observe_call(label, lane, count, f'{label}-{count}-warmup')
        result['three_way_admission'] = {'all_three_gpu_children_live': all(not value.child_lease.released for value in gpu_lanes.values()),
            'child_leases': {label: value.child_lease.to_dict() for label, value in gpu_lanes.items()}, 'resources': scheduler.snapshot()}
        _require(result['three_way_admission']['all_three_gpu_children_live'], 'three simultaneous CUDA children required')
        for count in COUNTS:
            samples = {label: [] for label in CUDA_LANES}
            entry = result['counts'][str(count)] = {'trials': [], 'samples_seconds': samples,
                'sample_count_each_route': 0, 'order_schedule': 'all_six_permutations_repeated_twice'}
            for index, order in enumerate(ORDERS):
                trial = {'trial': index, 'order': list(order), 'observations': {}}; entry['trials'].append(trial)
                for label in order:
                    observed = observe_call(label, gpu_lanes[label], count, f'{count}-trial{index:02d}-{label}', timed=True)
                    trial['observations'][label] = observed; samples[label].append(observed['unprofiled_cuda_elapsed_seconds'])
            medians = {label: statistics.median(values) for label, values in samples.items()}
            entry.update(median_seconds=medians, sample_count_each_route=PAIRS,
                first_position_each_route=4, second_position_each_route=4, third_position_each_route=4,
                raw_timing_evidence=evidence.json(f'{count}-raw-three-way-timings.json',
                    {'trials': entry['trials'], 'samples_seconds': samples, 'median_seconds': medians}),
                interpretation='descriptive_same_fixture_complete_public_calls_no_global_gain_or_default_promotion')
            for stem, left, right in (('baseline_over_cached_input', 'baseline_cuda', 'cached_input_cuda'),
                                      ('baseline_over_lease_cadence', 'baseline_cuda', 'lease_cadence_cuda'),
                                      ('cached_input_over_lease_cadence', 'cached_input_cuda', 'lease_cadence_cuda')):
                ratios = [a/b for a,b in zip(samples[left], samples[right])]
                entry['median_'+stem+'_ratio'] = medians[left]/medians[right]
                entry['paired_'+stem+'_ratios'] = ratios
                entry['paired_'+stem+'_min_ratio'], entry['paired_'+stem+'_max_ratio'] = min(ratios), max(ratios)
        with dimension_helper._forbidden_calls(torch, modules, counters):
            result['native_controls'] = _native_controls(gpu_lanes, inputs, cancel, heartbeat, resources)
        for label, lane in gpu_lanes.items():
            result['lanes'][label]['state_after'] = trained._state_pin(lane.owner, 'span')
            _require(result['lanes'][label]['state_after'] == result['expected_model_pin'] and lane.owner._checkpoint == checkpoint, 'CUDA model/checkpoint changed')
        with dimension_helper._forbidden_calls(torch, modules, counters):
            result['native_controls'].append(_cancel_after_measurements(gpu_lanes['lease_cadence_cuda'], inputs, heartbeat, resources))
        for lane in gpu_lanes.values(): lane.close(torch, device)
        gpu_lanes.clear(); lane = owner = None
        _require(result['public_return_count'] == result['complete_four_logit_snapshot_count'] == 126
                 and result['timed_return_count'] == 108 and len(result['owned_children']) == 6, 'complete126/108/sixowner coverage required')
        _require(all(value == 0 for value in counters.values()), 'inference attempted forbidden work')
        result['native_model_restore_attempts'] = sum(value['native_restore_attempts'] for value in result['constructor_observations'])
        result['native_model_restore_completions'] = sum(value['native_restore_completions'] for value in result['constructor_observations'])
        _require(result['native_model_restore_attempts'] == result['native_model_restore_completions'] == 6, 'six native private restores required')
        result['gpu_peak_allocated_bytes'] = torch.cuda.max_memory_allocated(device)
        _require(result['gpu_peak_allocated_bytes'] <= ROOT_GPU*1024**2, 'root GPU budget exceeded')
        result['actual_cuda_execution'] = result['qualified'] = True
    except BaseException as error:
        result['qualified'] = False
        result['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc(limit=14)}
    finally:
        if cancel is not None: cancel.clear()
        if owner is not None:
            try: owner.close()
            except BaseException as error: safe_close = False; result['unreturned_owner_cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
        for lane in active:
            try: lane.close(torch, device)
            except BaseException as error: safe_close = False; result.setdefault('cleanup_errors', []).append({'type': type(error).__name__, 'message': str(error)})
        owner = lane = probe = product = None
        gc.collect()
        if torch is not None and device is not None and safe_close:
            try: helpers['cleanup_helper']._cleanup_owned_cuda(torch, device, result)
            except BaseException as error: safe_close = False; result['cuda_cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
        if torch is not None and old_threads is not None:
            try:
                result['ambient_after_owned_cleanup_before_restore'] = helpers['coordinator_helpers']._settings(torch)
                _require(result['ambient_after_owned_cleanup_before_restore'] == result['ambient_reserved'], 'ambient policy not restored after owned cleanup')
                torch.set_num_threads(old_threads)
                result['ambient_after_thread_restore'] = helpers['coordinator_helpers']._settings(torch)
                _require(result['ambient_after_thread_restore'] == result['ambient_before'], 'ambient thread/default policy not restored')
            except BaseException as error:
                result['qualified'] = False; result['ambient_policy_error'] = {'type': type(error).__name__, 'message': str(error)}
                torch.set_num_threads(old_threads)
        for child, lane in zip(result['owned_children'], active): child['release_observed'] = lane.child_lease.released
        if parent is not None and safe_close and all(value['release_observed'] for value in result['owned_children']):
            try: parent.release()
            except BaseException as error: safe_close = False; result['root_release_error'] = {'type': type(error).__name__, 'message': str(error)}
        result['safe_owned_cleanup_established'] = safe_close
        result['root_release_observed'] = parent.released if parent is not None else False
        if scheduler is not None:
            try: result['resources_after'] = scheduler.snapshot()
            except BaseException as error: result['qualified'] = False; result['resource_snapshot_error'] = {'type': type(error).__name__, 'message': str(error)}
        result['elapsed_seconds_total'] = time.monotonic()-started
        result['elapsed_seconds_after_admission'] = time.monotonic()-admitted if admitted is not None else None
        result.update(counters)
        result['native_model_restore_attempts'] = sum(value['native_restore_attempts'] for value in result['constructor_observations'])
        result['native_model_restore_completions'] = sum(value['native_restore_completions'] for value in result['constructor_observations'])
        try:
            result['current_sources_fixtures_configuration_unchanged'] = all(helpers['coordinator_helpers']._pin(entry['current']['path']) == entry['current'] for entry in staged)
        except BaseException as error:
            result['current_sources_fixtures_configuration_unchanged'] = False
            result['currentness_error'] = {'type': type(error).__name__, 'message': str(error)}
        final_resources = result.get('resources_after', {})
        allocations = final_resources.get('allocated', {})
        final_zero = (type(allocations) is dict and set(allocations) == {'cpu_slots', 'memory_mb'}
            and all(type(value) is int and value == 0 for value in allocations.values())
            and all(type(final_resources.get(key)) is int and final_resources[key] == 0 for key in ('active_lease_count',
                'active_root_lease_count', 'active_child_lease_count', 'waiting_request_count',
                'allocated_gpu_memory_mb', 'allocated_unified_memory_mb', 'allocated_child_process_slots')))
        result['qualified'] = bool(result['qualified'] and result['error'] is None and safe_close and result['root_release_observed']
            and result['elapsed_seconds_after_admission'] <= MAX_SECONDS and result['current_sources_fixtures_configuration_unchanged']
            and final_zero and type(result.get('gpu_allocated_after_framework_workspace_clear_bytes')) is int
            and result['gpu_allocated_after_framework_workspace_clear_bytes'] == 0)
        if not result['qualified'] and result['error'] is None:
            result['error'] = {'type': 'QualificationClosureFailure', 'message': 'measurement/source/policy/deadline/resource closure not established'}
        result['evidence_limits'] = {'max_files': MAX_FILES, 'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES,
                                     'result_included_in_limits': True}
        if evidence is not None:
            result['evidence_files_except_result'], result['evidence_bytes_except_result'] = list(evidence.files), evidence.bytes
            evidence.json('result.json', result, final=True)
        else:
            raw = _wire(result); _require(len(raw) <= MAX_FILE_BYTES, 'bounded early refusal required')
            path = output/'result.json'
            with path.open('xb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            path.chmod(0o444)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dimension', type=int, choices=(768, 4096), required=True)
    parser.add_argument('--cohort', choices=('A', 'B'), required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--admission-timeout-seconds', type=int, default=60)
    arguments = parser.parse_args(); outcome = run(arguments)
    print(json.dumps({'qualified': outcome['qualified'], 'error': outcome['error'], 'namespace': arguments.namespace}, sort_keys=True))
    raise SystemExit(0 if outcome['qualified'] else 1)
