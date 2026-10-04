"""Solana wallet-to-Crypto-IR adapter (CRYPTOIR-G110 / CRYPTOIR-008).

Convert Solana wallet records into Crypto IR with exact program, instruction,
account, signer, writable, token, inner-instruction, log, slot, and commitment
semantics.

Design constraints:

* Import and conversion are side-effect free (no sockets, no package install).
* Base58 identities are validated (32-byte pubkeys, 64-byte signatures) and
  cluster/genesis binding prevents cross-cluster collision.
* Account order and privilege bits (signer/writable) are semantic, not
  presentation details; they survive conversion in canonical message order.
* Lamports and SPL token base units are exact decimal integer strings (no
  binary floats).
* Slot commitment levels remain distinct (processed/confirmed/finalized).
* Incomplete inner-instruction coverage remains explicit, never invented.
* Unsupported versioned messages (unknown version, partial lookup resolution)
  fail closed.

This module owns only the Solana adapter surface and offline conversion.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ...ir_core.provenance import freeze_json, thaw_json
from ..capabilities import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityStatus,
    CapabilitySurface,
)
from ..identity import sha256_digest
from ..model import (
    AccountIdentity,
    AssetIdentity,
    CallIntent,
    ChainIdentity,
    CompletenessReceipt,
    CompletenessStatus,
    ExactAmount,
    FinalityStatus,
    LedgerCoordinate,
    ObservedTransaction,
    RetractionStatus,
    SerializedTransactionCandidate,
    SignerRequirement,
    TransferIntent,
    UnsignedTransactionIntent,
    ValidityWindow,
    observation_provenance,
)
from ..provenance import (
    AuthorityKind,
    CryptoIRProvenance,
    CryptoIRProvenanceError,
    freeze_json_mapping,
)
from . import (
    AdapterConversionResult,
    AdapterConversionStatus,
    CryptoIRAdapterError,
    UnsupportedField,
)


CRYPTO_IR_SOLANA_ADAPTER_DOMAIN: Final[str] = "crypto-ir.adapter.solana"
SOLANA_NAMESPACE: Final[str] = "solana"
SOLANA_ADAPTER_ID: Final[str] = "crypto-ir.adapter.solana"
SOLANA_CAPABILITY_ID: Final[str] = "crypto-ir.chain-adapter.solana"
SOLANA_ADAPTER_IMPLEMENTATION_VERSION: Final[str] = "1.0.0"
SOLANA_ADAPTER_SEMANTIC_VERSION: Final[str] = "1.0.0"

# Cluster anchors (CAIP-2 style chain_id + genesis binding)
SOLANA_MAINNET_CHAIN_ID: Final[str] = "mainnet-beta"
SOLANA_MAINNET_NETWORK: Final[str] = "solana-mainnet-beta"
SOLANA_MAINNET_GENESIS_HASH: Final[str] = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

SOLANA_DEVNET_CHAIN_ID: Final[str] = "devnet"
SOLANA_DEVNET_NETWORK: Final[str] = "solana-devnet"
SOLANA_DEVNET_GENESIS_HASH: Final[str] = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"

SOLANA_TESTNET_CHAIN_ID: Final[str] = "testnet"
SOLANA_TESTNET_NETWORK: Final[str] = "solana-testnet"
SOLANA_TESTNET_GENESIS_HASH: Final[str] = "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY"

NATIVE_ASSET_NAMESPACE: Final[str] = "slip44"
NATIVE_ASSET_REFERENCE: Final[str] = "501"  # SOL
NATIVE_DECIMALS: Final[int] = 9
NATIVE_SYMBOL: Final[str] = "SOL"

SYSTEM_PROGRAM_ID: Final[str] = "11111111111111111111111111111111"
TOKEN_PROGRAM_ID: Final[str] = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
TOKEN_PROGRAM_IDS: Final[frozenset[str]] = frozenset(
    {TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID}
)

SUPPORTED_MESSAGE_VERSIONS: Final[frozenset[str]] = frozenset({"legacy", "0"})

_BASE58_ALPHABET: Final[str] = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)
_BASE58_INDEX: Final[dict[str, int]] = {
    ch: i for i, ch in enumerate(_BASE58_ALPHABET)
}
_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^-?(0|[1-9][0-9]*)$")
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0x)?[0-9A-Fa-f]+$")


class SolanaAdapterError(CryptoIRAdapterError):
    """Raised when a Solana wallet payload cannot be converted fail-closed."""


class SolanaPayloadKind(str, Enum):
    """Supported offline conversion payload kinds."""

    TRANSACTION_OBSERVATION = "transaction_observation"
    MESSAGE_CANDIDATE = "message_candidate"
    SERIALIZED_CANDIDATE = "serialized_candidate"


class AccountKeySource(str, Enum):
    """Where a resolved account key originated in the message account list."""

    STATIC = "static"
    LOOKUP_WRITABLE = "lookup_writable"
    LOOKUP_READONLY = "lookup_readonly"


# ---------------------------------------------------------------------------
# Validation / normalization helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SolanaAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise SolanaAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise SolanaAdapterError(f"{name} must not have surrounding whitespace")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SolanaAdapterError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise SolanaAdapterError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise SolanaAdapterError(str(exc)) from exc


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _ID_RE.fullmatch(text):
        raise SolanaAdapterError(f"{name} is not a stable identifier")
    return text


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        # Allow pure decimal integer strings (exact base units).
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            result = int(value)
        else:
            raise SolanaAdapterError(f"{name} must be an integer")
    else:
        result = value
    if result < 0:
        raise SolanaAdapterError(f"{name} must be non-negative")
    return result


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    return _non_negative_int(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise SolanaAdapterError(f"{name} must be a boolean")
    return value


def content_sha256_hex(value: Any) -> str:
    """Return bare 64-char sha256 hex for a JSON-compatible value."""

    from ...ir_core.canonical import canonical_json_bytes

    if isinstance(value, (bytes, bytearray)):
        return hashlib.sha256(bytes(value)).hexdigest()
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    try:
        frozen = freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise SolanaAdapterError(str(exc)) from exc
    digest_label = sha256_digest(canonical_json_bytes(frozen))
    if digest_label.startswith("sha256:"):
        return digest_label.split(":", 1)[1]
    return digest_label


def sha256_digest_tag(value: str | bytes) -> str:
    """Return ``sha256:<hex>`` for identity binding."""

    if isinstance(value, str):
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    else:
        digest = hashlib.sha256(bytes(value)).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Base58 pubkey / signature validation
# ---------------------------------------------------------------------------


def decode_base58(value: object, *, field: str = "value") -> bytes:
    """Decode a canonical base58 string without optional Solana dependencies."""

    if not isinstance(value, str) or not value:
        raise SolanaAdapterError(f"{field} must be a non-empty base58 string")
    number = 0
    try:
        for character in value:
            number = number * 58 + _BASE58_INDEX[character]
    except KeyError as exc:
        raise SolanaAdapterError(
            f"{field} contains non-base58 characters"
        ) from exc
    payload = (
        b"" if number == 0 else number.to_bytes((number.bit_length() + 7) // 8, "big")
    )
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + payload


def encode_base58(data: bytes) -> str:
    """Encode bytes as Bitcoin/Solana base58 (no checksum)."""

    if not isinstance(data, (bytes, bytearray)):
        raise SolanaAdapterError("base58 encode input must be bytes")
    number = int.from_bytes(data, "big")
    if number == 0:
        return "1" * len(data)
    out = ""
    while number:
        number, rem = divmod(number, 58)
        out = _BASE58_ALPHABET[rem] + out
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return ("1" * pad) + out


def normalize_pubkey(value: object, *, field: str = "pubkey") -> str:
    """Validate a 32-byte Solana public key and preserve its base58 spelling."""

    if not isinstance(value, str):
        raise SolanaAdapterError(f"{field} must be a string")
    text = _text(value, field)
    if len(decode_base58(text, field=field)) != 32:
        raise SolanaAdapterError(f"{field} must encode exactly 32 bytes")
    return text


def normalize_signature(value: object, *, field: str = "signature") -> str:
    """Validate a 64-byte Solana transaction signature (base58)."""

    if not isinstance(value, str):
        raise SolanaAdapterError(f"{field} must be a string")
    text = _text(value, field)
    if len(decode_base58(text, field=field)) != 64:
        raise SolanaAdapterError(f"{field} must encode exactly 64 bytes")
    return text


def normalize_blockhash(value: object, *, field: str = "blockhash") -> str:
    """Validate a 32-byte blockhash/recent-blockhash base58 value."""

    return normalize_pubkey(value, field=field)


def parse_exact_base_units(value: object, *, field: str = "amount") -> str:
    """Parse exact non-negative base units; reject floats and scientific notation."""

    if isinstance(value, bool) or isinstance(value, float):
        raise SolanaAdapterError(f"{field} rejects binary floats and bools")
    if type(value) is int:
        if value < 0:
            raise SolanaAdapterError(f"{field} must be non-negative")
        return str(value)
    text = _text(value, field)
    if not _DECIMAL_INTEGER.fullmatch(text) or text.startswith("-"):
        raise SolanaAdapterError(
            f"{field} must be a non-negative decimal integer string"
        )
    return text


# ---------------------------------------------------------------------------
# Network anchors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SolanaNetworkAnchor:
    """Known Solana cluster identity (chain id + genesis binding)."""

    chain_id: str
    network: str
    genesis_hash: str
    display_name: str = ""
    native_symbol: str = NATIVE_SYMBOL
    native_decimals: int = NATIVE_DECIMALS

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _text(self.chain_id, "chain_id"))
        object.__setattr__(self, "network", _text(self.network, "network"))
        # Genesis may be short base58 (mainnet) or 32-byte base58; store as-is
        # after non-empty validation.  Identity digests bind the literal.
        object.__setattr__(
            self, "genesis_hash", _text(self.genesis_hash, "genesis_hash")
        )
        object.__setattr__(
            self,
            "display_name",
            _text(self.display_name, "display_name", allow_empty=True),
        )
        object.__setattr__(
            self, "native_symbol", _text(self.native_symbol, "native_symbol")
        )
        if (
            isinstance(self.native_decimals, bool)
            or not isinstance(self.native_decimals, int)
            or not 0 <= self.native_decimals <= 255
        ):
            raise SolanaAdapterError("native_decimals must be between 0 and 255")

    def to_chain_identity(self) -> ChainIdentity:
        return ChainIdentity(
            chain_namespace=SOLANA_NAMESPACE,
            network=self.network,
            genesis_digest=sha256_digest_tag(self.genesis_hash),
            chain_id=self.chain_id,
            display_name=self.display_name or self.network,
            attributes={
                "genesis_hash": self.genesis_hash,
                "namespace": SOLANA_NAMESPACE,
                "cluster": self.chain_id,
            },
        )


KNOWN_NETWORKS: Final[dict[str, SolanaNetworkAnchor]] = {
    SOLANA_MAINNET_CHAIN_ID: SolanaNetworkAnchor(
        chain_id=SOLANA_MAINNET_CHAIN_ID,
        network=SOLANA_MAINNET_NETWORK,
        genesis_hash=SOLANA_MAINNET_GENESIS_HASH,
        display_name="Solana Mainnet Beta",
    ),
    SOLANA_DEVNET_CHAIN_ID: SolanaNetworkAnchor(
        chain_id=SOLANA_DEVNET_CHAIN_ID,
        network=SOLANA_DEVNET_NETWORK,
        genesis_hash=SOLANA_DEVNET_GENESIS_HASH,
        display_name="Solana Devnet",
    ),
    SOLANA_TESTNET_CHAIN_ID: SolanaNetworkAnchor(
        chain_id=SOLANA_TESTNET_CHAIN_ID,
        network=SOLANA_TESTNET_NETWORK,
        genesis_hash=SOLANA_TESTNET_GENESIS_HASH,
        display_name="Solana Testnet",
    ),
    # Network name aliases map to the same anchors.
    SOLANA_MAINNET_NETWORK: SolanaNetworkAnchor(
        chain_id=SOLANA_MAINNET_CHAIN_ID,
        network=SOLANA_MAINNET_NETWORK,
        genesis_hash=SOLANA_MAINNET_GENESIS_HASH,
        display_name="Solana Mainnet Beta",
    ),
    SOLANA_DEVNET_NETWORK: SolanaNetworkAnchor(
        chain_id=SOLANA_DEVNET_CHAIN_ID,
        network=SOLANA_DEVNET_NETWORK,
        genesis_hash=SOLANA_DEVNET_GENESIS_HASH,
        display_name="Solana Devnet",
    ),
    SOLANA_TESTNET_NETWORK: SolanaNetworkAnchor(
        chain_id=SOLANA_TESTNET_CHAIN_ID,
        network=SOLANA_TESTNET_NETWORK,
        genesis_hash=SOLANA_TESTNET_GENESIS_HASH,
        display_name="Solana Testnet",
    ),
}


def resolve_network(
    *,
    chain_id: str | None = None,
    network: str | None = None,
    genesis_hash: str | None = None,
    display_name: str = "",
) -> SolanaNetworkAnchor:
    """Resolve a cluster/genesis anchor without inventing identity.

    Known clusters may omit genesis when the official anchor matches.  Unknown
    clusters require an explicit genesis hash.  Mismatched genesis fails closed.
    """

    key = (chain_id or network or "").strip()
    aliases = {
        "mainnet": SOLANA_MAINNET_CHAIN_ID,
        "mainnet-beta": SOLANA_MAINNET_CHAIN_ID,
        "solana": SOLANA_MAINNET_CHAIN_ID,
        "solana-mainnet": SOLANA_MAINNET_CHAIN_ID,
        "solana-mainnet-beta": SOLANA_MAINNET_CHAIN_ID,
        "devnet": SOLANA_DEVNET_CHAIN_ID,
        "solana-devnet": SOLANA_DEVNET_CHAIN_ID,
        "testnet": SOLANA_TESTNET_CHAIN_ID,
        "solana-testnet": SOLANA_TESTNET_CHAIN_ID,
    }
    resolved_key = aliases.get(key.lower(), key) if key else ""

    known: SolanaNetworkAnchor | None = None
    if resolved_key:
        known = KNOWN_NETWORKS.get(resolved_key)
        if known is None and network:
            known = KNOWN_NETWORKS.get(network)
        if known is None and chain_id:
            known = KNOWN_NETWORKS.get(chain_id)

    if known is not None:
        if genesis_hash is not None and genesis_hash != "":
            provided = _text(genesis_hash, "genesis_hash")
            if provided != known.genesis_hash:
                raise SolanaAdapterError(
                    f"genesis_hash does not match known network for "
                    f"chain_id={known.chain_id}"
                )
        if network is not None and network not in {
            known.network,
            known.chain_id,
            "mainnet",
            "mainnet-beta",
            "devnet",
            "testnet",
            "solana",
            "solana-mainnet",
            "solana-mainnet-beta",
            "solana-devnet",
            "solana-testnet",
        }:
            if network != known.network:
                raise SolanaAdapterError(
                    f"network {network!r} does not match known chain_id={known.chain_id}"
                )
        return known

    if not chain_id and not network:
        raise SolanaAdapterError(
            "chain_id or network is required for Solana conversion"
        )
    if not genesis_hash:
        raise SolanaAdapterError(
            "unknown Solana cluster requires an explicit genesis_hash"
        )
    net_name = network or f"solana-{chain_id}"
    return SolanaNetworkAnchor(
        chain_id=chain_id or net_name,
        network=net_name,
        genesis_hash=genesis_hash,
        display_name=display_name or net_name,
    )


def account_identity(
    pubkey: str,
    chain: ChainIdentity,
    *,
    account_kind: str = "account",
    is_signer: bool | None = None,
    is_writable: bool | None = None,
    account_index: int | None = None,
) -> AccountIdentity:
    """Build an AccountIdentity; base58 spelling is the identity form."""

    original = normalize_pubkey(pubkey, field="pubkey")
    attributes: dict[str, Any] = {
        "encoding": "base58",
        "byte_length": 32,
    }
    if is_signer is not None:
        attributes["is_signer"] = bool(is_signer)
    if is_writable is not None:
        attributes["is_writable"] = bool(is_writable)
    if account_index is not None:
        attributes["account_index"] = int(account_index)
    return AccountIdentity(
        chain=chain,
        address_normalized=original,
        address_original=original,
        account_kind=account_kind,
        attributes=attributes,
    )


def native_asset(chain: ChainIdentity, network: SolanaNetworkAnchor) -> AssetIdentity:
    return AssetIdentity(
        chain=chain,
        asset_namespace=NATIVE_ASSET_NAMESPACE,
        asset_reference=NATIVE_ASSET_REFERENCE,
        decimals=network.native_decimals,
        symbol=network.native_symbol,
        attributes={"kind": "native", "unit": "lamports"},
    )


def token_asset(
    chain: ChainIdentity,
    mint: str,
    *,
    decimals: int | None,
    symbol: str = "",
    program_id: str = TOKEN_PROGRAM_ID,
) -> AssetIdentity:
    mint_key = normalize_pubkey(mint, field="mint")
    attributes: dict[str, Any] = {
        "kind": "token",
        "standard": "spl-token",
        "mint": mint_key,
        "program_id": normalize_pubkey(program_id, field="token.program_id"),
    }
    if decimals is None:
        attributes["decimals_absent"] = True
        resolved_decimals = 0
    else:
        resolved_decimals = _non_negative_int(decimals, "token.decimals")
        if resolved_decimals > 255:
            raise SolanaAdapterError("token.decimals must not exceed 255")
    return AssetIdentity(
        chain=chain,
        asset_namespace="spl-token",
        asset_reference=mint_key,
        decimals=resolved_decimals,
        symbol=symbol,
        attributes=attributes,
    )


def map_commitment(value: Any) -> FinalityStatus:
    """Map Solana RPC commitment levels; keep levels distinct (not collapsed)."""

    if value is None or value == "":
        return FinalityStatus.UNKNOWN
    if isinstance(value, FinalityStatus):
        return value
    text = _text(str(value), "commitment").lower().replace("-", "_")
    aliases = {
        "unknown": FinalityStatus.UNKNOWN,
        "processed": FinalityStatus.PROPOSED,
        "proposed": FinalityStatus.PROPOSED,
        "observed": FinalityStatus.PROPOSED,
        "confirmed": FinalityStatus.CONFIRMED,
        "finalized": FinalityStatus.FINALIZED,
        "final": FinalityStatus.FINALIZED,
        "reorged": FinalityStatus.REORGED,
        "retracted": FinalityStatus.RETRACTED,
    }
    if text in aliases:
        return aliases[text]
    try:
        return FinalityStatus(text)
    except ValueError as exc:
        raise SolanaAdapterError(f"unsupported commitment: {value!r}") from exc


def map_retraction(value: Any) -> RetractionStatus:
    if value is None or value == "":
        return RetractionStatus.UNKNOWN
    if isinstance(value, RetractionStatus):
        return value
    text = _text(str(value), "retraction").lower().replace("-", "_")
    aliases = {
        "not_retracted": RetractionStatus.NOT_RETRACTED,
        "none": RetractionStatus.NOT_RETRACTED,
        "superseded": RetractionStatus.SUPERSEDED,
        "retracted": RetractionStatus.RETRACTED,
        "unknown": RetractionStatus.UNKNOWN,
    }
    if text in aliases:
        return aliases[text]
    try:
        return RetractionStatus(text)
    except ValueError as exc:
        raise SolanaAdapterError(f"unsupported retraction: {value!r}") from exc


def normalize_message_version(value: Any) -> str:
    """Normalize message version; unsupported versions fail closed."""

    if value is None or value == "":
        return "legacy"
    if type(value) is int and not isinstance(value, bool):
        if value == 0:
            return "0"
        raise SolanaAdapterError(
            f"unsupported versioned message version: {value!r}"
        )
    text = str(value).strip().lower()
    if text in {"legacy", "legacy_v0"}:
        return "legacy"
    if text in {"0", "v0"}:
        return "0"
    raise SolanaAdapterError(f"unsupported versioned message version: {value!r}")


# ---------------------------------------------------------------------------
# Account privileges and instructions (semantic, ordered)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccountPrivilege:
    """Per-account privilege bits in consensus account-list order.

    Account order and signer/writable bits are semantic (affect instruction
    meaning and authorization), not presentation details.  Indices are the
    positions in the fully resolved account key list (static + loaded).
    """

    account_index: int
    pubkey: str
    is_signer: bool
    is_writable: bool
    source: str = AccountKeySource.STATIC.value

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_index",
            _non_negative_int(self.account_index, "account_index"),
        )
        object.__setattr__(
            self, "pubkey", normalize_pubkey(self.pubkey, field="pubkey")
        )
        object.__setattr__(self, "is_signer", _bool(self.is_signer, "is_signer"))
        object.__setattr__(
            self, "is_writable", _bool(self.is_writable, "is_writable")
        )
        source = _text(self.source, "source")
        try:
            AccountKeySource(source)
        except ValueError as exc:
            raise SolanaAdapterError(f"unsupported account key source: {source!r}") from exc
        object.__setattr__(self, "source", source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_index": self.account_index,
            "is_signer": self.is_signer,
            "is_writable": self.is_writable,
            "pubkey": self.pubkey,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AccountPrivilege":
        value = _as_mapping(value, "AccountPrivilege")
        return cls(
            account_index=value.get("account_index", 0),
            pubkey=value.get("pubkey", value.get("address", "")),
            is_signer=value.get("is_signer", value.get("signer", False)),
            is_writable=value.get("is_writable", value.get("writable", False)),
            source=value.get("source", AccountKeySource.STATIC.value),
        )


@dataclass(frozen=True, slots=True)
class SolanaInstruction:
    """One outer or inner program instruction with ordered account metas.

    ``account_indexes`` reference the resolved privilege list order.  Inner
    instructions set ``inner_index``; outer-only leave it ``None``.
    """

    program_id: str
    account_indexes: tuple[int, ...] = ()
    accounts: tuple[str, ...] = ()
    data: str = ""
    data_encoding: str = "base58"
    outer_index: int = 0
    inner_index: int | None = None
    stack_height: int | None = None
    parsed_type: str = ""
    parsed_info: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "program_id", normalize_pubkey(self.program_id, field="program_id")
        )
        if isinstance(self.account_indexes, (str, bytes, bytearray)) or not isinstance(
            self.account_indexes, Sequence
        ):
            raise SolanaAdapterError("account_indexes must be a sequence of integers")
        indexes = tuple(
            _non_negative_int(item, "account_index") for item in self.account_indexes
        )
        object.__setattr__(self, "account_indexes", indexes)
        if isinstance(self.accounts, (str, bytes, bytearray)) or not isinstance(
            self.accounts, Sequence
        ):
            raise SolanaAdapterError("accounts must be a sequence of pubkeys")
        accounts = tuple(
            normalize_pubkey(item, field="instruction.account")
            for item in self.accounts
        )
        object.__setattr__(self, "accounts", accounts)
        object.__setattr__(
            self, "data", _text(self.data, "data", allow_empty=True)
        )
        object.__setattr__(
            self, "data_encoding", _text(self.data_encoding, "data_encoding")
        )
        object.__setattr__(
            self, "outer_index", _non_negative_int(self.outer_index, "outer_index")
        )
        object.__setattr__(
            self,
            "inner_index",
            _optional_non_negative_int(self.inner_index, "inner_index"),
        )
        object.__setattr__(
            self,
            "stack_height",
            _optional_non_negative_int(self.stack_height, "stack_height"),
        )
        object.__setattr__(
            self, "parsed_type", _text(self.parsed_type, "parsed_type", allow_empty=True)
        )
        object.__setattr__(self, "parsed_info", _attributes(self.parsed_info))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def is_inner(self) -> bool:
        return self.inner_index is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_indexes": list(self.account_indexes),
            "accounts": list(self.accounts),
            "attributes": thaw_json(self.attributes),
            "data": self.data,
            "data_encoding": self.data_encoding,
            "inner_index": self.inner_index,
            "outer_index": self.outer_index,
            "parsed_info": thaw_json(self.parsed_info),
            "parsed_type": self.parsed_type,
            "program_id": self.program_id,
            "stack_height": self.stack_height,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolanaInstruction":
        value = _as_mapping(value, "SolanaInstruction")
        return cls(
            program_id=value.get("program_id", value.get("programId", "")),
            account_indexes=tuple(
                value.get("account_indexes", value.get("accountIndexes", ()))
            ),
            accounts=tuple(value.get("accounts", ())),
            data=value.get("data", ""),
            data_encoding=value.get("data_encoding", value.get("dataEncoding", "base58")),
            outer_index=value.get("outer_index", value.get("outerIndex", 0)),
            inner_index=value.get("inner_index", value.get("innerIndex")),
            stack_height=value.get("stack_height", value.get("stackHeight")),
            parsed_type=value.get("parsed_type", ""),
            parsed_info=value.get("parsed_info", {}),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class AddressLookupTableRef:
    """Resolved address-lookup-table reference for a versioned message."""

    account_key: str
    writable_indexes: tuple[int, ...] = ()
    readonly_indexes: tuple[int, ...] = ()
    writable_addresses: tuple[str, ...] = ()
    readonly_addresses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_key",
            normalize_pubkey(self.account_key, field="lookup.account_key"),
        )
        object.__setattr__(
            self,
            "writable_indexes",
            tuple(
                _non_negative_int(i, "lookup.writable_index")
                for i in self.writable_indexes
            ),
        )
        object.__setattr__(
            self,
            "readonly_indexes",
            tuple(
                _non_negative_int(i, "lookup.readonly_index")
                for i in self.readonly_indexes
            ),
        )
        object.__setattr__(
            self,
            "writable_addresses",
            tuple(
                normalize_pubkey(a, field="lookup.writable_address")
                for a in self.writable_addresses
            ),
        )
        object.__setattr__(
            self,
            "readonly_addresses",
            tuple(
                normalize_pubkey(a, field="lookup.readonly_address")
                for a in self.readonly_addresses
            ),
        )
        if len(self.writable_indexes) != len(self.writable_addresses):
            raise SolanaAdapterError(
                "lookup writable index/address count mismatch"
            )
        if len(self.readonly_indexes) != len(self.readonly_addresses):
            raise SolanaAdapterError(
                "lookup readonly index/address count mismatch"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_key": self.account_key,
            "readonly_addresses": list(self.readonly_addresses),
            "readonly_indexes": list(self.readonly_indexes),
            "writable_addresses": list(self.writable_addresses),
            "writable_indexes": list(self.writable_indexes),
        }


def _account_key_from_value(value: object, *, field: str) -> str:
    if isinstance(value, Mapping):
        pubkey = value.get("pubkey", value.get("address", value.get("publicKey")))
        return normalize_pubkey(pubkey, field=field)
    return normalize_pubkey(value, field=field)


def privileges_from_header(
    static_keys: Sequence[str],
    header: Mapping[str, Any],
    *,
    loaded_writable: Sequence[str] = (),
    loaded_readonly: Sequence[str] = (),
) -> tuple[AccountPrivilege, ...]:
    """Derive ordered privilege bits from message header + loaded addresses.

    Solana message header semantics:

    * first ``numRequiredSignatures`` static keys are signers;
    * among signers, the last ``numReadonlySignedAccounts`` are read-only;
    * among non-signers, the last ``numReadonlyUnsignedAccounts`` are read-only;
    * loaded writable addresses are non-signer writable;
    * loaded readonly addresses are non-signer read-only.

    Order is consensus-relevant: static, then loaded writable, then loaded
    readonly.
    """

    num_required = _non_negative_int(
        header.get("numRequiredSignatures", header.get("num_required_signatures", 0)),
        "numRequiredSignatures",
    )
    num_ro_signed = _non_negative_int(
        header.get(
            "numReadonlySignedAccounts",
            header.get("num_readonly_signed_accounts", 0),
        ),
        "numReadonlySignedAccounts",
    )
    num_ro_unsigned = _non_negative_int(
        header.get(
            "numReadonlyUnsignedAccounts",
            header.get("num_readonly_unsigned_accounts", 0),
        ),
        "numReadonlyUnsignedAccounts",
    )
    n = len(static_keys)
    if num_required > n:
        raise SolanaAdapterError("numRequiredSignatures exceeds static account keys")
    if num_ro_signed > num_required:
        raise SolanaAdapterError(
            "numReadonlySignedAccounts exceeds numRequiredSignatures"
        )
    if num_ro_unsigned > (n - num_required):
        raise SolanaAdapterError(
            "numReadonlyUnsignedAccounts exceeds non-signer static keys"
        )

    privileges: list[AccountPrivilege] = []
    for index, pubkey in enumerate(static_keys):
        is_signer = index < num_required
        if is_signer:
            # Writable signed: first (num_required - num_ro_signed)
            is_writable = index < (num_required - num_ro_signed)
        else:
            # Writable unsigned: first (n - num_required - num_ro_unsigned)
            unsigned_index = index - num_required
            writable_unsigned = n - num_required - num_ro_unsigned
            is_writable = unsigned_index < writable_unsigned
        privileges.append(
            AccountPrivilege(
                account_index=index,
                pubkey=pubkey,
                is_signer=is_signer,
                is_writable=is_writable,
                source=AccountKeySource.STATIC.value,
            )
        )

    base = len(privileges)
    for offset, pubkey in enumerate(loaded_writable):
        privileges.append(
            AccountPrivilege(
                account_index=base + offset,
                pubkey=pubkey,
                is_signer=False,
                is_writable=True,
                source=AccountKeySource.LOOKUP_WRITABLE.value,
            )
        )
    base = len(privileges)
    for offset, pubkey in enumerate(loaded_readonly):
        privileges.append(
            AccountPrivilege(
                account_index=base + offset,
                pubkey=pubkey,
                is_signer=False,
                is_writable=False,
                source=AccountKeySource.LOOKUP_READONLY.value,
            )
        )
    return tuple(privileges)


def privileges_from_json_parsed(
    account_keys: Sequence[Any],
    *,
    loaded_writable: Sequence[str] = (),
    loaded_readonly: Sequence[str] = (),
) -> tuple[AccountPrivilege, ...]:
    """Build privileges from jsonParsed accountKeys with explicit bits."""

    privileges: list[AccountPrivilege] = []
    for index, item in enumerate(account_keys):
        if isinstance(item, Mapping):
            pubkey = normalize_pubkey(
                item.get("pubkey", item.get("address")),
                field=f"accountKeys[{index}]",
            )
            is_signer = _bool(item.get("signer", item.get("is_signer", False)), "signer")
            is_writable = _bool(
                item.get("writable", item.get("is_writable", False)), "writable"
            )
        else:
            raise SolanaAdapterError(
                "jsonParsed accountKeys entries must be mappings with privilege bits"
            )
        privileges.append(
            AccountPrivilege(
                account_index=index,
                pubkey=pubkey,
                is_signer=is_signer,
                is_writable=is_writable,
                source=AccountKeySource.STATIC.value,
            )
        )
    base = len(privileges)
    for offset, pubkey in enumerate(loaded_writable):
        privileges.append(
            AccountPrivilege(
                account_index=base + offset,
                pubkey=normalize_pubkey(pubkey, field="loaded.writable"),
                is_signer=False,
                is_writable=True,
                source=AccountKeySource.LOOKUP_WRITABLE.value,
            )
        )
    base = len(privileges)
    for offset, pubkey in enumerate(loaded_readonly):
        privileges.append(
            AccountPrivilege(
                account_index=base + offset,
                pubkey=normalize_pubkey(pubkey, field="loaded.readonly"),
                is_signer=False,
                is_writable=False,
                source=AccountKeySource.LOOKUP_READONLY.value,
            )
        )
    return tuple(privileges)


def resolve_account_privileges(
    message: Mapping[str, Any],
    meta: Mapping[str, Any] | None = None,
) -> tuple[tuple[AccountPrivilege, ...], tuple[AddressLookupTableRef, ...]]:
    """Resolve full ordered privileges and lookup tables fail-closed.

    Canonical order: static keys, then loaded writable, then loaded readonly.
    Partial or mismatched lookup resolution raises :class:`SolanaAdapterError`.
    """

    message = _as_mapping(message, "message")
    raw_static = message.get("accountKeys", message.get("account_keys"))
    if not isinstance(raw_static, Sequence) or isinstance(raw_static, (str, bytes)):
        raise SolanaAdapterError("message.accountKeys must be a sequence")

    meta = meta or {}
    loaded = meta.get("loadedAddresses", meta.get("loaded_addresses")) or {}
    if loaded and not isinstance(loaded, Mapping):
        raise SolanaAdapterError("meta.loadedAddresses must be a mapping")
    raw_writable = (loaded or {}).get("writable") or ()
    raw_readonly = (loaded or {}).get("readonly") or ()
    if (
        not isinstance(raw_writable, Sequence)
        or isinstance(raw_writable, (str, bytes))
        or not isinstance(raw_readonly, Sequence)
        or isinstance(raw_readonly, (str, bytes))
    ):
        raise SolanaAdapterError("loaded address lists must be sequences")
    loaded_writable = tuple(
        normalize_pubkey(v, field=f"loadedAddresses.writable[{i}]")
        for i, v in enumerate(raw_writable)
    )
    loaded_readonly = tuple(
        normalize_pubkey(v, field=f"loadedAddresses.readonly[{i}]")
        for i, v in enumerate(raw_readonly)
    )

    # Lookup table declarations (versioned messages)
    declarations = message.get("addressTableLookups", message.get("address_table_lookups")) or ()
    if not isinstance(declarations, Sequence) or isinstance(declarations, (str, bytes)):
        raise SolanaAdapterError("message.addressTableLookups must be a sequence")

    tables: list[AddressLookupTableRef] = []
    writable_offset = 0
    readonly_offset = 0
    for table_index, declaration in enumerate(declarations):
        if not isinstance(declaration, Mapping):
            raise SolanaAdapterError("address lookup declaration must be a mapping")
        w_indexes = tuple(
            _non_negative_int(v, "lookup writable index")
            for v in (
                declaration.get("writableIndexes")
                or declaration.get("writable_indexes")
                or ()
            )
        )
        r_indexes = tuple(
            _non_negative_int(v, "lookup readonly index")
            for v in (
                declaration.get("readonlyIndexes")
                or declaration.get("readonly_indexes")
                or ()
            )
        )
        table_writable = loaded_writable[
            writable_offset : writable_offset + len(w_indexes)
        ]
        table_readonly = loaded_readonly[
            readonly_offset : readonly_offset + len(r_indexes)
        ]
        if len(table_writable) != len(w_indexes) or len(table_readonly) != len(r_indexes):
            raise SolanaAdapterError(
                f"lookup table {table_index} has unresolved address indexes"
            )
        tables.append(
            AddressLookupTableRef(
                account_key=declaration.get(
                    "accountKey", declaration.get("account_key", "")
                ),
                writable_indexes=w_indexes,
                readonly_indexes=r_indexes,
                writable_addresses=table_writable,
                readonly_addresses=table_readonly,
            )
        )
        writable_offset += len(w_indexes)
        readonly_offset += len(r_indexes)

    if declarations:
        if writable_offset != len(loaded_writable) or readonly_offset != len(
            loaded_readonly
        ):
            raise SolanaAdapterError(
                "loaded addresses are not fully described by lookup tables"
            )

    # Prefer explicit privilege bits when present on accountKeys.
    if raw_static and isinstance(raw_static[0], Mapping) and (
        "signer" in raw_static[0]
        or "is_signer" in raw_static[0]
        or "writable" in raw_static[0]
        or "is_writable" in raw_static[0]
    ):
        privileges = privileges_from_json_parsed(
            raw_static,
            loaded_writable=loaded_writable,
            loaded_readonly=loaded_readonly,
        )
        return privileges, tuple(tables)

    static = tuple(
        _account_key_from_value(v, field=f"message.accountKeys[{i}]")
        for i, v in enumerate(raw_static)
    )
    header = message.get("header")
    if header is None:
        # Without header or privilege bits, only fail if we need them.
        # Treat all static as non-signer read-only unless counts are given —
        # but that would invent facts.  Fail closed.
        raise SolanaAdapterError(
            "message.header or explicit account privilege bits are required"
        )
    header_map = _as_mapping(header, "message.header")
    privileges = privileges_from_header(
        static,
        header_map,
        loaded_writable=loaded_writable,
        loaded_readonly=loaded_readonly,
    )
    return privileges, tuple(tables)


def parse_instructions(
    message: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
    privileges: Sequence[AccountPrivilege],
    *,
    inner_instructions_present: bool | None = None,
) -> tuple[tuple[SolanaInstruction, ...], list[str], list[UnsupportedField]]:
    """Parse outer and inner instructions; record incomplete coverage explicitly."""

    message = _as_mapping(message, "message")
    outer = message.get("instructions")
    if not isinstance(outer, Sequence) or isinstance(outer, (str, bytes)):
        raise SolanaAdapterError("message.instructions must be a sequence")

    missing: list[str] = []
    unsupported: list[UnsupportedField] = []
    account_keys = tuple(p.pubkey for p in privileges)
    index_by_pubkey = {p.pubkey: p.account_index for p in privileges}

    def program_id_of(instruction: Mapping[str, Any]) -> str:
        if instruction.get("programId") is not None:
            return normalize_pubkey(instruction["programId"], field="programId")
        if instruction.get("program_id") is not None:
            return normalize_pubkey(instruction["program_id"], field="program_id")
        idx = instruction.get("programIdIndex", instruction.get("program_id_index"))
        if idx is None:
            raise SolanaAdapterError("instruction missing programId / programIdIndex")
        program_index = _non_negative_int(idx, "programIdIndex")
        try:
            return account_keys[program_index]
        except IndexError as exc:
            raise SolanaAdapterError(
                "programIdIndex is outside resolved account keys"
            ) from exc

    def accounts_of(instruction: Mapping[str, Any]) -> tuple[tuple[int, ...], tuple[str, ...]]:
        values = instruction.get("accounts") or ()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise SolanaAdapterError("instruction accounts must be a sequence")
        indexes: list[int] = []
        pubkeys: list[str] = []
        for value in values:
            if type(value) is int and not isinstance(value, bool):
                try:
                    pubkeys.append(account_keys[value])
                except IndexError as exc:
                    raise SolanaAdapterError(
                        "instruction account index is outside resolved account keys"
                    ) from exc
                indexes.append(value)
            else:
                pk = normalize_pubkey(value, field="instruction account")
                pubkeys.append(pk)
                if pk in index_by_pubkey:
                    indexes.append(index_by_pubkey[pk])
                else:
                    # Account named but not in resolved list — fail closed.
                    raise SolanaAdapterError(
                        f"instruction account {pk} not in resolved account keys"
                    )
        return tuple(indexes), tuple(pubkeys)

    def parsed_of(instruction: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
        parsed = instruction.get("parsed")
        if parsed is None:
            return "", {}
        if not isinstance(parsed, Mapping):
            raise SolanaAdapterError("instruction.parsed must be a mapping")
        kind = parsed.get("type", "")
        if kind is not None and kind != "" and not isinstance(kind, str):
            raise SolanaAdapterError("parsed instruction type must be a string")
        info = parsed.get("info") or {}
        if not isinstance(info, Mapping):
            raise SolanaAdapterError("parsed instruction info must be a mapping")
        return str(kind or ""), dict(info)

    def one(
        instruction: Mapping[str, Any],
        *,
        outer_index: int,
        inner_index: int | None,
    ) -> SolanaInstruction:
        indexes, pubs = accounts_of(instruction)
        ptype, pinfo = parsed_of(instruction)
        data = instruction.get("data", "")
        if data is None:
            data = ""
        if not isinstance(data, str):
            raise SolanaAdapterError("instruction data must be a string")
        stack = instruction.get("stackHeight", instruction.get("stack_height"))
        return SolanaInstruction(
            program_id=program_id_of(instruction),
            account_indexes=indexes,
            accounts=pubs,
            data=data,
            data_encoding=str(
                instruction.get("data_encoding", instruction.get("encoding", "base58"))
            ),
            outer_index=outer_index,
            inner_index=inner_index,
            stack_height=stack,
            parsed_type=ptype,
            parsed_info=pinfo,
            attributes={
                "program": instruction.get("program", ""),
            },
        )

    result: list[SolanaInstruction] = []
    meta = meta or {}
    inner_groups_raw = meta.get("innerInstructions", meta.get("inner_instructions"))

    if inner_instructions_present is False or (
        inner_instructions_present is None and inner_groups_raw is None and meta
    ):
        # Meta present but no innerInstructions field: incomplete coverage.
        if meta and "innerInstructions" not in meta and "inner_instructions" not in meta:
            missing.append("inner_instructions")
            unsupported.append(
                UnsupportedField(
                    path="meta.innerInstructions",
                    reason=(
                        "inner instruction coverage absent; CPI tree not invented"
                    ),
                )
            )

    inner_by_outer: dict[int, Sequence[object]] = {}
    if inner_groups_raw is not None:
        if not isinstance(inner_groups_raw, Sequence) or isinstance(
            inner_groups_raw, (str, bytes)
        ):
            raise SolanaAdapterError("meta.innerInstructions must be a sequence")
        for group in inner_groups_raw:
            if not isinstance(group, Mapping):
                raise SolanaAdapterError("inner instruction group must be a mapping")
            index = _non_negative_int(
                group.get("index"), "inner instruction outer index"
            )
            values = group.get("instructions")
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise SolanaAdapterError("inner instructions must be a sequence")
            if index in inner_by_outer:
                raise SolanaAdapterError("duplicate inner instruction outer index")
            inner_by_outer[index] = values

    for outer_index, value in enumerate(outer):
        if not isinstance(value, Mapping):
            raise SolanaAdapterError("outer instruction must be a mapping")
        result.append(one(value, outer_index=outer_index, inner_index=None))
        for inner_index, inner in enumerate(inner_by_outer.get(outer_index, ())):
            if not isinstance(inner, Mapping):
                raise SolanaAdapterError("inner instruction must be a mapping")
            result.append(
                one(inner, outer_index=outer_index, inner_index=inner_index)
            )

    unknown_groups = set(inner_by_outer) - set(range(len(outer)))
    if unknown_groups:
        raise SolanaAdapterError(
            "inner instructions reference a missing outer index"
        )

    return tuple(result), missing, unsupported


# ---------------------------------------------------------------------------
# Structured input records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SolanaTransactionObservation:
    """Observed Solana transaction facts from a wallet (observation authority).

    Message, meta, logs, balances, and inner instructions are preserved when
    present.  Explicit absences survive conversion and never become fabricated
    success, finality, or CPI coverage.
    """

    observation_id: str
    signature: str
    chain_id: str = SOLANA_MAINNET_CHAIN_ID
    network: str = ""
    genesis_hash: str = ""
    slot: int | None = None
    blockhash: str = ""
    block_time: int | None = None
    transaction_index: int | None = None
    commitment: str = ""
    retraction: str = ""
    observed_at: str = ""
    validity_start: str = ""
    validity_end: str = ""
    version: str = ""
    message: Mapping[str, Any] | None = None
    meta: Mapping[str, Any] | None = None
    signatures: Sequence[str] | None = None
    log_messages: Sequence[str] | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        object.__setattr__(
            self, "signature", normalize_signature(self.signature, field="signature")
        )
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", allow_empty=True)
        )
        for name in (
            "network",
            "genesis_hash",
            "blockhash",
            "commitment",
            "retraction",
            "observed_at",
            "validity_start",
            "validity_end",
            "version",
        ):
            raw = getattr(self, name)
            if name == "blockhash" and raw:
                object.__setattr__(
                    self, name, normalize_blockhash(raw, field="blockhash")
                )
            else:
                object.__setattr__(
                    self, name, _text(raw, name, allow_empty=True)
                )
        object.__setattr__(self, "slot", _optional_non_negative_int(self.slot, "slot"))
        object.__setattr__(
            self, "block_time", _optional_non_negative_int(self.block_time, "block_time")
        )
        object.__setattr__(
            self,
            "transaction_index",
            _optional_non_negative_int(self.transaction_index, "transaction_index"),
        )
        if self.message is not None:
            object.__setattr__(
                self, "message", _attributes(_as_mapping(self.message, "message"))
            )
        if self.meta is not None:
            object.__setattr__(
                self, "meta", _attributes(_as_mapping(self.meta, "meta"))
            )
        if self.signatures is not None:
            if isinstance(self.signatures, (str, bytes, bytearray)) or not isinstance(
                self.signatures, Sequence
            ):
                raise SolanaAdapterError("signatures must be a sequence")
            object.__setattr__(
                self,
                "signatures",
                tuple(
                    normalize_signature(s, field=f"signatures[{i}]")
                    for i, s in enumerate(self.signatures)
                ),
            )
        if self.log_messages is not None:
            if isinstance(self.log_messages, (str, bytes, bytearray)) or not isinstance(
                self.log_messages, Sequence
            ):
                raise SolanaAdapterError("log_messages must be a sequence of strings")
            object.__setattr__(
                self,
                "log_messages",
                tuple(_text(item, "log_message") for item in self.log_messages),
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "block_time": self.block_time,
            "blockhash": self.blockhash,
            "chain_id": self.chain_id,
            "commitment": self.commitment,
            "genesis_hash": self.genesis_hash,
            "kind": SolanaPayloadKind.TRANSACTION_OBSERVATION.value,
            "log_messages": None
            if self.log_messages is None
            else list(self.log_messages),
            "message": None if self.message is None else thaw_json(self.message),
            "meta": None if self.meta is None else thaw_json(self.meta),
            "network": self.network,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "raw": thaw_json(self.raw),
            "retraction": self.retraction,
            "signature": self.signature,
            "signatures": None
            if self.signatures is None
            else list(self.signatures),
            "slot": self.slot,
            "transaction_index": self.transaction_index,
            "validity_end": self.validity_end,
            "validity_start": self.validity_start,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolanaTransactionObservation":
        value = _as_mapping(value, "SolanaTransactionObservation")
        # Accept nested RPC shapes: transaction.transaction / transaction.meta
        message = value.get("message")
        meta = value.get("meta")
        signatures = value.get("signatures")
        version = value.get("version", "")
        nested = value.get("transaction")
        if isinstance(nested, Mapping):
            if message is None and isinstance(nested.get("message"), Mapping):
                message = nested["message"]
            if signatures is None:
                signatures = nested.get("signatures")
            if meta is None and isinstance(nested.get("meta"), Mapping):
                meta = nested["meta"]
            # RPC getTransaction shape: {transaction: {signatures, message}, meta, version}
            inner_tx = nested.get("transaction")
            if isinstance(inner_tx, Mapping):
                if message is None:
                    message = inner_tx.get("message")
                if signatures is None:
                    signatures = inner_tx.get("signatures")
            if version == "" and nested.get("version") is not None:
                version = nested.get("version", "")
        if meta is None and isinstance(value.get("transaction"), Mapping):
            # top-level meta may live beside nested transaction
            pass
        if version == "":
            version = value.get("version", "")
        signature = value.get(
            "signature",
            value.get("tx_hash", value.get("transaction_hash", "")),
        )
        if not signature and signatures:
            signature = signatures[0]
        logs = value.get("log_messages", value.get("logMessages"))
        if logs is None and isinstance(meta, Mapping):
            logs = meta.get("logMessages", meta.get("log_messages"))
        return cls(
            observation_id=value.get("observation_id", value.get("id", "")),
            signature=signature or "",
            chain_id=value.get("chain_id", value.get("cluster", SOLANA_MAINNET_CHAIN_ID)),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            slot=value.get("slot"),
            blockhash=value.get("blockhash", value.get("block_hash", "")),
            block_time=value.get("block_time", value.get("blockTime")),
            transaction_index=value.get(
                "transaction_index", value.get("transactionIndex")
            ),
            commitment=value.get(
                "commitment", value.get("confirmation_status", value.get("confirmationStatus", ""))
            ),
            retraction=value.get("retraction", ""),
            observed_at=value.get("observed_at", ""),
            validity_start=value.get("validity_start", ""),
            validity_end=value.get("validity_end", ""),
            version=str(version) if version is not None else "",
            message=message,
            meta=meta if meta is not None else value.get("meta"),
            signatures=signatures,
            log_messages=logs,
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


@dataclass(frozen=True, slots=True)
class SolanaMessageCandidate:
    """Unsigned Solana message candidate (declaration authority).

    Used for preflight of versioned/legacy messages before signing.  Account
    privileges and instruction order are required for semantic fidelity.
    """

    intent_id: str
    chain_id: str = SOLANA_MAINNET_CHAIN_ID
    network: str = ""
    genesis_hash: str = ""
    version: str = "legacy"
    recent_blockhash: str = ""
    message: Mapping[str, Any] = field(default_factory=dict)
    fee_payer: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", allow_empty=True)
        )
        object.__setattr__(
            self, "network", _text(self.network, "network", allow_empty=True)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _text(self.genesis_hash, "genesis_hash", allow_empty=True),
        )
        object.__setattr__(
            self, "version", normalize_message_version(self.version or "legacy")
        )
        if self.recent_blockhash:
            object.__setattr__(
                self,
                "recent_blockhash",
                normalize_blockhash(self.recent_blockhash, field="recent_blockhash"),
            )
        else:
            object.__setattr__(self, "recent_blockhash", "")
        object.__setattr__(
            self, "message", _attributes(_as_mapping(self.message, "message"))
        )
        if self.fee_payer:
            object.__setattr__(
                self, "fee_payer", normalize_pubkey(self.fee_payer, field="fee_payer")
            )
        else:
            object.__setattr__(self, "fee_payer", "")
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "fee_payer": self.fee_payer,
            "genesis_hash": self.genesis_hash,
            "intent_id": self.intent_id,
            "kind": SolanaPayloadKind.MESSAGE_CANDIDATE.value,
            "message": thaw_json(self.message),
            "network": self.network,
            "raw": thaw_json(self.raw),
            "recent_blockhash": self.recent_blockhash,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolanaMessageCandidate":
        value = _as_mapping(value, "SolanaMessageCandidate")
        message = value.get("message", {})
        if not isinstance(message, Mapping):
            message = {}
        recent = value.get(
            "recent_blockhash",
            value.get("recentBlockhash", message.get("recentBlockhash", "")),
        )
        return cls(
            intent_id=value.get("intent_id", value.get("id", "")),
            chain_id=value.get("chain_id", value.get("cluster", SOLANA_MAINNET_CHAIN_ID)),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            version=value.get("version", "legacy"),
            recent_blockhash=recent or "",
            message=message,
            fee_payer=value.get("fee_payer", value.get("feePayer", "")),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def default_solana_capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=SOLANA_CAPABILITY_ID,
        kind=CapabilityKind.CHAIN_ADAPTER,
        implementation_version=SOLANA_ADAPTER_IMPLEMENTATION_VERSION,
        semantic_version=SOLANA_ADAPTER_SEMANTIC_VERSION,
        status=CapabilityStatus.AVAILABLE,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=(SOLANA_NAMESPACE,),
        features=(
            "wallet_records",
            "transaction_observation",
            "message_candidate",
            "program_instructions",
            "account_privileges",
            "inner_instructions",
            "token_balances",
            "program_logs",
            "slot_commitment",
            "versioned_messages",
            "address_lookup_tables",
        ),
        summary=(
            "Solana wallet observation and message conversion into Crypto IR "
            "with exact account-order and privilege semantics"
        ),
        attributes={
            "known_clusters": sorted(
                {
                    a.chain_id
                    for a in KNOWN_NETWORKS.values()
                }
            ),
            "preserves_raw_evidence": True,
            "invents_missing_facts": False,
            "account_order_semantic": True,
            "privilege_bits_semantic": True,
        },
    )


class SolanaWalletAdapter:
    """Side-effect-free Solana wallet → Crypto IR adapter.

    Implements :class:`~ipfs_datasets_py.logic.crypto_ir.adapters.CryptoIRAdapter`.
    """

    def __init__(
        self,
        *,
        adapter_id: str = SOLANA_ADAPTER_ID,
        capability: CapabilityDescriptor | None = None,
    ) -> None:
        self._adapter_id = _text(adapter_id, "adapter_id")
        if capability is None:
            capability = default_solana_capability()
        if not isinstance(capability, CapabilityDescriptor):
            raise SolanaAdapterError("capability must be a CapabilityDescriptor")
        if not capability.side_effect_free:
            raise SolanaAdapterError(
                "Solana adapter capability must be side-effect-free"
            )
        self._capability = capability

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def capability(self) -> CapabilityDescriptor:
        return self._capability

    def supports_chain_namespace(self, namespace: str) -> bool:
        return self._capability.supports_chain_namespace(namespace)

    def convert(
        self,
        payload: Mapping[str, Any]
        | SolanaTransactionObservation
        | SolanaMessageCandidate,
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        """Convert *payload* without elevating authority or inventing facts."""

        if isinstance(payload, SolanaTransactionObservation):
            payload_map: Mapping[str, Any] = payload.to_dict()
        elif isinstance(payload, SolanaMessageCandidate):
            payload_map = payload.to_dict()
        elif isinstance(payload, Mapping):
            payload_map = payload
        else:
            raise SolanaAdapterError(
                "payload must be a mapping or Solana structured record"
            )

        source_digest = f"sha256:{content_sha256_hex(dict(payload_map))}"
        provenance_dict: dict[str, Any] = {}
        source_authority = AuthorityKind.OBSERVATION

        try:
            kind = self._detect_kind(payload_map)
            default_authority = (
                AuthorityKind.OBSERVATION
                if kind is SolanaPayloadKind.TRANSACTION_OBSERVATION
                else AuthorityKind.DECLARATION
            )
            provenance_dict, source_authority = self._resolve_provenance(
                source_provenance, default=default_authority
            )
            if source_authority is AuthorityKind.AUTHORIZATION:
                raise SolanaAdapterError(
                    "cannot convert authorization-authority payload through "
                    "Solana adapter"
                )
            result_authority = source_authority

            if kind is SolanaPayloadKind.TRANSACTION_OBSERVATION:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_observation(payload_map)
                )
            elif kind is SolanaPayloadKind.MESSAGE_CANDIDATE:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_message_candidate(payload_map)
                )
            elif kind is SolanaPayloadKind.SERIALIZED_CANDIDATE:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_serialized_candidate(payload_map)
                )
            else:
                raise SolanaAdapterError(f"unsupported Solana payload kind: {kind!r}")
        except SolanaAdapterError as exc:
            return AdapterConversionResult(
                conversion_id=f"solana-error:{self._adapter_id}",
                adapter_id=self._adapter_id,
                capability_id=self._capability.capability_id,
                status=AdapterConversionStatus.ERROR,
                source_authority=source_authority,
                result_authority=source_authority,
                source_digest=source_digest,
                result_payload={},
                unsupported_fields=(),
                preserved_provenance=provenance_dict,
                diagnostics=(str(exc),),
                attributes={"error": True, "chain_namespace": SOLANA_NAMESPACE},
            )

        result_digest = f"sha256:{content_sha256_hex(result_payload)}"
        conversion_id = f"solana:{kind.value}:{result_digest[:18]}"
        return AdapterConversionResult(
            conversion_id=conversion_id,
            adapter_id=self._adapter_id,
            capability_id=self._capability.capability_id,
            status=status,
            source_authority=source_authority,
            result_authority=result_authority,
            source_digest=source_digest,
            result_digest=result_digest,
            result_payload=result_payload,
            unsupported_fields=unsupported,
            preserved_provenance=provenance_dict,
            diagnostics=diagnostics,
            attributes={
                "chain_namespace": SOLANA_NAMESPACE,
                "payload_kind": kind.value,
                "preserves_raw_evidence": True,
                "account_order_semantic": True,
                "privilege_bits_semantic": True,
            },
        )

    def _resolve_provenance(
        self,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None,
        *,
        default: AuthorityKind = AuthorityKind.OBSERVATION,
    ) -> tuple[dict[str, Any], AuthorityKind]:
        if source_provenance is None:
            return {}, default
        if isinstance(source_provenance, CryptoIRProvenance):
            return source_provenance.to_dict(), source_provenance.authority.kind
        if isinstance(source_provenance, Mapping):
            data = dict(source_provenance)
            authority = data.get("authority", {})
            if isinstance(authority, Mapping) and "kind" in authority:
                try:
                    kind = AuthorityKind(authority["kind"])
                except (TypeError, ValueError) as exc:
                    raise SolanaAdapterError(
                        f"unsupported source authority: {authority['kind']!r}"
                    ) from exc
            else:
                kind = default
            return data, kind
        raise SolanaAdapterError(
            "source_provenance must be CryptoIRProvenance or mapping"
        )

    def _detect_kind(self, payload: Mapping[str, Any]) -> SolanaPayloadKind:
        kind_raw = payload.get("kind", payload.get("payload_kind", ""))
        if kind_raw:
            text = _text(str(kind_raw), "kind").lower().replace("-", "_")
            aliases = {
                "transaction_observation": SolanaPayloadKind.TRANSACTION_OBSERVATION,
                "observation": SolanaPayloadKind.TRANSACTION_OBSERVATION,
                "solana_transaction_observation": SolanaPayloadKind.TRANSACTION_OBSERVATION,
                "message_candidate": SolanaPayloadKind.MESSAGE_CANDIDATE,
                "unsigned_message": SolanaPayloadKind.MESSAGE_CANDIDATE,
                "solana_message_candidate": SolanaPayloadKind.MESSAGE_CANDIDATE,
                "serialized_candidate": SolanaPayloadKind.SERIALIZED_CANDIDATE,
                "candidate": SolanaPayloadKind.SERIALIZED_CANDIDATE,
            }
            if text in aliases:
                return aliases[text]
            raise SolanaAdapterError(f"unsupported Solana payload kind: {kind_raw!r}")
        if "signature" in payload or "slot" in payload or "meta" in payload:
            if "intent_id" in payload and "signature" not in payload:
                return SolanaPayloadKind.MESSAGE_CANDIDATE
            return SolanaPayloadKind.TRANSACTION_OBSERVATION
        if "intent_id" in payload or "message" in payload or "recent_blockhash" in payload:
            if "payload_digest" in payload or "encoding" in payload:
                return SolanaPayloadKind.SERIALIZED_CANDIDATE
            return SolanaPayloadKind.MESSAGE_CANDIDATE
        if "payload_digest" in payload or "candidate_id" in payload:
            return SolanaPayloadKind.SERIALIZED_CANDIDATE
        raise SolanaAdapterError("unable to detect Solana payload kind")

    def _extract_transfers(
        self,
        instructions: Sequence[SolanaInstruction],
        *,
        chain: ChainIdentity,
        network: SolanaNetworkAnchor,
        failed: bool,
    ) -> list[dict[str, Any]]:
        """Extract native/token transfers only from parsed successful effects."""

        if failed:
            return []
        transfers: list[dict[str, Any]] = []
        for instr in instructions:
            if instr.parsed_type not in {"transfer", "transferChecked"}:
                continue
            info = thaw_json(instr.parsed_info)
            if not isinstance(info, Mapping):
                continue
            if instr.program_id == SYSTEM_PROGRAM_ID and "lamports" in info:
                amount = parse_exact_base_units(info.get("lamports"), field="lamports")
                source = normalize_pubkey(info.get("source"), field="transfer.source")
                dest = normalize_pubkey(
                    info.get("destination"), field="transfer.destination"
                )
                transfers.append(
                    {
                        "kind": "native",
                        "asset": native_asset(chain, network).to_dict(),
                        "amount": ExactAmount(
                            base_units=amount, decimals=network.native_decimals
                        ).to_dict(),
                        "from_account": account_identity(source, chain).to_dict(),
                        "to_account": account_identity(dest, chain).to_dict(),
                        "outer_index": instr.outer_index,
                        "inner_index": instr.inner_index,
                        "program_id": instr.program_id,
                    }
                )
            elif instr.program_id in TOKEN_PROGRAM_IDS:
                source = normalize_pubkey(
                    info.get("source"), field="token transfer source"
                )
                dest = normalize_pubkey(
                    info.get("destination"), field="token transfer destination"
                )
                token_amount = info.get("tokenAmount", info.get("token_amount"))
                if token_amount is not None:
                    if not isinstance(token_amount, Mapping):
                        raise SolanaAdapterError("tokenAmount must be a mapping")
                    amount = parse_exact_base_units(
                        token_amount.get("amount"), field="SPL token amount"
                    )
                    decimals = _non_negative_int(
                        token_amount.get("decimals"), "SPL token decimals"
                    )
                    mint = normalize_pubkey(info.get("mint"), field="SPL token mint")
                else:
                    amount = parse_exact_base_units(
                        info.get("amount"), field="SPL token amount"
                    )
                    mint_raw = info.get("mint")
                    if mint_raw is None:
                        # Cannot invent mint/decimals for unchecked transfer.
                        continue
                    mint = normalize_pubkey(mint_raw, field="SPL token mint")
                    decimals = None
                asset = token_asset(
                    chain,
                    mint,
                    decimals=decimals,
                    program_id=instr.program_id,
                )
                transfers.append(
                    {
                        "kind": "token",
                        "asset": asset.to_dict(),
                        "amount": ExactAmount(
                            base_units=amount,
                            decimals=asset.decimals if decimals is not None else 0,
                        ).to_dict(),
                        "from_account": account_identity(
                            source, chain, account_kind="token_account"
                        ).to_dict(),
                        "to_account": account_identity(
                            dest, chain, account_kind="token_account"
                        ).to_dict(),
                        "decimals_absent": decimals is None,
                        "outer_index": instr.outer_index,
                        "inner_index": instr.inner_index,
                        "program_id": instr.program_id,
                    }
                )
        return transfers

    def _convert_observation(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        obs = SolanaTransactionObservation.from_dict(payload)
        network = resolve_network(
            chain_id=obs.chain_id or None,
            network=obs.network or None,
            genesis_hash=obs.genesis_hash or None,
        )
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []

        # Version — unsupported versions already fail in normalize when set.
        version_raw = obs.version
        if not version_raw and obs.message is not None:
            # version may only be on the envelope
            version_raw = payload.get("version", "legacy")
        try:
            version = normalize_message_version(version_raw or "legacy")
        except SolanaAdapterError:
            raise

        commitment = (
            map_commitment(obs.commitment) if obs.commitment else FinalityStatus.UNKNOWN
        )
        if not obs.commitment:
            missing_coverage.append("commitment")
            unsupported.append(
                UnsupportedField(
                    path="commitment",
                    reason="commitment absent; left as unknown (not invented)",
                )
            )
        retraction = (
            map_retraction(obs.retraction)
            if obs.retraction
            else RetractionStatus.UNKNOWN
        )
        if not obs.retraction:
            missing_coverage.append("retraction")

        privileges: tuple[AccountPrivilege, ...] = ()
        lookup_tables: tuple[AddressLookupTableRef, ...] = ()
        instructions: tuple[SolanaInstruction, ...] = ()
        message_dict: dict[str, Any] | None = (
            thaw_json(obs.message) if obs.message is not None else None
        )
        meta_dict: dict[str, Any] | None = (
            thaw_json(obs.meta) if obs.meta is not None else None
        )

        if message_dict is None:
            missing_coverage.append("message")
            unsupported.append(
                UnsupportedField(
                    path="message",
                    reason="message absent; account order and instructions not invented",
                )
            )
        else:
            privileges, lookup_tables = resolve_account_privileges(
                message_dict, meta_dict
            )
            instrs, instr_missing, instr_unsup = parse_instructions(
                message_dict, meta_dict, privileges
            )
            instructions = instrs
            missing_coverage.extend(instr_missing)
            unsupported.extend(instr_unsup)

        if meta_dict is None:
            missing_coverage.append("meta")
            unsupported.append(
                UnsupportedField(
                    path="meta",
                    reason=(
                        "meta absent; fee, balances, inner instructions, and "
                        "error status not invented"
                    ),
                )
            )

        failed = False
        fee_lamports: str | None = None
        if meta_dict is not None:
            failed = meta_dict.get("err") is not None
            if "fee" in meta_dict:
                fee_lamports = parse_exact_base_units(meta_dict.get("fee"), field="fee")
            else:
                missing_coverage.append("fee")
                unsupported.append(
                    UnsupportedField(
                        path="meta.fee",
                        reason="fee absent; not invented as zero",
                    )
                )

        # Logs
        logs_list: list[str] | None
        if obs.log_messages is not None:
            logs_list = list(obs.log_messages)
        elif meta_dict is not None and isinstance(
            meta_dict.get("logMessages") or meta_dict.get("log_messages"), list
        ):
            raw_logs = meta_dict.get("logMessages") or meta_dict.get("log_messages")
            logs_list = [str(item) for item in raw_logs]
        else:
            logs_list = None
            missing_coverage.append("log_messages")
            unsupported.append(
                UnsupportedField(
                    path="log_messages",
                    reason="program logs absent; not invented from silence",
                )
            )

        if obs.slot is None:
            missing_coverage.append("slot")
            unsupported.append(
                UnsupportedField(
                    path="slot",
                    reason="slot absent; not invented",
                )
            )

        transfers = self._extract_transfers(
            instructions, chain=chain, network=network, failed=failed
        )

        # Fee payer / first signer
        fee_payer_account = None
        signers = [p for p in privileges if p.is_signer]
        if signers:
            fee_payer_account = account_identity(
                signers[0].pubkey,
                chain,
                account_kind="signer",
                is_signer=True,
                is_writable=signers[0].is_writable,
                account_index=signers[0].account_index,
            )
        else:
            if privileges:
                diagnostics.append("no signer accounts in privilege list")
            missing_coverage.append("fee_payer")

        coordinate = LedgerCoordinate(
            sequence=obs.slot,
            hash=obs.blockhash,
            transaction_index=obs.transaction_index,
        )

        observed_at = obs.observed_at or "1970-01-01T00:00:00Z"
        if not obs.observed_at:
            diagnostics.append(
                "observed_at absent; placeholder epoch used only for schema validity"
            )
            missing_coverage.append("observed_at")

        provenance = observation_provenance(
            producer_id=self._adapter_id,
            observed_at=observed_at,
            finality=commitment,
            validity_start=obs.validity_start,
            validity_end=obs.validity_end,
            retraction_status=retraction,
        )

        # Participants preserve privilege order (semantic account order).
        participants = [
            account_identity(
                p.pubkey,
                chain,
                account_kind="signer" if p.is_signer else "account",
                is_signer=p.is_signer,
                is_writable=p.is_writable,
                account_index=p.account_index,
            ).to_dict()
            for p in privileges
        ]

        observed = ObservedTransaction(
            observation_id=obs.observation_id,
            chain=chain,
            tx_digest=sha256_digest_tag(obs.signature),
            coordinate=coordinate,
            finality=commitment,
            retraction=retraction,
            validity=ValidityWindow(
                start=obs.validity_start, end=obs.validity_end
            ),
            from_account=fee_payer_account,
            to_account=None,
            provenance=provenance,
            attributes={
                "signature": obs.signature,
                "signatures": list(obs.signatures or (obs.signature,)),
                "version": version,
                "commitment_raw": obs.commitment,
                "failed": failed,
                "error": None if meta_dict is None else meta_dict.get("err"),
                "fee_lamports": fee_lamports,
                "fee_absent": fee_lamports is None,
                "meta_present": meta_dict is not None,
                "message_present": message_dict is not None,
                "logs_present": logs_list is not None,
                "inner_instructions_present": (
                    meta_dict is not None
                    and (
                        "innerInstructions" in meta_dict
                        or "inner_instructions" in meta_dict
                    )
                ),
                "instruction_count": len(instructions),
                "outer_instruction_count": sum(
                    1 for i in instructions if i.inner_index is None
                ),
                "inner_instruction_count": sum(
                    1 for i in instructions if i.inner_index is not None
                ),
                "account_privilege_count": len(privileges),
                "lookup_table_count": len(lookup_tables),
                "transfer_count": len(transfers),
                "block_time": obs.block_time,
                "missing_coverage": list(missing_coverage),
                "raw": thaw_json(obs.raw),
                "source_attributes": thaw_json(obs.attributes),
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
            },
        )

        completeness_status = (
            CompletenessStatus.COMPLETE
            if not missing_coverage
            else CompletenessStatus.PARTIAL
            if len(missing_coverage) < 6
            else CompletenessStatus.UNKNOWN
        )
        completeness = CompletenessReceipt(
            receipt_id=f"cmp-{obs.observation_id}",
            chain=chain,
            scope=f"solana-tx:{obs.signature}",
            completeness=completeness_status,
            finality=commitment,
            validity=ValidityWindow(start=obs.validity_start, end=obs.validity_end),
            retraction=retraction,
            covered_ranges=(coordinate,) if obs.slot is not None else (),
            missing_ranges=(),
            provider_ids=(self._adapter_id,),
            attributes={
                "missing_coverage": list(missing_coverage),
                "meta_present": meta_dict is not None,
                "message_present": message_dict is not None,
                "logs_present": logs_list is not None,
            },
        )

        result_payload = {
            "record_type": "solana_transaction_observation",
            "authority": AuthorityKind.OBSERVATION.value,
            "chain": chain.to_dict(),
            "observed_transaction": observed.to_dict(),
            "account_privileges": [p.to_dict() for p in privileges],
            "participants": participants,
            "instructions": [i.to_dict() for i in instructions],
            "address_lookup_tables": [t.to_dict() for t in lookup_tables],
            "transfers": transfers,
            "fee": None
            if fee_lamports is None
            else {
                "asset": native_asset(chain, network).to_dict(),
                "amount": ExactAmount(
                    base_units=fee_lamports, decimals=network.native_decimals
                ).to_dict(),
                "kind": "fee",
            },
            "failed": failed,
            "version": version,
            "commitment": commitment.value,
            "commitment_raw": obs.commitment,
            "slot": obs.slot,
            "blockhash": obs.blockhash,
            "block_time": obs.block_time,
            "signature": obs.signature,
            "meta": meta_dict,
            "message": message_dict,
            "log_messages": logs_list,
            "completeness": completeness.to_dict(),
            "missing_coverage": list(missing_coverage),
            "raw": thaw_json(obs.raw),
        }

        status = (
            AdapterConversionStatus.SUCCEEDED
            if not missing_coverage
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"cluster={network.chain_id};network={network.network};"
            f"genesis={network.genesis_hash};version={version};"
            f"commitment={commitment.value}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _convert_message_candidate(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        candidate = SolanaMessageCandidate.from_dict(payload)
        network = resolve_network(
            chain_id=candidate.chain_id or None,
            network=candidate.network or None,
            genesis_hash=candidate.genesis_hash or None,
        )
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []

        version = candidate.version
        message_dict = thaw_json(candidate.message)
        if not message_dict:
            raise SolanaAdapterError("message_candidate requires a message mapping")

        # Versioned messages without loaded addresses: resolve with empty meta
        # unless lookups are declared (then fail closed for partial resolution).
        lookups = message_dict.get("addressTableLookups") or message_dict.get(
            "address_table_lookups"
        )
        meta_for_resolve: dict[str, Any] | None = None
        if lookups:
            loaded = payload.get("loaded_addresses") or payload.get("loadedAddresses")
            if not loaded:
                raise SolanaAdapterError(
                    "versioned message with addressTableLookups requires "
                    "resolved loadedAddresses; partial resolution fails closed"
                )
            meta_for_resolve = {"loadedAddresses": loaded}

        privileges, lookup_tables = resolve_account_privileges(
            message_dict, meta_for_resolve
        )
        instructions, instr_missing, instr_unsup = parse_instructions(
            message_dict, None, privileges
        )
        missing_coverage.extend(instr_missing)
        unsupported.extend(instr_unsup)

        fee_payer = candidate.fee_payer
        signers = [p for p in privileges if p.is_signer]
        if not fee_payer and signers:
            fee_payer = signers[0].pubkey
        if not fee_payer:
            missing_coverage.append("fee_payer")
            unsupported.append(
                UnsupportedField(
                    path="fee_payer",
                    reason="fee payer absent and no signer in privileges",
                )
            )

        recent = candidate.recent_blockhash or message_dict.get("recentBlockhash", "")
        if not recent:
            missing_coverage.append("recent_blockhash")
            unsupported.append(
                UnsupportedField(
                    path="recent_blockhash",
                    reason="recent blockhash absent; not invented",
                )
            )

        signer_requirements = tuple(
            SignerRequirement(
                account=account_identity(
                    p.pubkey,
                    chain,
                    account_kind="signer",
                    is_signer=True,
                    is_writable=p.is_writable,
                    account_index=p.account_index,
                ),
                role="fee_payer" if fee_payer and p.pubkey == fee_payer else "signer",
            )
            for p in signers
        )

        calls = tuple(
            CallIntent(
                target=account_identity(
                    instr.program_id, chain, account_kind="program"
                ),
                method=instr.parsed_type or "program_instruction",
                attributes={
                    "program_id": instr.program_id,
                    "outer_index": instr.outer_index,
                    "inner_index": instr.inner_index,
                    "account_indexes": list(instr.account_indexes),
                    "accounts": list(instr.accounts),
                    "data": instr.data,
                    "data_encoding": instr.data_encoding,
                    "parsed_info": thaw_json(instr.parsed_info),
                },
            )
            for instr in instructions
            if instr.inner_index is None  # outer only for intent surface
        )

        transfers_intent: list[TransferIntent] = []
        for item in self._extract_transfers(
            instructions, chain=chain, network=network, failed=False
        ):
            if item["kind"] in {"native", "token"}:
                transfers_intent.append(
                    TransferIntent(
                        asset=AssetIdentity.from_dict(item["asset"]),
                        amount=ExactAmount.from_dict(item["amount"]),
                        from_account=AccountIdentity.from_dict(item["from_account"]),
                        to_account=AccountIdentity.from_dict(item["to_account"]),
                        attributes={
                            "outer_index": item["outer_index"],
                            "inner_index": item["inner_index"],
                            "kind": item["kind"],
                        },
                    )
                )

        if not fee_payer:
            # UnsignedTransactionIntent requires a concrete origin account.
            raise SolanaAdapterError(
                "message_candidate requires fee_payer or at least one signer"
            )
        origin = account_identity(fee_payer, chain, account_kind="signer")
        if not signer_requirements:
            signer_requirements = (
                SignerRequirement(account=origin, role="fee_payer"),
            )

        unsigned = UnsignedTransactionIntent(
            intent_id=candidate.intent_id,
            chain=chain,
            origin=origin,
            signers=signer_requirements,
            calls=calls,
            transfers=tuple(transfers_intent),
            attributes={
                "version": version,
                "recent_blockhash": recent,
                "account_privileges": [p.to_dict() for p in privileges],
                "instructions": [i.to_dict() for i in instructions],
                "address_lookup_tables": [t.to_dict() for t in lookup_tables],
                "missing_coverage": list(missing_coverage),
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
                "raw": thaw_json(candidate.raw),
            },
        )

        result_payload = {
            "record_type": "solana_message_candidate",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "unsigned_transaction_intent": unsigned.to_dict(),
            "account_privileges": [p.to_dict() for p in privileges],
            "instructions": [i.to_dict() for i in instructions],
            "address_lookup_tables": [t.to_dict() for t in lookup_tables],
            "version": version,
            "recent_blockhash": recent,
            "fee_payer": fee_payer,
            "message": message_dict,
            "missing_coverage": list(missing_coverage),
            "raw": thaw_json(candidate.raw),
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not missing_coverage and not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"cluster={network.chain_id};network={network.network};"
            f"genesis={network.genesis_hash};version={version}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _convert_serialized_candidate(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        candidate_id = _identifier(
            payload.get("candidate_id", payload.get("id", "")), "candidate_id"
        )
        intent_id = _identifier(
            payload.get("intent_id", candidate_id), "intent_id"
        )
        network = resolve_network(
            chain_id=payload.get("chain_id") or payload.get("cluster") or None,
            network=payload.get("network") or None,
            genesis_hash=payload.get("genesis_hash") or None,
        )
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []

        raw_bytes = payload.get(
            "raw_tx", payload.get("serialized", payload.get("wire"))
        )
        payload_digest = payload.get("payload_digest", "")
        encoding = _text(payload.get("encoding", "base64"), "encoding")
        byte_length = payload.get("byte_length")

        raw_preserved: str | None = None
        if raw_bytes is not None:
            if not isinstance(raw_bytes, str):
                raise SolanaAdapterError("raw_tx must be a string")
            raw_preserved = raw_bytes
            if encoding in {"hex", "base16"}:
                text = raw_bytes[2:] if raw_bytes.startswith("0x") else raw_bytes
                if not _HEX_RE.fullmatch(raw_bytes if raw_bytes.startswith("0x") else text):
                    raise SolanaAdapterError("raw_tx is not valid hex")
                body = bytes.fromhex(text)
            elif encoding == "base58":
                body = decode_base58(raw_bytes, field="raw_tx")
            else:
                # base64 — store digest of utf-8 encoding of the string when
                # we cannot depend on stdlib decode failures inventing length.
                import base64

                try:
                    body = base64.b64decode(raw_bytes, validate=True)
                except Exception as exc:
                    raise SolanaAdapterError("raw_tx is not valid base64") from exc
            if byte_length is None:
                byte_length = len(body)
            if not payload_digest:
                payload_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
        else:
            if not payload_digest:
                raise SolanaAdapterError(
                    "serialized candidate requires raw_tx or payload_digest"
                )
            if byte_length is None:
                unsupported.append(
                    UnsupportedField(
                        path="byte_length",
                        reason="byte_length absent without raw bytes; not invented",
                    )
                )
                byte_length = 0
            diagnostics.append("raw_tx absent; digest-only candidate preserved")

        digest = _text(str(payload_digest), "payload_digest")
        if digest.startswith("0x") and len(digest) == 66:
            digest = f"sha256:{digest[2:]}"
        elif ":" not in digest and len(digest) == 64:
            digest = f"sha256:{digest}"

        version = payload.get("version", "")
        if version != "":
            version = normalize_message_version(version)

        candidate = SerializedTransactionCandidate(
            candidate_id=candidate_id,
            intent_id=intent_id,
            chain=chain,
            payload_digest=digest,
            encoding=encoding,
            byte_length=_non_negative_int(byte_length, "byte_length"),
            attributes={
                "raw_tx": raw_preserved,
                "raw_tx_absent": raw_preserved is None,
                "version": version,
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
            },
        )
        result_payload = {
            "record_type": "solana_serialized_candidate",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "serialized_transaction_candidate": candidate.to_dict(),
            "raw_tx": raw_preserved,
            "raw_tx_absent": raw_preserved is None,
            "version": version,
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"cluster={network.chain_id};network={network.network};"
            f"genesis={network.genesis_hash}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status


def convert_solana_payload(
    payload: Mapping[str, Any]
    | SolanaTransactionObservation
    | SolanaMessageCandidate,
    *,
    source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    adapter: SolanaWalletAdapter | None = None,
) -> AdapterConversionResult:
    """Module-level helper around :class:`SolanaWalletAdapter.convert`."""

    return (adapter or SolanaWalletAdapter()).convert(
        payload, source_provenance=source_provenance
    )


__all__ = [
    "CRYPTO_IR_SOLANA_ADAPTER_DOMAIN",
    "SOLANA_ADAPTER_ID",
    "SOLANA_CAPABILITY_ID",
    "SOLANA_NAMESPACE",
    "SOLANA_MAINNET_CHAIN_ID",
    "SOLANA_MAINNET_GENESIS_HASH",
    "SOLANA_MAINNET_NETWORK",
    "SOLANA_DEVNET_CHAIN_ID",
    "SOLANA_DEVNET_GENESIS_HASH",
    "SOLANA_DEVNET_NETWORK",
    "SOLANA_TESTNET_CHAIN_ID",
    "SOLANA_TESTNET_GENESIS_HASH",
    "SOLANA_TESTNET_NETWORK",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "TOKEN_PROGRAM_IDS",
    "KNOWN_NETWORKS",
    "AccountKeySource",
    "AccountPrivilege",
    "AddressLookupTableRef",
    "SolanaAdapterError",
    "SolanaInstruction",
    "SolanaMessageCandidate",
    "SolanaNetworkAnchor",
    "SolanaPayloadKind",
    "SolanaTransactionObservation",
    "SolanaWalletAdapter",
    "account_identity",
    "content_sha256_hex",
    "convert_solana_payload",
    "decode_base58",
    "default_solana_capability",
    "encode_base58",
    "map_commitment",
    "map_retraction",
    "native_asset",
    "normalize_blockhash",
    "normalize_message_version",
    "normalize_pubkey",
    "normalize_signature",
    "parse_exact_base_units",
    "parse_instructions",
    "privileges_from_header",
    "privileges_from_json_parsed",
    "resolve_account_privileges",
    "resolve_network",
    "sha256_digest_tag",
    "token_asset",
]
