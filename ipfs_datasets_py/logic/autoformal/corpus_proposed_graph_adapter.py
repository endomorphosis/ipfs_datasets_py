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


# Additive complete-population custody for the explicit graph-v2/eligibility-v3
# profile. The original official-view adapter above remains unchanged.
import base64 as _corpus_base64
from pathlib import Path as _CorpusPath

COORDINATE_CORPUS_SCHEMA = "legal-coordinate-graph-corpus/v1"
COORDINATE_CORPUS_PROFILE = "original-input-coordinate-graph-v2-corpus-custody/v1"
COORDINATE_CORPUS_EXPORT_SCHEMA = "legal-coordinate-graph-corpus-output-export/v1"
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


def _coordinate_corpus_owners():
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
    _corpus_need(callable(getattr(intake, "validate_coordinate_source_graph_intake_v2", None)),
                 "explicit original-input graph v2 owner required; no historical fallback")
    return intake, eligibility, exchange, dict(pins)


def _coordinate_corpus_callbacks(intake, eligibility, exchange):
    upstream = intake._coordinate_graph_callables(eligibility, eligibility_version=3)
    return (*upstream, intake.validate_coordinate_source_graph_intake_v2,
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
        intake_inputs, expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    for label, digest in (("intake raw", expected_intake_raw_sha256), ("intake canonical", expected_intake_sha256),
            ("intake originals", expected_intake_inputs_sha256), ("output inputs", expected_output_inputs_sha256)):
        require_sha256(digest, label)
    _corpus_need(type(intake_report_raw) is bytes and 0 < len(intake_report_raw) <= MAX_COORDINATE_CORPUS_BYTES
                 and _corpus_sha(intake_report_raw) == expected_intake_raw_sha256,
                 "intake artifact bytes differ from independent pin")
    offered = _corpus_read(intake_report_raw, MAX_COORDINATE_CORPUS_BYTES, "coordinate graph intake")
    _corpus_need(_corpus_sha(_corpus_wire(offered)) == expected_intake_sha256,
                 "intake canonical report differs from independent pin")
    _corpus_need(type(offered) is dict and offered.get("schema") == "legal-coordinate-source-graph-intake/v2"
                 and offered.get("source_compatibility_profile") == "original-input-coordinate-source-graph-intake/v1",
                 "explicit original-input coordinate graph v2 required")
    originals, originals_pin = _corpus_intake_inputs(intake_inputs)
    slots, slots_pin = _corpus_output_inputs(output_inputs)
    _corpus_need(originals_pin == expected_intake_inputs_sha256,
                 "intake originals differ from independent commitment")
    _corpus_need(slots_pin == expected_output_inputs_sha256,
                 "output inputs differ from independent commitment")
    request = _corpus_read(originals["request_raw"], _CORPUS_REQUEST_BYTES, "graph v2 request")
    eligibility_request = _corpus_read(originals["eligibility_request_raw"], _CORPUS_REQUEST_BYTES,
                                       "original-input eligibility request")
    _corpus_need(request.get("schema") == "legal-coordinate-source-graph-intake-request/v2"
                 and request.get("source_compatibility_profile") == "original-input-coordinate-source-graph-intake/v1"
                 and eligibility_request.get("schema") == "legal-source-span-target-eligibility-request/v3"
                 and eligibility_request.get("source_compatibility_profile") == "original-input-coordinate-target-eligibility/v1",
                 "graph v2 and original-input eligibility v3 requests required")
    intake, eligibility, exchange, pins = _coordinate_corpus_owners()
    callbacks = _coordinate_corpus_callbacks(intake, eligibility, exchange)
    offered_snapshot = _corpus_wire(offered)

    def originals_unchanged():
        _corpus_need(_corpus_intake_inputs(intake_inputs)[1] == expected_intake_inputs_sha256
                     and _corpus_intake_inputs(originals)[1] == expected_intake_inputs_sha256,
                     "original or detached graph intake inputs changed")
        _corpus_need(_corpus_output_inputs(output_inputs)[1] == expected_output_inputs_sha256
                     and _corpus_output_inputs(slots)[1] == expected_output_inputs_sha256,
                     "original or detached output custody inputs changed")
        _corpus_need(_corpus_wire(offered) == offered_snapshot, "captured graph intake report changed")

    def producers_unchanged():
        _corpus_need(_coordinate_corpus_owners()[-1] == pins,
                     "coordinate corpus producer sources changed during operation")
        current = _coordinate_corpus_callbacks(intake, eligibility, exchange)
        _corpus_need(len(current) == len(callbacks) and all(left is right for left, right in zip(current, callbacks)),
                     "coordinate corpus operation callback changed during operation")

    def replay():
        checked = intake.validate_coordinate_source_graph_intake_v2(offered,
            expected_report_sha256=expected_intake_sha256, **originals)
        _corpus_need(_corpus_wire(checked) == offered_snapshot,
                     "upstream graph intake differs from independently pinned original")
        return checked

    def finish(primary, extra=()):
        _finish_corpus_custody((("closing public graph intake replay", replay),
            ("original and detached inputs", originals_unchanged),
            ("producer sources and callbacks", producers_unchanged),
            *extra, ("post-replay original inputs", originals_unchanged),
            ("post-replay producer sources and callbacks", producers_unchanged)), primary)

    return {"originals": originals, "slots": slots, "pins": pins,
            "replay": replay, "originals_unchanged": originals_unchanged,
            "producers_unchanged": producers_unchanged, "finish": finish}


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


def prepare_coordinate_graph_corpus_v1(intake_report_raw, *, expected_intake_raw_sha256,
        expected_intake_sha256, intake_inputs, expected_intake_inputs_sha256,
        output_inputs, expected_output_inputs_sha256):
    """Retain every graph-v2 output and add only existing candidate custody."""
    state = _coordinate_corpus_setup(intake_report_raw,
        expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
        intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
        output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256)
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
                candidate_raw = _corpus_wire(candidate)
                checked = validate_proposed_graph_candidate(candidate, **arguments)
                _corpus_need(_corpus_wire(candidate) == candidate_raw == _corpus_wire(checked),
                             "existing candidate changed during genuine custody validation")
            rows.append({**identity, "intake_output": _corpus_copy(upstream), "candidate": candidate,
                "disposition": "candidate_corpus_custody" if candidate is not None else "unresolved",
                "custody_issues": issues, "selected_occurrence": None, "source_binding_mask": 0,
                "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
                "entity_binding": "unavailable_semantic_companions_not_supplied", "consumer_eligible": False,
                "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(_CORPUS_AUTHORITY)})
        report = {"schema": COORDINATE_CORPUS_SCHEMA, "source_compatibility_profile": COORDINATE_CORPUS_PROFILE,
            "intake_report_raw_utf8": intake_report_raw.decode("utf-8"),
            "intake_report_raw_sha256": expected_intake_raw_sha256,
            "intake_report_sha256": expected_intake_sha256,
            "intake_inputs_sha256": expected_intake_inputs_sha256,
            "output_inputs_sha256": expected_output_inputs_sha256,
            "physical_rows": _corpus_copy(intake["physical_rows"]),
            "row_references": _corpus_copy(intake["row_references"]), "output_occurrences": rows,
            "population_complete": True, "coverage_scope": "complete_supplied_graph_v2_physical_reference_and_output_population_only",
            "proposal_bytes_recipe": "canonical_dag_json_bytes_of_genuinely_replayed_graph/v1",
            "original_input_retention": "complete_external_originals_required_for_every_replay",
            "upstream_reexecution_performed": True,
            "upstream_reexecution_requirement": "opening_and_closing_public_graph_v2_original_input_replay",
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
        report_raw = _corpus_wire(report)
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"](primary)
    _corpus_need(_corpus_wire(report) == report_raw, "detached corpus report changed during closing replay")
    return _corpus_read(report_raw, MAX_COORDINATE_CORPUS_BYTES, "coordinate graph corpus")


def _corpus_offered_report(report, expected_report_sha256):
    require_sha256(expected_report_sha256, "coordinate corpus report")
    raw = report if type(report) is bytes else _corpus_wire(report)
    offered = _corpus_read(raw, MAX_COORDINATE_CORPUS_BYTES, "offered coordinate corpus report")
    _corpus_need(type(offered) is dict and offered.get("schema") == COORDINATE_CORPUS_SCHEMA
                 and offered.get("source_compatibility_profile") == COORDINATE_CORPUS_PROFILE,
                 "explicit graph-v2 coordinate corpus profile required")
    snapshot = _corpus_wire(offered)
    _corpus_need(_corpus_sha(snapshot) == expected_report_sha256, "coordinate corpus report pin differs")
    return offered, snapshot


def validate_coordinate_graph_corpus_v1(report, intake_report_raw, *, expected_report_sha256,
        expected_intake_raw_sha256, expected_intake_sha256, intake_inputs,
        expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    """Regenerate the complete corpus report from independently retained inputs."""
    offered, snapshot = _corpus_offered_report(report, expected_report_sha256)
    intake, eligibility, exchange, pins = _coordinate_corpus_owners()
    callbacks = _coordinate_corpus_callbacks(intake, eligibility, exchange)
    primary = None
    try:
        expected = prepare_coordinate_graph_corpus_v1(intake_report_raw,
            expected_intake_raw_sha256=expected_intake_raw_sha256, expected_intake_sha256=expected_intake_sha256,
            intake_inputs=intake_inputs, expected_intake_inputs_sha256=expected_intake_inputs_sha256,
            output_inputs=output_inputs, expected_output_inputs_sha256=expected_output_inputs_sha256)
        _corpus_need(_corpus_wire(expected) == snapshot,
                     "coordinate corpus report differs from complete original-input replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            current = (_corpus_read(report, MAX_COORDINATE_CORPUS_BYTES, "offered corpus report")
                       if type(report) is bytes else report)
            _corpus_need(_corpus_wire(current) == snapshot, "offered corpus report changed during validation")

        def producers_unchanged():
            _corpus_need(_coordinate_corpus_owners()[-1] == pins
                         and all(left is right for left, right in zip(
                             _coordinate_corpus_callbacks(intake, eligibility, exchange), callbacks)),
                         "coordinate corpus validation sources or callbacks changed")
        _finish_corpus_custody((("offered corpus report", offered_unchanged),
                               ("validation sources and callbacks", producers_unchanged)), primary)


def export_coordinate_graph_corpus_output_v1(report, output_occurrence_ordinal, output_directory,
        intake_report_raw, *, expected_report_sha256, expected_intake_raw_sha256, expected_intake_sha256,
        intake_inputs, expected_intake_inputs_sha256, output_inputs, expected_output_inputs_sha256):
    """Export one explicitly selected candidate after full-population validation.

    The existing writer performs its own genuine load/readback. A late custody
    failure raises while retaining written artifacts; it supplies no qualified
    export receipt and does not delete or repair the failed output directory.
    """
    _corpus_need(type(output_occurrence_ordinal) is int and 0 <= output_occurrence_ordinal < MAX_COORDINATE_CORPUS_OUTPUTS,
                 "explicit integer output occurrence ordinal required")
    offered, snapshot = _corpus_offered_report(report, expected_report_sha256)
    arguments = {"expected_intake_raw_sha256": expected_intake_raw_sha256,
        "expected_intake_sha256": expected_intake_sha256, "intake_inputs": intake_inputs,
        "expected_intake_inputs_sha256": expected_intake_inputs_sha256,
        "output_inputs": output_inputs, "expected_output_inputs_sha256": expected_output_inputs_sha256}
    state = _coordinate_corpus_setup(intake_report_raw, **arguments)
    primary, checked, checked_raw, receipt, receipt_raw = None, None, None, None, None

    def reports_unchanged():
        current = (_corpus_read(report, MAX_COORDINATE_CORPUS_BYTES, "offered corpus export report")
                   if type(report) is bytes else report)
        _corpus_need(_corpus_wire(current) == snapshot, "offered corpus report changed during export")
        if checked is not None:
            _corpus_need(_corpus_wire(checked) == checked_raw, "validated corpus report changed during export")

    try:
        checked = validate_coordinate_graph_corpus_v1(report, intake_report_raw,
            expected_report_sha256=expected_report_sha256, **arguments)
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
        _corpus_need(manifest["snapshot_cid"] == row["candidate"]["graph"]["record_cid"],
                     "existing graph export manifest names a different candidate snapshot")
        receipt = {"schema": COORDINATE_CORPUS_EXPORT_SCHEMA,
            "source_compatibility_profile": COORDINATE_CORPUS_PROFILE,
            "corpus_report_sha256": expected_report_sha256,
            **{key: row[key] for key in _CORPUS_IDENTITY_FIELDS},
            "candidate_record_cid": row["candidate"]["record_cid"], "graph_manifest": manifest,
            "graph_manifest_sha256": _corpus_sha(canonical_dag_json_bytes(manifest)),
            "snapshot_cid": manifest["snapshot_cid"], "delegated_writer_readback_performed": True,
            "full_candidate_retained_separately_required": True,
            "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
            "selected_occurrence": None, "source_binding_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": dict(_CORPUS_AUTHORITY), "atomic_snapshot_verified": False}
        receipt_raw = _corpus_wire(receipt)
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"](primary, (("offered and validated corpus report", reports_unchanged),))
    _corpus_need(_corpus_wire(receipt) == receipt_raw, "export receipt changed during closing custody")
    return _corpus_read(receipt_raw, MAX_COORDINATE_CORPUS_BYTES, "coordinate corpus output export")


__all__ += ["COORDINATE_CORPUS_SCHEMA", "COORDINATE_CORPUS_PROFILE", "COORDINATE_CORPUS_EXPORT_SCHEMA",
    "coordinate_graph_corpus_originals_sha256", "coordinate_graph_corpus_inputs_sha256",
    "coordinate_graph_corpus_sha256", "prepare_coordinate_graph_corpus_v1",
    "validate_coordinate_graph_corpus_v1", "export_coordinate_graph_corpus_output_v1"]
