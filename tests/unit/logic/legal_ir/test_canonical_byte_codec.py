"""Exact open-alphabet transport with occurrence checks, not semantic authority."""

import copy
import hashlib
import json
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_byte_codec as subject

SOURCE = ('The clerk must record evidence if fees have been paid and the application is complete, '
          'unless a court order applies or a legal hold applies.')
FALSE_FIELDS = ('target_access', 'model_executed', 'source_fidelity_established',
                'qualified', 'proof_authority', 'accepted')


def proposal():
    rule = dict(actor='clerk', modality='O', action='record', object='evidence',
                conditions=['application_complete', 'fees_paid'],
                exceptions=['court_order', 'legal_hold'], temporal=[])
    spans = {'actor': 'clerk', 'modality': 'must', 'action': 'record', 'object': 'evidence',
             'conditions/0': 'the application is complete', 'conditions/1': 'fees have been paid',
             'exceptions/0': 'a court order applies', 'exceptions/1': 'a legal hold applies'}
    anchors = []
    for leaf, text in sorted(spans.items()):
        facet = leaf.split('/')[0]
        symbol = rule[facet] if '/' not in leaf else rule[facet][int(leaf.split('/')[1])]
        start = SOURCE.index(text)
        anchors.append(dict(field_path='/rules/0/' + leaf, facet=facet,
                            canonical_symbol=symbol, start=start, end=start + len(text),
                            source_text=text, offset_unit='unicode_character_half_open'))
    return dict(schema=subject.PROPOSAL_SCHEMA,
                source_sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
                canonical_ir={'rules': [rule]}, anchors=anchors,
                facet_operators=dict(conditions='all', exceptions='any', temporal='all'),
                single_rule_scope=True, **dict.fromkeys(FALSE_FIELDS, False))


def wire(value=None):
    value = proposal() if value is None else value
    return dict(schema=subject.WIRE_SCHEMA, source_sha256=value['source_sha256'],
                canonical_ir=value['canonical_ir'],
                anchors=[[item['field_path'], item['start'], item['end']] for item in value['anchors']])


def tokens(value=None, *, text=None):
    if text is None:
        text = json.dumps(wire() if value is None else value, sort_keys=True,
                          separators=(',', ':'), ensure_ascii=False)
    return [1, *(byte + 3 for byte in text.encode('utf-8')), 2]


def test_lossless_complete_proposal_with_aliases_and_multiple_qualifiers():
    original = proposal()
    encoded = subject.encode_proposal(original, SOURCE)
    assert encoded == tokens()
    assert subject.decode_proposal(encoded, SOURCE) == original
    assert original['canonical_ir']['rules'][0]['conditions'][0] not in SOURCE
    assert len(original['anchors']) == 8
    assert subject.VOCAB_SIZE == 259


def test_validation_and_decode_return_detached_values():
    original = proposal()
    validated = subject.validate_proposal(original, SOURCE)
    decoded = subject.decode_proposal(subject.encode_proposal(original, SOURCE), SOURCE)
    validated['canonical_ir']['rules'][0]['conditions'].clear()
    decoded['anchors'][0]['source_text'] = 'changed'
    assert len(original['canonical_ir']['rules'][0]['conditions']) == 2
    assert original['anchors'][0]['source_text'] == 'record'


def test_exact_capacity_and_unavailable_without_truncation():
    original = proposal()
    required = len(tokens())
    assert subject.encode_proposal(original, SOURCE, output_cap=required) == tokens()
    assert subject.decode_proposal(tokens(), SOURCE, output_cap=required) == original
    unavailable = subject.inspect_encoding(original, SOURCE, output_cap=required - 1)
    assert unavailable['outcome'] == 'encoding_unavailable'
    assert subject.inspect_encoding(original, SOURCE, output_cap=required)['outcome'] == 'encoding_admitted'
    with pytest.raises(ValueError):
        subject.encode_proposal(original, SOURCE, output_cap=required - 1)
    with pytest.raises(ValueError):
        subject.decode_proposal(tokens(), SOURCE, output_cap=required - 1)


@pytest.mark.parametrize('cap', [None, True, 2, 32771, 4096.0, '4096', -1])
def test_invalid_caps_rejected(cap):
    with pytest.raises(ValueError):
        subject.encode_proposal(proposal(), SOURCE, output_cap=cap)


@pytest.mark.parametrize('field', FALSE_FIELDS)
def test_codec_never_accepts_forged_authority(field):
    changed = proposal()
    changed[field] = True
    with pytest.raises(ValueError):
        subject.encode_proposal(changed, SOURCE)


@pytest.mark.parametrize('field,value', [
    ('source_sha256', '0' * 64), ('schema', 'old'), ('single_rule_scope', 1),
    ('facet_operators', {'conditions': 'any', 'exceptions': 'any', 'temporal': 'all'}),
    ('reference', {}), ('accepted', 0), ('anchors', []), ('canonical_ir', {'rules': []}),
])
def test_proposal_closed_schema_and_identity(field, value):
    changed = proposal()
    changed[field] = value
    with pytest.raises(ValueError):
        subject.validate_proposal(changed, SOURCE)


@pytest.mark.parametrize('field,value', [
    ('start', True), ('end', 21.0), ('start', -1), ('end', 99999), ('start', 21),
    ('source_text', 'wrong'), ('canonical_symbol', 'notify'), ('facet', 'actor'),
    ('field_path', '/rules/0/action/0'), ('offset_unit', 'byte'), ('extra', None),
])
def test_anchor_corruption_rejected(field, value):
    changed = proposal()
    changed['anchors'][0][field] = value
    with pytest.raises(ValueError):
        subject.encode_proposal(changed, SOURCE)


@pytest.mark.parametrize('variant', ['missing', 'duplicate', 'reverse', 'overlap'])
def test_exact_complete_sorted_disjoint_anchor_coverage(variant):
    changed = proposal()
    if variant == 'missing':
        changed['anchors'].pop()
    elif variant == 'duplicate':
        changed['anchors'].append(copy.deepcopy(changed['anchors'][0]))
    elif variant == 'reverse':
        changed['anchors'].reverse()
    else:
        actor = next(anchor for anchor in changed['anchors'] if anchor['facet'] == 'actor')
        actor.update(start=15, end=21, source_text=SOURCE[15:21])
    with pytest.raises(ValueError):
        subject.validate_proposal(changed, SOURCE)


@pytest.mark.parametrize('facet,value', [
    ('conditions', ['fees_paid', 'application_complete']),
    ('conditions', ['application_complete', 'application_complete']),
    ('conditions', ['']), ('temporal', [None]), ('actor', ''), ('action', True),
    ('modality', 'obligation'), ('object', None), ('conditions', 'fees_paid'),
])
def test_rule_corruption_rejected(facet, value):
    changed = proposal()
    changed['canonical_ir']['rules'][0][facet] = value
    with pytest.raises(ValueError):
        subject.encode_proposal(changed, SOURCE)


@pytest.mark.parametrize('change', [
    lambda ids: ids[1:], lambda ids: ids[:-1], lambda ids: [0] + ids,
    lambda ids: ids + [0], lambda ids: ids + [2], lambda ids: [1, 1] + ids[1:],
    lambda ids: ids[:2] + [2] + ids[2:], lambda ids: [1, 0, 2],
    lambda ids: [1, 259, 2], lambda ids: [1, -1, 2],
    lambda ids: [1, True, 2], lambda ids: [1, 126.0, 2],
    lambda ids: [1, 198, 2], lambda ids: [1, 258, 2],
])
def test_strict_framing_ids_and_utf8(change):
    with pytest.raises(ValueError):
        subject.decode_proposal(change(tokens()), SOURCE)


@pytest.mark.parametrize('text', [
    '{}', '[]', '{"schema":NaN}', '{"schema":Infinity}',
    '{"schema":"x","schema":"y"}', '[' * 17 + '0' + ']' * 17,
    json.dumps(wire(), sort_keys=True),
    json.dumps(wire(), sort_keys=True, separators=(',', ':')) + '\n',
])
def test_strict_json_closed_schema_and_canonical_serialization(text):
    with pytest.raises(ValueError):
        subject.decode_proposal(tokens(text=text), SOURCE)


@pytest.mark.parametrize('source', ['', ' ', '\ud800', 'x' * 16385, None, 8])
def test_invalid_sources_rejected(source):
    with pytest.raises(ValueError):
        subject.decode_proposal(tokens(), source)


@pytest.mark.parametrize('symbol', ['élève', '甲方', '😀', 'a\\b', 'a"b', 'Ω_条件', '[{}]' * 20])
def test_utf8_alphabet_has_no_training_vocabulary(symbol):
    original = proposal()
    original['canonical_ir']['rules'][0]['actor'] = symbol
    anchor = next(anchor for anchor in original['anchors'] if anchor['facet'] == 'actor')
    anchor['canonical_symbol'] = symbol
    encoded = subject.encode_proposal(original, SOURCE)
    assert subject.decode_proposal(encoded, SOURCE) == original
    serialized = json.dumps(symbol, ensure_ascii=False).encode('utf-8')[1:-1]
    assert serialized in bytes(item - 3 for item in encoded[1:-1])


def test_source_offsets_count_unicode_characters_not_utf8_bytes():
    changed = proposal()
    source = 'É📄' + SOURCE[3:]
    changed['source_sha256'] = hashlib.sha256(source.encode('utf-8')).hexdigest()
    for anchor in changed['anchors']:
        anchor['start'] -= 1
        anchor['end'] -= 1
    assert subject.decode_proposal(subject.encode_proposal(changed, source), source) == changed
    actor = next(item for item in changed['anchors'] if item['facet'] == 'actor')
    assert actor['start'] == 3
    assert len(source[:actor['start']].encode('utf-8')) == 7


def test_empty_object_and_qualifier_lists_have_no_invented_anchors():
    changed = proposal()
    rule = changed['canonical_ir']['rules'][0]
    rule.update(object='', conditions=[], exceptions=[])
    changed['anchors'] = [item for item in changed['anchors'] if item['facet'] in ('actor', 'action', 'modality')]
    assert subject.decode_proposal(subject.encode_proposal(changed, SOURCE), SOURCE) == changed


def test_repeated_source_surface_uses_separate_occurrence_offsets():
    changed = proposal()
    source = SOURCE + ' evidence'
    changed['source_sha256'] = hashlib.sha256(source.encode('utf-8')).hexdigest()
    changed['canonical_ir']['rules'][0]['temporal'] = ['after_evidence']
    changed['anchors'].append(dict(field_path='/rules/0/temporal/0', facet='temporal',
        canonical_symbol='after_evidence', start=len(SOURCE) + 1, end=len(source),
        source_text='evidence', offset_unit='unicode_character_half_open'))
    decoded = subject.decode_proposal(subject.encode_proposal(changed, source), source)
    object_anchor = next(item for item in decoded['anchors'] if item['facet'] == 'object')
    assert object_anchor['source_text'] == decoded['anchors'][-1]['source_text']
    assert object_anchor['start'] != decoded['anchors'][-1]['start']


def test_byte_hard_bound_rejects_large_valid_structure_instead_of_truncating():
    source = 'a m v o ' + 'x ' * 128
    rule = dict(actor='a', modality='O', action='v', object='o', temporal=[],
                conditions=[f'{index:03d}' + 'c' * 509 for index in range(64)],
                exceptions=[f'{index:03d}' + 'e' * 509 for index in range(64)])
    changed = proposal()
    changed.update(source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                   canonical_ir={'rules': [rule]}, anchors=[])
    slots = [('actor', 'a', 0), ('modality', 'O', 2), ('action', 'v', 4), ('object', 'o', 6)]
    slots += [(facet + '/' + str(index), symbol, 8 + 2 * (index + 64 * offset))
              for offset, facet in enumerate(('conditions', 'exceptions'))
              for index, symbol in enumerate(rule[facet])]
    for path, symbol, start in sorted(slots):
        changed['anchors'].append(dict(field_path='/rules/0/' + path, facet=path.split('/')[0],
            canonical_symbol=symbol, start=start, end=start + 1, source_text=source[start:start + 1],
            offset_unit='unicode_character_half_open'))
    subject.validate_proposal(changed, source)
    with pytest.raises(ValueError, match='hard bound'):
        subject.encode_proposal(changed, source, output_cap=32770)


@pytest.mark.parametrize('facet,value', [('conditions', ['q'] * 65), ('actor', 'x' * 513)])
def test_bounded_atom_and_qualifier_capacity(facet, value):
    changed = proposal()
    changed['canonical_ir']['rules'][0][facet] = value
    with pytest.raises(ValueError):
        subject.encode_proposal(changed, SOURCE)


def test_structural_checks_do_not_assert_alias_or_modality_meaning():
    changed = proposal()
    changed['canonical_ir']['rules'][0]['modality'] = 'F'
    next(anchor for anchor in changed['anchors'] if anchor['facet'] == 'modality')['canonical_symbol'] = 'F'
    decoded = subject.decode_proposal(subject.encode_proposal(changed, SOURCE), SOURCE)
    assert decoded['canonical_ir']['rules'][0]['modality'] == 'F'
    assert all(decoded[field] is False for field in FALSE_FIELDS)


def test_wire_rejects_unknown_authority_and_wrong_source():
    changed = wire()
    changed['accepted'] = True
    with pytest.raises(ValueError):
        subject.decode_proposal(tokens(changed), SOURCE)
    with pytest.raises(ValueError):
        subject.decode_proposal(tokens(), SOURCE + ' ')


def test_module_does_not_import_grammar_or_model_stack():
    code = '''
import sys
from ipfs_datasets_py.logic.legal_ir import canonical_byte_codec
assert not {'torch', 'transformers', 'spacy', 'numpy', 'llama_cpp'}.intersection(sys.modules)
assert not any(name.endswith(('canonical_source_grounding', 'canonical_explicit_qualifiers',
                             'legal_formula_codec')) for name in sys.modules)
'''
    subprocess.run([sys.executable, '-c', code], check=True)
