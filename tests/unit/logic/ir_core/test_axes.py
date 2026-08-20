"""Regression contracts for orthogonal logic-platform axes (LPC-030)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.ir_core.axes import (
    CANONICAL_AXIS_BY_NAME,
    CANONICAL_AXIS_GENERATIONS,
    CANONICAL_AXIS_NAMES,
    CANONICAL_AXIS_TYPES,
    LOGIC_AXIS_SCHEMA_VERSION,
    LOGIC_AVAILABILITY_GENERATION,
    LOGIC_BOUNDEDNESS_GENERATION,
    LOGIC_EVIDENCE_AUTHORITY_GENERATION,
    LOGIC_EVIDENCE_KIND_GENERATION,
    LOGIC_OPERATION_STATUS_GENERATION,
    LOGIC_SEMANTIC_VERDICT_GENERATION,
    LOGIC_TRANSLATION_PRESERVATION_GENERATION,
    AxisValidationError,
    LogicAvailability,
    LogicAxisCoordinate,
    LogicBoundedness,
    LogicEvidenceAuthority,
    LogicEvidenceKind,
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicTranslationPreservation,
    assert_distinct_axis_types,
    axes_are_orthogonal,
    evidence_authority_from_operation_status,
    semantic_verdict_from_operation_status,
    succeeded_unknown_advisory_coordinate,
)


REQUIRED_AXIS_FIELDS = (
    "operation_status",
    "semantic_verdict",
    "availability",
    "evidence_kind",
    "evidence_authority",
    "boundedness",
    "translation_preservation",
)

REQUIRED_AXIS_TYPES = (
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicAvailability,
    LogicEvidenceKind,
    LogicEvidenceAuthority,
    LogicBoundedness,
    LogicTranslationPreservation,
)

def _migration_note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/axis_migration.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    # Fall back to the monorepo layout used by the implementation workspace.
    return Path(__file__).resolve().parents[5] / note_relative


def test_seven_canonical_axes_are_registered() -> None:
    assert CANONICAL_AXIS_NAMES == REQUIRED_AXIS_FIELDS
    assert CANONICAL_AXIS_TYPES == REQUIRED_AXIS_TYPES
    assert len(CANONICAL_AXIS_NAMES) == 7
    assert len(CANONICAL_AXIS_TYPES) == 7
    assert set(CANONICAL_AXIS_BY_NAME) == set(REQUIRED_AXIS_FIELDS)
    for name, axis_type in zip(REQUIRED_AXIS_FIELDS, REQUIRED_AXIS_TYPES):
        assert CANONICAL_AXIS_BY_NAME[name] is axis_type


def test_axis_types_are_pairwise_distinct() -> None:
    assert_distinct_axis_types()
    assert axes_are_orthogonal() is True
    # Identity, not merely unequal values: no shared enum class.
    for left_index, left in enumerate(CANONICAL_AXIS_TYPES):
        for right_index, right in enumerate(CANONICAL_AXIS_TYPES):
            if left_index == right_index:
                continue
            assert left is not right
            assert left.__name__ != right.__name__
            assert not issubclass(left, right)


def test_axis_types_are_str_enums_with_stable_values() -> None:
    for axis_type in CANONICAL_AXIS_TYPES:
        assert issubclass(axis_type, str)
        assert issubclass(axis_type, Enum)
        values = [member.value for member in axis_type]
        assert values
        assert all(isinstance(value, str) and value == value.strip() for value in values)
        assert len(values) == len(set(values))
        for member in axis_type:
            assert axis_type(member.value) is member
            assert str(member.value) == member.value


def test_generations_and_schema_version_are_stable() -> None:
    assert LOGIC_AXIS_SCHEMA_VERSION == "logic-axis/v1"
    assert LOGIC_OPERATION_STATUS_GENERATION == "LogicOperationStatus@1"
    assert LOGIC_SEMANTIC_VERDICT_GENERATION == "LogicSemanticVerdict@1"
    assert LOGIC_AVAILABILITY_GENERATION == "LogicAvailability@1"
    assert LOGIC_EVIDENCE_KIND_GENERATION == "LogicEvidenceKind@1"
    assert LOGIC_EVIDENCE_AUTHORITY_GENERATION == "LogicEvidenceAuthority@1"
    assert LOGIC_BOUNDEDNESS_GENERATION == "LogicBoundedness@1"
    assert LOGIC_TRANSLATION_PRESERVATION_GENERATION == (
        "LogicTranslationPreservation@1"
    )
    assert set(CANONICAL_AXIS_GENERATIONS) == set(REQUIRED_AXIS_FIELDS)
    for name in REQUIRED_AXIS_FIELDS:
        generation = CANONICAL_AXIS_GENERATIONS[name]
        assert generation.endswith("@1")
        assert generation


def test_operation_status_is_not_semantic_verdict() -> None:
    assert LogicOperationStatus is not LogicSemanticVerdict
    assert LogicOperationStatus.SUCCEEDED.value == "succeeded"
    assert LogicSemanticVerdict.PROVED.value == "proved"
    assert LogicSemanticVerdict.UNKNOWN.value == "unknown"
    # Shared English words across axes remain distinct typed members.
    assert LogicOperationStatus.UNSUPPORTED is not LogicSemanticVerdict.UNSUPPORTED
    assert LogicOperationStatus.UNSUPPORTED.value == LogicSemanticVerdict.UNSUPPORTED.value


def test_availability_is_not_operation_status() -> None:
    assert LogicAvailability is not LogicOperationStatus
    assert LogicAvailability.AVAILABLE.value == "available"
    assert LogicOperationStatus.SUCCEEDED.value == "succeeded"
    assert LogicAvailability.UNAVAILABLE is not LogicOperationStatus.UNAVAILABLE


def test_evidence_kind_is_not_evidence_authority() -> None:
    assert LogicEvidenceKind is not LogicEvidenceAuthority
    assert LogicEvidenceKind.KERNEL_CHECKED_PROOF.value == "kernel_checked_proof"
    assert LogicEvidenceAuthority.AUTHORITATIVE.value == "authoritative"
    assert LogicEvidenceAuthority.ADVISORY.value == "advisory"
    # Kind never appears as an authority member.
    authority_values = {member.value for member in LogicEvidenceAuthority}
    assert "kernel_checked_proof" not in authority_values
    assert "candidate" not in authority_values


def test_boundedness_is_not_authority_or_status() -> None:
    assert LogicBoundedness is not LogicEvidenceAuthority
    assert LogicBoundedness is not LogicOperationStatus
    assert LogicBoundedness.FINITE_TRACE.value == "finite_trace"
    assert LogicBoundedness.RESOURCE_BOUNDED.value == "resource_bounded"
    # Authority reuses the English word "bounded" as a trust ceiling, not scope.
    assert LogicEvidenceAuthority.BOUNDED.value == "bounded"
    assert LogicBoundedness.RESOURCE_BOUNDED is not LogicEvidenceAuthority.BOUNDED


def test_translation_preservation_is_independent_axis() -> None:
    assert LogicTranslationPreservation is not LogicBoundedness
    assert LogicTranslationPreservation is not LogicEvidenceAuthority
    assert LogicTranslationPreservation.LOSSLESS.value == "lossless"
    assert LogicTranslationPreservation.EQUISATISFIABLE.value == "equisatisfiable"
    assert LogicTranslationPreservation.HEURISTIC.value == "heuristic"


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
    # Explicit construction of the same counterexample must also succeed.
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


def test_no_authority_inferred_from_operation_success() -> None:
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
    # Even the strongest lifecycle value stays non-authoritative.
    assert (
        evidence_authority_from_operation_status(LogicOperationStatus.SUCCEEDED)
        is not LogicEvidenceAuthority.AUTHORITATIVE
    )
    assert (
        evidence_authority_from_operation_status(LogicOperationStatus.SUCCEEDED)
        is not LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )


def test_coordinate_round_trip_preserves_independent_fields() -> None:
    original = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.PARTIAL,
        semantic_verdict=LogicSemanticVerdict.INCONCLUSIVE,
        availability=LogicAvailability.OPT_IN,
        evidence_kind=LogicEvidenceKind.SOLVER_RESULT,
        evidence_authority=LogicEvidenceAuthority.BOUNDED,
        boundedness=LogicBoundedness.STEP_BOUNDED,
        translation_preservation=LogicTranslationPreservation.BOUNDED_ABSTRACTION,
    )
    payload = original.to_dict()
    assert payload["schema_version"] == LOGIC_AXIS_SCHEMA_VERSION
    for field_name in REQUIRED_AXIS_FIELDS:
        assert field_name in payload
    restored = LogicAxisCoordinate.from_dict(payload)
    assert restored == original
    # Mutating one axis in a new coordinate leaves others untouched.
    flipped = LogicAxisCoordinate(
        operation_status=LogicOperationStatus.SUCCEEDED,
        semantic_verdict=original.semantic_verdict,
        availability=original.availability,
        evidence_kind=original.evidence_kind,
        evidence_authority=original.evidence_authority,
        boundedness=original.boundedness,
        translation_preservation=original.translation_preservation,
    )
    assert flipped.operation_status is LogicOperationStatus.SUCCEEDED
    assert flipped.semantic_verdict is original.semantic_verdict
    assert flipped.evidence_authority is original.evidence_authority


def test_coordinate_rejects_unknown_axis_labels() -> None:
    with pytest.raises(AxisValidationError):
        LogicAxisCoordinate(
            operation_status="not-a-status",  # type: ignore[arg-type]
            semantic_verdict=LogicSemanticVerdict.UNKNOWN,
            availability=LogicAvailability.UNKNOWN,
            evidence_kind=LogicEvidenceKind.UNKNOWN,
            evidence_authority=LogicEvidenceAuthority.UNKNOWN,
            boundedness=LogicBoundedness.UNKNOWN,
            translation_preservation=LogicTranslationPreservation.UNKNOWN,
        )
    with pytest.raises(AxisValidationError):
        evidence_authority_from_operation_status("not-a-status")


def test_operation_status_lifecycle_helpers() -> None:
    assert LogicOperationStatus.PLANNED.terminal is False
    assert LogicOperationStatus.RUNNING.terminal is False
    assert LogicOperationStatus.SUCCEEDED.terminal is True
    assert LogicOperationStatus.FAILED.terminal is True
    assert LogicOperationStatus.SUCCEEDED.completed_without_crash is True
    assert LogicOperationStatus.PARTIAL.completed_without_crash is True
    assert LogicOperationStatus.FAILED.completed_without_crash is False
    assert LogicSemanticVerdict.PROVED.conclusive is True
    assert LogicSemanticVerdict.UNKNOWN.conclusive is False
    assert LogicSemanticVerdict.INCONCLUSIVE.conclusive is False


def test_evidence_authority_rank_is_order_only() -> None:
    ranks = {member: member.rank for member in LogicEvidenceAuthority}
    assert len(set(ranks.values())) == len(ranks)
    assert (
        ranks[LogicEvidenceAuthority.ADVISORY]
        < ranks[LogicEvidenceAuthority.BOUNDED]
        < ranks[LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE]
        < ranks[LogicEvidenceAuthority.AUTHORITATIVE]
    )
    # Rank is not an inference source from operation status.
    assert evidence_authority_from_operation_status(
        LogicOperationStatus.SUCCEEDED
    ).rank == LogicEvidenceAuthority.UNKNOWN.rank


def test_assert_distinct_axis_types_detects_collapse() -> None:
    with pytest.raises(AxisValidationError):
        assert_distinct_axis_types(
            (
                LogicOperationStatus,
                LogicOperationStatus,  # collapsed duplicate
                LogicAvailability,
                LogicEvidenceKind,
                LogicEvidenceAuthority,
                LogicBoundedness,
                LogicTranslationPreservation,
            )
        )
    with pytest.raises(AxisValidationError):
        assert_distinct_axis_types(CANONICAL_AXIS_TYPES[:3])


def test_migration_note_documents_all_seven_axes() -> None:
    note_path = _migration_note_path()
    assert note_path.is_file(), f"missing axis migration note at {note_path}"
    text = note_path.read_text(encoding="utf-8")
    for axis_name in REQUIRED_AXIS_FIELDS:
        assert axis_name in text
    for type_name in (
        "LogicOperationStatus",
        "LogicSemanticVerdict",
        "LogicAvailability",
        "LogicEvidenceKind",
        "LogicEvidenceAuthority",
        "LogicBoundedness",
        "LogicTranslationPreservation",
    ):
        assert type_name in text
    assert "succeeded" in text
    assert "advisory" in text
    assert "does not imply" in text.lower() or "never" in text.lower()
    assert "LogicOperationStatus@1" in text
    assert "LogicSemanticVerdict@1" in text


def test_axes_module_exports_match_public_surface() -> None:
    import ipfs_datasets_py.logic.ir_core.axes as axes_module

    for name in (
        "LogicOperationStatus",
        "LogicSemanticVerdict",
        "LogicAvailability",
        "LogicEvidenceKind",
        "LogicEvidenceAuthority",
        "LogicBoundedness",
        "LogicTranslationPreservation",
        "LogicAxisCoordinate",
        "succeeded_unknown_advisory_coordinate",
        "evidence_authority_from_operation_status",
        "axes_are_orthogonal",
    ):
        assert name in axes_module.__all__
        assert hasattr(axes_module, name)
