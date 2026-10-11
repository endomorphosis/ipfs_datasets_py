"""Opt-in numerical structure to source-bound, unresolved logic obligations.

The native ProgramIR bridge, many-sorted FOL syntax kernel and shared SMT
compiler own the representations. NumPy calls remain opaque. Mathematical
obligation templates are *not* assumptions or claims about Python execution.
This preparation API runs neither a solver nor source code nor a model.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..backends.smt.compiler import (
    SoftwareVerificationSMTCompiler, SmtTerm, term_int, term_symbol,
)
from ..families.registry import build_default_registry
from ..syntax_core.ast import TypedExpression, mk_constant, mk_predicate
from ..syntax_core.signatures import atomic_sort, many_sorted_fol_signature
from .syntax_bridge import SoftwareVerificationSyntaxBridge

PROFILE = "python-numerical-structure@1"
SCHEMA = "numerical-source-logic/v1"
MAX_OBLIGATIONS = 256
MAX_REPORT_BYTES = 8 * 1024 * 1024
COMPOUND_SCHEMA = "numerical-selected-eigenpair-contract@1"
MAX_COMPOUND_SUMMARIES = 8
MAX_COMPOUND_SUMMARY_BYTES = 4096
ASSERTION_SCHEMA = "numerical-source-assertion-requirement@1"
MAX_ASSERTION_SUMMARIES = 4
MAX_ASSERTION_SUMMARY_BYTES = 4096
_FALSE = dict(proof_authority=False, source_semantics_verified=False,
    whole_program_semantics_verified=False, completion_authority=False,
    execution_authority=False, source_executed=False, model_inference_executed=False)


class NumericalLogicError(ValueError):
    """Invalid or stale numerical structural evidence."""


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise NumericalLogicError("inert bounded numerical logic JSON required") from exc
    if len(raw) > MAX_REPORT_BYTES:
        raise NumericalLogicError("numerical logic report exceeds byte bound")
    return raw


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def describe_numerical_logic_profile():
    """Resolve existing families; SMT and Lean are encodings, not new families."""
    registry = build_default_registry()
    unsupported = {
        "transition_system": "No reviewed numerical transition relation; TLA+ is not generated from a CFG alone.",
        "temporal": "No source-grounded temporal specification or trace semantics.",
        "separation_logic": "No reviewed heap, aliasing or ownership model.",
        "concurrency": "No thread/interference semantics.",
        "hyperproperty": "No explicit information-flow policy and trace relation.",
        "refinement": "No reviewed numerical implementation/specification refinement relation.",
        "horn_chc": "No complete numerical verification-condition semantics.",
        "frame_logic": "No reviewed object/frame interpretation.",
        "dcec": "No supplied cognitive, normative or event interpretation.",
        "tdfol": "No supplied temporal/normative interpretation.",
    }
    for family in ("program", "first_order", "higher_order", *unsupported):
        registry.resolve(family)
    return dict(profile=PROFILE, schema=SCHEMA, opt_in=True,
        routes=[dict(family="program", encoding="ProgramIR", status="structural_only",
                     owner=SoftwareVerificationSyntaxBridge.INTERFACE),
                dict(family="first_order", encoding="TypedExpression", status="pending_predicates"),
                dict(family="first_order", encoding="SMT-LIB", status="pending_abstract_integer_constraints",
                     owner=SoftwareVerificationSMTCompiler.INTERFACE),
                dict(family="higher_order", encoding="Lean4", status="definitions_and_conditional_lemmas")],
        unsupported_families=[dict(family=k, status="unsupported", reason=v)
                              for k, v in unsupported.items()],
        contract_vc_status="unsupported_without_reviewed_numerical_semantics",
        solver_calls=0, provider_calls=0, **_FALSE)


def _reachable_functions(program):
    expressions = {x.expression_id: x for x in program.expressions}
    commands = {x.command_id: x for x in program.commands}
    owners = {}
    for function in program.functions:
        pending = [key for block in function.cfg.blocks for cid in block.command_ids
                   for key in commands[cid].expression_ids]
        seen = set()
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            owners.setdefault(key, set()).add(function.function_id)
            pending.extend(expressions[key].operand_ids)
    return owners


def _derive_obligations(program):
    owners = _reachable_functions(program)
    expressions = {x.expression_id: x for x in program.expressions}
    rows = []

    def add(kind, expression, reason, roles=None):
        row = dict(kind=kind, expression_id=expression.expression_id,
            source_ref_ids=list(expression.source_ref_ids), span_ids=list(expression.span_ids),
            function_ids=sorted(owners.get(expression.expression_id, ())),
            roles=roles or {}, status="pending", reason=reason,
            assumptions_asserted=False, source_binding_is_semantic_proof=False, **_FALSE)
        row["obligation_id"] = "numerical:" + _sha(row)[:32]
        rows.append(row)

    for expression in program.expressions:
        attrs = expression.attributes.to_dict()
        if expression.kind.value == "index":
            index = expressions[expression.operand_ids[1]]
            indices = (index.operand_ids if index.attributes.to_dict().get("call_kind") == "python.tuple"
                       else (index.expression_id,))
            for axis, key in enumerate(indices):
                item = expressions[key]
                kind = ("slice_safety" if item.attributes.to_dict().get("call_kind") == "python.slice"
                        else "indexing_semantics" if item.type_ref in {
                            "python.list", "python.tuple", "python.literal.NoneType",
                            "python.literal.str", "python.literal.bool", "python.literal.float"}
                        else "index_safety")
                add(kind, expression,
                    "Resolve receiver type, rank, axis, scalar/slice/advanced-index semantics and actual extent before discharge.",
                    dict(receiver_expression=expression.operand_ids[0], index_expression=key,
                         syntactic_axis=axis, actual_axis_interpretation="pending"))
        if expression.kind.value != "call" or attrs.get("call_kind") != "python.call":
            continue
        add("library_semantics_and_effects", expression,
            "Call result, exceptions, dispatch, mutation and aliasing remain opaque; imported names do not prove runtime identity.",
            dict(callee_expression=expression.operand_ids[0],
                 imported_callee=attrs.get("imported_callee"),
                 qualified_callee=attrs.get("qualified_callee")))
        if attrs.get("callee_resolution") != "declared_import":
            continue
        callee = attrs.get("imported_callee")
        args = expression.operand_ids[1:]
        count = attrs.get("positional_count", 0)
        # Only a directly identifiable input supports a numerical library
        # obligation. Unresolved dynamic receivers do not inherit NumPy types.
        array = args[0] if count else None
        if array is None and "a" in attrs.get("keyword_names", ()):
            array = args[count + attrs["keyword_names"].index("a")]
        if array is None:
            continue
        roles = dict(input_expression=array, result_expression=expression.expression_id,
                     imported_callee=callee)
        if callee in {"numpy.linalg.eig", "numpy.linalg.eigh"}:
            add("matrix_shape", expression,
                "Bind actual ndarray rank and trailing dimensions; mathematical square-matrix template does not establish dtype or runtime shape.", roles)
            add("eigenpair_residual", expression,
                "Choose real/complex arithmetic, finite/nonfinite and tolerance policy; bind each output eigenpair and prove library/source refinement.", roles)
        if callee in {"numpy.argsort", "numpy.argmax", "numpy.argmin"}:
            add("selection", expression,
                "Resolve axis, ordering key, permutation/extremum, tie, NaN and complex policies before identifying a selected result.", roles)
    if len(rows) > MAX_OBLIGATIONS:
        raise NumericalLogicError("numerical obligation count exceeds bound")
    return rows


def _selected_eigenpair_pattern(function, commands, expressions):
    """Join one straight-line def/use pattern, never infer NumPy semantics.

    This is deliberately not a general substitution engine: extra assignments,
    calls or control flow are fences. Distinct parameter/local symbols prevent
    simultaneous unpacking and later rebinding from conflating old/new values.
    """
    if len(function.cfg.blocks) != 1 or function.cfg.edges:
        return None, "control_flow_not_supported"
    ordered = [commands[key] for key in function.cfg.blocks[0].command_ids]
    ordered = [command for command in ordered if not (
        command.kind.value == "skip" and not command.expression_ids
        and not command.attributes.to_dict().get("unsupported_construct"))]
    if ([command.kind.value for command in ordered] != ["assign", "assign", "return"]
            or any(len(command.expression_ids) != 1 for command in ordered)
            or len(function.parameter_symbol_ids) != 1):
        return None, "straight_line_statement_shape_not_supported"
    eig_assign, index_assign, returned = ordered
    eig_pattern = eig_assign.attributes.to_dict().get("assignment_pattern", {})
    index_pattern = index_assign.attributes.to_dict().get("assignment_pattern", {})
    elements = eig_pattern.get("elements", ())
    if (eig_pattern.get("kind") not in {"tuple", "list"} or len(elements) != 2
            or any(item.get("kind") != "name" for item in elements)
            or index_pattern.get("kind") != "name"):
        return None, "unpacking_pattern_not_supported"
    values, vectors = (item["symbol_id"] for item in elements)
    selected = index_pattern["symbol_id"]
    parameter, = function.parameter_symbol_ids
    if (len({parameter, values, vectors, selected}) != 4
            or set(eig_assign.target_symbol_ids) != {values, vectors}
            or tuple(index_assign.target_symbol_ids) != (selected,)):
        return None, "rebound_or_aliased_symbols"

    def symbol(expression_id, expected):
        value = expressions[expression_id]
        return value.kind.value == "symbol" and tuple(value.symbol_ids) == (expected,)

    def argument(expression_id, callee, *, keyword=None):
        value = expressions[expression_id]
        attrs = value.attributes.to_dict()
        if (value.kind.value != "call" or attrs.get("call_kind") != "python.call"
                or attrs.get("callee_resolution") != "declared_import"
                or attrs.get("imported_callee") != callee or len(value.operand_ids) != 2):
            return None
        if attrs.get("positional_count") == 1 and attrs.get("keyword_names") == []:
            return value.operand_ids[1]
        if keyword and attrs.get("positional_count") == 0 and attrs.get("keyword_names") == [keyword]:
            return value.operand_ids[1]
        return None

    eig = eig_assign.expression_ids[0]
    input_expression = argument(eig, "numpy.linalg.eig", keyword="a")
    selection = index_assign.expression_ids[0]
    magnitude = argument(selection, "numpy.argmax", keyword="a")
    magnitude_input = argument(magnitude, "numpy.abs") if magnitude is not None else None
    if (input_expression is None or not symbol(input_expression, parameter)
            or magnitude_input is None or not symbol(magnitude_input, values)):
        return None, "eigensystem_or_magnitude_selection_not_matched"
    output = expressions[returned.expression_ids[0]]
    if (output.attributes.to_dict().get("call_kind") != "python.tuple"
            or len(output.operand_ids) != 2):
        return None, "returned_pair_not_matched"
    value, vector = (expressions[key] for key in output.operand_ids)
    if (value.kind.value != "index" or vector.kind.value != "index"
            or len(value.operand_ids) != 2 or len(vector.operand_ids) != 2
            or not symbol(value.operand_ids[0], values)
            or not symbol(value.operand_ids[1], selected)
            or not symbol(vector.operand_ids[0], vectors)):
        return None, "returned_value_flow_not_matched"
    axes = expressions[vector.operand_ids[1]]
    if (axes.attributes.to_dict().get("call_kind") != "python.tuple"
            or len(axes.operand_ids) != 2 or not symbol(axes.operand_ids[1], selected)):
        return None, "returned_column_not_matched"
    full_slice = expressions[axes.operand_ids[0]]
    slice_attrs = full_slice.attributes.to_dict()
    if (slice_attrs.get("call_kind") != "python.slice"
            or slice_attrs.get("explicit_bounds") != [False, False, False]
            or len(full_slice.operand_ids) != 3
            or any(expressions[key].type_ref != "python.literal.NoneType"
                   or expressions[key].attributes.to_dict().get("value") is not None
                   for key in full_slice.operand_ids)):
        return None, "partial_or_strided_column_not_supported"
    return dict(input_expression=input_expression, eig_expression=eig,
        magnitude_expression=magnitude, selection_expression=selection,
        returned_value_expression=value.expression_id, returned_vector_expression=vector.expression_id,
        return_expression=output.expression_id, values_symbol=values, vectors_symbol=vectors,
        selected_symbol=selected, eig_assignment_command=eig_assign.command_id,
        selection_assignment_command=index_assign.command_id, return_command=returned.command_id), None


_COMPOUND_REASONS = {
    "selected_eigenpair_runtime_interpretation":
        "Bind actual NumPy callable identities, ndarray types, dtype, exceptions, aliasing and effects; declared imports and annotations are not runtime evidence.",
    "selected_eigenpair_dimensions":
        "Establish a nonempty square input, an equally long eigenvalue vector and an eigenvector matrix with corresponding columns; no shape is inferred from an annotation.",
    "selected_eigenpair_value_column":
        "Interpret tuple unpacking and ndarray indexing so the returned value and whole vector column use the same selected index and eig call result.",
    "selected_eigenpair_magnitude_selection":
        "Interpret abs and argmax as magnitude maximization, with explicit complex, axis, tie and nonfinite policies; no spectral dominance follows from syntax alone.",
    "selected_eigenpair_nonzero":
        "Establish a nonzero returned vector; a not-allclose-to-zero guard additionally needs its own reviewed comparison policy, not merely exact inequality.",
    "selected_eigenpair_finite":
        "Bind and establish finiteness of the returned value and vector for the chosen real/complex floating-point interpretation.",
    "selected_eigenpair_approximate_residual":
        "Establish the source-bound approximate eigenpair residual under an explicit comparison relation and reviewed arithmetic; no tolerance/default or norm-based threshold is invented.",
}


def _compound_contracts(program, coverage, source_sha256):
    commands = {value.command_id: value for value in program.commands}
    expressions = {value.expression_id: value for value in program.expressions}
    covered = {row["function_id"]: row["structurally_complete"] for row in coverage}
    contracts, obligations, assessments = [], [], []
    for function in program.functions:
        if covered.get(function.function_id) is not True:
            roles, reason = None, "incomplete_or_unsupported_function"
        else:
            roles, reason = _selected_eigenpair_pattern(function, commands, expressions)
        assessments.append(dict(function_id=function.function_id,
            status="matched_syntax_only" if roles else "not_matched", reason=reason))
        if roles is None:
            continue
        spans = list(dict.fromkeys(span for key in (
            "eig_assignment_command", "selection_assignment_command", "return_command")
            for span in commands[roles[key]].span_ids))
        contract = dict(schema=COMPOUND_SCHEMA, kind="selected_eigenpair", status="pending",
            function_id=function.function_id, source_sha256=source_sha256,
            source_ref_ids=list(function.source_ref_ids), span_ids=spans,
            pattern_status="matched_syntax_only", roles=roles,
            tuple_components=[dict(symbol_id=roles["values_symbol"], component=0),
                              dict(symbol_id=roles["vectors_symbol"], component=1)],
            tolerance_policy="unresolved_no_defaults_assumed", runtime_identity_verified=False,
            source_obligations_discharged=0, assumptions_asserted=False, **_FALSE)
        contract["contract_id"] = "numerical-contract:" + _sha(contract)[:32]
        bound = []
        for kind, reason in _COMPOUND_REASONS.items():
            row = dict(kind=kind, expression_id=roles["return_expression"],
                source_ref_ids=list(function.source_ref_ids), span_ids=spans,
                function_ids=[function.function_id], roles=dict(compound_contract_id=contract["contract_id"], **roles),
                status="pending", reason=reason, assumptions_asserted=False,
                source_binding_is_semantic_proof=False, **_FALSE)
            row["obligation_id"] = "numerical:" + _sha(row)[:32]
            obligations.append(row); bound.append(row["obligation_id"])
        contract["obligation_ids"] = bound
        contracts.append(contract)
    return contracts, obligations, assessments


def _compound_summary(contracts):
    rows = [dict(contract_id=row["contract_id"], kind=row["kind"], function_id=row["function_id"],
        status="pending", source_ref_ids=row["source_ref_ids"], span_ids=row["span_ids"],
        roles={key: row["roles"][key] for key in ("input_expression", "eig_expression",
            "selection_expression", "returned_value_expression", "returned_vector_expression")},
        pending_obligation_kinds=list(_COMPOUND_REASONS), proof_authority=False,
        source_obligations_discharged=0) for row in contracts[:MAX_COMPOUND_SUMMARIES]]
    while len(_raw(rows)) > MAX_COMPOUND_SUMMARY_BYTES:
        rows.pop()
    return dict(compound_contracts=rows, compound_contract_count=len(contracts),
        omitted_compound_contract_summaries=len(contracts)-len(rows))


def _expression_closure(expression_id, expressions):
    """Keep source operand order while walking an already validated ProgramIR."""
    pending, seen, ordered = [expression_id], set(), []
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
        pending.extend(reversed(expressions[key].operand_ids))
    return ordered


def _assertion_predicate(expression, expressions):
    """Describe a call/polarity syntactically; do not choose truthiness semantics."""
    call, operator = expression, "expression"
    if (expression.kind.value == "unary" and expression.operator == "not"
            and len(expression.operand_ids) == 1):
        call, operator = expressions[expression.operand_ids[0]], "not"
    attrs = call.attributes.to_dict()
    if call.kind.value != "call" or attrs.get("call_kind") != "python.call":
        return dict(operator="expression", call_expression_id=None, imported_callee=None,
            callee_resolution=None, argument_expression_ids=[], keyword_names=[])
    return dict(operator="call" if operator == "expression" else operator,
        call_expression_id=call.expression_id, imported_callee=attrs.get("imported_callee"),
        callee_resolution=attrs.get("callee_resolution"),
        argument_expression_ids=list(call.operand_ids[1:]),
        keyword_names=attrs.get("keyword_names", []))


def _derive_assertion_requirements(program, coverage, source_sha256):
    """Observe local ASSERT predicates, never infer a callee postcondition.

    Assignment links are lexical reaching definitions, not heap/value equality.
    Versioned links preserve RHS-before-LHS rebinding and unpack component order.
    Every intervening expression retains unknown effects. Unsupported statements
    fence the function; only deferred failure messages permit predicate scanning.
    """
    expressions = {row.expression_id: row for row in program.expressions}
    commands = {row.command_id: row for row in program.commands}
    covered = {row["function_id"]: row for row in coverage}
    requirements, obligations, assessments = [], [], []
    for function in program.functions:
        unsupported = set(covered[function.function_id]["unsupported_constructs"])
        allowed = {"python.assert.message_expression_deferred"}
        if len(function.cfg.blocks) != 1 or function.cfg.edges or unsupported - allowed:
            assessments.append(dict(function_id=function.function_id, status="not_scanned",
                reason="control_flow_or_unsupported_function"))
            continue
        assessments.append(dict(function_id=function.function_id, status="predicate_scan_only",
            reason="deferred_failure_message" if unsupported else None))
        environment, definitions, prior_effects = {}, {}, []
        for command_id in function.cfg.blocks[0].command_ids:
            command = commands[command_id]
            attributes = command.attributes.to_dict()
            if command.kind.value == "assign" and len(command.expression_ids) == 1:
                value_id = command.expression_ids[0]
                closure = _expression_closure(value_id, expressions)
                dependencies = sorted({environment[symbol] for key in closure
                    for symbol in expressions[key].symbol_ids if symbol in environment})
                unresolved = sorted({symbol for key in closure for symbol in expressions[key].symbol_ids
                                     if symbol not in environment})
                pattern = attributes.get("assignment_pattern", {})
                targets, pending = [], [(pattern, [])]
                while pending:
                    node, path = pending.pop()
                    if node.get("kind") == "name":
                        targets.append((node["symbol_id"], path))
                    elif node.get("kind") in {"tuple", "list"}:
                        pending.extend((child, path + [index]) for index, child in
                                       reversed(list(enumerate(node.get("elements", [])))))
                counts = Counter(symbol for symbol, _ in targets)
                for symbol, path in targets:
                    if counts[symbol] != 1:
                        # Duplicate unpack targets need a separately reviewed
                        # overwrite interpretation; retain no reaching witness.
                        environment.pop(symbol, None)
                        continue
                    row = dict(symbol_id=symbol, assignment_command_id=command_id,
                        value_expression_id=value_id, component_path=path,
                        input_definition_ids=dependencies, unresolved_input_symbol_ids=unresolved,
                        source_ref_ids=list(command.source_ref_ids), span_ids=list(command.span_ids),
                        binding_kind="lexical_reaching_assignment_not_runtime_value")
                    row["definition_id"] = "assertion-definition:" + _sha(row)[:32]
                    definitions[row["definition_id"]] = row
                    environment[symbol] = row["definition_id"]
            if command.kind.value == "assert" and len(command.expression_ids) == 1:
                predicate_id = command.expression_ids[0]
                closure = _expression_closure(predicate_id, expressions)
                uses = [dict(expression_id=key, symbol_id=symbol,
                    definition_id=environment.get(symbol)) for key in closure
                    for symbol in expressions[key].symbol_ids]
                required = {row["definition_id"] for row in uses if row["definition_id"] is not None}
                pending = list(required)
                while pending:
                    for key in definitions[pending.pop()]["input_definition_ids"]:
                        if key not in required:
                            required.add(key)
                            pending.append(key)
                row = dict(schema=ASSERTION_SCHEMA, kind="source_assertion_predicate",
                    origin="source_assertion", status="pending", function_id=function.function_id,
                    command_id=command_id, predicate_expression_id=predicate_id,
                    source_sha256=source_sha256, source_ref_ids=list(command.source_ref_ids),
                    span_ids=list(command.span_ids), predicate_expression_ids=closure,
                    predicate=_assertion_predicate(expressions[predicate_id], expressions),
                    symbol_uses=uses, symbol_definitions=[definitions[key] for key in sorted(required)],
                    unresolved_symbol_ids=sorted({row["symbol_id"] for row in uses if row["definition_id"] is None}),
                    intervening_effect_command_ids=list(prior_effects), unknown_effects=True,
                    runtime_identity_verified=False, runtime_truthiness_verified=False,
                    function_postcondition_inferred=False, assertion_execution_verified=False,
                    scope="predicate at this source statement if reached with assertions enabled; not a global or callee postcondition",
                    failure_message_structure_lowered=attributes.get("assertion_message_structure_lowered", True),
                    comparison_policy="explicit_source_arguments_only_no_library_defaults_assumed",
                    assumptions_asserted=False, source_obligations_discharged=0, **_FALSE)
                row["requirement_id"] = "assertion-requirement:" + _sha(row)[:32]
                requirements.append(row)
                obligation = dict(kind="source_assertion_predicate", expression_id=predicate_id,
                    source_ref_ids=row["source_ref_ids"], span_ids=row["span_ids"],
                    function_ids=[function.function_id], status="pending",
                    roles=dict(requirement_id=row["requirement_id"], command_id=command_id,
                               predicate_operator=row["predicate"]["operator"]),
                    reason="Interpret the exact source assertion predicate, callable identity, truthiness, arguments, effects and reachability; its presence proves neither execution nor truth nor a called function's contract.",
                    assumptions_asserted=False, source_binding_is_semantic_proof=False, **_FALSE)
                obligation["obligation_id"] = "numerical:" + _sha(obligation)[:32]
                row["obligation_id"] = obligation["obligation_id"]
                obligations.append(obligation)
            if command.expression_ids:
                prior_effects.append(command_id)
    return requirements, obligations, assessments


def _assertion_summary(requirements):
    rows = []
    for row in requirements[:MAX_ASSERTION_SUMMARIES]:
        compact = {key: row[key] for key in ("requirement_id", "function_id", "command_id",
            "predicate_expression_id", "source_ref_ids", "span_ids", "origin", "status", "predicate",
            "unknown_effects", "proof_authority", "source_obligations_discharged")}
        # Direct predicate uses only; the complete versioned dependency graph
        # remains in the replayed full report. No inline source text is needed.
        direct = {use["definition_id"] for use in row["symbol_uses"]}
        compact["symbol_definitions"] = [{key: definition[key] for key in
            ("definition_id", "symbol_id", "assignment_command_id", "value_expression_id", "component_path")}
            for definition in row["symbol_definitions"] if definition["definition_id"] in direct]
        rows.append(compact)
    while len(_raw(rows)) > MAX_ASSERTION_SUMMARY_BYTES:
        rows.pop()
    return dict(assertion_requirements=rows, assertion_requirement_count=len(requirements),
        omitted_assertion_requirement_summaries=len(requirements)-len(rows))


def _fol(row):
    # These are explicit unresolved predicates over source expression identities.
    # There is no axiom asserting any predicate, nor an invented entity referent.
    sort = atomic_sort("SourceExpression")
    signature = many_sorted_fol_signature("sig:" + row["obligation_id"],
        sorts=(sort,), constants=(("source_expression", sort),),
        predicates=((row["kind"], (sort,)),))
    expression = TypedExpression("fol:" + row["obligation_id"],
        mk_predicate("node:obligation", row["kind"],
            (mk_constant("node:source", "source_expression", sort),)), signature,
        metadata=dict(source_expression_id=row["expression_id"],
                      obligation_id=row["obligation_id"], status="pending"))
    return dict(obligation_id=row["obligation_id"], expression=expression.to_dict(),
                predicate_interpretation="unresolved; no axiom asserted", **_FALSE)


def _smt(row):
    # The shared compiler produces goals with *no assumptions*. A check-sat
    # command is an artifact only; no solver runs here. Abstract symbols are not
    # silently equated with Python values, dimensions, or NumPy array effects.
    if row["kind"] == "index_safety":
        extent, index = term_symbol("extent"), term_symbol("index")
        goal = SmtTerm("and", arguments=(
            SmtTerm("ge", arguments=(extent, term_int(0))),
            SmtTerm("and", arguments=(
                SmtTerm("le", arguments=(SmtTerm("neg", arguments=(extent,)), index)),
                SmtTerm("lt", arguments=(index, extent))))))
        symbols = ("extent", "index")
        prerequisites = ["actual builtin integer scalar index", "selected concrete axis extent",
                         "reviewed ndarray indexing and source-value interpretation"]
    elif row["kind"] == "matrix_shape":
        rows, columns = term_symbol("rows"), term_symbol("columns")
        goal = SmtTerm("and", arguments=(
            SmtTerm("ge", arguments=(rows, term_int(0))),
            SmtTerm("and", arguments=(SmtTerm("ge", arguments=(columns, term_int(0))),
                                      SmtTerm("eq", arguments=(rows, columns))))))
        symbols = ("rows", "columns")
        prerequisites = ["actual ndarray rank at least two", "trailing matrix axes bound to abstract rows/columns",
                         "reviewed dtype and batch semantics"]
    else:
        return None
    compiler = SoftwareVerificationSMTCompiler()
    result = compiler.compile_arithmetic_goal(obligation_id=row["obligation_id"],
        goal=goal, symbols=symbols, assumptions=(), request_unsat_core=False)
    return dict(obligation_id=row["obligation_id"], status="pending",
        interpretation_prerequisites=prerequisites, compilation=result.to_dict(),
        solver_executed=False, discharged=False, **_FALSE)


_LEAN_BASE = """import Std

namespace NumericalObligations

-- Specifications only: no declaration below asserts a property of Python.
def IndexSafety (extent : Nat) (index : Int) : Prop :=
  -(Int.ofNat extent) ≤ index ∧ index < Int.ofNat extent

def MatrixShape (rows columns : Nat) : Prop := rows = columns

def SelectionMax {α : Type} (le : α → α → Prop)
    (n : Nat) (score : Nat → α) (selected : Nat) : Prop :=
  selected < n ∧ ∀ j, j < n → le (score j) (score selected)

def SelectionMin {α : Type} (le : α → α → Prop)
    (n : Nat) (score : Nat → α) (selected : Nat) : Prop :=
  selected < n ∧ ∀ j, j < n → le (score selected) (score j)

def Ordering {α : Type} (le : α → α → Prop)
    (n : Nat) (score : Nat → α) (order : Nat → Nat) : Prop :=
  (∀ i, i < n → order i < n) ∧
  (∀ i, i < n → ∀ j, j < n → order i = order j → i = j) ∧
  (∀ i, i + 1 < n → le (score (order i)) (score (order (i + 1))))

def finiteSum {α : Type} (zero : α) (add : α → α → α)
    (term : Nat → α) : Nat → α
  | 0 => zero
  | n + 1 => add (finiteSum zero add term n) (term n)

def EigenpairResidual {α : Type} (zero : α) (add mul : α → α → α)
    (n : Nat) (matrix : Nat → Nat → α) (vector : Nat → α) (value : α) : Prop :=
  ∀ i, i < n → finiteSum zero add (fun j => mul (matrix i j) (vector j)) n =
    mul value (vector i)

def NormalizeIndex (extent : Nat) (index : Int) : Int :=
  if index < 0 then index + Int.ofNat extent else index

-- Conditional arithmetic lemmas; their premises are not established for source values.
theorem normalized_index_bounds (extent : Nat) (index : Int)
    (bounds : IndexSafety extent index) :
    0 ≤ NormalizeIndex extent index ∧ NormalizeIndex extent index < Int.ofNat extent := by
  unfold IndexSafety at bounds
  unfold NormalizeIndex
  split <;> omega

theorem last_index_bound (extent : Nat) (nonempty : 0 < extent) : extent - 1 < extent := by
  omega
"""


_LEAN_COMPOUND = """
-- A proposed mathematical contract, not the runtime interpretation of NumPy.
def EigensystemDimensions (rows columns valuesCount vectorRows vectorColumns : Nat) : Prop :=
  0 < rows ∧ columns = rows ∧ valuesCount = rows ∧ vectorRows = rows ∧ vectorColumns = rows

def SameSelectedColumn {α : Type} (values : Nat → α) (vectors : Nat → Nat → α)
    (selected : Nat) (value : α) (vector : Nat → α) : Prop :=
  value = values selected ∧ ∀ row, vector row = vectors row selected

def NonzeroVector {α : Type} (zero : α) (n : Nat) (vector : Nat → α) : Prop :=
  ∃ row, row < n ∧ vector row ≠ zero

def FiniteEigenpair {α : Type} (finite : α → Prop)
    (n : Nat) (value : α) (vector : Nat → α) : Prop :=
  finite value ∧ ∀ row, row < n → finite (vector row)

-- `close` has no chosen tolerance or floating-point semantics. Those remain
-- source interpretation obligations, including the direction of comparison.
def ApproximateEigenpairResidual {α : Type} (zero : α) (add mul : α → α → α)
    (close : α → α → Prop) (n : Nat) (matrix : Nat → Nat → α)
    (vector : Nat → α) (value : α) : Prop :=
  ∀ row, row < n → close
    (finiteSum zero add (fun column => mul (matrix row column) (vector column)) n)
    (mul value (vector row))

def SelectedEigenpair {α β : Type} (zero : α) (add mul : α → α → α)
    (finite : α → Prop) (close : α → α → Prop) (le : β → β → Prop)
    (n : Nat) (matrix : Nat → Nat → α) (score : Nat → β)
    (selected : Nat) (value : α) (vector : Nat → α) : Prop :=
  NonzeroVector zero n vector ∧ FiniteEigenpair finite n value vector ∧
    ApproximateEigenpairResidual zero add mul close n matrix vector value ∧
    SelectionMax le n score selected

-- Both the eigensystem properties and the selection property are premises.
-- This theorem does not prove either premise for any source library call.
theorem selected_column_contract {α β : Type} (zero : α) (add mul : α → α → α)
    (finite : α → Prop) (close : α → α → Prop) (le : β → β → Prop)
    (n : Nat) (matrix vectors : Nat → Nat → α) (values : Nat → α)
    (score : Nat → β) (selected : Nat)
    (choice : SelectionMax le n score selected)
    (columns : ∀ j, j < n → NonzeroVector zero n (fun row => vectors row j) ∧
      FiniteEigenpair finite n (values j) (fun row => vectors row j) ∧
      ApproximateEigenpairResidual zero add mul close n matrix (fun row => vectors row j) (values j)) :
    SelectedEigenpair zero add mul finite close le n matrix score selected
      (values selected) (fun row => vectors row selected) := by
  exact ⟨(columns selected choice.1).1, (columns selected choice.1).2.1,
    (columns selected choice.1).2.2, choice⟩
"""


_LEAN_ASSERTIONS = """
-- Proposed interpretations of source ASSERT expressions. Callable evaluation,
-- Python truthiness, effects and reachability are unresolved parameters.
def AssertionPredicate (predicate : Prop) : Prop := predicate

def CallPredicate {Arguments Result : Type} (call : Arguments → Result)
    (truthy : Result → Prop) (arguments : Arguments) : Prop := truthy (call arguments)

def NegatedCallPredicate {Arguments Result : Type} (call : Arguments → Result)
    (truthy : Result → Prop) (arguments : Arguments) : Prop := ¬ truthy (call arguments)

-- Opposite predicates cannot both hold under the SAME supplied interpretation.
-- This supplies no witness for either predicate or for a Python call.
theorem opposite_call_predicates_incompatible {Arguments Result : Type}
    (call : Arguments → Result) (truthy : Result → Prop) (arguments : Arguments)
    (positive : CallPredicate call truthy arguments)
    (negative : NegatedCallPredicate call truthy arguments) : False := by
  exact negative positive
"""


def _lean(rows):
    definitions = {"index_safety": "IndexSafety", "matrix_shape": "MatrixShape",
                   "eigenpair_residual": "EigenpairResidual",
                   "selected_eigenpair_dimensions": "EigensystemDimensions",
                   "selected_eigenpair_value_column": "SameSelectedColumn",
                   "selected_eigenpair_magnitude_selection": "SelectionMax",
                   "selected_eigenpair_nonzero": "NonzeroVector",
                   "selected_eigenpair_finite": "FiniteEigenpair",
                   "selected_eigenpair_approximate_residual": "ApproximateEigenpairResidual"}
    bindings = []
    lines = [_LEAN_BASE]
    compound = any(row["kind"] in _COMPOUND_REASONS for row in rows)
    if compound:
        lines.append(_LEAN_COMPOUND)
    assertions = any(row["kind"] == "source_assertion_predicate" for row in rows)
    if assertions:
        lines.append(_LEAN_ASSERTIONS)
    for row in rows:
        definition = definitions.get(row["kind"])
        if row["kind"] == "selection":
            definition = {"numpy.argmax": "SelectionMax", "numpy.argmin": "SelectionMin",
                          "numpy.argsort": "Ordering"}.get(row["roles"]["imported_callee"])
        if row["kind"] == "source_assertion_predicate":
            definition = {"call": "CallPredicate", "not": "NegatedCallPredicate",
                          "expression": "AssertionPredicate"}[row["roles"]["predicate_operator"]]
        if definition is None:
            continue
        name = "source_obligation_" + row["obligation_id"].split(":")[1]
        # Generated declaration names use digests, never unescaped source text.
        lines.append(f"def {name} := @{definition}\n")
        bindings.append(dict(obligation_id=row["obligation_id"], declaration=name,
            definition=definition, source_expression_id=row["expression_id"],
            interpretation="pending; template parameters are not source-value witnesses"))
    lines.append("end NumericalObligations\n")
    source = "\n".join(lines)
    return dict(family="higher_order", encoding="Lean4", status="prepared_not_built",
        library="NumericalObligations", source=source,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(), bindings=bindings,
        conditional_lemmas=["normalized_index_bounds", "last_index_bound"] +
            (["selected_column_contract"] if compound else []) +
            (["opposite_call_predicates_incompatible"] if assertions else []),
        source_obligations_discharged=0, lake_executed=False, **_FALSE)


def formalize_numerical_source(source_text, *, path="source.py"):
    """Prepare native structural and logic artifacts without executing anything.

    The original source text is not copied into this report. Source-derived
    names/spans and IR literals remain in the structural evidence. Consumers
    must replay with the same source bytes/path before reusing a proof index.
    """
    from .numerical_source import adapt_numerical_source
    structural = adapt_numerical_source(source_text, path=path)
    wire = structural.to_dict()
    program = structural.program
    obligations = _derive_obligations(program) if program is not None else []
    contracts, compound_obligations, assessments = (_compound_contracts(program,
        wire["function_coverage"], wire["source_sha256"]) if program is not None else ([], [], []))
    obligations.extend(compound_obligations)
    assertions, assertion_obligations, assertion_assessments = (_derive_assertion_requirements(
        program, wire["function_coverage"], wire["source_sha256"]) if program is not None else ([], [], []))
    obligations.extend(assertion_obligations)
    if len(obligations) > MAX_OBLIGATIONS:
        raise NumericalLogicError("numerical obligation count exceeds bound")
    native = None
    if program is not None:
        bridge = SoftwareVerificationSyntaxBridge().round_trip(program)
        if not bridge.exact:
            raise NumericalLogicError("native numerical ProgramIR round trip differs")
        native = dict(family="program", encoding="ProgramIR", status="structural_only",
                      bridge=bridge.to_dict(), **_FALSE)
    fol = [_fol(row) for row in obligations]
    smt = [value for row in obligations if (value := _smt(row)) is not None]
    lean = _lean(obligations) if obligations else None
    projections = dict(program=native, first_order=fol, smt=smt, lean=lean)
    profile = describe_numerical_logic_profile()
    counts = Counter(fid for row in obligations for fid in row["function_ids"])
    coverage = wire["function_coverage"]
    functions = [dict(function_id=row["function_id"],
        qualified_name=row["name"].encode("utf-8")[:128].decode("utf-8", errors="ignore"),
        name_truncated=len(row["name"].encode("utf-8")) > 128,
        status="structurally_complete" if row["structurally_complete"] else "partial",
        structurally_complete=row["structurally_complete"],
        unsupported_construct_count=len(row["unsupported_constructs"]),
        pending_obligation_count=counts[row["function_id"]]) for row in coverage]
    report = dict(schema=SCHEMA, profile=PROFILE, source_sha256=wire["source_sha256"],
        path=path, structural=wire, pending_obligations=obligations, projections=projections,
        compound_contracts=contracts, compound_contract_assessments=assessments,
        assertion_requirements=assertions, assertion_requirement_assessments=assertion_assessments,
        unsupported_families=profile["unsupported_families"],
        coverage=dict(structural_status=wire["status"],
                      function_coverage=wire["function_coverage"],
                      pending_obligation_count=len(obligations),
                      source_obligations_discharged=0),
        solver_calls=0, provider_calls=0, training_performed=False, **_FALSE)
    # Coverage status/details come from the frontend; summary handling is kept
    # separate from proof status, which is always unresolved here.
    complete = sum(row["structurally_complete"] for row in functions)
    report["summary"] = dict(schema=SCHEMA, profile=PROFILE,
        source_sha256=wire["source_sha256"], functions=len(functions),
        structurally_complete_functions=complete,
        partial_or_unsupported_functions=len(functions) - complete,
        structural_status=wire["status"],
        pending_obligation_count=len(obligations),
        families_with_artifacts=[family for family, present in
            (("program", native), ("first_order", fol or smt), ("higher_order", lean)) if present],
        per_function=functions[:16], omitted_function_summaries=max(0, len(functions)-16), **_FALSE)
    report["summary"].update(_compound_summary(contracts))
    report["summary"].update(_assertion_summary(assertions))
    report["report_sha256"] = _sha(report)
    return report


def validate_numerical_logic_report(report, source_text, *, path="source.py"):
    """Recompute every source binding, obligation and artifact, rejecting tampering."""
    if type(report) is not dict:
        raise NumericalLogicError("native numerical logic report required")
    _raw(report)
    rebuilt = formalize_numerical_source(source_text, path=path)
    if _raw(report) != _raw(rebuilt):
        raise NumericalLogicError("numerical logic source, interpretation or artifact differs")
    return rebuilt


__all__ = ["PROFILE", "SCHEMA", "NumericalLogicError", "describe_numerical_logic_profile",
           "formalize_numerical_source", "validate_numerical_logic_report"]
