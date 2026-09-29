"""Summarize sealed search/qualification receipts; no producer imports or execution."""
from collections import defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import os

BASE = Path(__file__).resolve().parent
BRIDGES = ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router']

def read(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('evidence JSON exceeds bound')
    return json.loads(path.read_bytes())

def descriptor(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

def verified(ref, root=None):
    path = Path(ref['path']) if 'path' in ref else root / 'artifacts' / ref['sha256'][:2] / ref['sha256']
    observed = descriptor(path)
    assert all(observed[key] == ref[key] for key in ('sha256', 'bytes'))
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
    command, binding, cycle = (verified(audit[key]) for key in ('command', 'binding', 'cycle'))
    root = BASE / label
    training = cycle['training']
    assert command['returncode'] == 0 and command['source_unchanged'] and command['checkpoint_unchanged']
    assert binding['producer_manifest'] == audit['producer_manifest']
    stages, trial_counts, metric_calls, native_targets = defaultdict(float), defaultdict(int), defaultdict(int), defaultdict(float)
    rows, workers = [], []
    for row in audit['rows'].values():
        worker = verified(row['worker_receipt'], root)
        qualification = verified(row['qualification_receipt'], root)
        workers.append(worker)
        assert worker['bridge_names'] == BRIDGES
        assert worker['legal_ir_evaluate_provers'] is False and worker['metric_disk_cache'] == 0
        assert worker['legal_ir_parallel_workers'] == 1 and worker['use_sample_memory'] is False
        report = worker['training_report']
        for stage, values in report['projection_profile']['by_stage'].items():
            stages[stage] += values['seconds']
        for event in report['projection_profile']['events']:
            profile = event.get('metadata', {}).get('evaluation_profile')
            if profile is None:
                continue
            observation = profile.get('target_observation', {})
            if observation.get('bridge_names') == BRIDGES and observation.get('target_count', 0) > 0:
                metric_calls[event['stage']] += 1
                native_targets['bridge_on_call_count'] += 1
                native_targets['legal_ir_target_observations_sum'] += observation['target_count']
                for key in ('native_evaluation_attempt_count', 'generated_target_count', 'memory_cache_hit_count', 'disk_cache_hit_count'):
                    native_targets[key] += observation.get(key, 0)
        per_row_trials = []
        for epoch in report['epoch_reports']:
            for trial in epoch.get('candidate_reports', []):
                if trial.get('composed_refinement') is not True:
                    continue
                trial_counts['attempted'] += 1
                trial_counts['accepted'] += int(trial['accepted'])
                trial_counts['validation_evaluated'] += int(trial['holdout_evaluated'])
                trial_counts['validation_skipped'] += int(not trial['holdout_evaluated'])
                trial_counts['training_evaluated'] += int(trial.get('training_evaluated', 'training_after' in trial))
                for reason in trial.get('rejection_reasons', []):
                    trial_counts['rejected_reason:' + reason] += 1
                per_row_trials.append({key: trial.get(key) for key in (
                    'update', 'accepted', 'holdout_evaluated', 'training_evaluated', 'evaluation_order',
                    'validation_evaluation_skipped_reason', 'objective_delta', 'training_reconstruction_delta',
                    'rejection_reasons', 'pareto_regressions')})
        first = row['first_bridge_on_evaluation']
        assert first['sample_count'] == first['target_observation']['target_count'] == 1
        assert first['target_observation']['bridge_names'] == BRIDGES
        assert qualification['metric_evaluation']['bridge_names'] == [] and qualification['metric_evaluation']['legal_ir_target_count'] == 0
        q_rows = [{ 'split': item['split'], 'source_text': item['source']['text'], 'metric_gate': item['metric_gate'] }
                  for item in qualification['rows']]
        rows.append({
            'source_text': row['source_text'], 'lane': row['lane'], 'base': row['base'], 'candidate': row['candidate'],
            'qualified': row['qualified'], 'status': row['status'], 'gates': row['gates'],
            'selected_updates': row['selected_updates'], 'accepted_epochs': row['accepted_epochs'],
            'training_seconds': worker['training_seconds'], 'worker_wall_seconds': worker['elapsed_seconds'],
            'qualification_wall_seconds': qualification['elapsed_seconds'],
            'qualification_embedding_only_seconds': sum(item['model_evaluation_elapsed_seconds'] for item in qualification['rows']),
            'qualification_structural_seconds': sum(item['structural_elapsed_seconds'] for item in qualification['rows']),
            'lake_seconds': sum(proof['elapsed_seconds'] for item in qualification['rows'] for proof in item['lake_gate']['rows']),
            'first_bridge_on_evaluation': first,
            'projection_objective_deltas': [epoch['objective_delta'] for epoch in report['epoch_reports']],
            'tuning_metrics_after': {key: report['after'][key] for key in (
                'reconstruction_loss', 'embedding_cosine_similarity', 'cross_entropy_excess_loss', 'legal_ir_losses')},
            'qualification_rows': q_rows, 'refinement_trials': per_row_trials,
        })
    wave_records = training.get('qualification_wave_reports', [])
    dispatch_wall = sum(item['elapsed_seconds'] for item in training['dispatch_reports'])
    qualification_task_sum = sum(row['qualification_wall_seconds'] for row in rows)
    qualification_wall = sum(wave['elapsed_seconds'] for wave in wave_records) if wave_records else qualification_task_sum
    resource = audit['resource_record']
    first_walls = [row['first_bridge_on_evaluation']['total_seconds'] for row in rows]
    result = {
        'label': label, 'audit': descriptor(audit_path), 'audit_passed': audit['passed'], 'audit_failures': audit['failures'],
        'audit_check_count': audit['check_count'], 'producer_manifest': binding['producer_manifest'],
        'command': audit['command'], 'cycle': audit['cycle'], 'counts': audit['counts'],
        'wall_seconds': command['wall_seconds'], 'wall_seconds_per_training_span': command['wall_seconds'] / len(rows),
        'logical_lane_count': audit['logical_lane_count'], 'training_dispatch_widths': audit['dispatch_widths'],
        'qualification_requested_workers': command.get('qualification_parallel_workers'),
        'qualification_wave_widths': [wave['max_workers'] for wave in wave_records],
        'qualification_capacity_reports': training.get('qualification_capacity_reports', []),
        'qualification_wave_records': wave_records,
        'dispatch_wall_seconds': dispatch_wall, 'qualification_wave_wall_seconds': qualification_wall,
        'qualification_task_wall_seconds_sum': qualification_task_sum,
        'outside_dispatch_and_qualification_wave_wall_seconds': command['wall_seconds'] - dispatch_wall - qualification_wall,
        'training_profile_stage_seconds_sum': dict(stages), 'composed_refinement_counts': dict(trial_counts),
        'bridge_on_profile_calls_by_stage': dict(metric_calls), 'bridge_target_observation_sums': dict(native_targets),
        'first_one_sample_bridge_on_evaluate_wall_range_seconds': [min(first_walls), max(first_walls)],
        'measurement_settings': {**audit['configuration'], 'cold_processes': True, 'disk_target_cache_enabled': False,
            'os_cache_controlled': False, 'later_process_target_reuse': True,
            'qualification_metric_scope': 'bridge_off_embedding_only_not_legal_IR_timing'},
        'resource_reservation': {key: resource[key] for key in ('cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes', 'status')},
        'process_observations': process_summary(Path(audit['cycle']['path']).parent / 'process-observations.json', workers, resource['cpu_slots']),
        'rows': sorted(rows, key=lambda row: row['source_text']),
        'phase_scope': 'Worker stage/task sums overlap under parallelism; wave wall includes parent receipt staging, later stable-order DB/outbox completion lies outside it. Nested phases must not be added twice.',
        'admitted': False, 'formalized': False,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', default='serial')
    parser.add_argument('--after', default='parallel')
    parser.add_argument('--parity', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before, after = summarize(args.before), summarize(args.after)
    parity = read(args.parity)
    prerequisites = {
        'both_native_audits_passed': before['audit_passed'] and after['audit_passed'],
        'same_complete_producer_manifest': before['producer_manifest'] == after['producer_manifest'],
        'successful_exact_result_parity_audit': parity['passed'] is True,
        'parity_bound_to_exact_audits': parity['before_audit'] == before['audit'] and parity['after_audit'] == after['audit'],
    }
    eligible = all(prerequisites.values())
    result = {'schema': 'native-search-and-qualification-performance/v1',
              'before': before, 'after': after, 'parity': descriptor(args.parity),
              'speed_claim_prerequisites': prerequisites, 'speed_claim_eligible': eligible,
              'wall_seconds_saved': before['wall_seconds'] - after['wall_seconds'],
              'wall_time_reduction_fraction': 1 - after['wall_seconds'] / before['wall_seconds'] if eligible else None,
              'scope': 'One sequential same-source synthetic fixture comparison of serial versus bounded parallel qualification. No repeated-run variance or representative federal-law generalization established.',
              'lowest_loss_scope': 'Best observed candidates under bounded search and unchanged qualification gates, not a certified global minimum.',
              'global_minimum_certified': False, 'untouched_canary': False, 'validation_role': 'repeated_tuning_validation',
              'admitted': False, 'formalized': False, 'constitution_formalized': False}
    with args.output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'speed_claim_eligible': eligible, 'before_seconds': before['wall_seconds'],
                      'after_seconds': after['wall_seconds'], 'wall_time_reduction_fraction': result['wall_time_reduction_fraction'],
                      'qualified': [before['counts']['qualified'], after['counts']['qualified']]}))
    return 0 if eligible else 1

if __name__ == '__main__':
    raise SystemExit(main())
