#!/usr/bin/env python3
"""Post-qualification temporal diagnostics and paired case-group comparisons.

Resamples case groups, keeping their variants and all three fixed seeds together.
These intervals describe this authored panel, not statutory generalization or
uncertainty over random training seeds. No fitting or output repair occurs here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import analyze_legal_mixed_replay_errors as earlier
from scripts.ops.legal_ir import audit_legal_grounding_experiment as evidence

require, ref, read_ref, raw = evidence.require, evidence.ref, evidence.read_ref, evidence.raw
SEEDS = (1729, 1730, 1731)
ARMS = ('baseline_continuation', 'baseline_grounding',
        'temporal_augmented_continuation', 'temporal_augmented_grounding', 'parent')
PANELS = ('fresh', 'earlier_regression', 'exposed_regression', 'mixed_regression')


def temporal_record(prediction, target):
    """Abstentions fail fidelity; presence confusion keeps them separately."""
    decoded = prediction['status'] == 'decoded'
    wanted = target['canonical_ir']['rules'][0]
    actual = prediction['canonical_ir']['rules'][0] if decoded else None
    positive = bool(wanted['temporal'])
    observed = bool(actual['temporal']) if decoded else None
    confusion = ('abstained_positive' if positive else 'abstained_negative') if not decoded else (
        'true_positive' if positive and observed else 'false_negative' if positive else
        'false_positive' if observed else 'true_negative')
    coordinates = target.get('facet_spans')
    boundary = None
    if coordinates is not None:
        diagnostic = prediction.get('span_diagnostics', {}).get('facets', {}).get('temporal', {})
        span = [diagnostic.get('char_start'), diagnostic.get('char_end')] if diagnostic.get('present') else None
        boundary = bool(decoded and span == coordinates['temporal'])
    return {'status': prediction['status'], 'exact': bool(decoded and prediction['canonical_ir'] == target['canonical_ir']),
        'temporal_positive': positive, 'temporal_presence': confusion,
        'temporal_value_exact': bool(decoded and actual['temporal'] == wanted['temporal']),
        'temporal_coordinate_exact': boundary,
        'temporal_condition_routing_exact': bool(decoded and actual['temporal'] == wanted['temporal']
            and actual['conditions'] == wanted['conditions']),
        'actor_exact': bool(decoded and actual['actor'] == wanted['actor']),
        'modality_exact': bool(decoded and actual['modality'] == wanted['modality']),
        'temporal_failure': earlier.facet_state(prediction, wanted['temporal'], 'temporal')}


def summarize_rows(rows):
    require(bool(rows), 'nonempty outcome rows required')
    counts = Counter(r['temporal_presence'] for r in rows)
    positives = sum(r['temporal_positive'] for r in rows)
    negatives = len(rows) - positives
    annotated = [r for r in rows if r['temporal_coordinate_exact'] is not None]
    annotated_positive = [r for r in annotated if r['temporal_positive']]
    ratio = lambda a, b: a / b if b else None
    return {'count': len(rows), 'exact': sum(r['exact'] for r in rows),
        'abstained': sum(r['status'] == 'abstained' for r in rows),
        'temporal_positive': positives, 'temporal_negative': negatives,
        'presence_confusion': {key: counts[key] for key in ('true_positive', 'false_negative', 'false_positive',
            'true_negative', 'abstained_positive', 'abstained_negative')},
        'presence_recall_all_positives': ratio(counts['true_positive'], positives),
        'correct_absence_rate_all_negatives': ratio(counts['true_negative'], negatives),
        'false_positive_rate_decoded_negatives': ratio(counts['false_positive'], counts['true_negative'] + counts['false_positive']),
        'temporal_coordinate_annotated': len(annotated),
        'temporal_coordinate_exact': sum(r['temporal_coordinate_exact'] for r in annotated),
        'positive_temporal_coordinate_annotated': len(annotated_positive),
        'positive_temporal_coordinate_exact': sum(r['temporal_coordinate_exact'] for r in annotated_positive),
        **{key: sum(r[key] for r in rows) for key in ('temporal_value_exact', 'temporal_condition_routing_exact', 'actor_exact', 'modality_exact')},
        'temporal_failures': dict(Counter(r['temporal_failure'] for r in rows))}


def paired_clusters(left, right, *, replicates=2000, random_seed=6831):
    """Paired percentile interval, whole case groups as sampling units."""
    require(type(replicates) is int and replicates >= 100, 'at least100 bootstrap replicates required')
    index = lambda rows: {(r['seed'], r['id']): r for r in rows}
    a, b = index(left), index(right)
    require(len(a) == len(left) == len(right) == len(b) and set(a) == set(b), 'unique paired seed/source slots required')
    grouped, outcomes = defaultdict(list), Counter()
    for identity in sorted(a):
        x, y = a[identity], b[identity]
        require(x['case_group'] == y['case_group'] and bool(x['case_group']), 'paired case groups differ')
        grouped[x['case_group']].append(int(x['exact']) - int(y['exact']))
        outcomes[bool(x['exact']), bool(y['exact'])] += 1
    require(len(grouped) >= 2, 'at least two independent case groups required')
    groups = [grouped[k] for k in sorted(grouped)]
    require(len({len(g) for g in groups}) == 1, 'balanced case-group variants/seeds required')
    means = [sum(g) / len(g) for g in groups]
    rng = random.Random(random_seed)
    draws = sorted(sum(rng.choices(means, k=len(means))) / len(means) for _ in range(replicates))
    return {'count': len(left), 'case_groups': len(groups), 'slots_per_case_group': len(groups[0]),
        'left_only_correct': outcomes[True, False], 'right_only_correct': outcomes[False, True],
        'both_correct': outcomes[True, True], 'both_wrong': outcomes[False, False],
        'exact_rate_difference': sum(means) / len(means),
        'case_group_bootstrap_95_percentile': [draws[int(.025 * (replicates - 1))], draws[int(.975 * (replicates - 1))]],
        'bootstrap_replicates': replicates, 'bootstrap_seed': random_seed,
        'sampling_unit': 'whole authored case group; all variants and three fixed seeds retained together',
        'scope': 'Descriptive conditional interval; no uncertainty over seeds, templates or real statutes.'}


def verify_membership(ledger, sources):
    require(len({row['id'] for row in ledger}) == len(ledger), 'duplicate annotation identity')
    membership = {row['id']: row for row in ledger}
    groups = defaultdict(set)
    for source in sources:
        row = membership.get(source['id'])
        require(row is not None and row['split'] == 'challenge' and row['source_sha256'] == source['source_sha256'],
            'fresh annotation source or split differs')
        groups[row['case_group']].add(row['variant'])
    require(len(sources) == 180 and len(groups) == 30 and all(len(v) == 6 for v in groups.values()),
        'thirty complete six-variant challenge cases required')
    require(len({tuple(sorted(v)) for v in groups.values()}) == 1, 'case variants differ')
    return membership


def verify_binding(recorded, actual):
    require(all(recorded.get(key) == actual.get(key) for key in ('path', 'sha256')), 'qualification binding differs')
    # Receipt producers differ only in whether they include optional byte sizes.
    # Check any recorded size against the file rather than comparing key sets.
    return read_ref(recorded)


def analyze(run_directory, qualification_directory, output):
    run, qualified = Path(run_directory).resolve(), Path(qualification_directory).resolve()
    require((qualified / 'summary.json').is_file() and (qualified / 'builds-frozen.json').is_file(),
        'completed qualification and builds required before reference access')
    frozen_ref, summary_ref, builds_ref = ref(run / 'generation-frozen.json'), ref(qualified / 'summary.json'), ref(qualified / 'builds-frozen.json')
    frozen, summary = read_ref(frozen_ref), read_ref(summary_ref)
    verify_binding(summary['generation_freeze'], frozen_ref)
    verify_binding(summary['builds'], builds_ref)
    plan = read_ref(frozen['plan']); config = read_ref(plan['config']); manifest = read_ref(config['corpus_manifest'])
    sources = read_ref(frozen['sources'])
    targets = {'fresh': read_ref(manifest['artifacts']['challenge_targets'])}
    for panel in PANELS[1:]:
        targets[panel] = read_ref(config[panel + '_targets'])
        if isinstance(targets[panel], dict): targets[panel] = targets[panel]['targets']
    ledger = read_ref(manifest['artifacts']['annotation_ledger'])
    if isinstance(ledger, dict): ledger = ledger['rows']
    membership = verify_membership(ledger, sources['fresh'])
    expected = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    require(len(frozen['models']) == len(expected) and {m['name'] for m in frozen['models']} == expected, 'all15 selected model slots required')
    models, aggregate_rows = {}, defaultdict(lambda: defaultdict(list))
    for model in frozen['models']:
        name, arm, seed = model['name'], model['arm'], model['seed']
        panels = {}
        for panel in PANELS:
            generation = read_ref(frozen['files'][name][panel])
            indexed = {row['id']: row for row in targets[panel]}
            require(len(indexed) == len(targets[panel]) == len(generation['rows']) == len(sources[panel]) and
                set(indexed) == {s['id'] for s in sources[panel]}, 'complete reference/source/generation denominator required')
            rows = []
            for prediction, source in zip(generation['rows'], sources[panel]):
                target = indexed[source['id']]
                require(target.get('source_text', source['source_text']) == source['source_text'], 'target source differs')
                evidence.verify_prediction(prediction, source)
                annotation = membership[source['id']] if panel == 'fresh' else {}
                row = {'id': source['id'], 'seed': seed, **temporal_record(prediction, target),
                    'case_group': annotation.get('case_group'), 'variant': annotation.get('variant', 'exposed_regression'),
                    'annotation': annotation}
                rows.append(row)
            panels[panel] = {'metrics': summarize_rows(rows), 'rows': rows}
            aggregate_rows[arm][panel].extend(rows)
        models[name] = {'arm': arm, 'seed': seed, 'selected_steps': model['selected_steps'], 'selection': model['selection'], 'panels': panels}
    totals = {}
    for arm in ARMS:
        totals[arm] = {}
        for panel in PANELS:
            rows = aggregate_rows[arm][panel]
            metric = summarize_rows(rows)
            require(metric['exact'] == summary['totals'][arm][panel]['exact'] and metric['count'] == summary['totals'][arm][panel]['count'],
                'independent whole-rule metric differs from qualifier')
            if panel == 'fresh':
                metric['by_variant'] = {key: summarize_rows([r for r in rows if r['variant'] == key]) for key in sorted({r['variant'] for r in rows})}
            totals[arm][panel] = metric
    comparisons = []
    pairs = [('temporal_augmented_continuation', 'baseline_continuation'),
        ('temporal_augmented_grounding', 'baseline_grounding'),
        ('temporal_augmented_grounding', 'temporal_augmented_continuation'),
        ('baseline_grounding', 'baseline_continuation')]
    for left, right in pairs:
        comparisons.append({'left': left, 'right': right, 'panel': 'fresh',
            **paired_clusters(aggregate_rows[left]['fresh'], aggregate_rows[right]['fresh'])})
    report = {'schema': 'legal-temporal-curriculum-posthoc/v1', 'analyzer': ref(__file__),
        'generation_freeze': frozen_ref, 'qualification': summary_ref, 'build_freeze': builds_ref,
        'annotation_ledger': manifest['artifacts']['annotation_ledger'], 'models': models, 'totals': totals,
        'paired_case_group_comparisons': comparisons, 'training_performed': False, 'outputs_or_selections_changed': False,
        'qualified': False, 'limitations': ['Authored supported single-rule cases, not independently adjudicated statutes.',
            'All three seeds reuse the same180 fresh sources and30 case groups.',
            'Temporal-condition routing measures the bounded schema; opaque condition atoms do not prove internal calendar semantics.',
            'Selected400/800 steps can differ under one predeclared tuning policy; this compares training-and-selection policies.',
            'No nested scope or family-wide logical equivalence claim follows from exact canonical outputs or successful builds.']}
    with Path(output).open('xb') as stream: stream.write(raw(report))
    return ref(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True)
    parser.add_argument('--qualification-directory', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(analyze(args.run_directory, args.qualification_directory, args.output))
