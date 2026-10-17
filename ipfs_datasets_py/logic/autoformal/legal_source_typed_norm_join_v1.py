"""Unreviewed correspondence between exact source scope and typed syntax.

The existing source and relational owners retain their separate contracts.
This envelope records caller hypotheses over their exhaustively replayed
mapping domains. It never selects statutory meaning or produces source code.
Public import and independent input preflight use only the standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

REQUEST_SCHEMA = "legal-source-typed-norm-join-request/v1"
SCHEMA = "legal-source-typed-norm-join-proposal/v1"
PROFILE = "whole-source-partial-typed-correspondence/v1"
MAX_REQUEST_BYTES = 512 * 1024
MAX_SCOPE_BYTES = 65536
MAX_SCOPE_REPORT_BYTES = 1024 * 1024
MAX_RELATIONAL_REQUEST_BYTES = 512 * 1024
MAX_RELATIONAL_REPORT_BYTES = 8 * 1024 * 1024
MAX_SAMPLING_BYTES = 32 * 1024 * 1024
MAX_RAW_BYTES = 8_000_000
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_CORRESPONDENCES = 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REF_FIELDS = {"schema", "record_cid", "sha256"}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "legal_roles_verified", "source_context_resolved",
    "context_closure_verified", "dependency_inventory_exhaustive",
    "declared_issues_exhaustive", "applicability_verified",
    "singular_plural_identity_verified", "governing_use_verified",
    "independently_reviewed", "accepted", "admitted", "formalized",
    "semantic_graph_admitted", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "Lean_admitted", "proof_authority",
    "formal_norm_semantics_encoded", "lowering_authorized", "model_executed",
    "training_executed", "backend_executed", "source_bound",
), False)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, expected, label):
    _need(type(value) is dict and set(value) == set(expected),
          "closed exact fields required: " + label)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _text(value, label, maximum=256):
    _need(type(value) is str and bool(value.strip()) and "\x00" not in value
          and len(value) <= maximum, "bounded nonempty text required: " + label)


def _wire(value, maximum):
    remaining = 2_000_000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 96, "ordinary JSON node/depth bound exceeded")
        if type(item) is dict:
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= maximum,
                  "bounded ordinary UTF8 string required")
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
        else:
            raise ValueError("ordinary JSON values required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded; no truncation")
    return raw


def _digest(value, maximum):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _pairs(entries):
    result = {}
    for key, value in entries:
        _need(key not in result, "duplicate JSON key refused")
        result[key] = value
    return result


def _load(raw, expected_sha256, label, maximum):
    _sha(expected_sha256, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum,
          "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256,
          "independent byte pin differs: " + label)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free UTF8 JSON required: " + label) from error
    _need(type(value) is dict, "ordinary JSON object required: " + label)
    _wire(value, maximum)
    return value


def _pinned_copy(value, expected_sha256, label, maximum):
    _sha(expected_sha256, label)
    _need(type(value) is dict, "ordinary complete report required: " + label)
    raw = _wire(value, maximum)
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256,
          "independent canonical pin differs: " + label)
    return json.loads(raw)


def _reference(value):
    _keys(value, _REF_FIELDS, "selected sealed source unit")
    _need(value["schema"] == "legal-source-structured-sample-unit/v1",
          "selected sampled source unit schema required")
    _text(value["record_cid"], "selected source unit CID")
    _sha(value["sha256"], "selected sealed source unit")


def _request(raw, expected_sha256):
    value = _load(raw, expected_sha256, "join request", MAX_REQUEST_BYTES)
    _keys(value, {"schema", "interpretation_status", "component_id", "alternative_id",
                  "selected_unit_ref", "node_correspondences", "introduced_unresolved"},
          "join request")
    _need(value["schema"] == REQUEST_SCHEMA
          and value["interpretation_status"] == "unreviewed_correspondence_proposal",
          "unreviewed correspondence request required")
    _text(value["component_id"], "component identity")
    _text(value["alternative_id"], "alternative identity")
    _reference(value["selected_unit_ref"])
    rows, issues = value["node_correspondences"], value["introduced_unresolved"]
    _need(type(rows) is list and len(rows) <= MAX_CORRESPONDENCES,
          "bounded correspondence list required")
    _need(type(issues) is list and len(issues) <= MAX_CORRESPONDENCES,
          "bounded introduced issue list required")
    for row in rows:
        _keys(row, {"typed_path", "source_anchor_paths", "disposition", "unresolved_codes", "rationale"},
              "node correspondence")
        _text(row["typed_path"], "typed mapping path", 8192)
        _text(row["rationale"], "correspondence rationale", 4096)
        _need(type(row["disposition"]) is str
              and row["disposition"] in {"lexical_hypothesis", "introduced_unresolved"},
              "explicit unreviewed correspondence disposition required")
        for field in ("source_anchor_paths", "unresolved_codes"):
            _need(type(row[field]) is list and len(row[field]) <= MAX_CORRESPONDENCES,
                  "bounded correspondence references required")
            for item in row[field]:
                _text(item, field, 8192 if field == "source_anchor_paths" else 256)
            _need(len(set(row[field])) == len(row[field]), "duplicate correspondence reference")
        _need(bool(row["unresolved_codes"]), "every correspondence must retain an unresolved issue")
        _need(row["disposition"] != "lexical_hypothesis" or bool(row["source_anchor_paths"]),
              "lexical hypothesis requires an exact existing source anchor")
    for issue in issues:
        _keys(issue, {"code", "rationale", "affected_typed_paths"}, "introduced unresolved issue")
        _text(issue["code"], "introduced issue code")
        _text(issue["rationale"], "introduced issue rationale", 4096)
        paths = issue["affected_typed_paths"]
        _need(type(paths) is list and 0 < len(paths) <= MAX_CORRESPONDENCES,
              "introduced issue requires affected typed paths")
        for path in paths:
            _text(path, "introduced issue typed path", 8192)
        _need(len(set(paths)) == len(paths), "duplicate introduced issue path")
    return value


def _replay_inputs(inputs):
    required = {"sampling_report", "raw_html", "scope_request_raw", "scope_declaration_raw",
                "expected_sampling_report_sha256", "selected_unit_ref",
                "expected_scope_request_sha256", "expected_scope_declaration_sha256",
                "descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes"}
    _need(type(inputs) is dict and required <= set(inputs)
          and not (set(inputs) - required - {"view_limits", "limits"}),
          "closed complete original scope replay inputs required")
    result = {key: value for key, value in inputs.items()
              if key in {"raw_html", "scope_request_raw", "scope_declaration_raw"}}
    result["sampling_report"] = _pinned_copy(inputs["sampling_report"],
        inputs["expected_sampling_report_sha256"], "complete sampling report", MAX_SAMPLING_BYTES)
    _load(inputs["scope_request_raw"], inputs["expected_scope_request_sha256"],
          "scope request", MAX_SCOPE_BYTES)
    _load(inputs["scope_declaration_raw"], inputs["expected_scope_declaration_sha256"],
          "scope declaration", MAX_SCOPE_BYTES)
    raw = inputs["raw_html"]
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_RAW_BYTES,
          "bounded complete original HTML bytes required")
    _sha(inputs["expected_raw_sha256"], "original raw HTML")
    _need(type(inputs["expected_raw_bytes"]) is int
          and inputs["expected_raw_bytes"] == len(raw)
          and hashlib.sha256(raw).hexdigest() == inputs["expected_raw_sha256"],
          "independent complete original HTML commitments differ")
    result["descriptor"] = _pinned_copy(inputs["descriptor"],
        inputs["expected_descriptor_sha256"], "original acquisition descriptor", MAX_SCOPE_BYTES)
    _reference(inputs["selected_unit_ref"])
    for key in required - {"sampling_report", "raw_html", "scope_request_raw",
                            "scope_declaration_raw", "descriptor"}:
        result[key] = json.loads(_wire(inputs[key], MAX_SCOPE_BYTES))
    for key in ("view_limits", "limits"):
        if key in inputs:
            result[key] = json.loads(_wire(inputs[key], MAX_SCOPE_BYTES))
    return result


def _owners():
    from . import legal_source_norm_scope_v1 as source_scope
    from . import legal_relational_norm_v1 as relational
    return source_scope, relational


def _producer_pins(source_scope, relational, scope_report, relational_report):
    # Report commitments are untrusted until replay. Discover the actual owner
    # map first, so a resealed report cannot nominate arbitrary files to read.
    trusted_scope = source_scope._pins(source_scope._owners())
    _need(type(scope_report.get("producer_pins")) is dict
          and scope_report["producer_pins"] == trusted_scope,
          "source scope producer commitments differ from trusted owners")
    pins = dict(trusted_scope)
    if relational_report is not None:
        trusted_relational = relational._owners()[-1]
        _need(type(relational_report.get("producer_pins")) is dict
              and relational_report["producer_pins"] == trusted_relational,
              "relational producer commitments differ from trusted owners")
        for path, digest in trusted_relational.items():
            _need(path not in pins or pins[path] == digest, "shared producer commitments differ")
            pins[path] = digest
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    _check_producer_pins(pins)
    return pins


def _check_producer_pins(pins):
    _need(type(pins) is dict and bool(pins), "complete producer commitments required")
    for path, expected in pins.items():
        _text(path, "producer path", 4096)
        _sha(expected, "producer")
        _need(Path(path).is_absolute(), "absolute producer path required")
        try:
            actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError as error:
            raise ValueError("producer is unavailable during join") from error
        _need(actual == expected, "producer changed during source-to-typed join")


def _derived_structure(report):
    """Derive lexical binding and ordered argument facts from checked syntax."""
    mapping = report["structural_mapping"]
    by_path = {row["typed_path"]: row for row in mapping}
    _need(len(by_path) == len(mapping), "unique authoritative structural paths required")
    roles = {row["symbol"]: row["roles"] for row in report["argument_roles"]}
    derived = []

    def append(path, kind, *, node_id=None, **facts):
        original = by_path.get(path)
        _need(original is not None and original["kind"] == kind,
              "derived node must match the authoritative structural mapping")
        if node_id is not None:
            _need(original.get("node_id") == node_id, "authoritative node identity differs")
        row = {"typed_path": path, "kind": kind,
               "native_path": original["native_path"],
               "native_mapping_scope": "syntax_metadata_only", **facts}
        if node_id is not None:
            row["node_id"] = node_id
        derived.append(row)
        return row

    def visit(node, path, bound, argument=None):
        kind = node["kind"]
        row = append(path, kind, node_id=node["node_id"])
        if kind == "variable":
            name = node["symbol"]
            _need(name in bound and argument is not None,
                  "bound predicate argument provenance required")
            row.update(variable_name=name, variable_sort=node["sort"],
                       predicate_argument=argument, binding_quantifier=bound[name])
        elif kind == "predicate":
            symbol = node["symbol"]
            row.update(predicate_symbol=symbol, argument_roles=roles[symbol],
                       argument_typed_paths=[path + "/arguments/" + str(i)
                                             for i in range(len(node["arguments"]))])
            for index, child in enumerate(node["arguments"]):
                visit(child, path + "/arguments/" + str(index), bound,
                      {"predicate_symbol": symbol, "predicate_typed_path": path,
                       "argument_index": index, "declared_role": roles[symbol][index]})
        elif kind in {"forall", "exists"}:
            binder = node["binders"][0]
            binder_path, body_path = path + "/binders/0", path + "/arguments/0"
            binding = {"quantifier_typed_path": path, "quantifier_node_id": node["node_id"],
                       "quantifier_kind": kind, "binder_typed_path": binder_path,
                       "variable_name": binder["name"], "scope_body_typed_path": body_path}
            row.update(quantifier_kind=kind, binder_typed_path=binder_path,
                       variable_name=binder["name"], scope_body_typed_path=body_path)
            _need(by_path.get(binder_path, {}).get("binder_name") == binder["name"],
                  "authoritative binder identity differs")
            append(binder_path, "binder", binder_name=binder["name"],
                   binder_sort=binder["sort"], binding_quantifier=binding)
            visit(node["arguments"][0], body_path, {**bound, binder["name"]: binding})
        elif kind == "extension":
            extension, extension_path = node["extension"], path + "/extension"
            child_path = extension_path + "/children/0"
            letter = extension["payload"]["letter"]
            row.update(modal_operator=letter, extension_typed_path=extension_path,
                       modal_child_typed_path=child_path)
            _need(by_path.get(extension_path, {}).get("operator") == letter,
                  "authoritative modal operator differs")
            append(extension_path, "legacy.deontic/v1", node_id=extension["node_id"],
                   modal_operator=letter, modal_child_typed_path=child_path,
                   payload_schema=extension["payload_schema"])
            visit(extension["children"][0], child_path, bound)
        elif kind in {"and", "or", "implies", "iff", "not"}:
            row.update(connective_operator=kind,
                       ordered_child_paths=[path + "/arguments/" + str(i)
                                            for i in range(len(node["arguments"]))])
            for index, child in enumerate(node["arguments"]):
                visit(child, path + "/arguments/" + str(index), bound)
        else:
            raise ValueError("unsupported derived typed provenance kind")

    visit(report["typed_expression"]["root"], "/root", {})
    _need([row["typed_path"] for row in derived] == [row["typed_path"] for row in mapping],
          "complete authoritative mapping order and coverage required")
    return derived


def _correspondences(request, scope_report, relational_report):
    if relational_report is None:
        _need(request["node_correspondences"] == [] and request["introduced_unresolved"] == [],
              "source-only pending input cannot introduce a typed interpretation")
        return []
    derived = _derived_structure(relational_report)
    paths = [row["typed_path"] for row in derived]
    _need([row["typed_path"] for row in request["node_correspondences"]] == paths,
          "every authoritative typed path required once in original order")
    path_set = set(paths)
    anchors = {row["declaration_path"]: row for row in scope_report["anchor_mappings"]}
    _need(len(anchors) == len(scope_report["anchor_mappings"]),
          "unique authoritative source anchor paths required")
    original = scope_report["scope_declaration"]["unresolved"]
    original_codes = {row["code"] for row in original}
    _need(len(original_codes) == len(original), "unambiguous original unresolved issue codes required")
    introduced = {}
    for issue in request["introduced_unresolved"]:
        code = issue["code"]
        _need(code not in introduced and code not in original_codes,
              "unique new unresolved issue codes required")
        _need(set(issue["affected_typed_paths"]) <= path_set,
              "introduced issue references an absent typed path")
        introduced[code] = set(issue["affected_typed_paths"])
    used = {code: set() for code in introduced}
    ledger = []
    for facts, row in zip(derived, request["node_correspondences"]):
        source_paths, codes, path = row["source_anchor_paths"], row["unresolved_codes"], row["typed_path"]
        _need(set(source_paths) <= set(anchors), "correspondence requires existing whole source anchors")
        _need(set(codes) <= original_codes | set(introduced), "unknown unresolved issue reference")
        for code in set(codes) & set(introduced):
            _need(path in introduced[code], "introduced issue does not affect this typed path")
            used[code].add(path)
        if not source_paths:
            _need(row["disposition"] == "introduced_unresolved"
                  and bool(set(codes) & set(introduced)),
                  "unanchored typed structure requires an explicit introduced issue")
        ledger.append({**facts, "source_anchor_paths": source_paths,
                       "source_anchors": [anchors[source_path] for source_path in source_paths],
                       "disposition": row["disposition"], "unresolved_codes": codes,
                       "rationale": row["rationale"], "source_meaning_verified": False})
    _need(all(bool(used[code]) and used[code] == affected for code, affected in introduced.items()),
          "every introduced issue and affected path must be used explicitly")
    return ledger


def prepare_source_typed_norm_join_v1(
    scope_report, relational_report, join_request_raw, *,
    expected_join_request_sha256, expected_scope_report_sha256,
    expected_relational_report_sha256, scope_replay_inputs,
    relational_request_raw, expected_relational_request_sha256,
):
    """Retain an unreviewed correspondence, replaying both independent owners.

    ``scope_replay_inputs`` contains the original four scope preparation
    positional inputs by name, plus exactly its preparation keyword inputs.
    Relational report/request/pins must either all be present or all be null.
    Independent expected hashes originate in the retained input manifest.
    """
    request = _request(join_request_raw, expected_join_request_sha256)
    checked_scope = _pinned_copy(scope_report, expected_scope_report_sha256,
                                "complete scope report", MAX_SCOPE_REPORT_BYTES)
    replay = _replay_inputs(scope_replay_inputs)
    _need(request["selected_unit_ref"] == replay["selected_unit_ref"],
          "join selected unit differs from original scope replay inputs")
    absent = (relational_report is None, relational_request_raw is None,
              expected_relational_request_sha256 is None, expected_relational_report_sha256 is None)
    _need(all(absent) or not any(absent), "relational report/request/commitments must all be present or null")
    checked_relational = None
    if not any(absent):
        checked_relational = _pinned_copy(relational_report, expected_relational_report_sha256,
                                         "complete relational report", MAX_RELATIONAL_REPORT_BYTES)
        _load(relational_request_raw, expected_relational_request_sha256,
              "relational request", MAX_RELATIONAL_REQUEST_BYTES)
    else:
        _need(request["node_correspondences"] == [] and request["introduced_unresolved"] == [],
              "source-only pending request requires empty typed declarations")

    source_scope, relational = _owners()
    pins_before = _producer_pins(source_scope, relational, checked_scope, checked_relational)
    source_scope.validate_sampled_norm_scope_v1(checked_scope,
        expected_report_sha256=expected_scope_report_sha256, **replay)
    _check_producer_pins(pins_before)
    _need(checked_scope["input_pins"]["selected_unit_ref"] == request["selected_unit_ref"],
          "join selected unit differs from the authoritative scope report")
    if checked_relational is not None:
        checked_relational = relational.validate_relational_norm_v1(
            checked_relational, relational_request_raw,
            expected_request_sha256=expected_relational_request_sha256,
            expected_report_sha256=expected_relational_report_sha256)
        _need(checked_relational["source_binding"] is None
              and checked_relational["source_bound"] is False,
              "external relational preparation must retain its syntax-only source contract")
    pins = _producer_pins(source_scope, relational, checked_scope, checked_relational)
    _need(pins == pins_before, "producer commitments changed across prior owner replay")
    ledger = _correspondences(request, checked_scope, checked_relational)
    candidate = None
    if checked_relational is not None:
        candidate = {
            "schema": "legal-source-typed-norm-candidate/v1",
            "interpretation_status": "unreviewed_partial_fragment_hypothesis",
            "expression": checked_relational["typed_expression"],
            "typed_expression_content_digest": checked_relational["typed_expression_content_digest"],
            "typed_expression_sha256": checked_relational["typed_expression_sha256"],
            "argument_roles": checked_relational["argument_roles"],
            "counts": checked_relational["counts"],
            "source_binding": None, "source_meaning_verified": False,
            "source_translation_performed": False,
        }
    report = {
        "schema": SCHEMA, "profile": PROFILE,
        "status": ("unreviewed_partial_interpretation_correspondence_retained" if candidate is not None
                   else "source_only_pending_typed_interpretation_retained"),
        "component_id": request["component_id"], "alternative_id": request["alternative_id"],
        "join_request": request, "join_request_raw_utf8": join_request_raw.decode("utf-8"),
        "input_pins": {
            "join_request_raw_sha256": expected_join_request_sha256,
            "join_request_raw_bytes": len(join_request_raw),
            "join_request_canonical_sha256": _digest(request, MAX_REQUEST_BYTES),
            "scope_report_full_canonical_sha256": expected_scope_report_sha256,
            "source_scope_input_pins": checked_scope["input_pins"],
            "relational_report_full_canonical_sha256": expected_relational_report_sha256,
            "relational_request_raw_sha256": expected_relational_request_sha256,
            "relational_request_raw_bytes": (len(relational_request_raw)
                                               if relational_request_raw is not None else None),
        },
        "source_scope_report": checked_scope,
        "source_custody": {
            "selected_unit_ref": checked_scope["input_pins"]["selected_unit_ref"],
            "source_records": checked_scope["source_records"],
            "source_selector": checked_scope["source_selector"],
            "source_context_packet": checked_scope["source_context_packet"],
        },
        "typed_candidate": candidate, "provenance_ledger": ledger,
        "original_unresolved": checked_scope["scope_declaration"]["unresolved"],
        "introduced_unresolved": request["introduced_unresolved"],
        "literal_accounting_complete": checked_scope["literal_accounting_complete"],
        "declared_semantic_coverage": checked_scope["declared_semantic_coverage"],
        "source_custody_linked": True, "source_meaning_selected": False,
        "source_translation_performed": False, "external_relational_source_binding": None,
        "original_context_preserved": True, "external_context_nominations_applied": False,
        "formal_norm_ast": None, "lowered_IR": None, "native_output_for_source": None,
        "graph": None, "lookup": None, "governing_use": None,
        "accepted_lookup": None, "governing_definition_use": None,
        "native_build_executed": False, "human_reviews": 0,
        "signatures_constructed": 0, "admissions": 0,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "masks": dict(checked_scope["masks"]), "authority": dict(AUTHORITY),
        "model_calls": 0, "training_calls": 0, "native_processes": 0,
        "producer_pins": pins,
        "limitations": [
            "Correspondence records caller hypotheses and exact source custody; it does not establish natural-language semantics.",
            "Every typed node has declared provenance; that inventory does not prove exhaustive legal dependencies or interpretation choices.",
            "Predicate argument roles, lexical binding, quantifier order and modal/connective structure are syntax facts, not resolved legal entities.",
            "All original unresolved source issues remain unchanged, including those touched by a typed hypothesis.",
            "Unanchored structure requires an explicitly introduced unresolved assumption; anchored hypotheses remain unreviewed.",
            "The external relational preparation remains source-unbound and its generated code is not supplied as statutory output.",
            "Original open context, source coverage and external contextual nominations are not adjudicated or promoted.",
            "Related alternatives share source material and cannot constitute independent training or evaluation cases.",
            "No source meaning selection, review, signer, governing-use edge, admitted graph, native execution or qualified target is supplied.",
        ],
    }
    retained = _wire(report, MAX_REPORT_BYTES)
    _check_producer_pins(pins)
    return json.loads(retained)


def source_typed_norm_join_sha256(report):
    """Hash the complete ordinary envelope without importing operation owners."""
    return _digest(report, MAX_REPORT_BYTES)


def validate_source_typed_norm_join_v1(
    report, scope_report, relational_report, join_request_raw, *,
    expected_report_sha256, **preparation_inputs,
):
    """Require independent output identity and full original-input replay."""
    supplied = _pinned_copy(report, expected_report_sha256, "complete join report", MAX_REPORT_BYTES)
    regenerated = prepare_source_typed_norm_join_v1(
        scope_report, relational_report, join_request_raw, **preparation_inputs)
    _need(_wire(supplied, MAX_REPORT_BYTES) == _wire(regenerated, MAX_REPORT_BYTES),
          "join proposal differs from complete authoritative regeneration")
    return regenerated


__all__ = ["prepare_source_typed_norm_join_v1", "source_typed_norm_join_sha256",
           "validate_source_typed_norm_join_v1"]
