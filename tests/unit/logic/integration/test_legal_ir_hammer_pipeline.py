"""Tests for the Legal IR hammer runner."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerVerification,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
    LegalIRHammerConfig,
    run_legal_ir_hammer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrameLogic,
    ModalIRFrameLogicTriple,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _proved_backend(name: str = "z3"):
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend=name,
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="unsat",
            raw_output="unsat",
        )

    return CallableHammerBackendRunner(name, "smt-lib", _run)


def _document() -> ModalIRDocument:
    text = "The agency shall provide notice unless emergency conditions exist within 30 days."
    return ModalIRDocument(
        document_id="doc-1",
        source="unit",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="shall",
                    label="shall",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["agency", "notice"],
                    role="obligation",
                ),
                provenance=ModalIRProvenance(
                    source_id="doc-1",
                    start_char=0,
                    end_char=len(text),
                ),
                conditions=["within 30 days"],
                exceptions=["emergency conditions exist"],
            )
        ],
        frame_logic=ModalIRFrameLogic(
            triples=[
                ModalIRFrameLogicTriple(
                    subject="f1",
                    predicate="actor",
                    object="agency",
                )
            ]
        ),
    )


def test_legal_ir_hammer_runner_emits_trusted_guidance_for_obligations() -> None:
    report = run_legal_ir_hammer(
        _document(),
        config=LegalIRHammerConfig(max_premises=64, timeout_seconds=1, parallel_workers=1),
        backends=[_proved_backend()],
    )
    payload = report.to_dict()

    assert payload["schema_version"] == LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION
    assert report.obligation_count >= 6
    assert report.premise_count >= report.obligation_count
    assert report.proved_count == report.obligation_count
    assert report.trusted_count == report.obligation_count
    assert report.proof_success_rate == 1.0
    assert report.trusted_success_rate == 1.0
    assert all(artifact.trusted for artifact in report.artifacts)
    assert any(artifact.legal_ir_view == "deontic.ir" for artifact in report.artifacts)
    assert any("compiler_ir_cross_entropy_loss" in artifact.target_metrics for artifact in report.artifacts)
    assert all(artifact.selected_premises for artifact in report.artifacts)
    assert all(artifact.to_leanstral_guidance_item()["accepted"] for artifact in report.artifacts)


def test_legal_ir_hammer_runner_can_require_kernel_verified_reconstruction() -> None:
    calls = []

    def _verifier(itp_system, proof_script, goal, selected_premises):
        calls.append((itp_system, goal.name, len(selected_premises), proof_script))
        return HammerVerification(
            verified="aesop" in proof_script,
            checker="fake-lean-kernel",
            output="ok",
        )

    report = run_legal_ir_hammer(
        _document(),
        config=LegalIRHammerConfig(
            max_obligations=2,
            max_premises=32,
            timeout_seconds=1,
            verify_reconstruction=True,
            trusted_requires_reconstruction=True,
        ),
        backends=[_proved_backend()],
        kernel_verifier=_verifier,
    )

    assert report.obligation_count == 2
    assert report.proved_count == 2
    assert report.trusted_count == 2
    assert len(calls) == 2
    assert all(artifact.proof_checked for artifact in report.artifacts)
    assert all(artifact.reconstruction_status == "verified" for artifact in report.artifacts)

