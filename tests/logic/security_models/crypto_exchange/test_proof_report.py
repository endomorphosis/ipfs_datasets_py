import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import ProofReceipt
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport



def _report(**overrides) -> ProofReport:
    model = example_minimal_exchange_model()
    payload = dict(
        claim_id='claim:test',
        claim_version='1.0',
        model_cid=calculate_model_cid(model),
        model_schema_version=model.schema_version,
        status='PROVED',
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
    restored = ProofReport.from_dict(report.to_dict())
    assert restored.to_dict() == report.to_dict()
    assert report.deterministic_payload_cid == same_payload_other_timestamp.deterministic_payload_cid
    assert report.cid != same_payload_other_timestamp.cid



def test_proof_receipt_rejects_unaccepted_assumption() -> None:
    report = _report(assumptions=['A4', 'A5'])
    with pytest.raises(ValueError, match='not accepted'):
        ProofReceipt.from_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=['A4'],
        )



def test_proof_receipt_rejects_unknown_as_secure() -> None:
    report = _report(status='UNKNOWN', solver_result='unknown', reason_unknown='timeout')
    with pytest.raises(ValueError, match='not accepted as secure'):
        ProofReceipt.from_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
        )



def test_proof_receipt_accepts_valid_proved_report() -> None:
    report = _report()
    receipt = ProofReceipt.from_report(
        report,
        verifier='ts-wasm-kernel',
        verifier_version='0.1.0',
        accepted_assumptions=['A4'],
    )
    assert receipt.proof_report_cid == report.cid
    assert receipt.valid is True
