"""Tests for canonical LegalIR citation and cross-reference linking."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION,
    LegalIRCitationDiagnosticType,
    LegalIRCitationGraph,
    LegalIRCitationGraphBuilder,
    LegalIRCitationKind,
    LegalIRCitationResolutionStatus,
    LegalIRCitationUse,
    LegalIRSourceMap,
    LegalIRSourceMapBuilder,
    assert_legal_ir_citations_resolved,
    build_legal_ir_citation_graph,
    legal_ir_citations_allowed_for_use,
    normalize_legal_citation,
    parse_legal_citation,
    resolve_legal_ir_citation,
    validate_legal_ir_citation_graph,
)


SOURCE_TEXT = (
    "ORS 192.001 requires disclosure. "
    "ORS 192.003 through ORS 192.005 are incorporated by reference. "
    "Former ORS 192.999 is repealed. "
    "Section 192.001(1)(a) cross-references the agency rule."
)


def _source_map() -> LegalIRSourceMap:
    builder = LegalIRSourceMapBuilder(source_map_id="map-citations")
    builder.add_source_document("doc-citations", SOURCE_TEXT, citation="ORS 192.001")
    spans = {
        "doc-citations": (0, len(SOURCE_TEXT)),
        "target:ors-192-001": (0, SOURCE_TEXT.index(".")),
        "target:ors-192-003": (SOURCE_TEXT.index("ORS 192.003"), SOURCE_TEXT.index(" are incorporated")),
        "target:ors-192-005": (SOURCE_TEXT.index("ORS 192.003"), SOURCE_TEXT.index(" are incorporated")),
        "target:ors-192-999": (SOURCE_TEXT.index("Former"), SOURCE_TEXT.index("Section") - 1),
        "ref:internal-subsection": (SOURCE_TEXT.index("Section 192.001"), len(SOURCE_TEXT)),
        "ref:range": (SOURCE_TEXT.index("ORS 192.003"), SOURCE_TEXT.index(" are incorporated")),
        "ref:repealed": (SOURCE_TEXT.index("Former"), SOURCE_TEXT.index(" is repealed")),
        "ref:missing": (SOURCE_TEXT.index("agency rule"), len(SOURCE_TEXT)),
    }
    for node_id, (start, end) in spans.items():
        span = builder.add_span(
            "doc-citations",
            start,
            end,
            transformation_step_id="compiler.citation_span",
            metadata={"node_id": node_id},
        )
        builder.add_node(
            node_id,
            node_kind="citation_fixture",
            span_ids=(span.span_id,),
            emitted_fact=node_id,
            transformation_step_id="compiler.emit_citation_fixture",
        )
    return builder.to_source_map()


def test_canonicalizes_internal_external_ranges_and_subsections_with_lineage() -> None:
    source_map = _source_map()
    builder = LegalIRCitationGraphBuilder(
        citation_graph_id="citations-core",
        source_map=source_map,
    )
    builder.add_authority(
        "ORS",
        name="Oregon Revised Statutes",
        jurisdiction="OR",
        authority_type="statute",
        version="2025",
    )
    builder.add_target(
        "ORS 192.001",
        target_id="target:ors-192-001",
        authority_id="ORS",
        document_id="doc-citations",
        version="2025",
        source_node_ids=("target:ors-192-001",),
    )
    builder.add_target(
        "ORS 192.003",
        target_id="target:ors-192-003",
        authority_id="ORS",
        document_id="doc-citations",
        version="2025",
        source_node_ids=("target:ors-192-003",),
    )
    builder.add_target(
        "ORS 192.005",
        target_id="target:ors-192-005",
        authority_id="ORS",
        document_id="doc-citations",
        version="2025",
        source_node_ids=("target:ors-192-005",),
    )
    builder.add_reference(
        "§ 192.001(1)(a)",
        reference_id="ref:internal-subsection",
        citation_kind=LegalIRCitationKind.INTERNAL,
        document_id="doc-citations",
        authority_id="ORS",
        version="2025",
        source_node_ids=("ref:internal-subsection",),
    )
    builder.add_reference(
        "ORS 192.003 through 192.005",
        reference_id="ref:range",
        citation_kind=LegalIRCitationKind.RANGE,
        document_id="doc-citations",
        authority_id="ORS",
        version="2025",
        source_node_ids=("ref:range",),
    )

    graph = builder.to_citation_graph()
    subsection = graph.resolution_by_reference_id["ref:internal-subsection"]
    ranged = graph.resolution_by_reference_id["ref:range"]

    assert graph.schema_version == LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION
    assert LegalIRCitationGraph.from_dict(graph.to_dict()).to_dict() == graph.to_dict()
    assert normalize_legal_citation("42 U.S.C. § 1983(a)") == "42 U.S.C. 1983(a)"
    assert normalize_legal_citation("Former ORS 192.999") == "ORS 192.999"
    assert normalize_legal_citation("ORS 192.003-192.005") == "ORS 192.003-ORS 192.005"
    assert parse_legal_citation("ORS 192.001(1)(a)")["subsections"] == ("1", "a")
    assert subsection.status is LegalIRCitationResolutionStatus.RESOLVED
    assert subsection.canonical_citation == "ORS 192.001(1)(a)"
    assert subsection.target_ids == ("target:ors-192-001",)
    assert 0.8 <= subsection.confidence < 1.0
    assert subsection.source_traces
    assert ranged.status is LegalIRCitationResolutionStatus.RESOLVED
    assert ranged.target_ids == ("target:ors-192-003", "target:ors-192-005")
    assert ranged.canonical_citation == "ORS 192.003-ORS 192.005"

    validation = validate_legal_ir_citation_graph(graph, source_map=source_map)
    assert validation.valid, validation.to_dict()


def test_external_and_incorporated_references_resolve_against_external_graphs() -> None:
    source_map = _source_map()
    external_builder = LegalIRCitationGraphBuilder(citation_graph_id="citations-federal")
    external_builder.add_authority(
        "U.S.C.",
        name="United States Code",
        jurisdiction="US",
        authority_type="statute",
        version="2024",
    )
    external_builder.add_target(
        "42 USC 1983(a)",
        target_id="target:usc-42-1983-a",
        authority_id="U.S.C.",
        document_id="doc-usc-1983",
        version="2024",
    )
    external_graph = external_builder.to_citation_graph()

    builder = LegalIRCitationGraphBuilder(
        citation_graph_id="citations-incorporated",
        source_map=source_map,
    )
    builder.add_reference(
        "incorporated by reference: 42 U.S.C. § 1983(a)",
        reference_id="ref:incorporated",
        citation_kind=LegalIRCitationKind.INCORPORATED,
        authority_id="U.S.C.",
        version="2024",
        source_node_ids=("ref:range",),
    )

    graph = builder.to_citation_graph(external_citation_graphs=(external_graph,))
    resolution = graph.resolution_by_reference_id["ref:incorporated"]

    assert resolution.resolved
    assert resolution.citation_kind is LegalIRCitationKind.INCORPORATED
    assert resolution.canonical_citation == "42 U.S.C. 1983(a)"
    assert resolution.target_ids == ("target:usc-42-1983-a",)
    assert legal_ir_citations_allowed_for_use(graph, artifact_use=LegalIRCitationUse.PROOF_TARGET)


def test_repealed_and_unresolved_references_are_diagnostics_and_fail_closed() -> None:
    source_map = _source_map()
    builder = LegalIRCitationGraphBuilder(
        citation_graph_id="citations-closed",
        source_map=source_map,
    )
    builder.add_authority("ORS", name="Oregon Revised Statutes", version="2025")
    builder.add_target(
        "Former ORS 192.999",
        target_id="target:ors-192-999",
        authority_id="ORS",
        document_id="doc-citations",
        version="2025",
        repealed=True,
        source_node_ids=("target:ors-192-999",),
    )
    builder.add_reference(
        "ORS 192.999",
        reference_id="ref:repealed",
        citation_kind=LegalIRCitationKind.REPEALED,
        authority_id="ORS",
        version="2025",
        source_node_ids=("ref:repealed",),
    )
    builder.add_reference(
        "ORS 999.999",
        reference_id="ref:missing",
        authority_id="ORS",
        version="2025",
        source_node_ids=("ref:missing",),
    )

    graph = builder.to_citation_graph()
    repealed = graph.resolution_by_reference_id["ref:repealed"]
    missing = resolve_legal_ir_citation(graph, "ref:missing", source_map=source_map)

    assert repealed.status is LegalIRCitationResolutionStatus.REPEALED
    assert LegalIRCitationDiagnosticType.REPEALED_CITATION in repealed.diagnostic_types
    assert missing.status is LegalIRCitationResolutionStatus.UNRESOLVED
    assert LegalIRCitationDiagnosticType.UNRESOLVED_CITATION in missing.diagnostic_types
    assert graph.repealed_references[0].reference_id == "ref:repealed"
    assert graph.unresolved_references[0].reference_id == "ref:missing"
    assert not legal_ir_citations_allowed_for_use(graph, artifact_use=LegalIRCitationUse.LEARNED_TARGET)
    with pytest.raises(ValueError):
        assert_legal_ir_citations_resolved(graph, artifact_use=LegalIRCitationUse.PROOF_TARGET)


def test_ambiguous_citations_are_not_silent_best_guesses() -> None:
    builder = LegalIRCitationGraphBuilder(citation_graph_id="citations-ambiguous")
    builder.add_authority("ORS", name="Oregon Revised Statutes", version="2025")
    for target_id, document_id in (
        ("target:ors-192-001-a", "doc-a"),
        ("target:ors-192-001-b", "doc-b"),
    ):
        builder.add_target(
            "ORS 192.001",
            target_id=target_id,
            authority_id="ORS",
            document_id=document_id,
            version="2025",
            source_node_ids=(target_id,),
        )
    builder.add_reference(
        "ORS 192.001",
        reference_id="ref:ambiguous",
        authority_id="ORS",
        version="2025",
        source_node_ids=("ref:ambiguous",),
    )

    graph = builder.to_citation_graph()
    resolution = graph.resolution_by_reference_id["ref:ambiguous"]

    assert resolution.status is LegalIRCitationResolutionStatus.AMBIGUOUS
    assert set(resolution.target_ids) == {"target:ors-192-001-a", "target:ors-192-001-b"}
    assert LegalIRCitationDiagnosticType.AMBIGUOUS_CITATION in resolution.diagnostic_types


def test_build_citation_graph_extracts_common_legal_ir_shapes() -> None:
    sample = {
        "modal_ir": {
            "document_id": "doc-built-citations",
            "citation": "ORS 192.001",
            "authority": {
                "authority_id": "ORS",
                "name": "Oregon Revised Statutes",
                "jurisdiction": "OR",
                "version": "2025",
            },
            "version": "2025",
            "citation_targets": [
                {
                    "citation": "ORS 192.001",
                    "target_id": "target:built-192-001",
                    "source_node_ids": ["formula-built"],
                }
            ],
            "references": [
                {
                    "reference_id": "ref:built",
                    "citation": "§ 192.001",
                    "authority_id": "ORS",
                    "source_node_ids": ["formula-built"],
                }
            ],
            "formulas": [
                {
                    "formula_id": "formula-built",
                    "cross_references": ["ORS 192.001"],
                }
            ],
        }
    }

    graph = build_legal_ir_citation_graph(sample)

    assert graph.resolution_by_reference_id["ref:built"].resolved
    assert graph.resolution_by_reference_id["ref:built"].target_ids == (
        "target:built-192-001",
    )
    assert any(
        reference.citation_kind is LegalIRCitationKind.INTERNAL
        for reference in graph.references
        if reference.reference_id.startswith("formula-built")
    )
