from collections import Counter
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import re

import pytest

from scripts.ops.legal_ir import prepare_legal_scope_adapter_corpus as corpus


@pytest.fixture(scope='module')
def authored():
    return corpus.make_panels()


def test_exact_full_train_factorial_and_balanced_split_margins(authored):
    panels, pairs, ledger, counts = authored
    lookup = {a['candidate_id']: a for a in ledger['document_rows']}
    expected = set(product('OPF', corpus.HEADINGS, corpus.TIME_KINDS, (2, 3), range(4)))
    actual = {tuple(lookup[p['independent_id']]['factors'][k] for k in
        ('first_modality', 'heading', 'child_time_kind', 'clause_count', 'first_CE_mask')) for p in pairs['train']}
    assert actual == expected and len(actual) == 192
    for panel, n in corpus.COUNTS.items():
        assert len(panels[panel]) == n and len(pairs[panel]) == n // 2
        assert counts[panel]['supported'] == counts[panel]['unsupported'] == n // 2
        assert counts[panel]['heading_literals'] == {'dash': n // 2, 'period_bracket': n // 2}
        for side in (True, False):
            labels = [lookup[r['candidate_id']] for r in panels[panel] if r['supported'] is side]
            for key, values in (('first_modality', 'OPF'), ('heading', corpus.HEADINGS),
                ('child_time_kind', corpus.TIME_KINDS), ('clause_count', (2, 3)), ('first_CE_mask', range(4))):
                assert Counter(a['factors'][key] for a in labels) == {v: n // (2 * len(values)) for v in values}


def test_both_rendered_heading_branches_cross_every_train_factor(authored):
    panels, pairs, ledger, _ = authored
    lookup = {a['candidate_id']: a for a in ledger['document_rows']}
    witnessed = set()
    for p in pairs['train']:
        a = lookup[p['independent_id']]; child = a['local_clause_coordinates'][1]
        heading = child['editorial_context'][0]
        assert child['source_text'].startswith(corpus.HEADINGS[a['factors']['heading']])
        assert heading['source_text'] == corpus.HEADINGS[a['factors']['heading']]
        witnessed.add(tuple(a['factors'][k] for k in ('heading', 'child_time_kind', 'clause_count', 'first_modality', 'first_CE_mask')))
    assert len(witnessed) == 192


def test_complete_direct_annotations_and_same_body_opposite_scope_pairs(authored):
    panels, pairs, ledger, _ = authored
    lookup = {a['candidate_id']: a for a in ledger['document_rows']}
    for panel, rows in panels.items():
        corpus.validate_pairs(rows, pairs[panel], len(rows) // 2)
        for row in rows:
            corpus.validate_document(row, lookup[row['candidate_id']])
            assert not corpus.boundary.UNSUPPORTED.search(row['source_text'])
            assert len(corpus.boundary.tokenize(row['source_text'])) <= 512
        for pair in pairs[panel]:
            left, right = (lookup[pair[k]] for k in ('independent_id', 'nested_id'))
            assert left['factors'] == right['factors']
            assert [o['source_text'] for o in left['local_clause_coordinates']] == [o['source_text'] for o in right['local_clause_coordinates']]
            assert [o['rule'] for o in left['local_clause_coordinates']] == [o['rule'] for o in right['local_clause_coordinates']]
            assert left['scope_attachment'] is None and right['scope_attachment']['child_occurrence'] == 1


def test_sources_have_opaque_ids_no_label_case_or_pair_metadata_and_shuffled_order(authored):
    panels, _, _, _ = authored
    for rows in panels.values():
        values = [corpus.source_row(r) for r in rows]
        assert all(set(r) == {'candidate_id', 'source_text', 'source_sha256'} for r in values)
        assert all(re.fullmatch(r'scope-[0-9a-f]{64}', r['candidate_id']) for r in values)
        assert all(r['candidate_id'] == 'scope-' + corpus.sha(r['source_text'].encode()) for r in values)
        assert all('independent' not in r['candidate_id'] and 'nested' not in r['candidate_id'] for r in values)
        labels = [r['supported'] for r in rows]
        assert labels != [i % 2 == 0 for i in range(len(rows))]
        assert labels != sorted(labels)


def test_source_local_meaning_and_case_groups_do_not_cross_splits(authored):
    panels, pairs, ledger, _ = authored
    sets = {}
    for panel, rows in panels.items():
        sets[panel] = ({corpus.temporal.prior.normalized_source(r['source_text']) for r in rows},
            {p['case_group'] for p in pairs[panel]},
            {corpus.boundary.digest(o['rule']) for a in ledger['document_rows'] if a['panel'] == panel for o in a['local_clause_coordinates']})
    for i, left in enumerate(sets):
        for right in list(sets)[i + 1:]:
            assert all(not a & b for a, b in zip(sets[left], sets[right]))


@pytest.mark.parametrize('mutation', ['identity_class', 'heading', 'time_kind', 'modality', 'mask', 'count',
    'role_offset', 'role_atom', 'trigger', 'attachment', 'flat_guard', 'editorial_text', 'cue_owner'])
def test_annotation_and_source_tampering_fail_closed(mutation):
    case = next(i for i, f in enumerate(corpus.factor_schedule('train'))
        if f['first_CE_mask'] == 3 and f['child_time_kind'] == 'hours' and f['heading'] == 'period_bracket')
    rows, _, labels = corpus.make_pair('train', case)
    row, label = deepcopy((rows[1], labels[1]))
    child = label['local_clause_coordinates'][1]
    if mutation == 'identity_class': row['candidate_id'] += '-nested'
    elif mutation == 'heading': label['factors']['heading'] = 'dash'
    elif mutation == 'time_kind': label['factors']['child_time_kind'] = 'days'
    elif mutation == 'modality': label['factors']['first_modality'] = 'P'
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


@pytest.mark.parametrize('mutation', ['membership', 'body_hash', 'extra_key', 'same_label', 'duplicate_case', 'body'])
def test_pair_membership_and_exact_local_body_tampering_fail_closed(mutation):
    a = corpus.make_pair('tuning', 0); b = corpus.make_pair('tuning', 1)
    rows, pairs = deepcopy((a[0] + b[0], [a[1], b[1]]))
    if mutation == 'membership': pairs[0]['nested_id'] = pairs[1]['nested_id']
    elif mutation == 'body_hash': pairs[0]['local_clause_body_sha256'][0] = '0' * 64
    elif mutation == 'extra_key': pairs[0]['labels'] = True
    elif mutation == 'same_label': rows[1]['supported'] = True
    elif mutation == 'duplicate_case': pairs[1]['case_group'] = pairs[0]['case_group']
    else: rows[1]['source_text'] = rows[1]['source_text'].replace('filing', 'archive', 1)
    with pytest.raises(ValueError): corpus.validate_pairs(rows, pairs, 2)


@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    path = tmp_path_factory.mktemp('scope-adapter') / 'corpus'
    ref = corpus.freeze(path)
    return ref, json.loads(Path(ref['path']).read_bytes())


def test_full_materialized_loader_pins_replay_and_never_opens_new_sealed_files(frozen, monkeypatch):
    ref, manifest = frozen
    denied = {Path(manifest['artifacts'][k]['path']).resolve() for k in corpus.SEALED}
    original = Path.open; opened = []
    def guarded(path, *args, **kwargs):
        resolved = path.resolve(); opened.append(resolved)
        assert resolved not in denied, 'new sealed reference opened by training loader'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    loaded = corpus.load_training_inputs(ref['path'])
    assert len(loaded['new_train']) == 384 and len(loaded['training_pairs']) == 192
    assert len(loaded['new_tuning']) == 96 and len(loaded['fresh_sources']) == 192
    assert {k: len(v) for k, v in loaded['replay'].items()} == {'original': 192, 'expanded': 384, 'prior_scope': 192}
    assert len(loaded['tuning']) == 12 and not denied & set(opened)


def test_prior_released_scope_fresh_is_explicitly_exposed_and_guard_layout_gaps_disclosed(frozen):
    _, manifest = frozen
    exposure = corpus.read_ref(manifest['artifacts']['exposure_audit'])
    assert 'prior_scope_exposed_fresh' in exposure['historical_document_references']
    assert len(exposure['historical_layout_rows']['prior_scope_exposed_fresh']) == 192
    assert exposure['historical_unannotated_unsupported_ids']['prior_scope_exposed_fresh'] == []
    assert any(exposure['historical_unannotated_unsupported_ids'].values())
    assert len(exposure['rows']) == 192 and exposure['new_source_overlap_count'] == 0
    assert set(exposure['known_role_masked_layouts']) >= {'new_train', 'new_tuning', 'prior_scope_exposed_fresh'}


def test_loader_rejects_source_metadata_leakage_even_with_repaired_file_hash(frozen, tmp_path):
    _, manifest = frozen
    modified = deepcopy(manifest)
    sources = corpus.read_ref(manifest['artifacts']['fresh_sources'])
    sources[0]['supported'] = True
    source_ref = corpus.write_new(tmp_path / 'sources.json', sources)
    modified['artifacts']['fresh_sources'] = source_ref
    new_ref = corpus.write_new(tmp_path / 'manifest.json', modified)
    with pytest.raises(ValueError): corpus.load_training_inputs(new_ref['path'])


def test_freeze_refuses_to_overwrite(frozen):
    ref, _ = frozen
    with pytest.raises(ValueError, match='new output'): corpus.freeze(Path(ref['path']).parent)
