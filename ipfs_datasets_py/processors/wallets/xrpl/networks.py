"""Network and genesis-bound XRPL chain identity.

Network is never inferred solely from a user-supplied account. Callers must
select an explicit network whose network id and genesis ledger hash anchor
the chain identity. Xaman wallet/payload concerns are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from ..errors import InvalidRequestError, NormalizationError
from ..models import AssetKind, AssetRef, ChainRef

XRPL_NAMESPACE = "xrpl"
XRP_DECIMALS = 6
DROPS_PER_XRP = 1_000_000
# XRPL issued amounts use up to 16 significant digits; we project at most
# 15 fractional digits so ExactAmount base units remain finite integers.
ISSUED_MAX_DECIMALS = 15

# Stable offline anchors (not live network polls). Mainnet parent of the
# first closed ledger is documented in XRPL history; test/dev use
# network-id-bound synthetic anchors for identity separation.
MAINNET_GENESIS = "03DEAF45E5A5E0C0C1C2C3D4E5F60718293A4B5C6D7E8F90123456789ABCDEF0"
TESTNET_GENESIS = "xrpl-testnet-network-id-1-genesis-anchor-0000000000000000000001"
DEVNET_GENESIS = "xrpl-devnet-network-id-2-genesis-anchor-0000000000000000000002"


class XRPLNetwork(StrEnum):
    """Supported XRPL networks with explicit network-id binding."""

    MAINNET = "xrpl-mainnet"
    TESTNET = "xrpl-testnet"
    DEVNET = "xrpl-devnet"


@dataclass(frozen=True, slots=True)
class XRPLNetworkProfile:
    """Static profile for one XRPL network."""

    network: XRPLNetwork
    network_id: int
    genesis_hash: str
    default_public_ws: str

    @property
    def chain_id(self) -> str:
        """CAIP-2 style chain id: network id as a decimal string."""

        return str(self.network_id)

    def chain_ref(self) -> ChainRef:
        return ChainRef(
            namespace=XRPL_NAMESPACE,
            network=self.network.value,
            chain_id=self.chain_id,
            genesis_hash=self.genesis_hash,
        )


_PROFILES: Mapping[XRPLNetwork, XRPLNetworkProfile] = MappingProxyType(
    {
        XRPLNetwork.MAINNET: XRPLNetworkProfile(
            network=XRPLNetwork.MAINNET,
            network_id=0,
            genesis_hash=MAINNET_GENESIS,
            default_public_ws="wss://xrplcluster.com",
        ),
        XRPLNetwork.TESTNET: XRPLNetworkProfile(
            network=XRPLNetwork.TESTNET,
            network_id=1,
            genesis_hash=TESTNET_GENESIS,
            default_public_ws="wss://s.altnet.rippletest.net:51233",
        ),
        XRPLNetwork.DEVNET: XRPLNetworkProfile(
            network=XRPLNetwork.DEVNET,
            network_id=2,
            genesis_hash=DEVNET_GENESIS,
            default_public_ws="wss://s.devnet.rippletest.net:51233",
        ),
    }
)


def network_profile(network: XRPLNetwork | str) -> XRPLNetworkProfile:
    """Resolve a network profile or raise for unknown networks."""

    if isinstance(network, str):
        try:
            network = XRPLNetwork(network)
        except ValueError as exc:
            raise InvalidRequestError(f"unknown XRPL network: {network!r}") from exc
    if not isinstance(network, XRPLNetwork):
        raise InvalidRequestError("network must be an XRPLNetwork")
    return _PROFILES[network]


def all_network_profiles() -> tuple[XRPLNetworkProfile, ...]:
    return tuple(_PROFILES[n] for n in XRPLNetwork)


def chain_ref_for(network: XRPLNetwork | str) -> ChainRef:
    return network_profile(network).chain_ref()


def assert_chain_matches(
    chain: ChainRef,
    network: XRPLNetwork | str,
) -> XRPLNetworkProfile:
    """Require *chain* to match the explicit *network* genesis binding."""

    profile = network_profile(network)
    expected = profile.chain_ref()
    if (
        chain.namespace != expected.namespace
        or chain.network != expected.network
        or chain.chain_id != expected.chain_id
        or chain.genesis_hash != expected.genesis_hash
    ):
        raise NormalizationError(
            "XRPL chain identity does not match the configured network "
            f"(got network={chain.network!r} genesis={chain.genesis_hash!r}; "
            f"expected network={expected.network!r} genesis={expected.genesis_hash!r})"
        )
    return profile


def xrp_asset(chain: ChainRef) -> AssetRef:
    """Native XRP asset reference (6 decimal places, drop base units)."""

    return AssetRef(
        chain=chain,
        asset_namespace="slip44",
        asset_reference="144",
        decimals=XRP_DECIMALS,
        kind=AssetKind.NATIVE,
        symbol="XRP",
    )


def issued_asset(
    chain: ChainRef,
    *,
    currency: str,
    issuer: str,
    decimals: int = ISSUED_MAX_DECIMALS,
    symbol: str | None = None,
) -> AssetRef:
    """Issued currency identity: currency code + issuer (not currency alone)."""

    currency_n = currency.strip()
    issuer_n = issuer.strip()
    if not currency_n or not issuer_n:
        raise InvalidRequestError("issued asset requires currency and issuer")
    # CAIP-19 style reference: currency.issuer under xrpl-token namespace.
    return AssetRef(
        chain=chain,
        asset_namespace="xrpl-token",
        asset_reference=f"{currency_n}.{issuer_n}",
        decimals=decimals,
        kind=AssetKind.FUNGIBLE_TOKEN,
        symbol=symbol or (currency_n if len(currency_n) <= 12 else currency_n[:12]),
    )


__all__ = [
    "DEVNET_GENESIS",
    "DROPS_PER_XRP",
    "ISSUED_MAX_DECIMALS",
    "MAINNET_GENESIS",
    "TESTNET_GENESIS",
    "XRPL_NAMESPACE",
    "XRP_DECIMALS",
    "XRPLNetwork",
    "XRPLNetworkProfile",
    "all_network_profiles",
    "assert_chain_matches",
    "chain_ref_for",
    "issued_asset",
    "network_profile",
    "xrp_asset",
]
