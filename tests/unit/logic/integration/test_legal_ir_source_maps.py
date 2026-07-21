"""Tests for lossless LegalIR source maps and provenance spans."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION,
    LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
    LegalIRArtifactFamily,
    LegalIRSourceMap,
    LegalIRSourceMapBuilder,
    LegalIRTransformationKind,
    assert_legal_ir_artifact_traceable,
    bind_legal_ir_artifact_source_map,
    build_legal_ir_source_map,
    known_legal_ir_schema_versions,
    record_legal_ir_artifact_provenance,
    trace_legal_ir_fact,
    validate_legal_ir_schema_compatibility,
    validate_legal_ir_source_map,
)


SOURCE_TEXT = (
    "The agency shall disclose records within 30 days. "
    "The agency shall not disclose sealed records."
)


def _sample() -> dict[str, object]:
    second = SOURCE_TEXT.index("The agency shall not")
    return {
        "sample_id": "sample-source-map",
        "citation": "42 U.S.C. 1983(a)",
        "modal_ir": {
            "document_id": "doc-source-map",
            "citation": "42 U.S.C. 1983(a)",
            "normalized_text": SOURCE_TEXT,
            "formulas": [
                {
                    "formula_id": "formula-disclose",
                    "operator": {"family": "deontic", "symbol": "shall"},
                    "predicate": {"name": "disclose", "arguments": ["agency", "records"]},
                    "provenance": {
                        "source_id": "doc-source-map",
                        "citation": "42 U.S.C. 1983(a)",
                        "start_char": 0,
                        "end_char": SOURCE_TEXT.index(".") + 1,
                        "transformation_step": "compiler.parse_norm",
                    },
                },
                {
                    "formula_id": "formula-sealed",
                    "operator": {"family": "deontic", "symbol": "shall_not"},
                    "predicate": {
                        "name": "disclose",
                        "arguments": ["agency", "sealed records"],
                    },
                    "provenance": {
                        "source_id": "doc-source-map",
                        "citation": "42 U.S.C. 1983(b)",
                        "start_char": second,
                        "end_char": len(SOURCE_TEXT),
                        "transformation_step": "compiler.parse_exception",
                    },
                },
            ],
        },
    }


def test_build_source_map_preserves_lossless_span_fields_and_schema() -> None:
    source_map = build_legal_ir_source_map(_sample())
    payload = source_map.to_dict()

    assert source_map.schema_version == LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION
    assert LegalIRSourceMap.from_dict(payload) == source_map
    assert payload["sources"][0]["source_document"] == "doc-source-map"
    assert payload["sources"][0]["normalized_text"] == SOURCE_TEXT

    first = source_map.span_by_id[next(iter(source_map.node_by_id["formula-disclose"].span_ids))]
    assert first.source_document_id == "doc-source-map"
    assert first.citation == "42 U.S.C. 1983(a)"
    assert first.start_offset == 0
    assert first.end_offset == SOURCE_TEXT.index(".") + 1
    assert first.token_span.start_token == 0
    assert first.token_span.end_token == 8
    assert first.normalized_text == "The agency shall disclose records within 30 days."
    assert first.transformation_step_id == "compiler.parse_norm"
    assert first.decompiler_attribution == "not_decompiled"

    result = validate_legal_ir_source_map(source_map)
    assert result.valid, result.to_dict()
    schema = validate_legal_ir_schema_compatibility(
        payload,
        artifact_family=LegalIRArtifactFamily.SOURCE_MAP,
    )
    assert schema.reusable, schema.to_dict()
    assert LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION in known_legal_ir_schema_versions()


def test_source_map_supports_one_to_many_and_many_to_one_transforms() -> None:
    builder = LegalIRSourceMapBuilder(source_map_id="map-transforms")
    builder.add_source_document(
        "doc-source-map",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983",
    )
    span = builder.add_span(
        "doc-source-map",
        0,
        SOURCE_TEXT.index(".") + 1,
        transformation_step_id="compiler.parse_norm",
    )
    builder.add_node(
        "formula-disclose",
        node_kind="compiler_formula",
        span_ids=(span.span_id,),
        transformation_step_id="compiler.emit_formula",
    )
    builder.add_node(
        "deontic-disclose",
        node_kind="deontic_view",
        derived=True,
        derived_from_node_ids=("formula-disclose",),
        transformation_step_id="compiler.project_deontic",
    )
    builder.add_node(
        "frame-disclose",
        node_kind="frame_view",
        derived=True,
        derived_from_node_ids=("formula-disclose",),
        transformation_step_id="compiler.project_frame",
    )
    split = builder.add_transform(
        "compiler.project_views",
        LegalIRTransformationKind.COMPILER,
        input_node_ids=("formula-disclose",),
        output_node_ids=("deontic-disclose", "frame-disclose"),
    )
    builder.add_node(
        "diagnostic-disclose",
        node_kind="diagnostic",
        derived=True,
        derived_from_node_ids=("deontic-disclose", "frame-disclose"),
        transformation_step_id="diagnostic.cross_view_check",
    )
    merged = builder.add_transform(
        "diagnostic.cross_view_check",
        LegalIRTransformationKind.DIAGNOSTIC,
        input_node_ids=("deontic-disclose", "frame-disclose"),
        output_node_ids=("diagnostic-disclose",),
    )

    source_map = builder.to_source_map()
    assert source_map.transform_by_id[split.transform_id].one_to_many
    assert source_map.transform_by_id[merged.transform_id].many_to_one
    assert validate_legal_ir_source_map(source_map).valid
    trace = trace_legal_ir_fact(source_map, "diagnostic-disclose")
    assert trace.traceable
    assert trace.derived
    assert [span.normalized_text for span in trace.source_spans] == [
        "The agency shall disclose records within 30 days."
    ]


def test_compiler_decompiler_hammer_guidance_and_diagnostics_are_traceable() -> None:
    builder = LegalIRSourceMapBuilder(source_map_id="map-artifacts")
    builder.add_source_document(
        "doc-source-map",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983",
    )
    source_span = builder.add_span(
        "doc-source-map",
        0,
        SOURCE_TEXT.index(".") + 1,
        transformation_step_id="compiler.parse_norm",
    )
    builder.add_node(
        "formula-disclose",
        node_kind="compiler_formula",
        span_ids=(source_span.span_id,),
        transformation_step_id="compiler.emit_formula",
    )
    builder.add_derived_node(
        "frame-disclose",
        node_kind="compiler_frame",
        derived_from_node_ids=("formula-disclose",),
        transformation_step="compiler.project_frame_logic",
        transform_kind=LegalIRTransformationKind.COMPILER,
    )
    builder.add_derived_node(
        "decompiled-disclose",
        node_kind="decompiler_sentence",
        derived_from_node_ids=("frame-disclose",),
        transformation_step="decompiler.render_surface",
        transform_kind=LegalIRTransformationKind.DECOMPILER,
        decompiler_attribution="modal.decompiler.v1",
    )
    builder.add_derived_node(
        "stable-export-1",
        node_kind="learned_feature_export",
        derived_from_node_ids=("formula-disclose",),
        transformation_step="learned_guidance.stable_feature_export",
        transform_kind=LegalIRTransformationKind.LEARNED_GUIDANCE,
    )

    translation = {
        "schema_version": LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
        "translation_id": "translation-1",
        "obligation_id": "obligation-1",
        "input_formula_id": "formula-disclose",
        "artifact_sha256": "0" * 64,
    }
    receipt = {
        "schema_version": LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
        "receipt_id": "receipt-1",
        "obligation_id": "obligation-1",
        "input_formula_id": "formula-disclose",
        "translation_record_ids": ["translation-1"],
        "trusted": True,
    }
    guidance = {
        "schema_version": LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION,
        "guidance_id": "guidance-1",
        "source_export_id": "stable-export-1",
        "proof_receipt_ids": ["receipt-1"],
    }
    diagnostic = {
        "diagnostic_id": "diagnostic-1",
        "node_id": "decompiled-disclose",
        "severity": "warning",
    }

    record_legal_ir_artifact_provenance(builder, translation, artifact_kind="hammer_translation")
    record_legal_ir_artifact_provenance(builder, receipt, artifact_kind="hammer_receipt")
    record_legal_ir_artifact_provenance(builder, guidance, artifact_kind="learned_guidance")
    record_legal_ir_artifact_provenance(builder, diagnostic, artifact_kind="diagnostic")
    source_map = builder.to_source_map()

    assert validate_legal_ir_source_map(source_map).valid
    for artifact, kind, facts in (
        ({"frame_id": "frame-disclose"}, "compiler", ("frame-disclose",)),
        ({"diagnostic_id": "decompiled-disclose"}, "decompiler", ("decompiled-disclose",)),
        (translation, "hammer_translation", ("translation-1",)),
        (receipt, "hammer_receipt", ("receipt-1",)),
        (guidance, "learned_guidance", ("guidance-1",)),
        (diagnostic, "diagnostic", ("diagnostic-1",)),
    ):
        binding = bind_legal_ir_artifact_source_map(
            artifact,
            source_map,
            artifact_kind=kind,
            emitted_fact_ids=facts,
        )
        assert binding.traceable, binding.to_dict()
        assert binding.derived_fact_ids == facts

    guidance_trace = trace_legal_ir_fact(source_map, "guidance-1")
    assert guidance_trace.traceable
    assert "formula-disclose" in guidance_trace.visited_node_ids
    assert guidance_trace.source_spans[0].source_document_id == "doc-source-map"
    assert any(
        step.transform_kind is LegalIRTransformationKind.LEARNED_GUIDANCE
        for step in guidance_trace.transformation_steps
    )


def test_unmapped_artifact_fails_closed_unless_derived_node_exists() -> None:
    source_map = build_legal_ir_source_map(_sample())
    missing = bind_legal_ir_artifact_source_map(
        {"diagnostic_id": "missing-diagnostic"},
        source_map,
        artifact_kind="diagnostic",
    )

    assert not missing.traceable
    assert missing.missing_fact_ids == ("missing-diagnostic",)
    with pytest.raises(ValueError):
        assert_legal_ir_artifact_traceable(
            {"diagnostic_id": "missing-diagnostic"},
            source_map,
            artifact_kind="diagnostic",
        )
