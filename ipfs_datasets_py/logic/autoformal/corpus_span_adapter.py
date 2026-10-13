"""Preserve paired-cache observations as source-bound candidate interpretations.

This custody adapter accepts the existing paired-span v1/v2 row formats. It
retains the exact input JSON bytes and every emitted formal output, including
duplicates, producer routes, unsupported representations and legacy flags.
Formal payloads remain opaque: ``typed-deontic-rule/v1`` does not itself identify
one uniform semantic AST. No entity, definition, role or Lean claim is inferred.

An occurrence join requires caller-supplied source records, expected hashes and
the complete extracted view. Text equality alone never locates a physical span.
Missing joins and context remain explicit issues. Candidate record size is
bounded by the common envelope limit; oversized inputs fail without truncation.
"""
from __future__ import annotations

import hashlib

from .corpus_contracts import (
    CorpusContractError,
    clone_json,
    load_json_bytes,
    load_record_bytes,
    require_int,
    require_keys,
    require_sha256,
    require_text,
    seal_record,
    validate_record,
)
from .corpus_graph import build_edge, build_graph_snapshot, build_node
from .corpus_source import (
    validate_context_declaration,
    validate_source_occurrence,
)

SCHEMA = "legal-corpus-paired-span-candidate/v1"
INPUT_SCHEMA = "legal-corpus-paired-span-input/v1"
INTERPRETATION_SCHEMA = "legal-corpus-opaque-interpretation/v1"
ISSUE_SCHEMA = "legal-corpus-span-issue/v1"
SUPPORTED_PAIRED_SCHEMAS = frozenset({"uscode-paired-span-census/v1", "uscode-paired-span-census/v2"})
MAX_OUTPUTS_PER_ROUTE = 128
ROUTES = (
    ("autoencoder", "formal_outputs"),
    ("compiler", "formal_outputs"),
    ("compiler", "canonical_formal_outputs"),
)
FIELDS = {
    "input_record", "source_binding", "interpretations", "issues", "graph",
    "view", "admitted", "formalized", "source_semantics_verified",
}
_BINDING_FIELDS = {
    "source_version", "source_occurrence", "context_declaration", "expected_raw_sha256",
    "extracted_text", "expected_extracted_sha256",
}
_FORMAL_FIELDS = {
    "family", "format", "payload_json", "sha256", "origin", "independent",
    "target_conditioned", "syntax_status",
}


def _source(row):
    version = require_text(row.get("schema_version"), "paired schema_version")
    if version not in SUPPORTED_PAIRED_SCHEMAS:
        raise CorpusContractError("unsupported paired span schema_version")
    source = row.get("source")
    if type(source) is not dict:
        raise CorpusContractError("paired source object required")
    require_text(source.get("span_id"), "source.span_id")
    text = require_text(source.get("text"), "source.text", max_bytes=1024 * 1024)
    require_sha256(source.get("text_sha256"), "source.text_sha256")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != source["text_sha256"]:
        raise CorpusContractError("paired source text differs from its SHA256")
    return source


def _binding(source, supplied):
    if supplied is None:
        return None
    require_keys(supplied, _BINDING_FIELDS, "explicit source binding")
    occurrence = validate_source_occurrence(
        supplied["source_occurrence"], source_version=supplied["source_version"],
        expected_raw_sha256=supplied["expected_raw_sha256"],
        extracted_text=supplied["extracted_text"],
        expected_extracted_sha256=supplied["expected_extracted_sha256"],
    )
    if (occurrence["span_text"] != source["text"]
            or occurrence["span_sha256"] != source["text_sha256"]):
        raise CorpusContractError("paired span differs from the explicitly selected source occurrence")
    context = validate_context_declaration(
        supplied["context_declaration"], source_occurrence=occurrence,
        expected_occurrence_cid=occurrence["record_cid"],
    )
    # Revision and legal_id are preserved historical identifiers. Their lexical
    # shape is not evidence of identity with edition/provision/source records.
    return {
        "source_version": clone_json(supplied["source_version"]),
        "source_occurrence": occurrence, "context_declaration": context,
        "join_method": "caller_selected_exact_occurrence/v1",
        "source_integrity": "expected_hashes_and_extracted_geometry_checked",
        "source_authenticity_verified": False,
    }


def _formal(output):
    if type(output) is not dict or not _FORMAL_FIELDS <= set(output):
        raise CorpusContractError("complete paired formal output metadata required")
    for field in ("family", "format", "origin", "syntax_status"):
        require_text(output[field], "formal output " + field)
    for field in ("independent", "target_conditioned"):
        if type(output[field]) is not bool:
            raise CorpusContractError("formal output independence/conditioning must be explicit booleans")
    require_text(output["payload_json"], "formal output payload_json", max_bytes=1024 * 1024)
    raw = output["payload_json"].encode("utf-8")
    # Parse only to verify bounded, strict JSON custody; do not normalize the AST
    # or rewrite the producer's exact payload JSON string.
    payload = load_json_bytes(raw, expected_sha256=output["sha256"])
    if type(payload) not in (dict, list, str) or not payload:
        raise CorpusContractError("formal payload must be a nonempty JSON object, array or string")
    return clone_json(output)


def adapt_paired_span_bytes(raw, *, expected_row_sha256, source_binding=None):
    """Create a candidate record from externally hash-bound paired JSON bytes.

    ``expected_row_sha256`` commits to the complete supplied JSON serialization,
    independently of the historical observation_id (which is retained as data).
    ``source_binding=None`` preserves unresolved records without guessing a join.
    A binding has exactly the six keys named by ``_BINDING_FIELDS``; the extracted
    view is checked but not duplicated in the resulting candidate record.
    """
    row = load_record_bytes(raw, expected_sha256=expected_row_sha256)
    source = _source(row)
    binding = _binding(source, source_binding)
    input_record = seal_record({
        "schema": INPUT_SCHEMA, "row_json": raw.decode("utf-8"),
        "row_sha256": expected_row_sha256, "paired_schema": row["schema_version"],
        "span_id": source["span_id"], "span_text_sha256": source["text_sha256"],
    })
    input_cid = input_record["record_cid"]
    nodes, edges, interpretations, issues = [], [], [], []
    occurrence_cid = binding["source_occurrence"]["record_cid"] if binding else None
    context_cid = binding["context_declaration"]["record_cid"] if binding else None
    occurrence_node = None

    def add_issue(kind, reason, *, route=None):
        issue = seal_record({
            "schema": ISSUE_SCHEMA, "input_cid": input_cid, "kind": kind,
            "reason": reason, "route": route, "source_occurrence_cid": occurrence_cid,
        })
        issues.append(issue)
        node = build_node(node_type="issue", stable_id=issue["record_cid"],
                          content_cid=issue["record_cid"],
                          source_occurrence_cids=[occurrence_cid] if binding else [])
        nodes.append(node)
        if occurrence_node:
            edges.append(build_edge(src_cid=node["record_cid"],
                dst_cid=occurrence_node["record_cid"], relation="HAS_SOURCE", evidence_cids=[issue["record_cid"]]))

    if binding:
        version_cid = binding["source_version"]["record_cid"]
        version_node = build_node(node_type="source_version", stable_id=version_cid, content_cid=version_cid)
        occurrence_node = build_node(node_type="occurrence", stable_id=occurrence_cid,
                                    content_cid=occurrence_cid, source_occurrence_cids=[occurrence_cid])
        nodes.extend([version_node, occurrence_node])
        edges.append(build_edge(src_cid=occurrence_node["record_cid"], dst_cid=version_node["record_cid"],
                                relation="DERIVED_FROM", evidence_cids=[occurrence_cid]))
        context = binding["context_declaration"]
        if context["availability"] == "required_unavailable":
            add_issue("context_required_unavailable", "Declared source context is missing; interpretation remains pending.")
        elif context["availability"] == "declared_context":
            add_issue("context_declaration_only", "Referenced context has not been resolved or authenticated by this adapter.")
    else:
        add_issue("source_occurrence_unresolved", "No explicit source occurrence binding was supplied; span text is not a physical join.")

    for producer, field in ROUTES:
        route = producer + "." + field
        branch = row.get(producer)
        if type(branch) is not dict:
            raise CorpusContractError("paired producer object required: " + producer)
        outputs = branch.get(field)
        if outputs is None:
            add_issue("formal_output_collection_missing", "Producer did not retain this formal output collection.", route=route)
            continue
        if type(outputs) is not list or len(outputs) > MAX_OUTPUTS_PER_ROUTE:
            raise CorpusContractError("formal output collection exceeds bounded list contract")
        if not outputs:
            add_issue("formal_outputs_unavailable", "Producer emitted no formal outputs in this collection.", route=route)
        for ordinal, output in enumerate(outputs):
            require_int(ordinal, "formal output ordinal", maximum=MAX_OUTPUTS_PER_ROUTE - 1)
            interpretation = seal_record({
                "schema": INTERPRETATION_SCHEMA, "input_cid": input_cid,
                "source_occurrence_cid": occurrence_cid, "context_declaration_cid": context_cid,
                "source_binding_status": "exact_occurrence_bound" if binding else "unresolved",
                "route": route, "ordinal": ordinal, "formal_output": _formal(output),
                "projection_status": "opaque_preserved", "source_semantics_verified": False,
            })
            interpretations.append(interpretation)
            node = build_node(node_type="interpretation", stable_id=interpretation["record_cid"],
                content_cid=interpretation["record_cid"],
                source_occurrence_cids=[occurrence_cid] if binding else [],
                interpretation_cids=[interpretation["record_cid"]])
            nodes.append(node)
            if occurrence_node:
                edges.append(build_edge(src_cid=node["record_cid"], dst_cid=occurrence_node["record_cid"],
                                        relation="HAS_SOURCE", evidence_cids=[interpretation["record_cid"]]))
    if interpretations:
        add_issue("semantic_projection_pending", "All formal payloads are preserved opaquely; typed semantic projection and source review remain pending.")
    return seal_record({
        "schema": SCHEMA, "input_record": input_record, "source_binding": binding,
        "interpretations": interpretations, "issues": issues,
        "graph": build_graph_snapshot(nodes, edges), "view": "candidate",
        "admitted": False, "formalized": False, "source_semantics_verified": False,
    })


def validate_span_candidate(record, *, expected_row_sha256, source_binding=None):
    """Recompute custody and graph contents, using source bytes for bound records."""
    value = validate_record(record, schema=SCHEMA, fields=FIELDS)
    original = value["input_record"]
    if type(original) is not dict or type(original.get("row_json")) is not str:
        raise CorpusContractError("candidate must retain exact paired input JSON")
    expected = adapt_paired_span_bytes(original["row_json"].encode("utf-8"),
        expected_row_sha256=expected_row_sha256, source_binding=source_binding)
    if expected != value:
        raise CorpusContractError("candidate contents differ from recomputed paired/source custody")
    return value
