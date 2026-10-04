"""Occurrence identity and repaired-report attacks on a nonsemantic contract."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as c


def span(text, value, start=0):
    a = text.index(value, start)
    return {'char_start': a, 'char_end': a + len(value), 'text': value}


def fixture():
    text = 'Registry shall file if a permit is valid within 7 days unless a permit is valid within 7 days.'
    t = span(text, 'within 7 days')
    query = {'id': 'query-one', 'source_text': text,
             'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
             'proposed_time_span': {k: t[k] for k in ('char_start', 'char_end')}}
    body = {'char_start': 0, 'char_end': len(text)-1, 'text': text[:-1]}
    norm = {'owner_type': 'norm', 'anchor_span': span(text, 'file'),
            'scope_span': body, 'cue_span': span(text, 'shall')}
    condition = {'owner_type': 'condition', 'anchor_span': span(text, 'a permit is valid'),
                 'scope_span': span(text, 'if a permit is valid within 7 days'), 'cue_span': span(text, 'if')}
    return query, [norm, condition]


def test_candidates_remain_unreviewed_ambiguous_supplied_occurrences():
    query, candidates = fixture(); report = c.prepare_owner_candidates(query, candidates)
    assert c.validate_owner_candidates(report, query=query, candidates=candidates)
    assert all(report[k] is False for k in c.FALSE)
    assert report['selected_candidate_id'] is None
    assert report['candidate_origin'] == 'caller_supplied_unreviewed'
    assert report['coordinate_integrity_verified'] and len(report['candidates']) == 2


def test_same_type_distinct_anchors_never_collapsed():
    query, candidates = fixture(); text = query['source_text']
    other = deepcopy(candidates[1]); other['anchor_span'] = span(text, 'a permit is valid', text.index('unless'))
    other['cue_span'] = span(text, 'unless'); other['scope_span'] = candidates[0]['scope_span']
    report = c.prepare_owner_candidates(query, [candidates[1], other])
    assert report['candidates'][0]['owner_type'] == report['candidates'][1]['owner_type']
    assert report['candidates'][0]['anchor_span']['text'] == report['candidates'][1]['anchor_span']['text']
    assert len({x['candidate_id'] for x in report['candidates']}) == 2


def test_repeated_time_query_is_distinct_without_changing_owner_identity():
    query, candidates = fixture(); first = c.prepare_owner_candidates(query, candidates[:1])
    second = deepcopy(query); t = span(query['source_text'], 'within 7 days', query['source_text'].index('unless'))
    second['id'] = 'query-two'; second['proposed_time_span'] = {k: t[k] for k in ('char_start', 'char_end')}
    other = c.prepare_owner_candidates(second, candidates[:1])
    assert first['query_sha256'] != other['query_sha256']
    assert first['candidates'] == other['candidates']
    with pytest.raises(ValueError): c.validate_owner_candidates(first, query=second, candidates=candidates[:1])


@pytest.mark.parametrize('mutation', [
    lambda q, xs: q.update(source_sha256='0'*64),
    lambda q, xs: q.update(source_text=q['source_text'].replace('Registry', 'Registrar')),
    lambda q, xs: q.update(label='norm'),
    lambda q, xs: q['proposed_time_span'].update(char_start=True),
    lambda q, xs: xs.append(deepcopy(xs[0])),
    lambda q, xs: xs[0].update(owner_type='ambiguous'),
    lambda q, xs: xs[0].update(owner_type=True),
    lambda q, xs: xs[0].update(reviewed=True),
    lambda q, xs: xs[0]['anchor_span'].update(char_start=True),
    lambda q, xs: xs[0]['anchor_span'].update(char_end=999999),
    lambda q, xs: xs[0]['anchor_span'].update(text='archive'),
    lambda q, xs: xs[0]['anchor_span'].update(char_start=16, text='ile'),
    lambda q, xs: xs[0]['anchor_span'].update(token_start=2),
    lambda q, xs: xs[0].update(scope_span=span(q['source_text'], 'Registry shall file')),
    lambda q, xs: xs[0].update(anchor_span=span(q['source_text'], 'within 7 days')),
    lambda q, xs: xs[0].update(cue_span=deepcopy(xs[0]['anchor_span'])),
])
def test_invalid_request_rejected(mutation):
    query, candidates = fixture(); mutation(query, candidates)
    with pytest.raises(ValueError): c.prepare_owner_candidates(query, candidates)


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(owner_occurrence_resolved=True),
    lambda r: r.update(candidate_inventory_complete=True),
    lambda r: r.update(independently_reviewed=True),
    lambda r: r.update(selected_candidate_id=r['candidates'][0]['candidate_id']),
    lambda r: r['candidates'].reverse(),
    lambda r: r['candidates'][0].update(owner_type='exception'),
    lambda r: r['candidates'][0].update(candidate_id=r['candidates'][1]['candidate_id']),
    lambda r: r['query'].update(id='another-query'),
    lambda r: r.update(additional_formula='True'),
])
def test_repaired_report_hash_cannot_change_authoritative_request(mutation):
    query, candidates = fixture(); report = c.prepare_owner_candidates(query, candidates)
    mutation(report); report.pop('report_sha256'); report['report_sha256'] = c.digest(report)
    with pytest.raises(ValueError): c.validate_owner_candidates(report, query=query, candidates=candidates)


@pytest.mark.parametrize('bad', [[], (), [None]*17, 'candidates'])
def test_candidate_resource_and_type_bounds(bad):
    query, _ = fixture()
    with pytest.raises(ValueError): c.prepare_owner_candidates(query, bad)


def test_unicode_offsets_are_code_points_and_requests_are_not_mutated():
    query, candidates = fixture(); oldtext = query['source_text']; text = 'Élan ' + oldtext
    query['source_text'] = text; query['source_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    for key in ('char_start', 'char_end'): query['proposed_time_span'][key] += 5
    for candidate in candidates:
        for kind in ('anchor_span', 'scope_span', 'cue_span'):
            for key in ('char_start', 'char_end'): candidate[kind][key] += 5
    before = deepcopy((query, candidates)); report = c.prepare_owner_candidates(query, candidates)
    assert (query, candidates) == before
    assert report['candidates'][0]['anchor_span']['text'] == 'file'


def test_different_source_version_changes_every_candidate_identity():
    query, candidates = fixture(); first = c.prepare_owner_candidates(query, candidates)
    query['source_text'] += ' Annex'; query['source_sha256'] = hashlib.sha256(query['source_text'].encode()).hexdigest()
    second = c.prepare_owner_candidates(query, candidates)
    assert not {x['candidate_id'] for x in first['candidates']} & {x['candidate_id'] for x in second['candidates']}
