"""Scope contrasts cannot obtain correct labels from local clause differences."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as corpus


@pytest.fixture(scope='module')
def panels():
    return corpus.make_panels()


@pytest.mark.parametrize('panel,count', [('train', 192), ('tuning', 96), ('fresh', 192)])
def test_complete_balanced_scope_pairs(panels, panel, count):
    data, pairs, ledger = panels
    rows = data[panel]
    assert len(rows) == count and sum(r['supported'] for r in rows) == count // 2
    corpus.validate_pairs(rows, pairs[panel], count // 2)
    annotations = {a['candidate_id']: a for a in ledger['document_rows']}
    first_modalities = []
    ce_masks = []
    counts = []
    for pair in pairs[panel]:
        left, right = [annotations[pair[key]] for key in ('independent_id', 'nested_id')]
        lc, rc = left['local_clause_coordinates'], right['local_clause_coordinates']
        assert [r['source_text'] for r in lc] == [r['source_text'] for r in rc]
        assert [r['rule'] for r in lc] == [r['rule'] for r in rc]
        first_modalities.append(lc[0]['rule']['modality'])
        ce_masks.append(int(bool(lc[0]['rule']['conditions'])) + 2 * int(bool(lc[0]['rule']['exceptions'])))
        counts.append(len(lc))
    assert {m: first_modalities.count(m) for m in 'OPF'} == {m: count // 6 for m in 'OPF'}
    assert {m: ce_masks.count(m) for m in range(4)} == {m: count // 8 for m in range(4)}
    assert counts.count(2) == counts.count(3) == count // 4


def test_every_role_and_nested_attachment_directly_bound(panels):
    data, _, ledger = panels
    annotations = {r['candidate_id']: r for r in ledger['document_rows']}
    for rows in data.values():
        for row in rows:
            corpus.validate_document(row, annotations[row['candidate_id']])
            assert not corpus.boundary.UNSUPPORTED.search(row['source_text'])
            if not row['supported']: assert row['clauses'] == []


def test_entity_source_case_isolation_and_honest_mixed_layouts(panels):
    data, pairs, ledger = panels
    ann = {r['candidate_id']: r for r in ledger['document_rows']}
    source_sets = [{r['source_sha256'] for r in data[p]} for p in data]
    assert all(not a & b for i, a in enumerate(source_sets) for b in source_sets[i + 1:])
    case_sets = [{r['case_group'] for r in pairs[p]} for p in pairs]
    assert all(not a & b for i, a in enumerate(case_sets) for b in case_sets[i + 1:])
    layouts = {corpus.role_layout(r, ann[r['candidate_id']]) for r in data['train']}
    matching = [corpus.role_layout(r, ann[r['candidate_id']]) in layouts for r in data['fresh']]
    assert sum(matching) == len(matching) // 2


@pytest.mark.parametrize('change', ['hash', 'role_offset', 'attachment_offset', 'trigger_outside', 'invented_flat_targets'])
def test_reject_tampered_coordinates_or_unsupported_targets(change):
    rows, _, annotations = corpus.make_pair('train', 17)
    row, annotation = deepcopy(rows[1]), deepcopy(annotations[1])
    if change == 'hash': row['source_sha256'] = '0' * 64
    elif change == 'role_offset': annotation['local_clause_coordinates'][0]['facet_spans']['actor'][0] += 1
    elif change == 'attachment_offset': annotation['scope_attachment']['start_char'] += 1
    elif change == 'trigger_outside': annotation['local_clause_coordinates'][1]['trigger_span'] = annotation['local_clause_coordinates'][0]['trigger_span']
    else: row['clauses'] = deepcopy(rows[0]['clauses'])
    with pytest.raises(ValueError): corpus.validate_document(row, annotation)


@pytest.mark.parametrize('change', ['duplicate_pair', 'wrong_side', 'missing_row', 'wrong_local_hash', 'tuple_hashes', 'changed_nested_body', 'extra_metadata'])
def test_pair_membership_and_local_semantics_fail_closed(panels, change):
    rows, pairs = deepcopy(panels[0]['train']), deepcopy(panels[1]['train'])
    if change == 'duplicate_pair': pairs[-1] = deepcopy(pairs[0])
    elif change == 'wrong_side': pairs[0]['independent_id'], pairs[0]['nested_id'] = pairs[0]['nested_id'], pairs[0]['independent_id']
    elif change == 'missing_row': rows.pop()
    elif change == 'wrong_local_hash': pairs[0]['local_clause_body_sha256'][0] = '0' * 64
    elif change == 'tuple_hashes': pairs[0]['local_clause_body_sha256'] = tuple(pairs[0]['local_clause_body_sha256'])
    elif change == 'changed_nested_body': rows[1]['source_text'] = rows[1]['source_text'].replace('retain', 'delete', 1)
    else: pairs[0]['reference_meaning'] = 'invented'
    with pytest.raises(ValueError): corpus.validate_pairs(rows, pairs, 96)


def fixture_document(ordinal, prefix='Earlier'):
    supported = ordinal % 4 != 3
    body = f'{prefix}{ordinal} must retain records.'
    text = body if supported else 'Both following rules apply: ' + body
    rule = {'modality': 'O', 'actor': f'{prefix}{ordinal}', 'action': 'retain', 'object': 'records', 'conditions': [], 'exceptions': [], 'temporal': []}
    return {'candidate_id': f'{prefix}-{ordinal}', 'source_text': text, 'source_sha256': corpus.sha(text.encode()),
            'supported': supported, 'construction': 'fixture', 'repeated_rule_occurrences': False,
            'clauses': [{'char_start': 0, 'char_end': len(text), 'rule': rule}] if supported else [],
            'unsupported_reason': None if supported else 'shared_condition_prefix', 'label_origin': 'fixture'}


@pytest.fixture
def frozen_fixture(tmp_path, monkeypatch):
    refs = {}
    for name, count in (('original', 192), ('expanded', 384)):
        refs[name] = corpus.write_new(tmp_path / (name + '.json'), [fixture_document(i, name) for i in range(count)])
    retention = corpus.write_new(tmp_path / 'old-tune.json', [fixture_document(i, 'Tune') for i in range(48)])
    prior = corpus.write_new(tmp_path / 'prior.json', {'fixture': True})
    monkeypatch.setattr(corpus, 'historical_inventory', lambda *_: (refs, {'old': retention}, set(), [], 0))
    manifest = corpus.freeze(tmp_path / 'frozen', prior['path'], prior['path'])
    return Path(manifest['path'])


def test_training_loader_never_opens_sealed_labels_or_ledgers(frozen_fixture, monkeypatch):
    manifest = json.loads(frozen_fixture.read_text())
    sealed = {Path(manifest['artifacts'][key]['path']).resolve() for key in corpus.SEALED}
    original_open = Path.open
    attempted = []
    def checked(path, *args, **kwargs):
        if path.resolve() in sealed:
            attempted.append(str(path)); raise AssertionError('sealed read')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked)
    loaded = corpus.load_training_inputs(frozen_fixture)
    assert not attempted and len(loaded['fresh_sources']) == 192
    assert all(set(r) == corpus.SOURCE_KEYS for r in loaded['fresh_sources'])
    assert len(loaded['new_train']) == 192 and len(loaded['tuning']['old']) == 48


def test_manifest_count_tampering_rejected(frozen_fixture):
    manifest = json.loads(frozen_fixture.read_text()); manifest['counts']['fresh']['supported'] = 0
    frozen_fixture.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='counts'): corpus.load_training_inputs(frozen_fixture)


def test_source_tampering_rejected_even_with_updated_artifact_pin(frozen_fixture):
    manifest = json.loads(frozen_fixture.read_text()); path = Path(manifest['artifacts']['fresh_sources']['path'])
    rows = json.loads(path.read_text()); rows[0]['source_text'] += ' changed'; path.write_text(json.dumps(rows))
    manifest['artifacts']['fresh_sources'] = corpus.file_ref(path); frozen_fixture.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='hash'): corpus.load_training_inputs(frozen_fixture)
