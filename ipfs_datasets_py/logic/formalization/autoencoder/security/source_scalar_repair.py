"""Inert scalar operator proposals from an exact live bounded refutation.

The existing source qualifier owns the admitted Python fragment. This module
only enumerates a closed two-edit grammar over its single arithmetic operator;
it neither predicts a replacement ProgramIR nor evaluates a proposed repair.
Every proposed source still needs fresh inference, qualification and checking.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import io
import json
import tokenize

from .. import intent_code_effects_lake as gate
from . import source_program_binding_384 as source_owner
from . import source_program_binding_384_v2 as qualification

SCHEMA = "security-source-scalar-operator-repair/v1"
OPERATORS = {"+": ast.Add, "-": ast.Sub, "*": ast.Mult}
FALSE = dict(proof_authority=False, execution_authority=False,
    mutation_authority=False, completion_authority=False, admitted=False,
    source_executed=False, candidate_prediction_created=False,
    candidate_repaired=False, proposed_repairs_checked=False,
    repair_succeeded=False, source_semantics_verified=False,
    whole_program_semantics_verified=False, input_domains_inferred=False)
PRODUCERS = (gate, source_owner, qualification)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _positions(source):
    # The source owner already requires ASCII; AST byte columns and tokenize
    # character columns therefore agree. Never silently normalize Unicode.
    _require(source.isascii(), "qualified ASCII source required")
    starts, offset = [0], 0
    for line in source.splitlines(keepends=True):
        offset += len(line)
        starts.append(offset)

    def position(line, column):
        _require(type(line) is int and type(column) is int and
            1 <= line <= len(starts) and column >= 0, "source token position invalid")
        result = starts[line - 1] + column
        _require(result <= len(source), "source token outside original bytes")
        return result

    return position


def _edit(source, start, end, after):
    before = source[start:end]
    return dict(start_byte=start, end_byte=end, before=before, after=after,
        before_sha256=_sha(before.encode()), after_sha256=_sha(after.encode()))


def prepare_scalar_operator_repair(execution, rows, *, row_id):
    """Enumerate alternate arithmetic tokens for one live refuted row.

    ``rows`` is the complete, unchanged batch that produced ``execution``.
    Saved receipts, unissued handles, stale rows and non-refutations reject.
    An otherwise supported comparison returns an explicit unsupported result;
    no source/candidate is fabricated to fit the arithmetic repair grammar.
    """
    _require(type(row_id) is str and 0 < len(row_id) <= 256,
        "bounded exact refuted row identity required")
    receipt = gate.verify_intent_code_effects_lake(execution, rows)
    selected_inputs = [row for row in rows if row["id"] == row_id]
    selected_results = [row for row in receipt["rows"] if row["id"] == row_id]
    _require(len(selected_inputs) == len(selected_results) == 1,
        "selected row must occur once in the original live batch")
    original, checked = selected_inputs[0], selected_results[0]
    _require(receipt["backend_executed"] is True and checked["status"] == "passed"
        and checked["lake_status"] == "passed"
        and checked["finite_effects_kernel_checked"] is True
        and checked["counterexample_kernel_checked"] is True
        and checked["effect_status"] == "refuted"
        and checked["bounded_effects_satisfied"] is False,
        "live kernel-checked refutation required")
    contract = checked["contract"]
    _require(type(contract["enabled_case_count"]) is int and contract["enabled_case_count"] > 0
        and contract["counterexample_case_indices"], "nonvacuous counterexample required")
    for name in gate.FIELDS - {"id"}:
        _require(_raw(contract[name]) == _raw(original[name]),
            "refutation contract does not preserve exact original inputs")
    source = original["code_source_text"]
    qualified = qualification.qualify_source_candidate(source, original["code_candidate_ir"])
    _require(qualified["status"] == "qualified" and qualified["qualified"] is True,
        "original source and unchanged candidate must qualify")
    report = dict(schema=SCHEMA, status="unsupported", reason="arithmetic_operator_required",
        row_id=row_id, original_row=deepcopy(original), original_row_sha256=_sha(_raw(original)),
        input_rows_sha256=receipt["input_sha256"], refutation_receipt_sha256=_sha(_raw(receipt)),
        refutation_lean_source_sha256=receipt["lean_source_sha256"],
        original_source_sha256=_sha(source.encode()),
        original_candidate_sha256=_sha(_raw(original["code_candidate_ir"])),
        intent_source_sha256=_sha(original["intent_source_text"].encode()),
        intent_candidate_sha256=_sha(_raw(original["intent_candidate_ir"])),
        input_domains_sha256=_sha(_raw(original["input_domains"])),
        association_sha256=_sha(_raw(original["association"])),
        source_qualification=qualified, original_effect_status="refuted",
        original_refutation_kernel_checked=True,
        enabled_case_count=contract["enabled_case_count"],
        counterexample_case_indices=deepcopy(contract["counterexample_case_indices"]),
        original_case_count=len(contract["cases"]), proposals=[], proposal_count=0,
        allowed_operators=list(OPERATORS), operand_order_preserved=True,
        scope="selected refuted action and exact finite domains; arithmetic operator-only proposals",
        assumptions=list(qualified["assumptions"]),
        limitations=["operator-only edits cannot reorder operands or repair arbitrary Python",
            "proposals have no predicted candidate and require fresh source inference and native checks",
            "a finite refutation does not authorize changing the source or the instruction"],
        provider_calls=0, model_inference_calls=0, training_steps=0,
        source_writes=0, checker_calls=0, **FALSE)
    function, expression, operands, temporary, symbol, _, result_type = source_owner._guard(source)
    if type(expression) is not ast.BinOp or symbol not in OPERATORS or result_type != "integer":
        return report
    position = _positions(source)
    expression_start = position(expression.lineno, expression.col_offset)
    expression_end = position(expression.end_lineno, expression.end_col_offset)
    left_end = position(operands[0].end_lineno, operands[0].end_col_offset)
    right_start = position(operands[1].lineno, operands[1].col_offset)
    tokens = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.OP and token.string in OPERATORS:
            start, end = position(*token.start), position(*token.end)
            if left_end <= start < end <= right_start:
                tokens.append((token, start, end))
    _require(len(tokens) == 1 and tokens[0][0].string == symbol,
        "one exact arithmetic operator token required")
    _, start, end = tokens[0]
    _require(source[start:end] == symbol, "operator token and source bytes differ")
    for replacement, operator_type in OPERATORS.items():
        if replacement == symbol:
            continue
        after_source = source[:start] + replacement + source[end:]
        new_function, new_expression, new_operands, new_temporary, new_symbol, _, new_type = source_owner._guard(after_source)
        expected_function = deepcopy(function)
        expected_expressions = [node for node in ast.walk(expected_function) if type(node) is ast.BinOp]
        _require(len(expected_expressions) == 1, "one arithmetic AST node required")
        expected_expressions[0].op = operator_type()
        _require(ast.dump(new_function, include_attributes=False) ==
            ast.dump(expected_function, include_attributes=False)
            and [node.id for node in new_operands] == [node.id for node in operands]
            and temporary == new_temporary and new_symbol == replacement and new_type == result_type,
            "proposal changes more than the declared AST operator")
        _require(type(new_expression) is ast.BinOp, "proposal left the arithmetic source fragment")
        after_expression = source[expression_start:start] + replacement + source[end:expression_end]
        proposal = dict(operator_before=symbol, operator_after=replacement,
            before_source_sha256=report["original_source_sha256"],
            after_source_sha256=_sha(after_source.encode()), source_text=after_source,
            token_edit=_edit(source, start, end, replacement),
            expression_edit=_edit(source, expression_start, expression_end, after_expression),
            operand_names=[node.id for node in operands], original_row_sha256=report["original_row_sha256"],
            refutation_receipt_sha256=report["refutation_receipt_sha256"], **FALSE)
        proposal["id"] = "scalar-operator:" + _sha(_raw(proposal))
        report["proposals"].append(proposal)
    report.update(status="proposed", reason=None, proposal_count=len(report["proposals"]))
    _require(report["proposal_count"] == 2, "closed alternate operator population required")
    return report


def verify_scalar_operator_repair(report, execution, rows, *, row_id):
    """Replay the live refutation, original bindings, and every proposed byte."""
    expected = prepare_scalar_operator_repair(execution, rows, row_id=row_id)
    _require(_raw(report) == _raw(expected), "scalar operator repair proposal does not match exact replay")
    return expected


__all__ = ["prepare_scalar_operator_repair", "verify_scalar_operator_repair"]
