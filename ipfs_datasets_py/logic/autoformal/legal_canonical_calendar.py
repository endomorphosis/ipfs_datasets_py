"""Explicit absolute Gregorian deadlines for canonical legal rules.

The old duration bridge is unchanged. Calendar declarations preserve absolute
dates as day ordinals; they never replace a date with an inferred duration.
Compilation under this profile does not identify the real evaluation date,
interpret legal calendars, or establish legal-source fidelity or norm truth.
"""
from __future__ import annotations

from datetime import date
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
DECLARATION_SCOPE = previous.DECLARATION_SCOPE
_CALENDAR = re.compile(r"before ([0-9]{4}-[0-9]{2}-[0-9]{2})")
_CALENDAR_CHOICES = {"temporal_kind": "before_calendar_date", "calendar": "proleptic_gregorian",
    "ordinal_epoch": "0001-01-01", "ordinal_epoch_value": 1, "time_domain": "discrete_nat_days",
    "origin": "caller_supplied_evaluation_date_ordinal", "lower_inclusive": True,
    "upper_inclusive": False, "expired_deadline_policy": "empty_witness_interval"}
digest = previous.digest


def _pins():
    return previous.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    if _pins() != _IMPORTED_PINS:
        raise ValueError("calendar producer changed since import")
    return dict(_IMPORTED_PINS)


def parse_calendar_literal(literal):
    """Check date syntax/validity and return its Gregorian day1 ordinal.

    This helper recognizes a representation. It does not choose deadline scope
    or attest that a caller's legal interpretation of that representation is true.
    """
    if type(literal) is not str or not (match := _CALENDAR.fullmatch(literal)):
        raise ValueError("exact before YYYY-MM-DD calendar literal required")
    try:
        value = date.fromisoformat(match[1])
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


def _candidate(candidate):
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
        if len(rule["temporal"]) > 1:
            raise ValueError("one temporal atom per rule required")
        if len(rule["conditions"]) + len(rule["temporal"]) > 16 or len(rule["exceptions"]) > 8:
            raise ValueError("native qualifier cardinality exceeded")
        if rule["temporal"]:
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


def interpretation_skeleton(candidate):
    """Return an unfilled declaration, routing noncalendar candidates unchanged."""
    producer_pins()
    if not _has_calendar(candidate):
        return previous.interpretation_skeleton(candidate)
    try:
        candidate = _candidate(candidate)
        projection, mapping, _ = previous._mapping(candidate)
        declarations = []
        for index, (rule, formula) in enumerate(zip(candidate["canonical_ir"]["rules"], projection["payload"]["formulas"])):
            temporal = None
            if rule["temporal"]:
                literal = rule["temporal"][0]
                fields = set(_CALENDAR_CHOICES) | {"date", "date_ordinal"} if literal.startswith("before ") else {
                    "temporal_kind", "quantity", "unit", "time_domain", "origin", "lower_inclusive", "upper_inclusive"}
                temporal = dict.fromkeys(fields)
                temporal.update(source_index=len(rule["conditions"]), source_text=literal)
            declarations.append({"formula_index": index, "original_formula_sha256": native.digest(formula),
                "kind": "activation_guarded_legal_rule", "activation_scope": None, "exception_scope": None,
                "conditions": [{"source_index": j, "source_text": literal, "expression": None}
                               for j, literal in enumerate(rule["conditions"])],
                "exceptions": [{"source_index": j, "source_text": literal, "expression": None}
                               for j, literal in enumerate(rule["exceptions"])], "temporal": temporal})
        return {"schema": INTERPRETATION_SCHEMA, "candidate_id": candidate["candidate_id"],
            "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
            "canonical_ir_sha256": digest(candidate["canonical_ir"]), "mapping_sha256": digest(mapping),
            "declaration_scope": DECLARATION_SCOPE, "formulas": declarations}
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


def prepare_canonical_qualified(candidate, interpretation):
    """Emit explicit calendar semantics; delegate noncalendar inputs unchanged."""
    producer_pins()
    if not _has_calendar(candidate):
        return previous.prepare_canonical_qualified(candidate, interpretation)
    try:
        candidate = _candidate(candidate)
        projection, mapping, source_ref = previous._mapping(candidate)
        skeleton = interpretation_skeleton(candidate)
        previous._closed(interpretation, set(skeleton), "calendar interpretation")
        if any(interpretation[key] != skeleton[key] for key in skeleton if key != "formulas"):
            raise ValueError("calendar interpretation candidate/source/canonical/mapping binding differs")
        if len(previous._wire(interpretation)) > previous.MAX_IR_BYTES:
            raise ValueError("calendar interpretation exceeds byte bound")
        declarations, formulas = interpretation["formulas"], projection["payload"]["formulas"]
        if type(declarations) is not list or len(declarations) != len(formulas):
            raise ValueError("complete ordered formula declarations required")
        lines, typed_temporal, bindings, operators = [], [], {}, []
        for index, (rule, formula, declaration) in enumerate(zip(candidate["canonical_ir"]["rules"], formulas, declarations)):
            previous._closed(declaration, {"formula_index", "original_formula_sha256", "kind", "activation_scope",
                "conditions", "exceptions", "temporal", "exception_scope"}, "formula declaration")
            if (type(declaration["formula_index"]) is not int or declaration["formula_index"] != index or
                    declaration["original_formula_sha256"] != native.digest(formula)):
                raise ValueError("ordered native formula hash binding differs")
            temporal = declaration["temporal"]
            if rule["temporal"]:
                if (type(temporal) is not dict or type(temporal.get("source_index")) is not int or
                        temporal.get("source_index") != len(rule["conditions"]) or
                        temporal.get("source_text") != rule["temporal"][0]):
                    raise ValueError("canonical temporal facet must be interpreted exactly")
            elif temporal is not None:
                raise ValueError("activation condition cannot become temporal")
            if rule["temporal"] and rule["temporal"][0].startswith("before "):
                body, typed = _calendar_body(formula, declaration, bindings)
                typed_temporal.append(dict(typed, formula_index=index, canonical_temporal_index=0,
                                           native_condition_index=len(rule["conditions"])))
                operators.extend(["activation_all", "activation_time_waiver", "before_calendar_date", formula["operator"]["symbol"]])
            else:
                body, ops = native._formula(formula, declaration, "deontic", bindings)
                operators.extend(ops)
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
        payload = {"schema": SCHEMA, "original": projection, "interpretation": interpretation,
            "interpretation_sha256": digest(interpretation), "source_ref": source_ref.to_dict(),
            "source_semantics_verified": False, "source_text_inference_executed": False, "admitted": False}
        return json.loads(previous._wire({"schema": SCHEMA, "candidate_id": candidate["candidate_id"],
            "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
            "canonical_ir_sha256": digest(candidate["canonical_ir"]), "interpretation_sha256": digest(interpretation),
            "mapping_sha256": digest(mapping), "source_ref": source_ref.to_dict(),
            "original_canonical_ir": candidate["canonical_ir"], "reversible_mapping": mapping,
            "native_projection": projection, "interpretation": interpretation, "declaration_scope": DECLARATION_SCOPE,
            "qualified_projection": {"projection_id": projection["projection_id"] + "/explicit-calendar/v1",
                "logic_family": "deontic", "profile": PROFILE, "payload": payload, "producer_id": __name__},
            "lean_body": "\n".join(lines), "lowering_details": lowered, "producer_pins": producer_pins(),
            "source_semantics_verified": False, "source_text_inference_executed": False, "admitted": False}))
    except (KeyError, IndexError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid calendar candidate or explicit interpretation") from error
