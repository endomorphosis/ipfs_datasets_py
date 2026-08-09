"""Migrate crypto_ir cryptocurrency-network views to canonical typed logic.

Interface: ``CryptoNetworkFormalizationAdapter@1`` (LFP-035).

Cryptocurrency-network semantics emit typed formalization routes for ledger
transactions, balances, consensus, reorg/finality, bridges, wallets,
permissions, symbolic protocols, arithmetic, and privacy.  Every admitted
route names its attacker, consensus, finality, bound, arithmetic, and trace
assumptions explicitly.

Legacy crypto :class:`~.obligations.LogicFamily` labels (``smt_lib``, ``fol``,
…) are dual-read aliases only: they canonicalize into family/profile/notation
namespaces with a migration diagnostic, or fail closed.  Routes never imply
future probabilistic, fuzzy, or finite-field/ZK claims.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.aliases import (
    BASELINE_ALIAS_REGISTRY,
    LogicAliasRegistry,
    MigrationDisposition,
    UnknownAliasError,
    WrongNamespaceError,
    dual_read,
)
from ipfs_datasets_py.logic.families.namespaces import (
    BASELINE_NAMESPACES,
    NamespaceKind,
    UnknownIdentityError,
)
from ipfs_datasets_py.logic.families.profiles import (
    ArithmeticSemantics,
    AttackerModel,
    AttackerProfile,
    BoundProfile,
    ConsequenceRelation,
    DomainBoundedness,
    FairnessConstraint,
    HypertraceProfile,
    SemanticProfile,
    SmtTheoryProfile,
    TimeDensity,
    TimeProfile,
    TraceModel,
    TraceProfile,
    WorldPolicy,
)
from ipfs_datasets_py.logic.formalization.views import (
    FormalizationView,
    ViewRegistry,
)
from .obligations import LogicFamily


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE: Final = (
    "CryptoNetworkFormalizationAdapter@1"
)
CRYPTO_NETWORK_FORMALIZATION_ADAPTER_VERSION: Final = "1.0.0"
CRYPTO_NETWORK_ROUTE_SCHEMA: Final = "crypto-ir.network-route@1"
CRYPTO_NETWORK_ASSUMPTION_SCHEMA: Final = "crypto-ir.network-assumption@1"
CRYPTO_NETWORK_LABEL_DIAGNOSTIC_SCHEMA: Final = (
    "crypto-ir.legacy-logic-family-diagnostic@1"
)
CRYPTO_NETWORK_ADAPTER_MODULE_VERSION: Final = "1.0.0"
CRYPTO_IR_DOMAIN_ID: Final = "crypto_ir"

# Stable diagnostic codes.
CODE_UNKNOWN_VIEW: Final = "crypto_network.unknown_view"
CODE_UNKNOWN_LABEL: Final = "crypto_network.unknown_logic_family_label"
CODE_WRONG_NAMESPACE: Final = "crypto_network.wrong_namespace_label"
CODE_FUTURE_CLAIM: Final = "crypto_network.future_claim_rejected"
CODE_MISSING_ASSUMPTION: Final = "crypto_network.missing_assumption"
CODE_MALFORMED: Final = "crypto_network.malformed_input"
CODE_ROUTE: Final = "crypto_network.route_error"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNKNOWN_VIEW,
        CODE_UNKNOWN_LABEL,
        CODE_WRONG_NAMESPACE,
        CODE_FUTURE_CLAIM,
        CODE_MISSING_ASSUMPTION,
        CODE_MALFORMED,
        CODE_ROUTE,
    }
)

# Wave-4 / future families that must never be implied by crypto-network routes.
FUTURE_UNSUPPORTED_FAMILY_CLAIMS: Final[frozenset[str]] = frozenset(
    {
        "probabilistic",
        "fuzzy_weighted",
        "fuzzy",
        "finite_field_constraint",
        "finite_field",
        "ffc",
        "zk",
        "zkp",
        "zero_knowledge",
        "zero-knowledge",
        "zk_snark",
        "zk_stark",
        "relevance_paraconsistent",
        "argumentation",
        "situation_calculus",
        "defeasible_logic",
        "nonmonotonic_logic",
        "description_logic",
        "dependent_type",
    }
)

# Required named assumption dimensions for every cryptocurrency-network route.
REQUIRED_ASSUMPTION_KINDS: Final[tuple[str, ...]] = (
    "attacker",
    "consensus",
    "finality",
    "bound",
    "arithmetic",
    "trace",
)


class CryptoNetworkAdapterError(ValueError):
    """Raised when a crypto-network formalization request is invalid."""

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


class FutureClaimRejectedError(CryptoNetworkAdapterError):
    """Raised when a route would imply probabilistic/ZK/wave-4 claims."""

    def __init__(self, message: str, *, path: str = "family_id") -> None:
        super().__init__(message, code=CODE_FUTURE_CLAIM, path=path)


class UnknownLogicFamilyLabelError(CryptoNetworkAdapterError):
    """Raised when a legacy LogicFamily-like label cannot canonicalize."""

    def __init__(self, message: str, *, path: str = "logic_family") -> None:
        super().__init__(message, code=CODE_UNKNOWN_LABEL, path=path)


class CryptoNetworkViewKind(StrEnum):
    """Closed set of cryptocurrency-network formalization views (LFP-035)."""

    TRANSACTIONS = "transactions"
    BALANCES = "balances"
    CONSENSUS = "consensus"
    REORG_FINALITY = "reorg_finality"
    BRIDGES = "bridges"
    WALLETS = "wallets"
    PERMISSIONS = "permissions"
    SYMBOLIC_PROTOCOLS = "symbolic_protocols"
    ARITHMETIC = "arithmetic"
    PRIVACY = "privacy"


class NetworkAssumptionKind(StrEnum):
    """Named semantic assumption dimensions for cryptocurrency networks."""

    ATTACKER = "attacker"
    CONSENSUS = "consensus"
    FINALITY = "finality"
    BOUND = "bound"
    ARITHMETIC = "arithmetic"
    TRACE = "trace"


class RouteSupport(StrEnum):
    """Whether a typed network route is executable, bounded, or declaration-only."""

    NATIVE = "native"
    TRANSLATED = "translated"
    BOUNDED = "bounded"
    DECLARATION_ONLY = "declaration_only"


class LabelDisposition(StrEnum):
    """How a dual-read LogicFamily-like label was handled."""

    CANONICAL = "canonical"
    ALIAS = "alias"
    REJECTED_UNKNOWN = "rejected_unknown"
    REJECTED_WRONG_NAMESPACE = "rejected_wrong_namespace"
    REJECTED_FUTURE = "rejected_future"


# ---------------------------------------------------------------------------
# Legacy LogicFamily dual-read surface (diagnosed input alias only)
# ---------------------------------------------------------------------------

# Crypto-local LogicFamily enum values that remain dual-readable inputs.
# They are never emitted as canonical family IDs from this adapter.
_LEGACY_LOGIC_FAMILY_CANONICAL: Final[
    Mapping[str, tuple[str, str | None, str | None, str]]
] = MappingProxyType(
    {
        # label -> (family_id, profile_id|None, notation_id|None, notes)
        "smt_lib": (
            "first_order",
            "smt_lib",
            "smt_lib2",
            "legacy crypto LogicFamily.SMT_LIB is notation/profile over first_order",
        ),
        "smt": (
            "first_order",
            "smt_lib",
            "smt_lib2",
            "legacy smt label is notation/profile over first_order",
        ),
        "smtlib2": (
            "first_order",
            "smt_lib",
            "smt_lib2",
            "legacy smtlib2 label is notation/profile over first_order",
        ),
        "fol": (
            "first_order",
            None,
            None,
            "legacy crypto LogicFamily.FOL canonicalizes to family first_order",
        ),
        "first_order": (
            "first_order",
            None,
            None,
            "canonical first-order family",
        ),
        "propositional": (
            "propositional",
            None,
            None,
            "canonical propositional family",
        ),
        "datalog": (
            "datalog",
            None,
            None,
            "canonical datalog family",
        ),
        "temporal": (
            "temporal",
            None,
            None,
            "canonical temporal family",
        ),
        # Non-executable legacy labels stay diagnosed but never route.
        "opaque": (
            "unsupported",
            None,
            None,
            "opaque is non-executable; not a semantic family route",
        ),
        "prose": (
            "unsupported",
            None,
            None,
            "prose is non-executable; not a semantic family route",
        ),
        "unsupported": (
            "unsupported",
            None,
            None,
            "explicit unsupported family",
        ),
    }
)

# Canonical family IDs this adapter may emit on typed routes.
_ADMITTED_CANONICAL_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "propositional",
        "first_order",
        "datalog",
        "temporal",
        "transition_system",
        "cryptographic_protocol",
        "hyperproperty",
        "authorization",
        "refinement",
        "horn_chc",
        "program",
        "concurrency",
        "separation_logic",
    }
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise CryptoNetworkAdapterError(
            f"{label} must be a non-empty trimmed string",
            code=CODE_MALFORMED,
            path=label,
        )
    if "\x00" in value:
        raise CryptoNetworkAdapterError(
            f"{label} must not contain NUL bytes",
            code=CODE_MALFORMED,
            path=label,
        )
    return value


def _normalize_label(value: object) -> str:
    text = _text(value, "logic_family")
    return text.casefold().replace("-", "_").replace(" ", "_")


def _reject_future_claim(label: str, *, path: str = "logic_family") -> None:
    normalized = label.casefold().replace("-", "_").replace(" ", "_")
    if normalized in FUTURE_UNSUPPORTED_FAMILY_CLAIMS:
        raise FutureClaimRejectedError(
            f"crypto-network routes must not imply future claim {label!r}; "
            "probabilistic/ZK/finite-field families remain declaration-only "
            "outside this adapter",
            path=path,
        )
    # Substring guards for compound free-form claims.
    for forbidden in (
        "probabilistic",
        "zero_knowledge",
        "finite_field",
        "zk_snark",
        "zk_stark",
        "fuzzy_weighted",
    ):
        if forbidden in normalized:
            raise FutureClaimRejectedError(
                f"crypto-network routes must not imply future claim {label!r}",
                path=path,
            )


# ---------------------------------------------------------------------------
# Assumption and route contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NetworkAssumption:
    """One named cryptocurrency-network modeling assumption."""

    assumption_id: str
    kind: NetworkAssumptionKind | str
    statement: str
    profile_field: str
    value: str
    schema_version: str = CRYPTO_NETWORK_ASSUMPTION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assumption_id", _text(self.assumption_id, "assumption_id")
        )
        kind = (
            self.kind
            if isinstance(self.kind, NetworkAssumptionKind)
            else NetworkAssumptionKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self, "profile_field", _text(self.profile_field, "profile_field")
        )
        object.__setattr__(self, "value", _text(self.value, "value"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "kind": self.kind.value,
            "profile_field": self.profile_field,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class CryptoNetworkRoute:
    """Typed formalization route for one cryptocurrency-network view."""

    view_kind: CryptoNetworkViewKind | str
    view_id: str
    family_id: str
    profile_id: str
    description: str
    support: RouteSupport | str
    assumptions: tuple[NetworkAssumption, ...]
    providers: tuple[str, ...] = ()
    notation_id: str = ""
    property_ids: tuple[str, ...] = ()
    view_roles: tuple[str, ...] = ()
    authority_ceiling: str = "bounded"
    implies_future_claims: bool = False
    legacy_logic_family_aliases: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_NETWORK_ROUTE_SCHEMA

    def __post_init__(self) -> None:
        view_kind = (
            self.view_kind
            if isinstance(self.view_kind, CryptoNetworkViewKind)
            else CryptoNetworkViewKind(str(self.view_kind))
        )
        object.__setattr__(self, "view_kind", view_kind)
        object.__setattr__(self, "view_id", _text(self.view_id, "view_id"))
        family = _text(self.family_id, "family_id")
        _reject_future_claim(family, path="family_id")
        if family not in _ADMITTED_CANONICAL_FAMILIES:
            raise CryptoNetworkAdapterError(
                f"family_id {family!r} is not an admitted crypto-network family",
                code=CODE_MALFORMED,
                path="family_id",
            )
        object.__setattr__(self, "family_id", family)
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        support = (
            self.support
            if isinstance(self.support, RouteSupport)
            else RouteSupport(str(self.support))
        )
        object.__setattr__(self, "support", support)
        assumptions = tuple(self.assumptions)
        if not assumptions:
            raise CryptoNetworkAdapterError(
                "crypto-network route must name assumptions",
                code=CODE_MISSING_ASSUMPTION,
                path="assumptions",
            )
        kinds = {item.kind.value for item in assumptions}
        missing = [kind for kind in REQUIRED_ASSUMPTION_KINDS if kind not in kinds]
        if missing:
            raise CryptoNetworkAdapterError(
                "crypto-network route missing required assumptions: "
                + ", ".join(missing),
                code=CODE_MISSING_ASSUMPTION,
                path="assumptions",
            )
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(self, "providers", tuple(self.providers))
        object.__setattr__(
            self,
            "notation_id",
            _text(self.notation_id, "notation_id") if self.notation_id else "",
        )
        object.__setattr__(self, "property_ids", tuple(self.property_ids))
        object.__setattr__(self, "view_roles", tuple(self.view_roles))
        object.__setattr__(
            self,
            "authority_ceiling",
            _text(self.authority_ceiling, "authority_ceiling"),
        )
        if not isinstance(self.implies_future_claims, bool):
            raise CryptoNetworkAdapterError(
                "implies_future_claims must be a bool",
                code=CODE_MALFORMED,
                path="implies_future_claims",
            )
        if self.implies_future_claims:
            raise FutureClaimRejectedError(
                "crypto-network routes must set implies_future_claims=False",
                path="implies_future_claims",
            )
        object.__setattr__(
            self,
            "legacy_logic_family_aliases",
            tuple(self.legacy_logic_family_aliases),
        )
        meta = dict(self.metadata) if self.metadata else {}
        object.__setattr__(self, "metadata", MappingProxyType(meta))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def assumption_kinds(self) -> tuple[str, ...]:
        return tuple(item.kind.value for item in self.assumptions)

    def assumption(self, kind: NetworkAssumptionKind | str) -> NetworkAssumption:
        key = kind.value if isinstance(kind, NetworkAssumptionKind) else str(kind)
        for item in self.assumptions:
            if item.kind.value == key:
                return item
        raise CryptoNetworkAdapterError(
            f"route {self.view_id!r} has no assumption kind {key!r}",
            code=CODE_MISSING_ASSUMPTION,
            path="assumptions",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "authority_ceiling": self.authority_ceiling,
            "description": self.description,
            "family_id": self.family_id,
            "implies_future_claims": self.implies_future_claims,
            "legacy_logic_family_aliases": list(self.legacy_logic_family_aliases),
            "metadata": dict(self.metadata),
            "notation_id": self.notation_id,
            "profile_id": self.profile_id,
            "property_ids": list(self.property_ids),
            "providers": list(self.providers),
            "schema_version": self.schema_version,
            "support": self.support.value,
            "view_id": self.view_id,
            "view_kind": self.view_kind.value,
            "view_roles": list(self.view_roles),
        }


@dataclass(frozen=True, slots=True)
class LegacyLogicFamilyDiagnostic:
    """Dual-read diagnostic for a legacy crypto LogicFamily label."""

    input_label: str
    disposition: LabelDisposition | str
    family_id: str = ""
    profile_id: str = ""
    notation_id: str = ""
    message: str = ""
    ok: bool = False
    schema_version: str = CRYPTO_NETWORK_LABEL_DIAGNOSTIC_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "input_label", _text(self.input_label, "input_label")
        )
        disposition = (
            self.disposition
            if isinstance(self.disposition, LabelDisposition)
            else LabelDisposition(str(self.disposition))
        )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(
            self, "family_id", self.family_id if self.family_id else ""
        )
        object.__setattr__(
            self, "profile_id", self.profile_id if self.profile_id else ""
        )
        object.__setattr__(
            self, "notation_id", self.notation_id if self.notation_id else ""
        )
        object.__setattr__(self, "message", self.message if self.message else "")
        if not isinstance(self.ok, bool):
            raise CryptoNetworkAdapterError(
                "ok must be a bool", code=CODE_MALFORMED, path="ok"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "family_id": self.family_id,
            "input_label": self.input_label,
            "message": self.message,
            "notation_id": self.notation_id,
            "ok": self.ok,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Built-in assumption builders
# ---------------------------------------------------------------------------


def _assumption(
    kind: NetworkAssumptionKind,
    *,
    view: str,
    statement: str,
    profile_field: str,
    value: str,
) -> NetworkAssumption:
    return NetworkAssumption(
        assumption_id=f"asm.crypto_network.{view}.{kind.value}",
        kind=kind,
        statement=statement,
        profile_field=profile_field,
        value=value,
    )


def _default_assumptions(
    view: str,
    *,
    attacker: str,
    consensus: str,
    finality: str,
    bound: str,
    arithmetic: str,
    trace: str,
    attacker_statement: str,
    consensus_statement: str,
    finality_statement: str,
    bound_statement: str,
    arithmetic_statement: str,
    trace_statement: str,
) -> tuple[NetworkAssumption, ...]:
    return (
        _assumption(
            NetworkAssumptionKind.ATTACKER,
            view=view,
            statement=attacker_statement,
            profile_field="attacker.model",
            value=attacker,
        ),
        _assumption(
            NetworkAssumptionKind.CONSENSUS,
            view=view,
            statement=consensus_statement,
            profile_field="metadata.consensus_model",
            value=consensus,
        ),
        _assumption(
            NetworkAssumptionKind.FINALITY,
            view=view,
            statement=finality_statement,
            profile_field="metadata.finality_model",
            value=finality,
        ),
        _assumption(
            NetworkAssumptionKind.BOUND,
            view=view,
            statement=bound_statement,
            profile_field="bounds",
            value=bound,
        ),
        _assumption(
            NetworkAssumptionKind.ARITHMETIC,
            view=view,
            statement=arithmetic_statement,
            profile_field="smt_theory.arithmetic",
            value=arithmetic,
        ),
        _assumption(
            NetworkAssumptionKind.TRACE,
            view=view,
            statement=trace_statement,
            profile_field="traces.model",
            value=trace,
        ),
    )


def _build_semantic_profile(
    *,
    profile_id: str,
    name: str,
    family_ids: Sequence[str],
    attacker: AttackerModel,
    arithmetic: ArithmeticSemantics,
    trace: TraceModel,
    domain: DomainBoundedness = DomainBoundedness.FINITE,
    domain_size: int | None = 64,
    model_check_depth: int | None = 32,
    step_bound: int | None = 32,
    theories: Sequence[str] = (),
    bitvector_width: int | None = None,
    description: str = "",
) -> SemanticProfile:
    """Build a reviewed SemanticProfile@1 for a crypto-network route."""

    if domain is DomainBoundedness.FINITE and domain_size is None:
        domain_size = 64
    if domain is DomainBoundedness.UNBOUNDED:
        domain_size = None
    stuttering: bool | None
    fairness: FairnessConstraint
    if trace is TraceModel.NOT_APPLICABLE:
        stuttering = None
        fairness = FairnessConstraint.NOT_APPLICABLE
        time = TimeProfile()
    else:
        stuttering = True
        fairness = FairnessConstraint.WEAK
        time = TimeProfile(density=TimeDensity.DISCRETE)
    bounds = BoundProfile(
        domain=domain,
        domain_size=domain_size,
        model_check_depth=model_check_depth,
        step_bound=step_bound,
    )
    attacker_profile = AttackerProfile(model=attacker)
    if arithmetic is ArithmeticSemantics.NOT_APPLICABLE:
        smt = SmtTheoryProfile()
    else:
        smt = SmtTheoryProfile(
            theories=tuple(theories) if theories else (),
            arithmetic=arithmetic,
            bitvector_width=bitvector_width,
        )
    return SemanticProfile(
        profile_id=profile_id,
        name=name,
        consequence=ConsequenceRelation.CLASSICAL,
        world_policy=WorldPolicy.CLOSED_WORLD,
        description=description,
        bounds=bounds,
        traces=TraceProfile(
            model=trace,
            stuttering_allowed=stuttering,
            fairness=fairness,
        ),
        time=time,
        attacker=attacker_profile,
        smt_theory=smt,
        family_ids=tuple(family_ids),
    )


# ---------------------------------------------------------------------------
# Default route catalog
# ---------------------------------------------------------------------------


def _route(
    kind: CryptoNetworkViewKind,
    *,
    view_id: str,
    family_id: str,
    profile_id: str,
    description: str,
    support: RouteSupport,
    assumptions: tuple[NetworkAssumption, ...],
    providers: Sequence[str],
    notation_id: str = "",
    property_ids: Sequence[str] = (),
    view_roles: Sequence[str] = (),
    authority_ceiling: str = "bounded",
    legacy_aliases: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> CryptoNetworkRoute:
    return CryptoNetworkRoute(
        view_kind=kind,
        view_id=view_id,
        family_id=family_id,
        profile_id=profile_id,
        description=description,
        support=support,
        assumptions=assumptions,
        providers=tuple(providers),
        notation_id=notation_id,
        property_ids=tuple(property_ids),
        view_roles=tuple(view_roles),
        authority_ceiling=authority_ceiling,
        implies_future_claims=False,
        legacy_logic_family_aliases=tuple(legacy_aliases),
        metadata=metadata or {},
    )


def default_crypto_network_routes() -> tuple[CryptoNetworkRoute, ...]:
    """Reviewed typed routes for cryptocurrency-network views."""

    return (
        _route(
            CryptoNetworkViewKind.TRANSACTIONS,
            view_id="crypto-ir-view/transactions/v1",
            family_id="transition_system",
            profile_id="crypto_network_transactions",
            description=(
                "Ledger transaction acceptance and state-transition obligations."
            ),
            support=RouteSupport.BOUNDED,
            assumptions=_default_assumptions(
                "transactions",
                attacker="none",
                consensus="declared_chain_rules",
                finality="observation_bound",
                bound="finite_step_window",
                arithmetic="linear_integer",
                trace="finite",
                attacker_statement=(
                    "No protocol adversary; transaction validity is modeled "
                    "under closed-world chain rules only."
                ),
                consensus_statement=(
                    "Consensus is the declared chain rule pack; forks outside "
                    "the observation window are not modeled."
                ),
                finality_statement=(
                    "Finality is the observed finality status bound on the "
                    "transaction epoch; reorgs deeper than the bound are excluded."
                ),
                bound_statement=(
                    "Step and model-check depth are finite; unbounded ledgers "
                    "are not claimed."
                ),
                arithmetic_statement=(
                    "Amounts and fees use linear integer arithmetic over base units."
                ),
                trace_statement=(
                    "Transaction histories are finite discrete traces with weak fairness."
                ),
            ),
            providers=("z3", "cvc5", "tla_tlc", "apalache"),
            notation_id="smt_lib2",
            property_ids=("safety", "reachability"),
            view_roles=("source", "verification_condition"),
            legacy_aliases=("smt_lib", "fol"),
            metadata={
                "consensus_model": "declared_chain_rules",
                "finality_model": "observation_bound",
                "crypto_constructs": ["transaction", "ledger_transition"],
            },
        ),
        _route(
            CryptoNetworkViewKind.BALANCES,
            view_id="crypto-ir-view/balances/v1",
            family_id="first_order",
            profile_id="crypto_network_balances",
            description="Balance conservation and asset-effect arithmetic invariants.",
            support=RouteSupport.TRANSLATED,
            assumptions=_default_assumptions(
                "balances",
                attacker="none",
                consensus="ledger_state_closed_world",
                finality="confirmed_or_finalized_only",
                bound="finite_account_set",
                arithmetic="linear_integer",
                trace="not_applicable",
                attacker_statement=(
                    "Balance invariants assume no adversarial reordering beyond "
                    "the declared observation set."
                ),
                consensus_statement=(
                    "Balances are taken from a closed-world ledger state snapshot."
                ),
                finality_statement=(
                    "Only confirmed or finalized observations contribute to balances."
                ),
                bound_statement=(
                    "The account/asset universe is finite and explicitly enumerated."
                ),
                arithmetic_statement=(
                    "Conservation uses linear integer arithmetic on base units."
                ),
                trace_statement=(
                    "Balance obligations are state/FOL constraints, not trace properties."
                ),
            ),
            providers=("z3", "cvc5"),
            notation_id="smt_lib2",
            property_ids=("safety", "invariant"),
            view_roles=("verification_condition",),
            legacy_aliases=("smt_lib", "fol"),
            metadata={
                "consensus_model": "ledger_state_closed_world",
                "finality_model": "confirmed_or_finalized_only",
                "crypto_constructs": ["balance", "asset_effect"],
            },
        ),
        _route(
            CryptoNetworkViewKind.CONSENSUS,
            view_id="crypto-ir-view/consensus/v1",
            family_id="transition_system",
            profile_id="crypto_network_consensus",
            description="Consensus protocol transition and agreement obligations.",
            support=RouteSupport.BOUNDED,
            assumptions=_default_assumptions(
                "consensus",
                attacker="custom",
                consensus="quorum_or_longest_chain",
                finality="protocol_finality_predicate",
                bound="finite_validator_set",
                arithmetic="not_applicable",
                trace="finite",
                attacker_statement=(
                    "Attacker is a declared byzantine/minority coalition under the "
                    "consensus profile; cryptographic breaks are out of scope."
                ),
                consensus_statement=(
                    "Consensus model is the declared quorum or longest-chain rule."
                ),
                finality_statement=(
                    "Finality is the protocol finality predicate under the bound."
                ),
                bound_statement=(
                    "Validator set and round depth are finite; unbounded asynchrony "
                    "is not claimed."
                ),
                arithmetic_statement=(
                    "Consensus structure is combinatorial; numeric arithmetic is N/A."
                ),
                trace_statement=(
                    "Consensus runs are finite discrete traces with weak fairness."
                ),
            ),
            providers=("tla_tlc", "apalache", "z3"),
            property_ids=("safety", "liveness"),
            view_roles=("source",),
            legacy_aliases=(),
            metadata={
                "consensus_model": "quorum_or_longest_chain",
                "finality_model": "protocol_finality_predicate",
                "crypto_constructs": ["consensus", "validator_set"],
            },
        ),
        _route(
            CryptoNetworkViewKind.REORG_FINALITY,
            view_id="crypto-ir-view/transition/v1",
            family_id="transition_system",
            profile_id="crypto_network_reorg_finality",
            description="Ledger reorg and finality transition-system views.",
            support=RouteSupport.BOUNDED,
            assumptions=_default_assumptions(
                "reorg_finality",
                attacker="custom",
                consensus="declared_fork_choice",
                finality="depth_or_checkpoint",
                bound="max_reorg_depth",
                arithmetic="not_applicable",
                trace="finite",
                attacker_statement=(
                    "Attacker may withhold or reorder blocks within the reorg depth bound."
                ),
                consensus_statement=(
                    "Fork choice is the declared chain selection rule."
                ),
                finality_statement=(
                    "Finality is depth- or checkpoint-based; deeper reorgs are excluded."
                ),
                bound_statement=(
                    "Maximum reorg depth and step bound are finite and explicit."
                ),
                arithmetic_statement=(
                    "Reorg structure does not rely on numeric arithmetic semantics."
                ),
                trace_statement=(
                    "Reorg histories are finite traces; infinite chain growth is not claimed."
                ),
            ),
            providers=("tla_tlc", "apalache", "runtime_mtl"),
            property_ids=("safety", "liveness"),
            view_roles=("source",),
            legacy_aliases=(),
            metadata={
                "consensus_model": "declared_fork_choice",
                "finality_model": "depth_or_checkpoint",
                "crypto_constructs": ["reorg", "finality", "ledger_transition"],
            },
        ),
        _route(
            CryptoNetworkViewKind.BRIDGES,
            view_id="crypto-ir-view/bridges/v1",
            family_id="cryptographic_protocol",
            profile_id="crypto_network_bridges",
            description="Cross-chain bridge and message-passing protocol views.",
            support=RouteSupport.TRANSLATED,
            assumptions=_default_assumptions(
                "bridges",
                attacker="dolev_yao",
                consensus="per_chain_declared",
                finality="source_finality_before_mint",
                bound="finite_message_depth",
                arithmetic="linear_integer",
                trace="finite",
                attacker_statement=(
                    "Bridge messages face a Dolev-Yao network adversary; perfect "
                    "cryptography is assumed."
                ),
                consensus_statement=(
                    "Each chain has its own declared consensus; bridge does not "
                    "merge consensus identities."
                ),
                finality_statement=(
                    "Mint/release requires source-chain finality under the declared predicate."
                ),
                bound_statement=(
                    "Message and session depth are finite; unbounded relay is excluded."
                ),
                arithmetic_statement=(
                    "Locked and minted amounts use linear integer conservation."
                ),
                trace_statement=(
                    "Bridge sessions are finite protocol traces under Dolev-Yao."
                ),
            ),
            providers=("proverif", "tamarin", "z3"),
            property_ids=("safety", "secrecy", "authentication"),
            view_roles=("source",),
            legacy_aliases=("protocol",),
            metadata={
                "consensus_model": "per_chain_declared",
                "finality_model": "source_finality_before_mint",
                "crypto_constructs": ["bridge", "cross_chain_message"],
            },
        ),
        _route(
            CryptoNetworkViewKind.WALLETS,
            view_id="crypto-ir-view/wallets/v1",
            family_id="authorization",
            profile_id="crypto_network_wallets",
            description="Wallet control, signing authority, and account permission views.",
            support=RouteSupport.TRANSLATED,
            assumptions=_default_assumptions(
                "wallets",
                attacker="custom",
                consensus="not_applicable",
                finality="not_applicable",
                bound="finite_principal_set",
                arithmetic="not_applicable",
                trace="not_applicable",
                attacker_statement=(
                    "Attacker may control unauthorized principals; key compromise "
                    "outside the model is excluded."
                ),
                consensus_statement=(
                    "Wallet authorization is independent of chain consensus rules."
                ),
                finality_statement=(
                    "Wallet permission checks do not claim ledger finality."
                ),
                bound_statement=(
                    "Principals, keys, and accounts form a finite declared set."
                ),
                arithmetic_statement=(
                    "Authorization is rule-based; numeric arithmetic is N/A."
                ),
                trace_statement=(
                    "Wallet permission obligations are not temporal-trace claims."
                ),
            ),
            providers=("datalog_secpal", "z3"),
            property_ids=("authorization", "safety"),
            view_roles=("source", "verification_condition"),
            legacy_aliases=("datalog",),
            metadata={
                "consensus_model": "not_applicable",
                "finality_model": "not_applicable",
                "crypto_constructs": ["wallet", "signing_authority"],
            },
        ),
        _route(
            CryptoNetworkViewKind.PERMISSIONS,
            view_id="crypto-ir-view/authorization/v1",
            family_id="authorization",
            profile_id="crypto_network_permissions",
            description="Authorization and compliance policy views for crypto networks.",
            support=RouteSupport.TRANSLATED,
            assumptions=_default_assumptions(
                "permissions",
                attacker="none",
                consensus="not_applicable",
                finality="not_applicable",
                bound="finite_policy_world",
                arithmetic="not_applicable",
                trace="not_applicable",
                attacker_statement=(
                    "Policy evaluation assumes a closed declared world; no network adversary."
                ),
                consensus_statement=(
                    "Permissions are policy-layer; consensus is not part of this view."
                ),
                finality_statement=(
                    "Permissions do not assert finality of on-chain state."
                ),
                bound_statement=(
                    "Policy worlds and principals are finite and declared."
                ),
                arithmetic_statement=(
                    "Permission rules do not rely on arithmetic semantics."
                ),
                trace_statement=(
                    "Permission obligations are Horn/authorization, not traces."
                ),
            ),
            providers=("datalog_secpal",),
            property_ids=("authorization",),
            view_roles=("source",),
            legacy_aliases=("datalog",),
            metadata={
                "consensus_model": "not_applicable",
                "finality_model": "not_applicable",
                "crypto_constructs": ["permission", "compliance"],
            },
        ),
        _route(
            CryptoNetworkViewKind.SYMBOLIC_PROTOCOLS,
            view_id="crypto-ir-view/protocol/v1",
            family_id="cryptographic_protocol",
            profile_id="crypto_network_symbolic_protocol",
            description=(
                "Symbolic wallet/bridge/network protocol secrecy and authentication."
            ),
            support=RouteSupport.TRANSLATED,
            assumptions=_default_assumptions(
                "symbolic_protocols",
                attacker="dolev_yao",
                consensus="not_applicable",
                finality="not_applicable",
                bound="finite_session_depth",
                arithmetic="not_applicable",
                trace="finite",
                attacker_statement=(
                    "Dolev-Yao attacker with perfect cryptography over-approximation."
                ),
                consensus_statement=(
                    "Symbolic protocol views do not encode ledger consensus."
                ),
                finality_statement=(
                    "Symbolic protocol views do not encode chain finality."
                ),
                bound_statement=(
                    "Session and term depth are finite under the controlled subset."
                ),
                arithmetic_statement=(
                    "Symbolic crypto terms are non-arithmetic (perfect crypto)."
                ),
                trace_statement=(
                    "Protocol runs are finite symbolic traces under the attacker model."
                ),
            ),
            providers=("proverif", "tamarin"),
            property_ids=("secrecy", "authentication"),
            view_roles=("source",),
            legacy_aliases=("protocol",),
            metadata={
                "consensus_model": "not_applicable",
                "finality_model": "not_applicable",
                "crypto_constructs": ["protocol", "session", "channel"],
            },
        ),
        _route(
            CryptoNetworkViewKind.ARITHMETIC,
            view_id="crypto-ir-view/smt/v1",
            family_id="first_order",
            profile_id="crypto_network_arithmetic",
            description="SMT arithmetic invariants for amounts, fees, and overflow bounds.",
            support=RouteSupport.NATIVE,
            assumptions=_default_assumptions(
                "arithmetic",
                attacker="none",
                consensus="not_applicable",
                finality="not_applicable",
                bound="bitwidth_or_domain_finite",
                arithmetic="linear_integer",
                trace="not_applicable",
                attacker_statement=(
                    "Arithmetic invariants assume no adversarial model beyond the formula."
                ),
                consensus_statement=(
                    "Arithmetic views are ledger-value constraints, not consensus."
                ),
                finality_statement=(
                    "Arithmetic views do not claim finality."
                ),
                bound_statement=(
                    "Domain size / bit-width bounds are finite and explicit."
                ),
                arithmetic_statement=(
                    "Default arithmetic is linear integer; bitvector when declared."
                ),
                trace_statement=(
                    "Arithmetic obligations are quantifier-free FOL/SMT, not traces."
                ),
            ),
            providers=("z3", "cvc5"),
            notation_id="smt_lib2",
            property_ids=("safety", "satisfiability", "validity"),
            view_roles=("verification_condition",),
            legacy_aliases=("smt_lib", "fol"),
            authority_ceiling="exact",
            metadata={
                "consensus_model": "not_applicable",
                "finality_model": "not_applicable",
                "crypto_constructs": ["arithmetic", "overflow", "fee"],
                "observed_family_label": "smt",
            },
        ),
        _route(
            CryptoNetworkViewKind.PRIVACY,
            view_id="crypto-ir-view/hyperproperty/v1",
            family_id="hyperproperty",
            profile_id="crypto_network_privacy",
            description=(
                "Anonymity and relational privacy hyperproperties for crypto networks."
            ),
            support=RouteSupport.BOUNDED,
            assumptions=_default_assumptions(
                "privacy",
                attacker="custom",
                consensus="not_applicable",
                finality="not_applicable",
                bound="finite_hypertrace_window",
                arithmetic="not_applicable",
                trace="finite",
                attacker_statement=(
                    "Observer/attacker is a declared relational adversary; "
                    "computational ZK is not claimed."
                ),
                consensus_statement=(
                    "Privacy hyperproperties are independent of consensus identity."
                ),
                finality_statement=(
                    "Privacy views do not assert ledger finality."
                ),
                bound_statement=(
                    "Hypertrace window and alternation bounds are finite."
                ),
                arithmetic_statement=(
                    "Relational privacy does not rely on arithmetic theories."
                ),
                trace_statement=(
                    "Privacy compares finite hypertraces under the quantifier prefix."
                ),
            ),
            providers=("hyperltl_autohyper_mchyper",),
            property_ids=("noninterference", "secrecy"),
            view_roles=("source",),
            legacy_aliases=(),
            metadata={
                "consensus_model": "not_applicable",
                "finality_model": "not_applicable",
                "crypto_constructs": ["privacy", "anonymity", "hyperproperty"],
                "zk_claim": False,
                "probabilistic_claim": False,
            },
        ),
    )


def default_crypto_network_view_registry() -> ViewRegistry:
    """Formalization ViewRegistry for cryptocurrency-network views."""

    views: list[FormalizationView] = []
    for route in default_crypto_network_routes():
        views.append(
            FormalizationView(
                view_id=route.view_id,
                logic_family=route.family_id,
                description=route.description,
                capabilities=(
                    "typed_symbols",
                    "source_grounding",
                    "named_assumptions",
                    "legacy_label_canonicalization",
                ),
                metadata={
                    "authority_ceiling": route.authority_ceiling,
                    "crypto_network_view": route.view_kind.value,
                    "implies_future_claims": False,
                    "profile_id": route.profile_id,
                    "providers": list(route.providers),
                    "support": route.support.value,
                },
            )
        )
    return ViewRegistry(
        tuple(views),
        registry_id="crypto-ir-network-formalization-views",
    )


def default_crypto_network_profiles() -> Mapping[str, SemanticProfile]:
    """SemanticProfile@1 instances keyed by profile_id for network routes."""

    profiles: dict[str, SemanticProfile] = {}
    specs: tuple[tuple[str, str, tuple[str, ...], AttackerModel, ArithmeticSemantics, TraceModel, str], ...] = (
        (
            "crypto_network_transactions",
            "Crypto network transactions",
            ("transition_system", "first_order"),
            AttackerModel.NONE,
            ArithmeticSemantics.LINEAR_INTEGER,
            TraceModel.FINITE,
            "Finite ledger transaction transitions with LIA amounts.",
        ),
        (
            "crypto_network_balances",
            "Crypto network balances",
            ("first_order",),
            AttackerModel.NONE,
            ArithmeticSemantics.LINEAR_INTEGER,
            TraceModel.NOT_APPLICABLE,
            "Closed-world balance conservation under LIA.",
        ),
        (
            "crypto_network_consensus",
            "Crypto network consensus",
            ("transition_system",),
            AttackerModel.CUSTOM,
            ArithmeticSemantics.NOT_APPLICABLE,
            TraceModel.FINITE,
            "Finite validator consensus with declared adversary coalition.",
        ),
        (
            "crypto_network_reorg_finality",
            "Crypto network reorg/finality",
            ("transition_system", "temporal"),
            AttackerModel.CUSTOM,
            ArithmeticSemantics.NOT_APPLICABLE,
            TraceModel.FINITE,
            "Bounded reorg depth and finality predicates.",
        ),
        (
            "crypto_network_bridges",
            "Crypto network bridges",
            ("cryptographic_protocol", "first_order"),
            AttackerModel.DOLEV_YAO,
            ArithmeticSemantics.LINEAR_INTEGER,
            TraceModel.FINITE,
            "Cross-chain bridge protocol with Dolev-Yao and LIA amounts.",
        ),
        (
            "crypto_network_wallets",
            "Crypto network wallets",
            ("authorization",),
            AttackerModel.CUSTOM,
            ArithmeticSemantics.NOT_APPLICABLE,
            TraceModel.NOT_APPLICABLE,
            "Wallet signing and account authorization.",
        ),
        (
            "crypto_network_permissions",
            "Crypto network permissions",
            ("authorization", "datalog"),
            AttackerModel.NONE,
            ArithmeticSemantics.NOT_APPLICABLE,
            TraceModel.NOT_APPLICABLE,
            "Policy/compliance authorization world.",
        ),
        (
            "crypto_network_symbolic_protocol",
            "Crypto network symbolic protocol",
            ("cryptographic_protocol",),
            AttackerModel.DOLEV_YAO,
            ArithmeticSemantics.NOT_APPLICABLE,
            TraceModel.FINITE,
            "Symbolic applied-pi style network protocols.",
        ),
        (
            "crypto_network_arithmetic",
            "Crypto network arithmetic",
            ("first_order",),
            AttackerModel.NONE,
            ArithmeticSemantics.LINEAR_INTEGER,
            TraceModel.NOT_APPLICABLE,
            "SMT arithmetic invariants for ledger values.",
        ),
        (
            "crypto_network_privacy",
            "Crypto network privacy",
            ("hyperproperty",),
            AttackerModel.CUSTOM,
            ArithmeticSemantics.NOT_APPLICABLE,
            TraceModel.FINITE,
            "Bounded relational privacy hyperproperties (not ZK).",
        ),
    )
    for profile_id, name, families, attacker, arithmetic, trace, desc in specs:
        theories: tuple[str, ...] = ()
        if arithmetic is ArithmeticSemantics.LINEAR_INTEGER:
            theories = ("qf_lia",)
        # CUSTOM attacker requires at least one equational theory when used
        # with AttackerProfile validation — supply a modeling placeholder.
        equational: tuple[str, ...] = ()
        if attacker is AttackerModel.CUSTOM:
            equational = ("declared_adversary_coalition",)
        profile = _build_semantic_profile(
            profile_id=profile_id,
            name=name,
            family_ids=families,
            attacker=attacker if attacker is not AttackerModel.CUSTOM else AttackerModel.NONE,
            arithmetic=arithmetic,
            trace=trace,
            theories=theories,
            description=desc,
        )
        # Rebuild when custom attacker needs equational theories, or when the
        # privacy route needs an explicit finite hypertrace bound.
        hypertrace = profile.hypertrace
        if profile_id == "crypto_network_privacy":
            hypertrace = HypertraceProfile(
                quantifier_prefix=("forall", "exists"),
                max_alternation=1,
                supported=True,
            )
        if equational or profile_id == "crypto_network_privacy":
            profile = SemanticProfile(
                profile_id=profile.profile_id,
                name=profile.name,
                consequence=profile.consequence,
                world_policy=profile.world_policy,
                description=profile.description,
                bounds=profile.bounds,
                traces=profile.traces,
                time=profile.time,
                frames=profile.frames,
                norms=profile.norms,
                attacker=(
                    AttackerProfile(
                        model=AttackerModel.CUSTOM,
                        equational_theories=equational
                        or ("declared_observer_adversary",),
                        notes=(
                            "Declared crypto-network adversary coalition "
                            "(not computational ZK)."
                        ),
                    )
                    if equational or profile_id == "crypto_network_privacy"
                    else profile.attacker
                ),
                hypertrace=hypertrace,
                smt_theory=profile.smt_theory,
                kernel_environment=profile.kernel_environment,
                family_ids=profile.family_ids,
                fragment_ids=profile.fragment_ids,
                version=profile.version,
            )
        profiles[profile_id] = profile
    return MappingProxyType(profiles)


# ---------------------------------------------------------------------------
# Label canonicalization
# ---------------------------------------------------------------------------


def diagnose_legacy_logic_family(
    label: LogicFamily | str,
    *,
    alias_registry: LogicAliasRegistry | None = None,
) -> LegacyLogicFamilyDiagnostic:
    """Diagnose a legacy crypto LogicFamily label without raising.

    Returns an ok diagnostic when the label canonicalizes; otherwise records
    the rejection reason.  Future probabilistic/ZK labels are always rejected.
    """

    raw = label.value if isinstance(label, LogicFamily) else str(label)
    try:
        normalized = _normalize_label(raw)
    except CryptoNetworkAdapterError as exc:
        return LegacyLogicFamilyDiagnostic(
            input_label=str(label),
            disposition=LabelDisposition.REJECTED_UNKNOWN,
            message=str(exc),
            ok=False,
        )

    try:
        _reject_future_claim(normalized)
    except FutureClaimRejectedError as exc:
        return LegacyLogicFamilyDiagnostic(
            input_label=raw,
            disposition=LabelDisposition.REJECTED_FUTURE,
            message=str(exc),
            ok=False,
        )

    planned = _LEGACY_LOGIC_FAMILY_CANONICAL.get(normalized)
    if planned is not None:
        family_id, profile_id, notation_id, notes = planned
        if family_id == "unsupported":
            return LegacyLogicFamilyDiagnostic(
                input_label=raw,
                disposition=LabelDisposition.ALIAS,
                family_id="",
                profile_id=profile_id or "",
                notation_id=notation_id or "",
                message=notes + "; non-executable labels do not yield a route family",
                ok=False,
            )
        disposition = (
            LabelDisposition.CANONICAL
            if normalized == family_id
            else LabelDisposition.ALIAS
        )
        return LegacyLogicFamilyDiagnostic(
            input_label=raw,
            disposition=disposition,
            family_id=family_id,
            profile_id=profile_id or "",
            notation_id=notation_id or "",
            message=notes,
            ok=True,
        )

    # Fall back to baseline alias / namespace dual-read for family namespace.
    registry = alias_registry if alias_registry is not None else BASELINE_ALIAS_REGISTRY
    try:
        identity, migration = dual_read(NamespaceKind.FAMILY, raw, registry=registry)
    except WrongNamespaceError as exc:
        return LegacyLogicFamilyDiagnostic(
            input_label=raw,
            disposition=LabelDisposition.REJECTED_WRONG_NAMESPACE,
            message=str(exc),
            ok=False,
        )
    except UnknownAliasError as exc:
        # Try notation namespace for smt_lib-like labels not in local table.
        try:
            notation, _notation_diag = dual_read(
                NamespaceKind.NOTATION, raw, registry=registry
            )
        except (UnknownAliasError, WrongNamespaceError):
            return LegacyLogicFamilyDiagnostic(
                input_label=raw,
                disposition=LabelDisposition.REJECTED_UNKNOWN,
                message=str(exc),
                ok=False,
            )
        return LegacyLogicFamilyDiagnostic(
            input_label=raw,
            disposition=LabelDisposition.ALIAS,
            family_id="first_order",
            notation_id=notation.value,
            message=(
                f"label {raw!r} is notation {notation.qualified}; "
                "canonical family is first_order"
            ),
            ok=True,
        )

    if identity.value in FUTURE_UNSUPPORTED_FAMILY_CLAIMS:
        return LegacyLogicFamilyDiagnostic(
            input_label=raw,
            disposition=LabelDisposition.REJECTED_FUTURE,
            family_id=identity.value,
            message=(
                f"canonical family {identity.value!r} is a future/unsupported claim"
            ),
            ok=False,
        )

    disposition = (
        LabelDisposition.CANONICAL
        if migration.disposition is MigrationDisposition.CANONICAL
        else LabelDisposition.ALIAS
    )
    return LegacyLogicFamilyDiagnostic(
        input_label=raw,
        disposition=disposition,
        family_id=identity.value,
        message=migration.message,
        ok=True,
    )


def canonicalize_legacy_logic_family(
    label: LogicFamily | str,
    *,
    alias_registry: LogicAliasRegistry | None = None,
) -> tuple[str, LegacyLogicFamilyDiagnostic]:
    """Canonicalize a legacy LogicFamily label or fail closed.

    Returns ``(family_id, diagnostic)``.  Non-executable and unknown labels
    raise :class:`UnknownLogicFamilyLabelError`.  Future probabilistic/ZK
    labels raise :class:`FutureClaimRejectedError`.
    """

    diagnostic = diagnose_legacy_logic_family(label, alias_registry=alias_registry)
    if diagnostic.disposition is LabelDisposition.REJECTED_FUTURE:
        raise FutureClaimRejectedError(diagnostic.message)
    if not diagnostic.ok or not diagnostic.family_id:
        raise UnknownLogicFamilyLabelError(
            diagnostic.message
            or f"cannot canonicalize logic family label {diagnostic.input_label!r}"
        )
    if diagnostic.family_id not in _ADMITTED_CANONICAL_FAMILIES:
        # Allow intermediate family IDs that exist in the global catalog but
        # still reject future claims (already handled) and pure unsupported.
        try:
            BASELINE_NAMESPACES.get(NamespaceKind.FAMILY, diagnostic.family_id)
        except UnknownIdentityError as exc:
            raise UnknownLogicFamilyLabelError(
                f"canonical family {diagnostic.family_id!r} is not registered"
            ) from exc
        if diagnostic.family_id in FUTURE_UNSUPPORTED_FAMILY_CLAIMS:
            raise FutureClaimRejectedError(
                f"family {diagnostic.family_id!r} is a future claim"
            )
    return diagnostic.family_id, diagnostic


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CryptoNetworkFormalizationAdapter:
    """Typed formalization adapter for crypto_ir cryptocurrency-network views.

    Interface: ``CryptoNetworkFormalizationAdapter@1``.

    The adapter owns route catalog, assumption naming, and legacy LogicFamily
    dual-read canonicalization.  It does not execute solvers and does not
    elevate proof authority.
    """

    INTERFACE: ClassVar[str] = CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE
    interface: ClassVar[str] = CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE
    version: ClassVar[str] = CRYPTO_NETWORK_FORMALIZATION_ADAPTER_VERSION

    def __init__(
        self,
        *,
        routes: Sequence[CryptoNetworkRoute] | None = None,
        profiles: Mapping[str, SemanticProfile] | None = None,
        view_registry: ViewRegistry | None = None,
        alias_registry: LogicAliasRegistry | None = None,
    ) -> None:
        catalog = tuple(routes) if routes is not None else default_crypto_network_routes()
        if not catalog:
            raise CryptoNetworkAdapterError(
                "route catalog must be non-empty",
                code=CODE_MALFORMED,
                path="routes",
            )
        by_kind: dict[CryptoNetworkViewKind, CryptoNetworkRoute] = {}
        by_view_id: dict[str, CryptoNetworkRoute] = {}
        for route in catalog:
            if route.view_kind in by_kind:
                raise CryptoNetworkAdapterError(
                    f"duplicate view kind {route.view_kind.value!r}",
                    code=CODE_MALFORMED,
                    path="routes",
                )
            if route.view_id in by_view_id:
                raise CryptoNetworkAdapterError(
                    f"duplicate view_id {route.view_id!r}",
                    code=CODE_MALFORMED,
                    path="routes",
                )
            by_kind[route.view_kind] = route
            by_view_id[route.view_id] = route
        self._routes = catalog
        self._by_kind = MappingProxyType(by_kind)
        self._by_view_id = MappingProxyType(by_view_id)
        self._profiles = (
            MappingProxyType(dict(profiles))
            if profiles is not None
            else default_crypto_network_profiles()
        )
        self._view_registry = (
            view_registry
            if view_registry is not None
            else default_crypto_network_view_registry()
        )
        self._alias_registry = (
            alias_registry
            if alias_registry is not None
            else BASELINE_ALIAS_REGISTRY
        )

    @property
    def domain_id(self) -> str:
        return CRYPTO_IR_DOMAIN_ID

    @property
    def routes(self) -> tuple[CryptoNetworkRoute, ...]:
        return self._routes

    @property
    def view_registry(self) -> ViewRegistry:
        return self._view_registry

    @property
    def profiles(self) -> Mapping[str, SemanticProfile]:
        return self._profiles

    def known_views(self) -> tuple[str, ...]:
        return tuple(route.view_kind.value for route in self._routes)

    def known_view_ids(self) -> tuple[str, ...]:
        return tuple(route.view_id for route in self._routes)

    def route_for(
        self, view: CryptoNetworkViewKind | str
    ) -> CryptoNetworkRoute:
        """Resolve a typed route by view kind or view_id."""

        if isinstance(view, CryptoNetworkViewKind):
            try:
                return self._by_kind[view]
            except KeyError as exc:
                raise CryptoNetworkAdapterError(
                    f"unknown crypto-network view kind {view.value!r}",
                    code=CODE_UNKNOWN_VIEW,
                    path="view",
                ) from exc
        text = _text(view, "view")
        # Accept kind value or view_id.
        try:
            kind = CryptoNetworkViewKind(text)
            return self._by_kind[kind]
        except (ValueError, KeyError):
            pass
        try:
            return self._by_view_id[text]
        except KeyError as exc:
            raise CryptoNetworkAdapterError(
                f"unknown crypto-network view {text!r}",
                code=CODE_UNKNOWN_VIEW,
                path="view",
            ) from exc

    def profile_for(
        self, view: CryptoNetworkViewKind | str
    ) -> SemanticProfile:
        route = self.route_for(view)
        try:
            return self._profiles[route.profile_id]
        except KeyError as exc:
            raise CryptoNetworkAdapterError(
                f"missing semantic profile {route.profile_id!r}",
                code=CODE_MALFORMED,
                path="profile_id",
            ) from exc

    def assumptions_for(
        self, view: CryptoNetworkViewKind | str
    ) -> tuple[NetworkAssumption, ...]:
        return self.route_for(view).assumptions

    def diagnose_logic_family(
        self, label: LogicFamily | str
    ) -> LegacyLogicFamilyDiagnostic:
        return diagnose_legacy_logic_family(
            label, alias_registry=self._alias_registry
        )

    def canonicalize_logic_family(
        self, label: LogicFamily | str
    ) -> tuple[str, LegacyLogicFamilyDiagnostic]:
        return canonicalize_legacy_logic_family(
            label, alias_registry=self._alias_registry
        )

    def route_for_legacy_logic_family(
        self,
        label: LogicFamily | str,
        *,
        preferred_view: CryptoNetworkViewKind | str | None = None,
    ) -> tuple[CryptoNetworkRoute, LegacyLogicFamilyDiagnostic]:
        """Map a legacy LogicFamily label to a compatible typed network route.

        When *preferred_view* is supplied, the route must match that view and
        its family must equal the canonicalized family.  Otherwise the first
        route whose family matches (preferring arithmetic/SMT for ``smt_lib``)
        is selected.
        """

        family_id, diagnostic = self.canonicalize_logic_family(label)
        if preferred_view is not None:
            route = self.route_for(preferred_view)
            if route.family_id != family_id:
                raise CryptoNetworkAdapterError(
                    f"view {route.view_id!r} family {route.family_id!r} does not "
                    f"match canonicalized family {family_id!r} for label "
                    f"{diagnostic.input_label!r}",
                    code=CODE_ROUTE,
                    path="preferred_view",
                )
            return route, diagnostic

        # Preference order for SMT/FOL aliases: arithmetic then balances then
        # any first_order route.
        preferred_kinds = (
            CryptoNetworkViewKind.ARITHMETIC,
            CryptoNetworkViewKind.BALANCES,
            CryptoNetworkViewKind.TRANSACTIONS,
        )
        for kind in preferred_kinds:
            route = self._by_kind.get(kind)
            if route is not None and route.family_id == family_id:
                return route, diagnostic
        for route in self._routes:
            if route.family_id == family_id:
                return route, diagnostic
        raise CryptoNetworkAdapterError(
            f"no crypto-network route admits family {family_id!r}",
            code=CODE_ROUTE,
            path="logic_family",
        )

    def assert_no_future_claims(self) -> None:
        """Fail closed if any route implies probabilistic/ZK/wave-4 claims."""

        for route in self._routes:
            if route.implies_future_claims:
                raise FutureClaimRejectedError(
                    f"route {route.view_id!r} implies future claims",
                    path=route.view_id,
                )
            _reject_future_claim(route.family_id, path=route.view_id)
            for key in ("zk_claim", "probabilistic_claim", "finite_field_claim"):
                if route.metadata.get(key) is True:
                    raise FutureClaimRejectedError(
                        f"route {route.view_id!r} metadata asserts {key}=True",
                        path=route.view_id,
                    )
            profile = self._profiles.get(route.profile_id)
            if profile is not None:
                for family in profile.family_ids:
                    _reject_future_claim(family, path=f"{route.view_id}.profile")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_version": self.version,
            "domain_id": self.domain_id,
            "implies_future_claims": False,
            "interface": self.interface,
            "module_version": CRYPTO_NETWORK_ADAPTER_MODULE_VERSION,
            "profiles": {
                key: value.to_dict() for key, value in sorted(self._profiles.items())
            },
            "required_assumption_kinds": list(REQUIRED_ASSUMPTION_KINDS),
            "routes": [route.to_dict() for route in self._routes],
            "view_registry": self._view_registry.to_dict(),
        }


def adapt_crypto_network_view(
    view: CryptoNetworkViewKind | str,
    *,
    adapter: CryptoNetworkFormalizationAdapter | None = None,
) -> CryptoNetworkRoute:
    """Functional convenience: resolve one typed crypto-network route."""

    active = adapter if adapter is not None else CryptoNetworkFormalizationAdapter()
    return active.route_for(view)


def canonicalize_crypto_logic_family(
    label: LogicFamily | str,
    *,
    adapter: CryptoNetworkFormalizationAdapter | None = None,
) -> tuple[str, LegacyLogicFamilyDiagnostic]:
    """Functional convenience: canonicalize a legacy LogicFamily label."""

    active = adapter if adapter is not None else CryptoNetworkFormalizationAdapter()
    return active.canonicalize_logic_family(label)


__all__ = [
    "CRYPTO_IR_DOMAIN_ID",
    "CRYPTO_NETWORK_ADAPTER_MODULE_VERSION",
    "CRYPTO_NETWORK_ASSUMPTION_SCHEMA",
    "CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE",
    "CRYPTO_NETWORK_FORMALIZATION_ADAPTER_VERSION",
    "CRYPTO_NETWORK_LABEL_DIAGNOSTIC_SCHEMA",
    "CRYPTO_NETWORK_ROUTE_SCHEMA",
    "FUTURE_UNSUPPORTED_FAMILY_CLAIMS",
    "REQUIRED_ASSUMPTION_KINDS",
    "CODE_FUTURE_CLAIM",
    "CODE_MALFORMED",
    "CODE_MISSING_ASSUMPTION",
    "CODE_ROUTE",
    "CODE_UNKNOWN_LABEL",
    "CODE_UNKNOWN_VIEW",
    "CODE_WRONG_NAMESPACE",
    "CryptoNetworkAdapterError",
    "CryptoNetworkFormalizationAdapter",
    "CryptoNetworkRoute",
    "CryptoNetworkViewKind",
    "FutureClaimRejectedError",
    "LabelDisposition",
    "LegacyLogicFamilyDiagnostic",
    "NetworkAssumption",
    "NetworkAssumptionKind",
    "RouteSupport",
    "UnknownLogicFamilyLabelError",
    "adapt_crypto_network_view",
    "canonicalize_crypto_logic_family",
    "canonicalize_legacy_logic_family",
    "default_crypto_network_profiles",
    "default_crypto_network_routes",
    "default_crypto_network_view_registry",
    "diagnose_legacy_logic_family",
]
