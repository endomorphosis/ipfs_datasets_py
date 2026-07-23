"""Tests for scoped LegalIR symbol tables and definition resolution."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION,
    LegalIRResolutionStatus,
    LegalIRScopeKind,
    LegalIRSourceMap,
    LegalIRSourceMapBuilder,
    LegalIRSymbolDiagnosticType,
    LegalIRSymbolKind,
    LegalIRSymbolTable,
    LegalIRSymbolTableBuilder,
    assert_legal_ir_symbols_resolved,
    build_legal_ir_symbol_table,
    normalize_legal_symbol_name,
    resolve_legal_ir_symbol,
    validate_legal_ir_symbol_table,
)


SOURCE_TEXT = (
    "Agency means the public records agency. "
    "The agency shall disclose records unless emergency conditions exist within 30 days. "
    "Authority means the public records court."
)


def _source_map() -> LegalIRSourceMap:
    builder = LegalIRSourceMapBuilder(source_map_id="map-symbols")
    builder.add_source_document("doc-a", SOURCE_TEXT, citation="ORS 192.001")
    spans = {
        "actor-def": (0, SOURCE_TEXT.index(".")),
        "formula-1": (
            SOURCE_TEXT.index("The agency"),
            SOURCE_TEXT.index("Authority means") - 1,
        ),
        "authority-def": (SOURCE_TEXT.index("Authority means"), len(SOURCE_TEXT)),
    }
    for node_id, (start, end) in spans.items():
        span = builder.add_span(
            "doc-a",
            start,
            end,
            transformation_step_id="compiler.symbol_span",
            metadata={"node_id": node_id},
        )
        builder.add_node(
            node_id,
            node_kind="symbol_fixture",
            span_ids=(span.span_id,),
            emitted_fact=node_id,
            transformation_step_id="compiler.emit_symbol_fixture",
        )
    return builder.to_source_map()


def test_resolves_defined_terms_actors_authorities_exceptions_and_conditions_with_provenance() -> None:
    source_map = _source_map()
    builder = LegalIRSymbolTableBuilder(
        symbol_table_id="symbols-core",
        source_map=source_map,
    )
    doc = builder.add_document_scope("doc-a", citation="ORS 192.001")
    formula = builder.add_scope(
        "formula:f1",
        LegalIRScopeKind.FORMULA,
        parent_scope_id=doc.scope_id,
        document_id="doc-a",
        source_node_ids=("formula-1",),
    )
    builder.add_definition(
        "Agency",
        LegalIRSymbolKind.ACTOR,
        symbol_id="actor:agency",
        scope_id=doc.scope_id,
        document_id="doc-a",
        source_node_ids=("actor-def",),
        aliases=("public records agency",),
    )
    builder.add_definition(
        "public records court",
        LegalIRSymbolKind.AUTHORITY,
        symbol_id="authority:court",
        scope_id=doc.scope_id,
        document_id="doc-a",
        source_node_ids=("authority-def",),
    )
    builder.add_definition(
        "emergency conditions exist",
        LegalIRSymbolKind.EXCEPTION,
        symbol_id="exception:emergency",
        scope_id=formula.scope_id,
        document_id="doc-a",
        source_node_ids=("formula-1",),
    )
    builder.add_definition(
        "within 30 days",
        LegalIRSymbolKind.CONDITION,
        symbol_id="condition:30-days",
        scope_id=formula.scope_id,
        document_id="doc-a",
        source_node_ids=("formula-1",),
    )

    for reference_id, name, kind in (
        ("ref:actor", "agency", LegalIRSymbolKind.ACTOR),
        ("ref:authority", "public records court", LegalIRSymbolKind.AUTHORITY),
        ("ref:exception", "emergency conditions exist", LegalIRSymbolKind.EXCEPTION),
        ("ref:condition", "within 30 days", LegalIRSymbolKind.CONDITION),
    ):
        builder.add_reference(
            name,
            kind,
            reference_id=reference_id,
            scope_id=formula.scope_id,
            document_id="doc-a",
            source_node_ids=("formula-1",),
        )

    table = builder.to_symbol_table()
    assert table.schema_version == LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION
    assert LegalIRSymbolTable.from_dict(table.to_dict()).to_dict() == table.to_dict()
    assert table.resolved
    assert {resolution.reference_id for resolution in table.resolutions} == {
        "ref:actor",
        "ref:authority",
        "ref:exception",
        "ref:condition",
    }
    assert table.resolution_by_reference_id["ref:actor"].source_traces
    assert table.resolution_by_reference_id["ref:actor"].source_traces[0].source_spans

    validation = validate_legal_ir_symbol_table(table, source_map=source_map)
    assert validation.valid, validation.to_dict()
    assert validation.resolved_count == 4


def test_scoped_references_shadow_parent_definitions_without_ambiguity() -> None:
    builder = LegalIRSymbolTableBuilder(symbol_table_id="symbols-shadow")
    doc = builder.add_document_scope("doc-shadow")
    formula = builder.add_scope(
        "formula:shadow",
        LegalIRScopeKind.FORMULA,
        parent_scope_id=doc.scope_id,
        document_id="doc-shadow",
    )
    builder.add_definition(
        "record",
        LegalIRSymbolKind.DEFINED_TERM,
        symbol_id="term:record:general",
        scope_id=doc.scope_id,
        document_id="doc-shadow",
    )
    builder.add_definition(
        "record",
        LegalIRSymbolKind.DEFINED_TERM,
        symbol_id="term:record:local",
        scope_id=formula.scope_id,
        document_id="doc-shadow",
    )
    builder.add_reference(
        "record",
        LegalIRSymbolKind.DEFINED_TERM,
        reference_id="ref:local-record",
        scope_id=formula.scope_id,
        document_id="doc-shadow",
    )
    builder.add_reference(
        "record",
        LegalIRSymbolKind.DEFINED_TERM,
        reference_id="ref:doc-record",
        scope_id=doc.scope_id,
        document_id="doc-shadow",
    )

    table = builder.to_symbol_table()

    assert table.resolution_by_reference_id["ref:local-record"].status is LegalIRResolutionStatus.RESOLVED
    assert table.resolution_by_reference_id["ref:local-record"].symbol_ids == (
        "term:record:local",
    )
    assert table.resolution_by_reference_id["ref:doc-record"].symbol_ids == (
        "term:record:general",
    )
    assert not table.ambiguous_references


def test_ambiguous_symbols_are_typed_diagnostics_not_best_guesses() -> None:
    builder = LegalIRSymbolTableBuilder(symbol_table_id="symbols-ambiguous")
    doc = builder.add_document_scope("doc-ambiguous")
    builder.add_definition(
        "permit",
        LegalIRSymbolKind.DEFINED_TERM,
        symbol_id="term:permit:a",
        scope_id=doc.scope_id,
        document_id="doc-ambiguous",
    )
    builder.add_definition(
        "permit",
        LegalIRSymbolKind.DEFINED_TERM,
        symbol_id="term:permit:b",
        scope_id=doc.scope_id,
        document_id="doc-ambiguous",
    )
    builder.add_reference(
        "permit",
        LegalIRSymbolKind.DEFINED_TERM,
        reference_id="ref:permit",
        scope_id=doc.scope_id,
        document_id="doc-ambiguous",
    )

    table = builder.to_symbol_table()
    resolution = table.resolution_by_reference_id["ref:permit"]

    assert resolution.status is LegalIRResolutionStatus.AMBIGUOUS
    assert resolution.symbol_ids == ("term:permit:a", "term:permit:b")
    assert LegalIRSymbolDiagnosticType.AMBIGUOUS_SYMBOL in resolution.diagnostic_types
    assert table.ambiguous_references[0].reference_id == "ref:permit"


def test_unresolved_symbols_are_typed_diagnostics_and_assertion_fails_closed() -> None:
    source_map = _source_map()
    builder = LegalIRSymbolTableBuilder(
        symbol_table_id="symbols-unresolved",
        source_map=source_map,
    )
    doc = builder.add_document_scope("doc-a")
    builder.add_reference(
        "missing term",
        LegalIRSymbolKind.DEFINED_TERM,
        reference_id="ref:missing",
        scope_id=doc.scope_id,
        document_id="doc-a",
        source_node_ids=("formula-1",),
    )

    table = builder.to_symbol_table()
    resolution = resolve_legal_ir_symbol(table, "ref:missing", source_map=source_map)

    assert resolution.status is LegalIRResolutionStatus.UNRESOLVED
    assert LegalIRSymbolDiagnosticType.UNRESOLVED_SYMBOL in resolution.diagnostic_types
    assert resolution.diagnostics[0].source_span_ids
    assert table.unresolved_references[0].reference_id == "ref:missing"
    with pytest.raises(ValueError):
        assert_legal_ir_symbols_resolved(table)


def test_aliases_resolve_to_targets_and_alias_cycles_are_diagnostics() -> None:
    builder = LegalIRSymbolTableBuilder(symbol_table_id="symbols-alias")
    doc = builder.add_document_scope("doc-alias")
    builder.add_definition(
        "public records",
        LegalIRSymbolKind.DEFINED_TERM,
        symbol_id="term:public-records",
        scope_id=doc.scope_id,
        document_id="doc-alias",
    )
    builder.add_alias(
        "records",
        target_symbol_id="term:public-records",
        symbol_kind=LegalIRSymbolKind.DEFINED_TERM,
        scope_id=doc.scope_id,
        document_id="doc-alias",
        alias_id="alias:records",
    )
    builder.add_alias(
        "cycle a",
        target_name="cycle b",
        symbol_kind=LegalIRSymbolKind.DEFINED_TERM,
        scope_id=doc.scope_id,
        document_id="doc-alias",
        alias_id="alias:cycle-a",
    )
    builder.add_alias(
        "cycle b",
        target_name="cycle a",
        symbol_kind=LegalIRSymbolKind.DEFINED_TERM,
        scope_id=doc.scope_id,
        document_id="doc-alias",
        alias_id="alias:cycle-b",
    )
    builder.add_reference(
        "records",
        LegalIRSymbolKind.DEFINED_TERM,
        reference_id="ref:records",
        scope_id=doc.scope_id,
        document_id="doc-alias",
    )
    builder.add_reference(
        "cycle a",
        LegalIRSymbolKind.DEFINED_TERM,
        reference_id="ref:cycle",
        scope_id=doc.scope_id,
        document_id="doc-alias",
    )

    table = builder.to_symbol_table()

    resolved = table.resolution_by_reference_id["ref:records"]
    assert resolved.resolved
    assert resolved.symbol_ids == ("term:public-records",)
    assert resolved.alias_ids == ("alias:records",)

    cycle = table.resolution_by_reference_id["ref:cycle"]
    assert cycle.status is LegalIRResolutionStatus.UNRESOLVED
    assert LegalIRSymbolDiagnosticType.ALIAS_CYCLE in cycle.diagnostic_types
    assert LegalIRSymbolDiagnosticType.UNRESOLVED_SYMBOL in cycle.diagnostic_types


def test_explicit_cross_document_reference_resolves_only_to_target_document() -> None:
    external_builder = LegalIRSymbolTableBuilder(symbol_table_id="symbols-doc-b")
    doc_b = external_builder.add_document_scope("doc-b")
    external_builder.add_definition(
        "records officer",
        LegalIRSymbolKind.AUTHORITY,
        symbol_id="authority:records-officer",
        scope_id=doc_b.scope_id,
        document_id="doc-b",
    )
    external_table = external_builder.to_symbol_table()

    builder = LegalIRSymbolTableBuilder(symbol_table_id="symbols-doc-a")
    doc_a = builder.add_document_scope("doc-a")
    builder.add_definition(
        "records officer",
        LegalIRSymbolKind.AUTHORITY,
        symbol_id="authority:local-officer",
        scope_id=doc_a.scope_id,
        document_id="doc-a",
    )
    builder.add_reference(
        "records officer",
        LegalIRSymbolKind.AUTHORITY,
        reference_id="ref:doc-b-officer",
        scope_id=doc_a.scope_id,
        document_id="doc-a",
        explicit_target_document_id="doc-b",
    )

    table = builder.to_symbol_table(external_symbol_tables=(external_table,))

    assert table.resolution_by_reference_id["ref:doc-b-officer"].resolved
    assert table.resolution_by_reference_id["ref:doc-b-officer"].symbol_ids == (
        "authority:records-officer",
    )
    assert validate_legal_ir_symbol_table(
        table,
        external_symbol_tables=(external_table,),
    ).valid


def test_build_symbol_table_extracts_common_legal_ir_shapes() -> None:
    sample = {
        "modal_ir": {
            "document_id": "doc-built",
            "citation": "ORS 192.002",
            "defined_terms": [
                {
                    "term": "Public body",
                    "symbol_id": "term:public-body",
                    "aliases": ["agency"],
                    "source_node_ids": ["formula-built"],
                }
            ],
            "actors": [{"name": "requester", "symbol_id": "actor:requester"}],
            "formulas": [
                {
                    "formula_id": "formula-built",
                    "actor": "agency",
                    "conditions": ["within 5 days"],
                    "exceptions": ["sealed record exception"],
                }
            ],
            "references": [
                {
                    "reference_id": "ref:public-body",
                    "name": "agency",
                    "kind": "defined_term",
                    "source_node_ids": ["formula-built"],
                }
            ],
        }
    }

    table = build_legal_ir_symbol_table(sample)

    assert normalize_legal_symbol_name(" Public-Body ") == "public body"
    assert table.resolution_by_reference_id["ref:public-body"].symbol_ids == (
        "term:public-body",
    )
    assert {
        definition.symbol_kind for definition in table.definitions
    } >= {
        LegalIRSymbolKind.DEFINED_TERM,
        LegalIRSymbolKind.ACTOR,
        LegalIRSymbolKind.CONDITION,
        LegalIRSymbolKind.EXCEPTION,
    }
