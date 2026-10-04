from collections import Counter
from copy import deepcopy
import builtins
import io
import json
from pathlib import Path
import re
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_pointer_corpus as c

@pytest.fixture(scope='module')
def panels():
    return {split: c.make_panel(split) for split in c.UNITS}

@pytest.mark.parametrize('split', list(c.UNITS))
def test_complete_balanced_new_sources_and_exact_anchors(panels, split):
    rows, units = panels[split]
    assert len(rows) == 144 and len(units) == 12
    assert Counter(r['label'] for r in rows) == Counter({label: 36 for label in c.LABELS})
    targets = [c.project_reference(r) for r in rows]
    assert sum(r['owner_anchor_span'] is None for r in targets) == 36
    assert len({r['source_sha256'] for r in rows}) == 60
    assert all(set(c.source_row(r)) == c.SOURCE_KEYS for r in rows)
    c.validate_query_inventory([c.source_row(r) for r in rows], expected=144)
    assert all(len(re.findall(r'\w+|[^\w\s]', r['source_text'])) <= 256 for r in rows)

@pytest.mark.parametrize('module', [c.old, c.paired, c.previous, c.stability])
def test_legacy_reference_schema_normalization(module):
    rows = module.make_group('train', 0) if module is c.old else module.render_source('fresh_lexical' if module is c.stability else 'train', 0, 0)
    for row in rows:
        target = c.project_reference(row)
        assert set(target) == c.TARGET_KEYS
        if target['label'] != 'ambiguous':
            span = row['annotation']['owner_candidates'][0]['anchor_span']
            assert target['owner_anchor_span'] == {k: span[k] for k in ('char_start', 'char_end')}

def test_explicit_repeated_norm_time_selects_exact_later_anchor(panels):
    repeated = [r for r in panels['fresh_structural'][0] if r['label'] == 'norm' and len(r['annotation']['norm_occurrences']) > 1]
    assert repeated
    later = next(r for r in repeated if r['annotation']['norm_occurrences'][0]['time_span']['char_start'] != r['proposed_time_span']['char_start'])
    result = c.project_reference(later)
    assert result['owner_anchor_span']['char_start'] != later['annotation']['norm_occurrences'][0]['action_span']['char_start']

@pytest.mark.parametrize('mutation', ['multiple_candidates', 'wrong_type', 'wrong_norm_time', 'first_norm_action', 'duplicate_norm_time'])
def test_unique_reference_never_arbitrarily_picks_first(panels, mutation):
    row = deepcopy(next(r for r in panels['fresh_structural'][0] if r['label'] == 'norm' and len(r['annotation']['norm_occurrences']) > 1 and r['annotation']['norm_occurrences'][0]['time_span']['char_start'] != r['proposed_time_span']['char_start']))
    a = row['annotation']
    if mutation == 'multiple_candidates':
        extra = deepcopy(a['owner_candidates'][0]); extra['anchor_span'] = deepcopy(a['norm_occurrences'][0]['action_span']); a['owner_candidates'].append(extra)
    elif mutation == 'wrong_type': a['owner_candidates'][0]['owner_type'] = 'condition'
    elif mutation == 'wrong_norm_time':
        for norm in a['norm_occurrences']: norm['time_span'] = None
    elif mutation == 'first_norm_action': a['owner_candidates'][0]['anchor_span'] = deepcopy(a['norm_occurrences'][0]['action_span'])
    else:
        match = next(n for n in a['norm_occurrences'] if n['time_span']['char_start'] == row['proposed_time_span']['char_start']); a['norm_occurrences'].append(deepcopy(match))
    with pytest.raises(ValueError): c.project_reference(row, reconstruct=False)

@pytest.mark.parametrize('mutation', ['one_alternative', 'duplicate_alternative', 'missing_countermodel', 'selected_anchor'])
def test_ambiguity_preserves_null_and_distinct_reference_alternatives(panels, mutation):
    row = deepcopy(next(r for r in panels['fresh_lexical'][0] if r['label'] == 'ambiguous'))
    if mutation == 'selected_anchor':
        target = c.project_reference(row); target['owner_anchor_span'] = {'char_start': 0, 'char_end': 10}
        with pytest.raises(ValueError): c.validate_target(target)
        return
    if mutation == 'one_alternative': row['annotation']['owner_candidates'] = row['annotation']['owner_candidates'][:1]
    if mutation == 'duplicate_alternative': row['annotation']['owner_candidates'] = [row['annotation']['owner_candidates'][0]] * 2
    if mutation == 'missing_countermodel': row['annotation']['countermodels'] = None
    with pytest.raises(ValueError): c.project_reference(row, reconstruct=False)

@pytest.mark.parametrize('mutation', ['bool', 'float', 'partial_token', 'query_overlap', 'extra_key', 'source_hash'])
def test_closed_pointer_schema_and_token_integrity(panels, mutation):
    row = c.project_reference(next(r for r in panels['fresh_lexical'][0] if r['label'] == 'condition'))
    if mutation == 'bool': row['owner_anchor_span']['char_start'] = True
    elif mutation == 'float': row['owner_anchor_span']['char_end'] = float(row['owner_anchor_span']['char_end'])
    elif mutation == 'partial_token': row['owner_anchor_span']['char_start'] += 1
    elif mutation == 'query_overlap': row['owner_anchor_span'] = deepcopy(row['proposed_time_span'])
    elif mutation == 'extra_key': row['owner_candidates'] = []
    else: row['source_sha256'] = '0' * 64
    with pytest.raises(ValueError): c.validate_target(row)

def test_no_gold_anchor_width_cap():
    text = 'a ' * 40 + 'shall file within 15 days of notice.'
    row = {**c.query(text, c.propose_time_spans(text)[0]), 'label': 'norm', 'group_id': 'fictional', 'owner_anchor_span': {'char_start': 0, 'char_end': 79}}
    assert c.validate_target(row) == row

def test_repaired_target_hash_cannot_change_authoritative_anchor(panels):
    original = next(r for r in panels['fresh_lexical'][0] if r['label'] == 'condition')
    target = c.project_reference(original)
    alternative = next(x['span'] for x in original['annotation']['source_role_spans'] if x['role'] == 'action')
    target['owner_anchor_span'] = {k: alternative[k] for k in ('char_start', 'char_end')}
    c.validate_target(target)
    with pytest.raises(ValueError, match='authoritative'): c.validate_mapping([target], [original])

def test_producer_reconstruction_rejects_repaired_reference(panels):
    row = deepcopy(panels['fresh_lexical'][0][0]); row['annotation']['modality'] = 'invented'
    with pytest.raises(ValueError, match='insertion'): c.project_reference(row)

@pytest.mark.parametrize('assertion', [False, 1, None])
def test_exact_reference_uniqueness_assertion_required(panels, assertion):
    row = deepcopy(next(r for r in panels['fresh_lexical'][0] if r['label'] == 'norm'))
    row['annotation']['unique_owner_occurrence_asserted'] = assertion
    with pytest.raises(ValueError, match='explicitly'): c.project_reference(row, reconstruct=False)

def test_declared_shared_grammar_matches_old_stability_layouts(panels):
    known = {c.stability.body_layout(r) for split in c.stability.UNITS for r in c.stability.make_panel(split)[0]}
    assert all(c.stability.body_layout(r) in known for rows, _ in panels.values() for r in rows)
    assert c._fixed_manifest()['structural_novelty_claimed'] is False

@pytest.fixture
def miniature_admitted(monkeypatch, tmp_path):
    # Fictional fixture; no saved reference file enters the fitting-loader test.
    train = c.old.make_group('train', 0); tuning = c.old.make_group('tuning', 0)
    retained = {name: c.old.make_group('fresh', index) for index, name in enumerate(c.RETENTION)}
    data = {'training': train, 'tuning': tuning, 'retention': retained, 'history': {'training': train, 'selection': tuning, **retained}, 'historical_source_packs': []}
    monkeypatch.setattr(c, 'admitted_inputs', lambda _: deepcopy(data))
    prior = tmp_path / 'fictional-prior.json'; prior.write_text('{}')
    return data, prior

def test_source_only_loader_never_opens_four_sealed_paths(miniature_admitted, tmp_path, monkeypatch):
    data, prior = miniature_admitted; result = c.build_corpus(tmp_path / 'corpus', prior)
    manifest = c.read_ref(result['manifest']); denied = {manifest['artifacts'][k]['path'] for k in c.SEALED}
    original_builtin, original_io = builtins.open, io.open; attempts = []
    def guarded(original):
        def call(path, *args, **kwargs):
            if isinstance(path, (str, Path)) and str(Path(path).resolve()) in denied:
                attempts.append(str(path)); raise AssertionError('sealed reference opened')
            return original(path, *args, **kwargs)
        return call
    monkeypatch.setattr(builtins, 'open', guarded(original_builtin)); monkeypatch.setattr(io, 'open', guarded(original_io))
    loaded = c.load_training_inputs(result['manifest']['path'])
    assert attempts == [] and loaded['training'] == [c.project_reference(r) for r in data['training']]
    assert len(loaded['fresh_lexical_sources']) == len(loaded['fresh_structural_sources']) == 144
    assert set(loaded['retention_targets']) == set(c.RETENTION)

@pytest.mark.parametrize('mutation', ['producer_numeric_alias', 'duplicate_artifact', 'false_count', 'anchor_repaired_hash'])
def test_loader_rejects_repaired_manifest_or_targets(miniature_admitted, tmp_path, mutation):
    _, prior = miniature_admitted; result = c.build_corpus(tmp_path / 'corpus', prior)
    path = Path(result['manifest']['path']); manifest = json.loads(path.read_text())
    if mutation == 'producer_numeric_alias': manifest['producer_files'][0]['bytes'] = float(manifest['producer_files'][0]['bytes'])
    elif mutation == 'duplicate_artifact': manifest['artifacts']['fresh_lexical_sources'] = manifest['artifacts']['fresh_structural_sources']
    elif mutation == 'false_count': manifest['counts']['training'] = 1
    else:
        target_path = Path(manifest['artifacts']['training_targets']['path']); rows = json.loads(target_path.read_text())
        unique = next(r for r in rows if r['label'] == 'norm'); unique['owner_anchor_span']['char_end'] -= 1
        target_path.write_text(json.dumps(rows)); manifest['artifacts']['training_targets'] = c.file_ref(target_path)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError): c.load_training_inputs(path)

def test_duplicate_query_or_incomplete_occurrence_inventory_rejected(panels):
    rows, units = deepcopy(panels['fresh_structural']); rows[-1] = deepcopy(rows[0])
    with pytest.raises(ValueError): c.validate_panel(rows, units, 'fresh_structural')

def test_preserve_existing_corpus_path(tmp_path):
    with pytest.raises(ValueError, match='preserve'): c.build_corpus(tmp_path, '/no/read/allowed')
