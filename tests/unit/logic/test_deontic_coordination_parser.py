"""Source-only evidence for repeated-modal alternatives, without interpretation."""

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    _unresolved_duty_disjunction_groups,
    extract_normative_elements,
    score_scaffold_quality,
)


def assert_source_records(source, groups):
    for group in groups:
        start, end = group['span']
        assert source[start:end] == group['raw_text']
        scope_start, scope_end = group['scope_span']
        assert scope_start <= start < end <= scope_end
        assert source[scope_start:scope_end] == group['scope_raw_text']
        assert len(group['members']) == len(group['connectors']) + 1
        for member in group['members']:
            member_start, member_end = member['span']
            assert start <= member_start < member_end <= end
            assert source[member_start:member_end] == member['raw_text']
            modal_start, modal_end = member['modal_span']
            assert member_start <= modal_start < modal_end < member_end
            assert source[modal_start:modal_end] == member['modal_raw_text']
        for connector in group['connectors']:
            assert source[slice(*connector['span'])] == connector['raw_text']
            assert connector['raw_text'].casefold() == 'or'


@pytest.mark.parametrize('left_modal,right_modal', [
    ('shall', 'shall'), ('shall not', 'must'), ('may', 'shall not'),
    ('cannot', 'can not'), ('is required to', 'is permitted to'),
    ('has a duty to', 'is authorized to'), ('is responsible for', 'is directed to'),
    ('is obligated by law to', 'is legally required to'),
])
@pytest.mark.parametrize('connector', [' or ', ', or ', '; OR\t'])
def test_distinct_modal_forms_and_connectors_have_exact_original_source_coordinates(left_modal, right_modal, connector):
    left = f'The Secretary {left_modal} publish notice'
    right = f'the Clerk {right_modal} retain records'
    source = left + connector + right + '.'
    groups = _unresolved_duty_disjunction_groups(source)
    assert len(groups) == 1
    assert_source_records(source, groups)
    assert [member['raw_text'] for member in groups[0]['members']] == [left, right]
    assert [member['modal_raw_text'] for member in groups[0]['members']] == [left_modal, right_modal]


def test_repeated_implicit_actor_chain_preserves_each_modal_occurrence():
    source = 'The Secretary shall publish notice or shall publish notice or shall publish notice.'
    groups = _unresolved_duty_disjunction_groups(source)
    assert len(groups) == 1
    assert len(groups[0]['members']) == 3
    assert len({tuple(member['modal_span']) for member in groups[0]['members']}) == 3
    assert_source_records(source, groups)


@pytest.mark.parametrize('nested', [
    '(unless approval is granted)', '[unless approval is granted]',
    '{unless approval is granted}', '(unless "or shall disclose" is printed)',
    '(unless (under section 552(a)) approval is granted)',
])
def test_nonoperative_nested_text_is_retained_but_its_inner_modal_is_not_a_group_member(nested):
    source = f'The Secretary shall {nested} publish notice or shall retain records.'
    groups = _unresolved_duty_disjunction_groups(source)
    assert len(groups) == 1
    assert len(groups[0]['members']) == 2
    assert_source_records(source, groups)
    assert nested in groups[0]['members'][0]['raw_text']


@pytest.mark.parametrize('source', [
    'The Secretary shall publish notice and/or shall retain records.',
    'The Secretary shall publish notice and / or shall retain records.',
    'The Secretary shall publish notice or retain records.',
    'The Secretary shall publish notice under sections 552(a) or 553(b).',
    'The Secretary shall publish notice if the Clerk must file or shall retain records.',
    'The Secretary shall publish notice that the Clerk may file or shall retain records.',
    'The Secretary shall publish notice if the Clerk consents or the Director shall approve.',
    'The Secretary shall publish notice when approved or the Clerk shall retain records.',
    'The Secretary shall publish notice or the Clerk who may file the report.',
    'The Secretary shall publish notice (or the Clerk shall retain records.',
    'The Secretary shall publish notice) or the Clerk shall retain records.',
    'The Secretary shall display "publish or shall retain records.',
    'The Secretary shall publish notice. Or the Clerk shall retain records.',
])
def test_excluded_profiles_do_not_invent_a_top_level_group(source):
    assert _unresolved_duty_disjunction_groups(source) == []


@pytest.mark.parametrize('source', [
    'The Secretary shall publish notice or shall retain records.',
    'The Secretary may publish notice or the Clerk shall retain records.',
    'The Secretary shall not disclose records; or the Clerk shall release a summary.',
])
def test_fresh_scaffolds_carry_uncertainty_without_claiming_grouped_logic(source):
    rows = extract_normative_elements(source)
    assert rows
    for row in rows:
        assert 'disjunctive_duty_scope_unresolved' in row['parser_warnings']
        assert row['promotable_to_theorem'] is False
        # Detection does not manufacture an inclusive/exclusive choice operator.
        assert row['deontic_operator'] in {'O', 'P', 'F'}


@pytest.mark.parametrize('support', [None, [], [0, 0], [-1, 99], ['0', 5], [True, 9]])
def test_missing_or_invalid_support_cannot_hide_fresh_source_uncertainty(support):
    row = extract_normative_elements('The Secretary shall publish notice or shall retain records.')[0]
    row = deepcopy(row)
    row['support_span'] = support
    quality = score_scaffold_quality(row)
    assert 'disjunctive_duty_scope_unresolved' in quality['warnings']
    assert quality['promotable_to_theorem'] is False


def test_exact_independent_semicolon_support_does_not_inherit_neighbor_uncertainty():
    first = 'The Secretary shall publish notice'
    source = first + '; the Clerk shall retain records or shall file a report.'
    row = extract_normative_elements(first)[0]
    row['text'] = source
    row['support_span'] = [0, len(first)]
    assert 'disjunctive_duty_scope_unresolved' not in score_scaffold_quality(row)['warnings']
    group = _unresolved_duty_disjunction_groups(source)[0]
    assert group['raw_text'] == 'the Clerk shall retain records or shall file a report'


def test_plain_conjunction_and_independent_duties_retain_their_previous_readiness_warning_contract():
    for source in (
        'The Secretary shall publish notice and shall retain records.',
        'The Secretary shall publish notice; the Clerk shall retain records.',
    ):
        assert _unresolved_duty_disjunction_groups(source) == []
        assert all('disjunctive_duty_scope_unresolved' not in row['parser_warnings']
                   for row in extract_normative_elements(source))


@pytest.mark.parametrize('first_connector,second_connector', [('or', 'and'), ('and', 'or')])
def test_mixed_coordination_keeps_whole_semicolon_region_uncertain_without_assigning_precedence(first_connector, second_connector):
    clauses = ['The Secretary shall publish notice', 'the Clerk shall retain records', 'the Director shall file reports']
    region = f'{clauses[0]} {first_connector} {clauses[1]} {second_connector} {clauses[2]}'
    prefix = 'The Auditor shall inspect accounts; '
    suffix = '; the Registrar shall record the decision.'
    source = prefix + region + suffix
    groups = _unresolved_duty_disjunction_groups(source)
    assert len(groups) == 1
    assert_source_records(source, groups)
    assert groups[0]['scope_span'] == [len(prefix), len(prefix) + len(region)]
    assert groups[0]['scope_raw_text'] == region
    for clause in clauses:
        row = extract_normative_elements(clause)[0]
        row['text'] = source
        start = source.index(clause)
        row['support_span'] = [start, start + len(clause)]
        assert 'disjunctive_duty_scope_unresolved' in score_scaffold_quality(row)['warnings']
