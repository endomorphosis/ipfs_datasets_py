"""Compile confirmed end goals into shared verification semantics (FVT-G024).

``FormalGoalCompiler@1`` lowers a caller-confirmed :class:`FormalGoal` (wrapping
a resolved :class:`EndGoalSpec`) into:

* a source-grounded :class:`SoftwareVerificationIR` document with properties,
  contract/state/transition/environment declarations, assumptions, and bounds;
* backend-neutral root obligations that name shared property/assumption
  identities rather than provider syntax; and
* a loss-aware :class:`LogicTranslationReceipt` whose authority ceiling is
  computed from preservation class and **cannot** be raised by backend choice.

Acceptance invariants (enforced here and in the integration suite):

* exact targets and bounds reproduce from content identities;
* source spans and assumption classes survive compilation;
* material translation loss or unresolved ambiguity fails closed; and
* selecting a backend never raises assurance above the translation ceiling.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import BoundednessKind, EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.ir import (
    DeclarationKind,
    SoftwareVerificationIR,
    VerificationBound,
    VerificationDeclaration,
)
from ipfs_datasets_py.logic.software_verification.properties import (
    AssumptionKind,
    PropertyKind,
    VerificationAssumption,
    VerificationProperty,
)
from ipfs_datasets_py.logic.software_verification.receipts import (
    LogicTranslationReceipt,
)
from ipfs_datasets_py.logic.software_verification.translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    SemanticMutation,
    SemanticMutationKind,
    TranslationBound,
    authority_at_most,
    maximum_authority_for,
)

from .contracts import (
    AmbiguityStatus,
    AssumptionBinding,
    AssumptionClass,
    AuthorityCeiling,
    EndGoalInterpretation,
    EndGoalSpec,
    FormalGoal,
    PropertyClass,
    QuantifierKind,
    ResourceBounds,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

FORMAL_GOAL_COMPILER_INTERFACE: Final = "FormalGoalCompiler@1"
FORMAL_GOAL_COMPILER_VERSION: Final = "1.0.0"
FORMAL_GOAL_COMPILER_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/formal-goal-compiler@1"
)
GOAL_COMPILATION_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/goal-compilation-result@1"
)
ROOT_OBLIGATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/root-obligation@1"
)

SOURCE_FAMILY_ID: Final = "end_goal_spec"
SOURCE_FAMILY_VERSION: Final = "1"
TARGET_FAMILY_ID: Final = "software_verification"
TARGET_FAMILY_VERSION: Final = "1"

COMPILER_ID: Final = "compiler:formal-goal-compiler"
COMPILER_IMPLEMENTATION_SEED: Final = b"FormalGoalCompiler@1/v1.0.0"

_ID_SAFE: Final = re.compile(r"[^A-Za-z0-9._:/-]+")
_MATERIAL_LOSS_MARKERS: Final = frozenset(
    {
        "material",
        "lossy",
        "dropped",
        "omitted",
        "unsupported",
        "ambiguous",
        "incomplete",
        "erased",
        "unsound",
    }
)


# ---------------------------------------------------------------------------
# Errors and closed vocabularies
# ---------------------------------------------------------------------------


class GoalCompilerError(ValueError):
    """Raised when goal compilation is malformed or must fail closed."""


class CompilationStatus(StrEnum):
    """Outcome of a successful compilation (failure raises instead)."""

    SUCCESS = "success"


# Property-class → shared IR property kind (provider-neutral).
_PROPERTY_KIND: Final[Mapping[PropertyClass, PropertyKind]] = {
    PropertyClass.EXISTENTIAL_REACHABILITY: PropertyKind.REACHABILITY,
    PropertyClass.UNIVERSAL_REACHABILITY: PropertyKind.REACHABILITY,
    PropertyClass.INEVITABILITY: PropertyKind.LIVENESS,
    PropertyClass.LIVENESS: PropertyKind.LIVENESS,
    PropertyClass.INVARIANCE: PropertyKind.INVARIANT,
    PropertyClass.SAFETY: PropertyKind.SAFETY,
    PropertyClass.TERMINATION: PropertyKind.TERMINATION,
    PropertyClass.REFINEMENT: PropertyKind.REFINEMENT,
    PropertyClass.HYPERPROPERTY: PropertyKind.HYPERPROPERTY,
    PropertyClass.AUTHORIZATION: PropertyKind.AUTHORIZATION,
    PropertyClass.PROTOCOL: PropertyKind.TRACE_CONFORMANCE,
    PropertyClass.THEOREM: PropertyKind.THEOREM,
    PropertyClass.CONTRACT: PropertyKind.CONTRACT,
}

# Assumption class → shared assumption kind (class survives in extensions).
_ASSUMPTION_KIND: Final[Mapping[AssumptionClass, AssumptionKind]] = {
    AssumptionClass.TRUSTED: AssumptionKind.TRUST,
    AssumptionClass.MUST_PROVE: AssumptionKind.SEMANTIC,
    AssumptionClass.HYPOTHETICAL: AssumptionKind.MODELING,
}

# Tactician authority ceiling → evidence authority (never self-upgrades).
_AUTHORITY_TO_EVIDENCE: Final[Mapping[AuthorityCeiling, EvidenceAuthority]] = {
    AuthorityCeiling.NONE: EvidenceAuthority.NONE,
    AuthorityCeiling.ADVISORY: EvidenceAuthority.ADVISORY,
    AuthorityCeiling.CANDIDATE: EvidenceAuthority.ADVISORY,
    AuthorityCeiling.DECLARATIVE: EvidenceAuthority.ADVISORY,
    AuthorityCeiling.BOUNDED: EvidenceAuthority.BOUNDED,
    AuthorityCeiling.SATISFIABILITY: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    AuthorityCeiling.MODEL_CHECK: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    AuthorityCeiling.MONITOR: EvidenceAuthority.BOUNDED,
    AuthorityCeiling.AUTHORIZATION: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    AuthorityCeiling.PROTOCOL: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    AuthorityCeiling.HYPERPROPERTY: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    AuthorityCeiling.RECONSTRUCTION: EvidenceAuthority.AUTHORITATIVE,
    AuthorityCeiling.ATTESTATION: EvidenceAuthority.AUTHORITATIVE,
    AuthorityCeiling.THEOREM: EvidenceAuthority.AUTHORITATIVE,
}

_EVIDENCE_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.AUTHORITATIVE: 4,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value.strip() != value:
        raise GoalCompilerError(
            f"{label} must be a non-empty trimmed string"
            if not optional
            else f"{label} must be empty or a trimmed string"
        )
    if "\x00" in value:
        raise GoalCompilerError(f"{label} must not contain NUL")
    return value


def _stable_hex(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _sanitize_id(raw: str, *, prefix: str) -> str:
    text = raw.strip()
    if not text:
        text = "anon"
    cleaned = _ID_SAFE.sub("-", text).strip("-._:/")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"x-{cleaned}" if cleaned else "x"
    candidate = f"{prefix}:{cleaned}" if not cleaned.startswith(f"{prefix}:") else cleaned
    return candidate[:256]


def _mapping_json(value: Mapping[str, Any] | object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise GoalCompilerError("expected a JSON object mapping")
    # Defensive copy with string keys only.
    return {str(k): value[k] for k in value}


def _is_material_loss_token(token: str) -> bool:
    lowered = token.casefold()
    if any(marker in lowered for marker in _MATERIAL_LOSS_MARKERS):
        return True
    # Bare non-empty translation-loss entries are treated as material unless
    # they are explicitly annotated as "informational" / "cosmetic".
    if lowered.startswith("informational:") or lowered.startswith("cosmetic:"):
        return False
    return bool(token.strip())


def _authority_min(
    left: EvidenceAuthority, right: EvidenceAuthority
) -> EvidenceAuthority:
    if _EVIDENCE_RANK[left] <= _EVIDENCE_RANK[right]:
        return left
    return right


def map_property_kind(property_class: PropertyClass) -> PropertyKind:
    """Map an end-goal property class onto the shared IR property vocabulary."""

    kind = _PROPERTY_KIND.get(property_class)
    if kind is None:
        raise GoalCompilerError(
            f"property class {property_class.value!r} cannot be compiled "
            "into a shared verification property"
        )
    return kind


def map_assumption_kind(assumption_class: AssumptionClass) -> AssumptionKind:
    """Map a tactician assumption class onto the shared assumption vocabulary."""

    return _ASSUMPTION_KIND[assumption_class]


def map_evidence_authority(ceiling: AuthorityCeiling) -> EvidenceAuthority:
    """Map a tactician authority ceiling onto evidence authority."""

    return _AUTHORITY_TO_EVIDENCE[ceiling]


def _selected_interpretation(goal: FormalGoal) -> EndGoalInterpretation | None:
    end_goal = goal.end_goal
    selected = goal.selected_interpretation_id
    for item in end_goal.interpretations:
        if item.interpretation_id == selected:
            return item
    return None


def _effective_property_fields(
    goal: FormalGoal,
) -> tuple[PropertyClass, tuple[QuantifierKind, ...], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Resolve property/state fields from the selected interpretation when present."""

    end_goal = goal.end_goal
    interpretation = _selected_interpretation(goal)
    if interpretation is None:
        return (
            end_goal.property_class,
            end_goal.quantifiers,
            dict(end_goal.current_state),
            dict(end_goal.target_state),
            dict(end_goal.environment),
        )
    return (
        interpretation.property_class,
        interpretation.quantifiers or end_goal.quantifiers,
        dict(interpretation.current_state or end_goal.current_state),
        dict(interpretation.target_state or end_goal.target_state),
        dict(interpretation.environment or end_goal.environment),
    )


def _bounds_have_limits(bounds: ResourceBounds) -> bool:
    return any(
        (
            bounds.wall_time_ms,
            bounds.memory_bytes,
            bounds.max_steps,
            bounds.max_depth,
            bounds.max_nodes,
            bounds.max_candidates,
            bounds.model_token_limit,
            bool(bounds.extra),
        )
    )


def _resource_limits(bounds: ResourceBounds) -> dict[str, int]:
    limits: dict[str, int] = {}
    if bounds.wall_time_ms:
        limits["wall_time_ms"] = bounds.wall_time_ms
    if bounds.memory_bytes:
        limits["memory_bytes"] = bounds.memory_bytes
    if bounds.max_steps:
        limits["max_steps"] = bounds.max_steps
    if bounds.max_depth:
        limits["max_depth"] = bounds.max_depth
    if bounds.max_nodes:
        limits["max_nodes"] = bounds.max_nodes
    if bounds.max_candidates:
        limits["max_candidates"] = bounds.max_candidates
    if bounds.model_token_limit:
        limits["model_token_limit"] = bounds.model_token_limit
    for key, value in (bounds.extra or {}).items():
        limits[str(key)] = int(value)
    return limits


# ---------------------------------------------------------------------------
# Root obligations and compilation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RootObligation:
    """Backend-neutral root verification obligation derived from a formal goal.

    Obligations deliberately omit provider syntax.  ``provider_ids`` are
    advisory routing hints only and must never appear in the obligation
    statement or raise the translation authority ceiling.
    """

    SCHEMA: ClassVar[str] = ROOT_OBLIGATION_SCHEMA

    obligation_id: str
    property_id: str
    statement: str
    kind: PropertyKind | str
    assumption_ids: tuple[str, ...] = ()
    bound_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    formal_goal_id: str = ""
    root_goal_id: str = ""
    provider_ids: tuple[str, ...] = ()
    backend_neutral: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "property_id", _text(self.property_id, "property_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        kind = self.kind
        if isinstance(kind, PropertyKind):
            kind_value: PropertyKind | str = kind
        else:
            try:
                kind_value = PropertyKind(str(kind))
            except ValueError as error:
                raise GoalCompilerError(
                    f"root obligation kind must be a shared PropertyKind: {kind!r}"
                ) from error
        object.__setattr__(self, "kind", kind_value)
        object.__setattr__(
            self,
            "assumption_ids",
            tuple(sorted({_text(i, "assumption_ids item") for i in self.assumption_ids})),
        )
        object.__setattr__(
            self,
            "bound_ids",
            tuple(sorted({_text(i, "bound_ids item") for i in self.bound_ids})),
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            tuple(sorted({_text(i, "source_ref_ids item") for i in self.source_ref_ids})),
        )
        object.__setattr__(
            self,
            "span_ids",
            tuple(sorted({_text(i, "span_ids item") for i in self.span_ids})),
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", optional=True),
        )
        object.__setattr__(
            self,
            "root_goal_id",
            _text(self.root_goal_id, "root_goal_id", optional=True),
        )
        object.__setattr__(
            self,
            "provider_ids",
            tuple(sorted({_text(i, "provider_ids item") for i in self.provider_ids})),
        )
        if not isinstance(self.backend_neutral, bool):
            raise GoalCompilerError("backend_neutral must be a boolean")
        if not self.backend_neutral:
            raise GoalCompilerError(
                "root obligations must remain backend-neutral; do not embed "
                "provider syntax in FormalGoal compilation"
            )
        # Fail closed if the statement smuggles solver dialects.
        lowered = self.statement.casefold()
        for banned in ("(assert", "(check-sat", "smt-lib", "tla+", "```lean"):
            if banned in lowered:
                raise GoalCompilerError(
                    "root obligation statement must not embed provider syntax"
                )

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value if isinstance(self.kind, PropertyKind) else str(self.kind)
        return {
            "schema": self.SCHEMA,
            "obligation_id": self.obligation_id,
            "property_id": self.property_id,
            "statement": self.statement,
            "kind": kind,
            "assumption_ids": list(self.assumption_ids),
            "bound_ids": list(self.bound_ids),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "formal_goal_id": self.formal_goal_id,
            "root_goal_id": self.root_goal_id,
            "provider_ids": list(self.provider_ids),
            "backend_neutral": True,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RootObligation":
        if not isinstance(payload, Mapping):
            raise GoalCompilerError("root obligation payload must be an object")
        return cls(
            obligation_id=str(payload.get("obligation_id") or ""),
            property_id=str(payload.get("property_id") or ""),
            statement=str(payload.get("statement") or ""),
            kind=str(payload.get("kind") or ""),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            bound_ids=tuple(payload.get("bound_ids") or ()),
            source_ref_ids=tuple(payload.get("source_ref_ids") or ()),
            span_ids=tuple(payload.get("span_ids") or ()),
            formal_goal_id=str(payload.get("formal_goal_id") or ""),
            root_goal_id=str(payload.get("root_goal_id") or ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            backend_neutral=bool(payload.get("backend_neutral", True)),
        )


@dataclass(frozen=True, slots=True)
class GoalCompilationResult:
    """Immutable product of ``FormalGoalCompiler.compile``."""

    SCHEMA: ClassVar[str] = GOAL_COMPILATION_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = FORMAL_GOAL_COMPILER_INTERFACE

    formal_goal_id: str
    root_goal_id: str
    end_goal_content_id: str
    formal_goal_content_id: str
    selected_interpretation_id: str
    ir: SoftwareVerificationIR
    translation_receipt: LogicTranslationReceipt
    root_obligations: tuple[RootObligation, ...]
    assurance_ceiling: EvidenceAuthority
    preservation_kind: PreservationKind
    status: CompilationStatus = CompilationStatus.SUCCESS
    compiler_version: str = FORMAL_GOAL_COMPILER_VERSION
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "formal_goal_id", _text(self.formal_goal_id, "formal_goal_id")
        )
        object.__setattr__(
            self, "root_goal_id", _text(self.root_goal_id, "root_goal_id")
        )
        object.__setattr__(
            self,
            "end_goal_content_id",
            _text(self.end_goal_content_id, "end_goal_content_id"),
        )
        object.__setattr__(
            self,
            "formal_goal_content_id",
            _text(self.formal_goal_content_id, "formal_goal_content_id"),
        )
        object.__setattr__(
            self,
            "selected_interpretation_id",
            _text(
                self.selected_interpretation_id,
                "selected_interpretation_id",
                optional=True,
            ),
        )
        if not isinstance(self.ir, SoftwareVerificationIR):
            raise GoalCompilerError("ir must be a SoftwareVerificationIR")
        if not isinstance(self.translation_receipt, LogicTranslationReceipt):
            raise GoalCompilerError(
                "translation_receipt must be a LogicTranslationReceipt"
            )
        obligations = tuple(self.root_obligations or ())
        if not obligations:
            raise GoalCompilerError(
                "compilation must emit at least one root obligation"
            )
        normalized: list[RootObligation] = []
        for item in obligations:
            if isinstance(item, RootObligation):
                normalized.append(item)
            elif isinstance(item, Mapping):
                normalized.append(RootObligation.from_dict(item))
            else:
                raise GoalCompilerError(
                    "root_obligations must contain RootObligation values"
                )
        object.__setattr__(self, "root_obligations", tuple(normalized))
        authority = self.assurance_ceiling
        if not isinstance(authority, EvidenceAuthority):
            try:
                authority = EvidenceAuthority(str(authority))
            except ValueError as error:
                raise GoalCompilerError(
                    f"assurance_ceiling must be EvidenceAuthority: {authority!r}"
                ) from error
        object.__setattr__(self, "assurance_ceiling", authority)
        kind = self.preservation_kind
        if not isinstance(kind, PreservationKind):
            try:
                kind = PreservationKind(str(kind))
            except ValueError as error:
                raise GoalCompilerError(
                    f"preservation_kind must be PreservationKind: {kind!r}"
                ) from error
        object.__setattr__(self, "preservation_kind", kind)
        status = self.status
        if not isinstance(status, CompilationStatus):
            status = CompilationStatus(str(status))
        object.__setattr__(self, "status", status)
        if not isinstance(self.metadata, FrozenMap):
            object.__setattr__(self, "metadata", FrozenMap(_mapping_json(self.metadata)))

        # Cross-binding: receipt must point at the IR and formal goal identities.
        receipt = self.translation_receipt
        if receipt.target_identity != self.ir.document_id:
            raise GoalCompilerError(
                "translation receipt target_identity must equal IR document_id"
            )
        if receipt.source_identity not in {
            self.formal_goal_content_id,
            self.end_goal_content_id,
        }:
            raise GoalCompilerError(
                "translation receipt source_identity must bind the formal or end goal"
            )
        if receipt.authority_ceiling != self.assurance_ceiling:
            raise GoalCompilerError(
                "result assurance_ceiling must match the translation receipt ceiling"
            )
        if not authority_at_most(
            self.assurance_ceiling, maximum_authority_for(self.preservation_kind)
        ):
            raise GoalCompilerError(
                "assurance_ceiling exceeds the preservation-class maximum"
            )

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def document_id(self) -> str:
        return self.ir.document_id

    @property
    def receipt_id(self) -> str:
        return self.translation_receipt.receipt_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "compiler_version": self.compiler_version,
            "status": self.status.value,
            "formal_goal_id": self.formal_goal_id,
            "root_goal_id": self.root_goal_id,
            "end_goal_content_id": self.end_goal_content_id,
            "formal_goal_content_id": self.formal_goal_content_id,
            "selected_interpretation_id": self.selected_interpretation_id,
            "ir": self.ir.to_dict(),
            "translation_receipt": self.translation_receipt.to_dict(),
            "root_obligations": [item.to_dict() for item in self.root_obligations],
            "assurance_ceiling": self.assurance_ceiling.value,
            "preservation_kind": self.preservation_kind.value,
            "metadata": self.metadata.to_dict(),
        }


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class FormalGoalCompiler:
    """Compile a confirmed formal goal into shared verification semantics.

    The compiler reuses LFV ``SoftwareVerificationIR`` and
    ``LogicTranslationReceipt`` contracts.  It never embeds provider syntax
    into the EndGoalSpec path and never elevates backend choice above the
    translation authority ceiling.
    """

    INTERFACE: ClassVar[str] = FORMAL_GOAL_COMPILER_INTERFACE
    VERSION: ClassVar[str] = FORMAL_GOAL_COMPILER_VERSION
    SCHEMA: ClassVar[str] = FORMAL_GOAL_COMPILER_SCHEMA

    def __init__(self, *, compiler_version: str = FORMAL_GOAL_COMPILER_VERSION) -> None:
        self._compiler_version = _text(compiler_version, "compiler_version")

    @property
    def compiler_version(self) -> str:
        return self._compiler_version

    def compile(
        self,
        formal_goal: FormalGoal | Mapping[str, Any],
        *,
        requested_backend: str | None = None,
        source_family_id: str = SOURCE_FAMILY_ID,
        source_family_version: str = SOURCE_FAMILY_VERSION,
        target_family_id: str = TARGET_FAMILY_ID,
        target_family_version: str = TARGET_FAMILY_VERSION,
    ) -> GoalCompilationResult:
        """Compile ``formal_goal`` into IR, root obligations, and a receipt.

        Parameters
        ----------
        formal_goal:
            A confirmed :class:`FormalGoal` (or its dict form).
        requested_backend:
            Optional backend/provider identifier.  Used only as a routing
            hint on root obligations; **never** raises the translation
            authority ceiling.
        """

        goal = self._coerce_formal_goal(formal_goal)
        self._require_compilable(goal)

        property_class, quantifiers, current_state, target_state, environment = (
            _effective_property_fields(goal)
        )
        end_goal = goal.end_goal
        property_kind = map_property_kind(property_class)

        source_ref_ids, span_ids, sources, spans = self._materialize_provenance(
            end_goal
        )
        if not source_ref_ids:
            raise GoalCompilerError(
                "compilation requires at least one source_ref_id on the EndGoalSpec"
            )

        declarations = self._build_declarations(
            end_goal=end_goal,
            property_class=property_class,
            quantifiers=quantifiers,
            current_state=current_state,
            target_state=target_state,
            environment=environment,
            source_ref_ids=source_ref_ids,
            span_ids=span_ids,
        )
        assumptions = self._build_assumptions(
            end_goal=end_goal,
            subject_ids=tuple(item.declaration_id for item in declarations),
            fallback_source_ref_ids=source_ref_ids,
            fallback_span_ids=span_ids,
        )
        bounds = self._build_bounds(
            end_goal=end_goal,
            source_ref_ids=source_ref_ids,
            span_ids=span_ids,
        )
        prop = self._build_root_property(
            goal=goal,
            property_class=property_class,
            property_kind=property_kind,
            quantifiers=quantifiers,
            current_state=current_state,
            target_state=target_state,
            subject_ids=tuple(item.declaration_id for item in declarations),
            assumption_ids=tuple(item.assumption_id for item in assumptions),
            bound_ids=tuple(item.bound_id for item in bounds),
            source_ref_ids=source_ref_ids,
            span_ids=span_ids,
        )
        ir = SoftwareVerificationIR(
            sources=sources,
            spans=spans,
            declarations=declarations,
            assumptions=assumptions,
            bounds=bounds,
            properties=(prop,),
            metadata={
                "formal_goal_id": goal.formal_goal_id,
                "root_goal_id": goal.root_goal_id,
                "end_goal_id": end_goal.goal_id,
                "selected_interpretation_id": goal.selected_interpretation_id,
                "compiler": self.INTERFACE,
                "compiler_version": self._compiler_version,
            },
            extensions={
                "tactician.property_class": property_class.value,
                "tactician.logic_family": end_goal.logic_family or "unspecified",
            },
        )

        root_obligation = RootObligation(
            obligation_id=_sanitize_id(goal.formal_goal_id, prefix="obligation"),
            property_id=prop.property_id,
            statement=prop.statement,
            kind=property_kind,
            assumption_ids=prop.assumption_ids,
            bound_ids=prop.bound_ids,
            source_ref_ids=prop.source_ref_ids,
            span_ids=prop.span_ids,
            formal_goal_id=goal.formal_goal_id,
            root_goal_id=goal.root_goal_id,
            provider_ids=tuple(end_goal.provider_ids),
            backend_neutral=True,
        )

        preservation_kind, translation_bounds, mutations = self._preservation(
            end_goal=end_goal,
            bounds=bounds,
        )
        requested = (
            _text(requested_backend, "requested_backend")
            if requested_backend
            else ""
        )
        assurance_ceiling = self._assurance_ceiling(
            end_goal=end_goal,
            preservation_kind=preservation_kind,
            requested_backend=requested,
        )
        receipt = self._build_receipt(
            goal=goal,
            ir=ir,
            property_id=prop.property_id,
            preservation_kind=preservation_kind,
            translation_bounds=translation_bounds,
            mutations=mutations,
            assumption_ids=tuple(item.assumption_id for item in assumptions),
            assurance_ceiling=assurance_ceiling,
            source_family_id=source_family_id,
            source_family_version=source_family_version,
            target_family_id=target_family_id,
            target_family_version=target_family_version,
            requested_backend=requested,
        )

        return GoalCompilationResult(
            formal_goal_id=goal.formal_goal_id,
            root_goal_id=goal.root_goal_id,
            end_goal_content_id=end_goal.content_id,
            formal_goal_content_id=goal.content_id,
            selected_interpretation_id=goal.selected_interpretation_id,
            ir=ir,
            translation_receipt=receipt,
            root_obligations=(root_obligation,),
            assurance_ceiling=assurance_ceiling,
            preservation_kind=preservation_kind,
            status=CompilationStatus.SUCCESS,
            compiler_version=self._compiler_version,
            metadata=FrozenMap(
                {
                    "requested_backend": requested,
                    "provider_ids": list(end_goal.provider_ids),
                    "property_class": property_class.value,
                }
            ),
        )

    # -- coercion / fail-closed gates -------------------------------------

    def _coerce_formal_goal(
        self, value: FormalGoal | Mapping[str, Any]
    ) -> FormalGoal:
        if isinstance(value, FormalGoal):
            return value
        if isinstance(value, Mapping):
            try:
                return FormalGoal.from_dict(value)
            except TacticianContractError as error:
                raise GoalCompilerError(str(error)) from error
        raise GoalCompilerError("formal_goal must be a FormalGoal or mapping")

    def _require_compilable(self, goal: FormalGoal) -> None:
        end_goal = goal.end_goal
        if end_goal.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION:
            raise GoalCompilerError(
                "material ambiguity requires interpretation selection before compilation"
            )
        if end_goal.ambiguity_status is AmbiguityStatus.CANDIDATES_PRESENT:
            raise GoalCompilerError(
                "material ambiguity candidates remain; select an interpretation first"
            )
        if end_goal.ambiguity_status is AmbiguityStatus.UNSUPPORTED:
            raise GoalCompilerError(
                "unsupported ambiguity state cannot be compiled into shared IR"
            )
        if goal.status not in {"confirmed", "selected", "resolved"}:
            # Confirmed is the primary status; allow a small closed set.
            raise GoalCompilerError(
                f"formal goal status {goal.status!r} is not compilable; "
                "require confirmed/selected/resolved"
            )
        if end_goal.interpretations and not goal.selected_interpretation_id:
            raise GoalCompilerError(
                "selected_interpretation_id is required when interpretations exist"
            )
        if end_goal.interpretations:
            selected_ids = {item.interpretation_id for item in end_goal.interpretations}
            if goal.selected_interpretation_id not in selected_ids:
                raise GoalCompilerError(
                    "selected_interpretation_id must reference an EndGoalSpec interpretation"
                )
        material_losses = [
            item for item in end_goal.translation_loss if _is_material_loss_token(item)
        ]
        if material_losses:
            raise GoalCompilerError(
                "material translation loss fails closed before shared-IR compilation: "
                + ", ".join(material_losses)
            )
        if end_goal.unsupported_semantics:
            raise GoalCompilerError(
                "unsupported semantics fail closed before shared-IR compilation: "
                + ", ".join(end_goal.unsupported_semantics)
            )
        if end_goal.property_class is PropertyClass.UNSPECIFIED:
            interpretation = _selected_interpretation(goal)
            if (
                interpretation is None
                or interpretation.property_class is PropertyClass.UNSPECIFIED
            ):
                raise GoalCompilerError(
                    "cannot compile an unspecified property class into shared IR"
                )

    # -- provenance materialization ---------------------------------------

    def _materialize_provenance(
        self, end_goal: EndGoalSpec
    ) -> tuple[
        tuple[str, ...],
        tuple[str, ...],
        tuple[SourceRef, ...],
        tuple[SourceSpan, ...],
    ]:
        source_binding = end_goal.source
        ref_ids: list[str] = list(source_binding.source_ref_ids)
        span_ids: list[str] = list(source_binding.span_ids)

        for provenance in end_goal.provenance:
            for ref in provenance.source_ref_ids:
                if ref not in ref_ids:
                    ref_ids.append(ref)
            for span in provenance.span_ids:
                if span not in span_ids:
                    span_ids.append(span)

        for assumption in end_goal.assumptions:
            for ref in assumption.source.source_ref_ids:
                if ref not in ref_ids:
                    ref_ids.append(ref)
            for span in assumption.source.span_ids:
                if span not in span_ids:
                    span_ids.append(span)

        if not ref_ids and source_binding.tree_id:
            # Tree-only binding: synthesize a stable source ref from the tree.
            ref_ids.append(_sanitize_id(source_binding.tree_id, prefix="source"))

        if not ref_ids:
            return (), (), (), ()

        primary_ref = ref_ids[0]
        sources: list[SourceRef] = []
        for ref_id in ref_ids:
            digest = _stable_hex(
                "source-ref",
                end_goal.content_id,
                ref_id,
                source_binding.tree_id,
                source_binding.snapshot_id,
            )
            sources.append(
                SourceRef(
                    ref_id=ref_id,
                    source_uri=f"goal-source://{ref_id}",
                    source_id=ref_id,
                    source_revision=source_binding.snapshot_id
                    or source_binding.tree_id
                    or end_goal.content_id,
                    content_sha256=digest,
                )
            )

        # Map span_id → optional provenance offsets.
        provenance_offsets: dict[str, tuple[int, int]] = {}
        for provenance in end_goal.provenance:
            for span_id in provenance.span_ids:
                provenance_offsets[span_id] = (
                    provenance.start_offset,
                    max(provenance.end_offset, provenance.start_offset + 1),
                )

        known_refs = {item.ref_id for item in sources}

        def _span_source_ref(span_id: str) -> str:
            if source_binding.span_ids and span_id in source_binding.span_ids:
                if source_binding.source_ref_ids:
                    candidate = source_binding.source_ref_ids[0]
                    if candidate in known_refs:
                        return candidate
            for provenance in end_goal.provenance:
                if span_id in provenance.span_ids and provenance.source_ref_ids:
                    candidate = provenance.source_ref_ids[0]
                    if candidate in known_refs:
                        return candidate
            for assumption in end_goal.assumptions:
                if (
                    span_id in assumption.source.span_ids
                    and assumption.source.source_ref_ids
                ):
                    candidate = assumption.source.source_ref_ids[0]
                    if candidate in known_refs:
                        return candidate
            return primary_ref

        spans: list[SourceSpan] = []
        for index, span_id in enumerate(span_ids):
            start, end = provenance_offsets.get(span_id, (index, index + 1))
            if end <= start:
                end = start + 1
            spans.append(
                SourceSpan(
                    span_id=span_id,
                    source_ref_id=_span_source_ref(span_id),
                    start_byte=start,
                    end_byte=end,
                )
            )

        return (
            tuple(ref_ids),
            tuple(span_ids),
            tuple(sources),
            tuple(spans),
        )

    # -- IR builders ------------------------------------------------------

    def _build_declarations(
        self,
        *,
        end_goal: EndGoalSpec,
        property_class: PropertyClass,
        quantifiers: Sequence[QuantifierKind],
        current_state: Mapping[str, Any],
        target_state: Mapping[str, Any],
        environment: Mapping[str, Any],
        source_ref_ids: Sequence[str],
        span_ids: Sequence[str],
    ) -> tuple[VerificationDeclaration, ...]:
        refs = tuple(source_ref_ids)
        spans = tuple(span_ids) if span_ids else ()
        # Every declaration needs a source map; use refs (required non-empty).
        source_kwargs: dict[str, Any] = {"source_ref_ids": refs}
        if spans:
            source_kwargs["span_ids"] = spans

        declarations: list[VerificationDeclaration] = []

        state_id = _sanitize_id(f"{end_goal.goal_id}:state", prefix="decl")
        declarations.append(
            VerificationDeclaration(
                declaration_id=state_id,
                kind=DeclarationKind.STATE,
                name="goal-state-model",
                payload={
                    "state_variables": list(end_goal.state_variables),
                    "current_state": _mapping_json(current_state),
                    "target_state": _mapping_json(target_state),
                    "actors": list(end_goal.actors),
                },
                **source_kwargs,
            )
        )

        transition_ids: list[str] = []
        for transition in end_goal.transitions:
            transition_id = _sanitize_id(
                f"{end_goal.goal_id}:transition:{transition}", prefix="decl"
            )
            transition_ids.append(transition_id)
            declarations.append(
                VerificationDeclaration(
                    declaration_id=transition_id,
                    kind=DeclarationKind.TRANSITION,
                    name=str(transition),
                    payload={
                        "transition": str(transition),
                        "from_state": _mapping_json(current_state),
                        "to_state": _mapping_json(target_state),
                    },
                    depends_on=(state_id,),
                    **source_kwargs,
                )
            )

        env_id = _sanitize_id(f"{end_goal.goal_id}:environment", prefix="decl")
        declarations.append(
            VerificationDeclaration(
                declaration_id=env_id,
                kind=DeclarationKind.POLICY,
                name="goal-environment",
                payload={
                    "environment": _mapping_json(environment),
                    "interference": _mapping_json(end_goal.interference),
                },
                depends_on=(state_id,),
                **source_kwargs,
            )
        )

        contract_id = _sanitize_id(f"{end_goal.goal_id}:contract", prefix="decl")
        declarations.append(
            VerificationDeclaration(
                declaration_id=contract_id,
                kind=DeclarationKind.CONTRACT,
                name="goal-root-contract",
                payload={
                    "property_class": property_class.value,
                    "quantifiers": [item.value for item in quantifiers],
                    "current_state": _mapping_json(current_state),
                    "target_state": _mapping_json(target_state),
                    "transition_ids": transition_ids,
                    "environment_declaration_id": env_id,
                    "acceptance_evidence": list(end_goal.acceptance_evidence),
                    "expected_receipt_classes": list(
                        end_goal.expected_receipt_classes
                    ),
                },
                depends_on=tuple(
                    [state_id, env_id, *transition_ids]
                ),
                **source_kwargs,
            )
        )

        return tuple(declarations)

    def _build_assumptions(
        self,
        *,
        end_goal: EndGoalSpec,
        subject_ids: Sequence[str],
        fallback_source_ref_ids: Sequence[str],
        fallback_span_ids: Sequence[str],
    ) -> tuple[VerificationAssumption, ...]:
        if not end_goal.assumptions:
            return ()
        primary_subject = subject_ids[0] if subject_ids else ()
        results: list[VerificationAssumption] = []
        for binding in end_goal.assumptions:
            refs = binding.source.source_ref_ids or tuple(fallback_source_ref_ids)
            spans = binding.source.span_ids or tuple(fallback_span_ids)
            if not refs and not spans:
                refs = tuple(fallback_source_ref_ids)
            kind = map_assumption_kind(binding.assumption_class)
            # Preserve assumption class on the expression and as a namespaced
            # extension so survivors of compilation remain queryable.
            results.append(
                VerificationAssumption(
                    assumption_id=binding.assumption_id,
                    statement=binding.statement
                    or f"assumption {binding.assumption_id}",
                    kind=kind,
                    expression={
                        "assumption_class": binding.assumption_class.value,
                        "kind": binding.kind,
                        "authority": binding.authority.value,
                        "reviewable": binding.reviewable,
                        "statement": binding.statement,
                    },
                    subject_ids=(primary_subject,) if primary_subject else (),
                    source_ref_ids=refs,
                    span_ids=spans,
                    extensions={
                        "tactician.assumption_class": binding.assumption_class.value,
                        "tactician.assumption_kind": binding.kind,
                    },
                )
            )
        return tuple(results)

    def _build_bounds(
        self,
        *,
        end_goal: EndGoalSpec,
        source_ref_ids: Sequence[str],
        span_ids: Sequence[str],
    ) -> tuple[VerificationBound, ...]:
        bounds = end_goal.bounds
        if not _bounds_have_limits(bounds):
            return ()
        limits = _resource_limits(bounds)
        source_kwargs: dict[str, Any] = {"source_ref_ids": tuple(source_ref_ids)}
        if span_ids:
            source_kwargs["span_ids"] = tuple(span_ids)

        kind = BoundednessKind.RESOURCE_BOUNDED
        if bounds.max_steps and not (
            bounds.wall_time_ms or bounds.memory_bytes or bounds.model_token_limit
        ):
            kind = BoundednessKind.STEP_BOUNDED
        elif bounds.max_steps:
            kind = BoundednessKind.FINITE_TRACE

        bound = VerificationBound(
            bound_id=_sanitize_id(f"{end_goal.goal_id}:resource-bounds", prefix="bound"),
            kind=kind,
            limits=limits,
            description="Finite resource bounds compiled from EndGoalSpec.ResourceBounds",
            **source_kwargs,
        )
        return (bound,)

    def _build_root_property(
        self,
        *,
        goal: FormalGoal,
        property_class: PropertyClass,
        property_kind: PropertyKind,
        quantifiers: Sequence[QuantifierKind],
        current_state: Mapping[str, Any],
        target_state: Mapping[str, Any],
        subject_ids: Sequence[str],
        assumption_ids: Sequence[str],
        bound_ids: Sequence[str],
        source_ref_ids: Sequence[str],
        span_ids: Sequence[str],
    ) -> VerificationProperty:
        end_goal = goal.end_goal
        interpretation = _selected_interpretation(goal)
        if interpretation is not None and interpretation.controlled_english:
            statement = interpretation.controlled_english
        else:
            statement = (
                f"{property_class.value}: {end_goal.caller_text}".strip()
            )
        expression = {
            "property_class": property_class.value,
            "quantifiers": [item.value for item in quantifiers],
            "current_state": _mapping_json(current_state),
            "target_state": _mapping_json(target_state),
            "caller_text": end_goal.caller_text,
            "root_goal_id": end_goal.root_goal_id,
            "formal_goal_id": goal.formal_goal_id,
            "selected_interpretation_id": goal.selected_interpretation_id,
        }
        source_kwargs: dict[str, Any] = {"source_ref_ids": tuple(source_ref_ids)}
        if span_ids:
            source_kwargs["span_ids"] = tuple(span_ids)
        return VerificationProperty(
            property_id=_sanitize_id(f"{goal.formal_goal_id}:root", prefix="property"),
            kind=property_kind,
            statement=statement,
            expression=expression,
            logic_family=end_goal.logic_family or "software_verification",
            subject_ids=tuple(subject_ids),
            assumption_ids=tuple(assumption_ids),
            bound_ids=tuple(bound_ids),
            extensions={
                "tactician.property_class": property_class.value,
                "tactician.assurance_target": end_goal.assurance_target.value,
            },
            **source_kwargs,
        )

    # -- receipt / authority ----------------------------------------------

    def _preservation(
        self,
        *,
        end_goal: EndGoalSpec,
        bounds: Sequence[VerificationBound],
    ) -> tuple[
        PreservationKind,
        tuple[TranslationBound, ...],
        tuple[SemanticMutation, ...],
    ]:
        translation_bounds: list[TranslationBound] = []
        mutations: list[SemanticMutation] = []
        if bounds:
            for bound in bounds:
                translation_bounds.append(
                    TranslationBound(
                        bound_id=bound.bound_id,
                        kind=bound.kind
                        if isinstance(bound.kind, BoundednessKind)
                        else BoundednessKind(str(bound.kind)),
                        limits=dict(bound.limits.to_dict()),
                        description=bound.description
                        or "Finite bound introduced by goal compilation",
                    )
                )
                mutations.append(
                    SemanticMutation(
                        mutation_id=_sanitize_id(
                            f"{bound.bound_id}:introduced", prefix="mutation"
                        ),
                        kind=SemanticMutationKind.BOUND_INTRODUCED,
                        description=(
                            f"Compilation introduced finite bound {bound.bound_id}"
                        ),
                        target_construct_ids=(bound.bound_id,),
                        bound_ids=(bound.bound_id,),
                    )
                )
            return (
                PreservationKind.BOUNDED,
                tuple(translation_bounds),
                tuple(mutations),
            )
        # Lossless structural encoding of the confirmed goal into shared IR.
        return PreservationKind.EXACT, (), ()

    def _assurance_ceiling(
        self,
        *,
        end_goal: EndGoalSpec,
        preservation_kind: PreservationKind,
        requested_backend: str,
    ) -> EvidenceAuthority:
        """Compute the translation authority ceiling.

        Backend / provider selection is intentionally ignored for elevation:
        a stronger backend cannot raise assurance above the preservation class
        or the end-goal assurance target.
        """

        del requested_backend  # authority-neutral by design
        target = map_evidence_authority(end_goal.assurance_target)
        maximum = maximum_authority_for(preservation_kind)
        ceiling = _authority_min(target, maximum)
        # Provider lists also cannot raise the ceiling.
        for _provider in end_goal.provider_ids:
            ceiling = _authority_min(ceiling, maximum)
        return ceiling

    def _build_receipt(
        self,
        *,
        goal: FormalGoal,
        ir: SoftwareVerificationIR,
        property_id: str,
        preservation_kind: PreservationKind,
        translation_bounds: Sequence[TranslationBound],
        mutations: Sequence[SemanticMutation],
        assumption_ids: Sequence[str],
        assurance_ceiling: EvidenceAuthority,
        source_family_id: str,
        source_family_version: str,
        target_family_id: str,
        target_family_version: str,
        requested_backend: str,
    ) -> LogicTranslationReceipt:
        implementation_identity = "sha256:" + _stable_hex(
            COMPILER_IMPLEMENTATION_SEED.decode("utf-8"),
            self._compiler_version,
        )
        configuration_identity = "sha256:" + _stable_hex(
            goal.content_id,
            ir.document_id,
            requested_backend or "none",
        )
        compiler = CompilerBinding(
            compiler_id=COMPILER_ID,
            compiler_version=self._compiler_version,
            implementation_identity=implementation_identity,
            configuration_identity=configuration_identity,
            stage="goal-to-sv-ir",
        )
        claim = PreservationClaim(
            kind=preservation_kind,
            preserved_property_ids=(property_id,),
            permitted_result_classes=(
                "proved",
                "disproved",
                "bounded",
                "unsupported",
                "unknown",
            ),
            description=(
                "Confirmed EndGoalSpec compiled into backend-neutral "
                "SoftwareVerificationIR without provider syntax."
            ),
        )
        # Unsupported constructs remain empty on the success path: material
        # unsupported semantics fail closed before receipt construction.
        return LogicTranslationReceipt(
            source_identity=goal.content_id,
            target_identity=ir.document_id,
            source_family_id=source_family_id,
            source_family_version=source_family_version,
            target_family_id=target_family_id,
            target_family_version=target_family_version,
            compilers=(compiler,),
            preservation_claim=claim,
            authority_ceiling=assurance_ceiling,
            assumptions=tuple(assumption_ids),
            bounds=tuple(translation_bounds),
            unsupported_constructs=(),
            semantic_mutations=tuple(mutations),
            metadata={
                "formal_goal_id": goal.formal_goal_id,
                "root_goal_id": goal.root_goal_id,
                "end_goal_id": goal.end_goal.goal_id,
                "selected_interpretation_id": goal.selected_interpretation_id,
                "requested_backend": requested_backend,
                "provider_ids": list(goal.end_goal.provider_ids),
                "compiler_interface": self.INTERFACE,
            },
        )


def compile_formal_goal(
    formal_goal: FormalGoal | Mapping[str, Any],
    *,
    requested_backend: str | None = None,
) -> GoalCompilationResult:
    """Module-level convenience wrapper around :class:`FormalGoalCompiler`."""

    return FormalGoalCompiler().compile(
        formal_goal, requested_backend=requested_backend
    )


__all__ = [
    "COMPILER_ID",
    "FORMAL_GOAL_COMPILER_INTERFACE",
    "FORMAL_GOAL_COMPILER_SCHEMA",
    "FORMAL_GOAL_COMPILER_VERSION",
    "GOAL_COMPILATION_RESULT_SCHEMA",
    "ROOT_OBLIGATION_SCHEMA",
    "SOURCE_FAMILY_ID",
    "TARGET_FAMILY_ID",
    "CompilationStatus",
    "FormalGoalCompiler",
    "GoalCompilationResult",
    "GoalCompilerError",
    "RootObligation",
    "compile_formal_goal",
    "map_assumption_kind",
    "map_evidence_authority",
    "map_property_kind",
]
