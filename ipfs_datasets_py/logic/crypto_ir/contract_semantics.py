"""Chain-neutral contract control, coverage, and unsupported semantics.

CRYPTOIR-G300 / CRYPTOIR-014 defines the shared semantic surface used by
frontends and assurance rules:

* :class:`~.state.ContractStateEpoch` — code/state epochs
* :class:`ControlEdge` — ordered control transfer with privilege context
* :class:`~.effects.AssetEffect` — exact asset / storage effects
* :class:`SemanticCoverage` — coverage frontier
* :class:`UnsupportedSemantic` — explicit adapter non-support

**Share concepts, not false equivalences.**  Control-edge kinds distinguish
reentrancy, CPI, spend paths, native ledger transitions, and VM calls as
separate labels that share structural fields (source, target, privileges,
order) without equating VMs to ledger models.

Lossy projection cannot satisfy a proof obligation that depends on discarded
facts: see :func:`assert_obligation_admissible` and
:func:`project_semantic_model`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ..ir_core.canonical import CollectionSchema, CollectionSemantics, canonical_json_bytes
from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, thaw_json
from .effects import (
    ASSET_EFFECT_COLLECTION_SCHEMA,
    CRYPTO_IR_EFFECTS_DOMAIN,
    CRYPTO_IR_EFFECTS_SCHEMA_VERSION,
    AssetEffect,
    EffectKind,
    ordered_effects,
)
from .identity import crypto_ir_identity
from .model import CryptoAssumption, CryptoIRValidationError
from .provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from .state import (
    CONTRACT_STATE_COLLECTION_SCHEMA,
    CRYPTO_IR_STATE_DOMAIN,
    CRYPTO_IR_STATE_SCHEMA_VERSION,
    ContractStateEpoch,
    PrincipalRef,
    PrivilegeFlag,
    PrivilegeSet,
    StateEpochKind,
    StateInvariant,
)


CRYPTO_IR_SEMANTICS_DOMAIN: Final[str] = "crypto-ir.contract-semantics"
CRYPTO_IR_SEMANTICS_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class ControlEdgeKind(str, Enum):
    """Directed control relationship that preserves chain distinctions.

    Shared *concepts* (call-like transfer, conditional branch, return) appear
    as separate kinds for chain-specific mechanisms so rules never silently
    treat Solana CPI as EVM call, or a Bitcoin spend path as a reentrant
    callback:

    * ``CALL`` / ``INTERNAL_CALL`` / ``DELEGATECALL`` / ``STATICCALL`` —
      VM call graph (EVM-family and analogous VMs)
    * ``REENTRANT_CALL`` — callback into a frame already on the stack
    * ``CPI`` / ``INNER_INSTRUCTION`` — Solana cross-program invocation
    * ``SPEND_PATH`` / ``TAPLEAF`` — Bitcoin script / tapscript spend paths
    * ``NATIVE_TRANSITION`` / ``HOOK`` — XRPL ledger / Hooks
    * ``CONTINUE`` / ``CONDITIONAL`` / ``RETURN`` / ``THROW`` / ``FALLTHROUGH``
      — shared CFG primitives
    """

    CALL = "call"
    INTERNAL_CALL = "internal_call"
    DELEGATECALL = "delegatecall"
    STATICCALL = "staticcall"
    REENTRANT_CALL = "reentrant_call"
    CPI = "cpi"
    INNER_INSTRUCTION = "inner_instruction"
    SPEND_PATH = "spend_path"
    TAPLEAF = "tapleaf"
    NATIVE_TRANSITION = "native_transition"
    HOOK = "hook"
    CONTINUE = "continue"
    CONDITIONAL = "conditional"
    RETURN = "return"
    THROW = "throw"
    FALLTHROUGH = "fallthrough"
    OTHER = "other"


class CoverageStatus(str, Enum):
    """Whether a semantic dimension is covered for assurance use."""

    COVERED = "covered"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    OUT_OF_SCOPE = "out_of_scope"


class UnsupportedDisposition(str, Enum):
    """How an adapter treats a semantic it cannot faithfully model."""

    PRESERVE_OPAQUE = "preserve_opaque"
    EXCLUDE = "exclude"
    FAIL_CLOSED = "fail_closed"
    DEFER = "defer"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRValidationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise CryptoIRValidationError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRValidationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (ProvenanceValidationError, CryptoIRProvenanceError, TypeError, ValueError) as exc:
        raise CryptoIRValidationError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRValidationError(f"unsupported {name}: {value!r}") from exc


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise CryptoIRValidationError(f"{name} must be an integer")
    if value < 0:
        raise CryptoIRValidationError(f"{name} must be non-negative")
    return value


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRValidationError(f"{name} values must be unique")
    return result


def _sequence_of(
    values: Any,
    item_type: type[Any],
    name: str,
    *,
    from_dict: Any | None = None,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    converted: list[Any] = []
    for item in values:
        if isinstance(item, item_type):
            converted.append(item)
        elif from_dict is not None and isinstance(item, Mapping):
            converted.append(from_dict(item))
        else:
            raise CryptoIRValidationError(
                f"{name} items must be {item_type.__name__} or mappings"
            )
    return tuple(converted)


# ---------------------------------------------------------------------------
# Control edges
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlEdge:
    """Ordered control-flow / call / spend / CPI edge.

    ``kind`` preserves reentrancy, CPI, and spend-path distinctions.  Privileges
    on the edge are the asserted privilege context for that transfer, not a
    universal ACL.  ``order_index`` is semantic and must be unique within a
    model.
    """

    edge_id: str
    kind: ControlEdgeKind
    source_node_id: str
    target_node_id: str
    order_index: int
    fact_id: str = ""
    privileges: PrivilegeSet = field(default_factory=PrivilegeSet)
    principal_ids: tuple[str, ...] = ()
    state_epoch_id: str = ""
    guard_summary: str = ""
    assumption_ids: tuple[str, ...] = ()
    source_provenance_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_SEMANTICS_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(self, "kind", _enum(ControlEdgeKind, self.kind, "kind"))
        object.__setattr__(
            self, "source_node_id", _identifier(self.source_node_id, "source_node_id")
        )
        object.__setattr__(
            self, "target_node_id", _identifier(self.target_node_id, "target_node_id")
        )
        object.__setattr__(
            self, "order_index", _non_negative_int(self.order_index, "order_index")
        )
        fact = self.fact_id or f"edge:{self.edge_id}"
        object.__setattr__(self, "fact_id", _identifier(fact, "fact_id"))
        if not isinstance(self.privileges, PrivilegeSet):
            if isinstance(self.privileges, Mapping):
                object.__setattr__(
                    self, "privileges", PrivilegeSet.from_dict(self.privileges)
                )
            else:
                object.__setattr__(
                    self, "privileges", PrivilegeSet(flags=self.privileges)
                )
        object.__setattr__(
            self, "principal_ids", _unique_ids(self.principal_ids, "principal_ids")
        )
        object.__setattr__(
            self,
            "state_epoch_id",
            _text(self.state_epoch_id, "state_epoch_id", allow_empty=True),
        )
        if self.state_epoch_id and not _ID_RE.fullmatch(self.state_epoch_id):
            raise CryptoIRValidationError("state_epoch_id is not a stable identifier")
        object.__setattr__(
            self,
            "guard_summary",
            _text(self.guard_summary, "guard_summary", allow_empty=True),
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self,
            "source_provenance_ids",
            _unique_ids(self.source_provenance_ids, "source_provenance_ids"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "edge_id": self.edge_id,
            "fact_id": self.fact_id,
            "guard_summary": self.guard_summary,
            "kind": self.kind.value if isinstance(self.kind, ControlEdgeKind) else self.kind,
            "order_index": self.order_index,
            "principal_ids": list(self.principal_ids),
            "privileges": self.privileges.to_dict(),
            "schema_version": self.schema_version,
            "source_node_id": self.source_node_id,
            "source_provenance_ids": list(self.source_provenance_ids),
            "state_epoch_id": self.state_epoch_id,
            "target_node_id": self.target_node_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ControlEdge":
        value = _as_mapping(value, "ControlEdge")
        _known_fields(
            value,
            frozenset(
                {
                    "edge_id",
                    "kind",
                    "source_node_id",
                    "target_node_id",
                    "order_index",
                    "fact_id",
                    "privileges",
                    "principal_ids",
                    "state_epoch_id",
                    "guard_summary",
                    "assumption_ids",
                    "source_provenance_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "ControlEdge",
        )
        privileges = value.get("privileges", ())
        return cls(
            edge_id=value.get("edge_id", ""),
            kind=value.get("kind", ControlEdgeKind.OTHER),
            source_node_id=value.get("source_node_id", ""),
            target_node_id=value.get("target_node_id", ""),
            order_index=value.get("order_index", 0),
            fact_id=value.get("fact_id", ""),
            privileges=(
                PrivilegeSet.from_dict(privileges)
                if isinstance(privileges, Mapping)
                else PrivilegeSet(flags=privileges)
            ),
            principal_ids=tuple(value.get("principal_ids", ())),
            state_epoch_id=value.get("state_epoch_id", ""),
            guard_summary=value.get("guard_summary", ""),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_SEMANTICS_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SEMANTICS_DOMAIN}.control-edge",
        )


def ordered_control_edges(edges: Sequence[ControlEdge]) -> tuple[ControlEdge, ...]:
    """Return edges sorted by ``order_index``, failing on collisions."""

    if isinstance(edges, (str, bytes, bytearray)) or not isinstance(edges, Sequence):
        raise CryptoIRValidationError("control_edges must be a sequence")
    items = list(edges)
    indices = [item.order_index for item in items]
    if len(indices) != len(set(indices)):
        raise CryptoIRValidationError("control edge order_index values must be unique")
    return tuple(sorted(items, key=lambda item: item.order_index))


# ---------------------------------------------------------------------------
# Coverage and unsupported semantics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticCoverage:
    """Coverage frontier for one semantic dimension.

    ``covered_fact_ids`` are facts the frontend has modeled faithfully.
    ``frontier_fact_ids`` are known-but-unmodeled boundaries (e.g. external
    call targets without bytecode).  ``missing_fact_ids`` are required facts
    that were expected and not obtained.
    """

    coverage_id: str
    dimension: str
    status: CoverageStatus
    fact_id: str = ""
    covered_fact_ids: tuple[str, ...] = ()
    frontier_fact_ids: tuple[str, ...] = ()
    missing_fact_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    source_provenance_ids: tuple[str, ...] = ()
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "coverage_id", _identifier(self.coverage_id, "coverage_id")
        )
        object.__setattr__(self, "dimension", _text(self.dimension, "dimension"))
        object.__setattr__(
            self, "status", _enum(CoverageStatus, self.status, "status")
        )
        fact = self.fact_id or f"coverage:{self.coverage_id}"
        object.__setattr__(self, "fact_id", _identifier(fact, "fact_id"))
        object.__setattr__(
            self,
            "covered_fact_ids",
            _unique_ids(self.covered_fact_ids, "covered_fact_ids"),
        )
        object.__setattr__(
            self,
            "frontier_fact_ids",
            _unique_ids(self.frontier_fact_ids, "frontier_fact_ids"),
        )
        object.__setattr__(
            self,
            "missing_fact_ids",
            _unique_ids(self.missing_fact_ids, "missing_fact_ids"),
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self,
            "source_provenance_ids",
            _unique_ids(self.source_provenance_ids, "source_provenance_ids"),
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

        status = (
            self.status
            if isinstance(self.status, CoverageStatus)
            else CoverageStatus(self.status)
        )
        if status is CoverageStatus.COVERED and self.missing_fact_ids:
            raise CryptoIRValidationError(
                "covered status cannot declare missing_fact_ids"
            )
        if status is CoverageStatus.UNSUPPORTED and self.covered_fact_ids:
            raise CryptoIRValidationError(
                "unsupported status cannot declare covered_fact_ids"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "coverage_id": self.coverage_id,
            "covered_fact_ids": list(self.covered_fact_ids),
            "dimension": self.dimension,
            "fact_id": self.fact_id,
            "frontier_fact_ids": list(self.frontier_fact_ids),
            "missing_fact_ids": list(self.missing_fact_ids),
            "source_provenance_ids": list(self.source_provenance_ids),
            "status": (
                self.status.value
                if isinstance(self.status, CoverageStatus)
                else self.status
            ),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticCoverage":
        value = _as_mapping(value, "SemanticCoverage")
        _known_fields(
            value,
            frozenset(
                {
                    "coverage_id",
                    "dimension",
                    "status",
                    "fact_id",
                    "covered_fact_ids",
                    "frontier_fact_ids",
                    "missing_fact_ids",
                    "assumption_ids",
                    "source_provenance_ids",
                    "summary",
                    "attributes",
                }
            ),
            "SemanticCoverage",
        )
        return cls(
            coverage_id=value.get("coverage_id", ""),
            dimension=value.get("dimension", ""),
            status=value.get("status", CoverageStatus.UNKNOWN),
            fact_id=value.get("fact_id", ""),
            covered_fact_ids=tuple(value.get("covered_fact_ids", ())),
            frontier_fact_ids=tuple(value.get("frontier_fact_ids", ())),
            missing_fact_ids=tuple(value.get("missing_fact_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedSemantic:
    """Explicit record that a chain adapter could not model a semantic.

    Adapters **must** emit this rather than silently drop chain-specific
    behavior.  ``discarded_fact_ids`` lists fact identifiers that a lossy
    projection would remove; proof obligations depending on them fail closed.
    """

    unsupported_id: str
    code: str
    message: str
    disposition: UnsupportedDisposition
    fact_id: str = ""
    chain_namespace: str = ""
    dimension: str = ""
    discarded_fact_ids: tuple[str, ...] = ()
    source_provenance_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "unsupported_id", _identifier(self.unsupported_id, "unsupported_id")
        )
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(self, "message", _text(self.message, "message"))
        object.__setattr__(
            self,
            "disposition",
            _enum(UnsupportedDisposition, self.disposition, "disposition"),
        )
        fact = self.fact_id or f"unsupported:{self.unsupported_id}"
        object.__setattr__(self, "fact_id", _identifier(fact, "fact_id"))
        object.__setattr__(
            self,
            "chain_namespace",
            _text(self.chain_namespace, "chain_namespace", allow_empty=True),
        )
        object.__setattr__(
            self, "dimension", _text(self.dimension, "dimension", allow_empty=True)
        )
        object.__setattr__(
            self,
            "discarded_fact_ids",
            _unique_ids(self.discarded_fact_ids, "discarded_fact_ids"),
        )
        object.__setattr__(
            self,
            "source_provenance_ids",
            _unique_ids(self.source_provenance_ids, "source_provenance_ids"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_namespace": self.chain_namespace,
            "code": self.code,
            "dimension": self.dimension,
            "discarded_fact_ids": list(self.discarded_fact_ids),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, UnsupportedDisposition)
                else self.disposition
            ),
            "fact_id": self.fact_id,
            "message": self.message,
            "source_provenance_ids": list(self.source_provenance_ids),
            "unsupported_id": self.unsupported_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedSemantic":
        value = _as_mapping(value, "UnsupportedSemantic")
        _known_fields(
            value,
            frozenset(
                {
                    "unsupported_id",
                    "code",
                    "message",
                    "disposition",
                    "fact_id",
                    "chain_namespace",
                    "dimension",
                    "discarded_fact_ids",
                    "source_provenance_ids",
                    "attributes",
                }
            ),
            "UnsupportedSemantic",
        )
        return cls(
            unsupported_id=value.get("unsupported_id", ""),
            code=value.get("code", ""),
            message=value.get("message", ""),
            disposition=value.get("disposition", UnsupportedDisposition.FAIL_CLOSED),
            fact_id=value.get("fact_id", ""),
            chain_namespace=value.get("chain_namespace", ""),
            dimension=value.get("dimension", ""),
            discarded_fact_ids=tuple(value.get("discarded_fact_ids", ())),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Proof obligations and projection soundness
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofObligationDependency:
    """A proof obligation and the semantic facts it depends on.

    An obligation is admissible only when every ``required_fact_ids`` entry is
    present in the model's covered fact set and none appear in discarded or
    unsupported discarded sets.
    """

    obligation_id: str
    required_fact_ids: tuple[str, ...]
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "required_fact_ids",
            _unique_ids(self.required_fact_ids, "required_fact_ids"),
        )
        if not self.required_fact_ids:
            raise CryptoIRValidationError(
                "proof obligation must declare at least one required fact"
            )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "obligation_id": self.obligation_id,
            "required_fact_ids": list(self.required_fact_ids),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofObligationDependency":
        value = _as_mapping(value, "ProofObligationDependency")
        _known_fields(
            value,
            frozenset(
                {"obligation_id", "required_fact_ids", "summary", "attributes"}
            ),
            "ProofObligationDependency",
        )
        return cls(
            obligation_id=value.get("obligation_id", ""),
            required_fact_ids=tuple(value.get("required_fact_ids", ())),
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Aggregate semantic model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContractSemanticModel:
    """Ordered, provenance-bearing aggregate of shared contract semantics.

    Collections declare semantics:

    * ``control_edges`` and ``effects`` are **ordered** (order_index)
    * ``state_epochs``, ``principals``, ``invariants``, ``assumptions``,
      ``coverage``, ``unsupported`` are **set-like** by stable id
    """

    model_id: str
    chain_namespace: str
    state_epochs: tuple[ContractStateEpoch, ...] = ()
    principals: tuple[PrincipalRef, ...] = ()
    control_edges: tuple[ControlEdge, ...] = ()
    effects: tuple[AssetEffect, ...] = ()
    invariants: tuple[StateInvariant, ...] = ()
    assumptions: tuple[CryptoAssumption, ...] = ()
    coverage: tuple[SemanticCoverage, ...] = ()
    unsupported: tuple[UnsupportedSemantic, ...] = ()
    source_provenance_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_SEMANTICS_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", _identifier(self.model_id, "model_id"))
        object.__setattr__(
            self, "chain_namespace", _text(self.chain_namespace, "chain_namespace")
        )
        object.__setattr__(
            self,
            "state_epochs",
            _sequence_of(
                self.state_epochs,
                ContractStateEpoch,
                "state_epochs",
                from_dict=ContractStateEpoch.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "principals",
            _sequence_of(
                self.principals,
                PrincipalRef,
                "principals",
                from_dict=PrincipalRef.from_dict,
            ),
        )
        edges = _sequence_of(
            self.control_edges,
            ControlEdge,
            "control_edges",
            from_dict=ControlEdge.from_dict,
        )
        object.__setattr__(self, "control_edges", ordered_control_edges(edges))
        effects = _sequence_of(
            self.effects,
            AssetEffect,
            "effects",
            from_dict=AssetEffect.from_dict,
        )
        object.__setattr__(self, "effects", ordered_effects(effects))
        object.__setattr__(
            self,
            "invariants",
            _sequence_of(
                self.invariants,
                StateInvariant,
                "invariants",
                from_dict=StateInvariant.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _sequence_of(
                self.assumptions,
                CryptoAssumption,
                "assumptions",
                from_dict=CryptoAssumption.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "coverage",
            _sequence_of(
                self.coverage,
                SemanticCoverage,
                "coverage",
                from_dict=SemanticCoverage.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "unsupported",
            _sequence_of(
                self.unsupported,
                UnsupportedSemantic,
                "unsupported",
                from_dict=UnsupportedSemantic.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "source_provenance_ids",
            _unique_ids(self.source_provenance_ids, "source_provenance_ids"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        self._assert_unique_ids()

    def _assert_unique_ids(self) -> None:
        def _check(items: Sequence[Any], attr: str, name: str) -> None:
            ids = [getattr(item, attr) for item in items]
            if len(ids) != len(set(ids)):
                raise CryptoIRValidationError(f"{name} ids must be unique")

        _check(self.state_epochs, "epoch_id", "state_epochs")
        _check(self.principals, "principal_id", "principals")
        _check(self.control_edges, "edge_id", "control_edges")
        _check(self.effects, "effect_id", "effects")
        _check(self.invariants, "invariant_id", "invariants")
        _check(self.assumptions, "assumption_id", "assumptions")
        _check(self.coverage, "coverage_id", "coverage")
        _check(self.unsupported, "unsupported_id", "unsupported")

    def all_fact_ids(self) -> frozenset[str]:
        """Every fact_id contributed by modeled records in this model."""

        facts: set[str] = set()
        for epoch in self.state_epochs:
            facts.add(epoch.fact_id)
        for edge in self.control_edges:
            facts.add(edge.fact_id)
        for effect in self.effects:
            facts.add(effect.fact_id)
        for invariant in self.invariants:
            facts.add(invariant.fact_id)
        for assumption in self.assumptions:
            facts.add(f"assumption:{assumption.assumption_id}")
        for cov in self.coverage:
            facts.add(cov.fact_id)
            facts.update(cov.covered_fact_ids)
        for item in self.unsupported:
            facts.add(item.fact_id)
        return frozenset(facts)

    def discarded_fact_ids(self) -> frozenset[str]:
        """Fact ids an adapter declared as discarded or unsupported."""

        discarded: set[str] = set()
        for item in self.unsupported:
            discarded.update(item.discarded_fact_ids)
            if item.disposition is UnsupportedDisposition.EXCLUDE:
                discarded.add(item.fact_id)
        for cov in self.coverage:
            discarded.update(cov.missing_fact_ids)
            if cov.status in {
                CoverageStatus.UNSUPPORTED,
                CoverageStatus.OUT_OF_SCOPE,
            }:
                discarded.update(cov.frontier_fact_ids)
        return frozenset(discarded)

    def covered_fact_ids(self) -> frozenset[str]:
        """Union of explicitly covered facts and fully modeled record facts."""

        covered: set[str] = set()
        for cov in self.coverage:
            if cov.status in {CoverageStatus.COVERED, CoverageStatus.PARTIAL}:
                covered.update(cov.covered_fact_ids)
        # Modeled records are covered unless explicitly discarded.
        discarded = self.discarded_fact_ids()
        for fact_id in self.all_fact_ids():
            if fact_id not in discarded:
                covered.add(fact_id)
        return frozenset(covered) - discarded

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "attributes": thaw_json(self.attributes),
            "chain_namespace": self.chain_namespace,
            "control_edges": [item.to_dict() for item in self.control_edges],
            "coverage": [item.to_dict() for item in self.coverage],
            "effects": [item.to_dict() for item in self.effects],
            "invariants": [item.to_dict() for item in self.invariants],
            "model_id": self.model_id,
            "principals": [item.to_dict() for item in self.principals],
            "schema_version": self.schema_version,
            "source_provenance_ids": list(self.source_provenance_ids),
            "state_epochs": [item.to_dict() for item in self.state_epochs],
            "unsupported": [item.to_dict() for item in self.unsupported],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractSemanticModel":
        value = _as_mapping(value, "ContractSemanticModel")
        _known_fields(
            value,
            frozenset(
                {
                    "model_id",
                    "chain_namespace",
                    "state_epochs",
                    "principals",
                    "control_edges",
                    "effects",
                    "invariants",
                    "assumptions",
                    "coverage",
                    "unsupported",
                    "source_provenance_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "ContractSemanticModel",
        )
        return cls(
            model_id=value.get("model_id", ""),
            chain_namespace=value.get("chain_namespace", ""),
            state_epochs=tuple(value.get("state_epochs", ())),
            principals=tuple(value.get("principals", ())),
            control_edges=tuple(value.get("control_edges", ())),
            effects=tuple(value.get("effects", ())),
            invariants=tuple(value.get("invariants", ())),
            assumptions=tuple(value.get("assumptions", ())),
            coverage=tuple(value.get("coverage", ())),
            unsupported=tuple(value.get("unsupported", ())),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_SEMANTICS_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SEMANTICS_DOMAIN}.model",
        )


def project_semantic_model(
    model: ContractSemanticModel,
    *,
    drop_fact_ids: Iterable[str] | None = None,
    mark_unsupported: Sequence[UnsupportedSemantic] = (),
) -> ContractSemanticModel:
    """Project a model by dropping facts (lossy) and/or adding unsupported.

    Dropped edges/effects/epochs are removed from the projected model and
    recorded via ``mark_unsupported`` or a synthetic exclude record so
    :func:`assert_obligation_admissible` can reject obligations that needed
    the discarded facts.
    """

    drop = frozenset(_identifier(item, "drop_fact_ids") for item in (drop_fact_ids or ()))
    if not drop and not mark_unsupported:
        return model

    unsupported = list(model.unsupported)
    unsupported.extend(
        item
        if isinstance(item, UnsupportedSemantic)
        else UnsupportedSemantic.from_dict(item)
        for item in mark_unsupported
    )
    if drop:
        unsupported.append(
            UnsupportedSemantic(
                unsupported_id=f"projection-drop-{model.model_id}",
                code="lossy_projection",
                message="facts discarded by lossy projection",
                disposition=UnsupportedDisposition.EXCLUDE,
                discarded_fact_ids=tuple(sorted(drop)),
                dimension="projection",
                chain_namespace=model.chain_namespace,
            )
        )

    def _keep_fact(fact_id: str) -> bool:
        return fact_id not in drop

    return ContractSemanticModel(
        model_id=f"{model.model_id}:projected",
        chain_namespace=model.chain_namespace,
        state_epochs=tuple(
            item for item in model.state_epochs if _keep_fact(item.fact_id)
        ),
        principals=model.principals,
        control_edges=tuple(
            item for item in model.control_edges if _keep_fact(item.fact_id)
        ),
        effects=tuple(item for item in model.effects if _keep_fact(item.fact_id)),
        invariants=tuple(
            item for item in model.invariants if _keep_fact(item.fact_id)
        ),
        assumptions=model.assumptions,
        coverage=model.coverage,
        unsupported=tuple(unsupported),
        source_provenance_ids=model.source_provenance_ids,
        attributes=dict(model.attributes),
        schema_version=model.schema_version,
    )


def assert_obligation_admissible(
    model: ContractSemanticModel,
    obligation: ProofObligationDependency,
) -> None:
    """Fail closed when an obligation depends on discarded or missing facts.

    A lossy projection cannot satisfy a proof obligation that depends on
    facts it discarded.  Unsupported dimensions also block obligations that
    require those facts.
    """

    if not isinstance(obligation, ProofObligationDependency):
        obligation = ProofObligationDependency.from_dict(
            _as_mapping(obligation, "obligation")
        )
    discarded = model.discarded_fact_ids()
    covered = model.covered_fact_ids()
    missing_from_cover = [
        fact_id
        for fact_id in obligation.required_fact_ids
        if fact_id not in covered
    ]
    depends_on_discarded = [
        fact_id
        for fact_id in obligation.required_fact_ids
        if fact_id in discarded
    ]
    if depends_on_discarded:
        raise CryptoIRValidationError(
            "lossy projection cannot satisfy proof obligation "
            f"{obligation.obligation_id!r}; discarded facts required: "
            f"{', '.join(depends_on_discarded)}"
        )
    if missing_from_cover:
        raise CryptoIRValidationError(
            "proof obligation "
            f"{obligation.obligation_id!r} depends on uncovered facts: "
            f"{', '.join(missing_from_cover)}"
        )


def control_kinds_are_distinct(
    left: ControlEdgeKind | str, right: ControlEdgeKind | str
) -> bool:
    """Return True when two control kinds are different labels.

    Used by tests and adapters to refuse false equivalences (e.g. mapping CPI
    onto CALL without an explicit, reviewed lowering).
    """

    left_kind = _enum(ControlEdgeKind, left, "left")
    right_kind = _enum(ControlEdgeKind, right, "right")
    return left_kind is not right_kind


CONTRACT_SEMANTICS_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/control_edges": CollectionSemantics.ORDERED,
        "/effects": CollectionSemantics.ORDERED,
        "/state_epochs": CollectionSemantics.SET_LIKE,
        "/principals": CollectionSemantics.SET_LIKE,
        "/invariants": CollectionSemantics.SET_LIKE,
        "/assumptions": CollectionSemantics.SET_LIKE,
        "/coverage": CollectionSemantics.SET_LIKE,
        "/unsupported": CollectionSemantics.SET_LIKE,
        "/source_provenance_ids": CollectionSemantics.SET_LIKE,
    }
)


__all__ = [
    "ASSET_EFFECT_COLLECTION_SCHEMA",
    "CONTRACT_SEMANTICS_COLLECTION_SCHEMA",
    "CONTRACT_STATE_COLLECTION_SCHEMA",
    "CRYPTO_IR_EFFECTS_DOMAIN",
    "CRYPTO_IR_EFFECTS_SCHEMA_VERSION",
    "CRYPTO_IR_SEMANTICS_DOMAIN",
    "CRYPTO_IR_SEMANTICS_SCHEMA_VERSION",
    "CRYPTO_IR_STATE_DOMAIN",
    "CRYPTO_IR_STATE_SCHEMA_VERSION",
    "AssetEffect",
    "ContractSemanticModel",
    "ContractStateEpoch",
    "ControlEdge",
    "ControlEdgeKind",
    "CoverageStatus",
    "EffectKind",
    "PrincipalRef",
    "PrivilegeFlag",
    "PrivilegeSet",
    "ProofObligationDependency",
    "SemanticCoverage",
    "StateEpochKind",
    "StateInvariant",
    "UnsupportedDisposition",
    "UnsupportedSemantic",
    "assert_obligation_admissible",
    "control_kinds_are_distinct",
    "ordered_control_edges",
    "ordered_effects",
    "project_semantic_model",
]
