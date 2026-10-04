"""Prospective retention and source-only contracts for placement stability.

This module imports no model or training runtime and opens no files. Source
queries and predictions use the frozen owner-TYPE wire. Reference membership
is used only in scoring; it never becomes a numerical model input. Passing
these gates does not establish an owner occurrence, attachment, or formula.
"""
from __future__ import annotations

import hashlib
import math
import re

from . import legal_temporal_ownership_metrics as metric

SCHEMA = 'legal-temporal-stability-gate-counts/v1'
SELECTION_SCHEMA = 'legal-temporal-stability-selection/v1'
RETENTION_PANELS = ('single_tuning', 'prior_paired_tuning', 'old_single_fresh',
                    'old_multi_fresh', 'prior_fresh_lexical', 'prior_fresh_structural',
                    'placement_exposed_lexical', 'placement_exposed_structural')
NEW_TUNING = 'placement_tuning'
PANELS = (*RETENTION_PANELS, NEW_TUNING)
PANEL_COUNTS = dict(zip(PANELS, (144, 288, 192, 96, 144, 144, 144, 144, 288)))
STEPS = (0, 50, 100, 200)
CLASSES = metric.CLASSES
FALSE = {'current_fresh_results_used': False, 'owner_occurrence_resolved': False,
         'source_semantics_verified': False, 'attachment_or_formula_acceptance_measured': False,
         'pipeline_promotion': False}
CLASS_FIELDS = {'support', 'query_ids', 'correct', 'correct_ids', 'accepted_correct',
                'accepted_correct_ids', 'accepted_errors', 'accepted_error_ids'}
GATE_FIELDS = {'schema', 'count', 'class_order', 'threshold', 'source_targets_sha256',
               'per_class', 'correct', 'accepted_type_proposals', 'accepted_type_errors',
               'confusion_target_rows_prediction_columns', 'macro_f1', 'mean_nll', *FALSE}
ROW_FIELDS = {'id', 'source_sha256', 'proposed_time_span', 'target', 'predicted', 'correct',
              'accepted_type_proposal', 'accepted_type_error', 'ambiguous_confidently_resolved'}
require = metric.require
wire = metric.wire


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def _integer(value, low, high, message):
    require(type(value) is int and low <= value <= high, message)


def _ids(values):
    require(type(values) is list and all(type(v) is str and 0 < len(v) <= 256 for v in values)
            and values == sorted(set(values)), 'sorted unique bounded query IDs required')
    return set(values)


def gate_counts(scored):
    """Derive count/ID gates from every row of a frozen metric.score result.

    The caller must obtain ``scored`` by joining authenticated predictions to
    authoritative sources and targets. This function additionally reconciles
    all gate counts, confusion cells, and macro-F1 with those complete rows.
    NLL is independently calculated by the frozen scorer, not guessed here.
    """
    require(type(scored) is dict and type(scored.get('rows')) is list and
            1 <= len(scored['rows']) <= 4096, 'complete bounded scored rows required')
    require(scored.get('class_order') == list(CLASSES) and
            type(scored.get('threshold')) is float and scored['threshold'] == metric.THRESHOLD,
            'fixed owner taxonomy and threshold required')
    require(all(scored.get(k) is False for k in
                ('owner_occurrence_resolved', 'source_semantics_verified',
                 'attachment_or_formula_acceptance_measured')), 'type scoring cannot assert semantic authority')
    by_class = {c: {'query_ids': [], 'correct_ids': [], 'accepted_correct_ids': [],
                    'accepted_error_ids': []} for c in CLASSES}
    matrix = [[0] * 4 for _ in CLASSES]
    identities, seen, occurrences = [], set(), set()
    for row in scored['rows']:
        require(type(row) is dict and set(row) == ROW_FIELDS, 'closed scored query required')
        identity = row['id']; require(type(identity) is str and 0 < len(identity) <= 256
                                     and identity not in seen, 'unique bounded scored query ID required')
        seen.add(identity)
        require(type(row['source_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', row['source_sha256']),
                'source SHA required')
        interval = row['proposed_time_span']
        require(type(interval) is dict and set(interval) == {'char_start', 'char_end'} and
                type(interval['char_start']) is int and type(interval['char_end']) is int and
                0 <= interval['char_start'] < interval['char_end'] <= 40000, 'exact occurrence interval required')
        occurrence = (row['source_sha256'], interval['char_start'], interval['char_end'])
        require(occurrence not in occurrences, 'duplicate source occurrence')
        occurrences.add(occurrence)
        target, prediction = row['target'], row['predicted']
        require(target in CLASSES and prediction in CLASSES, 'known target and predicted type required')
        require(all(type(row[k]) is bool for k in ROW_FIELDS if k in
                    ('correct', 'accepted_type_proposal', 'accepted_type_error', 'ambiguous_confidently_resolved')),
                'strict scored decision booleans required')
        correct, accepted = target == prediction, row['accepted_type_proposal']
        require(row['correct'] == correct and row['accepted_type_error'] == (accepted and not correct)
                and row['ambiguous_confidently_resolved'] == (accepted and target == 'ambiguous')
                and (prediction != 'ambiguous' or not accepted), 'scored decisions contradict fixed type policy')
        values = by_class[target]; values['query_ids'].append(identity)
        if correct: values['correct_ids'].append(identity)
        if accepted: values['accepted_correct_ids' if correct else 'accepted_error_ids'].append(identity)
        matrix[CLASSES.index(target)][CLASSES.index(prediction)] += 1
        identities.append({k: row[k] for k in ('id', 'source_sha256', 'proposed_time_span', 'target')})
    for values in by_class.values():
        for key in tuple(values): values[key].sort()
        for count_key, ids_key in (('support', 'query_ids'), ('correct', 'correct_ids'),
                                  ('accepted_correct', 'accepted_correct_ids'), ('accepted_errors', 'accepted_error_ids')):
            values[count_key] = len(values[ids_key])
    count = len(seen); correct = sum(x['correct'] for x in by_class.values())
    errors = sum(x['accepted_errors'] for x in by_class.values())
    accepted = errors + sum(x['accepted_correct'] for x in by_class.values())
    for key, expected in (('count', count), ('correct', correct), ('accepted_type_errors', errors),
                          ('accepted_type_proposals', accepted)):
        require(type(scored.get(key)) is int and scored[key] == expected, 'scored aggregate differs: ' + key)
    require(wire(scored.get('confusion_target_rows_prediction_columns')) == wire(matrix), 'confusion matrix differs')
    require(type(scored.get('per_class')) is dict and set(scored['per_class']) == set(CLASSES), 'complete class metrics required')
    f1 = []
    for i, name in enumerate(CLASSES):
        predicted = sum(row[i] for row in matrix); support = by_class[name]['support']; tp = matrix[i][i]
        for key, expected in (('support', support), ('correct', tp), ('predicted', predicted)):
            require(type(scored['per_class'][name].get(key)) is int and scored['per_class'][name][key] == expected,
                    'scored class count differs')
        f1.append(2 * tp / (support + predicted) if support + predicted else 0.)
    macro = math.fsum(f1) / 4
    require(type(scored.get('macro_f1')) in (int, float) and math.isfinite(scored['macro_f1']) and
            abs(scored['macro_f1'] - macro) <= 1e-14, 'macro-F1 differs from source-joined decisions')
    nll = scored.get('mean_nll')
    require(type(nll) in (int, float) and math.isfinite(nll) and nll >= 0, 'finite nonnegative mean NLL required')
    result = {'schema': SCHEMA, 'count': count, 'class_order': list(CLASSES), 'threshold': metric.THRESHOLD,
              'source_targets_sha256': digest(sorted(identities, key=lambda x: x['id'])),
              'per_class': by_class, 'correct': correct, 'accepted_type_proposals': accepted,
              'accepted_type_errors': errors, 'confusion_target_rows_prediction_columns': matrix,
              'macro_f1': macro, 'mean_nll': nll, **FALSE}
    validate_gate_counts(result)
    return result


def validate_gate_counts(value, *, expected_count=None):
    require(type(value) is dict and set(value) == GATE_FIELDS and value['schema'] == SCHEMA,
            'closed stability gate-count schema required')
    require(value['class_order'] == list(CLASSES) and type(value['threshold']) is float
            and value['threshold'] == metric.THRESHOLD and all(value[k] is False for k in FALSE),
            'fixed taxonomy/threshold and false semantic authority required')
    _integer(value['count'], 1, 4096, 'bounded exact panel count required')
    if expected_count is not None:
        require(type(expected_count) is int and value['count'] == expected_count, 'prospective panel count differs')
    require(type(value['source_targets_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', value['source_targets_sha256']),
            'source/target inventory digest required')
    require(type(value['per_class']) is dict and set(value['per_class']) == set(CLASSES), 'all four class gates required')
    all_ids, correct, accepted_correct, errors = set(), 0, 0, 0
    for name in CLASSES:
        part = value['per_class'][name]
        require(type(part) is dict and set(part) == CLASS_FIELDS, 'closed class gate required')
        ids, right = _ids(part['query_ids']), _ids(part['correct_ids'])
        accepted, wrong = _ids(part['accepted_correct_ids']), _ids(part['accepted_error_ids'])
        require(not all_ids & ids and right <= ids and accepted <= right and wrong <= ids - right,
                'class membership or accepted decision partition differs')
        all_ids |= ids
        for key, expected in (('support', len(ids)), ('correct', len(right)),
                              ('accepted_correct', len(accepted)), ('accepted_errors', len(wrong))):
            require(type(part[key]) is int and part[key] == expected, 'class count/ID set differs')
        require(name != 'ambiguous' or not accepted, 'ambiguous predictions must defer')
        correct += len(right); accepted_correct += len(accepted); errors += len(wrong)
    for key, expected in (('count', len(all_ids)), ('correct', correct),
                          ('accepted_type_proposals', accepted_correct + errors), ('accepted_type_errors', errors)):
        require(type(value[key]) is int and value[key] == expected, 'gate aggregate differs: ' + key)
    for key, low, high in (('macro_f1', 0., 1.), ('mean_nll', 0., float('inf'))):
        require(type(value[key]) in (int, float) and math.isfinite(value[key]) and low <= value[key] <= high,
                'finite selection metric required: ' + key)
    matrix = value['confusion_target_rows_prediction_columns']
    require(type(matrix) is list and len(matrix) == 4 and all(type(row) is list and len(row) == 4
            and all(type(x) is int and 0 <= x <= value['count'] for x in row) for row in matrix),
            'exact four-by-four confusion matrix required')
    f1 = []
    for i, name in enumerate(CLASSES):
        support = value['per_class'][name]['support']; tp = value['per_class'][name]['correct']
        require(sum(matrix[i]) == support and matrix[i][i] == tp, 'class gates disagree with confusion matrix')
        predicted = sum(row[i] for row in matrix)
        f1.append(2 * tp / (support + predicted) if support + predicted else 0.)
    require(abs(value['macro_f1'] - math.fsum(f1) / 4) <= 1e-14, 'gate macro-F1 differs from confusion matrix')
    return value


def panel_metrics(sources, predictions, labels):
    """Score complete authenticated source/prediction/reference inventories."""
    scored = metric.score(sources, predictions, labels)
    return {'metrics': scored, 'gate_counts': gate_counts(scored)}


def _same_panel(candidate, parent):
    validate_gate_counts(candidate); validate_gate_counts(parent)
    require(candidate['count'] == parent['count'] and candidate['source_targets_sha256'] == parent['source_targets_sha256']
            and all(candidate['per_class'][c]['query_ids'] == parent['per_class'][c]['query_ids'] for c in CLASSES),
            'retention requires identical full source occurrences and target membership')


def retention_panel(candidate, parent, *, full_retention=True):
    """Per-class floors, ceilings and no newly accepted wrong query IDs.

    New placement tuning uses only full-denominator class-correctness floors.
    All six historical panels additionally retain accepted-correct coverage.
    Low-confidence correct-to-wrong churn is reported even when a class floor
    is retained by an offsetting gain; these gates do not claim zero churn.
    """
    require(type(full_retention) is bool, 'explicit retention mode required')
    _same_panel(candidate, parent)
    failures, churn = [], {}
    for name in CLASSES:
        after, before = candidate['per_class'][name], parent['per_class'][name]
        if after['correct'] < before['correct']: failures.append(name + ':correct_below_parent')
        if full_retention:
            if after['accepted_errors'] > before['accepted_errors']: failures.append(name + ':accepted_errors_above_parent')
            if not set(after['accepted_error_ids']) <= set(before['accepted_error_ids']):
                failures.append(name + ':new_accepted_error_ids')
            if after['accepted_correct'] < before['accepted_correct']: failures.append(name + ':accepted_correct_below_parent')
        before_right, after_right = set(before['correct_ids']), set(after['correct_ids'])
        churn[name] = {'fixed_ids': sorted(after_right - before_right), 'lost_ids': sorted(before_right - after_right),
                       'new_accepted_error_ids': sorted(set(after['accepted_error_ids']) - set(before['accepted_error_ids']))}
    return {'eligible': not failures, 'failures': failures, 'class_churn': churn,
            'accepted_correct_coverage_gate_applied': full_retention,
            'zero_correctness_churn_required': False, **FALSE}


def candidate_eligibility(candidate_panels, parent_panels):
    require(type(candidate_panels) is dict and type(parent_panels) is dict
            and set(candidate_panels) == set(parent_panels) == set(PANELS), 'exact seven admitted panels required')
    reports = {}
    for name in PANELS:
        validate_gate_counts(candidate_panels[name], expected_count=PANEL_COUNTS[name])
        validate_gate_counts(parent_panels[name], expected_count=PANEL_COUNTS[name])
        require(all(parent_panels[name]['per_class'][c]['support'] == PANEL_COUNTS[name] // 4 for c in CLASSES),
                'prospective panel class denominator differs')
        reports[name] = retention_panel(candidate_panels[name], parent_panels[name], full_retention=name != NEW_TUNING)
    return {'eligible': all(x['eligible'] for x in reports.values()), 'panels': reports, **FALSE}


def rank(new_tuning, steps):
    validate_gate_counts(new_tuning, expected_count=PANEL_COUNTS[NEW_TUNING])
    require(type(steps) is int and steps in STEPS, 'prospective checkpoint step required')
    return (-new_tuning['macro_f1'], new_tuning['mean_nll'], steps)


def select_candidate(scores_by_step):
    """Parent0 is eligible by construction; no current fresh input is accepted."""
    require(type(scores_by_step) is dict and all(type(k) is int for k in scores_by_step)
            and set(scores_by_step) == set(STEPS), 'parent0 and all50/100/200 candidates required')
    checks = {step: candidate_eligibility(scores_by_step[step], scores_by_step[0]) for step in STEPS}
    ranks = {step: rank(scores_by_step[step][NEW_TUNING], step) for step in STEPS}
    eligible = [step for step in STEPS if checks[step]['eligible']]
    require(0 in eligible, 'unchanged parent must remain an explicit fallback')
    chosen = min(eligible, key=ranks.__getitem__)
    return {'schema': SELECTION_SCHEMA, 'selected_steps': chosen, 'eligible_steps': eligible,
            'ranking': {str(step): list(ranks[step]) for step in STEPS},
            'eligibility': {str(step): checks[step] for step in STEPS},
            'retention_panels': list(RETENTION_PANELS), 'ranking_panel': NEW_TUNING,
            'accepted_correct_coverage_gate_applied': True, 'zero_correctness_churn_required': False, **FALSE}


def source_only_predictions(sources, rows):
    require(type(sources) is list and type(rows) is list and 1 <= len(sources) == len(rows) <= 4096,
            'complete bounded source-only inventory required')
    require([s['id'] for s in sources] == [r['id'] for r in rows]
            and len({s['id'] for s in sources}) == len(sources), 'ordered unique source/prediction IDs required')
    occurrences = set()
    for source, row in zip(sources, rows):
        metric.checked_prediction(source, row)
        key = (source['source_sha256'], source['proposed_time_span']['char_start'], source['proposed_time_span']['char_end'])
        require(key not in occurrences, 'duplicate source occurrence')
        occurrences.add(key)
    return {'query_rows': len(sources), 'sources_sha256': digest(sources), 'predictions_sha256': digest(rows),
            'labels_supplied': False, 'owner_or_cue_spans_supplied': False, **FALSE}


def verify_replayed_rows(sources, saved_rows, actual_rows):
    before = source_only_predictions(sources, saved_rows)
    after = source_only_predictions(sources, actual_rows)
    require(wire(saved_rows) == wire(actual_rows), 'source-only numerical replay differs from exact saved rows')
    return {**after, 'saved_predictions_sha256': before['predictions_sha256'],
            'exact_saved_rows_replayed': True}
