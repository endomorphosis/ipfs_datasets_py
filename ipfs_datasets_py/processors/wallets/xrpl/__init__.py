"""Reusable XRPL ledger processor (WALPROC-G200).

Implements classic account identity, ``account_tx`` marker pagination,
transactions plus metadata, ``delivered_amount`` (including partial payments),
XRP and issued-currency/trustline assets, destination tags, memos under privacy
policy, sequence, validated-ledger checkpoints, normalization, and export hooks.

Provider family: XRPL JSON-RPC. No signing or submission capability is exposed.
Xaman wallet/payload concerns are intentionally **not** part of this package;
compose them in ``processors.wallets.xaman`` over this ledger provider.
"""

from __future__ import annotations

from .accounts import (
    AccountDescriptor,
    AccountEncoding,
    describe_account,
    validate_classic_address,
)
from .amounts import exact_drops, exact_issued, parse_drops, parse_issued_value
from .finality import (
    DEFAULT_MAX_REORG_DEPTH,
    DEFAULT_XRPL_THRESHOLDS,
    XRPLFinalityPolicy,
)
from .models import AmountKind, MemoRecord, TxOutcome, XRPLAmount, XRPLTransaction
from .networks import (
    DEVNET_GENESIS,
    DROPS_PER_XRP,
    ISSUED_MAX_DECIMALS,
    MAINNET_GENESIS,
    TESTNET_GENESIS,
    XRPL_NAMESPACE,
    XRP_DECIMALS,
    XRPLNetwork,
    XRPLNetworkProfile,
    chain_ref_for,
    issued_asset,
    network_profile,
    xrp_asset,
)
from .normalizer import (
    EXTENSION_NAMESPACE,
    EXTENSION_SCHEMA,
    PROVIDER_KIND,
    XRPLNormalizer,
    delivered_amount,
    parse_account_tx_entry,
)
from .privacy import (
    DEFAULT_MAX_MEMO_DATA_BYTES,
    DEFAULT_MAX_MEMOS,
    MemoPrivacyPolicy,
)
from .processor import XRPLWalletProcessor
from .provider import (
    PROVIDER_FAMILY,
    PROVIDER_NAME,
    JsonRpcHttpBackend,
    MappingResponseBackend,
    XRPLLedgerProvider,
    fixture_backend_from_account_tx,
)

__all__ = [
    "AccountDescriptor",
    "AccountEncoding",
    "AmountKind",
    "DEFAULT_MAX_MEMO_DATA_BYTES",
    "DEFAULT_MAX_MEMOS",
    "DEFAULT_MAX_REORG_DEPTH",
    "DEFAULT_XRPL_THRESHOLDS",
    "DEVNET_GENESIS",
    "DROPS_PER_XRP",
    "EXTENSION_NAMESPACE",
    "EXTENSION_SCHEMA",
    "ISSUED_MAX_DECIMALS",
    "JsonRpcHttpBackend",
    "MAINNET_GENESIS",
    "MappingResponseBackend",
    "MemoPrivacyPolicy",
    "MemoRecord",
    "PROVIDER_FAMILY",
    "PROVIDER_KIND",
    "PROVIDER_NAME",
    "TESTNET_GENESIS",
    "TxOutcome",
    "XRPL_NAMESPACE",
    "XRP_DECIMALS",
    "XRPLAmount",
    "XRPLFinalityPolicy",
    "XRPLLedgerProvider",
    "XRPLNetwork",
    "XRPLNetworkProfile",
    "XRPLNormalizer",
    "XRPLTransaction",
    "XRPLWalletProcessor",
    "chain_ref_for",
    "delivered_amount",
    "describe_account",
    "exact_drops",
    "exact_issued",
    "fixture_backend_from_account_tx",
    "issued_asset",
    "network_profile",
    "parse_account_tx_entry",
    "parse_drops",
    "parse_issued_value",
    "validate_classic_address",
    "xrp_asset",
]
