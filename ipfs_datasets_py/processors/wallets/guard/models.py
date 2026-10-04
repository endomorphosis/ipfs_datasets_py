"""Request models for exact transaction intent and preflight guard contracts.

These types are custody-neutral: they bind unsigned intent facts and exact
serialized candidates for policy evaluation.  They deliberately exclude private
keys, signatures, caller-supplied approval booleans, and broadcast handles.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.admissibility.receipt import (
    AuthorizationCapability,
    BoundRoots,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest

from .errors import GuardForbiddenSurfaceError, GuardValidationError

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

TRANSACTION_INTENT_SCHEMA_VERSION: Final = "wallet-guard.transaction-intent/v1"
TRANSACTION_CANDIDATE_SCHEMA_VERSION: Final = (
    "wallet-guard.transaction-candidate/v1"
)
TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION: Final = (
    "wallet-guard.transaction-preflight-request/v1"
)
ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION: Final = (
    "wallet-guard.admissibility-capability/v1"
)
PREFLIGHT_RESULT_SCHEMA_VERSION: Final = "wallet-guard.preflight-result/v1"
PREFLIGHT_CONSUMPTION_SCHEMA_VERSION: Final = (
    "wallet-guard.preflight-consumption/v1"
)

TRANSACTION_INTENT_INTERFACE: Final = "TransactionIntent@1"
TRANSACTION_CANDIDATE_INTERFACE: Final = "TransactionCandidate@1"
TRANSACTION_PREFLIGHT_REQUEST_INTERFACE: Final = "TransactionPreflightRequest@1"
ADMISSIBILITY_CAPABILITY_INTERFACE: Final = "AdmissibilityCapability@1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_HEX_PAYLOAD_CHARS: Final = 1_048_576

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_DECIMAL_AMOUNT_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")

# Fields that must never appear on guard request surfaces.
_FORBIDDEN_REQUEST_FIELDS: Final[frozenset[str]] = frozenset(
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


# ---------------------------------------------------------------------------
# Low-level validators
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


def _amount(value: Any, name: str) -> str:
    if isinstance(value, int):
        if value < 0:
            raise GuardValidationError(f"{name} must be a non-negative integer")
        return str(value)
    text = _text(value, name, max_chars=128)
    if not _DECIMAL_AMOUNT_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be a non-negative decimal integer string"
        )
    return text


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardValidationError(f"{name} must be an integer")
    if value < 0:
        raise GuardValidationError(f"{name} must be non-negative")
    return value


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
    hit = sorted(set(value) & _FORBIDDEN_REQUEST_FIELDS)
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


# ---------------------------------------------------------------------------
# Component records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetAmount:
    """Exact asset quantity bound into an unsigned intent."""

    asset_id: str
    amount: str
    asset_namespace: str = "native"
    symbol: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _identifier(self.asset_id, "asset_id"))
        object.__setattr__(self, "amount", _amount(self.amount, "amount"))
        object.__setattr__(
            self,
            "asset_namespace",
            _identifier(self.asset_namespace, "asset_namespace"),
        )
        object.__setattr__(
            self, "symbol", _optional_text(self.symbol, "symbol", max_chars=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "asset_id": self.asset_id,
            "asset_namespace": self.asset_namespace,
            "symbol": self.symbol,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssetAmount":
        value = _mapping(value, "AssetAmount")
        _reject_forbidden(value, "AssetAmount")
        _reject_unknown(
            value,
            frozenset({"asset_id", "amount", "asset_namespace", "symbol"}),
            "AssetAmount",
        )
        return cls(
            asset_id=value.get("asset_id", ""),
            amount=value.get("amount", ""),
            asset_namespace=value.get("asset_namespace", "native"),
            symbol=value.get("symbol", ""),
        )


@dataclass(frozen=True, slots=True)
class FeeSpec:
    """Exact fee bound into an unsigned intent."""

    amount: str
    asset_id: str = "native"
    payer: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _amount(self.amount, "amount"))
        object.__setattr__(self, "asset_id", _identifier(self.asset_id, "asset_id"))
        object.__setattr__(
            self, "payer", _optional_text(self.payer, "payer", max_chars=256)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "asset_id": self.asset_id,
            "payer": self.payer,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeeSpec":
        value = _mapping(value, "FeeSpec")
        _reject_forbidden(value, "FeeSpec")
        _reject_unknown(
            value, frozenset({"amount", "asset_id", "payer"}), "FeeSpec"
        )
        return cls(
            amount=value.get("amount", ""),
            asset_id=value.get("asset_id", "native"),
            payer=value.get("payer", ""),
        )


@dataclass(frozen=True, slots=True)
class UtxoRef:
    """UTXO input reference bound into an unsigned intent (Bitcoin-class chains)."""

    outpoint: str
    amount: str
    script_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "outpoint", _identifier(self.outpoint, "outpoint"))
        object.__setattr__(self, "amount", _amount(self.amount, "amount"))
        if self.script_digest in (None, ""):
            object.__setattr__(self, "script_digest", "")
        else:
            object.__setattr__(
                self, "script_digest", _digest(self.script_digest, "script_digest")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "outpoint": self.outpoint,
            "script_digest": self.script_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UtxoRef":
        value = _mapping(value, "UtxoRef")
        _reject_forbidden(value, "UtxoRef")
        _reject_unknown(
            value, frozenset({"outpoint", "amount", "script_digest"}), "UtxoRef"
        )
        return cls(
            outpoint=value.get("outpoint", ""),
            amount=value.get("amount", ""),
            script_digest=value.get("script_digest", ""),
        )


@dataclass(frozen=True, slots=True)
class ExpectedEffect:
    """Named expected economic or control effect of the candidate."""

    effect_id: str
    kind: str
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "effect_id", _identifier(self.effect_id, "effect_id")
        )
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        object.__setattr__(
            self, "summary", _optional_text(self.summary, "summary")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "kind": self.kind,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExpectedEffect":
        value = _mapping(value, "ExpectedEffect")
        _reject_forbidden(value, "ExpectedEffect")
        _reject_unknown(
            value, frozenset({"effect_id", "kind", "summary"}), "ExpectedEffect"
        )
        return cls(
            effect_id=value.get("effect_id", ""),
            kind=value.get("kind", ""),
            summary=value.get("summary", ""),
        )


# ---------------------------------------------------------------------------
# Core request models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransactionIntent:
    """Unsigned transaction intention bound for preflight evaluation.

    Binds network, sender, destination, method/instruction/script, assets,
    amounts, fees, nonce/sequence, UTXOs, signers, expected effects, and expiry.
    This record is never authorization.
    """

    intent_id: str
    network: str
    sender: str
    destination: str
    method: str
    assets: tuple[AssetAmount, ...]
    fees: tuple[FeeSpec, ...]
    nonce_or_sequence: str
    signers: tuple[str, ...]
    expected_effects: tuple[ExpectedEffect, ...]
    expires_at: str
    utxos: tuple[UtxoRef, ...] = ()
    chain_namespace: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    interface: str = TRANSACTION_INTENT_INTERFACE
    schema_version: str = TRANSACTION_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(self, "network", _identifier(self.network, "network"))
        object.__setattr__(self, "sender", _text(self.sender, "sender", max_chars=256))
        object.__setattr__(
            self, "destination", _text(self.destination, "destination", max_chars=256)
        )
        object.__setattr__(self, "method", _text(self.method, "method", max_chars=512))
        object.__setattr__(
            self,
            "assets",
            _sequence_of(self.assets, AssetAmount, "assets", AssetAmount.from_dict),
        )
        if not self.assets:
            raise GuardValidationError("intent requires at least one asset amount")
        object.__setattr__(
            self,
            "fees",
            _sequence_of(self.fees, FeeSpec, "fees", FeeSpec.from_dict),
        )
        if not self.fees:
            raise GuardValidationError("intent requires at least one fee binding")
        object.__setattr__(
            self,
            "nonce_or_sequence",
            _text(self.nonce_or_sequence, "nonce_or_sequence", max_chars=128),
        )
        object.__setattr__(
            self,
            "signers",
            _unique_ids(self.signers, "signers", require_non_empty=True),
        )
        object.__setattr__(
            self,
            "expected_effects",
            _sequence_of(
                self.expected_effects,
                ExpectedEffect,
                "expected_effects",
                ExpectedEffect.from_dict,
            ),
        )
        if not self.expected_effects:
            raise GuardValidationError(
                "intent requires at least one expected effect"
            )
        object.__setattr__(
            self, "expires_at", _timestamp(self.expires_at, "expires_at")
        )
        object.__setattr__(
            self,
            "utxos",
            _sequence_of(self.utxos, UtxoRef, "utxos", UtxoRef.from_dict),
        )
        object.__setattr__(
            self,
            "chain_namespace",
            _optional_text(self.chain_namespace, "chain_namespace", max_chars=128),
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.interface != TRANSACTION_INTENT_INTERFACE:
            raise GuardValidationError(
                f"unsupported transaction intent interface: {self.interface!r}"
            )
        if self.schema_version != TRANSACTION_INTENT_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported transaction intent schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assets": [item.to_dict() for item in self.assets],
            "attributes": self.attributes.to_dict(),
            "chain_namespace": self.chain_namespace,
            "destination": self.destination,
            "expected_effects": [item.to_dict() for item in self.expected_effects],
            "expires_at": self.expires_at,
            "fees": [item.to_dict() for item in self.fees],
            "intent_id": self.intent_id,
            "interface": self.interface,
            "method": self.method,
            "network": self.network,
            "nonce_or_sequence": self.nonce_or_sequence,
            "schema_version": self.schema_version,
            "sender": self.sender,
            "signers": list(self.signers),
            "utxos": [item.to_dict() for item in self.utxos],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionIntent":
        value = _mapping(value, "TransactionIntent")
        _reject_forbidden(value, "TransactionIntent")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assets",
                    "attributes",
                    "chain_namespace",
                    "destination",
                    "expected_effects",
                    "expires_at",
                    "fees",
                    "intent_id",
                    "interface",
                    "method",
                    "network",
                    "nonce_or_sequence",
                    "schema_version",
                    "sender",
                    "signers",
                    "utxos",
                }
            ),
            "TransactionIntent",
        )
        return cls(
            intent_id=value.get("intent_id", ""),
            network=value.get("network", ""),
            sender=value.get("sender", ""),
            destination=value.get("destination", ""),
            method=value.get("method", ""),
            assets=tuple(value.get("assets", ())),
            fees=tuple(value.get("fees", ())),
            nonce_or_sequence=value.get("nonce_or_sequence", ""),
            signers=tuple(value.get("signers", ())),
            expected_effects=tuple(value.get("expected_effects", ())),
            expires_at=value.get("expires_at", ""),
            utxos=tuple(value.get("utxos", ())),
            chain_namespace=value.get("chain_namespace", ""),
            attributes=value.get("attributes", {}),
            interface=value.get("interface", TRANSACTION_INTENT_INTERFACE),
            schema_version=value.get(
                "schema_version", TRANSACTION_INTENT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class TransactionCandidate:
    """Exact serialized transaction candidate bound to one intent."""

    candidate_id: str
    intent_id: str
    serialized_digest: str
    encoding: str
    byte_length: int
    network: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    interface: str = TRANSACTION_CANDIDATE_INTERFACE
    schema_version: str = TRANSACTION_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self,
            "serialized_digest",
            _digest(self.serialized_digest, "serialized_digest"),
        )
        object.__setattr__(
            self, "encoding", _identifier(self.encoding, "encoding")
        )
        object.__setattr__(
            self, "byte_length", _non_negative_int(self.byte_length, "byte_length")
        )
        if self.byte_length == 0:
            raise GuardValidationError("candidate byte_length must be positive")
        object.__setattr__(
            self, "network", _optional_text(self.network, "network", max_chars=128)
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.interface != TRANSACTION_CANDIDATE_INTERFACE:
            raise GuardValidationError(
                f"unsupported transaction candidate interface: {self.interface!r}"
            )
        if self.schema_version != TRANSACTION_CANDIDATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported transaction candidate schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "byte_length": self.byte_length,
            "candidate_id": self.candidate_id,
            "encoding": self.encoding,
            "intent_id": self.intent_id,
            "interface": self.interface,
            "network": self.network,
            "schema_version": self.schema_version,
            "serialized_digest": self.serialized_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionCandidate":
        value = _mapping(value, "TransactionCandidate")
        _reject_forbidden(value, "TransactionCandidate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "byte_length",
                    "candidate_id",
                    "encoding",
                    "intent_id",
                    "interface",
                    "network",
                    "schema_version",
                    "serialized_digest",
                }
            ),
            "TransactionCandidate",
        )
        return cls(
            candidate_id=value.get("candidate_id", ""),
            intent_id=value.get("intent_id", ""),
            serialized_digest=value.get("serialized_digest", ""),
            encoding=value.get("encoding", ""),
            byte_length=value.get("byte_length", -1),
            network=value.get("network", ""),
            attributes=value.get("attributes", {}),
            interface=value.get("interface", TRANSACTION_CANDIDATE_INTERFACE),
            schema_version=value.get(
                "schema_version", TRANSACTION_CANDIDATE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class TransactionPreflightRequest:
    """Custody-neutral preflight request binding intent, candidate, and policy.

    Composes security and compliance requirement identifiers.  Never carries
    keys, signatures, broadcast handles, or caller-supplied approval flags.
    """

    request_id: str
    intent: TransactionIntent
    candidate: TransactionCandidate
    tenant_id: str
    actor_id: str
    audience_id: str
    policy_id: str
    security_requirement_ids: tuple[str, ...]
    compliance_requirement_ids: tuple[str, ...]
    issued_at: str
    deadline: str
    expiry: str
    environment_id: str = ""
    environment_digest: str = ""
    nonce: str = ""
    profile_id: str = "profile:wallet-guard"
    roots: BoundRoots | None = None
    attributes: FrozenMap = field(default_factory=FrozenMap)
    interface: str = TRANSACTION_PREFLIGHT_REQUEST_INTERFACE
    schema_version: str = TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION

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
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        object.__setattr__(
            self, "audience_id", _identifier(self.audience_id, "audience_id")
        )
        object.__setattr__(
            self, "policy_id", _identifier(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "security_requirement_ids",
            _unique_ids(self.security_requirement_ids, "security_requirement_ids"),
        )
        object.__setattr__(
            self,
            "compliance_requirement_ids",
            _unique_ids(
                self.compliance_requirement_ids, "compliance_requirement_ids"
            ),
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "deadline", _timestamp(self.deadline, "deadline")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        if self.deadline < self.issued_at:
            raise GuardValidationError("deadline must not precede issued_at")
        if self.expiry < self.issued_at:
            raise GuardValidationError("expiry must not precede issued_at")
        if self.expiry < self.deadline:
            raise GuardValidationError("expiry must not precede deadline")
        if self.intent.expires_at < self.expiry:
            raise GuardValidationError(
                "intent.expires_at must not precede request expiry"
            )
        object.__setattr__(
            self,
            "environment_id",
            _optional_text(self.environment_id, "environment_id", max_chars=256),
        )
        if self.environment_digest in (None, ""):
            object.__setattr__(self, "environment_digest", "")
        else:
            object.__setattr__(
                self,
                "environment_digest",
                _digest(self.environment_digest, "environment_digest"),
            )
        object.__setattr__(
            self, "nonce", _text(self.nonce or self.request_id, "nonce", max_chars=128)
        )
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        if self.roots is not None and not isinstance(self.roots, BoundRoots):
            if isinstance(self.roots, Mapping):
                object.__setattr__(self, "roots", BoundRoots.from_dict(self.roots))
            else:
                raise GuardValidationError("roots must be BoundRoots or mapping")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.interface != TRANSACTION_PREFLIGHT_REQUEST_INTERFACE:
            raise GuardValidationError(
                f"unsupported preflight request interface: {self.interface!r}"
            )
        if self.schema_version != TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported preflight request schema: {self.schema_version!r}"
            )

    @property
    def request_digest(self) -> str:
        """Content digest of the full preflight request (no secrets)."""

        return stable_digest(self.to_dict())

    @property
    def intent_digest(self) -> str:
        return self.intent.digest

    @property
    def candidate_digest(self) -> str:
        return self.candidate.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "attributes": self.attributes.to_dict(),
            "audience_id": self.audience_id,
            "candidate": self.candidate.to_dict(),
            "compliance_requirement_ids": list(self.compliance_requirement_ids),
            "deadline": self.deadline,
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "expiry": self.expiry,
            "intent": self.intent.to_dict(),
            "interface": self.interface,
            "issued_at": self.issued_at,
            "nonce": self.nonce,
            "policy_id": self.policy_id,
            "profile_id": self.profile_id,
            "request_id": self.request_id,
            "roots": None if self.roots is None else self.roots.to_dict(),
            "schema_version": self.schema_version,
            "security_requirement_ids": list(self.security_requirement_ids),
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionPreflightRequest":
        value = _mapping(value, "TransactionPreflightRequest")
        _reject_forbidden(value, "TransactionPreflightRequest")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actor_id",
                    "attributes",
                    "audience_id",
                    "candidate",
                    "compliance_requirement_ids",
                    "deadline",
                    "environment_digest",
                    "environment_id",
                    "expiry",
                    "intent",
                    "interface",
                    "issued_at",
                    "nonce",
                    "policy_id",
                    "profile_id",
                    "request_id",
                    "roots",
                    "schema_version",
                    "security_requirement_ids",
                    "tenant_id",
                }
            ),
            "TransactionPreflightRequest",
        )
        return cls(
            request_id=value.get("request_id", ""),
            intent=value.get("intent", {}),
            candidate=value.get("candidate", {}),
            tenant_id=value.get("tenant_id", ""),
            actor_id=value.get("actor_id", ""),
            audience_id=value.get("audience_id", ""),
            policy_id=value.get("policy_id", ""),
            security_requirement_ids=tuple(
                value.get("security_requirement_ids", ())
            ),
            compliance_requirement_ids=tuple(
                value.get("compliance_requirement_ids", ())
            ),
            issued_at=value.get("issued_at", ""),
            deadline=value.get("deadline", ""),
            expiry=value.get("expiry", ""),
            environment_id=value.get("environment_id", ""),
            environment_digest=value.get("environment_digest", ""),
            nonce=value.get("nonce", ""),
            profile_id=value.get("profile_id", "profile:wallet-guard"),
            roots=value.get("roots"),
            attributes=value.get("attributes", {}),
            interface=value.get(
                "interface", TRANSACTION_PREFLIGHT_REQUEST_INTERFACE
            ),
            schema_version=value.get(
                "schema_version", TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Capability specialization
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdmissibilityCapability:
    """Request-bound, one-use transaction admissibility capability.

    Specializes :class:`AuthorizationCapability` for wallet preflight.  Only
    issued after a current ``ALLOW``.  Consumption requires live revalidation
    of the exact request digests and atomic compare-and-consume.
    """

    capability_id: str
    request_digest: str
    intent_digest: str
    candidate_digest: str
    network: str
    intent_id: str
    candidate_id: str
    tenant_id: str
    authorization: AuthorizationCapability
    phase: str = "pre_sign"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    interface: str = ADMISSIBILITY_CAPABILITY_INTERFACE
    schema_version: str = ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capability_id", _identifier(self.capability_id, "capability_id")
        )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
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
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        if not isinstance(self.authorization, AuthorizationCapability):
            if isinstance(self.authorization, Mapping):
                object.__setattr__(
                    self,
                    "authorization",
                    AuthorizationCapability.from_dict(self.authorization),
                )
            else:
                raise GuardValidationError(
                    "authorization must be an AuthorizationCapability"
                )
        if not self.authorization.one_time:
            raise GuardValidationError(
                "admissibility capabilities must be one-time"
            )
        if self.authorization.request_digest != self.request_digest:
            raise GuardValidationError(
                "authorization.request_digest must match capability request_digest"
            )
        if self.authorization.capability_id != self.capability_id:
            raise GuardValidationError(
                "authorization.capability_id must match capability_id"
            )
        object.__setattr__(self, "phase", _identifier(self.phase, "phase"))
        if self.phase not in {"pre_sign", "pre_broadcast"}:
            raise GuardValidationError(
                "phase must be 'pre_sign' or 'pre_broadcast'"
            )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.interface != ADMISSIBILITY_CAPABILITY_INTERFACE:
            raise GuardValidationError(
                f"unsupported admissibility capability interface: {self.interface!r}"
            )
        if self.schema_version != ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported admissibility capability schema: "
                f"{self.schema_version!r}"
            )

    @property
    def one_time(self) -> bool:
        return True

    @property
    def expiry(self) -> str:
        return self.authorization.expiry

    @property
    def audience_id(self) -> str:
        return self.authorization.audience_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "authorization": self.authorization.to_dict(),
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "capability_id": self.capability_id,
            "intent_digest": self.intent_digest,
            "intent_id": self.intent_id,
            "interface": self.interface,
            "network": self.network,
            "one_time": True,
            "phase": self.phase,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdmissibilityCapability":
        value = _mapping(value, "AdmissibilityCapability")
        _reject_forbidden(value, "AdmissibilityCapability")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "authorization",
                    "candidate_digest",
                    "candidate_id",
                    "capability_id",
                    "intent_digest",
                    "intent_id",
                    "interface",
                    "network",
                    "one_time",
                    "phase",
                    "request_digest",
                    "schema_version",
                    "tenant_id",
                }
            ),
            "AdmissibilityCapability",
        )
        return cls(
            capability_id=value.get("capability_id", ""),
            request_digest=value.get("request_digest", ""),
            intent_digest=value.get("intent_digest", ""),
            candidate_digest=value.get("candidate_digest", ""),
            network=value.get("network", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            tenant_id=value.get("tenant_id", ""),
            authorization=value.get("authorization", {}),
            phase=value.get("phase", "pre_sign"),
            attributes=value.get("attributes", {}),
            interface=value.get("interface", ADMISSIBILITY_CAPABILITY_INTERFACE),
            schema_version=value.get(
                "schema_version", ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


class PreflightPhase(str, Enum):
    """Consumption phases for two-phase pre-sign / pre-broadcast revalidation."""

    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Immutable preflight evaluation outcome.

    A bare boolean is intentionally not sufficient: callers must inspect
    ``outcome``, ``blocks_automation``, and the optional capability.
    """

    request_digest: str
    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    receipt_id: str = ""
    receipt_digest: str = ""
    capability: AdmissibilityCapability | None = None
    security_results: FrozenMap = field(default_factory=FrozenMap)
    compliance_results: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PREFLIGHT_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if isinstance(self.outcome, str):
            try:
                object.__setattr__(
                    self, "outcome", TransactionVerdictOutcome(self.outcome)
                )
            except ValueError as exc:
                raise GuardValidationError(
                    f"unsupported outcome: {self.outcome!r}"
                ) from exc
        if not isinstance(self.outcome, TransactionVerdictOutcome):
            raise GuardValidationError("outcome must be a TransactionVerdictOutcome")
        if not isinstance(self.blocks_automation, bool):
            raise GuardValidationError("blocks_automation must be a bool")
        # Consistency: only current ALLOW may leave automation unblocked, and
        # only then with a one-use capability.
        if self.outcome is TransactionVerdictOutcome.ALLOW:
            if self.blocks_automation:
                raise GuardValidationError(
                    "ALLOW outcome cannot set blocks_automation=True"
                )
            if self.capability is None:
                raise GuardValidationError(
                    "ALLOW outcome requires an AdmissibilityCapability"
                )
        else:
            if not self.blocks_automation:
                raise GuardValidationError(
                    "non-ALLOW outcome must set blocks_automation=True"
                )
            if self.capability is not None:
                raise GuardValidationError(
                    "non-ALLOW outcome must not carry a capability"
                )
        object.__setattr__(
            self, "reason_codes", _unique_ids(self.reason_codes, "reason_codes")
        )
        object.__setattr__(
            self,
            "reasons",
            tuple(
                _text(item, "reasons item", max_chars=512)
                for item in (self.reasons or ())
            ),
        )
        object.__setattr__(
            self, "receipt_id", _optional_text(self.receipt_id, "receipt_id")
        )
        if self.receipt_digest in (None, ""):
            object.__setattr__(self, "receipt_digest", "")
        else:
            object.__setattr__(
                self, "receipt_digest", _digest(self.receipt_digest, "receipt_digest")
            )
        if self.capability is not None and not isinstance(
            self.capability, AdmissibilityCapability
        ):
            if isinstance(self.capability, Mapping):
                object.__setattr__(
                    self,
                    "capability",
                    AdmissibilityCapability.from_dict(self.capability),
                )
            else:
                raise GuardValidationError(
                    "capability must be AdmissibilityCapability or None"
                )
        if not isinstance(self.security_results, FrozenMap):
            object.__setattr__(
                self, "security_results", _attributes(self.security_results)
            )
        if not isinstance(self.compliance_results, FrozenMap):
            object.__setattr__(
                self, "compliance_results", _attributes(self.compliance_results)
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def is_allow(self) -> bool:
        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
            and self.capability is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks_automation": self.blocks_automation,
            "capability": (
                None if self.capability is None else self.capability.to_dict()
            ),
            "compliance_results": self.compliance_results.to_dict(),
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "security_results": self.security_results.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PreflightConsumptionResult:
    """Result of live revalidation and atomic one-use capability consumption."""

    allowed: bool
    reason_code: str
    reason: str
    capability_id: str
    request_digest: str
    phase: str
    consumed_at: str = ""
    schema_version: str = PREFLIGHT_CONSUMPTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise GuardValidationError("allowed must be a bool")
        object.__setattr__(
            self, "reason_code", _identifier(self.reason_code, "reason_code")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason", max_chars=512))
        object.__setattr__(
            self, "capability_id", _identifier(self.capability_id, "capability_id")
        )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(self, "phase", _identifier(self.phase, "phase"))
        object.__setattr__(
            self, "consumed_at", _optional_text(self.consumed_at, "consumed_at")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "capability_id": self.capability_id,
            "consumed_at": self.consumed_at,
            "phase": self.phase,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sequence_of(
    values: Any,
    item_type: type,
    name: str,
    from_dict,
) -> tuple:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise GuardValidationError(f"{name} must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise GuardValidationError(f"{name} exceeds maximum collection size")
    items = []
    for index, item in enumerate(values):
        if isinstance(item, item_type):
            items.append(item)
        elif isinstance(item, Mapping):
            items.append(from_dict(item))
        else:
            raise GuardValidationError(
                f"{name}[{index}] must be {item_type.__name__} or mapping"
            )
    return tuple(items)


__all__ = [
    "ADMISSIBILITY_CAPABILITY_INTERFACE",
    "ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION",
    "AdmissibilityCapability",
    "AssetAmount",
    "ExpectedEffect",
    "FeeSpec",
    "PREFLIGHT_CONSUMPTION_SCHEMA_VERSION",
    "PREFLIGHT_RESULT_SCHEMA_VERSION",
    "PreflightConsumptionResult",
    "PreflightPhase",
    "PreflightResult",
    "TRANSACTION_CANDIDATE_INTERFACE",
    "TRANSACTION_CANDIDATE_SCHEMA_VERSION",
    "TRANSACTION_INTENT_INTERFACE",
    "TRANSACTION_INTENT_SCHEMA_VERSION",
    "TRANSACTION_PREFLIGHT_REQUEST_INTERFACE",
    "TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION",
    "TransactionCandidate",
    "TransactionIntent",
    "TransactionPreflightRequest",
    "UtxoRef",
]
