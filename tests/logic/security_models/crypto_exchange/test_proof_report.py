import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import ProofReceipt, validate_proof_receipt
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import (
    PROOF_REPORT_SCHEMA_VERSION,
    PROOF_STATUS_DISPROVED,
    PROOF_STATUS_PROVED,
    PROOF_STATUS_UNKNOWN,
    ProofReport,
    validate_proof_report,
)


def _report(**overrides) -> ProofReport:
    model = example_minimal_exchange_model()
    payload = dict(
        claim_id='claim:test',
        claim_version='1.0',
        model_cid=calculate_model_cid(model),
        model_schema_version=model.schema_version,
        status=PROOF_STATUS_PROVED,
        prover='z3',
        solver_name='z3',
        solver_version='4.16.0',
        solver_result='unsat',
        proof_or_trace_cid='cid:proof',
        assumptions=['A4'],
        compiler_cid='cid:compiler',
        counterexample=None,
        risk='blocking',
        signatures=[],
        generated_at='2026-07-05T00:00:00+00:00',
        evidence_refs=[],
        soundness_notes=[],
    )
    payload.update(overrides)
    return ProofReport(**payload)


def test_proof_report_round_trip_and_deterministic_payload_cid() -> None:
    report = _report(generated_at='2026-07-05T00:00:00+00:00')
    same_payload_other_timestamp = _report(generated_at='2026-07-05T00:00:30+00:00')
    restored = ProofReport.from_untrusted_dict(report.to_dict())
    assert restored.to_dict() == report.to_dict()
    assert validate_proof_report(restored) is restored
    assert report.verify_report_cids() is True
    assert report.deterministic_payload_cid == same_payload_other_timestamp.deterministic_payload_cid
    assert report.cid != same_payload_other_timestamp.cid



def test_deterministic_payload_excludes_signatures() -> None:
    unsigned = _report(signatures=[])
    signed = _report(signatures=[{'key_id': 'k1', 'signature': 'abc'}])
    assert 'signatures' not in unsigned.deterministic_payload()
    assert 'signatures' in signed.nondeterministic_payload()
    assert unsigned.deterministic_payload_cid == signed.deterministic_payload_cid
    assert unsigned.nondeterministic_report_cid != signed.nondeterministic_report_cid


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('deterministic_payload_cid', 'cid:tampered', 'deterministic_payload_cid does not match'),
        ('nondeterministic_report_cid', 'cid:tampered', 'nondeterministic_report_cid does not match'),
    ],
)
def test_proof_report_from_dict_rejects_tampered_cids(field: str, value: str, message: str) -> None:
    payload = _report(generated_at='2026-07-05T00:00:00+00:00').to_dict()
    payload[field] = value
    with pytest.raises(ValueError, match=message):
        ProofReport.from_untrusted_dict(payload)


def test_proof_report_from_untrusted_dict_rejects_unknown_fields() -> None:
    payload = _report().to_dict()
    payload['unknown_field'] = True
    with pytest.raises(ValueError, match='Unknown proof report field'):
        ProofReport.from_untrusted_dict(payload)


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('status', 'MAYBE', 'unsupported proof status'),
        ('risk', 'critical', 'unsupported proof risk'),
    ],
)
def test_validate_proof_report_rejects_unknown_status_and_risk(field: str, value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _report(**{field: value})


def test_validate_proof_report_detects_cid_integrity_failures_unless_disabled() -> None:
    report = _report()
    report.signatures.append({'key_id': 'k1', 'signature': 'abc'})
    with pytest.raises(ValueError, match='CID integrity check failed'):
        validate_proof_report(report)
    assert validate_proof_report(report, verify_cids=False) is report
    assert report.recompute_deterministic_payload_cid() == report.deterministic_payload_cid
    assert report.recompute_nondeterministic_report_cid() != report.nondeterministic_report_cid



def test_proof_receipt_rejects_missing_explicit_assumptions_by_default() -> None:
    with pytest.raises(ValueError, match='accepted_assumptions must be provided explicitly'):
        ProofReceipt.from_report(
            _report(),
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
        )


def test_proof_receipt_allows_unsafe_report_assumptions_only_when_requested() -> None:
    receipt = ProofReceipt.from_report(
        _report(),
        verifier='ts-wasm-kernel',
        verifier_version='0.1.0',
        allow_report_assumptions=True,
    )
    assert receipt.accepted_assumptions == ['A4']
    assert receipt.metadata['unsafe_assumption_source'] == 'report'


def test_proof_receipt_rejects_unaccepted_assumption() -> None:
    report = _report(assumptions=['A4', 'A5'])
    with pytest.raises(ValueError, match='not accepted'):
        ProofReceipt.from_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=['A4'],
        )


@pytest.mark.parametrize('status', [PROOF_STATUS_UNKNOWN, PROOF_STATUS_DISPROVED])
def test_proof_receipt_rejects_non_secure_statuses(status: str) -> None:
    report = _report(status=status, solver_result='unknown' if status == PROOF_STATUS_UNKNOWN else 'sat')
    with pytest.raises(ValueError, match='not accepted as secure'):
        ProofReceipt.from_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=['A4'],
        )


def test_proof_receipt_rejects_unsupported_report_schema() -> None:
    report = _report(schema_version='proof-report/v999')
    with pytest.raises(ValueError, match='unsupported proof report schema version'):
        ProofReceipt.from_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=['A4'],
            supported_schema_versions=(PROOF_REPORT_SCHEMA_VERSION,),
        )


def test_proof_receipt_rejects_wrong_expected_model_cid() -> None:
    report = _report()
    with pytest.raises(ValueError, match='model_cid does not match report.model_cid'):
        ProofReceipt.validate_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=['A4'],
            expected_model_cid='cid:wrong',
        )


def test_proof_receipt_rejects_wrong_expected_claim_id() -> None:
    report = _report()
    with pytest.raises(ValueError, match='claim_id does not match report.claim_id'):
        ProofReceipt.validate_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=['A4'],
            expected_claim_id='claim:wrong',
        )


def test_proof_receipt_accepts_valid_proved_report() -> None:
    report = _report()
    receipt = ProofReceipt.from_report(
        report,
        verifier='ts-wasm-kernel',
        verifier_version='0.1.0',
        accepted_assumptions=['A4'],
    )
    assert validate_proof_receipt(receipt) is receipt
    assert receipt.proof_report_cid == report.cid
    assert receipt.valid is True
