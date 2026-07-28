"""World Chain composition layer over an Ethereum/EVM wallet processor.

World Chain is not a duplicate EVM implementation.  This module owns network
identity (chain ids 480/4801 + genesis), WLD asset binding, and finality
semantics that distinguish inclusion, operational confirmation, safe, finalized,
and optional L1 settlement.  Block depth alone is never labeled finality.

SIWE bootstrap is intentionally absent (future reviewed child objective).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from ..models import AssetRef, ChainRef, Finality
from .assets import (
    WorldChainAssetManifest,
    assert_asset_bound_to_chain,
    asset_manifests_for_chain,
    build_mainnet_wld_manifest,
    native_eth_asset,
    wld_asset,
)


# Official World Chain network anchors (WALPROC-G120).
# Genesis hashes are eth_getBlockByNumber("0x0") values from public RPC and
# must match the provider before any scan is trusted.
WORLD_CHAIN_MAINNET_CHAIN_ID = 480
WORLD_CHAIN_SEPOLIA_CHAIN_ID = 4801
WORLD_CHAIN_NAMESPACE = "eip155"

WORLD_CHAIN_MAINNET_GENESIS_HASH = (
    "0x70d316d2e0973b62332ba2e9768dd7854298d7ffe77f0409ffdb8d859f2d3fa3"
)
WORLD_CHAIN_SEPOLIA_GENESIS_HASH = (
    "0xf1deb67ee953f94d8545d2647918687fa8ba1f30fa6103771f11b7c483984070"
)

WORLD_CHAIN_MAINNET_NETWORK = "mainnet"
WORLD_CHAIN_SEPOLIA_NETWORK = "sepolia"

# Settlement layers for L1-settled finality labeling.
WORLD_CHAIN_MAINNET_SETTLEMENT = "ethereum-mainnet"
WORLD_CHAIN_SEPOLIA_SETTLEMENT = "ethereum-sepolia"

# SIWE is a separate reviewed child objective — do not promote a placeholder.
SIWE_BOOTSTRAP_SUPPORTED = False


class WorldChainConfigError(ValueError):
    """Raised when World Chain network configuration is invalid."""


def _is_bytes32_hex(value: str) -> bool:
    raw = str(value or "").strip().lower()
    if not raw.startswith("0x") or len(raw) != 66:
        return False
    try:
        int(raw[2:], 16)
    except ValueError:
        return False
    return True


class WorldChainFinalityLabel(StrEnum):
    """Distinct lifecycle labels for World Chain observations.

    These map onto the portable :class:`~..models.Finality` enum without
    collapsing uncertainty.  ``INCLUDED`` is not finality; ``L1_SETTLED`` is
    optional and never inferred from block depth alone.
    """

    INCLUDED = "included"
    OPERATIONALLY_CONFIRMED = "operationally_confirmed"
    SAFE = "safe"
    FINALIZED = "finalized"
    L1_SETTLED = "l1_settled"


_LABEL_TO_FINALITY: Mapping[WorldChainFinalityLabel, Finality] = {
    WorldChainFinalityLabel.INCLUDED: Finality.OBSERVED,
    WorldChainFinalityLabel.OPERATIONALLY_CONFIRMED: Finality.CONFIRMED,
    WorldChainFinalityLabel.SAFE: Finality.SAFE,
    WorldChainFinalityLabel.FINALIZED: Finality.FINALIZED,
    # L1 settlement is still "finalized" in the portable enum; the richer label
    # is retained in extensions for L2-aware consumers.
    WorldChainFinalityLabel.L1_SETTLED: Finality.FINALIZED,
}


@dataclass(frozen=True, slots=True)
class WorldChainNetwork:
    """Validated World Chain network identity."""

    chain_id: int
    network: str
    genesis_hash: str
    settlement_layer: str
    eip3770_short_name: str

    def __post_init__(self) -> None:
        if self.chain_id not in {WORLD_CHAIN_MAINNET_CHAIN_ID, WORLD_CHAIN_SEPOLIA_CHAIN_ID}:
            raise WorldChainConfigError(
                f"chain_id must be {WORLD_CHAIN_MAINNET_CHAIN_ID} or {WORLD_CHAIN_SEPOLIA_CHAIN_ID}"
            )
        if not self.network.strip():
            raise WorldChainConfigError("network must not be empty")
        if not _is_bytes32_hex(self.genesis_hash):
            raise WorldChainConfigError("genesis_hash must be 32-byte 0x-hex")
        if not self.settlement_layer.strip():
            raise WorldChainConfigError("settlement_layer must not be empty")

    @property
    def chain_id_str(self) -> str:
        return str(self.chain_id)

    def to_chain_ref(self) -> ChainRef:
        return ChainRef(
            namespace=WORLD_CHAIN_NAMESPACE,
            network=self.network,
            chain_id=self.chain_id_str,
            genesis_hash=self.genesis_hash.lower(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": WORLD_CHAIN_NAMESPACE,
            "chain_id": self.chain_id,
            "network": self.network,
            "genesis_hash": self.genesis_hash.lower(),
            "settlement_layer": self.settlement_layer,
            "eip3770_short_name": self.eip3770_short_name,
            "siwe_bootstrap_supported": SIWE_BOOTSTRAP_SUPPORTED,
        }


WORLD_CHAIN_MAINNET = WorldChainNetwork(
    chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
    network=WORLD_CHAIN_MAINNET_NETWORK,
    genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
    settlement_layer=WORLD_CHAIN_MAINNET_SETTLEMENT,
    eip3770_short_name="wc",
)

WORLD_CHAIN_SEPOLIA = WorldChainNetwork(
    chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    network=WORLD_CHAIN_SEPOLIA_NETWORK,
    genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
    settlement_layer=WORLD_CHAIN_SEPOLIA_SETTLEMENT,
    eip3770_short_name="wcsep",
)

_NETWORKS_BY_CHAIN_ID: Mapping[int, WorldChainNetwork] = {
    WORLD_CHAIN_MAINNET_CHAIN_ID: WORLD_CHAIN_MAINNET,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID: WORLD_CHAIN_SEPOLIA,
}


def get_world_chain_network(chain_id: int | str) -> WorldChainNetwork:
    """Return the official network descriptor for *chain_id*."""

    try:
        numeric = int(str(chain_id).strip(), 0) if isinstance(chain_id, str) else int(chain_id)
    except (TypeError, ValueError) as exc:
        raise WorldChainConfigError("chain_id must be an integer") from exc
    network = _NETWORKS_BY_CHAIN_ID.get(numeric)
    if network is None:
        raise WorldChainConfigError(
            f"unsupported World Chain chain_id {numeric}; expected "
            f"{WORLD_CHAIN_MAINNET_CHAIN_ID} or {WORLD_CHAIN_SEPOLIA_CHAIN_ID}"
        )
    return network


def validate_world_chain_identity(
    *,
    chain_id: int | str,
    genesis_hash: str,
    network: str | None = None,
) -> WorldChainNetwork:
    """Validate provider-reported chain id and genesis against official anchors."""

    expected = get_world_chain_network(chain_id)
    provided_genesis = str(genesis_hash or "").strip().lower()
    if provided_genesis != expected.genesis_hash.lower():
        raise WorldChainConfigError("genesis_hash does not match official World Chain network identity")
    if network is not None and str(network).strip().lower() != expected.network:
        raise WorldChainConfigError("network name does not match official World Chain identity")
    return expected


@dataclass(frozen=True, slots=True)
class WorldChainFinalityAssessment:
    """Result of classifying an observation's finality without depth-as-finality."""

    label: WorldChainFinalityLabel
    portable: Finality
    confirmations: int | None = None
    l1_settled: bool = False
    source_tag: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label.value,
            "portable_finality": self.portable.value,
            "confirmations": self.confirmations,
            "l1_settled": self.l1_settled,
            "source_tag": self.source_tag,
            "block_depth_alone_is_not_finality": True,
        }


def classify_world_chain_finality(
    *,
    block_tag: str | None = None,
    confirmations: int | None = None,
    l1_settled: bool = False,
    min_operational_confirmations: int = 1,
) -> WorldChainFinalityAssessment:
    """Map EVM finality signals to distinct World Chain labels.

    Preferred path uses explicit safe/finalized tags.  Confirmation count may
    only support ``operationally_confirmed`` / ``included`` and is never renamed
    to finality.  L1 settlement is optional and independent.
    """

    tag = str(block_tag or "").strip().lower()
    if l1_settled:
        return WorldChainFinalityAssessment(
            label=WorldChainFinalityLabel.L1_SETTLED,
            portable=_LABEL_TO_FINALITY[WorldChainFinalityLabel.L1_SETTLED],
            confirmations=confirmations,
            l1_settled=True,
            source_tag=tag or "l1_settled",
        )
    if tag in {"finalized", "finality"}:
        return WorldChainFinalityAssessment(
            label=WorldChainFinalityLabel.FINALIZED,
            portable=Finality.FINALIZED,
            confirmations=confirmations,
            source_tag=tag,
        )
    if tag == "safe":
        return WorldChainFinalityAssessment(
            label=WorldChainFinalityLabel.SAFE,
            portable=Finality.SAFE,
            confirmations=confirmations,
            source_tag=tag,
        )
    if confirmations is not None:
        if isinstance(confirmations, bool) or confirmations < 0:
            raise WorldChainConfigError("confirmations must be a non-negative integer")
        if confirmations >= min_operational_confirmations:
            return WorldChainFinalityAssessment(
                label=WorldChainFinalityLabel.OPERATIONALLY_CONFIRMED,
                portable=Finality.CONFIRMED,
                confirmations=confirmations,
                source_tag=tag or "confirmations",
            )
        return WorldChainFinalityAssessment(
            label=WorldChainFinalityLabel.INCLUDED,
            portable=Finality.OBSERVED,
            confirmations=confirmations,
            source_tag=tag or "confirmations",
        )
    if tag in {"latest", "pending", "earliest", ""}:
        return WorldChainFinalityAssessment(
            label=WorldChainFinalityLabel.INCLUDED,
            portable=Finality.OBSERVED,
            confirmations=confirmations,
            source_tag=tag or "included",
        )
    # Unknown tags remain included — never upgraded to finality.
    return WorldChainFinalityAssessment(
        label=WorldChainFinalityLabel.INCLUDED,
        portable=Finality.OBSERVED,
        confirmations=confirmations,
        source_tag=tag,
    )


@runtime_checkable
class EthereumWalletProcessor(Protocol):
    """Minimal EVM processor surface World Chain composes over.

    Concrete implementations live under ``processors.wallets.ethereum``.  This
    protocol keeps World Chain free of a duplicate EVM parser.
    """

    def normalize_transaction(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Normalize a chain-native transaction mapping."""

        ...

    def normalize_receipt(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Normalize a chain-native receipt mapping."""

        ...


@dataclass(frozen=True, slots=True)
class WorldChainProcessor:
    """Strict composition over an Ethereum processor for World Chain ledgers.

    Does not implement SIWE, signing, or broadcast.  Ethereum parsing is reused
    exclusively through the injected processor.
    """

    network: WorldChainNetwork
    ethereum: EthereumWalletProcessor
    min_operational_confirmations: int = 1
    _chain_ref: ChainRef = field(init=False, repr=False)
    _assets: Mapping[str, WorldChainAssetManifest] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.network, WorldChainNetwork):
            raise WorldChainConfigError("network must be a WorldChainNetwork")
        if not isinstance(self.ethereum, EthereumWalletProcessor):
            raise WorldChainConfigError("ethereum must implement EthereumWalletProcessor")
        if (
            isinstance(self.min_operational_confirmations, bool)
            or self.min_operational_confirmations < 1
        ):
            raise WorldChainConfigError("min_operational_confirmations must be a positive integer")
        chain_ref = self.network.to_chain_ref()
        object.__setattr__(self, "_chain_ref", chain_ref)
        object.__setattr__(self, "_assets", asset_manifests_for_chain(chain_ref))

    @property
    def chain_ref(self) -> ChainRef:
        return self._chain_ref

    @property
    def assets(self) -> Mapping[str, WorldChainAssetManifest]:
        return self._assets

    @property
    def wld(self) -> AssetRef | None:
        manifest = self._assets.get("wld")
        return manifest.asset if manifest is not None else None

    @property
    def native_eth(self) -> AssetRef:
        return native_eth_asset(self._chain_ref)

    def validate_provider_identity(self, *, chain_id: int | str, genesis_hash: str) -> None:
        """Reject providers that do not match this World Chain network."""

        validate_world_chain_identity(
            chain_id=chain_id,
            genesis_hash=genesis_hash,
            network=self.network.network,
        )

    def classify_finality(
        self,
        *,
        block_tag: str | None = None,
        confirmations: int | None = None,
        l1_settled: bool = False,
    ) -> WorldChainFinalityAssessment:
        return classify_world_chain_finality(
            block_tag=block_tag,
            confirmations=confirmations,
            l1_settled=l1_settled,
            min_operational_confirmations=self.min_operational_confirmations,
        )

    def normalize_transaction(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Reuse Ethereum parsing and annotate World Chain identity."""

        normalized = dict(self.ethereum.normalize_transaction(raw))
        normalized["chain"] = self._chain_ref.to_dict()
        normalized["world_chain"] = {
            "chain_id": self.network.chain_id,
            "network": self.network.network,
            "settlement_layer": self.network.settlement_layer,
        }
        return normalized

    def normalize_receipt(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Reuse Ethereum receipt parsing and annotate World Chain identity."""

        normalized = dict(self.ethereum.normalize_receipt(raw))
        normalized["chain"] = self._chain_ref.to_dict()
        return normalized

    def bind_wld_asset(self) -> AssetRef:
        """Return the network-bound WLD asset or raise if this network has none."""

        if self.network.chain_id != WORLD_CHAIN_MAINNET_CHAIN_ID:
            raise WorldChainConfigError("official WLD mainnet asset is only catalogued for chain_id 480")
        manifest = build_mainnet_wld_manifest(self._chain_ref)
        assert_asset_bound_to_chain(manifest.asset, self._chain_ref)
        return manifest.asset

    def capabilities(self) -> dict[str, object]:
        return {
            "provider": "world-chain",
            "chain_id": self.network.chain_id,
            "namespace": WORLD_CHAIN_NAMESPACE,
            "composes": "ethereum",
            "siwe_bootstrap_supported": SIWE_BOOTSTRAP_SUPPORTED,
            "finality_labels": [label.value for label in WorldChainFinalityLabel],
            "assets": sorted(self._assets.keys()),
        }


def world_chain_processor_for_chain_id(
    chain_id: int | str,
    ethereum: EthereumWalletProcessor,
    *,
    min_operational_confirmations: int = 1,
) -> WorldChainProcessor:
    """Factory that binds an official network descriptor to *ethereum*."""

    return WorldChainProcessor(
        network=get_world_chain_network(chain_id),
        ethereum=ethereum,
        min_operational_confirmations=min_operational_confirmations,
    )


__all__ = [
    "SIWE_BOOTSTRAP_SUPPORTED",
    "WORLD_CHAIN_MAINNET",
    "WORLD_CHAIN_MAINNET_CHAIN_ID",
    "WORLD_CHAIN_MAINNET_GENESIS_HASH",
    "WORLD_CHAIN_MAINNET_NETWORK",
    "WORLD_CHAIN_MAINNET_SETTLEMENT",
    "WORLD_CHAIN_NAMESPACE",
    "WORLD_CHAIN_SEPOLIA",
    "WORLD_CHAIN_SEPOLIA_CHAIN_ID",
    "WORLD_CHAIN_SEPOLIA_GENESIS_HASH",
    "WORLD_CHAIN_SEPOLIA_NETWORK",
    "WORLD_CHAIN_SEPOLIA_SETTLEMENT",
    "EthereumWalletProcessor",
    "WorldChainConfigError",
    "WorldChainFinalityAssessment",
    "WorldChainFinalityLabel",
    "WorldChainNetwork",
    "WorldChainProcessor",
    "classify_world_chain_finality",
    "get_world_chain_network",
    "validate_world_chain_identity",
    "world_chain_processor_for_chain_id",
    "wld_asset",
]
