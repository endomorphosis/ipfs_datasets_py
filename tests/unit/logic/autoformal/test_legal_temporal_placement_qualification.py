"""Prospective gates cannot conceal class loss, unsafe swaps, or all deferral."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import math

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_placement_qualification as q


@lru_cache(None)
def fixtures(count=8):
    sources, labels = [], {}
    for index in range(count):
        text = f'Registry {index} shall file within 7 days of notice.'
        source = {'id': f'query-{index:04d}', 'source_text': text,
                  'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                  'proposed_time_span': {'char_start': text.index('within'), 'char_end': text.index('.')}}
        sources.append(source); labels[source['id']] = q.CLASSES[index % 4]
    return sources, labels


def predictions(count=8, changes=None, strength=5.):
    sources, labels = fixtures(count); rows = []
    for source in sources:
        label, scale = (changes or {}).get(source['id'], (labels[source['id']], strength))
        logits = [0.] * 4; logits[q.CLASSES.index(label)] = scale
        probabilities = q.metric.softmax(logits); confidence = probabilities[q.CLASSES.index(label)]
        accepted = label != 'ambiguous' and confidence >= .8
        rows.append({'id': source['id'], 'source_sha256': source['source_sha256'],
                     'proposed_time_span': deepcopy(source['proposed_time_span']),
                     'time_token_span': q.metric.validate_source(source), 'logits': logits,
                     'probabilities': probabilities, 'predicted_label': label, 'confidence': confidence,
                     'status': 'accepted' if accepted else 'deferred', 'owner_type': label if accepted else None,
                     'reason': None if accepted else ('predicted_ambiguous' if label == 'ambiguous' else 'below_fixed_confidence'),
                     **{key: False for key in q.metric.FALSE_FIELDS}})
    return rows


def scored(count=8, changes=None, strength=5.):
    sources, labels = fixtures(count)
    return q.panel_metrics(sources, predictions(count, changes, strength), labels)


def gates(count=8, changes=None, strength=5.):
    return scored(count, changes, strength)['gate_counts']


@lru_cache(None)
def base_selection():
    panels = {name: gates(count) for name, count in q.PANEL_COUNTS.items()}
    return {step: deepcopy(panels) for step in q.STEPS}


def selection():
    return deepcopy(base_selection())


def test_source_join_and_gate_counts_keep_the_full_denominator():
    result = scored(changes={'query-0000': ('exception', 5.), 'query-0003': ('norm', 1.)})
    value = result['gate_counts']
    assert value['count'] == 8 and value['correct'] == 6
    assert value['per_class']['norm']['accepted_error_ids'] == ['query-0000']
    assert value['per_class']['ambiguous']['accepted_errors'] == 0
    assert value['per_class']['ambiguous']['accepted_correct'] == 0
    assert value['source_semantics_verified'] is False


def test_equal_total_accuracy_cannot_hide_per_class_loss():
    before = gates(changes={'query-0001': ('exception', 1.)})
    after = gates(changes={'query-0000': ('exception', 1.)})
    assert before['correct'] == after['correct']
    report = q.retention_panel(after, before)
    assert not report['eligible'] and 'norm:correct_below_parent' in report['failures']


def test_equal_accepted_error_count_cannot_swap_the_wrong_query():
    before = gates(changes={'query-0000': ('exception', 5.)})
    after = gates(changes={'query-0004': ('exception', 5.)})
    assert before['per_class']['norm']['accepted_errors'] == after['per_class']['norm']['accepted_errors'] == 1
    assert q.retention_panel(after, before)['failures'] == ['norm:new_accepted_error_ids']


def test_more_accepted_errors_in_same_target_class_fail_explicit_ceiling():
    before = gates(changes={'query-0000': ('exception', 5.), 'query-0004': ('exception', 1.)})
    after = gates(changes={'query-0000': ('exception', 5.), 'query-0004': ('exception', 5.)})
    result = q.retention_panel(after, before)
    assert 'norm:accepted_errors_above_parent' in result['failures']
    assert 'norm:new_accepted_error_ids' in result['failures']


def test_all_defer_cannot_pass_old_panel_coverage_floor():
    before, after = gates(), gates(strength=1.)
    assert after['correct'] == before['correct'] == 8 and after['accepted_type_proposals'] == 0
    report = q.retention_panel(after, before)
    assert report['failures'] == [c + ':accepted_correct_below_parent' for c in ('norm', 'condition', 'exception')]


def test_coverage_floor_is_per_class_not_only_total():
    before = gates(changes={'query-0001': ('condition', 1.)})
    after = gates(changes={'query-0000': ('norm', 1.)})
    assert before['accepted_type_proposals'] == after['accepted_type_proposals']
    assert q.retention_panel(after, before)['failures'] == ['norm:accepted_correct_below_parent']


def test_new_tuning_retains_class_accuracy_but_has_no_coverage_gate():
    result = q.retention_panel(gates(strength=1.), gates(), full_retention=False)
    assert result['eligible'] and result['accepted_correct_coverage_gate_applied'] is False


def test_low_confidence_within_class_churn_reported_without_claiming_zero_churn():
    before = gates(changes={'query-0000': ('exception', 1.), 'query-0004': ('norm', 1.)})
    after = gates(changes={'query-0000': ('norm', 1.), 'query-0004': ('exception', 1.)})
    result = q.retention_panel(after, before)
    assert result['eligible'] and result['zero_correctness_churn_required'] is False
    assert result['class_churn']['norm']['fixed_ids'] == ['query-0000']
    assert result['class_churn']['norm']['lost_ids'] == ['query-0004']


def test_parent_candidate_is_explicit_fallback_and_wins_exact_tie():
    result = q.select_candidate(selection())
    assert result['selected_steps'] == 0 and result['eligible_steps'] == list(q.STEPS)
    assert result['accepted_correct_coverage_gate_applied'] is True
    assert result['current_fresh_results_used'] is False and result['pipeline_promotion'] is False


def test_nll_then_earlier_update_breaks_equal_macro_f1_ties():
    values = selection()
    for step in (100, 200): values[step][q.NEW_TUNING] = gates(288, strength=6.)
    assert q.select_candidate(values)['selected_steps'] == 100


def test_macro_f1_precedes_nll_and_historical_gates_precede_both():
    values = selection()
    for step in q.STEPS:
        values[step][q.NEW_TUNING] = gates(288, changes={'query-0001': ('exception', 5.)})
    values[50][q.NEW_TUNING] = gates(288, strength=1.)  # Better F1 but worse NLL.
    values[100][q.NEW_TUNING] = gates(288, strength=8.)
    values[100]['old_multi_fresh'] = gates(96, changes={'query-0000': ('exception', 5.)})
    result = q.select_candidate(values)
    assert result['selected_steps'] == 50 and 100 not in result['eligible_steps']


@pytest.mark.parametrize('panel', q.RETENTION_PANELS)
def test_every_historical_panel_is_gated(panel):
    values = selection(); values[50][q.NEW_TUNING] = gates(288, strength=6.)
    values[50][panel] = gates(q.PANEL_COUNTS[panel], changes={'query-0000': ('exception', 5.)})
    assert 50 not in q.select_candidate(values)['eligible_steps']


def test_new_tuning_per_class_floor_blocks_a_tradeoff():
    values = selection()
    for step in q.STEPS:
        values[step][q.NEW_TUNING] = gates(288, changes={'query-0001': ('exception', 1.)})
    values[50][q.NEW_TUNING] = gates(288, changes={'query-0000': ('exception', 1.)})
    assert 50 not in q.select_candidate(values)['eligible_steps']


@pytest.mark.parametrize('mutation', [
    lambda v: v.pop(0), lambda v: v.pop(200), lambda v: v.update({True: v[0]}),
    lambda v: v[50].pop('old_multi_fresh'),
    lambda v: v[50].update(fresh_lexical=v[50][q.NEW_TUNING]),
])
def test_unplanned_stage_or_panel_inventory_fails_closed(mutation):
    values = selection(); mutation(values)
    with pytest.raises(ValueError): q.select_candidate(values)


@pytest.mark.parametrize('mutation', [
    lambda v: v.update(count=True), lambda v: v.update(threshold=.7),
    lambda v: v.update(current_fresh_results_used=True), lambda v: v.update(owner_occurrence_resolved=True),
    lambda v: v.update(extra_field='ignore'), lambda v: v.update(macro_f1=float('nan')),
    lambda v: v.update(mean_nll=-.1), lambda v: v.update(macro_f1=.5),
    lambda v: v['per_class']['norm'].update(correct=True),
    lambda v: v['per_class']['norm']['query_ids'].reverse(),
    lambda v: v['per_class']['norm']['accepted_correct_ids'].append('query-0001'),
    lambda v: v['per_class']['norm']['accepted_error_ids'].append('query-0000'),
    lambda v: v['confusion_target_rows_prediction_columns'][0].__setitem__(0, True),
])
def test_corrupted_gate_or_authority_claim_rejected(mutation):
    value = gates(); mutation(value)
    with pytest.raises(ValueError): q.validate_gate_counts(value)


def test_changed_source_target_binding_rejected_even_with_same_counts():
    before, after = gates(), gates(); after['source_targets_sha256'] = 'a' * 64
    with pytest.raises(ValueError, match='identical full source'): q.retention_panel(after, before)


@pytest.mark.parametrize('mutation', [
    lambda s: s.update(correct=0), lambda s: s.update(accepted_type_errors=1),
    lambda s: s['rows'][0].update(correct=False), lambda s: s['rows'][0].update(accepted_type_error=True),
    lambda s: s['rows'][0].update(accepted_type_proposal=1),
    lambda s: s['rows'][0].update(id=s['rows'][1]['id']),
    lambda s: s['rows'][0].update(proposed_time_span={'char_start':False,'char_end':5}),
    lambda s: s.update(macro_f1=.5), lambda s: s.update(source_semantics_verified=True),
])
def test_compact_summary_must_reconcile_saved_scored_rows(mutation):
    value = scored()['metrics']; mutation(value)
    with pytest.raises(ValueError): q.gate_counts(value)


def test_source_only_replay_validates_exact_rows_without_reference_labels():
    sources, _ = fixtures(); rows = predictions()
    report = q.verify_replayed_rows(sources, rows, deepcopy(rows))
    assert report['query_rows'] == 8 and report['exact_saved_rows_replayed'] is True
    assert report['labels_supplied'] is False and report['owner_or_cue_spans_supplied'] is False


def test_replay_rejects_another_valid_logit_vector_even_when_decision_is_same():
    sources, _ = fixtures()
    with pytest.raises(ValueError, match='numerical replay differs'):
        q.verify_replayed_rows(sources, predictions(), predictions(strength=6.))


@pytest.mark.parametrize('kind', ['reference_in_query', 'owner_authority', 'changed_offset', 'missing_row', 'reorder'])
def test_replay_rejects_label_leak_metadata_or_incomplete_inventory(kind):
    sources, _ = fixtures(); sources = deepcopy(sources); rows = predictions()
    if kind == 'reference_in_query': sources[0]['label'] = 'norm'
    if kind == 'owner_authority': rows[0]['owner_occurrence_resolved'] = True
    if kind == 'changed_offset': rows[0]['proposed_time_span']['char_start'] += 1
    if kind == 'missing_row': rows.pop()
    if kind == 'reorder': rows.reverse()
    with pytest.raises(ValueError): q.source_only_predictions(sources, rows)


def test_score_reference_join_requires_all_occurrences_not_only_accepted_subset():
    sources, labels = fixtures(); rows = predictions()
    with pytest.raises(ValueError): q.panel_metrics(sources, rows[:-1], labels)
    changed = deepcopy(rows); changed[0]['source_sha256'] = 'a' * 64
    with pytest.raises(ValueError): q.panel_metrics(sources, changed, labels)
