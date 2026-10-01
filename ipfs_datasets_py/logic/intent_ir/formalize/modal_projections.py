"""Native parsed DCEC, TDFOL and event-calculus views of declared Intent IR.

The projection preserves supplied declarations; it does not establish that
neural intent extraction understood its source. Norms never become observed
events. Unsupported modalities and absent event evidence remain explicit.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
import re


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _require(value, message):
    if not value:
        raise ValueError(message)


def _ast(value):
    """Inert native AST snapshot, never an executable object serialization."""
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": value.value}
    if is_dataclass(value):
        return {"node_type": type(value).__name__,
                **{field.name: _ast(getattr(value, field.name)) for field in fields(value)}}
    if type(value) in (tuple, list):
        return [_ast(child) for child in value]
    if type(value) in (str, int, float, bool) or value is None:
        return value
    raise ValueError("unrecognized native modal AST field")


class _Symbols:
    def __init__(self, family):
        self.family = family
        self.rows = {}

    def bind(self, role, value):
        _require(type(value) is str and 0 < len(value) <= 4096, "bounded nonempty semantic symbol required")
        digest = _sha([role, value])
        # Native TDFOL parses bare identifiers as variables. A colon-qualified
        # atom is its explicit constant spelling. CEC uses uppercase constants.
        symbol = ("entity:" + digest) if role == "argument" and self.family == "tdfol" else "S" + digest
        row = {"role": role, "value": value, "symbol": symbol}
        _require(symbol not in self.rows or self.rows[symbol] == row, "semantic symbol collision")
        self.rows[symbol] = row
        return symbol


def _dcec_print(formula):
    """Print the supported native AST subset without its zero-arity bug.

    The upstream CEC printer emits ``Constant()`` while its parser rejects
    empty functional arguments. This adapter prints zero-arity constants as
    names and checks native parse/print/parse AST equality independently.
    """
    from ...CEC.native import dcec_core as c

    def term(value):
        _require(type(value) is c.FunctionTerm and not value.arguments and
                 not value.function.argument_sorts and re.fullmatch(r"S[0-9a-f]{64}", value.function.name),
                 "bounded ground DCEC constant required")
        return value.function.name

    if type(formula) is c.AtomicFormula:
        _require(formula.arguments and re.fullmatch(r"S[0-9a-f]{64}", formula.predicate.name),
                 "bounded nonzero-arity DCEC predicate required")
        return formula.predicate.name + "(" + ", ".join(term(arg) for arg in formula.arguments) + ")"
    if type(formula) is c.DeonticFormula:
        _require(formula.agent is None and formula.operator in
                 (c.DeonticOperator.OBLIGATION, c.DeonticOperator.PERMISSION, c.DeonticOperator.PROHIBITION),
                 "unsupported DCEC deontic node")
        return formula.operator.value + "(" + _dcec_print(formula.formula) + ")"
    if type(formula) is c.CognitiveFormula:
        _require(formula.operator is c.CognitiveOperator.INTENTION, "only declared intention is projected")
        return "I(" + term(formula.agent) + ", " + _dcec_print(formula.formula) + ")"
    if type(formula) is c.TemporalFormula:
        operators = {c.TemporalOperator.ALWAYS: "always", c.TemporalOperator.EVENTUALLY: "eventually",
                     c.TemporalOperator.NEXT: "next"}
        _require(formula.operator in operators, "unsupported DCEC temporal operator")
        return operators[formula.operator] + "(" + _dcec_print(formula.formula) + ")"
    raise ValueError("unsupported DCEC AST node")


def _native_modal(family, source, expected_operator, temporal_operator=None):
    temporal_symbols = {"always": "□", "eventually": "◊", "next": "X"}
    if family == "dcec":
        from ...CEC.native.dcec_integration import parse_dcec_string
        from ...CEC.native import dcec_core as c
        parsed = parse_dcec_string(source)
        inner = parsed
        if temporal_operator is not None:
            _require(type(parsed) is c.TemporalFormula and parsed.operator.value == temporal_symbols[temporal_operator],
                     "native DCEC parser changed temporal operator or scope")
            inner = parsed.formula
        if expected_operator == "I":
            _require(type(inner) is c.CognitiveFormula and inner.operator is c.CognitiveOperator.INTENTION,
                     "native DCEC parser lost intention operator")
        elif expected_operator:
            _require(type(inner) is c.DeonticFormula and inner.operator.value == expected_operator,
                     "native DCEC parser lost deontic operator")
        else:
            _require(type(inner) is c.AtomicFormula, "native DCEC parser lost atomic proposition")
        printed = _dcec_print(parsed)
        replay = parse_dcec_string(printed)
    else:
        from ...TDFOL.tdfol_parser import parse_tdfol
        from ...TDFOL import tdfol_core as c
        parsed = parse_tdfol(source)
        inner = parsed
        if temporal_operator is not None:
            _require(type(parsed) is c.TemporalFormula and parsed.operator.value == temporal_symbols[temporal_operator],
                     "native TDFOL parser changed temporal operator or scope")
            inner = parsed.formula
        if expected_operator:
            _require(type(inner) is c.DeonticFormula and inner.operator.value == expected_operator,
                     "native TDFOL parser lost deontic operator")
        else:
            _require(type(inner) is c.Predicate, "native TDFOL parser lost atomic proposition")
        printed = parsed.to_string()
        replay = parse_tdfol(printed)
    _require(parsed is not None and parsed == replay, "native modal parse/print/parse changed AST")
    _require(not parsed.get_free_variables(), "modal declaration acquired free variables")
    return {"source": printed, "ast": _ast(parsed), "ast_sha256": _sha(_ast(parsed)),
            "native_parse_passed": True, "native_ast_roundtrip_passed": True,
            "free_variables": [], "backend_proof_executed": False}


def _statement_views(document, family, context):
    from ..schema import StatementKind, IntentModality
    from .projection_contracts import make_projection
    symbols, formulas, unsupported = _Symbols(family), [], []
    operators = {IntentModality.REQUIRED: "O", IntentModality.PERMITTED: "P", IntentModality.PROHIBITED: "F"}
    temporal_bindings = {row["statement_id"]: row for row in context.get("temporal_bindings", [])}
    assumptions = ["Only declared predicate/argument identities and modality are projected; source meaning is unverified.",
                   "No implicit temporal instant, truth of a goal, agent knowledge, or execution permission is asserted.",
                   "Native AST parsing and roundtrip do not discharge a proof obligation."]
    for statement in document.statements:
        reason = None
        temporal = temporal_bindings.get(statement.statement_id)
        # Match the established native Intent compiler: an asserted GOAL is
        # an intended outcome, never an assertion that the outcome is true.
        modality = (IntentModality.INTENDED if statement.kind is StatementKind.GOAL and
                    statement.modality is IntentModality.ASSERTED else statement.modality)
        if not statement.predicate or not statement.arguments:
            reason = "explicit_nonzero_arity_predicate_and_arguments_required"
        elif len(statement.arguments) > 32:
            reason = "predicate_arity_exceeds_bounded_modal_subset"
        elif statement.kind not in (StatementKind.GOAL, StatementKind.ASSUMPTION):
            reason = "statement_role_requires_state_or_action_contract_projection"
        elif modality is IntentModality.RECOMMENDED:
            reason = "recommendation_has_no_equivalent_strict_deontic_operator"
        elif modality is IntentModality.INTENDED and family == "tdfol":
            reason = "intention_agency_operator_not_in_tdfol_subset"
        if reason:
            unsupported.append({"node_id": statement.statement_id, "reason": reason}); continue
        operator = operators.get(modality, "")
        predicate = symbols.bind("predicate", statement.predicate)
        arguments = [symbols.bind("argument", arg) for arg in statement.arguments]
        atom = predicate + "(" + ", ".join(arguments) + ")"
        source = operator + "(" + atom + ")" if operator else atom
        actor_binding = None
        if modality is IntentModality.INTENDED:
            matches = [action for action in document.actions if action.verb == statement.predicate and
                       statement.arguments == (action.actor, *action.object_refs)]
            if len(matches) != 1:
                unsupported.append({"node_id": statement.statement_id,
                                    "reason": "intention_requires_unique_exact_action_actor_binding"}); continue
            actor_binding = matches[0].action_id
            source = "I(" + symbols.bind("argument", matches[0].actor) + ", " + atom + ")"
            operator = "I"
        if temporal is not None:
            spelling = ({"always": "always", "eventually": "eventually", "next": "next"} if family == "dcec" else
                        {"always": "□", "eventually": "◊", "next": "X"})[temporal["operator"]]
            source = spelling + "(" + source + ")"
        row = _native_modal(family, source, operator, temporal["operator"] if temporal else None)
        row.update(statement_id=statement.statement_id, statement_kind=statement.kind.value,
                   original_modality=statement.modality.value, source_ref_ids=list(statement.source_ref_ids),
                   effective_modality=modality.value,
                   actor_binding_action_id=actor_binding, inferred=statement.grounding.value == "inferred",
                   semantic_role="assumption" if statement.kind is StatementKind.ASSUMPTION else "goal_declaration")
        if temporal is not None:
            row["temporal_scope"] = {**temporal, "placement": "outside_complete_modal_proposition",
                                     "evidence_verified": False}
        formulas.append(row)
    for action in document.actions:
        if any(getattr(action, key) for key in ("precondition_ids", "effect_ids", "verification_ids", "tool_refs")):
            unsupported.append({"node_id": action.action_id, "reason": "action_constraints_require_separate_projection"})
    unsupported.extend({"node_id": edge.edge_id, "reason": "workflow_edges_require_temporal_transition_projection"}
                       for edge in document.control_edges)
    if family == "dcec":
        assumptions.append("Bounded constant serializer compensates for the native CEC printer's empty-function parse incompatibility.")
    assumptions.append("An asserted GOAL follows the native Intent compiler convention: intended outcome, not achieved fact.")
    if temporal_bindings:
        assumptions.extend([
            "Temporal scope is an explicit caller-supplied trace premise bound to a native source reference; its truth is unverified.",
            "The temporal operator scopes over the complete norm or intention; Always(Obligation(p)) is not Obligation(Always(p)).",
            "Native TDFOL uses ◊ for eventuality and F only for prohibition, avoiding the classic F ambiguity.",
            "No time instant, duration, deadline, fairness assumption, or actual execution trace is inferred."])
    payload = {"formulas": formulas, "symbols": [symbols.rows[key] for key in sorted(symbols.rows)],
               "native_syntax_profile": family + "_default"}
    if temporal_bindings:
        payload["temporal_bindings"] = list(context["temporal_bindings"])
    return make_projection(document, family_id=family,
        status="partial" if formulas and unsupported else "projected" if formulas else "unsupported",
        representation={"format": "native_" + family + "_ast", "payload": payload,
            "source": "\n".join(row["source"] for row in formulas)},
        source_node_ids=list(dict.fromkeys([row["statement_id"] for row in formulas] +
            [row["temporal_scope"]["evidence_ref"] for row in formulas if "temporal_scope" in row])),
        validation=[{"validator": family + ".native_parse_and_ast_roundtrip",
            "status": "passed" if formulas else "not_run", "details": {"formula_count": len(formulas),
            "semantic_operator_checked": bool(formulas), "proof_run": False,
            "fully_typed_kernel_check": False}}], assumptions=assumptions, unsupported=unsupported,
        semantics="statement_modality_projection")


def _context(context):
    if context is None:
        return {"event_occurrences": [], "effect_bindings": []}
    _require(type(context) is dict, "projection context must be an object")
    value = context.get("modal", {})
    _require(type(value) is dict and set(value) <= {"event_occurrences", "effect_bindings", "temporal_bindings"},
             "unknown modal projection context field")
    result = {}
    for name in ("event_occurrences", "effect_bindings"):
        rows = value.get(name, [])
        _require(type(rows) is list and len(rows) <= 256, "bounded modal context rows required")
        result[name] = rows
        for row in rows:
            expected = {"action_id", "time", "evidence_ref"} if name == "event_occurrences" else {
                "action_id", "statement_id", "kind", "evidence_ref"}
            _require(type(row) is dict and set(row) == expected, "closed modal evidence row required")
            _require(type(row["action_id"]) is str and type(row["evidence_ref"]) is str and
                     0 < len(row["evidence_ref"]) <= 512 and not any(ord(c) < 32 for c in row["evidence_ref"]),
                     "explicit bounded event/effect evidence reference required")
            if name == "event_occurrences":
                _require(type(row["time"]) is int and 0 <= row["time"] <= 10**9,
                         "explicit bounded integer occurrence time required")
            else:
                _require(type(row["statement_id"]) is str and row["kind"] in ("initiates", "terminates"),
                         "explicit typed effect polarity required")
        _require(len({_sha(row) for row in rows}) == len(rows), "duplicate modal evidence row")
    if "temporal_bindings" in value:
        rows = value["temporal_bindings"]
        _require(type(rows) is list and len(rows) <= 128, "bounded temporal context rows required")
        seen = set()
        for row in rows:
            _require(type(row) is dict and set(row) == {"statement_id", "operator", "evidence_ref"} and
                     type(row["statement_id"]) is str and type(row["operator"]) is str and
                     row["operator"] in {"always", "eventually", "next"} and
                     type(row["evidence_ref"]) is str and 0 < len(row["evidence_ref"]) <= 512 and
                     not any(ord(char) < 32 for char in row["evidence_ref"]),
                     "closed temporal scope with explicit native source reference required")
            _require(row["statement_id"] not in seen, "one explicit temporal scope per statement required")
            seen.add(row["statement_id"])
        result["temporal_bindings"] = rows
    return result


def _event_view(document, context):
    from ..schema import StatementKind, IntentModality
    from ...parsers.event_calculus import parse_print_parse
    from .projection_contracts import make_projection
    symbols, formulas, unsupported = _Symbols("event_calculus"), [], []
    actions = {row.action_id: row for row in document.actions}
    statements = {row.statement_id: row for row in document.statements}
    covered_actions, covered_statements = set(), set()
    source_refs = {source.ref_id for source in document.sources}

    def add(source, node_ids, evidence_ref, role):
        first, second, equivalent = parse_print_parse(source)
        _require(first.ok and second.ok and equivalent and first.root is not None,
                 "native event-calculus parser rejected generated syntax")
        formulas.append({"source": first.printed, "ast": first.root.to_dict(),
            "native_parse_passed": True, "native_ast_roundtrip_passed": True,
            "source_node_ids": node_ids, "evidence_ref": evidence_ref, "semantic_role": role,
            "evidence_verified": False, "backend_proof_executed": False})

    for row in context["event_occurrences"]:
        _require(row["action_id"] in actions, "event occurrence references unknown action")
        _require(row["evidence_ref"] in source_refs, "event evidence must reference a native SourceRef")
        event = symbols.bind("action_event", row["action_id"])
        add(f"happens({event}, {row['time']})", [row["action_id"], row["evidence_ref"]], row["evidence_ref"],
            "caller_declared_occurrence_not_an_observation_by_this_projector")
        covered_actions.add(row["action_id"])
    for row in context["effect_bindings"]:
        _require(row["action_id"] in actions and row["statement_id"] in statements,
                 "effect binding references unknown action or statement")
        action, statement = actions[row["action_id"]], statements[row["statement_id"]]
        _require(row["evidence_ref"] in source_refs, "effect evidence must reference a native SourceRef")
        _require(statement.statement_id in action.effect_ids and statement.kind in
                 (StatementKind.EFFECT, StatementKind.POSTCONDITION) and statement.predicate and
                 statement.modality is IntentModality.ASSERTED,
                 "effect binding requires an explicit asserted action effect link")
        _require(not action.precondition_ids, "conditional action effects need an explicit guarded event model")
        event = symbols.bind("action_event", action.action_id)
        fluent = symbols.bind("effect_fluent", statement.statement_id)
        add(f"forall t:Time. {row['kind']}({event}, {fluent}, t)",
            [action.action_id, statement.statement_id, row["evidence_ref"]], row["evidence_ref"],
            "caller_declared_time_independent_effect_law")
        covered_actions.add(action.action_id); covered_statements.add(statement.statement_id)
    unsupported.extend({"node_id": row.action_id, "reason": "no_occurrence_time_or_explicit_effect_context"}
                       for row in document.actions if row.action_id not in covered_actions)
    unsupported.extend({"node_id": row.statement_id, "reason": "intent_or_norm_is_not_an_observed_event_or_fluent"}
                       for row in document.statements if row.statement_id not in covered_statements)
    unsupported.extend({"node_id": edge.edge_id, "reason": "workflow_edge_is_not_an_observed_trace"}
                       for edge in document.control_edges)
    return make_projection(document, family_id="event_calculus",
        status="partial" if formulas and unsupported else "projected" if formulas else "unsupported",
        representation={"format": "canonical_event_calculus", "payload": {"formulas": formulas,
            "symbols": [symbols.rows[key] for key in sorted(symbols.rows)], "context": context,
            "native_syntax_profile": "event_calculus_classical",
            "event_bindings": [{"action_id": identifier, "actor": actions[identifier].actor,
                "verb": actions[identifier].verb, "object_refs": list(actions[identifier].object_refs)}
                for identifier in sorted(covered_actions)],
            "fluent_bindings": [{"statement_id": identifier, "predicate": statements[identifier].predicate,
                "arguments": list(statements[identifier].arguments)} for identifier in sorted(covered_statements)]},
            "source": "\n".join(row["source"] for row in formulas)},
        source_node_ids=sorted({node for row in formulas for node in row["source_node_ids"]}),
        validation=[{"validator": "event_calculus.native_parse_print_parse", "status": "passed" if formulas else "not_run",
            "details": {"formula_count": len(formulas), "alpha_equivalent_roundtrip": bool(formulas), "proof_run": False}}],
        assumptions=["Actions and goals alone are not evidence that events happened.",
                     "Context evidence references are caller declarations; their truth has not been checked.",
                     "Effect laws quantify a time variable and require an explicit time-independent effect premise.",
                     "No inertia, clock instant, deadline, precondition satisfaction, or event observation is invented."],
        unsupported=unsupported, semantics="caller_grounded_event_and_effect_projection")


def project_modal_families(document, context=None):
    """Return three reports; missing semantic prerequisites stay explicit."""
    from ..schema import validate_intent_ir
    from ..decoder import decode_intent_ir
    if type(document) is dict:
        document = decode_intent_ir(document)
    document = validate_intent_ir(document)
    _require(len(document.statements) <= 128 and len(document.actions) <= 128 and len(document.control_edges) <= 256,
             "bounded Intent declaration required")
    observed = _context(context)
    for row in observed.get("temporal_bindings", []):
        _require(row["statement_id"] in {statement.statement_id for statement in document.statements} and
                 row["evidence_ref"] in {source.ref_id for source in document.sources},
                 "temporal scope must bind a declared statement and native SourceRef")
    return [_statement_views(document, "dcec", observed), _statement_views(document, "tdfol", observed),
            _event_view(document, observed)]
