#!/usr/bin/env python3
"""Summarize audited fixed-parent optimizer work and losses; no producer imports."""
from pathlib import Path
import hashlib
import json

BASE = Path(__file__).resolve().parent
RUN = BASE / 'native-three-arm-retry'


def read(path):
    return json.loads(path.read_bytes())


def ref(path):
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def small_metrics(evaluation):
    losses = evaluation['legal_ir_losses']
    deontic = evaluation['legal_ir_view_family_metrics']['deontic']
    return {'cosine': evaluation['embedding_cosine_similarity'], 'reconstruction_loss': evaluation['reconstruction_loss'],
        'family_ce': evaluation['cross_entropy_loss'], 'family_ce_excess': evaluation['cross_entropy_excess_loss'],
        'ir_view_ce': losses['legal_ir_view_cross_entropy_loss'], 'ir_view_ce_excess': losses['legal_ir_view_cross_entropy_excess_loss'],
        'deontic_ir_cosine': deontic['ir_cosine_similarity'], 'deontic_ir_ce': deontic['ir_cross_entropy_loss']}


def main():
    audit, comparison = read(BASE / 'native-audit.json'), read(RUN / 'comparison.json')
    assert audit['passed'] and not audit['failures']
    fixed = comparison['arms'][0]
    rows = []
    for arm in comparison['arms']:
        stages = arm['profile_by_stage']
        nonnested = {key: stages[key]['seconds'] for key in ('before_holdout_evaluation', 'training_cache_prime',
                                                            'line_search_evaluation', 'projection_update_batch')}
        bridge = arm['bridge_evaluations']
        cold = [{'stage': item['stage'], 'sample_count': item['sample_count'],
                 'seconds': item['seconds'], 'seconds_per_span': item['seconds'] / item['sample_count'],
                 'target_count': item['observation']['target_count'],
                 'native_target_attempts': item['observation']['native_evaluation_attempt_count'],
                 'memory_hits': item['observation']['memory_cache_hit_count'],
                 'cache_empty_at_start': item['observation']['process_target_cache_empty_at_start']}
                for item in bridge if item['observation']['native_evaluation_attempt_count']]
        warm = [item['seconds'] for item in bridge if not item['observation']['native_evaluation_attempt_count']]
        failed = [{'text': item['source']['text'], 'cosine': item['metric_gate']['embedding_cosine_similarity'],
                   'reconstruction_loss': item['metric_gate']['reconstruction_loss'], 'reasons': item['metric_gate']['reasons']}
                  for item in arm['qualification_rows'] if not item['qualified']]
        rows.append({'arm': arm['arm'], 'attempted_epochs': arm['attempted_epochs'], 'accepted_epochs': arm['accepted_epochs'],
            'initial_objective': arm['initial_objective'], 'final_objective': arm['final_objective'], 'objective_reduction': arm['objective_reduction'],
            'training_seconds': arm['training_seconds'], 'training_seconds_per_span': arm['training_seconds_per_span'],
            'arm_wall_seconds_including_owner_and_qualification': arm['elapsed_seconds'],
            'arm_wall_seconds_per_training_span': arm['elapsed_seconds'] / 8,
            'training_seconds_reduction_vs_fixed_percent': 100 * (1 - arm['training_seconds'] / fixed['training_seconds']),
            'objective_reduction_per_epoch': arm['objective_reduction_per_attempted_epoch'],
            'objective_reduction_per_bridge_evaluation': arm['objective_reduction_per_bridge_evaluation'],
            'objective_reduction_per_training_second': arm['objective_reduction_per_training_second'],
            'candidate_tuning_evaluations': arm['candidate_tuning_search_evaluation_count'],
            'bridge_on_evaluations': arm['bridge_on_evaluation_count'], 'native_target_attempts': arm['legal_ir_native_attempt_count'],
            'memory_cache_hits': arm['memory_cache_hit_count'], 'disk_cache_hits': 0,
            'fixed_final_threshold': arm['fixed_final_objective_threshold'],
            'threshold_epoch': arm['threshold_first_observed_epoch'], 'threshold_training_seconds': arm['threshold_first_observed_training_seconds'],
            'threshold_time_reduction_vs_fixed_percent': 100 * (1 - arm['threshold_first_observed_training_seconds'] / fixed['threshold_first_observed_training_seconds']),
            'curve': arm['curve'], 'metrics_before': small_metrics(arm['metrics_before']), 'metrics_after': small_metrics(arm['metrics_after']),
            'head_productivity': arm['head_productivity'], 'nonnested_profile_seconds': nonnested,
            'training_seconds_outside_these_profile_phases': arm['training_seconds'] - sum(nonnested.values()),
            'qualification_seconds': arm['qualification_seconds'], 'qualified': arm['qualified'],
            'qualification_gate_results': arm['qualification_gates'], 'failed_qualification_rows': failed,
            'cold_target_evaluations': cold, 'warm_tuning_evaluation_seconds': {'count': len(warm),
                'mean': sum(warm) / len(warm), 'minimum': min(warm), 'maximum': max(warm)},
            'artifact': ref(RUN / arm['arm'] / 'summary.json')})
    canaries = read(RUN / 'selected-canary.json')
    canary_rows = [{'arm': item['arm'], 'roles': item['roles'], 'objective': item['objective'],
                   'metrics': small_metrics(item['evaluation']), 'elapsed_seconds': item['elapsed_seconds'],
                   'sample_count': item['evaluation']['sample_count'], 'target_count': item['evaluation']['legal_ir_target_count'],
                   'target_observation': item['evaluation']['evaluation_profile']['target_observation']}
                  for item in canaries['results']]
    result = {'schema': 'autoencoder-convergence-summary/v1', 'audit': ref(BASE / 'native-audit.json'),
        'comparison': ref(RUN / 'comparison.json'), 'producer_manifest': comparison['producer_manifest'], 'counts': audit['counts'],
        'configuration': {'sample_count': 8, 'tuning_sample_count': 1, 'canary_sample_count': 2,
            'bridge_names': ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router'],
            'provers': False, 'disk_cache': 0, 'legal_ir_workers': 1, 'use_sample_memory': False,
            'temperature': 0, 'epochs': 5, 'max_line_search_attempts': 2, 'max_seconds': 180,
            'projection_max_update_families': 5, 'composed_refinement_attempts': 0, 'backend': 'python_sparse_batch'},
        'arms': rows, 'selected_arm': comparison['selection']['selected_arm'], 'canary_results': canary_rows,
        'canary_objective_delta_selected_minus_fixed': comparison['canary_summary']['objective_delta_selected_minus_fixed'],
        'limitations': [
            'One ordered three-arm synthetic benchmark, not a randomized replicated timing study or federal-law canary.',
            'Both tuning family CE and CE excess stay at ln(9)=2.197224577336 with inactive family-logit scales; zero total loss is not an attainable target established here.',
            'Finite family-logit and decoded-embedding proposals have zero tuning objective response in this fixture; reported gradient/update norms are delta-derived.',
            'Target-aware reconstruction projection can return the supplied target embedding. Passing embedding metrics alone would not establish learned text/formula generation.',
            'All three arms fail the unchanged metric gate for the same five training rows; both synthetic canary embeddings also fail cosine/MSE thresholds.',
            'Lake admits only the generated locked numeric minimum-duration statements. Family parser success covers the existing atom projection, not full temporal/cognitive/event-law semantics.',
            'The descriptive fixed-final threshold is not a global-optimum or convergence proof. No weight promotion or Hub upload occurred.',
            'Selected canary target cache is warm after fixed-reference evaluation; their inference timings are not a matched cold speed comparison.',
            'Initial failed run is excluded due unrelated full-package source drift; its receipts and full storage claim remain retained.'
        ], 'resource_closeout': ref(BASE / 'resource-closeout.json'), 'admitted': False, 'global_minimum_claim': False}
    with (BASE / 'convergence-summary.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'arms': [{key: row[key] for key in ('arm', 'final_objective', 'training_seconds',
        'training_seconds_reduction_vs_fixed_percent', 'threshold_training_seconds', 'threshold_time_reduction_vs_fixed_percent', 'qualified')} for row in rows],
        'canary_delta': result['canary_objective_delta_selected_minus_fixed']}))


if __name__ == '__main__':
    main()
