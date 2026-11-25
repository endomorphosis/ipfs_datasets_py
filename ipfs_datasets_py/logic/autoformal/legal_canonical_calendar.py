"""Explicit Gregorian start dates and deadlines for canonical legal rules.

The old duration bridge is unchanged. Calendar declarations preserve absolute
dates as day ordinals; they never replace a date with an inferred duration.
Compilation under this profile does not identify the real evaluation date,
interpret legal calendars, or establish legal-source fidelity or norm truth.
"""
from __future__ import annotations

from collections import deque
from datetime import date
from functools import cache
import hashlib
import json
from pathlib import Path
import re

from . import legal_canonical_qualified as previous
from ..formalization.autoencoder import native_legal_qualified_lean as native
from ..formalization.autoencoder import native_qualified_lean as base
from ..legal_ir import canonical_contracts as contracts

SCHEMA = "legal-canonical-calendar/v1"
INTERPRETATION_SCHEMA = "legal-canonical-calendar-interpretation/v1"
PROFILE = "canonical-explicit-calendar/v1"
EFFECTIVE_SCHEMA = "legal-canonical-effective-date/v1"
EFFECTIVE_INTERPRETATION_SCHEMA = "legal-canonical-effective-date-interpretation/v1"
EFFECTIVE_PROFILE = "canonical-explicit-effective-date/v1"
DECLARATION_SCOPE = previous.DECLARATION_SCOPE
_CALENDAR = re.compile(r"before ([0-9]{4}-[0-9]{2}-[0-9]{2})")
_CALENDAR_CHOICES = {"temporal_kind": "before_calendar_date", "calendar": "proleptic_gregorian",
    "ordinal_epoch": "0001-01-01", "ordinal_epoch_value": 1, "time_domain": "discrete_nat_days",
    "origin": "caller_supplied_evaluation_date_ordinal", "lower_inclusive": True,
    "upper_inclusive": False, "expired_deadline_policy": "empty_witness_interval"}
_EFFECTIVE_LITERAL = re.compile(r"effective from ([0-9]{4}-[0-9]{2}-[0-9]{2})")
_EFFECTIVE_PREFIX = re.compile(r"\s*effective(?:\s+|[-_])from\b", re.IGNORECASE)
_EFFECTIVE_CHOICES = {"placement": "activation_at_evaluation_origin_before_modality",
                      "lower_inclusive": True}
digest = previous.digest


def _pins():
    return previous.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    if _pins() != _IMPORTED_PINS:
        raise ValueError("calendar producer changed since import")
    return dict(_IMPORTED_PINS)


def _effective_paths():
    logic = Path(__file__).resolve().parents[1]
    return tuple(logic / relative for relative in (
        "legal_ir/extended_compiler.py",
        "legal_ir/extended_contracts.py",
        "legal_ir/extended_decompiler.py",
        "TDFOL/compiler_repairs.py",
    ))


def _read_pins(paths):
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


@cache
def _initial_effective_pins():
    # Legacy calendar and duration users do not require this source profile.
    return _read_pins(_effective_paths())


def _effective_producer_pins():
    expected = _initial_effective_pins()
    if _read_pins(_effective_paths()) != expected:
        raise ValueError("effective-date source producers changed since first use")
    return producer_pins() | expected


def parse_calendar_literal(literal):
    """Check date syntax/validity and return its Gregorian day1 ordinal.

    This helper recognizes a representation. It does not choose deadline scope
    or attest that a caller's legal interpretation of that representation is true.
    """
    if type(literal) is not str or not (match := _CALENDAR.fullmatch(literal)):
        raise ValueError("exact before YYYY-MM-DD calendar literal required")
    return _civil_calendar_date(match[1])


def _civil_calendar_date(text):
    try:
        value = date.fromisoformat(text)
    except ValueError as error:
        raise ValueError("valid proleptic Gregorian date in years1..9999 required") from error
    return {"date": value.isoformat(), "date_ordinal": value.toordinal()}


def _has_calendar(candidate):
    if type(candidate) is not dict or type(candidate.get("canonical_ir")) is not dict:
        return False
    rules = candidate["canonical_ir"].get("rules")
    if type(rules) is not list:
        return False
    return any(type(rule) is dict and type(rule.get("temporal")) is list and
               any(type(item) is str and item.startswith("before ") for item in rule["temporal"])
               for rule in rules)


def _effective_literal(literal):
    if type(literal) is not str or not (match := _EFFECTIVE_LITERAL.fullmatch(literal)):
        raise ValueError("exact effective from YYYY-MM-DD calendar literal required")
    return _civil_calendar_date(match[1])


def _has_effective_date(candidate):
    if type(candidate) is not dict or type(candidate.get("canonical_ir")) is not dict:
        return False
    rules = candidate["canonical_ir"].get("rules")
    if type(rules) is list and any(
        type(rule) is dict and any(
            type(rule.get(facet)) is list and any(
                type(literal) is str and _EFFECTIVE_PREFIX.match(literal) for literal in rule[facet])
            for facet in ("conditions", "exceptions", "temporal"))
        for rule in rules
    ):
        return True
    # A start omitted from the supplied canonical IR must still take the typed
    # replay route. Parse only a possible explicit controlled date clause.
    text = candidate.get("source_text")
    if (type(text) is str and text.startswith(("Norm: ", "Definition: ", "Policy: "))
            and len(text) <= previous.MAX_SOURCE_BYTES
            and (" Temporal: effective from " in text or "; effective from " in text)):
        return _compile_effective_source(text) is not None
    return False


def _rule_temporals(rule):
    start = deadline = None
    for index, literal in enumerate(rule["temporal"]):
        if _EFFECTIVE_PREFIX.match(literal):
            if start is not None:
                raise ValueError("one explicit effective-from date per rule")
            _effective_literal(literal)
            start = (index, literal)
        else:
            if deadline is not None:
                raise ValueError("one deadline temporal atom per rule")
            if literal.startswith("before "):
                parse_calendar_literal(literal)
            elif not previous._DURATION.fullmatch(literal):
                raise ValueError("unsupported temporal atom")
            deadline = (index, literal)
    if start is not None and deadline is not None and not deadline[1].startswith("before "):
        raise ValueError("effective-from requires an explicit absolute before-deadline when combined")
    return start, deadline


def _compile_effective_source(source_text):
    pins = _effective_producer_pins()
    from ..TDFOL import compiler_repairs
    from ..legal_ir import extended_compiler, extended_contracts, extended_decompiler

    modules = (extended_compiler, extended_contracts, extended_decompiler, compiler_repairs)
    if any(Path(module.__file__).resolve() != path.resolve()
           for module, path in zip(modules, _effective_paths(), strict=True)):
        raise ValueError("effective-date source producer import path differs")
    typed = extended_compiler.compile_extended(
        source_text, profile=extended_decompiler.EFFECTIVE_DATE_PROSE_PROFILE)
    if _effective_producer_pins() != pins:
        raise ValueError("effective-date source producer pins changed during replay")
    return typed


def _effective_source_candidate(source_text, candidate_id):
    if type(source_text) is not str or not source_text.strip():
        raise ValueError("bounded nonblank full source required")
    try:
        source_raw = source_text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid effective-date UTF-8 source required") from error
    if len(source_raw) > previous.MAX_SOURCE_BYTES:
        raise ValueError("bounded nonblank full source required")
    typed = _compile_effective_source(source_text)
    from ..legal_ir import extended_contracts

    if type(typed) is not extended_contracts.ExtendedEffectiveDateLegalIR:
        raise ValueError("exact controlled effective-date source required")
    rules, source_occurrences = [], {}
    for source_index, statement in enumerate(typed.statements):
        if type(statement) is not extended_contracts.NormV2 or statement.scope:
            raise ValueError("effective-date calendar supports unscoped norms")
        temporal = []
        for atom in statement.temporal:
            if type(atom) is extended_contracts.EffectiveFrom:
                temporal.append("effective from " + atom.effective_from)
            elif type(atom) is str and not _EFFECTIVE_PREFIX.match(atom):
                temporal.append(atom)
            else:
                raise ValueError("effective-date calendar cannot convert this source temporal atom")
        rule = {"modality": statement.modality, "actor": statement.actor,
                "action": statement.action, "object": statement.object,
                "conditions": list(statement.conditions), "exceptions": list(statement.exceptions),
                "temporal": temporal}
        if any(len(set(rule[facet])) != len(rule[facet])
               for facet in ("conditions", "exceptions", "temporal")):
            raise ValueError("effective-date source qualifier occurrences cannot be collapsed")
        canonical_rule = contracts.CanonicalRule.from_dict(rule).to_dict()
        rules.append(canonical_rule)
        source_occurrences.setdefault(previous._wire(canonical_rule), deque()).append(source_index)
    canonical = contracts.CanonicalRoundTripIR.from_dict({"rules": rules}).to_dict()
    source_order = [source_occurrences[previous._wire(rule)].popleft() for rule in canonical["rules"]]
    candidate = _candidate({"candidate_id": candidate_id, "source_text": source_text,
        "source_sha256": hashlib.sha256(source_raw).hexdigest(), "canonical_ir": canonical},
        effective=True)
    return candidate, {"typed_source_ir": typed.to_dict(),
                       "canonical_to_source_statement_index": source_order}


def candidate_from_effective_date_prose(source_text, *, candidate_id):
    """Build a canonical candidate from exact controlled effective-date prose."""
    candidate, _ = _effective_source_candidate(source_text, candidate_id)
    return candidate


def _checked_calendar_candidate(candidate, effective):
    checked = _candidate(candidate, effective=effective)
    if not effective:
        return checked, None
    replay, typed = _effective_source_candidate(checked["source_text"], checked["candidate_id"])
    if replay != checked:
        raise ValueError("effective-date source replay differs from the canonical candidate")
    return checked, typed


def _candidate(candidate, *, effective=False):
    previous._closed(candidate, {"candidate_id", "source_text", "source_sha256", "canonical_ir"}, "candidate")
    base._text(candidate["candidate_id"], "candidate_id")
    source = candidate["source_text"]
    if type(source) is not str or not source.strip() or len(source.encode()) > previous.MAX_SOURCE_BYTES:
        raise ValueError("bounded nonblank full source required")
    if hashlib.sha256(source.encode()).hexdigest() != candidate["source_sha256"]:
        raise ValueError("source SHA256 differs from complete source bytes")
    ir = candidate["canonical_ir"]
    previous._closed(ir, {"rules"}, "canonical IR")
    if type(ir["rules"]) is not list or not 0 < len(ir["rules"]) <= previous.MAX_RULES:
        raise ValueError("canonical IR requires1..64 rules")
    for rule in ir["rules"]:
        previous._closed(rule, {"modality", "actor", "action", "object", "conditions", "exceptions", "temporal"}, "canonical rule")
        for facet in ("conditions", "exceptions", "temporal"):
            if type(rule[facet]) is not list:
                raise ValueError("qualifier lists required")
            for literal in rule[facet]:
                base._text(literal, facet)
        if effective:
            if any(_EFFECTIVE_PREFIX.match(literal)
                   for facet in ("conditions", "exceptions") for literal in rule[facet]):
                raise ValueError("effective-from cannot be hidden as an opaque qualifier")
            _rule_temporals(rule)
        elif len(rule["temporal"]) > 1:
            raise ValueError("one temporal atom per rule required")
        if len(rule["conditions"]) + len(rule["temporal"]) > 16 or len(rule["exceptions"]) > 8:
            raise ValueError("native qualifier cardinality exceeded")
        if not effective and rule["temporal"]:
            literal = rule["temporal"][0]
            if literal.startswith("before "):
                parse_calendar_literal(literal)
            elif not previous._DURATION.fullmatch(literal):
                raise ValueError("unsupported temporal atom")
        base._predicate({"name": rule["action"], "arguments": [rule["actor"]] +
                         ([rule["object"]] if rule["object"] != "" else [])})
    if contracts.CanonicalRoundTripIR.from_dict(ir).to_dict() != ir:
        raise ValueError("canonical IR must already be ordered and deduplicated")
    if len(previous._wire(ir)) > previous.MAX_IR_BYTES:
        raise ValueError("canonical IR exceeds byte bound")
    return json.loads(previous._wire(candidate))


def _declaration_skeleton(rule, formula, index, effective):
    if effective:
        start, deadline = _rule_temporals(rule)
    else:
        start = None
        deadline = (0, rule["temporal"][0]) if rule["temporal"] else None
    temporal = None
    if deadline is not None:
        temporal_index, literal = deadline
        fields = set(_CALENDAR_CHOICES) | {"date", "date_ordinal"} if literal.startswith("before ") else {
            "temporal_kind", "quantity", "unit", "time_domain", "origin", "lower_inclusive", "upper_inclusive"}
        temporal = dict.fromkeys(fields)
        temporal.update(source_index=len(rule["conditions"]) + temporal_index, source_text=literal)
    result = {"formula_index": index, "original_formula_sha256": native.digest(formula),
        "kind": "activation_guarded_legal_rule", "activation_scope": None, "exception_scope": None,
        "conditions": [{"source_index": j, "source_text": literal, "expression": None}
                       for j, literal in enumerate(rule["conditions"])],
        "exceptions": [{"source_index": j, "source_text": literal, "expression": None}
                       for j, literal in enumerate(rule["exceptions"])], "temporal": temporal}
    if effective:
        effective_from = None
        if start is not None:
            temporal_index, literal = start
            effective_from = dict.fromkeys((*_EFFECTIVE_CHOICES, "date", "date_ordinal"))
            effective_from.update(source_index=len(rule["conditions"]) + temporal_index,
                canonical_temporal_index=temporal_index, source_text=literal)
        result["effective_from"] = effective_from
    return result


def _interpretation_skeleton(candidate, projection, mapping, typed):
    result = {"schema": INTERPRETATION_SCHEMA, "candidate_id": candidate["candidate_id"],
        "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
        "canonical_ir_sha256": digest(candidate["canonical_ir"]), "mapping_sha256": digest(mapping),
        "declaration_scope": DECLARATION_SCOPE,
        "formulas": [_declaration_skeleton(rule, formula, index, typed is not None)
                     for index, (rule, formula) in enumerate(zip(candidate["canonical_ir"]["rules"],
                                                                 projection["payload"]["formulas"]))]}
    if typed is not None:
        result.update(schema=EFFECTIVE_INTERPRETATION_SCHEMA,
            typed_source_ir_sha256=digest(typed["typed_source_ir"]),
            canonical_to_source_statement_index=typed["canonical_to_source_statement_index"])
    return result


def interpretation_skeleton(candidate):
    """Return unfilled explicit calendar choices with exact source identity."""
    producer_pins()
    effective = _has_effective_date(candidate)
    if not effective and not _has_calendar(candidate):
        return previous.interpretation_skeleton(candidate)
    try:
        candidate, typed = _checked_calendar_candidate(candidate, effective)
        projection, mapping, _ = previous._mapping(candidate)
        return _interpretation_skeleton(candidate, projection, mapping, typed)
    except (KeyError, IndexError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid canonical calendar candidate") from error


def _calendar_body(formula, declaration, literal_bindings):
    temporal = declaration["temporal"]
    previous._closed(temporal, set(_CALENDAR_CHOICES) | {"date", "date_ordinal", "source_index", "source_text"}, "calendar declaration")
    expected_date = parse_calendar_literal(temporal["source_text"])
    for field, expected in (_CALENDAR_CHOICES | expected_date).items():
        if type(temporal[field]) is not type(expected) or temporal[field] != expected:
            raise ValueError("explicit calendar declaration differs: " + field)
    if declaration["activation_scope"] != "all_conditions_at_evaluation_origin":
        raise ValueError("explicit activation-at-evaluation-origin scope required")
    if declaration["exception_scope"] != "activation_time_waiver":
        raise ValueError("calendar profile requires explicit activation-time waiver; per-tick calendar exceptions are unsupported")
    if declaration["kind"] != "activation_guarded_legal_rule":
        raise ValueError("explicit activation-guarded rule kind required")
    # The last native condition is the separately ledgered canonical date.
    activations = native._bindings(formula["conditions"], declaration["conditions"], label="condition",
        indices=list(range(len(formula["conditions"]) - 1)), literal_bindings=literal_bindings)
    exemptions = native._bindings(formula["exceptions"], declaration["exceptions"], label="exception",
        indices=list(range(len(formula["exceptions"]))), literal_bindings=literal_bindings)
    # Existing duration-looking qualifiers must not bypass native duration checks
    # by entering the calendar route as ordinary conditions.
    if any(previous._DURATION.fullmatch(literal) or _CALENDAR.fullmatch(literal)
           for literal in formula["conditions"][:-1]):
        raise ValueError("temporal literal cannot be hidden as an activation condition")
    atom = base._predicate({key: formula["predicate"][key] for key in ("name", "arguments")})
    ordinal = expected_date["date_ordinal"]
    # Day0 is outside the declared date epoch. Guard the evaluation origin in
    # the interval itself, not outside the modality where falsehood is vacuous.
    interval = "(fun origin => 1 ≤ origin ∧ ∃ u, origin ≤ u ∧ u < " + str(ordinal) + " ∧ " + atom + " u)"
    body = '(i.modal ' + native.string("deontic:" + formula["operator"]["symbol"]) + \
        ' [] (some "explicit-calendar:proleptic-gregorian-day1") ' + interval + ')'
    guards = [native._expression(expression, "t") for expression in activations]
    if exemptions:
        guards.append("(¬ (" + " ∨ ".join(native._expression(expression, "t") for expression in exemptions) + "))")
    if guards:
        body = "(fun t => (" + " ∧ ".join(guards) + ") → " + body + " t)"
    return body, {"date": expected_date["date"], "date_ordinal": ordinal,
        "origin_domain": "Nat_day_ordinals_at_least1", "interval": "origin_inclusive_deadline_exclusive",
        "expired_interval": "empty_witness_set", "date_literal": temporal["source_text"]}


def _effective_lowering_copy(formula, declaration, expected_start):
    adjusted = dict(declaration)
    start = adjusted.pop("effective_from")
    if expected_start is None:
        if start is not None:
            raise ValueError("undeclared effective-from cannot become an activation guard")
        return formula, adjusted, None
    start_text = expected_start["source_text"]
    expected = {**expected_start, **_EFFECTIVE_CHOICES, **_effective_literal(start_text)}
    previous._closed(start, set(expected), "effective-from declaration")
    for field, value in expected.items():
        if type(start[field]) is not type(value) or start[field] != value:
            raise ValueError("explicit effective-from declaration differs: " + field)
    start_index = expected["source_index"]
    conditions = formula["conditions"]
    if conditions[start_index] != start_text:
        raise ValueError("effective-from source index differs")
    # The reversible mapping and formula hash keep the original slot. Only the
    # lowering copy drops it before native expression binding.
    lowered_formula = {**formula, "conditions": conditions[:start_index] + conditions[start_index + 1:]}
    temporal = adjusted["temporal"]
    if temporal is not None and temporal["source_index"] > start_index:
        adjusted["temporal"] = {**temporal, "source_index": temporal["source_index"] - 1}
    return lowered_formula, adjusted, expected


def prepare_canonical_qualified(candidate, interpretation):
    """Emit explicit calendar semantics; delegate noncalendar inputs unchanged."""
    producer_pins()
    explicit = type(interpretation) is dict and interpretation.get("schema") == EFFECTIVE_INTERPRETATION_SCHEMA
    effective = explicit or _has_effective_date(candidate)
    if not effective and not _has_calendar(candidate):
        return previous.prepare_canonical_qualified(candidate, interpretation)
    try:
        pins = _effective_producer_pins() if effective else producer_pins()
        candidate, typed_source = _checked_calendar_candidate(candidate, effective)
        projection, mapping, source_ref = previous._mapping(candidate)
        skeleton = _interpretation_skeleton(candidate, projection, mapping, typed_source)
        previous._closed(interpretation, set(skeleton), "calendar interpretation")
        if effective:
            source_indices = interpretation["canonical_to_source_statement_index"]
            if type(source_indices) is not list or any(type(index) is not int for index in source_indices):
                raise ValueError("exact canonical-to-source statement indices required")
        if any(interpretation[key] != skeleton[key] for key in skeleton if key != "formulas"):
            raise ValueError("calendar interpretation candidate/source/canonical/mapping binding differs")
        if len(previous._wire(interpretation)) > previous.MAX_IR_BYTES:
            raise ValueError("calendar interpretation exceeds byte bound")
        declarations, formulas = interpretation["formulas"], projection["payload"]["formulas"]
        if type(declarations) is not list or len(declarations) != len(formulas):
            raise ValueError("complete ordered formula declarations required")
        lines, typed_temporal, typed_starts, bindings, operators = [], [], [], {}, []
        for index, (formula, declaration, declared) in enumerate(zip(formulas, declarations, skeleton["formulas"])):
            previous._closed(declaration, set(declared), "formula declaration")
            if (type(declaration["formula_index"]) is not int or declaration["formula_index"] != index or
                    declaration["original_formula_sha256"] != native.digest(formula)):
                raise ValueError("ordered native formula hash binding differs")
            temporal, expected_temporal = declaration["temporal"], declared["temporal"]
            if expected_temporal is not None:
                if (type(temporal) is not dict or type(temporal.get("source_index")) is not int or
                        temporal.get("source_index") != expected_temporal["source_index"] or
                        temporal.get("source_text") != expected_temporal["source_text"]):
                    raise ValueError("canonical temporal facet must be interpreted exactly")
            elif temporal is not None:
                raise ValueError("activation condition cannot become temporal")
            explicit_start = None
            if effective:
                formula, declaration, explicit_start = _effective_lowering_copy(
                    formula, declaration, declared["effective_from"])
            if temporal is not None and temporal["source_text"].startswith("before "):
                body, typed = _calendar_body(formula, declaration, bindings)
                typed_temporal.append(dict(typed, formula_index=index, canonical_temporal_index=0,
                                           native_condition_index=temporal["source_index"]))
                operators.extend(["activation_all", "activation_time_waiver", "before_calendar_date", formula["operator"]["symbol"]])
            else:
                body, ops = native._formula(formula, declaration, "deontic", bindings)
                operators.extend(ops)
            if explicit_start is not None:
                active = f"effectiveFromActive_{index}"
                ordinal = explicit_start["date_ordinal"]
                lines.append(f"def {active} : Nat → Prop := fun t => 1 ≤ t ∧ {ordinal} ≤ t")
                body = f"(fun t => 1 ≤ t ∧ ({active} t → ({body}) t))"
                typed_starts.append(dict(explicit_start, formula_index=index,
                    native_condition_index=explicit_start["source_index"],
                    source_statement_index=typed_source["canonical_to_source_statement_index"][index]))
                operators.append("effective_from_date")
            lines.append(f"def qualifiedLegalFormula_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := " + body)
            lines.append(f"def originalFormulaProvenance_{index} : String := " + native.string(base._wire(formula["provenance"]).decode()))
        if previous.reconstruct_canonical(projection, mapping) != candidate["canonical_ir"]:
            raise ValueError("calendar native mapping is not reversible")
        lowered = {"validator": "exact_canonical_mapping_and_explicit_gregorian_declaration",
            "operators": operators, "supported_family_profile": "deontic/" + PROFILE,
            "canonical_facets_preserved": True, "calendar_interpretations": typed_temporal,
            "capability_floor_eligible": False, "source_semantics_verified": False,
            "source_text_inference_executed": False, "runtime_authority_granted": False,
            "event_occurrences_attested": False, "admitted": False,
            "origin_provenance_scope": "whole_source_identity_not_qualifier_span_alignment",
            "old_unqualified_lowering_equivalence_verified": False, "clock_unit_conversion_verified": False,
            "assumptions": ["The caller declares proleptic Gregorian dates with 0001-01-01 ordinal1 and supplies the evaluation date ordinal.",
                "Calendar intervals require origin>=1 and a witness at origin<=u<the absolute deadline ordinal.",
                "A deadline at/before origin gives an empty witness interval; the interpretation of deontic modalities remains a parameter.",
                "Conditions and activation-waiver exceptions are tested at the evaluation origin outside the modality.",
                "Calendar days have no timezone, business-day convention, real clock attestation or inferred triggering event.",
                "For mixed calendar/duration rules, tick/unit conversion and a shared real-world clock are not established.",
                "Declared qualifier expressions, source semantics, predicate meanings, norm truth and actual compliance are unverified."]}
        schema, profile, profile_path = SCHEMA, PROFILE, "/explicit-calendar/v1"
        evidence = {}
        if effective:
            schema, profile, profile_path = EFFECTIVE_SCHEMA, EFFECTIVE_PROFILE, "/explicit-effective-date/v1"
            evidence = {**typed_source, "typed_source_ir_sha256": skeleton["typed_source_ir_sha256"]}
            lowered.update(supported_family_profile="deontic/" + profile,
                           effective_interpretations=typed_starts)
            lowered["assumptions"].append(
                "An authored inclusive start gates rule activation at the evaluation origin outside the modality.")
            if _effective_producer_pins() != pins:
                raise ValueError("effective-date source or lowering producer pins changed")
        payload = {"schema": schema, **evidence, "original": projection, "interpretation": interpretation,
            "interpretation_sha256": digest(interpretation), "source_ref": source_ref.to_dict(),
            "source_semantics_verified": False, "source_text_inference_executed": False, "admitted": False}
        return json.loads(previous._wire({"schema": schema, **evidence, "candidate_id": candidate["candidate_id"],
            "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
            "canonical_ir_sha256": digest(candidate["canonical_ir"]), "interpretation_sha256": digest(interpretation),
            "mapping_sha256": digest(mapping), "source_ref": source_ref.to_dict(),
            "original_canonical_ir": candidate["canonical_ir"], "reversible_mapping": mapping,
            "native_projection": projection, "interpretation": interpretation, "declaration_scope": DECLARATION_SCOPE,
            "qualified_projection": {"projection_id": projection["projection_id"] + profile_path,
                "logic_family": "deontic", "profile": profile, "payload": payload, "producer_id": __name__},
            "lean_body": "\n".join(lines), "lowering_details": lowered, "producer_pins": pins if effective else producer_pins(),
            "source_semantics_verified": False, "source_text_inference_executed": False, "admitted": False}))
    except (KeyError, IndexError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid calendar candidate or explicit interpretation") from error
