"""Preserve declared normative occurrences and assess legacy transport gaps.

This bounded declaration schema is not a universal logic AST or a semantic
parser. It retains source/context spans, explicit attachment and inert binder
declarations. Validation checks data integrity and attachment, not whether
symbols, operators or opaque terms preserve source meaning. Compatibility
assessment emits neither a lowered formula nor approval of normalization.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

SCHEMA = "canonical-normative-scope-declaration/v1"
PROFILE = "normative-occurrence-scope/v1"
VALIDATION_SCHEMA = "canonical-normative-scope-validation/v1"
COMPATIBILITY_SCHEMA = "canonical-normative-flat-compatibility/v1"
INPUT_RECIPE = "sha256_sorted_compact_utf8_source_text_and_context/v1"
MAX_BYTES = 65536
MAX_JSON_DEPTH = 20
MAX_NODES = 25000
MAX_EXPRESSION_NODES = 1024
MAX_EXPRESSION_DEPTH = 6
MAX_OCCURRENCES = 512
MAX_RULES = 32
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = ("conditions", "exceptions", "temporal")
CORE = ("modality", "actor", "action", "object")
OPERATORS = {"conditions": "all", "exceptions": "any", "temporal": "all"}
MASKS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision", "proof_supervision", "fidelity_evaluation")
_FALSE = dict.fromkeys(("source_fidelity_established", "source_semantics_verified", "qualified", "accepted",
                       "proof_authority", "semantic_equivalence_assessed", "semantic_profile_validated",
                       "binder_terms_typechecked", "normalization_approved", "lowering_authorized",
                       "training_executed", "model_executed", "target_access"), False)
_FIELDS = {"schema", "family", "profile", "input", "input_sha256", "occurrences", "rules",
           "statement_structure", "binders", "coverage", "unresolved", "content_sha256"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _raw(value):
    remaining = MAX_NODES

    def visit(node, depth):
        nonlocal remaining
        remaining -= 1
        _require(remaining >= 0 and depth <= MAX_JSON_DEPTH, "scope JSON node/depth bound exceeded")
        if type(node) is dict:
            _require(all(type(key) is str for key in node), "plain JSON string keys required")
            for key, child in node.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(node) is list:
            for child in node:
                visit(child, depth + 1)
        elif type(node) is float:
            _require(math.isfinite(node), "finite JSON required")
        else:
            _require(node is None or type(node) in (str, int, bool), "plain ordinary JSON required")

    visit(value, 0)
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _require(len(data) <= MAX_BYTES, "scope payload exceeds bridge byte bound; no truncation")
    return data


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _hash(value, label):
    _require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
             label + " must be lowercase SHA256")


def _text(value, label, *, blank=False, maximum=4096):
    _require(type(value) is str and "\x00" not in value and len(value) <= maximum
             and (bool(value.strip()) or blank and value == ""), "bounded " + label + " required")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF8 " + label + " required") from error


def _list(value, label, maximum, *, nonempty=False):
    _require(type(value) is list and len(value) <= maximum and (not nonempty or value),
             "bounded " + label + " list required")


def _input(request):
    _closed(request, {"source_text", "context"}, "source/context input")
    _text(request["source_text"], "source_text", maximum=16384)
    context = request["context"]
    _closed(context, {"role", "text", "bindings", "sha256"}, "scope context")
    _require(type(context["role"]) is str and context["role"] in {
        "none_required", "declared_context", "required_unavailable"}, "known context role required")
    _text(context["text"], "context text", blank=True, maximum=16384)
    _require(type(context["bindings"]) is dict and context["bindings"] == {},
             "v1 context bindings must remain empty; resolved context has a separate owner")
    _hash(context["sha256"], "context sha256")
    _require(context["sha256"] == hashlib.sha256(context["text"].encode()).hexdigest(), "context digest mismatch")
    if context["role"] == "declared_context":
        _require(bool(context["text"].strip()), "declared_context requires supplied text")
    else:
        _require(context["text"] == "", "empty text required for this context role")


def _span(span, request):
    _closed(span, {"origin", "start", "end", "text", "offset_unit"}, "source/context span")
    _require(type(span["origin"]) is str and span["origin"] in {"source", "context"}, "known span origin required")
    _require(span["offset_unit"] == "unicode_character_half_open", "explicit character span unit required")
    text = request["source_text"] if span["origin"] == "source" else request["context"]["text"]
    _require(type(span["start"]) is int and type(span["end"]) is int
             and 0 <= span["start"] < span["end"] <= len(text), "exact nonempty character span required")
    _require(type(span["text"]) is str and span["text"] == text[span["start"]:span["end"]],
             "span differs from exact source/context occurrence")


def _validate(request, declaration, expected_input_sha256):
    _raw(request)
    _raw(declaration)
    _input(request)
    _hash(expected_input_sha256, "externally expected input SHA")
    _require(_digest(request) == expected_input_sha256, "externally expected source/context input differs")
    _closed(declaration, _FIELDS, "normative scope declaration")
    _require(declaration["schema"] == SCHEMA and declaration["family"] == "deontic"
             and declaration["profile"] == PROFILE, "scope schema/family/profile differs")
    _require(_raw(declaration["input"]) == _raw(request) and declaration["input_sha256"] == expected_input_sha256,
             "declaration source/context input binding differs")
    _hash(declaration["content_sha256"], "declaration content SHA")
    _require(declaration["content_sha256"] == _digest({k: v for k, v in declaration.items() if k != "content_sha256"}),
             "scope declaration checksum mismatch")
    occurrences = declaration["occurrences"]
    _list(occurrences, "occurrences", MAX_OCCURRENCES, nonempty=True)
    table = {}
    for occurrence in occurrences:
        _closed(occurrence, {"occurrence_id", "facet", "canonical_symbol", "anchor"}, "typed occurrence")
        _text(occurrence["occurrence_id"], "occurrence_id", maximum=128)
        _require(occurrence["occurrence_id"] not in table, "duplicate occurrence_id")
        _require(type(occurrence["facet"]) is str and occurrence["facet"] in (*FACETS, "binder_variable", "binder_domain"),
                 "known occurrence facet required")
        _text(occurrence["canonical_symbol"], "canonical_symbol")
        if occurrence["facet"] == "modality":
            _require(occurrence["canonical_symbol"] in {"O", "P", "F"}, "known normative modality required")
        _span(occurrence["anchor"], request)
        table[occurrence["occurrence_id"]] = occurrence
    used, attachments, expressions = set(), {}, [0]
    occurrence_sites, attachment_sites = {}, {}

    def occurrence_ref(identity, facet, site=None):
        _require(type(identity) is str and identity in table and table[identity]["facet"] == facet,
                 "unknown or wrong-facet occurrence reference")
        used.add(identity)
        if site is not None:
            occurrence_sites.setdefault(identity, set()).add(site)
        return {identity}

    def operator(node):
        if node["operator_anchor"] is not None:
            _span(node["operator_anchor"], request)

    def expression(node, facet, path, depth=0):
        if node is None:
            attachments[path] = set()
            attachment_sites[path] = set()
            return set()
        expressions[0] += 1
        _require(expressions[0] <= MAX_EXPRESSION_NODES and depth <= MAX_EXPRESSION_DEPTH,
                 "scope expression node/depth bound exceeded")
        _require(type(node) is dict and type(node.get("op")) is str, "tagged qualifier expression required")
        op = node["op"]
        if op == "leaf":
            _closed(node, {"op", "occurrence_id"}, "qualifier leaf")
            refs = occurrence_ref(node["occurrence_id"], facet, path)
            sites = {path}
        elif op in {"all", "any"}:
            _closed(node, {"op", "children", "operator_anchor"}, "qualifier connective")
            _list(node["children"], "qualifier children", 128, nonempty=True)
            operator(node)
            refs = set()
            sites = set()
            for i, child in enumerate(node["children"]):
                _require(child is not None, "connective cannot contain an absent child")
                child_path = f"{path}/children/{i}"
                refs |= expression(child, facet, child_path, depth + 1)
                sites |= attachment_sites[child_path]
        elif op == "not":
            _closed(node, {"op", "child", "operator_anchor"}, "qualifier negation")
            _require(node["child"] is not None, "negation requires a child")
            operator(node)
            refs = expression(node["child"], facet, path + "/child", depth + 1)
            sites = attachment_sites[path + "/child"]
        else:
            raise ValueError("unknown qualifier operator")
        attachments[path] = refs
        attachment_sites[path] = sites
        return refs

    def qualifier_set(value, path):
        _closed(value, QUALIFIERS, "local/shared qualifiers")
        refs = set()
        sites = set()
        for facet in QUALIFIERS:
            refs |= expression(value[facet], facet, path + "/" + facet)
            sites |= attachment_sites[path + "/" + facet]
        attachment_sites[path] = sites
        return refs

    rules = declaration["rules"]
    _list(rules, "rules", MAX_RULES, nonempty=True)
    rule_table, rule_refs, rule_sites = {}, {}, {}
    for index, rule in enumerate(rules):
        _closed(rule, {"rule_id", "body", "qualifiers"}, "scope rule")
        _text(rule["rule_id"], "rule_id", maximum=128)
        _require(rule["rule_id"] not in rule_table, "duplicate rule_id")
        _closed(rule["body"], CORE, "rule core references")
        refs = set()
        sites = set()
        path = f"/rules/{index}"
        for facet in CORE:
            if facet == "object" and rule["body"][facet] is None:
                continue
            site = path + "/body/" + facet
            refs |= occurrence_ref(rule["body"][facet], facet, site)
            sites.add(site)
        refs |= qualifier_set(rule["qualifiers"], path + "/qualifiers")
        sites |= attachment_sites[path + "/qualifiers"]
        attachments[path] = refs
        attachment_sites[path] = sites
        rule_refs[rule["rule_id"]] = refs
        rule_sites[rule["rule_id"]] = sites
        rule_table[rule["rule_id"]] = rule
    used_rules = []

    def statement(node, path, depth=0):
        expressions[0] += 1
        _require(expressions[0] <= MAX_EXPRESSION_NODES and depth <= MAX_EXPRESSION_DEPTH,
                 "statement expression node/depth bound exceeded")
        _require(type(node) is dict and type(node.get("op")) is str, "tagged statement expression required")
        op = node["op"]
        if op == "rule":
            _closed(node, {"op", "rule_id"}, "statement rule leaf")
            identity = node["rule_id"]
            _require(type(identity) is str and identity in rule_table, "unknown statement rule reference")
            used_rules.append(identity)
            refs = set(rule_refs[identity])
            sites = set(rule_sites[identity])
        elif op in {"all", "any"}:
            _closed(node, {"op", "children", "operator_anchor"}, "statement connective")
            _list(node["children"], "statement children", MAX_RULES, nonempty=True)
            operator(node)
            refs = set()
            sites = set()
            for i, child in enumerate(node["children"]):
                child_path = f"{path}/children/{i}"
                refs |= statement(child, child_path, depth + 1)
                sites |= attachment_sites[child_path]
        elif op == "attach":
            _closed(node, {"op", "body", "qualifiers"}, "shared qualifier attachment")
            refs = set(statement(node["body"], path + "/body", depth + 1))
            refs |= qualifier_set(node["qualifiers"], path + "/qualifiers")
            sites = attachment_sites[path + "/body"] | attachment_sites[path + "/qualifiers"]
        else:
            raise ValueError("unknown statement operator")
        attachments[path] = refs
        attachment_sites[path] = sites
        return refs

    statement(declaration["statement_structure"], "/statement_structure")
    _require(len(used_rules) == len(set(used_rules)) and set(used_rules) == set(rule_table),
             "statement structure must reference every rule exactly once")
    binders = declaration["binders"]
    _list(binders, "binders", 32)
    binder_ids, bound_ids = set(), set()
    for binder in binders:
        _closed(binder, {"binder_id", "quantifier", "variable_occurrence", "domain_occurrence",
                         "scope_path", "bound_occurrence_ids"}, "inert binder declaration")
        _text(binder["binder_id"], "binder_id", maximum=128)
        _require(binder["binder_id"] not in binder_ids, "duplicate binder_id")
        binder_ids.add(binder["binder_id"])
        _require(type(binder["quantifier"]) is str and binder["quantifier"] in {"forall", "exists"},
                 "known declared quantifier required")
        occurrence_ref(binder["variable_occurrence"], "binder_variable")
        occurrence_ref(binder["domain_occurrence"], "binder_domain")
        path = binder["scope_path"]
        _require(type(path) is str and path in attachments, "binder requires a known expression/rule attachment path")
        refs = binder["bound_occurrence_ids"]
        _list(refs, "bound_occurrence_ids", MAX_OCCURRENCES, nonempty=True)
        _require(all(type(ref) is str and ref in attachments[path] for ref in refs),
                 "bound occurrence escapes its declared attachment scope")
        _require(all(occurrence_sites.get(ref, set()) <= attachment_sites[path] for ref in refs),
                 "bound occurrence is also used outside its declared attachment scope")
        _require(len(refs) == len(set(refs)) and not bound_ids.intersection(refs),
                 "each bound occurrence requires one declared binder association")
        bound_ids.update(refs)
    _require(used == set(table), "orphan typed occurrence not attached to a rule/qualifier/binder")
    coverage = declaration["coverage"]
    _closed(coverage, {"declared_status", "segments"}, "declared coverage")
    _require(type(coverage["declared_status"]) is str and coverage["declared_status"] in {
        "complete", "partial", "unassessed"}, "known declared coverage status required")
    _list(coverage["segments"], "coverage segments", 128)
    for segment in coverage["segments"]:
        _closed(segment, {"span", "disposition", "rule_ids", "occurrence_ids", "reason"}, "coverage segment")
        _span(segment["span"], request)
        _text(segment["reason"], "coverage reason")
        _require(type(segment["disposition"]) is str and segment["disposition"] in {
            "represented", "unsupported", "unresolved"}, "known declared coverage disposition required")
        for field, ids in (("rule_ids", rule_table), ("occurrence_ids", table)):
            _list(segment[field], "coverage " + field, MAX_OCCURRENCES)
            _require(all(type(identity) is str and identity in ids for identity in segment[field])
                     and len(segment[field]) == len(set(segment[field])), "unknown/duplicate coverage reference")
        for identity in segment["occurrence_ids"]:
            anchor = table[identity]["anchor"]
            span = segment["span"]
            _require(anchor["origin"] == span["origin"]
                     and span["start"] <= anchor["start"] < anchor["end"] <= span["end"],
                     "coverage occurrence lies outside its declared source/context segment")
        if segment["disposition"] == "represented":
            _require(segment["rule_ids"] or segment["occurrence_ids"],
                     "represented coverage requires a declared rule or occurrence association")
    _list(declaration["unresolved"], "unresolved meaning", 128)
    for unresolved in declaration["unresolved"]:
        _closed(unresolved, {"code", "span", "reason"}, "unresolved meaning record")
        _text(unresolved["code"], "unresolved code", maximum=256)
        _text(unresolved["reason"], "unresolved reason")
        _span(unresolved["span"], request)
    if coverage["declared_status"] == "complete":
        _require(not declaration["unresolved"] and request["context"]["role"] != "required_unavailable"
                 and all(s["disposition"] == "represented" for s in coverage["segments"]),
                 "declared complete coverage cannot retain unsupported/unresolved meaning")
        for origin, text in (("source", request["source_text"]), ("context", request["context"]["text"])):
            end = 0
            spans = sorted((s["span"]["start"], s["span"]["end"]) for s in coverage["segments"]
                           if s["span"]["origin"] == origin)
            for start, stop in spans:
                _require(start <= end, "declared complete literal coverage has a gap")
                end = max(end, stop)
            _require(end == len(text), "declared complete literal coverage omits source/context characters")
    return table, rule_table


def validate_scope_declaration(request, declaration, *, expected_input_sha256):
    """Validate exact spans and structural attachment; preserve every occurrence."""
    table, rules = _validate(request, declaration, expected_input_sha256)
    result = {"schema": VALIDATION_SCHEMA, "status": "validated_scope_transport_only",
              "input_sha256": expected_input_sha256, "input_digest_recipe": INPUT_RECIPE,
              "declaration_content_sha256": declaration["content_sha256"], "declaration": deepcopy(declaration),
              "occurrence_count": len(table), "rule_count": len(rules), "binder_count": len(declaration["binders"]),
              "declared_coverage_status": declaration["coverage"]["declared_status"],
              "context_resolved": False, "verification_status": "pending", "admission_status": "pending",
              "masks": dict.fromkeys(MASKS, 0), "model_calls": 0, "prover_calls": 0, **_FALSE}
    # The validation wrapper can exceed the payload cap without changing the
    # payload. Its seal binds the small summary plus the original payload seal.
    result["content_sha256_scope"] = "summary_excluding_declaration_and_content_sha256"
    result["content_sha256"] = _digest({k: v for k, v in result.items() if k != "declaration"})
    return result


def assess_flat_profile_compatibility(declaration, *, byte_output_cap=4096):
    """Diagnose two legacy profiles, with no lowering or approved rewrite.

    The declaration's embedded input is self-bound here. An external input pin
    is required at validate_scope_declaration before using a received payload.
    Occurrence IDs, anchors and coverage always need the retained scope sidecar.
    """
    _raw(declaration)
    _closed(declaration, _FIELDS, "normative scope declaration")
    _require(type(byte_output_cap) is int and 3 <= byte_output_cap <= 32770,
             "byte_output_cap must be an integer from 3 to 32770")
    table, _ = _validate(declaration["input"], declaration, declaration["input_sha256"])
    issues = []

    def issue(path, disposition, code, targets=("canonical_roundtrip_ir_v1", "byte_proposal_v1")):
        issues.append({"path": path, "disposition": disposition, "code": code, "targets": list(targets)})

    issue("/occurrences", "sidecar_required", "occurrence_ids_and_anchors_not_in_flat_ir", ("canonical_roundtrip_ir_v1",))
    issue("/coverage", "sidecar_required", "coverage_and_scope_declaration_not_in_legacy_payload")
    context = declaration["input"]["context"]
    if context["role"] != "none_required":
        issue("/input/context", "unavailable", "context_has_no_qualified_flat_transport")
    if declaration["binders"]:
        issue("/binders", "unavailable", "binders_domains_and_attachment_not_in_flat_facets")
    if declaration["coverage"]["declared_status"] != "complete" or declaration["unresolved"]:
        issue("/coverage", "unavailable", "source_coverage_partial_unassessed_or_unresolved")
    statement = declaration["statement_structure"]
    expected_rule_order = [rule["rule_id"] for rule in declaration["rules"]]
    if statement["op"] == "rule":
        statement_order = [statement["rule_id"]]
    elif statement["op"] == "all" and all(child["op"] == "rule" for child in statement["children"]):
        statement_order = [child["rule_id"] for child in statement["children"]]
    else:
        statement_order = None
        issue("/statement_structure", "unavailable", "nonflat_statement_connective_or_shared_attachment")
    if statement_order is not None and statement_order != expected_rule_order:
        issue("/statement_structure", "normalization_required", "statement_and_occurrence_rule_order_differ")
    if len(declaration["rules"]) != 1:
        issue("/rules", "unavailable", "byte_profile_requires_exactly_one_rule", ("byte_proposal_v1",))
    values = []
    byte_anchors = []
    legacy_anchor_rows = []
    flat_qualifiers = True
    for index, rule in enumerate(declaration["rules"]):
        value = {}
        for facet in CORE:
            identity = rule["body"][facet]
            value[facet] = table[identity]["canonical_symbol"] if identity is not None else ""
            if identity is not None:
                anchor = table[identity]["anchor"]
                byte_anchors.append(anchor)
                legacy_anchor_rows.append({"field_path": f"/rules/{index}/{facet}", "facet": facet,
                                           "canonical_symbol": value[facet], "start": anchor["start"],
                                           "end": anchor["end"], "source_text": anchor["text"],
                                           "offset_unit": anchor["offset_unit"]})
                if len(value[facet]) > 512:
                    issue(f"/rules/{index}/body/{facet}", "unavailable", "byte_atom_character_limit", ("byte_proposal_v1",))
        for facet in QUALIFIERS:
            node = rule["qualifiers"][facet]
            if node is None:
                leaves = []
            elif node["op"] == "leaf":
                leaves = [node]
            elif node["op"] == OPERATORS[facet] and all(child["op"] == "leaf" for child in node["children"]):
                leaves = node["children"]
            else:
                leaves = None
                issue(f"/rules/{index}/qualifiers/{facet}", "unavailable", "qualifier_operator_or_nesting_not_flat_profile")
            if leaves is None:
                flat_qualifiers = False
                value[facet] = []
                continue
            symbols = [table[leaf["occurrence_id"]]["canonical_symbol"] for leaf in leaves]
            value[facet] = symbols
            byte_anchors.extend(table[leaf["occurrence_id"]]["anchor"] for leaf in leaves)
            for position, leaf in enumerate(leaves):
                occurrence = table[leaf["occurrence_id"]]
                anchor = occurrence["anchor"]
                legacy_anchor_rows.append({"field_path": f"/rules/{index}/{facet}/{position}", "facet": facet,
                                           "canonical_symbol": occurrence["canonical_symbol"],
                                           "start": anchor["start"], "end": anchor["end"],
                                           "source_text": anchor["text"], "offset_unit": anchor["offset_unit"]})
            if symbols != sorted(set(symbols)):
                issue(f"/rules/{index}/qualifiers/{facet}", "normalization_required", "legacy_qualifier_sort_or_dedup_loses_occurrences")
            if len(symbols) > 64 or any(len(symbol) > 512 for symbol in symbols):
                issue(f"/rules/{index}/qualifiers/{facet}", "unavailable", "byte_qualifier_count_or_atom_limit", ("byte_proposal_v1",))
        values.append(value)
    # Compare with the unchanged owner: duplicate rules are retained; only
    # ordering and qualifier normalization may change its facet arrays.
    from .canonical_contracts import CanonicalRoundTripIR

    normalized = CanonicalRoundTripIR.from_dict({"rules": values}).to_dict()["rules"] if flat_qualifiers else None
    if normalized is not None and normalized != values:
        issue("/rules", "normalization_required", "legacy_rule_or_qualifier_order_changes", ("canonical_roundtrip_ir_v1",))
    if any(anchor["origin"] != "source" for anchor in byte_anchors):
        issue("/occurrences", "unavailable", "byte_anchors_require_direct_source", ("byte_proposal_v1",))
    spans = sorted((anchor["start"], anchor["end"]) for anchor in byte_anchors if anchor["origin"] == "source")
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:], strict=False)):
        issue("/occurrences", "unavailable", "byte_anchors_overlap_or_share_a_mention", ("byte_proposal_v1",))
    # Check exact encoding limits with the unchanged byte owner only when all
    # structural premises hold. This transient candidate is never returned,
    # approved, written, or used as a formal target. Coverage remains separate.
    byte_capacity = {"checked": False, "configured_output_cap": byte_output_cap,
                     "payload_bytes": None, "required_token_count": None,
                     "assessment_scope": "legacy_facet_encoding_capacity_only"}
    structural_issues = [entry for entry in issues if "byte_proposal_v1" in entry["targets"]
                         and entry["path"] not in {"/coverage", "/input/context"}
                         and entry["disposition"] in {"unavailable", "normalization_required"}]
    if not structural_issues and context["role"] == "none_required":
        from .canonical_byte_codec import PROPOSAL_SCHEMA, inspect_encoding

        candidate = {"schema": PROPOSAL_SCHEMA,
                     "source_sha256": hashlib.sha256(declaration["input"]["source_text"].encode("utf-8")).hexdigest(),
                     "canonical_ir": {"rules": values},
                     "anchors": sorted(legacy_anchor_rows, key=lambda row: row["field_path"]),
                     "facet_operators": dict(OPERATORS), "single_rule_scope": True,
                     **dict.fromkeys(("target_access", "model_executed", "source_fidelity_established",
                                      "qualified", "proof_authority", "accepted"), False)}
        try:
            encoding = inspect_encoding(candidate, declaration["input"]["source_text"], output_cap=byte_output_cap)
        except ValueError:
            issue("/rules", "unavailable", "legacy_byte_owner_rejected_encoding_limits", ("byte_proposal_v1",))
        else:
            byte_capacity.update(checked=True, payload_bytes=encoding["payload_bytes"],
                                 required_token_count=encoding["required_token_count"])
            if encoding["outcome"] != "encoding_admitted":
                issue("/rules", "unavailable", "byte_complete_wire_exceeds_output_cap", ("byte_proposal_v1",))
    profiles = {}
    for target in ("canonical_roundtrip_ir_v1", "byte_proposal_v1"):
        relevant = [entry for entry in issues if target in entry["targets"]]
        blocked = any(entry["disposition"] == "unavailable" for entry in relevant)
        normalization = any(entry["disposition"] == "normalization_required" for entry in relevant)
        profiles[target] = {"status": "unavailable" if blocked else "normalization_required_unapproved" if normalization
                            else "flat_facets_fit_with_scope_sidecar",
                            "facet_transport_compatible_without_normalization": not blocked and not normalization,
                            "scope_sidecar_required": True, "standalone_scope_roundtrip_lossless": False,
                            "complete_legacy_encoding_qualified": False,
                            "issues": deepcopy(relevant)}
    result = {"schema": COMPATIBILITY_SCHEMA, "status": "assessed_transport_gaps_only",
              "declaration_content_sha256": declaration["content_sha256"], "input_sha256": declaration["input_sha256"],
              "input_pin_scope": "embedded_input_self_binding_only", "profiles": profiles, "issues": issues,
              "byte_encoding_capacity": byte_capacity,
              "lowered_ir": None, "masks": dict.fromkeys(MASKS, 0), "model_calls": 0, "prover_calls": 0, **_FALSE}
    result["content_sha256"] = _digest(result)
    return result


__all__ = ["validate_scope_declaration", "assess_flat_profile_compatibility"]
