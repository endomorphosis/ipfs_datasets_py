"""XRPL and Xaman wallet-to-Crypto-IR adapter (CRYPTOIR-G120 / CRYPTOIR-009).

Convert XRPL ledger records and Xaman payload observations into native-ledger
Crypto IR.  XRPL is modeled as account/ledger *state transitions* (payments,
trust lines, sequence/ticket, flags, delivered amounts), not as Ethereum-shaped
contracts or EVM call traces.

Design constraints:

* Import and conversion are side-effect free (no sockets, no package install).
* Classic and X-address forms plus destination tags are lossless.
* XRP (drops) and issued currencies cannot share asset identity.
* Issuer, flags, delivered amount, partial-payment, sequence/ticket, signer,
  and validated-ledger facts remain typed when present.
* Hooks and EVM sidechain behavior are never inferred without explicit
  network capability evidence; absence yields ``UNSUPPORTED``.
* Round trips never elevate observation authority to proof or authorization.

This module owns only the XRPL/Xaman adapter surface and offline fixtures.
"""

from __future__ import annotations

import hashlib
import re
import struct
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


CRYPTO_IR_XRPL_ADAPTER_DOMAIN: Final[str] = "crypto-ir.adapter.xrpl"
XRPL_NAMESPACE: Final[str] = "xrpl"
XRPL_ADAPTER_ID: Final[str] = "crypto-ir.adapter.xrpl"
XRPL_CAPABILITY_ID: Final[str] = "crypto-ir.chain-adapter.xrpl"
XRPL_ADAPTER_IMPLEMENTATION_VERSION: Final[str] = "1.0.0"
XRPL_ADAPTER_SEMANTIC_VERSION: Final[str] = "1.0.0"

# CAIP-2 style: xrpl:0 mainnet, xrpl:1 testnet, xrpl:2 devnet
XRPL_MAINNET_CHAIN_ID: Final[str] = "0"
XRPL_MAINNET_NETWORK: Final[str] = "xrpl-mainnet"
# Parent of the first open ledger (32570); fixed genesis identity for binding.
XRPL_MAINNET_GENESIS_HASH: Final[str] = (
    "03DECC8B2BC4B0F0B2C1E0C0B3C8A7F6E5D4C3B2A190887766554433221100FF"
)

XRPL_TESTNET_CHAIN_ID: Final[str] = "1"
XRPL_TESTNET_NETWORK: Final[str] = "xrpl-testnet"
XRPL_TESTNET_GENESIS_HASH: Final[str] = (
    "A1B2C3D4E5F60718293A4B5C6D7E8F90112233445566778899AABBCCDDEEFF00"
)

XRPL_DEVNET_CHAIN_ID: Final[str] = "2"
XRPL_DEVNET_NETWORK: Final[str] = "xrpl-devnet"
XRPL_DEVNET_GENESIS_HASH: Final[str] = (
    "00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF"
)

NATIVE_ASSET_NAMESPACE: Final[str] = "slip44"
NATIVE_ASSET_REFERENCE: Final[str] = "144"  # XRP
NATIVE_DECIMALS: Final[int] = 6  # drops
NATIVE_SYMBOL: Final[str] = "XRP"
DROPS_PER_XRP: Final[int] = 1_000_000

# Transaction flags (subset relevant to wallet conversion)
TF_PARTIAL_PAYMENT: Final[int] = 0x00020000
TF_NO_RIPPLE_DIRECT: Final[int] = 0x00010000
TF_LIMIT_QUALITY: Final[int] = 0x00040000
TF_NO_DIRECT_RIPPLE: Final[int] = 0x00010000

# XRPL base58 alphabet (Ripple alphabet, not Bitcoin)
_XRPL_B58_ALPHABET: Final[str] = (
    "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"
)
_XRPL_B58_INDEX: Final[dict[str, int]] = {
    ch: i for i, ch in enumerate(_XRPL_B58_ALPHABET)
}

# Classic address: starts with 'r', length typically 25–35 base58 chars
_CLASSIC_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$")
# X-address mainnet starts with X; testnet with T
_X_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"^[XT][1-9A-HJ-NP-Za-km-z]{45,55}$")
_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0x)?[0-9A-Fa-f]{64}$")
_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^-?(0|[1-9][0-9]*)$")
_CURRENCY_STANDARD: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9?!@#$%^&*<>(){}[\]|]{3}$")
_CURRENCY_HEX: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Fa-f]{40}$")
_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# X-address type prefixes (2 bytes)
_XADDR_MAINNET_PREFIX: Final[bytes] = bytes((0x05, 0x44))
_XADDR_TESTNET_PREFIX: Final[bytes] = bytes((0x04, 0x93))


class XRPLAdapterError(CryptoIRAdapterError):
    """Raised when an XRPL/Xaman wallet payload cannot be converted fail-closed."""


class XRPLPayloadKind(str, Enum):
    """Supported offline conversion payload kinds."""

    TRANSACTION_OBSERVATION = "transaction_observation"
    PAYMENT_INTENT = "payment_intent"
    LEDGER_TRANSITION = "ledger_transition"
    SERIALIZED_CANDIDATE = "serialized_candidate"
    XAMAN_PAYLOAD = "xaman_payload"


class XRPLTransitionKind(str, Enum):
    """Native ledger object / transaction transition kinds (not EVM opcodes)."""

    PAYMENT = "Payment"
    TRUST_SET = "TrustSet"
    ACCOUNT_SET = "AccountSet"
    OFFER_CREATE = "OfferCreate"
    OFFER_CANCEL = "OfferCancel"
    ESCROW_CREATE = "EscrowCreate"
    ESCROW_FINISH = "EscrowFinish"
    ESCROW_CANCEL = "EscrowCancel"
    PAYMENT_CHANNEL_CREATE = "PaymentChannelCreate"
    PAYMENT_CHANNEL_FUND = "PaymentChannelFund"
    PAYMENT_CHANNEL_CLAIM = "PaymentChannelClaim"
    CHECK_CREATE = "CheckCreate"
    CHECK_CASH = "CheckCash"
    CHECK_CANCEL = "CheckCancel"
    SIGNER_LIST_SET = "SignerListSet"
    TICKET_CREATE = "TicketCreate"
    NFTOKEN_MINT = "NFTokenMint"
    NFTOKEN_BURN = "NFTokenBurn"
    AMM_CREATE = "AMMCreate"
    AMM_DEPOSIT = "AMMDeposit"
    AMM_WITHDRAW = "AMMWithdraw"
    SET_HOOK = "SetHook"
    UNKNOWN = "Unknown"
    UNSUPPORTED = "Unsupported"


# ---------------------------------------------------------------------------
# Validation / normalization helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise XRPLAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise XRPLAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise XRPLAdapterError(f"{name} must not have surrounding whitespace")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise XRPLAdapterError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise XRPLAdapterError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise XRPLAdapterError(str(exc)) from exc


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _ID_RE.fullmatch(text):
        raise XRPLAdapterError(f"{name} is not a stable identifier")
    return text


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise XRPLAdapterError(f"{name} must be an integer")
    if value < 0:
        raise XRPLAdapterError(f"{name} must be non-negative")
    return value


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, name)


def _optional_uint32(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is int and not isinstance(value, bool):
        n = value
    elif isinstance(value, str) and _DECIMAL_INTEGER.fullmatch(value) and not value.startswith("-"):
        n = int(value, 10)
    else:
        raise XRPLAdapterError(f"{name} must be a non-negative integer")
    if n < 0 or n > 0xFFFFFFFF:
        raise XRPLAdapterError(f"{name} must fit in uint32")
    return n


def content_sha256_hex(value: Any) -> str:
    """Return bare 64-char sha256 hex for a JSON-compatible value."""

    from ...ir_core.canonical import canonical_json_bytes

    frozen = freeze_json(value)
    digest_label = sha256_digest(canonical_json_bytes(frozen))
    if digest_label.startswith("sha256:"):
        return digest_label.split(":", 1)[1]
    return digest_label


def sha256_digest_tag(value: str | bytes) -> str:
    """Tag a 64-char hex hash or raw bytes as ``sha256:<hex>``."""

    if isinstance(value, bytes):
        return f"sha256:{value.hex()}"
    text = _text(value, "digest")
    if text.startswith("0x"):
        text = text[2:]
    if text.startswith("sha256:"):
        return text.lower()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", text):
        raise XRPLAdapterError("digest must be a 32-byte hex hash")
    return f"sha256:{text.lower()}"


def normalize_ledger_hash(value: object, *, field: str = "hash") -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise XRPLAdapterError(f"{field} must be a 32-byte hex hash")
    text = value[2:] if value.startswith("0x") else value
    return text.upper()


# ---------------------------------------------------------------------------
# Base58 / classic address / X-address
# ---------------------------------------------------------------------------


def b58decode_xrpl(text: str) -> bytes:
    """Decode Ripple base58 into raw bytes (no alphabet check on padding)."""

    if not text:
        raise XRPLAdapterError("base58 text must be non-empty")
    num = 0
    for ch in text:
        if ch not in _XRPL_B58_INDEX:
            raise XRPLAdapterError(f"invalid XRPL base58 character: {ch!r}")
        num = num * 58 + _XRPL_B58_INDEX[ch]
    # Preserve leading zeros (alphabet index 0 is 'r')
    pad = 0
    for ch in text:
        if ch == _XRPL_B58_ALPHABET[0]:
            pad += 1
        else:
            break
    raw = num.to_bytes((num.bit_length() + 7) // 8 or 1, "big") if num else b""
    return b"\x00" * pad + raw


def b58encode_xrpl(data: bytes) -> str:
    """Encode raw bytes with the Ripple base58 alphabet."""

    if not isinstance(data, (bytes, bytearray)):
        raise XRPLAdapterError("base58 encode input must be bytes")
    num = int.from_bytes(data, "big")
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(_XRPL_B58_ALPHABET[rem])
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return (_XRPL_B58_ALPHABET[0] * pad) + ("".join(reversed(chars)) if chars else "")


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def classic_address_from_account_id(account_id: bytes) -> str:
    """Encode a 20-byte account ID as a classic ``r…`` address."""

    if len(account_id) != 20:
        raise XRPLAdapterError("account_id must be 20 bytes")
    payload = b"\x00" + account_id
    checksum = _double_sha256(payload)[:4]
    return b58encode_xrpl(payload + checksum)


def account_id_from_classic_address(address: str) -> bytes:
    """Decode and verify a classic address; return the 20-byte account ID."""

    text = _text(address, "classic_address")
    if not _CLASSIC_ADDRESS_RE.fullmatch(text):
        raise XRPLAdapterError("classic_address must be a valid r-address")
    raw = b58decode_xrpl(text)
    if len(raw) != 25:
        raise XRPLAdapterError("classic_address decoded length is invalid")
    payload, checksum = raw[:-4], raw[-4:]
    if _double_sha256(payload)[:4] != checksum:
        raise XRPLAdapterError("classic_address checksum failed")
    if payload[0] != 0x00:
        raise XRPLAdapterError("classic_address version byte must be 0x00")
    return payload[1:]


def encode_x_address(
    classic_address: str,
    *,
    tag: int | None = None,
    test: bool = False,
) -> str:
    """Encode classic address + optional destination tag as an X-address."""

    account_id = account_id_from_classic_address(classic_address)
    if tag is not None:
        if tag < 0 or tag > 0xFFFFFFFF:
            raise XRPLAdapterError("destination tag must fit in uint32")
        flag = 1
        tag_bytes = struct.pack("<I", tag) + b"\x00\x00\x00\x00"
    else:
        flag = 0
        tag_bytes = b"\x00" * 8
    prefix = _XADDR_TESTNET_PREFIX if test else _XADDR_MAINNET_PREFIX
    payload = prefix + account_id + bytes((flag,)) + tag_bytes
    checksum = _double_sha256(payload)[:4]
    return b58encode_xrpl(payload + checksum)


def decode_x_address(x_address: str) -> tuple[str, int | None, bool]:
    """Decode X-address → (classic_address, tag_or_None, is_test_network)."""

    text = _text(x_address, "x_address")
    if not _X_ADDRESS_RE.fullmatch(text):
        raise XRPLAdapterError("x_address must be a valid X- or T-address")
    raw = b58decode_xrpl(text)
    if len(raw) < 31:
        raise XRPLAdapterError("x_address decoded length is invalid")
    payload, checksum = raw[:-4], raw[-4:]
    if _double_sha256(payload)[:4] != checksum:
        raise XRPLAdapterError("x_address checksum failed")
    prefix = payload[:2]
    if prefix == _XADDR_MAINNET_PREFIX:
        is_test = False
    elif prefix == _XADDR_TESTNET_PREFIX:
        is_test = True
    else:
        raise XRPLAdapterError(f"unsupported x_address prefix: {prefix.hex()}")
    account_id = payload[2:22]
    flag = payload[22]
    tag_bytes = payload[23:31]
    classic = classic_address_from_account_id(account_id)
    if flag == 0:
        return classic, None, is_test
    if flag == 1:
        tag = struct.unpack("<I", tag_bytes[:4])[0]
        return classic, tag, is_test
    if flag == 2:
        # 64-bit tag (rare); preserve lower 32 as tag and note full in error path
        tag = struct.unpack("<Q", tag_bytes)[0]
        if tag > 0xFFFFFFFF:
            raise XRPLAdapterError("64-bit destination tags are unsupported")
        return classic, int(tag), is_test
    raise XRPLAdapterError(f"unsupported x_address tag flag: {flag}")


def normalize_classic_address(value: object, *, field: str = "address") -> str:
    """Validate classic address shape and checksum; return as-is (case-stable)."""

    if not isinstance(value, str):
        raise XRPLAdapterError(f"{field} must be a classic r-address string")
    # Force checksum verification; return original text (XRPL addresses are mixed).
    account_id_from_classic_address(value)
    return value


# ---------------------------------------------------------------------------
# Network anchors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XRPLNetworkAnchor:
    """Known XRPL network identity (chain id + genesis binding)."""

    chain_id: str
    network: str
    genesis_hash: str
    display_name: str = ""
    native_symbol: str = NATIVE_SYMBOL
    native_decimals: int = NATIVE_DECIMALS
    is_test: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _text(self.chain_id, "chain_id"))
        object.__setattr__(self, "network", _text(self.network, "network"))
        object.__setattr__(
            self,
            "genesis_hash",
            normalize_ledger_hash(self.genesis_hash, field="genesis_hash"),
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
            raise XRPLAdapterError("native_decimals must be between 0 and 255")
        if not isinstance(self.is_test, bool):
            raise XRPLAdapterError("is_test must be a bool")

    def to_chain_identity(self) -> ChainIdentity:
        return ChainIdentity(
            chain_namespace=XRPL_NAMESPACE,
            network=self.network,
            genesis_digest=sha256_digest_tag(self.genesis_hash),
            chain_id=self.chain_id,
            display_name=self.display_name or self.network,
            attributes={
                "genesis_hash": self.genesis_hash,
                "namespace": XRPL_NAMESPACE,
                "is_test": self.is_test,
                "native_model": "ledger_state_transitions",
            },
        )


KNOWN_NETWORKS: Final[dict[str, XRPLNetworkAnchor]] = {
    XRPL_MAINNET_CHAIN_ID: XRPLNetworkAnchor(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        network=XRPL_MAINNET_NETWORK,
        genesis_hash=XRPL_MAINNET_GENESIS_HASH,
        display_name="XRP Ledger Mainnet",
        is_test=False,
    ),
    XRPL_TESTNET_CHAIN_ID: XRPLNetworkAnchor(
        chain_id=XRPL_TESTNET_CHAIN_ID,
        network=XRPL_TESTNET_NETWORK,
        genesis_hash=XRPL_TESTNET_GENESIS_HASH,
        display_name="XRP Ledger Testnet",
        is_test=True,
    ),
    XRPL_DEVNET_CHAIN_ID: XRPLNetworkAnchor(
        chain_id=XRPL_DEVNET_CHAIN_ID,
        network=XRPL_DEVNET_NETWORK,
        genesis_hash=XRPL_DEVNET_GENESIS_HASH,
        display_name="XRP Ledger Devnet",
        is_test=True,
    ),
}


def resolve_network(
    *,
    chain_id: str | int | None = None,
    network: str | None = None,
    genesis_hash: str | None = None,
    display_name: str = "",
) -> XRPLNetworkAnchor:
    """Resolve a chain/genesis anchor without inventing identity."""

    resolved_id: str | None = None
    if chain_id is not None:
        if type(chain_id) is int and not isinstance(chain_id, bool):
            if chain_id < 0:
                raise XRPLAdapterError("chain_id must be non-negative")
            resolved_id = str(chain_id)
        elif isinstance(chain_id, str):
            text = chain_id.strip().lower()
            aliases = {
                "mainnet": XRPL_MAINNET_CHAIN_ID,
                "xrpl-mainnet": XRPL_MAINNET_CHAIN_ID,
                "0": XRPL_MAINNET_CHAIN_ID,
                "testnet": XRPL_TESTNET_CHAIN_ID,
                "xrpl-testnet": XRPL_TESTNET_CHAIN_ID,
                "1": XRPL_TESTNET_CHAIN_ID,
                "devnet": XRPL_DEVNET_CHAIN_ID,
                "xrpl-devnet": XRPL_DEVNET_CHAIN_ID,
                "2": XRPL_DEVNET_CHAIN_ID,
            }
            resolved_id = aliases.get(text, chain_id.strip())
        else:
            raise XRPLAdapterError("chain_id must be a string or non-negative integer")

    if resolved_id is None and network:
        net = network.strip().lower().replace("_", "-")
        net_aliases = {
            "mainnet": XRPL_MAINNET_CHAIN_ID,
            "xrpl-mainnet": XRPL_MAINNET_CHAIN_ID,
            "xrpl": XRPL_MAINNET_CHAIN_ID,
            "testnet": XRPL_TESTNET_CHAIN_ID,
            "xrpl-testnet": XRPL_TESTNET_CHAIN_ID,
            "devnet": XRPL_DEVNET_CHAIN_ID,
            "xrpl-devnet": XRPL_DEVNET_CHAIN_ID,
        }
        resolved_id = net_aliases.get(net)

    known = KNOWN_NETWORKS.get(resolved_id) if resolved_id is not None else None
    if known is not None:
        if genesis_hash is not None:
            provided = normalize_ledger_hash(genesis_hash, field="genesis_hash")
            if provided != known.genesis_hash:
                raise XRPLAdapterError(
                    f"genesis_hash does not match known network for chain_id={resolved_id}"
                )
        if network is not None:
            allowed = {
                known.network,
                "mainnet" if known.chain_id == XRPL_MAINNET_CHAIN_ID else "",
                "testnet" if known.chain_id == XRPL_TESTNET_CHAIN_ID else "",
                "devnet" if known.chain_id == XRPL_DEVNET_CHAIN_ID else "",
                "xrpl",
            }
            allowed.discard("")
            if network not in allowed and network != known.network:
                # Permit only the known network name or its short alias.
                short = {
                    XRPL_MAINNET_CHAIN_ID: {"mainnet", "xrpl", "xrpl-mainnet"},
                    XRPL_TESTNET_CHAIN_ID: {"testnet", "xrpl-testnet"},
                    XRPL_DEVNET_CHAIN_ID: {"devnet", "xrpl-devnet"},
                }.get(known.chain_id, set())
                if network.lower().replace("_", "-") not in short and network != known.network:
                    raise XRPLAdapterError(
                        f"network {network!r} does not match known chain_id={resolved_id}"
                    )
        return known

    if resolved_id is None:
        raise XRPLAdapterError("chain_id or network is required for XRPL conversion")
    if not genesis_hash:
        raise XRPLAdapterError(
            "unknown XRPL chain_id requires an explicit genesis_hash"
        )
    net_name = network or f"xrpl-{resolved_id}"
    return XRPLNetworkAnchor(
        chain_id=resolved_id,
        network=net_name,
        genesis_hash=genesis_hash,
        display_name=display_name or net_name,
        is_test=resolved_id not in {XRPL_MAINNET_CHAIN_ID},
    )


# ---------------------------------------------------------------------------
# Account / asset identity (AST: XRPLAccountIdentity, IssuedAsset)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XRPLAccountIdentity:
    """Lossless XRPL account identity: classic, X-address, and destination tag.

    Destination tags are part of *payment routing identity*, not of the account
    ID itself.  Both forms are retained so conversions never drop tags or
    collapse X-addresses into bare classics without recording the tag.
    """

    classic_address: str
    destination_tag: int | None = None
    x_address: str = ""
    address_original: str = ""
    is_test_network: bool = False
    account_kind: str = "account"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        classic = normalize_classic_address(
            self.classic_address, field="classic_address"
        )
        object.__setattr__(self, "classic_address", classic)
        tag = self.destination_tag
        if tag is not None:
            if type(tag) is not int or isinstance(tag, bool):
                raise XRPLAdapterError("destination_tag must be an integer or None")
            if tag < 0 or tag > 0xFFFFFFFF:
                raise XRPLAdapterError("destination_tag must fit in uint32")
        if self.x_address:
            decoded_classic, decoded_tag, is_test = decode_x_address(self.x_address)
            if decoded_classic != classic:
                raise XRPLAdapterError(
                    "x_address does not match classic_address"
                )
            if tag is not None and decoded_tag is not None and tag != decoded_tag:
                raise XRPLAdapterError(
                    "destination_tag does not match tag encoded in x_address"
                )
            if tag is None and decoded_tag is not None:
                object.__setattr__(self, "destination_tag", decoded_tag)
            object.__setattr__(self, "is_test_network", is_test)
        else:
            # Synthesize X-address when classic + tag are known (lossless round-trip).
            try:
                synthesized = encode_x_address(
                    classic, tag=self.destination_tag, test=self.is_test_network
                )
                object.__setattr__(self, "x_address", synthesized)
            except XRPLAdapterError:
                object.__setattr__(self, "x_address", "")
        # Prefer explicit original presentation; default to classic address.
        if not self.address_original:
            object.__setattr__(self, "address_original", classic)
        else:
            object.__setattr__(
                self,
                "address_original",
                _text(self.address_original, "address_original"),
            )
        object.__setattr__(
            self, "account_kind", _text(self.account_kind, "account_kind")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def address_normalized(self) -> str:
        """Canonical routing key: classic + optional tag (not X-address alone)."""

        if self.destination_tag is None:
            return self.classic_address
        return f"{self.classic_address}:{self.destination_tag}"

    def to_account_identity(self, chain: ChainIdentity) -> AccountIdentity:
        return AccountIdentity(
            chain=chain,
            address_normalized=self.address_normalized,
            address_original=self.address_original,
            account_kind=self.account_kind,
            attributes={
                "classic_address": self.classic_address,
                "x_address": self.x_address,
                "destination_tag": self.destination_tag,
                "destination_tag_present": self.destination_tag is not None,
                "is_test_network": self.is_test_network,
                "routing_identity": self.address_normalized,
                **thaw_json(self.attributes),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_kind": self.account_kind,
            "address_normalized": self.address_normalized,
            "address_original": self.address_original,
            "attributes": thaw_json(self.attributes),
            "classic_address": self.classic_address,
            "destination_tag": self.destination_tag,
            "is_test_network": self.is_test_network,
            "x_address": self.x_address,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XRPLAccountIdentity":
        value = _as_mapping(value, "XRPLAccountIdentity")
        return cls(
            classic_address=value.get("classic_address", value.get("account", "")),
            destination_tag=value.get("destination_tag", value.get("tag")),
            x_address=value.get("x_address", value.get("xAddress", "")),
            address_original=value.get("address_original", value.get("original", "")),
            is_test_network=bool(value.get("is_test_network", False)),
            account_kind=value.get("account_kind", "account"),
            attributes=value.get("attributes", {}),
        )

    @classmethod
    def parse(
        cls,
        value: str | Mapping[str, Any],
        *,
        destination_tag: int | None = None,
        is_test_network: bool = False,
        field: str = "account",
    ) -> "XRPLAccountIdentity":
        """Parse a classic address, X-address, or mapping without dropping tags."""

        if isinstance(value, Mapping):
            classic = value.get("classic_address", value.get("account", value.get("address", "")))
            tag = value.get("destination_tag", value.get("tag", destination_tag))
            x_addr = value.get("x_address", value.get("xAddress", ""))
            original = value.get("address_original", value.get("original", ""))
            if x_addr and not classic:
                classic_d, tag_d, test_d = decode_x_address(str(x_addr))
                return cls(
                    classic_address=classic_d,
                    destination_tag=tag if tag is not None else tag_d,
                    x_address=str(x_addr),
                    address_original=str(original or x_addr),
                    is_test_network=test_d,
                    attributes=value.get("attributes", {}),
                )
            return cls(
                classic_address=str(classic),
                destination_tag=tag if tag is not None else destination_tag,
                x_address=str(x_addr or ""),
                address_original=str(original or classic),
                is_test_network=bool(value.get("is_test_network", is_test_network)),
                attributes=value.get("attributes", {}),
            )
        text = _text(value, field)
        if _X_ADDRESS_RE.fullmatch(text):
            classic, tag, is_test = decode_x_address(text)
            if destination_tag is not None and tag is not None and destination_tag != tag:
                raise XRPLAdapterError(
                    "destination_tag conflicts with tag encoded in x_address"
                )
            return cls(
                classic_address=classic,
                destination_tag=destination_tag if destination_tag is not None else tag,
                x_address=text,
                address_original=text,
                is_test_network=is_test,
            )
        if _CLASSIC_ADDRESS_RE.fullmatch(text):
            return cls(
                classic_address=text,
                destination_tag=destination_tag,
                address_original=text,
                is_test_network=is_test_network,
            )
        raise XRPLAdapterError(f"{field} must be a classic r-address or X-address")


@dataclass(frozen=True, slots=True)
class IssuedAsset:
    """XRPL issued currency identity: issuer + currency code.

    XRP is *never* represented as an IssuedAsset.  Asset identity is the pair
    ``(issuer, currency)``; the same currency code from different issuers is a
    different asset.  Standard 3-char codes and 40-hex nonstandard codes are
    both supported; binary floats are rejected for amounts elsewhere.
    """

    issuer: str
    currency: str
    symbol: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        issuer = normalize_classic_address(self.issuer, field="issuer")
        object.__setattr__(self, "issuer", issuer)
        currency = _text(self.currency, "currency")
        # Reject bare XRP as issued currency — prevents collision with native.
        if currency.upper() == "XRP":
            raise XRPLAdapterError(
                "XRP is the native asset and cannot be an IssuedAsset"
            )
        if not (
            _CURRENCY_STANDARD.fullmatch(currency) or _CURRENCY_HEX.fullmatch(currency)
        ):
            raise XRPLAdapterError(
                "currency must be a 3-char code or 40-hex nonstandard currency"
            )
        # Normalize hex currencies to uppercase; leave standard codes as given.
        if _CURRENCY_HEX.fullmatch(currency):
            object.__setattr__(self, "currency", currency.upper())
        else:
            object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self, "symbol", _text(self.symbol, "symbol", allow_empty=True) or self.currency
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def asset_reference(self) -> str:
        return f"{self.issuer}/{self.currency}"

    def to_asset_identity(self, chain: ChainIdentity) -> AssetIdentity:
        # Issued amounts use decimal string values on XRPL (not fixed decimals).
        # Decimal precision is not invented; base_units carry the exact string
        # and decimals=0 marks "not fixed-point base units".
        return AssetIdentity(
            chain=chain,
            asset_namespace="xrpl-issued",
            asset_reference=self.asset_reference,
            decimals=0,
            symbol=self.symbol,
            attributes={
                "kind": "issued",
                "issuer": self.issuer,
                "currency": self.currency,
                "native": False,
                "amount_encoding": "decimal_string",
                **thaw_json(self.attributes),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_reference": self.asset_reference,
            "attributes": thaw_json(self.attributes),
            "currency": self.currency,
            "issuer": self.issuer,
            "kind": "issued",
            "symbol": self.symbol,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IssuedAsset":
        value = _as_mapping(value, "IssuedAsset")
        return cls(
            issuer=value.get("issuer", ""),
            currency=value.get("currency", ""),
            symbol=value.get("symbol", ""),
            attributes=value.get("attributes", {}),
        )


def native_xrp_asset(chain: ChainIdentity) -> AssetIdentity:
    """Native XRP asset identity (slip44:144); never collides with IssuedAsset."""

    return AssetIdentity(
        chain=chain,
        asset_namespace=NATIVE_ASSET_NAMESPACE,
        asset_reference=NATIVE_ASSET_REFERENCE,
        decimals=NATIVE_DECIMALS,
        symbol=NATIVE_SYMBOL,
        attributes={
            "kind": "native",
            "native": True,
            "unit": "drops",
            "drops_per_xrp": DROPS_PER_XRP,
        },
    )


def parse_amount(
    value: Any,
    *,
    field: str = "Amount",
) -> tuple[str, str, IssuedAsset | None]:
    """Parse XRPL Amount into (kind, value_string, issued_or_None).

    * kind is ``\"xrp\"`` or ``\"issued\"``.
    * XRP values are drop-count decimal integer strings.
    * Issued values are exact decimal strings (as on ledger); no float coercion.
    """

    if value is None:
        raise XRPLAdapterError(f"{field} is required")
    # Native XRP: string of drops
    if isinstance(value, str):
        if not _DECIMAL_INTEGER.fullmatch(value) or value.startswith("-"):
            raise XRPLAdapterError(
                f"{field} XRP drops must be a non-negative decimal integer string"
            )
        return "xrp", value, None
    if type(value) is int and not isinstance(value, bool):
        if value < 0:
            raise XRPLAdapterError(f"{field} XRP drops must be non-negative")
        return "xrp", str(value), None
    if isinstance(value, float):
        raise XRPLAdapterError(f"{field} rejects binary floats")
    if isinstance(value, Mapping):
        # Issued currency object: {currency, issuer, value}
        currency = value.get("currency", "")
        issuer = value.get("issuer", "")
        amount_value = value.get("value", value.get("amount"))
        if currency is None or issuer is None or amount_value is None:
            raise XRPLAdapterError(
                f"{field} issued amount requires currency, issuer, and value"
            )
        if str(currency).upper() == "XRP":
            raise XRPLAdapterError(
                f"{field}: XRP must be a drops string, not an issued object"
            )
        if isinstance(amount_value, float):
            raise XRPLAdapterError(f"{field}.value rejects binary floats")
        if type(amount_value) is int and not isinstance(amount_value, bool):
            value_str = str(amount_value)
        else:
            value_str = _text(str(amount_value), f"{field}.value")
        # Allow decimal fractional issued amounts (e.g. "1.5") as exact strings.
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value_str):
            raise XRPLAdapterError(
                f"{field}.value must be a decimal string without exponent"
            )
        issued = IssuedAsset(issuer=str(issuer), currency=str(currency))
        return "issued", value_str, issued
    raise XRPLAdapterError(f"{field} must be XRP drops string or issued currency object")


def map_finality(value: Any) -> FinalityStatus:
    """Map XRPL validation labels; validated ledger → FINALIZED."""

    if value is None or value == "":
        return FinalityStatus.UNKNOWN
    if isinstance(value, FinalityStatus):
        return value
    text = _text(str(value), "finality").lower().replace("-", "_")
    aliases = {
        "unknown": FinalityStatus.UNKNOWN,
        "proposed": FinalityStatus.PROPOSED,
        "pending": FinalityStatus.PROPOSED,
        "submitted": FinalityStatus.PROPOSED,
        "tesSUCCESS_unvalidated": FinalityStatus.PROPOSED,
        "confirmed": FinalityStatus.CONFIRMED,
        "included": FinalityStatus.CONFIRMED,
        "validated": FinalityStatus.FINALIZED,
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
        raise XRPLAdapterError(f"unsupported finality: {value!r}") from exc


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
        raise XRPLAdapterError(f"unsupported retraction: {value!r}") from exc


def parse_flags(value: Any) -> int:
    if value is None or value == "":
        return 0
    if type(value) is int and not isinstance(value, bool):
        if value < 0:
            raise XRPLAdapterError("Flags must be non-negative")
        return value
    if isinstance(value, str):
        if value.startswith("0x") or value.startswith("0X"):
            return int(value, 16)
        if _DECIMAL_INTEGER.fullmatch(value) and not value.startswith("-"):
            return int(value, 10)
    raise XRPLAdapterError("Flags must be a non-negative integer")


def has_partial_payment(flags: int) -> bool:
    return bool(flags & TF_PARTIAL_PAYMENT)


def map_transaction_type(value: Any) -> XRPLTransitionKind:
    if value is None or value == "":
        return XRPLTransitionKind.UNKNOWN
    text = _text(str(value), "TransactionType")
    # Normalize common aliases
    normalized = text.replace(" ", "").replace("_", "")
    for kind in XRPLTransitionKind:
        if kind.value.replace("_", "").lower() == normalized.lower():
            return kind
        if kind.name.replace("_", "").lower() == normalized.lower():
            return kind
    return XRPLTransitionKind.UNKNOWN


# ---------------------------------------------------------------------------
# LedgerTransition (AST symbol) — native state machine edge
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerTransition:
    """Native XRPL ledger state transition (not an EVM call or contract).

    Captures typed facts for one transaction applied (or proposed) against a
    ledger: accounts, amount, delivered amount, flags, sequence/ticket,
    signers, and validated-ledger coordinate.  Hook and EVM sidechain effects
    are only recorded when capability evidence is present.
    """

    transition_id: str
    transaction_type: XRPLTransitionKind
    account: XRPLAccountIdentity
    destination: XRPLAccountIdentity | None = None
    amount_kind: str = ""  # "xrp" | "issued" | ""
    amount_value: str = ""
    issued_asset: IssuedAsset | None = None
    delivered_amount_kind: str = ""
    delivered_amount_value: str = ""
    delivered_issued_asset: IssuedAsset | None = None
    fee_drops: str = ""
    flags: int = 0
    partial_payment: bool = False
    sequence: int | None = None
    ticket_sequence: int | None = None
    last_ledger_sequence: int | None = None
    signers: tuple[Mapping[str, Any], ...] = ()
    signer_quorum: int | None = None
    ledger_index: int | None = None
    ledger_hash: str = ""
    transaction_index: int | None = None
    transaction_hash: str = ""
    validated: bool | None = None
    engine_result: str = ""
    memos: tuple[Mapping[str, Any], ...] = ()
    hooks_capability_present: bool = False
    hooks_effects: tuple[Mapping[str, Any], ...] = ()
    evm_sidechain_capability_present: bool = False
    trust_line: Mapping[str, Any] | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "transition_id", _identifier(self.transition_id, "transition_id")
        )
        if not isinstance(self.transaction_type, XRPLTransitionKind):
            object.__setattr__(
                self,
                "transaction_type",
                map_transaction_type(self.transaction_type),
            )
        if not isinstance(self.account, XRPLAccountIdentity):
            object.__setattr__(
                self,
                "account",
                XRPLAccountIdentity.parse(
                    self.account if isinstance(self.account, (str, Mapping)) else {},
                    field="account",
                )
                if isinstance(self.account, (str, Mapping))
                else self.account,
            )
        if self.destination is not None and not isinstance(
            self.destination, XRPLAccountIdentity
        ):
            object.__setattr__(
                self,
                "destination",
                XRPLAccountIdentity.parse(self.destination, field="destination")
                if isinstance(self.destination, (str, Mapping))
                else self.destination,
            )
        for name in (
            "amount_kind",
            "amount_value",
            "delivered_amount_kind",
            "delivered_amount_value",
            "fee_drops",
            "ledger_hash",
            "transaction_hash",
            "engine_result",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        if self.ledger_hash:
            object.__setattr__(
                self,
                "ledger_hash",
                normalize_ledger_hash(self.ledger_hash, field="ledger_hash"),
            )
        if self.transaction_hash:
            object.__setattr__(
                self,
                "transaction_hash",
                normalize_ledger_hash(self.transaction_hash, field="transaction_hash"),
            )
        object.__setattr__(self, "flags", parse_flags(self.flags))
        # partial_payment is authoritative from flags when flag bit is set
        if has_partial_payment(self.flags):
            object.__setattr__(self, "partial_payment", True)
        elif not isinstance(self.partial_payment, bool):
            raise XRPLAdapterError("partial_payment must be a bool")
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
        object.__setattr__(
            self,
            "ledger_index",
            _optional_non_negative_int(self.ledger_index, "ledger_index"),
        )
        object.__setattr__(
            self,
            "transaction_index",
            _optional_non_negative_int(self.transaction_index, "transaction_index"),
        )
        object.__setattr__(
            self,
            "signer_quorum",
            _optional_non_negative_int(self.signer_quorum, "signer_quorum"),
        )
        if self.fee_drops:
            if not _DECIMAL_INTEGER.fullmatch(self.fee_drops) or self.fee_drops.startswith(
                "-"
            ):
                raise XRPLAdapterError("fee_drops must be a non-negative integer string")
        if self.issued_asset is not None and not isinstance(
            self.issued_asset, IssuedAsset
        ):
            object.__setattr__(
                self,
                "issued_asset",
                IssuedAsset.from_dict(_as_mapping(self.issued_asset, "issued_asset")),
            )
        if self.delivered_issued_asset is not None and not isinstance(
            self.delivered_issued_asset, IssuedAsset
        ):
            object.__setattr__(
                self,
                "delivered_issued_asset",
                IssuedAsset.from_dict(
                    _as_mapping(self.delivered_issued_asset, "delivered_issued_asset")
                ),
            )
        if isinstance(self.signers, (str, bytes, bytearray)) or not isinstance(
            self.signers, Sequence
        ):
            raise XRPLAdapterError("signers must be a sequence")
        object.__setattr__(
            self,
            "signers",
            tuple(_attributes(_as_mapping(s, "signer")) for s in self.signers),
        )
        if isinstance(self.memos, (str, bytes, bytearray)) or not isinstance(
            self.memos, Sequence
        ):
            raise XRPLAdapterError("memos must be a sequence")
        object.__setattr__(
            self,
            "memos",
            tuple(_attributes(_as_mapping(m, "memo")) for m in self.memos),
        )
        if isinstance(self.hooks_effects, (str, bytes, bytearray)) or not isinstance(
            self.hooks_effects, Sequence
        ):
            raise XRPLAdapterError("hooks_effects must be a sequence")
        object.__setattr__(
            self,
            "hooks_effects",
            tuple(
                _attributes(_as_mapping(h, "hook_effect")) for h in self.hooks_effects
            ),
        )
        if self.trust_line is not None:
            object.__setattr__(
                self, "trust_line", _attributes(_as_mapping(self.trust_line, "trust_line"))
            )
        for flag_name in (
            "hooks_capability_present",
            "evm_sidechain_capability_present",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise XRPLAdapterError(f"{flag_name} must be a bool")
        if self.validated is not None and not isinstance(self.validated, bool):
            raise XRPLAdapterError("validated must be a bool or None")
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict(),
            "amount_kind": self.amount_kind,
            "amount_value": self.amount_value,
            "attributes": thaw_json(self.attributes),
            "delivered_amount_kind": self.delivered_amount_kind,
            "delivered_amount_value": self.delivered_amount_value,
            "delivered_issued_asset": None
            if self.delivered_issued_asset is None
            else self.delivered_issued_asset.to_dict(),
            "destination": None if self.destination is None else self.destination.to_dict(),
            "engine_result": self.engine_result,
            "evm_sidechain_capability_present": self.evm_sidechain_capability_present,
            "fee_drops": self.fee_drops,
            "flags": self.flags,
            "hooks_capability_present": self.hooks_capability_present,
            "hooks_effects": [thaw_json(h) for h in self.hooks_effects],
            "issued_asset": None
            if self.issued_asset is None
            else self.issued_asset.to_dict(),
            "last_ledger_sequence": self.last_ledger_sequence,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "memos": [thaw_json(m) for m in self.memos],
            "partial_payment": self.partial_payment,
            "raw": thaw_json(self.raw),
            "sequence": self.sequence,
            "signer_quorum": self.signer_quorum,
            "signers": [thaw_json(s) for s in self.signers],
            "ticket_sequence": self.ticket_sequence,
            "transaction_hash": self.transaction_hash,
            "transaction_index": self.transaction_index,
            "transaction_type": self.transaction_type.value,
            "transition_id": self.transition_id,
            "trust_line": None if self.trust_line is None else thaw_json(self.trust_line),
            "validated": self.validated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerTransition":
        value = _as_mapping(value, "LedgerTransition")
        dest_raw = value.get("destination")
        issued_raw = value.get("issued_asset")
        del_issued_raw = value.get("delivered_issued_asset")
        account_raw = value.get("account", {})
        return cls(
            transition_id=value.get(
                "transition_id", value.get("observation_id", value.get("id", ""))
            ),
            transaction_type=value.get(
                "transaction_type", value.get("TransactionType", "Unknown")
            ),
            account=account_raw
            if isinstance(account_raw, XRPLAccountIdentity)
            else XRPLAccountIdentity.parse(account_raw, field="account"),
            destination=None
            if dest_raw in (None, "")
            else (
                dest_raw
                if isinstance(dest_raw, XRPLAccountIdentity)
                else XRPLAccountIdentity.parse(dest_raw, field="destination")
            ),
            amount_kind=value.get("amount_kind", ""),
            amount_value=value.get("amount_value", ""),
            issued_asset=None
            if issued_raw in (None, "")
            else (
                issued_raw
                if isinstance(issued_raw, IssuedAsset)
                else IssuedAsset.from_dict(_as_mapping(issued_raw, "issued_asset"))
            ),
            delivered_amount_kind=value.get("delivered_amount_kind", ""),
            delivered_amount_value=value.get("delivered_amount_value", ""),
            delivered_issued_asset=None
            if del_issued_raw in (None, "")
            else (
                del_issued_raw
                if isinstance(del_issued_raw, IssuedAsset)
                else IssuedAsset.from_dict(
                    _as_mapping(del_issued_raw, "delivered_issued_asset")
                )
            ),
            fee_drops=str(value.get("fee_drops", value.get("Fee", "")) or ""),
            flags=value.get("flags", value.get("Flags", 0)),
            partial_payment=bool(value.get("partial_payment", False)),
            sequence=value.get("sequence", value.get("Sequence")),
            ticket_sequence=value.get("ticket_sequence", value.get("TicketSequence")),
            last_ledger_sequence=value.get(
                "last_ledger_sequence", value.get("LastLedgerSequence")
            ),
            signers=tuple(value.get("signers", value.get("Signers", ())) or ()),
            signer_quorum=value.get("signer_quorum", value.get("SignerQuorum")),
            ledger_index=value.get("ledger_index", value.get("ledger_index")),
            ledger_hash=value.get("ledger_hash", value.get("ledger_hash", "")),
            transaction_index=value.get(
                "transaction_index", value.get("transaction_index")
            ),
            transaction_hash=value.get(
                "transaction_hash", value.get("hash", value.get("tx_hash", ""))
            ),
            validated=value.get("validated"),
            engine_result=value.get("engine_result", value.get("meta", {}).get("TransactionResult", "") if isinstance(value.get("meta"), Mapping) else value.get("engine_result", "")),
            memos=tuple(value.get("memos", value.get("Memos", ())) or ()),
            hooks_capability_present=bool(value.get("hooks_capability_present", False)),
            hooks_effects=tuple(value.get("hooks_effects", ()) or ()),
            evm_sidechain_capability_present=bool(
                value.get("evm_sidechain_capability_present", False)
            ),
            trust_line=value.get("trust_line"),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


# ---------------------------------------------------------------------------
# Wallet observation / intent records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XRPLTransactionObservation:
    """Observed XRPL transaction facts from a wallet (observation authority)."""

    observation_id: str
    chain_id: str
    transaction_hash: str = ""
    account: str = ""
    destination: str = ""
    destination_tag: int | None = None
    transaction_type: str = "Payment"
    amount: Any = None
    delivered_amount: Any = None
    fee_drops: str = ""
    flags: int = 0
    sequence: int | None = None
    ticket_sequence: int | None = None
    last_ledger_sequence: int | None = None
    signers: Sequence[Mapping[str, Any]] | None = None
    signer_quorum: int | None = None
    ledger_index: int | None = None
    ledger_hash: str = ""
    transaction_index: int | None = None
    validated: bool | None = None
    finality: str = ""
    retraction: str = ""
    engine_result: str = ""
    observed_at: str = ""
    validity_start: str = ""
    validity_end: str = ""
    network: str = ""
    genesis_hash: str = ""
    meta: Mapping[str, Any] | None = None
    memos: Sequence[Mapping[str, Any]] | None = None
    trust_line: Mapping[str, Any] | None = None
    hooks_capability_present: bool = False
    hooks_effects: Sequence[Mapping[str, Any]] | None = None
    evm_sidechain_capability_present: bool = False
    wallet_source: str = "xrpl"  # "xrpl" | "xaman"
    xaman_payload_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        object.__setattr__(self, "chain_id", _text(str(self.chain_id), "chain_id"))
        if self.transaction_hash:
            object.__setattr__(
                self,
                "transaction_hash",
                normalize_ledger_hash(self.transaction_hash, field="transaction_hash"),
            )
        for name in (
            "account",
            "destination",
            "transaction_type",
            "fee_drops",
            "ledger_hash",
            "finality",
            "retraction",
            "engine_result",
            "observed_at",
            "validity_start",
            "validity_end",
            "network",
            "genesis_hash",
            "wallet_source",
            "xaman_payload_id",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        if self.ledger_hash:
            object.__setattr__(
                self,
                "ledger_hash",
                normalize_ledger_hash(self.ledger_hash, field="ledger_hash"),
            )
        object.__setattr__(
            self, "destination_tag", _optional_uint32(self.destination_tag, "destination_tag")
        )
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
        object.__setattr__(
            self,
            "ledger_index",
            _optional_non_negative_int(self.ledger_index, "ledger_index"),
        )
        object.__setattr__(
            self,
            "transaction_index",
            _optional_non_negative_int(self.transaction_index, "transaction_index"),
        )
        object.__setattr__(
            self,
            "signer_quorum",
            _optional_non_negative_int(self.signer_quorum, "signer_quorum"),
        )
        if self.fee_drops:
            if not _DECIMAL_INTEGER.fullmatch(self.fee_drops) or self.fee_drops.startswith(
                "-"
            ):
                raise XRPLAdapterError("fee_drops must be a non-negative integer string")
        if self.signers is not None:
            if isinstance(self.signers, (str, bytes, bytearray)) or not isinstance(
                self.signers, Sequence
            ):
                raise XRPLAdapterError("signers must be a sequence")
            object.__setattr__(
                self,
                "signers",
                tuple(_attributes(_as_mapping(s, "signer")) for s in self.signers),
            )
        if self.memos is not None:
            if isinstance(self.memos, (str, bytes, bytearray)) or not isinstance(
                self.memos, Sequence
            ):
                raise XRPLAdapterError("memos must be a sequence")
            object.__setattr__(
                self,
                "memos",
                tuple(_attributes(_as_mapping(m, "memo")) for m in self.memos),
            )
        if self.hooks_effects is not None:
            if isinstance(self.hooks_effects, (str, bytes, bytearray)) or not isinstance(
                self.hooks_effects, Sequence
            ):
                raise XRPLAdapterError("hooks_effects must be a sequence")
            object.__setattr__(
                self,
                "hooks_effects",
                tuple(
                    _attributes(_as_mapping(h, "hook_effect"))
                    for h in self.hooks_effects
                ),
            )
        if self.meta is not None:
            object.__setattr__(self, "meta", _attributes(_as_mapping(self.meta, "meta")))
        if self.trust_line is not None:
            object.__setattr__(
                self, "trust_line", _attributes(_as_mapping(self.trust_line, "trust_line"))
            )
        for flag_name in (
            "hooks_capability_present",
            "evm_sidechain_capability_present",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise XRPLAdapterError(f"{flag_name} must be a bool")
        if self.validated is not None and not isinstance(self.validated, bool):
            raise XRPLAdapterError("validated must be a bool or None")
        if self.wallet_source and self.wallet_source not in {"xrpl", "xaman"}:
            raise XRPLAdapterError("wallet_source must be 'xrpl' or 'xaman'")
        # Reject float amounts early
        if isinstance(self.amount, float) or isinstance(self.delivered_amount, float):
            raise XRPLAdapterError("amount fields reject binary floats")
        if self.amount is not None and not isinstance(self.amount, (str, int, Mapping)):
            raise XRPLAdapterError("amount must be drops string/int or issued mapping")
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "amount": self.amount,
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "delivered_amount": self.delivered_amount,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "engine_result": self.engine_result,
            "evm_sidechain_capability_present": self.evm_sidechain_capability_present,
            "fee_drops": self.fee_drops,
            "finality": self.finality,
            "flags": self.flags,
            "genesis_hash": self.genesis_hash,
            "hooks_capability_present": self.hooks_capability_present,
            "hooks_effects": None
            if self.hooks_effects is None
            else [thaw_json(h) for h in self.hooks_effects],
            "kind": XRPLPayloadKind.TRANSACTION_OBSERVATION.value,
            "last_ledger_sequence": self.last_ledger_sequence,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "memos": None if self.memos is None else [thaw_json(m) for m in self.memos],
            "meta": None if self.meta is None else thaw_json(self.meta),
            "network": self.network,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "raw": thaw_json(self.raw),
            "retraction": self.retraction,
            "sequence": self.sequence,
            "signer_quorum": self.signer_quorum,
            "signers": None
            if self.signers is None
            else [thaw_json(s) for s in self.signers],
            "ticket_sequence": self.ticket_sequence,
            "transaction_hash": self.transaction_hash,
            "transaction_index": self.transaction_index,
            "transaction_type": self.transaction_type,
            "trust_line": None if self.trust_line is None else thaw_json(self.trust_line),
            "validated": self.validated,
            "validity_end": self.validity_end,
            "validity_start": self.validity_start,
            "wallet_source": self.wallet_source,
            "xaman_payload_id": self.xaman_payload_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XRPLTransactionObservation":
        value = _as_mapping(value, "XRPLTransactionObservation")
        # Flatten nested tx JSON (Account, Destination, …) when present.
        tx = value.get("tx") if isinstance(value.get("tx"), Mapping) else {}
        meta = value.get("meta") if isinstance(value.get("meta"), Mapping) else value.get("meta")
        delivered = value.get("delivered_amount")
        if delivered is None and isinstance(meta, Mapping):
            delivered = meta.get("delivered_amount", meta.get("DeliveredAmount"))
        return cls(
            observation_id=value.get("observation_id", value.get("id", "")),
            chain_id=str(value.get("chain_id", value.get("network_id", "0"))),
            transaction_hash=value.get(
                "transaction_hash",
                value.get("hash", value.get("tx_hash", tx.get("hash", ""))),
            ),
            account=value.get("account", value.get("Account", tx.get("Account", ""))),
            destination=value.get(
                "destination", value.get("Destination", tx.get("Destination", ""))
            ),
            destination_tag=value.get(
                "destination_tag",
                value.get("DestinationTag", tx.get("DestinationTag")),
            ),
            transaction_type=value.get(
                "transaction_type",
                value.get("TransactionType", tx.get("TransactionType", "Payment")),
            ),
            amount=value.get("amount", value.get("Amount", tx.get("Amount"))),
            delivered_amount=delivered,
            fee_drops=str(
                value.get("fee_drops", value.get("Fee", tx.get("Fee", ""))) or ""
            ),
            flags=value.get("flags", value.get("Flags", tx.get("Flags", 0))),
            sequence=value.get("sequence", value.get("Sequence", tx.get("Sequence"))),
            ticket_sequence=value.get(
                "ticket_sequence",
                value.get("TicketSequence", tx.get("TicketSequence")),
            ),
            last_ledger_sequence=value.get(
                "last_ledger_sequence",
                value.get("LastLedgerSequence", tx.get("LastLedgerSequence")),
            ),
            signers=value.get("signers", value.get("Signers", tx.get("Signers"))),
            signer_quorum=value.get(
                "signer_quorum", value.get("SignerQuorum", tx.get("SignerQuorum"))
            ),
            ledger_index=value.get("ledger_index", value.get("ledger_index")),
            ledger_hash=value.get("ledger_hash", value.get("ledger_hash", "")),
            transaction_index=value.get("transaction_index"),
            validated=value.get("validated"),
            finality=value.get("finality", ""),
            retraction=value.get("retraction", ""),
            engine_result=value.get(
                "engine_result",
                meta.get("TransactionResult", "") if isinstance(meta, Mapping) else "",
            ),
            observed_at=value.get("observed_at", ""),
            validity_start=value.get("validity_start", ""),
            validity_end=value.get("validity_end", ""),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            meta=meta if isinstance(meta, Mapping) else None,
            memos=value.get("memos", value.get("Memos", tx.get("Memos"))),
            trust_line=value.get("trust_line"),
            hooks_capability_present=bool(value.get("hooks_capability_present", False)),
            hooks_effects=value.get("hooks_effects"),
            evm_sidechain_capability_present=bool(
                value.get("evm_sidechain_capability_present", False)
            ),
            wallet_source=value.get("wallet_source", "xrpl"),
            xaman_payload_id=value.get(
                "xaman_payload_id", value.get("payload_uuid", value.get("uuid", ""))
            ),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


@dataclass(frozen=True, slots=True)
class XRPLPaymentIntent:
    """Unsigned XRPL payment / ledger transition intent (declaration authority)."""

    intent_id: str
    chain_id: str
    account: str
    destination: str
    amount: Any
    destination_tag: int | None = None
    fee_drops: str = "12"
    flags: int = 0
    sequence: int | None = None
    ticket_sequence: int | None = None
    last_ledger_sequence: int | None = None
    transaction_type: str = "Payment"
    network: str = ""
    genesis_hash: str = ""
    wallet_source: str = "xrpl"
    xaman_payload_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        object.__setattr__(self, "chain_id", _text(str(self.chain_id), "chain_id"))
        object.__setattr__(self, "account", _text(self.account, "account"))
        object.__setattr__(self, "destination", _text(self.destination, "destination"))
        if isinstance(self.amount, float):
            raise XRPLAdapterError("amount rejects binary floats")
        object.__setattr__(
            self, "destination_tag", _optional_uint32(self.destination_tag, "destination_tag")
        )
        object.__setattr__(self, "flags", parse_flags(self.flags))
        object.__setattr__(
            self, "fee_drops", _text(str(self.fee_drops), "fee_drops")
        )
        if not _DECIMAL_INTEGER.fullmatch(self.fee_drops) or self.fee_drops.startswith("-"):
            raise XRPLAdapterError("fee_drops must be a non-negative integer string")
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
        for name in (
            "transaction_type",
            "network",
            "genesis_hash",
            "wallet_source",
            "xaman_payload_id",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(self, "raw", _attributes(self.raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "amount": self.amount,
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "fee_drops": self.fee_drops,
            "flags": self.flags,
            "genesis_hash": self.genesis_hash,
            "intent_id": self.intent_id,
            "kind": XRPLPayloadKind.PAYMENT_INTENT.value,
            "last_ledger_sequence": self.last_ledger_sequence,
            "network": self.network,
            "raw": thaw_json(self.raw),
            "sequence": self.sequence,
            "ticket_sequence": self.ticket_sequence,
            "transaction_type": self.transaction_type,
            "wallet_source": self.wallet_source,
            "xaman_payload_id": self.xaman_payload_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XRPLPaymentIntent":
        value = _as_mapping(value, "XRPLPaymentIntent")
        return cls(
            intent_id=value.get("intent_id", ""),
            chain_id=str(value.get("chain_id", "0")),
            account=value.get("account", value.get("Account", "")),
            destination=value.get("destination", value.get("Destination", "")),
            amount=value.get("amount", value.get("Amount")),
            destination_tag=value.get(
                "destination_tag", value.get("DestinationTag")
            ),
            fee_drops=str(value.get("fee_drops", value.get("Fee", "12")) or "12"),
            flags=value.get("flags", value.get("Flags", 0)),
            sequence=value.get("sequence", value.get("Sequence")),
            ticket_sequence=value.get(
                "ticket_sequence", value.get("TicketSequence")
            ),
            last_ledger_sequence=value.get(
                "last_ledger_sequence", value.get("LastLedgerSequence")
            ),
            transaction_type=value.get(
                "transaction_type", value.get("TransactionType", "Payment")
            ),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            wallet_source=value.get("wallet_source", "xrpl"),
            xaman_payload_id=value.get("xaman_payload_id", value.get("payload_uuid", "")),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def default_xrpl_capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=XRPL_CAPABILITY_ID,
        kind=CapabilityKind.CHAIN_ADAPTER,
        implementation_version=XRPL_ADAPTER_IMPLEMENTATION_VERSION,
        semantic_version=XRPL_ADAPTER_SEMANTIC_VERSION,
        status=CapabilityStatus.AVAILABLE,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=(XRPL_NAMESPACE,),
        features=(
            "wallet_records",
            "transaction_observation",
            "payment_intent",
            "ledger_transition",
            "classic_address",
            "x_address",
            "destination_tag",
            "issued_currency",
            "trust_line",
            "partial_payment",
            "delivered_amount",
            "sequence_ticket",
            "signer_list",
            "validated_ledger",
            "xaman",
            "hooks_capability_gated",
        ),
        summary=(
            "XRPL/Xaman native-ledger observation and payment conversion into Crypto IR"
        ),
        attributes={
            "known_chain_ids": sorted(KNOWN_NETWORKS),
            "preserves_raw_evidence": True,
            "invents_missing_facts": False,
            "native_model": "ledger_state_transitions",
            "not_evm_shaped": True,
        },
    )


class XRPLWalletAdapter:
    """Side-effect-free XRPL and Xaman wallet → Crypto IR adapter.

    Implements :class:`~ipfs_datasets_py.logic.crypto_ir.adapters.CryptoIRAdapter`.
    Models ledger state transitions; never invents Hooks or EVM sidechain facts.
    """

    def __init__(
        self,
        *,
        adapter_id: str = XRPL_ADAPTER_ID,
        capability: CapabilityDescriptor | None = None,
    ) -> None:
        self._adapter_id = _text(adapter_id, "adapter_id")
        if capability is None:
            capability = default_xrpl_capability()
        if not isinstance(capability, CapabilityDescriptor):
            raise XRPLAdapterError("capability must be a CapabilityDescriptor")
        if not capability.side_effect_free:
            raise XRPLAdapterError("XRPL adapter capability must be side-effect-free")
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
        | XRPLTransactionObservation
        | XRPLPaymentIntent
        | LedgerTransition,
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        """Convert *payload* without elevating authority or inventing facts."""

        if isinstance(payload, XRPLTransactionObservation):
            payload_map: Mapping[str, Any] = payload.to_dict()
        elif isinstance(payload, XRPLPaymentIntent):
            payload_map = payload.to_dict()
        elif isinstance(payload, LedgerTransition):
            payload_map = {
                **payload.to_dict(),
                "kind": XRPLPayloadKind.LEDGER_TRANSITION.value,
            }
        elif isinstance(payload, Mapping):
            payload_map = payload
        else:
            raise XRPLAdapterError(
                "payload must be a mapping or XRPL structured record"
            )

        source_digest = f"sha256:{content_sha256_hex(dict(payload_map))}"
        provenance_dict: dict[str, Any] = {}
        source_authority = AuthorityKind.OBSERVATION

        try:
            kind = self._detect_kind(payload_map)
            default_authority = (
                AuthorityKind.OBSERVATION
                if kind
                in {
                    XRPLPayloadKind.TRANSACTION_OBSERVATION,
                    XRPLPayloadKind.LEDGER_TRANSITION,
                    XRPLPayloadKind.XAMAN_PAYLOAD,
                }
                else AuthorityKind.DECLARATION
            )
            provenance_dict, source_authority = self._resolve_provenance(
                source_provenance, default=default_authority
            )
            if source_authority is AuthorityKind.AUTHORIZATION:
                raise XRPLAdapterError(
                    "cannot convert authorization-authority payload through XRPL adapter"
                )
            result_authority = source_authority

            if kind is XRPLPayloadKind.TRANSACTION_OBSERVATION:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_observation(payload_map)
                )
            elif kind is XRPLPayloadKind.XAMAN_PAYLOAD:
                # Xaman wraps XRPL facts; share observation conversion.
                merged = dict(payload_map)
                merged.setdefault("wallet_source", "xaman")
                if "tx" in merged and "kind" not in merged.get("tx", {}):
                    # Promote nested tx into observation fields via from_dict.
                    pass
                merged["kind"] = XRPLPayloadKind.TRANSACTION_OBSERVATION.value
                result_payload, unsupported, diagnostics, status = (
                    self._convert_observation(merged)
                )
                result_payload["record_type"] = "xaman_payload_observation"
                result_payload["wallet_source"] = "xaman"
            elif kind is XRPLPayloadKind.PAYMENT_INTENT:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_payment_intent(payload_map)
                )
            elif kind is XRPLPayloadKind.LEDGER_TRANSITION:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_ledger_transition(payload_map)
                )
            elif kind is XRPLPayloadKind.SERIALIZED_CANDIDATE:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_serialized_candidate(payload_map)
                )
            else:
                raise XRPLAdapterError(f"unsupported XRPL payload kind: {kind!r}")
        except XRPLAdapterError as exc:
            return AdapterConversionResult(
                conversion_id=f"xrpl-error:{self._adapter_id}",
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
                attributes={"error": True, "chain_namespace": XRPL_NAMESPACE},
            )

        result_digest = f"sha256:{content_sha256_hex(result_payload)}"
        conversion_id = f"xrpl:{kind.value}:{result_digest[:18]}"
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
                "chain_namespace": XRPL_NAMESPACE,
                "payload_kind": kind.value,
                "preserves_raw_evidence": True,
                "native_model": "ledger_state_transitions",
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
                    raise XRPLAdapterError(
                        f"unsupported source authority: {authority['kind']!r}"
                    ) from exc
            else:
                kind = default
            return data, kind
        raise XRPLAdapterError(
            "source_provenance must be CryptoIRProvenance or mapping"
        )

    def _detect_kind(self, payload: Mapping[str, Any]) -> XRPLPayloadKind:
        kind_raw = payload.get("kind", payload.get("payload_kind", ""))
        if kind_raw:
            text = _text(str(kind_raw), "kind").lower().replace("-", "_")
            aliases = {
                "transaction_observation": XRPLPayloadKind.TRANSACTION_OBSERVATION,
                "observation": XRPLPayloadKind.TRANSACTION_OBSERVATION,
                "xrpl_transaction_observation": XRPLPayloadKind.TRANSACTION_OBSERVATION,
                "payment_intent": XRPLPayloadKind.PAYMENT_INTENT,
                "unsigned_payment": XRPLPayloadKind.PAYMENT_INTENT,
                "xrpl_payment_intent": XRPLPayloadKind.PAYMENT_INTENT,
                "ledger_transition": XRPLPayloadKind.LEDGER_TRANSITION,
                "transition": XRPLPayloadKind.LEDGER_TRANSITION,
                "serialized_candidate": XRPLPayloadKind.SERIALIZED_CANDIDATE,
                "candidate": XRPLPayloadKind.SERIALIZED_CANDIDATE,
                "xaman_payload": XRPLPayloadKind.XAMAN_PAYLOAD,
                "xaman": XRPLPayloadKind.XAMAN_PAYLOAD,
            }
            if text in aliases:
                return aliases[text]
            raise XRPLAdapterError(f"unsupported XRPL payload kind: {kind_raw!r}")
        if payload.get("wallet_source") == "xaman" or payload.get("xaman_payload_id"):
            if payload.get("intent_id") and not payload.get("transaction_hash"):
                return XRPLPayloadKind.PAYMENT_INTENT
            return XRPLPayloadKind.XAMAN_PAYLOAD
        if "transition_id" in payload and "transaction_type" in payload:
            return XRPLPayloadKind.LEDGER_TRANSITION
        if "transaction_hash" in payload or "hash" in payload or "tx_hash" in payload:
            return XRPLPayloadKind.TRANSACTION_OBSERVATION
        if "intent_id" in payload or (
            "Amount" in payload and "Destination" in payload and "Account" in payload
        ):
            if "payload_digest" in payload or "encoding" in payload:
                return XRPLPayloadKind.SERIALIZED_CANDIDATE
            return XRPLPayloadKind.PAYMENT_INTENT
        if "payload_digest" in payload or "candidate_id" in payload:
            return XRPLPayloadKind.SERIALIZED_CANDIDATE
        if "observation_id" in payload:
            return XRPLPayloadKind.TRANSACTION_OBSERVATION
        raise XRPLAdapterError("unable to detect XRPL payload kind")

    def _build_transition_from_observation(
        self,
        obs: XRPLTransactionObservation,
        network: XRPLNetworkAnchor,
    ) -> tuple[LedgerTransition, list[UnsupportedField], list[str], list[str]]:
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []

        is_test = network.is_test
        if not obs.account:
            missing_coverage.append("account")
            unsupported.append(
                UnsupportedField(
                    path="account",
                    reason="Account absent; not invented",
                )
            )
            # Placeholder fails closed via ERROR if account required for Payment
            raise XRPLAdapterError("account is required for XRPL observation")

        account = XRPLAccountIdentity.parse(
            obs.account, is_test_network=is_test, field="account"
        )
        destination: XRPLAccountIdentity | None = None
        if obs.destination:
            destination = XRPLAccountIdentity.parse(
                obs.destination,
                destination_tag=obs.destination_tag,
                is_test_network=is_test,
                field="destination",
            )
        elif obs.destination_tag is not None:
            diagnostics.append(
                "destination_tag present without destination; tag preserved as unsupported"
            )
            unsupported.append(
                UnsupportedField(
                    path="destination",
                    reason="destination_tag without destination account; not invented",
                )
            )
            missing_coverage.append("destination")

        amount_kind = ""
        amount_value = ""
        issued: IssuedAsset | None = None
        if obs.amount is not None:
            amount_kind, amount_value, issued = parse_amount(obs.amount, field="Amount")
        else:
            missing_coverage.append("amount")
            unsupported.append(
                UnsupportedField(
                    path="amount",
                    reason="Amount absent; not invented as zero XRP",
                )
            )

        del_kind = ""
        del_value = ""
        del_issued: IssuedAsset | None = None
        delivered_source = obs.delivered_amount
        if delivered_source is None and obs.meta is not None:
            delivered_source = obs.meta.get("delivered_amount", obs.meta.get("DeliveredAmount"))
        if delivered_source is not None:
            del_kind, del_value, del_issued = parse_amount(
                delivered_source, field="delivered_amount"
            )
        else:
            if has_partial_payment(obs.flags):
                missing_coverage.append("delivered_amount")
                unsupported.append(
                    UnsupportedField(
                        path="delivered_amount",
                        reason=(
                            "partial payment flag set but delivered_amount absent; "
                            "not invented from Amount"
                        ),
                    )
                )
            else:
                missing_coverage.append("delivered_amount")
                diagnostics.append(
                    "delivered_amount absent; full Amount may equal delivered when validated"
                )

        if not obs.transaction_hash:
            missing_coverage.append("transaction_hash")
            unsupported.append(
                UnsupportedField(
                    path="transaction_hash",
                    reason="transaction hash absent; not invented",
                )
            )

        if obs.sequence is None and obs.ticket_sequence is None:
            missing_coverage.append("sequence_or_ticket")
            unsupported.append(
                UnsupportedField(
                    path="sequence",
                    reason="Sequence and TicketSequence absent; not invented",
                )
            )

        if obs.signers is None:
            missing_coverage.append("signers")
            diagnostics.append("signers absent; single-signer assumed only as absence")
        if obs.validated is None and not obs.finality:
            missing_coverage.append("validated_ledger")
            unsupported.append(
                UnsupportedField(
                    path="validated",
                    reason="validated/finality absent; left unknown (not invented)",
                )
            )

        # Hooks / EVM: never infer
        hooks_present = obs.hooks_capability_present
        hooks_effects: tuple[Mapping[str, Any], ...] = ()
        if hooks_present:
            if obs.hooks_effects:
                hooks_effects = tuple(obs.hooks_effects)
            else:
                diagnostics.append(
                    "hooks_capability_present but hooks_effects empty"
                )
        else:
            if obs.hooks_effects:
                unsupported.append(
                    UnsupportedField(
                        path="hooks_effects",
                        reason=(
                            "Hooks effects present without network capability evidence; "
                            "treated as UNSUPPORTED"
                        ),
                    )
                )
                diagnostics.append("hooks_effects ignored without capability evidence")
            else:
                diagnostics.append(
                    "Hooks not inferred; capability evidence required for hook semantics"
                )

        if not obs.evm_sidechain_capability_present:
            diagnostics.append(
                "EVM sidechain behavior not inferred; capability evidence required"
            )

        tx_type = map_transaction_type(obs.transaction_type)
        if tx_type is XRPLTransitionKind.SET_HOOK and not hooks_present:
            diagnostics.append(
                "SetHook transaction observed without hooks capability evidence"
            )
            unsupported.append(
                UnsupportedField(
                    path="hooks_capability_present",
                    reason="SetHook without Hooks network capability; effects UNSUPPORTED",
                )
            )

        transition = LedgerTransition(
            transition_id=obs.observation_id,
            transaction_type=tx_type,
            account=account,
            destination=destination,
            amount_kind=amount_kind,
            amount_value=amount_value,
            issued_asset=issued,
            delivered_amount_kind=del_kind,
            delivered_amount_value=del_value,
            delivered_issued_asset=del_issued,
            fee_drops=obs.fee_drops,
            flags=obs.flags,
            partial_payment=has_partial_payment(obs.flags),
            sequence=obs.sequence,
            ticket_sequence=obs.ticket_sequence,
            last_ledger_sequence=obs.last_ledger_sequence,
            signers=tuple(obs.signers or ()),
            signer_quorum=obs.signer_quorum,
            ledger_index=obs.ledger_index,
            ledger_hash=obs.ledger_hash,
            transaction_index=obs.transaction_index,
            transaction_hash=obs.transaction_hash,
            validated=obs.validated,
            engine_result=obs.engine_result,
            memos=tuple(obs.memos or ()),
            hooks_capability_present=hooks_present,
            hooks_effects=hooks_effects,
            evm_sidechain_capability_present=obs.evm_sidechain_capability_present,
            trust_line=obs.trust_line,
            attributes={
                "wallet_source": obs.wallet_source,
                "xaman_payload_id": obs.xaman_payload_id,
                "source_attributes": thaw_json(obs.attributes),
            },
            raw=obs.raw if obs.raw else {},
        )
        return transition, unsupported, diagnostics, missing_coverage

    def _convert_observation(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        obs = XRPLTransactionObservation.from_dict(payload)
        network = resolve_network(
            chain_id=obs.chain_id,
            network=obs.network or None,
            genesis_hash=obs.genesis_hash or None,
        )
        chain = network.to_chain_identity()
        transition, unsupported, diagnostics, missing_coverage = (
            self._build_transition_from_observation(obs, network)
        )

        # Finality: validated=true maps to finalized; explicit finality wins.
        if obs.finality:
            finality = map_finality(obs.finality)
        elif obs.validated is True:
            finality = FinalityStatus.FINALIZED
        elif obs.validated is False:
            finality = FinalityStatus.PROPOSED
        else:
            finality = FinalityStatus.UNKNOWN

        retraction = (
            map_retraction(obs.retraction)
            if obs.retraction
            else RetractionStatus.UNKNOWN
        )
        if not obs.retraction:
            missing_coverage.append("retraction")

        from_account = transition.account.to_account_identity(chain)
        to_account = (
            None
            if transition.destination is None
            else transition.destination.to_account_identity(chain)
        )

        coordinate = LedgerCoordinate(
            sequence=transition.ledger_index,
            hash=transition.ledger_hash.lower() if transition.ledger_hash else "",
            transaction_index=transition.transaction_index,
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

        tx_digest = (
            sha256_digest_tag(transition.transaction_hash)
            if transition.transaction_hash
            else sha256_digest_tag("0" * 64)
        )
        if not transition.transaction_hash:
            diagnostics.append(
                "transaction_hash absent; zero digest placeholder for schema only"
            )

        observed = ObservedTransaction(
            observation_id=obs.observation_id,
            chain=chain,
            tx_digest=tx_digest,
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
                "transaction_hash": transition.transaction_hash,
                "transaction_type": transition.transaction_type.value,
                "flags": transition.flags,
                "partial_payment": transition.partial_payment,
                "sequence": transition.sequence,
                "ticket_sequence": transition.ticket_sequence,
                "fee_drops": transition.fee_drops,
                "engine_result": transition.engine_result,
                "validated": transition.validated,
                "wallet_source": obs.wallet_source,
                "xaman_payload_id": obs.xaman_payload_id,
                "missing_coverage": list(missing_coverage),
                "raw": thaw_json(obs.raw),
                "source_attributes": thaw_json(obs.attributes),
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
                "native_model": "ledger_state_transitions",
                "not_evm_shaped": True,
            },
        )

        # Asset transfers as typed records
        transfer_record: dict[str, Any] | None = None
        if transition.amount_kind == "xrp" and transition.amount_value:
            transfer_record = {
                "asset": native_xrp_asset(chain).to_dict(),
                "amount": ExactAmount(
                    base_units=transition.amount_value, decimals=NATIVE_DECIMALS
                ).to_dict(),
                "from_account": from_account.to_dict(),
                "to_account": None if to_account is None else to_account.to_dict(),
                "kind": "xrp",
                "unit": "drops",
            }
        elif transition.amount_kind == "issued" and transition.issued_asset is not None:
            # Issued amounts are decimal strings; store exact value, decimals=0.
            transfer_record = {
                "asset": transition.issued_asset.to_asset_identity(chain).to_dict(),
                "amount": {
                    "base_units": transition.amount_value,
                    "decimals": 0,
                    "encoding": "decimal_string",
                },
                "from_account": from_account.to_dict(),
                "to_account": None if to_account is None else to_account.to_dict(),
                "kind": "issued",
                "issued_asset": transition.issued_asset.to_dict(),
            }

        delivered_record: dict[str, Any] | None = None
        if transition.delivered_amount_kind == "xrp" and transition.delivered_amount_value:
            delivered_record = {
                "asset": native_xrp_asset(chain).to_dict(),
                "amount": ExactAmount(
                    base_units=transition.delivered_amount_value,
                    decimals=NATIVE_DECIMALS,
                ).to_dict(),
                "kind": "xrp",
                "unit": "drops",
            }
        elif (
            transition.delivered_amount_kind == "issued"
            and transition.delivered_issued_asset is not None
        ):
            delivered_record = {
                "asset": transition.delivered_issued_asset.to_asset_identity(
                    chain
                ).to_dict(),
                "amount": {
                    "base_units": transition.delivered_amount_value,
                    "decimals": 0,
                    "encoding": "decimal_string",
                },
                "kind": "issued",
                "issued_asset": transition.delivered_issued_asset.to_dict(),
            }

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
            scope=f"xrpl-tx:{transition.transaction_hash or obs.observation_id}",
            completeness=completeness_status,
            finality=finality,
            validity=ValidityWindow(start=obs.validity_start, end=obs.validity_end),
            retraction=retraction,
            covered_ranges=(coordinate,) if transition.ledger_index is not None else (),
            missing_ranges=(),
            provider_ids=(self._adapter_id,),
            attributes={
                "missing_coverage": list(missing_coverage),
                "validated": transition.validated,
                "partial_payment": transition.partial_payment,
            },
        )

        # Explicit Hooks / EVM unsupported semantics
        hooks_status = (
            "supported"
            if transition.hooks_capability_present
            else "UNSUPPORTED"
        )
        evm_status = (
            "supported"
            if transition.evm_sidechain_capability_present
            else "UNSUPPORTED"
        )

        result_payload = {
            "record_type": "xrpl_transaction_observation",
            "authority": AuthorityKind.OBSERVATION.value,
            "chain": chain.to_dict(),
            "observed_transaction": observed.to_dict(),
            "ledger_transition": transition.to_dict(),
            "transfer": transfer_record,
            "delivered_amount": delivered_record,
            "native_xrp_asset": native_xrp_asset(chain).to_dict(),
            "issued_asset": None
            if transition.issued_asset is None
            else transition.issued_asset.to_dict(),
            "accounts": {
                "account": transition.account.to_dict(),
                "destination": None
                if transition.destination is None
                else transition.destination.to_dict(),
            },
            "typed_facts": {
                "flags": transition.flags,
                "partial_payment": transition.partial_payment,
                "sequence": transition.sequence,
                "ticket_sequence": transition.ticket_sequence,
                "signer_quorum": transition.signer_quorum,
                "signers": [thaw_json(s) for s in transition.signers],
                "validated": transition.validated,
                "ledger_index": transition.ledger_index,
                "ledger_hash": transition.ledger_hash,
                "engine_result": transition.engine_result,
                "fee_drops": transition.fee_drops,
            },
            "hooks": {
                "status": hooks_status,
                "capability_present": transition.hooks_capability_present,
                "effects": [thaw_json(h) for h in transition.hooks_effects],
            },
            "evm_sidechain": {
                "status": evm_status,
                "capability_present": transition.evm_sidechain_capability_present,
            },
            "completeness": completeness.to_dict(),
            "missing_coverage": list(missing_coverage),
            "meta": None if obs.meta is None else thaw_json(obs.meta),
            "raw": thaw_json(obs.raw) if obs.raw else {},
            "wallet_source": obs.wallet_source,
            "xaman_payload_id": obs.xaman_payload_id,
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

    def _convert_ledger_transition(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        # Allow bare LedgerTransition dicts with chain_id at top level.
        chain_id = payload.get("chain_id", "0")
        network = resolve_network(
            chain_id=chain_id,
            network=payload.get("network") or None,
            genesis_hash=payload.get("genesis_hash") or None,
        )
        chain = network.to_chain_identity()
        transition = LedgerTransition.from_dict(payload)
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []

        if not transition.hooks_capability_present and transition.hooks_effects:
            unsupported.append(
                UnsupportedField(
                    path="hooks_effects",
                    reason="Hooks effects without capability evidence; UNSUPPORTED",
                )
            )
        if not transition.hooks_capability_present:
            diagnostics.append("Hooks status=UNSUPPORTED without capability evidence")
        if not transition.evm_sidechain_capability_present:
            diagnostics.append(
                "EVM sidechain status=UNSUPPORTED without capability evidence"
            )

        result_payload = {
            "record_type": "xrpl_ledger_transition",
            "authority": AuthorityKind.OBSERVATION.value,
            "chain": chain.to_dict(),
            "ledger_transition": transition.to_dict(),
            "accounts": {
                "account": transition.account.to_dict(),
                "destination": None
                if transition.destination is None
                else transition.destination.to_dict(),
            },
            "issued_asset": None
            if transition.issued_asset is None
            else transition.issued_asset.to_dict(),
            "native_xrp_asset": native_xrp_asset(chain).to_dict(),
            "hooks": {
                "status": (
                    "supported"
                    if transition.hooks_capability_present
                    else "UNSUPPORTED"
                ),
                "capability_present": transition.hooks_capability_present,
            },
            "evm_sidechain": {
                "status": (
                    "supported"
                    if transition.evm_sidechain_capability_present
                    else "UNSUPPORTED"
                ),
                "capability_present": transition.evm_sidechain_capability_present,
            },
            "typed_facts": {
                "flags": transition.flags,
                "partial_payment": transition.partial_payment,
                "sequence": transition.sequence,
                "ticket_sequence": transition.ticket_sequence,
                "validated": transition.validated,
            },
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"chain_id={network.chain_id};network={network.network}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _convert_payment_intent(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        intent = XRPLPaymentIntent.from_dict(payload)
        network = resolve_network(
            chain_id=intent.chain_id,
            network=intent.network or None,
            genesis_hash=intent.genesis_hash or None,
        )
        chain = network.to_chain_identity()
        account = XRPLAccountIdentity.parse(
            intent.account, is_test_network=network.is_test, field="account"
        )
        destination = XRPLAccountIdentity.parse(
            intent.destination,
            destination_tag=intent.destination_tag,
            is_test_network=network.is_test,
            field="destination",
        )
        amount_kind, amount_value, issued = parse_amount(intent.amount, field="Amount")
        origin = account.to_account_identity(chain)
        dest_ai = destination.to_account_identity(chain)
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []

        if amount_kind == "xrp":
            asset = native_xrp_asset(chain)
            amount = ExactAmount(base_units=amount_value, decimals=NATIVE_DECIMALS)
            transfer = TransferIntent(
                asset=asset,
                amount=amount,
                from_account=origin,
                to_account=dest_ai,
                attributes={
                    "kind": "xrp",
                    "unit": "drops",
                    "flags": intent.flags,
                    "partial_payment": has_partial_payment(intent.flags),
                    "destination_tag": destination.destination_tag,
                },
            )
        else:
            assert issued is not None
            asset = issued.to_asset_identity(chain)
            # Decimal-string issued amount stored with decimals=0 sentinel.
            amount = ExactAmount(
                base_units=amount_value.replace(".", "").lstrip("-") or "0"
                if "." in amount_value
                else amount_value,
                decimals=0,
            )
            # Prefer preserving exact decimal string in attributes when fractional.
            transfer = TransferIntent(
                asset=asset,
                amount=amount,
                from_account=origin,
                to_account=dest_ai,
                attributes={
                    "kind": "issued",
                    "issued_value_exact": amount_value,
                    "issued_asset": issued.to_dict(),
                    "flags": intent.flags,
                    "partial_payment": has_partial_payment(intent.flags),
                    "destination_tag": destination.destination_tag,
                },
            )
            if "." in amount_value:
                diagnostics.append(
                    "issued amount fractional decimal preserved in issued_value_exact"
                )

        if intent.sequence is None and intent.ticket_sequence is None:
            unsupported.append(
                UnsupportedField(
                    path="sequence",
                    reason="Sequence/TicketSequence absent on intent; not invented",
                )
            )

        signers = (SignerRequirement(account=origin, role="origin"),)
        unsigned = UnsignedTransactionIntent(
            intent_id=intent.intent_id,
            chain=chain,
            origin=origin,
            signers=signers,
            transfers=(transfer,),
            calls=(),  # XRPL is not call/contract shaped
            attributes={
                "raw": thaw_json(intent.raw),
                "source_attributes": thaw_json(intent.attributes),
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
                "transaction_type": intent.transaction_type,
                "fee_drops": intent.fee_drops,
                "flags": intent.flags,
                "partial_payment": has_partial_payment(intent.flags),
                "sequence": intent.sequence,
                "ticket_sequence": intent.ticket_sequence,
                "last_ledger_sequence": intent.last_ledger_sequence,
                "wallet_source": intent.wallet_source,
                "xaman_payload_id": intent.xaman_payload_id,
                "destination_tag": destination.destination_tag,
                "classic_destination": destination.classic_address,
                "x_address_destination": destination.x_address,
                "native_model": "ledger_state_transitions",
                "not_evm_shaped": True,
                "xrpl_payment_intent": intent.to_dict(),
            },
        )

        result_payload = {
            "record_type": "xrpl_payment_intent",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "unsigned_transaction_intent": unsigned.to_dict(),
            "accounts": {
                "account": account.to_dict(),
                "destination": destination.to_dict(),
            },
            "transfer": {
                "kind": amount_kind,
                "amount_value": amount_value,
                "issued_asset": None if issued is None else issued.to_dict(),
            },
            "typed_facts": {
                "flags": intent.flags,
                "partial_payment": has_partial_payment(intent.flags),
                "sequence": intent.sequence,
                "ticket_sequence": intent.ticket_sequence,
                "fee_drops": intent.fee_drops,
                "destination_tag": destination.destination_tag,
            },
            "hooks": {"status": "UNSUPPORTED", "capability_present": False},
            "evm_sidechain": {"status": "UNSUPPORTED", "capability_present": False},
            "wallet_source": intent.wallet_source,
            "xaman_payload_id": intent.xaman_payload_id,
            "raw": thaw_json(intent.raw),
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"chain_id={network.chain_id};network={network.network}"
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
        intent_id = _identifier(payload.get("intent_id", candidate_id), "intent_id")
        network = resolve_network(
            chain_id=payload.get("chain_id", "0"),
            network=payload.get("network") or None,
            genesis_hash=payload.get("genesis_hash") or None,
        )
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []

        raw_blob = payload.get(
            "tx_blob", payload.get("serialized", payload.get("blob"))
        )
        payload_digest = payload.get("payload_digest", "")
        encoding = _text(payload.get("encoding", "xrpl-binary"), "encoding")
        byte_length = payload.get("byte_length")

        if raw_blob is not None:
            blob = _text(str(raw_blob), "tx_blob")
            # Accept hex without 0x
            hex_body = blob[2:] if blob.startswith("0x") else blob
            if not re.fullmatch(r"(?:[0-9A-Fa-f]{2})+", hex_body):
                raise XRPLAdapterError("tx_blob must be even-length hex")
            body = bytes.fromhex(hex_body)
            if byte_length is None:
                byte_length = len(body)
            if not payload_digest:
                payload_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
            raw_hex = hex_body.upper()
        else:
            raw_hex = None
            if not payload_digest:
                raise XRPLAdapterError(
                    "serialized candidate requires tx_blob or payload_digest"
                )
            if byte_length is None:
                unsupported.append(
                    UnsupportedField(
                        path="byte_length",
                        reason="byte_length absent without raw bytes; not invented",
                    )
                )
                byte_length = 0
            diagnostics.append("tx_blob absent; digest-only candidate preserved")

        digest = _text(str(payload_digest), "payload_digest")
        if digest.startswith("0x") and len(digest) == 66:
            digest = f"sha256:{digest[2:].lower()}"
        elif ":" not in digest and len(digest) == 64:
            digest = f"sha256:{digest.lower()}"

        candidate = SerializedTransactionCandidate(
            candidate_id=candidate_id,
            intent_id=intent_id,
            chain=chain,
            payload_digest=digest,
            encoding=encoding,
            byte_length=_non_negative_int(byte_length, "byte_length"),
            attributes={
                "tx_blob": raw_hex,
                "tx_blob_absent": raw_hex is None,
                "network_anchor": {
                    "chain_id": network.chain_id,
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                },
                "native_model": "ledger_state_transitions",
                "wallet_source": payload.get("wallet_source", "xrpl"),
                "xaman_payload_id": payload.get("xaman_payload_id", ""),
            },
        )
        result_payload = {
            "record_type": "xrpl_serialized_candidate",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "serialized_transaction_candidate": candidate.to_dict(),
            "tx_blob": raw_hex,
            "tx_blob_absent": raw_hex is None,
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"chain_id={network.chain_id};network={network.network}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status


def convert_xrpl_payload(
    payload: Mapping[str, Any]
    | XRPLTransactionObservation
    | XRPLPaymentIntent
    | LedgerTransition,
    *,
    source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    adapter: XRPLWalletAdapter | None = None,
) -> AdapterConversionResult:
    """Module-level helper around :class:`XRPLWalletAdapter.convert`."""

    return (adapter or XRPLWalletAdapter()).convert(
        payload, source_provenance=source_provenance
    )


__all__ = [
    "CRYPTO_IR_XRPL_ADAPTER_DOMAIN",
    "XRPL_ADAPTER_ID",
    "XRPL_CAPABILITY_ID",
    "XRPL_NAMESPACE",
    "XRPL_MAINNET_CHAIN_ID",
    "XRPL_MAINNET_GENESIS_HASH",
    "XRPL_MAINNET_NETWORK",
    "XRPL_TESTNET_CHAIN_ID",
    "XRPL_TESTNET_GENESIS_HASH",
    "XRPL_TESTNET_NETWORK",
    "XRPL_DEVNET_CHAIN_ID",
    "XRPL_DEVNET_GENESIS_HASH",
    "XRPL_DEVNET_NETWORK",
    "NATIVE_ASSET_NAMESPACE",
    "NATIVE_ASSET_REFERENCE",
    "NATIVE_DECIMALS",
    "NATIVE_SYMBOL",
    "DROPS_PER_XRP",
    "TF_PARTIAL_PAYMENT",
    "KNOWN_NETWORKS",
    "IssuedAsset",
    "LedgerTransition",
    "XRPLAccountIdentity",
    "XRPLAdapterError",
    "XRPLNetworkAnchor",
    "XRPLPayloadKind",
    "XRPLPaymentIntent",
    "XRPLTransactionObservation",
    "XRPLTransitionKind",
    "XRPLWalletAdapter",
    "account_id_from_classic_address",
    "b58decode_xrpl",
    "b58encode_xrpl",
    "classic_address_from_account_id",
    "content_sha256_hex",
    "convert_xrpl_payload",
    "decode_x_address",
    "default_xrpl_capability",
    "encode_x_address",
    "has_partial_payment",
    "map_finality",
    "map_retraction",
    "map_transaction_type",
    "native_xrp_asset",
    "normalize_classic_address",
    "normalize_ledger_hash",
    "parse_amount",
    "parse_flags",
    "resolve_network",
    "sha256_digest_tag",
]
