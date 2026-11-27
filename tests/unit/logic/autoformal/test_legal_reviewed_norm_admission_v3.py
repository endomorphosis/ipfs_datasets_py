"""Source-complete fictional mixed admission through genuine existing owners."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from multiformats import CID, multihash

from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as legacy
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import corpus_source as sources
from ipfs_datasets_py.logic.syntax_core import ast, signatures
from tests.unit.logic.autoformal import test_legal_norm_content_adjudication_v1 as fixture
from tests.unit.logic.autoformal import test_legal_relational_norm_v1 as relational_fixture

ROOT = Path(__file__).resolve().parents[4]
CANONICAL_SOURCE = Path(legacy.__file__).resolve()
LEGACY_RAW = CANONICAL_SOURCE.read_bytes()
# Retained historical V2 epoch, not the identity of every later source revision.
# Current signed fixtures independently capture and pin LEGACY_RAW below.
V2_SOURCE_SHA256 = "1e4d8674851d03ee9b7e8f770a8925f22c50358375a934f42ec34d0d8ffef3d2"

auth, norm = fixture.auth, fixture.norm


def encode(value):
    if type(value) is bytes:
        return {'$fixture_bytes_base64': base64.b64encode(value).decode()}
    if type(value) is dict:
        return {key: encode(item) for key, item in value.items()}
    if type(value) is list:
        return [encode(item) for item in value]
    return value


def decode(value):
    if type(value) is dict:
        if set(value) == {'$fixture_bytes_base64'}:
            return base64.b64decode(value['$fixture_bytes_base64'], validate=True)
        return {key: decode(item) for key, item in value.items()}
    if type(value) is list:
        return [decode(item) for item in value]
    return value


def save(path, value):
    raw = json.dumps(encode(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def cloned(case):
    result = deepcopy({key: value for key, value in case.items() if key != 'signers'})
    result['signers'] = list(case['signers'])
    return result


@pytest.fixture(scope='module')
def v2_saved(tmp_path_factory):
    case = fixture.reviewed_norm_fixture_v2(legacy)
    report = fixture.assess_reviewed_fixture_v2(legacy, case)
    assert report['semantic_use_eligible'] and report['fixture_only']
    state = {key: value for key, value in case.items() if key != 'signers'}
    saved = {'case': state, 'assessment': report, 'canonical_owner_sha256': hashlib.sha256(LEGACY_RAW).hexdigest()}
    path = tmp_path_factory.mktemp('saved-reviewed-v2') / 'v2-before-sibling-load.json'
    save(path, saved)
    return case, path


@pytest.fixture(scope='module')
def sibling(v2_saved):
    # The V2 record is persisted before the normal sibling import.
    from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3
    assert CANONICAL_SOURCE.read_bytes() == LEGACY_RAW
    return legal_reviewed_norm_admission_v3


def mixed_request(*, covered_sort='Object'):
    builder = relational_fixture.Builder()
    obj, event, time = (signatures.LogicSort(name) for name in ('Object', 'EventFrame', 'TimeFrame'))
    sorts = {'Object': obj, 'EventFrame': event, 'TimeFrame': time}
    def atom(symbol, *args):
        return ast.mk_predicate(builder.nid(), symbol,
            [ast.mk_variable(builder.nid(), name, sort) for name, sort in args])
    category = sorts[covered_sort]
    first, second = (('officer', obj), ('supervisor', obj)) if covered_sort == 'Object' else (
        ('event', category), ('event', category))
    covered = ast.mk_and(builder.nid(), atom('CoveredOfficer', first), atom('CoveredOfficer', second))
    action = atom('InspectsRegisterAt', ('officer', obj), ('supervisor', obj), ('event', event), ('moment', time))
    root = ast.mk_implies(builder.nid(), covered, builder.modal('P', action))
    for name, sort in reversed((('officer', obj), ('supervisor', obj), ('event', event), ('moment', time))):
        root = ast.mk_forall(builder.nid(), [ast.Binder(name, sort)], root)
    signature = signatures.LogicSignature('fixture:complete-mixed-signature', family='tdfol', profile='tdfol_default',
        sorts=(obj, event, time), symbols=(signatures.declare_predicate('CoveredOfficer', (category,)),
            signatures.declare_predicate('InspectsRegisterAt', (obj, obj, event, time))))
    expression = ast.TypedExpression('fixture:complete-mixed-expression', root, signature)
    return {'schema': relational.MIXED_REQUEST_SCHEMA, 'profile': relational.MIXED_PROFILE,
        'interpretation_status': 'authored_unreviewed_declaration', 'expression': expression.to_dict(),
        'argument_roles': [{'symbol': 'CoveredOfficer', 'roles': ['officer']},
            {'symbol': 'InspectsRegisterAt', 'roles': ['officer', 'supervisor', 'event', 'moment']}],
        'source_binding': None}


def set_mixed_ir(case, *, covered_sort='Object'):
    unit = case['declaration']['units'][2]
    request = mixed_request(covered_sort=covered_sort)
    raw = fixture.wire(request)
    pin = fixture.sha(raw)
    report = relational.prepare_mixed_relational_norm_v1(raw, expected_request_sha256=pin)
    unit['relational_profile'] = relational.MIXED_PROFILE
    unit['relational_request_sha256'] = pin
    occurrence = unit['occurrence']
    unit['coverage'] = [{'typed_path': row['typed_path'], **{key: occurrence[key] for key in
        ('start_char', 'end_char', 'start_utf8', 'end_utf8')}} for row in report['structural_mapping']]
    case['relational_inputs'][unit['unit_id']] = {'request_raw': raw, 'report': report,
        'expected_report_sha256': relational.mixed_relational_norm_report_sha256(report)}
    paths = []
    for row in report['structural_mapping']:
        node = report['typed_expression']
        for token in row['typed_path'].split('/')[1:]:
            node = node[int(token)] if type(node) is list else node[token]
        if type(node) is dict and node.get('kind') == 'predicate' and node.get('symbol') == 'CoveredOfficer':
            paths.append(row['typed_path'])
    case['declaration']['definition_uses'][1]['target_typed_paths'] = paths
    assert len(paths) == 2


def prepare_args(case):
    return fixture.reviewed_prepare_arguments_v2(case)


def prepare(owner, case):
    fixture.reviewed_refresh_manifest_v2(case)
    return owner.prepare_reviewed_norm_admission_v3(case['declaration'], **prepare_args(case))


def refresh_signed_reviews(case, owner):
    subject = case['preparation']['subject']
    case['policy']['action'] = owner.REVIEWED_ACTION
    case['policy']['audience'] = owner.REVIEWED_AUDIENCE
    body_raw = norm._wire(case['declaration'])
    case['evidence'][case['declaration']['component_id']] = body_raw
    for claim in case['reviews']:
        claim.update(schema=owner.REVIEWED_CLAIM_SCHEMA, action=owner.REVIEWED_ACTION,
                     audience=owner.REVIEWED_AUDIENCE, subject=deepcopy(subject))
        claim['interpretation'].update(reviewed_graph_sha256=subject['graph_sha256'],
                                       reviewed_ast_sha256=subject['ast_sha256'])
        for obligation in claim['context_closure']['obligations']:
            obligation['evidence_refs'][0] = {'artifact_id': case['declaration']['component_id'],
                                            'sha256': fixture.sha(body_raw)}
    fixture.reviewed_resign_v2(case)


@pytest.fixture(scope='module')
def mixed_base(sibling, v2_saved):
    # Reuse the actual V2 fictional builder and its independent Ed25519 signers.
    texts = [
        'For this fictional Act, a covered officer means an officer appointed by the Board. Café.',
        'Every covered officer must file a report unless the Board expressly excuses that officer.',
        'For every officer, supervisor, event, and time, if both people are covered officers, that officer may inspect the register under that supervisor at that event and time.',
    ]
    case = fixture.reviewed_norm_fixture_v2(legacy, fixture_namespace='mixed-act-v1', source_texts=texts)
    case['declaration']['schema'] = sibling.REVIEWED_DECLARATION_SCHEMA
    for unit in case['declaration']['units']:
        unit['relational_profile'] = relational.PROFILE
    set_mixed_ir(case)
    case['preparation'] = prepare(sibling, case)
    refresh_signed_reviews(case, sibling)
    return case


@pytest.fixture
def mixed_case(mixed_base):
    return cloned(mixed_base)


def assess(owner, case, **overrides):
    args, kwargs = fixture.reviewed_assessment_arguments_v2(owner, case)
    return owner.assess_reviewed_norm_admission_v3(*args, **dict(kwargs, **overrides))


def assert_signatures_valid(case):
    keys = {key['key_id']: key for key in case['registry']['keys']}
    assert all(auth._verify_signature(claim, keys[claim['key_id']]) == 'valid' for claim in case['reviews'])
    # Independent verifier: rebuild the signed CID without the product signer.
    for claim in case['reviews']:
        body = {key: value for key, value in claim.items() if key != 'signature'}
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        cid = str(CID('base32', 1, 'dag-json', multihash.digest(raw, 'sha2-256')))
        key = keys[claim['key_id']]
        assert key['principal_id'] == claim['principal_id'] and key['signer_did'] == claim['signer_did']
        signature = base64.urlsafe_b64decode(claim['signature'] + '==')
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key['public_key_hex'])).verify(signature, cid.encode('ascii'))


def test_full_fictional_definition_object_use_and_mixed_use_replay(sibling, mixed_case, tmp_path):
    case = mixed_case
    before = norm._snapshot({key: value for key, value in case.items() if key != 'signers'})[1]
    report = assess(sibling, case)
    assert report['semantic_use_eligible'] and report['blockers'] == [] and report['fixture_only']
    assert [unit['relational_profile'] for unit in report['units']] == [
        relational.PROFILE, relational.PROFILE, relational.MIXED_PROFILE]
    assert_signatures_valid(case)
    reviews = report['review_authority']['reviews']
    assert len(reviews) == 2 and all(row['status'] == 'authenticated' and row['signature_status'] == 'valid' for row in reviews)
    assert len({row['principal_id'] for row in reviews}) == 2
    assert len({row['signer_did'] for row in case['reviews']}) == 2
    assert len({row['public_key_hex'] for row in case['registry']['keys']}) == 2
    assert not any(row['principal_id'] in {actor['principal_id'] for actor in case['declaration']['source_actors']}
                   for row in reviews)
    assert all(unit['source_text'] == case['declaration']['units'][index]['occurrence']['span_text']
               for index, unit in enumerate(report['units']))
    assert len(report['units'][2]['canonical_ir']['definition_uses'][0]['target_typed_paths']) == 2
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert all(report[key] is False for key in ('Lean_admitted', 'proof_authority', 'semantic_graph_admitted',
                                               'corpus_admitted', 'training_executed'))
    args, kwargs = fixture.reviewed_assessment_arguments_v2(sibling, case)
    assert sibling.validate_reviewed_norm_admission_v3(report, *args,
        expected_report_sha256=norm.norm_review_sha256(report), **kwargs) == report
    assert before == norm._snapshot({key: value for key, value in case.items() if key != 'signers'})[1]
    save(tmp_path / 'positive-mixed-case-and-report.json', {
        'case': {key: value for key, value in case.items() if key != 'signers'}, 'assessment': report})


def test_saved_v2_preparation_signatures_and_assessment_survive_sibling_load(sibling, v2_saved, tmp_path):
    saved = decode(json.loads(v2_saved[1].read_bytes()))
    case, original = saved['case'], saved['assessment']
    assert CANONICAL_SOURCE.read_bytes() == LEGACY_RAW
    assert str(Path(sibling.__file__).resolve()) not in case['preparation']['producer_pins']
    assert fixture.assess_reviewed_fixture_v2(legacy, case) == original
    args, kwargs = fixture.reviewed_assessment_arguments_v2(legacy, case)
    assert legacy.validate_reviewed_norm_admission_v2(original, *args,
        expected_report_sha256=norm.norm_review_sha256(original), **kwargs) == original
    assert legacy.prepare_reviewed_norm_admission_v2(case['declaration'], **prepare_args(case)) == case['preparation']
    assert_signatures_valid(case)
    save(tmp_path / 'saved-v2-replay-after-sibling-load.json', original)


@pytest.mark.parametrize('direction', ['v2-claims-in-v3', 'v3-claims-in-v2'])
def test_independently_valid_signatures_cannot_cross_domains(sibling, mixed_case, v2_saved, direction):
    v2 = cloned(v2_saved[0])
    assert_signatures_valid(v2)
    assert_signatures_valid(mixed_case)
    if direction == 'v2-claims-in-v3':
        mixed_case['reviews'] = deepcopy(v2['reviews'])
        with pytest.raises(ValueError, match='graph review signing domain differs'):
            assess(sibling, mixed_case)
    else:
        v2['reviews'] = deepcopy(mixed_case['reviews'])
        with pytest.raises(ValueError, match='graph review signing domain differs'):
            fixture.assess_reviewed_fixture_v2(legacy, v2)


@pytest.mark.parametrize('damage,reason', [
    ('typed-node-coverage', 'complete typed-node source correspondence required'),
    ('definition-use-target', 'complete ordered predicate definition-use targets required'),
    ('valid-mixed-sort-drift', 'governing predicate argument sorts differ'),
    ('overlapping-use', 'overlapping interpretations are not two distinct normative uses'),
])
def test_resealed_complete_transport_cannot_hide_semantic_contract_damage(sibling, mixed_case, damage, reason):
    case = mixed_case
    unit = case['declaration']['units'][2]
    if damage == 'typed-node-coverage':
        unit['coverage'].pop()
    elif damage == 'definition-use-target':
        case['declaration']['definition_uses'][1]['target_typed_paths'].pop()
    elif damage == 'valid-mixed-sort-drift':
        set_mixed_ir(case, covered_sort='EventFrame')
    else:
        first = case['declaration']['units'][1]
        original = deepcopy(case['source_inputs'][first['unit_id']])
        text, raw = original['extracted_text'], original['raw_bytes']
        version = sources.build_source_version(source_id=unit['unit_id'], release_id='fixture:mixed-act-v1',
            edition='fictional-edition-1', provision_id=unit['unit_id'], raw_bytes=raw,
            expected_raw_sha256=fixture.sha(raw), extracted_text=text, expected_extracted_sha256=fixture.sha(raw),
            extraction_profile='identity/v1', normalization_profile='identity/v1', media_type='text/plain')
        occurrence = sources.build_source_occurrence(version, expected_raw_sha256=fixture.sha(raw),
            extracted_text=text, expected_extracted_sha256=fixture.sha(raw), start_char=1, end_char=len(text)-1,
            start_utf8=1, end_utf8=len(raw)-1)
        unit.update(source_version=version, occurrence=occurrence)
        for row in unit['coverage']:
            row.update({key: occurrence[key] for key in ('start_char', 'end_char', 'start_utf8', 'end_utf8')})
        case['source_inputs'][unit['unit_id']] = original
        case['declaration']['definition_uses'][1]['use_occurrence_cid'] = occurrence['record_cid']
    fixture.reviewed_refresh_manifest_v2(case)
    with pytest.raises(ValueError, match=reason):
        sibling.prepare_reviewed_norm_admission_v3(case['declaration'], **prepare_args(case))


@pytest.mark.parametrize('damage,expected_reason', [
    ('stale-policy-signature', 'signed_policy_sha256_differs'),
    ('expired-policy', 'policy_not_current'),
    ('revoked-key', 'key_revoked'),
    ('revoked-principal', 'principal_revoked'),
])
def test_current_trust_controls_reject_even_genuine_signatures(sibling, mixed_case, damage, expected_reason, tmp_path):
    case = mixed_case
    if damage == 'stale-policy-signature':
        case['policy']['policy_id'] += ':fresh-version'
    elif damage == 'expired-policy':
        case['policy']['valid_until_utc'] = fixture.EVALUATED
        fixture.reviewed_resign_v2(case)
    elif damage == 'revoked-key':
        case['registry']['revocation_generation'] += 1
        case['registry']['keys'][0]['revoked_at_utc'] = fixture.EVALUATED
        fixture.reviewed_resign_v2(case)
    else:
        case['registry']['revocation_generation'] += 1
        case['registry']['revoked_principals'] = [{'principal_id': case['registry']['keys'][0]['principal_id'],
            'revoked_at_utc': fixture.EVALUATED}]
        fixture.reviewed_resign_v2(case)
    assert_signatures_valid(case)
    report = assess(sibling, case)
    assert report['semantic_use_eligible'] is False
    assert report['permitted_uses'] == [] and report['training_mask'] == report['evaluation_gold_mask'] == 0
    reasons = report['blockers'] + [reason for row in report['review_authority']['reviews'] for reason in row['blockers']]
    assert expected_reason in reasons
    save(tmp_path / (damage + '-rejection.json'), report)


def test_v3_sibling_preserves_v2_source_and_binds_current_producers(sibling, mixed_case, v2_saved):
    assert CANONICAL_SOURCE.read_bytes() == LEGACY_RAW
    saved = decode(json.loads(v2_saved[1].read_bytes()))
    current_pin = hashlib.sha256(LEGACY_RAW).hexdigest()
    assert saved['canonical_owner_sha256'] == current_pin
    assert saved['case']['preparation']['producer_pins'][str(CANONICAL_SOURCE)] == current_pin
    assert v2_saved[0]['preparation']['producer_pins'][str(CANONICAL_SOURCE)] == current_pin
    expected = ROOT / 'ipfs_datasets_py/logic/autoformal/legal_reviewed_norm_admission_v3.py'
    assert Path(sibling.__file__).resolve() == expected
    assert sibling.__name__ == 'ipfs_datasets_py.logic.autoformal.legal_reviewed_norm_admission_v3'
    assert str(expected) not in v2_saved[0]['preparation']['producer_pins']
    assert mixed_case['preparation']['producer_pins'][str(expected)] == hashlib.sha256(expected.read_bytes()).hexdigest()
    for path, expected in mixed_case['preparation']['producer_pins'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected


def test_governing_definition_rejects_implication_instead_of_complete_equivalence(sibling, mixed_case):
    """An exact rehashed transport cannot weaken a governing definition to one direction."""
    case = mixed_case
    unit = case['declaration']['units'][0]
    assert unit['kind'] == 'definition' and unit['relational_profile'] == relational.PROFILE
    request = json.loads(case['relational_inputs'][unit['unit_id']]['request_raw'])
    root = request['expression']['root']
    while root['kind'] == 'forall':
        root = root['arguments'][0]
    assert root['kind'] == 'iff' and root['arguments'][0]['kind'] == 'predicate'
    root['kind'] = 'implies'
    request['expression'] = ast.TypedExpression.from_dict(
        dict(request['expression'], content_digest='')).to_dict()
    raw = fixture.wire(request)
    report = relational.prepare_relational_norm_v1(raw, expected_request_sha256=fixture.sha(raw))
    unit['relational_request_sha256'] = fixture.sha(raw)
    occurrence = unit['occurrence']
    unit['coverage'] = [{'typed_path': row['typed_path'], **{key: occurrence[key] for key in
        ('start_char', 'end_char', 'start_utf8', 'end_utf8')}} for row in report['structural_mapping']]
    case['relational_inputs'][unit['unit_id']] = {'request_raw': raw, 'report': report,
        'expected_report_sha256': relational.relational_norm_report_sha256(report)}
    fixture.reviewed_refresh_manifest_v2(case)
    with pytest.raises(ValueError, match='supported definition must universally bind a predicate equivalence'):
        sibling.prepare_reviewed_norm_admission_v3(case['declaration'], **prepare_args(case))


@pytest.mark.parametrize('mutation,reason', [
    ('duplicate_repackage', 'logical source occurrence'),
    ('overlapping_repackage', 'overlapping logical source'),
    ('document_revision_label', 'logical source occurrence'),
    ('different_unaligned_view', 'unsupported source-view alignment'),
    ('different_view_and_document_revision_label', 'unsupported source-view alignment'),
    ('physical_alias', 'physical occurrence'),
])
def test_reviewed_v3_raw_repackaging_and_artifact_labels_do_not_create_legal_uses(sibling, mixed_case, mutation, reason):
    case = mixed_case
    original, alternate = fixture.reviewed_repeated_permission_source_v2(case, mutation)
    if mutation != 'physical_alias':
        assert original['source_version']['raw_artifact']['sha256'] != alternate['source_version']['raw_artifact']['sha256']
    fixture.reviewed_refresh_manifest_v2(case)
    with pytest.raises(ValueError, match=reason):
        sibling.prepare_reviewed_norm_admission_v3(case['declaration'], **prepare_args(case))
    with pytest.raises(ValueError, match=reason):
        assess(sibling, case)


@pytest.mark.parametrize('mutation', ['different_provision', 'different_release', 'different_edition', 'nonoverlapping_paragraphs', 'nonoverlapping_paragraphs_different_source_id'])
def test_reviewed_v3_distinct_legal_identities_and_nonoverlapping_uses_survive(sibling, mixed_case, mutation):
    case = mixed_case
    original, alternate = fixture.reviewed_repeated_permission_source_v2(case, mutation)
    if mutation == 'nonoverlapping_paragraphs_different_source_id':
        first, second = original['source_version'], alternate['source_version']
        assert first['raw_artifact']['sha256'] == second['raw_artifact']['sha256']
        assert first['extracted_view']['sha256'] == second['extracted_view']['sha256']
        assert first['source_id'] != second['source_id'] == alternate['unit_id']
        assert all(first[field] == second[field] for field in ('release_id', 'edition', 'provision_id'))
        assert original['occurrence']['end_char'] < alternate['occurrence']['start_char']
        assert original['occurrence']['end_utf8'] < alternate['occurrence']['start_utf8']
    case['preparation'] = prepare(sibling, case)
    refresh_signed_reviews(case, sibling)
    assert_signatures_valid(case)
    report = assess(sibling, case)
    assert report['semantic_use_eligible'] is True and report['blockers'] == []
    assert report['fixture_only'] and report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert report['Lean_admitted'] is report['proof_authority'] is report['corpus_admitted'] is False
    assert len({row['occurrence_cid'] for row in report['units'] if row['kind'] == 'norm'}) == 2
    assert original['occurrence']['span_text'] == alternate['occurrence']['span_text']


def test_old_generation_source_pin_cannot_be_rehashed_into_current_v2_preparation(sibling, v2_saved):
    case = cloned(v2_saved[0])
    source_key = str(CANONICAL_SOURCE)
    assert case['preparation']['producer_pins'][source_key] != V2_SOURCE_SHA256
    case['preparation']['producer_pins'][source_key] = V2_SOURCE_SHA256
    # The expected preparation digest is freshly computed by this fixture
    # helper. A matching outer hash does not make a historical producer current.
    args, kwargs = fixture.reviewed_assessment_arguments_v2(legacy, case)
    with pytest.raises(ValueError, match='complete original replay'):
        legacy.assess_reviewed_norm_admission_v2(*args, **kwargs)


def test_reviewed_v3_alternate_view_of_same_raw_paragraph_requires_distinct_use_witness(sibling, mixed_case):
    # Preparation-only fictional counterexample: no modified signed reviews
    # are submitted to an assessor, and no statutory meaning is asserted.
    case = mixed_case
    original, relabeled = case["declaration"]["units"][1:]
    assert original["kind"] == relabeled["kind"] == "norm"
    source_input = deepcopy(case["source_inputs"][original["unit_id"]])
    raw, first_view = source_input["raw_bytes"], source_input["extracted_text"]
    first_version, first_occurrence = original["source_version"], original["occurrence"]
    second_view = "\n" + first_view
    raw_sha = fixture.sha(raw)
    second_view_sha = fixture.sha(second_view.encode("utf-8"))
    assert first_version["raw_artifact"]["sha256"] == raw_sha
    assert second_view_sha != first_version["extracted_view"]["sha256"]
    version = sources.build_source_version(
        source_id=relabeled["unit_id"], release_id=first_version["release_id"],
        edition=first_version["edition"], provision_id=first_version["provision_id"],
        raw_bytes=raw, expected_raw_sha256=raw_sha,
        extracted_text=second_view, expected_extracted_sha256=second_view_sha,
        extraction_profile="fixture-leading-newline-derived-view/v1",
        normalization_profile="preserved-paragraph-leading-newline/v1", media_type="text/plain")
    occurrence = sources.build_source_occurrence(
        version, expected_raw_sha256=raw_sha, extracted_text=second_view,
        expected_extracted_sha256=second_view_sha,
        start_char=first_occurrence["start_char"] + 1,
        end_char=first_occurrence["end_char"] + 1,
        start_utf8=first_occurrence["start_utf8"] + 1,
        end_utf8=first_occurrence["end_utf8"] + 1)
    assert sources.validate_source_version(version, expected_raw_sha256=raw_sha,
        raw_bytes=raw, extracted_text=second_view,
        expected_extracted_sha256=second_view_sha) == version
    assert sources.validate_source_occurrence(occurrence, source_version=version,
        expected_raw_sha256=raw_sha, extracted_text=second_view,
        expected_extracted_sha256=second_view_sha) == occurrence
    assert version["raw_artifact"] == first_version["raw_artifact"]
    assert occurrence["span_text"] == first_occurrence["span_text"]
    assert occurrence["span_sha256"] == first_occurrence["span_sha256"]
    assert occurrence["record_cid"] != first_occurrence["record_cid"]
    relabeled.update(source_version=version, occurrence=occurrence,
        document_revision=original["document_revision"])
    case["source_inputs"][relabeled["unit_id"]] = {
        "raw_bytes": raw, "extracted_text": second_view}
    for coverage in relabeled["coverage"]:
        coverage.update({key: occurrence[key] for key in
            ("start_char", "end_char", "start_utf8", "end_utf8")})
    use = next(row for row in case["declaration"]["definition_uses"]
               if row["use_unit_id"] == relabeled["unit_id"])
    use["use_occurrence_cid"] = occurrence["record_cid"]
    fixture.reviewed_refresh_manifest_v2(case)
    assert len(case["declaration"]["units"]) == 3
    assert len(case["declaration"]["definition_uses"]) == 2
    # Different view coordinates cannot establish a second operative physical
    # use. This declaration supplies no common physical-coordinate witness.
    with pytest.raises(ValueError, match=r"same raw|cross.view|physical.*(witness|coordinate)|distinct.*(use|view)"):
        sibling.prepare_reviewed_norm_admission_v3(
            case["declaration"], **prepare_args(case))


@pytest.mark.parametrize("parent_edges", [
    ((1, 2), (2, 1)),
    ((0, 1),),
    ((0, 2), (2, 1)),
], ids=["parent-cycle", "parent-definition-cycle", "longer-mixed-cycle"])
def test_reviewed_v3_refuses_cyclic_unit_dependencies(sibling, mixed_case, parent_edges):
    units = mixed_case["declaration"]["units"]
    assert [unit["kind"] for unit in units] == ["definition", "norm", "norm"]
    for child, parent in parent_edges:
        units[child]["parent_unit_ids"].append(units[parent]["unit_id"])
    fixture.reviewed_refresh_manifest_v2(mixed_case)
    kwargs = prepare_args(mixed_case)
    # The artifact closure alone does not represent the cycle in legal units.
    assert kwargs["dependency_manifest"]["cycles"] == []
    with pytest.raises(ValueError, match="cyclic or unresolved reviewed governing dependency"):
        sibling.prepare_reviewed_norm_admission_v3(mixed_case["declaration"], **kwargs)


def test_reviewed_v3_preserves_acyclic_overlapping_unit_dependencies(sibling, mixed_case):
    declaration = mixed_case["declaration"]
    definition, first, second = declaration["units"]
    first["parent_unit_ids"] = [definition["unit_id"]]
    second["parent_unit_ids"] = [first["unit_id"], definition["unit_id"]]
    assert [use["definition_unit_id"] for use in declaration["definition_uses"]] == [
        definition["unit_id"], definition["unit_id"],
    ]
    report = prepare(sibling, mixed_case)
    assert report["declaration"]["units"] == declaration["units"]
    assert report["semantic_use_eligible"] is report["Lean_admitted"] is report["proof_authority"] is False


@pytest.mark.parametrize("versions, shared_id", [
    (("fictional-crosswalk/v1", "fictional-crosswalk/v2"), True),
    (("fictional-crosswalk/v2", "fictional-crosswalk/v1"), True),
    (("fictional-crosswalk/v1", "fictional-crosswalk/v1"), True),
    (("fictional-crosswalk/v1", "fictional-crosswalk/v2"), False),
], ids=["shared-forward-conflict", "shared-reverse-conflict", "shared-equal", "distinct-identities"])
def test_reviewed_v3_cross_reference_version_consistency(sibling, mixed_case, versions, shared_id):
    case = mixed_case
    declaration = case["declaration"]
    artifact_ids = (
        "fixture:crosswalk-a", "fixture:crosswalk-a" if shared_id else "fixture:crosswalk-b",
    )
    dependency = b"Identical fictional crosswalk bytes"
    dependency_sha = fixture.sha(dependency)
    process = {
        "artifact_id": fixture.REVIEWED_PROCESS_ID,
        "sha256": fixture.sha(case["evidence"][fixture.REVIEWED_PROCESS_ID]),
    }
    references = [
        {"from_unit_id": unit["unit_id"], "dependency_artifact_id": identity,
         "dependency_sha256": dependency_sha, "version": version,
         "evidence_refs": [deepcopy(process)]}
        for unit, identity, version in zip(declaration["units"][1:], artifact_ids, versions, strict=True)
    ]
    declaration["cross_references"] = references
    for identity in set(artifact_ids):
        case["evidence"][identity] = dependency
    fixture.reviewed_refresh_manifest_v2(case)
    artifacts = case["manifest"]["artifacts"]
    assert {row["artifact_id"]: row["artifact_sha256"] for row in artifacts
            if row["artifact_id"] in artifact_ids} == dict.fromkeys(artifact_ids, dependency_sha)
    assert case["manifest"]["cycles"] == []
    conflict = shared_id and versions[0] != versions[1]
    try:
        case["preparation"] = sibling.prepare_reviewed_norm_admission_v3(
            declaration, **prepare_args(case))
    except ValueError as error:
        if not conflict:
            raise
        assert "conflicting dependency versions" in str(error)
        return

    refresh_signed_reviews(case, sibling)
    assert_signatures_valid(case)
    report = assess(sibling, case)
    assert report["semantic_use_eligible"] and report["blockers"] == []
    assert report["fixture_only"] and report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert [unit["canonical_ir"]["cross_references"][0] for unit in report["units"][1:]] == references
    assert not conflict, "contradictory dependency version labels became eligible in a freshly signed V3 review"


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "nested"])
def test_reviewed_v3_refuses_governing_definition_reusing_its_predicate(sibling, mixed_case, nested):
    unit = mixed_case["declaration"]["units"][0]
    assert unit["kind"] == "definition" and unit["relational_profile"] == relational.PROFILE
    request = json.loads(mixed_case["relational_inputs"][unit["unit_id"]]["request_raw"])
    equivalence = request["expression"]["root"]
    while equivalence["kind"] == "forall":
        equivalence = equivalence["arguments"][0]
    predicate, original_rhs = equivalence["arguments"]
    assert equivalence["kind"] == "iff" and predicate["symbol"] == "CoveredOfficer"
    repeated_predicate = deepcopy(predicate)
    repeated_predicate["node_id"] += ":recursive-fixture"
    for argument in repeated_predicate["arguments"]:
        argument["node_id"] += ":recursive-fixture"
    revised_rhs = ast.LogicNode.from_dict(repeated_predicate)
    if nested:
        revised_rhs = ast.mk_and("fixture:recursive-definition-and",
                                 ast.LogicNode.from_dict(original_rhs), revised_rhs)
    else:
        # The direct tautology has no use for the former RHS declaration.
        request["expression"]["signature"]["symbols"] = [
            declaration for declaration in request["expression"]["signature"]["symbols"]
            if declaration["name"] != original_rhs["symbol"]
        ]
        request["argument_roles"] = [
            row for row in request["argument_roles"] if row["symbol"] != original_rhs["symbol"]
        ]
    equivalence["arguments"][1] = revised_rhs.to_dict()
    request["expression"] = ast.TypedExpression.from_dict(
        dict(request["expression"], content_digest="")).to_dict()
    raw = fixture.wire(request)
    pin = fixture.sha(raw)
    report = relational.prepare_relational_norm_v1(raw, expected_request_sha256=pin)
    unit["relational_request_sha256"] = pin
    occurrence = unit["occurrence"]
    unit["coverage"] = [{"typed_path": row["typed_path"], **{key: occurrence[key] for key in
        ("start_char", "end_char", "start_utf8", "end_utf8")}} for row in report["structural_mapping"]]
    mixed_case["relational_inputs"][unit["unit_id"]] = {
        "request_raw": raw, "report": report,
        "expected_report_sha256": relational.relational_norm_report_sha256(report),
    }
    fixture.reviewed_refresh_manifest_v2(mixed_case)
    kwargs = prepare_args(mixed_case)
    assert kwargs["dependency_manifest"]["cycles"] == []
    with pytest.raises(ValueError, match="cyclic or unresolved reviewed governing dependency"):
        sibling.prepare_reviewed_norm_admission_v3(mixed_case["declaration"], **kwargs)
