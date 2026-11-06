"""Explicit custody compatibility between retained declarations and fresh norms.

Complete old and current inputs keep their own identities. Only validated
producer/derived-generation fields may differ; every remaining field and every
ordered obligation payload must agree literally. This is not declaration
authentication, historical reexecution, meaning selection or definition use.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_content_declaration_v1 as declaration
from . import legal_norm_content_responses_v1 as content
from . import legal_norm_interpretation_review_v1 as norm
from . import legal_paired_manifest_inventory_v1 as transport

SCHEMA = "legal-norm-content-declaration-binding/v1"
PROFILE = "exact-retained-to-current-norm-candidate-custody/v1"
INPUT_NAMES = ("declaration", "declaration_request", "retained_norm_preparation",
               "retained_definition_evidence", "current_preparation", "dependency_manifest")
INPUT_LIMITS = {"declaration": declaration.MAX_REPORT_BYTES,
    "declaration_request": declaration.MAX_REQUEST_BYTES,
    "retained_norm_preparation": declaration.MAX_INPUT_BYTES,
    "retained_definition_evidence": declaration.MAX_INPUT_BYTES,
    "current_preparation": norm.MAX_BYTES, "dependency_manifest": norm.MAX_BYTES}
MAX_OBLIGATIONS = min(norm.MAX_OBLIGATIONS, declaration.MAX_OBLIGATIONS)
MAX_REPORT_BYTES = norm.MAX_BYTES
_BUILD_FIELDS = {"expected_preparation_sha256", "expected_manifest_sha256", "required_dependency_ids",
    "correspondence", "expected_correspondence_sha256", "correspondence_inputs", "context_inputs"}
AUTHORITY = dict(declaration.AUTHORITY, declaration_author_authenticated=False,
    review_prerequisites_verified=False, current_definition_reexecution_verified=False,
    semantic_graph_admitted=False, typed_meaning_decisions_applied=False)
_DIRECT_MODULES = (declaration, content, norm, transport)
_DIRECT_PINS = {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in _DIRECT_MODULES}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_need, _keys, _sha = norm._need, norm._keys, norm._sha
_PRODUCER_PATHS = ("/producer_pins", "/correspondence/producer_pins",
    "/correspondence/relational_fragment/producer_pins",
    "/correspondence/relational_fragment/native_fragment/producer_pins",
    "/correspondence/source_scope/producer_pins")
_COMPARISON_PATHS = ("/correspondence/source_scope", "/correspondence/source_scope/source_records",
    "/correspondence/source_scope/source_context_packet", "/correspondence/source_scope/scope_declaration",
    "/correspondence/source_scope/scope_declaration/coverage", "/correspondence/source_scope/input_pins",
    "/correspondence/source_scope/source_selector", "/correspondence/source_scope/anchor_mappings",
    "/correspondence/relational_fragment/typed_expression", "/correspondence/relational_fragment/native_ast",
    "/correspondence/relational_fragment/request", "/correspondence/relational_fragment/request_raw_utf8",
    "/correspondence/request/source_rows", "/correspondence/request/typed_rows",
    "/correspondence/typed_context_inventory", "/correspondence/retained_unresolved", "/context_evidence", "/")


def norm_content_declaration_binding_sha256(value):
    """Complete bounded norm canonical UTF8 SHA256, not raw-file SHA256.

    Raw input pins hash exact bytes. Canonical input pins use the existing
    transport recipe under each input's existing size bound. Compact signing
    subjects retain their separate graph-review accepted JSON profile.
    """
    return norm.norm_review_sha256(value)


def _pins():
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "declaration binding producer changed since import")
    _need({path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _DIRECT_PINS} == _DIRECT_PINS,
          "direct declaration binding producer changed since import")
    pins = dict(content._pins())
    for path, pin in declaration._freshness().items():
        _need(path not in pins or pins[path] == pin, "inherited producer generations disagree")
        pins[path] = pin
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    return pins


def _at(value, path):
    if path == "/":
        return value
    for token in path.split("/")[1:]:
        value = value[int(token)] if type(value) is list else value[token]
    return value


def _replace(value, path, replacement):
    parent, token = path.rsplit("/", 1)
    container = _at(value, parent or "/")
    container[int(token) if type(container) is list else token] = replacement


def _expected_obligations(preparation):
    correspondence = preparation["correspondence"]
    expected = [{"slot_id": row["slot_id"], "kind": "original_context", "original": row}
        for row in correspondence["source_scope"]["source_context_packet"]["dependency_slots"]]
    expected.extend({"slot_id": "norm-issue:" + norm.norm_review_sha256(
        [preparation["correspondence_sha256"], index, issue]), "kind": "original_unresolved_issue", "original": issue}
        for index, issue in enumerate(correspondence["retained_unresolved"]))
    expected.extend({"slot_id": "norm-question:" + norm.norm_review_sha256(
        [preparation["correspondence_sha256"], question]), "kind": "interpretation_question", "question": question}
        for question in norm.SEMANTIC_QUESTIONS)
    _need(0 < len(expected) <= MAX_OBLIGATIONS and norm._same(preparation["obligations"], expected),
          "complete exact ordered original obligations required")
    ids = [row["slot_id"] for row in expected]
    _need(len(set(ids)) == len(ids) and norm._same(preparation["context_slot_ids"], ids),
          "complete unique ordered context slot identities required")
    return expected


def _slot_pairs(historical, current):
    """Derive a complete ordered bijection; never accept offered slot remapping."""
    detached, _ = norm._snapshot({"historical": historical, "current": current})
    old, new = (_expected_obligations(detached[key]) for key in ("historical", "current"))
    _need(len(old) == len(new), "historical/current obligation populations differ")
    pairs = []
    for index, (left, right) in enumerate(zip(old, new, strict=True)):
        _need(left["kind"] == right["kind"], "ordered obligation kinds differ")
        kind = left["kind"]
        key = "question" if kind == "interpretation_question" else "original"
        _need(norm._same(left[key], right[key]), "original obligation payload or semantic question differs")
        if kind == "original_context":
            _need(left["slot_id"] == right["slot_id"], "original source context slot identity differs")
        semantic_key = {"kind": kind, "question": left[key]} if key == "question" else {
            "kind": kind, "original_sha256": norm.norm_review_sha256(left[key])}
        pairs.append({"ordinal": index, "kind": kind, "semantic_key": semantic_key,
            "historical_slot_id": left["slot_id"], "current_slot_id": right["slot_id"],
            "historical_obligation_sha256": norm.norm_review_sha256(left),
            "current_obligation_sha256": norm.norm_review_sha256(right),
            "historical_content_sha256": norm.norm_review_sha256(left[key]),
            "current_content_sha256": norm.norm_review_sha256(right[key])})
    return pairs


def _generation_projection(preparation):
    """Validate generation cross-links before normalizing only their exact paths."""
    value = json.loads(norm._wire(preparation))
    correspondence = preparation["correspondence"]
    scope, relational = correspondence["source_scope"], correspondence["relational_fragment"]
    input_pins, request = correspondence["input_pins"], correspondence["request"]
    corr_pin = norm.norm_review_sha256(correspondence)
    root = "norm-correspondence:" + corr_pin
    _need(preparation["correspondence_sha256"] == preparation["graph_sha256"] == corr_pin and preparation["graph_id"] == root,
          "generation correspondence root/hash cross-link differs")
    _need(preparation["scope_id"] == "norm-review-scope:" + norm.norm_review_sha256({
        "domain": norm.SUBJECT_SCHEMA, "correspondence_sha256": corr_pin,
        "source_unit": scope["input_pins"]["selected_unit_ref"]}), "generation scope identity differs")
    _need(preparation["ast_sha256"] == norm.norm_review_sha256(relational["typed_expression"])
          and preparation["native_ast_sha256"] == norm.norm_review_sha256(relational["native_ast"]),
          "generation literal AST commitments differ")
    _need(scope["report_sha256"] == norm.norm_review_sha256({k: v for k, v in scope.items() if k != "report_sha256"}),
          "generation source scope embedded report hash differs")
    fields = {}

    def mark(path, classification):
        fields[path] = {"classification": classification, "value": _at(preparation, path)}
        _replace(value, path, None)

    for path in _PRODUCER_PATHS:
        pins = _at(preparation, path)
        _need(type(pins) is dict and bool(pins) and all(type(key) is str for key in pins), "complete declared producer map required")
        for pin in pins.values():
            _sha(pin, "declared generation producer")
        mark(path, "retained_producer_generation_not_historical_execution_verification")
    for name, body in (("scope_report", scope), ("relational_report", relational)):
        encoded = norm._wire(body)
        pin = hashlib.sha256(encoded).hexdigest()
        _need(input_pins[name + "_sha256"] == request[name + "_sha256"] == pin,
              "generation complete report cross-commitment differs")
        replay = input_pins["replay_inputs"][name]
        _need(replay["sha256"] == pin and type(replay["bytes"]) is int and replay["bytes"] == len(encoded),
              "generation complete report replay hash/byte count differs")
        for path in ("/correspondence/input_pins/" + name + "_sha256",
                     "/correspondence/request/" + name + "_sha256",
                     "/correspondence/input_pins/replay_inputs/" + name + "/sha256",
                     "/correspondence/input_pins/replay_inputs/" + name + "/bytes"):
            mark(path, "derived_complete_retained_report_commitment")
    _need(correspondence["source_scope_validation"]["report_full_canonical_sha256"] == input_pins["scope_report_sha256"],
          "generation scope validation report commitment differs")
    mark("/correspondence/source_scope/report_sha256", "derived_scope_payload_digest")
    mark("/correspondence/source_scope_validation/report_full_canonical_sha256", "derived_complete_retained_report_commitment")
    _sha(input_pins["mapping_request_raw_sha256"], "declared mapping request raw bytes")
    _need(type(input_pins["mapping_request_raw_bytes"]) is int and 0 < input_pins["mapping_request_raw_bytes"] <= 4 * 1024**2,
          "bounded declared mapping request byte count required")
    mark("/correspondence/input_pins/mapping_request_raw_sha256", "declared_mapping_raw_commitment_not_reconstructed")
    mark("/correspondence/input_pins/mapping_request_raw_bytes", "declared_mapping_raw_commitment_not_reconstructed")
    for path in ("/correspondence_sha256", "/graph_sha256", "/graph_id", "/scope_id"):
        mark(path, "derived_correspondence_generation_identity")
    obligations = _expected_obligations(preparation)
    for index, row in enumerate(obligations):
        if row["kind"] != "original_context":
            for path in (f"/context_slot_ids/{index}", f"/obligations/{index}/slot_id"):
                mark(path, "derived_issue_or_question_generation_identity")
    dependencies = norm._owners()[0]
    dependencies.build_dependency_manifest(preparation["artifacts"], preparation["edges"],
        expected_artifact_ids=preparation["required_dependency_ids"])
    artifact_ids = [row["artifact_id"] for row in preparation["artifacts"]]
    _need(artifact_ids and artifact_ids[0] == root and preparation["required_dependency_ids"][0] == root,
          "complete generation root dependency inventory required")
    derived = {root: corr_pin, "norm-input:scope_report": input_pins["scope_report_sha256"],
        "norm-input:relational_report": input_pins["relational_report_sha256"],
        "norm-input:mapping_request_raw_sha256": input_pins["mapping_request_raw_sha256"],
        "norm-review-producers": norm.norm_review_sha256(preparation["producer_pins"])}
    _need(set(derived) <= set(artifact_ids), "complete generation-derived artifacts required")
    for index, row in enumerate(preparation["artifacts"]):
        identity = row["artifact_id"]
        if identity not in derived:
            continue
        _need(row["artifact_sha256"] == derived[identity], "generation-derived artifact hash differs")
        mark(f"/artifacts/{index}/artifact_sha256", "derived_artifact_commitment")
        if identity == root:
            mark(f"/artifacts/{index}/artifact_id", "derived_correspondence_generation_identity")
        if identity == "norm-review-producers":
            expected = [{"key": path, "sha256": pin} for path, pin in sorted(preparation["producer_pins"].items())]
            _need(norm._same(row["dependency_pins"]["policy"], expected), "complete producer policy dependency pins differ")
            mark(f"/artifacts/{index}/dependency_pins/policy", "complete_declared_producer_policy_generation")
    for index, edge in enumerate(preparation["edges"]):
        _need(edge["dependent_id"] == root, "generation dependency edge has another root")
        mark(f"/edges/{index}/dependent_id", "derived_correspondence_generation_identity")
    mark("/required_dependency_ids/0", "derived_correspondence_generation_identity")
    return value, fields


def _compare_preparations(historical, current):
    """Compare every remaining field; allow no open-ended metadata exemption."""
    detached, _ = norm._snapshot({"historical": historical, "current": current})
    _slot_pairs(detached["historical"], detached["current"])
    old, old_fields = _generation_projection(detached["historical"])
    new, new_fields = _generation_projection(detached["current"])
    _need(set(old_fields) == set(new_fields), "generation field/dependency populations differ")
    _need(norm._same(old, new), "unexplained non-generation source, coverage, AST or dependency difference")
    differences = []
    for path in sorted(old_fields):
        left, right = old_fields[path], new_fields[path]
        _need(left["classification"] == right["classification"], "generation field classification differs")
        if norm._same(left["value"], right["value"]):
            continue
        differences.append({"path": path, "classification": left["classification"],
            "historical_input": "retained_norm_preparation", "current_input": "current_preparation",
            "historical_sha256": norm.norm_review_sha256(left["value"]),
            "current_sha256": norm.norm_review_sha256(right["value"]),
            "value_custody": "complete_value_at_exact_path_in_independently_pinned_input"})
    comparisons = [{"path": path, "historical_sha256": norm.norm_review_sha256(_at(old, path)),
        "current_sha256": norm.norm_review_sha256(_at(new, path)), "equal": True,
        "generation_fields_separately_retained": [item for item in sorted(old_fields)
            if path == "/" or item.startswith(path.rstrip("/") + "/")]} for path in _COMPARISON_PATHS]
    return {"comparisons": comparisons, "generation_differences": differences,
            "non_generation_projection_sha256": norm.norm_review_sha256(old)}


def _inputs(raw_values, expected_input_pins):
    _keys(expected_input_pins, set(INPUT_NAMES), "six independently supplied input pin pairs")
    parsed = {}
    for name, raw in zip(INPUT_NAMES, raw_values, strict=True):
        pair = expected_input_pins[name]
        _keys(pair, {"raw_sha256", "canonical_sha256"}, "independent raw/canonical input pins")
        _sha(pair["raw_sha256"], name + " raw bytes")
        _sha(pair["canonical_sha256"], name + " complete canonical value")
        _need(type(raw) is bytes and 0 < len(raw) <= INPUT_LIMITS[name]
              and hashlib.sha256(raw).hexdigest() == pair["raw_sha256"], "exact bounded input bytes differ: " + name)
        value = transport._read_json(raw, INPUT_LIMITS[name], name)
        _need(type(value) is dict and hashlib.sha256(transport._wire(value, INPUT_LIMITS[name])).hexdigest() == pair["canonical_sha256"],
              "complete canonical input pin differs: " + name)
        parsed[name] = value
    return parsed


def _nested_refs(request):
    return {"status": "declared_not_verified", "supporting_bodies_verified": False,
        "references": [{"path": f"/request/{group}/{index}/evidence_refs", "evidence_refs": row["evidence_refs"]}
            for group in ("coverage_decisions", "definition_decisions") for index, row in enumerate(request[group])],
        "scope": "Complete ordered declared references retained; no evidence adequacy, author identity or decision authentication."}


def prepare_norm_content_declaration_binding_v1(declaration_raw, declaration_request_raw,
        retained_norm_preparation_raw, retained_definition_evidence_raw, current_preparation_raw,
        dependency_manifest_raw, *, expected_input_pins, current_build_inputs):
    """Bind exact compatible candidate generations, applying no declarations."""
    original = dict(raw_values=[declaration_raw, declaration_request_raw, retained_norm_preparation_raw,
        retained_definition_evidence_raw, current_preparation_raw, dependency_manifest_raw],
        expected_input_pins=expected_input_pins, current_build_inputs=current_build_inputs)
    detached, commitment = norm._snapshot(original)
    offered = _inputs(detached["raw_values"], detached["expected_input_pins"])
    _keys(detached["current_build_inputs"], _BUILD_FIELDS, "complete original current norm subject build inputs")
    pins = _pins()
    trusted = detached["expected_input_pins"]
    request = offered["declaration_request"]
    for label, input_name in (("norm_preparation", "retained_norm_preparation"), ("definition_evidence", "retained_definition_evidence")):
        _need(request[label + "_raw_sha256"] == trusted[input_name]["raw_sha256"] and
              request[label + "_sha256"] == trusted[input_name]["canonical_sha256"], "declaration request differs from independent retained input pins")
    regenerated = declaration.validate_norm_content_declaration(offered["declaration"],
        detached["raw_values"][1], detached["raw_values"][2], detached["raw_values"][3],
        expected_request_sha256=trusted["declaration_request"]["raw_sha256"],
        expected_report_sha256=trusted["declaration"]["canonical_sha256"])
    _need(norm._same(regenerated["retained_norm_preparation"], offered["retained_norm_preparation"])
          and declaration._same(regenerated["retained_definition_evidence"], offered["retained_definition_evidence"]),
          "declaration retains another complete input generation")
    build = detached["current_build_inputs"]
    _need(build["expected_preparation_sha256"] == trusted["current_preparation"]["canonical_sha256"],
          "current replay preparation differs from independent complete pin")
    template = content.build_norm_content_template_v1(offered["current_preparation"], offered["dependency_manifest"], **build)
    historical, current = offered["retained_norm_preparation"], offered["current_preparation"]
    comparison = _compare_preparations(historical, current)
    pairs = _slot_pairs(historical, current)
    report = {"schema": SCHEMA, "profile": PROFILE, "status": "exact_candidate_custody_compatibility_bound",
        "input_pins": trusted, "historical_generation": {
            "preparation_sha256": trusted["retained_norm_preparation"]["canonical_sha256"],
            "correspondence_sha256": historical["correspondence_sha256"], "graph_id": historical["graph_id"],
            "scope_id": historical["scope_id"], "producer_pins": historical["producer_pins"],
            "mapping_request_raw_sha256_declared": historical["correspondence"]["input_pins"]["mapping_request_raw_sha256"],
            "mapping_request_raw_bytes_declared": historical["correspondence"]["input_pins"]["mapping_request_raw_bytes"],
            "parsed_mapping_request_canonical_sha256": norm.norm_review_sha256(historical["correspondence"]["request"]),
            "mapping_request_raw_bytes_verified": False, "historical_owner_reexecution_performed": False},
        "current_generation": {"preparation_sha256": trusted["current_preparation"]["canonical_sha256"],
            "correspondence_sha256": current["correspondence_sha256"], "graph_id": current["graph_id"],
            "scope_id": current["scope_id"], "producer_pins": current["producer_pins"],
            "subject_sha256": template["subject_sha256"], "dependency_manifest_sha256": build["expected_manifest_sha256"],
            "mapping_request_raw_sha256": current["correspondence"]["input_pins"]["mapping_request_raw_sha256"],
            "mapping_request_raw_bytes": current["correspondence"]["input_pins"]["mapping_request_raw_bytes"],
            "parsed_mapping_request_canonical_sha256": norm.norm_review_sha256(current["correspondence"]["request"]),
            "complete_current_norm_replay_performed": True, "current_definition_reexecution_performed": False},
        "candidate_id": request["candidate_id"], "typed_expression_sha256": current["ast_sha256"],
        "native_ast_sha256": current["native_ast_sha256"], "slot_pairs": pairs, **comparison,
        "declared_nested_evidence": _nested_refs(request),
        "declaration_dispositions_sha256": norm.norm_review_sha256({key: request[key]
            for key in ("interpretation", "meaning_unit", "coverage_decisions", "definition_decisions")}),
        "counts": {"slot_pairs": len(pairs), "changed_slot_ids": sum(row["historical_slot_id"] != row["current_slot_id"] for row in pairs),
            "generation_differences": len(comparison["generation_differences"]),
            "definition_alternatives": regenerated["counts"]["definition_alternatives"],
            "definition_links": regenerated["counts"]["definition_links"],
            "distinct_typed_uses": regenerated["counts"]["distinct_typed_uses"],
            "authenticated_declarations": 0, "applied_meaning_decisions": 0, "applied_definition_uses": 0},
        "blockers": ["historical_definition_and_source_execution_not_reverified", "historical_mapping_raw_bytes_not_supplied",
            "declaration_and_nested_evidence_not_authenticated", "complete_meaning_unit_unestablished",
            "original_issues_context_and_coverage_unresolved", "definition_applicability_and_typed_application_unverified",
            "no_response_binding_or_adjudication_applied", "consumer_exposure_and_split_unbound"],
        "producer_pins": pins, "authority": dict(AUTHORITY), "norm_interpretation_ready": False,
        "selected_interpretation": None, "accepted_interpretation": None, "governing_definition_use": None,
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "automatic_response_injection_performed": False, "historical_inputs_rewritten": False}
    encoded = norm._wire(report)
    _need(len(encoded) <= MAX_REPORT_BYTES, "complete declaration binding report byte bound exceeded")
    _need(norm._snapshot(original)[1] == commitment and norm._snapshot(detached)[1] == commitment,
          "declaration binding inputs changed during operation")
    _need(_pins() == pins, "declaration binding producers changed during operation")
    return json.loads(encoded)


def validate_norm_content_declaration_binding_v1(report, *args, expected_report_sha256, **kwargs):
    """Require a complete independent report pin and regenerate all six inputs."""
    original = dict(report=report, args=list(args), kwargs=kwargs)
    detached, commitment = norm._snapshot(original)
    pins = _pins()
    _sha(expected_report_sha256, "complete declaration binding report")
    _need(norm_content_declaration_binding_sha256(detached["report"]) == expected_report_sha256,
          "independently pinned declaration binding report differs")
    expected = prepare_norm_content_declaration_binding_v1(*detached["args"], **detached["kwargs"])
    _need(norm._same(detached["report"], expected), "declaration binding differs from exact complete regeneration")
    encoded = norm._wire(expected)
    _need(len(encoded) <= MAX_REPORT_BYTES, "complete declaration binding report byte bound exceeded")
    _need(norm._snapshot(original)[1] == commitment and norm._snapshot(detached)[1] == commitment,
          "declaration binding validation inputs changed during operation")
    _need(_pins() == pins, "declaration binding producers changed during validation")
    return json.loads(encoded)


__all__ = ["prepare_norm_content_declaration_binding_v1", "validate_norm_content_declaration_binding_v1",
           "norm_content_declaration_binding_sha256"]
