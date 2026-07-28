"""World Chain native and WLD asset manifests.

Asset identities are network- and contract-bound.  Cross-network identities
cannot collide because each :class:`~..models.AssetRef` is scoped to a
:class:`~..models.ChainRef` that includes genesis hash and chain id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..models import AssetKind, AssetRef, ChainRef


# Official World Chain WLD ERC-20 (mainnet chain id 480).
# Source: https://docs.world.org/world-chain/reference/useful-contracts
WLD_WORLD_CHAIN_MAINNET_ADDRESS = "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"
WLD_DECIMALS = 18
WLD_SYMBOL = "WLD"

# OP Stack predeploy for wrapped native ETH on World Chain.
WETH_WORLD_CHAIN_ADDRESS = "0x4200000000000000000000000000000000000006"
WETH_DECIMALS = 18
WETH_SYMBOL = "WETH"

NATIVE_ETH_REFERENCE = "native:eth"
NATIVE_ETH_DECIMALS = 18
NATIVE_ETH_SYMBOL = "ETH"

_EVM_ADDRESS_RE_PREFIX = "0x"


def normalize_evm_address(address: str) -> str:
    """Normalize a 20-byte EVM address to lowercase ``0x``-prefixed hex."""

    raw = str(address or "").strip()
    if not raw:
        raise ValueError("address must not be empty")
    if raw.startswith("0X"):
        raw = "0x" + raw[2:]
    if not raw.startswith("0x"):
        raw = "0x" + raw
    body = raw[2:]
    if len(body) != 40:
        raise ValueError("address must be 20 bytes of hex")
    try:
        int(body, 16)
    except ValueError as exc:
        raise ValueError("address must be hex") from exc
    return "0x" + body.lower()


@dataclass(frozen=True, slots=True)
class WorldChainAssetManifest:
    """Catalog entry for a World Chain asset bound to one network."""

    chain: ChainRef
    asset: AssetRef
    label: str

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "chain": self.chain.to_dict(),
            "asset": self.asset.to_dict(),
        }


def native_eth_asset(chain: ChainRef) -> AssetRef:
    """Return the native ETH asset identity for *chain*."""

    return AssetRef(
        chain=chain,
        asset_namespace="eip155",
        asset_reference=NATIVE_ETH_REFERENCE,
        decimals=NATIVE_ETH_DECIMALS,
        kind=AssetKind.NATIVE,
        symbol=NATIVE_ETH_SYMBOL,
    )


def wld_asset(chain: ChainRef, *, contract_address: str = WLD_WORLD_CHAIN_MAINNET_ADDRESS) -> AssetRef:
    """Return the WLD ERC-20 asset identity bound to *chain* and contract."""

    address = normalize_evm_address(contract_address)
    return AssetRef(
        chain=chain,
        asset_namespace="eip155",
        asset_reference=f"erc20:{address}",
        decimals=WLD_DECIMALS,
        kind=AssetKind.FUNGIBLE_TOKEN,
        symbol=WLD_SYMBOL,
    )


def weth_asset(chain: ChainRef, *, contract_address: str = WETH_WORLD_CHAIN_ADDRESS) -> AssetRef:
    """Return the WETH predeploy asset identity for *chain*."""

    address = normalize_evm_address(contract_address)
    return AssetRef(
        chain=chain,
        asset_namespace="eip155",
        asset_reference=f"erc20:{address}",
        decimals=WETH_DECIMALS,
        kind=AssetKind.FUNGIBLE_TOKEN,
        symbol=WETH_SYMBOL,
    )


def assert_asset_bound_to_chain(asset: AssetRef, chain: ChainRef) -> None:
    """Raise if *asset* is not bound to the exact *chain* identity."""

    if asset.chain.chain_ref_id != chain.chain_ref_id:
        raise ValueError("asset is not bound to the expected chain identity")


def build_mainnet_wld_manifest(chain: ChainRef) -> WorldChainAssetManifest:
    """Build the official mainnet WLD manifest for a validated World Chain ref."""

    if chain.chain_id != "480":
        raise ValueError("mainnet WLD manifest requires chain_id 480")
    asset = wld_asset(chain, contract_address=WLD_WORLD_CHAIN_MAINNET_ADDRESS)
    assert_asset_bound_to_chain(asset, chain)
    return WorldChainAssetManifest(chain=chain, asset=asset, label="wld_mainnet")


def asset_manifests_for_chain(chain: ChainRef) -> Mapping[str, WorldChainAssetManifest]:
    """Return the standard native/WETH/WLD manifests for *chain* when known."""

    manifests: dict[str, WorldChainAssetManifest] = {
        "native_eth": WorldChainAssetManifest(
            chain=chain,
            asset=native_eth_asset(chain),
            label="native_eth",
        ),
        "weth": WorldChainAssetManifest(
            chain=chain,
            asset=weth_asset(chain),
            label="weth",
        ),
    }
    if chain.chain_id == "480":
        manifests["wld"] = build_mainnet_wld_manifest(chain)
    return manifests


__all__ = [
    "NATIVE_ETH_DECIMALS",
    "NATIVE_ETH_REFERENCE",
    "NATIVE_ETH_SYMBOL",
    "WETH_DECIMALS",
    "WETH_SYMBOL",
    "WETH_WORLD_CHAIN_ADDRESS",
    "WLD_DECIMALS",
    "WLD_SYMBOL",
    "WLD_WORLD_CHAIN_MAINNET_ADDRESS",
    "WorldChainAssetManifest",
    "assert_asset_bound_to_chain",
    "asset_manifests_for_chain",
    "build_mainnet_wld_manifest",
    "native_eth_asset",
    "normalize_evm_address",
    "weth_asset",
    "wld_asset",
]
