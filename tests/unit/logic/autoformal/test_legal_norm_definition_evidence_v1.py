"""Exact fictional term/definition nominations, never accepted legal meanings."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as sampling
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review_context as context
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_definition_binding_v2 as binding
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_definition_review_v2 as definition_link
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as definition_review
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.autoformal import legal_norm_definition_evidence_v1 as owner


def fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NORM = fixture('_definition_link_norm_fixture', 'test_legal_norm_interpretation_review_v1.py')
DEFINITION = fixture('_definition_link_definition_fixture', 'test_legal_source_sampling_definition_review_v2.py')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def pending_review(original):
    registry = dict(schema=signatures.REGISTRY_SCHEMA, mode='unavailable',
                    process_id='fixture:definition-evidence', generation=1,
                    revocation_generation=1, valid_from_utc=NORM.START,
                    valid_until_utc=NORM.END, keys=[], revoked_principals=[])
    policy = dict(schema=signatures.POLICY_SCHEMA, mode='unavailable',
                  policy_id='fixture:definition-evidence-policy', process_id=registry['process_id'],
                  registry_sha256=signatures.digest(registry), action=definition_review.ACTION,
                  audience=definition_review.AUDIENCE, required_roles=list(signatures.ROLES),
                  valid_from_utc=NORM.START, valid_until_utc=NORM.END,
                  max_review_age_seconds=86400)
    arguments = {key: original['args'][key] for key in (
        'candidate_inputs', 'expected_candidate_pin', 'context_inputs', 'expected_context_population')}
    arguments.update(subject=original['subject'], registry=registry, policy=policy, reviews=[],
                     dependency_manifest=original['args']['dependency_manifest'],
                     expected_subject_sha256=digest(original['subject']),
                     expected_registry_sha256=digest(registry), expected_policy_sha256=digest(policy),
                     expected_reviews_sha256=digest([]),
                     expected_manifest_sha256=original['args']['expected_manifest_sha256'],
                     at_time_utc=NORM.NOW, evidence_artifacts={},
                     **NORM.observations(original['args']['dependency_manifest']))
    assessment = definition_review.assess_definition_reviews_v2(**arguments)
    return dict(assessment=assessment, expected_assessment_sha256=digest(assessment),
                assessment_inputs=arguments)


def build_case(*, unrelated_support=False):
    """Two explicit alternatives, one shared context and two distinct variable uses.

    The fictional 'Clérk' source and fictional definition head are deliberately
    different literals. The declared association is not equivalence or resolution.
    """
    value = NORM.fixture.case()
    norm_inputs = NORM.preparation_arguments(value)
    source = value['source']
    replay = deepcopy(source['args'])
    if 'limits' in replay:
        replay['sampling_limits'] = replay.pop('limits')
    replay['expected_sampling_report_sha256'] = digest(source['sampling'])
    bundle = sampling.prepare_sampling_review_bundle(source['raw'], **replay)
    target_source = dict(bundle=bundle, raw=source['raw'],
                         expected_bundle_sha256=digest(bundle), replay_inputs=replay)
    target_guide = next(row for row in bundle['guides']
                        if row['subject_ref']['kind'] == 'unit'
                        and row['subject_ref']['sha256'] == digest(source['unit']))
    originals = [DEFINITION.joined_case(shape=shape) for shape in ('opaque', 'nested')]
    definition_source = originals[0]['source']
    assert definition_source['bundle'] == originals[1]['source']['bundle']
    sources = [target_source, dict(bundle=definition_source['bundle'], raw=definition_source['raw'],
                                  expected_bundle_sha256=digest(definition_source['bundle']),
                                  replay_inputs=definition_source['replay'])]
    required = DEFINITION._BINDING.selected_guides(definition_source)
    attachments = []
    for guide in required:
        attachments.append(dict(target_bundle_sha256=sources[0]['expected_bundle_sha256'],
                                target_subject_ref=target_guide['subject_ref'],
                                supporting_bundle_sha256=sources[1]['expected_bundle_sha256'],
                                supporting_subject_ref=guide['subject_ref'],
                                role='Fictional definition nomination; applicability unresolved.'))
        attachments.append(dict(target_bundle_sha256=sources[1]['expected_bundle_sha256'],
                                target_subject_ref=guide['subject_ref'],
                                supporting_bundle_sha256=sources[0]['expected_bundle_sha256'],
                                supporting_subject_ref=target_guide['subject_ref'],
                                role='Fictional context for the definition; not meaning evidence.'))
    if unrelated_support:
        guide = next(row for row in definition_source['bundle']['guides']
                     if row['subject_ref']['kind'] == 'unit'
                     and row['subject_ref'] not in [x['subject_ref'] for x in required])
        attachments.append(dict(target_bundle_sha256=sources[0]['expected_bundle_sha256'],
                                target_subject_ref=target_guide['subject_ref'],
                                supporting_bundle_sha256=sources[1]['expected_bundle_sha256'],
                                supporting_subject_ref=guide['subject_ref'],
                                role='Unrelated unit in the same source; not definition evidence.'))
    packet = context.prepare(sources, attachments, expected_attachments_sha256=digest(attachments))
    norm_inputs['context_inputs'] = dict(packet=packet, sources=sources, attachments=attachments,
        expected_context_sha256=digest(packet), expected_attachments_sha256=digest(attachments), limits=None)
    preparation = norm.prepare_norm_review_evidence_v1(**norm_inputs)
    alternatives = []
    for index, original in enumerate(originals):
        contextual_inputs = dict(request_raw=original['source']['request_raw'], context=packet,
            responses=[], sources=sources, attachments=attachments,
            expected_request_sha256=sha(original['source']['request_raw']),
            expected_definition_bundle_sha256=sources[1]['expected_bundle_sha256'],
            expected_context_sha256=digest(packet), expected_response_sha256s=[],
            expected_attachments_sha256=digest(attachments))
        result = binding.prepare_contextual_definition_binding_v2(**contextual_inputs)
        arguments = {key: val for key, val in original['args'].items()
                     if key != 'binding_replay_inputs'}
        arguments.update(binding_result=result, review_subject=original['subject'],
                         expected_binding_sha256=digest(result), contextual_replay_inputs=contextual_inputs)
        correspondence = definition_link.prepare_contextual_definition_review_correspondence_v2(**arguments)
        alternatives.append(dict(alternative_id='fictional-definition-' + str(index),
            correspondence=correspondence, expected_correspondence_sha256=digest(correspondence),
            correspondence_inputs=arguments, review_evidence=pending_review(original)))
    mapping = preparation['correspondence']['request']['typed_rows']
    selected = [row for row in mapping if row['target']['kind'] == 'variable'
                and row['source_paths'] == ['/occurrences/0/anchor']]
    assert len(selected) == 2
    nomination = preparation['context_evidence']['nominations'][-1]
    links = [dict(alternative_id=alt['alternative_id'], target=row['target'],
                  source_paths=row['source_paths'], nomination_sha256=digest(nomination),
                  rationale='Authored lexical nomination only; no same-meaning assertion.')
             for row in selected for alt in alternatives]
    request = dict(schema=owner.REQUEST_SCHEMA,
                   interpretation_status='authored_unreviewed_definition_nomination',
                   norm_preparation_sha256=digest(preparation), links=links)
    raw = wire(request)
    return dict(norm_preparation=preparation, request_raw=raw,
                expected_norm_preparation_sha256=digest(preparation), expected_request_sha256=sha(raw),
                norm_inputs=norm_inputs, definitions=alternatives)


def prepare(case):
    return owner.prepare_norm_definition_evidence_v1(**case)


def validate(case, report):
    return owner.validate_norm_definition_evidence_v1(
        report, expected_report_sha256=owner.norm_definition_evidence_sha256(report), **case)


def changed_request(case, change):
    value = deepcopy(case)
    request = json.loads(value['request_raw'])
    change(request)
    value['request_raw'] = wire(request)
    value['expected_request_sha256'] = sha(value['request_raw'])
    return value


@pytest.fixture(scope='module')
def base_case():
    return build_case()


@pytest.fixture(scope='module')
def base_report(base_case):
    return prepare(base_case)


def test_two_competing_definitions_and_two_occurrences_remain_distinct(base_case, base_report):
    encoded = wire(base_report)
    for endpoint in base_case['definitions']:
        assert endpoint['alternative_id'].encode() in encoded
        assert endpoint['expected_correspondence_sha256'].encode() in encoded
    for row in json.loads(base_case['request_raw'])['links']:
        assert row['target']['typed_path'].encode() in encoded
    assert base_report['governing_definition_use'] is None
    assert all(value is False for value in base_report['authority'].values())
    assert type(base_report['training_mask']) is int and base_report['training_mask'] == 0
    assert type(base_report['evaluation_gold_mask']) is int and base_report['evaluation_gold_mask'] == 0
    assert base_report['counts'] == dict(alternatives=2, links=4, distinct_typed_uses=2,
                                       supplied_definition_assessments=2)
    for row in base_report['links']:
        assert row['typed_context']['binding']['name'] == 'actor'
        assert row['typed_context']['argument']['role'] == 'actor'
        assert row['source_rows'][0]['anchor_mapping']['declaration_path'] == '/occurrences/0/anchor'
        assert row['typed_node']['symbol'] == 'actor'
        assert row['definition_support']['applicability_verified'] is False
    assert base_report['original_signatures_cover_companion'] is False
    assert base_report['original_unresolved'] == base_case['norm_preparation']['correspondence']['retained_unresolved']
    assert validate(base_case, base_report) == base_report


def test_original_inputs_remain_exact_and_pending(base_case, base_report):
    assert base_case['norm_preparation']['context_evidence']['typed_definition_reviews_supplied'] is False
    assert base_case['norm_preparation']['governing_definition_use'] is None
    assert all(endpoint['review_evidence']['assessment']['evidence_assessment_status'] == 'pending'
               for endpoint in base_case['definitions'])
    assert all(endpoint['review_evidence']['assessment_inputs']['reviews'] == []
               for endpoint in base_case['definitions'])


@pytest.mark.parametrize('field', ['expected_norm_preparation_sha256', 'expected_request_sha256'])
def test_independent_norm_and_request_pins_required_before_replay(base_case, field, monkeypatch):
    case = deepcopy(base_case)
    case[field] = '0' * 64
    def unexpected(*args, **kwargs):
        pytest.fail('mismatched independent input reached operation replay')
    monkeypatch.setattr(norm, 'prepare_norm_review_evidence_v1', unexpected)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize('mutation', ['target_hash', 'target_path', 'source_paths', 'unknown_alternative',
                                     'nomination', 'duplicate_link', 'unused_alternative', 'modal_node'])
def test_wrong_or_incomplete_join_is_rejected(base_case, mutation):
    def change(request):
        row = request['links'][0]
        if mutation == 'target_hash':
            row['target']['typed_sha256'] = '0' * 64
        elif mutation == 'target_path':
            row['target']['typed_path'] += '/arguments/0'
        elif mutation == 'source_paths':
            row['source_paths'] = ['/occurrences/3/anchor']
        elif mutation == 'unknown_alternative':
            row['alternative_id'] = 'missing'
        elif mutation == 'nomination':
            row['nomination_sha256'] = '0' * 64
        elif mutation == 'duplicate_link':
            request['links'].append(deepcopy(row))
        elif mutation == 'unused_alternative':
            request['links'] = [x for x in request['links'] if x['alternative_id'].endswith('0')]
        else:
            target = next(x for x in base_case['norm_preparation']['correspondence']['request']['typed_rows']
                          if x['target']['kind'] == 'legacy.deontic/v1')
            row['target'], row['source_paths'] = target['target'], target['source_paths']
    with pytest.raises(ValueError):
        prepare(changed_request(base_case, change))


@pytest.mark.parametrize('field', ['correspondence', 'review_assessment', 'subject', 'candidate_bytes', 'shared_context'])
def test_endpoint_substitution_cannot_reuse_another_binding(base_case, field):
    case = deepcopy(base_case)
    endpoint = case['definitions'][0]
    other = case['definitions'][1]
    if field == 'correspondence':
        endpoint['correspondence'] = other['correspondence']
        endpoint['expected_correspondence_sha256'] = other['expected_correspondence_sha256']
    elif field == 'review_assessment':
        endpoint['review_evidence'] = other['review_evidence']
    elif field == 'subject':
        endpoint['correspondence_inputs']['review_subject'] = other['correspondence_inputs']['review_subject']
    elif field == 'candidate_bytes':
        endpoint['correspondence_inputs']['candidate_inputs']['candidate_raw'] += b' '
    else:
        endpoint['correspondence_inputs']['contextual_replay_inputs']['expected_context_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        prepare(case)


def test_definition_assessment_is_optional_and_absence_stays_explicit(base_case):
    case = deepcopy(base_case)
    for endpoint in case['definitions']:
        endpoint['review_evidence'] = None
    report = prepare(case)
    assert report['governing_definition_use'] is None
    assert report['training_mask'] == 0
    assert validate(case, report) == report


@pytest.mark.parametrize('field,value', [('training_mask', 1), ('evaluation_gold_mask', False),
                                        ('governing_definition_use', 'approved')])
def test_rehashed_output_cannot_promote_authority(base_case, base_report, field, value):
    report = deepcopy(base_report)
    report[field] = value
    with pytest.raises(ValueError):
        validate(base_case, report)


def test_duplicate_alternative_identity_rejected(base_case):
    case = deepcopy(base_case)
    case['definitions'][1]['alternative_id'] = case['definitions'][0]['alternative_id']
    with pytest.raises(ValueError):
        prepare(case)


def test_original_input_mutation_during_replay_rejected(base_case, monkeypatch):
    case = deepcopy(base_case)
    original = norm.prepare_norm_review_evidence_v1
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        case['definitions'][0]['alternative_id'] = 'changed-during-replay'
        return result
    monkeypatch.setattr(norm, 'prepare_norm_review_evidence_v1', mutate)
    with pytest.raises(ValueError, match='chang'):
        prepare(case)


def test_detached_inputs_changed_during_replay_rejected(base_case, monkeypatch):
    original = norm.prepare_norm_review_evidence_v1
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        kwargs['context_inputs']['sources'][0]['raw'] += b' '
        return result
    monkeypatch.setattr(norm, 'prepare_norm_review_evidence_v1', mutate)
    with pytest.raises(ValueError, match='chang'):
        prepare(deepcopy(base_case))


def test_first_call_detects_producer_bytes_changed_during_replay(base_case, monkeypatch, tmp_path):
    copied = tmp_path / 'copied_definition_evidence_owner.py'
    original_bytes = Path(owner.__file__).read_bytes()
    copied.write_bytes(original_bytes)
    monkeypatch.setattr(owner, '_SELF_PATH', copied)
    monkeypatch.setattr(owner, '_OPERATION_PINS', None)
    original = norm.prepare_norm_review_evidence_v1
    calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append('replayed')
        copied.write_bytes(original_bytes + b'\n# synthetic producer mutation\n')
        return result
    monkeypatch.setattr(norm, 'prepare_norm_review_evidence_v1', mutate)
    with pytest.raises(ValueError, match='chang'):
        prepare(deepcopy(base_case))
    assert calls == ['replayed']


@pytest.mark.parametrize('field', ['sources', 'attachments'])
def test_complete_shared_population_cannot_be_substituted(base_case, field, monkeypatch):
    case = deepcopy(base_case)
    # Replace this list instead of editing an aliased fixture object, so only
    # the definition endpoint's supplied population changes.
    replay = case['definitions'][0]['correspondence_inputs']['contextual_replay_inputs']
    replay[field] = list(reversed(replay[field]))
    def unexpected(*args, **kwargs):
        pytest.fail('inconsistent shared context reached norm replay')
    monkeypatch.setattr(norm, 'prepare_norm_review_evidence_v1', unexpected)
    with pytest.raises(ValueError):
        prepare(case)


def test_unrelated_unit_in_same_definition_source_does_not_supply_definition_use():
    case = build_case(unrelated_support=True)
    with pytest.raises(ValueError, match='required definition subject|supporting nomination'):
        prepare(case)


def test_oversized_and_duplicate_key_requests_refuse_before_replay(base_case, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('invalid request reached norm operation')
    monkeypatch.setattr(norm, 'prepare_norm_review_evidence_v1', unexpected)
    for raw in (b'{' + b' ' * (4 * 1024 * 1024) + b'}', b'{"schema":"x","schema":"y"}'):
        case = dict(base_case, request_raw=raw, expected_request_sha256=sha(raw))
        with pytest.raises(ValueError):
            prepare(case)


@pytest.mark.parametrize('limit', [True, False, None, '7', 7.0, 0, -1, 4_000_001])
def test_snapshot_node_profile_requires_bounded_exact_positive_integer(limit):
    with pytest.raises(ValueError, match='positive integer snapshot node budget'):
        norm._snapshot([], max_nodes=limit)


def test_norm_default_node_limit_still_rejects_oversized_population_immediately():
    # Root plus these members exceeds the unchanged 1,500,000-node default.
    # The list cardinality guard rejects before traversing its scalar members.
    with pytest.raises(ValueError, match='bounded review list'):
        norm._snapshot([None] * 1_500_000)


def test_companion_profile_charges_combined_components_and_preserves_commitment(monkeypatch):
    population = [[True, None], [False, None]]
    original = norm._snapshot(population)
    assert owner.MAX_INPUT_NODES == 4_000_000
    assert owner._snapshot(population) == original
    # Lower only this companion's profile to exercise the exact boundary
    # cheaply: each child is three nodes, the aggregate is seven, not six.
    monkeypatch.setattr(owner, 'MAX_INPUT_NODES', 7)
    assert owner._snapshot(population) == original
    monkeypatch.setattr(owner, 'MAX_INPUT_NODES', 6)
    with pytest.raises(ValueError, match='bounded review list|bounded review input structure'):
        owner._snapshot(population)
    assert norm._snapshot(population) == original


def test_companion_node_profile_preserves_aggregate_byte_bound(monkeypatch):
    # Container cost 17 plus each raw item's 15+16 charges totals 79.
    population = [b'x' * 15, b'y' * 15]
    monkeypatch.setattr(norm, 'MAX_INPUT_BYTES', 79)
    expected = norm._snapshot(population)
    assert owner._snapshot(population) == expected
    monkeypatch.setattr(norm, 'MAX_INPUT_BYTES', 78)
    with pytest.raises(ValueError, match='aggregate review input byte bound'):
        owner._snapshot(population)


def test_companion_node_profile_preserves_depth_bound():
    nested = None
    for _ in range(96):
        nested = [nested]
    assert owner._snapshot(nested) == norm._snapshot(nested)
    with pytest.raises(ValueError, match='bounded review input structure'):
        owner._snapshot([nested])


def test_repeated_shared_input_copies_remain_distinct_and_mutation_bound():
    shared = {'raw': b'source bytes', 'members': [True, 1]}
    original = [shared, shared]
    detached, commitment = owner._snapshot(original)
    assert detached[0] is not detached[1]
    assert detached[0]['members'] is not detached[1]['members']
    assert owner._snapshot(detached)[1] == commitment
    detached[1]['members'][0] = 1
    assert owner._snapshot(detached)[1] != commitment
    assert owner._snapshot(original)[1] == commitment
