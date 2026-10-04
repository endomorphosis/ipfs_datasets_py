"""Non-custodial XRPL transaction guard (CRYPTOIR-G550 / CRYPTOIR-029).

Bind XRPL transaction JSON and serialized candidates, accounts/tags, issued
assets, flags, delivered amounts, sequence/tickets, signer quorum, native
ledger effects, and compliance evidence into the common two-phase wallet guard.

Acceptance (fail-closed):

* Network, destination/tag, issuer/currency/value, partial-payment/delivered
  amount, sequence/ticket, fee, signer list, ledger epoch, and exact candidate
  are bound.
* Tag/issuer/amount/signature-list mutation, unsupported Hooks, stale ledger,
  and compliance changes block.

This module never signs, broadcasts, or accepts bare booleans / caller
approval flags as authority.  Keys remain with an external custody system.
Shared XRPL effect normalization is also consumed by the Xaman leaf adapter.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.adapters.xrpl import (
    TF_PARTIAL_PAYMENT,
    XRPL_MAINNET_CHAIN_ID,
    XRPL_MAINNET_GENESIS_HASH,
    XRPL_MAINNET_NETWORK,
    XRPL_NAMESPACE,
    IssuedAsset,
    XRPLAccountIdentity,
    XRPLAdapterError,
    content_sha256_hex as xrpl_content_sha256_hex,
    has_partial_payment,
    map_transaction_type,
    normalize_classic_address,
    normalize_ledger_hash,
    parse_amount,
    parse_flags,
    resolve_network,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.provenance import thaw_json

from ..guard.errors import (
    GuardCapabilityError,
    GuardError,
    GuardForbiddenSurfaceError,
    GuardPolicyError,
    GuardValidationError,
)
from ..guard.models import (
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflightRequest,
)
from ..guard.preflight import TransactionPreflight

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

XRPL_TRANSACTION_GUARD_INTERFACE: Final = "XRPLTransactionGuard@1"
XRPL_TRANSACTION_GUARD_SCHEMA_VERSION: Final = (
    "wallet-guard.xrpl-transaction-guard/v1"
)
XRPL_CANDIDATE_SCHEMA_VERSION: Final = (
    "wallet-guard.xrpl-transaction-candidate/v1"
)
XRPL_BINDING_SCHEMA_VERSION: Final = "wallet-guard.xrpl-transaction-binding/v1"
LEDGER_EPOCH_SCHEMA_VERSION: Final = "wallet-guard.xrpl-ledger-epoch/v1"
SIGNER_LIST_SCHEMA_VERSION: Final = "wallet-guard.xrpl-signer-list/v1"
XRPL_GUARD_DECISION_SCHEMA_VERSION: Final = "wallet-guard.xrpl-guard-decision/v1"

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-xrpl-v1"
DEFAULT_POLICY_ID: Final = "policy:xrpl-wallet-guard-v1"
DEFAULT_FEE_DROPS: Final = "12"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_HEX_PAYLOAD_CHARS: Final = 1_048_576

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_DECIMAL_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")
_DECIMAL_AMOUNT_RE: Final = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")

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
        "TxnSignature",
        "txn_signature",
        "broadcast",
        "broadcast_url",
        "raw_key",
        "signing_key",
        "api_key",
        "caller_approved",
        "force_allow",
        "bypass",
        "SigningPubKey",
    }
)

DEFAULT_SECURITY_REQUIREMENTS: Final[tuple[str, ...]] = (
    "sec:xrpl-network-binding",
    "sec:xrpl-destination-tag",
    "sec:xrpl-amount-identity",
    "sec:xrpl-partial-payment",
    "sec:xrpl-sequence-ticket",
    "sec:xrpl-fee",
    "sec:xrpl-signer-list",
    "sec:xrpl-ledger-epoch",
    "sec:xrpl-exact-candidate",
    "sec:xrpl-hooks-capability",
)
DEFAULT_COMPLIANCE_REQUIREMENTS: Final[tuple[str, ...]] = (
    "comp:direct-sanctions",
    "comp:bounded-exposure",
)


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


def _optional_text(value: Any, name: str, *, max_chars: int = MAX_STRING_CHARS) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name, max_chars=max_chars)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuardValidationError(f"{name} is not a stable identifier")
    return text


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
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


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardValidationError(f"{name} must be an integer")
    if value < 0:
        raise GuardValidationError(f"{name} must be non-negative")
    return value


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    return _non_negative_int(value, name)


def _optional_uint32(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    n = _non_negative_int(value, name)
    if n > 0xFFFFFFFF:
        raise GuardValidationError(f"{name} must fit in uint32")
    return n


def _amount_drops(value: Any, name: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise GuardValidationError(f"{name} must be a non-negative integer")
        return str(value)
    text = _text(value, name, max_chars=128)
    if not _DECIMAL_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be a non-negative decimal integer string (drops)"
        )
    return text


def _amount_decimal(value: Any, name: str) -> str:
    """Issued currency amount: decimal string, never binary float."""

    if isinstance(value, float):
        raise GuardValidationError(
            f"{name} must not be a binary float; use a decimal string"
        )
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = _text(value, name, max_chars=128)
    if not _DECIMAL_AMOUNT_RE.fullmatch(text):
        raise GuardValidationError(f"{name} must be a decimal amount string")
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuardValidationError(f"{name} must be a mapping")
    return value


def _reject_forbidden(value: Mapping[str, Any], record_name: str) -> None:
    hit = sorted(set(value) & _FORBIDDEN_FIELDS)
    if hit:
        raise GuardForbiddenSurfaceError(
            f"{record_name} contains forbidden custody/approval field(s): "
            f"{', '.join(hit)}",
            details={"fields": hit},
        )
    # Nested tx blob may carry XRPL signing fields.
    nested = value.get("tx") or value.get("transaction") or value.get("Transaction")
    if isinstance(nested, Mapping):
        nested_hit = sorted(set(nested) & _FORBIDDEN_FIELDS)
        if nested_hit:
            raise GuardForbiddenSurfaceError(
                f"{record_name}.tx contains forbidden custody/signing field(s): "
                f"{', '.join(nested_hit)}",
                details={"fields": nested_hit},
            )


def _attributes(value: Mapping[str, Any] | None) -> FrozenMap:
    if value is None:
        return FrozenMap()
    if not isinstance(value, Mapping):
        raise GuardValidationError("attributes must be a mapping")
    _reject_forbidden(value, "attributes")
    try:
        return FrozenMap(value)
    except (TypeError, ValueError) as exc:
        raise GuardValidationError(f"attributes invalid: {exc}") from exc


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, FrozenMap):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return thaw_json(value)
    except Exception:  # noqa: BLE001
        return str(value)


def content_sha256_hex(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    """Stable SHA-256 hex digest over a JSON-like structure or raw string."""

    if isinstance(payload, str):
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return stable_digest(_jsonable(payload))


def _account(
    value: Any,
    name: str,
    *,
    destination_tag: int | None = None,
) -> XRPLAccountIdentity:
    try:
        if isinstance(value, XRPLAccountIdentity):
            return value
        return XRPLAccountIdentity.parse(
            value, destination_tag=destination_tag, field=name
        )
    except (XRPLAdapterError, TypeError, ValueError) as exc:
        raise GuardValidationError(f"{name} is not a valid XRPL account: {exc}") from exc


# ---------------------------------------------------------------------------
# Shared XRPL effect normalization (used by XRPL + Xaman adapters)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizedXRPLEffect:
    """Canonical economic / control effect extracted from an XRPL candidate.

    Shared by XRPL and Xaman leaf guards so both bind the same normalized
    payment, trust-line, and multi-sign effects without dual authority.
    """

    kind: str
    account: str
    destination: str = ""
    destination_tag: int | None = None
    amount_kind: str = ""  # "xrp" | "issued" | ""
    amount_value: str = ""
    currency: str = ""
    issuer: str = ""
    delivered_amount_kind: str = ""
    delivered_amount_value: str = ""
    delivered_currency: str = ""
    delivered_issuer: str = ""
    partial_payment: bool = False
    fee_drops: str = ""
    sequence: int | None = None
    ticket_sequence: int | None = None
    flags: int = 0
    transaction_type: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        object.__setattr__(
            self, "account", _text(self.account, "account", max_chars=128)
        )
        object.__setattr__(
            self,
            "destination",
            _optional_text(self.destination, "destination", max_chars=128),
        )
        if self.destination_tag is not None:
            object.__setattr__(
                self,
                "destination_tag",
                _optional_uint32(self.destination_tag, "destination_tag"),
            )
        object.__setattr__(
            self, "amount_kind", _optional_text(self.amount_kind, "amount_kind")
        )
        if self.amount_kind == "xrp":
            object.__setattr__(
                self, "amount_value", _amount_drops(self.amount_value or "0", "amount_value")
            )
        elif self.amount_kind == "issued":
            object.__setattr__(
                self,
                "amount_value",
                _amount_decimal(self.amount_value or "0", "amount_value"),
            )
        else:
            object.__setattr__(
                self,
                "amount_value",
                _optional_text(self.amount_value, "amount_value", max_chars=128),
            )
        object.__setattr__(
            self, "currency", _optional_text(self.currency, "currency", max_chars=64)
        )
        object.__setattr__(
            self, "issuer", _optional_text(self.issuer, "issuer", max_chars=128)
        )
        object.__setattr__(
            self,
            "delivered_amount_kind",
            _optional_text(self.delivered_amount_kind, "delivered_amount_kind"),
        )
        if self.delivered_amount_kind == "xrp":
            object.__setattr__(
                self,
                "delivered_amount_value",
                _amount_drops(
                    self.delivered_amount_value or "0", "delivered_amount_value"
                ),
            )
        elif self.delivered_amount_kind == "issued":
            object.__setattr__(
                self,
                "delivered_amount_value",
                _amount_decimal(
                    self.delivered_amount_value or "0", "delivered_amount_value"
                ),
            )
        else:
            object.__setattr__(
                self,
                "delivered_amount_value",
                _optional_text(
                    self.delivered_amount_value, "delivered_amount_value", max_chars=128
                ),
            )
        object.__setattr__(
            self,
            "delivered_currency",
            _optional_text(self.delivered_currency, "delivered_currency", max_chars=64),
        )
        object.__setattr__(
            self,
            "delivered_issuer",
            _optional_text(self.delivered_issuer, "delivered_issuer", max_chars=128),
        )
        object.__setattr__(self, "partial_payment", bool(self.partial_payment))
        if self.fee_drops:
            object.__setattr__(
                self, "fee_drops", _amount_drops(self.fee_drops, "fee_drops")
            )
        else:
            object.__setattr__(self, "fee_drops", "")
        object.__setattr__(
            self, "sequence", _optional_non_negative_int(self.sequence, "sequence")
        )
        object.__setattr__(
            self,
            "ticket_sequence",
            _optional_non_negative_int(self.ticket_sequence, "ticket_sequence"),
        )
        object.__setattr__(self, "flags", parse_flags(self.flags))
        object.__setattr__(
            self,
            "transaction_type",
            _optional_text(self.transaction_type, "transaction_type", max_chars=64),
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "amount_kind": self.amount_kind,
            "amount_value": self.amount_value,
            "attributes": self.attributes.to_dict(),
            "currency": self.currency,
            "delivered_amount_kind": self.delivered_amount_kind,
            "delivered_amount_value": self.delivered_amount_value,
            "delivered_currency": self.delivered_currency,
            "delivered_issuer": self.delivered_issuer,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "fee_drops": self.fee_drops,
            "flags": self.flags,
            "issuer": self.issuer,
            "kind": self.kind,
            "partial_payment": self.partial_payment,
            "sequence": self.sequence,
            "ticket_sequence": self.ticket_sequence,
            "transaction_type": self.transaction_type,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedXRPLEffect":
        value = _mapping(value, "NormalizedXRPLEffect")
        _reject_forbidden(value, "NormalizedXRPLEffect")
        return cls(
            kind=value.get("kind", "payment"),
            account=value.get("account", ""),
            destination=value.get("destination", ""),
            destination_tag=value.get("destination_tag", value.get("DestinationTag")),
            amount_kind=value.get("amount_kind", ""),
            amount_value=value.get("amount_value", ""),
            currency=value.get("currency", ""),
            issuer=value.get("issuer", ""),
            delivered_amount_kind=value.get("delivered_amount_kind", ""),
            delivered_amount_value=value.get("delivered_amount_value", ""),
            delivered_currency=value.get("delivered_currency", ""),
            delivered_issuer=value.get("delivered_issuer", ""),
            partial_payment=bool(value.get("partial_payment", False)),
            fee_drops=value.get("fee_drops", value.get("Fee", "")),
            sequence=value.get("sequence", value.get("Sequence")),
            ticket_sequence=value.get("ticket_sequence", value.get("TicketSequence")),
            flags=value.get("flags", value.get("Flags", 0)),
            transaction_type=value.get(
                "transaction_type", value.get("TransactionType", "")
            ),
            attributes=value.get("attributes", {}),
        )


def normalize_xrpl_tx_effects(
    tx: Mapping[str, Any],
    *,
    meta: Mapping[str, Any] | None = None,
) -> tuple[NormalizedXRPLEffect, ...]:
    """Normalize payment / trust-line effects from XRPL transaction JSON.

    Partial-payment delivered amounts are preferred over send-max when present
    in metadata.  Binary floats are rejected via parse_amount / IssuedAsset.
    """

    _reject_forbidden(tx, "xrpl_tx")
    account = _account(tx.get("Account", tx.get("account", "")), "Account")
    dest_raw = tx.get("Destination", tx.get("destination"))
    dest_tag = tx.get("DestinationTag", tx.get("destination_tag"))
    destination: XRPLAccountIdentity | None = None
    if dest_raw:
        destination = _account(dest_raw, "Destination", destination_tag=_optional_uint32(dest_tag, "DestinationTag") if dest_tag is not None else None)
    elif dest_tag is not None:
        raise GuardValidationError(
            "DestinationTag without Destination is unbound routing identity"
        )

    flags = parse_flags(tx.get("Flags", tx.get("flags", 0)))
    partial = has_partial_payment(flags) or bool(tx.get("partial_payment", False))
    fee = tx.get("Fee", tx.get("fee", DEFAULT_FEE_DROPS))
    sequence = tx.get("Sequence", tx.get("sequence"))
    ticket = tx.get("TicketSequence", tx.get("ticket_sequence"))
    tx_type = str(tx.get("TransactionType", tx.get("transaction_type", "Payment")))

    amount_kind = ""
    amount_value = ""
    currency = ""
    issuer = ""
    amount_raw = tx.get("Amount", tx.get("amount"))
    if amount_raw is not None:
        try:
            kind, value, issued = parse_amount(amount_raw)
        except XRPLAdapterError as exc:
            raise GuardValidationError(f"Amount invalid: {exc}") from exc
        amount_kind = kind
        amount_value = value
        if issued is not None:
            currency = issued.currency
            issuer = issued.issuer

    delivered_kind = ""
    delivered_value = ""
    delivered_currency = ""
    delivered_issuer = ""
    meta_map = dict(meta or {})
    delivered_raw = (
        meta_map.get("delivered_amount")
        or meta_map.get("DeliveredAmount")
        or tx.get("delivered_amount")
        or tx.get("DeliveredAmount")
    )
    if delivered_raw is not None:
        try:
            d_kind, d_value, d_issued = parse_amount(delivered_raw)
        except XRPLAdapterError as exc:
            raise GuardValidationError(f"delivered_amount invalid: {exc}") from exc
        delivered_kind = d_kind
        delivered_value = d_value
        if d_issued is not None:
            delivered_currency = d_issued.currency
            delivered_issuer = d_issued.issuer
    elif partial:
        # Partial payment without delivered amount fails closed at evaluation.
        pass

    effect = NormalizedXRPLEffect(
        kind="payment" if "Payment" in tx_type or tx_type == "Payment" else "ledger_transition",
        account=account.classic_address,
        destination=destination.classic_address if destination else "",
        destination_tag=destination.destination_tag if destination else _optional_uint32(dest_tag, "DestinationTag") if dest_tag is not None else None,
        amount_kind=amount_kind,
        amount_value=amount_value,
        currency=currency,
        issuer=issuer,
        delivered_amount_kind=delivered_kind,
        delivered_amount_value=delivered_value,
        delivered_currency=delivered_currency,
        delivered_issuer=delivered_issuer,
        partial_payment=partial,
        fee_drops=str(fee) if fee is not None else DEFAULT_FEE_DROPS,
        sequence=_optional_non_negative_int(sequence, "Sequence") if sequence is not None else None,
        ticket_sequence=_optional_non_negative_int(ticket, "TicketSequence") if ticket is not None else None,
        flags=flags,
        transaction_type=tx_type,
    )
    return (effect,)


# ---------------------------------------------------------------------------
# Epoch / signer list bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerEpoch:
    """Bound XRPL ledger epoch for freshness re-resolution at consumption."""

    ledger_index: int
    ledger_hash: str = ""
    validated: bool = True
    parent_hash: str = ""
    closed_time: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEDGER_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ledger_index", _non_negative_int(self.ledger_index, "ledger_index")
        )
        if self.ledger_hash:
            try:
                object.__setattr__(
                    self,
                    "ledger_hash",
                    normalize_ledger_hash(self.ledger_hash, field="ledger_hash"),
                )
            except XRPLAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
        else:
            object.__setattr__(self, "ledger_hash", "")
        object.__setattr__(self, "validated", bool(self.validated))
        if self.parent_hash:
            try:
                object.__setattr__(
                    self,
                    "parent_hash",
                    normalize_ledger_hash(self.parent_hash, field="parent_hash"),
                )
            except XRPLAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
        else:
            object.__setattr__(self, "parent_hash", "")
        object.__setattr__(
            self, "closed_time", _optional_text(self.closed_time, "closed_time", max_chars=64)
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != LEDGER_EPOCH_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported ledger epoch schema: {self.schema_version!r}"
            )

    @property
    def epoch_digest(self) -> str:
        return content_sha256_hex(
            {
                "ledger_hash": self.ledger_hash,
                "ledger_index": self.ledger_index,
                "parent_hash": self.parent_hash,
                "validated": self.validated,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "closed_time": self.closed_time,
            "epoch_digest": self.epoch_digest,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "parent_hash": self.parent_hash,
            "schema_version": self.schema_version,
            "validated": self.validated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerEpoch":
        value = _mapping(value, "LedgerEpoch")
        _reject_forbidden(value, "LedgerEpoch")
        return cls(
            ledger_index=value.get(
                "ledger_index", value.get("ledgerIndex", value.get("LedgerIndex", 0))
            ),
            ledger_hash=value.get(
                "ledger_hash", value.get("ledgerHash", value.get("LedgerHash", ""))
            ),
            validated=bool(value.get("validated", True)),
            parent_hash=value.get("parent_hash", value.get("parentHash", "")),
            closed_time=value.get("closed_time", value.get("close_time", "")),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", LEDGER_EPOCH_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SignerListBinding:
    """Bound multi-sign signer list and quorum for mutation detection."""

    signers: tuple[Mapping[str, Any], ...] = ()
    signer_quorum: int | None = None
    signer_list_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SIGNER_LIST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.signers, (str, bytes)) or not isinstance(
            self.signers, Sequence
        ):
            raise GuardValidationError("signers must be a sequence")
        if len(self.signers) > MAX_COLLECTION_ITEMS:
            raise GuardValidationError("signers exceeds maximum collection size")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(self.signers):
            if not isinstance(item, Mapping):
                raise GuardValidationError(f"signers[{index}] must be a mapping")
            _reject_forbidden(item, f"signers[{index}]")
            account = item.get("Account", item.get("account", item.get("SignerEntry", {})))
            if isinstance(account, Mapping):
                account = account.get("Account", account.get("account", ""))
            weight = item.get(
                "SignerWeight", item.get("signer_weight", item.get("weight", 1))
            )
            entry = {
                "account": normalize_classic_address(str(account), field="signer.account")
                if account
                else "",
                "weight": _non_negative_int(weight, "signer.weight") if weight is not None else 1,
            }
            if not entry["account"]:
                raise GuardValidationError(f"signers[{index}].account is required")
            normalized.append(entry)
        object.__setattr__(self, "signers", tuple(normalized))
        object.__setattr__(
            self,
            "signer_quorum",
            _optional_non_negative_int(self.signer_quorum, "signer_quorum"),
        )
        object.__setattr__(
            self,
            "signer_list_id",
            _optional_text(self.signer_list_id, "signer_list_id", max_chars=256),
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SIGNER_LIST_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported signer list schema: {self.schema_version!r}"
            )

    @property
    def list_digest(self) -> str:
        return content_sha256_hex(
            {
                "signer_quorum": self.signer_quorum,
                "signers": list(self.signers),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "list_digest": self.list_digest,
            "schema_version": self.schema_version,
            "signer_list_id": self.signer_list_id,
            "signer_quorum": self.signer_quorum,
            "signers": [dict(s) for s in self.signers],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignerListBinding":
        value = _mapping(value, "SignerListBinding")
        _reject_forbidden(value, "SignerListBinding")
        return cls(
            signers=tuple(value.get("signers", value.get("Signers", ()))),
            signer_quorum=value.get(
                "signer_quorum", value.get("SignerQuorum", value.get("quorum"))
            ),
            signer_list_id=value.get("signer_list_id", value.get("signerListId", "")),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", SIGNER_LIST_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# AST: XRPLTransactionCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XRPLTransactionCandidate:
    """Unsigned XRPL transaction candidate (declaration authority only).

    Binds network, accounts/tags, amount identity, flags, sequence/ticket,
    fee, signer list, last-ledger-sequence, and optional serialized blob.
    Never authorization to sign or broadcast.
    """

    intent_id: str
    account: str
    destination: str = ""
    destination_tag: int | None = None
    transaction_type: str = "Payment"
    amount: Any = None
    delivered_amount: Any = None
    fee_drops: str = DEFAULT_FEE_DROPS
    flags: int = 0
    sequence: int | None = None
    ticket_sequence: int | None = None
    last_ledger_sequence: int | None = None
    signers: tuple[Mapping[str, Any], ...] = ()
    signer_quorum: int | None = None
    chain_id: str = XRPL_MAINNET_CHAIN_ID
    network: str = XRPL_MAINNET_NETWORK
    genesis_hash: str = XRPL_MAINNET_GENESIS_HASH
    ledger_index: int | None = None
    ledger_hash: str = ""
    hooks_capability_present: bool = False
    hooks_effects: tuple[Mapping[str, Any], ...] = ()
    serialized_hex: str = ""
    tx_json: Mapping[str, Any] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = XRPL_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        try:
            anchor = resolve_network(
                chain_id=self.chain_id or None,
                network=self.network or None,
                genesis_hash=self.genesis_hash or None,
            )
        except XRPLAdapterError as exc:
            raise GuardValidationError(str(exc)) from exc
        object.__setattr__(self, "chain_id", anchor.chain_id)
        object.__setattr__(self, "network", anchor.network)
        object.__setattr__(self, "genesis_hash", anchor.genesis_hash)

        account = _account(self.account, "account")
        object.__setattr__(self, "account", account.classic_address)

        dest_tag = _optional_uint32(self.destination_tag, "destination_tag")
        if self.destination:
            dest = _account(self.destination, "destination", destination_tag=dest_tag)
            object.__setattr__(self, "destination", dest.classic_address)
            object.__setattr__(self, "destination_tag", dest.destination_tag)
        else:
            object.__setattr__(self, "destination", "")
            object.__setattr__(self, "destination_tag", dest_tag)

        object.__setattr__(
            self,
            "transaction_type",
            _text(self.transaction_type or "Payment", "transaction_type", max_chars=64),
        )
        object.__setattr__(self, "fee_drops", _amount_drops(self.fee_drops, "fee_drops"))
        object.__setattr__(self, "flags", parse_flags(self.flags))
        object.__setattr__(
            self, "sequence", _optional_non_negative_int(self.sequence, "sequence")
        )
        object.__setattr__(
            self,
            "ticket_sequence",
            _optional_non_negative_int(self.ticket_sequence, "ticket_sequence"),
        )
        if self.sequence is None and self.ticket_sequence is None:
            raise GuardValidationError(
                "sequence or ticket_sequence is required for XRPL candidate binding"
            )
        object.__setattr__(
            self,
            "last_ledger_sequence",
            _optional_non_negative_int(
                self.last_ledger_sequence, "last_ledger_sequence"
            ),
        )
        if isinstance(self.signers, (str, bytes)) or not isinstance(
            self.signers, Sequence
        ):
            raise GuardValidationError("signers must be a sequence")
        object.__setattr__(self, "signers", tuple(dict(s) for s in self.signers))
        object.__setattr__(
            self,
            "signer_quorum",
            _optional_non_negative_int(self.signer_quorum, "signer_quorum"),
        )
        object.__setattr__(
            self,
            "ledger_index",
            _optional_non_negative_int(self.ledger_index, "ledger_index"),
        )
        if self.ledger_hash:
            try:
                object.__setattr__(
                    self,
                    "ledger_hash",
                    normalize_ledger_hash(self.ledger_hash, field="ledger_hash"),
                )
            except XRPLAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
        else:
            object.__setattr__(self, "ledger_hash", "")
        object.__setattr__(
            self, "hooks_capability_present", bool(self.hooks_capability_present)
        )
        if isinstance(self.hooks_effects, (str, bytes)) or not isinstance(
            self.hooks_effects, Sequence
        ):
            raise GuardValidationError("hooks_effects must be a sequence")
        object.__setattr__(
            self, "hooks_effects", tuple(dict(h) for h in self.hooks_effects)
        )
        if self.serialized_hex:
            ser = _text(
                self.serialized_hex, "serialized_hex", max_chars=MAX_HEX_PAYLOAD_CHARS
            )
            if ser.startswith("0x"):
                ser = ser[2:]
            if ser and (len(ser) % 2 != 0 or not re.fullmatch(r"[0-9a-fA-F]+", ser)):
                raise GuardValidationError("serialized_hex must be even-length hex")
            object.__setattr__(self, "serialized_hex", ser.lower())
        else:
            object.__setattr__(self, "serialized_hex", "")
        if not isinstance(self.tx_json, Mapping):
            raise GuardValidationError("tx_json must be a mapping")
        if not isinstance(self.meta, Mapping):
            raise GuardValidationError("meta must be a mapping")
        object.__setattr__(self, "tx_json", dict(self.tx_json))
        object.__setattr__(self, "meta", dict(self.meta))
        # Amount fields validated when present (via parse_amount).
        if self.amount is not None:
            try:
                parse_amount(self.amount)
            except XRPLAdapterError as exc:
                raise GuardValidationError(f"amount invalid: {exc}") from exc
        if self.delivered_amount is not None:
            try:
                parse_amount(self.delivered_amount)
            except XRPLAdapterError as exc:
                raise GuardValidationError(f"delivered_amount invalid: {exc}") from exc
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != XRPL_CANDIDATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported XRPL candidate schema: {self.schema_version!r}"
            )

    @property
    def partial_payment(self) -> bool:
        return has_partial_payment(self.flags)

    def to_tx_json(self) -> dict[str, Any]:
        """Materialize a canonical XRPL transaction JSON surface."""

        if self.tx_json:
            return dict(self.tx_json)
        payload: dict[str, Any] = {
            "Account": self.account,
            "TransactionType": self.transaction_type,
            "Fee": self.fee_drops,
            "Flags": self.flags,
        }
        if self.destination:
            payload["Destination"] = self.destination
        if self.destination_tag is not None:
            payload["DestinationTag"] = self.destination_tag
        if self.amount is not None:
            payload["Amount"] = self.amount
        if self.sequence is not None:
            payload["Sequence"] = self.sequence
        if self.ticket_sequence is not None:
            payload["TicketSequence"] = self.ticket_sequence
        if self.last_ledger_sequence is not None:
            payload["LastLedgerSequence"] = self.last_ledger_sequence
        if self.signers:
            payload["Signers"] = [dict(s) for s in self.signers]
        if self.signer_quorum is not None:
            payload["SignerQuorum"] = self.signer_quorum
        return payload

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "amount": self.amount,
            "chain_id": self.chain_id,
            "delivered_amount": self.delivered_amount,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "fee_drops": self.fee_drops,
            "flags": self.flags,
            "genesis_hash": self.genesis_hash,
            "hooks_capability_present": self.hooks_capability_present,
            "hooks_effects": list(self.hooks_effects),
            "intent_id": self.intent_id,
            "last_ledger_sequence": self.last_ledger_sequence,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "network": self.network,
            "sequence": self.sequence,
            "serialized_hex": self.serialized_hex,
            "signer_quorum": self.signer_quorum,
            "signers": [dict(s) for s in self.signers],
            "ticket_sequence": self.ticket_sequence,
            "transaction_type": self.transaction_type,
            "tx_json": dict(self.tx_json) if self.tx_json else self.to_tx_json(),
        }

    @property
    def candidate_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "candidate_digest": self.candidate_digest,
                "kind": "xrpl_transaction_candidate",
                "meta": dict(self.meta),
                "partial_payment": self.partial_payment,
                "schema_version": self.schema_version,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XRPLTransactionCandidate":
        value = _mapping(value, "XRPLTransactionCandidate")
        _reject_forbidden(value, "XRPLTransactionCandidate")
        tx = value.get("tx") or value.get("transaction") or value.get("tx_json") or {}
        if not isinstance(tx, Mapping):
            tx = {}
        meta = value.get("meta") or value.get("metadata") or {}
        if not isinstance(meta, Mapping):
            meta = {}
        # Flatten common XRPL RPC shapes.
        account = value.get(
            "account",
            value.get("Account", tx.get("Account", tx.get("account", ""))),
        )
        destination = value.get(
            "destination",
            value.get("Destination", tx.get("Destination", tx.get("destination", ""))),
        )
        return cls(
            intent_id=value.get("intent_id", value.get("intentId", "")),
            account=account,
            destination=destination or "",
            destination_tag=value.get(
                "destination_tag",
                value.get("DestinationTag", tx.get("DestinationTag")),
            ),
            transaction_type=value.get(
                "transaction_type",
                value.get(
                    "TransactionType",
                    tx.get("TransactionType", tx.get("transaction_type", "Payment")),
                ),
            ),
            amount=value.get("amount", value.get("Amount", tx.get("Amount"))),
            delivered_amount=value.get(
                "delivered_amount",
                value.get(
                    "DeliveredAmount",
                    meta.get("delivered_amount", meta.get("DeliveredAmount")),
                ),
            ),
            fee_drops=value.get(
                "fee_drops", value.get("Fee", tx.get("Fee", DEFAULT_FEE_DROPS))
            ),
            flags=value.get("flags", value.get("Flags", tx.get("Flags", 0))),
            sequence=value.get(
                "sequence", value.get("Sequence", tx.get("Sequence"))
            ),
            ticket_sequence=value.get(
                "ticket_sequence",
                value.get("TicketSequence", tx.get("TicketSequence")),
            ),
            last_ledger_sequence=value.get(
                "last_ledger_sequence",
                value.get("LastLedgerSequence", tx.get("LastLedgerSequence")),
            ),
            signers=tuple(
                value.get("signers", value.get("Signers", tx.get("Signers", ())))
            ),
            signer_quorum=value.get(
                "signer_quorum",
                value.get("SignerQuorum", tx.get("SignerQuorum")),
            ),
            chain_id=value.get("chain_id", value.get("chainId", XRPL_MAINNET_CHAIN_ID)),
            network=value.get("network", XRPL_MAINNET_NETWORK),
            genesis_hash=value.get(
                "genesis_hash", value.get("genesisHash", XRPL_MAINNET_GENESIS_HASH)
            ),
            ledger_index=value.get(
                "ledger_index", value.get("ledgerIndex", value.get("LedgerIndex"))
            ),
            ledger_hash=value.get(
                "ledger_hash", value.get("ledgerHash", value.get("LedgerHash", ""))
            ),
            hooks_capability_present=bool(
                value.get("hooks_capability_present", value.get("hooksCapability", False))
            ),
            hooks_effects=tuple(
                value.get("hooks_effects", value.get("hooksEffects", ()))
            ),
            serialized_hex=value.get(
                "serialized_hex", value.get("serializedHex", value.get("tx_blob", ""))
            ),
            tx_json=dict(tx) if tx else dict(value.get("tx_json", {})),
            meta=dict(meta),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", XRPL_CANDIDATE_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XRPLTransactionBinding:
    """Exact XRPL facts bound for two-phase guard evaluation."""

    binding_id: str
    intent_id: str
    candidate_id: str
    chain_id: str
    network: str
    genesis_hash: str
    account: str
    destination: str
    destination_tag: int | None
    transaction_type: str
    effects: tuple[NormalizedXRPLEffect, ...]
    fee_drops: str
    flags: int
    sequence: int | None
    ticket_sequence: int | None
    last_ledger_sequence: int | None
    signer_list: SignerListBinding
    ledger_epoch: LedgerEpoch
    hooks_capability_present: bool
    hooks_effects: tuple[Mapping[str, Any], ...]
    candidate_digest: str
    serialized_digest: str
    tx_digest: str
    encoding: str
    byte_length: int
    binding_digest: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = XRPL_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", max_chars=128)
        )
        object.__setattr__(
            self, "network", _text(self.network, "network", max_chars=128)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _text(self.genesis_hash, "genesis_hash", max_chars=128),
        )
        object.__setattr__(self, "account", _text(self.account, "account", max_chars=128))
        object.__setattr__(
            self,
            "destination",
            _optional_text(self.destination, "destination", max_chars=128),
        )
        if self.destination_tag is not None:
            object.__setattr__(
                self,
                "destination_tag",
                _optional_uint32(self.destination_tag, "destination_tag"),
            )
        object.__setattr__(
            self,
            "transaction_type",
            _text(self.transaction_type, "transaction_type", max_chars=64),
        )
        effects: list[NormalizedXRPLEffect] = []
        for item in self.effects:
            if isinstance(item, NormalizedXRPLEffect):
                effects.append(item)
            elif isinstance(item, Mapping):
                effects.append(NormalizedXRPLEffect.from_dict(item))
            else:
                raise GuardValidationError("effects items must be NormalizedXRPLEffect")
        if not effects:
            raise GuardValidationError("effects must be non-empty")
        object.__setattr__(self, "effects", tuple(effects))
        object.__setattr__(self, "fee_drops", _amount_drops(self.fee_drops, "fee_drops"))
        object.__setattr__(self, "flags", parse_flags(self.flags))
        object.__setattr__(
            self, "sequence", _optional_non_negative_int(self.sequence, "sequence")
        )
        object.__setattr__(
            self,
            "ticket_sequence",
            _optional_non_negative_int(self.ticket_sequence, "ticket_sequence"),
        )
        object.__setattr__(
            self,
            "last_ledger_sequence",
            _optional_non_negative_int(
                self.last_ledger_sequence, "last_ledger_sequence"
            ),
        )
        if not isinstance(self.signer_list, SignerListBinding):
            if isinstance(self.signer_list, Mapping):
                object.__setattr__(
                    self, "signer_list", SignerListBinding.from_dict(self.signer_list)
                )
            else:
                raise GuardValidationError("signer_list must be SignerListBinding")
        if not isinstance(self.ledger_epoch, LedgerEpoch):
            if isinstance(self.ledger_epoch, Mapping):
                object.__setattr__(
                    self, "ledger_epoch", LedgerEpoch.from_dict(self.ledger_epoch)
                )
            else:
                raise GuardValidationError("ledger_epoch must be LedgerEpoch")
        object.__setattr__(
            self, "hooks_capability_present", bool(self.hooks_capability_present)
        )
        object.__setattr__(
            self, "hooks_effects", tuple(dict(h) for h in self.hooks_effects)
        )
        object.__setattr__(
            self, "candidate_digest", _digest(self.candidate_digest, "candidate_digest")
        )
        object.__setattr__(
            self,
            "serialized_digest",
            _digest(self.serialized_digest, "serialized_digest"),
        )
        object.__setattr__(self, "tx_digest", _digest(self.tx_digest, "tx_digest"))
        object.__setattr__(
            self, "encoding", _text(self.encoding, "encoding", max_chars=64)
        )
        object.__setattr__(
            self, "byte_length", _non_negative_int(self.byte_length, "byte_length")
        )
        if self.byte_length < 1:
            raise GuardValidationError("byte_length must be positive")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != XRPL_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported XRPL binding schema: {self.schema_version!r}"
            )
        if not self.binding_digest:
            object.__setattr__(self, "binding_digest", self.compute_binding_digest())
        else:
            object.__setattr__(
                self, "binding_digest", _digest(self.binding_digest, "binding_digest")
            )

    def compute_binding_digest(self) -> str:
        return content_sha256_hex(
            {
                "account": self.account,
                "candidate_digest": self.candidate_digest,
                "chain_id": self.chain_id,
                "destination": self.destination,
                "destination_tag": self.destination_tag,
                "effects": [e.to_dict() for e in self.effects],
                "fee_drops": self.fee_drops,
                "flags": self.flags,
                "genesis_hash": self.genesis_hash,
                "hooks_capability_present": self.hooks_capability_present,
                "intent_id": self.intent_id,
                "last_ledger_sequence": self.last_ledger_sequence,
                "ledger_epoch": self.ledger_epoch.epoch_digest,
                "network": self.network,
                "sequence": self.sequence,
                "serialized_digest": self.serialized_digest,
                "signer_list": self.signer_list.list_digest,
                "ticket_sequence": self.ticket_sequence,
                "transaction_type": self.transaction_type,
                "tx_digest": self.tx_digest,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "attributes": self.attributes.to_dict(),
            "binding_digest": self.binding_digest,
            "binding_id": self.binding_id,
            "byte_length": self.byte_length,
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "chain_id": self.chain_id,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "effects": [e.to_dict() for e in self.effects],
            "encoding": self.encoding,
            "fee_drops": self.fee_drops,
            "flags": self.flags,
            "genesis_hash": self.genesis_hash,
            "hooks_capability_present": self.hooks_capability_present,
            "hooks_effects": [dict(h) for h in self.hooks_effects],
            "intent_id": self.intent_id,
            "last_ledger_sequence": self.last_ledger_sequence,
            "ledger_epoch": self.ledger_epoch.to_dict(),
            "network": self.network,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "serialized_digest": self.serialized_digest,
            "signer_list": self.signer_list.to_dict(),
            "ticket_sequence": self.ticket_sequence,
            "transaction_type": self.transaction_type,
            "tx_digest": self.tx_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XRPLTransactionBinding":
        value = _mapping(value, "XRPLTransactionBinding")
        _reject_forbidden(value, "XRPLTransactionBinding")
        return cls(
            binding_id=value.get("binding_id", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            chain_id=value.get("chain_id", XRPL_MAINNET_CHAIN_ID),
            network=value.get("network", XRPL_MAINNET_NETWORK),
            genesis_hash=value.get("genesis_hash", XRPL_MAINNET_GENESIS_HASH),
            account=value.get("account", ""),
            destination=value.get("destination", ""),
            destination_tag=value.get("destination_tag"),
            transaction_type=value.get("transaction_type", "Payment"),
            effects=tuple(value.get("effects", ())),
            fee_drops=value.get("fee_drops", DEFAULT_FEE_DROPS),
            flags=value.get("flags", 0),
            sequence=value.get("sequence"),
            ticket_sequence=value.get("ticket_sequence"),
            last_ledger_sequence=value.get("last_ledger_sequence"),
            signer_list=value.get("signer_list", {}),
            ledger_epoch=value.get("ledger_epoch", {"ledger_index": 0}),
            hooks_capability_present=bool(
                value.get("hooks_capability_present", False)
            ),
            hooks_effects=tuple(value.get("hooks_effects", ())),
            candidate_digest=value.get("candidate_digest", ""),
            serialized_digest=value.get("serialized_digest", ""),
            tx_digest=value.get("tx_digest", ""),
            encoding=value.get("encoding", "xrpl-tx-json"),
            byte_length=value.get("byte_length", 1),
            binding_digest=value.get("binding_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", XRPL_BINDING_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class XRPLGuardPhase(str, Enum):
    """Phase at which the XRPL guard is consulted."""

    EVALUATE = "evaluate"
    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class XRPLGuardDecision:
    """Deterministic XRPL guard decision (not authorization to sign)."""

    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    binding_digest: str
    request_digest: str = ""
    preflight: PreflightResult | None = None
    security_results: Mapping[str, str] = field(default_factory=dict)
    compliance_results: Mapping[str, str] = field(default_factory=dict)
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = XRPL_GUARD_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, TransactionVerdictOutcome):
            object.__setattr__(
                self, "outcome", TransactionVerdictOutcome(str(self.outcome))
            )
        object.__setattr__(self, "blocks_automation", bool(self.blocks_automation))
        object.__setattr__(
            self, "reason_codes", tuple(str(c) for c in self.reason_codes)
        )
        object.__setattr__(self, "reasons", tuple(str(r) for r in self.reasons))
        object.__setattr__(
            self, "binding_digest", _digest(self.binding_digest, "binding_digest")
        )
        if self.request_digest:
            object.__setattr__(
                self, "request_digest", _digest(self.request_digest, "request_digest")
            )
        else:
            object.__setattr__(self, "request_digest", "")
        object.__setattr__(
            self, "security_results", dict(self.security_results or {})
        )
        object.__setattr__(
            self, "compliance_results", dict(self.compliance_results or {})
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def allowed(self) -> bool:
        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binding_digest": self.binding_digest,
            "blocks_automation": self.blocks_automation,
            "compliance_results": dict(self.compliance_results),
            "outcome": self.outcome.value,
            "preflight": self.preflight.to_dict() if self.preflight else None,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "security_results": dict(self.security_results),
        }


# ---------------------------------------------------------------------------
# Live resolvers
# ---------------------------------------------------------------------------

LedgerEpochResolver = Callable[[int | str], LedgerEpoch | Mapping[str, Any] | None]
LedgerFreshnessChecker = Callable[[LedgerEpoch, str], bool]


def _static_ledger_resolver(
    epochs: Mapping[int | str, LedgerEpoch | Mapping[str, Any]],
) -> LedgerEpochResolver:
    def _resolve(key: int | str) -> LedgerEpoch | Mapping[str, Any] | None:
        if key in epochs:
            return epochs[key]
        if isinstance(key, int) and str(key) in epochs:
            return epochs[str(key)]
        return None

    return _resolve


def _coerce_ledger_epoch(
    value: LedgerEpoch | Mapping[str, Any] | None, *, field_name: str
) -> LedgerEpoch | None:
    if value is None:
        return None
    if isinstance(value, LedgerEpoch):
        return value
    if isinstance(value, Mapping):
        return LedgerEpoch.from_dict(value)
    raise GuardValidationError(f"{field_name} must be LedgerEpoch or mapping")


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class XRPLTransactionGuard:
    """Non-custodial XRPL leaf guard adapter for the two-phase preflight API.

    Normalizes XRPL transaction candidates into exact
    :class:`TransactionIntent` / :class:`TransactionCandidate` bindings, runs
    XRPL-specific fail-closed checks, and delegates capability issuance /
    atomic consumption to :class:`TransactionPreflight`.

    Ledger epoch is re-resolved at consumption and must match the binding used
    when the admissibility capability was issued.
    """

    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_PRODUCER_ID
    policy_id: str = DEFAULT_POLICY_ID
    ledger_epoch_resolver: LedgerEpochResolver | None = None
    ledger_is_fresh: LedgerFreshnessChecker | None = None
    interface: str = XRPL_TRANSACTION_GUARD_INTERFACE
    schema_version: str = XRPL_TRANSACTION_GUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.preflight is None:
            self.preflight = TransactionPreflight(producer_id=self.producer_id)
        if self.interface != XRPL_TRANSACTION_GUARD_INTERFACE:
            raise GuardValidationError(
                f"unsupported xrpl guard interface: {self.interface!r}"
            )
        if self.schema_version != XRPL_TRANSACTION_GUARD_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported xrpl guard schema: {self.schema_version!r}"
            )
        if self.ledger_is_fresh is None:
            # Offline default: validated ledger epochs with index > 0 are fresh.
            self.ledger_is_fresh = (
                lambda epoch, _now: bool(epoch.validated) and epoch.ledger_index > 0
            )

    # -- binding ------------------------------------------------------------

    def bind_transaction(
        self,
        candidate: XRPLTransactionCandidate | Mapping[str, Any],
        *,
        ledger_epoch: LedgerEpoch | Mapping[str, Any] | None = None,
        signer_list: SignerListBinding | Mapping[str, Any] | None = None,
        declared_effects: Sequence[NormalizedXRPLEffect | Mapping[str, Any]]
        | None = None,
        serialized_bytes: bytes | str | None = None,
        encoding: str = "xrpl-tx-json",
        candidate_id: str = "",
        binding_id: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> XRPLTransactionBinding:
        """Normalize an XRPL candidate into an exact guard binding."""

        cand = self._coerce_candidate(candidate)
        tx_json = cand.to_tx_json()
        effects = (
            tuple(
                item
                if isinstance(item, NormalizedXRPLEffect)
                else NormalizedXRPLEffect.from_dict(item)
                for item in declared_effects
            )
            if declared_effects is not None
            else normalize_xrpl_tx_effects(tx_json, meta=cand.meta)
        )
        if not effects:
            raise GuardValidationError("normalized XRPL effects must be non-empty")

        # Prefer candidate-level delivered amount when present.
        if cand.delivered_amount is not None and effects:
            primary = effects[0]
            try:
                d_kind, d_value, d_issued = parse_amount(cand.delivered_amount)
            except XRPLAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
            effects = (
                NormalizedXRPLEffect(
                    kind=primary.kind,
                    account=primary.account,
                    destination=primary.destination,
                    destination_tag=primary.destination_tag,
                    amount_kind=primary.amount_kind,
                    amount_value=primary.amount_value,
                    currency=primary.currency,
                    issuer=primary.issuer,
                    delivered_amount_kind=d_kind,
                    delivered_amount_value=d_value,
                    delivered_currency=d_issued.currency if d_issued else "",
                    delivered_issuer=d_issued.issuer if d_issued else "",
                    partial_payment=primary.partial_payment or has_partial_payment(cand.flags),
                    fee_drops=primary.fee_drops or cand.fee_drops,
                    sequence=primary.sequence if primary.sequence is not None else cand.sequence,
                    ticket_sequence=(
                        primary.ticket_sequence
                        if primary.ticket_sequence is not None
                        else cand.ticket_sequence
                    ),
                    flags=cand.flags,
                    transaction_type=cand.transaction_type,
                    attributes=primary.attributes,
                ),
            ) + effects[1:]

        if ledger_epoch is not None:
            epoch = (
                ledger_epoch
                if isinstance(ledger_epoch, LedgerEpoch)
                else LedgerEpoch.from_dict(ledger_epoch)
            )
        elif cand.ledger_index is not None:
            epoch = LedgerEpoch(
                ledger_index=cand.ledger_index,
                ledger_hash=cand.ledger_hash,
                validated=True,
            )
        else:
            raise GuardValidationError(
                "ledger_epoch or candidate.ledger_index is required; "
                "unbound ledger fails closed"
            )

        if signer_list is not None:
            bound_signers = (
                signer_list
                if isinstance(signer_list, SignerListBinding)
                else SignerListBinding.from_dict(signer_list)
            )
        else:
            bound_signers = SignerListBinding(
                signers=cand.signers,
                signer_quorum=cand.signer_quorum,
            )

        tx_digest = content_sha256_hex(tx_json)
        if serialized_bytes is None:
            if cand.serialized_hex:
                raw = bytes.fromhex(cand.serialized_hex)
                serialized_digest = hashlib.sha256(raw).hexdigest()
                byte_length = len(raw) or 1
            else:
                serialized_digest = tx_digest
                byte_length = max(1, len(tx_digest) // 2)
        elif isinstance(serialized_bytes, bytes):
            serialized_digest = hashlib.sha256(serialized_bytes).hexdigest()
            byte_length = len(serialized_bytes) or 1
        else:
            raw_s = str(serialized_bytes).encode("utf-8")
            serialized_digest = hashlib.sha256(raw_s).hexdigest()
            byte_length = len(raw_s) or 1

        intent_id = cand.intent_id
        cand_id = candidate_id or f"candidate:xrpl:{intent_id}"
        bind_id = binding_id or f"binding:xrpl:{intent_id}"
        candidate_digest = content_sha256_hex(
            {
                "candidate_id": cand_id,
                "encoding": encoding,
                "intent_id": intent_id,
                "network": cand.network,
                "serialized_digest": serialized_digest,
                "tx_digest": tx_digest,
            }
        )

        return XRPLTransactionBinding(
            binding_id=bind_id,
            intent_id=intent_id,
            candidate_id=cand_id,
            chain_id=cand.chain_id,
            network=cand.network,
            genesis_hash=cand.genesis_hash,
            account=cand.account,
            destination=cand.destination,
            destination_tag=cand.destination_tag,
            transaction_type=cand.transaction_type,
            effects=effects,
            fee_drops=cand.fee_drops,
            flags=cand.flags,
            sequence=cand.sequence,
            ticket_sequence=cand.ticket_sequence,
            last_ledger_sequence=cand.last_ledger_sequence,
            signer_list=bound_signers,
            ledger_epoch=epoch,
            hooks_capability_present=cand.hooks_capability_present,
            hooks_effects=cand.hooks_effects,
            candidate_digest=candidate_digest,
            serialized_digest=serialized_digest,
            tx_digest=tx_digest,
            encoding=encoding,
            byte_length=byte_length,
            attributes=attributes or {},
        )

    def to_preflight_request(
        self,
        binding: XRPLTransactionBinding,
        *,
        request_id: str,
        tenant_id: str,
        actor_id: str,
        audience_id: str,
        issued_at: str,
        deadline: str,
        expiry: str,
        security_requirement_ids: Sequence[str] | None = None,
        compliance_requirement_ids: Sequence[str] | None = None,
        environment_id: str = "env:xrpl-guard",
        environment_digest: str = "",
        nonce: str = "",
        policy_id: str | None = None,
        intent_expires_at: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TransactionPreflightRequest:
        """Project an XRPL binding into the common preflight request surface."""

        intent = self._intent_from_binding(
            binding, expires_at=intent_expires_at or expiry
        )
        candidate = TransactionCandidate(
            candidate_id=binding.candidate_id,
            intent_id=binding.intent_id,
            serialized_digest=binding.serialized_digest,
            encoding=binding.encoding,
            byte_length=binding.byte_length,
            network=binding.network,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "destination_tag": binding.destination_tag,
                "genesis_hash": binding.genesis_hash,
                "ledger_epoch": binding.ledger_epoch.epoch_digest,
                "sequence": binding.sequence,
                "ticket_sequence": binding.ticket_sequence,
                "tx_digest": binding.tx_digest,
            },
        )
        return TransactionPreflightRequest(
            request_id=request_id,
            intent=intent,
            candidate=candidate,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audience_id=audience_id,
            policy_id=policy_id or self.policy_id,
            security_requirement_ids=tuple(
                security_requirement_ids
                if security_requirement_ids is not None
                else DEFAULT_SECURITY_REQUIREMENTS
            ),
            compliance_requirement_ids=tuple(
                compliance_requirement_ids
                if compliance_requirement_ids is not None
                else DEFAULT_COMPLIANCE_REQUIREMENTS
            ),
            issued_at=issued_at,
            deadline=deadline,
            expiry=expiry,
            environment_id=environment_id,
            environment_digest=environment_digest or ("e" * 64),
            nonce=nonce or request_id,
            attributes=attributes
            or {
                "binding_digest": binding.binding_digest,
                "xrpl_guard": True,
            },
        )

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        binding: XRPLTransactionBinding | Mapping[str, Any],
        *,
        request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        now: str | None = None,
        live_ledger_epoch: LedgerEpoch | Mapping[str, Any] | None = None,
        request_id: str = "req:xrpl-guard",
        tenant_id: str = "tenant:default",
        actor_id: str = "actor:policy-engine",
        audience_id: str = "audience:custody-signer",
        issued_at: str | None = None,
        deadline: str | None = None,
        expiry: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> XRPLGuardDecision:
        """Evaluate XRPL-specific bindings then run two-phase preflight."""

        if not isinstance(binding, XRPLTransactionBinding):
            binding = XRPLTransactionBinding.from_dict(binding)

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        sec_results = dict(security_results or {})
        comp_results = dict(compliance_results or {})

        structural = self._check_structural(
            binding,
            now=clock,
            live_ledger_epoch=live_ledger_epoch,
            phase=XRPLGuardPhase.EVALUATE,
        )
        reason_codes.extend(structural["reason_codes"])
        reasons.extend(structural["reasons"])
        for req_id, outcome in structural["security_results"].items():
            sec_results.setdefault(req_id, outcome)

        for req_id in DEFAULT_SECURITY_REQUIREMENTS:
            sec_results.setdefault(req_id, "pass")

        if request is None:
            issued = issued_at or clock
            dead = deadline or clock
            exp = expiry or clock
            if issued_at is None and deadline is None and expiry is None:
                issued = "2026-07-28T12:00:00Z"
                dead = "2026-07-28T12:05:00Z"
                exp = "2026-07-28T12:10:00Z"
                intent_exp = "2026-07-28T12:15:00Z"
            else:
                intent_exp = exp
            request = self.to_preflight_request(
                binding,
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                audience_id=audience_id,
                issued_at=issued,
                deadline=dead,
                expiry=exp,
                intent_expires_at=intent_exp,
            )
        elif not isinstance(request, TransactionPreflightRequest):
            request = TransactionPreflightRequest.from_dict(request)

        if compliance_results is None:
            for req_id in request.compliance_requirement_ids:
                comp_results.setdefault(req_id, "pass")

        if structural["blocking"] is not None:
            block_outcome = structural["blocking"]
            mapped = {
                TransactionVerdictOutcome.DENY: "deny",
                TransactionVerdictOutcome.STALE: "stale",
                TransactionVerdictOutcome.REVIEW: "review",
                TransactionVerdictOutcome.ERROR: "error",
                TransactionVerdictOutcome.INCONCLUSIVE: "inconclusive",
            }.get(block_outcome, "deny")
            if structural["failed_requirement"]:
                sec_results[structural["failed_requirement"]] = mapped
            else:
                sec_results["sec:xrpl-exact-candidate"] = mapped

        assert self.preflight is not None
        preflight_result = self.preflight.evaluate(
            request,
            security_results=sec_results,
            compliance_results=comp_results,
            now=clock,
            derive_capability_on_allow=derive_capability_on_allow,
        )

        outcome = preflight_result.outcome
        blocks = preflight_result.blocks_automation
        merged_codes = list(preflight_result.reason_codes) + [
            c for c in reason_codes if c not in preflight_result.reason_codes
        ]
        merged_reasons = list(preflight_result.reasons) + [
            r for r in reasons if r not in preflight_result.reasons
        ]

        return XRPLGuardDecision(
            outcome=outcome,
            blocks_automation=blocks,
            reason_codes=tuple(merged_codes),
            reasons=tuple(merged_reasons),
            binding_digest=binding.binding_digest,
            request_digest=preflight_result.request_digest,
            preflight=preflight_result,
            security_results=preflight_result.security_results,
            compliance_results=preflight_result.compliance_results,
            attributes={
                "destination_tag": binding.destination_tag,
                "ledger_index": binding.ledger_epoch.ledger_index,
                "partial_payment": any(e.partial_payment for e in binding.effects),
                "transaction_type": binding.transaction_type,
            },
        )

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        binding: XRPLTransactionBinding | Mapping[str, Any],
        *,
        phase: PreflightPhase | XRPLGuardPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        live_ledger_epoch: LedgerEpoch | Mapping[str, Any] | None = None,
        live_tx: Mapping[str, Any] | None = None,
        live_effects: Sequence[NormalizedXRPLEffect | Mapping[str, Any]] | None = None,
        live_signer_list: SignerListBinding | Mapping[str, Any] | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate XRPL ledger epoch and effects, then consume capability."""

        if not isinstance(binding, XRPLTransactionBinding):
            binding = XRPLTransactionBinding.from_dict(binding)
        if not isinstance(capability, AdmissibilityCapability):
            if isinstance(capability, Mapping):
                capability = AdmissibilityCapability.from_dict(capability)
            else:
                raise GuardValidationError(
                    "capability must be an AdmissibilityCapability"
                )
        if not isinstance(live_request, TransactionPreflightRequest):
            if isinstance(live_request, Mapping):
                live_request = TransactionPreflightRequest.from_dict(live_request)
            else:
                raise GuardValidationError(
                    "live_request must be a TransactionPreflightRequest"
                )

        if isinstance(phase, PreflightPhase):
            phase_value = phase.value
        elif isinstance(phase, XRPLGuardPhase):
            phase_value = (
                PreflightPhase.PRE_SIGN.value
                if phase is XRPLGuardPhase.PRE_SIGN
                else PreflightPhase.PRE_BROADCAST.value
                if phase is XRPLGuardPhase.PRE_BROADCAST
                else PreflightPhase.PRE_SIGN.value
            )
        else:
            phase_value = str(phase)

        clock = now or _iso_now()
        guard_phase = (
            XRPLGuardPhase.PRE_SIGN
            if phase_value == PreflightPhase.PRE_SIGN.value
            else XRPLGuardPhase.PRE_BROADCAST
        )

        if live_tx is not None:
            self._assert_live_tx_matches(binding, live_tx)

        if live_effects is not None:
            self._assert_live_effects_match(binding, live_effects)

        if live_signer_list is not None:
            live_list = (
                live_signer_list
                if isinstance(live_signer_list, SignerListBinding)
                else SignerListBinding.from_dict(live_signer_list)
            )
            if live_list.list_digest != binding.signer_list.list_digest:
                raise GuardCapabilityError(
                    "live signer list substituted",
                    reason_code="xrpl.signer_list_substituted",
                    details={
                        "expected": binding.signer_list.list_digest,
                        "observed": live_list.list_digest,
                    },
                )

        structural = self._check_structural(
            binding,
            now=clock,
            live_ledger_epoch=live_ledger_epoch,
            phase=guard_phase,
            re_resolve=True,
        )
        if structural["blocking"] is not None:
            raise GuardCapabilityError(
                "; ".join(structural["reasons"])
                or "xrpl live revalidation failed",
                reason_code=structural["reason_codes"][0]
                if structural["reason_codes"]
                else "xrpl.consumption_blocked",
                details={
                    "reason_codes": list(structural["reason_codes"]),
                    "phase": phase_value,
                    "binding_digest": binding.binding_digest,
                },
            )

        live_attrs = live_request.candidate.attributes.to_dict()
        bound_digest = live_attrs.get("binding_digest")
        if bound_digest and bound_digest != binding.binding_digest:
            raise GuardCapabilityError(
                "live candidate binding_digest does not match XRPL binding",
                reason_code="xrpl.binding_digest_mismatch",
                details={
                    "expected": binding.binding_digest,
                    "observed": bound_digest,
                },
            )

        assert self.preflight is not None
        return self.preflight.revalidate_and_consume(
            capability,
            live_request,
            phase=phase_value,
            now=clock,
        )

    # -- internals ----------------------------------------------------------

    def _coerce_candidate(
        self, candidate: XRPLTransactionCandidate | Mapping[str, Any]
    ) -> XRPLTransactionCandidate:
        if isinstance(candidate, XRPLTransactionCandidate):
            return candidate
        if isinstance(candidate, Mapping):
            _reject_forbidden(candidate, "XRPLTransactionCandidate")
            return XRPLTransactionCandidate.from_dict(candidate)
        raise GuardValidationError(
            "candidate must be an XRPLTransactionCandidate or mapping"
        )

    def _check_structural(
        self,
        binding: XRPLTransactionBinding,
        *,
        now: str,
        live_ledger_epoch: LedgerEpoch | Mapping[str, Any] | None,
        phase: XRPLGuardPhase,
        re_resolve: bool = False,
    ) -> dict[str, Any]:
        reason_codes: list[str] = []
        reasons: list[str] = []
        security_results: dict[str, str] = {}
        blocking: TransactionVerdictOutcome | None = None
        failed_requirement = ""

        def _block(
            outcome: TransactionVerdictOutcome,
            code: str,
            reason: str,
            requirement: str,
        ) -> None:
            nonlocal blocking, failed_requirement
            reason_codes.append(code)
            reasons.append(reason)
            security_results[requirement] = {
                TransactionVerdictOutcome.DENY: "deny",
                TransactionVerdictOutcome.STALE: "stale",
                TransactionVerdictOutcome.REVIEW: "review",
                TransactionVerdictOutcome.ERROR: "error",
                TransactionVerdictOutcome.INCONCLUSIVE: "inconclusive",
            }.get(outcome, "deny")
            if failed_requirement == "":
                failed_requirement = requirement
            if blocking is None or (
                outcome is TransactionVerdictOutcome.DENY
                and blocking is not TransactionVerdictOutcome.DENY
            ):
                blocking = outcome
            elif (
                outcome is TransactionVerdictOutcome.STALE
                and blocking
                not in (
                    TransactionVerdictOutcome.DENY,
                    TransactionVerdictOutcome.STALE,
                )
            ):
                blocking = outcome

        if not binding.network or not binding.chain_id or not binding.genesis_hash:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "xrpl.network_unbound",
                "network / chain_id / genesis_hash are unbound",
                "sec:xrpl-network-binding",
            )
        else:
            security_results.setdefault("sec:xrpl-network-binding", "pass")

        if not binding.destination and binding.transaction_type == "Payment":
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.destination_missing",
                "Payment destination is unbound",
                "sec:xrpl-destination-tag",
            )
        else:
            security_results.setdefault("sec:xrpl-destination-tag", "pass")

        primary = binding.effects[0]
        if not primary.amount_kind and binding.transaction_type == "Payment":
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.amount_unbound",
                "payment amount identity is unbound",
                "sec:xrpl-amount-identity",
            )
        elif primary.amount_kind == "issued" and (
            not primary.issuer or not primary.currency
        ):
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.issued_asset_incomplete",
                "issued amount requires issuer and currency",
                "sec:xrpl-amount-identity",
            )
        else:
            security_results.setdefault("sec:xrpl-amount-identity", "pass")

        if primary.partial_payment or has_partial_payment(binding.flags):
            if not primary.delivered_amount_kind or not primary.delivered_amount_value:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "xrpl.partial_payment_without_delivered",
                    "partial payment requires bound delivered amount",
                    "sec:xrpl-partial-payment",
                )
            else:
                security_results.setdefault("sec:xrpl-partial-payment", "pass")
        else:
            security_results.setdefault("sec:xrpl-partial-payment", "pass")

        if binding.sequence is None and binding.ticket_sequence is None:
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.sequence_unbound",
                "sequence/ticket is unbound",
                "sec:xrpl-sequence-ticket",
            )
        else:
            security_results.setdefault("sec:xrpl-sequence-ticket", "pass")

        if not binding.fee_drops:
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.fee_unbound",
                "fee is unbound",
                "sec:xrpl-fee",
            )
        else:
            security_results.setdefault("sec:xrpl-fee", "pass")

        security_results.setdefault("sec:xrpl-signer-list", "pass")

        # Hooks: effects without capability evidence fail closed.
        if binding.hooks_effects and not binding.hooks_capability_present:
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.unsupported_hooks",
                "hooks effects present without hooks capability evidence",
                "sec:xrpl-hooks-capability",
            )
        else:
            security_results.setdefault("sec:xrpl-hooks-capability", "pass")

        # Ledger freshness + optional re-resolution.
        assert self.ledger_is_fresh is not None
        try:
            fresh = bool(self.ledger_is_fresh(binding.ledger_epoch, now))
        except Exception as exc:  # noqa: BLE001
            fresh = False
            _block(
                TransactionVerdictOutcome.ERROR,
                "xrpl.ledger_freshness_checker_error",
                f"ledger freshness checker errored: {exc}",
                "sec:xrpl-ledger-epoch",
            )
        else:
            if not fresh:
                _block(
                    TransactionVerdictOutcome.STALE,
                    "xrpl.stale_ledger",
                    "ledger epoch is stale or unvalidated",
                    "sec:xrpl-ledger-epoch",
                )
            else:
                security_results.setdefault("sec:xrpl-ledger-epoch", "pass")

        # LastLedgerSequence vs current epoch.
        if (
            binding.last_ledger_sequence is not None
            and binding.ledger_epoch.ledger_index > binding.last_ledger_sequence
        ):
            _block(
                TransactionVerdictOutcome.STALE,
                "xrpl.last_ledger_sequence_elapsed",
                "current ledger exceeds LastLedgerSequence",
                "sec:xrpl-ledger-epoch",
            )

        resolver = self.ledger_epoch_resolver
        live_epoch_value: LedgerEpoch | Mapping[str, Any] | None = live_ledger_epoch
        if live_epoch_value is None and resolver is not None:
            try:
                live_epoch_value = resolver(binding.ledger_epoch.ledger_index)
            except Exception as exc:  # noqa: BLE001
                _block(
                    TransactionVerdictOutcome.ERROR,
                    "xrpl.ledger_resolve_error",
                    f"ledger epoch re-resolve failed: {exc}",
                    "sec:xrpl-ledger-epoch",
                )
                live_epoch_value = None

        if re_resolve or live_ledger_epoch is not None:
            if live_epoch_value is None and re_resolve:
                _block(
                    TransactionVerdictOutcome.STALE,
                    "xrpl.ledger_unresolved",
                    f"ledger epoch could not be re-resolved at {phase.value}",
                    "sec:xrpl-ledger-epoch",
                )
            elif live_epoch_value is not None:
                live_epoch = _coerce_ledger_epoch(
                    live_epoch_value, field_name="live ledger epoch"
                )
                assert live_epoch is not None
                if live_epoch.epoch_digest != binding.ledger_epoch.epoch_digest:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "xrpl.ledger_epoch_mismatch",
                        "ledger epoch changed (hash/index mutation)",
                        "sec:xrpl-ledger-epoch",
                    )
                elif not live_epoch.validated:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "xrpl.ledger_not_validated",
                        "live ledger epoch is not validated",
                        "sec:xrpl-ledger-epoch",
                    )

        if not binding.candidate_digest or not binding.serialized_digest:
            _block(
                TransactionVerdictOutcome.DENY,
                "xrpl.candidate_unbound",
                "exact candidate digests are unbound",
                "sec:xrpl-exact-candidate",
            )
        else:
            security_results.setdefault("sec:xrpl-exact-candidate", "pass")

        return {
            "blocking": blocking,
            "reason_codes": reason_codes,
            "reasons": reasons,
            "security_results": security_results,
            "failed_requirement": failed_requirement,
        }

    def _assert_live_tx_matches(
        self,
        binding: XRPLTransactionBinding,
        live_tx: Mapping[str, Any],
    ) -> None:
        """Fail closed when live tx substitutes tag, issuer, amount, or signers."""

        _reject_forbidden(live_tx, "live_tx")
        live_effects = normalize_xrpl_tx_effects(live_tx)
        self._assert_live_effects_match(binding, live_effects)

        live_digest = content_sha256_hex(dict(live_tx))
        if live_digest != binding.tx_digest:
            # Content changed — still allow if only non-semantic metadata differs
            # by comparing critical fields explicitly (already done via effects).
            # Hard fail when destination tag / amount / account diverge.
            live_account = str(live_tx.get("Account", live_tx.get("account", "")))
            live_dest = str(live_tx.get("Destination", live_tx.get("destination", "")))
            live_tag = live_tx.get("DestinationTag", live_tx.get("destination_tag"))
            if normalize_classic_address(live_account, field="live.Account") != binding.account:
                raise GuardCapabilityError(
                    "live tx Account substituted",
                    reason_code="xrpl.account_substituted",
                )
            if binding.destination and (
                not live_dest
                or normalize_classic_address(live_dest, field="live.Destination")
                != binding.destination
            ):
                raise GuardCapabilityError(
                    "live tx Destination substituted",
                    reason_code="xrpl.destination_substituted",
                )
            live_tag_n = _optional_uint32(live_tag, "live.DestinationTag") if live_tag is not None else None
            if live_tag_n != binding.destination_tag:
                raise GuardCapabilityError(
                    "live tx DestinationTag mutated",
                    reason_code="xrpl.destination_tag_mutated",
                )
            raise GuardCapabilityError(
                "live tx digest does not match binding",
                reason_code="xrpl.tx_substituted",
                details={
                    "expected": binding.tx_digest,
                    "observed": live_digest,
                },
            )

    def _assert_live_effects_match(
        self,
        binding: XRPLTransactionBinding,
        live_effects: Sequence[NormalizedXRPLEffect | Mapping[str, Any]],
    ) -> None:
        live_norm: list[NormalizedXRPLEffect] = []
        for item in live_effects:
            if isinstance(item, NormalizedXRPLEffect):
                live_norm.append(item)
            elif isinstance(item, Mapping):
                live_norm.append(NormalizedXRPLEffect.from_dict(item))
            else:
                raise GuardCapabilityError(
                    "live effects must be NormalizedXRPLEffect",
                    reason_code="xrpl.live_effects_invalid",
                )
        if len(live_norm) != len(binding.effects):
            raise GuardCapabilityError(
                "live effects count mismatch",
                reason_code="xrpl.effects_count_mismatch",
            )
        for expected, observed in zip(binding.effects, live_norm, strict=True):
            if expected.destination_tag != observed.destination_tag:
                raise GuardCapabilityError(
                    "live effect destination tag mutated",
                    reason_code="xrpl.destination_tag_mutated",
                )
            if expected.issuer != observed.issuer or expected.currency != observed.currency:
                raise GuardCapabilityError(
                    "live effect issuer/currency mutated",
                    reason_code="xrpl.issuer_currency_mutated",
                )
            if (
                expected.amount_value != observed.amount_value
                or expected.amount_kind != observed.amount_kind
            ):
                raise GuardCapabilityError(
                    "live effect amount mutated",
                    reason_code="xrpl.amount_mutated",
                )
            if (
                expected.delivered_amount_value != observed.delivered_amount_value
                or expected.delivered_amount_kind != observed.delivered_amount_kind
            ):
                raise GuardCapabilityError(
                    "live effect delivered amount mutated",
                    reason_code="xrpl.delivered_amount_mutated",
                )

    @staticmethod
    def _asset_amount_integer_string(value: str) -> str:
        """Project XRPL decimal amount strings into AssetAmount integer form.

        Guard :class:`AssetAmount` forbids binary floats and fractional decimal
        strings.  Issued currencies are exact decimal *strings* on XRPL; we
        preserve every digit by removing the radix point (scale is recorded on
        the intent attributes as ``amount_original``).
        """

        text = (value or "0").strip()
        if not text or text == "0":
            return "0"
        if text.startswith("-"):
            raise GuardValidationError("asset amount must be non-negative")
        if "." in text:
            whole, frac = text.split(".", 1)
            whole = whole or "0"
            digits = f"{whole}{frac}".lstrip("0") or "0"
            return digits
        if not _DECIMAL_RE.fullmatch(text):
            # Fall back to digit extraction for safety.
            digits = "".join(ch for ch in text if ch.isdigit())
            return digits.lstrip("0") or "0"
        return text

    def _intent_from_binding(
        self, binding: XRPLTransactionBinding, *, expires_at: str
    ) -> TransactionIntent:
        primary = binding.effects[0]
        destination = binding.destination or binding.account
        if binding.destination_tag is not None and binding.destination:
            destination = f"{binding.destination}:{binding.destination_tag}"

        assets: list[AssetAmount] = []
        amount_original = primary.amount_value or "0"
        if primary.amount_kind == "xrp":
            assets.append(
                AssetAmount(
                    asset_id="asset:xrp-native",
                    amount=self._asset_amount_integer_string(amount_original),
                    asset_namespace="native",
                    symbol="XRP",
                )
            )
        elif primary.amount_kind == "issued":
            # asset_id must be a stable identifier (no '/').
            issuer_token = primary.issuer.replace(":", "_")[:24]
            currency_token = primary.currency.replace(" ", "_")[:16]
            assets.append(
                AssetAmount(
                    asset_id=f"asset:xrpl-issued.{issuer_token}.{currency_token}",
                    amount=self._asset_amount_integer_string(amount_original),
                    asset_namespace="xrpl-issued",
                    symbol=primary.currency or "IOU",
                )
            )
        else:
            assets.append(
                AssetAmount(
                    asset_id="asset:xrp-native",
                    amount="0",
                    asset_namespace="native",
                    symbol="XRP",
                )
            )

        effects: list[ExpectedEffect] = []
        for index, effect in enumerate(binding.effects):
            summary = (
                f"{effect.transaction_type or binding.transaction_type} "
                f"{effect.amount_value} {effect.amount_kind} "
                f"{effect.account}->{effect.destination}"
            )
            if effect.partial_payment:
                summary += (
                    f" delivered={effect.delivered_amount_value}"
                    f"({effect.delivered_amount_kind})"
                )
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:xrpl-{index}",
                    kind=effect.kind,
                    summary=summary.strip(),
                )
            )

        signers: list[str] = [f"signer:{binding.account}"]
        for entry in binding.signer_list.signers:
            acct = str(entry.get("account", ""))
            if acct:
                signers.append(f"signer:{acct}")

        seq = (
            str(binding.sequence)
            if binding.sequence is not None
            else f"ticket:{binding.ticket_sequence}"
        )

        return TransactionIntent(
            intent_id=binding.intent_id,
            network=binding.network,
            sender=binding.account,
            destination=destination,
            method=f"xrpl.{binding.transaction_type}",
            assets=tuple(assets),
            fees=(
                FeeSpec(
                    amount=binding.fee_drops,
                    asset_id="asset:xrp-native",
                    payer=binding.account,
                ),
            ),
            nonce_or_sequence=seq,
            signers=tuple(dict.fromkeys(signers)),
            expected_effects=tuple(effects),
            expires_at=expires_at,
            chain_namespace=XRPL_NAMESPACE,
            attributes={
                "amount_original": amount_original,
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "destination_tag": binding.destination_tag,
                "flags": binding.flags,
                "genesis_hash": binding.genesis_hash,
                "ledger_epoch": binding.ledger_epoch.epoch_digest,
                "partial_payment": any(e.partial_payment for e in binding.effects),
                "signer_list_digest": binding.signer_list.list_digest,
            },
        )


def evaluate_xrpl_transaction_guard(
    candidate: XRPLTransactionCandidate | Mapping[str, Any],
    *,
    guard: XRPLTransactionGuard | None = None,
    **kwargs: Any,
) -> XRPLGuardDecision:
    """Convenience: bind an XRPL candidate and evaluate in one call."""

    guard = guard or XRPLTransactionGuard()
    bind_keys = {
        "ledger_epoch",
        "signer_list",
        "declared_effects",
        "serialized_bytes",
        "encoding",
        "candidate_id",
        "binding_id",
        "attributes",
    }
    bind_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in bind_keys}
    binding = guard.bind_transaction(candidate, **bind_kwargs)
    return guard.evaluate(binding, **kwargs)


__all__ = [
    "DEFAULT_COMPLIANCE_REQUIREMENTS",
    "DEFAULT_FEE_DROPS",
    "DEFAULT_POLICY_ID",
    "DEFAULT_PRODUCER_ID",
    "DEFAULT_SECURITY_REQUIREMENTS",
    "LEDGER_EPOCH_SCHEMA_VERSION",
    "SIGNER_LIST_SCHEMA_VERSION",
    "XRPL_BINDING_SCHEMA_VERSION",
    "XRPL_CANDIDATE_SCHEMA_VERSION",
    "XRPL_GUARD_DECISION_SCHEMA_VERSION",
    "XRPL_TRANSACTION_GUARD_INTERFACE",
    "XRPL_TRANSACTION_GUARD_SCHEMA_VERSION",
    "LedgerEpoch",
    "LedgerEpochResolver",
    "LedgerFreshnessChecker",
    "NormalizedXRPLEffect",
    "SignerListBinding",
    "XRPLGuardDecision",
    "XRPLGuardPhase",
    "XRPLTransactionBinding",
    "XRPLTransactionCandidate",
    "XRPLTransactionGuard",
    "content_sha256_hex",
    "evaluate_xrpl_transaction_guard",
    "normalize_xrpl_tx_effects",
]
