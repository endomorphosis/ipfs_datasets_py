"""Candidate-only corpus envelopes for explicit V2 unary definitions.

The complete sampler report and original HTML remain separately pinned inputs.
Native owners are imported only during explicit adaptation or validation. This
module neither chooses a legal meaning nor supplies review or a native build.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

from .corpus_contracts import (
    CorpusContractError,
    load_record_bytes,
    seal_record,
    validate_record,
)
from .corpus_graph import build_edge, build_graph_snapshot, build_node

SCHEMA = "legal-corpus-v2-definition-candidate/v1"
REQUEST_SCHEMA = "legal-corpus-v2-definition-request-custody/v1"
REPORT_SCHEMA = "legal-corpus-v2-definition-report-custody/v1"
SCOPE_SCHEMA = "legal-corpus-v2-definition-scope/v1"
SYMBOL_SCHEMA = "legal-corpus-v2-definition-symbols/v1"
DEFINITION_SCHEMA = "legal-corpus-v2-definition-assertion/v1"
AST_SCHEMA = "legal-corpus-v2-definition-native-ast/v1"
TERM_SCHEMA = "legal-corpus-v2-defined-category/v1"
INPUT_SCHEMA = "legal-corpus-v2-definition-input-binding/v1"
ISSUE_SCHEMA = "legal-corpus-v2-definition-issue/v1"
FALSE_FLAGS = dict.fromkeys(
    (
        "context_closure_verified",
        "source_semantics_verified",
        "source_authenticity_verified",
        "applicability_verified",
        "independently_reviewed",
        "admitted",
        "formalized",
        "proof_authority",
        "backend_executed",
        "lean_compilation_verified",
        "training_qualified",
        "training_gold_qualified",
        "learned_translation",
        "external_definition_resolution_verified",
    ),
    False,
)
FIELDS = {
    "profile",
    "family",
    "request_record",
    "report_record",
    "source_version",
    "source_occurrences",
    "source_bindings",
    "context_declarations",
    "scope_record",
    "symbol_record",
    "definition_record",
    "ast_record",
    "term_record",
    "input_binding",
    "issues",
    "graph",
    "view",
    "declared_native_profile_encoded",
    *FALSE_FLAGS,
}


def _seal(schema, **values):
    return seal_record({"schema": schema, **values})


def producer_pins():
    """Identify the adapter and graph/envelope owners at explicit execution."""
    from ipfs_datasets_py.utils import cid_utils

    from . import corpus_contracts, corpus_graph

    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__).resolve(),
            Path(corpus_contracts.__file__).resolve(),
            Path(corpus_graph.__file__).resolve(),
            Path(cid_utils.__file__).resolve(),
        )
    }


_IMPORTED_OWNER_PINS = producer_pins()


def _graph(version, occurrences, interpretation, scope, definition, ast, term, issues):
    nodes, edges = [], []
    scope_cid = scope["record_cid"]
    interpretation_cid = interpretation["record_cid"]

    def node(kind, record, origins=(), stable_id=None):
        physical = kind in {"source_version", "occurrence"}
        result = build_node(
            node_type=kind,
            stable_id=record["record_cid"] if stable_id is None else stable_id,
            content_cid=record["record_cid"],
            scope_cid=None if physical else scope_cid,
            source_occurrence_cids=list(origins),
            interpretation_cids=[] if physical else [interpretation_cid],
        )
        nodes.append(result)
        return result["record_cid"]

    def edge(src, dst, relation, evidence=None):
        edges.append(
            build_edge(
                src_cid=src,
                dst_cid=dst,
                relation=relation,
                evidence_cids=[interpretation_cid] if evidence is None else evidence,
            )
        )

    version_node = node("source_version", version)
    occurrence_nodes = {
        row["record_cid"]: node("occurrence", row) for row in occurrences
    }
    all_origins = list(occurrence_nodes)
    interpretation_node = node("interpretation", interpretation, all_origins)
    scope_node = node(
        "scope", scope, scope["source_occurrence_cids"], scope["scope_key"]
    )
    definition_node = node(
        "definition_assertion", definition, definition["source_occurrence_cids"]
    )
    term_node = node("term_sense", term, term["source_occurrence_cids"], term["symbol"])
    ast_node = node("expression", ast, all_origins)
    edge(
        definition_node,
        term_node,
        "DEFINES",
        [definition["record_cid"], term["record_cid"]],
    )
    for item in (definition_node, term_node, ast_node):
        edge(item, scope_node, "APPLIES_WITHIN")
        edge(item, interpretation_node, "DERIVED_FROM")
    edge(scope_node, interpretation_node, "DERIVED_FROM")
    edge(ast_node, definition_node, "CONTAINS")
    for cid, occurrence_node in occurrence_nodes.items():
        edge(occurrence_node, version_node, "HAS_SOURCE", [cid, version["record_cid"]])
        edge(interpretation_node, occurrence_node, "HAS_SOURCE")
    for cid in scope["source_occurrence_cids"]:
        edge(scope_node, occurrence_nodes[cid], "HAS_SOURCE")
    for issue in issues:
        issue_node = node("issue", issue, all_origins)
        edge(issue_node, interpretation_node, "DERIVED_FROM", [issue["record_cid"]])
    return build_graph_snapshot(nodes, edges)


def adapt_definition_only_bytes_v2(
    report_raw,
    *,
    expected_report_sha256,
    request_raw,
    expected_request_sha256,
    sampling_report,
    expected_sampling_report_sha256,
    raw_html,
    descriptor,
    expected_descriptor_sha256,
    expected_raw_sha256,
    expected_raw_bytes,
    view_limits=None,
    sampling_limits=None,
    limits=None,
):
    """Regenerate an explicit V2 definition and retain candidate-only records.

    Request/report hashes bind original JSON bytes; the sampler commitment binds
    its full canonical report, not its internal digest or a file hash. Original
    large inputs must remain independently available for later replay/export.
    Per-record one-MiB bounds apply to the complete returned companion as well.
    """
    request = load_record_bytes(request_raw, expected_sha256=expected_request_sha256)
    report = load_record_bytes(report_raw, expected_sha256=expected_report_sha256)
    adapter_pins = producer_pins()
    if adapter_pins != _IMPORTED_OWNER_PINS:
        raise CorpusContractError("V2 definition adapter owners changed since import")
    from . import legal_source_definition_bridge_v2 as owner

    try:
        owner.validate_definition_v2(
            report,
            request,
            sampling_report=sampling_report,
            expected_sampling_report_sha256=expected_sampling_report_sha256,
            raw_html=raw_html,
            descriptor=descriptor,
            expected_descriptor_sha256=expected_descriptor_sha256,
            expected_raw_sha256=expected_raw_sha256,
            expected_raw_bytes=expected_raw_bytes,
            view_limits=view_limits,
            sampling_limits=sampling_limits,
            limits=limits,
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        UnicodeError,
        RecursionError,
    ) as error:
        raise CorpusContractError(
            "V2 definition report failed authoritative regeneration"
        ) from error

    request_record = _seal(
        REQUEST_SCHEMA,
        request_json=request_raw.decode("utf-8"),
        request_sha256=expected_request_sha256,
        request_content_cid=cid_for_dag_json(request),
    )
    # The report body is already separately supplied and replayed. Retaining its
    # commitment here avoids copying complete evidence into several sealed rows.
    report_record = _seal(
        REPORT_SCHEMA,
        report_sha256=expected_report_sha256,
        producer_report_sha256=report["report_sha256"],
        report_content_cid=cid_for_dag_json(report),
        original_schema=report["schema"],
        profile=report["profile"],
        family=report["family"],
        payload_location="independently_pinned_caller_retained_report_bytes",
        interpretation_status="unreviewed_caller_declaration",
    )
    interpretation_cid = report_record["record_cid"]
    version, occurrences = report["source_version"], report["source_occurrences"]
    bindings = report["source_bindings"]
    by_role = {row["role"]: row["source_occurrence_cid"] for row in bindings}
    all_origins = [row["record_cid"] for row in occurrences]
    scope_origins = list(
        dict.fromkeys([by_role["scope_block"], by_role["scope_literal"]])
    )
    scope = _seal(
        SCOPE_SCHEMA,
        scope_key=report["scope_key"],
        profile=report["profile"],
        source_version_cid=version["record_cid"],
        normalized_view_id=report["normalized_view_id"],
        source_occurrence_cids=scope_origins,
        scope_unit_ref=report["scope_unit_ref"],
        declared_applicability=report["applicability"],
        interpretation_cid=interpretation_cid,
        context_closure_verified=False,
        applicability_verified=False,
    )
    scope_cid = scope["record_cid"]
    symbols = _seal(
        SYMBOL_SCHEMA,
        symbols=report["symbols"],
        symbol_occurrences=report["symbol_occurrences"],
        scope_cid=scope_cid,
        interpretation_cid=interpretation_cid,
    )
    definition = _seal(
        DEFINITION_SCHEMA,
        profile=report["profile"],
        declaration=report["declaration"],
        native_ast=report["native_ast"],
        scope_cid=scope_cid,
        source_occurrence_cids=all_origins,
        interpretation_cid=interpretation_cid,
        declared_native_profile_encoded=True,
        definition_lexical_coverage_complete=False,
        source_semantics_verified=False,
    )
    ast = _seal(
        AST_SCHEMA,
        profile=report["profile"],
        family=report["family"],
        native_ast=report["native_ast"],
        lean_body=report["lean_body"],
        source_occurrence_cids=all_origins,
        scope_cid=scope_cid,
        interpretation_cid=interpretation_cid,
        lean_compilation_verified=False,
    )
    term = _seal(
        TERM_SCHEMA,
        kind="declared_unary_category",
        symbol=report["native_ast"]["formula"]["left"]["name"],
        source_literal=report["declaration"]["head"]["text"],
        arity=1,
        carrier="Entity",
        scope_cid=scope_cid,
        interpretation_cid=interpretation_cid,
        source_occurrence_cids=[by_role["definition_head"]],
        resolved_entity_identity=False,
    )
    input_binding = _seal(
        INPUT_SCHEMA,
        request_sha256=expected_request_sha256,
        report_sha256=expected_report_sha256,
        sampling_report_full_canonical_sha256=expected_sampling_report_sha256,
        raw_sha256=expected_raw_sha256,
        raw_bytes=expected_raw_bytes,
        descriptor_full_canonical_sha256=expected_descriptor_sha256,
        source_input_pins=report["source_input_pins"],
        producer_pins=report["producer_pins"],
        adapter_producer_pins=adapter_pins,
        source_version_cid=version["record_cid"],
        source_occurrence_cids=all_origins,
        context_cids=[row["record_cid"] for row in report["context_declarations"]],
        contributor_unit_refs=report["contributor_unit_refs"],
        source_context_frontier=report["source_context_frontier"],
        request_record_cid=request_record["record_cid"],
        report_record_cid=interpretation_cid,
        scope_record_cid=scope_cid,
        definition_record_cid=definition["record_cid"],
        symbol_record_cid=symbols["record_cid"],
        ast_record_cid=ast["record_cid"],
        term_record_cid=term["record_cid"],
    )
    issues = [
        _seal(
            ISSUE_SCHEMA,
            code=code,
            reason=reason,
            interpretation_cid=interpretation_cid,
            source_occurrence_cids=all_origins,
        )
        for code, reason in (
            (
                "unreviewed_caller_interpretation",
                "Encoding does not establish source meaning or legal applicability.",
            ),
            (
                "context_and_coverage_unassessed",
                "All selected physical contexts remain open; whole-source semantic coverage is unassessed.",
            ),
            (
                "actual_use_not_supplied",
                "No norm or definition-use assertion is supplied by this definition-only profile.",
            ),
        )
    ]
    graph = _graph(
        version, occurrences, report_record, scope, definition, ast, term, issues
    )
    if producer_pins() != adapter_pins:
        raise CorpusContractError(
            "V2 definition adapter owners changed during preparation"
        )
    return _seal(
        SCHEMA,
        profile=report["profile"],
        family=report["family"],
        view="candidate",
        request_record=request_record,
        report_record=report_record,
        source_version=version,
        source_occurrences=occurrences,
        source_bindings=bindings,
        context_declarations=report["context_declarations"],
        scope_record=scope,
        symbol_record=symbols,
        definition_record=definition,
        ast_record=ast,
        term_record=term,
        input_binding=input_binding,
        issues=issues,
        graph=graph,
        declared_native_profile_encoded=True,
        **FALSE_FLAGS,
    )


def validate_definition_only_candidate_v2(record, report_raw, **validation_inputs):
    """Replay original independent inputs; resealing cannot authorize changes."""
    checked = validate_record(record, schema=SCHEMA, fields=FIELDS)
    expected = adapt_definition_only_bytes_v2(report_raw, **validation_inputs)
    if checked != expected:
        raise CorpusContractError(
            "V2 definition candidate differs from independent authoritative regeneration"
        )
    return checked


def export_definition_only_candidate_v2(record, output_directory, **validation_inputs):
    """Export graph envelopes after replay; retain the complete companion too."""
    checked = validate_definition_only_candidate_v2(record, **validation_inputs)
    from .corpus_graph_exchange import write_graph_bundle

    return write_graph_bundle(checked["graph"], output_directory)


__all__ = [
    "SCHEMA",
    "FALSE_FLAGS",
    "adapt_definition_only_bytes_v2",
    "validate_definition_only_candidate_v2",
    "export_definition_only_candidate_v2",
    "producer_pins",
]
