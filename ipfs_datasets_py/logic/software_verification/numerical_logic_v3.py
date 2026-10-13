"""Source-bound CFG/loop occurrences and pending numerical obligations.

An iteration label denotes a symbolic visit within an activation, never a
concrete iteration count, unrolling or termination witness. Existing guarded
FOL/SMT/Lean owners retain the full occurrence sidecar. No operational state
interpretation is invented for temporal, transition-system or TLA+ families.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace

from . import numerical_logic as base
from . import numerical_logic_v2 as guarded
from . import numerical_source_v3 as frontend
from .program import BasicBlock, ControlFlowGraph
from .syntax_bridge import SoftwareVerificationSyntaxBridge
from ..syntax_core.ast import TypedExpression

PROFILE = "python-numerical-control-structure@3"
SCHEMA = "numerical-source-logic/v3"
MAX_OBLIGATIONS = base.MAX_OBLIGATIONS
MAX_REPORT_BYTES = base.MAX_REPORT_BYTES
NumericalLogicError = base.NumericalLogicError
_raw, _sha, _FALSE = base._raw, base._sha, base._FALSE
_CONTROL_FALSE = dict(reachability_verified=False, loop_invariants_verified=False,
                      termination_verified=False, control_flow_semantics_verified=False)
_OCCURRENCE_KEYS = ("function_id", "cfg_id", "block_id", "command_id", "occurrence", "reachability_verified")


def describe_numerical_logic_profile():
    result = guarded.describe_numerical_logic_profile()
    result.update(profile=PROFILE, schema=SCHEMA, control_extension_required=True,
                  iteration_interpretation="symbolic activation/iteration scopes, not a concrete execution or loop bound",
                  **_CONTROL_FALSE)
    return result


def _contexts(program, regions, command_contexts, source_sha256):
    result = guarded._contexts(program, regions)
    locations = {row["command_id"]: row for row in command_contexts}
    if len(locations) != len(command_contexts) or set(locations) != {c.command_id for c in program.commands}:
        raise NumericalLogicError("exact per-command control occurrence inventory required")
    for entries in result.values():
        for entry in entries:
            location = locations[entry["command_id"]]
            if entry["function_id"] != location["function_id"]:
                raise NumericalLogicError("guarded context crosses control occurrence owner")
            entry.update(deepcopy(location), source_sha256=source_sha256)
            entry["guard_conditions"] = [dict(kind="cfg_block_visit",
                cfg_id=location["cfg_id"], block_id=location["block_id"], command_id=location["command_id"],
                occurrence=location["occurrence"])] + entry["guard_conditions"]
            entry["occurrence_interpretation"] = "symbolic visit under the enclosing activation/iteration scopes; reachability and visit count unresolved"
    return result


def _control_binding(row):
    return {key: deepcopy(row[key]) for key in
            ("control_region_ids", "loop_region_ids", "cfg_occurrences", *_CONTROL_FALSE,
             "proof_scope", "evaluation_context_role", "logical_guard_scope") if key in row}


def _controlled(row, contexts, source_sha256):
    value = guarded._guarded(row, contexts, source_sha256)
    value.pop("obligation_id")
    occurrences = []
    for context in value["evaluation_contexts"]:
        occurrence = {key: context[key] for key in _OCCURRENCE_KEYS}
        if occurrence not in occurrences:
            occurrences.append(occurrence)
    value.update(control_region_ids=sorted({rid for c in value["evaluation_contexts"]
                                            for rid in c["enclosing_region_ids"]}),
                 loop_region_ids=sorted({loop["region_id"] for c in value["evaluation_contexts"]
                                         for loop in c["loop_contexts"]}),
                 cfg_occurrences=occurrences,
                 evaluation_guard_interpretation="disjunction of symbolic CFG visits under activation/iteration scopes and expression guards; no reachability, visit count or successful effect established",
                 **_CONTROL_FALSE)
    if "proof_scope" in value:
        value.update(evaluation_context_role="source_anchor_only",
            logical_guard_scope="unresolved_proof_scope_applicability",
            evaluation_guard_interpretation="the logical guard denotes unresolved applicability of the complete proof_scope; evaluation_contexts and cfg_occurrences are source anchors only, not the proof phase or an established header visit")
    value["obligation_id"] = "numerical-control:" + _sha(value)[:32]
    return value


def _proof_scope(program, region, phase, regions, command_contexts):
    cfg = next(f.cfg for f in program.functions if f.function_id == region["function_id"])
    # Lexical ownership, not reachability: an inner loop's else can transfer
    # directly to an outer loop without making that outer loop part of its scope.
    inside = {c["block_id"] for c in command_contexts
              if region["region_id"] in c["enclosing_region_ids"]}
    for nested in regions:
        if nested["region_id"] == region["region_id"] or region["region_id"] in nested["enclosing_region_ids"]:
            inside.update(nested.get(key) for key in ("entry_block_id", "header_block_id",
                "body_entry_block_id", "else_entry_block_id", "target_block_id"))
            if nested["region_id"] != region["region_id"]:
                inside.add(nested["continuation_block_id"])
    inside.discard(None)
    entry_edges = [e.edge_id for e in cfg.edges
                   if e.target_block_id == region["entry_block_id"] and e.source_block_id not in inside]
    exit_edges = [e.edge_id for e in cfg.edges
                  if e.source_block_id in inside and e.target_block_id not in inside]
    backedges = sorted(set(region["backedge_ids"] + region["continue_edge_ids"]))
    gates = ([region["exhaustion_edge_id"]] if region["kind"] == "for_statement" else
             [e.edge_id for e in cfg.edges if e.source_block_id == region["header_block_id"]
              and e.kind.value == "false"])
    relevant = {"activation_entry": entry_edges,
                "normal_or_continue_backedge": backedges,
                "exit_cause_and_post_state": sorted(set(exit_edges + gates)),
                "whole_activation_progress": sorted(set(entry_edges + backedges + exit_edges + gates))}[phase]
    return dict(schema="numerical-loop-proof-scope@1", function_id=region["function_id"],
        cfg_id=cfg.graph_id, control_region_id=region["region_id"], proof_phase=phase,
        entry_block_id=region["entry_block_id"], header_block_id=region["header_block_id"],
        continuation_block_id=region["continuation_block_id"],
        activation_variable=region["activation_variable"], iteration_variable=region["iteration_variable"],
        relevant_edge_ids=relevant, full_region_cfg_interpretation_required=True,
        phase_established=False, applicability_verified=False,
        interpretation="pending proof phase over this activation and its actual CFG entry, backedge or exit boundaries; source anchor evaluation does not establish applicability")


def _control_obligations(program, regions, command_contexts):
    expressions = {row.expression_id: row for row in program.expressions}
    commands = {row.command_id: row for row in program.commands}
    result = []

    def add(region, kind, reason, key=None, proof_scope=None, **roles):
        key = key or region["anchor_expression_id"]
        expression = expressions[key]
        result.append(dict(kind=kind, expression_id=key, source_ref_ids=list(expression.source_ref_ids),
            span_ids=list(expression.span_ids), status="pending", reason=reason,
            roles=dict(control_region_id=region["region_id"], control_kind=region["kind"],
                       edge_ids=list(region["edge_ids"]), **roles),
            assumptions_asserted=False, source_binding_is_semantic_proof=False, **_FALSE))
        if proof_scope is not None:
            result[-1]["proof_scope"] = proof_scope

    for region in regions:
        add(region, "control_flow_semantics",
            "Interpret this source-bound CFG region, edge guards, ordering, normal and abrupt completion; graph connectivity establishes neither reachability nor execution.")
        if region["kind"] == "if_statement":
            add(region, "statement_truthiness_semantics",
                "Resolve test evaluation and Python truthiness, including effects and exceptions, before selecting exactly one suite.")
            continue
        if region["kind"] == "for_statement":
            add(region, "iterator_creation_semantics",
                "Evaluate the iterable and create an iterator once per activation, which may recur inside enclosing loops; resolve __iter__/sequence fallback and exceptions without assuming builtin identity.",
                key=region["iterator_expression_id"], iterable_expression_id=region["iterable_expression_id"])
            add(region, "iterator_advance_semantics",
                "At each advance, a returned item selects target binding; only StopIteration from this advance selects exhaustion. Other exceptions escape, and StopIteration from iterator creation, target or body is not exhaustion.",
                key=region["advance_expression_id"])
            target = commands[region["target_command_id"]]
            add(region, "loop_target_binding_semantics",
                "Bind each yielded item using the source target's assignment rules before the body; assignment may raise. Zero iterations establish no target binding and later rebinding is not a loop value invariant.",
                key=target.expression_ids[0], target_command_id=target.command_id,
                target_symbol_ids=list(target.target_symbol_ids))
        elif region["kind"] == "while_statement":
            add(region, "loop_test_semantics",
                "Reevaluate the test and Python truthiness on every header visit; false, including the first test, selects else; effects or exceptions are not omitted.")
        else:
            raise NumericalLogicError("unrecognized control region kind")
        for kind, reason in (
            ("loop_invariant_initialization", "Supply a source-state invariant and establish it at loop entry; no invariant is inferred or assumed."),
            ("loop_invariant_preservation", "Establish the supplied invariant across each normal or continue backedge with iteration-indexed bindings and effects; a syntax traversal is not an induction proof."),
            ("loop_exit_reasoning", "Relate invariant and actual exit cause to post-loop state; distinguish normal exhaustion/false test, break, return and escaping exception, including zero iterations and else."),
            ("loop_termination", "Supply a well-founded variant or another justified progress argument under the real protocol and effects; no finite bound follows merely from loop syntax or a name such as range."),
        ):
            phase = {"loop_invariant_initialization": "activation_entry",
                     "loop_invariant_preservation": "normal_or_continue_backedge",
                     "loop_exit_reasoning": "exit_cause_and_post_state",
                     "loop_termination": "whole_activation_progress"}[kind]
            anchor = (region["iterator_expression_id"] if kind == "loop_invariant_initialization"
                      and region["kind"] == "for_statement" else region["anchor_expression_id"])
            add(region, kind, reason, key=anchor, proof_phase=phase,
                proof_scope=_proof_scope(program, region, phase, regions, command_contexts),
                activation_variable=region["activation_variable"],
                iteration_variable=region["iteration_variable"],
                backedge_ids=list(region["backedge_ids"]),
                continue_edge_ids=list(region["continue_edge_ids"]),
                break_edge_ids=list(region["break_edge_ids"]),
                phase_established=False)
    return result


def _linear_matcher_view(program, guarded_regions, control_regions, coverage, contexts):
    """Review a unique nonbranching source-order path for the unchanged matcher.

    This temporary view is used only for syntactic matching. The native CFG and
    exception edges remain in the actual report; no runtime equivalence is
    asserted by the view.
    """
    blocked = {row["function_id"] for row in [*guarded_regions, *control_regions]}
    for expression in program.expressions:
        if expression.attributes.get("call_kind") in {"python.format_value", "python.joined_string"}:
            blocked.update(c["function_id"] for c in contexts.get(expression.expression_id, []))
    complete = {row["function_id"] for row in coverage if row["structurally_complete"]}
    replacements, admitted = [], set()
    for function in program.functions:
        cfg = function.cfg
        if function.function_id in blocked or function.function_id not in complete:
            replacements.append(function)
            continue
        blocks = {block.block_id: block for block in cfg.blocks}
        outgoing = {bid: [edge for edge in cfg.edges if edge.source_block_id == bid] for bid in blocks}
        current, visited, commands, valid = cfg.entry_block_id, set(), [], True
        while current not in cfg.normal_exit_block_ids:
            if current in visited or current in cfg.exceptional_exit_block_ids:
                valid = False
                break
            visited.add(current)
            commands.extend(blocks[current].command_ids)
            normal = []
            for edge in outgoing[current]:
                if edge.kind.value == "exception":
                    if edge.exception_type != "BaseException" or edge.target_block_id not in cfg.exceptional_exit_block_ids:
                        valid = False
                elif edge.kind.value in {"normal", "return"} and not edge.condition_expression_id:
                    normal.append(edge)
                else:
                    valid = False
            if not valid or len(normal) != 1:
                valid = False
                break
            current = normal[0].target_block_id
        if valid:
            commands.extend(blocks[current].command_ids)
            visited.add(current)
            valid = (set(blocks) - set(cfg.exceptional_exit_block_ids) == visited
                     and not any(blocks[bid].command_ids for bid in cfg.exceptional_exit_block_ids)
                     and len(commands) == len(set(commands)) == len(cfg.command_ids))
        if not valid:
            replacements.append(function)
            continue
        block = BasicBlock(cfg.entry_block_id, tuple(commands), source_ref_ids=function.source_ref_ids,
                           span_ids=function.span_ids)
        view = ControlFlowGraph(cfg.graph_id, block.block_id, (block,), (), (block.block_id,))
        replacements.append(replace(function, cfg=view))
        admitted.add(function.function_id)
    view = replace(program, program_id="", functions=tuple(replacements))
    filtered = [dict(row, structurally_complete=row["function_id"] in admitted) for row in coverage]
    return view, filtered, admitted


def _compounds(program, regions, controls, coverage, contexts, source_sha256):
    view, filtered, admitted = _linear_matcher_view(program, regions, controls, coverage, contexts)
    contracts, obligations, assessments = base._compound_contracts(view, filtered, source_sha256)
    replacements = {}
    for contract in contracts:
        old = contract.pop("contract_id")
        contract.pop("obligation_ids")
        binding = _controlled(dict(expression_id=contract["roles"]["return_expression"]), contexts, source_sha256)
        contract.update(evaluation_contexts=binding["evaluation_contexts"],
                        **_control_binding(binding), guarded_region_ids=[], evaluation_guard_verified=False,
                        matcher_scope="reviewed_unique_normal_return_path_without_control_guard_or_format_regions")
        contract["contract_id"] = "numerical-control-contract:" + _sha(contract)[:32]
        replacements[old] = contract["contract_id"]
    converted = []
    for row in obligations:
        row["roles"]["compound_contract_id"] = replacements[row["roles"]["compound_contract_id"]]
        converted.append(_controlled(row, contexts, source_sha256))
    for contract in contracts:
        contract["obligation_ids"] = [row["obligation_id"] for row in converted
            if row["roles"]["compound_contract_id"] == contract["contract_id"]]
    for assessment in assessments:
        if assessment["function_id"] not in admitted:
            assessment.update(status="not_derived", reason="not_a_complete_reviewed_straight_line_cfg")
    return contracts, converted, assessments


def _assertions(program, regions, coverage, contexts, source_sha256):
    requirements, obligations, assessments = guarded._assertions(program, regions, coverage, contexts, source_sha256)
    requirement_ids, original_obligations = {}, {}
    for row in requirements:
        old = row.pop("requirement_id")
        original_obligations[old] = row.pop("obligation_id")
        bound = _controlled(dict(expression_id=row["predicate_expression_id"]), contexts, source_sha256)
        row.update(schema="numerical-control-assertion-requirement@1", **_control_binding(bound))
        row["requirement_id"] = "assertion-control-requirement:" + _sha(row)[:32]
        requirement_ids[old] = row["requirement_id"]
    converted, id_map = [], {}
    for row in obligations:
        row["roles"]["requirement_id"] = requirement_ids[row["roles"]["requirement_id"]]
        value = _controlled(row, contexts, source_sha256)
        id_map[row["obligation_id"]] = value["obligation_id"]
        converted.append(value)
    by_id = {row["requirement_id"]: row for row in requirements}
    for old, new in requirement_ids.items():
        by_id[new]["obligation_id"] = id_map[original_obligations[old]]
    return requirements, converted, assessments


def _project(rows):
    fol, smt = [], []
    for row in rows:
        projected = dict(guarded._fol(row), **_control_binding(row))
        expression = projected["expression"]
        expression["metadata"].update(_control_binding(row))
        projected["expression"] = TypedExpression.from_dict(expression).to_dict()
        fol.append(projected)
        arithmetic = guarded._smt(row)
        if arithmetic is not None:
            smt.append(dict(arithmetic, **_control_binding(row)))
    lean = guarded._lean(rows) if rows else None
    if lean is not None:
        by_id = {row["obligation_id"]: row for row in rows}
        for binding in lean["bindings"]:
            binding.update(_control_binding(by_id[binding["obligation_id"]]))
        lean.update(**_CONTROL_FALSE)
    return fol, smt, lean


def formalize_numerical_source(source_text, *, path="source.py"):
    structural = frontend.adapt_numerical_source(source_text, path=path)
    wire, program = structural.to_dict(), structural.program
    regions, controls = wire["guarded_regions"], wire["control_regions"]
    contexts = _contexts(program, regions, wire["command_contexts"], wire["source_sha256"]) if program else {}
    rows = ([_controlled(row, contexts, wire["source_sha256"]) for row in
        base._derive_obligations(program) + guarded._evaluation_obligations(program, regions)
        + _control_obligations(program, controls, wire["command_contexts"])] if program else [])
    assertions, assertion_rows, assertion_assessments = (_assertions(program, regions,
        wire["function_coverage"], contexts, wire["source_sha256"]) if program else ([], [], []))
    compounds, compound_rows, compound_assessments = (_compounds(program, regions, controls,
        wire["function_coverage"], contexts, wire["source_sha256"]) if program else ([], [], []))
    rows.extend(assertion_rows)
    rows.extend(compound_rows)
    if len(rows) > MAX_OBLIGATIONS:
        raise NumericalLogicError("numerical obligation count exceeds bound")
    native = None
    if program is not None:
        bridge = SoftwareVerificationSyntaxBridge().round_trip(program)
        if not bridge.exact:
            raise NumericalLogicError("native control numerical ProgramIR round trip differs")
        native = dict(family="program", encoding="ProgramIR", status="structural_only_requires_control_extension",
            bridge=bridge.to_dict(), guarded_regions=deepcopy(regions), control_regions=deepcopy(controls),
            command_contexts=deepcopy(wire["command_contexts"]), guarded_extension_required=True,
            control_extension_required=True, standalone_program_evaluation_complete=False, **_CONTROL_FALSE, **_FALSE)
    fol, smt, lean = _project(rows)
    counts = Counter(fid for row in rows for fid in row["function_ids"])
    functions = [dict(function_id=row["function_id"],
        qualified_name=row["name"].encode("utf-8")[:128].decode("utf-8", errors="ignore"),
        name_truncated=len(row["name"].encode("utf-8")) > 128,
        status="structurally_complete" if row["structurally_complete"] else "partial",
        structurally_complete=row["structurally_complete"],
        unsupported_construct_count=len(row["unsupported_constructs"]),
        pending_obligation_count=counts[row["function_id"]]) for row in wire["function_coverage"]]
    report = dict(schema=SCHEMA, profile=PROFILE, source_sha256=wire["source_sha256"], path=path,
        structural=wire, pending_obligations=rows, projections=dict(program=native, first_order=fol, smt=smt, lean=lean),
        compound_contracts=compounds, compound_contract_assessments=compound_assessments,
        assertion_requirements=assertions, assertion_requirement_assessments=assertion_assessments,
        unsupported_families=describe_numerical_logic_profile()["unsupported_families"],
        guarded_extension_required=True, control_extension_required=True, standalone_program_evaluation_complete=False,
        coverage=dict(structural_status=wire["status"], function_coverage=wire["function_coverage"],
                      pending_obligation_count=len(rows), source_obligations_discharged=0),
        solver_calls=0, provider_calls=0, training_performed=False, **_CONTROL_FALSE, **_FALSE)
    complete = sum(row["structurally_complete"] for row in functions)
    summary = dict(schema=SCHEMA, profile=PROFILE, source_sha256=wire["source_sha256"], functions=len(functions),
        structurally_complete_functions=complete, partial_or_unsupported_functions=len(functions)-complete,
        structural_status=wire["status"], pending_obligation_count=len(rows),
        families_with_artifacts=[family for family, present in (("program", native), ("first_order", fol), ("higher_order", lean)) if present],
        per_function=functions[:16], omitted_function_summaries=max(0, len(functions)-16),
        guarded_region_count=len(regions), control_region_count=len(controls),
        loop_region_count=sum(r["kind"] in {"for_statement", "while_statement"} for r in controls),
        guarded_extension_required=True, control_extension_required=True, standalone_program_evaluation_complete=False,
        **_CONTROL_FALSE, **_FALSE)
    summary.update(base._compound_summary(compounds))
    full_contracts = {row["contract_id"]: row for row in compounds}
    for row in summary["compound_contracts"]:
        row.update(_control_binding(full_contracts[row["contract_id"]]), guarded_region_ids=[],
                   evaluation_guard_verified=False, full_evaluation_contexts_in_native_report=True)
    compact = [{key: deepcopy(row[key]) for key in ("requirement_id", "function_id", "command_id",
        "predicate_expression_id", "source_ref_ids", "span_ids", "origin", "status", "predicate",
        "unknown_effects", "proof_authority", "source_obligations_discharged", "guarded_region_ids")}
        | _control_binding(row) | dict(evaluation_guard_verified=False, full_evaluation_contexts_in_native_report=True)
        for row in assertions[:base.MAX_ASSERTION_SUMMARIES]]
    while len(_raw(compact)) > base.MAX_ASSERTION_SUMMARY_BYTES:
        compact.pop()
    summary.update(assertion_requirements=compact, assertion_requirement_count=len(assertions),
                   omitted_assertion_requirement_summaries=len(assertions)-len(compact))
    report["summary"] = summary
    report["report_sha256"] = _sha(report)
    return report


def validate_numerical_logic_report(report, source_text, *, path="source.py"):
    if type(report) is not dict:
        raise NumericalLogicError("native control numerical logic report required")
    _raw(report)
    expected = formalize_numerical_source(source_text, path=path)
    if _raw(report) != _raw(expected):
        raise NumericalLogicError("control numerical source, CFG occurrence or projection differs")
    return expected


__all__ = ["PROFILE", "SCHEMA", "NumericalLogicError", "describe_numerical_logic_profile",
           "formalize_numerical_source", "validate_numerical_logic_report"]
