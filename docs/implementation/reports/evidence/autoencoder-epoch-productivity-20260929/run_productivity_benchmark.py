#!/usr/bin/env python3
"""Bounded, fixed-parent native optimizer ablation. No promotion or Hub activity.

Prepare only with --prepare; execute only after producer source freeze. Every arm
uses eight synthetic training rows, one tuning row, and the identical seed. The
selected and baseline-reference canaries are evaluated after a tuning-only arm choice has been sealed.
"""
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
import argparse
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import traceback

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
ARMS = {'baseline_adaptive': ('guarded_adaptive', 0.5), 'productive_lr': ('productive_adaptive', 0.0),
        'productive_momentum': ('productive_adaptive', 0.5)}
INTEGRATED_ARMS = {'productive_momentum_refined': ('productive_adaptive', 0.5)}

def arms_for(config):
    return INTEGRATED_ARMS if config.get('experiment') == 'integrated' else ARMS

def refinement_for(config):
    return 3 if config.get('experiment') == 'integrated' else 0
BRIDGES = ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router']
PINNED = ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
PINNED_SHA = '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
LEDGER = ROOT / 'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'


RUN_ENV = {'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0', 'CUDA_VISIBLE_DEVICES': '',
    'IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA': '0', 'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0',
    'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'OPENBLAS_NUM_THREADS': '1',
    'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'PYTHONPATH': str(ROOT)}


def configure_environment():
    # Apply in parent, coordinator child and spawned workers before package imports.
    os.environ.update(RUN_ENV)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return {key: os.environ[key] for key in RUN_ENV}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def read(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('evidence JSON exceeds bound')
    return json.loads(path.read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def cli():
    configure_environment()
    path = ROOT / 'scripts/ops/legal_ir/run_incremental_autoencoders.py'
    spec = importlib.util.spec_from_file_location('convergence_existing_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_map():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _source_entries
    entries = _source_entries(ROOT / 'ipfs_datasets_py')
    return {'producer_manifest': {'sha256': digest(entries), 'file_count': len(entries)}, 'files': entries}


def records():
    def row(n):
        return {'title': 'synthetic-duration-ablation', 'section': str(n),
                'text': f'The officer shall retain the file for at least {n} days.',
                'embedding_model': 'mock:stable-sha256'}
    return {'training': [row(n) for n in range(20, 28)], 'tuning': [row(30)], 'canary': [row(34), row(35)]}


def plan(config):
    return {'schema': 'autoencoder-epoch-productivity-plan/v1', 'arms': arms_for(config), 'experiment': config['experiment'],
            'optional_integrated_prespecification': {'arm': INTEGRATED_ARMS, 'composed_refinement_attempts': 3,
                'automatically_launched': False, 'canary_evaluation': False, 'all_other_work_limits_unchanged': True,
                'separate_resource_admission_required': True, 'storage_bytes': 250000000, 'alternative_storage_bytes': 500000000},
            'samples': records(), 'sample_counts': {'training': 8, 'tuning': 1, 'canary': 2},
            'split_scope': 'Synthetic nearby-duration templates; disjoint within this experiment, seed pretraining exclusion unknown. Not a federal-law canary.',
            'seed': {'path': str(PINNED), 'sha256': PINNED_SHA, 'bytes': 25895338},
            'training': {'epochs': 5, 'learning_rate': .35, 'max_seconds': 180,
                         'max_line_search_attempts': 2, 'projection_max_update_families': 5,
                         'projection_max_composed_refinement_attempts': refinement_for(config),
                         'projection_update_backend': 'python_sparse_batch'},
            'bridge_names': BRIDGES, 'legal_ir_evaluate_provers': False,
            'metric_disk_cache': 0, 'legal_ir_parallel_workers': 1, 'use_sample_memory': False,
            'model_config': {'compute_device': 'python'}, 'temperature': 0,
            'cache_scope': 'Fresh spawned worker per arm; no supplied targets; disk target cache disabled. In-job memory reuse measured. OS caches uncontrolled.',
            'resources': {key: config[key] for key in ('memory_mb', 'storage_bytes', 'cycle_timeout')},
            'selection': 'Main experiment only: minimum final tuning objective among fully qualified arms; if none qualify, minimum final tuning objective for diagnostic canary evaluation only. Seal choice before any canary evaluation. Evaluate selected arm and baseline_adaptive final candidate on canaries; never use those outcomes for selection. Integrated diagnostic is prespecified, does not inspect canaries, and has no arm-selection comparison.',
            'admitted': False, 'promotion_performed': False, 'hub_publication_performed': False,
            'global_minimum_claim': False}


def objective(evaluation, weights):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import _evaluation_objective_for_training
    return _evaluation_objective_for_training(SimpleNamespace(**evaluation), **weights)


def compact_metrics(evaluation):
    return {key: evaluation.get(key) for key in ('sample_count', 'legal_ir_target_count',
        'reconstruction_loss', 'embedding_cosine_similarity', 'cross_entropy_loss',
        'cross_entropy_excess_loss', 'cross_entropy_entropy_loss', 'legal_ir_losses', 'legal_ir_view_family_metrics')}


def summarize_worker(worker):
    report = worker['training_report']
    weights = report['objective_weights']
    before, after = (objective(report[key], weights) for key in ('before', 'after'))
    current, cumulative_tuning_calls = before, 1
    curve = [{'epoch': 0, 'committed_objective': before, 'accepted': None,
              'cumulative_tuning_search_evaluations': 1, 'cumulative_training_elapsed_seconds': None}]
    productivity = defaultdict(lambda: {'attempts': 0, 'tuning_evaluations': 0, 'accepted_attempts': 0,
        'accepted_candidates_not_selected': 0, 'finite_objective_deltas': [],
        'cross_entropy_deltas': [], 'gradient_norms': [], 'update_norms': []})
    for epoch in report['epoch_reports']:
        for candidate in epoch.get('candidate_reports', []):
            bucket = productivity[candidate.get('update', 'unknown')]
            if candidate.get('accepted') and candidate.get('update') != epoch.get('selected_update'):
                bucket['accepted_candidates_not_selected'] += 1
            for trial in candidate.get('attempt_reports') or [candidate]:
                bucket['attempts'] += 1
                evaluated = trial.get('holdout_evaluated') is True
                bucket['tuning_evaluations'] += int(evaluated)
                cumulative_tuning_calls += int(evaluated)
                bucket['accepted_attempts'] += int(trial.get('accepted') is True)
                for source, dest in (('objective_delta', 'finite_objective_deltas'),
                                     ('cross_entropy_delta', 'cross_entropy_deltas')):
                    value = trial.get(source)
                    if evaluated and isinstance(value, (int, float)) and math.isfinite(value):
                        bucket[dest].append(value)
                for source, dest in (('gradient_norms_by_head', 'gradient_norms'), ('update_norms_by_head', 'update_norms')):
                    bucket[dest].extend(value for value in trial.get(source, {}).values()
                                        if isinstance(value, (int, float)) and math.isfinite(value))
                norms = trial.get('trainable_legal_ir_head_norms', {})
                for source, dest in (('gradient_norm', 'gradient_norms'), ('update_norm', 'update_norms')):
                    value = norms.get(source)
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        bucket[dest].append(value)
        accepted = epoch.get('accepted') is True
        if accepted:
            current -= epoch['objective_delta']
        curve.append({'epoch': epoch['epoch'], 'accepted': accepted,
            'committed_objective': current, 'attempted_objective_delta': epoch.get('objective_delta'),
            'selected_update': epoch.get('selected_update'),
            'cumulative_tuning_search_evaluations': cumulative_tuning_calls,
            'cumulative_training_elapsed_seconds': epoch.get('cumulative_training_elapsed_seconds'),
            'epoch_elapsed_seconds': epoch.get('epoch_elapsed_seconds'),
            'candidate_holdout_evaluation_count': epoch.get('candidate_holdout_evaluation_count'),
            'objective_before': epoch.get('objective_before'), 'objective_after': epoch.get('objective_after'),
            'evaluated_objective': epoch.get('evaluated_objective')})
    if not math.isclose(current, after, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('accepted objective deltas do not replay to final objective')
    bridge_events, all_model_events = [], []
    for event in report['projection_profile']['events']:
        metadata = event.get('metadata', {})
        profile = metadata.get('evaluation_profile')
        if profile:
            all_model_events.append(event)
            observation = profile.get('target_observation', {})
            if observation.get('bridge_names') == BRIDGES:
                if observation.get('target_count', 0) <= 0:
                    raise ValueError('bridge-on event has no targets')
                bridge_events.append({'stage': event['stage'], 'seconds': event['seconds'],
                    'sample_count': profile['sample_count'], 'observation': observation})
    if not bridge_events:
        raise ValueError('no bridge-on profile evidence')
    cold = bridge_events[0]['observation']
    if not cold.get('process_target_cache_empty_at_start') or cold.get('disk_cache_hit_count') != 0:
        raise ValueError('first bridge evaluation was not cold')
    for entry in bridge_events:
        obs = entry['observation']
        if obs['evaluate_provers'] or obs['disk_cache_enabled'] or obs['parallel_workers_requested'] != 1:
            raise ValueError('bridge measurement configuration changed')
    gain = before - after
    for bucket in productivity.values():
        for key in ('finite_objective_deltas', 'cross_entropy_deltas', 'gradient_norms', 'update_norms'):
            values = bucket[key]
            bucket[key + '_range'] = [min(values), max(values)] if values else None
        bucket['finite_update_zero_ce_and_objective_response'] = bool(bucket['update_norms'] and
            any(value > 0 for value in bucket['update_norms']) and bucket['finite_objective_deltas'] and
            all(value == 0 for value in bucket['finite_objective_deltas']) and
            bucket['cross_entropy_deltas'] and all(value == 0 for value in bucket['cross_entropy_deltas']))
    return {'initial_objective': before, 'final_objective': after, 'objective_reduction': gain,
        'requested_epochs': 5, 'attempted_epochs': len(report['epoch_reports']),
        'accepted_epochs': report['accepted_epochs'], 'stopped_reason': report['stopped_reason'],
        'objective_weights': weights, 'curve': curve, 'head_productivity': dict(productivity),
        'norm_scope': 'Optimizer update/delta-derived diagnostics, not independently differentiated gradient validation.',
        'bridge_evaluations': bridge_events, 'bridge_on_evaluation_count': len(bridge_events),
        'profiled_model_evaluation_count': len(all_model_events),
        'candidate_tuning_search_evaluation_count': cumulative_tuning_calls - 1,
        'legal_ir_native_attempt_count': sum(row['observation'].get('native_evaluation_attempt_count', 0) for row in bridge_events),
        'memory_cache_hit_count': sum(row['observation'].get('memory_cache_hit_count', 0) for row in bridge_events),
        'bridge_evaluation_seconds': sum(row['seconds'] for row in bridge_events),
        'training_seconds': worker['training_seconds'], 'worker_wall_seconds': worker['elapsed_seconds'],
        'training_seconds_per_span': worker['training_seconds'] / 8,
        'objective_reduction_per_training_second': gain / worker['training_seconds'],
        'objective_reduction_per_attempted_epoch': gain / len(report['epoch_reports']) if report['epoch_reports'] else None,
        'objective_reduction_per_bridge_evaluation': gain / len(bridge_events),
        'bridge_evaluations_per_objective_unit': len(bridge_events) / gain if gain > 0 else None,
        'metrics_before': compact_metrics(report['before']), 'metrics_after': compact_metrics(report['after']),
        'constant_family_ce': {'before': report['before']['cross_entropy_loss'],
            'after': report['after']['cross_entropy_loss'],
            'excess_before': report['before']['cross_entropy_excess_loss'],
            'excess_after': report['after']['cross_entropy_excess_loss'],
            'scope': 'Report this inactive-head contribution separately from trainable LegalIR CE; it is not a zero-loss target or a proven global lower bound.'},
        'profile_by_stage': report['projection_profile']['by_stage']}


def native_child(config):
    existing = cli()
    core = existing._pin()
    output = Path(config['output'])
    begin = source_map()
    write(output / 'package-native-begin.json', begin)
    orchestration = existing.orchestration_hashes()
    helper = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_adaptive_optimizer.py'
    if helper not in orchestration:
        raise ValueError('current CLI orchestration does not bind adaptive optimizer helper')
    if sha(PINNED) != PINNED_SHA:
        raise ValueError('protected seed hash changed')
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.autoencoder_shared_weight_control import SharedWeightRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _NativeTrainingPool
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import run_training_jobs, registered_checkpoint_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_candidate_qualification import qualify_candidate, _load_candidate
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import _effective_constructor_config
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paths import gated_evaluate, INFERENCE_PATH
    started = time.monotonic()
    splits = records()
    write(output / 'plan.json', plan(config))
    write(output / 'effective-environment.json', configure_environment())
    results = []
    error = None
    try:
        with AutoencoderRegistry(output / 'control.duckdb', output / 'artifacts') as registry:
            variant = {'source_language': 'en', 'target_formal_language': 'typed_deontic_ir',
                       'jurisdiction': 'us', 'model_variant': 'synthetic-fixed-parent-optimizer-ablation'}
            registry.register_variant('variant', 'convergence-english', variant)
            seed = registry.stage_artifact(PINNED, PINNED_SHA)
            base = registry.register_version('seed', 'convergence-english', seed)['version_id']
            base_inputs = registered_checkpoint_inputs(registry, base)
            for name, (mode, momentum) in arms_for(config).items():
                arm_dir = output / name
                arm_dir.mkdir()
                arm_begin = source_map()
                write(arm_dir / 'package-begin.json', arm_begin)
                write(output / ('package-' + name + '.json'), arm_begin['files'])
                write(arm_dir / 'arm-binding.json', {'core_sources': core, 'orchestration': orchestration,
                    'producer_manifest': arm_begin['producer_manifest'],
                    'checkpoint': {'sha256': PINNED_SHA, 'bytes': PINNED.stat().st_size},
                    'input_sha256': digest(splits['training']), 'validation_sha256': digest(splits['tuning']),
                    'canary_sha256': digest(splits['canary']), 'measurement_label': name, 'admitted': False})
                if arm_begin != begin or existing._pin() != core or existing.orchestration_hashes() != orchestration:
                    raise ValueError('producer changed before arm')
                spec = TrainingJobSpec.from_dict({
                    'schema_version': 'autoencoder-training-job-v3', 'job_id': name, 'run_id': name,
                    'base_version_id': base, **base_inputs, 'output_directory': str(arm_dir / 'worker'),
                    'code_identity': digest(core), 'expected_source_sha256': core,
                    'dataset_snapshot_id': digest(splits['training']), 'split_snapshot_id': digest(splits),
                    'samples': splits['training'], 'validation_samples': splits['tuning'],
                    'variant': variant, 'autoencoder_config': {'compute_device': 'python'},
                    'training_config': {'epochs': 5, 'max_seconds': 180, 'learning_rate': .35,
                        'max_line_search_attempts': 2, 'projection_max_update_families': 5,
                        'projection_max_composed_refinement_attempts': refinement_for(config), 'profile_projection': True,
                        'projection_optimizer_mode': mode, 'projection_momentum': momentum},
                    'capture_sparse_patches': True, 'candidate_storage': 'sparse'})
                write(arm_dir / 'job.json', spec.to_dict())
                job_artifact = registry.stage_artifact(arm_dir / 'job.json')
                registry.create_run('create-' + name, name, 'convergence-english', base,
                    {'job_spec_sha256': spec.canonical_sha256, 'job_spec_artifact': job_artifact})
                arm_started = time.monotonic()
                native_pool = _NativeTrainingPool(1, expected_manifest=begin['producer_manifest'])
                try:
                    with SharedWeightRegistry(registry, enable_prototype=True) as shared:
                        dispatched = run_training_jobs(shared, [spec], max_workers=1, _native_pool=native_pool)
                        dispatched['weight_control'] = shared.transport_report()
                finally:
                    native_pool.close()
                dispatch_seconds = time.monotonic() - arm_started
                write(arm_dir / 'dispatch.json', dispatched)
                if dispatched['failed'] or len(dispatched['completed']) != 1:
                    raise ValueError('native worker failed')
                worker_path = arm_dir / 'worker/receipt.json'
                worker = read(worker_path)
                if dispatched['completed'][0]['result'].get('sparse_replay_verified') is not True:
                    raise ValueError('owner did not verify sparse replay')
                if worker['execution_mode'] != 'native_training' or worker['sample_count'] != 8 or worker['validation_sample_count'] != 1:
                    raise ValueError('worker workload differs')
                if worker['base_checkpoint']['sha256'] != PINNED_SHA or worker['base_version_id'] != base:
                    raise ValueError('arm did not use identical protected parent')
                for stage in ('before', 'after'):
                    if worker['training_report'][stage]['legal_ir_target_count'] != 1:
                        raise ValueError('tuning targets missing')
                candidate_version = dispatched['completed'][0]['version_id']
                inputs = registered_checkpoint_inputs(registry, candidate_version)
                qualification = qualify_candidate(inputs['base_checkpoint'], candidate_version, splits['training'],
                    arm_dir / 'qualification', checkpoint_dependencies=inputs['base_checkpoint_dependencies'],
                    model_config=spec.to_dict()['autoencoder_config'], heldout_samples=splits['tuning'], lake_timeout_seconds=60)
                arm_end = source_map()
                write(arm_dir / 'package-end.json', arm_end)
                if arm_end != begin:
                    raise ValueError('full producer changed during arm')
                summary = summarize_worker(worker)
                summary.update(arm=name, mode=mode, momentum=momentum, worker_receipt=ref(worker_path),
                    native_dispatch_seconds=dispatch_seconds, base_version_id=base,
                    candidate_version_id=candidate_version, candidate_inputs=inputs,
                    qualified=qualification['qualified'], qualification_gates=qualification['gate_results'],
                    qualification_seconds=qualification['elapsed_seconds'],
                    qualification_rows=[{key: row.get(key) for key in ('sample_id', 'split', 'source', 'qualified',
                        'metric_gate', 'semantic_gate', 'family_syntax_gate', 'lake_gate')} for row in qualification['rows']],
                    qualification_receipt=ref(arm_dir / 'qualification/qualification.json'),
                    effective_model_config=worker['effective_autoencoder_config'],
                    weight_control=dispatched['weight_control'], elapsed_seconds=time.monotonic() - arm_started)
                write(arm_dir / 'summary.json', summary)
                results.append(summary)
                print(json.dumps({'arm': name, 'qualified': summary['qualified'], 'accepted_epochs': summary['accepted_epochs'],
                    'attempted_epochs': summary['attempted_epochs'], 'objective': summary['final_objective']}), flush=True)
            if any(row['effective_model_config'] != results[0]['effective_model_config'] for row in results):
                raise ValueError('effective model configuration differs across arms')
            if any(not math.isclose(row['initial_objective'], results[0]['initial_objective'], abs_tol=1e-12) for row in results):
                raise ValueError('initial objective differs across arms')
            eligible = [row for row in results if row['qualified']] or results
            selected = min(eligible, key=lambda row: (row['final_objective'], row['arm']))
            selection = {'selected_arm': selected['arm'], 'candidate_version_id': selected['candidate_version_id'],
                         'qualified': selected['qualified'], 'selection_metric': 'final_tuning_objective',
                         'canary_evaluated_before_selection': False, 'promotion_performed': False, 'admitted': False}
            write(output / 'selection-before-canary.json', selection)
            canaries = []
            for evaluated_arm in ([] if config['experiment'] == 'integrated' else
                    ([results[0]] if selected['arm'] == 'baseline_adaptive' else [results[0], selected])):
                inputs = evaluated_arm['candidate_inputs']
                resolved = _load_candidate(inputs['base_checkpoint'], inputs['base_checkpoint_dependencies'])
                constructor = _effective_constructor_config(AdaptiveModalAutoencoder, {'compute_device': 'python'})
                model = AdaptiveModalAutoencoder(state=resolved.state, **constructor)
                state_before = model.state.state_identity_record().to_dict()
                canary_started = time.monotonic()
                canary = gated_evaluate(model, [build_us_code_sample(**row) for row in splits['canary']],
                    execution_mode=INFERENCE_PATH, legal_ir_bridge_names=BRIDGES, legal_ir_evaluate_provers=False,
                    legal_ir_parallel_workers=1, use_sample_memory=False, profile_evaluation=True).to_dict()
                if canary['legal_ir_target_count'] != 2 or model.state.state_identity_record().to_dict() != state_before:
                    raise ValueError('canary targets missing or inference mutated weights')
                canaries.append({'arm': evaluated_arm['arm'], 'candidate_version_id': evaluated_arm['candidate_version_id'],
                    'roles': (['baseline_reference'] if evaluated_arm['arm'] == 'baseline_adaptive' else []) +
                             (['selected'] if evaluated_arm['arm'] == selected['arm'] else []),
                    'evaluation': canary, 'objective': objective(canary, evaluated_arm['objective_weights']),
                    'elapsed_seconds': time.monotonic() - canary_started, 'weights_unchanged': True})
            if canaries:
                selected_canary = next(row for row in canaries if 'selected' in row['roles'])
                baseline_canary = canaries[0]
                canary_summary = {'selected_arm': selected['arm'], 'baseline_reference_arm': 'baseline_adaptive',
                    'selected_objective': selected_canary['objective'], 'baseline_objective': baseline_canary['objective'],
                    'objective_delta_selected_minus_baseline': selected_canary['objective'] - baseline_canary['objective'],
                    'selected_metrics': compact_metrics(selected_canary['evaluation']),
                    'baseline_metrics': compact_metrics(baseline_canary['evaluation'])}
            else:
                canary_summary = {'evaluated': False, 'reason': 'Prespecified integrated diagnostic has no further canary evaluation.'}
            write(output / 'selected-canary.json', {'selection': ref(output / 'selection-before-canary.json'),
                'results': canaries, 'summary': canary_summary,
                'scope': 'Synthetic canaries untouched within this experiment until the sealed selection; no feedback into optimizer or arm selection. Baseline reference is the baseline-arm final candidate. Shared owner target cache may warm the second inference and is reported in evaluation profiles.',
                'admitted': False, 'heldout_federal_law_canary': False})
            threshold = results[0]['final_objective'] if config['experiment'] == 'main' else None
            prefix = min(row['attempted_epochs'] for row in results)
            for row in results:
                hits = [point for point in row['curve'] if threshold is not None and point['committed_objective'] <= threshold + 1e-12]
                hit = hits[0] if hits else None
                row['baseline_final_objective_threshold'] = threshold
                row['threshold_first_observed_epoch'] = hit['epoch'] if hit else None
                row['threshold_first_observed_training_seconds'] = hit['cumulative_training_elapsed_seconds'] if hit else None
                row['threshold_training_seconds_upper_bound'] = row['training_seconds'] if hit else None
                row['common_attempted_epoch_prefix'] = prefix
                row['common_prefix_objective'] = row['curve'][prefix]['committed_objective']
            write(output / 'comparison.json', {'schema': 'autoencoder-epoch-productivity-comparison/v1', 'experiment': config['experiment'], 'arms': results,
                'selection': selection, 'canary_receipt': ref(output / 'selected-canary.json'), 'canary_summary': canary_summary,
                'same_fixed_parent': True, 'same_effective_model_config': True, 'common_attempted_epoch_prefix': prefix,
                'threshold_scope': 'Main experiment threshold equals baseline_adaptive final tuning objective; integrated-only threshold is null and is not a comparative speed claim; not convergence or global-optimality proof. Missing epoch timestamp remains null; whole-training wall is only an upper bound.',
                'reconstruction_scope': 'Target-aware safe projection can return the supplied target embedding; cosine/MSE alone are not independent learned legal reconstruction.',
                'qualification_scope': 'Lake checks generated supported duration lemmas; family syntax artifacts are limited atom projections, not complete federal-law or cognitive/event semantics.',
                'producer_manifest': begin['producer_manifest'], 'effective_environment': configure_environment(),
                'elapsed_seconds': time.monotonic() - started,
                'admitted': False, 'promotion_performed': False, 'global_minimum_claim': False})
    except BaseException as exc:
        error = exc
        write(output / 'failure.json', {'error': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc(),
              'completed_arms': [row['arm'] for row in results], 'admitted': False})
    finally:
        end = source_map()
        write(output / 'package-native-end.json', end)
        guard = {'source_unchanged': begin == end, 'core_unchanged': existing._pin() == core,
                 'orchestration_unchanged': existing.orchestration_hashes() == orchestration,
                 'protected_seed_unchanged': sha(PINNED) == PINNED_SHA,
                 'producer_manifest': begin['producer_manifest'], 'admitted': False}
        write(output / 'native-guard.json', guard)
    if error:
        raise error
    if not all(guard[key] for key in ('source_unchanged', 'core_unchanged', 'orchestration_unchanged', 'protected_seed_unchanged')):
        raise ValueError('native producer or protected seed changed; evidence is not comparable')


def supervised(config):
    existing = cli()
    existing._pin()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_capacity import execution_capacity_plan, scheduler_capacity
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    output = Path(config['output'])
    output.mkdir(parents=True, exist_ok=False)
    initial = source_map()
    write(output / 'package-parent-begin.json', initial)
    available = scheduler_capacity(get_global_resource_scheduler().snapshot())
    capacity = execution_capacity_plan('training', max_workers=1, memory_budget_mb=config['memory_mb'], pending_count=1,
        scheduler_available_cpu=available['cpu_slots'], scheduler_available_memory_mb=available['memory_mb'],
        scheduler_available_process_slots=available['child_process_slots'])
    if capacity['workers'] != 1 or available['memory_mb'] < config['memory_mb']:
        raise RuntimeError('capacity unavailable for fixed single-worker experiment')
    write(output / 'capacity.json', capacity)
    roots = [row['path'] for row in read(LEDGER)['roots']]
    if not any(Path(root) == output or Path(root) in output.parents for root in roots):
        raise ValueError('output lies outside existing resource ledger roots')
    reservation = DaemonResourceReservation(LEDGER, roots=roots, storage_bytes=config['storage_bytes'],
        memory_mb=config['memory_mb'], cpu_slots=capacity['execution_envelope']['cpu_slots'],
        timeout_seconds=0, ledger_lock_timeout_seconds=60,
        child_process_slots=capacity['execution_envelope']['child_process_slots'])
    process, observations = None, []
    started = time.monotonic()
    with reservation:
        try:
            with (output / 'native.log').open('xb') as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--_child'],
                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=os.environ.copy())
                reservation.check_usage(attempt_directory=output, child_pid=process.pid)
                process.stdin.write(raw(config) + b'\n')
                process.stdin.close()
                next_check, next_observation = time.monotonic() + 15, time.monotonic()
                while process.poll() is None:
                    if time.monotonic() - started > config['cycle_timeout']:
                        raise TimeoutError('bounded three-arm benchmark exceeded process deadline')
                    if time.monotonic() >= next_check:
                        reservation.check_usage(attempt_directory=output, child_pid=process.pid)
                        next_check = time.monotonic() + 15
                    if time.monotonic() >= next_observation:
                        observations.append(existing._group_observation(process.pid))
                        next_observation = time.monotonic() + 2
                    time.sleep(.5)
                existing._stop_group(process)
                if process.returncode:
                    raise RuntimeError(f'native child failed rc={process.returncode}; inspect {output / "native.log"}')
            end = source_map()
            write(output / 'package-parent-end.json', end)
            native_guard = read(output / 'native-guard.json')
            if initial != end or native_guard['producer_manifest'] != initial['producer_manifest']:
                raise ValueError('full source changed between parent admission and native execution')
            write(output / 'process-observations.json', observations)
            finalization_started = time.monotonic()
            resource = reservation.finalize(attempt_directory=output, artifacts_durable=True)
            finalization_seconds = time.monotonic() - finalization_started
            write(output / 'resources.json', resource)
            write(output / 'command.json', {'returncode': 0, 'wall_seconds': time.monotonic() - started,
                'resource_finalization_seconds': finalization_seconds, 'source_unchanged': True,
                'checkpoint_unchanged': sha(PINNED) == PINNED_SHA, 'config': config,
                'harness': ref(__file__), 'effective_environment': configure_environment(), 'comparison': ref(output / 'comparison.json'), 'admitted': False})
        except BaseException:
            if process is not None:
                existing._stop_group(process)
            if not (output / 'process-observations.json').exists():
                write(output / 'process-observations.json', observations)
            write(output / 'retained-resources.json', reservation.to_dict())
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--integrated', action='store_true', help='Separate prespecified refinement3 diagnostic; no canary evaluation. Never launched automatically.')
    parser.add_argument('--memory-mb', type=int, default=8192)
    parser.add_argument('--storage-bytes', type=int, default=500000000)
    parser.add_argument('--cycle-timeout', type=int, default=900)
    parser.add_argument('--_child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._child:
        native_child(json.loads(sys.stdin.readline()))
        return
    if args.output is None:
        parser.error('--output required')
    allowed_storage = {250000000, 500000000} if args.integrated else {500000000}
    if args.storage_bytes not in allowed_storage or not 4096 <= args.memory_mb <= 12288 or not 600 <= args.cycle_timeout <= 1200:
        parser.error('use500MB main or250/500MB integrated storage; memory4096..12288MiB and deadline600..1200s')
    config = {'output': str(args.output.resolve()), 'memory_mb': args.memory_mb,
              'storage_bytes': args.storage_bytes, 'cycle_timeout': args.cycle_timeout,
              'experiment': 'integrated' if args.integrated else 'main'}
    if args.prepare:
        write(args.output, plan(config))
        print(str(args.output))
    else:
        supervised(config)
        print(str(args.output / 'comparison.json'))


if __name__ == '__main__':
    main()
