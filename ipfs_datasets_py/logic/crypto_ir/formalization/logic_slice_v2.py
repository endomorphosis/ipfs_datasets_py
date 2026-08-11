"""End-to-end Crypto IR domain logic slice (``CryptoLogicSlice@2``).

Connects admitted cryptocurrency-network views through a single typed vertical
path:

    typed origin → semantics → translation → request → result → replay
    → authority lineage

Base routes admitted here (Wave-2, before LFP2-044 overlays):

* ledger transitions and balances
* consensus safety/liveness
* reorg / finality
* authorization / wallet permissions
* symbolic protocol and bridge sessions
* integer / bitvector arithmetic invariants
* privacy hyperproperties

Every admitted route carries source-span-to-result lineage.  Network/chain
model, arithmetic domain, adversary, trace, finality, and approximation
assumptions are explicit on the route descriptor and appear on the domain
slice / obligation assumption set.  Finite-field and ZK-constraint overlays
attach only in LFP2-044 after LFP2-042.

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
from ipfs_datasets_py.logic.crypto_ir.formalization.typed_adapter import (
    CRYPTO_IR_DOMAIN_ID,
    CryptoNetworkFormalizationAdapter,
    CryptoNetworkViewKind,
    NetworkAssumptionKind,
    adapt_crypto_network_view,
)
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

CRYPTO_LOGIC_SLICE_INTERFACE: Final = "CryptoLogicSlice@2"
CRYPTO_LOGIC_SLICE_SCHEMA: Final = "crypto-logic-slice/v2"
CRYPTO_LOGIC_SLICE_VERSION: Final = "2.0.0"
OBLIGATION_LINEAGE_SCHEMA: Final = "crypto-obligation-lineage/v2"
DOMAIN_ID: Final = CRYPTO_IR_DOMAIN_ID

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

# Explicit assumption categories required by LFP2-023 acceptance.
# Network/chain, arithmetic domain, adversary, trace, finality, and
# approximation assumptions are never implicit.
ASSUMPTION_CATEGORIES: Final[tuple[str, ...]] = (
    "network_chain",
    "arithmetic_domain",
    "adversary",
    "trace",
    "finality",
    "approximation",
)

# Evidence subset named by the backlog task (must appear in supported kinds).
EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "ledger",
    "consensus",
    "finality",
    "protocol",
    "arithmetic",
    "hyperproperty",
)

# Deferred until LFP2-044 (finite-field / ZK overlays after LFP2-042).
DEFERRED_ROUTE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "finite_field",
        "finite_field_constraint",
        "zk",
        "zkp",
        "zk_constraint",
        "zero_knowledge",
        "probabilistic",
        "boolean_receipt",
        "free_form",
    }
)


class CryptoSliceError(ValueError):
    """Raised when a Crypto IR logic slice cannot be admitted."""


class ObligationLineageError(CryptoSliceError):
    """Raised when required lineage stages are missing or inconsistent."""


class UnsupportedRouteError(CryptoSliceError):
    """Raised for routes outside the admitted Crypto IR set."""


class CryptoRouteKind(StrEnum):
    """Admitted Crypto IR route classes connected end to end by this slice."""

    LEDGER = "ledger"
    BALANCES = "balances"
    CONSENSUS = "consensus"
    FINALITY = "finality"
    BRIDGES = "bridges"
    WALLETS = "wallets"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    ARITHMETIC = "arithmetic"
    HYPERPROPERTY = "hyperproperty"


SUPPORTED_ROUTE_KINDS: Final[tuple[CryptoRouteKind, ...]] = (
    CryptoRouteKind.LEDGER,
    CryptoRouteKind.BALANCES,
    CryptoRouteKind.CONSENSUS,
    CryptoRouteKind.FINALITY,
    CryptoRouteKind.BRIDGES,
    CryptoRouteKind.WALLETS,
    CryptoRouteKind.AUTHORIZATION,
    CryptoRouteKind.PROTOCOL,
    CryptoRouteKind.ARITHMETIC,
    CryptoRouteKind.HYPERPROPERTY,
)

# Map executable slice routes onto CryptoNetworkFormalizationAdapter@1 views.
_ROUTE_TO_NETWORK_VIEW: Final[Mapping[CryptoRouteKind, CryptoNetworkViewKind]] = (
    MappingProxyType(
        {
            CryptoRouteKind.LEDGER: CryptoNetworkViewKind.TRANSACTIONS,
            CryptoRouteKind.BALANCES: CryptoNetworkViewKind.BALANCES,
            CryptoRouteKind.CONSENSUS: CryptoNetworkViewKind.CONSENSUS,
            CryptoRouteKind.FINALITY: CryptoNetworkViewKind.REORG_FINALITY,
            CryptoRouteKind.BRIDGES: CryptoNetworkViewKind.BRIDGES,
            CryptoRouteKind.WALLETS: CryptoNetworkViewKind.WALLETS,
            CryptoRouteKind.AUTHORIZATION: CryptoNetworkViewKind.PERMISSIONS,
            CryptoRouteKind.PROTOCOL: CryptoNetworkViewKind.SYMBOLIC_PROTOCOLS,
            CryptoRouteKind.ARITHMETIC: CryptoNetworkViewKind.ARITHMETIC,
            CryptoRouteKind.HYPERPROPERTY: CryptoNetworkViewKind.PRIVACY,
        }
    )
)


@dataclass(frozen=True, slots=True)
class ExplicitAssumptions:
    """Closed assumption axes required for every admitted crypto route.

    Empty tuples are allowed only when the axis is not applicable; the
    descriptor still declares the axis so omission is never silent.
    """

    network_chain: tuple[str, ...]
    arithmetic_domain: tuple[str, ...]
    adversary: tuple[str, ...]
    trace: tuple[str, ...]
    finality: tuple[str, ...]
    approximation: tuple[str, ...]

    def all_ids(self) -> tuple[str, ...]:
        """Flatten unique assumption ids in stable category order."""

        ordered: list[str] = []
        seen: set[str] = set()
        for group in (
            self.network_chain,
            self.arithmetic_domain,
            self.adversary,
            self.trace,
            self.finality,
            self.approximation,
        ):
            for item in group:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary": list(self.adversary),
            "approximation": list(self.approximation),
            "arithmetic_domain": list(self.arithmetic_domain),
            "finality": list(self.finality),
            "network_chain": list(self.network_chain),
            "trace": list(self.trace),
        }


def _assumptions(
    *,
    network_chain: Sequence[str],
    arithmetic_domain: Sequence[str],
    adversary: Sequence[str],
    trace: Sequence[str],
    finality: Sequence[str],
    approximation: Sequence[str],
) -> ExplicitAssumptions:
    return ExplicitAssumptions(
        network_chain=tuple(network_chain),
        arithmetic_domain=tuple(arithmetic_domain),
        adversary=tuple(adversary),
        trace=tuple(trace),
        finality=tuple(finality),
        approximation=tuple(approximation),
    )


@dataclass(frozen=True, slots=True)
class ObligationRouteDescriptor:
    """Static routing metadata for one admitted Crypto IR route class."""

    kind: CryptoRouteKind
    network_view: CryptoNetworkViewKind
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
    crypto_route_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CryptoRouteKind):
            object.__setattr__(self, "kind", CryptoRouteKind(self.kind))
        if not isinstance(self.network_view, CryptoNetworkViewKind):
            object.__setattr__(
                self, "network_view", CryptoNetworkViewKind(self.network_view)
            )
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
            raise CryptoSliceError(
                f"route {self.kind.value!r} requires ExplicitAssumptions"
            )
        for axis in ASSUMPTION_CATEGORIES:
            if not hasattr(self.assumptions, axis):
                raise CryptoSliceError(
                    f"route {self.kind.value!r} missing assumption axis {axis!r}"
                )
        expected_view = _ROUTE_TO_NETWORK_VIEW[self.kind]
        if self.network_view is not expected_view:
            raise CryptoSliceError(
                f"route {self.kind.value!r} network_view must be "
                f"{expected_view.value!r}"
            )

    @property
    def assumption_ids(self) -> tuple[str, ...]:
        return self.assumptions.all_ids()


def default_obligation_routes() -> Mapping[
    CryptoRouteKind, ObligationRouteDescriptor
]:
    """Return the sealed admitted-route table for Crypto IR."""

    rows: tuple[ObligationRouteDescriptor, ...] = (
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.LEDGER,
            network_view=CryptoNetworkViewKind.TRANSACTIONS,
            family_id="transition_system",
            profile_id="crypto_network_transactions",
            property_name="safety",
            view_name="source",
            notation_name="crypto_ledger_transition",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="transition_system_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="crypto.ledger.bounded_smt",
            result_kind="model_check.satisfied",
            statement=(
                "Check ledger transaction acceptance under declared chain rules, "
                "observation-bound finality, and finite step window."
            ),
            target_text="(assert (not ledger_transition_invariant))",
            result_output="unsat",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:declared_chain_rules",
                    "asm.crypto_network.transactions.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:linear_integer",
                    "asm.crypto_network.transactions.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:none",
                    "asm.crypto_network.transactions.attacker",
                ),
                trace=(
                    "assumption:trace:finite",
                    "asm.crypto_network.transactions.trace",
                ),
                finality=(
                    "assumption:finality:observation_bound",
                    "asm.crypto_network.transactions.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_step_window",
                    "bound:step_window",
                    "asm.crypto_network.transactions.bound",
                ),
            ),
            features=("crypto_ir.ledger", "transition_system.ledger"),
            notes="Ledger transitions keep chain model and finality bounds explicit.",
            crypto_route_id="crypto-route/ledger/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.BALANCES,
            network_view=CryptoNetworkViewKind.BALANCES,
            family_id="first_order",
            profile_id="crypto_network_balances",
            property_name="invariant",
            view_name="verification_condition",
            notation_name="crypto_balance_invariant",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="crypto.balances.smtlib2",
            result_kind="satisfiability.unsat",
            statement=(
                "Discharge balance conservation under closed-world ledger state "
                "and linear-integer arithmetic on base units."
            ),
            target_text="(assert (not balance_conservation))",
            result_output="unsat",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:ledger_state_closed_world",
                    "asm.crypto_network.balances.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:linear_integer",
                    "asm.crypto_network.balances.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:none",
                    "asm.crypto_network.balances.attacker",
                ),
                trace=(
                    "assumption:trace:not_applicable",
                    "asm.crypto_network.balances.trace",
                ),
                finality=(
                    "assumption:finality:confirmed_or_finalized_only",
                    "asm.crypto_network.balances.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_account_set",
                    "bound:account_set",
                    "asm.crypto_network.balances.bound",
                ),
            ),
            features=("crypto_ir.balances", "first_order.balance_invariant"),
            notes="Balance FOL obligations never imply unbounded asset universes.",
            crypto_route_id="crypto-route/balances/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.CONSENSUS,
            network_view=CryptoNetworkViewKind.CONSENSUS,
            family_id="transition_system",
            profile_id="crypto_network_consensus",
            property_name="safety",
            view_name="source",
            notation_name="crypto_consensus",
            encoding_name="tla_plus",
            evidence_name="bounded",
            provider_name="tla_tlc",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="transition_system_to_tla_plus",
            translation_family="state_temporal",
            compiler_id="crypto.consensus.tla_plus",
            result_kind="model_check.satisfied",
            statement=(
                "Model-check consensus agreement under declared quorum/longest-chain "
                "rules, byzantine coalition bound, and finite validator set."
            ),
            target_text="[] consensus_agreement",
            result_output="satisfied",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:quorum_or_longest_chain",
                    "asm.crypto_network.consensus.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:not_applicable",
                    "asm.crypto_network.consensus.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:byzantine_coalition",
                    "asm.crypto_network.consensus.attacker",
                ),
                trace=(
                    "assumption:trace:finite",
                    "asm.crypto_network.consensus.trace",
                ),
                finality=(
                    "assumption:finality:protocol_finality_predicate",
                    "asm.crypto_network.consensus.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_validator_set",
                    "bound:validator_set",
                    "bound:round_depth",
                    "asm.crypto_network.consensus.bound",
                ),
            ),
            features=("crypto_ir.consensus", "transition_system.consensus"),
            notes="Consensus never claims unbounded asynchrony or cryptographic breaks.",
            crypto_route_id="crypto-route/consensus/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.FINALITY,
            network_view=CryptoNetworkViewKind.REORG_FINALITY,
            family_id="transition_system",
            profile_id="crypto_network_reorg_finality",
            property_name="safety",
            view_name="source",
            notation_name="crypto_reorg_finality",
            encoding_name="tla_plus",
            evidence_name="bounded",
            provider_name="tla_tlc",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="transition_system_to_tla_plus",
            translation_family="state_temporal",
            compiler_id="crypto.finality.tla_plus",
            result_kind="model_check.satisfied",
            statement=(
                "Check reorg/finality under declared fork-choice, depth-or-checkpoint "
                "finality, and maximum reorg depth bound."
            ),
            target_text="[] finality_stable",
            result_output="satisfied",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:declared_fork_choice",
                    "asm.crypto_network.reorg_finality.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:not_applicable",
                    "asm.crypto_network.reorg_finality.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:reorg_withholding",
                    "asm.crypto_network.reorg_finality.attacker",
                ),
                trace=(
                    "assumption:trace:finite",
                    "asm.crypto_network.reorg_finality.trace",
                ),
                finality=(
                    "assumption:finality:depth_or_checkpoint",
                    "asm.crypto_network.reorg_finality.finality",
                ),
                approximation=(
                    "assumption:approximation:max_reorg_depth",
                    "bound:reorg_depth",
                    "asm.crypto_network.reorg_finality.bound",
                ),
            ),
            features=("crypto_ir.finality", "transition_system.reorg_finality"),
            notes="Deeper reorgs than the declared bound are explicitly excluded.",
            crypto_route_id="crypto-route/finality/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.BRIDGES,
            network_view=CryptoNetworkViewKind.BRIDGES,
            family_id="cryptographic_protocol",
            profile_id="crypto_network_bridges",
            property_name="safety",
            view_name="protocol",
            notation_name="symbolic_protocol",
            encoding_name="proverif_pv",
            evidence_name="attack",
            provider_name="proverif",
            authority_ceiling=RequestAuthorityCeiling.PROTOCOL,
            result_authority=ResultAuthority.PROTOCOL,
            translation_edge_id="symbolic_protocol_to_proverif_applied_pi",
            translation_family="protocol_target",
            compiler_id="crypto.bridges.proverif",
            result_kind="protocol.safety.holds",
            statement=(
                "Analyze bridge mint/release under Dolev-Yao adversary, per-chain "
                "consensus, and source-finality-before-mint."
            ),
            target_text="query attacker(bridge_secret).",
            result_output="not attacker(bridge_secret).",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:per_chain_declared",
                    "asm.crypto_network.bridges.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:linear_integer",
                    "asm.crypto_network.bridges.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:dolev_yao",
                    "attacker:perfect_cryptography",
                    "asm.crypto_network.bridges.attacker",
                ),
                trace=(
                    "assumption:trace:finite",
                    "asm.crypto_network.bridges.trace",
                ),
                finality=(
                    "assumption:finality:source_finality_before_mint",
                    "asm.crypto_network.bridges.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_message_depth",
                    "bound:message_depth",
                    "asm.crypto_network.bridges.bound",
                ),
            ),
            features=("crypto_ir.bridges", "cryptographic_protocol.bridge"),
            notes="Bridge consensus identities remain per-chain; never merged silently.",
            crypto_route_id="crypto-route/bridges/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.WALLETS,
            network_view=CryptoNetworkViewKind.WALLETS,
            family_id="authorization",
            profile_id="crypto_network_wallets",
            property_name="authorization",
            view_name="source",
            notation_name="secpal_surface",
            encoding_name="datalog",
            evidence_name="authorization",
            provider_name="datalog_secpal",
            authority_ceiling=RequestAuthorityCeiling.AUTHORIZATION,
            result_authority=ResultAuthority.AUTHORIZATION,
            translation_edge_id="authorization_to_secpal",
            translation_family="policy_modal",
            compiler_id="crypto.wallets.secpal",
            result_kind="authorization.allow",
            statement=(
                "Evaluate wallet signing authority under explicit principal set "
                "and declared unauthorized-principal adversary."
            ),
            target_text="says(Wallet, can(Owner, sign))",
            result_output="allow",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:not_applicable",
                    "asm.crypto_network.wallets.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:not_applicable",
                    "asm.crypto_network.wallets.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:unauthorized_principal",
                    "asm.crypto_network.wallets.attacker",
                ),
                trace=(
                    "assumption:trace:not_applicable",
                    "asm.crypto_network.wallets.trace",
                ),
                finality=(
                    "assumption:finality:not_applicable",
                    "asm.crypto_network.wallets.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_principal_set",
                    "bound:principal_set",
                    "asm.crypto_network.wallets.bound",
                ),
            ),
            features=("crypto_ir.wallets", "authorization.wallet"),
            notes="Wallet authorization does not claim ledger consensus or finality.",
            crypto_route_id="crypto-route/wallets/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.AUTHORIZATION,
            network_view=CryptoNetworkViewKind.PERMISSIONS,
            family_id="authorization",
            profile_id="crypto_network_permissions",
            property_name="authorization",
            view_name="source",
            notation_name="secpal_surface",
            encoding_name="datalog",
            evidence_name="authorization",
            provider_name="datalog_secpal",
            authority_ceiling=RequestAuthorityCeiling.AUTHORIZATION,
            result_authority=ResultAuthority.AUTHORIZATION,
            translation_edge_id="authorization_to_secpal",
            translation_family="policy_modal",
            compiler_id="crypto.permissions.secpal",
            result_kind="authorization.allow",
            statement=(
                "Evaluate crypto-network permission/compliance policy under a "
                "closed finite policy world."
            ),
            target_text="says(Policy, can(Principal, action))",
            result_output="allow",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:not_applicable",
                    "asm.crypto_network.permissions.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:not_applicable",
                    "asm.crypto_network.permissions.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:none",
                    "asm.crypto_network.permissions.attacker",
                ),
                trace=(
                    "assumption:trace:not_applicable",
                    "asm.crypto_network.permissions.trace",
                ),
                finality=(
                    "assumption:finality:not_applicable",
                    "asm.crypto_network.permissions.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_policy_world",
                    "bound:policy_world",
                    "asm.crypto_network.permissions.bound",
                ),
            ),
            features=("crypto_ir.authorization", "authorization.permissions"),
            notes="Permissions are policy-layer; consensus/finality remain N/A and declared.",
            crypto_route_id="crypto-route/authorization/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.PROTOCOL,
            network_view=CryptoNetworkViewKind.SYMBOLIC_PROTOCOLS,
            family_id="cryptographic_protocol",
            profile_id="crypto_network_symbolic_protocol",
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
            compiler_id="crypto.protocol.proverif",
            result_kind="protocol.secrecy.holds",
            statement=(
                "Analyze symbolic wallet/network protocol secrecy under Dolev-Yao "
                "with perfect-cryptography over-approximation."
            ),
            target_text="query attacker(secret).",
            result_output="not attacker(secret).",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:not_applicable",
                    "asm.crypto_network.symbolic_protocols.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:not_applicable",
                    "asm.crypto_network.symbolic_protocols.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:dolev_yao",
                    "attacker:perfect_cryptography",
                    "assumption:approximation:perfect_crypto_overapprox",
                    "asm.crypto_network.symbolic_protocols.attacker",
                ),
                trace=(
                    "assumption:trace:finite",
                    "asm.crypto_network.symbolic_protocols.trace",
                ),
                finality=(
                    "assumption:finality:not_applicable",
                    "asm.crypto_network.symbolic_protocols.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_session_depth",
                    "assumption:approximation:perfect_crypto_overapprox",
                    "bound:session_depth",
                    "asm.crypto_network.symbolic_protocols.bound",
                ),
            ),
            features=(
                "crypto_ir.protocol",
                "cryptographic_protocol.symbolic",
            ),
            notes="Symbolic protocol views do not encode ledger consensus or finality.",
            crypto_route_id="crypto-route/protocol/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.ARITHMETIC,
            network_view=CryptoNetworkViewKind.ARITHMETIC,
            family_id="first_order",
            profile_id="crypto_network_arithmetic",
            property_name="safety",
            view_name="verification_condition",
            notation_name="smt_lib2",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="crypto.arithmetic.smtlib2",
            result_kind="satisfiability.unsat",
            statement=(
                "Discharge SMT arithmetic invariants for amounts, fees, and "
                "overflow under explicit linear-integer or bitvector domain."
            ),
            target_text="(assert (not arithmetic_invariant))",
            result_output="unsat",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:not_applicable",
                    "asm.crypto_network.arithmetic.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:linear_integer",
                    "assumption:arithmetic_domain:bitvector_when_declared",
                    "asm.crypto_network.arithmetic.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:none",
                    "asm.crypto_network.arithmetic.attacker",
                ),
                trace=(
                    "assumption:trace:not_applicable",
                    "asm.crypto_network.arithmetic.trace",
                ),
                finality=(
                    "assumption:finality:not_applicable",
                    "asm.crypto_network.arithmetic.finality",
                ),
                approximation=(
                    "assumption:approximation:bitwidth_or_domain_finite",
                    "bound:bitwidth",
                    "bound:domain_size",
                    "asm.crypto_network.arithmetic.bound",
                ),
            ),
            features=("crypto_ir.arithmetic", "first_order.smt_arithmetic"),
            notes=(
                "Finite-field/ZK arithmetic overlays remain deferred to LFP2-044."
            ),
            crypto_route_id="crypto-route/arithmetic/v1",
        ),
        ObligationRouteDescriptor(
            kind=CryptoRouteKind.HYPERPROPERTY,
            network_view=CryptoNetworkViewKind.PRIVACY,
            family_id="hyperproperty",
            profile_id="crypto_network_privacy",
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
            compiler_id="crypto.privacy.self_composition",
            result_kind="hyperproperty.noninterference.holds",
            statement=(
                "Check relational privacy/anonymity via bounded self-composition; "
                "computational ZK is not claimed."
            ),
            target_text="(assert (not privacy_noninterference))",
            result_output="unsat",
            assumptions=_assumptions(
                network_chain=(
                    "assumption:network_chain:not_applicable",
                    "asm.crypto_network.privacy.consensus",
                ),
                arithmetic_domain=(
                    "assumption:arithmetic_domain:not_applicable",
                    "asm.crypto_network.privacy.arithmetic",
                ),
                adversary=(
                    "assumption:adversary:relational_observer",
                    "asm.crypto_network.privacy.attacker",
                ),
                trace=(
                    "assumption:trace:finite",
                    "assumption:hypertrace:finite_window",
                    "asm.crypto_network.privacy.trace",
                ),
                finality=(
                    "assumption:finality:not_applicable",
                    "asm.crypto_network.privacy.finality",
                ),
                approximation=(
                    "assumption:approximation:finite_hypertrace_window",
                    "assumption:approximation:not_computational_zk",
                    "bound:hypertrace_window",
                    "bound:alternation",
                    "asm.crypto_network.privacy.bound",
                ),
            ),
            features=(
                "crypto_ir.hyperproperty",
                "hyperproperty.privacy",
            ),
            notes="Privacy hyperproperties never imply probabilistic or ZK claims.",
            crypto_route_id="crypto-route/hyperproperty/v1",
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
    network_view: str = ""
    source_range: SourceRange | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "domain_slice_digest": self.domain_slice_digest,
            "domain_slice_id": self.domain_slice_id,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "network_view": self.network_view,
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
    crypto_route_id: str = ""
    network_view: str = ""
    network_view_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "assumptions": self.assumptions.to_dict(),
            "crypto_route_id": self.crypto_route_id,
            "domain": self.domain,
            "family": self.family,
            "features": list(self.features),
            "network_view": self.network_view,
            "network_view_id": self.network_view_id,
            "notation": self.notation,
            "profile": self.profile,
            "property": self.property,
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
    """Complete end-to-end lineage for one admitted crypto route."""

    obligation_kind: CryptoRouteKind | str
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

    interface: ClassVar[str] = CRYPTO_LOGIC_SLICE_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.obligation_kind, CryptoRouteKind):
            object.__setattr__(
                self,
                "obligation_kind",
                CryptoRouteKind(self.obligation_kind),
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
class CryptoLogicSlice:
    """Compose admitted Crypto IR routes end to end.

    Interface: ``CryptoLogicSlice@2``.
    """

    INTERFACE: ClassVar[str] = CRYPTO_LOGIC_SLICE_INTERFACE
    VERSION: ClassVar[str] = CRYPTO_LOGIC_SLICE_VERSION
    SCHEMA_VERSION: ClassVar[str] = CRYPTO_LOGIC_SLICE_SCHEMA

    routes: Mapping[CryptoRouteKind, ObligationRouteDescriptor] = field(
        default_factory=default_obligation_routes
    )
    translation_graph: LogicTranslationGraph | None = None
    bounds: RequestBounds | None = None
    network_adapter: CryptoNetworkFormalizationAdapter | None = None

    def __post_init__(self) -> None:
        routes = dict(self.routes)
        expected = set(SUPPORTED_ROUTE_KINDS)
        known = set(routes)
        if known != expected:
            missing = sorted(item.value for item in expected - known)
            extra = sorted(
                item.value if isinstance(item, CryptoRouteKind) else str(item)
                for item in known - expected
            )
            raise CryptoSliceError(
                f"route table must cover every admitted crypto route; "
                f"missing={missing} extra={extra}"
            )
        object.__setattr__(self, "routes", MappingProxyType(routes))
        if self.bounds is None:
            object.__setattr__(self, "bounds", RequestBounds.default())
        if self.network_adapter is None:
            object.__setattr__(
                self, "network_adapter", CryptoNetworkFormalizationAdapter()
            )

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

    def deferred_obligation_kinds(self) -> tuple[str, ...]:
        return self.deferred_route_kinds()

    def route_for(
        self, kind: CryptoRouteKind | str
    ) -> ObligationRouteDescriptor:
        resolved = self._coerce_kind(kind)
        try:
            return self.routes[resolved]
        except KeyError as error:
            raise UnsupportedRouteError(
                f"unsupported crypto route kind {resolved.value!r}"
            ) from error

    def network_view_for(
        self, kind: CryptoRouteKind | str
    ) -> CryptoNetworkViewKind:
        return self.route_for(kind).network_view

    def connect_obligation(
        self,
        kind: CryptoRouteKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Connect one admitted route through the full lineage chain."""

        resolved = self._coerce_kind(kind)
        if resolved.value in DEFERRED_ROUTE_KINDS:
            raise UnsupportedRouteError(
                f"route {resolved.value!r} is deferred/unsupported for "
                "executable CryptoLogicSlice@2"
            )
        route = self.route_for(resolved)
        adapter = self.network_adapter or CryptoNetworkFormalizationAdapter()
        network_route = adapter.route_for(route.network_view)
        # Cross-check network adapter admission and assumption completeness.
        for axis_kind in NetworkAssumptionKind:
            network_route.assumption(axis_kind)

        text = source_text or self._default_source_text(route, network_route)
        document = SourceDocument.from_text(
            f"doc:crypto:{resolved.value}",
            text,
            encoding="utf-8",
        )
        expression = self._build_expression(route, network_route, document)
        source_range = SourceRange(start=0, end=document.byte_length)
        domain_slice = DomainLogicSliceV2.from_typed_expression(
            expression,
            slice_id=f"slice:crypto:{resolved.value}",
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
                "crypto_route_id": route.crypto_route_id or network_route.view_id,
                "network_view": route.network_view.value,
                "network_view_id": network_route.view_id,
                "slice_interface": self.INTERFACE,
            },
        )
        domain_slice.require_admitted()
        domain_slice.validate_against(document=document, expression=expression)

        translation = self._resolve_translation(route)
        bounds = self.bounds if self.bounds is not None else RequestBounds.default()
        obligation = LogicObligationV2.from_slice(
            domain_slice,
            obligation_id=f"obl:crypto:{resolved.value}",
            statement=route.statement,
            encoding=encoding_id(route.encoding_name),
            evidence_kind=evidence_id(route.evidence_name),
            bounds=bounds,
            authority_ceiling=route.authority_ceiling,
            metadata={
                "obligation_kind": resolved.value,
                "translation_edge_id": route.translation_edge_id,
                "network_view": route.network_view.value,
            },
        )
        request = BackendRequestV2.from_obligation(
            obligation,
            request_id=f"req:crypto:{resolved.value}",
            requested_provider=provider_id(route.provider_name),
            metadata={
                "obligation_kind": resolved.value,
                "hermetic": True,
            },
        )
        source_map = SourceMap(
            map_id=f"map:crypto:{resolved.value}",
            document_id=document.document_id,
            entries=(
                SourceMapEntry(
                    entry_id=f"map:entry:crypto:{resolved.value}",
                    range=source_range,
                    role="obligation",
                ),
            ),
        )
        compiled = admit_compiled_target(
            request,
            artifact_id=f"compiled:crypto:{resolved.value}",
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
            artifact_id=f"parsed:crypto:{resolved.value}",
            provider=provider_id(route.provider_name),
            result_kind=route.result_kind,
            output_text=route.result_output,
            decoded_evidence_digest=evidence_digest,
            evidence_kind=evidence_id(route.evidence_name),
            metadata={"hermetic_fixture": True},
        )
        execution = ProviderExecutionReceiptV2.from_parsed_target(
            parsed,
            receipt_id=f"exec:crypto:{resolved.value}",
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
            receipt_id=f"replay:crypto:{resolved.value}",
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
            network_view=route.network_view.value,
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
            crypto_route_id=route.crypto_route_id or network_route.view_id,
            network_view=route.network_view.value,
            network_view_id=network_route.view_id,
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
        kind: CryptoRouteKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Alias for :meth:`connect_obligation` (route-oriented naming)."""

        return self.connect_obligation(kind, source_text=source_text)

    def connect_all(
        self,
        kinds: Sequence[CryptoRouteKind | str] | None = None,
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
            "evidence_subset": list(EVIDENCE_SUBSET),
            "interface": self.INTERFACE,
            "schema_version": self.SCHEMA_VERSION,
            "supported_route_kinds": list(self.supported_route_kinds()),
            "version": self.VERSION,
            "weakens_to_free_form": False,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _coerce_kind(self, kind: CryptoRouteKind | str) -> CryptoRouteKind:
        if isinstance(kind, CryptoRouteKind):
            return kind
        token = str(kind).strip()
        if token in DEFERRED_ROUTE_KINDS:
            raise UnsupportedRouteError(
                f"route {token!r} is deferred/unsupported for "
                "executable CryptoLogicSlice@2"
            )
        # Accept network-view aliases for ergonomic routing.
        alias_map = {
            "transactions": CryptoRouteKind.LEDGER,
            "reorg_finality": CryptoRouteKind.FINALITY,
            "permissions": CryptoRouteKind.AUTHORIZATION,
            "symbolic_protocols": CryptoRouteKind.PROTOCOL,
            "privacy": CryptoRouteKind.HYPERPROPERTY,
        }
        if token in alias_map:
            return alias_map[token]
        try:
            return CryptoRouteKind(token)
        except ValueError as error:
            raise UnsupportedRouteError(
                f"unsupported crypto route kind {token!r}; supported="
                f"{list(self.supported_route_kinds())}"
            ) from error

    def _default_source_text(
        self,
        route: ObligationRouteDescriptor,
        network_route: Any,
    ) -> str:
        assumptions = route.assumptions.to_dict()
        return (
            f"# crypto_ir route: {route.kind.value}\n"
            f"# network_view: {route.network_view.value}\n"
            f"# network_view_id: {getattr(network_route, 'view_id', '')}\n"
            f"# family: {route.family_id} profile: {route.profile_id}\n"
            f"# statement: {route.statement}\n"
            f"# network_chain: {','.join(assumptions['network_chain']) or 'n/a'}\n"
            f"# arithmetic_domain: {','.join(assumptions['arithmetic_domain']) or 'n/a'}\n"
            f"# adversary: {','.join(assumptions['adversary']) or 'n/a'}\n"
            f"# trace: {','.join(assumptions['trace']) or 'n/a'}\n"
            f"# finality: {','.join(assumptions['finality']) or 'n/a'}\n"
            f"# approximation: {','.join(assumptions['approximation']) or 'n/a'}\n"
            f"route {route.kind.value} {{\n"
            f"  property = {route.property_name};\n"
            f"  edge = {route.translation_edge_id};\n"
            f"}}\n"
        )

    def _build_expression(
        self,
        route: ObligationRouteDescriptor,
        network_route: Any,
        document: SourceDocument,
    ) -> TypedExpression:
        """Build a typed-expression origin bound to the crypto route namespaces."""

        signature = LogicSignature(
            signature_id=f"sig:crypto:slice:{route.kind.value}",
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
        payload_schema = "crypto_ir.slice_expression/v2"
        payload = {
            "assumptions": route.assumptions.to_dict(),
            "crypto_route_id": route.crypto_route_id,
            "domain": DOMAIN_ID,
            "kind": route.kind.value,
            "network_view": route.network_view.value,
            "network_view_id": getattr(network_route, "view_id", ""),
            "obligation_kind": route.kind.value,
            "schema_version": payload_schema,
            "slice_interface": self.INTERFACE,
            "source_digest": document.content_digest,
            "source_document_id": document.document_id,
            "statement": route.statement,
            "translation_edge_id": route.translation_edge_id,
        }
        root = mk_extension(
            f"node:crypto:slice:{route.kind.value}",
            family=route.family_id,
            profile=route.profile_id,
            features=route.features,
            payload_schema=payload_schema,
            payload=payload,
            children=(),
        )
        return TypedExpression(
            expression_id=f"expr:crypto:slice:{route.kind.value}",
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
        if route.kind is CryptoRouteKind.PROTOCOL:
            return (
                "loss.proverif_role_to_process",
                "loss.proverif_attacker_ceiling",
                "loss.proverif_query_renaming",
            )
        if route.kind is CryptoRouteKind.BRIDGES:
            return (
                "loss.proverif_role_to_process",
                "loss.proverif_attacker_ceiling",
                "loss.bridge_per_chain_consensus",
            )
        if route.kind is CryptoRouteKind.HYPERPROPERTY:
            return (
                "loss.bounded_self_composition",
                "loss.alternation_restricted",
                "loss.not_computational_zk",
            )
        if route.kind is CryptoRouteKind.LEDGER:
            return ("loss.finite_step_window", "loss.observation_bound_finality")
        if route.kind is CryptoRouteKind.CONSENSUS:
            return ("loss.finite_validator_set", "loss.bounded_rounds")
        if route.kind is CryptoRouteKind.FINALITY:
            return ("loss.max_reorg_depth", "loss.finite_chain_growth")
        if route.kind is CryptoRouteKind.ARITHMETIC:
            return ("loss.finite_domain_or_bitwidth",)
        if route.kind is CryptoRouteKind.BALANCES:
            return ("loss.finite_account_set",)
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


def connect_crypto_route(
    kind: CryptoRouteKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Module-level helper for :meth:`CryptoLogicSlice.connect_route`."""

    return CryptoLogicSlice().connect_route(kind, source_text=source_text)


def connect_crypto_obligation(
    kind: CryptoRouteKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Alias matching the software-verification helper naming."""

    return connect_crypto_route(kind, source_text=source_text)


def connect_all_crypto_routes() -> tuple[ObligationLineageBundle, ...]:
    """Connect every admitted Crypto IR route end to end."""

    return CryptoLogicSlice().connect_all()


def validate_crypto_logic_slice() -> Mapping[str, str]:
    """Validate complete lineage for every admitted route."""

    return CryptoLogicSlice().validate_all()


def adapt_and_connect(view: CryptoNetworkViewKind | str) -> ObligationLineageBundle:
    """Resolve a network view, then connect the matching CryptoLogicSlice route."""

    network = adapt_crypto_network_view(view)
    reverse = {
        network_view: kind for kind, network_view in _ROUTE_TO_NETWORK_VIEW.items()
    }
    kind = reverse.get(network.view_kind)
    if kind is None:
        raise UnsupportedRouteError(
            f"network view {network.view_kind.value!r} has no CryptoLogicSlice@2 route"
        )
    return connect_crypto_route(kind)


__all__ = [
    "ASSUMPTION_CATEGORIES",
    "CRYPTO_LOGIC_SLICE_INTERFACE",
    "CRYPTO_LOGIC_SLICE_SCHEMA",
    "CRYPTO_LOGIC_SLICE_VERSION",
    "DEFERRED_ROUTE_KINDS",
    "DOMAIN_ID",
    "EVIDENCE_SUBSET",
    "LINEAGE_STAGES",
    "OBLIGATION_LINEAGE_SCHEMA",
    "SUPPORTED_ROUTE_KINDS",
    "AuthorityLineage",
    "AuthorityStage",
    "CryptoLogicSlice",
    "CryptoRouteKind",
    "CryptoSliceError",
    "ExplicitAssumptions",
    "ObligationLineageBundle",
    "ObligationLineageError",
    "ObligationRouteDescriptor",
    "ReplayLineage",
    "RequestLineage",
    "ResultLineage",
    "SemanticsLineage",
    "TranslationLineage",
    "TypedOriginLineage",
    "UnsupportedRouteError",
    "adapt_and_connect",
    "connect_all_crypto_routes",
    "connect_crypto_obligation",
    "connect_crypto_route",
    "default_obligation_routes",
    "validate_crypto_logic_slice",
]
