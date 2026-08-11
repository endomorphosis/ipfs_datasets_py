"""State, concurrency, refinement, and temporal translation edges.

``StateTemporalTranslationEdges@1`` publishes reviewed
``TranslationContract@2`` routes that map supported transition, concurrency,
refinement, and temporal properties to TLA+, bounded SMT, runtime MTL, and
HyperLTL encodings.

Every edge carries mandatory semantic receipts for:

* finite/infinite (or finite-prefix) trace model;
* fairness assumptions;
* refinement direction (or an explicit non-applicable value);
* clock domain; and
* bounds (including an explicit ``bound:unbounded`` disclosure).

Omission of any receipt is rejected at construction.  The catalog never
launders approximation into equivalence: bounded and monitor routes declare
``PreservationRelation.BOUNDED`` with authority at most ``BOUNDED``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    NodeDisposition,
    NodeMapEntry,
    PreservationRelation,
    SymbolMapEntry,
    TranslationAssumptionSet,
    TranslationContract,
    TranslationContractError,
    TranslationEndpoint,
    TranslationIdentities,
)
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.translations.planner import (
    TranslationPathPlanner,
    TranslationPathPlannerError,
)


STATE_TEMPORAL_EDGES_INTERFACE: Final = "StateTemporalTranslationEdges@1"
STATE_TEMPORAL_EDGES_SCHEMA_VERSION: Final = "logic-state-temporal-translation-edges/v1"
EDGE_RECEIPT_SCHEMA_VERSION: Final = "logic-state-temporal-edge-receipt/v1"
EDGE_RECEIPT_IDENTITY_DOMAIN: Final = "logic.translation.state_temporal.edge"
CATALOG_IDENTITY_DOMAIN: Final = "logic.translation.state_temporal.catalog"
COMPILER_IDENTITY: Final = "state-temporal-translation-compiler@1"
ENVIRONMENT_IDENTITY: Final = "state-temporal-translation-environment@1"


class StateTemporalTranslationError(ValueError):
    """Raised when a state/temporal edge or catalog is invalid."""


class TraceKind(str, Enum):
    """Finite/infinite (or finite-prefix) trace model; never omitted."""

    FINITE = "finite"
    INFINITE = "infinite"
    FINITE_PREFIX = "finite_prefix"
    FINITE_OR_INFINITE = "finite_or_infinite"


class FairnessKind(str, Enum):
    """Fairness assumption carried by a state/temporal route; never omitted."""

    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"
    UNCONDITIONAL = "unconditional"


class RefinementDirection(str, Enum):
    """Simulation/refinement direction; never omitted (use NOT_APPLICABLE)."""

    FORWARD = "forward"
    BACKWARD = "backward"
    BISIMULATION = "bisimulation"
    NOT_APPLICABLE = "not_applicable"


class ClockKind(str, Enum):
    """Clock domain for timed/monitor routes; never omitted."""

    DISCRETE = "discrete"
    DENSE = "dense"
    EVENT = "event"
    LOGICAL = "logical"
    NOT_APPLICABLE = "not_applicable"


class RouteKind(str, Enum):
    """Semantic family of a catalog edge."""

    TRANSITION = "transition"
    CONCURRENCY = "concurrency"
    REFINEMENT = "refinement"
    TEMPORAL = "temporal"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StateTemporalTranslationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise StateTemporalTranslationError(
            f"{field_name} must not contain NUL bytes"
        )
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name)


def _identifier(value: object, field_name: str) -> str:
    return _text(value, field_name)


def _strings(
    values: Sequence[str] | object,
    field_name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise StateTemporalTranslationError(
            f"{field_name} must be a sequence of strings"
        )
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = (
            _identifier(item, f"{field_name} item")
            if identifiers
            else _text(item, f"{field_name} item")
        )
        if text in seen:
            raise StateTemporalTranslationError(
                f"{field_name} must not contain duplicates"
            )
        seen.add(text)
        result.append(text)
    return tuple(result)


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StateTemporalTranslationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StateTemporalTranslationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise StateTemporalTranslationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise StateTemporalTranslationError(f"{field_name} must be a bool")
    return value


def _node(
    source: str,
    *targets: str,
    disposition: NodeDisposition | str = NodeDisposition.MAPPED,
    reason: str = "",
) -> NodeMapEntry:
    return NodeMapEntry(
        source_node_id=source,
        target_node_ids=targets,
        disposition=disposition,
        reason=reason,
    )


def _symbol(
    source: str,
    *targets: str,
    disposition: NodeDisposition | str = NodeDisposition.MAPPED,
    reason: str = "",
) -> SymbolMapEntry:
    return SymbolMapEntry(
        source_symbol_id=source,
        target_symbol_ids=targets,
        disposition=disposition,
        reason=reason,
    )


def _endpoint(
    family_id: str,
    *,
    profile_id: str = "",
    fragment_id: str = "",
    schema_id: str = "",
    notation_id: str = "",
    content_identity: str = "",
) -> TranslationEndpoint:
    family = _identifier(family_id, "family_id")
    return TranslationEndpoint(
        family_id=family,
        profile_id=profile_id or f"{family}_default",
        fragment_id=fragment_id or f"{family}_core",
        schema_id=schema_id or f"{family}_schema",
        notation_id=notation_id or f"{family}_notation",
        content_identity=content_identity or f"sha256:endpoint:{family}:{profile_id or 'default'}",
    )


def _identities(
    *,
    compiler_identity: str = COMPILER_IDENTITY,
    profile_identity: str,
    config_identity: str,
    source_identity: str = "",
    target_identity: str = "",
    environment_identity: str = ENVIRONMENT_IDENTITY,
) -> TranslationIdentities:
    return TranslationIdentities(
        compiler_identity=compiler_identity,
        profile_identity=profile_identity,
        config_identity=config_identity,
        source_identity=source_identity,
        target_identity=target_identity,
        environment_identity=environment_identity,
    )


def _require_non_omitted(value: object, field_name: str) -> None:
    """Reject missing/empty values for mandatory semantic receipts."""

    if value is None:
        raise StateTemporalTranslationError(
            f"{field_name} cannot be omitted"
        )
    if isinstance(value, str) and not value.strip():
        raise StateTemporalTranslationError(
            f"{field_name} cannot be omitted"
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        if len(value) == 0:
            raise StateTemporalTranslationError(
                f"{field_name} cannot be omitted"
            )


@dataclass(frozen=True, slots=True)
class StateTemporalSemanticReceipt:
    """Mandatory fairness/trace/clock/bound/refinement receipts for one edge.

    Acceptance criterion: finite/infinite trace, fairness, refinement
    direction, clocks, and bounds cannot be omitted.
    """

    trace_kind: TraceKind | str
    fairness: FairnessKind | str
    refinement_direction: RefinementDirection | str
    clock: ClockKind | str
    bounds: tuple[str, ...]
    route_kind: RouteKind | str
    stuttering_allowed: bool = False
    description: str = ""
    schema_version: str = EDGE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Fail closed on omission before enum coercion.
        _require_non_omitted(self.trace_kind, "trace_kind")
        _require_non_omitted(self.fairness, "fairness")
        _require_non_omitted(self.refinement_direction, "refinement_direction")
        _require_non_omitted(self.clock, "clock")
        _require_non_omitted(self.bounds, "bounds")
        _require_non_omitted(self.route_kind, "route_kind")

        object.__setattr__(
            self, "trace_kind", _enum(self.trace_kind, TraceKind, "trace_kind")
        )
        object.__setattr__(
            self, "fairness", _enum(self.fairness, FairnessKind, "fairness")
        )
        object.__setattr__(
            self,
            "refinement_direction",
            _enum(
                self.refinement_direction,
                RefinementDirection,
                "refinement_direction",
            ),
        )
        object.__setattr__(
            self, "clock", _enum(self.clock, ClockKind, "clock")
        )
        object.__setattr__(
            self,
            "route_kind",
            _enum(self.route_kind, RouteKind, "route_kind"),
        )
        object.__setattr__(
            self,
            "bounds",
            _strings(self.bounds, "bounds", identifiers=True),
        )
        if not self.bounds:
            raise StateTemporalTranslationError("bounds cannot be omitted")
        object.__setattr__(
            self,
            "stuttering_allowed",
            _bool(self.stuttering_allowed, "stuttering_allowed"),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )
        if self.schema_version != EDGE_RECEIPT_SCHEMA_VERSION:
            raise StateTemporalTranslationError(
                f"unsupported edge receipt schema {self.schema_version!r}"
            )

        # Route-specific integrity.
        if self.route_kind is RouteKind.REFINEMENT:
            if self.refinement_direction is RefinementDirection.NOT_APPLICABLE:
                raise StateTemporalTranslationError(
                    "refinement routes require an explicit refinement_direction "
                    "(forward, backward, or bisimulation)"
                )
        if self.route_kind is RouteKind.TEMPORAL:
            if self.clock is ClockKind.NOT_APPLICABLE and any(
                bound.startswith("bound:clock") for bound in self.bounds
            ):
                raise StateTemporalTranslationError(
                    "clock-bounded temporal routes require an explicit clock"
                )

    def assumption_ids(self) -> TranslationAssumptionSet:
        """Project semantic receipts into a TranslationAssumptionSet."""

        fairness_ids = (f"fairness:{self.fairness.value}",)
        bound_ids = tuple(self.bounds)
        domain_changes = (
            f"trace:{self.trace_kind.value}",
            f"clock:{self.clock.value}",
            f"refinement_direction:{self.refinement_direction.value}",
        )
        other = (
            f"route:{self.route_kind.value}",
            f"stuttering:{'allowed' if self.stuttering_allowed else 'forbidden'}",
        )
        return TranslationAssumptionSet(
            fairness=fairness_ids,
            bounds=bound_ids,
            domain_changes=domain_changes,
            other=other,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": list(self.bounds),
            "clock": self.clock.value,
            "description": self.description,
            "fairness": self.fairness.value,
            "refinement_direction": self.refinement_direction.value,
            "route_kind": self.route_kind.value,
            "schema_version": self.schema_version,
            "stuttering_allowed": self.stuttering_allowed,
            "trace_kind": self.trace_kind.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateTemporalSemanticReceipt":
        value = _mapping(value, "state temporal semantic receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "bounds",
                    "clock",
                    "description",
                    "fairness",
                    "refinement_direction",
                    "route_kind",
                    "schema_version",
                    "stuttering_allowed",
                    "trace_kind",
                }
            ),
            "state temporal semantic receipt",
        )
        # Explicit omission checks for dict ingress (None / missing keys).
        for required in (
            "trace_kind",
            "fairness",
            "refinement_direction",
            "clock",
            "bounds",
            "route_kind",
        ):
            if required not in value or value.get(required) is None:
                raise StateTemporalTranslationError(
                    f"{required} cannot be omitted"
                )
        return cls(
            trace_kind=value["trace_kind"],
            fairness=value["fairness"],
            refinement_direction=value["refinement_direction"],
            clock=value["clock"],
            bounds=tuple(value["bounds"]),
            route_kind=value["route_kind"],
            stuttering_allowed=bool(value.get("stuttering_allowed", False)),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", EDGE_RECEIPT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class StateTemporalEdge:
    """One reviewed state/temporal translation edge with mandatory receipts."""

    edge_id: str
    contract: TranslationContract
    receipt: StateTemporalSemanticReceipt
    edge_content_id: str = ""

    schema_version: ClassVar[str] = EDGE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))

        contract = self.contract
        if isinstance(contract, Mapping):
            try:
                contract = TranslationContract.from_dict(contract)
            except (TranslationContractError, ValueError) as error:
                raise StateTemporalTranslationError(str(error)) from error
        if not isinstance(contract, TranslationContract):
            raise StateTemporalTranslationError(
                "contract must be a TranslationContract"
            )
        object.__setattr__(self, "contract", contract)

        if self.edge_id != contract.contract_id:
            raise StateTemporalTranslationError(
                f"edge_id {self.edge_id!r} must match contract_id "
                f"{contract.contract_id!r}"
            )

        receipt = self.receipt
        if isinstance(receipt, Mapping):
            receipt = StateTemporalSemanticReceipt.from_dict(receipt)
        if not isinstance(receipt, StateTemporalSemanticReceipt):
            raise StateTemporalTranslationError(
                "receipt must be a StateTemporalSemanticReceipt"
            )
        object.__setattr__(self, "receipt", receipt)

        # Contract assumptions must include every mandatory receipt projection.
        projected = receipt.assumption_ids()
        if not contract.assumptions.issuperset(projected):
            missing = sorted(
                set(projected.all_assumption_ids)
                - set(contract.assumptions.all_assumption_ids)
            )
            raise StateTemporalTranslationError(
                "contract assumptions omit mandatory semantic receipts: "
                + ", ".join(missing)
            )

        # Bounded preservation requires a real bound id (not only unbounded).
        if contract.preservation is PreservationRelation.BOUNDED:
            concrete = [
                bound
                for bound in receipt.bounds
                if bound != "bound:unbounded"
            ]
            if not concrete:
                raise StateTemporalTranslationError(
                    "bounded edges require at least one concrete bound "
                    "(bound:unbounded alone is insufficient)"
                )

        # Refinement edges must declare direction both in receipt and assumptions.
        if receipt.route_kind is RouteKind.REFINEMENT:
            direction_token = (
                f"refinement_direction:{receipt.refinement_direction.value}"
            )
            if direction_token not in contract.assumptions.domain_changes:
                raise StateTemporalTranslationError(
                    "refinement direction cannot be omitted from contract "
                    "domain_changes"
                )

        computed = self._compute_identity()
        if self.edge_content_id and self.edge_content_id != computed.cid:
            raise StateTemporalTranslationError(
                "edge_content_id does not match canonical edge content"
            )
        object.__setattr__(self, "edge_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=EDGE_RECEIPT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.edge_content_id

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "contract_content_id": self.contract.contract_content_id,
            "contract_id": self.contract.contract_id,
            "edge_id": self.edge_id,
            "receipt": self.receipt.to_dict(),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract"] = self.contract.to_dict()
        payload["edge_content_id"] = self.edge_content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateTemporalEdge":
        value = _mapping(value, "state temporal edge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "contract",
                    "contract_content_id",
                    "contract_id",
                    "edge_content_id",
                    "edge_id",
                    "receipt",
                    "schema_version",
                }
            ),
            "state temporal edge",
        )
        return cls(
            edge_id=value.get("edge_id", ""),
            contract=value.get("contract", {}),  # type: ignore[arg-type]
            receipt=value.get("receipt", {}),  # type: ignore[arg-type]
            edge_content_id=value.get("edge_content_id", ""),
        )


def _build_contract(
    *,
    contract_id: str,
    source: TranslationEndpoint,
    target: TranslationEndpoint,
    preservation: PreservationRelation,
    authority_ceiling: EvidenceAuthority,
    proof_safe: bool,
    counterexample_safe: bool,
    receipt: StateTemporalSemanticReceipt,
    node_map: Sequence[NodeMapEntry],
    symbol_map: Sequence[SymbolMapEntry],
    feature_preconditions: Sequence[str],
    unsupported_constructs: Sequence[str] = (),
    extra_assumptions: TranslationAssumptionSet | None = None,
    checker_route: str = "",
    reconstruction_route: str = "",
    description: str = "",
    profile_identity: str,
    config_identity: str,
) -> TranslationContract:
    assumptions = receipt.assumption_ids()
    if extra_assumptions is not None:
        assumptions = assumptions.union(extra_assumptions)
    required_nodes = tuple(entry.source_node_id for entry in node_map)
    required_symbols = tuple(entry.source_symbol_id for entry in symbol_map)
    try:
        return TranslationContract(
            contract_id=contract_id,
            source=source,
            target=target,
            preservation=preservation,
            identities=_identities(
                profile_identity=profile_identity,
                config_identity=config_identity,
                source_identity=source.content_identity,
                target_identity=target.content_identity,
            ),
            proof_safe=proof_safe,
            counterexample_safe=counterexample_safe,
            authority_ceiling=authority_ceiling,
            assumptions=assumptions,
            node_map=tuple(node_map),
            symbol_map=tuple(symbol_map),
            required_source_node_ids=required_nodes,
            required_source_symbol_ids=required_symbols,
            feature_preconditions=tuple(feature_preconditions),
            unsupported_constructs=tuple(unsupported_constructs),
            checker_route=checker_route,
            reconstruction_route=reconstruction_route,
            description=description,
        )
    except (TranslationContractError, ValueError) as error:
        raise StateTemporalTranslationError(str(error)) from error


def _edge(
    contract: TranslationContract,
    receipt: StateTemporalSemanticReceipt,
) -> StateTemporalEdge:
    return StateTemporalEdge(
        edge_id=contract.contract_id,
        contract=contract,
        receipt=receipt,
    )


def _reviewed_catalog() -> tuple[StateTemporalEdge, ...]:
    """Build the reviewed state/concurrency/refinement/temporal edge set."""

    edges: list[StateTemporalEdge] = []

    # ------------------------------------------------------------------
    # Transition system -> TLA+ profile (infinite traces, weak fairness).
    # ------------------------------------------------------------------
    ts_tla_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.INFINITE,
        fairness=FairnessKind.WEAK,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.DISCRETE,
        bounds=("bound:unbounded", "bound:state_vars_finite"),
        route_kind=RouteKind.TRANSITION,
        stuttering_allowed=True,
        description="Transition systems to TLA+ modules with fairness receipts.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="transition_system_to_tla_plus",
                source=_endpoint(
                    "transition_system",
                    profile_id="transition_system_default",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "transition_system",
                    profile_id="tla_plus",
                    fragment_id="tla_action_system",
                    notation_id="tla_plus_source",
                ),
                preservation=PreservationRelation.TRACE_PRESERVING,
                authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
                proof_safe=True,
                counterexample_safe=True,
                receipt=ts_tla_receipt,
                node_map=(
                    _node("n_init", "tla_init", disposition=NodeDisposition.PRESERVED),
                    _node("n_next", "tla_next", disposition=NodeDisposition.MAPPED),
                    _node(
                        "n_invariant",
                        "tla_invariant",
                        disposition=NodeDisposition.PRESERVED,
                    ),
                    _node(
                        "n_fairness",
                        "tla_wf",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                symbol_map=(
                    _symbol("var_state", "tla_var", disposition=NodeDisposition.PRESERVED),
                    _symbol("act_step", "tla_action", disposition=NodeDisposition.MAPPED),
                ),
                feature_preconditions=(
                    "feat_transition_init",
                    "feat_transition_next",
                    "feat_state_invariant",
                    "feat_fairness",
                ),
                unsupported_constructs=("feat_dense_time", "feat_hyper_quantifier"),
                checker_route="tla_tlc:transition",
                reconstruction_route="replay:tla_trace",
                description=(
                    "Maps typed transition systems to TLA+ action systems "
                    "with explicit fairness and infinite-trace receipts."
                ),
                profile_identity="profile:transition_system_to_tla_plus",
                config_identity="config:tla_plus_infinite_weak_fairness",
            ),
            ts_tla_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Transition system -> bounded SMT (finite unrolling).
    # ------------------------------------------------------------------
    ts_smt_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.FINITE,
        fairness=FairnessKind.NONE,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.LOGICAL,
        bounds=("bound:bmc_depth_32", "bound:state_domain_finite"),
        route_kind=RouteKind.TRANSITION,
        stuttering_allowed=False,
        description="Bounded unrolling of transition systems into SMT.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="transition_system_to_bounded_smt",
                source=_endpoint(
                    "transition_system",
                    profile_id="transition_system_default",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "first_order",
                    profile_id="qf_uf_bounded",
                    fragment_id="bmc_unrolling",
                    notation_id="smt_lib2",
                ),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=True,
                counterexample_safe=True,
                receipt=ts_smt_receipt,
                node_map=(
                    _node("n_init", "smt_init", disposition=NodeDisposition.MAPPED),
                    _node(
                        "n_next",
                        "smt_next_unroll",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite BMC unrolling",
                    ),
                    _node(
                        "n_invariant",
                        "smt_assert_invariant",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_fairness",
                        disposition=NodeDisposition.DROPPED,
                        reason="bounded BMC does not encode infinite-trace fairness",
                    ),
                ),
                symbol_map=(
                    _symbol("var_state", "smt_state_k", disposition=NodeDisposition.MAPPED),
                ),
                feature_preconditions=(
                    "feat_transition_init",
                    "feat_transition_next",
                    "feat_state_invariant",
                    "feat_finite_domain",
                ),
                unsupported_constructs=(
                    "feat_liveness_unbounded",
                    "feat_strong_fairness",
                    "feat_hyper_quantifier",
                ),
                checker_route="smt:bmc",
                reconstruction_route="replay:bmc_trace",
                description=(
                    "Bounded model-checking unrolling of transition systems "
                    "to SMT-LIB with explicit depth and domain bounds."
                ),
                profile_identity="profile:transition_system_to_bounded_smt",
                config_identity="config:bmc_depth_32",
            ),
            ts_smt_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Concurrency -> TLA+ (interference + weak fairness).
    # ------------------------------------------------------------------
    conc_tla_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.INFINITE,
        fairness=FairnessKind.WEAK,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.DISCRETE,
        bounds=("bound:unbounded", "bound:interleaving_schedule"),
        route_kind=RouteKind.CONCURRENCY,
        stuttering_allowed=True,
        description="Concurrent systems to TLA+ with interference fairness.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="concurrency_to_tla_plus",
                source=_endpoint(
                    "concurrency",
                    profile_id="rely_guarantee",
                    fragment_id="interleaving",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "transition_system",
                    profile_id="tla_plus",
                    fragment_id="tla_concurrent",
                    notation_id="tla_plus_source",
                ),
                preservation=PreservationRelation.TRACE_PRESERVING,
                authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
                proof_safe=True,
                counterexample_safe=True,
                receipt=conc_tla_receipt,
                node_map=(
                    _node(
                        "n_component_step",
                        "tla_process_action",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_environment_step",
                        "tla_env_action",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_interference",
                        "tla_interference",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_fairness",
                        "tla_wf_processes",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                symbol_map=(
                    _symbol(
                        "comp_thread",
                        "tla_process",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _symbol(
                        "var_shared",
                        "tla_shared_var",
                        disposition=NodeDisposition.PRESERVED,
                    ),
                ),
                feature_preconditions=(
                    "feat_component_step",
                    "feat_environment_step",
                    "feat_interference",
                    "feat_fairness",
                ),
                unsupported_constructs=(
                    "feat_unbounded_session",
                    "feat_hyper_quantifier",
                ),
                extra_assumptions=TranslationAssumptionSet(
                    closure_assumptions=("closure:interleaving_semantics",),
                    other=("interference:explicit",),
                ),
                checker_route="tla_tlc:concurrency",
                reconstruction_route="replay:tla_concurrent_trace",
                description=(
                    "Projects concurrent component/environment steps into "
                    "TLA+ process actions with explicit interference and "
                    "fairness assumptions."
                ),
                profile_identity="profile:concurrency_to_tla_plus",
                config_identity="config:concurrency_weak_fairness",
            ),
            conc_tla_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Concurrency -> bounded SMT schedule.
    # ------------------------------------------------------------------
    conc_smt_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.FINITE,
        fairness=FairnessKind.NONE,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.LOGICAL,
        bounds=("bound:schedule_length_16", "bound:thread_count_8"),
        route_kind=RouteKind.CONCURRENCY,
        stuttering_allowed=False,
        description="Bounded concurrent schedules to SMT.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="concurrency_to_bounded_smt",
                source=_endpoint(
                    "concurrency",
                    profile_id="rely_guarantee",
                    fragment_id="interleaving",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "first_order",
                    profile_id="qf_uf_bounded",
                    fragment_id="bounded_schedule",
                    notation_id="smt_lib2",
                ),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=True,
                counterexample_safe=True,
                receipt=conc_smt_receipt,
                node_map=(
                    _node(
                        "n_component_step",
                        "smt_thread_step",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite schedule unrolling",
                    ),
                    _node(
                        "n_environment_step",
                        "smt_env_step",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite environment interference window",
                    ),
                    _node(
                        "n_interference",
                        "smt_interfere",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_fairness",
                        disposition=NodeDisposition.DROPPED,
                        reason="bounded schedules cannot claim infinite fairness",
                    ),
                ),
                symbol_map=(
                    _symbol(
                        "comp_thread",
                        "smt_thread_id",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                feature_preconditions=(
                    "feat_component_step",
                    "feat_environment_step",
                    "feat_interference",
                    "feat_bounded_schedule",
                ),
                unsupported_constructs=(
                    "feat_liveness_unbounded",
                    "feat_strong_fairness",
                ),
                checker_route="smt:bounded_schedule",
                reconstruction_route="replay:schedule_trace",
                description=(
                    "Encodes bounded concurrent schedules into SMT with "
                    "explicit schedule-length and thread-count bounds."
                ),
                profile_identity="profile:concurrency_to_bounded_smt",
                config_identity="config:schedule_16_threads_8",
            ),
            conc_smt_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Refinement -> transition system (forward simulation).
    # ------------------------------------------------------------------
    ref_fwd_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.INFINITE,
        fairness=FairnessKind.WEAK,
        refinement_direction=RefinementDirection.FORWARD,
        clock=ClockKind.DISCRETE,
        bounds=("bound:unbounded", "bound:simulation_relation"),
        route_kind=RouteKind.REFINEMENT,
        stuttering_allowed=True,
        description="Forward simulation refinement to transition systems.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="refinement_forward_to_transition_system",
                source=_endpoint(
                    "refinement",
                    profile_id="simulation",
                    fragment_id="forward_simulation",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "transition_system",
                    profile_id="transition_system_default",
                    fragment_id="simulation_product",
                    notation_id="canonical_text",
                ),
                preservation=PreservationRelation.THEOREM_PRESERVING,
                authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
                proof_safe=True,
                counterexample_safe=False,
                receipt=ref_fwd_receipt,
                node_map=(
                    _node(
                        "n_abstract_step",
                        "ts_abstract_step",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_concrete_step",
                        "ts_concrete_step",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_simulation_couple",
                        "ts_related_states",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_refinement_obligation",
                        "ts_simulation_invariant",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                symbol_map=(
                    _symbol(
                        "sys_abstract",
                        "ts_abstract",
                        disposition=NodeDisposition.PRESERVED,
                    ),
                    _symbol(
                        "sys_concrete",
                        "ts_concrete",
                        disposition=NodeDisposition.PRESERVED,
                    ),
                ),
                feature_preconditions=(
                    "feat_refinement_forward",
                    "feat_simulation_relation",
                    "feat_abstract_system",
                    "feat_concrete_system",
                ),
                unsupported_constructs=(
                    "feat_refinement_backward",
                    "feat_bounded_schedule_only",
                ),
                checker_route="kernel:refinement_simulation",
                reconstruction_route="replay:simulation_witness",
                description=(
                    "Forward simulation obligations over abstract/concrete "
                    "systems with explicit refinement direction receipts."
                ),
                profile_identity="profile:refinement_forward",
                config_identity="config:forward_simulation_unbounded",
            ),
            ref_fwd_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Refinement -> bounded SMT (bounded schedule, never unbounded claim).
    # ------------------------------------------------------------------
    ref_bmc_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.FINITE,
        fairness=FairnessKind.NONE,
        refinement_direction=RefinementDirection.FORWARD,
        clock=ClockKind.LOGICAL,
        bounds=("bound:refinement_steps_24", "bound:state_pairs_4096"),
        route_kind=RouteKind.REFINEMENT,
        stuttering_allowed=False,
        description="Bounded forward refinement checks in SMT.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="refinement_forward_to_bounded_smt",
                source=_endpoint(
                    "refinement",
                    profile_id="simulation",
                    fragment_id="forward_simulation",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "first_order",
                    profile_id="qf_uf_bounded",
                    fragment_id="bounded_refinement",
                    notation_id="smt_lib2",
                ),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=True,
                counterexample_safe=True,
                receipt=ref_bmc_receipt,
                node_map=(
                    _node(
                        "n_abstract_step",
                        "smt_abs_step",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite step bound",
                    ),
                    _node(
                        "n_concrete_step",
                        "smt_conc_step",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite step bound",
                    ),
                    _node(
                        "n_simulation_couple",
                        "smt_related",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_refinement_obligation",
                        "smt_obligation",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                symbol_map=(
                    _symbol(
                        "sys_abstract",
                        "smt_abs",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _symbol(
                        "sys_concrete",
                        "smt_conc",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                feature_preconditions=(
                    "feat_refinement_forward",
                    "feat_simulation_relation",
                    "feat_bounded_schedule",
                ),
                unsupported_constructs=(
                    "feat_unbounded_refinement",
                    "feat_bisimulation",
                ),
                checker_route="smt:bounded_refinement",
                reconstruction_route="replay:refinement_counterexample",
                description=(
                    "Bounded forward refinement obligations; schedule bounds "
                    "prevent claiming unbounded refinement authority."
                ),
                profile_identity="profile:refinement_forward_bounded",
                config_identity="config:refinement_steps_24",
            ),
            ref_bmc_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Temporal (LTL infinite) -> TLA+.
    # ------------------------------------------------------------------
    temp_tla_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.INFINITE,
        fairness=FairnessKind.WEAK,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.DISCRETE,
        bounds=("bound:unbounded", "bound:ltl_operators"),
        route_kind=RouteKind.TEMPORAL,
        stuttering_allowed=True,
        description="Infinite-trace LTL to TLA+ temporal formulas.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="temporal_ltl_to_tla_plus",
                source=_endpoint(
                    "temporal",
                    profile_id="ltl_infinite",
                    fragment_id="ltl_core",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "transition_system",
                    profile_id="tla_plus",
                    fragment_id="tla_temporal",
                    notation_id="tla_plus_source",
                ),
                preservation=PreservationRelation.TRACE_PRESERVING,
                authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
                proof_safe=True,
                counterexample_safe=True,
                receipt=temp_tla_receipt,
                node_map=(
                    _node("n_always", "tla_box", disposition=NodeDisposition.MAPPED),
                    _node(
                        "n_eventually",
                        "tla_diamond",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node("n_until", "tla_until", disposition=NodeDisposition.MAPPED),
                    _node("n_next", "tla_next", disposition=NodeDisposition.MAPPED),
                    _node(
                        "n_atom",
                        "tla_state_predicate",
                        disposition=NodeDisposition.PRESERVED,
                    ),
                ),
                symbol_map=(
                    _symbol("p", "tla_p", disposition=NodeDisposition.PRESERVED),
                ),
                feature_preconditions=(
                    "feat_temporal_always",
                    "feat_temporal_eventually",
                    "feat_temporal_until",
                    "feat_infinite_trace",
                ),
                unsupported_constructs=(
                    "feat_metric_interval",
                    "feat_past_operators",
                    "feat_hyper_quantifier",
                ),
                checker_route="tla_tlc:ltl",
                reconstruction_route="replay:tla_temporal_trace",
                description=(
                    "Encodes infinite-trace LTL formulas as TLA+ temporal "
                    "properties with fairness and discrete-clock receipts."
                ),
                profile_identity="profile:temporal_ltl_to_tla_plus",
                config_identity="config:ltl_infinite_weak_fairness",
            ),
            temp_tla_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Temporal (MTL/LTLf finite) -> runtime MTL monitor.
    # ------------------------------------------------------------------
    temp_mtl_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.FINITE_PREFIX,
        fairness=FairnessKind.NONE,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.DENSE,
        bounds=(
            "bound:finite_prefix",
            "bound:clock:dense_rational",
            "bound:monitor_horizon",
        ),
        route_kind=RouteKind.TEMPORAL,
        stuttering_allowed=False,
        description="Finite/prefix MTL to runtime monitor with clock receipts.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="temporal_mtl_to_runtime_mtl",
                source=_endpoint(
                    "temporal",
                    profile_id="mtl_finite",
                    fragment_id="mtl_core",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "temporal",
                    profile_id="runtime_mtl",
                    fragment_id="runtime_monitor",
                    notation_id="runtime_mtl_trace",
                ),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=temp_mtl_receipt,
                node_map=(
                    _node(
                        "n_always",
                        "mon_always",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite-prefix monitoring is three-valued",
                    ),
                    _node(
                        "n_eventually",
                        "mon_eventually",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite-prefix monitoring is three-valued",
                    ),
                    _node(
                        "n_until",
                        "mon_until",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_metric_interval",
                        "mon_interval",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_atom",
                        "mon_atom",
                        disposition=NodeDisposition.PRESERVED,
                    ),
                ),
                symbol_map=(
                    _symbol("p", "mon_p", disposition=NodeDisposition.PRESERVED),
                    _symbol(
                        "clock_event",
                        "mon_clock",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                feature_preconditions=(
                    "feat_temporal_always",
                    "feat_temporal_eventually",
                    "feat_metric_interval",
                    "feat_finite_trace",
                    "feat_clock",
                ),
                unsupported_constructs=(
                    "feat_infinite_trace",
                    "feat_path_quantifier",
                    "feat_hyper_quantifier",
                ),
                checker_route="runtime_mtl:monitor",
                reconstruction_route="replay:monitor_verdict",
                description=(
                    "Lowers finite/prefix MTL formulas to runtime MTL monitors. "
                    "Authority remains monitor-bounded; clocks and finite-prefix "
                    "bounds are mandatory."
                ),
                profile_identity="profile:temporal_mtl_to_runtime_mtl",
                config_identity="config:runtime_mtl_dense_clock",
            ),
            temp_mtl_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Temporal -> bounded SMT (finite-trace BMC).
    # ------------------------------------------------------------------
    temp_smt_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.FINITE,
        fairness=FairnessKind.NONE,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.LOGICAL,
        bounds=("bound:bmc_depth_64", "bound:proposition_set_finite"),
        route_kind=RouteKind.TEMPORAL,
        stuttering_allowed=False,
        description="Finite-trace temporal formulas to bounded SMT.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="temporal_to_bounded_smt",
                source=_endpoint(
                    "temporal",
                    profile_id="ltlf_finite",
                    fragment_id="ltlf_core",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "first_order",
                    profile_id="qf_uf_bounded",
                    fragment_id="temporal_bmc",
                    notation_id="smt_lib2",
                ),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=True,
                counterexample_safe=True,
                receipt=temp_smt_receipt,
                node_map=(
                    _node(
                        "n_always",
                        "smt_always_unroll",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite unrolling of G",
                    ),
                    _node(
                        "n_eventually",
                        "smt_eventually_unroll",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite unrolling of F",
                    ),
                    _node(
                        "n_until",
                        "smt_until_unroll",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite unrolling of U",
                    ),
                    _node(
                        "n_atom",
                        "smt_atom_k",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                symbol_map=(
                    _symbol("p", "smt_p_k", disposition=NodeDisposition.MAPPED),
                ),
                feature_preconditions=(
                    "feat_temporal_always",
                    "feat_temporal_eventually",
                    "feat_finite_trace",
                ),
                unsupported_constructs=(
                    "feat_infinite_trace",
                    "feat_metric_interval",
                    "feat_path_quantifier",
                ),
                checker_route="smt:temporal_bmc",
                reconstruction_route="replay:temporal_bmc_trace",
                description=(
                    "Finite-trace temporal BMC encoding into SMT-LIB with "
                    "explicit depth bounds."
                ),
                profile_identity="profile:temporal_to_bounded_smt",
                config_identity="config:temporal_bmc_depth_64",
            ),
            temp_smt_receipt,
        )
    )

    # ------------------------------------------------------------------
    # Temporal -> HyperLTL (restricted single-trace embedding).
    # ------------------------------------------------------------------
    temp_hyper_receipt = StateTemporalSemanticReceipt(
        trace_kind=TraceKind.INFINITE,
        fairness=FairnessKind.WEAK,
        refinement_direction=RefinementDirection.NOT_APPLICABLE,
        clock=ClockKind.DISCRETE,
        bounds=("bound:trace_quantifiers_1", "bound:system_copies_1"),
        route_kind=RouteKind.TEMPORAL,
        stuttering_allowed=True,
        description="Single-trace temporal formulas as HyperLTL without alternation.",
    )
    edges.append(
        _edge(
            _build_contract(
                contract_id="temporal_to_hyperltl",
                source=_endpoint(
                    "temporal",
                    profile_id="ltl_infinite",
                    fragment_id="ltl_core",
                    notation_id="canonical_text",
                ),
                target=_endpoint(
                    "hyperproperty",
                    profile_id="hyperltl",
                    fragment_id="single_trace",
                    notation_id="hyperltl_source",
                ),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=True,
                counterexample_safe=True,
                receipt=temp_hyper_receipt,
                node_map=(
                    _node(
                        "n_always",
                        "hyper_always",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_eventually",
                        "hyper_eventually",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_until",
                        "hyper_until",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_atom",
                        "hyper_atom_pi",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_trace_quantifier",
                        "hyper_forall_pi",
                        disposition=NodeDisposition.SYNTHESIZED,
                        reason="single universal trace quantifier introduced",
                    ),
                ),
                symbol_map=(
                    _symbol("p", "hyper_p_pi", disposition=NodeDisposition.MAPPED),
                    _symbol(
                        "trace_pi",
                        "hyper_pi",
                        disposition=NodeDisposition.SYNTHESIZED,
                        reason="named single-trace variable",
                    ),
                ),
                feature_preconditions=(
                    "feat_temporal_always",
                    "feat_temporal_eventually",
                    "feat_infinite_trace",
                ),
                unsupported_constructs=(
                    "feat_hyper_alternation",
                    "feat_multi_trace",
                    "feat_metric_interval",
                ),
                checker_route="hyperltl:single_trace",
                reconstruction_route="replay:hyper_trace",
                description=(
                    "Embeds ordinary temporal formulas as single-trace HyperLTL "
                    "with explicit quantifier and system-copy bounds."
                ),
                profile_identity="profile:temporal_to_hyperltl",
                config_identity="config:hyperltl_single_trace",
            ),
            temp_hyper_receipt,
        )
    )

    return tuple(sorted(edges, key=lambda edge: edge.edge_id))


@dataclass(frozen=True, slots=True)
class StateTemporalTranslationEdges:
    """Reviewed state/concurrency/refinement/temporal edge catalog.

    Interface: ``StateTemporalTranslationEdges@1``.
    """

    edges: tuple[StateTemporalEdge, ...] = field(default_factory=tuple)
    catalog_content_id: str = ""
    description: str = (
        "Reviewed transition, concurrency, refinement, and temporal "
        "translation routes with mandatory fairness/trace/clock/bound receipts."
    )

    interface: ClassVar[str] = STATE_TEMPORAL_EDGES_INTERFACE
    schema_version: ClassVar[str] = STATE_TEMPORAL_EDGES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalized: list[StateTemporalEdge] = []
        seen: set[str] = set()
        for index, edge in enumerate(self.edges):
            if isinstance(edge, Mapping):
                edge = StateTemporalEdge.from_dict(edge)
            if not isinstance(edge, StateTemporalEdge):
                raise StateTemporalTranslationError(
                    f"edges[{index}] must be a StateTemporalEdge"
                )
            if edge.edge_id in seen:
                raise StateTemporalTranslationError(
                    f"duplicate edge_id {edge.edge_id!r}"
                )
            seen.add(edge.edge_id)
            # Re-validate mandatory receipts (defensive).
            receipt = edge.receipt
            for field_name, value in (
                ("trace_kind", receipt.trace_kind),
                ("fairness", receipt.fairness),
                ("refinement_direction", receipt.refinement_direction),
                ("clock", receipt.clock),
                ("bounds", receipt.bounds),
            ):
                _require_non_omitted(value, field_name)
            normalized.append(edge)

        object.__setattr__(
            self,
            "edges",
            tuple(sorted(normalized, key=lambda item: item.edge_id)),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )
        computed = self._compute_identity()
        if self.catalog_content_id and self.catalog_content_id != computed.cid:
            raise StateTemporalTranslationError(
                "catalog_content_id does not match canonical catalog content"
            )
        object.__setattr__(self, "catalog_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=CATALOG_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.catalog_content_id

    def __iter__(self):
        return iter(self.edges)

    def __len__(self) -> int:
        return len(self.edges)

    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    def get(self, edge_id: str) -> StateTemporalEdge:
        edge_id = _identifier(edge_id, "edge_id")
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return edge
        raise StateTemporalTranslationError(f"unknown edge_id {edge_id!r}")

    def contracts(self) -> tuple[TranslationContract, ...]:
        """Return underlying TranslationContract edges for the planner."""

        return tuple(edge.contract for edge in self.edges)

    def by_route_kind(self, route_kind: RouteKind | str) -> tuple[StateTemporalEdge, ...]:
        selected = _enum(route_kind, RouteKind, "route_kind")
        return tuple(
            edge for edge in self.edges if edge.receipt.route_kind is selected
        )

    def by_target_family(
        self, family_id: str, *, profile_id: str = ""
    ) -> tuple[StateTemporalEdge, ...]:
        family_id = _identifier(family_id, "family_id")
        profile_id = _optional_text(profile_id, "profile_id")
        result: list[StateTemporalEdge] = []
        for edge in self.edges:
            if edge.contract.target.family_id != family_id:
                continue
            if profile_id and edge.contract.target.profile_id != profile_id:
                continue
            result.append(edge)
        return tuple(result)

    def register_with_planner(
        self, planner: TranslationPathPlanner | None = None
    ) -> TranslationPathPlanner:
        """Register all catalog contracts with a path planner."""

        if planner is None:
            planner = TranslationPathPlanner()
        if not isinstance(planner, TranslationPathPlanner):
            raise StateTemporalTranslationError(
                "planner must be a TranslationPathPlanner"
            )
        try:
            planner.register_edges(self.contracts())
        except TranslationPathPlannerError as error:
            raise StateTemporalTranslationError(str(error)) from error
        return planner

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "edge_content_ids": [edge.edge_content_id for edge in self.edges],
            "edge_ids": list(self.edge_ids()),
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["catalog_content_id"] = self.catalog_content_id
        payload["edges"] = [edge.to_dict() for edge in self.edges]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateTemporalTranslationEdges":
        value = _mapping(value, "state temporal translation edges")
        _reject_unknown(
            value,
            frozenset(
                {
                    "catalog_content_id",
                    "description",
                    "edge_content_ids",
                    "edge_ids",
                    "edges",
                    "interface",
                    "schema_version",
                }
            ),
            "state temporal translation edges",
        )
        interface = value.get("interface", STATE_TEMPORAL_EDGES_INTERFACE)
        if interface != STATE_TEMPORAL_EDGES_INTERFACE:
            raise StateTemporalTranslationError(
                f"unsupported state temporal edges interface {interface!r}"
            )
        schema = value.get("schema_version", STATE_TEMPORAL_EDGES_SCHEMA_VERSION)
        if schema != STATE_TEMPORAL_EDGES_SCHEMA_VERSION:
            raise StateTemporalTranslationError(
                f"unsupported state temporal edges schema {schema!r}"
            )
        edges_raw = value.get("edges", ())
        if not isinstance(edges_raw, Sequence) or isinstance(
            edges_raw, (str, bytes, bytearray)
        ):
            raise StateTemporalTranslationError("edges must be a sequence")
        return cls(
            edges=tuple(edges_raw),  # type: ignore[arg-type]
            catalog_content_id=value.get("catalog_content_id", ""),
            description=value.get("description", ""),
        )

    @classmethod
    def reviewed(cls) -> "StateTemporalTranslationEdges":
        """Return the built-in reviewed catalog."""

        return cls(edges=_reviewed_catalog())


def build_state_temporal_edges() -> StateTemporalTranslationEdges:
    """Public factory for the reviewed state/temporal edge catalog."""

    return StateTemporalTranslationEdges.reviewed()


def state_temporal_contracts() -> tuple[TranslationContract, ...]:
    """Return planner-ready TranslationContract edges from the catalog."""

    return build_state_temporal_edges().contracts()


def require_semantic_receipts(
    *,
    trace_kind: object,
    fairness: object,
    refinement_direction: object,
    clock: object,
    bounds: object,
    route_kind: object = RouteKind.TEMPORAL,
    stuttering_allowed: bool = False,
    description: str = "",
) -> StateTemporalSemanticReceipt:
    """Validate and construct a mandatory semantic receipt (fail-closed)."""

    return StateTemporalSemanticReceipt(
        trace_kind=trace_kind,  # type: ignore[arg-type]
        fairness=fairness,  # type: ignore[arg-type]
        refinement_direction=refinement_direction,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        bounds=bounds,  # type: ignore[arg-type]
        route_kind=route_kind,  # type: ignore[arg-type]
        stuttering_allowed=stuttering_allowed,
        description=description,
    )


__all__ = [
    "CATALOG_IDENTITY_DOMAIN",
    "COMPILER_IDENTITY",
    "ClockKind",
    "EDGE_RECEIPT_SCHEMA_VERSION",
    "ENVIRONMENT_IDENTITY",
    "FairnessKind",
    "RefinementDirection",
    "RouteKind",
    "STATE_TEMPORAL_EDGES_INTERFACE",
    "STATE_TEMPORAL_EDGES_SCHEMA_VERSION",
    "StateTemporalEdge",
    "StateTemporalSemanticReceipt",
    "StateTemporalTranslationEdges",
    "StateTemporalTranslationError",
    "TraceKind",
    "build_state_temporal_edges",
    "require_semantic_receipts",
    "state_temporal_contracts",
]
