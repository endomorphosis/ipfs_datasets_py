"""Explicit caption recovery and its governed/nested counterexamples."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.autoformal import legal_flat_scope_dependencies_v3 as dep
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition


def make(text, cuts=()):
    source = {'candidate_id': 'opaque-caption-case', 'source_text': text,
              'source_sha256': composition.text_sha256(text)}
    rows = []; start = 0
    for ordinal, end in enumerate((*cuts, len(text))):
        while start < end and text[start].isspace(): start += 1
        right = end
        while right > start and text[right-1].isspace(): right -= 1
        rows.append({'clause_id': str(ordinal), 'char_start': start, 'char_end': right,
                     'scope': deepcopy(composition.FLAT_SCOPE)})
        start = end
    return source, composition.prepare_source_plan(source, rows)


def evaluate(text, cuts=()):
    source, plan = make(text, cuts)
    result = dep.prepare_flat_scope_dependencies(source, plan, expected_plan_sha256=plan['plan_sha256'])
    assert dep.validate_flat_scope_dependencies(source, plan, result, expected_plan_sha256=plan['plan_sha256']) == result
    return result


@pytest.mark.parametrize('locator', ['731', '731.9', '731.9.12', '731(a)', '731.9(a)(2)', '999999.123456.12(ab12)(CD)'])
@pytest.mark.parametrize('caption', ['Editorial cross-reference: section', 'editorial cross-reference: section', 'EDITORIAL CROSS-REFERENCE: SECTION'])
def test_explicit_caption_case_and_bounded_unseen_locator_recovery(locator, caption):
    text = f'{caption} {locator}. Registry shall file notice.'
    result = evaluate(text)
    assert result['allows_flat_composition'], result['reasons']
    assert result['previous_deferral_recovered'] and not result['monotone_veto_over_v2']
    assert result['explicit_caption_spans'][0]['source_text'] == f'{caption} {locator}.'
    assert result['explicit_caption_spans'][0]['locator'] == locator
    assert result['recognized_top_level_intervals'] == [[0, len(text)]]
    assert not any(result[k] for k in dep.FALSE)


@pytest.mark.parametrize('locator', ['0', '000731.9', '1000000.9', '731.1234567', '731.9.2.3', '731..9',
                                    '731x.9', '731.9x', '731.9(a)(2)(b)', '731.9(abcde)', '731.9(a', '731.9)'])
def test_malformed_or_unbounded_locator_is_not_protected(locator):
    result = evaluate(f'Editorial cross-reference: section {locator}. Registry shall file notice.')
    assert not result['allows_flat_composition'] and not result['explicit_caption_spans']
    assert 'unresolved_semantic_reference' in result['reasons']


@pytest.mark.parametrize('text', [
    'Editorial cross-reference: section 731.9 Registry shall file notice.',
    'Editorial cross-reference: section 731.9.junk Registry shall file notice.',
    'Editorial cross-reference: section 731.9.; Registry shall file notice.',
    'Editorial cross-reference: section 731.9.. Registry shall file notice.',
    'non-Editorial cross-reference: section 731.9. Registry shall file notice.',
    'Editorial cross-reference: section\n731.9. Registry shall file notice.',
])
def test_exact_marker_punctuation_and_context_boundaries(text):
    result = evaluate(text)
    assert not result['explicit_caption_spans'] and not result['allows_flat_composition']


@pytest.mark.parametrize('governor', ['under', 'pursuant to', 'subject to', 'in accordance with', 'as provided in', 'as defined by', 'under the'])
@pytest.mark.parametrize('position', ['prefix', 'predicate'])
def test_governed_editorial_caption_remains_a_reference(governor, position):
    marker = 'Editorial cross-reference: section 731.9.'
    text = f'{governor.capitalize()} {marker} Registry shall file.' if position == 'prefix' else f'Registry shall file {governor} {marker}'
    result = evaluate(text)
    assert not result['allows_flat_composition']
    assert 'governed_editorial_reference' in result['reasons']
    assert result['governed_caption_findings']


@pytest.mark.parametrize('text', ['Under section 731.9, Registry shall file notice.',
    'Registry shall file notice under section 731.9.', 'Registry shall file notice pursuant to section 731.9.'])
def test_no_general_locator_or_substantive_reference_exemption(text):
    result = evaluate(text)
    assert not result['allows_flat_composition'] and 'unresolved_semantic_reference' in result['reasons']


@pytest.mark.parametrize('cue', ['unless', 'if', 'when', 'except when', 'provided that'])
@pytest.mark.parametrize('split', [False, True])
def test_nested_norm_across_caption_never_becomes_independent(cue, split):
    text = f'Registry shall file {cue} Editorial cross-reference: section 731.9. Board may archive.'
    end = text.index('731.9.') + len('731.9.')
    result = evaluate(text, [end] if split else [])
    assert not result['allows_flat_composition']
    assert 'multiple_norms_without_independent_separator' in result['reasons']
    assert any(e['kind'].startswith('nested_') for e in result['dependency_edges'])


@pytest.mark.parametrize('part', ['cross-reference:', 'section', '731.', '731.9'])
def test_cut_inside_caption_preserves_exact_offending_offsets(part):
    text = 'Editorial cross-reference: section 731.9. Registry shall file.'
    cut = text.index(part) + len(part)
    result = evaluate(text, [cut])
    assert not result['allows_flat_composition'] and 'plan_cut_inside_protected_region' in result['reasons']
    assert any(f['offset'] == cut and f['protected_kind'] == 'editorial_cross_reference' for f in result['cut_findings'])


@pytest.mark.parametrize('quote', ['"', '“'])
def test_quoted_marker_stays_an_opaque_literal_not_caption(quote):
    closer = '”' if quote == '“' else quote
    result = evaluate(f'Registry shall publish {quote}Editorial cross-reference: section 731.9. Under section 9, Board may archive{closer}.')
    assert result['allows_flat_composition'] and not result['explicit_caption_spans']
    assert len(result['modal_nodes']) == 1


@pytest.mark.parametrize('text', [
    'Editorial cross-reference: section 731.9. Registry shall file if the permit is active before 2099-01-01.',
    'Editorial cross-reference: section 731.9. Registry shall file unless the permit is valid within 4 days.',
])
def test_copular_time_ambiguity_is_not_relaxed(text):
    result = evaluate(text)
    assert not result['allows_flat_composition']
    assert 'local_qualifier_atom_outside_declared_grammar' in result['reasons']


@pytest.mark.parametrize('mutation', ['caption_offset', 'governor_removed', 'modal_removed', 'allow', 'authority', 'old_evidence'])
def test_repaired_evidence_digest_does_not_hide_mutations(mutation):
    source, plan = make('Registry shall file under Editorial cross-reference: section 731.9.')
    result = dep.prepare_flat_scope_dependencies(source, plan, expected_plan_sha256=plan['plan_sha256'])
    if mutation == 'caption_offset': result['explicit_caption_spans'][0]['char_start'] += 1
    elif mutation == 'governor_removed': result['governed_caption_findings'] = []
    elif mutation == 'modal_removed': result['modal_nodes'] = []
    elif mutation == 'allow': result['allows_flat_composition'] = True
    elif mutation == 'authority': result['independent_scope_verified'] = True
    else: result['previous_v2_evidence']['allows_flat_composition'] = True
    result['evidence_sha256'] = dep.digest({k:v for k,v in result.items() if k!='evidence_sha256'})
    with pytest.raises(ValueError, match='regeneration'):
        dep.validate_flat_scope_dependencies(source, plan, result, expected_plan_sha256=plan['plan_sha256'])


def test_multiple_caption_intervals_are_source_exact_and_distinct():
    first='Editorial cross-reference: section 731.9. Registry shall file;'
    text=first+' Editorial cross-reference: section 840.12(a). Board may archive.'
    result=evaluate(text,[len(first)])
    assert result['allows_flat_composition'] and len(result['explicit_caption_spans'])==2
    for span in result['protected_spans']:
        assert text[span['char_start']:span['char_end']]==span['source_text']


def test_plain_source_and_inputs_are_unchanged():
    source,plan=make('Registry shall file.');before=deepcopy((source,plan))
    result=dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256=plan['plan_sha256'])
    assert (source,plan)==before and result['allows_flat_composition']
    assert not result['previous_deferral_recovered']
