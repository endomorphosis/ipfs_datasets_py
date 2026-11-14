"""Unsigned source adoption intent authoring never authenticates or applies it.

Fictional choices exercise the authoring contract only. The enrolled retained
13/16/150 case creates no choices and preserves every pending physical subject.
No parent Parquet, metadata shard, cache table, signing, model or prover runs.
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
from ipfs_datasets_py.logic.autoformal import legal_stored_source_adoption_requests_v1 as owner


ROOT = Path('/home/barberb/lift_coding')
REAL_INPUTS = ROOT / 'artifacts/legal-ir-stored-source-adoption-20261019-01/inputs.json'
REAL_INPUTS_BYTES = 10482
REAL_INPUTS_SHA256 = '79c059a3eef8f3522161ef5462f2286a04cc16c18f5515db5b027ab76a31629b'
EVIDENCE_NAME = 'stored-source-adoption-requests-engineering-evidence.json'
ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353, 3354, 3355, 3357, 3358]
DOMAIN = {'profile': 'reviewed-stored-source-adoption/v1',
    'subject_schema': 'legal-stored-source-adoption-subject/v1',
    'claim_schema': 'legal-stored-source-adoption-signed-claim/v1',
    'action': 'apply_reviewed_stored_source_adoption/v1',
    'audience': 'legal-autoformalization-stored-source-adoption/v1',
    'effect': 'adopt_exact_stored_occurrence_for_explicit_scope_role_and_legal_as_of_only/v1'}
TEMPLATE = {'choice': None, 'source_use': None, 'declared_at_utc': None, 'rationale': None, 'evidence_refs': []}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_ref(raw):
    return {'bytes': len(raw), 'sha256': sha(raw)}


def fixture_helper():
    """Only tiny independently authored constructors, never prior test calls."""
    path = Path(__file__).with_name('test_legal_source_correspondence_requests_v1.py')
    spec = importlib.util.spec_from_file_location('fictional_correspondence_for_adoption_authoring', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def material(*, fanout=False, unavailable=None):
    helper = fixture_helper()
    data = helper.material(fanout=fanout, unavailable=unavailable)
    return {'banks': data['banks'], 'packet': helper.prepare(data), 'request_raw': wire(data['request'])}


def arguments(data, *, limits=None):
    return {'expected_packet_sha256': sha(wire(data['packet'])),
        'expected_request_sha256': sha(data['request_raw']), 'original_banks': data['banks'], 'limits': limits}


def prepare(data, *, limits=None):
    return owner.prepare_stored_source_adoption_requests_v1(data['packet'], data['request_raw'],
                                                           **arguments(data, limits=limits))


def validate(preparation, data, *, limits=None):
    return owner.validate_stored_source_adoption_requests_v1(preparation, data['packet'], data['request_raw'],
        expected_report_sha256=sha(wire(preparation)), **arguments(data, limits=limits))


def source_use(data, *, purpose='retained_source_analysis'):
    version = data['packet']['banks'][0]['preparation']['source_sections'][0]['source_version']
    return {'purpose': purpose, 'declared_region_role': 'operative_body', 'scope_id': 'fixture:analysis-scope',
        'jurisdiction_id': 'fixture:jurisdiction', 'instrument_id': 'fixture:instrument',
        'legal_as_of_civil_date': '2026-10-19', 'edition': None,
        'view_profile': version['extracted_view']['extraction_profile']}


def declaration_arguments(preparation, data, *, row=0, use=None, limits=None):
    return {'physical_reference': deepcopy(preparation['rows'][row]['physical_reference']),
        'source_use': source_use(data) if use is None else use,
        'declared_at_utc': '2026-10-19T00:00:00Z',
        'rationale': 'Fictional present-day source-use declaration; no actual review or legal effect.',
        'evidence_refs': [{'artifact_id': 'fixture:unverified-support', 'sha256': sha(b'fictional support')}],
        'packet': data['packet'], 'request_raw': data['request_raw'],
        'expected_preparation_sha256': sha(wire(preparation)), **arguments(data, limits=limits)}


def record(preparation, data, *, candidate=0, row=0, use=None, **overrides):
    choice = deepcopy(preparation['rows'][row]['candidate_choices'][candidate])
    kwargs = declaration_arguments(preparation, data, row=row, use=use)
    kwargs.update(overrides)
    return owner.record_stored_source_adoption_declaration_v1(preparation, choice, **kwargs)


def validate_declaration(declaration, preparation, choice, data, **overrides):
    kwargs = declaration_arguments(preparation, data)
    kwargs.update(overrides)
    return owner.validate_stored_source_adoption_declaration_v1(declaration, preparation, choice,
        expected_declaration_sha256=sha(wire(declaration)), **kwargs)


def flags(value):
    assert value['authority'] and all(flag is False for flag in value['authority'].values())
    assert value['inference_view'] is None
    assert all(type(value[name]) is int and value[name] == 0 for name in ('training_mask', 'evaluation_gold_mask'))


def check_pending(preparation, packet):
    assert preparation['schema'] == 'legal-stored-source-adoption-requests/v1'
    assert preparation['profile'] == 'unsigned-stored-source-adoption-authoring/v1'
    assert preparation['signing_domain'] == DOMAIN
    assert preparation['source_packet'] == packet
    assert preparation['source_packet_sha256'] == sha(wire(packet))
    assert preparation['source_request_sha256'] == packet['request_sha256']
    assert preparation['status'] == 'pending_actual_source_adoption_inputs'
    assert preparation['coverage']['submitted_declarations'] == preparation['coverage']['applied_source_decisions'] == 0
    assert preparation['coverage']['full_declared_population_retained'] is True
    assert len(preparation['rows']) == len(packet['physical_rows'])
    flags(preparation)
    for row, physical in zip(preparation['rows'], packet['physical_rows'], strict=True):
        expected_reference = {name: physical[name] for name in ('bank_id', 'physical_row_ordinal',
            'physical_identity', 'paired_row_sha256')}
        assert row['physical_reference'] == expected_reference
        assert row['request_ref'] == physical['request_ref']
        assert row['source_subject_ref'] == physical['subject_ref']
        assert row['source_preparation_manifest_sha256'] == physical['preparation_manifest_sha256']
        original = packet['banks'][physical['bank_ordinal']]['preparation']['requests'][physical['request_ordinal']]['original_row']
        choices = []
        for candidate in original['candidates']:
            section = packet['banks'][physical['bank_ordinal']]['preparation']['source_sections'][candidate['source_section_index']]
            choices.append({'source_section_index': candidate['source_section_index'], 'source_section_sha256': sha(wire(section)),
                'source_version_ref': {'record_cid': section['source_version']['record_cid'], 'sha256': sha(wire(section['source_version']))},
                'source_occurrence_ref': {'record_cid': candidate['source_occurrence']['record_cid'], 'sha256': sha(wire(candidate['source_occurrence']))},
                'context_ref': {'record_cid': candidate['context_declaration']['record_cid'], 'sha256': sha(wire(candidate['context_declaration']))}})
        assert row['candidate_choices'] == choices
        assert row['subject']['schema'] == DOMAIN['subject_schema']
        assert row['subject']['profile'] == DOMAIN['profile']
        assert row['subject']['physical_reference'] == expected_reference
        assert row['subject']['candidate_choices_sha256'] == sha(wire(choices))
        assert row['subject']['active_slot_ids'] == packet['banks'][physical['bank_ordinal']]['preparation']['requests'][physical['request_ordinal']]['context_slot_ids']
        assert row['subject']['deferred_slot_ids'] == packet['banks'][physical['bank_ordinal']]['preparation']['requests'][physical['request_ordinal']]['deferred_review_slot_ids']
        assert row['declaration_template'] == TEMPLATE and row['pending_obligations']
        assert row['decision_applied'] is row['subject']['decision_applied'] is False
        assert row['status'] == 'pending_actual_source_adoption_inputs'
        flags(row); flags(row['subject'])


def test_complete_pending_subjects_preserve_every_physical_reference_and_choice():
    data = material()
    original = sha(wire(data['packet']))
    preparation = prepare(data)
    check_pending(preparation, data['packet'])
    assert preparation['coverage']['physical_rows'] == preparation['coverage']['logical_requests'] == 4
    assert preparation['coverage']['candidate_occurrence_references'] == 6
    assert validate(preparation, data) == preparation
    assert owner.stored_source_adoption_requests_sha256(preparation) == sha(wire(preparation))
    assert sha(wire(data['packet'])) == original


def test_shared_logical_request_keeps_distinct_physical_adoption_subjects():
    data = material(fanout=True)
    preparation = prepare(data)
    check_pending(preparation, data['packet'])
    assert len(preparation['rows']) == 5
    first, repeated = preparation['rows'][0], preparation['rows'][2]
    assert first['request_ref'] == repeated['request_ref']
    assert first['candidate_choices'] == repeated['candidate_choices']
    assert first['physical_reference'] != repeated['physical_reference']
    assert first['subject']['record_cid'] != repeated['subject']['record_cid']
    assert validate(preparation, data) == preparation


@pytest.mark.parametrize('unavailable', ['receipt', 'section'])
def test_unavailable_sources_stay_in_pending_denominator_without_choices(unavailable):
    data = material(unavailable=unavailable)
    preparation = prepare(data)
    check_pending(preparation, data['packet'])
    assert len(preparation['rows']) == 4
    assert preparation['coverage']['candidate_occurrence_references'] == 0
    assert all(row['candidate_choices'] == [] and row['declaration_template'] == TEMPLATE for row in preparation['rows'])
    assert validate(preparation, data) == preparation


def test_preparation_and_validator_return_detached_copies():
    data = material()
    preparation = prepare(data)
    checked = validate(preparation, data)
    preparation['rows'][0]['candidate_choices'].clear()
    preparation['source_packet']['physical_rows'].clear()
    assert len(checked['rows'][0]['candidate_choices']) == 2 and len(checked['source_packet']['physical_rows']) == 4
    assert len(data['packet']['physical_rows']) == 4


@pytest.mark.parametrize('candidate', [0, 1])
def test_unsigned_declaration_binds_one_explicit_candidate_without_applying_it(candidate):
    data = material()
    preparation = prepare(data)
    before = sha(wire(preparation))
    choice = deepcopy(preparation['rows'][0]['candidate_choices'][candidate])
    declaration = record(preparation, data, candidate=candidate)
    assert declaration['choice'] == choice
    assert declaration['intent'] == 'deliberate_adoption'
    assert declaration['signature'] is None and declaration['decision_applied'] is False
    assert declaration['status'] == 'declared_unsigned_unapplied_source_adoption_intent'
    assert declaration['signing_domain'] == DOMAIN
    assert declaration['considered_candidate_choices_sha256'] == sha(wire(preparation['rows'][0]['candidate_choices']))
    assert declaration['original_context']['availability'] == 'required_unavailable'
    assert declaration['pending_obligations']
    flags(declaration)
    assert validate_declaration(declaration, preparation, choice, data) == declaration
    assert sha(wire(preparation)) == before
    check_pending(preparation, data['packet'])


def test_governing_intent_and_unknown_qualifiers_remain_explicit_unsigned_inputs():
    data = material()
    preparation = prepare(data)
    use = dict.fromkeys(('scope_id', 'jurisdiction_id', 'instrument_id', 'legal_as_of_civil_date', 'edition', 'view_profile'))
    use.update(purpose='governing_normative_source', declared_region_role='unknown')
    declaration = record(preparation, data, use=use)
    assert declaration['source_use'] == use and declaration['intent'] == 'deliberate_adoption'
    assert declaration['signature'] is None and declaration['decision_applied'] is False
    assert declaration['pending_obligations']
    flags(declaration)


def test_offered_edition_never_rewrites_original_source_edition_or_context():
    data = material()
    preparation = prepare(data)
    before = sha(wire(data['packet']))
    use = source_use(data); use['edition'] = 'fixture:separately-offered-edition'
    declaration = record(preparation, data, use=use)
    assert declaration['source_use']['edition'] == use['edition']
    assert declaration['original_context'] == data['packet']['banks'][0]['preparation']['requests'][0]['original_row']['candidates'][0]['context_declaration']
    assert sha(wire(data['packet'])) == before
    flags(declaration)


@pytest.mark.parametrize('damage', ['drop_row', 'reverse_rows', 'drop_choice', 'reverse_choices',
    'physical_subject', 'subject_domain', 'authority', 'training_mask', 'context_template'])
def test_rehashed_preparation_changes_fail_full_original_regeneration(damage):
    data = material(); preparation = prepare(data)
    row = preparation['rows'][0]
    if damage == 'drop_row': preparation['rows'].pop()
    elif damage == 'reverse_rows': preparation['rows'].reverse()
    elif damage == 'drop_choice': row['candidate_choices'].pop()
    elif damage == 'reverse_choices': row['candidate_choices'].reverse()
    elif damage == 'physical_subject': row['subject']['physical_reference'] = deepcopy(preparation['rows'][1]['physical_reference'])
    elif damage == 'subject_domain': preparation['signing_domain']['action'] = 'activate_legacy_candidate_source_answer_snapshot/v1'
    elif damage == 'authority': preparation['authority']['source_adoption_applied'] = True
    elif damage == 'training_mask': row['training_mask'] = True
    else: row['declaration_template']['choice'] = deepcopy(row['candidate_choices'][0])
    with pytest.raises(ValueError): validate(preparation, data)


@pytest.mark.parametrize('damage', ['packet_pin', 'request_pin', 'packet_row_drop', 'packet_candidate_shift',
    'original_bank_drop', 'original_physical_reorder', 'request_wire', 'source_text'])
def test_packet_request_and_original_bindings_cannot_be_substituted(damage):
    data = material(); kwargs = arguments(data)
    if damage == 'packet_pin': kwargs['expected_packet_sha256'] = '0' * 64
    elif damage == 'request_pin': kwargs['expected_request_sha256'] = '0' * 64
    elif damage == 'packet_row_drop': data['packet']['physical_rows'].pop(); kwargs['expected_packet_sha256'] = sha(wire(data['packet']))
    elif damage == 'packet_candidate_shift':
        data['packet']['banks'][0]['preparation']['requests'][0]['original_row']['candidates'][0]['source_occurrence']['start_utf8'] += 1
        kwargs['expected_packet_sha256'] = sha(wire(data['packet']))
    elif damage == 'original_bank_drop': data['banks'].pop()
    elif damage == 'original_physical_reorder': data['banks'][0]['physical_rows'].reverse()
    elif damage == 'request_wire': data['request_raw'] += b'\n'; kwargs['expected_request_sha256'] = sha(data['request_raw'])
    else: data['banks'][0]['join_inputs']['source_sections'][0]['text'] += ' substituted'
    with pytest.raises(ValueError):
        owner.prepare_stored_source_adoption_requests_v1(data['packet'], data['request_raw'], **kwargs)


@pytest.mark.parametrize('key', ['max_banks', 'max_physical_rows', 'max_original_bytes', 'max_report_bytes',
    'max_request_bytes', 'max_json_nodes', 'max_json_depth', 'max_string_bytes'])
def test_limits_are_lower_only_and_reject_boolean_aliases_before_source_work(key, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    for value in (correspondence.DEFAULT_LIMITS[key] + 1, True):
        with pytest.raises(owner.StoredSourceAdoptionRequestsError): prepare(data, limits={key: value})
    assert calls == []


@pytest.mark.parametrize('limits', [{'max_banks': 1}, {'max_physical_rows': 1}, {'max_original_bytes': 1},
    {'max_report_bytes': 1}, {'max_request_bytes': 1}, {'max_json_nodes': 1}, {'max_json_depth': 1}, {'max_string_bytes': 1}])
def test_lowered_input_and_preparation_caps_refuse_without_real_source_replay(limits, monkeypatch):
    data = material(); calls = []
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', lambda *args, **kwargs: calls.append(True))
    with pytest.raises(owner.StoredSourceAdoptionRequestsError): prepare(data, limits=limits)
    assert calls == []


@pytest.mark.parametrize('damage', ['packet', 'caller_original', 'detached_original', 'limits'])
def test_closing_guards_refuse_inputs_changed_during_genuine_replay(damage, monkeypatch):
    data = material(); limits = {'max_report_bytes': correspondence.DEFAULT_LIMITS['max_report_bytes']}
    original = legacy_review.prepare_legacy_source_review_requests; calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs); calls.append(True)
        if len(calls) == 1:
            if damage == 'packet': data['packet']['physical_rows'][0]['physical_identity']['row_ordinal'] += 1
            elif damage == 'caller_original': data['banks'][0]['join_inputs']['source_sections'][0]['text'] += ' changed'
            elif damage == 'detached_original': kwargs['source_sections'][0]['text'] += ' changed'
            else: limits['max_report_bytes'] -= 1
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate)
    with pytest.raises(ValueError): prepare(data, limits=limits)
    assert calls


@pytest.mark.parametrize('damage', ['section', 'version', 'occurrence', 'context', 'wrong_logical_candidate',
    'physical_row_bool', 'physical_row_unknown', 'physical_identity', 'source_use_extra', 'wrong_purpose',
    'wrong_role', 'invalid_civil_date', 'view_mismatch', 'empty_evidence', 'duplicate_evidence', 'old_claim_fields'])
def test_unsigned_declaration_refuses_cross_physical_choices_and_closed_field_violations(damage):
    data = material(); preparation = prepare(data)
    choice = deepcopy(preparation['rows'][0]['candidate_choices'][0])
    kwargs = declaration_arguments(preparation, data)
    if damage == 'section': choice['source_section_sha256'] = '0' * 64
    elif damage in ('version', 'occurrence', 'context'):
        choice[{'version': 'source_version_ref', 'occurrence': 'source_occurrence_ref', 'context': 'context_ref'}[damage]]['sha256'] = '0' * 64
    elif damage == 'wrong_logical_candidate': choice = deepcopy(preparation['rows'][1]['candidate_choices'][0])
    elif damage == 'physical_row_bool': kwargs['physical_reference']['physical_row_ordinal'] = False
    elif damage == 'physical_row_unknown': kwargs['physical_reference']['physical_row_ordinal'] = 99
    elif damage == 'physical_identity': kwargs['physical_reference']['physical_identity']['row_ordinal'] = 99
    elif damage == 'source_use_extra': kwargs['source_use']['authorized'] = True
    elif damage == 'wrong_purpose': kwargs['source_use']['purpose'] = 'copy_exact_declared_answer_variant_references_only'
    elif damage == 'wrong_role': kwargs['source_use']['declared_region_role'] = 'inferred_governing_law'
    elif damage == 'invalid_civil_date': kwargs['source_use']['legal_as_of_civil_date'] = '2026-02-30'
    elif damage == 'view_mismatch': kwargs['source_use']['view_profile'] = 'fixture:other-view'
    elif damage == 'empty_evidence': kwargs['evidence_refs'] = []
    elif damage == 'duplicate_evidence': kwargs['evidence_refs'] *= 2
    else: choice.update(schema='legal-corpus-legacy-source-binding-signed-claim/v1', action='record_legacy_candidate_structured_source_binding/v1', signature='cached-old-signature')
    with pytest.raises(ValueError):
        owner.record_stored_source_adoption_declaration_v1(preparation, choice, **kwargs)


@pytest.mark.parametrize('damage', ['choice', 'source_use', 'source_context', 'physical_subject',
    'signing_domain', 'signature', 'authority', 'decision_applied', 'gold_mask', 'rationale', 'evidence', 'timestamp'])
def test_rehashed_unsigned_body_mutations_fail_original_input_validation(damage):
    data = material(); preparation = prepare(data)
    choice = deepcopy(preparation['rows'][0]['candidate_choices'][0])
    declaration = record(preparation, data)
    if damage == 'choice': declaration['choice'] = deepcopy(preparation['rows'][0]['candidate_choices'][1])
    elif damage == 'source_use': declaration['source_use']['scope_id'] = 'fixture:changed-scope'
    elif damage == 'source_context': declaration['original_context']['availability'] = 'declared_complete'
    elif damage == 'physical_subject': declaration['physical_reference'] = deepcopy(preparation['rows'][1]['physical_reference'])
    elif damage == 'signing_domain': declaration['signing_domain']['action'] = 'activate_legacy_candidate_source_answer_snapshot/v1'
    elif damage == 'signature': declaration['signature'] = 'unverified-token'
    elif damage == 'authority': declaration['authority']['reviewer_authenticated'] = True
    elif damage == 'decision_applied': declaration['decision_applied'] = True
    elif damage == 'gold_mask': declaration['evaluation_gold_mask'] = 1
    elif damage == 'rationale': declaration['rationale'] += ' changed'
    elif damage == 'evidence': declaration['evidence_refs'][0]['sha256'] = '0' * 64
    else: declaration['declared_at_utc'] = '2026-10-20T00:00:00Z'
    with pytest.raises(ValueError): validate_declaration(declaration, preparation, choice, data)


def test_multibyte_rationale_obeys_utf8_byte_bound():
    data = material(); preparation = prepare(data)
    with pytest.raises(ValueError): record(preparation, data, rationale='é' * 4097)


def test_no_signature_assessment_or_application_engine_is_exported():
    assert not any(name.startswith(('assess_', 'apply_', 'sign_', 'authenticate_')) for name in owner.__all__)
    data = material(); preparation = prepare(data)
    assert all(row['declaration_template']['choice'] is None for row in preparation['rows'])
    flags(preparation)



@pytest.mark.parametrize('offered', ['preparation', 'declaration'])
def test_public_validators_refuse_offered_objects_mutated_during_genuine_replay(offered, monkeypatch):
    data = material(); preparation = prepare(data)
    choice = deepcopy(preparation['rows'][0]['candidate_choices'][0])
    declaration = record(preparation, data) if offered == 'declaration' else None
    original = legacy_review.prepare_legacy_source_review_requests; calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs); calls.append(True)
        if len(calls) == 1:
            if offered == 'preparation': preparation['rows'][0]['declaration_template']['choice'] = deepcopy(choice)
            else: declaration['source_use']['scope_id'] = 'fixture:changed-during-validation'
        return result
    monkeypatch.setattr(legacy_review, 'prepare_legacy_source_review_requests', mutate)
    with pytest.raises(ValueError):
        if offered == 'preparation': validate(preparation, data)
        else: validate_declaration(declaration, preparation, choice, data)
    assert calls


def test_validator_combined_root_bound_precedes_hashing_offered_output_and_originals(monkeypatch):
    data = material(); preparation = prepare(data)
    kwargs = arguments(data, limits={'max_original_bytes': 1})
    expected = sha(wire(preparation))
    def forbidden_hash(*args, **kwargs):
        raise AssertionError('SHA256 happened before combined-root refusal')
    monkeypatch.setattr(hashlib, 'sha256', forbidden_hash)
    with pytest.raises(owner.StoredSourceAdoptionRequestsError):
        owner.validate_stored_source_adoption_requests_v1(preparation, data['packet'], data['request_raw'],
            expected_report_sha256=expected, **kwargs)


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


def test_real_retained_source_adoption_authoring_preserves_13_16_150_without_actual_choices(tmp_path):
    assert os.environ.get('LEGAL_STORED_SOURCE_ADOPTION_ENROLLED') == '1', 'exact original admission required'
    assert os.environ.get('LEGAL_STORED_SOURCE_ADOPTION_INPUTS') == str(REAL_INPUTS)
    root_ref = {'path': str(REAL_INPUTS), 'bytes': REAL_INPUTS_BYTES, 'sha256': REAL_INPUTS_SHA256}
    inputs = read_json(root_ref)
    assert inputs['schema'] == 'legal-stored-source-adoption-qualification-inputs/v1'
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
    packet_raw = read_exact(inputs['packet'])
    packet = json.loads(packet_raw)
    assert packet_raw == wire(packet) + b'\n'
    assert sha(wire(packet)) == inputs['packet_canonical_sha256']
    request_raw = read_exact(inputs['request'])
    assert request_raw == wire(json.loads(request_raw))
    assert json.loads(request_raw) == fixture_helper().request_for(banks)
    assert packet['request_sha256'] == sha(request_raw)
    data = {'banks': banks, 'packet': packet, 'request_raw': request_raw}
    preparation = prepare(data)
    assert validate(preparation, data) == preparation
    check_pending(preparation, packet)
    expected_coverage = {'physical_rows': 16, 'logical_requests': 16, 'source_sections': 13,
        'candidate_occurrence_references': 150, 'pending_rows': 16, 'submitted_declarations': 0,
        'applied_source_decisions': 0, 'full_declared_population_retained': True}
    assert preparation['coverage'] == expected_coverage
    coverage = packet['coverage']
    assert coverage['banks'] == 2
    assert coverage['logical_requests'] == coverage['physical_rows'] == coverage['distinct_physical_identities'] == 16
    assert coverage['source_section_references'] == coverage['distinct_source_sections'] == 13
    assert coverage['candidate_occurrence_references'] == 150
    assert coverage['unique_candidate_rows'] == 11 and coverage['ambiguous_candidate_rows'] == 5
    assert coverage['disposition_counts'] == {'unique_exact_candidate': 11, 'ambiguous_exact_candidates': 5}
    assert fixture_helper().assert_geometry(packet) == 150
    assert len(packet['physical_rows']) == len(cache_oracles) == len(preparation['rows']) == 16
    for actual, oracle in zip(packet['physical_rows'], cache_oracles, strict=True):
        names = ('bank_id', 'physical_row_ordinal', 'physical_identity', 'paired_row_sha256', 'candidate_occurrence_ids')
        assert {key: actual[key] for key in names} == {key: oracle[key] for key in names}
    for bank, original in zip(packet['banks'], banks, strict=True):
        retained_join = json.loads(original['join_bytes'])
        assert bank['preparation']['source_sections'] == retained_join['source_sections']
        assert [request['original_row'] for request in bank['preparation']['requests']] == retained_join['rows']
    subjects = [row['subject'] for row in preparation['rows']]
    assert len({subject['record_cid'] for subject in subjects}) == 16
    assert sum(len(subject['active_slot_ids']) for subject in subjects) == 144
    assert sum(len(subject['deferred_slot_ids']) for subject in subjects) == 112
    assert sum(len(row['candidate_choices']) for row in preparation['rows']) == 150
    assert all(row['declaration_template'] == TEMPLATE for row in preparation['rows'])
    fixture_helper().no_authority(packet)
    full_raw = wire(packet) + b'\n'
    full_path = tmp_path / 'source-correspondence-full-report.json'
    with full_path.open('xb') as stream: stream.write(full_raw)
    full_ref = {'path': str(full_path), **raw_ref(full_raw)}
    request_path = tmp_path / 'source-correspondence-request.json'
    with request_path.open('xb') as stream: stream.write(request_raw)
    request_ref = {'path': str(request_path), **raw_ref(request_raw)}
    preparation_raw = wire(preparation) + b'\n'
    assert len(preparation_raw) <= 32 * 1024**2
    preparation_path = tmp_path / 'stored-source-adoption-preparation.json'
    with preparation_path.open('xb') as stream: stream.write(preparation_raw)
    preparation_ref = {'path': str(preparation_path), **raw_ref(preparation_raw)}
    evidence = {'schema': 'legal-stored-source-adoption-requests-engineering-evidence/v1',
        'coverage': coverage, 'adoption_coverage': preparation['coverage'],
        'full_report': full_ref, 'full_report_canonical_sha256': sha(wire(packet)),
        'adoption_preparation': preparation_ref, 'adoption_preparation_canonical_sha256': sha(wire(preparation)),
        'request_sha256': sha(request_raw), 'request_artifact': request_ref,
        'request_artifact_wire': 'exact canonical compact sorted Unicode JSON API bytes without final LF',
        'original_input_refs': [root_ref] + inputs['productive_originals'],
        'physical_cache_oracles': cache_oracles, 'retained_source_oracles': source_oracles,
        'exact_candidate_geometry_checked': 150, 'actual_submitted_reviews': 0,
        'selected_occurrences': 0, 'source_decisions_applied': 0,
        'actual_unsigned_declarations_authored': 0, 'actual_source_adoptions': 0,
        'active_pending_questions': 144, 'deferred_pending_questions': 112,
        'authoring_only': True, 'signatures_or_claims_generated': False,
        'original_parent_or26shards_opened': False, 'fresh_cache_table_verification': False,
        'fresh_full_raw_row_hash_recomputation': False,
        'correspondence_authority': packet['authority'], 'authority': preparation['authority'],
        'training_mask': 0, 'evaluation_gold_mask': 0, 'inference_view': None,
        'worker_lifetime_peak_rss_linux_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_scope': 'Linux worker lifetime peak includes bootstrap and fixtures; not an isolated owner peak or a memory bound proof.'}
    assert len(evidence['original_input_refs']) == 29
    with (tmp_path / EVIDENCE_NAME).open('xb') as stream:
        stream.write(wire(evidence) + b'\n')
