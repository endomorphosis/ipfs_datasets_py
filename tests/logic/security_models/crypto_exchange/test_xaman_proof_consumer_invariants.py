import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_proof_consumer import (
    CLAIM_ID,
    PROOF_KERNEL_THEOREMS,
    REJECTED_OUTCOMES,
    REQUIRED_ASSUMPTIONS,
    REQUIRED_BINDINGS,
    SCHEMA_VERSION,
    TASK_ID,
    XamanProofConsumerError,
    build_xaman_proof_consumer_report,
    validate_xaman_proof_consumer_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
PROOF_KERNEL_DIR = CORPUS_DIR / 'proof-kernel'
LEAN_PATH = PROOF_KERNEL_DIR / 'XamanReceipt.lean'
REPORT_PATH = PROOF_KERNEL_DIR / 'proof-consumer-report.json'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
ENVIRONMENT_PROBE_PATH = CORPUS_DIR / 'environment-probe.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_proof_consumer_invariants.md'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }


def _expected_report() -> dict[str, Any]:
    return build_xaman_proof_consumer_report(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        environment_probe=_load_json(ENVIRONMENT_PROBE_PATH),
        lean_source=LEAN_PATH.read_text(encoding='utf-8'),
    )


def _accepted_packet() -> dict[str, Any]:
    return copy.deepcopy(_load_json(REPORT_PATH)['accepted_packet'])


def _rebuild_report(packet: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    report_payload = dict(packet['proof_report'])
    report_payload.update(overrides)
    report_payload.pop('deterministic_payload_cid', None)
    report_payload.pop('nondeterministic_report_cid', None)
    report = ProofReport.from_dict(report_payload)
    packet['proof_report'] = report.to_dict()
    packet['proof_receipt']['proof_report_cid'] = report.cid
    packet['proof_receipt']['metadata']['solver_identity'] = {
        'prover': report.prover,
        'solver_name': report.solver_name,
        'solver_version': report.solver_version,
        'solver_result': report.solver_result,
    }
    return packet


def _mark_first_evidence_unreviewed(packet: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = copy.deepcopy(packet['proof_report']['evidence_refs'])
    evidence_refs[0]['review_status'] = 'machine_extracted'
    return _rebuild_report(packet, evidence_refs=evidence_refs)


def test_xaman_proof_consumer_report_is_generated_from_current_inputs() -> None:
    checked_in = _load_json(REPORT_PATH)
    expected = _expected_report()

    assert checked_in == expected
    assert checked_in['schema_version'] == SCHEMA_VERSION
    assert checked_in['task_id'] == TASK_ID
    assert checked_in['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in)
    )
    assert checked_in['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert checked_in['claim_id'] == CLAIM_ID


def test_xaman_lean_kernel_declares_required_invariant_theorems() -> None:
    lean = LEAN_PATH.read_text(encoding='utf-8')

    assert 'def Accepts' in lean
    assert 'inductive Outcome' in lean
    assert 'disproved' in lean
    assert 'unknown' in lean
    assert 'notModeled' in lean
    assert 'missingSolver' in lean
    for theorem in PROOF_KERNEL_THEOREMS:
        assert f'theorem {theorem}' in lean


def test_xaman_proof_consumer_report_binds_receipt_report_and_context() -> None:
    report = _load_json(REPORT_PATH)
    packet = report['accepted_packet']
    proof_report = packet['proof_report']
    receipt = packet['proof_receipt']
    context = packet['context']

    verdict = validate_xaman_proof_consumer_packet(packet)

    assert verdict['accepted'] is True
    assert verdict['claim_id'] == CLAIM_ID
    assert verdict['model_cid'] == report['model_cid']
    assert receipt['model_cid'] == proof_report['model_cid'] == context['model_cid']
    assert receipt['claim_id'] == proof_report['claim_id'] == context['claim_id'] == CLAIM_ID
    assert receipt['proof_report_cid'] == proof_report['nondeterministic_report_cid']
    assert receipt['report_schema_version'] == proof_report['schema_version']
    assert receipt['accepted_assumptions'] == REQUIRED_ASSUMPTIONS
    assert proof_report['assumptions'] == REQUIRED_ASSUMPTIONS
    assert set(context['checked_bindings']) == set(REQUIRED_BINDINGS)
    assert report['proof_kernel_cid'] == context['proof_kernel']['artifact_cid']


def test_xaman_proof_consumer_binds_corpus_commit_and_fresh_environment_probe() -> None:
    packet = _accepted_packet()
    context = packet['context']
    receipt = packet['proof_receipt']
    environment = context['environment_probe']

    assert context['corpus']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert receipt['metadata']['corpus']['commit_sha'] == context['corpus']['commit_sha']
    assert receipt['metadata']['corpus']['manifest_aggregate_sha256'] == (
        context['corpus']['manifest_aggregate_sha256']
    )
    assert environment['generated_at_utc'] == '2026-07-08T20:29:12Z'
    assert environment['overall_status'] == 'ready'
    assert environment['proof_acceptance_blocked'] is False
    assert packet['proof_receipt']['metadata']['environment_probe']['generated_at_utc'] == (
        environment['generated_at_utc']
    )
    assert validate_xaman_proof_consumer_packet(packet)['accepted'] is True


def test_xaman_proof_consumer_requires_reviewed_source_evidence() -> None:
    packet = _accepted_packet()
    evidence_paths = {
        ref.get('path') or ref.get('artifact_path') or ref.get('document_path')
        for ref in packet['proof_report']['evidence_refs']
    }

    for path in packet['context']['required_evidence_paths']:
        assert path in evidence_paths
    assert all(
        ref['review_status'] in {'reviewed', 'human_reviewed'}
        for ref in packet['proof_report']['evidence_refs']
    )


def test_xaman_proof_consumer_rejected_fixtures_cover_required_outcomes() -> None:
    report = _load_json(REPORT_PATH)
    fixtures = report['rejected_fixtures']

    assert {entry['outcome'] for entry in fixtures} >= set(REJECTED_OUTCOMES)
    assert {entry['case_id'] for entry in fixtures} >= {
        'reject_disproved',
        'reject_unknown',
        'reject_not_modeled',
        'reject_missing_solver',
        'reject_stale_environment_probe',
        'reject_mismatched_report_cid',
        'reject_unaccepted_assumption',
    }
    assert all(entry['accepted'] is False for entry in fixtures)
    assert all(entry['rejection_reason'] for entry in fixtures)


@pytest.mark.parametrize(
    ('status', 'solver_result', 'message'),
    [
        ('DISPROVED', 'sat', 'report status DISPROVED is not accepted'),
        ('UNKNOWN', 'unknown', 'report status UNKNOWN is not accepted'),
        ('NOT_MODELED', 'not-modeled', 'report status NOT_MODELED is not accepted'),
    ],
)
def test_xaman_proof_consumer_rejects_non_secure_report_statuses(
    status: str,
    solver_result: str,
    message: str,
) -> None:
    packet = _rebuild_report(
        _accepted_packet(),
        status=status,
        solver_result=solver_result,
    )

    with pytest.raises(XamanProofConsumerError, match=message):
        validate_xaman_proof_consumer_packet(packet)


@pytest.mark.parametrize(
    ('mutator', 'message'),
    [
        (
            lambda packet: _rebuild_report(packet, model_cid='cid:wrong'),
            'model_cid',
        ),
        (
            lambda packet: _rebuild_report(packet, claim_id='claim:wrong'),
            'claim_id',
        ),
        (
            lambda packet: packet['proof_receipt'].__setitem__('proof_report_cid', 'sha256:wrong'),
            'proof_report_cid',
        ),
        (
            lambda packet: packet['proof_receipt'].__setitem__(
                'accepted_assumptions',
                [REQUIRED_ASSUMPTIONS[0]],
            ),
            'accepted assumptions',
        ),
        (
            lambda packet: packet['proof_receipt']['metadata']['solver_identity'].__setitem__(
                'solver_name',
                'coq',
            ),
            'solver identity',
        ),
        (
            lambda packet: packet['proof_receipt']['metadata']['corpus'].__setitem__(
                'commit_sha',
                '0000000000000000000000000000000000000000',
            ),
            'corpus commit',
        ),
        (
            _mark_first_evidence_unreviewed,
            'unreviewed evidence',
        ),
        (
            lambda packet: packet['context']['checked_bindings'].remove('fresh_environment_probe'),
            'missing checked binding',
        ),
    ],
)
def test_xaman_proof_consumer_rejects_broken_receipt_bindings(
    mutator: Any,
    message: str,
) -> None:
    packet = _accepted_packet()
    mutator(packet)

    with pytest.raises((ValueError, XamanProofConsumerError), match=message):
        validate_xaman_proof_consumer_packet(packet)


def test_xaman_proof_consumer_rejects_missing_solver_outcome() -> None:
    packet = _rebuild_report(
        _accepted_packet(),
        solver_name='lean4',
        solver_version='missing',
    )

    with pytest.raises(XamanProofConsumerError, match='solver lean4 is missing'):
        validate_xaman_proof_consumer_packet(packet)


def test_xaman_proof_consumer_rejects_stale_environment_probe() -> None:
    packet = _accepted_packet()
    packet['context']['environment_probe']['generated_at_utc'] = '2026-07-06T20:29:12Z'
    packet['proof_receipt']['metadata']['environment_probe']['generated_at_utc'] = (
        '2026-07-06T20:29:12Z'
    )

    with pytest.raises(XamanProofConsumerError, match='environment probe is stale'):
        validate_xaman_proof_consumer_packet(packet)


def test_xaman_proof_consumer_rejects_environment_probe_that_blocks_acceptance() -> None:
    packet = _accepted_packet()
    packet['context']['environment_probe']['proof_acceptance_blocked'] = True
    packet['proof_receipt']['metadata']['environment_probe']['proof_acceptance_blocked'] = True

    with pytest.raises(XamanProofConsumerError, match='environment probe blocks proof acceptance'):
        validate_xaman_proof_consumer_packet(packet)


def test_xaman_proof_consumer_documentation_names_artifacts_and_validation() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-073' in doc
    assert 'XamanReceipt.lean' in doc
    assert 'proof-consumer-report.json' in doc
    assert 'test_xaman_proof_consumer_invariants.py' in doc
    assert 'DISPROVED' in doc
    assert 'UNKNOWN' in doc
    assert 'NOT_MODELED' in doc
    assert 'missing solver' in doc
