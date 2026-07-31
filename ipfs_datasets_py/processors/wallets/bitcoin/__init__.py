"""Bitcoin wallet and public-ledger processing (WALPROC-G400).

Implements network/genesis-bound transaction, UTXO, script/address descriptor,
fee, mempool/confirmed, confirmation-depth finality, reorg reverse, balance,
and export-oriented normalization behind the shared wallet protocols.

Provider family: Esplora REST (Blockstream-compatible). No PSBT, signing, or
broadcast capability is exposed. Ownership/change clustering is not asserted.
"""

from __future__ import annotations

from ..models import UTXORecord, UtxoRecord
from .amounts import exact_sats, parse_sats
from .finality import (
    DEFAULT_BITCOIN_THRESHOLDS,
    DEFAULT_MAX_REORG_DEPTH,
    BitcoinFinalityPolicy,
)
from .models import (
    BitcoinTransaction,
    OutPoint,
    TxInput,
    TxOutput,
    TxStatus,
    UtxoEntry,
    coinbase_input,
)
from .networks import (
    BITCOIN_NAMESPACE,
    BTC_DECIMALS,
    MAINNET_GENESIS,
    TESTNET_GENESIS,
    BitcoinNetwork,
    BitcoinNetworkProfile,
    btc_asset,
    chain_ref_for,
    network_profile,
)
from .normalizer import BitcoinNormalizer, parse_esplora_transaction
from .processor import BitcoinWalletProcessor
from .provider import (
    PROVIDER_FAMILY,
    PROVIDER_NAME,
    BitcoinLedgerProvider,
    EsploraHttpBackend,
    MappingResponseBackend,
    fixture_backend_from_transactions,
)
from .scripts import (
    AddressEncoding,
    ScriptDescriptor,
    ScriptType,
    classify_script_hex,
    describe_address,
    describe_script,
)
from .utxo_set import UtxoApplyResult, UtxoSet, seed_utxo

__all__ = [
    "ADDRESS_ENCODING",
    "AddressEncoding",
    "BITCOIN_NAMESPACE",
    "BTC_DECIMALS",
    "BitcoinFinalityPolicy",
    "BitcoinLedgerProvider",
    "BitcoinNetwork",
    "BitcoinNetworkProfile",
    "BitcoinNormalizer",
    "BitcoinTransaction",
    "BitcoinWalletProcessor",
    "DEFAULT_BITCOIN_THRESHOLDS",
    "DEFAULT_MAX_REORG_DEPTH",
    "EsploraHttpBackend",
    "MAINNET_GENESIS",
    "TESTNET_GENESIS",
    "MappingResponseBackend",
    "OutPoint",
    "PROVIDER_FAMILY",
    "PROVIDER_NAME",
    "ScriptDescriptor",
    "ScriptType",
    "TxInput",
    "TxOutput",
    "TxStatus",
    "UTXORecord",
    "UtxoApplyResult",
    "UtxoEntry",
    "UtxoRecord",
    "UtxoSet",
    "btc_asset",
    "chain_ref_for",
    "classify_script_hex",
    "coinbase_input",
    "describe_address",
    "describe_script",
    "exact_sats",
    "fixture_backend_from_transactions",
    "network_profile",
    "parse_esplora_transaction",
    "parse_sats",
    "seed_utxo",
]

# Alias retained for scanners that look for ADDRESS_ENCODING-style constants.
ADDRESS_ENCODING = AddressEncoding
