"""Observed TRAIN aliases can expose contradictions, without semantic authority."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_byte_codec as byte_codec
from ipfs_datasets_py.logic.legal_ir import canonical_symbol_bindings as subject

SOURCE = ('The clerk must record evidence within ten days if fees are paid and '
          'the application is complete, unless a court order applies or a legal hold applies.')
TRANSPORT_FALSE = ('target_access', 'model_executed', 'source_fidelity_established',
                   'qualified', 'proof_authority', 'accepted')


def proposal(source=SOURCE, *, changes=None, spans=None):
    rule = dict(actor='clerk', modality='O', action='record', object='evidence',
                conditions=['application_complete', 'fees_paid'],
                exceptions=['court_order', 'legal_hold'], temporal=['within_ten_days'])
    if changes:
        rule.update(copy.deepcopy(changes))
    surfaces = {'actor': 'The clerk', 'modality': 'must', 'action': 'record', 'object': 'evidence',
                'conditions/0': 'the application is complete', 'conditions/1': 'fees are paid',
                'exceptions/0': 'a court order applies', 'exceptions/1': 'a legal hold applies',
                'temporal/0': 'within ten days'}
    if spans:
        surfaces.update(spans)
    anchors = []
    for leaf, surface in sorted(surfaces.items()):
        facet = leaf.split('/')[0]
        if facet in ('conditions', 'exceptions', 'temporal'):
            index = int(leaf.split('/')[1])
            if index >= len(rule[facet]):
                continue
            symbol = rule[facet][index]
        else:
            symbol = rule[facet]
            if facet == 'object' and not symbol:
                continue
        if isinstance(surface, tuple):
            text, occurrence = surface
            start = -1
            for _ in range(occurrence + 1):
                start = source.index(text, start + 1)
        else:
            text, start = surface, source.index(surface)
        anchors.append(dict(field_path='/rules/0/' + leaf, facet=facet,
                            canonical_symbol=symbol, start=start, end=start + len(text),
                            source_text=text, offset_unit='unicode_character_half_open'))
    value = dict(schema=byte_codec.PROPOSAL_SCHEMA,
                 source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                 canonical_ir={'rules': [rule]}, anchors=anchors,
                 facet_operators=dict(conditions='all', exceptions='any', temporal='all'),
                 single_rule_scope=True, **dict.fromkeys(TRANSPORT_FALSE, False))
    return byte_codec.validate_proposal(value, source)


def example(identity='train-one', source=SOURCE, value=None):
    return dict(id=identity, source_text=source, proposal=proposal(source) if value is None else value)


def profile():
    return subject.fit_profile([example()])


def digest(value):
    payload = {key: item for key, item in value.items() if key != 'content_sha256'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reseal(value):
    value['content_sha256'] = digest(value)
    return value


def test_fit_is_detached_deterministic_and_explicit_about_training_supervision():
    rows = [example()]
    original = copy.deepcopy(rows)
    fitted = subject.fit_profile(rows)
    assert rows == original
    assert fitted == subject.fit_profile(copy.deepcopy(rows))
    assert fitted['content_sha256'] == digest(fitted)
    assert fitted['training_supervision_consumed'] is True
    assert fitted['query_reference_accessed'] is False
    assert 'target_access' not in fitted
    assert len(fitted['entries']) == 9
    validated = subject.validate_profile(fitted, expected_profile_sha256=fitted['content_sha256'])
    validated['entries'][0]['canonical_symbols'].clear()
    assert fitted['entries'][0]['canonical_symbols']


def test_full_multi_qualifier_observed_proposal_has_consistent_bindings_only():
    value, fitted = proposal(), profile()
    original = copy.deepcopy((value, fitted))
    receipt = subject.assess_bindings(SOURCE, value, fitted,
                                      expected_profile_sha256=fitted['content_sha256'])
    assert receipt['outcome'] == 'binding_consistent'
    assert receipt['content_sha256'] == digest(receipt)
    assert len(receipt['leaves']) == 9
    assert {item['outcome'] for item in receipt['leaves']} == {'matched_single_alias'}
    assert receipt['target_access'] is False
    assert receipt['target_access_scope'] == 'query_reference_only'
    assert receipt['proposal_input_scope'] == 'model_candidate_not_reference'
    for field in TRANSPORT_FALSE:
        assert receipt[field] is False
    assert (value, fitted) == original
    assert subject.validate_bindings(receipt, SOURCE, value, fitted) == receipt


def test_same_offsets_with_wrong_action_and_object_detect_two_known_alias_mismatches():
    original = proposal()
    changed = proposal(changes={'action': 'notify', 'object': 'application'})
    assert [(a['field_path'], a['start'], a['end'], a['source_text']) for a in changed['anchors']] == [
        (a['field_path'], a['start'], a['end'], a['source_text']) for a in original['anchors']]
    byte_codec.validate_proposal(changed, SOURCE)
    receipt = subject.assess_bindings(SOURCE, changed, profile())
    assert receipt['outcome'] == 'binding_inconsistent'
    mismatches = [leaf for leaf in receipt['leaves'] if leaf['outcome'] == 'known_alias_mismatch']
    assert [leaf['field_path'] for leaf in mismatches] == ['/rules/0/action', '/rules/0/object']
    assert changed['canonical_ir']['rules'][0]['action'] == 'notify'
    assert changed['canonical_ir']['rules'][0]['object'] == 'application'
    assert 'repaired_proposal' not in receipt
    assert all(receipt[field] is False for field in TRANSPORT_FALSE)


@pytest.mark.parametrize('claimed', ['record', 'notify', 'invented'])
def test_training_collision_is_unassessed_even_when_claim_matches_one_observation(claimed):
    fitted = subject.fit_profile([
        example('first'), example('second', value=proposal(changes={'action': 'notify'}))])
    entry = next(item for item in fitted['entries'] if item['facet'] == 'action')
    assert entry['canonical_symbols'] == ['notify', 'record']
    assert entry['observation_count'] == 2
    receipt = subject.assess_bindings(SOURCE, proposal(changes={'action': claimed}), fitted)
    action = next(item for item in receipt['leaves'] if item['facet'] == 'action')
    assert action['outcome'] == 'ambiguous_alias'
    assert receipt['outcome'] == 'binding_unassessed'
    assert 'selected_symbol' not in action


def test_known_mismatch_has_precedence_over_unknown_and_ambiguous_aliases():
    fitted = subject.fit_profile([
        example('first'), example('second', value=proposal(changes={'action': 'notify'}))])
    source = SOURCE.replace('within ten days', 'after a fortnight')
    value = proposal(source, changes={'object': 'application'},
                     spans={'temporal/0': 'after a fortnight'})
    receipt = subject.assess_bindings(source, value, fitted)
    assert receipt['outcome'] == 'binding_inconsistent'
    assert {'ambiguous_alias', 'unknown_literal', 'known_alias_mismatch'} <= {
        leaf['outcome'] for leaf in receipt['leaves']}


@pytest.mark.parametrize('surface,modality', [('shall', 'O'), ('shall not', 'F'),
                                            ('is obliged to', 'O'), ('may not', 'F')])
def test_unobserved_modality_variants_do_not_borrow_grammar_aliases(surface, modality):
    source = SOURCE.replace('must', surface)
    value = proposal(source, changes={'modality': modality}, spans={'modality': surface})
    receipt = subject.assess_bindings(source, value, profile())
    modal = next(item for item in receipt['leaves'] if item['facet'] == 'modality')
    assert modal['outcome'] == 'unknown_literal'
    assert receipt['outcome'] == 'binding_unassessed'


@pytest.mark.parametrize('claimed', ['F', 'P'])
def test_observed_must_cannot_be_assigned_a_different_modality(claimed):
    receipt = subject.assess_bindings(SOURCE, proposal(changes={'modality': claimed}), profile())
    modal = next(item for item in receipt['leaves'] if item['facet'] == 'modality')
    assert modal['outcome'] == 'known_alias_mismatch'
    assert receipt['outcome'] == 'binding_inconsistent'


def test_unicode_casefold_and_whitespace_normalization_preserve_exact_original_offsets():
    training_source = SOURCE.replace('The clerk', 'The Straße')
    training = proposal(training_source, changes={'actor': 'street_official'},
                        spans={'actor': 'The Straße'})
    fitted = subject.fit_profile([example('unicode-train', training_source, training)])
    source = training_source.replace('The Straße', 'THE STRASSE').replace(
        'fees are paid', 'fees\t are\u00a0\npaid')
    value = proposal(source, changes={'actor': 'street_official'},
                     spans={'actor': 'THE STRASSE', 'conditions/1': 'fees\t are\u00a0\npaid'})
    receipt = subject.assess_bindings(source, value, fitted)
    assert receipt['outcome'] == 'binding_consistent'
    assert value['source_sha256'] != training['source_sha256']
    assert all(source[a['start']:a['end']] == a['source_text'] for a in value['anchors'])
    condition = next(a for a in value['anchors'] if a['field_path'].endswith('conditions/1'))
    assert condition['source_text'] == 'fees\t are\u00a0\npaid'


@pytest.mark.parametrize('surface', ['fees_are_paid', 'fees are paid,', 'the fees are paid',
                                    'fees have been paid'])
def test_no_underscore_punctuation_article_or_copula_expansion(surface):
    source = SOURCE.replace('fees are paid', surface)
    value = proposal(source, spans={'conditions/1': surface})
    receipt = subject.assess_bindings(source, value, profile())
    condition = next(item for item in receipt['leaves'] if item['field_path'].endswith('conditions/1'))
    assert condition['outcome'] == 'unknown_literal'
    assert receipt['outcome'] == 'binding_unassessed'


def test_normalization_does_not_fold_unicode_composition_or_punctuation():
    training_source = SOURCE.replace('The clerk', 'The café')
    trained = proposal(training_source, spans={'actor': 'The café'})
    fitted = subject.fit_profile([example('unicode', training_source, trained)])
    source = training_source.replace('café', 'cafe\u0301')
    value = proposal(source, spans={'actor': 'The cafe\u0301'})
    receipt = subject.assess_bindings(source, value, fitted)
    actor = next(item for item in receipt['leaves'] if item['facet'] == 'actor')
    assert actor['outcome'] == 'unknown_literal'
    assert receipt['outcome'] == 'binding_unassessed'


def test_repeated_literals_on_different_typed_paths_do_not_collide_across_facets():
    source = 'record must record record if record'
    value = proposal(source, changes=dict(actor='clerk', action='record', object='evidence',
                                          conditions=['fees_paid'], exceptions=[], temporal=[]),
                     spans={'actor': ('record', 0), 'action': ('record', 1),
                            'object': ('record', 2), 'conditions/0': ('record', 3)})
    fitted = subject.fit_profile([example('repeated', source, value)])
    repeated = [entry for entry in fitted['entries'] if entry['normalized_literal'] == 'record']
    assert {entry['facet'] for entry in repeated} == {'actor', 'action', 'object', 'conditions'}
    assert all(len(entry['canonical_symbols']) == 1 for entry in repeated)
    receipt = subject.assess_bindings(source, value, fitted)
    assert receipt['outcome'] == 'binding_consistent'
    assert len({a['start'] for a in value['anchors']}) == len(value['anchors'])


def test_repeated_same_facet_literals_retain_collision_instead_of_using_position_as_gold():
    source = 'The clerk must record evidence if approved and approved'
    value = proposal(source, changes=dict(conditions=['alpha', 'beta'], exceptions=[], temporal=[]),
                     spans={'conditions/0': ('approved', 0), 'conditions/1': ('approved', 1)})
    fitted = subject.fit_profile([example('two-conditions', source, value)])
    entry = next(item for item in fitted['entries'] if item['facet'] == 'conditions')
    assert entry['canonical_symbols'] == ['alpha', 'beta']
    receipt = subject.assess_bindings(source, value, fitted)
    conditions = [leaf for leaf in receipt['leaves'] if leaf['facet'] == 'conditions']
    assert len(conditions) == 2
    assert {leaf['outcome'] for leaf in conditions} == {'ambiguous_alias'}
    assert receipt['outcome'] == 'binding_unassessed'


def test_empty_object_has_no_fabricated_leaf_or_alias():
    value = proposal(changes={'object': ''})
    fitted = subject.fit_profile([example(value=value)])
    receipt = subject.assess_bindings(SOURCE, value, fitted)
    assert receipt['outcome'] == 'binding_consistent'
    assert 'object' not in {entry['facet'] for entry in fitted['entries']}
    assert 'object' not in {leaf['facet'] for leaf in receipt['leaves']}


def test_consistently_wrong_training_correspondence_can_pass_without_claiming_fidelity():
    wrong = proposal(changes={'action': 'notify'})
    fitted = subject.fit_profile([example('authored-wrong', value=wrong)])
    receipt = subject.assess_bindings(SOURCE, wrong, fitted)
    assert receipt['outcome'] == 'binding_consistent'
    assert receipt['source_fidelity_established'] is False
    assert receipt['independent_semantic_review_completed'] is False
    assert receipt['canonical_ir_repaired'] is False
    assert receipt['proposal_changed'] is False


def test_profile_manifest_binds_exact_examples_including_order_ids_source_and_labels():
    first, second = example('first'), example('second')
    forward = subject.fit_profile([first, second])
    reverse = subject.fit_profile([second, first])
    renamed = subject.fit_profile([example('renamed'), second])
    assert forward['entries'] == reverse['entries'] == renamed['entries']
    assert len({forward['training_manifest_sha256'], reverse['training_manifest_sha256'],
                renamed['training_manifest_sha256']}) == 3
    changed = subject.fit_profile([first, example('second', value=proposal(changes={'action': 'notify'}))])
    assert changed['training_manifest_sha256'] != forward['training_manifest_sha256']
    expected_manifest = hashlib.sha256(json.dumps(
        [first, second], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert forward['training_manifest_sha256'] == expected_manifest


@pytest.mark.parametrize('rows', [[], [example()] * 2, [dict(example(), target={})],
                                [dict(example(), split='DEV')], [example()] * 257])
def test_fit_rejects_unclosed_cohorts_duplicate_ids_and_bounds(rows):
    with pytest.raises(ValueError):
        subject.fit_profile(rows)


@pytest.mark.parametrize('identity', [True, 'x' * 513, '\ud800'])
def test_fit_rejects_invalid_identity(identity):
    with pytest.raises(ValueError):
        subject.fit_profile([example(identity)])


@pytest.mark.parametrize('surface', ['\ud800', 'x' * 16385])
def test_literal_normalization_rejects_invalid_text_without_truncation(surface):
    with pytest.raises(ValueError):
        subject.normalize_literal(surface)


def test_whitespace_only_candidate_span_is_unassessed_and_cannot_train_a_blank_alias():
    value = proposal()
    action = next(anchor for anchor in value['anchors'] if anchor['facet'] == 'action')
    start = SOURCE.index('record') - 1
    action.update(start=start, end=start + 1, source_text=SOURCE[start:start + 1])
    byte_codec.validate_proposal(value, SOURCE)
    assert subject.normalize_literal(action['source_text']) == ''
    receipt = subject.assess_bindings(SOURCE, value, profile())
    leaf = next(item for item in receipt['leaves'] if item['facet'] == 'action')
    assert leaf['outcome'] == 'unknown_literal'
    assert receipt['outcome'] == 'binding_unassessed'
    with pytest.raises(ValueError):
        subject.fit_profile([example(value=value)])


@pytest.mark.parametrize('change', ['missing_leaf', 'wrong_offset', 'forged_authority',
                                   'source_mismatch', 'stale_ir'])
def test_malformed_proposal_rejects_before_alias_lookup_and_never_returns_partial(monkeypatch, change):
    value = proposal()
    if change == 'missing_leaf':
        value['anchors'].pop()
    elif change == 'wrong_offset':
        value['anchors'][-1]['end'] += 1
    elif change == 'forged_authority':
        value['accepted'] = True
    elif change == 'source_mismatch':
        value['source_sha256'] = '0' * 64
    else:
        value['canonical_ir']['rules'][0]['action'] = 'notify'
    before = copy.deepcopy(value)
    fitted = profile()

    def forbidden_lookup(surface):
        pytest.fail('invalid complete proposal reached alias normalization')

    monkeypatch.setattr(subject, 'normalize_literal', forbidden_lookup)
    with pytest.raises(ValueError):
        subject.assess_bindings(SOURCE, value, fitted)
    assert value == before


@pytest.mark.parametrize('extra', ['reference_ir', 'target', 'embeddings'])
def test_inference_api_does_not_accept_query_reference_or_other_unscoped_inputs(extra):
    with pytest.raises(TypeError):
        subject.assess_bindings(SOURCE, proposal(), profile(), **{extra: {}})


@pytest.mark.parametrize('field,value', [
    ('schema', 'old'), ('normalization', 'grammar-expansion'), ('checksum_recipe', 'file-sha256'),
    ('training_pair_count', True), ('training_anchor_count', 10),
    ('training_supervision_consumed', False), ('target_access', False),
])
def test_resealed_profile_with_invalid_closed_metadata_is_rejected(field, value):
    fitted = profile()
    fitted[field] = value
    reseal(fitted)
    with pytest.raises(ValueError):
        subject.validate_profile(fitted)


@pytest.mark.parametrize('field,value', [
    ('facet', 'conditions/0'), ('normalized_literal', 'RECORD'),
    ('canonical_symbols', []), ('canonical_symbols', ['record', 'record']),
    ('observation_count', True),
])
def test_resealed_profile_with_invalid_entry_is_rejected(field, value):
    fitted = profile()
    entry = next(item for item in fitted['entries'] if item['facet'] == 'action')
    entry[field] = value
    reseal(fitted)
    with pytest.raises(ValueError):
        subject.validate_profile(fitted)


@pytest.mark.parametrize('change', ['reverse', 'duplicate', 'unsupported_modality', 'wrong_sum'])
def test_resealed_profile_rejects_entry_order_duplicates_symbols_and_count_mismatch(change):
    fitted = profile()
    if change == 'reverse':
        fitted['entries'].reverse()
    elif change == 'duplicate':
        fitted['entries'][1] = copy.deepcopy(fitted['entries'][0])
    elif change == 'unsupported_modality':
        next(entry for entry in fitted['entries'] if entry['facet'] == 'modality')['canonical_symbols'] = ['obligation']
    else:
        fitted['entries'][0]['observation_count'] = 2
    reseal(fitted)
    with pytest.raises(ValueError):
        subject.validate_profile(fitted)


def test_separately_supplied_profile_pin_rejects_a_self_consistent_changed_alias_table():
    fitted = profile()
    pin = fitted['content_sha256']
    changed = copy.deepcopy(fitted)
    next(entry for entry in changed['entries'] if entry['facet'] == 'action')['canonical_symbols'] = ['notify']
    reseal(changed)
    subject.validate_profile(changed)
    assert changed['content_sha256'] != pin
    for call in (
        lambda: subject.validate_profile(changed, expected_profile_sha256=pin),
        lambda: subject.assess_bindings(SOURCE, proposal(), changed, expected_profile_sha256=pin),
        lambda: subject.validate_bindings(subject.assess_bindings(SOURCE, proposal(), changed),
                                          SOURCE, proposal(), changed, expected_profile_sha256=pin),
    ):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize('pin', [True, 'A' * 64, '0' * 64])
def test_bad_profile_identity_rejected(pin):
    with pytest.raises(ValueError):
        subject.validate_profile(profile(), expected_profile_sha256=pin)


@pytest.mark.parametrize('field,value', [
    ('outcome', 'binding_inconsistent'), ('proposal_sha256', '0' * 64), ('target_access', True),
    ('target_access_scope', 'global'), ('accepted', True), ('extra', None),
])
def test_resealed_assessment_metadata_cannot_replace_recomputation(field, value):
    fitted, value_proposal = profile(), proposal()
    receipt = subject.assess_bindings(SOURCE, value_proposal, fitted)
    receipt[field] = value
    reseal(receipt)
    with pytest.raises(ValueError):
        subject.validate_bindings(receipt, SOURCE, value_proposal, fitted)


@pytest.mark.parametrize('field,value', [('start', True),
                                      ('claimed_symbol', 'notify'), ('recognized_symbols', ['notify']),
                                      ('outcome', 'known_alias_mismatch')])
def test_resealed_leaf_corruption_rejects_entire_assessment(field, value):
    fitted, value_proposal = profile(), proposal()
    receipt = subject.assess_bindings(SOURCE, value_proposal, fitted)
    receipt['leaves'][0][field] = value
    reseal(receipt)
    with pytest.raises(ValueError):
        subject.validate_bindings(receipt, SOURCE, value_proposal, fitted)


def test_assessment_replay_is_exact_detached_and_bound_to_candidate_profile_and_source():
    fitted, value = profile(), proposal()
    receipt = subject.assess_bindings(SOURCE, value, fitted)
    assert subject.assess_bindings(SOURCE, value, fitted) == receipt
    detached = subject.validate_bindings(receipt, SOURCE, value, fitted)
    detached['leaves'][0]['recognized_symbols'].clear()
    assert receipt['leaves'][0]['recognized_symbols']
    assert fitted['entries'][0]['canonical_symbols']
    changed_source = SOURCE + ' '
    changed_proposal = proposal(changed_source)
    changed_profile = subject.fit_profile([example('other')])
    for source, candidate, aliases in (
        (changed_source, changed_proposal, fitted),
        (SOURCE, proposal(changes={'action': 'notify'}), fitted),
        (SOURCE, value, changed_profile),
    ):
        with pytest.raises(ValueError):
            subject.validate_bindings(receipt, source, candidate, aliases)


def test_import_fit_and_assessment_use_no_grammar_model_or_prover():
    script = '''import builtins, json, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    roots = {'torch', 'spacy', 'transformers', 'numpy', 'sympy'}
    forbidden = ('canonical_explicit_qualifiers', 'canonical_compiler',
                 'legal_formula_learning', 'legal_formula_codec')
    if name.split('.')[0] in roots or name.endswith(forbidden) or 'prover' in name:
        raise AssertionError('forbidden numerical/grammar/prover import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from ipfs_datasets_py.logic.legal_ir import canonical_symbol_bindings as subject
row = json.load(sys.stdin)
fitted = subject.fit_profile([row])
receipt = subject.assess_bindings(row['source_text'], row['proposal'], fitted)
assert receipt['outcome'] == 'binding_consistent'
assert receipt['model_executed'] is False and receipt['prover_executed'] is False
print('target-free-stdlib-assessment-passed')
'''
    completed = subprocess.run([sys.executable, '-c', script], input=json.dumps(example()),
                               text=True, capture_output=True, check=True, timeout=20,
                               cwd=Path(subject.__file__).resolve().parents[3])
    assert completed.stdout.strip() == 'target-free-stdlib-assessment-passed'


def test_omitted_unanchored_source_qualifier_can_pass_without_establishing_whole_source_coverage():
    value = proposal(changes={'conditions': ['application_complete']})
    assert 'fees are paid' in SOURCE
    assert 'fees are paid' not in {a['source_text'] for a in value['anchors']}
    byte_codec.validate_proposal(value, SOURCE)
    receipt = subject.assess_bindings(SOURCE, value, profile())
    assert receipt['outcome'] == 'binding_consistent'
    assert receipt['leaf_count'] == 8
    assert receipt['assessment_scope'] == 'per_leaf_observed_TRAIN_literal_alias_agreement'
    assert receipt['source_fidelity_established'] is False
    assert receipt['independent_semantic_review_completed'] is False
    assert receipt['accepted'] is False
