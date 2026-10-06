"""A closed semantic request renders without source or cached teacher artifacts."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.deontic.coordination_decoder import (
    COORDINATION_DECODE_REQUEST_SCHEMA,
    CoordinationDecodeMember,
    CoordinationDecodeRequest,
    coordination_symbol_registry,
    decode_coordination_request,
    render_coordination_request,
    semantic_label_identity,
)


def request(scope='modal_over_actions', modalities=('O', 'O'), actors=('secretary', 'secretary'),
            actions=('publish notice', 'retain records')):
    return CoordinationDecodeRequest(
        modal_scope=scope, connective='inclusive_or', binding_profile='universal_actor_predicate',
        members=tuple(CoordinationDecodeMember(actor, modality, action)
                      for actor, modality, action in zip(actors, modalities, actions)),
    )


def test_closed_request_has_only_ordered_semantic_fields_and_round_trips():
    item = request()
    assert item.to_dict() == {
        'schema': COORDINATION_DECODE_REQUEST_SCHEMA,
        'modal_scope': 'modal_over_actions', 'connective': 'inclusive_or',
        'binding_profile': 'universal_actor_predicate',
        'members': [{'actor': 'secretary', 'modality': 'O', 'action': 'publish notice'},
                    {'actor': 'secretary', 'modality': 'O', 'action': 'retain records'}],
    }
    assert CoordinationDecodeRequest.from_dict(item.to_dict()) == item
    assert type(item.members) is tuple
    with pytest.raises(FrozenInstanceError):
        item.modal_scope = 'disjunction_of_norms'
    with pytest.raises(FrozenInstanceError):
        item.members[0].action = 'disclose secrets'


@pytest.mark.parametrize('operator,name', [('O', 'OBLIGATION'), ('P', 'PERMISSION'), ('F', 'PROHIBITION')])
def test_both_scopes_have_distinct_formula_ast_and_explicit_normalized_text(operator, name):
    wide = decode_coordination_request(request(modalities=(operator, operator)))
    narrow = decode_coordination_request(request('disjunction_of_norms', modalities=(operator, operator)))
    assert wide['formula'] != narrow['formula']
    assert wide['native_ast'] != narrow['native_ast']
    assert wide['normalized_text'] != narrow['normalized_text']
    assert 'modal_over_actions' in wide['normalized_text']
    assert 'disjunction_of_norms' in narrow['normalized_text']
    assert wide['normalized_text'].count(name) == 1
    assert narrow['normalized_text'].count(name) == 2
    for result in (wide, narrow):
        assert result['context'] == 'source_withheld_semantic_ir'
        assert result['decoder_kind'] == 'deterministic_ir_renderer'
        assert result['family_validation']['passed'] is True
        assert result['native_validation']['validator'] == 'strict_native_reparse_and_exact_AST'
        assert result['lean_body']
        for flag in ('source_semantics_verified', 'semantic_equivalence_checked', 'admitted', 'formalized', 'proof_ready'):
            assert result[flag] is False
        assert result['requires_validation'] is True


def test_narrow_scope_preserves_distinct_actors_and_mixed_modalities():
    result = decode_coordination_request(request('disjunction_of_norms', modalities=('P', 'F'), actors=('clerk', 'director')))
    assert len(result['mapping']['actor_symbols']) == 2
    assert result['formula'].startswith('(P(')
    assert ' or F(' in result['formula']
    assert 'PERMISSION[' in result['normalized_text']
    assert 'PROHIBITION[' in result['normalized_text']


@pytest.mark.parametrize('actors,modalities', [(('clerk', 'director'), ('O', 'O')), (('clerk', 'clerk'), ('O', 'P'))])
def test_shared_scope_rejects_mismatched_actor_or_modality(actors, modalities):
    item = request(actors=actors, modalities=modalities)
    with pytest.raises(ValueError, match='one normalized actor'):
        decode_coordination_request(item)


def test_normalization_matches_case_spacing_and_one_leading_actor_article_only():
    item = request(actors=('The Secretary', 'secretary'), actions=('Publish\tNotice', 'retain  records'))
    result = decode_coordination_request(item)
    canonical = decode_coordination_request(request())
    assert result['formula'] == canonical['formula']
    assert result['native_ast'] == canonical['native_ast']
    assert result['normalized_text'] == canonical['normalized_text']
    assert semantic_label_identity('The The Clerk', actor=True) == 'the clerk'
    assert semantic_label_identity('The Notice', actor=False) == 'the notice'
    assert semantic_label_identity('a-b', actor=False) != semantic_label_identity('a b', actor=False)


def test_duplicate_members_are_retained_in_order_even_when_symbol_registry_deduplicates():
    item = request(actions=('publish notice', 'publish notice'))
    result = decode_coordination_request(item)
    actions = result['mapping']['action_symbols']
    assert len(actions) == 1
    assert actions[0]['member_indices'] == [0, 1]
    assert result['formula'].count(actions[0]['symbol']) == 2
    reversed_item = replace(request(), members=tuple(reversed(request().members)))
    assert decode_coordination_request(reversed_item)['formula'] != decode_coordination_request(request())['formula']


def test_collision_safe_registry_distinguishes_hyphen_from_space_and_retains_label_inventory():
    rows, symbols = coordination_symbol_registry(('file a-b', 'file a b'), 'action')
    assert symbols[0] != symbols[1]
    assert [row['member_indices'] for row in rows] == [[0], [1]]
    assert [row['source_texts'] for row in rows] == [['file a-b'], ['file a b']]
    result = decode_coordination_request(request(actions=('file a-b', 'file a b')))
    assert result['mapping']['action_symbols'] == rows


@pytest.mark.parametrize('forbidden', ['source_text', 'raw_text', 'source_id', 'source_span', 'group_id', 'source_sha256',
                                       'formula', 'native_ast', 'native_payload', 'teacher_response', 'metadata'])
@pytest.mark.parametrize('level', ['request', 'member'])
def test_extra_provenance_and_teacher_fields_are_rejected_at_each_closed_level(forbidden, level):
    data = request().to_dict()
    target = data if level == 'request' else data['members'][0]
    target[forbidden] = {'nested': {'hidden': 'The Clerk shall disclose secrets'}}
    with pytest.raises(ValueError):
        CoordinationDecodeRequest.from_dict(data)


@pytest.mark.parametrize('value', [None, False, 1, [], {}, 'O', ('actor', 'secretary')])
def test_nonobject_wire_requests_are_not_coerced(value):
    with pytest.raises(ValueError):
        CoordinationDecodeRequest.from_dict(value)


@pytest.mark.parametrize('field,value', [
    ('schema', None), ('schema', True), ('schema', 'old'),
    ('modal_scope', None), ('modal_scope', 'exclusive_or'), ('modal_scope', ['modal_over_actions']),
    ('connective', 'exclusive_or'), ('binding_profile', 'existential_actor'),
])
def test_missing_or_unknown_interpretation_choices_cannot_receive_defaults(field, value):
    data = request().to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        CoordinationDecodeRequest.from_dict(data)


@pytest.mark.parametrize('slot,value', [
    ('actor', 'The Secretary shall publish notice'), ('action', 'shall publish notice'),
    ('action', 'publish notice unless approved'), ('action', 'publish notice and retain records'),
    ('action', 'not publish notice'), ('action', 'publish notice within 10 days'),
    ('action', 'publish notice under section 552'), ('action', 'publish notice\nretain records'),
    ('action', 'publish notice; retain records'), ('action', 'O(Publish(x))'),
    ('actor', 'Every Clerk'), ('actor', 'None'), ('actor', 'a' * 257),
    ('action', 'a' * 1025), ('action', ' '.join(['word'] * 33)),
    ('actor', 'élève'), ('action', 'publish\x00notice'), ('actor', 'secretary\u200b'),
    ('action', 'a' * 64), ('actor', 'abcdef01-abcd-abcd-abcd-abcdef012345'),
    ('actor', {'raw_text': 'Secretary'}), ('action', ['publish notice']),
    ('action', 'is required to publish notice'), ('action', 'has a duty to publish notice'),
    ('action', 'is legally obligated to publish notice'), ('action', 'is hereby prohibited from publishing notice'),
    ('action', 'is duty-bound to publish notice'), ('action', 'is duty bound to publish notice'),
    ('action', 'it is unlawful to disclose records'),
])
def test_labels_cannot_hide_source_clauses_formulas_or_unbounded_payloads(slot, value):
    data = request().to_dict()
    data['members'][0][slot] = value
    with pytest.raises(ValueError):
        CoordinationDecodeRequest.from_dict(data)


@pytest.mark.parametrize('count', [0, 1, 9, 1000])
def test_member_count_is_strictly_bounded(count):
    data = request().to_dict()
    data['members'] = [data['members'][0]] * count
    with pytest.raises(ValueError):
        CoordinationDecodeRequest.from_dict(data)


def test_eight_members_render_without_losing_order_or_modalities():
    members = tuple(CoordinationDecodeMember('clerk', 'O', 'file report ' + str(index)) for index in range(8))
    item = CoordinationDecodeRequest('disjunction_of_norms', 'inclusive_or', 'universal_actor_predicate', members)
    result = decode_coordination_request(item)
    assert len(result['mapping']['action_symbols']) == 8
    assert [row['member_indices'] for row in result['mapping']['action_symbols']] == [[index] for index in range(8)]


def test_direct_decoder_accepts_only_exact_typed_request_and_revalidates_forged_mutation():
    for value in (request().to_dict(), None, [], 'The Secretary shall publish notice'):
        with pytest.raises(ValueError):
            decode_coordination_request(value)
    item = request()
    object.__setattr__(item.members[0], 'action', 'shall disclose secrets')
    with pytest.raises(ValueError):
        decode_coordination_request(item)


def test_semantic_renderer_never_calls_source_parser_group_builder_or_legacy_decoder(monkeypatch):
    import sys
    from importlib import import_module
    from types import ModuleType

    def forbidden(*args, **kwargs):
        raise AssertionError('Source-based or legacy decode path was accessed')

    # Test-only sentinels make forbidden source paths independent of optional modules.
    for name, attributes in (
        ('ipfs_datasets_py.logic.deontic.coordination', ('build_coordination_groups', 'reconstruct_source')),
        ('ipfs_datasets_py.logic.deontic.utils.deontic_parser', ('extract_normative_elements', '_unresolved_duty_disjunction_groups')),
        ('ipfs_datasets_py.logic.deontic.decoder', ('decode_legal_norm_ir',)),
    ):
        sentinel = ModuleType(name)
        for attribute in attributes:
            setattr(sentinel, attribute, forbidden)
        parent_name, _, child_name = name.rpartition(".")
        monkeypatch.setattr(import_module(parent_name), child_name, sentinel, raising=False)
        monkeypatch.setitem(sys.modules, name, sentinel)
    assert decode_coordination_request(request())['structure_compiled'] is True


def test_request_and_result_mutable_wire_copies_do_not_change_subsequent_rendering():
    item = request()
    baseline = decode_coordination_request(item)
    exported = item.to_dict()
    exported['members'][0]['action'] = 'invent a duty'
    modified = deepcopy(baseline)
    modified['native_ast'].clear()
    modified['mapping']['action_symbols'].clear()
    assert item.to_dict() != exported
    assert decode_coordination_request(item) == baseline
    assert render_coordination_request(item) == baseline
