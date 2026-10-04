"""Consumer boundary and policy tests on fictional source-only examples.

Saved logits below are authored numerical fixtures, not trained-model outputs
or independently reviewed semantic labels. No challenge renderer is imported.
"""
from copy import deepcopy
import hashlib
import inspect
import math

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_event_owner_adapter_v4 as a
from tests.unit.logic.autoformal.test_legal_temporal_owner_pointer_metrics_v2 import prediction


def receipt(text='Registry shall file after receipt of notice.'):
    return a.proposer.propose(text)


@pytest.mark.parametrize('key,old_value', [
    ('schema', 'legal-temporal-event-proposals/v3'),
    ('profile', 'bounded-event-surface-offsets/v3'),
])
def test_old_receipt_version_cannot_claim_v4_boundary_validation(key, old_value):
    value = receipt()
    value[key] = old_value
    with pytest.raises(ValueError):
        a.plan_batch(value)


def policy(threshold=.95):
    return a.metrics._policy(threshold)


def saved(query, owner='norm', strength=12., chosen=None):
    tokens, time = a.metrics.source_tokens(query)
    if chosen is None:
        first = next((t for i, t in enumerate(tokens) if not time[0] <= i <= time[1]), None)
        chosen = None if first is None else {'char_start': first.start(), 'char_end': first.end()}
    row = prediction(query, owner=owner, chosen=chosen, span_strength=strength)
    n = len(tokens)
    row.update(pointer_start_factors=[[0.] * 8 for _ in tokens],
               pointer_end_factors=[[0.] * 8 for _ in tokens], interaction_scale=1/math.sqrt(8),
               interaction_enabled=True, base_pointer_start_logits=list(row['pointer_start_logits']),
               base_pointer_end_logits=list(row['pointer_end_logits']), relative_start_logits=[0.] * n,
               relative_end_logits=[0.] * n, relative_enabled=True)
    a.metrics.checked_prediction(query, row)
    return row


def assessed(value=None, selected_policy=None):
    value = receipt() if value is None else value
    queries = a.plan_batch(value)['queries']
    return a.assess_batch(value, [saved(q) for q in queries], policy() if selected_policy is None else selected_policy)


def assert_no_formal_payload(value):
    prohibited = {'canonical_ir', 'formula', 'native_ast', 'lean_body', 'qualified_projection', 'formal_payload'}
    if isinstance(value, dict):
        assert not prohibited.intersection(value)
        for key, item in value.items():
            if key == 'formula_admission':
                assert item is False
            assert_no_formal_payload(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_formal_payload(item)


@pytest.mark.parametrize('text,family', [
    ('Registry shall file after receipt of notice.', 'after_event'),
    ('Registry shall file not later than 21 days after publication of notice.', 'not_later_than_after'),
    ('Registry shall retain until the notice expires.', 'until_event'),
    ('Registry shall file within 9 days of notice.', 'legacy_lexical'),
])
def test_exact_source_only_queries_enter_unchanged_generic_validator(text, family):
    value = receipt(text); plan = a.plan_batch(value)
    assert len(plan['queries']) == 1 and not plan['excluded']
    assert plan['queries'] == a.proposer.source_queries(text, value)
    assert plan['eligibility'][0]['family'] == family
    assert set(plan['queries'][0]) == a.metrics.SOURCE_KEYS
    assert plan['queries'][0]['source_text'] == text
    assert plan['budgets']['required_model_batches'] == 1
    assert_no_formal_payload(plan)


def test_new_event_query_does_not_pass_legacy_regex_but_generic_validator_accepts():
    value = receipt(); query = a.plan_batch(value)['queries'][0]
    assert a.proposer.legacy.propose_time_spans(query['source_text']) == []
    assert a.metrics.types.validate_source(query) == query_token_span(query)


def query_token_span(query):
    return list(a.metrics.source_tokens(query)[1])


def test_confident_owner_acceptance_cannot_authorize_event_formula():
    result = assessed(); row = result['rows'][0]
    assert row['fixed_owner_accepted'] and row['calibrated_owner_accepted']
    assert result['counts']['formula_admitted'] == 0
    assert row['formula_gate']['status'] == 'deferred'
    assert 'event_origin_unresolved' in row['formula_gate']['reason_codes']
    assert 'event_relative_temporal_translation_unavailable' in row['formula_gate']['reason_codes']
    assert all(v is False for v in result['authority'].values())
    assert_no_formal_payload(result)


def test_event_complement_never_becomes_predicted_owner_anchor_or_truth():
    value = receipt(); result = assessed(value); row = result['rows'][0]
    assert row['event_span'] == value['proposals'][0]['event_span']
    assert row['raw_owner_anchor_span'] != row['event_span']
    assert row['gold_accuracy_available'] is False
    assert row['boundary_semantic_flags']['event_reference_unresolved'] is True


@pytest.mark.parametrize('text,reason', [
    ('Registry shall file within 9 days of notice.', 'notice_relative_duration_requires_explicit_translation'),
    ('Registry shall file before 2029-04-18.', 'calendar_literal_requires_caller_interpretation'),
    ('Registry shall file before April 18, 2029.', 'noncanonical_calendar_literal_requires_explicit_translation'),
])
def test_legacy_profile_still_needs_explicit_clock_and_scope(text, reason):
    result = assessed(receipt(text)); gate = result['rows'][0]['formula_gate']
    assert reason in gate['reason_codes']
    assert 'explicit_clock_and_scope_not_supplied' in gate['reason_codes']
    assert gate['formula_admission'] is False


@pytest.mark.parametrize('text', [
    'Registry shall file after receipt of notice Council shall publish.',
    'Registry shall file after receipt until approval of the Board.',
    'Registry shall file after a blue triangle.',
    'The phrase "within 9 days of notice" is quoted.',
])
def test_deferred_boundaries_are_excluded_from_decoder_even_when_complete_spans_exist(text):
    value = receipt(text); plan = a.plan_batch(value)
    assert plan['excluded']
    excluded = {p['query_id'] for p in plan['excluded']}
    assert not excluded.intersection(q['id'] for q in plan['queries'])
    assert all('temporal_boundary_deferred' in x['exclusion_reasons'] for x in plan['excluded'])
    result = a.assess_batch(value, [saved(q) for q in plan['queries']], policy())
    assert result['counts']['assessed_queries'] == len(plan['queries'])
    assert result['counts']['formula_admitted'] == 0


@pytest.mark.parametrize('text', ['Registry shall file after.', 'Registry shall wait until;', 'The word "after receipt" is quoted.'])
def test_missing_or_quoted_cues_remain_explicit_issues_without_model_rows(text):
    value = receipt(text); plan = a.plan_batch(value)
    assert plan['issues'] and not plan['queries']
    result = a.assess_batch(value, [], policy())
    assert result['counts']['assessed_queries'] == 0
    assert result['plan']['budgets']['required_model_batches'] == 0


def test_unresolved_anaphora_does_not_claim_resolved_owner_or_origin():
    result = assessed(receipt('Registry shall file after such notice.'))
    assert result['rows'][0]['boundary_semantic_flags']['event_anaphora_unresolved']
    assert result['rows'][0]['calibrated_owner_accepted']
    assert not result['formula_admission']


def test_invalid_calendar_issue_does_not_disappear_or_drop_other_eligible_query():
    value = receipt('Registry shall file before 2029-02-30; Council shall file after receipt of notice.')
    result = assessed(value)
    assert any('invalid_calendar_literal' in issue['reason_codes'] for issue in result['plan']['issues'])
    assert len(result['rows']) == 1 and result['rows'][0]['family'] == 'after_event'
    assert result['counts']['formula_admitted'] == 0


def test_oversized_full_source_is_preserved_and_excluded_without_truncation():
    text = ' '.join(['preamble'] * 257) + ' Registry shall file after receipt of notice.'
    value = receipt(text); plan = a.plan_batch(value)
    assert plan['source_text'] == text and not plan['queries']
    assert plan['issues'] and plan['budgets']['source_tokens'] > 256
    assert plan['budgets']['source_truncated'] is False
    assert plan['budgets']['model_source_budget_met'] is False
    assert all('source_token_budget_exceeded' in x['exclusion_reasons'] for x in plan['excluded'])


def test_long_single_token_is_excluded_even_when_total_token_count_is_small():
    text = 'x' * 2049 + ' shall file after receipt of notice.'
    plan = a.plan_batch(receipt(text))
    assert not plan['queries']
    assert plan['excluded'][0]['exclusion_reasons'] == ['source_token_byte_budget_exceeded']


def test_repeated_equal_literals_keep_distinct_offsets_and_complete_id_joins():
    value = receipt('Registry shall file after receipt of notice; Council shall publish after receipt of notice.')
    queries = a.plan_batch(value)['queries']; assert len(queries) == 2
    assert queries[0]['id'] != queries[1]['id']
    rows = [saved(q) for q in queries]
    result = a.assess_batch(value, rows[::-1], policy())
    assert [r['query_id'] for r in result['rows']] == [q['id'] for q in queries]


def test_more_than_one_model_batch_preserves_all_source_queries():
    text = 'after notice; ' * 80
    plan = a.plan_batch(receipt(text))
    assert len(plan['queries']) == 80 and plan['budgets']['source_tokens'] == 240
    assert plan['budgets']['maximum_batch_queries'] == 64
    assert plan['budgets']['required_model_batches'] == 2
    assert all(q['source_text'] == text for q in plan['queries'])


def test_none_predictions_is_explicit_not_executed_and_does_not_invent_rejections():
    result = a.assess_batch(receipt())
    assert result['status'] == 'not_executed' and result['counts']['eligible_queries'] == 1
    assert result['counts']['assessed_queries'] == 0 and result['rows'] == []
    assert result['predictions_sha256'] is None
    assert result['model_forwards_executed_by_adapter'] == 0


def test_frozen_accept_none_and_ambiguity_remain_deferred():
    value = receipt(); query = a.plan_batch(value)['queries'][0]
    none = a.assess_batch(value, [saved(query)], policy(None))
    assert none['rows'][0]['fixed_owner_accepted'] and not none['rows'][0]['calibrated_owner_accepted']
    ambiguous = a.assess_batch(value, [saved(query, owner='ambiguous')], policy())
    assert not ambiguous['rows'][0]['fixed_owner_accepted'] and not ambiguous['rows'][0]['calibrated_owner_accepted']


def test_calibration_is_applied_to_diagnostics_without_mutating_saved_predictions():
    value = receipt(); query = a.plan_batch(value)['queries'][0]
    row = saved(query, strength=1.5); before = deepcopy(row)
    # The calibrated .99 policy is at least as strict as fixed .8.
    result = a.assess_batch(value, [row], policy(.99))
    assert row == before
    assert not result['rows'][0]['calibrated_owner_accepted']


@pytest.mark.parametrize('mutation', [
    lambda r:r.update(gold_owner='norm'),
    lambda r:r['authority'].update(formal_formula_admitted=True),
    lambda r:r['proposals'][0].update(status='admitted'),
    lambda r:r['proposals'][0].update(canonical_ir={'rules': []}),
    lambda r:r['proposals'][0]['semantic_flags'].update(event_reference_unresolved=False),
    lambda r:r['proposals'][0]['event_span'].update(char_start=0),
    lambda r:r['proposals'][0]['query'].update(owner_candidates=[]),
    lambda r:r['proposals'][0]['query']['proposed_time_span'].update(char_end=1),
])
def test_proposal_or_scope_payload_tampering_fails_regeneration(mutation):
    value = receipt(); mutation(value)
    with pytest.raises(ValueError): a.plan_batch(value)


def test_source_repairing_only_hash_does_not_rebind_old_spans():
    value = receipt(); value['source_text'] = 'PREFIX ' + value['source_text']
    value['source_sha256'] = hashlib.sha256(value['source_text'].encode()).hexdigest()
    value['proposals'][0]['query'].update(source_text=value['source_text'], source_sha256=value['source_sha256'])
    with pytest.raises(ValueError): a.plan_batch(value)


@pytest.mark.parametrize('mutation', [
    lambda rows: rows.clear(),
    lambda rows: rows.append(deepcopy(rows[0])),
    lambda rows: rows[0].update(id='other-occurrence'),
    lambda rows: rows[0].update(source_sha256='0' * 64),
    lambda rows: rows[0]['proposed_time_span'].update(char_start=0),
    lambda rows: rows[0].update(scope_resolved=True),
    lambda rows: rows[0].update(formula='O(file)'),
    lambda rows: rows[0].update(confidence=1.),
    lambda rows: rows[0].update(span_confidence=.99),
    lambda rows: rows[0]['relative_start_logits'].__setitem__(0,1.),
    lambda rows: rows[0].update(owner_occurrence_resolved=True),
])
def test_missing_duplicate_changed_or_forged_positive_predictions_fail_closed(mutation):
    value = receipt(); rows = [saved(q) for q in a.plan_batch(value)['queries']]; mutation(rows)
    with pytest.raises(ValueError): a.assess_batch(value, rows, policy())


@pytest.mark.parametrize('mutation', [
    lambda p:p.update(safety_guarantee=True),
    lambda p:p.update(span_threshold=.1),
    lambda p:p.update(formula_admission=True),
    lambda p:p.update(type_threshold=0.),
])
def test_policy_cannot_expand_frozen_confidence_or_authority_contract(mutation):
    p = policy(); mutation(p)
    with pytest.raises(ValueError): assessed(selected_policy=p)


def test_supplied_predictions_require_policy_and_cannot_include_deferred_query():
    value = receipt('Registry shall file after a blue triangle.')
    assert not a.plan_batch(value)['queries']
    with pytest.raises(ValueError):a.assess_batch(value, [saved(value['proposals'][0]['query'])], policy())
    value = receipt(); rows = [saved(q) for q in a.plan_batch(value)['queries']]
    with pytest.raises(ValueError):a.assess_batch(value, rows)


def test_module_has_no_neural_or_formal_emitter_import_and_does_not_claim_authentication():
    code = inspect.getsource(a)
    assert 'import torch' not in code and 'optimizers' not in code and 'legal_family_routes' not in code
    result = assessed()
    assert not result['authority']['model_execution_verified']
    assert not result['authority']['model_policy_provenance_authenticated']
    assert result['model_forwards_executed_by_adapter'] == 0


@pytest.mark.parametrize('expression,family', [
    ('no later than 3 days after receipt of notice', 'not_later_than_after'),
    ('within 4 weeks after publication of notice', 'within_event'),
    ('within 2 months of issuance of notice', 'within_event'),
    ('at least 6 hours after receipt of notice', 'minimum_after_event'),
    ('no later than 1 year after approval of notice', 'not_later_than_after'),
])
def test_complete_compound_envelope_stays_diagnostic_even_with_confident_owner(expression, family):
    text = 'Registry shall file ' + expression + '.'
    value = receipt(text)
    plan = a.plan_batch(value)
    assert len(plan['queries']) == 1 and not plan['excluded']
    query = plan['queries'][0]
    coords = query['proposed_time_span']
    assert text[coords['char_start']:coords['char_end']] == expression
    result = assessed(value)
    row = result['rows'][0]
    assert row['family'] == family
    assert row['fixed_owner_accepted'] and row['calibrated_owner_accepted']
    assert row['formula_gate']['representation_profile_hint'] == 'event_relative_temporal_translation_unavailable'
    assert row['formula_gate']['status'] == 'deferred'
    assert 'event_origin_unresolved' in row['formula_gate']['reason_codes']
    assert row['boundary_semantic_flags']['event_reference_unresolved'] is True
    assert row['boundary_semantic_flags']['temporal_direction_unresolved'] is True
    if family == 'minimum_after_event':
        assert row['boundary_semantic_flags']['minimum_duration_scope_unresolved'] is True
    assert all(v is False for v in result['authority'].values())
    assert result['counts']['formula_admitted'] == 0
    assert_no_formal_payload(result)


def test_unknown_family_cannot_enter_formula_gate():
    value = receipt()['proposals'][0]
    value['family'] = 'bare_duration'
    with pytest.raises(ValueError, match='unknown surface proposal family'):
        a._formula_gate(value)


def test_minimum_family_cannot_claim_resolved_minimum_duration():
    value = receipt('Registry shall file at least 6 hours after receipt of notice.')
    proposal = value['proposals'][0]
    assert proposal['family'] == 'minimum_after_event'
    proposal['semantic_flags']['minimum_duration_scope_unresolved'] = False
    with pytest.raises(ValueError):
        a.plan_batch(value)
    with pytest.raises(ValueError, match='minimum duration meaning'):
        a._formula_gate(proposal)
