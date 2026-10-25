"""Candidate graph custody for replayed exact term/definition nominations.

The complete original evidence remains external. Typed use occurrences and
source references are distinct; no semantic role, alias, governing definition,
review authority or new signature is inferred by this projection.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils

from . import corpus_contracts as contracts
from . import corpus_graph as graphs

SCHEMA = "legal-corpus-norm-definition-graph/v1"
PROFILE = "exact-term-definition-nomination-custody/v1"
REPORT_SCHEMA = "legal-corpus-norm-definition-report-reference/v1"
NORM_SCHEMA = "legal-corpus-norm-definition-norm-reference/v1"
DEFINITION_SCHEMA = "legal-corpus-norm-definition-alternative-reference/v1"
USE_SCHEMA = "legal-corpus-norm-definition-typed-use/v1"
SOURCE_SCHEMA = "legal-corpus-norm-definition-source-reference/v1"
NOMINATION_SCHEMA = "legal-corpus-norm-definition-nomination/v1"
FALSE_FLAGS = dict.fromkeys((
    "admitted", "formalized", "source_semantics_verified", "source_authenticity_verified",
    "definition_applicability_verified", "definition_substitution_verified",
    "external_definition_resolution_verified", "context_closure_verified",
    "independently_reviewed", "training_qualified", "proof_authority",
    "original_signatures_cover_projection", "all_norm_term_uses_enumerated",
    "native_ast_rewritten", "backend_executed", "lean_compilation_verified",
), False)
FIELDS = {"profile", "report_record", "norm_record", "definition_records", "use_records",
    "source_records", "nomination_records", "graph", "counts", "producer_pins", "view",
    "authority", "training_mask", "evaluation_gold_mask", "selected_interpretation",
    "governing_definition_use", "external_complete_inputs_required"}
_SELF_PATH = Path(__file__).resolve()
_PURE_MODULES = (contracts, graphs, cid_utils)


def _pure_pins():
    paths = (_SELF_PATH, *(Path(module.__file__).resolve() for module in _PURE_MODULES))
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


_IMPORTED_PINS = _pure_pins()


def _need(condition, message):
    if not condition:
        raise contracts.CorpusContractError(message)


def _check_pure():
    _need(_pure_pins() == _IMPORTED_PINS, "norm definition graph producers changed since import")
    return dict(_IMPORTED_PINS)


def _owner():
    # Public evidence owners perform pure preflight before loading native and
    # source operations. Importing this adapter itself never loads them.
    from . import legal_norm_definition_evidence_v1
    return legal_norm_definition_evidence_v1


def _producer_pins(owner):
    result = _check_pure()
    observed = owner._pins(owner._owners())
    for path, value in observed.items():
        _need(path not in result or result[path] == value, "projection producer observations disagree")
        result[path] = value
    return result


def _ref(value, owner):
    result = {"sha256": owner.norm_definition_evidence_sha256(value)}
    if type(value) is dict:
        for key in ("schema", "record_cid"):
            if key in value:
                result[key] = value[key]
    return result


def norm_definition_graph_sha256(record):
    """Hash the complete bounded canonical projection, not only its graph."""
    value = contracts.clone_json(record)
    return hashlib.sha256(cid_utils.canonical_dag_json_bytes(value)).hexdigest()


def _preflight(report, args, kwargs, expected_report_sha256):
    _check_pure()
    contracts.require_sha256(expected_report_sha256, "expected_report_sha256")
    owner = _owner()
    _need(owner.norm_definition_evidence_sha256(report) == expected_report_sha256,
          "independent norm definition evidence report pin differs")
    original = {"report": report, "args": list(args), "kwargs": kwargs}
    # Reuse the existing aggregate snapshot for complete raw bytes and plain
    # records. The graph adds no allowance per endpoint and truncates nothing.
    detached, commitment = owner._snapshot(original)
    bound = inspect.signature(owner.prepare_norm_definition_evidence_v1).bind(
        *detached["args"], **detached["kwargs"])
    inputs = bound.arguments
    # Invoke the same pure input contracts before loading operation owners.
    owner._preflight({key: inputs[key] for key in (
        "norm_preparation", "request_raw", "norm_inputs", "definitions")},
        inputs["expected_norm_preparation_sha256"], inputs["expected_request_sha256"])
    return owner, original, detached, commitment


def _project(report, expected_report_sha256, producers, owner):
    """Pure projection only; its caller must perform complete evidence replay."""
    _need(report["schema"] == owner.SCHEMA and report["profile"] == owner.PROFILE,
          "exact existing definition evidence profile required")
    _need(report["selected_interpretation"] is None and report["governing_definition_use"] is None
          and report["native_ast_rewritten"] is False
          and all(value is False for value in report["authority"].values()),
          "nomination evidence cannot confer semantic authority")
    _need(type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
          "nomination evidence cannot confer training authority")
    seal = contracts.seal_record
    report_record = seal({"schema": REPORT_SCHEMA,
        "original_schema": report["schema"], "original_profile": report["profile"],
        "report_sha256": expected_report_sha256, "request_raw_sha256": report["request_raw_sha256"],
        "report_counts": report["counts"], "external_complete_inputs_required": True})
    norm_record = seal({"schema": NORM_SCHEMA,
        "norm_preparation_sha256": report["norm_preparation_sha256"],
        "norm_correspondence_sha256": report["norm_correspondence_sha256"],
        "norm_scope_id": report["norm_scope_id"], "norm_ast_sha256": report["norm_ast_sha256"],
        "norm_native_ast_sha256": report["norm_native_ast_sha256"],
        "source_context_ref": _ref(report["source_context"], owner),
        "original_unresolved_ref": _ref(report["original_unresolved"], owner),
        "original_context_slots_ref": _ref(report["original_context_slots"], owner),
        "norm_obligations_ref": _ref(report["norm_obligations"], owner),
        "report_record_cid": report_record["record_cid"]})
    definitions, definitions_by_id = [], {}
    for ordinal, endpoint in enumerate(report["definitions"]):
        alternative = endpoint["alternative_id"]
        _need(alternative not in definitions_by_id, "duplicate definition alternative identity")
        evidence = endpoint["review_evidence"]
        assessment = evidence["assessment"]
        record = seal({"schema": DEFINITION_SCHEMA, "ordinal": ordinal,
            "alternative_id": alternative, "endpoint_ref": _ref(endpoint, owner),
            "correspondence_sha256": endpoint["correspondence_sha256"],
            "binding_sha256": endpoint["binding_sha256"], "subject_sha256": endpoint["subject_sha256"],
            "candidate_pin": endpoint["candidate_pin"], "candidate_cid": endpoint["candidate_cid"],
            "family": endpoint["family"], "source_identity": endpoint["source_identity"],
            "source_version_ref": _ref(endpoint["source_version"], owner),
            "scope_record_ref": _ref(endpoint["scope_record"], owner),
            "definition_record_ref": _ref(endpoint["definition_record"], owner),
            "term_record_ref": _ref(endpoint["term_record"], owner),
            "ast_record_ref": _ref(endpoint["ast_record"], owner),
            "source_bindings_ref": _ref(endpoint["source_bindings"], owner),
            "source_occurrence_refs": [_ref(row, owner) for row in endpoint["source_occurrences"]],
            "review_evidence_ref": _ref(evidence, owner), "original_review_status": evidence["status"],
            "original_assessment_sha256": evidence["assessment_sha256"],
            "original_assessment_evaluation_time_utc": (
                None if assessment is None else assessment.get("evaluation_time_utc")),
            "original_review_covers_projection": False,
            "report_record_cid": report_record["record_cid"]})
        definitions.append(record)
        definitions_by_id[alternative] = record
    uses, uses_by_path, sources, sources_by_digest, nominations = [], {}, [], {}, []

    def source_ref(kind, value):
        body = {"reference_kind": kind, "reference": value}
        key = owner.norm_definition_evidence_sha256(body)
        if key not in sources_by_digest:
            record = seal({"schema": SOURCE_SCHEMA, "ordinal": len(sources), **body,
                "reference_sha256": owner.norm_definition_evidence_sha256(value),
                "custody_only": True})
            sources.append(record)
            sources_by_digest[key] = record
        return sources_by_digest[key]

    for ordinal, link in enumerate(report["links"]):
        request = link["request_link"]
        path = request["target"]["typed_path"]
        body = {"target": request["target"], "typed_node": link["typed_node"],
            "typed_context": link["typed_context"], "typed_row": link["typed_row"],
            "source_paths": request["source_paths"], "source_rows": link["source_rows"],
            "norm_source_target": link["norm_source_target"],
            "norm_record_cid": norm_record["record_cid"]}
        if path not in uses_by_path:
            record = seal({"schema": USE_SCHEMA, "ordinal": len(uses), **body})
            uses.append(record)
            uses_by_path[path] = record
        use = uses_by_path[path]
        _need(all(cid_utils.canonical_dag_json_bytes(use[key]) == cid_utils.canonical_dag_json_bytes(value)
                  for key, value in body.items()), "one typed path has conflicting complete occurrence evidence")
        target_source = source_ref("norm_source_target", link["norm_source_target"])
        support_source = source_ref("required_definition_subject", link["required_definition_subject"])
        alternative = definitions_by_id[request["alternative_id"]]
        nominations.append(seal({"schema": NOMINATION_SCHEMA, "ordinal": ordinal,
            "link_ref": _ref(link, owner), "request_link": request,
            "use_record_cid": use["record_cid"], "definition_record_cid": alternative["record_cid"],
            "norm_source_record_cid": target_source["record_cid"],
            "support_source_record_cid": support_source["record_cid"],
            "nomination": link["nomination"], "definition_support": link["definition_support"],
            "definition_term_ref": link["definition_term_ref"],
            "definition_ast_ref": link["definition_ast_ref"],
            "status": link["status"], "governing_definition_use": None}))
    _need(len(definitions) == report["counts"]["alternatives"]
          and len(uses) == report["counts"]["distinct_typed_uses"]
          and len(nominations) == report["counts"]["links"], "complete projection population differs")
    nodes, nodes_by_companion = [], {}

    def node(record, kind="interpretation"):
        # Source references remain opaque provenance assertions, never invented
        # corpus_source occurrences. Alternatives are not globally exclusive.
        value = graphs.build_node(node_type=kind, stable_id=record["record_cid"],
                                  content_cid=record["record_cid"])
        nodes.append(value)
        nodes_by_companion[record["record_cid"]] = value["record_cid"]

    node(report_record)
    node(norm_record)
    for record in definitions:
        node(record)
    for record in uses:
        node(record, "expression")
    for record in sources:
        node(record)
    for record in nominations:
        node(record)
    edges = []

    def edge(source_cid, target_cid, relation, evidence_cid, ordinal=None):
        edges.append(graphs.build_edge(src_cid=nodes_by_companion[source_cid],
            dst_cid=nodes_by_companion[target_cid], relation=relation,
            evidence_cids=[evidence_cid], ordinal=ordinal))

    for record in [norm_record, *definitions, *sources]:
        edge(record["record_cid"], report_record["record_cid"], "DERIVED_FROM", record["record_cid"])
    for record in uses:
        edge(record["record_cid"], norm_record["record_cid"], "DERIVED_FROM", record["record_cid"])
    for record in nominations:
        identity = record["record_cid"]
        for field, relation in (("use_record_cid", "DERIVED_FROM"), ("definition_record_cid", "CITES"),
                               ("norm_source_record_cid", "HAS_SOURCE"),
                               ("support_source_record_cid", "HAS_SOURCE")):
            edge(identity, record[field], relation, identity, record["ordinal"])
    return seal({"schema": SCHEMA, "profile": PROFILE, "report_record": report_record,
        "norm_record": norm_record, "definition_records": definitions, "use_records": uses,
        "source_records": sources, "nomination_records": nominations,
        "graph": graphs.build_graph_snapshot(nodes, edges),
        "counts": {"alternatives": len(definitions), "typed_uses": len(uses),
                   "source_references": len(sources), "nominations": len(nominations)},
        "producer_pins": producers, "view": "candidate", "authority": dict(FALSE_FLAGS),
        "training_mask": 0, "evaluation_gold_mask": 0, "selected_interpretation": None,
        "governing_definition_use": None, "external_complete_inputs_required": True})


def _build(report, args, kwargs, expected_report_sha256, offered=None):
    owner, original, detached, commitment = _preflight(report, args, kwargs, expected_report_sha256)
    # Pure projection precheck catches altered/resealed custody before costly
    # upstream replay. This check never substitutes for that replay on success.
    if offered is not None:
        projected = _project(detached["report"], expected_report_sha256, offered["producer_pins"], owner)
        _need(cid_utils.canonical_dag_json_bytes(projected) == cid_utils.canonical_dag_json_bytes(offered),
              "graph projection differs from independently committed report")
    producers = _producer_pins(owner)

    def fence():
        _need(owner._snapshot(original)[1] == commitment and owner._snapshot(detached)[1] == commitment,
              "norm definition graph inputs changed during replay")
        _need(_producer_pins(owner) == producers, "norm definition graph producers changed during replay")

    fence()
    checked = owner.validate_norm_definition_evidence_v1(detached["report"], *detached["args"],
        expected_report_sha256=expected_report_sha256, **detached["kwargs"])
    fence()
    result = _project(checked, expected_report_sha256, producers, owner)
    fence()
    return result


def build_norm_definition_graph_v1(report, *args, expected_report_sha256, **kwargs):
    """Replay all original evidence, then project candidate custody only."""
    return _build(report, args, kwargs, expected_report_sha256)


def validate_norm_definition_graph_v1(record, report, *args, expected_graph_sha256,
                                    expected_report_sha256, **kwargs):
    """Check independent full projection identity and exact complete replay."""
    _check_pure()
    contracts.require_sha256(expected_graph_sha256, "expected_graph_sha256")
    checked = contracts.validate_record(record, schema=SCHEMA, fields=FIELDS)
    _need(norm_definition_graph_sha256(checked) == expected_graph_sha256,
          "independent complete norm definition graph pin differs")
    expected = _build(report, args, kwargs, expected_report_sha256, offered=checked)
    _need(norm_definition_graph_sha256(record) == expected_graph_sha256,
          "offered norm definition graph changed during replay")
    _need(cid_utils.canonical_dag_json_bytes(checked) == cid_utils.canonical_dag_json_bytes(expected),
          "norm definition graph differs from complete regeneration")
    return expected


def export_norm_definition_graph_v1(record, output_directory, report, *args,
                                  expected_graph_sha256, expected_report_sha256, **kwargs):
    """Export graph envelopes after replay; retain full companions separately."""
    checked = validate_norm_definition_graph_v1(record, report, *args,
        expected_graph_sha256=expected_graph_sha256, expected_report_sha256=expected_report_sha256, **kwargs)
    from . import corpus_graph_exchange as exchange
    path = Path(exchange.__file__).resolve()
    producer = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = exchange.write_graph_bundle(checked["graph"], output_directory)
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == producer,
          "graph exchange producer changed during export")
    _check_pure()
    return manifest


__all__ = ["SCHEMA", "PROFILE", "FALSE_FLAGS", "norm_definition_graph_sha256",
    "build_norm_definition_graph_v1", "validate_norm_definition_graph_v1", "export_norm_definition_graph_v1"]


# Explicit parent-literal nominations retain a different endpoint and context
# contract. The original HTML/contextual projection above is unchanged.
PARENT_SCHEMA = "legal-corpus-parent-norm-definition-graph/v1"
PARENT_PROFILE = "parent-literal-term-definition-nomination-custody/v1"
PARENT_NORM_SCHEMA = "legal-corpus-parent-norm-definition-norm-reference/v1"
PARENT_DEFINITION_SCHEMA = "legal-corpus-parent-norm-definition-alternative-reference/v1"
PARENT_USE_SCHEMA = "legal-corpus-parent-norm-definition-typed-use/v1"
PARENT_NOMINATION_SCHEMA = "legal-corpus-parent-norm-definition-nomination/v1"
PARENT_FIELDS = FIELDS | {"semantic_mask", "consumer_mask"}
_PARENT_GRAPH_PINS = None


def _parent_graph_preflight(report, args, kwargs, expected_report_sha256):
    """Check closed original parent inputs before discovering operation owners."""
    _check_pure()
    contracts.require_sha256(expected_report_sha256, "expected_report_sha256")
    owner = _owner()
    _need(owner.norm_definition_evidence_sha256(report) == expected_report_sha256,
          "independent complete parent nomination report pin differs")
    original = {"report": report, "args": list(args), "kwargs": kwargs}
    detached, commitment = owner._parent_definition_snapshot(original)
    try:
        bound = inspect.signature(owner.prepare_parent_norm_definition_evidence_v1).bind(
            *detached["args"], **detached["kwargs"])
    except TypeError as error:
        raise contracts.CorpusContractError("closed original parent nomination inputs required") from error
    parent_inputs = dict(bound.arguments, offered=detached["report"],
        expected_report_sha256=expected_report_sha256, validating=True)
    # This is the genuine upstream pure input preflight. It binds every raw
    # request/candidate/report and both original populations without replay.
    checked, parent_commitment, parsed = owner._parent_definition_preflight(parent_inputs)
    return owner, original, detached, commitment, parent_inputs, checked, parent_commitment, parsed


def _parent_graph_pins(owner, owners):
    global _PARENT_GRAPH_PINS
    result = _check_pure()
    owner._merge(result, owner._parent_definition_pins(owners))
    if _PARENT_GRAPH_PINS is None:
        _PARENT_GRAPH_PINS = dict(result)
    _need(result == _PARENT_GRAPH_PINS, "parent nomination graph producers changed since first use")
    return result


def _parent_graph_callbacks(owner, owners):
    functions = (_parent_graph_preflight, _parent_graph_pins, _parent_graph_callbacks,
        _parent_graph_runtime, _project_parent, _parent_graph_operation,
        _parent_graph_serialized_fence, build_parent_norm_definition_graph_v1,
        validate_parent_norm_definition_graph_v1, export_parent_norm_definition_graph_v1,
        _need, _check_pure, _pure_pins, _owner, _ref, norm_definition_graph_sha256,
        contracts.clone_json, contracts.seal_record, contracts.validate_record,
        graphs.build_node, graphs.validate_node, graphs.build_edge, graphs.validate_edge,
        graphs.build_graph_snapshot, graphs._validate_snapshot_parts,
        cid_utils.canonical_dag_json_bytes)
    return owner._parent_definition_callbacks(owners) + tuple(
        (function, getattr(function, "__code__", None),
         id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
        for function in functions)


def _parent_graph_runtime(owner, owners):
    return {"schema": PARENT_SCHEMA, "profile": PARENT_PROFILE,
        "companion_schemas": [REPORT_SCHEMA, PARENT_NORM_SCHEMA, PARENT_DEFINITION_SCHEMA,
                              PARENT_USE_SCHEMA, SOURCE_SCHEMA, PARENT_NOMINATION_SCHEMA],
        "fields": sorted(PARENT_FIELDS), "authority": dict(FALSE_FLAGS),
        "record_limits": [contracts.MAX_RECORD_BYTES, contracts.MAX_JSON_DEPTH,
                          contracts.MAX_JSON_NODES],
        "graph_limits": [graphs.MAX_NODES, graphs.MAX_EDGES],
        "graph_node_types": sorted(graphs.NODE_TYPES), "graph_relations": sorted(graphs.RELATIONS),
        "upstream": owner._parent_definition_runtime(owners)}


def _project_parent(report, expected_report_sha256, producers, owner):
    """Thin candidate custody; full report and all replay inputs stay external."""
    _need(report["schema"] == owner.PARENT_SCHEMA and report["profile"] == owner.PARENT_PROFILE,
          "explicit complete parent nomination profile required")
    _need(report["selected_interpretation"] is None and report["governing_definition_use"] is None
          and report["native_ast_rewritten"] is False
          and all(value is False for value in report["authority"].values()),
          "parent nominations cannot confer semantic authority")
    _need(all(type(report[key]) is int and report[key] == 0 for key in
              ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask")),
          "parent nominations require integer-zero masks")
    seal = contracts.seal_record
    report_record = seal({"schema": REPORT_SCHEMA,
        "original_schema": report["schema"], "original_profile": report["profile"],
        "report_sha256": expected_report_sha256, "request_raw_sha256": report["request_raw_sha256"],
        "request_ref": _ref(report["request"], owner), "report_counts": report["counts"],
        "external_complete_inputs_required": True})
    sources, sources_by_digest = [], {}

    def source_ref(kind, value):
        # The complete parent report supplies original bodies. A hash of a
        # context JSON is a reference to that JSON, never an original byte hash.
        reference = _ref(value, owner)
        body = {"reference_kind": kind, "reference": reference}
        key = owner.norm_definition_evidence_sha256(body)
        if key not in sources_by_digest:
            record = seal({"schema": SOURCE_SCHEMA, "ordinal": len(sources), **body,
                "reference_sha256": reference["sha256"], "custody_only": True})
            sources.append(record)
            sources_by_digest[key] = record
        return sources_by_digest[key]

    preparation = report["norm_preparation"]
    correspondence = preparation["correspondence"]
    norm_source = source_ref("norm_parent_source_binding",
        correspondence["source_scope"]["parent_source_binding"])
    norm_context = source_ref("norm_original_parent_context", preparation["original_parent_context"])
    norm_record = seal({"schema": PARENT_NORM_SCHEMA,
        "norm_preparation_sha256": report["norm_preparation_sha256"],
        "preparation_ref": _ref(preparation, owner),
        "correspondence_ref": _ref(correspondence, owner),
        "norm_correspondence_sha256": preparation["correspondence_sha256"],
        "norm_ast_sha256": preparation["ast_sha256"],
        "norm_native_ast_sha256": preparation["native_ast_sha256"],
        "source_identity": preparation["source_identity"],
        "source_identity_ref": _ref(preparation["source_identity"], owner),
        "source_binding_ref": _ref(correspondence["source_scope"]["parent_source_binding"], owner),
        "original_parent_context_ref": _ref(preparation["original_parent_context"], owner),
        "obligations_ref": _ref(preparation["obligations"], owner),
        "context_obligation_ids_ref": _ref(preparation["context_obligation_ids"], owner),
        "typed_context_inventory_ref": _ref(preparation["typed_context_inventory"], owner),
        "source_rows_ref": _ref(preparation["source_rows"], owner),
        "parent_source_record_cid": norm_source["record_cid"],
        "context_record_cid": norm_context["record_cid"],
        "report_record_cid": report_record["record_cid"]})
    definitions, definitions_by_id = [], {}
    for ordinal, endpoint in enumerate(report["definitions"]):
        alternative = endpoint["alternative_id"]
        _need(alternative not in definitions_by_id, "duplicate parent definition alternative identity")
        checked, candidate = endpoint["preparation"], endpoint["candidate"]
        parent_source = source_ref("definition_parent_source_binding", checked["parent_source_binding"])
        occurrence_sources = [source_ref("definition_source_occurrence", row)
                              for row in checked["source_occurrences"]]
        context_sources = [source_ref("definition_context", row) for row in checked["contexts"]]
        record = seal({"schema": PARENT_DEFINITION_SCHEMA, "ordinal": ordinal,
            "alternative_id": alternative, "endpoint_ref": _ref(endpoint, owner),
            "preparation_sha256": endpoint["preparation_sha256"],
            "preparation_ref": _ref(checked, owner), "candidate_ref": _ref(candidate, owner),
            "candidate_pin": checked["candidate_pin"], "family": checked["family"],
            "profile": checked["profile"], "source_version_ref": _ref(checked["source_version"], owner),
            "source_occurrence_refs": [_ref(row, owner) for row in checked["source_occurrences"]],
            "source_bindings_ref": _ref(checked["source_bindings"], owner),
            "parent_source_binding_ref": _ref(checked["parent_source_binding"], owner),
            "contexts_ref": _ref(checked["contexts"], owner),
            "context_refs": [_ref(row, owner) for row in checked["contexts"]],
            "expected_context_population_ref": _ref(checked["expected_context_population"], owner),
            "context_slot_ids_ref": _ref(checked["context_slot_ids"], owner),
            "term_record_ref": _ref(candidate["term_record"], owner),
            "ast_record_ref": _ref(candidate["ast_record"], owner),
            "definition_record_ref": _ref(candidate["definition_record"], owner),
            "scope_record_ref": _ref(candidate["scope_record"], owner),
            "definition_term_ref": endpoint["definition_term_ref"],
            "definition_ast_ref": endpoint["definition_ast_ref"],
            "source_occurrence_record_cids": [row["record_cid"] for row in occurrence_sources],
            "context_record_cids": [row["record_cid"] for row in context_sources],
            "parent_source_record_cid": parent_source["record_cid"],
            "original_review_covers_projection": False,
            "report_record_cid": report_record["record_cid"]})
        definitions.append(record)
        definitions_by_id[alternative] = record
    uses, uses_by_path, nominations = [], {}, []
    for ordinal, link in enumerate(report["links"]):
        request = link["request_link"]
        path = request["target"]["typed_path"]
        body = {"target": request["target"], "typed_node": link["typed_node"],
            "typed_context": link["typed_context"], "typed_row": link["typed_row"],
            "source_paths": request["source_paths"], "source_rows": link["source_rows"],
            "norm_record_cid": norm_record["record_cid"]}
        if path not in uses_by_path:
            record = seal({"schema": PARENT_USE_SCHEMA, "ordinal": len(uses), **body})
            uses.append(record)
            uses_by_path[path] = record
        use = uses_by_path[path]
        _need(all(cid_utils.canonical_dag_json_bytes(use[key]) == cid_utils.canonical_dag_json_bytes(value)
                  for key, value in body.items()), "parent typed path has conflicting complete occurrence evidence")
        source_rows = [source_ref("norm_source_row", row) for row in link["source_rows"]]
        alternative = definitions_by_id[request["alternative_id"]]
        nominations.append(seal({"schema": PARENT_NOMINATION_SCHEMA, "ordinal": ordinal,
            "link_ref": _ref(link, owner), "request_link": request,
            "use_record_cid": use["record_cid"], "definition_record_cid": alternative["record_cid"],
            "norm_source_record_cids": [row["record_cid"] for row in source_rows],
            "definition_source_record_cids": alternative["source_occurrence_record_cids"],
            "definition_candidate_ref": link["definition_candidate_ref"],
            "definition_term_ref": link["definition_term_ref"],
            "definition_ast_ref": link["definition_ast_ref"],
            "status": link["status"], "governing_definition_use": None}))
    _need(len(definitions) == report["counts"]["alternatives"]
          and len(uses) == report["counts"]["distinct_typed_uses"]
          and len(nominations) == report["counts"]["links"], "complete parent projection population differs")
    nodes, nodes_by_companion, edges = [], {}, []

    def node(record, kind="interpretation"):
        value = graphs.build_node(node_type=kind, stable_id=record["record_cid"],
                                  content_cid=record["record_cid"])
        nodes.append(value)
        nodes_by_companion[record["record_cid"]] = value["record_cid"]

    for record in [report_record, norm_record, *definitions, *sources, *nominations]:
        node(record)
    for record in uses:
        node(record, "expression")

    def edge(source_cid, target_cid, relation, evidence_cid, ordinal=None):
        edges.append(graphs.build_edge(src_cid=nodes_by_companion[source_cid],
            dst_cid=nodes_by_companion[target_cid], relation=relation,
            evidence_cids=[evidence_cid], ordinal=ordinal))

    for record in [norm_record, *definitions, *sources]:
        edge(record["record_cid"], report_record["record_cid"], "DERIVED_FROM", record["record_cid"])
    for source_cid in (norm_record["parent_source_record_cid"], norm_record["context_record_cid"]):
        edge(norm_record["record_cid"], source_cid, "HAS_SOURCE", norm_record["record_cid"])
    for record in definitions:
        identity = record["record_cid"]
        edge(identity, record["parent_source_record_cid"], "HAS_SOURCE", identity)
        for index, source_cid in enumerate(record["source_occurrence_record_cids"]):
            edge(identity, source_cid, "HAS_SOURCE", identity, index)
        for index, source_cid in enumerate(record["context_record_cids"]):
            edge(identity, source_cid, "DERIVED_FROM", identity, index)
    for record in uses:
        edge(record["record_cid"], norm_record["record_cid"], "DERIVED_FROM", record["record_cid"])
    for record in nominations:
        identity = record["record_cid"]
        edge(identity, record["use_record_cid"], "DERIVED_FROM", identity, record["ordinal"])
        edge(identity, record["definition_record_cid"], "CITES", identity, record["ordinal"])
        for index, source_cid in enumerate(record["norm_source_record_cids"]):
            edge(identity, source_cid, "HAS_SOURCE", identity, index)
        for index, source_cid in enumerate(record["definition_source_record_cids"]):
            edge(identity, source_cid, "HAS_SOURCE", identity, index)
    return seal({"schema": PARENT_SCHEMA, "profile": PARENT_PROFILE, "report_record": report_record,
        "norm_record": norm_record, "definition_records": definitions, "use_records": uses,
        "source_records": sources, "nomination_records": nominations,
        "graph": graphs.build_graph_snapshot(nodes, edges),
        "counts": {"alternatives": len(definitions), "typed_uses": len(uses),
            "source_references": len(sources), "nominations": len(nominations),
            "definition_source_occurrences": sum(len(row["source_occurrence_refs"]) for row in definitions),
            "definition_contexts": sum(len(row["context_refs"]) for row in definitions)},
        "producer_pins": producers, "view": "candidate", "authority": dict(FALSE_FLAGS),
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "selected_interpretation": None, "governing_definition_use": None,
        "external_complete_inputs_required": True})


def _parent_graph_serialized_fence(result, serialized, owner):
    _need(owner.norm._parent_review_pure_wire(result) == serialized,
          "parent nomination graph changed after serialization")


def _parent_graph_operation(report, args, kwargs, expected_report_sha256, offered=None):
    (owner, original, detached, commitment, parent_inputs, preflight_inputs,
     parent_commitment, parsed) = _parent_graph_preflight(report, args, kwargs, expected_report_sha256)
    if offered is not None:
        try:
            projected = _project_parent(detached["report"], expected_report_sha256,
                                        offered["producer_pins"], owner)
        except (KeyError, TypeError, IndexError, RecursionError) as error:
            raise contracts.CorpusContractError("malformed parent nomination projection") from error
        _need(cid_utils.canonical_dag_json_bytes(projected) == cid_utils.canonical_dag_json_bytes(offered),
              "parent graph projection differs from independently committed report")
    owners = owner._parent_definition_owners()
    _, lineage, source = owners
    producers = _parent_graph_pins(owner, owners)
    callbacks = _parent_graph_callbacks(owner, owners)
    runtime = owner.norm._parent_review_pure_wire(_parent_graph_runtime(owner, owners))
    parsed_commitment = owner.norm._parent_review_fingerprint(parsed)
    physical, held = [], []
    result = serialized = None
    primary = None

    def fence():
        _need(_parent_graph_callbacks(owner, owners) == callbacks,
              "parent graph replay or projection callbacks changed")
        _need(owner.norm._parent_review_pure_wire(_parent_graph_runtime(owner, owners)) == runtime,
              "parent graph policy or bounds changed")
        _need(_parent_graph_pins(owner, owners) == producers, "parent graph producer source changed")
        _need(owner._parent_definition_snapshot(original)[1] == commitment
              and owner._parent_definition_snapshot(detached)[1] == commitment,
              "parent graph original or detached inputs changed")
        _need(owner.norm._parent_review_fingerprint(parent_inputs) == parent_commitment
              and owner.norm._parent_review_fingerprint(preflight_inputs) == parent_commitment,
              "parent graph preflight inputs changed")
        _need(owner.norm._parent_review_fingerprint(parsed) == parsed_commitment,
              "parent graph parsed original inputs changed")
        for checked, raw in held:
            _need(owner._wire(checked) == raw, "parent graph actual upstream return changed")
        for plan, witness, frozen in physical:
            _need(owner.norm._parent_review_fingerprint(plan) == frozen,
                  "parent graph physical file plan changed")
            _need(owner._parent_definition_file_witness(plan, lineage) == witness,
                  "parent graph physical original file changed")

    def replay():
        checked = owner.validate_parent_norm_definition_evidence_v1(detached["report"],
            *detached["args"], expected_report_sha256=expected_report_sha256, **detached["kwargs"])
        raw = owner._wire(checked)
        held.append((checked, raw))
        _need(hashlib.sha256(raw).hexdigest() == expected_report_sha256,
              "complete parent graph nomination regeneration differs")
        owner._observe(producers, checked["producer_pins"])
        return checked

    def bind_files(replay_inputs):
        fence()
        plan = owner._parent_definition_file_plan(replay_inputs, lineage)
        frozen = owner.norm._parent_review_fingerprint(plan)
        witness = owner._parent_definition_file_witness(plan, lineage)
        physical.append((plan, witness, frozen))
        fence()

    def output_fence():
        if serialized is not None:
            _parent_graph_serialized_fence(result, serialized, owner)
            fence()
            _parent_graph_serialized_fence(result, serialized, owner)

    def terminal_fence():
        fence()
        if serialized is not None:
            _parent_graph_serialized_fence(result, serialized, owner)

    try:
        fence()
        checked = replay()
        bind_files(preflight_inputs["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"])
        for endpoint in preflight_inputs["definitions"]:
            bind_files(endpoint["preparation_inputs"]["parent_inputs"]["replay_inputs"])
        fence()
        result = _project_parent(checked, expected_report_sha256, producers, owner)
        serialized = owner.norm._parent_review_pure_wire(result)
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        # The genuine nomination validator has already closed both original
        # endpoint replays. Keep its returned bodies and physical files fenced
        # through this projection without dispatching the same replay again.
        source._parent_finish((fence, output_fence, terminal_fence), primary)


def build_parent_norm_definition_graph_v1(report, *args, expected_report_sha256, **kwargs):
    """Replay both whole parent populations and project candidate custody only."""
    return _parent_graph_operation(report, args, kwargs, expected_report_sha256)


def validate_parent_norm_definition_graph_v1(record, report, *args,
        expected_graph_sha256, expected_report_sha256, **kwargs):
    """Rebuild the exact independently pinned parent nomination companion."""
    _check_pure()
    contracts.require_sha256(expected_graph_sha256, "expected_graph_sha256")
    checked = contracts.validate_record(record, schema=PARENT_SCHEMA, fields=PARENT_FIELDS)
    _need(norm_definition_graph_sha256(checked) == expected_graph_sha256,
          "independent complete parent nomination graph pin differs")
    expected = _parent_graph_operation(report, args, kwargs, expected_report_sha256, offered=checked)
    _need(norm_definition_graph_sha256(record) == expected_graph_sha256,
          "offered parent nomination graph changed during replay")
    _need(cid_utils.canonical_dag_json_bytes(checked) == cid_utils.canonical_dag_json_bytes(expected),
          "parent nomination graph differs from complete regeneration")
    return expected


def export_parent_norm_definition_graph_v1(record, output_directory, report, *args,
        expected_graph_sha256, expected_report_sha256, **kwargs):
    """Replay then use the existing graph bundle; retain whole inputs externally."""
    checked = validate_parent_norm_definition_graph_v1(record, report, *args,
        expected_graph_sha256=expected_graph_sha256,
        expected_report_sha256=expected_report_sha256, **kwargs)
    from . import corpus_graph_exchange as exchange
    path = Path(exchange.__file__).resolve()
    producer = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = exchange.write_graph_bundle(checked["graph"], output_directory)
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == producer,
          "parent nomination graph exchange producer changed during export")
    _check_pure()
    return manifest


__all__ += ["PARENT_SCHEMA", "PARENT_PROFILE", "build_parent_norm_definition_graph_v1",
    "validate_parent_norm_definition_graph_v1", "export_parent_norm_definition_graph_v1"]
