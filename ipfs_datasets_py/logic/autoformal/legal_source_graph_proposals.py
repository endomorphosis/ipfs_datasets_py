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
