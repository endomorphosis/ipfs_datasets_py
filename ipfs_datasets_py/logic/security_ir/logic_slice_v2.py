"""End-to-end Security IR domain logic slice (``SecurityLogicSlice@2``).

Connects admitted Security IR views through a single typed vertical path:

    typed origin → semantics → translation → request → result → replay
    → authority lineage

Admitted routes (aligned with ``ADMITTED_SECURITY_VIEW_NAMES``):

* threat models and state/transition obligations
* authorization / policy authority
* FOL / CHC verification-condition claims
* temporal properties
* cryptographic protocols (attacker semantics explicit)
* noninterference / information-flow hyperproperties
* separation and concurrency

Every admitted route carries source-span-to-result lineage.  Information-flow,
attacker, bound, and policy-authority assumptions are explicit on the route
descriptor and appear on the domain slice / obligation assumption set.

Hermetic fixtures supply provider execution and replay without requiring live
provers.  Tool absence remains an availability result, not a mock proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.artifacts_v2 import (
    CompiledLogicArtifact,
    ParsedTargetArtifact,
    admit_compiled_target,
    admit_parsed_result,
)
from ipfs_datasets_py.logic.backends.evidence_v2 import (
    EvidenceReplayReceipt,
    ExecutionOutcome,
    ExecutionRecordKind,
    ProviderExecutionReceiptV2,
    ReplayDisposition,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    LogicObligationV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    encoding_id,
    evidence_id,
    notation_id,
    property_id,
    provider_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DomainLogicSliceV2,
)
from ipfs_datasets_py.logic.security_ir.formalization_adapter_v2 import (
    ADMITTED_SECURITY_VIEW_NAMES,
    SECURITY_IR_DOMAIN_ID,
    resolve_security_route,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_extension
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    content_sha256,
    canonical_json_bytes,
)
from ipfs_datasets_py.logic.syntax_core.signatures import LogicSignature
from ipfs_datasets_py.logic.translations.catalog import (
    LogicTranslationGraph,
    build_logic_translation_graph,
)
from ipfs_datasets_py.logic.translations.hyper import (
    build_hyperproperty_translation_edges,
)
from ipfs_datasets_py.logic.translations.policy_modal import (
    build_policy_modal_translation_edges,
)
from ipfs_datasets_py.logic.translations.program import (
    build_program_translation_edges,
)
from ipfs_datasets_py.logic.translations.protocol_targets import (
    build_protocol_target_translation_edges,
)
from ipfs_datasets_py.logic.translations.state_temporal import (
    build_state_temporal_edges,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SECURITY_LOGIC_SLICE_INTERFACE: Final = "SecurityLogicSlice@2"
SECURITY_LOGIC_SLICE_SCHEMA: Final = "security-logic-slice/v2"
SECURITY_LOGIC_SLICE_VERSION: Final = "2.0.0"
OBLIGATION_LINEAGE_SCHEMA: Final = "security-obligation-lineage/v2"
DOMAIN_ID: Final = SECURITY_IR_DOMAIN_ID

# Required lineage stages for every admitted route (acceptance criterion).
LINEAGE_STAGES: Final[tuple[str, ...]] = (
    "typed_origin",
    "semantics",
    "translation",
    "request",
    "result",
    "replay",
    "authority_lineage",
)

# Explicit assumption categories required by LFP2-022 acceptance.
ASSUMPTION_CATEGORIES: Final[tuple[str, ...]] = (
    "information_flow",
    "attacker",
    "bound",
    "policy_authority",
)

# Operation / view roles that are never executable domain routes here.
DEFERRED_ROUTE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "verification_condition",
        "graph_projection",
        "proof_translation",
        "free_form",
        "boolean_receipt",
    }
)


class SecuritySliceError(ValueError):
    """Raised when a Security IR logic slice cannot be admitted."""


class ObligationLineageError(SecuritySliceError):
    """Raised when required lineage stages are missing or inconsistent."""


class UnsupportedRouteError(SecuritySliceError):
    """Raised for routes outside the admitted Security IR set."""


class SecurityRouteKind(StrEnum):
    """Admitted Security IR route classes connected end to end by this slice."""

    THREAT = "threat"
    AUTHORIZATION = "authorization"
    CLAIM = "claim"
    STATE = "state"
    TEMPORAL = "temporal"
    PROTOCOL = "protocol"
    NONINTERFERENCE = "noninterference"
    SEPARATION = "separation"
    CONCURRENCY = "concurrency"


SUPPORTED_ROUTE_KINDS: Final[tuple[SecurityRouteKind, ...]] = (
    SecurityRouteKind.THREAT,
    SecurityRouteKind.AUTHORIZATION,
    SecurityRouteKind.CLAIM,
    SecurityRouteKind.STATE,
    SecurityRouteKind.TEMPORAL,
    SecurityRouteKind.PROTOCOL,
    SecurityRouteKind.NONINTERFERENCE,
    SecurityRouteKind.SEPARATION,
    SecurityRouteKind.CONCURRENCY,
)


# Ensure the executable slice stays aligned with the formalization adapter.
assert tuple(item.value for item in SUPPORTED_ROUTE_KINDS) == tuple(
    ADMITTED_SECURITY_VIEW_NAMES
)


@dataclass(frozen=True, slots=True)
class ExplicitAssumptions:
    """Closed assumption axes required for every admitted security route.

    Empty tuples are allowed only when the axis is not applicable; the
    descriptor still declares the axis so omission is never silent.
    """

    information_flow: tuple[str, ...]
    attacker: tuple[str, ...]
    bound: tuple[str, ...]
    policy_authority: tuple[str, ...]

    def all_ids(self) -> tuple[str, ...]:
        """Flatten unique assumption ids in stable category order."""

        ordered: list[str] = []
        seen: set[str] = set()
        for group in (
            self.information_flow,
            self.attacker,
            self.bound,
            self.policy_authority,
        ):
            for item in group:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker": list(self.attacker),
            "bound": list(self.bound),
            "information_flow": list(self.information_flow),
            "policy_authority": list(self.policy_authority),
        }


@dataclass(frozen=True, slots=True)
class ObligationRouteDescriptor:
    """Static routing metadata for one admitted Security IR route class."""

    kind: SecurityRouteKind
    family_id: str
    profile_id: str
    property_name: str
    view_name: str
    notation_name: str
    encoding_name: str
    evidence_name: str
    provider_name: str
    authority_ceiling: RequestAuthorityCeiling
    result_authority: ResultAuthority
    translation_edge_id: str
    translation_family: str
    compiler_id: str
    result_kind: str
    statement: str
    target_text: str
    result_output: str
    assumptions: ExplicitAssumptions
    features: tuple[str, ...] = ()
    notes: str = ""
    security_route_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SecurityRouteKind):
            object.__setattr__(self, "kind", SecurityRouteKind(self.kind))
        if not isinstance(self.authority_ceiling, RequestAuthorityCeiling):
            object.__setattr__(
                self,
                "authority_ceiling",
                RequestAuthorityCeiling(self.authority_ceiling),
            )
        if not isinstance(self.result_authority, ResultAuthority):
            object.__setattr__(
                self, "result_authority", ResultAuthority(self.result_authority)
            )
        if not isinstance(self.assumptions, ExplicitAssumptions):
            raise SecuritySliceError(
                f"route {self.kind.value!r} requires ExplicitAssumptions"
            )
        # Axes must be declared (possibly empty) so omission is never silent.
        for axis in ASSUMPTION_CATEGORIES:
            if not hasattr(self.assumptions, axis):
                raise SecuritySliceError(
                    f"route {self.kind.value!r} missing assumption axis {axis!r}"
                )

    @property
    def assumption_ids(self) -> tuple[str, ...]:
        return self.assumptions.all_ids()


def default_obligation_routes() -> Mapping[
    SecurityRouteKind, ObligationRouteDescriptor
]:
    """Return the sealed admitted-route table for Security IR."""

    rows: tuple[ObligationRouteDescriptor, ...] = (
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.THREAT,
            family_id="transition_system",
            profile_id="threat_model",
            property_name="attacker_reachability",
            view_name="threat",
            notation_name="security_threat_model",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="transition_system_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="security.threat.bounded_smt",
            result_kind="model_check.satisfied",
            statement=(
                "Check threat-model attacker reachability under declared "
                "environment bounds and attacker identity."
            ),
            target_text="(assert (not threat_invariant))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(
                    "assumption:attacker_identity",
                    "assumption:environment_boundary",
                    "assumption:assumption_polarity",
                ),
                bound=(
                    "bound:state_space",
                    "bound:attacker_steps",
                ),
                policy_authority=(),
            ),
            features=("security_ir.threat", "transition_system.threat_model"),
            notes="Threat routes keep attacker and environment bounds explicit.",
            security_route_id="security-route/threat/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.AUTHORIZATION,
            family_id="authorization",
            profile_id="secpal",
            property_name="authorization",
            view_name="policy",
            notation_name="secpal_surface",
            encoding_name="datalog",
            evidence_name="authorization",
            provider_name="datalog_secpal",
            authority_ceiling=RequestAuthorityCeiling.AUTHORIZATION,
            result_authority=ResultAuthority.AUTHORIZATION,
            translation_edge_id="authorization_to_secpal",
            translation_family="policy_modal",
            compiler_id="security.authorization.secpal",
            result_kind="authorization.allow",
            statement=(
                "Evaluate SecPAL/Datalog authorization under explicit policy "
                "authority, principal identity, and delegation scope."
            ),
            target_text="says(Admin, can(User, action))",
            result_output="allow",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(),
                bound=(),
                policy_authority=(
                    "assumption:policy_authority_bound",
                    "assumption:principal_identity",
                    "assumption:delegation_scope",
                    "assumption:world_policy",
                    "assumption:effect_polarity",
                ),
            ),
            features=("security_ir.authorization", "authorization.secpal"),
            notes=(
                "Policy authority is never upgraded by mock authorization output."
            ),
            security_route_id="security-route/authorization/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.CLAIM,
            family_id="first_order",
            profile_id="verification_condition",
            property_name="validity",
            view_name="claim",
            notation_name="security_claim",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="security.claim.smtlib2",
            result_kind="satisfiability.unsat",
            statement=(
                "Discharge a Security IR verification-condition claim by "
                "theorem-by-negation SMT query."
            ),
            target_text="(assert (not claim_goal))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(),
                bound=("bound:quantifier_instantiations",),
                policy_authority=(),
            ),
            features=("security_ir.claim", "first_order.verification_condition"),
            notes="VC is a view role under first_order; never a family.",
            security_route_id="security-route/claim-fol/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.STATE,
            family_id="transition_system",
            profile_id="default",
            property_name="invariant",
            view_name="transition",
            notation_name="security_state",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="transition_system_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="security.state.bounded_smt",
            result_kind="model_check.satisfied",
            statement=(
                "Check finite-state security invariant under declared domain "
                "bounds."
            ),
            target_text="(assert (not security_invariant))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(),
                bound=(
                    "assumption:finite_domain",
                    "bound:state_space",
                    "bound:transition_depth",
                ),
                policy_authority=(),
            ),
            features=("security_ir.state", "transition_system.state"),
            notes="Finite/infinite bounds remain explicit.",
            security_route_id="security-route/transition/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.TEMPORAL,
            family_id="temporal",
            profile_id="ltl",
            property_name="safety",
            view_name="transition",
            notation_name="ltl_surface",
            encoding_name="tla_plus",
            evidence_name="bounded",
            provider_name="tla_tlc",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="temporal_ltl_to_tla_plus",
            translation_family="state_temporal",
            compiler_id="security.temporal.tla_plus",
            result_kind="model_check.satisfied",
            statement=(
                "Model-check temporal safety under fairness and bound-depth "
                "receipts."
            ),
            target_text="[] security_safe",
            result_output="satisfied",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(),
                bound=(
                    "bound:trace_length",
                    "bound:bound_depth",
                    "assumption:fairness_constraint",
                ),
                policy_authority=(),
            ),
            features=("security_ir.temporal", "temporal.ltl"),
            notes="Trace model, fairness, and bounds cannot be omitted.",
            security_route_id="security-route/temporal/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.PROTOCOL,
            family_id="cryptographic_protocol",
            profile_id="default",
            property_name="secrecy",
            view_name="protocol",
            notation_name="symbolic_protocol",
            encoding_name="proverif_pv",
            evidence_name="attack",
            provider_name="proverif",
            authority_ceiling=RequestAuthorityCeiling.PROTOCOL,
            result_authority=ResultAuthority.PROTOCOL,
            translation_edge_id="symbolic_protocol_to_proverif_applied_pi",
            translation_family="protocol_target",
            compiler_id="security.protocol.proverif",
            result_kind="protocol.secrecy.holds",
            statement=(
                "Analyze protocol secrecy under Dolev-Yao attacker semantics "
                "and dialect-specific equations, roles, and channels."
            ),
            target_text="query attacker(secret).",
            result_output="not attacker(secret).",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(
                    "attacker:dolev_yao",
                    "attacker:perfect_cryptography",
                    "attacker:public_network",
                    "assumption:role_identity",
                    "assumption:channel_identity",
                    "assumption:equational_theory",
                ),
                bound=("bound:protocol_sessions",),
                policy_authority=(),
            ),
            features=(
                "security_ir.protocol",
                "cryptographic_protocol.symbolic",
            ),
            notes="Attacker semantics remain dialect-specific and receipted.",
            security_route_id="security-route/protocol/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.NONINTERFERENCE,
            family_id="hyperproperty",
            profile_id="noninterference",
            property_name="noninterference",
            view_name="hyperproperty",
            notation_name="hyperltl_surface",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.HYPERPROPERTY,
            translation_edge_id="noninterference_to_self_composition",
            translation_family="hyper",
            compiler_id="security.noninterference.self_composition",
            result_kind="hyperproperty.noninterference.holds",
            statement=(
                "Check noninterference via bounded self-composition with "
                "explicit high/low partition and alternation bound."
            ),
            target_text="(assert (not noninterference))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                information_flow=(
                    "assumption:high_low_partition",
                    "assumption:observation_equivalence",
                    "assumption:hypertrace_quantifier",
                    "assumption:information_flow_explicit",
                ),
                attacker=(),
                bound=(
                    "bound:system_copies",
                    "bound:trace_steps",
                    "assumption:alternation_bound",
                ),
                policy_authority=(),
            ),
            features=(
                "security_ir.noninterference",
                "hyperproperty.noninterference",
            ),
            notes=(
                "Noninterference is a property under hyperproperty, never a family."
            ),
            security_route_id="security-route/noninterference/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.SEPARATION,
            family_id="separation_logic",
            profile_id="default",
            property_name="frame",
            view_name="separation",
            notation_name="separation_surface",
            encoding_name="smtlib2",
            evidence_name="candidate",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="separation_to_smt",
            translation_family="program",
            compiler_id="security.separation.smtlib2",
            result_kind="candidate.frame",
            statement=(
                "Preserve separation-logic frame formula outside the command "
                "footprint; heap/resource loss remains explicit."
            ),
            target_text="(assert (not frame_preserved))",
            result_output="candidate",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(),
                bound=("bound:heap_locations",),
                policy_authority=(),
            ),
            features=("security_ir.separation", "separation_logic.frame"),
            notes="Heap/resource losses stay on the translation edge.",
            security_route_id="security-route/separation/v1",
        ),
        ObligationRouteDescriptor(
            kind=SecurityRouteKind.CONCURRENCY,
            family_id="concurrency",
            profile_id="default",
            property_name="rely_guarantee",
            view_name="concurrency",
            notation_name="concurrency_ir",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="concurrency_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="security.concurrency.bounded_smt",
            result_kind="model_check.satisfied",
            statement=(
                "Check rely/guarantee under explicit interference, fairness, "
                "and interleaving bounds."
            ),
            target_text="(assert (not rely_guarantee))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                information_flow=(),
                attacker=(),
                bound=(
                    "bound:interleavings",
                    "assumption:interference_declared",
                    "assumption:weak_fairness",
                ),
                policy_authority=(),
            ),
            features=("security_ir.concurrency", "concurrency.rely_guarantee"),
            notes="Interference and interleaving bounds cannot be omitted.",
            security_route_id="security-route/concurrency/v1",
        ),
    )
    return MappingProxyType({item.kind: item for item in rows})


# ---------------------------------------------------------------------------
# Lineage records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedOriginLineage:
    """Exact source and typed-expression identity for one route."""

    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    domain_slice_id: str
    domain_slice_digest: str
    route_kind: str
    source_range: SourceRange | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "domain_slice_digest": self.domain_slice_digest,
            "domain_slice_id": self.domain_slice_id,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "route_kind": self.route_kind,
            "source_digest": self.source_digest,
            "source_range": None
            if self.source_range is None
            else self.source_range.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticsLineage:
    """Typed semantic namespaces for one route."""

    family: str
    profile: str
    property: str
    view: str
    notation: str
    features: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    statement: str
    assumptions: ExplicitAssumptions
    domain: str = DOMAIN_ID
    security_route_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "assumptions": self.assumptions.to_dict(),
            "domain": self.domain,
            "family": self.family,
            "features": list(self.features),
            "notation": self.notation,
            "profile": self.profile,
            "property": self.property,
            "security_route_id": self.security_route_id,
            "statement": self.statement,
            "view": self.view,
        }


@dataclass(frozen=True, slots=True)
class TranslationLineage:
    """Reviewed translation edge binding for one route."""

    edge_id: str
    family_key: str
    source_family_id: str
    target_family_id: str
    preservation: str
    authority_ceiling: str
    compiler_id: str
    content_id: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "compiler_id": self.compiler_id,
            "content_id": self.content_id,
            "description": self.description,
            "edge_id": self.edge_id,
            "family_key": self.family_key,
            "preservation": self.preservation,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
        }


@dataclass(frozen=True, slots=True)
class RequestLineage:
    """BackendRequest@2 / LogicObligation@2 identities."""

    obligation_id: str
    obligation_digest: str
    request_id: str
    request_digest: str
    encoding: str
    evidence_kind: str
    provider: str
    authority_ceiling: str
    bounds: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "bounds": dict(self.bounds),
            "encoding": self.encoding,
            "evidence_kind": self.evidence_kind,
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "provider": self.provider,
            "request_digest": self.request_digest,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class ResultLineage:
    """Compiled/parsed result identities and authority."""

    compiled_artifact_id: str
    compiled_artifact_digest: str
    parsed_artifact_id: str
    parsed_artifact_digest: str
    result_kind: str
    result_authority: str
    output_digest: str
    result_digest: str
    decoded_evidence_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiled_artifact_digest": self.compiled_artifact_digest,
            "compiled_artifact_id": self.compiled_artifact_id,
            "decoded_evidence_digest": self.decoded_evidence_digest,
            "output_digest": self.output_digest,
            "parsed_artifact_digest": self.parsed_artifact_digest,
            "parsed_artifact_id": self.parsed_artifact_id,
            "result_authority": self.result_authority,
            "result_digest": self.result_digest,
            "result_kind": self.result_kind,
        }


@dataclass(frozen=True, slots=True)
class ReplayLineage:
    """Execution and evidence-replay receipt identities."""

    execution_receipt_id: str
    execution_receipt_digest: str
    replay_receipt_id: str
    replay_receipt_digest: str
    record_kind: str
    disposition: str
    replay_claimed: bool
    match_digest: str
    launch_id: str
    tool_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "execution_receipt_digest": self.execution_receipt_digest,
            "execution_receipt_id": self.execution_receipt_id,
            "launch_id": self.launch_id,
            "match_digest": self.match_digest,
            "record_kind": self.record_kind,
            "replay_claimed": self.replay_claimed,
            "replay_receipt_digest": self.replay_receipt_digest,
            "replay_receipt_id": self.replay_receipt_id,
            "tool_id": self.tool_id,
        }


@dataclass(frozen=True, slots=True)
class AuthorityStage:
    """One stage in the ordered authority lineage chain."""

    stage: str
    identity: str
    digest: str
    authority_ceiling: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "digest": self.digest,
            "identity": self.identity,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class AuthorityLineage:
    """Ordered authority chain from origin through replay."""

    stages: tuple[AuthorityStage, ...]
    terminal_authority: str
    never_upgrades: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "never_upgrades": self.never_upgrades,
            "stages": [item.to_dict() for item in self.stages],
            "terminal_authority": self.terminal_authority,
        }


@dataclass(frozen=True, slots=True)
class ObligationLineageBundle:
    """Complete end-to-end lineage for one admitted security route."""

    obligation_kind: SecurityRouteKind | str
    typed_origin: TypedOriginLineage
    semantics: SemanticsLineage
    translation: TranslationLineage
    request: RequestLineage
    result: ResultLineage
    replay: ReplayLineage
    authority_lineage: AuthorityLineage
    domain_slice: DomainLogicSliceV2
    obligation: LogicObligationV2
    backend_request: BackendRequestV2
    compiled: CompiledLogicArtifact
    parsed: ParsedTargetArtifact
    execution: ProviderExecutionReceiptV2
    replay_receipt: EvidenceReplayReceipt
    expression: TypedExpression
    document: SourceDocument
    content_digest: str = ""
    schema_version: str = OBLIGATION_LINEAGE_SCHEMA
    notes: str = ""

    interface: ClassVar[str] = SECURITY_LOGIC_SLICE_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.obligation_kind, SecurityRouteKind):
            object.__setattr__(
                self,
                "obligation_kind",
                SecurityRouteKind(self.obligation_kind),
            )
        if self.schema_version != OBLIGATION_LINEAGE_SCHEMA:
            raise ObligationLineageError(
                f"unsupported obligation lineage schema {self.schema_version!r}"
            )
        missing = [
            stage
            for stage in LINEAGE_STAGES
            if getattr(self, stage if stage != "typed_origin" else "typed_origin")
            is None
        ]
        if missing:
            raise ObligationLineageError(
                f"obligation lineage missing stages: {', '.join(missing)}"
            )
        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            if self.content_digest != content:
                raise ObligationLineageError(
                    "content_digest does not match obligation lineage payload"
                )
            object.__setattr__(self, "content_digest", self.content_digest)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "authority_lineage": self.authority_lineage.to_dict(),
            "interface": self.interface,
            "notes": self.notes,
            "obligation_kind": self.obligation_kind.value,
            "replay": self.replay.to_dict(),
            "request": self.request.to_dict(),
            "result": self.result.to_dict(),
            "schema_version": self.schema_version,
            "semantics": self.semantics.to_dict(),
            "translation": self.translation.to_dict(),
            "typed_origin": self.typed_origin.to_dict(),
        }

    def require_complete_lineage(self) -> "ObligationLineageBundle":
        """Fail closed when any required lineage stage is empty or unbound."""

        stages = {
            "typed_origin": self.typed_origin,
            "semantics": self.semantics,
            "translation": self.translation,
            "request": self.request,
            "result": self.result,
            "replay": self.replay,
            "authority_lineage": self.authority_lineage,
        }
        for name, value in stages.items():
            if value is None:
                raise ObligationLineageError(f"missing lineage stage {name!r}")
        if not self.typed_origin.source_digest or not self.typed_origin.expression_digest:
            raise ObligationLineageError(
                "typed origin requires source_digest and expression_digest"
            )
        if self.typed_origin.source_range is None:
            raise ObligationLineageError(
                "typed origin requires source_range for source-span-to-result lineage"
            )
        if not self.translation.edge_id or not self.translation.content_id:
            raise ObligationLineageError(
                "translation lineage requires edge_id and content_id"
            )
        if not self.request.request_digest or not self.request.obligation_digest:
            raise ObligationLineageError(
                "request lineage requires request and obligation digests"
            )
        if not self.result.parsed_artifact_digest:
            raise ObligationLineageError(
                "result lineage requires parsed artifact digest"
            )
        if not self.replay.replay_receipt_digest:
            raise ObligationLineageError(
                "replay lineage requires replay receipt digest"
            )
        if len(self.authority_lineage.stages) < len(LINEAGE_STAGES):
            raise ObligationLineageError(
                "authority lineage must cover every required stage"
            )
        stage_names = tuple(item.stage for item in self.authority_lineage.stages)
        for required in LINEAGE_STAGES:
            if required not in stage_names:
                raise ObligationLineageError(
                    f"authority lineage missing stage {required!r}"
                )
        # Source → request → result digests must remain coherent.
        if self.backend_request.source_digest != self.typed_origin.source_digest:
            raise ObligationLineageError(
                "backend request source_digest diverged from typed origin"
            )
        if self.backend_request.expression_digest != self.typed_origin.expression_digest:
            raise ObligationLineageError(
                "backend request expression_digest diverged from typed origin"
            )
        if self.execution.request_digest != self.backend_request.content_digest:
            raise ObligationLineageError(
                "execution receipt request_digest diverged from backend request"
            )
        if self.replay_receipt.execution_receipt_digest != self.execution.content_digest:
            raise ObligationLineageError(
                "replay receipt is not bound to the execution receipt"
            )
        # Explicit assumption axes must remain present on the semantics record.
        assumptions = self.semantics.assumptions
        for axis in ASSUMPTION_CATEGORIES:
            if not hasattr(assumptions, axis):
                raise ObligationLineageError(
                    f"semantics missing explicit assumption axis {axis!r}"
                )
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["domain_slice_id"] = self.domain_slice.slice_id
        payload["expression_id"] = self.expression.expression_id
        payload["request_id"] = self.backend_request.request_id
        return payload


@dataclass(frozen=True, slots=True)
class SecurityLogicSlice:
    """Compose admitted Security IR routes end to end.

    Interface: ``SecurityLogicSlice@2``.
    """

    INTERFACE: ClassVar[str] = SECURITY_LOGIC_SLICE_INTERFACE
    VERSION: ClassVar[str] = SECURITY_LOGIC_SLICE_VERSION
    SCHEMA_VERSION: ClassVar[str] = SECURITY_LOGIC_SLICE_SCHEMA

    routes: Mapping[SecurityRouteKind, ObligationRouteDescriptor] = field(
        default_factory=default_obligation_routes
    )
    translation_graph: LogicTranslationGraph | None = None
    bounds: RequestBounds | None = None

    def __post_init__(self) -> None:
        routes = dict(self.routes)
        expected = set(SUPPORTED_ROUTE_KINDS)
        known = set(routes)
        if known != expected:
            missing = sorted(item.value for item in expected - known)
            extra = sorted(
                item.value if isinstance(item, SecurityRouteKind) else str(item)
                for item in known - expected
            )
            raise SecuritySliceError(
                f"route table must cover every admitted security route; "
                f"missing={missing} extra={extra}"
            )
        object.__setattr__(self, "routes", MappingProxyType(routes))
        if self.bounds is None:
            object.__setattr__(self, "bounds", RequestBounds.default())

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def domain_id(self) -> str:
        return DOMAIN_ID

    def supported_obligation_kinds(self) -> tuple[str, ...]:
        return tuple(item.value for item in SUPPORTED_ROUTE_KINDS)

    def supported_route_kinds(self) -> tuple[str, ...]:
        return self.supported_obligation_kinds()

    def deferred_route_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(DEFERRED_ROUTE_KINDS))

    def route_for(
        self, kind: SecurityRouteKind | str
    ) -> ObligationRouteDescriptor:
        resolved = self._coerce_kind(kind)
        try:
            return self.routes[resolved]
        except KeyError as error:
            raise UnsupportedRouteError(
                f"unsupported security route kind {resolved.value!r}"
            ) from error

    def connect_obligation(
        self,
        kind: SecurityRouteKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Connect one admitted route through the full lineage chain."""

        resolved = self._coerce_kind(kind)
        if resolved.value in DEFERRED_ROUTE_KINDS:
            raise UnsupportedRouteError(
                f"route {resolved.value!r} is deferred/unsupported for "
                "executable SecurityLogicSlice@2"
            )
        route = self.route_for(resolved)
        # Cross-check formalization adapter admission.
        security_route = resolve_security_route(resolved.value)
        if not security_route.is_admitted:
            raise UnsupportedRouteError(
                f"security formalization route {resolved.value!r} is not admitted"
            )

        text = source_text or self._default_source_text(route)
        document = SourceDocument.from_text(
            f"doc:security:{resolved.value}",
            text,
            encoding="utf-8",
        )
        expression = self._build_expression(route, document)
        source_range = SourceRange(start=0, end=document.byte_length)
        domain_slice = DomainLogicSliceV2.from_typed_expression(
            expression,
            slice_id=f"slice:security:{resolved.value}",
            domain=DOMAIN_ID,
            document_id=document.document_id,
            source_digest=document.content_digest,
            property=property_id(route.property_name),
            view=view_id(route.view_name),
            notation=notation_id(route.notation_name),
            source_range=source_range,
            features=route.features,
            assumption_ids=route.assumption_ids,
            metadata={
                "obligation_kind": resolved.value,
                "security_route_id": route.security_route_id
                or security_route.route_id,
                "slice_interface": self.INTERFACE,
            },
        )
        domain_slice.require_admitted()
        domain_slice.validate_against(document=document, expression=expression)

        translation = self._resolve_translation(route)
        bounds = self.bounds if self.bounds is not None else RequestBounds.default()
        obligation = LogicObligationV2.from_slice(
            domain_slice,
            obligation_id=f"obl:security:{resolved.value}",
            statement=route.statement,
            encoding=encoding_id(route.encoding_name),
            evidence_kind=evidence_id(route.evidence_name),
            bounds=bounds,
            authority_ceiling=route.authority_ceiling,
            metadata={
                "obligation_kind": resolved.value,
                "translation_edge_id": route.translation_edge_id,
            },
        )
        request = BackendRequestV2.from_obligation(
            obligation,
            request_id=f"req:security:{resolved.value}",
            requested_provider=provider_id(route.provider_name),
            metadata={
                "obligation_kind": resolved.value,
                "hermetic": True,
            },
        )
        source_map = SourceMap(
            map_id=f"map:security:{resolved.value}",
            document_id=document.document_id,
            entries=(
                SourceMapEntry(
                    entry_id=f"map:entry:security:{resolved.value}",
                    range=source_range,
                    role="obligation",
                ),
            ),
        )
        compiled = admit_compiled_target(
            request,
            artifact_id=f"compiled:security:{resolved.value}",
            compiler_id=route.compiler_id,
            target_text=route.target_text,
            source_map=source_map,
            assumption_ids=route.assumption_ids,
            loss_ids=self._loss_ids_for(route),
            toolchain_id=f"toolchain:hermetic:{route.provider_name}",
            metadata={"hermetic_fixture": True, "obligation_kind": resolved.value},
        )
        evidence_digest = content_sha256(
            canonical_json_bytes(
                {
                    "kind": resolved.value,
                    "output": route.result_output,
                    "request_digest": request.content_digest,
                }
            )
        )
        parsed = admit_parsed_result(
            compiled,
            artifact_id=f"parsed:security:{resolved.value}",
            provider=provider_id(route.provider_name),
            result_kind=route.result_kind,
            output_text=route.result_output,
            decoded_evidence_digest=evidence_digest,
            evidence_kind=evidence_id(route.evidence_name),
            metadata={"hermetic_fixture": True},
        )
        execution = ProviderExecutionReceiptV2.from_parsed_target(
            parsed,
            receipt_id=f"exec:security:{resolved.value}",
            launch_id=f"launch:hermetic:{route.provider_name}:{resolved.value}",
            tool_id=f"tool:hermetic:{route.provider_name}",
            bounds=bounds,
            record_kind=ExecutionRecordKind.HERMETIC_FIXTURE,
            execution_claimed=True,
            outcome=ExecutionOutcome.SUCCEEDED,
            exit_code=0,
            duration_ms=1,
            toolchain_id=f"toolchain:hermetic:{route.provider_name}",
            metadata={"hermetic_fixture": True},
        )
        match_digest = content_sha256(
            canonical_json_bytes(
                {
                    "execution_digest": execution.content_digest,
                    "output_digest": parsed.output_digest,
                    "result_digest": parsed.result_digest,
                }
            )
        )
        replay_receipt = EvidenceReplayReceipt.from_execution(
            execution,
            receipt_id=f"replay:security:{resolved.value}",
            disposition=ReplayDisposition.REPLAYED,
            replay_claimed=True,
            match_digest=match_digest,
            decoded_evidence_digest=parsed.decoded_evidence_digest,
            reason="hermetic fixture replay matched execution identities",
            metadata={"hermetic_fixture": True},
        )

        typed_origin = TypedOriginLineage(
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            domain_slice_id=domain_slice.slice_id,
            domain_slice_digest=domain_slice.content_digest,
            route_kind=route.kind.value,
            source_range=source_range,
        )
        semantics = SemanticsLineage(
            family=_identity_value(domain_slice.family),
            profile=_identity_value(domain_slice.profile),
            property=_identity_value(domain_slice.property),
            view=_identity_value(domain_slice.view),
            notation=_identity_value(domain_slice.notation),
            features=tuple(domain_slice.features),
            assumption_ids=tuple(domain_slice.assumption_ids),
            statement=route.statement,
            assumptions=route.assumptions,
            security_route_id=route.security_route_id or security_route.route_id,
        )
        request_lineage = RequestLineage(
            obligation_id=obligation.obligation_id,
            obligation_digest=obligation.content_digest,
            request_id=request.request_id,
            request_digest=request.content_digest,
            encoding=_identity_value(request.encoding),
            evidence_kind=_identity_value(request.evidence_kind),
            provider=route.provider_name,
            authority_ceiling=route.authority_ceiling.value,
            bounds={
                "timeout_ms": bounds.timeout_ms,
                "max_steps": bounds.max_steps,
                "max_memory_bytes": bounds.max_memory_bytes,
                "max_output_bytes": bounds.max_output_bytes,
            },
        )
        result_lineage = ResultLineage(
            compiled_artifact_id=compiled.artifact_id,
            compiled_artifact_digest=compiled.content_digest,
            parsed_artifact_id=parsed.artifact_id,
            parsed_artifact_digest=parsed.content_digest,
            result_kind=route.result_kind,
            result_authority=route.result_authority.value,
            output_digest=parsed.output_digest,
            result_digest=parsed.result_digest,
            decoded_evidence_digest=parsed.decoded_evidence_digest,
        )
        replay_lineage = ReplayLineage(
            execution_receipt_id=execution.receipt_id,
            execution_receipt_digest=execution.content_digest,
            replay_receipt_id=replay_receipt.receipt_id,
            replay_receipt_digest=replay_receipt.content_digest,
            record_kind=ExecutionRecordKind.HERMETIC_FIXTURE.value,
            disposition=ReplayDisposition.REPLAYED.value,
            replay_claimed=True,
            match_digest=match_digest,
            launch_id=execution.launch_id,
            tool_id=execution.tool_id,
        )
        translation_digest = (
            translation.content_id
            if _is_sha256_hex(translation.content_id)
            else content_sha256(
                translation.content_id.encode("utf-8", errors="surrogatepass")
            )
        )
        authority = AuthorityLineage(
            stages=(
                AuthorityStage(
                    "typed_origin",
                    domain_slice.slice_id,
                    domain_slice.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "semantics",
                    f"semantics:{resolved.value}",
                    content_sha256(canonical_json_bytes(semantics.to_dict())),
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "translation",
                    translation.edge_id,
                    translation_digest,
                    translation.authority_ceiling,
                ),
                AuthorityStage(
                    "request",
                    request.request_id,
                    request.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "result",
                    parsed.artifact_id,
                    parsed.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "replay",
                    replay_receipt.receipt_id,
                    replay_receipt.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "authority_lineage",
                    f"authority:{resolved.value}",
                    content_sha256(
                        canonical_json_bytes(
                            {
                                "kind": resolved.value,
                                "terminal": route.authority_ceiling.value,
                            }
                        )
                    ),
                    route.authority_ceiling.value,
                ),
            ),
            terminal_authority=route.authority_ceiling.value,
            never_upgrades=True,
        )

        bundle = ObligationLineageBundle(
            obligation_kind=resolved,
            typed_origin=typed_origin,
            semantics=semantics,
            translation=translation,
            request=request_lineage,
            result=result_lineage,
            replay=replay_lineage,
            authority_lineage=authority,
            domain_slice=domain_slice,
            obligation=obligation,
            backend_request=request,
            compiled=compiled,
            parsed=parsed,
            execution=execution,
            replay_receipt=replay_receipt,
            expression=expression,
            document=document,
            notes=route.notes,
        )
        return bundle.require_complete_lineage()

    def connect_route(
        self,
        kind: SecurityRouteKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Alias for :meth:`connect_obligation` (route-oriented naming)."""

        return self.connect_obligation(kind, source_text=source_text)

    def connect_all(
        self,
        kinds: Sequence[SecurityRouteKind | str] | None = None,
    ) -> tuple[ObligationLineageBundle, ...]:
        """Connect every admitted route (or an explicit subset)."""

        if kinds is None:
            selected = SUPPORTED_ROUTE_KINDS
        else:
            selected = tuple(self._coerce_kind(item) for item in kinds)
        return tuple(self.connect_obligation(kind) for kind in selected)

    def validate_all(
        self,
        bundles: Sequence[ObligationLineageBundle] | None = None,
    ) -> Mapping[str, str]:
        """Validate complete lineage for each admitted route.

        Returns a mapping of route kind → content digest.
        """

        items = bundles if bundles is not None else self.connect_all()
        seen: set[str] = set()
        digests: dict[str, str] = {}
        for bundle in items:
            complete = bundle.require_complete_lineage()
            kind = complete.obligation_kind.value
            if kind in seen:
                raise ObligationLineageError(
                    f"duplicate route kind in validation set: {kind}"
                )
            seen.add(kind)
            digests[kind] = complete.content_digest
        missing = [
            kind.value
            for kind in SUPPORTED_ROUTE_KINDS
            if kind.value not in digests
        ]
        if bundles is None and missing:
            raise ObligationLineageError(
                f"validation set missing admitted routes: {', '.join(missing)}"
            )
        return MappingProxyType(digests)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_categories": list(ASSUMPTION_CATEGORIES),
            "deferred_route_kinds": list(self.deferred_route_kinds()),
            "domain_id": self.domain_id,
            "interface": self.INTERFACE,
            "schema_version": self.SCHEMA_VERSION,
            "supported_route_kinds": list(self.supported_route_kinds()),
            "version": self.VERSION,
            "weakens_to_free_form": False,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _coerce_kind(
        self, kind: SecurityRouteKind | str
    ) -> SecurityRouteKind:
        if isinstance(kind, SecurityRouteKind):
            return kind
        token = str(kind).strip()
        if token in DEFERRED_ROUTE_KINDS:
            raise UnsupportedRouteError(
                f"route {token!r} is deferred/unsupported for "
                "executable SecurityLogicSlice@2"
            )
        try:
            return SecurityRouteKind(token)
        except ValueError as error:
            raise UnsupportedRouteError(
                f"unsupported security route kind {token!r}; supported="
                f"{list(self.supported_route_kinds())}"
            ) from error

    def _default_source_text(self, route: ObligationRouteDescriptor) -> str:
        assumptions = route.assumptions.to_dict()
        return (
            f"# security_ir route: {route.kind.value}\n"
            f"# family: {route.family_id} profile: {route.profile_id}\n"
            f"# statement: {route.statement}\n"
            f"# information_flow: {','.join(assumptions['information_flow']) or 'n/a'}\n"
            f"# attacker: {','.join(assumptions['attacker']) or 'n/a'}\n"
            f"# bound: {','.join(assumptions['bound']) or 'n/a'}\n"
            f"# policy_authority: {','.join(assumptions['policy_authority']) or 'n/a'}\n"
            f"route {route.kind.value} {{\n"
            f"  property = {route.property_name};\n"
            f"  edge = {route.translation_edge_id};\n"
            f"}}\n"
        )

    def _build_expression(
        self,
        route: ObligationRouteDescriptor,
        document: SourceDocument,
    ) -> TypedExpression:
        """Build a typed-expression origin bound to the security route namespaces."""

        signature = LogicSignature(
            signature_id=f"sig:security:slice:{route.kind.value}",
            family=route.family_id,
            profile=route.profile_id,
            sorts=(),
            symbols=(),
            features=route.features,
            metadata={
                "domain": DOMAIN_ID,
                "kind": route.kind.value,
                "slice": self.INTERFACE,
            },
        )
        payload_schema = "security_ir.slice_expression/v2"
        payload = {
            "assumptions": route.assumptions.to_dict(),
            "domain": DOMAIN_ID,
            "kind": route.kind.value,
            "obligation_kind": route.kind.value,
            "schema_version": payload_schema,
            "security_route_id": route.security_route_id,
            "slice_interface": self.INTERFACE,
            "source_digest": document.content_digest,
            "source_document_id": document.document_id,
            "statement": route.statement,
            "translation_edge_id": route.translation_edge_id,
        }
        root = mk_extension(
            f"node:security:slice:{route.kind.value}",
            family=route.family_id,
            profile=route.profile_id,
            features=route.features,
            payload_schema=payload_schema,
            payload=payload,
            children=(),
        )
        return TypedExpression(
            expression_id=f"expr:security:slice:{route.kind.value}",
            root=root,
            signature=signature,
            family=route.family_id,
            profile=route.profile_id,
            range=SourceRange(start=0, end=document.byte_length),
            elaborate_on_init=False,
            metadata={
                "domain": DOMAIN_ID,
                "obligation_kind": route.kind.value,
                "slice": self.INTERFACE,
            },
        )

    def _resolve_translation(
        self, route: ObligationRouteDescriptor
    ) -> TranslationLineage:
        edge_id = route.translation_edge_id
        family_key = route.translation_family
        edge = self._lookup_translation_edge(edge_id, family_key)
        contract = getattr(edge, "contract", None)
        if contract is None:
            raise ObligationLineageError(
                f"translation edge {edge_id!r} lacks a TranslationContract"
            )
        source_family = getattr(contract.source, "family_id", "") or ""
        target_family = getattr(contract.target, "family_id", "") or ""
        preservation = contract.preservation
        preservation_value = (
            preservation.value if hasattr(preservation, "value") else str(preservation)
        )
        authority = contract.authority_ceiling
        authority_value = (
            authority.value if hasattr(authority, "value") else str(authority)
        )
        content_id = (
            getattr(edge, "content_id", None)
            or getattr(edge, "edge_content_id", None)
            or getattr(contract, "contract_content_id", None)
            or getattr(contract, "content_id", None)
            or edge_id
        )
        if callable(content_id):
            content_id = content_id()
        compiler = route.compiler_id
        identities = getattr(contract, "identities", None)
        if identities is not None:
            compiler = (
                getattr(identities, "compiler_identity", None)
                or getattr(identities, "compiler_id", None)
                or compiler
            )
        return TranslationLineage(
            edge_id=edge_id,
            family_key=family_key,
            source_family_id=str(source_family),
            target_family_id=str(target_family),
            preservation=preservation_value,
            authority_ceiling=authority_value,
            compiler_id=str(compiler),
            content_id=str(content_id),
            description=str(getattr(contract, "description", "") or route.notes),
        )

    def _lookup_translation_edge(self, edge_id: str, family_key: str) -> Any:
        if family_key == "program":
            for edge in build_program_translation_edges():
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "state_temporal":
            catalog = build_state_temporal_edges()
            for edge in catalog.edges:
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "policy_modal":
            catalog = build_policy_modal_translation_edges()
            for edge in catalog.edges:
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "hyper":
            catalog = build_hyperproperty_translation_edges()
            for edge in catalog.edges:
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "protocol_target":
            for edge in build_protocol_target_translation_edges():
                if edge.edge_id == edge_id:
                    return edge
        graph = self.translation_graph
        if graph is None:
            try:
                graph = build_logic_translation_graph()
            except Exception:
                graph = None
        if graph is not None:
            contracts = getattr(graph, "contracts", ()) or ()
            if callable(contracts):
                contracts = contracts()
            for contract in contracts:
                contract_id = getattr(contract, "contract_id", None)
                if contract_id == edge_id:
                    return type(
                        "EdgeProxy",
                        (),
                        {
                            "edge_id": edge_id,
                            "contract": contract,
                            "content_id": getattr(
                                contract, "contract_content_id", edge_id
                            ),
                        },
                    )()
        raise ObligationLineageError(
            f"translation edge {edge_id!r} not found in family {family_key!r}"
        )

    def _loss_ids_for(self, route: ObligationRouteDescriptor) -> tuple[str, ...]:
        if route.kind is SecurityRouteKind.SEPARATION:
            return (
                "loss.heap_as_array",
                "loss.sep_conj_to_and",
            )
        if route.kind is SecurityRouteKind.PROTOCOL:
            return (
                "loss.proverif_role_to_process",
                "loss.proverif_attacker_ceiling",
                "loss.proverif_query_renaming",
            )
        if route.kind is SecurityRouteKind.NONINTERFERENCE:
            return (
                "loss.bounded_self_composition",
                "loss.alternation_restricted",
            )
        if route.kind is SecurityRouteKind.CONCURRENCY:
            return ("loss.bounded_interleaving",)
        if route.kind is SecurityRouteKind.TEMPORAL:
            return ("loss.bounded_trace",)
        if route.kind is SecurityRouteKind.STATE:
            return ("loss.finite_domain",)
        if route.kind is SecurityRouteKind.THREAT:
            return ("loss.bounded_attacker_steps",)
        return ()


def _identity_value(identity: LogicIdentity | Mapping[str, Any] | str | Any) -> str:
    if isinstance(identity, LogicIdentity):
        return identity.value
    if isinstance(identity, Mapping):
        return str(identity.get("value") or identity.get("id") or "")
    if hasattr(identity, "value") and not isinstance(identity, str):
        return str(getattr(identity, "value"))
    return str(identity)


def _is_sha256_hex(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def connect_security_route(
    kind: SecurityRouteKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Module-level helper for :meth:`SecurityLogicSlice.connect_route`."""

    return SecurityLogicSlice().connect_route(kind, source_text=source_text)


def connect_security_obligation(
    kind: SecurityRouteKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Alias matching the software-verification helper naming."""

    return connect_security_route(kind, source_text=source_text)


def connect_all_security_routes() -> tuple[ObligationLineageBundle, ...]:
    """Connect every admitted Security IR route end to end."""

    return SecurityLogicSlice().connect_all()


def validate_security_logic_slice() -> Mapping[str, str]:
    """Validate complete lineage for every admitted route."""

    return SecurityLogicSlice().validate_all()


__all__ = [
    "ASSUMPTION_CATEGORIES",
    "DEFERRED_ROUTE_KINDS",
    "DOMAIN_ID",
    "LINEAGE_STAGES",
    "OBLIGATION_LINEAGE_SCHEMA",
    "SECURITY_LOGIC_SLICE_INTERFACE",
    "SECURITY_LOGIC_SLICE_SCHEMA",
    "SECURITY_LOGIC_SLICE_VERSION",
    "SUPPORTED_ROUTE_KINDS",
    "AuthorityLineage",
    "AuthorityStage",
    "ExplicitAssumptions",
    "ObligationLineageBundle",
    "ObligationLineageError",
    "ObligationRouteDescriptor",
    "ReplayLineage",
    "RequestLineage",
    "ResultLineage",
    "SecurityLogicSlice",
    "SecurityRouteKind",
    "SecuritySliceError",
    "SemanticsLineage",
    "TranslationLineage",
    "TypedOriginLineage",
    "UnsupportedRouteError",
    "connect_all_security_routes",
    "connect_security_obligation",
    "connect_security_route",
    "default_obligation_routes",
    "validate_security_logic_slice",
]
