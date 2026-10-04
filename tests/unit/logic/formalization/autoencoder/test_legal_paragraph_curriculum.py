"""Authored composition data controls; no numerical model or Lake execution."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location('paragraph_preparation', ROOT / 'scripts/ops/autoencoder/prepare_legal_paragraph_curriculum.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


def validator(target):
    assert len(target['rules']) == 1
    assert target['rules'][0]['modality'] in ('O', 'P', 'F')
    return {'valid': True, 'canonical_ir': deepcopy(target)}


def fixture(slots=12):
    panels = {}
    for split in ('train', 'validation'):
        rows = []
        for index in range(slots):
            for variation in range(2):
                actor = split + '_agency_' + str(index)
                source = ('Évidence: ' if variation else '') + actor + ' shall retain the records.\n'
                rule = dict(actor=actor, action='retain', object='records', modality='O',
                            conditions=[], exceptions=[], temporal=[])
                rows.append(dict(id=split + ':' + str(index) + ':' + str(variation), group_id=split + ':' + str(index),
                                 split=split, source_text=source, target={'rules': [rule]},
                                 proof_authority=False, source_semantics_verified=False))
        panels[split] = rows
    vocab = sorted({token for rows in panels.values() for row in rows for token in p.TOKEN.findall(p.raw(row['target']).decode())})
    codec = {'schema': p.TOKEN_SCHEMA, 'target_vocabulary': ['<pad>', '<bos>', '<eos>', *vocab]}
    return panels['train'], panels['validation'], codec


def build(*args, **kwargs):
    return p.build_paragraphs(*args, validate_single_target=validator, **kwargs)


def test_deterministic_complete_ordered_sources_targets_and_input_immutability():
    args = fixture()
    original = deepcopy(args)
    actual = build(*args, rows_per_length=3)
    assert actual == build(*args, rows_per_length=3)
    assert args == original
    by_id = {row['id']: row for split in args[:2] for row in split}
    assert actual['status'] == 'prepared'
    for split in ('train', 'validation'):
        assert len(actual[split]) == 12
        for row in actual[split]:
            assert row['target_ids'][0] == 1 and row['target_ids'][-1] == 2
            assert len(row['target']['rules']) == row['clause_count']
            assert len({tuple(c['logical_slot']) for c in row['components']}) == row['clause_count']
            assert row['target_component_ids'] == [c['id'] for c in row['components']]
            assert row['source_encoder_token_count'] is None
            for position, component in enumerate(row['components']):
                old = by_id[component['id']]
                assert row['source_text'][component['char_start']:component['char_end']] == old['source_text']
                assert row['source_text'].encode()[component['byte_start']:component['byte_end']] == old['source_text'].encode()
                assert row['target']['rules'][position] == old['target']['rules'][0]
                assert component['split'] == split


def test_16_clauses_unavailable_with_ten_slots_but_other_lengths_retained():
    result = build(*fixture(slots=10), clause_counts=(1, 2, 4, 8, 16), rows_per_length=2)
    assert result['status'] == 'partial'
    blocked = [row for row in result['length_readiness'] if row['clause_count'] == 16]
    assert len(blocked) == 2
    assert all(row['reason'] == 'not_enough_independent_logical_slots' and row['produced_rows'] == 0 for row in blocked)
    assert len(result['train']) == len(result['validation']) == 8


@pytest.mark.parametrize('field', ['id', 'group_id', 'source_text'])
def test_cross_split_source_identity_and_groups_rejected(field):
    train, validation, codec = fixture()
    validation[0][field] = train[0][field]
    with pytest.raises(ValueError, match='overlap'):
        build(train, validation, codec)


def test_normalized_cross_split_overlap_rejected():
    train, validation, codec = fixture()
    validation[0]['source_text'] = train[0]['source_text'].swapcase() + ' '
    with pytest.raises(ValueError, match='normalized_source'):
        build(train, validation, codec)


def test_vector_leakage_rejected_and_no_vectors_exported():
    train, validation, codec = fixture()
    train[0]['embedding'] = validation[0]['embedding'] = [0.2, 0.4]
    with pytest.raises(ValueError, match='embedding'):
        build(train, validation, codec)
    validation[0]['embedding'] = [0.4, 0.2]
    result = build(train, validation, codec, clause_counts=(1,), rows_per_length=1)
    assert 'embedding' not in result['train'][0] and 'input' not in result['train'][0]
    assert all('embedding' not in c['original_metadata'] for c in result['train'][0]['components'])


def test_unknown_target_token_rejected_before_composition():
    train, validation, codec = fixture()
    validation[0]['target']['rules'][0]['actor'] = 'unseen'
    with pytest.raises(ValueError, match='vocabulary'):
        build(train, validation, codec)


def test_all_original_rows_validated_even_unselected():
    train, validation, codec = fixture()
    calls = []
    def capture(target):
        calls.append(p.digest(target))
        return validator(target)
    p.build_paragraphs(train, validation, codec, (1,), 1, validate_single_target=capture)
    assert len(calls) == len(train) + len(validation)


@pytest.mark.parametrize('field', ['proof_authority', 'source_semantics_verified', 'qualified', 'truncated'])
def test_false_original_authority_or_truncation_rejected(field):
    train, validation, codec = fixture()
    train[0][field] = True
    with pytest.raises(ValueError, match='authority/truncation'):
        build(train, validation, codec)


def test_validator_cannot_silently_replace_target():
    train, validation, codec = fixture()
    def altered(target):
        target['rules'][0]['actor'] = 'changed'
        return {'valid': True, 'canonical_ir': target}
    with pytest.raises(ValueError, match='changed target'):
        p.build_paragraphs(train, validation, codec, validate_single_target=altered)


@pytest.mark.parametrize('counts', [(0,), (1, 1), (True,), (65,), (), '1,2'])
def test_bounded_unique_lengths(counts):
    with pytest.raises(ValueError, match='clause counts'):
        build(*fixture(), clause_counts=counts)


def test_no_qualification_or_legacy_multirule_claim():
    result = build(*fixture(), clause_counts=(2,), rows_per_length=1)
    assert result['legacy_single_rule_runtime_loadable'] is False
    assert result['representation'] == 'experimental_ordered_multi_rule_json/v1'
    for key, value in p.FALSE.items():
        assert result[key] is value
        assert all(row[key] is value for split in ('train', 'validation') for row in result[split])


def test_sha_input_reader_rejects_changed_or_duplicate_json(tmp_path):
    source = tmp_path / 'input.json'
    source.write_text('{"a":1}')
    expected = p.text_digest(source.read_text())
    assert p._read_file(source, expected)[0] == {'a': 1}
    source.write_text('{"a":2}')
    with pytest.raises(ValueError, match='digest'):
        p._read_file(source, expected)
    source.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match='duplicate'):
        p._read_file(source, p.text_digest(source.read_text()))
