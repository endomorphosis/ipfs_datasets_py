"""Bounded native compatibility probe of retained 768D/4096D cache candidates.

Single CUDA observations are diagnostics, not repeatable performance evidence.
Complete public decisions and separate four-logit snapshots use fixed retained
fixtures. No fitting, encoders, production promotion or proof authority.
"""
import argparse
from copy import deepcopy
import gc
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

PREFIX = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
ROOT = Path('/home/barberb/lift_coding')
BASE = ROOT/'artifacts/codebase_ir_terminal_bench'
PACKAGE = ROOT/'external/ipfs_datasets'
CONFIG = BASE/'successor-expansion-resources-20261003-01/configuration.json'
CONFIG_SHA = 'c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575'
FIXTURES = {
    768: ('native-768-device-qualification-20261004-04/diagnostic-native768-head.json',
          '9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b',
          'dimension-768-guard-cost-profile-20261004-03/dimension-inference-inputs.json',
          '1b29ffd8b62d628aa8d6823f5e5a2b702a710357add2f4337b6243b7ca117090'),
    4096: ('native-4096-synthetic-head-device-v2-qualification-20261004-04/synthetic-untrained-checkpoint.json',
           '04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7',
           'dimension-4096-guard-cost-profile-20261004-04/dimension-inference-inputs.json',
           '2c4e4ac0053871c902c5aebb423ee2ccd1345fa46ad6c28234a45b10eaada388')}
MODULES = ('resource_scheduler', 'legal_span_formula', 'legal_span_dimensions', 'legal_span_device_inference',
    'legal_span_device_batch_inference', 'legal_span_device_bitwise_inference', 'legal_span_4096',
    'legal_span_4096_device_inference', 'legal_span_4096_bitwise_device_inference',
    'legal_span_4096_bitwise_device_inference_v2', 'legal_span_cached_input_device_inference',
    'input_content_guard', 'owned_tensor_value_guard', 'owned_tensor_bitwise_guard',
    'checkpoint_content_guard', 'runtime_telemetry', 'proof_resource_safety', 'legal_formula_codec',
    'legal_ir_grammar_decoder', 'legal_ir_family_evaluator', 'snapshot_evaluator')
FIXED = {'resource_scheduler': 'f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa',
    'legal_span_cached_input_device_inference': 'ec07cb2d502c0e1aedbdb3c11d29348fbddf438982dfbab4c07368a85391eb70',
    'input_content_guard': 'aa3fefbe8a1ab4d81bf61ae9edf395a9070b3c0f94b728ee6fa5ddca0c81c325',
    'legal_span_device_bitwise_inference': 'd1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91',
    'legal_span_4096_bitwise_device_inference_v2': '14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3'}


def load_helper(name, expected=None):
    path = Path(__file__).with_name(name+'.py')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert expected is None or digest == expected
    spec = importlib.util.spec_from_file_location('_cached_span_'+name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    return module, path, digest


def run(args):
    output = BASE/args.namespace
    assert args.namespace and '/' not in args.namespace and args.namespace not in ('.', '..')
    output.mkdir()
    trained, trained_path, _ = load_helper('qualify_bitwise_trained_head_devices',
        '29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110')
    dimension_helper, dimension_path, dimension_sha = load_helper('profile_dimension_guard_costs_v6',
        'c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0')
    coordinator, coordinator_path, _ = load_helper('qualify_formula_guard_coordinator',
        'e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8')
    cleanup, cleanup_path, _ = load_helper('qualify_native_768_device',
        '73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c')
    synthetic, synthetic_path, _ = load_helper('qualify_synthetic_4096_head_device_v2',
        'a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36')
    evidence = trained.Evidence(output)
    result = {'schema': 'cached-span-native-compatibility-probe/v1', 'qualified': False, 'error': None,
        'dimension': args.dimension, 'performance_qualified': False, 'proof_authority': False,
        'execution_attestation': False, 'production_qualified': False, 'selected_existing_profile_changed': False,
        'native_leanstral_outputs_qualified': False, 'trained4096_qualification_established': False,
        'source_pins': [], 'fixture_pins': [], 'lanes': {}, 'owned_children': [],
        'public_return_count': 0, 'complete_four_logit_snapshot_count': 0,
        'timing_scope': 'one_uninstrumented_complete_call_per_CUDA_route_count_no_repeatability_claim',
        'counter_scope': 'constructors_CPU_calls_and_separate_numeric_snapshots_only_not_timed_CUDA',
        'numeric_tolerance_absolute': 5e-5, 'encoder_execution_performed': False,
        'max_seconds_after_admission': 120, 'shared_configuration_changed': False,
        'actual_cuda_execution': False, 'dimension_helper_source_sha256': dimension_sha}
    staged, active, refs, numeric_refs = [], [], {}, {}
    scheduler = parent = torch = device = cancel = None
    old_threads = admitted = None
    safe_close = True
    counters = dict.fromkeys(('optimizer_constructor_calls', 'optimizer_steps', 'new_training_fits', 'training_mode_true_calls'), 0)
    started = time.monotonic()
    try:
        paths = {name: PACKAGE/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/(name+'.py') for name in MODULES}
        paths.update({'benchmark': Path(__file__).absolute(), 'trained_helpers': trained_path,
            'dimension_helpers': dimension_path, 'coordinator_helpers': coordinator_path,
            'cleanup_helper': cleanup_path, 'synthetic_helpers': synthetic_path,
            'tree_pin': PACKAGE/'ipfs_datasets_py/logic/autoformal/tree_pin.py',
            'canonical_contracts': PACKAGE/'ipfs_datasets_py/logic/legal_ir/canonical_contracts.py',
            'cid_utils': PACKAGE/'ipfs_datasets_py/utils/cid_utils.py'})
        for index, (name, path) in enumerate(paths.items()):
            _, entry = evidence.retain(f'{index:02d}-{path.name}', path, name, FIXED.get(name))
            result['source_pins'].append(entry); staged.append(entry)
        raw, config_entry = evidence.retain('configuration.json', CONFIG, 'configuration', CONFIG_SHA)
        result['shared_configuration'] = config_entry; staged.append(config_entry)
        cp_path, cp_sha, inputs_path, inputs_sha = FIXTURES[args.dimension]
        cp_raw, cp_entry = evidence.retain('checkpoint.json', BASE/cp_path, 'checkpoint', cp_sha)
        input_raw, input_entry = evidence.retain('inputs.json', BASE/inputs_path, 'inputs', inputs_sha)
        result['fixture_pins'] = [cp_entry, input_entry]; staged.extend(result['fixture_pins'])
        checkpoint, inputs = json.loads(cp_raw), json.loads(input_raw)
        result['retained_progress'] = deepcopy(checkpoint['progress'])
        assert checkpoint['progress']['optimizer_steps'] == (1 if args.dimension == 768 else 0)
        result['checkpoint_sha256'] = cp_sha
        result['expected_model_pin'] = {'bytes': len(trained._wire(checkpoint['model_state'])),
            'sha256': hashlib.sha256(trained._wire(checkpoint['model_state'])).hexdigest()}
        assert not any(PREFIX+name in sys.modules for name in MODULES if name != 'resource_scheduler')
        resources = importlib.import_module(PREFIX+'resource_scheduler')
        config = json.loads(raw)
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(**config['persisted_config'],
            state_path=config['state_path'], lease_ttl_seconds=config['lease_ttl_seconds'], auto_renew_leases=config['auto_renew_leases']))
        result['resources_before'] = scheduler.snapshot()
        parent = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=2, memory_mb=2048,
            gpu_memory_mb=512, unified_memory_mb=2560, requires_gpu=True, timeout=60, request_id=args.namespace)
        admitted = time.monotonic(); result['admission'] = parent.to_dict()
        cancel = trained.Cancellation(parent, admitted+120)
        import torch as actual_torch
        torch = actual_torch
        old_threads = torch.get_num_threads(); result['ambient_before'] = coordinator._settings(torch)
        torch.set_num_threads(1); result['ambient_reserved'] = coordinator._settings(torch)
        assert torch.cuda.is_available() and sys.getprofile() is None
        device = torch.cuda.current_device()
        result['hardware'] = {'torch': str(torch.__version__), 'cuda_runtime': torch.version.cuda,
            'name': torch.cuda.get_device_name(device), 'capability': list(torch.cuda.get_device_capability(device)),
            'actual_initial_cuda_kernel': synthetic._initial_kernel(torch, device) == [4.]}
        assert result['hardware']['actual_initial_cuda_kernel'] is True
        result['gpu_allocated_before_owned_sessions_bytes'] = torch.cuda.memory_allocated(device)
        assert result['gpu_allocated_before_owned_sessions_bytes'] == 0
        torch.cuda.reset_peak_memory_stats(device)
        modules = {name: importlib.import_module(PREFIX+name) for name in MODULES}
        assert all(Path(module.__file__).absolute() == paths[name] for name, module in modules.items())
        for entry in staged:
            assert coordinator._pin(entry['current']['path']) == entry['current']
        api, span, batch = modules['legal_span_cached_input_device_inference'], modules['legal_span_formula'], modules['legal_span_device_batch_inference']
        classes = ({'baseline': api._BASE_768, 'candidate': api.InputCachedDeviceDimensionalSpanSession} if args.dimension == 768 else
            {'baseline': api._BASE_4096, 'candidate': api.InputCachedDeviceLeanstral4096SpanSession})
        for optimized in (False, True):
            for route, cls in classes.items():
                options = dict(expected_checkpoint_sha256=cp_sha, optimized=optimized, scheduler=scheduler,
                    parent_lease=parent, cancel_event=cancel, admission_timeout_seconds=60,
                    max_seconds=120, memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=1280)
                if args.dimension == 4096: options['synthetic_unreceipted'] = True
                with dimension_helper._forbidden_calls(torch, modules, counters):
                    owner = cls(deepcopy(checkpoint), **options)
                lane = dimension_helper.DimensionLane(owner, args.dimension); active.append(lane)
                label = route+('_cuda' if optimized else '_cpu_opt_out')
                child = {'lane': label, 'admission': lane.child_lease.to_dict(), 'release_observed': False}
                result['owned_children'].append(child)
                record = result['lanes'][label] = {'profile': lane.describe(), 'state_before': trained._state_pin(owner, 'span'), 'counts': {}}
                assert record['state_before'] == result['expected_model_pin']
                for count in (1, 16, 32):
                    cancel.poll()
                    cpu_rng, gpu_rng = torch.get_rng_state(), torch.cuda.get_rng_state(device)
                    if optimized:
                        assert sys.getprofile() is None
                        torch.cuda.synchronize(device)
                        mark = time.monotonic(); report = lane.call(inputs, count); torch.cuda.synchronize(device)
                        elapsed = time.monotonic()-mark
                    else:
                        with dimension_helper._forbidden_calls(torch, modules, counters): report = lane.call(inputs, count)
                        elapsed = None
                    assert torch.equal(cpu_rng, torch.get_rng_state()) and torch.equal(gpu_rng, torch.cuda.get_rng_state(device))
                    canonical = trained._decisions(report, 'span')
                    if label == 'baseline_cpu_opt_out': refs[count] = canonical
                    assert canonical == refs[count]
                    assert report['cuda_executed'] is optimized
                    result['public_return_count'] += 1
                    with dimension_helper._forbidden_calls(torch, modules, counters):
                        if args.dimension == 768:
                            values, scope = trained._span_logits(torch, span, batch, lane, inputs, count, singleton=not optimized)
                        else:
                            records = [{'tokens': span.tokenize_source(text), 'latent': vector}
                                for text, vector in zip(inputs['texts'][:count], inputs['vectors'][:count])]
                            if optimized:
                                raw_values, scope = synthetic._checked_private_logits(torch, span, owner, records)
                                values = dimension_helper._rows_from_batched_logits(raw_values, [len(row['tokens']) for row in records])
                            else:
                                values, scopes = [], []
                                for item in records:
                                    raw_values, one_scope = synthetic._checked_private_logits(torch, span, owner, [item])
                                    values.extend(dimension_helper._rows_from_batched_logits(raw_values, [len(item['tokens'])]))
                                    scopes.append(one_scope)
                                scope = {'singletons': True, 'separate_checked_private_four_logits': True, 'observations': scopes}
                    if label == 'baseline_cpu_opt_out': numeric_refs[count] = values
                    errors = trained._four_errors(numeric_refs[count], values)
                    result['complete_four_logit_snapshot_count'] += 1
                    record['counts'][str(count)] = {'report': evidence.json(f'{label}-{count}-report.json', report),
                        'four_logits': evidence.json(f'{label}-{count}-four-logits.json', values),
                        'four_logit_scope': scope, 'four_logit_max_abs_errors': errors,
                        'complete_decisions_match_original_CPU': True, 'cpu_cuda_rng_unchanged': True,
                        'unprofiled_cuda_elapsed_seconds': elapsed}
                record['state_after'] = trained._state_pin(owner, 'span')
                assert record['state_after'] == record['state_before'] and owner._checkpoint == checkpoint
                lane.close(torch, device); child['release_observed'] = lane.child_lease.released
                owner = lane = None
        result['gpu_peak_allocated_bytes'] = torch.cuda.max_memory_allocated(device)
        assert result['gpu_peak_allocated_bytes'] <= 512*1024**2
        result['actual_cuda_execution'] = result['qualified'] = True
        assert result['public_return_count'] == result['complete_four_logit_snapshot_count'] == 12
    except BaseException as error:
        result['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc(limit=12)}
    finally:
        if cancel is not None: cancel.clear()
        for lane in active:
            try: lane.close(torch, device)
            except BaseException as error:
                safe_close = False; result['cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
        if torch is not None and device is not None and safe_close:
            try: cleanup._cleanup_owned_cuda(torch, device, result)
            except BaseException as error:
                safe_close = False; result['cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
        if torch is not None and old_threads is not None:
            try:
                assert coordinator._settings(torch) == result['ambient_reserved']
                torch.set_num_threads(old_threads)
                assert coordinator._settings(torch) == result['ambient_before']
            except BaseException as error:
                result['qualified'] = False
                result['ambient_policy_error'] = {'type': type(error).__name__, 'message': str(error)}
                torch.set_num_threads(old_threads)
        for child, lane in zip(result['owned_children'], active): child['release_observed'] = lane.child_lease.released
        if parent is not None and safe_close and all(child['release_observed'] for child in result['owned_children']):
            try: parent.release()
            except BaseException as error:
                safe_close = False; result['root_release_error'] = {'type': type(error).__name__, 'message': str(error)}
        result['safe_owned_cleanup_established'] = safe_close
        result['root_release_observed'] = parent.released if parent is not None else False
        if scheduler is not None:
            try: result['resources_after'] = scheduler.snapshot()
            except BaseException as error:
                result['qualified'] = False; result['resource_snapshot_error'] = {'type': type(error).__name__, 'message': str(error)}
        result['elapsed_seconds_total'] = time.monotonic()-started
        result['elapsed_seconds_after_admission'] = time.monotonic()-admitted if admitted is not None else None
        result.update(counters)
        try:
            result['current_sources_fixtures_configuration_unchanged'] = all(coordinator._pin(entry['current']['path']) == entry['current'] for entry in staged)
        except BaseException as error:
            result['current_sources_fixtures_configuration_unchanged'] = False
            result['currentness_error'] = {'type': type(error).__name__, 'message': str(error)}
        result['qualified'] = (result['qualified'] and result['error'] is None and safe_close and result['root_release_observed']
            and result['elapsed_seconds_after_admission'] <= 120 and result['current_sources_fixtures_configuration_unchanged']
            and result.get('resources_after', {}).get('active_lease_count') == 0
            and result.get('resources_after', {}).get('waiting_request_count') == 0)
        if result['qualified']:
            snapshot = result['resources_after']
            result['qualified'] = (type(snapshot['allocated']) is dict
                and set(snapshot['allocated']) == {'cpu_slots', 'memory_mb'}
                and all(type(value) is int and value == 0 for value in snapshot['allocated'].values())
                and all(type(snapshot[key]) is int and snapshot[key] == 0 for key in ('active_lease_count',
                    'active_root_lease_count', 'active_child_lease_count', 'waiting_request_count',
                    'allocated_gpu_memory_mb', 'allocated_unified_memory_mb', 'allocated_child_process_slots')))
        if not result['qualified'] and result['error'] is None:
            result['error'] = {'type': 'DiagnosticClosureFailure', 'message': 'compatibility or owned resource closure did not qualify'}
        result['evidence_files_except_result'] = list(evidence.files)
        result['evidence_bytes_except_result'] = evidence.bytes
        evidence.json('result.json', result, final=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dimension', type=int, choices=(768, 4096), required=True)
    parser.add_argument('--namespace', required=True)
    args = parser.parse_args(); result = run(args)
    print(json.dumps({'qualified': result['qualified'], 'error': result['error'], 'namespace': args.namespace}, sort_keys=True))
    raise SystemExit(0 if result['qualified'] else 1)
