"""Immutable source-bound unresolved alternatives are not semantic gold."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json

import pytest

from ipfs_datasets_py.logic.deontic.coordination import (
    COORDINATION_SCHEMA_VERSION,
    CoordinationGroup,
    MAX_SOURCE_CHARACTERS,
    build_coordination_groups,
    reconstruct_source,
    validate_coordination_group,
)

SOURCE = 'The Secretary shall publish notice or shall retain records.'


def candidate(source=SOURCE):
    groups = build_coordination_groups(source, 'fixture:1')
    assert len(groups) == 1
    return groups[0]


def reseal(payload):
    payload['evidence_sha256'] = sha256(json.dumps(
        {key: value for key, value in payload.items() if key != 'evidence_sha256'},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode()).hexdigest()
    return payload


def test_unresolved_structure_preserves_distinct_member_evidence_and_actor_inheritance():
    group = candidate()
    assert group.schema_version == COORDINATION_SCHEMA_VERSION
    assert group.structure_supported is True
    assert group.interpretation_required is True
    assert group.source_semantics_verified is False
    assert group.proof_ready is False
    assert group.blockers == ('coordination_interpretation_required',)
    assert [member.action for member in group.members] == ['publish notice', 'retain records']
    assert [member.actor for member in group.members] == ['The Secretary', 'The Secretary']
    assert [member.actor_inherited_from for member in group.members] == [None, 0]
    assert group.members[0].actor_span == group.members[1].actor_span
    assert group.members[0].modal_span != group.members[1].modal_span
    assert group.source_sha256 == sha256(SOURCE.encode()).hexdigest()
    assert group.source_text == SOURCE
    for member in group.members:
        assert SOURCE[slice(*member.actor_span)] == member.actor
        assert SOURCE[slice(*member.modal_span)] == member.modal_text
        assert SOURCE[slice(*member.action_span)] == member.action
        assert SOURCE[slice(*member.span)] == member.raw_text
    assert CoordinationGroup.from_dict(group.to_dict()) == group
    assert reconstruct_source(group) == SOURCE[:-1]


@pytest.mark.parametrize('left,right,operators', [
    ('shall', 'shall', ('O', 'O')),
    ('must', 'may', ('O', 'P')),
    ('shall not', 'must not', ('F', 'F')),
    ('cannot', 'can not', ('F', 'F')),
    ('is required to', 'is permitted to', ('O', 'P')),
    ('has a duty to', 'is authorized to', ('O', 'P')),
    ('has authority to', 'is empowered to', ('P', 'P')),
    ('is vested with the power to', 'is granted authority to', ('P', 'P')),
    ('is authorized and directed to', 'is conferred the authority to', ('O', 'P')),
])
def test_modal_evidence_is_source_faithful_without_claiming_scope(left, right, operators):
    group = candidate(f'The Secretary {left} publish notice or the Clerk {right} retain records.')
    assert group.structure_supported
    assert tuple(member.modality for member in group.members) == operators
    assert [member.modal_text for member in group.members] == [left, right]
    assert all(member.actor_inherited_from is None for member in group.members)
    assert group.proof_ready is False


def test_actor_inheritance_switches_to_last_explicit_actor_with_original_span():
    group = candidate('The Secretary shall publish notice or the Clerk shall retain records or shall file a report.')
    assert group.structure_supported
    assert [member.actor for member in group.members] == ['The Secretary', 'the Clerk', 'the Clerk']
    assert group.members[2].actor_inherited_from == 1
    assert group.members[2].actor_span == group.members[1].actor_span
    assert group.members[2].actor_span != group.members[0].actor_span


@pytest.mark.parametrize('separator', [' or ', ', or ', '; OR\t', ' ,\tOr  '])
def test_reconstruction_preserves_original_internal_separators_and_whitespace(separator):
    source = '  The Secretary shall publish notice' + separator + 'the Clerk shall retain records.  '
    group = candidate(source)
    assert group.structure_supported
    assert reconstruct_source(group) == source[slice(*group.scope_span)]
    assert separator in reconstruct_source(group)
    assert group.connectors[0].raw_text.lower() == 'or'


def test_scope_reconstruction_keeps_mixed_coordination_without_interpreting_precedence():
    source = 'The Auditor shall inspect accounts; The Secretary shall publish notice or shall retain records and shall file reports; the Registrar shall publish results.'
    group = candidate(source)
    assert group.structure_supported is False
    assert 'coordination_scope_not_fully_represented' in group.blockers
    assert reconstruct_source(group) == 'The Secretary shall publish notice or shall retain records and shall file reports'
    assert len(group.members) == 2
    assert 'Auditor' not in group.scope_raw_text and 'Registrar' not in group.scope_raw_text


@pytest.mark.parametrize('source,expected', [
    ('The Secretary shall publish notice or shall retain records within 10 days.', 'coordination_temporal_structure_unsupported'),
    ('The Secretary shall publish notice or shall retain records unless approved.', 'coordination_qualification_unsupported'),
    ('The Secretary shall (unless approved) publish notice or shall retain records.', 'coordination_nested_source_unsupported'),
    ('The Secretary shall publish notice or shall retain records under section 552.', 'coordination_reference_structure_unsupported'),
    ('The Secretary shall publish notice or shall inspect the premises after receiving an application.', 'coordination_procedure_structure_unsupported'),
    ('The Secretary shall publish notice or shall retain records and reports.', 'coordination_action_coordination_unsupported'),
    ('The Secretary shall publish notice or shall retain records, reports, applications.', 'coordination_action_structure_unsupported'),
    ('The Secretary shall publish notice or shall not retain no records.', 'coordination_action_negation_unsupported'),
    ('Each Secretary shall publish notice or shall retain records.', 'coordination_actor_structure_unsupported'),
    ('If approved, the Secretary shall publish notice or shall retain records.', 'coordination_scope_not_fully_represented'),
])
def test_unsupported_structure_keeps_exact_raw_evidence_and_explicit_blocker(source, expected):
    group = candidate(source)
    assert not group.structure_supported
    assert expected in group.blockers
    assert group.source_text == source
    assert reconstruct_source(group) == source[slice(*group.scope_span)]
    assert CoordinationGroup.from_dict(group.to_dict()) == group
    assert not group.proof_ready and not group.source_semantics_verified


@pytest.mark.parametrize('member_count', [2, 8, 9, 30])
def test_bounded_member_records_preserve_raw_source_above_supported_limit(member_count):
    source = 'The Secretary shall publish notice' + ' or shall retain records' * (member_count - 1) + '.'
    group = candidate(source)
    assert group.observed_member_count == member_count
    if member_count <= 8:
        assert group.structure_supported
        assert len(group.members) == member_count
        assert len(group.connectors) == member_count - 1
    else:
        assert not group.structure_supported
        assert group.members == group.connectors == ()
        assert 'coordination_member_count_unsupported' in group.blockers
    assert reconstruct_source(group) == source[:-1]
    assert CoordinationGroup.from_dict(group.to_dict()) == group


@pytest.mark.parametrize('source', [
    'The Secretary shall publish notice and shall retain records.',
    'The Secretary shall publish notice or retain records.',
    'The Secretary shall display "publish notice or shall retain records".',
    'The Secretary shall publish notice (or shall retain records).',
])
def test_unrecognized_source_does_not_manufacture_group(source):
    assert build_coordination_groups(source) == ()


def test_group_identity_is_deterministic_and_disambiguates_repeated_equal_regions():
    source = SOURCE + ' ' + SOURCE
    groups = build_coordination_groups(source, 'document:a')
    assert len(groups) == 2
    assert groups[0].group_raw_text == groups[1].group_raw_text
    assert groups[0].group_id != groups[1].group_id
    assert groups == build_coordination_groups(source, 'document:a')
    assert groups[0].group_id != build_coordination_groups(source, 'document:b')[0].group_id


@pytest.mark.parametrize('tamper', [
    lambda row: row['members'][0].update(actor='the Clerk'),
    lambda row: row['members'][0].update(action='disclose secrets'),
    lambda row: row['members'][0].update(modality='P'),
    lambda row: row['members'][1].update(actor_inherited_from=None),
    lambda row: row['members'][1].update(actor_span=row['members'][1]['modal_span']),
    lambda row: row.update(group_span=row['scope_span'][:1] + [row['scope_span'][1] - 1]),
    lambda row: row.update(scope_raw_text='altered scope'),
    lambda row: row.update(blockers=[]),
    lambda row: row.update(proof_ready=True),
    lambda row: row.update(source_semantics_verified=True),
    lambda row: row.update(interpretation_required=False),
    lambda row: row.update(unrecognized={'claim': 'trusted'}),
    lambda row: row['connectors'][0].update(raw_text='and'),
    lambda row: row['members'][0].update(index=False),
    lambda row: row.update(observed_member_count=True),
])
def test_deserialization_rebuilds_source_and_rejects_tamper_even_with_recomputed_seal(tamper):
    data = candidate().to_dict()
    tamper(data)
    reseal(data)
    with pytest.raises(ValueError):
        CoordinationGroup.from_dict(data)


def test_dataclass_replace_cannot_bypass_export_validation():
    group = candidate()
    wrong_member = replace(group.members[0], action='invent a duty')
    tampered = replace(group, members=(wrong_member, *group.members[1:]))
    for operation in (tampered.validate, tampered.to_dict, lambda: reconstruct_source(tampered),
                      lambda: validate_coordination_group(tampered)):
        with pytest.raises(ValueError):
            operation()
    with pytest.raises(ValueError):
        replace(group, proof_ready=True)
    with pytest.raises(FrozenInstanceError):
        group.group_raw_text = 'changed'
    with pytest.raises(FrozenInstanceError):
        group.members[0].action = 'changed'


def test_export_mapping_cannot_mutate_frozen_group_or_later_exports():
    group = candidate()
    exported = group.to_dict()
    exported['members'][0]['action_span'][0] = 0
    exported['blockers'].clear()
    assert exported != group.to_dict()
    assert group.members[0].action_span[0] > 0
    assert group.blockers == ('coordination_interpretation_required',)


@pytest.mark.parametrize('source,source_id', [(None, ''), (SOURCE, None), (SOURCE * 2000, ''), (SOURCE, 'x' * 513), ('\ud800', '')])
def test_source_bounds_and_types_are_strict(source, source_id):
    with pytest.raises(ValueError):
        build_coordination_groups(source, source_id)


def test_group_record_count_limit_prevents_unbounded_typed_exports():
    with pytest.raises(ValueError, match='group count'):
        build_coordination_groups(' '.join([SOURCE] * 65))
    assert build_coordination_groups('x' * MAX_SOURCE_CHARACTERS) == ()


def test_deserialization_rejects_malformed_types_and_shapes_before_accepting_payload():
    original = candidate().to_dict()
    for mutation in [
        lambda data: data.update(members=tuple(data['members'])),
        lambda data: data['members'][0].update(action_span=tuple(data['members'][0]['action_span'])),
        lambda data: data.pop('schema_version'),
        lambda data: data.update(connectors=data['connectors'] * 1000),
    ]:
        data = deepcopy(original)
        mutation(data)
        with pytest.raises(ValueError):
            CoordinationGroup.from_dict(data)
