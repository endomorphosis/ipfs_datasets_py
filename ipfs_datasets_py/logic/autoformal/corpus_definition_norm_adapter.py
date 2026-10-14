"""Candidate graph for an existing explicit definition/unary-norm profile.

This adapter transports a caller's bounded interpretation after authoritative
regeneration by the unchanged definition/norm owner. It does not extract legal
meaning, authenticate an official source, close context, or execute a backend.
Importing this module does not import the native parser/compiler owner.
"""
from __future__ import annotations

import base64
import hashlib

from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

from .corpus_contracts import (
    CorpusContractError,
    load_record_bytes,
    require_int,
    require_sha256,
    require_text,
    seal_record,
    validate_record,
)
from .corpus_graph import build_edge, build_graph_snapshot, build_node
from .corpus_source import MAX_TEXT_BYTES, build_source_occurrence, build_source_version

SCHEMA = "legal-corpus-definition-norm-candidate/v1"
REQUEST_SCHEMA = "legal-corpus-definition-norm-request-custody/v1"
REPORT_SCHEMA = "legal-corpus-definition-norm-report-custody/v1"
SCOPE_SCHEMA = "legal-corpus-definition-norm-scope/v1"
SYMBOL_SCHEMA = "legal-corpus-definition-norm-symbols/v1"
DEFINITION_SCHEMA = "legal-corpus-definition-native-assertion/v1"
NORM_SCHEMA = "legal-corpus-defined-category-native-norm/v1"
AST_SCHEMA = "legal-corpus-definition-norm-native-ast/v1"
TERM_SCHEMA = "legal-corpus-defined-unary-category/v1"
INPUT_SCHEMA = "legal-corpus-definition-norm-input-binding/v1"
ISSUE_SCHEMA = "legal-corpus-definition-norm-issue/v1"
MAX_RAW_HTML_BYTES = 8_000_000
MAX_SOURCE_OCCURRENCES = 256
MAX_SOURCE_BINDINGS = 512
FALSE_FLAGS = dict.fromkeys((
    "context_closure_verified", "source_semantics_verified", "source_authenticity_verified",
    "independently_reviewed", "admitted", "formalized", "proof_authority", "backend_executed",
    "lean_compilation_verified", "learned_translation",
), False)
FIELDS = {
    "profile", "family", "request_record", "report_record", "source_version",
    "source_occurrences", "source_bindings", "scope_record", "symbol_record",
    "definition_record", "norm_record", "ast_record", "term_record", "input_binding",
    "issues", "graph", "view", "declared_native_profile_encoded", *FALSE_FLAGS,
}


def _fail(message):
    raise CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _inputs(report_raw, request_raw, raw_html, *, expected_report_sha256,
            expected_request_sha256, expected_raw_sha256, expected_extracted_sha256):
    report = load_record_bytes(report_raw, expected_sha256=expected_report_sha256)
    request = load_record_bytes(request_raw, expected_sha256=expected_request_sha256)
    require_sha256(expected_raw_sha256, "expected_raw_sha256")
    require_sha256(expected_extracted_sha256, "expected_extracted_sha256")
    if (type(raw_html) is not bytes or not 1 <= len(raw_html) <= MAX_RAW_HTML_BYTES
            or _sha(raw_html) != expected_raw_sha256):
        _fail("raw HTML differs from independently expected SHA256 or byte bounds")
    definition_request = request.get("definition_request")
    if type(definition_request) is not dict:
        _fail("existing explicit definition request required")
    encoded = definition_request.get("raw_html_base64")
    if type(encoded) is not str:
        _fail("request must retain exact base64 HTML")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise CorpusContractError("invalid request base64 HTML") from error
    if decoded != raw_html:
        _fail("request HTML differs from separately bound raw bytes")
    document = definition_request.get("document")
    if type(document) is not dict:
        _fail("existing complete extracted document required")
    text = require_text(document.get("document_text"), "complete extracted view",
                        max_bytes=MAX_TEXT_BYTES)
    if _sha(text.encode("utf-8")) != expected_extracted_sha256:
        _fail("extracted view differs from independently expected SHA256")
    # Native parsing and lowering are imported only for this explicit operation.
    # No Lake gate, model, provider, or backend is invoked by this adapter.
    from . import legal_source_definition_norm_bridge as owner

    try:
        owner.validate_definition_norm(report, request)
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        raise CorpusContractError("definition/norm report failed authoritative regeneration") from error
    return request, report, document, owner


def _sources(document, report, raw_html, expected_raw_sha256, expected_extracted_sha256, context):
    text = document["document_text"]
    require_int(document["edition"], "declared source edition", minimum=1, maximum=9999)
    version = build_source_version(
        source_id=document["legal_id"], release_id=f"govinfo-edition:{document['edition']}",
        edition=str(document["edition"]), provision_id=document["legal_id"],
        raw_bytes=raw_html, expected_raw_sha256=expected_raw_sha256,
        extracted_text=text, expected_extracted_sha256=expected_extracted_sha256,
        extraction_profile=context.SCHEMA, normalization_profile=context.NORMALIZATION_PROFILE,
        media_type="text/html",
    )
    occurrences, by_geometry, bindings, touched = [], {}, [], set()

    def add(role, span, *, source_symbol=None, symbol=None):
        if len(bindings) >= MAX_SOURCE_BINDINGS:
            _fail("source binding bound exceeded; no source origin may be discarded")
        start, end = span["char_start"], span["char_end"]
        require_int(start, "source char_start", maximum=len(text))
        require_int(end, "source char_end", maximum=len(text))
        if start >= end:
            _fail("nonempty physical source origin required")
        paragraphs = [row["paragraph_index"] for row in document["paragraphs"]
                      if row["char_start"] < end and start < row["char_end"]]
        if not paragraphs:
            _fail("source origin must touch an extracted physical paragraph")
        touched.update(paragraphs)
        geometry = (start, end)
        if geometry not in by_geometry:
            if len(occurrences) >= MAX_SOURCE_OCCURRENCES:
                _fail("physical source occurrence bound exceeded; no source origin may be discarded")
            occurrence = build_source_occurrence(
                version, expected_raw_sha256=expected_raw_sha256, extracted_text=text,
                expected_extracted_sha256=expected_extracted_sha256,
                start_char=start, end_char=end,
                start_utf8=len(text[:start].encode("utf-8")),
                end_utf8=len(text[:end].encode("utf-8")),
            )
            by_geometry[geometry] = occurrence
            occurrences.append(occurrence)
        occurrence = by_geometry[geometry]
        bindings.append({"role": role, "source_occurrence_cid": occurrence["record_cid"],
                         "paragraph_indices": paragraphs, "source_symbol": source_symbol,
                         "symbol": symbol})
        return occurrence["record_cid"]

    definition = report["definition"]
    declaration = definition["declaration"]
    norm = report["norm_declaration"]
    add("definition_block", definition["definition_block"])
    add("definition_paragraph", document["paragraphs"][declaration["paragraph_index"]])
    add("scope_literal", declaration["scope_span"])
    add("definition_cue", declaration["definition_cue"])
    old_head = definition["native_ast"]["formula"]["left"]["name"]
    rebinding = report["definition_symbol_rebinding"]
    add("definition_head", declaration["head"], source_symbol=old_head, symbol=rebinding[old_head])
    body_index = 0
    for row in definition["symbol_occurrences"]:
        if row["role"] == "body":
            add(f"definition_body/{body_index:04d}", row["span"],
                source_symbol=row["symbol"], symbol=rebinding[row["symbol"]])
            body_index += 1
    add("norm_paragraph", document["paragraphs"][norm["paragraph_index"]])
    for role, field in (
        ("norm_span", "source_span"), ("norm_quantifier", "quantifier_span"),
        ("norm_category", "category_span"), ("norm_modality", "modality_span"),
        ("norm_action", "action_span"),
    ):
        add(role, norm[field])
    # The enclosing definition block may include descendant paragraphs. Keep
    # every touched paragraph, including both sides of a cross-paragraph atom.
    for index in sorted(touched):
        add(f"physical_paragraph/{index}", document["paragraphs"][index])
    return version, occurrences, bindings


def adapt_definition_norm_bytes(report_raw, *, expected_report_sha256, request_raw,
                                 expected_request_sha256, raw_html,
                                 expected_raw_sha256, expected_extracted_sha256):
    """Encode one regenerated explicit caller interpretation as a candidate.

    Expected hashes must originate independently of incoming records. Request
    and report hashes bind exact UTF8 file bytes, not canonicalized replacements.
    The unchanged owner may reject reports produced in another absolute source
    tree because its retained producer-pin keys include those original paths.
    """
    request, report, document, owner = _inputs(
        report_raw, request_raw, raw_html, expected_report_sha256=expected_report_sha256,
        expected_request_sha256=expected_request_sha256, expected_raw_sha256=expected_raw_sha256,
        expected_extracted_sha256=expected_extracted_sha256,
    )
    source_version, occurrences, bindings = _sources(
        document, report, raw_html, expected_raw_sha256, expected_extracted_sha256,
        owner.definitions.context,
    )
    request_record = seal_record({
        "schema": REQUEST_SCHEMA, "request_json": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256, "request_content_cid": cid_for_dag_json(request),
    })
    report_record = seal_record({
        "schema": REPORT_SCHEMA, "report_json": report_raw.decode("utf-8"),
        "report_sha256": expected_report_sha256, "producer_report_sha256": report["report_sha256"],
        "report_content_cid": cid_for_dag_json(report), "original_schema": report["schema"],
        "profile": report["profile"], "family": report["family"],
        "interpretation_status": "unreviewed_caller_declaration",
    })
    interpretation_cid = report_record["record_cid"]
    by_role = {row["role"]: row["source_occurrence_cid"] for row in bindings}

    def origin_refs(prefix):
        return list(dict.fromkeys(row["source_occurrence_cid"] for row in bindings
                                 if row["role"].startswith(prefix)))

    def_refs = list(dict.fromkeys([*origin_refs("definition_"), by_role["scope_literal"]]))
    norm_refs = origin_refs("norm_")
    all_refs = [row["record_cid"] for row in occurrences]
    scope_record = seal_record({
        "schema": SCOPE_SCHEMA, "scope_key": report["scope_key"], "profile": report["profile"],
        **{key: document[key] for key in ("document_id", "legal_id", "edition", "source_url")},
        "scope_span_occurrence_cid": by_role["scope_literal"],
        "source_version_cid": source_version["record_cid"],
        "interpretation_status": "unreviewed_caller_declaration", "context_closure_verified": False,
    })
    scope_cid = scope_record["record_cid"]
    symbol_record = seal_record({
        "schema": SYMBOL_SCHEMA, "symbol_table": report["symbol_table"],
        "definition_symbol_rebinding": report["definition_symbol_rebinding"],
        "variable_binding": report["variable_binding"], "scope_cid": scope_cid,
        "interpretation_cid": interpretation_cid,
    })
    definition_record = seal_record({
        "schema": DEFINITION_SCHEMA, "profile": report["definition"]["profile"],
        "declaration": report["definition"]["declaration"],
        "native_ast": report["bound_definition_native_ast"],
        "scope_cid": scope_cid, "source_occurrence_cids": def_refs,
        "interpretation_cid": interpretation_cid, "declared_native_profile_encoded": True,
        "definition_lexical_coverage_complete": False, "source_semantics_verified": False,
    })
    norm_record = seal_record({
        "schema": NORM_SCHEMA, "profile": report["profile"], "family": report["family"],
        "declaration": report["norm_declaration"], "native_ast": report["norm_native_ast"],
        "variable_binding": report["variable_binding"], "scope_cid": scope_cid,
        "source_occurrence_cids": norm_refs, "interpretation_cid": interpretation_cid,
        "complete_norm_paragraph_covered": report["complete_norm_paragraph_covered"],
        "universal_category_guard_outside_modal": report["universal_category_guard_outside_modal"],
        "source_semantics_verified": False,
    })
    ast_record = seal_record({
        "schema": AST_SCHEMA, "profile": report["profile"], "family": report["family"],
        "native_ast": report["native_ast"],
        "bound_definition_native_ast": report["bound_definition_native_ast"],
        "norm_native_ast": report["norm_native_ast"], "lean_body": report["lean_body"],
        "scope_cid": scope_cid, "source_occurrence_cids": all_refs,
        "interpretation_cid": interpretation_cid, "lean_compilation_verified": False,
    })
    head_symbol = report["variable_binding"]["category_symbol"]
    head = next(row for row in report["symbol_table"] if row["symbol"] == head_symbol)
    term_record = seal_record({
        "schema": TERM_SCHEMA, "kind": "declared_unary_category", "symbol": head_symbol,
        "source_literal": head["source_literal"], "arity": head["arity"],
        "scope_cid": scope_cid, "interpretation_cid": interpretation_cid,
        "source_occurrence_cids": list(dict.fromkeys([
            by_role["definition_head"], by_role["norm_category"],
        ])), "source_semantics_verified": False,
    })
    input_binding = seal_record({
        "schema": INPUT_SCHEMA, "request_sha256": expected_request_sha256,
        "report_sha256": expected_report_sha256, "raw_sha256": expected_raw_sha256,
        "extracted_sha256": expected_extracted_sha256,
        "request_record_cid": request_record["record_cid"], "report_record_cid": interpretation_cid,
        "source_version_cid": source_version["record_cid"],
        "scope_record_cid": scope_cid, "symbol_record_cid": symbol_record["record_cid"],
        "definition_record_cid": definition_record["record_cid"],
        "norm_record_cid": norm_record["record_cid"], "ast_record_cid": ast_record["record_cid"],
        "term_record_cid": term_record["record_cid"], "source_occurrence_cids": all_refs,
    })
    issues = [seal_record({
        "schema": ISSUE_SCHEMA, "code": code, "reason": reason,
        "report_record_cid": interpretation_cid, "source_occurrence_cids": all_refs,
    }) for code, reason in (
        ("unreviewed_caller_interpretation", "Regeneration and native AST encoding do not establish reviewed legal meaning."),
        ("source_authenticity_unverified", "Official URL shape and exact source bytes do not authenticate a government source."),
        ("context_closure_unverified", "The explicit section-local binding does not close governing legal context or external dependencies."),
        ("definition_coverage_unassessed", "The full definition source block is retained; completeness of its declared meaning is not asserted."),
        ("no_lean_compilation_or_proof", "Retained Lean source has not been compiled or proved by this adapter."),
    )]
    graph = _graph(source_version, occurrences, report_record, scope_record, definition_record,
                   norm_record, ast_record, term_record, input_binding, issues)
    return seal_record({
        "schema": SCHEMA, "profile": report["profile"], "family": report["family"],
        "request_record": request_record, "report_record": report_record,
        "source_version": source_version, "source_occurrences": occurrences,
        "source_bindings": bindings, "scope_record": scope_record, "symbol_record": symbol_record,
        "definition_record": definition_record, "norm_record": norm_record,
        "ast_record": ast_record, "term_record": term_record, "input_binding": input_binding,
        "issues": issues, "graph": graph, "view": "candidate",
        "declared_native_profile_encoded": True, **FALSE_FLAGS,
    })


def _graph(version, occurrences, report, scope, definition, norm, ast, term, binding, issues):
    interpretation_cid, scope_cid = report["record_cid"], scope["record_cid"]
    nodes, edges = [], []

    def node(kind, record, *, origins=None, stable_id=None):
        result = build_node(
            node_type=kind, stable_id=record["record_cid"] if stable_id is None else stable_id,
            content_cid=record["record_cid"],
            scope_cid=None if kind in {"source_version", "occurrence"} else scope_cid,
            source_occurrence_cids=[] if origins is None else origins,
            interpretation_cids=[] if kind in {"source_version", "occurrence"} else [interpretation_cid],
        )
        nodes.append(result)
        return result

    def edge(src, dst, relation, evidence=None):
        edges.append(build_edge(src_cid=src["record_cid"], dst_cid=dst["record_cid"],
                                relation=relation, evidence_cids=[binding["record_cid"]]
                                if evidence is None else evidence))

    source = node("source_version", version)
    occurrence_nodes = {}
    for occurrence in occurrences:
        item = node("occurrence", occurrence, origins=[occurrence["record_cid"]])
        occurrence_nodes[occurrence["record_cid"]] = item
        edge(item, source, "DERIVED_FROM", [occurrence["record_cid"]])
    interpretation = node("interpretation", report, origins=[row["record_cid"] for row in occurrences])
    scope_node = node("scope", scope, origins=[scope["scope_span_occurrence_cid"]], stable_id=scope["scope_key"])
    definition_node = node("definition_assertion", definition, origins=definition["source_occurrence_cids"])
    norm_node = node("norm_assertion", norm, origins=norm["source_occurrence_cids"])
    term_node = node("term_sense", term, origins=term["source_occurrence_cids"], stable_id=term["symbol"])
    ast_node = node("expression", ast, origins=ast["source_occurrence_cids"])
    edge(definition_node, term_node, "DEFINES", [definition["record_cid"], term["record_cid"]])
    edge(norm_node, definition_node, "USES_DEFINITION", [norm["record_cid"], binding["record_cid"]])
    for item, record in ((definition_node, definition), (norm_node, norm), (term_node, term)):
        edge(item, scope_node, "APPLIES_WITHIN")
        edge(item, interpretation, "DERIVED_FROM")
        for origin in record["source_occurrence_cids"]:
            edge(item, occurrence_nodes[origin], "HAS_SOURCE")
    edge(scope_node, occurrence_nodes[scope["scope_span_occurrence_cid"]], "HAS_SOURCE")
    edge(scope_node, interpretation, "DERIVED_FROM")
    edge(ast_node, interpretation, "DERIVED_FROM")
    edge(ast_node, definition_node, "CONTAINS")
    edge(ast_node, norm_node, "CONTAINS")
    for occurrence_node in occurrence_nodes.values():
        edge(interpretation, occurrence_node, "HAS_SOURCE")
    for issue in issues:
        issue_node = node("issue", issue, origins=issue["source_occurrence_cids"])
        edge(issue_node, interpretation, "DERIVED_FROM", [issue["record_cid"]])
    return build_graph_snapshot(nodes, edges)


def validate_definition_norm_candidate(record, report_raw, *, expected_report_sha256,
                                        request_raw, expected_request_sha256, raw_html,
                                        expected_raw_sha256, expected_extracted_sha256):
    """Regenerate all nested source, native AST, symbol and graph records."""
    checked = validate_record(record, schema=SCHEMA, fields=FIELDS)
    expected = adapt_definition_norm_bytes(
        report_raw, expected_report_sha256=expected_report_sha256, request_raw=request_raw,
        expected_request_sha256=expected_request_sha256, raw_html=raw_html,
        expected_raw_sha256=expected_raw_sha256, expected_extracted_sha256=expected_extracted_sha256,
    )
    if checked != expected:
        _fail("definition/norm candidate differs from independent authoritative regeneration")
    return checked


def export_definition_norm_candidate(record, output_directory, **validation_inputs):
    """Export graph envelopes only; retain the full candidate companion."""
    checked = validate_definition_norm_candidate(record, **validation_inputs)
    from .corpus_graph_exchange import write_graph_bundle

    return write_graph_bundle(checked["graph"], output_directory)


__all__ = [
    "SCHEMA", "FALSE_FLAGS", "adapt_definition_norm_bytes",
    "validate_definition_norm_candidate", "export_definition_norm_candidate",
]
