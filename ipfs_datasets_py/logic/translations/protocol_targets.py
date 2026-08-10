"""Neutral-protocol to ProVerif/Tamarin translation edges.

``ProtocolTargetTranslationEdges@1`` publishes reviewed
:class:`~ipfs_datasets_py.logic.families.translations.TranslationContract`
routes that lower a dialect-neutral symbolic-protocol IR into:

* ProVerif applied-pi encodings; and
* Tamarin multiset-rewriting encodings.

Dialect-specific axes remain explicit on every edge (never inferred from
family names alone):

* equational theory / equations;
* roles (ProVerif processes) vs rules (Tamarin multiset rules);
* channels / public network model;
* attacker / adversary semantics; and
* query / lemma identities.

Every edge carries mandatory loss receipts.  Dialect constructs that have no
sound image on the other backend fail closed before any target obligation is
emitted.  Protocol results remain protocol/symbolic evidence — never theorem
authority.
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

PROTOCOL_TARGET_EDGES_INTERFACE: Final = "ProtocolTargetTranslationEdges@1"
PROTOCOL_TARGET_EDGES_SCHEMA: Final = "logic-protocol-target-translation-edges/v1"
PROTOCOL_EDGE_SCHEMA: Final = "logic-protocol-target-translation-edge/v1"
PROTOCOL_DIALECT_RECEIPT_SCHEMA: Final = "logic-protocol-dialect-receipt/v1"
PROTOCOL_LOSS_SCHEMA: Final = "logic-protocol-translation-loss/v1"
PROTOCOL_LOWERING_RESULT_SCHEMA: Final = "logic-protocol-lowering-result/v1"
EDGE_IDENTITY_DOMAIN: Final = "logic.translation.protocol_target.edge"
EDGES_IDENTITY_DOMAIN: Final = "logic.translation.protocol_target.edges"
LOWERING_IDENTITY_DOMAIN: Final = "logic.translation.protocol_target.lowering"
RECEIPT_IDENTITY_DOMAIN: Final = "logic.translation.protocol_target.receipt"

COMPILER_IDENTITY: Final = "compiler:protocol-target@1"
PROFILE_IDENTITY: Final = "profile:protocol-target-default@1"
CONFIG_IDENTITY: Final = "config:protocol-target-translation-edges@1"
ENVIRONMENT_IDENTITY: Final = "sha256:env:protocol-target-translation@1"

# Neutral source and dialect targets.
SOURCE_SYMBOLIC_PROTOCOL: Final = "cryptographic_protocol"
TARGET_PROVERIF: Final = "proverif_applied_pi"
TARGET_TAMARIN: Final = "tamarin_multiset_rewriting"

VIEW_NEUTRAL: Final = "neutral_protocol"
VIEW_PROVERIF: Final = "proverif_applied_pi"
VIEW_TAMARIN: Final = "tamarin_multiset_rewriting"

# Canonical feature identifiers for symbolic protocol obligations.
FEAT_PROTOCOL_ROLES: Final = "feat_protocol_roles"
FEAT_PROTOCOL_PROCESSES: Final = "feat_protocol_processes"
FEAT_PROTOCOL_EQUATIONS: Final = "feat_protocol_equations"
FEAT_PROTOCOL_CHANNELS: Final = "feat_protocol_channels"
FEAT_PROTOCOL_EVENTS: Final = "feat_protocol_events"
FEAT_PROTOCOL_CLAIMS: Final = "feat_protocol_claims"
FEAT_PROTOCOL_SECRECY: Final = "feat_protocol_secrecy"
FEAT_PROTOCOL_AUTHENTICATION: Final = "feat_protocol_authentication"
FEAT_PROTOCOL_CORRESPONDENCE: Final = "feat_protocol_correspondence"
FEAT_PROTOCOL_REACHABILITY: Final = "feat_protocol_reachability"
FEAT_ATTACKER_DOLEV_YAO: Final = "feat_attacker_dolev_yao"
FEAT_PERFECT_CRYPTO: Final = "feat_perfect_cryptography"
FEAT_PUBLIC_CHANNEL: Final = "feat_public_channel"
FEAT_PRIVATE_CHANNEL: Final = "feat_private_channel"
FEAT_MULTISET_RULES: Final = "feat_multiset_rules"
FEAT_MULTISET_FACTS: Final = "feat_multiset_facts"
FEAT_APPLIED_PI_PROCESS: Final = "feat_applied_pi_process"
FEAT_QUERY_IDENTITY: Final = "feat_query_identity"
FEAT_LEMMA_IDENTITY: Final = "feat_lemma_identity"
FEAT_EQUIVALENCE_CLAIM: Final = "feat_equivalence_claim"
FEAT_DIFF_EQUIVALENCE: Final = "feat_diff_equivalence"
FEAT_STATEFUL_ORACLES: Final = "feat_stateful_oracles"
FEAT_GLOBAL_STATE: Final = "feat_global_state"
FEAT_COMPUTATIONAL_SOUNDNESS: Final = "feat_computational_soundness"

UNSUPPORTED_CONSTRUCTS: Final = frozenset(
    {
        FEAT_COMPUTATIONAL_SOUNDNESS,
        FEAT_GLOBAL_STATE,
        "construct:computational_soundness",
        "construct:bitstring_adversary",
        "construct:unbounded_sessions_proof",
    }
)

DEFAULT_PROTOCOL_TARGET_TRANSLATION_EDGES: Final = (
    "symbolic_protocol_to_proverif_applied_pi",
    "symbolic_protocol_to_tamarin_multiset_rewriting",
)


class ProtocolTargetTranslationError(ValueError):
    """Raised when a protocol-target edge or lowering is invalid."""


class ProtocolDialect(str, Enum):
    """Closed dialect vocabulary for protocol target encodings."""

    PROVERIF_APPLIED_PI = "proverif_applied_pi"
    TAMARIN_MULTISET_REWRITING = "tamarin_multiset_rewriting"


class EquationTheoryKind(str, Enum):
    """Equational / algebraic theory family (dialect-specific encoding)."""

    FREE = "free"
    PAIRING = "pairing"
    SYMMETRIC_ENCRYPTION = "symmetric_encryption"
    ASYMMETRIC_ENCRYPTION = "asymmetric_encryption"
    SIGNATURES = "signatures"
    HASHING = "hashing"
    XOR = "xor"
    DIFFIE_HELLMAN = "diffie_hellman"
    CUSTOM = "custom"


class RoleRuleKind(str, Enum):
    """How roles/rules are represented in the target dialect."""

    APPLIED_PI_PROCESS = "applied_pi_process"
    MULTISET_RULE = "multiset_rule"
    ROLE_PROCESS = "role_process"


class ChannelModel(str, Enum):
    """Channel / network model declared by the edge."""

    PUBLIC_NETWORK = "public_network"
    PRIVATE_CHANNEL = "private_channel"
    MIXED = "mixed"
    NOT_APPLICABLE = "not_applicable"


class AttackerSemantics(str, Enum):
    """Attacker / adversary model (always explicit)."""

    DOLEV_YAO = "dolev_yao"
    PASSIVE = "passive"
    ACTIVE_BOUNDED = "active_bounded"
    CUSTOM = "custom"
    NOT_APPLICABLE = "not_applicable"


class QueryIdentityKind(str, Enum):
    """How queries / lemmas are identified on the target dialect."""

    PROVERIF_QUERY = "proverif_query"
    TAMARIN_LEMMA = "tamarin_lemma"
    NEUTRAL_CLAIM = "neutral_claim"


class ProtocolLossKind(str, Enum):
    """Closed vocabulary of protocol-translation losses."""

    NONE = "none"
    EQUATION_FRAGMENT = "equation_fragment"
    ROLE_TO_PROCESS = "role_to_process"
    ROLE_TO_RULE = "role_to_rule"
    CHANNEL_COLLAPSE = "channel_collapse"
    ATTACKER_CEILING = "attacker_ceiling"
    QUERY_RENAMING = "query_renaming"
    CLAIM_SUBSET = "claim_subset"
    SESSION_BOUND = "session_bound"
    STATE_ELISION = "state_elision"
    EQUIVALENCE_DROP = "equivalence_drop"


class LoweringStatus(str, Enum):
    """Outcome of applying a reviewed edge to one obligation."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ObligationKind(str, Enum):
    """Source obligation class accepted by protocol-target edges."""

    SECRECY = "secrecy"
    AUTHENTICATION = "authentication"
    CORRESPONDENCE = "correspondence"
    REACHABILITY = "reachability"
    EQUIVALENCE = "equivalence"
    PROTOCOL_DOCUMENT = "protocol_document"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProtocolTargetTranslationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise ProtocolTargetTranslationError(
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
        raise ProtocolTargetTranslationError(
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
            raise ProtocolTargetTranslationError(
                f"{field_name} must not contain duplicates"
            )
        seen.add(text)
        result.append(text)
    return tuple(result)


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolTargetTranslationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProtocolTargetTranslationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ProtocolTargetTranslationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolTargetTranslationError(f"{field_name} must be a bool")
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
        or "bafkreiprotocolsrcaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        target_identity=target_identity
        or "bafkreiprotocoltgtaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        environment_identity=ENVIRONMENT_IDENTITY,
    )


# ---------------------------------------------------------------------------
# Dialect receipts and losses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolDialectReceipt:
    """Mandatory dialect-specific semantic receipt (never omitted).

    Protocol equations, roles/rules, channels, attacker semantics, and query
    identities remain dialect-specific: each field is required at construction.
    """

    dialect: ProtocolDialect | str
    equations: tuple[str, ...]
    equation_theory: EquationTheoryKind | str
    role_rule_kind: RoleRuleKind | str
    roles_or_rules: tuple[str, ...]
    channel_model: ChannelModel | str
    channels: tuple[str, ...]
    attacker_semantics: AttackerSemantics | str
    attacker_assumptions: tuple[str, ...]
    query_identity_kind: QueryIdentityKind | str
    query_identities: tuple[str, ...]
    description: str = ""
    schema_version: str = PROTOCOL_DIALECT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dialect", _enum(self.dialect, ProtocolDialect, "dialect")
        )
        equations = _strings(self.equations, "equations", identifiers=True)
        if not equations:
            raise ProtocolTargetTranslationError(
                "equations must be non-empty (dialect-specific equations required)"
            )
        object.__setattr__(self, "equations", equations)
        object.__setattr__(
            self,
            "equation_theory",
            _enum(self.equation_theory, EquationTheoryKind, "equation_theory"),
        )
        object.__setattr__(
            self,
            "role_rule_kind",
            _enum(self.role_rule_kind, RoleRuleKind, "role_rule_kind"),
        )
        roles = _strings(self.roles_or_rules, "roles_or_rules", identifiers=True)
        if not roles:
            raise ProtocolTargetTranslationError(
                "roles_or_rules must be non-empty (dialect-specific roles/rules required)"
            )
        object.__setattr__(self, "roles_or_rules", roles)
        object.__setattr__(
            self,
            "channel_model",
            _enum(self.channel_model, ChannelModel, "channel_model"),
        )
        channels = _strings(self.channels, "channels", identifiers=True)
        if not channels and self.channel_model is not ChannelModel.NOT_APPLICABLE:
            raise ProtocolTargetTranslationError(
                "channels must be non-empty when channel_model is applicable"
            )
        object.__setattr__(self, "channels", channels)
        object.__setattr__(
            self,
            "attacker_semantics",
            _enum(self.attacker_semantics, AttackerSemantics, "attacker_semantics"),
        )
        attacker = _strings(
            self.attacker_assumptions, "attacker_assumptions", identifiers=True
        )
        if not attacker:
            raise ProtocolTargetTranslationError(
                "attacker_assumptions must be non-empty (attacker semantics required)"
            )
        object.__setattr__(self, "attacker_assumptions", attacker)
        object.__setattr__(
            self,
            "query_identity_kind",
            _enum(self.query_identity_kind, QueryIdentityKind, "query_identity_kind"),
        )
        queries = _strings(
            self.query_identities, "query_identities", identifiers=True
        )
        if not queries:
            raise ProtocolTargetTranslationError(
                "query_identities must be non-empty (dialect-specific query ids required)"
            )
        object.__setattr__(self, "query_identities", queries)
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != PROTOCOL_DIALECT_RECEIPT_SCHEMA:
            raise ProtocolTargetTranslationError(
                f"unsupported dialect receipt schema {self.schema_version!r}"
            )
        # Dialect shape consistency.
        if self.dialect is ProtocolDialect.PROVERIF_APPLIED_PI:
            if self.role_rule_kind not in {
                RoleRuleKind.APPLIED_PI_PROCESS,
                RoleRuleKind.ROLE_PROCESS,
            }:
                raise ProtocolTargetTranslationError(
                    "ProVerif dialect requires applied-pi / role process encoding"
                )
            if self.query_identity_kind is not QueryIdentityKind.PROVERIF_QUERY:
                raise ProtocolTargetTranslationError(
                    "ProVerif dialect requires proverif_query identities"
                )
        if self.dialect is ProtocolDialect.TAMARIN_MULTISET_REWRITING:
            if self.role_rule_kind is not RoleRuleKind.MULTISET_RULE:
                raise ProtocolTargetTranslationError(
                    "Tamarin dialect requires multiset_rule encoding"
                )
            if self.query_identity_kind is not QueryIdentityKind.TAMARIN_LEMMA:
                raise ProtocolTargetTranslationError(
                    "Tamarin dialect requires tamarin_lemma identities"
                )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=RECEIPT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker_assumptions": list(self.attacker_assumptions),
            "attacker_semantics": self.attacker_semantics.value,
            "channel_model": self.channel_model.value,
            "channels": list(self.channels),
            "description": self.description,
            "dialect": self.dialect.value,
            "equation_theory": self.equation_theory.value,
            "equations": list(self.equations),
            "query_identities": list(self.query_identities),
            "query_identity_kind": self.query_identity_kind.value,
            "role_rule_kind": self.role_rule_kind.value,
            "roles_or_rules": list(self.roles_or_rules),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolDialectReceipt":
        value = _mapping(value, "protocol dialect receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attacker_assumptions",
                    "attacker_semantics",
                    "channel_model",
                    "channels",
                    "description",
                    "dialect",
                    "equation_theory",
                    "equations",
                    "query_identities",
                    "query_identity_kind",
                    "role_rule_kind",
                    "roles_or_rules",
                    "schema_version",
                }
            ),
            "protocol dialect receipt",
        )
        return cls(
            dialect=value.get("dialect", ""),
            equations=tuple(value.get("equations", ())),
            equation_theory=value.get("equation_theory", ""),
            role_rule_kind=value.get("role_rule_kind", ""),
            roles_or_rules=tuple(value.get("roles_or_rules", ())),
            channel_model=value.get("channel_model", ""),
            channels=tuple(value.get("channels", ())),
            attacker_semantics=value.get("attacker_semantics", ""),
            attacker_assumptions=tuple(value.get("attacker_assumptions", ())),
            query_identity_kind=value.get("query_identity_kind", ""),
            query_identities=tuple(value.get("query_identities", ())),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", PROTOCOL_DIALECT_RECEIPT_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class ProtocolTranslationLoss:
    """One explicit protocol-translation loss (never silent)."""

    loss_id: str
    kind: ProtocolLossKind | str
    description: str
    source_construct_ids: tuple[str, ...] = ()
    target_construct_ids: tuple[str, ...] = ()
    dialect: ProtocolDialect | str | None = None
    schema_version: str = PROTOCOL_LOSS_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "loss_id", _identifier(self.loss_id, "loss_id"))
        object.__setattr__(
            self, "kind", _enum(self.kind, ProtocolLossKind, "kind")
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
        if self.dialect is not None and self.dialect != "":
            object.__setattr__(
                self, "dialect", _enum(self.dialect, ProtocolDialect, "dialect")
            )
        else:
            object.__setattr__(self, "dialect", None)
        if self.schema_version != PROTOCOL_LOSS_SCHEMA:
            raise ProtocolTargetTranslationError(
                f"unsupported protocol loss schema {self.schema_version!r}"
            )
        if self.kind is ProtocolLossKind.NONE and (
            self.source_construct_ids or self.target_construct_ids
        ):
            raise ProtocolTargetTranslationError(
                "none loss cannot bind source or target construct ids"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "dialect": (
                self.dialect.value
                if isinstance(self.dialect, ProtocolDialect)
                else self.dialect
            ),
            "kind": self.kind.value,
            "loss_id": self.loss_id,
            "schema_version": self.schema_version,
            "source_construct_ids": list(self.source_construct_ids),
            "target_construct_ids": list(self.target_construct_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolTranslationLoss":
        value = _mapping(value, "protocol translation loss")
        _reject_unknown(
            value,
            frozenset(
                {
                    "description",
                    "dialect",
                    "kind",
                    "loss_id",
                    "schema_version",
                    "source_construct_ids",
                    "target_construct_ids",
                }
            ),
            "protocol translation loss",
        )
        return cls(
            loss_id=value.get("loss_id", ""),
            kind=value.get("kind", ""),
            description=value.get("description", ""),
            source_construct_ids=tuple(value.get("source_construct_ids", ())),
            target_construct_ids=tuple(value.get("target_construct_ids", ())),
            dialect=value.get("dialect"),
            schema_version=value.get("schema_version", PROTOCOL_LOSS_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Reviewed edge descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolTargetTranslationEdge:
    """One reviewed neutral-protocol → dialect translation edge."""

    edge_id: str
    contract: TranslationContract
    dialect_receipt: ProtocolDialectReceipt
    losses: tuple[ProtocolTranslationLoss, ...] = ()
    obligation_kinds: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = PROTOCOL_EDGE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        if not isinstance(self.contract, TranslationContract):
            raise ProtocolTargetTranslationError(
                "contract must be a TranslationContract"
            )
        if self.edge_id != self.contract.contract_id:
            raise ProtocolTargetTranslationError(
                "edge_id must equal contract.contract_id"
            )
        if isinstance(self.dialect_receipt, Mapping):
            object.__setattr__(
                self,
                "dialect_receipt",
                ProtocolDialectReceipt.from_dict(self.dialect_receipt),
            )
        if not isinstance(self.dialect_receipt, ProtocolDialectReceipt):
            raise ProtocolTargetTranslationError(
                "dialect_receipt must be a ProtocolDialectReceipt"
            )
        losses: list[ProtocolTranslationLoss] = []
        for item in self.losses:
            if isinstance(item, ProtocolTranslationLoss):
                losses.append(item)
            elif isinstance(item, Mapping):
                losses.append(ProtocolTranslationLoss.from_dict(item))
            else:
                raise ProtocolTargetTranslationError(
                    "losses items must be ProtocolTranslationLoss values"
                )
        object.__setattr__(
            self,
            "losses",
            tuple(sorted(losses, key=lambda item: item.loss_id)),
        )
        kinds = _strings(self.obligation_kinds, "obligation_kinds")
        for kind in kinds:
            _enum(kind, ObligationKind, "obligation_kinds item")
        object.__setattr__(self, "obligation_kinds", kinds)
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != PROTOCOL_EDGE_SCHEMA:
            raise ProtocolTargetTranslationError(
                f"unsupported protocol edge schema {self.schema_version!r}"
            )
        # Loss receipt required whenever approximation is claimed.
        non_none = [
            loss for loss in self.losses if loss.kind is not ProtocolLossKind.NONE
        ]
        if (
            self.contract.preservation
            in {
                PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
                PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION,
                PreservationRelation.BOUNDED,
                PreservationRelation.APPROXIMATE,
            }
            and not non_none
        ):
            raise ProtocolTargetTranslationError(
                "approximating protocol edges require at least one non-none loss receipt"
            )
        if non_none and self.contract.preservation is PreservationRelation.EXACT_EQUIVALENCE:
            raise ProtocolTargetTranslationError(
                "exact_equivalence cannot declare protocol translation losses"
            )
        # Dialect receipt axes must also appear as assumptions / attacker model.
        assumptions = self.contract.assumptions
        if not assumptions.attacker_model:
            raise ProtocolTargetTranslationError(
                "protocol edges require attacker_model assumptions"
            )

    @property
    def source_family_id(self) -> str:
        return self.contract.source.family_id

    @property
    def target_family_id(self) -> str:
        return self.contract.target.family_id

    @property
    def dialect(self) -> ProtocolDialect:
        return self.dialect_receipt.dialect  # type: ignore[return-value]

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
    def loss_ids(self) -> tuple[str, ...]:
        return tuple(loss.loss_id for loss in self.losses)

    @property
    def is_loss_receipted(self) -> bool:
        """True when every non-trivial loss is recorded, or exact with none."""

        if self.contract.preservation is PreservationRelation.EXACT_EQUIVALENCE:
            return all(loss.kind is ProtocolLossKind.NONE for loss in self.losses)
        return any(loss.kind is not ProtocolLossKind.NONE for loss in self.losses)

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
            "dialect_receipt": self.dialect_receipt.to_dict(),
            "edge_id": self.edge_id,
            "losses": [loss.to_dict() for loss in self.losses],
            "obligation_kinds": list(self.obligation_kinds),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract"] = self.contract.to_dict()
        payload["content_id"] = self.content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolTargetTranslationEdge":
        value = _mapping(value, "protocol target translation edge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "content_id",
                    "contract",
                    "contract_content_id",
                    "contract_id",
                    "description",
                    "dialect_receipt",
                    "edge_id",
                    "losses",
                    "obligation_kinds",
                    "schema_version",
                }
            ),
            "protocol target translation edge",
        )
        contract_value = value.get("contract")
        if not isinstance(contract_value, Mapping):
            raise ProtocolTargetTranslationError("contract must be a mapping")
        return cls(
            edge_id=value.get("edge_id", ""),
            contract=TranslationContract.from_dict(contract_value),
            dialect_receipt=value.get("dialect_receipt", {}),  # type: ignore[arg-type]
            losses=tuple(value.get("losses", ())),
            obligation_kinds=tuple(value.get("obligation_kinds", ())),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", PROTOCOL_EDGE_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Edge construction
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


def _neutral_source(*, profile: str, fragment: str) -> TranslationEndpoint:
    return _endpoint(
        SOURCE_SYMBOLIC_PROTOCOL,
        profile_id=profile,
        fragment_id=fragment,
        schema_id="symbolic_protocol_ir_schema",
        notation_id="neutral_protocol_surface",
        content_identity=f"sha256:protocol:neutral:{profile}:{fragment}",
    )


def _proverif_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_PROVERIF,
        profile_id="applied_pi_controlled",
        fragment_id="applied_pi_core",
        schema_id="proverif_applied_pi_schema",
        notation_id="proverif_source",
        content_identity="sha256:protocol:proverif:applied_pi",
    )


def _tamarin_target() -> TranslationEndpoint:
    return _endpoint(
        TARGET_TAMARIN,
        profile_id="multiset_rewriting_controlled",
        fragment_id="spthy_core",
        schema_id="tamarin_multiset_schema",
        notation_id="tamarin_spthy",
        content_identity="sha256:protocol:tamarin:multiset",
    )


def _proverif_nodes() -> tuple[NodeMapEntry, ...]:
    return (
        _node("n_role", "pv_process", disposition=NodeDisposition.MAPPED),
        _node("n_process", "pv_process", disposition=NodeDisposition.MAPPED),
        _node("n_equation", "pv_equation", disposition=NodeDisposition.MAPPED),
        _node("n_channel", "pv_channel", disposition=NodeDisposition.MAPPED),
        _node("n_event", "pv_event", disposition=NodeDisposition.MAPPED),
        _node("n_claim_secrecy", "pv_query", disposition=NodeDisposition.MAPPED),
        _node(
            "n_claim_auth",
            "pv_query",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_claim_correspondence",
            "pv_query",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_claim_reachability",
            "pv_query",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_claim_equivalence",
            "pv_query",
            disposition=NodeDisposition.APPROXIMATED,
            reason="observational equivalence is ProVerif-specific and loss-receipted",
        ),
        _node(
            "n_global_state",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="global mutable state is outside controlled applied-pi fragment",
        ),
        _node(
            "n_computational",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="computational soundness is never claimed",
        ),
    )


def _proverif_symbols() -> tuple[SymbolMapEntry, ...]:
    return (
        _symbol("sym_role", "pv_process_name", disposition=NodeDisposition.MAPPED),
        _symbol("sym_channel", "pv_channel_name", disposition=NodeDisposition.MAPPED),
        _symbol("sym_fun", "pv_fun", disposition=NodeDisposition.MAPPED),
        _symbol("sym_attacker", "pv_attacker", disposition=NodeDisposition.MAPPED),
        _symbol("sym_query", "pv_query_id", disposition=NodeDisposition.MAPPED),
        _symbol("sym_event", "pv_event_name", disposition=NodeDisposition.MAPPED),
    )


def _tamarin_nodes() -> tuple[NodeMapEntry, ...]:
    return (
        _node("n_role", "tm_rule", disposition=NodeDisposition.MAPPED),
        _node(
            "n_process",
            "tm_rule",
            disposition=NodeDisposition.APPROXIMATED,
            reason="process structure flattens to multiset rules",
        ),
        _node("n_equation", "tm_builtin", disposition=NodeDisposition.MAPPED),
        _node("n_channel", "tm_fact_out_in", disposition=NodeDisposition.MAPPED),
        _node("n_event", "tm_action_fact", disposition=NodeDisposition.MAPPED),
        _node("n_claim_secrecy", "tm_lemma", disposition=NodeDisposition.MAPPED),
        _node("n_claim_auth", "tm_lemma", disposition=NodeDisposition.MAPPED),
        _node(
            "n_claim_correspondence",
            "tm_lemma",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_claim_reachability",
            "tm_lemma",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_claim_equivalence",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="observational equivalence is not in controlled Tamarin fragment",
        ),
        _node(
            "n_global_state",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="global mutable state is outside controlled multiset fragment",
        ),
        _node(
            "n_computational",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="computational soundness is never claimed",
        ),
    )


def _tamarin_symbols() -> tuple[SymbolMapEntry, ...]:
    return (
        _symbol("sym_role", "tm_rule_name", disposition=NodeDisposition.MAPPED),
        _symbol("sym_channel", "tm_fact", disposition=NodeDisposition.MAPPED),
        _symbol("sym_fun", "tm_fun", disposition=NodeDisposition.MAPPED),
        _symbol("sym_attacker", "tm_adversary", disposition=NodeDisposition.MAPPED),
        _symbol("sym_query", "tm_lemma_id", disposition=NodeDisposition.MAPPED),
        _symbol("sym_event", "tm_action", disposition=NodeDisposition.MAPPED),
        _symbol("sym_fact", "tm_fact", disposition=NodeDisposition.MAPPED),
    )


def _build_proverif_edge() -> ProtocolTargetTranslationEdge:
    receipt = ProtocolDialectReceipt(
        dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
        equations=(
            "eq:pairing",
            "eq:sdec_senc",
            "eq:adec_aenc",
            "eq:checksign_sign",
            "eq:hash_free",
        ),
        equation_theory=EquationTheoryKind.SYMMETRIC_ENCRYPTION,
        role_rule_kind=RoleRuleKind.APPLIED_PI_PROCESS,
        roles_or_rules=("role:initiator", "role:responder", "role:server"),
        channel_model=ChannelModel.PUBLIC_NETWORK,
        channels=("chan:public", "chan:c"),
        attacker_semantics=AttackerSemantics.DOLEV_YAO,
        attacker_assumptions=(
            "attacker:dolev_yao",
            "attacker:perfect_cryptography",
            "attacker:public_network",
        ),
        query_identity_kind=QueryIdentityKind.PROVERIF_QUERY,
        query_identities=(
            "query:secrecy",
            "query:auth_initiator",
            "query:auth_responder",
            "query:correspondence",
        ),
        description=(
            "ProVerif applied-pi dialect: process roles, free/equational theory, "
            "public-channel Dolev-Yao attacker, query identities."
        ),
    )
    losses = (
        ProtocolTranslationLoss(
            loss_id="loss:proverif-role-to-process",
            kind=ProtocolLossKind.ROLE_TO_PROCESS,
            description=(
                "Neutral roles lower to applied-pi processes; interleaving "
                "scheduling of multi-session roles is not uniquely reconstructed."
            ),
            source_construct_ids=("n_role",),
            target_construct_ids=("pv_process",),
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:proverif-attacker-ceiling",
            kind=ProtocolLossKind.ATTACKER_CEILING,
            description=(
                "Attacker remains symbolic Dolev-Yao under perfect cryptography; "
                "no computational reduction is established."
            ),
            source_construct_ids=("sym_attacker",),
            target_construct_ids=("pv_attacker",),
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:proverif-query-renaming",
            kind=ProtocolLossKind.QUERY_RENAMING,
            description=(
                "Neutral claim identities become ProVerif query strings; lemma "
                "names are dialect-specific and must not be conflated with "
                "Tamarin lemmas."
            ),
            source_construct_ids=("sym_query", "n_claim_secrecy"),
            target_construct_ids=("pv_query", "pv_query_id"),
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:proverif-equation-fragment",
            kind=ProtocolLossKind.EQUATION_FRAGMENT,
            description=(
                "Only the controlled equational fragment lowers; custom or "
                "unsupported algebraic theories fail closed."
            ),
            source_construct_ids=("n_equation",),
            target_construct_ids=("pv_equation",),
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:proverif-channel-collapse",
            kind=ProtocolLossKind.CHANNEL_COLLAPSE,
            description=(
                "Private channels may collapse to public-network modeling under "
                "the declared channel model; residual privacy is loss-receipted."
            ),
            source_construct_ids=("n_channel",),
            target_construct_ids=("pv_channel",),
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
        ),
    )
    contract = _contract(
        "symbolic_protocol_to_proverif_applied_pi",
        source=_neutral_source(
            profile="neutral_symbolic", fragment="protocol_claims"
        ),
        target=_proverif_target(),
        preservation=PreservationRelation.TRACE_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=_proverif_nodes(),
        symbol_map=_proverif_symbols(),
        required_source_node_ids=(
            "n_role",
            "n_process",
            "n_equation",
            "n_channel",
            "n_event",
            "n_claim_secrecy",
            "n_claim_auth",
            "n_claim_correspondence",
            "n_claim_reachability",
            "n_claim_equivalence",
            "n_global_state",
            "n_computational",
        ),
        required_source_symbol_ids=(
            "sym_role",
            "sym_channel",
            "sym_fun",
            "sym_attacker",
            "sym_query",
            "sym_event",
        ),
        feature_preconditions=(
            FEAT_PROTOCOL_ROLES,
            FEAT_PROTOCOL_PROCESSES,
            FEAT_PROTOCOL_EQUATIONS,
            FEAT_PROTOCOL_CHANNELS,
            FEAT_PROTOCOL_EVENTS,
            FEAT_PROTOCOL_CLAIMS,
            FEAT_ATTACKER_DOLEV_YAO,
            FEAT_PERFECT_CRYPTO,
            FEAT_PUBLIC_CHANNEL,
            FEAT_APPLIED_PI_PROCESS,
            FEAT_QUERY_IDENTITY,
            FEAT_PROTOCOL_SECRECY,
            FEAT_PROTOCOL_AUTHENTICATION,
        ),
        unsupported_constructs=(
            FEAT_COMPUTATIONAL_SOUNDNESS,
            FEAT_GLOBAL_STATE,
            FEAT_STATEFUL_ORACLES,
            "construct:computational_soundness",
            "construct:bitstring_adversary",
            "construct:unbounded_sessions_proof",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:perfect_cryptography",
                "axiom:free_equational_fragment",
            ),
            attacker_model=(
                "attacker:dolev_yao",
                "attacker:perfect_cryptography",
                "attacker:public_network",
            ),
            domain_changes=(
                "domain:role_to_applied_pi_process",
                "domain:claim_to_proverif_query",
            ),
            other=(
                "loss:proverif-role-to-process",
                "loss:proverif-attacker-ceiling",
                "loss:proverif-query-renaming",
            ),
        ),
        checker_route="differential:protocol-proverif",
        reconstruction_route="replay:proverif-attack-trace",
        description=(
            "Neutral symbolic protocol IR lowers to ProVerif applied-pi with "
            "dialect-specific equations, roles/processes, channels, Dolev-Yao "
            "attacker, and query identities; losses are receipted."
        ),
        identities=_identities(config_identity="config:protocol-to-proverif@1"),
    )
    return ProtocolTargetTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        dialect_receipt=receipt,
        losses=losses,
        obligation_kinds=(
            ObligationKind.SECRECY.value,
            ObligationKind.AUTHENTICATION.value,
            ObligationKind.CORRESPONDENCE.value,
            ObligationKind.REACHABILITY.value,
            ObligationKind.EQUIVALENCE.value,
            ObligationKind.PROTOCOL_DOCUMENT.value,
        ),
        description=contract.description,
    )


def _build_tamarin_edge() -> ProtocolTargetTranslationEdge:
    receipt = ProtocolDialectReceipt(
        dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        equations=(
            "eq:pairing",
            "eq:sdec_senc",
            "eq:adec_aenc",
            "eq:verify_sign",
            "eq:hash_free",
        ),
        equation_theory=EquationTheoryKind.ASYMMETRIC_ENCRYPTION,
        role_rule_kind=RoleRuleKind.MULTISET_RULE,
        roles_or_rules=(
            "rule:Init",
            "rule:Recv",
            "rule:Send",
            "rule:Finish",
        ),
        channel_model=ChannelModel.PUBLIC_NETWORK,
        channels=("fact:Out", "fact:In", "fact:Fr"),
        attacker_semantics=AttackerSemantics.DOLEV_YAO,
        attacker_assumptions=(
            "attacker:dolev_yao",
            "attacker:perfect_cryptography",
            "attacker:public_network",
            "attacker:fresh_names",
        ),
        query_identity_kind=QueryIdentityKind.TAMARIN_LEMMA,
        query_identities=(
            "lemma:secrecy",
            "lemma:auth_initiator",
            "lemma:auth_responder",
            "lemma:executable",
        ),
        description=(
            "Tamarin multiset-rewriting dialect: rules/facts, builtins, "
            "public-network Dolev-Yao attacker, lemma identities."
        ),
    )
    losses = (
        ProtocolTranslationLoss(
            loss_id="loss:tamarin-role-to-rule",
            kind=ProtocolLossKind.ROLE_TO_RULE,
            description=(
                "Neutral roles flatten into multiset rewriting rules; process "
                "control-flow structure is approximated by rule sequencing."
            ),
            source_construct_ids=("n_role", "n_process"),
            target_construct_ids=("tm_rule",),
            dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:tamarin-attacker-ceiling",
            kind=ProtocolLossKind.ATTACKER_CEILING,
            description=(
                "Attacker remains symbolic Dolev-Yao under perfect cryptography; "
                "no computational reduction is established."
            ),
            source_construct_ids=("sym_attacker",),
            target_construct_ids=("tm_adversary",),
            dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:tamarin-query-renaming",
            kind=ProtocolLossKind.QUERY_RENAMING,
            description=(
                "Neutral claim identities become Tamarin lemmas; query strings "
                "are dialect-specific and must not be conflated with ProVerif "
                "queries."
            ),
            source_construct_ids=("sym_query", "n_claim_secrecy"),
            target_construct_ids=("tm_lemma", "tm_lemma_id"),
            dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:tamarin-equation-fragment",
            kind=ProtocolLossKind.EQUATION_FRAGMENT,
            description=(
                "Only controlled Tamarin builtins lower; unsupported equational "
                "theories fail closed."
            ),
            source_construct_ids=("n_equation",),
            target_construct_ids=("tm_builtin",),
            dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:tamarin-claim-subset",
            kind=ProtocolLossKind.CLAIM_SUBSET,
            description=(
                "Observational equivalence claims are unsupported on the "
                "controlled Tamarin multiset fragment and fail closed."
            ),
            source_construct_ids=("n_claim_equivalence",),
            target_construct_ids=(),
            dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        ),
        ProtocolTranslationLoss(
            loss_id="loss:tamarin-channel-to-facts",
            kind=ProtocolLossKind.CHANNEL_COLLAPSE,
            description=(
                "Channels lower to In/Out/Fr facts; private-channel privacy is "
                "not preserved beyond the public-network model."
            ),
            source_construct_ids=("n_channel",),
            target_construct_ids=("tm_fact_out_in",),
            dialect=ProtocolDialect.TAMARIN_MULTISET_REWRITING,
        ),
    )
    contract = _contract(
        "symbolic_protocol_to_tamarin_multiset_rewriting",
        source=_neutral_source(
            profile="neutral_symbolic_tamarin", fragment="protocol_rules"
        ),
        target=_tamarin_target(),
        preservation=PreservationRelation.TRACE_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=_tamarin_nodes(),
        symbol_map=_tamarin_symbols(),
        required_source_node_ids=(
            "n_role",
            "n_process",
            "n_equation",
            "n_channel",
            "n_event",
            "n_claim_secrecy",
            "n_claim_auth",
            "n_claim_correspondence",
            "n_claim_reachability",
            "n_claim_equivalence",
            "n_global_state",
            "n_computational",
        ),
        required_source_symbol_ids=(
            "sym_role",
            "sym_channel",
            "sym_fun",
            "sym_attacker",
            "sym_query",
            "sym_event",
            "sym_fact",
        ),
        feature_preconditions=(
            FEAT_PROTOCOL_ROLES,
            FEAT_PROTOCOL_EQUATIONS,
            FEAT_PROTOCOL_CHANNELS,
            FEAT_PROTOCOL_EVENTS,
            FEAT_PROTOCOL_CLAIMS,
            FEAT_ATTACKER_DOLEV_YAO,
            FEAT_PERFECT_CRYPTO,
            FEAT_PUBLIC_CHANNEL,
            FEAT_MULTISET_RULES,
            FEAT_MULTISET_FACTS,
            FEAT_LEMMA_IDENTITY,
            FEAT_PROTOCOL_SECRECY,
            FEAT_PROTOCOL_AUTHENTICATION,
            FEAT_PROTOCOL_REACHABILITY,
        ),
        unsupported_constructs=(
            FEAT_COMPUTATIONAL_SOUNDNESS,
            FEAT_GLOBAL_STATE,
            FEAT_EQUIVALENCE_CLAIM,
            FEAT_DIFF_EQUIVALENCE,
            FEAT_STATEFUL_ORACLES,
            "construct:computational_soundness",
            "construct:bitstring_adversary",
            "construct:observational_equivalence",
        ),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:perfect_cryptography",
                "axiom:multiset_rewriting_soundness",
            ),
            attacker_model=(
                "attacker:dolev_yao",
                "attacker:perfect_cryptography",
                "attacker:public_network",
                "attacker:fresh_names",
            ),
            domain_changes=(
                "domain:role_to_multiset_rule",
                "domain:claim_to_tamarin_lemma",
                "domain:channel_to_in_out_facts",
            ),
            other=(
                "loss:tamarin-role-to-rule",
                "loss:tamarin-attacker-ceiling",
                "loss:tamarin-query-renaming",
                "loss:tamarin-claim-subset",
            ),
        ),
        checker_route="differential:protocol-tamarin",
        reconstruction_route="replay:tamarin-attack-trace",
        description=(
            "Neutral symbolic protocol IR lowers to Tamarin multiset rewriting "
            "with dialect-specific equations, rules/facts, channels, Dolev-Yao "
            "attacker, and lemma identities; losses are receipted."
        ),
        identities=_identities(config_identity="config:protocol-to-tamarin@1"),
    )
    return ProtocolTargetTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        dialect_receipt=receipt,
        losses=losses,
        obligation_kinds=(
            ObligationKind.SECRECY.value,
            ObligationKind.AUTHENTICATION.value,
            ObligationKind.CORRESPONDENCE.value,
            ObligationKind.REACHABILITY.value,
            ObligationKind.PROTOCOL_DOCUMENT.value,
        ),
        description=contract.description,
    )


def build_protocol_target_translation_edges() -> tuple[
    ProtocolTargetTranslationEdge, ...
]:
    """Return the reviewed protocol-target edge set (stable order)."""

    edges = (
        _build_proverif_edge(),
        _build_tamarin_edge(),
    )
    ids = [edge.edge_id for edge in edges]
    if len(ids) != len(set(ids)):
        raise ProtocolTargetTranslationError(
            "duplicate protocol target translation edge ids"
        )
    return edges


def protocol_target_translation_contracts() -> tuple[TranslationContract, ...]:
    """Return only the ``TranslationContract@2`` edges for planner registration."""

    return tuple(edge.contract for edge in build_protocol_target_translation_edges())


# ---------------------------------------------------------------------------
# Edge registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolTargetTranslationEdges:
    """Reviewed edge registry (``ProtocolTargetTranslationEdges@1``).

    Owns neutral-protocol → ProVerif applied-pi and Tamarin multiset-rewriting
    routes.  Dialect equations, roles/rules, channels, attacker semantics, and
    query identities remain explicit per edge.
    """

    INTERFACE: ClassVar[str] = PROTOCOL_TARGET_EDGES_INTERFACE
    schema_version: ClassVar[str] = PROTOCOL_TARGET_EDGES_SCHEMA
    interface: str = PROTOCOL_TARGET_EDGES_INTERFACE

    edges: tuple[ProtocolTargetTranslationEdge, ...] = field(default_factory=tuple)
    catalog_content_id: str = ""
    description: str = (
        "Neutral symbolic protocol IR to ProVerif applied-pi and Tamarin "
        "multiset-rewriting encodings with dialect-specific receipts and losses."
    )

    def __post_init__(self) -> None:
        if self.interface != PROTOCOL_TARGET_EDGES_INTERFACE:
            raise ProtocolTargetTranslationError(
                f"unsupported protocol target edges interface {self.interface!r}"
            )
        if not self.edges:
            object.__setattr__(
                self, "edges", build_protocol_target_translation_edges()
            )
        normalized: list[ProtocolTargetTranslationEdge] = []
        seen: set[str] = set()
        for item in self.edges:
            if isinstance(item, ProtocolTargetTranslationEdge):
                edge = item
            elif isinstance(item, Mapping):
                edge = ProtocolTargetTranslationEdge.from_dict(item)
            else:
                raise ProtocolTargetTranslationError(
                    "edges items must be ProtocolTargetTranslationEdge values"
                )
            if edge.edge_id in seen:
                raise ProtocolTargetTranslationError(
                    f"duplicate edge id {edge.edge_id!r}"
                )
            seen.add(edge.edge_id)
            if not edge.is_loss_receipted:
                raise ProtocolTargetTranslationError(
                    f"edge {edge.edge_id!r} is not loss-receipted"
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
            _optional_text(self.description, "description"),
        )
        computed = self._compute_identity()
        if self.catalog_content_id and self.catalog_content_id != computed.cid:
            raise ProtocolTargetTranslationError(
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
        if isinstance(item, ProtocolTargetTranslationEdge):
            return item.edge_id in self.by_id()
        return False

    def by_id(self) -> Mapping[str, ProtocolTargetTranslationEdge]:
        return {edge.edge_id: edge for edge in self.edges}

    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    def get(self, edge_id: str) -> ProtocolTargetTranslationEdge:
        edge_id = _identifier(edge_id, "edge_id")
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return edge
        raise ProtocolTargetTranslationError(f"unknown edge_id {edge_id!r}")

    def contracts(self) -> tuple[TranslationContract, ...]:
        return tuple(edge.contract for edge in self.edges)

    def by_dialect(
        self, dialect: ProtocolDialect | str
    ) -> tuple[ProtocolTargetTranslationEdge, ...]:
        selected = _enum(dialect, ProtocolDialect, "dialect")
        return tuple(edge for edge in self.edges if edge.dialect is selected)

    def edges_for(
        self,
        *,
        source_family_id: str | None = None,
        target_family_id: str | None = None,
    ) -> tuple[ProtocolTargetTranslationEdge, ...]:
        result: list[ProtocolTargetTranslationEdge] = []
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
            result.append(edge)
        return tuple(result)

    def all_loss_receipted(self) -> bool:
        return all(edge.is_loss_receipted for edge in self.edges)

    def register_with_planner(
        self, planner: TranslationPathPlanner | None = None
    ) -> TranslationPathPlanner:
        if planner is None:
            planner = TranslationPathPlanner()
        if not isinstance(planner, TranslationPathPlanner):
            raise ProtocolTargetTranslationError(
                "planner must be a TranslationPathPlanner"
            )
        try:
            planner.register_edges(self.contracts())
        except TranslationPathPlannerError as error:
            raise ProtocolTargetTranslationError(str(error)) from error
        return planner

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "edge_content_ids": [edge.content_id for edge in self.edges],
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
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolTargetTranslationEdges":
        value = _mapping(value, "protocol target translation edges")
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
            "protocol target translation edges",
        )
        interface = value.get("interface", PROTOCOL_TARGET_EDGES_INTERFACE)
        if interface != PROTOCOL_TARGET_EDGES_INTERFACE:
            raise ProtocolTargetTranslationError(
                f"unsupported protocol target edges interface {interface!r}"
            )
        schema = value.get("schema_version", PROTOCOL_TARGET_EDGES_SCHEMA)
        if schema != PROTOCOL_TARGET_EDGES_SCHEMA:
            raise ProtocolTargetTranslationError(
                f"unsupported protocol target edges schema {schema!r}"
            )
        edges_raw = value.get("edges", ())
        if not isinstance(edges_raw, Sequence) or isinstance(
            edges_raw, (str, bytes, bytearray)
        ):
            raise ProtocolTargetTranslationError("edges must be a sequence")
        return cls(
            edges=tuple(edges_raw),  # type: ignore[arg-type]
            catalog_content_id=value.get("catalog_content_id", ""),
            description=value.get("description", ""),
        )

    @classmethod
    def reviewed(cls) -> "ProtocolTargetTranslationEdges":
        return cls(edges=build_protocol_target_translation_edges())


# ---------------------------------------------------------------------------
# Obligations and lowering
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolObligation:
    """One neutral-protocol obligation presented to a target edge."""

    obligation_id: str
    kind: ObligationKind | str
    source_family_id: str = SOURCE_SYMBOLIC_PROTOCOL
    features: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    equations: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    query_identities: tuple[str, ...] = ()
    attacker_assumptions: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
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
        for name in (
            "roles",
            "equations",
            "channels",
            "claims",
            "events",
            "query_identities",
            "attacker_assumptions",
            "symbols",
        ):
            object.__setattr__(
                self, name, _strings(getattr(self, name), name, identifiers=True)
            )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )

    def feature_set(self) -> FeatureSet:
        return FeatureSet.from_features(self.features)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker_assumptions": list(self.attacker_assumptions),
            "channels": list(self.channels),
            "claims": list(self.claims),
            "description": self.description,
            "equations": list(self.equations),
            "events": list(self.events),
            "features": list(self.features),
            "kind": self.kind.value if isinstance(self.kind, ObligationKind) else self.kind,
            "obligation_id": self.obligation_id,
            "query_identities": list(self.query_identities),
            "roles": list(self.roles),
            "source_family_id": self.source_family_id,
            "symbols": list(self.symbols),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolObligation":
        value = _mapping(value, "protocol obligation")
        return cls(
            obligation_id=value.get("obligation_id", ""),
            kind=value.get("kind", ObligationKind.PROTOCOL_DOCUMENT),
            source_family_id=value.get(
                "source_family_id", SOURCE_SYMBOLIC_PROTOCOL
            ),
            features=tuple(value.get("features", ())),
            roles=tuple(value.get("roles", ())),
            equations=tuple(value.get("equations", ())),
            channels=tuple(value.get("channels", ())),
            claims=tuple(value.get("claims", ())),
            events=tuple(value.get("events", ())),
            query_identities=tuple(value.get("query_identities", ())),
            attacker_assumptions=tuple(value.get("attacker_assumptions", ())),
            symbols=tuple(value.get("symbols", ())),
            description=value.get("description", ""),
        )


@dataclass(frozen=True, slots=True)
class ProtocolLoweringResult:
    """Result of applying a protocol-target edge to one obligation."""

    status: LoweringStatus | str
    edge_id: str
    obligation_id: str
    dialect: ProtocolDialect | str
    loss_ids: tuple[str, ...] = ()
    dialect_receipt: ProtocolDialectReceipt | None = None
    unsupported_constructs: tuple[str, ...] = ()
    reason: str = ""
    target_family_id: str = ""
    schema_version: str = PROTOCOL_LOWERING_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, LoweringStatus, "status")
        )
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "dialect", _enum(self.dialect, ProtocolDialect, "dialect")
        )
        object.__setattr__(
            self, "loss_ids", _strings(self.loss_ids, "loss_ids", identifiers=True)
        )
        if self.dialect_receipt is not None and isinstance(
            self.dialect_receipt, Mapping
        ):
            object.__setattr__(
                self,
                "dialect_receipt",
                ProtocolDialectReceipt.from_dict(self.dialect_receipt),
            )
        object.__setattr__(
            self,
            "unsupported_constructs",
            _strings(self.unsupported_constructs, "unsupported_constructs"),
        )
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))
        object.__setattr__(
            self,
            "target_family_id",
            _optional_text(self.target_family_id, "target_family_id"),
        )
        if self.schema_version != PROTOCOL_LOWERING_RESULT_SCHEMA:
            raise ProtocolTargetTranslationError(
                f"unsupported lowering result schema {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=LOWERING_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dialect": (
                self.dialect.value
                if isinstance(self.dialect, ProtocolDialect)
                else self.dialect
            ),
            "dialect_receipt": (
                self.dialect_receipt.to_dict()
                if self.dialect_receipt is not None
                else None
            ),
            "edge_id": self.edge_id,
            "loss_ids": list(self.loss_ids),
            "obligation_id": self.obligation_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, LoweringStatus)
                else self.status
            ),
            "target_family_id": self.target_family_id,
            "unsupported_constructs": list(self.unsupported_constructs),
        }


def lower_protocol_obligation(
    obligation: ProtocolObligation | Mapping[str, Any],
    edge: ProtocolTargetTranslationEdge | str | None = None,
    *,
    edges: ProtocolTargetTranslationEdges | None = None,
) -> ProtocolLoweringResult:
    """Lower a neutral-protocol obligation through a reviewed edge (fail-closed)."""

    if isinstance(obligation, Mapping):
        obligation = ProtocolObligation.from_dict(obligation)
    if not isinstance(obligation, ProtocolObligation):
        raise ProtocolTargetTranslationError(
            "obligation must be a ProtocolObligation"
        )
    catalog = edges or ProtocolTargetTranslationEdges.reviewed()
    if isinstance(edge, str):
        edge = catalog.get(edge)
    elif edge is None:
        # Select first dialect-compatible edge for the obligation features.
        candidates = [
            item
            for item in catalog.edges
            if obligation.kind.value in item.obligation_kinds
            or ObligationKind.PROTOCOL_DOCUMENT.value in item.obligation_kinds
        ]
        if not candidates:
            raise ProtocolTargetTranslationError(
                f"no protocol target edge for obligation kind {obligation.kind}"
            )
        edge = candidates[0]
    if not isinstance(edge, ProtocolTargetTranslationEdge):
        raise ProtocolTargetTranslationError(
            "edge must be a ProtocolTargetTranslationEdge"
        )

    present = obligation.feature_set()
    compatible, missing, hits = edge_feature_compatibility(edge.contract, present)
    if hits or missing:
        return ProtocolLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            obligation_id=obligation.obligation_id,
            dialect=edge.dialect,
            loss_ids=edge.loss_ids,
            dialect_receipt=edge.dialect_receipt,
            unsupported_constructs=tuple(sorted(set(hits) | set(missing))),
            reason=(
                f"feature incompatibility: missing={list(missing)} hits={list(hits)}"
            ),
            target_family_id=edge.target_family_id,
        )
    hit_unsupported = sorted(
        present.as_set() & set(edge.unsupported_constructs)
        | present.as_set() & UNSUPPORTED_CONSTRUCTS
    )
    if hit_unsupported:
        return ProtocolLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            obligation_id=obligation.obligation_id,
            dialect=edge.dialect,
            loss_ids=edge.loss_ids,
            dialect_receipt=edge.dialect_receipt,
            unsupported_constructs=tuple(hit_unsupported),
            reason="unsupported constructs present in obligation",
            target_family_id=edge.target_family_id,
        )
    if not compatible:
        return ProtocolLoweringResult(
            status=LoweringStatus.UNSUPPORTED,
            edge_id=edge.edge_id,
            obligation_id=obligation.obligation_id,
            dialect=edge.dialect,
            loss_ids=edge.loss_ids,
            dialect_receipt=edge.dialect_receipt,
            unsupported_constructs=tuple(missing),
            reason="edge feature preconditions not met",
            target_family_id=edge.target_family_id,
        )
    return ProtocolLoweringResult(
        status=LoweringStatus.SUPPORTED,
        edge_id=edge.edge_id,
        obligation_id=obligation.obligation_id,
        dialect=edge.dialect,
        loss_ids=edge.loss_ids,
        dialect_receipt=edge.dialect_receipt,
        unsupported_constructs=(),
        reason="",
        target_family_id=edge.target_family_id,
    )


def plan_protocol_path(
    *,
    target_family_id: str,
    features: Sequence[str],
    source_family_id: str = SOURCE_SYMBOLIC_PROTOCOL,
    source_profile_id: str = "",
    target_profile_id: str = "",
    edges: ProtocolTargetTranslationEdges | None = None,
) -> TranslationPathReceipt:
    """Plan a feature-total protocol path to a dialect target."""

    catalog = edges or ProtocolTargetTranslationEdges.reviewed()
    planner = catalog.register_with_planner()
    request = TranslationPathRequest(
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        source_profile_id=source_profile_id,
        target_profile_id=target_profile_id,
        features=FeatureSet.from_features(features),
    )
    try:
        return plan_translation_path(planner.registered_edges, request)
    except TranslationPathPlannerError as error:
        raise ProtocolTargetTranslationError(str(error)) from error


def require_dialect_receipt(
    *,
    dialect: object,
    equations: object,
    equation_theory: object,
    role_rule_kind: object,
    roles_or_rules: object,
    channel_model: object,
    channels: object,
    attacker_semantics: object,
    attacker_assumptions: object,
    query_identity_kind: object,
    query_identities: object,
    description: str = "",
) -> ProtocolDialectReceipt:
    """Validate and construct a mandatory dialect receipt (fail-closed)."""

    return ProtocolDialectReceipt(
        dialect=dialect,  # type: ignore[arg-type]
        equations=equations,  # type: ignore[arg-type]
        equation_theory=equation_theory,  # type: ignore[arg-type]
        role_rule_kind=role_rule_kind,  # type: ignore[arg-type]
        roles_or_rules=roles_or_rules,  # type: ignore[arg-type]
        channel_model=channel_model,  # type: ignore[arg-type]
        channels=channels,  # type: ignore[arg-type]
        attacker_semantics=attacker_semantics,  # type: ignore[arg-type]
        attacker_assumptions=attacker_assumptions,  # type: ignore[arg-type]
        query_identity_kind=query_identity_kind,  # type: ignore[arg-type]
        query_identities=query_identities,  # type: ignore[arg-type]
        description=description,
    )


__all__ = [
    "COMPILER_IDENTITY",
    "CONFIG_IDENTITY",
    "DEFAULT_PROTOCOL_TARGET_TRANSLATION_EDGES",
    "ENVIRONMENT_IDENTITY",
    "FEAT_APPLIED_PI_PROCESS",
    "FEAT_ATTACKER_DOLEV_YAO",
    "FEAT_COMPUTATIONAL_SOUNDNESS",
    "FEAT_DIFF_EQUIVALENCE",
    "FEAT_EQUIVALENCE_CLAIM",
    "FEAT_GLOBAL_STATE",
    "FEAT_LEMMA_IDENTITY",
    "FEAT_MULTISET_FACTS",
    "FEAT_MULTISET_RULES",
    "FEAT_PERFECT_CRYPTO",
    "FEAT_PRIVATE_CHANNEL",
    "FEAT_PROTOCOL_AUTHENTICATION",
    "FEAT_PROTOCOL_CHANNELS",
    "FEAT_PROTOCOL_CLAIMS",
    "FEAT_PROTOCOL_CORRESPONDENCE",
    "FEAT_PROTOCOL_EQUATIONS",
    "FEAT_PROTOCOL_EVENTS",
    "FEAT_PROTOCOL_PROCESSES",
    "FEAT_PROTOCOL_REACHABILITY",
    "FEAT_PROTOCOL_ROLES",
    "FEAT_PROTOCOL_SECRECY",
    "FEAT_PUBLIC_CHANNEL",
    "FEAT_QUERY_IDENTITY",
    "FEAT_STATEFUL_ORACLES",
    "PROFILE_IDENTITY",
    "PROTOCOL_TARGET_EDGES_INTERFACE",
    "PROTOCOL_TARGET_EDGES_SCHEMA",
    "SOURCE_SYMBOLIC_PROTOCOL",
    "TARGET_PROVERIF",
    "TARGET_TAMARIN",
    "AttackerSemantics",
    "ChannelModel",
    "EquationTheoryKind",
    "LoweringStatus",
    "ObligationKind",
    "ProtocolDialect",
    "ProtocolDialectReceipt",
    "ProtocolLossKind",
    "ProtocolLoweringResult",
    "ProtocolObligation",
    "ProtocolTargetTranslationEdge",
    "ProtocolTargetTranslationEdges",
    "ProtocolTargetTranslationError",
    "ProtocolTranslationLoss",
    "QueryIdentityKind",
    "RoleRuleKind",
    "build_protocol_target_translation_edges",
    "lower_protocol_obligation",
    "plan_protocol_path",
    "protocol_target_translation_contracts",
    "require_dialect_receipt",
]
