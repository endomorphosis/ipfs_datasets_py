import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import TypeScriptSchemaEmitter
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import canonicalize_ir
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import SecurityModelIR, validate_ir
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import ProofReceipt, validate_proof_receipt
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport, validate_proof_report
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


pytest.importorskip('z3')



def _accepted_assumptions(model: SecurityModelIR) -> list[str]:
    return [item if isinstance(item, str) else item['id'] for item in model.assumptions]



def _report_with_status(report: ProofReport, status: str, solver_result: str) -> ProofReport:
    payload = report.to_dict()
    payload['status'] = status
    payload['solver_result'] = solver_result
    payload.pop('deterministic_payload_cid', None)
    payload.pop('nondeterministic_report_cid', None)
    return ProofReport.from_dict(payload)



def test_security_artifact_e2e_trusted_fixture() -> None:
    model = example_minimal_exchange_model()
    strict_model = SecurityModelIR.from_untrusted_dict(model.to_dict(), strict=True)
    validated = validate_ir(strict_model)
    canonical = canonicalize_ir(validated)
    model_cid = calculate_model_cid(validated)

    assert canonical
    assert model_cid

    runner = Z3Runner()
    reports = [runner.run_claim(claim, validated) for claim in default_claims()]

    assert [report.claim_id for report in reports] == [claim.claim_id for claim in default_claims()]
    assert all(report.status == 'PROVED' for report in reports)
    assert all(not (report.risk == 'blocking' and report.status == 'DISPROVED') for report in reports)
    assert all(not (report.risk == 'blocking' and report.status == 'UNKNOWN') for report in reports)
    assert all(report.status == 'PROVED' for report in reports if report.risk == 'blocking')

    accepted_assumptions = _accepted_assumptions(validated)
    receipts = []
    for report in reports:
        assert report.model_cid == model_cid
        assert report.verify_report_cids() is True
        assert validate_proof_report(report) is report
        receipt = ProofReceipt.from_report(
            report,
            verifier='ts-wasm-kernel',
            verifier_version='0.1.0',
            accepted_assumptions=accepted_assumptions,
        )
        assert validate_proof_receipt(receipt) is receipt
        assert receipt.valid is True
        receipts.append(receipt)

    assert len(receipts) == len(reports)

    emitted_schema = TypeScriptSchemaEmitter().emit_schema(validated)
    assert 'export interface ProofReport {' in emitted_schema
    assert 'export function verifyProofReceipt' in emitted_schema

    secure_report = reports[0]
    unknown_report = _report_with_status(secure_report, 'UNKNOWN', 'unknown')
    disproved_report = _report_with_status(secure_report, 'DISPROVED', 'sat')
    not_modeled_report = _report_with_status(secure_report, 'NOT_MODELED', 'not-modeled')

    for report in (unknown_report, disproved_report, not_modeled_report):
        with pytest.raises(ValueError, match='not accepted as secure'):
            ProofReceipt.from_report(
                report,
                verifier='ts-wasm-kernel',
                verifier_version='0.1.0',
                accepted_assumptions=accepted_assumptions,
            )
