"""Dependency-free Solana identities and chain-native ingestion values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..errors import InvalidRequestError, NormalizationError
from ..models import ChainRef, TokenAccountRecord


SOLANA_NAMESPACE = "solana"
SOLANA_MAINNET_GENESIS_HASH = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_VALUES = {character: index for index, character in enumerate(_BASE58_ALPHABET)}


class Commitment(StrEnum):
    """Solana RPC commitment levels, kept deliberately distinct."""

    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


def decode_base58(value: object, *, field_name: str) -> bytes:
    """Decode a canonical base58 value without an optional Solana dependency."""

    if not isinstance(value, str) or not value:
        raise NormalizationError(f"{field_name} must be a non-empty base58 string")
    number = 0
    try:
        for character in value:
            number = number * 58 + _BASE58_VALUES[character]
    except KeyError:
        raise NormalizationError(f"{field_name} contains non-base58 characters") from None
    payload = b"" if number == 0 else number.to_bytes((number.bit_length() + 7) // 8, "big")
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + payload


def normalize_pubkey(value: object, *, field_name: str = "public key") -> str:
    """Validate a 32-byte Solana public key and preserve its base58 spelling."""

    if not isinstance(value, str):
        raise NormalizationError(f"{field_name} must be a string")
    if len(decode_base58(value, field_name=field_name)) != 32:
        raise NormalizationError(f"{field_name} must encode exactly 32 bytes")
    return value


def normalize_signature(value: object, *, field_name: str = "signature") -> str:
    """Validate a 64-byte Solana transaction signature."""

    if not isinstance(value, str):
        raise NormalizationError(f"{field_name} must be a string")
    if len(decode_base58(value, field_name=field_name)) != 64:
        raise NormalizationError(f"{field_name} must encode exactly 64 bytes")
    return value


def parse_non_negative_int(value: object, *, field_name: str) -> int:
    """Parse an integer without permitting floats, bools, signs, or exponents."""

    if isinstance(value, bool):
        raise NormalizationError(f"{field_name} must be a non-negative integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        result = int(value)
    else:
        raise NormalizationError(f"{field_name} must be a non-negative integer")
    if result < 0:
        raise NormalizationError(f"{field_name} must be a non-negative integer")
    return result


@dataclass(frozen=True, slots=True)
class SolanaNetwork:
    """Expected cluster identity and native-asset metadata."""

    network: str
    genesis_hash: str
    chain_id: str
    native_symbol: str = "SOL"
    native_decimals: int = 9

    def __post_init__(self) -> None:
        if not isinstance(self.network, str) or not self.network.strip():
            raise InvalidRequestError("network must not be empty")
        if not isinstance(self.genesis_hash, str) or not self.genesis_hash.strip():
            raise InvalidRequestError("genesis_hash must not be empty")
        if not isinstance(self.chain_id, str) or not self.chain_id.strip():
            raise InvalidRequestError("chain_id must not be empty")
        if not isinstance(self.native_symbol, str) or not self.native_symbol.strip():
            raise InvalidRequestError("native_symbol must not be empty")
        if (
            isinstance(self.native_decimals, bool)
            or not isinstance(self.native_decimals, int)
            or not 0 <= self.native_decimals <= 255
        ):
            raise InvalidRequestError("native_decimals must be between 0 and 255")

    def to_chain_ref(self) -> ChainRef:
        return ChainRef(
            namespace=SOLANA_NAMESPACE,
            network=self.network,
            chain_id=self.chain_id,
            genesis_hash=self.genesis_hash,
        )


SOLANA_MAINNET = SolanaNetwork(
    network="solana-mainnet-beta",
    genesis_hash=SOLANA_MAINNET_GENESIS_HASH,
    chain_id="mainnet-beta",
)


@dataclass(frozen=True, slots=True)
class AddressLookupTable:
    """Resolved addresses for one versioned-message lookup-table reference."""

    account_key: str
    writable_indexes: tuple[int, ...]
    readonly_indexes: tuple[int, ...]
    writable_addresses: tuple[str, ...]
    readonly_addresses: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_key", normalize_pubkey(self.account_key))
        for field_name in ("writable_indexes", "readonly_indexes"):
            indexes = tuple(getattr(self, field_name))
            if any(
                isinstance(index, bool) or not isinstance(index, int) or index < 0
                for index in indexes
            ):
                raise NormalizationError(f"{field_name} must contain non-negative integers")
            object.__setattr__(self, field_name, indexes)
        for field_name in ("writable_addresses", "readonly_addresses"):
            addresses = tuple(
                normalize_pubkey(item, field_name=field_name)
                for item in getattr(self, field_name)
            )
            object.__setattr__(self, field_name, addresses)
        if len(self.writable_indexes) != len(self.writable_addresses):
            raise NormalizationError("lookup writable index/address count mismatch")
        if len(self.readonly_indexes) != len(self.readonly_addresses):
            raise NormalizationError("lookup readonly index/address count mismatch")


def _account_key(value: object, *, field_name: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("pubkey")
    return normalize_pubkey(value, field_name=field_name)


def resolve_message_account_keys(
    message: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[AddressLookupTable, ...]]:
    """Resolve static plus loaded addresses in Solana's canonical order.

    The RPC ``jsonParsed`` shape returns lookup addresses under
    ``meta.loadedAddresses``. The order is consensus-relevant: all static
    keys, then all writable loaded keys, then all read-only loaded keys.
    Lookup declarations are cross-checked against those resolved lists so
    malformed or partial versioned messages fail closed.
    """

    raw_static = message.get("accountKeys")
    if not isinstance(raw_static, Sequence) or isinstance(raw_static, (str, bytes)):
        raise NormalizationError("message.accountKeys must be a sequence")
    static = tuple(
        _account_key(value, field_name=f"message.accountKeys[{index}]")
        for index, value in enumerate(raw_static)
    )
    loaded = meta.get("loadedAddresses") or {}
    if not isinstance(loaded, Mapping):
        raise NormalizationError("meta.loadedAddresses must be a mapping")
    raw_writable = loaded.get("writable") or ()
    raw_readonly = loaded.get("readonly") or ()
    if (
        not isinstance(raw_writable, Sequence)
        or isinstance(raw_writable, (str, bytes))
        or not isinstance(raw_readonly, Sequence)
        or isinstance(raw_readonly, (str, bytes))
    ):
        raise NormalizationError("loaded address lists must be sequences")
    writable = tuple(
        normalize_pubkey(value, field_name=f"loadedAddresses.writable[{index}]")
        for index, value in enumerate(raw_writable)
    )
    readonly = tuple(
        normalize_pubkey(value, field_name=f"loadedAddresses.readonly[{index}]")
        for index, value in enumerate(raw_readonly)
    )

    declarations = message.get("addressTableLookups") or ()
    if not isinstance(declarations, Sequence) or isinstance(declarations, (str, bytes)):
        raise NormalizationError("message.addressTableLookups must be a sequence")
    tables: list[AddressLookupTable] = []
    writable_offset = 0
    readonly_offset = 0
    for table_index, declaration in enumerate(declarations):
        if not isinstance(declaration, Mapping):
            raise NormalizationError("address lookup declaration must be a mapping")
        writable_indexes = tuple(
            parse_non_negative_int(value, field_name="lookup writable index")
            for value in (declaration.get("writableIndexes") or ())
        )
        readonly_indexes = tuple(
            parse_non_negative_int(value, field_name="lookup readonly index")
            for value in (declaration.get("readonlyIndexes") or ())
        )
        table_writable = writable[
            writable_offset : writable_offset + len(writable_indexes)
        ]
        table_readonly = readonly[
            readonly_offset : readonly_offset + len(readonly_indexes)
        ]
        if len(table_writable) != len(writable_indexes) or len(table_readonly) != len(
            readonly_indexes
        ):
            raise NormalizationError(
                f"lookup table {table_index} has unresolved address indexes"
            )
        tables.append(
            AddressLookupTable(
                account_key=declaration.get("accountKey"),
                writable_indexes=writable_indexes,
                readonly_indexes=readonly_indexes,
                writable_addresses=table_writable,
                readonly_addresses=table_readonly,
            )
        )
        writable_offset += len(writable_indexes)
        readonly_offset += len(readonly_indexes)
    if writable_offset != len(writable) or readonly_offset != len(readonly):
        raise NormalizationError("loaded addresses are not fully described by lookup tables")
    return static + writable + readonly, tuple(tables)


@dataclass(frozen=True, slots=True)
class SolanaSignatureInfo:
    signature: str
    slot: int
    err: object | None
    memo: str | None
    block_time: int | None
    confirmation_status: Commitment

    def __post_init__(self) -> None:
        object.__setattr__(self, "signature", normalize_signature(self.signature))
        object.__setattr__(
            self, "slot", parse_non_negative_int(self.slot, field_name="signature slot")
        )
        if self.block_time is not None:
            object.__setattr__(
                self,
                "block_time",
                parse_non_negative_int(self.block_time, field_name="block time"),
            )
        if not isinstance(self.confirmation_status, Commitment):
            raise NormalizationError("confirmation_status must be a Commitment")


@dataclass(frozen=True, slots=True)
class SolanaTransactionBundle:
    """One transaction plus the hash-anchored slot context used to normalize it."""

    transaction: Mapping[str, Any]
    slot: int
    blockhash: str
    block_time: int | None
    commitment: Commitment
    transaction_index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.transaction, Mapping):
            raise NormalizationError("transaction must be a mapping")
        object.__setattr__(self, "transaction", MappingProxyType(dict(self.transaction)))
        object.__setattr__(self, "slot", parse_non_negative_int(self.slot, field_name="slot"))
        if not isinstance(self.blockhash, str) or not self.blockhash:
            raise NormalizationError("blockhash must not be empty")
        if self.block_time is not None:
            object.__setattr__(
                self,
                "block_time",
                parse_non_negative_int(self.block_time, field_name="block time"),
            )
        if not isinstance(self.commitment, Commitment):
            raise NormalizationError("commitment must be a Commitment")
        object.__setattr__(
            self,
            "transaction_index",
            parse_non_negative_int(
                self.transaction_index, field_name="transaction index"
            ),
        )


@dataclass(frozen=True, slots=True)
class SolanaBlockBundle:
    slot: int
    blockhash: str
    previous_blockhash: str | None
    parent_slot: int
    block_time: int | None
    transactions: tuple[SolanaTransactionBundle, ...] = field(default_factory=tuple)
    commitment: Commitment = Commitment.FINALIZED


@dataclass(frozen=True, slots=True)
class SolanaHead:
    processed_slot: int
    confirmed_slot: int
    finalized_slot: int
    finalized_blockhash: str

    @property
    def sequence(self) -> int:
        return self.processed_slot

    @property
    def hash(self) -> str:
        return self.finalized_blockhash


__all__ = [
    "AddressLookupTable",
    "Commitment",
    "SOLANA_MAINNET",
    "SOLANA_MAINNET_GENESIS_HASH",
    "SOLANA_NAMESPACE",
    "SolanaBlockBundle",
    "SolanaHead",
    "SolanaNetwork",
    "SolanaSignatureInfo",
    "SolanaTransactionBundle",
    "TokenAccountRecord",
    "decode_base58",
    "normalize_pubkey",
    "normalize_signature",
    "parse_non_negative_int",
    "resolve_message_account_keys",
]
