from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import ProofReceipt
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport


def test_proof_report_and_receipt_round_trip() -> None:
    model = example_minimal_exchange_model()
    report = ProofReport(
        claim_id='claim:test',
        model_cid=calculate_model_cid(model),
        status='PROVED',
        prover='z3',
        proof_or_trace_cid='cid:proof',
        assumptions=['A4'],
        compiler_cid='cid:compiler',
        counterexample=None,
        risk='blocking',
        signatures=[],
        created_at='2026-07-05T00:00:00+00:00',
    )
    restored = ProofReport.from_dict(report.to_dict())
    receipt = ProofReceipt.from_report(restored, verifier='ts-wasm-kernel', verifier_version='0.1.0', valid=True)
    assert restored.to_dict() == report.to_dict()
    assert receipt.proof_report_cid == report.cid
    assert receipt.valid is True
