"""Canonical Crypto IR model: frozen, content-addressed, chain-neutral records.

This module adapts :mod:`ipfs_datasets_py.logic.ir_core` for wallet identities,
exact amounts, unsigned intents, serialized candidates, contract artifacts,
observations, completeness, and time-bounded epochs.

Authority layers are explicit.  Declarations, observations, assumptions,
results, and authorization are separate record families; conversion cannot
elevate authority (see :mod:`.provenance`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ..ir_core.canonical import (
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes,
)
from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, freeze_json, thaw_json
from .identity import crypto_ir_identity
from .provenance import (
    AuthorityBinding,
    AuthorityKind,
    CryptoIRProvenance,
    CryptoIRProvenanceError,
    ObservationProvenance,
    assert_authority_not_elevated,
    freeze_json_mapping,
)
from .schema_versions import (
    CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION,
    CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION,
    CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION,
    CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION,
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
    CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION,
    CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION,
)


CRYPTO_IR_MODEL_DOMAIN: Final[str] = "crypto-ir.model"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DECIMAL_INTEGER = re.compile(r"^-?(0|[1-9][0-9]*)$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_TAGGED = re.compile(r"^[a-z0-9]+:[0-9a-f]+$")


class CryptoIRValidationError(ValueError):
    """Raised when a Crypto IR record is malformed or fails closed."""


class FinalityStatus(str, Enum):
    """Observed finality classification; not authorization."""

    UNKNOWN = "unknown"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    REORGED = "reorged"
    RETRACTED = "retracted"


class RetractionStatus(str, Enum):
    """Whether an observation remains valid after reorg/retraction."""

    NOT_RETRACTED = "not_retracted"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    UNKNOWN = "unknown"


class CompletenessStatus(str, Enum):
    """Coverage completeness of an acquisition or observation window."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class ArtifactKind(str, Enum):
    """High-level contract/program/script artifact kinds."""

    BYTECODE = "bytecode"
    PROGRAM = "program"
    SCRIPT = "script"
    SOURCE = "source"
    ABI = "abi"
    IDL = "idl"
    BUILD_MANIFEST = "build_manifest"
    METADATA = "metadata"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRValidationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise CryptoIRValidationError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRValidationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (ProvenanceValidationError, CryptoIRProvenanceError) as exc:
        raise CryptoIRValidationError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except ProvenanceValidationError as exc:
        raise CryptoIRValidationError(str(exc)) from exc


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise CryptoIRValidationError(f"{name} must be an integer")
    if value < 0:
        raise CryptoIRValidationError(f"{name} must be non-negative")
    return value


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, name)


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRValidationError(f"unsupported {name}: {value!r}") from exc


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRValidationError(f"{name} values must be unique")
    return result


def _digest(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = _text(value, name, allow_empty=allow_empty)
    if not text:
        return text
    if _SHA256_HEX.fullmatch(text):
        return f"sha256:{text}"
    if not _DIGEST_TAGGED.fullmatch(text):
        raise CryptoIRValidationError(
            f"{name} must be a tagged digest (algorithm:hex) or bare sha256 hex"
        )
    return text


def _sequence_of(
    values: Any,
    item_type: type[Any],
    name: str,
    *,
    from_dict: Any | None = None,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    converted: list[Any] = []
    for item in values:
        if isinstance(item, item_type):
            converted.append(item)
        elif from_dict is not None and isinstance(item, Mapping):
            converted.append(from_dict(item))
        else:
            raise CryptoIRValidationError(
                f"{name} items must be {item_type.__name__} or mappings"
            )
    return tuple(converted)


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExactAmount:
    """Exact signed base-unit quantity; binary floats are rejected."""

    base_units: str
    decimals: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.base_units, float) or isinstance(self.decimals, float):
            raise CryptoIRValidationError("ExactAmount rejects binary floats")
        if type(self.base_units) is int and not isinstance(self.base_units, bool):
            object.__setattr__(self, "base_units", str(self.base_units))
        if not isinstance(self.base_units, str) or not _DECIMAL_INTEGER.fullmatch(
            self.base_units
        ):
            raise CryptoIRValidationError(
                "base_units must be a canonical decimal integer string"
            )
        object.__setattr__(
            self, "decimals", _non_negative_int(self.decimals, "decimals")
        )
        if self.decimals > 255:
            raise CryptoIRValidationError("decimals must not exceed 255")

    @classmethod
    def from_int(cls, value: int, *, decimals: int = 0) -> "ExactAmount":
        if isinstance(value, bool) or type(value) is not int:
            raise CryptoIRValidationError("amount must be an integer")
        if isinstance(value, float) or isinstance(decimals, float):
            raise CryptoIRValidationError("ExactAmount rejects binary floats")
        return cls(str(value), decimals)

    def to_dict(self) -> dict[str, Any]:
        return {"base_units": self.base_units, "decimals": self.decimals}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactAmount":
        value = _as_mapping(value, "ExactAmount")
        _known_fields(value, frozenset({"base_units", "decimals"}), "ExactAmount")
        return cls(
            base_units=value.get("base_units", ""),
            decimals=value.get("decimals", 0),
        )


@dataclass(frozen=True, slots=True)
class LedgerCoordinate:
    """Chain-neutral block, slot, or ledger coordinate."""

    sequence: int | None = None
    hash: str = ""
    transaction_index: int | None = None
    event_index: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sequence", _optional_non_negative_int(self.sequence, "sequence")
        )
        object.__setattr__(self, "hash", _text(self.hash, "hash", allow_empty=True))
        object.__setattr__(
            self,
            "transaction_index",
            _optional_non_negative_int(self.transaction_index, "transaction_index"),
        )
        object.__setattr__(
            self,
            "event_index",
            _optional_non_negative_int(self.event_index, "event_index"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_index": self.event_index,
            "hash": self.hash,
            "sequence": self.sequence,
            "transaction_index": self.transaction_index,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerCoordinate":
        value = _as_mapping(value, "LedgerCoordinate")
        _known_fields(
            value,
            frozenset({"sequence", "hash", "transaction_index", "event_index"}),
            "LedgerCoordinate",
        )
        return cls(
            sequence=value.get("sequence"),
            hash=value.get("hash", ""),
            transaction_index=value.get("transaction_index"),
            event_index=value.get("event_index"),
        )


@dataclass(frozen=True, slots=True)
class ValidityWindow:
    """Inclusive-start / exclusive-end validity interval (ISO-8601 strings)."""

    start: str = ""
    end: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _text(self.start, "start", allow_empty=True))
        object.__setattr__(self, "end", _text(self.end, "end", allow_empty=True))

    def to_dict(self) -> dict[str, Any]:
        return {"end": self.end, "start": self.start}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidityWindow":
        value = _as_mapping(value, "ValidityWindow")
        _known_fields(value, frozenset({"start", "end"}), "ValidityWindow")
        return cls(start=value.get("start", ""), end=value.get("end", ""))


@dataclass(frozen=True, slots=True)
class TimeBoundedEpoch:
    """Time-bounded mutable fact (proxy, upgrade authority, list membership)."""

    epoch_id: str
    kind: str
    subject_id: str
    value_digest: str
    validity: ValidityWindow = field(default_factory=ValidityWindow)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "value_digest", _digest(self.value_digest, "value_digest")
        )
        if not isinstance(self.validity, ValidityWindow):
            object.__setattr__(
                self,
                "validity",
                ValidityWindow.from_dict(_as_mapping(self.validity, "validity")),
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "epoch_id": self.epoch_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "validity": self.validity.to_dict(),
            "value_digest": self.value_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TimeBoundedEpoch":
        value = _as_mapping(value, "TimeBoundedEpoch")
        _known_fields(
            value,
            frozenset(
                {
                    "epoch_id",
                    "kind",
                    "subject_id",
                    "value_digest",
                    "validity",
                    "attributes",
                }
            ),
            "TimeBoundedEpoch",
        )
        return cls(
            epoch_id=value.get("epoch_id", ""),
            kind=value.get("kind", ""),
            subject_id=value.get("subject_id", ""),
            value_digest=value.get("value_digest", ""),
            validity=ValidityWindow.from_dict(
                _as_mapping(value.get("validity", {}), "validity")
            ),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Identity declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChainIdentity:
    """Immutable chain/network/genesis identity declaration."""

    chain_namespace: str
    network: str
    genesis_digest: str
    chain_id: str = ""
    display_name: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION.identifier

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "chain_namespace", _text(self.chain_namespace, "chain_namespace")
        )
        object.__setattr__(self, "network", _text(self.network, "network"))
        object.__setattr__(
            self, "genesis_digest", _digest(self.genesis_digest, "genesis_digest")
        )
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", allow_empty=True)
        )
        object.__setattr__(
            self,
            "display_name",
            _text(self.display_name, "display_name", allow_empty=True),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "chain_namespace": self.chain_namespace,
            "display_name": self.display_name,
            "genesis_digest": self.genesis_digest,
            "network": self.network,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChainIdentity":
        value = _as_mapping(value, "ChainIdentity")
        _known_fields(
            value,
            frozenset(
                {
                    "chain_namespace",
                    "network",
                    "genesis_digest",
                    "chain_id",
                    "display_name",
                    "attributes",
                    "schema_version",
                }
            ),
            "ChainIdentity",
        )
        return cls(
            chain_namespace=value.get("chain_namespace", ""),
            network=value.get("network", ""),
            genesis_digest=value.get("genesis_digest", ""),
            chain_id=value.get("chain_id", ""),
            display_name=value.get("display_name", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION.identifier
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_MODEL_DOMAIN}.chain-identity",
        )


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    """Normalized account/address identity bound to a chain identity."""

    chain: ChainIdentity
    address_normalized: str
    address_original: str
    account_kind: str = "account"
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION.identifier

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(
            self, "address_normalized", _text(self.address_normalized, "address_normalized")
        )
        object.__setattr__(
            self, "address_original", _text(self.address_original, "address_original")
        )
        object.__setattr__(self, "account_kind", _text(self.account_kind, "account_kind"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_kind": self.account_kind,
            "address_normalized": self.address_normalized,
            "address_original": self.address_original,
            "attributes": thaw_json(self.attributes),
            "chain": self.chain.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AccountIdentity":
        value = _as_mapping(value, "AccountIdentity")
        _known_fields(
            value,
            frozenset(
                {
                    "chain",
                    "address_normalized",
                    "address_original",
                    "account_kind",
                    "attributes",
                    "schema_version",
                }
            ),
            "AccountIdentity",
        )
        return cls(
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            address_normalized=value.get("address_normalized", ""),
            address_original=value.get("address_original", ""),
            account_kind=value.get("account_kind", "account"),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION.identifier
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_MODEL_DOMAIN}.account-identity",
        )


@dataclass(frozen=True, slots=True)
class WalletDescriptor:
    """Declared wallet capabilities and controlled accounts."""

    wallet_id: str
    accounts: tuple[AccountIdentity, ...]
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet_id", _identifier(self.wallet_id, "wallet_id"))
        object.__setattr__(
            self,
            "accounts",
            _sequence_of(
                self.accounts, AccountIdentity, "accounts", from_dict=AccountIdentity.from_dict
            ),
        )
        if not self.accounts:
            raise CryptoIRValidationError("wallet must declare at least one account")
        object.__setattr__(self, "label", _text(self.label, "label", allow_empty=True))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "accounts": [item.to_dict() for item in self.accounts],
            "attributes": thaw_json(self.attributes),
            "label": self.label,
            "wallet_id": self.wallet_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WalletDescriptor":
        value = _as_mapping(value, "WalletDescriptor")
        _known_fields(
            value,
            frozenset({"wallet_id", "accounts", "label", "attributes"}),
            "WalletDescriptor",
        )
        return cls(
            wallet_id=value.get("wallet_id", ""),
            accounts=tuple(
                AccountIdentity.from_dict(item) for item in value.get("accounts", ())
            ),
            label=value.get("label", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    """Chain-qualified asset identity with display precision."""

    chain: ChainIdentity
    asset_namespace: str
    asset_reference: str
    decimals: int = 0
    symbol: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(
            self, "asset_namespace", _text(self.asset_namespace, "asset_namespace")
        )
        object.__setattr__(
            self, "asset_reference", _text(self.asset_reference, "asset_reference")
        )
        object.__setattr__(
            self, "decimals", _non_negative_int(self.decimals, "decimals")
        )
        if self.decimals > 255:
            raise CryptoIRValidationError("decimals must not exceed 255")
        object.__setattr__(
            self, "symbol", _text(self.symbol, "symbol", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_namespace": self.asset_namespace,
            "asset_reference": self.asset_reference,
            "attributes": thaw_json(self.attributes),
            "chain": self.chain.to_dict(),
            "decimals": self.decimals,
            "symbol": self.symbol,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssetIdentity":
        value = _as_mapping(value, "AssetIdentity")
        _known_fields(
            value,
            frozenset(
                {
                    "chain",
                    "asset_namespace",
                    "asset_reference",
                    "decimals",
                    "symbol",
                    "attributes",
                }
            ),
            "AssetIdentity",
        )
        return cls(
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            asset_namespace=value.get("asset_namespace", ""),
            asset_reference=value.get("asset_reference", ""),
            decimals=value.get("decimals", 0),
            symbol=value.get("symbol", ""),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Transaction intent declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignerRequirement:
    """Declared signer requirement for an unsigned intent."""

    account: AccountIdentity
    role: str = "signer"
    threshold_weight: int = 1
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.account, AccountIdentity):
            object.__setattr__(
                self,
                "account",
                AccountIdentity.from_dict(_as_mapping(self.account, "account")),
            )
        object.__setattr__(self, "role", _text(self.role, "role"))
        object.__setattr__(
            self,
            "threshold_weight",
            _non_negative_int(self.threshold_weight, "threshold_weight"),
        )
        if self.threshold_weight < 1:
            raise CryptoIRValidationError("threshold_weight must be >= 1")
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict(),
            "attributes": thaw_json(self.attributes),
            "role": self.role,
            "threshold_weight": self.threshold_weight,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignerRequirement":
        value = _as_mapping(value, "SignerRequirement")
        _known_fields(
            value,
            frozenset({"account", "role", "threshold_weight", "attributes"}),
            "SignerRequirement",
        )
        return cls(
            account=AccountIdentity.from_dict(
                _as_mapping(value.get("account", {}), "account")
            ),
            role=value.get("role", "signer"),
            threshold_weight=value.get("threshold_weight", 1),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class TransferIntent:
    """Declared asset transfer within an unsigned intent."""

    asset: AssetIdentity
    amount: ExactAmount
    from_account: AccountIdentity
    to_account: AccountIdentity
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.asset, AssetIdentity):
            object.__setattr__(
                self, "asset", AssetIdentity.from_dict(_as_mapping(self.asset, "asset"))
            )
        if not isinstance(self.amount, ExactAmount):
            object.__setattr__(
                self,
                "amount",
                ExactAmount.from_dict(_as_mapping(self.amount, "amount")),
            )
        if not isinstance(self.from_account, AccountIdentity):
            object.__setattr__(
                self,
                "from_account",
                AccountIdentity.from_dict(_as_mapping(self.from_account, "from_account")),
            )
        if not isinstance(self.to_account, AccountIdentity):
            object.__setattr__(
                self,
                "to_account",
                AccountIdentity.from_dict(_as_mapping(self.to_account, "to_account")),
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount.to_dict(),
            "asset": self.asset.to_dict(),
            "attributes": thaw_json(self.attributes),
            "from_account": self.from_account.to_dict(),
            "to_account": self.to_account.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransferIntent":
        value = _as_mapping(value, "TransferIntent")
        _known_fields(
            value,
            frozenset(
                {"asset", "amount", "from_account", "to_account", "attributes"}
            ),
            "TransferIntent",
        )
        return cls(
            asset=AssetIdentity.from_dict(_as_mapping(value.get("asset", {}), "asset")),
            amount=ExactAmount.from_dict(_as_mapping(value.get("amount", {}), "amount")),
            from_account=AccountIdentity.from_dict(
                _as_mapping(value.get("from_account", {}), "from_account")
            ),
            to_account=AccountIdentity.from_dict(
                _as_mapping(value.get("to_account", {}), "to_account")
            ),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class CallIntent:
    """Declared contract/program call within an unsigned intent."""

    target: AccountIdentity
    method: str
    calldata_digest: str = ""
    value: ExactAmount | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.target, AccountIdentity):
            object.__setattr__(
                self,
                "target",
                AccountIdentity.from_dict(_as_mapping(self.target, "target")),
            )
        object.__setattr__(self, "method", _text(self.method, "method"))
        object.__setattr__(
            self,
            "calldata_digest",
            _digest(self.calldata_digest, "calldata_digest", allow_empty=True),
        )
        if self.value is not None and not isinstance(self.value, ExactAmount):
            object.__setattr__(
                self, "value", ExactAmount.from_dict(_as_mapping(self.value, "value"))
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "calldata_digest": self.calldata_digest,
            "method": self.method,
            "target": self.target.to_dict(),
            "value": None if self.value is None else self.value.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CallIntent":
        value = _as_mapping(value, "CallIntent")
        _known_fields(
            value,
            frozenset(
                {"target", "method", "calldata_digest", "value", "attributes"}
            ),
            "CallIntent",
        )
        raw_value = value.get("value")
        return cls(
            target=AccountIdentity.from_dict(
                _as_mapping(value.get("target", {}), "target")
            ),
            method=value.get("method", ""),
            calldata_digest=value.get("calldata_digest", ""),
            value=None
            if raw_value is None
            else ExactAmount.from_dict(_as_mapping(raw_value, "value")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ExpectedEffect:
    """Declared expected effect of an unsigned intent (not an observation)."""

    effect_id: str
    kind: str
    summary: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _identifier(self.effect_id, "effect_id"))
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "effect_id": self.effect_id,
            "kind": self.kind,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExpectedEffect":
        value = _as_mapping(value, "ExpectedEffect")
        _known_fields(
            value,
            frozenset({"effect_id", "kind", "summary", "attributes"}),
            "ExpectedEffect",
        )
        return cls(
            effect_id=value.get("effect_id", ""),
            kind=value.get("kind", ""),
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
        )


UNSIGNED_INTENT_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/signers": CollectionSemantics.ORDERED,
        "/transfers": CollectionSemantics.ORDERED,
        "/calls": CollectionSemantics.ORDERED,
        "/expected_effects": CollectionSemantics.SET_LIKE,
        "/assumption_ids": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class UnsignedTransactionIntent:
    """Declaration of an unsigned transaction intention (not authorization)."""

    intent_id: str
    chain: ChainIdentity
    origin: AccountIdentity
    signers: tuple[SignerRequirement, ...]
    transfers: tuple[TransferIntent, ...] = ()
    calls: tuple[CallIntent, ...] = ()
    expected_effects: tuple[ExpectedEffect, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    memo: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION.identifier

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        if not isinstance(self.origin, AccountIdentity):
            object.__setattr__(
                self,
                "origin",
                AccountIdentity.from_dict(_as_mapping(self.origin, "origin")),
            )
        object.__setattr__(
            self,
            "signers",
            _sequence_of(
                self.signers,
                SignerRequirement,
                "signers",
                from_dict=SignerRequirement.from_dict,
            ),
        )
        if not self.signers:
            raise CryptoIRValidationError("unsigned intent requires at least one signer")
        object.__setattr__(
            self,
            "transfers",
            _sequence_of(
                self.transfers,
                TransferIntent,
                "transfers",
                from_dict=TransferIntent.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "calls",
            _sequence_of(
                self.calls, CallIntent, "calls", from_dict=CallIntent.from_dict
            ),
        )
        object.__setattr__(
            self,
            "expected_effects",
            _sequence_of(
                self.expected_effects,
                ExpectedEffect,
                "expected_effects",
                from_dict=ExpectedEffect.from_dict,
            ),
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(self, "memo", _text(self.memo, "memo", allow_empty=True))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "calls": [item.to_dict() for item in self.calls],
            "chain": self.chain.to_dict(),
            "expected_effects": [item.to_dict() for item in self.expected_effects],
            "intent_id": self.intent_id,
            "memo": self.memo,
            "origin": self.origin.to_dict(),
            "schema_version": self.schema_version,
            "signers": [item.to_dict() for item in self.signers],
            "transfers": [item.to_dict() for item in self.transfers],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsignedTransactionIntent":
        value = _as_mapping(value, "UnsignedTransactionIntent")
        _known_fields(
            value,
            frozenset(
                {
                    "intent_id",
                    "chain",
                    "origin",
                    "signers",
                    "transfers",
                    "calls",
                    "expected_effects",
                    "assumption_ids",
                    "memo",
                    "attributes",
                    "schema_version",
                }
            ),
            "UnsignedTransactionIntent",
        )
        return cls(
            intent_id=value.get("intent_id", ""),
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            origin=AccountIdentity.from_dict(
                _as_mapping(value.get("origin", {}), "origin")
            ),
            signers=tuple(
                SignerRequirement.from_dict(item) for item in value.get("signers", ())
            ),
            transfers=tuple(
                TransferIntent.from_dict(item) for item in value.get("transfers", ())
            ),
            calls=tuple(CallIntent.from_dict(item) for item in value.get("calls", ())),
            expected_effects=tuple(
                ExpectedEffect.from_dict(item)
                for item in value.get("expected_effects", ())
            ),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            memo=value.get("memo", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION.identifier
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            self.to_dict(), collection_schema=UNSIGNED_INTENT_COLLECTION_SCHEMA
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_MODEL_DOMAIN}.unsigned-intent",
            collection_schema=UNSIGNED_INTENT_COLLECTION_SCHEMA,
        )


@dataclass(frozen=True, slots=True)
class SerializedTransactionCandidate:
    """Exact serialized transaction candidate bound to an unsigned intent."""

    candidate_id: str
    intent_id: str
    chain: ChainIdentity
    payload_digest: str
    encoding: str
    byte_length: int
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION.identifier

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(
            self, "payload_digest", _digest(self.payload_digest, "payload_digest")
        )
        object.__setattr__(self, "encoding", _text(self.encoding, "encoding"))
        object.__setattr__(
            self, "byte_length", _non_negative_int(self.byte_length, "byte_length")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "candidate_id": self.candidate_id,
            "chain": self.chain.to_dict(),
            "encoding": self.encoding,
            "intent_id": self.intent_id,
            "payload_digest": self.payload_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SerializedTransactionCandidate":
        value = _as_mapping(value, "SerializedTransactionCandidate")
        _known_fields(
            value,
            frozenset(
                {
                    "candidate_id",
                    "intent_id",
                    "chain",
                    "payload_digest",
                    "encoding",
                    "byte_length",
                    "attributes",
                    "schema_version",
                }
            ),
            "SerializedTransactionCandidate",
        )
        return cls(
            candidate_id=value.get("candidate_id", ""),
            intent_id=value.get("intent_id", ""),
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            payload_digest=value.get("payload_digest", ""),
            encoding=value.get("encoding", ""),
            byte_length=value.get("byte_length", 0),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION.identifier,
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_MODEL_DOMAIN}.serialized-candidate",
        )


# ---------------------------------------------------------------------------
# Contract artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContractArtifact:
    """Immutable contract/program/script artifact declaration."""

    artifact_id: str
    chain: ChainIdentity
    kind: ArtifactKind
    content_digest: str
    media_type: str
    byte_length: int
    content_cid: str = ""
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION.identifier

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(self, "kind", _enum(ArtifactKind, self.kind, "kind"))
        object.__setattr__(
            self, "content_digest", _digest(self.content_digest, "content_digest")
        )
        object.__setattr__(self, "media_type", _text(self.media_type, "media_type"))
        object.__setattr__(
            self, "byte_length", _non_negative_int(self.byte_length, "byte_length")
        )
        object.__setattr__(
            self, "content_cid", _text(self.content_cid, "content_cid", allow_empty=True)
        )
        object.__setattr__(self, "label", _text(self.label, "label", allow_empty=True))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "chain": self.chain.to_dict(),
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "kind": self.kind.value,
            "label": self.label,
            "media_type": self.media_type,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractArtifact":
        value = _as_mapping(value, "ContractArtifact")
        _known_fields(
            value,
            frozenset(
                {
                    "artifact_id",
                    "chain",
                    "kind",
                    "content_digest",
                    "media_type",
                    "byte_length",
                    "content_cid",
                    "label",
                    "attributes",
                    "schema_version",
                }
            ),
            "ContractArtifact",
        )
        return cls(
            artifact_id=value.get("artifact_id", ""),
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            kind=value.get("kind", ArtifactKind.OTHER.value),
            content_digest=value.get("content_digest", ""),
            media_type=value.get("media_type", ""),
            byte_length=value.get("byte_length", 0),
            content_cid=value.get("content_cid", ""),
            label=value.get("label", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION.identifier
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_MODEL_DOMAIN}.contract-artifact",
        )


# ---------------------------------------------------------------------------
# Observations, assumptions, completeness
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedTransaction:
    """Observed on-chain transaction facts (observation authority only)."""

    observation_id: str
    chain: ChainIdentity
    tx_digest: str
    coordinate: LedgerCoordinate
    finality: FinalityStatus
    retraction: RetractionStatus
    validity: ValidityWindow
    from_account: AccountIdentity | None = None
    to_account: AccountIdentity | None = None
    provenance: CryptoIRProvenance | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(self, "tx_digest", _digest(self.tx_digest, "tx_digest"))
        if not isinstance(self.coordinate, LedgerCoordinate):
            object.__setattr__(
                self,
                "coordinate",
                LedgerCoordinate.from_dict(_as_mapping(self.coordinate, "coordinate")),
            )
        object.__setattr__(
            self, "finality", _enum(FinalityStatus, self.finality, "finality")
        )
        object.__setattr__(
            self, "retraction", _enum(RetractionStatus, self.retraction, "retraction")
        )
        if not isinstance(self.validity, ValidityWindow):
            object.__setattr__(
                self,
                "validity",
                ValidityWindow.from_dict(_as_mapping(self.validity, "validity")),
            )
        if self.from_account is not None and not isinstance(
            self.from_account, AccountIdentity
        ):
            object.__setattr__(
                self,
                "from_account",
                AccountIdentity.from_dict(
                    _as_mapping(self.from_account, "from_account")
                ),
            )
        if self.to_account is not None and not isinstance(
            self.to_account, AccountIdentity
        ):
            object.__setattr__(
                self,
                "to_account",
                AccountIdentity.from_dict(_as_mapping(self.to_account, "to_account")),
            )
        if self.provenance is not None:
            if not isinstance(self.provenance, CryptoIRProvenance):
                object.__setattr__(
                    self,
                    "provenance",
                    CryptoIRProvenance.from_dict(
                        _as_mapping(self.provenance, "provenance")
                    ),
                )
            if self.provenance.authority.kind is not AuthorityKind.OBSERVATION:
                raise CryptoIRValidationError(
                    "ObservedTransaction provenance must have observation authority"
                )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain": self.chain.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "finality": self.finality.value,
            "from_account": None
            if self.from_account is None
            else self.from_account.to_dict(),
            "observation_id": self.observation_id,
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "retraction": self.retraction.value,
            "to_account": None if self.to_account is None else self.to_account.to_dict(),
            "tx_digest": self.tx_digest,
            "validity": self.validity.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObservedTransaction":
        value = _as_mapping(value, "ObservedTransaction")
        _known_fields(
            value,
            frozenset(
                {
                    "observation_id",
                    "chain",
                    "tx_digest",
                    "coordinate",
                    "finality",
                    "retraction",
                    "validity",
                    "from_account",
                    "to_account",
                    "provenance",
                    "attributes",
                }
            ),
            "ObservedTransaction",
        )
        from_raw = value.get("from_account")
        to_raw = value.get("to_account")
        prov_raw = value.get("provenance")
        return cls(
            observation_id=value.get("observation_id", ""),
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            tx_digest=value.get("tx_digest", ""),
            coordinate=LedgerCoordinate.from_dict(
                _as_mapping(value.get("coordinate", {}), "coordinate")
            ),
            finality=value.get("finality", FinalityStatus.UNKNOWN.value),
            retraction=value.get("retraction", RetractionStatus.UNKNOWN.value),
            validity=ValidityWindow.from_dict(
                _as_mapping(value.get("validity", {}), "validity")
            ),
            from_account=None
            if from_raw is None
            else AccountIdentity.from_dict(_as_mapping(from_raw, "from_account")),
            to_account=None
            if to_raw is None
            else AccountIdentity.from_dict(_as_mapping(to_raw, "to_account")),
            provenance=None
            if prov_raw is None
            else CryptoIRProvenance.from_dict(_as_mapping(prov_raw, "provenance")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class CryptoAssumption:
    """Explicit premise; declaring it does not establish truth or authority."""

    assumption_id: str
    statement: str
    source_refs: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.ASSUMPTION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assumption_id", _identifier(self.assumption_id, "assumption_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self, "source_refs", _unique_ids(self.source_refs, "source_refs")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "attributes": thaw_json(self.attributes),
            "source_refs": list(self.source_refs),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CryptoAssumption":
        value = _as_mapping(value, "CryptoAssumption")
        _known_fields(
            value,
            frozenset({"assumption_id", "statement", "source_refs", "attributes"}),
            "CryptoAssumption",
        )
        return cls(
            assumption_id=value.get("assumption_id", ""),
            statement=value.get("statement", ""),
            source_refs=tuple(value.get("source_refs", ())),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class CryptoExtension:
    """Namespaced extension; required unknown extensions fail closed."""

    extension_id: str
    vocabulary: str
    version: str
    payload: Any
    required: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "extension_id", _identifier(self.extension_id, "extension_id")
        )
        object.__setattr__(self, "vocabulary", _identifier(self.vocabulary, "vocabulary"))
        object.__setattr__(self, "version", _text(self.version, "version"))
        if not isinstance(self.required, bool):
            raise CryptoIRValidationError("extension required must be a boolean")
        object.__setattr__(self, "payload", _payload(self.payload))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "extension_id": self.extension_id,
            "payload": thaw_json(self.payload),
            "required": self.required,
            "version": self.version,
            "vocabulary": self.vocabulary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CryptoExtension":
        value = _as_mapping(value, "CryptoExtension")
        _known_fields(
            value,
            frozenset(
                {
                    "extension_id",
                    "vocabulary",
                    "version",
                    "payload",
                    "required",
                    "attributes",
                }
            ),
            "CryptoExtension",
        )
        return cls(
            extension_id=value.get("extension_id", ""),
            vocabulary=value.get("vocabulary", ""),
            version=value.get("version", ""),
            payload=value.get("payload"),
            required=value.get("required", False),
            attributes=value.get("attributes", {}),
        )


COMPLETENESS_RECEIPT_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/covered_ranges": CollectionSemantics.ORDERED,
        "/missing_ranges": CollectionSemantics.ORDERED,
        "/provider_ids": CollectionSemantics.SET_LIKE,
        "/assumption_ids": CollectionSemantics.SET_LIKE,
        "/extensions": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class CompletenessReceipt:
    """Observation of acquisition/observation completeness for a scope.

    Carries finality, completeness status, validity, and retraction so later
    decisions can fail closed on partial or stale coverage.  This is not
    authorization and cannot authorize a transaction.
    """

    receipt_id: str
    chain: ChainIdentity
    scope: str
    completeness: CompletenessStatus
    finality: FinalityStatus
    validity: ValidityWindow
    retraction: RetractionStatus
    covered_ranges: tuple[LedgerCoordinate, ...] = ()
    missing_ranges: tuple[LedgerCoordinate, ...] = ()
    provider_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    extensions: tuple[CryptoExtension, ...] = ()
    accepted_extension_vocabularies: tuple[str, ...] = ()
    provenance: CryptoIRProvenance | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION.identifier

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(self, "scope", _text(self.scope, "scope"))
        object.__setattr__(
            self,
            "completeness",
            _enum(CompletenessStatus, self.completeness, "completeness"),
        )
        object.__setattr__(
            self, "finality", _enum(FinalityStatus, self.finality, "finality")
        )
        if not isinstance(self.validity, ValidityWindow):
            object.__setattr__(
                self,
                "validity",
                ValidityWindow.from_dict(_as_mapping(self.validity, "validity")),
            )
        object.__setattr__(
            self, "retraction", _enum(RetractionStatus, self.retraction, "retraction")
        )
        object.__setattr__(
            self,
            "covered_ranges",
            _sequence_of(
                self.covered_ranges,
                LedgerCoordinate,
                "covered_ranges",
                from_dict=LedgerCoordinate.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "missing_ranges",
            _sequence_of(
                self.missing_ranges,
                LedgerCoordinate,
                "missing_ranges",
                from_dict=LedgerCoordinate.from_dict,
            ),
        )
        object.__setattr__(
            self, "provider_ids", _unique_ids(self.provider_ids, "provider_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self,
            "extensions",
            _sequence_of(
                self.extensions,
                CryptoExtension,
                "extensions",
                from_dict=CryptoExtension.from_dict,
            ),
        )
        accepted = _unique_ids(
            self.accepted_extension_vocabularies, "accepted_extension_vocabularies"
        )
        object.__setattr__(self, "accepted_extension_vocabularies", accepted)
        for extension in self.extensions:
            if extension.required and extension.vocabulary not in accepted:
                raise CryptoIRValidationError(
                    "unknown required extension vocabulary fails closed: "
                    f"{extension.vocabulary}"
                )
        if self.provenance is not None:
            if not isinstance(self.provenance, CryptoIRProvenance):
                object.__setattr__(
                    self,
                    "provenance",
                    CryptoIRProvenance.from_dict(
                        _as_mapping(self.provenance, "provenance")
                    ),
                )
            if self.provenance.authority.kind is not AuthorityKind.OBSERVATION:
                raise CryptoIRValidationError(
                    "CompletenessReceipt provenance must have observation authority"
                )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_extension_vocabularies": list(
                self.accepted_extension_vocabularies
            ),
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "chain": self.chain.to_dict(),
            "completeness": self.completeness.value,
            "covered_ranges": [item.to_dict() for item in self.covered_ranges],
            "extensions": [item.to_dict() for item in self.extensions],
            "finality": self.finality.value,
            "missing_ranges": [item.to_dict() for item in self.missing_ranges],
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "provider_ids": list(self.provider_ids),
            "receipt_id": self.receipt_id,
            "retraction": self.retraction.value,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "validity": self.validity.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompletenessReceipt":
        value = _as_mapping(value, "CompletenessReceipt")
        _known_fields(
            value,
            frozenset(
                {
                    "receipt_id",
                    "chain",
                    "scope",
                    "completeness",
                    "finality",
                    "validity",
                    "retraction",
                    "covered_ranges",
                    "missing_ranges",
                    "provider_ids",
                    "assumption_ids",
                    "extensions",
                    "accepted_extension_vocabularies",
                    "provenance",
                    "attributes",
                    "schema_version",
                }
            ),
            "CompletenessReceipt",
        )
        prov_raw = value.get("provenance")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            scope=value.get("scope", ""),
            completeness=value.get("completeness", CompletenessStatus.UNKNOWN.value),
            finality=value.get("finality", FinalityStatus.UNKNOWN.value),
            validity=ValidityWindow.from_dict(
                _as_mapping(value.get("validity", {}), "validity")
            ),
            retraction=value.get("retraction", RetractionStatus.UNKNOWN.value),
            covered_ranges=tuple(
                LedgerCoordinate.from_dict(item)
                for item in value.get("covered_ranges", ())
            ),
            missing_ranges=tuple(
                LedgerCoordinate.from_dict(item)
                for item in value.get("missing_ranges", ())
            ),
            provider_ids=tuple(value.get("provider_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            extensions=tuple(
                CryptoExtension.from_dict(item) for item in value.get("extensions", ())
            ),
            accepted_extension_vocabularies=tuple(
                value.get("accepted_extension_vocabularies", ())
            ),
            provenance=None
            if prov_raw is None
            else CryptoIRProvenance.from_dict(_as_mapping(prov_raw, "provenance")),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION.identifier,
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            self.to_dict(),
            collection_schema=COMPLETENESS_RECEIPT_COLLECTION_SCHEMA,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_MODEL_DOMAIN}.completeness-receipt",
            collection_schema=COMPLETENESS_RECEIPT_COLLECTION_SCHEMA,
        )


# ---------------------------------------------------------------------------
# Result / authorization placeholders (separate layers; not elevatable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisResultRef:
    """Reference to an analysis result; not itself a proof or authorization."""

    result_id: str
    kind: str
    subject_identity: str
    outcome: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", _identifier(self.result_id, "result_id"))
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        object.__setattr__(
            self, "subject_identity", _text(self.subject_identity, "subject_identity")
        )
        object.__setattr__(self, "outcome", _text(self.outcome, "outcome"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "kind": self.kind,
            "outcome": self.outcome,
            "result_id": self.result_id,
            "subject_identity": self.subject_identity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisResultRef":
        value = _as_mapping(value, "AnalysisResultRef")
        _known_fields(
            value,
            frozenset(
                {"result_id", "kind", "subject_identity", "outcome", "attributes"}
            ),
            "AnalysisResultRef",
        )
        return cls(
            result_id=value.get("result_id", ""),
            kind=value.get("kind", ""),
            subject_identity=value.get("subject_identity", ""),
            outcome=value.get("outcome", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationDecisionRef:
    """Reference to a transaction authorization decision (authorization layer)."""

    decision_id: str
    candidate_id: str
    verdict: str
    policy_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.AUTHORIZATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "verdict", _text(self.verdict, "verdict"))
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "candidate_id": self.candidate_id,
            "decision_id": self.decision_id,
            "policy_id": self.policy_id,
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorizationDecisionRef":
        value = _as_mapping(value, "AuthorizationDecisionRef")
        _known_fields(
            value,
            frozenset(
                {
                    "decision_id",
                    "candidate_id",
                    "verdict",
                    "policy_id",
                    "attributes",
                }
            ),
            "AuthorizationDecisionRef",
        )
        return cls(
            decision_id=value.get("decision_id", ""),
            candidate_id=value.get("candidate_id", ""),
            verdict=value.get("verdict", ""),
            policy_id=value.get("policy_id", ""),
            attributes=value.get("attributes", {}),
        )


def record_layer(record: Any) -> AuthorityKind:
    """Return the fixed authority layer of a Crypto IR record type."""

    layer = getattr(type(record), "LAYER", None)
    if not isinstance(layer, AuthorityKind):
        raise CryptoIRValidationError(
            f"{type(record).__name__} does not declare a record layer"
        )
    return layer


def refuse_authority_elevation(source: Any, target_layer: AuthorityKind | str) -> None:
    """Fail closed when converting *source* would elevate its authority layer."""

    source_layer = record_layer(source)
    try:
        assert_authority_not_elevated(source_layer, target_layer)
    except CryptoIRProvenanceError as exc:
        raise CryptoIRValidationError(str(exc)) from exc


def observation_provenance(
    *,
    producer_id: str,
    observed_at: str,
    finality: FinalityStatus | str,
    validity_start: str = "",
    validity_end: str = "",
    retraction_status: RetractionStatus | str = RetractionStatus.NOT_RETRACTED,
    reorg_depth: int | None = None,
) -> CryptoIRProvenance:
    """Build observation-layer provenance with required observation bindings."""

    finality_value = (
        finality.value if isinstance(finality, FinalityStatus) else str(finality)
    )
    retraction_value = (
        retraction_status.value
        if isinstance(retraction_status, RetractionStatus)
        else str(retraction_status)
    )
    return CryptoIRProvenance(
        authority=AuthorityBinding(kind=AuthorityKind.OBSERVATION),
        producer_id=producer_id,
        observation=ObservationProvenance(
            observed_at=observed_at,
            finality=finality_value,
            validity_start=validity_start,
            validity_end=validity_end,
            retraction_status=retraction_value,
            reorg_depth=reorg_depth,
        ),
    )


__all__ = [
    "COMPLETENESS_RECEIPT_COLLECTION_SCHEMA",
    "CRYPTO_IR_MODEL_DOMAIN",
    "UNSIGNED_INTENT_COLLECTION_SCHEMA",
    "AccountIdentity",
    "AnalysisResultRef",
    "ArtifactKind",
    "AssetIdentity",
    "AuthorizationDecisionRef",
    "CallIntent",
    "ChainIdentity",
    "CompletenessReceipt",
    "CompletenessStatus",
    "ContractArtifact",
    "CryptoAssumption",
    "CryptoExtension",
    "CryptoIRValidationError",
    "ExactAmount",
    "ExpectedEffect",
    "FinalityStatus",
    "LedgerCoordinate",
    "ObservedTransaction",
    "RetractionStatus",
    "SerializedTransactionCandidate",
    "SignerRequirement",
    "TimeBoundedEpoch",
    "TransferIntent",
    "UnsignedTransactionIntent",
    "ValidityWindow",
    "WalletDescriptor",
    "observation_provenance",
    "record_layer",
    "refuse_authority_elevation",
]
