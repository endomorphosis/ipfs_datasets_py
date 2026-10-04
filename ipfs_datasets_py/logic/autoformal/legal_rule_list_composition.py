"""Source-bound composition of explicitly declared independent legal clauses.

This is output plumbing for a future segmenter, not a segmenter or a semantic
parser. Each declared clause supplies exactly one rule and explicit copied-atom
coordinates. Source order and repeated rule occurrences survive canonical rule
sorting through a bijective occurrence ledger. No qualifier normalization,
cross-clause inheritance, shared scope, or nested scope is inferred.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re

from . import legal_canonical_calendar as calendar
from ..legal_ir import canonical_contracts as contracts

SCHEMA = "legal-source-rule-list-composition/v1"
PLAN_SCHEMA = "legal-flat-clause-source-plan/v1"
MAX_RULES = 64
MAX_SOURCE_BYTES = 1_000_000
MAX_CLAUSE_CHARACTERS = 16_384
MAX_CLAUSE_TOKENS = 256
MAX_TOKEN_BYTES = 2048
MAX_WIRE_BYTES = 8 * 1024**2
FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FIELDS[4:]
SPAN_FIELDS = FIELDS[1:]
FLAT_SCOPE = {"kind": "independent_flat_rule", "parent_clause_id": None, "shared_qualifier_scope": None}
FALSE = {"segmentation_learned": False, "segmentation_semantics_verified": False,
    "source_semantics_verified": False, "modality_source_semantics_verified": False,
    "qualified": False, "admitted": False, "proof_authority": False}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKENS = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite bounded JSON required") from error
    _require(len(raw) <= MAX_WIRE_BYTES, "composition JSON exceeds byte bound")
    return raw


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def text_sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _pins():
    return calendar.producer_pins() | {str(Path(contracts.__file__).resolve()): hashlib.sha256(Path(contracts.__file__).read_bytes()).hexdigest(),
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    _require(_pins() == _IMPORTED_PINS, "rule-list composition producer changed since import")
    return dict(_IMPORTED_PINS)


def _source(source):
    _closed(source, {"candidate_id", "source_text", "source_sha256"}, "source document")
    _require(type(source["candidate_id"]) is str and source["candidate_id"].strip()
        and len(source["candidate_id"]) <= 256, "bounded nonblank document identity required")
    text = source["source_text"]
    _require(type(text) is str and text.strip() and len(text.encode()) <= MAX_SOURCE_BYTES, "bounded nonblank source text required")
    _require(source["source_sha256"] == text_sha256(text), "complete source hash differs")
    return json.loads(_wire(source))


def _scope(value):
    _require(_wire(value) == _wire(FLAT_SCOPE), "unsupported nested, dependent, or shared qualifier scope; explicit independent flat rule required")


def prepare_source_plan(source, clauses):
    """Bind a caller's clause inventory without inferring its legal correctness.

    Clauses are ordered, non-overlapping intervals; uncovered characters must be
    whitespace. This proves textual inventory coverage, not that a caller found
    every norm or correctly classified a clause as semantically independent.
    """
    producer_pins()
    source = _source(source)
    text = source["source_text"]
    _require(type(clauses) is list and 1 <= len(clauses) <= MAX_RULES, "one to64 declared clauses required")
    rows, seen, cursor, gaps = [], set(), 0, []
    for ordinal, item in enumerate(clauses):
        _closed(item, {"clause_id", "char_start", "char_end", "scope"}, "clause declaration")
        identity = item["clause_id"]
        _require(type(identity) is str and identity.strip() and len(identity) <= 128 and identity not in seen, "bounded unique clause identity required")
        seen.add(identity)
        _scope(item["scope"])
        start, end = item["char_start"], item["char_end"]
        _require(type(start) is int and type(end) is int and cursor <= start < end <= len(text), "ordered nonoverlapping clause offsets required")
        gap = text[cursor:start]
        _require(not gap.strip(), "unassigned non-whitespace source text; dropped clause or uncovered separator")
        if gap:
            gaps.append({"char_start": cursor, "char_end": start, "source_sha256": text_sha256(gap)})
        clause = text[start:end]
        _require(clause == clause.strip() and clause and len(clause) <= MAX_CLAUSE_CHARACTERS, "bounded trimmed clause text required")
        tokens = list(_TOKENS.finditer(clause))
        _require(1 <= len(tokens) <= MAX_CLAUSE_TOKENS and all(len(t.group().casefold().encode()) <= MAX_TOKEN_BYTES for t in tokens),
            "clause exceeds inherited source-token bounds; truncation forbidden")
        rows.append({**item, "source_ordinal": ordinal, "source_text": clause, "source_sha256": text_sha256(clause)})
        cursor = end
    _require(not text[cursor:].strip(), "unassigned non-whitespace source tail; dropped clause")
    if text[cursor:]:
        gaps.append({"char_start": cursor, "char_end": len(text), "source_sha256": text_sha256(text[cursor:])})
    value = {"schema": PLAN_SCHEMA, "source": source, "clauses": rows, "whitespace_gaps": gaps,
        "clause_count": len(rows), "coverage": "all_non_whitespace_source_characters_accounted_for",
        "scope": "Caller-declared one independent rule per clause; no natural-language scope classification or rule-count proof.",
        "producer_pins": producer_pins(), **FALSE}
    value["plan_sha256"] = digest(value)
    return json.loads(_wire(value))


def validate_source_plan(plan, *, expected_plan_sha256):
    _require(type(expected_plan_sha256) is str and _SHA.fullmatch(expected_plan_sha256), "external full source-plan hash required")
    _require(type(plan) is dict and plan.get("plan_sha256") == expected_plan_sha256, "source plan differs from external commitment")
    clauses = [{key: row[key] for key in ("clause_id", "char_start", "char_end", "scope")} for row in plan["clauses"]]
    expected = prepare_source_plan(plan["source"], clauses)
    _require(_wire(expected) == _wire(plan), "source plan contents, coverage or producer binding differ")
    return expected


def _rule(rule):
    _closed(rule, FIELDS, "canonical clause rule")
    for field in FIELDS[:4]:
        _require(type(rule[field]) is str, "exact scalar strings required")
    for field in QUALIFIERS:
        _require(type(rule[field]) is list and all(type(atom) is str for atom in rule[field]), "exact qualifier string lists required")
    _require(contracts.CanonicalRule.from_dict(rule).to_dict() == rule,
        "qualifier normalization, duplicate removal or sorting would change rule; supply exact canonical atoms")
    _require(len(rule["temporal"]) <= 1 and len(rule["conditions"]) + len(rule["temporal"]) <= 16
        and len(rule["exceptions"]) <= 8, "native qualifier cardinality exceeded")
    _require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rule["action"]) is not None, "native predicate identifier required; action paraphrase unsupported")
    return json.loads(_wire(rule))


def _attachments(source, clause, rule, attachments):
    _closed(attachments, SPAN_FIELDS, "complete facet attachments")
    text = source["source_text"]
    tokens = list(_TOKENS.finditer(text[clause["char_start"]:clause["char_end"]]))
    starts = {clause["char_start"] + token.start() for token in tokens}
    ends = {clause["char_start"] + token.end() for token in tokens}
    occupied, result = [], {}
    for field in SPAN_FIELDS:
        atoms = rule[field] if field in QUALIFIERS else ([rule[field]] if rule[field] else [])
        pointers = attachments[field]
        _require(type(pointers) is list and len(pointers) == len(atoms), "every predicted facet atom needs exactly one attachment")
        retained = []
        for atom, pointer in zip(atoms, pointers):
            _closed(pointer, {"char_start", "char_end"}, "source atom pointer")
            start, end = pointer["char_start"], pointer["char_end"]
            _require(type(start) is int and type(end) is int and clause["char_start"] <= start < end <= clause["char_end"],
                "cross-clause or invalid atom attachment")
            _require(start in starts and end in ends and text[start:end] == atom,
                "atom must equal its exact token-aligned source occurrence")
            _require(not any(start < prior_end and prior_start < end for prior_start, prior_end in occupied),
                "copied facet attachments overlap")
            occupied.append((start, end))
            retained.append({**pointer, "source_sha256": text_sha256(atom), "clause_id": clause["clause_id"]})
        result[field] = retained
    return result


def compose_rule_list(source_plan, clause_predictions, *, expected_plan_sha256):
    """Compose every declared clause exactly once; keep occurrence identity."""
    plan = validate_source_plan(source_plan, expected_plan_sha256=expected_plan_sha256)
    _require(type(clause_predictions) is list and len(clause_predictions) == plan["clause_count"],
        "complete one-prediction-per-clause inventory required; dropping rules is forbidden")
    rules, ledger = [], []
    for ordinal, (clause, prediction) in enumerate(zip(plan["clauses"], clause_predictions)):
        _closed(prediction, {"clause_id", "clause_source_sha256", "rule", "attachments", "scope"}, "clause prediction")
        _require(prediction["clause_id"] == clause["clause_id"] and prediction["clause_source_sha256"] == clause["source_sha256"],
            "ordered exact clause identity and source hash required")
        _scope(prediction["scope"])
        rule = _rule(prediction["rule"])
        pointers = _attachments(plan["source"], clause, rule, prediction["attachments"])
        rules.append(rule)
        ledger.append({"occurrence_id": clause["clause_id"], "source_ordinal": ordinal,
            "clause_source_sha256": clause["source_sha256"], "clause_char_start": clause["char_start"],
            "clause_char_end": clause["char_end"], "rule_sha256": digest(rule), "attachments": pointers,
            "scope": prediction["scope"]})
    canonical = contracts.CanonicalRoundTripIR.from_dict({"rules": rules}).to_dict()
    _require(len(canonical["rules"]) == len(rules), "canonical conversion lost rule multiplicity")
    available = defaultdict(deque)
    for ordinal, rule in enumerate(rules):
        available[digest(rule)].append(ordinal)
    permutation = []
    for canonical_index, rule in enumerate(canonical["rules"]):
        queue = available[digest(rule)]
        _require(bool(queue), "canonical rule not present in source occurrence inventory")
        source_index = queue.popleft()
        _require(rule == rules[source_index], "canonical atom conversion changed source rule")
        permutation.append(source_index)
        ledger[source_index]["canonical_rule_index"] = canonical_index
    _require(all(not queue for queue in available.values()), "source occurrence disappeared during canonical ordering")
    value = {"schema": SCHEMA, "source_plan": plan, "source_plan_sha256": expected_plan_sha256,
        "clause_predictions": clause_predictions, "source_rule_list": rules, "canonical_ir": canonical,
        "canonical_to_source_ordinal": permutation, "occurrences": ledger, "rule_count": len(rules),
        "source_order_preserved_in_ledger": True, "duplicate_rule_occurrences_preserved": True,
        "canonical_order_is_not_source_order": permutation != list(range(len(rules))),
        "qualifier_normalization_performed": False, "producer_pins": producer_pins(), **FALSE}
    value["composition_sha256"] = digest(value)
    return json.loads(_wire(value))


def validate_composition(composition, *, expected_plan_sha256):
    _require(type(composition) is dict, "composition object required")
    restored = compose_rule_list(composition["source_plan"], composition["clause_predictions"], expected_plan_sha256=expected_plan_sha256)
    _require(_wire(restored) == _wire(composition), "composition rule coverage, order, attachments or hashes changed")
    return restored


def reconstruct_source_rule_list(composition, *, expected_plan_sha256):
    value = validate_composition(composition, expected_plan_sha256=expected_plan_sha256)
    restored = [None] * value["rule_count"]
    for canonical_index, source_index in enumerate(value["canonical_to_source_ordinal"]):
        restored[source_index] = value["canonical_ir"]["rules"][canonical_index]
    _require(restored == value["source_rule_list"], "source rule occurrence order did not round-trip")
    return json.loads(_wire(restored))


def calendar_candidate(composition, *, expected_plan_sha256):
    value = validate_composition(composition, expected_plan_sha256=expected_plan_sha256)
    return {**value["source_plan"]["source"], "canonical_ir": value["canonical_ir"]}


def prepare_calendar_composition(composition, interpretation, *, expected_plan_sha256):
    """Apply explicitly supplied semantics only after source-occurrence checks."""
    candidate = calendar_candidate(composition, expected_plan_sha256=expected_plan_sha256)
    lowered = calendar.prepare_canonical_qualified(candidate, interpretation)
    _require(lowered["original_canonical_ir"] == candidate["canonical_ir"], "calendar lowering changed rule inventory")
    _require(calendar.previous.reconstruct_canonical(lowered["native_projection"], lowered["reversible_mapping"]) == candidate["canonical_ir"],
        "native multi-rule projection did not round-trip")
    return {"schema": "legal-source-rule-list-calendar/v1", "composition_sha256": composition["composition_sha256"],
        "source_plan_sha256": expected_plan_sha256, "rule_count": composition["rule_count"], "candidate": candidate,
        "interpretation": json.loads(_wire(interpretation)), "lowering": lowered,
        "occurrences": composition["occurrences"], "canonical_to_source_ordinal": composition["canonical_to_source_ordinal"],
        "producer_pins": producer_pins(), **FALSE}


def attach_span_prediction(source_plan, clause_id, prediction, *, scope, expected_plan_sha256):
    """Convert an existing single-clause pointer receipt to document coordinates.

    The caller still supplies the flat-scope declaration. Decoder provenance and
    numerical authenticity remain the responsibility of its own receipt checker.
    """
    plan = validate_source_plan(source_plan, expected_plan_sha256=expected_plan_sha256)
    _scope(scope)
    clauses = [row for row in plan["clauses"] if row["clause_id"] == clause_id]
    _require(len(clauses) == 1, "clause must belong to committed source inventory")
    clause = clauses[0]
    _require(type(prediction) is dict and prediction.get("status") == "decoded"
        and prediction.get("source_sha256") == clause["source_sha256"]
        and prediction.get("target_access") is False and prediction.get("teacher_forcing") is False,
        "free single-clause decoded source prediction required")
    ir = prediction["canonical_ir"]
    _closed(ir, {"rules"}, "single-clause IR")
    _require(type(ir["rules"]) is list and len(ir["rules"]) == 1, "single-clause decoder must supply exactly one rule")
    rule = _rule(ir["rules"][0])
    facets = prediction["span_diagnostics"]["facets"]
    _closed(facets, SPAN_FIELDS, "complete single-clause span diagnostics")
    attachments = {}
    for field in SPAN_FIELDS:
        atoms = rule[field] if field in QUALIFIERS else ([rule[field]] if rule[field] else [])
        _require(len(atoms) <= 1, "inherited span receipt supports at most one atom per facet")
        record = facets[field]
        _require(type(record) is dict and record.get("present") is bool(atoms), "span presence differs from rule")
        if atoms:
            start, end = record.get("char_start"), record.get("char_end")
            _require(type(start) is int and type(end) is int and 0 <= start < end <= len(clause["source_text"])
                and record.get("text") == clause["source_text"][start:end] == atoms[0], "single-clause span text or coordinates differ")
            attachments[field] = [{"char_start": clause["char_start"] + start, "char_end": clause["char_start"] + end}]
        else:
            _require(record.get("char_start") is None and record.get("char_end") is None and record.get("text") is None,
                "absent facet reports a source span")
            attachments[field] = []
    _attachments(plan["source"], clause, rule, attachments)
    return {"clause_id": clause_id, "clause_source_sha256": clause["source_sha256"], "rule": rule,
        "attachments": attachments, "scope": json.loads(_wire(scope))}


__all__ = ["prepare_source_plan", "validate_source_plan", "compose_rule_list", "validate_composition",
    "reconstruct_source_rule_list", "calendar_candidate", "prepare_calendar_composition", "attach_span_prediction",
    "producer_pins", "digest", "text_sha256", "FLAT_SCOPE", "SCHEMA", "PLAN_SCHEMA"]
