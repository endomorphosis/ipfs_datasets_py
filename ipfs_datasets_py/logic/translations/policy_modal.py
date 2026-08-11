"""Authorization, frame, event, modal, and cognitive translation edges.

``PolicyModalTranslationEdges@1`` publishes reviewed
:class:`~ipfs_datasets_py.logic.families.translations.TranslationContract`
edges for policy and modal/cognitive families.  Every edge makes the following
semantic axes **explicit** (never inferred from family names alone):

* **frame conditions** — Kripke frame axioms / F-logic frame constraints
* **norm semantics** — monadic deontic / SecPAL decision polarity
* **event closure** — inertia / circumscription / clipped fluent closure
* **agent indices** — multi-agent epistemic/intention indexing policy
* **reification** — relational vs reified FOL/ATP encoding
* **approximation direction** — over / under / none (required for conservative)

Effects: typed Datalog/SecPAL, FOL/ATP, relational, and reified encodings for
supported authorization, frame, event-calculus, deontic, epistemic, intention,
DCEC, and TDFOL profiles.  Edges are planner-ready descriptors only; this
module performs no compilation or prover execution.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
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
    TranslationPathPlanner,
    TranslationPathPlannerError,
)

# Same shape as logic.families.models so edge/contract ids stay composable.
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

POLICY_MODAL_EDGES_INTERFACE: Final = "PolicyModalTranslationEdges@1"
POLICY_MODAL_EDGE_SCHEMA_VERSION: Final = "logic-policy-modal-translation-edge/v1"
POLICY_MODAL_CATALOG_SCHEMA_VERSION: Final = "logic-policy-modal-translation-catalog/v1"
POLICY_MODAL_EDGE_IDENTITY_DOMAIN: Final = "logic.translation.policy_modal.edge"
POLICY_MODAL_CATALOG_IDENTITY_DOMAIN: Final = "logic.translation.policy_modal.catalog"
POLICY_MODAL_MODULE_VERSION: Final = "1.0.0"

# Stable compiler / profile / config identity pins for reviewed edges.
_COMPILER_PREFIX: Final = "compiler:policy-modal/"
_PROFILE_PREFIX: Final = "profile:policy-modal/"
_CONFIG_PREFIX: Final = "config:policy-modal/"


class PolicyModalTranslationError(ValueError):
    """Raised when a policy/modal translation edge is malformed or incomplete."""


class EncodingKind(str, Enum):
    """Target encoding shape for a policy/modal edge."""

    DATALOG = "datalog"
    SECPAL = "secpal"
    RELATIONAL_FOL = "relational_fol"
    REIFIED_FOL = "reified_fol"
    ATP_TPTP = "atp_tptp"


class ReificationKind(str, Enum):
    """How modal/event structure is reified in the target encoding.

    ``none`` is an explicit declaration (relational embedding without turning
    operators into first-class individuals).  Silent omission is rejected.
    """

    NONE = "none"
    PREDICATE = "predicate_reification"
    FORMULA = "formula_reification"
    FULL = "full_reification"


class ApproximationDirection(str, Enum):
    """Direction of a conservative translation (explicit even when none)."""

    NONE = "none"
    OVER = "over_approximation"
    UNDER = "under_approximation"


class AgentIndexPolicy(str, Enum):
    """How agent indices are treated on cognitive/modal edges."""

    NOT_APPLICABLE = "not_applicable"
    FORBIDDEN = "forbidden"
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT_INDEXED = "multi_agent_indexed"
    REIFIED_AGENT_SORT = "reified_agent_sort"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PolicyModalTranslationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise PolicyModalTranslationError(f"{field_name} must not contain NUL bytes")
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name)


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _IDENTIFIER_RE.fullmatch(result):
        raise PolicyModalTranslationError(
            f"{field_name} must be a lowercase canonical identifier; got {result!r}"
        )
    return result


def _strings(
    values: Sequence[str] | object,
    field_name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise PolicyModalTranslationError(f"{field_name} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _identifier(item, f"{field_name} item") if identifiers else _text(
            item, f"{field_name} item"
        )
        if text in seen:
            raise PolicyModalTranslationError(f"{field_name} must not contain duplicates")
        seen.add(text)
        result.append(text)
    return tuple(result)


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise PolicyModalTranslationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyModalTranslationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PolicyModalTranslationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


# ---------------------------------------------------------------------------
# Endpoint / identity builders
# ---------------------------------------------------------------------------


def _endpoint(
    family_id: str,
    *,
    profile_id: str = "",
    fragment_id: str = "",
    schema_id: str = "",
    notation_id: str = "",
    content_identity: str = "",
) -> TranslationEndpoint:
    profile = profile_id or f"{family_id}_default"
    fragment = fragment_id or f"{family_id}_core"
    schema = schema_id or f"{family_id}_schema"
    notation = notation_id or f"{family_id}_notation"
    content = content_identity or f"sha256:policy-modal-endpoint:{family_id}:{profile}"
    return TranslationEndpoint(
        family_id=family_id,
        profile_id=profile,
        fragment_id=fragment,
        schema_id=schema,
        notation_id=notation,
        content_identity=content,
    )


def _identities(edge_id: str) -> TranslationIdentities:
    return TranslationIdentities(
        compiler_identity=f"{_COMPILER_PREFIX}{edge_id}@{POLICY_MODAL_MODULE_VERSION}",
        profile_identity=f"{_PROFILE_PREFIX}{edge_id}",
        config_identity=f"{_CONFIG_PREFIX}{edge_id}",
        source_identity=f"bafkrei{edge_id.replace('_', '')[:50].ljust(50, 'a')}",
        target_identity=f"bafkrei{edge_id.replace('_', '')[::-1][:50].ljust(50, 'b')}",
        environment_identity=f"sha256:policy-modal-env:{edge_id}",
    )


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


# ---------------------------------------------------------------------------
# PolicyModalEdge@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyModalEdge:
    """One reviewed policy/modal translation edge with explicit semantics.

    The edge embeds a planner-ready :class:`TranslationContract` and requires
    every acceptance axis to be declared.  Silent omission of frame conditions,
    norm semantics, event closure, agent indices, reification, or approximation
    direction is rejected at construction time.
    """

    edge_id: str
    contract: TranslationContract
    encoding_kind: EncodingKind | str
    frame_conditions: tuple[str, ...]
    norm_semantics: tuple[str, ...]
    event_closure: tuple[str, ...]
    agent_indices: AgentIndexPolicy | str
    reification: ReificationKind | str
    approximation_direction: ApproximationDirection | str
    description: str = ""
    schema_version: str = POLICY_MODAL_EDGE_SCHEMA_VERSION
    edge_content_id: str = ""

    interface: ClassVar[str] = POLICY_MODAL_EDGES_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))

        contract = self.contract
        if isinstance(contract, Mapping):
            try:
                contract = TranslationContract.from_dict(contract)
            except TranslationContractError as error:
                raise PolicyModalTranslationError(
                    f"invalid embedded translation contract: {error}"
                ) from error
        if not isinstance(contract, TranslationContract):
            raise PolicyModalTranslationError(
                "contract must be a TranslationContract"
            )
        object.__setattr__(self, "contract", contract)

        object.__setattr__(
            self,
            "encoding_kind",
            _enum(self.encoding_kind, EncodingKind, "encoding_kind"),
        )
        object.__setattr__(
            self,
            "frame_conditions",
            _strings(self.frame_conditions, "frame_conditions", identifiers=True),
        )
        object.__setattr__(
            self,
            "norm_semantics",
            _strings(self.norm_semantics, "norm_semantics", identifiers=True),
        )
        object.__setattr__(
            self,
            "event_closure",
            _strings(self.event_closure, "event_closure", identifiers=True),
        )
        object.__setattr__(
            self,
            "agent_indices",
            _enum(self.agent_indices, AgentIndexPolicy, "agent_indices"),
        )
        object.__setattr__(
            self,
            "reification",
            _enum(self.reification, ReificationKind, "reification"),
        )
        object.__setattr__(
            self,
            "approximation_direction",
            _enum(
                self.approximation_direction,
                ApproximationDirection,
                "approximation_direction",
            ),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )
        if self.schema_version != POLICY_MODAL_EDGE_SCHEMA_VERSION:
            raise PolicyModalTranslationError(
                f"unsupported policy/modal edge schema {self.schema_version!r}"
            )

        self._validate_acceptance_axes()
        self._validate_contract_alignment()

        computed = self._compute_identity()
        if self.edge_content_id and self.edge_content_id != computed.cid:
            raise PolicyModalTranslationError(
                "edge_content_id does not match canonical edge content"
            )
        object.__setattr__(self, "edge_content_id", computed.cid)

    # -- validation ---------------------------------------------------------

    def _validate_acceptance_axes(self) -> None:
        """Reject edges that omit any acceptance-required semantic axis."""

        # Frame conditions must be non-empty for modal/frame sources.
        source_family = self.contract.source.family_id
        if source_family in {"modal", "frame_logic"} and not self.frame_conditions:
            raise PolicyModalTranslationError(
                "frame conditions must be explicit for modal/frame_logic edges "
                f"(edge {self.edge_id!r})"
            )

        # Norm semantics must be non-empty for authorization/deontic sources.
        if source_family in {"authorization", "deontic", "tdfol"} and not self.norm_semantics:
            raise PolicyModalTranslationError(
                "norm semantics must be explicit for authorization/deontic/tdfol "
                f"edges (edge {self.edge_id!r})"
            )

        # Event closure must be non-empty for event-calculus / dcec sources.
        if source_family in {"event_calculus", "dcec"} and not self.event_closure:
            raise PolicyModalTranslationError(
                "event closure must be explicit for event_calculus/dcec edges "
                f"(edge {self.edge_id!r})"
            )

        # Agent indices: cognitive/modal multi-agent encodings cannot use
        # not_applicable when the source is epistemic/intention/dcec.
        profile = self.contract.source.profile_id
        cognitive = any(
            token in profile
            for token in ("epistemic", "intention", "doxastic", "cognitive")
        ) or source_family == "dcec"
        if cognitive and self.agent_indices is AgentIndexPolicy.NOT_APPLICABLE:
            raise PolicyModalTranslationError(
                "agent indices must be explicit for cognitive/dcec edges "
                f"(edge {self.edge_id!r}); not_applicable is forbidden"
            )

        # Reification must align with encoding kind.
        if self.encoding_kind in {
            EncodingKind.REIFIED_FOL,
            EncodingKind.ATP_TPTP,
        } and self.reification is ReificationKind.NONE:
            # ATP may use pure relational; only reified_fol strictly requires
            # non-none reification.
            if self.encoding_kind is EncodingKind.REIFIED_FOL:
                raise PolicyModalTranslationError(
                    "reified_fol encoding requires a non-none reification kind "
                    f"(edge {self.edge_id!r})"
                )

        if (
            self.encoding_kind is EncodingKind.RELATIONAL_FOL
            and self.reification is not ReificationKind.NONE
        ):
            raise PolicyModalTranslationError(
                "relational_fol encoding requires reification=none "
                f"(edge {self.edge_id!r}); use reified_fol for reification"
            )

        # Approximation direction must match preservation relation.
        preservation = self.contract.preservation
        if preservation in {
            PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
            PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION,
        }:
            expected = (
                ApproximationDirection.OVER
                if preservation
                is PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION
                else ApproximationDirection.UNDER
            )
            if self.approximation_direction is ApproximationDirection.NONE:
                raise PolicyModalTranslationError(
                    "conservative translations require an approximation direction "
                    f"(edge {self.edge_id!r})"
                )
            if self.approximation_direction is not expected:
                raise PolicyModalTranslationError(
                    f"approximation_direction {self.approximation_direction.value!r} "
                    f"does not match preservation {preservation.value!r} "
                    f"(edge {self.edge_id!r})"
                )
        elif self.approximation_direction is not ApproximationDirection.NONE:
            raise PolicyModalTranslationError(
                "approximation_direction is only valid for conservative "
                f"approximations (edge {self.edge_id!r})"
            )

    def _validate_contract_alignment(self) -> None:
        if self.edge_id != self.contract.contract_id:
            raise PolicyModalTranslationError(
                f"contract_id {self.contract.contract_id!r} must equal edge_id "
                f"{self.edge_id!r}"
            )

    # -- identity / serialization -------------------------------------------

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=POLICY_MODAL_EDGE_IDENTITY_DOMAIN,
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

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "agent_indices": self.agent_indices.value,
            "approximation_direction": self.approximation_direction.value,
            "contract": self.contract.semantic_dict(),
            "description": self.description,
            "edge_id": self.edge_id,
            "encoding_kind": self.encoding_kind.value,
            "event_closure": list(self.event_closure),
            "frame_conditions": list(self.frame_conditions),
            "interface": self.interface,
            "norm_semantics": list(self.norm_semantics),
            "reification": self.reification.value,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract"] = self.contract.to_dict()
        payload["edge_content_id"] = self.edge_content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyModalEdge":
        value = _mapping(value, "policy/modal edge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "agent_indices",
                    "approximation_direction",
                    "contract",
                    "description",
                    "edge_content_id",
                    "edge_id",
                    "encoding_kind",
                    "event_closure",
                    "frame_conditions",
                    "interface",
                    "norm_semantics",
                    "reification",
                    "schema_version",
                }
            ),
            "policy/modal edge",
        )
        interface = value.get("interface", POLICY_MODAL_EDGES_INTERFACE)
        if interface != POLICY_MODAL_EDGES_INTERFACE:
            raise PolicyModalTranslationError(
                f"unsupported policy/modal edge interface {interface!r}"
            )
        return cls(
            edge_id=value.get("edge_id", ""),
            contract=value.get("contract", {}),  # type: ignore[arg-type]
            encoding_kind=value.get("encoding_kind", ""),
            frame_conditions=tuple(value.get("frame_conditions", ())),
            norm_semantics=tuple(value.get("norm_semantics", ())),
            event_closure=tuple(value.get("event_closure", ())),
            agent_indices=value.get(
                "agent_indices", AgentIndexPolicy.NOT_APPLICABLE.value
            ),
            reification=value.get("reification", ReificationKind.NONE.value),
            approximation_direction=value.get(
                "approximation_direction", ApproximationDirection.NONE.value
            ),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", POLICY_MODAL_EDGE_SCHEMA_VERSION
            ),
            edge_content_id=value.get("edge_content_id", ""),
        )


# ---------------------------------------------------------------------------
# Catalog builders (reviewed edges)
# ---------------------------------------------------------------------------


def _contract(
    *,
    contract_id: str,
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
) -> TranslationContract:
    return TranslationContract(
        contract_id=contract_id,
        source=source,
        target=target,
        preservation=preservation,
        identities=_identities(contract_id),
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
        checker_route=checker_route or f"differential:{contract_id}",
        reconstruction_route=reconstruction_route or f"replay:{contract_id}",
        description=description,
    )


def build_authorization_to_datalog_edge() -> PolicyModalEdge:
    """Stratified authorization policy → Datalog rules (decision-preserving)."""

    edge_id = "authorization_to_datalog"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "authorization",
            profile_id="authorization_secpal_core",
            fragment_id="authorization_stratified",
            notation_id="secpal_controlled",
        ),
        target=_endpoint(
            "datalog",
            profile_id="datalog_stratified",
            fragment_id="datalog_horn",
            notation_id="datalog_rules",
        ),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=(
            _node("n_fact", "t_fact", disposition=NodeDisposition.PRESERVED),
            _node("n_rule", "t_horn_rule", disposition=NodeDisposition.MAPPED),
            _node("n_says", "t_says_atom", disposition=NodeDisposition.MAPPED),
            _node(
                "n_delegation",
                "t_delegation_rule",
                disposition=NodeDisposition.MAPPED,
            ),
            _node(
                "n_query",
                "t_goal",
                disposition=NodeDisposition.MAPPED,
            ),
        ),
        symbol_map=(
            _symbol("may", "may", disposition=NodeDisposition.PRESERVED),
            _symbol("role", "role", disposition=NodeDisposition.PRESERVED),
            _symbol("speaks_for", "speaks_for", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_fact",
            "n_rule",
            "n_says",
            "n_delegation",
            "n_query",
        ),
        required_source_symbol_ids=("may", "role", "speaks_for"),
        feature_preconditions=(
            "feat_authorization_facts",
            "feat_stratified_rules",
            "feat_decision_query",
        ),
        unsupported_constructs=(
            "feat_unstratified_negation",
            "feat_unbounded_delegation",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:closed_world_authorization",),
            closure_assumptions=("closure:stratified_negation",),
            bounds=("bound:max_delegation_depth_64",),
            other=("assumption:deny_overrides_explicit",),
        ),
        description=(
            "Maps stratified authorization facts/rules/queries to Datalog with "
            "explicit closed-world and delegation-depth assumptions."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.DATALOG,
        frame_conditions=("frame:not_applicable_authorization",),
        norm_semantics=(
            "norm:allow_deny_effects",
            "norm:deny_overrides",
            "norm:speaks_for_delegation",
            "norm:closed_world_decision",
        ),
        event_closure=("event_closure:not_applicable_authorization",),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_authorization_to_secpal_edge() -> PolicyModalEdge:
    """Authorization IR → controlled SecPAL surface (decision-preserving)."""

    edge_id = "authorization_to_secpal"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "authorization",
            profile_id="authorization_ir_core",
            fragment_id="authorization_principals",
            notation_id="authorization_ir",
        ),
        target=_endpoint(
            "authorization",
            profile_id="secpal",
            fragment_id="secpal_says",
            notation_id="secpal_controlled",
            schema_id="secpal_schema",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_principal", "t_principal", disposition=NodeDisposition.PRESERVED),
            _node("n_says", "t_says", disposition=NodeDisposition.MAPPED),
            _node("n_can_say", "t_can_say", disposition=NodeDisposition.MAPPED),
            _node("n_constraint", "t_constraint", disposition=NodeDisposition.MAPPED),
            _node(
                "n_open_recursion",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="open recursion requires finite bounds declaration",
            ),
        ),
        symbol_map=(
            _symbol("says", "says", disposition=NodeDisposition.PRESERVED),
            _symbol("can_say", "can_say", disposition=NodeDisposition.MAPPED),
            _symbol("can", "can", disposition=NodeDisposition.PRESERVED),
        ),
        required_source_node_ids=(
            "n_principal",
            "n_says",
            "n_can_say",
            "n_constraint",
            "n_open_recursion",
        ),
        required_source_symbol_ids=("says", "can_say", "can"),
        feature_preconditions=(
            "feat_principals",
            "feat_says_assertions",
            "feat_can_say_delegation",
        ),
        unsupported_constructs=("feat_open_recursion", "feat_vendor_secpal_extensions"),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:secpal_says_monotonic",),
            bounds=("bound:max_delegation_depth_64",),
            other=("assumption:authorization_decision_authority_only",),
        ),
        description=(
            "Projects AuthorizationIR onto controlled SecPAL says/can-say surface "
            "with explicit finite delegation bounds."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.SECPAL,
        frame_conditions=("frame:not_applicable_authorization",),
        norm_semantics=(
            "norm:secpal_says",
            "norm:can_say_delegation",
            "norm:constraint_guards",
            "norm:authorization_decision_only",
        ),
        event_closure=("event_closure:not_applicable_authorization",),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_frame_logic_to_fol_edge() -> PolicyModalEdge:
    """F-logic frames → FOL with explicit frame conditions."""

    edge_id = "frame_logic_to_fol"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "frame_logic",
            profile_id="frame_logic_core",
            fragment_id="flogic_frames",
            notation_id="flogic_surface",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_isa", "t_isa_pred", disposition=NodeDisposition.MAPPED),
            _node("n_frame_slot", "t_slot_pred", disposition=NodeDisposition.MAPPED),
            _node("n_molecule", "t_conj", disposition=NodeDisposition.MAPPED),
            _node(
                "n_inh_path",
                "t_trans_closure",
                disposition=NodeDisposition.APPROXIMATED,
                reason="inheritance paths lowered via explicit transitive axioms",
            ),
        ),
        symbol_map=(
            _symbol("isa", "isa", disposition=NodeDisposition.MAPPED),
            _symbol("slot", "has_slot", disposition=NodeDisposition.MAPPED),
            _symbol("self", "self_obj", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_isa",
            "n_frame_slot",
            "n_molecule",
            "n_inh_path",
        ),
        required_source_symbol_ids=("isa", "slot", "self"),
        feature_preconditions=(
            "feat_frame_molecules",
            "feat_isa_hierarchy",
            "feat_slot_attachments",
        ),
        unsupported_constructs=("feat_hilog_variables", "feat_unbounded_inheritance"),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:frame_isa_transitive",
                "axiom:frame_slot_functionality_optional",
            ),
            domain_changes=("domain:objects_and_classes_as_sorts",),
            other=("assumption:no_hilog",),
        ),
        description=(
            "Lowers F-logic molecules and isa/slot structure to many-sorted FOL "
            "with explicit frame inheritance axioms."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.RELATIONAL_FOL,
        frame_conditions=(
            "frame:isa_transitive",
            "frame:slot_attachment_well_typed",
            "frame:molecule_conjunction",
            "frame:no_hilog_variables",
        ),
        norm_semantics=("norm:not_applicable_frame_logic",),
        event_closure=("event_closure:not_applicable_frame_logic",),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_event_calculus_to_fol_edge() -> PolicyModalEdge:
    """Event calculus → FOL with explicit event/fluent closure."""

    edge_id = "event_calculus_to_fol"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "event_calculus",
            profile_id="event_calculus_discrete",
            fragment_id="ec_core_predicates",
            notation_id="event_calculus_surface",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_happens", "t_happens", disposition=NodeDisposition.PRESERVED),
            _node("n_holds_at", "t_holds_at", disposition=NodeDisposition.PRESERVED),
            _node("n_initiates", "t_initiates", disposition=NodeDisposition.PRESERVED),
            _node("n_terminates", "t_terminates", disposition=NodeDisposition.PRESERVED),
            _node(
                "n_clipped",
                "t_clipped_def",
                disposition=NodeDisposition.MAPPED,
            ),
            _node(
                "n_inertia",
                "t_inertia_axiom",
                disposition=NodeDisposition.SYNTHESIZED,
                reason="common-sense law of inertia emitted as explicit FOL axiom",
            ),
        ),
        symbol_map=(
            _symbol("happens", "happens", disposition=NodeDisposition.MAPPED),
            _symbol("holds_at", "holds_at", disposition=NodeDisposition.MAPPED),
            _symbol("initiates", "initiates", disposition=NodeDisposition.MAPPED),
            _symbol("terminates", "terminates", disposition=NodeDisposition.MAPPED),
            _symbol("clipped", "clipped", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_happens",
            "n_holds_at",
            "n_initiates",
            "n_terminates",
            "n_clipped",
            "n_inertia",
        ),
        required_source_symbol_ids=(
            "happens",
            "holds_at",
            "initiates",
            "terminates",
            "clipped",
        ),
        feature_preconditions=(
            "feat_events",
            "feat_fluents",
            "feat_time_points",
            "feat_initiates_terminates",
        ),
        unsupported_constructs=(
            "feat_continuous_time",
            "feat_probabilistic_events",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:discrete_time_linear",
                "axiom:common_sense_law_of_inertia",
            ),
            closure_assumptions=(
                "closure:event_occurrence_circumscribed",
                "closure:clipped_definitional",
            ),
            domain_changes=("domain:event_fluent_time_sorts",),
        ),
        description=(
            "Embeds discrete event calculus into FOL with explicit inertia and "
            "event-occurrence circumscription."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.RELATIONAL_FOL,
        frame_conditions=("frame:not_applicable_event_calculus",),
        norm_semantics=("norm:not_applicable_event_calculus",),
        event_closure=(
            "event_closure:common_sense_law_of_inertia",
            "event_closure:clipped_between_initiates_terminates",
            "event_closure:circumscribe_happens",
            "event_closure:discrete_time_points",
        ),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_event_calculus_to_atp_edge() -> PolicyModalEdge:
    """Event calculus → TPTP ATP encoding (reified time/event terms)."""

    edge_id = "event_calculus_to_atp"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "event_calculus",
            profile_id="event_calculus_discrete",
            fragment_id="ec_core_predicates",
            notation_id="event_calculus_surface",
        ),
        target=_endpoint(
            "first_order",
            profile_id="tptp_fof_atp",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
            schema_id="tptp_fof_schema",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_happens", "t_happens_fof", disposition=NodeDisposition.MAPPED),
            _node("n_holds_at", "t_holds_at_fof", disposition=NodeDisposition.MAPPED),
            _node("n_initiates", "t_initiates_fof", disposition=NodeDisposition.MAPPED),
            _node("n_terminates", "t_terminates_fof", disposition=NodeDisposition.MAPPED),
            _node(
                "n_trajectory",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="trajectory axioms out of controlled discrete subset",
            ),
        ),
        symbol_map=(
            _symbol("happens", "happens", disposition=NodeDisposition.MAPPED),
            _symbol("holds_at", "holds_at", disposition=NodeDisposition.MAPPED),
            _symbol("initiates", "initiates", disposition=NodeDisposition.MAPPED),
            _symbol("terminates", "terminates", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_happens",
            "n_holds_at",
            "n_initiates",
            "n_terminates",
            "n_trajectory",
        ),
        required_source_symbol_ids=("happens", "holds_at", "initiates", "terminates"),
        feature_preconditions=(
            "feat_events",
            "feat_fluents",
            "feat_time_points",
        ),
        unsupported_constructs=("feat_trajectory", "feat_continuous_change"),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:discrete_time_linear", "axiom:common_sense_law_of_inertia"),
            closure_assumptions=("closure:event_occurrence_circumscribed",),
            other=("assumption:tptp_fof_only",),
        ),
        description=(
            "Prints discrete event calculus as TPTP FOF for ATP backends with "
            "explicit inertia and unsupported trajectory disposition."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.ATP_TPTP,
        frame_conditions=("frame:not_applicable_event_calculus",),
        norm_semantics=("norm:not_applicable_event_calculus",),
        event_closure=(
            "event_closure:common_sense_law_of_inertia",
            "event_closure:circumscribe_happens",
            "event_closure:trajectory_unsupported",
        ),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.PREDICATE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_modal_s5_to_fol_relational_edge() -> PolicyModalEdge:
    """Alethic modal S5 → relational FOL (world quantifiers)."""

    edge_id = "modal_s5_to_fol_relational"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "modal",
            profile_id="modal_kripke_s5",
            fragment_id="modal_box_diamond",
            notation_id="canonical_modal",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_box", "t_forall_world", disposition=NodeDisposition.MAPPED),
            _node("n_diamond", "t_exists_world", disposition=NodeDisposition.MAPPED),
            _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
            _node("n_or", "t_or", disposition=NodeDisposition.PRESERVED),
            _node("n_not", "t_not", disposition=NodeDisposition.PRESERVED),
            _node("n_atom", "t_holds_world", disposition=NodeDisposition.MAPPED),
        ),
        symbol_map=(
            _symbol("box", "forall_accessible", disposition=NodeDisposition.MAPPED),
            _symbol("diamond", "exists_accessible", disposition=NodeDisposition.MAPPED),
            _symbol("r", "accessible", disposition=NodeDisposition.SYNTHESIZED),
        ),
        required_source_node_ids=(
            "n_box",
            "n_diamond",
            "n_and",
            "n_or",
            "n_not",
            "n_atom",
        ),
        required_source_symbol_ids=("box", "diamond", "r"),
        feature_preconditions=(
            "feat_box",
            "feat_diamond",
            "feat_boolean",
            "feat_kripke_frame_s5",
        ),
        unsupported_constructs=(
            "feat_dyadic_norms",
            "feat_defeasible_modal",
            "feat_first_order_modal_barcan",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:accessibility_equivalence_s5",
                "axiom:world_sort_nonempty",
            ),
            domain_changes=("domain:world_parameter_on_atoms",),
        ),
        description=(
            "Standard translation of S5 box/diamond to world-quantified FOL with "
            "explicit equivalence accessibility frame conditions."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.RELATIONAL_FOL,
        frame_conditions=(
            "frame:kripke_s5",
            "frame:accessibility_reflexive",
            "frame:accessibility_symmetric",
            "frame:accessibility_transitive",
            "frame:accessibility_euclidean",
        ),
        norm_semantics=("norm:not_applicable_alethic_modal",),
        event_closure=("event_closure:not_applicable_modal",),
        agent_indices=AgentIndexPolicy.FORBIDDEN,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_deontic_to_fol_reified_edge() -> PolicyModalEdge:
    """Monadic deontic O/P/F → reified FOL norms."""

    edge_id = "deontic_to_fol_reified"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "deontic",
            profile_id="deontic_monadic_strong",
            fragment_id="deontic_opf",
            notation_id="canonical_modal",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_obligation", "t_obligated_reified", disposition=NodeDisposition.MAPPED),
            _node("n_permission", "t_permitted_reified", disposition=NodeDisposition.MAPPED),
            _node("n_prohibition", "t_forbidden_reified", disposition=NodeDisposition.MAPPED),
            _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
            _node(
                "n_dyadic",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="dyadic norms fail closed under monadic profile",
            ),
            _node(
                "n_defeasible",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="defeasible/priority norms not admitted",
            ),
        ),
        symbol_map=(
            _symbol("o", "obligated", disposition=NodeDisposition.MAPPED),
            _symbol("p", "permitted", disposition=NodeDisposition.MAPPED),
            _symbol("f", "forbidden", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_obligation",
            "n_permission",
            "n_prohibition",
            "n_and",
            "n_dyadic",
            "n_defeasible",
        ),
        required_source_symbol_ids=("o", "p", "f"),
        feature_preconditions=(
            "feat_obligation",
            "feat_permission",
            "feat_prohibition",
            "feat_monadic_norms",
        ),
        unsupported_constructs=(
            "feat_dyadic_norms",
            "feat_defeasible_norms",
            "feat_contrary_to_duty",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:monadic_deontic_standard_sdl_fragment",
                "axiom:prohibition_as_obligation_negation",
            ),
            domain_changes=("domain:reified_norm_individuals",),
            other=("assumption:strong_permission_polarity",),
        ),
        description=(
            "Reifies monadic O/P/F as FOL predicates over formula codes; over-"
            "approximates ideal SDL obligations (no dyadic/defeasible norms)."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.REIFIED_FOL,
        frame_conditions=("frame:not_applicable_deontic_monadic",),
        norm_semantics=(
            "norm:monadic_obligation",
            "norm:monadic_permission_strong",
            "norm:monadic_prohibition",
            "norm:dyadic_unsupported",
            "norm:defeasible_unsupported",
        ),
        event_closure=("event_closure:not_applicable_deontic",),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.FORMULA,
        approximation_direction=ApproximationDirection.OVER,
        description=contract.description,
    )


def build_epistemic_to_fol_relational_edge() -> PolicyModalEdge:
    """Epistemic K[a] → multi-agent relational FOL."""

    edge_id = "epistemic_to_fol_relational"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "modal",
            profile_id="modal_epistemic_multi_agent",
            fragment_id="modal_knows",
            notation_id="canonical_modal",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_knows", "t_forall_agent_world", disposition=NodeDisposition.MAPPED),
            _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
            _node("n_not", "t_not", disposition=NodeDisposition.PRESERVED),
            _node("n_atom", "t_holds_world", disposition=NodeDisposition.MAPPED),
            _node(
                "n_common_knowledge",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="common knowledge fixed-point not in controlled fragment",
            ),
        ),
        symbol_map=(
            _symbol("k", "knows", disposition=NodeDisposition.MAPPED),
            _symbol("agent", "agent", disposition=NodeDisposition.PRESERVED),
            _symbol("r_a", "accessible_agent", disposition=NodeDisposition.SYNTHESIZED),
        ),
        required_source_node_ids=(
            "n_knows",
            "n_and",
            "n_not",
            "n_atom",
            "n_common_knowledge",
        ),
        required_source_symbol_ids=("k", "agent", "r_a"),
        feature_preconditions=(
            "feat_knows",
            "feat_agent_index",
            "feat_boolean",
            "feat_epistemic_s5_per_agent",
        ),
        unsupported_constructs=(
            "feat_common_knowledge",
            "feat_distributed_knowledge",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:per_agent_accessibility_equivalence",
                "axiom:agent_sort_finite_named",
            ),
            domain_changes=("domain:agent_indexed_accessibility",),
        ),
        description=(
            "Relational multi-agent epistemic translation: K[a]φ becomes "
            "∀w′. R(a,w,w′) → Holds(φ,w′) with explicit agent indices."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.RELATIONAL_FOL,
        frame_conditions=(
            "frame:epistemic_s5_per_agent",
            "frame:accessibility_reflexive_per_agent",
            "frame:accessibility_euclidean_per_agent",
        ),
        norm_semantics=("norm:not_applicable_epistemic",),
        event_closure=("event_closure:not_applicable_epistemic",),
        agent_indices=AgentIndexPolicy.MULTI_AGENT_INDEXED,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


def build_intention_to_fol_reified_edge() -> PolicyModalEdge:
    """Intention/BDI I[a] → reified FOL attitudes."""

    edge_id = "intention_to_fol_reified"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "modal",
            profile_id="modal_intention_agency",
            fragment_id="modal_intends",
            notation_id="canonical_modal",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_intends", "t_intends_reified", disposition=NodeDisposition.MAPPED),
            _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
            _node(
                "n_intention_persistence",
                "t_persist_axiom",
                disposition=NodeDisposition.APPROXIMATED,
                reason="intention persistence under-approximated without full BDI axioms",
            ),
            _node(
                "n_plan_library",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="plan libraries out of controlled intention fragment",
            ),
        ),
        symbol_map=(
            _symbol("i", "intends", disposition=NodeDisposition.MAPPED),
            _symbol("agent", "agent", disposition=NodeDisposition.PRESERVED),
        ),
        required_source_node_ids=(
            "n_intends",
            "n_and",
            "n_intention_persistence",
            "n_plan_library",
        ),
        required_source_symbol_ids=("i", "agent"),
        feature_preconditions=(
            "feat_intends",
            "feat_agent_index",
            "feat_boolean",
        ),
        unsupported_constructs=("feat_plan_library", "feat_full_bdi_commitments"),
        assumptions=TranslationAssumptionSet(
            axioms=("axiom:intention_consistency_weak",),
            domain_changes=("domain:reified_attitude_individuals",),
            other=("assumption:under_approx_intention_persistence",),
        ),
        description=(
            "Reifies agent-indexed intentions as FOL atoms; under-approximates "
            "persistence so only forced intentions are retained."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.REIFIED_FOL,
        frame_conditions=("frame:not_applicable_intention",),
        norm_semantics=("norm:not_applicable_intention",),
        event_closure=("event_closure:not_applicable_intention",),
        agent_indices=AgentIndexPolicy.REIFIED_AGENT_SORT,
        reification=ReificationKind.FULL,
        approximation_direction=ApproximationDirection.UNDER,
        description=contract.description,
    )


def build_dcec_to_fol_reified_edge() -> PolicyModalEdge:
    """DCEC (deontic + cognitive + event) → reified FOL."""

    edge_id = "dcec_to_fol_reified"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "dcec",
            profile_id="dcec_default",
            fragment_id="dcec_deontic_event_cognitive",
            notation_id="dcec_surface",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_obligation", "t_obligated", disposition=NodeDisposition.MAPPED),
            _node("n_knows", "t_knows", disposition=NodeDisposition.MAPPED),
            _node("n_happens", "t_happens", disposition=NodeDisposition.MAPPED),
            _node("n_holds_at", "t_holds_at", disposition=NodeDisposition.MAPPED),
            _node(
                "n_inertia",
                "t_inertia",
                disposition=NodeDisposition.SYNTHESIZED,
                reason="event closure axioms synthesized for DCEC fluents",
            ),
            _node(
                "n_full_shadowprover_dialect",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="vendor ShadowProver extensions out of controlled subset",
            ),
        ),
        symbol_map=(
            _symbol("o", "obligated", disposition=NodeDisposition.MAPPED),
            _symbol("k", "knows", disposition=NodeDisposition.MAPPED),
            _symbol("happens", "happens", disposition=NodeDisposition.MAPPED),
            _symbol("holds_at", "holds_at", disposition=NodeDisposition.MAPPED),
        ),
        required_source_node_ids=(
            "n_obligation",
            "n_knows",
            "n_happens",
            "n_holds_at",
            "n_inertia",
            "n_full_shadowprover_dialect",
        ),
        required_source_symbol_ids=("o", "k", "happens", "holds_at"),
        feature_preconditions=(
            "feat_deontic_norms",
            "feat_epistemic_knows",
            "feat_events",
            "feat_fluents",
            "feat_agent_index",
        ),
        unsupported_constructs=("feat_shadowprover_extensions",),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:dcec_component_composition",
                "axiom:common_sense_law_of_inertia",
            ),
            closure_assumptions=("closure:event_occurrence_circumscribed",),
            domain_changes=("domain:reified_norms_events_attitudes",),
        ),
        description=(
            "Composes deontic, epistemic, and event-calculus components of DCEC "
            "into reified FOL with explicit event closure and agent indices."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.REIFIED_FOL,
        frame_conditions=(
            "frame:epistemic_s5_per_agent",
            "frame:dcec_component_composition",
        ),
        norm_semantics=(
            "norm:monadic_obligation",
            "norm:dcec_deontic_component",
        ),
        event_closure=(
            "event_closure:common_sense_law_of_inertia",
            "event_closure:circumscribe_happens",
            "event_closure:dcec_fluent_persistence",
        ),
        agent_indices=AgentIndexPolicy.MULTI_AGENT_INDEXED,
        reification=ReificationKind.FULL,
        approximation_direction=ApproximationDirection.OVER,
        description=contract.description,
    )


def build_tdfol_to_fol_relational_edge() -> PolicyModalEdge:
    """TDFOL (temporal deontic FOL) → relational FOL with time + norms."""

    edge_id = "tdfol_to_fol_relational"
    contract = _contract(
        contract_id=edge_id,
        source=_endpoint(
            "tdfol",
            profile_id="tdfol_default",
            fragment_id="tdfol_temporal_deontic_fol",
            notation_id="tdfol_surface",
        ),
        target=_endpoint(
            "first_order",
            profile_id="fol_many_sorted",
            fragment_id="fol_quantifiers",
            notation_id="tptp_fof",
        ),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_forall_time", "t_forall_time", disposition=NodeDisposition.MAPPED),
            _node("n_obligation", "t_obligated_at", disposition=NodeDisposition.MAPPED),
            _node("n_until", "t_until_expanded", disposition=NodeDisposition.MAPPED),
            _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
            _node(
                "n_continuous_time",
                disposition=NodeDisposition.UNSUPPORTED,
                reason="continuous time not in discrete TDFOL fragment",
            ),
        ),
        symbol_map=(
            _symbol("o", "obligated_at", disposition=NodeDisposition.MAPPED),
            _symbol("p", "permitted_at", disposition=NodeDisposition.MAPPED),
            _symbol("u", "until", disposition=NodeDisposition.MAPPED),
            _symbol("time", "time", disposition=NodeDisposition.PRESERVED),
        ),
        required_source_node_ids=(
            "n_forall_time",
            "n_obligation",
            "n_until",
            "n_and",
            "n_continuous_time",
        ),
        required_source_symbol_ids=("o", "p", "u", "time"),
        feature_preconditions=(
            "feat_temporal_quantifiers",
            "feat_deontic_norms",
            "feat_first_order",
            "feat_discrete_time",
        ),
        unsupported_constructs=("feat_continuous_time", "feat_dyadic_norms"),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:discrete_linear_time",
                "axiom:monadic_deontic_at_time",
            ),
            domain_changes=("domain:time_sort_on_atoms",),
        ),
        description=(
            "Standard translation of discrete TDFOL into many-sorted FOL with "
            "explicit time parameters and monadic deontic-at-time norms."
        ),
    )
    return PolicyModalEdge(
        edge_id=edge_id,
        contract=contract,
        encoding_kind=EncodingKind.RELATIONAL_FOL,
        frame_conditions=(
            "frame:discrete_linear_time",
            "frame:tdfol_temporal_order",
        ),
        norm_semantics=(
            "norm:monadic_obligation_at_time",
            "norm:monadic_permission_at_time",
            "norm:dyadic_unsupported",
        ),
        event_closure=("event_closure:not_applicable_tdfol_relational",),
        agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
        reification=ReificationKind.NONE,
        approximation_direction=ApproximationDirection.NONE,
        description=contract.description,
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


_EDGE_BUILDERS: Final[tuple[Any, ...]] = (
    build_authorization_to_datalog_edge,
    build_authorization_to_secpal_edge,
    build_frame_logic_to_fol_edge,
    build_event_calculus_to_fol_edge,
    build_event_calculus_to_atp_edge,
    build_modal_s5_to_fol_relational_edge,
    build_deontic_to_fol_reified_edge,
    build_epistemic_to_fol_relational_edge,
    build_intention_to_fol_reified_edge,
    build_dcec_to_fol_reified_edge,
    build_tdfol_to_fol_relational_edge,
)


def iter_policy_modal_edges() -> tuple[PolicyModalEdge, ...]:
    """Return all reviewed policy/modal edges in stable edge_id order."""

    edges = tuple(builder() for builder in _EDGE_BUILDERS)
    return tuple(sorted(edges, key=lambda edge: edge.edge_id))


def policy_modal_contracts() -> tuple[TranslationContract, ...]:
    """Return planner-ready :class:`TranslationContract` values only."""

    return tuple(edge.contract for edge in iter_policy_modal_edges())


def get_policy_modal_edge(edge_id: str) -> PolicyModalEdge:
    """Look up one reviewed edge by id (fail closed on unknown)."""

    key = _identifier(edge_id, "edge_id")
    for edge in iter_policy_modal_edges():
        if edge.edge_id == key:
            return edge
    raise PolicyModalTranslationError(f"unknown policy/modal edge {key!r}")


@dataclass(frozen=True, slots=True)
class PolicyModalTranslationEdges:
    """Catalog of reviewed policy/modal edges (``PolicyModalTranslationEdges@1``).

    The catalog is the admission surface for the translation planner: every
    edge is feature-preconditioned, loss-receipted, and carries explicit frame
    conditions, norm semantics, event closure, agent indices, reification, and
    approximation direction.
    """

    edges: tuple[PolicyModalEdge, ...] = field(default_factory=iter_policy_modal_edges)
    schema_version: str = POLICY_MODAL_CATALOG_SCHEMA_VERSION
    catalog_content_id: str = ""

    interface: ClassVar[str] = POLICY_MODAL_EDGES_INTERFACE

    def __post_init__(self) -> None:
        edges = self.edges
        if isinstance(edges, (str, bytes, bytearray)) or not isinstance(edges, Sequence):
            raise PolicyModalTranslationError("edges must be a sequence")
        normalized: list[PolicyModalEdge] = []
        seen: set[str] = set()
        for item in edges:
            if isinstance(item, Mapping):
                item = PolicyModalEdge.from_dict(item)
            if not isinstance(item, PolicyModalEdge):
                raise PolicyModalTranslationError(
                    "edges items must be PolicyModalEdge values"
                )
            if item.edge_id in seen:
                raise PolicyModalTranslationError(
                    f"duplicate policy/modal edge_id {item.edge_id!r}"
                )
            seen.add(item.edge_id)
            normalized.append(item)
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(normalized, key=lambda edge: edge.edge_id)),
        )
        if self.schema_version != POLICY_MODAL_CATALOG_SCHEMA_VERSION:
            raise PolicyModalTranslationError(
                f"unsupported catalog schema {self.schema_version!r}"
            )
        self._validate_coverage()
        computed = self._compute_identity()
        if self.catalog_content_id and self.catalog_content_id != computed.cid:
            raise PolicyModalTranslationError(
                "catalog_content_id does not match canonical catalog content"
            )
        object.__setattr__(self, "catalog_content_id", computed.cid)

    def _validate_coverage(self) -> None:
        """Ensure evidence-subset families appear as sources."""

        required_sources = {
            "authorization",
            "frame_logic",
            "event_calculus",
            "deontic",
            "modal",
            "dcec",
            "tdfol",
        }
        present = {edge.source_family_id for edge in self.edges}
        missing = sorted(required_sources - present)
        if missing:
            raise PolicyModalTranslationError(
                "policy/modal catalog missing source families: " + ", ".join(missing)
            )
        # Epistemic and intention are modal profiles, not separate families.
        profiles = {edge.contract.source.profile_id for edge in self.edges}
        if not any("epistemic" in profile for profile in profiles):
            raise PolicyModalTranslationError(
                "policy/modal catalog requires an epistemic modal profile edge"
            )
        if not any("intention" in profile for profile in profiles):
            raise PolicyModalTranslationError(
                "policy/modal catalog requires an intention modal profile edge"
            )

        for edge in self.edges:
            # Every edge must surface all six acceptance axes in its dict form.
            payload = edge.to_dict()
            for axis in (
                "frame_conditions",
                "norm_semantics",
                "event_closure",
                "agent_indices",
                "reification",
                "approximation_direction",
            ):
                if axis not in payload:
                    raise PolicyModalTranslationError(
                        f"edge {edge.edge_id!r} omits acceptance axis {axis!r}"
                    )
                if payload[axis] is None or payload[axis] == "":
                    raise PolicyModalTranslationError(
                        f"edge {edge.edge_id!r} has empty acceptance axis {axis!r}"
                    )

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            {
                "edges": [edge.edge_content_id for edge in self.edges],
                "interface": self.interface,
                "schema_version": self.schema_version,
            },
            domain=POLICY_MODAL_CATALOG_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.catalog_content_id

    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    def contracts(self) -> tuple[TranslationContract, ...]:
        return tuple(edge.contract for edge in self.edges)

    def get(self, edge_id: str) -> PolicyModalEdge:
        key = _identifier(edge_id, "edge_id")
        for edge in self.edges:
            if edge.edge_id == key:
                return edge
        raise PolicyModalTranslationError(f"unknown policy/modal edge {key!r}")

    def edges_from(self, family_id: str) -> tuple[PolicyModalEdge, ...]:
        family = _identifier(family_id, "family_id")
        return tuple(
            edge for edge in self.edges if edge.source_family_id == family
        )

    def edges_to(self, family_id: str) -> tuple[PolicyModalEdge, ...]:
        family = _identifier(family_id, "family_id")
        return tuple(
            edge for edge in self.edges if edge.target_family_id == family
        )

    def register_with_planner(
        self, planner: TranslationPathPlanner | None = None
    ) -> TranslationPathPlanner:
        """Register all catalog contracts with a path planner."""

        target = planner if planner is not None else TranslationPathPlanner()
        if not isinstance(target, TranslationPathPlanner):
            raise PolicyModalTranslationError(
                "planner must be a TranslationPathPlanner"
            )
        try:
            target.register_edges(self.contracts())
        except TranslationPathPlannerError as error:
            raise PolicyModalTranslationError(
                f"failed to register policy/modal edges: {error}"
            ) from error
        return target

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_content_id": self.catalog_content_id,
            "edges": [edge.to_dict() for edge in self.edges],
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyModalTranslationEdges":
        value = _mapping(value, "policy/modal catalog")
        _reject_unknown(
            value,
            frozenset(
                {
                    "catalog_content_id",
                    "edges",
                    "interface",
                    "schema_version",
                }
            ),
            "policy/modal catalog",
        )
        interface = value.get("interface", POLICY_MODAL_EDGES_INTERFACE)
        if interface != POLICY_MODAL_EDGES_INTERFACE:
            raise PolicyModalTranslationError(
                f"unsupported catalog interface {interface!r}"
            )
        return cls(
            edges=tuple(value.get("edges", ())),  # type: ignore[arg-type]
            schema_version=value.get(
                "schema_version", POLICY_MODAL_CATALOG_SCHEMA_VERSION
            ),
            catalog_content_id=value.get("catalog_content_id", ""),
        )

    @classmethod
    def reviewed(cls) -> "PolicyModalTranslationEdges":
        """Return the sealed reviewed catalog."""

        return cls()


def build_policy_modal_translation_edges() -> PolicyModalTranslationEdges:
    """Construct the reviewed ``PolicyModalTranslationEdges@1`` catalog."""

    return PolicyModalTranslationEdges.reviewed()


__all__ = [
    "AgentIndexPolicy",
    "ApproximationDirection",
    "EncodingKind",
    "POLICY_MODAL_CATALOG_SCHEMA_VERSION",
    "POLICY_MODAL_EDGES_INTERFACE",
    "POLICY_MODAL_EDGE_SCHEMA_VERSION",
    "POLICY_MODAL_MODULE_VERSION",
    "PolicyModalEdge",
    "PolicyModalTranslationEdges",
    "PolicyModalTranslationError",
    "ReificationKind",
    "build_authorization_to_datalog_edge",
    "build_authorization_to_secpal_edge",
    "build_dcec_to_fol_reified_edge",
    "build_deontic_to_fol_reified_edge",
    "build_epistemic_to_fol_relational_edge",
    "build_event_calculus_to_atp_edge",
    "build_event_calculus_to_fol_edge",
    "build_frame_logic_to_fol_edge",
    "build_intention_to_fol_reified_edge",
    "build_modal_s5_to_fol_relational_edge",
    "build_policy_modal_translation_edges",
    "build_tdfol_to_fol_relational_edge",
    "get_policy_modal_edge",
    "iter_policy_modal_edges",
    "policy_modal_contracts",
]
