"""Dependency-free, read-only Ethereum/EVM wallet processor."""

from .finality import EthereumFinalityAssessment, EthereumFinalityPolicy
from .normalizer import (
    DecodedTokenTransfer,
    EthereumNormalizer,
    TokenMetadata,
    decode_transfer_log,
)
from .rpc import (
    ETHEREUM_MAINNET,
    ETHEREUM_MAINNET_CHAIN_ID,
    ETHEREUM_MAINNET_GENESIS_HASH,
    EVM_NAMESPACE,
    EthereumIdentityError,
    EthereumLedgerProvider,
    EvmBlockBundle,
    EvmHead,
    EvmNetwork,
    encode_quantity,
    normalize_address,
    normalize_hash,
    parse_quantity,
)

__all__ = [
    "DecodedTokenTransfer",
    "ETHEREUM_MAINNET",
    "ETHEREUM_MAINNET_CHAIN_ID",
    "ETHEREUM_MAINNET_GENESIS_HASH",
    "EVM_NAMESPACE",
    "EthereumFinalityAssessment",
    "EthereumFinalityPolicy",
    "EthereumIdentityError",
    "EthereumLedgerProvider",
    "EthereumNormalizer",
    "EvmBlockBundle",
    "EvmHead",
    "EvmNetwork",
    "TokenMetadata",
    "decode_transfer_log",
    "encode_quantity",
    "normalize_address",
    "normalize_hash",
    "parse_quantity",
]
