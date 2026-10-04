"""Direct-sanctions and bounded-flow compliance gate (CRYPTOIR-G520 / CRYPTOIR-028).

``ComplianceGate`` screens every economically relevant counterparty—not only the
displayed destination ``to`` address—against direct sanctions evidence and
configured bounded-flow exposure policy before capability issuance or
consumption.

Acceptance (fail-closed):

* Exact listed matches hard-deny.
* Party and ownership decisions require reviewed evidence.
* Indirect exposure obeys named bounds and policy.
* Stale or incomplete list/graph evidence blocks automation.
* Destination indirection, token/router/proxy changes, bridge legs, fee flows,
  multisend outputs, and UTXO change cannot bypass screening.
* License exceptions are scoped and expiry-bound.

This module issues compliance *composition results* only.  It never signs,
broadcasts, acquires live lists, mints designations, or accepts bare booleans /
caller approval as authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.compliance.models import SanctionsPolicyOutcome
from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    SanctionsMatchLevel,
    TransactionVerdictOutcome,
    transaction_blocks_automation,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest

from .errors import GuardForbiddenSurfaceError, GuardPolicyError, GuardValidationError
from .models import TransactionCandidate, TransactionIntent

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

COMPLIANCE_GATE_INTERFACE: Final = "ComplianceGate@1"
COMPLIANCE_GATE_SCHEMA_VERSION: Final = "wallet-guard.compliance-gate/v1"
COUNTERPARTY_SET_SCHEMA_VERSION: Final = "wallet-guard.counterparty-set/v1"
SANCTIONS_DECISION_SCHEMA_VERSION: Final = "wallet-guard.sanctions-decision/v1"
EXPOSURE_DECISION_SCHEMA_VERSION: Final = "wallet-guard.exposure-decision/v1"
COMPLIANCE_GATE_REQUEST_SCHEMA_VERSION: Final = (
    "wallet-guard.compliance-gate-request/v1"
)
COMPLIANCE_GATE_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.compliance-gate-decision/v1"
)

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-compliance-v1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)

_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approval",
        "allow",
        "allowed",
        "private_key",
        "private_keys",
        "secret",
        "secrets",
        "seed",
        "mnemonic",
        "signature",
        "signatures",
        "signed_tx",
        "signed_transaction",
        "broadcast",
        "broadcast_url",
        "raw_key",
        "signing_key",
        "api_key",
        "caller_approved",
        "force_allow",
        "bypass",
    }
)

# Effect kinds that imply additional counterparties beyond displayed ``to``.
_EFFECT_REQUIRED_ROLES: Final[Mapping[str, frozenset[str]]] = {
    "fee": frozenset({"fee_recipient"}),
    "bridge": frozenset({"bridge_leg"}),
    "bridge_leg": frozenset({"bridge_leg"}),
    "multisend": frozenset({"multisend_output"}),
    "multisend_output": frozenset({"multisend_output"}),
    "utxo_change": frozenset({"utxo_change"}),
    "change": frozenset({"utxo_change"}),
    "approval": frozenset({"spender"}),
    "approve": frozenset({"spender"}),
    "swap": frozenset({"router", "token"}),
    "proxy_call": frozenset({"proxy", "contract"}),
    "proxy": frozenset({"proxy"}),
    "router": frozenset({"router"}),
    "token_transfer": frozenset({"token", "token_issuer"}),
    "transfer": frozenset(),  # base transfer covered by recipient
    "destination_indirection": frozenset({"beneficiary", "derived"}),
}

# Match levels that hard-deny when exact-listed (no license override without
# reviewed scoped license).
_HARD_DENY_MATCH_LEVELS: Final[frozenset[SanctionsMatchLevel]] = frozenset(
    {
        SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
    }
)

# Levels that require reviewed evidence before non-ALLOW composition.
_REVIEWED_EVIDENCE_LEVELS: Final[frozenset[SanctionsMatchLevel]] = frozenset(
    {
        SanctionsMatchLevel.OWNED_ENTITY,
        SanctionsMatchLevel.DIRECT_ASSOCIATION,
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
    }
)

# Outcome severity for fail-closed composition (higher wins).
_OUTCOME_SEVERITY: Final[Mapping[TransactionVerdictOutcome, int]] = {
    TransactionVerdictOutcome.ALLOW: 0,
    TransactionVerdictOutcome.REVIEW: 1,
    TransactionVerdictOutcome.INCONCLUSIVE: 2,
    TransactionVerdictOutcome.STALE: 3,
    TransactionVerdictOutcome.ERROR: 4,
    TransactionVerdictOutcome.DENY: 5,
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CounterpartyRole(str, Enum):
    """Economically relevant roles that must be screened (not only ``to``)."""

    SENDER = "sender"
    RECIPIENT = "recipient"
    SPENDER = "spender"
    BENEFICIARY = "beneficiary"
    CONTRACT = "contract"
    TOKEN_ISSUER = "token_issuer"
    FEE_RECIPIENT = "fee_recipient"
    DERIVED = "derived"
    BRIDGE_LEG = "bridge_leg"
    MULTISEND_OUTPUT = "multisend_output"
    UTXO_CHANGE = "utxo_change"
    PROXY = "proxy"
    ROUTER = "router"
    TOKEN = "token"
    SIGNER = "signer"


class ExposureVerdict(str, Enum):
    """Bounded-flow exposure result for one origin under named bounds.

    Distinct from designation and from transaction authorization.
    """

    CLEAR = "clear"
    DIRECT_HIT = "direct_hit"
    INDIRECT_EXPOSURE = "indirect_exposure"
    TRUNCATED = "truncated"
    INCOMPLETE_FRONTIER = "incomplete_frontier"
    STALE = "stale"
    ERROR = "error"
    MISSING = "missing"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise GuardValidationError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise GuardValidationError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise GuardValidationError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise GuardValidationError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuardValidationError(f"{name} is not a stable identifier")
    return text


def _digest(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = _text(value, name, allow_empty=allow_empty, max_chars=96)
    if not text:
        return text
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise GuardValidationError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _timestamp(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=64)
    if not _ISO8601_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be an ISO-8601 UTC/offset timestamp"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuardValidationError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GuardValidationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _reject_forbidden(value: Mapping[str, Any], record_name: str) -> None:
    hit = sorted(set(value) & _FORBIDDEN_FIELDS)
    if hit:
        raise GuardForbiddenSurfaceError(
            f"{record_name} contains forbidden custody/approval field(s): "
            f"{', '.join(hit)}",
            details={"fields": hit},
        )


def _unique_ids(
    values: Any,
    name: str,
    *,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: tuple[str, ...] = ()
    elif isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise GuardValidationError(f"{name} must be a sequence of strings")
    else:
        if len(values) > MAX_COLLECTION_ITEMS:
            raise GuardValidationError(f"{name} exceeds maximum collection size")
        items = tuple(_identifier(item, f"{name} item") for item in values)
        if len(items) != len(set(items)):
            raise GuardValidationError(f"{name} values must be unique")
    if require_non_empty and not items:
        raise GuardValidationError(f"{name} must be non-empty")
    return items


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise GuardValidationError(f"unsupported {name}: {value!r}") from exc


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_expired(expiry: str, now: str) -> bool:
    return now > expiry


def _prefer_blocking(
    current: TransactionVerdictOutcome | None,
    proposed: TransactionVerdictOutcome,
) -> TransactionVerdictOutcome:
    if current is None:
        return proposed
    if _OUTCOME_SEVERITY[proposed] >= _OUTCOME_SEVERITY[current]:
        return proposed
    return current


def policy_outcome_to_transaction(
    outcome: SanctionsPolicyOutcome | str,
) -> TransactionVerdictOutcome:
    """Map a screening outcome onto the transaction-verdict lattice.

    Screening never elevates into authorization; only ``ALLOW`` maps to
    transaction ``ALLOW``, and every other outcome remains blocking for
    automation when composed by the gate.
    """

    value = (
        outcome
        if isinstance(outcome, SanctionsPolicyOutcome)
        else SanctionsPolicyOutcome(outcome)
    )
    mapping = {
        SanctionsPolicyOutcome.ALLOW: TransactionVerdictOutcome.ALLOW,
        SanctionsPolicyOutcome.REVIEW: TransactionVerdictOutcome.REVIEW,
        SanctionsPolicyOutcome.DENY: TransactionVerdictOutcome.DENY,
        SanctionsPolicyOutcome.INCONCLUSIVE: TransactionVerdictOutcome.INCONCLUSIVE,
        SanctionsPolicyOutcome.STALE: TransactionVerdictOutcome.STALE,
        SanctionsPolicyOutcome.ERROR: TransactionVerdictOutcome.ERROR,
    }
    return mapping[value]


# ---------------------------------------------------------------------------
# Counterparty / CounterpartySet
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Counterparty:
    """One economically relevant party subject to sanctions/exposure screening."""

    party_id: str
    role: CounterpartyRole
    address: str = ""
    network: str = ""
    effect_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "party_id", _identifier(self.party_id, "party_id"))
        object.__setattr__(self, "role", _enum(CounterpartyRole, self.role, "role"))
        object.__setattr__(
            self,
            "address",
            _text(self.address, "address", allow_empty=True, max_chars=256),
        )
        object.__setattr__(
            self,
            "network",
            _text(self.network, "network", allow_empty=True, max_chars=128),
        )
        object.__setattr__(
            self,
            "effect_id",
            _text(self.effect_id, "effect_id", allow_empty=True, max_chars=256),
        )
        if self.effect_id and not _ID_RE.fullmatch(self.effect_id):
            raise GuardValidationError("effect_id is not a stable identifier")
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "Counterparty.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))

    @property
    def screening_key(self) -> str:
        """Stable key used to join sanctions/exposure evidence."""

        return f"{self.role.value}:{self.party_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "attributes": dict(self.attributes),
            "effect_id": self.effect_id,
            "network": self.network,
            "party_id": self.party_id,
            "role": (
                self.role.value if isinstance(self.role, CounterpartyRole) else self.role
            ),
            "screening_key": self.screening_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Counterparty":
        value = _mapping(value, "Counterparty")
        _reject_forbidden(value, "Counterparty")
        _reject_unknown(
            value,
            frozenset(
                {
                    "address",
                    "attributes",
                    "effect_id",
                    "network",
                    "party_id",
                    "role",
                    "screening_key",
                }
            ),
            "Counterparty",
        )
        return cls(
            party_id=value.get("party_id", ""),
            role=value.get("role", "recipient"),
            address=value.get("address", ""),
            network=value.get("network", ""),
            effect_id=value.get("effect_id", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class CounterpartySet:
    """Complete set of counterparties that must be screened for one candidate.

    Construction from a :class:`TransactionIntent` always includes sender and
    destination (recipient/contract).  Fee payers, bridge legs, multisend
    outputs, UTXO change, spenders, token issuers, and derived parties must be
    bound explicitly so destination-only screening cannot bypass the gate.
    """

    set_id: str
    counterparties: tuple[Counterparty, ...]
    intent_id: str = ""
    candidate_id: str = ""
    network: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = COUNTERPARTY_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "set_id", _identifier(self.set_id, "set_id"))
        items = _sequence_of_counterparties(self.counterparties)
        if not items:
            raise GuardValidationError("CounterpartySet requires at least one party")
        keys = [item.screening_key for item in items]
        if len(keys) != len(set(keys)):
            raise GuardValidationError(
                "counterparties screening_key values must be unique"
            )
        object.__setattr__(self, "counterparties", items)
        object.__setattr__(
            self,
            "intent_id",
            _text(self.intent_id, "intent_id", allow_empty=True, max_chars=256),
        )
        if self.intent_id and not _ID_RE.fullmatch(self.intent_id):
            raise GuardValidationError("intent_id is not a stable identifier")
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", allow_empty=True, max_chars=256),
        )
        if self.candidate_id and not _ID_RE.fullmatch(self.candidate_id):
            raise GuardValidationError("candidate_id is not a stable identifier")
        object.__setattr__(
            self,
            "network",
            _text(self.network, "network", allow_empty=True, max_chars=128),
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "CounterpartySet.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != COUNTERPARTY_SET_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported CounterpartySet schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def party_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c.party_id for c in self.counterparties))

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(
            c.role.value if isinstance(c.role, CounterpartyRole) else str(c.role)
            for c in self.counterparties
        )

    def parties_for_role(self, role: CounterpartyRole | str) -> tuple[Counterparty, ...]:
        role_value = (
            role if isinstance(role, CounterpartyRole) else CounterpartyRole(role)
        )
        return tuple(c for c in self.counterparties if c.role is role_value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "candidate_id": self.candidate_id,
            "counterparties": [c.to_dict() for c in self.counterparties],
            "intent_id": self.intent_id,
            "network": self.network,
            "party_ids": list(self.party_ids),
            "roles": sorted(self.roles),
            "schema_version": self.schema_version,
            "set_id": self.set_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterpartySet":
        value = _mapping(value, "CounterpartySet")
        _reject_forbidden(value, "CounterpartySet")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "candidate_id",
                    "counterparties",
                    "intent_id",
                    "network",
                    "party_ids",
                    "roles",
                    "schema_version",
                    "set_id",
                }
            ),
            "CounterpartySet",
        )
        return cls(
            set_id=value.get("set_id", ""),
            counterparties=tuple(value.get("counterparties", ())),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            network=value.get("network", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", COUNTERPARTY_SET_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_intent(
        cls,
        intent: TransactionIntent,
        *,
        set_id: str,
        candidate: TransactionCandidate | None = None,
        extra: Sequence[Counterparty | Mapping[str, Any]] = (),
    ) -> "CounterpartySet":
        """Build a counterparty set from intent base fields plus *extra* parties.

        Always screens sender and destination (as recipient and contract).
        Fee payers from :attr:`TransactionIntent.fees` are included when set.
        Additional economically relevant parties (bridge legs, multisend,
        UTXO change, spenders, token issuers, proxies, routers) must be
        supplied via *extra* so they cannot be omitted silently.
        """

        if not isinstance(intent, TransactionIntent):
            raise GuardValidationError("intent must be a TransactionIntent")

        parties: list[Counterparty] = [
            Counterparty(
                party_id=f"party:sender:{intent.sender}",
                role=CounterpartyRole.SENDER,
                address=intent.sender,
                network=intent.network,
            ),
            Counterparty(
                party_id=f"party:recipient:{intent.destination}",
                role=CounterpartyRole.RECIPIENT,
                address=intent.destination,
                network=intent.network,
            ),
            Counterparty(
                party_id=f"party:contract:{intent.destination}",
                role=CounterpartyRole.CONTRACT,
                address=intent.destination,
                network=intent.network,
            ),
        ]
        for index, fee in enumerate(intent.fees):
            if fee.payer:
                parties.append(
                    Counterparty(
                        party_id=f"party:fee-payer:{fee.payer}",
                        role=CounterpartyRole.FEE_RECIPIENT,
                        address=fee.payer,
                        network=intent.network,
                        effect_id=f"effect:fee-{index}",
                    )
                )
        for signer in intent.signers:
            parties.append(
                Counterparty(
                    party_id=f"party:signer:{signer}",
                    role=CounterpartyRole.SIGNER,
                    address=signer,
                    network=intent.network,
                )
            )
        for item in extra:
            if isinstance(item, Counterparty):
                parties.append(item)
            elif isinstance(item, Mapping):
                parties.append(Counterparty.from_dict(item))
            else:
                raise GuardValidationError(
                    "extra counterparties must be Counterparty or mappings"
                )

        # De-duplicate by screening_key while preserving first occurrence.
        seen: set[str] = set()
        unique: list[Counterparty] = []
        for party in parties:
            if party.screening_key in seen:
                continue
            seen.add(party.screening_key)
            unique.append(party)

        return cls(
            set_id=set_id,
            counterparties=tuple(unique),
            intent_id=intent.intent_id,
            candidate_id=candidate.candidate_id if candidate is not None else "",
            network=intent.network,
        )


def _sequence_of_counterparties(values: Any) -> tuple[Counterparty, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise GuardValidationError("counterparties must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise GuardValidationError("counterparties exceeds maximum collection size")
    out: list[Counterparty] = []
    for item in values:
        if isinstance(item, Counterparty):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(Counterparty.from_dict(item))
        else:
            raise GuardValidationError(
                "counterparties items must be Counterparty or mappings"
            )
    return tuple(out)


# ---------------------------------------------------------------------------
# SanctionsDecision (gate-bound screening result per party)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SanctionsDecision:
    """Direct-list / party / ownership screening result for one counterparty.

    Bound to exact policy and snapshot revisions.  Exact listed matches are
    hard-deny unless a scoped, unexpired, reviewed license applies.
    Party/ownership positive outcomes require ``reviewed_evidence=True``.
    """

    decision_id: str
    party_id: str
    outcome: SanctionsPolicyOutcome
    match_level: SanctionsMatchLevel
    policy_id: str
    policy_revision: str
    snapshot_id: str
    snapshot_revision: str
    reason_codes: tuple[str, ...] = ()
    reviewed_evidence: bool = False
    list_complete: bool = True
    freshness_expires_at: str = ""
    license_ids: tuple[str, ...] = ()
    license_expires_at: str = ""
    license_scoped_activity: str = ""
    screening_key: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SANCTIONS_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(self, "party_id", _identifier(self.party_id, "party_id"))
        object.__setattr__(
            self,
            "outcome",
            _enum(SanctionsPolicyOutcome, self.outcome, "outcome"),  # type: ignore[arg-type]
        )
        object.__setattr__(
            self,
            "match_level",
            _enum(SanctionsMatchLevel, self.match_level, "match_level"),  # type: ignore[arg-type]
        )
        for name in (
            "policy_id",
            "policy_revision",
            "snapshot_id",
            "snapshot_revision",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "reason_codes", _unique_ids(self.reason_codes, "reason_codes")
        )
        for name in ("reviewed_evidence", "list_complete"):
            if not isinstance(getattr(self, name), bool):
                raise GuardValidationError(f"{name} must be a bool")
        if self.freshness_expires_at:
            object.__setattr__(
                self,
                "freshness_expires_at",
                _timestamp(self.freshness_expires_at, "freshness_expires_at"),
            )
        else:
            object.__setattr__(self, "freshness_expires_at", "")
        object.__setattr__(
            self, "license_ids", _unique_ids(self.license_ids, "license_ids")
        )
        if self.license_expires_at:
            object.__setattr__(
                self,
                "license_expires_at",
                _timestamp(self.license_expires_at, "license_expires_at"),
            )
        else:
            object.__setattr__(self, "license_expires_at", "")
        object.__setattr__(
            self,
            "license_scoped_activity",
            _text(
                self.license_scoped_activity,
                "license_scoped_activity",
                allow_empty=True,
                max_chars=256,
            ),
        )
        object.__setattr__(
            self,
            "screening_key",
            _text(self.screening_key, "screening_key", allow_empty=True, max_chars=512),
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "SanctionsDecision.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def is_stale(self, now: str) -> bool:
        if not self.freshness_expires_at:
            return False
        return _is_expired(self.freshness_expires_at, now)

    def license_active(self, now: str, *, activity_id: str = "") -> bool:
        """True only for scoped, unexpired licenses bound on this decision."""

        if not self.license_ids:
            return False
        if self.license_expires_at and _is_expired(self.license_expires_at, now):
            return False
        if self.license_scoped_activity and activity_id:
            return self.license_scoped_activity == activity_id
        # License present without activity scope is still scoped to the
        # decision's party; empty activity means scope was not asserted.
        return bool(self.license_ids) and bool(self.license_expires_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "decision_id": self.decision_id,
            "freshness_expires_at": self.freshness_expires_at,
            "license_expires_at": self.license_expires_at,
            "license_ids": list(self.license_ids),
            "license_scoped_activity": self.license_scoped_activity,
            "list_complete": self.list_complete,
            "match_level": (
                self.match_level.value
                if isinstance(self.match_level, SanctionsMatchLevel)
                else self.match_level
            ),
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, SanctionsPolicyOutcome)
                else self.outcome
            ),
            "party_id": self.party_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "reason_codes": list(self.reason_codes),
            "reviewed_evidence": self.reviewed_evidence,
            "schema_version": self.schema_version,
            "screening_key": self.screening_key,
            "snapshot_id": self.snapshot_id,
            "snapshot_revision": self.snapshot_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsDecision":
        value = _mapping(value, "SanctionsDecision")
        _reject_forbidden(value, "SanctionsDecision")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "decision_id",
                    "freshness_expires_at",
                    "license_expires_at",
                    "license_ids",
                    "license_scoped_activity",
                    "list_complete",
                    "match_level",
                    "outcome",
                    "party_id",
                    "policy_id",
                    "policy_revision",
                    "reason_codes",
                    "reviewed_evidence",
                    "schema_version",
                    "screening_key",
                    "snapshot_id",
                    "snapshot_revision",
                }
            ),
            "SanctionsDecision",
        )
        return cls(
            decision_id=value.get("decision_id", ""),
            party_id=value.get("party_id", ""),
            outcome=value.get("outcome", "error"),
            match_level=value.get("match_level", "unknown"),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            snapshot_id=value.get("snapshot_id", ""),
            snapshot_revision=value.get("snapshot_revision", ""),
            reason_codes=tuple(value.get("reason_codes", ())),
            reviewed_evidence=value.get("reviewed_evidence", False),
            list_complete=value.get("list_complete", True),
            freshness_expires_at=value.get("freshness_expires_at", ""),
            license_ids=tuple(value.get("license_ids", ())),
            license_expires_at=value.get("license_expires_at", ""),
            license_scoped_activity=value.get("license_scoped_activity", ""),
            screening_key=value.get("screening_key", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", SANCTIONS_DECISION_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# ExposureDecision (bounded-flow result per origin)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExposureDecision:
    """Bounded-flow exposure decision for one origin under named policy bounds.

    Indirect exposure never manufactures a designation.  Truncation or an
    incomplete completeness frontier blocks automation for absence claims.
    """

    decision_id: str
    origin_party_id: str
    verdict: ExposureVerdict
    policy_id: str
    policy_revision: str
    bounds_digest: str
    max_depth: int
    graph_snapshot_id: str
    list_revision: str
    outcome: SanctionsPolicyOutcome = SanctionsPolicyOutcome.ALLOW
    path_ids: tuple[str, ...] = ()
    truncated: bool = False
    incomplete_frontier: bool = False
    freshness_expires_at: str = ""
    screening_key: str = ""
    reason_codes: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EXPOSURE_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self,
            "origin_party_id",
            _identifier(self.origin_party_id, "origin_party_id"),
        )
        object.__setattr__(
            self, "verdict", _enum(ExposureVerdict, self.verdict, "verdict")
        )
        for name in ("policy_id", "policy_revision", "graph_snapshot_id", "list_revision"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "bounds_digest", _digest(self.bounds_digest, "bounds_digest")
        )
        if not isinstance(self.max_depth, int) or isinstance(self.max_depth, bool):
            raise GuardValidationError("max_depth must be an integer")
        if self.max_depth < 0:
            raise GuardValidationError("max_depth must be non-negative")
        object.__setattr__(
            self,
            "outcome",
            _enum(SanctionsPolicyOutcome, self.outcome, "outcome"),  # type: ignore[arg-type]
        )
        object.__setattr__(self, "path_ids", _unique_ids(self.path_ids, "path_ids"))
        for name in ("truncated", "incomplete_frontier"):
            if not isinstance(getattr(self, name), bool):
                raise GuardValidationError(f"{name} must be a bool")
        if self.freshness_expires_at:
            object.__setattr__(
                self,
                "freshness_expires_at",
                _timestamp(self.freshness_expires_at, "freshness_expires_at"),
            )
        else:
            object.__setattr__(self, "freshness_expires_at", "")
        object.__setattr__(
            self,
            "screening_key",
            _text(self.screening_key, "screening_key", allow_empty=True, max_chars=512),
        )
        object.__setattr__(
            self, "reason_codes", _unique_ids(self.reason_codes, "reason_codes")
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "ExposureDecision.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # Indirect exposure never elevates to designation hard-deny by default;
        # policy outcome must be REVIEW or DENY when a path exists.
        if self.verdict is ExposureVerdict.INDIRECT_EXPOSURE:
            if self.outcome is SanctionsPolicyOutcome.ALLOW:
                raise GuardPolicyError(
                    "indirect exposure cannot map to ALLOW; use REVIEW or DENY"
                )
        if self.verdict is ExposureVerdict.DIRECT_HIT:
            if self.outcome is SanctionsPolicyOutcome.ALLOW:
                raise GuardPolicyError(
                    "direct exposure hit cannot map to ALLOW"
                )

    def is_stale(self, now: str) -> bool:
        if self.verdict is ExposureVerdict.STALE:
            return True
        if not self.freshness_expires_at:
            return False
        return _is_expired(self.freshness_expires_at, now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "bounds_digest": self.bounds_digest,
            "decision_id": self.decision_id,
            "freshness_expires_at": self.freshness_expires_at,
            "graph_snapshot_id": self.graph_snapshot_id,
            "incomplete_frontier": self.incomplete_frontier,
            "list_revision": self.list_revision,
            "max_depth": self.max_depth,
            "origin_party_id": self.origin_party_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, SanctionsPolicyOutcome)
                else self.outcome
            ),
            "path_ids": list(self.path_ids),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "screening_key": self.screening_key,
            "truncated": self.truncated,
            "verdict": (
                self.verdict.value
                if isinstance(self.verdict, ExposureVerdict)
                else self.verdict
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExposureDecision":
        value = _mapping(value, "ExposureDecision")
        _reject_forbidden(value, "ExposureDecision")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "bounds_digest",
                    "decision_id",
                    "freshness_expires_at",
                    "graph_snapshot_id",
                    "incomplete_frontier",
                    "list_revision",
                    "max_depth",
                    "origin_party_id",
                    "outcome",
                    "path_ids",
                    "policy_id",
                    "policy_revision",
                    "reason_codes",
                    "schema_version",
                    "screening_key",
                    "truncated",
                    "verdict",
                }
            ),
            "ExposureDecision",
        )
        return cls(
            decision_id=value.get("decision_id", ""),
            origin_party_id=value.get("origin_party_id", ""),
            verdict=value.get("verdict", "error"),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            bounds_digest=value.get("bounds_digest", ""),
            max_depth=value.get("max_depth", 0),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            outcome=value.get("outcome", "allow"),
            path_ids=tuple(value.get("path_ids", ())),
            truncated=value.get("truncated", False),
            incomplete_frontier=value.get("incomplete_frontier", False),
            freshness_expires_at=value.get("freshness_expires_at", ""),
            screening_key=value.get("screening_key", ""),
            reason_codes=tuple(value.get("reason_codes", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", EXPOSURE_DECISION_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Request + gate decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComplianceGateRequest:
    """Request binding candidate, counterparty set, and screening evidence.

    Every party in :attr:`counterparties` must have a corresponding
    :class:`SanctionsDecision`.  Bounded-flow :class:`ExposureDecision`
    evidence is required when ``require_exposure`` is True (default).
    """

    request_id: str
    intent: TransactionIntent
    candidate: TransactionCandidate
    counterparties: CounterpartySet
    sanctions_decisions: tuple[SanctionsDecision, ...]
    exposure_decisions: tuple[ExposureDecision, ...]
    tenant_id: str
    actor_id: str
    policy_id: str
    issued_at: str
    expiry: str
    activity_id: str = "activity:transfer"
    require_exposure: bool = True
    expected_bounds_digest: str = ""
    list_snapshot_id: str = ""
    list_revision: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = COMPLIANCE_GATE_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        if not isinstance(self.intent, TransactionIntent):
            if isinstance(self.intent, Mapping):
                object.__setattr__(
                    self, "intent", TransactionIntent.from_dict(self.intent)
                )
            else:
                raise GuardValidationError("intent must be a TransactionIntent")
        if not isinstance(self.candidate, TransactionCandidate):
            if isinstance(self.candidate, Mapping):
                object.__setattr__(
                    self,
                    "candidate",
                    TransactionCandidate.from_dict(self.candidate),
                )
            else:
                raise GuardValidationError(
                    "candidate must be a TransactionCandidate"
                )
        if self.candidate.intent_id != self.intent.intent_id:
            raise GuardValidationError(
                "candidate.intent_id must match intent.intent_id"
            )
        if self.candidate.network and self.candidate.network != self.intent.network:
            raise GuardValidationError(
                "candidate.network must match intent.network when provided"
            )
        if not isinstance(self.counterparties, CounterpartySet):
            if isinstance(self.counterparties, Mapping):
                object.__setattr__(
                    self,
                    "counterparties",
                    CounterpartySet.from_dict(self.counterparties),
                )
            else:
                raise GuardValidationError(
                    "counterparties must be a CounterpartySet"
                )
        object.__setattr__(
            self,
            "sanctions_decisions",
            _sequence_of_sanctions(self.sanctions_decisions),
        )
        object.__setattr__(
            self,
            "exposure_decisions",
            _sequence_of_exposure(self.exposure_decisions),
        )
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        object.__setattr__(
            self, "policy_id", _identifier(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        if self.expiry < self.issued_at:
            raise GuardValidationError("expiry must not precede issued_at")
        object.__setattr__(
            self, "activity_id", _identifier(self.activity_id, "activity_id")
        )
        if not isinstance(self.require_exposure, bool):
            raise GuardValidationError("require_exposure must be a bool")
        object.__setattr__(
            self,
            "expected_bounds_digest",
            _digest(
                self.expected_bounds_digest,
                "expected_bounds_digest",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "list_snapshot_id",
            _text(
                self.list_snapshot_id,
                "list_snapshot_id",
                allow_empty=True,
                max_chars=256,
            ),
        )
        if self.list_snapshot_id and not _ID_RE.fullmatch(self.list_snapshot_id):
            raise GuardValidationError("list_snapshot_id is not a stable identifier")
        object.__setattr__(
            self,
            "list_revision",
            _text(
                self.list_revision, "list_revision", allow_empty=True, max_chars=128
            ),
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "ComplianceGateRequest.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def intent_digest(self) -> str:
        return self.intent.digest

    @property
    def candidate_digest(self) -> str:
        return self.candidate.digest

    @property
    def request_digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "actor_id": self.actor_id,
            "attributes": dict(self.attributes),
            "candidate": self.candidate.to_dict(),
            "counterparties": self.counterparties.to_dict(),
            "expected_bounds_digest": self.expected_bounds_digest,
            "expiry": self.expiry,
            "exposure_decisions": [e.to_dict() for e in self.exposure_decisions],
            "intent": self.intent.to_dict(),
            "issued_at": self.issued_at,
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "policy_id": self.policy_id,
            "request_id": self.request_id,
            "require_exposure": self.require_exposure,
            "sanctions_decisions": [s.to_dict() for s in self.sanctions_decisions],
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceGateRequest":
        value = _mapping(value, "ComplianceGateRequest")
        _reject_forbidden(value, "ComplianceGateRequest")
        _reject_unknown(
            value,
            frozenset(
                {
                    "activity_id",
                    "actor_id",
                    "attributes",
                    "candidate",
                    "counterparties",
                    "expected_bounds_digest",
                    "expiry",
                    "exposure_decisions",
                    "intent",
                    "issued_at",
                    "list_revision",
                    "list_snapshot_id",
                    "policy_id",
                    "request_id",
                    "require_exposure",
                    "sanctions_decisions",
                    "schema_version",
                    "tenant_id",
                }
            ),
            "ComplianceGateRequest",
        )
        return cls(
            request_id=value.get("request_id", ""),
            intent=value.get("intent", {}),
            candidate=value.get("candidate", {}),
            counterparties=value.get("counterparties", {}),
            sanctions_decisions=tuple(value.get("sanctions_decisions", ())),
            exposure_decisions=tuple(value.get("exposure_decisions", ())),
            tenant_id=value.get("tenant_id", ""),
            actor_id=value.get("actor_id", ""),
            policy_id=value.get("policy_id", ""),
            issued_at=value.get("issued_at", ""),
            expiry=value.get("expiry", ""),
            activity_id=value.get("activity_id", "activity:transfer"),
            require_exposure=value.get("require_exposure", True),
            expected_bounds_digest=value.get("expected_bounds_digest", ""),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", COMPLIANCE_GATE_REQUEST_SCHEMA_VERSION
            ),
        )


def _sequence_of_sanctions(values: Any) -> tuple[SanctionsDecision, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise GuardValidationError("sanctions_decisions must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise GuardValidationError(
            "sanctions_decisions exceeds maximum collection size"
        )
    out: list[SanctionsDecision] = []
    for item in values:
        if isinstance(item, SanctionsDecision):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(SanctionsDecision.from_dict(item))
        else:
            raise GuardValidationError(
                "sanctions_decisions items must be SanctionsDecision or mappings"
            )
    return tuple(out)


def _sequence_of_exposure(values: Any) -> tuple[ExposureDecision, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise GuardValidationError("exposure_decisions must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise GuardValidationError(
            "exposure_decisions exceeds maximum collection size"
        )
    out: list[ExposureDecision] = []
    for item in values:
        if isinstance(item, ExposureDecision):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ExposureDecision.from_dict(item))
        else:
            raise GuardValidationError(
                "exposure_decisions items must be ExposureDecision or mappings"
            )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class ComplianceGateDecision:
    """Deterministic compliance composition for one exact transaction candidate.

    Only :attr:`TransactionVerdictOutcome.ALLOW` with ``blocks_automation=False``
    permits automated use, and only for the exact counterparty set and evidence
    digests bound into this decision.
    """

    decision_id: str
    request_digest: str
    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    intent_digest: str
    candidate_digest: str
    network: str
    counterparty_set_digest: str
    screened_party_ids: tuple[str, ...]
    screened_roles: tuple[str, ...]
    sanctions_results: Mapping[str, str]
    exposure_results: Mapping[str, str]
    sanctions_decision_ids: tuple[str, ...]
    exposure_decision_ids: tuple[str, ...]
    list_snapshot_id: str
    list_revision: str
    issued_at: str
    expiry: str
    producer_id: str = DEFAULT_PRODUCER_ID
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = COMPLIANCE_GATE_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "outcome",
            _enum(TransactionVerdictOutcome, self.outcome, "outcome"),
        )
        if not isinstance(self.blocks_automation, bool):
            raise GuardValidationError("blocks_automation must be a bool")
        expected_block = transaction_blocks_automation(self.outcome)  # type: ignore[arg-type]
        if self.outcome is TransactionVerdictOutcome.ALLOW:
            if self.blocks_automation:
                raise GuardValidationError(
                    "ALLOW decisions must set blocks_automation=False"
                )
        elif not self.blocks_automation:
            raise GuardValidationError(
                f"non-ALLOW outcome {self.outcome} must block automation"
            )
        if expected_block and not self.blocks_automation:
            raise GuardValidationError(
                "blocks_automation inconsistent with outcome"
            )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_ids(self.reason_codes, "reason_codes", require_non_empty=True)
            if self.reason_codes
            else ("compliance.decision",),
        )
        if isinstance(self.reasons, (str, bytes, bytearray)) or not isinstance(
            self.reasons, Sequence
        ):
            raise GuardValidationError("reasons must be a sequence of strings")
        object.__setattr__(
            self,
            "reasons",
            tuple(_text(r, "reasons item") for r in self.reasons)
            if self.reasons
            else ("compliance gate decision",),
        )
        object.__setattr__(
            self, "intent_digest", _digest(self.intent_digest, "intent_digest")
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _digest(self.candidate_digest, "candidate_digest"),
        )
        object.__setattr__(self, "network", _identifier(self.network, "network"))
        object.__setattr__(
            self,
            "counterparty_set_digest",
            _digest(self.counterparty_set_digest, "counterparty_set_digest"),
        )
        object.__setattr__(
            self,
            "screened_party_ids",
            _unique_ids(self.screened_party_ids, "screened_party_ids"),
        )
        object.__setattr__(
            self,
            "screened_roles",
            _unique_ids(self.screened_roles, "screened_roles"),
        )
        if not isinstance(self.sanctions_results, Mapping):
            raise GuardValidationError("sanctions_results must be a mapping")
        object.__setattr__(
            self,
            "sanctions_results",
            {
                _identifier(k, "sanctions_results key"): _text(
                    v, f"sanctions_results[{k}]"
                )
                for k, v in self.sanctions_results.items()
            },
        )
        if not isinstance(self.exposure_results, Mapping):
            raise GuardValidationError("exposure_results must be a mapping")
        object.__setattr__(
            self,
            "exposure_results",
            {
                _identifier(k, "exposure_results key"): _text(
                    v, f"exposure_results[{k}]"
                )
                for k, v in self.exposure_results.items()
            },
        )
        object.__setattr__(
            self,
            "sanctions_decision_ids",
            _unique_ids(self.sanctions_decision_ids, "sanctions_decision_ids"),
        )
        object.__setattr__(
            self,
            "exposure_decision_ids",
            _unique_ids(self.exposure_decision_ids, "exposure_decision_ids"),
        )
        object.__setattr__(
            self,
            "list_snapshot_id",
            _text(
                self.list_snapshot_id,
                "list_snapshot_id",
                allow_empty=True,
                max_chars=256,
            ),
        )
        object.__setattr__(
            self,
            "list_revision",
            _text(
                self.list_revision, "list_revision", allow_empty=True, max_chars=128
            ),
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "ComplianceGateDecision.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def permits_automation(self) -> bool:
        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "blocks_automation": self.blocks_automation,
            "candidate_digest": self.candidate_digest,
            "counterparty_set_digest": self.counterparty_set_digest,
            "decision_id": self.decision_id,
            "expiry": self.expiry,
            "exposure_decision_ids": list(self.exposure_decision_ids),
            "exposure_results": dict(self.exposure_results),
            "intent_digest": self.intent_digest,
            "issued_at": self.issued_at,
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "network": self.network,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, TransactionVerdictOutcome)
                else self.outcome
            ),
            "producer_id": self.producer_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "request_digest": self.request_digest,
            "sanctions_decision_ids": list(self.sanctions_decision_ids),
            "sanctions_results": dict(self.sanctions_results),
            "schema_version": self.schema_version,
            "screened_party_ids": list(self.screened_party_ids),
            "screened_roles": list(self.screened_roles),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceGateDecision":
        value = _mapping(value, "ComplianceGateDecision")
        _reject_forbidden(value, "ComplianceGateDecision")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "blocks_automation",
                    "candidate_digest",
                    "counterparty_set_digest",
                    "decision_id",
                    "expiry",
                    "exposure_decision_ids",
                    "exposure_results",
                    "intent_digest",
                    "issued_at",
                    "list_revision",
                    "list_snapshot_id",
                    "network",
                    "outcome",
                    "producer_id",
                    "reason_codes",
                    "reasons",
                    "request_digest",
                    "sanctions_decision_ids",
                    "sanctions_results",
                    "schema_version",
                    "screened_party_ids",
                    "screened_roles",
                }
            ),
            "ComplianceGateDecision",
        )
        return cls(
            decision_id=value.get("decision_id", ""),
            request_digest=value.get("request_digest", ""),
            outcome=value.get("outcome", "error"),
            blocks_automation=value.get("blocks_automation", True),
            reason_codes=tuple(value.get("reason_codes", ())),
            reasons=tuple(value.get("reasons", ())),
            intent_digest=value.get("intent_digest", ""),
            candidate_digest=value.get("candidate_digest", ""),
            network=value.get("network", ""),
            counterparty_set_digest=value.get("counterparty_set_digest", ""),
            screened_party_ids=tuple(value.get("screened_party_ids", ())),
            screened_roles=tuple(value.get("screened_roles", ())),
            sanctions_results=value.get("sanctions_results", {}),
            exposure_results=value.get("exposure_results", {}),
            sanctions_decision_ids=tuple(value.get("sanctions_decision_ids", ())),
            exposure_decision_ids=tuple(value.get("exposure_decision_ids", ())),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            issued_at=value.get("issued_at", ""),
            expiry=value.get("expiry", ""),
            producer_id=value.get("producer_id", DEFAULT_PRODUCER_ID),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", COMPLIANCE_GATE_DECISION_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def _required_roles_for_intent(intent: TransactionIntent) -> frozenset[str]:
    """Roles implied by expected effect kinds that must be present on the set."""

    required: set[str] = {
        CounterpartyRole.SENDER.value,
        CounterpartyRole.RECIPIENT.value,
    }
    for effect in intent.expected_effects:
        kind = effect.kind.lower()
        for role in _EFFECT_REQUIRED_ROLES.get(kind, frozenset()):
            required.add(role)
    # Fee bindings without payer still require fee_recipient when fee effects
    # are declared; fee payers on FeeSpec are auto-collected by from_intent.
    if any(effect.kind.lower() == "fee" for effect in intent.expected_effects):
        required.add(CounterpartyRole.FEE_RECIPIENT.value)
    return frozenset(required)


def _index_sanctions(
    decisions: Sequence[SanctionsDecision],
) -> dict[str, SanctionsDecision]:
    by_party: dict[str, SanctionsDecision] = {}
    by_key: dict[str, SanctionsDecision] = {}
    for decision in decisions:
        if decision.party_id not in by_party:
            by_party[decision.party_id] = decision
        if decision.screening_key:
            by_key[decision.screening_key] = decision
    return {**by_party, **{f"key:{k}": v for k, v in by_key.items()}}


def _lookup_sanctions(
    index: Mapping[str, SanctionsDecision],
    party: Counterparty,
) -> SanctionsDecision | None:
    if party.screening_key and f"key:{party.screening_key}" in index:
        return index[f"key:{party.screening_key}"]
    return index.get(party.party_id)


def _index_exposure(
    decisions: Sequence[ExposureDecision],
) -> dict[str, ExposureDecision]:
    by_origin: dict[str, ExposureDecision] = {}
    by_key: dict[str, ExposureDecision] = {}
    for decision in decisions:
        if decision.origin_party_id not in by_origin:
            by_origin[decision.origin_party_id] = decision
        if decision.screening_key:
            by_key[decision.screening_key] = decision
    return {**by_origin, **{f"key:{k}": v for k, v in by_key.items()}}


def _lookup_exposure(
    index: Mapping[str, ExposureDecision],
    party: Counterparty,
) -> ExposureDecision | None:
    if party.screening_key and f"key:{party.screening_key}" in index:
        return index[f"key:{party.screening_key}"]
    return index.get(party.party_id)


def _evaluate_sanctions_decision(
    decision: SanctionsDecision,
    *,
    party: Counterparty,
    clock: str,
    activity_id: str,
    list_snapshot_id: str,
    list_revision: str,
) -> tuple[TransactionVerdictOutcome | None, str, str]:
    """Return ``(blocking_or_None, result_key, reason)`` for one sanctions row."""

    if not decision.list_complete:
        return (
            TransactionVerdictOutcome.INCONCLUSIVE,
            "incomplete_list",
            f"sanctions list incomplete for {party.party_id}",
        )
    if decision.is_stale(clock) or decision.outcome is SanctionsPolicyOutcome.STALE:
        return (
            TransactionVerdictOutcome.STALE,
            "stale",
            f"sanctions evidence stale for {party.party_id}",
        )
    if list_snapshot_id and decision.snapshot_id != list_snapshot_id:
        return (
            TransactionVerdictOutcome.DENY,
            "snapshot_mismatch",
            (
                f"sanctions snapshot for {party.party_id} does not match "
                "request-bound list revision"
            ),
        )
    if list_revision and decision.snapshot_revision != list_revision:
        return (
            TransactionVerdictOutcome.DENY,
            "revision_mismatch",
            (
                f"sanctions revision for {party.party_id} does not match "
                "request-bound list revision"
            ),
        )

    level = decision.match_level
    assert isinstance(level, SanctionsMatchLevel)
    outcome = decision.outcome
    assert isinstance(outcome, SanctionsPolicyOutcome)

    # Party/ownership positive hits require reviewed evidence.
    if (
        level in _REVIEWED_EVIDENCE_LEVELS
        and outcome
        in {
            SanctionsPolicyOutcome.DENY,
            SanctionsPolicyOutcome.REVIEW,
        }
        and not decision.reviewed_evidence
    ):
        return (
            TransactionVerdictOutcome.INCONCLUSIVE,
            "unreviewed_party_ownership",
            (
                f"party/ownership decision for {party.party_id} lacks "
                "reviewed evidence"
            ),
        )

    # Exact listed / named designated: hard-deny unless scoped active license.
    if level in _HARD_DENY_MATCH_LEVELS and outcome is SanctionsPolicyOutcome.DENY:
        if decision.license_active(clock, activity_id=activity_id):
            return (
                TransactionVerdictOutcome.REVIEW,
                "licensed_exception",
                (
                    f"exact listed match for {party.party_id} covered by "
                    "scoped unexpired license; requires review"
                ),
            )
        if decision.license_ids and not decision.license_active(
            clock, activity_id=activity_id
        ):
            return (
                TransactionVerdictOutcome.DENY,
                "expired_or_unscoped_license",
                (
                    f"license for {party.party_id} is expired or not scoped "
                    "to this activity"
                ),
            )
        return (
            TransactionVerdictOutcome.DENY,
            "exact_listed_deny",
            f"exact listed/designated match hard-denies {party.party_id}",
        )

    # Owned entity / association under DENY without license still denies when
    # reviewed.
    if outcome is SanctionsPolicyOutcome.DENY:
        return (
            TransactionVerdictOutcome.DENY,
            "sanctions_deny",
            f"sanctions policy denies {party.party_id}",
        )
    if outcome is SanctionsPolicyOutcome.ERROR:
        return (
            TransactionVerdictOutcome.ERROR,
            "sanctions_error",
            f"sanctions screening error for {party.party_id}",
        )
    if outcome is SanctionsPolicyOutcome.INCONCLUSIVE:
        return (
            TransactionVerdictOutcome.INCONCLUSIVE,
            "sanctions_inconclusive",
            f"sanctions screening inconclusive for {party.party_id}",
        )
    if outcome is SanctionsPolicyOutcome.REVIEW:
        return (
            TransactionVerdictOutcome.REVIEW,
            "sanctions_review",
            f"sanctions screening requires review for {party.party_id}",
        )
    if outcome is SanctionsPolicyOutcome.ALLOW:
        return (None, "clear", f"sanctions clear for {party.party_id}")
    return (
        TransactionVerdictOutcome.INCONCLUSIVE,
        "sanctions_unknown",
        f"unrecognized sanctions outcome for {party.party_id}",
    )


def _evaluate_exposure_decision(
    decision: ExposureDecision,
    *,
    party: Counterparty,
    clock: str,
    expected_bounds_digest: str,
) -> tuple[TransactionVerdictOutcome | None, str, str]:
    """Return ``(blocking_or_None, result_key, reason)`` for one exposure row."""

    if decision.is_stale(clock):
        return (
            TransactionVerdictOutcome.STALE,
            "stale",
            f"exposure evidence stale for {party.party_id}",
        )
    if expected_bounds_digest and decision.bounds_digest != expected_bounds_digest:
        return (
            TransactionVerdictOutcome.DENY,
            "bounds_mismatch",
            (
                f"exposure bounds for {party.party_id} do not match the "
                "configured named bounds"
            ),
        )
    if decision.truncated or decision.verdict is ExposureVerdict.TRUNCATED:
        return (
            TransactionVerdictOutcome.INCONCLUSIVE,
            "truncated",
            (
                f"exposure search truncated for {party.party_id}; "
                "cannot prove absence"
            ),
        )
    if (
        decision.incomplete_frontier
        or decision.verdict is ExposureVerdict.INCOMPLETE_FRONTIER
    ):
        return (
            TransactionVerdictOutcome.INCONCLUSIVE,
            "incomplete_frontier",
            (
                f"exposure completeness frontier incomplete for "
                f"{party.party_id}"
            ),
        )
    if decision.verdict is ExposureVerdict.ERROR:
        return (
            TransactionVerdictOutcome.ERROR,
            "exposure_error",
            f"exposure analysis error for {party.party_id}",
        )
    if decision.verdict is ExposureVerdict.MISSING:
        return (
            TransactionVerdictOutcome.INCONCLUSIVE,
            "exposure_missing",
            f"exposure evidence missing for {party.party_id}",
        )
    if decision.verdict is ExposureVerdict.DIRECT_HIT:
        return (
            policy_outcome_to_transaction(decision.outcome),
            "direct_hit",
            f"bounded-flow direct hit for {party.party_id}",
        )
    if decision.verdict is ExposureVerdict.INDIRECT_EXPOSURE:
        # Obey named policy outcome (REVIEW or DENY only by construction).
        return (
            policy_outcome_to_transaction(decision.outcome),
            "indirect_exposure",
            (
                f"bounded-flow indirect exposure for {party.party_id} "
                f"under policy {decision.policy_id}"
            ),
        )
    if decision.verdict is ExposureVerdict.CLEAR:
        if decision.outcome is not SanctionsPolicyOutcome.ALLOW:
            return (
                policy_outcome_to_transaction(decision.outcome),
                "clear_non_allow",
                f"clear verdict with non-ALLOW outcome for {party.party_id}",
            )
        return (None, "clear", f"bounded-flow clear for {party.party_id}")
    if decision.verdict is ExposureVerdict.STALE:
        return (
            TransactionVerdictOutcome.STALE,
            "stale",
            f"exposure stale for {party.party_id}",
        )
    return (
        TransactionVerdictOutcome.INCONCLUSIVE,
        "exposure_unknown",
        f"unrecognized exposure verdict for {party.party_id}",
    )


@dataclass
class ComplianceGate:
    """Compose direct-sanctions and bounded-flow evidence for one candidate.

    Deterministic, fail-closed, and custody-neutral.  Screens every party in
    the bound :class:`CounterpartySet`—including fee recipients, bridge legs,
    multisend outputs, UTXO change, spenders, token issuers, proxies, and
    routers—so displayed-destination-only screening cannot bypass policy.
    """

    producer_id: str = DEFAULT_PRODUCER_ID
    interface: str = COMPLIANCE_GATE_INTERFACE
    schema_version: str = COMPLIANCE_GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.interface != COMPLIANCE_GATE_INTERFACE:
            raise GuardValidationError(
                f"unsupported compliance gate interface: {self.interface!r}"
            )
        if self.schema_version != COMPLIANCE_GATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported compliance gate schema: {self.schema_version!r}"
            )
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )

    def evaluate(
        self,
        request: ComplianceGateRequest | Mapping[str, Any],
        *,
        now: str | None = None,
    ) -> ComplianceGateDecision:
        """Evaluate compliance for *request* at *now* (ISO-8601)."""

        if not isinstance(request, ComplianceGateRequest):
            if isinstance(request, Mapping):
                request = ComplianceGateRequest.from_dict(request)
            else:
                raise GuardValidationError(
                    "request must be a ComplianceGateRequest"
                )

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        sanctions_results: dict[str, str] = {}
        exposure_results: dict[str, str] = {}
        blocking: TransactionVerdictOutcome | None = None

        def _block(
            outcome: TransactionVerdictOutcome, code: str, reason: str
        ) -> None:
            nonlocal blocking
            reason_codes.append(code)
            reasons.append(reason)
            blocking = _prefer_blocking(blocking, outcome)

        # Request / intent freshness
        if _is_expired(request.expiry, clock):
            _block(
                TransactionVerdictOutcome.STALE,
                "compliance.request_expired",
                "compliance gate request expired before evaluation",
            )
        if _is_expired(request.intent.expires_at, clock):
            _block(
                TransactionVerdictOutcome.STALE,
                "compliance.intent_expired",
                "unsigned intent expired before evaluation",
            )

        counterparties = request.counterparties
        present_roles = counterparties.roles
        required_roles = _required_roles_for_intent(request.intent)

        # Anti-bypass: effect kinds require named counterparty roles.
        missing_roles = sorted(required_roles - present_roles)
        if missing_roles:
            _block(
                TransactionVerdictOutcome.DENY,
                "compliance.missing_roles",
                (
                    "economically relevant counterparty roles missing from "
                    f"screening set: {', '.join(missing_roles)}"
                ),
            )

        # Destination-only sets that omit fee/bridge/multisend/change when
        # those effects are declared are already covered by missing_roles.
        # Also refuse empty-of-recipient sets (structural).
        if CounterpartyRole.RECIPIENT.value not in present_roles:
            _block(
                TransactionVerdictOutcome.DENY,
                "compliance.missing_recipient",
                "recipient/destination counterparty must be screened",
            )

        sanctions_index = _index_sanctions(request.sanctions_decisions)
        exposure_index = _index_exposure(request.exposure_decisions)

        for party in counterparties.counterparties:
            key = party.screening_key
            sanctions = _lookup_sanctions(sanctions_index, party)
            if sanctions is None:
                sanctions_results[key] = "missing"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"compliance.sanctions_missing:{key}",
                    f"missing sanctions decision for {key}",
                )
            else:
                block, result_key, reason = _evaluate_sanctions_decision(
                    sanctions,
                    party=party,
                    clock=clock,
                    activity_id=request.activity_id,
                    list_snapshot_id=request.list_snapshot_id,
                    list_revision=request.list_revision,
                )
                sanctions_results[key] = result_key
                if block is not None:
                    _block(
                        block,
                        f"compliance.sanctions:{result_key}:{key}",
                        reason,
                    )

            if request.require_exposure:
                exposure = _lookup_exposure(exposure_index, party)
                if exposure is None:
                    exposure_results[key] = "missing"
                    _block(
                        TransactionVerdictOutcome.INCONCLUSIVE,
                        f"compliance.exposure_missing:{key}",
                        f"missing exposure decision for {key}",
                    )
                else:
                    block, result_key, reason = _evaluate_exposure_decision(
                        exposure,
                        party=party,
                        clock=clock,
                        expected_bounds_digest=request.expected_bounds_digest,
                    )
                    exposure_results[key] = result_key
                    if block is not None:
                        _block(
                            block,
                            f"compliance.exposure:{result_key}:{key}",
                            reason,
                        )

        if blocking is None:
            outcome = TransactionVerdictOutcome.ALLOW
            if not reason_codes:
                reason_codes.append("compliance.allow")
                reasons.append(
                    "all counterparties clear under direct sanctions and "
                    "bounded-flow policy"
                )
            blocks = False
        else:
            outcome = blocking
            blocks = True

        decision_id = "decision:" + stable_digest(
            {
                "request": request.request_digest,
                "producer": self.producer_id,
                "outcome": outcome.value,
            }
        )[:32]

        return ComplianceGateDecision(
            decision_id=decision_id,
            request_digest=request.request_digest,
            outcome=outcome,
            blocks_automation=blocks,
            reason_codes=tuple(reason_codes),
            reasons=tuple(reasons),
            intent_digest=request.intent_digest,
            candidate_digest=request.candidate_digest,
            network=request.intent.network,
            counterparty_set_digest=counterparties.digest,
            screened_party_ids=counterparties.party_ids,
            screened_roles=tuple(sorted(present_roles)),
            sanctions_results=sanctions_results,
            exposure_results=exposure_results,
            sanctions_decision_ids=tuple(
                d.decision_id for d in request.sanctions_decisions
            ),
            exposure_decision_ids=tuple(
                d.decision_id for d in request.exposure_decisions
            ),
            list_snapshot_id=request.list_snapshot_id,
            list_revision=request.list_revision,
            issued_at=request.issued_at,
            expiry=request.expiry,
            producer_id=self.producer_id,
        )

    def revalidate(
        self,
        decision: ComplianceGateDecision | Mapping[str, Any],
        request: ComplianceGateRequest | Mapping[str, Any],
        *,
        now: str | None = None,
    ) -> ComplianceGateDecision:
        """Revalidate a prior decision against the live request.

        Any material change (candidate, counterparty set, list revision) or
        re-evaluation that blocks automation invalidates prior permission.
        """

        if not isinstance(decision, ComplianceGateDecision):
            if isinstance(decision, Mapping):
                decision = ComplianceGateDecision.from_dict(decision)
            else:
                raise GuardValidationError(
                    "decision must be a ComplianceGateDecision"
                )
        if not isinstance(request, ComplianceGateRequest):
            if isinstance(request, Mapping):
                request = ComplianceGateRequest.from_dict(request)
            else:
                raise GuardValidationError(
                    "request must be a ComplianceGateRequest"
                )

        mismatches: list[str] = []
        if decision.request_digest != request.request_digest:
            mismatches.append("request_digest")
        if decision.intent_digest != request.intent_digest:
            mismatches.append("intent_digest")
        if decision.candidate_digest != request.candidate_digest:
            mismatches.append("candidate_digest")
        if decision.network != request.intent.network:
            mismatches.append("network")
        if decision.counterparty_set_digest != request.counterparties.digest:
            mismatches.append("counterparty_set")
        if (
            decision.list_snapshot_id
            and request.list_snapshot_id
            and decision.list_snapshot_id != request.list_snapshot_id
        ):
            mismatches.append("list_snapshot_id")
        if (
            decision.list_revision
            and request.list_revision
            and decision.list_revision != request.list_revision
        ):
            mismatches.append("list_revision")

        if mismatches:
            return ComplianceGateDecision(
                decision_id="decision:"
                + stable_digest(
                    {
                        "prior": decision.digest,
                        "mismatches": mismatches,
                        "request": request.request_digest,
                    }
                )[:32],
                request_digest=request.request_digest,
                outcome=TransactionVerdictOutcome.STALE,
                blocks_automation=True,
                reason_codes=("compliance.revalidate_mismatch",),
                reasons=(
                    "prior compliance permission invalidated: "
                    + ", ".join(mismatches),
                ),
                intent_digest=request.intent_digest,
                candidate_digest=request.candidate_digest,
                network=request.intent.network,
                counterparty_set_digest=request.counterparties.digest,
                screened_party_ids=request.counterparties.party_ids,
                screened_roles=tuple(sorted(request.counterparties.roles)),
                sanctions_results=dict(decision.sanctions_results),
                exposure_results=dict(decision.exposure_results),
                sanctions_decision_ids=tuple(
                    d.decision_id for d in request.sanctions_decisions
                ),
                exposure_decision_ids=tuple(
                    d.decision_id for d in request.exposure_decisions
                ),
                list_snapshot_id=request.list_snapshot_id,
                list_revision=request.list_revision,
                issued_at=request.issued_at,
                expiry=request.expiry,
                producer_id=self.producer_id,
            )

        # Fresh re-evaluation under the same bindings.
        return self.evaluate(request, now=now)


def evaluate_compliance_gate(
    request: ComplianceGateRequest | Mapping[str, Any],
    *,
    now: str | None = None,
    producer_id: str = DEFAULT_PRODUCER_ID,
) -> ComplianceGateDecision:
    """Module-level convenience wrapper around :class:`ComplianceGate`."""

    return ComplianceGate(producer_id=producer_id).evaluate(request, now=now)


__all__ = [
    "COMPLIANCE_GATE_DECISION_SCHEMA_VERSION",
    "COMPLIANCE_GATE_INTERFACE",
    "COMPLIANCE_GATE_REQUEST_SCHEMA_VERSION",
    "COMPLIANCE_GATE_SCHEMA_VERSION",
    "COUNTERPARTY_SET_SCHEMA_VERSION",
    "DEFAULT_PRODUCER_ID",
    "EXPOSURE_DECISION_SCHEMA_VERSION",
    "SANCTIONS_DECISION_SCHEMA_VERSION",
    "ComplianceGate",
    "ComplianceGateDecision",
    "ComplianceGateRequest",
    "Counterparty",
    "CounterpartyRole",
    "CounterpartySet",
    "ExposureDecision",
    "ExposureVerdict",
    "SanctionsDecision",
    "evaluate_compliance_gate",
    "policy_outcome_to_transaction",
]
