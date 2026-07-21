"""Tests for LegalIR standards and interchange interoperability."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_INTEROP_SCHEMA_VERSION,
    LegalIRInteropFormat,
    LegalIRInteropLossMode,
    LegalIRSourceMapBuilder,
    assert_legal_ir_interop_round_trip_conformant,
    export_legal_ir_interchange,
    import_legal_ir_interchange,
    read_legal_ir_interchange_json,
    round_trip_legal_ir_interchange,
    supported_legal_ir_projection,
    write_legal_ir_interchange_json,
)


SOURCE_TEXT = "The agency shall disclose records within 30 days."


def _source_map():
    builder = LegalIRSourceMapBuilder(source_map_id="map-interop")
    builder.add_source_document(
        "doc-interop",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983(a)",
    )
    span = builder.add_span(
        "doc-interop",
        0,
        len(SOURCE_TEXT),
        transformation_step_id="interop.test.source",
    )
    builder.add_node(
        "formula-disclose",
        node_kind="compiler_formula",
        span_ids=(span.span_id,),
        emitted_fact="formula-disclose",
        transformation_step_id="interop.test.formula",
    )
    return builder.to_source_map()


def _legal_ir() -> dict[str, object]:
    return {
        "citation": "42 U.S.C. 1983(a)",
        "decompiler": {
            "decompiled_text": SOURCE_TEXT,
            "losses": [
                {
                    "field_path": "obligations.0.proof_status",
                    "reason": "proof_status_not_rendered_to_text",
                }
            ],
            "lossless": False,
            "statements": [SOURCE_TEXT],
        },
        "document_id": "doc-interop",
        "kg": {
            "edges": [{"from": "agency", "kind": "owes", "to": "requester"}],
            "nodes": [
                {"id": "agency", "kind": "legal_actor"},
                {"id": "requester", "kind": "legal_actor"},
            ],
        },
        "legal_ir_outputs": {
            "deontic": {"obligation_ids": ["obl-disclose"]},
            "tdfol": {"formula_ids": ["formula-disclose"]},
        },
        "obligations": [
            {
                "action": ["disclose"],
                "citations": ["42 U.S.C. 1983(a)"],
                "conditions": ["public records request received"],
                "exceptions": ["statutory exemption applies"],
                "formula_id": "formula-disclose",
                "object": ["records"],
                "obligation_id": "obl-disclose",
                "operator": "shall",
                "proof_status": {"status": "proved", "trust_status": "trusted"},
                "source_node_ids": ["formula-disclose"],
                "statement": SOURCE_TEXT,
                "subject": ["agency"],
            }
        ],
        "proof": {
            "artifact_id": "proof-interop",
            "evidence": {
                "reconstruction_receipts": [
                    {
                        "obligation_id": "po-disclose",
                        "receipt_id": "receipt-disclose",
                        "trusted": True,
                    }
                ],
                "translation_records": [
                    {
                        "obligation_id": "po-disclose",
                        "translation_id": "translation-disclose",
                    }
                ],
            },
            "verification_policy": {"require_trusted_proofs": True},
        },
        "proof_obligations": [
            {
                "formula_id": "formula-disclose",
                "kind": "deontic_polarity",
                "legal_ir_view": "deontic.ir",
                "logic_family": "deontic",
                "obligation_id": "po-disclose",
                "sample_id": "doc-interop",
                "statement": "notice_disclosure_obligation(formula_disclose)",
            }
        ],
        "text": SOURCE_TEXT,
    }


def test_legal_json_interchange_is_lossless_and_json_serializable(tmp_path) -> None:
    envelope = export_legal_ir_interchange(
        _legal_ir(),
        LegalIRInteropFormat.LEGAL_JSON,
        source_map=_source_map(),
    )

    assert envelope.schema_version == LEGAL_IR_INTEROP_SCHEMA_VERSION
    assert envelope.lossless is True
    assert envelope.loss_markers == ()
    assert envelope.source_map.source_map_id == "map-interop"
    assert envelope.schema_mappings[0].mode == LegalIRInteropLossMode.LOSSLESS.value

    imported = import_legal_ir_interchange(envelope.payload, "legal_json", source_map=envelope.source_map)
    assert imported.legal_ir == envelope.legal_ir

    path = tmp_path / "interop.json"
    write_legal_ir_interchange_json(path, envelope)
    loaded = read_legal_ir_interchange_json(path)
    assert loaded.to_dict() == envelope.to_dict()
    json.loads(json.dumps(envelope.to_dict(), sort_keys=True))


def test_legal_xml_round_trip_preserves_supported_subset_and_marks_unsupported_fields() -> None:
    envelope = export_legal_ir_interchange(_legal_ir(), "legal_xml", source_map=_source_map())

    assert "<LegalDocument" in envelope.payload
    assert envelope.lossless is False
    assert envelope.unsupported_count >= 1
    assert "unsupported_backend_feature" in envelope.diagnostics.families
    assert {marker.feature for marker in envelope.loss_markers} >= {"proof", "legal_ir_outputs"}

    imported = import_legal_ir_interchange(envelope.payload, "xml", source_map=envelope.source_map)
    assert imported.legal_ir["obligations"][0]["statement"] == SOURCE_TEXT
    assert supported_legal_ir_projection(imported.legal_ir, "legal_xml") == supported_legal_ir_projection(
        envelope.legal_ir,
        "legal_xml",
    )

    round_trip = assert_legal_ir_interop_round_trip_conformant(
        _legal_ir(),
        "legal_xml",
        source_map=_source_map(),
    )
    assert round_trip.conformant is True
    assert round_trip.lossless is False


def test_rdf_owl_and_kg_profiles_emit_schema_mappings_and_round_trip_supported_subset() -> None:
    rdf = export_legal_ir_interchange(_legal_ir(), "rdf_owl", source_map=_source_map())
    assert rdf.payload["@context"]["owl"] == "http://www.w3.org/2002/07/owl#"
    assert any(node.get("@type") == "lir:Obligation" for node in rdf.payload["@graph"])
    assert any(mapping.feature == "rdf_owl" for mapping in rdf.schema_mappings)
    assert round_trip_legal_ir_interchange(_legal_ir(), "rdf", source_map=_source_map()).conformant

    kg = export_legal_ir_interchange(_legal_ir(), "kg_json", source_map=_source_map())
    assert any(node["kind"] == "obligation" for node in kg.payload["nodes"])
    assert any(edge["kind"] == "has_obligation" for edge in kg.payload["edges"])
    kg_import = import_legal_ir_interchange(kg.payload, "knowledge_graph", source_map=kg.source_map)
    assert kg_import.legal_ir["obligations"][0]["obligation_id"] == "obl-disclose"
    assert round_trip_legal_ir_interchange(_legal_ir(), "kg", source_map=_source_map()).conformant


def test_proof_interchange_preserves_evidence_subset_and_reports_document_loss() -> None:
    proof = export_legal_ir_interchange(_legal_ir(), "proof", source_map=_source_map())

    assert proof.payload["proof_obligations"][0]["obligation_id"] == "po-disclose"
    assert proof.payload["evidence"]["translation_records"][0]["translation_id"] == "translation-disclose"
    assert proof.unsupported_count >= 1
    assert {marker.feature for marker in proof.loss_markers} >= {"obligations", "text"}

    imported = import_legal_ir_interchange(proof.payload, "proof_json", source_map=proof.source_map)
    assert imported.legal_ir["proof"]["evidence"] == proof.legal_ir["proof"]["evidence"]

    round_trip = round_trip_legal_ir_interchange(_legal_ir(), "proof", source_map=_source_map())
    assert round_trip.conformant is True
    assert round_trip.supported_before == round_trip.supported_after


def test_decompiler_interchange_carries_loss_markers_and_round_trip_statements() -> None:
    decompiler = export_legal_ir_interchange(_legal_ir(), "decompiler_json", source_map=_source_map())

    assert decompiler.payload["decompiled_text"] == SOURCE_TEXT
    assert decompiler.payload["lossless"] is False
    assert any(marker.mode == LegalIRInteropLossMode.LOSSY.value for marker in decompiler.loss_markers)
    assert "decompiler_loss" in decompiler.diagnostics.families

    imported = import_legal_ir_interchange(decompiler.payload, "decompiler_json", source_map=decompiler.source_map)
    assert imported.legal_ir["decompiler"]["statements"] == [SOURCE_TEXT]

    round_trip = round_trip_legal_ir_interchange(_legal_ir(), "decompiler_json", source_map=_source_map())
    assert round_trip.conformant is True
    assert round_trip.supported_before == round_trip.supported_after
