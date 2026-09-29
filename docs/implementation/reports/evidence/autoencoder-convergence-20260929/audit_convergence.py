#!/usr/bin/env python3
"""Read-only integrity audit of native three-arm convergence evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import math

ARMS = {'fixed': ('fixed', 0.0), 'adaptive_lr': ('guarded_adaptive', 0.0), 'adaptive_momentum': ('guarded_adaptive', 0.5)}
BRIDGES = ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router']
SEED = '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
FAMILIES = {'fol', 'deontic_fol', 'temporal_fol', 'deontic_temporal_fol', 'deontic_cognitive_event_calculus', 'frame_logic'}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('oversized evidence')
    return json.loads(path.read_bytes())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    checks, failures = 0, []
    def check(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)
    def verified(reference):
        path = Path(reference['path'])
        check(path.stat().st_size == reference['bytes'] and sha(path) == reference['sha256'], 'artifact content ' + str(path))
        return read(path)
    command = read(run / 'command.json')
    comparison = verified(command['comparison'])
    guard = read(run / 'native-guard.json')
    plan = read(run / 'plan.json')
    selection = read(run / 'selection-before-canary.json')
    canary = read(run / 'selected-canary.json')
    environment = read(run / 'effective-environment.json')
    check(environment == comparison['effective_environment'] == command['effective_environment'], 'effective environment receipt parity')
    check(environment['IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE'] == '0' and environment['CUDA_VISIBLE_DEVICES'] == '' and
          environment['HF_HUB_OFFLINE'] == '1' and environment['TRANSFORMERS_OFFLINE'] == '1' and
          environment['IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI'] == '0', 'no target disk cache, weights download, external prover install')
    check(command['returncode'] == 0 and command['source_unchanged'] and command['checkpoint_unchanged'], 'command provenance')
    check(all(guard.get(key) is True for key in ('source_unchanged', 'core_unchanged', 'orchestration_unchanged', 'protected_seed_unchanged')), 'native guards')
    package = read(run / 'package-native-begin.json')
    check(package == read(run / 'package-native-end.json') == read(run / 'package-parent-begin.json') == read(run / 'package-parent-end.json'), 'all boundary maps identical')
    check(guard['producer_manifest'] == package['producer_manifest'] == comparison['producer_manifest'], 'same producer')
    check(hashlib.sha256(raw(package['files'])).hexdigest() == package['producer_manifest']['sha256'] and len(package['files']) == package['producer_manifest']['file_count'], 'full map manifest digest')
    check(plan['sample_counts'] == {'training': 8, 'tuning': 1, 'canary': 2}, 'declared split counts')
    normalized = [{row['text'].strip().casefold() for row in plan['samples'][key]} for key in ('training', 'tuning', 'canary')]
    check(not any(normalized[i] & normalized[j] for i in range(3) for j in range(i + 1, 3)), 'split text disjointness')
    check([row['arm'] for row in comparison['arms']] == list(ARMS), 'prespecified arm order')
    check(selection['canary_evaluated_before_selection'] is False and not selection['promotion_performed'], 'selection has no canary feedback or promotion')
    check(verified(canary['selection']) == selection, 'canary binds sealed selection')
    check(comparison['admitted'] is False and comparison['global_minimum_claim'] is False, 'no global optimum or admission claim')
    parent, model = None, None
    counts = {'arms': 0, 'requested_epochs': 15, 'attempted_epochs': 0, 'accepted_epochs': 0,
              'qualified_arms': 0, 'qualification_rows': 0, 'lake_builds': 0, 'family_artifacts': 0}
    rows = []
    for summary in comparison['arms']:
        name = summary['arm']
        mode, momentum = ARMS[name]
        binding = read(run / name / 'arm-binding.json')
        worker = verified(summary['worker_receipt'])
        qualification = verified(summary['qualification_receipt'])
        dispatch = read(run / name / 'dispatch.json')
        spec = worker['job_spec']
        cfg, report = spec['training_config'], worker['training_report']
        check(binding['producer_manifest'] == package['producer_manifest'], name + ': bound producer')
        check(read(run / ('package-' + name + '.json')) == package['files'], name + ': raw package map')
        check(read(run / name / 'package-begin.json') == package == read(run / name / 'package-end.json'), name + ': boundary maps')
        check(binding['checkpoint']['sha256'] == SEED == spec['base_checkpoint']['sha256'], name + ': protected parent hash')
        check(spec['base_checkpoint']['bytes'] == 25895338, name + ': protected parent bytes')
        current_parent = (spec['base_version_id'], spec['base_checkpoint']['sha256'], worker['base_state_identity'])
        parent = current_parent if parent is None else parent
        check(parent == current_parent and not spec.get('base_checkpoint_dependencies'), name + ': identical initial version/state')
        check(worker['execution_mode'] == 'native_training' and worker['execution_gate_applied'] is True, name + ': native training gate')
        check(worker['tree_file_sha256'] == binding['core_sources'] == spec['expected_source_sha256'] and worker['worker_source_sha256'] == binding['core_sources']['worker'], name + ': core hashes')
        check(worker['bridge_names'] == BRIDGES and worker['legal_ir_target_count'] > 0 if 'legal_ir_target_count' in worker else worker['bridge_names'] == BRIDGES, name + ': five bridges')
        check(worker['legal_ir_evaluate_provers'] is False and worker['metric_disk_cache'] == 0 and worker['legal_ir_parallel_workers'] == 1 and worker['use_sample_memory'] is False, name + ': exact bridge configuration')
        check(worker['sample_count'] == 8 and worker['validation_sample_count'] == 1, name + ': workload')
        check([row['text'] for row in spec['samples']] == [row['text'] for row in plan['samples']['training']], name + ': training records')
        check([row['text'] for row in spec['validation_samples']] == [row['text'] for row in plan['samples']['tuning']], name + ': tuning records')
        check(cfg['epochs'] == 5 and cfg['max_seconds'] == 180 and cfg['learning_rate'] == .35 and cfg['max_line_search_attempts'] == 2 and cfg['projection_max_update_families'] == 5, name + ': fixed budget')
        check(cfg.get('projection_max_composed_refinement_attempts', 0) == 0 and cfg.get('projection_optimizer_mode', 'fixed') == mode and cfg.get('projection_momentum', 0.0) == momentum, name + ': optimizer treatment')
        check(cfg['projection_update_backend'] == 'python_sparse_batch', name + ': backend')
        current_model = worker['effective_autoencoder_config']
        model = current_model if model is None else model
        check(current_model == model, name + ': identical effective model')
        check(all(value == 0 for key, value in model.items() if key.endswith('family_logit_scale')), name + ': inactive family-logit measurement scales')
        check(not dispatch['failed'] and len(dispatch['completed']) == 1, name + ': one native completion')
        completed = dispatch['completed'][0]
        check(completed['result']['sparse_replay_verified'] is True, name + ': sparse replay')
        check(dispatch['weight_control']['transport'] == 'native_scoped_quack_prototype' and
              all(cap['native_quack'] for cap in dispatch['weight_control']['capabilities']) and
              dispatch['weight_control']['database_writer_count'] == 1 and
              dispatch['weight_control']['workers_open_database'] is False, name + ': actual single-writer Quack transport')
        check(len(report['epoch_reports']) == summary['attempted_epochs'] <= 5, name + ': actual attempted epochs')
        check(report['accepted_epochs'] == summary['accepted_epochs'], name + ': actual accepted epochs')
        check(len(worker['sparse_patch_segments']) == report['accepted_epochs'], name + ': one sparse segment per accepted epoch')
        check(all(report[key]['legal_ir_target_count'] == 1 for key in ('before', 'after')), name + ': tuning bridge targets')
        last_elapsed, last_objective = 0.0, summary['initial_objective']
        for epoch, point in zip(report['epoch_reports'], summary['curve'][1:]):
            label = f'{name}: epoch {epoch["epoch"]}'
            check(epoch['cumulative_training_elapsed_seconds'] >= last_elapsed and epoch['epoch_elapsed_seconds'] >= 0, label + ': monotonic wall telemetry')
            check(math.isclose(epoch['objective_before'], last_objective, abs_tol=1e-9), label + ': objective before')
            expected = last_objective - epoch['objective_delta'] if epoch['accepted'] else last_objective
            check(math.isclose(epoch['objective_after'], expected, abs_tol=1e-9) and math.isclose(point['committed_objective'], expected, abs_tol=1e-9), label + ': accepted/rejected objective replay')
            check(epoch['candidate_holdout_evaluation_count'] >= 0, label + ': evaluation count')
            last_elapsed, last_objective = epoch['cumulative_training_elapsed_seconds'], expected
        check(math.isclose(last_objective, summary['final_objective'], abs_tol=1e-9), name + ': final objective replay')
        check(set(qualification['gate_results']) == {'metric_gate', 'semantic_gate', 'family_syntax_gate', 'lake_gate', 'heldout_gate'}, name + ': all five qualification gates')
        check(qualification['sample_count'] == 8 and qualification['heldout_sample_count'] == 1 and len(qualification['rows']) == 9, name + ': qualification split')
        check(qualification['heldout_canary'] is False and qualification['heldout_role'] == 'tuning_validation', name + ': tuning not independent canary')
        check(qualification['qualified'] == all(value['passed'] for value in qualification['gate_results'].values()), name + ': conjunction of all gates')
        check(summary['qualified'] == qualification['qualified'], name + ': qualification disposition')
        for row in qualification['rows']:
            counts['qualification_rows'] += 1
            for native in row['lake_gate'].get('rows', []):
                counts['lake_builds'] += 1
                source = Path(native['source_file'])
                check(sha(source) == native['lean_source_sha256'], name + ': generated Lean binding')
                if native['passed']:
                    check(native['command'] == ['lake', 'build', 'Legal'] and native['returncode'] == 0 and native['lake_ok'] is True and native['admitted'] is True, name + ': Lake is only admit')
                    log = Path(native['log']['path'])
                    check(sha(log) == native['log']['sha256'] and 'Built Legal' in log.read_text() and 'error:' not in log.read_text(), name + ': Lake log')
                    check(not any(word in source.read_text() for word in ('Mathlib', 'sorry', 'axiom')), name + ': permitted Lean source')
            for family_row in row['family_syntax_gate'].get('rows', []):
                counts['family_artifacts'] += len(family_row['families'])
                check(set(family_row['families']) == FAMILIES, name + ': complete requested family set')
                for family in family_row['families'].values():
                    check(family.get('admitted') is False, name + ': family syntax not Lean admission')
                    if family.get('passed'):
                        check(family.get('consumed_all_input') is True, name + ': entire family artifact parsed')
        counts['arms'] += 1
        counts['attempted_epochs'] += len(report['epoch_reports'])
        counts['accepted_epochs'] += report['accepted_epochs']
        counts['qualified_arms'] += int(qualification['qualified'])
        rows.append({'arm': name, 'attempted_epochs': summary['attempted_epochs'], 'accepted_epochs': summary['accepted_epochs'],
                     'qualified': summary['qualified'], 'gate_results': qualification['gate_results'],
                     'initial_objective': summary['initial_objective'], 'final_objective': summary['final_objective'],
                     'training_seconds': summary['training_seconds'], 'training_seconds_per_span': summary['training_seconds_per_span'],
                     'bridge_on_evaluation_count': summary['bridge_on_evaluation_count'],
                     'threshold_first_observed_epoch': summary['threshold_first_observed_epoch'],
                     'threshold_first_observed_training_seconds': summary['threshold_first_observed_training_seconds']})
    eligible = [row for row in comparison['arms'] if row['qualified']] or comparison['arms']
    expected_selected = min(eligible, key=lambda row: (row['final_objective'], row['arm']))['arm']
    check(selection['selected_arm'] == expected_selected, 'sealed tuning-only selection follows policy')
    for result in canary['results']:
        observation = result['evaluation']['evaluation_profile']['target_observation']
        check(observation['bridge_names'] == BRIDGES and observation['target_count'] == 2 and
              observation['disk_cache_enabled'] is False and observation['disk_cache_hit_count'] == 0 and
              observation['evaluate_provers'] is False and observation['parallel_workers_requested'] == 1, 'canary measured bridge configuration')
        check(result['weights_unchanged'] is True and result['evaluation']['sample_count'] == 2 and result['evaluation']['legal_ir_target_count'] == 2, 'inference-only canary with targets')
    check({row['arm'] for row in canary['results']} == {'fixed', expected_selected}, 'prespecified fixed/selected canary set')
    resource = read(run / 'resources.json')
    record = resource['record']
    check(resource['status'] == record['status'] == 'released' and resource['resource_lease']['released'] is True, 'resource lease finalized and released')
    check(resource['storage_limit_bytes'] == 80000000000 and record['storage_bytes'] == 750000000 and
          record['final_total_charged_bytes'] <= record['storage_bytes'] and not record['attempt_exceeded_reservation'], 'existing storage cap and attempt budget preserved')
    check(record['cpu_slots'] == 2 and record['child_process_slots'] == 5 and record['memory_mb'] == command['config']['memory_mb'], 'bounded owner plus worker resource envelope')
    check(record['artifacts_durable_asserted'] is True and resource['cleanup_error'] is None, 'durable successful finalization')
    output = {'schema': 'autoencoder-convergence-audit/v1', 'passed': not failures, 'check_count': checks,
        'failures': failures, 'counts': counts, 'arms': rows, 'selection': selection,
        'canary_summary': comparison['canary_summary'], 'producer_manifest': package['producer_manifest'],
        'command_wall_seconds': command['wall_seconds'], 'resource_record': resource,
        'admitted': False, 'global_minimum_claim': False,
        'scope': 'Evidence integrity and unchanged qualification policy. Failed qualification arms remain failed; synthetic canaries do not establish federal-law coverage.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': not failures, 'checks': checks, 'failures': failures, 'counts': counts}))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
