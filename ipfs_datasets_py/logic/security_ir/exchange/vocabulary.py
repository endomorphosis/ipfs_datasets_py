"""Namespaced crypto-exchange vocabulary for Security IR v1.

The shared :mod:`security_ir.model` records intentionally do not assign
meaning to words such as ``wallet``, ``withdrawals`` or
``authorization_required``.  This module owns those terms, their version, and
the shape of the single extension used by the exchange adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from ..model import SecurityExtension


EXCHANGE_VOCABULARY: Final = "security.crypto-exchange"
EXCHANGE_VOCABULARY_NAMESPACE: Final = EXCHANGE_VOCABULARY
EXCHANGE_VOCABULARY_VERSION: Final = "v1"
EXCHANGE_VOCABULARY_SCHEMA_VERSION: Final = (
    f"{EXCHANGE_VOCABULARY}/{EXCHANGE_VOCABULARY_VERSION}"
)
EXCHANGE_SCHEMA_VERSION: Final = EXCHANGE_VOCABULARY_SCHEMA_VERSION
EXCHANGE_EXTENSION_ID: Final = "extension:security.crypto-exchange:v1"

EXCHANGE_DOMAINS: Final = frozenset(
    {"audit", "capabilities", "deposits", "hsm", "ledger", "withdrawals"}
)
EXCHANGE_RESOURCE_KINDS: Final = frozenset(
    {"account", "entity", "wallet"}
)
EXCHANGE_WALLET_STATUSES: Final = frozenset(
    {"active", "disabled", "frozen", "retired", "rotating"}
)
EXCHANGE_EVENT_TYPES: Final = frozenset(
    {
        "audit_logged",
        "balance_released",
        "balance_reserved",
        "capability_reinstated",
        "capability_revoked",
        "chain_reorg_detected",
        "deposit_credited",
        "deposit_finalized",
        "deposit_observed",
        "nonce_consumed",
        "nonce_reserved",
        "privileged_action",
        "signing_request",
        "wallet_frozen",
        "wallet_unfrozen",
        "withdrawal_approved",
        "withdrawal_broadcast",
        "withdrawal_cancelled",
        "withdrawal_requested",
    }
)
EXCHANGE_POLICY_NAMES: Final = frozenset(
    {
        "atomic_reservation",
        "audit_required",
        "authorization_required",
        "credit_after_finality_required",
        "delegation_monotonicity",
        "fresh_nonce_required",
        "revocation_enforced",
        "sufficient_balance_required",
        "wallet_not_frozen_required",
    }
)
EXCHANGE_PROVER_TARGETS: Final = frozenset(
    {
        "coq",
        "cvc5",
        "datalog",
        "ergoai",
        "hyperltl",
        "lean",
        "proverif",
        "tamarin",
        "tla",
        "z3",
    }
)

EXCHANGE_ASSUMPTIONS: Final = MappingProxyType(
    {
        "A1": "cryptographic primitives are unbroken",
        "A2": "private keys are generated with sufficient entropy",
        "A3": "signing code signs only approved canonical transaction bytes",
        "A4": "database commits are serializable",
        "A5": "nonce reservation is atomic",
        "A6": "blockchain finality threshold k is sufficient",
        "A7": "admin identities are not all compromised",
        "A8": "HSM/key manager obeys its interface contract",
        "A9": "external RPC providers may lie/delay/censor within modeled bounds",
        "A10": "audit logs are append-only or tamper-evident",
    }
)


@dataclass(frozen=True, slots=True)
class ExchangeClaimSpec:
    """Stable semantics for a built-in exchange claim."""

    claim_id: str
    domain: str
    statement: str
    severity: str
    assumption_ids: tuple[str, ...]
    policy_names: tuple[str, ...] = ()


DEFAULT_EXCHANGE_CLAIMS: Final = (
    ExchangeClaimSpec(
        "no_unauthorized_withdrawal",
        "withdrawals",
        "No withdrawal broadcast occurs without authorization.",
        "blocking",
        ("A3", "A4", "A5", "A8"),
        (
            "authorization_required",
            "fresh_nonce_required",
            "sufficient_balance_required",
            "wallet_not_frozen_required",
        ),
    ),
    ExchangeClaimSpec(
        "no_over_reserved_internal_account",
        "ledger",
        "No internal account is over-reserved.",
        "blocking",
        ("A4", "A5"),
        ("atomic_reservation",),
    ),
    ExchangeClaimSpec(
        "global_asset_conservation",
        "ledger",
        "Global asset liabilities are covered by custody assets.",
        "blocking",
        ("A4", "A10"),
    ),
    ExchangeClaimSpec(
        "no_deposit_before_finality",
        "deposits",
        "Deposits are credited only after finality is reached.",
        "high",
        ("A6", "A9"),
        ("credit_after_finality_required",),
    ),
    ExchangeClaimSpec(
        "no_signing_request_after_wallet_freeze",
        "hsm",
        "No signing request after wallet freeze.",
        "high",
        ("A3", "A8"),
        ("wallet_not_frozen_required",),
    ),
    ExchangeClaimSpec(
        "capability_delegation_no_authority_increase",
        "capabilities",
        "Capability delegation cannot increase authority.",
        "high",
        ("A1", "A7"),
        ("delegation_monotonicity",),
    ),
    ExchangeClaimSpec(
        "revoked_capability_no_future_authorization",
        "capabilities",
        "Revoked capability cannot authorize future action.",
        "high",
        ("A10",),
        ("revocation_enforced",),
    ),
    ExchangeClaimSpec(
        "audit_event_exists_for_critical_transition",
        "audit",
        "Audit event exists for every critical transition.",
        "medium",
        ("A10",),
        ("audit_required",),
    ),
)
DEFAULT_EXCHANGE_CLAIMS_BY_ID: Final = MappingProxyType(
    {item.claim_id: item for item in DEFAULT_EXCHANGE_CLAIMS}
)

EXCHANGE_EXTENSION_FIELDS: Final = (
    "roles",
    "capabilities",
    "events",
    "invariants",
    "prover_targets",
    "metadata",
)


class ExchangeVocabularyError(ValueError):
    """Raised when an exchange vocabulary term or payload is malformed."""


def exchange_term(category: str, value: str) -> str:
    """Return the canonical namespaced spelling of an exchange term."""

    if not isinstance(category, str) or not category:
        raise ExchangeVocabularyError("exchange term category must be non-empty")
    if not isinstance(value, str) or not value:
        raise ExchangeVocabularyError("exchange term value must be non-empty")
    if "/" in category or "/" in value:
        raise ExchangeVocabularyError("exchange term components must not contain '/'")
    return f"{EXCHANGE_VOCABULARY_SCHEMA_VERSION}/{category}/{value}"


def parse_exchange_term(value: str, *, category: str) -> str:
    """Validate and remove the namespace from an exchange term."""

    prefix = f"{EXCHANGE_VOCABULARY_SCHEMA_VERSION}/{category}/"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ExchangeVocabularyError(
            f"expected a {category!r} term in {EXCHANGE_VOCABULARY_SCHEMA_VERSION}"
        )
    local_name = value[len(prefix) :]
    if not local_name or "/" in local_name:
        raise ExchangeVocabularyError(f"malformed exchange {category} term")
    return local_name


def _records(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise ExchangeVocabularyError(f"{field_name} must be a sequence")
    records = tuple(value)
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ExchangeVocabularyError(
                f"{field_name}[{index}] must be a mapping"
            )
    return records


def _unique_record_ids(
    records: Sequence[Mapping[str, Any]], field_name: str
) -> None:
    seen: set[str] = set()
    for index, record in enumerate(records):
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise ExchangeVocabularyError(
                f"{field_name}[{index}].id must be a non-empty string"
            )
        if record_id in seen:
            raise ExchangeVocabularyError(
                f"{field_name} contains duplicate id {record_id!r}"
            )
        seen.add(record_id)


def validate_exchange_extension(
    extension: SecurityExtension,
) -> SecurityExtension:
    """Validate the exchange extension's namespace, version, and payload."""

    if not isinstance(extension, SecurityExtension):
        raise ExchangeVocabularyError(
            "exchange extension must be a SecurityExtension"
        )
    if extension.extension_id != EXCHANGE_EXTENSION_ID:
        raise ExchangeVocabularyError(
            f"exchange extension id must be {EXCHANGE_EXTENSION_ID!r}"
        )
    if extension.vocabulary != EXCHANGE_VOCABULARY:
        raise ExchangeVocabularyError(
            f"exchange vocabulary must be {EXCHANGE_VOCABULARY!r}"
        )
    if extension.version != EXCHANGE_VOCABULARY_VERSION:
        raise ExchangeVocabularyError(
            f"unsupported exchange vocabulary version: {extension.version!r}"
        )
    if not extension.required:
        raise ExchangeVocabularyError("exchange extension must be required")
    if not isinstance(extension.payload, Mapping):
        raise ExchangeVocabularyError("exchange extension payload must be a mapping")

    payload = extension.payload
    allowed = {"schema_version", *EXCHANGE_EXTENSION_FIELDS}
    unknown = sorted(set(payload) - allowed)
    missing = sorted(allowed - set(payload))
    if unknown:
        raise ExchangeVocabularyError(
            f"unknown exchange extension field(s): {', '.join(unknown)}"
        )
    if missing:
        raise ExchangeVocabularyError(
            f"missing exchange extension field(s): {', '.join(missing)}"
        )
    if payload["schema_version"] != EXCHANGE_VOCABULARY_SCHEMA_VERSION:
        raise ExchangeVocabularyError(
            "exchange extension schema_version does not match its vocabulary"
        )

    roles = _records(payload["roles"], "roles")
    capabilities = _records(payload["capabilities"], "capabilities")
    events = _records(payload["events"], "events")
    invariants = _records(payload["invariants"], "invariants")
    for name, records in (
        ("roles", roles),
        ("capabilities", capabilities),
        ("events", events),
        ("invariants", invariants),
    ):
        _unique_record_ids(records, name)

    for index, event in enumerate(events):
        event_name = event.get("event")
        if event_name not in EXCHANGE_EVENT_TYPES:
            raise ExchangeVocabularyError(
                f"events[{index}] uses unknown exchange event {event_name!r}"
            )
    targets = payload["prover_targets"]
    if isinstance(targets, (str, bytes, bytearray)) or not isinstance(
        targets, Sequence
    ):
        raise ExchangeVocabularyError("prover_targets must be a sequence")
    if not targets:
        raise ExchangeVocabularyError("prover_targets must not be empty")
    if any(not isinstance(target, str) or not target for target in targets):
        raise ExchangeVocabularyError(
            "prover_targets must contain non-empty strings"
        )
    if len(targets) != len(set(targets)):
        raise ExchangeVocabularyError("prover_targets must be unique")
    unsupported_targets = sorted(set(targets) - EXCHANGE_PROVER_TARGETS)
    if unsupported_targets:
        raise ExchangeVocabularyError(
            "unsupported exchange prover target(s): "
            + ", ".join(unsupported_targets)
        )
    if not isinstance(payload["metadata"], Mapping):
        raise ExchangeVocabularyError("metadata must be a mapping")
    return extension


validate_exchange_vocabulary = validate_exchange_extension


__all__ = [
    "DEFAULT_EXCHANGE_CLAIMS",
    "DEFAULT_EXCHANGE_CLAIMS_BY_ID",
    "EXCHANGE_ASSUMPTIONS",
    "EXCHANGE_DOMAINS",
    "EXCHANGE_EVENT_TYPES",
    "EXCHANGE_EXTENSION_FIELDS",
    "EXCHANGE_EXTENSION_ID",
    "EXCHANGE_POLICY_NAMES",
    "EXCHANGE_PROVER_TARGETS",
    "EXCHANGE_RESOURCE_KINDS",
    "EXCHANGE_SCHEMA_VERSION",
    "EXCHANGE_VOCABULARY",
    "EXCHANGE_VOCABULARY_NAMESPACE",
    "EXCHANGE_VOCABULARY_SCHEMA_VERSION",
    "EXCHANGE_VOCABULARY_VERSION",
    "EXCHANGE_WALLET_STATUSES",
    "ExchangeClaimSpec",
    "ExchangeVocabularyError",
    "exchange_term",
    "parse_exchange_term",
    "validate_exchange_extension",
    "validate_exchange_vocabulary",
]
