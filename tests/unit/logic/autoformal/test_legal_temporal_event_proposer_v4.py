"""Development and synthetic fixtures only; no held-out reference files read."""
import copy
import hashlib
import json
import re

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as p
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_corpus as old


WAIVER = ('(2) Not later than 10 days after the Secretary provides a waiver under paragraph (1), '
          'the Secretary shall submit to the Committee on Armed Services of the Senate and the '
          'Committee on Armed Services of the House of Representatives a written notice setting '
          'forth the reasoning for the waiver, together with a copy of the waiver itself.')
COMMENT = ('(2) The Secretary may issue rules specifying end items, goods, and products for which '
           'a printed circuit board that is a component thereof shall be a specified type if the '
           'Secretary has promulgated final regulations, after an opportunity for notice and '
           'comment that is not less than 12 months, implementing this section.')
APPLICABILITY = ('(e) Applicability.—This section shall apply only with respect to contracts '
                 'entered into after the issuance of a final rule implementing this section.')
DISCHARGE = ('The concealment of assets of a debtor in a case under title 11 shall be deemed to '
             'be a continuing offense until the debtor shall have been finally discharged or '
             'a discharge denied, and the period of limitations shall not begin to run until '
             'such final discharge or denial of discharge.')


def interval(text, literal, start=0):
    a = text.index(literal, start)
    return {'char_start': a, 'char_end': a+len(literal)}


def literal(text, span):
    return text[span['char_start']:span['char_end']]


@pytest.mark.parametrize('text,a,b,flag', [
    (WAIVER, 4, 84, None),
    (COMMENT, 216, 291, 'minimum_duration_scope_unresolved'),
    (APPLICABILITY, 88, 148, None),
    (DISCHARGE, 106, 179, None),
    (DISCHARGE, 234, 283, 'event_anaphora_unresolved'),
])
def test_manually_queried_historical_development_spans(text, a, b, flag):
    # Exact interval fidelity is the assertion, never a legal-owner reference.
    result = p.propose(text)
    matched = [q for q in result['proposals'] if q['query']['proposed_time_span'] ==
               {'char_start': a, 'char_end': b}]
    assert len(matched) == 1 and matched[0]['status'] == 'surface_candidate'
    assert matched[0]['semantic_flags']['event_reference_unresolved']
    assert matched[0]['semantic_flags']['temporal_direction_unresolved']
    if flag:
        assert matched[0]['semantic_flags'][flag]
    assert result['authority'] == {'legal_semantics_verified': False, 'owner_assigned': False,
                                   'formal_formula_admitted': False}


@pytest.mark.parametrize('text', [
    'Board shall file within 12 days of notice.',
    'Before filing, Board shall file before 2040-02-29.',
    'Board shall file before March 14, 2099 and within 2 hours of notice.',
    'Notice says "before 2040-01-01"; Board shall file before 2041-01-01.',
])
def test_legacy_intervals_and_ids_preserved_exactly(text):
    actual = [r for r in p.propose(text)['proposals'] if r['family'] == 'legacy_lexical']
    assert [r['query']['proposed_time_span'] for r in actual] == old.propose_time_spans(text)
    assert [r['query'] for r in actual] == [old.query(text, s) for s in old.propose_time_spans(text)]
    for row in actual:
        assert literal(text, row['cue_span']) in ('within', 'before')


def test_quoted_legacy_inventory_retained_but_not_submitted():
    text = 'The phrase "before 2040-01-01" is quoted.'
    result = p.propose(text)
    assert result['proposals'][0]['reason_codes'] == ['quoted_time_mention']
    assert p.source_queries(text, result) == []


@pytest.mark.parametrize('quotes', [('"','"'), ('“','”'), ("'", "'")])
def test_new_quoted_cues_are_issues_not_queries(quotes):
    text = f'Caption {quotes[0]}until approval{quotes[1]}; Board shall file after receipt.'
    result = p.propose(text)
    assert result['issues'] == [{'cue_span': interval(text, 'until'), 'reason_codes': ['quoted_cue_mention']}]
    assert len(result['proposals']) == 1
    assert literal(text, result['proposals'][0]['event_span']) == 'receipt'


def test_unicode_offsets_case_and_compound_cue_no_duplicate_after():
    text = '§9.—Élan shall file NOT  LATER THAN 7 DAYS AFTER the receipt of a permit.'
    result = p.propose(text)
    assert len(result['proposals']) == 1
    row = result['proposals'][0]
    assert literal(text, row['cue_span']) == 'NOT  LATER THAN'
    assert literal(text, row['event_span']) == 'the receipt of a permit'
    assert row['status'] == 'surface_candidate'
    assert row['query'] == old.query(text, interval(text, 'NOT  LATER THAN 7 DAYS AFTER the receipt of a permit'))


def test_repeated_identical_events_are_distinct_occurrences():
    text = 'Board shall file after receipt; Registry shall publish after receipt.'
    rows = p.propose(text)['proposals']
    assert len(rows) == 2 and len({r['query']['id'] for r in rows}) == 2
    assert [literal(text, r['query']['proposed_time_span']) for r in rows] == ['after receipt']*2
    assert p.propose(text) == p.propose(text)


@pytest.mark.parametrize('event', [
    'the receipt of notice under paragraph (1)',
    'the receipt of notice under 1.25 U.S.C. 23',
    'the receipt of notice from Dr. Hart',
    'the receipt of "Approval; effective." notice',
    "the Secretary's receipt of notice",
    "the agencies' receipt of notice",
    'the agencies’ receipt of notice',
])
def test_citations_abbreviations_decimal_and_quotes_do_not_cut_event(event):
    text = 'Board shall file after '+event+'. Registry shall archive.'
    rows = p.propose(text)['proposals']
    assert len(rows) == 1
    assert literal(text, rows[0]['event_span']) == event
    assert rows[0]['status'] == 'surface_candidate'


@pytest.mark.parametrize('event', [
    'the debtor shall have been finally discharged or a discharge denied',
    'the application shall be approved',
])
def test_declared_subordinate_modal_retained(event):
    text = 'Board shall wait until '+event+', and Registry shall archive.'
    row = p.propose(text)['proposals'][0]
    assert literal(text, row['event_span']) == event
    assert row['status'] == 'surface_candidate'


@pytest.mark.parametrize('text', [
    'After receipt the Board shall file.',
    'Board shall wait until approval and Registry must archive.',
])
def test_unpunctuated_main_modal_boundary_deferred(text):
    result = p.propose(text)
    assert result['proposals'][0]['status'] == 'deferred'
    assert 'ambiguous_unpunctuated_clause_boundary' in result['proposals'][0]['reason_codes']
    assert p.source_queries(text, result) == []


def test_nested_cues_recorded_without_assigning_scope():
    text = 'Board shall file after receipt until completion.'
    result = p.propose(text)
    assert [r['status'] for r in result['proposals']] == ['deferred', 'surface_candidate']
    assert result['proposals'][0]['semantic_flags']['nested_temporal_scope_unresolved']
    assert 'ambiguous_nested_temporal_boundary' in result['proposals'][0]['reason_codes']
    assert len(p.source_queries(text, result)) == 1


@pytest.mark.parametrize('text', ['Board shall wait until.', 'After   , Board shall file.'])
def test_missing_event_is_issue_without_invented_span(text):
    result = p.propose(text)
    assert result['proposals'] == []
    assert result['issues'][0]['reason_codes'] == ['missing_event_complement']


@pytest.mark.parametrize('text', ['Board shall wait until lower caption.',
                                 'Board shall file after blue.',
                                 'After lunch, Board shall file.'])
def test_outside_declared_event_vocabulary_deferred(text):
    result = p.propose(text)
    assert result['proposals'][0]['status'] == 'deferred'
    assert 'unsupported_event_shape' in result['proposals'][0]['reason_codes']


@pytest.mark.parametrize('text,reason', [
    ('Board shall file after receipt under paragraph (1.', 'unbalanced_delimiters'),
    ('Board shall file after receipt of "the notice.', 'unterminated_quotation'),
])
def test_unbalanced_source_boundaries_deferred(text, reason):
    result = p.propose(text)
    assert result['proposals'][0]['status'] == 'deferred'
    assert reason in result['proposals'][0]['reason_codes']


def test_minimum_duration_and_anaphora_are_not_owner_or_operator_labels():
    result = p.propose(COMMENT)
    flags = result['proposals'][0]['semantic_flags']
    assert flags['minimum_duration_scope_unresolved'] and not flags['event_anaphora_unresolved']
    assert result['proposals'][0]['status'] == 'surface_candidate'
    assert not any(result['authority'].values())
    assert set(flags) == set(p.SEMANTIC_KEYS)


def test_every_emitted_query_is_closed_and_token_aligned():
    from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metrics
    for text in (WAIVER, COMMENT, APPLICABILITY, DISCHARGE):
        result = p.propose(text)
        for query in p.source_queries(text, result):
            assert set(query) == {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
            metrics.validate_source(query)  # Pure source validation; no model.


def test_budget_keeps_legacy_intervals_but_never_truncates_into_model():
    text = ('word '*255)+'before 2040-01-01; after receipt.'
    result = p.propose(text)
    assert len(result['proposals']) == 2
    assert all(r['status'] == 'deferred' for r in result['proposals'])
    assert result['proposals'][0]['query']['proposed_time_span'] == old.propose_time_spans(text)[0]
    assert result['issues'][0] == {'cue_span': None, 'reason_codes': ['source_token_budget_exceeded']}
    assert p.source_queries(text, result) == []


@pytest.mark.parametrize('value', ['', 'a'*4097, 42, True, {'source_text': 'after receipt'}])
def test_invalid_source_rejected_without_coercion(value):
    with pytest.raises(ValueError): p.propose(value)


def test_invalid_calendar_date_does_not_erase_valid_legacy_or_event_candidates():
    text = 'Board shall file before 2041-02-29; after receipt; before 2040-02-29.'
    result = p.propose(text)
    assert result['issues'] == [{'cue_span': interval(text, 'before'),
                                'reason_codes': ['invalid_calendar_literal']}]
    assert [literal(text, r['query']['proposed_time_span']) for r in result['proposals']] == [
        'after receipt', 'before 2040-02-29']


@pytest.mark.parametrize('mutation', ['id', 'offset', 'float_offset', 'status', 'semantic', 'authority',
                                      'producer', 'extra', 'source', 'event_span', 'family', 'issues'])
def test_authoritative_regeneration_rejects_repaired_receipt(mutation):
    text = 'Board shall file after receipt.'
    result = copy.deepcopy(p.propose(text)); row = result['proposals'][0]
    if mutation == 'id': row['query']['id'] = 'occ-'+'a'*64
    elif mutation == 'offset':
        row['query'] = old.query(text, interval(text, 'receipt'))
    elif mutation == 'float_offset':
        row['query']['proposed_time_span']['char_start'] = float(row['query']['proposed_time_span']['char_start'])
    elif mutation == 'status': row['status'] = 'deferred'
    elif mutation == 'semantic': row['semantic_flags']['event_reference_unresolved'] = False
    elif mutation == 'authority': result['authority']['formal_formula_admitted'] = True
    elif mutation == 'producer': result['producer_pins'][next(iter(result['producer_pins']))] = 'b'*64
    elif mutation == 'extra': row['owner_type'] = 'norm'
    elif mutation == 'source':
        result['source_text'] = text+' '
        result['source_sha256'] = hashlib.sha256(result['source_text'].encode()).hexdigest()
    elif mutation == 'event_span': row['event_span']['char_start'] += 1
    elif mutation == 'family': row['family'] = 'until_event'
    elif mutation == 'issues': result['issues'].append({'cue_span': None, 'reason_codes': []})
    with pytest.raises(ValueError, match='regeneration'): p.validate_result(text, result)


def test_projection_returns_independent_source_span_copy():
    text = 'Board shall file after receipt.'
    result = p.propose(text)
    queries = p.source_queries(text, result)
    queries[0]['proposed_time_span']['char_end'] = 0
    assert p.validate_result(text, result) is result


def test_closed_output_enums_and_no_authority_escalation():
    for text in (WAIVER, COMMENT, APPLICABILITY, DISCHARGE, 'Caption "until receipt"; after blue.'):
        result = p.propose(text)
        assert set(result) == {'schema','profile','source_text','source_sha256','proposals','issues','producer_pins','authority'}
        for row in result['proposals']:
            assert set(row) == {'query','family','cue_span','event_span','status','reason_codes','semantic_flags'}
            assert row['family'] in p.FAMILIES and row['status'] in p.STATUSES
            assert set(row['reason_codes']) <= set(p.REASONS)
            assert all(type(x) is bool for x in row['semantic_flags'].values())
        for issue in result['issues']:
            assert set(issue) == {'cue_span','reason_codes'}
            assert set(issue['reason_codes']) <= set(p.REASONS)
        assert set(result['authority']) == set(p.AUTHORITY) and not any(result['authority'].values())


@pytest.mark.parametrize('event', [
    'the hearing concludes', 'the audit ends', 'the review closes',
    'the seal is removed', 'the filing (see section 6; paragraph (c)) is complete',
    'the register is marked “accepted, complete”', 'the Dept. certifies the record',
    'the measurement reaches 3.75', 'such certification',
    'the prisoner shall have been finally released',
    'the application is not approved', 'the permit has not been formally issued',
    'the office has received the application', 'the office has not received the application',
    'the hearing concluded under section 3', 'the notice was duly served',
    'the receipt of a notice implementing this section',
    'the certification by Dr. Q. Rao under 12 U.S.C. 34(a)',
    'the clerk signs the receipt', 'the clerk records “approved; complete”',
    'the receipt of the certified dossier',
])
def test_explicit_nominal_subject_predicate_and_auxiliary_shapes(event):
    text = 'Office shall archive after '+event+'. Registry shall reply.'
    result = p.propose(text)
    assert len(result['proposals']) == 1
    row = result['proposals'][0]
    assert row['status'] == 'surface_candidate', (event, row['reason_codes'])
    assert literal(text, row['event_span']) == event
    assert row['semantic_flags']['event_reference_unresolved']
    assert row['semantic_flags']['temporal_direction_unresolved']
    assert not any(result['authority'].values())


@pytest.mark.parametrize('event', [
    'approved', 'finally approved', 'not approved', 'formally released',
    'is approved', 'shall have been released', 'the application approved',
    'the hearing quickly', 'the caption mentions approval', 'approval blue',
    'the word “approved”', 'the heading (approval)', 'the receipt the clerk files',
    'the application is approved the clerk files',
    'the application is approved and the clerk files',
    'the application shall be approved and the Board shall be released',
    'the receipt of the notice and the clerk files',
    'the clerk receives', 'the seal is removed a report',
    'the application may be approved', 'not receipt',
    'the office has been', 'the receipt of', 'the receipt of blue and',
    'the implementing this section is approved',
    'Board receives the implementing this section',
    'approval of the Board certified', 'the clerk receives the dossier certified',
    'approval of the Board certified under section 7',
])
def test_incomplete_or_competing_shapes_do_not_become_event_candidates(event):
    text = 'Office shall wait until '+event+'.'
    result = p.propose(text)
    assert len(result['proposals']) == 1
    assert result['proposals'][0]['status'] == 'deferred', event
    assert 'unsupported_event_shape' in result['proposals'][0]['reason_codes']
    assert p.source_queries(text, result) == []


def test_punctuation_ends_valid_event_before_independent_finite_clause():
    text = 'Office waits until the application is approved; the clerk files.'
    row = p.propose(text)['proposals'][0]
    assert row['status'] == 'surface_candidate'
    assert literal(text, row['event_span']) == 'the application is approved'


def test_quoted_predicates_cannot_complete_an_unrecognized_nominal_fragment():
    text = 'Office waits until the caption “the hearing concludes”.'
    row = p.propose(text)['proposals'][0]
    assert row['status'] == 'deferred'
    assert p.source_queries(text, p.propose(text)) == []



def test_v4_wire_version_and_prior_modules_remain_distinct():
    from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v3 as previous
    text = 'Office acts within 6 weeks after receipt.'
    before, after = previous.propose(text), p.propose(text)
    assert literal(text, before['proposals'][0]['query']['proposed_time_span']) == 'after receipt'
    assert literal(text, after['proposals'][0]['query']['proposed_time_span']) == 'within 6 weeks after receipt'
    assert after['schema'] == 'legal-temporal-event-proposals/v4'
    assert after['profile'] == 'bounded-event-surface-offsets/v4'
    assert set(after) == set(before)
    assert set(p.REASONS) == set(previous.REASONS) | {'unsupported_temporal_prefix'}
    assert set(p.FAMILIES) == set(previous.FAMILIES) | {'within_event', 'minimum_after_event'}
    assert p.SEMANTIC_KEYS == previous.SEMANTIC_KEYS
    assert p.AUTHORITY == previous.AUTHORITY


@pytest.mark.parametrize('prefix,family,cue', [
    ('no later than 3 days after', 'not_later_than_after', 'no later than'),
    ('not later than 2 weeks after', 'not_later_than_after', 'not later than'),
    ('No LATER  THAN 1 hour after', 'not_later_than_after', 'No LATER  THAN'),
    ('within 9 weeks after', 'within_event', 'within'),
    ('WITHIN\t999 years\tafter', 'within_event', 'WITHIN'),
    ('within 2 months of', 'within_event', 'within'),
    ('within 1 day of', 'within_event', 'within'),
    ('at least 6 hours after', 'minimum_after_event', 'at least'),
    ('AT\tLEAST 1 week AFTER', 'minimum_after_event', 'AT\tLEAST'),
])
def test_complete_compound_prefix_is_the_only_eligible_envelope(prefix, family, cue):
    event = 'the receipt of a notice under section (4)'
    text = '§2.—Office acts '+prefix+' '+event+'; Registry archives.'
    result = p.propose(text)
    assert result['issues'] == []
    assert len(result['proposals']) == 1
    row = result['proposals'][0]
    assert row['family'] == family and row['status'] == 'surface_candidate'
    assert literal(text, row['cue_span']) == cue
    assert literal(text, row['event_span']) == event
    assert literal(text, row['query']['proposed_time_span']) == prefix+' '+event
    assert row['semantic_flags']['minimum_duration_scope_unresolved'] == (family == 'minimum_after_event')
    assert not row['semantic_flags']['nested_temporal_scope_unresolved']
    assert row['query'] == old.query(text, interval(text, prefix+' '+event))


@pytest.mark.parametrize('unit', ['hour','hours','day','days','week','weeks','month','months','year','years'])
def test_all_declared_units_accept_ascii_integer_bounds(unit):
    for number in (1, 999):
        text = f'Office acts no later than {number} {unit} after publication.'
        row, = p.propose(text)['proposals']
        assert row['status'] == 'surface_candidate'
        assert literal(text, row['query']['proposed_time_span']) == text[12:-1]


@pytest.mark.parametrize('prefix', [
    'within two days after', 'within 0 days after', 'within 1000 days after',
    'within 01 days after', 'within 2.5 days after', 'within 1/2 days after',
    'within -3 days after', 'within +3 days after', 'within ٣ days after',
    'within 3 fortnights after', 'within 2 business days after',
    'within several days after', 'within 5 days following',
    'within 5 days prior to', 'within 5 days since',
    'no later than five days after', 'not later than 0 weeks after',
    'not later than 4 decades after', 'at least 1001 months after',
    'at least 5 fortnights after', 'at least 2 days of',
    'no later than 3 days of', 'for 4 days after', 'for three hours after',
])
def test_unsupported_outer_prefix_never_promotes_suffix_after(prefix):
    text = 'Office acts '+prefix+' receipt.'
    result = p.propose(text)
    assert p.source_queries(text, result) == []
    assert result['proposals'] == []
    issue, = result['issues']
    assert issue['reason_codes'] == ['unsupported_temporal_prefix']
    expected_cue = ('not later than' if prefix.startswith('not later') else
                    'no later than' if prefix.startswith('no later') else
                    'at least' if prefix.startswith('at least') else prefix.split()[0])
    assert literal(text, issue['cue_span']) == expected_cue


@pytest.mark.parametrize('phrase', ['within 7 days', 'at least 5 weeks', 'for 2 months'])
def test_bare_duration_requires_outer_cue_abstention(phrase):
    text = 'Office acts '+phrase+'.'
    result = p.propose(text)
    assert not result['proposals']
    assert result['issues'][0]['reason_codes'] == ['unsupported_temporal_prefix']


def test_unsupported_outer_prefix_does_not_swallow_punctuated_independent_occurrence():
    text = 'Office acts within two days after receipt; Registry acts after approval.'
    result = p.propose(text)
    assert len(result['issues']) == 1
    row, = result['proposals']
    assert row['status'] == 'surface_candidate'
    assert literal(text, row['query']['proposed_time_span']) == 'after approval'


def test_unsupported_outer_prefix_suppresses_nested_alternative_suffixes():
    text = 'Office acts within two days after receipt until approval.'
    result = p.propose(text)
    assert not p.source_queries(text, result)
    assert len(result['issues']) == 1


@pytest.mark.parametrize('phrase,cue', [
    ('within 2 weeks after receipt', 'within'),
    ('at least 3 days after receipt', 'at least'),
    ('no later than 8 hours after approval', 'no later than'),
    ('within two days after receipt', 'within'),
])
def test_quoted_complete_or_unsupported_compound_is_one_issue(phrase, cue):
    text = 'Caption “'+phrase+'” and Office acts after approval.'
    result = p.propose(text)
    assert result['issues'] == [{'cue_span': interval(text, cue), 'reason_codes': ['quoted_cue_mention']}]
    row, = result['proposals']
    assert row['status'] == 'surface_candidate'
    assert literal(text, row['query']['proposed_time_span']) == 'after approval'


@pytest.mark.parametrize('phrase', ['within 3 days of notice', 'within 6 hours of notice'])
def test_complete_legacy_notice_overlap_remains_one_legacy_occurrence(phrase):
    text = 'Office acts '+phrase+'; Registry archives.'
    row, = p.propose(text)['proposals']
    assert row['family'] == 'legacy_lexical' and row['status'] == 'surface_candidate'
    assert row['query'] == old.query(text, interval(text, phrase))
    assert row['event_span'] is None and not any(row['semantic_flags'].values())


def test_quoted_legacy_notice_overlap_is_deferred_without_extra_issue_or_duplicate():
    text = 'Caption "within 3 days of notice".'
    result = p.propose(text)
    row, = result['proposals']
    assert result['issues'] == [] and row['family'] == 'legacy_lexical'
    assert row['reason_codes'] == ['quoted_time_mention']


@pytest.mark.parametrize('extension', ['of the hearing', 'that the board approves', 'which confirms receipt',
                                       'under section (7)', 'from the Registrar'])
def test_extended_legacy_notice_prefix_is_preserved_but_cannot_be_promoted(extension):
    text = 'Office acts within 6 days of notice '+extension+'.'
    result = p.propose(text)
    row, = result['proposals']
    assert row['query'] == old.query(text, old.propose_time_spans(text)[0])
    assert row['family'] == 'legacy_lexical' and row['status'] == 'deferred'
    assert row['reason_codes'] == ['unsupported_temporal_prefix']
    assert p.source_queries(text, result) == []


def test_compound_nested_cue_and_separate_occurrence_use_source_locations():
    text = ('Office acts within 8 days after receipt until approval; '
            'Registry acts at least 3 hours after such receipt.')
    rows = p.propose(text)['proposals']
    assert len(rows) == 3
    assert rows[0]['status'] == 'deferred'
    assert rows[0]['semantic_flags']['nested_temporal_scope_unresolved']
    assert rows[1]['status'] == rows[2]['status'] == 'surface_candidate'
    assert not rows[1]['semantic_flags']['nested_temporal_scope_unresolved']
    assert not rows[2]['semantic_flags']['nested_temporal_scope_unresolved']
    assert rows[2]['semantic_flags']['minimum_duration_scope_unresolved']
    assert rows[2]['semantic_flags']['event_anaphora_unresolved']


@pytest.mark.parametrize('event', ['the list will have been published', 'the permit will be issued',
                                  'that earlier approval'])
def test_exposed_explicit_modal_and_earlier_modifier_regressions(event):
    text = 'Office acts within 4 weeks after '+event+'.'
    row, = p.propose(text)['proposals']
    assert row['status'] == 'surface_candidate'
    assert literal(text, row['event_span']) == event


@pytest.mark.parametrize('event', ['will have been published', 'earlier approved',
                                  'finally approved', 'the permit will issue',
                                  'receipt the Board will be approved'])
def test_explicit_modal_repairs_do_not_admit_bare_or_competing_clauses(event):
    text = 'Office acts within 4 weeks after '+event+'.'
    row, = p.propose(text)['proposals']
    assert row['status'] == 'deferred'
    assert p.source_queries(text, p.propose(text)) == []


def test_quoted_label_inside_complete_event_keeps_outer_compound():
    text = 'Office acts within 3 weeks after the register is marked “after approval”.'
    result = p.propose(text)
    row, = result['proposals']
    assert row['status'] == 'surface_candidate'
    assert literal(text, row['query']['proposed_time_span']) == text[12:-1]
    assert not row['semantic_flags']['nested_temporal_scope_unresolved']
    assert result['issues'][0]['reason_codes'] == ['quoted_cue_mention']


def test_ordinary_for_preposition_is_not_an_unsupported_temporal_prefix():
    text = 'Office waits for review after receipt of notice.'
    result = p.propose(text)
    assert not result['issues']
    assert len(result['proposals']) == 1
    assert result['proposals'][0]['status'] == 'surface_candidate'


def test_relative_minimum_duration_stays_inside_event_without_spurious_nested_cue():
    text = 'Office acts after an opportunity for notice that is at least 2 weeks.'
    result = p.propose(text)
    row, = result['proposals']
    assert row['status'] == 'surface_candidate'
    assert not result['issues']
    assert row['semantic_flags']['minimum_duration_scope_unresolved']
    assert not row['semantic_flags']['nested_temporal_scope_unresolved']


def test_extended_legacy_notice_does_not_leak_suffix_after_query():
    text = 'Office acts within 6 days of notice of the hearing after approval; Registry acts after receipt.'
    result = p.propose(text)
    rows = result['proposals']
    assert len(rows) == 2
    assert rows[0]['family'] == 'legacy_lexical' and rows[0]['status'] == 'deferred'
    assert literal(text, rows[1]['query']['proposed_time_span']) == 'after receipt'
    assert rows[1]['status'] == 'surface_candidate'


def test_unsupported_outer_prefix_keeps_contained_legacy_inventory_deferred():
    text = 'Office acts within two days after receipt before 2040-01-01.'
    result = p.propose(text)
    row, = result['proposals']
    assert row['family'] == 'legacy_lexical'
    assert row['status'] == 'deferred'
    assert row['query'] == old.query(text, old.propose_time_spans(text)[0])
    assert row['reason_codes'] == ['unsupported_temporal_prefix']
    assert p.source_queries(text, result) == []


@pytest.mark.parametrize('quantity', ['thirteen', 'twenty-five', 'dozen', '-3', '+3', '٣', '½'])
def test_unsupported_for_duration_quantity_does_not_leak_suffix(quantity):
    text = f'Office acts for {quantity} days after receipt.'
    result = p.propose(text)
    assert p.source_queries(text, result) == []
    assert result['issues'] == [{'cue_span': interval(text, 'for'),
                                'reason_codes': ['unsupported_temporal_prefix']}]


def test_quoted_extended_legacy_prefix_cannot_swallow_independent_outer_event():
    text = 'Caption "within 6 days of notice of the hearing" and Office acts after receipt.'
    result = p.propose(text)
    assert len(result['proposals']) == 2
    assert result['proposals'][0]['status'] == 'deferred'
    assert result['proposals'][1]['status'] == 'surface_candidate'
    assert literal(text, result['proposals'][1]['query']['proposed_time_span']) == 'after receipt'


@pytest.mark.parametrize('prefix', ['within two\nweeks after', 'within 2.5\nweeks after',
                                   'at least 1000\nmonths after', 'for thirteen\ndays after',
                                   'no later than half a\nyear after'])
def test_unsupported_prefix_whitespace_does_not_make_suffix_a_new_occurrence(prefix):
    text = 'Office acts '+prefix+' receipt.'
    result = p.propose(text)
    assert p.source_queries(text, result) == []
    assert len(result['issues']) == 1
    assert result['issues'][0]['reason_codes'] == ['unsupported_temporal_prefix']


def test_unsupported_prefix_sentence_period_still_separates_independent_cue():
    text = 'Office acts within two days.\nAfter receipt, Registry archives.'
    result = p.propose(text)
    row, = result['proposals']
    assert row['status'] == 'surface_candidate'
    assert literal(text, row['query']['proposed_time_span']) == 'After receipt'
