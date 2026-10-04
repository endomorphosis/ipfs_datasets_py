"""Evaluation-only corpus checks; production holdout files are never test inputs."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import pytest
from scripts.ops.legal_ir import prepare_legal_scope_preservation_corpus as corpus

@pytest.fixture(scope='module')
def authored():
    return corpus.make_panels()


def test_only288_new_evaluation_documents_and_balanced_realized_factors(authored):
    panels, pairs, ledger, counts = authored
    assert set(panels) == {'tuning', 'fresh'} and len(ledger['document_rows']) == 288
    lookup = {a['candidate_id']: a for a in ledger['document_rows']}
    for panel, n in corpus.COUNTS.items():
        assert len(panels[panel]) == n and len(pairs[panel]) == n // 2
        assert counts[panel]['heading_literals'] == {'dash': n // 2, 'period_bracket': n // 2}
        for side in (True, False):
            labels = [lookup[r['candidate_id']] for r in panels[panel] if r['supported'] is side]
            for key, values in (('first_modality', 'OPF'), ('heading', corpus.HEADINGS),
                ('child_time_kind', corpus.TIME_KINDS), ('clause_count', (2, 3)), ('first_CE_mask', range(4))):
                assert Counter(a['factors'][key] for a in labels) == {v: n // (2 * len(values)) for v in values}
    with pytest.raises(ValueError): corpus.make_pair('train', 0)


def test_direct_offsets_paired_bodies_and_all_heading_time_count_crossings(authored):
    panels, pairs, ledger, _ = authored
    lookup = {a['candidate_id']: a for a in ledger['document_rows']}
    for panel, rows in panels.items():
        witnessed = set()
        corpus.validate_pairs(rows, pairs[panel], len(rows) // 2)
        for row in rows:
            a = lookup[row['candidate_id']]; corpus.validate_document(row, a)
            child = a['local_clause_coordinates'][1]
            assert child['source_text'].startswith(corpus.HEADINGS[a['factors']['heading']])
            witnessed.add(tuple(a['factors'][k] for k in ('first_modality','heading','child_time_kind','clause_count')))
            assert len(corpus.boundary.tokenize(row['source_text'])) <= 512
        assert len(witnessed) == 48
        for pair in pairs[panel]:
            left, right = (lookup[pair[k]] for k in ('independent_id', 'nested_id'))
            assert [o['source_text'] for o in left['local_clause_coordinates']] == [o['source_text'] for o in right['local_clause_coordinates']]
            assert [o['rule'] for o in left['local_clause_coordinates']] == [o['rule'] for o in right['local_clause_coordinates']]
            assert left['scope_attachment'] is None and right['scope_attachment']['child_occurrence'] == 1


def test_source_ids_metadata_order_and_split_isolation(authored):
    panels, pairs, ledger, _ = authored
    source_sets, meaning_sets, case_sets = [], [], []
    for panel, rows in panels.items():
        sources = [corpus.source_row(r) for r in rows]
        assert all(set(r) == {'candidate_id','source_text','source_sha256'} for r in sources)
        assert all(re.fullmatch(r'scope-[0-9a-f]{64}', r['candidate_id']) for r in sources)
        assert [r['supported'] for r in rows] != [i % 2 == 0 for i in range(len(rows))]
        source_sets.append({corpus.temporal.prior.normalized_source(r['source_text']) for r in rows})
        meaning_sets.append({corpus.boundary.digest(o['rule']) for a in ledger['document_rows'] if a['panel'] == panel for o in a['local_clause_coordinates']})
        case_sets.append({p['case_group'] for p in pairs[panel]})
    assert not source_sets[0] & source_sets[1] and not meaning_sets[0] & meaning_sets[1] and not case_sets[0] & case_sets[1]


def test_old_module_globals_and_train_rendering_unchanged():
    before = deepcopy((corpus.adapter.COUNTS, corpus.adapter.PREFIXES, corpus.adapter.make_pair('train', 0)))
    corpus.make_panels()
    assert before == (corpus.adapter.COUNTS, corpus.adapter.PREFIXES, corpus.adapter.make_pair('train', 0))


@pytest.mark.parametrize('mutation', ['identity_class','heading','time_kind','modality','mask','count','role_offset','role_atom','trigger','attachment','flat_guard','editorial_text','cue_owner'])
def test_annotation_tampering_rejected(mutation):
    case = next(i for i, f in enumerate(corpus.factor_schedule('tuning')) if f['first_CE_mask'] == 3 and f['child_time_kind'] == 'hours' and f['heading'] == 'period_bracket' and f['clause_count'] == 2)
    rows, _, labels = corpus.make_pair('tuning', case)
    row, label = deepcopy((rows[1], labels[1])); child = label['local_clause_coordinates'][1]
    if mutation == 'identity_class': row['candidate_id'] += '-nested'
    elif mutation == 'heading': label['factors']['heading'] = 'dash'
    elif mutation == 'time_kind': label['factors']['child_time_kind'] = 'days'
    elif mutation == 'modality': label['factors']['first_modality'] = next(x for x in 'OPF' if x != label['factors']['first_modality'])
    elif mutation == 'mask': label['factors']['first_CE_mask'] = 0
    elif mutation == 'count': label['factors']['clause_count'] = 3
    elif mutation == 'role_offset': child['facet_spans']['actor'][0] += 1
    elif mutation == 'role_atom': child['rule']['actor'] = 'another actor'
    elif mutation == 'trigger': child['trigger_span'][1] -= 1
    elif mutation == 'attachment': label['scope_attachment']['start_char'] += 1
    elif mutation == 'flat_guard': row['clauses'] = deepcopy(rows[0]['clauses'])
    elif mutation == 'editorial_text': child['editorial_context'][0]['source_text'] = 'Other heading.'
    else: child['qualifier_cues'][0]['end_char'] += 1
    with pytest.raises(ValueError): corpus.validate_document(row, label)


@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    path = tmp_path_factory.mktemp('scope-preservation') / 'corpus'
    pin = corpus.freeze(path)
    return pin, json.loads(Path(pin['path']).read_bytes())


def test_loader_reuses_all_train_refs_and_never_opens_new_sealed_files(frozen, monkeypatch):
    pin, manifest = frozen
    denied = {Path(manifest['artifacts'][k]['path']).resolve() for k in corpus.SEALED}
    original = Path.open; opened = []
    def guarded(path, *args, **kwargs):
        resolved = path.resolve(); opened.append(resolved)
        assert resolved not in denied, 'new sealed reference opened'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    loaded = corpus.load_training_inputs(pin['path'])
    parent = corpus.read_ref(manifest['inputs']['prior_adapter_corpus'])
    for k in ('new_training_targets','training_pairs','training_sources'):
        assert manifest['artifacts'][k] == parent['artifacts'][k]
    assert loaded['new_train'] == corpus.read_ref(parent['artifacts']['new_training_targets'])
    assert loaded['training_pairs'] == corpus.read_ref(parent['artifacts']['training_pairs'])
    assert sum(map(len,loaded['replay'].values())) == 768 and len(loaded['new_train']) == 384
    assert len(loaded['tuning']) == 18 and sum(map(len,loaded['tuning'].values())) == 1872
    assert {'prior_adapter_tuning','prior_adapter_fresh','scope_new'} <= set(loaded['tuning'])
    assert len(loaded['fresh_sources']) == 192 and not denied & set(opened)


def test_exposure_includes_all_released_prior_adapter_rows_without_new_train(frozen):
    _, manifest = frozen
    exposure = corpus.read_ref(manifest['artifacts']['exposure_audit'])
    for name, count in (('prior_adapter_train',384),('prior_adapter_tuning',96),('prior_adapter_fresh',192)):
        assert len(exposure['historical_layout_rows'][name]) == count
        assert exposure['historical_unannotated_unsupported_ids'][name] == []
    assert exposure['training_reused_without_new_examples'] is True
    assert 'new_train' not in exposure['known_role_masked_layouts']
    assert len(exposure['rows']) == 192 and exposure['new_source_overlap_count'] == 0
    assert manifest['new_training_documents'] == 0


@pytest.mark.parametrize('mutation', ['train_pin','replay_pin','retention_drop','source_label','counts'])
def test_loader_rejects_changed_admission_or_source_metadata(frozen,tmp_path,mutation):
    _, original = frozen; manifest = deepcopy(original)
    if mutation == 'train_pin': manifest['artifacts']['new_training_targets'] = manifest['artifacts']['tuning_targets']
    elif mutation == 'replay_pin': manifest['replay_references']['original'] = manifest['artifacts']['tuning_targets']
    elif mutation == 'retention_drop': del manifest['retention_target_references']['prior_adapter_fresh']
    elif mutation == 'counts': manifest['counts']['fresh']['documents'] = 96
    else:
        rows = corpus.read_ref(manifest['artifacts']['fresh_sources']); rows[0]['supported'] = True
        manifest['artifacts']['fresh_sources'] = corpus.write_new(tmp_path/'sources.json',rows)
    pin = corpus.write_new(tmp_path/'manifest.json',manifest)
    with pytest.raises(ValueError): corpus.load_training_inputs(pin['path'])


def test_freeze_refuses_overwrite(frozen):
    pin,_ = frozen
    with pytest.raises(ValueError,match='new output'): corpus.freeze(Path(pin['path']).parent)
