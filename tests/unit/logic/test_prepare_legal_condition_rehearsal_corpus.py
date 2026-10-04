"""Condition/time corpus integrity and source-only loading regression checks."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as c


@pytest.fixture(scope='module')
def inventory():
    return c.make_panels()


def test_condition_modal_temporal_balance_and_no_new_fit_data(inventory):
    panels, pairs, ledger = inventory
    assert set(panels) == set(c.COUNTS) and 'train' not in panels
    for panel in ('tuning', 'fresh'):
        count = len(panels[panel]); annotations = [a for a in ledger['single_rows'] if a['panel'] == panel]
        assert Counter(a['condition_cue'] for a in annotations) == {None: count//2, 'when': count//6, 'if': count//6, 'provided that': count//6}
        assert Counter(a['temporal_kind'] for a in annotations) == {None: count//2, 'before_calendar': count//4, 'within_days': count//8, 'within_hours': count//8}
        assert len(pairs[panel]) == count//2
        by_id = {r['id']: r for r in panels[panel]}
        for p in pairs[panel]:
            left, right = by_id[p['left_id']], by_id[p['right_id']]
            assert left['canonical_ir'] == right['canonical_ir'] and left['source_text'] != right['source_text']
        opaque = [r for r in panels[panel] if 'within ' in r['source_text'] and not r['canonical_ir']['rules'][0]['temporal']]
        assert len(opaque) == count//8
        for r in opaque:
            assert 'within ' in r['canonical_ir']['rules'][0]['conditions'][0]
    fresh = [a for a in ledger['single_rows'] if a['panel'] == 'fresh' and a['condition_present']]
    assert Counter(a['condition_placement'] for a in fresh) == dict.fromkeys(
        ('before_actor', 'between_actor_and_modal', 'between_modal_and_action', 'after_object'), 24)
    assert c.validate_panels(*inventory)['added_fitting_rows'] == 0


def test_documents_preserve_occurrences_offsets_and_unsupported_scope(inventory):
    panels, _, ledger = inventory
    by_id = {a['candidate_id']: a for a in ledger['document_rows']}
    for panel in ('document_tuning', 'document_fresh'):
        assert sum(len(r['clauses']) for r in panels[panel]) == 144
        assert sum(by_id[r['candidate_id']]['unique_rules'] for r in panels[panel]) == 132
        for r in panels[panel]:
            c.validate_document(r, by_id[r['candidate_id']])
            if r['supported']: assert 'provided that' not in r['source_text'].casefold()
            else: assert not r['clauses']
            for local in c.document_clause_rows([r], [by_id[r['candidate_id']]]): c.validate_row(local)


@pytest.mark.parametrize('mutation', ['trigger','facet','absent','force','identity','tuple_span'])
def test_invalid_coordinate_annotations_rejected(inventory, mutation):
    row = deepcopy(inventory[0]['tuning'][0])
    if mutation == 'trigger': row['trigger_span'][0] += 1
    elif mutation == 'facet': row['facet_spans']['actor'] = row['trigger_span']
    elif mutation == 'absent': row['facet_spans']['conditions'] = row['trigger_span']
    elif mutation == 'force': row['canonical_ir']['rules'][0]['modality'] = 'F'
    elif mutation == 'tuple_span': row['facet_spans']['actor'] = tuple(row['facet_spans']['actor'])
    else: row['id'] = 'unbound'
    with pytest.raises((ValueError, TypeError)): c.validate_row(row)


@pytest.mark.parametrize('field', ['source_sha256','presence_mask','side','role_masked_layout','case_group',
    'condition_present','condition_cue','condition_placement','temporal_present','temporal_kind','condition_owned_temporal_language'])
def test_ledger_mutations_rejected(inventory, field):
    panels, pairs, ledger = deepcopy(inventory)
    ledger['single_rows'][0][field] = 'tampered'
    with pytest.raises(ValueError): c.validate_panels(panels, pairs, ledger)


@pytest.mark.parametrize('mutation', ['offset','occurrences','unique_rules','repeatflag','supported','guard','index'])
def test_document_coordinate_and_scope_mutations_rejected(inventory, mutation):
    row = deepcopy(inventory[0]['document_tuning'][24])
    a = deepcopy(next(a for a in inventory[2]['document_rows'] if a['candidate_id'] == row['candidate_id']))
    if mutation == 'offset': a['clause_coordinates'][0]['facet_spans']['actor'][0] += 1
    elif mutation == 'occurrences': a['clause_occurrences'] += 1
    elif mutation == 'unique_rules': a['unique_rules'] += 1
    elif mutation == 'repeatflag': row['repeated_rule_occurrences'] = False
    elif mutation == 'supported': a['supported'] = False
    elif mutation == 'guard': a['guard'] = 'nested_normative_exception'
    else: a['clause_coordinates'][0]['clause_index'] += 1
    with pytest.raises(ValueError): c.validate_document(row, a)


def loader_fixture(tmp_path, inventory):
    def write(name, value):
        path = tmp_path/name; path.write_text(json.dumps(value)); return c.file_ref(path)
    panels, pairs, _ = inventory
    a = {'new_tuning': write('tune.json', panels['tuning']), 'tuning_pairs': write('pairs.json', pairs['tuning']),
        'challenge_sources': write('fresh.json', [{k:r[k] for k in ('id','source_text')} for r in panels['fresh']]),
        'document_challenge_sources': write('docs.json', [c.document_source(r) for r in panels['document_fresh']]),
        'document_tuning_sources': write('ds.json', [c.document_source(r) for r in panels['document_tuning']]),
        'document_tuning_targets': write('dt.json', panels['document_tuning'])}
    for key in c.SEALED: a[key] = {'path': str(tmp_path/(key+'.sealed.json')), 'bytes': 0, 'sha256': '0'*64}
    manifest = {'schema': c.SCHEMA, 'counts': c.COUNTS, 'frozen_before_training': True,
        'sealed_artifacts': list(c.SEALED), 'generator': c.file_ref(c.__file__), 'inputs': {}, 'dependencies': {}, 'artifacts': a}
    path = Path(write('manifest.json', manifest)['path'])
    return path, manifest


def test_loader_has_zero_sealed_reads_and_adds_no_fitting_rows(tmp_path, inventory, monkeypatch):
    path, manifest = loader_fixture(tmp_path, inventory)
    forbidden = {manifest['artifacts'][k]['path'] for k in c.SEALED}
    original, opened = Path.open, []
    def tracked(self, *args, **kwargs):
        opened.append(str(self)); assert str(self) not in forbidden
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', tracked)
    result = c.load_training_inputs(path)
    assert 'new_train' not in result and len(result['new_tuning']) == 96
    assert len(result['fresh_sources']) == 192 and len(result['fresh_document_sources']) == 96
    assert not forbidden & set(opened)


@pytest.mark.parametrize('key', ['challenge_sources', 'document_challenge_sources'])
def test_recommitted_duplicate_sources_rejected(tmp_path, inventory, key):
    path, manifest = loader_fixture(tmp_path, inventory)
    source = Path(manifest['artifacts'][key]['path']); rows = json.loads(source.read_bytes()); rows[1] = rows[0]
    source.write_text(json.dumps(rows)); manifest['artifacts'][key] = c.file_ref(source); path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='overlap'): c.load_training_inputs(path)


def test_supported_temporal_and_opaque_condition_forms_lower(inventory):
    from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
    from ipfs_datasets_py.logic.autoformal import legal_canonical_calendar as bridge
    selected = {}
    for row in inventory[0]['tuning']:
        metadata = c.condition_metadata(row)
        kind = metadata['temporal_kind'] or ('opaque' if metadata['condition_owned_temporal_language'] else 'none')
        selected.setdefault(kind, row)
    assert set(selected) == {'within_days', 'within_hours', 'before_calendar', 'opaque', 'none'}
    for row in selected.values():
        candidate = {'candidate_id': row['id'], 'source_text': row['source_text'],
            'source_sha256': c.sha(row['source_text'].encode()), 'canonical_ir': row['canonical_ir']}
        interpretation = calendar.synthetic_interpretation(candidate, policy=calendar.POLICY)
        assert bridge.prepare_canonical_qualified(candidate, interpretation)


def test_historical_pool_names_cannot_replace_prior_temporal_tuning(tmp_path, monkeypatch):
    def write(name, value):
        p = tmp_path/name; p.write_text(json.dumps(value)); return c.file_ref(p)
    old_row = {'source_text': 'old temporal tuning source'}
    new_row = {'source_text': 'new temporal presence tuning source'}
    artifacts = {k: write(k+'.json', [new_row]) for k in ('new_training','new_tuning','challenge_targets')}
    artifacts.update({k: write(k+'.json', []) for k in ('document_tuning_targets','document_challenge_targets')})
    manifest = write('manifest.json', {'inputs': {'prior_corpus': {'path': 'older'}}, 'artifacts': artifacts})
    monkeypatch.setattr(c.previous, 'historical_inputs', lambda _: (None, {'temporal_tuning': [old_row]}, set(), {}, {}, 0))
    _, pools, excluded, _, _, _ = c.historical_inputs(manifest['path'])
    assert pools['temporal_tuning'] == [old_row]
    assert pools['temporal_presence_tuning'] == [new_row]
    assert excluded == {old_row['source_text'], new_row['source_text']}
