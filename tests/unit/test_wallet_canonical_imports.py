from __future__ import annotations

import importlib.util
import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")


def test_wallet_is_canonical_generic_wallet_import() -> None:
    from ipfs_datasets_py.wallet import (
        AccessRequest,
        AnalyticsTemplate,
        DataWalletService,
        DeterministicLocationDistanceProofBackend,
        DeterministicLocationRegionProofBackend,
        ProofBackendRegistry,
        SimulatedProofBackend,
        StorageHealthReport,
        StorageReplicaStatus,
        WalletInvocation,
        WalletService,
    )

    assert WalletService is DataWalletService
    assert AccessRequest.__name__ == "AccessRequest"
    assert AnalyticsTemplate.__name__ == "AnalyticsTemplate"
    assert DeterministicLocationDistanceProofBackend.__name__ == "DeterministicLocationDistanceProofBackend"
    assert DeterministicLocationRegionProofBackend.__name__ == "DeterministicLocationRegionProofBackend"
    assert ProofBackendRegistry.__name__ == "ProofBackendRegistry"
    assert SimulatedProofBackend.__name__ == "SimulatedProofBackend"
    assert StorageHealthReport.__name__ == "StorageHealthReport"
    assert StorageReplicaStatus.__name__ == "StorageReplicaStatus"
    assert WalletInvocation.__name__ == "WalletInvocation"


def test_wallet_submodules_expose_generic_helpers() -> None:
    from ipfs_datasets_py.wallet import (
        FilecoinEncryptedBlobStore,
        LocalWalletRepository,
        ReplicatedEncryptedBlobStore,
        S3EncryptedBlobStore,
        WalletStorageConfig,
        create_encrypted_blob_store,
    )
    from ipfs_datasets_py.wallet.storage import IPFSEncryptedBlobStore, LocalEncryptedBlobStore
    from ipfs_datasets_py.wallet.ucan import resource_for_location, resource_for_record

    assert FilecoinEncryptedBlobStore.__name__ == "FilecoinEncryptedBlobStore"
    assert IPFSEncryptedBlobStore.__name__ == "IPFSEncryptedBlobStore"
    assert LocalEncryptedBlobStore.__name__ == "LocalEncryptedBlobStore"
    assert LocalWalletRepository.__name__ == "LocalWalletRepository"
    assert ReplicatedEncryptedBlobStore.__name__ == "ReplicatedEncryptedBlobStore"
    assert S3EncryptedBlobStore.__name__ == "S3EncryptedBlobStore"
    assert WalletStorageConfig.__name__ == "WalletStorageConfig"
    assert callable(create_encrypted_blob_store)
    assert resource_for_record("wallet-1", "rec-1") == "wallet://wallet-1/records/rec-1"
    assert resource_for_location("wallet-1", "rec-1") == "wallet://wallet-1/location/rec-1"


def test_legacy_wallet_namespaces_are_removed() -> None:
    assert importlib.util.find_spec("ipfs_datasets_py.wallet.document") is None
    assert importlib.util.find_spec("ipfs_datasets_py.data_wallet") is None
    assert importlib.util.find_spec("ipfs_datasets_py.document_wallet") is None
