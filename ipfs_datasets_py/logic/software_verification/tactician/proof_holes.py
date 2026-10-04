"""Typed proof-hole emission for VC and model compilation (``TypedProofHoleEmitter@1``).

FVT-G030 / FVT-012: VC and model compilation must return *source-bound typed
holes* when required proof material is absent, rather than inventing default
invariants, contracts, or frames, and rather than collapsing every gap into a
generic failure.

This module owns the hole-emission adapter that sits between:

* closed :class:`~ipfs_datasets_py.logic.software_verification.tactician.contracts.ProofHole`
  wire contracts (FVT-G021), and
* focused VC / model-compilation surfaces that declare what is required versus
  what is annotated.

Program invariants:

* fail closed — missing material becomes an open hole; it is never silently
  discharged;
* never invent default invariants, contracts, frames, fairness premises, or
  bridge lemmas;
* unsupported language/logic semantics and unavailable tools remain distinct
  non-success states from missing-proof holes;
* every hole carries a source span, rationale, dependency ids, expected
  authority ceiling, and a machine-readable validation recipe; and
* holes never claim proof or completion authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    PROOF_HOLE_INTERFACE,
    AuthorityCeiling,
    HoleKind,
    HoleStatus,
    ProofHole,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    ValidationRecipe,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface and schema constants
# ---------------------------------------------------------------------------

TYPED_PROOF_HOLE_EMITTER_INTERFACE: Final = "TypedProofHoleEmitter@1"
PROOF_HOLE_EMISSION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-hole-emission@1"
)
COMPILATION_SURFACE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/compilation-surface@1"
)
ANNOTATION_SITE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/annotation-site@1"
)
EMITTER_ALGORITHM_VERSION: Final = "typed-proof-hole-emitter/1.0.0"

DEFAULT_PROVIDER_IDS: Final[tuple[str, ...]] = ("provider:z3",)
DEFAULT_BOUNDS: Final = ResourceBounds(
    wall_time_ms=30_000,
    memory_bytes=256 * 1024 * 1024,
    max_steps=64,
    max_depth=16,
    max_nodes=128,
    max_candidates=32,
    network_allowed=False,
)


class ProofHoleEmissionError(ValueError):
    """Raised when hole emission inputs are malformed or unsafe."""


class AnnotationRole(StrEnum):
    """Roles of proof material that compilation may require at a site."""

    LOOP_INVARIANT = "loop_invariant"
    LOOP_VARIANT = "loop_variant"
    CALLEE_PRECONDITION = "callee_precondition"
    CALLEE_POSTCONDITION = "callee_postcondition"
    EXCEPTIONAL_CONTRACT = "exceptional_contract"
    FUNCTION_SUMMARY = "function_summary"
    FRAME = "frame"
    ALIAS = "alias"
    OWNERSHIP = "ownership"
    SEPARATION = "separation"
    RELY_GUARANTEE = "rely_guarantee"
    LINEARIZATION = "linearization"
    STATE_INVARIANT = "state_invariant"
    REFINEMENT_MAPPING = "refinement_mapping"
    TEMPORAL_FAIRNESS = "temporal_fairness"
    TEMPORAL_PROGRESS = "temporal_progress"
    PROTOCOL_TRUST = "protocol_trust"
    PROTOCOL_FRESHNESS = "protocol_freshness"
    PROTOCOL_SECRECY = "protocol_secrecy"
    PROTOCOL_AUTHENTICATION = "protocol_authentication"
    INFORMATION_FLOW = "information_flow"
    OBSERVATION_POLICY = "observation_policy"
    BRIDGE_LEMMA = "bridge_lemma"
    TRANSLATION_PRESERVATION = "translation_preservation"
    MISSING_SOURCE_FACT = "missing_source_fact"
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    UNAVAILABLE_TOOL = "unavailable_tool"
    UNAVAILABLE_RECONSTRUCTION = "unavailable_reconstruction"
    REQUIRED_IMPLEMENTATION_CHANGE = "required_implementation_change"


class SiteKind(StrEnum):
    """Source construct kind that hosts required annotations."""

    LOOP = "loop"
    CALL = "call"
    FUNCTION = "function"
    FRAME = "frame"
    TEMPORAL = "temporal"
    CONCURRENCY = "concurrency"
    REFINEMENT = "refinement"
    PROTOCOL = "protocol"
    BRIDGE = "bridge"
    TRANSLATION = "translation"
    EVIDENCE = "evidence"
    SEMANTICS = "semantics"
    TOOL = "tool"
    IMPLEMENTATION = "implementation"
    OTHER = "other"


# Map annotation roles to ProofHole@1 kinds (identity for the closed set).
_ROLE_TO_HOLE_KIND: Final[Mapping[AnnotationRole, HoleKind]] = {
    AnnotationRole.LOOP_INVARIANT: HoleKind.LOOP_INVARIANT,
    AnnotationRole.LOOP_VARIANT: HoleKind.LOOP_VARIANT,
    AnnotationRole.CALLEE_PRECONDITION: HoleKind.CALLEE_PRECONDITION,
    AnnotationRole.CALLEE_POSTCONDITION: HoleKind.CALLEE_POSTCONDITION,
    AnnotationRole.EXCEPTIONAL_CONTRACT: HoleKind.EXCEPTIONAL_CONTRACT,
    AnnotationRole.FUNCTION_SUMMARY: HoleKind.FUNCTION_SUMMARY,
    AnnotationRole.FRAME: HoleKind.FRAME,
    AnnotationRole.ALIAS: HoleKind.ALIAS,
    AnnotationRole.OWNERSHIP: HoleKind.OWNERSHIP,
    AnnotationRole.SEPARATION: HoleKind.SEPARATION,
    AnnotationRole.RELY_GUARANTEE: HoleKind.RELY_GUARANTEE,
    AnnotationRole.LINEARIZATION: HoleKind.LINEARIZATION,
    AnnotationRole.STATE_INVARIANT: HoleKind.STATE_INVARIANT,
    AnnotationRole.REFINEMENT_MAPPING: HoleKind.REFINEMENT_MAPPING,
    AnnotationRole.TEMPORAL_FAIRNESS: HoleKind.TEMPORAL_FAIRNESS,
    AnnotationRole.TEMPORAL_PROGRESS: HoleKind.TEMPORAL_PROGRESS,
    AnnotationRole.PROTOCOL_TRUST: HoleKind.PROTOCOL_TRUST,
    AnnotationRole.PROTOCOL_FRESHNESS: HoleKind.PROTOCOL_FRESHNESS,
    AnnotationRole.PROTOCOL_SECRECY: HoleKind.PROTOCOL_SECRECY,
    AnnotationRole.PROTOCOL_AUTHENTICATION: HoleKind.PROTOCOL_AUTHENTICATION,
    AnnotationRole.INFORMATION_FLOW: HoleKind.INFORMATION_FLOW,
    AnnotationRole.OBSERVATION_POLICY: HoleKind.OBSERVATION_POLICY,
    AnnotationRole.BRIDGE_LEMMA: HoleKind.BRIDGE_LEMMA,
    AnnotationRole.TRANSLATION_PRESERVATION: HoleKind.TRANSLATION_PRESERVATION,
    AnnotationRole.MISSING_SOURCE_FACT: HoleKind.MISSING_SOURCE_FACT,
    AnnotationRole.MISSING_EVIDENCE: HoleKind.MISSING_EVIDENCE,
    AnnotationRole.UNSUPPORTED_SEMANTICS: HoleKind.UNSUPPORTED_SEMANTICS,
    AnnotationRole.UNAVAILABLE_TOOL: HoleKind.UNAVAILABLE_TOOL,
    AnnotationRole.UNAVAILABLE_RECONSTRUCTION: HoleKind.UNAVAILABLE_RECONSTRUCTION,
    AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE: (
        HoleKind.REQUIRED_IMPLEMENTATION_CHANGE
    ),
}

# Roles that represent non-proof gaps (semantics / tools / false goals).
_NON_PROOF_ROLES: Final[frozenset[AnnotationRole]] = frozenset(
    {
        AnnotationRole.UNSUPPORTED_SEMANTICS,
        AnnotationRole.UNAVAILABLE_TOOL,
        AnnotationRole.UNAVAILABLE_RECONSTRUCTION,
        AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE,
    }
)

_ROLE_PROPERTY_CLASS: Final[Mapping[AnnotationRole, PropertyClass]] = {
    AnnotationRole.LOOP_INVARIANT: PropertyClass.INVARIANCE,
    AnnotationRole.LOOP_VARIANT: PropertyClass.TERMINATION,
    AnnotationRole.CALLEE_PRECONDITION: PropertyClass.CONTRACT,
    AnnotationRole.CALLEE_POSTCONDITION: PropertyClass.CONTRACT,
    AnnotationRole.EXCEPTIONAL_CONTRACT: PropertyClass.CONTRACT,
    AnnotationRole.FUNCTION_SUMMARY: PropertyClass.CONTRACT,
    AnnotationRole.FRAME: PropertyClass.CONTRACT,
    AnnotationRole.STATE_INVARIANT: PropertyClass.INVARIANCE,
    AnnotationRole.REFINEMENT_MAPPING: PropertyClass.REFINEMENT,
    AnnotationRole.TEMPORAL_FAIRNESS: PropertyClass.LIVENESS,
    AnnotationRole.TEMPORAL_PROGRESS: PropertyClass.LIVENESS,
    AnnotationRole.RELY_GUARANTEE: PropertyClass.PROTOCOL,
    AnnotationRole.LINEARIZATION: PropertyClass.PROTOCOL,
    AnnotationRole.PROTOCOL_TRUST: PropertyClass.PROTOCOL,
    AnnotationRole.PROTOCOL_FRESHNESS: PropertyClass.PROTOCOL,
    AnnotationRole.PROTOCOL_SECRECY: PropertyClass.PROTOCOL,
    AnnotationRole.PROTOCOL_AUTHENTICATION: PropertyClass.PROTOCOL,
    AnnotationRole.INFORMATION_FLOW: PropertyClass.HYPERPROPERTY,
    AnnotationRole.OBSERVATION_POLICY: PropertyClass.HYPERPROPERTY,
    AnnotationRole.BRIDGE_LEMMA: PropertyClass.THEOREM,
    AnnotationRole.TRANSLATION_PRESERVATION: PropertyClass.THEOREM,
}

_ROLE_AUTHORITY: Final[Mapping[AnnotationRole, AuthorityCeiling]] = {
    AnnotationRole.LOOP_INVARIANT: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.LOOP_VARIANT: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.CALLEE_PRECONDITION: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.CALLEE_POSTCONDITION: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.EXCEPTIONAL_CONTRACT: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.FUNCTION_SUMMARY: AuthorityCeiling.BOUNDED,
    AnnotationRole.FRAME: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.ALIAS: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.OWNERSHIP: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.SEPARATION: AuthorityCeiling.SATISFIABILITY,
    AnnotationRole.RELY_GUARANTEE: AuthorityCeiling.MODEL_CHECK,
    AnnotationRole.LINEARIZATION: AuthorityCeiling.MODEL_CHECK,
    AnnotationRole.STATE_INVARIANT: AuthorityCeiling.MODEL_CHECK,
    AnnotationRole.REFINEMENT_MAPPING: AuthorityCeiling.THEOREM,
    AnnotationRole.TEMPORAL_FAIRNESS: AuthorityCeiling.MODEL_CHECK,
    AnnotationRole.TEMPORAL_PROGRESS: AuthorityCeiling.MODEL_CHECK,
    AnnotationRole.PROTOCOL_TRUST: AuthorityCeiling.PROTOCOL,
    AnnotationRole.PROTOCOL_FRESHNESS: AuthorityCeiling.PROTOCOL,
    AnnotationRole.PROTOCOL_SECRECY: AuthorityCeiling.PROTOCOL,
    AnnotationRole.PROTOCOL_AUTHENTICATION: AuthorityCeiling.PROTOCOL,
    AnnotationRole.INFORMATION_FLOW: AuthorityCeiling.HYPERPROPERTY,
    AnnotationRole.OBSERVATION_POLICY: AuthorityCeiling.HYPERPROPERTY,
    AnnotationRole.BRIDGE_LEMMA: AuthorityCeiling.THEOREM,
    AnnotationRole.TRANSLATION_PRESERVATION: AuthorityCeiling.THEOREM,
    AnnotationRole.MISSING_SOURCE_FACT: AuthorityCeiling.DECLARATIVE,
    AnnotationRole.MISSING_EVIDENCE: AuthorityCeiling.ATTESTATION,
    AnnotationRole.UNSUPPORTED_SEMANTICS: AuthorityCeiling.NONE,
    AnnotationRole.UNAVAILABLE_TOOL: AuthorityCeiling.NONE,
    AnnotationRole.UNAVAILABLE_RECONSTRUCTION: AuthorityCeiling.NONE,
    AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE: AuthorityCeiling.NONE,
}

_ROLE_CHECKER: Final[Mapping[AnnotationRole, str]] = {
    AnnotationRole.LOOP_INVARIANT: "smt_invariant_check",
    AnnotationRole.LOOP_VARIANT: "smt_variant_check",
    AnnotationRole.CALLEE_PRECONDITION: "smt_precondition_check",
    AnnotationRole.CALLEE_POSTCONDITION: "smt_postcondition_check",
    AnnotationRole.EXCEPTIONAL_CONTRACT: "smt_exceptional_check",
    AnnotationRole.FUNCTION_SUMMARY: "summary_soundness_check",
    AnnotationRole.FRAME: "smt_frame_check",
    AnnotationRole.ALIAS: "alias_analysis_check",
    AnnotationRole.OWNERSHIP: "ownership_check",
    AnnotationRole.SEPARATION: "separation_logic_check",
    AnnotationRole.RELY_GUARANTEE: "rely_guarantee_check",
    AnnotationRole.LINEARIZATION: "linearizability_check",
    AnnotationRole.STATE_INVARIANT: "model_check_invariant",
    AnnotationRole.REFINEMENT_MAPPING: "refinement_check",
    AnnotationRole.TEMPORAL_FAIRNESS: "temporal_fairness_check",
    AnnotationRole.TEMPORAL_PROGRESS: "temporal_progress_check",
    AnnotationRole.PROTOCOL_TRUST: "protocol_trust_check",
    AnnotationRole.PROTOCOL_FRESHNESS: "protocol_freshness_check",
    AnnotationRole.PROTOCOL_SECRECY: "protocol_secrecy_check",
    AnnotationRole.PROTOCOL_AUTHENTICATION: "protocol_authentication_check",
    AnnotationRole.INFORMATION_FLOW: "information_flow_check",
    AnnotationRole.OBSERVATION_POLICY: "observation_policy_check",
    AnnotationRole.BRIDGE_LEMMA: "kernel_bridge_lemma_check",
    AnnotationRole.TRANSLATION_PRESERVATION: "translation_preservation_check",
    AnnotationRole.MISSING_SOURCE_FACT: "source_fact_presence_check",
    AnnotationRole.MISSING_EVIDENCE: "evidence_receipt_check",
    AnnotationRole.UNSUPPORTED_SEMANTICS: "semantics_support_probe",
    AnnotationRole.UNAVAILABLE_TOOL: "tool_availability_probe",
    AnnotationRole.UNAVAILABLE_RECONSTRUCTION: "reconstruction_probe",
    AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE: (
        "implementation_conformance_check"
    ),
}

_ROLE_RECIPE_STEPS: Final[Mapping[AnnotationRole, tuple[str, ...]]] = {
    AnnotationRole.LOOP_INVARIANT: (
        "bind_source_span",
        "propose_or_retrieve_invariant",
        "typecheck_candidate",
        "check_init",
        "check_preserve",
        "record_receipt",
    ),
    AnnotationRole.LOOP_VARIANT: (
        "bind_source_span",
        "propose_or_retrieve_variant",
        "check_decrease",
        "check_well_founded",
        "record_receipt",
    ),
    AnnotationRole.CALLEE_PRECONDITION: (
        "bind_call_site",
        "retrieve_or_synthesize_precondition",
        "check_at_call",
        "record_receipt",
    ),
    AnnotationRole.CALLEE_POSTCONDITION: (
        "bind_call_site",
        "retrieve_or_synthesize_postcondition",
        "check_after_return",
        "record_receipt",
    ),
    AnnotationRole.FRAME: (
        "bind_modifies_set",
        "check_unframed_writes",
        "record_receipt",
    ),
    AnnotationRole.TEMPORAL_FAIRNESS: (
        "bind_fairness_premise",
        "model_check_under_fairness",
        "record_receipt",
    ),
    AnnotationRole.BRIDGE_LEMMA: (
        "bind_bridge_sites",
        "typecheck_lemma",
        "kernel_check",
        "record_receipt",
    ),
    AnnotationRole.UNSUPPORTED_SEMANTICS: (
        "classify_construct",
        "report_unsupported",
        "do_not_discharge",
    ),
    AnnotationRole.UNAVAILABLE_TOOL: (
        "probe_tool",
        "report_unavailable",
        "do_not_discharge",
    ),
    AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE: (
        "confirm_goal_false_of_program",
        "emit_required_change",
        "do_not_invent_proof",
    ),
}


def _text(value: object, label: str, *, optional: bool = False, maximum: int = 4096) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise ProofHoleEmissionError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise ProofHoleEmissionError(f"{label} must not contain NUL")
    if not optional and not text:
        raise ProofHoleEmissionError(f"{label} is required")
    if len(text) > maximum:
        raise ProofHoleEmissionError(f"{label} exceeds maximum length of {maximum}")
    return text


def _enum(value: object, enum_type: type[StrEnum], label: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip())
        except ValueError as error:
            raise ProofHoleEmissionError(
                f"{label} must be a valid {enum_type.__name__}"
            ) from error
    raise ProofHoleEmissionError(f"{label} must be a {enum_type.__name__}")


def _string_tuple(
    values: Sequence[str] | None,
    label: str,
    *,
    preserve_order: bool = True,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ProofHoleEmissionError(f"{label} must be a sequence of strings")
    items: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        text = _text(raw, f"{label}[{index}]", maximum=512)
        if text in seen:
            continue
        seen.add(text)
        items.append(text)
    if not preserve_order:
        items = sorted(items)
    return tuple(items)


def _role_set(values: Sequence[AnnotationRole | str] | None, label: str) -> frozenset[AnnotationRole]:
    if values is None:
        return frozenset()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ProofHoleEmissionError(f"{label} must be a sequence of annotation roles")
    roles: set[AnnotationRole] = set()
    for index, raw in enumerate(values):
        roles.add(_enum(raw, AnnotationRole, f"{label}[{index}]"))
    return frozenset(roles)


def _source_binding(value: object, label: str = "source") -> SourceSpanBinding:
    if isinstance(value, SourceSpanBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return SourceSpanBinding.from_dict(value)
        except TacticianContractError as error:
            raise ProofHoleEmissionError(f"{label}: {error}") from error
    raise ProofHoleEmissionError(f"{label} must be a SourceSpanBinding")


def _stable_hole_id(*parts: str) -> str:
    digest = hashlib.sha256(
        "|".join(parts).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"hole:{parts[0]}:{digest}"


def default_validation_recipe(
    role: AnnotationRole | str,
    *,
    site_id: str = "",
    provider_ids: Sequence[str] | None = None,
    bounds: ResourceBounds | None = None,
) -> ValidationRecipe:
    """Return the canonical validation recipe for an annotation role."""

    resolved = _enum(role, AnnotationRole, "role")
    providers = tuple(provider_ids) if provider_ids else DEFAULT_PROVIDER_IDS
    authority = _ROLE_AUTHORITY.get(resolved, AuthorityCeiling.CANDIDATE)
    checker = _ROLE_CHECKER.get(resolved, "generic_hole_check")
    steps = _ROLE_RECIPE_STEPS.get(
        resolved,
        ("bind_source_span", "synthesize_candidate", "validate", "record_receipt"),
    )
    recipe_id = f"recipe:{resolved.value}:{site_id or 'site'}"
    return ValidationRecipe(
        recipe_id=recipe_id[:256],
        checker_kind=checker,
        provider_ids=providers,
        required_authority=authority,
        bounds=bounds if bounds is not None else DEFAULT_BOUNDS,
        steps=steps,
        oracle_id=f"oracle:{resolved.value}",
    )


def hole_status_for_role(role: AnnotationRole | str) -> HoleStatus:
    """Map annotation role to hole lifecycle status."""

    resolved = _enum(role, AnnotationRole, "role")
    if resolved is AnnotationRole.UNSUPPORTED_SEMANTICS:
        return HoleStatus.UNSUPPORTED
    if resolved is AnnotationRole.UNAVAILABLE_TOOL:
        return HoleStatus.UNAVAILABLE
    if resolved is AnnotationRole.UNAVAILABLE_RECONSTRUCTION:
        return HoleStatus.UNAVAILABLE
    if resolved is AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE:
        return HoleStatus.FALSE
    return HoleStatus.OPEN


def is_missing_proof_role(role: AnnotationRole | str) -> bool:
    """True when the role represents missing proof material (not semantics/tools)."""

    resolved = _enum(role, AnnotationRole, "role")
    return resolved not in _NON_PROOF_ROLES


# ---------------------------------------------------------------------------
# Compilation surface (required vs annotated proof material)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnnotationSite:
    """One source-bound site that may require typed proof material.

    ``required_roles`` lists material the compiler needs to proceed with a
    proof attempt.  ``present_roles`` lists material that is actually
    annotated.  The emitter never invents entries for ``present_roles``.
    Roles in ``non_proof_roles`` (or required roles that are non-proof) emit
    as unsupported/unavailable/false rather than open missing-proof holes.
    """

    site_id: str
    site_kind: SiteKind
    source: SourceSpanBinding
    required_roles: frozenset[AnnotationRole] = field(default_factory=frozenset)
    present_roles: frozenset[AnnotationRole] = field(default_factory=frozenset)
    dependency_ids: tuple[str, ...] = ()
    statement: str = ""
    rationale: str = ""
    provider_ids: tuple[str, ...] = ()
    formal_goal_id: str = ""
    expected_authority: AuthorityCeiling | None = None
    property_class: PropertyClass | None = None
    bounds: ResourceBounds | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "site_id", _text(self.site_id, "site_id", maximum=256)
        )
        object.__setattr__(
            self, "site_kind", _enum(self.site_kind, SiteKind, "site_kind")
        )
        object.__setattr__(self, "source", _source_binding(self.source, "source"))
        object.__setattr__(
            self,
            "required_roles",
            _role_set(tuple(self.required_roles), "required_roles"),
        )
        object.__setattr__(
            self,
            "present_roles",
            _role_set(tuple(self.present_roles), "present_roles"),
        )
        # present_roles may only mention required roles (or be empty).
        extra = self.present_roles - self.required_roles
        if extra and not self.required_roles:
            # Allow free-standing non-proof diagnostics that list only present
            # unsupported markers via required_roles==present_roles patterns.
            pass
        object.__setattr__(
            self,
            "dependency_ids",
            _string_tuple(self.dependency_ids, "dependency_ids"),
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", optional=True, maximum=8192),
        )
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, "rationale", optional=True, maximum=4096),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", optional=True, maximum=256),
        )
        if self.expected_authority is not None:
            object.__setattr__(
                self,
                "expected_authority",
                _enum(self.expected_authority, AuthorityCeiling, "expected_authority"),
            )
        if self.property_class is not None:
            object.__setattr__(
                self,
                "property_class",
                _enum(self.property_class, PropertyClass, "property_class"),
            )
        if self.bounds is not None and not isinstance(self.bounds, ResourceBounds):
            if isinstance(self.bounds, Mapping):
                object.__setattr__(
                    self, "bounds", ResourceBounds.from_dict(self.bounds)
                )
            else:
                raise ProofHoleEmissionError("bounds must be a ResourceBounds")
        if not isinstance(self.metadata, Mapping):
            raise ProofHoleEmissionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def missing_roles(self) -> frozenset[AnnotationRole]:
        """Roles that are required but not present (candidates for emission)."""

        return frozenset(self.required_roles - self.present_roles)

    def without_roles(self, *roles: AnnotationRole | str) -> "AnnotationSite":
        """Return a copy with the given roles removed from ``present_roles``.

        Used by acceptance tests that remove a loop invariant, frame, fairness
        premise, or bridge lemma and re-emit holes.  Never invents replacements.
        """

        drop = {_enum(role, AnnotationRole, "role") for role in roles}
        remaining = frozenset(r for r in self.present_roles if r not in drop)
        return replace(self, present_roles=remaining)

    def with_required(self, *roles: AnnotationRole | str) -> "AnnotationSite":
        """Return a copy that additionally requires the given roles."""

        extra = {_enum(role, AnnotationRole, "role") for role in roles}
        return replace(self, required_roles=frozenset(self.required_roles | extra))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ANNOTATION_SITE_SCHEMA,
            "site_id": self.site_id,
            "site_kind": self.site_kind.value,
            "source": self.source.to_dict(),
            "required_roles": sorted(role.value for role in self.required_roles),
            "present_roles": sorted(role.value for role in self.present_roles),
            "dependency_ids": list(self.dependency_ids),
            "statement": self.statement,
            "rationale": self.rationale,
            "provider_ids": list(self.provider_ids),
            "formal_goal_id": self.formal_goal_id,
            "expected_authority": (
                None
                if self.expected_authority is None
                else self.expected_authority.value
            ),
            "property_class": (
                None if self.property_class is None else self.property_class.value
            ),
            "bounds": None if self.bounds is None else self.bounds.to_dict(),
            "metadata": dict(self.metadata),
            "missing_roles": sorted(role.value for role in self.missing_roles),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AnnotationSite":
        if not isinstance(payload, Mapping):
            raise ProofHoleEmissionError("annotation site payload must be an object")
        bounds_raw = payload.get("bounds")
        return cls(
            site_id=payload.get("site_id", ""),
            site_kind=payload.get("site_kind", SiteKind.OTHER),
            source=payload.get("source") or {},
            required_roles=tuple(payload.get("required_roles") or ()),
            present_roles=tuple(payload.get("present_roles") or ()),
            dependency_ids=tuple(payload.get("dependency_ids") or ()),
            statement=payload.get("statement", ""),
            rationale=payload.get("rationale", ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            formal_goal_id=payload.get("formal_goal_id", ""),
            expected_authority=payload.get("expected_authority"),
            property_class=payload.get("property_class"),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else bounds_raw
            ),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CompilationSurface:
    """Declarative view of VC / model compilation inputs for hole emission.

    Sites declare required vs present annotations.  The emitter never fills
    missing present roles with defaults.
    """

    surface_id: str
    formal_goal_id: str = ""
    tree_id: str = ""
    sites: tuple[AnnotationSite, ...] = ()
    provider_ids: tuple[str, ...] = ()
    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "surface_id", _text(self.surface_id, "surface_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", optional=True, maximum=256)
        )
        normalized: list[AnnotationSite] = []
        seen: set[str] = set()
        for index, site in enumerate(self.sites):
            if isinstance(site, Mapping):
                site = AnnotationSite.from_dict(site)
            elif not isinstance(site, AnnotationSite):
                raise ProofHoleEmissionError(
                    f"sites[{index}] must be an AnnotationSite"
                )
            if site.site_id in seen:
                raise ProofHoleEmissionError(
                    f"duplicate annotation site id {site.site_id!r}"
                )
            seen.add(site.site_id)
            if self.tree_id and not site.source.tree_id:
                site = replace(
                    site,
                    source=SourceSpanBinding(
                        tree_id=self.tree_id,
                        source_ref_ids=site.source.source_ref_ids,
                        span_ids=site.source.span_ids,
                        ast_scope_ids=site.source.ast_scope_ids,
                        snapshot_id=site.source.snapshot_id,
                    ),
                )
            if self.formal_goal_id and not site.formal_goal_id:
                site = replace(site, formal_goal_id=self.formal_goal_id)
            normalized.append(site)
        object.__setattr__(self, "sites", tuple(normalized))
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids") or DEFAULT_PROVIDER_IDS,
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise ProofHoleEmissionError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        if not isinstance(self.metadata, Mapping):
            raise ProofHoleEmissionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def site(self, site_id: str) -> AnnotationSite:
        for item in self.sites:
            if item.site_id == site_id:
                return item
        raise ProofHoleEmissionError(f"unknown site {site_id!r}")

    def without_annotation(
        self,
        site_id: str,
        *roles: AnnotationRole | str,
    ) -> "CompilationSurface":
        """Drop present annotations at ``site_id`` (fail-closed, no defaults)."""

        if not roles:
            raise ProofHoleEmissionError("at least one role must be removed")
        updated: list[AnnotationSite] = []
        found = False
        for site in self.sites:
            if site.site_id == site_id:
                found = True
                updated.append(site.without_roles(*roles))
            else:
                updated.append(site)
        if not found:
            raise ProofHoleEmissionError(f"unknown site {site_id!r}")
        return replace(self, sites=tuple(updated))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPILATION_SURFACE_SCHEMA,
            "surface_id": self.surface_id,
            "formal_goal_id": self.formal_goal_id,
            "tree_id": self.tree_id,
            "sites": [site.to_dict() for site in self.sites],
            "provider_ids": list(self.provider_ids),
            "bounds": self.bounds.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompilationSurface":
        if not isinstance(payload, Mapping):
            raise ProofHoleEmissionError("compilation surface payload must be an object")
        bounds_raw = payload.get("bounds")
        return cls(
            surface_id=payload.get("surface_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            tree_id=payload.get("tree_id", ""),
            sites=tuple(
                AnnotationSite.from_dict(item)
                if isinstance(item, Mapping)
                else item
                for item in (payload.get("sites") or ())
            ),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else bounds_raw if bounds_raw is not None else DEFAULT_BOUNDS
            ),
            metadata=payload.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Site builders (ergonomic construction for common VC / model sites)
# ---------------------------------------------------------------------------


def loop_site(
    site_id: str,
    *,
    source: SourceSpanBinding | Mapping[str, Any],
    has_invariant: bool,
    has_variant: bool = False,
    require_variant: bool = False,
    dependency_ids: Sequence[str] = (),
    statement: str = "",
    rationale: str = "",
    formal_goal_id: str = "",
) -> AnnotationSite:
    """Build a loop annotation site (invariants never invented)."""

    required: set[AnnotationRole] = {AnnotationRole.LOOP_INVARIANT}
    present: set[AnnotationRole] = set()
    if has_invariant:
        present.add(AnnotationRole.LOOP_INVARIANT)
    if require_variant:
        required.add(AnnotationRole.LOOP_VARIANT)
        if has_variant:
            present.add(AnnotationRole.LOOP_VARIANT)
    elif has_variant:
        required.add(AnnotationRole.LOOP_VARIANT)
        present.add(AnnotationRole.LOOP_VARIANT)
    return AnnotationSite(
        site_id=site_id,
        site_kind=SiteKind.LOOP,
        source=source,  # type: ignore[arg-type]
        required_roles=frozenset(required),
        present_roles=frozenset(present),
        dependency_ids=tuple(dependency_ids),
        statement=statement
        or f"loop site {site_id} requires a typed invariant"
        + (" and variant" if require_variant else ""),
        rationale=rationale
        or (
            "Loop verification conditions need an explicit invariant; "
            "defaults are never invented."
        ),
        formal_goal_id=formal_goal_id,
    )


def callee_site(
    site_id: str,
    *,
    source: SourceSpanBinding | Mapping[str, Any],
    has_precondition: bool = False,
    has_postcondition: bool = False,
    has_frame: bool = False,
    has_summary: bool = False,
    has_exceptional: bool = False,
    require_precondition: bool = True,
    require_postcondition: bool = True,
    require_frame: bool = True,
    require_summary: bool = False,
    require_exceptional: bool = False,
    dependency_ids: Sequence[str] = (),
    statement: str = "",
    rationale: str = "",
    formal_goal_id: str = "",
) -> AnnotationSite:
    """Build a call-site contract/frame annotation site."""

    required: set[AnnotationRole] = set()
    present: set[AnnotationRole] = set()
    pairs = (
        (require_precondition, has_precondition, AnnotationRole.CALLEE_PRECONDITION),
        (require_postcondition, has_postcondition, AnnotationRole.CALLEE_POSTCONDITION),
        (require_frame, has_frame, AnnotationRole.FRAME),
        (require_summary, has_summary, AnnotationRole.FUNCTION_SUMMARY),
        (require_exceptional, has_exceptional, AnnotationRole.EXCEPTIONAL_CONTRACT),
    )
    for require, has, role in pairs:
        if require:
            required.add(role)
            if has:
                present.add(role)
        elif has:
            required.add(role)
            present.add(role)
    return AnnotationSite(
        site_id=site_id,
        site_kind=SiteKind.CALL,
        source=source,  # type: ignore[arg-type]
        required_roles=frozenset(required),
        present_roles=frozenset(present),
        dependency_ids=tuple(dependency_ids),
        statement=statement or f"callee site {site_id} requires contract/frame material",
        rationale=rationale
        or (
            "Call-site verification needs explicit callee contracts and frames; "
            "defaults are never invented."
        ),
        formal_goal_id=formal_goal_id,
    )


def fairness_site(
    site_id: str,
    *,
    source: SourceSpanBinding | Mapping[str, Any],
    has_fairness_premise: bool,
    dependency_ids: Sequence[str] = (),
    statement: str = "",
    rationale: str = "",
    formal_goal_id: str = "",
) -> AnnotationSite:
    """Build a temporal fairness premise site."""

    present = (
        frozenset({AnnotationRole.TEMPORAL_FAIRNESS})
        if has_fairness_premise
        else frozenset()
    )
    return AnnotationSite(
        site_id=site_id,
        site_kind=SiteKind.TEMPORAL,
        source=source,  # type: ignore[arg-type]
        required_roles=frozenset({AnnotationRole.TEMPORAL_FAIRNESS}),
        present_roles=present,
        dependency_ids=tuple(dependency_ids),
        statement=statement or f"fairness premise required at {site_id}",
        rationale=rationale
        or (
            "Liveness/inevitability goals need an explicit fairness premise; "
            "it is never silently assumed."
        ),
        formal_goal_id=formal_goal_id,
    )


def bridge_lemma_site(
    site_id: str,
    *,
    source: SourceSpanBinding | Mapping[str, Any],
    has_bridge_lemma: bool,
    dependency_ids: Sequence[str] = (),
    statement: str = "",
    rationale: str = "",
    formal_goal_id: str = "",
) -> AnnotationSite:
    """Build a bridge-lemma obligation site between logic/IR fragments."""

    present = (
        frozenset({AnnotationRole.BRIDGE_LEMMA}) if has_bridge_lemma else frozenset()
    )
    return AnnotationSite(
        site_id=site_id,
        site_kind=SiteKind.BRIDGE,
        source=source,  # type: ignore[arg-type]
        required_roles=frozenset({AnnotationRole.BRIDGE_LEMMA}),
        present_roles=present,
        dependency_ids=tuple(dependency_ids),
        statement=statement or f"bridge lemma required at {site_id}",
        rationale=rationale
        or (
            "Cross-logic or cross-IR composition needs an explicit bridge lemma; "
            "string equality is never trusted as a bridge."
        ),
        formal_goal_id=formal_goal_id,
    )


def unsupported_semantics_site(
    site_id: str,
    *,
    source: SourceSpanBinding | Mapping[str, Any],
    description: str,
    dependency_ids: Sequence[str] = (),
    formal_goal_id: str = "",
) -> AnnotationSite:
    """Build a non-proof unsupported-semantics diagnostic site."""

    return AnnotationSite(
        site_id=site_id,
        site_kind=SiteKind.SEMANTICS,
        source=source,  # type: ignore[arg-type]
        required_roles=frozenset({AnnotationRole.UNSUPPORTED_SEMANTICS}),
        present_roles=frozenset(),
        dependency_ids=tuple(dependency_ids),
        statement=description,
        rationale=(
            "This construct is outside the supported semantic profile; "
            "it is not a missing-proof gap and must not be discharged as one."
        ),
        formal_goal_id=formal_goal_id,
    )


def unavailable_tool_site(
    site_id: str,
    *,
    source: SourceSpanBinding | Mapping[str, Any],
    tool_id: str,
    dependency_ids: Sequence[str] = (),
    formal_goal_id: str = "",
) -> AnnotationSite:
    """Build a non-proof unavailable-tool diagnostic site."""

    return AnnotationSite(
        site_id=site_id,
        site_kind=SiteKind.TOOL,
        source=source,  # type: ignore[arg-type]
        required_roles=frozenset({AnnotationRole.UNAVAILABLE_TOOL}),
        present_roles=frozenset(),
        dependency_ids=tuple(dependency_ids),
        statement=f"tool {tool_id} is unavailable",
        rationale=(
            "Tool absence is an operational non-success state, not missing proof."
        ),
        formal_goal_id=formal_goal_id,
        metadata={"tool_id": tool_id},
    )


# ---------------------------------------------------------------------------
# Emission result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofHoleEmission:
    """Result of :class:`TypedProofHoleEmitter` over a compilation surface."""

    SCHEMA: ClassVar[str] = PROOF_HOLE_EMISSION_SCHEMA
    INTERFACE: ClassVar[str] = TYPED_PROOF_HOLE_EMITTER_INTERFACE

    emission_id: str
    surface_id: str
    formal_goal_id: str
    holes: tuple[ProofHole, ...]
    missing_proof_hole_ids: tuple[str, ...]
    non_proof_hole_ids: tuple[str, ...]
    algorithm_version: str = EMITTER_ALGORITHM_VERSION
    invented_defaults: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "emission_id", _text(self.emission_id, "emission_id", maximum=256)
        )
        object.__setattr__(
            self, "surface_id", _text(self.surface_id, "surface_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", optional=True, maximum=256),
        )
        normalized: list[ProofHole] = []
        for index, hole in enumerate(self.holes):
            if isinstance(hole, Mapping):
                try:
                    hole = ProofHole.from_dict(hole)
                except TacticianContractError as error:
                    raise ProofHoleEmissionError(
                        f"holes[{index}]: {error}"
                    ) from error
            elif not isinstance(hole, ProofHole):
                raise ProofHoleEmissionError(f"holes[{index}] must be a ProofHole")
            if hole.proof_claimed or hole.completion_claimed:
                raise ProofHoleEmissionError(
                    "emitted ProofHole cannot claim proof or completion"
                )
            normalized.append(hole)
        object.__setattr__(self, "holes", tuple(normalized))
        object.__setattr__(
            self,
            "missing_proof_hole_ids",
            _string_tuple(self.missing_proof_hole_ids, "missing_proof_hole_ids"),
        )
        object.__setattr__(
            self,
            "non_proof_hole_ids",
            _string_tuple(self.non_proof_hole_ids, "non_proof_hole_ids"),
        )
        if self.invented_defaults:
            raise ProofHoleEmissionError(
                "TypedProofHoleEmitter must never invent default annotations"
            )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(self.algorithm_version, "algorithm_version", maximum=128),
        )

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def missing_proof_holes(self) -> tuple[ProofHole, ...]:
        ids = set(self.missing_proof_hole_ids)
        return tuple(hole for hole in self.holes if hole.hole_id in ids)

    @property
    def non_proof_holes(self) -> tuple[ProofHole, ...]:
        ids = set(self.non_proof_hole_ids)
        return tuple(hole for hole in self.holes if hole.hole_id in ids)

    def holes_of_kind(self, kind: HoleKind | str) -> tuple[ProofHole, ...]:
        resolved = kind if isinstance(kind, HoleKind) else HoleKind(kind)
        return tuple(hole for hole in self.holes if hole.kind is resolved)

    def hole_for_site_role(
        self, site_id: str, role: AnnotationRole | str
    ) -> ProofHole | None:
        resolved = _enum(role, AnnotationRole, "role")
        kind = _ROLE_TO_HOLE_KIND[resolved]
        prefix = f"hole:{site_id}:"
        for hole in self.holes:
            if hole.kind is kind and (
                hole.hole_id.startswith(prefix)
                or hole.statement.find(site_id) >= 0
                or site_id in hole.dependency_ids
                or hole.hole_id.endswith(site_id)
            ):
                # Prefer exact site encoding in hole_id.
                if site_id in hole.hole_id or hole.hole_id.startswith(f"hole:{resolved.value}"):
                    return hole
        # Fall back: match kind + site_id substring in reason/statement.
        for hole in self.holes:
            if hole.kind is kind and site_id in (hole.reason + hole.statement + hole.hole_id):
                return hole
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "emission_id": self.emission_id,
            "surface_id": self.surface_id,
            "formal_goal_id": self.formal_goal_id,
            "holes": [hole.to_dict() for hole in self.holes],
            "missing_proof_hole_ids": list(self.missing_proof_hole_ids),
            "non_proof_hole_ids": list(self.non_proof_hole_ids),
            "algorithm_version": self.algorithm_version,
            "invented_defaults": False,
        }

    def to_record(self) -> dict[str, Any]:
        return {**self.to_dict(), "content_id": self.content_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofHoleEmission":
        if not isinstance(payload, Mapping):
            raise ProofHoleEmissionError("emission payload must be an object")
        if payload.get("invented_defaults") is True:
            raise ProofHoleEmissionError(
                "TypedProofHoleEmitter must never invent default annotations"
            )
        return cls(
            emission_id=payload.get("emission_id", ""),
            surface_id=payload.get("surface_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            holes=tuple(payload.get("holes") or ()),
            missing_proof_hole_ids=tuple(payload.get("missing_proof_hole_ids") or ()),
            non_proof_hole_ids=tuple(payload.get("non_proof_hole_ids") or ()),
            algorithm_version=payload.get(
                "algorithm_version", EMITTER_ALGORITHM_VERSION
            ),
            invented_defaults=False,
        )


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedProofHoleEmitter:
    """Emit source-bound typed proof holes (``TypedProofHoleEmitter@1``).

    The emitter is pure and fail-closed: given a :class:`CompilationSurface`
    it returns one :class:`ProofHole` per missing required role, with full
    actionable metadata.  It never invents present annotations.
    """

    INTERFACE: ClassVar[str] = TYPED_PROOF_HOLE_EMITTER_INTERFACE
    ALGORITHM_VERSION: ClassVar[str] = EMITTER_ALGORITHM_VERSION

    require_source_spans: bool = True
    default_provider_ids: tuple[str, ...] = DEFAULT_PROVIDER_IDS
    default_bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)

    def __post_init__(self) -> None:
        if not isinstance(self.require_source_spans, bool):
            raise ProofHoleEmissionError("require_source_spans must be boolean")
        object.__setattr__(
            self,
            "default_provider_ids",
            _string_tuple(self.default_provider_ids, "default_provider_ids")
            or DEFAULT_PROVIDER_IDS,
        )
        bounds = self.default_bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise ProofHoleEmissionError("default_bounds must be a ResourceBounds")
        object.__setattr__(self, "default_bounds", bounds)

    def emit(self, surface: CompilationSurface | Mapping[str, Any]) -> ProofHoleEmission:
        """Emit all actionable typed holes for ``surface``."""

        if isinstance(surface, Mapping):
            surface = CompilationSurface.from_dict(surface)
        elif not isinstance(surface, CompilationSurface):
            raise ProofHoleEmissionError("surface must be a CompilationSurface")

        holes: list[ProofHole] = []
        missing_ids: list[str] = []
        non_proof_ids: list[str] = []

        for site in surface.sites:
            if self.require_source_spans:
                if not site.source.source_ref_ids and not site.source.span_ids:
                    raise ProofHoleEmissionError(
                        f"site {site.site_id!r} is missing source span binding"
                    )
            for role in sorted(site.missing_roles, key=lambda item: item.value):
                hole = self._emit_hole(surface=surface, site=site, role=role)
                holes.append(hole)
                if is_missing_proof_role(role):
                    missing_ids.append(hole.hole_id)
                else:
                    non_proof_ids.append(hole.hole_id)

        # Deterministic ordering: missing-proof first by kind, then non-proof.
        holes_sorted = tuple(
            sorted(
                holes,
                key=lambda hole: (
                    0 if hole.hole_id in missing_ids else 1,
                    hole.kind.value,
                    hole.hole_id,
                ),
            )
        )
        emission_id = (
            "emission:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "surface_id": surface.surface_id,
                        "hole_ids": [hole.hole_id for hole in holes_sorted],
                        "algorithm": self.ALGORITHM_VERSION,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        return ProofHoleEmission(
            emission_id=emission_id,
            surface_id=surface.surface_id,
            formal_goal_id=surface.formal_goal_id,
            holes=holes_sorted,
            missing_proof_hole_ids=tuple(
                hole.hole_id for hole in holes_sorted if hole.hole_id in set(missing_ids)
            ),
            non_proof_hole_ids=tuple(
                hole.hole_id
                for hole in holes_sorted
                if hole.hole_id in set(non_proof_ids)
            ),
            algorithm_version=self.ALGORITHM_VERSION,
            invented_defaults=False,
        )

    def emit_for_removed_annotation(
        self,
        surface: CompilationSurface,
        site_id: str,
        *roles: AnnotationRole | str,
    ) -> ProofHoleEmission:
        """Remove present annotation(s) and re-emit holes (acceptance helper)."""

        return self.emit(surface.without_annotation(site_id, *roles))

    def _emit_hole(
        self,
        *,
        surface: CompilationSurface,
        site: AnnotationSite,
        role: AnnotationRole,
    ) -> ProofHole:
        kind = _ROLE_TO_HOLE_KIND[role]
        status = hole_status_for_role(role)
        authority = (
            site.expected_authority
            if site.expected_authority is not None
            else _ROLE_AUTHORITY.get(role, AuthorityCeiling.CANDIDATE)
        )
        property_class = (
            site.property_class
            if site.property_class is not None
            else _ROLE_PROPERTY_CLASS.get(role, PropertyClass.UNSPECIFIED)
        )
        providers = site.provider_ids or surface.provider_ids or self.default_provider_ids
        bounds = site.bounds if site.bounds is not None else surface.bounds
        recipe = default_validation_recipe(
            role,
            site_id=site.site_id,
            provider_ids=providers,
            bounds=bounds,
        )
        reason = site.rationale or self._default_reason(site=site, role=role)
        statement = site.statement or self._default_statement(site=site, role=role)
        hole_id = _stable_hole_id(site.site_id, role.value, kind.value)
        # Encode site_id into hole_id for reliable lookup while staying stable.
        hole_id = f"hole:{site.site_id}:{role.value}"
        if len(hole_id) > 256:
            hole_id = _stable_hole_id(site.site_id, role.value)

        dependencies = list(site.dependency_ids)
        # Peer missing roles at the same site become soft dependencies.
        for peer in sorted(site.missing_roles, key=lambda item: item.value):
            if peer is role:
                continue
            peer_id = f"hole:{site.site_id}:{peer.value}"
            if peer_id not in dependencies:
                dependencies.append(peer_id)

        try:
            return ProofHole(
                hole_id=hole_id,
                kind=kind,
                reason=reason,
                source=site.source,
                formal_goal_id=site.formal_goal_id or surface.formal_goal_id,
                expected_authority=authority,
                dependency_ids=tuple(dependencies),
                validation_recipe=recipe,
                status=status,
                property_class=property_class,
                statement=statement,
                provider_ids=tuple(providers),
                bounds=bounds if bounds is not None else self.default_bounds,
                proof_claimed=False,
                completion_claimed=False,
            )
        except TacticianContractError as error:
            raise ProofHoleEmissionError(
                f"failed to construct ProofHole for {site.site_id}/{role.value}: {error}"
            ) from error

    @staticmethod
    def _default_reason(*, site: AnnotationSite, role: AnnotationRole) -> str:
        if role in _NON_PROOF_ROLES:
            return (
                f"{role.value} at site {site.site_id} ({site.site_kind.value}) "
                f"is a non-proof diagnostic, not a missing-proof obligation."
            )
        return (
            f"Required {role.value} is missing at site {site.site_id} "
            f"({site.site_kind.value}); compilation refuses to invent a default."
        )

    @staticmethod
    def _default_statement(*, site: AnnotationSite, role: AnnotationRole) -> str:
        return f"missing {role.value} at {site.site_id}"


def emit_typed_proof_holes(
    surface: CompilationSurface | Mapping[str, Any],
    *,
    require_source_spans: bool = True,
) -> ProofHoleEmission:
    """Convenience entry point for ``TypedProofHoleEmitter@1``."""

    return TypedProofHoleEmitter(
        require_source_spans=require_source_spans
    ).emit(surface)


__all__ = [
    "TYPED_PROOF_HOLE_EMITTER_INTERFACE",
    "PROOF_HOLE_EMISSION_SCHEMA",
    "COMPILATION_SURFACE_SCHEMA",
    "ANNOTATION_SITE_SCHEMA",
    "EMITTER_ALGORITHM_VERSION",
    "DEFAULT_PROVIDER_IDS",
    "DEFAULT_BOUNDS",
    "PROOF_HOLE_INTERFACE",
    "ProofHoleEmissionError",
    "AnnotationRole",
    "SiteKind",
    "AnnotationSite",
    "CompilationSurface",
    "ProofHoleEmission",
    "TypedProofHoleEmitter",
    "default_validation_recipe",
    "hole_status_for_role",
    "is_missing_proof_role",
    "loop_site",
    "callee_site",
    "fairness_site",
    "bridge_lemma_site",
    "unsupported_semantics_site",
    "unavailable_tool_site",
    "emit_typed_proof_holes",
]
