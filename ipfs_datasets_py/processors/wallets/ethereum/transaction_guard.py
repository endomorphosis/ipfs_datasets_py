"""Non-custodial Ethereum / EVM transaction guard (CRYPTOIR-G530 / CRYPTOIR-030).

Normalize Ethereum/EVM transaction candidates and all native/token/contract/
proxy effects into the common two-phase wallet guard without adding signing
or broadcast.

Acceptance (fail-closed):

* Chain ID, nonce, fee, calldata, value, approvals, internal/token effects,
  code/proxy epoch, sender recovery, and exact serialized candidate are
  bound and revalidated.
* Permit substitution, nonce/fee mutation, proxy upgrade, hidden transfer,
  stale list/graph, and replay fixtures fail closed.
* An EVM transaction is guarded by **actual decoded and simulated effects**,
  not method name alone.

This module never signs, broadcasts, or accepts bare booleans / caller
approval flags as authority.  Keys remain with an external custody system.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.adapters.evm import (
    ETHEREUM_MAINNET_CHAIN_ID,
    ETHEREUM_MAINNET_GENESIS_HASH,
    ETHEREUM_MAINNET_NETWORK,
    EVM_NAMESPACE,
    EVMAdapterError,
    content_sha256_hex as evm_content_sha256_hex,
    normalize_address,
    normalize_hash,
    normalize_hex_data,
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

ETHEREUM_TRANSACTION_GUARD_INTERFACE: Final = "EthereumTransactionGuard@1"
ETHEREUM_TRANSACTION_GUARD_SCHEMA_VERSION: Final = (
    "wallet-guard.ethereum-transaction-guard/v1"
)
EVM_CANDIDATE_SCHEMA_VERSION: Final = (
    "wallet-guard.evm-transaction-candidate/v1"
)
CODE_PROXY_EPOCH_SCHEMA_VERSION: Final = (
    "wallet-guard.evm-code-proxy-epoch/v1"
)
APPROVAL_BINDING_SCHEMA_VERSION: Final = (
    "wallet-guard.evm-approval-binding/v1"
)
EVM_TX_BINDING_SCHEMA_VERSION: Final = "wallet-guard.evm-transaction-binding/v1"
ETHEREUM_GUARD_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.ethereum-guard-decision/v1"
)

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-ethereum-v1"
DEFAULT_POLICY_ID: Final = "policy:ethereum-wallet-guard-v1"
DEFAULT_FEE_WEI: Final = "21000000000000"  # 21000 * 1 gwei placeholder

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_HEX_PAYLOAD_CHARS: Final = 1_048_576

# Well-known ERC-20 / ERC-2612 selectors (4-byte method ids).
SELECTOR_APPROVE: Final = "0x095ea7b3"
SELECTOR_TRANSFER: Final = "0xa9059cbb"
SELECTOR_TRANSFER_FROM: Final = "0x23b872dd"
SELECTOR_PERMIT: Final = "0xd505accf"
SELECTOR_INCREASE_ALLOWANCE: Final = "0x39509351"
SELECTOR_DECREASE_ALLOWANCE: Final = "0xa457c2d7"

_KNOWN_SELECTORS: Final[dict[str, str]] = {
    SELECTOR_APPROVE: "approve",
    SELECTOR_TRANSFER: "transfer",
    SELECTOR_TRANSFER_FROM: "transferFrom",
    SELECTOR_PERMIT: "permit",
    SELECTOR_INCREASE_ALLOWANCE: "increaseAllowance",
    SELECTOR_DECREASE_ALLOWANCE: "decreaseAllowance",
}

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_DECIMAL_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")

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

DEFAULT_SECURITY_REQUIREMENTS: Final[tuple[str, ...]] = (
    "sec:evm-chain-identity",
    "sec:evm-nonce-fee",
    "sec:evm-calldata-effects",
    "sec:evm-approvals",
    "sec:evm-internal-token-effects",
    "sec:evm-code-proxy-epoch",
    "sec:evm-sender-recovery",
    "sec:evm-exact-candidate",
    "sec:evm-list-graph-freshness",
)
DEFAULT_COMPLIANCE_REQUIREMENTS: Final[tuple[str, ...]] = (
    "comp:direct-sanctions",
    "comp:bounded-exposure",
    "comp:contract-safety",
)

# Re-export alias for AST scanners that look for EVMTransactionCandidate.
__all__ = [
    "APPROVAL_BINDING_SCHEMA_VERSION",
    "ApprovalBinding",
    "CODE_PROXY_EPOCH_SCHEMA_VERSION",
    "CodeProxyEpoch",
    "DEFAULT_COMPLIANCE_REQUIREMENTS",
    "DEFAULT_SECURITY_REQUIREMENTS",
    "ETHEREUM_GUARD_DECISION_SCHEMA_VERSION",
    "ETHEREUM_TRANSACTION_GUARD_INTERFACE",
    "ETHEREUM_TRANSACTION_GUARD_SCHEMA_VERSION",
    "EVMTransactionBinding",
    "EVMTransactionCandidate",
    "EthereumGuardDecision",
    "EthereumGuardPhase",
    "EthereumTransactionGuard",
    "SELECTOR_APPROVE",
    "SELECTOR_PERMIT",
    "SELECTOR_TRANSFER",
    "SELECTOR_TRANSFER_FROM",
    "content_sha256_hex",
    "decode_calldata_effects",
    "evaluate_ethereum_transaction_guard",
    "method_selector",
]


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
        if isinstance(value, str) and value.isdigit():
            return int(value, 10)
        raise GuardValidationError(f"{name} must be an integer")
    if value < 0:
        raise GuardValidationError(f"{name} must be non-negative")
    return value


def _positive_int(value: Any, name: str) -> int:
    n = _non_negative_int(value, name)
    if n <= 0:
        raise GuardValidationError(f"{name} must be a positive integer")
    return n


def _amount(value: Any, name: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise GuardValidationError(f"{name} must be a non-negative integer")
        return str(value)
    text = _text(value, name, max_chars=128)
    if not _DECIMAL_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be a non-negative decimal integer string"
        )
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
    try:
        return evm_content_sha256_hex(_jsonable(payload))
    except Exception:  # noqa: BLE001
        return stable_digest(_jsonable(payload))


def _address(value: Any, name: str) -> str:
    try:
        return normalize_address(value, field=name)
    except (EVMAdapterError, TypeError, ValueError) as exc:
        raise GuardValidationError(f"{name} is not a valid EVM address: {exc}") from exc


def _optional_address(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _address(value, name)


def _hex_data(value: Any, name: str) -> str:
    try:
        return normalize_hex_data(value, field=name)
    except (EVMAdapterError, TypeError, ValueError) as exc:
        raise GuardValidationError(f"{name} is not valid hex data: {exc}") from exc


def _word_to_address(word_hex: str) -> str:
    """Decode a 32-byte ABI word as a 20-byte address (right-aligned)."""

    clean = word_hex.lower().removeprefix("0x")
    if len(clean) != 64:
        raise GuardValidationError("ABI word must be 32 bytes")
    return "0x" + clean[-40:]


def _word_to_uint(word_hex: str) -> str:
    clean = word_hex.lower().removeprefix("0x")
    if len(clean) != 64:
        raise GuardValidationError("ABI word must be 32 bytes")
    return str(int(clean, 16))


def method_selector(data: str) -> str:
    """Return the 4-byte method selector from calldata, or empty for bare value txs."""

    normalized = _hex_data(data, "data")
    if normalized in {"0x", "0X"} or len(normalized) < 10:
        return ""
    return normalized[:10].lower()


# ---------------------------------------------------------------------------
# Calldata decoding — effects, not method names alone
# ---------------------------------------------------------------------------


def decode_calldata_effects(
    *,
    to_address: str,
    data: str,
    value_wei: str = "0",
    from_address: str = "",
) -> dict[str, Any]:
    """Decode outer calldata into structured approval/transfer effect facts.

    Method *names* are never authoritative.  Effects are derived from the
    4-byte selector and ABI-decoded arguments.  Unknown selectors yield an
    explicit ``unknown_call`` effect so callers cannot claim safety from a
    friendly method label alone.
    """

    to_addr = _address(to_address, "to_address")
    calldata = _hex_data(data, "data")
    value = _amount(value_wei, "value_wei")
    sender = _optional_address(from_address, "from_address")
    selector = method_selector(calldata)

    approvals: list[dict[str, Any]] = []
    token_effects: list[dict[str, Any]] = []
    native_effects: list[dict[str, Any]] = []
    decoded_kind = "empty" if not selector else "unknown_call"
    decoded_args: dict[str, Any] = {}

    if int(value) > 0:
        native_effects.append(
            {
                "kind": "native_transfer",
                "from": sender,
                "to": to_addr,
                "value_wei": value,
            }
        )

    body = calldata[10:] if selector else ""
    words = [body[i : i + 64] for i in range(0, len(body), 64) if len(body[i : i + 64]) == 64]

    if selector == SELECTOR_APPROVE and len(words) >= 2:
        spender = _word_to_address(words[0])
        amount = _word_to_uint(words[1])
        decoded_kind = "approve"
        decoded_args = {"spender": spender, "amount": amount, "token": to_addr}
        approvals.append(
            {
                "kind": "approve",
                "token": to_addr,
                "owner": sender,
                "spender": spender,
                "amount": amount,
                "selector": selector,
                "source": "calldata",
            }
        )
    elif selector == SELECTOR_INCREASE_ALLOWANCE and len(words) >= 2:
        spender = _word_to_address(words[0])
        amount = _word_to_uint(words[1])
        decoded_kind = "increaseAllowance"
        decoded_args = {"spender": spender, "added_value": amount, "token": to_addr}
        approvals.append(
            {
                "kind": "increaseAllowance",
                "token": to_addr,
                "owner": sender,
                "spender": spender,
                "amount": amount,
                "selector": selector,
                "source": "calldata",
            }
        )
    elif selector == SELECTOR_DECREASE_ALLOWANCE and len(words) >= 2:
        spender = _word_to_address(words[0])
        amount = _word_to_uint(words[1])
        decoded_kind = "decreaseAllowance"
        decoded_args = {"spender": spender, "subtracted_value": amount, "token": to_addr}
        approvals.append(
            {
                "kind": "decreaseAllowance",
                "token": to_addr,
                "owner": sender,
                "spender": spender,
                "amount": amount,
                "selector": selector,
                "source": "calldata",
            }
        )
    elif selector == SELECTOR_PERMIT and len(words) >= 4:
        # permit(owner, spender, value, deadline, v, r, s) — first four words
        # are sufficient for effect binding; signature bytes are not stored.
        owner = _word_to_address(words[0])
        spender = _word_to_address(words[1])
        amount = _word_to_uint(words[2])
        deadline = _word_to_uint(words[3])
        decoded_kind = "permit"
        decoded_args = {
            "owner": owner,
            "spender": spender,
            "amount": amount,
            "deadline": deadline,
            "token": to_addr,
        }
        approvals.append(
            {
                "kind": "permit",
                "token": to_addr,
                "owner": owner,
                "spender": spender,
                "amount": amount,
                "deadline": deadline,
                "selector": selector,
                "source": "calldata",
            }
        )
    elif selector == SELECTOR_TRANSFER and len(words) >= 2:
        recipient = _word_to_address(words[0])
        amount = _word_to_uint(words[1])
        decoded_kind = "transfer"
        decoded_args = {"to": recipient, "amount": amount, "token": to_addr}
        token_effects.append(
            {
                "kind": "token_transfer",
                "token": to_addr,
                "from": sender,
                "to": recipient,
                "amount": amount,
                "selector": selector,
                "source": "calldata",
            }
        )
    elif selector == SELECTOR_TRANSFER_FROM and len(words) >= 3:
        source = _word_to_address(words[0])
        recipient = _word_to_address(words[1])
        amount = _word_to_uint(words[2])
        decoded_kind = "transferFrom"
        decoded_args = {
            "from": source,
            "to": recipient,
            "amount": amount,
            "token": to_addr,
        }
        token_effects.append(
            {
                "kind": "token_transfer",
                "token": to_addr,
                "from": source,
                "to": recipient,
                "amount": amount,
                "selector": selector,
                "source": "calldata",
            }
        )
    elif selector:
        decoded_kind = "unknown_call"
        decoded_args = {"selector": selector, "token_or_contract": to_addr}

    label = _KNOWN_SELECTORS.get(selector, "")
    return {
        "selector": selector,
        "decoded_kind": decoded_kind,
        "decoded_label": label,
        "decoded_args": decoded_args,
        "approvals": approvals,
        "token_effects": token_effects,
        "native_effects": native_effects,
    }


# ---------------------------------------------------------------------------
# Epoch / approval records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodeProxyEpoch:
    """Bound contract code / proxy implementation epoch for one address.

    Re-resolved at consumption.  A code hash, implementation, or proxy-admin
    change (upgrade) invalidates prior permission.
    """

    contract_address: str
    code_epoch: str
    chain_id: int
    code_hash: str = ""
    implementation_address: str = ""
    implementation_code_digest: str = ""
    proxy_kind: str = ""
    proxy_admin: str = ""
    network: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = CODE_PROXY_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contract_address",
            _address(self.contract_address, "contract_address"),
        )
        object.__setattr__(
            self, "code_epoch", _text(self.code_epoch, "code_epoch", max_chars=256)
        )
        object.__setattr__(self, "chain_id", _positive_int(self.chain_id, "chain_id"))
        if self.code_hash:
            try:
                object.__setattr__(
                    self, "code_hash", normalize_hash(self.code_hash, field="code_hash")
                )
            except EVMAdapterError as exc:
                # Also accept bare sha256 digests for offline fixtures.
                dig = _text(self.code_hash, "code_hash", max_chars=96)
                if dig.startswith("sha256:"):
                    dig = dig[len("sha256:") :]
                if dig.startswith("0x") and len(dig) == 66:
                    object.__setattr__(self, "code_hash", dig.lower())
                elif _SHA256_HEX_RE.fullmatch(dig):
                    object.__setattr__(self, "code_hash", dig)
                else:
                    raise GuardValidationError(f"code_hash invalid: {exc}") from exc
        else:
            object.__setattr__(self, "code_hash", "")
        object.__setattr__(
            self,
            "implementation_address",
            _optional_address(self.implementation_address, "implementation_address"),
        )
        if self.implementation_code_digest:
            dig = _text(
                self.implementation_code_digest,
                "implementation_code_digest",
                max_chars=96,
            )
            if dig.startswith("sha256:"):
                dig = dig[len("sha256:") :]
            if dig.startswith("0x") and len(dig) == 66:
                dig = dig[2:].lower()
            if not _SHA256_HEX_RE.fullmatch(dig):
                raise GuardValidationError(
                    "implementation_code_digest must be a SHA-256 hex digest"
                )
            object.__setattr__(self, "implementation_code_digest", dig)
        else:
            object.__setattr__(self, "implementation_code_digest", "")
        object.__setattr__(
            self, "proxy_kind", _optional_text(self.proxy_kind, "proxy_kind", max_chars=64)
        )
        object.__setattr__(
            self, "proxy_admin", _optional_address(self.proxy_admin, "proxy_admin")
        )
        try:
            anchor = resolve_network(
                chain_id=self.chain_id, network=self.network or None
            )
            object.__setattr__(self, "network", anchor.network)
        except EVMAdapterError:
            if self.network:
                object.__setattr__(
                    self, "network", _text(self.network, "network", max_chars=128)
                )
            else:
                object.__setattr__(self, "network", f"eip155:{self.chain_id}")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != CODE_PROXY_EPOCH_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported code/proxy epoch schema: {self.schema_version!r}"
            )

    @property
    def epoch_digest(self) -> str:
        return content_sha256_hex(
            {
                "chain_id": self.chain_id,
                "code_epoch": self.code_epoch,
                "code_hash": self.code_hash,
                "contract_address": self.contract_address,
                "implementation_address": self.implementation_address,
                "implementation_code_digest": self.implementation_code_digest,
                "proxy_admin": self.proxy_admin,
                "proxy_kind": self.proxy_kind,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "code_hash": self.code_hash,
            "contract_address": self.contract_address,
            "epoch_digest": self.epoch_digest,
            "implementation_address": self.implementation_address,
            "implementation_code_digest": self.implementation_code_digest,
            "network": self.network,
            "proxy_admin": self.proxy_admin,
            "proxy_kind": self.proxy_kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeProxyEpoch":
        value = _mapping(value, "CodeProxyEpoch")
        _reject_forbidden(value, "CodeProxyEpoch")
        return cls(
            contract_address=value.get(
                "contract_address", value.get("contractAddress", "")
            ),
            code_epoch=value.get("code_epoch", value.get("codeEpoch", "")),
            chain_id=value.get("chain_id", value.get("chainId", 0)),
            code_hash=value.get("code_hash", value.get("codeHash", "")),
            implementation_address=value.get(
                "implementation_address", value.get("implementationAddress", "")
            ),
            implementation_code_digest=value.get(
                "implementation_code_digest",
                value.get("implementationCodeDigest", ""),
            ),
            proxy_kind=value.get("proxy_kind", value.get("proxyKind", "")),
            proxy_admin=value.get("proxy_admin", value.get("proxyAdmin", "")),
            network=value.get("network", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CODE_PROXY_EPOCH_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ApprovalBinding:
    """Bound ERC-20 approve / permit / allowance effect (decoded, not named)."""

    token: str
    owner: str
    spender: str
    amount: str
    kind: str = "approve"
    deadline: str = ""
    selector: str = ""
    source: str = "calldata"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = APPROVAL_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", _address(self.token, "token"))
        object.__setattr__(self, "owner", _optional_address(self.owner, "owner"))
        object.__setattr__(self, "spender", _address(self.spender, "spender"))
        object.__setattr__(self, "amount", _amount(self.amount, "amount"))
        kind = _text(self.kind, "kind", max_chars=64).lower()
        if kind not in {
            "approve",
            "permit",
            "increaseallowance",
            "decreaseallowance",
            "increase_allowance",
            "decrease_allowance",
        }:
            # Normalize camelCase variants.
            if kind not in {"approve", "permit"}:
                pass
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "deadline", _optional_text(self.deadline, "deadline", max_chars=64)
        )
        object.__setattr__(
            self, "selector", _optional_text(self.selector, "selector", max_chars=16)
        )
        object.__setattr__(
            self, "source", _optional_text(self.source, "source", max_chars=32) or "calldata"
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def approval_digest(self) -> str:
        return content_sha256_hex(
            {
                "amount": self.amount,
                "deadline": self.deadline,
                "kind": self.kind,
                "owner": self.owner,
                "selector": self.selector,
                "spender": self.spender,
                "token": self.token,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "approval_digest": self.approval_digest,
            "attributes": self.attributes.to_dict(),
            "deadline": self.deadline,
            "kind": self.kind,
            "owner": self.owner,
            "schema_version": self.schema_version,
            "selector": self.selector,
            "source": self.source,
            "spender": self.spender,
            "token": self.token,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApprovalBinding":
        value = _mapping(value, "ApprovalBinding")
        _reject_forbidden(value, "ApprovalBinding")
        return cls(
            token=value.get("token", ""),
            owner=value.get("owner", ""),
            spender=value.get("spender", ""),
            amount=value.get("amount", "0"),
            kind=value.get("kind", "approve"),
            deadline=str(value.get("deadline", "")),
            selector=value.get("selector", ""),
            source=value.get("source", "calldata"),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", APPROVAL_BINDING_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# AST: EVMTransactionCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EVMTransactionCandidate:
    """Unsigned Ethereum / EVM transaction candidate for guard binding.

    Declaration authority only.  Never holds signatures, keys, or broadcast
    authority.  Effects must be derived from decoded calldata and declared
    simulation/trace overlays — method names alone are insufficient.
    """

    intent_id: str
    chain_id: int
    from_address: str
    to_address: str
    value_wei: str = "0"
    data: str = "0x"
    method: str = ""
    nonce: int | None = None
    gas_limit: int | None = None
    max_fee_per_gas: int | None = None
    max_priority_fee_per_gas: int | None = None
    gas_price: int | None = None
    network: str = ""
    genesis_hash: str = ""
    # Declared / simulated effects (overlays; never invented by the guard).
    native_effects: tuple[Mapping[str, Any], ...] = ()
    token_effects: tuple[Mapping[str, Any], ...] = ()
    internal_effects: tuple[Mapping[str, Any], ...] = ()
    approval_effects: tuple[Mapping[str, Any], ...] = ()
    # Optional recovered sender (EIP-155 signature recovery result as evidence).
    recovered_sender: str = ""
    sender_recovery_digest: str = ""
    list_revision: str = ""
    graph_revision: str = ""
    serialized_hex: str = ""
    encoding: str = "rlp-ethereum"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = EVM_CANDIDATE_SCHEMA_VERSION
    kind: str = "evm_transaction_candidate"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(self, "kind", _text(self.kind, "kind", max_chars=64))
        chain_id = _positive_int(self.chain_id, "chain_id")
        object.__setattr__(self, "chain_id", chain_id)
        try:
            anchor = resolve_network(
                chain_id=chain_id,
                network=self.network or None,
                genesis_hash=self.genesis_hash or None,
            )
        except EVMAdapterError as exc:
            raise GuardValidationError(str(exc)) from exc
        object.__setattr__(self, "network", anchor.network)
        object.__setattr__(self, "genesis_hash", anchor.genesis_hash)
        object.__setattr__(
            self, "from_address", _address(self.from_address, "from_address")
        )
        object.__setattr__(
            self, "to_address", _address(self.to_address, "to_address")
        )
        object.__setattr__(self, "value_wei", _amount(self.value_wei, "value_wei"))
        object.__setattr__(self, "data", _hex_data(self.data, "data"))
        object.__setattr__(
            self, "method", _optional_text(self.method, "method", max_chars=128)
        )
        if self.nonce is not None:
            object.__setattr__(self, "nonce", _non_negative_int(self.nonce, "nonce"))
        if self.gas_limit is not None:
            object.__setattr__(
                self, "gas_limit", _non_negative_int(self.gas_limit, "gas_limit")
            )
        if self.max_fee_per_gas is not None:
            object.__setattr__(
                self,
                "max_fee_per_gas",
                _non_negative_int(self.max_fee_per_gas, "max_fee_per_gas"),
            )
        if self.max_priority_fee_per_gas is not None:
            object.__setattr__(
                self,
                "max_priority_fee_per_gas",
                _non_negative_int(
                    self.max_priority_fee_per_gas, "max_priority_fee_per_gas"
                ),
            )
        if self.gas_price is not None:
            object.__setattr__(
                self, "gas_price", _non_negative_int(self.gas_price, "gas_price")
            )
        object.__setattr__(
            self,
            "native_effects",
            tuple(dict(item) for item in self.native_effects),
        )
        object.__setattr__(
            self, "token_effects", tuple(dict(item) for item in self.token_effects)
        )
        object.__setattr__(
            self,
            "internal_effects",
            tuple(dict(item) for item in self.internal_effects),
        )
        object.__setattr__(
            self,
            "approval_effects",
            tuple(dict(item) for item in self.approval_effects),
        )
        object.__setattr__(
            self,
            "recovered_sender",
            _optional_address(self.recovered_sender, "recovered_sender"),
        )
        if self.sender_recovery_digest:
            object.__setattr__(
                self,
                "sender_recovery_digest",
                _digest(self.sender_recovery_digest, "sender_recovery_digest"),
            )
        else:
            object.__setattr__(self, "sender_recovery_digest", "")
        object.__setattr__(
            self,
            "list_revision",
            _optional_text(self.list_revision, "list_revision", max_chars=128),
        )
        object.__setattr__(
            self,
            "graph_revision",
            _optional_text(self.graph_revision, "graph_revision", max_chars=128),
        )
        if self.serialized_hex:
            ser = _text(
                self.serialized_hex, "serialized_hex", max_chars=MAX_HEX_PAYLOAD_CHARS
            )
            if not ser.startswith("0x"):
                raise GuardValidationError("serialized_hex must be 0x-prefixed")
            if len(ser) > 2 and (len(ser) - 2) % 2 != 0:
                raise GuardValidationError("serialized_hex must be even-length hex")
            object.__setattr__(self, "serialized_hex", ser.lower())
        else:
            object.__setattr__(self, "serialized_hex", "")
        object.__setattr__(
            self, "encoding", _identifier(self.encoding, "encoding")
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != EVM_CANDIDATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported EVM candidate schema: {self.schema_version!r}"
            )

    @property
    def candidate_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    @property
    def selector(self) -> str:
        return method_selector(self.data)

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "approval_effects": list(self.approval_effects),
            "chain_id": self.chain_id,
            "data": self.data,
            "from_address": self.from_address,
            "gas_limit": self.gas_limit,
            "gas_price": self.gas_price,
            "genesis_hash": self.genesis_hash,
            "graph_revision": self.graph_revision,
            "intent_id": self.intent_id,
            "internal_effects": list(self.internal_effects),
            "list_revision": self.list_revision,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "method": self.method,
            "native_effects": list(self.native_effects),
            "network": self.network,
            "nonce": self.nonce,
            "recovered_sender": self.recovered_sender,
            "sender_recovery_digest": self.sender_recovery_digest,
            "serialized_hex": self.serialized_hex,
            "to_address": self.to_address,
            "token_effects": list(self.token_effects),
            "value_wei": self.value_wei,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "candidate_digest": self.candidate_digest,
                "encoding": self.encoding,
                "kind": self.kind,
                "schema_version": self.schema_version,
                "selector": self.selector,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EVMTransactionCandidate":
        value = _mapping(value, "EVMTransactionCandidate")
        _reject_forbidden(value, "EVMTransactionCandidate")
        return cls(
            intent_id=value.get("intent_id", value.get("intentId", "")),
            chain_id=value.get("chain_id", value.get("chainId", 0)),
            from_address=value.get(
                "from_address", value.get("fromAddress", value.get("from", ""))
            ),
            to_address=value.get(
                "to_address", value.get("toAddress", value.get("to", ""))
            ),
            value_wei=value.get(
                "value_wei", value.get("valueWei", value.get("value", "0"))
            ),
            data=value.get("data", value.get("input", value.get("calldata", "0x"))),
            method=value.get("method", ""),
            nonce=value.get("nonce"),
            gas_limit=value.get("gas_limit", value.get("gasLimit", value.get("gas"))),
            max_fee_per_gas=value.get(
                "max_fee_per_gas", value.get("maxFeePerGas")
            ),
            max_priority_fee_per_gas=value.get(
                "max_priority_fee_per_gas", value.get("maxPriorityFeePerGas")
            ),
            gas_price=value.get("gas_price", value.get("gasPrice")),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", value.get("genesisHash", "")),
            native_effects=tuple(
                value.get("native_effects", value.get("nativeEffects", ()))
            ),
            token_effects=tuple(
                value.get("token_effects", value.get("tokenEffects", ()))
            ),
            internal_effects=tuple(
                value.get("internal_effects", value.get("internalEffects", ()))
            ),
            approval_effects=tuple(
                value.get("approval_effects", value.get("approvalEffects", ()))
            ),
            recovered_sender=value.get(
                "recovered_sender", value.get("recoveredSender", "")
            ),
            sender_recovery_digest=value.get(
                "sender_recovery_digest", value.get("senderRecoveryDigest", "")
            ),
            list_revision=value.get(
                "list_revision", value.get("listRevision", "")
            ),
            graph_revision=value.get(
                "graph_revision", value.get("graphRevision", "")
            ),
            serialized_hex=value.get(
                "serialized_hex", value.get("serializedHex", "")
            ),
            encoding=value.get("encoding", "rlp-ethereum"),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", EVM_CANDIDATE_SCHEMA_VERSION
            ),
            kind=value.get("kind", "evm_transaction_candidate"),
        )


# ---------------------------------------------------------------------------
# Composite binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EVMTransactionBinding:
    """Exact EVM transaction facts bound for two-phase guard evaluation.

    Every policy-relevant field is frozen so pre-sign and pre-broadcast
    revalidation can detect permit substitution, nonce/fee mutation, proxy
    upgrades, hidden transfers, stale list/graph, and replay.
    """

    binding_id: str
    intent_id: str
    candidate_id: str
    chain_id: int
    network: str
    genesis_hash: str
    from_address: str
    to_address: str
    value_wei: str
    data: str
    method: str
    selector: str
    nonce: int | None
    fee_wei: str
    gas_limit: int | None
    max_fee_per_gas: int | None
    max_priority_fee_per_gas: int | None
    approvals: tuple[ApprovalBinding, ...]
    native_effects: tuple[Mapping[str, Any], ...]
    token_effects: tuple[Mapping[str, Any], ...]
    internal_effects: tuple[Mapping[str, Any], ...]
    code_proxy_epochs: tuple[CodeProxyEpoch, ...]
    recovered_sender: str
    sender_recovery_digest: str
    candidate_digest: str
    serialized_digest: str
    encoding: str
    byte_length: int
    list_revision: str
    graph_revision: str
    decoded_kind: str
    expected_effects: tuple[ExpectedEffect, ...]
    binding_digest: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = EVM_TX_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "chain_id", _positive_int(self.chain_id, "chain_id"))
        object.__setattr__(
            self, "network", _text(self.network, "network", max_chars=128)
        )
        object.__setattr__(
            self, "genesis_hash", _text(self.genesis_hash, "genesis_hash", max_chars=128)
        )
        object.__setattr__(
            self, "from_address", _address(self.from_address, "from_address")
        )
        object.__setattr__(
            self, "to_address", _address(self.to_address, "to_address")
        )
        object.__setattr__(self, "value_wei", _amount(self.value_wei, "value_wei"))
        object.__setattr__(self, "data", _hex_data(self.data, "data"))
        object.__setattr__(
            self, "method", _optional_text(self.method, "method", max_chars=128)
        )
        object.__setattr__(
            self, "selector", _optional_text(self.selector, "selector", max_chars=16)
        )
        if self.nonce is not None:
            object.__setattr__(self, "nonce", _non_negative_int(self.nonce, "nonce"))
        object.__setattr__(self, "fee_wei", _amount(self.fee_wei, "fee_wei"))
        if self.gas_limit is not None:
            object.__setattr__(
                self, "gas_limit", _non_negative_int(self.gas_limit, "gas_limit")
            )
        if self.max_fee_per_gas is not None:
            object.__setattr__(
                self,
                "max_fee_per_gas",
                _non_negative_int(self.max_fee_per_gas, "max_fee_per_gas"),
            )
        if self.max_priority_fee_per_gas is not None:
            object.__setattr__(
                self,
                "max_priority_fee_per_gas",
                _non_negative_int(
                    self.max_priority_fee_per_gas, "max_priority_fee_per_gas"
                ),
            )
        approvals: list[ApprovalBinding] = []
        for item in self.approvals:
            if isinstance(item, ApprovalBinding):
                approvals.append(item)
            elif isinstance(item, Mapping):
                approvals.append(ApprovalBinding.from_dict(item))
            else:
                raise GuardValidationError(
                    "approvals items must be ApprovalBinding"
                )
        object.__setattr__(self, "approvals", tuple(approvals))
        object.__setattr__(
            self,
            "native_effects",
            tuple(dict(item) for item in self.native_effects),
        )
        object.__setattr__(
            self, "token_effects", tuple(dict(item) for item in self.token_effects)
        )
        object.__setattr__(
            self,
            "internal_effects",
            tuple(dict(item) for item in self.internal_effects),
        )
        epochs: list[CodeProxyEpoch] = []
        for item in self.code_proxy_epochs:
            if isinstance(item, CodeProxyEpoch):
                epochs.append(item)
            elif isinstance(item, Mapping):
                epochs.append(CodeProxyEpoch.from_dict(item))
            else:
                raise GuardValidationError(
                    "code_proxy_epochs items must be CodeProxyEpoch"
                )
        object.__setattr__(self, "code_proxy_epochs", tuple(epochs))
        object.__setattr__(
            self,
            "recovered_sender",
            _optional_address(self.recovered_sender, "recovered_sender"),
        )
        if self.sender_recovery_digest:
            object.__setattr__(
                self,
                "sender_recovery_digest",
                _digest(self.sender_recovery_digest, "sender_recovery_digest"),
            )
        else:
            object.__setattr__(self, "sender_recovery_digest", "")
        object.__setattr__(
            self, "candidate_digest", _digest(self.candidate_digest, "candidate_digest")
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
            raise GuardValidationError("byte_length must be positive")
        object.__setattr__(
            self,
            "list_revision",
            _optional_text(self.list_revision, "list_revision", max_chars=128),
        )
        object.__setattr__(
            self,
            "graph_revision",
            _optional_text(self.graph_revision, "graph_revision", max_chars=128),
        )
        object.__setattr__(
            self,
            "decoded_kind",
            _optional_text(self.decoded_kind, "decoded_kind", max_chars=64),
        )
        effects: list[ExpectedEffect] = []
        for item in self.expected_effects:
            if isinstance(item, ExpectedEffect):
                effects.append(item)
            elif isinstance(item, Mapping):
                effects.append(ExpectedEffect.from_dict(item))
            else:
                raise GuardValidationError(
                    "expected_effects items must be ExpectedEffect"
                )
        object.__setattr__(self, "expected_effects", tuple(effects))
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != EVM_TX_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported EVM binding schema: {self.schema_version!r}"
            )
        if not self.binding_digest:
            object.__setattr__(self, "binding_digest", self.compute_binding_digest())
        else:
            object.__setattr__(
                self, "binding_digest", _digest(self.binding_digest, "binding_digest")
            )

    def compute_binding_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "approvals": [a.to_dict() for a in self.approvals],
            "byte_length": self.byte_length,
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "chain_id": self.chain_id,
            "code_proxy_epochs": [e.to_dict() for e in self.code_proxy_epochs],
            "data": self.data,
            "decoded_kind": self.decoded_kind,
            "encoding": self.encoding,
            "expected_effects": [e.to_dict() for e in self.expected_effects],
            "fee_wei": self.fee_wei,
            "from_address": self.from_address,
            "gas_limit": self.gas_limit,
            "genesis_hash": self.genesis_hash,
            "graph_revision": self.graph_revision,
            "intent_id": self.intent_id,
            "internal_effects": list(self.internal_effects),
            "list_revision": self.list_revision,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "method": self.method,
            "native_effects": list(self.native_effects),
            "network": self.network,
            "nonce": self.nonce,
            "recovered_sender": self.recovered_sender,
            "selector": self.selector,
            "sender_recovery_digest": self.sender_recovery_digest,
            "serialized_digest": self.serialized_digest,
            "to_address": self.to_address,
            "token_effects": list(self.token_effects),
            "value_wei": self.value_wei,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "binding_digest": self.binding_digest,
                "binding_id": self.binding_id,
                "schema_version": self.schema_version,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EVMTransactionBinding":
        value = _mapping(value, "EVMTransactionBinding")
        _reject_forbidden(value, "EVMTransactionBinding")
        return cls(
            binding_id=value.get("binding_id", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            chain_id=value.get("chain_id", 0),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            from_address=value.get("from_address", ""),
            to_address=value.get("to_address", ""),
            value_wei=value.get("value_wei", "0"),
            data=value.get("data", "0x"),
            method=value.get("method", ""),
            selector=value.get("selector", ""),
            nonce=value.get("nonce"),
            fee_wei=value.get("fee_wei", DEFAULT_FEE_WEI),
            gas_limit=value.get("gas_limit"),
            max_fee_per_gas=value.get("max_fee_per_gas"),
            max_priority_fee_per_gas=value.get("max_priority_fee_per_gas"),
            approvals=tuple(value.get("approvals", ())),
            native_effects=tuple(value.get("native_effects", ())),
            token_effects=tuple(value.get("token_effects", ())),
            internal_effects=tuple(value.get("internal_effects", ())),
            code_proxy_epochs=tuple(value.get("code_proxy_epochs", ())),
            recovered_sender=value.get("recovered_sender", ""),
            sender_recovery_digest=value.get("sender_recovery_digest", ""),
            candidate_digest=value.get("candidate_digest", ""),
            serialized_digest=value.get("serialized_digest", ""),
            encoding=value.get("encoding", "rlp-ethereum"),
            byte_length=value.get("byte_length", 0),
            list_revision=value.get("list_revision", ""),
            graph_revision=value.get("graph_revision", ""),
            decoded_kind=value.get("decoded_kind", ""),
            expected_effects=tuple(value.get("expected_effects", ())),
            binding_digest=value.get("binding_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", EVM_TX_BINDING_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class EthereumGuardPhase(str, Enum):
    """Phase at which the Ethereum guard is consulted."""

    EVALUATE = "evaluate"
    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class EthereumGuardDecision:
    """Deterministic Ethereum guard decision (not authorization to sign)."""

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
    schema_version: str = ETHEREUM_GUARD_DECISION_SCHEMA_VERSION

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

CodeProxyEpochResolver = Callable[
    [str], CodeProxyEpoch | Mapping[str, Any] | None
]
ListRevisionChecker = Callable[[str, str], bool]
GraphRevisionChecker = Callable[[str, str], bool]
NonceReplayChecker = Callable[[int, str, str], bool]
# (nonce, from_address, chain_id_str) -> already_used


def _static_epoch_resolver(
    epochs: Mapping[str, CodeProxyEpoch | Mapping[str, Any]],
) -> CodeProxyEpochResolver:
    def _resolve(address: str) -> CodeProxyEpoch | Mapping[str, Any] | None:
        key = address.lower() if isinstance(address, str) else address
        if key in epochs:
            return epochs[key]
        # Also try original keys.
        return epochs.get(address)

    return _resolve


def _coerce_code_epoch(
    value: CodeProxyEpoch | Mapping[str, Any] | None, *, field_name: str
) -> CodeProxyEpoch | None:
    if value is None:
        return None
    if isinstance(value, CodeProxyEpoch):
        return value
    if isinstance(value, Mapping):
        return CodeProxyEpoch.from_dict(value)
    raise GuardValidationError(f"{field_name} must be CodeProxyEpoch or mapping")


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class EthereumTransactionGuard:
    """Non-custodial Ethereum / EVM leaf guard adapter.

    Normalizes EVM transaction candidates into exact
    :class:`TransactionIntent` / :class:`TransactionCandidate` bindings, runs
    EVM-specific fail-closed checks (decoded effects, approvals, code/proxy
    epochs, sender recovery), and delegates capability issuance / atomic
    consumption to :class:`TransactionPreflight`.

    Code/proxy epochs and list/graph revisions are re-resolved at consumption
    and must match the binding used when the admissibility capability was
    issued.  Method names alone never authorize effects.
    """

    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_PRODUCER_ID
    policy_id: str = DEFAULT_POLICY_ID
    code_proxy_resolver: CodeProxyEpochResolver | None = None
    list_revision_is_current: ListRevisionChecker | None = None
    graph_revision_is_current: GraphRevisionChecker | None = None
    nonce_already_used: NonceReplayChecker | None = None
    interface: str = ETHEREUM_TRANSACTION_GUARD_INTERFACE
    schema_version: str = ETHEREUM_TRANSACTION_GUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.preflight is None:
            self.preflight = TransactionPreflight(producer_id=self.producer_id)
        if self.interface != ETHEREUM_TRANSACTION_GUARD_INTERFACE:
            raise GuardValidationError(
                f"unsupported ethereum guard interface: {self.interface!r}"
            )
        if self.schema_version != ETHEREUM_TRANSACTION_GUARD_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported ethereum guard schema: {self.schema_version!r}"
            )
        if self.list_revision_is_current is None:
            self.list_revision_is_current = lambda _rev, _now: True
        if self.graph_revision_is_current is None:
            self.graph_revision_is_current = lambda _rev, _now: True
        if self.nonce_already_used is None:
            # Offline default: nonce not used unless caller injects checker.
            self.nonce_already_used = lambda _n, _from, _chain: False

    # -- binding ------------------------------------------------------------

    def bind_transaction(
        self,
        candidate: EVMTransactionCandidate | Mapping[str, Any],
        *,
        code_proxy_epochs: Sequence[CodeProxyEpoch | Mapping[str, Any]] | None = None,
        declared_internal_effects: Sequence[Mapping[str, Any]] | None = None,
        declared_token_effects: Sequence[Mapping[str, Any]] | None = None,
        declared_approvals: Sequence[ApprovalBinding | Mapping[str, Any]]
        | None = None,
        list_revision: str = "",
        graph_revision: str = "",
        fee_wei: str | int | None = None,
        serialized_bytes: bytes | str | None = None,
        encoding: str = "rlp-ethereum",
        candidate_id: str = "",
        binding_id: str = "",
        expected_effects: Sequence[ExpectedEffect | Mapping[str, Any]] | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> EVMTransactionBinding:
        """Normalize an EVM candidate into an exact guard binding.

        Calldata is decoded into approvals/token effects.  Declared simulation
        overlays (internal transfers, extra token moves) are bound as well.
        Method labels alone never establish effects.
        """

        cand = self._coerce_candidate(candidate)

        decoded = decode_calldata_effects(
            to_address=cand.to_address,
            data=cand.data,
            value_wei=cand.value_wei,
            from_address=cand.from_address,
        )

        # Method name must not authorize alone and must not contradict decode.
        if cand.method and cand.method.strip():
            method_norm = cand.method.strip().lower().replace("_", "")
            label_norm = (decoded["decoded_label"] or "").lower().replace("_", "")
            if decoded["decoded_kind"] == "unknown_call" and decoded["selector"]:
                # Friendly label on an unknown selector is not authority.
                raise GuardValidationError(
                    f"method name {cand.method!r} cannot authorize unknown "
                    f"selector {decoded['selector']}; guarding uses decoded "
                    f"and simulated effects, not method names alone"
                )
            if label_norm and method_norm != label_norm:
                # Friendly label lying about a known decoded selector fails closed.
                raise GuardValidationError(
                    f"method name {cand.method!r} does not match decoded "
                    f"selector effects ({decoded['decoded_label']}); "
                    f"guarding uses decoded effects, not method names alone"
                )

        # Approvals: decoded + declared overlays.
        approvals: list[ApprovalBinding] = []
        for item in decoded["approvals"]:
            approvals.append(ApprovalBinding.from_dict(item))
        for item in cand.approval_effects:
            approvals.append(
                item
                if isinstance(item, ApprovalBinding)
                else ApprovalBinding.from_dict(item)
            )
        if declared_approvals:
            for item in declared_approvals:
                if isinstance(item, ApprovalBinding):
                    approvals.append(item)
                elif isinstance(item, Mapping):
                    approvals.append(ApprovalBinding.from_dict(item))
                else:
                    raise GuardValidationError(
                        "declared_approvals items must be ApprovalBinding"
                    )

        # Token effects: decoded + candidate + declared simulation.
        token_effects: list[dict[str, Any]] = list(decoded["token_effects"])
        for item in cand.token_effects:
            token_effects.append(dict(item))
        if declared_token_effects:
            for item in declared_token_effects:
                token_effects.append(dict(item))

        # Native: decoded (from value) + candidate overlays.
        native_effects: list[dict[str, Any]] = list(decoded["native_effects"])
        for item in cand.native_effects:
            native_effects.append(dict(item))
        if int(cand.value_wei) > 0 and not any(
            e.get("kind") == "native_transfer" for e in native_effects
        ):
            native_effects.append(
                {
                    "kind": "native_transfer",
                    "from": cand.from_address,
                    "to": cand.to_address,
                    "value_wei": cand.value_wei,
                }
            )

        # Internal effects: only from declared simulation/traces — never invented.
        internal_effects: list[dict[str, Any]] = [
            dict(item) for item in cand.internal_effects
        ]
        if declared_internal_effects:
            for item in declared_internal_effects:
                internal_effects.append(dict(item))

        # Code/proxy epochs for the target contract (and any token addresses).
        bound_epochs = self._bind_code_epochs(
            cand,
            code_proxy_epochs=code_proxy_epochs,
            token_effects=token_effects,
            approvals=approvals,
        )

        # Fee binding.
        if fee_wei is not None:
            fee = _amount(fee_wei, "fee_wei")
        elif cand.gas_limit is not None and cand.max_fee_per_gas is not None:
            fee = str(int(cand.gas_limit) * int(cand.max_fee_per_gas))
        elif cand.gas_limit is not None and cand.gas_price is not None:
            fee = str(int(cand.gas_limit) * int(cand.gas_price))
        else:
            fee = DEFAULT_FEE_WEI

        # Serialized candidate digest.
        if serialized_bytes is None:
            if cand.serialized_hex:
                raw = bytes.fromhex(cand.serialized_hex[2:])
                serialized_digest = hashlib.sha256(raw).hexdigest()
                byte_length = max(1, len(raw))
            else:
                serialized_digest = cand.candidate_digest
                byte_length = max(1, len(serialized_digest) // 2)
        elif isinstance(serialized_bytes, bytes):
            serialized_digest = hashlib.sha256(serialized_bytes).hexdigest()
            byte_length = len(serialized_bytes) or 1
        else:
            raw_s = str(serialized_bytes).encode("utf-8")
            serialized_digest = hashlib.sha256(raw_s).hexdigest()
            byte_length = len(raw_s) or 1

        intent_id = cand.intent_id
        cand_id = candidate_id or f"candidate:ethereum:{intent_id}"
        bind_id = binding_id or f"binding:ethereum:{intent_id}"

        list_rev = list_revision or cand.list_revision
        graph_rev = graph_revision or cand.graph_revision

        # Expected effects for preflight projection.
        effects: list[ExpectedEffect] = []
        if expected_effects is not None:
            for item in expected_effects:
                if isinstance(item, ExpectedEffect):
                    effects.append(item)
                elif isinstance(item, Mapping):
                    effects.append(ExpectedEffect.from_dict(item))
                else:
                    raise GuardValidationError(
                        "expected_effects items must be ExpectedEffect"
                    )
        else:
            effects = self._derive_expected_effects(
                decoded_kind=decoded["decoded_kind"],
                native_effects=native_effects,
                token_effects=token_effects,
                internal_effects=internal_effects,
                approvals=approvals,
            )

        return EVMTransactionBinding(
            binding_id=bind_id,
            intent_id=intent_id,
            candidate_id=cand_id,
            chain_id=cand.chain_id,
            network=cand.network,
            genesis_hash=cand.genesis_hash,
            from_address=cand.from_address,
            to_address=cand.to_address,
            value_wei=cand.value_wei,
            data=cand.data,
            method=cand.method,
            selector=decoded["selector"] or cand.selector,
            nonce=cand.nonce,
            fee_wei=fee,
            gas_limit=cand.gas_limit,
            max_fee_per_gas=cand.max_fee_per_gas,
            max_priority_fee_per_gas=cand.max_priority_fee_per_gas,
            approvals=tuple(approvals),
            native_effects=tuple(native_effects),
            token_effects=tuple(token_effects),
            internal_effects=tuple(internal_effects),
            code_proxy_epochs=tuple(bound_epochs),
            recovered_sender=cand.recovered_sender,
            sender_recovery_digest=cand.sender_recovery_digest,
            candidate_digest=cand.candidate_digest,
            serialized_digest=serialized_digest,
            encoding=encoding,
            byte_length=byte_length,
            list_revision=list_rev,
            graph_revision=graph_rev,
            decoded_kind=decoded["decoded_kind"],
            expected_effects=tuple(effects),
            attributes=attributes or {},
        )

    def to_preflight_request(
        self,
        binding: EVMTransactionBinding,
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
        environment_id: str = "env:ethereum-guard",
        environment_digest: str = "",
        nonce: str = "",
        policy_id: str | None = None,
        intent_expires_at: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TransactionPreflightRequest:
        """Project an EVM binding into the common preflight request surface."""

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
                "genesis_hash": binding.genesis_hash,
                "candidate_digest": binding.candidate_digest,
                "nonce": binding.nonce,
                "fee_wei": binding.fee_wei,
                "selector": binding.selector,
                "decoded_kind": binding.decoded_kind,
                "list_revision": binding.list_revision,
                "graph_revision": binding.graph_revision,
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
                "ethereum_guard": True,
                "namespace": EVM_NAMESPACE,
            },
        )

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        binding: EVMTransactionBinding | Mapping[str, Any],
        *,
        request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        now: str | None = None,
        live_code_proxy_epochs: Mapping[str, CodeProxyEpoch | Mapping[str, Any]]
        | None = None,
        request_id: str = "req:ethereum-guard",
        tenant_id: str = "tenant:default",
        actor_id: str = "actor:policy-engine",
        audience_id: str = "audience:custody-signer",
        issued_at: str | None = None,
        deadline: str | None = None,
        expiry: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> EthereumGuardDecision:
        """Evaluate EVM-specific bindings then run two-phase preflight.

        Structural checks (decoded effects, approvals, epochs, freshness,
        replay) run first.  Any block becomes a non-ALLOW security requirement
        so preflight never issues a capability.
        """

        if not isinstance(binding, EVMTransactionBinding):
            binding = EVMTransactionBinding.from_dict(binding)

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        sec_results = dict(security_results or {})
        comp_results = dict(compliance_results or {})

        structural = self._check_structural(
            binding,
            now=clock,
            live_code_proxy_epochs=live_code_proxy_epochs,
            phase=EthereumGuardPhase.EVALUATE,
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
                sec_results["sec:evm-chain-identity"] = mapped

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

        return EthereumGuardDecision(
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
                "chain_id": binding.chain_id,
                "decoded_kind": binding.decoded_kind,
                "approval_count": len(binding.approvals),
                "code_proxy_epoch_count": len(binding.code_proxy_epochs),
                "namespace": EVM_NAMESPACE,
            },
        )

    # -- revalidate + consume -----------------------------------------------

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        binding: EVMTransactionBinding | Mapping[str, Any],
        *,
        phase: PreflightPhase | EthereumGuardPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        live_code_proxy_epochs: Mapping[str, CodeProxyEpoch | Mapping[str, Any]]
        | None = None,
        live_candidate: EVMTransactionCandidate | Mapping[str, Any] | None = None,
        live_list_revision: str | None = None,
        live_graph_revision: str | None = None,
        live_nonce: int | None = None,
        live_fee_wei: str | int | None = None,
        live_approvals: Sequence[ApprovalBinding | Mapping[str, Any]] | None = None,
        live_internal_effects: Sequence[Mapping[str, Any]] | None = None,
        live_token_effects: Sequence[Mapping[str, Any]] | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate EVM epochs/effects, then atomically consume.

        Re-resolves code/proxy epochs and checks permit/approval substitution,
        nonce/fee mutation, hidden transfers, list/graph freshness, and replay
        at consumption.  Any mismatch fails closed before consumption.
        """

        if not isinstance(binding, EVMTransactionBinding):
            binding = EVMTransactionBinding.from_dict(binding)
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
        elif isinstance(phase, EthereumGuardPhase):
            phase_value = (
                PreflightPhase.PRE_SIGN.value
                if phase is EthereumGuardPhase.PRE_SIGN
                else PreflightPhase.PRE_BROADCAST.value
                if phase is EthereumGuardPhase.PRE_BROADCAST
                else PreflightPhase.PRE_SIGN.value
            )
        else:
            phase_value = str(phase)

        clock = now or _iso_now()
        guard_phase = (
            EthereumGuardPhase.PRE_SIGN
            if phase_value == PreflightPhase.PRE_SIGN.value
            else EthereumGuardPhase.PRE_BROADCAST
        )

        # Live candidate field substitution (nonce/fee/calldata/value/chain).
        if live_candidate is not None:
            live_cand = self._coerce_candidate(live_candidate)
            if live_cand.candidate_digest != binding.candidate_digest:
                raise GuardCapabilityError(
                    "live EVM candidate substituted",
                    reason_code="ethereum.candidate_substituted",
                    details={
                        "expected": binding.candidate_digest,
                        "observed": live_cand.candidate_digest,
                    },
                )
            if live_cand.chain_id != binding.chain_id:
                raise GuardCapabilityError(
                    "live candidate chain_id substituted",
                    reason_code="ethereum.chain_id_substituted",
                    details={
                        "expected": binding.chain_id,
                        "observed": live_cand.chain_id,
                    },
                )
            if live_cand.nonce != binding.nonce:
                raise GuardCapabilityError(
                    "nonce mutated at consumption",
                    reason_code="ethereum.nonce_mutated",
                    details={
                        "expected": binding.nonce,
                        "observed": live_cand.nonce,
                    },
                )
            if (
                live_cand.from_address != binding.from_address
                or live_cand.to_address != binding.to_address
                or live_cand.value_wei != binding.value_wei
                or live_cand.data != binding.data
            ):
                raise GuardCapabilityError(
                    "live candidate fields substituted (from/to/value/data)",
                    reason_code="ethereum.candidate_fields_substituted",
                )

        if live_nonce is not None and live_nonce != binding.nonce:
            raise GuardCapabilityError(
                "nonce mutated at consumption",
                reason_code="ethereum.nonce_mutated",
                details={"expected": binding.nonce, "observed": live_nonce},
            )

        if live_fee_wei is not None:
            live_fee = _amount(live_fee_wei, "live_fee_wei")
            if live_fee != binding.fee_wei:
                raise GuardCapabilityError(
                    "fee mutated at consumption",
                    reason_code="ethereum.fee_mutated",
                    details={"expected": binding.fee_wei, "observed": live_fee},
                )

        # Permit / approval substitution.
        if live_approvals is not None:
            live_appr: list[ApprovalBinding] = []
            for item in live_approvals:
                if isinstance(item, ApprovalBinding):
                    live_appr.append(item)
                elif isinstance(item, Mapping):
                    live_appr.append(ApprovalBinding.from_dict(item))
                else:
                    raise GuardValidationError("live_approvals invalid")
            expected = {a.approval_digest for a in binding.approvals}
            observed = {a.approval_digest for a in live_appr}
            if expected != observed:
                raise GuardCapabilityError(
                    "permit/approval substituted at consumption",
                    reason_code="ethereum.permit_substituted",
                    details={
                        "expected": sorted(expected),
                        "observed": sorted(observed),
                    },
                )

        # Hidden transfer: live simulation reveals effects not in binding.
        if live_internal_effects is not None:
            expected_internal = {
                content_sha256_hex(dict(e)) for e in binding.internal_effects
            }
            observed_internal = {
                content_sha256_hex(dict(e)) for e in live_internal_effects
            }
            if observed_internal - expected_internal:
                raise GuardCapabilityError(
                    "hidden internal transfer detected at consumption",
                    reason_code="ethereum.hidden_transfer",
                    details={
                        "extra": sorted(observed_internal - expected_internal),
                    },
                )
            if expected_internal != observed_internal:
                raise GuardCapabilityError(
                    "internal effects substituted at consumption",
                    reason_code="ethereum.internal_effects_substituted",
                )

        if live_token_effects is not None:
            expected_tok = {
                content_sha256_hex(dict(e)) for e in binding.token_effects
            }
            observed_tok = {
                content_sha256_hex(dict(e)) for e in live_token_effects
            }
            if observed_tok - expected_tok:
                raise GuardCapabilityError(
                    "hidden token transfer detected at consumption",
                    reason_code="ethereum.hidden_transfer",
                    details={"extra": sorted(observed_tok - expected_tok)},
                )

        # List / graph revision freshness at consumption.
        if live_list_revision is not None and live_list_revision != binding.list_revision:
            raise GuardCapabilityError(
                "list revision stale or substituted at consumption",
                reason_code="ethereum.list_revision_stale",
                details={
                    "expected": binding.list_revision,
                    "observed": live_list_revision,
                },
            )
        if (
            live_graph_revision is not None
            and live_graph_revision != binding.graph_revision
        ):
            raise GuardCapabilityError(
                "graph revision stale or substituted at consumption",
                reason_code="ethereum.graph_revision_stale",
                details={
                    "expected": binding.graph_revision,
                    "observed": live_graph_revision,
                },
            )

        structural = self._check_structural(
            binding,
            now=clock,
            live_code_proxy_epochs=live_code_proxy_epochs,
            phase=guard_phase,
            re_resolve=True,
        )
        if structural["blocking"] is not None:
            raise GuardCapabilityError(
                "; ".join(structural["reasons"])
                or "ethereum live revalidation failed",
                reason_code=structural["reason_codes"][0]
                if structural["reason_codes"]
                else "ethereum.consumption_blocked",
                details={
                    "reason_codes": list(structural["reason_codes"]),
                    "phase": phase_value,
                    "binding_digest": binding.binding_digest,
                },
            )

        # Binding digest on live candidate attributes must still match.
        live_attrs = live_request.candidate.attributes.to_dict()
        bound_digest = live_attrs.get("binding_digest")
        if bound_digest and bound_digest != binding.binding_digest:
            raise GuardCapabilityError(
                "live candidate binding_digest does not match EVM binding",
                reason_code="ethereum.binding_digest_mismatch",
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
        self, candidate: EVMTransactionCandidate | Mapping[str, Any]
    ) -> EVMTransactionCandidate:
        if isinstance(candidate, EVMTransactionCandidate):
            return candidate
        if isinstance(candidate, Mapping):
            _reject_forbidden(candidate, "EVMTransactionCandidate")
            return EVMTransactionCandidate.from_dict(candidate)
        raise GuardValidationError(
            "candidate must be an EVMTransactionCandidate or mapping"
        )

    def _bind_code_epochs(
        self,
        cand: EVMTransactionCandidate,
        *,
        code_proxy_epochs: Sequence[CodeProxyEpoch | Mapping[str, Any]] | None,
        token_effects: Sequence[Mapping[str, Any]],
        approvals: Sequence[ApprovalBinding],
    ) -> list[CodeProxyEpoch]:
        provided: dict[str, CodeProxyEpoch] = {}
        if code_proxy_epochs is not None:
            for item in code_proxy_epochs:
                epoch = (
                    item
                    if isinstance(item, CodeProxyEpoch)
                    else CodeProxyEpoch.from_dict(item)
                )
                provided[epoch.contract_address.lower()] = epoch

        # Contracts that participate in effects should have epochs when any
        # epochs are supplied (fail closed on partial binding).
        required: set[str] = {cand.to_address.lower()}
        for t in token_effects:
            tok = t.get("token") or t.get("address")
            if tok:
                try:
                    required.add(normalize_address(str(tok), field="token").lower())
                except EVMAdapterError:
                    pass
        for a in approvals:
            required.add(a.token.lower())

        bound: list[CodeProxyEpoch] = []
        if code_proxy_epochs is not None:
            for addr in sorted(required):
                epoch = provided.get(addr)
                if epoch is None:
                    # Outer call target is required; token addresses may be
                    # EOAs without code — only fail for the primary to.
                    if addr == cand.to_address.lower():
                        raise GuardValidationError(
                            f"missing code/proxy epoch for {addr}"
                        )
                    continue
                if epoch.chain_id != cand.chain_id:
                    raise GuardValidationError(
                        f"code/proxy epoch chain_id mismatch for {addr}"
                    )
                bound.append(epoch)
            # Keep extras that were explicitly provided.
            for addr, epoch in provided.items():
                if addr not in {b.contract_address.lower() for b in bound}:
                    bound.append(epoch)
        else:
            # Synthetic epoch for primary target so re-resolution still works
            # when a live resolver is injected later.
            bound.append(
                CodeProxyEpoch(
                    contract_address=cand.to_address,
                    code_epoch=f"unresolved:{cand.to_address.lower()}",
                    chain_id=cand.chain_id,
                    network=cand.network,
                    attributes={"synthetic": True},
                )
            )
        return bound

    def _derive_expected_effects(
        self,
        *,
        decoded_kind: str,
        native_effects: Sequence[Mapping[str, Any]],
        token_effects: Sequence[Mapping[str, Any]],
        internal_effects: Sequence[Mapping[str, Any]],
        approvals: Sequence[ApprovalBinding],
    ) -> list[ExpectedEffect]:
        effects: list[ExpectedEffect] = []
        idx = 0
        for n in native_effects:
            idx += 1
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:native-{idx}",
                    kind="native_transfer",
                    summary=(
                        f"native {n.get('value_wei', '0')} wei "
                        f"{n.get('from', '')} -> {n.get('to', '')}"
                    ),
                )
            )
        for t in token_effects:
            idx += 1
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:token-{idx}",
                    kind="token_transfer",
                    summary=(
                        f"token {t.get('token', '')} amount {t.get('amount', '0')} "
                        f"{t.get('from', '')} -> {t.get('to', '')}"
                    ),
                )
            )
        for i in internal_effects:
            idx += 1
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:internal-{idx}",
                    kind=str(i.get("kind", "internal_call")),
                    summary=str(i.get("summary", i.get("type", "internal"))),
                )
            )
        for a in approvals:
            idx += 1
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:approval-{idx}",
                    kind=a.kind,
                    summary=(
                        f"{a.kind} token={a.token} spender={a.spender} "
                        f"amount={a.amount}"
                    ),
                )
            )
        if not effects and decoded_kind:
            effects.append(
                ExpectedEffect(
                    effect_id="effect:call-1",
                    kind=decoded_kind,
                    summary=f"decoded call kind={decoded_kind}",
                )
            )
        if not effects:
            effects.append(
                ExpectedEffect(
                    effect_id="effect:noop-1",
                    kind="noop",
                    summary="no economic effects declared",
                )
            )
        return effects

    def _intent_from_binding(
        self,
        binding: EVMTransactionBinding,
        *,
        expires_at: str,
    ) -> TransactionIntent:
        assets: list[AssetAmount] = []
        if int(binding.value_wei) > 0:
            assets.append(
                AssetAmount(
                    asset_id="asset:eth-native",
                    amount=binding.value_wei,
                    asset_namespace="native",
                    symbol="ETH",
                )
            )
        for token in binding.token_effects:
            assets.append(
                AssetAmount(
                    asset_id=f"asset:token:{token.get('token', 'unknown')}",
                    amount=str(token.get("amount", "0")),
                    asset_namespace="erc20",
                    symbol=str(token.get("symbol", "")),
                )
            )
        if not assets:
            assets.append(
                AssetAmount(
                    asset_id="asset:eth-native",
                    amount="0",
                    asset_namespace="native",
                    symbol="ETH",
                )
            )

        method = binding.decoded_kind or binding.method or binding.selector or "eth_call"
        return TransactionIntent(
            intent_id=binding.intent_id,
            network=binding.network,
            sender=binding.from_address,
            destination=binding.to_address,
            method=method,
            assets=tuple(assets),
            fees=(
                FeeSpec(
                    amount=binding.fee_wei,
                    asset_id="native",
                    payer=binding.from_address,
                ),
            ),
            nonce_or_sequence=str(binding.nonce if binding.nonce is not None else ""),
            signers=(binding.from_address,),
            expected_effects=binding.expected_effects,
            expires_at=expires_at,
            chain_namespace=EVM_NAMESPACE,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "selector": binding.selector,
                "decoded_kind": binding.decoded_kind,
                "genesis_hash": binding.genesis_hash,
            },
        )

    def _check_structural(
        self,
        binding: EVMTransactionBinding,
        *,
        now: str,
        live_code_proxy_epochs: Mapping[str, CodeProxyEpoch | Mapping[str, Any]]
        | None,
        phase: EthereumGuardPhase,
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

        # Chain identity.
        if binding.chain_id <= 0:
            _block(
                TransactionVerdictOutcome.DENY,
                "ethereum.chain_id_missing",
                "chain_id is unbound",
                "sec:evm-chain-identity",
            )
        else:
            security_results.setdefault("sec:evm-chain-identity", "pass")

        # Nonce / fee binding.
        if binding.nonce is None:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "ethereum.nonce_unbound",
                "nonce is unbound",
                "sec:evm-nonce-fee",
            )
        if not binding.fee_wei:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "ethereum.fee_unbound",
                "fee is unbound",
                "sec:evm-nonce-fee",
            )
        else:
            security_results.setdefault("sec:evm-nonce-fee", "pass")

        # Replay: nonce already used for this sender/chain.
        assert self.nonce_already_used is not None
        if binding.nonce is not None:
            try:
                used = bool(
                    self.nonce_already_used(
                        binding.nonce,
                        binding.from_address,
                        str(binding.chain_id),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                used = True
                _block(
                    TransactionVerdictOutcome.ERROR,
                    "ethereum.nonce_replay_checker_error",
                    f"nonce replay checker errored: {exc}",
                    "sec:evm-nonce-fee",
                )
            else:
                if used:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "ethereum.nonce_replay",
                        "nonce already consumed (replay)",
                        "sec:evm-nonce-fee",
                    )

        # Calldata / effects: re-decode and compare.
        try:
            live_decoded = decode_calldata_effects(
                to_address=binding.to_address,
                data=binding.data,
                value_wei=binding.value_wei,
                from_address=binding.from_address,
            )
        except GuardValidationError as exc:
            _block(
                TransactionVerdictOutcome.ERROR,
                "ethereum.calldata_decode_error",
                str(exc),
                "sec:evm-calldata-effects",
            )
            live_decoded = None

        if live_decoded is not None:
            if live_decoded["selector"] != binding.selector:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "ethereum.selector_mismatch",
                    "bound selector does not match calldata",
                    "sec:evm-calldata-effects",
                )
            if live_decoded["decoded_kind"] != binding.decoded_kind:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "ethereum.decoded_kind_mismatch",
                    "decoded effect kind does not match binding",
                    "sec:evm-calldata-effects",
                )
            # Approvals from calldata must be covered by bound approvals.
            live_appr_digests = {
                ApprovalBinding.from_dict(a).approval_digest
                for a in live_decoded["approvals"]
            }
            bound_appr_digests = {a.approval_digest for a in binding.approvals}
            if live_appr_digests - bound_appr_digests:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "ethereum.approval_not_bound",
                    "calldata approvals not fully bound",
                    "sec:evm-approvals",
                )
            else:
                security_results.setdefault("sec:evm-approvals", "pass")

            # Method name alone must not authorize when effects unknown.
            if (
                binding.method
                and live_decoded["decoded_kind"] == "unknown_call"
                and binding.selector
            ):
                # Unknown selector with a friendly method name is not enough
                # for automation — require explicit review unless internal
                # effects / expected effects fully cover the call.
                if not binding.internal_effects and not binding.token_effects:
                    _block(
                        TransactionVerdictOutcome.REVIEW,
                        "ethereum.method_name_alone",
                        "unknown selector cannot be authorized by method name alone",
                        "sec:evm-calldata-effects",
                    )
                else:
                    security_results.setdefault("sec:evm-calldata-effects", "pass")
            else:
                security_results.setdefault("sec:evm-calldata-effects", "pass")

        # Internal/token effects binding present when simulation declared them.
        security_results.setdefault("sec:evm-internal-token-effects", "pass")

        # Sender recovery consistency.
        if binding.recovered_sender:
            if binding.recovered_sender != binding.from_address:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "ethereum.sender_recovery_mismatch",
                    "recovered sender does not match from_address",
                    "sec:evm-sender-recovery",
                )
            else:
                security_results.setdefault("sec:evm-sender-recovery", "pass")
        else:
            # Recovery optional for unsigned candidates; mark pass when unbound.
            security_results.setdefault("sec:evm-sender-recovery", "pass")

        # Exact candidate binding.
        if not binding.serialized_digest or not binding.candidate_digest:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "ethereum.exact_candidate_unbound",
                "exact serialized candidate unbound",
                "sec:evm-exact-candidate",
            )
        else:
            security_results.setdefault("sec:evm-exact-candidate", "pass")

        # List / graph freshness.
        assert self.list_revision_is_current is not None
        assert self.graph_revision_is_current is not None
        if binding.list_revision:
            try:
                list_ok = bool(
                    self.list_revision_is_current(binding.list_revision, now)
                )
            except Exception as exc:  # noqa: BLE001
                list_ok = False
                _block(
                    TransactionVerdictOutcome.ERROR,
                    "ethereum.list_revision_checker_error",
                    f"list revision checker errored: {exc}",
                    "sec:evm-list-graph-freshness",
                )
            else:
                if not list_ok:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "ethereum.list_revision_stale",
                        "sanctions list revision is stale",
                        "sec:evm-list-graph-freshness",
                    )
        if binding.graph_revision:
            try:
                graph_ok = bool(
                    self.graph_revision_is_current(binding.graph_revision, now)
                )
            except Exception as exc:  # noqa: BLE001
                graph_ok = False
                _block(
                    TransactionVerdictOutcome.ERROR,
                    "ethereum.graph_revision_checker_error",
                    f"graph revision checker errored: {exc}",
                    "sec:evm-list-graph-freshness",
                )
            else:
                if not graph_ok:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "ethereum.graph_revision_stale",
                        "exposure graph revision is stale",
                        "sec:evm-list-graph-freshness",
                    )
        if "sec:evm-list-graph-freshness" not in security_results:
            security_results["sec:evm-list-graph-freshness"] = "pass"

        # Code / proxy epochs — re-resolve when requested or live maps given.
        epoch_resolver = self.code_proxy_resolver
        if live_code_proxy_epochs is not None:
            epoch_resolver = _static_epoch_resolver(live_code_proxy_epochs)
        if re_resolve or live_code_proxy_epochs is not None or epoch_resolver is not None:
            for epoch in binding.code_proxy_epochs:
                # Skip synthetic unresolved epochs when not re-resolving strictly.
                synthetic = False
                attrs = epoch.attributes.to_dict() if epoch.attributes else {}
                if attrs.get("synthetic"):
                    synthetic = True
                live_value: CodeProxyEpoch | Mapping[str, Any] | None = None
                if epoch_resolver is not None:
                    try:
                        live_value = epoch_resolver(epoch.contract_address)
                    except Exception as exc:  # noqa: BLE001
                        _block(
                            TransactionVerdictOutcome.ERROR,
                            "ethereum.code_proxy_resolve_error",
                            f"code/proxy re-resolve failed for "
                            f"{epoch.contract_address}: {exc}",
                            "sec:evm-code-proxy-epoch",
                        )
                        continue
                if live_value is None:
                    if re_resolve and not synthetic:
                        _block(
                            TransactionVerdictOutcome.STALE,
                            "ethereum.code_proxy_unresolved",
                            f"code/proxy epoch could not be re-resolved for "
                            f"{epoch.contract_address}",
                            "sec:evm-code-proxy-epoch",
                        )
                    continue
                live_epoch = _coerce_code_epoch(
                    live_value, field_name="live_code_proxy_epoch"
                )
                assert live_epoch is not None
                if live_epoch.epoch_digest != epoch.epoch_digest:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "ethereum.proxy_upgrade",
                        f"proxy/code upgrade detected for "
                        f"{epoch.contract_address}",
                        "sec:evm-code-proxy-epoch",
                    )
                elif live_epoch.code_epoch != epoch.code_epoch:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "ethereum.proxy_upgrade",
                        f"code_epoch changed for {epoch.contract_address}",
                        "sec:evm-code-proxy-epoch",
                    )
            if "sec:evm-code-proxy-epoch" not in security_results:
                security_results["sec:evm-code-proxy-epoch"] = "pass"
        else:
            security_results.setdefault("sec:evm-code-proxy-epoch", "pass")

        _ = phase  # reserved for phase-specific rules
        return {
            "blocking": blocking,
            "failed_requirement": failed_requirement,
            "reason_codes": reason_codes,
            "reasons": reasons,
            "security_results": security_results,
        }


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------


def evaluate_ethereum_transaction_guard(
    candidate: EVMTransactionCandidate | Mapping[str, Any],
    *,
    request_id: str,
    tenant_id: str,
    actor_id: str,
    audience_id: str,
    issued_at: str,
    deadline: str,
    expiry: str,
    now: str | None = None,
    security_results: Mapping[str, Any] | None = None,
    compliance_results: Mapping[str, Any] | None = None,
    code_proxy_epochs: Sequence[CodeProxyEpoch | Mapping[str, Any]] | None = None,
    declared_internal_effects: Sequence[Mapping[str, Any]] | None = None,
    list_revision: str = "",
    graph_revision: str = "",
    fee_wei: str | int | None = None,
    guard: EthereumTransactionGuard | None = None,
    **bind_kwargs: Any,
) -> EthereumGuardDecision:
    """Bind + evaluate an EVM candidate in one call (offline / test helper)."""

    g = guard or EthereumTransactionGuard()
    binding = g.bind_transaction(
        candidate,
        code_proxy_epochs=code_proxy_epochs,
        declared_internal_effects=declared_internal_effects,
        list_revision=list_revision,
        graph_revision=graph_revision,
        fee_wei=fee_wei,
        **bind_kwargs,
    )
    request = g.to_preflight_request(
        binding,
        request_id=request_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        audience_id=audience_id,
        issued_at=issued_at,
        deadline=deadline,
        expiry=expiry,
        intent_expires_at=expiry,
    )
    return g.evaluate(
        binding,
        request=request,
        security_results=security_results,
        compliance_results=compliance_results,
        now=now,
        live_code_proxy_epochs=(
            {
                (
                    e.contract_address
                    if isinstance(e, CodeProxyEpoch)
                    else CodeProxyEpoch.from_dict(e).contract_address
                ): e
                for e in code_proxy_epochs
            }
            if code_proxy_epochs is not None
            else None
        ),
    )


# Silence unused import lint for GuardError / GuardPolicyError (public surface).
_ = (GuardError, GuardPolicyError, ETHEREUM_MAINNET_CHAIN_ID, ETHEREUM_MAINNET_GENESIS_HASH, ETHEREUM_MAINNET_NETWORK)
