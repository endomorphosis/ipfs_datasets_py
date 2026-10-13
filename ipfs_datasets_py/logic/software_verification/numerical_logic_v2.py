"""Source-replayed guarded numerical structure and unresolved logic goals.

Python evaluation contexts are symbolic obligations, never facts asserted about
an execution. The eager ProgramIR alone is deliberately incomplete; its guarded
sidecar and exact source must accompany every projection. No source, model or
solver is executed. The historical v1 producer and scalar checkpoint pins are
unchanged.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib

from . import numerical_logic as base
from . import numerical_source_v2 as frontend
from ..syntax_core.ast import TypedExpression, mk_constant, mk_predicate, mk_implies
from ..syntax_core.signatures import atomic_sort, many_sorted_fol_signature
from ..backends.smt.compiler import SoftwareVerificationSMTCompiler, SmtTerm, term_int, term_symbol
from .syntax_bridge import SoftwareVerificationSyntaxBridge

PROFILE = "python-numerical-guarded-structure@2"
SCHEMA = "numerical-source-logic/v2"
ASSERTION_SCHEMA = "numerical-guarded-assertion-requirement@1"
MAX_OBLIGATIONS = base.MAX_OBLIGATIONS
MAX_REPORT_BYTES = base.MAX_REPORT_BYTES
NumericalLogicError = base.NumericalLogicError
_FALSE = base._FALSE
_raw, _sha = base._raw, base._sha


def describe_numerical_logic_profile():
    profile = base.describe_numerical_logic_profile()
    profile.update(profile=PROFILE, schema=SCHEMA, guarded_extension_required=True,
                   standalone_program_evaluation_complete=False)
    profile["routes"][0]["status"] = "structural_only_requires_guarded_extension"
    profile["routes"][1]["status"] = "pending_guarded_predicates"
    profile["routes"][2]["status"] = "pending_guarded_abstract_integer_constraints"
    return profile


def _contexts(program, regions):
    """May-evaluation contexts; no truth value or successful effect is supplied."""
    expressions = {row.expression_id: row for row in program.expressions}
    commands = {row.command_id: row for row in program.commands}
    conditionals = {row["root_expression_id"]: row for row in regions if row["kind"] == "if_expression"}
    assertions = {row["command_id"]: row for row in regions if row["kind"] == "assert_statement"}
    contexts = {}

    def walk(key, function, command, guards, region_ids, active=()):
        if key in active:
            raise NumericalLogicError("cyclic guarded expression dependency")
        context = dict(function_id=function, command_id=command,
                       guard_conditions=guards, guarded_region_ids=region_ids)
        if context not in contexts.setdefault(key, []):
            contexts[key].append(context)
        expression = expressions[key]
        conditional = conditionals.get(key)
        if conditional is not None:
            refs = region_ids + [conditional["region_id"]]
            test = conditional["test_expression_id"]
            walk(test, function, command, guards, refs, active + (key,))
            for branch, truth in (("then_expression_id", True), ("else_expression_id", False)):
                selected = guards + [dict(kind="normal_completion", expression_id=test),
                    dict(kind="truthiness_result", expression_id=test, value=truth)]
                walk(conditional[branch], function, command, selected, refs, active + (key,))
            return
        prior = []
        for operand in expression.evaluation_order:
            walk(operand, function, command, guards + prior, region_ids, active + (key,))
            prior = prior + [dict(kind="normal_completion", expression_id=operand)]

    for function in program.functions:
        for block in function.cfg.blocks:
            for cid in block.command_ids:
                command = commands[cid]
                reached = [dict(kind="command_reached", command_id=cid)]
                assertion = assertions.get(cid)
                if assertion is not None:
                    refs = [assertion["region_id"]]
                    enabled = reached + [dict(kind="assertions_enabled")]
                    predicate = assertion["predicate_expression_id"]
                    walk(predicate, function.function_id, cid, enabled, refs)
                    if assertion["message_expression_id"] is not None:
                        walk(assertion["message_expression_id"], function.function_id, cid,
                             enabled + [dict(kind="normal_completion", expression_id=predicate),
                                        dict(kind="truthiness_result", expression_id=predicate, value=False)], refs)
                else:
                    prior = []
                    for key in command.evaluation_order:
                        walk(key, function.function_id, cid, reached + prior, [])
                        prior = prior + [dict(kind="normal_completion", expression_id=key)]
    return contexts


def _guarded(row, contexts, source_sha256):
    row = deepcopy(row)
    row.pop("obligation_id", None)
    values = contexts.get(row["expression_id"], [])
    row.update(source_sha256=source_sha256, evaluation_contexts=deepcopy(values),
        guarded_region_ids=sorted({ref for value in values for ref in value["guarded_region_ids"]}),
        function_ids=sorted({value["function_id"] for value in values}),
        evaluation_guard_interpretation="disjunction of listed entry contexts; no condition or normal completion is established",
        evaluation_guard_verified=False, runtime_truthiness_verified=False,
        runtime_effects_verified=False, standalone_program_evaluation_complete=False)
    row["obligation_id"] = "numerical-guarded:" + _sha(row)[:32]
    return row


def _evaluation_obligations(program, regions):
    expressions = {row.expression_id: row for row in program.expressions}
    rows = []

    def add(kind, key, reason, roles):
        expression = expressions[key]
        rows.append(dict(kind=kind, expression_id=key,
            source_ref_ids=list(expression.source_ref_ids), span_ids=list(expression.span_ids),
            roles=roles, status="pending", reason=reason, assumptions_asserted=False,
            source_binding_is_semantic_proof=False, **_FALSE))

    for region in regions:
        if region["kind"] == "if_expression":
            add("conditional_evaluation_semantics", region["root_expression_id"],
                "Resolve test evaluation and Python truthiness, including exceptions; evaluate exactly one selected branch once.",
                dict(guarded_region_id=region["region_id"], evaluation_policy=region["evaluation_policy"]))
        elif region["kind"] == "assert_statement":
            add("assertion_evaluation_semantics", region["predicate_expression_id"],
                "Resolve assertion enablement and reachability; a truthiness exception skips the message, and a message exception propagates instead of AssertionError.",
                dict(guarded_region_id=region["region_id"], message_expression_id=region["message_expression_id"],
                     evaluation_policy=region["evaluation_policy"]))
    for expression in program.expressions:
        attrs = expression.attributes.to_dict()
        if attrs.get("call_kind") == "python.format_value":
            add("formatting_evaluation_semantics", expression.expression_id,
                "Resolve value then nested format specification, then conversion, then __format__; each phase can have effects or raise and prevent later evaluation.",
                dict(conversion=attrs["conversion"], evaluation_policy=attrs["evaluation_policy"],
                     runtime_conversion_identity_verified=False, runtime_format_identity_verified=False))
        elif attrs.get("call_kind") == "python.joined_string":
            add("joined_string_evaluation_semantics", expression.expression_id,
                "Evaluate and format components from left to right; a raised exception prevents every later component.",
                dict(component_expression_ids=list(expression.operand_ids)))
    return rows


def _assertions(program, regions, coverage, contexts, source_sha256):
    expressions = {row.expression_id: row for row in program.expressions}
    commands = {row.command_id: row for row in program.commands}
    complete = {row["function_id"]: row["structurally_complete"] for row in coverage}
    requirements, obligations = [], []
    for region in regions:
        if region["kind"] != "assert_statement" or not complete[region["function_id"]]:
            continue
        key, cid = region["predicate_expression_id"], region["command_id"]
        command = commands[cid]
        row = dict(schema=ASSERTION_SCHEMA, kind="source_assertion_predicate", status="pending",
            origin="source_assertion", function_id=region["function_id"], command_id=cid,
            predicate_expression_id=key, source_sha256=source_sha256,
            source_ref_ids=list(command.source_ref_ids), span_ids=list(command.span_ids),
            predicate=base._assertion_predicate(expressions[key], expressions),
            evaluation_contexts=deepcopy(contexts[key]), guarded_region_ids=[region["region_id"]],
            unknown_effects=True, runtime_identity_verified=False, runtime_truthiness_verified=False,
            evaluation_guard_verified=False, runtime_effects_verified=False,
            standalone_program_evaluation_complete=False,
            function_postcondition_inferred=False, assertion_execution_verified=False,
            lexical_reaching_definitions_inferred=False,
            scope="predicate at this source statement if reached with assertions enabled; no execution, truth or callee postcondition inferred",
            failure_message_structure_lowered=region.get("message_status") != "unsupported",
            comparison_policy="explicit_source_arguments_only_no_library_defaults_assumed",
            assumptions_asserted=False, source_obligations_discharged=0, **_FALSE)
        row["requirement_id"] = "assertion-requirement:" + _sha(row)[:32]
        obligation = _guarded(dict(kind="source_assertion_predicate", expression_id=key,
            source_ref_ids=row["source_ref_ids"], span_ids=row["span_ids"], status="pending",
            roles=dict(requirement_id=row["requirement_id"], command_id=cid,
                       predicate_operator=row["predicate"]["operator"]),
            reason="Interpret guarded predicate evaluation, truthiness, effects and reachability; syntax establishes neither execution nor truth.",
            assumptions_asserted=False, source_binding_is_semantic_proof=False, **_FALSE), contexts, source_sha256)
        row["obligation_id"] = obligation["obligation_id"]
        requirements.append(row)
        obligations.append(obligation)
    assessments = [dict(function_id=row["function_id"],
                        status="guarded_predicate_scan_only" if row["structurally_complete"] else "not_scanned",
                        reason=None if row["structurally_complete"] else "unsupported_function") for row in coverage]
    return requirements, obligations, assessments


def _binding(row):
    return dict(evaluation_contexts=deepcopy(row["evaluation_contexts"]),
                guarded_region_ids=list(row["guarded_region_ids"]), evaluation_guard_verified=False,
                evaluation_guard_interpretation=row["evaluation_guard_interpretation"])


def _compounds(program, regions, coverage, contexts, source_sha256):
    blocked = {row["function_id"] for row in regions}
    for expression in program.expressions:
        if expression.attributes.get("call_kind") in {"python.format_value", "python.joined_string"}:
            blocked.update(row["function_id"] for row in contexts.get(expression.expression_id, []))
    admitted = [dict(row, structurally_complete=row["structurally_complete"] and row["function_id"] not in blocked)
                for row in coverage]
    contracts, obligations, assessments = base._compound_contracts(program, admitted, source_sha256)
    replacements = {}
    for contract in contracts:
        old = contract.pop("contract_id")
        contract.pop("obligation_ids")
        contract.update(evaluation_contexts=deepcopy(contexts[contract["roles"]["return_expression"]]),
                        guarded_region_ids=[], evaluation_guard_verified=False,
                        matcher_scope="complete_function_without_guarded_or_format_constructs")
        contract["contract_id"] = "numerical-guarded-contract:" + _sha(contract)[:32]
        replacements[old] = contract["contract_id"]
    converted = []
    for row in obligations:
        row["roles"]["compound_contract_id"] = replacements[row["roles"]["compound_contract_id"]]
        converted.append(_guarded(row, contexts, source_sha256))
    for contract in contracts:
        contract["obligation_ids"] = [row["obligation_id"] for row in converted
            if row["roles"]["compound_contract_id"] == contract["contract_id"]]
    for assessment in assessments:
        if assessment["function_id"] in blocked:
            assessment.update(status="not_derived", reason="guarded_or_format_function_requires_reviewed_compound_matcher")
    return contracts, converted, assessments


def _fol(row):
    sort = atomic_sort("SourceExpression")
    signature = many_sorted_fol_signature("sig:" + row["obligation_id"], sorts=(sort,),
        constants=(("source_expression", sort),),
        predicates=(("evaluation_context", (sort,)), (row["kind"], (sort,))))
    guard = mk_predicate("node:guard", "evaluation_context",
                         (mk_constant("node:guard-source", "source_expression", sort),))
    requirement = mk_predicate("node:requirement", row["kind"],
                               (mk_constant("node:source", "source_expression", sort),))
    expression = TypedExpression("fol:" + row["obligation_id"],
        mk_implies("node:guarded-requirement", guard, requirement), signature,
        metadata=dict(source_expression_id=row["expression_id"], obligation_id=row["obligation_id"],
                      status="pending", **_binding(row)))
    return dict(obligation_id=row["obligation_id"], expression=expression.to_dict(),
                predicate_interpretation="unresolved guarded implication; no axiom asserted",
                **_binding(row), **_FALSE)


def _smt(row):
    if row["kind"] == "index_safety":
        extent, index = term_symbol("extent"), term_symbol("index")
        goal = SmtTerm("and", arguments=(SmtTerm("ge", arguments=(extent, term_int(0))),
            SmtTerm("and", arguments=(SmtTerm("le", arguments=(SmtTerm("neg", arguments=(extent,)), index)),
                                      SmtTerm("lt", arguments=(index, extent))))))
        symbols = ("extent", "index")
        prerequisites = ["actual builtin integer scalar index", "concrete axis extent and reviewed receiver semantics"]
    elif row["kind"] == "matrix_shape":
        rows, columns = term_symbol("rows"), term_symbol("columns")
        goal = SmtTerm("and", arguments=(SmtTerm("ge", arguments=(rows, term_int(0))),
            SmtTerm("and", arguments=(SmtTerm("ge", arguments=(columns, term_int(0))),
                                      SmtTerm("eq", arguments=(rows, columns))))))
        symbols = ("rows", "columns")
        prerequisites = ["actual ndarray rank and trailing axes", "reviewed dtype and batch semantics"]
    else:
        return None
    guard = SmtTerm("eq", arguments=(term_symbol("evaluation_context"), term_int(1)))
    guarded = SmtTerm("implies", arguments=(guard, goal))
    compilation = SoftwareVerificationSMTCompiler().compile_arithmetic_goal(
        obligation_id=row["obligation_id"], goal=guarded, symbols=("evaluation_context", *symbols),
        assumptions=(), request_unsat_core=False)
    return dict(obligation_id=row["obligation_id"], status="pending",
        interpretation_prerequisites=["bind abstract evaluation_context = 1 to the complete source entry guards without assuming them", *prerequisites],
        compilation=compilation.to_dict(), solver_executed=False, discharged=False,
        **_binding(row), **_FALSE)


def _lean(rows):
    # Reuse the existing mathematical definitions and conditional arithmetic
    # lemmas, but never create its unguarded per-source aliases for v2 rows.
    prepared = base._lean([])
    source = prepared["source"].removesuffix("end NumericalObligations\n")
    if any(row["kind"] in base._COMPOUND_REASONS for row in rows):
        source += base._LEAN_COMPOUND
        prepared["conditional_lemmas"].append("selected_column_contract")
    source += "\n-- Both propositions are unresolved interpretation parameters.\n"
    source += "def GuardedRequirement (evaluationContext requirement : Prop) : Prop := evaluationContext → requirement\n"
    bindings = []
    for row in rows:
        name = "guarded_source_obligation_" + row["obligation_id"].split(":")[1]
        source += f"def {name} := @GuardedRequirement\n"
        bindings.append(dict(obligation_id=row["obligation_id"], declaration=name,
            definition="GuardedRequirement", source_expression_id=row["expression_id"],
            requirement_kind=row["kind"],
            interpretation="pending guard and requirement parameters; no source-value or execution witness",
            **_binding(row)))
    source += "end NumericalObligations\n"
    prepared.update(source=source, source_sha256=hashlib.sha256(source.encode()).hexdigest(), bindings=bindings)
    return prepared


def formalize_numerical_source(source_text, *, path="source.py"):
    structural = frontend.adapt_numerical_source(source_text, path=path)
    wire, program = structural.to_dict(), structural.program
    regions = wire["guarded_regions"]
    contexts = _contexts(program, regions) if program is not None else {}
    obligations = ([_guarded(row, contexts, wire["source_sha256"]) for row in
        base._derive_obligations(program) + _evaluation_obligations(program, regions)] if program is not None else [])
    assertions, assertion_obligations, assessments = (_assertions(program, regions,
        wire["function_coverage"], contexts, wire["source_sha256"]) if program is not None else ([], [], []))
    obligations.extend(assertion_obligations)
    compounds, compound_obligations, compound_assessments = (_compounds(program, regions,
        wire["function_coverage"], contexts, wire["source_sha256"]) if program is not None else ([], [], []))
    obligations.extend(compound_obligations)
    if len(obligations) > MAX_OBLIGATIONS:
        raise NumericalLogicError("numerical obligation count exceeds bound")
    native = None
    if program is not None:
        bridge = SoftwareVerificationSyntaxBridge().round_trip(program)
        if not bridge.exact:
            raise NumericalLogicError("native guarded numerical ProgramIR round trip differs")
        native = dict(family="program", encoding="ProgramIR", status="structural_only_requires_guarded_extension",
            bridge=bridge.to_dict(), guarded_regions=deepcopy(regions),
            guarded_extension_required=True, standalone_program_evaluation_complete=False, **_FALSE)
    projections = dict(program=native, first_order=[_fol(row) for row in obligations],
        smt=[value for row in obligations if (value := _smt(row)) is not None],
        lean=_lean(obligations) if obligations else None)
    counts = Counter(fid for row in obligations for fid in row["function_ids"])
    functions = [dict(function_id=row["function_id"],
        qualified_name=row["name"].encode("utf-8")[:128].decode("utf-8", errors="ignore"),
        name_truncated=len(row["name"].encode("utf-8")) > 128,
        status="structurally_complete" if row["structurally_complete"] else "partial",
        structurally_complete=row["structurally_complete"],
        unsupported_construct_count=len(row["unsupported_constructs"]),
        pending_obligation_count=counts[row["function_id"]]) for row in wire["function_coverage"]]
    report = dict(schema=SCHEMA, profile=PROFILE, source_sha256=wire["source_sha256"], path=path,
        structural=wire, pending_obligations=obligations, projections=projections,
        compound_contracts=compounds, compound_contract_assessments=compound_assessments,
        assertion_requirements=assertions, assertion_requirement_assessments=assessments,
        unsupported_families=describe_numerical_logic_profile()["unsupported_families"],
        guarded_extension_required=True, standalone_program_evaluation_complete=False,
        coverage=dict(structural_status=wire["status"], function_coverage=wire["function_coverage"],
                      pending_obligation_count=len(obligations), source_obligations_discharged=0),
        solver_calls=0, provider_calls=0, training_performed=False, **_FALSE)
    complete = sum(row["structurally_complete"] for row in functions)
    report["summary"] = dict(schema=SCHEMA, profile=PROFILE, source_sha256=wire["source_sha256"],
        functions=len(functions), structurally_complete_functions=complete,
        partial_or_unsupported_functions=len(functions) - complete,
        structural_status=wire["status"], pending_obligation_count=len(obligations),
        families_with_artifacts=[family for family, present in
            (("program", native), ("first_order", projections["first_order"]), ("higher_order", projections["lean"])) if present],
        per_function=functions[:16], omitted_function_summaries=max(0, len(functions)-16),
        guarded_region_count=len(regions), guarded_extension_required=True,
        standalone_program_evaluation_complete=False, **_FALSE)
    report["summary"].update(base._compound_summary(compounds))
    for row in report["summary"]["compound_contracts"]:
        row.update(guarded_region_ids=[], evaluation_guard_verified=False,
                   full_evaluation_contexts_in_native_report=True)
    summaries = [{key: row[key] for key in ("requirement_id", "function_id", "command_id",
        "predicate_expression_id", "source_ref_ids", "span_ids", "origin", "status", "predicate",
        "unknown_effects", "proof_authority", "source_obligations_discharged", "guarded_region_ids")}
        | dict(evaluation_guard_verified=False, full_evaluation_contexts_in_native_report=True)
        for row in assertions[:base.MAX_ASSERTION_SUMMARIES]]
    while len(_raw(summaries)) > base.MAX_ASSERTION_SUMMARY_BYTES:
        summaries.pop()
    report["summary"].update(assertion_requirements=summaries, assertion_requirement_count=len(assertions),
        omitted_assertion_requirement_summaries=len(assertions) - len(summaries))
    report["report_sha256"] = _sha(report)
    return report


def validate_numerical_logic_report(report, source_text, *, path="source.py"):
    if type(report) is not dict:
        raise NumericalLogicError("native guarded numerical logic report required")
    _raw(report)
    expected = formalize_numerical_source(source_text, path=path)
    if _raw(report) != _raw(expected):
        raise NumericalLogicError("guarded numerical source, evaluation context or projection differs")
    return expected


__all__ = ["PROFILE", "SCHEMA", "NumericalLogicError", "describe_numerical_logic_profile",
           "formalize_numerical_source", "validate_numerical_logic_report"]
