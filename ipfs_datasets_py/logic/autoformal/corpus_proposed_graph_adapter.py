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
from . import corpus_contracts as contracts
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


def _clone_relational_inputs(value):
    """Detach one relational AST without relaxing ordinary corpus metadata.

    The unchanged common owner validates every scalar and shallow key carrier.
    One traversal budgets the actual complete input, while only its ``ast``
    subtree receives the graph owner's existing depth/node allowance.
    """
    if type(value) is not dict or len(value) != len(TRUSTED_INPUT_FIELDS):
        _fail("closed independently supplied proposal inputs fields required")
    require_keys(value, TRUSTED_INPUT_FIELDS, "independently supplied proposal inputs")
    if type(value["profile"]) is not str or value["profile"] != "relational_norm_v1":
        _fail("explicit relational profile required for relational AST custody")
    remaining = contracts.MAX_JSON_NODES
    remaining_bytes = contracts.MAX_RECORD_BYTES
    ast_nodes = 0

    def visit(node, depth, ast_depth=None):
        nonlocal remaining, remaining_bytes, ast_nodes
        remaining -= 1
        if remaining < 0:
            _fail("proposal inputs exceed aggregate JSON node bound")
        if ast_depth is None:
            if depth > contracts.MAX_JSON_DEPTH:
                _fail("proposal metadata exceeds JSON depth bound")
        else:
            ast_nodes += 1
            if ast_depth > proposed.RELATIONAL_MAX_DEPTH or ast_nodes > proposed.MAX_NODES:
                _fail("relational AST exceeds graph JSON depth/node bounds")
        if type(node) is dict:
            # Zero is a minimum-size JSON value. This carrier validates every
            # original key without imposing extra nesting or a larger byte cost.
            if len(node) > remaining:
                _fail("proposal inputs exceed aggregate JSON node bound")
            clone_json(dict.fromkeys(node, 0))
            result = {}
            for key, item in node.items():
                remaining_bytes -= len(key.encode("utf-8"))
                child_ast_depth = (ast_depth + 1 if ast_depth is not None else
                                   0 if depth == 0 and key == "ast" else None)
                result[key] = visit(item, depth + 1, child_ast_depth)
        elif type(node) is list:
            if len(node) > remaining:
                _fail("proposal inputs exceed aggregate JSON node bound")
            child_ast_depth = None if ast_depth is None else ast_depth + 1
            result = [visit(item, depth + 1, child_ast_depth) for item in node]
        else:
            result = clone_json(node)
            if type(node) is str:
                remaining_bytes -= len(node.encode("utf-8"))
        if remaining_bytes < 0:
            _fail("proposal inputs exceed aggregate byte bound")
        return result

    checked = visit(value, 0)
    if len(canonical_dag_json_bytes(checked)) > contracts.MAX_RECORD_BYTES:
        _fail("proposal inputs exceed aggregate byte bound")
    return checked


def _inputs(value, expected_sha256):
    require_sha256(expected_sha256, "expected_inputs_sha256")
    relational = (type(value) is dict and type(value.get("profile")) is str
                  and value["profile"] == "relational_norm_v1")
    checked = _clone_relational_inputs(value) if relational else clone_json(value)
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
    # Full candidate regeneration above already authenticated this canonical
    # string against the independently supplied AST. Recover through the same
    # bounded input policy, rather than parse it again under the legacy depth20.
    ast = _inputs(validation_inputs["trusted_proposal_inputs"],
                  validation_inputs["expected_inputs_sha256"])["ast"]
    raw = custody["ast_json"].encode("utf-8")
    if (canonical_dag_json_bytes(ast) != raw
            or hashlib.sha256(raw).hexdigest() != custody["ast_sha256"]
            or cid_for_dag_json(ast) != custody["ast_cid"]):
        _fail("canonical AST custody bytes or identity differ")
    return ast


__all__ = [
    "SCHEMA", "PARENT_SCHEMA", "TRUSTED_INPUT_FIELDS", "INPUT_DIGEST_RECIPE",
    "adapt_proposed_graph_bytes", "validate_proposed_graph_candidate", "export_proposed_graph_candidate",
    "restore_proposed_graph_ast",
    "adapt_parent_proposed_graph_bytes", "validate_parent_proposed_graph_candidate",
]


# Additive complete-population custody for the explicit graph-v2/eligibility-v3
# profile. The original official-view adapter above remains unchanged.
import base64 as _corpus_base64
import os as _corpus_os
import stat as _corpus_stat
from pathlib import Path as _CorpusPath

COORDINATE_CORPUS_SCHEMA = "legal-coordinate-graph-corpus/v1"
COORDINATE_CORPUS_PROFILE = "original-input-coordinate-graph-v2-corpus-custody/v1"
COORDINATE_CORPUS_EXPORT_SCHEMA = "legal-coordinate-graph-corpus-output-export/v1"
COORDINATE_CORPUS_SCHEMA_V2 = "legal-coordinate-graph-corpus/v2"
COORDINATE_CORPUS_PROFILE_V2 = "original-input-wire-coordinate-graph-v3-corpus-custody/v1"
COORDINATE_CORPUS_EXPORT_SCHEMA_V2 = "legal-coordinate-graph-corpus-output-export/v2"
COORDINATE_CORPUS_METADATA_PROFILE_V2 = "hf-default-parquet-envelope/v1"
MAX_COORDINATE_CORPUS_BYTES = 64 * 1024 * 1024
MAX_COORDINATE_CORPUS_OUTPUTS = 128
_CORPUS_REQUEST_BYTES = 128 * 1024
_CORPUS_ARTIFACT_BYTES = 16 * 1024 * 1024
_CORPUS_ORIGINAL_BYTES = 8 * 1024 * 1024
_CORPUS_INTAKE_FIELDS = {
    "request_raw", "eligibility_report_raw", "eligibility_request_raw", "join_manifest_raw",
    "expected_request_sha256", "join_originals", "source_bindings",
}
_CORPUS_IDENTITY_FIELDS = {
    "output_occurrence_ordinal", "physical_identity_sha256", "route", "ordinal",
}
_CORPUS_CUSTODY_FIELDS = {
    "expected_proposal_sha256", "trusted_proposal_inputs", "expected_inputs_sha256",
    "expected_raw_sha256", "expected_extracted_sha256",
}
_CORPUS_AUTHORITY = dict.fromkeys((
    "source_authenticity_verified", "source_semantics_verified", "context_closure_verified",
    "coordinate_to_graph_source_correspondence_verified", "current_source_release_correspondence_verified",
    "entity_semantic_bindings_verified", "semantic_review_verified", "graph_admitted", "admitted",
    "formalized", "proof_authority", "training_qualified", "evaluation_gold_qualified",
    "model_executed", "training_executed", "Lean_admitted", "published",
), False)
_CORPUS_SELF_PIN = hashlib.sha256(_CorpusPath(__file__).read_bytes()).hexdigest()
_CORPUS_OWNER_PINS = None


def _corpus_need(condition, message):
    if not condition:
        raise CorpusContractError(message)


def _corpus_wire(value, maximum=MAX_COORDINATE_CORPUS_BYTES):
    from .legal_paired_manifest_inventory_v1 import _wire
    return _wire(value, maximum)


def _corpus_read(raw, maximum, label):
    from .legal_paired_manifest_inventory_v1 import _read_json
    return _read_json(raw, maximum, label)


def _corpus_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _corpus_copy(value, maximum=MAX_COORDINATE_CORPUS_BYTES):
    return _corpus_read(_corpus_wire(value, maximum), maximum, "coordinate corpus value")


def _corpus_intake_inputs(value):
    """Detach complete public upstream arguments and commit their exact bytes."""
    from . import legal_span_cache_intake as intake, legal_source_span_target_eligibility_v1 as eligibility
    require_keys(value, _CORPUS_INTAKE_FIELDS, "complete coordinate graph intake inputs")
    captured, identity = {}, {}
    for key, maximum in (("request_raw", _CORPUS_REQUEST_BYTES),
            ("eligibility_report_raw", _CORPUS_ARTIFACT_BYTES),
            ("eligibility_request_raw", _CORPUS_REQUEST_BYTES),
            ("join_manifest_raw", _CORPUS_ARTIFACT_BYTES)):
        raw = value[key]
        _corpus_need(type(raw) is bytes and 0 < len(raw) <= maximum,
                     "bounded exact graph intake bytes required: " + key)
        captured[key] = raw
        identity[key] = {"bytes": len(raw), "sha256": _corpus_sha(raw)}
    require_sha256(value["expected_request_sha256"], "upstream request pin")
    _corpus_need(_corpus_sha(captured["request_raw"]) == value["expected_request_sha256"],
                 "upstream request bytes differ from independent pin")
    captured["expected_request_sha256"] = identity["expected_request_sha256"] = value["expected_request_sha256"]
    captured["join_originals"] = intake._coordinate_graph_originals(value["join_originals"])
    identity["join_originals_sha256"] = eligibility.source_span_target_join_originals_sha256(captured["join_originals"])
    bindings = value["source_bindings"]
    _corpus_need(type(bindings) is dict and all(type(key) is str for key in bindings),
                 "ordinary physical-identity source binding map required")
    binding_raw = _corpus_wire(bindings, _CORPUS_ORIGINAL_BYTES)
    captured["source_bindings"] = _corpus_read(binding_raw, _CORPUS_ORIGINAL_BYTES, "original source bindings")
    identity["source_bindings"] = {"bytes": len(binding_raw), "sha256": _corpus_sha(binding_raw)}
    return captured, _corpus_sha(_corpus_wire(identity, _CORPUS_REQUEST_BYTES))


def coordinate_graph_corpus_originals_sha256(intake_inputs):
    """Commit complete upstream originals; the commitment grants no authority."""
    return _corpus_intake_inputs(intake_inputs)[1]


def _corpus_output_inputs(value):
    _corpus_need(type(value) is list and len(value) <= MAX_COORDINATE_CORPUS_OUTPUTS,
                 "complete bounded ordered coordinate corpus output inputs required")
    captured = []
    for index, item in enumerate(value):
        require_keys(item, _CORPUS_IDENTITY_FIELDS | _CORPUS_CUSTODY_FIELDS, "coordinate corpus output input")
        _corpus_need(type(item["output_occurrence_ordinal"]) is int and item["output_occurrence_ordinal"] == index
                     and type(item["ordinal"]) is int and 0 <= item["ordinal"] < 2**63,
                     "exact ordered output occurrence and formal ordinal required")
        require_sha256(item["physical_identity_sha256"], "output physical identity")
        _corpus_need(type(item["route"]) is str and 0 < len(item["route"].encode("utf-8")) <= 2048,
                     "bounded original output route required")
        missing = [item[key] is None for key in _CORPUS_CUSTODY_FIELDS]
        _corpus_need(all(missing) or not any(missing), "partial output custody inputs are forbidden")
        checked = {key: item[key] for key in _CORPUS_IDENTITY_FIELDS}
        if all(missing):
            checked.update(dict.fromkeys(_CORPUS_CUSTODY_FIELDS, None))
        else:
            for key in _CORPUS_CUSTODY_FIELDS - {"trusted_proposal_inputs"}:
                require_sha256(item[key], key)
                checked[key] = item[key]
            trusted = clone_json(item["trusted_proposal_inputs"])
            require_keys(trusted, TRUSTED_INPUT_FIELDS, "complete original proposal inputs")
            checked["trusted_proposal_inputs"] = trusted
        captured.append(checked)
    raw = _corpus_wire(captured)
    return _corpus_read(raw, MAX_COORDINATE_CORPUS_BYTES, "complete output custody inputs"), _corpus_sha(raw)


def coordinate_graph_corpus_inputs_sha256(output_inputs):
    """Commit every ordered slot, including explicit unavailable custody."""
    return _corpus_output_inputs(output_inputs)[1]


def coordinate_graph_corpus_sha256(report):
    """Hash the full ordinary report; no field is omitted or independently trusted."""
    return _corpus_sha(_corpus_wire(report))


def _coordinate_corpus_owners(*, profile_version=1):
    _corpus_need(type(profile_version) is int and profile_version in (1, 2),
                 "explicit coordinate corpus profile version required")
    from . import (legal_span_cache_intake as intake,
        legal_source_span_target_eligibility_v1 as eligibility,
        corpus_graph_exchange as exchange, corpus_contracts as contracts,
        corpus_graph as graph, corpus_source as source, legal_paired_manifest_inventory_v1 as ordinary)
    from ipfs_datasets_py.utils import cid_utils
    modules = (intake, eligibility, exchange, contracts, graph, source, ordinary, proposed, context, cid_utils)
    root = _CorpusPath(__file__).resolve().parents[3]
    pins = {}
    for module in modules:
        path = _CorpusPath(module.__file__).resolve()
        _corpus_need(path == root.joinpath(*module.__name__.split(".")).with_suffix(".py"),
                     "coordinate corpus owner escaped selected source tree")
        pins[str(path)] = _corpus_sha(path.read_bytes())
    own_path = _CorpusPath(__file__).resolve()
    _corpus_need(_corpus_sha(own_path.read_bytes()) == _CORPUS_SELF_PIN,
                 "coordinate corpus owner changed since import")
    pins[str(own_path)] = _CORPUS_SELF_PIN
    global _CORPUS_OWNER_PINS
    if _CORPUS_OWNER_PINS is None:
        _CORPUS_OWNER_PINS = dict(pins)
    _corpus_need(pins == _CORPUS_OWNER_PINS, "coordinate corpus owners changed since first use")
    validator = ("validate_coordinate_source_graph_intake_v2" if profile_version == 1
                 else "validate_coordinate_source_graph_intake_v3")
    _corpus_need(callable(getattr(intake, validator, None)),
                 "explicit original-input graph v2 owner required; no historical fallback")
    return intake, eligibility, exchange, dict(pins)


def _coordinate_corpus_callbacks(intake, eligibility, exchange, *, profile_version=1):
    upstream = intake._coordinate_graph_callables(eligibility,
        eligibility_version=3 if profile_version == 1 else 4)
    validator = (intake.validate_coordinate_source_graph_intake_v2 if profile_version == 1
                 else intake.validate_coordinate_source_graph_intake_v3)
    result = (*upstream, validator,
        intake.coordinate_source_graph_intake_sha256, intake._coordinate_graph_originals,
        eligibility.source_span_target_join_originals_sha256,
        adapt_proposed_graph_bytes, validate_proposed_graph_candidate, export_proposed_graph_candidate,
        _inputs, _source, globals().get("_candidate"), clone_json, load_record_bytes,
        require_keys, require_sha256, seal_record, validate_record,
        canonical_dag_json_bytes, cid_for_dag_json,
        proposed.validate_graph, proposed.bind_source_occurrence, context.normalized_document_view,
        build_source_version, build_source_occurrence, build_node, build_edge, build_graph_snapshot,
        exchange.write_graph_bundle, exchange.load_graph_bundle,
        coordinate_graph_corpus_originals_sha256, coordinate_graph_corpus_inputs_sha256,
        coordinate_graph_corpus_sha256, prepare_coordinate_graph_corpus_v1,
        validate_coordinate_graph_corpus_v1, export_coordinate_graph_corpus_output_v1)
    if profile_version == 2:
        result += (prepare_coordinate_graph_corpus_v2, validate_coordinate_graph_corpus_v2,
            export_coordinate_graph_corpus_output_v2, _prepare_coordinate_graph_corpus,
            _validate_coordinate_graph_corpus, _export_coordinate_graph_corpus_output,
            _coordinate_corpus_setup, _corpus_intake_inputs, _corpus_output_inputs,
            _corpus_candidate_arguments, _corpus_wire_physical_plan,
            _corpus_wire_export_witness, _corpus_wire_unqualified,
            _corpus_wire, _corpus_read, _corpus_copy, _corpus_sha, _corpus_need,
            _coordinate_corpus_owners, _coordinate_corpus_callbacks,
            _finish_corpus_custody, _corpus_offered_report, _corpus_slot_identity,
            eligibility._owners, intake._coordinate_graph_wire_file_plan,
            exchange._path, exchange._open_directory, exchange._verify_directory,
            exchange._read_file, exchange._identity, _corpus_os.fstat, _corpus_os.stat,
            _corpus_os.listdir, _corpus_os.close, _corpus_stat.S_ISREG)
    return result


def _finish_corpus_custody(checks, primary):
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary coordinate corpus custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
        return
    if failures:
        label, error = failures[0]
        error.add_note("closing coordinate corpus custody check: " + label)
        for other_label, other in failures[1:]:
            error.add_note("additional coordinate corpus custody failure (" + other_label + "): "
                           + type(other).__name__ + ": " + str(other)[:512])
        raise error


def _coordinate_corpus_setup(intake_report_raw, *, expected_intake_raw_sha256, expected_intake_sha256,
        intake_inputs, expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256,
        profile_version=1):
    _corpus_need(type(profile_version) is int and profile_version in (1, 2),
                 "explicit coordinate corpus profile version required")
    for label, digest in (("intake raw", expected_intake_raw_sha256), ("intake canonical", expected_intake_sha256),
            ("intake originals", expected_intake_inputs_sha256), ("output inputs", expected_output_inputs_sha256)):
        require_sha256(digest, label)
    _corpus_need(type(intake_report_raw) is bytes and 0 < len(intake_report_raw) <= MAX_COORDINATE_CORPUS_BYTES
                 and _corpus_sha(intake_report_raw) == expected_intake_raw_sha256,
                 "intake artifact bytes differ from independent pin")
    offered = _corpus_read(intake_report_raw, MAX_COORDINATE_CORPUS_BYTES, "coordinate graph intake")
    _corpus_need(_corpus_sha(_corpus_wire(offered)) == expected_intake_sha256,
                 "intake canonical report differs from independent pin")
    schema = "legal-coordinate-source-graph-intake/v2" if profile_version == 1 else "legal-coordinate-source-graph-intake/v3"
    profile = ("original-input-coordinate-source-graph-intake/v1" if profile_version == 1
               else "original-input-wire-coordinate-source-graph-intake/v1")
    _corpus_need(type(offered) is dict and offered.get("schema") == schema
                 and offered.get("source_compatibility_profile") == profile,
                 "explicit original-input coordinate graph v2 required" if profile_version == 1
                 else "explicit wire coordinate graph v3 required")
    originals, originals_pin = _corpus_intake_inputs(intake_inputs)
    slots, slots_pin = _corpus_output_inputs(output_inputs)
    _corpus_need(originals_pin == expected_intake_inputs_sha256,
                 "intake originals differ from independent commitment")
    _corpus_need(slots_pin == expected_output_inputs_sha256,
                 "output inputs differ from independent commitment")
    request = _corpus_read(originals["request_raw"], _CORPUS_REQUEST_BYTES,
                           "graph v2 request" if profile_version == 1 else "wire graph v3 request")
    eligibility_request = _corpus_read(originals["eligibility_request_raw"], _CORPUS_REQUEST_BYTES,
                                       "original-input eligibility request")
    _corpus_need(request.get("schema") == ("legal-coordinate-source-graph-intake-request/v2" if profile_version == 1
                                          else "legal-coordinate-source-graph-intake-request/v3")
                 and request.get("source_compatibility_profile") == profile
                 and eligibility_request.get("schema") == ("legal-source-span-target-eligibility-request/v3" if profile_version == 1
                                                            else "legal-source-span-target-eligibility-request/v4")
                 and eligibility_request.get("source_compatibility_profile") == (
                     "original-input-coordinate-target-eligibility/v1" if profile_version == 1
                     else "original-input-wire-coordinate-target-eligibility/v1"),
                 "graph v2 and original-input eligibility v3 requests required" if profile_version == 1
                 else "wire graph v3 and original-input eligibility v4 requests required")
    if profile_version == 2:
        _corpus_need(offered.get("metadata_profile") == request.get("metadata_profile")
                     == eligibility_request.get("metadata_profile") == COORDINATE_CORPUS_METADATA_PROFILE_V2,
                     "explicit matching wire corpus metadata profile required")
    intake, eligibility, exchange, pins = _coordinate_corpus_owners(profile_version=profile_version)
    callbacks = _coordinate_corpus_callbacks(intake, eligibility, exchange, profile_version=profile_version)
    owners_provider, callbacks_provider, finish_custody = (
        _coordinate_corpus_owners, _coordinate_corpus_callbacks, _finish_corpus_custody)
    offered_snapshot = _corpus_wire(offered)
    parsed_snapshots = tuple(_corpus_wire(value) for value in (request, eligibility_request))
    pins_snapshot = _corpus_wire(pins, _CORPUS_REQUEST_BYTES)
    validator = (intake.validate_coordinate_source_graph_intake_v2 if profile_version == 1
                 else intake.validate_coordinate_source_graph_intake_v3)
    opened, plan, plan_raw, files_raw = False, None, None, None
    runtime, runtime_pins_raw, runtime_description = None, None, None
    held, replays = [], []

    def hold(value, label):
        if profile_version == 2:
            _corpus_need(len(held) < 1024, "bounded corpus return witness population required")
            held.append((value, _corpus_wire(value), label))
        return value

    def originals_unchanged():
        _corpus_need(_corpus_intake_inputs(intake_inputs)[1] == expected_intake_inputs_sha256
                     and _corpus_intake_inputs(originals)[1] == expected_intake_inputs_sha256,
                     "original or detached graph intake inputs changed")
        _corpus_need(_corpus_output_inputs(output_inputs)[1] == expected_output_inputs_sha256
                     and _corpus_output_inputs(slots)[1] == expected_output_inputs_sha256,
                     "original or detached output custody inputs changed")
        _corpus_need(_corpus_wire(offered) == offered_snapshot, "captured graph intake report changed")
        if profile_version == 2:
            _corpus_need(tuple(_corpus_wire(value) for value in (request, eligibility_request)) == parsed_snapshots,
                         "wire corpus parsed request snapshots changed")
            _corpus_need(_corpus_wire(pins, _CORPUS_REQUEST_BYTES) == pins_snapshot,
                         "wire corpus captured producer pins changed")

    def producers_unchanged():
        owner_check = _coordinate_corpus_owners if profile_version == 1 else owners_provider
        callback_check = _coordinate_corpus_callbacks if profile_version == 1 else callbacks_provider
        _corpus_need(owner_check(profile_version=profile_version)[-1] == pins,
                     "coordinate corpus producer sources changed during operation")
        current = callback_check(intake, eligibility, exchange, profile_version=profile_version)
        _corpus_need(len(current) == len(callbacks) and all(left is right for left, right in zip(current, callbacks)),
                     "coordinate corpus operation callback changed during operation")
        if profile_version == 2 and runtime is not None:
            owners = eligibility._owners()
            _corpus_need(owners[4] is runtime and _corpus_wire(owners[5], _CORPUS_REQUEST_BYTES) == runtime_pins_raw
                         and _corpus_wire(runtime.describe_runtime("legal_ir", eligibility_request["decoder_profile"]))
                         == runtime_description, "wire corpus runtime description or owners changed")

    def returns_unchanged():
        if profile_version == 2:
            for value, snapshot, label in held:
                _corpus_need(_corpus_wire(value) == snapshot, "live wire corpus return changed: " + label)
            for value, snapshot in replays:
                _corpus_need(_corpus_wire(value) == snapshot, "genuine wire graph return changed during corpus operation")

    def physical_unchanged():
        if profile_version == 2 and files_raw is not None:
            _corpus_need(_corpus_wire(plan, _CORPUS_ARTIFACT_BYTES) == plan_raw,
                         "wire corpus physical nomination changed before file replay")
            join = eligibility._owners()[0]
            _corpus_need(_corpus_wire(join._coordinate_file_witnesses(*plan), _CORPUS_REQUEST_BYTES) == files_raw,
                         "wire corpus physical files changed after genuine graph replay")

    def guard(extra=()):
        checks = (("original and detached inputs", originals_unchanged),
                  ("producer sources and callbacks", producers_unchanged))
        if profile_version == 2:
            checks += (("live wire returns", returns_unchanged), ("physical wire inputs", physical_unchanged))
        checks += tuple(extra) + (("post-replay original inputs", originals_unchanged),
                                  ("post-replay producer sources and callbacks", producers_unchanged))
        if profile_version == 2:
            checks += (("final live wire returns", returns_unchanged),
                       ("final physical wire inputs", physical_unchanged),
                       ("final original wire inputs", originals_unchanged))
        return checks

    def adopt(checked):
        nonlocal plan, plan_raw, files_raw, runtime, runtime_pins_raw, runtime_description
        _corpus_need(profile_version == 2, "wire corpus adoption requires explicit profile v2")
        originals_unchanged()
        producers_unchanged()
        _corpus_need(_corpus_wire(checked) == offered_snapshot,
                     "regenerated wire graph differs from the independently pinned artifact")
        intake._coordinate_graph_wire_unqualified(checked)
        replays.append((checked, _corpus_wire(checked)))
        if plan is None:
            plan = list(_corpus_wire_physical_plan(intake, eligibility, checked, originals))
            plan_raw = _corpus_wire(plan, _CORPUS_ARTIFACT_BYTES)
            files_raw = _corpus_wire(eligibility._owners()[0]._coordinate_file_witnesses(*plan), _CORPUS_REQUEST_BYTES)
            owners = eligibility._owners()
            runtime, runtime_pins_raw = owners[4], _corpus_wire(owners[5], _CORPUS_REQUEST_BYTES)
            runtime_description = _corpus_wire(checked["runtime_description"])
            producers_unchanged()
        return checked

    def replay():
        nonlocal opened
        if profile_version == 2:
            # Refuse callback substitution before invoking the captured validator.
            producers_unchanged()
        selected = intake.validate_coordinate_source_graph_intake_v2 if profile_version == 1 else validator
        checked = selected(offered, expected_report_sha256=expected_intake_sha256, **originals)
        _corpus_need(_corpus_wire(checked) == offered_snapshot,
                     "upstream graph intake differs from independently pinned original")
        opened = True
        if profile_version == 2:
            adopt(checked)
        return checked

    def finish(primary, extra=(), *, close_upstream=True):
        checks = ()
        if close_upstream and (profile_version == 1 or opened):
            checks += (("closing public graph intake replay", replay),)
        selected_finish = _finish_corpus_custody if profile_version == 1 else finish_custody
        selected_finish(checks + guard(extra), primary)

    return {"originals": originals, "slots": slots, "pins": pins,
            "replay": replay, "originals_unchanged": originals_unchanged,
            "producers_unchanged": producers_unchanged, "finish": finish,
            "guard": guard, "hold": hold, "adopt": adopt, "offered": offered,
            "request": request, "eligibility_request": eligibility_request}


def _corpus_wire_physical_plan(intake, eligibility, genuine_graph, originals):
    """Reuse upstream nominations only from the genuinely replayed wire ancestry."""
    intake._coordinate_graph_wire_unqualified(genuine_graph)
    raw = genuine_graph.get("eligibility_report_raw_utf8")
    _corpus_need(type(raw) is str and raw.encode("utf-8") == originals["eligibility_report_raw"],
                 "genuine wire graph must retain the exact original eligibility bytes")
    eligible = _corpus_read(raw.encode("utf-8"), _CORPUS_ARTIFACT_BYTES,
                            "genuinely replayed corpus wire eligibility")
    digest = genuine_graph.get("source_metadata_intake_sha256")
    require_sha256(digest, "wire corpus source metadata intake")
    _corpus_need(eligible.get("schema") == "legal-source-span-target-eligibility/v4"
                 and eligible.get("source_compatibility_profile") == "original-input-wire-coordinate-target-eligibility/v1"
                 and eligible.get("metadata_profile") == genuine_graph.get("metadata_profile")
                 == COORDINATE_CORPUS_METADATA_PROFILE_V2
                 and eligible.get("source_metadata_intake_sha256") == digest,
                 "wire corpus graph and original eligibility ancestry differ")
    return intake._coordinate_graph_wire_file_plan(eligibility, eligible,
        originals["join_manifest_raw"], originals["join_originals"])


def _corpus_wire_unqualified(report, *, export=False):
    """Keep custody evidence separate from legal, consumer and proof authority."""
    _corpus_need(type(report) is dict
                 and report.get("schema") == (COORDINATE_CORPUS_EXPORT_SCHEMA_V2 if export else COORDINATE_CORPUS_SCHEMA_V2)
                 and report.get("source_compatibility_profile") == COORDINATE_CORPUS_PROFILE_V2
                 and report.get("metadata_profile") == COORDINATE_CORPUS_METADATA_PROFILE_V2,
                 "explicit wire corpus v2 profile required")
    require_sha256(report.get("source_metadata_intake_sha256"), "wire corpus metadata intake")
    rows = [report] if export else [report, *report["output_occurrences"]]
    for row in rows:
        authority = row.get("authority")
        _corpus_need(type(authority) is dict and set(authority) == set(_CORPUS_AUTHORITY)
                     and all(value is False for value in authority.values()),
                     "wire corpus custody cannot grant authority")
        for key in ("source_binding_mask", "training_mask", "evaluation_gold_mask"):
            _corpus_need(type(row.get(key)) is int and row[key] == 0,
                         "wire corpus masks must remain plain integer zero")
        _corpus_need(row.get("selected_occurrence") is None and row.get("consumer_eligible") is False
                     and row.get("coordinate_to_graph_source_correspondence") == "unverified_no_independent_crosswalk",
                     "wire corpus cannot infer source correspondence or consumer qualification")
        if not export:
            _corpus_need(row.get("entity_binding") == "unavailable_semantic_companions_not_supplied",
                         "wire corpus entity semantics remain unavailable")
    _corpus_need(report.get("atomic_snapshot_verified") is False,
                 "wire corpus observations cannot grant an atomic snapshot")


def _corpus_wire_export_witness(exchange, directory, manifest, snapshot):
    """Retain the existing four-file format and genuine loader through final custody."""
    _corpus_need(exchange.BUNDLE_FILES == frozenset(("manifest.json", "snapshot.json", "nodes.parquet", "edges.parquet"))
                 and exchange.MANIFEST_FILE == "manifest.json" and exchange.SNAPSHOT_FILE == "snapshot.json"
                 and exchange.MAX_MANIFEST_BYTES == 32 * 1024 and exchange.MAX_RECORD_BYTES == 1024 * 1024
                 and exchange.MAX_PARQUET_BYTES == 8 * 1024 * 1024,
                 "existing graph bundle filenames and byte bounds changed")
    path = exchange._path(directory)
    manifest_raw = canonical_dag_json_bytes(manifest)
    expected = _corpus_sha(manifest_raw)
    descriptor = exchange._open_directory(path)
    try:
        before_directory = exchange._identity(_corpus_os.fstat(descriptor))
        _corpus_need(set(_corpus_os.listdir(descriptor)) == exchange.BUNDLE_FILES,
                     "wire corpus export requires the existing complete four-file bundle")
        witnesses = {}
        for name in sorted(exchange.BUNDLE_FILES):
            maximum = (exchange.MAX_MANIFEST_BYTES if name == exchange.MANIFEST_FILE else
                       exchange.MAX_RECORD_BYTES if name == exchange.SNAPSHOT_FILE else exchange.MAX_PARQUET_BYTES)
            before = _corpus_os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _corpus_need(_corpus_stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                         "wire corpus export requires unaliased regular bundle files")
            raw = exchange._read_file(descriptor, name, maximum)
            after = _corpus_os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _corpus_need(exchange._identity(before) == exchange._identity(after),
                         "wire corpus exported file changed while recording custody")
            witnesses[name] = {"identity": list(exchange._identity(after)),
                               "sha256": _corpus_sha(raw), "bytes": len(raw)}
        _corpus_need(witnesses[exchange.MANIFEST_FILE]["sha256"] == expected,
                     "written export manifest differs from the genuine writer return")
        loaded = exchange.load_graph_bundle(path, expected_manifest_sha256=expected)
        _corpus_need(canonical_dag_json_bytes(loaded["manifest"]) == manifest_raw
                     and canonical_dag_json_bytes(loaded["snapshot"]) == canonical_dag_json_bytes(snapshot),
                     "genuine late bundle readback differs from the selected candidate")
        exchange._verify_directory(path, descriptor)
        _corpus_need(exchange._identity(_corpus_os.fstat(descriptor)) == before_directory
                     and set(_corpus_os.listdir(descriptor)) == exchange.BUNDLE_FILES,
                     "wire corpus exported directory changed during readback")
        for name, witness in witnesses.items():
            current = _corpus_os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _corpus_need(list(exchange._identity(current)) == witness["identity"]
                         and _corpus_stat.S_ISREG(current.st_mode) and current.st_nlink == 1,
                         "wire corpus exported file changed during genuine late readback")
        return {"directory": list(before_directory), "files": witnesses}, loaded
    finally:
        _corpus_os.close(descriptor)


def _corpus_slot_identity(row, ordinal):
    return {"output_occurrence_ordinal": ordinal, "physical_identity_sha256": row["physical_identity_sha256"],
            "route": row["route"], "ordinal": row["ordinal"]}


def _corpus_candidate_arguments(intake_output, slot, originals):
    """Require independent full proposal inputs to match the replayed producer."""
    graph, request = intake_output["graph"], intake_output["graph_request"]
    _corpus_need(type(graph) is dict and type(request) is dict,
                 "unresolved upstream graph cannot receive corpus custody inputs")
    _corpus_need(set(request) == TRUSTED_INPUT_FIELDS - {"semantic_declarations", "scope_request"}
                 and request.get("profile") == "canonical_rules_v1",
                 "exact canonical-rules graph producer inputs required")
    expected_inputs = {**request, "semantic_declarations": None, "scope_request": None}
    trusted = slot["trusted_proposal_inputs"]
    _corpus_need(canonical_dag_json_bytes(trusted) == canonical_dag_json_bytes(expected_inputs),
                 "independent proposal inputs differ from genuine graph producer inputs")
    _corpus_need(request["source"] == intake_output["source_binding"],
                 "genuine graph and nominated source binding differ")
    binding = originals["source_bindings"].get(slot["physical_identity_sha256"])
    _corpus_need(type(binding) is dict and binding.get("scope") == request["scope"],
                 "original physical source declaration missing or changed")
    encoded = binding.get("raw_html_base64")
    _corpus_need(type(encoded) is str and len(encoded) <= 4 * ((MAX_RAW_HTML_BYTES + 2) // 3),
                 "bounded original raw HTML declaration required")
    try:
        raw_html = _corpus_base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise CorpusContractError("invalid original raw HTML declaration") from error
    _corpus_need(0 < len(raw_html) <= MAX_RAW_HTML_BYTES, "original raw HTML bound exceeded")
    document = binding["document"]
    _corpus_need(_corpus_sha(raw_html) == slot["expected_raw_sha256"]
                 and _corpus_sha(document["document_text"].encode("utf-8")) == slot["expected_extracted_sha256"],
                 "original nominated HTML or extracted view differs from independent pin")
    raw = canonical_dag_json_bytes(graph)
    _corpus_need(_corpus_sha(raw) == slot["expected_proposal_sha256"],
                 "genuine canonical proposal bytes differ from independent pin")
    arguments = {"expected_proposal_sha256": slot["expected_proposal_sha256"],
        "trusted_proposal_inputs": trusted, "expected_inputs_sha256": slot["expected_inputs_sha256"],
        "document": document, "raw_html": raw_html, "expected_raw_sha256": slot["expected_raw_sha256"],
        "expected_extracted_sha256": slot["expected_extracted_sha256"]}
    return raw, arguments


def _prepare_coordinate_graph_corpus(intake_report_raw, *, expected_intake_raw_sha256,
        expected_intake_sha256, intake_inputs, expected_intake_inputs_sha256,
        output_inputs, expected_output_inputs_sha256, profile_version):
    """Retain every graph-v2 output and add only existing candidate custody."""
    state = _coordinate_corpus_setup(intake_report_raw,
        expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
        intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=profile_version)
    primary, report, report_raw = None, None, None
    try:
        state["originals_unchanged"]()
        state["producers_unchanged"]()
        intake = state["replay"]()
        outputs, slots = intake["output_occurrences"], state["slots"]
        _corpus_need(len(outputs) == len(slots) <= MAX_COORDINATE_CORPUS_OUTPUTS,
                     "complete ordered output custody population differs")
        rows = []
        for ordinal, (upstream, slot) in enumerate(zip(outputs, slots)):
            identity = _corpus_slot_identity(upstream, ordinal)
            _corpus_need(all(slot[key] == value for key, value in identity.items()),
                         "output physical identity, route, ordinal or order differs")
            absent = slot["trusted_proposal_inputs"] is None
            candidate, issues = None, []
            if upstream["graph"] is None:
                _corpus_need(absent, "unresolved upstream graph must retain explicit unavailable custody")
                issues.append({"code": "upstream_graph_unresolved"})
            elif absent:
                issues.append({"code": "custody_inputs_not_supplied"})
            else:
                raw, arguments = _corpus_candidate_arguments(upstream, slot, state["originals"])
                candidate = adapt_proposed_graph_bytes(raw, **arguments)
                state["hold"](candidate, "genuine adapter candidate")
                candidate_raw = _corpus_wire(candidate)
                checked = validate_proposed_graph_candidate(candidate, **arguments)
                state["hold"](checked, "genuine checked candidate")
                _corpus_need(_corpus_wire(candidate) == candidate_raw == _corpus_wire(checked),
                             "existing candidate changed during genuine custody validation")
            rows.append({**identity, "intake_output": _corpus_copy(upstream), "candidate": candidate,
                "disposition": "candidate_corpus_custody" if candidate is not None else "unresolved",
                "custody_issues": issues, "selected_occurrence": None, "source_binding_mask": 0,
                "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
                "entity_binding": "unavailable_semantic_companions_not_supplied", "consumer_eligible": False,
                "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(_CORPUS_AUTHORITY)})
        report = {"schema": COORDINATE_CORPUS_SCHEMA if profile_version == 1 else COORDINATE_CORPUS_SCHEMA_V2,
            "source_compatibility_profile": COORDINATE_CORPUS_PROFILE if profile_version == 1 else COORDINATE_CORPUS_PROFILE_V2,
            "intake_report_raw_utf8": intake_report_raw.decode("utf-8"),
            "intake_report_raw_sha256": expected_intake_raw_sha256,
            "intake_report_sha256": expected_intake_sha256,
            "intake_inputs_sha256": expected_intake_inputs_sha256,
            "output_inputs_sha256": expected_output_inputs_sha256,
            "physical_rows": _corpus_copy(intake["physical_rows"]),
            "row_references": _corpus_copy(intake["row_references"]), "output_occurrences": rows,
            "population_complete": True, "coverage_scope": ("complete_supplied_graph_v2_physical_reference_and_output_population_only" if profile_version == 1
                else "complete_supplied_wire_graph_v3_physical_reference_and_output_population_only"),
            "proposal_bytes_recipe": "canonical_dag_json_bytes_of_genuinely_replayed_graph/v1",
            "original_input_retention": "complete_external_originals_required_for_every_replay",
            "upstream_reexecution_performed": True,
            "upstream_reexecution_requirement": ("opening_and_closing_public_graph_v2_original_input_replay" if profile_version == 1
                else "opening_and_closing_public_wire_graph_v3_original_input_replay"),
            "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
            "current_source_release_correspondence": "unverified_no_independent_crosswalk",
            "entity_binding": "unavailable_semantic_companions_not_supplied", "selected_occurrence": None,
            "source_binding_mask": 0, "consumer_eligible": False, "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": dict(_CORPUS_AUTHORITY), "producer_pins": state["pins"],
            "producer_pins_scope": "listed_corpus_graph_source_and_upstream_owner_observations_not_complete_execution_closure",
            "atomic_snapshot_verified": False,
            "counts": {"physical_rows": len(intake["physical_rows"]), "row_references": len(intake["row_references"]),
                "output_occurrences": len(rows), "candidate_outputs": sum(row["candidate"] is not None for row in rows),
                "unresolved_outputs": sum(row["candidate"] is None for row in rows)}}
        if profile_version == 2:
            report.update(metadata_profile=COORDINATE_CORPUS_METADATA_PROFILE_V2,
                source_metadata_intake_sha256=intake["source_metadata_intake_sha256"])
            _corpus_wire_unqualified(report)
            state["hold"](report, "live prepared corpus report")
        report_raw = _corpus_wire(report)
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"](primary)
    if profile_version == 1:
        _corpus_need(_corpus_wire(report) == report_raw, "detached corpus report changed during closing replay")
        return _corpus_read(report_raw, MAX_COORDINATE_CORPUS_BYTES, "coordinate graph corpus")
    primary = None
    try:
        _corpus_need(_corpus_wire(report) == report_raw, "wire corpus report changed during closing replay")
        final = _corpus_read(report_raw, MAX_COORDINATE_CORPUS_BYTES, "detached wire coordinate corpus v2")
        state["hold"](final, "final detached corpus report")
        _corpus_wire_unqualified(final)
        _corpus_need(_corpus_wire(final) == report_raw, "final wire corpus serialization changed")
        return final
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"](primary, close_upstream=False)


def _corpus_offered_report(report, expected_report_sha256, *, profile_version=1):
    require_sha256(expected_report_sha256, "coordinate corpus report")
    raw = report if type(report) is bytes else _corpus_wire(report)
    offered = _corpus_read(raw, MAX_COORDINATE_CORPUS_BYTES, "offered coordinate corpus report")
    _corpus_need(type(offered) is dict
                 and offered.get("schema") == (COORDINATE_CORPUS_SCHEMA if profile_version == 1 else COORDINATE_CORPUS_SCHEMA_V2)
                 and offered.get("source_compatibility_profile") == (COORDINATE_CORPUS_PROFILE if profile_version == 1 else COORDINATE_CORPUS_PROFILE_V2),
                 "explicit graph-v2 coordinate corpus profile required" if profile_version == 1
                 else "explicit wire graph-v3 coordinate corpus v2 profile required")
    if profile_version == 2:
        _corpus_wire_unqualified(offered)
    snapshot = _corpus_wire(offered)
    _corpus_need(_corpus_sha(snapshot) == expected_report_sha256, "coordinate corpus report pin differs")
    return offered, snapshot


def _validate_coordinate_graph_corpus(report, intake_report_raw, *, expected_report_sha256,
        expected_intake_raw_sha256, expected_intake_sha256, intake_inputs,
        expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256, profile_version):
    """Regenerate the complete report; wire outer custody adds no redundant graph replay."""
    offered, snapshot = _corpus_offered_report(report, expected_report_sha256, profile_version=profile_version)
    intake, eligibility, exchange, pins = _coordinate_corpus_owners(profile_version=profile_version)
    callbacks = _coordinate_corpus_callbacks(intake, eligibility, exchange, profile_version=profile_version)
    arguments = {"expected_intake_raw_sha256": expected_intake_raw_sha256,
        "expected_intake_sha256": expected_intake_sha256, "intake_inputs": intake_inputs,
        "expected_intake_inputs_sha256": expected_intake_inputs_sha256,
        "output_inputs": output_inputs, "expected_output_inputs_sha256": expected_output_inputs_sha256}
    state = (_coordinate_corpus_setup(intake_report_raw, **arguments, profile_version=2)
             if profile_version == 2 else None)
    if state is not None:
        state["hold"](offered, "outer offered corpus report")
    primary = None
    try:
        prepare = prepare_coordinate_graph_corpus_v1 if profile_version == 1 else prepare_coordinate_graph_corpus_v2
        expected = prepare(intake_report_raw, **arguments)
        if state is not None:
            state["hold"](expected, "outer regenerated corpus report")
        _corpus_need(_corpus_wire(expected) == snapshot,
                     "coordinate corpus report differs from complete original-input replay")
        if state is not None:
            # Refuse changes in outer parsed objects before any path nomination or I/O.
            _finish_corpus_custody(state["guard"](), None)
            raw = expected["intake_report_raw_utf8"].encode("utf-8")
            _corpus_need(raw == intake_report_raw,
                         "regenerated wire corpus does not retain the exact original graph artifact")
            genuine_graph = _corpus_read(raw, MAX_COORDINATE_CORPUS_BYTES,
                                         "outer genuinely regenerated wire corpus graph")
            state["adopt"](genuine_graph)
            _corpus_wire_unqualified(expected)
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            current = (_corpus_read(report, MAX_COORDINATE_CORPUS_BYTES, "offered corpus report")
                       if type(report) is bytes else report)
            _corpus_need(_corpus_wire(current) == snapshot and _corpus_wire(offered) == snapshot,
                         "offered corpus report changed during validation")

        def producers_unchanged():
            current = _coordinate_corpus_callbacks(intake, eligibility, exchange, profile_version=profile_version)
            _corpus_need(_coordinate_corpus_owners(profile_version=profile_version)[-1] == pins
                         and len(current) == len(callbacks)
                         and all(left is right for left, right in zip(current, callbacks)),
                         "coordinate corpus validation sources or callbacks changed")
        checks = (("offered corpus report", offered_unchanged),
                  ("validation sources and callbacks", producers_unchanged))
        if state is None:
            _finish_corpus_custody(checks, primary)
        else:
            state["finish"](primary, checks, close_upstream=False)


def _export_coordinate_graph_corpus_output(report, output_occurrence_ordinal, output_directory,
        intake_report_raw, *, expected_report_sha256, expected_intake_raw_sha256, expected_intake_sha256,
        intake_inputs, expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256, profile_version):
    """Export one explicitly selected candidate after full-population validation.

    The existing writer performs its own genuine load/readback. A late custody
    failure raises while retaining written artifacts; it supplies no qualified
    export receipt and does not delete or repair the failed output directory.
    """
    _corpus_need(type(output_occurrence_ordinal) is int and 0 <= output_occurrence_ordinal < MAX_COORDINATE_CORPUS_OUTPUTS,
                 "explicit integer output occurrence ordinal required")
    offered, snapshot = _corpus_offered_report(report, expected_report_sha256, profile_version=profile_version)
    arguments = {"expected_intake_raw_sha256": expected_intake_raw_sha256,
        "expected_intake_sha256": expected_intake_sha256, "intake_inputs": intake_inputs,
        "expected_intake_inputs_sha256": expected_intake_inputs_sha256,
        "output_inputs": output_inputs, "expected_output_inputs_sha256": expected_output_inputs_sha256}
    state = _coordinate_corpus_setup(intake_report_raw, **arguments, profile_version=profile_version)
    if profile_version == 2:
        state["hold"](offered, "export offered corpus report")
        _, _, exchange, _ = _coordinate_corpus_owners(profile_version=2)
        output_directory = exchange._path(output_directory)
    output_witness, manifest, selected_snapshot = None, None, None
    primary, checked, checked_raw, receipt, receipt_raw = None, None, None, None, None

    def reports_unchanged():
        current = (_corpus_read(report, MAX_COORDINATE_CORPUS_BYTES, "offered corpus export report")
                   if type(report) is bytes else report)
        _corpus_need(_corpus_wire(current) == snapshot, "offered corpus report changed during export")
        if checked is not None:
            _corpus_need(_corpus_wire(checked) == checked_raw, "validated corpus report changed during export")

    def written_bundle_unchanged():
        if profile_version == 2 and output_witness is not None:
            witness, loaded = _corpus_wire_export_witness(exchange, output_directory, manifest, selected_snapshot)
            state["hold"](loaded, "genuine late exported bundle readback")
            _corpus_need(_corpus_wire(witness, _CORPUS_REQUEST_BYTES) == output_witness,
                         "written corpus graph bundle identity or content changed after export")

    try:
        validate = validate_coordinate_graph_corpus_v1 if profile_version == 1 else validate_coordinate_graph_corpus_v2
        checked = validate(report, intake_report_raw,
            expected_report_sha256=expected_report_sha256, **arguments)
        state["hold"](checked, "genuine full export validation return")
        checked_raw = _corpus_wire(checked)
        state["originals_unchanged"]()
        state["producers_unchanged"]()
        fresh_intake = state["replay"]()
        _corpus_need(output_occurrence_ordinal < len(checked["output_occurrences"]),
                     "selected output occurrence ordinal is outside complete population")
        row = checked["output_occurrences"][output_occurrence_ordinal]
        _corpus_need(row["candidate"] is not None and row["disposition"] == "candidate_corpus_custody",
                     "unresolved coordinate corpus output cannot be exported")
        _, candidate_inputs = _corpus_candidate_arguments(
            fresh_intake["output_occurrences"][output_occurrence_ordinal],
            state["slots"][output_occurrence_ordinal], state["originals"])
        manifest = export_proposed_graph_candidate(row["candidate"], output_directory, **candidate_inputs)
        state["hold"](manifest, "genuine graph writer manifest")
        _corpus_need(manifest["snapshot_cid"] == row["candidate"]["graph"]["record_cid"],
                     "existing graph export manifest names a different candidate snapshot")
        if profile_version == 2:
            selected_snapshot = row["candidate"]["graph"]
            witness, loaded = _corpus_wire_export_witness(exchange, output_directory, manifest, selected_snapshot)
            output_witness = _corpus_wire(witness, _CORPUS_REQUEST_BYTES)
            state["hold"](witness, "written bundle physical witness")
            state["hold"](loaded, "genuine opening exported bundle readback")
        receipt = {"schema": COORDINATE_CORPUS_EXPORT_SCHEMA if profile_version == 1 else COORDINATE_CORPUS_EXPORT_SCHEMA_V2,
            "source_compatibility_profile": COORDINATE_CORPUS_PROFILE if profile_version == 1 else COORDINATE_CORPUS_PROFILE_V2,
            "corpus_report_sha256": expected_report_sha256,
            **{key: row[key] for key in _CORPUS_IDENTITY_FIELDS},
            "candidate_record_cid": row["candidate"]["record_cid"], "graph_manifest": manifest,
            "graph_manifest_sha256": _corpus_sha(canonical_dag_json_bytes(manifest)),
            "snapshot_cid": manifest["snapshot_cid"], "delegated_writer_readback_performed": True,
            "full_candidate_retained_separately_required": True,
            "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
            "selected_occurrence": None, "source_binding_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": dict(_CORPUS_AUTHORITY), "atomic_snapshot_verified": False}
        if profile_version == 2:
            receipt.update(metadata_profile=COORDINATE_CORPUS_METADATA_PROFILE_V2,
                source_metadata_intake_sha256=fresh_intake["source_metadata_intake_sha256"], consumer_eligible=False)
            _corpus_wire_unqualified(receipt, export=True)
            state["hold"](receipt, "live corpus export receipt")
        receipt_raw = _corpus_wire(receipt)
    except BaseException as error:
        primary = error
        raise
    finally:
        checks = (("offered and validated corpus report", reports_unchanged),)
        if profile_version == 2:
            checks += (("written graph bundle after closing replay", written_bundle_unchanged),)
        state["finish"](primary, checks)
    if profile_version == 1:
        _corpus_need(_corpus_wire(receipt) == receipt_raw, "export receipt changed during closing custody")
        return _corpus_read(receipt_raw, MAX_COORDINATE_CORPUS_BYTES, "coordinate corpus output export")
    primary = None
    try:
        _corpus_need(_corpus_wire(receipt) == receipt_raw, "wire export receipt changed during closing custody")
        final = _corpus_read(receipt_raw, MAX_COORDINATE_CORPUS_BYTES, "detached wire coordinate corpus export v2")
        state["hold"](final, "final detached export receipt")
        _corpus_wire_unqualified(final, export=True)
        _corpus_need(_corpus_wire(final) == receipt_raw, "final wire export receipt serialization changed")
        return final
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"](primary, (("offered and validated corpus report", reports_unchanged),
            ("written graph bundle after final serialization", written_bundle_unchanged)), close_upstream=False)


def prepare_coordinate_graph_corpus_v1(intake_report_raw, *, expected_intake_raw_sha256,
        expected_intake_sha256, intake_inputs, expected_intake_inputs_sha256,
        output_inputs, expected_output_inputs_sha256):
    """Retain the complete explicit graph-v2 population with candidate custody."""
    return _prepare_coordinate_graph_corpus(intake_report_raw,
        expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
        intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=1)


def validate_coordinate_graph_corpus_v1(report, intake_report_raw, *, expected_report_sha256,
        expected_intake_raw_sha256, expected_intake_sha256, intake_inputs,
        expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    """Regenerate every output from the independently retained original inputs."""
    return _validate_coordinate_graph_corpus(report, intake_report_raw,
        expected_report_sha256=expected_report_sha256, expected_intake_raw_sha256=expected_intake_raw_sha256,
        expected_intake_sha256=expected_intake_sha256, intake_inputs=intake_inputs,
        expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=1)


def export_coordinate_graph_corpus_output_v1(report, output_occurrence_ordinal, output_directory,
        intake_report_raw, *, expected_report_sha256, expected_intake_raw_sha256, expected_intake_sha256,
        intake_inputs, expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    """Export one explicit candidate with the existing writer after full validation."""
    return _export_coordinate_graph_corpus_output(report, output_occurrence_ordinal, output_directory,
        intake_report_raw, expected_report_sha256=expected_report_sha256,
        expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
        intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=1)


def prepare_coordinate_graph_corpus_v2(intake_report_raw, *, expected_intake_raw_sha256,
        expected_intake_sha256, intake_inputs, expected_intake_inputs_sha256,
        output_inputs, expected_output_inputs_sha256):
    """Retain the complete explicit wire graph-v3 population with candidate custody."""
    return _prepare_coordinate_graph_corpus(intake_report_raw,
        expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
        intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=2)


def validate_coordinate_graph_corpus_v2(report, intake_report_raw, *, expected_report_sha256,
        expected_intake_raw_sha256, expected_intake_sha256, intake_inputs,
        expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    """Regenerate every output from the independently retained original inputs."""
    return _validate_coordinate_graph_corpus(report, intake_report_raw,
        expected_report_sha256=expected_report_sha256, expected_intake_raw_sha256=expected_intake_raw_sha256,
        expected_intake_sha256=expected_intake_sha256, intake_inputs=intake_inputs,
        expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=2)


def export_coordinate_graph_corpus_output_v2(report, output_occurrence_ordinal, output_directory,
        intake_report_raw, *, expected_report_sha256, expected_intake_raw_sha256, expected_intake_sha256,
        intake_inputs, expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    """Export one explicit candidate with the existing writer after full validation."""
    return _export_coordinate_graph_corpus_output(report, output_occurrence_ordinal, output_directory,
        intake_report_raw, expected_report_sha256=expected_report_sha256,
        expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
        intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256,
        profile_version=2)


__all__ += ["COORDINATE_CORPUS_SCHEMA", "COORDINATE_CORPUS_PROFILE", "COORDINATE_CORPUS_EXPORT_SCHEMA",
    "coordinate_graph_corpus_originals_sha256", "coordinate_graph_corpus_inputs_sha256",
    "coordinate_graph_corpus_sha256", "prepare_coordinate_graph_corpus_v1",
    "validate_coordinate_graph_corpus_v1", "export_coordinate_graph_corpus_output_v1",
    "COORDINATE_CORPUS_SCHEMA_V2", "COORDINATE_CORPUS_PROFILE_V2", "COORDINATE_CORPUS_EXPORT_SCHEMA_V2",
    "COORDINATE_CORPUS_METADATA_PROFILE_V2", "prepare_coordinate_graph_corpus_v2",
    "validate_coordinate_graph_corpus_v2", "export_coordinate_graph_corpus_output_v2"]
