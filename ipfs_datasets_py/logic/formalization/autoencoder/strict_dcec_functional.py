"""Independent complete parsing of the ground rich-Intent DCEC wire fragment.

This does not loosen the generic DCEC qualification gate. It recognizes only
the functional spellings emitted by the existing rich Intent owner and checks
their entire native AST, typed semantic symbols and ground agency binding.
No infix rewriting, modal axioms, observed events or proof authority is added.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

from . import family_training as core
from ...autoformal import tree_pin
from ...CEC.native import dcec_core, dcec_integration, dcec_cleaning, dcec_parsing, dcec_prototypes
from ...intent_ir.formalize import modal_projections

SCHEMA = "strict-rich-dcec-functional/v1"
MAX_BYTES = 16384
MAX_TOKENS = 2048
MAX_DEPTH = 32
_SYMBOL = re.compile(r"S[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[(),]")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_PAYLOAD_FIELDS = {"source", "ast", "ast_sha256", "symbols", "slot_declarations_sha256",
    "native_parse_passed", "native_structure_checked", "native_reparse_passed",
    "backend_proof_executed", "typed_slot_specializations_applied"}
FALSE = {"qualified": False, "admitted": False, "formalized": False,
    "proof_authority": False, "execution_authority": False, "source_semantics_verified": False,
    "lake_executed": False, "backend_executed": False, "formula_rewritten": False}
PRODUCERS = (sys.modules[__name__], core, tree_pin, dcec_core, dcec_integration,
             dcec_cleaning, dcec_parsing, dcec_prototypes, modal_projections)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _bounded_json(value):
    nodes = 0
    text_characters = 0

    def visit(item, depth):
        nonlocal nodes, text_characters
        nodes += 1
        _require(nodes <= 8192 and depth <= 48, "bounded rich DCEC payload required")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "string JSON keys required")
            text_characters += sum(len(key) for key in item)
            for child in item.values():
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        else:
            _require(type(item) in (str, int, bool, type(None)), "exact inert JSON payload required")
            if type(item) is str:
                text_characters += len(item)
        _require(text_characters <= 131072, "rich DCEC payload string bound exceeded")

    visit(value, 0)
    raw = _wire(value)
    _require(len(raw) <= 131072, "rich DCEC payload exceeds byte bound")
    return raw


def _pins():
    root = Path(__file__).resolve().parents[4]
    _require(Path(tree_pin.workspace_root()).resolve() == root, "rich DCEC canonical tree differs")
    _require(all(root in Path(module.__file__).resolve().parents for module in PRODUCERS),
             "rich DCEC owner outside canonical tree")
    return {name: digest for module in PRODUCERS for name, digest in core._pin(module).items()}


def _parse(text):
    """Closed tokenizer and recursive descent, independent of native parsers."""
    _require(type(text) is str and 0 < len(text.encode()) <= MAX_BYTES, "bounded rich DCEC formula required")
    tokens, offset = [], 0
    while offset < len(text):
        if text[offset] in " \t\r\n":
            offset += 1
            continue
        match = _TOKEN.match(text, offset)
        _require(match is not None, "unsupported rich DCEC token at " + str(offset))
        tokens.append(match.group())
        _require(len(tokens) <= MAX_TOKENS, "rich DCEC token bound exceeded")
        offset = match.end()
    position = 0

    def expression(depth):
        nonlocal position
        _require(depth <= MAX_DEPTH and position < len(tokens), "rich DCEC depth or incomplete input")
        name = tokens[position]
        _require(name not in ("(", ")", ","), "rich DCEC identifier required")
        position += 1
        arguments = None
        if position < len(tokens) and tokens[position] == "(":
            position += 1
            arguments = [expression(depth + 1)]
            while position < len(tokens) and tokens[position] == ",":
                position += 1
                arguments.append(expression(depth + 1))
            _require(position < len(tokens) and tokens[position] == ")", "unbalanced rich DCEC input")
            position += 1
        return name, arguments

    result = expression(0)
    _require(position == len(tokens), "unconsumed rich DCEC formula suffix")
    return result


def _symbol_table(rows):
    _require(type(rows) is list and 1 <= len(rows) <= 32, "bounded rich semantic symbol table required")
    table = {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"role", "value", "symbol"}, "closed rich symbol row required")
        role, value, symbol = row["role"], row["value"], row["symbol"]
        _require(type(symbol) is str and _SYMBOL.fullmatch(symbol) is not None and symbol not in table,
                 "unique generated rich symbol required")
        if role == "predicate":
            _require(type(value) is str and any(value.startswith(prefix) and _WORD.fullmatch(value[len(prefix):])
                     for prefix in ("action:", "property:")), "rich action/property predicate required")
        elif role == "slot":
            _require(type(value) is dict and set(value) == {"surface", "sort"}
                and type(value["surface"]) is str and 0 < len(value["surface"]) <= 160
                and type(value["sort"]) is str and value["sort"] in {"Agent", "Entity"},
                "closed typed rich referent required")
        else:
            raise ValueError("unknown rich semantic symbol role")
        _require(symbol == "S" + _digest([role, value]), "rich symbol is not bound to its exact role/value")
        table[symbol] = row
    return table


def _independent_ast(tree, table):
    """Build a full expected native snapshot without using native constructors."""
    used = set()

    def meaning(symbol, role):
        _require(type(symbol) is str and symbol in table and table[symbol]["role"] == role,
                 "undeclared rich symbol or wrong semantic role")
        used.add(symbol)
        return table[symbol]["value"]

    def sort(name):
        return {"node_type": "Sort", "name": name, "parent": None}

    def term(node, source_sort, native_sort="Object"):
        name, arguments = node
        _require(arguments is None and meaning(name, "slot")["sort"] == source_sort,
                 "ground rich term/source sort required; functions and free variables refused")
        return {"node_type": "FunctionTerm", "arguments": [], "function": {
            "node_type": "Function", "name": name, "argument_sorts": [], "return_sort": sort(native_sort)}}

    def predicate(node, prefix):
        name, arguments = node
        value = meaning(name, "predicate")
        sorts = ("Agent", "Entity") if prefix == "action:" else ("Entity",)
        _require(value.startswith(prefix) and type(arguments) is list and len(arguments) == len(sorts),
                 "rich predicate category or arity differs")
        return {"node_type": "AtomicFormula", "predicate": {"node_type": "Predicate", "name": name,
            "argument_sorts": [sort("Object") for _ in sorts]},
            "arguments": [term(arg, expected) for arg, expected in zip(arguments, sorts)]}

    def modal(node):
        name, arguments = node
        _require(name in {"O", "P", "F", "I"} and type(arguments) is list,
                 "rich modal atom required; unknown operators are not predicates")
        if name == "I":
            _require(len(arguments) == 2, "rich intention requires exact agent and formula arity")
            agent = term(arguments[0], "Agent", "agent")
            body = predicate(arguments[1], "action:")
            _require(arguments[1][1][0] == arguments[0], "intention agent differs from action actor")
            return {"node_type": "CognitiveFormula", "operator": {"enum": "CognitiveOperator", "value": "I"},
                "agent": agent, "formula": body}
        _require(len(arguments) == 1, "rich deontic operator requires one complete formula; no context or agent loss")
        return {"node_type": "DeonticFormula", "operator": {"enum": "DeonticOperator", "value": name},
                "agent": None, "formula": predicate(arguments[0], "action:")}

    def connective(operator, children):
        return {"node_type": "ConnectiveFormula", "connective": {"enum": "LogicalConnective", "value": operator},
                "formulas": children}

    name, arguments = tree
    if name in {"O", "P", "F", "I"}:
        ast = modal(tree)
    elif name in {"and", "or"}:
        _require(type(arguments) is list and len(arguments) == 2, "exactly two complete rich modal branches required")
        ast = connective({"and": "∧", "or": "∨"}[name], [modal(child) for child in arguments])
    elif name == "implies":
        _require(type(arguments) is list and len(arguments) == 2, "exact guard and modal consequent required")
        guard = arguments[0]
        if guard[0] == "not":
            _require(type(guard[1]) is list and len(guard[1]) == 1, "exact unary rich guard negation required")
            left = connective("¬", [predicate(guard[1][0], "property:")])
        else:
            left = predicate(guard, "property:")
        ast = connective("→", [left, modal(arguments[1])])
    else:
        raise ValueError("unsupported complete rich DCEC production")
    _require(used == set(table), "rich formula omitted a semantic symbol declaration")
    return ast


def validate_rich_dcec_payload(payload):
    """Validate one exact existing rich DCEC payload, without executing Lake."""
    original = _bounded_json(payload)
    _require(type(payload) is dict and set(payload) == _PAYLOAD_FIELDS, "closed rich DCEC payload required")
    for key in ("native_parse_passed", "native_structure_checked", "native_reparse_passed"):
        _require(payload[key] is True, "original rich native checks must have passed")
    for key in ("backend_proof_executed", "typed_slot_specializations_applied"):
        _require(payload[key] is False, "unexpected rich proof authority or typed specialization")
    _require(type(payload["slot_declarations_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", payload["slot_declarations_sha256"]) is not None,
        "rich slot declarations digest required; full source replay is an outer gate")
    pins = _pins()
    tree_pin.require_workspace_logic_tree()
    table = _symbol_table(payload["symbols"])
    expected = _independent_ast(_parse(payload["source"]), table)
    _require(_wire(expected) == _wire(payload["ast"]) and _digest(expected) == payload["ast_sha256"],
             "independent rich functional parse differs from complete declared native AST")
    native = dcec_integration.parse_dcec_string(payload["source"])
    _require(native is not None and not native.get_free_variables(), "native rich formula must be closed and ground")
    actual = modal_projections._ast(native)
    _require(_wire(actual) == _wire(expected), "native DCEC parser changed complete independent AST, sorts or agency")
    replay = dcec_integration.parse_dcec_string(payload["source"])
    _require(replay is not None and _wire(modal_projections._ast(replay)) == _wire(expected),
             "native rich DCEC reparse changed AST")
    _require(_pins() == pins and _bounded_json(payload) == original, "rich DCEC producer or payload changed")
    result = {"schema": SCHEMA, "passed": True, "source": payload["source"],
        "source_sha256": hashlib.sha256(payload["source"].encode()).hexdigest(),
        "native_ast": deepcopy(actual), "independent_ast": expected,
        "native_ast_sha256": _digest(actual), "payload_sha256": hashlib.sha256(original).hexdigest(),
        "symbol_table_sha256": _digest(payload["symbols"]), "producer_pins": pins,
        "full_input_consumed": True, "native_parse_passed": True, "native_reparse_passed": True,
        "independent_structure_equal": True, "free_variables": [], "ground_only": True,
        "source_candidate_replay_required": True,
        "scope": "ground_rich_deontic_and_intention_formulas_not_full_DCEC_or_timed_events", **FALSE}
    result["receipt_sha256"] = _digest(result)
    return result


__all__ = ["validate_rich_dcec_payload", "PRODUCERS"]
