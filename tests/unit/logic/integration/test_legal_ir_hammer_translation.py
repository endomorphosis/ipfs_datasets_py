"""Tests for typed Legal IR hammer translation and reconstruction receipts."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerLogicTranslator,
    HammerPipeline,
    HammerPremise,
    HammerStatus,
    HammerVerification,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LegalIRHammerConfig,
    run_legal_ir_hammer,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    HammerReconstructionOutcome,
    HammerReconstructionReceipt,
    HammerTranslationDecisionStatus,
    HammerTranslationRecord,
    HammerTranslationSurface,
    HammerTrustStatus,
    reconstruction_receipt_from_hammer_result,
    translation_records_from_hammer_result,
)


def _backend(name: str, problem_format: str, *, proved: bool = True):
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend=name,
            status=(HammerBackendStatus.PROVED if proved else HammerBackendStatus.UNKNOWN),
            proved=proved,
            elapsed_seconds=min(timeout_seconds, 0.01),
            translation_format=translation.target_format,
            proof_trace="proof" if proved else "",
            raw_output="proof" if proved else "unknown",
        )

    return CallableHammerBackendRunner(name, problem_format, _run)


def _goal() -> HammerGoal:
    return HammerGoal(
        "typed_notice_obligation(f1)",
        name="lir-obligation-typed",
        itp_system="lean",
        metadata={
            "formula_id": "f1",
            "itp_statement": "True",
            "lean_imports": "",
            "obligation_id": "lir-obligation-typed",
        },
    )


def test_records_smt_tptp_and_lean_surfaces_with_typed_decisions() -> None:
    result = HammerPipeline(
        backends=[
            _backend("z3", "smt-lib"),
            _backend("vampire", "tptp-fof", proved=False),
        ],
        max_premises=4,
        parallel_workers=1,
    ).prove(_goal(), [HammerPremise("typed_notice", "typed_notice_obligation(f1)")])

    records = translation_records_from_hammer_result(result)

    assert result.status == HammerStatus.PROVED
    assert [record.surface for record in records] == [
        HammerTranslationSurface.SMT_LIB,
        HammerTranslationSurface.TPTP,
        HammerTranslationSurface.LEAN,
    ]
    for record in records[:2]:
        assert record.schema_version == LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION
        assert record.artifact_size_bytes > 0
        assert len(record.artifact_sha256) == 64
        assert record.monomorphization.status == HammerTranslationDecisionStatus.APPLIED
        assert record.type_encoding.applied is True
        assert record.lambda_elimination.applied is True
        assert set(record.decisions) == {
            "lambda_elimination",
            "monomorphization",
            "type_encoding",
        }

    lean_record = records[-1]
    assert lean_record.target_format == "lean"
    assert lean_record.metadata["reconstruction_status"] == "script_generated"
    assert all(
        decision.status == HammerTranslationDecisionStatus.NOT_APPLICABLE
        for decision in lean_record.transformation_decisions
    )
    assert HammerTranslationRecord.from_dict(lean_record.to_dict()) == lean_record


def test_explicit_translation_decisions_override_legacy_transformations() -> None:
    class _DecisionTranslator(HammerLogicTranslator):
        def translate(self, goal, premises, *, target_format):
            translation = super().translate(goal, premises, target_format=target_format)
            translation.metadata["translation_decisions"] = {
                "monomorphization": {
                    "applied": False,
                    "rationale": "input_was_already_monomorphic",
                    "strategy": "none",
                },
                "type_encoding": {
                    "status": "applied",
                    "rationale": "tagged_sort_encoding",
                    "strategy": "tags",
                },
                "lambda_elimination": "not_applied",
            }
            return translation

    pipeline = HammerPipeline(
        translator=_DecisionTranslator(),
        backends=[_backend("z3", "smt-lib")],
        parallel_workers=1,
    )
    result = pipeline.prove(_goal(), [HammerPremise("p", "P")])
    record = translation_records_from_hammer_result(result)[0]

    assert record.monomorphization.status == HammerTranslationDecisionStatus.NOT_APPLIED
    assert record.monomorphization.rationale == "input_was_already_monomorphic"
    assert record.monomorphization.details == {"strategy": "none"}
    assert record.type_encoding.details == {"strategy": "tags"}
    assert record.lambda_elimination.status == HammerTranslationDecisionStatus.NOT_APPLIED


def test_receipt_separates_backend_proof_from_unverified_native_script_and_trust() -> None:
    result = HammerPipeline(
        backends=[_backend("z3", "smt-lib")],
        parallel_workers=1,
    ).prove(_goal(), [HammerPremise("p", "P")])
    records = translation_records_from_hammer_result(result)

    receipt = reconstruction_receipt_from_hammer_result(
        result,
        translation_records=records,
        trusted_requires_reconstruction=True,
    )

    assert receipt.outcome == HammerReconstructionOutcome.BACKEND_PROOF
    assert receipt.backend_proved is True
    assert receipt.native_reconstruction is True
    assert receipt.native_reconstruction_verified is False
    assert receipt.trusted is False
    assert receipt.trust_status == HammerTrustStatus.UNTRUSTED
    assert receipt.trust_reason == "native_reconstruction_required"
    assert receipt.translation_record_ids == tuple(record.translation_id for record in records)
    assert HammerReconstructionReceipt.from_dict(receipt.to_dict()) == receipt


def test_receipt_marks_verified_native_reconstruction_trusted() -> None:
    def _verifier(itp_system, proof_script, goal, selected_premises):
        return HammerVerification(verified=True, checker="fake-lean-kernel", output="ok")

    result = HammerPipeline(
        backends=[_backend("z3", "smt-lib")],
        verify_reconstruction=True,
        kernel_verifier=_verifier,
        parallel_workers=1,
    ).prove(_goal(), [HammerPremise("p", "P")])
    receipt = reconstruction_receipt_from_hammer_result(
        result,
        trusted_requires_reconstruction=True,
    )

    assert receipt.outcome == HammerReconstructionOutcome.NATIVE_RECONSTRUCTION
    assert receipt.native_reconstruction_verified is True
    assert receipt.checker == "fake-lean-kernel"
    assert receipt.trust_status == HammerTrustStatus.TRUSTED
    assert receipt.trust_reason == "native_reconstruction_verified"


def test_translation_failure_is_persisted_without_running_backend() -> None:
    calls = []

    def _should_not_run(translation, timeout_seconds):
        calls.append(translation)
        raise AssertionError("backend must not run after translation failure")

    result = HammerPipeline(
        backends=[CallableHammerBackendRunner("custom", "unsupported-format", _should_not_run)],
        parallel_workers=1,
    ).prove(_goal(), [HammerPremise("p", "P")])
    records = translation_records_from_hammer_result(result)
    receipt = reconstruction_receipt_from_hammer_result(
        result,
        translation_records=records,
        trusted=True,
    )

    assert result.status == HammerStatus.TRANSLATION_FAILED
    assert not calls
    assert len(records) == 1
    assert records[0].surface == HammerTranslationSurface.OTHER
    assert records[0].success is False
    assert all(
        decision.status == HammerTranslationDecisionStatus.FAILED
        for decision in records[0].transformation_decisions
    )
    assert receipt.outcome == HammerReconstructionOutcome.TRANSLATION_FAILURE
    assert receipt.translation_failed is True
    assert receipt.backend_proved is False
    assert receipt.native_reconstruction is False
    # A caller-provided trust value can revoke trust but cannot elevate a
    # failed translation across the receipt's trust boundary.
    assert receipt.trusted is False
    assert receipt.errors == ("Unsupported hammer translation target: unsupported-format",)


def test_legal_ir_report_persists_records_and_receipts_without_source_payloads() -> None:
    obligation = {
        "formula_id": "f1",
        "kind": "external_prover_route_preservation",
        "legal_ir_view": "external_provers.router",
        "logic_family": "proof_translation",
        "obligation_id": "lir-obligation-report",
        "sample_id": "sample-1",
        "statement": "external_route_preserves_types(f1)",
    }
    report = run_legal_ir_hammer(
        {"sample_id": "sample-1"},
        obligations=[obligation],
        premises=[HammerPremise("route_preservation", "external_route_preserves_types(f1)")],
        config=LegalIRHammerConfig(
            max_premises=4,
            parallel_workers=1,
            trusted_requires_reconstruction=True,
        ),
        backends=[_backend("z3", "smt-lib")],
    )
    payload = report.to_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert len(report.translation_records) == 2
    assert len(report.reconstruction_receipts) == 1
    assert payload["metadata"]["translation_record_count"] == 2
    assert payload["metadata"]["reconstruction_receipt_count"] == 1
    assert payload["reconstruction_receipts"][0]["schema_version"] == (
        LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
    )
    assert payload["reconstruction_receipts"][0]["trusted"] is False
    assert report.artifacts[0].trusted is False
    assert "external_route_preserves_types(f1)" not in encoded
