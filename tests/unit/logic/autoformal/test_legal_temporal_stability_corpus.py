"""Independent source-coordinate, exposure, unchanged-input, and seal checks."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_corpus as c
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as candidates


@pytest.fixture(scope='module')
def panels():
    return {split: c.make_panel(split) for split in c.COUNTS}


@pytest.mark.parametrize('split', list(c.COUNTS))
def test_complete_balanced_queries_and_units(panels, split):
    rows, units = panels[split]
    c.validate_units(rows, units, split)
    assert len(rows) == 144 and len(units) == 12
    assert len({r['source_sha256'] for r in rows}) == 60
    for label in c.LABELS:
        values = [r for r in rows if r['label'] == label]
        assert len(values) == 36
        assert Counter(r['annotation']['modality'] for r in values) == {k: 12 for k in 'OPF'}
        assert Counter(r['annotation']['time_form'] for r in values) == {k: 9 for k in c.TIME_FORMS}
        assert Counter(r['annotation']['norm_time_placement'] for r in values) == {k: 12 for k in c.previous.PLACEMENTS}


def test_actual_interposition_order_balanced_parentheses_and_all_norm_positions(panels):
    counts, norm_positions, multiple = Counter(), Counter(), 0
    seen = set()
    for rows, _ in panels.values():
        for row in rows:
            a, text = row['annotation'], row['source_text']
            for n in a['norm_occurrences']:
                actor, modal, action, time = (n[k] for k in ('actor_span', 'modal_span', 'action_span', 'time_span'))
                assert actor['char_end'] < modal['char_start'] < action['char_start']
                for s in (actor, modal, action, n['clause_span']):
                    assert text[s['char_start']:s['char_end']] == s['text']
                    assert n['clause_span']['char_start'] <= s['char_start'] < s['char_end'] <= n['clause_span']['char_end']
                if time is None:
                    continue
                if a['norm_time_placement'] == 'before_actor':
                    assert time['char_end'] < actor['char_start']
                elif a['norm_time_placement'] == 'after_modal':
                    assert modal['char_end'] < time['char_start'] < time['char_end'] < action['char_start']
                else:
                    assert action['char_end'] < time['char_start']
                assert text[time['char_start']:time['char_end']] == time['text']
            if row['label'] == 'norm':
                matches = [n for n in a['norm_occurrences'] if n['time_span'] == a['time_span']]
                assert len(matches) == 1
                assert matches[0]['action_span'] == a['owner_candidates'][0]['anchor_span']
                assert matches[0]['clause_span'] == a['owner_candidates'][0]['scope_span']
                norm_positions[a['norm_time_placement']] += 1
            if a['split'] != 'fresh_structural' or row['source_sha256'] in seen:
                continue
            seen.add(row['source_sha256'])
            first, joint = a['norm_occurrences'][0], a['interposition_span']
            assert text[joint['char_start']:joint['char_end']] == joint['text']
            assert joint['text'][0] == '(' and joint['text'][-1] == ')'
            assert joint['text'].count('(') == joint['text'].count(')') == 1
            lo, hi = joint['char_start'], joint['char_end']
            if a['structural_family'] == c.STRUCTURAL_FAMILIES[0]:
                assert first['actor_span']['char_end'] < lo < hi < first['modal_span']['char_start']
            else:
                assert first['modal_span']['char_end'] < lo < hi < first['action_span']['char_start']
            for owner in ('condition', 'exception'):
                block = a['block_spans'][owner]
                assert lo < block['char_start'] < block['char_end'] < hi
                assert sum(x['role'] == owner + '_predicate' for x in a['source_role_spans']) == 3
            first_owner, second_owner = a['qualifier_order']
            assert a['block_spans'][first_owner]['char_end'] < a['block_spans'][second_owner]['char_start']
            counts[a['structural_family']] += 1
            multiple += len(a['norm_occurrences']) > 1
    assert counts == {k: 30 for k in c.STRUCTURAL_FAMILIES}
    assert norm_positions == {k: 24 for k in c.previous.PLACEMENTS}
    assert multiple > 0


def test_both_qualifier_orders_in_each_structural_family(panels):
    counts = defaultdict(Counter)
    for row in panels['fresh_structural'][0]:
        a = row['annotation']
        counts[a['structural_family']]['_'.join(a['qualifier_order'])] += 1
    assert all(set(v) == {'condition_exception', 'exception_condition'} for v in counts.values())


def test_reference_candidates_exact_scopes_and_ambiguity_hypotheses(panels):
    for rows, _ in panels.values():
        for row in rows:
            report = candidates.prepare_owner_candidates(c.source_row(row), c.candidate_coordinate_inputs(row))
            assert report['owner_occurrence_resolved'] is False
            assert report['candidate_inventory_complete'] is False
            a = row['annotation']
            assert a['source_semantics_verified'] is a['legal_gold'] is False
            if row['label'] == 'ambiguous':
                assert a['countermodels'] and not a['unique_owner_type_asserted']
                assert len({x['owner_type'] for x in a['owner_candidates']}) == 2
                assert all(x['scope_span'] == a['body_span'] for x in a['owner_candidates'] if x['owner_type'] == 'norm')


def test_source_complete_same_type_and_mixed_owner_queries(panels):
    for rows, _ in panels.values():
        sources = defaultdict(list)
        for row in rows:
            sources[row['source_sha256']].append(row)
        patterns = Counter()
        for values in sources.values():
            c.validate_query_inventory([c.source_row(r) for r in values])
            labels = {r['label'] for r in values}
            patterns[len(values), len(labels)] += 1
            if len(labels) == 1 and 'ambiguous' not in labels:
                assert len({r['annotation']['owner_candidates'][0]['owner_occurrence_id'] for r in values}) == len(values)
        assert patterns[2, 1] and patterns[3, 1] and patterns[2, 2] and patterns[3, 3]


def test_source_only_queries_opaque_ids_token_alignment_and_budget(panels):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    for rows, _ in panels.values():
        for row in rows:
            q = c.source_row(row)
            assert set(q) == c.SOURCE_KEYS and len(q['id']) == 68
            assert all(label not in q['id'] for label in c.LABELS)
            tokens = span.tokenize_source(q['source_text'])
            assert len(tokens) <= 256
            assert q['proposed_time_span']['char_start'] in {x['start'] for x in tokens}
            assert q['proposed_time_span']['char_end'] in {x['end'] for x in tokens}
            if row['annotation']['time_form'] == 'month_date':
                assert ', ' in row['annotation']['time_span']['text']


@pytest.mark.parametrize('change', ['label', 'source', 'scope', 'owner_id', 'actor', 'norm_time', 'interposition', 'family', 'unit_float', 'authority'])
def test_repaired_reference_tampering_rejected(change):
    row = deepcopy(c.render_source('fresh_structural', 0, 0)[0])
    a = row['annotation']
    if change == 'label':
        row['label'] = 'norm'
    elif change == 'source':
        row['source_text'] = row['source_text'].replace(' was received', ' was issued')
        row.update(c.query(row['source_text'], row['proposed_time_span']))
    elif change == 'scope':
        a['owner_candidates'][0]['scope_span'] = deepcopy(a['body_span'])
    elif change == 'owner_id':
        a['owner_candidates'][0]['owner_occurrence_id'] = 'owner-' + '0' * 64
    elif change == 'actor':
        a['norm_occurrences'][0]['actor_span'] = deepcopy(a['heading_span'])
    elif change == 'norm_time':
        a['norm_occurrences'][0]['time_span'] = deepcopy(a['time_span'])
    elif change == 'interposition':
        a['interposition_span'] = deepcopy(a['body_span'])
    elif change == 'family':
        a['structural_family'] = c.STRUCTURAL_FAMILIES[1]
    elif change == 'unit_float':
        a['unit_index'] = 0.0
    else:
        a['source_semantics_verified'] = True
    with pytest.raises(ValueError):
        c.validate_target(row)


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'duplicate_unit', 'cross_unit', 'label'])
def test_broken_units_rejected(panels, change):
    rows, units = deepcopy(panels['fresh_lexical'])
    if change == 'duplicate':
        rows[-1] = deepcopy(rows[0])
    elif change == 'missing':
        rows.pop()
    elif change == 'duplicate_unit':
        units[0] = deepcopy(units[1])
    elif change == 'cross_unit':
        units[0]['query_ids'][0] = units[1]['query_ids'][0]
        units[0]['query_ids'].sort()
    else:
        rows[0]['label'] = 'wrong'
    with pytest.raises(ValueError):
        c.validate_units(rows, units, 'fresh_lexical')


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp('stability-fixture')
    original = c.old.build_corpus(base / 'old', [])
    paired = c.paired.build_corpus(base / 'paired', original['path'])
    placement = c.previous.build_corpus(base / 'placement', paired['path'])
    current = c.build_corpus(base / 'current', placement['path'])
    return Path(current['path'])


def test_actual_exposure_all_prior_annotated_panels_and_matched_control(built):
    m = c.read_ref(c.file_ref(built))
    a = c.read_ref(m['artifacts']['exposure_audit'])
    assert len(a['prior_annotated_pools']) == 12
    assert a['panels']['fresh_lexical']['matches_placement_train_body_layout_queries'] == 144
    assert a['panels']['fresh_structural']['matches_prior_body_layout_queries'] == 0
    assert a['historical_source_overlap'] == a['cross_panel_source_overlap'] == a['cross_panel_literal_overlap'] == 0
    assert {'placement_exposed_lexical', 'placement_exposed_structural', 'old_single_fresh', 'old_multi_fresh'} <= set(a['prior_annotated_pools'])


def test_all_eight_runtime_inputs_unchanged_and_old_panels_exposed(built):
    loaded = c.load_training_inputs(built)
    prior = loaded['prior_inputs']
    assert all(c.wire(loaded[key]) == c.wire(prior[key]) for key in c.RUNTIME_KEYS)
    assert loaded['manifest']['new_training_queries'] == loaded['manifest']['new_tuning_queries'] == 0
    assert set(loaded['retention_targets']) == set(c.RETENTION) and len(c.RETENTION) == 8
    assert all([c.source_row(r) for r in v] == loaded['retention_sources'][k] for k, v in loaded['retention_targets'].items())
    assert len(loaded['fresh_lexical_sources']) == len(loaded['fresh_structural_sources']) == 144


def test_loader_reads_zero_current_sealed_files(built):
    program = '''
import json,sys
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_corpus as c
p=Path(sys.argv[1]);m=json.loads(p.read_text());blocked={str(Path(m['artifacts'][k]['path']).resolve()) for k in c.SEALED};attempts=[]
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)) and str(Path(args[0]).resolve()) in blocked:
  attempts.append(str(args[0]));raise RuntimeError('sealed')
sys.addaudithook(guard)
x=c.load_training_inputs(p)
assert len(x['retention_targets'])==8 and not attempts
assert all(c.digest(x[k])==m['reused_runtime_inputs'][k] for k in c.RUNTIME_KEYS)
print('zero current semantic reads')
'''
    result = subprocess.run([sys.executable, '-c', program, str(built)], capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[4])
    assert result.returncode == 0, result.stderr
    assert 'zero current semantic reads' in result.stdout


@pytest.mark.parametrize('change', ['count_float', 'producer_float', 'authority', 'extra', 'alias', 'ref_bool', 'runtime_digest'])
def test_repaired_manifest_tampering_rejected(built, tmp_path, change):
    m = json.loads(built.read_text())
    if change == 'count_float':
        m['counts']['fresh_lexical'] = 144.0
    elif change == 'producer_float':
        m['producer_files'][0]['bytes'] = float(m['producer_files'][0]['bytes'])
    elif change == 'authority':
        m['independent_legal_gold'] = True
    elif change == 'extra':
        m['unapproved'] = True
    elif change == 'alias':
        m['artifacts']['fresh_lexical_targets'] = m['artifacts']['fresh_structural_targets']
    elif change == 'ref_bool':
        m['artifacts']['fresh_lexical_targets']['bytes'] = True
    else:
        m['reused_runtime_inputs']['single_training'] = '0' * 64
    ref = c.write_new(tmp_path / 'manifest.json', m)
    with pytest.raises(ValueError):
        c.load_training_inputs(ref['path'])


def test_missing_occurrence_rejected_and_materialization_not_overwritten(built, panels):
    with pytest.raises(ValueError):
        c.validate_query_inventory([c.source_row(r) for r in panels['fresh_structural'][0][1:]])
    with pytest.raises(ValueError, match='new corpus'):
        c.build_corpus(built.parent, built)
