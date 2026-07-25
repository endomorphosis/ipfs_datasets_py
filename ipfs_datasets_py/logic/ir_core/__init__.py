"""Stable, dependency-independent contracts for the shared IR kernel.

The package root is deliberately lazy: importing :mod:`ir_core` must not load
domain schemas, proof backends, model runtimes, or optional dependencies.
Leaf modules remain the owners of the exported contracts.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "artifacts": (
        "ARTIFACT_MANIFEST_IDENTITY_DOMAIN",
        "IR_ARTIFACT_MANIFEST_SCHEMA_VERSION",
        "Artifact",
        "ArtifactBinding",
        "ArtifactDecision",
        "ArtifactIntegrityError",
        "ArtifactManifest",
        "ArtifactManifestValidationError",
        "ArtifactRecord",
        "ArtifactRole",
        "DecisionKind",
        "IntegrityIssue",
        "IntegrityIssueKind",
        "IntegrityReport",
        "IntegrityVerificationReport",
        "ManifestDecision",
        "ObservationalMetadata",
        "RunManifest",
        "RunObservations",
        "artifact_from_path",
        "build_artifact",
        "verify_artifact_integrity",
    ),
    "canonical": (
        "CANONICAL_JSON_PROFILE",
        "CanonicalizationError",
        "CanonicalizationSchema",
        "CollectionRule",
        "CollectionSchema",
        "CollectionSemantics",
        "canonical_json",
        "canonical_json_bytes",
        "canonical_bytes",
        "canonical_dumps",
        "canonicalize",
        "canonicalize_json",
        "coerce_collection_schema",
    ),
    "claims": (
        "Assumption",
        "Claim",
        "ClaimValidationError",
        "FrozenMap",
        "IRAssumption",
        "IRClaim",
        "IRObligation",
        "Obligation",
        "ProofObligation",
        "IR_ASSUMPTION_SCHEMA_VERSION",
        "IR_CLAIM_SCHEMA_VERSION",
        "IR_OBLIGATION_SCHEMA_VERSION",
        "freeze_json",
        "stable_digest",
        "thaw_json",
    ),
    "diagnostics": (
        "Diagnostic",
        "DiagnosticCode",
        "DiagnosticLocation",
        "DiagnosticReport",
        "DiagnosticSeverity",
        "DiagnosticValidationError",
        "IRDiagnostic",
        "IRDiagnosticReport",
        "IRDiagnostics",
        "IR_DIAGNOSTICS_SCHEMA_VERSION",
        "canonical_diagnostics_bytes",
        "canonical_diagnostics_json",
        "diagnostics_sha256",
        "validate_cross_references",
        "validate_diagnostics",
        "validate_ir_references",
    ),
    "evidence": (
        "Evidence",
        "EvidenceKind",
        "EvidenceRef",
        "EvidenceReference",
        "EvidenceRegistry",
        "EvidenceReviewStatus",
        "EvidenceValidationError",
        "IR_EVIDENCE_SCHEMA_VERSION",
        "canonical_evidence_bytes",
        "canonical_evidence_json",
        "evidence_sha256",
        "validate_evidence",
    ),
    "identity": (
        "CID_VERSION",
        "DIGEST_SIZE",
        "IDENTITY_PROFILE",
        "IDENTITY_PROFILE_NAME",
        "MULTIBASE_NAME",
        "MULTICODEC_CODE",
        "MULTICODEC_NAME",
        "MULTIHASH_CODE",
        "MULTIHASH_NAME",
        "CanonicalIdentity",
        "IdentityProfile",
        "canonical_identity",
        "cid_v1",
        "cid_v1_from_digest",
        "compute_identity",
        "identity_for",
        "identity_preimage",
        "sha256_digest",
    ),
    "protocols": (
        "AttemptStatus",
        "AuthorityKind",
        "AuthorityMismatchError",
        "BackendAttempt",
        "BackendCapabilities",
        "BackendRequest",
        "BackendResult",
        "BoundedResult",
        "EvidenceGateResult",
        "ExecutionBounds",
        "MonitorResult",
        "PolicyDecision",
        "ProofAttempt",
        "ProofBackend",
        "ProofReceipt",
        "ProofResult",
        "ProtocolValidationError",
        "QueryKind",
        "Receipt",
        "ResourceUsage",
        "ResultAuthority",
        "ResultReceipt",
        "ResultStatus",
        "SatisfiabilityResult",
        "TheoremProofReceipt",
        "BACKEND_ATTEMPT_SCHEMA_VERSION",
        "BACKEND_CAPABILITIES_SCHEMA_VERSION",
        "BACKEND_REQUEST_SCHEMA_VERSION",
        "BOUNDED_RESULT_SCHEMA_VERSION",
        "PROOF_RECEIPT_SCHEMA_VERSION",
        "RESULT_AUTHORITY_SCHEMA_VERSION",
        "RESULT_RECEIPT_SCHEMA_VERSION",
    ),
    "provenance": (
        "ConfigBinding",
        "ConfigurationBinding",
        "IRProvenance",
        "IR_PROVENANCE_SCHEMA_VERSION",
        "ProducerBinding",
        "Provenance",
        "ProvenanceBinding",
        "ProvenanceValidationError",
        "SourceRef",
        "SourceReference",
        "SourceReviewStatus",
        "SourceSpan",
        "canonical_provenance_bytes",
        "canonical_provenance_json",
        "provenance_sha256",
        "validate_provenance",
    ),
    "schema_registry": (
        "MIGRATION_RECEIPT_SCHEMA_ID",
        "CompatibilityDeclaration",
        "CompatibilityResult",
        "CompatibilityStatus",
        "DuplicateRegistrationError",
        "IRSchemaRegistry",
        "InvalidSchemaIDError",
        "LossReport",
        "MigrationCycleError",
        "MigrationExecutionError",
        "MigrationLoss",
        "MigrationLossReport",
        "MigrationOutcome",
        "MigrationPathError",
        "MigrationReceipt",
        "MigrationResult",
        "MigrationSpec",
        "MigrationTransform",
        "NondeterministicMigrationError",
        "SchemaMigration",
        "SchemaRegistryError",
        "SchemaSpec",
        "SchemaVersion",
        "UnknownSchemaError",
        "canonical_payload_bytes",
        "payload_digest",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    """Load a reviewed kernel contract from its dependency-light leaf module."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
