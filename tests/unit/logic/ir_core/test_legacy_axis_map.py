"""Regression contracts for explicit legacy → canonical axis maps (LPC-031).

The durable inventory is
``data/agent_supervisor/logic_platform_canonicalization/notes/legacy_enum_mappings.md``.
This module parses every ``legacy-map`` fence, enforces fail-closed lookup, and
cross-checks live inventoried enums so unknown labels cannot pass silently.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping

import pytest

from ipfs_datasets_py.logic.ir_core.axes import (
    AxisValidationError,
    LogicAvailability,
    LogicBoundedness,
    LogicEvidenceAuthority,
    LogicEvidenceKind,
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicTranslationPreservation,
)


# ---------------------------------------------------------------------------
# Errors and axis registry
# ---------------------------------------------------------------------------


class LegacyAxisMapError(AxisValidationError):
    """Raised when a legacy label cannot be mapped without semantic loss."""


CANONICAL_AXIS_TYPES: Final[Mapping[str, type[Enum]]] = MappingProxyType(
    {
        "operation_status": LogicOperationStatus,
        "semantic_verdict": LogicSemanticVerdict,
        "availability": LogicAvailability,
        "evidence_kind": LogicEvidenceKind,
        "evidence_authority": LogicEvidenceAuthority,
        "boundedness": LogicBoundedness,
        "translation_preservation": LogicTranslationPreservation,
    }
)

REQUIRED_SURFACES: Final[tuple[str, ...]] = (
    "supervisor.AttemptStatus",
    "datasets.ir_core.AttemptStatus",
    "supervisor.ProofVerdict",
    "datasets.ir_core.ResultStatus",
    "datasets.VerificationStatus",
    "datasets.FeatureAvailability",
    "datasets.AvailabilityStatus",
    "supervisor.SupportStatus",
    "families.EvidenceKind",
    "supervisor.EvidenceKind",
    "datasets.ir_core.EvidenceKind",
    "families.EvidenceAuthority",
    "supervisor.EvidenceAuthority",
    "supervisor.AssuranceLevel",
    "families.BoundednessKind",
    "parsers.BoundednessKind",
    "families.TranslationKind",
    "families.PreservationKind",
    "supervisor.TranslationClass",
    "goal_quality.EvidenceAuthority",
    "prompt_workflow.EvidenceAuthority",
    "plan_analysis.EvidenceAuthority",
    "planner_doctor.EvidenceAuthorityClass",
    "repository_surface.EvidenceKind",
    "supervisor.ResourceBudget",
)

REJECT_MERGE_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "goal_quality.EvidenceAuthority",
        "prompt_workflow.EvidenceAuthority",
        "plan_analysis.EvidenceAuthority",
        "planner_doctor.EvidenceAuthorityClass",
        "repository_surface.EvidenceKind",
    }
)

OPERATIONAL_ONLY_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "supervisor.ResourceBudget",
    }
)

_LEGACY_MAP_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"```legacy-map\n(.*?)\n```",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Note loading / parsing
# ---------------------------------------------------------------------------


def _mappings_note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "legacy_enum_mappings.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


def _label_value(raw: object) -> str:
    if isinstance(raw, Enum):
        value = raw.value
    else:
        value = raw
    if not isinstance(value, str) or not value or value != value.strip():
        raise LegacyAxisMapError(
            f"legacy label must be a non-empty trimmed string; got {raw!r}"
        )
    return value


def _parse_multi_axis_target(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in raw.split(";"):
        piece = part.strip()
        if not piece:
            continue
        if "=" not in piece:
            raise LegacyAxisMapError(
                f"multi-axis target must be axis=value pairs; got {raw!r}"
            )
        axis_name, axis_value = piece.split("=", 1)
        axis_name = axis_name.strip()
        axis_value = axis_value.strip()
        if axis_name not in CANONICAL_AXIS_TYPES:
            raise LegacyAxisMapError(
                f"unknown canonical axis {axis_name!r} in multi-axis target"
            )
        if not axis_value:
            raise LegacyAxisMapError(
                f"empty target value for axis {axis_name!r}"
            )
        fields[axis_name] = axis_value
    if not fields:
        raise LegacyAxisMapError(f"empty multi-axis target: {raw!r}")
    return fields


def parse_legacy_map_blocks(text: str) -> dict[str, dict[str, Any]]:
    """Parse every ``legacy-map`` fence into a surface mapping record."""

    surfaces: dict[str, dict[str, Any]] = {}
    for match in _LEGACY_MAP_FENCE_RE.finditer(text):
        body = match.group(1)
        meta: dict[str, str] = {}
        labels: dict[str, str] = {}
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise LegacyAxisMapError(
                    f"legacy-map line must be key: value; got {raw_line!r}"
                )
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in {
                "surface",
                "target_axis",
                "disposition",
                "fail_closed",
            }:
                meta[key] = value
            else:
                labels[key] = value

        surface = meta.get("surface")
        if not surface:
            raise LegacyAxisMapError("legacy-map block missing surface")
        if surface in surfaces:
            raise LegacyAxisMapError(f"duplicate legacy-map surface {surface!r}")

        disposition = meta.get("disposition", "map")
        fail_closed = meta.get("fail_closed", "true").lower() == "true"
        target_axis = meta.get("target_axis")

        if disposition == "map":
            if target_axis not in CANONICAL_AXIS_TYPES:
                raise LegacyAxisMapError(
                    f"surface {surface!r} map disposition requires target_axis"
                )
            resolved: dict[str, Any] = {}
            for legacy_label, target in labels.items():
                member = CANONICAL_AXIS_TYPES[target_axis](target)
                resolved[legacy_label] = member
            surfaces[surface] = {
                "surface": surface,
                "disposition": disposition,
                "fail_closed": fail_closed,
                "target_axis": target_axis,
                "labels": MappingProxyType(resolved),
            }
        elif disposition == "multi_axis":
            resolved_multi: dict[str, Mapping[str, Enum]] = {}
            for legacy_label, target in labels.items():
                field_map = _parse_multi_axis_target(target)
                typed: dict[str, Enum] = {}
                for axis_name, axis_value in field_map.items():
                    typed[axis_name] = CANONICAL_AXIS_TYPES[axis_name](axis_value)
                resolved_multi[legacy_label] = MappingProxyType(typed)
            surfaces[surface] = {
                "surface": surface,
                "disposition": disposition,
                "fail_closed": fail_closed,
                "target_axis": None,
                "labels": MappingProxyType(resolved_multi),
            }
        elif disposition in {"reject_merge", "operational_only"}:
            if labels:
                raise LegacyAxisMapError(
                    f"surface {surface!r} disposition {disposition} must not "
                    f"declare label maps; got {sorted(labels)!r}"
                )
            surfaces[surface] = {
                "surface": surface,
                "disposition": disposition,
                "fail_closed": fail_closed,
                "target_axis": None,
                "labels": MappingProxyType({}),
            }
        else:
            raise LegacyAxisMapError(
                f"surface {surface!r} has unknown disposition {disposition!r}"
            )
    return surfaces


def load_legacy_axis_maps(
    note_path: Path | None = None,
) -> Mapping[str, Mapping[str, Any]]:
    path = note_path if note_path is not None else _mappings_note_path()
    text = path.read_text(encoding="utf-8")
    return MappingProxyType(parse_legacy_map_blocks(text))


# ---------------------------------------------------------------------------
# Fail-closed mappers
# ---------------------------------------------------------------------------


def map_legacy_label(surface: str, label: object) -> Enum:
    """Map a single-axis legacy label, failing closed on unknowns."""

    maps = load_legacy_axis_maps()
    if surface not in maps:
        raise LegacyAxisMapError(f"unknown legacy surface {surface!r}")
    record = maps[surface]
    disposition = record["disposition"]
    if disposition == "reject_merge":
        raise LegacyAxisMapError(
            f"surface {surface!r} is reject_merge; cannot map as a logic axis"
        )
    if disposition == "operational_only":
        raise LegacyAxisMapError(
            f"surface {surface!r} is operational_only; not a logic axis label"
        )
    if disposition == "multi_axis":
        raise LegacyAxisMapError(
            f"surface {surface!r} is multi_axis; use map_legacy_multi_axis"
        )
    key = _label_value(label)
    labels: Mapping[str, Enum] = record["labels"]
    if key not in labels:
        allowed = ", ".join(sorted(labels))
        raise LegacyAxisMapError(
            f"unknown label {key!r} for surface {surface!r}; "
            f"allowed: {allowed}"
        )
    return labels[key]


def map_legacy_multi_axis(
    surface: str, label: object
) -> Mapping[str, Enum]:
    """Map an overlapping composite label onto independent axis fields."""

    maps = load_legacy_axis_maps()
    if surface not in maps:
        raise LegacyAxisMapError(f"unknown legacy surface {surface!r}")
    record = maps[surface]
    if record["disposition"] != "multi_axis":
        raise LegacyAxisMapError(
            f"surface {surface!r} is not multi_axis; use map_legacy_label"
        )
    key = _label_value(label)
    labels: Mapping[str, Mapping[str, Enum]] = record["labels"]
    if key not in labels:
        allowed = ", ".join(sorted(labels))
        raise LegacyAxisMapError(
            f"unknown label {key!r} for surface {surface!r}; "
            f"allowed: {allowed}"
        )
    return labels[key]


def assert_surface_fail_closed(surface: str, unknown: str = "__not_a_legacy_label__") -> None:
    maps = load_legacy_axis_maps()
    record = maps[surface]
    disposition = record["disposition"]
    if disposition in {"reject_merge", "operational_only"}:
        with pytest.raises(LegacyAxisMapError):
            map_legacy_label(surface, unknown)
        return
    if disposition == "multi_axis":
        with pytest.raises(LegacyAxisMapError):
            map_legacy_multi_axis(surface, unknown)
        return
    with pytest.raises(LegacyAxisMapError):
        map_legacy_label(surface, unknown)


# ---------------------------------------------------------------------------
# Live enum fixtures (import when present)
# ---------------------------------------------------------------------------


def _enum_values(enum_type: type[Enum]) -> set[str]:
    return {member.value for member in enum_type}


def _optional_import_enum(module_path: str, name: str) -> type[Enum] | None:
    try:
        module = __import__(module_path, fromlist=[name])
    except Exception:
        return None
    return getattr(module, name, None)


LIVE_ENUM_CHECKS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "supervisor.AttemptStatus",
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "AttemptStatus",
    ),
    (
        "datasets.ir_core.AttemptStatus",
        "ipfs_datasets_py.logic.ir_core.protocols",
        "AttemptStatus",
    ),
    (
        "supervisor.ProofVerdict",
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "ProofVerdict",
    ),
    (
        "datasets.ir_core.ResultStatus",
        "ipfs_datasets_py.logic.ir_core.protocols",
        "ResultStatus",
    ),
    (
        "datasets.VerificationStatus",
        "ipfs_datasets_py.logic.verification_api",
        "VerificationStatus",
    ),
    (
        "datasets.FeatureAvailability",
        "ipfs_datasets_py.logic.verification_api",
        "FeatureAvailability",
    ),
    (
        "datasets.AvailabilityStatus",
        "ipfs_datasets_py.logic.conformance.matrix",
        "AvailabilityStatus",
    ),
    (
        "supervisor.SupportStatus",
        "ipfs_accelerate_py.agent_supervisor.proof.program_contracts",
        "SupportStatus",
    ),
    (
        "families.EvidenceKind",
        "ipfs_datasets_py.logic.families.models",
        "EvidenceKind",
    ),
    (
        "supervisor.EvidenceKind",
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "EvidenceKind",
    ),
    (
        "datasets.ir_core.EvidenceKind",
        "ipfs_datasets_py.logic.ir_core.evidence",
        "EvidenceKind",
    ),
    (
        "families.EvidenceAuthority",
        "ipfs_datasets_py.logic.families.models",
        "EvidenceAuthority",
    ),
    (
        "supervisor.EvidenceAuthority",
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "EvidenceAuthority",
    ),
    (
        "supervisor.AssuranceLevel",
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "AssuranceLevel",
    ),
    (
        "families.BoundednessKind",
        "ipfs_datasets_py.logic.families.models",
        "BoundednessKind",
    ),
    (
        "families.TranslationKind",
        "ipfs_datasets_py.logic.families.models",
        "TranslationKind",
    ),
    (
        "families.PreservationKind",
        "ipfs_datasets_py.logic.translations.family_extensions",
        "PreservationKind",
    ),
    (
        "supervisor.TranslationClass",
        "ipfs_accelerate_py.agent_supervisor.proof.logic_translation_validation",
        "TranslationClass",
    ),
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mappings_note_exists_and_declares_schema() -> None:
    note_path = _mappings_note_path()
    assert note_path.is_file(), f"missing legacy enum mappings note at {note_path}"
    text = note_path.read_text(encoding="utf-8")
    assert "logic-legacy-axis-map/v1" in text
    assert "LPC-031" in text
    assert "fail closed" in text.lower() or "fail-closed" in text.lower()
    assert "LogicOperationStatus" in text
    assert "LogicSemanticVerdict" in text
    assert "LogicEvidenceAuthority" in text


def test_every_required_surface_has_explicit_map_block() -> None:
    maps = load_legacy_axis_maps()
    assert set(maps) == set(REQUIRED_SURFACES)
    for surface in REQUIRED_SURFACES:
        record = maps[surface]
        assert record["fail_closed"] is True
        assert record["disposition"] in {
            "map",
            "multi_axis",
            "reject_merge",
            "operational_only",
        }


def test_reject_merge_and_operational_surfaces_are_classified() -> None:
    maps = load_legacy_axis_maps()
    for surface in REJECT_MERGE_SURFACES:
        assert maps[surface]["disposition"] == "reject_merge"
        assert maps[surface]["labels"] == {}
    for surface in OPERATIONAL_ONLY_SURFACES:
        assert maps[surface]["disposition"] == "operational_only"
        assert maps[surface]["labels"] == {}


def test_single_axis_maps_cover_non_empty_labels() -> None:
    maps = load_legacy_axis_maps()
    for surface, record in maps.items():
        if record["disposition"] != "map":
            continue
        labels = record["labels"]
        assert labels, f"{surface} must declare at least one label"
        target_axis = record["target_axis"]
        axis_type = CANONICAL_AXIS_TYPES[target_axis]
        for legacy_label, member in labels.items():
            assert isinstance(legacy_label, str) and legacy_label
            assert isinstance(member, axis_type)
            assert map_legacy_label(surface, legacy_label) is member
            assert map_legacy_label(surface, legacy_label).value == member.value
            # Wire-value identity: when the legacy label equals the canonical
            # value, the same string is accepted as the lookup key.
            if legacy_label == member.value:
                assert map_legacy_label(surface, member.value) is member


def test_multi_axis_verification_status_split() -> None:
    mapped = map_legacy_multi_axis("datasets.VerificationStatus", "succeeded")
    assert mapped["operation_status"] is LogicOperationStatus.SUCCEEDED
    assert mapped["availability"] is LogicAvailability.AVAILABLE
    assert mapped["semantic_verdict"] is LogicSemanticVerdict.UNKNOWN
    # Success never promotes authority; multi-axis map does not emit authority.
    assert "evidence_authority" not in mapped

    partial = map_legacy_multi_axis("datasets.VerificationStatus", "partial")
    assert partial["operation_status"] is LogicOperationStatus.PARTIAL
    assert partial["semantic_verdict"] is LogicSemanticVerdict.UNKNOWN

    unsupported = map_legacy_multi_axis(
        "datasets.VerificationStatus", "unsupported"
    )
    assert unsupported["operation_status"] is LogicOperationStatus.UNSUPPORTED
    assert unsupported["availability"] is LogicAvailability.UNSUPPORTED


def test_unknown_labels_fail_closed_for_every_surface() -> None:
    maps = load_legacy_axis_maps()
    for surface in maps:
        assert_surface_fail_closed(surface)
        assert_surface_fail_closed(surface, "")
        assert_surface_fail_closed(surface, "   ")
        assert_surface_fail_closed(surface, "totally-unknown-label-xyz")


def test_unknown_surface_fails_closed() -> None:
    with pytest.raises(LegacyAxisMapError):
        map_legacy_label("not.a.surface", "succeeded")
    with pytest.raises(LegacyAxisMapError):
        map_legacy_multi_axis("not.a.surface", "succeeded")


def test_reject_merge_surfaces_never_map_known_looking_labels() -> None:
    # Even labels that look like logic authority must not project.
    for surface in REJECT_MERGE_SURFACES:
        for label in (
            "proof",
            "authoritative",
            "kernel_checked_proof",
            "diagnostic",
            "prompt",
        ):
            with pytest.raises(LegacyAxisMapError):
                map_legacy_label(surface, label)


def test_resource_budget_is_operational_only() -> None:
    with pytest.raises(LegacyAxisMapError):
        map_legacy_label("supervisor.ResourceBudget", "wall_time_ms")
    with pytest.raises(LegacyAxisMapError):
        map_legacy_label("supervisor.ResourceBudget", "resource_bounded")


def test_succeeded_does_not_map_to_proof_or_authority() -> None:
    status = map_legacy_label("supervisor.AttemptStatus", "succeeded")
    assert status is LogicOperationStatus.SUCCEEDED
    assert status is not LogicSemanticVerdict.PROVED
    assert status.value != LogicEvidenceAuthority.AUTHORITATIVE.value

    multi = map_legacy_multi_axis("datasets.VerificationStatus", "succeeded")
    assert multi["semantic_verdict"] is LogicSemanticVerdict.UNKNOWN
    assert multi["operation_status"] is LogicOperationStatus.SUCCEEDED


def test_supervisor_attempt_status_mapping() -> None:
    expected = {
        "planned": LogicOperationStatus.PLANNED,
        "running": LogicOperationStatus.RUNNING,
        "succeeded": LogicOperationStatus.SUCCEEDED,
        "failed": LogicOperationStatus.FAILED,
        "unsupported": LogicOperationStatus.UNSUPPORTED,
        "unavailable": LogicOperationStatus.UNAVAILABLE,
        "timed_out": LogicOperationStatus.TIMED_OUT,
        "cancelled": LogicOperationStatus.CANCELLED,
        "blocked": LogicOperationStatus.BLOCKED,
    }
    for label, member in expected.items():
        assert map_legacy_label("supervisor.AttemptStatus", label) is member


def test_supervisor_proof_verdict_mapping() -> None:
    expected = {
        "proved": LogicSemanticVerdict.PROVED,
        "disproved": LogicSemanticVerdict.DISPROVED,
        "inconclusive": LogicSemanticVerdict.INCONCLUSIVE,
        "unsupported": LogicSemanticVerdict.UNSUPPORTED,
        "error": LogicSemanticVerdict.ERROR,
        "cancelled": LogicSemanticVerdict.CANCELLED,
    }
    for label, member in expected.items():
        assert map_legacy_label("supervisor.ProofVerdict", label) is member


def test_supervisor_evidence_kind_and_authority_mappings() -> None:
    assert (
        map_legacy_label("supervisor.EvidenceKind", "kernel_verification")
        is LogicEvidenceKind.KERNEL_CHECKED_PROOF
    )
    assert (
        map_legacy_label("supervisor.EvidenceKind", "cryptographic_attestation")
        is LogicEvidenceKind.ATTESTATION
    )
    assert (
        map_legacy_label("supervisor.EvidenceKind", "llm_output")
        is LogicEvidenceKind.LLM_OUTPUT
    )
    # Kind map never yields an authority member.
    kind = map_legacy_label("supervisor.EvidenceKind", "solver_result")
    assert not isinstance(kind, LogicEvidenceAuthority)

    assert (
        map_legacy_label("supervisor.EvidenceAuthority", "kernel")
        is LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )
    assert (
        map_legacy_label("supervisor.EvidenceAuthority", "llm")
        is LogicEvidenceAuthority.ADVISORY
    )
    assert (
        map_legacy_label("supervisor.EvidenceAuthority", "cache")
        is LogicEvidenceAuthority.NONE
    )
    # Boundary name "kernel" is not automatic authoritative ceiling.
    assert (
        map_legacy_label("supervisor.EvidenceAuthority", "kernel")
        is not LogicEvidenceAuthority.AUTHORITATIVE
    )


def test_assurance_level_maps_to_authority_ceiling() -> None:
    expected = {
        "unverified": LogicEvidenceAuthority.NONE,
        "candidate": LogicEvidenceAuthority.ADVISORY,
        "solver_checked": LogicEvidenceAuthority.BOUNDED,
        "kernel_verified": LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "attested": LogicEvidenceAuthority.AUTHORITATIVE,
    }
    for label, member in expected.items():
        assert map_legacy_label("supervisor.AssuranceLevel", label) is member


def test_translation_and_boundedness_maps() -> None:
    assert (
        map_legacy_label("supervisor.TranslationClass", "exact")
        is LogicTranslationPreservation.EXACT
    )
    assert (
        map_legacy_label("supervisor.TranslationClass", "bounded_abstraction")
        is LogicTranslationPreservation.BOUNDED_ABSTRACTION
    )
    assert (
        map_legacy_label("families.PreservationKind", "bounded")
        is LogicTranslationPreservation.BOUNDED_ABSTRACTION
    )
    assert (
        map_legacy_label("families.BoundednessKind", "finite_trace")
        is LogicBoundedness.FINITE_TRACE
    )
    assert (
        map_legacy_label("parsers.BoundednessKind", "finite_state")
        is LogicBoundedness.FINITE_DOMAIN
    )
    assert (
        map_legacy_label("parsers.BoundednessKind", "bounded_unrolling")
        is LogicBoundedness.STEP_BOUNDED
    )


def test_availability_maps() -> None:
    assert (
        map_legacy_label("datasets.FeatureAvailability", "opt_in")
        is LogicAvailability.OPT_IN
    )
    assert (
        map_legacy_label("datasets.AvailabilityStatus", "not_declared")
        is LogicAvailability.ABSENT
    )
    assert (
        map_legacy_label("datasets.AvailabilityStatus", "source_missing")
        is LogicAvailability.SOURCE_MISSING
    )
    assert (
        map_legacy_label("supervisor.SupportStatus", "supported")
        is LogicAvailability.AVAILABLE
    )
    assert (
        map_legacy_label("supervisor.SupportStatus", "assumed")
        is LogicAvailability.DECLARED
    )


def test_live_enums_are_exhaustively_covered_when_importable() -> None:
    maps = load_legacy_axis_maps()
    checked = 0
    for surface, module_path, enum_name in LIVE_ENUM_CHECKS:
        enum_type = _optional_import_enum(module_path, enum_name)
        if enum_type is None:
            continue
        checked += 1
        live_values = _enum_values(enum_type)
        record = maps[surface]
        if record["disposition"] in {"reject_merge", "operational_only"}:
            continue
        mapped_labels = set(record["labels"])
        missing = live_values - mapped_labels
        assert not missing, (
            f"{surface} missing explicit maps for live labels: {sorted(missing)}"
        )
        # Every mapped label must resolve without error.
        for label in live_values:
            if record["disposition"] == "multi_axis":
                result = map_legacy_multi_axis(surface, label)
                assert result
            else:
                member = map_legacy_label(surface, label)
                assert isinstance(member, Enum)
    assert checked >= 10, "expected most live inventoried enums to be importable"


def test_note_documents_non_inference_and_inventory_language() -> None:
    text = _mappings_note_path().read_text(encoding="utf-8")
    for needle in (
        "supervisor.AttemptStatus",
        "supervisor.ProofVerdict",
        "datasets.VerificationStatus",
        "supervisor.EvidenceAuthority",
        "goal_quality.EvidenceAuthority",
        "supervisor.ResourceBudget",
        "reject_merge",
        "operational_only",
        "does **not** imply",
    ):
        assert needle in text


def test_map_legacy_label_rejects_wrong_helper_for_multi_axis() -> None:
    with pytest.raises(LegacyAxisMapError):
        map_legacy_label("datasets.VerificationStatus", "succeeded")
    with pytest.raises(LegacyAxisMapError):
        map_legacy_multi_axis("supervisor.AttemptStatus", "succeeded")


def test_legacy_axis_map_error_is_axis_validation_error() -> None:
    with pytest.raises(AxisValidationError):
        map_legacy_label("supervisor.AttemptStatus", "not-real")
    with pytest.raises(LegacyAxisMapError):
        map_legacy_label("supervisor.AttemptStatus", "not-real")
