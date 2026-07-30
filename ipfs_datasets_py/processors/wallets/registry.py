"""Lazy wallet processor registry and factory (WALPROC-G600 / CRYPTOIR-G600).

This module is the integration-owner entry point for constructing chain
processors.  Importing it does **not** import optional chain packages, open
network sockets, resolve secrets, or auto-install dependencies.

Public AST surface:

* :class:`WalletProcessorRegistry`
* :class:`WalletRegistry` (cutover alias)
* :func:`get_wallet_processor`

CRYPTOIR-G600 cutover notes:

* Every registered processor declares ``supports_sign=False`` and
  ``supports_broadcast=False`` (or equivalent).
* Transaction guards are registered as inspectable module paths only; loading
  them never enables key storage or unguarded signing.
* Signing/broadcast must go through :class:`GuardService` with consumed
  admissibility capabilities — there is no ``approved=true`` escape hatch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from types import MappingProxyType
from typing import Any

from .errors import InvalidRequestError, UnsupportedCapabilityError, WalletProcessorError
from .protocols import Capabilities, Capability


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OptionalDependencyError(WalletProcessorError, ImportError):
    """Raised when a chain family needs an optional extra that is not installed.

    The message always names the pip extra.  Callers must never auto-install.
    """

    def __init__(
        self,
        *,
        family: str,
        extra: str,
        cause: BaseException | None = None,
    ) -> None:
        self.family = family
        self.extra = extra
        message = (
            f"Wallet processor family {family!r} requires optional dependency "
            f"extra {extra!r}. Install with: "
            f'pip install "ipfs_datasets_py[{extra}]". '
            "Processors never auto-install missing extras."
        )
        if cause is not None:
            message = f"{message} Underlying import error: {cause}"
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


class UnknownProcessorError(WalletProcessorError, KeyError):
    """Raised when a requested processor family or alias is not registered."""

    def __init__(self, name: str, *, known: Sequence[str] | None = None) -> None:
        self.name = name
        known_list = ", ".join(sorted(known or ()))
        suffix = f" Known families: {known_list}." if known_list else ""
        super().__init__(f"Unknown wallet processor family {name!r}.{suffix}")


class AmbiguousNetworkError(InvalidRequestError):
    """Raised when a network/chain selector matches more than one family."""

    def __init__(self, selector: str, *, matches: Sequence[str]) -> None:
        self.selector = selector
        self.matches = tuple(matches)
        listed = ", ".join(sorted(self.matches))
        super().__init__(
            f"Network selector {selector!r} is ambiguous across families "
            f"[{listed}]; pass an explicit family or disambiguating chain id."
        )


# ---------------------------------------------------------------------------
# Family catalogue (static; no chain imports)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessorFamilySpec:
    """Static description of one lazy-loaded wallet processor family."""

    family: str
    extra: str
    module: str
    aliases: frozenset[str] = field(default_factory=frozenset)
    chain_namespaces: frozenset[str] = field(default_factory=frozenset)
    features: frozenset[Capability] = field(default_factory=frozenset)
    default_network: str | None = None
    networks: frozenset[str] = field(default_factory=frozenset)
    composes: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.family.strip():
            raise InvalidRequestError("family must not be empty")
        if not self.extra.strip():
            raise InvalidRequestError("extra must not be empty")
        if not self.module.strip():
            raise InvalidRequestError("module must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def declared_capabilities(self) -> Capabilities:
        """Return inspectable capabilities without loading the chain package."""

        meta: dict[str, object] = {
            "extra": self.extra,
            "module": self.module,
            "lazy": True,
            "default_network": self.default_network,
            "networks": sorted(self.networks),
            "composes": sorted(self.composes),
            "description": self.description,
        }
        meta.update(self.metadata)
        return Capabilities(
            provider=f"registry:{self.family}",
            chain_namespaces=self.chain_namespaces,
            features=self.features,
            metadata=meta,
        )


_DEFAULT_FEATURES = frozenset(
    {
        Capability.WALLET_HISTORY,
        Capability.LEDGER_RANGE,
        Capability.BALANCES,
        Capability.FINALITY,
        Capability.DATASET_EXPORT,
    }
)

# Static family table.  Builders are bound separately so the catalogue itself
# never imports optional chain modules at module import time.
_FAMILY_SPECS: tuple[ProcessorFamilySpec, ...] = (
    ProcessorFamilySpec(
        family="bitcoin",
        extra="wallets-bitcoin",
        module="ipfs_datasets_py.processors.wallets.bitcoin",
        aliases=frozenset({"btc", "bip122"}),
        chain_namespaces=frozenset({"bip122"}),
        features=_DEFAULT_FEATURES | frozenset({Capability.REORG_RECOVERY}),
        default_network="bitcoin-mainnet",
        networks=frozenset(
            {
                "bitcoin-mainnet",
                "bitcoin-testnet",
                "bitcoin-signet",
                "bitcoin-regtest",
                "mainnet",
                "testnet",
                "signet",
                "regtest",
            }
        ),
        description="Bitcoin UTXO public-ledger processor (no signing/broadcast).",
        metadata={
            "utxo_model": True,
            "supports_sign": False,
            "supports_broadcast": False,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.bitcoin.transaction_guard"
            ),
            "transaction_guard_symbol": "BitcoinTransactionGuard",
        },
    ),
    ProcessorFamilySpec(
        family="ethereum",
        extra="wallets-ethereum",
        module="ipfs_datasets_py.processors.wallets.ethereum",
        aliases=frozenset({"eth", "evm", "eip155"}),
        chain_namespaces=frozenset({"eip155"}),
        features=_DEFAULT_FEATURES
        | frozenset(
            {
                Capability.TOKEN_TRANSFERS,
                Capability.CONTRACT_EVENTS,
                Capability.INTERNAL_TRANSFERS,
                Capability.RAW_PAYLOADS,
            }
        ),
        default_network="ethereum-mainnet",
        networks=frozenset({"ethereum-mainnet", "mainnet", "1"}),
        description="Ethereum/EVM public-ledger processor (raw JSON-RPC).",
        metadata={
            "supports_sign": False,
            "supports_broadcast": False,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.ethereum.transaction_guard"
            ),
            "transaction_guard_symbol": "EthereumTransactionGuard",
        },
    ),
    ProcessorFamilySpec(
        family="solana",
        extra="wallets-solana",
        module="ipfs_datasets_py.processors.wallets.solana",
        aliases=frozenset({"sol"}),
        chain_namespaces=frozenset({"solana"}),
        features=_DEFAULT_FEATURES
        | frozenset({Capability.TOKEN_TRANSFERS, Capability.RAW_PAYLOADS}),
        default_network="mainnet-beta",
        networks=frozenset({"mainnet-beta", "mainnet", "devnet", "testnet"}),
        description="Solana account/signature public-ledger processor.",
        metadata={
            "supports_sign": False,
            "supports_broadcast": False,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.solana.transaction_guard"
            ),
            "transaction_guard_symbol": "SolanaTransactionGuard",
        },
    ),
    ProcessorFamilySpec(
        family="xrpl",
        extra="wallets-xrpl",
        module="ipfs_datasets_py.processors.wallets.xrpl",
        aliases=frozenset({"xrp", "ripple"}),
        chain_namespaces=frozenset({"xrpl"}),
        features=_DEFAULT_FEATURES
        | frozenset({Capability.TOKEN_TRANSFERS, Capability.REORG_RECOVERY}),
        default_network="xrpl-mainnet",
        networks=frozenset(
            {
                "xrpl-mainnet",
                "xrpl-testnet",
                "xrpl-devnet",
                "mainnet",
                "testnet",
                "devnet",
            }
        ),
        description="XRPL classic-account public-ledger processor.",
        metadata={
            "supports_sign": False,
            "supports_submit": False,
            "supports_broadcast": False,
            "xaman_payloads": False,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.xrpl.transaction_guard"
            ),
            "transaction_guard_symbol": "XRPLTransactionGuard",
        },
    ),
    ProcessorFamilySpec(
        family="xaman",
        extra="wallets-xaman",
        module="ipfs_datasets_py.processors.wallets.xaman",
        aliases=frozenset({"xumm"}),
        chain_namespaces=frozenset({"xrpl"}),
        features=frozenset(
            {
                Capability.WALLET_HISTORY,
                Capability.DATASET_EXPORT,
                Capability.FINALITY,
                Capability.RAW_PAYLOADS,
            }
        ),
        default_network="xrpl-mainnet",
        networks=frozenset(
            {
                "xrpl-mainnet",
                "xrpl-testnet",
                "xrpl-devnet",
                "mainnet",
                "testnet",
                "devnet",
            }
        ),
        composes=frozenset({"xrpl"}),
        description="Xaman payload processor composed over XRPL settlement.",
        metadata={
            "supports_sign": False,
            "supports_submit": False,
            "supports_approve": False,
            "supports_broadcast": False,
            "settlement_via": "xrpl",
            "composed_xrpl": True,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.xaman.transaction_guard"
            ),
            "transaction_guard_symbol": "XamanTransactionGuard",
        },
    ),
    ProcessorFamilySpec(
        family="worldcoin",
        extra="wallets-worldcoin",
        module="ipfs_datasets_py.processors.wallets.worldcoin",
        aliases=frozenset({"world-id", "worldid", "wld-id"}),
        chain_namespaces=frozenset({"eip155"}),
        features=frozenset(
            {
                Capability.DATASET_EXPORT,
                Capability.FINALITY,
            }
        ),
        default_network=None,
        # World ID package has no unique chain-id networks; use family explicitly.
        # Chain-id selectors for World Chain live under the world-chain family.
        networks=frozenset(),
        composes=frozenset({"ethereum"}),
        description="World ID protocol package plus World Chain composition.",
        metadata={
            "world_id": True,
            "world_chain": True,
            "composes_ethereum": True,
            "siwe_bootstrap_supported": False,
            "supports_sign": False,
            "supports_broadcast": False,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.worldcoin.transaction_guard"
            ),
            "transaction_guard_symbol": "WorldcoinTransactionGuard",
        },
    ),
    ProcessorFamilySpec(
        family="world-chain",
        extra="wallets-worldcoin",
        module="ipfs_datasets_py.processors.wallets.worldcoin",
        aliases=frozenset({"worldchain", "wld-chain"}),
        chain_namespaces=frozenset({"eip155"}),
        features=frozenset(
            {
                Capability.WALLET_HISTORY,
                Capability.LEDGER_RANGE,
                Capability.TOKEN_TRANSFERS,
                Capability.FINALITY,
                Capability.DATASET_EXPORT,
            }
        ),
        default_network="world-chain-mainnet",
        networks=frozenset(
            {
                "world-chain-mainnet",
                "world-chain-sepolia",
                "480",
                "4801",
            }
        ),
        composes=frozenset({"ethereum"}),
        description="World Chain ledger processor composed over Ethereum/EVM.",
        metadata={
            "composes_ethereum": True,
            "siwe_bootstrap_supported": False,
            "block_depth_alone_is_not_finality": True,
            "supports_sign": False,
            "supports_broadcast": False,
            "transaction_guard": (
                "ipfs_datasets_py.processors.wallets.worldcoin.transaction_guard"
            ),
            "transaction_guard_symbol": "WorldcoinTransactionGuard",
        },
    ),
)

# Stable catalogue of chain transaction-guard modules for cutover inventory.
TRANSACTION_GUARD_CATALOG: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        family: MappingProxyType(
            {
                "module": str(spec.metadata.get("transaction_guard", "")),
                "symbol": str(spec.metadata.get("transaction_guard_symbol", "")),
            }
        )
        for family, spec in ((s.family, s) for s in _FAMILY_SPECS)
        if spec.metadata.get("transaction_guard")
    }
)


# ---------------------------------------------------------------------------
# Lazy builders (import chain packages only when invoked)
# ---------------------------------------------------------------------------


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must be a non-empty string")
    return value.strip()


def _import_family_module(spec: ProcessorFamilySpec) -> Any:
    try:
        return import_module(spec.module)
    except ImportError as exc:
        raise OptionalDependencyError(
            family=spec.family,
            extra=spec.extra,
            cause=exc,
        ) from exc


def _build_bitcoin(spec: ProcessorFamilySpec, *, network: str | None, options: Mapping[str, Any]) -> Any:
    module = _import_family_module(spec)
    BitcoinNetwork = module.BitcoinNetwork
    BitcoinWalletProcessor = module.BitcoinWalletProcessor

    selected = network or options.get("network") or spec.default_network
    if selected is None:
        raise InvalidRequestError("bitcoin network is required")
    key = str(selected).strip().lower()
    mapping = {
        "bitcoin-mainnet": BitcoinNetwork.MAINNET,
        "mainnet": BitcoinNetwork.MAINNET,
        "bitcoin-testnet": BitcoinNetwork.TESTNET,
        "testnet": BitcoinNetwork.TESTNET,
        "bitcoin-signet": BitcoinNetwork.SIGNET,
        "signet": BitcoinNetwork.SIGNET,
        "bitcoin-regtest": BitcoinNetwork.REGTEST,
        "regtest": BitcoinNetwork.REGTEST,
    }
    if key not in mapping:
        raise InvalidRequestError(
            f"unknown bitcoin network {selected!r}; "
            f"expected one of {sorted(mapping)}"
        )
    return BitcoinWalletProcessor(
        network=mapping[key],
        provider=options.get("provider"),
        normalizer=options.get("normalizer"),
        finality_policy=options.get("finality_policy"),
        utxo_set=options.get("utxo_set"),
        name=str(options.get("name") or "bitcoin-wallet-processor"),
    )


def _build_ethereum(spec: ProcessorFamilySpec, *, network: str | None, options: Mapping[str, Any]) -> Any:
    module = _import_family_module(spec)
    ETHEREUM_MAINNET = module.ETHEREUM_MAINNET
    EvmNetwork = module.EvmNetwork
    EthereumNormalizer = module.EthereumNormalizer
    EthereumLedgerProvider = module.EthereumLedgerProvider
    normalize_address = module.normalize_address
    normalize_hash = module.normalize_hash

    selected = network or options.get("network") or spec.default_network
    key = str(selected).strip().lower() if selected is not None else "ethereum-mainnet"
    if key in {"ethereum-mainnet", "mainnet", "1"}:
        net = ETHEREUM_MAINNET
    elif isinstance(options.get("evm_network"), EvmNetwork):
        net = options["evm_network"]
    else:
        raise InvalidRequestError(
            f"unknown ethereum network {selected!r}; "
            "pass an explicit EvmNetwork via options['evm_network'] for non-mainnet"
        )

    normalizer = options.get("normalizer") or EthereumNormalizer(network=net)
    provider = options.get("provider")

    class EthereumWalletFacade:
        """Registry-constructed ethereum surface for World Chain composition.

        Satisfies ``worldcoin.EthereumWalletProcessor`` (normalize_transaction /
        normalize_receipt) without moving domain parsing into the registry.
        """

        __slots__ = ("_network", "_normalizer", "_provider", "_capabilities", "name")

        def __init__(self) -> None:
            self._network = net
            self._normalizer = normalizer
            self._provider = provider
            self.name = str(options.get("name") or "ethereum-wallet-processor")
            features = set(normalizer.capabilities.features)
            if provider is not None:
                features |= set(getattr(provider, "capabilities", normalizer.capabilities).features)
            self._capabilities = Capabilities(
                provider=self.name,
                chain_namespaces=frozenset({"eip155"}),
                features=frozenset(features),
                metadata={
                    "network": "ethereum-mainnet" if net is ETHEREUM_MAINNET else str(net.chain_id),
                    "chain_id": str(net.chain_id),
                    "composes": (),
                    "supports_sign": False,
                    "supports_broadcast": False,
                    "family": "ethereum",
                },
            )

        @property
        def capabilities(self) -> Capabilities:
            return self._capabilities

        @property
        def network(self) -> Any:
            return self._network

        @property
        def normalizer(self) -> Any:
            return self._normalizer

        @property
        def provider(self) -> Any:
            return self._provider

        def normalize_transaction(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
            if not isinstance(raw, Mapping):
                raise InvalidRequestError("raw transaction must be a mapping")
            tx_hash = raw.get("hash") or raw.get("transactionHash") or raw.get("transaction_hash")
            from_addr = raw.get("from")
            to_addr = raw.get("to")
            value = raw.get("value", "0x0")
            return {
                "hash": normalize_hash(tx_hash, field="hash") if tx_hash else None,
                "from": normalize_address(from_addr, field="from") if from_addr else None,
                "to": normalize_address(to_addr, field="to") if to_addr else None,
                "value": value,
                "chain_id": self._network.chain_id,
                "parsed_by": "ethereum",
                "status": raw.get("status", "unknown"),
            }

        def normalize_receipt(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
            if not isinstance(raw, Mapping):
                raise InvalidRequestError("raw receipt must be a mapping")
            tx_hash = raw.get("transactionHash") or raw.get("transaction_hash") or raw.get("hash")
            return {
                "transaction_hash": (
                    normalize_hash(tx_hash, field="transactionHash") if tx_hash else None
                ),
                "status": raw.get("status"),
                "logs": list(raw.get("logs") or ()),
                "chain_id": self._network.chain_id,
                "parsed_by": "ethereum",
            }

        def get_capabilities(self) -> dict[str, object]:
            caps = self._capabilities
            return {
                "name": self.name,
                "family": "ethereum",
                "provider": caps.provider,
                "chain_namespaces": sorted(caps.chain_namespaces),
                "features": sorted(f.value for f in caps.features),
                "metadata": dict(caps.metadata),
            }

    # Keep EthereumLedgerProvider referenced so static analysis and callers can
    # inject a provider constructed from the same package.
    _ = EthereumLedgerProvider
    return EthereumWalletFacade()


def _build_solana(spec: ProcessorFamilySpec, *, network: str | None, options: Mapping[str, Any]) -> Any:
    module = _import_family_module(spec)
    SOLANA_MAINNET = module.SOLANA_MAINNET
    SolanaNetwork = module.SolanaNetwork
    SolanaNormalizer = module.SolanaNormalizer
    SolanaLedgerProvider = module.SolanaLedgerProvider
    SolanaFinalityPolicy = module.SolanaFinalityPolicy

    selected = network or options.get("network") or spec.default_network or "mainnet-beta"
    key = str(selected).strip().lower()
    if key in {"mainnet-beta", "mainnet"}:
        net = SOLANA_MAINNET
    elif isinstance(options.get("solana_network"), SolanaNetwork):
        net = options["solana_network"]
    else:
        raise InvalidRequestError(
            f"unknown solana network {selected!r}; "
            "pass SolanaNetwork via options['solana_network'] for non-mainnet"
        )

    normalizer = options.get("normalizer") or SolanaNormalizer(network=net)
    finality = options.get("finality_policy") or SolanaFinalityPolicy()
    provider = options.get("provider")

    class SolanaWalletFacade:
        """Registry-constructed Solana surface with explicit capabilities."""

        __slots__ = ("_network", "_normalizer", "_provider", "_finality", "_capabilities", "name")

        def __init__(self) -> None:
            self._network = net
            self._normalizer = normalizer
            self._provider = provider
            self._finality = finality
            self.name = str(options.get("name") or "solana-wallet-processor")
            features = {
                Capability.FINALITY,
                Capability.DATASET_EXPORT,
                Capability.TOKEN_TRANSFERS,
            }
            if provider is not None:
                features |= {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.BALANCES,
                    Capability.RAW_PAYLOADS,
                }
            self._capabilities = Capabilities(
                provider=self.name,
                chain_namespaces=frozenset({"solana"}),
                features=frozenset(features),
                metadata={
                    "network": getattr(net, "chain_id", str(net)),
                    "family": "solana",
                    "supports_sign": False,
                    "supports_broadcast": False,
                },
            )

        @property
        def capabilities(self) -> Capabilities:
            return self._capabilities

        @property
        def network(self) -> Any:
            return self._network

        @property
        def normalizer(self) -> Any:
            return self._normalizer

        @property
        def provider(self) -> Any:
            return self._provider

        @property
        def finality_policy(self) -> Any:
            return self._finality

        def get_capabilities(self) -> dict[str, object]:
            caps = self._capabilities
            return {
                "name": self.name,
                "family": "solana",
                "provider": caps.provider,
                "chain_namespaces": sorted(caps.chain_namespaces),
                "features": sorted(f.value for f in caps.features),
                "metadata": dict(caps.metadata),
            }

    _ = SolanaLedgerProvider
    return SolanaWalletFacade()


def _build_xrpl(spec: ProcessorFamilySpec, *, network: str | None, options: Mapping[str, Any]) -> Any:
    module = _import_family_module(spec)
    XRPLNetwork = module.XRPLNetwork
    XRPLWalletProcessor = module.XRPLWalletProcessor

    selected = network or options.get("network") or spec.default_network
    key = str(selected).strip().lower() if selected is not None else "xrpl-mainnet"
    mapping = {
        "xrpl-mainnet": XRPLNetwork.MAINNET,
        "mainnet": XRPLNetwork.MAINNET,
        "xrpl-testnet": XRPLNetwork.TESTNET,
        "testnet": XRPLNetwork.TESTNET,
        "xrpl-devnet": XRPLNetwork.DEVNET,
        "devnet": XRPLNetwork.DEVNET,
    }
    if key not in mapping:
        raise InvalidRequestError(
            f"unknown xrpl network {selected!r}; expected one of {sorted(mapping)}"
        )
    return XRPLWalletProcessor(
        network=mapping[key],
        provider=options.get("provider"),
        normalizer=options.get("normalizer"),
        finality_policy=options.get("finality_policy"),
        privacy=options.get("privacy"),
        name=str(options.get("name") or "xrpl-wallet-processor"),
    )


def _build_xaman(spec: ProcessorFamilySpec, *, network: str | None, options: Mapping[str, Any]) -> Any:
    """Xaman always composes XRPL; settlement is never treated as API success."""

    module = _import_family_module(spec)
    XRPLNetwork = import_module("ipfs_datasets_py.processors.wallets.xrpl").XRPLNetwork
    XRPLWalletProcessor = import_module(
        "ipfs_datasets_py.processors.wallets.xrpl"
    ).XRPLWalletProcessor
    XamanWalletProcessor = module.XamanWalletProcessor

    selected = network or options.get("network") or spec.default_network
    key = str(selected).strip().lower() if selected is not None else "xrpl-mainnet"
    mapping = {
        "xrpl-mainnet": XRPLNetwork.MAINNET,
        "mainnet": XRPLNetwork.MAINNET,
        "xrpl-testnet": XRPLNetwork.TESTNET,
        "testnet": XRPLNetwork.TESTNET,
        "xrpl-devnet": XRPLNetwork.DEVNET,
        "devnet": XRPLNetwork.DEVNET,
    }
    if key not in mapping:
        raise InvalidRequestError(
            f"unknown xaman network {selected!r}; expected one of {sorted(mapping)}"
        )
    net = mapping[key]
    xrpl_processor = options.get("xrpl_processor")
    if xrpl_processor is None:
        xrpl_processor = XRPLWalletProcessor(network=net, provider=options.get("xrpl_provider"))
    return XamanWalletProcessor(
        network=net,
        payload_provider=options.get("payload_provider"),
        xrpl_processor=xrpl_processor,
        privacy=options.get("privacy"),
        name=str(options.get("name") or "xaman-wallet-processor"),
    )


def _build_world_chain(
    spec: ProcessorFamilySpec,
    *,
    network: str | None,
    options: Mapping[str, Any],
) -> Any:
    """World Chain always composes an Ethereum processor — never reimplements EVM."""

    module = _import_family_module(spec)
    WorldChainProcessor = module.WorldChainProcessor
    world_chain_processor_for_chain_id = module.world_chain_processor_for_chain_id
    get_world_chain_network = module.get_world_chain_network
    WORLD_CHAIN_MAINNET_CHAIN_ID = module.WORLD_CHAIN_MAINNET_CHAIN_ID
    WORLD_CHAIN_SEPOLIA_CHAIN_ID = module.WORLD_CHAIN_SEPOLIA_CHAIN_ID

    selected = network or options.get("network") or options.get("chain_id") or spec.default_network
    if selected is None:
        raise InvalidRequestError("world-chain network or chain_id is required")
    key = str(selected).strip().lower()
    chain_id_map = {
        "world-chain-mainnet": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "mainnet": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "480": WORLD_CHAIN_MAINNET_CHAIN_ID,
        str(WORLD_CHAIN_MAINNET_CHAIN_ID): WORLD_CHAIN_MAINNET_CHAIN_ID,
        "world-chain-sepolia": WORLD_CHAIN_SEPOLIA_CHAIN_ID,
        "sepolia": WORLD_CHAIN_SEPOLIA_CHAIN_ID,
        "4801": WORLD_CHAIN_SEPOLIA_CHAIN_ID,
        str(WORLD_CHAIN_SEPOLIA_CHAIN_ID): WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    }
    if key not in chain_id_map:
        # Allow numeric pass-through for reviewed chain ids only via factory.
        try:
            chain_id: int | str = int(key)
        except ValueError as exc:
            raise InvalidRequestError(
                f"unknown world-chain network {selected!r}; "
                f"expected one of {sorted(chain_id_map)}"
            ) from exc
    else:
        chain_id = chain_id_map[key]

    ethereum = options.get("ethereum")
    if ethereum is None:
        ethereum = _build_ethereum(
            _FAMILY_BY_NAME["ethereum"],
            network="ethereum-mainnet",
            options={},
        )

    return world_chain_processor_for_chain_id(
        chain_id,
        ethereum,
        min_operational_confirmations=int(options.get("min_operational_confirmations") or 1),
        sepolia_wld_contract=options.get("sepolia_wld_contract"),
    )


def _build_worldcoin(spec: ProcessorFamilySpec, *, network: str | None, options: Mapping[str, Any]) -> Any:
    """Return a World ID package handle; World Chain is available via composition."""

    module = _import_family_module(spec)
    # Prefer World Chain composition when a chain network is requested; otherwise
    # expose the worldcoin package surface for protocol utilities.
    selected = network or options.get("network") or options.get("chain_id")
    if selected is not None or options.get("ethereum") is not None:
        return _build_world_chain(spec, network=network or "world-chain-mainnet", options=options)

    class WorldcoinPackageFacade:
        """Lazy worldcoin package handle with explicit capability metadata."""

        __slots__ = ("_module", "_capabilities", "name")

        def __init__(self) -> None:
            self._module = module
            self.name = str(options.get("name") or "worldcoin-package")
            self._capabilities = Capabilities(
                provider=self.name,
                chain_namespaces=frozenset({"eip155"}),
                features=frozenset({Capability.DATASET_EXPORT, Capability.FINALITY}),
                metadata={
                    "family": "worldcoin",
                    "world_id": True,
                    "world_chain_available": True,
                    "composes_ethereum": True,
                    "siwe_bootstrap_supported": False,
                    "module": spec.module,
                },
            )

        @property
        def capabilities(self) -> Capabilities:
            return self._capabilities

        @property
        def module(self) -> Any:
            return self._module

        def world_chain_processor(self, **kwargs: Any) -> Any:
            return _build_world_chain(spec, network=kwargs.pop("network", None), options=kwargs)

        def get_capabilities(self) -> dict[str, object]:
            caps = self._capabilities
            return {
                "name": self.name,
                "family": "worldcoin",
                "provider": caps.provider,
                "chain_namespaces": sorted(caps.chain_namespaces),
                "features": sorted(f.value for f in caps.features),
                "metadata": dict(caps.metadata),
            }

    return WorldcoinPackageFacade()


_Builder = Callable[[ProcessorFamilySpec, str | None, Mapping[str, Any]], Any]

_BUILDERS: dict[str, _Builder] = {
    "bitcoin": lambda s, n, o: _build_bitcoin(s, network=n, options=o),
    "ethereum": lambda s, n, o: _build_ethereum(s, network=n, options=o),
    "solana": lambda s, n, o: _build_solana(s, network=n, options=o),
    "xrpl": lambda s, n, o: _build_xrpl(s, network=n, options=o),
    "xaman": lambda s, n, o: _build_xaman(s, network=n, options=o),
    "worldcoin": lambda s, n, o: _build_worldcoin(s, network=n, options=o),
    "world-chain": lambda s, n, o: _build_world_chain(s, network=n, options=o),
}

_FAMILY_BY_NAME: dict[str, ProcessorFamilySpec] = {s.family: s for s in _FAMILY_SPECS}
_ALIAS_TO_FAMILY: dict[str, str] = {}
for _spec in _FAMILY_SPECS:
    _ALIAS_TO_FAMILY[_spec.family.lower()] = _spec.family
    for _alias in _spec.aliases:
        _ALIAS_TO_FAMILY[_alias.lower()] = _spec.family


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class WalletProcessorRegistry:
    """Lazy factory for wallet processor families.

    * Chain packages load only when :meth:`get_wallet_processor` is called.
    * Capabilities for each family are inspectable without loading.
    * Unknown families and ambiguous network selectors fail closed.
    * Missing optional packages raise :class:`OptionalDependencyError` that
      names the extra; nothing is auto-installed.
    * Exactly one generic adapter (core ``ProcessorProtocol``) lives under
      ``adapters/processor_protocol.py``; this registry does **not** wire the
      rejected legacy ``can_process`` surface.
    """

    def __init__(
        self,
        *,
        specs: Sequence[ProcessorFamilySpec] | None = None,
        builders: Mapping[str, _Builder] | None = None,
    ) -> None:
        family_specs = tuple(specs) if specs is not None else _FAMILY_SPECS
        self._specs: dict[str, ProcessorFamilySpec] = {
            spec.family: spec for spec in family_specs
        }
        self._aliases: dict[str, str] = {}
        for spec in family_specs:
            self._aliases[spec.family.lower()] = spec.family
            for alias in spec.aliases:
                self._aliases[alias.lower()] = spec.family
        self._builders: dict[str, _Builder] = dict(builders or _BUILDERS)
        self._instance_cache: MutableMapping[tuple[str, str | None], Any] = {}
        self._cache_enabled = False

    # -- catalogue ---------------------------------------------------------

    def list_families(self) -> tuple[str, ...]:
        """Return registered family names in stable order."""

        return tuple(sorted(self._specs))

    def list_specs(self) -> tuple[ProcessorFamilySpec, ...]:
        return tuple(self._specs[name] for name in self.list_families())

    def resolve_family(self, name: str) -> str:
        """Normalize a family name or alias; raise if unknown."""

        key = _require_str(name, "family").lower()
        family = self._aliases.get(key)
        if family is None:
            raise UnknownProcessorError(name, known=self.list_families())
        return family

    def get_spec(self, name: str) -> ProcessorFamilySpec:
        family = self.resolve_family(name)
        return self._specs[family]

    def capabilities_for(self, name: str) -> Capabilities:
        """Return declared capabilities without importing the chain package."""

        return self.get_spec(name).declared_capabilities()

    def capabilities_catalog(self) -> Mapping[str, Capabilities]:
        """Map family name → declared capabilities (no chain imports)."""

        return MappingProxyType(
            {family: self.capabilities_for(family) for family in self.list_families()}
        )

    def required_extra(self, name: str) -> str:
        return self.get_spec(name).extra

    def list_transaction_guards(self) -> Mapping[str, Mapping[str, str]]:
        """Return registered transaction-guard module paths without loading them.

        Signing remains disabled on every processor; guards only issue
        exact-candidate admissibility evidence for an external custody system.
        """

        return MappingProxyType(
            {
                family: MappingProxyType(dict(entry))
                for family, entry in TRANSACTION_GUARD_CATALOG.items()
                if family in self._specs
            }
        )

    def transaction_guard_module(self, name: str) -> str:
        """Return the transaction-guard module path for *name* (no import)."""

        family = self.resolve_family(name)
        entry = TRANSACTION_GUARD_CATALOG.get(family)
        if entry is None or not entry.get("module"):
            raise UnsupportedCapabilityError(
                f"family {family!r} does not declare a transaction guard"
            )
        return str(entry["module"])

    def asserts_no_signing_authority(self, name: str | None = None) -> bool:
        """Return True when the named family (or all families) forbids signing.

        CRYPTOIR-G600 invariant: processors never gain key storage or unguarded
        sign/broadcast authority through the registry cutover.
        """

        families = (self.resolve_family(name),) if name is not None else self.list_families()
        for family in families:
            meta = dict(self.get_spec(family).metadata)
            if meta.get("supports_sign") is True or meta.get("supports_broadcast") is True:
                return False
            if meta.get("supports_submit") is True or meta.get("supports_approve") is True:
                return False
        return True

    # -- resolution --------------------------------------------------------

    def resolve_family_for_network(
        self,
        *,
        network: str | None = None,
        chain_namespace: str | None = None,
        chain_id: str | int | None = None,
        family: str | None = None,
    ) -> str:
        """Resolve a unique family for a network/chain selector.

        Raises:
            UnknownProcessorError: no match
            AmbiguousNetworkError: more than one match
        """

        if family is not None:
            return self.resolve_family(family)

        matches: list[str] = []
        net_key = network.strip().lower() if isinstance(network, str) and network.strip() else None
        ns_key = (
            chain_namespace.strip().lower()
            if isinstance(chain_namespace, str) and chain_namespace.strip()
            else None
        )
        cid_key = str(chain_id).strip().lower() if chain_id is not None else None

        for spec in self._specs.values():
            if net_key is not None and net_key in {n.lower() for n in spec.networks}:
                matches.append(spec.family)
                continue
            if cid_key is not None and cid_key in {n.lower() for n in spec.networks}:
                matches.append(spec.family)
                continue
            if (
                ns_key is not None
                and net_key is None
                and cid_key is None
                and ns_key in {n.lower() for n in spec.chain_namespaces}
            ):
                matches.append(spec.family)

        unique = sorted(set(matches))
        if not unique:
            selector = network or chain_namespace or (str(chain_id) if chain_id is not None else "")
            raise UnknownProcessorError(
                selector or "<empty>",
                known=self.list_families(),
            )
        if len(unique) > 1:
            selector = network or chain_namespace or (str(chain_id) if chain_id is not None else "")
            raise AmbiguousNetworkError(selector, matches=unique)
        return unique[0]

    # -- construction ------------------------------------------------------

    def get_wallet_processor(
        self,
        family: str,
        *,
        network: str | None = None,
        require_capability: Capability | None = None,
        **options: Any,
    ) -> Any:
        """Lazily construct a processor for *family*.

        Chain modules are imported only on this call path.  Optional dependency
        failures identify the pip extra and never auto-install packages.
        """

        resolved = self.resolve_family(family)
        spec = self._specs[resolved]
        builder = self._builders.get(resolved)
        if builder is None:
            raise UnknownProcessorError(resolved, known=tuple(self._builders))

        if network is not None:
            network = _require_str(network, "network")
            allowed = {n.lower() for n in spec.networks}
            # Permit pass-through for builders that accept explicit network objects
            # via options; still reject clearly invalid bare strings when the
            # family documents a closed network set and no override is present.
            if (
                allowed
                and network.lower() not in allowed
                and "evm_network" not in options
                and "solana_network" not in options
                and "chain_id" not in options
            ):
                raise InvalidRequestError(
                    f"network {network!r} is not valid for family {resolved!r}; "
                    f"expected one of {sorted(spec.networks)}"
                )

        if require_capability is not None:
            declared = spec.declared_capabilities()
            if not declared.supports(require_capability):
                raise UnsupportedCapabilityError(
                    f"family {resolved!r} does not declare capability "
                    f"{require_capability.value!r}"
                )

        cache_key = (resolved, network)
        if self._cache_enabled and cache_key in self._instance_cache:
            return self._instance_cache[cache_key]

        processor = builder(spec, network, MappingProxyType(dict(options)))
        if self._cache_enabled:
            self._instance_cache[cache_key] = processor
        return processor

    def enable_instance_cache(self, enabled: bool = True) -> None:
        """Opt-in processor instance cache (off by default for test isolation)."""

        self._cache_enabled = bool(enabled)
        if not enabled:
            self._instance_cache.clear()

    def clear_cache(self) -> None:
        self._instance_cache.clear()


_DEFAULT_REGISTRY: WalletProcessorRegistry | None = None


def default_registry() -> WalletProcessorRegistry:
    """Return the process-wide default lazy registry."""

    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = WalletProcessorRegistry()
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Drop the process-wide registry (intended for tests)."""

    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None


def get_wallet_processor(
    family: str,
    *,
    network: str | None = None,
    require_capability: Capability | None = None,
    **options: Any,
) -> Any:
    """Module-level factory: ``WalletProcessorRegistry.get_wallet_processor``."""

    return default_registry().get_wallet_processor(
        family,
        network=network,
        require_capability=require_capability,
        **options,
    )


# CRYPTOIR-G600 AST alias: WalletRegistry is the cutover name for the same
# serialized sole-owner registry surface.
WalletRegistry = WalletProcessorRegistry


__all__ = [
    "AmbiguousNetworkError",
    "OptionalDependencyError",
    "ProcessorFamilySpec",
    "TRANSACTION_GUARD_CATALOG",
    "UnknownProcessorError",
    "WalletProcessorRegistry",
    "WalletRegistry",
    "default_registry",
    "get_wallet_processor",
    "reset_default_registry",
]
