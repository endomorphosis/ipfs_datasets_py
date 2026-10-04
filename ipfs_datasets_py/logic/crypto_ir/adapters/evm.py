"""EVM wallet-to-Crypto-IR adapter (CRYPTOIR-G100 / CRYPTOIR-007).

Convert Ethereum and EVM wallet observations and unsigned transaction
candidates into chain-qualified Crypto IR without inventing missing receipt,
trace, token, or finality facts.

Design constraints:

* Import and conversion are side-effect free (no sockets, no package install).
* Chain ID and genesis identity bind every account, asset, and observation.
* Addresses retain original presentation plus lowercase and EIP-55 forms.
* Native and token amounts are exact base-unit strings (no binary floats).
* Calldata, receipts, logs, traces, finality, and missing coverage survive
  conversion as normalized fields and/or explicit absences.
* World Chain (``eip155:480``) remains a distinct network from Ethereum mainnet.
* Round trips never elevate observation authority to proof or authorization.

This module owns only the EVM adapter surface and its offline fixtures.
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


CRYPTO_IR_EVM_ADAPTER_DOMAIN: Final[str] = "crypto-ir.adapter.evm"
EVM_NAMESPACE: Final[str] = "eip155"
EVM_ADAPTER_ID: Final[str] = "crypto-ir.adapter.evm"
EVM_CAPABILITY_ID: Final[str] = "crypto-ir.chain-adapter.evm"
EVM_ADAPTER_IMPLEMENTATION_VERSION: Final[str] = "1.0.0"
EVM_ADAPTER_SEMANTIC_VERSION: Final[str] = "1.0.0"

ETHEREUM_MAINNET_CHAIN_ID: Final[int] = 1
ETHEREUM_MAINNET_NETWORK: Final[str] = "ethereum-mainnet"
ETHEREUM_MAINNET_GENESIS_HASH: Final[str] = (
    "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
)

WORLD_CHAIN_MAINNET_CHAIN_ID: Final[int] = 480
WORLD_CHAIN_MAINNET_NETWORK: Final[str] = "world-chain-mainnet"
WORLD_CHAIN_MAINNET_GENESIS_HASH: Final[str] = (
    "0x70d316d2e0973b62332ba2e9768dd7854298d7ffe77f0409ffdb8d859f2d3fa3"
)

WORLD_CHAIN_SEPOLIA_CHAIN_ID: Final[int] = 4801
WORLD_CHAIN_SEPOLIA_NETWORK: Final[str] = "world-chain-sepolia"
WORLD_CHAIN_SEPOLIA_GENESIS_HASH: Final[str] = (
    "0xf1deb67ee953f94d8545d2647918687fa8ba1f30fa6103771f11b7c483984070"
)

NATIVE_ASSET_NAMESPACE: Final[str] = "slip44"
NATIVE_ASSET_REFERENCE: Final[str] = "60"
NATIVE_DECIMALS: Final[int] = 18
NATIVE_SYMBOL: Final[str] = "ETH"

TRANSFER_TOPIC: Final[str] = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX_DATA_RE: Final[re.Pattern[str]] = re.compile(r"^0x(?:[0-9a-fA-F]{2})*$")
_QUANTITY_RE: Final[re.Pattern[str]] = re.compile(
    r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$"
)
_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^-?(0|[1-9][0-9]*)$")
_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"
)


class EVMAdapterError(CryptoIRAdapterError):
    """Raised when an EVM wallet payload cannot be converted fail-closed."""


class EVMPayloadKind(str, Enum):
    """Supported offline conversion payload kinds."""

    TRANSACTION_OBSERVATION = "transaction_observation"
    CALL_INTENT = "call_intent"
    SERIALIZED_CANDIDATE = "serialized_candidate"


@dataclass(frozen=True, slots=True)
class EVMNetworkAnchor:
    """Known EVM network identity (chain id + genesis binding)."""

    chain_id: int
    network: str
    genesis_hash: str
    display_name: str = ""
    native_symbol: str = NATIVE_SYMBOL
    native_decimals: int = NATIVE_DECIMALS

    def __post_init__(self) -> None:
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
        ):
            raise EVMAdapterError("chain_id must be a positive integer")
        object.__setattr__(self, "network", _text(self.network, "network"))
        object.__setattr__(
            self,
            "genesis_hash",
            normalize_hash(self.genesis_hash, field="genesis_hash"),
        )
        object.__setattr__(
            self,
            "display_name",
            _text(self.display_name, "display_name", allow_empty=True),
        )
        object.__setattr__(
            self,
            "native_symbol",
            _text(self.native_symbol, "native_symbol"),
        )
        if (
            isinstance(self.native_decimals, bool)
            or not isinstance(self.native_decimals, int)
            or not 0 <= self.native_decimals <= 255
        ):
            raise EVMAdapterError("native_decimals must be between 0 and 255")

    def to_chain_identity(self) -> ChainIdentity:
        return ChainIdentity(
            chain_namespace=EVM_NAMESPACE,
            network=self.network,
            genesis_digest=keccak_digest_tag(self.genesis_hash),
            chain_id=str(self.chain_id),
            display_name=self.display_name or self.network,
            attributes={
                "genesis_hash": self.genesis_hash,
                "namespace": EVM_NAMESPACE,
            },
        )


# ---------------------------------------------------------------------------
# Validation / normalization helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EVMAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise EVMAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise EVMAdapterError(f"{name} must not have surrounding whitespace")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EVMAdapterError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise EVMAdapterError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise EVMAdapterError(str(exc)) from exc


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _ID_RE.fullmatch(text):
        raise EVMAdapterError(f"{name} is not a stable identifier")
    return text


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise EVMAdapterError(f"{name} must be an integer")
    if value < 0:
        raise EVMAdapterError(f"{name} must be non-negative")
    return value


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, name)


def keccak256(data: bytes) -> bytes:
    """Return Keccak-256 digest (Ethereum, not NIST SHA3-256).

    Prefers ``eth_hash`` then ``pycryptodome`` when present.  Falls back to a
    pure-Python implementation so conversion never requires network installs.
    """

    if not isinstance(data, (bytes, bytearray)):
        raise EVMAdapterError("keccak256 input must be bytes")
    try:
        from eth_hash.auto import keccak as _eth_keccak  # type: ignore[import-untyped]

        return bytes(_eth_keccak(bytes(data)))
    except Exception:
        pass
    try:
        from Crypto.Hash import keccak as _crypto_keccak  # type: ignore[import-untyped]

        hasher = _crypto_keccak.new(digest_bits=256)
        hasher.update(bytes(data))
        return bytes(hasher.digest())
    except Exception:
        pass
    return _pure_keccak256(bytes(data))


def _pure_keccak256(data: bytes) -> bytes:
    """Minimal Keccak-f[1600] / Keccak-256 (rate 1088, capacity 512)."""

    rate = 136  # 1088 bits
    state = bytearray(200)
    # Absorb
    offset = 0
    while offset < len(data):
        block = data[offset : offset + rate]
        for i, byte in enumerate(block):
            state[i] ^= byte
        offset += len(block)
        if len(block) == rate:
            _keccak_f1600(state)
    # Padding: multi-rate 0x01 ... 0x80 (Keccak, not SHA3's 0x06)
    pad_index = len(data) % rate
    state[pad_index] ^= 0x01
    state[rate - 1] ^= 0x80
    _keccak_f1600(state)
    return bytes(state[:32])


def _keccak_f1600(state: bytearray) -> None:
    """In-place Keccak-f[1600] permutation over a 200-byte state."""

    # Convert to 25 little-endian 64-bit lanes.
    lanes = [
        int.from_bytes(state[i * 8 : (i + 1) * 8], "little") for i in range(25)
    ]
    round_constants = (
        0x0000000000000001,
        0x0000000000008082,
        0x800000000000808A,
        0x8000000080008000,
        0x000000000000808B,
        0x0000000080000001,
        0x8000000080008081,
        0x8000000000008009,
        0x000000000000008A,
        0x0000000000000088,
        0x0000000080008009,
        0x000000008000000A,
        0x000000008000808B,
        0x800000000000008B,
        0x8000000000008089,
        0x8000000000008003,
        0x8000000000008002,
        0x8000000000000080,
        0x000000000000800A,
        0x800000008000000A,
        0x8000000080008081,
        0x8000000000008080,
        0x0000000080000001,
        0x8000000080008008,
    )
    rot = (
        (0, 36, 3, 41, 18),
        (1, 44, 10, 45, 2),
        (62, 6, 43, 15, 61),
        (28, 55, 25, 21, 56),
        (27, 20, 39, 8, 14),
    )
    mask = (1 << 64) - 1

    def rol(value: int, shift: int) -> int:
        return ((value << shift) | (value >> (64 - shift))) & mask

    for rc in round_constants:
        # θ
        c = [lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                lanes[x + 5 * y] ^= d[x]
        # ρ and π
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = rol(lanes[x + 5 * y], rot[x][y])
        # χ
        for x in range(5):
            for y in range(5):
                lanes[x + 5 * y] = (
                    b[x + 5 * y]
                    ^ ((~b[((x + 1) % 5) + 5 * y]) & b[((x + 2) % 5) + 5 * y])
                ) & mask
        # ι
        lanes[0] ^= rc

    for i, lane in enumerate(lanes):
        state[i * 8 : (i + 1) * 8] = lane.to_bytes(8, "little")


def eip55_checksum_address(address: str) -> str:
    """Return the EIP-55 mixed-case checksum form of a 20-byte address."""

    if not isinstance(address, str) or not _ADDRESS_RE.fullmatch(address):
        raise EVMAdapterError("address must be a 20-byte 0x address")
    lower = address[2:].lower()
    digest = keccak256(lower.encode("ascii")).hex()
    chars: list[str] = ["0x"]
    for char, nibble in zip(lower, digest):
        chars.append(char.upper() if int(nibble, 16) >= 8 else char)
    return "".join(chars)


def normalize_address(value: object, *, field: str = "address") -> str:
    """Return lowercase 0x address; shape is always enforced."""

    if not isinstance(value, str) or not _ADDRESS_RE.fullmatch(value):
        raise EVMAdapterError(f"{field} must be a 20-byte 0x address")
    return value.lower()


def normalize_hash(value: object, *, field: str = "hash") -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise EVMAdapterError(f"{field} must be a 32-byte 0x hash")
    return value.lower()


def normalize_hex_data(value: object, *, field: str = "data") -> str:
    if not isinstance(value, str) or not _HEX_DATA_RE.fullmatch(value):
        raise EVMAdapterError(f"{field} must be 0x-prefixed even-length hex")
    return value.lower()


def parse_quantity(value: object, *, field: str = "quantity") -> int:
    """Parse EIP-1474 quantity or non-negative decimal integer string/int."""

    if type(value) is int and not isinstance(value, bool):
        if value < 0:
            raise EVMAdapterError(f"{field} must be non-negative")
        return value
    if isinstance(value, str):
        if _QUANTITY_RE.fullmatch(value):
            return int(value[2:], 16)
        if _DECIMAL_INTEGER.fullmatch(value) and not value.startswith("-"):
            return int(value, 10)
    raise EVMAdapterError(f"{field} must be a non-negative quantity")


def keccak_digest_tag(value_0x: str) -> str:
    """Tag a 0x hash as ``keccak256:<hex>`` for Crypto IR digest fields."""

    normalized = normalize_hash(value_0x, field="digest")
    return f"keccak256:{normalized[2:]}"


KNOWN_NETWORKS: Final[dict[int, EVMNetworkAnchor]] = {
    ETHEREUM_MAINNET_CHAIN_ID: EVMNetworkAnchor(
        chain_id=ETHEREUM_MAINNET_CHAIN_ID,
        network=ETHEREUM_MAINNET_NETWORK,
        genesis_hash=ETHEREUM_MAINNET_GENESIS_HASH,
        display_name="Ethereum Mainnet",
    ),
    WORLD_CHAIN_MAINNET_CHAIN_ID: EVMNetworkAnchor(
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        network=WORLD_CHAIN_MAINNET_NETWORK,
        genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        display_name="World Chain Mainnet",
    ),
    WORLD_CHAIN_SEPOLIA_CHAIN_ID: EVMNetworkAnchor(
        chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID,
        network=WORLD_CHAIN_SEPOLIA_NETWORK,
        genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
        display_name="World Chain Sepolia",
    ),
}


def content_sha256_hex(value: Any) -> str:
    """Return bare 64-char sha256 hex for a JSON-compatible value."""

    from ...ir_core.canonical import canonical_json_bytes

    frozen = freeze_json(value)
    digest_label = sha256_digest(canonical_json_bytes(frozen))
    if digest_label.startswith("sha256:"):
        return digest_label.split(":", 1)[1]
    return digest_label


def resolve_network(
    *,
    chain_id: int | str | None = None,
    network: str | None = None,
    genesis_hash: str | None = None,
    display_name: str = "",
) -> EVMNetworkAnchor:
    """Resolve a chain/genesis anchor without inventing identity.

    Known chain ids may omit genesis when the official anchor matches.  Unknown
    networks require an explicit genesis hash.
    """

    resolved_id: int | None = None
    if chain_id is not None:
        if isinstance(chain_id, str):
            if not chain_id.strip() or not chain_id.isdigit():
                raise EVMAdapterError("chain_id must be a positive decimal integer")
            resolved_id = int(chain_id, 10)
        elif type(chain_id) is int and not isinstance(chain_id, bool):
            resolved_id = chain_id
        else:
            raise EVMAdapterError("chain_id must be a positive integer")
        if resolved_id <= 0:
            raise EVMAdapterError("chain_id must be a positive integer")

    known = KNOWN_NETWORKS.get(resolved_id) if resolved_id is not None else None
    if known is not None:
        if genesis_hash is not None:
            provided = normalize_hash(genesis_hash, field="genesis_hash")
            if provided != known.genesis_hash:
                raise EVMAdapterError(
                    f"genesis_hash does not match known network for chain_id={resolved_id}"
                )
        if network is not None and network not in {
            known.network,
            known.network.removeprefix("world-chain-"),
            "mainnet" if known.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID else network,
            "sepolia" if known.chain_id == WORLD_CHAIN_SEPOLIA_CHAIN_ID else network,
        }:
            # Allow explicit alternate labels only when they equal the anchor.
            if network != known.network:
                # World Chain often appears as "mainnet"/"sepolia" in wallet code.
                if not (
                    (
                        known.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
                        and network in {"mainnet", "worldchain", "world-chain"}
                    )
                    or (
                        known.chain_id == WORLD_CHAIN_SEPOLIA_CHAIN_ID
                        and network in {"sepolia", "worldchain-sepolia"}
                    )
                    or (
                        known.chain_id == ETHEREUM_MAINNET_CHAIN_ID
                        and network in {"mainnet", "ethereum", "eth"}
                    )
                ):
                    raise EVMAdapterError(
                        f"network {network!r} does not match known chain_id={resolved_id}"
                    )
        return known

    if resolved_id is None:
        raise EVMAdapterError("chain_id is required for EVM conversion")
    if not genesis_hash:
        raise EVMAdapterError(
            "unknown EVM chain_id requires an explicit genesis_hash"
        )
    net_name = network or f"eip155-{resolved_id}"
    return EVMNetworkAnchor(
        chain_id=resolved_id,
        network=net_name,
        genesis_hash=genesis_hash,
        display_name=display_name or net_name,
    )


def account_identity(
    address: str,
    chain: ChainIdentity,
    *,
    account_kind: str = "eoa",
) -> AccountIdentity:
    """Build an AccountIdentity with original, lowercase, and EIP-55 forms."""

    original = _text(address, "address")
    if not _ADDRESS_RE.fullmatch(original):
        raise EVMAdapterError("address must be a 20-byte 0x address")
    normalized = original.lower()
    checksummed = eip55_checksum_address(normalized)
    return AccountIdentity(
        chain=chain,
        address_normalized=normalized,
        address_original=original,
        account_kind=account_kind,
        attributes={
            "address_checksummed": checksummed,
            "address_lowercase": normalized,
        },
    )


def native_asset(chain: ChainIdentity, network: EVMNetworkAnchor) -> AssetIdentity:
    return AssetIdentity(
        chain=chain,
        asset_namespace=NATIVE_ASSET_NAMESPACE,
        asset_reference=NATIVE_ASSET_REFERENCE,
        decimals=network.native_decimals,
        symbol=network.native_symbol,
        attributes={"kind": "native"},
    )


def token_asset(
    chain: ChainIdentity,
    contract: str,
    *,
    decimals: int | None,
    symbol: str = "",
    standard: str = "erc20",
) -> AssetIdentity:
    address = normalize_address(contract, field="token.contract")
    # Missing decimals is explicit absence — do not invent 18.
    attributes: dict[str, Any] = {
        "kind": "token",
        "standard": standard,
        "contract": address,
        "contract_checksummed": eip55_checksum_address(address),
    }
    if decimals is None:
        attributes["decimals_absent"] = True
        resolved_decimals = 0
    else:
        resolved_decimals = _non_negative_int(decimals, "token.decimals")
        if resolved_decimals > 255:
            raise EVMAdapterError("token.decimals must not exceed 255")
    return AssetIdentity(
        chain=chain,
        asset_namespace="erc20" if standard == "erc20" else standard,
        asset_reference=address,
        decimals=resolved_decimals,
        symbol=symbol,
        attributes=attributes,
    )


def map_finality(value: Any) -> FinalityStatus:
    """Map wallet finality labels; unknown/absent stays UNKNOWN (not invented)."""

    if value is None or value == "":
        return FinalityStatus.UNKNOWN
    if isinstance(value, FinalityStatus):
        return value
    text = _text(str(value), "finality").lower().replace("-", "_")
    aliases = {
        "unknown": FinalityStatus.UNKNOWN,
        "proposed": FinalityStatus.PROPOSED,
        "observed": FinalityStatus.PROPOSED,
        "included": FinalityStatus.PROPOSED,
        "pending": FinalityStatus.PROPOSED,
        "confirmed": FinalityStatus.CONFIRMED,
        "operationally_confirmed": FinalityStatus.CONFIRMED,
        "safe": FinalityStatus.CONFIRMED,
        "finalized": FinalityStatus.FINALIZED,
        "final": FinalityStatus.FINALIZED,
        "l1_settled": FinalityStatus.FINALIZED,
        "reorged": FinalityStatus.REORGED,
        "reverted": FinalityStatus.REORGED,
        "retracted": FinalityStatus.RETRACTED,
    }
    if text in aliases:
        return aliases[text]
    try:
        return FinalityStatus(text)
    except ValueError as exc:
        raise EVMAdapterError(f"unsupported finality: {value!r}") from exc


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
        raise EVMAdapterError(f"unsupported retraction: {value!r}") from exc


# ---------------------------------------------------------------------------
# Structured EVM input records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EVMCallIntent:
    """Unsigned EVM call intent from a wallet (declaration authority).

    Calldata is preserved both as raw hex and as a content digest.  Missing
    method selector labels remain explicit rather than guessed from bytecode.
    """

    intent_id: str
    chain_id: int
    from_address: str
    to_address: str
    value_wei: str = "0"
    data: str = "0x"
    method: str = ""
    gas_limit: int | None = None
    max_fee_per_gas: int | None = None
    max_priority_fee_per_gas: int | None = None
    nonce: int | None = None
    network: str = ""
    genesis_hash: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
        ):
            raise EVMAdapterError("chain_id must be a positive integer")
        object.__setattr__(
            self,
            "from_address",
            _text(self.from_address, "from_address"),
        )
        object.__setattr__(
            self,
            "to_address",
            _text(self.to_address, "to_address"),
        )
        if not _ADDRESS_RE.fullmatch(self.from_address):
            raise EVMAdapterError("from_address must be a 20-byte 0x address")
        if not _ADDRESS_RE.fullmatch(self.to_address):
            raise EVMAdapterError("to_address must be a 20-byte 0x address")
        if type(self.value_wei) is int and not isinstance(self.value_wei, bool):
            object.__setattr__(self, "value_wei", str(self.value_wei))
        value = _text(self.value_wei, "value_wei")
        if not _DECIMAL_INTEGER.fullmatch(value) or value.startswith("-"):
            raise EVMAdapterError("value_wei must be a non-negative decimal integer string")
        object.__setattr__(self, "value_wei", value)
        object.__setattr__(self, "data", normalize_hex_data(self.data, field="data"))
        object.__setattr__(
            self, "method", _text(self.method, "method", allow_empty=True)
        )
        object.__setattr__(
            self, "gas_limit", _optional_non_negative_int(self.gas_limit, "gas_limit")
        )
        object.__setattr__(
            self,
            "max_fee_per_gas",
            _optional_non_negative_int(self.max_fee_per_gas, "max_fee_per_gas"),
        )
        object.__setattr__(
            self,
            "max_priority_fee_per_gas",
            _optional_non_negative_int(
                self.max_priority_fee_per_gas, "max_priority_fee_per_gas"
            ),
        )
        object.__setattr__(
            self, "nonce", _optional_non_negative_int(self.nonce, "nonce")
        )
        object.__setattr__(
            self, "network", _text(self.network, "network", allow_empty=True)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _text(self.genesis_hash, "genesis_hash", allow_empty=True),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "data": self.data,
            "from_address": self.from_address,
            "gas_limit": self.gas_limit,
            "genesis_hash": self.genesis_hash,
            "intent_id": self.intent_id,
            "kind": EVMPayloadKind.CALL_INTENT.value,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "method": self.method,
            "network": self.network,
            "nonce": self.nonce,
            "raw": thaw_json(self.raw),
            "to_address": self.to_address,
            "value_wei": self.value_wei,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EVMCallIntent":
        value = _as_mapping(value, "EVMCallIntent")
        return cls(
            intent_id=value.get("intent_id", ""),
            chain_id=value.get("chain_id", 0),
            from_address=value.get("from_address", value.get("from", "")),
            to_address=value.get("to_address", value.get("to", "")),
            value_wei=value.get("value_wei", value.get("value", "0")),
            data=value.get("data", value.get("input", value.get("calldata", "0x"))),
            method=value.get("method", ""),
            gas_limit=value.get("gas_limit", value.get("gas")),
            max_fee_per_gas=value.get("max_fee_per_gas"),
            max_priority_fee_per_gas=value.get("max_priority_fee_per_gas"),
            nonce=value.get("nonce"),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


@dataclass(frozen=True, slots=True)
class EVMTransactionObservation:
    """Observed EVM transaction facts from a wallet (observation authority).

    Raw transaction, receipt, logs, and traces are preserved when present.
    Explicit absences (``receipt is None``, ``traces is None``) survive
    conversion and never become fabricated success/finality.
    """

    observation_id: str
    chain_id: int
    tx_hash: str
    from_address: str = ""
    to_address: str = ""
    value_wei: str | None = None
    input_data: str | None = None
    block_number: int | None = None
    block_hash: str = ""
    transaction_index: int | None = None
    finality: str = ""
    retraction: str = ""
    observed_at: str = ""
    validity_start: str = ""
    validity_end: str = ""
    network: str = ""
    genesis_hash: str = ""
    receipt: Mapping[str, Any] | None = None
    logs: Sequence[Mapping[str, Any]] | None = None
    traces: Sequence[Mapping[str, Any]] | None = None
    token_transfers: Sequence[Mapping[str, Any]] | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
        ):
            raise EVMAdapterError("chain_id must be a positive integer")
        object.__setattr__(
            self, "tx_hash", normalize_hash(self.tx_hash, field="tx_hash")
        )
        for name in ("from_address", "to_address"):
            raw = getattr(self, name)
            if raw in (None, ""):
                object.__setattr__(self, name, "")
            else:
                text = _text(raw, name)
                if not _ADDRESS_RE.fullmatch(text):
                    raise EVMAdapterError(f"{name} must be a 20-byte 0x address")
                object.__setattr__(self, name, text)
        if self.value_wei is not None:
            if type(self.value_wei) is int and not isinstance(self.value_wei, bool):
                object.__setattr__(self, "value_wei", str(self.value_wei))
            value = _text(self.value_wei, "value_wei")
            if not _DECIMAL_INTEGER.fullmatch(value) or value.startswith("-"):
                raise EVMAdapterError(
                    "value_wei must be a non-negative decimal integer string"
                )
            object.__setattr__(self, "value_wei", value)
        if self.input_data is not None:
            object.__setattr__(
                self,
                "input_data",
                normalize_hex_data(self.input_data, field="input_data"),
            )
        object.__setattr__(
            self,
            "block_number",
            _optional_non_negative_int(self.block_number, "block_number"),
        )
        if self.block_hash:
            object.__setattr__(
                self, "block_hash", normalize_hash(self.block_hash, field="block_hash")
            )
        else:
            object.__setattr__(self, "block_hash", "")
        object.__setattr__(
            self,
            "transaction_index",
            _optional_non_negative_int(self.transaction_index, "transaction_index"),
        )
        for name in (
            "finality",
            "retraction",
            "observed_at",
            "validity_start",
            "validity_end",
            "network",
            "genesis_hash",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        if self.receipt is not None:
            object.__setattr__(
                self, "receipt", _attributes(_as_mapping(self.receipt, "receipt"))
            )
        if self.logs is not None:
            if isinstance(self.logs, (str, bytes, bytearray)) or not isinstance(
                self.logs, Sequence
            ):
                raise EVMAdapterError("logs must be a sequence of mappings")
            object.__setattr__(
                self,
                "logs",
                tuple(_attributes(_as_mapping(item, "log")) for item in self.logs),
            )
        if self.traces is not None:
            if isinstance(self.traces, (str, bytes, bytearray)) or not isinstance(
                self.traces, Sequence
            ):
                raise EVMAdapterError("traces must be a sequence of mappings")
            object.__setattr__(
                self,
                "traces",
                tuple(_attributes(_as_mapping(item, "trace")) for item in self.traces),
            )
        if self.token_transfers is not None:
            if isinstance(self.token_transfers, (str, bytes, bytearray)) or not isinstance(
                self.token_transfers, Sequence
            ):
                raise EVMAdapterError("token_transfers must be a sequence of mappings")
            object.__setattr__(
                self,
                "token_transfers",
                tuple(
                    _attributes(_as_mapping(item, "token_transfer"))
                    for item in self.token_transfers
                ),
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "block_hash": self.block_hash,
            "block_number": self.block_number,
            "chain_id": self.chain_id,
            "finality": self.finality,
            "from_address": self.from_address,
            "genesis_hash": self.genesis_hash,
            "input_data": self.input_data,
            "kind": EVMPayloadKind.TRANSACTION_OBSERVATION.value,
            "logs": None if self.logs is None else [thaw_json(item) for item in self.logs],
            "network": self.network,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "raw": thaw_json(self.raw),
            "receipt": None if self.receipt is None else thaw_json(self.receipt),
            "retraction": self.retraction,
            "to_address": self.to_address,
            "token_transfers": None
            if self.token_transfers is None
            else [thaw_json(item) for item in self.token_transfers],
            "traces": None
            if self.traces is None
            else [thaw_json(item) for item in self.traces],
            "transaction_index": self.transaction_index,
            "tx_hash": self.tx_hash,
            "validity_end": self.validity_end,
            "validity_start": self.validity_start,
            "value_wei": self.value_wei,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EVMTransactionObservation":
        value = _as_mapping(value, "EVMTransactionObservation")
        return cls(
            observation_id=value.get("observation_id", value.get("id", "")),
            chain_id=value.get("chain_id", 0),
            tx_hash=value.get("tx_hash", value.get("hash", value.get("transaction_hash", ""))),
            from_address=value.get("from_address", value.get("from", "")),
            to_address=value.get("to_address", value.get("to", "")),
            value_wei=value.get("value_wei", value.get("value")),
            input_data=value.get("input_data", value.get("input", value.get("data"))),
            block_number=value.get("block_number", value.get("blockNumber")),
            block_hash=value.get("block_hash", value.get("blockHash", "")),
            transaction_index=value.get(
                "transaction_index", value.get("transactionIndex")
            ),
            finality=value.get("finality", ""),
            retraction=value.get("retraction", ""),
            observed_at=value.get("observed_at", ""),
            validity_start=value.get("validity_start", ""),
            validity_end=value.get("validity_end", ""),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            receipt=value.get("receipt"),
            logs=value.get("logs"),
            traces=value.get("traces"),
            token_transfers=value.get("token_transfers"),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def default_evm_capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=EVM_CAPABILITY_ID,
        kind=CapabilityKind.CHAIN_ADAPTER,
        implementation_version=EVM_ADAPTER_IMPLEMENTATION_VERSION,
        semantic_version=EVM_ADAPTER_SEMANTIC_VERSION,
        status=CapabilityStatus.AVAILABLE,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=(EVM_NAMESPACE,),
        features=(
            "wallet_records",
            "transaction_observation",
            "call_intent",
            "receipts",
            "logs",
            "traces",
            "token_transfers",
            "finality",
            "world_chain",
        ),
        summary="EVM wallet observation and unsigned call conversion into Crypto IR",
        attributes={
            "known_chain_ids": sorted(KNOWN_NETWORKS),
            "preserves_raw_evidence": True,
            "invents_missing_facts": False,
        },
    )


class EVMWalletAdapter:
    """Side-effect-free EVM wallet → Crypto IR adapter.

    Implements :class:`~ipfs_datasets_py.logic.crypto_ir.adapters.CryptoIRAdapter`.
    """

    def __init__(
        self,
        *,
        adapter_id: str = EVM_ADAPTER_ID,
        capability: CapabilityDescriptor | None = None,
    ) -> None:
        self._adapter_id = _text(adapter_id, "adapter_id")
        if capability is None:
            capability = default_evm_capability()
        if not isinstance(capability, CapabilityDescriptor):
            raise EVMAdapterError("capability must be a CapabilityDescriptor")
        if not capability.side_effect_free:
            raise EVMAdapterError("EVM adapter capability must be side-effect-free")
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
        payload: Mapping[str, Any] | EVMTransactionObservation | EVMCallIntent,
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        """Convert *payload* without elevating authority or inventing facts."""

        if isinstance(payload, EVMTransactionObservation):
            payload_map: Mapping[str, Any] = payload.to_dict()
        elif isinstance(payload, EVMCallIntent):
            payload_map = payload.to_dict()
        elif isinstance(payload, Mapping):
            payload_map = payload
        else:
            raise EVMAdapterError("payload must be a mapping or EVM structured record")

        source_digest = f"sha256:{content_sha256_hex(dict(payload_map))}"
        provenance_dict: dict[str, Any] = {}
        source_authority = AuthorityKind.OBSERVATION

        try:
            kind = self._detect_kind(payload_map)
            default_authority = (
                AuthorityKind.OBSERVATION
                if kind is EVMPayloadKind.TRANSACTION_OBSERVATION
                else AuthorityKind.DECLARATION
            )
            provenance_dict, source_authority = self._resolve_provenance(
                source_provenance, default=default_authority
            )
            if source_authority is AuthorityKind.AUTHORIZATION:
                raise EVMAdapterError(
                    "cannot convert authorization-authority payload through EVM adapter"
                )
            # Result authority never elevates and never rewrites into a
            # different sibling kind; preserve source authority on the receipt.
            result_authority = source_authority

            if kind is EVMPayloadKind.TRANSACTION_OBSERVATION:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_observation(payload_map)
                )
            elif kind is EVMPayloadKind.CALL_INTENT:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_call_intent(payload_map)
                )
            elif kind is EVMPayloadKind.SERIALIZED_CANDIDATE:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_serialized_candidate(payload_map)
                )
            else:
                raise EVMAdapterError(f"unsupported EVM payload kind: {kind!r}")
        except EVMAdapterError as exc:
            return AdapterConversionResult(
                conversion_id=f"evm-error:{self._adapter_id}",
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
                attributes={"error": True, "chain_namespace": EVM_NAMESPACE},
            )

        result_digest = f"sha256:{content_sha256_hex(result_payload)}"
        conversion_id = f"evm:{kind.value}:{result_digest[:18]}"
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
                "chain_namespace": EVM_NAMESPACE,
                "payload_kind": kind.value,
                "preserves_raw_evidence": True,
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
                    raise EVMAdapterError(
                        f"unsupported source authority: {authority['kind']!r}"
                    ) from exc
            else:
                kind = default
            return data, kind
        raise EVMAdapterError("source_provenance must be CryptoIRProvenance or mapping")

    def _detect_kind(self, payload: Mapping[str, Any]) -> EVMPayloadKind:
        kind_raw = payload.get("kind", payload.get("payload_kind", ""))
        if kind_raw:
            text = _text(str(kind_raw), "kind").lower().replace("-", "_")
            aliases = {
                "transaction_observation": EVMPayloadKind.TRANSACTION_OBSERVATION,
                "observation": EVMPayloadKind.TRANSACTION_OBSERVATION,
                "evm_transaction_observation": EVMPayloadKind.TRANSACTION_OBSERVATION,
                "call_intent": EVMPayloadKind.CALL_INTENT,
                "unsigned_call": EVMPayloadKind.CALL_INTENT,
                "evm_call_intent": EVMPayloadKind.CALL_INTENT,
                "serialized_candidate": EVMPayloadKind.SERIALIZED_CANDIDATE,
                "candidate": EVMPayloadKind.SERIALIZED_CANDIDATE,
            }
            if text in aliases:
                return aliases[text]
            raise EVMAdapterError(f"unsupported EVM payload kind: {kind_raw!r}")
        # Infer from fields when kind omitted.
        if "tx_hash" in payload or "transaction_hash" in payload or "hash" in payload:
            if "intent_id" in payload and "data" in payload and "tx_hash" not in payload:
                return EVMPayloadKind.CALL_INTENT
            return EVMPayloadKind.TRANSACTION_OBSERVATION
        if "intent_id" in payload or "calldata" in payload or "input" in payload:
            if "payload_digest" in payload or "encoding" in payload:
                return EVMPayloadKind.SERIALIZED_CANDIDATE
            return EVMPayloadKind.CALL_INTENT
        if "payload_digest" in payload or "candidate_id" in payload:
            return EVMPayloadKind.SERIALIZED_CANDIDATE
        raise EVMAdapterError("unable to detect EVM payload kind")

    def _convert_observation(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        obs = EVMTransactionObservation.from_dict(payload)
        network = resolve_network(
            chain_id=obs.chain_id,
            network=obs.network or None,
            genesis_hash=obs.genesis_hash or None,
        )
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []

        # Addresses
        from_account = None
        if obs.from_address:
            from_account = account_identity(obs.from_address, chain, account_kind="eoa")
        else:
            missing_coverage.append("from_address")
            unsupported.append(
                UnsupportedField(
                    path="from_address",
                    reason="from address absent; not invented",
                )
            )

        to_account = None
        if obs.to_address:
            to_account = account_identity(
                obs.to_address, chain, account_kind="contract_or_eoa"
            )
        else:
            missing_coverage.append("to_address")
            # Contract creation may legitimately omit `to`; preserve absence.
            diagnostics.append("to_address absent (possible contract creation)")

        # Finality / retraction — absent stays unknown
        finality = map_finality(obs.finality) if obs.finality else FinalityStatus.UNKNOWN
        if not obs.finality:
            missing_coverage.append("finality")
            unsupported.append(
                UnsupportedField(
                    path="finality",
                    reason="finality absent; left as unknown (not invented)",
                )
            )
        retraction = (
            map_retraction(obs.retraction)
            if obs.retraction
            else RetractionStatus.UNKNOWN
        )
        if not obs.retraction:
            missing_coverage.append("retraction")

        # Receipt
        receipt_present = obs.receipt is not None
        receipt_dict: dict[str, Any] | None = (
            thaw_json(obs.receipt) if obs.receipt is not None else None
        )
        if not receipt_present:
            missing_coverage.append("receipt")
            unsupported.append(
                UnsupportedField(
                    path="receipt",
                    reason="receipt absent; success/status/gas not invented",
                )
            )

        # Logs: prefer explicit logs, else receipt.logs, else absence
        logs_list: list[dict[str, Any]] | None
        if obs.logs is not None:
            logs_list = [thaw_json(item) for item in obs.logs]
        elif receipt_dict is not None and isinstance(receipt_dict.get("logs"), list):
            logs_list = [
                dict(item)
                for item in receipt_dict["logs"]
                if isinstance(item, Mapping)
            ]
        else:
            logs_list = None
            missing_coverage.append("logs")
            unsupported.append(
                UnsupportedField(
                    path="logs",
                    reason="logs absent; token transfers not inferred from silence",
                )
            )

        # Traces
        traces_list: list[dict[str, Any]] | None
        if obs.traces is not None:
            traces_list = [thaw_json(item) for item in obs.traces]
        else:
            traces_list = None
            missing_coverage.append("traces")
            unsupported.append(
                UnsupportedField(
                    path="traces",
                    reason="traces absent; internal value transfers not invented",
                )
            )

        # Calldata
        calldata = obs.input_data
        calldata_digest = ""
        if calldata is None:
            missing_coverage.append("calldata")
            unsupported.append(
                UnsupportedField(
                    path="input_data",
                    reason="calldata absent; not invented as empty success path",
                )
            )
        else:
            calldata_digest = f"sha256:{hashlib.sha256(bytes.fromhex(calldata[2:])).hexdigest()}"

        # Native value
        native_transfer: dict[str, Any] | None = None
        if obs.value_wei is None:
            missing_coverage.append("value_wei")
            unsupported.append(
                UnsupportedField(
                    path="value_wei",
                    reason="native value absent; not invented as zero",
                )
            )
        else:
            amount = ExactAmount(base_units=obs.value_wei, decimals=network.native_decimals)
            asset = native_asset(chain, network)
            native_transfer = {
                "asset": asset.to_dict(),
                "amount": amount.to_dict(),
                "from_account": None
                if from_account is None
                else from_account.to_dict(),
                "to_account": None if to_account is None else to_account.to_dict(),
                "kind": "native",
            }

        # Token transfers: only from explicit list or decodable Transfer logs
        token_records: list[dict[str, Any]] = []
        if obs.token_transfers is not None:
            for index, item in enumerate(obs.token_transfers):
                token_records.append(
                    self._normalize_token_transfer(item, chain, index=index)
                )
        elif logs_list is not None:
            for index, log in enumerate(logs_list):
                decoded = self._try_decode_erc20_transfer(log, chain, index=index)
                if decoded is not None:
                    token_records.append(decoded)
        else:
            missing_coverage.append("token_transfers")

        coordinate = LedgerCoordinate(
            sequence=obs.block_number,
            hash=obs.block_hash,
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
            finality=finality,
            validity_start=obs.validity_start,
            validity_end=obs.validity_end,
            retraction_status=retraction,
        )

        observed = ObservedTransaction(
            observation_id=obs.observation_id,
            chain=chain,
            tx_digest=keccak_digest_tag(obs.tx_hash),
            coordinate=coordinate,
            finality=finality,
            retraction=retraction,
            validity=ValidityWindow(
                start=obs.validity_start, end=obs.validity_end
            ),
            from_account=from_account,
            to_account=to_account,
            provenance=provenance,
            attributes={
                "tx_hash": obs.tx_hash,
                "calldata": calldata,
                "calldata_digest": calldata_digest,
                "calldata_absent": calldata is None,
                "value_wei": obs.value_wei,
                "value_absent": obs.value_wei is None,
                "receipt_present": receipt_present,
                "logs_present": logs_list is not None,
                "traces_present": traces_list is not None,
                "token_transfer_count": len(token_records),
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
            scope=f"evm-tx:{obs.tx_hash}",
            completeness=completeness_status,
            finality=finality,
            validity=ValidityWindow(start=obs.validity_start, end=obs.validity_end),
            retraction=retraction,
            covered_ranges=(coordinate,) if obs.block_number is not None else (),
            missing_ranges=(),
            provider_ids=(self._adapter_id,),
            attributes={
                "missing_coverage": list(missing_coverage),
                "receipt_present": receipt_present,
                "logs_present": logs_list is not None,
                "traces_present": traces_list is not None,
            },
        )

        result_payload = {
            "record_type": "evm_transaction_observation",
            "authority": AuthorityKind.OBSERVATION.value,
            "chain": chain.to_dict(),
            "observed_transaction": observed.to_dict(),
            "native_transfer": native_transfer,
            "token_transfers": token_records,
            "receipt": receipt_dict,
            "logs": logs_list,
            "traces": traces_list,
            "calldata": calldata,
            "calldata_digest": calldata_digest,
            "completeness": completeness.to_dict(),
            "missing_coverage": list(missing_coverage),
            "raw": thaw_json(obs.raw) if obs.raw else thaw_json(obs.attributes),
            "addresses": {
                "from": None
                if from_account is None
                else {
                    "original": from_account.address_original,
                    "normalized": from_account.address_normalized,
                    "checksummed": from_account.attributes.get("address_checksummed"),
                },
                "to": None
                if to_account is None
                else {
                    "original": to_account.address_original,
                    "normalized": to_account.address_normalized,
                    "checksummed": to_account.attributes.get("address_checksummed"),
                },
            },
        }

        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        if missing_coverage:
            diagnostics.append(
                "missing_coverage=" + ",".join(sorted(set(missing_coverage)))
            )
        diagnostics.append(
            f"chain_id={network.chain_id};network={network.network};"
            f"genesis={network.genesis_hash}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _normalize_token_transfer(
        self,
        item: Mapping[str, Any],
        chain: ChainIdentity,
        *,
        index: int,
    ) -> dict[str, Any]:
        contract = item.get("contract", item.get("address", item.get("token", "")))
        if not contract:
            raise EVMAdapterError(f"token_transfers[{index}].contract is required")
        decimals_raw = item.get("decimals")
        decimals = None if decimals_raw is None else _non_negative_int(
            decimals_raw, f"token_transfers[{index}].decimals"
        )
        asset = token_asset(
            chain,
            str(contract),
            decimals=decimals,
            symbol=str(item.get("symbol", "") or ""),
            standard=str(item.get("standard", "erc20") or "erc20"),
        )
        amount_raw = item.get("amount", item.get("value", item.get("value_base_units")))
        if amount_raw is None:
            raise EVMAdapterError(
                f"token_transfers[{index}].amount is required when transfer is present"
            )
        if type(amount_raw) is int and not isinstance(amount_raw, bool):
            amount_str = str(amount_raw)
        else:
            amount_str = _text(str(amount_raw), f"token_transfers[{index}].amount")
        if not _DECIMAL_INTEGER.fullmatch(amount_str) or amount_str.startswith("-"):
            raise EVMAdapterError(
                f"token_transfers[{index}].amount must be a non-negative integer string"
            )
        amount = ExactAmount(
            base_units=amount_str,
            decimals=asset.decimals,
        )
        source = item.get("from", item.get("source", ""))
        dest = item.get("to", item.get("destination", ""))
        return {
            "asset": asset.to_dict(),
            "amount": amount.to_dict(),
            "from_account": None
            if not source
            else account_identity(str(source), chain).to_dict(),
            "to_account": None
            if not dest
            else account_identity(str(dest), chain).to_dict(),
            "kind": "token",
            "log_index": item.get("log_index", item.get("logIndex", index)),
            "raw": thaw_json(item),
            "decimals_absent": decimals is None,
        }

    def _try_decode_erc20_transfer(
        self,
        log: Mapping[str, Any],
        chain: ChainIdentity,
        *,
        index: int,
    ) -> dict[str, Any] | None:
        topics = log.get("topics")
        if not isinstance(topics, Sequence) or isinstance(topics, (str, bytes)):
            return None
        if len(topics) != 3:
            return None
        try:
            sig = normalize_hash(topics[0], field="log.topics[0]")
        except EVMAdapterError:
            return None
        if sig != TRANSFER_TOPIC:
            return None
        contract = log.get("address", "")
        if not contract:
            return None
        try:
            source = "0x" + normalize_hash(topics[1], field="log.topics[1]")[-40:]
            dest = "0x" + normalize_hash(topics[2], field="log.topics[2]")[-40:]
            data = normalize_hex_data(log.get("data", "0x"), field="log.data")
            if len(data) < 2 + 64:
                return None
            value = str(int(data[2:66], 16))
            # Decimals unknown from the log alone — preserve absence.
            asset = token_asset(chain, str(contract), decimals=None, standard="erc20")
            return {
                "asset": asset.to_dict(),
                "amount": ExactAmount(base_units=value, decimals=0).to_dict(),
                "from_account": account_identity(source, chain).to_dict(),
                "to_account": account_identity(dest, chain).to_dict(),
                "kind": "token",
                "log_index": log.get("logIndex", log.get("log_index", index)),
                "raw": thaw_json(log),
                "decimals_absent": True,
                "decoded_from": "erc20_transfer_topic",
            }
        except EVMAdapterError:
            return None

    def _convert_call_intent(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        intent = EVMCallIntent.from_dict(payload)
        network = resolve_network(
            chain_id=intent.chain_id,
            network=intent.network or None,
            genesis_hash=intent.genesis_hash or None,
        )
        chain = network.to_chain_identity()
        origin = account_identity(intent.from_address, chain, account_kind="eoa")
        target = account_identity(
            intent.to_address, chain, account_kind="contract_or_eoa"
        )
        calldata_digest = (
            f"sha256:{hashlib.sha256(bytes.fromhex(intent.data[2:])).hexdigest()}"
        )
        method = intent.method
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        if not method:
            # Do not invent a method name from the selector alone.
            if intent.data != "0x" and len(intent.data) >= 10:
                method = f"selector:{intent.data[2:10]}"
                diagnostics.append(
                    "method label absent; selector preserved without ABI decode"
                )
            else:
                method = "unknown"
                unsupported.append(
                    UnsupportedField(
                        path="method",
                        reason="method absent and calldata empty; not invented",
                    )
                )

        value_amount = ExactAmount(
            base_units=intent.value_wei, decimals=network.native_decimals
        )
        call = CallIntent(
            target=target,
            method=method,
            calldata_digest=calldata_digest
            if calldata_digest
            else f"sha256:{'00' * 32}",
            value=value_amount,
            attributes={
                "calldata": intent.data,
                "calldata_digest": calldata_digest,
                "gas_limit": intent.gas_limit,
                "max_fee_per_gas": intent.max_fee_per_gas,
                "max_priority_fee_per_gas": intent.max_priority_fee_per_gas,
                "nonce": intent.nonce,
                "method_label_absent": not bool(intent.method),
            },
        )
        transfer = None
        if intent.value_wei != "0":
            transfer = TransferIntent(
                asset=native_asset(chain, network),
                amount=value_amount,
                from_account=origin,
                to_account=target,
                attributes={"kind": "native"},
            )

        unsigned = UnsignedTransactionIntent(
            intent_id=intent.intent_id,
            chain=chain,
            origin=origin,
            signers=(SignerRequirement(account=origin, role="origin"),),
            transfers=() if transfer is None else (transfer,),
            calls=(call,),
            attributes={
                "raw": thaw_json(intent.raw),
                "source_attributes": thaw_json(intent.attributes),
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
                "evm_call_intent": intent.to_dict(),
            },
        )

        result_payload = {
            "record_type": "evm_call_intent",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "unsigned_transaction_intent": unsigned.to_dict(),
            "call_intent": call.to_dict(),
            "calldata": intent.data,
            "calldata_digest": calldata_digest,
            "addresses": {
                "from": {
                    "original": origin.address_original,
                    "normalized": origin.address_normalized,
                    "checksummed": origin.attributes.get("address_checksummed"),
                },
                "to": {
                    "original": target.address_original,
                    "normalized": target.address_normalized,
                    "checksummed": target.attributes.get("address_checksummed"),
                },
            },
            "raw": thaw_json(intent.raw),
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"chain_id={network.chain_id};network={network.network};"
            f"genesis={network.genesis_hash}"
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
        intent_id = _identifier(payload.get("intent_id", ""), "intent_id")
        chain_id = payload.get("chain_id")
        network = resolve_network(
            chain_id=chain_id,
            network=payload.get("network") or None,
            genesis_hash=payload.get("genesis_hash") or None,
        )
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []

        raw_bytes_hex = payload.get("raw_tx", payload.get("serialized", payload.get("rlp")))
        payload_digest = payload.get("payload_digest", "")
        encoding = _text(payload.get("encoding", "rlp"), "encoding")
        byte_length = payload.get("byte_length")

        if raw_bytes_hex is not None:
            data = normalize_hex_data(raw_bytes_hex, field="raw_tx")
            body = bytes.fromhex(data[2:])
            if byte_length is None:
                byte_length = len(body)
            if not payload_digest:
                payload_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
        else:
            data = None
            if not payload_digest:
                raise EVMAdapterError(
                    "serialized candidate requires raw_tx or payload_digest"
                )
            if byte_length is None:
                missing = "byte_length"
                unsupported.append(
                    UnsupportedField(
                        path=missing,
                        reason="byte_length absent without raw bytes; not invented",
                    )
                )
                byte_length = 0
            diagnostics.append("raw_tx absent; digest-only candidate preserved")

        # Normalize digest tag
        digest = _text(str(payload_digest), "payload_digest")
        if digest.startswith("0x") and len(digest) == 66:
            digest = f"sha256:{digest[2:]}"
        elif ":" not in digest and len(digest) == 64:
            digest = f"sha256:{digest}"

        candidate = SerializedTransactionCandidate(
            candidate_id=candidate_id,
            intent_id=intent_id,
            chain=chain,
            payload_digest=digest,
            encoding=encoding,
            byte_length=_non_negative_int(byte_length, "byte_length"),
            attributes={
                "raw_tx": data,
                "raw_tx_absent": data is None,
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
                "source": thaw_json(
                    {
                        k: v
                        for k, v in payload.items()
                        if k
                        not in {
                            "candidate_id",
                            "id",
                            "intent_id",
                            "chain_id",
                            "network",
                            "genesis_hash",
                            "raw_tx",
                            "serialized",
                            "rlp",
                            "payload_digest",
                            "encoding",
                            "byte_length",
                            "kind",
                        }
                    }
                ),
            },
        )
        result_payload = {
            "record_type": "evm_serialized_candidate",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "serialized_transaction_candidate": candidate.to_dict(),
            "raw_tx": data,
            "raw_tx_absent": data is None,
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"chain_id={network.chain_id};network={network.network};"
            f"genesis={network.genesis_hash}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status


def convert_evm_payload(
    payload: Mapping[str, Any] | EVMTransactionObservation | EVMCallIntent,
    *,
    source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    adapter: EVMWalletAdapter | None = None,
) -> AdapterConversionResult:
    """Module-level helper around :class:`EVMWalletAdapter.convert`."""

    return (adapter or EVMWalletAdapter()).convert(
        payload, source_provenance=source_provenance
    )


__all__ = [
    "CRYPTO_IR_EVM_ADAPTER_DOMAIN",
    "EVM_ADAPTER_ID",
    "EVM_CAPABILITY_ID",
    "EVM_NAMESPACE",
    "ETHEREUM_MAINNET_CHAIN_ID",
    "ETHEREUM_MAINNET_GENESIS_HASH",
    "ETHEREUM_MAINNET_NETWORK",
    "WORLD_CHAIN_MAINNET_CHAIN_ID",
    "WORLD_CHAIN_MAINNET_GENESIS_HASH",
    "WORLD_CHAIN_MAINNET_NETWORK",
    "WORLD_CHAIN_SEPOLIA_CHAIN_ID",
    "WORLD_CHAIN_SEPOLIA_GENESIS_HASH",
    "WORLD_CHAIN_SEPOLIA_NETWORK",
    "KNOWN_NETWORKS",
    "EVMAdapterError",
    "EVMCallIntent",
    "EVMNetworkAnchor",
    "EVMPayloadKind",
    "EVMTransactionObservation",
    "EVMWalletAdapter",
    "account_identity",
    "content_sha256_hex",
    "convert_evm_payload",
    "default_evm_capability",
    "eip55_checksum_address",
    "keccak256",
    "keccak_digest_tag",
    "map_finality",
    "map_retraction",
    "native_asset",
    "normalize_address",
    "normalize_hash",
    "normalize_hex_data",
    "parse_quantity",
    "resolve_network",
    "token_asset",
]
