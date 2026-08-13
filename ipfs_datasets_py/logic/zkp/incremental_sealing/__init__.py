"""Datasets semantic authority for IncrementalProofSealer schemas (IPS-012).

Public contracts are exported lazily so a cold import of this package performs
no optional capability import, install, key generation, process spawn, network
I/O, or user-state access.  Submodules remain independently importable.

Legacy ZK / test / proof receipts are classified through
``classify_legacy_receipt`` without upgrading their actual assurance class.
"""

from __future__ import annotations

from typing import Any

# Package-level evidence subsets for the public freeze (IPS-012).
PUBLIC_API_SUBSET = "ips/datasets-public-api@1"
MIGRATION_SUBSET = "ips/legacy-receipt-migration@1"
PACKAGE_SCHEMA_VERSION = "1"

# Lazy export table: public name -> (submodule, attribute).
# Keep this closed and explicit; unknown attributes fail closed.
_EXPORTS: dict[str, tuple[str, str]] = {
    # Package metadata
    "PUBLIC_API_SUBSET": (__name__, "PUBLIC_API_SUBSET"),
    "MIGRATION_SUBSET": (__name__, "MIGRATION_SUBSET"),
    "PACKAGE_SCHEMA_VERSION": (__name__, "PACKAGE_SCHEMA_VERSION"),
    # evidence
    "EVIDENCE_SUBSET": (".evidence", "EVIDENCE_SUBSET"),
    "SCHEMA_VERSION": (".evidence", "SCHEMA_VERSION"),
    "DirectExecutionProof": (".evidence", "DirectExecutionProof"),
    "EvidenceClass": (".evidence", "EvidenceClass"),
    "EvidenceClassError": (".evidence", "EvidenceClassError"),
    "IncrementalCommitSeal": (".evidence", "IncrementalCommitSeal"),
    "IntegrityCommitment": (".evidence", "IntegrityCommitment"),
    "ProofMode": (".evidence", "ProofMode"),
    "ProofTerminalStatus": (".evidence", "ProofTerminalStatus"),
    "ProofUnitKind": (".evidence", "ProofUnitKind"),
    "ReceiptAggregationZkProof": (".evidence", "ReceiptAggregationZkProof"),
    "SealStatus": (".evidence", "SealStatus"),
    "SignedExecutionReceipt": (".evidence", "SignedExecutionReceipt"),
    "assert_production_seal_allowed": (".evidence", "assert_production_seal_allowed"),
    "closed_evidence_class_names": (".evidence", "closed_evidence_class_names"),
    "closed_proof_mode_values": (".evidence", "closed_proof_mode_values"),
    "closed_proof_unit_kind_values": (".evidence", "closed_proof_unit_kind_values"),
    "closed_seal_status_values": (".evidence", "closed_seal_status_values"),
    "closed_terminal_status_values": (".evidence", "closed_terminal_status_values"),
    "evidence_from_canonical": (".evidence", "evidence_from_canonical"),
    "parse_proof_mode": (".evidence", "parse_proof_mode"),
    "parse_proof_unit_kind": (".evidence", "parse_proof_unit_kind"),
    "parse_seal_status": (".evidence", "parse_seal_status"),
    "parse_terminal_status": (".evidence", "parse_terminal_status"),
    "production_seal_allowed": (".evidence", "production_seal_allowed"),
    "require_direct_execution_for_claim": (
        ".evidence",
        "require_direct_execution_for_claim",
    ),
    "status_satisfies_class": (".evidence", "status_satisfies_class"),
    # proof_unit
    "PROOF_UNIT_SCHEMA": (".proof_unit", "PROOF_UNIT_SCHEMA"),
    "ProofUnit": (".proof_unit", "ProofUnit"),
    "ProofUnitError": (".proof_unit", "ProofUnitError"),
    "assert_unit_production_policy": (".proof_unit", "assert_unit_production_policy"),
    "sample_production_unit": (".proof_unit", "sample_production_unit"),
    # identity
    "IDENTITY_SUBSET": (".identity", "IDENTITY_SUBSET"),
    "IdentityError": (".identity", "IdentityError"),
    "PropertyIdentity": (".identity", "PropertyIdentity"),
    "RepositoryState": (".identity", "RepositoryState"),
    "SourceArtifactIdentity": (".identity", "SourceArtifactIdentity"),
    "SourceSymbolIdentity": (".identity", "SourceSymbolIdentity"),
    "TestSelectorIdentity": (".identity", "TestSelectorIdentity"),
    "canonical_cid": (".identity", "canonical_cid"),
    "canonical_cid_for_bytes": (".identity", "canonical_cid_for_bytes"),
    "canonicalize_relative_path": (".identity", "canonicalize_relative_path"),
    "validate_profile_cid": (".identity", "validate_profile_cid"),
    # cache_key
    "CACHE_KEY_SUBSET": (".cache_key", "CACHE_KEY_SUBSET"),
    "CacheKeyError": (".cache_key", "CacheKeyError"),
    "ProofCacheKey": (".cache_key", "ProofCacheKey"),
    "build_proof_cache_key": (".cache_key", "build_proof_cache_key"),
    "sample_proof_cache_key": (".cache_key", "sample_proof_cache_key"),
    # manifest
    "MANIFEST_SUBSET": (".manifest", "MANIFEST_SUBSET"),
    "ManifestError": (".manifest", "ManifestError"),
    "RequiredUnitDescriptor": (".manifest", "RequiredUnitDescriptor"),
    "UnitRemovalAuthorization": (".manifest", "UnitRemovalAuthorization"),
    "VerificationPolicy": (".manifest", "VerificationPolicy"),
    "VerificationRequirementManifest": (
        ".manifest",
        "VerificationRequirementManifest",
    ),
    "assert_no_unauthorized_disappearance": (
        ".manifest",
        "assert_no_unauthorized_disappearance",
    ),
    "build_verification_requirement_manifest": (
        ".manifest",
        "build_verification_requirement_manifest",
    ),
    "sample_verification_policy": (".manifest", "sample_verification_policy"),
    "sample_verification_requirement_manifest": (
        ".manifest",
        "sample_verification_requirement_manifest",
    ),
    # statements
    "STATEMENTS_SUBSET": (".statements", "STATEMENTS_SUBSET"),
    "CanonicalProofStatement": (".statements", "CanonicalProofStatement"),
    "DirectExecutionStatement": (".statements", "DirectExecutionStatement"),
    "ForestTransitionStatement": (".statements", "ForestTransitionStatement"),
    "PrivateInputCommitment": (".statements", "PrivateInputCommitment"),
    "PublicInputDeclaration": (".statements", "PublicInputDeclaration"),
    "ReceiptAggregationStatement": (".statements", "ReceiptAggregationStatement"),
    "StatementError": (".statements", "StatementError"),
    # forest_codec
    "FOREST_CODEC_SUBSET": (".forest_codec", "FOREST_CODEC_SUBSET"),
    "CategoryRoot": (".forest_codec", "CategoryRoot"),
    "ForestCodecError": (".forest_codec", "ForestCodecError"),
    "ProofForestLeaf": (".forest_codec", "ProofForestLeaf"),
    "RepositoryProofRoot": (".forest_codec", "RepositoryProofRoot"),
    "compute_category_root": (".forest_codec", "compute_category_root"),
    "compute_repository_root": (".forest_codec", "compute_repository_root"),
    # migration
    "LegacyAssurance": (".migration", "LegacyAssurance"),
    "LegacyReceiptClassification": (".migration", "LegacyReceiptClassification"),
    "MigrationDisposition": (".migration", "MigrationDisposition"),
    "MigrationError": (".migration", "MigrationError"),
    "classify_legacy_receipt": (".migration", "classify_legacy_receipt"),
    "closed_legacy_assurances": (".migration", "closed_legacy_assurances"),
    "closed_legacy_path_families": (".migration", "closed_legacy_path_families"),
    "closed_migration_dispositions": (".migration", "closed_migration_dispositions"),
    "known_legacy_path_matrix": (".migration", "known_legacy_path_matrix"),
}

__all__ = tuple(sorted(_EXPORTS))


def __getattr__(name: str) -> Any:
    """Resolve public contracts on demand without eager submodule imports."""

    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc
    if module_name == __name__:
        return globals()[attr_name]
    from importlib import import_module

    module = import_module(module_name, package=__name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
