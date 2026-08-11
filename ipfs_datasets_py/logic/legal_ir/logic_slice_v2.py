"""Legal IR vertical logic slices (LFP2-025).

Interface: ``LegalLogicSlice@2``

Connects Legal IR **base norm**, **exception**, **event**, and **jurisdiction**
claims to :class:`~ipfs_datasets_py.logic.formalization.artifacts_v3.DomainLogicSliceV2`
and :class:`~ipfs_datasets_py.logic.formalization.artifacts_v3.FormalizationArtifactV3`
through base/common typed evidence paths already available after frontend and
translation convergence (LFP2-019, LFP2-021).

Every admitted legal slice makes the following axes **explicit** (never
inferred from family names alone):

* deontic profile (monadic / dyadic / conditional / defeasible form)
* temporal model (time density, trace model, event order anchors)
* defeasibility (exceptions, defeaters, unresolved conflicts)
* jurisdiction (territory / subject-matter / authority scope)
* priority (ordered norm identities)
* authority (result ceiling; natural-language extraction is never proof)

``graph_projection``, ``proof_translation``, and ``structural_round_trip``
remain operation / view roles — **never** semantic families.

Overlays for full normative, argumentation, and description-logic families
attach later via LFP2-044 after LFP2-037–039.  This module stays on base
families: ``deontic``, ``tdfol``, ``event_calculus``, ``authorization``,
and ``frame_logic``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    LogicObligationV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    encoding_id,
    evidence_id,
    family_id,
    notation_id,
    profile_id,
    property_id,
    view_id,
)
from ipfs_datasets_py.logic.families.profiles import (
    NormForm,
    PermissionStrength,
    TimeDensity,
    TraceModel,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DomainLogicSliceV2,
    DomainSliceStatus,
    FormalizationArtifactStatus,
    FormalizationArtifactV3,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.legal_ir.typed_adapter import (
    LEGAL_FORMALIZATION_ADAPTER_INTERFACE,
    NEVER_FAMILY_OPERATION_ROLES,
    AmbiguityRecord,
    LegalFormalizationAdapter,
    LegalLogicRoute,
    NormConflict,
    RouteNamespace,
    detect_norm_conflicts,
    is_never_family_label,
    looks_like_natural_language,
    reject_natural_language_proof_authority,
    reject_operation_role_as_family,
    resolve_legal_route,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SourceDocument,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    propositional_signature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LEGAL_LOGIC_SLICE_V2_INTERFACE: Final = "LegalLogicSlice@2"
LEGAL_LOGIC_SLICE_V2_SCHEMA_VERSION: Final = "legal-logic-slice/v2"
LEGAL_LOGIC_SLICE_BUNDLE_SCHEMA: Final = "legal-logic-slice-bundle/v2"
LEGAL_LOGIC_SLICE_MODULE_VERSION: Final = "1.0.0"

LEGAL_IR_DOMAIN_ID: Final = "legal_ir"
LEGAL_IR_TYPED_DOMAIN: Final = "legal"
LEGAL_LOGIC_SLICE_PRODUCER_ID: Final = "legal-ir-logic-slice-v2"

# Explicit axis schema versions.
LEGAL_DEONTIC_PROFILE_SCHEMA: Final = "legal-deontic-profile/v1"
LEGAL_TEMPORAL_MODEL_SCHEMA: Final = "legal-temporal-model/v1"
LEGAL_DEFEASIBILITY_SCHEMA: Final = "legal-defeasibility/v1"
LEGAL_JURISDICTION_SCHEMA: Final = "legal-jurisdiction/v1"
LEGAL_PRIORITY_SCHEMA: Final = "legal-priority/v1"
LEGAL_AUTHORITY_SCHEMA: Final = "legal-authority-binding/v1"
LEGAL_CLAIM_SCHEMA: Final = "legal-slice-claim/v1"

# Stable diagnostic codes.
CODE_MALFORMED: Final = "legal_slice.malformed"
CODE_MISSING_AXIS: Final = "legal_slice.missing_axis"
CODE_GRAPH_AS_FAMILY: Final = "legal_slice.graph_projection_not_family"
CODE_OPERATION_AS_FAMILY: Final = "legal_slice.operation_role_as_family"
CODE_NL_PROOF: Final = "legal_slice.nl_not_proof"
CODE_AUTHORITY: Final = "legal_slice.authority_rejected"
CODE_UNKNOWN_KIND: Final = "legal_slice.unknown_kind"
CODE_ROUTE: Final = "legal_slice.route_error"
CODE_LINEAGE: Final = "legal_slice.lineage"
CODE_UNSUPPORTED_OVERLAY: Final = "legal_slice.unsupported_overlay"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_MALFORMED,
        CODE_MISSING_AXIS,
        CODE_GRAPH_AS_FAMILY,
        CODE_OPERATION_AS_FAMILY,
        CODE_NL_PROOF,
        CODE_AUTHORITY,
        CODE_UNKNOWN_KIND,
        CODE_ROUTE,
        CODE_LINEAGE,
        CODE_UNSUPPORTED_OVERLAY,
    }
)

# Evidence-subset kinds from LFP2-025.
LEGAL_EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "norm",
    "policy",
    "exception",
    "priority",
    "event",
    "conflict",
    "jurisdiction",
)

# Operation / view roles that must never become families on legal slices.
LEGAL_NEVER_FAMILY_VIEW_ROLES: Final[frozenset[str]] = frozenset(
    NEVER_FAMILY_OPERATION_ROLES
    | {
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
        "knowledge_graphs",
        "knowledge_graph",
        "neo4j_compat",
    }
)

# Future overlays deferred to LFP2-044 after LFP2-037–039.
LEGAL_DEFERRED_OVERLAY_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "argumentation",
        "description_logic",
        "defeasible_logic",
        "nonmonotonic_logic",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_JURISDICTION_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LegalSliceKind(StrEnum):
    """Closed set of base Legal IR vertical-slice kinds (LFP2-025)."""

    BASE_NORM = "base_norm"
    EXCEPTION = "exception"
    EVENT = "event"
    JURISDICTION = "jurisdiction"
    PRIORITY = "priority"
    CONFLICT = "conflict"
    POLICY = "policy"


class LegalAuthorityRole(StrEnum):
    """What a legal slice may claim about proof/result authority."""

    NONE = "none"
    CANDIDATE = "candidate"
    DECLARATION = "declaration"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    # Kernel/backend only — never assigned by legal slice construction alone.
    OFFICIAL = "official"


class LegalSourceKind(StrEnum):
    """Origin of the legal claim feeding a slice."""

    SYMBOLIC = "symbolic"
    STRUCTURED = "structured"
    NATURAL_LANGUAGE = "natural_language"
    MIXED = "mixed"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegalLogicSliceError(ValueError):
    """Raised when a LegalLogicSlice@2 request or record is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_ROUTE,
        path: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code if code in _ALL_CODES else CODE_ROUTE
        self.path = path


class GraphProjectionAsFamilyError(LegalLogicSliceError):
    """Raised when graph projection is offered as a semantic family."""

    def __init__(self, label: str = "graph_projection", *, path: str = "family") -> None:
        super().__init__(
            f"{label!r} is a view/operation role, never a semantic family",
            code=CODE_GRAPH_AS_FAMILY,
            path=path,
        )
        self.label = label


class MissingLegalAxisError(LegalLogicSliceError):
    """Raised when a required explicit axis is omitted."""

    def __init__(self, axis: str, *, path: str = "") -> None:
        super().__init__(
            f"legal slice requires explicit {axis}",
            code=CODE_MISSING_AXIS,
            path=path or axis,
        )
        self.axis = axis


class LegalAuthorityRejectedError(LegalLogicSliceError):
    """Raised when authority claims exceed the legal slice ceiling."""

    def __init__(self, message: str, *, path: str = "authority") -> None:
        super().__init__(message, code=CODE_AUTHORITY, path=path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identifier(value: object, field_name: str) -> str:
    text = _text(value, field_name, maximum=256)
    if not _ID_RE.fullmatch(text):
        raise LegalLogicSliceError(
            f"{field_name} must be a stable identifier; got {text!r}",
            code=CODE_MALFORMED,
            path=field_name,
        )
    return text


def _optional_text(value: object, field_name: str, *, maximum: int = 512) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name, maximum=maximum)


def _string_tuple(
    value: object,
    field_name: str,
    *,
    identifiers: bool = False,
    required: bool = False,
) -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=256)
        for item in _require_sequence(value if value is not None else (), field_name)
    )
    if required and not items:
        raise LegalLogicSliceError(
            f"{field_name} must be non-empty",
            code=CODE_MALFORMED,
            path=field_name,
        )
    if identifiers:
        for item in items:
            if not _ID_RE.fullmatch(item):
                raise LegalLogicSliceError(
                    f"{field_name} item must be a stable identifier; got {item!r}",
                    code=CODE_MALFORMED,
                    path=field_name,
                )
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _feature_tuple(value: object, field_name: str) -> tuple[str, ...]:
    items = _string_tuple(value, field_name)
    for item in items:
        if not _FEATURE_RE.fullmatch(item):
            raise LegalLogicSliceError(
                f"{field_name} item must be a feature identity; got {item!r}",
                code=CODE_MALFORMED,
                path=field_name,
            )
    return tuple(sorted(set(items)))


def _jurisdiction_id(value: object, field_name: str = "jurisdiction") -> str:
    text = _text(value, field_name, maximum=128).lower().replace("_", "-")
    if not _JURISDICTION_RE.fullmatch(text):
        raise LegalLogicSliceError(
            f"{field_name} must be a lowercase hyphenated identifier; got {text!r}",
            code=CODE_MALFORMED,
            path=field_name,
        )
    return text


def _enum_value(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    text = _text(value, field_name, maximum=64)
    try:
        return enum_type(text)
    except ValueError as error:
        raise LegalLogicSliceError(
            f"{field_name} must be a {enum_type.__name__} value; got {text!r}",
            code=CODE_MALFORMED,
            path=field_name,
        ) from error


def _profile_enum(value: object, enum_type: type, field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    text = str(value or "").strip()
    try:
        return enum_type(text)
    except ValueError as error:
        raise LegalLogicSliceError(
            f"{field_name} must be a {enum_type.__name__} value; got {text!r}",
            code=CODE_MALFORMED,
            path=field_name,
        ) from error


def _normalize_label(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("-", "_").replace(" ", "_").replace(".", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def is_graph_projection_label(label: object) -> bool:
    """Return True when *label* names the graph-projection view role."""

    normalized = _normalize_label(label)
    return normalized in {
        "graph_projection",
        "knowledge_graphs",
        "knowledge_graph",
        "neo4j_compat",
        "knowledge_graphs_neo4j_compat",
        "legal_ir_view_knowledge_graphs_v1",
        "legal_route_graph_projection_v1",
    } or "graph_projection" in normalized


def reject_graph_projection_as_family(
    label: object, *, path: str = "family"
) -> None:
    """Fail closed when graph projection is claimed as a semantic family."""

    if is_graph_projection_label(label) or is_never_family_label(label):
        raise GraphProjectionAsFamilyError(str(label or "graph_projection"), path=path)
    reject_operation_role_as_family(label, path=path)


# ---------------------------------------------------------------------------
# Explicit axis records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalDeonticProfileBinding:
    """Explicit deontic profile for a legal slice (never silent defaults)."""

    profile_id: str
    form: NormForm | str
    permission: PermissionStrength | str
    exceptions: bool
    priorities: bool
    contrary_to_duty: bool = False
    operator_force: str = ""
    description: str = ""
    schema_version: str = LEGAL_DEONTIC_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "deontic.profile_id")
        )
        object.__setattr__(
            self, "form", _profile_enum(self.form, NormForm, "deontic.form")
        )
        object.__setattr__(
            self,
            "permission",
            _profile_enum(self.permission, PermissionStrength, "deontic.permission"),
        )
        if not isinstance(self.exceptions, bool):
            raise LegalLogicSliceError(
                "deontic.exceptions must be a boolean",
                code=CODE_MALFORMED,
                path="deontic.exceptions",
            )
        if not isinstance(self.priorities, bool):
            raise LegalLogicSliceError(
                "deontic.priorities must be a boolean",
                code=CODE_MALFORMED,
                path="deontic.priorities",
            )
        if not isinstance(self.contrary_to_duty, bool):
            raise LegalLogicSliceError(
                "deontic.contrary_to_duty must be a boolean",
                code=CODE_MALFORMED,
                path="deontic.contrary_to_duty",
            )
        form = self.form
        permission = self.permission
        if form is NormForm.NOT_APPLICABLE or permission is PermissionStrength.NOT_APPLICABLE:
            raise MissingLegalAxisError("deontic_profile", path="deontic")
        object.__setattr__(
            self, "operator_force", _optional_text(self.operator_force, "deontic.operator_force")
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "deontic.description", maximum=1024)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contrary_to_duty": self.contrary_to_duty,
            "description": self.description,
            "exceptions": self.exceptions,
            "form": self.form.value if isinstance(self.form, NormForm) else str(self.form),
            "operator_force": self.operator_force,
            "permission": (
                self.permission.value
                if isinstance(self.permission, PermissionStrength)
                else str(self.permission)
            ),
            "priorities": self.priorities,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalDeonticProfileBinding":
        payload = _require_mapping(data, "LegalDeonticProfileBinding")
        return cls(
            profile_id=str(payload.get("profile_id") or ""),
            form=str(payload.get("form") or NormForm.NOT_APPLICABLE.value),
            permission=str(
                payload.get("permission") or PermissionStrength.NOT_APPLICABLE.value
            ),
            exceptions=bool(payload.get("exceptions", False)),
            priorities=bool(payload.get("priorities", False)),
            contrary_to_duty=bool(payload.get("contrary_to_duty", False)),
            operator_force=str(payload.get("operator_force") or ""),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or LEGAL_DEONTIC_PROFILE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalTemporalModelBinding:
    """Explicit temporal model for a legal slice."""

    model_id: str
    density: TimeDensity | str
    trace_model: TraceModel | str
    event_order: bool = True
    temporal_anchors: tuple[str, ...] = ()
    metric_intervals: bool = False
    description: str = ""
    schema_version: str = LEGAL_TEMPORAL_MODEL_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "model_id", _identifier(self.model_id, "temporal.model_id")
        )
        object.__setattr__(
            self, "density", _profile_enum(self.density, TimeDensity, "temporal.density")
        )
        object.__setattr__(
            self,
            "trace_model",
            _profile_enum(self.trace_model, TraceModel, "temporal.trace_model"),
        )
        density = self.density
        trace = self.trace_model
        if density is TimeDensity.NOT_APPLICABLE or trace is TraceModel.NOT_APPLICABLE:
            raise MissingLegalAxisError("temporal_model", path="temporal")
        if not isinstance(self.event_order, bool):
            raise LegalLogicSliceError(
                "temporal.event_order must be a boolean",
                code=CODE_MALFORMED,
                path="temporal.event_order",
            )
        if not isinstance(self.metric_intervals, bool):
            raise LegalLogicSliceError(
                "temporal.metric_intervals must be a boolean",
                code=CODE_MALFORMED,
                path="temporal.metric_intervals",
            )
        object.__setattr__(
            self,
            "temporal_anchors",
            _string_tuple(self.temporal_anchors, "temporal.temporal_anchors"),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "temporal.description", maximum=1024),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "density": self.density.value if isinstance(self.density, TimeDensity) else str(self.density),
            "description": self.description,
            "event_order": self.event_order,
            "metric_intervals": self.metric_intervals,
            "model_id": self.model_id,
            "schema_version": self.schema_version,
            "temporal_anchors": list(self.temporal_anchors),
            "trace_model": (
                self.trace_model.value
                if isinstance(self.trace_model, TraceModel)
                else str(self.trace_model)
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalTemporalModelBinding":
        payload = _require_mapping(data, "LegalTemporalModelBinding")
        return cls(
            model_id=str(payload.get("model_id") or ""),
            density=str(payload.get("density") or TimeDensity.NOT_APPLICABLE.value),
            trace_model=str(
                payload.get("trace_model") or TraceModel.NOT_APPLICABLE.value
            ),
            event_order=bool(payload.get("event_order", True)),
            temporal_anchors=tuple(payload.get("temporal_anchors") or ()),
            metric_intervals=bool(payload.get("metric_intervals", False)),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or LEGAL_TEMPORAL_MODEL_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalDefeasibilityBinding:
    """Explicit defeasibility / exception structure for a legal slice."""

    enabled: bool
    exception_ids: tuple[str, ...] = ()
    defeater_scope: tuple[str, ...] = ()
    unresolved_conflicts: bool = False
    description: str = ""
    schema_version: str = LEGAL_DEFEASIBILITY_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise LegalLogicSliceError(
                "defeasibility.enabled must be a boolean",
                code=CODE_MALFORMED,
                path="defeasibility.enabled",
            )
        object.__setattr__(
            self,
            "exception_ids",
            _string_tuple(self.exception_ids, "defeasibility.exception_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "defeater_scope",
            _string_tuple(self.defeater_scope, "defeasibility.defeater_scope"),
        )
        if not isinstance(self.unresolved_conflicts, bool):
            raise LegalLogicSliceError(
                "defeasibility.unresolved_conflicts must be a boolean",
                code=CODE_MALFORMED,
                path="defeasibility.unresolved_conflicts",
            )
        if self.enabled and not self.exception_ids and not self.defeater_scope:
            # Defeasibility may be enabled with empty exceptions when the slice
            # kind is base_norm declaring that defeaters are admitted but not
            # yet attached — still explicit.
            pass
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "defeasibility.description", maximum=1024),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "defeater_scope": list(self.defeater_scope),
            "description": self.description,
            "enabled": self.enabled,
            "exception_ids": list(self.exception_ids),
            "schema_version": self.schema_version,
            "unresolved_conflicts": self.unresolved_conflicts,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalDefeasibilityBinding":
        payload = _require_mapping(data, "LegalDefeasibilityBinding")
        return cls(
            enabled=bool(payload.get("enabled", False)),
            exception_ids=tuple(payload.get("exception_ids") or ()),
            defeater_scope=tuple(payload.get("defeater_scope") or ()),
            unresolved_conflicts=bool(payload.get("unresolved_conflicts", False)),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or LEGAL_DEFEASIBILITY_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalJurisdictionBinding:
    """Explicit jurisdiction / authority-scope binding for a legal slice."""

    jurisdiction: str
    territory: str = ""
    subject_matter: str = ""
    authority_id: str = ""
    authority_kind: str = "statute"
    description: str = ""
    schema_version: str = LEGAL_JURISDICTION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "jurisdiction", _jurisdiction_id(self.jurisdiction, "jurisdiction")
        )
        object.__setattr__(
            self, "territory", _optional_text(self.territory, "jurisdiction.territory")
        )
        object.__setattr__(
            self,
            "subject_matter",
            _optional_text(self.subject_matter, "jurisdiction.subject_matter"),
        )
        if self.authority_id:
            object.__setattr__(
                self,
                "authority_id",
                _identifier(self.authority_id, "jurisdiction.authority_id"),
            )
        object.__setattr__(
            self,
            "authority_kind",
            _optional_text(self.authority_kind, "jurisdiction.authority_kind") or "statute",
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "jurisdiction.description", maximum=1024),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "authority_kind": self.authority_kind,
            "description": self.description,
            "jurisdiction": self.jurisdiction,
            "schema_version": self.schema_version,
            "subject_matter": self.subject_matter,
            "territory": self.territory,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalJurisdictionBinding":
        payload = _require_mapping(data, "LegalJurisdictionBinding")
        return cls(
            jurisdiction=str(payload.get("jurisdiction") or ""),
            territory=str(payload.get("territory") or ""),
            subject_matter=str(payload.get("subject_matter") or ""),
            authority_id=str(payload.get("authority_id") or ""),
            authority_kind=str(payload.get("authority_kind") or "statute"),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or LEGAL_JURISDICTION_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalPriorityBinding:
    """Explicit priority ordering over norms / exceptions."""

    ordered_ids: tuple[str, ...]
    relation: str = "strict_total"
    description: str = ""
    schema_version: str = LEGAL_PRIORITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ordered_ids",
            _string_tuple(
                self.ordered_ids,
                "priority.ordered_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "relation",
            _optional_text(self.relation, "priority.relation") or "strict_total",
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "priority.description", maximum=1024),
        )

    @property
    def is_empty(self) -> bool:
        return not self.ordered_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "ordered_ids": list(self.ordered_ids),
            "relation": self.relation,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalPriorityBinding":
        payload = _require_mapping(data, "LegalPriorityBinding")
        return cls(
            ordered_ids=tuple(payload.get("ordered_ids") or ()),
            relation=str(payload.get("relation") or "strict_total"),
            description=str(payload.get("description") or ""),
            schema_version=str(payload.get("schema_version") or LEGAL_PRIORITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class LegalAuthorityBinding:
    """Explicit authority ceiling for a legal slice (fail-closed)."""

    role: LegalAuthorityRole | str
    result_ceiling: ResultAuthority | str
    source_kind: LegalSourceKind | str = LegalSourceKind.SYMBOLIC
    evidence_authority: EvidenceAuthority | str = EvidenceAuthority.NONE
    nl_extraction: bool = False
    description: str = ""
    schema_version: str = LEGAL_AUTHORITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "role", _enum_value(self.role, LegalAuthorityRole, "authority.role")
        )
        if isinstance(self.result_ceiling, ResultAuthority):
            ceiling = self.result_ceiling
        else:
            try:
                ceiling = ResultAuthority(str(self.result_ceiling))
            except ValueError as error:
                raise LegalLogicSliceError(
                    f"authority.result_ceiling must be a ResultAuthority; "
                    f"got {self.result_ceiling!r}",
                    code=CODE_MALFORMED,
                    path="authority.result_ceiling",
                ) from error
        object.__setattr__(self, "result_ceiling", ceiling)
        object.__setattr__(
            self,
            "source_kind",
            _enum_value(self.source_kind, LegalSourceKind, "authority.source_kind"),
        )
        if isinstance(self.evidence_authority, EvidenceAuthority):
            evidence = self.evidence_authority
        else:
            try:
                evidence = EvidenceAuthority(str(self.evidence_authority))
            except ValueError as error:
                raise LegalLogicSliceError(
                    f"authority.evidence_authority must be EvidenceAuthority; "
                    f"got {self.evidence_authority!r}",
                    code=CODE_MALFORMED,
                    path="authority.evidence_authority",
                ) from error
        object.__setattr__(self, "evidence_authority", evidence)
        if not isinstance(self.nl_extraction, bool):
            raise LegalLogicSliceError(
                "authority.nl_extraction must be a boolean",
                code=CODE_MALFORMED,
                path="authority.nl_extraction",
            )
        role = self.role
        # Legal slices never mint official/theorem authority alone.
        if role is LegalAuthorityRole.OFFICIAL:
            raise LegalAuthorityRejectedError(
                "legal slices cannot claim official proof authority without "
                "independent kernel/backend receipts"
            )
        if ceiling is ResultAuthority.THEOREM and role is not LegalAuthorityRole.OFFICIAL:
            raise LegalAuthorityRejectedError(
                "legal slices cannot claim theorem result authority without "
                "official kernel acceptance"
            )
        if self.nl_extraction or self.source_kind is LegalSourceKind.NATURAL_LANGUAGE:
            if role in {LegalAuthorityRole.OFFICIAL, LegalAuthorityRole.BOUNDED}:
                raise LegalAuthorityRejectedError(
                    "natural-language extraction is never proof or bounded "
                    "theorem authority"
                )
            if ceiling is ResultAuthority.THEOREM:
                raise LegalAuthorityRejectedError(
                    "natural-language extraction cannot establish theorem authority"
                )
            # Force candidate ceiling for NL.
            object.__setattr__(self, "role", LegalAuthorityRole.CANDIDATE)
            object.__setattr__(self, "result_ceiling", ResultAuthority.CANDIDATE)
            object.__setattr__(self, "evidence_authority", EvidenceAuthority.NONE)
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "authority.description", maximum=1024),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "evidence_authority": (
                self.evidence_authority.value
                if isinstance(self.evidence_authority, EvidenceAuthority)
                else str(self.evidence_authority)
            ),
            "nl_extraction": self.nl_extraction,
            "result_ceiling": (
                self.result_ceiling.value
                if isinstance(self.result_ceiling, ResultAuthority)
                else str(self.result_ceiling)
            ),
            "role": self.role.value if isinstance(self.role, LegalAuthorityRole) else str(self.role),
            "schema_version": self.schema_version,
            "source_kind": (
                self.source_kind.value
                if isinstance(self.source_kind, LegalSourceKind)
                else str(self.source_kind)
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalAuthorityBinding":
        payload = _require_mapping(data, "LegalAuthorityBinding")
        return cls(
            role=str(payload.get("role") or LegalAuthorityRole.CANDIDATE.value),
            result_ceiling=str(
                payload.get("result_ceiling") or ResultAuthority.CANDIDATE.value
            ),
            source_kind=str(
                payload.get("source_kind") or LegalSourceKind.SYMBOLIC.value
            ),
            evidence_authority=str(
                payload.get("evidence_authority") or EvidenceAuthority.NONE.value
            ),
            nl_extraction=bool(payload.get("nl_extraction", False)),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or LEGAL_AUTHORITY_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Claim input
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalSliceClaim:
    """One Legal IR claim projected into a typed vertical slice."""

    claim_id: str
    kind: LegalSliceKind | str
    statement: str
    formula_id: str = ""
    actor: str = ""
    action: str = ""
    object: str = ""
    norm_type: str = ""
    conditions: tuple[str, ...] = ()
    exception_ids: tuple[str, ...] = ()
    priority_rank: int | None = None
    event_id: str = ""
    fluent_id: str = ""
    jurisdiction: str = ""
    territory: str = ""
    subject_matter: str = ""
    authority_id: str = ""
    source_kind: LegalSourceKind | str = LegalSourceKind.SYMBOLIC
    source_text: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGAL_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(
            self, "kind", _enum_value(self.kind, LegalSliceKind, "kind")
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "statement", maximum=4096)
        )
        if self.formula_id:
            object.__setattr__(
                self, "formula_id", _identifier(self.formula_id, "formula_id")
            )
        else:
            object.__setattr__(self, "formula_id", f"formula:{self.claim_id}")
        object.__setattr__(self, "actor", _optional_text(self.actor, "actor"))
        object.__setattr__(self, "action", _optional_text(self.action, "action"))
        object.__setattr__(self, "object", _optional_text(self.object, "object"))
        object.__setattr__(
            self, "norm_type", _optional_text(self.norm_type, "norm_type")
        )
        object.__setattr__(
            self, "conditions", _string_tuple(self.conditions, "conditions")
        )
        object.__setattr__(
            self,
            "exception_ids",
            _string_tuple(self.exception_ids, "exception_ids", identifiers=True),
        )
        if self.priority_rank is not None and not isinstance(self.priority_rank, int):
            raise LegalLogicSliceError(
                "priority_rank must be an integer or None",
                code=CODE_MALFORMED,
                path="priority_rank",
            )
        object.__setattr__(self, "event_id", _optional_text(self.event_id, "event_id"))
        object.__setattr__(
            self, "fluent_id", _optional_text(self.fluent_id, "fluent_id")
        )
        if self.jurisdiction:
            object.__setattr__(
                self, "jurisdiction", _jurisdiction_id(self.jurisdiction)
            )
        object.__setattr__(
            self, "territory", _optional_text(self.territory, "territory")
        )
        object.__setattr__(
            self, "subject_matter", _optional_text(self.subject_matter, "subject_matter")
        )
        if self.authority_id:
            object.__setattr__(
                self, "authority_id", _identifier(self.authority_id, "authority_id")
            )
        object.__setattr__(
            self,
            "source_kind",
            _enum_value(self.source_kind, LegalSourceKind, "source_kind"),
        )
        object.__setattr__(
            self,
            "source_text",
            _optional_text(self.source_text, "source_text", maximum=8192),
        )
        if not isinstance(self.metadata, FrozenMap):
            object.__setattr__(
                self, "metadata", FrozenMap(dict(self.metadata or {}))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "actor": self.actor,
            "authority_id": self.authority_id,
            "claim_id": self.claim_id,
            "conditions": list(self.conditions),
            "event_id": self.event_id,
            "exception_ids": list(self.exception_ids),
            "fluent_id": self.fluent_id,
            "formula_id": self.formula_id,
            "jurisdiction": self.jurisdiction,
            "kind": self.kind.value if isinstance(self.kind, LegalSliceKind) else str(self.kind),
            "metadata": dict(self.metadata),
            "norm_type": self.norm_type,
            "object": self.object,
            "priority_rank": self.priority_rank,
            "schema_version": self.schema_version,
            "source_kind": (
                self.source_kind.value
                if isinstance(self.source_kind, LegalSourceKind)
                else str(self.source_kind)
            ),
            "source_text": self.source_text,
            "statement": self.statement,
            "subject_matter": self.subject_matter,
            "territory": self.territory,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalSliceClaim":
        payload = _require_mapping(data, "LegalSliceClaim")
        return cls(
            claim_id=str(payload.get("claim_id") or ""),
            kind=str(payload.get("kind") or ""),
            statement=str(payload.get("statement") or ""),
            formula_id=str(payload.get("formula_id") or ""),
            actor=str(payload.get("actor") or ""),
            action=str(payload.get("action") or ""),
            object=str(payload.get("object") or ""),
            norm_type=str(payload.get("norm_type") or ""),
            conditions=tuple(payload.get("conditions") or ()),
            exception_ids=tuple(payload.get("exception_ids") or ()),
            priority_rank=payload.get("priority_rank"),
            event_id=str(payload.get("event_id") or ""),
            fluent_id=str(payload.get("fluent_id") or ""),
            jurisdiction=str(payload.get("jurisdiction") or ""),
            territory=str(payload.get("territory") or ""),
            subject_matter=str(payload.get("subject_matter") or ""),
            authority_id=str(payload.get("authority_id") or ""),
            source_kind=str(
                payload.get("source_kind") or LegalSourceKind.SYMBOLIC.value
            ),
            source_text=str(payload.get("source_text") or ""),
            metadata=FrozenMap(dict(payload.get("metadata") or {})),
            schema_version=str(payload.get("schema_version") or LEGAL_CLAIM_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Kind → route / axis defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _KindRouteSpec:
    """Sealed mapping from slice kind to canonical family/profile route."""

    kind: LegalSliceKind
    route_label: str
    family: str
    profile: str
    property_name: str
    view_name: str
    features: tuple[str, ...]
    deontic_profile_id: str
    deontic_form: NormForm
    deontic_permission: PermissionStrength
    deontic_exceptions: bool
    deontic_priorities: bool
    temporal_model_id: str
    temporal_density: TimeDensity
    temporal_trace: TraceModel
    temporal_event_order: bool
    defeasibility_enabled: bool
    authority_role: LegalAuthorityRole
    result_ceiling: ResultAuthority
    evidence_authority: EvidenceAuthority
    require_jurisdiction: bool
    require_priority_ids: bool


_KIND_SPECS: Final[dict[LegalSliceKind, _KindRouteSpec]] = {
    LegalSliceKind.BASE_NORM: _KindRouteSpec(
        kind=LegalSliceKind.BASE_NORM,
        route_label="deontic",
        family="deontic",
        profile="conditional_normative",
        property_name="validity",
        view_name="source",
        features=("deontic", "norm", "conditional"),
        deontic_profile_id="conditional_normative",
        deontic_form=NormForm.DYADIC,
        deontic_permission=PermissionStrength.STRONG,
        deontic_exceptions=True,
        deontic_priorities=True,
        temporal_model_id="legal_discrete_finite",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE,
        temporal_event_order=True,
        defeasibility_enabled=True,
        authority_role=LegalAuthorityRole.CANDIDATE,
        result_ceiling=ResultAuthority.CANDIDATE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=True,
        require_priority_ids=False,
    ),
    LegalSliceKind.EXCEPTION: _KindRouteSpec(
        kind=LegalSliceKind.EXCEPTION,
        route_label="defeasible",
        family="deontic",
        profile="defeasible_normative",
        property_name="validity",
        view_name="source",
        features=("deontic", "exception", "defeasible"),
        deontic_profile_id="defeasible_normative",
        deontic_form=NormForm.DYADIC,
        deontic_permission=PermissionStrength.STRONG,
        deontic_exceptions=True,
        deontic_priorities=True,
        temporal_model_id="legal_discrete_finite",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE,
        temporal_event_order=True,
        defeasibility_enabled=True,
        authority_role=LegalAuthorityRole.CANDIDATE,
        result_ceiling=ResultAuthority.CANDIDATE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=True,
        require_priority_ids=False,
    ),
    LegalSliceKind.EVENT: _KindRouteSpec(
        kind=LegalSliceKind.EVENT,
        route_label="event_calculus",
        family="event_calculus",
        profile="event_calculus",
        property_name="reachability",
        view_name="source",
        features=("event", "event_calculus", "fluent"),
        deontic_profile_id="event_norm_bridge",
        deontic_form=NormForm.MONADIC,
        deontic_permission=PermissionStrength.WEAK,
        deontic_exceptions=False,
        deontic_priorities=False,
        temporal_model_id="event_calculus_discrete",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE_OR_INFINITE,
        temporal_event_order=True,
        defeasibility_enabled=False,
        authority_role=LegalAuthorityRole.CANDIDATE,
        result_ceiling=ResultAuthority.CANDIDATE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=False,
        require_priority_ids=False,
    ),
    LegalSliceKind.JURISDICTION: _KindRouteSpec(
        kind=LegalSliceKind.JURISDICTION,
        route_label="authorization",
        family="authorization",
        profile="secpal",
        property_name="authorization",
        view_name="source",
        features=("jurisdiction", "authorization", "authority"),
        deontic_profile_id="jurisdiction_policy",
        deontic_form=NormForm.MONADIC,
        deontic_permission=PermissionStrength.STRONG,
        deontic_exceptions=True,
        deontic_priorities=True,
        temporal_model_id="legal_discrete_finite",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE,
        temporal_event_order=False,
        defeasibility_enabled=True,
        authority_role=LegalAuthorityRole.BOUNDED,
        result_ceiling=ResultAuthority.AUTHORIZATION,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=True,
        require_priority_ids=False,
    ),
    LegalSliceKind.PRIORITY: _KindRouteSpec(
        kind=LegalSliceKind.PRIORITY,
        route_label="defeasible",
        family="deontic",
        profile="defeasible_normative",
        property_name="validity",
        view_name="source",
        features=("priority", "deontic", "defeasible"),
        deontic_profile_id="defeasible_normative",
        deontic_form=NormForm.DYADIC,
        deontic_permission=PermissionStrength.STRONG,
        deontic_exceptions=True,
        deontic_priorities=True,
        temporal_model_id="legal_discrete_finite",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE,
        temporal_event_order=False,
        defeasibility_enabled=True,
        authority_role=LegalAuthorityRole.CANDIDATE,
        result_ceiling=ResultAuthority.CANDIDATE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=True,
        require_priority_ids=True,
    ),
    LegalSliceKind.CONFLICT: _KindRouteSpec(
        kind=LegalSliceKind.CONFLICT,
        route_label="deontic",
        family="deontic",
        profile="conditional_normative",
        property_name="validity",
        view_name="source",
        features=("conflict", "deontic", "norm"),
        deontic_profile_id="conditional_normative",
        deontic_form=NormForm.DYADIC,
        deontic_permission=PermissionStrength.STRONG,
        deontic_exceptions=True,
        deontic_priorities=True,
        temporal_model_id="legal_discrete_finite",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE,
        temporal_event_order=True,
        defeasibility_enabled=True,
        authority_role=LegalAuthorityRole.CANDIDATE,
        result_ceiling=ResultAuthority.CANDIDATE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=True,
        require_priority_ids=False,
    ),
    LegalSliceKind.POLICY: _KindRouteSpec(
        kind=LegalSliceKind.POLICY,
        route_label="authorization",
        family="authorization",
        profile="secpal",
        property_name="authorization",
        view_name="source",
        features=("policy", "authorization", "deontic"),
        deontic_profile_id="authorization_policy",
        deontic_form=NormForm.MONADIC,
        deontic_permission=PermissionStrength.STRONG,
        deontic_exceptions=True,
        deontic_priorities=True,
        temporal_model_id="legal_discrete_finite",
        temporal_density=TimeDensity.DISCRETE,
        temporal_trace=TraceModel.FINITE,
        temporal_event_order=False,
        defeasibility_enabled=True,
        authority_role=LegalAuthorityRole.BOUNDED,
        result_ceiling=ResultAuthority.AUTHORIZATION,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        require_jurisdiction=True,
        require_priority_ids=False,
    ),
}


def legal_slice_kind_specs() -> Mapping[LegalSliceKind, _KindRouteSpec]:
    """Return the sealed kind → route specification map."""

    return _KIND_SPECS


# ---------------------------------------------------------------------------
# LegalLogicSlice@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalLogicSliceV2:
    """One admitted Legal IR vertical slice with explicit semantic axes.

    Interface: ``LegalLogicSlice@2``.

    Binds:

    * claim identity and slice kind (base_norm / exception / event / jurisdiction …)
    * explicit deontic profile, temporal model, defeasibility, jurisdiction,
      priority, and authority bindings
    * a :class:`DomainLogicSliceV2` with source + typed-expression lineage
    * the canonical :class:`LegalLogicRoute` used for family/profile routing

    Graph projection and other operation roles are rejected at construction.
    """

    slice_id: str
    kind: LegalSliceKind | str
    claim: LegalSliceClaim
    deontic_profile: LegalDeonticProfileBinding
    temporal_model: LegalTemporalModelBinding
    defeasibility: LegalDefeasibilityBinding
    jurisdiction: LegalJurisdictionBinding
    priority: LegalPriorityBinding
    authority: LegalAuthorityBinding
    domain_slice: DomainLogicSliceV2
    route: LegalLogicRoute
    expression: TypedExpression
    document: SourceDocument
    conflicts: tuple[NormConflict, ...] = ()
    ambiguities: tuple[AmbiguityRecord, ...] = ()
    features: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    content_digest: str = ""
    schema_version: str = LEGAL_LOGIC_SLICE_V2_SCHEMA_VERSION

    interface: ClassVar[str] = LEGAL_LOGIC_SLICE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "slice_id", _record_id(self.slice_id, "slice_id"))
        object.__setattr__(
            self, "kind", _enum_value(self.kind, LegalSliceKind, "kind")
        )
        if not isinstance(self.claim, LegalSliceClaim):
            raise LegalLogicSliceError(
                "claim must be a LegalSliceClaim",
                code=CODE_MALFORMED,
                path="claim",
            )
        if not isinstance(self.deontic_profile, LegalDeonticProfileBinding):
            raise MissingLegalAxisError("deontic_profile")
        if not isinstance(self.temporal_model, LegalTemporalModelBinding):
            raise MissingLegalAxisError("temporal_model")
        if not isinstance(self.defeasibility, LegalDefeasibilityBinding):
            raise MissingLegalAxisError("defeasibility")
        if not isinstance(self.jurisdiction, LegalJurisdictionBinding):
            raise MissingLegalAxisError("jurisdiction")
        if not isinstance(self.priority, LegalPriorityBinding):
            raise MissingLegalAxisError("priority")
        if not isinstance(self.authority, LegalAuthorityBinding):
            raise MissingLegalAxisError("authority")
        if not isinstance(self.domain_slice, DomainLogicSliceV2):
            raise LegalLogicSliceError(
                "domain_slice must be a DomainLogicSliceV2",
                code=CODE_MALFORMED,
                path="domain_slice",
            )
        if not isinstance(self.route, LegalLogicRoute):
            raise LegalLogicSliceError(
                "route must be a LegalLogicRoute",
                code=CODE_MALFORMED,
                path="route",
            )
        if not isinstance(self.expression, TypedExpression):
            raise LegalLogicSliceError(
                "expression must be a TypedExpression",
                code=CODE_MALFORMED,
                path="expression",
            )
        if not isinstance(self.document, SourceDocument):
            raise LegalLogicSliceError(
                "document must be a SourceDocument",
                code=CODE_MALFORMED,
                path="document",
            )

        # Graph projection / operation roles never route as families.
        if self.route.is_operation_role or self.route.namespace is RouteNamespace.VIEW_ROLE:
            raise GraphProjectionAsFamilyError(
                self.route.view_role_id or self.route.view_name,
                path="route",
            )
        if self.route.family_id:
            reject_graph_projection_as_family(self.route.family_id, path="route.family_id")
        family_value = (
            self.domain_slice.family.value
            if isinstance(self.domain_slice.family, LogicIdentity)
            else str(self.domain_slice.family)
        )
        reject_graph_projection_as_family(family_value, path="domain_slice.family")

        # Deferred overlays are not admitted as base slices.
        if family_value in LEGAL_DEFERRED_OVERLAY_FAMILIES:
            raise LegalLogicSliceError(
                f"family {family_value!r} is a deferred overlay (LFP2-044); "
                "base legal slices use deontic/event/authorization/tdfol only",
                code=CODE_UNSUPPORTED_OVERLAY,
                path="family",
            )

        # Domain must be legal_ir.
        if self.domain_slice.domain != LEGAL_IR_DOMAIN_ID:
            raise LegalLogicSliceError(
                f"domain_slice.domain must be {LEGAL_IR_DOMAIN_ID!r}; "
                f"got {self.domain_slice.domain!r}",
                code=CODE_LINEAGE,
                path="domain_slice.domain",
            )

        # Lineage consistency.
        if self.domain_slice.document_id != self.document.document_id:
            raise LegalLogicSliceError(
                "domain_slice.document_id does not match document",
                code=CODE_LINEAGE,
                path="document_id",
            )
        if self.domain_slice.source_digest != self.document.content_digest:
            raise LegalLogicSliceError(
                "domain_slice.source_digest does not match document",
                code=CODE_LINEAGE,
                path="source_digest",
            )
        if self.domain_slice.expression_id != self.expression.expression_id:
            raise LegalLogicSliceError(
                "domain_slice.expression_id does not match expression",
                code=CODE_LINEAGE,
                path="expression_id",
            )
        if self.domain_slice.expression_digest != self.expression.content_digest:
            raise LegalLogicSliceError(
                "domain_slice.expression_digest does not match expression",
                code=CODE_LINEAGE,
                path="expression_digest",
            )

        object.__setattr__(self, "features", _feature_tuple(self.features, "features"))
        object.__setattr__(
            self,
            "assumption_ids",
            _string_tuple(self.assumption_ids, "assumption_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "conflicts",
            tuple(self.conflicts) if self.conflicts is not None else (),
        )
        object.__setattr__(
            self,
            "ambiguities",
            tuple(self.ambiguities) if self.ambiguities is not None else (),
        )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise LegalLogicSliceError(
                    "content_digest does not match LegalLogicSliceV2 content",
                    code=CODE_MALFORMED,
                    path="content_digest",
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "authority": self.authority.to_dict(),
            "claim": self.claim.to_dict(),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "deontic_profile": self.deontic_profile.to_dict(),
            "defeasibility": self.defeasibility.to_dict(),
            "domain_slice_digest": self.domain_slice.content_digest,
            "expression_digest": self.expression.content_digest,
            "features": list(self.features),
            "interface": self.interface,
            "jurisdiction": self.jurisdiction.to_dict(),
            "kind": self.kind.value if isinstance(self.kind, LegalSliceKind) else str(self.kind),
            "priority": self.priority.to_dict(),
            "route_id": self.route.route_id,
            "schema_version": self.schema_version,
            "slice_id": self.slice_id,
            "source_digest": self.document.content_digest,
            "temporal_model": self.temporal_model.to_dict(),
        }

    @property
    def is_admitted(self) -> bool:
        return self.domain_slice.is_admitted

    @property
    def family_id(self) -> str:
        family = self.domain_slice.family
        if isinstance(family, LogicIdentity):
            return family.value
        return str(family)

    @property
    def profile_id(self) -> str:
        profile = self.domain_slice.profile
        if isinstance(profile, LogicIdentity):
            return profile.value
        return str(profile)

    def require_admitted(self) -> "LegalLogicSliceV2":
        """Return self when the domain slice is admitted for backend use."""

        self.domain_slice.require_admitted()
        return self

    def require_explicit_axes(self) -> "LegalLogicSliceV2":
        """Fail closed if any required axis is missing (construction already checks)."""

        for axis_name, axis in (
            ("deontic_profile", self.deontic_profile),
            ("temporal_model", self.temporal_model),
            ("defeasibility", self.defeasibility),
            ("jurisdiction", self.jurisdiction),
            ("priority", self.priority),
            ("authority", self.authority),
        ):
            if axis is None:
                raise MissingLegalAxisError(axis_name)
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["ambiguities"] = [a.to_dict() for a in self.ambiguities]
        payload["content_digest"] = self.content_digest
        payload["domain_slice"] = self.domain_slice.to_dict()
        payload["family_id"] = self.family_id
        payload["is_admitted"] = self.is_admitted
        payload["profile_id"] = self.profile_id
        payload["route"] = self.route.to_dict()
        return payload

    def to_domain_slice(self) -> DomainLogicSliceV2:
        """Project the underlying DomainLogicSlice@2."""

        return self.domain_slice

    def to_obligation(
        self,
        *,
        obligation_id: str,
        encoding: LogicIdentity | Mapping[str, Any] | str | None = None,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str | None = None,
        bounds: RequestBounds | Mapping[str, Any] | None = None,
        authority_ceiling: RequestAuthorityCeiling | str | None = None,
    ) -> LogicObligationV2:
        """Admit a LogicObligation@2 from this legal slice."""

        admitted = self.require_admitted()
        if encoding is None:
            encoding = encoding_id("smt_lib2")
        if evidence_kind is None:
            evidence_kind = evidence_id("model")
        if bounds is None:
            bounds = RequestBounds.default()
        if authority_ceiling is None:
            authority_ceiling = _request_ceiling_for_legal(admitted.authority)
        return LogicObligationV2.from_slice(
            admitted.domain_slice,
            obligation_id=obligation_id,
            statement=admitted.claim.statement,
            encoding=encoding,
            evidence_kind=evidence_kind,
            bounds=bounds,
            authority_ceiling=authority_ceiling,
            metadata={
                "legal_slice_id": admitted.slice_id,
                "legal_slice_kind": (
                    admitted.kind.value
                    if isinstance(admitted.kind, LegalSliceKind)
                    else str(admitted.kind)
                ),
                "jurisdiction": admitted.jurisdiction.jurisdiction,
                "deontic_profile_id": admitted.deontic_profile.profile_id,
            },
        )

    def to_backend_request(
        self,
        *,
        request_id: str,
        obligation_id: str,
        encoding: LogicIdentity | Mapping[str, Any] | str | None = None,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str | None = None,
        bounds: RequestBounds | Mapping[str, Any] | None = None,
        authority_ceiling: RequestAuthorityCeiling | str | None = None,
    ) -> BackendRequestV2:
        """Admit a BackendRequest@2 from this legal slice."""

        admitted = self.require_admitted()
        if encoding is None:
            encoding = encoding_id("smt_lib2")
        if evidence_kind is None:
            evidence_kind = evidence_id("model")
        if bounds is None:
            bounds = RequestBounds.default()
        if authority_ceiling is None:
            authority_ceiling = _request_ceiling_for_legal(admitted.authority)
        return BackendRequestV2.from_slice(
            admitted.domain_slice,
            request_id=request_id,
            obligation_id=obligation_id,
            statement=admitted.claim.statement,
            encoding=encoding,
            evidence_kind=evidence_kind,
            bounds=bounds,
            authority_ceiling=authority_ceiling,
            metadata={
                "legal_slice_id": admitted.slice_id,
                "legal_slice_kind": (
                    admitted.kind.value
                    if isinstance(admitted.kind, LegalSliceKind)
                    else str(admitted.kind)
                ),
                "jurisdiction": admitted.jurisdiction.jurisdiction,
            },
        )


def _request_ceiling_for_legal(
    authority: LegalAuthorityBinding,
) -> RequestAuthorityCeiling:
    """Map legal authority binding to a request ceiling (never kernel/theorem)."""

    role = authority.role
    if isinstance(role, LegalAuthorityRole):
        if role is LegalAuthorityRole.BOUNDED:
            if authority.result_ceiling is ResultAuthority.AUTHORIZATION:
                return RequestAuthorityCeiling.AUTHORIZATION
            return RequestAuthorityCeiling.BOUNDED
        if role is LegalAuthorityRole.ADVISORY:
            return RequestAuthorityCeiling.ADVISORY
        if role is LegalAuthorityRole.DECLARATION:
            return RequestAuthorityCeiling.ADVISORY
    return RequestAuthorityCeiling.CANDIDATE


# ---------------------------------------------------------------------------
# Bundle of connected slices
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalLogicSliceBundle:
    """Connected set of base Legal IR slices sharing source identity."""

    bundle_id: str
    document: SourceDocument
    slices: tuple[LegalLogicSliceV2, ...]
    formalization: FormalizationArtifactV3 | None = None
    conflicts: tuple[NormConflict, ...] = ()
    content_digest: str = ""
    schema_version: str = LEGAL_LOGIC_SLICE_BUNDLE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _record_id(self.bundle_id, "bundle_id"))
        if not isinstance(self.document, SourceDocument):
            raise LegalLogicSliceError(
                "document must be a SourceDocument",
                code=CODE_MALFORMED,
                path="document",
            )
        slices = tuple(self.slices or ())
        if not slices:
            raise LegalLogicSliceError(
                "bundle requires at least one LegalLogicSliceV2",
                code=CODE_MALFORMED,
                path="slices",
            )
        for item in slices:
            if not isinstance(item, LegalLogicSliceV2):
                raise LegalLogicSliceError(
                    "slices must contain LegalLogicSliceV2 values",
                    code=CODE_MALFORMED,
                    path="slices",
                )
            if item.document.document_id != self.document.document_id:
                raise LegalLogicSliceError(
                    "all slices must share the bundle document identity",
                    code=CODE_LINEAGE,
                    path="slices",
                )
        object.__setattr__(self, "slices", slices)
        object.__setattr__(
            self, "conflicts", tuple(self.conflicts) if self.conflicts else ()
        )
        content = content_sha256(
            canonical_json_bytes(
                {
                    "bundle_id": self.bundle_id,
                    "document_id": self.document.document_id,
                    "schema_version": self.schema_version,
                    "slice_digests": [s.content_digest for s in slices],
                    "source_digest": self.document.content_digest,
                }
            )
        )
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise LegalLogicSliceError(
                    "content_digest does not match LegalLogicSliceBundle content",
                    code=CODE_MALFORMED,
                    path="content_digest",
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    @property
    def kinds(self) -> tuple[LegalSliceKind, ...]:
        return tuple(
            s.kind if isinstance(s.kind, LegalSliceKind) else LegalSliceKind(str(s.kind))
            for s in self.slices
        )

    def slice_for(self, kind: LegalSliceKind | str) -> LegalLogicSliceV2 | None:
        target = (
            kind
            if isinstance(kind, LegalSliceKind)
            else LegalSliceKind(str(kind))
        )
        for item in self.slices:
            item_kind = (
                item.kind
                if isinstance(item.kind, LegalSliceKind)
                else LegalSliceKind(str(item.kind))
            )
            if item_kind is target:
                return item
        return None

    def require_kinds(self, *kinds: LegalSliceKind | str) -> "LegalLogicSliceBundle":
        present = set(self.kinds)
        for kind in kinds:
            target = (
                kind
                if isinstance(kind, LegalSliceKind)
                else LegalSliceKind(str(kind))
            )
            if target not in present:
                raise LegalLogicSliceError(
                    f"bundle missing required slice kind {target.value!r}",
                    code=CODE_MISSING_AXIS,
                    path="slices",
                )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "content_digest": self.content_digest,
            "document_id": self.document.document_id,
            "formalization": None
            if self.formalization is None
            else self.formalization.to_dict(),
            "kinds": [
                k.value if isinstance(k, LegalSliceKind) else str(k)
                for k in self.kinds
            ],
            "schema_version": self.schema_version,
            "slices": [s.to_dict() for s in self.slices],
            "source_digest": self.document.content_digest,
        }


# ---------------------------------------------------------------------------
# Connector / builder
# ---------------------------------------------------------------------------


def _proposition_name(claim: LegalSliceClaim) -> str:
    """Build a safe propositional atom for a claim statement."""

    base = claim.action or claim.norm_type or claim.kind.value
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", base)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"Claim_{cleaned}" if cleaned else "Claim"
    # Capitalize for predicate style used by propositional_signature.
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned[:64]


def _build_expression(
    claim: LegalSliceClaim,
    *,
    family: str,
    profile: str,
    expression_id: str,
) -> TypedExpression:
    prop = _proposition_name(claim)
    signature = propositional_signature(
        f"sig:legal:{claim.claim_id}",
        (prop,),
        family=family,
        profile=profile,
    )
    root = mk_predicate(f"n:legal:{claim.claim_id}", prop)
    return TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=family_id(family),
        profile=profile_id(profile),
    )


def _build_axes_for_claim(
    claim: LegalSliceClaim,
    spec: _KindRouteSpec,
    *,
    priority_override: LegalPriorityBinding | None = None,
    deontic_override: LegalDeonticProfileBinding | None = None,
    temporal_override: LegalTemporalModelBinding | None = None,
    defeasibility_override: LegalDefeasibilityBinding | None = None,
    jurisdiction_override: LegalJurisdictionBinding | None = None,
    authority_override: LegalAuthorityBinding | None = None,
) -> tuple[
    LegalDeonticProfileBinding,
    LegalTemporalModelBinding,
    LegalDefeasibilityBinding,
    LegalJurisdictionBinding,
    LegalPriorityBinding,
    LegalAuthorityBinding,
]:
    deontic = deontic_override or LegalDeonticProfileBinding(
        profile_id=spec.deontic_profile_id,
        form=spec.deontic_form,
        permission=spec.deontic_permission,
        exceptions=spec.deontic_exceptions,
        priorities=spec.deontic_priorities,
        contrary_to_duty=False,
        operator_force=claim.norm_type or "",
        description=f"Deontic profile for legal slice kind {spec.kind.value}",
    )
    anchors: list[str] = []
    if claim.event_id:
        anchors.append(claim.event_id)
    if claim.fluent_id:
        anchors.append(claim.fluent_id)
    temporal = temporal_override or LegalTemporalModelBinding(
        model_id=spec.temporal_model_id,
        density=spec.temporal_density,
        trace_model=spec.temporal_trace,
        event_order=spec.temporal_event_order,
        temporal_anchors=tuple(anchors),
        metric_intervals=False,
        description=f"Temporal model for legal slice kind {spec.kind.value}",
    )
    exception_ids = claim.exception_ids
    defeasibility = defeasibility_override or LegalDefeasibilityBinding(
        enabled=spec.defeasibility_enabled,
        exception_ids=exception_ids,
        defeater_scope=exception_ids,
        unresolved_conflicts=False,
        description=f"Defeasibility for legal slice kind {spec.kind.value}",
    )

    jurisdiction_value = claim.jurisdiction
    if not jurisdiction_value:
        if spec.require_jurisdiction:
            raise MissingLegalAxisError("jurisdiction", path="claim.jurisdiction")
        # Event slices may omit claim jurisdiction; still bind an explicit
        # placeholder scope so the axis is never silent.
        jurisdiction_value = "unspecified"
    jurisdiction = jurisdiction_override or LegalJurisdictionBinding(
        jurisdiction=jurisdiction_value,
        territory=claim.territory,
        subject_matter=claim.subject_matter,
        authority_id=claim.authority_id or "",
        authority_kind="statute",
        description=f"Jurisdiction scope for legal slice kind {spec.kind.value}",
    )

    ordered: list[str] = []
    if priority_override is not None:
        priority = priority_override
    else:
        if claim.formula_id:
            ordered.append(claim.formula_id)
        for exc in claim.exception_ids:
            if exc not in ordered:
                ordered.append(exc)
        if spec.require_priority_ids and len(ordered) < 2:
            raise MissingLegalAxisError(
                "priority",
                path="priority.ordered_ids",
            )
        priority = LegalPriorityBinding(
            ordered_ids=tuple(ordered),
            relation="strict_total" if ordered else "none",
            description=f"Priority binding for legal slice kind {spec.kind.value}",
        )

    nl = (
        claim.source_kind is LegalSourceKind.NATURAL_LANGUAGE
        or looks_like_natural_language(claim.source_text or claim.statement)
    )
    # Natural-language extraction is admitted only as a candidate — never as
    # proof.  LegalAuthorityBinding enforces the ceiling; do not raise merely
    # because the source is NL.
    if authority_override is not None and (
        nl
        or authority_override.nl_extraction
        or authority_override.source_kind is LegalSourceKind.NATURAL_LANGUAGE
    ):
        reject_natural_language_proof_authority(
            {
                "kind": "natural_language",
                "text": claim.source_text or claim.statement,
                "nl_extraction": True,
                "authority": (
                    authority_override.result_ceiling.value
                    if isinstance(authority_override.result_ceiling, ResultAuthority)
                    else str(authority_override.result_ceiling)
                ),
            }
        )
    authority = authority_override or LegalAuthorityBinding(
        role=LegalAuthorityRole.CANDIDATE if nl else spec.authority_role,
        result_ceiling=ResultAuthority.CANDIDATE if nl else spec.result_ceiling,
        source_kind=(
            LegalSourceKind.NATURAL_LANGUAGE if nl else claim.source_kind
        ),
        evidence_authority=(
            EvidenceAuthority.NONE if nl else spec.evidence_authority
        ),
        nl_extraction=nl,
        description=f"Authority binding for legal slice kind {spec.kind.value}",
    )
    return deontic, temporal, defeasibility, jurisdiction, priority, authority


class LegalLogicSliceConnector:
    """Build connected LegalLogicSlice@2 records from Legal IR claims.

    Interface producer for ``LegalLogicSlice@2``.
    """

    INTERFACE: ClassVar[str] = LEGAL_LOGIC_SLICE_V2_INTERFACE
    VERSION: ClassVar[str] = LEGAL_LOGIC_SLICE_MODULE_VERSION

    def __init__(
        self,
        *,
        route_adapter: LegalFormalizationAdapter | None = None,
    ) -> None:
        self._routes = route_adapter or LegalFormalizationAdapter()

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def version(self) -> str:
        return self.VERSION

    @property
    def domain_id(self) -> str:
        return LEGAL_IR_DOMAIN_ID

    def resolve_route(self, label: object) -> LegalLogicRoute:
        """Resolve a legal route; reject graph projection as family."""

        reject_graph_projection_as_family(label, path="label")
        route = resolve_legal_route(label)
        if route.is_operation_role:
            raise GraphProjectionAsFamilyError(
                route.view_role_id or str(label),
                path="label",
            )
        if route.family_id in LEGAL_DEFERRED_OVERLAY_FAMILIES:
            raise LegalLogicSliceError(
                f"family {route.family_id!r} is deferred to LFP2-044 overlays",
                code=CODE_UNSUPPORTED_OVERLAY,
                path="label",
            )
        return route

    def connect_claim(
        self,
        claim: LegalSliceClaim | Mapping[str, Any],
        *,
        document: SourceDocument | None = None,
        document_id: str = "",
        source_text: str = "",
        slice_id: str = "",
        expression_id: str = "",
        priority: LegalPriorityBinding | None = None,
        deontic_profile: LegalDeonticProfileBinding | None = None,
        temporal_model: LegalTemporalModelBinding | None = None,
        defeasibility: LegalDefeasibilityBinding | None = None,
        jurisdiction: LegalJurisdictionBinding | None = None,
        authority: LegalAuthorityBinding | None = None,
        conflicts: Sequence[NormConflict] = (),
        ambiguities: Sequence[AmbiguityRecord] = (),
        assumption_ids: Sequence[str] = (),
    ) -> LegalLogicSliceV2:
        """Connect one Legal IR claim into an admitted LegalLogicSlice@2."""

        if isinstance(claim, Mapping):
            claim = LegalSliceClaim.from_dict(claim)
        if not isinstance(claim, LegalSliceClaim):
            raise LegalLogicSliceError(
                "claim must be a LegalSliceClaim or mapping",
                code=CODE_MALFORMED,
                path="claim",
            )

        kind = (
            claim.kind
            if isinstance(claim.kind, LegalSliceKind)
            else LegalSliceKind(str(claim.kind))
        )
        spec = _KIND_SPECS.get(kind)
        if spec is None:
            raise LegalLogicSliceError(
                f"unknown legal slice kind {kind!r}",
                code=CODE_UNKNOWN_KIND,
                path="kind",
            )

        route = self.resolve_route(spec.route_label)
        # Ensure route family matches sealed kind mapping.
        if route.family_id and route.family_id != spec.family:
            # Profiles under deontic are fine when family matches.
            if route.family_id != spec.family:
                raise LegalLogicSliceError(
                    f"route family {route.family_id!r} does not match kind "
                    f"spec family {spec.family!r}",
                    code=CODE_ROUTE,
                    path="route",
                )

        (
            deontic,
            temporal,
            defeas,
            juris,
            prio,
            auth,
        ) = _build_axes_for_claim(
            claim,
            spec,
            priority_override=priority,
            deontic_override=deontic_profile,
            temporal_override=temporal_model,
            defeasibility_override=defeasibility,
            jurisdiction_override=jurisdiction,
            authority_override=authority,
        )

        # Build source document.
        body = source_text or claim.source_text or claim.statement
        if document is None:
            doc_id = document_id or f"doc:legal:{claim.claim_id}"
            document = SourceDocument.from_text(doc_id, body, encoding="utf-8")
        elif not isinstance(document, SourceDocument):
            raise LegalLogicSliceError(
                "document must be a SourceDocument",
                code=CODE_MALFORMED,
                path="document",
            )

        expr_id = expression_id or f"expr:legal:{claim.claim_id}"
        profile_name = route.profile_id or spec.profile
        expression = _build_expression(
            claim,
            family=spec.family,
            profile=profile_name,
            expression_id=expr_id,
        )

        sid = slice_id or f"slice:legal:{kind.value}:{claim.claim_id}"
        features = _feature_tuple(
            list(spec.features)
            + [
                "legal_ir",
                f"slice.{kind.value}",
            ],
            "features",
        )
        assumptions = _string_tuple(
            list(assumption_ids)
            + [
                f"axis:deontic:{deontic.profile_id}",
                f"axis:temporal:{temporal.model_id}",
                f"axis:jurisdiction:{juris.jurisdiction}",
                f"axis:authority:{auth.role.value if isinstance(auth.role, LegalAuthorityRole) else auth.role}",
            ],
            "assumption_ids",
            identifiers=True,
        )

        domain_slice = DomainLogicSliceV2.from_typed_expression(
            expression,
            slice_id=sid,
            domain=LEGAL_IR_DOMAIN_ID,
            document_id=document.document_id,
            source_digest=document.content_digest,
            property=property_id(spec.property_name),
            view=view_id(spec.view_name),
            notation=notation_id("canonical_text"),
            status=DomainSliceStatus.ADMITTED,
            features=features,
            assumption_ids=assumptions,
            metadata={
                "legal_slice_kind": kind.value,
                "legal_claim_id": claim.claim_id,
                "jurisdiction": juris.jurisdiction,
                "deontic_profile_id": deontic.profile_id,
                "temporal_model_id": temporal.model_id,
                "defeasibility_enabled": defeas.enabled,
                "priority_count": len(prio.ordered_ids),
                "authority_role": (
                    auth.role.value
                    if isinstance(auth.role, LegalAuthorityRole)
                    else str(auth.role)
                ),
                "route_id": route.route_id,
                "producer_id": LEGAL_LOGIC_SLICE_PRODUCER_ID,
            },
        )

        return LegalLogicSliceV2(
            slice_id=sid,
            kind=kind,
            claim=claim,
            deontic_profile=deontic,
            temporal_model=temporal,
            defeasibility=defeas,
            jurisdiction=juris,
            priority=prio,
            authority=auth,
            domain_slice=domain_slice,
            route=route,
            expression=expression,
            document=document,
            conflicts=tuple(conflicts),
            ambiguities=tuple(ambiguities),
            features=features,
            assumption_ids=assumptions,
        )

    def connect_base_slices(
        self,
        claims: Sequence[LegalSliceClaim | Mapping[str, Any]],
        *,
        document: SourceDocument | None = None,
        document_id: str = "doc:legal:bundle",
        source_text: str = "",
        bundle_id: str = "",
        require_core_kinds: bool = True,
    ) -> LegalLogicSliceBundle:
        """Connect base_norm, exception, event, and jurisdiction claims.

        When *require_core_kinds* is True (default), the claim set must cover
        the four core LFP2-025 kinds: base_norm, exception, event, jurisdiction.
        """

        if not claims:
            raise LegalLogicSliceError(
                "connect_base_slices requires at least one claim",
                code=CODE_MALFORMED,
                path="claims",
            )

        parsed: list[LegalSliceClaim] = []
        for raw in claims:
            if isinstance(raw, Mapping):
                parsed.append(LegalSliceClaim.from_dict(raw))
            elif isinstance(raw, LegalSliceClaim):
                parsed.append(raw)
            else:
                raise LegalLogicSliceError(
                    "claims must be LegalSliceClaim or mapping values",
                    code=CODE_MALFORMED,
                    path="claims",
                )

        # Shared document from first claim / provided text.
        if document is None:
            body = source_text or "\n".join(c.statement for c in parsed)
            document = SourceDocument.from_text(
                document_id, body, encoding="utf-8"
            )

        # Cross-claim priority: collect formula ids ordered by priority_rank.
        ranked = sorted(
            (c for c in parsed if c.priority_rank is not None),
            key=lambda c: int(c.priority_rank or 0),
        )
        shared_priority_ids = tuple(c.formula_id for c in ranked)
        shared_priority = (
            LegalPriorityBinding(
                ordered_ids=shared_priority_ids,
                relation="strict_total",
                description="Cross-claim priority order for legal slice bundle",
            )
            if shared_priority_ids
            else None
        )

        # Detect norm conflicts across claims.
        formula_payloads = [
            {
                "formula_id": c.formula_id,
                "norm_type": c.norm_type,
                "actor": c.actor,
                "action": c.action,
                "object": c.object,
                "conditions": c.conditions,
                "exceptions": c.exception_ids,
                "priority": c.priority_rank,
            }
            for c in parsed
        ]
        conflicts = detect_norm_conflicts(formula_payloads)

        slices: list[LegalLogicSliceV2] = []
        for claim in parsed:
            kind = (
                claim.kind
                if isinstance(claim.kind, LegalSliceKind)
                else LegalSliceKind(str(claim.kind))
            )
            if shared_priority is not None and (
                kind is LegalSliceKind.PRIORITY
                or kind
                in {
                    LegalSliceKind.BASE_NORM,
                    LegalSliceKind.EXCEPTION,
                    LegalSliceKind.CONFLICT,
                }
            ):
                # Shared cross-claim priority is the explicit order for
                # norm/exception/conflict/priority slices in the bundle.
                prio = shared_priority
            elif kind is LegalSliceKind.PRIORITY:
                # Priority slices must carry at least two ordered identities.
                prio = LegalPriorityBinding(
                    ordered_ids=(claim.formula_id, *claim.exception_ids),
                    relation="strict_total",
                    description="Priority slice ordering",
                )
            else:
                # Per-claim priority remains explicit when no shared order.
                prio = LegalPriorityBinding(
                    ordered_ids=(
                        (claim.formula_id,) + claim.exception_ids
                        if claim.formula_id
                        else claim.exception_ids
                    ),
                    relation="strict_total" if claim.formula_id else "none",
                    description=f"Per-claim priority for {claim.claim_id}",
                )

            slice_item = self.connect_claim(
                claim,
                document=document,
                priority=prio,
                conflicts=conflicts,
            )
            slices.append(slice_item)

        if require_core_kinds:
            core = {
                LegalSliceKind.BASE_NORM,
                LegalSliceKind.EXCEPTION,
                LegalSliceKind.EVENT,
                LegalSliceKind.JURISDICTION,
            }
            present = {
                s.kind if isinstance(s.kind, LegalSliceKind) else LegalSliceKind(str(s.kind))
                for s in slices
            }
            missing = core - present
            if missing:
                raise LegalLogicSliceError(
                    "connect_base_slices missing core kinds: "
                    + ", ".join(sorted(k.value for k in missing)),
                    code=CODE_MISSING_AXIS,
                    path="claims",
                )

        # Build FormalizationArtifact@3 spanning all domain slices.
        primary = slices[0]
        formalization = FormalizationArtifactV3(
            artifact_id=f"art:legal:{bundle_id or document.document_id}",
            sample_id=f"sample:legal:{document.document_id}",
            domain=LEGAL_IR_DOMAIN_ID,
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=primary.expression.expression_id,
            expression_digest=primary.expression.content_digest,
            family=primary.domain_slice.family,
            profile=primary.domain_slice.profile,
            view=view_id("source"),
            notation=notation_id("canonical_text"),
            status=FormalizationArtifactStatus.OK,
            slices=tuple(s.domain_slice for s in slices),
            assumption_ids=tuple(
                sorted({aid for s in slices for aid in s.assumption_ids})
            ),
            metadata={
                "producer_id": LEGAL_LOGIC_SLICE_PRODUCER_ID,
                "interface": LEGAL_LOGIC_SLICE_V2_INTERFACE,
                "kinds": [
                    s.kind.value if isinstance(s.kind, LegalSliceKind) else str(s.kind)
                    for s in slices
                ],
                "conflict_count": len(conflicts),
            },
        )

        bid = bundle_id or f"bundle:legal:{document.document_id}"
        return LegalLogicSliceBundle(
            bundle_id=bid,
            document=document,
            slices=tuple(slices),
            formalization=formalization,
            conflicts=conflicts,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": LEGAL_IR_TYPED_DOMAIN,
            "domain_id": LEGAL_IR_DOMAIN_ID,
            "interface": self.interface,
            "module_version": LEGAL_LOGIC_SLICE_MODULE_VERSION,
            "producer_id": LEGAL_LOGIC_SLICE_PRODUCER_ID,
            "route_adapter": LEGAL_FORMALIZATION_ADAPTER_INTERFACE,
            "supported_kinds": [k.value for k in LegalSliceKind],
            "version": self.version,
        }


# Module-level convenience API.
_DEFAULT_CONNECTOR: LegalLogicSliceConnector | None = None


def legal_logic_slice_connector() -> LegalLogicSliceConnector:
    """Return a process-local default LegalLogicSliceConnector."""

    global _DEFAULT_CONNECTOR
    if _DEFAULT_CONNECTOR is None:
        _DEFAULT_CONNECTOR = LegalLogicSliceConnector()
    return _DEFAULT_CONNECTOR


def connect_legal_claim(
    claim: LegalSliceClaim | Mapping[str, Any],
    **kwargs: Any,
) -> LegalLogicSliceV2:
    """Connect one Legal IR claim via the default connector."""

    return legal_logic_slice_connector().connect_claim(claim, **kwargs)


def connect_legal_base_slices(
    claims: Sequence[LegalSliceClaim | Mapping[str, Any]],
    **kwargs: Any,
) -> LegalLogicSliceBundle:
    """Connect base norm/exception/event/jurisdiction slices."""

    return legal_logic_slice_connector().connect_base_slices(claims, **kwargs)


def build_core_legal_claims(
    *,
    jurisdiction: str = "us-federal",
    actor: str = "Person",
    action: str = "FileReport",
) -> tuple[LegalSliceClaim, ...]:
    """Build a compact four-claim core set for tests and fixtures."""

    base_id = "norm:base:file_report"
    exception_id = "norm:exc:emergency"
    return (
        LegalSliceClaim(
            claim_id="claim:base_norm:1",
            kind=LegalSliceKind.BASE_NORM,
            statement=f"O({action})",
            formula_id=base_id,
            actor=actor,
            action=action,
            norm_type="obligation",
            exception_ids=(exception_id,),
            priority_rank=2,
            jurisdiction=jurisdiction,
            territory="united-states",
            subject_matter="reporting",
            authority_id="auth:statute:reporting",
            source_kind=LegalSourceKind.SYMBOLIC,
        ),
        LegalSliceClaim(
            claim_id="claim:exception:1",
            kind=LegalSliceKind.EXCEPTION,
            statement=f"exception({exception_id}, Emergency)",
            formula_id=exception_id,
            actor=actor,
            action=action,
            norm_type="permission",
            exception_ids=(exception_id,),
            priority_rank=1,
            jurisdiction=jurisdiction,
            territory="united-states",
            subject_matter="reporting",
            authority_id="auth:statute:reporting",
            source_kind=LegalSourceKind.SYMBOLIC,
        ),
        LegalSliceClaim(
            claim_id="claim:event:1",
            kind=LegalSliceKind.EVENT,
            statement="Happens(FileReportEvent, t)",
            formula_id="event:file_report",
            actor=actor,
            action=action,
            event_id="FileReportEvent",
            fluent_id="ReportFiled",
            jurisdiction=jurisdiction,
            source_kind=LegalSourceKind.SYMBOLIC,
        ),
        LegalSliceClaim(
            claim_id="claim:jurisdiction:1",
            kind=LegalSliceKind.JURISDICTION,
            statement=f"jurisdiction({jurisdiction})",
            formula_id="juris:scope",
            actor=actor,
            action=action,
            jurisdiction=jurisdiction,
            territory="united-states",
            subject_matter="reporting",
            authority_id="auth:statute:reporting",
            source_kind=LegalSourceKind.SYMBOLIC,
        ),
    )


__all__ = [
    "LEGAL_AUTHORITY_SCHEMA",
    "LEGAL_CLAIM_SCHEMA",
    "LEGAL_DEFEASIBILITY_SCHEMA",
    "LEGAL_DEFERRED_OVERLAY_FAMILIES",
    "LEGAL_DEONTIC_PROFILE_SCHEMA",
    "LEGAL_EVIDENCE_SUBSET",
    "LEGAL_IR_DOMAIN_ID",
    "LEGAL_JURISDICTION_SCHEMA",
    "LEGAL_LOGIC_SLICE_BUNDLE_SCHEMA",
    "LEGAL_LOGIC_SLICE_MODULE_VERSION",
    "LEGAL_LOGIC_SLICE_PRODUCER_ID",
    "LEGAL_LOGIC_SLICE_V2_INTERFACE",
    "LEGAL_LOGIC_SLICE_V2_SCHEMA_VERSION",
    "LEGAL_NEVER_FAMILY_VIEW_ROLES",
    "LEGAL_PRIORITY_SCHEMA",
    "LEGAL_TEMPORAL_MODEL_SCHEMA",
    "GraphProjectionAsFamilyError",
    "LegalAuthorityBinding",
    "LegalAuthorityRejectedError",
    "LegalAuthorityRole",
    "LegalDefeasibilityBinding",
    "LegalDeonticProfileBinding",
    "LegalJurisdictionBinding",
    "LegalLogicSliceBundle",
    "LegalLogicSliceConnector",
    "LegalLogicSliceError",
    "LegalLogicSliceV2",
    "LegalPriorityBinding",
    "LegalSliceClaim",
    "LegalSliceKind",
    "LegalSourceKind",
    "LegalTemporalModelBinding",
    "MissingLegalAxisError",
    "build_core_legal_claims",
    "connect_legal_base_slices",
    "connect_legal_claim",
    "is_graph_projection_label",
    "legal_logic_slice_connector",
    "legal_slice_kind_specs",
    "reject_graph_projection_as_family",
]
