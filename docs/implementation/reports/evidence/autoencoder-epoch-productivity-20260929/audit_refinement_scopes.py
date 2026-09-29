#!/usr/bin/env python3
"""Read saved receipts only; distinguish training screens from qualification."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re

BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def ref(path):
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def training_rows(summary):
    result = {}
    for row in summary['qualification_rows']:
        duration = int(re.search(r'at least (\d+) days', row['source']['text']).group(1))
        if 20 <= duration <= 27:
            result[duration] = {
                'passed': row['qualified'],
                'cosine': row['metric_gate']['embedding_cosine_similarity'],
                'reconstruction_loss': row['metric_gate']['reconstruction_loss'],
                'reasons': row['metric_gate']['reasons'],
            }
    assert set(result) == set(range(20, 28))
    return result


def main():
    main_path = BASE / 'native-three-arm/productive_momentum/summary.json'
    integrated_path = BASE / 'integrated-productive-refined/productive_momentum_refined/summary.json'
    baseline, integrated = read(main_path), read(integrated_path)
    worker_path = Path(integrated['worker_receipt']['path'])
    report = read(worker_path)['training_report']
    main_manifest = read(BASE / 'native-three-arm/comparison.json')['producer_manifest']
    integrated_manifest = read(BASE / 'integrated-productive-refined/comparison.json')['producer_manifest']
    assert main_manifest == integrated_manifest
    epochs, counts = [], Counter()
    for epoch in report['epoch_reports']:
        trials = []
        for candidate in epoch['candidate_reports']:
            if '+decoded_embedding_refinement:' not in candidate.get('update', ''):
                continue
            keys = ('update', 'refinement_attempt', 'accepted', 'strict_accepted', 'training_evaluated',
                    'holdout_evaluated', 'validation_evaluation_skipped_reason', 'training_metric_scope',
                    'training_before', 'training_after', 'training_reconstruction_delta', 'objective_delta',
                    'rejection_reasons', 'pareto_regressions', 'selected_candidate_regressions')
            row = {key: candidate[key] for key in keys if key in candidate}
            assert row['training_metric_scope'] == 'bridge_off_reconstruction_only'
            counts['trials'] += 1
            if row['accepted']:
                assert row['strict_accepted'] and row['holdout_evaluated']
                assert row['training_reconstruction_delta'] > 0
                counts['strictly_accepted_trials'] += 1
            if row['holdout_evaluated']:
                counts['bridge_on_tuning_validations'] += 1
            else:
                assert row['validation_evaluation_skipped_reason'] == 'training_screen_rejected'
                assert row['objective_delta'] is None
                assert row['training_reconstruction_delta'] <= 0
                counts['training_screen_rejections'] += 1
                counts['negative_training_delta' if row['training_reconstruction_delta'] < 0 else 'zero_training_delta'] += 1
            trials.append(row)
        selected_refinement = '+decoded_embedding_refinement:' in epoch['selected_update']
        counts['selected_refinements'] += int(selected_refinement)
        epochs.append({'epoch': epoch['epoch'], 'selected_update': epoch['selected_update'], 'trials': trials})
    before, after = training_rows(baseline), training_rows(integrated)
    aggregate = lambda rows: {
        'sample_count': len(rows), 'passing_rows': sum(row['passed'] for row in rows.values()),
        'mean_cosine': sum(row['cosine'] for row in rows.values()) / len(rows),
        'mean_reconstruction_loss': sum(row['reconstruction_loss'] for row in rows.values()) / len(rows),
    }
    result = {
        'schema': 'autoencoder-refinement-scope-audit/v1', 'passed': True,
        'read_only_saved_receipts': True, 'producer_manifest': main_manifest,
        'same_full_producer': True, 'main_reference': ref(main_path),
        'integrated_reference': ref(integrated_path), 'worker_reference': ref(worker_path),
        'counts': dict(counts), 'epochs': epochs,
        'qualification_training_scope': 'bridge_on_individual_rows_20_through_27',
        'main_training_qualification': aggregate(before),
        'integrated_training_qualification': aggregate(after),
        'qualification_rows': {str(d): {'main': before[d], 'integrated': after[d]} for d in before},
        'repaired_durations': [d for d in before if not before[d]['passed'] and after[d]['passed']],
        'regressed_durations': [d for d in before if before[d]['passed'] and not after[d]['passed']],
        'persisting_failures': [d for d in before if not before[d]['passed'] and not after[d]['passed']],
        'late_bridge_off_screen': epochs[-1]['trials'][0]['training_before'],
        'notes': [
            'The bridge-off aggregate training screen is not final bridge-on qualification.',
            'Screen improvement permits individual-row regressions; every row still needs final qualification.',
            'Exact causal attribution of the bridge/cache context discrepancy requires a separate controlled replay; this audit does not rerun inference.',
            'This integration uses three extra refinement trials per epoch; it is not an isolated learning-rate speed comparison.',
            'No canary was evaluated for the integration and no candidate was promoted.',
        ], 'admitted': False,
    }
    with (BASE / 'integrated-refinement-scope-audit.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({key: result[key] for key in ('passed', 'counts', 'integrated_training_qualification',
        'repaired_durations', 'regressed_durations', 'persisting_failures')}))


if __name__ == '__main__':
    main()
