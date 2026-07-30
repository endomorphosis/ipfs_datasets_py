"""Worldcoin, World ID, and World Chain composition adapter (CRYPTOIR-G140).

Compose the EVM adapter for World Chain while representing WLD assets, World ID
proof-domain facts, nullifiers, actions, verifier instances, bridges, and Mini
App evidence as *distinct* Crypto IR records.

Design constraints:

* Import and conversion are side-effect free (no sockets, no package install).
* Reuse EVM transaction semantics for World Chain ledger observations; do not
  reimplement EVM decoding in this module.
* World ID, World Chain, WLD, verifier, bridge, nullifier, action, RP/app, and
  proof observations remain distinct record types with mandatory chain/domain
  binding where applicable.
* Proof observations confer neither legal/account identity nor transaction
  authorization by themselves.
* Never collapse proof, identity, asset, and chain authorities.
* Raw nullifiers and raw proof bytes are never retained; only privacy-safe
  commitments and refs survive conversion.

This module owns only the Worldcoin composition adapter surface and offline
fixtures (CRYPTOIR-015 / CRYPTOIR-G140).
"""

from __future__ import annotations

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
from ..model import AssetIdentity, ChainIdentity
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
from .evm import (
    EVM_NAMESPACE,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_MAINNET_NETWORK,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
    WORLD_CHAIN_SEPOLIA_NETWORK,
    EVMAdapterError,
    EVMWalletAdapter,
    content_sha256_hex,
    convert_evm_payload,
    keccak_digest_tag,
    normalize_address,
    normalize_hash,
    resolve_network,
    token_asset,
)


CRYPTO_IR_WORLDCOIN_ADAPTER_DOMAIN: Final[str] = "crypto-ir.adapter.worldcoin"
WORLDCOIN_ADAPTER_ID: Final[str] = "crypto-ir.adapter.worldcoin"
WORLDCOIN_CAPABILITY_ID: Final[str] = "crypto-ir.chain-adapter.worldcoin"
WORLDCOIN_ADAPTER_IMPLEMENTATION_VERSION: Final[str] = "1.0.0"
WORLDCOIN_ADAPTER_SEMANTIC_VERSION: Final[str] = "1.0.0"

# Official World Chain WLD ERC-20 (mainnet chain id 480).
# Source: https://docs.world.org/world-chain/reference/useful-contracts
WLD_WORLD_CHAIN_MAINNET_ADDRESS: Final[str] = (
    "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"
)
WLD_DECIMALS: Final[int] = 18
WLD_SYMBOL: Final[str] = "WLD"

WORLD_ID_PROOF_TYPE: Final[str] = "world_id_proof_of_human"
WORLD_ID_NULLIFIER_REF_PREFIX: Final[str] = "worldid-nullifier-ref:v1:"

# Settlement layers for L1-aware World Chain labeling (never inferred from depth).
WORLD_CHAIN_MAINNET_SETTLEMENT: Final[str] = "ethereum-mainnet"
WORLD_CHAIN_SEPOLIA_SETTLEMENT: Final[str] = "ethereum-sepolia"

_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"
)
_HEX_COMMITMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:0x)?[0-9a-fA-F]{64}$|^(?:sha256|keccak256|hmac-sha256):[0-9a-fA-F]{64}$"
)
_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"^0x[0-9a-fA-F]{40}$")


class WorldcoinAdapterError(CryptoIRAdapterError):
    """Raised when a Worldcoin composition payload cannot be converted fail-closed."""


class WorldcoinPayloadKind(str, Enum):
    """Supported offline conversion payload kinds (non-interchangeable)."""

    WORLD_ID_OBSERVATION = "world_id_observation"
    NULLIFIER_BINDING = "nullifier_binding"
    WORLD_CHAIN_IDENTITY = "world_chain_identity"
    WORLD_CHAIN_TRANSACTION = "world_chain_transaction"
    WLD_ASSET = "wld_asset"
    VERIFIER_INSTANCE = "verifier_instance"
    BRIDGE_OBSERVATION = "bridge_observation"
    MINI_APP_EVIDENCE = "mini_app_evidence"
    ACTION_DOMAIN = "action_domain"
    COMPOSITION = "composition"


# Private fields that must never survive conversion as raw values.
_PRIVATE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "nullifier",
        "raw_nullifier",
        "session_nullifier",
        "proof",
        "idkit_payload",
        "developer_portal_response",
        "jwt",
        "rp_signature",
        "signature",
        "nonce",
        "integrity_bundle",
        "responses",
    }
)


# ---------------------------------------------------------------------------
# Validation / normalization helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise WorldcoinAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise WorldcoinAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise WorldcoinAdapterError(f"{name} must not have surrounding whitespace")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorldcoinAdapterError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise WorldcoinAdapterError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise WorldcoinAdapterError(str(exc)) from exc


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _ID_RE.fullmatch(text):
        raise WorldcoinAdapterError(f"{name} is not a stable identifier")
    return text


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        if isinstance(value, str) and value.isdigit():
            parsed = int(value, 10)
            if parsed <= 0:
                raise WorldcoinAdapterError(f"{name} must be a positive integer")
            return parsed
        raise WorldcoinAdapterError(f"{name} must be a positive integer")
    if value <= 0:
        raise WorldcoinAdapterError(f"{name} must be a positive integer")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value is None:
        return ""
    return _text(value, name, allow_empty=True)


def _commitment(value: Any, name: str) -> str:
    """Normalize a privacy-safe commitment or nullifier ref; reject empty raw secrets."""

    text = _text(value, name)
    lowered = text.lower()
    if lowered in {"null", "none", "undefined"}:
        raise WorldcoinAdapterError(f"{name} is not a valid commitment")
    # Allow explicit privacy-safe prefixes used by wallet bindings.
    if text.startswith(WORLD_ID_NULLIFIER_REF_PREFIX):
        return text
    if text.startswith("worldid-nullifier-ref:"):
        return text
    if _HEX_COMMITMENT_RE.fullmatch(text):
        if text.startswith("0x") or text.startswith("0X"):
            return f"sha256:{text[2:].lower()}"
        if ":" in text:
            scheme, body = text.split(":", 1)
            return f"{scheme.lower()}:{body.lower()}"
        return f"sha256:{text.lower()}"
    # Opaque non-empty refs (e.g. binding ids) are allowed as refs, not raw secrets.
    if len(text) >= 8 and not any(
        secret in lowered for secret in ("raw_nullifier", "session_nullifier")
    ):
        return text
    raise WorldcoinAdapterError(f"{name} must be a privacy-safe commitment or ref")


def _reject_private_fields(payload: Mapping[str, Any], *, path: str = "") -> None:
    """Fail closed when raw private proof/nullifier material is present."""

    for key, item in payload.items():
        key_text = str(key)
        lowered = key_text.lower()
        full = f"{path}.{key_text}" if path else key_text
        if lowered in _PRIVATE_FIELD_NAMES or lowered.endswith("_key"):
            # Allow metadata that *names* the private field without value retention
            # only when the value is an explicit redaction marker.
            if isinstance(item, str) and item in {"[redacted]", "[absent]", ""}:
                continue
            raise WorldcoinAdapterError(
                f"private field {full!r} must not be retained in Crypto IR conversion"
            )
        if isinstance(item, Mapping):
            _reject_private_fields(item, path=full)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for index, child in enumerate(item):
                if isinstance(child, Mapping):
                    _reject_private_fields(child, path=f"{full}[{index}]")


def _protocol_version(value: Any) -> str:
    text = _text(value, "protocol_version")
    if text not in {"3.0", "4.0"}:
        raise WorldcoinAdapterError("protocol_version must be 3.0 or 4.0")
    return text


def _environment(value: Any) -> str:
    text = _text(value, "environment").lower()
    if text not in {"production", "staging", "development", "test"}:
        raise WorldcoinAdapterError(
            "environment must be production, staging, development, or test"
        )
    return text


def world_chain_settlement_layer(chain_id: int) -> str:
    """Return the L1 settlement label for a known World Chain network."""

    if chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID:
        return WORLD_CHAIN_MAINNET_SETTLEMENT
    if chain_id == WORLD_CHAIN_SEPOLIA_CHAIN_ID:
        return WORLD_CHAIN_SEPOLIA_SETTLEMENT
    raise WorldcoinAdapterError(
        f"chain_id {chain_id} is not a known World Chain network"
    )


def is_world_chain_id(chain_id: int) -> bool:
    return chain_id in {
        WORLD_CHAIN_MAINNET_CHAIN_ID,
        WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    }


def normalize_wld_contract(address: str) -> str:
    return normalize_address(address, field="wld_contract")


# ---------------------------------------------------------------------------
# Structured composition records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorldChainIdentity:
    """World Chain network identity (chain authority only — not proof or asset).

    Distinct from World ID proof observations, WLD asset identities, and
    verifier instances.  Reuses EVM chain-id + genesis binding.
    """

    chain_id: int
    network: str = ""
    genesis_hash: str = ""
    settlement_layer: str = ""
    display_name: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        chain_id = _positive_int(self.chain_id, "chain_id")
        if not is_world_chain_id(chain_id):
            raise WorldcoinAdapterError(
                "WorldChainIdentity requires World Chain chain_id 480 or 4801"
            )
        object.__setattr__(self, "chain_id", chain_id)
        anchor = resolve_network(
            chain_id=chain_id,
            network=self.network or None,
            genesis_hash=self.genesis_hash or None,
            display_name=self.display_name,
        )
        object.__setattr__(self, "network", anchor.network)
        object.__setattr__(self, "genesis_hash", anchor.genesis_hash)
        settlement = self.settlement_layer or world_chain_settlement_layer(chain_id)
        object.__setattr__(
            self, "settlement_layer", _text(settlement, "settlement_layer")
        )
        object.__setattr__(
            self,
            "display_name",
            _text(self.display_name or anchor.display_name, "display_name"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

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
                "settlement_layer": self.settlement_layer,
                "composition": "world-chain",
                "composes": "evm",
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "display_name": self.display_name,
            "genesis_hash": self.genesis_hash,
            "kind": WorldcoinPayloadKind.WORLD_CHAIN_IDENTITY.value,
            "network": self.network,
            "settlement_layer": self.settlement_layer,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorldChainIdentity":
        value = _as_mapping(value, "WorldChainIdentity")
        return cls(
            chain_id=value.get("chain_id", 0),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            settlement_layer=value.get("settlement_layer", ""),
            display_name=value.get("display_name", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class NullifierBinding:
    """Privacy-safe nullifier binding (never raw nullifier material).

    Bound to RP/app/action/environment domain.  Distinct from account identity,
    asset identity, and transaction authorization.
    """

    binding_id: str
    nullifier_commitment: str
    rp_id: str
    action: str
    environment: str
    app_id: str = ""
    protocol_version: str = "4.0"
    nullifier_ref: str = ""
    signal_hash_ref: str = ""
    challenge_id: str = ""
    verification_status: str = "verified"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(
            self,
            "nullifier_commitment",
            _commitment(self.nullifier_commitment, "nullifier_commitment"),
        )
        object.__setattr__(self, "rp_id", _text(self.rp_id, "rp_id"))
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(self, "environment", _environment(self.environment))
        object.__setattr__(
            self, "app_id", _text(self.app_id, "app_id", allow_empty=True)
        )
        object.__setattr__(
            self, "protocol_version", _protocol_version(self.protocol_version)
        )
        object.__setattr__(
            self,
            "nullifier_ref",
            _text(self.nullifier_ref, "nullifier_ref", allow_empty=True),
        )
        if self.nullifier_ref:
            object.__setattr__(
                self,
                "nullifier_ref",
                _commitment(self.nullifier_ref, "nullifier_ref"),
            )
        object.__setattr__(
            self,
            "signal_hash_ref",
            _text(self.signal_hash_ref, "signal_hash_ref", allow_empty=True),
        )
        object.__setattr__(
            self,
            "challenge_id",
            _text(self.challenge_id, "challenge_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "verification_status",
            _text(self.verification_status, "verification_status"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        # Domain binding is mandatory: rp + action + environment form the
        # external-nullifier / replay domain.
        if not self.rp_id or not self.action:
            raise WorldcoinAdapterError(
                "NullifierBinding requires rp_id and action domain binding"
            )

    @property
    def replay_domain(self) -> dict[str, str]:
        return {
            "rp_id": self.rp_id,
            "app_id": self.app_id,
            "action": self.action,
            "environment": self.environment,
            "protocol_version": self.protocol_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "app_id": self.app_id,
            "attributes": thaw_json(self.attributes),
            "binding_id": self.binding_id,
            "challenge_id": self.challenge_id,
            "environment": self.environment,
            "kind": WorldcoinPayloadKind.NULLIFIER_BINDING.value,
            "nullifier_commitment": self.nullifier_commitment,
            "nullifier_ref": self.nullifier_ref,
            "protocol_version": self.protocol_version,
            "replay_domain": self.replay_domain,
            "rp_id": self.rp_id,
            "signal_hash_ref": self.signal_hash_ref,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NullifierBinding":
        value = _as_mapping(value, "NullifierBinding")
        return cls(
            binding_id=value.get("binding_id", value.get("id", "")),
            nullifier_commitment=value.get(
                "nullifier_commitment", value.get("nullifier_ref", "")
            ),
            rp_id=value.get("rp_id", ""),
            action=value.get("action", ""),
            environment=value.get("environment", "production"),
            app_id=value.get("app_id", ""),
            protocol_version=value.get("protocol_version", "4.0"),
            nullifier_ref=value.get("nullifier_ref", ""),
            signal_hash_ref=value.get("signal_hash_ref", ""),
            challenge_id=value.get("challenge_id", ""),
            verification_status=value.get("verification_status", "verified"),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class WorldIDObservation:
    """World ID proof-domain observation (evidence/observation — not authorization).

    Distinct from World Chain identity, WLD assets, bridge records, Mini App
    evidence, and transaction candidates.  A valid proof does not imply payment
    authorization, legal identity, or account control.
    """

    observation_id: str
    rp_id: str
    action: str
    environment: str
    nullifier_commitment: str
    app_id: str = ""
    protocol_version: str = "4.0"
    verifier_id: str = ""
    proof_system: str = ""
    credential_policy: str = "proof_of_human"
    verification_status: str = "verified"
    signal_hash_ref: str = ""
    challenge_id: str = ""
    binding_id: str = ""
    observed_at: str = ""
    # Optional World Chain domain binding for on-chain verifier consumers.
    chain_id: int | None = None
    network: str = ""
    genesis_hash: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _identifier(self.observation_id, "observation_id"),
        )
        object.__setattr__(self, "rp_id", _text(self.rp_id, "rp_id"))
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(self, "environment", _environment(self.environment))
        object.__setattr__(
            self,
            "nullifier_commitment",
            _commitment(self.nullifier_commitment, "nullifier_commitment"),
        )
        object.__setattr__(
            self, "app_id", _text(self.app_id, "app_id", allow_empty=True)
        )
        object.__setattr__(
            self, "protocol_version", _protocol_version(self.protocol_version)
        )
        object.__setattr__(
            self, "verifier_id", _text(self.verifier_id, "verifier_id", allow_empty=True)
        )
        object.__setattr__(
            self,
            "proof_system",
            _text(self.proof_system, "proof_system", allow_empty=True),
        )
        object.__setattr__(
            self,
            "credential_policy",
            _text(self.credential_policy, "credential_policy"),
        )
        object.__setattr__(
            self,
            "verification_status",
            _text(self.verification_status, "verification_status"),
        )
        object.__setattr__(
            self,
            "signal_hash_ref",
            _text(self.signal_hash_ref, "signal_hash_ref", allow_empty=True),
        )
        object.__setattr__(
            self,
            "challenge_id",
            _text(self.challenge_id, "challenge_id", allow_empty=True),
        )
        object.__setattr__(
            self, "binding_id", _text(self.binding_id, "binding_id", allow_empty=True)
        )
        object.__setattr__(
            self, "observed_at", _text(self.observed_at, "observed_at", allow_empty=True)
        )
        if self.chain_id is not None:
            chain_id = _positive_int(self.chain_id, "chain_id")
            if not is_world_chain_id(chain_id):
                raise WorldcoinAdapterError(
                    "WorldIDObservation chain_id must be World Chain 480 or 4801 "
                    "when provided (proof domain may also be off-chain)"
                )
            object.__setattr__(self, "chain_id", chain_id)
            anchor = resolve_network(
                chain_id=chain_id,
                network=self.network or None,
                genesis_hash=self.genesis_hash or None,
            )
            object.__setattr__(self, "network", anchor.network)
            object.__setattr__(self, "genesis_hash", anchor.genesis_hash)
        else:
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
        _reject_private_fields(dict(self.raw))
        _reject_private_fields(dict(self.attributes))

    @property
    def proof_domain(self) -> dict[str, Any]:
        domain: dict[str, Any] = {
            "rp_id": self.rp_id,
            "app_id": self.app_id,
            "action": self.action,
            "environment": self.environment,
            "protocol_version": self.protocol_version,
            "credential_policy": self.credential_policy,
        }
        if self.chain_id is not None:
            domain["chain_id"] = self.chain_id
            domain["network"] = self.network
            domain["genesis_hash"] = self.genesis_hash
        return domain

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "app_id": self.app_id,
            "attributes": thaw_json(self.attributes),
            "binding_id": self.binding_id,
            "chain_id": self.chain_id,
            "challenge_id": self.challenge_id,
            "credential_policy": self.credential_policy,
            "environment": self.environment,
            "genesis_hash": self.genesis_hash,
            "kind": WorldcoinPayloadKind.WORLD_ID_OBSERVATION.value,
            "network": self.network,
            "nullifier_commitment": self.nullifier_commitment,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "proof_domain": self.proof_domain,
            "proof_system": self.proof_system,
            "protocol_version": self.protocol_version,
            "raw": thaw_json(self.raw),
            "rp_id": self.rp_id,
            "signal_hash_ref": self.signal_hash_ref,
            "verification_status": self.verification_status,
            "verifier_id": self.verifier_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorldIDObservation":
        value = _as_mapping(value, "WorldIDObservation")
        return cls(
            observation_id=value.get("observation_id", value.get("id", "")),
            rp_id=value.get("rp_id", ""),
            action=value.get("action", ""),
            environment=value.get("environment", "production"),
            nullifier_commitment=value.get(
                "nullifier_commitment", value.get("nullifier_ref", "")
            ),
            app_id=value.get("app_id", ""),
            protocol_version=value.get("protocol_version", "4.0"),
            verifier_id=value.get("verifier_id", ""),
            proof_system=value.get("proof_system", ""),
            credential_policy=value.get("credential_policy", "proof_of_human"),
            verification_status=value.get("verification_status", "verified"),
            signal_hash_ref=value.get("signal_hash_ref", ""),
            challenge_id=value.get("challenge_id", ""),
            binding_id=value.get("binding_id", ""),
            observed_at=value.get("observed_at", ""),
            chain_id=value.get("chain_id"),
            network=value.get("network", ""),
            genesis_hash=value.get("genesis_hash", ""),
            attributes=value.get("attributes", {}),
            raw=value.get("raw", {}),
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def default_worldcoin_capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=WORLDCOIN_CAPABILITY_ID,
        kind=CapabilityKind.CHAIN_ADAPTER,
        implementation_version=WORLDCOIN_ADAPTER_IMPLEMENTATION_VERSION,
        semantic_version=WORLDCOIN_ADAPTER_SEMANTIC_VERSION,
        status=CapabilityStatus.AVAILABLE,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=(EVM_NAMESPACE, "worldcoin", "world-id"),
        features=(
            "world_id",
            "world_chain",
            "wld_asset",
            "nullifier_binding",
            "verifier_instance",
            "bridge_observation",
            "mini_app_evidence",
            "action_domain",
            "evm_composition",
            "authority_separation",
        ),
        summary=(
            "Worldcoin composition: World ID proof-domain, nullifiers, WLD, "
            "World Chain via EVM reuse, bridges, Mini App evidence"
        ),
        attributes={
            "world_chain_ids": [
                WORLD_CHAIN_MAINNET_CHAIN_ID,
                WORLD_CHAIN_SEPOLIA_CHAIN_ID,
            ],
            "wld_mainnet_contract": WLD_WORLD_CHAIN_MAINNET_ADDRESS.lower(),
            "composes": "crypto-ir.adapter.evm",
            "preserves_raw_evidence": True,
            "invents_missing_facts": False,
            "proof_implies_authorization": False,
            "proof_implies_legal_identity": False,
            "collapses_authorities": False,
        },
    )


class WorldcoinAdapter:
    """Side-effect-free Worldcoin / World ID / World Chain → Crypto IR adapter.

    Implements :class:`~ipfs_datasets_py.logic.crypto_ir.adapters.CryptoIRAdapter`.
    Composes :class:`EVMWalletAdapter` for World Chain transaction semantics
    without collapsing proof, identity, asset, or chain authorities.
    """

    def __init__(
        self,
        *,
        adapter_id: str = WORLDCOIN_ADAPTER_ID,
        capability: CapabilityDescriptor | None = None,
        evm_adapter: EVMWalletAdapter | None = None,
    ) -> None:
        self._adapter_id = _text(adapter_id, "adapter_id")
        if capability is None:
            capability = default_worldcoin_capability()
        if not isinstance(capability, CapabilityDescriptor):
            raise WorldcoinAdapterError("capability must be a CapabilityDescriptor")
        if not capability.side_effect_free:
            raise WorldcoinAdapterError(
                "Worldcoin adapter capability must be side-effect-free"
            )
        self._capability = capability
        self._evm = evm_adapter or EVMWalletAdapter()

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
        | WorldIDObservation
        | NullifierBinding
        | WorldChainIdentity,
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        """Convert *payload* without elevating authority or inventing facts."""

        if isinstance(payload, WorldIDObservation):
            payload_map: Mapping[str, Any] = payload.to_dict()
        elif isinstance(payload, NullifierBinding):
            payload_map = payload.to_dict()
        elif isinstance(payload, WorldChainIdentity):
            payload_map = payload.to_dict()
        elif isinstance(payload, Mapping):
            payload_map = payload
        else:
            raise WorldcoinAdapterError(
                "payload must be a mapping or Worldcoin structured record"
            )

        source_digest = f"sha256:{content_sha256_hex(dict(payload_map))}"
        provenance_dict: dict[str, Any] = {}
        source_authority = AuthorityKind.OBSERVATION

        try:
            kind = self._detect_kind(payload_map)
            default_authority = self._default_authority(kind)
            provenance_dict, source_authority = self._resolve_provenance(
                source_provenance, default=default_authority
            )
            if source_authority is AuthorityKind.AUTHORIZATION:
                raise WorldcoinAdapterError(
                    "cannot convert authorization-authority payload through "
                    "Worldcoin composition adapter"
                )
            # Result authority never elevates and never rewrites into a
            # different sibling kind; preserve source authority on the receipt.
            result_authority = source_authority

            converters = {
                WorldcoinPayloadKind.WORLD_ID_OBSERVATION: self._convert_world_id_observation,
                WorldcoinPayloadKind.NULLIFIER_BINDING: self._convert_nullifier_binding,
                WorldcoinPayloadKind.WORLD_CHAIN_IDENTITY: self._convert_world_chain_identity,
                WorldcoinPayloadKind.WORLD_CHAIN_TRANSACTION: self._convert_world_chain_transaction,
                WorldcoinPayloadKind.WLD_ASSET: self._convert_wld_asset,
                WorldcoinPayloadKind.VERIFIER_INSTANCE: self._convert_verifier_instance,
                WorldcoinPayloadKind.BRIDGE_OBSERVATION: self._convert_bridge_observation,
                WorldcoinPayloadKind.MINI_APP_EVIDENCE: self._convert_mini_app_evidence,
                WorldcoinPayloadKind.ACTION_DOMAIN: self._convert_action_domain,
                WorldcoinPayloadKind.COMPOSITION: self._convert_composition,
            }
            converter = converters[kind]
            result_payload, unsupported, diagnostics, status = converter(payload_map)
        except (WorldcoinAdapterError, EVMAdapterError) as exc:
            return AdapterConversionResult(
                conversion_id=f"worldcoin-error:{self._adapter_id}",
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
                attributes={
                    "error": True,
                    "chain_namespace": EVM_NAMESPACE,
                    "composition": "worldcoin",
                },
            )

        result_digest = f"sha256:{content_sha256_hex(result_payload)}"
        conversion_id = f"worldcoin:{kind.value}:{result_digest[:18]}"
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
                "composition": "worldcoin",
                "preserves_raw_evidence": True,
                "proof_implies_authorization": False,
                "proof_implies_legal_identity": False,
            },
        )

    def _default_authority(self, kind: WorldcoinPayloadKind) -> AuthorityKind:
        if kind in {
            WorldcoinPayloadKind.WORLD_CHAIN_IDENTITY,
            WorldcoinPayloadKind.WLD_ASSET,
            WorldcoinPayloadKind.VERIFIER_INSTANCE,
            WorldcoinPayloadKind.ACTION_DOMAIN,
        }:
            return AuthorityKind.DECLARATION
        if kind is WorldcoinPayloadKind.MINI_APP_EVIDENCE:
            return AuthorityKind.EVIDENCE
        return AuthorityKind.OBSERVATION

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
            authority = data.get("authority")
            if isinstance(authority, Mapping):
                kind_value = authority.get("kind", default.value)
            else:
                kind_value = data.get("authority_kind", default.value)
            try:
                kind = AuthorityKind(kind_value) if not isinstance(
                    kind_value, AuthorityKind
                ) else kind_value
            except (TypeError, ValueError) as exc:
                raise WorldcoinAdapterError(
                    f"unsupported source authority: {kind_value!r}"
                ) from exc
            return data, kind
        raise WorldcoinAdapterError("source_provenance must be CryptoIRProvenance or mapping")

    def _detect_kind(self, payload: Mapping[str, Any]) -> WorldcoinPayloadKind:
        if "kind" in payload and payload["kind"] not in (None, ""):
            try:
                return WorldcoinPayloadKind(str(payload["kind"]))
            except ValueError as exc:
                raise WorldcoinAdapterError(
                    f"unsupported Worldcoin payload kind: {payload['kind']!r}"
                ) from exc
        # Structural detection for composition fixtures without explicit kind.
        if "nullifier_commitment" in payload and "rp_id" in payload and "action" in payload:
            if "observation_id" in payload or "verifier_id" in payload:
                return WorldcoinPayloadKind.WORLD_ID_OBSERVATION
            if "binding_id" in payload:
                return WorldcoinPayloadKind.NULLIFIER_BINDING
        if (
            "chain_id" in payload
            and "settlement_layer" in payload
            and "tx_hash" not in payload
            and "wld_contract" not in payload
        ):
            return WorldcoinPayloadKind.WORLD_CHAIN_IDENTITY
        if "tx_hash" in payload or "transaction_hash" in payload:
            return WorldcoinPayloadKind.WORLD_CHAIN_TRANSACTION
        if "wld_contract" in payload or (
            payload.get("symbol") == WLD_SYMBOL and "chain_id" in payload
        ):
            return WorldcoinPayloadKind.WLD_ASSET
        if "verifier_id" in payload and "verifier_address" in payload:
            return WorldcoinPayloadKind.VERIFIER_INSTANCE
        if "bridge_id" in payload or payload.get("record_family") == "bridge":
            return WorldcoinPayloadKind.BRIDGE_OBSERVATION
        if "mini_app_id" in payload or payload.get("record_family") == "mini_app":
            return WorldcoinPayloadKind.MINI_APP_EVIDENCE
        if "action" in payload and "rp_id" in payload and "components" not in payload:
            return WorldcoinPayloadKind.ACTION_DOMAIN
        if "components" in payload:
            return WorldcoinPayloadKind.COMPOSITION
        raise WorldcoinAdapterError(
            "unable to detect Worldcoin payload kind; set kind explicitly"
        )

    # ------------------------------------------------------------------
    # Kind converters
    # ------------------------------------------------------------------

    def _convert_world_id_observation(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        observation = WorldIDObservation.from_dict(payload)
        unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = [
            "record_type=world_id_observation",
            "authority_boundary=proof_observation_not_authorization",
            "authority_boundary=proof_observation_not_legal_identity",
            f"proof_domain_rp={observation.rp_id}",
            f"proof_domain_action={observation.action}",
            f"proof_domain_environment={observation.environment}",
        ]

        nullifier_binding = NullifierBinding(
            binding_id=observation.binding_id or f"nb-{observation.observation_id}",
            nullifier_commitment=observation.nullifier_commitment,
            rp_id=observation.rp_id,
            action=observation.action,
            environment=observation.environment,
            app_id=observation.app_id,
            protocol_version=observation.protocol_version,
            signal_hash_ref=observation.signal_hash_ref,
            challenge_id=observation.challenge_id,
            verification_status=observation.verification_status,
        )

        chain_dict: dict[str, Any] | None = None
        if observation.chain_id is not None:
            identity = WorldChainIdentity(
                chain_id=observation.chain_id,
                network=observation.network,
                genesis_hash=observation.genesis_hash,
            )
            chain_dict = identity.to_chain_identity().to_dict()
            diagnostics.append(
                f"chain_bound=true;chain_id={observation.chain_id};"
                f"network={observation.network}"
            )
        else:
            diagnostics.append("chain_bound=false;off_chain_proof_domain")
            unsupported.append(
                UnsupportedField(
                    path="chain_id",
                    reason="off-chain World ID domain; chain binding absent (not invented)",
                )
            )

        verifier_id = observation.verifier_id
        if not verifier_id:
            major = observation.protocol_version.split(".", 1)[0]
            verifier_id = f"world_id_developer_portal_v{major}"
            diagnostics.append("verifier_id_defaulted_from_protocol")

        proof_system = observation.proof_system
        if not proof_system:
            major = observation.protocol_version.split(".", 1)[0]
            proof_system = f"world_id_idkit_v{major}"

        result_payload: dict[str, Any] = {
            "record_type": "world_id_observation",
            "authority": AuthorityKind.OBSERVATION.value,
            "proof_type": WORLD_ID_PROOF_TYPE,
            "observation_id": observation.observation_id,
            "proof_domain": observation.proof_domain,
            "nullifier_binding": nullifier_binding.to_dict(),
            "verifier": {
                "verifier_id": verifier_id,
                "proof_system": proof_system,
                "type": "world_id_verifier",
            },
            "verification_status": observation.verification_status,
            "credential_policy": observation.credential_policy,
            "observed_at": observation.observed_at,
            "chain": chain_dict,
            # Explicit non-implications — fail-closed consumers rely on these.
            "implies_transaction_authorization": False,
            "implies_legal_identity": False,
            "implies_account_control": False,
            "implies_asset_transfer": False,
            "distinct_from": [
                "world_chain_identity",
                "wld_asset",
                "bridge_observation",
                "mini_app_evidence",
                "transaction_authorization",
            ],
            "attributes": thaw_json(observation.attributes),
            "raw": thaw_json(observation.raw),
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        return result_payload, tuple(unsupported), tuple(diagnostics), status

    def _convert_nullifier_binding(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        _reject_private_fields(dict(payload))
        binding = NullifierBinding.from_dict(payload)
        diagnostics = (
            "record_type=nullifier_binding",
            "raw_nullifier_absent=true",
            f"replay_domain={binding.rp_id}/{binding.action}/{binding.environment}",
            "distinct_from=account_identity,asset_identity,authorization",
        )
        result_payload = {
            "record_type": "nullifier_binding",
            "authority": AuthorityKind.OBSERVATION.value,
            "nullifier_binding": binding.to_dict(),
            "replay_domain": binding.replay_domain,
            "implies_transaction_authorization": False,
            "implies_legal_identity": False,
            "implies_account_control": False,
            "distinct_from": [
                "world_id_observation",
                "world_chain_identity",
                "wld_asset",
                "account_identity",
            ],
        }
        return (
            result_payload,
            (),
            diagnostics,
            AdapterConversionStatus.SUCCEEDED,
        )

    def _convert_world_chain_identity(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        identity = WorldChainIdentity.from_dict(payload)
        chain = identity.to_chain_identity()
        # Cross-check against Ethereum mainnet to keep networks distinct.
        eth_anchor = resolve_network(chain_id=1)
        diagnostics = (
            "record_type=world_chain_identity",
            f"chain_id={identity.chain_id}",
            f"network={identity.network}",
            f"settlement_layer={identity.settlement_layer}",
            f"distinct_from_ethereum_mainnet={identity.chain_id != eth_anchor.chain_id}",
            "composes=evm",
            "not_world_id_proof=true",
            "not_wld_asset=true",
        )
        result_payload = {
            "record_type": "world_chain_identity",
            "authority": AuthorityKind.DECLARATION.value,
            "world_chain_identity": identity.to_dict(),
            "chain": chain.to_dict(),
            "settlement_layer": identity.settlement_layer,
            "composes": "evm",
            "distinct_from": [
                "ethereum-mainnet",
                "world_id_observation",
                "wld_asset",
                "nullifier_binding",
            ],
        }
        return (
            result_payload,
            (),
            diagnostics,
            AdapterConversionStatus.SUCCEEDED,
        )

    def _convert_world_chain_transaction(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        """Compose EVM conversion for World Chain ledger transactions."""

        chain_id = payload.get("chain_id")
        if chain_id is None:
            raise WorldcoinAdapterError(
                "world_chain_transaction requires chain_id (480 or 4801)"
            )
        resolved_id = _positive_int(chain_id, "chain_id")
        if not is_world_chain_id(resolved_id):
            raise WorldcoinAdapterError(
                "world_chain_transaction chain_id must be World Chain 480 or 4801; "
                "use the EVM adapter directly for other EVM networks"
            )

        # Force kind to EVM transaction observation while preserving fields.
        evm_payload = dict(payload)
        evm_payload["kind"] = "transaction_observation"
        evm_payload["chain_id"] = resolved_id
        if not evm_payload.get("network"):
            identity = WorldChainIdentity(chain_id=resolved_id)
            evm_payload["network"] = identity.network
            evm_payload.setdefault("genesis_hash", identity.genesis_hash)

        evm_result = convert_evm_payload(evm_payload, adapter=self._evm)
        if evm_result.status is AdapterConversionStatus.ERROR:
            raise WorldcoinAdapterError(
                evm_result.diagnostics[0]
                if evm_result.diagnostics
                else "EVM composition failed for World Chain transaction"
            )

        identity = WorldChainIdentity(
            chain_id=resolved_id,
            network=str(evm_payload.get("network") or ""),
            genesis_hash=str(evm_payload.get("genesis_hash") or ""),
        )
        composed = {
            "record_type": "world_chain_transaction",
            "authority": AuthorityKind.OBSERVATION.value,
            "composition": "evm",
            "world_chain_identity": identity.to_dict(),
            "settlement_layer": identity.settlement_layer,
            "evm_conversion": {
                "conversion_id": evm_result.conversion_id,
                "adapter_id": evm_result.adapter_id,
                "status": evm_result.status.value,
                "result_payload": thaw_json(evm_result.result_payload),
                "unsupported_fields": [
                    item.to_dict() for item in evm_result.unsupported_fields
                ],
                "diagnostics": list(evm_result.diagnostics),
            },
            # Composition markers: ledger observation is not a World ID proof.
            "implies_world_id_proof": False,
            "implies_transaction_authorization": False,
            "distinct_from": [
                "world_id_observation",
                "nullifier_binding",
                "mini_app_evidence",
                "bridge_observation",
            ],
        }
        diagnostics = (
            "record_type=world_chain_transaction",
            "composed_via=crypto-ir.adapter.evm",
            f"chain_id={resolved_id}",
            f"settlement_layer={identity.settlement_layer}",
            f"evm_status={evm_result.status.value}",
        )
        return (
            composed,
            tuple(evm_result.unsupported_fields),
            diagnostics,
            evm_result.status,
        )

    def _convert_wld_asset(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        chain_id = _positive_int(payload.get("chain_id", 0), "chain_id")
        if not is_world_chain_id(chain_id):
            raise WorldcoinAdapterError(
                "WLD asset identity requires World Chain chain_id 480 or 4801"
            )
        identity = WorldChainIdentity(
            chain_id=chain_id,
            network=str(payload.get("network") or ""),
            genesis_hash=str(payload.get("genesis_hash") or ""),
        )
        chain = identity.to_chain_identity()
        contract = payload.get("wld_contract") or payload.get("contract_address")
        if contract is None or contract == "":
            if chain_id != WORLD_CHAIN_MAINNET_CHAIN_ID:
                raise WorldcoinAdapterError(
                    "WLD contract_address is required outside World Chain mainnet; "
                    "never substitute the mainnet WLD address for other networks"
                )
            contract = WLD_WORLD_CHAIN_MAINNET_ADDRESS
        contract_norm = normalize_wld_contract(str(contract))
        if (
            chain_id != WORLD_CHAIN_MAINNET_CHAIN_ID
            and contract_norm == WLD_WORLD_CHAIN_MAINNET_ADDRESS.lower()
        ):
            raise WorldcoinAdapterError(
                "mainnet WLD contract must not be bound to a non-mainnet World Chain network"
            )

        asset = token_asset(
            chain,
            contract_norm,
            decimals=WLD_DECIMALS,
            symbol=WLD_SYMBOL,
            standard="erc20",
        )
        # Enrich attributes with WLD catalog label without inventing decimals.
        asset_dict = asset.to_dict()
        asset_dict["attributes"] = {
            **dict(asset_dict.get("attributes") or {}),
            "catalog": "wld",
            "world_chain": True,
        }
        # Rebuild through AssetIdentity for frozen attributes.
        asset = AssetIdentity(
            chain=chain,
            asset_namespace=asset.asset_namespace,
            asset_reference=asset.asset_reference,
            decimals=asset.decimals,
            symbol=asset.symbol,
            attributes=asset_dict["attributes"],
        )

        diagnostics = (
            "record_type=wld_asset",
            f"chain_id={chain_id}",
            f"contract={contract_norm}",
            "distinct_from=native_eth,world_id_proof,nullifier",
        )
        result_payload = {
            "record_type": "wld_asset",
            "authority": AuthorityKind.DECLARATION.value,
            "asset": asset.to_dict(),
            "chain": chain.to_dict(),
            "symbol": WLD_SYMBOL,
            "decimals": WLD_DECIMALS,
            "contract": contract_norm,
            "distinct_from": [
                "world_id_observation",
                "nullifier_binding",
                "native_eth",
                "bridge_observation",
            ],
        }
        return (
            result_payload,
            (),
            diagnostics,
            AdapterConversionStatus.SUCCEEDED,
        )

    def _convert_verifier_instance(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        verifier_id = _identifier(payload.get("verifier_id", ""), "verifier_id")
        verifier_address = normalize_address(
            payload.get("verifier_address", ""), field="verifier_address"
        )
        chain_id = payload.get("chain_id")
        chain_dict: dict[str, Any] | None = None
        unsupported: list[UnsupportedField] = []
        if chain_id is not None:
            resolved = _positive_int(chain_id, "chain_id")
            if not is_world_chain_id(resolved):
                raise WorldcoinAdapterError(
                    "on-chain verifier_instance requires World Chain chain_id"
                )
            identity = WorldChainIdentity(
                chain_id=resolved,
                network=str(payload.get("network") or ""),
                genesis_hash=str(payload.get("genesis_hash") or ""),
            )
            chain_dict = identity.to_chain_identity().to_dict()
        else:
            unsupported.append(
                UnsupportedField(
                    path="chain_id",
                    reason="verifier not chain-bound; not invented as World Chain",
                )
            )

        protocol_version = _protocol_version(payload.get("protocol_version", "4.0"))
        external_nullifier_domain = payload.get("external_nullifier_domain") or {}
        if not isinstance(external_nullifier_domain, Mapping):
            raise WorldcoinAdapterError(
                "external_nullifier_domain must be a mapping when provided"
            )
        domain = {
            "rp_id": _optional_text(external_nullifier_domain.get("rp_id"), "rp_id"),
            "app_id": _optional_text(external_nullifier_domain.get("app_id"), "app_id"),
            "action": _optional_text(external_nullifier_domain.get("action"), "action"),
            "environment": _optional_text(
                external_nullifier_domain.get("environment"), "environment"
            ),
        }
        if not domain["rp_id"] or not domain["action"]:
            raise WorldcoinAdapterError(
                "verifier_instance requires external_nullifier_domain with rp_id and action"
            )
        if domain["environment"]:
            domain["environment"] = _environment(domain["environment"])

        diagnostics = (
            "record_type=verifier_instance",
            f"verifier_id={verifier_id}",
            f"verifier_address={verifier_address}",
            "distinct_from=account_identity,authorization,wld_asset",
            "proof_consumer_only=true",
        )
        result_payload = {
            "record_type": "verifier_instance",
            "authority": AuthorityKind.DECLARATION.value,
            "verifier_id": verifier_id,
            "verifier_address": verifier_address,
            "protocol_version": protocol_version,
            "external_nullifier_domain": domain,
            "chain": chain_dict,
            "code_epoch": _optional_text(payload.get("code_epoch"), "code_epoch"),
            "implies_transaction_authorization": False,
            "implies_legal_identity": False,
            "distinct_from": [
                "world_id_observation",
                "account_identity",
                "wld_asset",
                "bridge_observation",
            ],
            "attributes": thaw_json(
                _attributes(payload.get("attributes") if isinstance(
                    payload.get("attributes"), Mapping
                ) else {})
            ),
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        return result_payload, tuple(unsupported), diagnostics, status

    def _convert_bridge_observation(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        bridge_id = _identifier(
            payload.get("bridge_id", payload.get("observation_id", "")), "bridge_id"
        )
        source_chain_id = _positive_int(
            payload.get("source_chain_id", payload.get("chain_id", 0)),
            "source_chain_id",
        )
        dest_chain_id = payload.get("destination_chain_id")
        if dest_chain_id is None:
            raise WorldcoinAdapterError(
                "bridge_observation requires destination_chain_id"
            )
        dest_id = _positive_int(dest_chain_id, "destination_chain_id")
        # At least one side must be World Chain for this composition adapter.
        if not (is_world_chain_id(source_chain_id) or is_world_chain_id(dest_id)):
            raise WorldcoinAdapterError(
                "bridge_observation must involve World Chain (480 or 4801) on one side"
            )

        asset_symbol = _optional_text(payload.get("asset_symbol"), "asset_symbol")
        amount = payload.get("amount_base_units")
        amount_text = ""
        if amount is not None:
            amount_text = _text(str(amount), "amount_base_units")
            if not re.fullmatch(r"0|[1-9][0-9]*", amount_text):
                raise WorldcoinAdapterError(
                    "amount_base_units must be a non-negative decimal integer string"
                )

        diagnostics = (
            "record_type=bridge_observation",
            f"bridge_id={bridge_id}",
            f"source_chain_id={source_chain_id}",
            f"destination_chain_id={dest_id}",
            "distinct_from=world_id_proof,nullifier,mini_app",
            "not_authorization=true",
        )
        result_payload = {
            "record_type": "bridge_observation",
            "authority": AuthorityKind.OBSERVATION.value,
            "bridge_id": bridge_id,
            "source_chain_id": source_chain_id,
            "destination_chain_id": dest_id,
            "asset_symbol": asset_symbol,
            "amount_base_units": amount_text,
            "direction": _optional_text(payload.get("direction"), "direction"),
            "tx_hash": _optional_text(
                payload.get("tx_hash", payload.get("transaction_hash")), "tx_hash"
            ),
            "implies_world_id_proof": False,
            "implies_transaction_authorization": False,
            "distinct_from": [
                "world_id_observation",
                "nullifier_binding",
                "mini_app_evidence",
                "verifier_instance",
            ],
            "attributes": thaw_json(
                _attributes(
                    payload.get("attributes")
                    if isinstance(payload.get("attributes"), Mapping)
                    else {}
                )
            ),
        }
        return (
            result_payload,
            (),
            diagnostics,
            AdapterConversionStatus.SUCCEEDED,
        )

    def _convert_mini_app_evidence(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        _reject_private_fields(dict(payload))
        mini_app_id = _identifier(
            payload.get("mini_app_id", payload.get("app_id", "")), "mini_app_id"
        )
        rp_id = _text(payload.get("rp_id", mini_app_id), "rp_id")
        action = _optional_text(payload.get("action"), "action")
        unsupported: list[UnsupportedField] = []
        if not action:
            unsupported.append(
                UnsupportedField(
                    path="action",
                    reason="Mini App evidence without action; domain incomplete",
                )
            )

        diagnostics_list = [
            "record_type=mini_app_evidence",
            f"mini_app_id={mini_app_id}",
            f"rp_id={rp_id}",
            "distinct_from=world_id_proof,bridge,wld_asset,authorization",
        ]
        result_payload = {
            "record_type": "mini_app_evidence",
            "authority": AuthorityKind.EVIDENCE.value,
            "mini_app_id": mini_app_id,
            "rp_id": rp_id,
            "action": action,
            "app_id": _optional_text(payload.get("app_id"), "app_id"),
            "session_ref": _optional_text(payload.get("session_ref"), "session_ref"),
            "evidence_digest": _optional_text(
                payload.get("evidence_digest"), "evidence_digest"
            ),
            "implies_world_id_proof": False,
            "implies_transaction_authorization": False,
            "implies_legal_identity": False,
            "distinct_from": [
                "world_id_observation",
                "nullifier_binding",
                "bridge_observation",
                "wld_asset",
                "world_chain_transaction",
            ],
            "attributes": thaw_json(
                _attributes(
                    payload.get("attributes")
                    if isinstance(payload.get("attributes"), Mapping)
                    else {}
                )
            ),
        }
        status = (
            AdapterConversionStatus.SUCCEEDED
            if not unsupported
            else AdapterConversionStatus.PARTIAL
        )
        return result_payload, tuple(unsupported), tuple(diagnostics_list), status

    def _convert_action_domain(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        rp_id = _text(payload.get("rp_id", ""), "rp_id")
        action = _text(payload.get("action", ""), "action")
        environment = _environment(payload.get("environment", "production"))
        app_id = _optional_text(payload.get("app_id"), "app_id")
        protocol_version = _protocol_version(payload.get("protocol_version", "4.0"))
        domain = {
            "rp_id": rp_id,
            "app_id": app_id,
            "action": action,
            "environment": environment,
            "protocol_version": protocol_version,
        }
        domain_digest = f"sha256:{content_sha256_hex(domain)}"
        diagnostics = (
            "record_type=action_domain",
            f"domain_digest={domain_digest[:24]}",
            "mandatory_binding=rp_id+action+environment",
            "distinct_from=nullifier_value,account_identity",
        )
        result_payload = {
            "record_type": "action_domain",
            "authority": AuthorityKind.DECLARATION.value,
            "action_domain": domain,
            "domain_digest": domain_digest,
            "external_nullifier_inputs": {
                "rp_id": rp_id,
                "action": action,
                "app_id": app_id,
                "environment": environment,
            },
            "implies_nullifier_spent": False,
            "implies_transaction_authorization": False,
            "distinct_from": [
                "nullifier_binding",
                "world_id_observation",
                "account_identity",
            ],
        }
        return (
            result_payload,
            (),
            diagnostics,
            AdapterConversionStatus.SUCCEEDED,
        )

    def _convert_composition(
        self, payload: Mapping[str, Any]
    ) -> tuple[
        dict[str, Any],
        tuple[UnsupportedField, ...],
        tuple[str, ...],
        AdapterConversionStatus,
    ]:
        """Convert a multi-domain composition packet without collapsing authorities."""

        composition_id = _identifier(
            payload.get("composition_id", payload.get("id", "composition-1")),
            "composition_id",
        )
        components = payload.get("components")
        if not isinstance(components, Sequence) or isinstance(
            components, (str, bytes, bytearray)
        ):
            raise WorldcoinAdapterError("composition.components must be a sequence")
        if not components:
            raise WorldcoinAdapterError("composition.components must not be empty")

        converted: list[dict[str, Any]] = []
        all_unsupported: list[UnsupportedField] = []
        diagnostics: list[str] = [f"composition_id={composition_id}"]
        record_types: list[str] = []
        statuses: list[AdapterConversionStatus] = []

        for index, component in enumerate(components):
            if not isinstance(component, Mapping):
                raise WorldcoinAdapterError(
                    f"composition.components[{index}] must be a mapping"
                )
            # Prevent recursive unbounded composition nesting without kind.
            if (
                component.get("kind") == WorldcoinPayloadKind.COMPOSITION.value
                or "components" in component
            ):
                raise WorldcoinAdapterError(
                    "nested composition components are not supported"
                )
            child = self.convert(component)
            statuses.append(child.status)
            child_payload = thaw_json(child.result_payload)
            record_type = (
                child_payload.get("record_type")
                if isinstance(child_payload, Mapping)
                else None
            )
            if record_type:
                record_types.append(str(record_type))
            converted.append(
                {
                    "index": index,
                    "status": child.status.value,
                    "source_authority": child.source_authority.value,
                    "result_authority": child.result_authority.value,
                    "conversion_id": child.conversion_id,
                    "record_type": record_type,
                    "result_payload": child_payload,
                    "diagnostics": list(child.diagnostics),
                }
            )
            for field_item in child.unsupported_fields:
                all_unsupported.append(
                    UnsupportedField(
                        path=f"components[{index}].{field_item.path}",
                        reason=field_item.reason,
                        raw_digest=field_item.raw_digest,
                        attributes=dict(field_item.attributes),
                    )
                )
            if child.status is AdapterConversionStatus.ERROR:
                diagnostics.append(f"components[{index}]=error")

        # Authority separation audit: proof records must not be treated as auth.
        has_proof = "world_id_observation" in record_types
        has_tx = "world_chain_transaction" in record_types
        has_asset = "wld_asset" in record_types
        has_bridge = "bridge_observation" in record_types
        has_mini = "mini_app_evidence" in record_types
        has_chain = "world_chain_identity" in record_types
        diagnostics.extend(
            [
                f"component_record_types={','.join(record_types)}",
                f"has_world_id_proof={has_proof}",
                f"has_world_chain_tx={has_tx}",
                f"has_wld_asset={has_asset}",
                f"has_bridge={has_bridge}",
                f"has_mini_app={has_mini}",
                f"has_chain_identity={has_chain}",
                "authorities_collapsed=false",
                "proof_confers_authorization=false",
            ]
        )

        if AdapterConversionStatus.ERROR in statuses:
            status = AdapterConversionStatus.ERROR
        elif AdapterConversionStatus.PARTIAL in statuses:
            status = AdapterConversionStatus.PARTIAL
        elif AdapterConversionStatus.UNSUPPORTED in statuses:
            status = AdapterConversionStatus.PARTIAL
        else:
            status = AdapterConversionStatus.SUCCEEDED

        result_payload = {
            "record_type": "worldcoin_composition",
            "authority": AuthorityKind.OBSERVATION.value,
            "composition_id": composition_id,
            "components": converted,
            "component_record_types": record_types,
            "authority_lattice": {
                "proof": has_proof,
                "chain": has_chain or has_tx,
                "asset": has_asset,
                "bridge": has_bridge,
                "mini_app": has_mini,
                "collapsed": False,
                "proof_implies_authorization": False,
                "proof_implies_legal_identity": False,
            },
            "distinct_domains_preserved": True,
        }
        return result_payload, tuple(all_unsupported), tuple(diagnostics), status


def convert_worldcoin_payload(
    payload: Mapping[str, Any]
    | WorldIDObservation
    | NullifierBinding
    | WorldChainIdentity,
    *,
    source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    adapter: WorldcoinAdapter | None = None,
) -> AdapterConversionResult:
    """Module-level helper around :class:`WorldcoinAdapter.convert`."""

    return (adapter or WorldcoinAdapter()).convert(
        payload, source_provenance=source_provenance
    )


# Alias matching AST query / registry naming.
WorldCoinAdapter = WorldcoinAdapter


__all__ = [
    "CRYPTO_IR_WORLDCOIN_ADAPTER_DOMAIN",
    "WORLDCOIN_ADAPTER_ID",
    "WORLDCOIN_CAPABILITY_ID",
    "WORLD_CHAIN_MAINNET_CHAIN_ID",
    "WORLD_CHAIN_MAINNET_GENESIS_HASH",
    "WORLD_CHAIN_MAINNET_NETWORK",
    "WORLD_CHAIN_MAINNET_SETTLEMENT",
    "WORLD_CHAIN_SEPOLIA_CHAIN_ID",
    "WORLD_CHAIN_SEPOLIA_GENESIS_HASH",
    "WORLD_CHAIN_SEPOLIA_NETWORK",
    "WORLD_CHAIN_SEPOLIA_SETTLEMENT",
    "WORLD_ID_NULLIFIER_REF_PREFIX",
    "WORLD_ID_PROOF_TYPE",
    "WLD_DECIMALS",
    "WLD_SYMBOL",
    "WLD_WORLD_CHAIN_MAINNET_ADDRESS",
    "NullifierBinding",
    "WorldChainIdentity",
    "WorldCoinAdapter",
    "WorldIDObservation",
    "WorldcoinAdapter",
    "WorldcoinAdapterError",
    "WorldcoinPayloadKind",
    "convert_worldcoin_payload",
    "default_worldcoin_capability",
    "is_world_chain_id",
    "normalize_wld_contract",
    "world_chain_settlement_layer",
]
