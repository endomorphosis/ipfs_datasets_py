"""Reuse native ProgramIR expression typing for explicit interpretation evidence.

The carrier is deliberately a pure, return-true function over global typed
symbols. Its function body supplies no source-program semantics and is never
emitted as a proof. Only caller-selected, natively checked expression DAG roots
are rendered. The fixed carrier shape prevents silently discarding commands.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import native_program_lean as program
from . import native_family_lean_emitters as lean
from ...software_verification import program as program_types

PROFILE = "native-ProgramIR-typed-interpretation-expressions/v1"
PRODUCERS = (program, program_types, lean)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def evidence_strings(name, value):
    """Keep all evidence as bounded chunks rather than truncating a declaration."""
    lean.require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is not None,
                 "safe_interpretation_evidence_identifier_required")
    text = canonical(value)
    chunks = [text[index:index + 8192] for index in range(0, len(text), 8192)]
    return "def " + name + " : List String := [" + ", ".join(lean.string(chunk) for chunk in chunks) + "]"


def make_carrier(symbols, expressions, *, sources):
    """Wrap explicitly supplied native expressions without inferring any roots."""
    mapped = {"source_ref_ids": tuple(source.ref_id for source in sources)}
    prefix = "interpretation:carrier:"
    truth = program_types.ProgramExpression(prefix + "true", "literal", "boolean",
        attributes={"value": True}, **mapped)
    command = program_types.ProgramCommand(prefix + "return", "return",
        expression_ids=(truth.expression_id,), evaluation_order=(truth.expression_id,), **mapped)
    block = program_types.BasicBlock(prefix + "block", (command.command_id,), **mapped)
    cfg = program_types.ControlFlowGraph(prefix + "cfg", block.block_id, (block,), (), (block.block_id,))
    function = program_types.ProgramFunction(prefix + "function", "InterpretationExpressionCarrier", cfg,
        return_type="boolean", purity="pure", **mapped)
    value = program_types.ProgramIR(tuple(sources), (), tuple(symbols), (*expressions, truth),
        (command,), (function,), global_symbol_ids=tuple(symbol.symbol_id for symbol in symbols)).to_dict()
    TypedExpressions(value)
    return value


class TypedExpressions:
    """Exact ProgramIR carrier, with the existing expression renderer underneath."""

    def __init__(self, payload):
        lean.require(type(payload) is dict and len(canonical(payload).encode()) <= 262144,
                     "bounded_typed_interpretation_expression_carrier_required")
        model = program._Program(payload)
        function = model.function
        lean.require(not function["parameter_symbol_ids"] and not function["local_symbol_ids"]
            and not function["result_symbol_id"] and function["return_type"] == "boolean"
            and function["purity"] == "pure", "typed_interpretation_requires_pure_global_Boolean_carrier")
        lean.require(set(payload["global_symbol_ids"]) == set(model.symbols)
            and all(row["kind"] == "global" for row in model.symbols.values()),
            "typed_interpretation_symbols_must_all_be_explicit_globals")
        lean.require(not function["effects"]["reads"] and not function["effects"]["writes"]
            and len(model.commands) == 1 and model.commands[0]["kind"] == "return",
            "typed_interpretation_carrier_body_must_have_no_operational_effects")
        returned = model.expressions[model.commands[0]["expression_ids"][0]]
        lean.require(returned["kind"] == "literal" and returned["type_ref"] == "boolean"
            and returned["attributes"] == {"value": True},
            "typed_interpretation_carrier_body_must_return_literal_true")
        lean.require(not model.actual_reads and not model.actual_writes,
            "typed_interpretation_carrier_cannot_execute_symbol_accesses")
        self._model = model
        self.payload = json.loads(canonical(payload))
        self.sha256 = digest(payload)
        self.fields = dict(model.fields)
        self.types = {key: row["type_ref"] for key, row in model.expressions.items()}
        self.symbol_types = {key: row["type_ref"] for key, row in model.symbols.items()}
        self.reads = {key: frozenset(value) for key, value in model.reads.items()}
        self.special = {key: frozenset(value) for key, value in model.special.items()}

    def require_root(self, key, expected_type, *, allow_old=False):
        lean.require(type(key) is str and self.types.get(key) == expected_type,
                     "typed_interpretation_expression_root_type_mismatch")
        lean.require(not (self.special[key] - ({"old"} if allow_old else set())),
                     "typed_interpretation_expression_time_scope_mismatch")
        return key

    def render(self, expression_id, *, current="after", initial="before"):
        lean.require(expression_id in self.types and "result" not in self.special[expression_id],
                     "known_interpretation_expression_without_result_required")
        for value in (current, initial):
            lean.require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", value) is not None,
                         "safe_interpretation_store_name_required")
        self._model.render_visits = 0
        return self._model._expression(expression_id, current, initial, "false", 0)

    def store_declaration(self, name="Store"):
        lean.require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is not None,
                     "safe_interpretation_store_identifier_required")
        fields = ["  " + self.fields[key] + " : " + program.TYPES[kind]
                  for key, kind in self.symbol_types.items()]
        return "\n".join(["structure " + name + " where", *fields, "  deriving DecidableEq, Repr"])


__all__ = ["TypedExpressions", "PROFILE", "PRODUCERS", "canonical", "digest", "evidence_strings", "make_carrier"]
