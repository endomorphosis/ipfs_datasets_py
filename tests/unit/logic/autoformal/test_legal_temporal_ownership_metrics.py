"""Independent known-distribution and source-inventory scoring checks."""
from copy import deepcopy
import hashlib
import math

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metric


def query(index=0, text=None, start=None):
    text = text or f'Registry{index} shall file within 14 days.'
    a = text.index('within 14 days') if start is None else start
    return {'id': f'q{index}', 'source_text': text,
            'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span': {'char_start': a, 'char_end': a+len('within 14 days')}}


def prediction(source, label='norm', strong=True):
    # One selected logit log(97), three zero logits give [0.97, .01, .01, .01].
    index = metric.CLASSES.index(label)
    logits = [0.]*4; probabilities = [.25]*4
    if strong:
        logits[index] = math.log(97)
        probabilities = [.01]*4; probabilities[index] = .97
    else:
        label = 'norm'; index = 0
    accepted = strong and label != 'ambiguous'
    return {'id': source['id'], 'source_sha256': source['source_sha256'],
        'proposed_time_span': deepcopy(source['proposed_time_span']),
        'time_token_span': metric.validate_source(source), 'logits': logits,
        'probabilities': probabilities, 'predicted_label': label, 'confidence': probabilities[index],
        'status': 'accepted' if accepted else 'deferred', 'owner_type': label if accepted else None,
        'reason': None if accepted else ('predicted_ambiguous' if label == 'ambiguous' else 'below_fixed_confidence'),
        **{key: False for key in metric.FALSE_FIELDS}}


def test_exact_known_four_class_distribution():
    sources = [query(i) for i in range(4)]
    labels = {s['id']: label for s, label in zip(sources, metric.CLASSES)}
    rows = [prediction(s, labels[s['id']]) for s in sources]
    result = metric.score(sources, rows, labels)
    assert result['correct'] == 4 and result['accuracy'] == result['macro_f1'] == 1
    assert result['mean_nll'] == pytest.approx(-math.log(.97))
    assert result['multiclass_brier_sum'] == pytest.approx(.0012)
    assert result['ece_10_equal_width_bins'] == pytest.approx(.03)
    assert result['accepted_type_proposals'] == 3 and result['accepted_type_errors'] == 0
    assert result['ambiguous_queries'] == 1 and result['ambiguous_confidently_resolved'] == 0


def test_uniform_predictions_count_abstentions_and_missing_class_predictions():
    sources = [query(i) for i in range(4)]
    labels = {s['id']: label for s, label in zip(sources, metric.CLASSES)}
    result = metric.score(sources, [prediction(s, strong=False) for s in sources], labels)
    assert result['correct'] == 1 and result['accuracy'] == .25
    assert result['macro_f1'] == pytest.approx(.1)
    assert result['mean_nll'] == pytest.approx(math.log(4))
    assert result['multiclass_brier_sum'] == .75
    assert result['ece_10_equal_width_bins'] == 0
    assert result['accepted_type_proposals'] == 0 and result['selective_type_error_rate'] is None


def test_confident_resolution_of_ambiguous_text_is_an_error():
    source = query(); result = metric.score([source], [prediction(source)], {source['id']: 'ambiguous'})
    assert result['ambiguous_confidently_resolved'] == result['accepted_type_errors'] == 1
    assert result['selective_type_error_rate'] == 1


@pytest.mark.parametrize('mutation', ['id', 'hash', 'float_span', 'bool_token', 'probabilities',
    'probability_nan', 'logit_nan', 'logit_bool', 'confidence', 'owner', 'authority', 'numeric_authority',
    'extra', 'status', 'reason'])
def test_repaired_or_inconsistent_predictions_are_rejected(mutation):
    source = query(); row = prediction(source)
    if mutation == 'id': row['id'] = 'other'
    if mutation == 'hash': row['source_sha256'] = '0'*64
    if mutation == 'float_span': row['proposed_time_span']['char_start'] = float(row['proposed_time_span']['char_start'])
    if mutation == 'bool_token': row['time_token_span'][0] = True
    if mutation == 'probabilities': row['probabilities'] = [.7, .1, .1, .1]; row['confidence'] = .7
    if mutation == 'probability_nan': row['probabilities'][0] = float('nan')
    if mutation == 'logit_nan': row['logits'][0] = float('nan')
    if mutation == 'logit_bool': row['logits'][0] = True
    if mutation == 'confidence': row['confidence'] = .5
    if mutation == 'owner': row['owner_type'] = 'exception'
    if mutation == 'authority': row['owner_occurrence_resolved'] = True
    if mutation == 'numeric_authority': row['owner_occurrence_resolved'] = 0
    if mutation == 'extra': row['gold_owner'] = 'norm'
    if mutation == 'status': row['status'] = 'deferred'
    if mutation == 'reason': row['reason'] = 'source_semantics_verified'
    with pytest.raises(ValueError): metric.checked_prediction(source, row)


@pytest.mark.parametrize('kind', ['source_label', 'source_hash', 'source_float', 'token_cut', 'source_empty'])
def test_source_boundary_and_type_contract(kind):
    source = query()
    if kind == 'source_label': source['label'] = 'norm'
    if kind == 'source_hash': source['source_text'] += ' Changed.'
    if kind == 'source_float': source['proposed_time_span']['char_end'] = float(source['proposed_time_span']['char_end'])
    if kind == 'token_cut': source['proposed_time_span']['char_start'] += 1
    if kind == 'source_empty': source['source_text'] = ''
    with pytest.raises(ValueError): metric.validate_source(source)


@pytest.mark.parametrize('kind', ['missing_prediction', 'duplicate_prediction', 'extra_label', 'duplicate_occurrence'])
def test_complete_query_denominator_is_required(kind):
    sources = [query(0), query(1)]
    rows = [prediction(s) for s in sources]; labels = {s['id']: 'norm' for s in sources}
    if kind == 'missing_prediction': rows.pop()
    if kind == 'duplicate_prediction': rows[1] = deepcopy(rows[0])
    if kind == 'extra_label': labels['unknown'] = 'norm'
    if kind == 'duplicate_occurrence':
        sources[1] = deepcopy(sources[0]); sources[1]['id'] = 'q1'; rows[1] = prediction(sources[1])
    with pytest.raises(ValueError): metric.score(sources, rows, labels)


def test_same_source_two_occurrences_require_query_sensitivity_for_two_correct_types():
    text = 'Registry shall file within 14 days if the application arrived within 14 days.'
    sources = [query(0, text), query(1, text, text.rindex('within 14 days'))]
    labels = {'q0': 'norm', 'q1': 'condition'}
    pooled = [prediction(s) for s in sources]
    result = metric.occurrence_diagnostics(sources, pooled, labels, require_query_invariance=True)
    assert result['repeated_source_groups'] == 1 and result['all_types_correct_groups'] == 0
    assert result['distinct_predicted_type_groups'] == 0
    occurrence = [prediction(s, labels[s['id']]) for s in sources]
    result = metric.occurrence_diagnostics(sources, occurrence, labels)
    assert result['all_types_correct_groups'] == result['distinct_predicted_type_groups'] == 1
    with pytest.raises(ValueError, match='query-agnostic'):
        metric.occurrence_diagnostics(sources, occurrence, labels, require_query_invariance=True)


def test_high_logit_magnitude_has_stable_nll_without_probability_log_zero():
    source = query(); row = prediction(source)
    row['logits'] = [1000., 0., 0., 0.]; row['probabilities'] = [1., 0., 0., 0.]; row['confidence'] = 1.
    result = metric.score([source], [row], {source['id']: 'condition'})
    assert result['mean_nll'] == 1000 and result['multiclass_brier_sum'] == 2


def test_inputs_and_prediction_order_are_not_semantic_features():
    sources = [query(0), query(1)]; rows = [prediction(s) for s in sources]
    labels = {'q0': 'norm', 'q1': 'condition'}; before = deepcopy((sources, rows, labels))
    assert metric.score(sources, rows, labels) == metric.score(sources, list(reversed(rows)), labels)
    assert (sources, rows, labels) == before


@pytest.mark.parametrize('field', sorted(metric.FALSE_FIELDS))
def test_owner_type_prediction_cannot_claim_authority_or_gate_changes(field):
    source = query(); row = prediction(source); row[field] = True
    with pytest.raises(ValueError, match='authority'):
        metric.checked_prediction(source, row)
