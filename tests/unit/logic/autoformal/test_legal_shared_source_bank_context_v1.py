"""Immutable parsed bank contexts project planned source requests without review authority.

Fixtures are fictional; the retained case preserves13sections/16physicalrows/
150candidates. Two declared epochs are a forecast, never actual history replay.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import stat

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as legacy_review
from ipfs_datasets_py.logic.autoformal import legal_source_correspondence_requests_v1 as correspondence
from ipfs_datasets_py.logic.autoformal import legal_shared_source_replay_v1 as shared_owner
from ipfs_datasets_py.logic.autoformal import legal_shared_source_bank_context_v1 as owner

ROOT = Path('/home/barberb/lift_coding')
REAL_INPUTS = ROOT / 'artifacts/legal-ir-shared-bank-context-20261019-01/inputs.json'
REAL_INPUTS_BYTES = 12639
REAL_INPUTS_SHA256 = 'ca9e6426029d9dc47aedcaa53d677fcc257c4f8d91585ba0f7ab8f25cbac120e'
EVIDENCE_NAME = 'shared-source-bank-context-engineering-evidence.json'
PROFILE = 'shared-original-catalog-planned-replay/v1'
ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353, 3354, 3355, 3357, 3358]
EPOCHS = [{'epoch_id': 'plan:root', 'parent_epoch_id': None},
          {'epoch_id': 'plan:second', 'parent_epoch_id': 'plan:root'}]
PARSER_PROFILES = {'join': 'legacy-source-join-canonical-record/v1',
    'paired': 'paired-span-census-record/v1', 'receipt': 'legacy-producer-receipt-json/v1'}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_ref(raw):
    return {'bytes': len(raw), 'sha256': sha(raw)}


def fixture_helper():
    path = Path(__file__).with_name('test_legal_source_correspondence_requests_v1.py')
    spec = importlib.util.spec_from_file_location('fictional_correspondence_for_shared_replay', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def independently_catalog(banks):
    """Published descriptor/origin recipes, independently authored from raw bytes."""
    records, origins, bank_rows, bodies = {}, [], [], {}
    for bank in banks:
        bank_id = bank['bank_id']
        root = {'bank_id': bank_id, 'join_origin_id': None, 'paired_origin_ids': [], 'producer_receipt_origin_id': None}
        items = [('join', None, bank['join_bytes'])]
        items += [('paired', index, raw) for index, raw in enumerate(bank['paired_row_bytes'])]
        if bank['join_inputs']['producer_receipt_bytes'] is not None:
            items.append(('receipt', None, bank['join_inputs']['producer_receipt_bytes']))
        for kind, ordinal, raw in items:
            key = {**raw_ref(raw), 'media_type': 'application/json', 'parser_profile': PARSER_PROFILES[kind]}
            content_id = 'sha256:' + sha(wire(key))
            if content_id in bodies: assert bodies[content_id] == raw
            bodies[content_id] = raw
            records[content_id] = {'content_id': content_id, **key}
            origin_key = {'bank_id': bank_id, 'kind': kind, 'logical_row_ordinal': ordinal}
            origin_id = 'sha256:' + sha(wire(origin_key))
            origins.append({'origin_id': origin_id, **origin_key, 'content_id': content_id,
                            'raw_sha256': key['sha256'], 'raw_bytes': key['bytes']})
            if kind == 'join': root['join_origin_id'] = origin_id
            elif kind == 'paired': root['paired_origin_ids'].append(origin_id)
            else: root['producer_receipt_origin_id'] = origin_id
        bank_rows.append(root)
    ordered = [records[key] for key in sorted(records)]
    receipts = [row for row in ordered if row['parser_profile'] == PARSER_PROFILES['receipt']]
    return {'schema': 'legal-shared-source-original-catalog/v1', 'profile': PROFILE,
        'records': ordered, 'origins': origins, 'banks': bank_rows,
        'coverage': {'content_records': len(ordered), 'origin_references': len(origins),
            'unique_content_bytes': sum(row['bytes'] for row in ordered),
            'origin_reference_bytes': sum(row['raw_bytes'] for row in origins),
            'unique_receipt_bytes': sum(row['bytes'] for row in receipts),
            'receipt_origin_bytes': sum(row['raw_bytes'] for row in origins if row['kind'] == 'receipt')}}


def independently_schedule(banks, epochs, catalog):
    requests = []; expanded = receipt_bytes = physical = 0
    by_bank = {row['bank_id']: row for row in catalog['banks']}
    children = {row['epoch_id']: [] for row in epochs}
    for epoch in epochs:
        if epoch['parent_epoch_id'] is not None:
            children[epoch['parent_epoch_id']].append(epoch['epoch_id'])
        for bank in banks:
            origins = by_bank[bank['bank_id']]
            receipt = bank['join_inputs']['producer_receipt_bytes']
            size = 0 if receipt is None else len(receipt)
            for ordinal, raw in enumerate(bank['paired_row_bytes']):
                locators = [row['physical_row_ordinal'] for row in bank['physical_rows'] if row['request_ordinal'] == ordinal]
                requests.append({'epoch_id': epoch['epoch_id'], 'bank_id': bank['bank_id'], 'request_ordinal': ordinal,
                    'join_origin_id': origins['join_origin_id'], 'paired_origin_id': origins['paired_origin_ids'][ordinal],
                    'producer_receipt_origin_id': origins['producer_receipt_origin_id'], 'physical_row_ordinals': locators})
                expanded += len(bank['join_bytes']) + len(raw) + size
                receipt_bytes += size; physical += len(locators)
    return {'schema': 'legal-shared-source-planned-schedule/v1', 'profile': PROFILE, 'epochs': deepcopy(epochs),
        'requests': requests, 'forks': [{'parent_epoch_id': row['epoch_id'], 'child_epoch_ids': children[row['epoch_id']]}
            for row in epochs if len(children[row['epoch_id']]) > 1],
        'coverage': {'epochs': len(epochs), 'scheduled_logical_requests': len(requests),
            'scheduled_physical_references': physical, 'expanded_reference_bytes': expanded,
            'expanded_receipt_reference_bytes': receipt_bytes, 'legacy_history_input_cap': 512 * 1024**2,
            'receipt_reference_lower_bound_exceeds_legacy_cap': receipt_bytes > 512 * 1024**2}}


def replay_request(banks, epochs):
    catalog = independently_catalog(banks)
    schedule = independently_schedule(banks, epochs, catalog)
    return {'schema': 'legal-shared-source-replay-request/v1', 'profile': PROFILE,
        'bank_commitments': [{'bank_id': bank['bank_id'], 'original_bank_sha256': fixture_helper().original_bank_sha256(bank)} for bank in banks],
        'catalog_sha256': sha(wire(catalog)), 'schedule_sha256': sha(wire(schedule)), 'epochs': deepcopy(epochs)}


def source_material(*, fanout=False, unavailable=None, epochs=None):
    helper = fixture_helper(); source = helper.material(fanout=fanout, unavailable=unavailable)
    banks = source['banks']; packet = helper.prepare(source)
    return {'banks': banks, 'packet': packet, 'source_request_raw': wire(source['request']),
        'replay_request': replay_request(banks, EPOCHS if epochs is None else epochs)}



def shared_arguments(data, *, limits=None):
    return {'expected_packet_sha256': sha(wire(data['packet'])),
        'expected_source_request_sha256': sha(data['source_request_raw']),
        'expected_replay_request_sha256': sha(wire(data['replay_request'])),
        'original_banks': data['banks'], 'limits': limits}


def material(*, fanout=False, unavailable=None, epochs=None):
    data = source_material(fanout=fanout, unavailable=unavailable, epochs=epochs)
    data['shared_report'] = shared_owner.prepare_shared_source_replay_v1(data['packet'],
        data['source_request_raw'], wire(data['replay_request']), **shared_arguments(data))
    return data


def arguments(data, *, limits=None):
    return {'expected_shared_report_sha256': sha(wire(data['shared_report'])), **shared_arguments(data, limits=limits)}


def prepare(data, *, limits=None):
    return owner.prepare_shared_source_bank_context_v1(data['shared_report'], data['packet'],
        data['source_request_raw'], wire(data['replay_request']), **arguments(data, limits=limits))


def validate(report, data, *, limits=None):
    return owner.validate_shared_source_bank_context_v1(report, data['shared_report'], data['packet'],
        data['source_request_raw'], wire(data['replay_request']), expected_report_sha256=sha(wire(report)),
        **arguments(data, limits=limits))


def flags(report):
    assert report['authority'] and all(value is False for value in report['authority'].values())
    assert report['inference_view'] is None
    assert all(type(report[name]) is int and report[name] == 0 for name in ('training_mask', 'evaluation_gold_mask'))


def check_projection(report, packet, schedule):
    assert report['schema'] == 'legal-shared-source-bank-context/v1'
    assert report['profile'] == 'owner-minted-immutable-bank-projections/v1'
    assert report['status'] == 'complete_planned_bank_context_projections'
    assert len(report['contexts']) == len(packet['banks'])
    assert len(report['projections']) == len(schedule['requests'])
    contexts = {row['bank_id']: row for row in report['contexts']}
    banks = {row['bank_id']: row for row in packet['banks']}
    epochs = {row['epoch_id']: row for row in schedule['epochs']}
    physical_count = candidate_count = 0
    for projection, planned in zip(report['projections'], schedule['requests'], strict=True):
        bank_id, ordinal = planned['bank_id'], planned['request_ordinal']
        bundle = banks[bank_id]['preparation']
        context = contexts[bank_id]
        physical = [row for row in packet['physical_rows'] if row['bank_id'] == bank_id and row['request_ordinal'] == ordinal]
        assert projection == {'epoch_id': planned['epoch_id'], 'parent_epoch_id': epochs[planned['epoch_id']]['parent_epoch_id'],
            'bank_id': bank_id, 'request_ordinal': ordinal, 'context_id': context['context_id'],
            'context_generation_sha256': report['context_generation_sha256'],
            'request': bundle['requests'][ordinal], 'subject': bundle['subjects'][ordinal],
            'dependency_manifest': bundle['dependency_manifests'][ordinal],
            'source_sections': bundle['source_sections'], 'physical_references': physical}
        assert [row['physical_row_ordinal'] for row in physical] == planned['physical_row_ordinals']
        assert projection['request']['selected_occurrence'] is None
        physical_count += len(physical); candidate_count += sum(row['candidate_count'] for row in physical)
    assert report['coverage'] == {'contexts_minted': len(contexts), 'planned_epochs': len(schedule['epochs']),
        'projected_logical_requests': len(schedule['requests']), 'projected_physical_references': physical_count,
        'projected_candidate_occurrence_references': candidate_count,
        'original_physical_references': len(packet['physical_rows']),
        'original_candidate_occurrence_references': packet['coverage']['candidate_occurrence_references'],
        'full_declared_population_retained': True}
    flags(report)


def test_genuine_two_bank_mint_matches_complete_naive_old_owner_projection(monkeypatch):
    data = material(); original = legacy_review.prepare_legacy_source_review_requests; calls = []
    def counted(*args, **kwargs):
        result = original(*args, **kwargs); calls.append(sha(args[0])); return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', counted)
    report = prepare(data)
    assert len(calls) == 2
    check_projection(report, data['packet'], data['shared_report']['schedule'])
    assert report['work'] == {'shared_report_validation_calls': 1, 'source_bank_preparations': 2,
        'immutable_bank_context_mints': 2, 'planned_context_accesses': 8,
        'legacy_bank_parses_during_projection': 0, 'original_raw_body_parses_by_context_owner': 0,
        'history_epoch_replays': 0, 'authority_cache_hits': 0, 'shared_bank_projection_reuse_implemented': True}
    banks = {row['bank_id']: row for row in data['banks']}
    naive_start = len(calls)
    for projection in report['projections']:
        bank = banks[projection['bank_id']]; ordinal = projection['request_ordinal']
        bundle = legacy_review.prepare_legacy_source_review_requests(bank['join_bytes'], bank['paired_row_bytes'],
            expected_join_sha256=sha(bank['join_bytes']), **bank['join_inputs'])
        assert projection['request'] == bundle['requests'][ordinal]
        assert projection['subject'] == bundle['subjects'][ordinal]
        assert projection['dependency_manifest'] == bundle['dependency_manifests'][ordinal]
        assert projection['source_sections'] == bundle['source_sections']
    assert len(calls) - naive_start == 8
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', original)
    assert validate(report, data) == report
    assert owner.shared_source_bank_context_sha256(report) == sha(wire(report))


def test_physical_fanout_remains_distinct_inside_each_reused_request():
    data = material(fanout=True); report = prepare(data)
    check_projection(report, data['packet'], data['shared_report']['schedule'])
    assert report['coverage']['projected_logical_requests'] == 8
    assert report['coverage']['projected_physical_references'] == 10
    assert len(report['projections'][0]['physical_references']) == 2
    assert len(report['contexts']) == 2


def test_all_fork_branches_project_the_same_originals_without_selecting_a_head():
    epochs = EPOCHS + [{'epoch_id': 'plan:fork', 'parent_epoch_id': 'plan:root'}]
    data = material(epochs=epochs); report = prepare(data)
    check_projection(report, data['packet'], data['shared_report']['schedule'])
    assert [row['epoch_id'] for row in report['projections']] == ['plan:root'] * 4 + ['plan:second'] * 4 + ['plan:fork'] * 4
    assert report['work']['source_bank_preparations'] == 2 and len(report['contexts']) == 2


@pytest.mark.parametrize('unavailable', ['receipt', 'section'])
def test_unavailable_originals_keep_complete_pending_contexts(unavailable):
    data = material(unavailable=unavailable); report = prepare(data)
    check_projection(report, data['packet'], data['shared_report']['schedule'])
    assert report['coverage']['projected_candidate_occurrence_references'] == 0
    assert len(report['projections']) == 8
    assert all(row['request']['selected_occurrence'] is None for row in report['projections'])


def test_each_projection_and_validated_report_is_independently_detached():
    data = material(); report = prepare(data); checked = validate(report, data)
    report['projections'][0]['request']['original_row']['candidates'].clear()
    report['projections'][0]['source_sections'][0]['extracted_text'] = 'changed detached copy'
    assert len(report['projections'][4]['request']['original_row']['candidates']) == 2
    assert len(checked['projections'][0]['request']['original_row']['candidates']) == 2
    assert data['packet']['banks'][0]['preparation']['source_sections'][0]['extracted_text'] == '§ Café Clerk; Clerk.'


@pytest.mark.parametrize('damage', ['join', 'paired', 'receipt', 'source_text', 'expected_population'])
def test_bad_originals_are_refused_by_both_old_public_owner_and_context_mint(damage):
    data = material(); bank = data['banks'][0]
    if damage == 'join': bank['join_bytes'] += b'!'
    elif damage == 'paired': bank['paired_row_bytes'][0] += b' '
    elif damage == 'receipt': bank['join_inputs']['producer_receipt_bytes'] += b' '
    elif damage == 'source_text': bank['join_inputs']['source_sections'][0]['text'] += ' changed'
    else: bank['join_inputs']['expected_population'][0]['row_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        legacy_review.prepare_legacy_source_review_requests(bank['join_bytes'], bank['paired_row_bytes'],
            expected_join_sha256=sha(bank['join_bytes']), **bank['join_inputs'])
    with pytest.raises(ValueError): prepare(data)


@pytest.mark.parametrize('damage', ['shared_pin', 'source_pin', 'source_request_pin', 'replay_pin',
    'shared_report_drop', 'packet_geometry', 'source_request_wire', 'replay_request_wire',
    'original_bank_drop', 'original_bank_reorder', 'physical_reorder'])
def test_all_independent_inputs_and_ordered_populations_bind_each_new_context_generation(damage):
    data = material(); kwargs = arguments(data)
    if damage == 'shared_pin': kwargs['expected_shared_report_sha256'] = '0' * 64
    elif damage == 'source_pin': kwargs['expected_packet_sha256'] = '0' * 64
    elif damage == 'source_request_pin': kwargs['expected_source_request_sha256'] = '0' * 64
    elif damage == 'replay_pin': kwargs['expected_replay_request_sha256'] = '0' * 64
    elif damage == 'shared_report_drop': data['shared_report']['schedule']['requests'].pop(); kwargs['expected_shared_report_sha256'] = sha(wire(data['shared_report']))
    elif damage == 'packet_geometry': data['packet']['banks'][0]['preparation']['requests'][0]['original_row']['candidates'][0]['source_occurrence']['start_utf8'] += 1; kwargs['expected_packet_sha256'] = sha(wire(data['packet']))
    elif damage == 'source_request_wire': data['source_request_raw'] += b'\n'; kwargs['expected_source_request_sha256'] = sha(data['source_request_raw'])
    elif damage == 'replay_request_wire': data['replay_request'] = {'wrong_profile': True}; kwargs['expected_replay_request_sha256'] = sha(wire(data['replay_request']))
    elif damage == 'original_bank_drop': data['banks'].pop()
    elif damage == 'original_bank_reorder': data['banks'].reverse()
    else: data['banks'][0]['physical_rows'].reverse()
    with pytest.raises(ValueError):
        owner.prepare_shared_source_bank_context_v1(data['shared_report'], data['packet'], data['source_request_raw'],
            wire(data['replay_request']), **kwargs)


@pytest.mark.parametrize('damage', ['context_drop', 'context_reorder', 'context_bundle_hash', 'context_generation',
    'projection_drop', 'projection_reorder', 'projection_request', 'projection_subject', 'projection_dependency',
    'projection_source', 'projection_physical', 'projection_bool_ordinal', 'generation_sources', 'generation_limits',
    'shared_report', 'coverage', 'work', 'authority', 'training_mask', 'inference_view'])
def test_rehashed_output_context_or_projection_changes_cannot_replace_reminting(damage):
    data = material(); report = prepare(data)
    if damage == 'context_drop': report['contexts'].pop()
    elif damage == 'context_reorder': report['contexts'].reverse()
    elif damage == 'context_bundle_hash': report['contexts'][0]['bank_bundle_sha256'] = '0' * 64
    elif damage == 'context_generation': report['contexts'][0]['generation_sha256'] = '0' * 64
    elif damage == 'projection_drop': report['projections'].pop()
    elif damage == 'projection_reorder': report['projections'].reverse()
    elif damage == 'projection_request': report['projections'][0]['request']['original_row']['candidates'].pop()
    elif damage == 'projection_subject': report['projections'][0]['subject'] = deepcopy(report['projections'][1]['subject'])
    elif damage == 'projection_dependency': report['projections'][0]['dependency_manifest'] = deepcopy(report['projections'][1]['dependency_manifest'])
    elif damage == 'projection_source': report['projections'][0]['source_sections'].clear()
    elif damage == 'projection_physical': report['projections'][0]['physical_references'].pop()
    elif damage == 'projection_bool_ordinal': report['projections'][0]['request_ordinal'] = False
    elif damage == 'generation_sources': report['context_generation']['owner_profiles'] = {}
    elif damage == 'generation_limits': report['context_generation']['limits'] = {}
    elif damage == 'shared_report': report['shared_report']['physical_references'].pop()
    elif damage == 'coverage': report['coverage']['projected_logical_requests'] -= 1
    elif damage == 'work': report['work']['legacy_bank_parses_during_projection'] = 1
    elif damage == 'authority': report['authority']['parsed_bank_context_is_review_authority'] = True
    elif damage == 'training_mask': report['training_mask'] = True
    else: report['inference_view'] = {'unexpected_permission': True}
    with pytest.raises(ValueError): validate(report, data)


@pytest.mark.parametrize('key', ['max_banks', 'max_physical_rows', 'max_original_bytes', 'max_report_bytes',
    'max_request_bytes', 'max_json_nodes', 'max_json_depth', 'max_string_bytes', 'max_epochs',
    'max_scheduled_requests', 'max_expanded_reference_bytes', 'max_context_bytes', 'max_projection_count'])
def test_all_inherited_caps_are_lower_only_and_refuse_boolean_aliases_before_replay(key, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    for value in (owner.DEFAULT_LIMITS[key] + 1, True):
        with pytest.raises(ValueError): prepare(data, limits={key: value})
    assert calls == []


@pytest.mark.parametrize('limits', [{'max_banks': 1}, {'max_physical_rows': 1}, {'max_original_bytes': 1},
    {'max_report_bytes': 1}, {'max_request_bytes': 1}, {'max_json_nodes': 1}, {'max_json_depth': 1},
    {'max_string_bytes': 1}, {'max_epochs': 1}, {'max_scheduled_requests': 1}, {'max_expanded_reference_bytes': 1},
    {'max_context_bytes': 1}, {'max_projection_count': 1}])
def test_lowered_combined_and_schedule_budgets_refuse_without_genuine_replay(limits, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    with pytest.raises(ValueError): prepare(data, limits=limits)
    assert calls == []


@pytest.mark.parametrize('damage', ['shared_report', 'packet', 'original', 'detached_original', 'limits', 'offered_report'])
def test_caller_detached_limit_and_offered_report_mutation_refuse_closing_checks(damage, monkeypatch):
    data = material(); report = prepare(data) if damage == 'offered_report' else None
    limits = {'max_report_bytes': shared_owner.DEFAULT_LIMITS['max_report_bytes']}
    original = legacy_review.prepare_legacy_source_review_requests; calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs); calls.append(True)
        if len(calls) == 1:
            if damage == 'shared_report': data['shared_report']['work']['history_epoch_replays'] = 1
            elif damage == 'packet': data['packet']['physical_rows'].pop()
            elif damage == 'original': data['banks'][0]['join_inputs']['source_sections'][0]['text'] += ' changed'
            elif damage == 'detached_original': kwargs['source_sections'][0]['text'] += ' changed'
            elif damage == 'limits': limits['max_report_bytes'] -= 1
            else: report['projections'][0]['request_ordinal'] = False
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate)
    with pytest.raises(ValueError):
        if damage == 'offered_report': validate(report, data, limits=limits)
        else: prepare(data, limits=limits)
    assert calls


def test_public_validator_bounds_complete_root_before_hashing_any_offered_output(monkeypatch):
    data = material(); report = prepare(data); kwargs = arguments(data, limits={'max_original_bytes': 1})
    expected = sha(wire(report))
    def forbidden_hash(*args, **kwargs): raise AssertionError('hash before complete root bound')
    monkeypatch.setattr(hashlib, 'sha256', forbidden_hash)
    with pytest.raises(ValueError):
        owner.validate_shared_source_bank_context_v1(report, data['shared_report'], data['packet'],
            data['source_request_raw'], wire(data['replay_request']), expected_report_sha256=expected, **kwargs)


def test_caller_cannot_supply_a_verified_dictionary_as_an_owner_minted_context():
    data = material(); forged = {'verified': True, 'contexts': [{'bank_id': data['banks'][0]['bank_id']}]}
    kwargs = arguments(data); kwargs['expected_shared_report_sha256'] = sha(wire(forged))
    with pytest.raises(ValueError):
        owner.prepare_shared_source_bank_context_v1(forged, data['packet'], data['source_request_raw'],
            wire(data['replay_request']), **kwargs)
    assert not any(name.startswith(('assess_', 'authenticate_', 'apply_')) for name in owner.__all__)



def test_context_generation_identity_keeps_limits_and_owner_profiles_explicit():
    data = material(); report = prepare(data)
    generation = report['context_generation']
    assert generation['schema'] == 'legal-shared-source-bank-context-generation/v1'
    assert generation['owner_profile'] == report['profile']
    assert generation['shared_report_sha256'] == sha(wire(data['shared_report']))
    assert generation['source_packet_sha256'] == sha(wire(data['packet']))
    assert generation['source_request_sha256'] == sha(data['source_request_raw'])
    assert generation['replay_request_sha256'] == sha(wire(data['replay_request']))
    assert generation['limits'] == owner.DEFAULT_LIMITS
    assert generation['source_view_profiles'] and generation['owner_profiles']
    assert report['context_generation_sha256'] == sha(wire(generation))
    for context, bank in zip(report['contexts'], data['packet']['banks'], strict=True):
        assert context['bank_bundle_sha256'] == sha(wire(bank))
        assert context['bank_bundle_bytes'] == len(wire(bank))
        identity = {'generation_sha256': report['context_generation_sha256'], 'bank_id': bank['bank_id'],
            'bank_ordinal': bank['bank_ordinal'], 'bank_bundle_sha256': sha(wire(bank))}
        assert context['context_id'] == 'sha256:' + sha(wire(identity))


@pytest.mark.parametrize('key', ['max_context_bytes', 'max_projection_count'])
def test_lower_but_sufficient_context_limit_changes_generation_and_context_ids(key):
    data = material(); original = prepare(data)
    changed = prepare(data, limits={key: owner.DEFAULT_LIMITS[key] - 1})
    assert changed['projections'][0]['request'] == original['projections'][0]['request']
    assert changed['context_generation_sha256'] != original['context_generation_sha256']
    assert changed['contexts'][0]['context_id'] != original['contexts'][0]['context_id']
    assert validate(changed, data, limits={key: owner.DEFAULT_LIMITS[key] - 1}) == changed


def read_exact(reference):
    path = Path(reference['path'])
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == reference['bytes']
        assert 0 < before.st_size <= 32 * 1024**2
        raw = stream.read(reference['bytes'] + 1)
        after = os.fstat(stream.fileno())
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    assert identity(before) == identity(after) == identity(path.lstat())
    assert len(raw) == reference['bytes'] and sha(raw) == reference['sha256']
    return raw


def read_json(reference):
    raw = read_exact(reference)
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite original')))


def physical_source_key(provenance):
    return {key: provenance[key] for key in ('repository_id', 'revision', 'path_in_repo',
            'artifact_sha256', 'artifact_bytes', 'parquet_row_index')}


def test_real_two_bank_contexts_project_all_32_requests_without_bank_reparsing(tmp_path, monkeypatch):
    assert os.environ.get('LEGAL_SHARED_SOURCE_BANK_CONTEXT_ENROLLED') == '1', 'exact original admission required'
    assert os.environ.get('LEGAL_SHARED_SOURCE_BANK_CONTEXT_INPUTS') == str(REAL_INPUTS)
    root_ref = {'path': str(REAL_INPUTS), 'bytes': REAL_INPUTS_BYTES, 'sha256': REAL_INPUTS_SHA256}
    inputs = read_json(root_ref)
    assert inputs['schema'] == 'legal-shared-source-bank-context-qualification-inputs/v1'
    prior_inputs = read_json(inputs['prior_inputs'])
    refs = prior_inputs['originals']
    declarations = read_json(refs['parent_declarations'])
    legacy_inputs = read_json(refs['legacy_inputs'])
    sections = read_json(refs['parent_sections'])
    row_pins = read_json(refs['parent_row_pins'])
    crosswalk = read_json(refs['crosswalk'])
    assert len(crosswalk['records']) == 16 and len(crosswalk['bundles']) == 2
    assert len(sections['source_sections']) == len(sections['expected_source_sections']) == 13
    assert sections['selected_row_ordinals'] == row_pins['row_ordinals'] == ORDINALS
    assert len(row_pins['expected_row_sha256s']) == 13 and len(row_pins['all_columns']) == 45
    source_oracles = []
    source_by_ordinal = {}
    for ordinal, section, expected, row_hash in zip(ORDINALS, sections['source_sections'],
            sections['expected_source_sections'], row_pins['expected_row_sha256s'], strict=True):
        assert {key: section[key] for key in expected} == expected
        assert expected['parquet_row_index'] == ordinal
        assert sha(section['text'].encode('utf-8')) == expected['text_sha256']
        key = physical_source_key(expected)
        source_id = 'sha256:' + sha(wire(key))
        source_oracles.append({'physical_section_id': source_id, 'physical_key': key,
            'text_sha256': expected['text_sha256'], 'text_utf8_bytes': len(section['text'].encode('utf-8')),
            'independently_retained_full_row_sha256': row_hash, 'full_raw_row_recomputed_here': False})
        source_by_ordinal[ordinal] = section
    banks, cache_oracles = [], []
    for declaration, supplied in zip(declarations['banks'], prior_inputs['banks'], strict=True):
        bank_id, manifest = supplied['bank_id'], supplied['manifest_path_in_repo']
        assert declaration['bank'] == bank_id
        original = legacy_inputs[manifest]
        cross_rows = [row for row in crosswalk['records'] if row['manifest_path_in_repo'] == manifest]
        assert len(cross_rows) == len(supplied['paired_rows']) == len(declaration['rows']) == 8
        raw_rows = [read_exact(ref) for ref in supplied['paired_rows']]
        physical_rows = []
        for ordinal, cross_row, row_raw, row_ref, expected in zip(range(8), cross_rows, raw_rows,
                supplied['paired_rows'], original['expected_population'], strict=True):
            assert cross_row['row_ordinal'] == ordinal
            assert cross_row['row_sha256'] == expected['row_sha256'] == row_ref['sha256'] == sha(row_raw)
            physical = {'repository_id': cross_row['repository_id'], 'revision': cross_row['revision'],
                'path_in_repo': cross_row['table']['path_in_repo'],
                'artifact_sha256': cross_row['table']['sha256'], 'row_ordinal': ordinal}
            published_key = {'repository_id': physical['repository_id'], 'revision': physical['revision'],
                'table_path_in_repo': physical['path_in_repo'], 'table_sha256': physical['artifact_sha256'],
                'row_ordinal': ordinal}
            assert cross_row['physical_record_id'] == 'sha256:' + sha(wire(published_key))
            physical_rows.append({'physical_row_ordinal': ordinal, 'request_ordinal': ordinal,
                                  'physical_identity': physical})
            cache_oracles.append({'bank_id': bank_id, 'physical_row_ordinal': ordinal,
                'physical_identity': physical, 'physical_record_id': cross_row['physical_record_id'],
                'reference_id': cross_row['reference_id'], 'paired_row_sha256': row_ref['sha256'],
                'candidate_occurrence_ids': cross_row['candidate_occurrence_ids']})
        receipt = read_exact(supplied['producer_receipt'])
        assert sha(receipt) == original['expected_producer_receipt_sha256']
        join_inputs = {key: deepcopy(original[key]) for key in ('expected_population',
            'expected_producer_receipt_sha256', 'source_sections', 'expected_source_sections')}
        join_inputs['producer_receipt_bytes'] = receipt
        for section in join_inputs['source_sections']:
            assert section == source_by_ordinal[section['parquet_row_index']]
        banks.append({'bank_id': bank_id, 'join_bytes': read_exact(supplied['join']),
            'paired_row_bytes': raw_rows, 'join_inputs': join_inputs, 'physical_rows': physical_rows})
    packet_raw = read_exact(inputs['packet']); packet = json.loads(packet_raw)
    assert packet_raw == wire(packet) + b'\n' and sha(wire(packet)) == inputs['packet_canonical_sha256']
    source_request_raw = read_exact(inputs['source_request'])
    assert source_request_raw == wire(json.loads(source_request_raw))
    assert json.loads(source_request_raw) == fixture_helper().request_for(banks)
    shared_raw = read_exact(inputs['shared_replay_report']); shared_report = json.loads(shared_raw)
    assert shared_raw == wire(shared_report) + b'\n'
    assert sha(wire(shared_report)) == inputs['shared_replay_report_canonical_sha256']
    replay_raw = read_exact(inputs['replay_request']); replay = json.loads(replay_raw)
    assert replay_raw == wire(replay) and replay == replay_request(banks, EPOCHS)
    data = {'banks': banks, 'packet': packet, 'source_request_raw': source_request_raw,
            'replay_request': replay, 'shared_report': shared_report}
    original = legacy_review.prepare_legacy_source_review_requests
    actual_calls = []
    def counted(*args, **kwargs):
        result = original(*args, **kwargs); actual_calls.append(sha(args[0])); return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', counted)
    report = prepare(data)
    assert len(actual_calls) == 2
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', original)
    assert validate(report, data) == report
    check_projection(report, packet, shared_report['schedule'])
    assert report['coverage'] == {'contexts_minted': 2, 'planned_epochs': 2, 'projected_logical_requests': 32,
        'projected_physical_references': 32, 'projected_candidate_occurrence_references': 300,
        'original_physical_references': 16, 'original_candidate_occurrence_references': 150,
        'full_declared_population_retained': True}
    assert report['work'] == {'shared_report_validation_calls': 1, 'source_bank_preparations': 2,
        'immutable_bank_context_mints': 2, 'planned_context_accesses': 32,
        'legacy_bank_parses_during_projection': 0, 'original_raw_body_parses_by_context_owner': 0,
        'history_epoch_replays': 0, 'authority_cache_hits': 0, 'shared_bank_projection_reuse_implemented': True}
    assert report['shared_report'] == shared_report
    coverage = packet['coverage']
    assert coverage['banks'] == 2
    assert coverage['logical_requests'] == coverage['physical_rows'] == coverage['distinct_physical_identities'] == 16
    assert coverage['source_section_references'] == coverage['distinct_source_sections'] == 13
    assert coverage['candidate_occurrence_references'] == 150
    assert coverage['unique_candidate_rows'] == 11 and coverage['ambiguous_candidate_rows'] == 5
    assert coverage['disposition_counts'] == {'unique_exact_candidate': 11, 'ambiguous_exact_candidates': 5}
    assert fixture_helper().assert_geometry(packet) == 150
    assert len(packet['physical_rows']) == len(cache_oracles) == 16
    names = ('bank_id', 'physical_row_ordinal', 'physical_identity', 'paired_row_sha256', 'candidate_occurrence_ids')
    for physical, oracle in zip(packet['physical_rows'], cache_oracles, strict=True):
        assert {key: physical[key] for key in names} == {key: oracle[key] for key in names}
    assert sum(len(unit['context_slot_ids']) for bank in packet['banks'] for unit in bank['preparation']['requests']) == 144
    assert sum(len(unit['deferred_review_slot_ids']) for bank in packet['banks'] for unit in bank['preparation']['requests']) == 112
    flags(report); fixture_helper().no_authority(packet)
    def retain(name, raw):
        path = tmp_path / name
        assert len(raw) <= 32 * 1024**2
        with path.open('xb') as stream: stream.write(raw)
        return {'path': str(path), **raw_ref(raw)}
    full_ref = retain('source-correspondence-full-report.json', wire(packet) + b'\n')
    source_ref = retain('source-correspondence-request.json', source_request_raw)
    shared_ref = retain('shared-source-replay-report.json', wire(shared_report) + b'\n')
    replay_ref = retain('shared-source-replay-request.json', replay_raw)
    context_ref = retain('shared-source-bank-context-report.json', wire(report) + b'\n')
    evidence = {'schema': 'legal-shared-source-bank-context-engineering-evidence/v1', 'coverage': coverage,
        'full_report': full_ref, 'full_report_canonical_sha256': sha(wire(packet)),
        'request_sha256': sha(source_request_raw), 'request_artifact': source_ref,
        'request_artifact_wire': 'exact canonical compact sorted Unicode JSON API bytes without final LF',
        'shared_replay_report': shared_ref, 'shared_replay_report_canonical_sha256': sha(wire(shared_report)),
        'replay_request_artifact': replay_ref, 'replay_request_sha256': sha(replay_raw),
        'bank_context_report': context_ref, 'bank_context_report_canonical_sha256': sha(wire(report)),
        'context_coverage': report['coverage'], 'context_work': report['work'],
        'context_generation_sha256': report['context_generation_sha256'],
        'actual_prepare_bank_replay_calls': len(actual_calls), 'actual_context_projection_count': 32,
        'catalog_coverage': shared_report['catalog']['coverage'], 'schedule_coverage': shared_report['schedule']['coverage'],
        'work': shared_report['work'], 'scheduled_candidate_references': 300,
        'original_input_refs': [root_ref] + inputs['productive_originals'],
        'physical_cache_oracles': cache_oracles, 'retained_source_oracles': source_oracles,
        'exact_candidate_geometry_checked': 150, 'actual_submitted_reviews': 0,
        'selected_occurrences': 0, 'source_decisions_applied': 0, 'actual_source_adoptions': 0,
        'actual_history_epoch_replays': 0, 'planned_epochs_are_executed': False,
        'actual_saved_work_or_speedup_measured': False, 'original_parent_or26shards_opened': False,
        'fresh_cache_table_verification': False, 'fresh_full_raw_row_hash_recomputation': False,
        'correspondence_authority': packet['authority'], 'shared_replay_authority': shared_report['authority'],
        'authority': report['authority'], 'training_mask': 0, 'evaluation_gold_mask': 0, 'inference_view': None,
        'worker_lifetime_peak_rss_linux_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_scope': 'Linux worker lifetime peak includes bootstrap and fixtures; not an isolated owner peak or a memory bound proof.'}
    assert len(evidence['original_input_refs']) == 31
    with (tmp_path / EVIDENCE_NAME).open('xb') as stream: stream.write(wire(evidence) + b'\n')
