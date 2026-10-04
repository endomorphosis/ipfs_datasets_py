"""Bounded baseline/whole-call/deduplicated binding span comparison.

Each invocation owns one dimension and one fresh A/B cohort. All public calls
retain exact decisions and a separate guarded complete four-logit snapshot.
CUDA intervals have no Python observer attached. Only the outer request input
guard and duplicate binding registrations change; checkpoint, result, numerical
cache and lease guards stay fresh.
Ordinary artifacts confer no
execution attestation, proof, encoder provenance or production promotion.
"""
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
import sys
import time
import traceback

SCHEMA = 'span-deduplicated-input-guard-qualification/v1'
PREFIX = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
ROOT = Path('/home/barberb/lift_coding')
BASE = ROOT/'artifacts/codebase_ir_terminal_bench'
PACKAGE = ROOT/'external/ipfs_datasets'
CONFIG = BASE/'successor-expansion-resources-20261003-01/configuration.json'
CONFIG_SHA = 'c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575'
WHOLE_INPUT_SHA = '398611f204ce27194d6a0c5b739ad13d1387feeb626d250995ac97de42d17b20'
DEDUPLICATED_SHA = '451b162cf25c90681a7f372f421c52c9711a6267bc614f5fb8cc1c44f8831f34'
HELPERS = {
    'trained_helpers': ('qualify_bitwise_trained_head_devices', '29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110'),
    'dimension_helpers': ('profile_dimension_guard_costs_v6', 'c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0'),
    'coordinator_helpers': ('qualify_formula_guard_coordinator', 'e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8'),
    'cleanup_helper': ('qualify_native_768_device', '73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c'),
    'synthetic_helpers': ('qualify_synthetic_4096_head_device_v2', 'a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36'),
    'compatibility_probe_helpers': ('probe_cached_span_device_candidate_v2', '4a5e5a6c633f20c6886bbeecdf9bbc45b23c5c784d8fd5d55543acb18932ecc5'),
    'comparison_helpers': ('qualify_span_inference_candidates', 'a558fd42438f4471268d7d7c8f87f62ca0024570001c59bf3f5736328ff22258')}
CPU_LANES = ('baseline_cpu_opt_out', 'whole_input_cpu_opt_out', 'deduplicated_cpu_opt_out')
CUDA_LANES = ('baseline_cuda', 'whole_input_cuda', 'deduplicated_cuda')
COUNTS, PAIRS, MAX_SECONDS = (1, 16, 32), 12, 120
ORDERS = tuple(itertools.permutations(CUDA_LANES))*2
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 1024, 8*1024**2, 64*1024**2
ROOT_CPU, ROOT_RAM, ROOT_GPU, ROOT_UNIFIED = 3, 3072, 768, 3840
CHILD_RAM, CHILD_GPU, CHILD_UNIFIED = 1024, 256, 1280


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


def _native_controls(torch, lane, inputs, cancellation, input_guard, route):
    """Native caller aliases and the independent function-local snapshot."""
    controls, owner = [], lane.owner
    forward_code = owner._model.forward.__func__.__code__
    constructor_code = input_guard.InputContentGuard.__init__.__code__
    names = ('caller_input_alias_after_forward', 'caller_source_alias_after_forward',
             'paired_input_guard_reference_after_forward', 'input_guard_canonical_snapshot_after_forward',
             'input_guard_fast_mode_alias_after_forward', 'valid_input_guard_snapshot_after_forward',
             'paired_input_guard_nested_array_after_forward')
    fields = ('_reference', '_canonical_bytes', '_use_fast_comparison')
    for name in names:
        authored = deepcopy(inputs)
        texts, vectors = authored['texts'][:1], authored['vectors'][:1]
        options = {} if lane.dimension == 4096 else {'embedding_receipts': authored['receipts'][:1],
                                                    'expected_receipt_sha256s': authored['receipt_pins'][:1]}
        previous, forward_calls, constructor_calls = sys.getprofile(), 0, 0
        captured, snapshot, original_value = None, None, None
        replacement_content_matches = None
        nested_snapshot = None
        cpu_rng, gpu_rng = torch.get_rng_state(), torch.cuda.get_rng_state()

        def observe(frame, event, arg):
            nonlocal forward_calls, constructor_calls, captured, snapshot, original_value
            if event == 'call' and frame.f_code is forward_code:
                forward_calls += 1
            if event == 'return' and frame.f_code is constructor_code and arg is None:
                constructor_calls += 1
                if captured is None:
                    value = frame.f_locals.get('self')
                    _require(type(value) is input_guard.InputContentGuard,
                             'source-bound exact fresh whole-input guard constructor required')
                    captured = value
                    snapshot = tuple(getattr(captured, field) for field in fields)
                    original_value = deepcopy(frame.f_locals['value'])
            if previous is not None:
                previous(frame, event, arg)

        def mutate():
            nonlocal replacement_content_matches, nested_snapshot
            _require(captured is not None and snapshot is not None, 'fresh local input guard not observed before callback')
            if name in ('caller_input_alias_after_forward', 'paired_input_guard_reference_after_forward',
                        'paired_input_guard_nested_array_after_forward'):
                vectors[0][0] += .25
            elif name == 'caller_source_alias_after_forward':
                texts[0] += ' changed'
            if name in ('paired_input_guard_reference_after_forward', 'valid_input_guard_snapshot_after_forward'):
                current = deepcopy(original_value)
                if name == 'paired_input_guard_reference_after_forward':
                    current['vectors'][0][0] += .25
                replacement = input_guard.InputContentGuard(current)
                _require(replacement._reference is not captured._reference,
                         'replacement must have a distinct immutable root snapshot')
                replacement_content_matches = replacement.matches(current)
                _require(replacement_content_matches is True, 'fresh replacement content must compare successfully')
                for field in fields:
                    object.__setattr__(captured, field, getattr(replacement, field))
            elif name == 'input_guard_canonical_snapshot_after_forward':
                object.__setattr__(captured, '_canonical_bytes', b'changed')
            elif name == 'input_guard_fast_mode_alias_after_forward':
                _require(captured._use_fast_comparison is True, 'authored finite inputs must use the structural path')
                object.__setattr__(captured, '_use_fast_comparison', 1)
            elif name == 'paired_input_guard_nested_array_after_forward':
                current = deepcopy(original_value)
                current['vectors'][0][0] += .25
                replacement = input_guard.InputContentGuard(current)
                old_array = dict(captured._reference.fields)['vectors'].items[0]
                new_array = dict(replacement._reference.fields)['vectors'].items[0]
                _require(type(old_array) is type(new_array) is input_guard._Array
                         and old_array.atoms is True and old_array.items is not new_array.items,
                         'complete native vector atom array snapshot seam required')
                nested_snapshot = old_array, old_array.items, old_array.atoms
                object.__setattr__(old_array, 'items', new_array.items)
                _require(captured._reference is snapshot[0], 'nested control must retain original immutable root identity')
                replacement_content_matches = captured.matches(current)
                _require(replacement_content_matches is True, 'coordinated nested snapshot must otherwise match changed caller')

        cancellation.owner, cancellation.family, cancellation.action = owner, 'span', mutate
        refusal = None
        try:
            sys.setprofile(observe)
            owner.decode_formal_logic(texts, vectors, **options)
        except (ValueError, RuntimeError, TimeoutError) as error:
            expected = ('checkpoint content changed' if name in names[:2]
                        else 'whole-input independent local guard or immutable snapshot changed')
            _require(type(error) is ValueError and str(error) == expected and forward_calls > 0
                     and cancellation.triggered and captured is not None,
                     'whole-input custody refused at an unexpected boundary')
            refusal = str(error)
        else:
            raise ValueError('span whole-input candidate accepted native caller or snapshot mutation')
        finally:
            sys.setprofile(previous)
            if captured is not None and snapshot is not None:
                for field, value in zip(fields, snapshot):
                    object.__setattr__(captured, field, value)
            if nested_snapshot is not None:
                nested, items, atoms = nested_snapshot
                object.__setattr__(nested, 'items', items)
                object.__setattr__(nested, 'atoms', atoms)
            cancellation.clear()
        _require(captured is not None and all(getattr(captured, field) is value for field, value in zip(fields, snapshot)),
                 'original per-call input snapshot identities not restored')
        if nested_snapshot is not None:
            _require(nested_snapshot[0].items is nested_snapshot[1] and nested_snapshot[0].atoms is nested_snapshot[2],
                     'original nested reference wrapper fields not restored')
        _require(torch.equal(cpu_rng, torch.get_rng_state()) and torch.equal(gpu_rng, torch.cuda.get_rng_state()),
                 'native input custody control changed RNG')
        lane.describe()
        controls.append({'control': name, 'route': route, 'refused': True, 'refusal': refusal,
            'actual_model_forward_calls': forward_calls, 'before_forward_refusal': False,
            'post_forward_callback_executed': True, 'fresh_input_guard_constructor_observed': True,
            'input_guard_constructor_calls': constructor_calls,
            'input_guard_constructor_source_role': 'input_content_guard',
            'input_guard_constructor_source_sha256': 'aa3fefbe8a1ab4d81bf61ae9edf395a9070b3c0f94b728ee6fa5ddca0c81c325',
            'input_guard_constructor_method': 'InputContentGuard.__init__',
            'original_input_guard_snapshot_identities_restored': True,
            'original_nested_reference_wrapper_identities_restored': True if nested_snapshot is not None else None,
            'replacement_guard_current_content_matches': replacement_content_matches,
            'cpu_cuda_rng_unchanged': True,
            'scope': 'source_bound_local_input_guard_and_actual_caller_aliases_after_observed_forward_only',
            'proof_authority': False, 'execution_attestation': False})
    return controls


def _cancel_after_measurements(lane, inputs, route):
    """Actually revoke this owned child only after all measurements."""
    owner, previous, forward_calls = lane.owner, sys.getprofile(), 0
    code = owner._model.forward.__func__.__code__
    def observe(frame, event, arg):
        nonlocal forward_calls
        if event == 'call' and frame.f_code is code: forward_calls += 1
        if previous is not None: previous(frame, event, arg)
    _require(owner._lease.cancel() is True and not owner._lease.released, 'actual own child cancellation required')
    snapshot = owner._scheduler.snapshot()
    try:
        sys.setprofile(observe)
        lane.call(inputs, 1)
    except (ValueError, RuntimeError, TimeoutError) as error:
        expected = ('768D device lease revoked or expired' if lane.dimension == 768
                    else 'native4096 device lease revoked or expired')
        _require(type(error) is RuntimeError and str(error) == expected
                 and forward_calls == 0, 'actual revoked child was not refused before forward')
        return {'control': 'actual_owned_child_cancel_after_measurements', 'route': route, 'refused': True,
            'refusal': str(error), 'actual_model_forward_calls': 0, 'before_forward_refusal': True,
            'post_forward_callback_executed': False, 'child_cancel_requested': True,
            'owned_child_lease_id': owner._lease.lease_id, 'released_before_close': False,
            'resources_after_cancel_before_close': snapshot,
            'scope': 'actual_owned_child_only_revocation_after_all_public_measurements_and_state_joins',
            'proof_authority': False, 'execution_attestation': False}
    else: raise ValueError('span whole-input candidate accepted actual own child cancellation')
    finally: sys.setprofile(previous)


def run(args):
    _require(type(args.dimension) is int and args.dimension in (768, 4096)
             and type(args.cohort) is str and args.cohort in ('A', 'B'), 'exact dimension/cohort required')
    _require(type(args.admission_timeout_seconds) is int and 1 <= args.admission_timeout_seconds <= 60, 'admission1..60seconds required')
    _require(type(args.namespace) is str and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', args.namespace), 'fresh relative namespace required')
    _require(all(len(pin) == 64 and all(value in '0123456789abcdef' for value in pin)
                 for pin in (WHOLE_INPUT_SHA, DEDUPLICATED_SHA)), 'final candidate source pins required')
    output = BASE/args.namespace; output.mkdir()
    result = {'schema': SCHEMA, 'qualified': False, 'error': None, 'dimension': args.dimension, 'cohort': args.cohort,
        'performance_qualified': False, 'proof_authority': False, 'execution_attestation': False,
        'production_qualified': False, 'selected_existing_profile_changed': False, 'native_leanstral_outputs_qualified': False,
        'trained4096_qualification_established': False, 'native_due_renewal_qualified': False, 'native_lease_expiry_qualified': False,
        'source_pins': [], 'fixture_pins': [], 'lanes': {}, 'counts': {}, 'owned_children': [], 'constructor_observations': [],
        'expected_positive_inventory': {'source_files': 34, 'archive_files': 293, 'current_pins': 37},
        'native_control_routes': ['whole_input_cuda', 'deduplicated_cuda'],
        'public_return_count': 0, 'complete_four_logit_snapshot_count': 0, 'timed_return_count': 0,
        'numeric_tolerance_absolute': 5e-5, 'encoder_execution_performed': False, 'shared_configuration_changed': False,
        'actual_cuda_execution': False, 'max_seconds_after_admission': MAX_SECONDS,
        'admission_timeout_seconds': args.admission_timeout_seconds, 'paired_samples_per_route_per_count': PAIRS,
        'timing_scope': 'complete_guarded_public_call_and_completion_sync_input_copy_before_interval_no_profiler',
        'span_numeric_scope': 'one_separate_complete_checked_four_logit_snapshot_after_every_public_return_outside_timing',
        'counter_scope': 'constructors_CPU_references_CUDA_warmups_controls_and_separate_numeric_only_not_timed_CUDA',
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
        synthetic, cleanup, prior, comparison = (helpers[key] for key in ('synthetic_helpers', 'cleanup_helper', 'compatibility_probe_helpers', 'comparison_helpers'))
        evidence = trained.Evidence(output)
        names = (*prior.MODULES, 'legal_span_whole_input_guard_device_inference',
                 'legal_span_deduplicated_whole_input_guard_device_inference')
        paths = {name: PACKAGE/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/(name+'.py') for name in names}
        paths.update({'benchmark': Path(__file__).absolute(), **helper_paths,
            'tree_pin': PACKAGE/'ipfs_datasets_py/logic/autoformal/tree_pin.py',
            'canonical_contracts': PACKAGE/'ipfs_datasets_py/logic/legal_ir/canonical_contracts.py',
            'cid_utils': PACKAGE/'ipfs_datasets_py/utils/cid_utils.py'})
        fixed = {**prior.FIXED, 'legal_span_whole_input_guard_device_inference': WHOLE_INPUT_SHA,
                 'legal_span_deduplicated_whole_input_guard_device_inference': DEDUPLICATED_SHA,
                 **{role: sha for role, (_, sha) in HELPERS.items()}}
        _require(len(paths) == 34, 'exact34 producer source roles required')
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
        result['physical_input_limits'] = comparison._bound_inputs(inputs, args.dimension)
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
        parent = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=ROOT_CPU, memory_mb=ROOT_RAM,
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
        whole_input = modules['legal_span_whole_input_guard_device_inference']
        deduplicated = modules['legal_span_deduplicated_whole_input_guard_device_inference']
        classes = ({'baseline': whole_input._BASE_768, 'whole_input': whole_input.WholeInputDeviceDimensionalSpanSession,
                    'deduplicated': deduplicated.DeduplicatedWholeInputDeviceDimensionalSpanSession}
                   if args.dimension == 768 else
                   {'baseline': whole_input._BASE_4096, 'whole_input': whole_input.WholeInputDeviceLeanstral4096SpanSession,
                    'deduplicated': deduplicated.DeduplicatedWholeInputDeviceLeanstral4096SpanSession})

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
                    with comparison._restore_observer(torch, restore_module, method, receipt):
                        owner = classes[route](deepcopy(checkpoint), **options)
                _require(receipt['native_restore_attempts'] == receipt['native_restore_completions'] == 1, 'one validated private model restore required')
                _require(coordinator._settings(torch) == result['ambient_reserved'], 'constructor changed ambient policy')
                lane = dimension_helper.DimensionLane(owner, args.dimension); active.append(lane)
                child = {'lane': label, 'admission': lane.child_lease.to_dict(), 'release_observed': False}
                result['owned_children'].append(child)
                receipt['completed'] = True
                record = result['lanes'][label] = {'constructor': deepcopy(receipt), 'profile': lane.describe(),
                    'state_before': trained._state_pin(owner, 'span'), 'counts': {}}
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
            canonical = trained._decisions(report, 'span')
            if label == 'baseline_cpu_opt_out': references[count] = canonical
            _require(canonical == references[count] and report['cuda_executed'] is label.endswith('_cuda'), 'complete public canonical/device equality differs')
            observed['complete_decisions_match_original_CPU'] = True
            with dimension_helper._forbidden_calls(torch, modules, counters):
                values, scope = comparison._numeric_snapshot(torch, modules, lane, authored, count, trained, dimension_helper, synthetic)
            _require(torch.equal(cpu_rng, torch.get_rng_state()) and torch.equal(gpu_rng, torch.cuda.get_rng_state(device)), 'checked numeric snapshot changed RNG')
            if label == 'baseline_cpu_opt_out': numeric_references[count] = values
            observed.update(four_logits=evidence.json(stem+'-four-logits.json', values), four_logit_scope=scope)
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
            for left, right in (('baseline', 'whole_input'), ('baseline', 'deduplicated'), ('whole_input', 'deduplicated')):
                key = left+'_over_'+right
                ratios = [a/b for a,b in zip(samples[left+'_cuda'], samples[right+'_cuda'])]
                entry['median_'+key+'_ratio'] = medians[left+'_cuda']/medians[right+'_cuda']
                entry['paired_'+key+'_ratios'] = ratios
                entry['paired_'+key+'_min_ratio'], entry['paired_'+key+'_max_ratio'] = min(ratios), max(ratios)

        result['native_controls'] = []
        with dimension_helper._forbidden_calls(torch, modules, counters):
            for label in result['native_control_routes']:
                result['native_controls'].extend(_native_controls(torch, gpu_lanes[label], inputs, cancel,
                                                                 modules['input_content_guard'], label))
        for label, lane in gpu_lanes.items():
            result['lanes'][label]['state_after'] = trained._state_pin(lane.owner, 'span')
            _require(result['lanes'][label]['state_after'] == result['expected_model_pin'] and lane.owner._checkpoint == checkpoint, 'CUDA model/checkpoint changed')
        with dimension_helper._forbidden_calls(torch, modules, counters):
            for label in result['native_control_routes']:
                result['native_controls'].append(_cancel_after_measurements(gpu_lanes[label], inputs, label))
        _require(len(result['native_controls']) == 16, 'sixteen distinct candidate-route native controls required')
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
