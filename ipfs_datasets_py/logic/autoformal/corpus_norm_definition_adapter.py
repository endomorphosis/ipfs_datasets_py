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
