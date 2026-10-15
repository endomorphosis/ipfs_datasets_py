"""Caller-declared event-triggered deadlines on a discrete Nat trace.

The source observation records a numeric not/no-later-than prefix and its event
complement. Only an explicit declaration chooses a tick conversion, response
anchor, repeated-trigger policy and closed endpoints. No law, legal owner,
modality, clock conversion or real event occurrence is inferred or attested.

Bounded response is represented with existing LTL operators: B_0(p) = p and
B_(n+1)(p) = p or next(B_n(p)). The full property is always(trigger implies
B_n(response)). A separate Lean declaration gives its closed-interval meaning.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from . import legal_temporal_event_interpretation as until
from ..TDFOL import tdfol_core as native
from ..intent_ir.formalize import modal_projections
from ..software_verification.temporal import TemporalFormula

REQUEST_SCHEMA = "legal-temporal-deadline-interpretation-requests/v1"
DECLARATION_SCHEMA = "legal-temporal-deadline-interpretation-declaration/v1"
ARTIFACT_SCHEMA = "legal-temporal-deadline-interpretation/v1"
PROFILE = "caller-declared-triggered-deadline-property/v1"
# G + implication + n alternating or/next pairs have maximum depth 2 + 2n.
# Thirty ticks fit the existing native renderer's depth-64 budget unchanged.
MAX_DEADLINE_TICKS = 30
MAX_AST_DEPTH = 64
MAX_AST_NODES = 128
_MEANING_FIELDS = (
    "response_source_span", "response_source_text", "trigger_atom", "response_atom",
    "ticks_per_source_unit", "trigger_scope", "deadline_origin", "lower_inclusive",
    "upper_inclusive", "time_domain", "evaluation_origin", "modal_scope", "response_reuse",
)
_BINDING_FIELDS = (*until._BINDING_FIELDS, "deadline_surface")
_PREFIX = re.compile(
    r"(?P<cue>(?:not|no)\s+later\s+than)\s+"
    r"(?P<quantity>[1-9][0-9]{0,2})\s+"
    r"(?P<unit>hours?|days?|weeks?|months?|years?)\s+"
    r"(?P<connector>after)\s*\Z", re.IGNORECASE)
_FALSE = {**until._FALSE, "deadline_semantics_inferred": False}
_require, _closed, _copy, _wire, _seal, digest = (
    until._require, until._closed, until._copy, until._wire, until._seal, until.digest)


def _dependency_pins():
    paths = (Path(__file__).resolve(), Path(modal_projections.__file__).resolve())
    return until.producer_pins() | {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


_INITIAL_PINS = _dependency_pins()


def producer_pins():
    _require(_dependency_pins() == _INITIAL_PINS, "temporal deadline interpretation producer changed")
    return dict(_INITIAL_PINS)


def _deadline_surface(request, receipt, source_text, document_text):
    """Observe only the authenticated prefix; no chosen tick or legal meaning."""
    if request["proposal_family"] != "not_later_than_after" or request["event_source"] is None:
        return None
    start = request["temporal_source"]["source_span"]["char_start"]
    event_start = request["event_source"]["source_span"]["char_start"]
    match = _PREFIX.fullmatch(source_text[start:event_start])
    if match is None:
        return None
    observed = {}
    for field in ("cue", "quantity", "unit", "connector"):
        left, right = match.span(field)
        observed[field + "_source"] = until._source_anchor(
            {"char_start": start + left, "char_end": start + right},
            receipt, source_text, document_text)
    _require(observed["cue_source"] == request["cue_source"], "deadline cue observation differs")
    observed["quantity"] = int(match.group("quantity"))
    observed["source_unit"] = match.group("unit").lower().removesuffix("s")
    return observed


def build_deadline_requests(receipt, proposal_receipt, *, source_text,
                            document_text=None, rule_rows=()):
    """Inventory every authenticated proposal; fill no caller meaning fields.

Until's inventory remains unchanged. This separate profile admits only plain
day/hour numeric not/no-later-than-after surfaces for a possible declaration.
Other families, exclusions, unsupported units and impossible budgets remain
visible. An absent legacy parser match is never converted to a match.
"""
    pins = producer_pins()
    original = until.build_interpretation_requests(
        receipt, proposal_receipt, source_text=source_text,
        document_text=document_text, rule_rows=rule_rows)
    document_text = source_text if document_text is None else document_text
    requests = []
    for source_request in original["requests"]:
        surface = _deadline_surface(source_request, receipt, source_text, document_text)
        if source_request["status"] == "excluded":
            status = "excluded"
        elif source_request["proposal_family"] != "not_later_than_after":
            status = "unsupported_family"
        elif surface is None or surface["source_unit"] not in {"day", "hour"}:
            status = "unsupported_surface"
        elif surface["quantity"] > MAX_DEADLINE_TICKS:
            status = "unsupported_budget"
        else:
            status = "awaiting_caller_interpretation"
        body = {key: _copy(value) for key, value in source_request.items()
                if key not in {"profile", "request_id", "request_sha256", "declaration_skeleton",
                               "status", "reason_codes", "producer_pins"}}
        reasons = [reason for reason in source_request["reason_codes"] if reason not in {
            "only_until_event_property_supported", "all_meaning_fields_require_caller_declaration"}]
        reasons.append({
            "excluded": "excluded_surface_cannot_be_declared",
            "unsupported_family": "only_not_later_than_after_deadline_profile_supported",
            "unsupported_surface": "positive_numeric_plain_day_or_hour_after_prefix_required",
            "unsupported_budget": "source_quantity_exceeds_maximum_deadline_ticks",
            "awaiting_caller_interpretation": "all_deadline_meaning_fields_require_caller_declaration",
        }[status])
        body.update(profile=PROFILE, status=status,
                    source_request_id=source_request["request_id"],
                    source_request_sha256=source_request["request_sha256"],
                    source_request_status=source_request["status"],
                    deadline_surface=surface, reason_codes=sorted(set(reasons)),
                    limits={"maximum_deadline_ticks": MAX_DEADLINE_TICKS,
                            "maximum_ast_depth": MAX_AST_DEPTH, "maximum_ast_nodes": MAX_AST_NODES},
                    authority=dict(_FALSE), producer_pins=pins)
        request = {"request_id": "deadline-interpretation-request-sha256:" + digest(body), **body}
        request["request_sha256"] = digest(request)
        source_binding = receipt["source_binding"]
        request["declaration_skeleton"] = {
            "schema": DECLARATION_SCHEMA,
            "request_id": request["request_id"], "request_sha256": request["request_sha256"],
            **{key: source_binding[key] for key in (
                "source_id", "document_id", "source_text_sha256", "document_text_sha256")},
            "occurrence_receipt_sha256": receipt["receipt_sha256"],
            "proposal_receipt_sha256": digest(proposal_receipt), "deadline_surface": _copy(surface),
            **dict.fromkeys(_MEANING_FIELDS),
        }
        requests.append(request)
    _require(producer_pins() == pins, "deadline interpretation producer changed during request construction")
    return _seal({
        "schema": REQUEST_SCHEMA, "profile": PROFILE,
        "source_binding": _copy(receipt["source_binding"]),
        "occurrence_receipt_sha256": receipt["receipt_sha256"],
        "proposal_receipt_sha256": digest(proposal_receipt),
        "source_request_inventory_sha256": original["receipt_sha256"],
        "requests": requests, "excluded": _copy(original["excluded"]),
        "issues": _copy(original["issues"]),
        "unmatched_occurrence_ids": _copy(original["unmatched_occurrence_ids"]),
        "counts": {"requests": len(requests), "issues": len(original["issues"]), **{
            status: sum(request["status"] == status for request in requests)
            for status in ("awaiting_caller_interpretation", "excluded", "unsupported_family",
                           "unsupported_surface", "unsupported_budget")}},
        "model_calls": 0, "source_binding_is_owner_resolution": False,
        "authority": dict(_FALSE), "producer_pins": pins,
    })


def _expanded_formulas(trigger, response, ticks):
    action = TemporalFormula(operator="atom", proposition=response)
    native_action = native.Predicate(response, ())
    body, native_body = action, native_action
    for _ in range(ticks):
        body = TemporalFormula(operator="or", operands=(
            action, TemporalFormula(operator="next", operands=(body,))))
        native_body = native.BinaryFormula(native.LogicOperator.OR, native_action,
            native.TemporalFormula(native.TemporalOperator.NEXT, native_body))
    formula = TemporalFormula(operator="always", operands=(
        TemporalFormula(operator="implies", operands=(
            TemporalFormula(operator="atom", proposition=trigger), body)),))
    native_formula = native.TemporalFormula(native.TemporalOperator.ALWAYS,
        native.BinaryFormula(native.LogicOperator.IMPLIES, native.Predicate(trigger, ()), native_body))
    return formula, native_formula


def _ast_budget(formula):
    nodes, maximum_depth = 0, 0
    pending = [(formula, 0)]
    while pending:
        node, depth = pending.pop()
        nodes += 1
        maximum_depth = max(maximum_depth, depth)
        _require(nodes <= MAX_AST_NODES and depth <= MAX_AST_DEPTH, "deadline LTL expansion exceeds AST budget")
        pending.extend((child, depth + 1) for child in node.operands)
    return {"nodes": nodes, "maximum_depth": maximum_depth}


def _event_ltl_expression(formula):
    """The same closed G/implies/or/X/atom AST, with event role interpretation."""
    op = formula.operator.value
    if op == "atom":
        return "(trace.occurs " + until.lean.string(formula.proposition) + ")"
    children = [_event_ltl_expression(child) for child in formula.operands]
    if op in {"always", "next"}:
        return "(" + {"always": "alwaysTime", "next": "nextTime"}[op] + " " + children[0] + ")"
    _require(op in {"or", "implies"} and len(children) == 2, "unsupported deadline LTL expansion operator")
    return "(fun t => (" + children[0] + " t) " + {"or": "∨", "implies": "→"}[op] + " (" + children[1] + " t))"


def _lean_declarations(trigger, response, ticks, formula):
    trigger_lean, response_lean = until.lean.string(trigger), until.lean.string(response)
    return (
        "structure DeadlineEventInterpretation where\n"
        "  occurs : String → Nat → Prop\n\n"
        "def boundedResponse (response : Nat → Prop) : Nat → Nat → Prop\n"
        "  | 0, t => response t\n"
        "  | n + 1, t => response t ∨ boundedResponse response n (t + 1)\n\n"
        "def deadlineTemporalProperty (trace : DeadlineEventInterpretation) (origin : Nat) : Prop :=\n"
        "  ∀ triggerTick, origin ≤ triggerTick → trace.occurs " + trigger_lean + " triggerTick →\n"
        "    ∃ responseTick, triggerTick ≤ responseTick ∧ responseTick ≤ triggerTick + " + str(ticks) +
        " ∧ trace.occurs " + response_lean + " responseTick\n\n"
        "def deadlineExpandedProperty (trace : DeadlineEventInterpretation) : Nat → Prop :=\n"
        "  alwaysTime (fun t => trace.occurs " + trigger_lean + " t →\n"
        "    boundedResponse (trace.occurs " + response_lean + ") " + str(ticks) + " t)\n\n"
        "def deadlineNativeLTLProperty (trace : DeadlineEventInterpretation) : Nat → Prop :=\n  " +
        _event_ltl_expression(formula) + "\n"
    )


def prepare_deadline_interpretation(receipt, proposal_receipt, declaration, *, source_text,
                                    document_text=None, rule_rows=()):
    """Compile a fully supplied closed-interval response property, never a norm."""
    pins = producer_pins()
    inventory = build_deadline_requests(receipt, proposal_receipt, source_text=source_text,
                                         document_text=document_text, rule_rows=rule_rows)
    _closed(declaration, {"schema", *_BINDING_FIELDS, *_MEANING_FIELDS}, "deadline interpretation declaration")
    _require(declaration["schema"] == DECLARATION_SCHEMA, "deadline interpretation declaration schema differs")
    matches = [request for request in inventory["requests"] if request["request_id"] == declaration["request_id"]]
    _require(len(matches) == 1, "exact deadline request ID required")
    request = matches[0]
    _require(_wire({key: declaration[key] for key in _BINDING_FIELDS}) ==
             _wire({key: request["declaration_skeleton"][key] for key in _BINDING_FIELDS}),
             "deadline request/source/surface binding differs")
    _require(request["status"] == "awaiting_caller_interpretation", "unsupported or excluded deadline request")
    _require(all(declaration[key] is not None for key in _MEANING_FIELDS), "complete caller deadline meaning required")
    required = {
        "trigger_scope": "each_trigger_at_or_after_evaluation_origin",
        "deadline_origin": "each_trigger_occurrence_time",
        "time_domain": "discrete_unbounded_nat", "evaluation_origin": "caller_supplied_evaluation_time",
        "modal_scope": "temporal_property_only",
        "response_reuse": "one_response_may_satisfy_multiple_triggers",
    }
    _require(all(declaration[key] == value for key, value in required.items()) and
             declaration["lower_inclusive"] is True and declaration["upper_inclusive"] is True,
             "unsupported deadline scope/origin/endpoints/response policy")
    factor = declaration["ticks_per_source_unit"]
    _require(type(factor) is int and 1 <= factor <= MAX_DEADLINE_TICKS,
             "positive bounded integer ticks per source unit required")
    ticks = declaration["deadline_surface"]["quantity"] * factor
    _require(1 <= ticks <= MAX_DEADLINE_TICKS, "declared deadline ticks exceed expansion budget")
    for key in ("trigger_atom", "response_atom"):
        _require(type(declaration[key]) is str and until._ATOM.fullmatch(declaration[key]) is not None,
                 "bounded distinct deadline identifier atoms required")
    trigger, response = declaration["trigger_atom"], declaration["response_atom"]
    _require(trigger != response, "trigger and response atoms must be distinct")
    start, end = until._span(declaration["response_source_span"], source_text)
    temporal_span = request["temporal_source"]["source_span"]
    _require(end <= temporal_span["char_start"] or start >= temporal_span["char_end"],
             "response source anchor must not overlap deadline qualifier")
    _require(type(declaration["response_source_text"]) is str and
             declaration["response_source_text"] == source_text[start:end] and
             re.search(r"\w", source_text[start:end], re.UNICODE) is not None,
             "exact lexical response source text required")
    response_source = until._source_anchor(declaration["response_source_span"], receipt,
        source_text, source_text if document_text is None else document_text)
    typed, native_formula = _expanded_formulas(trigger, response, ticks)
    ast_budget = _ast_budget(typed)
    ast = typed.to_dict()
    _require(TemporalFormula.from_dict(ast).to_dict() == ast, "deadline typed temporal AST roundtrip differs")
    # Native prefix printing puts a nullary atom immediately before the next
    # parenthesized operand; the parser can read that as a predicate argument.
    # Its existing recursive infix printer is unambiguous for this fragment.
    concrete = native_formula.to_string(pretty=True)
    diagnostics = [until.family.validate_family_artifact(name, concrete)
                   for name in ("temporal_fol", "deontic_temporal_fol")]
    _require(all(item["passed"] and item["syntax_valid"] for item in diagnostics),
             "strict bounded-response TDFOL validation failed")
    parsed, strict_receipt = until.family._strict_tdfol(concrete)
    native_ast = modal_projections._ast(native_formula)
    _require(modal_projections._ast(parsed) == native_ast and parsed.to_string(pretty=True) == concrete,
             "deadline native AST strict roundtrip differs")
    renderer = until.lean.FormulaRenderer()
    generic_expression = renderer.formula(native_ast)
    declarations = _lean_declarations(trigger, response, ticks, typed)
    _require(producer_pins() == pins, "deadline producer changed during preparation")
    return _seal({
        "schema": ARTIFACT_SCHEMA, "profile": PROFILE,
        "declaration": _copy(declaration), "declaration_sha256": digest(declaration),
        "request": _copy(request), "request_inventory_sha256": inventory["receipt_sha256"],
        "source_binding": _copy(receipt["source_binding"]),
        "response_source": response_source, "trigger_source": _copy(request["event_source"]),
        "response_anchor_scope": "source_anchor_only_not_canonical_legal_owner",
        "atom_roles": {trigger: "trigger_occurs", response: "response_occurs"},
        "deadline_ticks": ticks, "temporal_ast": ast, "native_tdfol_ast": native_ast,
        "ast_budget": ast_budget, "tdfol_formula": concrete,
        "family_diagnostics": diagnostics, "strict_tdfol_receipt": strict_receipt,
        "native_renderer_diagnostic": {
            "validator": "FormulaRenderer_exact_native_AST",
            "scope": "generic_atom_interpretation_only_event_roles_supplied_separately",
            "operators": renderer.operators, "expression": generic_expression,
        },
        "lean_declarations": declarations, "lean_source": until.lean.PRELUDE + "\n" + declarations,
        "lean_prelude_sha256": hashlib.sha256(until.lean.PRELUDE.encode()).hexdigest(),
        "semantics": {
            "scope": "caller_supplied_interpretation_not_source_translation", **required,
            "lower_inclusive": True, "upper_inclusive": True,
            "ticks_per_source_unit": factor, "deadline_ticks": ticks,
            "source_unit": request["deadline_surface"]["source_unit"],
            "independent_trigger_and_response_event_traces": True,
            "trigger_existence_required": False, "absent_trigger_property_is_vacuously_true": True,
            "earlier_than_trigger_response_qualifies": False,
            "same_tick_response_qualifies": True, "response_at_final_deadline_tick_qualifies": True,
            "one_response_can_witness_multiple_trigger_windows": True,
            "source_units_are_caller_declared_tick_scales_not_wall_clock_conversion": True,
            "syntax_atom_roles_supplied_separately": True,
        },
        "assumptions": [
            "Every trigger at or after evaluation origin has a response in its own closed [trigger, trigger + ticks] window.",
            "Distinct nullary trigger and response symbols denote independent arbitrary event traces, not attested events.",
            "The caller supplies ticks per source unit. No calendar, business-day or real-time conversion is performed.",
            "A response can witness multiple overlapping trigger windows; no per-instance event correlation or response consumption is asserted.",
            "Absent triggers make this conditional temporal property vacuously true; no trigger existence, law or compliance follows.",
            "The exact source anchor supplies no canonical rule ownership or natural-language fidelity.",
            "Typed LTL and strict family diagnostics preserve bounded response through finite X/or expansion; no bounded TDFOL grammar is assumed.",
            "Source/family qualification, modal obligations and admission remain unestablished, including when the property is satisfied.",
        ],
        "model_calls": 0, "authority": dict(_FALSE), "producer_pins": pins,
    })


def validate_deadline_interpretation(artifact, receipt, proposal_receipt, *, source_text,
                                    document_text=None, rule_rows=()):
    """Regenerate source binding, expansion, declarations and every output field."""
    _require(type(artifact) is dict and artifact.get("schema") == ARTIFACT_SCHEMA,
             "versioned deadline interpretation artifact required")
    expected = prepare_deadline_interpretation(receipt, proposal_receipt, artifact.get("declaration"),
        source_text=source_text, document_text=document_text, rule_rows=rule_rows)
    _require(_wire(expected) == _wire(artifact), "deadline interpretation artifact differs from exact replay")
    return _copy(expected)


__all__ = ["build_deadline_requests", "prepare_deadline_interpretation", "validate_deadline_interpretation",
           "producer_pins", "digest", "REQUEST_SCHEMA", "DECLARATION_SCHEMA", "ARTIFACT_SCHEMA", "PROFILE",
           "MAX_DEADLINE_TICKS", "MAX_AST_DEPTH", "MAX_AST_NODES"]
