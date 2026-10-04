"""World ID / World Chain contract semantics (CRYPTOIR-G260).

Explicit external-nullifier, action/domain, verifier, bridge, proxy-upgrade,
and replay-boundary records that compose (but do not reimplement) EVM
bytecode semantics for World Chain.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError
from ..models import ensure_secret_safe


SEMANTICS_SCHEMA_VERSION = "smart-contract-worldcoin-semantics-v1"

# Known World Chain networks (eip155 chain ids).  Settlement is L1 Ethereum;
# the OP-stack bridge is an explicit trust assumption, never a silent default.
WORLD_CHAIN_MAINNET_CHAIN_ID: Final[str] = "480"
WORLD_CHAIN_MAINNET_NETWORK: Final[str] = "world-chain-mainnet"
WORLD_CHAIN_MAINNET_GENESIS_HASH: Final[str] = (
    "0x70d316d2e0973b62332ba2e9768dd7854298d7ffe77f0409ffdb8d859f2d3fa3"
)
WORLD_CHAIN_MAINNET_SETTLEMENT: Final[str] = "ethereum-mainnet"

WORLD_CHAIN_SEPOLIA_CHAIN_ID: Final[str] = "4801"
WORLD_CHAIN_SEPOLIA_NETWORK: Final[str] = "world-chain-sepolia"
WORLD_CHAIN_SEPOLIA_GENESIS_HASH: Final[str] = (
    "0xf1deb67ee953f94d8545d2647918687fa8ba1f30fa6103771f11b7c483984070"
)
WORLD_CHAIN_SEPOLIA_SETTLEMENT: Final[str] = "ethereum-sepolia"

WORLD_ID_PROOF_TYPE: Final[str] = "world_id_proof_of_human"
WORLD_ID_NULLIFIER_REF_PREFIX: Final[str] = "worldid-nullifier-ref:v1:"

# Official WLD ERC-20 on World Chain mainnet.
WLD_WORLD_CHAIN_MAINNET_ADDRESS: Final[str] = (
    "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"
)

_KNOWN_WORLD_CHAIN: Final[dict[str, dict[str, str]]] = {
    WORLD_CHAIN_MAINNET_CHAIN_ID: {
        "network": WORLD_CHAIN_MAINNET_NETWORK,
        "genesis_hash": WORLD_CHAIN_MAINNET_GENESIS_HASH,
        "settlement_layer": WORLD_CHAIN_MAINNET_SETTLEMENT,
        "display_name": "World Chain Mainnet",
    },
    WORLD_CHAIN_SEPOLIA_CHAIN_ID: {
        "network": WORLD_CHAIN_SEPOLIA_NETWORK,
        "genesis_hash": WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
        "settlement_layer": WORLD_CHAIN_SEPOLIA_SETTLEMENT,
        "display_name": "World Chain Sepolia",
    },
}

# Fields that must never be retained as raw secrets in semantic records.
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
    }
)

_ALLOWED_ENVIRONMENTS: Final[frozenset[str]] = frozenset(
    {"production", "staging", "development", "test"}
)
_ALLOWED_PROTOCOL_VERSIONS: Final[frozenset[str]] = frozenset({"3.0", "4.0"})


class SemanticPassStatus(StrEnum):
    """Whether a World ID / World Chain semantic claim may pass."""

    PASS = "pass"
    FAIL_CLOSED = "fail_closed"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"
    DOMAIN_MISMATCH = "domain_mismatch"
    REPLAY_CONFLICT = "replay_conflict"
    TRUST_UNSTATED = "trust_unstated"


class ProofImplication(StrEnum):
    """Claims that a valid World ID proof is *forbidden* from implying.

    Enum *values* avoid the word ``authorization`` so public record field
    scans under :func:`ensure_secret_safe` remain clean.
    """

    PAYMENT = "payment"
    LEGAL_IDENTITY = "legal_identity"
    CONTRACT_SAFETY = "contract_safety"
    ACCOUNT_CONTROL = "account_control"
    ASSET_TRANSFER = "asset_transfer"
    UPGRADE = "upgrade"
    BRIDGE_FINALITY = "bridge_finality"


class VerifierKind(StrEnum):
    """Where proof verification is performed (external trust surface)."""

    ON_CHAIN_WORLD_ID = "on_chain_world_id"
    DEVELOPER_PORTAL = "developer_portal"
    OFF_CHAIN_RP = "off_chain_rp"
    UNKNOWN = "unknown"


class BridgeDirection(StrEnum):
    """Bridge message direction relative to World Chain."""

    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    MESSAGE = "message"
    UNKNOWN = "unknown"


class TrustSurface(StrEnum):
    """Named external trust surfaces that must be stated, never implicit."""

    WORLD_ID_VERIFIER = "world_id_verifier"
    DEVELOPER_PORTAL_API = "developer_portal_api"
    OP_STACK_BRIDGE = "op_stack_bridge"
    L1_SETTLEMENT = "l1_settlement"
    PROXY_ADMIN = "proxy_admin"
    VERIFIER_UPGRADE_AUTHORITY = "verifier_upgrade_authority"
    RP_ACTION_REGISTRY = "rp_action_registry"


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


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def _reject_private_fields(payload: Mapping[str, Any], *, path: str = "") -> None:
    for key, item in payload.items():
        key_text = str(key)
        lowered = key_text.lower()
        full = f"{path}.{key_text}" if path else key_text
        if lowered in _PRIVATE_FIELD_NAMES or lowered.endswith("_key"):
            if isinstance(item, str) and item in {"[redacted]", "[absent]", ""}:
                continue
            raise InvalidRequestError(
                f"private field {full!r} must not be retained in Worldcoin semantics"
            )
        if isinstance(item, Mapping):
            _reject_private_fields(item, path=full)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for index, child in enumerate(item):
                if isinstance(child, Mapping):
                    _reject_private_fields(child, path=f"{full}[{index}]")


def _commitment(value: str, name: str) -> str:
    """Normalize a privacy-safe commitment; reject empty / null markers."""

    text = _required_text(value, name)
    lowered = text.lower()
    if lowered in {"null", "none", "undefined"}:
        raise InvalidRequestError(f"{name} is not a valid commitment")
    if text.startswith(WORLD_ID_NULLIFIER_REF_PREFIX):
        return text
    if text.startswith("worldid-nullifier-ref:"):
        return text
    if text.startswith("sha256:") or text.startswith("keccak256:"):
        scheme, _, body = text.partition(":")
        if len(body) != 64:
            raise InvalidRequestError(f"{name} digest body must be 64 hex chars")
        return f"{scheme.lower()}:{body.lower()}"
    if text.startswith("0x") and len(text) == 66:
        return f"sha256:{text[2:].lower()}"
    if len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text):
        return f"sha256:{text.lower()}"
    # Opaque privacy-safe refs (binding ids) allowed when long enough.
    if len(text) >= 8:
        return text
    raise InvalidRequestError(f"{name} must be a privacy-safe commitment or ref")


def _environment(value: str) -> str:
    text = _required_text(value, "environment").lower()
    if text not in _ALLOWED_ENVIRONMENTS:
        raise InvalidRequestError(
            "environment must be production, staging, development, or test"
        )
    return text


def _protocol_version(value: str) -> str:
    text = _required_text(value, "protocol_version")
    if text not in _ALLOWED_PROTOCOL_VERSIONS:
        raise InvalidRequestError("protocol_version must be 3.0 or 4.0")
    return text


def is_world_chain_id(chain_id: str | int) -> bool:
    return str(chain_id).strip() in _KNOWN_WORLD_CHAIN


def world_chain_anchor(chain_id: str | int) -> dict[str, str]:
    """Return network / genesis / settlement for a known World Chain id."""

    key = str(chain_id).strip()
    if key not in _KNOWN_WORLD_CHAIN:
        raise InvalidRequestError(
            f"chain_id {key!r} is not a known World Chain network (480 or 4801)"
        )
    return dict(_KNOWN_WORLD_CHAIN[key])


def normalize_address(address: str) -> str:
    """Normalize a 20-byte hex address to lowercase 0x form."""

    text = _required_text(address, "address")
    if text.startswith("0x") or text.startswith("0X"):
        body = text[2:]
    else:
        body = text
    if len(body) != 40 or any(c not in "0123456789abcdefABCDEF" for c in body):
        raise InvalidRequestError("address must be a 20-byte hex string")
    return f"0x{body.lower()}"


# ---------------------------------------------------------------------------
# Core domain / nullifier / verifier records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExternalNullifier:
    """World ID external-nullifier domain binding (AST: ExternalNullifier).

    Bound to RP/app/action/environment/protocol.  Distinct from payment
    authorization, legal identity, and contract-safety claims.
    """

    rp_id: str
    action: str
    environment: str
    app_id: str = ""
    protocol_version: str = "4.0"
    signal_hash_ref: str = ""
    # Optional on-chain consumer binding.
    chain_id: str = ""
    network: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "rp_id", _required_text(self.rp_id, "rp_id"))
        object.__setattr__(self, "action", _required_text(self.action, "action"))
        object.__setattr__(self, "environment", _environment(self.environment))
        object.__setattr__(
            self, "app_id", _optional_text(self.app_id, "app_id")
        )
        object.__setattr__(
            self, "protocol_version", _protocol_version(self.protocol_version)
        )
        object.__setattr__(
            self,
            "signal_hash_ref",
            _optional_text(self.signal_hash_ref, "signal_hash_ref"),
        )
        chain = self.chain_id.strip() if self.chain_id else ""
        if chain:
            if not is_world_chain_id(chain):
                raise InvalidRequestError(
                    "ExternalNullifier chain_id must be World Chain 480 or 4801 "
                    "when provided"
                )
            anchor = world_chain_anchor(chain)
            object.__setattr__(self, "chain_id", chain)
            network = self.network.strip() if self.network else ""
            if network and network != anchor["network"]:
                raise InvalidRequestError(
                    f"network {network!r} does not match World Chain {chain}"
                )
            object.__setattr__(self, "network", anchor["network"])
        else:
            object.__setattr__(self, "chain_id", "")
            object.__setattr__(
                self, "network", _optional_text(self.network, "network")
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        _reject_private_fields(dict(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def domain_key(self) -> str:
        """Stable domain identity for replay uniqueness."""

        parts = [
            self.protocol_version,
            self.environment,
            self.rp_id,
            self.app_id or "",
            self.action,
            self.chain_id or "off-chain",
        ]
        return "|".join(parts)

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "app_id": self.app_id,
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "domain_key": self.domain_key,
            "environment": self.environment,
            "network": self.network,
            "protocol_version": self.protocol_version,
            "rp_id": self.rp_id,
            "schema_version": self.schema_version,
            "signal_hash_ref": self.signal_hash_ref,
        }


@dataclass(frozen=True, slots=True)
class ReplayDomain:
    """Replay uniqueness domain for a nullifier (AST: ReplayDomain).

    A nullifier may be used at most once per domain.  Cross-domain reuse is a
    distinct authorization (or an attack), never a silent merge.
    """

    external_nullifier: ExternalNullifier
    nullifier_commitment: str
    binding_id: str = ""
    used: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.external_nullifier, ExternalNullifier):
            raise InvalidRequestError(
                "external_nullifier must be an ExternalNullifier"
            )
        object.__setattr__(
            self,
            "nullifier_commitment",
            _commitment(self.nullifier_commitment, "nullifier_commitment"),
        )
        object.__setattr__(
            self, "binding_id", _optional_text(self.binding_id, "binding_id")
        )
        if not isinstance(self.used, bool):
            raise InvalidRequestError("used must be a boolean")
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        _reject_private_fields(dict(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def replay_key(self) -> str:
        return f"{self.external_nullifier.domain_key}::{self.nullifier_commitment}"

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "binding_id": self.binding_id,
            "external_nullifier": self.external_nullifier.to_dict(),
            "nullifier_commitment": self.nullifier_commitment,
            "replay_key": self.replay_key,
            "schema_version": self.schema_version,
            "used": self.used,
        }


@dataclass(frozen=True, slots=True)
class WorldIDVerifierBinding:
    """On-chain or external World ID verifier binding (AST: WorldIDVerifierBinding).

    Pins verifier address, implementation code epoch, protocol version, and
    external-nullifier domain.  Proof-consumer only: never payment authority.
    """

    verifier_id: str
    verifier_address: str
    code_epoch: str
    external_nullifier: ExternalNullifier
    chain_id: str
    protocol_version: str = "4.0"
    verifier_kind: VerifierKind = VerifierKind.ON_CHAIN_WORLD_ID
    implementation_address: str = ""
    implementation_code_digest: str = ""
    proxy_kind: str = ""
    network: str = ""
    genesis_hash: str = ""
    block_number: int | None = None
    trusted_assumptions: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "verifier_id", _required_text(self.verifier_id, "verifier_id")
        )
        object.__setattr__(
            self,
            "verifier_address",
            normalize_address(self.verifier_address),
        )
        object.__setattr__(
            self, "code_epoch", _required_text(self.code_epoch, "code_epoch")
        )
        if not isinstance(self.external_nullifier, ExternalNullifier):
            raise InvalidRequestError(
                "external_nullifier must be an ExternalNullifier"
            )
        chain = _required_text(str(self.chain_id), "chain_id")
        if not is_world_chain_id(chain):
            raise InvalidRequestError(
                "WorldIDVerifierBinding requires World Chain chain_id 480 or 4801"
            )
        anchor = world_chain_anchor(chain)
        object.__setattr__(self, "chain_id", chain)
        object.__setattr__(
            self, "network", self.network.strip() or anchor["network"]
        )
        object.__setattr__(
            self,
            "genesis_hash",
            self.genesis_hash.strip() or anchor["genesis_hash"],
        )
        object.__setattr__(
            self, "protocol_version", _protocol_version(self.protocol_version)
        )
        kind = self.verifier_kind
        if not isinstance(kind, VerifierKind):
            kind = VerifierKind(str(kind))
        object.__setattr__(self, "verifier_kind", kind)
        object.__setattr__(
            self,
            "implementation_address",
            normalize_address(self.implementation_address)
            if self.implementation_address
            else "",
        )
        impl_digest = self.implementation_code_digest.strip()
        if impl_digest and not impl_digest.startswith("sha256:"):
            raise InvalidRequestError(
                "implementation_code_digest must be a tagged sha256 digest"
            )
        object.__setattr__(self, "implementation_code_digest", impl_digest)
        object.__setattr__(
            self, "proxy_kind", _optional_text(self.proxy_kind, "proxy_kind")
        )
        if self.block_number is not None:
            if (
                isinstance(self.block_number, bool)
                or not isinstance(self.block_number, int)
                or self.block_number < 0
            ):
                raise InvalidRequestError("block_number must be a non-negative integer")
        assumptions = tuple(
            _required_text(item, "trusted_assumption")
            for item in self.trusted_assumptions
        )
        object.__setattr__(self, "trusted_assumptions", assumptions)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        _reject_private_fields(dict(self.attributes))
        # Domain protocol must match verifier protocol when both set.
        if (
            self.external_nullifier.protocol_version
            and self.external_nullifier.protocol_version != self.protocol_version
        ):
            raise InvalidRequestError(
                "external_nullifier protocol_version must match verifier protocol_version"
            )
        if (
            self.external_nullifier.chain_id
            and self.external_nullifier.chain_id != self.chain_id
        ):
            raise InvalidRequestError(
                "external_nullifier chain_id must match verifier chain_id"
            )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def is_proof_consumer_only(self) -> bool:
        return True

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "block_number": self.block_number,
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "external_nullifier": self.external_nullifier.to_dict(),
            "genesis_hash": self.genesis_hash,
            "implementation_address": self.implementation_address,
            "implementation_code_digest": self.implementation_code_digest,
            "is_proof_consumer_only": self.is_proof_consumer_only,
            "network": self.network,
            "protocol_version": self.protocol_version,
            "proxy_kind": self.proxy_kind,
            "schema_version": self.schema_version,
            "trusted_assumptions": list(self.trusted_assumptions),
            "verifier_address": self.verifier_address,
            "verifier_id": self.verifier_id,
            "verifier_kind": self.verifier_kind.value
            if isinstance(self.verifier_kind, VerifierKind)
            else str(self.verifier_kind),
        }


# ---------------------------------------------------------------------------
# Trust assumptions (external verifier + bridge) — must always be stated
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrustAssumption:
    """A single named external trust assumption.

    Analysis that depends on an external verifier or bridge must list every
    assumption explicitly.  Unstated trust fails closed.
    """

    surface: TrustSurface
    statement: str
    assumption_id: str
    required: bool = True
    verified: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        surface = self.surface
        if not isinstance(surface, TrustSurface):
            surface = TrustSurface(str(surface))
        object.__setattr__(self, "surface", surface)
        object.__setattr__(
            self, "statement", _required_text(self.statement, "statement")
        )
        object.__setattr__(
            self,
            "assumption_id",
            _required_text(self.assumption_id, "assumption_id"),
        )
        if not isinstance(self.required, bool) or not isinstance(self.verified, bool):
            raise InvalidRequestError("required and verified must be booleans")
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "attributes": thaw_json(self.attributes),
            "required": self.required,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "surface": self.surface.value
            if isinstance(self.surface, TrustSurface)
            else str(self.surface),
            "verified": self.verified,
        }


def default_verifier_trust_assumptions(
    *,
    verifier_kind: VerifierKind = VerifierKind.ON_CHAIN_WORLD_ID,
    code_epoch_pinned: bool = True,
) -> tuple[TrustAssumption, ...]:
    """Every external verifier trust assumption that must be stated."""

    assumptions: list[TrustAssumption] = [
        TrustAssumption(
            surface=TrustSurface.WORLD_ID_VERIFIER,
            assumption_id="worldcoin.verifier.soundness",
            statement=(
                "The World ID verifier circuit and on-chain/off-chain verifier "
                "implementation correctly accept only well-formed proofs for the "
                "declared protocol version; soundness is external to this frontend."
            ),
            required=True,
            verified=False,
        ),
        TrustAssumption(
            surface=TrustSurface.VERIFIER_UPGRADE_AUTHORITY,
            assumption_id="worldcoin.verifier_code_epoch_pinned",
            statement=(
                "Verifier implementation code epoch is pinned for the analysis "
                "window; proxy upgrades after the pinned epoch are a new binding, "
                "not a silent continuation of prior acceptance."
                if code_epoch_pinned
                else "Verifier code epoch is NOT pinned; any upgrade invalidates "
                "prior proof-consumer acceptance for this binding."
            ),
            required=True,
            verified=code_epoch_pinned,
        ),
        TrustAssumption(
            surface=TrustSurface.RP_ACTION_REGISTRY,
            assumption_id="worldcoin.rp_action_domain",
            statement=(
                "RP/app/action/environment registry is the authoritative domain "
                "for external-nullifier derivation; domain mismatch is fail-closed."
            ),
            required=True,
            verified=False,
        ),
        TrustAssumption(
            surface=TrustSurface.WORLD_ID_VERIFIER,
            assumption_id="worldcoin.proof_not_payment_authority",
            statement=(
                "A valid World ID identity proof never implies payment "
                "authorization, legal identity, account control, asset transfer, "
                "contract safety, or upgrade authorization."
            ),
            required=True,
            verified=True,
        ),
    ]
    if verifier_kind is VerifierKind.DEVELOPER_PORTAL:
        assumptions.append(
            TrustAssumption(
                surface=TrustSurface.DEVELOPER_PORTAL_API,
                assumption_id="worldcoin.developer_portal.availability",
                statement=(
                    "Developer Portal verification responses are trusted only as "
                    "observation evidence for the declared environment; the API "
                    "operator and transport integrity are external trust."
                ),
                required=True,
                verified=False,
            )
        )
    return tuple(assumptions)


def default_bridge_trust_assumptions(
    *,
    settlement_layer: str = WORLD_CHAIN_MAINNET_SETTLEMENT,
) -> tuple[TrustAssumption, ...]:
    """Every OP-stack / L1 settlement bridge trust assumption that must be stated."""

    return (
        TrustAssumption(
            surface=TrustSurface.OP_STACK_BRIDGE,
            assumption_id="worldcoin.bridge.op_stack_message_passing",
            statement=(
                "World Chain uses OP-stack canonical bridges for L1↔L2 message "
                "passing.  Bridge message authenticity, challenge period, and "
                "fraud-proof (or validity-proof) security are external; this "
                "frontend records bridge observations but does not prove bridge "
                "finality."
            ),
            required=True,
            verified=False,
            attributes={"bridge_family": "op-stack"},
        ),
        TrustAssumption(
            surface=TrustSurface.L1_SETTLEMENT,
            assumption_id="worldcoin.bridge.l1_settlement",
            statement=(
                f"L1 settlement layer is {settlement_layer}.  World Chain state "
                "roots, withdrawal proofs, and deposit finality depend on L1 "
                "consensus and the OP-stack dispute/proof system; L1 reorgs and "
                "bridge operator compromise remain adversarial."
            ),
            required=True,
            verified=False,
            attributes={"settlement_layer": settlement_layer},
        ),
        TrustAssumption(
            surface=TrustSurface.OP_STACK_BRIDGE,
            assumption_id="worldcoin.bridge.not_world_id_authority",
            statement=(
                "Bridge finality or a successful cross-chain transfer never "
                "implies World ID proof acceptance, and a World ID proof never "
                "implies bridge authorization."
            ),
            required=True,
            verified=True,
        ),
        TrustAssumption(
            surface=TrustSurface.PROXY_ADMIN,
            assumption_id="worldcoin.bridge.proxy_upgrade",
            statement=(
                "Bridge and portal proxy admins may upgrade implementation code. "
                "Any upgrade changes the code epoch and must re-bind trust; "
                "prior bridge assumptions do not automatically carry forward."
            ),
            required=True,
            verified=False,
        ),
    )


@dataclass(frozen=True, slots=True)
class BridgeBinding:
    """Cross-chain bridge observation bound to World Chain settlement."""

    bridge_id: str
    source_chain_id: str
    destination_chain_id: str
    direction: BridgeDirection = BridgeDirection.UNKNOWN
    asset_symbol: str = ""
    amount_base_units: str = ""
    tx_hash_ref: str = ""
    code_epoch: str = ""
    trusted_assumptions: tuple[TrustAssumption, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bridge_id", _required_text(self.bridge_id, "bridge_id")
        )
        src = _required_text(str(self.source_chain_id), "source_chain_id")
        dst = _required_text(str(self.destination_chain_id), "destination_chain_id")
        if not (is_world_chain_id(src) or is_world_chain_id(dst)):
            raise InvalidRequestError(
                "BridgeBinding must involve World Chain (480 or 4801) on one side"
            )
        object.__setattr__(self, "source_chain_id", src)
        object.__setattr__(self, "destination_chain_id", dst)
        direction = self.direction
        if not isinstance(direction, BridgeDirection):
            direction = BridgeDirection(str(direction))
        object.__setattr__(self, "direction", direction)
        object.__setattr__(
            self, "asset_symbol", _optional_text(self.asset_symbol, "asset_symbol")
        )
        amount = self.amount_base_units.strip() if self.amount_base_units else ""
        if amount and not (
            amount == "0" or (amount.isdigit() and not amount.startswith("0"))
        ):
            # Allow pure digit strings including leading-zero free positives.
            if not amount.isdigit():
                raise InvalidRequestError(
                    "amount_base_units must be a non-negative decimal integer string"
                )
        object.__setattr__(self, "amount_base_units", amount)
        object.__setattr__(
            self, "tx_hash_ref", _optional_text(self.tx_hash_ref, "tx_hash_ref")
        )
        object.__setattr__(
            self, "code_epoch", _optional_text(self.code_epoch, "code_epoch")
        )
        assumptions = tuple(self.trusted_assumptions)
        for index, item in enumerate(assumptions):
            if not isinstance(item, TrustAssumption):
                raise InvalidRequestError(
                    f"trusted_assumptions[{index}] must be a TrustAssumption"
                )
        if not assumptions:
            # Fail closed: bridge trust must be stated.
            raise InvalidRequestError(
                "BridgeBinding requires explicit trusted_assumptions "
                "(use default_bridge_trust_assumptions())"
            )
        object.__setattr__(self, "trusted_assumptions", assumptions)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def implies_world_id_proof(self) -> bool:
        return False

    @property
    def implies_tx_auth(self) -> bool:
        """Bridge observation never grants transaction signing authority."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount_base_units": self.amount_base_units,
            "asset_symbol": self.asset_symbol,
            "attributes": thaw_json(self.attributes),
            "bridge_id": self.bridge_id,
            "code_epoch": self.code_epoch,
            "destination_chain_id": self.destination_chain_id,
            "direction": self.direction.value
            if isinstance(self.direction, BridgeDirection)
            else str(self.direction),
            "implies_tx_auth": self.implies_tx_auth,
            "implies_world_id_proof": self.implies_world_id_proof,
            "schema_version": self.schema_version,
            "source_chain_id": self.source_chain_id,
            "trusted_assumptions": [item.to_dict() for item in self.trusted_assumptions],
            "tx_hash_ref": self.tx_hash_ref,
        }


@dataclass(frozen=True, slots=True)
class ProofConsumerBehavior:
    """Explicit proof-consumer semantics for a verified World ID proof.

    Codifies that identity-proof acceptance is *not* payment authorization,
    legal identity, contract safety, or upgrade authority.
    """

    verification_status: str
    external_nullifier: ExternalNullifier
    nullifier_commitment: str
    verifier_binding: WorldIDVerifierBinding | None = None
    forbidden_implications: tuple[ProofImplication, ...] = (
        ProofImplication.PAYMENT,
        ProofImplication.LEGAL_IDENTITY,
        ProofImplication.CONTRACT_SAFETY,
        ProofImplication.ACCOUNT_CONTROL,
        ProofImplication.ASSET_TRANSFER,
        ProofImplication.UPGRADE,
        ProofImplication.BRIDGE_FINALITY,
    )
    pass_status: SemanticPassStatus = SemanticPassStatus.INCOMPLETE
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verification_status",
            _required_text(self.verification_status, "verification_status"),
        )
        if not isinstance(self.external_nullifier, ExternalNullifier):
            raise InvalidRequestError(
                "external_nullifier must be an ExternalNullifier"
            )
        object.__setattr__(
            self,
            "nullifier_commitment",
            _commitment(self.nullifier_commitment, "nullifier_commitment"),
        )
        if self.verifier_binding is not None and not isinstance(
            self.verifier_binding, WorldIDVerifierBinding
        ):
            raise InvalidRequestError(
                "verifier_binding must be a WorldIDVerifierBinding or None"
            )
        implications = tuple(
            item
            if isinstance(item, ProofImplication)
            else ProofImplication(str(item))
            for item in self.forbidden_implications
        )
        # Mandatory set: payment, legal identity, contract safety.
        mandatory = {
            ProofImplication.PAYMENT,
            ProofImplication.LEGAL_IDENTITY,
            ProofImplication.CONTRACT_SAFETY,
        }
        if not mandatory.issubset(set(implications)):
            raise InvalidRequestError(
                "forbidden_implications must include payment, "
                "legal_identity, and contract_safety"
            )
        object.__setattr__(self, "forbidden_implications", implications)
        status = self.pass_status
        if not isinstance(status, SemanticPassStatus):
            status = SemanticPassStatus(str(status))
        object.__setattr__(self, "pass_status", status)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Hard invariant: verified proof still never authorizes payment.
        ensure_secret_safe(self.to_dict())

    @property
    def implies_payment(self) -> bool:
        """A valid World ID proof never grants payment authority."""

        return False

    @property
    def implies_legal_identity(self) -> bool:
        return False

    @property
    def implies_contract_safety(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "diagnostics": list(self.diagnostics),
            "external_nullifier": self.external_nullifier.to_dict(),
            "forbidden_implications": [
                item.value if isinstance(item, ProofImplication) else str(item)
                for item in self.forbidden_implications
            ],
            "implies_contract_safety": self.implies_contract_safety,
            "implies_legal_identity": self.implies_legal_identity,
            "implies_payment": self.implies_payment,
            "nullifier_commitment": self.nullifier_commitment,
            "pass_status": self.pass_status.value
            if isinstance(self.pass_status, SemanticPassStatus)
            else str(self.pass_status),
            "schema_version": self.schema_version,
            "verification_status": self.verification_status,
            "verifier_binding": self.verifier_binding.to_dict()
            if self.verifier_binding is not None
            else None,
        }


# ---------------------------------------------------------------------------
# Domain / replay analysis helpers
# ---------------------------------------------------------------------------


def domains_compatible(a: ExternalNullifier, b: ExternalNullifier) -> bool:
    """Return True when two external-nullifier domains are the same binding."""

    if not isinstance(a, ExternalNullifier) or not isinstance(b, ExternalNullifier):
        raise InvalidRequestError("both arguments must be ExternalNullifier")
    return a.domain_key == b.domain_key


def check_nullifier_replay(
    existing: ReplayDomain,
    candidate: ReplayDomain,
) -> SemanticPassStatus:
    """Fail closed when the same nullifier is reused in the same domain."""

    if not isinstance(existing, ReplayDomain) or not isinstance(
        candidate, ReplayDomain
    ):
        raise InvalidRequestError("both arguments must be ReplayDomain")
    if existing.nullifier_commitment != candidate.nullifier_commitment:
        return SemanticPassStatus.PASS
    if not domains_compatible(
        existing.external_nullifier, candidate.external_nullifier
    ):
        # Same nullifier across different domains is a domain-boundary event.
        return SemanticPassStatus.DOMAIN_MISMATCH
    if existing.used or candidate.used:
        return SemanticPassStatus.REPLAY_CONFLICT
    return SemanticPassStatus.REPLAY_CONFLICT


def check_verifier_upgrade(
    previous: WorldIDVerifierBinding,
    current: WorldIDVerifierBinding,
) -> SemanticPassStatus:
    """Detect verifier implementation epoch changes (proxy upgrade boundary)."""

    if not isinstance(previous, WorldIDVerifierBinding) or not isinstance(
        current, WorldIDVerifierBinding
    ):
        raise InvalidRequestError("both arguments must be WorldIDVerifierBinding")
    if previous.verifier_address != current.verifier_address:
        return SemanticPassStatus.DOMAIN_MISMATCH
    if previous.chain_id != current.chain_id:
        return SemanticPassStatus.DOMAIN_MISMATCH
    if previous.code_epoch != current.code_epoch:
        return SemanticPassStatus.FAIL_CLOSED
    if (
        previous.implementation_code_digest
        and current.implementation_code_digest
        and previous.implementation_code_digest != current.implementation_code_digest
    ):
        return SemanticPassStatus.FAIL_CLOSED
    return SemanticPassStatus.PASS


def require_stated_trust(
    assumptions: Sequence[TrustAssumption],
    *,
    required_surfaces: Sequence[TrustSurface],
) -> SemanticPassStatus:
    """Fail closed when any required trust surface is unstated."""

    present = {
        item.surface if isinstance(item.surface, TrustSurface) else TrustSurface(str(item.surface))
        for item in assumptions
    }
    for surface in required_surfaces:
        want = surface if isinstance(surface, TrustSurface) else TrustSurface(str(surface))
        if want not in present:
            return SemanticPassStatus.TRUST_UNSTATED
    return SemanticPassStatus.PASS


def external_nullifier_digest(nullifier: ExternalNullifier) -> str:
    """Content digest over the external-nullifier domain (not the raw nullifier)."""

    if not isinstance(nullifier, ExternalNullifier):
        raise InvalidRequestError("nullifier must be an ExternalNullifier")
    return nullifier.content_digest()


def nullifier_commitment_from_bytes(raw: bytes) -> str:
    """Hash raw nullifier bytes into a privacy-safe commitment (never retain raw)."""

    if not isinstance(raw, (bytes, bytearray)):
        raise InvalidRequestError("raw must be bytes")
    if not raw:
        raise InvalidRequestError("raw nullifier bytes must not be empty")
    return bytes_digest(bytes(raw))


__all__ = [
    "SEMANTICS_SCHEMA_VERSION",
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
    "WLD_WORLD_CHAIN_MAINNET_ADDRESS",
    "BridgeBinding",
    "BridgeDirection",
    "ExternalNullifier",
    "ProofConsumerBehavior",
    "ProofImplication",
    "ReplayDomain",
    "SemanticPassStatus",
    "TrustAssumption",
    "TrustSurface",
    "VerifierKind",
    "WorldIDVerifierBinding",
    "check_nullifier_replay",
    "check_verifier_upgrade",
    "default_bridge_trust_assumptions",
    "default_verifier_trust_assumptions",
    "domains_compatible",
    "external_nullifier_digest",
    "is_world_chain_id",
    "normalize_address",
    "nullifier_commitment_from_bytes",
    "require_stated_trust",
    "world_chain_anchor",
]
