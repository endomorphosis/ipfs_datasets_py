"""Immutable, chain-neutral models for wallet and public-ledger datasets.

Only semantics proven to be shared by every supported chain live here.
Chain-native details belong in :class:`VersionedExtension` values or in
content-addressed raw payloads referenced by :class:`RawPayloadRef`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any, ClassVar

from .canonical import (
    canonical_json,
    deterministic_id,
    format_datetime,
    freeze_json,
    thaw_json,
)


LEDGER_RECORD_SCHEMA_VERSION = "wallet-ledger-record-v1"
EXPORT_MANIFEST_SCHEMA_VERSION = "wallet-export-manifest-v1"
CHAIN_REF_SCHEMA_VERSION = "wallet-chain-ref-v1"
ACCOUNT_REF_SCHEMA_VERSION = "wallet-account-ref-v1"
ASSET_REF_SCHEMA_VERSION = "wallet-asset-ref-v1"
CURSOR_SCHEMA_VERSION = "wallet-ledger-cursor-v1"

_DECIMAL_INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_DIGEST = re.compile(r"^[a-z0-9][a-z0-9._-]*:[A-Za-z0-9_-]+$")
_CID = re.compile(r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7][a-z2-7]+)$")
_URN_ID = re.compile(r"^urn:wallet:[a-z][a-z0-9_-]*:sha256:[0-9a-f]{64}$")

# Free-form values cross durable and representational trust boundaries.  Keep
# this policy deliberately smaller than a general secret scanner: strong
# credential formats and unambiguous field names are rejected, while ordinary
# public-ledger values such as hashes, signatures, ``token`` and ``token_id``
# remain valid.
SECRET_SAFE_MAX_DEPTH = 32
SECRET_SAFE_MAX_NODES = 10_000
SECRET_SAFE_MAX_COLLECTION_ITEMS = 2_048
SECRET_SAFE_MAX_STRING_CHARS = 1_048_576

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_FIELD_SEPARATOR = re.compile(r"[^a-z0-9]+")
_SECRET_FIELD_WORDS = frozenset(
    {
        "authorization",
        "bearer",
        "mnemonic",
        "passphrase",
        "passwd",
        "password",
        "secret",
    }
)
_SECRET_FIELD_NAMES = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "api_secret",
        "auth_token",
        "client_secret",
        "credential",
        "credentials",
        "private_key",
        "provider_secret",
        "recovery_phrase",
        "recovery_seed",
        "refresh_token",
        "seed",
        "seed_phrase",
        "session_token",
        "signing_key",
        "signing_material",
        "user_token",
        "wallet_seed",
    }
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(
        r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
        r"github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9])"
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
        r"AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9])"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|passphrase|api[_-]?key|private[_-]?key|"
        r"secret|mnemonic|seed[_ -]?phrase)\s*[:=]\s*\S{4,}"
    ),
    re.compile(r"(?i)^(?:vault|keyring|secret|env|file)://"),
    re.compile(r"(?i)^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
    # Catches long sentinel-style tokens without treating paths or prose that
    # merely mention a security test as concrete credentials.
    re.compile(
        r"(?i)^[a-z0-9][a-z0-9_-]{15,}-(?:secret|password|passwd|passphrase)$"
    ),
)


def _normalized_field_name(value: str) -> str:
    separated = _CAMEL_BOUNDARY.sub("_", value).casefold()
    return _FIELD_SEPARATOR.sub("_", separated).strip("_")


def _is_secret_field(value: str) -> bool:
    normalized = _normalized_field_name(value)
    if normalized in _SECRET_FIELD_NAMES:
        return True
    return bool(_SECRET_FIELD_WORDS.intersection(normalized.split("_")))


def _is_concrete_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def ensure_secret_safe(value: Any) -> None:
    """Reject secret-shaped or unbounded values before wallet serialization.

    The traversal has explicit depth, node, collection, and string budgets so
    an untrusted extension, cursor, warning, or metadata object cannot turn
    secret inspection into an unbounded operation.  Errors intentionally omit
    field paths and values because both are attacker-controlled and may
    themselves contain the secret.
    """

    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > SECRET_SAFE_MAX_DEPTH or nodes > SECRET_SAFE_MAX_NODES:
            raise ValueError("wallet serialization security policy limit exceeded")

        if isinstance(item, str):
            if len(item) > SECRET_SAFE_MAX_STRING_CHARS:
                raise ValueError("wallet serialization security policy limit exceeded")
            if _is_concrete_secret(item):
                raise ValueError(
                    "wallet serialization rejects concrete secret values"
                )
            return

        if isinstance(item, Mapping):
            if len(item) > SECRET_SAFE_MAX_COLLECTION_ITEMS:
                raise ValueError("wallet serialization security policy limit exceeded")
            for key, child in item.items():
                if isinstance(key, str):
                    if len(key) > SECRET_SAFE_MAX_STRING_CHARS:
                        raise ValueError(
                            "wallet serialization security policy limit exceeded"
                        )
                    if _is_secret_field(key) or _is_concrete_secret(key):
                        raise ValueError(
                            "wallet serialization rejects secret-shaped fields"
                        )
                visit(child, depth + 1)
            return

        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray, memoryview)
        ):
            if len(item) > SECRET_SAFE_MAX_COLLECTION_ITEMS:
                raise ValueError("wallet serialization security policy limit exceeded")
            for child in item:
                visit(child, depth + 1)
            return

        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            visit(to_dict(), depth + 1)

    visit(value, 0)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


class Finality(StrEnum):
    """Portable lifecycle states without collapsing uncertainty or corrections."""

    UNKNOWN = "unknown"
    OBSERVED = "observed"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SAFE = "safe"
    FINALIZED = "finalized"
    ORPHANED = "orphaned"
    REVERTED = "reverted"
    FAILED = "failed"


class TransactionStatus(StrEnum):
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AccountKind(StrEnum):
    UNKNOWN = "unknown"
    ADDRESS = "address"
    CONTRACT = "contract"
    SCRIPT = "script"
    TOKEN_ACCOUNT = "token_account"
    PROTOCOL_SUBJECT = "protocol_subject"


class AssetKind(StrEnum):
    UNKNOWN = "unknown"
    NATIVE = "native"
    FUNGIBLE_TOKEN = "fungible_token"
    NON_FUNGIBLE_TOKEN = "non_fungible_token"
    MULTI_TOKEN = "multi_token"


class TransferKind(StrEnum):
    UNKNOWN = "unknown"
    NATIVE = "native"
    TOKEN = "token"
    FEE = "fee"
    REWARD = "reward"
    MINT = "mint"
    BURN = "burn"


class ExportStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RawPayloadPolicy(StrEnum):
    OMITTED = "omitted"
    REFERENCED = "referenced"
    SEPARATELY_ENCRYPTED = "separately_encrypted"


@dataclass(frozen=True, slots=True)
class VersionedExtension:
    """A namespaced, explicitly versioned home for chain-specific fields."""

    schema_version: str
    data: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _required(self.schema_version, "extension schema_version")
        if not isinstance(self.data, Mapping):
            raise ValueError("extension data must be a mapping")
        ensure_secret_safe(
            {"schema_version": self.schema_version, "data": self.data}
        )
        frozen = freeze_json(self.data)
        ensure_secret_safe(frozen)
        object.__setattr__(self, "data", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "data": thaw_json(self.data),
        }


def _extensions(
    value: Mapping[str, VersionedExtension],
) -> Mapping[str, VersionedExtension]:
    if not isinstance(value, Mapping):
        raise ValueError("extensions must be a mapping")
    result: dict[str, VersionedExtension] = {}
    for namespace, extension in value.items():
        _required(namespace, "extension namespace")
        ensure_secret_safe({namespace: None})
        if not isinstance(extension, VersionedExtension):
            raise ValueError("extensions must contain VersionedExtension values")
        result[namespace] = extension
    return MappingProxyType(result)


def _extension_dict(
    value: Mapping[str, VersionedExtension],
) -> dict[str, dict[str, Any]]:
    return {namespace: extension.to_dict() for namespace, extension in value.items()}


@dataclass(frozen=True, slots=True)
class ChainRef:
    """Network and genesis-bound chain identity."""

    namespace: str
    network: str
    chain_id: str
    genesis_hash: str
    schema_version: str = field(default=CHAIN_REF_SCHEMA_VERSION, init=False)
    chain_ref_id: str = field(init=False)

    def __post_init__(self) -> None:
        _required(self.namespace, "namespace")
        _required(self.network, "network")
        _required(self.chain_id, "chain_id")
        _required(self.genesis_hash, "genesis_hash")
        object.__setattr__(
            self,
            "chain_ref_id",
            deterministic_id("chain", self.identity_dict()),
        )

    def identity_dict(self) -> dict[str, str]:
        return {
            "chain_namespace": self.namespace,
            "network": self.network,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
        }

    @property
    def chain_namespace(self) -> str:
        """The normalized serialized name for :attr:`namespace`."""

        return self.namespace

    @property
    def genesis_id(self) -> str:
        """Chain-neutral alias for the genesis anchor."""

        return self.genesis_hash

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "chain_ref_id": self.chain_ref_id,
            **self.identity_dict(),
        }


@dataclass(frozen=True, slots=True)
class AccountRef:
    """A canonical account/address identity scoped to one exact chain."""

    chain: ChainRef
    address: str
    kind: AccountKind = AccountKind.ADDRESS
    schema_version: str = field(default=ACCOUNT_REF_SCHEMA_VERSION, init=False)
    account_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainRef):
            raise ValueError("chain must be a ChainRef")
        _required(self.address, "address")
        if not isinstance(self.kind, AccountKind):
            raise ValueError("kind must be an AccountKind")
        object.__setattr__(
            self,
            "account_id",
            deterministic_id(
                "account",
                {
                    "chain": self.chain.identity_dict(),
                    "address": self.address,
                    "kind": self.kind,
                },
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "chain": self.chain.to_dict(),
            "address": self.address,
            "kind": self.kind.value,
        }

    @property
    def canonical_address(self) -> str:
        """The chain normalizer's canonical address supplied at construction."""

        return self.address


@dataclass(frozen=True, slots=True)
class AssetRef:
    """A native or issued asset identity with explicit display precision."""

    chain: ChainRef
    asset_namespace: str
    asset_reference: str
    decimals: int
    kind: AssetKind = AssetKind.UNKNOWN
    symbol: str | None = None
    schema_version: str = field(default=ASSET_REF_SCHEMA_VERSION, init=False)
    asset_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainRef):
            raise ValueError("chain must be a ChainRef")
        _required(self.asset_namespace, "asset_namespace")
        _required(self.asset_reference, "asset_reference")
        if not isinstance(self.kind, AssetKind):
            raise ValueError("kind must be an AssetKind")
        _non_negative(self.decimals, "decimals")
        if self.decimals > 255:
            raise ValueError("decimals must not exceed 255")
        if self.symbol is not None:
            _required(self.symbol, "symbol")
        object.__setattr__(
            self,
            "asset_id",
            deterministic_id(
                "asset",
                {
                    "chain": self.chain.identity_dict(),
                    "asset_namespace": self.asset_namespace,
                    "asset_reference": self.asset_reference,
                },
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "chain": self.chain.to_dict(),
            "asset_namespace": self.asset_namespace,
            "asset_reference": self.asset_reference,
            "decimals": self.decimals,
            "kind": self.kind.value,
        }
        if self.symbol is not None:
            result["symbol"] = self.symbol
        return result


@dataclass(frozen=True, slots=True)
class ExactAmount:
    """An exact signed base-unit quantity and its display precision."""

    base_units: str
    decimals: int

    def __post_init__(self) -> None:
        if not isinstance(self.base_units, str) or not _DECIMAL_INTEGER.fullmatch(
            self.base_units
        ):
            raise ValueError("base_units must be a canonical decimal integer string")
        _non_negative(self.decimals, "decimals")
        if self.decimals > 255:
            raise ValueError("decimals must not exceed 255")

    @classmethod
    def from_int(cls, value: int, *, decimals: int) -> "ExactAmount":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("amount must be an integer")
        return cls(str(value), decimals)

    def to_dict(self) -> dict[str, Any]:
        return {"base_units": self.base_units, "decimals": self.decimals}


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    """A chain-neutral block, slot, or ledger coordinate."""

    sequence: int | None
    hash: str | None = None
    transaction_index: int | None = None
    event_index: int | None = None

    def __post_init__(self) -> None:
        if self.sequence is not None:
            _non_negative(self.sequence, "sequence")
        if self.hash is not None:
            _required(self.hash, "hash")
        if self.transaction_index is not None:
            _non_negative(self.transaction_index, "transaction_index")
        if self.event_index is not None:
            _non_negative(self.event_index, "event_index")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "hash": self.hash,
            "transaction_index": self.transaction_index,
            "event_index": self.event_index,
        }


@dataclass(frozen=True, slots=True)
class RawPayloadRef:
    """A content reference; raw provider payload bytes never enter a record."""

    digest: str | None = None
    cid: str | None = None
    media_type: str = "application/json"
    byte_length: int | None = None

    def __post_init__(self) -> None:
        if self.digest is None and self.cid is None:
            raise ValueError("raw payload reference requires a digest or CID")
        if self.digest is not None and not _DIGEST.fullmatch(self.digest):
            raise ValueError("digest must be tagged as algorithm:value")
        if self.cid is not None and not _CID.fullmatch(self.cid):
            raise ValueError("cid must be a CIDv0 or lowercase-base32 CIDv1")
        _required(self.media_type, "media_type")
        if self.byte_length is not None:
            _non_negative(self.byte_length, "byte_length")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"media_type": self.media_type}
        if self.digest is not None:
            result["digest"] = self.digest
        if self.cid is not None:
            result["cid"] = self.cid
        if self.byte_length is not None:
            result["byte_length"] = self.byte_length
        return result


@dataclass(frozen=True, slots=True)
class Provenance:
    """Mandatory source and observation metadata for a normalized record."""

    provider: str
    provider_kind: str
    request_id: str
    scope: str
    observed_at: datetime
    raw_payload: RawPayloadRef | None = None

    def __post_init__(self) -> None:
        _required(self.provider, "provider")
        _required(self.provider_kind, "provider_kind")
        _required(self.request_id, "request_id")
        _required(self.scope, "scope")
        _aware(self.observed_at, "observed_at")

    def source_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "provider_kind": self.provider_kind,
            "request_id": self.request_id,
            "scope": self.scope,
        }
        if self.raw_payload is not None:
            result["raw_payload"] = self.raw_payload.to_dict()
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.source_dict(),
            "observed_at": format_datetime(self.observed_at),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerRecord:
    """Common immutable envelope implemented by every normalized record."""

    chain: ChainRef
    provenance: Provenance
    ledger_position: LedgerPosition
    finality: Finality
    extensions: Mapping[str, VersionedExtension] = field(
        default_factory=dict,
        hash=False,
    )
    record_id: str = field(init=False)

    record_type: ClassVar[str] = "ledger_record"
    schema_version: ClassVar[str] = LEDGER_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainRef):
            raise ValueError("chain must be a ChainRef")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be Provenance")
        if not isinstance(self.ledger_position, LedgerPosition):
            raise ValueError("ledger_position must be LedgerPosition")
        if not isinstance(self.finality, Finality):
            raise ValueError("finality must be a Finality value")
        object.__setattr__(self, "extensions", _extensions(self.extensions))
        record_id = deterministic_id(
            self.record_type,
            {
                "chain": self.chain.identity_dict(),
                "coordinates": self.identity_coordinates(),
            },
        )
        if not _URN_ID.fullmatch(record_id):
            raise AssertionError("deterministic ID encoder returned an invalid ID")
        object.__setattr__(self, "record_id", record_id)

    def identity_coordinates(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def _common_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "record_type": self.record_type,
            **self.chain.identity_dict(),
            "observed_at": format_datetime(self.provenance.observed_at),
            "source": self.provenance.source_dict(),
            "ledger_position": self.ledger_position.to_dict(),
            "finality": self.finality.value,
            "extensions": _extension_dict(self.extensions),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


def _same_chain(record: LedgerRecord, *refs: AccountRef | AssetRef | None) -> None:
    for ref in refs:
        if ref is not None:
            if not isinstance(ref, (AccountRef, AssetRef)):
                raise ValueError("record references must be AccountRef or AssetRef values")
            if ref.chain != record.chain:
                raise ValueError(
                    "account and asset references must match the record chain"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockRecord(LedgerRecord):
    record_type: ClassVar[str] = "block"

    block_hash: str
    parent_hash: str | None
    block_time: datetime | None = None
    transaction_count: int | None = None

    def __post_init__(self) -> None:
        _required(self.block_hash, "block_hash")
        if self.ledger_position.sequence is None:
            raise ValueError("block ledger position must have a sequence")
        if (
            self.ledger_position.hash is not None
            and self.ledger_position.hash != self.block_hash
        ):
            raise ValueError("block_hash must match the ledger position hash")
        if self.parent_hash is not None:
            _required(self.parent_hash, "parent_hash")
        if self.block_time is not None:
            _aware(self.block_time, "block_time")
        if self.transaction_count is not None:
            _non_negative(self.transaction_count, "transaction_count")
        super(BlockRecord, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {
            "sequence": self.ledger_position.sequence,
            "block_hash": self.block_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self._common_dict(),
            "block_hash": self.block_hash,
            "parent_hash": self.parent_hash,
            "transaction_count": self.transaction_count,
        }
        if self.block_time is not None:
            result["block_time"] = format_datetime(self.block_time)
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class TransactionRecord(LedgerRecord):
    record_type: ClassVar[str] = "transaction"

    transaction_hash: str
    status: TransactionStatus
    participants: tuple[AccountRef, ...] = ()
    fee: ExactAmount | None = None
    block_time: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.transaction_hash, "transaction_hash")
        if not isinstance(self.status, TransactionStatus):
            raise ValueError("status must be a TransactionStatus")
        if any(not isinstance(item, AccountRef) for item in self.participants):
            raise ValueError("participants must contain AccountRef values")
        object.__setattr__(self, "participants", tuple(self.participants))
        for participant in self.participants:
            _same_chain(self, participant)
        if self.fee is not None and not isinstance(self.fee, ExactAmount):
            raise ValueError("fee must be ExactAmount")
        if self.block_time is not None:
            _aware(self.block_time, "block_time")
        super(TransactionRecord, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {"transaction_hash": self.transaction_hash}

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self._common_dict(),
            "transaction_hash": self.transaction_hash,
            "status": self.status.value,
            "participants": [item.to_dict() for item in self.participants],
        }
        if self.fee is not None:
            result["fee"] = self.fee.to_dict()
        if self.block_time is not None:
            result["block_time"] = format_datetime(self.block_time)
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class TransferRecord(LedgerRecord):
    record_type: ClassVar[str] = "transfer"

    transaction_hash: str
    transfer_index: int
    asset: AssetRef
    amount: ExactAmount
    source_account: AccountRef | None = None
    destination_account: AccountRef | None = None
    transfer_kind: TransferKind = TransferKind.UNKNOWN

    def __post_init__(self) -> None:
        _required(self.transaction_hash, "transaction_hash")
        _non_negative(self.transfer_index, "transfer_index")
        if not isinstance(self.transfer_kind, TransferKind):
            raise ValueError("transfer_kind must be a TransferKind")
        if not isinstance(self.asset, AssetRef):
            raise ValueError("asset must be an AssetRef")
        if not isinstance(self.amount, ExactAmount):
            raise ValueError("amount must be ExactAmount")
        if self.amount.decimals != self.asset.decimals:
            raise ValueError("amount decimals must match asset decimals")
        if self.amount.base_units.startswith("-"):
            raise ValueError("transfer amount must not be negative")
        _same_chain(self, self.asset, self.source_account, self.destination_account)
        super(TransferRecord, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {
            "transaction_hash": self.transaction_hash,
            "transfer_index": self.transfer_index,
        }

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self._common_dict(),
            "transaction_hash": self.transaction_hash,
            "transfer_index": self.transfer_index,
            "asset": self.asset.to_dict(),
            "amount": self.amount.to_dict(),
            "transfer_kind": self.transfer_kind.value,
        }
        if self.source_account is not None:
            result["source_account"] = self.source_account.to_dict()
        if self.destination_account is not None:
            result["destination_account"] = self.destination_account.to_dict()
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class BalanceSnapshot(LedgerRecord):
    record_type: ClassVar[str] = "balance"

    account: AccountRef
    asset: AssetRef
    amount: ExactAmount

    def __post_init__(self) -> None:
        if not isinstance(self.account, AccountRef):
            raise ValueError("account must be an AccountRef")
        if not isinstance(self.asset, AssetRef):
            raise ValueError("asset must be an AssetRef")
        if not isinstance(self.amount, ExactAmount):
            raise ValueError("amount must be ExactAmount")
        if self.amount.decimals != self.asset.decimals:
            raise ValueError("amount decimals must match asset decimals")
        _same_chain(self, self.account, self.asset)
        super(BalanceSnapshot, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {
            "account_id": self.account.account_id,
            "asset_id": self.asset.asset_id,
            "ledger_position": self.ledger_position,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._common_dict(),
            "account": self.account.to_dict(),
            "asset": self.asset.to_dict(),
            "amount": self.amount.to_dict(),
        }


BalanceRecord = BalanceSnapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class UTXORecord(LedgerRecord):
    record_type: ClassVar[str] = "utxo"

    transaction_hash: str
    output_index: int
    asset: AssetRef
    amount: ExactAmount
    owner: AccountRef | None = None
    spent_by_transaction_hash: str | None = None

    def __post_init__(self) -> None:
        _required(self.transaction_hash, "transaction_hash")
        _non_negative(self.output_index, "output_index")
        if not isinstance(self.asset, AssetRef):
            raise ValueError("asset must be an AssetRef")
        if not isinstance(self.amount, ExactAmount):
            raise ValueError("amount must be ExactAmount")
        if self.amount.decimals != self.asset.decimals:
            raise ValueError("amount decimals must match asset decimals")
        if self.amount.base_units.startswith("-"):
            raise ValueError("UTXO amount must not be negative")
        if self.spent_by_transaction_hash is not None:
            _required(self.spent_by_transaction_hash, "spent_by_transaction_hash")
        _same_chain(self, self.asset, self.owner)
        super(UTXORecord, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {
            "transaction_hash": self.transaction_hash,
            "output_index": self.output_index,
        }

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self._common_dict(),
            "transaction_hash": self.transaction_hash,
            "output_index": self.output_index,
            "asset": self.asset.to_dict(),
            "amount": self.amount.to_dict(),
        }
        if self.owner is not None:
            result["owner"] = self.owner.to_dict()
        if self.spent_by_transaction_hash is not None:
            result["spent_by_transaction_hash"] = self.spent_by_transaction_hash
        return result


UtxoRecord = UTXORecord


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenAccountRecord(LedgerRecord):
    record_type: ClassVar[str] = "token_account"

    token_account: AccountRef
    owner: AccountRef | None
    asset: AssetRef
    amount: ExactAmount

    def __post_init__(self) -> None:
        if not isinstance(self.token_account, AccountRef):
            raise ValueError("token_account must be an AccountRef")
        if self.token_account.kind is not AccountKind.TOKEN_ACCOUNT:
            raise ValueError("token_account must have kind token_account")
        if self.owner is not None and not isinstance(self.owner, AccountRef):
            raise ValueError("owner must be an AccountRef")
        if not isinstance(self.asset, AssetRef):
            raise ValueError("asset must be an AssetRef")
        if not isinstance(self.amount, ExactAmount):
            raise ValueError("amount must be ExactAmount")
        if self.amount.decimals != self.asset.decimals:
            raise ValueError("amount decimals must match asset decimals")
        _same_chain(self, self.token_account, self.owner, self.asset)
        super(TokenAccountRecord, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {
            "token_account_id": self.token_account.account_id,
            "asset_id": self.asset.asset_id,
            "ledger_position": self.ledger_position,
        }

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self._common_dict(),
            "token_account": self.token_account.to_dict(),
            "asset": self.asset.to_dict(),
            "amount": self.amount.to_dict(),
        }
        if self.owner is not None:
            result["owner"] = self.owner.to_dict()
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractEventRecord(LedgerRecord):
    record_type: ClassVar[str] = "contract_event"

    transaction_hash: str
    event_index: int
    contract: AccountRef
    event_signature: str | None = None
    topics: tuple[str, ...] = ()
    data_ref: RawPayloadRef | None = None

    def __post_init__(self) -> None:
        _required(self.transaction_hash, "transaction_hash")
        _non_negative(self.event_index, "event_index")
        if not isinstance(self.contract, AccountRef):
            raise ValueError("contract must be an AccountRef")
        if self.contract.kind is not AccountKind.CONTRACT:
            raise ValueError("contract must have kind contract")
        if self.event_signature is not None:
            _required(self.event_signature, "event_signature")
        for topic in self.topics:
            _required(topic, "topic")
        object.__setattr__(self, "topics", tuple(self.topics))
        if (
            self.ledger_position.event_index is not None
            and self.ledger_position.event_index != self.event_index
        ):
            raise ValueError("event_index must match the ledger position event index")
        _same_chain(self, self.contract)
        super(ContractEventRecord, self).__post_init__()

    def identity_coordinates(self) -> Mapping[str, Any]:
        return {
            "transaction_hash": self.transaction_hash,
            "event_index": self.event_index,
        }

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self._common_dict(),
            "transaction_hash": self.transaction_hash,
            "event_index": self.event_index,
            "contract": self.contract.to_dict(),
            "topics": list(self.topics),
        }
        if self.event_signature is not None:
            result["event_signature"] = self.event_signature
        if self.data_ref is not None:
            result["data_ref"] = self.data_ref.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class LedgerCursor:
    """Hash-anchored checkpoint identity for one exact scan scope."""

    chain: ChainRef
    provider: str
    scope: str
    normalized_schema_major: int
    normalizer_version: str
    position: LedgerPosition
    revision: str
    continuation_token: str | None = None
    schema_version: str = field(default=CURSOR_SCHEMA_VERSION, init=False)
    cursor_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainRef):
            raise ValueError("chain must be a ChainRef")
        if not isinstance(self.position, LedgerPosition):
            raise ValueError("position must be a LedgerPosition")
        _required(self.provider, "provider")
        _required(self.scope, "scope")
        _non_negative(self.normalized_schema_major, "normalized_schema_major")
        if self.normalized_schema_major == 0:
            raise ValueError("normalized_schema_major must be positive")
        _required(self.normalizer_version, "normalizer_version")
        _required(self.revision, "revision")
        if self.continuation_token is not None:
            _required(self.continuation_token, "continuation_token")
            ensure_secret_safe(self.continuation_token)
        object.__setattr__(
            self,
            "cursor_id",
            deterministic_id(
                "cursor",
                {
                    "chain": self.chain.identity_dict(),
                    "provider": self.provider,
                    "scope": self.scope,
                    "normalized_schema_major": self.normalized_schema_major,
                    "normalizer_version": self.normalizer_version,
                },
            ),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "cursor_id": self.cursor_id,
            "chain": self.chain.to_dict(),
            "provider": self.provider,
            "scope": self.scope,
            "normalized_schema_major": self.normalized_schema_major,
            "normalizer_version": self.normalizer_version,
            "position": self.position.to_dict(),
            "revision": self.revision,
        }
        if self.continuation_token is not None:
            result["continuation_token"] = self.continuation_token
        return result


@dataclass(frozen=True, slots=True)
class ExportPartition:
    """One immutable dataset object named by digest and/or CID."""

    path: str
    format: str
    record_count: int
    byte_count: int
    digest: str | None = None
    cid: str | None = None
    record_types: tuple[str, ...] = ()
    min_position: int | None = None
    max_position: int | None = None

    def __post_init__(self) -> None:
        _required(self.path, "path")
        _required(self.format, "format")
        _non_negative(self.record_count, "record_count")
        _non_negative(self.byte_count, "byte_count")
        if self.digest is None and self.cid is None:
            raise ValueError("export partition requires a digest or CID")
        if self.digest is not None and not _DIGEST.fullmatch(self.digest):
            raise ValueError("digest must be tagged as algorithm:value")
        if self.cid is not None and not _CID.fullmatch(self.cid):
            raise ValueError("cid must be a CIDv0 or lowercase-base32 CIDv1")
        for value, name in (
            (self.min_position, "min_position"),
            (self.max_position, "max_position"),
        ):
            if value is not None:
                _non_negative(value, name)
        if (
            self.min_position is not None
            and self.max_position is not None
            and self.min_position > self.max_position
        ):
            raise ValueError("min_position must not exceed max_position")
        object.__setattr__(self, "record_types", tuple(self.record_types))
        for record_type in self.record_types:
            _required(record_type, "record_type")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "path": self.path,
            "format": self.format,
            "record_count": self.record_count,
            "byte_count": self.byte_count,
            "record_types": list(self.record_types),
            "min_position": self.min_position,
            "max_position": self.max_position,
        }
        if self.digest is not None:
            result["digest"] = self.digest
        if self.cid is not None:
            result["cid"] = self.cid
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportManifest:
    """Deterministic receipt describing a bounded wallet dataset export."""

    chain: ChainRef
    provenance: Provenance
    status: ExportStatus
    raw_payload_policy: RawPayloadPolicy
    partitions: tuple[ExportPartition, ...]
    record_count: int
    warning_count: int
    finality_counts: Mapping[Finality, int] = field(hash=False)
    started_at: datetime
    completed_at: datetime
    checkpoint_before: LedgerCursor | None = None
    checkpoint_after: LedgerCursor | None = None
    warnings: tuple[str, ...] = ()
    extensions: Mapping[str, VersionedExtension] = field(
        default_factory=dict,
        hash=False,
    )
    schema_version: str = field(default=EXPORT_MANIFEST_SCHEMA_VERSION, init=False)
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainRef):
            raise ValueError("chain must be a ChainRef")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be Provenance")
        if not isinstance(self.status, ExportStatus):
            raise ValueError("status must be an ExportStatus")
        if not isinstance(self.raw_payload_policy, RawPayloadPolicy):
            raise ValueError("raw_payload_policy must be a RawPayloadPolicy")
        object.__setattr__(self, "partitions", tuple(self.partitions))
        if any(not isinstance(part, ExportPartition) for part in self.partitions):
            raise ValueError("partitions must contain ExportPartition values")
        object.__setattr__(self, "warnings", tuple(self.warnings))
        for warning in self.warnings:
            if not isinstance(warning, str):
                raise ValueError("warnings must contain strings")
        ensure_secret_safe(self.warnings)
        _non_negative(self.record_count, "record_count")
        _non_negative(self.warning_count, "warning_count")
        _aware(self.started_at, "started_at")
        _aware(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.warning_count != len(self.warnings):
            raise ValueError("warning_count must equal the number of warnings")
        if sum(part.record_count for part in self.partitions) != self.record_count:
            raise ValueError("partition record counts must equal record_count")
        counts: dict[Finality, int] = {}
        for state, count in self.finality_counts.items():
            if not isinstance(state, Finality):
                raise ValueError("finality_counts keys must be Finality values")
            counts[state] = _non_negative(count, "finality count")
        if sum(counts.values()) != self.record_count:
            raise ValueError("finality counts must equal record_count")
        object.__setattr__(self, "finality_counts", MappingProxyType(counts))
        object.__setattr__(self, "extensions", _extensions(self.extensions))
        for cursor in (self.checkpoint_before, self.checkpoint_after):
            if cursor is not None and cursor.chain != self.chain:
                raise ValueError("manifest checkpoints must match the manifest chain")
        identity = {
            "chain": self.chain.identity_dict(),
            "source": self.provenance.source_dict(),
            "partitions": [partition.to_dict() for partition in self.partitions],
            "checkpoint_before": (
                self.checkpoint_before.cursor_id if self.checkpoint_before else None
            ),
            "checkpoint_after": (
                self.checkpoint_after.cursor_id if self.checkpoint_after else None
            ),
        }
        object.__setattr__(self, "manifest_id", deterministic_id("manifest", identity))
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            **self.chain.identity_dict(),
            "observed_at": format_datetime(self.provenance.observed_at),
            "source": self.provenance.source_dict(),
            "status": self.status.value,
            "raw_payload_policy": self.raw_payload_policy.value,
            "partitions": [partition.to_dict() for partition in self.partitions],
            "record_count": self.record_count,
            "warning_count": self.warning_count,
            "finality_counts": {
                state.value: count
                for state, count in sorted(
                    self.finality_counts.items(), key=lambda item: item[0].value
                )
            },
            "started_at": format_datetime(self.started_at),
            "completed_at": format_datetime(self.completed_at),
            "checkpoint_before": (
                self.checkpoint_before.to_dict() if self.checkpoint_before else None
            ),
            "checkpoint_after": (
                self.checkpoint_after.to_dict() if self.checkpoint_after else None
            ),
            "warnings": list(self.warnings),
            "extensions": _extension_dict(self.extensions),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


__all__ = [
    "ACCOUNT_REF_SCHEMA_VERSION",
    "ASSET_REF_SCHEMA_VERSION",
    "CHAIN_REF_SCHEMA_VERSION",
    "CURSOR_SCHEMA_VERSION",
    "EXPORT_MANIFEST_SCHEMA_VERSION",
    "LEDGER_RECORD_SCHEMA_VERSION",
    "AccountKind",
    "AccountRef",
    "AssetKind",
    "AssetRef",
    "BalanceRecord",
    "BalanceSnapshot",
    "BlockRecord",
    "ChainRef",
    "ContractEventRecord",
    "ExactAmount",
    "ExportManifest",
    "ExportPartition",
    "ExportStatus",
    "Finality",
    "LedgerCursor",
    "LedgerPosition",
    "LedgerRecord",
    "Provenance",
    "RawPayloadPolicy",
    "RawPayloadRef",
    "SECRET_SAFE_MAX_COLLECTION_ITEMS",
    "SECRET_SAFE_MAX_DEPTH",
    "SECRET_SAFE_MAX_NODES",
    "SECRET_SAFE_MAX_STRING_CHARS",
    "TokenAccountRecord",
    "TransactionRecord",
    "TransactionStatus",
    "TransferKind",
    "TransferRecord",
    "UTXORecord",
    "UtxoRecord",
    "VersionedExtension",
    "ensure_secret_safe",
]
