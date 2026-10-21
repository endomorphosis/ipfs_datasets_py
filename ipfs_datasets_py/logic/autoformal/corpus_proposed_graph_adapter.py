"""Lossless custody bridge from existing proposed legal graphs to corpus v1.

The original graph's semantic IDs, declarations and ordered AST remain intact.
This adapter validates them against independent caller inputs, then binds an
official-view selector or replayed literal parent to the corpus source contract. Its graph edges
describe custody only; AST-tree edges never become legal-role relationships.
Definitions remain unreviewed tags with definition_semantics_encoded=False.
"""
from __future__ import annotations

import hashlib

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

from . import legal_semantic_graph as proposed
from . import legal_statutory_context as context
from .corpus_contracts import (
    CorpusContractError,
    clone_json,
    load_json_bytes,
    load_record_bytes,
    require_keys,
    require_sha256,
    seal_record,
    validate_record,
)
from .corpus_graph import build_edge, build_graph_snapshot, build_node
from .corpus_source import build_source_occurrence, build_source_version

SCHEMA = "legal-corpus-proposed-graph-candidate/v1"
PARENT_SCHEMA = "legal-corpus-parent-proposed-graph-candidate/v1"
PROPOSAL_SCHEMA = "legal-corpus-proposal-custody/v1"
AST_SCHEMA = "legal-corpus-proposed-ast-custody/v1"
AST_JSON_SCHEMA = "legal-corpus-proposed-ast-custody/v2"
INPUT_SCHEMA = "legal-corpus-proposal-input-binding/v1"
ISSUE_SCHEMA = "legal-corpus-proposal-issue/v1"
INPUT_DIGEST_RECIPE = "sha256-of-canonical-dag-json-bytes/v1"
MAX_RAW_HTML_BYTES = 8_000_000
TRUSTED_INPUT_FIELDS = {
    "ast", "profile", "source", "scope", "semantic_declarations",
    "dependency_refs", "evidence_refs", "scope_request",
}
FIELDS = {
    "proposal_record", "ast_record", "input_binding", "source_version", "source_occurrence",
    "issues", "graph", "view", "admitted", "formalized", "source_semantics_verified",
    "source_authenticity_verified", "external_references_verified", "definition_semantics_encoded",
}
PARENT_FIELDS = FIELDS | {"parent_source_binding"}


def _fail(message):
    raise CorpusContractError(message)


def _inputs(value, expected_sha256):
    require_sha256(expected_sha256, "expected_inputs_sha256")
    checked = clone_json(value)
    require_keys(checked, TRUSTED_INPUT_FIELDS, "independently supplied proposal inputs")
    if hashlib.sha256(canonical_dag_json_bytes(checked)).hexdigest() != expected_sha256:
        _fail("original proposal inputs differ from independently expected SHA256")
    return checked


def _source(document, raw_html, inputs, expected_raw_sha256, expected_extracted_sha256):
    require_sha256(expected_raw_sha256, "expected_raw_sha256")
    require_sha256(expected_extracted_sha256, "expected_extracted_sha256")
    if (type(raw_html) is not bytes or not 1 <= len(raw_html) <= MAX_RAW_HTML_BYTES
            or hashlib.sha256(raw_html).hexdigest() != expected_raw_sha256):
        _fail("raw HTML differs from independently expected SHA256")
    # The existing owner regenerates the complete extracted document and its
    # edition-bound v2 view/selector. Caller-supplied source digests alone cannot
    # substitute for this physical geometry validation.
    try:
        bound = proposed.bind_source_occurrence(document, raw_html,
            selector=inputs["source"]["selector"],
            document_revision=inputs["source"]["document_revision"])
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError) as error:
        raise CorpusContractError("official source selector/document regeneration failed") from error
    if canonical_dag_json_bytes(bound) != canonical_dag_json_bytes(inputs["source"]):
        _fail("proposed source binding differs from independent document regeneration")
    text = document["document_text"]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_extracted_sha256:
        _fail("extracted official view differs from independently expected SHA256")
    version = build_source_version(
        source_id=document["legal_id"], release_id=bound["document_revision"],
        edition=str(document["edition"]), provision_id=document["legal_id"],
        raw_bytes=raw_html, expected_raw_sha256=expected_raw_sha256,
        extracted_text=text, expected_extracted_sha256=expected_extracted_sha256,
        extraction_profile=context.SCHEMA, normalization_profile=context.NORMALIZATION_PROFILE,
        media_type="text/html",
    )
    selector = bound["selector"]
    occurrence = build_source_occurrence(version,
        expected_raw_sha256=expected_raw_sha256, extracted_text=text,
        expected_extracted_sha256=expected_extracted_sha256,
        start_char=selector["char_start"], end_char=selector["char_end"],
        start_utf8=selector["utf8_byte_start"], end_utf8=selector["utf8_byte_end"],
    )
    return version, occurrence


def adapt_proposed_graph_bytes(raw, *, expected_proposal_sha256, trusted_proposal_inputs,
                               expected_inputs_sha256, document, raw_html,
                               expected_raw_sha256, expected_extracted_sha256):
    """Preserve one independently committed proposal and its original inputs.

    Inputs have exactly ``TRUSTED_INPUT_FIELDS``. Their external SHA256 uses
    ``canonical_dag_json_bytes``; the proposal's SHA256 binds its exact original
    serialized file bytes. All original inputs and physical HTML/view bytes are
    required again for validation. No review identity or source authenticity is
    inferred. Aggregate common-envelope limits may be reached before owner caps.
    """
    graph = load_record_bytes(raw, expected_sha256=expected_proposal_sha256)
    inputs = _inputs(trusted_proposal_inputs, expected_inputs_sha256)
    source_version, source_occurrence = _source(document, raw_html, inputs,
        expected_raw_sha256, expected_extracted_sha256)
    return _candidate(raw, graph, inputs, expected_proposal_sha256, expected_inputs_sha256,
                      source_version, source_occurrence)


def adapt_parent_proposed_graph_bytes(raw, *, expected_proposal_sha256, trusted_proposal_inputs,
                                     expected_inputs_sha256, parent_bundle, expected_manifest_cid,
                                     source_occurrence_cid, companion_record_cid, report_bytes,
                                     expected_report_pins, replay_inputs, limits=None):
    """Replay the existing physical parent population and preserve its records.

    Exact source/role nomination remains an unreviewed proposal. The externally
    retained complete population is required again, including original reports,
    file bytes and row witnesses. A self-sealed graph cannot supply that evidence.
    No HTML, official edition, governing scope or qualified definition is inferred.
    """
    graph = load_record_bytes(raw, expected_sha256=expected_proposal_sha256)
    inputs = _inputs(trusted_proposal_inputs, expected_inputs_sha256)
    bound = proposed.bind_parent_source_occurrence(parent_bundle,
        expected_manifest_cid=expected_manifest_cid, source_occurrence_cid=source_occurrence_cid,
        companion_record_cid=companion_record_cid, report_bytes=report_bytes,
        expected_report_pins=expected_report_pins, replay_inputs=replay_inputs, limits=limits)
    if bound != inputs["source"]:
        _fail("proposed parent source differs from complete independent regeneration")
    return _candidate(raw, graph, inputs, expected_proposal_sha256, expected_inputs_sha256,
                      bound["source_version"], bound["selector"], parent_source_binding=bound)


def _candidate(raw, graph, inputs, expected_proposal_sha256, expected_inputs_sha256,
               source_version, source_occurrence, *, parent_source_binding=None):
    """Common lossless proposal custody; source admission belongs to each route."""
    try:
        proposed.validate_graph(graph, ast=inputs["ast"],
            **{key: inputs[key] for key in TRUSTED_INPUT_FIELDS if key != "ast"})
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError) as error:
        raise CorpusContractError("proposal differs from independently supplied graph inputs") from error
    proposal_record = seal_record({
        "schema": PROPOSAL_SCHEMA, "proposal_json": raw.decode("utf-8"),
        "proposal_sha256": expected_proposal_sha256, "proposal_graph_id": graph["graph_id"],
        "original_proposal_schema": graph["schema"], "projection_status": "opaque_preserved",
        "source_semantics_verified": False, "definition_semantics_encoded": False,
    })
    ast_payload = {
        "schema": AST_SCHEMA, "ast": inputs["ast"], "ast_cid": cid_for_dag_json(inputs["ast"]),
        "profile": inputs["profile"], "source_occurrence_cid": source_occurrence["record_cid"],
        "projection_status": "ordered_ast_custody_only", "source_semantics_verified": False,
    }
    if inputs["profile"] == "relational_norm_v1":
        # The complete request is already bounded by _inputs and the graph
        # owner. Preserve its canonical bytes without adding nested envelope
        # depth to that AST. Existing profiles retain their exact v1 payload.
        ast_raw = canonical_dag_json_bytes(ast_payload.pop("ast"))
        ast_payload.update(schema=AST_JSON_SCHEMA, ast_json=ast_raw.decode("utf-8"),
                           ast_sha256=hashlib.sha256(ast_raw).hexdigest())
    ast_record = seal_record(ast_payload)
    input_binding = seal_record({
        "schema": INPUT_SCHEMA, "inputs_sha256": expected_inputs_sha256,
        "inputs_cid": cid_for_dag_json(inputs), "digest_recipe": INPUT_DIGEST_RECIPE,
        "proposal_sha256": expected_proposal_sha256,
        "proposal_record_cid": proposal_record["record_cid"],
        "ast_record_cid": ast_record["record_cid"],
        "source_version_cid": source_version["record_cid"],
        "source_occurrence_cid": source_occurrence["record_cid"],
    })
    occurrence_cid = source_occurrence["record_cid"]
    source_node = build_node(node_type="source_version", stable_id=source_version["record_cid"],
                             content_cid=source_version["record_cid"])
    occurrence_node = build_node(node_type="occurrence", stable_id=occurrence_cid,
        content_cid=occurrence_cid, source_occurrence_cids=[occurrence_cid])
    proposal_node = build_node(node_type="interpretation", stable_id=graph["graph_id"],
        content_cid=proposal_record["record_cid"], source_occurrence_cids=[occurrence_cid],
        interpretation_cids=[proposal_record["record_cid"]])
    ast_node = build_node(node_type="expression", stable_id=ast_record["record_cid"],
        content_cid=ast_record["record_cid"], source_occurrence_cids=[occurrence_cid],
        interpretation_cids=[proposal_record["record_cid"]])
    nodes = [source_node, occurrence_node, proposal_node, ast_node]
    edges = [
        build_edge(src_cid=occurrence_node["record_cid"], dst_cid=source_node["record_cid"],
                   relation="DERIVED_FROM", evidence_cids=[occurrence_cid]),
        build_edge(src_cid=proposal_node["record_cid"], dst_cid=occurrence_node["record_cid"],
                   relation="HAS_SOURCE", evidence_cids=[input_binding["record_cid"]]),
        build_edge(src_cid=proposal_node["record_cid"], dst_cid=ast_node["record_cid"],
                   relation="DERIVED_FROM", evidence_cids=[input_binding["record_cid"]]),
    ]
    issues = []

    def issue(kind, reason):
        record = seal_record({
            "schema": ISSUE_SCHEMA, "kind": kind, "reason": reason,
            "proposal_record_cid": proposal_record["record_cid"],
            "source_occurrence_cid": occurrence_cid,
        })
        issues.append(record)
        node = build_node(node_type="issue", stable_id=record["record_cid"],
                          content_cid=record["record_cid"], source_occurrence_cids=[occurrence_cid])
        nodes.append(node)
        edges.append(build_edge(src_cid=node["record_cid"], dst_cid=proposal_node["record_cid"],
                                relation="DERIVED_FROM", evidence_cids=[record["record_cid"]]))

    issue("unreviewed_semantic_proposal", "Source integrity and AST transport do not establish reviewed legal meaning.")
    issue("context_closure_unverified", "Declared proposal scope does not establish complete legal context or dependency closure.")
    if parent_source_binding is not None:
        issue("parent_governing_source_unresolved", "Literal physical field provenance and all candidate alternatives remain bound by the complete parent manifest; no governing occurrence, edition or statutory region is selected.")
    if graph["entities"] or graph["assertions"]:
        issue("semantic_declarations_preserved_opaquely", "Original entity/assertion identities and declarations remain in the proposal; no legal-role graph projection is inferred.")
    if any(row["declaration"]["kind"] == "definition" for row in graph["entities"]):
        issue("definition_semantics_not_encoded", "Definition operator tags are unreviewed metadata, not validated quantified definition semantics.")
    references = [*graph["dependency_refs"], *graph["evidence_refs"]]
    references += [reference for row in graph["entities"] for reference in row["declaration"]["evidence_refs"]]
    references += [reference for row in graph["assertions"]
                   for field in ("dependency_refs", "evidence_refs") for reference in row["declaration"][field]]
    if references:
        issue("external_references_unverified", "External evidence and dependency references are retained declarations; their artifact bytes are not authenticated by this adapter.")
    return seal_record({
        "schema": SCHEMA if parent_source_binding is None else PARENT_SCHEMA,
        **({} if parent_source_binding is None else {"parent_source_binding": parent_source_binding}),
        "proposal_record": proposal_record, "ast_record": ast_record,
        "input_binding": input_binding, "source_version": source_version,
        "source_occurrence": source_occurrence, "issues": issues,
        "graph": build_graph_snapshot(nodes, edges), "view": "candidate",
        "admitted": False, "formalized": False, "source_semantics_verified": False,
        "source_authenticity_verified": False, "external_references_verified": False,
        "definition_semantics_encoded": False,
    })


def validate_proposed_graph_candidate(record, *, expected_proposal_sha256, trusted_proposal_inputs,
                                      expected_inputs_sha256, document, raw_html,
                                      expected_raw_sha256, expected_extracted_sha256):
    """Regenerate every nested record from independent inputs and exact source."""
    value = validate_record(record, schema=SCHEMA, fields=FIELDS)
    original = value["proposal_record"]
    if type(original) is not dict or type(original.get("proposal_json")) is not str:
        _fail("candidate must retain exact original proposal JSON")
    expected = adapt_proposed_graph_bytes(original["proposal_json"].encode("utf-8"),
        expected_proposal_sha256=expected_proposal_sha256,
        trusted_proposal_inputs=trusted_proposal_inputs, expected_inputs_sha256=expected_inputs_sha256,
        document=document, raw_html=raw_html, expected_raw_sha256=expected_raw_sha256,
        expected_extracted_sha256=expected_extracted_sha256)
    if expected != value:
        _fail("candidate differs from independently regenerated proposal/source custody")
    return value


def validate_parent_proposed_graph_candidate(record, *, expected_proposal_sha256,
        trusted_proposal_inputs, expected_inputs_sha256, parent_bundle, expected_manifest_cid,
        source_occurrence_cid, companion_record_cid, report_bytes, expected_report_pins,
        replay_inputs, limits=None):
    """Regenerate the proposal and every companion from the complete originals."""
    value = validate_record(record, schema=PARENT_SCHEMA, fields=PARENT_FIELDS)
    original = value["proposal_record"]
    if type(original) is not dict or type(original.get("proposal_json")) is not str:
        _fail("candidate must retain exact original proposal JSON")
    expected = adapt_parent_proposed_graph_bytes(original["proposal_json"].encode("utf-8"),
        expected_proposal_sha256=expected_proposal_sha256, trusted_proposal_inputs=trusted_proposal_inputs,
        expected_inputs_sha256=expected_inputs_sha256, parent_bundle=parent_bundle,
        expected_manifest_cid=expected_manifest_cid, source_occurrence_cid=source_occurrence_cid,
        companion_record_cid=companion_record_cid, report_bytes=report_bytes,
        expected_report_pins=expected_report_pins, replay_inputs=replay_inputs, limits=limits)
    if expected != value:
        _fail("candidate differs from independently regenerated parent/source custody")
    return value


def _validate_candidate(record, validation_inputs):
    if type(record) is dict and record.get("schema") == PARENT_SCHEMA:
        return validate_parent_proposed_graph_candidate(record, **validation_inputs)
    return validate_proposed_graph_candidate(record, **validation_inputs)


def export_proposed_graph_candidate(record, output_directory, **validation_inputs):
    """Export only graph envelopes; retain the full companion candidate separately."""
    checked = _validate_candidate(record, validation_inputs)
    from .corpus_graph_exchange import write_graph_bundle
    return write_graph_bundle(checked["graph"], output_directory)


def restore_proposed_graph_ast(record, **validation_inputs):
    """Recover the complete AST only after full independent custody replay.

    V2's string payload removes envelope nesting, not request grammar or byte
    limits. The original source and graph inputs remain mandatory. This is
    structured JSON recovery, not raw source-file formatting or legal meaning.
    """
    checked = _validate_candidate(record, validation_inputs)
    custody = checked["ast_record"]
    if custody["schema"] == AST_SCHEMA:
        return clone_json(custody["ast"])
    if custody["schema"] != AST_JSON_SCHEMA or custody["profile"] != "relational_norm_v1":
        _fail("unsupported AST custody schema/profile")
    raw = custody["ast_json"].encode("utf-8")
    ast = load_json_bytes(raw, expected_sha256=custody["ast_sha256"])
    if canonical_dag_json_bytes(ast) != raw or cid_for_dag_json(ast) != custody["ast_cid"]:
        _fail("canonical AST custody bytes or identity differ")
    return ast


__all__ = [
    "SCHEMA", "PARENT_SCHEMA", "TRUSTED_INPUT_FIELDS", "INPUT_DIGEST_RECIPE",
    "adapt_proposed_graph_bytes", "validate_proposed_graph_candidate", "export_proposed_graph_candidate",
    "restore_proposed_graph_ast",
    "adapt_parent_proposed_graph_bytes", "validate_parent_proposed_graph_candidate",
]
