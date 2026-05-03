from __future__ import annotations

import importlib.util
import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")


def test_wallet_is_canonical_generic_wallet_import() -> None:
    from ipfs_datasets_py.wallet import DataWalletService, WalletService

    assert WalletService is DataWalletService


def test_wallet_submodules_expose_generic_helpers() -> None:
    from ipfs_datasets_py.wallet.storage import IPFSEncryptedBlobStore, LocalEncryptedBlobStore
    from ipfs_datasets_py.wallet.ucan import resource_for_location, resource_for_record

    assert IPFSEncryptedBlobStore.__name__ == "IPFSEncryptedBlobStore"
    assert LocalEncryptedBlobStore.__name__ == "LocalEncryptedBlobStore"
    assert resource_for_record("wallet-1", "rec-1") == "wallet://wallet-1/records/rec-1"
    assert resource_for_location("wallet-1", "rec-1") == "wallet://wallet-1/location/rec-1"


def test_legacy_wallet_namespaces_are_removed() -> None:
    assert importlib.util.find_spec("ipfs_datasets_py.wallet.document") is None
    assert importlib.util.find_spec("ipfs_datasets_py.data_wallet") is None
    assert importlib.util.find_spec("ipfs_datasets_py.document_wallet") is None
