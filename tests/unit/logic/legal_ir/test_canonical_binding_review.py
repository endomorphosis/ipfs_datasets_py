"""Synthetic declarations exercise recording; no human review is performed."""

import builtins
import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_binding_review as subject

ANNOTATION_FIELDS = ('interpretation_status', 'ambiguity', 'unsupported_meaning', 'normative_rules',
                     'freeform_qualifier_scope', 'notes', 'reviewer_id', 'reviewed_at_utc')
MASK_FIELDS = ('weak_decoder_fit', 'strong_semantic_fit', 'contrastive_supervision',
               'proof_supervision', 'fidelity_evaluation')
FALSE_AUTHORITY = ('qualified', 'accepted', 'source_fidelity_established', 'proof_authority',
                   'independent_semantic_review_completed', 'reviewer_identity_authenticated',
                   'reviewer_independence_authenticated', 'semantic_gold_created',
                   'actual_training_or_evaluation_admission')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture_packet(count=2):
    items = []
    for index in range(count):
        source = f'Synthetic unit fixture {index}: the clerk must record evidence.'
        context = dict(role='none_required', text='', bindings={}, sha256=text_sha(''))
        input_sha = digest(dict(source_text=source, context=context))
        item_id = 'binding-review-item-' + hashlib.sha256(
            b'authored-binding-review-v1\0' + bytes.fromhex(input_sha)).hexdigest()[:24]
        items.append(dict(item_id=item_id, source_text=source, source_sha256=text_sha(source),
                          input_sha256=input_sha, context=context,
                          annotation=dict.fromkeys(ANNOTATION_FIELDS)))
    instructions = {name: 'Synthetic fixture instruction; no actual human review occurred.' for name in (
        'task', 'context', 'normative_rules', 'qualifier_scope', 'blank_annotations', 'identity', 'provenance')}
    return dict(schema='symbol-binding-source-reviewer/v1', instructions=instructions,
                items=sorted(items, key=lambda item: item['item_id']))


def rule(**changes):
    value = dict(modality='O', actor='fixture_actor', action='fixture_action', object='fixture_object',
                 conditions=['fixture_condition'], exceptions=['fixture_exception'], temporal=['fixture_time'])
    value.update(copy.deepcopy(changes))
    return value


def annotation(reviewer='unit-declared-A', *, status='normative'):
    return dict(interpretation_status=status, ambiguity=status == 'ambiguous',
                unsupported_meaning=status == 'unsupported',
                normative_rules=[rule()] if status == 'normative' else [],
                freeform_qualifier_scope='Synthetic fixture: all conditions, any exception, opaque time.',
                notes='Synthetic test declaration; no human interpretation or review is claimed.',
                reviewer_id=reviewer, reviewed_at_utc='2026-10-04T04:00:00Z')


def submission(packet, reviewer='unit-declared-A', *, indices=(0,), complete=True, status='normative'):
    value = copy.deepcopy(packet)
    value['items'] = [value['items'][index] for index in indices]
    if complete:
        for item in value['items']:
            item['annotation'] = annotation(reviewer, status=status)
    return value


def record(packet, *payloads):
    return subject.record_reviews(packet, list(payloads), expected_packet_sha256=digest(packet))


def first_record(receipt, payload):
    identity = payload['items'][0]['item_id']
    return next(item for item in receipt['items'] if item['item_id'] == identity)


def assert_no_authority(receipt):
    for value in (receipt, *receipt['items']):
        assert all(value[field] is False for field in FALSE_AUTHORITY)
    for field in ('human_reviews_authenticated', 'independent_reviews_authenticated'):
        assert type(receipt[field]) is int and receipt[field] == 0
    for field in ('model_calls', 'provider_calls', 'encoder_calls', 'prover_calls'):
        assert type(receipt[field]) is int and receipt[field] == 0
    for field in ('training_executed', 'automatic_adjudication', 'submissions_created'):
        assert receipt[field] is False


def test_all_64_blank_envelopes_remain_pending_and_detached_without_declarations():
    packet = fixture_packet(64)
    before = copy.deepcopy(packet)
    validation = subject.validate_blank_packet(packet, expected_packet_sha256=digest(packet))
    assert validation['item_count'] == 64
    assert validation['reviewer_packet_sha256'] == digest(packet)
    receipt = record(packet)
    assert receipt['status'] == 'pending'
    assert receipt['submission_count'] == receipt['declared_completed_annotation_count'] == 0
    assert receipt['status_counts']['pending'] == 64
    assert sum(receipt['status_counts'].values()) == 64
    assert all(item['received_declarations'] == [] for item in receipt['items'])
    assert all(item['complete_declaration_count'] == 0 for item in receipt['items'])
    assert all(item['masks'] == dict.fromkeys(MASK_FIELDS, 0) for item in receipt['items'])
    assert all(item['external_adjudication_status'] == 'pending' for item in receipt['items'])
    assert all(item['independent_adjudication_completed'] is False for item in receipt['items'])
    assert_no_authority(receipt)
    assert packet == before
    receipt['items'][0]['context']['bindings']['changed'] = True
    assert packet == before


def test_nonempty_blank_partial_subset_and_reordering_preserve_all_prepared_item_accounting():
    packet = fixture_packet(4)
    blank = submission(packet, complete=False, indices=(2, 0))
    before = copy.deepcopy((packet, blank))
    receipt = record(packet, blank)
    assert receipt['status_counts']['pending'] == 4
    assert sum(item['pending_declaration_count'] for item in receipt['items']) == 2
    assert sum(item['complete_declaration_count'] for item in receipt['items']) == 0
    assert (packet, blank) == before
    complete = submission(packet, indices=(2, 0))
    assert record(packet, complete)['status_counts']['single_review'] == 2
    complete['items'].reverse()
    assert record(packet, complete)['status_counts']['single_review'] == 2


def test_exact_canonical_packet_identity_is_required_and_distinct_from_file_bytes():
    packet = fixture_packet()
    canonical_pin = digest(packet)
    pretty_file_sha = hashlib.sha256((json.dumps(packet, indent=2) + '\n').encode()).hexdigest()
    assert pretty_file_sha != canonical_pin
    for call in (
        lambda: subject.validate_blank_packet(packet, expected_packet_sha256=pretty_file_sha),
        lambda: subject.record_reviews(packet, [], expected_packet_sha256='0' * 64),
        lambda: subject.record_reviews(packet, []),
    ):
        with pytest.raises((ValueError, TypeError)):
            call()
    changed = copy.deepcopy(packet)
    changed['instructions']['task'] += ' Changed packet identity.'
    with pytest.raises(ValueError):
        subject.validate_blank_packet(changed, expected_packet_sha256=canonical_pin)


@pytest.mark.parametrize('fault', ['source_hash', 'input_hash', 'namespace_id', 'context_binding',
                                 'context_role', 'nonblank_original', 'duplicate_input'])
def test_prepared_source_envelopes_id_recipe_empty_context_and_blank_slots_are_enforced(fault):
    packet = fixture_packet()
    item = packet['items'][0]
    if fault == 'source_hash':
        item['source_text'] += '\n'
    elif fault == 'input_hash':
        item['input_sha256'] = '0' * 64
    elif fault == 'namespace_id':
        item['item_id'] = 'other-review-item-' + item['item_id'].split('-')[-1]
    elif fault == 'context_binding':
        item['context']['bindings']['guessed_actor'] = 'clerk'
    elif fault == 'context_role':
        item['context']['role'] = 'explicit_assumptions'
    elif fault == 'nonblank_original':
        item['annotation']['reviewer_id'] = 'fabricated-original-review'
    else:
        packet['items'][1] = copy.deepcopy(item)
    with pytest.raises(ValueError):
        subject.validate_blank_packet(packet, expected_packet_sha256=digest(packet))


@pytest.mark.parametrize('fault', ['source_rehashed', 'context_rehashed', 'instructions', 'unknown_item'])
def test_submissions_cannot_replace_the_original_envelope_even_when_locally_rehashed(fault):
    packet = fixture_packet()
    payload = submission(packet)
    item = payload['items'][0]
    if fault == 'source_rehashed':
        item['source_text'] += '\n'
        item['source_sha256'] = text_sha(item['source_text'])
        item['input_sha256'] = digest(dict(source_text=item['source_text'], context=item['context']))
    elif fault == 'context_rehashed':
        item['context']['text'] = 'Added assumption.'
        item['context']['sha256'] = text_sha(item['context']['text'])
        item['input_sha256'] = digest(dict(source_text=item['source_text'], context=item['context']))
    elif fault == 'instructions':
        payload['instructions']['task'] = 'Replace immutable reviewer guidance.'
    else:
        item['item_id'] = packet['items'][1]['item_id']
    with pytest.raises(ValueError):
        record(packet, payload)


def test_two_named_declarations_can_agree_without_authenticating_people_or_adjudicating():
    packet = fixture_packet()
    first, second = submission(packet), submission(packet, 'unit-declared-B')
    second['items'][0]['annotation']['notes'] = 'Different synthetic note; same literal meaning signature.'
    second['items'][0]['annotation']['reviewed_at_utc'] = '2026-10-04T04:01:00.123456+00:00'
    receipt = record(packet, first, second)
    item = first_record(receipt, first)
    assert item['status'] == 'agreed_multiple_reviews'
    assert item['complete_declaration_count'] == 2
    assert item['meaning_signature_count'] == 1
    assert item['external_adjudication_status'] == 'pending'
    assert item['independent_adjudication_completed'] is False
    assert item['masks'] == dict.fromkeys(MASK_FIELDS, 0)
    assert_no_authority(receipt)


@pytest.mark.parametrize('status,expected', [('normative', 'single_review'),
    ('no_normative_rule', 'single_review'), ('ambiguous', 'ambiguous'), ('unsupported', 'unsupported')])
def test_literal_dispositions_are_recorded_without_selecting_the_source_meaning(status, expected):
    packet = fixture_packet()
    payload = submission(packet, status=status)
    receipt = record(packet, payload)
    item = first_record(receipt, payload)
    assert item['status'] == expected
    assert item['received_declarations'][0]['annotation'] == payload['items'][0]['annotation']
    assert item['masks'] == dict.fromkeys(MASK_FIELDS, 0)


def test_null_rule_and_nested_slots_stay_pending_while_explicit_empty_values_are_reviewed():
    packet = fixture_packet()
    payload = submission(packet, status='no_normative_rule')
    assert first_record(record(packet, payload), payload)['status'] == 'single_review'
    payload['items'][0]['annotation']['normative_rules'] = None
    pending = first_record(record(packet, payload), payload)
    assert pending['status'] == 'pending'
    assert 'normative_rules' in pending['received_declarations'][0]['missing_fields']
    payload = submission(packet)
    payload['items'][0]['annotation']['normative_rules'] = [rule(object='', conditions=[], exceptions=[], temporal=[])]
    payload['items'][0]['annotation']['freeform_qualifier_scope'] = ''
    assert first_record(record(packet, payload), payload)['status'] == 'single_review'
    payload['items'][0]['annotation']['normative_rules'][0]['conditions'] = None
    pending = first_record(record(packet, payload), payload)
    assert pending['status'] == 'pending'
    assert pending['received_declarations'][0]['meaning_signature_sha256'] is None


def test_complete_and_partial_declarations_do_not_count_partial_slots_as_agreement():
    packet = fixture_packet()
    first, partial = submission(packet), submission(packet, 'unit-declared-B')
    partial['items'][0]['annotation']['reviewer_id'] = None
    item = first_record(record(packet, first, partial), first)
    assert item['status'] == 'single_review'
    assert item['complete_declaration_count'] == item['pending_declaration_count'] == 1
    assert item['meaning_signature_count'] == 1


@pytest.mark.parametrize('change', ['scope', 'qualifier_order', 'qualifier_multiplicity', 'rule_order',
                                  'rule_multiplicity', 'disposition'])
def test_scope_order_multiplicity_and_disposition_disagreements_remain_disputed(change):
    packet = fixture_packet()
    first, second = submission(packet), submission(packet, 'unit-declared-B')
    for payload in (first, second):
        payload['items'][0]['annotation']['normative_rules'] = [rule(conditions=['a', 'b']), rule(actor='other_actor')]
    changed = second['items'][0]['annotation']
    if change == 'scope':
        changed['freeform_qualifier_scope'] = 'Synthetic fixture alternative: either condition applies.'
    elif change == 'qualifier_order':
        changed['normative_rules'][0]['conditions'].reverse()
    elif change == 'qualifier_multiplicity':
        changed['normative_rules'][0]['conditions'].append('a')
    elif change == 'rule_order':
        changed['normative_rules'].reverse()
    elif change == 'rule_multiplicity':
        changed['normative_rules'].append(copy.deepcopy(changed['normative_rules'][0]))
    else:
        second['items'][0]['annotation'] = annotation('unit-declared-B', status='no_normative_rule')
    item = first_record(record(packet, first, second), first)
    assert item['status'] == 'disputed'
    assert item['meaning_signature_count'] == 2
    assert item['received_declarations'][1]['annotation'] == second['items'][0]['annotation']
    assert item['independent_adjudication_completed'] is False


@pytest.mark.parametrize('kind', ['payload', 'item', 'same_reviewer_different_file'])
def test_duplicate_payload_item_and_reviewer_input_do_not_inflate_declaration_counts(kind):
    packet = fixture_packet()
    first = submission(packet)
    second = copy.deepcopy(first)
    if kind == 'payload':
        payloads = (first, second)
    elif kind == 'item':
        second['items'].append(copy.deepcopy(second['items'][0]))
        payloads = (second,)
    else:
        second['items'][0]['annotation']['notes'] += ' Changed file; same declaration identity.'
        payloads = (first, second)
    with pytest.raises(ValueError):
        record(packet, *payloads)


def test_same_declared_name_on_disjoint_inputs_is_not_a_duplicate_or_authenticated_person():
    packet = fixture_packet()
    first, second = submission(packet, indices=(0,)), submission(packet, indices=(1,))
    receipt = record(packet, first, second)
    assert receipt['status_counts']['single_review'] == 2
    assert receipt['declared_completed_annotation_count'] == 2
    assert_no_authority(receipt)


@pytest.mark.parametrize('fault', ['normative_without_rule', 'normative_ambiguity',
                                 'no_rule_nonempty', 'unsupported_false', 'qualifiers_without_scope'])
def test_contradictory_dispositions_fail_instead_of_becoming_complete_declarations(fault):
    packet = fixture_packet()
    status = 'no_normative_rule' if fault == 'no_rule_nonempty' else 'unsupported' if fault == 'unsupported_false' else 'normative'
    payload = submission(packet, status=status)
    answer = payload['items'][0]['annotation']
    if fault == 'normative_without_rule':
        answer['normative_rules'] = []
    elif fault == 'normative_ambiguity':
        answer['ambiguity'] = True
    elif fault == 'no_rule_nonempty':
        answer['normative_rules'] = [rule()]
    elif fault == 'unsupported_false':
        answer['unsupported_meaning'] = False
    else:
        answer['freeform_qualifier_scope'] = ''
    with pytest.raises(ValueError):
        record(packet, payload)


@pytest.mark.parametrize('field,value', [('ambiguity', 0), ('reviewer_id', ' unit-name '),
                                      ('reviewed_at_utc', '2026-02-30T04:00:00Z'),
                                      ('reviewed_at_utc', '2026-10-04T04:00:00+01:00'),
                                      ('notes', 'bad\x00text'), ('notes', 'bad\ud800text')])
def test_declaration_type_calendar_utc_and_utf8_boundaries_fail_closed(field, value):
    packet = fixture_packet()
    payload = submission(packet)
    payload['items'][0]['annotation'][field] = value
    with pytest.raises(ValueError):
        record(packet, payload)


def test_literal_unicode_meaning_is_preserved_without_normalization_or_adjudication():
    packet = fixture_packet()
    first, second = submission(packet), submission(packet, 'unit-declared-B')
    first['items'][0]['annotation']['freeform_qualifier_scope'] = 'Synthetic café scope.'
    second['items'][0]['annotation']['freeform_qualifier_scope'] = 'Synthetic cafe\u0301 scope.'
    receipt = record(packet, first, second)
    item = first_record(receipt, first)
    assert item['status'] == 'disputed'
    assert [entry['annotation']['freeform_qualifier_scope'] for entry in item['received_declarations']] == [
        first['items'][0]['annotation']['freeform_qualifier_scope'],
        second['items'][0]['annotation']['freeform_qualifier_scope']]
    assert_no_authority(receipt)


@pytest.mark.parametrize('where,field,value', [('payload', 'canonical_ir', {}),
    ('item', 'proposed_split', 'proposed_train'), ('annotation', 'reviewer_authenticated', True),
    ('rule', 'proof_verified', True)])
def test_closed_submission_schema_rejects_candidate_gold_split_and_authority_leaks(where, field, value):
    packet = fixture_packet()
    payload = submission(packet)
    targets = {'payload': payload, 'item': payload['items'][0],
               'annotation': payload['items'][0]['annotation'],
               'rule': payload['items'][0]['annotation']['normative_rules'][0]}
    targets[where][field] = value
    with pytest.raises(ValueError):
        record(packet, payload)


def test_rule_qualifier_item_and_submission_budgets_reject_without_truncation():
    packet = fixture_packet()
    for mutate in (
        lambda payload: payload['items'][0]['annotation'].update(normative_rules=[rule()] * 33),
        lambda payload: payload['items'][0]['annotation']['normative_rules'][0].update(conditions=['atom'] * 129),
    ):
        payload = submission(packet)
        mutate(payload)
        with pytest.raises(ValueError):
            record(packet, payload)
    too_many_items = fixture_packet(65)
    with pytest.raises(ValueError):
        subject.validate_blank_packet(too_many_items, expected_packet_sha256=digest(too_many_items))
    payloads = [submission(packet, f'unit-declared-{i}') for i in range(21)]
    with pytest.raises(ValueError):
        record(packet, *payloads)


def test_deep_nonfinite_and_nonordinary_values_reject_before_annotation_helpers(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_admission as legacy,
    )

    packet = fixture_packet()

    def forbidden_annotation(value):
        pytest.fail('invalid ordinary JSON reached annotation helper')

    monkeypatch.setattr(legacy, '_annotation', forbidden_annotation)
    deep = None
    for _ in range(20):
        deep = [deep]
    for poison in (deep, float('nan'), object()):
        payload = submission(packet)
        payload['items'][0]['annotation']['notes'] = poison
        with pytest.raises(ValueError):
            record(packet, payload)


def test_recording_and_guide_require_no_legacy_bundle_model_prover_or_network(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_admission as legacy,
    )

    packet = fixture_packet()
    original_import = builtins.__import__
    forbidden = {'torch', 'numpy', 'spacy', 'transformers', 'sentence_transformers',
                 'requests', 'httpx', 'openai', 'z3', 'cvc5'}

    def guarded(name, *args, **kwargs):
        assert name.split('.')[0] not in forbidden, name
        return original_import(name, *args, **kwargs)

    def no_legacy_bundle(value):
        pytest.fail('new source-only adapter invoked legacy private reference bundle')

    monkeypatch.setattr(builtins, '__import__', guarded)
    monkeypatch.setattr(legacy, '_blank_bundle', no_legacy_bundle)
    receipt = record(packet)
    subject.validate_recording(receipt, packet, [], expected_packet_sha256=digest(packet))
    guide = subject.submission_guide()
    assert all(guide[field] is False for field in FALSE_AUTHORITY)
    assert all(type(guide[field]) is int and guide[field] == 0 for field in (
        'model_calls', 'provider_calls', 'encoder_calls', 'prover_calls'))
    assert 'unit-declared-A' not in json.dumps(guide)
    guide['mutated'] = True
    assert 'mutated' not in subject.submission_guide()
    assert_no_authority(receipt)


@pytest.mark.parametrize('fault', ['source', 'signature', 'mask', 'authority', 'count_alias',
                                 'complete_alias', 'extra'])
def test_replay_rejects_resealed_receipt_corruption_and_numeric_aliases(fault):
    packet = fixture_packet()
    payload = submission(packet)
    receipt = record(packet, payload)
    changed = copy.deepcopy(receipt)
    item = first_record(changed, payload)
    if fault == 'source':
        item['source_text'] += ' Changed receipt source.'
    elif fault == 'signature':
        item['received_declarations'][0]['meaning_signature_sha256'] = '0' * 64
    elif fault == 'mask':
        item['masks']['weak_decoder_fit'] = 1
    elif fault == 'authority':
        changed['qualified'] = 0
    elif fault == 'count_alias':
        item['complete_declaration_count'] = 1.0
    elif fault == 'complete_alias':
        item['received_declarations'][0]['complete'] = 1
    else:
        changed['model_candidate'] = {}
    changed['receipt_sha256'] = digest({key: value for key, value in changed.items() if key != 'receipt_sha256'})
    with pytest.raises(ValueError):
        subject.validate_recording(changed, packet, [payload], expected_packet_sha256=digest(packet))


def test_exact_receipt_replay_is_bound_to_packet_and_submission_generations_and_returns_detached_values():
    packet = fixture_packet()
    payload = submission(packet)
    before = copy.deepcopy((packet, payload))
    receipt = record(packet, payload)
    assert receipt == record(packet, payload)
    assert receipt['receipt_sha256'] == digest({key: value for key, value in receipt.items() if key != 'receipt_sha256'})
    validation = subject.validate_recording(receipt, packet, [payload], expected_packet_sha256=digest(packet))
    assert validation['status'] == 'validated_declaration_recording_only'
    assert validation['reviewer_packet_sha256'] == digest(packet)
    assert validation['masks'] == dict.fromkeys(MASK_FIELDS, 0)
    assert all(validation[field] is False for field in FALSE_AUTHORITY)
    validation['status_counts']['pending'] = 999
    assert receipt['status_counts']['pending'] == 1
    receipt['items'][0]['context']['bindings']['changed'] = True
    assert (packet, payload) == before
    original_receipt = record(packet, payload)
    changed = copy.deepcopy(payload)
    changed['items'][0]['annotation']['notes'] += ' Changed submission bytes but same meaning.'
    with pytest.raises(ValueError):
        subject.validate_recording(original_receipt, packet, [changed], expected_packet_sha256=digest(packet))
    changed_packet = copy.deepcopy(packet)
    changed_packet['instructions']['task'] += ' Changed original packet bytes.'
    with pytest.raises(ValueError):
        subject.validate_recording(original_receipt, changed_packet, [payload],
                                   expected_packet_sha256=digest(changed_packet))


def test_plain_json_and_bounded_source_packet_reject_unrepresentable_or_unscoped_inputs():
    packet = fixture_packet()
    for poison in ('\x00source', 'é' * (subject.MAX_SOURCE_BYTES // 2 + 1)):
        changed = copy.deepcopy(packet)
        changed['items'][0]['source_text'] = poison
        with pytest.raises(ValueError):
            subject.validate_blank_packet(changed, expected_packet_sha256=digest(changed))

    class DictionarySubclass(dict):
        pass

    with pytest.raises(ValueError):
        subject.validate_blank_packet(DictionarySubclass(packet), expected_packet_sha256=digest(packet))
    with pytest.raises(TypeError):
        subject.record_reviews(packet, [], expected_packet_sha256=digest(packet), organizer={})
    with pytest.raises(TypeError):
        subject.record_reviews(packet, [], expected_packet_sha256=digest(packet), alias_profile={})


def test_a_known_disagreement_cannot_be_resolved_by_an_extra_candidate_or_reference_answer():
    packet = fixture_packet()
    first, second = submission(packet), submission(packet, 'unit-declared-B')
    second['items'][0]['annotation']['normative_rules'][0]['modality'] = 'P'
    receipt = record(packet, first, second)
    assert first_record(receipt, first)['status'] == 'disputed'
    assert receipt['reference_used_to_resolve_disputes'] is False
    assert receipt['authored_reference_scoring_executed'] is False
    assert receipt['candidate_aware_computation'] is False
    changed_packet = copy.deepcopy(packet)
    changed_packet['reference_rule'] = rule()
    with pytest.raises(ValueError):
        subject.record_reviews(changed_packet, [first, second], expected_packet_sha256=digest(changed_packet))
    assert_no_authority(receipt)
