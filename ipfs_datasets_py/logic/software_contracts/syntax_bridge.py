"""Bridge software-contracts AST IR through the shared syntax kernel (LFP-039).

Interface: ``SoftwareContractsSyntaxBridge@1``

The software-contracts :class:`~.ast_ir.ASTRecord` remains the typed owner of
frontend parsing facts.  This bridge only publishes and consumes that record
as a versioned :class:`~ipfs_datasets_py.logic.syntax_core.ast.LogicExtensionNode`
payload inside a :class:`~ipfs_datasets_py.logic.syntax_core.ast.TypedExpression`.
It never weakens the AST IR to free-form text/JSON; unsupported constructs
carried by the AST remain explicit; source provenance identities are preserved
across round trips.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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

from .ast_ir import (
    AST_IR_SCHEMA_VERSION,
    ASTIRValidationError,
    ASTRecord,
    UnsupportedConstruct,
)
from .schema_versions import AST_IR_SCHEMA


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE: Final = (
    "SoftwareContractsSyntaxBridge@1"
)
SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_VERSION: Final = "1.0.0"
BRIDGE_RESULT_SCHEMA: Final = "software-contracts.syntax-bridge-result/v1"
BRIDGE_LOSS_SCHEMA: Final = "software-contracts.syntax-bridge-loss/v1"
BRIDGE_UNSUPPORTED_SCHEMA: Final = (
    "software-contracts.syntax-bridge-unsupported/v1"
)
BRIDGE_ROUTE_SCHEMA: Final = "software-contracts.syntax-bridge-route/v1"
BRIDGE_MODULE_VERSION: Final = "1.0.0"
BRIDGE_DOMAIN_ID: Final = "software_contracts"
AST_FAMILY_ID: Final = "program"
AST_PROFILE_ID: Final = "software_contracts_ast"
AST_FEATURES: Final[tuple[str, ...]] = (
    "software_contracts.ast_ir",
    "program.source_ast",
)
AST_PAYLOAD_SCHEMA: Final = "program.software_contracts_ast_ir/v1"

# Stable diagnostic codes.
CODE_UNSUPPORTED: Final = "software_contracts.unsupported_construct"
CODE_FREE_FORM: Final = "software_contracts.free_form_rejected"
CODE_IDENTITY_MISMATCH: Final = "software_contracts.identity_mismatch"
CODE_SOURCE_MISMATCH: Final = "software_contracts.source_identity_mismatch"
CODE_MALFORMED: Final = "software_contracts.malformed_input"
CODE_PAYLOAD: Final = "software_contracts.invalid_payload"
CODE_ROUTE: Final = "software_contracts.route_error"
CODE_LOSS: Final = "software_contracts.explicit_loss"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
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


class SoftwareContractsBridgeError(ValueError):
    """Raised when a software-contracts syntax bridge request fails closed."""

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


class FreeFormRejectedError(SoftwareContractsBridgeError):
    """Raised when free-form text/JSON is offered in place of ASTRecord."""

    def __init__(self, message: str = "", *, path: str = "document") -> None:
        super().__init__(
            message
            or "free-form text/JSON is rejected; publish a typed ASTRecord",
            code=CODE_FREE_FORM,
            path=path,
        )


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
    SOURCE_MAP = "source_map"
    OTHER = "other"


class PreservationKind(StrEnum):
    """Semantic relationship between AST IR and syntax-kernel view."""

    EXACT = "exact"
    STRUCTURAL = "structural"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContractsRouteDescriptor:
    """Canonical family/profile route for the software-contracts AST IR."""

    family_id: str = AST_FAMILY_ID
    profile_id: str = AST_PROFILE_ID
    features: tuple[str, ...] = AST_FEATURES
    payload_schema: str = AST_PAYLOAD_SCHEMA
    domain_schema: str = AST_IR_SCHEMA_VERSION.identifier
    notes: str = "ASTRecord remains the typed owner of frontend parsing facts."

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_schema": self.domain_schema,
            "family_id": self.family_id,
            "features": list(self.features),
            "kind": "ast_ir",
            "notes": self.notes,
            "payload_schema": self.payload_schema,
            "profile_id": self.profile_id,
            "schema": BRIDGE_ROUTE_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class BridgeLossRecord:
    """Explicit loss that occurred while bridging an AST IR."""

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
            raise SoftwareContractsBridgeError(
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


@dataclass(frozen=True, slots=True)
class UnsupportedConstructRecord:
    """Explicit unsupported construct projected from or into the bridge."""

    construct_id: str
    construct: str
    reason: str
    path: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema: str = BRIDGE_UNSUPPORTED_SCHEMA

    def __post_init__(self) -> None:
        if not self.construct_id or not self.construct or not self.reason:
            raise SoftwareContractsBridgeError(
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
    def from_ast(cls, item: UnsupportedConstruct) -> "UnsupportedConstructRecord":
        return cls(
            construct_id=item.unsupported_id,
            construct=item.construct,
            reason=item.reason or "frontend marked construct unsupported",
            path=item.code,
            attributes={
                "code": item.code,
                "span": item.span.to_dict(),
            },
        )


@dataclass(frozen=True, slots=True)
class ContractsSyntaxBridgeResult:
    """Accounted publish / consume / round-trip outcome for AST IR."""

    status: BridgeStatus | str
    domain_identity: str
    source_identities: tuple[str, ...] = ()
    expression: TypedExpression | None = None
    document: ASTRecord | None = None
    preservation: PreservationKind | str = PreservationKind.EXACT
    losses: tuple[BridgeLossRecord, ...] = ()
    unsupported: tuple[UnsupportedConstructRecord, ...] = ()
    route: ContractsRouteDescriptor | None = None
    diagnostics: tuple[str, ...] = ()
    interface: str = SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE
    schema: str = BRIDGE_RESULT_SCHEMA
    bridge_version: str = SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", BridgeStatus(self.status))
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

    @property
    def ok(self) -> bool:
        return self.status in {BridgeStatus.OK, BridgeStatus.LOSSY}

    @property
    def exact(self) -> bool:
        return (
            self.status is BridgeStatus.OK
            and self.preservation is PreservationKind.EXACT
            and not self.losses
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
            "kind": "ast_ir",
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


def domain_identity_of(document: ASTRecord) -> str:
    """Return the content-addressed identity of an ASTRecord."""

    if not isinstance(document, ASTRecord):
        raise SoftwareContractsBridgeError(
            "domain identity requires an ASTRecord",
            code=CODE_MALFORMED,
            path="document",
        )
    return document.cid


def source_identities_of(document: ASTRecord) -> tuple[str, ...]:
    """Collect provenance and span identities carried by *document*."""

    if not isinstance(document, ASTRecord):
        raise SoftwareContractsBridgeError(
            "source identities require an ASTRecord",
            code=CODE_MALFORMED,
            path="document",
        )
    found: set[str] = set()
    provenance = document.provenance
    found.add(provenance.source_cid)
    found.add(provenance.repository_id)
    found.add(provenance.revision)
    found.add(provenance.path)
    if provenance.repository_tree_cid:
        found.add(provenance.repository_tree_cid)
    found.add(document.module.module_id)
    found.add(document.module.scope_id)
    for scope in document.scopes:
        found.add(scope.scope_id)
    for symbol in document.symbols:
        found.add(symbol.symbol_id)
    for item in document.unsupported:
        found.add(item.unsupported_id)
    return tuple(sorted(item for item in found if item))


def unsupported_of(
    document: ASTRecord,
) -> tuple[UnsupportedConstructRecord, ...]:
    """Project AST unsupported constructs into bridge records."""

    return tuple(
        UnsupportedConstructRecord.from_ast(item) for item in document.unsupported
    )


def _serialize_document(document: ASTRecord) -> dict[str, Any]:
    payload = document.to_dict()
    if not isinstance(payload, Mapping):
        raise FreeFormRejectedError("ASTRecord.to_dict() must return a mapping")
    keys = set(payload)
    if keys and keys <= {"text", "raw", "blob", "data", "expression", "json"}:
        raise FreeFormRejectedError(
            "payload looks like free-form text/JSON rather than AST IR"
        )
    # schema field must remain the reviewed AST schema identity.
    if payload.get("schema") != AST_IR_SCHEMA_VERSION.identifier:
        raise SoftwareContractsBridgeError(
            "ASTRecord schema identity is not the reviewed AST IR schema",
            code=CODE_MALFORMED,
            path="schema",
        )
    return dict(payload)


def _signature() -> LogicSignature:
    return LogicSignature(
        signature_id="sig:sc:ast_ir",
        family=AST_FAMILY_ID,
        profile=AST_PROFILE_ID,
        sorts=(),
        symbols=(),
        features=AST_FEATURES,
        metadata={
            "bridge": SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE,
            "domain": BRIDGE_DOMAIN_ID,
            "kind": "ast_ir",
        },
    )


def _expression_id(domain_identity: str) -> str:
    digest = domain_identity.replace(":", "-").replace("/", "-")
    if len(digest) > 96:
        digest = digest[:96]
    return f"expr:sc:ast_ir:{digest}"


def _node_id(domain_identity: str) -> str:
    digest = domain_identity.replace(":", "-").replace("/", "-")
    if len(digest) > 96:
        digest = digest[:96]
    return f"node:sc:ast_ir:{digest}"


def _build_payload(
    *,
    document: ASTRecord,
    domain_identity: str,
    source_identities: Sequence[str],
) -> dict[str, Any]:
    return {
        "bridge_interface": SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE,
        "bridge_version": SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_VERSION,
        "document": _serialize_document(document),
        "domain_identity": domain_identity,
        "domain_schema": AST_IR_SCHEMA_VERSION.identifier,
        "kind": "ast_ir",
        "schema_version": AST_PAYLOAD_SCHEMA,
        "source_identities": list(source_identities),
        "unsupported_ids": [item.unsupported_id for item in document.unsupported],
    }


def _extension_root(
    *,
    payload: Mapping[str, Any],
    domain_identity: str,
) -> LogicNode:
    return mk_extension(
        _node_id(domain_identity),
        family=AST_FAMILY_ID,
        profile=AST_PROFILE_ID,
        features=AST_FEATURES,
        payload_schema=AST_PAYLOAD_SCHEMA,
        payload=payload,
        children=(),
    )


def _extract_extension(expression: TypedExpression | LogicNode) -> Any:
    root = expression.root if isinstance(expression, TypedExpression) else expression
    if not isinstance(root, LogicNode):
        raise SoftwareContractsBridgeError(
            "expression root must be a LogicNode",
            code=CODE_PAYLOAD,
            path="expression.root",
        )
    if root.kind is not NodeKind.EXTENSION or root.extension is None:
        raise FreeFormRejectedError(
            "typed software-contracts bridge requires a LogicExtensionNode root",
            path="expression.root",
        )
    return root.extension


def _coerce_ast(document: ASTRecord | Mapping[str, Any]) -> ASTRecord:
    if isinstance(document, ASTRecord):
        return document
    if isinstance(document, Mapping):
        try:
            return ASTRecord.from_dict(document)
        except (ASTIRValidationError, TypeError, ValueError) as error:
            raise SoftwareContractsBridgeError(
                f"failed to reconstruct ASTRecord: {error}",
                code=CODE_MALFORMED,
                path="document",
            ) from error
    if isinstance(document, (str, bytes, bytearray)):
        raise FreeFormRejectedError(
            "free-form text/bytes cannot replace a typed ASTRecord"
        )
    raise FreeFormRejectedError(
        f"unsupported document type {type(document).__name__}; expected ASTRecord"
    )


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SoftwareContractsSyntaxBridge:
    """Publish and consume software-contracts AST IR via the syntax kernel.

    Interface: ``SoftwareContractsSyntaxBridge@1``.
    """

    INTERFACE: ClassVar[str] = SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE
    VERSION: ClassVar[str] = SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_VERSION

    route: ContractsRouteDescriptor = field(default_factory=ContractsRouteDescriptor)

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def domain_id(self) -> str:
        return BRIDGE_DOMAIN_ID

    def publish(
        self,
        document: ASTRecord | Mapping[str, Any],
    ) -> ContractsSyntaxBridgeResult:
        """Publish a typed ASTRecord as a syntax-kernel TypedExpression."""

        record = _coerce_ast(document)
        domain_identity = domain_identity_of(record)
        sources = source_identities_of(record)
        unsupported = unsupported_of(record)
        payload = _build_payload(
            document=record,
            domain_identity=domain_identity,
            source_identities=sources,
        )
        try:
            root = _extension_root(payload=payload, domain_identity=domain_identity)
            expression = TypedExpression(
                expression_id=_expression_id(domain_identity),
                root=root,
                signature=_signature(),
                family=self.route.family_id,
                profile=self.route.profile_id,
                elaborate_on_init=False,
                metadata={
                    "bridge": self.INTERFACE,
                    "domain_identity": domain_identity,
                    "kind": "ast_ir",
                    "source_identities": list(sources),
                    "unsupported_ids": [
                        item.construct_id for item in unsupported
                    ],
                },
            )
        except (SyntaxContractError, TypeError, ValueError) as error:
            raise SoftwareContractsBridgeError(
                f"failed to publish typed expression: {error}",
                code=CODE_PAYLOAD,
                path="expression",
            ) from error

        return ContractsSyntaxBridgeResult(
            status=BridgeStatus.OK,
            domain_identity=domain_identity,
            source_identities=sources,
            expression=expression,
            document=record,
            preservation=PreservationKind.EXACT,
            unsupported=unsupported,
            route=self.route,
        )

    def consume(
        self,
        expression: TypedExpression | LogicNode | Mapping[str, Any],
    ) -> ContractsSyntaxBridgeResult:
        """Consume a syntax-kernel expression back into a typed ASTRecord."""

        if isinstance(expression, (str, bytes, bytearray)):
            raise FreeFormRejectedError(
                "free-form text/bytes cannot be consumed as AST IR"
            )
        if isinstance(expression, Mapping):
            try:
                expression = TypedExpression.from_dict(expression)
            except Exception as error:
                raise FreeFormRejectedError(
                    f"expression mapping is not a TypedExpression: {error}"
                ) from error
        if not isinstance(expression, (TypedExpression, LogicNode)):
            raise SoftwareContractsBridgeError(
                "consume requires TypedExpression or LogicNode",
                code=CODE_MALFORMED,
                path="expression",
            )

        extension = _extract_extension(expression)
        if extension.payload_schema != self.route.payload_schema:
            raise SoftwareContractsBridgeError(
                f"payload_schema {extension.payload_schema!r} does not match "
                f"route schema {self.route.payload_schema!r}",
                code=CODE_PAYLOAD,
                path="payload_schema",
            )
        family_value = (
            extension.family.value
            if hasattr(extension.family, "value")
            else str(extension.family)
        )
        if family_value != self.route.family_id:
            raise SoftwareContractsBridgeError(
                f"extension family {family_value!r} does not match route "
                f"{self.route.family_id!r}",
                code=CODE_PAYLOAD,
                path="family",
            )

        payload = _thaw_mapping(extension.payload)
        if str(payload.get("kind") or "") != "ast_ir":
            raise SoftwareContractsBridgeError(
                "extension payload.kind must be 'ast_ir'",
                code=CODE_PAYLOAD,
                path="payload.kind",
            )
        document_payload = payload.get("document")
        if not isinstance(document_payload, Mapping):
            raise FreeFormRejectedError(
                "extension payload.document must be a typed AST mapping",
                path="payload.document",
            )
        keys = set(document_payload)
        if keys and keys <= {"text", "raw", "blob", "data", "expression", "json"}:
            raise FreeFormRejectedError(
                "payload.document is free-form text/JSON, not AST IR"
            )

        record = _coerce_ast(document_payload)
        domain_identity = domain_identity_of(record)
        declared_identity = str(payload.get("domain_identity") or "")
        if declared_identity and declared_identity != domain_identity:
            raise SoftwareContractsBridgeError(
                "payload domain_identity does not match reconstructed AST cid",
                code=CODE_IDENTITY_MISMATCH,
                path="domain_identity",
            )

        sources = source_identities_of(record)
        unsupported = unsupported_of(record)
        losses: list[BridgeLossRecord] = []
        declared_sources = tuple(
            str(item) for item in (payload.get("source_identities") or ())
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
                            "reconstructed AST is missing declared source "
                            "identities: " + ", ".join(missing)
                        ),
                        recoverable=False,
                        attributes={"missing": missing},
                    )
                )

        # Unsupported constructs remain explicit; their presence is not loss.
        typed_expression = (
            expression if isinstance(expression, TypedExpression) else None
        )
        status = BridgeStatus.LOSSY if losses else BridgeStatus.OK
        preservation = (
            PreservationKind.LOSSY if losses else PreservationKind.EXACT
        )
        return ContractsSyntaxBridgeResult(
            status=status,
            domain_identity=domain_identity,
            source_identities=sources,
            expression=typed_expression,
            document=record,
            preservation=preservation,
            losses=tuple(losses),
            unsupported=unsupported,
            route=self.route,
        )

    def round_trip(
        self,
        document: ASTRecord | Mapping[str, Any],
    ) -> ContractsSyntaxBridgeResult:
        """Publish then consume, preserving AST cid and source identities."""

        published = self.publish(document)
        assert published.expression is not None
        consumed = self.consume(published.expression)

        if consumed.domain_identity != published.domain_identity:
            raise SoftwareContractsBridgeError(
                "round trip changed AST content identity",
                code=CODE_IDENTITY_MISMATCH,
                path="domain_identity",
            )
        if published.document is None or consumed.document is None:
            raise SoftwareContractsBridgeError(
                "round trip missing document",
                code=CODE_MALFORMED,
                path="document",
            )
        if published.document.to_dict() != consumed.document.to_dict():
            raise SoftwareContractsBridgeError(
                "round trip failed AST domain invariant check",
                code=CODE_IDENTITY_MISMATCH,
                path="document",
            )
        if published.document.provenance.source_cid != (
            consumed.document.provenance.source_cid
        ):
            raise SoftwareContractsBridgeError(
                "round trip changed source_cid",
                code=CODE_SOURCE_MISMATCH,
                path="provenance.source_cid",
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

        # Preserve explicit unsupported constructs across the trip.
        published_unsupported = {
            item.construct_id for item in published.unsupported
        }
        consumed_unsupported = {
            item.construct_id for item in consumed.unsupported
        }
        if published_unsupported != consumed_unsupported:
            raise SoftwareContractsBridgeError(
                "round trip changed unsupported construct set",
                code=CODE_UNSUPPORTED,
                path="unsupported",
            )

        status = BridgeStatus.LOSSY if losses else BridgeStatus.OK
        preservation = (
            PreservationKind.LOSSY if losses else PreservationKind.EXACT
        )
        return ContractsSyntaxBridgeResult(
            status=status,
            domain_identity=published.domain_identity,
            source_identities=consumed.source_identities,
            expression=published.expression,
            document=consumed.document,
            preservation=preservation,
            losses=tuple(losses),
            unsupported=consumed.unsupported,
            route=self.route,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ast_schema": AST_IR_SCHEMA.identifier,
            "bridge_version": self.VERSION,
            "domain_id": self.domain_id,
            "interface": self.INTERFACE,
            "module_version": BRIDGE_MODULE_VERSION,
            "route": self.route.to_dict(),
            "weakens_to_free_form": False,
        }


def publish_software_contracts_ast(
    document: ASTRecord | Mapping[str, Any],
) -> ContractsSyntaxBridgeResult:
    """Module-level helper for :meth:`SoftwareContractsSyntaxBridge.publish`."""

    return SoftwareContractsSyntaxBridge().publish(document)


def consume_software_contracts_expression(
    expression: TypedExpression | LogicNode | Mapping[str, Any],
) -> ContractsSyntaxBridgeResult:
    """Module-level helper for :meth:`SoftwareContractsSyntaxBridge.consume`."""

    return SoftwareContractsSyntaxBridge().consume(expression)


def round_trip_software_contracts_ast(
    document: ASTRecord | Mapping[str, Any],
) -> ContractsSyntaxBridgeResult:
    """Module-level helper for :meth:`SoftwareContractsSyntaxBridge.round_trip`."""

    return SoftwareContractsSyntaxBridge().round_trip(document)


__all__ = [
    "AST_FAMILY_ID",
    "AST_FEATURES",
    "AST_PAYLOAD_SCHEMA",
    "AST_PROFILE_ID",
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
    "ContractsRouteDescriptor",
    "ContractsSyntaxBridgeResult",
    "FreeFormRejectedError",
    "LossKind",
    "PreservationKind",
    "SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE",
    "SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_VERSION",
    "SoftwareContractsBridgeError",
    "SoftwareContractsSyntaxBridge",
    "UnsupportedConstructRecord",
    "consume_software_contracts_expression",
    "domain_identity_of",
    "publish_software_contracts_ast",
    "round_trip_software_contracts_ast",
    "source_identities_of",
    "unsupported_of",
]
