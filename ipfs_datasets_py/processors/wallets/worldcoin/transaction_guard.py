"""Non-custodial Worldcoin / World Chain transaction guard (CRYPTOIR-G570).

Compose EVM transaction guarding for World Chain and add World ID
action/domain/nullifier/verifier, WLD, bridge, and Mini App transaction
bindings while preserving World ID-specific evidence boundaries.

Acceptance (fail-closed):

* World Chain ID, candidate bytes, WLD/native effects, verifier/proxy epoch,
  action/external-nullifier/domain, RP/app, bridge legs, proof age,
  list/graph/policy, and expected effects are bound.
* Replay/domain/nullifier/verifier/bridge/candidate substitution and stale
  evidence block.
* Proof success cannot bypass contract or sanctions policy.

This module never signs, broadcasts, or accepts bare booleans / caller
approval flags as authority.  Keys remain with an external custody system.
A valid World ID proof is evidence only — never payment authorization,
contract safety, or sanctions clearance.
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
    EVM_NAMESPACE,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_MAINNET_NETWORK,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
    WORLD_CHAIN_SEPOLIA_NETWORK,
    EVMAdapterError,
    content_sha256_hex as evm_content_sha256_hex,
    normalize_address,
    normalize_hash,
    normalize_hex_data,
    resolve_network,
)
from ipfs_datasets_py.logic.crypto_ir.adapters.worldcoin import (
    WLD_WORLD_CHAIN_MAINNET_ADDRESS,
    WORLD_ID_NULLIFIER_REF_PREFIX,
    WorldcoinAdapterError,
    is_world_chain_id,
    world_chain_settlement_layer,
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

WORLDCOIN_TRANSACTION_GUARD_INTERFACE: Final = "WorldcoinTransactionGuard@1"
WORLDCOIN_TRANSACTION_GUARD_SCHEMA_VERSION: Final = (
    "wallet-guard.worldcoin-transaction-guard/v1"
)
WORLD_CHAIN_CANDIDATE_SCHEMA_VERSION: Final = (
    "wallet-guard.world-chain-transaction-candidate/v1"
)
WORLD_ID_BINDING_SCHEMA_VERSION: Final = "wallet-guard.world-id-binding/v1"
VERIFIER_PROXY_EPOCH_SCHEMA_VERSION: Final = (
    "wallet-guard.worldcoin-verifier-proxy-epoch/v1"
)
BRIDGE_LEG_SCHEMA_VERSION: Final = "wallet-guard.worldcoin-bridge-leg/v1"
WORLDCOIN_TX_BINDING_SCHEMA_VERSION: Final = (
    "wallet-guard.worldcoin-transaction-binding/v1"
)
WORLDCOIN_GUARD_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.worldcoin-guard-decision/v1"
)

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-worldcoin-v1"
DEFAULT_POLICY_ID: Final = "policy:worldcoin-wallet-guard-v1"
DEFAULT_FEE_WEI: Final = "21000000000000"  # 21000 * 1 gwei placeholder

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_HEX_PAYLOAD_CHARS: Final = 1_048_576

# Default proof max age when proof_observed_at is bound (seconds).
DEFAULT_PROOF_MAX_AGE_SECONDS: Final = 900

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_DECIMAL_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")
_ADDRESS_RE: Final = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX_COMMITMENT_RE: Final = re.compile(
    r"^(?:0x)?[0-9a-fA-F]{64}$|^(?:sha256|keccak256|hmac-sha256):[0-9a-fA-F]{64}$"
)

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
        # Raw World ID private material (commitments/refs only).
        "nullifier",
        "raw_nullifier",
        "session_nullifier",
        "proof",
        "idkit_payload",
        "jwt",
        "rp_signature",
    }
)

_ALLOWED_ENVIRONMENTS: Final[frozenset[str]] = frozenset(
    {"production", "staging", "development", "test"}
)
_ALLOWED_PROTOCOL_VERSIONS: Final[frozenset[str]] = frozenset({"3.0", "4.0"})

DEFAULT_SECURITY_REQUIREMENTS: Final[tuple[str, ...]] = (
    "sec:world-chain-identity",
    "sec:world-chain-candidate-bytes",
    "sec:world-chain-effects",
    "sec:world-id-domain",
    "sec:world-id-nullifier",
    "sec:world-id-verifier-epoch",
    "sec:world-id-proof-freshness",
    "sec:worldcoin-bridge-legs",
)
DEFAULT_COMPLIANCE_REQUIREMENTS: Final[tuple[str, ...]] = (
    "comp:direct-sanctions",
    "comp:bounded-exposure",
    "comp:contract-safety",
)

# Explicit claims a World ID proof success is forbidden from implying.
PROOF_CANNOT_BYPASS: Final[tuple[str, ...]] = (
    "contract_safety",
    "sanctions_policy",
    "payment_authorization",
    "legal_identity",
    "account_control",
)


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


def _optional_timestamp(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _timestamp(value, name)


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardValidationError(f"{name} must be an integer")
    if value < 0:
        raise GuardValidationError(f"{name} must be non-negative")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.isdigit():
            parsed = int(value, 10)
            if parsed <= 0:
                raise GuardValidationError(f"{name} must be a positive integer")
            return parsed
        raise GuardValidationError(f"{name} must be a positive integer")
    if value <= 0:
        raise GuardValidationError(f"{name} must be a positive integer")
    return value


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
            f"{record_name} contains forbidden custody/approval/raw-proof "
            f"field(s): {', '.join(hit)}",
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


def _parse_iso(ts: str) -> datetime:
    text = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _is_expired(expiry: str, now: str) -> bool:
    return now > expiry


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


def _environment(value: Any) -> str:
    text = _text(value, "environment").lower()
    if text not in _ALLOWED_ENVIRONMENTS:
        raise GuardValidationError(
            "environment must be production, staging, development, or test"
        )
    return text


def _protocol_version(value: Any) -> str:
    text = _text(value, "protocol_version")
    if text not in _ALLOWED_PROTOCOL_VERSIONS:
        raise GuardValidationError("protocol_version must be 3.0 or 4.0")
    return text


def _commitment(value: Any, name: str) -> str:
    """Normalize a privacy-safe commitment; reject raw secret markers."""

    text = _text(value, name)
    lowered = text.lower()
    if lowered in {"null", "none", "undefined"}:
        raise GuardValidationError(f"{name} is not a valid commitment")
    if text.startswith(WORLD_ID_NULLIFIER_REF_PREFIX) or text.startswith(
        "worldid-nullifier-ref:"
    ):
        return text
    if _HEX_COMMITMENT_RE.fullmatch(text):
        if text.startswith("0x") or text.startswith("0X"):
            return f"sha256:{text[2:].lower()}"
        if ":" in text:
            scheme, body = text.split(":", 1)
            return f"{scheme.lower()}:{body.lower()}"
        return f"sha256:{text.lower()}"
    if len(text) >= 8:
        return text
    raise GuardValidationError(f"{name} must be a privacy-safe commitment or ref")


def _require_world_chain_id(chain_id: Any) -> int:
    cid = _positive_int(chain_id, "chain_id")
    if not is_world_chain_id(cid):
        raise GuardValidationError(
            f"chain_id must be World Chain 480 or 4801 (got {cid})"
        )
    return cid


# ---------------------------------------------------------------------------
# Supporting epoch / leg records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifierProxyEpoch:
    """Bound World ID verifier / proxy implementation epoch.

    Re-resolved at consumption.  An upgrade (code epoch / implementation
    digest / proxy admin change) invalidates prior permission.
    """

    verifier_id: str
    verifier_address: str
    code_epoch: str
    chain_id: int
    implementation_address: str = ""
    implementation_code_digest: str = ""
    proxy_kind: str = ""
    proxy_admin: str = ""
    network: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = VERIFIER_PROXY_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "verifier_id", _identifier(self.verifier_id, "verifier_id")
        )
        object.__setattr__(
            self, "verifier_address", _address(self.verifier_address, "verifier_address")
        )
        object.__setattr__(
            self, "code_epoch", _text(self.code_epoch, "code_epoch", max_chars=256)
        )
        object.__setattr__(self, "chain_id", _require_world_chain_id(self.chain_id))
        object.__setattr__(
            self,
            "implementation_address",
            _optional_address(self.implementation_address, "implementation_address"),
        )
        if self.implementation_code_digest:
            digest = _text(
                self.implementation_code_digest,
                "implementation_code_digest",
                max_chars=96,
            )
            if digest.startswith("sha256:"):
                digest = digest[len("sha256:") :]
            if not _SHA256_HEX_RE.fullmatch(digest):
                raise GuardValidationError(
                    "implementation_code_digest must be a SHA-256 hex digest"
                )
            object.__setattr__(self, "implementation_code_digest", digest)
        else:
            object.__setattr__(self, "implementation_code_digest", "")
        object.__setattr__(
            self, "proxy_kind", _optional_text(self.proxy_kind, "proxy_kind", max_chars=64)
        )
        object.__setattr__(
            self, "proxy_admin", _optional_address(self.proxy_admin, "proxy_admin")
        )
        anchor = resolve_network(chain_id=self.chain_id, network=self.network or None)
        object.__setattr__(self, "network", anchor.network)
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != VERIFIER_PROXY_EPOCH_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported verifier proxy epoch schema: {self.schema_version!r}"
            )

    @property
    def epoch_digest(self) -> str:
        return content_sha256_hex(
            {
                "chain_id": self.chain_id,
                "code_epoch": self.code_epoch,
                "implementation_address": self.implementation_address,
                "implementation_code_digest": self.implementation_code_digest,
                "proxy_admin": self.proxy_admin,
                "proxy_kind": self.proxy_kind,
                "verifier_address": self.verifier_address,
                "verifier_id": self.verifier_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "epoch_digest": self.epoch_digest,
            "implementation_address": self.implementation_address,
            "implementation_code_digest": self.implementation_code_digest,
            "network": self.network,
            "proxy_admin": self.proxy_admin,
            "proxy_kind": self.proxy_kind,
            "schema_version": self.schema_version,
            "verifier_address": self.verifier_address,
            "verifier_id": self.verifier_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerifierProxyEpoch":
        value = _mapping(value, "VerifierProxyEpoch")
        _reject_forbidden(value, "VerifierProxyEpoch")
        return cls(
            verifier_id=value.get("verifier_id", value.get("verifierId", "")),
            verifier_address=value.get(
                "verifier_address", value.get("verifierAddress", "")
            ),
            code_epoch=value.get("code_epoch", value.get("codeEpoch", "")),
            chain_id=value.get("chain_id", value.get("chainId", 0)),
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
                "schema_version", VERIFIER_PROXY_EPOCH_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class BridgeLegBinding:
    """Bound bridge leg for World Chain deposit/withdraw/message paths."""

    leg_id: str
    direction: str
    source_chain_id: str
    destination_chain_id: str
    bridge_contract: str = ""
    message_digest: str = ""
    asset_id: str = ""
    amount: str = "0"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BRIDGE_LEG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "leg_id", _identifier(self.leg_id, "leg_id"))
        direction = _text(self.direction, "direction", max_chars=32).lower()
        if direction not in {"deposit", "withdraw", "message"}:
            raise GuardValidationError(
                "bridge direction must be deposit, withdraw, or message"
            )
        object.__setattr__(self, "direction", direction)
        object.__setattr__(
            self,
            "source_chain_id",
            _text(str(self.source_chain_id), "source_chain_id", max_chars=64),
        )
        object.__setattr__(
            self,
            "destination_chain_id",
            _text(
                str(self.destination_chain_id), "destination_chain_id", max_chars=64
            ),
        )
        object.__setattr__(
            self,
            "bridge_contract",
            _optional_address(self.bridge_contract, "bridge_contract"),
        )
        if self.message_digest:
            object.__setattr__(
                self, "message_digest", _digest(self.message_digest, "message_digest")
            )
        else:
            object.__setattr__(self, "message_digest", "")
        object.__setattr__(
            self, "asset_id", _optional_text(self.asset_id, "asset_id", max_chars=128)
        )
        object.__setattr__(self, "amount", _amount(self.amount, "amount"))
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BRIDGE_LEG_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported bridge leg schema: {self.schema_version!r}"
            )

    @property
    def leg_digest(self) -> str:
        return content_sha256_hex(
            {
                "amount": self.amount,
                "asset_id": self.asset_id,
                "bridge_contract": self.bridge_contract,
                "destination_chain_id": self.destination_chain_id,
                "direction": self.direction,
                "leg_id": self.leg_id,
                "message_digest": self.message_digest,
                "source_chain_id": self.source_chain_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "asset_id": self.asset_id,
            "attributes": self.attributes.to_dict(),
            "bridge_contract": self.bridge_contract,
            "destination_chain_id": self.destination_chain_id,
            "direction": self.direction,
            "leg_digest": self.leg_digest,
            "leg_id": self.leg_id,
            "message_digest": self.message_digest,
            "schema_version": self.schema_version,
            "source_chain_id": self.source_chain_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BridgeLegBinding":
        value = _mapping(value, "BridgeLegBinding")
        _reject_forbidden(value, "BridgeLegBinding")
        return cls(
            leg_id=value.get("leg_id", value.get("legId", "")),
            direction=value.get("direction", ""),
            source_chain_id=value.get(
                "source_chain_id", value.get("sourceChainId", "")
            ),
            destination_chain_id=value.get(
                "destination_chain_id", value.get("destinationChainId", "")
            ),
            bridge_contract=value.get(
                "bridge_contract", value.get("bridgeContract", "")
            ),
            message_digest=value.get(
                "message_digest", value.get("messageDigest", "")
            ),
            asset_id=value.get("asset_id", value.get("assetId", "")),
            amount=value.get("amount", "0"),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", BRIDGE_LEG_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# AST: WorldChainTransactionCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorldChainTransactionCandidate:
    """Unsigned World Chain EVM transaction candidate (declaration authority).

    Composes EVM call semantics on World Chain only (chain ids 480 / 4801).
    Candidate bytes, native/WLD effects, nonce, fee, and calldata are bound
    for two-phase guard evaluation.
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
    network: str = ""
    genesis_hash: str = ""
    settlement_layer: str = ""
    # Declared economic effects (native + WLD transfers).
    native_effects: tuple[Mapping[str, Any], ...] = ()
    wld_effects: tuple[Mapping[str, Any], ...] = ()
    token_effects: tuple[Mapping[str, Any], ...] = ()
    serialized_hex: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = WORLD_CHAIN_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        chain_id = _require_world_chain_id(self.chain_id)
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
        settlement = self.settlement_layer or world_chain_settlement_layer(chain_id)
        object.__setattr__(
            self, "settlement_layer", _text(settlement, "settlement_layer")
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
        object.__setattr__(
            self,
            "native_effects",
            tuple(dict(item) for item in self.native_effects),
        )
        object.__setattr__(
            self, "wld_effects", tuple(dict(item) for item in self.wld_effects)
        )
        object.__setattr__(
            self, "token_effects", tuple(dict(item) for item in self.token_effects)
        )
        if self.serialized_hex:
            ser = _text(self.serialized_hex, "serialized_hex", max_chars=MAX_HEX_PAYLOAD_CHARS)
            if not ser.startswith("0x"):
                raise GuardValidationError("serialized_hex must be 0x-prefixed")
            if len(ser) > 2 and (len(ser) - 2) % 2 != 0:
                raise GuardValidationError("serialized_hex must be even-length hex")
            object.__setattr__(self, "serialized_hex", ser.lower())
        else:
            object.__setattr__(self, "serialized_hex", "")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != WORLD_CHAIN_CANDIDATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported World Chain candidate schema: {self.schema_version!r}"
            )

    @property
    def candidate_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "data": self.data,
            "from_address": self.from_address,
            "gas_limit": self.gas_limit,
            "genesis_hash": self.genesis_hash,
            "intent_id": self.intent_id,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "method": self.method,
            "native_effects": list(self.native_effects),
            "network": self.network,
            "nonce": self.nonce,
            "serialized_hex": self.serialized_hex,
            "settlement_layer": self.settlement_layer,
            "to_address": self.to_address,
            "token_effects": list(self.token_effects),
            "value_wei": self.value_wei,
            "wld_effects": list(self.wld_effects),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "candidate_digest": self.candidate_digest,
                "kind": "world_chain_transaction_candidate",
                "schema_version": self.schema_version,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorldChainTransactionCandidate":
        value = _mapping(value, "WorldChainTransactionCandidate")
        _reject_forbidden(value, "WorldChainTransactionCandidate")
        return cls(
            intent_id=value.get("intent_id", value.get("intentId", "")),
            chain_id=value.get("chain_id", value.get("chainId", 0)),
            from_address=value.get(
                "from_address", value.get("fromAddress", value.get("from", ""))
            ),
            to_address=value.get(
                "to_address", value.get("toAddress", value.get("to", ""))
            ),
            value_wei=value.get("value_wei", value.get("valueWei", value.get("value", "0"))),
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
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", value.get("genesisHash", "")),
            settlement_layer=value.get(
                "settlement_layer", value.get("settlementLayer", "")
            ),
            native_effects=tuple(value.get("native_effects", value.get("nativeEffects", ()))),
            wld_effects=tuple(value.get("wld_effects", value.get("wldEffects", ()))),
            token_effects=tuple(value.get("token_effects", value.get("tokenEffects", ()))),
            serialized_hex=value.get(
                "serialized_hex", value.get("serializedHex", "")
            ),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", WORLD_CHAIN_CANDIDATE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# AST: WorldIDBinding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorldIDBinding:
    """World ID action/domain/nullifier/verifier binding for transaction guard.

    Distinct from World Chain ledger authorization.  Holds privacy-safe
    commitments only — never raw nullifiers or proof bytes.  A successful
    proof verification does not authorize payment, contract safety, or
    sanctions clearance.
    """

    binding_id: str
    rp_id: str
    action: str
    environment: str
    nullifier_commitment: str
    app_id: str = ""
    protocol_version: str = "4.0"
    external_nullifier_domain: str = ""
    signal_hash_ref: str = ""
    challenge_id: str = ""
    verification_status: str = "verified"
    proof_observed_at: str = ""
    proof_max_age_seconds: int = DEFAULT_PROOF_MAX_AGE_SECONDS
    verifier_epoch: VerifierProxyEpoch | None = None
    mini_app_id: str = ""
    chain_id: int | None = None
    network: str = ""
    # Explicit boundary: proof evidence ≠ policy authorization.
    proof_implies_authorization: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = WORLD_ID_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(self, "rp_id", _text(self.rp_id, "rp_id", max_chars=256))
        object.__setattr__(self, "action", _text(self.action, "action", max_chars=256))
        object.__setattr__(self, "environment", _environment(self.environment))
        object.__setattr__(
            self,
            "nullifier_commitment",
            _commitment(self.nullifier_commitment, "nullifier_commitment"),
        )
        object.__setattr__(
            self, "app_id", _optional_text(self.app_id, "app_id", max_chars=256)
        )
        object.__setattr__(
            self, "protocol_version", _protocol_version(self.protocol_version)
        )
        domain = self.external_nullifier_domain
        if not domain:
            domain = "|".join(
                [
                    self.protocol_version,
                    self.environment,
                    self.rp_id,
                    self.app_id or "",
                    self.action,
                    str(self.chain_id) if self.chain_id is not None else "off-chain",
                ]
            )
        object.__setattr__(
            self,
            "external_nullifier_domain",
            _text(domain, "external_nullifier_domain", max_chars=1024),
        )
        object.__setattr__(
            self,
            "signal_hash_ref",
            _optional_text(self.signal_hash_ref, "signal_hash_ref", max_chars=256),
        )
        object.__setattr__(
            self,
            "challenge_id",
            _optional_text(self.challenge_id, "challenge_id", max_chars=256),
        )
        object.__setattr__(
            self,
            "verification_status",
            _text(self.verification_status, "verification_status", max_chars=64),
        )
        object.__setattr__(
            self,
            "proof_observed_at",
            _optional_timestamp(self.proof_observed_at, "proof_observed_at"),
        )
        object.__setattr__(
            self,
            "proof_max_age_seconds",
            _non_negative_int(self.proof_max_age_seconds, "proof_max_age_seconds"),
        )
        if self.verifier_epoch is not None and not isinstance(
            self.verifier_epoch, VerifierProxyEpoch
        ):
            if isinstance(self.verifier_epoch, Mapping):
                object.__setattr__(
                    self,
                    "verifier_epoch",
                    VerifierProxyEpoch.from_dict(self.verifier_epoch),
                )
            else:
                raise GuardValidationError(
                    "verifier_epoch must be VerifierProxyEpoch or mapping"
                )
        object.__setattr__(
            self,
            "mini_app_id",
            _optional_text(self.mini_app_id, "mini_app_id", max_chars=256),
        )
        if self.chain_id is not None:
            object.__setattr__(
                self, "chain_id", _require_world_chain_id(self.chain_id)
            )
            anchor = resolve_network(
                chain_id=self.chain_id, network=self.network or None
            )
            object.__setattr__(self, "network", anchor.network)
        else:
            object.__setattr__(
                self, "network", _optional_text(self.network, "network", max_chars=128)
            )
        # Hard boundary: proof success never implies authorization.
        if self.proof_implies_authorization is True:
            raise GuardValidationError(
                "World ID proof success cannot imply transaction authorization; "
                "proof_implies_authorization must be false"
            )
        object.__setattr__(self, "proof_implies_authorization", False)
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != WORLD_ID_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported World ID binding schema: {self.schema_version!r}"
            )
        if not self.rp_id or not self.action:
            raise GuardValidationError(
                "WorldIDBinding requires rp_id and action domain binding"
            )

    @property
    def replay_domain(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "app_id": self.app_id,
            "chain_id": self.chain_id,
            "environment": self.environment,
            "external_nullifier_domain": self.external_nullifier_domain,
            "protocol_version": self.protocol_version,
            "rp_id": self.rp_id,
        }

    @property
    def binding_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "app_id": self.app_id,
            "binding_id": self.binding_id,
            "chain_id": self.chain_id,
            "challenge_id": self.challenge_id,
            "environment": self.environment,
            "external_nullifier_domain": self.external_nullifier_domain,
            "mini_app_id": self.mini_app_id,
            "network": self.network,
            "nullifier_commitment": self.nullifier_commitment,
            "proof_max_age_seconds": self.proof_max_age_seconds,
            "proof_observed_at": self.proof_observed_at,
            "protocol_version": self.protocol_version,
            "rp_id": self.rp_id,
            "signal_hash_ref": self.signal_hash_ref,
            "verification_status": self.verification_status,
            "verifier_epoch": (
                self.verifier_epoch.to_dict() if self.verifier_epoch else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "binding_digest": self.binding_digest,
                "kind": "world_id_binding",
                "proof_implies_authorization": False,
                "proof_cannot_bypass": list(PROOF_CANNOT_BYPASS),
                "replay_domain": self.replay_domain,
                "schema_version": self.schema_version,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorldIDBinding":
        value = _mapping(value, "WorldIDBinding")
        _reject_forbidden(value, "WorldIDBinding")
        return cls(
            binding_id=value.get("binding_id", value.get("bindingId", "")),
            rp_id=value.get("rp_id", value.get("rpId", "")),
            action=value.get("action", ""),
            environment=value.get("environment", "production"),
            nullifier_commitment=value.get(
                "nullifier_commitment",
                value.get("nullifierCommitment", value.get("nullifier_ref", "")),
            ),
            app_id=value.get("app_id", value.get("appId", "")),
            protocol_version=value.get(
                "protocol_version", value.get("protocolVersion", "4.0")
            ),
            external_nullifier_domain=value.get(
                "external_nullifier_domain",
                value.get("externalNullifierDomain", ""),
            ),
            signal_hash_ref=value.get(
                "signal_hash_ref", value.get("signalHashRef", "")
            ),
            challenge_id=value.get("challenge_id", value.get("challengeId", "")),
            verification_status=value.get(
                "verification_status", value.get("verificationStatus", "verified")
            ),
            proof_observed_at=value.get(
                "proof_observed_at", value.get("proofObservedAt", "")
            ),
            proof_max_age_seconds=value.get(
                "proof_max_age_seconds",
                value.get("proofMaxAgeSeconds", DEFAULT_PROOF_MAX_AGE_SECONDS),
            ),
            verifier_epoch=value.get(
                "verifier_epoch", value.get("verifierEpoch")
            ),
            mini_app_id=value.get("mini_app_id", value.get("miniAppId", "")),
            chain_id=value.get("chain_id", value.get("chainId")),
            network=value.get("network", ""),
            proof_implies_authorization=value.get(
                "proof_implies_authorization", False
            ),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", WORLD_ID_BINDING_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Composite transaction binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorldcoinTransactionBinding:
    """Exact World Chain + World ID facts bound for two-phase guard evaluation."""

    binding_id: str
    intent_id: str
    candidate_id: str
    chain_id: int
    network: str
    genesis_hash: str
    settlement_layer: str
    from_address: str
    to_address: str
    value_wei: str
    data: str
    method: str
    nonce: int | None
    fee_wei: str
    native_effects: tuple[Mapping[str, Any], ...]
    wld_effects: tuple[Mapping[str, Any], ...]
    token_effects: tuple[Mapping[str, Any], ...]
    candidate_digest: str
    serialized_digest: str
    encoding: str
    byte_length: int
    world_id: WorldIDBinding | None
    bridge_legs: tuple[BridgeLegBinding, ...]
    list_revision: str
    graph_revision: str
    policy_revision: str
    expected_effects: tuple[ExpectedEffect, ...]
    binding_digest: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = WORLDCOIN_TX_BINDING_SCHEMA_VERSION

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
        object.__setattr__(self, "chain_id", _require_world_chain_id(self.chain_id))
        object.__setattr__(
            self, "network", _text(self.network, "network", max_chars=128)
        )
        object.__setattr__(
            self, "genesis_hash", _text(self.genesis_hash, "genesis_hash", max_chars=128)
        )
        object.__setattr__(
            self,
            "settlement_layer",
            _text(self.settlement_layer, "settlement_layer", max_chars=128),
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
        if self.nonce is not None:
            object.__setattr__(self, "nonce", _non_negative_int(self.nonce, "nonce"))
        object.__setattr__(self, "fee_wei", _amount(self.fee_wei, "fee_wei"))
        object.__setattr__(
            self,
            "native_effects",
            tuple(dict(item) for item in self.native_effects),
        )
        object.__setattr__(
            self, "wld_effects", tuple(dict(item) for item in self.wld_effects)
        )
        object.__setattr__(
            self, "token_effects", tuple(dict(item) for item in self.token_effects)
        )
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
        if self.world_id is not None and not isinstance(self.world_id, WorldIDBinding):
            if isinstance(self.world_id, Mapping):
                object.__setattr__(
                    self, "world_id", WorldIDBinding.from_dict(self.world_id)
                )
            else:
                raise GuardValidationError(
                    "world_id must be WorldIDBinding, mapping, or None"
                )
        legs: list[BridgeLegBinding] = []
        for item in self.bridge_legs:
            if isinstance(item, BridgeLegBinding):
                legs.append(item)
            elif isinstance(item, Mapping):
                legs.append(BridgeLegBinding.from_dict(item))
            else:
                raise GuardValidationError(
                    "bridge_legs items must be BridgeLegBinding"
                )
        object.__setattr__(self, "bridge_legs", tuple(legs))
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
            "policy_revision",
            _optional_text(self.policy_revision, "policy_revision", max_chars=128),
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
        if self.schema_version != WORLDCOIN_TX_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported worldcoin binding schema: {self.schema_version!r}"
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
            "bridge_legs": [leg.to_dict() for leg in self.bridge_legs],
            "byte_length": self.byte_length,
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "chain_id": self.chain_id,
            "data": self.data,
            "encoding": self.encoding,
            "expected_effects": [e.to_dict() for e in self.expected_effects],
            "fee_wei": self.fee_wei,
            "from_address": self.from_address,
            "genesis_hash": self.genesis_hash,
            "graph_revision": self.graph_revision,
            "intent_id": self.intent_id,
            "list_revision": self.list_revision,
            "method": self.method,
            "native_effects": list(self.native_effects),
            "network": self.network,
            "nonce": self.nonce,
            "policy_revision": self.policy_revision,
            "serialized_digest": self.serialized_digest,
            "settlement_layer": self.settlement_layer,
            "to_address": self.to_address,
            "token_effects": list(self.token_effects),
            "value_wei": self.value_wei,
            "wld_effects": list(self.wld_effects),
            "world_id": self.world_id.to_dict() if self.world_id else None,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "WorldcoinTransactionBinding":
        value = _mapping(value, "WorldcoinTransactionBinding")
        _reject_forbidden(value, "WorldcoinTransactionBinding")
        return cls(
            binding_id=value.get("binding_id", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            chain_id=value.get("chain_id", 0),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            settlement_layer=value.get("settlement_layer", ""),
            from_address=value.get("from_address", ""),
            to_address=value.get("to_address", ""),
            value_wei=value.get("value_wei", "0"),
            data=value.get("data", "0x"),
            method=value.get("method", ""),
            nonce=value.get("nonce"),
            fee_wei=value.get("fee_wei", DEFAULT_FEE_WEI),
            native_effects=tuple(value.get("native_effects", ())),
            wld_effects=tuple(value.get("wld_effects", ())),
            token_effects=tuple(value.get("token_effects", ())),
            candidate_digest=value.get("candidate_digest", ""),
            serialized_digest=value.get("serialized_digest", ""),
            encoding=value.get("encoding", "rlp-world-chain"),
            byte_length=value.get("byte_length", 0),
            world_id=value.get("world_id"),
            bridge_legs=tuple(value.get("bridge_legs", ())),
            list_revision=value.get("list_revision", ""),
            graph_revision=value.get("graph_revision", ""),
            policy_revision=value.get("policy_revision", ""),
            expected_effects=tuple(value.get("expected_effects", ())),
            binding_digest=value.get("binding_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", WORLDCOIN_TX_BINDING_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class WorldcoinGuardPhase(str, Enum):
    """Phase at which the Worldcoin guard is consulted."""

    EVALUATE = "evaluate"
    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class WorldcoinGuardDecision:
    """Deterministic Worldcoin guard decision (not authorization to sign)."""

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
    schema_version: str = WORLDCOIN_GUARD_DECISION_SCHEMA_VERSION

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

VerifierEpochResolver = Callable[
    [str], VerifierProxyEpoch | Mapping[str, Any] | None
]
NullifierReplayChecker = Callable[[str, str], bool]
# (nullifier_commitment, external_nullifier_domain) -> already_used


def _static_verifier_resolver(
    epochs: Mapping[str, VerifierProxyEpoch | Mapping[str, Any]],
) -> VerifierEpochResolver:
    def _resolve(verifier_id: str) -> VerifierProxyEpoch | Mapping[str, Any] | None:
        return epochs.get(verifier_id)

    return _resolve


def _coerce_verifier_epoch(
    value: VerifierProxyEpoch | Mapping[str, Any] | None, *, field_name: str
) -> VerifierProxyEpoch | None:
    if value is None:
        return None
    if isinstance(value, VerifierProxyEpoch):
        return value
    if isinstance(value, Mapping):
        return VerifierProxyEpoch.from_dict(value)
    raise GuardValidationError(f"{field_name} must be VerifierProxyEpoch or mapping")


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class WorldcoinTransactionGuard:
    """Non-custodial Worldcoin / World Chain leaf guard adapter.

    Normalizes World Chain transaction candidates and World ID bindings into
    exact :class:`TransactionIntent` / :class:`TransactionCandidate` records,
    runs Worldcoin-specific fail-closed checks, and delegates capability
    issuance / atomic consumption to :class:`TransactionPreflight`.

    Verifier/proxy epochs and nullifier replay state are re-resolved at
    consumption and must match the binding used when the admissibility
    capability was issued.

    World ID proof success is treated as *evidence only* and can never
    bypass contract-safety or sanctions compliance requirements.
    """

    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_PRODUCER_ID
    policy_id: str = DEFAULT_POLICY_ID
    verifier_epoch_resolver: VerifierEpochResolver | None = None
    nullifier_already_used: NullifierReplayChecker | None = None
    interface: str = WORLDCOIN_TRANSACTION_GUARD_INTERFACE
    schema_version: str = WORLDCOIN_TRANSACTION_GUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.preflight is None:
            self.preflight = TransactionPreflight(producer_id=self.producer_id)
        if self.interface != WORLDCOIN_TRANSACTION_GUARD_INTERFACE:
            raise GuardValidationError(
                f"unsupported worldcoin guard interface: {self.interface!r}"
            )
        if self.schema_version != WORLDCOIN_TRANSACTION_GUARD_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported worldcoin guard schema: {self.schema_version!r}"
            )
        if self.nullifier_already_used is None:
            # Offline default: nullifier not used unless caller injects checker.
            self.nullifier_already_used = lambda _n, _d: False

    # -- binding ------------------------------------------------------------

    def bind_transaction(
        self,
        candidate: WorldChainTransactionCandidate | Mapping[str, Any],
        *,
        world_id: WorldIDBinding | Mapping[str, Any] | None = None,
        bridge_legs: Sequence[BridgeLegBinding | Mapping[str, Any]] | None = None,
        list_revision: str = "",
        graph_revision: str = "",
        policy_revision: str = "",
        fee_wei: str | int = DEFAULT_FEE_WEI,
        serialized_bytes: bytes | str | None = None,
        encoding: str = "rlp-world-chain",
        candidate_id: str = "",
        binding_id: str = "",
        expected_effects: Sequence[ExpectedEffect | Mapping[str, Any]] | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> WorldcoinTransactionBinding:
        """Normalize a World Chain candidate + World ID binding into a guard binding."""

        cand = self._coerce_candidate(candidate)
        wid: WorldIDBinding | None = None
        if world_id is not None:
            if isinstance(world_id, WorldIDBinding):
                wid = world_id
            elif isinstance(world_id, Mapping):
                _reject_forbidden(world_id, "WorldIDBinding")
                wid = WorldIDBinding.from_dict(world_id)
            else:
                raise GuardValidationError(
                    "world_id must be WorldIDBinding or mapping"
                )
            # Domain must bind to the same World Chain when chain_id present.
            if wid.chain_id is not None and wid.chain_id != cand.chain_id:
                raise GuardValidationError(
                    "WorldIDBinding chain_id does not match World Chain candidate"
                )

        legs: list[BridgeLegBinding] = []
        if bridge_legs:
            for item in bridge_legs:
                if isinstance(item, BridgeLegBinding):
                    legs.append(item)
                elif isinstance(item, Mapping):
                    legs.append(BridgeLegBinding.from_dict(item))
                else:
                    raise GuardValidationError(
                        "bridge_legs items must be BridgeLegBinding"
                    )

        if serialized_bytes is None:
            if cand.serialized_hex:
                raw = bytes.fromhex(cand.serialized_hex[2:])
                serialized_digest = hashlib.sha256(raw).hexdigest()
                byte_length = max(1, len(raw))
            else:
                # Deterministic commitment over candidate facts when raw
                # RLP bytes are not provided by the custody path.
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
        cand_id = candidate_id or f"candidate:world-chain:{intent_id}"
        bind_id = binding_id or f"binding:worldcoin:{intent_id}"

        # Derive expected effects when not supplied.
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
            effects = self._derive_expected_effects(cand, world_id=wid, bridge_legs=legs)

        # Auto native effect from value_wei when not declared.
        native_effects = list(cand.native_effects)
        if int(cand.value_wei) > 0 and not native_effects:
            native_effects.append(
                {
                    "kind": "native_transfer",
                    "from": cand.from_address,
                    "to": cand.to_address,
                    "value_wei": cand.value_wei,
                }
            )

        return WorldcoinTransactionBinding(
            binding_id=bind_id,
            intent_id=intent_id,
            candidate_id=cand_id,
            chain_id=cand.chain_id,
            network=cand.network,
            genesis_hash=cand.genesis_hash,
            settlement_layer=cand.settlement_layer,
            from_address=cand.from_address,
            to_address=cand.to_address,
            value_wei=cand.value_wei,
            data=cand.data,
            method=cand.method,
            nonce=cand.nonce,
            fee_wei=fee_wei,
            native_effects=tuple(native_effects),
            wld_effects=tuple(cand.wld_effects),
            token_effects=tuple(cand.token_effects),
            candidate_digest=cand.candidate_digest,
            serialized_digest=serialized_digest,
            encoding=encoding,
            byte_length=byte_length,
            world_id=wid,
            bridge_legs=tuple(legs),
            list_revision=list_revision,
            graph_revision=graph_revision,
            policy_revision=policy_revision,
            expected_effects=tuple(effects),
            attributes=attributes or {},
        )

    def to_preflight_request(
        self,
        binding: WorldcoinTransactionBinding,
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
        environment_id: str = "env:worldcoin-guard",
        environment_digest: str = "",
        nonce: str = "",
        policy_id: str | None = None,
        intent_expires_at: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TransactionPreflightRequest:
        """Project a Worldcoin binding into the common preflight request surface."""

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
                "settlement_layer": binding.settlement_layer,
                "list_revision": binding.list_revision,
                "graph_revision": binding.graph_revision,
                "policy_revision": binding.policy_revision,
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
                "worldcoin_guard": True,
                "proof_cannot_bypass": list(PROOF_CANNOT_BYPASS),
            },
        )

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        binding: WorldcoinTransactionBinding | Mapping[str, Any],
        *,
        request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        now: str | None = None,
        live_verifier_epochs: Mapping[str, VerifierProxyEpoch | Mapping[str, Any]]
        | None = None,
        request_id: str = "req:worldcoin-guard",
        tenant_id: str = "tenant:default",
        actor_id: str = "actor:policy-engine",
        audience_id: str = "audience:custody-signer",
        issued_at: str | None = None,
        deadline: str | None = None,
        expiry: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> WorldcoinGuardDecision:
        """Evaluate Worldcoin-specific bindings then run two-phase preflight.

        Structural World Chain / World ID checks run first.  Any block becomes
        a non-ALLOW security requirement so preflight never issues a capability.

        **Proof success cannot bypass contract or sanctions policy**: even when
        ``world_id.verification_status == "verified"``, contract-safety and
        sanctions compliance requirements must independently pass.
        """

        if not isinstance(binding, WorldcoinTransactionBinding):
            binding = WorldcoinTransactionBinding.from_dict(binding)

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        sec_results = dict(security_results or {})
        comp_results = dict(compliance_results or {})

        structural = self._check_structural(
            binding,
            now=clock,
            live_verifier_epochs=live_verifier_epochs,
            phase=WorldcoinGuardPhase.EVALUATE,
        )
        reason_codes.extend(structural["reason_codes"])
        reasons.extend(structural["reasons"])
        for req_id, outcome in structural["security_results"].items():
            sec_results.setdefault(req_id, outcome)

        for req_id in DEFAULT_SECURITY_REQUIREMENTS:
            sec_results.setdefault(req_id, "pass")

        # Proof success cannot clear contract/sanctions compliance.
        if binding.world_id is not None and binding.world_id.verification_status in {
            "verified",
            "success",
            "pass",
        }:
            # If caller tried to omit compliance because proof succeeded,
            # still require explicit pass results for contract + sanctions.
            for req_id in ("comp:direct-sanctions", "comp:contract-safety"):
                if req_id not in comp_results and compliance_results is not None:
                    # Caller provided a compliance map but omitted these —
                    # leave unset so preflight fails closed.
                    pass
            # Never auto-pass compliance solely due to proof success.
            for req_id in ("comp:direct-sanctions", "comp:contract-safety"):
                if sec_results.get("sec:world-id-domain") == "pass":
                    # Domain checks passed; compliance remains independent.
                    pass

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
                # Default pass only when caller omitted compliance entirely;
                # production callers must supply live list/graph results.
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
                sec_results["sec:world-chain-identity"] = mapped

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

        return WorldcoinGuardDecision(
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
                "has_world_id": binding.world_id is not None,
                "bridge_leg_count": len(binding.bridge_legs),
                "proof_cannot_bypass": list(PROOF_CANNOT_BYPASS),
            },
        )

    # -- revalidate + consume -----------------------------------------------

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        binding: WorldcoinTransactionBinding | Mapping[str, Any],
        *,
        phase: PreflightPhase | WorldcoinGuardPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        live_verifier_epochs: Mapping[str, VerifierProxyEpoch | Mapping[str, Any]]
        | None = None,
        live_candidate: WorldChainTransactionCandidate | Mapping[str, Any] | None = None,
        live_world_id: WorldIDBinding | Mapping[str, Any] | None = None,
        live_bridge_legs: Sequence[BridgeLegBinding | Mapping[str, Any]] | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate Worldcoin epochs/domains, then atomically consume.

        Re-resolves verifier/proxy epochs and checks nullifier replay domain,
        candidate bytes, and bridge legs at consumption.  Any substitution
        fails closed before consumption.
        """

        if not isinstance(binding, WorldcoinTransactionBinding):
            binding = WorldcoinTransactionBinding.from_dict(binding)
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
        elif isinstance(phase, WorldcoinGuardPhase):
            phase_value = (
                PreflightPhase.PRE_SIGN.value
                if phase is WorldcoinGuardPhase.PRE_SIGN
                else PreflightPhase.PRE_BROADCAST.value
                if phase is WorldcoinGuardPhase.PRE_BROADCAST
                else PreflightPhase.PRE_SIGN.value
            )
        else:
            phase_value = str(phase)

        clock = now or _iso_now()
        guard_phase = (
            WorldcoinGuardPhase.PRE_SIGN
            if phase_value == PreflightPhase.PRE_SIGN.value
            else WorldcoinGuardPhase.PRE_BROADCAST
        )

        # Live candidate substitution check.
        if live_candidate is not None:
            live_cand = self._coerce_candidate(live_candidate)
            if live_cand.candidate_digest != binding.candidate_digest:
                raise GuardCapabilityError(
                    "live World Chain candidate substituted",
                    reason_code="worldcoin.candidate_substituted",
                    details={
                        "expected": binding.candidate_digest,
                        "observed": live_cand.candidate_digest,
                    },
                )
            if live_cand.chain_id != binding.chain_id:
                raise GuardCapabilityError(
                    "live candidate chain_id substituted",
                    reason_code="worldcoin.chain_id_substituted",
                    details={
                        "expected": binding.chain_id,
                        "observed": live_cand.chain_id,
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
                    reason_code="worldcoin.candidate_fields_substituted",
                )

        # Live World ID domain / nullifier substitution.
        if live_world_id is not None:
            if isinstance(live_world_id, Mapping):
                live_wid = WorldIDBinding.from_dict(live_world_id)
            elif isinstance(live_world_id, WorldIDBinding):
                live_wid = live_world_id
            else:
                raise GuardValidationError("live_world_id must be WorldIDBinding")
            if binding.world_id is None:
                raise GuardCapabilityError(
                    "live World ID binding present but original binding had none",
                    reason_code="worldcoin.world_id_injected",
                )
            if live_wid.binding_digest != binding.world_id.binding_digest:
                raise GuardCapabilityError(
                    "World ID binding substituted (domain/nullifier/verifier)",
                    reason_code="worldcoin.world_id_substituted",
                    details={
                        "expected": binding.world_id.binding_digest,
                        "observed": live_wid.binding_digest,
                    },
                )
            if (
                live_wid.nullifier_commitment
                != binding.world_id.nullifier_commitment
            ):
                raise GuardCapabilityError(
                    "nullifier commitment substituted",
                    reason_code="worldcoin.nullifier_substituted",
                )
            if (
                live_wid.external_nullifier_domain
                != binding.world_id.external_nullifier_domain
            ):
                raise GuardCapabilityError(
                    "external-nullifier domain substituted",
                    reason_code="worldcoin.domain_substituted",
                )

        # Live bridge leg substitution.
        if live_bridge_legs is not None:
            live_legs: list[BridgeLegBinding] = []
            for item in live_bridge_legs:
                if isinstance(item, BridgeLegBinding):
                    live_legs.append(item)
                elif isinstance(item, Mapping):
                    live_legs.append(BridgeLegBinding.from_dict(item))
                else:
                    raise GuardValidationError("live bridge legs invalid")
            expected_digests = {leg.leg_digest for leg in binding.bridge_legs}
            observed_digests = {leg.leg_digest for leg in live_legs}
            if expected_digests != observed_digests:
                raise GuardCapabilityError(
                    "bridge legs substituted",
                    reason_code="worldcoin.bridge_substituted",
                    details={
                        "expected": sorted(expected_digests),
                        "observed": sorted(observed_digests),
                    },
                )

        structural = self._check_structural(
            binding,
            now=clock,
            live_verifier_epochs=live_verifier_epochs,
            phase=guard_phase,
            re_resolve=True,
        )
        if structural["blocking"] is not None:
            raise GuardCapabilityError(
                "; ".join(structural["reasons"])
                or "worldcoin live revalidation failed",
                reason_code=structural["reason_codes"][0]
                if structural["reason_codes"]
                else "worldcoin.consumption_blocked",
                details={
                    "reason_codes": list(structural["reason_codes"]),
                    "phase": phase_value,
                    "binding_digest": binding.binding_digest,
                },
            )

        live_attrs = live_request.candidate.attributes.to_dict()
        bound_digest = live_attrs.get("binding_digest")
        if bound_digest and bound_digest != binding.binding_digest:
            raise GuardCapabilityError(
                "live candidate binding_digest does not match Worldcoin binding",
                reason_code="worldcoin.binding_digest_mismatch",
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
        self, candidate: WorldChainTransactionCandidate | Mapping[str, Any]
    ) -> WorldChainTransactionCandidate:
        if isinstance(candidate, WorldChainTransactionCandidate):
            return candidate
        if isinstance(candidate, Mapping):
            _reject_forbidden(candidate, "WorldChainTransactionCandidate")
            return WorldChainTransactionCandidate.from_dict(candidate)
        raise GuardValidationError(
            "candidate must be a WorldChainTransactionCandidate or mapping"
        )

    def _derive_expected_effects(
        self,
        cand: WorldChainTransactionCandidate,
        *,
        world_id: WorldIDBinding | None,
        bridge_legs: Sequence[BridgeLegBinding],
    ) -> list[ExpectedEffect]:
        effects: list[ExpectedEffect] = []
        if int(cand.value_wei) > 0:
            effects.append(
                ExpectedEffect(
                    effect_id="effect:native-transfer",
                    kind="native_transfer",
                    summary=f"transfer {cand.value_wei} wei to {cand.to_address}",
                )
            )
        for index, wld in enumerate(cand.wld_effects):
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:wld-{index}",
                    kind="wld_transfer",
                    summary=f"WLD transfer amount={wld.get('amount', '')}",
                )
            )
        for index, token in enumerate(cand.token_effects):
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:token-{index}",
                    kind="token_transfer",
                    summary=f"token={token.get('token', '')} amount={token.get('amount', '')}",
                )
            )
        for leg in bridge_legs:
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:bridge-{leg.leg_id}",
                    kind=f"bridge_{leg.direction}",
                    summary=f"bridge {leg.direction} {leg.source_chain_id}->{leg.destination_chain_id}",
                )
            )
        if world_id is not None:
            effects.append(
                ExpectedEffect(
                    effect_id="effect:world-id-evidence",
                    kind="world_id_proof_evidence",
                    summary=(
                        f"World ID evidence action={world_id.action} "
                        f"(not authorization)"
                    ),
                )
            )
        if not effects:
            effects.append(
                ExpectedEffect(
                    effect_id="effect:world-chain-call",
                    kind="evm_call",
                    summary=f"World Chain call to={cand.to_address} method={cand.method or 'unknown'}",
                )
            )
        return effects

    def _check_structural(
        self,
        binding: WorldcoinTransactionBinding,
        *,
        now: str,
        live_verifier_epochs: Mapping[str, VerifierProxyEpoch | Mapping[str, Any]]
        | None,
        phase: WorldcoinGuardPhase,
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

        # World Chain identity.
        if not is_world_chain_id(binding.chain_id):
            _block(
                TransactionVerdictOutcome.DENY,
                "worldcoin.invalid_chain_id",
                f"chain_id {binding.chain_id} is not World Chain",
                "sec:world-chain-identity",
            )
        if not binding.genesis_hash or not binding.network:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "worldcoin.network_unbound",
                "World Chain network/genesis unbound",
                "sec:world-chain-identity",
            )

        # Candidate bytes.
        if not binding.serialized_digest or binding.byte_length <= 0:
            _block(
                TransactionVerdictOutcome.DENY,
                "worldcoin.candidate_bytes_unbound",
                "candidate bytes unbound",
                "sec:world-chain-candidate-bytes",
            )
        if not binding.candidate_digest:
            _block(
                TransactionVerdictOutcome.DENY,
                "worldcoin.candidate_digest_missing",
                "candidate digest missing",
                "sec:world-chain-candidate-bytes",
            )

        # Effects binding (at least method/call or explicit effects).
        has_effects = bool(
            binding.native_effects
            or binding.wld_effects
            or binding.token_effects
            or binding.expected_effects
            or int(binding.value_wei) > 0
            or binding.data not in {"", "0x"}
        )
        if not has_effects:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "worldcoin.effects_unbound",
                "WLD/native/token effects unbound",
                "sec:world-chain-effects",
            )

        # World ID domain / nullifier / verifier / proof age.
        wid = binding.world_id
        if wid is not None:
            if not wid.rp_id or not wid.action or not wid.external_nullifier_domain:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "worldcoin.domain_unbound",
                    "action/external-nullifier/domain unbound",
                    "sec:world-id-domain",
                )
            if not wid.nullifier_commitment:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "worldcoin.nullifier_unbound",
                    "nullifier commitment unbound",
                    "sec:world-id-nullifier",
                )
            # Replay check.
            assert self.nullifier_already_used is not None
            if self.nullifier_already_used(
                wid.nullifier_commitment, wid.external_nullifier_domain
            ):
                _block(
                    TransactionVerdictOutcome.DENY,
                    "worldcoin.nullifier_replay",
                    "nullifier already used in this external-nullifier domain",
                    "sec:world-id-nullifier",
                )
            # Verifier epoch.
            if wid.verifier_epoch is not None:
                bound_epoch = wid.verifier_epoch
                live = None
                if live_verifier_epochs is not None:
                    live = _coerce_verifier_epoch(
                        live_verifier_epochs.get(bound_epoch.verifier_id),
                        field_name="live_verifier_epochs item",
                    )
                elif self.verifier_epoch_resolver is not None and re_resolve:
                    live = _coerce_verifier_epoch(
                        self.verifier_epoch_resolver(bound_epoch.verifier_id),
                        field_name="verifier_epoch_resolver result",
                    )
                if re_resolve and live is None and (
                    live_verifier_epochs is not None
                    or self.verifier_epoch_resolver is not None
                ):
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "worldcoin.verifier_epoch_unresolved",
                        f"verifier epoch for {bound_epoch.verifier_id} could not be re-resolved",
                        "sec:world-id-verifier-epoch",
                    )
                elif live is not None:
                    if live.epoch_digest != bound_epoch.epoch_digest:
                        _block(
                            TransactionVerdictOutcome.DENY,
                            "worldcoin.verifier_upgrade",
                            "verifier/proxy epoch upgraded or substituted",
                            "sec:world-id-verifier-epoch",
                        )
                    if live.code_epoch != bound_epoch.code_epoch:
                        _block(
                            TransactionVerdictOutcome.DENY,
                            "worldcoin.verifier_code_epoch_mismatch",
                            "verifier code epoch mismatch at revalidation",
                            "sec:world-id-verifier-epoch",
                        )
            # Proof age freshness.
            if wid.proof_observed_at and wid.proof_max_age_seconds > 0:
                try:
                    observed = _parse_iso(wid.proof_observed_at)
                    clock_dt = _parse_iso(now)
                    age = (clock_dt - observed).total_seconds()
                    if age > wid.proof_max_age_seconds:
                        _block(
                            TransactionVerdictOutcome.STALE,
                            "worldcoin.proof_stale",
                            f"World ID proof age {age:.0f}s exceeds max "
                            f"{wid.proof_max_age_seconds}s",
                            "sec:world-id-proof-freshness",
                        )
                    if age < 0:
                        _block(
                            TransactionVerdictOutcome.INCONCLUSIVE,
                            "worldcoin.proof_future",
                            "World ID proof_observed_at is in the future",
                            "sec:world-id-proof-freshness",
                        )
                except (TypeError, ValueError) as exc:
                    _block(
                        TransactionVerdictOutcome.ERROR,
                        "worldcoin.proof_timestamp_invalid",
                        f"invalid proof timestamp: {exc}",
                        "sec:world-id-proof-freshness",
                    )
        else:
            # World ID optional for pure World Chain txs, but domain reqs pass.
            security_results.setdefault("sec:world-id-domain", "pass")
            security_results.setdefault("sec:world-id-nullifier", "pass")
            security_results.setdefault("sec:world-id-verifier-epoch", "pass")
            security_results.setdefault("sec:world-id-proof-freshness", "pass")

        # Bridge legs integrity (if present).
        for leg in binding.bridge_legs:
            if not leg.leg_id or not leg.direction:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "worldcoin.bridge_leg_unbound",
                    "bridge leg incomplete",
                    "sec:worldcoin-bridge-legs",
                )

        # Stale list/graph/policy revisions (when bound, must be non-empty at re-resolve).
        if re_resolve:
            if binding.list_revision == "stale":
                _block(
                    TransactionVerdictOutcome.STALE,
                    "worldcoin.list_revision_stale",
                    "sanctions list revision is stale",
                    "sec:world-chain-identity",
                )
            if binding.graph_revision == "stale":
                _block(
                    TransactionVerdictOutcome.STALE,
                    "worldcoin.graph_revision_stale",
                    "exposure graph revision is stale",
                    "sec:world-chain-identity",
                )
            if binding.policy_revision == "stale":
                _block(
                    TransactionVerdictOutcome.STALE,
                    "worldcoin.policy_revision_stale",
                    "policy revision is stale",
                    "sec:world-chain-identity",
                )

        _ = phase  # reserved for phase-specific tightening
        return {
            "blocking": blocking,
            "failed_requirement": failed_requirement,
            "reason_codes": reason_codes,
            "reasons": reasons,
            "security_results": security_results,
        }

    def _intent_from_binding(
        self,
        binding: WorldcoinTransactionBinding,
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
        for wld in binding.wld_effects:
            assets.append(
                AssetAmount(
                    asset_id=f"asset:wld:{WLD_WORLD_CHAIN_MAINNET_ADDRESS.lower()}",
                    amount=str(wld.get("amount", "0")),
                    asset_namespace="erc20",
                    symbol="WLD",
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

        return TransactionIntent(
            intent_id=binding.intent_id,
            network=binding.network,
            sender=binding.from_address,
            destination=binding.to_address,
            method=binding.method or "eth_call",
            assets=tuple(assets),
            fees=(
                FeeSpec(
                    amount=binding.fee_wei,
                    asset_id="asset:eth-native",
                    payer=binding.from_address,
                ),
            ),
            nonce_or_sequence=str(binding.nonce) if binding.nonce is not None else "0",
            signers=(f"signer:{binding.from_address}",),
            expected_effects=binding.expected_effects
            or (
                ExpectedEffect(
                    effect_id="effect:world-chain-call",
                    kind="evm_call",
                    summary="World Chain transaction",
                ),
            ),
            expires_at=expires_at,
            chain_namespace=EVM_NAMESPACE,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "genesis_hash": binding.genesis_hash,
                "settlement_layer": binding.settlement_layer,
                "list_revision": binding.list_revision,
                "graph_revision": binding.graph_revision,
                "policy_revision": binding.policy_revision,
                "world_id_binding_digest": (
                    binding.world_id.binding_digest if binding.world_id else ""
                ),
                "proof_cannot_bypass": list(PROOF_CANNOT_BYPASS),
            },
        )


def evaluate_worldcoin_transaction_guard(
    candidate: WorldChainTransactionCandidate | Mapping[str, Any],
    *,
    guard: WorldcoinTransactionGuard | None = None,
    **kwargs: Any,
) -> WorldcoinGuardDecision:
    """Convenience: bind a World Chain candidate and evaluate in one call."""

    guard = guard or WorldcoinTransactionGuard()
    bind_keys = {
        "world_id",
        "bridge_legs",
        "list_revision",
        "graph_revision",
        "policy_revision",
        "fee_wei",
        "serialized_bytes",
        "encoding",
        "candidate_id",
        "binding_id",
        "expected_effects",
        "attributes",
    }
    bind_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in bind_keys}
    binding = guard.bind_transaction(candidate, **bind_kwargs)
    return guard.evaluate(binding, **kwargs)


__all__ = [
    "BRIDGE_LEG_SCHEMA_VERSION",
    "DEFAULT_COMPLIANCE_REQUIREMENTS",
    "DEFAULT_FEE_WEI",
    "DEFAULT_POLICY_ID",
    "DEFAULT_PROOF_MAX_AGE_SECONDS",
    "DEFAULT_PRODUCER_ID",
    "DEFAULT_SECURITY_REQUIREMENTS",
    "PROOF_CANNOT_BYPASS",
    "VERIFIER_PROXY_EPOCH_SCHEMA_VERSION",
    "WORLDCOIN_GUARD_DECISION_SCHEMA_VERSION",
    "WORLDCOIN_TRANSACTION_GUARD_INTERFACE",
    "WORLDCOIN_TRANSACTION_GUARD_SCHEMA_VERSION",
    "WORLDCOIN_TX_BINDING_SCHEMA_VERSION",
    "WORLD_CHAIN_CANDIDATE_SCHEMA_VERSION",
    "WORLD_CHAIN_MAINNET_CHAIN_ID",
    "WORLD_CHAIN_MAINNET_GENESIS_HASH",
    "WORLD_CHAIN_MAINNET_NETWORK",
    "WORLD_CHAIN_SEPOLIA_CHAIN_ID",
    "WORLD_CHAIN_SEPOLIA_GENESIS_HASH",
    "WORLD_CHAIN_SEPOLIA_NETWORK",
    "WORLD_ID_BINDING_SCHEMA_VERSION",
    "BridgeLegBinding",
    "NullifierReplayChecker",
    "VerifierEpochResolver",
    "VerifierProxyEpoch",
    "WorldChainTransactionCandidate",
    "WorldIDBinding",
    "WorldcoinGuardDecision",
    "WorldcoinGuardPhase",
    "WorldcoinTransactionBinding",
    "WorldcoinTransactionGuard",
    "content_sha256_hex",
    "evaluate_worldcoin_transaction_guard",
]
