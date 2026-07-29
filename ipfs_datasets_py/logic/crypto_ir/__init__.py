"""Crypto IR: chain-neutral, immutable intermediate representation.

The package root is deliberately lazy: importing :mod:`crypto_ir` must not
load chain adapters, network clients, or optional dependencies.  Leaf modules
remain the owners of the exported contracts.

CRYPTOIR-G020 owns foundational records, identity, provenance, and schema
versions.  Adapter/registry exports for CRYPTOIR-G030 are added by that task.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "model": (
        "COMPLETENESS_RECEIPT_COLLECTION_SCHEMA",
        "CRYPTO_IR_MODEL_DOMAIN",
        "UNSIGNED_INTENT_COLLECTION_SCHEMA",
        "AccountIdentity",
        "AnalysisResultRef",
        "ArtifactKind",
        "AssetIdentity",
        "AuthorizationDecisionRef",
        "CallIntent",
        "ChainIdentity",
        "CompletenessReceipt",
        "CompletenessStatus",
        "ContractArtifact",
        "CryptoAssumption",
        "CryptoExtension",
        "CryptoIRValidationError",
        "ExactAmount",
        "ExpectedEffect",
        "FinalityStatus",
        "LedgerCoordinate",
        "ObservedTransaction",
        "RetractionStatus",
        "SerializedTransactionCandidate",
        "SignerRequirement",
        "TimeBoundedEpoch",
        "TransferIntent",
        "UnsignedTransactionIntent",
        "ValidityWindow",
        "WalletDescriptor",
        "observation_provenance",
        "record_layer",
        "refuse_authority_elevation",
    ),
    "identity": (
        "CANONICAL_JSON_PROFILE",
        "CID_VERSION",
        "CRYPTO_IR_CHAIN_QUALIFIED_DOMAIN",
        "CRYPTO_IR_IDENTITY_DOMAIN",
        "CRYPTO_IR_IDENTITY_PROFILE",
        "CRYPTO_IR_IDENTITY_SCHEMA_ID",
        "DIGEST_SIZE",
        "IDENTITY_PROFILE",
        "IDENTITY_PROFILE_NAME",
        "CanonicalIdentity",
        "CollectionRule",
        "CollectionSchema",
        "CollectionSemantics",
        "CryptoIRIdentityError",
        "CryptoIRIdentityProfile",
        "IdentityProfile",
        "canonical_identity",
        "chain_qualified_identity",
        "cid_v1",
        "crypto_ir_identity",
        "identity_profile_descriptor",
        "sha256_digest",
    ),
    "provenance": (
        "CRYPTO_IR_PROVENANCE_COLLECTION_SCHEMA",
        "CRYPTO_IR_PROVENANCE_DOMAIN",
        "CRYPTO_IR_PROVENANCE_SCHEMA_ID",
        "AcquisitionProvenance",
        "AuthorityBinding",
        "AuthorityKind",
        "CryptoIRProvenance",
        "CryptoIRProvenanceError",
        "ObservationProvenance",
        "assert_authority_not_elevated",
        "bind_shared_provenance",
        "coerce_authority_kind",
        "freeze_json",
        "freeze_json_mapping",
        "thaw_json",
    ),
    "schema_versions": (
        "CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION",
        "CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION",
        "CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION",
        "CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION",
        "CRYPTO_IR_IDENTITY_SCHEMA",
        "CRYPTO_IR_IDENTITY_SCHEMA_VERSION",
        "CRYPTO_IR_KERNEL_SCHEMA_VERSION",
        "CRYPTO_IR_MODEL_SCHEMA",
        "CRYPTO_IR_MODEL_SCHEMA_ID",
        "CRYPTO_IR_MODEL_SCHEMA_VERSION",
        "CRYPTO_IR_PROVENANCE_SCHEMA",
        "CRYPTO_IR_PROVENANCE_SCHEMA_VERSION",
        "CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION",
        "CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION",
        "SCHEMA_REGISTRY_SCHEMA",
        "SCHEMA_VERSIONS",
        "SchemaVersion",
        "SchemaVersionError",
        "get_schema_version",
        "is_registered_schema",
        "schema_registry_descriptor",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

if len(_EXPORT_MODULE) != sum(len(names) for names in _EXPORTS.values()):
    raise RuntimeError("Crypto IR package exports must have one owning module")

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    """Load a reviewed Crypto IR contract from its owning leaf module."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
