"""Original-bound source review requests preserve complete physical populations.

Authored helpers are fictional. The one explicitly enrolled retained-data case
replays saved source/cache declarations without opening parent Parquet, metadata
shards or cache tables. Neither case supplies reviews or adopts governing law.
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
from ipfs_datasets_py.logic.autoformal import legal_source_correspondence_requests_v1 as owner


ROOT = Path('/home/barberb/lift_coding')
REAL_INPUTS = ROOT / 'artifacts/legal-ir-source-correspondence-20261019-01/inputs.json'
REAL_INPUTS_BYTES = 15872
REAL_INPUTS_SHA256 = '0cc1a5d2798b9a1512619f6665cabb49adcbc6625f963681e533062855483112'
EVIDENCE_NAME = 'source-correspondence-requests-engineering-evidence.json'
REQUEST_SCHEMA = 'legal-source-correspondence-request/v1'
PROFILE = 'complete-declared-physical-source-review-requests/v1'
ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353, 3354, 3355, 3357, 3358]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_ref(raw):
    return {'bytes': len(raw), 'sha256': sha(raw)}


def original_bank_sha256(bank):
    """Independently author the published commitment recipe, without owner help."""
    projection = deepcopy(bank)
    projection['join_bytes'] = raw_ref(bank['join_bytes'])
    projection['paired_row_bytes'] = [raw_ref(raw) for raw in bank['paired_row_bytes']]
    receipt = bank['join_inputs']['producer_receipt_bytes']
    projection['join_inputs']['producer_receipt_bytes'] = None if receipt is None else raw_ref(receipt)
    return sha(wire(projection))


def fixture_helper():
    """Use tiny authored constructors only; prior test functions are not selected."""
    path = Path(__file__).with_name('test_corpus_legacy_source_review.py')
    spec = importlib.util.spec_from_file_location('fictional_source_request_fixture', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request_for(banks):
    return {'schema': REQUEST_SCHEMA, 'profile': PROFILE, 'banks': [
        {'bank_id': bank['bank_id'], 'original_bank_sha256': original_bank_sha256(bank),
         'physical_rows': len(bank['physical_rows']), 'logical_rows': len(bank['paired_row_bytes'])}
        for bank in banks]}


def material(*, fanout=False, unavailable=None, second=True):
    banks = []
    for index in range(2):
        data = fixture_helper().case(second=second, unavailable=unavailable)
        physical = []
        for ordinal, request_ordinal in enumerate(range(len(data['rows']))):
            physical.append({'physical_row_ordinal': ordinal, 'request_ordinal': request_ordinal,
                'physical_identity': {'repository_id': 'fixture:cache', 'revision': str(index + 1) * 40,
                    'path_in_repo': f'paired/bank-{index}.parquet',
                    'artifact_sha256': sha(f'fictional cache table {index}'.encode()), 'row_ordinal': ordinal}})
        if fanout and index == 0:
            physical.append({'physical_row_ordinal': len(physical), 'request_ordinal': 0,
                'physical_identity': {**deepcopy(physical[0]['physical_identity']), 'row_ordinal': len(physical)}})
        banks.append({'bank_id': f'fixture:bank:{index}', 'join_bytes': data['join_bytes'],
                      'paired_row_bytes': data['rows'], 'join_inputs': data['inputs'], 'physical_rows': physical})
    return {'banks': banks, 'request': request_for(banks)}


def prepare(data, *, limits=None):
    raw = wire(data['request'])
    return owner.prepare_source_correspondence_requests_v1(raw,
        expected_request_sha256=sha(raw), original_banks=data['banks'], limits=limits)


def validate(report, data, *, limits=None):
    raw = wire(data['request'])
    return owner.validate_source_correspondence_requests_v1(report, raw,
        expected_report_sha256=sha(wire(report)), expected_request_sha256=sha(raw),
        original_banks=data['banks'], limits=limits)


def no_authority(report):
    assert report['authority'] and all(value is False for value in report['authority'].values())
    assert type(report['training_mask']) is int and report['training_mask'] == 0
    assert type(report['evaluation_gold_mask']) is int and report['evaluation_gold_mask'] == 0
    assert report['inference_view'] is None
    assert report['coverage']['selected_occurrences'] == report['coverage']['source_decisions_applied'] == 0
    for row in report['physical_rows']:
        assert row['selected_occurrence'] is row['governing_source'] is row['inference_view'] is None
        assert type(row['training_mask']) is type(row['evaluation_gold_mask']) is int
        assert row['training_mask'] == row['evaluation_gold_mask'] == 0
    for bank in report['banks']:
        for request in bank['preparation']['requests']:
            assert request['selected_occurrence'] is None
            assert request['original_producer_occurrence_attested'] is False
            assert all(question['answer'] is None for question in request['review_questions'])


def assert_geometry(report):
    observed = 0
    for bank in report['banks']:
        preparation = bank['preparation']
        for request in preparation['requests']:
            row = request['original_row']
            assert row['selected_occurrence'] is None and row['original_producer_occurrence_attested'] is False
            assert row['occurrence_count'] == len(row['candidates'])
            for candidate in row['candidates']:
                section = preparation['source_sections'][candidate['source_section_index']]
                occurrence = candidate['source_occurrence']
                text, span = section['extracted_text'], occurrence['span_text']
                assert text[occurrence['start_char']:occurrence['end_char']] == span
                assert text.encode('utf-8')[occurrence['start_utf8']:occurrence['end_utf8']] == span.encode('utf-8')
                assert occurrence['span_sha256'] == sha(span.encode('utf-8'))
                assert section['provenance']['text_sha256'] == sha(text.encode('utf-8'))
                assert candidate['context_declaration']['availability'] == 'required_unavailable'
                observed += 1
    return observed


def test_two_banks_keep_all_original_questions_and_unicode_candidates():
    data = material()
    before = [original_bank_sha256(bank) for bank in data['banks']]
    report = prepare(data)
    assert [original_bank_sha256(bank) for bank in data['banks']] == before
    assert report['schema'] == 'legal-source-correspondence-requests/v1'
    assert report['profile'] == PROFILE
    assert report['coverage']['banks'] == 2
    assert report['coverage']['logical_requests'] == report['coverage']['physical_rows'] == 4
    assert assert_geometry(report) == 6
    first = report['banks'][0]['preparation']['requests'][0]['original_row']['candidates']
    assert [candidate['source_occurrence']['start_char'] for candidate in first] == [7, 14]
    assert [candidate['source_occurrence']['start_utf8'] for candidate in first] == [9, 16]
    assert validate(report, data) == report
    assert owner.source_correspondence_requests_sha256(report) == sha(wire(report))
    no_authority(report)


def test_repeated_raw_bytes_at_distinct_physical_coordinates_keep_every_reference():
    data = material(fanout=True)
    report = prepare(data)
    assert report['coverage']['logical_requests'] == 4
    assert report['coverage']['physical_rows'] == report['coverage']['distinct_physical_identities'] == 5
    first, extra = report['physical_rows'][0], report['physical_rows'][2]
    assert first['request_ordinal'] == extra['request_ordinal'] == 0
    assert first['paired_row_sha256'] == extra['paired_row_sha256']
    assert first['physical_identity'] != extra['physical_identity']
    assert first['request_ref'] == extra['request_ref']
    assert len(report['banks'][0]['preparation']['requests']) == 2
    assert validate(report, data) == report
    no_authority(report)


def test_cross_bank_same_physical_reference_remains_two_declared_observations():
    data = material()
    data['banks'][1]['physical_rows'] = deepcopy(data['banks'][0]['physical_rows'])
    data['request'] = request_for(data['banks'])
    report = prepare(data)
    assert report['coverage']['physical_rows'] == 4
    assert report['coverage']['distinct_physical_identities'] == 2
    assert len(report['physical_rows']) == 4
    assert validate(report, data) == report


@pytest.mark.parametrize('unavailable,disposition', [
    ('receipt', 'producer_source_unavailable'),
    ('section', 'source_section_unavailable'),
])
def test_independently_declared_unavailable_inputs_keep_all_rows(unavailable, disposition):
    data = material(unavailable=unavailable)
    report = prepare(data)
    assert report['coverage']['logical_requests'] == report['coverage']['physical_rows'] == 4
    assert report['coverage']['disposition_counts'][disposition] == 4
    assert report['coverage']['candidate_occurrence_references'] == 0
    assert validate(report, data) == report
    no_authority(report)


def test_public_bank_digest_matches_independent_recipe_and_changes_with_coordinates():
    data = material()
    bank = data['banks'][0]
    expected = original_bank_sha256(bank)
    assert owner.source_correspondence_original_bank_sha256(bank) == expected
    changed = deepcopy(bank)
    changed['physical_rows'][0]['physical_identity']['row_ordinal'] = 91
    assert owner.source_correspondence_original_bank_sha256(changed) == original_bank_sha256(changed) != expected


def test_returned_packet_and_validator_are_detached_from_originals():
    data = material()
    report = prepare(data)
    checked = validate(report, data)
    report['physical_rows'][0]['physical_identity']['path_in_repo'] = 'mutated'
    report['banks'][0]['preparation']['requests'][0]['original_row']['candidates'].clear()
    assert checked['physical_rows'][0]['physical_identity']['path_in_repo'] != 'mutated'
    assert len(checked['banks'][0]['preparation']['requests'][0]['original_row']['candidates']) == 2
    data['banks'][0]['join_inputs']['source_sections'][0]['text'] = 'changed after operation'
    assert checked['banks'][0]['preparation']['source_sections'][0]['extracted_text'] == '§ Café Clerk; Clerk.'


@pytest.mark.parametrize('damage', [
    'wrong_request_sha', 'noncanonical', 'final_lf', 'duplicate_key', 'nonfinite', 'extra_field',
    'wrong_schema', 'wrong_profile', 'drop_bank', 'reverse_banks', 'duplicate_bank', 'bank_digest',
    'physical_count_bool', 'logical_count_bool', 'physical_count_wrong', 'logical_count_wrong', 'huge_integer',
])
def test_request_and_original_population_refusals_happen_before_review_work(damage, monkeypatch):
    data = material()
    request = deepcopy(data['request'])
    if damage == 'extra_field': request['extra'] = None
    elif damage == 'wrong_schema': request['schema'] += '-other'
    elif damage == 'wrong_profile': request['profile'] += '-other'
    elif damage == 'drop_bank': request['banks'].pop()
    elif damage == 'reverse_banks': request['banks'].reverse()
    elif damage == 'duplicate_bank': request['banks'][1] = deepcopy(request['banks'][0])
    elif damage == 'bank_digest': request['banks'][0]['original_bank_sha256'] = '0' * 64
    elif damage == 'physical_count_bool': request['banks'][0]['physical_rows'] = True
    elif damage == 'logical_count_bool': request['banks'][0]['logical_rows'] = True
    elif damage == 'physical_count_wrong': request['banks'][0]['physical_rows'] += 1
    elif damage == 'logical_count_wrong': request['banks'][0]['logical_rows'] += 1
    raw = wire(request)
    if damage == 'noncanonical': raw = json.dumps(request, indent=2).encode()
    elif damage == 'final_lf': raw += b'\n'
    elif damage == 'duplicate_key': raw = raw[:-1] + b',"schema":"' + REQUEST_SCHEMA.encode() + b'"}'
    elif damage == 'nonfinite': raw = raw[:-1] + b',"notfinite":NaN}'
    elif damage == 'huge_integer': raw = raw[:-1] + b',"unbounded":' + b'9' * 5000 + b'}'
    expected = '0' * 64 if damage == 'wrong_request_sha' else sha(raw)
    called = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
                        lambda *args, **kwargs: called.append(True))
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        owner.prepare_source_correspondence_requests_v1(raw,
            expected_request_sha256=expected, original_banks=data['banks'])
    assert called == []


@pytest.mark.parametrize('damage', [
    'drop_original_bank', 'reverse_original_banks', 'duplicate_bank_id', 'unknown_bank_field',
    'drop_physical', 'duplicate_physical', 'reorder_physical', 'wrong_physical_ordinal',
    'uncovered_request', 'out_of_range_request', 'bool_request_ordinal', 'bool_table_ordinal',
    'bool_physical_ordinal', 'physical_path', 'physical_sha', 'physical_revision',
    'bool_source_artifact_bytes', 'bool_source_row_index', 'physical_byte_conflict',
])
def test_original_shapes_counts_and_physical_mapping_are_closed_before_review(damage, monkeypatch):
    data = material()
    banks = data['banks']
    if damage == 'drop_original_bank': banks.pop()
    elif damage == 'reverse_original_banks': banks.reverse()
    elif damage == 'duplicate_bank_id': banks[1]['bank_id'] = banks[0]['bank_id']
    elif damage == 'unknown_bank_field': banks[0]['extra'] = None
    elif damage == 'bool_source_artifact_bytes': banks[0]['join_inputs']['source_sections'][0]['artifact_bytes'] = True
    elif damage == 'bool_source_row_index': banks[0]['join_inputs']['source_sections'][0]['parquet_row_index'] = False
    elif damage == 'physical_byte_conflict':
        banks[1]['physical_rows'] = deepcopy(banks[0]['physical_rows'])
        banks[1]['physical_rows'][0]['request_ordinal'] = 1
        banks[1]['physical_rows'][1]['request_ordinal'] = 0
        data['request'] = request_for(banks)
    else:
        rows = banks[0]['physical_rows']
        if damage == 'drop_physical': rows.pop()
        elif damage == 'duplicate_physical': rows[1]['physical_identity'] = deepcopy(rows[0]['physical_identity'])
        elif damage == 'reorder_physical': rows.reverse()
        elif damage == 'wrong_physical_ordinal': rows[0]['physical_row_ordinal'] = 8
        elif damage == 'uncovered_request': rows[1]['request_ordinal'] = 0
        elif damage == 'out_of_range_request': rows[0]['request_ordinal'] = 2
        elif damage == 'bool_request_ordinal': rows[0]['request_ordinal'] = True
        elif damage == 'bool_table_ordinal': rows[0]['physical_identity']['row_ordinal'] = True
        elif damage == 'bool_physical_ordinal': rows[0]['physical_row_ordinal'] = False
        elif damage == 'physical_path': rows[0]['physical_identity']['path_in_repo'] = '../alias.parquet'
        elif damage == 'physical_sha': rows[0]['physical_identity']['artifact_sha256'] = 'x' * 64
        elif damage == 'physical_revision': rows[0]['physical_identity']['revision'] = True
    called = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
                        lambda *args, **kwargs: called.append(True))
    raw = wire(data['request'])
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        owner.prepare_source_correspondence_requests_v1(raw,
            expected_request_sha256=sha(raw), original_banks=banks)
    assert called == []


@pytest.mark.parametrize('damage', [
    'dropped_bank', 'dropped_physical', 'reordered_physical', 'dropped_candidate', 'reordered_candidates',
    'shifted_utf8', 'authority', 'training_mask', 'gold_mask', 'governing_source', 'selected_occurrence',
    'physical_identity',
])
def test_rehashed_report_tampering_cannot_replace_full_original_regeneration(damage):
    data = material()
    report = prepare(data)
    request = report['banks'][0]['preparation']['requests'][0]
    if damage == 'dropped_bank': report['banks'].pop()
    elif damage == 'dropped_physical': report['physical_rows'].pop()
    elif damage == 'reordered_physical': report['physical_rows'].reverse()
    elif damage == 'dropped_candidate': request['original_row']['candidates'].pop()
    elif damage == 'reordered_candidates': request['original_row']['candidates'].reverse()
    elif damage == 'shifted_utf8': request['original_row']['candidates'][0]['source_occurrence']['start_utf8'] += 1
    elif damage == 'authority': report['authority']['source_correspondence_verified'] = True
    elif damage == 'training_mask': report['training_mask'] = 1
    elif damage == 'gold_mask': report['physical_rows'][0]['evaluation_gold_mask'] = True
    elif damage == 'governing_source': report['physical_rows'][0]['governing_source'] = 'invented adoption'
    elif damage == 'selected_occurrence': report['physical_rows'][0]['selected_occurrence'] = 'unique does not select'
    elif damage == 'physical_identity': report['physical_rows'][0]['physical_identity']['row_ordinal'] += 1
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        validate(report, data)


@pytest.mark.parametrize('key', [
    'max_banks', 'max_physical_rows', 'max_original_bytes', 'max_report_bytes',
    'max_request_bytes', 'max_json_nodes', 'max_json_depth', 'max_string_bytes',
])
def test_hard_caps_cannot_be_increased_or_replaced_by_boolean(key, monkeypatch):
    data = material()
    called = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
                        lambda *args, **kwargs: called.append(True))
    for invalid in (owner.DEFAULT_LIMITS[key] + 1, True):
        with pytest.raises(owner.SourceCorrespondenceRequestsError):
            prepare(data, limits={key: invalid})
    assert called == []


@pytest.mark.parametrize('limits', [
    {'max_banks': 1}, {'max_physical_rows': 1}, {'max_original_bytes': 1},
    {'max_request_bytes': 1}, {'max_json_nodes': 1}, {'max_json_depth': 1}, {'max_string_bytes': 1},
])
def test_lowered_input_caps_refuse_before_delegation(limits, monkeypatch):
    data = material()
    called = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
                        lambda *args, **kwargs: called.append(True))
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        prepare(data, limits=limits)
    assert called == []


@pytest.mark.parametrize('damage', ['original_text', 'physical_coordinate', 'limits', 'detached_original_text'])
def test_closing_fence_refuses_mutation_during_genuine_review_work(damage, monkeypatch):
    data = material()
    limits = {'max_report_bytes': owner.DEFAULT_LIMITS['max_report_bytes']}
    original = legacy_review.prepare_legacy_source_review_requests
    original_caller_pins = [original_bank_sha256(bank) for bank in data['banks']]
    called = []
    def mutate_after_work(*args, **kwargs):
        result = original(*args, **kwargs)
        called.append(True)
        if len(called) == 1:
            if damage == 'original_text': data['banks'][0]['join_inputs']['source_sections'][0]['text'] += ' changed'
            elif damage == 'physical_coordinate': data['banks'][0]['physical_rows'][0]['physical_identity']['row_ordinal'] += 99
            elif damage == 'detached_original_text': kwargs['source_sections'][0]['text'] += ' changed inside replay'
            else: limits['max_report_bytes'] -= 1
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate_after_work)
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        prepare(data, limits=limits)
    assert called
    if damage == 'detached_original_text':
        assert [original_bank_sha256(bank) for bank in data['banks']] == original_caller_pins


def test_lowered_output_cap_refuses_whole_packet_after_genuine_first_bank(monkeypatch):
    data = material()
    original = legacy_review.prepare_legacy_source_review_requests
    called = []
    def actual(*args, **kwargs):
        result = original(*args, **kwargs)
        called.append(True)
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', actual)
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        prepare(data, limits={'max_report_bytes': 256})
    assert len(called) == 1


def test_utf8_string_byte_bound_refuses_before_review_even_when_character_count_fits(monkeypatch):
    data = material()
    data['banks'][0]['bank_id'] = 'é' * 100
    data['request'] = request_for(data['banks'])
    called = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
                        lambda *args, **kwargs: called.append(True))
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        prepare(data, limits={'max_string_bytes': 150})
    assert called == []


def test_unknown_limit_cannot_change_the_resource_contract(monkeypatch):
    data = material()
    called = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
                        lambda *args, **kwargs: called.append(True))
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        prepare(data, limits={'max_receipt_bytes': 1})
    assert called == []


def test_same_citation_substituted_text_does_not_replace_exact_original_source():
    data = material()
    # Keep the citation and physical locator; declare different text and repin
    # the outer bank. The exact retained join must still refuse substitution.
    section = data['banks'][0]['join_inputs']['source_sections'][0]
    section['text'] += ' a different edition'
    section['text_sha256'] = sha(section['text'].encode('utf-8'))
    data['banks'][0]['join_inputs']['expected_source_sections'][0]['text_sha256'] = section['text_sha256']
    data['request'] = request_for(data['banks'])
    with pytest.raises(ValueError):
        prepare(data)


def test_no_exact_match_is_retained_without_normalizing_away_the_difference():
    fixture = fixture_helper().case(text='Clerk  shall', span='Clerk shall')
    data = material(second=False)
    for bank in data['banks']:
        bank['join_bytes'] = fixture['join_bytes']
        bank['paired_row_bytes'] = fixture['rows']
        bank['join_inputs'] = deepcopy(fixture['inputs'])
    data['request'] = request_for(data['banks'])
    report = prepare(data)
    assert report['coverage']['logical_requests'] == report['coverage']['physical_rows'] == 2
    assert report['coverage']['disposition_counts'] == {'no_exact_occurrence': 2}
    assert report['coverage']['candidate_occurrence_references'] == 0
    assert validate(report, data) == report
    no_authority(report)


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


def test_real_retained_two_banks_sixteen_requests_and_all_150_candidates(tmp_path):
    assert os.environ.get('LEGAL_SOURCE_CORRESPONDENCE_ENROLLED') == '1', 'exact original admission required'
    assert os.environ.get('LEGAL_SOURCE_CORRESPONDENCE_INPUTS') == str(REAL_INPUTS)
    root_ref = {'path': str(REAL_INPUTS), 'bytes': REAL_INPUTS_BYTES, 'sha256': REAL_INPUTS_SHA256}
    inputs = read_json(root_ref)
    assert inputs['schema'] == 'legal-source-correspondence-qualification-inputs/v1'
    refs = inputs['originals']
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
    for declaration, supplied in zip(declarations['banks'], inputs['banks'], strict=True):
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
    data = {'banks': banks, 'request': request_for(banks)}
    request_raw = wire(data['request'])
    report = prepare(data)
    assert validate(report, data) == report
    coverage = report['coverage']
    assert coverage['banks'] == 2
    assert coverage['logical_requests'] == coverage['physical_rows'] == coverage['distinct_physical_identities'] == 16
    assert coverage['source_section_references'] == coverage['distinct_source_sections'] == 13
    assert coverage['candidate_occurrence_references'] == 150
    assert coverage['unique_candidate_rows'] == 11 and coverage['ambiguous_candidate_rows'] == 5
    assert coverage['disposition_counts'] == {'unique_exact_candidate': 11, 'ambiguous_exact_candidates': 5}
    assert assert_geometry(report) == 150
    assert len(report['physical_rows']) == len(cache_oracles) == 16
    for actual, oracle in zip(report['physical_rows'], cache_oracles, strict=True):
        assert {key: actual[key] for key in ('bank_id', 'physical_row_ordinal', 'physical_identity',
            'paired_row_sha256', 'candidate_occurrence_ids')} == {key: oracle[key] for key in (
                'bank_id', 'physical_row_ordinal', 'physical_identity', 'paired_row_sha256', 'candidate_occurrence_ids')}
    for bank, original in zip(report['banks'], banks, strict=True):
        retained_join = json.loads(original['join_bytes'])
        assert bank['preparation']['source_sections'] == retained_join['source_sections']
        assert [request['original_row'] for request in bank['preparation']['requests']] == retained_join['rows']
    no_authority(report)
    request_transport = request_raw
    request_path = tmp_path / 'source-correspondence-request.json'
    with request_path.open('xb') as stream:
        stream.write(request_transport)
    request_ref = {'path': str(request_path), **raw_ref(request_transport)}
    full_raw = wire(report) + b'\n'
    assert len(full_raw) <= 32 * 1024**2
    full_path = tmp_path / 'source-correspondence-full-report.json'
    with full_path.open('xb') as stream:
        stream.write(full_raw)
    full_ref = {'path': str(full_path), **raw_ref(full_raw)}
    evidence = {'schema': 'legal-source-correspondence-requests-engineering-evidence/v1',
        'coverage': coverage, 'full_report': full_ref, 'full_report_canonical_sha256': sha(wire(report)),
        'request_sha256': sha(request_raw), 'request_artifact': request_ref,
        'request_artifact_wire': 'exact canonical compact sorted Unicode JSON API bytes without final LF',
        'original_input_refs': [root_ref] + inputs['productive_originals'],
        'physical_cache_oracles': cache_oracles, 'retained_source_oracles': source_oracles,
        'exact_candidate_geometry_checked': 150, 'actual_submitted_reviews': 0,
        'selected_occurrences': 0, 'source_decisions_applied': 0,
        'original_parent_or26shards_opened': False, 'fresh_cache_table_verification': False,
        'fresh_full_raw_row_hash_recomputation': False,
        'authority': report['authority'], 'training_mask': 0, 'evaluation_gold_mask': 0, 'inference_view': None,
        'worker_lifetime_peak_rss_linux_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_scope': 'Linux worker lifetime peak includes bootstrap and fixtures; not an isolated owner peak or a memory bound proof.'}
    assert len(evidence['original_input_refs']) == 26
    with (tmp_path / EVIDENCE_NAME).open('xb') as stream:
        stream.write(wire(evidence) + b'\n')
# Coordinate-originals custody is a separate opt-in source-request profile.
# Every positive here uses the genuine paired producer, Arrow transport,
# original-input graph replay and unchanged legacy review owner. The authored
# receipt/source declarations are fictional inputs, never statutory evidence.
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as _coordinate_legacy_join
from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as _coordinate_corpus
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as _coordinate_graph
from ipfs_datasets_py.logic.autoformal import paired_span_census as _coordinate_paired
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes as _coordinate_cid
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import (
    coordinate_join as _correspondence_base_join,
)
from tests.unit.logic.autoformal.test_legal_paired_coordinate_intake_v2 import (
    build_coordinate_payload as _correspondence_coordinate_payload,
)
from tests.unit.logic.autoformal.test_legal_span_cache_intake import (
    coordinate_graph_v2_case,
    _prepare_coordinate_graph_v2,
    _coordinate_graph_v2_request,
)


_CORRESPONDENCE_RULE = {
    'modality': 'O', 'actor': 'Clerk', 'action': 'file', 'object': 'report',
    'conditions': [], 'exceptions': [], 'temporal': [],
}
_CORRESPONDENCE_DOCUMENT = {
    'z_metadata': 'first', 'a_metadata': 'second', 'legal_id': 'usc:us:5:551',
    'text': 'Unselected Ω context. Clerk shall file report.',
}


@pytest.fixture
def coordinate_join(_correspondence_base_join, tmp_path, request):
    """Author receipt originals before a fresh genuine producer captures them."""
    options = getattr(request, 'param', {})
    case = deepcopy(_correspondence_base_join)
    coordinate = _correspondence_coordinate_payload(tmp_path / 'correspondence-stock',
        documents=[_CORRESPONDENCE_DOCUMENT, _CORRESPONDENCE_DOCUMENT],
        selected_indices=(1, 3),
        compiler_rule=None if options.get('unsupported') else _CORRESPONDENCE_RULE)
    sections, expected_sections = [], []
    observations = deepcopy(coordinate['observations'])
    receipt = None
    if options.get('receipt', True):
        producer_rows = []
        for index, observation in enumerate(observations):
            text = observation['text']
            section_text = '§ Ω ' + text + ' ' + text
            provenance = {
                'repository_id': 'justicedao/ipfs_uscode', 'revision': 'd' * 40,
                'path_in_repo': 'uscode_parquet/laws.parquet',
                'artifact_sha256': sha(b'fictional independent source artifact'),
                'artifact_bytes': 4000, 'release_id': coordinate['report']['release_id'],
                'parquet_row_index': index, 'entry_cid': _coordinate_cid(('authored-row-' + str(index)).encode()),
                'legal_id': observation['legal_id'], 'text_sha256': sha(section_text.encode()),
            }
            sections.append({**provenance, 'text': section_text})
            expected_sections.append(provenance)
            observation['logic_target_observation'] = {}
            producer_rows.append({
                'source_span_id': observation['source_span_id'], 'text': text,
                'source_sha256': sha(text.encode()), 'legal_id': observation['legal_id'],
                'entry_cid': provenance['entry_cid'], 'source_section_offset': index,
                'source_parent': {
                    'repository_id': provenance['repository_id'], 'revision': provenance['revision'],
                    'path_in_repo': provenance['path_in_repo'], 'sha256': provenance['artifact_sha256'],
                    'bytes': provenance['artifact_bytes'], 'release_id': provenance['release_id'],
                }, 'logic_target_observation': {},
            })
        receipt = {'schema_version': 'fictional-independent-coordinate-source-producer/v1',
                   'rows': producer_rows}
    bundle = _coordinate_paired.build_paired_census(observations,
        agent_id='coordinate-source-correspondence', code_identity='authored:source-correspondence',
        model_identity='diagnostic:test', release_id=coordinate['report']['release_id'],
        original_receipt=receipt, source_coordinate_report=coordinate['report'],
        expected_source_coordinate_report_sha256=coordinate['pin'])
    written = _coordinate_paired.write_paired_census_bundle(bundle, tmp_path / 'correspondence-producer')
    retained = (tmp_path / 'correspondence-retained' / ('a' * 40)).absolute()
    for kind in (*_coordinate_paired.TABLE_NAMES, 'manifest'):
        entry = written[kind]
        destination = retained / entry['path_in_repo']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(Path(entry['path']).read_bytes())
    location = {**coordinate['request'], 'repository_root': retained,
        'manifest_path_in_repo': written['manifest']['path_in_repo'],
        'expected_manifest_sha256': written['manifest']['sha256']}
    coordinate.update(request=location, bundle=bundle, observations=observations, written=written)
    path = location['manifest_path_in_repo']
    manifest_raw = (retained / path).read_bytes()
    case['coordinate'] = coordinate
    case['manifests'] = {path: manifest_raw}
    case['paired_request']['manifests'] = [{'path_in_repo': path, 'bytes': len(manifest_raw),
        'sha256': sha(manifest_raw), 'source_coordinate_report_sha256': coordinate['pin']}]
    case['request']['paired_inventory_request_sha256'] = sha(wire(case['paired_request']))
    case['request']['paired_bundles'] = [{'manifest_path_in_repo': path, 'repository_root': str(retained)}]
    receipt_raw = None if receipt is None else _coordinate_paired.decode_artifact(next(
        artifact for artifact in bundle['artifacts'] if artifact['kind'] == 'original_producer_receipt'))
    case['_correspondence_originals'] = {
        'producer_receipt_bytes': receipt_raw,
        'expected_producer_receipt_sha256': None if receipt_raw is None else sha(receipt_raw),
        'source_sections': sections, 'expected_source_sections': expected_sections,
    }
    case['_correspondence_options'] = options
    return case


@pytest.fixture
def coordinate_correspondence_case(coordinate_graph_v2_case):
    upstream = coordinate_graph_v2_case
    graph = _prepare_coordinate_graph_v2(upstream)
    graph_raw = json.dumps(graph, ensure_ascii=False, indent=2).encode()
    graph_request_raw = _coordinate_graph_v2_request(upstream)
    originals = {'request_raw': graph_request_raw, 'eligibility_report_raw': upstream['eligibility_raw'],
        'eligibility_request_raw': upstream['eligibility_request_raw'],
        'join_manifest_raw': upstream['join_raw'], 'expected_request_sha256': sha(graph_request_raw),
        'join_originals': upstream['originals'], 'source_bindings': upstream['bindings']}
    options = upstream['case']['_correspondence_options']
    payload = upstream['joined']['paired_bundles'][0]['payload_intake']['rows']
    coverage = options.get('covered_rows', len(payload))
    rows = [row['derived_row_json'].encode() for row in payload[:coverage]]
    join_inputs = deepcopy(upstream['case']['_correspondence_originals'])
    join_inputs['expected_population'] = [{
        'row_sha256': sha(raw), 'source_span_id': json.loads(raw)['source']['span_id'],
        'text_sha256': json.loads(raw)['source']['text_sha256'],
        'source_revision': json.loads(raw)['source']['revision'],
    } for raw in rows]
    ledger = _coordinate_legacy_join.build_legacy_source_join(rows, **join_inputs)
    banks = []
    for index in range(options.get('banks', 1)):
        physical = []
        for ordinal, row in enumerate(graph['physical_rows'][:coverage]):
            identity = deepcopy(row['physical_identity'])
            identity['artifact_sha256'] = identity.pop('file_sha256')
            physical.append({'physical_row_ordinal': ordinal, 'request_ordinal': ordinal,
                             'physical_identity': identity})
        banks.append({'bank_id': 'authored-coordinate-source-bank:' + str(index),
            'join_bytes': wire(ledger), 'paired_row_bytes': list(rows),
            'join_inputs': deepcopy(join_inputs), 'physical_rows': physical})
    source_raw = wire(request_for(banks))
    slots = [{'physical_row_ordinal': ordinal,
        'physical_identity_sha256': row['physical_identity_sha256'],
        'review_nominations': [{'bank_ordinal': bank_index, 'bank_physical_row_ordinal': ordinal}
            for bank_index in range(len(banks))] if ordinal < coverage else []}
        for ordinal, row in enumerate(graph['physical_rows'])]
    return {'upstream': upstream, 'graph': graph, 'graph_raw': graph_raw, 'originals': originals,
            'banks': banks, 'source_raw': source_raw, 'slots': slots}


def _coordinate_correspondence_request(case, **changes):
    return wire({'schema': 'legal-source-correspondence-request/v2',
        'profile': 'original-input-coordinate-graph-v2-source-review-request-custody/v1',
        'graph_report_raw_sha256': sha(case['graph_raw']),
        'graph_report_sha256': _coordinate_graph.coordinate_source_graph_intake_sha256(case['graph']),
        'graph_originals_sha256': _coordinate_corpus.coordinate_graph_corpus_originals_sha256(case['originals']),
        'source_request_sha256': sha(case['source_raw']), 'physical_review_nominations': case['slots'], **changes})


def _prepare_coordinate_correspondence(case, *, request_raw=None, limits=None):
    raw = _coordinate_correspondence_request(case) if request_raw is None else request_raw
    return owner.prepare_source_correspondence_requests_v2(raw, case['graph_raw'], case['source_raw'],
        expected_request_sha256=sha(raw), graph_originals=case['originals'],
        original_banks=case['banks'], limits=limits)


def _validate_coordinate_correspondence(report, case, *, expected_report_sha256=None):
    raw = _coordinate_correspondence_request(case)
    return owner.validate_source_correspondence_requests_v2(report, raw, case['graph_raw'], case['source_raw'],
        expected_report_sha256=sha(wire(report)) if expected_report_sha256 is None else expected_report_sha256,
        expected_request_sha256=sha(raw), graph_originals=case['originals'], original_banks=case['banks'])


def _coordinate_correspondence_no_authority(report):
    assert report['authority'] and all(value is False for value in report['authority'].values())
    assert type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert report['selected_occurrence'] is report['governing_source'] is report['governing_definition_use'] is None
    for binding in (*report['physical_review_bindings'], *report['output_occurrence_bindings']):
        assert binding['selected_occurrence'] is binding['governing_source'] is None
        for field in ('source_binding_mask', 'training_mask', 'evaluation_gold_mask'):
            assert type(binding[field]) is int and binding[field] == 0
    no_authority(report['source_preparation'])


def _coordinate_correspondence_repin_banks(case):
    case['source_raw'] = wire(request_for(case['banks']))


def test_coordinate_correspondence_real_receipt_and_review_preparation_roundtrip(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    assert report['schema'] == 'legal-source-correspondence-requests/v2'
    assert report['source_preparation'] == owner.prepare_source_correspondence_requests_v1(
        case['source_raw'], expected_request_sha256=sha(case['source_raw']), original_banks=case['banks'])
    assert assert_geometry(report['source_preparation']) == 4
    assert all(row['source_disposition'] == 'ambiguous_exact_candidates'
               for row in report['source_preparation']['physical_rows'])
    assert _validate_coordinate_correspondence(report, case) == report
    assert owner.source_correspondence_requests_v2_sha256(report) == sha(wire(report))
    _coordinate_correspondence_no_authority(report)


@pytest.mark.parametrize('coordinate_join', [{'receipt': False}], indirect=True)
def test_coordinate_correspondence_real_unavailable_receipt_remains_unresolved(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    assert report['source_preparation']['coverage']['candidate_occurrence_references'] == 0
    assert all(row['source_disposition'] == 'producer_source_unavailable'
               for row in report['source_preparation']['physical_rows'])
    assert _validate_coordinate_correspondence(report, case) == report
    _coordinate_correspondence_no_authority(report)


@pytest.mark.parametrize('coordinate_join', [{'banks': 2}], indirect=True)
def test_coordinate_correspondence_multibank_alternatives_keep_all_physical_and_output_slots(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    assert report['physical_rows'] == case['graph']['physical_rows']
    assert report['row_references'] == case['graph']['row_references']
    assert len(report['physical_review_bindings']) == 2
    assert all(len(row['review_references']) == 2 for row in report['physical_review_bindings'])
    assert len(report['output_occurrence_bindings']) == len(case['graph']['output_occurrences']) >= 4
    for output, original in zip(report['output_occurrence_bindings'], case['graph']['output_occurrences'], strict=True):
        assert all(output[key] == original[key] for key in
            ('output_occurrence_ordinal', 'physical_identity_sha256', 'route', 'ordinal'))
        assert output['review_references'] == report['physical_review_bindings'][output['physical_row_ordinal']]['review_references']
    assert _validate_coordinate_correspondence(report, case) == report
    _coordinate_correspondence_no_authority(report)


@pytest.mark.parametrize('coordinate_join', [{'covered_rows': 1}], indirect=True)
def test_coordinate_correspondence_uncovered_physical_slot_is_explicit_not_dropped(coordinate_correspondence_case):
    report = _prepare_coordinate_correspondence(coordinate_correspondence_case)
    assert len(report['physical_review_bindings']) == 2
    assert report['physical_review_bindings'][1]['review_nominations'] == []
    assert report['physical_review_bindings'][1]['review_references'] == []
    assert all(row['review_references'] == [] for row in report['output_occurrence_bindings']
               if row['physical_row_ordinal'] == 1)
    _coordinate_correspondence_no_authority(report)


@pytest.mark.parametrize('coordinate_join', [{'unsupported': True}], indirect=True)
def test_coordinate_correspondence_unsupported_graph_outputs_remain_in_review_ledger(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    assert all(output['graph'] is None for output in case['graph']['output_occurrences'])
    report = _prepare_coordinate_correspondence(case)
    assert len(report['output_occurrence_bindings']) == len(case['graph']['output_occurrences'])
    assert all(row['review_references'] for row in report['output_occurrence_bindings'])
    _coordinate_correspondence_no_authority(report)


def test_coordinate_correspondence_raw_carrier_preserves_noncanonical_upstream_bytes_once(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    assert report['graph_report_raw_utf8'].encode() == case['graph_raw']
    assert sha(case['graph_raw']) != sha(wire(case['graph']))
    assert report['source_request_raw_utf8'].encode() == case['source_raw']
    def carriers(value):
        if type(value) is dict:
            return int('graph_report_raw_utf8' in value) + sum(carriers(v) for v in value.values())
        return sum(carriers(v) for v in value) if type(value) is list else 0
    assert carriers(report) == 1


@pytest.mark.parametrize('pin', ['graph_report_raw_sha256', 'graph_report_sha256',
    'graph_originals_sha256', 'source_request_sha256'])
def test_coordinate_correspondence_resealed_request_cannot_replace_independent_pins(coordinate_correspondence_case, pin):
    case = coordinate_correspondence_case
    with pytest.raises(ValueError):
        _prepare_coordinate_correspondence(case, request_raw=_coordinate_correspondence_request(case, **{pin: '0' * 64}))


@pytest.mark.parametrize('damage', ['v1_schema', 'missing_profile', 'wrong_profile'])
def test_coordinate_correspondence_explicit_profile_is_required(coordinate_correspondence_case, damage):
    case = coordinate_correspondence_case
    request = json.loads(_coordinate_correspondence_request(case))
    if damage == 'v1_schema': request['schema'] = 'legal-source-correspondence-request/v1'
    elif damage == 'missing_profile': request.pop('profile')
    else: request['profile'] = 'complete-declared-physical-source-review-requests/v1'
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(case, request_raw=wire(request))


@pytest.mark.parametrize('damage', ['table_path', 'file_hash', 'row_ordinal', 'paired_bytes', 'boolean_slot', 'boolean_bank',
    'boolean_physical', 'duplicate_nomination', 'omitted_bank_reference', 'missing_slot', 'reordered_slots'])
def test_coordinate_correspondence_exact_physical_original_linkage_refuses_resealed_declarations(coordinate_correspondence_case, damage):
    case = coordinate_correspondence_case
    physical = case['banks'][0]['physical_rows'][0]['physical_identity']
    if damage == 'table_path': physical['path_in_repo'] = 'authored/unrelated.parquet'
    elif damage == 'file_hash': physical['artifact_sha256'] = 'f' * 64
    elif damage == 'row_ordinal': physical['row_ordinal'] += 90
    elif damage == 'paired_bytes':
        bank = case['banks'][0]
        changed = json.loads(bank['paired_row_bytes'][0])
        changed['provenance']['code_identity'] = 'same-source-text-unrelated-producer'
        bank['paired_row_bytes'][0] = wire(changed)
        bank['join_inputs']['expected_population'][0]['row_sha256'] = sha(bank['paired_row_bytes'][0])
        bank['join_bytes'] = wire(_coordinate_legacy_join.build_legacy_source_join(bank['paired_row_bytes'], **bank['join_inputs']))
    elif damage == 'boolean_slot': case['slots'][0]['physical_row_ordinal'] = False
    elif damage == 'boolean_bank': case['slots'][0]['review_nominations'][0]['bank_ordinal'] = False
    elif damage == 'boolean_physical': case['slots'][0]['review_nominations'][0]['bank_physical_row_ordinal'] = False
    elif damage == 'duplicate_nomination': case['slots'][0]['review_nominations'].append(deepcopy(case['slots'][0]['review_nominations'][0]))
    elif damage == 'omitted_bank_reference': case['slots'][0]['review_nominations'].clear()
    elif damage == 'missing_slot': case['slots'].pop()
    else: case['slots'].reverse()
    _coordinate_correspondence_repin_banks(case)
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(case)


@pytest.mark.parametrize('damage', ['physical_drop', 'physical_reorder', 'output_drop', 'review_drop',
    'question_answer', 'mask', 'authority'])
def test_coordinate_correspondence_rehashed_report_requires_complete_original_regeneration(coordinate_correspondence_case, damage):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    if damage == 'physical_drop': report['physical_review_bindings'].pop()
    elif damage == 'physical_reorder': report['physical_review_bindings'].reverse()
    elif damage == 'output_drop': report['output_occurrence_bindings'].pop()
    elif damage == 'review_drop': report['physical_review_bindings'][0]['review_references'].clear()
    elif damage == 'question_answer': report['source_preparation']['banks'][0]['preparation']['requests'][0]['review_questions'][0]['answer'] = 'invented review'
    elif damage == 'mask': report['training_mask'] = True
    else: report['authority']['source_correspondence_verified'] = True
    with pytest.raises(ValueError): _validate_coordinate_correspondence(report, case)


@pytest.mark.parametrize('damage', ['live_bank', 'detached_bank', 'graph_metadata', 'retained_table', 'limits',
    'question_callable', 'question_prompts', 'authority', 'callback'])
def test_coordinate_correspondence_closing_fences_follow_genuine_review_work(coordinate_correspondence_case, monkeypatch, damage):
    case = coordinate_correspondence_case
    genuine = legacy_review.prepare_legacy_source_review_requests
    calls = []
    limits = {'max_report_bytes': 64 * 1024**2}
    def mutate_after_real(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            if damage == 'live_bank': case['banks'][0]['join_inputs']['source_sections'][0]['text'] += ' changed'
            elif damage == 'detached_bank': kwargs['source_sections'][0]['text'] += ' changed'
            elif damage == 'graph_metadata': case['originals']['join_originals']['source_metadata_bytes']['README.md'] += b' changed'
            elif damage == 'retained_table':
                material = case['upstream']['case']['coordinate']
                table = Path(material['request']['repository_root']) / material['written']['paired_spans']['path_in_repo']
                table.write_bytes(table.read_bytes() + b' changed after genuine source preparation')
            elif damage == 'limits': limits['max_report_bytes'] -= 1
            elif damage == 'question_callable': monkeypatch.setattr(legacy_review.questions, '_questions', lambda *a, **k: [])
            elif damage == 'question_prompts': monkeypatch.setitem(legacy_review.wording.PROMPTS, 'definition', 'changed after actual question generation')
            elif damage == 'authority': monkeypatch.setitem(owner.AUTHORITY, 'training_qualified', True)
            else: monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v2', lambda *a, **k: {})
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate_after_real)
    expected_error = owner.SourceCorrespondenceRequestsError if damage == 'authority' else ValueError
    with pytest.raises(expected_error): _prepare_coordinate_correspondence(case, limits=limits)
    assert calls


def test_coordinate_correspondence_primary_error_retains_secondary_closing_failure(coordinate_correspondence_case, monkeypatch):
    case = coordinate_correspondence_case
    genuine = legacy_review.prepare_legacy_source_review_requests
    class Primary(BaseException):
        pass
    primary = Primary('authored primary failure after actual review work')
    calls = []
    def fail_after_real(*args, **kwargs):
        genuine(*args, **kwargs)
        calls.append(True)
        case['banks'][0]['physical_rows'][0]['physical_identity']['row_ordinal'] += 99
        raise primary
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', fail_after_real)
    with pytest.raises(Primary) as caught: _prepare_coordinate_correspondence(case)
    assert caught.value is primary and calls
    assert getattr(primary, '__notes__', [])


def test_coordinate_correspondence_validator_fences_offered_report_after_genuine_delegation(coordinate_correspondence_case, monkeypatch):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    genuine = legacy_review.prepare_legacy_source_review_requests
    calls = []
    def mutate_after_real(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(True)
        report['physical_review_bindings'][0]['review_references'].clear()
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate_after_real)
    with pytest.raises(ValueError): _validate_coordinate_correspondence(report, case)
    assert calls


@pytest.mark.parametrize('limits', [{'max_original_bytes': 1}, {'max_report_bytes': 1}, {'max_physical_rows': 1}])
def test_coordinate_correspondence_lower_caps_refuse_whole_population(coordinate_correspondence_case, limits):
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(coordinate_correspondence_case, limits=limits)


def test_coordinate_correspondence_returned_reports_are_detached(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    report = _prepare_coordinate_correspondence(case)
    checked = _validate_coordinate_correspondence(report, case)
    report['physical_review_bindings'][0]['review_references'].clear()
    report['source_preparation']['banks'][0]['preparation']['requests'][0]['original_row']['candidates'].clear()
    assert checked['physical_review_bindings'][0]['review_references']
    assert len(checked['source_preparation']['banks'][0]['preparation']['requests'][0]['original_row']['candidates']) == 2


@pytest.mark.parametrize('coordinate_join', [{'banks': 2}], indirect=True)
def test_coordinate_correspondence_multibank_nominations_require_natural_order(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    case['slots'][0]['review_nominations'].reverse()
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(case)


@pytest.mark.parametrize('damage', ['graph_schema', 'graph_profile', 'graph_list', 'graph_null', 'graph_scalar'])
def test_coordinate_correspondence_resealed_upstream_domain_cannot_enter_new_profile(coordinate_correspondence_case, monkeypatch, damage):
    case = coordinate_correspondence_case
    request = json.loads(_coordinate_correspondence_request(case))
    if damage == 'graph_schema': case['graph']['schema'] = 'legal-coordinate-source-graph-intake/v1'
    elif damage == 'graph_profile': case['graph']['source_compatibility_profile'] = 'retained-row-coordinate-source-graph-intake/v1'
    else: case['graph'] = {'graph_list': [], 'graph_null': None, 'graph_scalar': 7}[damage]
    case['graph_raw'] = wire(case['graph'])
    request.update(graph_report_raw_sha256=sha(case['graph_raw']), graph_report_sha256=sha(wire(case['graph'])))
    monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v2',
        lambda *args, **kwargs: pytest.fail('malformed upstream domain reached graph work'))
    with pytest.raises(owner.SourceCorrespondenceRequestsError):
        _prepare_coordinate_correspondence(case, request_raw=wire(request))


def test_coordinate_correspondence_wrong_outer_request_pin_refuses_before_graph_work(coordinate_correspondence_case, monkeypatch):
    case = coordinate_correspondence_case
    monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v2',
        lambda *args, **kwargs: pytest.fail('wrong independent request pin reached graph work'))
    with pytest.raises(ValueError):
        owner.prepare_source_correspondence_requests_v2(_coordinate_correspondence_request(case),
            case['graph_raw'], case['source_raw'], expected_request_sha256='0' * 64,
            graph_originals=case['originals'], original_banks=case['banks'])


def test_coordinate_correspondence_nonempty_existing_v1_bank_contract_is_preserved(coordinate_correspondence_case):
    case = coordinate_correspondence_case
    case['banks'] = []
    case['source_raw'] = wire(request_for([]))
    for slot in case['slots']: slot['review_nominations'] = []
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(case)


def test_coordinate_correspondence_closing_source_observation_catches_late_hash_drift(coordinate_correspondence_case, monkeypatch):
    case = coordinate_correspondence_case
    genuine_review = legacy_review.prepare_legacy_source_review_requests
    genuine_read = Path.read_bytes
    changed = []
    own_path = Path(owner.__file__).resolve()
    def read_then_observe(path):
        raw = genuine_read(path)
        # Simulate a later source observation after an actual source-file read;
        # never change any runtime source file or its original native source pin.
        return raw + b'\n' if changed and path.resolve() == own_path else raw
    def finish_real_review(*args, **kwargs):
        result = genuine_review(*args, **kwargs)
        changed.append(True)
        return result
    monkeypatch.setattr(Path, 'read_bytes', read_then_observe)
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', finish_real_review)
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(case)
    assert changed


def test_coordinate_correspondence_final_graph_replay_catches_table_change_after_real_closing_v1_validation(coordinate_correspondence_case, monkeypatch):
    case = coordinate_correspondence_case
    genuine = owner.validate_source_correspondence_requests_v1
    calls = []
    def change_after_genuine_closing_source(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            material = case['upstream']['case']['coordinate']
            table = Path(material['request']['repository_root']) / material['written']['paired_spans']['path_in_repo']
            table.write_bytes(table.read_bytes() + b' late change after real closing v1 validation')
        return result
    monkeypatch.setattr(owner, 'validate_source_correspondence_requests_v1', change_after_genuine_closing_source)
    with pytest.raises(ValueError): _prepare_coordinate_correspondence(case)
    assert calls


# Reuse the existing receipt-producing coordinate_join override above. The
# existing wire join/eligibility/graph fixtures consume it without another
# producer or an independently copied HTML/source-binding recipe.
from tests.unit.logic.autoformal.test_legal_span_cache_intake import (
    wire_coordinate_join,
    wire_original_replay_v4,
    wire_graph_v3_case,
    _prepare_wire_graph_v3,
    _wire_graph_v3_request,
    _coordinate_graph_retained_table,
)


_WIRE_CORRESPONDENCE_SCHEMA = 'legal-source-correspondence-requests/v3'
_WIRE_CORRESPONDENCE_PROFILE = 'original-input-wire-coordinate-graph-v3-source-review-request-custody/v1'
_WIRE_CORRESPONDENCE_METADATA = 'hf-default-parquet-envelope/v1'


@pytest.fixture
def wire_correspondence_case(wire_graph_v3_case):
    upstream = wire_graph_v3_case
    graph = _prepare_wire_graph_v3(upstream)
    graph_request = _wire_graph_v3_request(upstream)
    originals = {'request_raw': graph_request, 'eligibility_report_raw': upstream['eligibility_raw'],
        'eligibility_request_raw': upstream['eligibility_request_raw'], 'join_manifest_raw': upstream['join_raw'],
        'expected_request_sha256': sha(graph_request), 'join_originals': upstream['originals'],
        'source_bindings': upstream['bindings']}
    options = upstream['case']['_correspondence_options']
    payload = upstream['joined']['paired_bundles'][0]['payload_intake']['rows']
    coverage = options.get('covered_rows', len(payload))
    rows = [row['derived_row_json'].encode('utf-8') for row in payload[:coverage]]
    join_inputs = deepcopy(upstream['case']['_correspondence_originals'])
    join_inputs['expected_population'] = [{
        'row_sha256': sha(raw), 'source_span_id': json.loads(raw)['source']['span_id'],
        'text_sha256': json.loads(raw)['source']['text_sha256'],
        'source_revision': json.loads(raw)['source']['revision'],
    } for raw in rows]
    ledger = _coordinate_legacy_join.build_legacy_source_join(rows, **join_inputs)
    banks = []
    for index in range(options.get('banks', 1)):
        physical = []
        for ordinal, row in enumerate(graph['physical_rows'][:coverage]):
            identity = deepcopy(row['physical_identity'])
            identity['artifact_sha256'] = identity.pop('file_sha256')
            physical.append({'physical_row_ordinal': ordinal, 'request_ordinal': ordinal,
                'physical_identity': identity})
        banks.append({'bank_id': 'authored-coordinate-source-bank:' + str(index),
            'join_bytes': wire(ledger), 'paired_row_bytes': list(rows),
            'join_inputs': deepcopy(join_inputs), 'physical_rows': physical})
    slots = [{'physical_row_ordinal': ordinal,
        'physical_identity_sha256': row['physical_identity_sha256'],
        'review_nominations': [{'bank_ordinal': index, 'bank_physical_row_ordinal': ordinal}
            for index in range(len(banks))] if ordinal < coverage else []}
        for ordinal, row in enumerate(graph['physical_rows'])]
    return {'upstream': upstream, 'graph': graph,
        'graph_raw': (json.dumps(graph, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
        'originals': originals, 'banks': banks, 'source_raw': wire(request_for(banks)), 'slots': slots}


def _wire_correspondence_request(case, **changes):
    return wire({'schema': 'legal-source-correspondence-request/v3',
        'profile': _WIRE_CORRESPONDENCE_PROFILE,
        'graph_report_raw_sha256': sha(case['graph_raw']),
        'graph_report_sha256': _coordinate_graph.coordinate_source_graph_intake_sha256(case['graph']),
        'graph_originals_sha256': _coordinate_corpus.coordinate_graph_corpus_originals_sha256(case['originals']),
        'source_request_sha256': sha(case['source_raw']),
        'physical_review_nominations': case['slots'], **changes})


def _prepare_wire_correspondence(case, *, request_raw=None, limits=None, **changes):
    raw = _wire_correspondence_request(case) if request_raw is None else request_raw
    return owner.prepare_source_correspondence_requests_v3(raw, case['graph_raw'], case['source_raw'],
        **{'expected_request_sha256': sha(raw), 'graph_originals': case['originals'],
           'original_banks': case['banks'], 'limits': limits, **changes})


def _validate_wire_correspondence(case, report, *, limits=None, **changes):
    raw = _wire_correspondence_request(case)
    value = json.loads(report) if type(report) is bytes else report
    return owner.validate_source_correspondence_requests_v3(report, raw, case['graph_raw'], case['source_raw'],
        **{'expected_report_sha256': sha(wire(value)), 'expected_request_sha256': sha(raw),
           'graph_originals': case['originals'], 'original_banks': case['banks'], 'limits': limits, **changes})


def _wire_correspondence_metadata_drift(case):
    case['originals']['join_originals']['source_metadata_bytes']['README.md'] += b'changed wire correspondence metadata'


def _wire_correspondence_bank_drift(case):
    case['banks'][0]['join_inputs']['source_sections'][0]['text'] += 'changed wire correspondence bank'


def _assert_wire_correspondence_unreviewed(report, case):
    _coordinate_correspondence_no_authority(report)
    assert report['schema'] == _WIRE_CORRESPONDENCE_SCHEMA
    assert report['profile'] == _WIRE_CORRESPONDENCE_PROFILE
    assert report['metadata_profile'] == _WIRE_CORRESPONDENCE_METADATA
    assert report['source_metadata_intake_sha256'] == case['upstream']['joined']['source_metadata_intake_sha256']
    assert report['atomic_snapshot_verified'] is False
    assert report['counts']['selected_occurrences'] == report['counts']['source_decisions_applied'] == 0

    def check(value):
        if type(value) is dict:
            for key, item in value.items():
                if key.endswith('_mask'):
                    assert type(item) is int and item == 0
                elif key == 'field_masks':
                    assert type(item) is dict and all(type(mask) is int and mask == 0 for mask in item.values())
                elif key == 'authority':
                    assert type(item) is dict and all(type(flag) is bool and flag is False for flag in item.values())
                check(item)
        elif type(value) is list:
            for item in value:
                check(item)
    check(report)


@pytest.mark.parametrize('offered', ['object', 'serialized_roundtrip'])
def test_wire_correspondence_v3_genuine_graph_and_source_owners_roundtrip(wire_correspondence_case, monkeypatch, offered):
    case = wire_correspondence_case
    genuine_graph = _coordinate_graph.validate_coordinate_source_graph_intake_v3
    genuine_prepare = owner.prepare_source_correspondence_requests_v1
    genuine_validate = owner.validate_source_correspondence_requests_v1
    calls = {'graph': [], 'source_prepare': [], 'source_validate': []}

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        calls['graph'].append(result)
        return result

    def prepare_source(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        calls['source_prepare'].append(result)
        return result

    def validate_source(*args, **kwargs):
        result = genuine_validate(*args, **kwargs)
        calls['source_validate'].append(result)
        return result

    monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v3', graph)
    monkeypatch.setattr(owner, 'prepare_source_correspondence_requests_v1', prepare_source)
    monkeypatch.setattr(owner, 'validate_source_correspondence_requests_v1', validate_source)
    original = deepcopy(case['originals']), deepcopy(case['banks']), deepcopy(case['slots'])
    report = _prepare_wire_correspondence(case)
    assert len(calls['graph']) == 2 and len(calls['source_validate']) == 1
    assert len(calls['source_prepare']) == 2
    assert report['source_preparation'] == calls['source_prepare'][0]
    assert report['physical_rows'] == case['graph']['physical_rows']
    assert report['row_references'] == case['graph']['row_references']
    assert len(report['physical_review_bindings']) == 2 and len(report['output_occurrence_bindings']) == 4
    assert report['source_preparation']['coverage']['candidate_occurrence_references'] == 4
    assert assert_geometry(report['source_preparation']) == 4
    assert all(row['source_disposition'] == 'ambiguous_exact_candidates'
        for row in report['source_preparation']['physical_rows'])
    for output, upstream in zip(report['output_occurrence_bindings'], case['graph']['output_occurrences'], strict=True):
        assert {key: output[key] for key in ('output_occurrence_ordinal', 'physical_identity_sha256', 'route', 'ordinal')} == {
            key: upstream[key] for key in ('output_occurrence_ordinal', 'physical_identity_sha256', 'route', 'ordinal')}
    assert (case['originals'], case['banks'], case['slots']) == original
    assert owner.source_correspondence_requests_v3_sha256(report) == sha(wire(report))
    _assert_wire_correspondence_unreviewed(report, case)
    value = json.loads(wire(report)) if offered == 'serialized_roundtrip' else report
    assert sha(wire(value)) == sha(wire(report))
    assert _validate_wire_correspondence(case, value) == report
    assert len(calls['graph']) == 4 and len(calls['source_validate']) == 2


@pytest.mark.parametrize('coordinate_join', [{'banks': 2}], indirect=True)
def test_wire_correspondence_v3_equal_text_multibank_keeps_every_physical_and_output_alternative(wire_correspondence_case):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    assert len(report['physical_rows']) == len(report['physical_review_bindings']) == 2
    assert report['physical_rows'][0]['source_text'] == report['physical_rows'][1]['source_text']
    assert len({row['physical_identity_sha256'] for row in report['physical_rows']}) == 2
    assert [row['output_occurrence_ordinal'] for row in report['output_occurrence_bindings']] == [0, 1, 2, 3]
    assert [row['route'] for row in report['output_occurrence_bindings']] == [
        'compiler.formal_outputs', 'compiler.canonical_formal_outputs'] * 2
    assert report['source_preparation']['coverage']['banks'] == 2
    assert report['source_preparation']['coverage']['logical_requests'] == 4
    for physical in report['physical_review_bindings']:
        assert [ref['bank_ordinal'] for ref in physical['review_references']] == [0, 1]
    for output in report['output_occurrence_bindings']:
        assert output['review_references'] == report['physical_review_bindings'][output['physical_row_ordinal']]['review_references']
    assert _validate_wire_correspondence(case, report) == report
    _assert_wire_correspondence_unreviewed(report, case)


@pytest.mark.parametrize('coordinate_join', [{'receipt': False}], indirect=True)
def test_wire_correspondence_v3_real_missing_receipt_remains_unavailable(wire_correspondence_case):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    assert report['source_preparation']['coverage']['candidate_occurrence_references'] == 0
    assert all(row['source_disposition'] == 'producer_source_unavailable'
        for row in report['source_preparation']['physical_rows'])
    assert _validate_wire_correspondence(case, report) == report
    _assert_wire_correspondence_unreviewed(report, case)


@pytest.mark.parametrize('coordinate_join', [{'covered_rows': 1}], indirect=True)
def test_wire_correspondence_v3_uncovered_physical_slot_remains_explicit(wire_correspondence_case):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    assert len(report['physical_review_bindings']) == 2
    assert report['physical_review_bindings'][1]['review_nominations'] == []
    assert report['physical_review_bindings'][1]['review_references'] == []
    assert report['physical_review_bindings'][1]['disposition'] == 'review_inputs_unavailable'
    assert all(row['review_references'] == [] for row in report['output_occurrence_bindings'] if row['physical_row_ordinal'] == 1)
    _assert_wire_correspondence_unreviewed(report, case)


@pytest.mark.parametrize('coordinate_join', [{'unsupported': True}], indirect=True)
def test_wire_correspondence_v3_unsupported_outputs_keep_full_review_population(wire_correspondence_case):
    case = wire_correspondence_case
    assert case['graph']['output_occurrences'] and all(row['graph'] is None for row in case['graph']['output_occurrences'])
    report = _prepare_wire_correspondence(case)
    assert len(report['output_occurrence_bindings']) == len(case['graph']['output_occurrences']) == 4
    assert all(row['review_references'] for row in report['output_occurrence_bindings'])
    assert _validate_wire_correspondence(case, report) == report
    _assert_wire_correspondence_unreviewed(report, case)


def test_wire_correspondence_v3_raw_graph_and_source_carriers_remain_exact_once(wire_correspondence_case):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    assert report['graph_report_raw_utf8'].encode('utf-8') == case['graph_raw']
    assert sha(case['graph_raw']) != sha(wire(case['graph']))
    assert report['source_request_raw_utf8'].encode('utf-8') == case['source_raw']
    eligibility = json.loads(json.loads(report['graph_report_raw_utf8'])['eligibility_report_raw_utf8'])
    assert eligibility['join_manifest_raw_utf8'].encode('utf-8') == case['upstream']['join_raw']

    def count(value, key):
        if type(value) is dict:
            return int(key in value) + sum(count(child, key) for child in value.values())
        return sum(count(child, key) for child in value) if type(value) is list else 0
    assert count(report, 'graph_report_raw_utf8') == count(report, 'source_preparation') == 1
    _assert_wire_correspondence_unreviewed(report, case)


@pytest.mark.parametrize('route', ['old_graph_into_wire', 'wire_graph_into_old'])
def test_wire_correspondence_v3_refuses_both_genuine_foreign_graph_routes(request, coordinate_join, monkeypatch, route):
    case = request.getfixturevalue('coordinate_correspondence_case' if route == 'old_graph_into_wire' else 'wire_correspondence_case')
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
        lambda *args, **kwargs: pytest.fail('foreign graph profile reached source-review preparation'))
    with pytest.raises(ValueError):
        (_prepare_wire_correspondence if route == 'old_graph_into_wire' else _prepare_coordinate_correspondence)(case)


@pytest.mark.parametrize('axis', ['metadata_profile', 'source_metadata_intake_sha256'])
def test_wire_correspondence_v3_resealed_metadata_axes_require_genuine_wire_ancestry(wire_correspondence_case, monkeypatch, axis):
    case = wire_correspondence_case
    case['graph'][axis] = 'foreign-wire-metadata-profile' if axis == 'metadata_profile' else '0' * 64
    case['graph_raw'] = wire(case['graph'])
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests',
        lambda *args, **kwargs: pytest.fail('resealed wire metadata reached source-review preparation'))
    with pytest.raises(ValueError):
        _prepare_wire_correspondence(case)


@pytest.mark.parametrize('pin', ['outer_request', 'graph_report_raw_sha256', 'graph_report_sha256',
    'graph_originals_sha256', 'source_request_sha256'])
def test_wire_correspondence_v3_every_independent_commitment_is_required(wire_correspondence_case, pin):
    case = wire_correspondence_case
    with pytest.raises(ValueError):
        if pin == 'outer_request':
            _prepare_wire_correspondence(case, expected_request_sha256='0' * 64)
        else:
            _prepare_wire_correspondence(case, request_raw=_wire_correspondence_request(case, **{pin: '0' * 64}))


@pytest.mark.parametrize('damage', ['drop_slot', 'reorder_slots', 'duplicate_nomination', 'boolean_ordinal', 'whole_row_same_text'])
def test_wire_correspondence_v3_recommitted_nominations_require_exact_complete_original_rows(wire_correspondence_case, damage):
    case = wire_correspondence_case
    if damage == 'drop_slot':
        case['slots'].pop()
    elif damage == 'reorder_slots':
        case['slots'].reverse()
    elif damage == 'duplicate_nomination':
        case['slots'][0]['review_nominations'].append(deepcopy(case['slots'][0]['review_nominations'][0]))
    elif damage == 'boolean_ordinal':
        case['slots'][0]['review_nominations'][0]['bank_ordinal'] = False
    else:
        bank = case['banks'][0]
        row = json.loads(bank['paired_row_bytes'][0])
        row['provenance']['code_identity'] = 'equal-text-independent-producer-substitution'
        bank['paired_row_bytes'][0] = wire(row)
        bank['join_inputs']['expected_population'][0]['row_sha256'] = sha(bank['paired_row_bytes'][0])
        bank['join_bytes'] = wire(_coordinate_legacy_join.build_legacy_source_join(bank['paired_row_bytes'], **bank['join_inputs']))
    _coordinate_correspondence_repin_banks(case)
    with pytest.raises(ValueError):
        _prepare_wire_correspondence(case)


@pytest.mark.parametrize('damage', ['drop_output', 'output_pointer', 'answered_question', 'mask', 'authority'])
def test_wire_correspondence_v3_rehashed_reports_require_complete_unsigned_regeneration(wire_correspondence_case, damage):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    if damage == 'drop_output':
        report['output_occurrence_bindings'].pop()
    elif damage == 'output_pointer':
        report['output_occurrence_bindings'][0]['upstream_output_reference']['json_pointer'] = '/output_occurrences/1'
    elif damage == 'answered_question':
        report['source_preparation']['banks'][0]['preparation']['requests'][0]['review_questions'][0]['answer'] = 'invented signed meaning'
    elif damage == 'mask':
        report['physical_review_bindings'][0]['source_binding_mask'] = True
    else:
        report['authority']['source_correspondence_verified'] = True
    with pytest.raises(ValueError):
        _validate_wire_correspondence(case, report)


@pytest.mark.parametrize('damage', ['original_bank', 'detached_bank', 'graph_metadata', 'retained_table', 'callback'])
def test_wire_correspondence_v3_late_changes_after_genuine_review_are_refused(wire_correspondence_case, monkeypatch, damage):
    case = wire_correspondence_case
    genuine = legacy_review.prepare_legacy_source_review_requests
    calls = []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(result)
        if len(calls) == 1:
            if damage == 'original_bank':
                _wire_correspondence_bank_drift(case)
            elif damage == 'detached_bank':
                kwargs['source_sections'][0]['text'] += 'changed after real question preparation'
            elif damage == 'graph_metadata':
                _wire_correspondence_metadata_drift(case)
            elif damage == 'retained_table':
                path = _coordinate_graph_retained_table(case['upstream'])
                path.write_bytes(path.read_bytes() + b'changed after real wire source preparation')
            else:
                monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v3',
                    lambda *args, **kwargs: pytest.fail('substituted graph callback was invoked'))
        return result

    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate)
    with pytest.raises(ValueError):
        _prepare_wire_correspondence(case)
    assert calls


def test_wire_correspondence_v3_primary_baseexception_retains_actual_closing_graph_failure(wire_correspondence_case, monkeypatch):
    case = wire_correspondence_case
    genuine_review = legacy_review.prepare_legacy_source_review_requests
    genuine_graph = _coordinate_graph.validate_coordinate_source_graph_intake_v3
    attempts, failures, calls = [], [], []

    class Primary(BaseException):
        pass
    primary = Primary('authored wire source-review primary failure')

    def graph(*args, **kwargs):
        attempts.append(True)
        try:
            return genuine_graph(*args, **kwargs)
        except BaseException as error:
            failures.append(error)
            raise

    def fail(*args, **kwargs):
        result = genuine_review(*args, **kwargs)
        calls.append(result)
        path = _coordinate_graph_retained_table(case['upstream'])
        path.write_bytes(path.read_bytes() + b'changed after actual wire review before primary failure')
        raise primary

    monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v3', graph)
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', fail)
    with pytest.raises(Primary) as caught:
        _prepare_wire_correspondence(case)
    assert caught.value is primary and calls and len(attempts) == 2 and len(failures) == 1
    detail = type(failures[0]).__name__ + ': ' + str(failures[0])[:512]
    assert any(detail in note for note in getattr(primary, '__notes__', ()))


@pytest.mark.parametrize('returned', ['opening_graph', 'source_preparation', 'source_validation', 'closing_graph'])
def test_wire_correspondence_v3_actual_genuine_returns_remain_guarded_after_closing(wire_correspondence_case, monkeypatch, returned):
    case = wire_correspondence_case
    genuine_graph = _coordinate_graph.validate_coordinate_source_graph_intake_v3
    genuine_prepare = owner.prepare_source_correspondence_requests_v1
    genuine_validate = owner.validate_source_correspondence_requests_v1
    genuine_plain = owner._v2_plain
    graphs, sources, checks, changed = [], [], [], []

    def prepare_source(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        sources.append(result)
        return result

    def validate_source(*args, **kwargs):
        result = genuine_validate(*args, **kwargs)
        checks.append(result)
        return result

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        if len(graphs) == 2 and returned != 'closing_graph':
            assert sources and checks
            if returned == 'opening_graph':
                graphs[0]['output_occurrences'][0]['training_mask'] = 1
            else:
                selected = sources[0] if returned == 'source_preparation' else checks[0]
                selected['physical_rows'][0]['training_mask'] = 1
            changed.append(returned)
        return result

    def plain(*args, **kwargs):
        result = genuine_plain(*args, **kwargs)
        if (returned == 'closing_graph' and len(graphs) == 2 and not changed
                and result[0].get('schema') == _WIRE_CORRESPONDENCE_SCHEMA):
            # The genuine closing validator has returned and its result has
            # already passed adoption and immediate replay equality checks.
            graphs[1]['output_occurrences'][0]['training_mask'] = 1
            changed.append(returned)
        return result

    monkeypatch.setattr(owner, 'prepare_source_correspondence_requests_v1', prepare_source)
    monkeypatch.setattr(owner, 'validate_source_correspondence_requests_v1', validate_source)
    monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v3', graph)
    monkeypatch.setattr(owner, '_v2_plain', plain)
    with pytest.raises(ValueError):
        _prepare_wire_correspondence(case)
    assert changed == [returned] and len(graphs) == 2


@pytest.mark.parametrize('inputs', ['banks', 'graph_originals'])
def test_wire_correspondence_v3_outer_validation_guards_callers_after_real_inner_prepare(wire_correspondence_case, monkeypatch, inputs):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    genuine = owner._prepare_source_correspondence_requests
    changed = []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        assert kwargs['profile_version'] == 3
        (_wire_correspondence_bank_drift if inputs == 'banks' else _wire_correspondence_metadata_drift)(case)
        changed.append(inputs)
        return result

    monkeypatch.setattr(owner, '_prepare_source_correspondence_requests', mutate)
    with pytest.raises(ValueError):
        _validate_wire_correspondence(case, report)
    assert changed == [inputs]


def test_wire_correspondence_v3_outer_parsed_graph_cannot_nominate_foreign_files(wire_correspondence_case, monkeypatch):
    case = wire_correspondence_case
    report = _prepare_wire_correspondence(case)
    genuine_setup = owner._coordinate_correspondence_setup
    genuine_prepare = owner._prepare_source_correspondence_requests
    genuine_plan = _coordinate_corpus._corpus_wire_physical_plan
    states, changed, plans = [], [], []

    def setup(*args, **kwargs):
        result = genuine_setup(*args, **kwargs)
        states.append(result)
        return result

    def mutate(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        assert kwargs['profile_version'] == 3 and len(states) >= 2
        graph = states[0]['offered_graph']
        eligibility = json.loads(graph['eligibility_report_raw_utf8'])
        joined = json.loads(eligibility['join_manifest_raw_utf8'])
        joined['span_inventory']['manifests'][0]['manifest']['tables']['paired_spans']['path_in_repo'] = 'unselected/outer-wire-source-review.parquet'
        eligibility['join_manifest_raw_utf8'] = wire(joined).decode('utf-8')
        graph['eligibility_report_raw_utf8'] = wire(eligibility).decode('utf-8')
        changed.append(True)
        return result

    def plan(*args, **kwargs):
        assert not changed, 'mutated outer source-review graph reached physical nomination'
        plans.append(True)
        return genuine_plan(*args, **kwargs)

    monkeypatch.setattr(owner, '_coordinate_correspondence_setup', setup)
    monkeypatch.setattr(owner, '_prepare_source_correspondence_requests', mutate)
    monkeypatch.setattr(_coordinate_corpus, '_corpus_wire_physical_plan', plan)
    with pytest.raises(ValueError):
        _validate_wire_correspondence(case, report)
    assert changed == [True] and plans


@pytest.mark.parametrize('damage', ['original_bank', 'detached_report'])
def test_wire_correspondence_v3_postclosing_serialization_guards_originals_and_detached_result(wire_correspondence_case, monkeypatch, damage):
    case = wire_correspondence_case
    genuine_graph = _coordinate_graph.validate_coordinate_source_graph_intake_v3
    genuine_plain, genuine_wire = owner._v2_plain, owner._wire
    graphs, detached, changed = [], [], []

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        return result

    def plain(*args, **kwargs):
        result = genuine_plain(*args, **kwargs)
        if result[0].get('schema') == _WIRE_CORRESPONDENCE_SCHEMA:
            detached.append(result[0])
        return result

    def wire_value(value):
        raw = genuine_wire(value)
        eligible = type(value) is dict and value.get('schema') == _WIRE_CORRESPONDENCE_SCHEMA
        if damage == 'detached_report':
            eligible = eligible and any(value is item for item in detached)
        if len(graphs) == 2 and eligible and not changed:
            if damage == 'original_bank':
                _wire_correspondence_bank_drift(case)
            else:
                value['counts']['mapped_physical_rows'] += 1
            changed.append(damage)
        return raw

    monkeypatch.setattr(_coordinate_graph, 'validate_coordinate_source_graph_intake_v3', graph)
    monkeypatch.setattr(owner, '_v2_plain', plain)
    monkeypatch.setattr(owner, '_wire', wire_value)
    with pytest.raises(ValueError):
        _prepare_wire_correspondence(case)
    assert changed == [damage] and len(graphs) == 2


@pytest.mark.parametrize('limits', [{'max_original_bytes': 1}, {'max_report_bytes': 1}, {'max_physical_rows': 1}])
def test_wire_correspondence_v3_preserves_unchanged_lower_only_whole_population_caps(wire_correspondence_case, limits):
    with pytest.raises(ValueError):
        _prepare_wire_correspondence(wire_correspondence_case, limits=limits)
