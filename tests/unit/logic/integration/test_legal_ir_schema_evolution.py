"""Tests for LegalIR schema evolution and compatibility gates."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    HAMMER_GUIDANCE_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION,
    LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION,
    LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
    LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION,
    LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION,
    LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    MODAL_COMPILER_REPAIR_SCHEMA_VERSION,
    LegalIRArtifactFamily,
    LegalIRSchemaCompatibility,
    LegalIRSchemaCompatibilityError,
    assert_legal_ir_schema_compatible,
    bind_legal_ir_metric_lineage,
    downgrade_legal_ir_schema,
    known_legal_ir_schema_versions,
    legal_ir_feature_gate_enabled,
    legal_ir_schema_evolution_manifest,
    legal_ir_schema_version_registry,
    migrate_legal_ir_schema,
    validate_legal_ir_schema_compatibility,
)


def _learned_export() -> dict[str, object]:
    return {
        "export_id": "lir-export-schema-evolution",
        "schema_version": LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
        "stable_features": [
            {
                "feature": "compiler-contract:force-polarity:obligation",
                "feature_group": "compiler_contract",
                "stable": True,
            }
        ],
    }


def _hammer_receipt() -> dict[str, object]:
    return {
        "obligation_id": "obligation-schema-evolution",
        "receipt_id": "receipt-schema-evolution",
        "schema_version": LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
        "trusted": True,
    }


def _compiler_output() -> dict[str, object]:
    return {
        "frame_id": "frame-schema-evolution",
        "provenance_ids": ["prov:sha256:abc"],
        "schema_version": MODAL_COMPILER_REPAIR_SCHEMA_VERSION,
    }


def test_manifest_lists_explicit_versions_migrations_feature_gates_and_deprecations() -> None:
    manifest = legal_ir_schema_evolution_manifest()

    assert manifest["schema_version"] == LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION
    assert manifest["registry_version"] == LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION
    known = known_legal_ir_schema_versions()
    assert LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION in known
    assert LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION in known
    assert LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION in known
    assert LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION in known
    assert MODAL_COMPILER_REPAIR_SCHEMA_VERSION in known
    assert any(
        item["source_schema_version"] == LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION
        and item["target_schema_version"] == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
        for item in manifest["migrations"]
    )
    legacy = legal_ir_schema_version_registry()[LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION]
    assert legacy.deprecation.status.value == "deprecated"
    assert legacy.migration_targets == (LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,)


@pytest.mark.parametrize(
    ("payload", "family"),
    [
        (_learned_export(), LegalIRArtifactFamily.LEARNED_EXPORT),
        (_hammer_receipt(), LegalIRArtifactFamily.HAMMER_RECEIPT),
        (
            {
                "guidance_id": "hammer-guidance-schema-evolution",
                "obligation_id": "obligation-schema-evolution",
                "schema_version": HAMMER_GUIDANCE_SCHEMA_VERSION,
                "trusted": True,
            },
            LegalIRArtifactFamily.HAMMER_RECEIPT,
        ),
        (
            {
                "classification": "missing_rule",
                "proof_obligation_ids": ["obligation-schema-evolution"],
                "request_id": "leanstral-audit-schema-evolution",
                "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            },
            LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        ),
        (
            {
                "entries": [],
                "key": "leanstral-cache-key",
                "response": {"request_id": "leanstral-audit-schema-evolution"},
                "schema_version": LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION,
            },
            LegalIRArtifactFamily.CACHE,
        ),
        (_compiler_output(), LegalIRArtifactFamily.COMPILER_OUTPUT),
    ],
)
def test_known_artifact_families_are_reusable(payload: dict[str, object], family) -> None:
    result = validate_legal_ir_schema_compatibility(payload, artifact_family=family)

    assert result.reusable, result.to_dict()
    assert result.compatibility is LegalIRSchemaCompatibility.COMPATIBLE
    assert assert_legal_ir_schema_compatible(payload, artifact_family=family).reusable


@pytest.mark.parametrize(
    ("payload", "family", "code"),
    [
        ({"export_id": "no-schema"}, LegalIRArtifactFamily.LEARNED_EXPORT, "schema_version_missing"),
        (
            {"schema_version": "legal-ir-stable-autoencoder-feature-export-v999", "export_id": "unknown"},
            LegalIRArtifactFamily.LEARNED_EXPORT,
            "unknown_schema_version",
        ),
        (
            {
                "export_id": "wrong-family",
                "schema_version": HAMMER_GUIDANCE_SCHEMA_VERSION,
                "stable_features": [],
            },
            LegalIRArtifactFamily.LEARNED_EXPORT,
            "schema_family_mismatch",
        ),
        (
            {
                "obligation_id": "missing-receipt",
                "schema_version": LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
                "trusted": True,
            },
            LegalIRArtifactFamily.HAMMER_RECEIPT,
            "required_schema_field_missing",
        ),
    ],
)
def test_unknown_or_inconsistent_artifacts_are_rejected(
    payload: dict[str, object], family: LegalIRArtifactFamily, code: str
) -> None:
    result = validate_legal_ir_schema_compatibility(payload, artifact_family=family)

    assert not result.reusable
    assert code in {issue.code for issue in result.issues}
    with pytest.raises(LegalIRSchemaCompatibilityError):
        assert_legal_ir_schema_compatible(payload, artifact_family=family)


def test_leanstral_audit_migration_and_downgrade_are_explicit() -> None:
    legacy = {
        "classification": "missing_rule",
        "request_id": "leanstral-audit-legacy",
        "schema_version": LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
    }

    result = validate_legal_ir_schema_compatibility(
        legacy,
        artifact_family=LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        reader_schema_version=LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    )
    assert result.requires_migration
    assert not result.reusable
    assert result.migration_path == (
        LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
        LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    )

    migrated = migrate_legal_ir_schema(legacy, LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION)
    assert migrated["schema_version"] == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
    assert migrated["proof_obligation_ids"] == []
    assert validate_legal_ir_schema_compatibility(migrated).reusable

    downgraded = downgrade_legal_ir_schema(
        migrated,
        LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
    )
    assert downgraded["schema_version"] == LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION
    assert "proposed_compiler_surface" not in downgraded
    with pytest.raises(LegalIRSchemaCompatibilityError):
        downgrade_legal_ir_schema(_learned_export(), LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION)


def test_feature_gates_require_known_compatible_schema_versions() -> None:
    assert legal_ir_feature_gate_enabled(
        "schema.compatibility.reuse",
        _learned_export(),
        artifact_family=LegalIRArtifactFamily.LEARNED_EXPORT,
    )
    assert legal_ir_feature_gate_enabled(
        "hammer.receipt.trusted-reuse",
        _hammer_receipt(),
        artifact_family=LegalIRArtifactFamily.HAMMER_RECEIPT,
    )
    assert legal_ir_feature_gate_enabled(
        "compiler.output.training-reuse",
        _compiler_output(),
        artifact_family=LegalIRArtifactFamily.COMPILER_OUTPUT,
    )
    assert not legal_ir_feature_gate_enabled(
        "schema.compatibility.reuse",
        {"schema_version": "legal-ir-unknown-v1", "export_id": "bad"},
        artifact_family=LegalIRArtifactFamily.LEARNED_EXPORT,
    )
    assert not legal_ir_feature_gate_enabled(
        "unknown.gate",
        _learned_export(),
        artifact_family=LegalIRArtifactFamily.LEARNED_EXPORT,
    )


def test_metric_lineage_binding_rejects_unchecked_or_unbound_artifacts() -> None:
    metric = {
        "evidence_id": "metric-evidence-schema-evolution",
        "metric_lineage": {
            "compiler_output_ids": ["frame-schema-evolution"],
            "learned_export_id": "lir-export-schema-evolution",
            "proof_receipt_ids": ["receipt-schema-evolution"],
        },
        "schema_version": LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION,
    }

    binding = bind_legal_ir_metric_lineage(
        metric,
        [_learned_export(), _hammer_receipt(), _compiler_output()],
        required_artifact_families=(
            LegalIRArtifactFamily.LEARNED_EXPORT,
            LegalIRArtifactFamily.HAMMER_RECEIPT,
            LegalIRArtifactFamily.COMPILER_OUTPUT,
        ),
    )
    assert binding.reusable, binding.to_dict()
    assert binding.artifact_bindings["learned_export"] == (
        "lir-export-schema-evolution",
    )

    rejected = bind_legal_ir_metric_lineage(
        metric,
        [
            _learned_export(),
            {"receipt_id": "unbound-receipt", "schema_version": "legal-ir-hammer-reconstruction-receipt-v999"},
        ],
        required_artifact_families=(LegalIRArtifactFamily.HAMMER_RECEIPT,),
    )
    assert not rejected.reusable
    assert rejected.rejected_artifacts
    assert "missing_required_artifact_family:hammer_receipt" in rejected.missing_lineage


def test_metrics_without_lineage_are_not_reusable_for_schema_evolution() -> None:
    result = validate_legal_ir_schema_compatibility(
        {"schema_version": LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION},
        artifact_family=LegalIRArtifactFamily.METRIC,
        require_lineage=True,
    )

    assert not result.reusable
    assert "metric_lineage_field_missing" in {issue.code for issue in result.issues}
