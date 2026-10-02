"""Lower explicit scalar Intent action contracts using a caller's parameter map.

This builder accepts a source-bound prediction from the controlled action
contract codec. It translates declared predicate meanings; it never chooses a
code implementation, supplies a missing effect, or changes a prediction to
match observed code results. The existing finite-effects owner validates the
complete result, retaining both refutations and disabled inputs.
"""
from __future__ import annotations

from copy import deepcopy

from . import intent_code_effects as effects
from . import native_interpretation_expressions as typed
from .security import source_state_model as states
from ...intent_ir.formalize import action_contracts as codec
from ...ir_core import provenance
from ...software_verification import program

PROFILE = "explicit-scalar-Intent-code-association/v1"
PRODUCERS = tuple(dict.fromkeys((effects, *effects.PRODUCERS, typed, *typed.PRODUCERS,
    states, *states.PRODUCERS, codec, *getattr(codec, "PRODUCERS", ()), provenance, program)))


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def build_intent_action_association(intent_source, intent_candidate, code_source, code_candidate, input_domains,
        *, action_id, input_parameter_mapping):
    """Build the closed finite-effects association from explicit predicted meanings.

    ``input_parameter_mapping`` is an exact bijection from ``left``/``right`` to
    the two declared code parameter names. ``result`` and ``returned`` denote
    the code's return observation fields, not arbitrary source locals. The
    candidate must already carry its exact original instruction provenance.
    """
    _require(type(intent_candidate) is dict and set(intent_candidate) == {"kind", "document"}
        and intent_candidate["kind"] == "document", "source-bound native Intent document envelope required")
    codec.verify_bound_candidate_source(intent_source, intent_candidate)
    _require(type(action_id) is str and action_id == "action", "explicit selected scalar contract action required")
    _require(type(input_parameter_mapping) is dict and set(input_parameter_mapping) == {"left", "right"}
        and all(type(value) is str for value in input_parameter_mapping.values()),
        "explicit complete left/right code parameter mapping required")
    requirements = effects.intent_code_effect_requirements(
        intent_source, intent_candidate, code_source, code_candidate, input_domains)
    model = states.derive_source_state_model(code_source, code_candidate, input_domains)
    _require(len(model["parameter_order"]) == 2
        and set(input_parameter_mapping.values()) == set(model["parameter_order"]),
        "Intent inputs must bijectively bind the exact two code parameters")
    _require(model["result_type"] == "integer", "scalar arithmetic Intent requires an integer code result")
    actions = {row["action_id"]: row for row in requirements["actions"]}
    action = actions.get(action_id)
    _require(action is not None and action["precondition_ids"] == ["precondition"]
        and set(action["effect_ids"]) == {"effect:equation", "effect:returned"},
        "complete predicted scalar precondition and effects required")
    statements = {row["statement_id"]: row for row in requirements["statements"]}
    pre, equation, returned = [statements[key] for key in ("precondition", "effect:equation", "effect:returned")]
    _require(equation["predicate"] == "return_equation" and len(equation["arguments"]) == 4,
        "explicit returned arithmetic equation required")
    result_name, left, operator, right = equation["arguments"]
    _require(result_name == "result" and left in {"old:left", "old:right"}
        and right in {"old:left", "old:right"} and operator in {"add", "sub", "mul"}
        and returned["predicate"] == "returned" and returned["arguments"] == ["returned"],
        "closed scalar old-input equation and returned observation required")
    intent_refs, code_refs = requirements["intent_source_refs"], requirements["code_source_refs"]
    _require(len(intent_refs) == len(code_refs) == 1 and intent_refs[0]["ref_id"] == "intent-contract:source",
        "single exact contract and code evidence references required")
    intent_ref, code_ref = intent_refs[0]["ref_id"], code_refs[0]["ref_id"]
    _require(action["source_ref_ids"] == [intent_ref]
        and all(row["source_ref_ids"] == [intent_ref] for row in (pre, equation, returned)),
        "predicted conditions require original instruction evidence")
    refs = (code_ref,)
    role_variables = {name: model["parameter_variables"][parameter]
        for name, parameter in input_parameter_mapping.items()}
    role_variables.update(result=model["result_variable_id"], returned=model["returned_variable_id"])
    roles = ("left", "right", "result", "returned")
    symbols = [program.ProgramSymbol("intent-contract:" + role, role,
        type_ref="boolean" if role == "returned" else "integer", kind="global", source_ref_ids=refs) for role in roles]
    expressions = []

    def expression(identity, kind, type_ref="integer", *, children=(), operator="", role=None, value=None):
        expressions.append(program.ProgramExpression(identity, kind, type_ref, operand_ids=children,
            evaluation_order=children, operator=operator,
            symbol_ids=() if role is None else ("intent-contract:" + role,),
            attributes={"value": value} if kind == "literal" else {}, source_ref_ids=refs))
        return identity

    # Distinct expression occurrences preserve subtraction order and repeated
    # source operands without violating ProgramIR's unique operand-ID contract.
    operands = []
    for position, operand in enumerate((left, right)):
        read = expression("contract:operand:" + str(position), "symbol", role=operand[4:])
        operands.append(expression("contract:old:" + str(position), "old", children=(read,)))
    expected = expression("contract:expected", "binary", children=tuple(operands), operator=operator)
    result = expression("contract:result", "symbol", role="result")
    equation_root = expression("contract:equation", "binary", "boolean", children=(result, expected), operator="eq")
    returned_root = expression("contract:returned", "symbol", "boolean", role="returned")
    if pre["predicate"] == "input_true" and pre["arguments"] == []:
        pre_root = expression("contract:precondition", "literal", "boolean", value=True)
    else:
        _require(pre["predicate"] == "input_gt" and len(pre["arguments"]) == 2
            and pre["arguments"][0] in {"left", "right"}, "closed scalar input precondition required")
        role, decimal = pre["arguments"]
        _require(type(decimal) is str, "canonical integer precondition threshold required")
        try:
            threshold = int(decimal)
        except (ValueError, TypeError):
            raise ValueError("canonical integer precondition threshold required") from None
        _require(str(threshold) == decimal and abs(threshold) <= 1_000_000,
            "bounded canonical precondition integer required")
        read = expression("contract:precondition:input", "symbol", role=role)
        literal = expression("contract:precondition:threshold", "literal", value=threshold)
        pre_root = expression("contract:precondition", "binary", "boolean", children=(read, literal), operator="gt")
    carrier = typed.make_carrier(symbols, expressions,
        sources=tuple(provenance.SourceRef.from_dict(row) for row in code_refs))
    binding = lambda sid, root: dict(statement_id=sid, expression_id=root, evidence_ref=intent_ref)
    association = dict(schema=effects.ASSOCIATION_SCHEMA,
        **{key: requirements[key] for key in effects.IDENTITY_FIELDS}, action_id=action_id,
        intent_evidence_ref=intent_ref, code_evidence_ref=code_ref, expression_program=carrier,
        symbol_bindings=[dict(symbol_id="intent-contract:" + role, state_variable_id=role_variables[role]) for role in roles],
        precondition_bindings=[binding("precondition", pre_root)],
        effect_bindings=[binding("effect:equation", equation_root), binding("effect:returned", returned_root)])
    # Exact native typing, source identities, all condition roots and all finite
    # cases are replayed. Their truth does not influence the constructed formula.
    effects.prepare_intent_code_effects(intent_source, intent_candidate, code_source, code_candidate,
        input_domains, association)
    return association


def verify_intent_action_association(association, intent_source, intent_candidate, code_source, code_candidate,
        input_domains, *, action_id, input_parameter_mapping):
    """Reject modified generated formulas, provenance, mappings or native inputs."""
    expected = build_intent_action_association(intent_source, intent_candidate, code_source, code_candidate,
        input_domains, action_id=action_id, input_parameter_mapping=input_parameter_mapping)
    _require(typed.canonical(association) == typed.canonical(expected), "scalar Intent association differs from exact replay")
    return deepcopy(expected)


__all__ = ["PROFILE", "PRODUCERS", "build_intent_action_association", "verify_intent_action_association"]
