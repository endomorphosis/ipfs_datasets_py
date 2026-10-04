"""Coverage accounting tests only; no Torch, encoders, models, or Lake."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location('long_span_coverage_under_test', ROOT / 'scripts/ops/autoencoder/benchmark_long_span_decoder.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|-?\d+|true|false|null')


def test_package_inventory_ignores_torch_virtual_filenames(tmp_path, monkeypatch):
    source = tmp_path / 'real.py'
    source.write_text('value = 1\n')
    monkeypatch.setattr(b, 'sys', SimpleNamespace(modules={
        'torch._ops': SimpleNamespace(__file__='_ops.py'),
        'ipfs_datasets_py.real': SimpleNamespace(__file__=str(source)),
        'ipfs_datasets_py.namespace': SimpleNamespace(__file__=None),
    }))
    assert b.dependency_inventory(tmp_path) == {str(source): b.sha(source)}


@pytest.mark.parametrize('filename', ['relative.py', '/nonexistent/package-source.py'])
def test_package_inventory_refuses_unbound_package_source(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(b, 'sys', SimpleNamespace(modules={
        'ipfs_datasets_py.real': SimpleNamespace(__file__=filename)}))
    with pytest.raises(ValueError, match='outside explicit dependency tree'):
        b.dependency_inventory(tmp_path)


def rule(actor='agency', modality='O'):
    return dict(actor=actor, action='retain', object='records', modality=modality,
                conditions=[], exceptions=[], temporal=[])


def native_check(target):
    if type(target) is not dict or set(target) != {'rules'} or len(target['rules']) != 1:
        raise ValueError('one rule required')
    value = target['rules'][0]
    if type(value) is not dict or set(value) != set(rule()) or value['modality'] not in ('O', 'P', 'F'):
        raise ValueError('invalid rule')
    if any(type(value[k]) is not str for k in ('actor', 'action', 'object', 'modality')):
        raise ValueError('typed scalar required')
    return {'valid': True, 'canonical_ir': deepcopy(target)}


def fixture(expected=None, generated=None, *, text=None):
    expected = {'rules': [rule(), rule('officer')]} if expected is None else expected
    generated = deepcopy(expected) if generated is None else generated
    rendered = json.dumps(generated, sort_keys=True, separators=(',', ':')) if text is None else text
    pieces = TOKEN.findall(rendered)
    assert ''.join(pieces) == rendered
    vocabulary = ['<pad>', '<bos>', '<eos>', *sorted(set(pieces))]
    rows = [{'id': 'case-1', 'source_text': 'Whole original source.', 'target': expected}]
    predictions = [{'id': 'case-1', 'token_ids': [vocabulary.index(token) for token in pieces],
                    'generation_status': 'eos', 'eos_reached': True, 'exact_target': False,
                    'reconstructed_input': []}]
    return rows, predictions, vocabulary


def score(*args, validate=native_check):
    return b.coverage(*args, validate)['rows'][0]


def test_exact_candidate_requires_no_target_in_prediction_and_preserves_callers():
    values = fixture()
    old = deepcopy(values)
    assert 'target' not in values[1][0] and 'target_ids' not in values[1][0]
    result = score(*values)
    assert result['ordered_exact'] and result['all_rules_preserved']
    assert result['whole_rules_missing'] == result['whole_rules_extra'] == 0
    assert values == old
    assert result['source_text'] == values[0][0]['source_text']
    assert result['generated_ir'] == values[0][0]['target']
    assert all(result[key] is False for key in b.FALSE)


def test_missing_rule_counted_without_fabricating_output():
    rows, predictions, vocabulary = fixture(generated={'rules': [rule()]})
    result = score(rows, predictions, vocabulary)
    assert result['whole_rules_missing'] == 1 and result['whole_rules_extra'] == 0
    assert len(result['generated_ir']['rules']) == 1
    assert not result['ordered_exact'] and not result['all_rules_preserved']


def test_extra_rule_counted():
    result = score(*fixture(generated={'rules': [rule(), rule('officer'), rule('extra')]}))
    assert result['whole_rules_missing'] == 0 and result['whole_rules_extra'] == 1


def test_polarity_mutation_is_missing_original_and_extra_wrong_rule():
    result = score(*fixture(generated={'rules': [rule(modality='F'), rule('officer')]}))
    assert result['whole_rules_missing'] == result['whole_rules_extra'] == 1


def test_order_is_separate_from_multiset_rule_coverage():
    result = score(*fixture(generated={'rules': [rule('officer'), rule()]}))
    assert result['all_rules_preserved'] and not result['ordered_exact']


def test_rule_multiplicity_never_collapsed_to_set():
    result = score(*fixture(expected={'rules': [rule(), rule()]}, generated={'rules': [rule()]}))
    assert result['whole_rules_expected'] == 2 and result['whole_rules_missing'] == 1
    result = score(*fixture(expected={'rules': [rule()]}, generated={'rules': [rule(), rule()]}))
    assert result['whole_rules_extra'] == 1


@pytest.mark.parametrize('generated', [{'rules': []}, {'rules': 'bad'}, {'rules': [None]},
                                      {'rules': [{'actor': 'agency'}]}, {'wrong': []}])
def test_invalid_generated_structure_gets_no_partial_credit(generated):
    result = score(*fixture(generated=generated))
    assert result['generated_ir'] is None and result['error']
    assert result['whole_rules_missing'] == result['whole_rules_expected'] == 2
    assert not result['ordered_exact'] and not result['all_rules_preserved']


def test_missing_eos_no_gold_fallback_or_trusting_exact_flag():
    values = fixture()
    values[1][0].update(eos_reached=False, exact_target=True)
    result = score(*values)
    assert result['generated_ir'] is None and result['whole_rules_missing'] == 2
    assert not result['ordered_exact']


def test_malformed_json_no_gold_fallback():
    values = fixture(text='{"rules":[')
    result = score(*values)
    assert result['generated_ir'] is None and result['whole_rules_missing'] == 2


def test_duplicate_json_keys_cannot_be_silently_discarded():
    expected = {'rules': [rule()]}
    original = json.dumps(expected['rules'], sort_keys=True, separators=(',', ':'))
    result = score(*fixture(expected=expected, text='{"rules":[],"rules":' + original + '}'))
    assert result['generated_ir'] is None and not result['ordered_exact']


def test_validator_false_receipt_is_invalid_not_accepted():
    result = score(*fixture(), validate=lambda target: {'valid': False})
    assert result['generated_ir'] is None and result['whole_rules_missing'] == 2


@pytest.mark.parametrize('bad', [True, -1, 1.0, '3', None])
def test_invalid_token_ids_rejected(bad):
    values = fixture()
    values[1][0]['token_ids'][0] = bad
    result = score(*values)
    assert result['generated_ir'] is None


def test_negative_index_cannot_alias_valid_vocabulary_token():
    values = fixture()
    vocabulary = values[2]
    values[1][0]['token_ids'] = [index - len(vocabulary) for index in values[1][0]['token_ids']]
    result = score(*values)
    assert result['generated_ir'] is None and not result['ordered_exact']


@pytest.mark.parametrize('bad', [1, 'true', [], None])
def test_eos_must_be_exact_boolean_true(bad):
    values = fixture()
    values[1][0]['eos_reached'] = bad
    assert score(*values)['generated_ir'] is None


def test_missing_extra_and_duplicate_prediction_ids_fail_closed():
    rows, predictions, vocabulary = fixture()
    for changed in ([], predictions + deepcopy(predictions), [{**predictions[0], 'id': 'foreign'}]):
        with pytest.raises(ValueError):
            b.coverage(rows, changed, vocabulary, native_check)
    rows.append({**deepcopy(rows[0]), 'id': 'case-2'})
    with pytest.raises(ValueError):
        b.coverage(rows, predictions + deepcopy(predictions), vocabulary, native_check)


def test_duplicate_reference_ids_fail_closed():
    rows, predictions, vocabulary = fixture()
    with pytest.raises(ValueError):
        b.coverage(rows + deepcopy(rows), predictions + deepcopy(predictions), vocabulary, native_check)


def test_missing_reference_target_is_not_inferred_from_generated_output():
    rows, predictions, vocabulary = fixture()
    del rows[0]['target']
    with pytest.raises((ValueError, KeyError)):
        b.coverage(rows, predictions, vocabulary, native_check)
