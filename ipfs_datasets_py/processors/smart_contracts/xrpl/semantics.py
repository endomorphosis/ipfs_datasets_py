"""XRPL native-ledger object and transition semantics (CRYPTOIR-G240).

Models XRPL as account/ledger *state machines* — trust lines, escrows, checks,
payment channels, offers, AMMs, NFTs, signer lists, account flags, reserves,
sequence/ticket, partial payment, issuer freeze/clawback, destination tags,
and validated-ledger epochs — **not** as Ethereum-style contracts or EVM call
traces.

Hooks are capability-gated: absence yields ``UNSUPPORTED``.  Ripple EVM
sidechain identity is never silently treated as XRPL mainnet.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError
from ..models import ensure_secret_safe


SEMANTICS_SCHEMA_VERSION = "smart-contract-xrpl-semantics-v1"

# CAIP-2 style: xrpl:0 mainnet, xrpl:1 testnet, xrpl:2 devnet
XRPL_MAINNET_CHAIN_ID: Final[str] = "0"
XRPL_MAINNET_NETWORK: Final[str] = "xrpl-mainnet"
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

# Ripple EVM sidechain is a distinct EVM lane (never XRPL mainnet).
# Public mainnet chain id for the XRPL EVM sidechain (eip155).
RIPPLE_EVM_SIDECHAIN_CHAIN_ID: Final[str] = "1440002"
RIPPLE_EVM_SIDECHAIN_NETWORK: Final[str] = "ripple-evm-sidechain"
RIPPLE_EVM_SIDECHAIN_NAMESPACE: Final[str] = "eip155"

NATIVE_ASSET_SYMBOL: Final[str] = "XRP"
DROPS_PER_XRP: Final[int] = 1_000_000
NATIVE_DECIMALS: Final[int] = 6

# Transaction flags (subset relevant to ledger semantics)
TF_PARTIAL_PAYMENT: Final[int] = 0x00020000
TF_NO_DIRECT_RIPPLE: Final[int] = 0x00010000
TF_LIMIT_QUALITY: Final[int] = 0x00040000
TF_SET_NO_RIPPLE: Final[int] = 0x00020000  # TrustSet
TF_CLEAR_NO_RIPPLE: Final[int] = 0x00040000
TF_SET_FREEZE: Final[int] = 0x00100000
TF_CLEAR_FREEZE: Final[int] = 0x00200000
TF_SETF_AUTH: Final[int] = 0x00010000

# AccountRoot flags (asf*) — subset used for issuer/policy modeling
ASF_REQUIRE_DEST: Final[int] = 1
ASF_REQUIRE_AUTH: Final[int] = 2
ASF_DISALLOW_XRP: Final[int] = 3
ASF_DISABLE_MASTER: Final[int] = 4
ASF_ACCOUNT_TXN_ID: Final[int] = 5
ASF_NO_FREEZE: Final[int] = 6
ASF_GLOBAL_FREEZE: Final[int] = 7
ASF_DEFAULT_RIPPLE: Final[int] = 8
ASF_DEPOSIT_AUTH: Final[int] = 9
ASF_AUTHORIZED_NFTOKEN_MINTER: Final[int] = 10
ASF_DISABLE_INCOMING_CHECK: Final[int] = 13
ASF_DISABLE_INCOMING_NFTOKEN_OFFER: Final[int] = 12
ASF_DISABLE_INCOMING_PAYCHAN: Final[int] = 14
ASF_DISABLE_INCOMING_TRUSTLINE: Final[int] = 15
ASF_ALLOW_TRUSTLINE_CLAWBACK: Final[int] = 16

# Classic address: starts with 'r', length typically 25–35 base58 chars
_CLASSIC_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(
    r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$"
)
_X_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(
    r"^[XT][1-9A-HJ-NP-Za-km-z]{45,55}$"
)
_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0x)?[0-9A-Fa-f]{64}$")
_CURRENCY_STANDARD: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9?!@#$%^&*<>(){}[\]|]{3}$"
)
_CURRENCY_HEX: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Fa-f]{40}$")
_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^-?(0|[1-9][0-9]*)$")
_DECIMAL_AMOUNT: Final[re.Pattern[str]] = re.compile(
    r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"
)

_KNOWN_XRPL: Final[dict[str, dict[str, str]]] = {
    XRPL_MAINNET_CHAIN_ID: {
        "network": XRPL_MAINNET_NETWORK,
        "genesis_hash": XRPL_MAINNET_GENESIS_HASH,
        "display_name": "XRPL Mainnet",
    },
    XRPL_TESTNET_CHAIN_ID: {
        "network": XRPL_TESTNET_NETWORK,
        "genesis_hash": XRPL_TESTNET_GENESIS_HASH,
        "display_name": "XRPL Testnet",
    },
    XRPL_DEVNET_CHAIN_ID: {
        "network": XRPL_DEVNET_NETWORK,
        "genesis_hash": XRPL_DEVNET_GENESIS_HASH,
        "display_name": "XRPL Devnet",
    },
}

_NETWORK_ALIASES: Final[dict[str, str]] = {
    "0": XRPL_MAINNET_CHAIN_ID,
    "mainnet": XRPL_MAINNET_CHAIN_ID,
    "xrpl": XRPL_MAINNET_CHAIN_ID,
    "xrpl-mainnet": XRPL_MAINNET_CHAIN_ID,
    "1": XRPL_TESTNET_CHAIN_ID,
    "testnet": XRPL_TESTNET_CHAIN_ID,
    "xrpl-testnet": XRPL_TESTNET_CHAIN_ID,
    "2": XRPL_DEVNET_CHAIN_ID,
    "devnet": XRPL_DEVNET_CHAIN_ID,
    "xrpl-devnet": XRPL_DEVNET_CHAIN_ID,
}

# Sidechain aliases that must never resolve to XRPL mainnet.
_EVM_SIDECHAIN_ALIASES: Final[frozenset[str]] = frozenset(
    {
        RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
        "ripple-evm",
        "ripple-evm-sidechain",
        "xrpl-evm",
        "xrpl-evm-sidechain",
        "evm-sidechain",
    }
)


class SemanticPassStatus(StrEnum):
    """Outcome of an XRPL semantic coverage claim."""

    PASS = "pass"
    FAIL_CLOSED = "fail_closed"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class LedgerObjectKind(StrEnum):
    """Native XRPL ledger object types (not EVM storage slots)."""

    ACCOUNT_ROOT = "AccountRoot"
    TRUST_LINE = "RippleState"
    OFFER = "Offer"
    ESCROW = "Escrow"
    PAYMENT_CHANNEL = "PayChannel"
    CHECK = "Check"
    SIGNER_LIST = "SignerList"
    TICKET = "Ticket"
    DEPOSIT_PREAUTH = "DepositPreauth"
    NFTOKEN_PAGE = "NFTokenPage"
    NFTOKEN_OFFER = "NFTokenOffer"
    AMM = "AMM"
    DIR_NODE = "DirectoryNode"
    LEDGER_HASHES = "LedgerHashes"
    AMENDMENTS = "Amendments"
    FEE_SETTINGS = "FeeSettings"
    HOOK = "Hook"
    HOOK_STATE = "HookState"
    HOOK_DEFINITION = "HookDefinition"
    UNKNOWN = "Unknown"
    UNSUPPORTED = "Unsupported"


class XRPLTransactionType(StrEnum):
    """Native ledger transaction types (not EVM opcodes)."""

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
    DEPOSIT_PREAUTH = "DepositPreauth"
    NFTOKEN_MINT = "NFTokenMint"
    NFTOKEN_BURN = "NFTokenBurn"
    NFTOKEN_CREATE_OFFER = "NFTokenCreateOffer"
    NFTOKEN_ACCEPT_OFFER = "NFTokenAcceptOffer"
    NFTOKEN_CANCEL_OFFER = "NFTokenCancelOffer"
    AMM_CREATE = "AMMCreate"
    AMM_DEPOSIT = "AMMDeposit"
    AMM_WITHDRAW = "AMMWithdraw"
    AMM_VOTE = "AMMVote"
    AMM_BID = "AMMBid"
    AMM_DELETE = "AMMDelete"
    SET_HOOK = "SetHook"
    ACCOUNT_DELETE = "AccountDelete"
    UNKNOWN = "Unknown"
    UNSUPPORTED = "Unsupported"


class HookCapabilityState(StrEnum):
    """Whether Hooks are proven present on the observed network/amendment set."""

    PROVEN = "proven"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class SidechainRouting(StrEnum):
    """How a request is routed between XRPL mainnet and EVM sidechain."""

    XRPL_NATIVE = "xrpl_native"
    EVM_SIDECHAIN = "evm_sidechain"
    REJECTED_CROSS_NETWORK = "rejected_cross_network"
    UNKNOWN = "unknown"


class AmountKind(StrEnum):
    """Asset amount encoding on XRPL."""

    XRP = "xrp"
    ISSUED = "issued"
    UNKNOWN = "unknown"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _optional_text(value: str | None, name: str) -> str:
    if value is None or value == "":
        return ""
    return _required_text(value, name)


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{name} must be a bool")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def is_xrpl_chain_id(chain_id: str | int) -> bool:
    """Return whether *chain_id* is a known XRPL native network id."""

    text = str(chain_id).strip().lower()
    return text in _NETWORK_ALIASES or text in _KNOWN_XRPL


def is_ripple_evm_sidechain(chain_id: str | int | None, network: str = "") -> bool:
    """Return whether the identity is the Ripple EVM sidechain (not XRPL mainnet)."""

    candidates = {
        str(chain_id).strip().lower() if chain_id is not None else "",
        network.strip().lower() if network else "",
    }
    return bool(candidates & {a.lower() for a in _EVM_SIDECHAIN_ALIASES})


def resolve_xrpl_chain_id(chain_id: str | int = "", network: str = "") -> str:
    """Resolve aliases to a canonical XRPL chain id; reject EVM sidechain."""

    if is_ripple_evm_sidechain(chain_id, network):
        raise InvalidRequestError(
            "Ripple EVM sidechain must not be resolved as XRPL native ledger; "
            "delegate to the EVM frontend"
        )
    raw = str(chain_id).strip() if chain_id not in (None, "") else ""
    net = network.strip().lower() if network else ""
    if raw:
        key = raw.lower()
        if key in _NETWORK_ALIASES:
            return _NETWORK_ALIASES[key]
        if raw in _KNOWN_XRPL:
            return raw
        # Allow explicit non-alias numeric/string chain ids that look like XRPL.
        if raw.isdigit() and raw in _KNOWN_XRPL:
            return raw
        raise InvalidRequestError(f"unknown XRPL chain_id: {raw!r}")
    if net:
        if net in _NETWORK_ALIASES:
            return _NETWORK_ALIASES[net]
        raise InvalidRequestError(f"unknown XRPL network: {network!r}")
    raise InvalidRequestError("chain_id or network is required for XRPL resolution")


def xrpl_network_anchor(chain_id: str | int) -> dict[str, str]:
    """Return network/genesis metadata for a known XRPL chain id."""

    resolved = resolve_xrpl_chain_id(chain_id)
    anchor = _KNOWN_XRPL[resolved]
    return {
        "chain_id": resolved,
        "network": anchor["network"],
        "genesis_hash": anchor["genesis_hash"],
        "display_name": anchor["display_name"],
    }


def normalize_classic_address(value: str, *, field: str = "address") -> str:
    """Validate and return a classic r-address (lossless; no X-address decode)."""

    text = _required_text(value, field)
    if _X_ADDRESS_RE.fullmatch(text):
        raise InvalidRequestError(
            f"{field} is an X-address; decode to classic r-address + destination tag first"
        )
    if not _CLASSIC_ADDRESS_RE.fullmatch(text):
        raise InvalidRequestError(f"{field} must be a classic XRPL r-address")
    return text


def normalize_ledger_hash(value: str, *, field: str = "ledger_hash") -> str:
    """Normalize a 64-hex ledger/transaction hash to uppercase without 0x."""

    text = _required_text(value, field)
    if text.startswith(("0x", "0X")):
        text = text[2:]
    if not _HASH_RE.fullmatch(text) and not re.fullmatch(r"[0-9A-Fa-f]{64}", text):
        raise InvalidRequestError(f"{field} must be a 64-hex hash")
    return text.upper()


def normalize_currency(value: str) -> str:
    """Normalize issued currency code (3-char or 40-hex); reject bare XRP."""

    text = _required_text(value, "currency")
    if text.upper() == "XRP":
        raise InvalidRequestError("XRP is the native asset and cannot be an issued currency")
    if _CURRENCY_HEX.fullmatch(text):
        return text.upper()
    if _CURRENCY_STANDARD.fullmatch(text):
        return text
    raise InvalidRequestError(
        "currency must be a 3-char code or 40-hex nonstandard currency"
    )


def map_transaction_type(value: str | XRPLTransactionType) -> XRPLTransactionType:
    """Map a transaction type string to :class:`XRPLTransactionType`."""

    if isinstance(value, XRPLTransactionType):
        return value
    text = _required_text(str(value), "transaction_type")
    try:
        return XRPLTransactionType(text)
    except ValueError:
        # Common alias forms
        normalized = text.replace(" ", "").replace("_", "")
        for member in XRPLTransactionType:
            if member.value.replace("_", "").lower() == normalized.lower():
                return member
        return XRPLTransactionType.UNKNOWN


def map_ledger_object_kind(value: str | LedgerObjectKind) -> LedgerObjectKind:
    if isinstance(value, LedgerObjectKind):
        return value
    text = _required_text(str(value), "object_kind")
    try:
        return LedgerObjectKind(text)
    except ValueError:
        aliases = {
            "ripplestate": LedgerObjectKind.TRUST_LINE,
            "trustline": LedgerObjectKind.TRUST_LINE,
            "paychannel": LedgerObjectKind.PAYMENT_CHANNEL,
            "paymentchannel": LedgerObjectKind.PAYMENT_CHANNEL,
            "signerlist": LedgerObjectKind.SIGNER_LIST,
            "nftokenpage": LedgerObjectKind.NFTOKEN_PAGE,
            "nftokenoffer": LedgerObjectKind.NFTOKEN_OFFER,
            "accountroot": LedgerObjectKind.ACCOUNT_ROOT,
        }
        key = text.replace(" ", "").replace("_", "").lower()
        if key in aliases:
            return aliases[key]
        return LedgerObjectKind.UNKNOWN


def partial_payment_flag_set(flags: int) -> bool:
    """Return whether the Payment tfPartialPayment flag is set."""

    if isinstance(flags, bool) or not isinstance(flags, int) or flags < 0:
        raise InvalidRequestError("flags must be a non-negative integer")
    return bool(flags & TF_PARTIAL_PAYMENT)


def incomplete_coverage_never_passes(status: SemanticPassStatus) -> SemanticPassStatus:
    """Guard: incomplete / unsupported / unknown must not silently pass."""

    if not isinstance(status, SemanticPassStatus):
        status = SemanticPassStatus(str(status))
    if status is SemanticPassStatus.PASS:
        return status
    if status in {
        SemanticPassStatus.INCOMPLETE,
        SemanticPassStatus.UNSUPPORTED,
        SemanticPassStatus.UNKNOWN,
        SemanticPassStatus.FAIL_CLOSED,
    }:
        return status
    return SemanticPassStatus.FAIL_CLOSED


# ---------------------------------------------------------------------------
# Issued asset / issuer policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuedAsset:
    """XRPL issued currency identity: issuer + currency code.

    XRP is *never* represented as an IssuedAsset.
    """

    issuer: str
    currency: str
    symbol: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "issuer", normalize_classic_address(self.issuer, field="issuer")
        )
        currency = normalize_currency(self.currency)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self,
            "symbol",
            _optional_text(self.symbol, "symbol") or currency,
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    @property
    def asset_reference(self) -> str:
        return f"{self.issuer}/{self.currency}"

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
        if not isinstance(value, Mapping):
            raise InvalidRequestError("IssuedAsset must be a mapping")
        return cls(
            issuer=str(value.get("issuer", "")),
            currency=str(value.get("currency", "")),
            symbol=str(value.get("symbol", "")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class IssuerPolicy:
    """Issuer authority for freeze, clawback, require-auth, and default ripple.

    Freeze and clawback transitions are only admissible when the corresponding
    account flags are declared.  Never invents Ethereum-style admin roles.
    """

    issuer: str
    require_auth: bool = False
    default_ripple: bool = False
    global_freeze: bool = False
    no_freeze: bool = False
    allow_trustline_clawback: bool = False
    deposit_auth: bool = False
    account_flags: int = 0
    enabled_amendments: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "issuer", normalize_classic_address(self.issuer, field="issuer")
        )
        for name in (
            "require_auth",
            "default_ripple",
            "global_freeze",
            "no_freeze",
            "allow_trustline_clawback",
            "deposit_auth",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        object.__setattr__(
            self, "account_flags", _non_negative(self.account_flags, "account_flags")
        )
        amendments = tuple(
            _required_text(item, "amendment") for item in self.enabled_amendments
        )
        object.__setattr__(self, "enabled_amendments", amendments)
        # Consistency: no_freeze forbids global_freeze.
        if self.no_freeze and self.global_freeze:
            raise InvalidRequestError(
                "IssuerPolicy cannot set both no_freeze and global_freeze"
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def can_freeze(self) -> bool:
        """Whether freeze transitions are admissible for this issuer."""

        return not self.no_freeze

    @property
    def can_clawback(self) -> bool:
        """Whether clawback is admissible (requires explicit enablement)."""

        return self.allow_trustline_clawback

    def authorize_freeze(self, *, global_scope: bool = False) -> SemanticPassStatus:
        if self.no_freeze:
            return SemanticPassStatus.FAIL_CLOSED
        if global_scope and not self.global_freeze:
            return SemanticPassStatus.FAIL_CLOSED
        if not self.can_freeze:
            return SemanticPassStatus.FAIL_CLOSED
        return SemanticPassStatus.PASS

    def authorize_clawback(self) -> SemanticPassStatus:
        if not self.allow_trustline_clawback:
            return SemanticPassStatus.FAIL_CLOSED
        return SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_flags": self.account_flags,
            "allow_trustline_clawback": self.allow_trustline_clawback,
            "attributes": thaw_json(self.attributes),
            "can_clawback": self.can_clawback,
            "can_freeze": self.can_freeze,
            "default_ripple": self.default_ripple,
            "deposit_auth": self.deposit_auth,
            "enabled_amendments": list(self.enabled_amendments),
            "global_freeze": self.global_freeze,
            "issuer": self.issuer,
            "no_freeze": self.no_freeze,
            "require_auth": self.require_auth,
            "schema_version": self.schema_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IssuerPolicy":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("IssuerPolicy must be a mapping")
        return cls(
            issuer=str(value.get("issuer", "")),
            require_auth=bool(value.get("require_auth", False)),
            default_ripple=bool(value.get("default_ripple", False)),
            global_freeze=bool(value.get("global_freeze", False)),
            no_freeze=bool(value.get("no_freeze", False)),
            allow_trustline_clawback=bool(
                value.get("allow_trustline_clawback", False)
            ),
            deposit_auth=bool(value.get("deposit_auth", False)),
            account_flags=int(value.get("account_flags", 0) or 0),
            enabled_amendments=tuple(value.get("enabled_amendments", ()) or ()),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", SEMANTICS_SCHEMA_VERSION)
            ),
        )

    @classmethod
    def from_account_flags(
        cls,
        issuer: str,
        *,
        flags: int = 0,
        set_flag: int | None = None,
        clear_flag: int | None = None,
        allow_trustline_clawback: bool | None = None,
        enabled_amendments: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> "IssuerPolicy":
        """Derive issuer policy from AccountRoot Flags / SetFlag / ClearFlag."""

        flags_i = _non_negative(flags, "flags")
        # AccountRoot Flags bit layout is not identical to asf* enum numbers;
        # we accept explicit booleans derived by callers and optional set_flag.
        require_auth = bool(flags_i & (1 << 16))  # lsfRequireAuth
        default_ripple = bool(flags_i & (1 << 23))  # lsfDefaultRipple
        global_freeze = bool(flags_i & (1 << 22))  # lsfGlobalFreeze
        no_freeze = bool(flags_i & (1 << 21))  # lsfNoFreeze
        deposit_auth = bool(flags_i & (1 << 24))  # lsfDepositAuth
        clawback = bool(flags_i & (1 << 28)) if allow_trustline_clawback is None else (
            bool(allow_trustline_clawback)
        )
        # SetFlag / ClearFlag override when provided (AccountSet semantics).
        if set_flag is not None:
            sf = _positive(set_flag, "set_flag")
            if sf == ASF_REQUIRE_AUTH:
                require_auth = True
            elif sf == ASF_DEFAULT_RIPPLE:
                default_ripple = True
            elif sf == ASF_GLOBAL_FREEZE:
                global_freeze = True
            elif sf == ASF_NO_FREEZE:
                no_freeze = True
            elif sf == ASF_DEPOSIT_AUTH:
                deposit_auth = True
            elif sf == ASF_ALLOW_TRUSTLINE_CLAWBACK:
                clawback = True
        if clear_flag is not None:
            cf = _positive(clear_flag, "clear_flag")
            if cf == ASF_REQUIRE_AUTH:
                require_auth = False
            elif cf == ASF_DEFAULT_RIPPLE:
                default_ripple = False
            elif cf == ASF_GLOBAL_FREEZE:
                global_freeze = False
            elif cf == ASF_DEPOSIT_AUTH:
                deposit_auth = False
            # no_freeze and allow clawback are not clearable once set on-ledger
        return cls(
            issuer=issuer,
            require_auth=require_auth,
            default_ripple=default_ripple,
            global_freeze=global_freeze,
            no_freeze=no_freeze,
            allow_trustline_clawback=clawback,
            deposit_auth=deposit_auth,
            account_flags=flags_i,
            enabled_amendments=tuple(enabled_amendments),
            attributes=dict(attributes or {}),
        )


# ---------------------------------------------------------------------------
# Hooks capability (AST: HookCapability)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HookCapability:
    """Explicit Hooks amendment/capability evidence for one network epoch.

    When capability is not proven present, any Hook claim must surface as
    ``UNSUPPORTED`` — never invent Hook execution or EVM-style contract logic.
    """

    chain_id: str
    state: HookCapabilityState
    amendment_name: str = "Hooks"
    amendment_enabled: bool = False
    capability_evidence: str = ""
    network: str = ""
    ledger_index: int | None = None
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        resolved = resolve_xrpl_chain_id(self.chain_id)
        anchor = xrpl_network_anchor(resolved)
        object.__setattr__(self, "chain_id", resolved)
        state = (
            self.state
            if isinstance(self.state, HookCapabilityState)
            else HookCapabilityState(str(self.state))
        )
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "amendment_name",
            _required_text(self.amendment_name, "amendment_name"),
        )
        object.__setattr__(
            self, "amendment_enabled", _bool(self.amendment_enabled, "amendment_enabled")
        )
        object.__setattr__(
            self,
            "capability_evidence",
            _optional_text(self.capability_evidence, "capability_evidence"),
        )
        object.__setattr__(
            self, "network", self.network.strip() or anchor["network"]
        )
        if self.ledger_index is not None:
            object.__setattr__(
                self,
                "ledger_index",
                _non_negative(self.ledger_index, "ledger_index"),
            )
        # Invariant: proven requires amendment_enabled and evidence.
        if state is HookCapabilityState.PROVEN:
            if not self.amendment_enabled:
                raise InvalidRequestError(
                    "HookCapability PROVEN requires amendment_enabled=True"
                )
            if not self.capability_evidence:
                raise InvalidRequestError(
                    "HookCapability PROVEN requires capability_evidence"
                )
        if state is HookCapabilityState.ABSENT and self.amendment_enabled:
            raise InvalidRequestError(
                "HookCapability ABSENT cannot claim amendment_enabled"
            )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(d, "diagnostics item") for d in self.diagnostics),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def is_supported(self) -> bool:
        return self.state is HookCapabilityState.PROVEN and self.amendment_enabled

    def evaluate_hook_claim(self) -> SemanticPassStatus:
        """Return pass status for a SetHook / Hook object claim."""

        if self.state is HookCapabilityState.PROVEN and self.amendment_enabled:
            return SemanticPassStatus.PASS
        if self.state is HookCapabilityState.ABSENT:
            return SemanticPassStatus.UNSUPPORTED
        if self.state is HookCapabilityState.UNSUPPORTED:
            return SemanticPassStatus.UNSUPPORTED
        if self.state is HookCapabilityState.UNKNOWN:
            return SemanticPassStatus.UNKNOWN
        return SemanticPassStatus.UNSUPPORTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment_enabled": self.amendment_enabled,
            "amendment_name": self.amendment_name,
            "attributes": thaw_json(self.attributes),
            "capability_evidence": self.capability_evidence,
            "chain_id": self.chain_id,
            "diagnostics": list(self.diagnostics),
            "is_supported": self.is_supported,
            "ledger_index": self.ledger_index,
            "network": self.network,
            "schema_version": self.schema_version,
            "state": self.state.value
            if isinstance(self.state, HookCapabilityState)
            else str(self.state),
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def absent(
        cls,
        chain_id: str,
        *,
        network: str = "",
        diagnostics: Sequence[str] = (),
    ) -> "HookCapability":
        return cls(
            chain_id=chain_id,
            state=HookCapabilityState.ABSENT,
            amendment_enabled=False,
            capability_evidence="",
            network=network,
            diagnostics=tuple(diagnostics)
            or ("Hooks amendment not proven present",),
        )

    @classmethod
    def proven(
        cls,
        chain_id: str,
        *,
        capability_evidence: str,
        network: str = "",
        ledger_index: int | None = None,
        amendment_name: str = "Hooks",
    ) -> "HookCapability":
        return cls(
            chain_id=chain_id,
            state=HookCapabilityState.PROVEN,
            amendment_name=amendment_name,
            amendment_enabled=True,
            capability_evidence=_required_text(
                capability_evidence, "capability_evidence"
            ),
            network=network,
            ledger_index=ledger_index,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HookCapability":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("HookCapability must be a mapping")
        return cls(
            chain_id=str(value.get("chain_id", "")),
            state=HookCapabilityState(str(value.get("state", "unknown"))),
            amendment_name=str(value.get("amendment_name", "Hooks")),
            amendment_enabled=bool(value.get("amendment_enabled", False)),
            capability_evidence=str(value.get("capability_evidence", "")),
            network=str(value.get("network", "")),
            ledger_index=value.get("ledger_index"),
            diagnostics=tuple(value.get("diagnostics", ()) or ()),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", SEMANTICS_SCHEMA_VERSION)
            ),
        )


# ---------------------------------------------------------------------------
# Validated ledger epoch / reserves / signer quorum
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidatedLedgerEpoch:
    """Validated ledger coordinate binding for one XRPL network epoch."""

    chain_id: str
    ledger_index: int
    ledger_hash: str
    validated: bool = True
    parent_hash: str = ""
    close_time: int | None = None
    network: str = ""
    genesis_hash: str = ""
    base_reserve_drops: str = ""
    owner_reserve_drops: str = ""
    enabled_amendments: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        resolved = resolve_xrpl_chain_id(self.chain_id)
        anchor = xrpl_network_anchor(resolved)
        object.__setattr__(self, "chain_id", resolved)
        object.__setattr__(
            self, "ledger_index", _non_negative(self.ledger_index, "ledger_index")
        )
        object.__setattr__(
            self,
            "ledger_hash",
            normalize_ledger_hash(self.ledger_hash, field="ledger_hash"),
        )
        object.__setattr__(self, "validated", _bool(self.validated, "validated"))
        if not self.validated:
            raise InvalidRequestError(
                "ValidatedLedgerEpoch requires validated=True; unvalidated "
                "ledgers must use an incomplete/unknown path"
            )
        if self.parent_hash:
            object.__setattr__(
                self,
                "parent_hash",
                normalize_ledger_hash(self.parent_hash, field="parent_hash"),
            )
        else:
            object.__setattr__(self, "parent_hash", "")
        if self.close_time is not None:
            object.__setattr__(
                self, "close_time", _non_negative(self.close_time, "close_time")
            )
        object.__setattr__(
            self, "network", self.network.strip() or anchor["network"]
        )
        object.__setattr__(
            self,
            "genesis_hash",
            self.genesis_hash.strip() or anchor["genesis_hash"],
        )
        for name in ("base_reserve_drops", "owner_reserve_drops"):
            raw = getattr(self, name)
            if raw:
                text = _required_text(str(raw), name)
                if not _DECIMAL_INTEGER.fullmatch(text) or text.startswith("-"):
                    raise InvalidRequestError(f"{name} must be a non-negative integer string")
                object.__setattr__(self, name, text)
            else:
                object.__setattr__(self, name, "")
        object.__setattr__(
            self,
            "enabled_amendments",
            tuple(
                _required_text(item, "amendment") for item in self.enabled_amendments
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def epoch_id(self) -> str:
        return f"xrpl:{self.chain_id}:{self.ledger_index}:{self.ledger_hash[:16]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "base_reserve_drops": self.base_reserve_drops,
            "chain_id": self.chain_id,
            "close_time": self.close_time,
            "enabled_amendments": list(self.enabled_amendments),
            "epoch_id": self.epoch_id,
            "genesis_hash": self.genesis_hash,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "network": self.network,
            "owner_reserve_drops": self.owner_reserve_drops,
            "parent_hash": self.parent_hash,
            "schema_version": self.schema_version,
            "validated": self.validated,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidatedLedgerEpoch":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ValidatedLedgerEpoch must be a mapping")
        return cls(
            chain_id=str(value.get("chain_id", "")),
            ledger_index=int(value.get("ledger_index", 0)),
            ledger_hash=str(value.get("ledger_hash", "")),
            validated=bool(value.get("validated", True)),
            parent_hash=str(value.get("parent_hash", "")),
            close_time=value.get("close_time"),
            network=str(value.get("network", "")),
            genesis_hash=str(value.get("genesis_hash", "")),
            base_reserve_drops=str(value.get("base_reserve_drops", "")),
            owner_reserve_drops=str(value.get("owner_reserve_drops", "")),
            enabled_amendments=tuple(value.get("enabled_amendments", ()) or ()),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", SEMANTICS_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class SignerQuorum:
    """SignerList quorum requirement for multi-signer authorization."""

    account: str
    quorum: int
    signers: tuple[Mapping[str, Any], ...] = ()
    signer_list_id: int = 0
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "account", normalize_classic_address(self.account, field="account")
        )
        object.__setattr__(self, "quorum", _positive(self.quorum, "quorum"))
        object.__setattr__(
            self, "signer_list_id", _non_negative(self.signer_list_id, "signer_list_id")
        )
        frozen_signers: list[Mapping[str, Any]] = []
        total_weight = 0
        for index, item in enumerate(self.signers):
            if not isinstance(item, Mapping):
                raise InvalidRequestError(f"signers[{index}] must be a mapping")
            account = normalize_classic_address(
                str(item.get("account", item.get("Account", ""))),
                field=f"signers[{index}].account",
            )
            weight = item.get("weight", item.get("SignerWeight", 0))
            if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
                raise InvalidRequestError(
                    f"signers[{index}].weight must be a positive integer"
                )
            total_weight += weight
            frozen_signers.append(
                MappingProxyType(
                    {
                        "account": account,
                        "weight": weight,
                    }
                )
            )
        object.__setattr__(self, "signers", tuple(frozen_signers))
        if frozen_signers and total_weight < self.quorum:
            raise InvalidRequestError(
                "signer total weight must be >= quorum when signers are declared"
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "attributes": thaw_json(self.attributes),
            "quorum": self.quorum,
            "signer_list_id": self.signer_list_id,
            "signers": [dict(s) for s in self.signers],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignerQuorum":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SignerQuorum must be a mapping")
        return cls(
            account=str(value.get("account", "")),
            quorum=int(value.get("quorum", 0)),
            signers=tuple(value.get("signers", ()) or ()),
            signer_list_id=int(value.get("signer_list_id", 0) or 0),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Ledger object transition (AST: LedgerObjectTransition)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerObjectTransition:
    """Native XRPL ledger object state transition (not an EVM call).

    Captures typed facts for one transaction applied (or proposed) against a
    validated ledger: accounts, amounts, delivered amount, flags, sequence/
    ticket, signers, destination tag, partial payment, and ledger coordinate.
    Hook effects are only recorded when :class:`HookCapability` is proven.
    """

    transition_id: str
    transaction_type: XRPLTransactionType
    account: str
    object_kind: LedgerObjectKind = LedgerObjectKind.UNKNOWN
    destination: str = ""
    destination_tag: int | None = None
    source_tag: int | None = None
    amount_kind: str = ""
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
    signer_quorum: SignerQuorum | None = None
    ledger_index: int | None = None
    ledger_hash: str = ""
    transaction_hash: str = ""
    validated: bool | None = None
    engine_result: str = ""
    memos: tuple[Mapping[str, Any], ...] = ()
    trust_line: Mapping[str, Any] | None = None
    issuer_policy: IssuerPolicy | None = None
    hooks_capability: HookCapability | None = None
    hooks_effects: tuple[Mapping[str, Any], ...] = ()
    object_id: str = ""
    previous_fields: Mapping[str, Any] = field(default_factory=dict)
    final_fields: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transition_id",
            _required_text(self.transition_id, "transition_id"),
        )
        tx_type = map_transaction_type(self.transaction_type)
        object.__setattr__(self, "transaction_type", tx_type)
        object.__setattr__(
            self, "account", normalize_classic_address(self.account, field="account")
        )
        object.__setattr__(
            self, "object_kind", map_ledger_object_kind(self.object_kind)
        )
        if self.destination:
            object.__setattr__(
                self,
                "destination",
                normalize_classic_address(self.destination, field="destination"),
            )
        else:
            object.__setattr__(self, "destination", "")
        if self.destination_tag is not None:
            object.__setattr__(
                self,
                "destination_tag",
                _non_negative(self.destination_tag, "destination_tag"),
            )
        if self.source_tag is not None:
            object.__setattr__(
                self, "source_tag", _non_negative(self.source_tag, "source_tag")
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
            "object_id",
        ):
            raw = getattr(self, name)
            object.__setattr__(self, name, _optional_text(str(raw) if raw else "", name))
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
        object.__setattr__(self, "flags", _non_negative(self.flags, "flags"))
        # Derive partial_payment from flags when not explicitly set True via flag.
        partial = _bool(self.partial_payment, "partial_payment")
        if partial_payment_flag_set(self.flags):
            partial = True
        object.__setattr__(self, "partial_payment", partial)
        if self.amount_kind:
            kind = self.amount_kind.lower()
            if kind not in {AmountKind.XRP.value, AmountKind.ISSUED.value, AmountKind.UNKNOWN.value}:
                raise InvalidRequestError(
                    "amount_kind must be 'xrp', 'issued', or 'unknown'"
                )
            object.__setattr__(self, "amount_kind", kind)
        if self.amount_value and self.amount_kind == AmountKind.XRP.value:
            if not _DECIMAL_INTEGER.fullmatch(self.amount_value):
                raise InvalidRequestError(
                    "XRP amount_value must be integer drops string"
                )
        if self.amount_value and self.amount_kind == AmountKind.ISSUED.value:
            if not _DECIMAL_AMOUNT.fullmatch(self.amount_value):
                raise InvalidRequestError(
                    "issued amount_value must be a decimal string"
                )
        if self.issued_asset is not None and not isinstance(
            self.issued_asset, IssuedAsset
        ):
            raise InvalidRequestError("issued_asset must be IssuedAsset or None")
        if self.delivered_issued_asset is not None and not isinstance(
            self.delivered_issued_asset, IssuedAsset
        ):
            raise InvalidRequestError(
                "delivered_issued_asset must be IssuedAsset or None"
            )
        if self.amount_kind == AmountKind.ISSUED.value and self.issued_asset is None:
            raise InvalidRequestError(
                "issued amount_kind requires issued_asset"
            )
        if self.amount_kind == AmountKind.XRP.value and self.issued_asset is not None:
            raise InvalidRequestError(
                "XRP amount_kind must not carry issued_asset"
            )
        for name in ("sequence", "ticket_sequence", "last_ledger_sequence", "ledger_index"):
            val = getattr(self, name)
            if val is not None:
                object.__setattr__(self, name, _non_negative(val, name))
        # Sequence XOR ticket: both may be absent (incomplete), but both set is invalid.
        if self.sequence is not None and self.ticket_sequence is not None:
            raise InvalidRequestError(
                "sequence and ticket_sequence are mutually exclusive"
            )
        if self.signer_quorum is not None and not isinstance(
            self.signer_quorum, SignerQuorum
        ):
            raise InvalidRequestError("signer_quorum must be SignerQuorum or None")
        if self.validated is not None:
            object.__setattr__(self, "validated", _bool(self.validated, "validated"))
        memos: list[Mapping[str, Any]] = []
        for index, memo in enumerate(self.memos):
            if not isinstance(memo, Mapping):
                raise InvalidRequestError(f"memos[{index}] must be a mapping")
            memos.append(_freeze_mapping(memo))
        object.__setattr__(self, "memos", tuple(memos))
        if self.trust_line is not None:
            if not isinstance(self.trust_line, Mapping):
                raise InvalidRequestError("trust_line must be a mapping or None")
            object.__setattr__(self, "trust_line", _freeze_mapping(self.trust_line))
        if self.issuer_policy is not None and not isinstance(
            self.issuer_policy, IssuerPolicy
        ):
            raise InvalidRequestError("issuer_policy must be IssuerPolicy or None")
        if self.hooks_capability is not None and not isinstance(
            self.hooks_capability, HookCapability
        ):
            raise InvalidRequestError(
                "hooks_capability must be HookCapability or None"
            )
        effects: list[Mapping[str, Any]] = []
        for index, effect in enumerate(self.hooks_effects):
            if not isinstance(effect, Mapping):
                raise InvalidRequestError(f"hooks_effects[{index}] must be a mapping")
            effects.append(_freeze_mapping(effect))
        object.__setattr__(self, "hooks_effects", tuple(effects))
        # Fail closed: hooks_effects require proven capability.
        if self.hooks_effects:
            if self.hooks_capability is None or not self.hooks_capability.is_supported:
                raise InvalidRequestError(
                    "hooks_effects require proven HookCapability; "
                    "absent Hooks must return UNSUPPORTED"
                )
        object.__setattr__(
            self, "previous_fields", _freeze_mapping(self.previous_fields)
        )
        object.__setattr__(self, "final_fields", _freeze_mapping(self.final_fields))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def semantic_status(self) -> SemanticPassStatus:
        """Derive a fail-closed semantic status for this transition."""

        if self.transaction_type is XRPLTransactionType.UNSUPPORTED:
            return SemanticPassStatus.UNSUPPORTED
        if self.transaction_type is XRPLTransactionType.UNKNOWN:
            return SemanticPassStatus.UNKNOWN
        if self.object_kind is LedgerObjectKind.UNSUPPORTED:
            return SemanticPassStatus.UNSUPPORTED
        # SetHook without proven Hooks → UNSUPPORTED
        if self.transaction_type is XRPLTransactionType.SET_HOOK:
            if self.hooks_capability is None:
                return SemanticPassStatus.UNSUPPORTED
            return self.hooks_capability.evaluate_hook_claim()
        if self.hooks_effects and (
            self.hooks_capability is None or not self.hooks_capability.is_supported
        ):
            return SemanticPassStatus.UNSUPPORTED
        # Incomplete coordinate facts
        if self.ledger_index is None or not self.ledger_hash:
            return SemanticPassStatus.INCOMPLETE
        if self.validated is False:
            return SemanticPassStatus.INCOMPLETE
        if self.sequence is None and self.ticket_sequence is None:
            return SemanticPassStatus.INCOMPLETE
        return SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "amount_kind": self.amount_kind,
            "amount_value": self.amount_value,
            "attributes": thaw_json(self.attributes),
            "delivered_amount_kind": self.delivered_amount_kind,
            "delivered_amount_value": self.delivered_amount_value,
            "delivered_issued_asset": self.delivered_issued_asset.to_dict()
            if self.delivered_issued_asset is not None
            else None,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "engine_result": self.engine_result,
            "fee_drops": self.fee_drops,
            "final_fields": thaw_json(self.final_fields),
            "flags": self.flags,
            "hooks_capability": self.hooks_capability.to_dict()
            if self.hooks_capability is not None
            else None,
            "hooks_effects": [thaw_json(e) for e in self.hooks_effects],
            "issued_asset": self.issued_asset.to_dict()
            if self.issued_asset is not None
            else None,
            "issuer_policy": self.issuer_policy.to_dict()
            if self.issuer_policy is not None
            else None,
            "last_ledger_sequence": self.last_ledger_sequence,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "memos": [thaw_json(m) for m in self.memos],
            "object_id": self.object_id,
            "object_kind": self.object_kind.value
            if isinstance(self.object_kind, LedgerObjectKind)
            else str(self.object_kind),
            "partial_payment": self.partial_payment,
            "previous_fields": thaw_json(self.previous_fields),
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "signer_quorum": self.signer_quorum.to_dict()
            if self.signer_quorum is not None
            else None,
            "source_tag": self.source_tag,
            "ticket_sequence": self.ticket_sequence,
            "transaction_hash": self.transaction_hash,
            "transaction_type": self.transaction_type.value
            if isinstance(self.transaction_type, XRPLTransactionType)
            else str(self.transaction_type),
            "transition_id": self.transition_id,
            "trust_line": thaw_json(self.trust_line)
            if self.trust_line is not None
            else None,
            "validated": self.validated,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerObjectTransition":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("LedgerObjectTransition must be a mapping")
        issued = value.get("issued_asset")
        del_issued = value.get("delivered_issued_asset")
        policy = value.get("issuer_policy")
        hooks = value.get("hooks_capability")
        quorum = value.get("signer_quorum")
        return cls(
            transition_id=str(value.get("transition_id", "")),
            transaction_type=map_transaction_type(
                str(value.get("transaction_type", "Unknown"))
            ),
            account=str(value.get("account", "")),
            object_kind=map_ledger_object_kind(
                str(value.get("object_kind", "Unknown"))
            ),
            destination=str(value.get("destination", "")),
            destination_tag=value.get("destination_tag"),
            source_tag=value.get("source_tag"),
            amount_kind=str(value.get("amount_kind", "")),
            amount_value=str(value.get("amount_value", "")),
            issued_asset=IssuedAsset.from_dict(issued)
            if isinstance(issued, Mapping)
            else None,
            delivered_amount_kind=str(value.get("delivered_amount_kind", "")),
            delivered_amount_value=str(value.get("delivered_amount_value", "")),
            delivered_issued_asset=IssuedAsset.from_dict(del_issued)
            if isinstance(del_issued, Mapping)
            else None,
            fee_drops=str(value.get("fee_drops", "")),
            flags=int(value.get("flags", 0) or 0),
            partial_payment=bool(value.get("partial_payment", False)),
            sequence=value.get("sequence"),
            ticket_sequence=value.get("ticket_sequence"),
            last_ledger_sequence=value.get("last_ledger_sequence"),
            signer_quorum=SignerQuorum.from_dict(quorum)
            if isinstance(quorum, Mapping)
            else None,
            ledger_index=value.get("ledger_index"),
            ledger_hash=str(value.get("ledger_hash", "")),
            transaction_hash=str(value.get("transaction_hash", "")),
            validated=value.get("validated"),
            engine_result=str(value.get("engine_result", "")),
            memos=tuple(value.get("memos", ()) or ()),
            trust_line=value.get("trust_line"),
            issuer_policy=IssuerPolicy.from_dict(policy)
            if isinstance(policy, Mapping)
            else None,
            hooks_capability=HookCapability.from_dict(hooks)
            if isinstance(hooks, Mapping)
            else None,
            hooks_effects=tuple(value.get("hooks_effects", ()) or ()),
            object_id=str(value.get("object_id", "")),
            previous_fields=value.get("previous_fields", {}),
            final_fields=value.get("final_fields", {}),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", SEMANTICS_SCHEMA_VERSION)
            ),
        )


def default_object_kind_for_tx(
    transaction_type: XRPLTransactionType | str,
) -> LedgerObjectKind:
    """Map a transaction type to its primary affected ledger object kind."""

    tx = map_transaction_type(transaction_type)
    mapping: dict[XRPLTransactionType, LedgerObjectKind] = {
        XRPLTransactionType.PAYMENT: LedgerObjectKind.ACCOUNT_ROOT,
        XRPLTransactionType.TRUST_SET: LedgerObjectKind.TRUST_LINE,
        XRPLTransactionType.ACCOUNT_SET: LedgerObjectKind.ACCOUNT_ROOT,
        XRPLTransactionType.OFFER_CREATE: LedgerObjectKind.OFFER,
        XRPLTransactionType.OFFER_CANCEL: LedgerObjectKind.OFFER,
        XRPLTransactionType.ESCROW_CREATE: LedgerObjectKind.ESCROW,
        XRPLTransactionType.ESCROW_FINISH: LedgerObjectKind.ESCROW,
        XRPLTransactionType.ESCROW_CANCEL: LedgerObjectKind.ESCROW,
        XRPLTransactionType.PAYMENT_CHANNEL_CREATE: LedgerObjectKind.PAYMENT_CHANNEL,
        XRPLTransactionType.PAYMENT_CHANNEL_FUND: LedgerObjectKind.PAYMENT_CHANNEL,
        XRPLTransactionType.PAYMENT_CHANNEL_CLAIM: LedgerObjectKind.PAYMENT_CHANNEL,
        XRPLTransactionType.CHECK_CREATE: LedgerObjectKind.CHECK,
        XRPLTransactionType.CHECK_CASH: LedgerObjectKind.CHECK,
        XRPLTransactionType.CHECK_CANCEL: LedgerObjectKind.CHECK,
        XRPLTransactionType.SIGNER_LIST_SET: LedgerObjectKind.SIGNER_LIST,
        XRPLTransactionType.TICKET_CREATE: LedgerObjectKind.TICKET,
        XRPLTransactionType.DEPOSIT_PREAUTH: LedgerObjectKind.DEPOSIT_PREAUTH,
        XRPLTransactionType.NFTOKEN_MINT: LedgerObjectKind.NFTOKEN_PAGE,
        XRPLTransactionType.NFTOKEN_BURN: LedgerObjectKind.NFTOKEN_PAGE,
        XRPLTransactionType.NFTOKEN_CREATE_OFFER: LedgerObjectKind.NFTOKEN_OFFER,
        XRPLTransactionType.NFTOKEN_ACCEPT_OFFER: LedgerObjectKind.NFTOKEN_OFFER,
        XRPLTransactionType.NFTOKEN_CANCEL_OFFER: LedgerObjectKind.NFTOKEN_OFFER,
        XRPLTransactionType.AMM_CREATE: LedgerObjectKind.AMM,
        XRPLTransactionType.AMM_DEPOSIT: LedgerObjectKind.AMM,
        XRPLTransactionType.AMM_WITHDRAW: LedgerObjectKind.AMM,
        XRPLTransactionType.AMM_VOTE: LedgerObjectKind.AMM,
        XRPLTransactionType.AMM_BID: LedgerObjectKind.AMM,
        XRPLTransactionType.AMM_DELETE: LedgerObjectKind.AMM,
        XRPLTransactionType.SET_HOOK: LedgerObjectKind.HOOK,
        XRPLTransactionType.ACCOUNT_DELETE: LedgerObjectKind.ACCOUNT_ROOT,
    }
    return mapping.get(tx, LedgerObjectKind.UNKNOWN)


__all__ = [
    "SEMANTICS_SCHEMA_VERSION",
    "XRPL_MAINNET_CHAIN_ID",
    "XRPL_MAINNET_NETWORK",
    "XRPL_MAINNET_GENESIS_HASH",
    "XRPL_TESTNET_CHAIN_ID",
    "XRPL_TESTNET_NETWORK",
    "XRPL_TESTNET_GENESIS_HASH",
    "XRPL_DEVNET_CHAIN_ID",
    "XRPL_DEVNET_NETWORK",
    "XRPL_DEVNET_GENESIS_HASH",
    "RIPPLE_EVM_SIDECHAIN_CHAIN_ID",
    "RIPPLE_EVM_SIDECHAIN_NETWORK",
    "RIPPLE_EVM_SIDECHAIN_NAMESPACE",
    "NATIVE_ASSET_SYMBOL",
    "DROPS_PER_XRP",
    "NATIVE_DECIMALS",
    "TF_PARTIAL_PAYMENT",
    "ASF_ALLOW_TRUSTLINE_CLAWBACK",
    "ASF_GLOBAL_FREEZE",
    "ASF_NO_FREEZE",
    "ASF_REQUIRE_AUTH",
    "ASF_DEFAULT_RIPPLE",
    "ASF_DEPOSIT_AUTH",
    "SemanticPassStatus",
    "LedgerObjectKind",
    "XRPLTransactionType",
    "HookCapabilityState",
    "SidechainRouting",
    "AmountKind",
    "IssuedAsset",
    "IssuerPolicy",
    "HookCapability",
    "ValidatedLedgerEpoch",
    "SignerQuorum",
    "LedgerObjectTransition",
    "is_xrpl_chain_id",
    "is_ripple_evm_sidechain",
    "resolve_xrpl_chain_id",
    "xrpl_network_anchor",
    "normalize_classic_address",
    "normalize_ledger_hash",
    "normalize_currency",
    "map_transaction_type",
    "map_ledger_object_kind",
    "partial_payment_flag_set",
    "incomplete_coverage_never_passes",
    "default_object_kind_for_tx",
    "bytes_digest",
]
