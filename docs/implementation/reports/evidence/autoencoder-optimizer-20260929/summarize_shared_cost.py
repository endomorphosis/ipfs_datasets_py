"""Read completed native evidence only; do not import or execute model code."""
import hashlib
import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent

def read(name):
    return json.loads((BASE / name).read_bytes())

def ref(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def workers(label):
    records = []
    for path in sorted((BASE / label / 'progress/outputs').glob('*/receipt.json')):
        row = json.loads(path.read_bytes())
        events = row['training_report']['projection_profile']['events']
        first = next(event for event in events if event.get('stage') == 'before_holdout_evaluation')
        detail = first.get('metadata', {}).get('evaluation_profile')
        if detail is None:
            detail = row['training_report'].get('before', {}).get('evaluation_profile')
        records.append({'receipt': ref(path), 'run_id': row['run_id'], 'sample': row['job_spec']['samples'][0],
                        'worker_elapsed_seconds': row['elapsed_seconds'], 'training_seconds': row['training_seconds'],
                        'target_load_seconds': row['target_load_seconds'],
                        'target_artifact_verification_seconds': row['target_artifact_verification_seconds'],
                        'target_hydration_seconds': row['target_hydration_seconds'],
                        'target_reduction_seconds': row['target_reduction']['total_seconds'],
                        'shared_target_count': row['shared_target_count'],
                        'target_snapshot_sample_count': row['target_snapshot_sample_count'],
                        'shared_targets_verified': row['shared_targets_verified'],
                        'source_manifest_verified': row['source_manifest_verified'],
                        'shared_target_verification_scope': row['shared_target_verification_scope'],
                        'first_bridge_on_evaluation': detail,
                        'bridge_names': row['bridge_names'], 'legal_ir_evaluate_provers': row['legal_ir_evaluate_provers'],
                        'legal_ir_parallel_workers': row['legal_ir_parallel_workers'],
                        'metric_disk_cache': row['metric_disk_cache'], 'use_sample_memory': row['use_sample_memory'],
                        'runtime': row['runtime'], 'admitted': False})
    return records

def main():
    prep = read('shared-preparation-audit.json')
    p = prep['preparation']
    baseline = read('scaled-command.json')
    shared = read('shared-command.json')
    b_audit, s_audit = read('scaled-audit.json'), read('shared-audit.json')
    parity = read('shared-parity-audit.json')
    transport = read('shared-transport-parity-audit.json')
    assert transport['before_audit'] == ref(BASE / 'scaled-audit.json')
    assert transport['after_audit'] == ref(BASE / 'shared-audit.json')
    br, sr = workers('scaled'), workers('shared')
    assert len(br) == len(sr) == 4
    keys = ['base', 'candidate', 'base_identity', 'candidate_identity', 'model_config', 'training_config',
            'samples', 'validation_samples', 'training_metrics_sha256', 'selected_updates', 'gates', 'qualified']
    matching = {}
    assert set(b_audit['rows']) == set(s_audit['rows'])
    for identity, before in b_audit['rows'].items():
        after = s_audit['rows'][identity]
        matching[identity] = {key: before[key] == after[key] for key in keys}
    exact = all(all(row.values()) for row in matching.values())
    topology = {'logical_lane_count': [b_audit['logical_lane_count'], s_audit['logical_lane_count']],
                'runtime_parallel_workers': [b_audit['runtime_parallel_workers'], s_audit['runtime_parallel_workers']],
                'dispatch_widths': [b_audit['dispatch_widths'], s_audit['dispatch_widths']],
                'distinct_lanes_per_route': [len({r['lane'] for r in audit['rows'].values()}) for audit in [b_audit, s_audit]],
                'chain_depths': [[r['chain_depth'] for r in audit['rows'].values()] for audit in [b_audit, s_audit]],
                'exact_parent_candidate_binding_for_all_rows': all(row['base'] and row['candidate'] for row in matching.values()),
                'expected_transport_differences': transport['expected_transport_differences']}
    assert topology['logical_lane_count'] == [32, 32]
    assert topology['runtime_parallel_workers'] == [4, 4]
    assert topology['distinct_lanes_per_route'] == [4, 4]
    assert topology['chain_depths'] == [[1] * 4, [1] * 4]
    eligible = (exact and transport['passed'] and transport['consumer_comparison_eligible']
                and b_audit['passed'] and s_audit['passed']
                and baseline['returncode'] == shared['returncode'] == 0)
    production = prep['timings']['full_cli_wall_seconds']
    private, consumer = baseline['wall_seconds'], shared['wall_seconds']
    saving = private - consumer
    finance = {'exact_parity_verified': eligible,
               'numeric_objective_candidate_gate_parity_verified': exact,
               'strict_route_parity_failures': parity['failures'],
               'conditional_amortization_if_expected_transport_and_lane_changes_are_separately_validated': math.floor(production / saving) + 1 if exact and saving > 0 else None,
               'conditional_amortization_scope': 'Transport and exact parent/candidate parity passed; arithmetic projects repeated use of these one-run timings only. The 1.411s consumer difference may include measurement noise. Repeated-run savings and 17-use payback have not been demonstrated.',
               'strict_route_parity_passed': parity['passed'],
               'transport_parity_passed': transport['passed'],
               'transport_parity_check_count': transport['check_count'],
               'consumer_comparison_eligible': eligible,
               'observed_end_to_end_speedup': eligible and production + consumer < private, 'scaled_private_targets_wall_seconds': private,
               'shared_consumer_wall_seconds': consumer, 'cold_preparation_wall_seconds': production,
               'one_off_preparation_plus_consumer_wall_seconds': production + consumer,
               'one_off_extra_wall_seconds': production + consumer - private,
               'one_off_total_ratio_to_private': (production + consumer) / private,
               'per_consumer_observed_wall_seconds_saved': saving,
               'formula': 'P + N*S < N*B; first integer N = floor(P/(B-S))+1 only if B>S and parity holds',
               'estimated_first_reuse_count_with_net_saving': math.floor(production / saving) + 1 if eligible and saving > 0 else None,
               'scope': 'Single sequential measurements on four synthetic duration fixtures, four simultaneous worker slots, same five bridges and disjoint repeated tuning validation. Estimate assumes similar future timings and unchanged source/runtime/input binding; it is not a measured repeated-run speedup.',
               'full_cli_seconds_per_training_span': {'private': private / 4, 'shared_consumer': consumer / 4,
                                                       'shared_cold_preparation_plus_consumer': (production + consumer) / 4}}
    stats = p['artifact_statistics']
    summary = {'schema_version': 'native-shared-target-cost-summary/v1',
               'evidence': {name: ref(BASE / name) for name in ['shared-preparation-audit.json', 'shared-preparation-command.json',
                              'scaled-command.json', 'shared-command.json', 'scaled-audit.json', 'shared-audit.json', 'shared-parity-audit.json', 'shared-transport-parity-audit.json']},
               'preparation': {'fresh_process': True, 'unique_targets': 5, 'training_rows': 4, 'validation_rows': 1,
                    'bridge_names': p['bridge_names'], 'legal_ir_evaluate_provers': False, 'metric_disk_cache': 0,
                    'legal_ir_parallel_workers': 1, 'metric_process_cache_used': False,
                    'multiview_process_cache_used': False, 'use_sample_memory': False,
                    'cache_scope': prep['cache_scope'], 'source_input_seed_unchanged': prep['command']['sources_inputs_seed_unchanged'],
                    'all_targets_ready': all(status == 'ready' for status in p['statuses'].values()),
                    'all_five_bridge_reports_accepted_per_target': all(row['accepted_bridge_count'] == 5 and row['failed_bridge_count'] == 0 for row in p['bridge_report_telemetry'].values()),
                    'target_artifact': prep['target_artifact'], 'target_snapshot_id': prep['target_snapshot_id'],
                    'timings': {**prep['timings'], 'producer_elapsed_seconds': p['elapsed_seconds'],
                       'target_generation_seconds': p['target_generation_seconds'],
                       'target_generation_seconds_per_span': p['target_generation_seconds_per_span'],
                       'sample_preparation_seconds': p['sample_preparation_seconds'],
                       'target_generation_and_artifact_seconds': p['target_generation_and_artifact_seconds'],
                       'target_pipeline_non_generation_seconds': p['target_pipeline_non_generation_seconds'],
                       'supervised_process_wall_seconds': prep['supervision']['supervised_process_wall_seconds'],
                       'compression_seconds': stats['compression_seconds'], 'encoding_validate_seconds': stats['encoding_validate_seconds'],
                       'producer_outside_sample_pipeline_residual_seconds': p['elapsed_seconds'] - p['sample_preparation_seconds'] - p['target_generation_and_artifact_seconds'],
                       'child_outside_producer_residual_seconds': prep['supervision']['supervised_process_wall_seconds'] - prep['timings']['producer_call_wall_seconds'],
                       'cli_outside_supervised_child_residual_seconds': production - prep['supervision']['supervised_process_wall_seconds']},
                    'timing_scope': 'Nested timings are not additive. Residuals include uninstrumented startup/guards/accounting work and are not attributed to a single function.',
                    'artifact_statistics': stats, 'observed_peak_group_rss_bytes': prep['supervision']['observed_peak_group_rss_bytes'],
                    'finalization_profile': prep['resources']['record']['finalization_profile'],
                    'reservation_status': prep['resources']['record']['status'],
                    'storage_limit_bytes': prep['resources']['storage_limit_bytes'],
                    'attempt_exceeded_reservation': prep['resources']['record']['attempt_exceeded_reservation']},
               'comparison': finance, 'matched_topology': topology, 'exact_per_sample_parity': matching,
               'consumers': {'private': br, 'shared': sr},
               'aggregate_worker_observations': {name: {key: sum(row[key] for row in rows) for key in ['worker_elapsed_seconds', 'training_seconds', 'target_load_seconds', 'target_artifact_verification_seconds', 'target_hydration_seconds', 'target_reduction_seconds']} for name, rows in [('private', br), ('shared', sr)]},
               'aggregate_worker_scope': 'Concurrent worker duration sums are work observations, not end-to-end elapsed wall time. Target load contains artifact verification/hydration and is not additive with them.',
               'qualification_counts': {'private': b_audit['counts'], 'shared': s_audit['counts']},
               'consumer_finalization_profile': {name: audit['resource_record'].get('finalization_profile') for name, audit in [('private', b_audit), ('shared', s_audit)]},
               'limits': ['Shared targets amortize only while exact producer package/runtime/input binding remains valid.',
                          'One validation target is reused across all four jobs; validation is repeated tuning, not an independent held-out canary.',
                          'Targets, bridge acceptance, metrics and bundle rows do not establish Lean admission; native Lake builds remain separately audited.',
                          'No US Constitution span was formalized; these are five synthetic duration fixtures.'],
               'admitted': False, 'constitution_formalized': False}
    (BASE / 'shared-cost-summary.json').write_text(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'comparison': finance, 'aggregate_worker_observations': summary['aggregate_worker_observations']}))

if __name__ == '__main__':
    main()
