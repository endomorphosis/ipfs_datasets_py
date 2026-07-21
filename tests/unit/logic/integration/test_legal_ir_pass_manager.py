"""Tests for the verified LegalIR pass manager."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION,
    LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION,
    LegalIRInvalidationRule,
    LegalIRPassKind,
    LegalIRPassManager,
    LegalIRPassSpec,
    LegalIRPassValidationError,
    LegalIRProtectedMutationJustification,
    LegalIRSchemaMigrationSpec,
    LegalIRSourceMapBuilder,
    apply_declared_schema_migration,
    default_legal_ir_passes,
    legal_ir_pass_manager_manifest,
    replay_legal_ir_passes,
    run_legal_ir_passes,
    validate_legal_ir_passes,
)


SOURCE_TEXT = "The agency shall disclose records within 30 days."


def _source_map() -> dict[str, object]:
    builder = LegalIRSourceMapBuilder(source_map_id="pass-manager-source-map")
    span = builder.add_source_document(
        "doc-pass-manager",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983(a)",
    )
    del span
    source_span = builder.add_span(
        "doc-pass-manager",
        0,
        len(SOURCE_TEXT),
        transformation_step_id="compiler.source_ingest",
    )
    builder.add_node(
        "formula-disclose",
        node_kind="compiler_formula",
        span_ids=(source_span.span_id,),
        emitted_fact="formula-disclose",
        transformation_step_id="compiler.emit_formula",
    )
    return builder.to_source_map().to_dict()


def test_default_manifest_declares_ordered_compiler_decompiler_contracts() -> None:
    validation = validate_legal_ir_passes()
    manifest = legal_ir_pass_manager_manifest()

    assert validation.valid, validation.to_dict()
    assert manifest["schema_version"] == LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION
    assert manifest["valid"] is True
    assert manifest["ordered_pass_ids"] == [
        item.pass_id for item in sorted(default_legal_ir_passes(), key=lambda item: item.order)
    ]
    assert manifest["ordered_pass_ids"].index("legal_ir.source_ingest") < manifest[
        "ordered_pass_ids"
    ].index("legal_ir.decompile")
    assert any(item["kind"] == "decompiler" for item in manifest["passes"])
    assert any(item["schema_migrations"] for item in manifest["passes"])
    assert any(item["hammer_obligations"] for item in manifest["passes"])
    assert any(item["invalidation_rules"] for item in manifest["passes"])
    assert any(
        item["pass_id"] == "legal_ir.source_map_validate"
        and item["declared_inputs"] == ["source_map", "decompiler_map", "hammer_receipts"]
        for item in manifest["passes"]
    )


def test_pass_execution_records_invalidation_and_deterministic_replay() -> None:
    passes = (
        LegalIRPassSpec(
            pass_id="normalize",
            title="Normalize",
            kind=LegalIRPassKind.COMPILER,
            order=1,
            declared_inputs=("raw_document",),
            declared_outputs=("normalized_document",),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("parsed_formulas",),
                    when_outputs_change=("normalized_document",),
                    reason="normalized source changed",
                ),
            ),
        ),
        LegalIRPassSpec(
            pass_id="lower",
            title="Lower",
            kind=LegalIRPassKind.COMPILER,
            order=2,
            declared_inputs=("normalized_document",),
            declared_outputs=("lowered_views",),
        ),
    )

    functions = {
        "normalize": lambda state: {
            **state,
            "normalized_document": str(state["raw_document"]).strip().lower(),
        },
        "lower": lambda state: {
            **state,
            "lowered_views": {"deontic": state["normalized_document"]},
        },
    }
    run = run_legal_ir_passes(
        {"raw_document": "  SHALL DISCLOSE  "},
        functions,
        passes=passes,
    )
    replay = replay_legal_ir_passes(
        {"raw_document": "  SHALL DISCLOSE  "},
        run,
        functions,
        passes=passes,
    )

    assert run.schema_version == LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION
    assert run.successful
    assert run.replay_digest == replay.replay_digest
    assert run.records[0].invalidated_paths == ("parsed_formulas",)
    assert run.output_state["lowered_views"] == {"deontic": "shall disclose"}


def test_source_map_preservation_is_checked_for_traceability() -> None:
    passes = (
        LegalIRPassSpec(
            pass_id="preserve",
            title="Preserve",
            kind=LegalIRPassKind.COMPILER,
            order=1,
            declared_inputs=("source_map",),
            declared_outputs=("lowered_views",),
            preserves_source_map=True,
        ),
    )
    run = run_legal_ir_passes(
        {"source_map": _source_map()},
        {"preserve": lambda state: {**state, "lowered_views": {"ok": True}}},
        passes=passes,
    )

    assert run.successful
    assert run.records[0].source_map_preserved is True
    assert run.records[0].protected_mutations == ()


def test_dropping_source_map_is_rejected() -> None:
    passes = (
        LegalIRPassSpec(
            pass_id="drop-map",
            title="Drop map",
            kind=LegalIRPassKind.COMPILER,
            order=1,
            declared_inputs=("source_map",),
            declared_outputs=("lowered_views",),
            preserves_source_map=True,
        ),
    )

    with pytest.raises(LegalIRPassValidationError):
        run_legal_ir_passes(
            {"source_map": _source_map()},
            {"drop-map": lambda state: {"lowered_views": {"bad": True}}},
            passes=passes,
        )


def test_declared_schema_migration_uses_registered_migration_and_preserves_replay() -> None:
    migration = LegalIRSchemaMigrationSpec(
        source_schema_version=LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
        target_schema_version=LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        migration_id="leanstral-audit-response-v1-to-v2",
        artifact_family="leanstral_audit",
    )
    passes = (
        LegalIRPassSpec(
            pass_id="migrate",
            title="Migrate",
            kind=LegalIRPassKind.SCHEMA_MIGRATION,
            order=1,
            declared_inputs=("schema_version",),
            declared_outputs=("schema_version", "proof_obligation_ids"),
            schema_migrations=(migration,),
            protected_mutation_justifications=(
                LegalIRProtectedMutationJustification(
                    field_path="schema_version",
                    diagnostic_code="schema_migration_declared",
                ),
                LegalIRProtectedMutationJustification(
                    field_path="proof_obligation_ids",
                    diagnostic_code="schema_migration_declared",
                ),
            ),
        ),
    )
    legacy = {
        "classification": "missing_rule",
        "request_id": "audit-pass-manager",
        "schema_version": LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
    }

    run = run_legal_ir_passes(
        legacy,
        {"migrate": lambda state: apply_declared_schema_migration(state, migration)},
        passes=passes,
    )

    assert run.successful, run.to_dict()
    assert run.output_state["schema_version"] == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
    assert run.output_state["proof_obligation_ids"] == []
    assert run.records[0].schema_migration_path == (
        LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
        LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    )


def test_pass_declaring_protected_output_without_proof_or_diagnostic_is_invalid() -> None:
    result = validate_legal_ir_passes(
        (
            LegalIRPassSpec(
                pass_id="bad-provenance",
                title="Bad provenance",
                kind=LegalIRPassKind.COMPILER,
                order=1,
                declared_inputs=("lowered_views",),
                declared_outputs=("provenance_ids",),
            ),
        )
    )

    assert not result.valid
    assert {
        diagnostic.code for diagnostic in result.diagnostics
    } == {"protected_output_requires_proof_or_diagnostic"}


def test_runtime_protected_field_mutation_requires_proof_or_explicit_diagnostic() -> None:
    passes = (
        LegalIRPassSpec(
            pass_id="mutate-provenance",
            title="Mutate provenance",
            kind=LegalIRPassKind.COMPILER,
            order=1,
            declared_inputs=("lowered_views",),
            declared_outputs=("lowered_views",),
        ),
    )

    with pytest.raises(LegalIRPassValidationError):
        run_legal_ir_passes(
            {"lowered_views": {}, "provenance_ids": ["prov:old"]},
            {
                "mutate-provenance": lambda state: {
                    **state,
                    "provenance_ids": ["prov:new"],
                }
            },
            passes=passes,
        )

    run = run_legal_ir_passes(
        {"lowered_views": {}, "provenance_ids": ["prov:old"]},
        {
            "mutate-provenance": lambda state: {
                **state,
                "diagnostics": [
                    {
                        "code": "provenance_rewritten_by_operator",
                        "field_path": "provenance_ids",
                        "pass_id": "mutate-provenance",
                        "severity": "warning",
                    }
                ],
                "provenance_ids": ["prov:new"],
            }
        },
        passes=passes,
    )

    assert run.successful
    assert run.records[0].protected_mutations == ("provenance_ids",)
    assert "undeclared_output_mutation" in {
        diagnostic.code for diagnostic in run.records[0].diagnostics
    }
