"""Bridge software-verification IRs through the shared syntax kernel (LFP-039).

Interface: ``SoftwareVerificationSyntaxBridge@1``

Rich typed software-verification models remain the semantic owners.  This
bridge only publishes and consumes them as versioned
:class:`~ipfs_datasets_py.logic.syntax_core.ast.LogicExtensionNode` payloads
inside :class:`~ipfs_datasets_py.logic.syntax_core.ast.TypedExpression`
roots.  Free-form text/JSON is rejected; unsupported constructs and
observational loss are explicit records, never silent omissions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _thaw_mapping,
)
from ipfs_datasets_py.logic.syntax_core.signatures import LogicSignature

from .authorization import AuthorizationIR
from .concurrency import ConcurrencyIR
from .contracts import ProgramContract
from .heap import HeapModel
from .hyperproperties import HyperpropertyIR
from .program import ProgramIR
from .protocol import ProtocolIR
from .refinement import RefinementIR
from .separation import SeparationLogicIR
from .state import StateSchema
from .temporal import TemporalFormula
from .trace import TraceIR
from .transitions import StateTransitionIR
from .vc import VerificationConditionSet


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE: Final = (
    "SoftwareVerificationSyntaxBridge@1"
)
SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_VERSION: Final = "1.0.0"
BRIDGE_RESULT_SCHEMA: Final = "software-verification.syntax-bridge-result/v1"
BRIDGE_LOSS_SCHEMA: Final = "software-verification.syntax-bridge-loss/v1"
BRIDGE_UNSUPPORTED_SCHEMA: Final = (
    "software-verification.syntax-bridge-unsupported/v1"
)
BRIDGE_ROUTE_SCHEMA: Final = "software-verification.syntax-bridge-route/v1"
BRIDGE_MODULE_VERSION: Final = "1.0.0"
BRIDGE_DOMAIN_ID: Final = "software_verification"
VC_VIEW_ROLE: Final = "verification_condition"

# Stable diagnostic codes.
CODE_UNKNOWN_KIND: Final = "software_verification.unknown_ir_kind"
CODE_UNSUPPORTED: Final = "software_verification.unsupported_construct"
CODE_FREE_FORM: Final = "software_verification.free_form_rejected"
CODE_IDENTITY_MISMATCH: Final = "software_verification.identity_mismatch"
CODE_SOURCE_MISMATCH: Final = "software_verification.source_identity_mismatch"
CODE_MALFORMED: Final = "software_verification.malformed_input"
CODE_PAYLOAD: Final = "software_verification.invalid_payload"
CODE_ROUTE: Final = "software_verification.route_error"
CODE_LOSS: Final = "software_verification.explicit_loss"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNKNOWN_KIND,
        CODE_UNSUPPORTED,
        CODE_FREE_FORM,
        CODE_IDENTITY_MISMATCH,
        CODE_SOURCE_MISMATCH,
        CODE_MALFORMED,
        CODE_PAYLOAD,
        CODE_ROUTE,
        CODE_LOSS,
    }
)


class SoftwareVerificationBridgeError(ValueError):
    """Raised when a software-verification syntax bridge request fails closed."""

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
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


class FreeFormRejectedError(SoftwareVerificationBridgeError):
    """Raised when free-form text/JSON is offered in place of a typed IR."""

    def __init__(self, message: str = "", *, path: str = "document") -> None:
        super().__init__(
            message
            or "free-form text/JSON is rejected; publish a typed software-verification IR",
            code=CODE_FREE_FORM,
            path=path,
        )


class UnsupportedConstructError(SoftwareVerificationBridgeError):
    """Raised when a construct has no admitted syntax-kernel route."""

    def __init__(self, construct: str, *, path: str = "kind") -> None:
        super().__init__(
            f"unsupported software-verification construct {construct!r}",
            code=CODE_UNSUPPORTED,
            path=path,
        )
        self.construct = construct


class SoftwareVerificationIRKind(StrEnum):
    """Closed set of software-verification IRs admitted by the bridge."""

    STATE = "state"
    TRANSITION = "transition"
    PROGRAM = "program"
    CONTRACT = "contract"
    VC = "vc"
    TEMPORAL = "temporal"
    TRACE = "trace"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    HEAP = "heap"
    SEPARATION = "separation"
    CONCURRENCY = "concurrency"
    REFINEMENT = "refinement"


class BridgeStatus(StrEnum):
    """Outcome of a publish, consume, or round-trip operation."""

    OK = "ok"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class LossKind(StrEnum):
    """Closed set of explicit semantic loss classifications."""

    NONE = "none"
    OBSERVATIONAL = "observational"
    UNSUPPORTED_CONSTRUCT = "unsupported_construct"
    APPROXIMATION = "approximation"
    SOURCE_MAP = "source_map"
    OTHER = "other"


class PreservationKind(StrEnum):
    """Semantic relationship between domain IR and syntax-kernel view."""

    EXACT = "exact"
    STRUCTURAL = "structural"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Route descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IRRouteDescriptor:
    """Canonical family/profile route for one software-verification IR kind."""

    kind: SoftwareVerificationIRKind
    family_id: str
    profile_id: str
    features: tuple[str, ...]
    payload_schema: str
    domain_schema: str
    view_role: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SoftwareVerificationIRKind(self.kind))
        if not self.family_id or not self.profile_id:
            raise SoftwareVerificationBridgeError(
                "route requires family_id and profile_id",
                code=CODE_ROUTE,
            )
        if not self.features:
            raise SoftwareVerificationBridgeError(
                "route features must be non-empty",
                code=CODE_ROUTE,
            )
        if "/v" not in self.payload_schema:
            raise SoftwareVerificationBridgeError(
                "payload_schema must be versioned",
                code=CODE_ROUTE,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_schema": self.domain_schema,
            "family_id": self.family_id,
            "features": list(self.features),
            "kind": self.kind.value,
            "notes": self.notes,
            "payload_schema": self.payload_schema,
            "profile_id": self.profile_id,
            "schema": BRIDGE_ROUTE_SCHEMA,
            "view_role": self.view_role,
        }


def default_ir_routes() -> Mapping[SoftwareVerificationIRKind, IRRouteDescriptor]:
    """Return the sealed route table for every admitted IR kind."""

    rows: tuple[IRRouteDescriptor, ...] = (
        IRRouteDescriptor(
            SoftwareVerificationIRKind.STATE,
            family_id="transition_system",
            profile_id="state_schema",
            features=("software_verification.state", "transition_system.state"),
            payload_schema="transition_system.state_schema/v1",
            domain_schema="state-schema/v1",
            notes="Typed state schemas remain StateSchema owners.",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.TRANSITION,
            family_id="transition_system",
            profile_id="action_system",
            features=(
                "software_verification.transition",
                "transition_system.action",
            ),
            payload_schema="transition_system.state_transition_ir/v1",
            domain_schema="state-transition-ir/v1",
            notes="Action systems and Kripke structures stay typed.",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.PROGRAM,
            family_id="program",
            profile_id="program_ir",
            features=("software_verification.program", "program.ir"),
            payload_schema="program.program_ir/v1",
            domain_schema="program-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.CONTRACT,
            family_id="program",
            profile_id="dynamic_hoare",
            features=("software_verification.contract", "program.contract"),
            payload_schema="program.program_contract/v1",
            domain_schema="program-contract/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.VC,
            family_id="program",
            profile_id="wp_vc",
            features=(
                "software_verification.vc",
                "program.verification_condition",
            ),
            payload_schema="program.verification_condition_set/v1",
            domain_schema="verification-condition-set/v1",
            view_role=VC_VIEW_ROLE,
            notes="verification_condition is a view role, never a family.",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.TEMPORAL,
            family_id="temporal",
            profile_id="ltl",
            features=("software_verification.temporal", "temporal.formula"),
            payload_schema="temporal.formula/v1",
            domain_schema="temporal-formula/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.TRACE,
            family_id="temporal",
            profile_id="finite_trace",
            features=("software_verification.trace", "temporal.trace"),
            payload_schema="temporal.trace_ir/v1",
            domain_schema="trace-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.AUTHORIZATION,
            family_id="authorization",
            profile_id="datalog",
            features=(
                "software_verification.authorization",
                "authorization.policy",
            ),
            payload_schema="authorization.ir/v1",
            domain_schema="authorization-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.PROTOCOL,
            family_id="cryptographic_protocol",
            profile_id="dolev_yao",
            features=(
                "software_verification.protocol",
                "cryptographic_protocol.ir",
            ),
            payload_schema="cryptographic_protocol.ir/v1",
            domain_schema="protocol-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.HYPERPROPERTY,
            family_id="hyperproperty",
            profile_id="hyperltl",
            features=(
                "software_verification.hyperproperty",
                "hyperproperty.ir",
            ),
            payload_schema="hyperproperty.ir/v1",
            domain_schema="hyperproperty-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.HEAP,
            family_id="separation_logic",
            profile_id="heap_model",
            features=("software_verification.heap", "separation_logic.heap"),
            payload_schema="separation_logic.heap_model/v1",
            domain_schema="heap-model/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.SEPARATION,
            family_id="separation_logic",
            profile_id="separation",
            features=(
                "software_verification.separation",
                "separation_logic.ir",
            ),
            payload_schema="separation_logic.ir/v1",
            domain_schema="separation-logic-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.CONCURRENCY,
            family_id="concurrency",
            profile_id="rely_guarantee",
            features=(
                "software_verification.concurrency",
                "concurrency.ir",
            ),
            payload_schema="concurrency.ir/v1",
            domain_schema="concurrency-ir/v1",
        ),
        IRRouteDescriptor(
            SoftwareVerificationIRKind.REFINEMENT,
            family_id="refinement",
            profile_id="simulation",
            features=(
                "software_verification.refinement",
                "refinement.ir",
            ),
            payload_schema="refinement.ir/v1",
            domain_schema="refinement-ir/v1",
        ),
    )
    return MappingProxyType({item.kind: item for item in rows})


_TYPE_TO_KIND: Final[Mapping[type, SoftwareVerificationIRKind]] = MappingProxyType(
    {
        StateSchema: SoftwareVerificationIRKind.STATE,
        StateTransitionIR: SoftwareVerificationIRKind.TRANSITION,
        ProgramIR: SoftwareVerificationIRKind.PROGRAM,
        ProgramContract: SoftwareVerificationIRKind.CONTRACT,
        VerificationConditionSet: SoftwareVerificationIRKind.VC,
        TemporalFormula: SoftwareVerificationIRKind.TEMPORAL,
        TraceIR: SoftwareVerificationIRKind.TRACE,
        AuthorizationIR: SoftwareVerificationIRKind.AUTHORIZATION,
        ProtocolIR: SoftwareVerificationIRKind.PROTOCOL,
        HyperpropertyIR: SoftwareVerificationIRKind.HYPERPROPERTY,
        HeapModel: SoftwareVerificationIRKind.HEAP,
        SeparationLogicIR: SoftwareVerificationIRKind.SEPARATION,
        ConcurrencyIR: SoftwareVerificationIRKind.CONCURRENCY,
        RefinementIR: SoftwareVerificationIRKind.REFINEMENT,
    }
)

_KIND_TO_TYPE: Final[Mapping[SoftwareVerificationIRKind, type]] = MappingProxyType(
    {kind: cls for cls, kind in _TYPE_TO_KIND.items()}
)

_FROM_DICT: Final[
    Mapping[SoftwareVerificationIRKind, Callable[[Mapping[str, Any]], Any]]
] = MappingProxyType(
    {
        SoftwareVerificationIRKind.STATE: StateSchema.from_dict,
        SoftwareVerificationIRKind.TRANSITION: StateTransitionIR.from_dict,
        SoftwareVerificationIRKind.PROGRAM: ProgramIR.from_dict,
        SoftwareVerificationIRKind.CONTRACT: ProgramContract.from_dict,
        SoftwareVerificationIRKind.VC: VerificationConditionSet.from_dict,
        SoftwareVerificationIRKind.TEMPORAL: TemporalFormula.from_dict,
        SoftwareVerificationIRKind.TRACE: TraceIR.from_dict,
        SoftwareVerificationIRKind.AUTHORIZATION: AuthorizationIR.from_dict,
        SoftwareVerificationIRKind.PROTOCOL: ProtocolIR.from_dict,
        SoftwareVerificationIRKind.HYPERPROPERTY: HyperpropertyIR.from_dict,
        SoftwareVerificationIRKind.HEAP: HeapModel.from_dict,
        SoftwareVerificationIRKind.SEPARATION: SeparationLogicIR.from_dict,
        SoftwareVerificationIRKind.CONCURRENCY: ConcurrencyIR.from_dict,
        SoftwareVerificationIRKind.REFINEMENT: RefinementIR.from_dict,
    }
)

_IDENTITY_ATTRS: Final[tuple[str, ...]] = (
    "document_id",
    "program_id",
    "schema_id",
    "vc_set_id",
    "trace_id",
    "model_id",
    "contract_id",
    "formula_id",
    "canonical_id",
    "cid",
)


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BridgeLossRecord:
    """Explicit loss that occurred while bridging a domain IR."""

    loss_id: str
    kind: LossKind | str
    path: str
    description: str
    recoverable: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema: str = BRIDGE_LOSS_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", LossKind(self.kind))
        if not self.loss_id or not self.description:
            raise SoftwareVerificationBridgeError(
                "loss records require loss_id and description",
                code=CODE_LOSS,
            )
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "description": self.description,
            "kind": self.kind.value,
            "loss_id": self.loss_id,
            "path": self.path,
            "recoverable": self.recoverable,
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BridgeLossRecord":
        return cls(
            loss_id=str(value.get("loss_id") or ""),
            kind=str(value.get("kind") or LossKind.OTHER.value),
            path=str(value.get("path") or ""),
            description=str(value.get("description") or ""),
            recoverable=bool(value.get("recoverable", False)),
            attributes=dict(value.get("attributes") or {}),
            schema=str(value.get("schema") or BRIDGE_LOSS_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedConstructRecord:
    """An explicit unsupported construct encountered by the bridge."""

    construct_id: str
    construct: str
    reason: str
    path: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema: str = BRIDGE_UNSUPPORTED_SCHEMA

    def __post_init__(self) -> None:
        if not self.construct_id or not self.construct or not self.reason:
            raise SoftwareVerificationBridgeError(
                "unsupported construct requires id, construct, and reason",
                code=CODE_UNSUPPORTED,
            )
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "construct": self.construct,
            "construct_id": self.construct_id,
            "path": self.path,
            "reason": self.reason,
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedConstructRecord":
        return cls(
            construct_id=str(value.get("construct_id") or ""),
            construct=str(value.get("construct") or ""),
            reason=str(value.get("reason") or ""),
            path=str(value.get("path") or ""),
            attributes=dict(value.get("attributes") or {}),
            schema=str(value.get("schema") or BRIDGE_UNSUPPORTED_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class SyntaxBridgeResult:
    """Accounted publish / consume / round-trip outcome."""

    status: BridgeStatus | str
    kind: SoftwareVerificationIRKind | str
    domain_identity: str
    source_identities: tuple[str, ...] = ()
    expression: TypedExpression | None = None
    document: Any | None = None
    preservation: PreservationKind | str = PreservationKind.EXACT
    losses: tuple[BridgeLossRecord, ...] = ()
    unsupported: tuple[UnsupportedConstructRecord, ...] = ()
    route: IRRouteDescriptor | None = None
    diagnostics: tuple[str, ...] = ()
    interface: str = SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE
    schema: str = BRIDGE_RESULT_SCHEMA
    bridge_version: str = SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", BridgeStatus(self.status))
        object.__setattr__(
            self, "kind", SoftwareVerificationIRKind(self.kind)
        )
        object.__setattr__(
            self, "preservation", PreservationKind(self.preservation)
        )
        object.__setattr__(
            self,
            "source_identities",
            tuple(sorted(set(self.source_identities))),
        )
        object.__setattr__(self, "losses", tuple(self.losses))
        object.__setattr__(self, "unsupported", tuple(self.unsupported))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if self.status is BridgeStatus.OK and self.losses:
            object.__setattr__(self, "status", BridgeStatus.LOSSY)
            object.__setattr__(self, "preservation", PreservationKind.LOSSY)
        if self.unsupported and self.status is BridgeStatus.OK:
            object.__setattr__(self, "status", BridgeStatus.UNSUPPORTED)
            object.__setattr__(
                self, "preservation", PreservationKind.UNSUPPORTED
            )

    @property
    def ok(self) -> bool:
        return self.status in {BridgeStatus.OK, BridgeStatus.LOSSY}

    @property
    def exact(self) -> bool:
        return (
            self.status is BridgeStatus.OK
            and self.preservation is PreservationKind.EXACT
            and not self.losses
            and not self.unsupported
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridge_version": self.bridge_version,
            "diagnostics": list(self.diagnostics),
            "domain_identity": self.domain_identity,
            "expression": None
            if self.expression is None
            else self.expression.to_dict(),
            "has_document": self.document is not None,
            "interface": self.interface,
            "kind": self.kind.value,
            "losses": [item.to_dict() for item in self.losses],
            "preservation": self.preservation.value,
            "route": None if self.route is None else self.route.to_dict(),
            "schema": self.schema,
            "source_identities": list(self.source_identities),
            "status": self.status.value,
            "unsupported": [item.to_dict() for item in self.unsupported],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SoftwareVerificationBridgeError(
            f"{label} must be a mapping",
            code=CODE_MALFORMED,
            path=label,
        )
    return value


def _identity_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    cid = getattr(value, "cid", None)
    if isinstance(cid, str) and cid:
        return cid
    return str(value)


def domain_identity_of(document: Any) -> str:
    """Extract the durable domain identity of a software-verification IR."""

    for attr in _IDENTITY_ATTRS:
        if hasattr(document, attr):
            value = getattr(document, attr)
            if isinstance(value, str) and value:
                return value
    identity = getattr(document, "identity", None)
    if identity is not None:
        cid = getattr(identity, "cid", None)
        if isinstance(cid, str) and cid:
            return cid
    raise SoftwareVerificationBridgeError(
        f"cannot extract domain identity from {type(document).__name__}",
        code=CODE_IDENTITY_MISMATCH,
        path="domain_identity",
    )


def source_identities_of(document: Any) -> tuple[str, ...]:
    """Collect source-ref / provenance identities carried by *document*."""

    found: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, str) and value:
            found.add(value)

    if hasattr(document, "source_ref_ids"):
        for item in getattr(document, "source_ref_ids") or ():
            add(item)
    if hasattr(document, "sources"):
        for source in getattr(document, "sources") or ():
            add(getattr(source, "ref_id", None))
            add(getattr(source, "content_sha256", None))
            add(getattr(source, "source_uri", None))
    if hasattr(document, "span_ids"):
        for item in getattr(document, "span_ids") or ():
            add(item)
    if hasattr(document, "spans"):
        for span in getattr(document, "spans") or ():
            add(getattr(span, "span_id", None))
            add(getattr(span, "source_ref_id", None))
    provenance = getattr(document, "provenance", None)
    if provenance is not None:
        add(getattr(provenance, "source_cid", None))
        add(getattr(provenance, "repository_id", None))
        add(getattr(provenance, "revision", None))

    # Nested collections that commonly carry source maps.
    for attr in (
        "predicates",
        "actions",
        "symbols",
        "expressions",
        "commands",
        "functions",
        "events",
        "formulas",
        "claims",
        "rules",
        "facts",
        "preconditions",
        "postconditions",
        "obligations",
    ):
        collection = getattr(document, attr, None)
        if not collection:
            continue
        for item in collection:
            if hasattr(item, "source_ref_ids"):
                for ref in getattr(item, "source_ref_ids") or ():
                    add(ref)
            if hasattr(item, "span_ids"):
                for span_id in getattr(item, "span_ids") or ():
                    add(span_id)

    return tuple(sorted(found))


def kind_of(document: Any) -> SoftwareVerificationIRKind:
    """Resolve the bridge kind for a typed domain document."""

    for cls, kind in _TYPE_TO_KIND.items():
        if isinstance(document, cls):
            return kind
    raise UnsupportedConstructError(type(document).__name__, path="document")


def _serialize_document(document: Any) -> dict[str, Any]:
    if not hasattr(document, "to_dict"):
        raise FreeFormRejectedError(
            f"{type(document).__name__} lacks a typed to_dict() surface"
        )
    payload = document.to_dict()
    if not isinstance(payload, Mapping):
        raise FreeFormRejectedError("typed IR to_dict() must return a mapping")
    # Fail closed on free-form smuggling: the document must not be a bare
    # text/blob envelope.
    keys = set(payload)
    if keys and keys <= {"text", "raw", "blob", "data", "expression", "json"}:
        raise FreeFormRejectedError(
            "payload looks like free-form text/JSON rather than a typed IR"
        )
    return dict(payload)


def _signature_for(route: IRRouteDescriptor) -> LogicSignature:
    return LogicSignature(
        signature_id=f"sig:sv:{route.kind.value}",
        family=route.family_id,
        profile=route.profile_id,
        sorts=(),
        symbols=(),
        features=route.features,
        metadata={
            "bridge": SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE,
            "domain": BRIDGE_DOMAIN_ID,
            "kind": route.kind.value,
        },
    )


def _expression_id(kind: SoftwareVerificationIRKind, domain_identity: str) -> str:
    digest = domain_identity.replace(":", "-").replace("/", "-")
    if len(digest) > 80:
        digest = digest[:80]
    return f"expr:sv:{kind.value}:{digest}"


def _node_id(kind: SoftwareVerificationIRKind, domain_identity: str) -> str:
    digest = domain_identity.replace(":", "-").replace("/", "-")
    if len(digest) > 80:
        digest = digest[:80]
    return f"node:sv:{kind.value}:{digest}"


def _build_payload(
    *,
    route: IRRouteDescriptor,
    document: Any,
    domain_identity: str,
    source_identities: Sequence[str],
) -> dict[str, Any]:
    return {
        "bridge_interface": SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE,
        "bridge_version": SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_VERSION,
        "document": _serialize_document(document),
        "domain_identity": domain_identity,
        "domain_schema": route.domain_schema,
        "kind": route.kind.value,
        "schema_version": route.payload_schema,
        "source_identities": list(source_identities),
        "view_role": route.view_role,
    }


def _extension_root(
    *,
    route: IRRouteDescriptor,
    payload: Mapping[str, Any],
    domain_identity: str,
) -> LogicNode:
    return mk_extension(
        _node_id(route.kind, domain_identity),
        family=route.family_id,
        profile=route.profile_id,
        features=route.features,
        payload_schema=route.payload_schema,
        payload=payload,
        children=(),
    )


def _extract_extension(expression: TypedExpression | LogicNode) -> Any:
    root = expression.root if isinstance(expression, TypedExpression) else expression
    if not isinstance(root, LogicNode):
        raise SoftwareVerificationBridgeError(
            "expression root must be a LogicNode",
            code=CODE_PAYLOAD,
            path="expression.root",
        )
    if root.kind is not NodeKind.EXTENSION or root.extension is None:
        raise FreeFormRejectedError(
            "typed software-verification bridge requires a LogicExtensionNode root",
            path="expression.root",
        )
    return root.extension


def _observational_loss(
    original: Mapping[str, Any],
    restored: Mapping[str, Any],
) -> tuple[BridgeLossRecord, ...]:
    """Detect keys present only on one side that are observational."""

    observational = {
        "clock",
        "duration",
        "duration_ms",
        "elapsed",
        "elapsed_ms",
        "ended_at",
        "environment",
        "finished_at",
        "host",
        "hostname",
        "observations",
        "resource_usage",
        "started_at",
        "timing",
        "wall_time",
    }
    losses: list[BridgeLossRecord] = []
    original_keys = set(original)
    restored_keys = set(restored)
    dropped = sorted((original_keys - restored_keys) & observational)
    for index, key in enumerate(dropped):
        losses.append(
            BridgeLossRecord(
                loss_id=f"loss:observational:{index}:{key}",
                kind=LossKind.OBSERVATIONAL,
                path=key,
                description=(
                    f"observational field {key!r} is excluded from semantic identity"
                ),
                recoverable=False,
            )
        )
    return tuple(losses)


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SoftwareVerificationSyntaxBridge:
    """Publish and consume software-verification IRs via the syntax kernel.

    Interface: ``SoftwareVerificationSyntaxBridge@1``.
    """

    INTERFACE: ClassVar[str] = SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE
    VERSION: ClassVar[str] = SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_VERSION

    routes: Mapping[SoftwareVerificationIRKind, IRRouteDescriptor] = field(
        default_factory=default_ir_routes
    )

    def __post_init__(self) -> None:
        routes = dict(self.routes)
        expected = set(SoftwareVerificationIRKind)
        known = set(routes)
        if known != expected:
            missing = sorted(item.value for item in expected - known)
            extra = sorted(
                item.value if isinstance(item, SoftwareVerificationIRKind) else str(item)
                for item in known - expected
            )
            raise SoftwareVerificationBridgeError(
                f"route table must cover every IR kind; missing={missing} extra={extra}",
                code=CODE_ROUTE,
            )
        object.__setattr__(self, "routes", MappingProxyType(routes))

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def domain_id(self) -> str:
        return BRIDGE_DOMAIN_ID

    def known_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(item.value for item in self.routes))

    def route_for(
        self, kind: SoftwareVerificationIRKind | str
    ) -> IRRouteDescriptor:
        try:
            resolved = (
                kind
                if isinstance(kind, SoftwareVerificationIRKind)
                else SoftwareVerificationIRKind(kind)
            )
        except ValueError as error:
            raise UnsupportedConstructError(str(kind)) from error
        try:
            return self.routes[resolved]
        except KeyError as error:
            raise UnsupportedConstructError(resolved.value) from error

    def publish(
        self,
        document: Any,
        *,
        kind: SoftwareVerificationIRKind | str | None = None,
    ) -> SyntaxBridgeResult:
        """Publish a typed domain IR as a syntax-kernel TypedExpression."""

        if document is None:
            raise SoftwareVerificationBridgeError(
                "document is required",
                code=CODE_MALFORMED,
                path="document",
            )
        if isinstance(document, (str, bytes, bytearray)):
            raise FreeFormRejectedError(
                "free-form text/bytes cannot replace a typed software-verification IR"
            )
        if isinstance(document, Mapping) and kind is None:
            # Bare mappings without an explicit kind are free-form.
            raise FreeFormRejectedError(
                "bare JSON mappings require an explicit kind and typed reconstruction"
            )

        resolved_kind = (
            SoftwareVerificationIRKind(kind)
            if kind is not None
            else kind_of(document)
        )
        if kind is not None and not isinstance(document, Mapping):
            expected_type = _KIND_TO_TYPE[resolved_kind]
            if not isinstance(document, expected_type):
                raise SoftwareVerificationBridgeError(
                    f"document type {type(document).__name__} does not match "
                    f"kind {resolved_kind.value}",
                    code=CODE_MALFORMED,
                    path="document",
                )

        # Reconstruct mapping inputs through the typed model first so the
        # bridge never weakens to arbitrary JSON.
        if isinstance(document, Mapping):
            try:
                document = _FROM_DICT[resolved_kind](document)
            except Exception as error:
                raise SoftwareVerificationBridgeError(
                    f"failed to reconstruct typed {resolved_kind.value} IR: {error}",
                    code=CODE_MALFORMED,
                    path="document",
                ) from error

        route = self.route_for(resolved_kind)
        domain_identity = domain_identity_of(document)
        sources = source_identities_of(document)
        payload = _build_payload(
            route=route,
            document=document,
            domain_identity=domain_identity,
            source_identities=sources,
        )
        try:
            root = _extension_root(
                route=route,
                payload=payload,
                domain_identity=domain_identity,
            )
            expression = TypedExpression(
                expression_id=_expression_id(resolved_kind, domain_identity),
                root=root,
                signature=_signature_for(route),
                family=route.family_id,
                profile=route.profile_id,
                elaborate_on_init=False,
                metadata={
                    "bridge": self.INTERFACE,
                    "domain_identity": domain_identity,
                    "kind": resolved_kind.value,
                    "source_identities": list(sources),
                    "view_role": route.view_role,
                },
            )
        except (SyntaxContractError, TypeError, ValueError) as error:
            raise SoftwareVerificationBridgeError(
                f"failed to publish typed expression: {error}",
                code=CODE_PAYLOAD,
                path="expression",
            ) from error

        return SyntaxBridgeResult(
            status=BridgeStatus.OK,
            kind=resolved_kind,
            domain_identity=domain_identity,
            source_identities=sources,
            expression=expression,
            document=document,
            preservation=PreservationKind.EXACT,
            route=route,
        )

    def consume(
        self,
        expression: TypedExpression | LogicNode | Mapping[str, Any],
        *,
        kind: SoftwareVerificationIRKind | str | None = None,
    ) -> SyntaxBridgeResult:
        """Consume a syntax-kernel expression back into a typed domain IR."""

        if isinstance(expression, (str, bytes, bytearray)):
            raise FreeFormRejectedError(
                "free-form text/bytes cannot be consumed as a typed IR"
            )
        if isinstance(expression, Mapping):
            try:
                expression = TypedExpression.from_dict(expression)
            except Exception as error:
                raise FreeFormRejectedError(
                    f"expression mapping is not a TypedExpression: {error}"
                ) from error
        if not isinstance(expression, (TypedExpression, LogicNode)):
            raise SoftwareVerificationBridgeError(
                "consume requires TypedExpression or LogicNode",
                code=CODE_MALFORMED,
                path="expression",
            )

        extension = _extract_extension(expression)
        payload = _thaw_mapping(extension.payload)
        payload_kind = str(payload.get("kind") or "")
        if kind is not None:
            resolved_kind = SoftwareVerificationIRKind(kind)
        elif payload_kind:
            try:
                resolved_kind = SoftwareVerificationIRKind(payload_kind)
            except ValueError as error:
                raise UnsupportedConstructError(payload_kind) from error
        else:
            raise SoftwareVerificationBridgeError(
                "extension payload is missing kind",
                code=CODE_PAYLOAD,
                path="payload.kind",
            )

        route = self.route_for(resolved_kind)
        if extension.payload_schema != route.payload_schema:
            raise SoftwareVerificationBridgeError(
                f"payload_schema {extension.payload_schema!r} does not match "
                f"route schema {route.payload_schema!r}",
                code=CODE_PAYLOAD,
                path="payload_schema",
            )
        family_value = (
            extension.family.value
            if hasattr(extension.family, "value")
            else str(extension.family)
        )
        if family_value != route.family_id:
            raise SoftwareVerificationBridgeError(
                f"extension family {family_value!r} does not match route "
                f"{route.family_id!r}",
                code=CODE_PAYLOAD,
                path="family",
            )

        document_payload = payload.get("document")
        if not isinstance(document_payload, Mapping):
            raise FreeFormRejectedError(
                "extension payload.document must be a typed IR mapping",
                path="payload.document",
            )
        # Reject free-form document envelopes.
        keys = set(document_payload)
        if keys and keys <= {"text", "raw", "blob", "data", "expression", "json"}:
            raise FreeFormRejectedError(
                "payload.document is free-form text/JSON, not a typed IR"
            )

        try:
            document = _FROM_DICT[resolved_kind](document_payload)
        except Exception as error:
            raise SoftwareVerificationBridgeError(
                f"failed to reconstruct typed {resolved_kind.value} IR: {error}",
                code=CODE_MALFORMED,
                path="payload.document",
            ) from error

        domain_identity = domain_identity_of(document)
        declared_identity = str(payload.get("domain_identity") or "")
        if declared_identity and declared_identity != domain_identity:
            raise SoftwareVerificationBridgeError(
                "payload domain_identity does not match reconstructed IR identity",
                code=CODE_IDENTITY_MISMATCH,
                path="domain_identity",
            )

        sources = source_identities_of(document)
        declared_sources = tuple(
            str(item) for item in (payload.get("source_identities") or ())
        )
        losses = list(
            _observational_loss(dict(document_payload), document.to_dict())
        )
        if declared_sources:
            missing = sorted(set(declared_sources) - set(sources))
            if missing:
                losses.append(
                    BridgeLossRecord(
                        loss_id="loss:source_map:missing",
                        kind=LossKind.SOURCE_MAP,
                        path="source_identities",
                        description=(
                            "reconstructed IR is missing declared source identities: "
                            + ", ".join(missing)
                        ),
                        recoverable=False,
                        attributes={"missing": missing},
                    )
                )

        typed_expression = (
            expression
            if isinstance(expression, TypedExpression)
            else None
        )
        status = BridgeStatus.LOSSY if losses else BridgeStatus.OK
        preservation = (
            PreservationKind.LOSSY if losses else PreservationKind.EXACT
        )
        return SyntaxBridgeResult(
            status=status,
            kind=resolved_kind,
            domain_identity=domain_identity,
            source_identities=sources,
            expression=typed_expression,
            document=document,
            preservation=preservation,
            losses=tuple(losses),
            route=route,
        )

    def round_trip(
        self,
        document: Any,
        *,
        kind: SoftwareVerificationIRKind | str | None = None,
    ) -> SyntaxBridgeResult:
        """Publish then consume, preserving domain and source identities."""

        published = self.publish(document, kind=kind)
        assert published.expression is not None
        consumed = self.consume(published.expression, kind=published.kind)

        if consumed.domain_identity != published.domain_identity:
            raise SoftwareVerificationBridgeError(
                "round trip changed domain identity",
                code=CODE_IDENTITY_MISMATCH,
                path="domain_identity",
            )
        missing_sources = sorted(
            set(published.source_identities) - set(consumed.source_identities)
        )
        losses = list(consumed.losses)
        if missing_sources:
            losses.append(
                BridgeLossRecord(
                    loss_id="loss:source_map:round_trip",
                    kind=LossKind.SOURCE_MAP,
                    path="source_identities",
                    description=(
                        "round trip dropped source identities: "
                        + ", ".join(missing_sources)
                    ),
                    recoverable=False,
                    attributes={"missing": missing_sources},
                )
            )

        # Structural equality of the typed wire form is the authoritative
        # domain invariant check (IRs may not implement __eq__ uniformly).
        original = published.document
        restored = consumed.document
        if hasattr(original, "to_dict") and hasattr(restored, "to_dict"):
            if original.to_dict() != restored.to_dict():
                # Content identity fields still matching counts as structural
                # preservation with explicit loss elsewhere.
                if domain_identity_of(original) == domain_identity_of(restored):
                    losses.append(
                        BridgeLossRecord(
                            loss_id="loss:structural:wire_diff",
                            kind=LossKind.OTHER,
                            path="document",
                            description=(
                                "round trip preserved domain identity but "
                                "wire forms differ"
                            ),
                            recoverable=False,
                        )
                    )
                else:
                    raise SoftwareVerificationBridgeError(
                        "round trip failed domain invariant check",
                        code=CODE_IDENTITY_MISMATCH,
                        path="document",
                    )

        status = BridgeStatus.LOSSY if losses else BridgeStatus.OK
        preservation = (
            PreservationKind.LOSSY if losses else PreservationKind.EXACT
        )
        return SyntaxBridgeResult(
            status=status,
            kind=published.kind,
            domain_identity=published.domain_identity,
            source_identities=consumed.source_identities,
            expression=published.expression,
            document=restored,
            preservation=preservation,
            losses=tuple(losses),
            unsupported=(),
            route=published.route,
            diagnostics=(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridge_version": self.VERSION,
            "domain_id": self.domain_id,
            "interface": self.INTERFACE,
            "known_kinds": list(self.known_kinds()),
            "module_version": BRIDGE_MODULE_VERSION,
            "routes": {
                kind.value: route.to_dict() for kind, route in self.routes.items()
            },
            "weakens_to_free_form": False,
        }


def publish_software_verification_ir(
    document: Any,
    *,
    kind: SoftwareVerificationIRKind | str | None = None,
) -> SyntaxBridgeResult:
    """Module-level helper for :meth:`SoftwareVerificationSyntaxBridge.publish`."""

    return SoftwareVerificationSyntaxBridge().publish(document, kind=kind)


def consume_software_verification_expression(
    expression: TypedExpression | LogicNode | Mapping[str, Any],
    *,
    kind: SoftwareVerificationIRKind | str | None = None,
) -> SyntaxBridgeResult:
    """Module-level helper for :meth:`SoftwareVerificationSyntaxBridge.consume`."""

    return SoftwareVerificationSyntaxBridge().consume(expression, kind=kind)


def round_trip_software_verification_ir(
    document: Any,
    *,
    kind: SoftwareVerificationIRKind | str | None = None,
) -> SyntaxBridgeResult:
    """Module-level helper for :meth:`SoftwareVerificationSyntaxBridge.round_trip`."""

    return SoftwareVerificationSyntaxBridge().round_trip(document, kind=kind)


__all__ = [
    "BRIDGE_DOMAIN_ID",
    "BRIDGE_LOSS_SCHEMA",
    "BRIDGE_MODULE_VERSION",
    "BRIDGE_RESULT_SCHEMA",
    "BRIDGE_ROUTE_SCHEMA",
    "BRIDGE_UNSUPPORTED_SCHEMA",
    "BridgeLossRecord",
    "BridgeStatus",
    "CODE_FREE_FORM",
    "CODE_IDENTITY_MISMATCH",
    "CODE_LOSS",
    "CODE_MALFORMED",
    "CODE_PAYLOAD",
    "CODE_ROUTE",
    "CODE_SOURCE_MISMATCH",
    "CODE_UNSUPPORTED",
    "CODE_UNKNOWN_KIND",
    "FreeFormRejectedError",
    "IRRouteDescriptor",
    "LossKind",
    "PreservationKind",
    "SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE",
    "SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_VERSION",
    "SoftwareVerificationBridgeError",
    "SoftwareVerificationIRKind",
    "SoftwareVerificationSyntaxBridge",
    "SyntaxBridgeResult",
    "UnsupportedConstructError",
    "UnsupportedConstructRecord",
    "VC_VIEW_ROLE",
    "consume_software_verification_expression",
    "default_ir_routes",
    "domain_identity_of",
    "kind_of",
    "publish_software_verification_ir",
    "round_trip_software_verification_ir",
    "source_identities_of",
]
