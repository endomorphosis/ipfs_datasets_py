"""Encrypted document wallet primitives for `ipfs_datasets_py`."""

from __future__ import annotations

from .crypto import generate_key
from .models import DocumentRecord, DocumentVersion, KeyWrap, StorageReceipt, WalletGrant, WalletRecord
from .service import DocumentWalletService
from .storage import IPFSStorageAdapter, LocalFileStorageAdapter, MemoryStorageAdapter
from .ucan import document_resource, wallet_resource

__all__ = [
    "DocumentRecord",
    "DocumentVersion",
    "DocumentWalletService",
    "IPFSStorageAdapter",
    "KeyWrap",
    "LocalFileStorageAdapter",
    "MemoryStorageAdapter",
    "StorageReceipt",
    "WalletGrant",
    "WalletRecord",
    "document_resource",
    "generate_key",
    "wallet_resource",
]

