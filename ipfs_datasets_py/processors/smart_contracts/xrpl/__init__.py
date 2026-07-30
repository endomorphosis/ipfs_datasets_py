"""XRPL native-ledger, Hooks, and sidechain package (CRYPTOIR-G240).

Bounded offline acquisition and normalization of XRPL ledger objects: account
flags, trust lines, escrows, checks, payment channels, offers, AMMs, NFTs,
signer lists, amendment/capability state, issuer freeze/clawback, partial
payment, reserve, sequence/ticket, destination tags, and validated-ledger
epochs.  Hooks return ``UNSUPPORTED`` where capability evidence is absent.
Ripple EVM sidechain delegates to the EVM frontend and is never silently
treated as XRPL mainnet.

Importing this package performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from .frontend import (
    DEFAULT_MAX_OBJECTS,
    DEFAULT_MAX_TRANSITIONS,
    FRONTEND_ID,
    FRONTEND_SCHEMA_VERSION,
    FRONTEND_VERSION,
    AnalysisMode,
    XRPLLedgerFrontend,
    XRPLNormalizationResult,
)
from .provider import (
    PROVIDER_SCHEMA_VERSION,
    XRPL_PROVIDER_ID,
    OfflineXRPLProvider,
    XRPLLedgerFixture,
)
from .semantics import (
    ASF_ALLOW_TRUSTLINE_CLAWBACK,
    ASF_DEFAULT_RIPPLE,
    ASF_DEPOSIT_AUTH,
    ASF_GLOBAL_FREEZE,
    ASF_NO_FREEZE,
    ASF_REQUIRE_AUTH,
    DROPS_PER_XRP,
    NATIVE_ASSET_SYMBOL,
    NATIVE_DECIMALS,
    RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
    RIPPLE_EVM_SIDECHAIN_NAMESPACE,
    RIPPLE_EVM_SIDECHAIN_NETWORK,
    SEMANTICS_SCHEMA_VERSION,
    TF_PARTIAL_PAYMENT,
    XRPL_DEVNET_CHAIN_ID,
    XRPL_DEVNET_GENESIS_HASH,
    XRPL_DEVNET_NETWORK,
    XRPL_MAINNET_CHAIN_ID,
    XRPL_MAINNET_GENESIS_HASH,
    XRPL_MAINNET_NETWORK,
    XRPL_TESTNET_CHAIN_ID,
    XRPL_TESTNET_GENESIS_HASH,
    XRPL_TESTNET_NETWORK,
    AmountKind,
    HookCapability,
    HookCapabilityState,
    IssuedAsset,
    IssuerPolicy,
    LedgerObjectKind,
    LedgerObjectTransition,
    SemanticPassStatus,
    SidechainRouting,
    SignerQuorum,
    ValidatedLedgerEpoch,
    XRPLTransactionType,
    default_object_kind_for_tx,
    incomplete_coverage_never_passes,
    is_ripple_evm_sidechain,
    is_xrpl_chain_id,
    map_ledger_object_kind,
    map_transaction_type,
    normalize_classic_address,
    normalize_currency,
    normalize_ledger_hash,
    partial_payment_flag_set,
    resolve_xrpl_chain_id,
    xrpl_network_anchor,
)

# Alias matching EVM/Solana naming for package surface symmetry.
XRPLArtifactProvider = OfflineXRPLProvider

__all__ = [
    # Frontend
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "DEFAULT_MAX_TRANSITIONS",
    "DEFAULT_MAX_OBJECTS",
    "AnalysisMode",
    "XRPLLedgerFrontend",
    "XRPLNormalizationResult",
    # Provider
    "PROVIDER_SCHEMA_VERSION",
    "XRPL_PROVIDER_ID",
    "OfflineXRPLProvider",
    "XRPLArtifactProvider",
    "XRPLLedgerFixture",
    # Semantics
    "SEMANTICS_SCHEMA_VERSION",
    "XRPL_MAINNET_CHAIN_ID",
    "XRPL_MAINNET_NETWORK",
    "XRPL_MAINNET_GENESIS_HASH",
    "XRPL_TESTNET_CHAIN_ID",
    "XRPL_TESTNET_NETWORK",
    "XRPL_TESTNET_GENESIS_HASH",
    "XRPL_DEVNET_CHAIN_ID",
    "XRPL_DEVNET_NETWORK",
    "XRPL_DEVNET_GENESIS_HASH",
    "RIPPLE_EVM_SIDECHAIN_CHAIN_ID",
    "RIPPLE_EVM_SIDECHAIN_NETWORK",
    "RIPPLE_EVM_SIDECHAIN_NAMESPACE",
    "NATIVE_ASSET_SYMBOL",
    "DROPS_PER_XRP",
    "NATIVE_DECIMALS",
    "TF_PARTIAL_PAYMENT",
    "ASF_ALLOW_TRUSTLINE_CLAWBACK",
    "ASF_GLOBAL_FREEZE",
    "ASF_NO_FREEZE",
    "ASF_REQUIRE_AUTH",
    "ASF_DEFAULT_RIPPLE",
    "ASF_DEPOSIT_AUTH",
    "SemanticPassStatus",
    "LedgerObjectKind",
    "XRPLTransactionType",
    "HookCapabilityState",
    "SidechainRouting",
    "AmountKind",
    "IssuedAsset",
    "IssuerPolicy",
    "HookCapability",
    "ValidatedLedgerEpoch",
    "SignerQuorum",
    "LedgerObjectTransition",
    "is_xrpl_chain_id",
    "is_ripple_evm_sidechain",
    "resolve_xrpl_chain_id",
    "xrpl_network_anchor",
    "normalize_classic_address",
    "normalize_ledger_hash",
    "normalize_currency",
    "map_transaction_type",
    "map_ledger_object_kind",
    "partial_payment_flag_set",
    "incomplete_coverage_never_passes",
    "default_object_kind_for_tx",
]
