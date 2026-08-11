"""Program, VC, and separation translation edges (``ProgramTranslationEdges@1``).

Reviewed routes lower supported program contracts/commands, verification
conditions, frames, and separation/resource obligations into first-order
logic, Horn/CHC, and SMT encodings.

Every edge binds:

* feature preconditions and explicit unsupported constructs;
* preservation relation, proof/counterexample polarity, and authority ceiling;
* total node/symbol maps (silent drops are rejected);
* explicit heap/resource abstraction losses and validity direction; and
* checker/reconstruction routes for differential fixtures.

Heap and resource constructs never disappear: array encodings, permission
collapse, and frame approximations are recorded as
:class:`HeapResourceLoss` entries.  Unsupported spatial constructs (magic
wand, septraction) fail closed before any target obligation is emitted.
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
    OpaqueDisposition,
    PreservationRelation,
    SymbolMapEntry,
    TranslationAssumptionSet,
    TranslationContract,
    TranslationEndpoint,
    TranslationIdentities,
)
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.translations.planner import (
    FeatureSet,
    TranslationPathPlanner,
    TranslationPathPlannerError,
    TranslationPathReceipt,
    TranslationPathRequest,
    edge_feature_compatibility,
    plan_translation_path,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROGRAM_TRANSLATION_EDGES_INTERFACE: Final = "ProgramTranslationEdges@1"
PROGRAM_TRANSLATION_EDGES_SCHEMA: Final = "logic-program-translation-edges/v1"
PROGRAM_EDGE_SCHEMA: Final = "logic-program-translation-edge/v1"
HEAP_RESOURCE_LOSS_SCHEMA: Final = "logic-heap-resource-loss/v1"
LOWERING_RESULT_SCHEMA: Final = "logic-program-lowering-result/v1"
EDGE_IDENTITY_DOMAIN: Final = "logic.translation.program.edge"
EDGES_IDENTITY_DOMAIN: Final = "logic.translation.program.edges"
LOWERING_IDENTITY_DOMAIN: Final = "logic.translation.program.lowering"

COMPILER_IDENTITY: Final = "compiler:program-vc-separation@1"
PROFILE_IDENTITY: Final = "profile:program-vc-separation-default@1"
CONFIG_IDENTITY: Final = "config:program-translation-edges@1"

# Canonical feature identifiers present in program/VC/separation obligations.
FEAT_PROGRAM_CONTRACTS: Final = "feat_program_contracts"
FEAT_PROGRAM_COMMANDS: Final = "feat_program_commands"
FEAT_VERIFICATION_CONDITIONS: Final = "feat_verification_conditions"
FEAT_FRAME_CONDITIONS: Final = "feat_frame_conditions"
FEAT_HEAP_RESOURCE: Final = "feat_heap_resource"
FEAT_SEPARATION_SPATIAL: Final = "feat_separation_spatial"
FEAT_PURE_ASSERTIONS: Final = "feat_pure_assertions"
FEAT_ARITHMETIC: Final = "feat_arithmetic"
FEAT_EQUALITY: Final = "feat_equality"
FEAT_QUANTIFIERS: Final = "feat_quantifiers"
FEAT_SEPARATION_WAND: Final = "feat_separation_wand"
FEAT_SEPTRACTION: Final = "feat_septraction"
FEAT_UNBOUNDED_HEAP: Final = "feat_unbounded_heap"

# Target family / encoding ids used as planner endpoints.
TARGET_FOL: Final = "first_order"
TARGET_CHC: Final = "horn_chc"
TARGET_SMT: Final = "smt"

SOURCE_PROGRAM: Final = "program"
SOURCE_SEPARATION: Final = "separation_logic"

VIEW_SOURCE: Final = "source"
VIEW_VC: Final = "verification_condition"
VIEW_SEPARATION: Final = "separation"

# Constructs that never lower silently.
UNSUPPORTED_SPATIAL: Final = frozenset(
    {
        FEAT_SEPARATION_WAND,
        FEAT_SEPTRACTION,
        FEAT_UNBOUNDED_HEAP,
        "construct:magic_wand",
        "construct:septraction",
        "construct:unbounded_heap",
    }
)


class ProgramTranslationError(ValueError):
    """Raised when a program/VC/separation route is invalid or unsupported."""


class ValidityDirection(str, Enum):
    """How a translation relates source and target *validity*.

    * ``PRESERVES_VALIDITY`` — if the target obligation is valid, the source
      obligation is valid (theorem-preserving / sound for proof).
    * ``EQUISATISFIABLE`` — validity and satisfiability are equivalent under
      the declared assumptions.
    * ``OVER_APPROXIMATES_VALIDITY`` — a valid target may be stronger than the
      source (false positives for proof / false negatives for bugs).
    * ``UNDER_APPROXIMATES_VALIDITY`` — a valid target may be weaker (bugs may
      be missed when using the target as a safety proof).
    """

    PRESERVES_VALIDITY = "preserves_validity"
    EQUISATISFIABLE = "equisatisfiable"
    OVER_APPROXIMATES_VALIDITY = "over_approximates_validity"
    UNDER_APPROXIMATES_VALIDITY = "under_approximates_validity"


class HeapResourceLossKind(str, Enum):
    """Closed vocabulary of heap/resource abstractions that lose precision."""

    NONE = "none"
    HEAP_AS_ARRAY = "heap_as_array"
    FRACTIONAL_PERMISSION_COLLAPSE = "fractional_permission_collapse"
    SPATIAL_TO_PURE = "spatial_to_pure"
    SEP_CONJ_TO_AND = "sep_conj_to_and"
    FRAME_APPROXIMATION = "frame_approximation"
    RESOURCE_ALGEBRA_DROP = "resource_algebra_drop"
    POINTS_TO_SELECT = "points_to_select"
    OWNERSHIP_ELISION = "ownership_elision"


class LoweringStatus(str, Enum):
    """Outcome of applying a reviewed edge to one obligation."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ObligationKind(str, Enum):
    """Source obligation class accepted by the program translation edges."""

    PROGRAM_CONTRACT = "program_contract"
    PROGRAM_COMMAND = "program_command"
    VERIFICATION_CONDITION = "verification_condition"
    FRAME = "frame"
    SEPARATION = "separation"
    HEAP_FRAGMENT = "heap_fragment"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProgramTranslationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise ProgramTranslationError(f"{field_name} must not contain NUL bytes")
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
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ProgramTranslationError(f"{field_name} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _identifier(item, f"{field_name} item")
        if text in seen:
            raise ProgramTranslationError(f"{field_name} must not contain duplicates")
        seen.add(text)
        result.append(text)
    return tuple(result)


def _enum(value: object, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ProgramTranslationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramTranslationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProgramTranslationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProgramTranslationError(f"{field_name} must be a bool")
    return value


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


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
    family: str,
    *,
    profile_id: str = "",
    fragment_id: str = "",
    schema_id: str = "",
    notation_id: str = "",
    content_identity: str = "",
) -> TranslationEndpoint:
    profile = profile_id or f"{family}_default"
    fragment = fragment_id or f"{family}_core"
    schema = schema_id or f"{family}_schema"
    notation = notation_id or f"{family}_notation"
    content = content_identity or f"sha256:endpoint:{family}:{profile}:{fragment}"
    return TranslationEndpoint(
        family_id=family,
        profile_id=profile,
        fragment_id=fragment,
        schema_id=schema,
        notation_id=notation,
        content_identity=content,
    )


def _identities(
    *,
    compiler_identity: str = COMPILER_IDENTITY,
    profile_identity: str = PROFILE_IDENTITY,
    config_identity: str = CONFIG_IDENTITY,
    source_identity: str = "",
    target_identity: str = "",
) -> TranslationIdentities:
    return TranslationIdentities(
        compiler_identity=compiler_identity,
        profile_identity=profile_identity,
        config_identity=config_identity,
        source_identity=source_identity
        or "bafkreiprogramsrcaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        target_identity=target_identity
        or "bafkreiprogramtgtaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        environment_identity="sha256:env:program-translation@1",
    )


def validity_direction_for(
    preservation: PreservationRelation | str,
) -> ValidityDirection:
    """Map a preservation relation onto a closed validity direction."""

    relation = _enum(preservation, PreservationRelation, "preservation")
    if relation is PreservationRelation.EXACT_EQUIVALENCE:
        return ValidityDirection.EQUISATISFIABLE
    if relation is PreservationRelation.EQUISATISFIABLE:
        return ValidityDirection.EQUISATISFIABLE
    if relation is PreservationRelation.THEOREM_PRESERVING:
        return ValidityDirection.PRESERVES_VALIDITY
    if relation is PreservationRelation.MODEL_PRESERVING:
        return ValidityDirection.EQUISATISFIABLE
    if relation is PreservationRelation.TRACE_PRESERVING:
        return ValidityDirection.EQUISATISFIABLE
    if relation is PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION:
        return ValidityDirection.OVER_APPROXIMATES_VALIDITY
    if relation is PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION:
        return ValidityDirection.UNDER_APPROXIMATES_VALIDITY
    if relation is PreservationRelation.BOUNDED:
        return ValidityDirection.OVER_APPROXIMATES_VALIDITY
    if relation is PreservationRelation.APPROXIMATE:
        return ValidityDirection.OVER_APPROXIMATES_VALIDITY
    return ValidityDirection.UNDER_APPROXIMATES_VALIDITY


# ---------------------------------------------------------------------------
# Heap / resource loss records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeapResourceLoss:
    """One explicit heap or resource abstraction loss on a translation edge.

    Losses never upgrade validity direction: recording a loss can only weaken
    (or leave unchanged) the edge's claimed soundness.
    """

    loss_id: str
    kind: HeapResourceLossKind | str
    description: str
    source_construct_ids: tuple[str, ...] = ()
    target_construct_ids: tuple[str, ...] = ()
    validity_impact: ValidityDirection | str = (
        ValidityDirection.OVER_APPROXIMATES_VALIDITY
    )
    schema_version: str = HEAP_RESOURCE_LOSS_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "loss_id", _identifier(self.loss_id, "loss_id"))
        object.__setattr__(
            self, "kind", _enum(self.kind, HeapResourceLossKind, "kind")
        )
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        object.__setattr__(
            self,
            "source_construct_ids",
            _strings(self.source_construct_ids, "source_construct_ids"),
        )
        object.__setattr__(
            self,
            "target_construct_ids",
            _strings(self.target_construct_ids, "target_construct_ids"),
        )
        object.__setattr__(
            self,
            "validity_impact",
            _enum(self.validity_impact, ValidityDirection, "validity_impact"),
        )
        if self.schema_version != HEAP_RESOURCE_LOSS_SCHEMA:
            raise ProgramTranslationError(
                f"unsupported heap resource loss schema {self.schema_version!r}"
            )
        if self.kind is HeapResourceLossKind.NONE and (
            self.source_construct_ids or self.target_construct_ids
        ):
            raise ProgramTranslationError(
                "none loss cannot bind source or target construct ids"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "kind": self.kind.value,
            "loss_id": self.loss_id,
            "schema_version": self.schema_version,
            "source_construct_ids": list(self.source_construct_ids),
            "target_construct_ids": list(self.target_construct_ids),
            "validity_impact": self.validity_impact.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HeapResourceLoss":
        value = _mapping(value, "heap resource loss")
        _reject_unknown(
            value,
            frozenset(
                {
                    "description",
                    "kind",
                    "loss_id",
                    "schema_version",
                    "source_construct_ids",
                    "target_construct_ids",
                    "validity_impact",
                }
            ),
            "heap resource loss",
        )
        return cls(
            loss_id=value.get("loss_id", ""),
            kind=value.get("kind", ""),
            description=value.get("description", ""),
            source_construct_ids=tuple(value.get("source_construct_ids", ())),
            target_construct_ids=tuple(value.get("target_construct_ids", ())),
            validity_impact=value.get(
                "validity_impact",
                ValidityDirection.OVER_APPROXIMATES_VALIDITY.value,
            ),
            schema_version=value.get(
                "schema_version", HEAP_RESOURCE_LOSS_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Reviewed edge descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramTranslationEdge:
    """One reviewed program/VC/separation translation edge.

    Wraps a ``TranslationContract@2`` with program-specific validity direction
    and explicit heap/resource loss accounting.
    """

    edge_id: str
    contract: TranslationContract
    validity_direction: ValidityDirection | str
    view_role: str = VIEW_SOURCE
    heap_resource_losses: tuple[HeapResourceLoss, ...] = ()
    obligation_kinds: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = PROGRAM_EDGE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        if not isinstance(self.contract, TranslationContract):
            raise ProgramTranslationError(
                "contract must be a TranslationContract"
            )
        if self.edge_id != self.contract.contract_id:
            raise ProgramTranslationError(
                "edge_id must equal contract.contract_id"
            )
        object.__setattr__(
            self,
            "validity_direction",
            _enum(self.validity_direction, ValidityDirection, "validity_direction"),
        )
        object.__setattr__(
            self, "view_role", _identifier(self.view_role, "view_role")
        )
        if self.view_role not in {VIEW_SOURCE, VIEW_VC, VIEW_SEPARATION}:
            raise ProgramTranslationError(
                f"view_role must be one of "
                f"{VIEW_SOURCE!r}, {VIEW_VC!r}, {VIEW_SEPARATION!r}"
            )
        losses: list[HeapResourceLoss] = []
        for item in self.heap_resource_losses:
            if isinstance(item, HeapResourceLoss):
                losses.append(item)
            elif isinstance(item, Mapping):
                losses.append(HeapResourceLoss.from_dict(item))
            else:
                raise ProgramTranslationError(
                    "heap_resource_losses items must be HeapResourceLoss values"
                )
        # Stable order for content identity.
        losses_sorted = tuple(sorted(losses, key=lambda item: item.loss_id))
        object.__setattr__(self, "heap_resource_losses", losses_sorted)

        kinds = _strings(self.obligation_kinds, "obligation_kinds")
        for kind in kinds:
            _enum(kind, ObligationKind, "obligation_kinds item")
        object.__setattr__(self, "obligation_kinds", kinds)
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != PROGRAM_EDGE_SCHEMA:
            raise ProgramTranslationError(
                f"unsupported program edge schema {self.schema_version!r}"
            )

        expected = validity_direction_for(self.contract.preservation)
        # Edge validity direction may be weaker than the preservation-derived
        # default, but never stronger (no soundness upgrade via metadata).
        if _validity_rank(self.validity_direction) > _validity_rank(expected):
            raise ProgramTranslationError(
                f"validity_direction {self.validity_direction.value} is stronger "
                f"than preservation {self.contract.preservation.value} allows "
                f"({expected.value})"
            )
        self._validate_heap_losses()

    def _validate_heap_losses(self) -> None:
        non_none = [
            loss
            for loss in self.heap_resource_losses
            if loss.kind is not HeapResourceLossKind.NONE
        ]
        if non_none and self.contract.preservation is PreservationRelation.EXACT_EQUIVALENCE:
            raise ProgramTranslationError(
                "exact_equivalence cannot declare heap/resource losses"
            )
        # Any non-trivial heap loss forbids claiming pure equisatisfiable
        # validity without also approximating nodes.
        if non_none and self.validity_direction is ValidityDirection.EQUISATISFIABLE:
            if self.contract.preservation not in {
                PreservationRelation.EQUISATISFIABLE,
                PreservationRelation.MODEL_PRESERVING,
                PreservationRelation.TRACE_PRESERVING,
            }:
                raise ProgramTranslationError(
                    "heap/resource loss with equisatisfiable validity requires "
                    "an equisatisfiable-class preservation relation"
                )
        for loss in non_none:
            if _validity_rank(loss.validity_impact) > _validity_rank(
                self.validity_direction
            ):
                raise ProgramTranslationError(
                    f"loss {loss.loss_id!r} validity_impact "
                    f"{loss.validity_impact.value} is stronger than edge "
                    f"validity_direction {self.validity_direction.value}"
                )

    @property
    def source_family_id(self) -> str:
        return self.contract.source.family_id

    @property
    def target_family_id(self) -> str:
        return self.contract.target.family_id

    @property
    def preservation(self) -> PreservationRelation:
        return self.contract.preservation  # type: ignore[return-value]

    @property
    def authority_ceiling(self) -> EvidenceAuthority:
        return self.contract.authority_ceiling  # type: ignore[return-value]

    @property
    def feature_preconditions(self) -> tuple[str, ...]:
        return self.contract.feature_preconditions

    @property
    def unsupported_constructs(self) -> tuple[str, ...]:
        return self.contract.unsupported_constructs

    @property
    def has_heap_loss(self) -> bool:
        return any(
            loss.kind is not HeapResourceLossKind.NONE
            for loss in self.heap_resource_losses
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=EDGE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def content_id(self) -> str:
        return self.identity.cid

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "contract_content_id": self.contract.contract_content_id,
            "contract_id": self.contract.contract_id,
            "description": self.description,
            "edge_id": self.edge_id,
            "heap_resource_losses": [
                loss.to_dict() for loss in self.heap_resource_losses
            ],
            "obligation_kinds": list(self.obligation_kinds),
            "schema_version": self.schema_version,
            "validity_direction": self.validity_direction.value,
            "view_role": self.view_role,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract"] = self.contract.to_dict()
        payload["content_id"] = self.content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTranslationEdge":
        value = _mapping(value, "program translation edge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "content_id",
                    "contract",
                    "contract_content_id",
                    "contract_id",
                    "description",
                    "edge_id",
                    "heap_resource_losses",
                    "obligation_kinds",
                    "schema_version",
                    "validity_direction",
                    "view_role",
                }
            ),
            "program translation edge",
        )
        contract_value = value.get("contract")
        if not isinstance(contract_value, Mapping):
            raise ProgramTranslationError("contract must be a mapping")
        return cls(
            edge_id=value.get("edge_id", ""),
            contract=TranslationContract.from_dict(contract_value),
            validity_direction=value.get("validity_direction", ""),
            view_role=value.get("view_role", VIEW_SOURCE),
            heap_resource_losses=tuple(value.get("heap_resource_losses", ())),
            obligation_kinds=tuple(value.get("obligation_kinds", ())),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", PROGRAM_EDGE_SCHEMA),
        )


_VALIDITY_RANK: Final[dict[ValidityDirection, int]] = {
    ValidityDirection.EQUISATISFIABLE: 3,
    ValidityDirection.PRESERVES_VALIDITY: 2,
    ValidityDirection.OVER_APPROXIMATES_VALIDITY: 1,
    ValidityDirection.UNDER_APPROXIMATES_VALIDITY: 0,
}


def _validity_rank(direction: ValidityDirection | str) -> int:
    selected = _enum(direction, ValidityDirection, "validity_direction")
    return _VALIDITY_RANK[selected]


def weaker_validity_direction(
    left: ValidityDirection | str,
    right: ValidityDirection | str,
) -> ValidityDirection:
    """Return the weaker of two validity directions (weakest-link)."""

    a = _enum(left, ValidityDirection, "left")
    b = _enum(right, ValidityDirection, "right")
    return a if _VALIDITY_RANK[a] <= _VALIDITY_RANK[b] else b


# ---------------------------------------------------------------------------
# Edge construction helpers
# ---------------------------------------------------------------------------


def _contract(
    contract_id: str,
    *,
    source: TranslationEndpoint,
    target: TranslationEndpoint,
    preservation: PreservationRelation,
    authority_ceiling: EvidenceAuthority,
    proof_safe: bool,
    counterexample_safe: bool,
    node_map: Sequence[NodeMapEntry],
    symbol_map: Sequence[SymbolMapEntry],
    required_source_node_ids: Sequence[str],
    required_source_symbol_ids: Sequence[str],
    feature_preconditions: Sequence[str],
    unsupported_constructs: Sequence[str] = (),
    assumptions: TranslationAssumptionSet | None = None,
    checker_route: str = "",
    reconstruction_route: str = "",
    description: str = "",
    identities: TranslationIdentities | None = None,
) -> TranslationContract:
    return TranslationContract(
        contract_id=contract_id,
        source=source,
        target=target,
        preservation=preservation,
        identities=identities or _identities(),
        proof_safe=proof_safe,
        counterexample_safe=counterexample_safe,
        authority_ceiling=authority_ceiling,
        assumptions=assumptions or TranslationAssumptionSet(),
        node_map=tuple(node_map),
        symbol_map=tuple(symbol_map),
        required_source_node_ids=tuple(required_source_node_ids),
        required_source_symbol_ids=tuple(required_source_symbol_ids),
        feature_preconditions=tuple(feature_preconditions),
        unsupported_constructs=tuple(unsupported_constructs),
        opaque_disposition=OpaqueDisposition.UNSUPPORTED,
        checker_route=checker_route,
        reconstruction_route=reconstruction_route,
        description=description,
    )


def _program_source(*, fragment: str, profile: str) -> TranslationEndpoint:
    return _endpoint(
        SOURCE_PROGRAM,
        profile_id=profile,
        fragment_id=fragment,
        schema_id="program_ir_schema",
        notation_id="program_logic_surface",
        content_identity=f"sha256:program:{profile}:{fragment}",
    )


def _separation_source(*, profile: str = "separation_classical") -> TranslationEndpoint:
    return _endpoint(
        SOURCE_SEPARATION,
        profile_id=profile,
        fragment_id="separation_core",
        schema_id="separation_logic_ir_schema",
        notation_id="separation_surface",
        content_identity=f"sha256:separation:{profile}",
    )


def _fol_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_FOL,
        profile_id="first_order_default",
        fragment_id="first_order_core",
        schema_id="fol_schema",
        notation_id="canonical_text",
        content_identity="sha256:target:first_order",
    )


def _chc_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_CHC,
        profile_id="horn_chc_default",
        fragment_id="horn_clauses",
        schema_id="horn_chc_schema",
        notation_id="smt_lib2",
        content_identity="sha256:target:horn_chc",
    )


def _smt_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_SMT,
        profile_id="smt_lib2_default",
        fragment_id="smt_core",
        schema_id="smt_lib2_schema",
        notation_id="smt_lib2",
        content_identity="sha256:target:smt",
    )


def _pure_program_nodes() -> tuple[NodeMapEntry, ...]:
    return (
        _node("n_precondition", "t_assume", disposition=NodeDisposition.MAPPED),
        _node("n_postcondition", "t_assert", disposition=NodeDisposition.MAPPED),
        _node("n_assign", "t_equality", disposition=NodeDisposition.MAPPED),
        _node("n_assume", "t_assume", disposition=NodeDisposition.PRESERVED),
        _node("n_assert", "t_assert", disposition=NodeDisposition.PRESERVED),
        _node("n_frame", "t_frame_axioms", disposition=NodeDisposition.MAPPED),
        _node(
            "n_call",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="unmodeled calls require explicit summaries",
        ),
        _node(
            "n_havoc",
            "t_fresh",
            disposition=NodeDisposition.APPROXIMATED,
            reason="havoc becomes unconstrained fresh symbols",
        ),
    )


def _pure_program_symbols() -> tuple[SymbolMapEntry, ...]:
    return (
        _symbol("sym_state", "sym_state", disposition=NodeDisposition.PRESERVED),
        _symbol("sym_result", "sym_result", disposition=NodeDisposition.MAPPED),
        _symbol("sym_heap", "sym_heap", disposition=NodeDisposition.MAPPED),
    )


def _vc_nodes() -> tuple[NodeMapEntry, ...]:
    return (
        _node("n_vc_goal", "t_goal", disposition=NodeDisposition.PRESERVED),
        _node("n_path_condition", "t_assume", disposition=NodeDisposition.MAPPED),
        _node("n_wp_assign", "t_subst", disposition=NodeDisposition.MAPPED),
        _node("n_wp_assert", "t_assert", disposition=NodeDisposition.PRESERVED),
        _node("n_frame", "t_frame_axioms", disposition=NodeDisposition.MAPPED),
        _node(
            "n_unsupported_effect",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="I/O, sync, and unframed writes fail closed",
        ),
    )


def _vc_symbols() -> tuple[SymbolMapEntry, ...]:
    return (
        _symbol("sym_path", "sym_path", disposition=NodeDisposition.PRESERVED),
        _symbol("sym_goal", "sym_goal", disposition=NodeDisposition.PRESERVED),
        _symbol("sym_generated", "sym_fresh", disposition=NodeDisposition.MAPPED),
    )


def _separation_nodes(*, heap_target: str) -> tuple[NodeMapEntry, ...]:
    return (
        _node("n_pure", "t_pure", disposition=NodeDisposition.PRESERVED),
        _node(
            "n_points_to",
            heap_target,
            disposition=NodeDisposition.APPROXIMATED,
            reason="points-to cells encode as select/store equalities",
        ),
        _node(
            "n_emp",
            "t_true",
            disposition=NodeDisposition.APPROXIMATED,
            reason="emp becomes a pure unit under the heap array encoding",
        ),
        _node(
            "n_sep_conj",
            "t_and",
            disposition=NodeDisposition.APPROXIMATED,
            reason="separating conjunction becomes conjunction plus disjointness",
        ),
        _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
        _node("n_or", "t_or", disposition=NodeDisposition.PRESERVED),
        _node("n_not", "t_not", disposition=NodeDisposition.PRESERVED),
        _node("n_implies", "t_implies", disposition=NodeDisposition.PRESERVED),
        _node("n_forall", "t_forall", disposition=NodeDisposition.MAPPED),
        _node("n_exists", "t_exists", disposition=NodeDisposition.MAPPED),
        _node("n_frame", "t_frame_axioms", disposition=NodeDisposition.MAPPED),
        _node(
            "n_wand",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="magic wand has no silent FOL/SMT encoding",
        ),
        _node(
            "n_septraction",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="septraction has no silent FOL/SMT encoding",
        ),
    )


def _separation_symbols() -> tuple[SymbolMapEntry, ...]:
    return (
        _symbol("sym_loc", "sym_loc", disposition=NodeDisposition.PRESERVED),
        _symbol("sym_val", "sym_val", disposition=NodeDisposition.PRESERVED),
        _symbol(
            "sym_heap",
            "sym_heap_array",
            disposition=NodeDisposition.APPROXIMATED,
            reason="heap model becomes an Array sort",
        ),
        _symbol(
            "sym_permission",
            "sym_permission_real",
            disposition=NodeDisposition.APPROXIMATED,
            reason="fractional permissions collapse to reals in [0,1]",
        ),
    )


def _heap_losses_for_array_encoding() -> tuple[HeapResourceLoss, ...]:
    return (
        HeapResourceLoss(
            loss_id="loss:heap-as-array",
            kind=HeapResourceLossKind.HEAP_AS_ARRAY,
            description=(
                "Supported points-to cells are encoded as Array select equalities; "
                "heap structure beyond the finite cell set is not preserved."
            ),
            source_construct_ids=("n_points_to", "sym_heap"),
            target_construct_ids=("t_select", "sym_heap_array"),
            validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        ),
        HeapResourceLoss(
            loss_id="loss:sep-conj-to-and",
            kind=HeapResourceLossKind.SEP_CONJ_TO_AND,
            description=(
                "Separating conjunction is replaced by classical conjunction plus "
                "explicit disjointness axioms; residual heap framing is approximate."
            ),
            source_construct_ids=("n_sep_conj",),
            target_construct_ids=("t_and",),
            validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        ),
        HeapResourceLoss(
            loss_id="loss:points-to-select",
            kind=HeapResourceLossKind.POINTS_TO_SELECT,
            description=(
                "Each points-to atom becomes a select equality; ownership and "
                "permission conservation are not fully reconstructed."
            ),
            source_construct_ids=("n_points_to",),
            target_construct_ids=("t_select",),
            validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        ),
        HeapResourceLoss(
            loss_id="loss:fractional-permission-collapse",
            kind=HeapResourceLossKind.FRACTIONAL_PERMISSION_COLLAPSE,
            description=(
                "Fractional permissions lower to real-valued constraints in [0,1]; "
                "resource-algebra identities may be incomplete."
            ),
            source_construct_ids=("sym_permission",),
            target_construct_ids=("sym_permission_real",),
            validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        ),
        HeapResourceLoss(
            loss_id="loss:frame-approximation",
            kind=HeapResourceLossKind.FRAME_APPROXIMATION,
            description=(
                "Frame obligations become explicit pure axioms; unframed residual "
                "heap context is not silently dropped but is approximated."
            ),
            source_construct_ids=("n_frame",),
            target_construct_ids=("t_frame_axioms",),
            validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        ),
    )


def _build_program_to_fol() -> ProgramTranslationEdge:
    contract = _contract(
        "program_to_first_order",
        source=_program_source(
            fragment="program_contracts", profile="program_contracts"
        ),
        target=_fol_target(),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=_pure_program_nodes(),
        symbol_map=_pure_program_symbols(),
        required_source_node_ids=(
            "n_precondition",
            "n_postcondition",
            "n_assign",
            "n_assume",
            "n_assert",
            "n_frame",
            "n_call",
            "n_havoc",
        ),
        required_source_symbol_ids=("sym_state", "sym_result", "sym_heap"),
        feature_preconditions=(
            FEAT_PROGRAM_CONTRACTS,
            FEAT_PROGRAM_COMMANDS,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            FEAT_UNBOUNDED_HEAP,
            "construct:unmodeled_call",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:frame_stability",),
            domain_changes=("domain:program_state_to_fol_terms",),
        ),
        checker_route="differential:program-fol",
        reconstruction_route="replay:fol-program",
        description=(
            "Supported pure program contracts and commands lower to FOL with "
            "theorem-preserving validity direction."
        ),
        identities=_identities(config_identity="config:program-to-fol@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.PRESERVES_VALIDITY,
        view_role=VIEW_SOURCE,
        heap_resource_losses=(),
        obligation_kinds=(
            ObligationKind.PROGRAM_CONTRACT.value,
            ObligationKind.PROGRAM_COMMAND.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def _build_program_to_chc() -> ProgramTranslationEdge:
    contract = _contract(
        "program_to_horn_chc",
        source=_program_source(
            fragment="program_transitions", profile="program_chc"
        ),
        target=_chc_target(),
        preservation=PreservationRelation.MODEL_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=(
            _node("n_init", "t_init_clause", disposition=NodeDisposition.MAPPED),
            _node(
                "n_transition",
                "t_horn_clause",
                disposition=NodeDisposition.MAPPED,
            ),
            _node("n_bad", "t_query", disposition=NodeDisposition.MAPPED),
            _node("n_assert", "t_query", disposition=NodeDisposition.MAPPED),
            _node("n_frame", "t_frame_clause", disposition=NodeDisposition.MAPPED),
            _node(
                "n_call",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="recursive calls require explicit CHC summaries",
            ),
        ),
        symbol_map=(
            _symbol("sym_state", "rel_state", disposition=NodeDisposition.MAPPED),
            _symbol("sym_inv", "rel_inv", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_init",
            "n_transition",
            "n_bad",
            "n_assert",
            "n_frame",
            "n_call",
        ),
        required_source_symbol_ids=("sym_state", "sym_inv"),
        feature_preconditions=(
            FEAT_PROGRAM_COMMANDS,
            FEAT_PROGRAM_CONTRACTS,
            FEAT_PURE_ASSERTIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
            FEAT_FRAME_CONDITIONS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            "construct:unmodeled_call",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:transition_closed",),
            domain_changes=("domain:cfg_to_horn_relations",),
        ),
        checker_route="differential:program-chc",
        reconstruction_route="replay:chc-program",
        description=(
            "Supported program transition systems lower to Horn/CHC clauses "
            "with model-preserving reachability."
        ),
        identities=_identities(config_identity="config:program-to-chc@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.EQUISATISFIABLE,
        view_role=VIEW_SOURCE,
        heap_resource_losses=(),
        obligation_kinds=(
            ObligationKind.PROGRAM_CONTRACT.value,
            ObligationKind.PROGRAM_COMMAND.value,
        ),
        description=contract.description,
    )


def _build_program_to_smt() -> ProgramTranslationEdge:
    contract = _contract(
        "program_to_smt",
        source=_program_source(fragment="program_smt", profile="program_smt"),
        target=_smt_target(),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=_pure_program_nodes(),
        symbol_map=_pure_program_symbols(),
        required_source_node_ids=(
            "n_precondition",
            "n_postcondition",
            "n_assign",
            "n_assume",
            "n_assert",
            "n_frame",
            "n_call",
            "n_havoc",
        ),
        required_source_symbol_ids=("sym_state", "sym_result", "sym_heap"),
        feature_preconditions=(
            FEAT_PROGRAM_CONTRACTS,
            FEAT_PROGRAM_COMMANDS,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            FEAT_UNBOUNDED_HEAP,
            "construct:unmodeled_call",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:frame_stability",),
            domain_changes=("domain:program_state_to_smt_terms",),
        ),
        checker_route="differential:program-smt",
        reconstruction_route="replay:smt-program",
        description=(
            "Supported pure program contracts lower to SMT-LIB theorem queries "
            "preserving validity direction under frame axioms."
        ),
        identities=_identities(config_identity="config:program-to-smt@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.PRESERVES_VALIDITY,
        view_role=VIEW_SOURCE,
        heap_resource_losses=(),
        obligation_kinds=(
            ObligationKind.PROGRAM_CONTRACT.value,
            ObligationKind.PROGRAM_COMMAND.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def _build_vc_to_fol() -> ProgramTranslationEdge:
    contract = _contract(
        "vc_to_first_order",
        source=_program_source(fragment="verification_condition", profile="program_vc"),
        target=_fol_target(),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=_vc_nodes(),
        symbol_map=_vc_symbols(),
        required_source_node_ids=(
            "n_vc_goal",
            "n_path_condition",
            "n_wp_assign",
            "n_wp_assert",
            "n_frame",
            "n_unsupported_effect",
        ),
        required_source_symbol_ids=("sym_path", "sym_goal", "sym_generated"),
        feature_preconditions=(
            FEAT_VERIFICATION_CONDITIONS,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            "construct:unsupported_effect",
            "construct:unframed_write",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:wp_soundness", "axiom:frame_stability"),
            domain_changes=("domain:vc_to_fol_formula",),
        ),
        checker_route="differential:vc-fol",
        reconstruction_route="replay:fol-vc",
        description=(
            "Supported verification conditions lower to FOL goals with "
            "theorem-preserving validity direction."
        ),
        identities=_identities(config_identity="config:vc-to-fol@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.PRESERVES_VALIDITY,
        view_role=VIEW_VC,
        heap_resource_losses=(),
        obligation_kinds=(
            ObligationKind.VERIFICATION_CONDITION.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def _build_vc_to_chc() -> ProgramTranslationEdge:
    contract = _contract(
        "vc_to_horn_chc",
        source=_program_source(fragment="verification_condition", profile="program_vc_chc"),
        target=_chc_target(),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=(
            _node("n_vc_goal", "t_query", disposition=NodeDisposition.MAPPED),
            _node(
                "n_path_condition",
                "t_body",
                disposition=NodeDisposition.MAPPED,
            ),
            _node(
                "n_wp_assign",
                "t_horn_clause",
                disposition=NodeDisposition.MAPPED,
            ),
            _node("n_wp_assert", "t_query", disposition=NodeDisposition.MAPPED),
            _node(
                "n_loop_invariant",
                "t_relation",
                disposition=NodeDisposition.MAPPED,
            ),
            _node(
                "n_unsupported_effect",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="unsupported effects cannot become CHC clauses",
            ),
        ),
        symbol_map=(
            _symbol("sym_path", "rel_path", disposition=NodeDisposition.MAPPED),
            _symbol("sym_goal", "rel_error", disposition=NodeDisposition.MAPPED),
            _symbol("sym_inv", "rel_inv", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_vc_goal",
            "n_path_condition",
            "n_wp_assign",
            "n_wp_assert",
            "n_loop_invariant",
            "n_unsupported_effect",
        ),
        required_source_symbol_ids=("sym_path", "sym_goal", "sym_inv"),
        feature_preconditions=(
            FEAT_VERIFICATION_CONDITIONS,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            "construct:unsupported_effect",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:wp_to_horn",),
            domain_changes=("domain:vc_to_horn_clauses",),
        ),
        checker_route="differential:vc-chc",
        reconstruction_route="replay:chc-vc",
        description=(
            "Supported verification conditions lower to equisatisfiable Horn/CHC "
            "clauses for inductive validity."
        ),
        identities=_identities(config_identity="config:vc-to-chc@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.EQUISATISFIABLE,
        view_role=VIEW_VC,
        heap_resource_losses=(),
        obligation_kinds=(ObligationKind.VERIFICATION_CONDITION.value,),
        description=contract.description,
    )


def _build_vc_to_smt() -> ProgramTranslationEdge:
    contract = _contract(
        "vc_to_smt",
        source=_program_source(fragment="verification_condition", profile="program_vc_smt"),
        target=_smt_target(),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=_vc_nodes(),
        symbol_map=_vc_symbols(),
        required_source_node_ids=(
            "n_vc_goal",
            "n_path_condition",
            "n_wp_assign",
            "n_wp_assert",
            "n_frame",
            "n_unsupported_effect",
        ),
        required_source_symbol_ids=("sym_path", "sym_goal", "sym_generated"),
        feature_preconditions=(
            FEAT_VERIFICATION_CONDITIONS,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            "construct:unsupported_effect",
            "construct:unframed_write",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:wp_soundness", "axiom:frame_stability"),
            domain_changes=("domain:vc_to_smt_terms",),
        ),
        checker_route="differential:vc-smt",
        reconstruction_route="replay:smt-vc",
        description=(
            "Supported verification conditions lower to SMT theorem-by-negation "
            "queries preserving validity direction."
        ),
        identities=_identities(config_identity="config:vc-to-smt@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.PRESERVES_VALIDITY,
        view_role=VIEW_VC,
        heap_resource_losses=(),
        obligation_kinds=(
            ObligationKind.VERIFICATION_CONDITION.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def _build_separation_to_fol() -> ProgramTranslationEdge:
    losses = _heap_losses_for_array_encoding()
    contract = _contract(
        "separation_to_first_order",
        source=_separation_source(),
        target=_fol_target(),
        preservation=PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=_separation_nodes(heap_target="t_select"),
        symbol_map=_separation_symbols(),
        required_source_node_ids=(
            "n_pure",
            "n_points_to",
            "n_emp",
            "n_sep_conj",
            "n_and",
            "n_or",
            "n_not",
            "n_implies",
            "n_forall",
            "n_exists",
            "n_frame",
            "n_wand",
            "n_septraction",
        ),
        required_source_symbol_ids=(
            "sym_loc",
            "sym_val",
            "sym_heap",
            "sym_permission",
        ),
        feature_preconditions=(
            FEAT_SEPARATION_SPATIAL,
            FEAT_HEAP_RESOURCE,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            FEAT_UNBOUNDED_HEAP,
            "construct:magic_wand",
            "construct:septraction",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:heap_array_theory",
                "axiom:location_disjointness",
                "axiom:permission_unit_interval",
            ),
            domain_changes=(
                "domain:heap_to_array",
                "domain:sep_conj_to_and",
            ),
            other=("loss:heap_resource_explicit",),
        ),
        checker_route="differential:separation-fol",
        reconstruction_route="replay:fol-separation",
        description=(
            "Supported separation fragments lower to FOL with explicit heap/array "
            "abstraction; magic wand and septraction remain unsupported."
        ),
        identities=_identities(config_identity="config:separation-to-fol@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        view_role=VIEW_SEPARATION,
        heap_resource_losses=losses,
        obligation_kinds=(
            ObligationKind.SEPARATION.value,
            ObligationKind.HEAP_FRAGMENT.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def _build_separation_to_chc() -> ProgramTranslationEdge:
    losses = _heap_losses_for_array_encoding() + (
        HeapResourceLoss(
            loss_id="loss:ownership-elision-chc",
            kind=HeapResourceLossKind.OWNERSHIP_ELISION,
            description=(
                "Ownership transfer obligations become CHC frame clauses; "
                "principal-indexed ownership is not fully reconstructed."
            ),
            source_construct_ids=("n_frame",),
            target_construct_ids=("t_frame_clause",),
            validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        ),
    )
    contract = _contract(
        "separation_to_horn_chc",
        source=_separation_source(profile="separation_chc"),
        target=_chc_target(),
        preservation=PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=_separation_nodes(heap_target="t_heap_rel")
        + (
            _node(
                "n_transition",
                "t_horn_clause",
                disposition=NodeDisposition.MAPPED,
            ),
        ),
        symbol_map=_separation_symbols()
        + (
            _symbol("sym_inv", "rel_inv", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_pure",
            "n_points_to",
            "n_emp",
            "n_sep_conj",
            "n_and",
            "n_or",
            "n_not",
            "n_implies",
            "n_forall",
            "n_exists",
            "n_frame",
            "n_wand",
            "n_septraction",
            "n_transition",
        ),
        required_source_symbol_ids=(
            "sym_loc",
            "sym_val",
            "sym_heap",
            "sym_permission",
            "sym_inv",
        ),
        feature_preconditions=(
            FEAT_SEPARATION_SPATIAL,
            FEAT_HEAP_RESOURCE,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            FEAT_UNBOUNDED_HEAP,
            "construct:magic_wand",
            "construct:septraction",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:heap_array_theory",
                "axiom:location_disjointness",
                "axiom:horn_heap_transition",
            ),
            domain_changes=(
                "domain:heap_to_array",
                "domain:sep_conj_to_and",
                "domain:heap_to_horn_relations",
            ),
            other=("loss:heap_resource_explicit",),
        ),
        checker_route="differential:separation-chc",
        reconstruction_route="replay:chc-separation",
        description=(
            "Supported separation heap transitions lower to Horn/CHC with "
            "explicit heap/resource abstraction losses."
        ),
        identities=_identities(config_identity="config:separation-to-chc@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        view_role=VIEW_SEPARATION,
        heap_resource_losses=losses,
        obligation_kinds=(
            ObligationKind.SEPARATION.value,
            ObligationKind.HEAP_FRAGMENT.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def _build_separation_to_smt() -> ProgramTranslationEdge:
    losses = _heap_losses_for_array_encoding()
    contract = _contract(
        "separation_to_smt",
        source=_separation_source(profile="separation_smt"),
        target=_smt_target(),
        preservation=PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=_separation_nodes(heap_target="t_select"),
        symbol_map=_separation_symbols(),
        required_source_node_ids=(
            "n_pure",
            "n_points_to",
            "n_emp",
            "n_sep_conj",
            "n_and",
            "n_or",
            "n_not",
            "n_implies",
            "n_forall",
            "n_exists",
            "n_frame",
            "n_wand",
            "n_septraction",
        ),
        required_source_symbol_ids=(
            "sym_loc",
            "sym_val",
            "sym_heap",
            "sym_permission",
        ),
        feature_preconditions=(
            FEAT_SEPARATION_SPATIAL,
            FEAT_HEAP_RESOURCE,
            FEAT_PURE_ASSERTIONS,
            FEAT_FRAME_CONDITIONS,
            FEAT_EQUALITY,
            FEAT_ARITHMETIC,
            FEAT_QUANTIFIERS,
        ),
        unsupported_constructs=(
            FEAT_SEPARATION_WAND,
            FEAT_SEPTRACTION,
            FEAT_UNBOUNDED_HEAP,
            "construct:magic_wand",
            "construct:septraction",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:heap_array_theory",
                "axiom:location_disjointness",
                "axiom:permission_unit_interval",
            ),
            domain_changes=(
                "domain:heap_to_array",
                "domain:sep_conj_to_and",
            ),
            other=("loss:heap_resource_explicit",),
        ),
        checker_route="differential:separation-smt",
        reconstruction_route="replay:smt-separation",
        description=(
            "Supported separation fragments lower to SMT Array heap encodings "
            "with explicit heap/resource losses; wand/septraction fail closed."
        ),
        identities=_identities(config_identity="config:separation-to-smt@1"),
    )
    return ProgramTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        validity_direction=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
        view_role=VIEW_SEPARATION,
        heap_resource_losses=losses,
        obligation_kinds=(
            ObligationKind.SEPARATION.value,
            ObligationKind.HEAP_FRAGMENT.value,
            ObligationKind.FRAME.value,
        ),
        description=contract.description,
    )


def build_program_translation_edges() -> tuple[ProgramTranslationEdge, ...]:
    """Return the reviewed program/VC/separation edge set (stable order)."""

    edges = (
        _build_program_to_fol(),
        _build_program_to_chc(),
        _build_program_to_smt(),
        _build_vc_to_fol(),
        _build_vc_to_chc(),
        _build_vc_to_smt(),
        _build_separation_to_fol(),
        _build_separation_to_chc(),
        _build_separation_to_smt(),
    )
    ids = [edge.edge_id for edge in edges]
    if len(ids) != len(set(ids)):
        raise ProgramTranslationError("duplicate program translation edge ids")
    return edges


def program_translation_contracts() -> tuple[TranslationContract, ...]:
    """Return only the ``TranslationContract@2`` edges for planner registration."""

    return tuple(edge.contract for edge in build_program_translation_edges())


# ---------------------------------------------------------------------------
# Edge registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramTranslationEdges:
    """Reviewed edge registry (``ProgramTranslationEdges@1``).

    Owns program/VC/separation routes into FOL, Horn/CHC, and SMT.  The
    planner joins these descriptors; it never invents preservation or drops
    heap/resource losses.
    """

    INTERFACE: ClassVar[str] = PROGRAM_TRANSLATION_EDGES_INTERFACE
    schema_version: ClassVar[str] = PROGRAM_TRANSLATION_EDGES_SCHEMA

    edges: tuple[ProgramTranslationEdge, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.edges:
            object.__setattr__(self, "edges", build_program_translation_edges())
        normalized: list[ProgramTranslationEdge] = []
        seen: set[str] = set()
        for item in self.edges:
            if isinstance(item, ProgramTranslationEdge):
                edge = item
            elif isinstance(item, Mapping):
                edge = ProgramTranslationEdge.from_dict(item)
            else:
                raise ProgramTranslationError(
                    "edges items must be ProgramTranslationEdge values"
                )
            if edge.edge_id in seen:
                raise ProgramTranslationError(
                    f"duplicate edge id {edge.edge_id!r}"
                )
            seen.add(edge.edge_id)
            normalized.append(edge)
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(normalized, key=lambda item: item.edge_id)),
        )

    def __iter__(self):
        return iter(self.edges)

    def __len__(self) -> int:
        return len(self.edges)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return item in self.by_id()
        if isinstance(item, ProgramTranslationEdge):
            return item.edge_id in self.by_id()
        return False

    def by_id(self) -> Mapping[str, ProgramTranslationEdge]:
        return {edge.edge_id: edge for edge in self.edges}

    def contracts(self) -> tuple[TranslationContract, ...]:
        return tuple(edge.contract for edge in self.edges)

    def edges_for(
        self,
        *,
        source_family_id: str | None = None,
        target_family_id: str | None = None,
        view_role: str | None = None,
    ) -> tuple[ProgramTranslationEdge, ...]:
        result: list[ProgramTranslationEdge] = []
        for edge in self.edges:
            if (
                source_family_id is not None
                and edge.source_family_id != source_family_id
            ):
                continue
            if (
                target_family_id is not None
                and edge.target_family_id != target_family_id
            ):
                continue
            if view_role is not None and edge.view_role != view_role:
                continue
            result.append(edge)
        return tuple(result)

    def get(self, edge_id: str) -> ProgramTranslationEdge:
        try:
            return self.by_id()[_identifier(edge_id, "edge_id")]
        except KeyError as error:
            raise ProgramTranslationError(
                f"unknown program translation edge {edge_id!r}"
            ) from error

    def planner(self) -> TranslationPathPlanner:
        return TranslationPathPlanner(self.contracts())

    def plan(
        self,
        request: TranslationPathRequest | Mapping[str, Any],
    ) -> TranslationPathReceipt:
        """Plan a feature-total path using only reviewed program edges."""

        return plan_translation_path(self.contracts(), request)

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            {
                "edge_content_ids": [edge.content_id for edge in self.edges],
                "edge_ids": [edge.edge_id for edge in self.edges],
                "interface": self.INTERFACE,
                "schema_version": self.schema_version,
            },
            domain=EDGES_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def content_id(self) -> str:
        return self.identity.cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "edges": [edge.to_dict() for edge in self.edges],
            "interface": self.INTERFACE,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTranslationEdges":
        value = _mapping(value, "program translation edges")
        _reject_unknown(
            value,
            frozenset(
                {"content_id", "edges", "interface", "schema_version"}
            ),
            "program translation edges",
        )
        interface = value.get("interface", PROGRAM_TRANSLATION_EDGES_INTERFACE)
        if interface != PROGRAM_TRANSLATION_EDGES_INTERFACE:
            raise ProgramTranslationError(
                f"unsupported program translation edges interface {interface!r}"
            )
        schema = value.get("schema_version", PROGRAM_TRANSLATION_EDGES_SCHEMA)
        if schema != PROGRAM_TRANSLATION_EDGES_SCHEMA:
            raise ProgramTranslationError(
                f"unsupported program translation edges schema {schema!r}"
            )
        return cls(edges=tuple(value.get("edges", ())))

    @classmethod
    def default(cls) -> "ProgramTranslationEdges":
        return cls()


DEFAULT_PROGRAM_TRANSLATION_EDGES: Final = ProgramTranslationEdges.default()


# ---------------------------------------------------------------------------
# Obligation lowering
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramObligation:
    """Minimal obligation sketch accepted by program translation lowering.

    This is intentionally a compact recipe rather than a full IR dump so
    fixtures remain generator-friendly.
    """

    obligation_id: str
    kind: ObligationKind | str
    source_family_id: str
    features: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    frames: tuple[str, ...] = ()
    points_to: tuple[tuple[str, str], ...] = ()
    pure_atoms: tuple[str, ...] = ()
    constructs: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "obligation_id",
            _identifier(self.obligation_id, "obligation_id"),
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, ObligationKind, "kind")
        )
        object.__setattr__(
            self,
            "source_family_id",
            _identifier(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self, "features", _sorted_unique(_strings(self.features, "features"))
        )
        object.__setattr__(
            self,
            "assumptions",
            _strings(self.assumptions, "assumptions"),
        )
        object.__setattr__(self, "goals", _strings(self.goals, "goals"))
        object.__setattr__(self, "commands", _strings(self.commands, "commands"))
        object.__setattr__(self, "frames", _strings(self.frames, "frames"))
        object.__setattr__(
            self, "pure_atoms", _strings(self.pure_atoms, "pure_atoms")
        )
        object.__setattr__(
            self, "constructs", _strings(self.constructs, "constructs")
        )
        object.__setattr__(self, "symbols", _strings(self.symbols, "symbols"))

        points: list[tuple[str, str]] = []
        if not isinstance(self.points_to, Sequence) or isinstance(
            self.points_to, (str, bytes, bytearray)
        ):
            raise ProgramTranslationError("points_to must be a sequence of pairs")
        seen_pts: set[tuple[str, str]] = set()
        for item in self.points_to:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise ProgramTranslationError(
                    "points_to items must be (location, value) pairs"
                )
            loc = _identifier(item[0], "points_to location")
            val = _identifier(item[1], "points_to value")
            pair = (loc, val)
            if pair in seen_pts:
                raise ProgramTranslationError(
                    "points_to must not contain duplicate cells"
                )
            seen_pts.add(pair)
            points.append(pair)
        object.__setattr__(self, "points_to", tuple(points))

        attrs = self.attributes
        if not isinstance(attrs, Mapping):
            raise ProgramTranslationError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(attrs))

    def feature_set(self) -> FeatureSet:
        return FeatureSet.from_features(self.features)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "attributes": dict(self.attributes),
            "commands": list(self.commands),
            "constructs": list(self.constructs),
            "features": list(self.features),
            "frames": list(self.frames),
            "goals": list(self.goals),
            "kind": self.kind.value,
            "obligation_id": self.obligation_id,
            "points_to": [list(item) for item in self.points_to],
            "pure_atoms": list(self.pure_atoms),
            "source_family_id": self.source_family_id,
            "symbols": list(self.symbols),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramObligation":
        value = _mapping(value, "program obligation")
        points_raw = value.get("points_to", ())
        points: list[tuple[str, str]] = []
        if isinstance(points_raw, Sequence) and not isinstance(
            points_raw, (str, bytes, bytearray)
        ):
            for item in points_raw:
                if isinstance(item, Sequence) and not isinstance(
                    item, (str, bytes, bytearray)
                ):
                    points.append((str(item[0]), str(item[1])))
        return cls(
            obligation_id=value.get("obligation_id", ""),
            kind=value.get("kind", ""),
            source_family_id=value.get("source_family_id", ""),
            features=tuple(value.get("features", ())),
            assumptions=tuple(value.get("assumptions", ())),
            goals=tuple(value.get("goals", ())),
            commands=tuple(value.get("commands", ())),
            frames=tuple(value.get("frames", ())),
            points_to=tuple(points),
            pure_atoms=tuple(value.get("pure_atoms", ())),
            constructs=tuple(value.get("constructs", ())),
            symbols=tuple(value.get("symbols", ())),
            attributes=dict(value.get("attributes", {}) or {}),
        )


@dataclass(frozen=True, slots=True)
class ProgramLoweringResult:
    """Result of lowering one obligation along a reviewed edge."""

    status: LoweringStatus | str
    edge_id: str
    target_family_id: str
    validity_direction: ValidityDirection | str
    heap_resource_losses: tuple[HeapResourceLoss, ...] = ()
    target_obligation: Mapping[str, Any] = field(default_factory=dict)
    unsupported_constructs: tuple[str, ...] = ()
    reason: str = ""
    path_receipt: TranslationPathReceipt | None = None
    schema_version: str = LOWERING_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, LoweringStatus, "status")
        )
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(
            self,
            "target_family_id",
            _identifier(self.target_family_id, "target_family_id"),
        )
        object.__setattr__(
            self,
            "validity_direction",
            _enum(self.validity_direction, ValidityDirection, "validity_direction"),
        )
        losses: list[HeapResourceLoss] = []
        for item in self.heap_resource_losses:
            if isinstance(item, HeapResourceLoss):
                losses.append(item)
            elif isinstance(item, Mapping):
                losses.append(HeapResourceLoss.from_dict(item))
            else:
                raise ProgramTranslationError(
                    "heap_resource_losses items must be HeapResourceLoss values"
                )
        object.__setattr__(
            self,
            "heap_resource_losses",
            tuple(sorted(losses, key=lambda item: item.loss_id)),
        )
        if not isinstance(self.target_obligation, Mapping):
            raise ProgramTranslationError("target_obligation must be a mapping")
        object.__setattr__(
            self, "target_obligation", dict(self.target_obligation)
        )
        object.__setattr__(
            self,
            "unsupported_constructs",
            _strings(self.unsupported_constructs, "unsupported_constructs"),
        )
        object.__setattr__(
            self, "reason", _optional_text(self.reason, "reason")
        )
        if self.path_receipt is not None and not isinstance(
            self.path_receipt, TranslationPathReceipt
        ):
            raise ProgramTranslationError(
                "path_receipt must be a TranslationPathReceipt or None"
            )
        if self.schema_version != LOWERING_RESULT_SCHEMA:
            raise ProgramTranslationError(
                f"unsupported lowering result schema {self.schema_version!r}"
            )
        if self.status is LoweringStatus.SUPPORTED:
            if self.unsupported_constructs:
                raise ProgramTranslationError(
                    "supported lowering cannot list unsupported constructs"
                )
            if not self.target_obligation:
                raise ProgramTranslationError(
                    "supported lowering requires a target_obligation"
                )
        if self.status is LoweringStatus.UNSUPPORTED:
            if not self.reason:
                raise ProgramTranslationError(
                    "unsupported lowering requires a reason"
                )

    @property
    def is_supported(self) -> bool:
        return self.status is LoweringStatus.SUPPORTED

    @property
    def has_explicit_heap_loss(self) -> bool:
        return any(
            loss.kind is not HeapResourceLossKind.NONE
            for loss in self.heap_resource_losses
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=LOWERING_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def content_id(self) -> str:
        return self.identity.cid

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "heap_resource_losses": [
                loss.to_dict() for loss in self.heap_resource_losses
            ],
            "path_content_id": (
                self.path_receipt.path_content_id
                if self.path_receipt is not None
                else ""
            ),
            "reason": self.reason,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "target_family_id": self.target_family_id,
            "target_obligation": dict(self.target_obligation),
            "unsupported_constructs": list(self.unsupported_constructs),
            "validity_direction": self.validity_direction.value,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["content_id"] = self.content_id
        if self.path_receipt is not None:
            payload["path_receipt"] = self.path_receipt.to_dict()
        return payload


def _obligation_hits_unsupported(
    obligation: ProgramObligation,
    edge: ProgramTranslationEdge,
) -> tuple[str, ...]:
    present = set(obligation.features) | set(obligation.constructs)
    hits = present & set(edge.unsupported_constructs)
    hits |= present & UNSUPPORTED_SPATIAL
    # Spatial wand/septraction constructs named without feat_ prefix.
    for construct in obligation.constructs:
        lowered = construct.lower()
        if "wand" in lowered or "septraction" in lowered:
            hits.add(construct)
    return tuple(sorted(hits))


def _select_edge_for_obligation(
    edges: ProgramTranslationEdges,
    obligation: ProgramObligation,
    target_family_id: str,
) -> ProgramTranslationEdge:
    target = _identifier(target_family_id, "target_family_id")
    kind = obligation.kind
    if kind is ObligationKind.SEPARATION or kind is ObligationKind.HEAP_FRAGMENT:
        view = VIEW_SEPARATION
        source = SOURCE_SEPARATION
    elif kind is ObligationKind.VERIFICATION_CONDITION:
        view = VIEW_VC
        source = SOURCE_PROGRAM
    else:
        view = VIEW_SOURCE
        source = SOURCE_PROGRAM

    if obligation.source_family_id not in {source, SOURCE_PROGRAM, SOURCE_SEPARATION}:
        raise ProgramTranslationError(
            f"obligation source_family_id {obligation.source_family_id!r} is not "
            f"owned by program translation edges"
        )

    candidates = edges.edges_for(
        source_family_id=source,
        target_family_id=target,
        view_role=view,
    )
    if not candidates:
        raise ProgramTranslationError(
            f"no reviewed edge from {view!r}/{obligation.source_family_id!r} "
            f"to {target!r}"
        )

    feature_set = obligation.feature_set()
    compatible: list[ProgramTranslationEdge] = []
    for edge in candidates:
        ok, _missing, hits = edge_feature_compatibility(edge.contract, feature_set)
        if ok and not hits:
            # Obligation kind must be admitted by the edge when declared.
            if edge.obligation_kinds and kind.value not in edge.obligation_kinds:
                continue
            compatible.append(edge)
    if not compatible:
        raise ProgramTranslationError(
            f"no feature-compatible edge from {view!r} to {target!r} for "
            f"features {list(obligation.features)}"
        )
    # Deterministic: most specific feature preconditions first, then edge id.
    compatible.sort(
        key=lambda edge: (
            -len(edge.feature_preconditions),
            edge.edge_id,
        )
    )
    return compatible[0]


def _encode_fol_obligation(
    obligation: ProgramObligation,
    edge: ProgramTranslationEdge,
) -> dict[str, Any]:
    pure = list(obligation.pure_atoms) + list(obligation.assumptions)
    goals = list(obligation.goals) or list(obligation.pure_atoms) or ["true"]
    heap_axioms: list[dict[str, Any]] = []
    for index, (loc, val) in enumerate(obligation.points_to):
        heap_axioms.append(
            {
                "kind": "points_to_select",
                "location": loc,
                "value": val,
                "formula": f"(= (select heap {loc}) {val})",
                "index": index,
            }
        )
    for frame in obligation.frames:
        pure.append(f"frame:{frame}")
    return {
        "encoding": "fol-sketch/v1",
        "edge_id": edge.edge_id,
        "assumptions": pure,
        "goal": goals[0] if len(goals) == 1 else {"and": goals},
        "goals": goals,
        "heap_axioms": heap_axioms,
        "commands": list(obligation.commands),
        "symbols": list(obligation.symbols),
        "validity_direction": edge.validity_direction.value,
        "heap_theory": "array" if obligation.points_to else "none",
    }


def _encode_chc_obligation(
    obligation: ProgramObligation,
    edge: ProgramTranslationEdge,
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if obligation.assumptions or obligation.commands:
        body = list(obligation.assumptions) + [
            f"cmd:{command}" for command in obligation.commands
        ]
        clauses.append(
            {
                "clause_id": f"clause:body:{obligation.obligation_id}",
                "body": body,
                "head": "Inv",
                "is_query": False,
            }
        )
    goals = list(obligation.goals) or ["Error"]
    for index, goal in enumerate(goals):
        clauses.append(
            {
                "clause_id": f"clause:query:{obligation.obligation_id}:{index}",
                "body": ["Inv", goal] if goal != "Error" else ["Inv", f"bad:{goal}"],
                "head": "false",
                "is_query": True,
            }
        )
    for index, (loc, val) in enumerate(obligation.points_to):
        clauses.append(
            {
                "clause_id": f"clause:heap:{obligation.obligation_id}:{index}",
                "body": [f"(= (select heap {loc}) {val})"],
                "head": "HeapOk",
                "is_query": False,
            }
        )
    return {
        "encoding": "chc-sketch/v1",
        "edge_id": edge.edge_id,
        "query_mode": "fixed_point",
        "clauses": clauses,
        "relations": ["Inv", "HeapOk", "Error"],
        "symbols": list(obligation.symbols),
        "validity_direction": edge.validity_direction.value,
        "heap_theory": "array" if obligation.points_to else "none",
    }


def _encode_smt_obligation(
    obligation: ProgramObligation,
    edge: ProgramTranslationEdge,
) -> dict[str, Any]:
    assumptions: list[dict[str, str]] = []
    for index, assumption in enumerate(obligation.assumptions):
        assumptions.append({"name": f"assume_{index}", "formula": assumption})
    for index, atom in enumerate(obligation.pure_atoms):
        assumptions.append({"name": f"pure_{index}", "formula": atom})
    for index, frame in enumerate(obligation.frames):
        assumptions.append({"name": f"frame_{index}", "formula": f"frame:{frame}"})
    for index, (loc, val) in enumerate(obligation.points_to):
        assumptions.append(
            {
                "name": f"points_to_{index}",
                "formula": f"(= (select heap {loc}) {val})",
            }
        )
    goals = list(obligation.goals) or list(obligation.pure_atoms) or ["true"]
    goal = goals[0] if len(goals) == 1 else f"(and {' '.join(goals)})"
    return {
        "encoding": "smt-sketch/v1",
        "edge_id": edge.edge_id,
        "query_mode": "theorem_by_negation",
        "goal": goal,
        "assumptions": assumptions,
        "features": list(obligation.features),
        "functions": (
            [{"name": "heap", "range": "(Array Int Int)", "is_const": True}]
            if obligation.points_to
            else []
        ),
        "symbols": list(obligation.symbols),
        "validity_direction": edge.validity_direction.value,
        "heap_theory": "array" if obligation.points_to else "none",
        "property_ids": [f"property:{obligation.obligation_id}"],
    }


def _encode_target(
    obligation: ProgramObligation,
    edge: ProgramTranslationEdge,
) -> dict[str, Any]:
    target = edge.target_family_id
    if target == TARGET_FOL:
        return _encode_fol_obligation(obligation, edge)
    if target == TARGET_CHC:
        return _encode_chc_obligation(obligation, edge)
    if target == TARGET_SMT:
        return _encode_smt_obligation(obligation, edge)
    raise ProgramTranslationError(f"unsupported target family {target!r}")


def reject_silent_heap_loss(
    *,
    source_has_heap: bool,
    losses: Sequence[HeapResourceLoss],
    target_mentions_heap: bool,
) -> None:
    """Fail closed when heap content would disappear without a loss receipt."""

    if source_has_heap and not target_mentions_heap:
        non_none = [
            loss for loss in losses if loss.kind is not HeapResourceLossKind.NONE
        ]
        if not non_none:
            raise ProgramTranslationError(
                "silent heap/resource loss forbidden: source heap present but "
                "target encoding omits heap without an explicit loss receipt"
            )


def lower_program_obligation(
    obligation: ProgramObligation | Mapping[str, Any],
    target_family_id: str,
    *,
    edges: ProgramTranslationEdges | None = None,
    plan: bool = True,
) -> ProgramLoweringResult:
    """Lower one program/VC/separation obligation along a reviewed edge.

    Unsupported constructs and feature mismatches fail closed with an
    ``unsupported`` result (or raise when the registry itself is incomplete).
    Supported obligations preserve the edge's validity direction and surface
    every heap/resource loss explicitly.
    """

    if isinstance(obligation, Mapping):
        obligation = ProgramObligation.from_dict(obligation)
    if not isinstance(obligation, ProgramObligation):
        raise ProgramTranslationError(
            "obligation must be a ProgramObligation or mapping"
        )

    registry = edges if edges is not None else DEFAULT_PROGRAM_TRANSLATION_EDGES
    try:
        edge = _select_edge_for_obligation(registry, obligation, target_family_id)
    except ProgramTranslationError as error:
        # Feature / kind mismatches are fail-closed unsupported outcomes when a
        # target family is known; structural registry gaps still raise.
        message = str(error)
        if "feature-compatible" not in message and "no reviewed edge" not in message:
            raise
        # Prefer the best-matching reviewed edge for diagnostics.
        kind = obligation.kind
        if kind is ObligationKind.SEPARATION or kind is ObligationKind.HEAP_FRAGMENT:
            view = VIEW_SEPARATION
            source = SOURCE_SEPARATION
        elif kind is ObligationKind.VERIFICATION_CONDITION:
            view = VIEW_VC
            source = SOURCE_PROGRAM
        else:
            view = VIEW_SOURCE
            source = SOURCE_PROGRAM
        diagnostic_edges = registry.edges_for(
            source_family_id=source,
            target_family_id=_identifier(target_family_id, "target_family_id"),
            view_role=view,
        )
        if not diagnostic_edges:
            raise
        edge = diagnostic_edges[0]
        _ok, missing, feature_hits = edge_feature_compatibility(
            edge.contract, obligation.feature_set()
        )
        detail_parts: list[str] = []
        if missing:
            detail_parts.append("missing features: " + ", ".join(missing))
        if feature_hits:
            detail_parts.append(
                "unsupported features: " + ", ".join(feature_hits)
            )
        return ProgramLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            validity_direction=edge.validity_direction,
            heap_resource_losses=edge.heap_resource_losses,
            target_obligation={},
            unsupported_constructs=tuple(feature_hits),
            reason="; ".join(detail_parts) or message,
        )

    hits = _obligation_hits_unsupported(obligation, edge)
    if hits:
        return ProgramLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            validity_direction=edge.validity_direction,
            heap_resource_losses=edge.heap_resource_losses,
            target_obligation={},
            unsupported_constructs=hits,
            reason=(
                "unsupported constructs present: " + ", ".join(hits)
            ),
        )

    # Feature preconditions must be satisfied (defensive re-check).
    compatible, missing, feature_hits = edge_feature_compatibility(
        edge.contract, obligation.feature_set()
    )
    if not compatible:
        detail_parts = []
        if missing:
            detail_parts.append("missing features: " + ", ".join(missing))
        if feature_hits:
            detail_parts.append("unsupported features: " + ", ".join(feature_hits))
        return ProgramLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            validity_direction=edge.validity_direction,
            heap_resource_losses=edge.heap_resource_losses,
            target_obligation={},
            unsupported_constructs=tuple(feature_hits),
            reason="; ".join(detail_parts) or "feature-incompatible edge",
        )

    target_payload = _encode_target(obligation, edge)
    source_has_heap = bool(
        obligation.points_to
        or FEAT_HEAP_RESOURCE in obligation.features
        or FEAT_SEPARATION_SPATIAL in obligation.features
    )
    target_mentions_heap = bool(
        target_payload.get("heap_axioms")
        or target_payload.get("heap_theory") not in {None, "", "none"}
        or any(
            "heap" in str(item).lower()
            for item in target_payload.get("assumptions", ())
        )
        or any(
            "heap" in str(item).lower()
            for item in target_payload.get("clauses", ())
        )
        or target_payload.get("functions")
    )
    reject_silent_heap_loss(
        source_has_heap=source_has_heap,
        losses=edge.heap_resource_losses,
        target_mentions_heap=target_mentions_heap,
    )
    if source_has_heap and not edge.has_heap_loss:
        raise ProgramTranslationError(
            f"edge {edge.edge_id!r} admits heap content without explicit "
            "heap/resource loss receipts"
        )

    path_receipt: TranslationPathReceipt | None = None
    if plan:
        try:
            path_receipt = registry.plan(
                TranslationPathRequest(
                    source_family_id=edge.source_family_id,
                    target_family_id=edge.target_family_id,
                    source_profile_id=edge.contract.source.profile_id,
                    target_profile_id=edge.contract.target.profile_id,
                    features=obligation.features,
                    claimed_preservation=edge.preservation,
                    claimed_authority=edge.authority_ceiling,
                    require_proof_safe=edge.contract.proof_safe,
                    require_counterexample_safe=edge.contract.counterexample_safe,
                )
            )
        except TranslationPathPlannerError as error:
            return ProgramLoweringResult(
                status=LoweringStatus.UNSUPPORTED,
                edge_id=edge.edge_id,
                target_family_id=edge.target_family_id,
                validity_direction=edge.validity_direction,
                heap_resource_losses=edge.heap_resource_losses,
                target_obligation={},
                reason=f"path planning failed: {error}",
            )

    return ProgramLoweringResult(
        status=LoweringStatus.SUPPORTED,
        edge_id=edge.edge_id,
        target_family_id=edge.target_family_id,
        validity_direction=edge.validity_direction,
        heap_resource_losses=edge.heap_resource_losses,
        target_obligation=target_payload,
        path_receipt=path_receipt,
    )


def metamorphic_rename_obligation(
    obligation: ProgramObligation,
    *,
    suffix: str = "_m",
) -> ProgramObligation:
    """Return a symbol-renamed obligation for metamorphic validity checks.

    Renaming free symbols/locations must not change validity direction or
    heap-loss kinds when lowered along the same reviewed edge.
    """

    if not suffix or not isinstance(suffix, str):
        raise ProgramTranslationError("suffix must be a non-empty string")

    def _rename(name: str) -> str:
        return f"{name}{suffix}"

    return ProgramObligation(
        obligation_id=_rename(obligation.obligation_id),
        kind=obligation.kind,
        source_family_id=obligation.source_family_id,
        features=obligation.features,
        assumptions=tuple(_rename(item) for item in obligation.assumptions),
        goals=tuple(_rename(item) for item in obligation.goals),
        commands=tuple(_rename(item) for item in obligation.commands),
        frames=tuple(_rename(item) for item in obligation.frames),
        points_to=tuple(
            (_rename(loc), _rename(val)) for loc, val in obligation.points_to
        ),
        pure_atoms=tuple(_rename(item) for item in obligation.pure_atoms),
        constructs=obligation.constructs,
        symbols=tuple(_rename(item) for item in obligation.symbols),
        attributes=dict(obligation.attributes),
    )


def assert_validity_direction_preserved(
    source: ProgramLoweringResult,
    target: ProgramLoweringResult,
) -> None:
    """Metamorphic oracle: renamed/reordered obligations keep validity direction."""

    if source.status is not LoweringStatus.SUPPORTED:
        raise ProgramTranslationError(
            "source lowering must be supported for validity comparison"
        )
    if target.status is not LoweringStatus.SUPPORTED:
        raise ProgramTranslationError(
            "target lowering must be supported for validity comparison"
        )
    if source.validity_direction is not target.validity_direction:
        raise ProgramTranslationError(
            "validity direction changed under metamorphic transformation: "
            f"{source.validity_direction.value} -> {target.validity_direction.value}"
        )
    source_kinds = tuple(loss.kind for loss in source.heap_resource_losses)
    target_kinds = tuple(loss.kind for loss in target.heap_resource_losses)
    if source_kinds != target_kinds:
        raise ProgramTranslationError(
            "heap/resource loss kinds changed under metamorphic transformation"
        )


__all__ = [
    "COMPILER_IDENTITY",
    "CONFIG_IDENTITY",
    "DEFAULT_PROGRAM_TRANSLATION_EDGES",
    "FEAT_ARITHMETIC",
    "FEAT_EQUALITY",
    "FEAT_FRAME_CONDITIONS",
    "FEAT_HEAP_RESOURCE",
    "FEAT_PROGRAM_COMMANDS",
    "FEAT_PROGRAM_CONTRACTS",
    "FEAT_PURE_ASSERTIONS",
    "FEAT_QUANTIFIERS",
    "FEAT_SEPARATION_SPATIAL",
    "FEAT_SEPARATION_WAND",
    "FEAT_SEPTRACTION",
    "FEAT_UNBOUNDED_HEAP",
    "FEAT_VERIFICATION_CONDITIONS",
    "HEAP_RESOURCE_LOSS_SCHEMA",
    "LOWERING_RESULT_SCHEMA",
    "PROFILE_IDENTITY",
    "PROGRAM_EDGE_SCHEMA",
    "PROGRAM_TRANSLATION_EDGES_INTERFACE",
    "PROGRAM_TRANSLATION_EDGES_SCHEMA",
    "SOURCE_PROGRAM",
    "SOURCE_SEPARATION",
    "TARGET_CHC",
    "TARGET_FOL",
    "TARGET_SMT",
    "UNSUPPORTED_SPATIAL",
    "VIEW_SEPARATION",
    "VIEW_SOURCE",
    "VIEW_VC",
    "HeapResourceLoss",
    "HeapResourceLossKind",
    "LoweringStatus",
    "ObligationKind",
    "ProgramLoweringResult",
    "ProgramObligation",
    "ProgramTranslationEdge",
    "ProgramTranslationEdges",
    "ProgramTranslationError",
    "ValidityDirection",
    "assert_validity_direction_preserved",
    "build_program_translation_edges",
    "lower_program_obligation",
    "metamorphic_rename_obligation",
    "program_translation_contracts",
    "reject_silent_heap_loss",
    "validity_direction_for",
    "weaker_validity_direction",
]
