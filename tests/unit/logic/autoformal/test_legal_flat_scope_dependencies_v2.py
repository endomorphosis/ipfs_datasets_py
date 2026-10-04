"""Authored structural contrasts; these are not statutory scope gold labels."""
from copy import deepcopy
import pytest

from ipfs_datasets_py.logic.autoformal import legal_flat_scope_dependencies as v1
from ipfs_datasets_py.logic.autoformal import legal_flat_scope_dependencies_v2 as dep
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition


def make(text, cuts=(), identity='opaque-id'):
    source = {'candidate_id': identity, 'source_text': text, 'source_sha256': composition.text_sha256(text)}
    rows = []; start = 0
    for ordinal, end in enumerate((*cuts, len(text))):
        while start < end and text[start].isspace(): start += 1
        right = end
        while right > start and text[right-1].isspace(): right -= 1
        rows.append({'clause_id': f'occurrence-{ordinal}', 'char_start': start, 'char_end': right,
                     'scope': deepcopy(composition.FLAT_SCOPE)})
        start = end
    return source, composition.prepare_source_plan(source, rows)


def evaluate(text, cuts=()):
    source, plan = make(text, cuts)
    result = dep.prepare_flat_scope_dependencies(source, plan, expected_plan_sha256=plan['plan_sha256'])
    assert dep.validate_flat_scope_dependencies(source, plan, result, expected_plan_sha256=plan['plan_sha256']) == result
    return result


@pytest.mark.parametrize('text', [
    'Registry shall file notice.',
    'Registry may not release records.',
    'Registry is permitted to file notice.',
    'If the permit is active, Registry shall file notice.',
    'Unless the exemption is active, Registry shall file notice.',
    'Registry, when the permit is active, shall file notice.',
    'Registry shall, when the permit is active, file notice.',
    'Registry shall file notice if the permit is active.',
    'Registry shall file notice unless the exemption is active.',
    'Registry shall file notice except when the exemption is active.',
    'Registry shall file notice except where the record is sealed.',
    'Registry shall file notice provided that the permit is valid.',
    'When the application arrived within 14 days, Registry shall file notice before 2099-03-14.',
    'When the application was received within 14 days of publication, Registry shall file notice.',
    'If the application was not received before 2099-03-14, Registry shall file notice.',
    'Unless the record was filed, Registry shall archive notice.',
    'If the exemption applies, Registry shall file notice.',
    'Within 1.5 days, the Dept. of Records shall file notice.',
    'Before May 15, 2099, Registry shall file notice.',
    'Registry shall publish "only if; except that; provided however; otherwise; in that case".',
    'Registry shall publish “Board may archive unless exempt”.',
    "Registry shall publish the applicant's notice.",
])
def test_positive_declared_atoms_dates_and_opaque_quotes(text):
    result = evaluate(text)
    assert result['allows_flat_composition'], result['reasons']
    assert not result['semantic_independence_verified'] and not result['qualified']
    assert result['base_evidence']['allows_flat_composition']


@pytest.mark.parametrize('heading', ['(2) Filing duty: ', 'Record duty [2]. ', 'Editorial index [section 63001.2]: ', 'Filing duty.— '])
def test_v1_recognized_captions_after_closed_qualifier_preserved(heading):
    result = evaluate('If the permit is active, ' + heading + 'Registry shall file notice.')
    assert result['allows_flat_composition'], result['reasons']


@pytest.mark.parametrize('caption', ['record duty [2].', 'rEcOrD duty [2].', 'filing duty.—', 'fILING DUTY.—'])
def test_editorial_capitalization_cannot_launder_subordinate_norm(caption):
    text = 'Registry shall file unless ' + caption + ' Board may archive.'
    cut = text.index('.') + 1
    result = evaluate(text, [cut])
    assert not result['allows_flat_composition']
    assert 'unclassified_editorial_punctuation' in result['additional_reasons']
    for finding in result['editorial_findings']:
        assert text[finding['char_start']:finding['char_end']] == finding['source_text']


@pytest.mark.parametrize('cue', ['except that', 'EXCEPT THAT', 'provided however', 'provided, however,', 'only if', 'ONLY IF', 'provided always'])
def test_unclassified_scope_connectives_are_never_ignored(cue):
    result = evaluate(f'Registry shall file {cue} the permit is active.')
    assert not result['allows_flat_composition'] and result['unclassified_cue_findings']


@pytest.mark.parametrize('cue', ['otherwise', 'Otherwise', 'in that case', 'IN THAT CASE', 'in such event', 'if so', 'if not'])
def test_explicit_cross_clause_context_deferred(cue):
    first = 'Registry shall file notice;'
    result = evaluate(first + ' ' + cue + ' Board may archive.', [len(first)])
    assert not result['allows_flat_composition']
    assert any(row['kind'] == 'unclassified_cross_clause_context' for row in result['unclassified_cue_findings'])


@pytest.mark.parametrize('atom', ['lower caption', 'record duty', 'the permit active', 'the permit seems active',
                                  'the permit is active and the exemption is valid', 'the permit is active or valid',
                                  'the permit that is active is valid', 'the Board may archive', 'a valid permit exists'])
def test_finite_predicate_grammar_refuses_nominals_and_unimplemented_forms(atom):
    result = evaluate('Registry shall file notice unless ' + atom + '.')
    assert not result['allows_flat_composition']
    if result['local_atom_checks']:
        assert any(not check['within_declared_atom_grammar'] for check in result['local_atom_checks'])


def test_ordinary_independent_flat_conditionals_keep_distinct_owners():
    first = 'If the permit is active, Registry shall file unless the exemption is active.'
    result = evaluate(first + ' Unless the record is sealed, Board may archive.', [len(first)])
    assert result['allows_flat_composition'], result['reasons']
    assert {row['owner_norm_id'] for row in result['local_atom_checks']} == {'norm-00', 'norm-01'}
    assert all(row['matched_rule'] == 'copular_state' for row in result['local_atom_checks'])


def test_time_inside_condition_and_independent_deadline_keep_v1_ownership():
    result = evaluate('When the application arrived within 14 days, Registry shall file notice before 2099-03-14.')
    assert result['allows_flat_composition']
    times = [row for row in result['qualifier_nodes'] if row['kind'] == 'temporal_lexeme']
    assert [row['attachment_status'] for row in times] == ['inside_local_atom', 'local_declared_time']
    assert result['local_atom_checks'][0]['matched_rule'] == 'explicit_event'


@pytest.mark.parametrize('text,cuts', [
    ('record duty [2]. Registry shall file notice.', []),
    ('Registry shall file unless Board may archive.', []),
    ('If Board may archive, Registry shall file notice.', []),
    ('If the permit is active: Registry shall file notice; Board may archive.', [53]),
    ('Registry shall file under section 63.2.', []),
    ('Registry shall publish "Board may archive.', []),
])
def test_monotone_no_v1_deferral_is_promoted(text, cuts):
    source, plan = make(text, cuts)
    prior = v1.prepare_flat_scope_dependencies(source, plan, expected_plan_sha256=plan['plan_sha256'])
    assert not prior['allows_flat_composition']
    result = dep.prepare_flat_scope_dependencies(source, plan, expected_plan_sha256=plan['plan_sha256'])
    assert not result['allows_flat_composition'] and result['base_evidence'] == prior
    assert set(prior['reasons']).issubset(result['reasons'])


@pytest.mark.parametrize('mutation', ['owner', 'atom', 'grammar', 'base', 'permission', 'source', 'extra', 'cut'])
def test_repaired_hash_does_not_override_authoritative_regeneration(mutation):
    source, plan = make('If the permit is active, Registry shall file notice.')
    result = dep.prepare_flat_scope_dependencies(source, plan, expected_plan_sha256=plan['plan_sha256'])
    value = deepcopy(result)
    if mutation == 'owner': value['local_atom_checks'][0]['owner_norm_id'] = 'norm-99'
    if mutation == 'atom': value['local_atom_checks'][0]['char_end'] -= 1
    if mutation == 'grammar': value['local_atom_checks'][0]['matched_rule'] = 'guessed'
    if mutation == 'base': value['base_evidence']['allows_flat_composition'] = False
    if mutation == 'permission': value['allows_flat_composition'] = False
    if mutation == 'source': value['source']['source_text'] = 'Other source.'
    if mutation == 'extra': value['semantic_scope_proved'] = True
    if mutation == 'cut': value['recognized_top_level_intervals'][0][1] -= 1
    value['evidence_sha256'] = dep.digest({key: item for key, item in value.items() if key != 'evidence_sha256'})
    with pytest.raises(ValueError, match='authoritative regeneration'):
        dep.validate_flat_scope_dependencies(source, plan, value, expected_plan_sha256=plan['plan_sha256'])


def test_exact_external_source_plan_and_profile_commitments():
    source, plan = make('Registry shall file notice.')
    for kwargs in ({'expected_plan_sha256': '0'*64}, {'expected_plan_sha256': plan['plan_sha256'], 'profile': v1.PROFILE}):
        with pytest.raises(ValueError): dep.prepare_flat_scope_dependencies(source, plan, **kwargs)
    with pytest.raises(ValueError):
        dep.prepare_flat_scope_dependencies({**source, 'canonical_ir': {}}, plan, expected_plan_sha256=plan['plan_sha256'])
    with pytest.raises(ValueError):
        dep.prepare_flat_scope_dependencies({**source, 'candidate_id': 'changed'}, plan, expected_plan_sha256=plan['plan_sha256'])


def test_id_never_selects_a_grammar_rule():
    text = 'If the permit is active, Registry shall file notice.'
    a, p = make(text, identity='supported'); b, q = make(text, identity='unsupported')
    x = dep.prepare_flat_scope_dependencies(a, p, expected_plan_sha256=p['plan_sha256'])
    y = dep.prepare_flat_scope_dependencies(b, q, expected_plan_sha256=q['plan_sha256'])
    for key in ('status', 'reasons', 'local_atom_checks', 'editorial_findings', 'unclassified_cue_findings'):
        assert x[key] == y[key]
    assert not x['source_id_used_as_feature']


def test_quoted_caption_and_cue_words_are_opaque_objects():
    result = evaluate('Registry shall publish "unless record duty [2]. otherwise Board may archive".')
    assert result['allows_flat_composition'], result['reasons']
    assert result['editorial_findings'] == result['unclassified_cue_findings'] == result['local_atom_checks'] == []
