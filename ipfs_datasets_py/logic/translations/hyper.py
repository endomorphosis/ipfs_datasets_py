"""Bounded HyperLTL self-composition translation edges.

``HyperpropertyTranslationEdges@1`` publishes reviewed
:class:`~ipfs_datasets_py.logic.families.translations.TranslationContract`
routes that lower restricted HyperLTL / hyperproperty formulas into finite
self-composition products and bounded FOL/SMT encodings.

Every edge carries mandatory semantic receipts for:

* quantifier alternation ceiling;
* system-copy / trace cardinality limits;
* finite self-composition bounds (traces, pairs, steps);
* witness contracts (counterexample / clean-sample only); and
* an explicit refusal of unbounded / universal proof authority.

Unsupported alternation depth and unbounded composition fail closed before
any target obligation is emitted.  Accepted transformations surface
differential checker routes and reconstructible witness fixtures.  Bounded
or clean-sample evidence never promotes to universal proof.
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
    TranslationContractError,
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

HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE: Final = "HyperpropertyTranslationEdges@1"
HYPERPROPERTY_TRANSLATION_EDGES_SCHEMA: Final = (
    "logic-hyperproperty-translation-edges/v1"
)
HYPER_EDGE_SCHEMA: Final = "logic-hyperproperty-translation-edge/v1"
HYPER_COMPOSITION_RECEIPT_SCHEMA: Final = "logic-hyperproperty-composition-receipt/v1"
HYPER_LOWERING_RESULT_SCHEMA: Final = "logic-hyperproperty-lowering-result/v1"
HYPER_WITNESS_FIXTURE_SCHEMA: Final = "logic-hyperproperty-witness-fixture/v1"
EDGE_IDENTITY_DOMAIN: Final = "logic.translation.hyperproperty.edge"
EDGES_IDENTITY_DOMAIN: Final = "logic.translation.hyperproperty.edges"
LOWERING_IDENTITY_DOMAIN: Final = "logic.translation.hyperproperty.lowering"
RECEIPT_IDENTITY_DOMAIN: Final = "logic.translation.hyperproperty.receipt"

COMPILER_IDENTITY: Final = "compiler:hyperproperty-self-composition@1"
PROFILE_IDENTITY: Final = "profile:hyperproperty-self-composition-default@1"
CONFIG_IDENTITY: Final = "config:hyperproperty-translation-edges@1"
ENVIRONMENT_IDENTITY: Final = "sha256:env:hyperproperty-translation@1"

# Canonical feature identifiers for hyperproperty / HyperLTL obligations.
FEAT_HYPER_QUANTIFIER: Final = "feat_hyper_quantifier"
FEAT_TRACE_VARIABLE: Final = "feat_trace_variable"
FEAT_NONINTERFERENCE: Final = "feat_noninterference"
FEAT_OBSERVATIONAL_DETERMINISM: Final = "feat_observational_determinism"
FEAT_DECLASSIFICATION: Final = "feat_declassification"
FEAT_INFORMATION_FLOW: Final = "feat_information_flow"
FEAT_SELF_COMPOSITION: Final = "feat_self_composition"
FEAT_FINITE_BOUND: Final = "feat_finite_bound"
FEAT_TEMPORAL_ALWAYS: Final = "feat_temporal_always"
FEAT_TEMPORAL_EVENTUALLY: Final = "feat_temporal_eventually"
FEAT_EQUALITY: Final = "feat_equality"
FEAT_OBSERVATION_MAP: Final = "feat_observation_map"
FEAT_HYPER_ALTERNATION: Final = "feat_hyper_alternation"
FEAT_MULTI_TRACE: Final = "feat_multi_trace"
FEAT_UNBOUNDED_COMPOSITION: Final = "feat_unbounded_composition"
FEAT_UNIVERSAL_PROOF: Final = "feat_universal_proof"
FEAT_NESTED_ALTERNATION: Final = "feat_nested_alternation"
FEAT_EXISTS_FORALL_ALTERNATION: Final = "feat_exists_forall_alternation"
FEAT_FORALL_EXISTS_ALTERNATION: Final = "feat_forall_exists_alternation"

SOURCE_HYPERPROPERTY: Final = "hyperproperty"
SOURCE_HYPERLTL: Final = "hyperltl"
TARGET_SELF_COMPOSITION: Final = "self_composition"
TARGET_FOL: Final = "first_order"
TARGET_SMT: Final = "smt"
TARGET_PRODUCT_SYSTEM: Final = "product_system"

# Default finite ceilings for self-composition (never unbounded).
DEFAULT_MAX_ALTERNATIONS: Final = 1
DEFAULT_MAX_SYSTEM_COPIES: Final = 2
DEFAULT_MAX_TRACES: Final = 32
DEFAULT_MAX_PAIRS: Final = 256
DEFAULT_MAX_STEPS: Final = 64

# Constructs that never lower silently.
UNSUPPORTED_CONSTRUCTS: Final = frozenset(
    {
        FEAT_UNBOUNDED_COMPOSITION,
        FEAT_UNIVERSAL_PROOF,
        FEAT_NESTED_ALTERNATION,
        "construct:unbounded_composition",
        "construct:universal_proof",
        "construct:unbounded_traces",
        "construct:infinite_system_copies",
    }
)


class HyperpropertyTranslationError(ValueError):
    """Raised when a hyperproperty translation edge or lowering is invalid."""


class RouteKind(str, Enum):
    """Semantic family of a hyperproperty translation edge."""

    SELF_COMPOSITION = "self_composition"
    BOUNDED_SMT = "bounded_smt"
    BOUNDED_FOL = "bounded_fol"
    PRODUCT_SYSTEM = "product_system"


class QuantifierShape(str, Enum):
    """Closed vocabulary of supported prenex quantifier shapes."""

    FORALL_FORALL = "forall_forall"
    EXISTS_EXISTS = "exists_exists"
    FORALL_EXISTS = "forall_exists"
    EXISTS_FORALL = "exists_forall"
    FORALL_STAR = "forall_star"
    EXISTS_STAR = "exists_star"
    SINGLE_FORALL = "single_forall"
    SINGLE_EXISTS = "single_exists"
    GENERAL = "general"


class WitnessContractKind(str, Enum):
    """What a successful/failed bounded check may produce as evidence.

    Universal proof is never a valid witness contract on these routes.
    """

    COUNTEREXAMPLE = "counterexample"
    CLEAN_SAMPLE = "clean_sample"
    COUNTEREXAMPLE_OR_CLEAN_SAMPLE = "counterexample_or_clean_sample"
    NONE = "none"


class ObligationKind(str, Enum):
    """Source obligation class accepted by hyperproperty translation edges."""

    NONINTERFERENCE = "noninterference"
    OBSERVATIONAL_DETERMINISM = "observational_determinism"
    DECLASSIFICATION = "declassification"
    HYPERLTL = "hyperltl"
    RELATIONAL = "relational"


class LoweringStatus(str, Enum):
    """Outcome of applying a reviewed edge to one obligation."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class QuantifierKind(str, Enum):
    """Trace quantifier polarity."""

    FORALL = "forall"
    EXISTS = "exists"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HyperpropertyTranslationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise HyperpropertyTranslationError(
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
        raise HyperpropertyTranslationError(
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
            raise HyperpropertyTranslationError(
                f"{field_name} must not contain duplicates"
            )
        seen.add(text)
        result.append(text)
    return tuple(result)


def _enum(value: object, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise HyperpropertyTranslationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HyperpropertyTranslationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HyperpropertyTranslationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise HyperpropertyTranslationError(f"{field_name} must be a bool")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HyperpropertyTranslationError(
            f"{field_name} must be a positive integer"
        )
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HyperpropertyTranslationError(
            f"{field_name} must be a non-negative integer"
        )
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
    environment_identity: str = ENVIRONMENT_IDENTITY,
) -> TranslationIdentities:
    return TranslationIdentities(
        compiler_identity=compiler_identity,
        profile_identity=profile_identity,
        config_identity=config_identity,
        source_identity=source_identity
        or "bafkreihypersrcaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        target_identity=target_identity
        or "bafkreihypertgtaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        environment_identity=environment_identity,
    )


# ---------------------------------------------------------------------------
# Quantifier analysis
# ---------------------------------------------------------------------------


def count_quantifier_alternations(
    quantifier_prefix: Sequence[QuantifierKind | str],
) -> int:
    """Count alternation switches in declaration order.

    ``forall exists forall`` has two alternations.  An empty prefix has zero.
    """

    if quantifier_prefix is None:
        return 0
    if isinstance(quantifier_prefix, (str, bytes, bytearray)):
        raise HyperpropertyTranslationError(
            "quantifier_prefix must be a sequence of quantifier kinds"
        )
    kinds: list[QuantifierKind] = []
    for index, item in enumerate(quantifier_prefix):
        kinds.append(_enum(item, QuantifierKind, f"quantifier_prefix[{index}]"))
    if len(kinds) <= 1:
        return 0
    alternations = 0
    previous = kinds[0]
    for current in kinds[1:]:
        if current is not previous:
            alternations += 1
            previous = current
    return alternations


def quantifier_shape_of(
    quantifier_prefix: Sequence[QuantifierKind | str],
) -> QuantifierShape:
    """Classify a prenex quantifier prefix into a closed shape vocabulary."""

    if quantifier_prefix is None or (
        isinstance(quantifier_prefix, Sequence)
        and not isinstance(quantifier_prefix, (str, bytes, bytearray))
        and len(quantifier_prefix) == 0
    ):
        raise HyperpropertyTranslationError(
            "quantifier_prefix cannot be empty for shape classification"
        )
    kinds = tuple(
        _enum(item, QuantifierKind, f"quantifier_prefix[{index}]")
        for index, item in enumerate(quantifier_prefix)
    )
    if len(kinds) == 1:
        return (
            QuantifierShape.SINGLE_FORALL
            if kinds[0] is QuantifierKind.FORALL
            else QuantifierShape.SINGLE_EXISTS
        )
    unique = set(kinds)
    if unique == {QuantifierKind.FORALL}:
        return (
            QuantifierShape.FORALL_FORALL
            if len(kinds) == 2
            else QuantifierShape.FORALL_STAR
        )
    if unique == {QuantifierKind.EXISTS}:
        return (
            QuantifierShape.EXISTS_EXISTS
            if len(kinds) == 2
            else QuantifierShape.EXISTS_STAR
        )
    # First block kind then opposite block (EAHyper-style single alternation).
    first = kinds[0]
    switch_index = next(
        (i for i, k in enumerate(kinds) if k is not first),
        None,
    )
    if switch_index is None:
        return QuantifierShape.GENERAL
    second = kinds[switch_index]
    if any(k is not second for k in kinds[switch_index:]):
        return QuantifierShape.GENERAL
    if first is QuantifierKind.FORALL and second is QuantifierKind.EXISTS:
        return QuantifierShape.FORALL_EXISTS
    if first is QuantifierKind.EXISTS and second is QuantifierKind.FORALL:
        return QuantifierShape.EXISTS_FORALL
    return QuantifierShape.GENERAL


def system_copies_for_prefix(
    quantifier_prefix: Sequence[QuantifierKind | str],
) -> int:
    """System copies equal the number of distinct trace quantifiers."""

    if quantifier_prefix is None or (
        isinstance(quantifier_prefix, Sequence)
        and not isinstance(quantifier_prefix, (str, bytes, bytearray))
        and len(quantifier_prefix) == 0
    ):
        raise HyperpropertyTranslationError(
            "quantifier_prefix cannot be empty for system-copy count"
        )
    # Validate each entry while counting.
    for index, item in enumerate(quantifier_prefix):
        _enum(item, QuantifierKind, f"quantifier_prefix[{index}]")
    return len(tuple(quantifier_prefix))


# ---------------------------------------------------------------------------
# Composition receipt (mandatory semantic axes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperCompositionReceipt:
    """Mandatory alternation / system-copy / bound / witness receipts.

    Acceptance criterion: unsupported alternation or unbounded composition
    fails; every accepted edge declares finite bounds and a witness contract
    that cannot authorize universal proof.
    """

    max_alternations: int
    max_system_copies: int
    max_traces: int
    max_pairs: int
    max_steps: int
    quantifier_shape: QuantifierShape | str
    witness_contract: WitnessContractKind | str
    route_kind: RouteKind | str
    preserves_quantifier_order: bool = True
    authorizes_universal_proof: bool = False
    description: str = ""
    schema_version: str = HYPER_COMPOSITION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_alternations",
            _non_negative_int(self.max_alternations, "max_alternations"),
        )
        object.__setattr__(
            self,
            "max_system_copies",
            _positive_int(self.max_system_copies, "max_system_copies"),
        )
        object.__setattr__(
            self, "max_traces", _positive_int(self.max_traces, "max_traces")
        )
        object.__setattr__(
            self, "max_pairs", _positive_int(self.max_pairs, "max_pairs")
        )
        object.__setattr__(
            self, "max_steps", _positive_int(self.max_steps, "max_steps")
        )
        object.__setattr__(
            self,
            "quantifier_shape",
            _enum(self.quantifier_shape, QuantifierShape, "quantifier_shape"),
        )
        object.__setattr__(
            self,
            "witness_contract",
            _enum(self.witness_contract, WitnessContractKind, "witness_contract"),
        )
        object.__setattr__(
            self, "route_kind", _enum(self.route_kind, RouteKind, "route_kind")
        )
        object.__setattr__(
            self,
            "preserves_quantifier_order",
            _bool(self.preserves_quantifier_order, "preserves_quantifier_order"),
        )
        object.__setattr__(
            self,
            "authorizes_universal_proof",
            _bool(
                self.authorizes_universal_proof, "authorizes_universal_proof"
            ),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )
        if self.schema_version != HYPER_COMPOSITION_RECEIPT_SCHEMA:
            raise HyperpropertyTranslationError(
                f"unsupported composition receipt schema {self.schema_version!r}"
            )
        if self.authorizes_universal_proof:
            raise HyperpropertyTranslationError(
                "composition receipts cannot authorize universal proof; "
                "bounded self-composition evidence remains non-authoritative"
            )
        if self.witness_contract is WitnessContractKind.NONE:
            raise HyperpropertyTranslationError(
                "witness_contract cannot be none for self-composition routes; "
                "declare counterexample and/or clean_sample contracts"
            )
        if self.max_system_copies > self.max_traces:
            raise HyperpropertyTranslationError(
                "max_system_copies cannot exceed max_traces"
            )

    @property
    def unbounded_proof(self) -> bool:
        return False

    @property
    def may_promote_to_unbounded_proof(self) -> bool:
        return False

    def bound_ids(self) -> tuple[str, ...]:
        """Project finite bounds into assumption-style identifiers."""

        return (
            f"bound:max_alternations_{self.max_alternations}",
            f"bound:system_copies_{self.max_system_copies}",
            f"bound:max_traces_{self.max_traces}",
            f"bound:max_pairs_{self.max_pairs}",
            f"bound:max_steps_{self.max_steps}",
        )

    def assumption_ids(self) -> TranslationAssumptionSet:
        """Project semantic receipts into a TranslationAssumptionSet."""

        return TranslationAssumptionSet(
            bounds=self.bound_ids(),
            domain_changes=(
                f"quantifier_shape:{self.quantifier_shape.value}",
                f"witness_contract:{self.witness_contract.value}",
                "authority:bounded",
                "unbounded_proof:false",
            ),
            other=(
                f"route:{self.route_kind.value}",
                f"preserves_quantifier_order:"
                f"{'true' if self.preserves_quantifier_order else 'false'}",
                "authorizes_universal_proof:false",
            ),
        )

    def admits(
        self,
        *,
        alternations: int,
        system_copies: int,
        max_traces: int | None = None,
        max_pairs: int | None = None,
        max_steps: int | None = None,
    ) -> tuple[bool, str]:
        """Return whether an obligation fits this receipt's ceilings."""

        if alternations > self.max_alternations:
            return (
                False,
                f"unsupported alternation: {alternations} exceeds "
                f"ceiling {self.max_alternations}",
            )
        if system_copies > self.max_system_copies:
            return (
                False,
                f"unsupported system copies: {system_copies} exceeds "
                f"ceiling {self.max_system_copies}",
            )
        if max_traces is not None and max_traces > self.max_traces:
            return (
                False,
                f"trace bound {max_traces} exceeds edge max_traces "
                f"{self.max_traces}",
            )
        if max_pairs is not None and max_pairs > self.max_pairs:
            return (
                False,
                f"pair bound {max_pairs} exceeds edge max_pairs {self.max_pairs}",
            )
        if max_steps is not None and max_steps > self.max_steps:
            return (
                False,
                f"step bound {max_steps} exceeds edge max_steps {self.max_steps}",
            )
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_universal_proof": False,
            "description": self.description,
            "max_alternations": self.max_alternations,
            "max_pairs": self.max_pairs,
            "max_steps": self.max_steps,
            "max_system_copies": self.max_system_copies,
            "max_traces": self.max_traces,
            "may_promote_to_unbounded_proof": False,
            "preserves_quantifier_order": self.preserves_quantifier_order,
            "quantifier_shape": self.quantifier_shape.value,
            "route_kind": self.route_kind.value,
            "schema_version": self.schema_version,
            "unbounded_proof": False,
            "witness_contract": self.witness_contract.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HyperCompositionReceipt":
        value = _mapping(value, "hyper composition receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authorizes_universal_proof",
                    "description",
                    "max_alternations",
                    "max_pairs",
                    "max_steps",
                    "max_system_copies",
                    "max_traces",
                    "may_promote_to_unbounded_proof",
                    "preserves_quantifier_order",
                    "quantifier_shape",
                    "route_kind",
                    "schema_version",
                    "unbounded_proof",
                    "witness_contract",
                }
            ),
            "hyper composition receipt",
        )
        for required in (
            "max_alternations",
            "max_system_copies",
            "max_traces",
            "max_pairs",
            "max_steps",
            "quantifier_shape",
            "witness_contract",
            "route_kind",
        ):
            if required not in value or value.get(required) is None:
                raise HyperpropertyTranslationError(
                    f"{required} cannot be omitted"
                )
        if value.get("authorizes_universal_proof") is True:
            raise HyperpropertyTranslationError(
                "composition receipts cannot authorize universal proof"
            )
        if value.get("unbounded_proof") is True:
            raise HyperpropertyTranslationError(
                "composition receipts reject unbounded_proof=true"
            )
        return cls(
            max_alternations=value["max_alternations"],
            max_system_copies=value["max_system_copies"],
            max_traces=value["max_traces"],
            max_pairs=value["max_pairs"],
            max_steps=value["max_steps"],
            quantifier_shape=value["quantifier_shape"],
            witness_contract=value["witness_contract"],
            route_kind=value["route_kind"],
            preserves_quantifier_order=bool(
                value.get("preserves_quantifier_order", True)
            ),
            authorizes_universal_proof=bool(
                value.get("authorizes_universal_proof", False)
            ),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", HYPER_COMPOSITION_RECEIPT_SCHEMA
            ),
        )


def require_composition_receipt(
    *,
    max_alternations: object,
    max_system_copies: object,
    max_traces: object,
    max_pairs: object,
    max_steps: object,
    quantifier_shape: object,
    witness_contract: object,
    route_kind: object = RouteKind.SELF_COMPOSITION,
    preserves_quantifier_order: bool = True,
    description: str = "",
) -> HyperCompositionReceipt:
    """Validate and construct a mandatory composition receipt (fail-closed)."""

    return HyperCompositionReceipt(
        max_alternations=max_alternations,  # type: ignore[arg-type]
        max_system_copies=max_system_copies,  # type: ignore[arg-type]
        max_traces=max_traces,  # type: ignore[arg-type]
        max_pairs=max_pairs,  # type: ignore[arg-type]
        max_steps=max_steps,  # type: ignore[arg-type]
        quantifier_shape=quantifier_shape,  # type: ignore[arg-type]
        witness_contract=witness_contract,  # type: ignore[arg-type]
        route_kind=route_kind,  # type: ignore[arg-type]
        preserves_quantifier_order=preserves_quantifier_order,
        description=description,
    )


# ---------------------------------------------------------------------------
# Reviewed edge descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperpropertyTranslationEdge:
    """One reviewed HyperLTL / hyperproperty self-composition edge."""

    edge_id: str
    contract: TranslationContract
    receipt: HyperCompositionReceipt
    obligation_kinds: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = HYPER_EDGE_SCHEMA
    edge_content_id: str = ""

    interface: ClassVar[str] = HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))

        contract = self.contract
        if isinstance(contract, Mapping):
            try:
                contract = TranslationContract.from_dict(contract)
            except (TranslationContractError, ValueError) as error:
                raise HyperpropertyTranslationError(str(error)) from error
        if not isinstance(contract, TranslationContract):
            raise HyperpropertyTranslationError(
                "contract must be a TranslationContract"
            )
        object.__setattr__(self, "contract", contract)

        if self.edge_id != contract.contract_id:
            raise HyperpropertyTranslationError(
                f"edge_id {self.edge_id!r} must match contract_id "
                f"{contract.contract_id!r}"
            )

        receipt = self.receipt
        if isinstance(receipt, Mapping):
            receipt = HyperCompositionReceipt.from_dict(receipt)
        if not isinstance(receipt, HyperCompositionReceipt):
            raise HyperpropertyTranslationError(
                "receipt must be a HyperCompositionReceipt"
            )
        object.__setattr__(self, "receipt", receipt)

        kinds = _strings(self.obligation_kinds, "obligation_kinds")
        for kind in kinds:
            _enum(kind, ObligationKind, "obligation_kinds item")
        object.__setattr__(self, "obligation_kinds", kinds)
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != HYPER_EDGE_SCHEMA:
            raise HyperpropertyTranslationError(
                f"unsupported hyperproperty edge schema {self.schema_version!r}"
            )

        # Contract assumptions must include every mandatory receipt projection.
        projected = receipt.assumption_ids()
        if not contract.assumptions.issuperset(projected):
            missing = sorted(
                set(projected.all_assumption_ids)
                - set(contract.assumptions.all_assumption_ids)
            )
            raise HyperpropertyTranslationError(
                "contract assumptions omit mandatory composition receipts: "
                + ", ".join(missing)
            )

        # Bounded preservation requires BOUNDED authority ceiling.
        if contract.preservation is PreservationRelation.BOUNDED:
            if contract.authority_ceiling is not EvidenceAuthority.BOUNDED:
                raise HyperpropertyTranslationError(
                    "bounded self-composition edges require BOUNDED authority"
                )

        # Never allow independent/universal authority on these routes.
        if contract.authority_ceiling in {
            EvidenceAuthority.AUTHORITATIVE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        }:
            raise HyperpropertyTranslationError(
                "self-composition routes cannot claim independent or "
                "authoritative proof ceilings"
            )

        computed = self._compute_identity()
        if self.edge_content_id and self.edge_content_id != computed.cid:
            raise HyperpropertyTranslationError(
                "edge_content_id does not match canonical edge content"
            )
        object.__setattr__(self, "edge_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=EDGE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.edge_content_id

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

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "contract_content_id": self.contract.contract_content_id,
            "contract_id": self.contract.contract_id,
            "description": self.description,
            "edge_id": self.edge_id,
            "obligation_kinds": list(self.obligation_kinds),
            "receipt": self.receipt.to_dict(),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract"] = self.contract.to_dict()
        payload["edge_content_id"] = self.edge_content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HyperpropertyTranslationEdge":
        value = _mapping(value, "hyperproperty translation edge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "contract",
                    "contract_content_id",
                    "contract_id",
                    "description",
                    "edge_content_id",
                    "edge_id",
                    "obligation_kinds",
                    "receipt",
                    "schema_version",
                }
            ),
            "hyperproperty translation edge",
        )
        return cls(
            edge_id=value.get("edge_id", ""),
            contract=value.get("contract", {}),  # type: ignore[arg-type]
            receipt=value.get("receipt", {}),  # type: ignore[arg-type]
            obligation_kinds=tuple(value.get("obligation_kinds", ())),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", HYPER_EDGE_SCHEMA),
            edge_content_id=value.get("edge_content_id", ""),
        )


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
    receipt: HyperCompositionReceipt,
    node_map: Sequence[NodeMapEntry],
    symbol_map: Sequence[SymbolMapEntry],
    feature_preconditions: Sequence[str],
    unsupported_constructs: Sequence[str] = (),
    extra_assumptions: TranslationAssumptionSet | None = None,
    checker_route: str = "",
    reconstruction_route: str = "",
    description: str = "",
    profile_identity: str = "",
    config_identity: str = "",
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
                profile_identity=profile_identity
                or f"profile:hyper:{contract_id}",
                config_identity=config_identity
                or f"config:hyper:{contract_id}",
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
            opaque_disposition=OpaqueDisposition.UNSUPPORTED,
            checker_route=checker_route or f"differential:{contract_id}",
            reconstruction_route=reconstruction_route
            or f"replay:witness:{contract_id}",
            description=description,
        )
    except (TranslationContractError, ValueError) as error:
        raise HyperpropertyTranslationError(str(error)) from error


def _edge(
    contract: TranslationContract,
    receipt: HyperCompositionReceipt,
    *,
    obligation_kinds: Sequence[str] = (),
    description: str = "",
) -> HyperpropertyTranslationEdge:
    return HyperpropertyTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        receipt=receipt,
        obligation_kinds=tuple(obligation_kinds),
        description=description or contract.description,
    )


def _hyper_source(
    *,
    profile: str,
    fragment: str,
    family: str = SOURCE_HYPERPROPERTY,
    notation: str = "hyperltl_source",
) -> TranslationEndpoint:
    return _endpoint(
        family,
        profile_id=profile,
        fragment_id=fragment,
        schema_id="hyperproperty_ir_schema",
        notation_id=notation,
        content_identity=f"sha256:hyper:{family}:{profile}:{fragment}",
    )


def _self_composition_target(*, copies: int) -> TranslationEndpoint:
    return _endpoint(
        TARGET_SELF_COMPOSITION,
        profile_id=f"finite_{copies}_copies",
        fragment_id="bounded_product",
        schema_id="self_composition_schema",
        notation_id="product_system_sketch",
        content_identity=f"sha256:target:self_composition:{copies}",
    )


def _product_system_target(*, copies: int) -> TranslationEndpoint:
    return _endpoint(
        TARGET_PRODUCT_SYSTEM,
        profile_id=f"product_{copies}",
        fragment_id="synchronous_product",
        schema_id="product_system_schema",
        notation_id="product_transition",
        content_identity=f"sha256:target:product_system:{copies}",
    )


def _fol_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_FOL,
        profile_id="qf_uf_bounded",
        fragment_id="self_composition_unrolling",
        schema_id="fol_schema",
        notation_id="canonical_text",
        content_identity="sha256:target:first_order:hyper_sc",
    )


def _smt_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_SMT,
        profile_id="qf_uf_bounded",
        fragment_id="self_composition_bmc",
        schema_id="smt_lib2_schema",
        notation_id="smt_lib2",
        content_identity="sha256:target:smt:hyper_sc",
    )


def _core_hyper_nodes(*, copies: int) -> tuple[NodeMapEntry, ...]:
    copy_targets = tuple(f"sc_copy_{index}" for index in range(copies))
    return (
        _node(
            "n_quantifier_prefix",
            "sc_quantifier_prefix",
            disposition=NodeDisposition.PRESERVED,
            reason="prenex quantifier order is semantic identity",
        ),
        _node(
            "n_trace_variable",
            *copy_targets,
            disposition=NodeDisposition.MAPPED,
            reason=f"each trace variable becomes one of {copies} system copies",
        ),
        _node(
            "n_matrix",
            "sc_relational_matrix",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_observation",
            "sc_observation_equality",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_low_input",
            "sc_low_input_equality",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_high_input",
            "sc_high_input_variation",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_self_composition_bound",
            "sc_finite_bound",
            disposition=NodeDisposition.SYNTHESIZED,
            reason="finite self-composition bounds are mandatory",
        ),
        _node(
            "n_unbounded_composition",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="unbounded composition is rejected",
        ),
        _node(
            "n_universal_proof",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="bounded evidence cannot authorize universal proof",
        ),
    )


def _core_hyper_symbols(*, copies: int) -> tuple[SymbolMapEntry, ...]:
    copy_symbols = tuple(f"sym_copy_{index}" for index in range(copies))
    return (
        _symbol(
            "sym_trace",
            *copy_symbols,
            disposition=NodeDisposition.MAPPED,
            reason="trace variables become product-system state components",
        ),
        _symbol(
            "sym_observation",
            "sym_obs_field",
            disposition=NodeDisposition.PRESERVED,
        ),
        _symbol(
            "sym_low_input",
            "sym_low_field",
            disposition=NodeDisposition.PRESERVED,
        ),
        _symbol(
            "sym_high_input",
            "sym_high_field",
            disposition=NodeDisposition.PRESERVED,
        ),
        _symbol(
            "sym_bound",
            "sym_finite_bound",
            disposition=NodeDisposition.SYNTHESIZED,
            reason="explicit finite bound symbols",
        ),
    )


_COMMON_UNSUPPORTED: Final = (
    FEAT_UNBOUNDED_COMPOSITION,
    FEAT_UNIVERSAL_PROOF,
    FEAT_NESTED_ALTERNATION,
    "construct:unbounded_composition",
    "construct:universal_proof",
)


def _reviewed_catalog() -> tuple[HyperpropertyTranslationEdge, ...]:
    """Build the reviewed HyperLTL self-composition edge set."""

    edges: list[HyperpropertyTranslationEdge] = []

    # ------------------------------------------------------------------
    # Noninterference -> 2-copy self-composition product.
    # ------------------------------------------------------------------
    ni_receipt = HyperCompositionReceipt(
        max_alternations=0,
        max_system_copies=2,
        max_traces=DEFAULT_MAX_TRACES,
        max_pairs=DEFAULT_MAX_PAIRS,
        max_steps=DEFAULT_MAX_STEPS,
        quantifier_shape=QuantifierShape.FORALL_FORALL,
        witness_contract=WitnessContractKind.COUNTEREXAMPLE_OR_CLEAN_SAMPLE,
        route_kind=RouteKind.SELF_COMPOSITION,
        description=(
            "Two-trace noninterference via finite self-composition; "
            "∀π₁∀π₂ with no quantifier alternation."
        ),
    )
    edges.append(
        _edge(
            _contract(
                "noninterference_to_self_composition",
                source=_hyper_source(
                    profile="noninterference",
                    fragment="two_trace_ni",
                ),
                target=_self_composition_target(copies=2),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=ni_receipt,
                node_map=_core_hyper_nodes(copies=2),
                symbol_map=_core_hyper_symbols(copies=2),
                feature_preconditions=(
                    FEAT_NONINTERFERENCE,
                    FEAT_HYPER_QUANTIFIER,
                    FEAT_TRACE_VARIABLE,
                    FEAT_INFORMATION_FLOW,
                    FEAT_OBSERVATION_MAP,
                    FEAT_FINITE_BOUND,
                    FEAT_SELF_COMPOSITION,
                    FEAT_EQUALITY,
                ),
                unsupported_constructs=(
                    *_COMMON_UNSUPPORTED,
                    FEAT_HYPER_ALTERNATION,
                    FEAT_DECLASSIFICATION,
                    FEAT_EXISTS_FORALL_ALTERNATION,
                    FEAT_FORALL_EXISTS_ALTERNATION,
                ),
                extra_assumptions=TranslationAssumptionSet(
                    closure_assumptions=("closure:low_equivalent_inputs",),
                    other=(
                        "information_flow:noninterference",
                        "system_copies:2",
                    ),
                ),
                checker_route="differential:noninterference_self_composition",
                reconstruction_route="replay:witness:ni_self_composition",
                description=(
                    "Lowers two-trace noninterference to a finite 2-copy "
                    "self-composition product with explicit observation and "
                    "bound receipts. Authority remains bounded."
                ),
                profile_identity="profile:noninterference_to_self_composition",
                config_identity="config:ni_2copy_finite",
            ),
            ni_receipt,
            obligation_kinds=(ObligationKind.NONINTERFERENCE.value,),
        )
    )

    # ------------------------------------------------------------------
    # Observational determinism -> 2-copy self-composition.
    # ------------------------------------------------------------------
    od_receipt = HyperCompositionReceipt(
        max_alternations=0,
        max_system_copies=2,
        max_traces=DEFAULT_MAX_TRACES,
        max_pairs=DEFAULT_MAX_PAIRS,
        max_steps=DEFAULT_MAX_STEPS,
        quantifier_shape=QuantifierShape.FORALL_FORALL,
        witness_contract=WitnessContractKind.COUNTEREXAMPLE_OR_CLEAN_SAMPLE,
        route_kind=RouteKind.SELF_COMPOSITION,
        description=(
            "Observational determinism as ∀π₁∀π₂ self-composition over "
            "public observations."
        ),
    )
    edges.append(
        _edge(
            _contract(
                "observational_determinism_to_self_composition",
                source=_hyper_source(
                    profile="observational_determinism",
                    fragment="two_trace_od",
                ),
                target=_self_composition_target(copies=2),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=od_receipt,
                node_map=_core_hyper_nodes(copies=2),
                symbol_map=_core_hyper_symbols(copies=2),
                feature_preconditions=(
                    FEAT_OBSERVATIONAL_DETERMINISM,
                    FEAT_HYPER_QUANTIFIER,
                    FEAT_TRACE_VARIABLE,
                    FEAT_OBSERVATION_MAP,
                    FEAT_FINITE_BOUND,
                    FEAT_SELF_COMPOSITION,
                    FEAT_EQUALITY,
                ),
                unsupported_constructs=(
                    *_COMMON_UNSUPPORTED,
                    FEAT_HYPER_ALTERNATION,
                    FEAT_DECLASSIFICATION,
                ),
                checker_route="differential:od_self_composition",
                reconstruction_route="replay:witness:od_self_composition",
                description=(
                    "Lowers observational determinism to finite 2-copy "
                    "self-composition with observation-equality witnesses."
                ),
                profile_identity="profile:od_to_self_composition",
                config_identity="config:od_2copy_finite",
            ),
            od_receipt,
            obligation_kinds=(ObligationKind.OBSERVATIONAL_DETERMINISM.value,),
        )
    )

    # ------------------------------------------------------------------
    # HyperLTL ∀∀ fragment -> product system (explicit system copies).
    # ------------------------------------------------------------------
    ff_receipt = HyperCompositionReceipt(
        max_alternations=0,
        max_system_copies=2,
        max_traces=DEFAULT_MAX_TRACES,
        max_pairs=DEFAULT_MAX_PAIRS,
        max_steps=DEFAULT_MAX_STEPS,
        quantifier_shape=QuantifierShape.FORALL_FORALL,
        witness_contract=WitnessContractKind.COUNTEREXAMPLE,
        route_kind=RouteKind.PRODUCT_SYSTEM,
        description="HyperLTL ∀π₁∀π₂ matrix to a synchronous product system.",
    )
    edges.append(
        _edge(
            _contract(
                "hyperltl_forall_forall_to_product_system",
                source=_hyper_source(
                    profile="hyperltl",
                    fragment="forall_forall",
                    family=SOURCE_HYPERPROPERTY,
                    notation="hyperltl_source",
                ),
                target=_product_system_target(copies=2),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=ff_receipt,
                node_map=_core_hyper_nodes(copies=2)
                + (
                    _node(
                        "n_always",
                        "prod_always",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_eventually",
                        "prod_eventually",
                        disposition=NodeDisposition.MAPPED,
                    ),
                ),
                symbol_map=_core_hyper_symbols(copies=2),
                feature_preconditions=(
                    FEAT_HYPER_QUANTIFIER,
                    FEAT_TRACE_VARIABLE,
                    FEAT_MULTI_TRACE,
                    FEAT_TEMPORAL_ALWAYS,
                    FEAT_FINITE_BOUND,
                    FEAT_EQUALITY,
                ),
                unsupported_constructs=(
                    *_COMMON_UNSUPPORTED,
                    FEAT_HYPER_ALTERNATION,
                    FEAT_EXISTS_FORALL_ALTERNATION,
                    FEAT_FORALL_EXISTS_ALTERNATION,
                ),
                checker_route="differential:hyperltl_ff_product",
                reconstruction_route="replay:witness:hyperltl_ff_product",
                description=(
                    "Embeds prenex ∀∀ HyperLTL formulas as a 2-copy product "
                    "system with preserved quantifier order."
                ),
                profile_identity="profile:hyperltl_ff_product",
                config_identity="config:hyperltl_ff_2copy",
            ),
            ff_receipt,
            obligation_kinds=(ObligationKind.HYPERLTL.value,),
        )
    )

    # ------------------------------------------------------------------
    # EAHyper-style single-alternation fragment -> self-composition.
    # ------------------------------------------------------------------
    ea_receipt = HyperCompositionReceipt(
        max_alternations=1,
        max_system_copies=4,
        max_traces=DEFAULT_MAX_TRACES,
        max_pairs=DEFAULT_MAX_PAIRS,
        max_steps=DEFAULT_MAX_STEPS,
        quantifier_shape=QuantifierShape.EXISTS_FORALL,
        witness_contract=WitnessContractKind.COUNTEREXAMPLE_OR_CLEAN_SAMPLE,
        route_kind=RouteKind.SELF_COMPOSITION,
        description=(
            "EAHyper decidable fragment: exists*/forall* or forall*/exists* "
            "with at most one quantifier alternation."
        ),
    )
    edges.append(
        _edge(
            _contract(
                "hyperltl_eahyper_fragment_to_self_composition",
                source=_hyper_source(
                    profile="hyperltl_eahyper",
                    fragment="single_alternation",
                ),
                target=_self_composition_target(copies=4),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=ea_receipt,
                node_map=_core_hyper_nodes(copies=4),
                symbol_map=_core_hyper_symbols(copies=4),
                feature_preconditions=(
                    FEAT_HYPER_QUANTIFIER,
                    FEAT_TRACE_VARIABLE,
                    FEAT_MULTI_TRACE,
                    FEAT_FINITE_BOUND,
                    FEAT_SELF_COMPOSITION,
                    FEAT_HYPER_ALTERNATION,
                ),
                unsupported_constructs=(
                    *_COMMON_UNSUPPORTED,
                    "construct:alternation_depth_gt_1",
                    "construct:full_hyperltl",
                ),
                extra_assumptions=TranslationAssumptionSet(
                    other=(
                        "fragment:eahyper_decidable",
                        "max_alternations:1",
                    ),
                ),
                checker_route="differential:eahyper_self_composition",
                reconstruction_route="replay:witness:eahyper_self_composition",
                description=(
                    "Restricted HyperLTL self-composition for the EAHyper "
                    "exists*/forall* and forall*/exists* shapes under a "
                    "single-alternation ceiling."
                ),
                profile_identity="profile:eahyper_self_composition",
                config_identity="config:eahyper_alt1_copies4",
            ),
            ea_receipt,
            obligation_kinds=(
                ObligationKind.HYPERLTL.value,
                ObligationKind.RELATIONAL.value,
            ),
        )
    )

    # ------------------------------------------------------------------
    # HyperLTL noninterference -> bounded SMT product unrolling.
    # ------------------------------------------------------------------
    smt_receipt = HyperCompositionReceipt(
        max_alternations=0,
        max_system_copies=2,
        max_traces=16,
        max_pairs=64,
        max_steps=32,
        quantifier_shape=QuantifierShape.FORALL_FORALL,
        witness_contract=WitnessContractKind.COUNTEREXAMPLE,
        route_kind=RouteKind.BOUNDED_SMT,
        description=(
            "Finite self-composition of noninterference into bounded SMT-LIB."
        ),
    )
    edges.append(
        _edge(
            _contract(
                "noninterference_to_bounded_smt",
                source=_hyper_source(
                    profile="noninterference",
                    fragment="two_trace_ni",
                ),
                target=_smt_target(),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=smt_receipt,
                node_map=(
                    _node(
                        "n_quantifier_prefix",
                        "smt_forall_pi1_pi2",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_trace_variable",
                        "smt_copy_0",
                        "smt_copy_1",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_matrix",
                        "smt_assert_matrix",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite BMC unrolling of relational matrix",
                    ),
                    _node(
                        "n_observation",
                        "smt_obs_eq",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_low_input",
                        "smt_low_eq",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_high_input",
                        "smt_high_var",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_self_composition_bound",
                        "smt_bound_asserts",
                        disposition=NodeDisposition.SYNTHESIZED,
                    ),
                    _node(
                        "n_unbounded_composition",
                        disposition=NodeDisposition.UNSUPPORTED,
                        reason="unbounded composition is rejected",
                    ),
                    _node(
                        "n_universal_proof",
                        disposition=NodeDisposition.UNSUPPORTED,
                        reason="bounded SMT cannot authorize universal proof",
                    ),
                ),
                symbol_map=_core_hyper_symbols(copies=2),
                feature_preconditions=(
                    FEAT_NONINTERFERENCE,
                    FEAT_HYPER_QUANTIFIER,
                    FEAT_TRACE_VARIABLE,
                    FEAT_INFORMATION_FLOW,
                    FEAT_OBSERVATION_MAP,
                    FEAT_FINITE_BOUND,
                    FEAT_EQUALITY,
                    FEAT_SELF_COMPOSITION,
                ),
                unsupported_constructs=(
                    *_COMMON_UNSUPPORTED,
                    FEAT_HYPER_ALTERNATION,
                    FEAT_DECLASSIFICATION,
                ),
                checker_route="differential:ni_bounded_smt",
                reconstruction_route="replay:witness:ni_smt_model",
                description=(
                    "Encodes two-trace noninterference as a bounded SMT "
                    "self-composition with explicit depth and pair bounds."
                ),
                profile_identity="profile:ni_to_bounded_smt",
                config_identity="config:ni_smt_depth_32",
            ),
            smt_receipt,
            obligation_kinds=(ObligationKind.NONINTERFERENCE.value,),
        )
    )

    # ------------------------------------------------------------------
    # HyperLTL ∀∀ -> bounded FOL encoding.
    # ------------------------------------------------------------------
    fol_receipt = HyperCompositionReceipt(
        max_alternations=0,
        max_system_copies=2,
        max_traces=16,
        max_pairs=64,
        max_steps=32,
        quantifier_shape=QuantifierShape.FORALL_FORALL,
        witness_contract=WitnessContractKind.COUNTEREXAMPLE,
        route_kind=RouteKind.BOUNDED_FOL,
        description="Finite self-composition of ∀∀ HyperLTL into first-order logic.",
    )
    edges.append(
        _edge(
            _contract(
                "hyperltl_forall_forall_to_bounded_fol",
                source=_hyper_source(
                    profile="hyperltl",
                    fragment="forall_forall",
                ),
                target=_fol_target(),
                preservation=PreservationRelation.BOUNDED,
                authority_ceiling=EvidenceAuthority.BOUNDED,
                proof_safe=False,
                counterexample_safe=True,
                receipt=fol_receipt,
                node_map=(
                    _node(
                        "n_quantifier_prefix",
                        "fol_forall_pi1_pi2",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_trace_variable",
                        "fol_copy_0",
                        "fol_copy_1",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_matrix",
                        "fol_matrix",
                        disposition=NodeDisposition.APPROXIMATED,
                        reason="finite unrolling of temporal matrix",
                    ),
                    _node(
                        "n_observation",
                        "fol_obs_eq",
                        disposition=NodeDisposition.MAPPED,
                    ),
                    _node(
                        "n_self_composition_bound",
                        "fol_bound",
                        disposition=NodeDisposition.SYNTHESIZED,
                    ),
                    _node(
                        "n_unbounded_composition",
                        disposition=NodeDisposition.UNSUPPORTED,
                        reason="unbounded composition is rejected",
                    ),
                    _node(
                        "n_universal_proof",
                        disposition=NodeDisposition.UNSUPPORTED,
                        reason="bounded FOL cannot authorize universal proof",
                    ),
                ),
                symbol_map=_core_hyper_symbols(copies=2),
                feature_preconditions=(
                    FEAT_HYPER_QUANTIFIER,
                    FEAT_TRACE_VARIABLE,
                    FEAT_MULTI_TRACE,
                    FEAT_TEMPORAL_ALWAYS,
                    FEAT_FINITE_BOUND,
                    FEAT_EQUALITY,
                ),
                unsupported_constructs=(
                    *_COMMON_UNSUPPORTED,
                    FEAT_HYPER_ALTERNATION,
                    FEAT_EXISTS_FORALL_ALTERNATION,
                    FEAT_FORALL_EXISTS_ALTERNATION,
                ),
                checker_route="differential:hyperltl_ff_fol",
                reconstruction_route="replay:witness:hyperltl_ff_fol",
                description=(
                    "Encodes prenex ∀∀ HyperLTL as a bounded first-order "
                    "self-composition obligation."
                ),
                profile_identity="profile:hyperltl_ff_fol",
                config_identity="config:hyperltl_ff_fol_depth_32",
            ),
            fol_receipt,
            obligation_kinds=(ObligationKind.HYPERLTL.value,),
        )
    )

    return tuple(sorted(edges, key=lambda edge: edge.edge_id))


# ---------------------------------------------------------------------------
# Edge registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperpropertyTranslationEdges:
    """Reviewed edge registry (``HyperpropertyTranslationEdges@1``).

    Owns restricted HyperLTL / hyperproperty self-composition routes with
    explicit alternation, system-copy, bound, and witness contracts.  The
    planner joins these descriptors; it never invents unbounded composition
    or elevates bounded evidence to universal proof.
    """

    INTERFACE: ClassVar[str] = HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE
    schema_version: ClassVar[str] = HYPERPROPERTY_TRANSLATION_EDGES_SCHEMA

    edges: tuple[HyperpropertyTranslationEdge, ...] = field(default_factory=tuple)
    catalog_content_id: str = ""
    description: str = (
        "Reviewed HyperLTL self-composition and bounded hyperproperty "
        "translation routes with mandatory alternation, system-copy, bound, "
        "and witness receipts."
    )

    def __post_init__(self) -> None:
        if not self.edges:
            object.__setattr__(self, "edges", _reviewed_catalog())
        normalized: list[HyperpropertyTranslationEdge] = []
        seen: set[str] = set()
        for item in self.edges:
            if isinstance(item, HyperpropertyTranslationEdge):
                edge = item
            elif isinstance(item, Mapping):
                edge = HyperpropertyTranslationEdge.from_dict(item)
            else:
                raise HyperpropertyTranslationError(
                    "edges items must be HyperpropertyTranslationEdge values"
                )
            if edge.edge_id in seen:
                raise HyperpropertyTranslationError(
                    f"duplicate edge id {edge.edge_id!r}"
                )
            seen.add(edge.edge_id)
            if edge.receipt.authorizes_universal_proof:
                raise HyperpropertyTranslationError(
                    f"edge {edge.edge_id!r} cannot authorize universal proof"
                )
            normalized.append(edge)
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(normalized, key=lambda item: item.edge_id)),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description")
            if self.description
            else (
                "Reviewed HyperLTL self-composition and bounded hyperproperty "
                "translation routes with mandatory alternation, system-copy, "
                "bound, and witness receipts."
            ),
        )
        computed = self._compute_identity()
        if self.catalog_content_id and self.catalog_content_id != computed.cid:
            raise HyperpropertyTranslationError(
                "catalog_content_id does not match canonical catalog content"
            )
        object.__setattr__(self, "catalog_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=EDGES_IDENTITY_DOMAIN,
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

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return item in self.by_id()
        if isinstance(item, HyperpropertyTranslationEdge):
            return item.edge_id in self.by_id()
        return False

    def by_id(self) -> Mapping[str, HyperpropertyTranslationEdge]:
        return {edge.edge_id: edge for edge in self.edges}

    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    def contracts(self) -> tuple[TranslationContract, ...]:
        return tuple(edge.contract for edge in self.edges)

    def edges_for(
        self,
        *,
        source_family_id: str | None = None,
        target_family_id: str | None = None,
        route_kind: RouteKind | str | None = None,
        obligation_kind: ObligationKind | str | None = None,
    ) -> tuple[HyperpropertyTranslationEdge, ...]:
        selected_route: RouteKind | None = None
        if route_kind is not None:
            selected_route = _enum(route_kind, RouteKind, "route_kind")
        selected_kind: str | None = None
        if obligation_kind is not None:
            selected_kind = _enum(
                obligation_kind, ObligationKind, "obligation_kind"
            ).value
        result: list[HyperpropertyTranslationEdge] = []
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
            if (
                selected_route is not None
                and edge.receipt.route_kind is not selected_route
            ):
                continue
            if selected_kind is not None and selected_kind not in edge.obligation_kinds:
                continue
            result.append(edge)
        return tuple(result)

    def get(self, edge_id: str) -> HyperpropertyTranslationEdge:
        try:
            return self.by_id()[_identifier(edge_id, "edge_id")]
        except KeyError as error:
            raise HyperpropertyTranslationError(
                f"unknown hyperproperty translation edge {edge_id!r}"
            ) from error

    def by_route_kind(
        self, route_kind: RouteKind | str
    ) -> tuple[HyperpropertyTranslationEdge, ...]:
        return self.edges_for(route_kind=route_kind)

    def planner(self) -> TranslationPathPlanner:
        return TranslationPathPlanner(self.contracts())

    def plan(
        self,
        request: TranslationPathRequest | Mapping[str, Any],
    ) -> TranslationPathReceipt:
        """Plan a feature-total path using only reviewed hyperproperty edges."""

        return plan_translation_path(self.contracts(), request)

    def register_with_planner(
        self, planner: TranslationPathPlanner | None = None
    ) -> TranslationPathPlanner:
        if planner is None:
            planner = TranslationPathPlanner()
        if not isinstance(planner, TranslationPathPlanner):
            raise HyperpropertyTranslationError(
                "planner must be a TranslationPathPlanner"
            )
        try:
            planner.register_edges(self.contracts())
        except TranslationPathPlannerError as error:
            raise HyperpropertyTranslationError(str(error)) from error
        return planner

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "edge_content_ids": [edge.edge_content_id for edge in self.edges],
            "edge_ids": list(self.edge_ids()),
            "interface": self.INTERFACE,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["catalog_content_id"] = self.catalog_content_id
        payload["edges"] = [edge.to_dict() for edge in self.edges]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HyperpropertyTranslationEdges":
        value = _mapping(value, "hyperproperty translation edges")
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
            "hyperproperty translation edges",
        )
        interface = value.get(
            "interface", HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE
        )
        if interface != HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE:
            raise HyperpropertyTranslationError(
                f"unsupported hyperproperty translation edges interface "
                f"{interface!r}"
            )
        schema = value.get(
            "schema_version", HYPERPROPERTY_TRANSLATION_EDGES_SCHEMA
        )
        if schema != HYPERPROPERTY_TRANSLATION_EDGES_SCHEMA:
            raise HyperpropertyTranslationError(
                f"unsupported hyperproperty translation edges schema {schema!r}"
            )
        return cls(
            edges=tuple(value.get("edges", ())),
            catalog_content_id=value.get("catalog_content_id", ""),
            description=value.get("description", ""),
        )

    @classmethod
    def default(cls) -> "HyperpropertyTranslationEdges":
        return cls()

    @classmethod
    def reviewed(cls) -> "HyperpropertyTranslationEdges":
        return cls(edges=_reviewed_catalog())


DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES: Final = (
    HyperpropertyTranslationEdges.default()
)


def build_hyperproperty_translation_edges() -> HyperpropertyTranslationEdges:
    """Public factory for the reviewed hyperproperty edge catalog."""

    return HyperpropertyTranslationEdges.reviewed()


def hyperproperty_translation_contracts() -> tuple[TranslationContract, ...]:
    """Return planner-ready TranslationContract edges from the catalog."""

    return build_hyperproperty_translation_edges().contracts()


# ---------------------------------------------------------------------------
# Obligation recipe and lowering
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperpropertyObligation:
    """Compact hyperproperty/HyperLTL obligation accepted by lowering.

    Intentionally a recipe rather than a full IR dump so differential and
    witness fixtures remain generator-friendly.
    """

    obligation_id: str
    kind: ObligationKind | str
    quantifier_prefix: tuple[str, ...]
    features: tuple[str, ...] = ()
    trace_variables: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()
    low_inputs: tuple[str, ...] = ()
    high_inputs: tuple[str, ...] = ()
    matrix_statement: str = ""
    constructs: tuple[str, ...] = ()
    max_traces: int | None = None
    max_pairs: int | None = None
    max_steps: int | None = None
    unbounded: bool = False
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
        if (
            not isinstance(self.quantifier_prefix, Sequence)
            or isinstance(self.quantifier_prefix, (str, bytes, bytearray))
            or not self.quantifier_prefix
        ):
            raise HyperpropertyTranslationError(
                "quantifier_prefix must be a non-empty sequence of quantifier kinds"
            )
        prefix = tuple(
            _enum(item, QuantifierKind, f"quantifier_prefix[{index}]").value
            for index, item in enumerate(self.quantifier_prefix)
        )
        object.__setattr__(self, "quantifier_prefix", prefix)
        object.__setattr__(
            self, "features", _sorted_unique(_strings(self.features, "features"))
        )
        object.__setattr__(
            self,
            "trace_variables",
            _strings(self.trace_variables, "trace_variables", identifiers=True),
        )
        object.__setattr__(
            self,
            "observations",
            _strings(self.observations, "observations", identifiers=True),
        )
        object.__setattr__(
            self,
            "low_inputs",
            _strings(self.low_inputs, "low_inputs", identifiers=True),
        )
        object.__setattr__(
            self,
            "high_inputs",
            _strings(self.high_inputs, "high_inputs", identifiers=True),
        )
        object.__setattr__(
            self,
            "matrix_statement",
            _optional_text(self.matrix_statement, "matrix_statement"),
        )
        object.__setattr__(
            self, "constructs", _strings(self.constructs, "constructs")
        )
        if self.max_traces is not None:
            object.__setattr__(
                self, "max_traces", _positive_int(self.max_traces, "max_traces")
            )
        if self.max_pairs is not None:
            object.__setattr__(
                self, "max_pairs", _positive_int(self.max_pairs, "max_pairs")
            )
        if self.max_steps is not None:
            object.__setattr__(
                self, "max_steps", _positive_int(self.max_steps, "max_steps")
            )
        object.__setattr__(self, "unbounded", _bool(self.unbounded, "unbounded"))
        attrs = self.attributes
        if not isinstance(attrs, Mapping):
            raise HyperpropertyTranslationError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(attrs))

        # Fail closed: unbounded composition is never admitted as a valid
        # finite obligation (callers may still construct it to test rejection).
        if self.unbounded and (
            self.max_traces is not None
            or self.max_pairs is not None
            or self.max_steps is not None
        ):
            raise HyperpropertyTranslationError(
                "unbounded obligations cannot declare finite max_traces/"
                "max_pairs/max_steps"
            )

    @property
    def alternations(self) -> int:
        return count_quantifier_alternations(self.quantifier_prefix)

    @property
    def system_copies(self) -> int:
        return system_copies_for_prefix(self.quantifier_prefix)

    @property
    def quantifier_shape(self) -> QuantifierShape:
        return quantifier_shape_of(self.quantifier_prefix)

    def feature_set(self) -> FeatureSet:
        return FeatureSet.from_features(self.features)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "constructs": list(self.constructs),
            "features": list(self.features),
            "high_inputs": list(self.high_inputs),
            "kind": self.kind.value,
            "low_inputs": list(self.low_inputs),
            "matrix_statement": self.matrix_statement,
            "max_pairs": self.max_pairs,
            "max_steps": self.max_steps,
            "max_traces": self.max_traces,
            "obligation_id": self.obligation_id,
            "observations": list(self.observations),
            "quantifier_prefix": list(self.quantifier_prefix),
            "trace_variables": list(self.trace_variables),
            "unbounded": self.unbounded,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HyperpropertyObligation":
        value = _mapping(value, "hyperproperty obligation")
        return cls(
            obligation_id=value.get("obligation_id", ""),
            kind=value.get("kind", ""),
            quantifier_prefix=tuple(value.get("quantifier_prefix", ())),
            features=tuple(value.get("features", ())),
            trace_variables=tuple(value.get("trace_variables", ())),
            observations=tuple(value.get("observations", ())),
            low_inputs=tuple(value.get("low_inputs", ())),
            high_inputs=tuple(value.get("high_inputs", ())),
            matrix_statement=value.get("matrix_statement", ""),
            constructs=tuple(value.get("constructs", ())),
            max_traces=value.get("max_traces"),
            max_pairs=value.get("max_pairs"),
            max_steps=value.get("max_steps"),
            unbounded=bool(value.get("unbounded", False)),
            attributes=dict(value.get("attributes", {}) or {}),
        )


@dataclass(frozen=True, slots=True)
class HyperWitnessFixture:
    """Differential / witness fixture for one accepted transformation.

    Fixtures bind checker and reconstruction routes so metamorphic tests can
    replay counterexamples without elevating authority.
    """

    fixture_id: str
    edge_id: str
    checker_route: str
    reconstruction_route: str
    witness_contract: WitnessContractKind | str
    system_copies: int
    quantifier_prefix: tuple[str, ...]
    observations: tuple[str, ...] = ()
    bound_ids: tuple[str, ...] = ()
    authorizes_universal_proof: bool = False
    differential_pairs: tuple[Mapping[str, Any], ...] = ()
    description: str = ""
    schema_version: str = HYPER_WITNESS_FIXTURE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_id", _identifier(self.fixture_id, "fixture_id")
        )
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(
            self, "checker_route", _text(self.checker_route, "checker_route")
        )
        object.__setattr__(
            self,
            "reconstruction_route",
            _text(self.reconstruction_route, "reconstruction_route"),
        )
        object.__setattr__(
            self,
            "witness_contract",
            _enum(self.witness_contract, WitnessContractKind, "witness_contract"),
        )
        object.__setattr__(
            self,
            "system_copies",
            _positive_int(self.system_copies, "system_copies"),
        )
        object.__setattr__(
            self,
            "quantifier_prefix",
            tuple(
                _enum(item, QuantifierKind, f"quantifier_prefix[{index}]").value
                for index, item in enumerate(self.quantifier_prefix)
            ),
        )
        if not self.quantifier_prefix:
            raise HyperpropertyTranslationError(
                "witness fixtures require a non-empty quantifier_prefix"
            )
        object.__setattr__(
            self,
            "observations",
            _strings(self.observations, "observations", identifiers=True),
        )
        object.__setattr__(
            self,
            "bound_ids",
            _strings(self.bound_ids, "bound_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "authorizes_universal_proof",
            _bool(
                self.authorizes_universal_proof, "authorizes_universal_proof"
            ),
        )
        if self.authorizes_universal_proof:
            raise HyperpropertyTranslationError(
                "witness fixtures cannot authorize universal proof"
            )
        pairs: list[dict[str, Any]] = []
        if not isinstance(self.differential_pairs, Sequence) or isinstance(
            self.differential_pairs, (str, bytes, bytearray)
        ):
            raise HyperpropertyTranslationError(
                "differential_pairs must be a sequence of mappings"
            )
        for index, item in enumerate(self.differential_pairs):
            if not isinstance(item, Mapping):
                raise HyperpropertyTranslationError(
                    f"differential_pairs[{index}] must be a mapping"
                )
            pairs.append(dict(item))
        object.__setattr__(self, "differential_pairs", tuple(pairs))
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != HYPER_WITNESS_FIXTURE_SCHEMA:
            raise HyperpropertyTranslationError(
                f"unsupported witness fixture schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_universal_proof": False,
            "bound_ids": list(self.bound_ids),
            "checker_route": self.checker_route,
            "description": self.description,
            "differential_pairs": [dict(item) for item in self.differential_pairs],
            "edge_id": self.edge_id,
            "fixture_id": self.fixture_id,
            "observations": list(self.observations),
            "quantifier_prefix": list(self.quantifier_prefix),
            "reconstruction_route": self.reconstruction_route,
            "schema_version": self.schema_version,
            "system_copies": self.system_copies,
            "witness_contract": self.witness_contract.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HyperWitnessFixture":
        value = _mapping(value, "hyper witness fixture")
        return cls(
            fixture_id=value.get("fixture_id", ""),
            edge_id=value.get("edge_id", ""),
            checker_route=value.get("checker_route", ""),
            reconstruction_route=value.get("reconstruction_route", ""),
            witness_contract=value.get("witness_contract", ""),
            system_copies=value.get("system_copies", 0),
            quantifier_prefix=tuple(value.get("quantifier_prefix", ())),
            observations=tuple(value.get("observations", ())),
            bound_ids=tuple(value.get("bound_ids", ())),
            authorizes_universal_proof=bool(
                value.get("authorizes_universal_proof", False)
            ),
            differential_pairs=tuple(value.get("differential_pairs", ())),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", HYPER_WITNESS_FIXTURE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class HyperLoweringResult:
    """Result of lowering one hyperproperty obligation along a reviewed edge."""

    status: LoweringStatus | str
    edge_id: str
    target_family_id: str
    authority_ceiling: EvidenceAuthority | str
    receipt: HyperCompositionReceipt | None = None
    target_obligation: Mapping[str, Any] = field(default_factory=dict)
    witness_fixture: HyperWitnessFixture | None = None
    unsupported_constructs: tuple[str, ...] = ()
    reason: str = ""
    path_receipt: TranslationPathReceipt | None = None
    schema_version: str = HYPER_LOWERING_RESULT_SCHEMA

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
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling"),
        )
        if self.receipt is not None:
            receipt = self.receipt
            if isinstance(receipt, Mapping):
                receipt = HyperCompositionReceipt.from_dict(receipt)
            if not isinstance(receipt, HyperCompositionReceipt):
                raise HyperpropertyTranslationError(
                    "receipt must be a HyperCompositionReceipt or None"
                )
            object.__setattr__(self, "receipt", receipt)
        if not isinstance(self.target_obligation, Mapping):
            raise HyperpropertyTranslationError(
                "target_obligation must be a mapping"
            )
        object.__setattr__(
            self, "target_obligation", dict(self.target_obligation)
        )
        if self.witness_fixture is not None:
            fixture = self.witness_fixture
            if isinstance(fixture, Mapping):
                fixture = HyperWitnessFixture.from_dict(fixture)
            if not isinstance(fixture, HyperWitnessFixture):
                raise HyperpropertyTranslationError(
                    "witness_fixture must be a HyperWitnessFixture or None"
                )
            object.__setattr__(self, "witness_fixture", fixture)
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
            raise HyperpropertyTranslationError(
                "path_receipt must be a TranslationPathReceipt or None"
            )
        if self.schema_version != HYPER_LOWERING_RESULT_SCHEMA:
            raise HyperpropertyTranslationError(
                f"unsupported lowering result schema {self.schema_version!r}"
            )
        if self.status is LoweringStatus.SUPPORTED:
            if self.unsupported_constructs:
                raise HyperpropertyTranslationError(
                    "supported lowering cannot list unsupported constructs"
                )
            if not self.target_obligation:
                raise HyperpropertyTranslationError(
                    "supported lowering requires a target_obligation"
                )
            if self.receipt is None:
                raise HyperpropertyTranslationError(
                    "supported lowering requires a composition receipt"
                )
            if self.witness_fixture is None:
                raise HyperpropertyTranslationError(
                    "supported lowering requires a differential/witness fixture"
                )
            if self.authority_ceiling is not EvidenceAuthority.BOUNDED:
                raise HyperpropertyTranslationError(
                    "supported self-composition lowering must retain BOUNDED "
                    "authority"
                )
        if self.status is LoweringStatus.UNSUPPORTED and not self.reason:
            raise HyperpropertyTranslationError(
                "unsupported lowering requires a reason"
            )

    @property
    def is_supported(self) -> bool:
        return self.status is LoweringStatus.SUPPORTED

    @property
    def authorizes_universal_proof(self) -> bool:
        return False

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
            "authority_ceiling": self.authority_ceiling.value,
            "authorizes_universal_proof": False,
            "edge_id": self.edge_id,
            "path_content_id": (
                self.path_receipt.path_content_id
                if self.path_receipt is not None
                else ""
            ),
            "reason": self.reason,
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "target_family_id": self.target_family_id,
            "target_obligation": dict(self.target_obligation),
            "unsupported_constructs": list(self.unsupported_constructs),
            "witness_fixture": (
                self.witness_fixture.to_dict()
                if self.witness_fixture is not None
                else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["content_id"] = self.content_id
        if self.path_receipt is not None:
            payload["path_receipt"] = self.path_receipt.to_dict()
        return payload


def reject_unbounded_composition(
    *,
    unbounded: bool,
    max_traces: int | None,
    max_pairs: int | None,
    max_steps: int | None,
) -> None:
    """Fail closed when composition would run without finite bounds."""

    if unbounded:
        raise HyperpropertyTranslationError(
            "unbounded composition is rejected; self-composition requires "
            "explicit finite max_traces/max_pairs/max_steps"
        )
    if max_traces is None or max_pairs is None or max_steps is None:
        raise HyperpropertyTranslationError(
            "unbounded composition is rejected; max_traces, max_pairs, and "
            "max_steps must all be positive finite bounds"
        )


def reject_authority_promotion(
    *,
    authority: EvidenceAuthority | str,
    authorizes_universal_proof: bool = False,
) -> None:
    """Fail closed when bounded evidence is treated as universal proof."""

    ceiling = _enum(authority, EvidenceAuthority, "authority")
    if authorizes_universal_proof:
        raise HyperpropertyTranslationError(
            "bounded self-composition evidence cannot authorize universal proof"
        )
    if ceiling in {
        EvidenceAuthority.AUTHORITATIVE,
        EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    }:
        raise HyperpropertyTranslationError(
            f"authority ceiling {ceiling.value} is not permitted for "
            "self-composition routes (bounded only)"
        )


def _obligation_hits_unsupported(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> tuple[str, ...]:
    present = set(obligation.features) | set(obligation.constructs)
    hits = present & set(edge.unsupported_constructs)
    hits |= present & UNSUPPORTED_CONSTRUCTS
    if obligation.unbounded:
        hits.add(FEAT_UNBOUNDED_COMPOSITION)
    for construct in obligation.constructs:
        lowered = construct.lower()
        if "unbounded" in lowered:
            hits.add(construct)
        if "universal_proof" in lowered or "unbounded_proof" in lowered:
            hits.add(construct)
    return tuple(sorted(hits))


def _select_edge_for_obligation(
    edges: HyperpropertyTranslationEdges,
    obligation: HyperpropertyObligation,
    target_family_id: str,
) -> HyperpropertyTranslationEdge:
    target = _identifier(target_family_id, "target_family_id")
    kind = obligation.kind
    candidates = edges.edges_for(
        target_family_id=target,
        obligation_kind=kind,
    )
    if not candidates:
        # Fall back to any edge to the requested target for diagnostics.
        candidates = edges.edges_for(target_family_id=target)
    if not candidates:
        raise HyperpropertyTranslationError(
            f"no reviewed hyperproperty edge to target family {target!r}"
        )

    feature_set = obligation.feature_set()
    compatible: list[HyperpropertyTranslationEdge] = []
    for edge in candidates:
        if edge.obligation_kinds and kind.value not in edge.obligation_kinds:
            continue
        ok, _missing, hits = edge_feature_compatibility(edge.contract, feature_set)
        if ok and not hits:
            admitted, _reason = edge.receipt.admits(
                alternations=obligation.alternations,
                system_copies=obligation.system_copies,
                max_traces=obligation.max_traces,
                max_pairs=obligation.max_pairs,
                max_steps=obligation.max_steps,
            )
            if admitted:
                compatible.append(edge)
    if not compatible:
        raise HyperpropertyTranslationError(
            f"no feature-compatible hyperproperty edge to {target!r} for "
            f"kind {kind.value} with features {list(obligation.features)}"
        )
    compatible.sort(
        key=lambda edge: (-len(edge.feature_preconditions), edge.edge_id)
    )
    return compatible[0]


def _encode_self_composition(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> dict[str, Any]:
    copies = obligation.system_copies
    copy_ids = [
        f"copy:{name}" if name else f"copy:{index}"
        for index, name in enumerate(
            obligation.trace_variables
            or tuple(f"pi{i + 1}" for i in range(copies))
        )
    ]
    # Pad/truncate to exact system-copy count.
    while len(copy_ids) < copies:
        copy_ids.append(f"copy:pi{len(copy_ids) + 1}")
    copy_ids = copy_ids[:copies]
    return {
        "encoding": "self-composition-sketch/v1",
        "edge_id": edge.edge_id,
        "quantifier_prefix": list(obligation.quantifier_prefix),
        "quantifier_shape": obligation.quantifier_shape.value,
        "alternations": obligation.alternations,
        "system_copies": copies,
        "copy_ids": copy_ids,
        "matrix_statement": obligation.matrix_statement
        or "relational_matrix",
        "observations": list(obligation.observations),
        "low_inputs": list(obligation.low_inputs),
        "high_inputs": list(obligation.high_inputs),
        "bounds": {
            "max_traces": obligation.max_traces,
            "max_pairs": obligation.max_pairs,
            "max_steps": obligation.max_steps,
        },
        "authority_ceiling": EvidenceAuthority.BOUNDED.value,
        "authorizes_universal_proof": False,
        "unbounded_proof": False,
        "witness_contract": edge.receipt.witness_contract.value,
    }


def _encode_smt(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> dict[str, Any]:
    base = _encode_self_composition(obligation, edge)
    assumptions: list[dict[str, str]] = []
    for index, field_name in enumerate(obligation.low_inputs):
        assumptions.append(
            {
                "name": f"low_eq_{index}",
                "formula": f"(= (low {field_name} copy_0) (low {field_name} copy_1))",
            }
        )
    for index, field_name in enumerate(obligation.observations):
        assumptions.append(
            {
                "name": f"obs_eq_{index}",
                "formula": (
                    f"(= (obs {field_name} copy_0) (obs {field_name} copy_1))"
                ),
            }
        )
    goal = obligation.matrix_statement or "noninterference_holds"
    return {
        **base,
        "encoding": "smt-self-composition-sketch/v1",
        "query_mode": "theorem_by_negation",
        "goal": goal,
        "assumptions": assumptions,
        "features": list(obligation.features),
        "property_ids": [f"property:{obligation.obligation_id}"],
    }


def _encode_fol(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> dict[str, Any]:
    base = _encode_self_composition(obligation, edge)
    low_axioms = [
        f"(= (low {field} pi1) (low {field} pi2))"
        for field in obligation.low_inputs
    ]
    obs_axioms = [
        f"(= (obs {field} pi1) (obs {field} pi2))"
        for field in obligation.observations
    ]
    return {
        **base,
        "encoding": "fol-self-composition-sketch/v1",
        "assumptions": low_axioms,
        "goals": obs_axioms
        or [obligation.matrix_statement or "relational_postcondition"],
        "symbols": list(obligation.trace_variables)
        + list(obligation.observations)
        + list(obligation.low_inputs)
        + list(obligation.high_inputs),
    }


def _encode_product_system(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> dict[str, Any]:
    base = _encode_self_composition(obligation, edge)
    return {
        **base,
        "encoding": "product-system-sketch/v1",
        "product_kind": "synchronous",
        "components": base["copy_ids"],
        "shared_observations": list(obligation.observations),
        "transition_relation": "product_next",
        "initial_condition": "product_init",
    }


def _encode_target(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> dict[str, Any]:
    target = edge.target_family_id
    if target == TARGET_SELF_COMPOSITION:
        return _encode_self_composition(obligation, edge)
    if target == TARGET_PRODUCT_SYSTEM:
        return _encode_product_system(obligation, edge)
    if target == TARGET_SMT:
        return _encode_smt(obligation, edge)
    if target == TARGET_FOL:
        return _encode_fol(obligation, edge)
    raise HyperpropertyTranslationError(
        f"unsupported target family {target!r}"
    )


def build_witness_fixture(
    obligation: HyperpropertyObligation,
    edge: HyperpropertyTranslationEdge,
) -> HyperWitnessFixture:
    """Build a differential/witness fixture for an accepted transformation."""

    pairs: list[dict[str, Any]] = []
    if obligation.observations:
        # Compact differential recipe: one low-equivalent, high-varying pair.
        pairs.append(
            {
                "pair_id": f"pair:{obligation.obligation_id}:0",
                "role": "counterexample_candidate",
                "left_trace": "trace:left",
                "right_trace": "trace:right",
                "low_inputs_equal": True,
                "high_inputs_differ": bool(obligation.high_inputs),
                "observation_fields": list(obligation.observations),
                "expected_observation_equal": True,
            }
        )
        pairs.append(
            {
                "pair_id": f"pair:{obligation.obligation_id}:clean",
                "role": "clean_sample",
                "left_trace": "trace:clean_a",
                "right_trace": "trace:clean_b",
                "low_inputs_equal": True,
                "high_inputs_differ": True,
                "observation_fields": list(obligation.observations),
                "expected_observation_equal": True,
            }
        )
    return HyperWitnessFixture(
        fixture_id=f"fixture:{edge.edge_id}:{obligation.obligation_id}",
        edge_id=edge.edge_id,
        checker_route=edge.contract.checker_route,
        reconstruction_route=edge.contract.reconstruction_route,
        witness_contract=edge.receipt.witness_contract,
        system_copies=obligation.system_copies,
        quantifier_prefix=obligation.quantifier_prefix,
        observations=obligation.observations,
        bound_ids=edge.receipt.bound_ids(),
        differential_pairs=tuple(pairs),
        description=(
            f"Differential/witness fixture for {edge.edge_id} on "
            f"{obligation.obligation_id}"
        ),
    )


def lower_hyperproperty_obligation(
    obligation: HyperpropertyObligation | Mapping[str, Any],
    target_family_id: str,
    *,
    edges: HyperpropertyTranslationEdges | None = None,
    plan: bool = True,
) -> HyperLoweringResult:
    """Lower one hyperproperty obligation along a reviewed edge.

    Unsupported alternation, unbounded composition, and authority promotion
    fail closed.  Supported obligations retain BOUNDED authority and surface
    an explicit differential/witness fixture.
    """

    if isinstance(obligation, Mapping):
        obligation = HyperpropertyObligation.from_dict(obligation)
    if not isinstance(obligation, HyperpropertyObligation):
        raise HyperpropertyTranslationError(
            "obligation must be a HyperpropertyObligation or mapping"
        )

    registry = (
        edges if edges is not None else DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES
    )
    target = _identifier(target_family_id, "target_family_id")

    # Hard fail-closed gates before edge selection diagnostics.
    if obligation.unbounded:
        diagnostic = registry.edges_for(target_family_id=target)
        edge_id = diagnostic[0].edge_id if diagnostic else "unresolved"
        authority = (
            diagnostic[0].authority_ceiling
            if diagnostic
            else EvidenceAuthority.BOUNDED
        )
        return HyperLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge_id,
            target_family_id=target,
            authority_ceiling=authority,
            reason=(
                "unbounded composition is rejected; self-composition requires "
                "explicit finite max_traces/max_pairs/max_steps"
            ),
            unsupported_constructs=(FEAT_UNBOUNDED_COMPOSITION,),
        )

    try:
        reject_unbounded_composition(
            unbounded=obligation.unbounded,
            max_traces=obligation.max_traces,
            max_pairs=obligation.max_pairs,
            max_steps=obligation.max_steps,
        )
    except HyperpropertyTranslationError as error:
        diagnostic = registry.edges_for(target_family_id=target)
        edge_id = diagnostic[0].edge_id if diagnostic else "unresolved"
        authority = (
            diagnostic[0].authority_ceiling
            if diagnostic
            else EvidenceAuthority.BOUNDED
        )
        return HyperLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge_id,
            target_family_id=target,
            authority_ceiling=authority,
            reason=str(error),
            unsupported_constructs=(FEAT_UNBOUNDED_COMPOSITION,),
        )

    try:
        edge = _select_edge_for_obligation(registry, obligation, target)
    except HyperpropertyTranslationError as error:
        message = str(error)
        diagnostic_edges = registry.edges_for(target_family_id=target)
        if not diagnostic_edges:
            raise
        edge = diagnostic_edges[0]
        # Prefer kind-matching diagnostic edge when available.
        kind_matches = [
            item
            for item in diagnostic_edges
            if obligation.kind.value in item.obligation_kinds
        ]
        if kind_matches:
            edge = kind_matches[0]

        admitted, admit_reason = edge.receipt.admits(
            alternations=obligation.alternations,
            system_copies=obligation.system_copies,
            max_traces=obligation.max_traces,
            max_pairs=obligation.max_pairs,
            max_steps=obligation.max_steps,
        )
        _ok, missing, feature_hits = edge_feature_compatibility(
            edge.contract, obligation.feature_set()
        )
        detail_parts: list[str] = []
        if not admitted and admit_reason:
            detail_parts.append(admit_reason)
        if missing:
            detail_parts.append("missing features: " + ", ".join(missing))
        if feature_hits:
            detail_parts.append(
                "unsupported features: " + ", ".join(feature_hits)
            )
        unsupported = tuple(sorted(set(feature_hits)))
        if not admitted and "alternation" in admit_reason:
            unsupported = tuple(
                sorted(set(unsupported) | {FEAT_HYPER_ALTERNATION})
            )
        return HyperLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            authority_ceiling=edge.authority_ceiling,
            receipt=edge.receipt,
            unsupported_constructs=unsupported,
            reason="; ".join(detail_parts) or message,
        )

    hits = _obligation_hits_unsupported(obligation, edge)
    if hits:
        return HyperLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            authority_ceiling=edge.authority_ceiling,
            receipt=edge.receipt,
            unsupported_constructs=hits,
            reason="unsupported constructs present: " + ", ".join(hits),
        )

    admitted, admit_reason = edge.receipt.admits(
        alternations=obligation.alternations,
        system_copies=obligation.system_copies,
        max_traces=obligation.max_traces,
        max_pairs=obligation.max_pairs,
        max_steps=obligation.max_steps,
    )
    if not admitted:
        unsupported: tuple[str, ...] = ()
        if "alternation" in admit_reason:
            unsupported = (FEAT_HYPER_ALTERNATION,)
        return HyperLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            authority_ceiling=edge.authority_ceiling,
            receipt=edge.receipt,
            unsupported_constructs=unsupported,
            reason=admit_reason,
        )

    # Shape gate for non-alternating routes: EAHyper admits EA/AE; pure
    # noninterference routes require forall_forall.
    if (
        edge.receipt.quantifier_shape is QuantifierShape.FORALL_FORALL
        and obligation.quantifier_shape is not QuantifierShape.FORALL_FORALL
    ):
        return HyperLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=edge.target_family_id,
            authority_ceiling=edge.authority_ceiling,
            receipt=edge.receipt,
            unsupported_constructs=(FEAT_HYPER_ALTERNATION,),
            reason=(
                f"unsupported quantifier shape {obligation.quantifier_shape.value}; "
                f"edge {edge.edge_id!r} requires forall_forall"
            ),
        )

    if edge.receipt.quantifier_shape is QuantifierShape.EXISTS_FORALL:
        # EAHyper fragment: allow EA, AE, and pure star shapes under alt ≤ 1.
        allowed = {
            QuantifierShape.EXISTS_FORALL,
            QuantifierShape.FORALL_EXISTS,
            QuantifierShape.FORALL_STAR,
            QuantifierShape.EXISTS_STAR,
            QuantifierShape.FORALL_FORALL,
            QuantifierShape.EXISTS_EXISTS,
            QuantifierShape.SINGLE_FORALL,
            QuantifierShape.SINGLE_EXISTS,
        }
        if obligation.quantifier_shape not in allowed:
            return HyperLoweringResult(
                status=LoweringStatus.UNSUPPORTED,
                edge_id=edge.edge_id,
                target_family_id=edge.target_family_id,
                authority_ceiling=edge.authority_ceiling,
                receipt=edge.receipt,
                unsupported_constructs=(FEAT_NESTED_ALTERNATION,),
                reason=(
                    f"unsupported quantifier shape "
                    f"{obligation.quantifier_shape.value} for EAHyper fragment"
                ),
            )

    reject_authority_promotion(
        authority=edge.authority_ceiling,
        authorizes_universal_proof=False,
    )

    target_payload = _encode_target(obligation, edge)
    witness = build_witness_fixture(obligation, edge)

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
            return HyperLoweringResult(
                status=LoweringStatus.UNSUPPORTED,
                edge_id=edge.edge_id,
                target_family_id=edge.target_family_id,
                authority_ceiling=edge.authority_ceiling,
                receipt=edge.receipt,
                reason=f"path planning failed: {error}",
            )

    return HyperLoweringResult(
        status=LoweringStatus.SUPPORTED,
        edge_id=edge.edge_id,
        target_family_id=edge.target_family_id,
        authority_ceiling=edge.authority_ceiling,
        receipt=edge.receipt,
        target_obligation=target_payload,
        witness_fixture=witness,
        path_receipt=path_receipt,
    )


def metamorphic_rename_obligation(
    obligation: HyperpropertyObligation,
    *,
    suffix: str = "_m",
) -> HyperpropertyObligation:
    """Return a field-renamed obligation for metamorphic witness checks."""

    if not suffix or not isinstance(suffix, str):
        raise HyperpropertyTranslationError("suffix must be a non-empty string")

    def _rename(name: str) -> str:
        return f"{name}{suffix}"

    return HyperpropertyObligation(
        obligation_id=_rename(obligation.obligation_id),
        kind=obligation.kind,
        quantifier_prefix=obligation.quantifier_prefix,
        features=obligation.features,
        trace_variables=tuple(
            _rename(item) for item in obligation.trace_variables
        ),
        observations=tuple(_rename(item) for item in obligation.observations),
        low_inputs=tuple(_rename(item) for item in obligation.low_inputs),
        high_inputs=tuple(_rename(item) for item in obligation.high_inputs),
        matrix_statement=(
            _rename(obligation.matrix_statement)
            if obligation.matrix_statement
            else ""
        ),
        constructs=obligation.constructs,
        max_traces=obligation.max_traces,
        max_pairs=obligation.max_pairs,
        max_steps=obligation.max_steps,
        unbounded=obligation.unbounded,
        attributes=dict(obligation.attributes),
    )


def assert_witness_fixture_preserved(
    source: HyperLoweringResult,
    target: HyperLoweringResult,
) -> None:
    """Metamorphic oracle: renamed obligations keep witness/authority contracts."""

    if source.status is not LoweringStatus.SUPPORTED:
        raise HyperpropertyTranslationError(
            "source lowering must be supported for witness comparison"
        )
    if target.status is not LoweringStatus.SUPPORTED:
        raise HyperpropertyTranslationError(
            "target lowering must be supported for witness comparison"
        )
    if source.edge_id != target.edge_id:
        raise HyperpropertyTranslationError(
            f"edge id changed under metamorphic transformation: "
            f"{source.edge_id} -> {target.edge_id}"
        )
    if source.authority_ceiling is not target.authority_ceiling:
        raise HyperpropertyTranslationError(
            "authority ceiling changed under metamorphic transformation"
        )
    if source.authorizes_universal_proof or target.authorizes_universal_proof:
        raise HyperpropertyTranslationError(
            "metamorphic comparison cannot authorize universal proof"
        )
    assert source.witness_fixture is not None
    assert target.witness_fixture is not None
    if (
        source.witness_fixture.witness_contract
        is not target.witness_fixture.witness_contract
    ):
        raise HyperpropertyTranslationError(
            "witness contract changed under metamorphic transformation"
        )
    if (
        source.witness_fixture.system_copies
        != target.witness_fixture.system_copies
    ):
        raise HyperpropertyTranslationError(
            "system_copies changed under metamorphic transformation"
        )
    if (
        source.witness_fixture.quantifier_prefix
        != target.witness_fixture.quantifier_prefix
    ):
        raise HyperpropertyTranslationError(
            "quantifier_prefix changed under metamorphic transformation"
        )


__all__ = [
    "COMPILER_IDENTITY",
    "CONFIG_IDENTITY",
    "DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES",
    "DEFAULT_MAX_ALTERNATIONS",
    "DEFAULT_MAX_PAIRS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MAX_SYSTEM_COPIES",
    "DEFAULT_MAX_TRACES",
    "ENVIRONMENT_IDENTITY",
    "FEAT_DECLASSIFICATION",
    "FEAT_EQUALITY",
    "FEAT_EXISTS_FORALL_ALTERNATION",
    "FEAT_FINITE_BOUND",
    "FEAT_FORALL_EXISTS_ALTERNATION",
    "FEAT_HYPER_ALTERNATION",
    "FEAT_HYPER_QUANTIFIER",
    "FEAT_INFORMATION_FLOW",
    "FEAT_MULTI_TRACE",
    "FEAT_NESTED_ALTERNATION",
    "FEAT_NONINTERFERENCE",
    "FEAT_OBSERVATION_MAP",
    "FEAT_OBSERVATIONAL_DETERMINISM",
    "FEAT_SELF_COMPOSITION",
    "FEAT_TEMPORAL_ALWAYS",
    "FEAT_TEMPORAL_EVENTUALLY",
    "FEAT_TRACE_VARIABLE",
    "FEAT_UNBOUNDED_COMPOSITION",
    "FEAT_UNIVERSAL_PROOF",
    "HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE",
    "HYPERPROPERTY_TRANSLATION_EDGES_SCHEMA",
    "HYPER_COMPOSITION_RECEIPT_SCHEMA",
    "HYPER_EDGE_SCHEMA",
    "HYPER_LOWERING_RESULT_SCHEMA",
    "HYPER_WITNESS_FIXTURE_SCHEMA",
    "PROFILE_IDENTITY",
    "SOURCE_HYPERLTL",
    "SOURCE_HYPERPROPERTY",
    "TARGET_FOL",
    "TARGET_PRODUCT_SYSTEM",
    "TARGET_SELF_COMPOSITION",
    "TARGET_SMT",
    "UNSUPPORTED_CONSTRUCTS",
    "HyperCompositionReceipt",
    "HyperLoweringResult",
    "HyperWitnessFixture",
    "HyperpropertyObligation",
    "HyperpropertyTranslationEdge",
    "HyperpropertyTranslationEdges",
    "HyperpropertyTranslationError",
    "LoweringStatus",
    "ObligationKind",
    "QuantifierKind",
    "QuantifierShape",
    "RouteKind",
    "WitnessContractKind",
    "assert_witness_fixture_preserved",
    "build_hyperproperty_translation_edges",
    "build_witness_fixture",
    "count_quantifier_alternations",
    "hyperproperty_translation_contracts",
    "lower_hyperproperty_obligation",
    "metamorphic_rename_obligation",
    "quantifier_shape_of",
    "reject_authority_promotion",
    "reject_unbounded_composition",
    "require_composition_receipt",
    "system_copies_for_prefix",
]
