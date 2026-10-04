"""World Chain native and WLD asset manifests.

Asset identities are network- and contract-bound.  Cross-network identities
cannot collide because each :class:`~..models.AssetRef` is scoped to a
:class:`~..models.ChainRef` that includes genesis hash and chain id.

WLD mainnet contract identity is catalogued for chain id 480 only.  Sepolia
(and any other World Chain network) requires an explicit reviewed contract
address and must never silently substitute the mainnet WLD address.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..models import AssetKind, AssetRef, ChainRef


# Official World Chain WLD ERC-20 (mainnet chain id 480).
# Source: https://docs.world.org/world-chain/reference/useful-contracts
WLD_WORLD_CHAIN_MAINNET_ADDRESS = "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"
WLD_WORLD_CHAIN_MAINNET_CHAIN_ID = "480"
WLD_DECIMALS = 18
WLD_SYMBOL = "WLD"

# OP Stack predeploy for wrapped native ETH on World Chain.
WETH_WORLD_CHAIN_ADDRESS = "0x4200000000000000000000000000000000000006"
WETH_DECIMALS = 18
WETH_SYMBOL = "WETH"

NATIVE_ETH_REFERENCE = "native:eth"
NATIVE_ETH_DECIMALS = 18
NATIVE_ETH_SYMBOL = "ETH"


class WorldChainAssetError(ValueError):
    """Raised when a World Chain asset identity is invalid or unbound."""


def normalize_evm_address(address: str) -> str:
    """Normalize a 20-byte EVM address to lowercase ``0x``-prefixed hex."""

    raw = str(address or "").strip()
    if not raw:
        raise WorldChainAssetError("address must not be empty")
    if raw.startswith("0X"):
        raw = "0x" + raw[2:]
    if not raw.startswith("0x"):
        raw = "0x" + raw
    body = raw[2:]
    if len(body) != 40:
        raise WorldChainAssetError("address must be 20 bytes of hex")
    try:
        int(body, 16)
    except ValueError as exc:
        raise WorldChainAssetError("address must be hex") from exc
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


def wld_asset(
    chain: ChainRef,
    *,
    contract_address: str | None = None,
    allow_cross_network_contract: bool = False,
) -> AssetRef:
    """Return the WLD ERC-20 asset identity bound to *chain* and contract.

    Defaults the contract to the official mainnet WLD address only when
    *chain* is World Chain mainnet (``480``).  Other networks require an
    explicit *contract_address* so mainnet WLD is never silently substituted.
    """

    chain_id = str(chain.chain_id).strip()
    if contract_address is None:
        if chain_id != WLD_WORLD_CHAIN_MAINNET_CHAIN_ID:
            raise WorldChainAssetError(
                "WLD contract_address is required outside World Chain mainnet; "
                "never substitute the mainnet WLD address for other networks"
            )
        contract_address = WLD_WORLD_CHAIN_MAINNET_ADDRESS
    elif (
        not allow_cross_network_contract
        and chain_id != WLD_WORLD_CHAIN_MAINNET_CHAIN_ID
        and normalize_evm_address(contract_address)
        == normalize_evm_address(WLD_WORLD_CHAIN_MAINNET_ADDRESS)
    ):
        raise WorldChainAssetError(
            "mainnet WLD contract must not be bound to a non-mainnet World Chain network"
        )

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
        raise WorldChainAssetError("asset is not bound to the expected chain identity")


def build_mainnet_wld_manifest(chain: ChainRef) -> WorldChainAssetManifest:
    """Build the official mainnet WLD manifest for a validated World Chain ref."""

    if str(chain.chain_id) != WLD_WORLD_CHAIN_MAINNET_CHAIN_ID:
        raise WorldChainAssetError("mainnet WLD manifest requires chain_id 480")
    asset = wld_asset(chain, contract_address=WLD_WORLD_CHAIN_MAINNET_ADDRESS)
    assert_asset_bound_to_chain(asset, chain)
    if normalize_evm_address(WLD_WORLD_CHAIN_MAINNET_ADDRESS) not in asset.asset_reference:
        raise WorldChainAssetError("mainnet WLD manifest contract mismatch")
    return WorldChainAssetManifest(chain=chain, asset=asset, label="wld_mainnet")


def build_sepolia_wld_manifest(
    chain: ChainRef,
    *,
    contract_address: str,
) -> WorldChainAssetManifest:
    """Build a Sepolia WLD manifest from an explicit reviewed contract address."""

    if str(chain.chain_id) != "4801":
        raise WorldChainAssetError("sepolia WLD manifest requires chain_id 4801")
    asset = wld_asset(chain, contract_address=contract_address)
    assert_asset_bound_to_chain(asset, chain)
    return WorldChainAssetManifest(chain=chain, asset=asset, label="wld_sepolia")


def asset_manifests_for_chain(
    chain: ChainRef,
    *,
    sepolia_wld_contract: str | None = None,
) -> Mapping[str, WorldChainAssetManifest]:
    """Return the standard native/WETH/WLD manifests for *chain* when known.

    Mainnet (480) always includes the official WLD catalog entry.  Sepolia
    includes WLD only when *sepolia_wld_contract* is supplied explicitly.
    """

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
    if str(chain.chain_id) == WLD_WORLD_CHAIN_MAINNET_CHAIN_ID:
        manifests["wld"] = build_mainnet_wld_manifest(chain)
    elif str(chain.chain_id) == "4801" and sepolia_wld_contract is not None:
        manifests["wld"] = build_sepolia_wld_manifest(
            chain, contract_address=sepolia_wld_contract
        )
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
    "WLD_WORLD_CHAIN_MAINNET_CHAIN_ID",
    "WorldChainAssetError",
    "WorldChainAssetManifest",
    "assert_asset_bound_to_chain",
    "asset_manifests_for_chain",
    "build_mainnet_wld_manifest",
    "build_sepolia_wld_manifest",
    "native_eth_asset",
    "normalize_evm_address",
    "weth_asset",
    "wld_asset",
]
