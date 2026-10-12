"""Audit explicit duration occurrences, declared scopes and caller clocks.

This opt-in boundary consumes the existing canonical candidate and qualified
interpretation formats. It neither parses legal meaning nor emits logic. The
existing scope owner validates occurrences; this module checks an explicit join
from each canonical temporal facet to its actual declared leaf and an independently
supplied clock declaration. Matching character/UTF8 geometry is transport custody,
not evidence that an anchor authorizes a clock or that a deadline is legally true.

The initial profile is flat local within/minimum day/hour durations with discrete
evaluation-time clocks. Shared/nested scope, binders, calendar/business-day and
event-relative clocks are refused. No old parser, decoder or emitter is changed.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from . import canonical_statement_scope as scope

SCHEMA = "legal-duration-occurrence-bindings/v1"
VALIDATION_SCHEMA = "legal-duration-occurrence-binding-validation/v1"
PROFILE = "flat-local-explicit-evaluation-duration/v1"
INTERPRETATION_SCHEMA = "legal-canonical-qualified-interpretation/v1"
DECLARATION_SCOPE = "caller_supplied_interpretation_not_source_translation"
MAX_BYTES = 524288
MAX_NODES = 50000
MAX_DEPTH = 24
MAX_RULES = scope.MAX_RULES
GEOMETRY_FIELDS = {"origin", "source_sha256", "char_start", "char_end", "utf8_start", "utf8_end", "text"}
BINDING_FIELDS = {"rule_index", "temporal_index", "scope_rule_id", "scope_leaf_path", "occurrence_id", "duration_anchor", "clock_id"}
CLOCK_SEMANTICS = {"temporal_kind", "quantity", "unit", "time_domain", "origin", "lower_inclusive", "upper_inclusive"}
CLOCK_FIELDS = {"clock_id", "declaration_id", "declaration_scope", "scope_rule_id", "anchor", *CLOCK_SEMANTICS}
FALSE = dict.fromkeys(("qualified", "admitted", "accepted", "formalized", "proof_authority",
    "source_semantics_verified", "source_fidelity_established", "semantic_gold",
    "reviewer_authenticated", "source_context_custody_verified", "statutory_custody_verified",
    "clock_meaning_verified", "clock_unit_conversion_verified", "clock_origin_inferred",
    "temporal_origin_resolved", "scope_inferred", "native_lowering_performed", "lowering_authorized",
    "family_qualified", "all_logic_families_supported", "training_masks_emitted",
    "training_executed", "model_executed", "encoder_executed", "Lake_executed", "target_access"), False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _wire(value):
    remaining = MAX_NODES

    def visit(node, depth):
        nonlocal remaining
        remaining -= 1
        _require(remaining >= 0 and depth <= MAX_DEPTH, "duration binding JSON node/depth bound exceeded")
        if type(node) is dict:
            _require(all(type(key) is str for key in node), "plain JSON keys required")
            for key, child in node.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(node) is list:
            for child in node:
                visit(child, depth + 1)
        else:
            _require(node is None or type(node) in (str, int, bool), "integer-only ordinary JSON required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _require(len(raw) <= MAX_BYTES, "duration binding byte bound exceeded; no truncation")
    return raw


def digest(value):
    """Canonical JSON content SHA256, distinct from a physical file digest."""
    return hashlib.sha256(_wire(value)).hexdigest()


def parse_json_bytes(raw):
    """Read bounded integer-only UTF8 JSON, rejecting repeated object keys."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "bounded JSON bytes required")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def unsupported_number(value):
        raise ValueError("floating/nonfinite JSON numbers are unsupported")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_float=unsupported_number, parse_constant=unsupported_number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("strict integer-only UTF8 JSON required") from error
    _wire(value)
    return value


def _detach(value):
    return parse_json_bytes(_wire(value))


def _sha(value, label):
    _require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
             label + " lowercase SHA256 required")


def _text(value, label, maximum=4096, blank=False):
    _require(type(value) is str and "\x00" not in value and len(value) <= maximum
             and (bool(value.strip()) or blank and value == ""), "bounded " + label + " required")


def _index(value, label):
    _require(type(value) is int and value >= 0, label + " nonnegative integer required")


def _geometry(value, request, label, *, original=None):
    _closed(value, GEOMETRY_FIELDS, label + " geometry")
    _require(type(value["origin"]) is str and value["origin"] in {"source", "context"},
             label + " known source/context origin required")
    text = request["source_text"] if value["origin"] == "source" else request["context"]["text"]
    _sha(value["source_sha256"], label + " source")
    _require(value["source_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest(),
             label + " whole origin source SHA differs")
    for field in ("char_start", "char_end", "utf8_start", "utf8_end"):
        _index(value[field], label + " " + field)
    start, end = value["char_start"], value["char_end"]
    _require(0 <= start < end <= len(text) and value["text"] == text[start:end],
             label + " exact character occurrence differs")
    _require(value["utf8_start"] == len(text[:start].encode("utf-8"))
             and value["utf8_end"] == len(text[:end].encode("utf-8")),
             label + " exact UTF8 geometry differs")
    if original is not None:
        _require(value["origin"] == original["origin"] and start == original["start"]
                 and end == original["end"] and value["text"] == original["text"],
                 label + " mapped scope occurrence differs")


def _flat_leaves(node, facet, path):
    if node is None:
        return []
    if node["op"] == "leaf":
        return [(path, node["occurrence_id"])]
    if node["op"] == scope.OPERATORS[facet] and all(child["op"] == "leaf" for child in node["children"]):
        return [(f"{path}/children/{index}", child["occurrence_id"])
                for index, child in enumerate(node["children"])]
    raise ValueError("nested/nonflat qualifier scope is unsupported; no flattening")


def _candidate(candidate, request):
    _closed(candidate, {"candidate_id", "source_text", "source_sha256", "canonical_ir"}, "canonical candidate")
    _text(candidate["candidate_id"], "candidate_id", maximum=256)
    _require(candidate["source_text"] == request["source_text"], "candidate complete source differs from scope input")
    _sha(candidate["source_sha256"], "candidate source")
    _require(candidate["source_sha256"] == hashlib.sha256(request["source_text"].encode("utf-8")).hexdigest(),
             "candidate complete source SHA differs")
    _closed(candidate["canonical_ir"], {"rules"}, "canonical IR")
    rules = candidate["canonical_ir"]["rules"]
    _require(type(rules) is list and 0 < len(rules) <= MAX_RULES, "bounded canonical rules required")
    for rule in rules:
        _closed(rule, scope.FACETS, "canonical rule")
        _require(type(rule["modality"]) is str and rule["modality"] in {"O", "P", "F"}, "canonical modality required")
        for field in ("actor", "action", "object"):
            _text(rule[field], field, maximum=4096, blank=field == "object")
        for field in scope.QUALIFIERS:
            values = rule[field]
            _require(type(values) is list and len(values) <= 128, "bounded canonical qualifiers required")
            for literal in values:
                _text(literal, field)
            _require(values == sorted(set(values)), "canonical qualifier order/dedup differs; no normalization")
        _require(len(rule["temporal"]) <= 1, "at most one local duration per rule is supported")
    return rules


def _interpretation(interpretation, candidate):
    _closed(interpretation, {"schema", "candidate_id", "candidate_sha256", "source_sha256", "canonical_ir_sha256",
                            "mapping_sha256", "declaration_scope", "formulas"}, "existing qualified interpretation")
    _require(interpretation["schema"] == INTERPRETATION_SCHEMA and interpretation["declaration_scope"] == DECLARATION_SCOPE,
             "existing interpretation schema/scope differs")
    _require(interpretation["candidate_id"] == candidate["candidate_id"]
             and interpretation["candidate_sha256"] == digest(candidate)
             and interpretation["source_sha256"] == candidate["source_sha256"]
             and interpretation["canonical_ir_sha256"] == digest(candidate["canonical_ir"]),
             "interpretation candidate/source/canonical binding differs")
    _sha(interpretation["mapping_sha256"], "retained mapping")
    formulas = interpretation["formulas"]
    rules = candidate["canonical_ir"]["rules"]
    _require(type(formulas) is list and len(formulas) == len(rules), "complete ordered existing formula declarations required")
    for index, (formula, rule) in enumerate(zip(formulas, rules, strict=True)):
        _closed(formula, {"formula_index", "original_formula_sha256", "kind", "activation_scope", "conditions", "temporal",
                         "exception_scope", "exceptions"}, "existing formula declaration")
        _index(formula["formula_index"], "formula_index")
        _require(formula["formula_index"] == index and formula["kind"] == "activation_guarded_legal_rule",
                 "existing formula index/kind differs")
        _sha(formula["original_formula_sha256"], "retained original formula")
        temporal = formula["temporal"]
        if not rule["temporal"]:
            _require(temporal is None, "a non-temporal canonical role cannot become a duration")
        else:
            _closed(temporal, {"source_index", "source_text", *CLOCK_SEMANTICS}, "existing temporal interpretation")
            _index(temporal["source_index"], "temporal source_index")
            _require(temporal["source_index"] == len(rule["conditions"]) and temporal["source_text"] == rule["temporal"][0],
                     "existing canonical temporal index/literal differs")
    # Mapping/formula hashes and non-temporal expressions are retained exactly.
    # Their native validity remains with the current qualified owner, not here.
    return formulas


def _clock(clock, request):
    _closed(clock, CLOCK_FIELDS, "explicit clock declaration")
    for field in ("clock_id", "declaration_id", "scope_rule_id"):
        _text(clock[field], field, maximum=128)
    _require(clock["declaration_scope"] == DECLARATION_SCOPE, "clock declaration scope differs")
    _geometry(clock["anchor"], request, "clock declaration anchor")
    _require(type(clock["temporal_kind"]) is str and clock["temporal_kind"] in {"within_duration", "minimum_duration"},
             "unsupported explicit duration kind")
    _require(type(clock["quantity"]) is int and 1 <= clock["quantity"] <= 1000000,
             "positive bounded integer clock quantity required")
    _require(type(clock["unit"]) is str and clock["unit"] in {"day", "hour"}, "unsupported explicit clock unit")
    _require(clock["time_domain"] == "discrete_nat" and clock["origin"] == "caller_supplied_evaluation_time"
             and clock["lower_inclusive"] is True and clock["upper_inclusive"] is True,
             "unsupported clock origin/domain/endpoints; explicit closed evaluation clock required")
    duration = str(clock["quantity"]) + " " + clock["unit"] + ("s" if clock["quantity"] != 1 else "")
    return ("within " if clock["temporal_kind"] == "within_duration" else "for at least ") + duration


def prepare_duration_bindings(candidate, interpretation, scope_request, scope_declaration,
                              occurrence_bindings, clock_declarations, *, expected_candidate_sha256,
                              expected_interpretation_sha256, expected_scope_input_sha256,
                              expected_scope_declaration_sha256):
    """Return a sealed integrity report, requiring explicit complete caller maps.

    No occurrence is found by literal search. Missing, duplicated, exchanged or
    extra maps/clocks fail the whole join. Exact repeated literals remain distinct
    by rule, facet, leaf path, occurrence ID and original geometry. Clock anchors
    custody caller declarations only; they do not attest an evaluation event.
    Native interpretation syntax, emitted code and statutory review remain with
    their separate owners. This report never authorizes lowering or supervision.
    """
    candidate, interpretation, request, declaration, bindings, clocks = map(_detach,
        (candidate, interpretation, scope_request, scope_declaration, occurrence_bindings, clock_declarations))
    pins = {"candidate_sha256": expected_candidate_sha256, "interpretation_sha256": expected_interpretation_sha256,
            "scope_input_sha256": expected_scope_input_sha256, "scope_declaration_sha256": expected_scope_declaration_sha256}
    for label, expected, value in (("candidate", expected_candidate_sha256, candidate),
                                  ("interpretation", expected_interpretation_sha256, interpretation),
                                  ("scope input", expected_scope_input_sha256, request),
                                  ("scope declaration", expected_scope_declaration_sha256, declaration)):
        _sha(expected, "externally expected " + label)
        _require(digest(value) == expected, "externally expected " + label + " content differs")
    validation = scope.validate_scope_declaration(request, declaration, expected_input_sha256=expected_scope_input_sha256)
    _require(not declaration["binders"], "binder duration scope is unsupported")
    _require(declaration["coverage"]["declared_status"] == "complete" and not declaration["unresolved"],
             "complete declared coverage is required; no coverage inference")
    rules = _candidate(candidate, request)
    formulas = _interpretation(interpretation, candidate)
    declared_rules = declaration["rules"]
    _require(len(rules) == len(declared_rules), "complete ordered canonical/scope rule map differs")
    statement = declaration["statement_structure"]
    if statement["op"] == "rule":
        order = [statement["rule_id"]]
    elif statement["op"] == "all" and all(child["op"] == "rule" for child in statement["children"]):
        order = [child["rule_id"] for child in statement["children"]]
    else:
        raise ValueError("shared/nonflat statement duration scope is unsupported; no flattening")
    _require(order == [rule["rule_id"] for rule in declared_rules], "statement and canonical/scope rule order differs")
    table = {item["occurrence_id"]: item for item in declaration["occurrences"]}
    expected_sites = []
    for index, (rule, declared_rule) in enumerate(zip(rules, declared_rules, strict=True)):
        for facet in scope.CORE:
            identity = declared_rule["body"][facet]
            symbol = "" if identity is None else table[identity]["canonical_symbol"]
            _require(rule[facet] == symbol, "canonical core and actual declared role differ")
        for facet in scope.QUALIFIERS:
            leaves = _flat_leaves(declared_rule["qualifiers"][facet], facet, f"/rules/{index}/qualifiers/{facet}")
            _require(rule[facet] == [table[identity]["canonical_symbol"] for _, identity in leaves],
                     "canonical qualifier and actual declared facet/leaf order differ")
            if facet == "temporal":
                for temporal_index, (path, identity) in enumerate(leaves):
                    expected_sites.append((index, temporal_index, declared_rule["rule_id"], path, identity))
    temporal_ids = [site[4] for site in expected_sites]
    _require(len(temporal_ids) == len(set(temporal_ids)), "shared temporal occurrence is unsupported; explicit local custody required")
    temporal_anchors = [table[identity]["anchor"] for identity in temporal_ids]
    for index, anchor in enumerate(temporal_anchors):
        for other in temporal_anchors[index + 1:]:
            _require(anchor["origin"] != other["origin"] or anchor["end"] <= other["start"] or other["end"] <= anchor["start"],
                     "overlapping temporal occurrences are ambiguous in the local profile")
        for occurrence in table.values():
            other = occurrence["anchor"]
            if occurrence["facet"] != "temporal":
                _require(anchor["origin"] != other["origin"] or anchor["end"] <= other["start"] or other["end"] <= anchor["start"],
                         "duration overlaps a declared non-temporal role; ownership is ambiguous")
    _require(type(bindings) is list and len(bindings) == len(expected_sites), "complete exact duration occurrence map required")
    _require(type(clocks) is list and len(clocks) == len(expected_sites), "complete independent clock declaration inventory required")
    clock_table, clock_literals, declaration_ids = {}, {}, set()
    for clock in clocks:
        literal = _clock(clock, request)
        _require(clock["clock_id"] not in clock_table and clock["declaration_id"] not in declaration_ids,
                 "duplicate clock/declaration identity")
        clock_table[clock["clock_id"]] = clock
        clock_literals[clock["clock_id"]] = literal
        declaration_ids.add(clock["declaration_id"])
    used_clocks, joins = set(), []
    for binding, (index, temporal_index, rule_id, path, identity) in zip(bindings, expected_sites, strict=True):
        _closed(binding, BINDING_FIELDS, "duration occurrence binding")
        _index(binding["rule_index"], "rule_index")
        _index(binding["temporal_index"], "temporal_index")
        _require((binding["rule_index"], binding["temporal_index"], binding["scope_rule_id"],
                  binding["scope_leaf_path"], binding["occurrence_id"]) == (index, temporal_index, rule_id, path, identity),
                 "actual temporal rule/facet/leaf/occurrence binding differs")
        occurrence = table[identity]
        _geometry(binding["duration_anchor"], request, "duration anchor", original=occurrence["anchor"])
        literal = rules[index]["temporal"][temporal_index]
        _require(binding["duration_anchor"]["text"] == literal, "temporal literal differs from exact duration occurrence")
        clock_id = binding["clock_id"]
        _require(type(clock_id) is str and clock_id in clock_table and clock_id not in used_clocks,
                 "missing/duplicated independently supplied clock reference")
        clock = clock_table[clock_id]
        _require(clock["scope_rule_id"] == rule_id and clock_literals[clock_id] == literal,
                 "clock owner or explicit kind/quantity/unit differs from duration")
        _require(all(type(clock[key]) is type(formulas[index]["temporal"][key])
                     and clock[key] == formulas[index]["temporal"][key] for key in CLOCK_SEMANTICS),
                 "independent clock differs from unchanged interpretation")
        used_clocks.add(clock_id)
        joins.append({**deepcopy(binding), "temporal_literal": literal, "clock_declaration_id": clock["declaration_id"],
                      "clock_anchor": deepcopy(clock["anchor"]),
                      "declared_clock": {key: clock[key] for key in sorted(CLOCK_SEMANTICS)}})
    _require(used_clocks == set(clock_table), "unused independent clock declaration")
    result = {"schema": SCHEMA, "profile": PROFILE, "status": "joined_declared_duration_occurrences_only",
              "external_pins": pins, "candidate": candidate, "interpretation": interpretation,
              "scope_request": request, "scope_declaration": declaration, "occurrence_bindings": bindings,
              "clock_declarations": clocks, "joins": joins, "duration_count": len(joins), "rule_count": len(rules),
              "scope_validation_sha256": validation["content_sha256"],
              "geometry_units": {"characters": "unicode_character_half_open", "bytes": "UTF8_byte_half_open"},
              "interpretation_preserved_exactly": True, "explicit_maps_complete": True,
              "native_interpretation_validated": False, "statutory_custody": "separate_owner_not_assessed",
              "geometry_authority": "exact_source_context_integrity_not_legal_or_clock_meaning",
              "masks": dict.fromkeys(scope.MASKS, 0), "model_calls": 0, "prover_calls": 0, **FALSE}
    result["content_sha256"] = digest(result)
    _wire(result)
    return result


def validate_duration_bindings(report, candidate, interpretation, scope_request, scope_declaration,
                               occurrence_bindings, clock_declarations, **expected_pins):
    """Replay the complete report against separately retained original inputs."""
    report = _detach(report)
    replay = prepare_duration_bindings(candidate, interpretation, scope_request, scope_declaration,
                                        occurrence_bindings, clock_declarations, **expected_pins)
    _require(_wire(report) == _wire(replay), "duration binding report differs from exact replay")
    result = {"schema": VALIDATION_SCHEMA, "status": "validated_duration_binding_transport_only",
              "report_sha256": digest(report), "report_content_sha256": report["content_sha256"],
              "external_pins": deepcopy(report["external_pins"]), "duration_count": report["duration_count"],
              "masks": dict.fromkeys(scope.MASKS, 0), "model_calls": 0, "prover_calls": 0, **FALSE}
    result["content_sha256"] = digest(result)
    return result


__all__ = ["prepare_duration_bindings", "validate_duration_bindings", "digest", "parse_json_bytes"]
