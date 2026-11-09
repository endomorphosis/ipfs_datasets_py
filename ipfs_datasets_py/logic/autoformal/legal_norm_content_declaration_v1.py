"""Unsigned proposed content over independently pinned historical evidence.

Only retained JSON relationships are checked. Historical producers, alternatives
and unresolved obligations remain unchanged. This operation does not reexecute
source/definition owners, authenticate declarations, select meanings or apply a
definition. A proposed positive declaration leaves every semantic mask zero.
"""
from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
import re

from . import legal_paired_manifest_inventory_v1 as transport
from . import legal_norm_scope_correspondence_v1 as contexts
from . import legal_norm_interpretation_review_v1 as review_schema

REQUEST_SCHEMA = "legal-norm-content-declaration-request/v1"
SCHEMA = "legal-norm-content-declaration-preparation/v1"
INPUT_SCOPE = "retained_historical_evidence_only"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_TARGETS = 512
MAX_OBLIGATIONS = 512
MAX_DEFINITIONS = 16
MAX_LINKS = 128
MAX_REFS = 64
SEMANTIC_QUESTIONS = review_schema.SEMANTIC_QUESTIONS
AUTHORITY = dict.fromkeys(("source_reexecution_verified", "definition_reexecution_verified",
    "source_semantics_verified", "complete_meaning_unit_verified", "declaration_authenticated",
    "review_verified", "interpretation_selected", "definition_applicability_verified",
    "definition_substitution_verified", "source_context_closed", "consumer_dispatched",
    "training_qualified", "evaluation_gold_qualified", "admitted", "formalized",
    "proof_authority", "Lean_admitted", "published"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_PRODUCER_PATHS = tuple(Path(module.__file__).resolve() for module in (transport, contexts, review_schema))
_PRODUCER_PATHS += (Path(__file__).resolve(),)
_IMPORT_PINS = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in _PRODUCER_PATHS}
_keys, _read_json, _wire = transport._keys, transport._read_json, transport._wire


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(_wire(value, MAX_REPORT_BYTES))


def _same(left, right):
    return _wire(left, MAX_REPORT_BYTES) == _wire(right, MAX_REPORT_BYTES)


def _pin(value):
    _need(type(value) is str and _SHA.fullmatch(value), "exact lowercase SHA256 required")


def _text(value, *, empty=False):
    _need(type(value) is str and len(value) <= 8192 and (empty or bool(value.strip())),
          "bounded explicit text required")


def _freshness():
    _need({str(path): _sha(path.read_bytes()) for path in _PRODUCER_PATHS} == _IMPORT_PINS,
          "content declaration producer or JSON helper changed since import")
    return dict(_IMPORT_PINS)


def _unqualified(value):
    if type(value) is dict:
        for key, child in value.items():
            if key == "authority":
                _need(type(child) is dict and bool(child) and all(flag is False for flag in child.values()),
                      "retained authority must remain explicitly false")
            elif key.endswith("_mask"):
                _need(type(child) is int and child == 0, "retained masks must be integer zero")
            elif key in {"masks", "field_masks"}:
                _need(type(child) is dict and all(type(flag) is int and flag == 0 for flag in child.values()),
                      "retained field masks must be integer zero")
            elif key in {"selected_interpretation", "governing_definition_use"}:
                _need(child is None, "retained interpretation or governing use must remain unselected")
            _unqualified(child)
    elif type(value) is list:
        for child in value:
            _unqualified(child)


def _mapping(fragment):
    """Inventory typed paths only; native translation is historical evidence."""
    _need(fragment.get("profile") == "authored-object-relational-deontic/v1", "unsupported retained relational profile")
    expression = fragment["typed_expression"]
    _need(type(expression) is dict and type(expression.get("root")) is dict, "complete typed expression root required")
    expected, identities, binders = [], set(), set()
    def visit(node, path, bound):
        _need(type(node) is dict and len(expected) < MAX_TARGETS, "bounded complete typed nodes required")
        kind, identity = node.get("kind"), node.get("node_id")
        _text(identity)
        _need(identity not in identities, "duplicate typed node or extension identity")
        identities.add(identity)
        expected.append({"typed_path": path, "node_id": identity, "kind": kind})
        arguments, declarations = node.get("arguments", []), node.get("binders", [])
        _need(type(arguments) is list and type(declarations) is list, "ordered typed children required")
        if kind == "variable":
            _need(not arguments and not declarations and node.get("symbol") in bound, "bound variable occurrence required")
            return
        if kind == "predicate":
            _need(not declarations and bool(arguments) and all(type(child) is dict and child.get("kind") == "variable" for child in arguments),
                  "ordered bound-variable predicate arguments required")
            _need(type(node.get("symbol")) is str and _NAME.fullmatch(node["symbol"]), "explicit predicate symbol required")
            for index, child in enumerate(arguments):
                visit(child, path + "/arguments/" + str(index), bound)
            return
        if kind in {"and", "or", "implies", "iff", "not"}:
            _need(not declarations and len(arguments) == (1 if kind == "not" else 2), "exact connective arity required")
            for index, child in enumerate(arguments):
                visit(child, path + "/arguments/" + str(index), bound)
            return
        if kind in {"forall", "exists"}:
            _need(len(arguments) == len(declarations) == 1, "single binder and quantified body required")
            binder = declarations[0]
            _need(type(binder) is dict, "explicit binder required")
            name = binder.get("name")
            _need(type(name) is str and _NAME.fullmatch(name) and name not in binders
                  and type(binder.get("sort")) is dict and binder["sort"].get("name") == "Object",
                  "distinct Object binder required")
            binders.add(name)
            expected.append({"typed_path": path + "/binders/0", "binder_name": name,
                "kind": "binder", "typed_sort": "Object", "native_sort": None})
            visit(arguments[0], path + "/arguments/0", bound | {name})
            return
        _need(kind == "extension" and not arguments and not declarations, "unsupported retained AST constructor")
        extension = node.get("extension")
        _need(type(extension) is dict and extension.get("payload_schema") == "legacy.deontic/v1"
              and type(extension.get("payload")) is dict
              and type(extension.get("children")) is list and len(extension["children"]) == 1,
              "single existing deontic extension required")
        operator, extension_id = extension["payload"].get("letter"), extension.get("node_id")
        _text(extension_id)
        _need(operator in {"O", "P", "F"} and extension_id not in identities, "exact distinct modal extension required")
        identities.add(extension_id)
        expected.append({"typed_path": path + "/extension", "node_id": extension_id,
            "kind": "legacy.deontic/v1", "operator": operator})
        visit(extension["children"][0], path + "/extension/children/0", bound)
    visit(expression["root"], "/root", set())
    mapping = fragment["structural_mapping"]
    _need(binders and type(mapping) is list and len(mapping) == len(expected) <= MAX_TARGETS,
          "complete ordered typed mapping differs from retained AST")
    for row, target in zip(mapping, expected):
        _keys(row, set(target) | {"native_path"}, "retained structural target")
        _need(type(row["native_path"]) is str and len(row["native_path"]) <= 8192
              and _same({key: row[key] for key in target}, target), "exact typed path/node/binder differs")
    _need(type(fragment["native_ast"]) is dict, "complete retained native AST required")
    return mapping


def _retained(preparation, evidence, request):
    _need(preparation.get("schema") == "legal-norm-interpretation-review-evidence/v1"
          and evidence.get("schema") == "legal-norm-definition-evidence/v1"
          and evidence.get("profile") == "unsigned-source-linked-term-definition-nominations/v1",
          "supported retained preparation and definition evidence required")
    _unqualified(preparation)
    _unqualified(evidence)
    _need(preparation["original_signatures_cover_norm_review"] is False
          and all(evidence[key] is False for key in ("original_signatures_cover_companion",
              "all_norm_term_uses_enumerated", "native_ast_rewritten")),
          "retained unsigned and non-exhaustive evidence scope required")
    for retained in (preparation, evidence, preparation["correspondence"]):
        _need(type(retained.get("authority")) is dict and bool(retained["authority"])
              and type(retained.get("training_mask")) is int and retained["training_mask"] == 0
              and type(retained.get("evaluation_gold_mask")) is int and retained["evaluation_gold_mask"] == 0,
              "explicit retained authority and zero masks required")
    correspondence = preparation["correspondence"]
    _need(correspondence.get("schema") == "legal-norm-scope-correspondence-report/v1"
          and correspondence["alternative_id"] == request["candidate_id"], "exact retained alternative required")
    fragment, scope = correspondence["relational_fragment"], correspondence["source_scope"]
    _need(scope["declared_semantic_coverage"] in {"partial", "unassessed"}
          and scope["scope_declaration"]["coverage"]["declared_status"] == scope["declared_semantic_coverage"]
          and _same(correspondence["retained_unresolved"], scope["scope_declaration"]["unresolved"]),
          "retained partial coverage and unresolved population must remain unchanged")
    targets = _mapping(fragment)
    _need(_digest(correspondence) == preparation["correspondence_sha256"]
          and _digest(fragment["typed_expression"]) == preparation["ast_sha256"]
          and _digest(fragment["native_ast"]) == preparation["native_ast_sha256"], "retained preparation cross-commitment differs")
    inventory = contexts._typed_contexts(fragment)
    _need(_same(inventory, correspondence["typed_context_inventory"]), "full typed binder/role/ancestry inventory differs")
    typed_rows, source_rows = correspondence["request"]["typed_rows"], correspondence["request"]["source_rows"]
    anchors = scope["anchor_mappings"]
    _need(type(typed_rows) is list and type(source_rows) is list and type(anchors) is list
          and len(anchors) <= MAX_TARGETS and len({row["declaration_path"] for row in anchors}) == len(anchors)
          and _same([row["target"] for row in typed_rows], targets)
          and _same([row["anchor_mapping"] for row in source_rows], anchors), "complete ordered source/typed population differs")
    by_path = {target["typed_path"]: target for target in targets}
    inverse = {path: [] for path in by_path}
    for row in source_rows:
        seen = set()
        for target in row["targets"]:
            path = target["typed_path"]
            _need(path in by_path and path not in seen and _same(target, by_path[path]), "exact unique source-linked target required")
            seen.add(path)
            inverse[path].append(row["anchor_mapping"]["declaration_path"])
    for row in typed_rows:
        paths = inverse[row["target"]["typed_path"]]
        _need(_same(row["source_paths"], paths) and row["disposition"] == ("source_linked" if paths else "authored_scaffolding"),
              "complete inverse typed/source mapping differs")
    counts = {"typed_targets": len(targets), "source_anchors": len(anchors),
        "proposed_links": sum(len(row["targets"]) for row in source_rows),
        "authored_scaffolding": sum(not row["source_paths"] for row in typed_rows)}
    _need(_same(correspondence["counts"], counts), "retained correspondence denominator differs")
    obligations = preparation["obligations"]
    expected_obligations = [{"slot_id": row["slot_id"], "kind": "original_context", "original": row}
        for row in scope["source_context_packet"]["dependency_slots"]]
    expected_obligations += [{"slot_id": "norm-issue:" + review_schema.norm_review_sha256([preparation["correspondence_sha256"], index, issue]),
        "kind": "original_unresolved_issue", "original": issue}
        for index, issue in enumerate(correspondence["retained_unresolved"])]
    expected_obligations += [{"slot_id": "norm-question:" + review_schema.norm_review_sha256([preparation["correspondence_sha256"], question]),
        "kind": "interpretation_question", "question": question} for question in SEMANTIC_QUESTIONS]
    _need(type(obligations) is list and len(obligations) <= MAX_OBLIGATIONS
          and _same(obligations, expected_obligations)
          and _same(preparation["context_slot_ids"], [row["slot_id"] for row in obligations])
          and len({row["slot_id"] for row in obligations}) == len(obligations), "complete distinct ordered obligations required")
    for key, value in (("norm_preparation_sha256", request["norm_preparation_sha256"]),
        ("norm_correspondence_sha256", preparation["correspondence_sha256"]), ("norm_scope_id", preparation["scope_id"]),
        ("norm_ast_sha256", preparation["ast_sha256"]), ("norm_native_ast_sha256", preparation["native_ast_sha256"]),
        ("source_context", preparation["context_evidence"]), ("norm_obligations", obligations),
        ("original_unresolved", correspondence["retained_unresolved"]),
        ("original_context_slots", scope["source_context_packet"]["dependency_slots"])):
        _need(_same(evidence[key], value), "definition evidence cross-link differs: " + key)
    unit = scope["source_records"]["unit"]
    source_target = preparation["context_evidence"]["target"]
    _need(type(unit["ordinal"]) is int and _same(source_target["subject_ref"],
          {"kind": "unit", "index": unit["ordinal"], "sha256": _digest(unit)})
          and all(_same(source_target[key], unit[key]) for key in ("source_occurrence_ref", "context_ref")),
          "exact source unit/occurrence/context reference differs")
    definitions, links = evidence["definitions"], evidence["links"]
    _need(type(definitions) is list and 0 < len(definitions) <= MAX_DEFINITIONS
          and type(links) is list and 0 < len(links) <= MAX_LINKS, "bounded complete definition/link population required")
    endpoints = {row["alternative_id"]: row for row in definitions}
    _need(len(endpoints) == len(definitions), "duplicate definition alternative identity")
    groups, seen_links, referenced = {}, set(), set()
    for link in links:
        offered = link["request_link"]
        target, alternative = offered["target"], offered["alternative_id"]
        path = target["typed_path"]
        _need(path in by_path and _same(target, by_path[path]) and target["kind"] in {"variable", "predicate"}
              and alternative in endpoints, "exact existing typed target and definition alternative required")
        identity = (path, alternative)
        _need(identity not in seen_links, "duplicate exact target/definition link")
        seen_links.add(identity)
        referenced.add(alternative)
        row, context = typed_rows[list(by_path).index(path)], inventory[list(by_path).index(path)]
        expected_sources = [source for source in source_rows if source["anchor_mapping"]["declaration_path"] in row["source_paths"]]
        _need(row["disposition"] == "source_linked" and _same(link["typed_row"], row)
              and _same(offered["source_paths"], row["source_paths"]) and _same(link["typed_context"], context)
              and _same(link["typed_node"], contexts._at(fragment["typed_expression"], path))
              and _same(link["source_rows"], expected_sources) and _same(link["norm_source_target"], source_target),
              "exact typed-use source/node/binder context differs")
        _need(offered["nomination_sha256"] == _digest(link["nomination"])
              and any(_same(link["nomination"], row) for row in preparation["context_evidence"]["nominations"]),
              "complete retained contextual nomination differs")
        nomination = link["nomination"]["nomination"]
        _need(nomination["target_bundle_sha256"] == source_target["bundle_sha256"]
              and _same(nomination["target_subject_ref"], source_target["subject_ref"]),
              "nomination targets another retained source unit")
        for key, record in (("definition_term_ref", "term_record"), ("definition_ast_ref", "ast_record")):
            body = endpoints[alternative][record]
            _need(_same(link[key], {"record_cid": body["record_cid"], "sha256": _digest(body)}), "definition record reference differs")
        groups.setdefault(path, {"target": target, "typed_context": context, "links": []})["links"].append(link)
    _need(referenced == set(endpoints), "definition alternative population is not completely referenced")
    _need(_same(evidence["counts"], {"alternatives": len(definitions), "links": len(links),
        "distinct_typed_uses": len(groups), "supplied_definition_assessments": sum(
            row["review_evidence"]["assessment"] is not None for row in definitions)}), "retained definition denominator differs")
    return list(groups.values()), unit


def _refs_and_reason(row, proposed):
    _text(row["rationale"], empty=not proposed)
    refs = row["evidence_refs"]
    _need(type(refs) is list and len(refs) <= MAX_REFS and (not proposed or bool(refs)),
          "bounded declared evidence references required for proposed decisions")
    seen = set()
    for ref in refs:
        _keys(ref, {"artifact_id", "sha256"}, "declared evidence reference")
        _text(ref["artifact_id"])
        _pin(ref["sha256"])
        _need(ref["artifact_id"] not in seen, "duplicate declared evidence identity")
        seen.add(ref["artifact_id"])


def prepare_norm_content_declaration(request_raw, norm_preparation_raw, definition_evidence_raw, *, expected_request_sha256):
    """Prepare proposed unsigned declarations; verify retained JSON custody only."""
    _pin(expected_request_sha256)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256, "request bytes differ from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "content declaration request")
    _keys(request, {"schema", "input_scope", "candidate_id", "norm_preparation_raw_sha256", "norm_preparation_sha256",
        "definition_evidence_raw_sha256", "definition_evidence_sha256", "interpretation", "meaning_unit",
        "coverage_decisions", "definition_decisions"}, "content declaration request")
    _need(request["schema"] == REQUEST_SCHEMA and request["input_scope"] == INPUT_SCOPE, "unsupported unsigned retained-input scope")
    _text(request["candidate_id"])
    parsed = []
    for label, raw in (("norm_preparation", norm_preparation_raw), ("definition_evidence", definition_evidence_raw)):
        for field in (label + "_raw_sha256", label + "_sha256"):
            _pin(request[field])
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_INPUT_BYTES and _sha(raw) == request[label + "_raw_sha256"],
              "retained input bytes differ: " + label)
        value = _read_json(raw, MAX_INPUT_BYTES, label)
        _need(type(value) is dict and _digest(value) == request[label + "_sha256"], "retained canonical pin differs: " + label)
        parsed.append(value)
    before = _freshness()
    preparation, evidence = parsed
    try:
        groups, unit = _retained(preparation, evidence, request)
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError("complete retained structural evidence required") from error
    interpretation, meaning = request["interpretation"], request["meaning_unit"]
    _keys(interpretation, {"disposition", "typed_expression_sha256", "rationale"}, "interpretation declaration")
    _need(type(interpretation["disposition"]) is str
          and interpretation["disposition"] in {"pending", "proposed_support", "proposed_reject"}
          and interpretation["typed_expression_sha256"] == preparation["ast_sha256"], "exact unselected interpretation declaration required")
    _text(interpretation["rationale"], empty=interpretation["disposition"] == "pending")
    _keys(meaning, {"source_unit_sha256", "coverage", "legal_as_of", "rationale"}, "meaning-unit declaration")
    _need(meaning["source_unit_sha256"] == _digest(unit) and type(meaning["coverage"]) is str
          and meaning["coverage"] in {"unassessed", "partial"},
          "exact unestablished source-unit declaration required")
    if meaning["legal_as_of"] is not None:
        _need(type(meaning["legal_as_of"]) is str and date.fromisoformat(meaning["legal_as_of"]).isoformat() == meaning["legal_as_of"],
              "canonical legal-as-of civil date required")
    _text(meaning["rationale"], empty=meaning["coverage"] == "unassessed" and meaning["legal_as_of"] is None)
    coverage = request["coverage_decisions"]
    _need(type(coverage) is list and len(coverage) == len(preparation["obligations"]), "complete ordered coverage declarations required")
    for row, obligation in zip(coverage, preparation["obligations"]):
        _keys(row, {"slot_id", "disposition", "evidence_refs", "rationale"}, "coverage declaration")
        _need(row["slot_id"] == obligation["slot_id"] and type(row["disposition"]) is str and row["disposition"] in
              {"pending", "proposed_resolved", "proposed_not_applicable"}, "exact ordered obligation declaration required")
        _refs_and_reason(row, row["disposition"] != "pending")
    decisions = request["definition_decisions"]
    _need(type(decisions) is list and len(decisions) == len(groups), "complete ordered typed-use declarations required")
    for row, group in zip(decisions, groups):
        _keys(row, {"target", "disposition", "alternative_id", "link_sha256", "evidence_refs", "rationale"}, "definition declaration")
        _need(_same(row["target"], group["target"]) and type(row["disposition"]) is str and row["disposition"] in
              {"pending", "proposed_applicable", "proposed_not_applicable"}, "exact ordered typed-use declaration required")
        if row["disposition"] == "proposed_applicable":
            _pin(row["link_sha256"])
            _need(any(row["alternative_id"] == link["request_link"]["alternative_id"]
                      and row["link_sha256"] == _digest(link) for link in group["links"]), "exact complete target/alternative link required")
        else:
            _need(row["alternative_id"] is None and row["link_sha256"] is None, "unselected declaration requires null definition/link")
        _refs_and_reason(row, row["disposition"] != "pending")
    report = {"schema": SCHEMA, "input_scope": INPUT_SCOPE, "request": request,
        "request_raw_utf8": request_raw.decode("utf-8"), "request_sha256": expected_request_sha256,
        "retained_norm_preparation": preparation, "retained_definition_evidence": evidence,
        "definition_uses": groups, "meaning_unit_id": None, "selected_occurrence": None, "accepted_interpretation": None,
        "governing_definition_use": None, "typed_definition_application_status": "unsupported_requires_separate_adapter",
        "declaration_status": "unsigned_proposed_content", "evidence_reference_status": "declared_not_verified",
        "current_upstream_reexecution_performed": False, "typed_native_equivalence_reexecution": False,
        "original_subjects_and_producer_pins_unchanged": True,
        "counts": {"typed_targets": len(preparation["correspondence"]["relational_fragment"]["structural_mapping"]),
            "source_anchors": len(preparation["correspondence"]["source_scope"]["anchor_mappings"]),
            "obligations": len(coverage), "definition_alternatives": len(evidence["definitions"]),
            "definition_links": len(evidence["links"]), "distinct_typed_uses": len(groups),
            "established_meaning_units": 0, "accepted_interpretations": 0, "applied_definition_uses": 0},
        "blockers": ["historical_inputs_not_current_owner_source_replay", "unsigned_declarations_not_authenticated_review",
            "meaning_unit_unestablished", "source_context_and_coverage_unresolved", "definition_applicability_unverified",
            "typed_definition_application_requires_separate_adapter", "consumer_exposure_and_split_unbound"],
        "authority": dict(AUTHORITY), "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0,
        "evaluation_gold_mask": 0, "producer_pins": before,
        "producer_pins_scope": "content_preparation_and_pure_JSON_helpers_only_not_historical_execution_closure"}
    _need(_digest(preparation) == request["norm_preparation_sha256"]
          and _digest(evidence) == request["definition_evidence_sha256"], "retained snapshots changed during preparation")
    raw = _wire(report, MAX_REPORT_BYTES)
    _need(_same(_freshness(), before), "content declaration producers changed during preparation")
    return _read_json(raw, MAX_REPORT_BYTES, "content declaration preparation")


def norm_content_declaration_sha256(report):
    return _digest(report)


def validate_norm_content_declaration(report, request_raw, norm_preparation_raw, definition_evidence_raw, *,
        expected_request_sha256, expected_report_sha256):
    """Regenerate from the same complete retained inputs; replay no upstream owner."""
    _pin(expected_report_sha256)
    offered = _read_json(report if type(report) is bytes else _wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "content report")
    _need(_digest(offered) == expected_report_sha256, "content report differs from independent pin")
    expected = prepare_norm_content_declaration(request_raw, norm_preparation_raw, definition_evidence_raw,
                                                expected_request_sha256=expected_request_sha256)
    _need(_same(offered, expected), "content report differs from full retained-input regeneration")
    return expected
