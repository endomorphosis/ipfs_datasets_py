"""Stable Security IR declarations, adapters, and result contracts.

Exports are resolved lazily because the legacy adapters intentionally depend
on the frozen ``security_models.crypto_exchange`` namespace.  A plain import
of this package therefore remains free of solver/runtime imports and avoids a
cycle with that compatibility namespace.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "model": (
        "Asset",
        "Assumption",
        "Channel",
        "Claim",
        "Extension",
        "Policy",
        "PolicyEffect",
        "Principal",
        "Resource",
        "SECURITY_IR_COLLECTION_SCHEMA",
        "SECURITY_IR_IDENTITY_DOMAIN",
        "SECURITY_IR_SCHEMA_VERSION",
        "SECURITY_IR_V1_SCHEMA_VERSION",
        "SecurityAsset",
        "SecurityAssumption",
        "SecurityChannel",
        "SecurityClaim",
        "SecurityExtension",
        "SecurityIR",
        "SecurityIRV1",
        "SecurityIRValidationError",
        "SecurityPolicy",
        "SecurityPrincipal",
        "SecurityResource",
        "SecuritySource",
        "SecurityStateMachine",
        "SecurityTrustZone",
        "Source",
        "StateMachine",
        "StateTransition",
        "ThreatAssumption",
        "TrustZone",
        "validate_security_ir",
    ),
    "adapter": (
        "LEGACY_ADAPTER_VERSION",
        "LEGACY_DECLARATION_FIELDS",
        "LEGACY_TOP_LEVEL_FIELDS",
        "LEGACY_VERIFICATION_FIELDS",
        "LegacyAdapterError",
        "LegacyAdapterResult",
        "LegacySecurityIRAdapter",
        "LegacyVerificationData",
        "SecurityIRLegacyAdapter",
        "adapt_legacy",
        "adapt_legacy_model",
        "adapt_legacy_security_ir",
        "from_legacy",
        "to_legacy",
        "to_legacy_model",
        "to_legacy_security_ir",
    ),
    "results": (
        "DisproofResult",
        "EvidenceGateResult",
        "LEGACY_RESULT_MAPPING_VERSION",
        "LegacyResultDiagnostic",
        "LegacyResultMapping",
        "MonitorResult",
        "PolicyDecision",
        "ProofReceipt",
        "ProofResult",
        "ReleasePolicyDecision",
        "RuntimeMonitorResult",
        "SECURITY_RESULT_INTERFACE_VERSION",
        "SatisfiabilityResult",
        "SecurityProofReceipt",
        "SecurityResult",
        "SecurityResultFamily",
        "SecurityResultValidationError",
        "issue_proof_receipt",
        "map_legacy_result",
        "map_xaman_blocker_satisfiability",
        "result_family",
    ),
    "result_policy": (
        "PortfolioVerdict",
        "ResultPolicy",
        "ResultSelectionPolicy",
        "SECURITY_RESULT_POLICY_VERSION",
        "SecurityResultAuthority",
        "select_authoritative_result",
        "select_portfolio_result",
    ),
    "artifact_migration": (
        "ArtifactClass",
        "ArtifactMigrationError",
        "ArtifactMigrationIntegrityError",
        "DEFAULT_INVENTORY_PATH",
        "DEFAULT_MANIFEST_PATH",
        "MigrationIntegrityReceipt",
        "SECURITY_ARTIFACT_MIGRATION_RECEIPT_VERSION",
        "SECURITY_ARTIFACT_MIGRATION_VERSION",
        "SECURITY_ARTIFACT_RECORD_VERSION",
        "audit_migration_integrity",
        "build_artifact_migration_manifest",
        "build_migration_manifest",
        "load_migration_manifest",
        "migrate_legacy_reference",
        "render_migration_manifest",
        "restore_inventory_records",
        "reverse_migration",
        "validate_artifact_migration_manifest",
        "validate_migration_manifest",
        "verify_migration_integrity",
    ),
    "formalization_adapter": (
        "SECURITY_IR_ADAPTER_CONFIG_ID",
        "SECURITY_IR_ADAPTER_PRODUCER_ID",
        "SECURITY_IR_CLAIM_VIEW_ID",
        "SECURITY_IR_DOMAIN",
        "SECURITY_IR_FORMALIZATION_ADAPTER_VERSION",
        "SECURITY_IR_FORMALIZATION_CONFIG_ID",
        "SECURITY_IR_FORMALIZATION_DOMAIN",
        "SECURITY_IR_FORMALIZATION_PRODUCER_ID",
        "SECURITY_IR_FORMALIZATION_VIEW_REGISTRY",
        "SECURITY_IR_POLICY_VIEW_ID",
        "SECURITY_IR_THREAT_VIEW_ID",
        "SECURITY_IR_TRANSITION_VIEW_ID",
        "SECURITY_IR_VIEW_REGISTRY",
        "SecurityIRAdapter",
        "SecurityIRAdapterError",
        "SecurityIRFormalizationAdapter",
        "SecurityIRFormalizationAdapterError",
        "adapt_security_ir",
        "adapt_security_sample",
    ),
    "exchange.adapter": (
        "EXCHANGE_ADAPTER_VERSION",
        "DeclaredExtensionAdapter",
        "ExchangeAdapter",
        "ExchangeAdapterError",
        "ExchangeSecurityAdapter",
        "ExtensionAdapter",
        "ExtensionAdapters",
        "adapt_exchange_model",
        "adapt_exchange_security_ir",
        "adapt_legacy_exchange_security_ir",
        "to_legacy_exchange_ir",
        "to_legacy_exchange_security_ir",
        "validate_exchange_security_ir",
    ),
    "exchange.vocabulary": (
        "DEFAULT_EXCHANGE_CLAIMS",
        "DEFAULT_EXCHANGE_CLAIMS_BY_ID",
        "EXCHANGE_ASSUMPTIONS",
        "EXCHANGE_DOMAINS",
        "EXCHANGE_EVENT_TYPES",
        "EXCHANGE_EXTENSION_FIELDS",
        "EXCHANGE_EXTENSION_ID",
        "EXCHANGE_POLICY_NAMES",
        "EXCHANGE_PROVER_TARGETS",
        "EXCHANGE_RESOURCE_KINDS",
        "EXCHANGE_SCHEMA_VERSION",
        "EXCHANGE_VOCABULARY",
        "EXCHANGE_VOCABULARY_NAMESPACE",
        "EXCHANGE_VOCABULARY_SCHEMA_VERSION",
        "EXCHANGE_VOCABULARY_VERSION",
        "EXCHANGE_WALLET_STATUSES",
        "ExchangeClaimSpec",
        "ExchangeVocabularyError",
        "exchange_term",
        "parse_exchange_term",
        "validate_exchange_extension",
        "validate_exchange_vocabulary",
    ),
    "xaman.adapter": (
        "XAMAN_ADAPTER_VERSION",
        "XAMAN_EVIDENCE_REQUIREMENT_VERSION",
        "XamanAdapterError",
        "XamanAdapterResult",
        "XamanEvidenceRequirement",
        "XamanSecurityAdapter",
        "adapt_xaman_declaration",
        "adapt_xaman_security_ir",
        "to_legacy_xaman_declaration",
        "to_legacy_xaman_security_ir",
        "validate_xaman_security_ir",
    ),
    "xaman.config": (
        "DEFAULT_XAMAN_EVIDENCE_REQUIREMENTS",
        "XAMAN_ADAPTER_CONFIG_VERSION",
        "XAMAN_ASSUMPTIONS",
        "XAMAN_EXTENSION_ID",
        "XAMAN_SECURITY_DOMAINS",
        "XAMAN_VOCABULARY",
        "XAMAN_VOCABULARY_SCHEMA_VERSION",
        "XAMAN_VOCABULARY_VERSION",
        "XamanAdapterConfig",
        "XamanConfigError",
        "XamanSecurityAdapterConfig",
        "XamanSourceBinding",
        "XamanSourceConfig",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

if len(_EXPORT_MODULE) != sum(len(names) for names in _EXPORTS.values()):
    raise RuntimeError("Security IR package exports must have one owning module")

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    """Load a reviewed Security IR contract from its owning leaf module."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
