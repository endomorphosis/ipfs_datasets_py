"""Finite return observations derived from an exactly source-qualified program.

The existing scalar source binding owns parsing, candidate comparison, typing
and effect refinement. This module evaluates its closed ProgramIR data only;
Python source is never executed. Explicit parameter intervals bound all input
combinations. Locals are absent until assigned and no security goal is inferred.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import product
import json

from . import source_program_binding_384_v2 as binding
from ....software_verification import program as program_types
from ....software_verification import state as state_types
from ....software_verification import transitions
from ....software_verification import source_adapters, syntax_bridge

SCHEMA = "security-source-state-model/v1"
MAX_INPUT_CASES = 64
MAX_ABS_INPUT = 1_000_000
RESULT_VARIABLE = "state:result"
RETURNED_VARIABLE = "state:returned"
PRODUCERS = (binding, binding.previous, program_types, state_types, transitions,
             source_adapters, syntax_bridge)
FALSE = dict(proof_authority=False, execution_authority=False,
    completion_authority=False, source_semantics_verified=False,
    whole_program_semantics_verified=False, security_specification_inferred=False,
    source_executed=False, model_inference_executed=False,
    candidate_rewritten=False, candidate_repaired=False, qualified=False,
    admitted=False, model_checker_executed=False, liveness_proved=False)


class SourceStateModelError(ValueError):
    """The exact source/candidate, finite inputs or scalar model is unsupported."""


def _require(condition, reason):
    if not condition:
        raise SourceStateModelError(reason)


def _raw(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as error:
        raise SourceStateModelError("inert_source_state_JSON_required") from error
    _require(len(encoded) <= 2 * 1024 * 1024, "bounded_source_state_report_required")
    return encoded


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _domains(value, names):
    _require(type(value) is dict and set(value) == set(names),
             "exact_source_parameter_domains_required")
    result, size = {}, 1
    for name in names:
        row = value[name]
        _require(type(row) is dict and set(row) == {"lower", "upper"},
                 "closed_integer_interval_required")
        lower, upper = row["lower"], row["upper"]
        _require(type(lower) is int and type(upper) is int,
                 "integer_interval_excludes_Boolean_or_coerced_bounds")
        _require(-MAX_ABS_INPUT <= lower <= upper <= MAX_ABS_INPUT,
                 "nonempty_bounded_integer_interval_required")
        size *= upper - lower + 1
        _require(size <= MAX_INPUT_CASES, "finite_source_input_product_exceeds_64")
        result[name] = dict(lower=lower, upper=upper)
    return result, size


def _no_external_effects(effect):
    _require(type(effect) is dict and set(effect) == {"reads", "writes", *binding.EFFECT_OTHER_FIELDS},
             "closed_source_program_effect_summary_required")
    _require(all(not effect[key] for key in binding.EFFECT_OTHER_FIELDS),
             "source_program_external_effect_not_supported")


def _evaluate_program(payload, parameters):
    """Evaluate only native typed symbols/binaries, fresh assignment and return.

    Missing locals/result slots are deliberately not defaulted. This helper is
    internal; public derivation first obtains an exact v2 qualification report.
    """
    native = program_types.ProgramIR.from_dict(payload)
    _require(_raw(native.to_dict()) == _raw(payload), "exact_source_program_roundtrip_required")
    _require(len(payload["functions"]) == 1 and not payload["global_symbol_ids"],
             "one_closed_scalar_source_function_required")
    function = payload["functions"][0]
    _no_external_effects(function["effects"])
    cfg = function["cfg"]
    _require(len(cfg["blocks"]) == 1 and not cfg["edges"] and not cfg["exceptional_exit_block_ids"],
             "straight_line_source_program_required")
    block = cfg["blocks"][0]
    _require(cfg["entry_block_id"] == block["block_id"] and cfg["normal_exit_block_ids"] == [block["block_id"]],
             "one_normal_source_exit_required")
    symbols = {row["symbol_id"]: row for row in payload["symbols"]}
    expressions = {row["expression_id"]: row for row in payload["expressions"]}
    commands = {row["command_id"]: row for row in payload["commands"]}
    parameter_ids = function["parameter_symbol_ids"]
    _require(not function["declared_exceptions"] and not function["exception_symbol_ids"]
             and len(function["local_symbol_ids"]) <= 1
             and all(row["type_ref"] in {"integer", "boolean"} and not row["attributes"] for row in symbols.values()),
             "closed_typed_scalar_source_scope_required")
    _require(len(parameter_ids) == 2 and set(parameters) == {symbols[key]["name"] for key in parameter_ids},
             "exact_scalar_parameter_values_required")
    store = {}
    for key in parameter_ids:
        row = symbols[key]; value = parameters[row["name"]]
        _require(row["kind"] == "parameter" and row["type_ref"] == "integer" and type(value) is int,
                 "source_parameter_requires_exact_integer")
        store[key] = value
    initial = deepcopy(store)
    _require(set(commands) == set(block["command_ids"]) and 1 <= len(commands) <= 2,
             "all_source_commands_must_be_accounted")
    seen, active, total_reads, total_writes = set(), set(), set(), set()
    operators = {"add": lambda a, b: a + b, "sub": lambda a, b: a - b, "mul": lambda a, b: a * b,
        "lt": lambda a, b: a < b, "le": lambda a, b: a <= b, "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b, "eq": lambda a, b: a == b, "ne": lambda a, b: a != b}

    def evaluate(key, depth=0):
        _require(key in expressions and key not in active and depth <= 8,
                 "bounded_acyclic_source_expression_required")
        row = expressions[key]
        _require(not row["attributes"] and row["evaluation_order"] == row["operand_ids"],
                 "closed_ordered_source_expression_required")
        active.add(key); seen.add(key)
        if row["kind"] == "symbol":
            _require(not row["operand_ids"] and not row["operator"] and len(row["symbol_ids"]) == 1,
                     "plain_source_symbol_expression_required")
            symbol, = row["symbol_ids"]
            _require(symbol in store, "source_symbol_not_initialized")
            value, reads = store[symbol], {symbol}
        else:
            _require(row["kind"] == "binary" and row["operator"] in operators
                     and len(row["operand_ids"]) == 2 and not row["symbol_ids"],
                     "supported_scalar_source_binary_required")
            (left, left_reads), (right, right_reads) = [evaluate(child, depth + 1) for child in row["operand_ids"]]
            _require(type(left) is int and type(right) is int, "source_binary_requires_exact_integer_operands")
            value = operators[row["operator"]](left, right)
            reads = left_reads | right_reads
        _require(row["type_ref"] in {"integer", "boolean"}
                 and type(value) is (int if row["type_ref"] == "integer" else bool),
                 "source_expression_result_type_differs")
        active.remove(key)
        return value, reads

    returned = None
    for index, key in enumerate(block["command_ids"]):
        command = commands[key]
        _no_external_effects(command["effects"])
        _require(len(command["expression_ids"]) == 1 and command["evaluation_order"] == command["expression_ids"]
                 and not command["attributes"] and not command["undefined_behavior"],
                 "closed_scalar_source_command_required")
        value, reads = evaluate(command["expression_ids"][0])
        if command["kind"] == "assign":
            _require(index == 0 and len(commands) == 2 and len(command["target_symbol_ids"]) == 1,
                     "single_fresh_source_assignment_required")
            target, = command["target_symbol_ids"]
            _require(target in function["local_symbol_ids"] and target not in store
                     and symbols[target]["kind"] == "local"
                     and type(value) is (int if symbols[target]["type_ref"] == "integer" else bool),
                     "fresh_typed_source_local_required")
            store[target] = value; writes = {target}
        else:
            _require(command["kind"] == "return" and index == len(commands) - 1 and not command["target_symbol_ids"]
                     and function["return_type"] in {"integer", "boolean"}
                     and type(value) is (int if function["return_type"] == "integer" else bool),
                     "terminal_typed_source_return_required")
            returned = value; writes = set()
        _require(set(command["effects"]["reads"]) == reads and set(command["effects"]["writes"]) == writes,
                 "exact_source_command_effects_required")
        total_reads.update(reads); total_writes.update(writes)
    _require(returned is not None and seen == set(expressions), "complete_source_expression_and_return_required")
    _require(set(function["effects"]["reads"]) == total_reads and set(function["effects"]["writes"]) == total_writes,
             "exact_source_function_effects_required")
    return initial, store, returned


def derive_source_state_model(source_text, candidate, input_domains):
    """Derive all return cases of an unchanged, exactly qualified scalar candidate."""
    qualification = binding.qualify_source_candidate(source_text, candidate)
    _require(qualification["status"] == "qualified",
        "source_candidate_" + qualification["status"] + ":" + str(qualification.get("reason")))
    source_program = qualification["projections"][0]["native_document"]
    function = source_program["functions"][0]
    symbols = {row["symbol_id"]: row for row in source_program["symbols"]}
    names = [symbols[key]["name"] for key in function["parameter_symbol_ids"]]
    domains, case_count = _domains(input_domains, names)
    parameter_symbols = {symbols[key]["name"]: key for key in function["parameter_symbol_ids"]}
    parameter_variables = {name: "state:input:" + str(index) for index, name in enumerate(names)}
    result_type = function["return_type"]
    default = 0 if result_type == "integer" else False
    source_refs = (source_program["sources"][0]["ref_id"],)
    cases = []
    for index, values in enumerate(product(*(range(domains[name]["lower"], domains[name]["upper"] + 1) for name in names))):
        parameters = dict(zip(names, values))
        initial_symbols, final_symbols, result = _evaluate_program(source_program, parameters)
        initial = {parameter_variables[name]: parameters[name] for name in names}
        initial.update({RESULT_VARIABLE: default, RETURNED_VARIABLE: False})
        final = dict(initial, **{RESULT_VARIABLE: result, RETURNED_VARIABLE: True})
        suffix = f"{index:03d}"
        cases.append(dict(index=index, parameter_values=parameters, initial_symbols=initial_symbols,
            final_symbols=final_symbols, result=result, initial_state=initial, final_state=final,
            action_id="source:return:" + suffix, guard_predicate_id="source:guard:" + suffix,
            next_predicate_id="source:next:" + suffix))
    _require(len(cases) == case_count, "all_source_input_combinations_required")
    variables = [state_types.StateVariable(parameter_variables[name], "input_" + str(index), "integer", "finite",
        state_types.FiniteDomainBound("bound:input:" + str(index), **domains[name]), source_ref_ids=source_refs)
        for index, name in enumerate(names)]
    result_values = [default, *(case["result"] for case in cases)]
    result_bound = (state_types.FiniteDomainBound("bound:result", lower=min(result_values), upper=max(result_values))
        if result_type == "integer" else state_types.FiniteDomainBound("bound:result", cardinality=2))
    variables.extend([state_types.StateVariable(RESULT_VARIABLE, "result", result_type, "finite", result_bound,
        source_ref_ids=source_refs), state_types.StateVariable(RETURNED_VARIABLE, "returned", "boolean", "finite",
        state_types.FiniteDomainBound("bound:returned", cardinality=2), source_ref_ids=source_refs)])
    schema = state_types.StateSchema(tuple(variables))
    predicates = [state_types.StatePredicate("source:initial", "initial", "Pending source return observation.",
        expression={RESULT_VARIABLE: default, RETURNED_VARIABLE: False},
        subject_variable_ids=(RESULT_VARIABLE, RETURNED_VARIABLE), source_ref_ids=source_refs)]
    actions = []
    for case in cases:
        for phase, role, key in (("initial_state", "guard", "guard_predicate_id"), ("final_state", "next", "next_predicate_id")):
            state_types.StateValuation("valuation:" + role + ":" + str(case["index"]), case[phase]).validate_against(schema)
            predicates.append(state_types.StatePredicate(case[key], role,
                "Exact " + role + " return observation for input case " + str(case["index"]) + ".",
                expression=case[phase], subject_variable_ids=tuple(case[phase]), source_ref_ids=source_refs))
        actions.append(transitions.Action(case["action_id"], "Return input case " + str(case["index"]),
            transitions.ActionFrame(reads=tuple(case["initial_state"]), writes=(RESULT_VARIABLE, RETURNED_VARIABLE)),
            guard_predicate_id=case["guard_predicate_id"], next_predicate_id=case["next_predicate_id"],
            source_ref_ids=source_refs))
    relation = transitions.TransitionRelation("source:returns", "action", "One complete scalar function return.",
        action_ids=tuple(case["action_id"] for case in cases), allows_stutter=False, source_ref_ids=source_refs)
    model = transitions.StateTransitionIR(schema, tuple(predicates), tuple(actions), (relation,)).to_dict()
    report = dict(schema=SCHEMA, status="derived", derivation_mode="deterministic_qualified_ProgramIR",
        source_text=source_text, candidate_ir=deepcopy(candidate),
        source_sha256=qualification["source_sha256"], candidate_sha256=qualification["candidate_sha256"],
        input_domains=domains, input_domains_sha256=_digest(domains),
        source_qualification=deepcopy(qualification), source_program=deepcopy(source_program),
        source_program_sha256=_digest(source_program), state_model=model, state_model_sha256=_digest(model),
        parameter_order=names, parameter_symbols=parameter_symbols, parameter_variables=parameter_variables,
        result_variable_id=RESULT_VARIABLE, returned_variable_id=RETURNED_VARIABLE,
        result_type=result_type, initial_result_observation=default, case_count=case_count, cases=cases,
        all_input_combinations_enumerated=True, terminal_returns_have_no_outgoing_actions=True,
        provider_calls=0, solver_calls=0,
        assumptions=[*qualification["assumptions"],
            "Input intervals are explicit caller bounds, not inferred properties of callers or source software.",
            "All bounded parameter combinations are interpreted using the exact qualified scalar ProgramIR; no Python source executes.",
            "One state action represents a complete function call; local command interleavings are not represented.",
            "The result observation is a storage sentinel while returned is false; it is not an initialized source local or source result slot.",
            "Only parameters exist in the initial symbolic store. Fresh locals are added after their assignments, and returned values are separate observations.",
            "World-state access frames describe observation bookkeeping; exact source read/write effects remain separately preserved in ProgramIR.",
            "Integer result bounds cover the sentinel and every computed return. Unreachable intermediate integer values in that interval add no return transitions.",
            "Returned states are terminal with no inferred fairness, stutter, environment action or liveness theorem.",
            "A source-derived table is not a learned prediction, a source-equivalence proof, a security contract or training qualification."], **FALSE)
    report["report_sha256"] = _digest(report)
    return report


def verify_source_state_model(report, source_text, candidate, input_domains):
    """Reparse exact source, recheck the unchanged candidate and replay every case."""
    _require(type(report) is dict, "source_state_report_required")
    expected = derive_source_state_model(source_text, candidate, input_domains)
    _require(_raw(report) == _raw(expected), "source_state_model_differs_from_exact_replay")
    return expected


__all__ = ["SCHEMA", "PRODUCERS", "FALSE", "SourceStateModelError", "derive_source_state_model",
           "verify_source_state_model", "MAX_INPUT_CASES", "MAX_ABS_INPUT"]
