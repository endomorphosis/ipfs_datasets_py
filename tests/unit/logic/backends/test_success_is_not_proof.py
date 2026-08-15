"""LPC-032: provider success must never imply proof authority.

Acceptance:

* ``succeeded + unknown + advisory`` is a representable axis coordinate.
* That coordinate cannot pass a kernel-required policy.
* Backend enforcement points refuse silent promotion from operation success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from ipfs_datasets_py.logic.backends.atp.execution_v2 import (
    atp_success_establishes_theorem,
)
from ipfs_datasets_py.logic.backends.portfolio import assurance_satisfies
from ipfs_datasets_py.logic.backends.requests_v2 import (
    AuthorityOverclaimError,
    RequestAuthorityCeiling,
    _check_authority_overclaim,
)
from ipfs_datasets_py.logic.backends.results import (
    AuthoritySubstitutionError,
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import evidence_id
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicAvailability,
    LogicAxisCoordinate,
    LogicBoundedness,
    LogicEvidenceAuthority,
    LogicEvidenceKind,
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicTranslationPreservation,
    evidence_authority_from_operation_status,
    semantic_verdict_from_operation_status,
    succeeded_unknown_advisory_coordinate,
)
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage


# ---------------------------------------------------------------------------
# Kernel-required policy (axis coordinate)
# ---------------------------------------------------------------------------

# Authority ceilings that may satisfy a kernel-required admission gate.
_KERNEL_GRADE_AUTHORITY: Final[frozenset[LogicEvidenceAuthority]] = frozenset(
    {
        LogicEvidenceAuthority.AUTHORITATIVE,
        LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    }
)

# Evidence kinds that may accompany kernel-grade proof authority.
_KERNEL_GRADE_EVIDENCE_KIND: Final[frozenset[LogicEvidenceKind]] = frozenset(
    {
        LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        LogicEvidenceKind.CHECKED_PROOF,
        LogicEvidenceKind.PROOF_CERTIFICATE,
    }
)


def coordinate_passes_kernel_required_policy(
    coordinate: LogicAxisCoordinate,
) -> bool:
    """Return whether a coordinate may satisfy a kernel-required policy.

    Fail-closed.  Operation success is deliberately **not** consulted: a
    succeeded attempt with unknown/advisory fields must fail, and a non-success
    lifecycle alone cannot mint kernel authority either.
    """

    if coordinate.evidence_authority not in _KERNEL_GRADE_AUTHORITY:
        return False
    if not coordinate.semantic_verdict.conclusive:
        return False
    if coordinate.evidence_kind not in _KERNEL_GRADE_EVIDENCE_KIND:
        return False
    return True


def kernel_policy_rejection_reasons(
    coordinate: LogicAxisCoordinate,
) -> tuple[str, ...]:
    """Stable reason codes explaining why a coordinate fails kernel policy."""

    reasons: list[str] = []
    if coordinate.evidence_authority not in _KERNEL_GRADE_AUTHORITY:
        reasons.append(
            f"evidence_authority_{coordinate.evidence_authority.value}"
            "_below_kernel_floor"
        )
    if not coordinate.semantic_verdict.conclusive:
        reasons.append(
            f"semantic_verdict_{coordinate.semantic_verdict.value}_not_conclusive"
        )
    if coordinate.evidence_kind not in _KERNEL_GRADE_EVIDENCE_KIND:
        reasons.append(
            f"evidence_kind_{coordinate.evidence_kind.value}_not_kernel_grade"
        )
    # Document that success is ignored as an authority signal.
    if coordinate.operation_status is LogicOperationStatus.SUCCEEDED:
        reasons.append("operation_success_is_not_proof_authority")
    return tuple(reasons)


def _note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "no_success_implies_proof.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


def _candidate_result() -> CandidateResult:
    return CandidateResult(
        result_id="result:lpc-032-candidate",
        backend_id="provider.advisory",
        backend_version="1.0.0",
        authority=ResultAuthority.CANDIDATE,
        status=ResultStatus.CANDIDATE,
        bounds=ExecutionBounds(),
        translation_ceiling=EvidenceAuthority.ADVISORY,
        usage=ResourceUsage(),
        reason="provider succeeded with advisory candidate only",
    )


def _theorem_result() -> TheoremResult:
    return TheoremResult(
        result_id="result:lpc-032-theorem",
        backend_id="kernel.lean",
        backend_version="4.0.0",
        authority=ResultAuthority.THEOREM,
        status=ResultStatus.PROVED,
        bounds=ExecutionBounds(),
        translation_ceiling=EvidenceAuthority.AUTHORITATIVE,
        usage=ResourceUsage(),
    )


# ---------------------------------------------------------------------------
# Representability
# ---------------------------------------------------------------------------


def test_succeeded_unknown_advisory_is_representable() -> None:
    coordinate = succeeded_unknown_advisory_coordinate()

    assert coordinate.operation_status is LogicOperationStatus.SUCCEEDED
    assert coordinate.semantic_verdict is LogicSemanticVerdict.UNKNOWN
    assert coordinate.availability is LogicAvailability.AVAILABLE
    assert coordinate.evidence_kind is LogicEvidenceKind.CANDIDATE
    assert coordinate.evidence_authority is LogicEvidenceAuthority.ADVISORY
    assert coordinate.boundedness is LogicBoundedness.UNKNOWN
    assert (
        coordinate.translation_preservation
        is LogicTranslationPreservation.NOT_APPLICABLE
    )

    rebuilt = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.SUCCEEDED,
        semantic_verdict=LogicSemanticVerdict.UNKNOWN,
        availability=LogicAvailability.AVAILABLE,
        evidence_kind=LogicEvidenceKind.CANDIDATE,
        evidence_authority=LogicEvidenceAuthority.ADVISORY,
        boundedness=LogicBoundedness.UNKNOWN,
        translation_preservation=LogicTranslationPreservation.NOT_APPLICABLE,
    )
    assert rebuilt == coordinate
    payload = coordinate.to_dict()
    assert LogicAxisCoordinate.from_dict(payload) == coordinate


def test_succeeded_provider_response_may_carry_unknown_and_advisory() -> None:
    """Axes stay independent: success does not force proved/authoritative."""

    for verdict in (
        LogicSemanticVerdict.UNKNOWN,
        LogicSemanticVerdict.INCONCLUSIVE,
        LogicSemanticVerdict.NOT_APPLICABLE,
    ):
        for authority in (
            LogicEvidenceAuthority.ADVISORY,
            LogicEvidenceAuthority.NONE,
            LogicEvidenceAuthority.UNKNOWN,
        ):
            coordinate = LogicAxisCoordinate(
                operation_status=LogicOperationStatus.SUCCEEDED,
                semantic_verdict=verdict,
                availability=LogicAvailability.AVAILABLE,
                evidence_kind=LogicEvidenceKind.CANDIDATE,
                evidence_authority=authority,
                boundedness=LogicBoundedness.UNKNOWN,
                translation_preservation=LogicTranslationPreservation.NOT_APPLICABLE,
            )
            assert coordinate.operation_status is LogicOperationStatus.SUCCEEDED
            assert coordinate.semantic_verdict is verdict
            assert coordinate.evidence_authority is authority


# ---------------------------------------------------------------------------
# Kernel-required policy rejection
# ---------------------------------------------------------------------------


def test_succeeded_unknown_advisory_cannot_pass_kernel_required_policy() -> None:
    coordinate = succeeded_unknown_advisory_coordinate()

    assert coordinate_passes_kernel_required_policy(coordinate) is False
    reasons = kernel_policy_rejection_reasons(coordinate)
    assert reasons
    assert any("advisory" in reason for reason in reasons)
    assert any("unknown" in reason for reason in reasons)
    assert any("candidate" in reason for reason in reasons)
    assert "operation_success_is_not_proof_authority" in reasons

    # Success alone never flips the policy even if other fields improve later;
    # each missing gate is independently required.
    only_success = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.SUCCEEDED,
        semantic_verdict=LogicSemanticVerdict.UNKNOWN,
        availability=LogicAvailability.AVAILABLE,
        evidence_kind=LogicEvidenceKind.CANDIDATE,
        evidence_authority=LogicEvidenceAuthority.ADVISORY,
        boundedness=LogicBoundedness.UNKNOWN,
        translation_preservation=LogicTranslationPreservation.NOT_APPLICABLE,
    )
    assert coordinate_passes_kernel_required_policy(only_success) is False


def test_kernel_policy_ignores_operation_status_as_authority_signal() -> None:
    """Changing only lifecycle must not grant or revoke kernel authority."""

    base_failing = succeeded_unknown_advisory_coordinate()
    for status in LogicOperationStatus:
        flipped = LogicAxisCoordinate(
            operation_status=status,
            semantic_verdict=base_failing.semantic_verdict,
            availability=base_failing.availability,
            evidence_kind=base_failing.evidence_kind,
            evidence_authority=base_failing.evidence_authority,
            boundedness=base_failing.boundedness,
            translation_preservation=base_failing.translation_preservation,
        )
        assert coordinate_passes_kernel_required_policy(flipped) is False

    # A fully kernel-grade coordinate passes regardless of lifecycle, because
    # lifecycle is not an authority axis (still must not *derive* authority
    # from success — authority is set explicitly here).
    kernel_grade = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.FAILED,
        semantic_verdict=LogicSemanticVerdict.PROVED,
        availability=LogicAvailability.AVAILABLE,
        evidence_kind=LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        evidence_authority=LogicEvidenceAuthority.AUTHORITATIVE,
        boundedness=LogicBoundedness.UNBOUNDED,
        translation_preservation=LogicTranslationPreservation.LOSSLESS,
    )
    assert coordinate_passes_kernel_required_policy(kernel_grade) is True

    kernel_grade_succeeded = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.SUCCEEDED,
        semantic_verdict=LogicSemanticVerdict.PROVED,
        availability=LogicAvailability.AVAILABLE,
        evidence_kind=LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        evidence_authority=LogicEvidenceAuthority.AUTHORITATIVE,
        boundedness=LogicBoundedness.UNBOUNDED,
        translation_preservation=LogicTranslationPreservation.LOSSLESS,
    )
    assert coordinate_passes_kernel_required_policy(kernel_grade_succeeded) is True
    # Explicit fields — not success — are what pass.  Strip authority back.
    demoted = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.SUCCEEDED,
        semantic_verdict=LogicSemanticVerdict.PROVED,
        availability=LogicAvailability.AVAILABLE,
        evidence_kind=LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        evidence_authority=LogicEvidenceAuthority.ADVISORY,
        boundedness=LogicBoundedness.UNBOUNDED,
        translation_preservation=LogicTranslationPreservation.LOSSLESS,
    )
    assert coordinate_passes_kernel_required_policy(demoted) is False


def test_partial_kernel_fields_still_fail_closed() -> None:
    """Each kernel gate is mandatory; partial strength is not enough."""

    # Authoritative but non-conclusive.
    assert (
        coordinate_passes_kernel_required_policy(
            LogicAxisCoordinate(
                operation_status=LogicOperationStatus.SUCCEEDED,
                semantic_verdict=LogicSemanticVerdict.UNKNOWN,
                availability=LogicAvailability.AVAILABLE,
                evidence_kind=LogicEvidenceKind.KERNEL_CHECKED_PROOF,
                evidence_authority=LogicEvidenceAuthority.AUTHORITATIVE,
                boundedness=LogicBoundedness.UNBOUNDED,
                translation_preservation=LogicTranslationPreservation.LOSSLESS,
            )
        )
        is False
    )
    # Proved candidate remains non-kernel kind.
    assert (
        coordinate_passes_kernel_required_policy(
            LogicAxisCoordinate(
                operation_status=LogicOperationStatus.SUCCEEDED,
                semantic_verdict=LogicSemanticVerdict.PROVED,
                availability=LogicAvailability.AVAILABLE,
                evidence_kind=LogicEvidenceKind.CANDIDATE,
                evidence_authority=LogicEvidenceAuthority.AUTHORITATIVE,
                boundedness=LogicBoundedness.UNBOUNDED,
                translation_preservation=LogicTranslationPreservation.LOSSLESS,
            )
        )
        is False
    )
    # Kernel kind with advisory ceiling fails.
    assert (
        coordinate_passes_kernel_required_policy(
            LogicAxisCoordinate(
                operation_status=LogicOperationStatus.SUCCEEDED,
                semantic_verdict=LogicSemanticVerdict.PROVED,
                availability=LogicAvailability.AVAILABLE,
                evidence_kind=LogicEvidenceKind.KERNEL_CHECKED_PROOF,
                evidence_authority=LogicEvidenceAuthority.ADVISORY,
                boundedness=LogicBoundedness.UNBOUNDED,
                translation_preservation=LogicTranslationPreservation.LOSSLESS,
            )
        )
        is False
    )


# ---------------------------------------------------------------------------
# Axis non-inference helpers
# ---------------------------------------------------------------------------


def test_no_authority_or_verdict_inferred_from_operation_success() -> None:
    for status in LogicOperationStatus:
        assert (
            evidence_authority_from_operation_status(status)
            is LogicEvidenceAuthority.UNKNOWN
        )
        assert (
            evidence_authority_from_operation_status(status.value)
            is LogicEvidenceAuthority.UNKNOWN
        )
        assert (
            semantic_verdict_from_operation_status(status)
            is LogicSemanticVerdict.UNKNOWN
        )

    assert evidence_authority_from_operation_status(
        LogicOperationStatus.SUCCEEDED
    ) is not LogicEvidenceAuthority.AUTHORITATIVE
    assert evidence_authority_from_operation_status(
        LogicOperationStatus.SUCCEEDED
    ) is not LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE
    assert evidence_authority_from_operation_status(
        LogicOperationStatus.SUCCEEDED
    ) is not LogicEvidenceAuthority.ADVISORY
    assert (
        semantic_verdict_from_operation_status(LogicOperationStatus.SUCCEEDED)
        is not LogicSemanticVerdict.PROVED
    )


def test_advisory_rank_is_below_kernel_floor() -> None:
    advisory = LogicEvidenceAuthority.ADVISORY
    assert advisory.rank < LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE.rank
    assert advisory.rank < LogicEvidenceAuthority.AUTHORITATIVE.rank
    # Portfolio lattice (families EvidenceAuthority) agrees.
    assert not assurance_satisfies(
        EvidenceAuthority.ADVISORY, EvidenceAuthority.AUTHORITATIVE
    )
    assert not assurance_satisfies(
        EvidenceAuthority.ADVISORY, EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )
    assert assurance_satisfies(
        EvidenceAuthority.AUTHORITATIVE, EvidenceAuthority.ADVISORY
    )


# ---------------------------------------------------------------------------
# Backend enforcement anchors
# ---------------------------------------------------------------------------


def test_advisor_advisory_cannot_satisfy_certified_or_kernel_authority() -> None:
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.ADVISOR, ToolchainAuthorityCeiling.ADVISORY
        )
        is False
    )
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.CANDIDATE, ToolchainAuthorityCeiling.CANDIDATE
        )
        is False
    )
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.ADVISOR, ToolchainAuthorityCeiling.KERNEL
        )
        is False
    )
    # Even an authority role with an advisory ceiling cannot certify.
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.AUTHORITY, ToolchainAuthorityCeiling.ADVISORY
        )
        is False
    )
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.AUTHORITY, ToolchainAuthorityCeiling.KERNEL
        )
        is True
    )


def test_candidate_and_advisory_evidence_cannot_claim_kernel_ceiling() -> None:
    for kind in ("candidate", "advisory", "model", "trace", "monitor", "parse"):
        with pytest.raises(AuthorityOverclaimError):
            _check_authority_overclaim(
                RequestAuthorityCeiling.KERNEL,
                evidence_id(kind),
            )


def test_candidate_result_cannot_satisfy_theorem_authority_requirement() -> None:
    candidate = _candidate_result()
    assert candidate.authority is ResultAuthority.CANDIDATE
    assert candidate.translation_ceiling is EvidenceAuthority.ADVISORY
    with pytest.raises(AuthoritySubstitutionError):
        candidate.require_authority(ResultAuthority.THEOREM)

    theorem = _theorem_result()
    assert theorem.require_authority(ResultAuthority.THEOREM) is theorem
    with pytest.raises(AuthoritySubstitutionError):
        theorem.require_authority(ResultAuthority.CANDIDATE)


def test_atp_success_never_establishes_theorem_authority() -> None:
    assert atp_success_establishes_theorem() is False
    assert (
        atp_success_establishes_theorem(
            szs_status="Theorem",
            proof_present=True,
            reconstruction_ok=True,
            replay_matched=True,
            available=True,
            confidence=1.0,
        )
        is False
    )


def test_succeeded_unknown_advisory_fails_every_backend_kernel_proxy() -> None:
    """End-to-end: the LPC-032 counterexample fails all kernel-grade proxies."""

    coordinate = succeeded_unknown_advisory_coordinate()
    assert coordinate.operation_status is LogicOperationStatus.SUCCEEDED
    assert coordinate_passes_kernel_required_policy(coordinate) is False

    # Axis helpers refuse promotion from success.
    assert (
        evidence_authority_from_operation_status(coordinate.operation_status)
        is LogicEvidenceAuthority.UNKNOWN
    )
    assert (
        semantic_verdict_from_operation_status(coordinate.operation_status)
        is LogicSemanticVerdict.UNKNOWN
    )

    # Assurance lattice: advisory cannot meet authoritative (kernel-grade).
    assert not assurance_satisfies(
        EvidenceAuthority(coordinate.evidence_authority.value),
        EvidenceAuthority.AUTHORITATIVE,
    )

    # Role matrix: advisor/advisory cannot certify.
    assert not role_can_satisfy_certified_authority(
        ToolRole.ADVISOR, ToolchainAuthorityCeiling.ADVISORY
    )

    # Request admission: candidate evidence cannot claim kernel.
    with pytest.raises(AuthorityOverclaimError):
        _check_authority_overclaim(
            RequestAuthorityCeiling.KERNEL,
            evidence_id(coordinate.evidence_kind.value),
        )

    # Typed result: candidate cannot stand in for theorem.
    with pytest.raises(AuthoritySubstitutionError):
        _candidate_result().require_authority(ResultAuthority.THEOREM)

    # ATP success path is permanently non-theorem.
    assert atp_success_establishes_theorem(proof_present=True) is False


# ---------------------------------------------------------------------------
# Durable note contract
# ---------------------------------------------------------------------------


def test_note_documents_non_inference_and_kernel_policy() -> None:
    note_path = _note_path()
    assert note_path.is_file(), f"missing LPC-032 note at {note_path}"
    text = note_path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "LPC-032" in text
    assert "succeeded" in text
    assert "unknown" in text
    assert "advisory" in text
    assert "succeeded_unknown_advisory_coordinate" in text
    assert "operation_status" in text
    assert "semantic_verdict" in text
    assert "evidence_authority" in text
    assert "cannot pass" in lowered
    assert "kernel-required" in lowered or "kernel required" in lowered
    assert "success" in lowered and "proof" in lowered
    assert "authority" in lowered
    # Non-inference headings (unicode or ASCII fallback).
    assert ("Success ≠ proof" in text) or ("Success != proof" in text)
    assert ("Success ≠ authority" in text) or ("Success != authority" in text)
