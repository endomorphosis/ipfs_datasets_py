"""Balanced qualifier supervision, exact occurrence provenance, and sealed IO."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts.ops.legal_ir import prepare_legal_facet_retention_corpus as corpus


@pytest.fixture(scope='module')
def inventory():
    return corpus.make_panels()


def test_exact_inventory_all8_masks_crossed_with_three_modalities(inventory):
    panels, pairs, ledger = inventory
    assert {k: len(v) for k,v in panels.items()} == corpus.COUNTS
    for panel in corpus.SINGLE_COUNTS:
        count = len(panels[panel])
        actual = Counter()
        for row in panels[panel]:
            rule = row['canonical_ir']['rules'][0]
            mask = sum(1 << bit for bit, f in enumerate(corpus.FIELDS[3:]) if rule[f])
            actual[(rule['modality'], mask)] += 1
        assert actual == {(m, mask): count // 24 for m in 'OPF' for mask in range(8)}
        assert len(pairs[panel]) == count // 2
    assert len(ledger['single_rows']) == 1152 and len(ledger['document_rows']) == 192


def test_every_single_span_is_exact_and_pair_meanings_identical(inventory):
    panels, pairs, _ = inventory
    for panel in corpus.SINGLE_COUNTS:
        by_id = {r['id']: r for r in panels[panel]}
        for row in by_id.values(): corpus.validate_row(row)
        for pair in pairs[panel]:
            left, right = by_id[pair['left_id']], by_id[pair['right_id']]
            assert left['canonical_ir'] == right['canonical_ir']
            assert left['source_text'] != right['source_text']
            assert pair['canonical_ir_sha256'] == corpus.sha(corpus.prior.canonical_bytes(left['canonical_ir']))
        assert len({p['case_group'] for p in pairs[panel]}) == len(pairs[panel])


def test_all_basic_qualifier_cues_trained_at_multiple_positions(inventory):
    panels, _, ledger = inventory
    rows = {r['id']: r for r in panels['train']}
    positions = {cue: set() for cue in corpus.CONDITION_CUES + corpus.EXCEPTION_CUES}
    for a in ledger['single_rows']:
        if a['panel'] != 'train': continue
        row = rows[a['id']]
        for q in a['qualifier_cues']:
            cue = q['source_text'].strip().casefold()
            start, end = q['start_char'], q['end_char']
            assert row['source_text'][start:end] == q['source_text']
            assert end == row['facet_spans'][q['field']][0]
            positions[cue].add('front' if start < row['facet_spans']['actor'][0]
                else 'suffix' if start > row['facet_spans']['object'][1] else 'infix')
    assert all(len(values) >= 2 for values in positions.values())


def test_headings_dates_extent_editorial_are_explicit_and_optional(inventory):
    panels, _, ledger = inventory
    rows = {r['id']: r for p in corpus.SINGLE_COUNTS for r in panels[p]}
    for a in ledger['single_rows']:
        row = rows[a['id']]
        for note in a['editorial_context']:
            assert row['source_text'][note['start_char']:note['end_char']] == note['source_text']
            assert note['author_stipulated_role'] == 'nonoperative_editorial_context'
            for span in row['facet_spans'].values():
                if span: assert span[1] <= note['start_char'] or span[0] >= note['end_char']
    for family in corpus.FAMILIES:
        labels = [a for a in ledger['single_rows'] if a['panel'] == 'train' and a['family'] == family]
        assert set(a['presence_mask'] for a in labels) == set(range(8))
    assert any('provided that' in r['source_text'] for r in panels['train'])
    assert all('provided that' not in r['source_text'].casefold() for p in ('document_tuning','document_fresh') for r in panels[p] if r['supported'])


def test_shared_layout_controls_and_unmatched_combinations_not_all_novel(inventory):
    panels, _, _ = inventory
    train = {corpus.role_layout(r) for r in panels['train']}
    statuses = [corpus.role_layout(r) in train for r in panels['fresh']]
    assert any(statuses) and not all(statuses)
    assert all(corpus.role_layout(r) in train for r in panels['fresh'][::2])


def test_case_source_meaning_isolation_does_not_claim_grammar_isolation(inventory):
    panels,pairs,ledger = inventory
    audit = corpus.validate_panels(panels,pairs,ledger)
    assert audit['cross_split_source_overlap'] == audit['cross_split_meaning_overlap'] == audit['cross_split_case_overlap'] == 0
    assert audit['case_groups'] == 768
    assert 'Shared grammar' in audit['layout_policy']
    assert 'shared core role/action vocabulary' in audit['lexical_policy']


def test_document_occurrences_guards_and_duplicates_have_separate_counts(inventory):
    panels,_,ledger = inventory
    by_id = {a['candidate_id']: a for a in ledger['document_rows']}
    for panel in ('document_tuning','document_fresh'):
        rows = panels[panel]
        assert Counter(len(r['clauses']) for r in rows if r['supported']) == {1:24,2:24,3:24}
        assert sum(len(r['clauses']) for r in rows) == 144
        assert sum(by_id[r['candidate_id']]['unique_rules'] for r in rows) == 132
        assert sum(r['repeated_rule_occurrences'] for r in rows) == 12
        assert Counter(r['unsupported_reason'] for r in rows if not r['supported']) == {g:8 for g in corpus.GUARDS}
        for row in rows:
            a = by_id[row['candidate_id']]
            corpus.validate_document(row,a)
            if not row['supported']:
                assert row['clauses'] == a['clause_coordinates'] == []
            for clause, coords in zip(row['clauses'], a['clause_coordinates'], strict=True):
                for field, span in coords['facet_spans'].items():
                    value = clause['rule'][field]
                    if isinstance(value,list): value = value[0] if value else None
                    if span: assert row['source_text'][slice(*span)] == value


def test_modal_spelling_is_not_layout_novelty():
    a,_ = corpus.render('train','front_exception',2,0,0)
    b = deepcopy(a)
    start,end = b['trigger_span']; text = b['source_text']
    # Skeleton does not use trigger offsets; replace a modal after all facet spans
    # have been recomputed by the independent renderer.
    b,_ = corpus.render('train','front_exception',2,0,1)
    assert 'must not' in a['source_text'] and 'may not' in b['source_text']
    assert corpus.role_layout(a) == corpus.role_layout(b)


@pytest.mark.parametrize('mutation', ['trigger','facet','absent','force','identity','tuple_span'])
def test_invalid_annotations_rejected(inventory,mutation):
    row = deepcopy(inventory[0]['train'][0])
    if mutation == 'trigger': row['trigger_span'][0] += 1
    elif mutation == 'facet': row['facet_spans']['actor'] = row['trigger_span']
    elif mutation == 'absent': row['facet_spans']['conditions'] = row['trigger_span']
    elif mutation == 'force': row['canonical_ir']['rules'][0]['modality'] = 'F'
    elif mutation == 'tuple_span': row['facet_spans']['actor'] = tuple(row['facet_spans']['actor'])
    else: row['id'] = 'facet-train-invalid'
    with pytest.raises((ValueError,TypeError)): corpus.validate_row(row)


@pytest.mark.parametrize('mutation', ['tuple','missing','duplicate_row','semantic','case'])
def test_malformed_pairs_rejected(inventory,mutation):
    rows,pairs = deepcopy(inventory[0]['train']),deepcopy(inventory[1]['train'])
    if mutation == 'tuple': pairs = tuple(pairs)
    elif mutation == 'missing': pairs[0].pop('left_id')
    elif mutation == 'duplicate_row': pairs[1]['left_id'] = pairs[0]['left_id']
    elif mutation == 'semantic': rows[1]['canonical_ir']['rules'][0]['modality'] = 'P'
    else: pairs[1]['case_group'] = pairs[0]['case_group']
    with pytest.raises((ValueError,KeyError)): corpus.validate_pairs(rows,pairs,384)


@pytest.mark.parametrize('mutation',['offset','occurrences','unique_rules','repeatflag'])
def test_document_coordinate_or_occurrence_drift_rejected(inventory,mutation):
    row = deepcopy(inventory[0]['document_tuning'][24])
    a = deepcopy(next(a for a in inventory[2]['document_rows'] if a['candidate_id'] == row['candidate_id']))
    if mutation == 'offset': a['clause_coordinates'][0]['facet_spans']['actor'][0] += 1
    elif mutation == 'occurrences': a['clause_occurrences'] += 1
    elif mutation == 'unique_rules': a['unique_rules'] += 1
    else: row['repeated_rule_occurrences'] = False
    with pytest.raises(ValueError): corpus.validate_document(row,a)


@pytest.mark.parametrize('mutation',['hash','mask','pairside','template','case'])
def test_ledger_binding_cannot_drift(inventory,mutation):
    panels,pairs,ledger = deepcopy(inventory)
    a = ledger['single_rows'][0]
    if mutation == 'hash': a['source_sha256'] = '0'*64
    elif mutation == 'mask': a['presence_mask'] = 7
    elif mutation == 'pairside': a['side'] = 1
    elif mutation == 'template': a['template'] = 'fake novel layout'
    else: a['case_group'] = 'other-case'
    with pytest.raises(ValueError): corpus.validate_panels(panels,pairs,ledger)


def loader_fixture(tmp_path,inventory,monkeypatch):
    def write(name,value):
        path = tmp_path/name; path.write_text(json.dumps(value)); return corpus.file_ref(path)
    panels,pairs,_ = inventory
    artifacts = {
        'new_training':write('train.json',panels['train']), 'training_pairs':write('train-pairs.json',pairs['train']),
        'new_tuning':write('tune.json',panels['tuning']), 'tuning_pairs':write('tune-pairs.json',pairs['tuning']),
        'challenge_sources':write('fresh-sources.json',[{k:r[k] for k in ('id','source_text')} for r in panels['fresh']]),
        'document_challenge_sources':write('doc-sources.json',[corpus.document_source(r) for r in panels['document_fresh']]),
        'document_tuning_sources':write('doc-tune-sources.json',[corpus.document_source(r) for r in panels['document_tuning']]),
        'document_tuning_targets':write('doc-tune.json',panels['document_tuning'])}
    for key in corpus.SEALED:
        artifacts[key] = {'path':str(tmp_path/(key+'.sealed.json')),'sha256':'0'*64,'bytes':0}
    monkeypatch.setattr(corpus.previous,'load_training_inputs',lambda _: {'replay':{},'tuning':{},'new_train':[],'new_tuning':[]})
    manifest = {'schema':corpus.SCHEMA,'frozen_before_training':True,'counts':corpus.COUNTS,
        'sealed_artifacts':list(corpus.SEALED),'generator':corpus.file_ref(corpus.__file__),
        'dependencies':{},'inputs':{'prior_corpus':write('prior.json',{})},'artifacts':artifacts}
    ref = write('manifest.json',manifest)
    return Path(ref['path']),manifest


def test_loader_has_zero_sealed_reads_and_closed_source_only_rows(tmp_path,inventory,monkeypatch):
    path,manifest = loader_fixture(tmp_path,inventory,monkeypatch)
    forbidden = {manifest['artifacts'][k]['path'] for k in corpus.SEALED}
    original,opened = Path.open,[]
    def tracked(self,*args,**kwargs):
        opened.append(str(self)); assert str(self) not in forbidden
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',tracked)
    value = corpus.load_training_inputs(path)
    assert len(value['new_train']) == 768 and len(value['new_tuning']) == 192
    assert len(value['fresh_sources']) == 192 and len(value['fresh_document_sources']) == 96
    assert len(value['document_tuning']) == 96
    assert all(set(r) == {'id','source_text'} for r in value['fresh_sources'])
    assert not forbidden & set(opened)


@pytest.mark.parametrize('field',['counts','sealed_artifacts'])
def test_loader_denominator_or_seal_drift_rejected(tmp_path,inventory,monkeypatch,field):
    path,manifest = loader_fixture(tmp_path,inventory,monkeypatch)
    manifest[field] = {} if field == 'counts' else []
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='denominators or seal'): corpus.load_training_inputs(path)


@pytest.mark.parametrize('key',['challenge_sources','document_challenge_sources'])
def test_loader_recommitted_duplicate_fresh_sources_rejected(tmp_path,inventory,monkeypatch,key):
    path,manifest = loader_fixture(tmp_path,inventory,monkeypatch)
    source_path = Path(manifest['artifacts'][key]['path']); rows = json.loads(source_path.read_bytes()); rows[1] = rows[0]
    source_path.write_text(json.dumps(rows)); manifest['artifacts'][key] = corpus.file_ref(source_path)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='duplicate or overlap'): corpus.load_training_inputs(path)
