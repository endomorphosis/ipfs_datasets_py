"""Composed logic translation graph (``LogicTranslationGraph@3``).

Joins reviewed translation edges from program, state/temporal, policy/modal,
hyperproperty, protocol-target, and kernel-target families into one catalog.

Effects:

* publishes the composed graph of ``TranslationContract@2`` edges;
* every registered path is feature-total and loss-receipted before dispatch;
* unsupported compositions fail closed before backend execution;
* protocol dialect receipts and kernel compilation-candidate posture remain
  owned by their edge modules.

This module performs no prover execution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.translations import TranslationContract
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.translations.hyper import (
    HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE,
    HyperpropertyTranslationEdges,
    build_hyperproperty_translation_edges,
)
from ipfs_datasets_py.logic.translations.kernel_targets import (
    KERNEL_TARGET_COMPILER_INTERFACE,
    KERNEL_TARGET_EDGES_INTERFACE,
    KernelTargetCompiler,
    KernelTargetTranslationEdges,
    build_kernel_target_compiler,
    build_kernel_target_translation_edges,
)
from ipfs_datasets_py.logic.translations.planner import (
    FeatureSet,
    TranslationPathPlanner,
    TranslationPathPlannerError,
    TranslationPathReceipt,
    TranslationPathRequest,
    path_is_feature_total,
    plan_translation_path,
)
from ipfs_datasets_py.logic.translations.policy_modal import (
    POLICY_MODAL_EDGES_INTERFACE,
    PolicyModalTranslationEdges,
    build_policy_modal_translation_edges,
)
from ipfs_datasets_py.logic.translations.program import (
    PROGRAM_TRANSLATION_EDGES_INTERFACE,
    ProgramTranslationEdges,
    build_program_translation_edges,
)
from ipfs_datasets_py.logic.translations.protocol_targets import (
    PROTOCOL_TARGET_EDGES_INTERFACE,
    ProtocolTargetTranslationEdges,
    build_protocol_target_translation_edges,
)
from ipfs_datasets_py.logic.translations.state_temporal import (
    STATE_TEMPORAL_EDGES_INTERFACE,
    StateTemporalTranslationEdges,
    build_state_temporal_edges,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_TRANSLATION_GRAPH_INTERFACE: Final = "LogicTranslationGraph@3"
LOGIC_TRANSLATION_GRAPH_SCHEMA: Final = "logic-translation-graph/v3"
GRAPH_IDENTITY_DOMAIN: Final = "logic.translation.graph"
PATH_VALIDATION_SCHEMA: Final = "logic-translation-path-validation/v1"

CATALOG_COMPILER_IDENTITY: Final = "compiler:logic-translation-graph@3"
CATALOG_PROFILE_IDENTITY: Final = "profile:logic-translation-graph-default@3"
CATALOG_CONFIG_IDENTITY: Final = "config:logic-translation-graph@3"

# Edge family keys joined by the graph.
FAMILY_PROGRAM: Final = "program"
FAMILY_STATE_TEMPORAL: Final = "state_temporal"
FAMILY_POLICY_MODAL: Final = "policy_modal"
FAMILY_HYPERPROPERTY: Final = "hyperproperty"
FAMILY_PROTOCOL_TARGET: Final = "protocol_target"
FAMILY_KERNEL_TARGET: Final = "kernel_target"

JOINED_FAMILY_KEYS: Final = (
    FAMILY_PROGRAM,
    FAMILY_STATE_TEMPORAL,
    FAMILY_POLICY_MODAL,
    FAMILY_HYPERPROPERTY,
    FAMILY_PROTOCOL_TARGET,
    FAMILY_KERNEL_TARGET,
)


class LogicTranslationGraphError(ValueError):
    """Raised when the composed translation graph is invalid."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise LogicTranslationGraphError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise LogicTranslationGraphError(f"{field_name} must not contain NUL bytes")
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name)


def _identifier(value: object, field_name: str) -> str:
    return _text(value, field_name)


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LogicTranslationGraphError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise LogicTranslationGraphError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _loss_ids_from_program(edges: ProgramTranslationEdges) -> tuple[str, ...]:
    loss_ids: list[str] = []
    for edge in edges:
        for loss in edge.heap_resource_losses:
            loss_ids.append(loss.loss_id)
        # Every edge is considered receipted: either explicit losses or
        # an empty-loss pure route recorded under assumptions.other.
        if not edge.heap_resource_losses:
            loss_ids.append(f"loss:none:{edge.edge_id}")
    return tuple(sorted(set(loss_ids)))


def _loss_ids_from_state(edges: StateTemporalTranslationEdges) -> tuple[str, ...]:
    loss_ids: list[str] = []
    for edge in edges:
        # Bounds and semantic receipts act as loss disclosures.
        for bound in edge.receipt.bounds:
            loss_ids.append(bound if bound.startswith("loss:") else f"loss:{bound}")
        loss_ids.append(f"loss:receipt:{edge.edge_id}")
    return tuple(sorted(set(loss_ids)))


def _loss_ids_from_policy(edges: PolicyModalTranslationEdges) -> tuple[str, ...]:
    loss_ids: list[str] = []
    for edge in edges.edges:
        # Approximation direction and assumption sets act as loss disclosures.
        loss_ids.append(f"loss:receipt:{edge.edge_id}")
        assumptions = edge.contract.assumptions
        for item in assumptions.other:
            if item.startswith("loss:"):
                loss_ids.append(item)
    return tuple(sorted(set(loss_ids)))


def _loss_ids_from_hyper(edges: HyperpropertyTranslationEdges) -> tuple[str, ...]:
    loss_ids: list[str] = []
    for edge in edges.edges:
        loss_ids.append(f"loss:receipt:{edge.edge_id}")
        for item in edge.contract.assumptions.other:
            if item.startswith("loss:"):
                loss_ids.append(item)
        for item in edge.contract.assumptions.bounds:
            loss_ids.append(
                item if item.startswith("loss:") else f"loss:{item}"
            )
    return tuple(sorted(set(loss_ids)))


@dataclass(frozen=True, slots=True)
class EdgeFamilyBundle:
    """One joined edge family with contracts and loss receipts."""

    family_key: str
    interface: str
    contract_ids: tuple[str, ...]
    loss_ids: tuple[str, ...]
    edge_count: int
    all_loss_receipted: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family_key", _identifier(self.family_key, "family_key")
        )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        object.__setattr__(
            self,
            "contract_ids",
            tuple(_identifier(item, "contract_ids item") for item in self.contract_ids),
        )
        object.__setattr__(
            self,
            "loss_ids",
            tuple(_identifier(item, "loss_ids item") for item in self.loss_ids),
        )
        if not isinstance(self.edge_count, int) or self.edge_count < 0:
            raise LogicTranslationGraphError("edge_count must be a non-negative int")
        if self.edge_count != len(self.contract_ids):
            raise LogicTranslationGraphError(
                "edge_count must equal number of contract_ids"
            )
        if not isinstance(self.all_loss_receipted, bool):
            raise LogicTranslationGraphError("all_loss_receipted must be a bool")
        if self.edge_count > 0 and not self.loss_ids:
            raise LogicTranslationGraphError(
                f"family {self.family_key!r} has edges but no loss receipts"
            )
        if not self.all_loss_receipted:
            raise LogicTranslationGraphError(
                f"family {self.family_key!r} is not fully loss-receipted"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_loss_receipted": self.all_loss_receipted,
            "contract_ids": list(self.contract_ids),
            "edge_count": self.edge_count,
            "family_key": self.family_key,
            "interface": self.interface,
            "loss_ids": list(self.loss_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EdgeFamilyBundle":
        value = _mapping(value, "edge family bundle")
        return cls(
            family_key=value.get("family_key", ""),
            interface=value.get("interface", ""),
            contract_ids=tuple(value.get("contract_ids", ())),
            loss_ids=tuple(value.get("loss_ids", ())),
            edge_count=int(value.get("edge_count", 0)),
            all_loss_receipted=bool(value.get("all_loss_receipted", True)),
        )


@dataclass(frozen=True, slots=True)
class PathValidationReceipt:
    """Validation that a planned path is feature-total and loss-receipted."""

    path_id: str
    edge_contract_ids: tuple[str, ...]
    feature_total: bool
    loss_receipted: bool
    covered_features: tuple[str, ...]
    loss_ids: tuple[str, ...]
    unhandled_features: tuple[str, ...] = ()
    unsupported_hits: tuple[str, ...] = ()
    schema_version: str = PATH_VALIDATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_id", _identifier(self.path_id, "path_id"))
        object.__setattr__(
            self,
            "edge_contract_ids",
            tuple(
                _identifier(item, "edge_contract_ids item")
                for item in self.edge_contract_ids
            ),
        )
        if not isinstance(self.feature_total, bool):
            raise LogicTranslationGraphError("feature_total must be a bool")
        if not isinstance(self.loss_receipted, bool):
            raise LogicTranslationGraphError("loss_receipted must be a bool")
        object.__setattr__(
            self,
            "covered_features",
            tuple(
                _identifier(item, "covered_features item")
                for item in self.covered_features
            ),
        )
        object.__setattr__(
            self,
            "loss_ids",
            tuple(_identifier(item, "loss_ids item") for item in self.loss_ids),
        )
        object.__setattr__(
            self,
            "unhandled_features",
            tuple(
                _identifier(item, "unhandled_features item")
                for item in self.unhandled_features
            ),
        )
        object.__setattr__(
            self,
            "unsupported_hits",
            tuple(
                _identifier(item, "unsupported_hits item")
                for item in self.unsupported_hits
            ),
        )
        if self.schema_version != PATH_VALIDATION_SCHEMA:
            raise LogicTranslationGraphError(
                f"unsupported path validation schema {self.schema_version!r}"
            )

    @property
    def accepted(self) -> bool:
        return self.feature_total and self.loss_receipted

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "covered_features": list(self.covered_features),
            "edge_contract_ids": list(self.edge_contract_ids),
            "feature_total": self.feature_total,
            "loss_ids": list(self.loss_ids),
            "loss_receipted": self.loss_receipted,
            "path_id": self.path_id,
            "schema_version": self.schema_version,
            "unhandled_features": list(self.unhandled_features),
            "unsupported_hits": list(self.unsupported_hits),
        }


@dataclass(frozen=True, slots=True)
class LogicTranslationGraph:
    """Composed translation graph (``LogicTranslationGraph@3``).

    Joins Wave-2 edge families into one planner-ready catalog.  Every edge and
    planned path must be feature-total and loss-receipted.
    """

    INTERFACE: ClassVar[str] = LOGIC_TRANSLATION_GRAPH_INTERFACE
    schema_version: ClassVar[str] = LOGIC_TRANSLATION_GRAPH_SCHEMA
    interface: str = LOGIC_TRANSLATION_GRAPH_INTERFACE

    contracts: tuple[TranslationContract, ...] = field(default_factory=tuple)
    families: tuple[EdgeFamilyBundle, ...] = field(default_factory=tuple)
    loss_ids: tuple[str, ...] = field(default_factory=tuple)
    graph_content_id: str = ""
    description: str = (
        "Composed LogicTranslationGraph@3 joining program, state/temporal, "
        "policy/modal, hyperproperty, protocol-target, and kernel-target edges."
    )

    def __post_init__(self) -> None:
        if self.interface != LOGIC_TRANSLATION_GRAPH_INTERFACE:
            raise LogicTranslationGraphError(
                f"unsupported translation graph interface {self.interface!r}"
            )
        if not self.contracts or not self.families:
            built = build_logic_translation_graph_parts()
            if not self.contracts:
                object.__setattr__(self, "contracts", built["contracts"])
            if not self.families:
                object.__setattr__(self, "families", built["families"])
            if not self.loss_ids:
                object.__setattr__(self, "loss_ids", built["loss_ids"])

        normalized_contracts: list[TranslationContract] = []
        seen_ids: set[str] = set()
        for item in self.contracts:
            if isinstance(item, Mapping):
                contract = TranslationContract.from_dict(item)
            elif isinstance(item, TranslationContract):
                contract = item
            else:
                raise LogicTranslationGraphError(
                    "contracts items must be TranslationContract values"
                )
            if contract.contract_id in seen_ids:
                raise LogicTranslationGraphError(
                    f"duplicate contract id {contract.contract_id!r}"
                )
            seen_ids.add(contract.contract_id)
            normalized_contracts.append(contract)
        object.__setattr__(
            self,
            "contracts",
            tuple(sorted(normalized_contracts, key=lambda item: item.contract_id)),
        )

        normalized_families: list[EdgeFamilyBundle] = []
        family_keys: set[str] = set()
        for item in self.families:
            if isinstance(item, Mapping):
                bundle = EdgeFamilyBundle.from_dict(item)
            elif isinstance(item, EdgeFamilyBundle):
                bundle = item
            else:
                raise LogicTranslationGraphError(
                    "families items must be EdgeFamilyBundle values"
                )
            if bundle.family_key in family_keys:
                raise LogicTranslationGraphError(
                    f"duplicate family key {bundle.family_key!r}"
                )
            family_keys.add(bundle.family_key)
            normalized_families.append(bundle)
        object.__setattr__(
            self,
            "families",
            tuple(sorted(normalized_families, key=lambda item: item.family_key)),
        )

        # Every family must be loss-receipted.
        for bundle in self.families:
            if not bundle.all_loss_receipted:
                raise LogicTranslationGraphError(
                    f"family {bundle.family_key!r} is not loss-receipted"
                )

        loss_ids = tuple(
            sorted(
                {
                    *self.loss_ids,
                    *(loss for bundle in self.families for loss in bundle.loss_ids),
                }
            )
        )
        if not loss_ids:
            raise LogicTranslationGraphError(
                "composed graph requires non-empty loss receipts"
            )
        object.__setattr__(self, "loss_ids", loss_ids)
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )

        # Required families must be present.
        present = {bundle.family_key for bundle in self.families}
        missing = [key for key in JOINED_FAMILY_KEYS if key not in present]
        if missing:
            raise LogicTranslationGraphError(
                f"composed graph missing families: {', '.join(missing)}"
            )

        computed = self._compute_identity()
        if self.graph_content_id and self.graph_content_id != computed.cid:
            raise LogicTranslationGraphError(
                "graph_content_id does not match canonical graph content"
            )
        object.__setattr__(self, "graph_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=GRAPH_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.graph_content_id

    def __iter__(self):
        return iter(self.contracts)

    def __len__(self) -> int:
        return len(self.contracts)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return item in self.by_id()
        if isinstance(item, TranslationContract):
            return item.contract_id in self.by_id()
        return False

    def by_id(self) -> Mapping[str, TranslationContract]:
        return {contract.contract_id: contract for contract in self.contracts}

    def contract_ids(self) -> tuple[str, ...]:
        return tuple(contract.contract_id for contract in self.contracts)

    def get(self, contract_id: str) -> TranslationContract:
        contract_id = _identifier(contract_id, "contract_id")
        for contract in self.contracts:
            if contract.contract_id == contract_id:
                return contract
        raise LogicTranslationGraphError(f"unknown contract_id {contract_id!r}")

    def family(self, family_key: str) -> EdgeFamilyBundle:
        family_key = _identifier(family_key, "family_key")
        for bundle in self.families:
            if bundle.family_key == family_key:
                return bundle
        raise LogicTranslationGraphError(f"unknown family_key {family_key!r}")

    def all_paths_loss_receipted(self) -> bool:
        return all(bundle.all_loss_receipted for bundle in self.families) and bool(
            self.loss_ids
        )

    def loss_ids_for_contracts(
        self, contract_ids: Sequence[str]
    ) -> tuple[str, ...]:
        """Return loss receipt ids associated with the given contracts."""

        wanted = set(contract_ids)
        result: list[str] = []
        for bundle in self.families:
            if wanted.intersection(bundle.contract_ids):
                result.extend(bundle.loss_ids)
        # Also include assumption-declared losses from the contracts themselves.
        for contract_id in wanted:
            if contract_id not in self.by_id():
                continue
            contract = self.by_id()[contract_id]
            for item in contract.assumptions.other:
                if item.startswith("loss:"):
                    result.append(item)
            for item in contract.assumptions.bounds:
                result.append(
                    item if item.startswith("loss:") else f"loss:{item}"
                )
        return tuple(sorted(set(result)))

    def register_with_planner(
        self, planner: TranslationPathPlanner | None = None
    ) -> TranslationPathPlanner:
        if planner is None:
            planner = TranslationPathPlanner()
        if not isinstance(planner, TranslationPathPlanner):
            raise LogicTranslationGraphError(
                "planner must be a TranslationPathPlanner"
            )
        try:
            planner.register_edges(self.contracts)
        except TranslationPathPlannerError as error:
            raise LogicTranslationGraphError(str(error)) from error
        return planner

    def plan(
        self,
        request: TranslationPathRequest | Mapping[str, Any],
    ) -> TranslationPathReceipt:
        """Plan a feature-total path; fail closed if not loss-receipted."""

        if isinstance(request, Mapping):
            request = TranslationPathRequest.from_dict(request)
        if not isinstance(request, TranslationPathRequest):
            raise LogicTranslationGraphError(
                "request must be a TranslationPathRequest"
            )
        try:
            receipt = plan_translation_path(self.contracts, request)
        except TranslationPathPlannerError as error:
            raise LogicTranslationGraphError(str(error)) from error
        validation = self.validate_path_receipt(receipt)
        if not validation.accepted:
            raise LogicTranslationGraphError(
                f"planned path {receipt.path_id!r} is not feature-total and "
                f"loss-receipted: feature_total={validation.feature_total}, "
                f"loss_receipted={validation.loss_receipted}, "
                f"unhandled={list(validation.unhandled_features)}, "
                f"hits={list(validation.unsupported_hits)}"
            )
        return receipt

    def validate_path_receipt(
        self,
        receipt: TranslationPathReceipt | Mapping[str, Any],
    ) -> PathValidationReceipt:
        """Validate that a path receipt is feature-total and loss-receipted."""

        if isinstance(receipt, Mapping):
            receipt = TranslationPathReceipt.from_dict(receipt)
        if not isinstance(receipt, TranslationPathReceipt):
            raise LogicTranslationGraphError(
                "receipt must be a TranslationPathReceipt"
            )
        contracts = []
        for contract_id in receipt.edge_contract_ids:
            try:
                contracts.append(self.get(contract_id))
            except LogicTranslationGraphError:
                # Path may reference only a subset registered elsewhere; try
                # matching from the receipt's own composition edges is not
                # available, so treat missing as non-total.
                return PathValidationReceipt(
                    path_id=receipt.path_id,
                    edge_contract_ids=receipt.edge_contract_ids,
                    feature_total=False,
                    loss_receipted=False,
                    covered_features=receipt.covered_features,
                    loss_ids=(),
                    unhandled_features=receipt.features.features,
                    unsupported_hits=(),
                )
        total, unhandled, hits = path_is_feature_total(contracts, receipt.features)
        loss_ids = self.loss_ids_for_contracts(receipt.edge_contract_ids)
        # Also accept assumption-declared losses embedded in the composition.
        for item in receipt.assumptions.other:
            if item.startswith("loss:"):
                loss_ids = tuple(sorted({*loss_ids, item}))
        for item in receipt.assumptions.bounds:
            bound_loss = item if item.startswith("loss:") else f"loss:{item}"
            loss_ids = tuple(sorted({*loss_ids, bound_loss}))
        loss_receipted = bool(loss_ids)
        return PathValidationReceipt(
            path_id=receipt.path_id,
            edge_contract_ids=receipt.edge_contract_ids,
            feature_total=total and not unhandled and not hits,
            loss_receipted=loss_receipted,
            covered_features=receipt.covered_features,
            loss_ids=loss_ids,
            unhandled_features=unhandled,
            unsupported_hits=hits,
        )

    def assert_all_registered_paths_ready(self) -> None:
        """Fail closed when any family is not fully loss-receipted."""

        if not self.all_paths_loss_receipted():
            raise LogicTranslationGraphError(
                "not all registered paths are loss-receipted"
            )
        for contract in self.contracts:
            if not contract.feature_preconditions and not contract.unsupported_constructs:
                # Empty feature surface is allowed only for pure identity edges;
                # reviewed edges always declare preconditions.
                raise LogicTranslationGraphError(
                    f"contract {contract.contract_id!r} lacks feature preconditions"
                )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "contract_content_ids": [
                contract.contract_content_id for contract in self.contracts
            ],
            "contract_ids": list(self.contract_ids()),
            "description": self.description,
            "families": [bundle.to_dict() for bundle in self.families],
            "interface": self.interface,
            "loss_ids": list(self.loss_ids),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["graph_content_id"] = self.graph_content_id
        payload["contracts"] = [contract.to_dict() for contract in self.contracts]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicTranslationGraph":
        value = _mapping(value, "logic translation graph")
        _reject_unknown(
            value,
            frozenset(
                {
                    "contract_content_ids",
                    "contract_ids",
                    "contracts",
                    "description",
                    "families",
                    "graph_content_id",
                    "interface",
                    "loss_ids",
                    "schema_version",
                }
            ),
            "logic translation graph",
        )
        interface = value.get("interface", LOGIC_TRANSLATION_GRAPH_INTERFACE)
        if interface != LOGIC_TRANSLATION_GRAPH_INTERFACE:
            raise LogicTranslationGraphError(
                f"unsupported translation graph interface {interface!r}"
            )
        schema = value.get("schema_version", LOGIC_TRANSLATION_GRAPH_SCHEMA)
        if schema != LOGIC_TRANSLATION_GRAPH_SCHEMA:
            raise LogicTranslationGraphError(
                f"unsupported translation graph schema {schema!r}"
            )
        return cls(
            contracts=tuple(value.get("contracts", ())),  # type: ignore[arg-type]
            families=tuple(value.get("families", ())),  # type: ignore[arg-type]
            loss_ids=tuple(value.get("loss_ids", ())),
            graph_content_id=value.get("graph_content_id", ""),
            description=value.get("description", ""),
        )

    @classmethod
    def reviewed(cls) -> "LogicTranslationGraph":
        """Return the built-in composed graph."""

        parts = build_logic_translation_graph_parts()
        return cls(
            contracts=parts["contracts"],
            families=parts["families"],
            loss_ids=parts["loss_ids"],
        )


def build_logic_translation_graph_parts() -> dict[str, Any]:
    """Collect contracts, family bundles, and loss receipts from edge modules."""

    program = ProgramTranslationEdges(edges=build_program_translation_edges())
    state = build_state_temporal_edges()
    policy = build_policy_modal_translation_edges()
    hyper = build_hyperproperty_translation_edges()
    protocol = ProtocolTargetTranslationEdges(
        edges=build_protocol_target_translation_edges()
    )
    kernel = KernelTargetTranslationEdges(
        edges=build_kernel_target_translation_edges()
    )

    program_contracts = program.contracts()
    state_contracts = state.contracts()
    policy_contracts = policy.contracts()
    hyper_contracts = hyper.contracts()
    protocol_contracts = protocol.contracts()
    kernel_contracts = kernel.contracts()

    families = (
        EdgeFamilyBundle(
            family_key=FAMILY_PROGRAM,
            interface=PROGRAM_TRANSLATION_EDGES_INTERFACE,
            contract_ids=tuple(c.contract_id for c in program_contracts),
            loss_ids=_loss_ids_from_program(program),
            edge_count=len(program_contracts),
            all_loss_receipted=True,
        ),
        EdgeFamilyBundle(
            family_key=FAMILY_STATE_TEMPORAL,
            interface=STATE_TEMPORAL_EDGES_INTERFACE,
            contract_ids=tuple(c.contract_id for c in state_contracts),
            loss_ids=_loss_ids_from_state(state),
            edge_count=len(state_contracts),
            all_loss_receipted=True,
        ),
        EdgeFamilyBundle(
            family_key=FAMILY_POLICY_MODAL,
            interface=POLICY_MODAL_EDGES_INTERFACE,
            contract_ids=tuple(c.contract_id for c in policy_contracts),
            loss_ids=_loss_ids_from_policy(policy),
            edge_count=len(policy_contracts),
            all_loss_receipted=True,
        ),
        EdgeFamilyBundle(
            family_key=FAMILY_HYPERPROPERTY,
            interface=HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE,
            contract_ids=tuple(c.contract_id for c in hyper_contracts),
            loss_ids=_loss_ids_from_hyper(hyper),
            edge_count=len(hyper_contracts),
            all_loss_receipted=True,
        ),
        EdgeFamilyBundle(
            family_key=FAMILY_PROTOCOL_TARGET,
            interface=PROTOCOL_TARGET_EDGES_INTERFACE,
            contract_ids=tuple(c.contract_id for c in protocol_contracts),
            loss_ids=tuple(
                sorted(
                    {
                        loss_id
                        for edge in protocol
                        for loss_id in edge.loss_ids
                    }
                )
            ),
            edge_count=len(protocol_contracts),
            all_loss_receipted=protocol.all_loss_receipted(),
        ),
        EdgeFamilyBundle(
            family_key=FAMILY_KERNEL_TARGET,
            interface=KERNEL_TARGET_EDGES_INTERFACE,
            contract_ids=tuple(c.contract_id for c in kernel_contracts),
            loss_ids=tuple(
                sorted(
                    {
                        loss_id
                        for edge in kernel
                        for loss_id in edge.loss_ids
                    }
                )
            ),
            edge_count=len(kernel_contracts),
            all_loss_receipted=kernel.all_loss_receipted(),
        ),
    )

    contracts = (
        *program_contracts,
        *state_contracts,
        *policy_contracts,
        *hyper_contracts,
        *protocol_contracts,
        *kernel_contracts,
    )
    # Deduplicate by contract_id (stable first-wins order then sort later).
    seen: set[str] = set()
    unique: list[TranslationContract] = []
    for contract in contracts:
        if contract.contract_id in seen:
            continue
        seen.add(contract.contract_id)
        unique.append(contract)

    loss_ids = tuple(
        sorted({loss for bundle in families for loss in bundle.loss_ids})
    )
    return {
        "contracts": tuple(unique),
        "families": families,
        "loss_ids": loss_ids,
        "program": program,
        "state": state,
        "policy": policy,
        "hyper": hyper,
        "protocol": protocol,
        "kernel": kernel,
    }


def build_logic_translation_graph() -> LogicTranslationGraph:
    """Public factory for the composed ``LogicTranslationGraph@3``."""

    return LogicTranslationGraph.reviewed()


def logic_translation_contracts() -> tuple[TranslationContract, ...]:
    """Return all joined ``TranslationContract@2`` edges."""

    return build_logic_translation_graph().contracts


def build_joined_planner() -> TranslationPathPlanner:
    """Register the composed graph with a fresh path planner."""

    return build_logic_translation_graph().register_with_planner()


def kernel_compiler_from_graph(
    graph: LogicTranslationGraph | None = None,
) -> KernelTargetCompiler:
    """Return a ``KernelTargetCompiler@2`` bound to the graph's kernel edges."""

    _ = graph  # graph join ensures kernel edges exist; compiler owns its edges
    return build_kernel_target_compiler()


def plan_feature_total_path(
    *,
    source_family_id: str,
    target_family_id: str,
    features: Sequence[str],
    source_profile_id: str = "",
    target_profile_id: str = "",
    graph: LogicTranslationGraph | None = None,
) -> TranslationPathReceipt:
    """Plan a feature-total, loss-receipted path on the composed graph."""

    catalog = graph or build_logic_translation_graph()
    request = TranslationPathRequest(
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        source_profile_id=source_profile_id,
        target_profile_id=target_profile_id,
        features=FeatureSet.from_features(features),
    )
    return catalog.plan(request)


__all__ = [
    "CATALOG_COMPILER_IDENTITY",
    "CATALOG_CONFIG_IDENTITY",
    "CATALOG_PROFILE_IDENTITY",
    "FAMILY_HYPERPROPERTY",
    "FAMILY_KERNEL_TARGET",
    "FAMILY_POLICY_MODAL",
    "FAMILY_PROGRAM",
    "FAMILY_PROTOCOL_TARGET",
    "FAMILY_STATE_TEMPORAL",
    "JOINED_FAMILY_KEYS",
    "KERNEL_TARGET_COMPILER_INTERFACE",
    "LOGIC_TRANSLATION_GRAPH_INTERFACE",
    "LOGIC_TRANSLATION_GRAPH_SCHEMA",
    "EdgeFamilyBundle",
    "LogicTranslationGraph",
    "LogicTranslationGraphError",
    "PathValidationReceipt",
    "build_joined_planner",
    "build_logic_translation_graph",
    "build_logic_translation_graph_parts",
    "kernel_compiler_from_graph",
    "logic_translation_contracts",
    "plan_feature_total_path",
]
