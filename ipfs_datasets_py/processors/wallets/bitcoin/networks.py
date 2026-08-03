"""Network and genesis-bound Bitcoin chain identity (bip122).

Network is never inferred solely from a user-supplied address. Callers must
select an explicit network whose genesis hash anchors the chain identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from ..errors import InvalidRequestError, NormalizationError
from ..models import AssetKind, AssetRef, ChainRef

BITCOIN_NAMESPACE = "bip122"
BTC_DECIMALS = 8
SLIP44_BTC = "0"

# BIP122 chain_id values are the first 16 bytes (32 hex chars) of the genesis block hash.
MAINNET_GENESIS = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
TESTNET_GENESIS = "000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943"
SIGNET_GENESIS = "00000008819873e925422c1ff0f99f7cc9bbb232af63a077a480a3633bee1ef6"
REGTEST_GENESIS = "0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206"


class BitcoinNetwork(StrEnum):
    """Supported Bitcoin networks with explicit genesis binding."""

    MAINNET = "bitcoin-mainnet"
    TESTNET = "bitcoin-testnet"
    SIGNET = "bitcoin-signet"
    REGTEST = "bitcoin-regtest"


@dataclass(frozen=True, slots=True)
class BitcoinNetworkProfile:
    """Static profile for one Bitcoin network."""

    network: BitcoinNetwork
    genesis_hash: str
    hrp: str
    legacy_p2pkh_versions: frozenset[int]
    legacy_p2sh_versions: frozenset[int]
    default_port: int

    @property
    def chain_id(self) -> str:
        """BIP122 chain id: first 32 hex characters of the genesis hash."""

        return self.genesis_hash[:32]

    def chain_ref(self) -> ChainRef:
        return ChainRef(
            namespace=BITCOIN_NAMESPACE,
            network=self.network.value,
            chain_id=self.chain_id,
            genesis_hash=self.genesis_hash,
        )


_PROFILES: Mapping[BitcoinNetwork, BitcoinNetworkProfile] = MappingProxyType(
    {
        BitcoinNetwork.MAINNET: BitcoinNetworkProfile(
            network=BitcoinNetwork.MAINNET,
            genesis_hash=MAINNET_GENESIS,
            hrp="bc",
            legacy_p2pkh_versions=frozenset({0x00}),
            legacy_p2sh_versions=frozenset({0x05}),
            default_port=8332,
        ),
        BitcoinNetwork.TESTNET: BitcoinNetworkProfile(
            network=BitcoinNetwork.TESTNET,
            genesis_hash=TESTNET_GENESIS,
            hrp="tb",
            legacy_p2pkh_versions=frozenset({0x6F}),
            legacy_p2sh_versions=frozenset({0xC4}),
            default_port=18332,
        ),
        BitcoinNetwork.SIGNET: BitcoinNetworkProfile(
            network=BitcoinNetwork.SIGNET,
            genesis_hash=SIGNET_GENESIS,
            hrp="tb",
            legacy_p2pkh_versions=frozenset({0x6F}),
            legacy_p2sh_versions=frozenset({0xC4}),
            default_port=38332,
        ),
        BitcoinNetwork.REGTEST: BitcoinNetworkProfile(
            network=BitcoinNetwork.REGTEST,
            genesis_hash=REGTEST_GENESIS,
            hrp="bcrt",
            legacy_p2pkh_versions=frozenset({0x6F}),
            legacy_p2sh_versions=frozenset({0xC4}),
            default_port=18443,
        ),
    }
)


def network_profile(network: BitcoinNetwork | str) -> BitcoinNetworkProfile:
    """Resolve a network profile or raise for unknown networks."""

    if isinstance(network, str):
        try:
            network = BitcoinNetwork(network)
        except ValueError as exc:
            raise InvalidRequestError(f"unknown Bitcoin network: {network!r}") from exc
    if not isinstance(network, BitcoinNetwork):
        raise InvalidRequestError("network must be a BitcoinNetwork")
    return _PROFILES[network]


def all_network_profiles() -> tuple[BitcoinNetworkProfile, ...]:
    return tuple(_PROFILES[n] for n in BitcoinNetwork)


def chain_ref_for(network: BitcoinNetwork | str) -> ChainRef:
    return network_profile(network).chain_ref()


def assert_chain_matches(
    chain: ChainRef,
    network: BitcoinNetwork | str,
) -> BitcoinNetworkProfile:
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
            "Bitcoin chain identity does not match the configured network "
            f"(got network={chain.network!r} genesis={chain.genesis_hash!r}; "
            f"expected network={expected.network!r} genesis={expected.genesis_hash!r})"
        )
    return profile


def btc_asset(chain: ChainRef) -> AssetRef:
    """Native BTC asset reference (8 decimal places, satoshi base units)."""

    return AssetRef(
        chain=chain,
        asset_namespace="slip44",
        asset_reference=SLIP44_BTC,
        decimals=BTC_DECIMALS,
        kind=AssetKind.NATIVE,
        symbol="BTC",
    )


__all__ = [
    "BITCOIN_NAMESPACE",
    "BTC_DECIMALS",
    "MAINNET_GENESIS",
    "REGTEST_GENESIS",
    "SIGNET_GENESIS",
    "SLIP44_BTC",
    "TESTNET_GENESIS",
    "BitcoinNetwork",
    "BitcoinNetworkProfile",
    "all_network_profiles",
    "assert_chain_matches",
    "btc_asset",
    "chain_ref_for",
    "network_profile",
]
