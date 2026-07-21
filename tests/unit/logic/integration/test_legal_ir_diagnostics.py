"""Tests for structured LegalIR diagnostics and explanation traces."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION,
    LegalIRDiagnosticCode,
    LegalIRDiagnosticFamily,
    LegalIRDiagnosticReport,
    LegalIRDiagnosticsBuilder,
    LegalIRSourceMapBuilder,
    LegalIRTransformationKind,
    attach_legal_ir_diagnostic_to_source_map,
    build_legal_ir_diagnostic_report,
    collect_legal_ir_diagnostics,
    trace_legal_ir_fact,
    validate_legal_ir_source_map,
)


SOURCE_TEXT = "The agency shall disclose records unless the record is sealed."


def _source_map():
    builder = LegalIRSourceMapBuilder(source_map_id="map-diagnostics")
    builder.add_source_document(
        "doc-diagnostics",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983(a)",
    )
    span = builder.add_span(
        "doc-diagnostics",
        0,
        SOURCE_TEXT.index(".") + 1,
        transformation_step_id="compiler.parse",
    )
    builder.add_node(
        "formula-disclose",
        node_kind="compiler_formula",
        span_ids=(span.span_id,),
        transformation_step_id="compiler.emit_formula",
    )
    builder.add_derived_node(
        "decompiled-disclose",
        node_kind="decompiler_sentence",
        derived_from_node_ids=("formula-disclose",),
        transformation_step="decompiler.render",
        transform_kind=LegalIRTransformationKind.DECOMPILER,
    )
    return builder.to_source_map()


def test_builder_emits_required_diagnostic_families_with_source_maps_and_hints() -> None:
    source_map = _source_map()
    builder = LegalIRDiagnosticsBuilder(
        artifact_id="artifact-diagnostics",
        source_map=source_map,
    )

    builder.add_unresolved_symbol(
        "Referenced actor has no scoped definition.",
        source_node_ids=("formula-disclose",),
        related_ids={"reference_id": ("ref-agency",)},
    )
    builder.add_unresolved_citation(
        "Citation target could not be resolved.",
        source_node_ids=("formula-disclose",),
        related_ids={"reference_id": ("cite-1",)},
    )
    builder.add_ambiguity(
        "Competing deontic scope parses remain unresolved.",
        source_node_ids=("formula-disclose",),
        related_ids={"ambiguity_id": ("amb-1",)},
    )
    builder.add_temporal_authority(
        "Repealed authority was selected for the query date.",
        source_node_ids=("formula-disclose",),
        related_ids={"law_version_id": ("law-old",)},
    )
    builder.add_unsupported_backend_feature(
        "TDFOL backend cannot represent emergency sunset windows.",
        related_ids={"backend": ("tdfol",), "feature": ("temporal_window",)},
    )
    builder.add_proof_failure(
        "Hammer receipt was not kernel trusted.",
        source_node_ids=("formula-disclose",),
        related_ids={"receipt_id": ("receipt-1",), "obligation_id": ("obl-1",)},
    )
    builder.add_learned_guidance_abstention(
        "No stable learned guidance met the canary threshold.",
        related_ids={"promotion_id": ("promotion-1",)},
    )
    builder.add_poisoning_rejection(
        "Prompt injection marker was rejected before proof use.",
        field_path="premises.0.text",
        related_ids={"artifact_id": ("premise-1",)},
    )
    builder.add_decompiler_loss(
        "Decompiler dropped the exception scope field.",
        source_node_ids=("decompiled-disclose",),
        field_path="exception_scope",
        related_ids={"failure_id": ("loss-1",), "formula_id": ("formula-disclose",)},
    )
    builder.add_codex_repair_attribution(
        "Codex repair attribution recorded closed-loop outcome accepted_benefit.",
        related_ids={"lineage_id": ("lineage-1",), "todo_id": ("todo-1",)},
    )

    report = builder.build(report_id="report-diagnostics")
    payload = report.to_dict()

    assert report.schema_version == LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION
    assert payload["schema_version"] == LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION
    assert set(report.families) == {
        LegalIRDiagnosticFamily.SYMBOL.value,
        LegalIRDiagnosticFamily.CITATION.value,
        LegalIRDiagnosticFamily.AMBIGUITY.value,
        LegalIRDiagnosticFamily.TEMPORAL_AUTHORITY.value,
        LegalIRDiagnosticFamily.UNSUPPORTED_BACKEND_FEATURE.value,
        LegalIRDiagnosticFamily.PROOF_FAILURE.value,
        LegalIRDiagnosticFamily.LEARNED_GUIDANCE_ABSTENTION.value,
        LegalIRDiagnosticFamily.POISONING_REJECTION.value,
        LegalIRDiagnosticFamily.DECOMPILER_LOSS.value,
        LegalIRDiagnosticFamily.CODEX_REPAIR_ATTRIBUTION.value,
    }
    assert len(report.diagnostics) == 10
    assert len(report.traces) == 10
    for diagnostic in payload["diagnostics"]:
        assert diagnostic["severity"]
        assert diagnostic["family"]
        assert diagnostic["source_map"]["source_map_id"] == "map-diagnostics"
        assert diagnostic["remediation_hint"]
        assert diagnostic["code"].startswith("legal_ir.")
        assert diagnostic["explanation_trace_id"]
    assert report.by_family(LegalIRDiagnosticFamily.DECOMPILER_LOSS)[0].source_map.source_span_ids

    round_trip = LegalIRDiagnosticReport.from_dict(json.loads(json.dumps(payload)))
    assert round_trip.to_dict() == payload


def test_collector_normalizes_existing_artifact_diagnostics() -> None:
    source_map = _source_map()
    symbol_result = {
        "diagnostics": [
            {
                "diagnostic_type": "unresolved_symbol",
                "message": "Symbol is missing.",
                "reference_id": "ref-1",
                "source_node_ids": ["formula-disclose"],
            }
        ]
    }
    citation_result = {
        "diagnostics": [
            {
                "diagnostic_type": "ambiguous_citation",
                "message": "Citation matched two targets.",
                "target_ids": ["t1", "t2"],
            }
        ]
    }
    backend_result = {
        "unsupported_diagnostics": [
            {
                "backend": "tdfol",
                "feature": "temporal",
                "reason_code": "unsupported_emergency_sunset",
                "obligation_ids": ["obl-1"],
            }
        ]
    }
    security_result = {
        "artifact_id": "premise-1",
        "accepted": False,
        "findings": [
            {
                "reason": "prompt_injection",
                "field_path": "premises.0.text",
                "detail": "Instruction-like legal source text was rejected.",
            }
        ],
    }
    telemetry = {
        "decompiler_preservation_failures": [
            {
                "failure_id": "loss-1",
                "field_path": "predicate.arguments",
                "formula_id": "formula-disclose",
                "reason": "preserved_value_mismatch",
                "source_contract_id": "modal_ir",
            }
        ]
    }
    proof_receipt = {
        "receipt_id": "receipt-1",
        "obligation_id": "obl-1",
        "input_formula_id": "formula-disclose",
        "trusted": False,
        "proof_checked": False,
        "reconstruction_status": "not_reconstructed",
    }
    guidance = {
        "promotion_id": "promotion-1",
        "source_export_id": "stable-export-1",
        "promoted": False,
        "block_reasons": ["missing_guardrail_evidence"],
    }
    lineage = {
        "schema_version": "legal-ir-compiler-repair-lineage-v1",
        "stable_id": "lineage-1",
        "todo_id": "todo-1",
        "classification": {"outcome": "quality_regression"},
        "evidence_refs": [{"stable_id": "receipt-1"}],
    }

    report = build_legal_ir_diagnostic_report(
        symbol_result,
        citation_result,
        backend_result,
        security_result,
        telemetry,
        proof_receipt,
        guidance,
        lineage,
        source_map=source_map,
    )

    codes = {diagnostic.code for diagnostic in report.diagnostics}
    assert LegalIRDiagnosticCode.UNRESOLVED_SYMBOL.value in codes
    assert LegalIRDiagnosticCode.AMBIGUOUS_CITATION.value in codes
    assert LegalIRDiagnosticCode.UNSUPPORTED_BACKEND_FEATURE.value in codes
    assert LegalIRDiagnosticCode.POISONING_REJECTION.value in codes
    assert LegalIRDiagnosticCode.DECOMPILER_LOSS.value in codes
    assert LegalIRDiagnosticCode.PROOF_FAILURE.value in codes
    assert LegalIRDiagnosticCode.LEARNED_GUIDANCE_ABSTENTION.value in codes
    assert LegalIRDiagnosticCode.CODEX_REPAIR_ATTRIBUTION.value in codes
    assert report.by_family("unsupported_backend_feature")[0].severity.value == "warning"


def test_diagnostic_nodes_are_traceable_when_attached_to_source_map() -> None:
    source_map = _source_map()
    diagnostics = collect_legal_ir_diagnostics(
        [
            {
                "diagnostics": [
                    {
                        "diagnostic_type": "source_provenance_untraceable",
                        "message": "Derived fact lost source provenance.",
                        "source_node_ids": ["decompiled-disclose"],
                    }
                ]
            }
        ],
        source_map=source_map,
    )
    diagnostic = diagnostics.diagnostics[0]

    builder = LegalIRSourceMapBuilder(source_map_id="map-diagnostic-node")
    builder.add_source_document(
        "doc-diagnostics",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983(a)",
    )
    span = builder.add_span(
        "doc-diagnostics",
        0,
        SOURCE_TEXT.index(".") + 1,
        transformation_step_id="compiler.parse",
    )
    builder.add_node(
        "decompiled-disclose",
        node_kind="decompiler_sentence",
        span_ids=(span.span_id,),
        transformation_step_id="decompiler.render",
    )

    node_id = attach_legal_ir_diagnostic_to_source_map(builder, diagnostic)
    mapped = builder.to_source_map()
    trace = trace_legal_ir_fact(mapped, node_id)

    assert validate_legal_ir_source_map(mapped).valid
    assert trace.traceable
    assert trace.source_spans[0].source_document_id == "doc-diagnostics"
