"""Integration tests: separate Hammer, reconstruction, official kernel (LFP2-034).

Acceptance (fail-closed):

* Imports, axioms, admits, trust escapes, environment, source theorem, and
  official kernel result are bound on every answer.
* Hammer never becomes proof authority — premise selection / ATP success /
  reconstruction alone cannot mint theorem proof.
* Only official Lean / Rocq / Isabelle kernel acceptance with matching
  bindings may establish proved / theorem authority.
* Mock / fallback / availability / confidence never establish proof.

Interfaces: KernelProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.kernel.execution_v2 import (
    KERNEL_EXECUTION_V2_TASK_ID,
    KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE,
    KernelAuthorityError,
    KernelClaimKind,
    KernelDisposition,
    KernelExecutionEngineV2,
    KernelExecutionError,
    KernelExecutionMode,
    KernelExecutionRequestV2,
    KernelPhase,
    KernelPhaseStatus,
    KernelProviderEvidenceV2,
    KernelProviderKind,
    build_minimal_theory,
    execute_isabelle,
    execute_kernel,
    execute_lean,
    execute_rocq,
    hammer_establishes_proof,
    non_authoritative_signal_establishes,
    normalize_kernel_provider,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.translations.kernel_targets import (
    KernelCompilationCandidate,
    KernelTargetKind,
)


# ---------------------------------------------------------------------------
# Compact fixture recipes
# ---------------------------------------------------------------------------


def _theory(
    *,
    imports: tuple[str, ...] = ("Init.Prelude",),
    axioms: tuple[str, ...] = ("classical_choice",),
    statement: str = "True",
    theory_id: str = "theory:demo",
    theorem_id: str = "thm:goal",
):
    return build_minimal_theory(
        theory_id=theory_id,
        name="Demo",
        theorem_id=theorem_id,
        theorem_name="goal",
        statement=statement,
        imports=imports,
        axioms=axioms,
    )


def _request(**overrides: object) -> KernelExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": "req:kernel:1",
        "provider": KernelProviderKind.LEAN,
        "theory": _theory(),
        "mode": KernelExecutionMode.FULL_PIPELINE,
        "environment_id": "env:lean:test",
        "environment": {
            "toolchain_id": "lean",
            "toolchain_version": "4.0.0-test",
        },
        "source_ref_ids": ("source:fixture:kernel:1",),
    }
    payload.update(overrides)
    return KernelExecutionRequestV2(**payload)  # type: ignore[arg-type]


def _assert_bindings_present(evidence: KernelProviderEvidenceV2) -> None:
    """Every answer must bind the LFP2-034 required surfaces."""

    assert evidence.imports.imports is not None
    assert evidence.imports.import_digest
    assert evidence.axioms.axioms is not None
    assert evidence.axioms.axiom_digest
    assert evidence.admits.admit_digest
    assert isinstance(evidence.admits.admits_present, bool)
    assert evidence.trust_escapes.trust_escape_digest
    assert isinstance(evidence.trust_escapes.escapes_present, bool)
    assert evidence.environment.environment_id
    assert evidence.environment.environment_digest
    assert evidence.environment.kernel_target is not None
    assert evidence.source_theorem.theorem_id
    assert evidence.source_theorem.statement_digest
    assert evidence.official_kernel.phase is KernelPhase.OFFICIAL_KERNEL
    assert evidence.official_kernel.kernel_provider is not None
    # Phase separation: all six phases recorded.
    phase_names = {item.phase for item in evidence.phases}
    assert KernelPhase.PREMISE_SELECTION in phase_names
    assert KernelPhase.ATP_CANDIDATE in phase_names
    assert KernelPhase.RECONSTRUCTION in phase_names
    assert KernelPhase.TARGET_COMPILATION in phase_names
    assert KernelPhase.ELABORATION in phase_names
    assert KernelPhase.OFFICIAL_KERNEL in phase_names
    # Hammer is never proof authority.
    assert evidence.hammer_is_proof_authority is False


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = KernelExecutionEngineV2()
    assert engine.INTERFACE == KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "KernelProviderEvidence@2"
    assert engine.TASK_ID == KERNEL_EXECUTION_V2_TASK_ID
    assert KernelExecutionRequestV2.interface == "KernelExecutionRequest@2"
    assert engine.PHASE_ORDER == (
        "premise_selection",
        "atp_candidate",
        "reconstruction",
        "target_compilation",
        "elaboration",
        "official_kernel",
    )


def test_provider_normalization() -> None:
    assert normalize_kernel_provider("lean") is KernelProviderKind.LEAN
    assert normalize_kernel_provider("lean4") is KernelProviderKind.LEAN
    assert normalize_kernel_provider("rocq") is KernelProviderKind.ROCQ
    assert normalize_kernel_provider("coq") is KernelProviderKind.ROCQ
    assert normalize_kernel_provider("isabelle") is KernelProviderKind.ISABELLE
    assert normalize_kernel_provider(KernelTargetKind.LEAN) is KernelProviderKind.LEAN
    with pytest.raises(KernelExecutionError):
        normalize_kernel_provider("vampire")
    with pytest.raises(KernelExecutionError):
        normalize_kernel_provider("hammer")


# ---------------------------------------------------------------------------
# Hammer never becomes proof authority
# ---------------------------------------------------------------------------


def test_hammer_establishes_proof_always_false() -> None:
    assert (
        hammer_establishes_proof(
            premise_selected=True,
            atp_success=True,
            reconstruction_ok=True,
            hammer_available=True,
            confidence=1.0,
            mock_output={"status": "proved"},
        )
        is False
    )


@pytest.mark.parametrize("claim", list(KernelClaimKind))
def test_non_authoritative_signals_never_establish(claim: KernelClaimKind) -> None:
    assert (
        non_authoritative_signal_establishes(
            claim,
            mock_output={"proved": True},
            fallback_output={"proved": True},
            available=True,
            confidence=1.0,
            fluent_text="Obviously proved by Hammer.",
            hammer_success=True,
            reconstruction_success=True,
        )
        is False
    )


def test_hammer_only_mode_remains_candidate() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.HAMMER_ONLY,
            hammer_premises=("prem:nat_add_comm", "prem:nat_zero"),
            hammer_atp_verdict="proved",
            hammer_candidate_id="cand:hammer:1",
            confidence=0.99,
            fluent_text="Hammer found a proof.",
        )
    )
    assert result.disposition is KernelDisposition.HAMMER_CANDIDATE_ONLY
    assert result.proof_established is False
    assert result.is_proved is False
    assert result.evidence.result_authority is ResultAuthority.CANDIDATE
    assert result.evidence.result_status is ResultStatus.CANDIDATE
    assert result.evidence.hammer_is_proof_authority is False
    premise = result.evidence.phase(KernelPhase.PREMISE_SELECTION)
    assert premise is not None
    assert premise.authority is ResultAuthority.CANDIDATE
    atp = result.evidence.phase(KernelPhase.ATP_CANDIDATE)
    assert atp is not None
    assert atp.status is KernelPhaseStatus.CANDIDATE_ONLY
    assert atp.authority is ResultAuthority.CANDIDATE
    assert atp.payload.get("theorem_authority_forbidden") is True
    assert atp.payload.get("hammer_is_proof_authority") is False
    official = result.evidence.phase(KernelPhase.OFFICIAL_KERNEL)
    assert official is not None
    assert official.status is not KernelPhaseStatus.ACCEPTED
    _assert_bindings_present(result.evidence)


def test_atp_success_without_kernel_stays_candidate() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.FULL_PIPELINE,
            hammer_premises=("prem:a",),
            hammer_atp_verdict="unsat",
            reconstruction_accepted=True,
            reconstruction_source="exact h",
            # official_kernel_accepted left None → unavailable
        )
    )
    assert result.proof_established is False
    assert result.is_proved is False
    assert result.evidence.result_authority in {
        ResultAuthority.CANDIDATE,
        ResultAuthority.RECONSTRUCTION,
    }
    assert result.evidence.official_kernel.accepted is False
    assert result.evidence.hammer_is_proof_authority is False
    # ATP phase cannot claim theorem.
    atp = result.evidence.phase(KernelPhase.ATP_CANDIDATE)
    assert atp is not None
    assert atp.authority is ResultAuthority.CANDIDATE
    _assert_bindings_present(result.evidence)


def test_reconstruction_only_is_not_theorem() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.RECONSTRUCTION_ONLY,
            reconstruction_accepted=True,
            reconstruction_source="rfl",
            hammer_atp_verdict="proved",
        )
    )
    assert result.disposition is KernelDisposition.RECONSTRUCTED
    assert result.proof_established is False
    assert result.is_proved is False
    assert result.evidence.result_authority is ResultAuthority.RECONSTRUCTION
    assert result.evidence.result_status is ResultStatus.RECONSTRUCTED
    recon = result.evidence.phase(KernelPhase.RECONSTRUCTION)
    assert recon is not None
    assert recon.authority is ResultAuthority.RECONSTRUCTION
    assert recon.authority is not ResultAuthority.THEOREM
    _assert_bindings_present(result.evidence)


def test_phase_receipt_rejects_hammer_theorem_authority() -> None:
    from ipfs_datasets_py.logic.backends.kernel.execution_v2 import (
        KernelPhaseReceiptV2,
    )

    with pytest.raises(KernelAuthorityError):
        KernelPhaseReceiptV2(
            phase=KernelPhase.ATP_CANDIDATE,
            status=KernelPhaseStatus.CANDIDATE_ONLY,
            authority=ResultAuthority.THEOREM,
        )
    with pytest.raises(KernelAuthorityError):
        KernelPhaseReceiptV2(
            phase=KernelPhase.PREMISE_SELECTION,
            status=KernelPhaseStatus.COMPLETED,
            authority=ResultAuthority.THEOREM,
        )
    with pytest.raises(KernelAuthorityError):
        KernelPhaseReceiptV2(
            phase=KernelPhase.RECONSTRUCTION,
            status=KernelPhaseStatus.RECONSTRUCTED,
            authority=ResultAuthority.THEOREM,
        )


# ---------------------------------------------------------------------------
# Official kernel is sole theorem authority
# ---------------------------------------------------------------------------


def test_official_kernel_acceptance_establishes_proof() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.FULL_PIPELINE,
            hammer_premises=("prem:a",),
            hammer_atp_verdict="proved",
            hammer_candidate_id="cand:h:1",
            reconstruction_accepted=True,
            reconstruction_source="rfl",
            official_kernel_accepted=True,
            official_kernel_receipt_id="receipt:lean:ok:1",
            official_kernel_diagnostics=("kernel accepted",),
            environment_id="env:lean:test",
        )
    )
    assert result.disposition is KernelDisposition.PROVED
    assert result.proof_established is True
    assert result.is_proved is True
    assert result.evidence.result_authority is ResultAuthority.THEOREM
    assert result.evidence.result_status is ResultStatus.PROVED
    assert result.evidence.official_kernel.accepted is True
    assert result.evidence.official_kernel.authority is ResultAuthority.THEOREM
    assert result.evidence.official_kernel.receipt_id == "receipt:lean:ok:1"
    assert result.evidence.hammer_is_proof_authority is False
    assert result.evidence.role is ToolRole.AUTHORITY
    assert result.evidence.authority_ceiling is ToolchainAuthorityCeiling.KERNEL
    kernel_phase = result.evidence.phase(KernelPhase.OFFICIAL_KERNEL)
    assert kernel_phase is not None
    assert kernel_phase.status is KernelPhaseStatus.ACCEPTED
    assert kernel_phase.authority is ResultAuthority.THEOREM
    # Bindings coherent with acceptance.
    assert (
        result.evidence.official_kernel.environment_id
        == result.evidence.environment.environment_id
    )
    assert (
        result.evidence.official_kernel.theorem_digest
        == result.evidence.source_theorem.statement_digest
    )
    assert result.evidence.imports.imports == ("Init.Prelude",)
    assert "classical_choice" in result.evidence.axioms.axioms
    assert result.evidence.admits.admits_present is False
    assert result.evidence.trust_escapes.escapes_present is False
    assert result.typed_result is not None
    assert result.typed_result.authority is ResultAuthority.THEOREM
    _assert_bindings_present(result.evidence)


def test_official_kernel_rejection_not_proved() -> None:
    result = execute_kernel(
        _request(
            official_kernel_accepted=False,
            official_kernel_receipt_id="receipt:lean:bad:1",
            official_kernel_diagnostics=("type mismatch",),
            reconstruction_accepted=True,
            hammer_atp_verdict="proved",
        )
    )
    assert result.disposition is KernelDisposition.KERNEL_REJECTED
    assert result.proof_established is False
    assert result.is_proved is False
    assert result.evidence.official_kernel.accepted is False
    assert result.evidence.result_authority is ResultAuthority.CANDIDATE
    _assert_bindings_present(result.evidence)


def test_kernel_checker_callback_can_accept() -> None:
    def checker(request, candidate: KernelCompilationCandidate):
        del request
        assert candidate.kernel_accepted is False
        return {
            "accepted": True,
            "receipt_id": "receipt:callback:1",
            "diagnostics": ("callback accepted",),
        }

    engine = KernelExecutionEngineV2(kernel_checker=checker)
    result = engine.execute(
        _request(
            official_kernel_accepted=None,
            reconstruction_accepted=True,
        )
    )
    assert result.is_proved is True
    assert result.evidence.official_kernel.receipt_id == "receipt:callback:1"
    _assert_bindings_present(result.evidence)


# ---------------------------------------------------------------------------
# Trust escapes / admits block theorem authority
# ---------------------------------------------------------------------------


def test_proof_body_with_sorry_rejected() -> None:
    result = execute_kernel(
        _request(
            proof_body="sorry",
            official_kernel_accepted=True,
            official_kernel_receipt_id="receipt:should-not-matter",
        )
    )
    assert result.proof_established is False
    assert result.is_proved is False
    assert result.disposition in {
        KernelDisposition.TRUST_ESCAPE_REJECTED,
        KernelDisposition.ADMIT_REJECTED,
        KernelDisposition.ERROR,
    }
    _assert_bindings_present(result.evidence)


def test_proof_body_with_admit_rejected_for_rocq() -> None:
    result = execute_rocq(
        _theory(imports=("Coq.Init.Prelude",), axioms=()),
        request_id="req:rocq:admit",
        environment_id="env:rocq:test",
        environment={"toolchain_id": "rocq", "toolchain_version": "8.20-test"},
        proof_body="admit.",
        official_kernel_accepted=True,
        official_kernel_receipt_id="receipt:rocq:should-not",
        source_ref_ids=("source:fixture:rocq:1",),
    )
    assert result.proof_established is False
    assert result.is_proved is False
    assert result.disposition in {
        KernelDisposition.TRUST_ESCAPE_REJECTED,
        KernelDisposition.ADMIT_REJECTED,
        KernelDisposition.ERROR,
    }
    assert result.evidence.provider is KernelProviderKind.ROCQ
    _assert_bindings_present(result.evidence)


def test_evidence_rejects_hammer_as_proof_authority_flag() -> None:
    good = execute_kernel(
        _request(
            official_kernel_accepted=True,
            official_kernel_receipt_id="receipt:lean:ok:2",
        )
    )
    # Reconstructing with the flag forced True must fail closed.
    with pytest.raises(KernelAuthorityError, match="Hammer never becomes"):
        KernelProviderEvidenceV2(
            evidence_id=good.evidence.evidence_id,
            request_id=good.evidence.request_id,
            provider=good.evidence.provider,
            disposition=good.evidence.disposition,
            phases=good.evidence.phases,
            imports=good.evidence.imports,
            axioms=good.evidence.axioms,
            admits=good.evidence.admits,
            trust_escapes=good.evidence.trust_escapes,
            environment=good.evidence.environment,
            source_theorem=good.evidence.source_theorem,
            official_kernel=good.evidence.official_kernel,
            result_authority=ResultAuthority.THEOREM,
            result_status=ResultStatus.PROVED,
            hammer_is_proof_authority=True,
            proof_established=True,
        )


# ---------------------------------------------------------------------------
# Mock / fallback rejection
# ---------------------------------------------------------------------------


def test_mock_output_rejected() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.MOCK,
            mock_output={"status": "proved", "kernel_accepted": True},
            confidence=1.0,
        )
    )
    assert result.disposition is KernelDisposition.MOCK_REJECTED
    assert result.proof_established is False
    assert result.is_proved is False
    _assert_bindings_present(result.evidence)


def test_fallback_output_rejected() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.FALLBACK,
            fallback_output={"status": "proved"},
        )
    )
    assert result.disposition is KernelDisposition.FALLBACK_REJECTED
    assert result.proof_established is False
    _assert_bindings_present(result.evidence)


# ---------------------------------------------------------------------------
# Per-provider paths + binding completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider,execute_fn,imports",
    [
        (KernelProviderKind.LEAN, execute_lean, ("Init.Prelude",)),
        (KernelProviderKind.ROCQ, execute_rocq, ("Coq.Init.Prelude",)),
        (KernelProviderKind.ISABELLE, execute_isabelle, ("Main",)),
    ],
)
def test_provider_paths_bind_all_surfaces(
    provider: KernelProviderKind,
    execute_fn,
    imports: tuple[str, ...],
) -> None:
    result = execute_fn(
        _theory(imports=imports, axioms=("ax:refl",)),
        request_id=f"req:{provider.value}:bind",
        environment_id=f"env:{provider.value}:bind",
        environment={
            "toolchain_id": provider.value,
            "toolchain_version": "test-1",
        },
        official_kernel_accepted=True,
        official_kernel_receipt_id=f"receipt:{provider.value}:1",
        source_ref_ids=(f"source:fixture:{provider.value}:1",),
    )
    assert result.evidence.provider is provider
    assert result.is_proved is True
    assert result.evidence.imports.imports == imports
    assert "ax:refl" in result.evidence.axioms.axioms
    assert result.evidence.environment.kernel_target is provider
    assert result.evidence.source_theorem.statement == "True"
    assert result.evidence.official_kernel.accepted is True
    # Separated phases present and ordered uniquely.
    seen: list[KernelPhase] = []
    for receipt in result.evidence.phases:
        assert receipt.phase not in seen
        seen.append(receipt.phase)  # type: ignore[arg-type]
    assert KernelPhase.OFFICIAL_KERNEL in seen
    _assert_bindings_present(result.evidence)


def test_compile_and_check_skips_hammer_but_can_prove() -> None:
    result = execute_kernel(
        _request(
            mode=KernelExecutionMode.COMPILE_AND_CHECK,
            official_kernel_accepted=True,
            official_kernel_receipt_id="receipt:compile:1",
        )
    )
    assert result.is_proved is True
    premise = result.evidence.phase(KernelPhase.PREMISE_SELECTION)
    assert premise is not None
    assert premise.status is KernelPhaseStatus.SKIPPED
    atp = result.evidence.phase(KernelPhase.ATP_CANDIDATE)
    assert atp is not None
    assert atp.status is KernelPhaseStatus.SKIPPED
    _assert_bindings_present(result.evidence)


def test_bindings_survive_serialization_round_trip() -> None:
    result = execute_kernel(
        _request(
            official_kernel_accepted=True,
            official_kernel_receipt_id="receipt:rt:1",
            hammer_premises=("prem:x",),
            hammer_atp_verdict="candidate",
        )
    )
    wire = result.to_dict()
    assert wire["evidence"]["interface"] == KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE
    assert wire["evidence"]["hammer_is_proof_authority"] is False
    assert "imports" in wire["evidence"]
    assert "axioms" in wire["evidence"]
    assert "admits" in wire["evidence"]
    assert "trust_escapes" in wire["evidence"]
    assert "environment" in wire["evidence"]
    assert "source_theorem" in wire["evidence"]
    assert "official_kernel" in wire["evidence"]
    assert len(wire["evidence"]["phases"]) == 6


def test_request_rejects_authority_metadata_keys() -> None:
    with pytest.raises(KernelAuthorityError):
        _request(metadata={"proved": True})
    with pytest.raises(KernelAuthorityError):
        _request(metadata={"mock_output": {"x": 1}})
