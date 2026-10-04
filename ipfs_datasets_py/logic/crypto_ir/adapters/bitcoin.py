"""Bitcoin wallet-to-Crypto-IR adapter (CRYPTOIR-G130 / CRYPTOIR-010).

Convert Bitcoin wallet, transaction, UTXO, script-classification, and finality
records into network-bound Crypto IR with exact input/output and spending-
context identity.

Design constraints:

* Import and conversion are side-effect free (no sockets, no package install).
* Network/genesis (bip122) bind every observation and UTXO record.
* Outpoints and script commitments are the canonical spending identity;
  display addresses are never authoritative for spendability.
* Txid display hex and internal (byte-reversed) forms are both preserved.
* Satoshi amounts are exact base-unit integers (no binary floats).
* Script bytes, witness stacks, sequence, confirmations, replacement,
  coinbase, and reorg state survive conversion as normalized fields.
* Missing previous-output facts remain incomplete (never invented).
* No Script execution, Miniscript evaluation, or PSBT signing is performed.

This module owns only the Bitcoin adapter surface and its offline fixtures.
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


CRYPTO_IR_BITCOIN_ADAPTER_DOMAIN: Final[str] = "crypto-ir.adapter.bitcoin"
BITCOIN_NAMESPACE: Final[str] = "bip122"
BITCOIN_ADAPTER_ID: Final[str] = "crypto-ir.adapter.bitcoin"
BITCOIN_CAPABILITY_ID: Final[str] = "crypto-ir.chain-adapter.bitcoin"
BITCOIN_ADAPTER_IMPLEMENTATION_VERSION: Final[str] = "1.0.0"
BITCOIN_ADAPTER_SEMANTIC_VERSION: Final[str] = "1.0.0"

NATIVE_ASSET_NAMESPACE: Final[str] = "slip44"
NATIVE_ASSET_REFERENCE: Final[str] = "0"
NATIVE_DECIMALS: Final[int] = 8
NATIVE_SYMBOL: Final[str] = "BTC"
MAX_MONEY_SATS: Final[int] = 21_000_000 * 100_000_000

# Genesis block hashes (full 32-byte hex, no 0x prefix). BIP122 chain_id is
# the first 32 hex characters of the genesis hash.
MAINNET_GENESIS: Final[str] = (
    "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
)
TESTNET_GENESIS: Final[str] = (
    "000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943"
)
SIGNET_GENESIS: Final[str] = (
    "00000008819873e925422c1ff0f99f7cc9bbb232af63a077a480a3633bee1ef6"
)
REGTEST_GENESIS: Final[str] = (
    "0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206"
)

MAINNET_NETWORK: Final[str] = "bitcoin-mainnet"
TESTNET_NETWORK: Final[str] = "bitcoin-testnet"
SIGNET_NETWORK: Final[str] = "bitcoin-signet"
REGTEST_NETWORK: Final[str] = "bitcoin-regtest"

COINBASE_TXID_DISPLAY: Final[str] = "0" * 64
COINBASE_VOUT: Final[int] = 0xFFFFFFFF

_TXID_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0x)?(?:[0-9a-fA-F]{2})*$")
_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^(?:0|[1-9][0-9]*)$")
_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"
)


class BitcoinAdapterError(CryptoIRAdapterError):
    """Raised when a Bitcoin wallet payload cannot be converted fail-closed."""


class BitcoinPayloadKind(str, Enum):
    """Supported offline conversion payload kinds."""

    TRANSACTION_OBSERVATION = "transaction_observation"
    UTXO_SET = "utxo_set"
    SPEND_INTENT = "spend_intent"
    SERIALIZED_CANDIDATE = "serialized_candidate"


class ScriptType(str, Enum):
    """Standard Bitcoin script forms recognized without execution."""

    P2PKH = "p2pkh"
    P2SH = "p2sh"
    P2WPKH = "p2wpkh"
    P2WSH = "p2wsh"
    P2TR = "p2tr"
    P2PK = "p2pk"
    MULTISIG = "multisig"
    NULL_DATA = "null_data"
    UNKNOWN = "unknown"
    COINBASE = "coinbase"


class TxStatus(str, Enum):
    """Mempool / confirmed / replacement / reorg status labels."""

    MEMPOOL = "mempool"
    CONFIRMED = "confirmed"
    REPLACED = "replaced"
    ORPHANED = "orphaned"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise BitcoinAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise BitcoinAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise BitcoinAdapterError(f"{name} must not have surrounding whitespace")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BitcoinAdapterError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise BitcoinAdapterError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise BitcoinAdapterError(str(exc)) from exc


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise BitcoinAdapterError(f"{name} is not a stable identifier")
    return normalized


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise BitcoinAdapterError(f"{name} must be an integer")
    if value < 0:
        raise BitcoinAdapterError(f"{name} must be non-negative")
    return value


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, name)


def content_sha256_hex(value: Any) -> str:
    """Return bare 64-char sha256 hex for a JSON-compatible value."""

    from ...ir_core.canonical import canonical_json_bytes

    frozen = freeze_json(value)
    digest_label = sha256_digest(canonical_json_bytes(frozen))
    if digest_label.startswith("sha256:"):
        return digest_label.split(":", 1)[1]
    return digest_label


def sha256_digest_tag(value: str | bytes) -> str:
    if isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = value
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def reverse_hex_bytes(hex_value: str) -> str:
    """Reverse byte order of an even-length hex string (txid internal form)."""

    text = hex_value.lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) % 2 != 0 or not re.fullmatch(r"[0-9a-f]*", text):
        raise BitcoinAdapterError("hex value must be even-length lowercase hex")
    pairs = [text[i : i + 2] for i in range(0, len(text), 2)]
    return "".join(reversed(pairs))


def normalize_txid(value: object, *, field: str = "txid") -> str:
    """Normalize a display-form Bitcoin txid to lowercase 64-char hex.

    RPC and wallet surfaces present the *display* form (byte-reversed relative
    to the internal double-SHA256 digest).  Conversion preserves both forms via
    :func:`txid_byte_order_record`.
    """

    text = _text(str(value), field)
    if text.startswith("0x") or text.startswith("0X"):
        text = text[2:]
    if not _TXID_RE.fullmatch(text) and not re.fullmatch(r"[0-9a-fA-F]{64}", text):
        raise BitcoinAdapterError(f"{field} must be a 32-byte hex txid")
    return text.lower()


def txid_byte_order_record(display_txid: str) -> dict[str, str]:
    """Return display and internal (byte-reversed) txid forms."""

    display = normalize_txid(display_txid, field="txid")
    internal = reverse_hex_bytes(display)
    return {
        "txid_display": display,
        "txid_internal": internal,
        "byte_order": "display_is_reversed_of_internal",
    }


def normalize_hex_script(value: object, *, field: str = "script_hex") -> str:
    """Normalize script bytes to lowercase hex without a 0x prefix."""

    text = _text(str(value), field, allow_empty=True)
    if not text:
        return ""
    if text.startswith("0x") or text.startswith("0X"):
        text = text[2:]
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", text):
        raise BitcoinAdapterError(f"{field} must be even-length hex")
    return text.lower()


def script_commitment(script_hex: str) -> str:
    """Authoritative script commitment: sha256 of raw script bytes.

    Empty script is allowed (e.g. coinbase placeholder) and still yields a
    deterministic digest of the empty byte string.
    """

    raw = bytes.fromhex(script_hex) if script_hex else b""
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def parse_sats(value: object, *, field: str = "value_sats") -> str:
    """Parse satoshi amounts as canonical decimal-integer strings.

    Binary floats are rejected.  Values exceeding the max money supply fail
    closed.  The result is a string base-units quantity for ExactAmount.
    """

    if isinstance(value, bool):
        raise BitcoinAdapterError(f"{field} must not be a boolean")
    if isinstance(value, float):
        raise BitcoinAdapterError(
            f"{field} must not be a binary float; use integer satoshis"
        )
    if type(value) is int:
        sats = value
    elif isinstance(value, str):
        text = value.strip()
        if not _DECIMAL_INTEGER.fullmatch(text):
            raise BitcoinAdapterError(
                f"{field} must be a canonical decimal integer string"
            )
        sats = int(text, 10)
    else:
        raise BitcoinAdapterError(f"{field} must be an int or decimal integer string")
    if sats < 0:
        raise BitcoinAdapterError(f"{field} must not be negative")
    if sats > MAX_MONEY_SATS:
        raise BitcoinAdapterError(f"{field} exceeds maximum Bitcoin supply in sats")
    return str(sats)


def parse_script_type(value: Any) -> ScriptType:
    if value is None or value == "":
        return ScriptType.UNKNOWN
    if isinstance(value, ScriptType):
        return value
    text = _text(str(value), "script_type").lower().replace("-", "_")
    aliases = {
        "p2pkh": ScriptType.P2PKH,
        "pubkeyhash": ScriptType.P2PKH,
        "p2sh": ScriptType.P2SH,
        "scripthash": ScriptType.P2SH,
        "p2wpkh": ScriptType.P2WPKH,
        "v0_p2wpkh": ScriptType.P2WPKH,
        "p2wsh": ScriptType.P2WSH,
        "v0_p2wsh": ScriptType.P2WSH,
        "p2tr": ScriptType.P2TR,
        "v1_p2tr": ScriptType.P2TR,
        "taproot": ScriptType.P2TR,
        "p2pk": ScriptType.P2PK,
        "pubkey": ScriptType.P2PK,
        "multisig": ScriptType.MULTISIG,
        "null_data": ScriptType.NULL_DATA,
        "op_return": ScriptType.NULL_DATA,
        "unknown": ScriptType.UNKNOWN,
        "coinbase": ScriptType.COINBASE,
        "nonstandard": ScriptType.UNKNOWN,
    }
    if text in aliases:
        return aliases[text]
    try:
        return ScriptType(text)
    except ValueError as exc:
        raise BitcoinAdapterError(f"unsupported script_type: {value!r}") from exc


def parse_tx_status(value: Any) -> TxStatus:
    if value is None or value == "":
        return TxStatus.UNKNOWN
    if isinstance(value, TxStatus):
        return value
    text = _text(str(value), "status").lower().replace("-", "_")
    aliases = {
        "mempool": TxStatus.MEMPOOL,
        "unconfirmed": TxStatus.MEMPOOL,
        "pending": TxStatus.MEMPOOL,
        "confirmed": TxStatus.CONFIRMED,
        "in_block": TxStatus.CONFIRMED,
        "replaced": TxStatus.REPLACED,
        "rbf": TxStatus.REPLACED,
        "orphaned": TxStatus.ORPHANED,
        "reorged": TxStatus.ORPHANED,
        "unknown": TxStatus.UNKNOWN,
    }
    if text in aliases:
        return aliases[text]
    try:
        return TxStatus(text)
    except ValueError as exc:
        raise BitcoinAdapterError(f"unsupported status: {value!r}") from exc


def map_finality(
    value: Any,
    *,
    confirmations: int | None = None,
    status: TxStatus | None = None,
) -> FinalityStatus:
    """Map wallet finality / status / confirmations; absence stays UNKNOWN."""

    if isinstance(value, FinalityStatus):
        return value
    if value is not None and value != "":
        text = _text(str(value), "finality").lower().replace("-", "_")
        aliases = {
            "unknown": FinalityStatus.UNKNOWN,
            "proposed": FinalityStatus.PROPOSED,
            "mempool": FinalityStatus.PROPOSED,
            "unconfirmed": FinalityStatus.PROPOSED,
            "pending": FinalityStatus.PROPOSED,
            "confirmed": FinalityStatus.CONFIRMED,
            "safe": FinalityStatus.CONFIRMED,
            "finalized": FinalityStatus.FINALIZED,
            "final": FinalityStatus.FINALIZED,
            "reorged": FinalityStatus.REORGED,
            "orphaned": FinalityStatus.REORGED,
            "retracted": FinalityStatus.RETRACTED,
            "replaced": FinalityStatus.RETRACTED,
        }
        if text in aliases:
            return aliases[text]
        try:
            return FinalityStatus(text)
        except ValueError as exc:
            raise BitcoinAdapterError(f"unsupported finality: {value!r}") from exc

    # Compare by value so reloaded-module enum members remain compatible.
    status_value = status.value if isinstance(status, TxStatus) else status
    if status_value == TxStatus.MEMPOOL.value:
        return FinalityStatus.PROPOSED
    if status_value == TxStatus.REPLACED.value:
        return FinalityStatus.RETRACTED
    if status_value == TxStatus.ORPHANED.value:
        return FinalityStatus.REORGED
    if status_value == TxStatus.CONFIRMED.value:
        if confirmations is None:
            return FinalityStatus.CONFIRMED
        if confirmations <= 0:
            return FinalityStatus.PROPOSED
        if confirmations >= 100:
            return FinalityStatus.FINALIZED
        return FinalityStatus.CONFIRMED
    return FinalityStatus.UNKNOWN


def map_retraction(
    value: Any,
    *,
    status: TxStatus | None = None,
) -> RetractionStatus:
    if isinstance(value, RetractionStatus):
        return value
    if value is not None and value != "":
        text = _text(str(value), "retraction").lower().replace("-", "_")
        aliases = {
            "not_retracted": RetractionStatus.NOT_RETRACTED,
            "none": RetractionStatus.NOT_RETRACTED,
            "superseded": RetractionStatus.SUPERSEDED,
            "replaced": RetractionStatus.SUPERSEDED,
            "retracted": RetractionStatus.RETRACTED,
            "orphaned": RetractionStatus.RETRACTED,
            "unknown": RetractionStatus.UNKNOWN,
        }
        if text in aliases:
            return aliases[text]
        try:
            return RetractionStatus(text)
        except ValueError as exc:
            raise BitcoinAdapterError(f"unsupported retraction: {value!r}") from exc

    status_value = status.value if isinstance(status, TxStatus) else status
    if status_value == TxStatus.REPLACED.value:
        return RetractionStatus.SUPERSEDED
    if status_value == TxStatus.ORPHANED.value:
        return RetractionStatus.RETRACTED
    if status_value in {TxStatus.MEMPOOL.value, TxStatus.CONFIRMED.value}:
        return RetractionStatus.NOT_RETRACTED
    return RetractionStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Network anchors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BitcoinNetworkAnchor:
    """Known Bitcoin network identity (bip122 genesis binding)."""

    network: str
    genesis_hash: str
    display_name: str = ""
    native_symbol: str = NATIVE_SYMBOL
    native_decimals: int = NATIVE_DECIMALS

    def __post_init__(self) -> None:
        object.__setattr__(self, "network", _text(self.network, "network"))
        genesis = _text(self.genesis_hash, "genesis_hash").lower()
        if genesis.startswith("0x"):
            genesis = genesis[2:]
        if not re.fullmatch(r"[0-9a-f]{64}", genesis):
            raise BitcoinAdapterError("genesis_hash must be 32-byte hex")
        object.__setattr__(self, "genesis_hash", genesis)
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
            raise BitcoinAdapterError("native_decimals must be between 0 and 255")

    @property
    def chain_id(self) -> str:
        """BIP122 chain id: first 32 hex characters of the genesis hash."""

        return self.genesis_hash[:32]

    def to_chain_identity(self) -> ChainIdentity:
        return ChainIdentity(
            chain_namespace=BITCOIN_NAMESPACE,
            network=self.network,
            genesis_digest=f"sha256:{self.genesis_hash}",
            chain_id=self.chain_id,
            display_name=self.display_name or self.network,
            attributes={
                "genesis_hash": self.genesis_hash,
                "namespace": BITCOIN_NAMESPACE,
                "bip122_chain_id": self.chain_id,
            },
        )


KNOWN_NETWORKS: Final[dict[str, BitcoinNetworkAnchor]] = {
    MAINNET_NETWORK: BitcoinNetworkAnchor(
        network=MAINNET_NETWORK,
        genesis_hash=MAINNET_GENESIS,
        display_name="Bitcoin Mainnet",
    ),
    TESTNET_NETWORK: BitcoinNetworkAnchor(
        network=TESTNET_NETWORK,
        genesis_hash=TESTNET_GENESIS,
        display_name="Bitcoin Testnet",
    ),
    SIGNET_NETWORK: BitcoinNetworkAnchor(
        network=SIGNET_NETWORK,
        genesis_hash=SIGNET_GENESIS,
        display_name="Bitcoin Signet",
    ),
    REGTEST_NETWORK: BitcoinNetworkAnchor(
        network=REGTEST_NETWORK,
        genesis_hash=REGTEST_GENESIS,
        display_name="Bitcoin Regtest",
    ),
    # Common aliases
    "mainnet": BitcoinNetworkAnchor(
        network=MAINNET_NETWORK,
        genesis_hash=MAINNET_GENESIS,
        display_name="Bitcoin Mainnet",
    ),
    "testnet": BitcoinNetworkAnchor(
        network=TESTNET_NETWORK,
        genesis_hash=TESTNET_GENESIS,
        display_name="Bitcoin Testnet",
    ),
    "signet": BitcoinNetworkAnchor(
        network=SIGNET_NETWORK,
        genesis_hash=SIGNET_GENESIS,
        display_name="Bitcoin Signet",
    ),
    "regtest": BitcoinNetworkAnchor(
        network=REGTEST_NETWORK,
        genesis_hash=REGTEST_GENESIS,
        display_name="Bitcoin Regtest",
    ),
}

# Index by genesis hash and bip122 chain_id for alternate resolution.
_BY_GENESIS: Final[dict[str, BitcoinNetworkAnchor]] = {
    MAINNET_GENESIS: KNOWN_NETWORKS[MAINNET_NETWORK],
    TESTNET_GENESIS: KNOWN_NETWORKS[TESTNET_NETWORK],
    SIGNET_GENESIS: KNOWN_NETWORKS[SIGNET_NETWORK],
    REGTEST_GENESIS: KNOWN_NETWORKS[REGTEST_NETWORK],
}
_BY_CHAIN_ID: Final[dict[str, BitcoinNetworkAnchor]] = {
    MAINNET_GENESIS[:32]: KNOWN_NETWORKS[MAINNET_NETWORK],
    TESTNET_GENESIS[:32]: KNOWN_NETWORKS[TESTNET_NETWORK],
    SIGNET_GENESIS[:32]: KNOWN_NETWORKS[SIGNET_NETWORK],
    REGTEST_GENESIS[:32]: KNOWN_NETWORKS[REGTEST_NETWORK],
}


def resolve_network(
    *,
    network: str | None = None,
    genesis_hash: str | None = None,
    chain_id: str | None = None,
    display_name: str = "",
) -> BitcoinNetworkAnchor:
    """Resolve a bip122 network/genesis anchor without inventing identity.

    Known networks may omit genesis when the official anchor matches.  Unknown
    networks require an explicit genesis hash.  Network is never inferred from
    a display address alone.
    """

    provided_genesis: str | None = None
    if genesis_hash is not None and genesis_hash != "":
        provided_genesis = _text(genesis_hash, "genesis_hash").lower()
        if provided_genesis.startswith("0x"):
            provided_genesis = provided_genesis[2:]
        if not re.fullmatch(r"[0-9a-f]{64}", provided_genesis):
            raise BitcoinAdapterError("genesis_hash must be 32-byte hex")

    provided_chain_id: str | None = None
    if chain_id is not None and chain_id != "":
        provided_chain_id = _text(chain_id, "chain_id").lower()
        if provided_chain_id.startswith("0x"):
            provided_chain_id = provided_chain_id[2:]

    if network is not None and network != "":
        key = _text(network, "network")
        known = KNOWN_NETWORKS.get(key)
        if known is not None:
            if provided_genesis is not None and provided_genesis != known.genesis_hash:
                raise BitcoinAdapterError(
                    f"genesis_hash does not match known network {known.network}"
                )
            if (
                provided_chain_id is not None
                and provided_chain_id != known.chain_id
                and provided_chain_id != known.genesis_hash
            ):
                raise BitcoinAdapterError(
                    f"chain_id does not match known network {known.network}"
                )
            return known
        # Unknown network label requires explicit genesis.
        if provided_genesis is None:
            # Maybe the label is actually a known genesis/chain id alias miss.
            raise BitcoinAdapterError(
                f"unknown Bitcoin network {key!r} requires an explicit genesis_hash"
            )
        return BitcoinNetworkAnchor(
            network=key,
            genesis_hash=provided_genesis,
            display_name=display_name or key,
        )

    if provided_genesis is not None:
        known = _BY_GENESIS.get(provided_genesis)
        if known is not None:
            return known
        # Unknown genesis without network name uses bip122-derived network id.
        net_name = f"bip122-{provided_genesis[:32]}"
        return BitcoinNetworkAnchor(
            network=net_name,
            genesis_hash=provided_genesis,
            display_name=display_name or net_name,
        )

    if provided_chain_id is not None:
        known = _BY_CHAIN_ID.get(provided_chain_id)
        if known is not None:
            return known
        raise BitcoinAdapterError(
            "unknown bip122 chain_id requires an explicit genesis_hash and network"
        )

    raise BitcoinAdapterError(
        "Bitcoin conversion requires network and/or genesis_hash (bip122 binding)"
    )


def native_asset(chain: ChainIdentity, network: BitcoinNetworkAnchor) -> AssetIdentity:
    return AssetIdentity(
        chain=chain,
        asset_namespace=NATIVE_ASSET_NAMESPACE,
        asset_reference=NATIVE_ASSET_REFERENCE,
        decimals=network.native_decimals,
        symbol=network.native_symbol,
        attributes={"kind": "native", "unit": "satoshi"},
    )


def display_address_account(
    address: str,
    chain: ChainIdentity,
    *,
    account_kind: str = "bitcoin_script_display",
) -> AccountIdentity:
    """Build a display-only account identity from an address string.

    Addresses are never the canonical spending identity.  Callers must still
    attach outpoint and script-commitment facts for spendability.
    """

    original = _text(address, "address")
    return AccountIdentity(
        chain=chain,
        address_normalized=original.lower() if original[:2].lower() in {"bc", "tb"} else original,
        address_original=original,
        account_kind=account_kind,
        attributes={
            "display_only": True,
            "canonical_spending_identity": False,
            "authority": "display_address_not_spend_authority",
        },
    )


# ---------------------------------------------------------------------------
# Core identity records: Outpoint, SpendingCondition, UtxoInput
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outpoint:
    """Transaction outpoint — authoritative previous-output identity.

    ``txid`` is the *display* form (RPC hex).  ``txid_internal`` is the
    byte-reversed form used on the wire / in internal hashes.  Together they
    preserve txid byte order without ambiguity.
    """

    txid: str
    vout: int
    txid_internal: str = ""

    def __post_init__(self) -> None:
        display = normalize_txid(self.txid, field="txid")
        object.__setattr__(self, "txid", display)
        # Coinbase uses vout 0xffffffff; allow the full uint32 range.
        if (
            isinstance(self.vout, bool)
            or not isinstance(self.vout, int)
            or self.vout < 0
            or self.vout > 0xFFFFFFFF
        ):
            raise BitcoinAdapterError("vout must be a uint32 integer")
        if self.txid_internal:
            internal = normalize_txid(self.txid_internal, field="txid_internal")
            expected = reverse_hex_bytes(display)
            if internal != expected and internal != display:
                # Accept either consistent internal form or an explicit override
                # only when it matches reverse(display).
                if internal != expected:
                    raise BitcoinAdapterError(
                        "txid_internal must be the byte-reverse of display txid"
                    )
            object.__setattr__(self, "txid_internal", internal if internal == expected else expected)
        else:
            object.__setattr__(self, "txid_internal", reverse_hex_bytes(display))

    @property
    def key(self) -> str:
        return f"{self.txid}:{self.vout}"

    @property
    def is_coinbase_prevout(self) -> bool:
        return self.txid == COINBASE_TXID_DISPLAY and self.vout == COINBASE_VOUT

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "txid": self.txid,
            "txid_display": self.txid,
            "txid_internal": self.txid_internal,
            "byte_order": "display_is_reversed_of_internal",
            "vout": self.vout,
            "is_coinbase_prevout": self.is_coinbase_prevout,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | "Outpoint") -> "Outpoint":
        if isinstance(value, Outpoint):
            return value
        value = _as_mapping(value, "Outpoint")
        txid = value.get("txid", value.get("txid_display", value.get("hash", "")))
        vout = value.get("vout", value.get("n", value.get("index")))
        if vout is None:
            raise BitcoinAdapterError("Outpoint.vout is required")
        return cls(
            txid=str(txid),
            vout=int(vout) if not isinstance(vout, bool) else vout,  # type: ignore[arg-type]
            txid_internal=str(value.get("txid_internal", "") or ""),
        )

    @classmethod
    def coinbase(cls) -> "Outpoint":
        return cls(txid=COINBASE_TXID_DISPLAY, vout=COINBASE_VOUT)


@dataclass(frozen=True, slots=True)
class SpendingCondition:
    """Locking-script commitment and classification for a UTXO or output.

    The ``script_commitment`` (sha256 of script bytes) is authoritative.
    ``address`` is optional display metadata and must never be treated as the
    canonical spending identity.
    """

    script_type: ScriptType
    script_hex: str = ""
    script_commitment: str = ""
    address: str = ""
    witness_version: int | None = None
    is_standard: bool = True
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.script_type, ScriptType):
            object.__setattr__(
                self, "script_type", parse_script_type(self.script_type)
            )
        script = normalize_hex_script(self.script_hex, field="script_hex")
        object.__setattr__(self, "script_hex", script)
        if self.script_commitment:
            commitment = _text(self.script_commitment, "script_commitment")
            if not commitment.startswith("sha256:"):
                # Allow bare hex digest.
                if re.fullmatch(r"[0-9a-fA-F]{64}", commitment):
                    commitment = f"sha256:{commitment.lower()}"
                else:
                    raise BitcoinAdapterError(
                        "script_commitment must be sha256:hex or bare sha256 hex"
                    )
            expected = script_commitment(script)
            if commitment != expected and script:
                raise BitcoinAdapterError(
                    "script_commitment does not match script_hex bytes"
                )
            object.__setattr__(self, "script_commitment", commitment)
        else:
            object.__setattr__(self, "script_commitment", script_commitment(script))
        object.__setattr__(
            self, "address", _text(self.address, "address", allow_empty=True)
        )
        if self.witness_version is not None:
            if (
                isinstance(self.witness_version, bool)
                or not isinstance(self.witness_version, int)
                or not 0 <= self.witness_version <= 16
            ):
                raise BitcoinAdapterError("witness_version must be 0..16")
        if type(self.is_standard) is not bool:
            raise BitcoinAdapterError("is_standard must be a boolean")
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def is_segwit(self) -> bool:
        return self.script_type in {
            ScriptType.P2WPKH,
            ScriptType.P2WSH,
            ScriptType.P2TR,
        }

    @property
    def is_taproot(self) -> bool:
        return self.script_type is ScriptType.P2TR

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "attributes": thaw_json(self.attributes),
            "canonical_spending_identity": "script_commitment",
            "display_address_authoritative": False,
            "is_segwit": self.is_segwit,
            "is_standard": self.is_standard,
            "is_taproot": self.is_taproot,
            "script_commitment": self.script_commitment,
            "script_hex": self.script_hex,
            "script_type": self.script_type.value,
            "witness_version": self.witness_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | "SpendingCondition") -> "SpendingCondition":
        if isinstance(value, SpendingCondition):
            return value
        value = _as_mapping(value, "SpendingCondition")
        # Support nested descriptor form from wallet processor.
        if "descriptor" in value and isinstance(value["descriptor"], Mapping):
            value = {**value["descriptor"], **{k: v for k, v in value.items() if k != "descriptor"}}
        script_hex = value.get(
            "script_hex",
            value.get("scriptpubkey", value.get("script_pub_key", value.get("hex", ""))),
        )
        return cls(
            script_type=parse_script_type(
                value.get("script_type", value.get("type", ScriptType.UNKNOWN))
            ),
            script_hex=str(script_hex or ""),
            script_commitment=str(value.get("script_commitment", "") or ""),
            address=str(value.get("address", "") or ""),
            witness_version=value.get("witness_version"),
            is_standard=bool(value.get("is_standard", True)),
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


@dataclass(frozen=True, slots=True)
class UtxoInput:
    """One transaction input with outpoint-centric spending context.

    When ``previous_output_known`` is False the prevout value/script are
    incomplete and must remain incomplete after conversion.
    """

    outpoint: Outpoint | None
    is_coinbase: bool = False
    sequence: int = 0xFFFFFFFF
    script_sig_hex: str = ""
    witness: tuple[str, ...] = ()
    prevout_value_sats: str | None = None
    prevout_spending_condition: SpendingCondition | None = None
    previous_output_known: bool = True
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.is_coinbase) is not bool:
            raise BitcoinAdapterError("is_coinbase must be a boolean")
        if self.is_coinbase:
            if self.outpoint is not None and not self.outpoint.is_coinbase_prevout:
                # Allow None or the conventional null outpoint for coinbase.
                if self.outpoint is not None:
                    raise BitcoinAdapterError(
                        "coinbase input must not reference a spent outpoint"
                    )
        else:
            if self.outpoint is None:
                raise BitcoinAdapterError(
                    "non-coinbase input requires an outpoint"
                )
            if not isinstance(self.outpoint, Outpoint):
                object.__setattr__(
                    self,
                    "outpoint",
                    Outpoint.from_dict(_as_mapping(self.outpoint, "outpoint")),
                )
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
            or self.sequence > 0xFFFFFFFF
        ):
            raise BitcoinAdapterError("sequence must be a uint32")
        object.__setattr__(
            self,
            "script_sig_hex",
            normalize_hex_script(self.script_sig_hex, field="script_sig_hex"),
        )
        if isinstance(self.witness, (str, bytes, bytearray)) or not isinstance(
            self.witness, Sequence
        ):
            raise BitcoinAdapterError("witness must be a sequence of hex strings")
        object.__setattr__(
            self,
            "witness",
            tuple(
                normalize_hex_script(item, field=f"witness[{i}]")
                for i, item in enumerate(self.witness)
            ),
        )
        if self.prevout_value_sats is not None:
            object.__setattr__(
                self,
                "prevout_value_sats",
                parse_sats(self.prevout_value_sats, field="prevout_value_sats"),
            )
        if self.prevout_spending_condition is not None and not isinstance(
            self.prevout_spending_condition, SpendingCondition
        ):
            object.__setattr__(
                self,
                "prevout_spending_condition",
                SpendingCondition.from_dict(
                    _as_mapping(
                        self.prevout_spending_condition, "prevout_spending_condition"
                    )
                ),
            )
        if type(self.previous_output_known) is not bool:
            raise BitcoinAdapterError("previous_output_known must be a boolean")
        # Missing value or script implies incomplete prevout.
        if (
            not self.is_coinbase
            and (
                self.prevout_value_sats is None
                or self.prevout_spending_condition is None
            )
        ):
            object.__setattr__(self, "previous_output_known", False)
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "is_coinbase": self.is_coinbase,
            "outpoint": None if self.outpoint is None else self.outpoint.to_dict(),
            "previous_output_known": self.previous_output_known,
            "prevout_spending_condition": None
            if self.prevout_spending_condition is None
            else self.prevout_spending_condition.to_dict(),
            "prevout_value_sats": self.prevout_value_sats,
            "script_sig_hex": self.script_sig_hex,
            "sequence": self.sequence,
            "witness": list(self.witness),
            "witness_item_count": len(self.witness),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | "UtxoInput") -> "UtxoInput":
        if isinstance(value, UtxoInput):
            return value
        value = _as_mapping(value, "UtxoInput")
        is_coinbase = bool(value.get("is_coinbase", False))
        prev = value.get("previous_output", value.get("outpoint", value.get("prevout")))
        outpoint: Outpoint | None
        if is_coinbase and prev is None:
            outpoint = None
        elif isinstance(prev, Mapping) and (
            "txid" in prev
            or "txid_display" in prev
            or "hash" in prev
            or "vout" in prev
        ):
            # Nested outpoint object.
            if "value" in prev or "value_sats" in prev or "scriptpubkey" in prev:
                # Esplora-style: prevout embedded with value/script at top of prev.
                outpoint = Outpoint.from_dict(
                    {
                        "txid": prev.get("txid", prev.get("hash", "")),
                        "vout": prev.get("vout", prev.get("n", 0)),
                        "txid_internal": prev.get("txid_internal", ""),
                    }
                )
            else:
                outpoint = Outpoint.from_dict(prev)
        elif prev is None and not is_coinbase:
            # Allow flattened txid/vout on the input itself.
            if "txid" in value or "prev_txid" in value:
                outpoint = Outpoint.from_dict(
                    {
                        "txid": value.get("txid", value.get("prev_txid", "")),
                        "vout": value.get("vout", value.get("prev_vout", 0)),
                        "txid_internal": value.get("txid_internal", ""),
                    }
                )
            else:
                raise BitcoinAdapterError("UtxoInput requires outpoint or is_coinbase")
        else:
            outpoint = Outpoint.from_dict(prev) if prev is not None else None

        # Prevout value / script may live on nested prevout or flat fields.
        prevout_value = value.get(
            "prevout_value_sats",
            value.get("value_sats", value.get("value")),
        )
        prev_map = prev if isinstance(prev, Mapping) else {}
        if prevout_value is None and isinstance(prev_map, Mapping):
            prevout_value = prev_map.get(
                "value_sats", prev_map.get("value", prev_map.get("amount"))
            )

        condition_raw = value.get(
            "prevout_spending_condition",
            value.get("spending_condition", value.get("descriptor")),
        )
        if condition_raw is None and isinstance(prev_map, Mapping):
            if any(
                k in prev_map
                for k in (
                    "script_hex",
                    "scriptpubkey",
                    "script_type",
                    "address",
                    "descriptor",
                )
            ):
                condition_raw = prev_map

        witness_raw = value.get("witness", value.get("txinwitness", ()))
        if witness_raw is None:
            witness_raw = ()

        known = value.get("previous_output_known")
        if known is None:
            known = prevout_value is not None and condition_raw is not None

        return cls(
            outpoint=outpoint,
            is_coinbase=is_coinbase,
            sequence=int(value.get("sequence", 0xFFFFFFFF)),
            script_sig_hex=str(
                value.get("script_sig_hex", value.get("scriptsig", value.get("scriptSig", "")))
                or ""
            ),
            witness=tuple(witness_raw) if not isinstance(witness_raw, str) else (witness_raw,),
            prevout_value_sats=None if prevout_value is None else str(prevout_value),
            prevout_spending_condition=(
                None
                if condition_raw is None
                else SpendingCondition.from_dict(_as_mapping(condition_raw, "condition"))
            ),
            previous_output_known=bool(known),
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


@dataclass(frozen=True, slots=True)
class TxOutputRecord:
    """One transaction output valued in satoshis with spending condition."""

    n: int
    value_sats: str
    spending_condition: SpendingCondition
    spent_by: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "n", _non_negative_int(self.n, "n"))
        object.__setattr__(
            self, "value_sats", parse_sats(self.value_sats, field="value_sats")
        )
        if not isinstance(self.spending_condition, SpendingCondition):
            object.__setattr__(
                self,
                "spending_condition",
                SpendingCondition.from_dict(
                    _as_mapping(self.spending_condition, "spending_condition")
                ),
            )
        object.__setattr__(
            self, "spent_by", _text(self.spent_by, "spent_by", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "is_spent": bool(self.spent_by),
            "n": self.n,
            "spending_condition": self.spending_condition.to_dict(),
            "spent_by": self.spent_by,
            "value_sats": self.value_sats,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | "TxOutputRecord") -> "TxOutputRecord":
        if isinstance(value, TxOutputRecord):
            return value
        value = _as_mapping(value, "TxOutputRecord")
        condition_raw = value.get(
            "spending_condition",
            value.get("descriptor", value.get("scriptpubkey_type")),
        )
        if isinstance(condition_raw, str):
            condition_raw = {
                "script_type": condition_raw,
                "script_hex": value.get(
                    "script_hex",
                    value.get("scriptpubkey", value.get("scriptPubKey", "")),
                ),
                "address": value.get("address", value.get("scriptpubkey_address", "")),
            }
        elif condition_raw is None:
            condition_raw = {
                "script_type": value.get("script_type", value.get("type", "unknown")),
                "script_hex": value.get(
                    "script_hex",
                    value.get("scriptpubkey", value.get("scriptPubKey", "")),
                ),
                "address": value.get("address", value.get("scriptpubkey_address", "")),
                "witness_version": value.get("witness_version"),
            }
        return cls(
            n=int(value.get("n", value.get("vout", value.get("index", 0)))),
            value_sats=str(value.get("value_sats", value.get("value", "0"))),
            spending_condition=SpendingCondition.from_dict(
                _as_mapping(condition_raw, "spending_condition")
            ),
            spent_by=str(value.get("spent_by", "") or ""),
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


@dataclass(frozen=True, slots=True)
class UtxoEntry:
    """One UTXO tracked by an offline wallet or set snapshot."""

    outpoint: Outpoint
    value_sats: str
    spending_condition: SpendingCondition
    created_by: str
    created_height: int | None = None
    spent_by: str = ""
    spent_height: int | None = None
    confirmations: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.outpoint, Outpoint):
            object.__setattr__(
                self,
                "outpoint",
                Outpoint.from_dict(_as_mapping(self.outpoint, "outpoint")),
            )
        object.__setattr__(
            self, "value_sats", parse_sats(self.value_sats, field="value_sats")
        )
        if not isinstance(self.spending_condition, SpendingCondition):
            object.__setattr__(
                self,
                "spending_condition",
                SpendingCondition.from_dict(
                    _as_mapping(self.spending_condition, "spending_condition")
                ),
            )
        object.__setattr__(self, "created_by", _text(self.created_by, "created_by"))
        object.__setattr__(
            self,
            "created_height",
            _optional_non_negative_int(self.created_height, "created_height"),
        )
        object.__setattr__(
            self, "spent_by", _text(self.spent_by, "spent_by", allow_empty=True)
        )
        object.__setattr__(
            self,
            "spent_height",
            _optional_non_negative_int(self.spent_height, "spent_height"),
        )
        object.__setattr__(
            self,
            "confirmations",
            _optional_non_negative_int(self.confirmations, "confirmations"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def is_spent(self) -> bool:
        return bool(self.spent_by)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "confirmations": self.confirmations,
            "created_by": self.created_by,
            "created_height": self.created_height,
            "is_spent": self.is_spent,
            "outpoint": self.outpoint.to_dict(),
            "spending_condition": self.spending_condition.to_dict(),
            "spent_by": self.spent_by,
            "spent_height": self.spent_height,
            "value_sats": self.value_sats,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | "UtxoEntry") -> "UtxoEntry":
        if isinstance(value, UtxoEntry):
            return value
        value = _as_mapping(value, "UtxoEntry")
        outpoint_raw = value.get("outpoint")
        if outpoint_raw is None:
            outpoint_raw = {
                "txid": value.get("txid", ""),
                "vout": value.get("vout", value.get("n", 0)),
                "txid_internal": value.get("txid_internal", ""),
            }
        condition_raw = value.get(
            "spending_condition", value.get("descriptor", value.get("script"))
        )
        if condition_raw is None:
            condition_raw = {
                "script_type": value.get("script_type", "unknown"),
                "script_hex": value.get("script_hex", ""),
                "address": value.get("address", ""),
            }
        return cls(
            outpoint=Outpoint.from_dict(_as_mapping(outpoint_raw, "outpoint")),
            value_sats=str(value.get("value_sats", value.get("value", "0"))),
            spending_condition=SpendingCondition.from_dict(
                _as_mapping(condition_raw, "spending_condition")
            ),
            created_by=str(value.get("created_by", value.get("txid", "unknown"))),
            created_height=value.get("created_height", value.get("height")),
            spent_by=str(value.get("spent_by", "") or ""),
            spent_height=value.get("spent_height"),
            confirmations=value.get("confirmations"),
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


# ---------------------------------------------------------------------------
# Structured observation / intent payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BitcoinTransactionObservation:
    """Normalized Bitcoin transaction observation prior to Crypto IR projection."""

    observation_id: str
    txid: str
    inputs: tuple[UtxoInput, ...]
    outputs: tuple[TxOutputRecord, ...]
    network: str = ""
    genesis_hash: str = ""
    chain_id: str = ""
    status: TxStatus = TxStatus.UNKNOWN
    block_height: int | None = None
    block_hash: str = ""
    confirmations: int | None = None
    fee_sats: str | None = None
    weight: int | None = None
    replaces: str = ""
    replaced_by: str = ""
    finality: str = ""
    retraction: str = ""
    reorg_depth: int | None = None
    observed_at: str = ""
    validity_start: str = ""
    validity_end: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        object.__setattr__(self, "txid", normalize_txid(self.txid, field="txid"))
        if not self.inputs:
            raise BitcoinAdapterError("transaction must have at least one input")
        if not self.outputs:
            raise BitcoinAdapterError("transaction must have at least one output")
        object.__setattr__(
            self,
            "inputs",
            tuple(
                item if isinstance(item, UtxoInput) else UtxoInput.from_dict(item)
                for item in self.inputs
            ),
        )
        object.__setattr__(
            self,
            "outputs",
            tuple(
                item
                if isinstance(item, TxOutputRecord)
                else TxOutputRecord.from_dict(item)
                for item in self.outputs
            ),
        )
        if not isinstance(self.status, TxStatus):
            object.__setattr__(self, "status", parse_tx_status(self.status))
        object.__setattr__(
            self, "network", _text(self.network, "network", allow_empty=True)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _text(self.genesis_hash, "genesis_hash", allow_empty=True),
        )
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", allow_empty=True)
        )
        object.__setattr__(
            self,
            "block_height",
            _optional_non_negative_int(self.block_height, "block_height"),
        )
        if self.block_hash:
            object.__setattr__(
                self, "block_hash", normalize_txid(self.block_hash, field="block_hash")
            )
        else:
            object.__setattr__(self, "block_hash", "")
        object.__setattr__(
            self,
            "confirmations",
            _optional_non_negative_int(self.confirmations, "confirmations"),
        )
        if self.fee_sats is not None:
            object.__setattr__(
                self, "fee_sats", parse_sats(self.fee_sats, field="fee_sats")
            )
        object.__setattr__(
            self, "weight", _optional_non_negative_int(self.weight, "weight")
        )
        object.__setattr__(
            self, "replaces", _text(self.replaces, "replaces", allow_empty=True)
        )
        if self.replaces:
            object.__setattr__(
                self, "replaces", normalize_txid(self.replaces, field="replaces")
            )
        object.__setattr__(
            self,
            "replaced_by",
            _text(self.replaced_by, "replaced_by", allow_empty=True),
        )
        if self.replaced_by:
            object.__setattr__(
                self,
                "replaced_by",
                normalize_txid(self.replaced_by, field="replaced_by"),
            )
        object.__setattr__(
            self, "finality", _text(self.finality, "finality", allow_empty=True)
        )
        object.__setattr__(
            self, "retraction", _text(self.retraction, "retraction", allow_empty=True)
        )
        object.__setattr__(
            self,
            "reorg_depth",
            _optional_non_negative_int(self.reorg_depth, "reorg_depth"),
        )
        object.__setattr__(
            self, "observed_at", _text(self.observed_at, "observed_at", allow_empty=True)
        )
        object.__setattr__(
            self,
            "validity_start",
            _text(self.validity_start, "validity_start", allow_empty=True),
        )
        object.__setattr__(
            self,
            "validity_end",
            _text(self.validity_end, "validity_end", allow_empty=True),
        )
        object.__setattr__(self, "raw", _attributes(self.raw))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def is_coinbase(self) -> bool:
        return any(item.is_coinbase for item in self.inputs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "block_hash": self.block_hash,
            "block_height": self.block_height,
            "chain_id": self.chain_id,
            "confirmations": self.confirmations,
            "fee_sats": self.fee_sats,
            "finality": self.finality,
            "genesis_hash": self.genesis_hash,
            "inputs": [item.to_dict() for item in self.inputs],
            "is_coinbase": self.is_coinbase,
            "kind": BitcoinPayloadKind.TRANSACTION_OBSERVATION.value,
            "network": self.network,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "outputs": [item.to_dict() for item in self.outputs],
            "raw": thaw_json(self.raw),
            "replaced_by": self.replaced_by,
            "replaces": self.replaces,
            "reorg_depth": self.reorg_depth,
            "retraction": self.retraction,
            "status": self.status.value,
            "txid": self.txid,
            "validity_end": self.validity_end,
            "validity_start": self.validity_start,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any] | "BitcoinTransactionObservation"
    ) -> "BitcoinTransactionObservation":
        if isinstance(value, BitcoinTransactionObservation):
            return value
        value = _as_mapping(value, "BitcoinTransactionObservation")
        txid = value.get("txid", value.get("tx_hash", value.get("hash", "")))
        inputs_raw = value.get("inputs", value.get("vin", ()))
        outputs_raw = value.get("outputs", value.get("vout", ()))
        if not isinstance(inputs_raw, Sequence) or isinstance(
            inputs_raw, (str, bytes, bytearray)
        ):
            raise BitcoinAdapterError("inputs must be a sequence")
        if not isinstance(outputs_raw, Sequence) or isinstance(
            outputs_raw, (str, bytes, bytearray)
        ):
            raise BitcoinAdapterError("outputs must be a sequence")
        return cls(
            observation_id=str(
                value.get("observation_id", value.get("id", f"btc-tx-{txid}"))
            ),
            txid=str(txid),
            inputs=tuple(inputs_raw),
            outputs=tuple(outputs_raw),
            network=str(value.get("network", "") or ""),
            genesis_hash=str(value.get("genesis_hash", "") or ""),
            chain_id=str(value.get("chain_id", "") or ""),
            status=parse_tx_status(value.get("status", TxStatus.UNKNOWN)),
            block_height=value.get("block_height", value.get("height")),
            block_hash=str(value.get("block_hash", "") or ""),
            confirmations=value.get("confirmations"),
            fee_sats=(
                None
                if value.get("fee_sats", value.get("fee")) is None
                else str(value.get("fee_sats", value.get("fee")))
            ),
            weight=value.get("weight"),
            replaces=str(value.get("replaces", "") or ""),
            replaced_by=str(value.get("replaced_by", "") or ""),
            finality=str(value.get("finality", "") or ""),
            retraction=str(value.get("retraction", "") or ""),
            reorg_depth=value.get("reorg_depth"),
            observed_at=str(value.get("observed_at", "") or ""),
            validity_start=str(value.get("validity_start", "") or ""),
            validity_end=str(value.get("validity_end", "") or ""),
            raw=value.get("raw", {})
            if isinstance(value.get("raw"), Mapping)
            else {},
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


@dataclass(frozen=True, slots=True)
class BitcoinUtxoSetObservation:
    """Snapshot of UTXO entries bound to a Bitcoin network."""

    observation_id: str
    utxos: tuple[UtxoEntry, ...]
    network: str = ""
    genesis_hash: str = ""
    chain_id: str = ""
    observed_at: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        if isinstance(self.utxos, (str, bytes, bytearray)) or not isinstance(
            self.utxos, Sequence
        ):
            raise BitcoinAdapterError("utxos must be a sequence")
        object.__setattr__(
            self,
            "utxos",
            tuple(
                item if isinstance(item, UtxoEntry) else UtxoEntry.from_dict(item)
                for item in self.utxos
            ),
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
            self, "chain_id", _text(self.chain_id, "chain_id", allow_empty=True)
        )
        object.__setattr__(
            self, "observed_at", _text(self.observed_at, "observed_at", allow_empty=True)
        )
        object.__setattr__(self, "raw", _attributes(self.raw))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "kind": BitcoinPayloadKind.UTXO_SET.value,
            "network": self.network,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "raw": thaw_json(self.raw),
            "utxos": [item.to_dict() for item in self.utxos],
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any] | "BitcoinUtxoSetObservation"
    ) -> "BitcoinUtxoSetObservation":
        if isinstance(value, BitcoinUtxoSetObservation):
            return value
        value = _as_mapping(value, "BitcoinUtxoSetObservation")
        utxos = value.get("utxos", value.get("entries", value.get("outputs", ())))
        return cls(
            observation_id=str(
                value.get("observation_id", value.get("id", "btc-utxo-set"))
            ),
            utxos=tuple(utxos) if isinstance(utxos, Sequence) else (),
            network=str(value.get("network", "") or ""),
            genesis_hash=str(value.get("genesis_hash", "") or ""),
            chain_id=str(value.get("chain_id", "") or ""),
            observed_at=str(value.get("observed_at", "") or ""),
            raw=value.get("raw", {})
            if isinstance(value.get("raw"), Mapping)
            else {},
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


@dataclass(frozen=True, slots=True)
class BitcoinSpendIntent:
    """Unsigned spend declaration (not authorization)."""

    intent_id: str
    inputs: tuple[UtxoInput, ...]
    outputs: tuple[TxOutputRecord, ...]
    network: str = ""
    genesis_hash: str = ""
    chain_id: str = ""
    fee_sats: str | None = None
    change_address: str = ""
    origin_address: str = ""
    memo: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, "intent_id"))
        if not self.inputs:
            raise BitcoinAdapterError("spend intent requires at least one input")
        if not self.outputs:
            raise BitcoinAdapterError("spend intent requires at least one output")
        object.__setattr__(
            self,
            "inputs",
            tuple(
                item if isinstance(item, UtxoInput) else UtxoInput.from_dict(item)
                for item in self.inputs
            ),
        )
        object.__setattr__(
            self,
            "outputs",
            tuple(
                item
                if isinstance(item, TxOutputRecord)
                else TxOutputRecord.from_dict(item)
                for item in self.outputs
            ),
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
            self, "chain_id", _text(self.chain_id, "chain_id", allow_empty=True)
        )
        if self.fee_sats is not None:
            object.__setattr__(
                self, "fee_sats", parse_sats(self.fee_sats, field="fee_sats")
            )
        object.__setattr__(
            self,
            "change_address",
            _text(self.change_address, "change_address", allow_empty=True),
        )
        object.__setattr__(
            self,
            "origin_address",
            _text(self.origin_address, "origin_address", allow_empty=True),
        )
        object.__setattr__(self, "memo", _text(self.memo, "memo", allow_empty=True))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "change_address": self.change_address,
            "fee_sats": self.fee_sats,
            "genesis_hash": self.genesis_hash,
            "inputs": [item.to_dict() for item in self.inputs],
            "intent_id": self.intent_id,
            "kind": BitcoinPayloadKind.SPEND_INTENT.value,
            "memo": self.memo,
            "network": self.network,
            "origin_address": self.origin_address,
            "outputs": [item.to_dict() for item in self.outputs],
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any] | "BitcoinSpendIntent"
    ) -> "BitcoinSpendIntent":
        if isinstance(value, BitcoinSpendIntent):
            return value
        value = _as_mapping(value, "BitcoinSpendIntent")
        return cls(
            intent_id=str(value.get("intent_id", value.get("id", "btc-intent"))),
            inputs=tuple(value.get("inputs", ())),
            outputs=tuple(value.get("outputs", ())),
            network=str(value.get("network", "") or ""),
            genesis_hash=str(value.get("genesis_hash", "") or ""),
            chain_id=str(value.get("chain_id", "") or ""),
            fee_sats=(
                None
                if value.get("fee_sats", value.get("fee")) is None
                else str(value.get("fee_sats", value.get("fee")))
            ),
            change_address=str(value.get("change_address", "") or ""),
            origin_address=str(value.get("origin_address", "") or ""),
            memo=str(value.get("memo", "") or ""),
            attributes=value.get("attributes", {})
            if isinstance(value.get("attributes"), Mapping)
            else {},
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def default_bitcoin_capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=BITCOIN_CAPABILITY_ID,
        kind=CapabilityKind.CHAIN_ADAPTER,
        implementation_version=BITCOIN_ADAPTER_IMPLEMENTATION_VERSION,
        semantic_version=BITCOIN_ADAPTER_SEMANTIC_VERSION,
        status=CapabilityStatus.AVAILABLE,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=(BITCOIN_NAMESPACE,),
        features=(
            "wallet_records",
            "transaction_observation",
            "utxo_set",
            "outpoints",
            "script_commitments",
            "witness_context",
            "confirmations",
            "replacement",
            "coinbase",
            "reorg_state",
            "spend_intent",
            "no_script_execution",
        ),
        summary=(
            "Bitcoin UTXO wallet observation and spend-intent conversion into "
            "Crypto IR (outpoint and script-commitment authoritative)"
        ),
        attributes={
            "known_networks": sorted(
                {
                    MAINNET_NETWORK,
                    TESTNET_NETWORK,
                    SIGNET_NETWORK,
                    REGTEST_NETWORK,
                }
            ),
            "preserves_raw_evidence": True,
            "invents_missing_facts": False,
            "script_execution": False,
            "canonical_spending_identity": ["outpoint", "script_commitment"],
            "display_address_authoritative": False,
        },
    )


class BitcoinWalletAdapter:
    """Side-effect-free Bitcoin wallet → Crypto IR adapter.

    Implements :class:`~ipfs_datasets_py.logic.crypto_ir.adapters.CryptoIRAdapter`.
    """

    def __init__(
        self,
        *,
        adapter_id: str = BITCOIN_ADAPTER_ID,
        capability: CapabilityDescriptor | None = None,
    ) -> None:
        self._adapter_id = _text(adapter_id, "adapter_id")
        if capability is None:
            capability = default_bitcoin_capability()
        if not isinstance(capability, CapabilityDescriptor):
            raise BitcoinAdapterError("capability must be a CapabilityDescriptor")
        if not capability.side_effect_free:
            raise BitcoinAdapterError(
                "Bitcoin adapter capability must be side-effect-free"
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
        payload: (
            Mapping[str, Any]
            | BitcoinTransactionObservation
            | BitcoinUtxoSetObservation
            | BitcoinSpendIntent
        ),
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        """Convert *payload* without elevating authority or inventing facts."""

        if isinstance(payload, BitcoinTransactionObservation):
            payload_map: Mapping[str, Any] = payload.to_dict()
        elif isinstance(payload, BitcoinUtxoSetObservation):
            payload_map = payload.to_dict()
        elif isinstance(payload, BitcoinSpendIntent):
            payload_map = payload.to_dict()
        elif isinstance(payload, Mapping):
            payload_map = payload
        else:
            raise BitcoinAdapterError(
                "payload must be a mapping or Bitcoin structured record"
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
                    BitcoinPayloadKind.TRANSACTION_OBSERVATION,
                    BitcoinPayloadKind.UTXO_SET,
                }
                else AuthorityKind.DECLARATION
            )
            provenance_dict, source_authority = self._resolve_provenance(
                source_provenance, default=default_authority
            )
            if source_authority is AuthorityKind.AUTHORIZATION:
                raise BitcoinAdapterError(
                    "cannot convert authorization-authority payload through "
                    "Bitcoin adapter"
                )
            result_authority = source_authority

            if kind is BitcoinPayloadKind.TRANSACTION_OBSERVATION:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_observation(payload_map)
                )
            elif kind is BitcoinPayloadKind.UTXO_SET:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_utxo_set(payload_map)
                )
            elif kind is BitcoinPayloadKind.SPEND_INTENT:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_spend_intent(payload_map)
                )
            elif kind is BitcoinPayloadKind.SERIALIZED_CANDIDATE:
                result_payload, unsupported, diagnostics, status = (
                    self._convert_serialized_candidate(payload_map)
                )
            else:
                raise BitcoinAdapterError(f"unsupported Bitcoin payload kind: {kind!r}")
        except BitcoinAdapterError as exc:
            return AdapterConversionResult(
                conversion_id=f"bitcoin-error:{self._adapter_id}",
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
                attributes={"error": True, "chain_namespace": BITCOIN_NAMESPACE},
            )

        result_digest = f"sha256:{content_sha256_hex(result_payload)}"
        conversion_id = f"bitcoin:{kind.value}:{result_digest[:18]}"
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
                "chain_namespace": BITCOIN_NAMESPACE,
                "payload_kind": kind.value,
                "preserves_raw_evidence": True,
                "canonical_spending_identity": ["outpoint", "script_commitment"],
                "display_address_authoritative": False,
                "script_execution": False,
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
                    raise BitcoinAdapterError(
                        f"unsupported source authority: {authority['kind']!r}"
                    ) from exc
            else:
                kind = default
            return data, kind
        raise BitcoinAdapterError(
            "source_provenance must be CryptoIRProvenance or mapping"
        )

    def _detect_kind(self, payload: Mapping[str, Any]) -> BitcoinPayloadKind:
        kind_raw = payload.get("kind", payload.get("payload_kind", ""))
        if kind_raw:
            text = _text(str(kind_raw), "kind").lower().replace("-", "_")
            aliases = {
                "transaction_observation": BitcoinPayloadKind.TRANSACTION_OBSERVATION,
                "observation": BitcoinPayloadKind.TRANSACTION_OBSERVATION,
                "bitcoin_transaction_observation": (
                    BitcoinPayloadKind.TRANSACTION_OBSERVATION
                ),
                "tx": BitcoinPayloadKind.TRANSACTION_OBSERVATION,
                "utxo_set": BitcoinPayloadKind.UTXO_SET,
                "utxo": BitcoinPayloadKind.UTXO_SET,
                "utxos": BitcoinPayloadKind.UTXO_SET,
                "spend_intent": BitcoinPayloadKind.SPEND_INTENT,
                "unsigned_spend": BitcoinPayloadKind.SPEND_INTENT,
                "bitcoin_spend_intent": BitcoinPayloadKind.SPEND_INTENT,
                "serialized_candidate": BitcoinPayloadKind.SERIALIZED_CANDIDATE,
                "candidate": BitcoinPayloadKind.SERIALIZED_CANDIDATE,
                "raw_tx": BitcoinPayloadKind.SERIALIZED_CANDIDATE,
            }
            if text in aliases:
                return aliases[text]
            raise BitcoinAdapterError(f"unsupported Bitcoin payload kind: {kind_raw!r}")

        if "utxos" in payload or "entries" in payload:
            return BitcoinPayloadKind.UTXO_SET
        if "intent_id" in payload and ("inputs" in payload or "outputs" in payload):
            return BitcoinPayloadKind.SPEND_INTENT
        if "payload_digest" in payload or "candidate_id" in payload:
            return BitcoinPayloadKind.SERIALIZED_CANDIDATE
        if "txid" in payload or "tx_hash" in payload or "vin" in payload:
            return BitcoinPayloadKind.TRANSACTION_OBSERVATION
        raise BitcoinAdapterError("unable to detect Bitcoin payload kind")

    def _resolve_anchor(self, payload: Mapping[str, Any]) -> BitcoinNetworkAnchor:
        return resolve_network(
            network=payload.get("network") or None,
            genesis_hash=payload.get("genesis_hash") or None,
            chain_id=payload.get("chain_id") or None,
        )

    def _convert_observation(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        obs = BitcoinTransactionObservation.from_dict(payload)
        network = self._resolve_anchor(obs.to_dict())
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []

        txid_order = txid_byte_order_record(obs.txid)
        finality = map_finality(
            obs.finality or None,
            confirmations=obs.confirmations,
            status=obs.status,
        )
        if (
            not obs.finality
            and obs.confirmations is None
            and obs.status == TxStatus.UNKNOWN
        ):
            missing_coverage.append("finality")
            unsupported.append(
                UnsupportedField(
                    path="finality",
                    reason="finality/confirmations/status absent; left unknown",
                )
            )
        retraction = map_retraction(obs.retraction or None, status=obs.status)
        if not obs.retraction and obs.status == TxStatus.UNKNOWN:
            missing_coverage.append("retraction")

        if obs.confirmations is None and obs.status != TxStatus.MEMPOOL:
            missing_coverage.append("confirmations")

        # Inputs: preserve outpoints, witness, coinbase, incomplete prevouts.
        input_records: list[dict[str, Any]] = []
        incomplete_prevouts = 0
        for index, vin in enumerate(obs.inputs):
            record = vin.to_dict()
            record["input_index"] = index
            if not vin.is_coinbase and not vin.previous_output_known:
                incomplete_prevouts += 1
                missing_coverage.append(f"inputs[{index}].previous_output")
                unsupported.append(
                    UnsupportedField(
                        path=f"inputs[{index}].previous_output",
                        reason=(
                            "previous output value/script unknown; "
                            "left incomplete (not invented)"
                        ),
                    )
                )
            # Never promote display address to spending authority.
            if (
                vin.prevout_spending_condition is not None
                and vin.prevout_spending_condition.address
            ):
                record["display_address_not_spend_authority"] = True
            input_records.append(record)

        output_records: list[dict[str, Any]] = []
        for index, vout in enumerate(obs.outputs):
            record = vout.to_dict()
            record["output_index"] = index
            record["outpoint"] = Outpoint(txid=obs.txid, vout=vout.n).to_dict()
            # Address is display-only metadata on the spending condition.
            if vout.spending_condition.address:
                record["display_address_not_spend_authority"] = True
            if not vout.spending_condition.script_hex:
                missing_coverage.append(f"outputs[{index}].script_hex")
                unsupported.append(
                    UnsupportedField(
                        path=f"outputs[{index}].script_hex",
                        reason="script bytes absent; commitment is of empty script",
                    )
                )
            output_records.append(record)

        fee_amount: dict[str, Any] | None = None
        if obs.fee_sats is None:
            if not obs.is_coinbase:
                missing_coverage.append("fee_sats")
                unsupported.append(
                    UnsupportedField(
                        path="fee_sats",
                        reason="fee absent; not invented from incomplete prevouts",
                    )
                )
        else:
            fee_amount = ExactAmount(
                base_units=obs.fee_sats, decimals=network.native_decimals
            ).to_dict()

        # Replacement / reorg surface.
        replacement = {
            "replaces": obs.replaces or None,
            "replaced_by": obs.replaced_by or None,
            "status": obs.status.value,
        }
        reorg_state = {
            "reorg_depth": obs.reorg_depth,
            "finality": finality.value,
            "retraction": retraction.value,
            "status": obs.status.value,
            "is_orphaned": obs.status == TxStatus.ORPHANED
            or finality == FinalityStatus.REORGED,
        }

        coordinate = LedgerCoordinate(
            sequence=obs.block_height,
            hash=obs.block_hash,
            transaction_index=None,
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
            reorg_depth=obs.reorg_depth,
        )

        # Account identities are display-only when derived from addresses;
        # outpoints remain the spend identity on attributes.
        from_account = None
        to_account = None
        first_out_addr = next(
            (o.spending_condition.address for o in obs.outputs if o.spending_condition.address),
            "",
        )
        if first_out_addr:
            to_account = display_address_account(first_out_addr, chain)

        asset = native_asset(chain, network)
        transfers: list[dict[str, Any]] = []
        for vout in obs.outputs:
            amount = ExactAmount(
                base_units=vout.value_sats, decimals=network.native_decimals
            )
            transfers.append(
                {
                    "kind": "native",
                    "asset": asset.to_dict(),
                    "amount": amount.to_dict(),
                    "outpoint": Outpoint(txid=obs.txid, vout=vout.n).to_dict(),
                    "spending_condition": vout.spending_condition.to_dict(),
                    "display_address": vout.spending_condition.address or None,
                    "display_address_authoritative": False,
                }
            )

        observed = ObservedTransaction(
            observation_id=obs.observation_id,
            chain=chain,
            tx_digest=f"sha256:{txid_order['txid_internal']}",
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
                "txid": txid_order["txid_display"],
                "txid_display": txid_order["txid_display"],
                "txid_internal": txid_order["txid_internal"],
                "txid_byte_order": txid_order["byte_order"],
                "is_coinbase": obs.is_coinbase,
                "confirmations": obs.confirmations,
                "fee_sats": obs.fee_sats,
                "weight": obs.weight,
                "status": obs.status.value,
                "replacement": replacement,
                "reorg_state": reorg_state,
                "input_count": len(obs.inputs),
                "output_count": len(obs.outputs),
                "incomplete_prevout_count": incomplete_prevouts,
                "missing_coverage": list(missing_coverage),
                "canonical_spending_identity": ["outpoint", "script_commitment"],
                "display_address_authoritative": False,
                "script_execution": False,
                "raw": thaw_json(obs.raw),
                "source_attributes": thaw_json(obs.attributes),
                "network_anchor": {
                    "network": network.network,
                    "genesis_hash": network.genesis_hash,
                    "chain_id": network.chain_id,
                    "namespace": BITCOIN_NAMESPACE,
                },
            },
        )

        completeness_status = (
            CompletenessStatus.COMPLETE
            if not missing_coverage
            else CompletenessStatus.PARTIAL
            if len(missing_coverage) < 8
            else CompletenessStatus.UNKNOWN
        )
        completeness = CompletenessReceipt(
            receipt_id=f"cmp-{obs.observation_id}",
            chain=chain,
            scope=f"bitcoin-tx:{obs.txid}",
            completeness=completeness_status,
            finality=finality,
            validity=ValidityWindow(
                start=obs.validity_start, end=obs.validity_end
            ),
            retraction=retraction,
            covered_ranges=(coordinate,) if obs.block_height is not None else (),
            missing_ranges=(),
            provider_ids=(self._adapter_id,),
            attributes={
                "missing_coverage": list(missing_coverage),
                "incomplete_prevout_count": incomplete_prevouts,
            },
        )

        result_payload = {
            "record_type": "bitcoin_transaction_observation",
            "authority": AuthorityKind.OBSERVATION.value,
            "chain": chain.to_dict(),
            "observed_transaction": observed.to_dict(),
            "txid": txid_order,
            "inputs": input_records,
            "outputs": output_records,
            "transfers": transfers,
            "fee": fee_amount,
            "native_asset": asset.to_dict(),
            "confirmations": obs.confirmations,
            "replacement": replacement,
            "reorg_state": reorg_state,
            "is_coinbase": obs.is_coinbase,
            "completeness": completeness.to_dict(),
            "missing_coverage": list(missing_coverage),
            "raw": thaw_json(obs.raw) if obs.raw else thaw_json(obs.attributes),
            "canonical_spending_identity": ["outpoint", "script_commitment"],
            "display_address_authoritative": False,
            "script_execution": False,
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
            f"network={network.network};genesis={network.genesis_hash};"
            f"txid_display={txid_order['txid_display']};"
            f"incomplete_prevouts={incomplete_prevouts}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _convert_utxo_set(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        obs = BitcoinUtxoSetObservation.from_dict(payload)
        network = self._resolve_anchor(obs.to_dict())
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []

        asset = native_asset(chain, network)
        entries: list[dict[str, Any]] = []
        for index, utxo in enumerate(obs.utxos):
            entry = utxo.to_dict()
            entry["asset"] = asset.to_dict()
            entry["amount"] = ExactAmount(
                base_units=utxo.value_sats, decimals=network.native_decimals
            ).to_dict()
            # Identity vector: outpoint key + script commitment.
            entry["identity"] = {
                "outpoint_key": utxo.outpoint.key,
                "script_commitment": utxo.spending_condition.script_commitment,
                "canonical": ["outpoint", "script_commitment"],
                "display_address": utxo.spending_condition.address or None,
                "display_address_authoritative": False,
            }
            if not utxo.spending_condition.script_hex:
                missing_coverage.append(f"utxos[{index}].script_hex")
                unsupported.append(
                    UnsupportedField(
                        path=f"utxos[{index}].script_hex",
                        reason="script bytes absent on UTXO; commitment of empty script",
                    )
                )
            if utxo.spending_condition.address:
                entry["display_address_not_spend_authority"] = True
            entries.append(entry)

        if not obs.utxos:
            missing_coverage.append("utxos")
            diagnostics.append("empty UTXO set")

        result_payload = {
            "record_type": "bitcoin_utxo_set",
            "authority": AuthorityKind.OBSERVATION.value,
            "chain": chain.to_dict(),
            "observation_id": obs.observation_id,
            "utxos": entries,
            "utxo_count": len(entries),
            "native_asset": asset.to_dict(),
            "missing_coverage": list(missing_coverage),
            "raw": thaw_json(obs.raw),
            "canonical_spending_identity": ["outpoint", "script_commitment"],
            "display_address_authoritative": False,
            "script_execution": False,
            "network_anchor": {
                "network": network.network,
                "genesis_hash": network.genesis_hash,
                "chain_id": network.chain_id,
            },
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"network={network.network};utxo_count={len(entries)};"
            f"genesis={network.genesis_hash}"
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _convert_spend_intent(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        intent = BitcoinSpendIntent.from_dict(payload)
        network = self._resolve_anchor(intent.to_dict())
        chain = network.to_chain_identity()
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = []
        missing_coverage: list[str] = []
        asset = native_asset(chain, network)

        input_records = []
        for index, vin in enumerate(intent.inputs):
            if vin.is_coinbase:
                raise BitcoinAdapterError("spend intent cannot spend a coinbase input marker")
            if not vin.previous_output_known:
                missing_coverage.append(f"inputs[{index}].previous_output")
                unsupported.append(
                    UnsupportedField(
                        path=f"inputs[{index}].previous_output",
                        reason="prevout incomplete; spend intent remains partial",
                    )
                )
            record = vin.to_dict()
            record["input_index"] = index
            input_records.append(record)

        output_records = []
        transfers: list[TransferIntent] = []
        for index, vout in enumerate(intent.outputs):
            record = vout.to_dict()
            record["output_index"] = index
            output_records.append(record)
            to_account = None
            if vout.spending_condition.address:
                to_account = display_address_account(
                    vout.spending_condition.address, chain
                )
            # TransferIntent requires from/to accounts — use outpoint-bound
            # synthetic account when address absent so declarations stay valid.
            if to_account is None:
                to_account = AccountIdentity(
                    chain=chain,
                    address_normalized=f"script:{vout.spending_condition.script_commitment[7:23]}",
                    address_original=f"script:{vout.spending_condition.script_commitment}",
                    account_kind="script_commitment",
                    attributes={
                        "script_commitment": vout.spending_condition.script_commitment,
                        "display_only": False,
                        "canonical_spending_identity": True,
                    },
                )
            origin_account = None
            if intent.origin_address:
                origin_account = display_address_account(intent.origin_address, chain)
            elif intent.inputs and intent.inputs[0].outpoint is not None:
                op = intent.inputs[0].outpoint
                origin_account = AccountIdentity(
                    chain=chain,
                    address_normalized=f"outpoint:{op.key}",
                    address_original=f"outpoint:{op.key}",
                    account_kind="outpoint",
                    attributes={
                        "outpoint": op.to_dict(),
                        "canonical_spending_identity": True,
                    },
                )
            else:
                origin_account = AccountIdentity(
                    chain=chain,
                    address_normalized="unknown-origin",
                    address_original="unknown-origin",
                    account_kind="unknown",
                    attributes={"canonical_spending_identity": False},
                )
            transfers.append(
                TransferIntent(
                    asset=asset,
                    amount=ExactAmount(
                        base_units=vout.value_sats, decimals=network.native_decimals
                    ),
                    from_account=origin_account,
                    to_account=to_account,
                    attributes={
                        "output_index": index,
                        "spending_condition": vout.spending_condition.to_dict(),
                        "display_address_authoritative": False,
                    },
                )
            )

        origin = (
            display_address_account(intent.origin_address, chain)
            if intent.origin_address
            else transfers[0].from_account
        )
        signers = (
            SignerRequirement(account=origin, role="spender"),
        )
        unsigned = UnsignedTransactionIntent(
            intent_id=intent.intent_id,
            chain=chain,
            origin=origin,
            signers=signers,
            transfers=tuple(transfers),
            memo=intent.memo,
            attributes={
                "fee_sats": intent.fee_sats,
                "change_address": intent.change_address or None,
                "input_outpoints": [
                    None if vin.outpoint is None else vin.outpoint.to_dict()
                    for vin in intent.inputs
                ],
                "canonical_spending_identity": ["outpoint", "script_commitment"],
                "display_address_authoritative": False,
                "script_execution": False,
            },
        )

        result_payload = {
            "record_type": "bitcoin_spend_intent",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "unsigned_transaction_intent": unsigned.to_dict(),
            "inputs": input_records,
            "outputs": output_records,
            "fee_sats": intent.fee_sats,
            "native_asset": asset.to_dict(),
            "missing_coverage": list(missing_coverage),
            "canonical_spending_identity": ["outpoint", "script_commitment"],
            "display_address_authoritative": False,
            "script_execution": False,
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        diagnostics.append(
            f"network={network.network};inputs={len(input_records)};"
            f"outputs={len(output_records)}"
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
        """Preserve a serialized raw transaction candidate without parsing Script."""

        network = self._resolve_anchor(payload)
        chain = network.to_chain_identity()
        candidate_id = _identifier(
            str(payload.get("candidate_id", payload.get("id", "btc-candidate"))),
            "candidate_id",
        )
        raw_hex = normalize_hex_script(
            payload.get("raw_hex", payload.get("hex", payload.get("payload", ""))),
            field="raw_hex",
        )
        if not raw_hex:
            raise BitcoinAdapterError("serialized candidate requires raw_hex")
        encoding = _text(str(payload.get("encoding", "bitcoin-tx-hex")), "encoding")
        payload_digest = f"sha256:{hashlib.sha256(bytes.fromhex(raw_hex)).hexdigest()}"
        if payload.get("payload_digest"):
            provided = _text(str(payload["payload_digest"]), "payload_digest")
            if not provided.startswith("sha256:"):
                if re.fullmatch(r"[0-9a-fA-F]{64}", provided):
                    provided = f"sha256:{provided.lower()}"
            if provided != payload_digest:
                raise BitcoinAdapterError(
                    "payload_digest does not match raw_hex bytes"
                )

        intent_id = _identifier(
            str(payload.get("intent_id", f"intent-{candidate_id}")),
            "intent_id",
        )
        byte_length = len(raw_hex) // 2
        candidate = SerializedTransactionCandidate(
            candidate_id=candidate_id,
            intent_id=intent_id,
            chain=chain,
            payload_digest=payload_digest,
            encoding=encoding,
            byte_length=byte_length,
            attributes={
                "raw_hex_length": byte_length,
                "script_execution": False,
                "parsed": False,
            },
        )
        result_payload = {
            "record_type": "bitcoin_serialized_candidate",
            "authority": AuthorityKind.DECLARATION.value,
            "chain": chain.to_dict(),
            "serialized_transaction_candidate": candidate.to_dict(),
            "raw_hex": raw_hex,
            "payload_digest": payload_digest,
            "encoding": encoding,
            "script_execution": False,
            "diagnostics": [
                "raw transaction preserved without Script execution or parsing"
            ],
        }
        return (
            result_payload,
            (),
            ("serialized candidate preserved without script execution",),
            AdapterConversionStatus.SUCCEEDED,
        )


def convert_bitcoin_payload(
    payload: Mapping[str, Any]
    | BitcoinTransactionObservation
    | BitcoinUtxoSetObservation
    | BitcoinSpendIntent,
    *,
    source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    adapter: BitcoinWalletAdapter | None = None,
) -> AdapterConversionResult:
    """Module-level helper for offline Bitcoin → Crypto IR conversion."""

    active = adapter if adapter is not None else BitcoinWalletAdapter()
    return active.convert(payload, source_provenance=source_provenance)


__all__ = [
    "BITCOIN_ADAPTER_ID",
    "BITCOIN_CAPABILITY_ID",
    "BITCOIN_NAMESPACE",
    "COINBASE_TXID_DISPLAY",
    "COINBASE_VOUT",
    "MAINNET_GENESIS",
    "MAINNET_NETWORK",
    "MAX_MONEY_SATS",
    "NATIVE_DECIMALS",
    "REGTEST_GENESIS",
    "REGTEST_NETWORK",
    "SIGNET_GENESIS",
    "SIGNET_NETWORK",
    "TESTNET_GENESIS",
    "TESTNET_NETWORK",
    "BitcoinAdapterError",
    "BitcoinNetworkAnchor",
    "BitcoinPayloadKind",
    "BitcoinSpendIntent",
    "BitcoinTransactionObservation",
    "BitcoinUtxoSetObservation",
    "BitcoinWalletAdapter",
    "Outpoint",
    "ScriptType",
    "SpendingCondition",
    "TxOutputRecord",
    "TxStatus",
    "UtxoEntry",
    "UtxoInput",
    "content_sha256_hex",
    "convert_bitcoin_payload",
    "default_bitcoin_capability",
    "display_address_account",
    "map_finality",
    "map_retraction",
    "native_asset",
    "normalize_hex_script",
    "normalize_txid",
    "parse_sats",
    "parse_script_type",
    "resolve_network",
    "reverse_hex_bytes",
    "script_commitment",
    "txid_byte_order_record",
]
