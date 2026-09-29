"""Summarize completed source-bound native receipts; never import model code."""
import argparse
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
BRIDGES = ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router']


def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(path):
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Evidence JSON exceeds 64 MiB: ' + str(path))
    return json.loads(path.read_bytes())


def verified(reference):
    path = Path(reference['path'])
    observed = descriptor(path)
    assert observed['sha256'] == reference['sha256'] and observed['bytes'] == reference['bytes'], path
    return read(path)


def process_summary(path, workers, cpu_slots):
    observations = read(path)
    hz = os.sysconf('SC_CLK_TCK')
    worker_pids = {row['runtime']['pid'] for row in workers}
    peak_per_pid, max_rates = {}, {}
    totals, observed_cpu = [], 0.0
    for snapshot in observations:
        for process in snapshot['processes']:
            identity = (process['pid'], process['birth'])
            peak_per_pid[identity] = max(peak_per_pid.get(identity, 0), process['rss_bytes'])
    for before, after in zip(observations, observations[1:]):
        duration = after['wall_time'] - before['wall_time']
        assert duration > 0
        previous = {(row['pid'], row['birth']): row for row in before['processes']}
        total = 0.0
        for row in after['processes']:
            identity = row['pid'], row['birth']
            if identity not in previous:
                continue
            elapsed_cpu = max(0, row['cpu_ticks'] - previous[identity]['cpu_ticks']) / hz
            rate = elapsed_cpu / duration
            observed_cpu += elapsed_cpu
            max_rates[identity] = max(rate, max_rates.get(identity, 0.0))
            total += rate
        totals.append(total)
    maximum = max(totals, default=0.0)
    return {'evidence': descriptor(path), 'sample_count': len(observations),
            'ticks_per_second': hz, 'observation_wall_seconds': observations[-1]['wall_time'] - observations[0]['wall_time'],
            'sampled_peak_group_rss_bytes': max((sum(row['rss_bytes'] for row in shot['processes']) for shot in observations), default=0),
            'sampled_max_process_count': max((len(shot['processes']) for shot in observations), default=0),
            'max_observed_interval_cpu_cores': maximum,
            'max_observed_cpu_fraction_of_reserved_slots': maximum / cpu_slots,
            'known_process_identity_interval_cpu_seconds': observed_cpu,
            'worker_processes': [{'pid': pid, 'birth': birth, 'sampled_peak_rss_bytes': peak,
                                  'max_observed_interval_cpu_cores': max_rates.get((pid, birth))}
                                 for (pid, birth), peak in sorted(peak_per_pid.items()) if pid in worker_pids],
            'max_nonworker_observed_interval_cpu_cores': max((rate for (pid, _), rate in max_rates.items() if pid not in worker_pids), default=0.0),
            'scope': 'Polled process-group lower bounds, not kernel quotas. CPU rates use only identities present at both adjacent observations; short-lived processes are omitted. RSS may count shared pages repeatedly. SC_CLK_TCK is read on this same audit host.'}


def summarize(label):
    audit_path = BASE / (label + '-audit.json')
    audit = read(audit_path)
    # Source-guard failures remain failures; intact artifacts can still support
    # raw observations, never a parity-backed speed claim.
    command = verified(audit['command'])
    binding = verified(audit['binding'])
    cycle = verified(audit['cycle'])
    assert command['returncode'] == 0 and command['source_unchanged'] and command['checkpoint_unchanged']
    assert binding['core_sources'] == audit['core_sources']
    assert binding['input_sha256'] == audit['input_sha256'] and binding['validation_sha256'] == audit['validation_sha256']
    resource = audit['resource_record']
    assert resource['status'] == 'released' and not resource['attempt_exceeded_reservation']
    workers = {}
    for path in (BASE / label / 'progress/outputs').glob('*/receipt.json'):
        worker = read(path)
        assert worker['run_id'] not in workers
        workers[worker['run_id']] = path, worker
    assert len(workers) == audit['counts']['jobs'] == 8
    rows = []
    for sample_id, row in audit['rows'].items():
        path, worker = workers[row['run_id']]
        reference = descriptor(path)
        assert {key: reference[key] for key in ['sha256', 'bytes']} == row['worker_receipt']
        assert worker['source_manifest_verified'] and worker['sample_count'] == worker['validation_sample_count'] == 1
        assert worker['bridge_names'] == BRIDGES and worker['legal_ir_evaluate_provers'] is False
        assert worker['metric_disk_cache'] == 0 and worker['legal_ir_parallel_workers'] == 1
        assert worker['use_sample_memory'] is False
        assert worker['effective_projection_config']['projection_update_backend'] == 'python_sparse_batch'
        profile = row['first_bridge_on_evaluation']
        target = profile['target_observation']
        assert profile['sample_count'] == target['target_count'] == 1
        assert target['bridge_names'] == BRIDGES and target['evaluate_provers'] is False
        assert target['disk_cache_enabled'] is False and target['parallel_workers_requested'] == 1
        qualification = verified(row['qualification_receipt'])
        # Qualification embedding-only evaluations must not masquerade as IR timings.
        assert qualification['metric_evaluation']['legal_ir_target_count'] == 0
        assert qualification['metric_evaluation']['bridge_names'] == []
        metrics_wall = sum(item['model_evaluation_elapsed_seconds'] for item in qualification['rows'])
        structural_wall = sum(item['structural_elapsed_seconds'] for item in qualification['rows'])
        rows.append({'sample_identity': sample_id, 'source_text': row['source_text'], 'lane': row['lane'],
            'base_sha256': row['base']['sha256'], 'candidate_sha256': row['candidate']['sha256'],
            'worker_receipt': reference, 'qualification_receipt': row['qualification_receipt'],
            'qualified': row['qualified'], 'status': row['status'], 'gates': row['gates'],
            'accepted_epochs': row['accepted_epochs'], 'selected_updates': row['selected_updates'],
            'worker_wall_seconds': worker['elapsed_seconds'], 'training_seconds': worker['training_seconds'],
            'base_checkpoint_load_seconds': worker['base_checkpoint_load_seconds'],
            'weight_load_seconds_after_json_parse': worker['weight_load_seconds_after_json_parse'],
            'candidate_serialization_seconds': worker['candidate_serialization_seconds'],
            'target_load_seconds': worker['target_load_seconds'], 'target_hydration_seconds': worker['target_hydration_seconds'],
            'qualification_wall_seconds': row['qualification_seconds'],
            'qualification_embedding_only_model_seconds': metrics_wall,
            'qualification_structural_seconds': structural_wall,
            'qualification_outside_rows_residual_seconds': row['qualification_seconds'] - metrics_wall - structural_wall,
            'first_bridge_on_evaluation': {'total_seconds': profile['total_seconds'], 'sample_count': 1,
                'evaluation_role': 'before_holdout_evaluation_on_repeated_tuning_validation',
                'evaluated_sources': [item['text'] for item in row['validation_samples']],
                'target_payload_seconds': profile['target_payload_seconds'], 'model_metrics_seconds': profile['model_metrics_seconds'],
                'ontology_capture_seconds': profile['ontology_capture_seconds'], 'target_observation': target,
                'decompiler_evidence': worker['training_report']['before']['decompiler_evidence']},
            'runtime': worker['runtime'], 'process_target_cache_initial_entries': worker['process_target_cache_initial_entries'],
            'process_cache_initially_empty': worker['process_cache_initially_empty']})
    keys = ['worker_wall_seconds', 'training_seconds', 'base_checkpoint_load_seconds', 'weight_load_seconds_after_json_parse',
            'candidate_serialization_seconds', 'target_load_seconds', 'target_hydration_seconds', 'qualification_wall_seconds',
            'qualification_embedding_only_model_seconds', 'qualification_structural_seconds', 'qualification_outside_rows_residual_seconds']
    totals = {key: sum(row[key] for row in rows) for key in keys}
    dispatch = sum(item['elapsed_seconds'] for item in cycle['training']['dispatch_reports'])
    observation_path = Path(audit['cycle']['path']).parent / 'process-observations.json'
    return {'label': label, 'audit': descriptor(audit_path), 'command': audit['command'], 'binding': audit['binding'],
        'cycle': audit['cycle'], 'run_producer_manifest': binding['producer_manifest'],
        'post_run_audit_producer_manifest': audit['producer_manifest'],
        'audit_check_count': audit['check_count'],
        'native_audit_passed': audit['passed'], 'native_audit_failures': audit['failures'],
        'native_audit_successful_check_count': audit['check_count'] - len(audit['failures']),
        'observations_only': not audit['passed'], 'wall_seconds': command['wall_seconds'],
        'wall_seconds_per_training_span': command['wall_seconds'] / len(rows), 'sample_count': len(rows),
        'counts': audit['counts'], 'configuration': audit['configuration'],
        'compute_backend': 'python', 'projection_update_backend': 'python_sparse_batch',
        'logical_lane_count': audit['logical_lane_count'], 'requested_parallel_workers': command['parallel_workers'],
        'actual_wave_widths': audit['dispatch_widths'], 'capacity_reports': cycle['training']['capacity_reports'],
        'resource_reservation': {key: resource[key] for key in ['cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes', 'status']},
        'finalization_profile': resource['finalization_profile'],
        'process_observations': process_summary(observation_path, [item[1] for item in workers.values()], resource['cpu_slots']),
        'dispatch_wall_seconds_sum': dispatch, 'phase_totals': totals,
        'outside_dispatch_and_serial_qualification_wall_residual_seconds': command['wall_seconds'] - dispatch - totals['qualification_wall_seconds'],
        'phase_scope': 'Worker phase totals overlap during parallel execution; they are not end-to-end elapsed time. Qualification is serial in these routes. Checkpoint load and target subphases are nested, not additive.',
        'rows': rows, 'admitted': False}


def comparisons(runs):
    candidates = []
    for path in sorted(BASE.glob('*parity*.json')):
        value = read(path)
        if value.get('schema') == 'native-optimizer-speed-parity-audit/v1':
            candidates.append((path, value))
    results = []
    for before, after in [('baseline', 'optimized'), ('optimized', 'rechecked'), ('rechecked', 'automatic-retry'), ('baseline', 'automatic-retry')]:
        if before not in runs or after not in runs:
            continue
        left, right = runs[before], runs[after]
        matches = [(path, report) for path, report in candidates
                   if report.get('before_audit') == left['audit'] and report.get('after_audit') == right['audit']]
        same_producer = (left['run_producer_manifest'] == right['run_producer_manifest']
                         == left['post_run_audit_producer_manifest'] == right['post_run_audit_producer_manifest'])
        controlled_pair = (before, after) == ('rechecked', 'automatic-retry')
        eligible = (controlled_pair and same_producer and left['native_audit_passed'] and right['native_audit_passed']
                    and any(report.get('passed') is True and report.get('speed_claim_eligible') is True for _, report in matches))
        results.append({'before': before, 'after': after,
            'parity_receipts': [{'evidence': descriptor(path), 'passed': report['passed'], 'check_count': report['check_count'],
                                'failures': report['failures'], 'scope': report['scope'], 'speed_claim_eligible': report['speed_claim_eligible']}
                               for path, report in matches],
            'speed_claim_eligible': eligible,
            'speed_claim_prerequisites': {'controlled_rechecked_automatic_retry_pair': controlled_pair,
                                         'identical_native_and_post_run_audit_complete_producer_manifests': same_producer,
                                         'both_native_audits_passed': left['native_audit_passed'] and right['native_audit_passed'],
                                         'matching_successful_parity_receipt': any(report.get('passed') is True and report.get('speed_claim_eligible') is True for _, report in matches)},
            'measured_wall_seconds_before': left['wall_seconds'], 'measured_wall_seconds_after': right['wall_seconds'],
            'observed_difference_seconds': left['wall_seconds'] - right['wall_seconds'],
            'eligible_wall_time_reduction_fraction': 1 - right['wall_seconds'] / left['wall_seconds'] if eligible else None,
            'scope': 'Single sequential unprofiled routes; differences may include system noise. Only rechecked-to-automatic-retry with identical complete producer manifests and successful native plus exact-result parity audits can support a speed claim; historical source-drift routes remain raw observations.'})
    return results



def failed_attempts():
    attempts = []
    for label in ['baseline', 'optimized', 'rechecked', 'automatic', 'automatic-retry']:
        command_path = BASE / (label + '-command.json')
        if not command_path.exists():
            continue
        command = read(command_path)
        if command['returncode'] == 0:
            continue
        binding_path, log_path = BASE / (label + '-binding.json'), BASE / (label + '.log')
        worker_receipts = list((BASE / label / 'progress/outputs').glob('*/receipt.json'))
        cycle_receipts = list((BASE / label / 'cycles').glob('*/cycle.json'))
        log = log_path.read_text() if log_path.exists() else ''
        capacity_failure = ('storage reservation capacity exceeded' in log
                            and not worker_receipts and not cycle_receipts)
        attempts.append({'label': label, 'command': descriptor(command_path),
            'binding': descriptor(binding_path) if binding_path.exists() else None,
            'log': descriptor(log_path) if log_path.exists() else None,
            'returncode': command['returncode'], 'failed_attempt_elapsed_seconds': command['wall_seconds'],
            'source_unchanged_during_attempt': command.get('source_unchanged'),
            'checkpoint_unchanged': command.get('checkpoint_unchanged'),
            'prelaunch_failed': capacity_failure,
            'failure_reason': 'storage_reservation_capacity_exceeded_before_worker_launch' if capacity_failure else 'failed_command_see_log',
            'worker_receipt_count': len(worker_receipts), 'cycle_completion_receipt_count': len(cycle_receipts),
            'excluded_from_completed_training_timings': True, 'speed_claim_eligible': False,
            'capacity_followup_evidence': [descriptor(path) for path in sorted(BASE.glob(label + '-capacity-blocked-*')) if path.is_file()],
            'admitted': False})
    return attempts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', nargs='+', choices=['baseline', 'optimized', 'rechecked', 'automatic', 'automatic-retry'], default=['baseline', 'optimized', 'rechecked', 'automatic-retry'])
    parser.add_argument('--output', type=Path, default=BASE / 'native-performance-summary.json')
    args = parser.parse_args()
    missing = {label: [str(BASE / (label + suffix)) for suffix in ['-audit.json', '-command.json', '-binding.json']
                       if not (BASE / (label + suffix)).exists()] for label in args.labels}
    missing = {label: paths for label, paths in missing.items() if paths}
    failures = failed_attempts()
    failed_labels = {item['label'] for item in failures}
    missing = {label: paths for label, paths in missing.items() if label not in failed_labels}
    runs = {label: summarize(label) for label in args.labels if label not in missing and label not in failed_labels}
    if not runs:
        raise SystemExit('No completed native evidence is available')
    result = {'schema_version': 'source-bound-native-performance-summary/v1', 'runs': runs,
              'comparisons': comparisons(runs), 'completed_requested_runs': list(runs), 'pending_runs': missing,
              'failed_attempts': failures,
              'producer_drift_evidence': {path.name: descriptor(path) for path in [BASE / 'readiness-provenance-audit.json', BASE / 'post-optimized-producer-drift.json', BASE / 'package-controlled-before.json', BASE / 'resource-closeout.json'] if path.exists()},
              'attribution_limit': 'Baseline-to-optimized bindings also include four external source changes. A subsequent entity_cache.py edit invalidated the optimized post-run full producer audit; those timings remain raw observations. Rechecked-to-automatic-retry is evaluated independently and requires the same complete producer manifest and passing native/parity audits.',
              'scope': 'Eight synthetic duration fixtures; the 30-day validation sentence is reused for tuning, not an independent held-out canary. Existing Lake receipts and six family syntax projections are audited separately. No new training, inference or proof process is executed by this summary.',
              'metric_scope': 'First bridge-on evaluations have one target and all five configured bridges; embedding-only qualification timings have zero IR targets and are reported separately.',
              'admitted': False, 'formalized': False, 'constitution_formalized': False}
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': descriptor(args.output), 'runs': {key: {'wall_seconds': value['wall_seconds'], 'waves': value['actual_wave_widths'], 'qualified': value['counts']['qualified']} for key, value in runs.items()}, 'comparisons': result['comparisons']}))

if __name__ == '__main__':
    main()
