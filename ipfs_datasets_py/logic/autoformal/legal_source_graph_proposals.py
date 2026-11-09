"""Complete source/primary-anchor graph proposals and inert review requests.

Primary associations are independently declared transport correspondences. A
source-package ID or corpus checksum is never an official HTML byte hash. Open
context obligations survive even when complete custody permits a review request.
No entity records are merged and no legal or proof authority is established.
"""
from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
import hashlib
import re

from . import legal_graph_dependencies as dependencies
from . import legal_graph_review as review
from . import legal_semantic_graph as graphs
from . import legal_span_cache_intake as intake
from . import legal_span_section_bridge as bridge_owner
from . import legal_statutory_context as contexts

SCHEMA = "legal-source-primary-graph-proposals/v1"
MAX_ROWS = 128
_SHA = re.compile(r"[0-9a-f]{64}\Z")
INPUT_FIELDS = {"record_sha256", "semantic_declarations", "expected_scope_id", "expected_graph_sha256",
    "context_packet", "expected_context_sha256", "context_dependency_requests", "dependency_manifest",
    "expected_manifest_sha256", "required_dependency_ids", "observed_artifact_sha256s", "observed_pins"}
AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified", "context_closure_verified",
    "primary_source_correspondence_verified", "source_package_content_identity_verified",
    "primary_checksum_used_as_html_hash", "authenticated_review_verified", "global_consistency_verified",
    "training_qualified", "proof_authority", "accepted_view_eligible", "entity_records_merged"), False)


class SourceGraphProposalError(ValueError):
    """Independent population, proposal inputs or a complete binding disagrees."""


def _need(ok, message):
    if not ok:
        raise SourceGraphProposalError(message)


def _wire(value):
    return intake._wire(value)


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def proposal_inputs_sha256(row_inputs):
    """Hash the entire explicit per-record input population, including null gaps."""
    _need(type(row_inputs) is list and 0 < len(row_inputs) <= MAX_ROWS, "bounded complete proposal input population required")
    for value in row_inputs:
        _need(type(value) is dict and set(value) == INPUT_FIELDS, "closed explicit proposal input required")
        _need(type(value["record_sha256"]) is str and _SHA.fullmatch(value["record_sha256"]), "exact proposal record pin required")
    return _digest(row_inputs)


def required_primary_artifacts(primary_binding, candidate_section):
    """Declare every exact selected primary anchor/evidence reference for a row.

    The mapping is included as an artifact so a review subject's dependency
    closure binds the explicit source association, not only its target nodes.
    Hashes of primary records address their original record_json UTF8 bytes.
    Recognized release points retain all relationship witnesses as declared
    producer context, without establishing legal applicability or currentness.
    This helper confers no correspondence or governing-context authority.
    """
    _need(type(primary_binding) is dict and type(candidate_section) is dict, "bound primary candidate and mapping required")
    _need(primary_binding["section_entry_cid"] == candidate_section["entry_cid"], "primary section differs from independent mapping")
    packages = [row for row in candidate_section["source_packages"] if row["entry_cid"] == primary_binding["source_package_entry_cid"]]
    _need(len(packages) == 1, "complete literal source-package binding missing or ambiguous")
    package = packages[0]
    rows = [(candidate_section["section_observation"], "declared_primary_section"),
            (package["source_package_observation"], "declared_primary_source_package")]
    _need(package["has_source_observations"], "primary package has no explicit source relationship evidence")
    rows.extend((edge, "declared_HAS_SOURCE_transport_evidence") for edge in package["has_source_observations"])
    release_points = candidate_section.get("release_points", [])
    _need(type(release_points) is list, "complete recognized release-point population required")
    for point in release_points:
        _need(point["has_source_observations"], "primary release point has no explicit source relationship evidence")
        rows.append((point["release_point_observation"], "declared_primary_release_point"))
        rows.extend((edge, "declared_HAS_SOURCE_release_context_evidence") for edge in point["has_source_observations"])
    result, seen = [], set()
    for observation, role in rows:
        identity = observation["declared_identity"]["entry_cid"]
        sha = observation["record_sha256"]
        _need(type(identity) is str and type(sha) is str and _SHA.fullmatch(sha) and identity not in seen,
              "unique exact primary record evidence required")
        seen.add(identity)
        result.append({"artifact_id": identity, "artifact_sha256": sha, "role": role})
    mapping_sha = _digest(primary_binding)
    result.append({"artifact_id": "legal-primary-source-mapping:sha256:" + mapping_sha,
                   "artifact_sha256": mapping_sha, "role": "declared_primary_source_correspondence_only"})
    return result


def _review_request(graph, row, supplied, bridge_inputs, primary_refs):
    for key in ("expected_graph_sha256", "context_packet", "expected_context_sha256", "dependency_manifest",
                "expected_manifest_sha256", "required_dependency_ids", "observed_artifact_sha256s", "observed_pins"):
        _need(supplied[key] is not None, "missing_review_request_input:" + key)
    declaration = bridge_inputs["source_bindings"][row["primary_binding"]["source_span_id"]]
    packet, manifest = supplied["context_packet"], supplied["dependency_manifest"]
    subject = review.build_review_subject(graph, packet, manifest,
        expected_graph_sha256=supplied["expected_graph_sha256"], expected_context_sha256=supplied["expected_context_sha256"],
        expected_manifest_sha256=supplied["expected_manifest_sha256"], document=declaration["document"],
        raw_html=base64.b64decode(declaration["raw_html_base64"], validate=True),
        required_dependency_ids=supplied["required_dependency_ids"],
        context_dependency_requests=supplied["context_dependency_requests"])
    reachable = set(subject["required_dependency_ids"])
    artifacts = {value["artifact_id"]: value["artifact_sha256"] for value in subject["dependency_artifacts"]}
    for ref in primary_refs:
        _need(ref["artifact_id"] in reachable and artifacts.get(ref["artifact_id"]) == ref["artifact_sha256"],
              "required_primary_anchor_or_relationship_omitted_or_changed:" + ref["role"])
    _need(all(value is not None for value in artifacts.values()), "required_dependency_target_missing")
    current = dependencies.invalidate_dependencies(manifest, expected_manifest_sha256=supplied["expected_manifest_sha256"],
        observed_artifact_sha256s=supplied["observed_artifact_sha256s"], observed_pins=supplied["observed_pins"])
    _need(not reachable.intersection(current["stale_artifact_ids"]), "required_dependency_closure_not_current")
    _need(not any(reachable.intersection(cycle) for cycle in current["cycles"]), "required_dependency_cycle_unresolved")
    return {"schema": "legal-source-primary-graph-review-request/v1", "subject": subject,
        "subject_sha256": review.digest(subject), "dependency_invalidation_sha256": current["invalidation_sha256"],
        "context_dependency_slots": deepcopy(packet["dependency_slots"]),
        "status": "custody_complete_review_request_context_obligations_open", "authority": dict(AUTHORITY)}


def _open_context_obligations(status="open_missing_context_packet"):
    return [{"kind": kind, "status": status, "open": True, "attachments": [],
             "semantic_attachment_verified": False} for kind in contexts.DEPENDENCY_KINDS]


def prepare_source_graph_proposals(bridge, rows, *, expected_bridge_sha256, bridge_inputs,
        row_inputs, expected_row_inputs_sha256, expected_record_sha256s):
    """Regenerate the complete trusted bridge and retain every proposal or gap.

    A sidecar per physical record supplies explicit semantic declarations and
    independent graph/scope/context/dependency pins, or explicit null gaps.
    Review subjects are requests about open context, never completed reviews.
    """
    _need(type(expected_bridge_sha256) is str and _SHA.fullmatch(expected_bridge_sha256)
          and type(bridge) is dict and bridge.get("bridge_sha256") == expected_bridge_sha256,
          "independent complete bridge pin differs")
    bridge = bridge_owner.validate_span_section_bridge(bridge, rows, **bridge_inputs)
    _need(proposal_inputs_sha256(row_inputs) == expected_row_inputs_sha256, "independent proposal input population pin differs")
    _need(type(expected_record_sha256s) in (list, tuple)
          and list(expected_record_sha256s) == bridge["expected_record_sha256s"]
          == [value["record_sha256"] for value in row_inputs]
          and len(row_inputs) == bridge["row_count"], "proposal membership, order, multiplicity or physical occurrence differs")
    _wire(bridge)
    result_rows = []
    for original, supplied in zip(bridge["rows"], row_inputs):
        graph = request = None
        primary_refs, primary_links, context_obligations, issues = [], [], _open_context_obligations(), []
        if original["graph_proposal"] is None:
            issues.append({"code": "source_section_bridge_prerequisites_unresolved"})
        else:
            try:
                _need(supplied["semantic_declarations"] is not None, "explicit_semantic_declarations_missing")
                graph_arguments = deepcopy(original["graph_request"])
                _need(supplied["expected_scope_id"] == graph_arguments["scope"]["scope_id"], "independent_scope_pin_missing_or_different")
                graph_arguments["semantic_declarations"] = supplied["semantic_declarations"]
                graph = graphs.build_graph(**graph_arguments)
                expected_graph = supplied["expected_graph_sha256"]
                if expected_graph is not None:
                    _need(type(expected_graph) is str and _SHA.fullmatch(expected_graph)
                          and review.digest(graph) == expected_graph,
                          "independent_graph_pin_malformed_or_different")
                primary_refs = required_primary_artifacts(original["primary_binding"], original["candidate_section"])
                mapping = original["primary_binding"]
                source = graph["source"]
                _need(source["document_revision"] == mapping["document_revision"] and source["view_id"] == mapping["document_view_id"],
                      "exact_source_occurrence_revision_or_view_differs")
                for kind, values, key in (("entity", graph["entities"], "entity_id"), ("assertion", graph["assertions"], "assertion_id")):
                    for value in values:
                        link = {"record_sha256": original["record_sha256"], "proposal_kind": kind,
                            "proposal_id": value[key], "graph_id": graph["graph_id"], "scope_id": graph["scope"]["scope_id"],
                            "source_occurrence_id": source["selector"]["occurrence_id"], "primary_binding": deepcopy(mapping),
                            "status": "declared_unreviewed_primary_transport_anchor", "authority": dict(AUTHORITY)}
                        link["link_sha256"] = _digest(link)
                        primary_links.append(link)
            except (ValueError, KeyError, TypeError) as error:
                graph = None
                primary_refs, primary_links = [], []
                issues.append({"code": "source_scoped_semantic_proposal_unresolved", "message": str(error)[:512]})
        if graph is not None:
            try:
                request = _review_request(graph, original, supplied, bridge_inputs, primary_refs)
                context_obligations = deepcopy(request["context_dependency_slots"])
            except (ValueError, KeyError, TypeError) as error:
                issues.append({"code": "review_request_prerequisites_unresolved", "message": str(error)[:512]})
                if supplied["context_packet"] is not None:
                    # Unverified packet content remains lossless in proposal_input;
                    # it cannot close the explicit obligations displayed here.
                    context_obligations = _open_context_obligations("open_review_request_custody_unresolved")
        result_rows.append({"row_ordinal": original["row_ordinal"], "record_sha256": original["record_sha256"],
            "raw_row_sha256": original["raw_row_sha256"], "proposal_input": deepcopy(supplied),
            "source_scoped_graph": graph, "primary_artifact_refs": primary_refs, "primary_links": primary_links,
            "review_request": request, "context_obligations": context_obligations,
            "open_obligations": {**deepcopy(original["obligations"]),
                "context": "all_v2_dependency_slots_remain_open" if request else "context_or_dependency_custody_unresolved",
                "review": "review_request_only_no_authenticated_review"},
            "issues": issues, "disposition": "review_request_prepared_context_open" if request else
                "proposed_unreviewed_graph_with_open_obligations" if graph else "unresolved", "authority": dict(AUTHORITY)})
    report = {"schema": SCHEMA, "bridge_sha256": expected_bridge_sha256, "bridge": bridge,
        "proposal_inputs_sha256": expected_row_inputs_sha256, "expected_record_sha256s": list(expected_record_sha256s),
        "row_count": len(result_rows), "rows": result_rows,
        "disposition_counts": dict(Counter(value["disposition"] for value in result_rows)),
        "population_complete": True, "coverage_scope": "exact_independently_pinned_supplied_span_rows_only",
        "whole_cache_coverage_verified": False, "complete_section_coverage_verified": False,
        "primary_correspondence_basis": "independently_declared_mapping_only_not_official_source_authentication",
        "original_task_acceptance": "preparatory_subset_only", "authority": dict(AUTHORITY)}
    report["proposals_sha256"] = _digest(report)
    return deepcopy(report)


def validate_source_graph_proposals(report, bridge, rows, **trusted_inputs):
    expected = prepare_source_graph_proposals(bridge, rows, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "source graph proposals differ from independent complete regeneration")
    return expected


__all__ = ["SourceGraphProposalError", "proposal_inputs_sha256", "required_primary_artifacts",
           "prepare_source_graph_proposals", "validate_source_graph_proposals"]


# This separate proposal profile consumes an unchanged, genuinely replayed wire
# graph-v3 population. It does not broaden that graph or coordinate-corpus API.
import json as _semantic_json
import math as _semantic_math
from pathlib import Path as _SemanticPath

COORDINATE_SEMANTIC_REQUEST_SCHEMA = "legal-coordinate-semantic-graph-proposals-request/v1"
COORDINATE_SEMANTIC_SCHEMA = "legal-coordinate-semantic-graph-proposals/v1"
COORDINATE_SEMANTIC_PROFILE = "original-input-wire-coordinate-authored-semantic-proposals/v1"
COORDINATE_SEMANTIC_METADATA_PROFILE = "hf-default-parquet-envelope/v1"
MAX_COORDINATE_SEMANTIC_REQUEST_BYTES = 4 * 1024**2
MAX_COORDINATE_SEMANTIC_GRAPH_BYTES = 64 * 1024**2
MAX_COORDINATE_SEMANTIC_INPUT_BYTES = 128 * 1024**2
MAX_COORDINATE_SEMANTIC_REPORT_BYTES = 128 * 1024**2
MAX_COORDINATE_SEMANTIC_OUTPUTS = 256
_COORDINATE_SEMANTIC_SELF_PIN = hashlib.sha256(_SemanticPath(__file__).read_bytes()).hexdigest()
_COORDINATE_SEMANTIC_PINS = None
_COORDINATE_SEMANTIC_ORIGINAL_FIELDS = {
    "request_raw", "eligibility_report_raw", "eligibility_request_raw", "join_manifest_raw",
    "expected_request_sha256", "join_originals", "source_bindings",
}
_COORDINATE_SEMANTIC_SLOT_FIELDS = {
    "output_occurrence_ordinal", "physical_identity_sha256", "route", "ordinal",
}


def _coordinate_semantic_authority():
    # A fresh literal contract also detects a consistently corrupted public map.
    return dict.fromkeys(("admitted", "formalized", "source_semantics_verified",
        "context_closure_verified", "primary_source_correspondence_verified",
        "source_package_content_identity_verified", "primary_checksum_used_as_html_hash",
        "authenticated_review_verified", "global_consistency_verified", "training_qualified",
        "proof_authority", "accepted_view_eligible", "entity_records_merged",
        "governing_edition_verified", "governing_definition_use_verified",
        "entity_cache_semantics_verified", "Lean_admitted"), False)


def _coordinate_semantic_snapshot(value, *, copy=True):
    """Bound and commit ordinary values plus designated immutable byte inputs.

    This guard uses no JSON encoder. Mapping order is not semantic, while list
    order, multiplicity, byte presentations and scalar types are committed.
    It bounds cooperative custody checks, not process RSS or concurrent writers.
    """
    remaining, nodes, active = MAX_COORDINATE_SEMANTIC_INPUT_BYTES, 200000, set()
    digest = hashlib.sha256()

    def add(tag, raw):
        nonlocal remaining
        remaining -= len(raw) + len(tag) + 9
        _need(remaining >= 0, "complete semantic proposal input byte bound exceeded")
        digest.update(tag + str(len(raw)).encode("ascii") + b":" + raw)

    def visit(item, depth):
        nonlocal nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 48, "bounded semantic proposal graph required")
        kind = type(item)
        if kind in (dict, list):
            identity = id(item)
            _need(identity not in active, "cyclic semantic proposal input refused")
            active.add(identity)
            try:
                if kind is dict:
                    _need(all(type(key) is str for key in item), "plain semantic proposal keys required")
                    add(b"d", str(len(item)).encode("ascii"))
                    result = {} if copy else None
                    for key in sorted(item):
                        visit(key, depth + 1)
                        child = visit(item[key], depth + 1)
                        if copy:
                            result[key] = child
                else:
                    add(b"l", str(len(item)).encode("ascii"))
                    result = [] if copy else None
                    for child in item:
                        observed = visit(child, depth + 1)
                        if copy:
                            result.append(observed)
                return result
            finally:
                active.remove(identity)
        if kind is bytes:
            add(b"b", item)
        elif kind is str:
            _need(len(item) <= MAX_COORDINATE_SEMANTIC_INPUT_BYTES and "\x00" not in item
                  and not any(0xD800 <= ord(char) <= 0xDFFF for char in item),
                  "ordinary bounded UTF8 semantic proposal string required")
            add(b"s", item.encode("utf-8"))
        elif item is None:
            add(b"n", b"")
        elif kind is bool:
            add(b"t", b"1" if item else b"0")
        elif kind is int:
            _need(-(1 << 63) <= item < (1 << 63), "bounded semantic proposal integer required")
            add(b"i", str(item).encode("ascii"))
        elif kind is float:
            _need(_semantic_math.isfinite(item), "finite semantic proposal number required")
            add(b"f", item.hex().encode("ascii"))
        else:
            raise SourceGraphProposalError("plain semantic proposal inputs required")
        return item if copy else None

    detached = visit(value, 0)
    return detached, digest.hexdigest()


def _coordinate_semantic_wire(value, maximum=MAX_COORDINATE_SEMANTIC_REPORT_BYTES):
    from .legal_paired_manifest_inventory_v1 import _wire as ordinary_wire
    return ordinary_wire(value, maximum)


def _coordinate_semantic_read(raw, maximum, label):
    from .legal_paired_manifest_inventory_v1 import _read_json
    return _read_json(raw, maximum, label)


def _coordinate_semantic_finish(checks, primary):
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary semantic proposal custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
        return
    if failures:
        label, error = failures[0]
        error.add_note("semantic proposal closing check: " + label)
        for other_label, other in failures[1:]:
            error.add_note("additional semantic proposal custody failure (" + other_label + "): "
                           + type(other).__name__ + ": " + str(other)[:512])
        raise error


def _coordinate_semantic_owners():
    from . import corpus_proposed_graph_adapter as corpus
    from . import legal_source_span_target_eligibility_v1 as eligibility
    from . import legal_paired_manifest_inventory_v1 as ordinary
    return corpus, intake, eligibility, ordinary, graphs


def _coordinate_semantic_sources(owners):
    root = _SemanticPath(__file__).resolve().parents[3]
    pins = {}
    for module in owners:
        path = _SemanticPath(module.__file__).resolve()
        _need(path == root.joinpath(*module.__name__.split(".")).with_suffix(".py"),
              "semantic proposal owner escaped selected source tree")
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    own = _SemanticPath(__file__).resolve()
    _need(hashlib.sha256(own.read_bytes()).hexdigest() == _COORDINATE_SEMANTIC_SELF_PIN,
          "semantic proposal owner changed since import")
    pins[str(own)] = _COORDINATE_SEMANTIC_SELF_PIN
    observed_eligibility, upstream = intake._coordinate_graph_owners()
    _need(observed_eligibility is owners[2], "semantic proposal eligibility owner differs")
    pins["upstream_graph_owners"] = upstream
    global _COORDINATE_SEMANTIC_PINS
    if _COORDINATE_SEMANTIC_PINS is None:
        _COORDINATE_SEMANTIC_PINS = _coordinate_semantic_snapshot(pins)[0]
    _need(_coordinate_semantic_snapshot(pins)[1]
          == _coordinate_semantic_snapshot(_COORDINATE_SEMANTIC_PINS)[1],
          "semantic proposal owners changed since first use")
    return pins


def _coordinate_semantic_callbacks(owners):
    corpus, upstream, eligibility, ordinary, graph_owner = owners
    return (*upstream._coordinate_graph_callables(eligibility, eligibility_version=4),
        upstream.validate_coordinate_source_graph_intake_v3,
        corpus.coordinate_graph_corpus_originals_sha256, corpus._corpus_intake_inputs,
        corpus._corpus_wire_physical_plan, ordinary._wire, ordinary._read_json, ordinary._pairs,
        graph_owner.build_graph, graph_owner.graph_to_ast, graph_owner.validate_graph,
        graph_owner._semantics, graph_owner._subselector, graph_owner._refs,
        graph_owner._check_bindings, graph_owner._validate_ast, graph_owner._tree,
        _coordinate_semantic_wire, _coordinate_semantic_read, _coordinate_semantic_snapshot,
        _coordinate_semantic_finish, _coordinate_semantic_owners, _coordinate_semantic_sources,
        _coordinate_semantic_callbacks, _coordinate_semantic_authority,
        _coordinate_semantic_slot, _coordinate_semantic_preflight, _coordinate_semantic_unqualified,
        _coordinate_semantic_operation, coordinate_semantic_graph_proposals_originals_sha256,
        coordinate_semantic_graph_proposals_sha256, prepare_coordinate_semantic_graph_proposals_v1,
        validate_coordinate_semantic_graph_proposals_v1, _semantic_json.dumps)


def coordinate_semantic_graph_proposals_originals_sha256(graph_originals):
    """Reuse the existing seven-field original graph-input commitment recipe."""
    _need(type(graph_originals) is dict and set(graph_originals) == _COORDINATE_SEMANTIC_ORIGINAL_FIELDS,
          "complete original wire graph arguments required")
    from . import corpus_proposed_graph_adapter as corpus
    return corpus.coordinate_graph_corpus_originals_sha256(graph_originals)


def coordinate_semantic_graph_proposals_sha256(report):
    """Identity of the complete ordinary report; this hash grants no authority."""
    return hashlib.sha256(_coordinate_semantic_wire(report)).hexdigest()


def _coordinate_semantic_slot(row, ordinal):
    return {"output_occurrence_ordinal": ordinal,
        "physical_identity_sha256": row["physical_identity_sha256"],
        "route": row["route"], "ordinal": row["ordinal"]}


def _coordinate_semantic_preflight(request, offered):
    fields = {"schema", "profile", "graph_report_raw_sha256", "graph_report_sha256",
              "graph_originals_sha256", "output_inputs"}
    _need(type(request) is dict and set(request) == fields
          and request["schema"] == COORDINATE_SEMANTIC_REQUEST_SCHEMA
          and request["profile"] == COORDINATE_SEMANTIC_PROFILE,
          "explicit closed coordinate semantic proposal request required")
    for key in ("graph_report_raw_sha256", "graph_report_sha256", "graph_originals_sha256"):
        _need(type(request[key]) is str and _SHA.fullmatch(request[key]), "exact semantic proposal pin required")
    _need(type(offered) is dict and offered.get("schema") == "legal-coordinate-source-graph-intake/v3"
          and offered.get("source_compatibility_profile") == "original-input-wire-coordinate-source-graph-intake/v1"
          and offered.get("metadata_profile") == COORDINATE_SEMANTIC_METADATA_PROFILE,
          "explicit original-input wire graph v3 required")
    outputs, sidecars = offered.get("output_occurrences"), request["output_inputs"]
    _need(type(outputs) is list and type(sidecars) is list
          and len(outputs) == len(sidecars) <= MAX_COORDINATE_SEMANTIC_OUTPUTS,
          "complete bounded semantic output slot population required")
    seen = set()
    for ordinal, (output, sidecar) in enumerate(zip(outputs, sidecars, strict=True)):
        _need(type(output) is dict and type(sidecar) is dict
              and set(sidecar) == _COORDINATE_SEMANTIC_SLOT_FIELDS
              | {"semantic_declarations", "expected_scope_id", "expected_graph_sha256"},
              "closed per-output semantic proposal sidecar required")
        _need(type(sidecar["output_occurrence_ordinal"]) is int
              and sidecar["output_occurrence_ordinal"] == ordinal
              and type(sidecar["ordinal"]) is int and 0 <= sidecar["ordinal"] < 2**63
              and type(sidecar["physical_identity_sha256"]) is str
              and _SHA.fullmatch(sidecar["physical_identity_sha256"])
              and type(sidecar["route"]) is str and 0 < len(sidecar["route"].encode("utf-8")) <= 2048,
              "exact ordered semantic output identity required")
        identity = tuple(sidecar[key] for key in ("physical_identity_sha256", "route", "ordinal"))
        _need(identity not in seen and all(sidecar[key] == value for key, value in
              _coordinate_semantic_slot(output, ordinal).items()),
              "semantic output slot omitted, duplicated, reordered or changed")
        seen.add(identity)
        declarations, scope, graph_pin = (sidecar[key] for key in
            ("semantic_declarations", "expected_scope_id", "expected_graph_sha256"))
        if declarations is None:
            _need(scope is None and graph_pin is None, "unavailable semantic declarations require null proposal pins")
        else:
            _need(type(declarations) is dict and set(declarations) == {"entities", "assertions"}
                  and type(declarations["entities"]) is list and len(declarations["entities"]) <= 256
                  and type(declarations["assertions"]) is list and len(declarations["assertions"]) <= 512,
                  "bounded existing semantic declaration shape required")
            _need(type(scope) is str and re.fullmatch(r"legal-scope:sha256:[0-9a-f]{64}", scope),
                  "independently supplied exact semantic scope identity required")
            _need(graph_pin is None or type(graph_pin) is str and _SHA.fullmatch(graph_pin),
                  "optional independent semantic graph pin required")


def _coordinate_semantic_unqualified(report):
    _need(type(report) is dict and report.get("schema") == COORDINATE_SEMANTIC_SCHEMA
          and report.get("profile") == COORDINATE_SEMANTIC_PROFILE
          and report.get("metadata_profile") == COORDINATE_SEMANTIC_METADATA_PROFILE
          and report.get("status") == "proposed_unreviewed",
          "explicit unreviewed coordinate semantic proposal report required")
    outputs = report.get("output_occurrences")
    _need(type(outputs) is list and len(outputs) <= MAX_COORDINATE_SEMANTIC_OUTPUTS,
          "complete bounded unreviewed semantic outputs required")
    expected_authority = _coordinate_semantic_authority()
    for row in [report, *outputs]:
        authority = row.get("authority")
        _need(type(authority) is dict and set(authority) == set(expected_authority)
              and all(value is False for value in authority.values()), "semantic proposals cannot grant authority")
        for key in ("training_mask", "evaluation_gold_mask", "source_binding_mask"):
            _need(type(row.get(key)) is int and row[key] == 0, "semantic proposal masks must remain plain integer zero")
        _need(row.get("selected_occurrence") is None and row.get("governing_definition_use") is None,
              "semantic proposals cannot select a source or governing definition")


def _coordinate_semantic_operation(request_raw, graph_report_raw, expected_request_sha256,
        graph_originals, *, report=None, expected_report_sha256=None, validating=False):
    # Hold finalization and encoders before the first callback/encoder boundary.
    finish, encoder, reader, snapshot, direct_dumps = (_coordinate_semantic_finish,
        _coordinate_semantic_wire, _coordinate_semantic_read, _coordinate_semantic_snapshot,
        _semantic_json.dumps)
    def entry_bindings():
        return (_coordinate_semantic_finish, _coordinate_semantic_wire, _coordinate_semantic_read,
            _coordinate_semantic_snapshot, _coordinate_semantic_owners, _coordinate_semantic_sources,
            _coordinate_semantic_callbacks, _coordinate_semantic_authority,
            _coordinate_semantic_slot, _coordinate_semantic_preflight, _coordinate_semantic_unqualified,
            _coordinate_semantic_operation, coordinate_semantic_graph_proposals_originals_sha256,
            coordinate_semantic_graph_proposals_sha256, prepare_coordinate_semantic_graph_proposals_v1,
            validate_coordinate_semantic_graph_proposals_v1, graphs.build_graph, graphs.graph_to_ast,
            graphs._semantics, graphs._subselector, graphs._refs, graphs._check_bindings,
            graphs._validate_ast, graphs._tree, intake.validate_coordinate_source_graph_intake_v3,
            _semantic_json.dumps)
    entry_callbacks = entry_bindings()
    original = dict(request_raw=request_raw, graph_report_raw=graph_report_raw,
        expected_request_sha256=expected_request_sha256, graph_originals=graph_originals,
        report=report, expected_report_sha256=expected_report_sha256, validating=validating)
    detached, commitment = snapshot(original)
    owners = pins = callbacks = None
    request = offered = parsed_report = result = None
    parsed_commitment = offered_canonical = serialized = None
    plan = file_witness = runtime = runtime_pins = runtime_description = None
    runtime_function = runtime_self = None
    retained, opened, primary = [], False, None

    def fingerprint(value):
        return snapshot(value, copy=False)[1]

    def encode(value, maximum=MAX_COORDINATE_SEMANTIC_REPORT_BYTES):
        raw = encoder(value, maximum)
        exact = direct_dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        _need(type(raw) is bytes and raw == exact and len(raw) <= maximum,
              "semantic proposal encoder differs from actual ordinary object")
        return raw

    def hold(value, label):
        _need(len(retained) < 4096, "bounded semantic proposal delegate returns required")
        retained.append((value, fingerprint(value), label))
        return value

    def pure_fence():
        _need(_coordinate_semantic_finish is finish and _coordinate_semantic_wire is encoder
              and _coordinate_semantic_read is reader and _coordinate_semantic_snapshot is snapshot
              and _semantic_json.dumps is direct_dumps, "semantic proposal entry callbacks changed")
        _need(all(left is right for left, right in zip(entry_bindings(), entry_callbacks, strict=True)),
              "semantic proposal entry producer bindings changed")
        _need(fingerprint(original) == commitment and fingerprint(detached) == commitment,
              "original or detached semantic proposal inputs changed")
        if parsed_commitment is not None:
            _need(fingerprint([request, offered, parsed_report, pins]) == parsed_commitment,
                  "parsed semantic proposal request, report, upstream graph or pins changed")
        for value, identity, label in retained:
            _need(fingerprint(value) == identity, "actual semantic proposal delegate return changed: " + label)

    def producer_fence():
        if owners is None:
            return
        _need(fingerprint(_coordinate_semantic_sources(owners)) == fingerprint(pins),
              "semantic proposal selected producer sources changed")
        current = _coordinate_semantic_callbacks(owners)
        _need(len(current) == len(callbacks) and all(
            getattr(left, "__func__", left) is getattr(right, "__func__", right)
            and getattr(left, "__self__", None) is getattr(right, "__self__", None)
            for left, right in zip(current, callbacks, strict=True)),
            "semantic proposal selected producer callbacks changed")
        if runtime is not None:
            observed, observed_pins = intake._coordinate_graph_runtime(owners[2])
            operation = observed.describe_runtime
            _need(observed is runtime and fingerprint(observed_pins) == runtime_pins
                  and getattr(operation, "__func__", operation) is runtime_function
                  and getattr(operation, "__self__", None) is runtime_self,
                  "semantic proposal runtime identity changed")
            description = hold(operation("legal_ir", eligibility_request["decoder_profile"]),
                               "actual closing runtime description")
            _need(fingerprint(description) == runtime_description, "semantic proposal runtime metadata changed")

    def physical_fence():
        if plan is not None:
            join = owners[2]._owners()[0]
            observed = hold(join._coordinate_file_witnesses(*plan), "actual closing physical witness")
            _need(fingerprint(observed) == file_witness, "semantic proposal physical inputs changed after graph replay")

    def fence():
        finish((("pure inputs and retained returns", pure_fence),
            ("selected producers and runtime", producer_fence), ("physical graph originals", physical_fence),
            ("post-callback pure custody", pure_fence)), None)

    def replay():
        nonlocal opened
        opened = True
        arguments = detached["graph_originals"]
        value = hold(intake.validate_coordinate_source_graph_intake_v3(offered,
            arguments["request_raw"], arguments["eligibility_report_raw"],
            arguments["eligibility_request_raw"], arguments["join_manifest_raw"],
            expected_request_sha256=arguments["expected_request_sha256"],
            expected_report_sha256=request["graph_report_sha256"],
            join_originals=arguments["join_originals"], source_bindings=arguments["source_bindings"]),
            "actual genuine wire graph validation return")
        _need(encode(value, MAX_COORDINATE_SEMANTIC_GRAPH_BYTES) == graph_canonical,
              "genuine wire graph validation differs from independently pinned complete graph")
        intake._coordinate_graph_wire_unqualified(value)
        return value

    def final_output():
        if serialized is not None:
            _need(encode(result) == serialized, "semantic proposal result changed during final serialization")
            fence()
            _coordinate_semantic_unqualified(result)
            _need(direct_dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8") == serialized,
                "actual returned semantic proposal report differs from final bytes")

    try:
        _need(type(expected_request_sha256) is str and _SHA.fullmatch(expected_request_sha256)
              and type(request_raw) is bytes and 0 < len(request_raw) <= MAX_COORDINATE_SEMANTIC_REQUEST_BYTES
              and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
              "semantic proposal request differs from independent raw pin")
        _need(type(graph_report_raw) is bytes and 0 < len(graph_report_raw) <= MAX_COORDINATE_SEMANTIC_GRAPH_BYTES,
              "bounded complete original wire graph bytes required")
        _need(type(graph_originals) is dict and set(graph_originals) == _COORDINATE_SEMANTIC_ORIGINAL_FIELDS,
              "complete original wire graph arguments required")
        request = hold(reader(detached["request_raw"], MAX_COORDINATE_SEMANTIC_REQUEST_BYTES,
            "semantic proposal request"), "actual parsed semantic proposal request")
        offered = hold(reader(detached["graph_report_raw"], MAX_COORDINATE_SEMANTIC_GRAPH_BYTES,
            "original wire graph"), "actual parsed original wire graph")
        _coordinate_semantic_preflight(request, offered)
        _need(hashlib.sha256(graph_report_raw).hexdigest() == request["graph_report_raw_sha256"],
              "wire graph artifact differs from independent semantic proposal pin")
        graph_canonical = encode(offered, MAX_COORDINATE_SEMANTIC_GRAPH_BYTES)
        _need(hashlib.sha256(graph_canonical).hexdigest() == request["graph_report_sha256"],
              "wire graph canonical identity differs from independent semantic proposal pin")
        if validating:
            _need(type(expected_report_sha256) is str and _SHA.fullmatch(expected_report_sha256),
                  "independent complete semantic proposal report pin required")
            parsed_report = reader(detached["report"], MAX_COORDINATE_SEMANTIC_REPORT_BYTES, "semantic proposal report") \
                if type(detached["report"]) is bytes else detached["report"]
            hold(parsed_report, "actual parsed offered semantic proposal report")
            offered_canonical = encode(parsed_report)
            _need(hashlib.sha256(offered_canonical).hexdigest() == expected_report_sha256,
                  "semantic proposal offered report differs from independent pin")
            _coordinate_semantic_unqualified(parsed_report)
        pure_fence()
        owners = _coordinate_semantic_owners()
        pins = _coordinate_semantic_sources(owners)
        callbacks = _coordinate_semantic_callbacks(owners)
        _need(coordinate_semantic_graph_proposals_originals_sha256(detached["graph_originals"])
              == request["graph_originals_sha256"], "independent original graph argument commitment differs")
        parsed_commitment = fingerprint([request, offered, parsed_report, pins])
        fence()
        genuine = replay()
        fence()
        corpus, _, eligibility, _, _ = owners
        plan = hold(list(corpus._corpus_wire_physical_plan(intake, eligibility, genuine,
            detached["graph_originals"])), "actual complete wire physical plan")
        file_witness = fingerprint(hold(eligibility._owners()[0]._coordinate_file_witnesses(*plan),
            "actual opening physical witness"))
        retained_join = hold(reader(detached["graph_originals"]["join_manifest_raw"],
            16 * 1024**2, "genuinely replayed original wire join"), "actual parsed retained wire join")
        _need(file_witness == fingerprint(retained_join["retained_file_witnesses"]),
              "semantic proposal opening physical witness differs from genuine retained join")
        runtime, observed_pins = intake._coordinate_graph_runtime(eligibility)
        runtime_pins = fingerprint(hold(observed_pins, "actual opening runtime producer pins"))
        eligibility_request = hold(reader(detached["graph_originals"]["eligibility_request_raw"],
            128 * 1024, "wire eligibility request"), "actual parsed eligibility request")
        operation = runtime.describe_runtime
        runtime_function, runtime_self = getattr(operation, "__func__", operation), getattr(operation, "__self__", None)
        runtime_description = fingerprint(hold(operation("legal_ir", eligibility_request["decoder_profile"]),
            "actual opening runtime description"))
        _need(runtime_description == fingerprint(genuine["runtime_description"]),
              "genuine graph runtime description differs from current metadata")
        fence()
        rows = []
        for ordinal, (output, sidecar) in enumerate(zip(genuine["output_occurrences"], request["output_inputs"], strict=True)):
            graph = graph_request = None
            issues = []
            if output["graph"] is None:
                issues.append({"code": "upstream_graph_unresolved"})
            elif sidecar["semantic_declarations"] is None:
                issues.append({"code": "semantic_declarations_not_supplied"})
            else:
                base = output["graph_request"]
                _need(type(base) is dict and set(base) == {"ast", "profile", "source", "scope", "dependency_refs", "evidence_refs"}
                      and base["profile"] == "canonical_rules_v1"
                      and sidecar["expected_scope_id"] == base["scope"]["scope_id"],
                      "semantic proposal exact source graph scope differs")
                graph_request = hold(snapshot({**base, "semantic_declarations": sidecar["semantic_declarations"],
                    "scope_request": None})[0], "actual independent semantic builder request")
                builder_commitment = fingerprint(graph_request)
                graph = hold(graphs.build_graph(**graph_request), "actual semantic graph builder return")
                _need(fingerprint(graph_request) == builder_commitment, "semantic graph builder mutated its request")
                ast = hold(graphs.graph_to_ast(graph), "actual semantic graph roundtrip return")
                _need(fingerprint(ast) == fingerprint(base["ast"]), "semantic graph changed the complete ordered AST")
                _need(graph["profile"] == base["profile"] and graph["scope_request"] is None
                      and fingerprint([graph["source"], graph["scope"], graph["dependency_refs"], graph["evidence_refs"]])
                      == fingerprint([base["source"], base["scope"], base["dependency_refs"], base["evidence_refs"]])
                      and fingerprint({"entities": [row["declaration"] for row in graph["entities"]],
                          "assertions": [row["declaration"] for row in graph["assertions"]]})
                      == fingerprint(sidecar["semantic_declarations"]),
                      "semantic graph builder changed independently supplied declarations or bindings")
                graph_raw = encode(graph, 1024**2)
                _need(sidecar["expected_graph_sha256"] is None
                      or hashlib.sha256(graph_raw).hexdigest() == sidecar["expected_graph_sha256"],
                      "semantic graph differs from optional independent graph pin")
            rows.append({**_coordinate_semantic_slot(output, ordinal),
                "upstream_output": output, "proposal_input": sidecar,
                "source_scoped_graph": graph, "graph_request": graph_request, "issues": issues,
                "disposition": "proposed_unreviewed_graph" if graph is not None else "unresolved",
                "authority": _coordinate_semantic_authority(), "training_mask": 0,
                "evaluation_gold_mask": 0, "source_binding_mask": 0,
                "selected_occurrence": None, "governing_definition_use": None})
        result = hold({"schema": COORDINATE_SEMANTIC_SCHEMA, "profile": COORDINATE_SEMANTIC_PROFILE,
            "status": "proposed_unreviewed", "metadata_profile": COORDINATE_SEMANTIC_METADATA_PROFILE,
            "source_metadata_intake_sha256": genuine["source_metadata_intake_sha256"],
            "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256,
            "graph_report_raw_utf8": graph_report_raw.decode("utf-8"),
            "graph_report_reference": {"artifact_sha256": request["graph_report_raw_sha256"],
                "report_sha256": request["graph_report_sha256"], "bytes": len(graph_report_raw),
                "graph_originals_sha256": request["graph_originals_sha256"]},
            "physical_rows": genuine["physical_rows"], "row_references": genuine["row_references"],
            "output_occurrences": rows, "population_complete": True,
            "counts": {"physical_rows": len(genuine["physical_rows"]),
                "output_occurrences": len(rows), "proposed_unreviewed_graphs": sum(row["source_scoped_graph"] is not None for row in rows),
                "unresolved_outputs": sum(row["source_scoped_graph"] is None for row in rows)},
            "upstream_reexecution_requirement": "opening_and_closing_original_input_wire_graph_v3_public_validation",
            "external_complete_originals_required": True, "atomic_snapshot_verified": False,
            "entity_binding": "unavailable_semantic_companions_not_supplied",
            "source_edition_context_definition_status": "unresolved_independent_review_required",
            "selected_occurrence": None, "governing_definition_use": None,
            "authority": _coordinate_semantic_authority(), "training_mask": 0,
            "evaluation_gold_mask": 0, "source_binding_mask": 0, "producer_pins": pins,
            "producer_pin_scope": "listed_semantic_proposal_and_upstream_graph_owner_files_not_complete_execution_closure",
            "limitations": [
                "Complete supplied output slots, original wire graph and independently authored declarations are proposal custody only.",
                "Mention, concept, definition operator and ordered relationship declarations are preserved without interpreting or approving their legal meaning.",
                "No entity-cache row is selected, repaired, merged or semantically associated; an entity census cannot supply these declarations.",
                "Original graph source nominations remain unselected; source/edition correspondence, context closure and governing definition applicability remain unresolved.",
                "The unchanged graph-v3 and coordinate-corpus-v2 contracts do not accept this new report; existing general graph adapters require their full independent inputs.",
                "Complete inputs exceeding this profile's bounded request, output, aggregate or existing graph limits are refused, never truncated.",
                "Opening/closing observations are cooperative custody boundaries, not an atomic snapshot, OS sandbox or complete loaded-byte attestation.",
                "No authentication, meaning decision, source adoption, training, gold, model, graph admission or Lean execution is established."]},
            "actual assembled semantic proposal report")
        _coordinate_semantic_unqualified(result)
        serialized = encode(result)
        _need(not validating or serialized == offered_canonical,
              "semantic proposal report differs from complete original regeneration")
        result = hold(reader(serialized, MAX_COORDINATE_SEMANTIC_REPORT_BYTES,
            "detached semantic proposal report"), "actual detached semantic proposal report")
    except BaseException as error:
        primary = error
        raise
    finally:
        finish((("closing genuine wire graph validation", lambda: replay() if opened else None),
            ("closing original, producer, return and physical custody", fence),
            ("final semantic proposal output", final_output)), primary)
    return result


def prepare_coordinate_semantic_graph_proposals_v1(request_raw, graph_report_raw, *,
        expected_request_sha256, graph_originals):
    """Propose authored scoped entities/assertions over every genuine wire output."""
    return _coordinate_semantic_operation(request_raw, graph_report_raw, expected_request_sha256,
        graph_originals)


def validate_coordinate_semantic_graph_proposals_v1(report, request_raw, graph_report_raw, *,
        expected_report_sha256, expected_request_sha256, graph_originals):
    """Regenerate all proposals from complete originals and independent pins."""
    return _coordinate_semantic_operation(request_raw, graph_report_raw, expected_request_sha256,
        graph_originals, report=report, expected_report_sha256=expected_report_sha256, validating=True)


__all__ += ["coordinate_semantic_graph_proposals_originals_sha256",
    "coordinate_semantic_graph_proposals_sha256", "prepare_coordinate_semantic_graph_proposals_v1",
    "validate_coordinate_semantic_graph_proposals_v1"]
