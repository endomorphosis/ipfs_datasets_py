"""Shared original-body custody and planned replay costs carry no review effect.

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
from ipfs_datasets_py.logic.autoformal import legal_shared_source_replay_v1 as owner

ROOT = Path('/home/barberb/lift_coding')
REAL_INPUTS = ROOT / 'artifacts/legal-ir-shared-source-replay-20261019-01/inputs.json'
REAL_INPUTS_BYTES = 10858
REAL_INPUTS_SHA256 = '09e9f87e2c13464b2b56f60fefdbde016894c52844e4ca447db9387353a22977'
EVIDENCE_NAME = 'shared-source-replay-engineering-evidence.json'
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


def material(*, fanout=False, unavailable=None, epochs=None):
    helper = fixture_helper(); source = helper.material(fanout=fanout, unavailable=unavailable)
    banks = source['banks']; packet = helper.prepare(source)
    return {'banks': banks, 'packet': packet, 'source_request_raw': wire(source['request']),
        'replay_request': replay_request(banks, EPOCHS if epochs is None else epochs)}


def arguments(data, *, limits=None):
    return {'expected_packet_sha256': sha(wire(data['packet'])),
        'expected_source_request_sha256': sha(data['source_request_raw']),
        'expected_replay_request_sha256': sha(wire(data['replay_request'])),
        'original_banks': data['banks'], 'limits': limits}


def prepare(data, *, limits=None):
    return owner.prepare_shared_source_replay_v1(data['packet'], data['source_request_raw'], wire(data['replay_request']),
                                               **arguments(data, limits=limits))


def validate(report, data, *, limits=None):
    return owner.validate_shared_source_replay_v1(report, data['packet'], data['source_request_raw'], wire(data['replay_request']),
        expected_report_sha256=sha(wire(report)), **arguments(data, limits=limits))


def flags(record):
    assert record['authority'] and all(value is False for value in record['authority'].values())
    assert record['inference_view'] is None
    assert all(type(record[name]) is int and record[name] == 0 for name in ('training_mask', 'evaluation_gold_mask'))


def no_raw_bodies(value):
    assert not isinstance(value, bytes)
    if type(value) is dict:
        for child in value.values(): no_raw_bodies(child)
    elif type(value) is list:
        for child in value: no_raw_bodies(child)


def test_catalog_and_schedule_match_independent_complete_recipes():
    data = material(); report = prepare(data)
    expected_catalog = independently_catalog(data['banks'])
    expected_schedule = independently_schedule(data['banks'], EPOCHS, expected_catalog)
    assert report['catalog'] == expected_catalog and report['catalog_sha256'] == sha(wire(expected_catalog))
    assert report['schedule'] == expected_schedule and report['schedule_sha256'] == sha(wire(expected_schedule))
    assert report['source_packet'] == data['packet'] and report['physical_references'] == data['packet']['physical_rows']
    assert report['schedule']['coverage']['scheduled_logical_requests'] == 8
    assert report['schedule']['coverage']['scheduled_physical_references'] == 8
    assert validate(report, data) == report
    assert owner.shared_source_replay_sha256(report) == sha(wire(report))
    flags(report); no_raw_bodies(report)


def test_equal_bytes_keep_distinct_bank_origins_and_physical_fanout():
    data = material(fanout=True); report = prepare(data)
    catalog = report['catalog']
    assert len(catalog['origins']) == 8 and len(catalog['records']) == 4
    assert len({row['origin_id'] for row in catalog['origins']}) == 8
    assert len({row['content_id'] for row in catalog['origins']}) == 4
    assert report['schedule']['coverage']['scheduled_physical_references'] == 10
    assert report['schedule']['coverage']['scheduled_logical_requests'] == 8
    assert len(report['physical_references']) == 5
    flags(report)


def test_equal_body_bytes_in_different_parser_profiles_never_share_content_identity():
    data = material(); bank = deepcopy(data['banks'][0])
    bank['paired_row_bytes'][0] = bank['join_bytes']
    expected = independently_catalog([bank])
    result = owner.prepare_shared_source_replay_commitments_v1([bank], EPOCHS)
    assert result['catalog'] == expected
    joins = [row for row in result['catalog']['records'] if row['parser_profile'] == PARSER_PROFILES['join']]
    paired = [row for row in result['catalog']['records'] if row['parser_profile'] == PARSER_PROFILES['paired']
              and row['sha256'] == joins[0]['sha256']]
    assert len(paired) == 1 and paired[0]['content_id'] != joins[0]['content_id']
    no_raw_bodies(result)


def test_forks_are_explicit_without_discarding_any_planned_branch():
    epochs = EPOCHS + [{'epoch_id': 'plan:other-child', 'parent_epoch_id': 'plan:root'}]
    data = material(epochs=epochs); report = prepare(data)
    assert report['schedule']['epochs'] == epochs
    assert report['schedule']['forks'] == [{'parent_epoch_id': 'plan:root', 'child_epoch_ids': ['plan:second', 'plan:other-child']}]
    assert report['schedule']['coverage']['scheduled_logical_requests'] == 12
    assert report['schedule']['coverage']['scheduled_physical_references'] == 12
    assert validate(report, data) == report
    flags(report)


@pytest.mark.parametrize('unavailable', ['receipt', 'section'])
def test_missing_receipts_or_sources_keep_original_pending_rows(unavailable):
    data = material(unavailable=unavailable); report = prepare(data)
    assert len(report['physical_references']) == 4
    assert report['source_packet']['coverage']['candidate_occurrence_references'] == 0
    if unavailable == 'receipt':
        assert all(bank['producer_receipt_origin_id'] is None for bank in report['catalog']['banks'])
        assert report['catalog']['coverage']['unique_receipt_bytes'] == 0
    assert validate(report, data) == report
    flags(report)


def test_inputs_and_validated_output_are_detached():
    data = material(); report = prepare(data); checked = validate(report, data)
    report['catalog']['origins'].clear(); report['schedule']['requests'].clear()
    assert len(checked['catalog']['origins']) == 8 and len(checked['schedule']['requests']) == 8
    assert len(data['packet']['physical_rows']) == 4


@pytest.mark.parametrize('damage', ['schema', 'profile', 'catalog_pin', 'schedule_pin', 'bank_pin',
    'bank_drop', 'bank_reorder', 'extra_field', 'epoch_duplicate', 'epoch_multiple_roots',
    'epoch_forward_parent', 'epoch_cycle', 'epoch_drop', 'epoch_reorder', 'epoch_extra'])
def test_pinned_complete_request_and_planned_dag_refusals(damage):
    data = material(); req = data['replay_request']
    if damage == 'schema': req['schema'] += '-other'
    elif damage == 'profile': req['profile'] += '-other'
    elif damage == 'catalog_pin': req['catalog_sha256'] = '0' * 64
    elif damage == 'schedule_pin': req['schedule_sha256'] = '0' * 64
    elif damage == 'bank_pin': req['bank_commitments'][0]['original_bank_sha256'] = '0' * 64
    elif damage == 'bank_drop': req['bank_commitments'].pop()
    elif damage == 'bank_reorder': req['bank_commitments'].reverse()
    elif damage == 'extra_field': req['reviews'] = []
    elif damage == 'epoch_duplicate': req['epochs'][1]['epoch_id'] = req['epochs'][0]['epoch_id']
    elif damage == 'epoch_multiple_roots': req['epochs'][1]['parent_epoch_id'] = None
    elif damage == 'epoch_forward_parent': req['epochs'][0]['parent_epoch_id'] = req['epochs'][1]['epoch_id']
    elif damage == 'epoch_cycle': req['epochs'][1]['parent_epoch_id'] = req['epochs'][1]['epoch_id']
    elif damage == 'epoch_drop': req['epochs'].pop()
    elif damage == 'epoch_reorder': req['epochs'].reverse()
    else: req['epochs'][0]['source_decision'] = True
    with pytest.raises(ValueError): prepare(data)


@pytest.mark.parametrize('damage', ['catalog_record_drop', 'catalog_origin_drop', 'catalog_origin_reorder', 'catalog_profile',
    'catalog_length', 'catalog_origin_identity', 'schedule_request_drop', 'schedule_request_reorder',
    'schedule_physical_drop', 'schedule_bank', 'source_geometry', 'physical_reference', 'forecast_bytes',
    'authority', 'training_mask', 'work_count'])
def test_rehashed_catalog_schedule_or_source_packet_tampering_is_refused(damage):
    data = material(); report = prepare(data)
    if damage == 'catalog_record_drop': report['catalog']['records'].pop()
    elif damage == 'catalog_origin_drop': report['catalog']['origins'].pop()
    elif damage == 'catalog_origin_reorder': report['catalog']['origins'].reverse()
    elif damage == 'catalog_profile': report['catalog']['records'][0]['parser_profile'] += '-other'
    elif damage == 'catalog_length': report['catalog']['records'][0]['bytes'] += 1
    elif damage == 'catalog_origin_identity': report['catalog']['origins'][0]['bank_id'] = 'other-bank'
    elif damage == 'schedule_request_drop': report['schedule']['requests'].pop()
    elif damage == 'schedule_request_reorder': report['schedule']['requests'].reverse()
    elif damage == 'schedule_physical_drop': report['schedule']['requests'][0]['physical_row_ordinals'].clear()
    elif damage == 'schedule_bank': report['schedule']['requests'][0]['bank_id'] = 'other-bank'
    elif damage == 'source_geometry': report['source_packet']['banks'][0]['preparation']['requests'][0]['original_row']['candidates'][0]['source_occurrence']['start_utf8'] += 1
    elif damage == 'physical_reference': report['physical_references'].pop()
    elif damage == 'forecast_bytes': report['schedule']['coverage']['expanded_receipt_reference_bytes'] += 1
    elif damage == 'authority': report['authority']['source_correspondence_verified'] = True
    elif damage == 'training_mask': report['training_mask'] = True
    else: report['work']['source_bank_preparations'] += 1
    with pytest.raises(ValueError): validate(report, data)


@pytest.mark.parametrize('key', ['max_banks', 'max_physical_rows', 'max_original_bytes', 'max_report_bytes',
    'max_request_bytes', 'max_json_nodes', 'max_json_depth', 'max_string_bytes'])
def test_legacy_structural_caps_are_lower_only_and_preserve_boolean_integer_distinction(key, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    for value in (correspondence.DEFAULT_LIMITS[key] + 1, True):
        with pytest.raises(ValueError): prepare(data, limits={key: value})
    assert calls == []


@pytest.mark.parametrize('limits', [{'max_banks': 1}, {'max_physical_rows': 1}, {'max_original_bytes': 1},
    {'max_report_bytes': 1}, {'max_request_bytes': 1}, {'max_json_nodes': 1}, {'max_json_depth': 1}, {'max_string_bytes': 1}])
def test_combined_root_caps_refuse_before_genuine_source_replay(limits, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    with pytest.raises(ValueError): prepare(data, limits=limits)
    assert calls == []


@pytest.mark.parametrize('damage', ['caller_packet', 'caller_original', 'detached_original', 'limits', 'offered_report'])
def test_closing_guards_refuse_mutation_during_genuine_public_owner_replay(damage, monkeypatch):
    data = material(); report = prepare(data) if damage == 'offered_report' else None
    limits = {'max_report_bytes': correspondence.DEFAULT_LIMITS['max_report_bytes']}
    original = legacy_review.prepare_legacy_source_review_requests; calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs); calls.append(True)
        if len(calls) == 1:
            if damage == 'caller_packet': data['packet']['physical_rows'][0]['physical_identity']['row_ordinal'] += 1
            elif damage == 'caller_original': data['banks'][0]['join_inputs']['source_sections'][0]['text'] += ' changed'
            elif damage == 'detached_original': kwargs['source_sections'][0]['text'] += ' changed'
            elif damage == 'limits': limits['max_report_bytes'] -= 1
            else: report['schedule']['requests'].pop()
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate)
    with pytest.raises(ValueError):
        if damage == 'offered_report': validate(report, data, limits=limits)
        else: prepare(data, limits=limits)
    assert calls


def test_validator_complete_root_bound_precedes_any_hash(monkeypatch):
    data = material(); report = prepare(data)
    kwargs = arguments(data, limits={'max_original_bytes': 1}); expected = sha(wire(report))
    def forbidden_hash(*args, **kwargs): raise AssertionError('hash before complete-root bound')
    monkeypatch.setattr(hashlib, 'sha256', forbidden_hash)
    with pytest.raises(ValueError):
        owner.validate_shared_source_replay_v1(report, data['packet'], data['source_request_raw'], wire(data['replay_request']),
            expected_report_sha256=expected, **kwargs)



def test_exact_repeated_typed_body_hashes_once_per_catalog_construction_pass():
    data = material()
    result = owner.prepare_shared_source_replay_commitments_v1(data['banks'], EPOCHS)
    coverage, work = result['catalog']['coverage'], result['catalog_work']
    assert coverage['origin_references'] == 8 and coverage['content_records'] == 4
    assert work['body_sha256_calls'] == coverage['content_records']
    assert work['body_sha256_input_bytes'] == coverage['unique_content_bytes']
    assert work['body_sha256_input_bytes'] < coverage['origin_reference_bytes']
    assert work['equality_comparisons'] >= 4
    assert work['compared_candidate_bytes_upper_bound'] >= sum(row['raw_bytes'] for row in result['catalog']['origins'][4:])
    no_raw_bodies(result)


@pytest.mark.parametrize('key', ['max_epochs', 'max_scheduled_requests', 'max_expanded_reference_bytes'])
def test_new_schedule_caps_cannot_be_raised_or_replaced_by_booleans(key, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    for value in (owner.DEFAULT_LIMITS[key] + 1, True):
        with pytest.raises(ValueError): prepare(data, limits={key: value})
    assert calls == []


@pytest.mark.parametrize('limits', [{'max_epochs': 1}, {'max_scheduled_requests': 1}, {'max_expanded_reference_bytes': 1}])
def test_lower_schedule_caps_refuse_whole_plan_before_genuine_replay(limits, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    with pytest.raises(ValueError): prepare(data, limits=limits)
    assert calls == []


@pytest.mark.parametrize('damage', ['request_pin', 'source_pin', 'packet_pin', 'noncanonical', 'final_lf', 'duplicate_key'])
def test_independent_api_pins_and_exact_request_wire_are_required(damage):
    data = material(); kwargs = arguments(data); raw = wire(data['replay_request'])
    if damage == 'request_pin': kwargs['expected_replay_request_sha256'] = '0' * 64
    elif damage == 'source_pin': kwargs['expected_source_request_sha256'] = '0' * 64
    elif damage == 'packet_pin': kwargs['expected_packet_sha256'] = '0' * 64
    elif damage == 'noncanonical': raw = json.dumps(data['replay_request'], indent=2).encode(); kwargs['expected_replay_request_sha256'] = sha(raw)
    elif damage == 'final_lf': raw += b'\n'; kwargs['expected_replay_request_sha256'] = sha(raw)
    else:
        raw = raw[:-1] + b',"schema":"legal-shared-source-replay-request/v1"}'
        kwargs['expected_replay_request_sha256'] = sha(raw)
    with pytest.raises(ValueError):
        owner.prepare_shared_source_replay_v1(data['packet'], data['source_request_raw'], raw, **kwargs)


def test_full_eight_epoch_roster_respects_original_request_count_cap():
    epochs = [{'epoch_id': 'plan:root', 'parent_epoch_id': None}]
    epochs += [{'epoch_id': f'plan:epoch:{index}', 'parent_epoch_id': epochs[0]['epoch_id']} for index in range(1, 8)]
    data = material(epochs=epochs); report = prepare(data)
    assert report['schedule']['coverage']['epochs'] == 8
    assert report['schedule']['coverage']['scheduled_logical_requests'] == 32
    assert report['schedule']['coverage']['scheduled_physical_references'] == 32
    assert len(report['schedule']['forks']) == 1
    assert report['work']['source_bank_preparations'] == 2 and report['work']['history_epoch_replays'] == 0
    flags(report)


def test_ninth_epoch_is_refused_without_truncating_to_the_first_eight():
    data = material()
    epochs = [{'epoch_id': 'plan:root', 'parent_epoch_id': None}]
    epochs += [{'epoch_id': f'plan:epoch:{index}', 'parent_epoch_id': 'plan:root'} for index in range(1, 9)]
    with pytest.raises(ValueError): owner.prepare_shared_source_replay_commitments_v1(data['banks'], epochs)


def test_cyclic_original_graph_is_refused_before_body_hashing(monkeypatch):
    data = material(); bank = deepcopy(data['banks'][0]); bank['join_inputs']['source_sections'][0]['text'] = bank
    def forbidden_hash(*args, **kwargs): raise AssertionError('hash before cyclic graph refusal')
    monkeypatch.setattr(hashlib, 'sha256', forbidden_hash)
    with pytest.raises(ValueError): owner.prepare_shared_source_replay_commitments_v1([bank], EPOCHS)




def test_expanded_reference_budget_is_exact_and_lowered_by_one_refuses_whole_plan():
    data = material()
    catalog = independently_catalog(data['banks'])
    expanded = independently_schedule(data['banks'], EPOCHS, catalog)['coverage']['expanded_reference_bytes']
    accepted = owner.prepare_shared_source_replay_commitments_v1(data['banks'], EPOCHS,
        limits={'max_expanded_reference_bytes': expanded})
    assert accepted['schedule']['coverage']['expanded_reference_bytes'] == expanded
    with pytest.raises(ValueError):
        owner.prepare_shared_source_replay_commitments_v1(data['banks'], EPOCHS,
            limits={'max_expanded_reference_bytes': expanded - 1})


@pytest.mark.parametrize('damage', ['physical_bool', 'epoch_id_bool'])
def test_complete_schedule_identity_inputs_reject_boolean_integer_aliases(damage):
    data = material()
    if damage == 'physical_bool': data['banks'][0]['physical_rows'][0]['physical_row_ordinal'] = False
    else: data['replay_request']['epochs'][0]['epoch_id'] = True
    with pytest.raises(ValueError): prepare(data)


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


def test_real_shared_catalog_preserves_13_16_150_and_complete_two_epoch_forecast(tmp_path, monkeypatch):
    assert os.environ.get('LEGAL_SHARED_SOURCE_REPLAY_ENROLLED') == '1', 'exact original admission required'
    assert os.environ.get('LEGAL_SHARED_SOURCE_REPLAY_INPUTS') == str(REAL_INPUTS)
    root_ref = {'path': str(REAL_INPUTS), 'bytes': REAL_INPUTS_BYTES, 'sha256': REAL_INPUTS_SHA256}
    inputs = read_json(root_ref)
    assert inputs['schema'] == 'legal-shared-source-replay-qualification-inputs/v1'
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
    epochs = inputs['planned_epochs']
    assert epochs == EPOCHS
    replay = replay_request(banks, epochs)
    data = {'banks': banks, 'packet': packet, 'source_request_raw': source_request_raw, 'replay_request': replay}
    original_review = legacy_review.prepare_legacy_source_review_requests
    actual_bank_calls = []
    def counted_review(*args, **kwargs):
        result = original_review(*args, **kwargs)
        actual_bank_calls.append(sha(args[0]))
        return result
    # Count genuine delegate events, not the planned schedule's requested work.
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', counted_review)
    report = prepare(data)
    assert len(actual_bank_calls) == 2
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', original_review)
    assert validate(report, data) == report
    assert report['source_packet'] == packet and report['physical_references'] == packet['physical_rows']
    catalog = independently_catalog(banks)
    schedule = independently_schedule(banks, epochs, catalog)
    assert report['catalog'] == catalog and report['schedule'] == schedule
    assert catalog['coverage']['content_records'] == catalog['coverage']['origin_references'] == 20
    assert catalog['coverage']['unique_content_bytes'] == catalog['coverage']['origin_reference_bytes'] == 45323135
    assert catalog['coverage']['unique_receipt_bytes'] == catalog['coverage']['receipt_origin_bytes'] == 44791887
    assert schedule['coverage']['epochs'] == 2 and schedule['coverage']['scheduled_logical_requests'] == 32
    assert schedule['coverage']['scheduled_physical_references'] == 32
    assert schedule['coverage']['expanded_reference_bytes'] == 724255288
    assert schedule['coverage']['expanded_receipt_reference_bytes'] == 716670192
    assert schedule['coverage']['receipt_reference_lower_bound_exceeds_legacy_cap'] is True
    assert report['work']['source_packet_validation_calls'] == 1
    assert report['work']['source_bank_preparations'] == 2
    assert report['work']['catalog_raw_body_parses'] == report['work']['history_epoch_replays'] == report['work']['authority_memoizations'] == 0
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
    for actual, oracle in zip(packet['physical_rows'], cache_oracles, strict=True):
        assert {key: actual[key] for key in names} == {key: oracle[key] for key in names}
    assert sum(len(bank['preparation']['requests']) for bank in packet['banks']) == 16
    assert sum(len(unit['context_slot_ids']) for bank in packet['banks'] for unit in bank['preparation']['requests']) == 144
    assert sum(len(unit['deferred_review_slot_ids']) for bank in packet['banks'] for unit in bank['preparation']['requests']) == 112
    assert sum(physical['candidate_count'] for _ in epochs for physical in packet['physical_rows']) == 300
    flags(report); fixture_helper().no_authority(packet); no_raw_bodies(report)
    full_raw = wire(packet) + b'\n'; full_path = tmp_path / 'source-correspondence-full-report.json'
    with full_path.open('xb') as stream: stream.write(full_raw)
    full_ref = {'path': str(full_path), **raw_ref(full_raw)}
    source_request_path = tmp_path / 'source-correspondence-request.json'
    with source_request_path.open('xb') as stream: stream.write(source_request_raw)
    source_request_ref = {'path': str(source_request_path), **raw_ref(source_request_raw)}
    replay_raw = wire(replay); replay_path = tmp_path / 'shared-source-replay-request.json'
    with replay_path.open('xb') as stream: stream.write(replay_raw)
    replay_ref = {'path': str(replay_path), **raw_ref(replay_raw)}
    shared_raw = wire(report) + b'\n'; shared_path = tmp_path / 'shared-source-replay-report.json'
    assert len(shared_raw) <= 32 * 1024**2
    with shared_path.open('xb') as stream: stream.write(shared_raw)
    shared_ref = {'path': str(shared_path), **raw_ref(shared_raw)}
    evidence = {'schema': 'legal-shared-source-replay-engineering-evidence/v1', 'coverage': coverage,
        'full_report': full_ref, 'full_report_canonical_sha256': sha(wire(packet)),
        'request_sha256': sha(source_request_raw), 'request_artifact': source_request_ref,
        'request_artifact_wire': 'exact canonical compact sorted Unicode JSON API bytes without final LF',
        'shared_replay_report': shared_ref, 'shared_replay_report_canonical_sha256': sha(wire(report)),
        'replay_request_artifact': replay_ref, 'replay_request_sha256': sha(replay_raw),
        'catalog_coverage': catalog['coverage'], 'schedule_coverage': schedule['coverage'], 'work': report['work'],
        'actual_prepare_bank_replay_calls': len(actual_bank_calls),
        'original_input_refs': [root_ref] + inputs['productive_originals'],
        'physical_cache_oracles': cache_oracles, 'retained_source_oracles': source_oracles,
        'exact_candidate_geometry_checked': 150, 'scheduled_candidate_references': 300,
        'actual_submitted_reviews': 0, 'selected_occurrences': 0, 'source_decisions_applied': 0,
        'actual_source_adoptions': 0, 'actual_history_epoch_replays': 0, 'planned_epochs_are_executed': False,
        'actual_saved_work_or_speedup_measured': False,
        'original_parent_or26shards_opened': False, 'fresh_cache_table_verification': False,
        'fresh_full_raw_row_hash_recomputation': False, 'correspondence_authority': packet['authority'],
        'authority': report['authority'], 'training_mask': 0, 'evaluation_gold_mask': 0, 'inference_view': None,
        'worker_lifetime_peak_rss_linux_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_scope': 'Linux worker lifetime peak includes bootstrap and fixtures; not an isolated owner peak or a memory bound proof.'}
    assert len(evidence['original_input_refs']) == 29
    with (tmp_path / EVIDENCE_NAME).open('xb') as stream: stream.write(wire(evidence) + b'\n')
