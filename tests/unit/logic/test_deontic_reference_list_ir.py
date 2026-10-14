"""Exact retained qualifiers keep citation members without widening norm scope."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


CITATION = 'sections 5.01.020, 5.01.030, and 5.01.040'
TARGETS = {'5.01.020', '5.01.030', '5.01.040'}


def source_element(family):
    text = (
        f'Subject to {CITATION}, the Secretary shall publish the notice.'
        if family == 'condition' else
        f'The Secretary shall publish the notice except as provided in {CITATION}.'
    )
    element, = extract_normative_elements(text)
    assert {row['value'] for row in element['cross_reference_details']} == TARGETS
    return element


@pytest.mark.parametrize('family', ['condition', 'exception'])
@pytest.mark.parametrize('mutation', ['raw_text', 'source_id', 'source_span', 'outside_source'])
def test_reference_rescue_requires_exact_occurrence_provenance(family, mutation):
    element = source_element(family)
    target = '5.01.020' if family == 'condition' else '5.01.040'
    reference = next(row for row in element['cross_reference_details'] if row['value'] == target)
    if mutation == 'raw_text':
        reference['raw_text'] = 'section 99.99.999'
    elif mutation == 'source_id':
        reference['source_id'] = 'a-different-source'
    elif mutation == 'source_span':
        reference['source_span'] = [2 * len(element['text']), 2 * len(element['text']) + 1]
    else:
        reference['span'] = [2 * len(element['text']), 2 * len(element['text']) + 1]
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    assert target not in {row['value'] for row in norm.cross_references}
    assert element == original


@pytest.mark.parametrize('family', ['condition', 'exception'])
def test_reference_rescue_requires_source_bound_qualifier(family):
    element = source_element(family)
    qualifier, = element[family + '_details']
    qualifier['raw_text'] = 'a different qualifier not present in the source'
    norm = LegalNormIR.from_parser_element(element)
    ordinary_member = '5.01.040' if family == 'condition' else '5.01.020'
    assert {row['value'] for row in norm.cross_references} == {ordinary_member}


def test_reference_members_stay_with_their_own_retained_qualifier():
    text = (
        f'Subject to {CITATION}, the Secretary shall publish the notice. '
        'Subject to sections 6.01.020, 6.01.030, and 6.01.040, the Clerk shall file the report.'
    )
    elements = extract_normative_elements(text)
    assert len(elements) == 2
    expected = {'Secretary': TARGETS, 'Clerk': {'6.01.020', '6.01.030', '6.01.040'}}
    for element in elements:
        norm = LegalNormIR.from_parser_element(element)
        assert {row['value'] for row in norm.cross_references} == expected[norm.actor]
        for row in norm.cross_references:
            assert norm.source_text[slice(*row['span'])] == row['raw_text']
