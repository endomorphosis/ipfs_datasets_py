"""Bounded native ProgramIR operational semantics and declared Hoare contracts.

This version supports one straight-line, single-block integer/Boolean function.
Its Lean definitions execute assignments and preserve assertion failure versus
blocked assumptions. Contracts describe partial correctness; they are not
asserted theorems and a successful Lake build does not verify source behavior.
The caller must replay the complete native report against its original inputs.
"""
from __future__ import annotations

import hashlib
import json

from ...software_verification.program import ProgramIR
from ...software_verification.contracts import ProgramContract
from .native_family_lean_emitters import UnsupportedNativeLean, require, string

PROFILE = "native-program-straight-line-lean/v1"
TYPES = {"integer": "Int", "boolean": "Bool"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _effects(value):
    require(not any(value[name] for name in ("allocates", "deallocates", "raises", "performs_io", "nondeterministic", "synchronizes")),
            "program_external_heap_exception_effect_not_lowered")


class _Program:
    def __init__(self, payload):
        self.native = ProgramIR.from_dict(payload)
        require(self.native.to_dict() == payload, "native_program_exact_roundtrip_required")
        self.payload = payload
        require(not payload["metadata"], "program_metadata_requires_explicit_semantics_review")
        require(len(payload["functions"]) == 1, "one_native_function_required")
        require(len(payload["symbols"]) <= 64 and len(payload["expressions"]) <= 256 and len(payload["commands"]) <= 128,
                "bounded_program_fragment_required")
        self.function = payload["functions"][0]
        function = self.function
        require(function["return_type"] in TYPES, "integer_or_Boolean_return_required")
        require(not function["declared_exceptions"] and not function["exception_symbol_ids"], "program_exception_semantics_not_lowered")
        _effects(function["effects"])
        self.result_type = function["return_type"]
        self.result_symbol = function["result_symbol_id"]
        self.symbols = {row["symbol_id"]: row for row in payload["symbols"]}
        self.fields = {key: "v" + str(index) for index, key in enumerate(self.symbols)}
        visible = set(payload["global_symbol_ids"]) | set(function["parameter_symbol_ids"]) | set(function["local_symbol_ids"])
        if self.result_symbol: visible.add(self.result_symbol)
        require(set(self.symbols) == visible, "unscoped_program_symbol_not_lowered")
        for symbol in self.symbols.values():
            require(symbol["type_ref"] in TYPES and not symbol["attributes"], "unsupported_program_symbol_type_or_attributes")
            require(symbol["kind"] in ("global", "parameter", "local", "result"), "unsupported_program_symbol_kind")
        if self.result_symbol:
            require(self.symbols[self.result_symbol]["type_ref"] == self.result_type, "program_result_type_mismatch")
        self.expressions = {row["expression_id"]: row for row in payload["expressions"]}
        self.expr_names = {key: "expression_" + str(index) for index, key in enumerate(self.expressions)}
        self.entry_symbols = set(payload["global_symbol_ids"]) | set(function["parameter_symbol_ids"])
        self.reads = {}; self.special = {}; self.render_visits = 0
        for key in self.expressions: self._expression(key, "current", "initial", "returned", 0)
        cfg = function["cfg"]
        require(len(cfg["blocks"]) == 1 and not cfg["edges"] and not cfg["exceptional_exit_block_ids"],
                "single_block_straight_line_CFG_required")
        block = cfg["blocks"][0]
        require(cfg["entry_block_id"] == block["block_id"] and cfg["normal_exit_block_ids"] == [block["block_id"]],
                "single_normal_entry_exit_required")
        commands = {row["command_id"]: row for row in payload["commands"]}
        require(set(commands) == set(block["command_ids"]), "all_native_commands_must_be_executed_in_block")
        self.commands = [commands[key] for key in block["command_ids"]]
        require(self.commands and self.commands[-1]["kind"] == "return", "explicit_final_return_required")
        self.actual_reads = set(); self.actual_writes = set()
        initialized = set(payload["global_symbol_ids"]) | set(function["parameter_symbol_ids"])
        for index, command in enumerate(self.commands):
            require(not command["attributes"] and not command["undefined_behavior"], "command_attributes_or_undefined_behavior_not_lowered")
            _effects(command["effects"])
            kind = command["kind"]; ids = command["expression_ids"]; targets = command["target_symbol_ids"]
            require(command["evaluation_order"] == ids, "noncanonical_command_evaluation_order_not_lowered")
            require(kind in ("skip", "assign", "assume", "assert", "return"), "unsupported_native_command:" + kind)
            require((kind == "skip" and not ids and not targets) or
                    (kind != "skip" and len(ids) == 1 and len(targets) == (1 if kind == "assign" else 0)), "native_command_arity_not_supported")
            read = set().union(*(self.reads[key] for key in ids))
            require(read <= initialized, "program_read_before_initialization")
            require(not any(self.special[key] for key in ids), "old_or_result_expression_in_operational_body")
            require(read <= set(command["effects"]["reads"]), "actual_program_reads_exceed_declared_command_effects")
            require(set(targets) <= set(command["effects"]["writes"]), "actual_program_writes_exceed_declared_command_effects")
            require(set(command["effects"]["reads"]) <= set(function["effects"]["reads"]) and
                    set(command["effects"]["writes"]) <= set(function["effects"]["writes"]), "command_effects_exceed_function_effects")
            self.actual_reads.update(read); self.actual_writes.update(targets)
            if kind in ("assert", "assume"):
                require(self.expressions[ids[0]]["type_ref"] == "boolean", "Boolean_command_condition_required")
            elif kind == "assign":
                require(targets[0] != self.result_symbol and self.expressions[ids[0]]["type_ref"] == self.symbols[targets[0]]["type_ref"],
                        "assignment_type_or_result_target_mismatch")
                initialized.update(targets)
            elif kind == "return":
                require(index == len(self.commands) - 1 and self.expressions[ids[0]]["type_ref"] == self.result_type,
                        "typed_final_return_required")
        self.final_initialized = initialized

    def _expression(self, key, current, initial, returned, depth):
        self.render_visits += 1
        require(depth <= 64 and self.render_visits <= 16384, "bounded_native_expression_expansion_required")
        row = self.expressions[key]; kind = row["kind"]; operands = row["operand_ids"]
        require(row["type_ref"] in TYPES, "unsupported_native_expression_type")
        require(row["evaluation_order"] == operands, "noncanonical_operand_evaluation_order_not_lowered")
        if kind == "literal":
            require(set(row["attributes"]) == {"value"} and not row["operator"], "literal_value_only_required")
            value = row["attributes"]["value"]
            require(type(value) is (int if row["type_ref"] == "integer" else bool), "typed_native_literal_required")
            result = "(" + str(value) + " : Int)" if type(value) is int else str(value).lower()
            reads = set(); special = set()
        else:
            require(not row["attributes"], "opaque_expression_attributes_not_lowered")
            reads = set(); special = set()
            values = []
            for operand in operands:
                values.append(self._expression(operand, initial if kind == "old" else current, initial, returned, depth + 1))
                reads.update(self.reads[operand]); special.update(self.special[operand])
            types = [self.expressions[operand]["type_ref"] for operand in operands]
            operator = row["operator"]; symbols = row["symbol_ids"]
            if kind in ("symbol", "result"):
                require(not operands and not operator and len(symbols) == 1, "native_symbol_expression_shape")
                symbol = symbols[0]
                require(symbol in self.symbols and row["type_ref"] == self.symbols[symbol]["type_ref"], "native_symbol_expression_type")
                if kind == "result" or symbol == self.result_symbol:
                    require(symbol == self.result_symbol, "native_result_symbol_mismatch")
                    result = returned; special.add("result")
                else: result = current + "." + self.fields[symbol]; reads.add(symbol)
            else:
                require(not symbols, "compound_expression_extra_symbol_references")
                if kind == "old":
                    require(len(values) == 1 and not operator and types[0] == row["type_ref"] and "result" not in special,
                            "native_old_expression_shape")
                    require(reads <= self.entry_symbols, "old_expression_requires_initialized_entry_symbols")
                    result = values[0]; special.add("old")
                elif kind == "unary":
                    require(len(values) == 1 and ((operator == "not" and types == ["boolean"] and row["type_ref"] == "boolean") or
                            (operator in ("neg", "pos") and types == ["integer"] and row["type_ref"] == "integer")), "unsupported_typed_unary_operator")
                    result = "(" + {"not": "!", "neg": "-", "pos": "+"}[operator] + values[0] + ")" if operator != "pos" else values[0]
                elif kind == "binary":
                    require(len(values) == 2, "binary_expression_arity")
                    if operator in ("add", "sub", "mul"):
                        require(types == ["integer", "integer"] and row["type_ref"] == "integer", "integer_arithmetic_types_required")
                        result = "(" + values[0] + " " + {"add": "+", "sub": "-", "mul": "*"}[operator] + " " + values[1] + ")"
                    elif operator in ("and", "or"):
                        require(types == ["boolean", "boolean"] and row["type_ref"] == "boolean", "Boolean_connective_types_required")
                        result = "(" + values[0] + " " + {"and": "&&", "or": "||"}[operator] + " " + values[1] + ")"
                    else:
                        require(operator in ("eq", "ne", "lt", "le", "gt", "ge") and types[0] == types[1] and
                                row["type_ref"] == "boolean" and (operator in ("eq", "ne") or types == ["integer", "integer"]),
                                "unsupported_typed_binary_operator")
                        result = "(decide (" + values[0] + " " + {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}[operator] + " " + values[1] + "))"
                elif kind == "conditional":
                    require(len(values) == 3 and not operator and types[0] == "boolean" and types[1] == types[2] == row["type_ref"],
                            "typed_conditional_expression_required")
                    result = "(if " + values[0] + " then " + values[1] + " else " + values[2] + ")"
                else: raise UnsupportedNativeLean("unsupported_native_expression:" + kind)
        self.reads[key] = reads; self.special[key] = special
        return result

    def source(self):
        fields = ["  " + self.fields[key] + " : " + TYPES[row["type_ref"]] for key, row in self.symbols.items()]
        lines = ["set_option linter.unusedVariables false", "structure Store where", *fields, "  deriving DecidableEq", "",
                 "inductive Outcome where", "  | returned (store : Store) (value : " + TYPES[self.result_type] + ")",
                 "  | blocked", "  | assertionFailure", "  deriving DecidableEq"]
        default = "(0 : Int)" if self.result_type == "integer" else "false"
        for key, row in self.expressions.items():
            body = self._expression(key, "current", "initial", "returned", 0)
            lines.append("def " + self.expr_names[key] + " (initial current : Store) (returned : " + TYPES[self.result_type] + ") : " + TYPES[row["type_ref"]] + " := " + body)
        continuation = ""
        for command in reversed(self.commands):
            kind = command["kind"]
            value = self.expr_names[command["expression_ids"][0]] + " initial current " + default if command["expression_ids"] else ""
            if kind == "return": continuation = "Outcome.returned current (" + value + ")"
            elif kind == "assign": continuation = "let current := { current with " + self.fields[command["target_symbol_ids"][0]] + " := " + value + " };\n" + continuation
            elif kind in ("assert", "assume"):
                continuation = "if " + value + " then\n  (" + continuation.replace("\n", "\n  ") + ")\nelse Outcome." + ("assertionFailure" if kind == "assert" else "blocked")
        lines.append("def run (initial : Store) : Outcome :=\n  let current := initial;\n  " + continuation.replace("\n", "\n  "))
        for label, actual, declared in (("Reads", self.actual_reads, self.function["effects"]["reads"]),
                                        ("Writes", self.actual_writes, self.function["effects"]["writes"])):
            lines.append("def declared" + label + " (symbol : String) : Bool := [" + ", ".join(string(x) for x in declared) + "].contains symbol")
            lines.append("example : ([" + ", ".join(string(x) for x in sorted(actual)) + "] : List String).all declared" + label + " = true := by decide")
        return "\n\n".join(lines)

    def details(self):
        return {"validator": "ProgramIR.from_dict_exact_roundtrip_and_bounded_operational_lowering", "profile": PROFILE,
                "program_sha256": _digest(self.payload), "operators": [row["kind"] for row in self.commands],
                "actual_reads": sorted(self.actual_reads), "actual_writes": sorted(self.actual_writes),
                "assumptions": ["Integer means mathematical unbounded Int; Boolean means Bool.",
                    "Single-block execution preserves assignments, blocked assumptions, assertion failure, and return.",
                    "Native purity/effects are declared bounds; unknown purity is not promoted to pure.",
                    "Source maps and descriptive text remain evidence; the native typed expressions supply semantics.",
                    "A compiled operational definition is not evidence that the original source implements it."]}


def emit_program(payload):
    program = _Program(payload)
    return program.source(), program.details()


def emit_contract(payload, *, program_payload):
    program = _Program(program_payload)
    native = ProgramContract.from_dict(payload)
    require(native.to_dict() == payload, "native_contract_exact_roundtrip_required")
    native.validate_against(program.native)
    require(not payload["attributes"] and not payload["undefined_behavior"] and not payload["exceptional_postconditions"],
            "contract_extra_semantics_not_lowered")
    _effects(payload["effects"])
    frame = payload["frame"]
    require(frame["allows_all_reads"] or program.actual_reads <= set(frame["readable_symbol_ids"]), "actual_program_reads_exceed_contract_frame")
    require(frame["allows_all_writes"] or program.actual_writes <= set(frame["writable_symbol_ids"]), "actual_program_writes_exceed_contract_frame")
    default = "(0 : Int)" if program.result_type == "integer" else "false"
    initial_symbols = set(program_payload["global_symbol_ids"]) | set(program.function["parameter_symbol_ids"])
    def clauses(rows, post):
        conditions = []
        for row in rows:
            require(not row["attributes"] and not row["exception_type"], "contract_clause_extra_semantics_not_lowered")
            key = row["expression_id"]
            require(program.expressions[key]["type_ref"] == "boolean", "Boolean_contract_expression_required")
            if not post:
                require(not program.special[key] and program.reads[key] <= initial_symbols, "precondition_requires_initialized_entry_symbols")
            else:
                require(program.reads[key] <= program.final_initialized, "postcondition_reads_uninitialized_local")
            conditions.append("(" + program.expr_names[key] + " initial " + ("final returned" if post else "initial " + default) + " = true)")
        return " ∧ ".join(conditions) or "True"
    preserved = ["final." + field + " = initial." + field for key, field in program.fields.items()
                 if key != program.result_symbol and not frame["allows_all_writes"] and key not in frame["writable_symbol_ids"]]
    lines = [program.source(), "def precondition (initial : Store) : Prop := " + clauses(payload["preconditions"], False),
             "def postcondition (initial final : Store) (returned : " + TYPES[program.result_type] + ") : Prop := " + clauses(payload["postconditions"], True),
             "def frameCondition (initial final : Store) : Prop := " + (" ∧ ".join(preserved) or "True"),
             "def contract : Prop := ∀ initial, precondition initial →\n  match run initial with\n  | .returned final value => postcondition initial final value ∧ frameCondition initial final\n  | .blocked => True\n  | .assertionFailure => False"]
    details = program.details()
    details.update(validator="ProgramContract.validate_against_exact_paired_ProgramIR_and_operational_Hoare_lowering",
                   contract_sha256=_digest(payload), operators=details["operators"] + ["precondition", "postcondition", "frame", "partial_correctness"])
    details["assumptions"].append("The generated contract is a proposition, not an asserted or proved theorem; blocked assumptions use partial-correctness semantics.")
    return "\n\n".join(lines), details


def emit_projection(row, *, report=None):
    payload = row.get("payload")
    if row.get("logic_family") != "program" or not isinstance(payload, dict): raise NotImplementedError
    schema = payload.get("schema_version")
    if schema == "program-ir/v1": return emit_program(payload)
    if schema != "program-contract/v1": raise NotImplementedError
    require(isinstance(report, dict), "paired_program_report_required_for_contract")
    candidates = [item["payload"] for item in report.get("projections", ()) if item.get("logic_family") == "program"
                  and isinstance(item.get("payload"), dict) and item["payload"].get("schema_version") == "program-ir/v1"
                  and item.get("ready_for_training") is True]
    require(len(candidates) == 1, "one_ready_paired_native_program_required_for_contract")
    return emit_contract(payload, program_payload=candidates[0])
