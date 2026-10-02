"""Expanded pure-control-flow source grammar, forked without changing v1.

Bounded source observations and compositional candidate construction.

Syntax topology, identifier bindings and literal values are deterministic source
observations. Production choices are supplied separately by a learned decoder.
The builder never repairs a predicted production using the parsed source label.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import tokenize

from ..source_screening import _contains_secret, SourceSecretError

SCHEMA = "security-source-production-grammar@2"
PRODUCTIONS = ("integer", "string", "name", "add", "sub", "mul", "pos", "neg", "not",
    "in", "not_in", "eq", "or", "and", "call", "title", "lower", "upper", "casefold", "replace",
    "assign", "return", "if_raise", "boolean", "none", "ne", "lt", "le", "gt", "ge", "if_expr", "if_else")
SURFACE_TOKENS = ("+", "-", "*", ".", ",", "=", ":", "==",
    "in", "not", "or", "and", "return", "if", "raise", "title", "lower", "upper", "casefold", "replace", "True", "False", "None", "!=", "<", "<=", ">", ">=", "else")
FEATURES = tuple("surface:" + token for token in SURFACE_TOKENS) + (
    "name_tokens", "number_tokens", "string_tokens", "child_count", "word_count", "bias")
MAX_SOURCE_BYTES = 65_536
MAX_NODES = 256
MAX_DEPTH = 32
_BINARY = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul"}
_UNARY = {ast.UAdd: "pos", ast.USub: "neg", ast.Not: "not"}
_COMPARE = {ast.In: "in", ast.NotIn: "not_in", ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge"}
_BOOL = {ast.Or: "or", ast.And: "and"}
_METHODS = {"title", "lower", "upper", "casefold", "replace"}


class UnsupportedFormulaSource(ValueError):
    pass


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _surface_features(shell: str, arity: int):
    counts = {token: 0 for token in SURFACE_TOKENS}
    names = numbers = strings = words = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(shell).readline):
            if token.type == tokenize.NAME:
                names += 1
                words += 1
            elif token.type == tokenize.NUMBER:
                numbers += 1
            elif token.type == tokenize.STRING:
                strings += 1
            if token.type in (tokenize.NAME, tokenize.OP) and token.string in counts:
                counts[token.string] += 1
    except (tokenize.TokenError, IndentationError):
        # Child masking can leave an incomplete shell; already emitted tokens
        # still describe exact source lexemes. No AST production enters here.
        pass
    return [float(min(counts[token], 4)) for token in SURFACE_TOKENS] + [
        float(min(names, 4)), float(min(numbers, 4)), float(min(strings, 4)),
        float(arity), float(min(words, 4)), 1.0]


def parse_formula_source(source_bytes: bytes) -> dict:
    """Parse one explicit modeling unit; produce observations and teacher labels.

    Teacher labels are used for training and independent post-decode checking.
    The numeric predictor receives only ``features`` and source ``shell`` text.
    """
    if type(source_bytes) is not bytes or not 0 < len(source_bytes) <= MAX_SOURCE_BYTES:
        raise UnsupportedFormulaSource("bounded nonempty source bytes required")
    if _contains_secret(source_bytes):
        raise SourceSecretError("formula source refused by shared source screen")
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise UnsupportedFormulaSource("UTF-8 modeling unit required") from exc
    if any(ord(char) < 32 and char not in "\n\t" or ord(char) == 127 for char in text):
        raise UnsupportedFormulaSource("unsupported source controls")
    try:
        tree = ast.parse(text, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise UnsupportedFormulaSource("complete Python function required") from exc
    if len(tree.body) != 1 or type(tree.body[0]) is not ast.FunctionDef or tree.type_ignores:
        raise UnsupportedFormulaSource("one plain function required")
    function = tree.body[0]
    args = function.args
    if (function.returns or function.type_comment or getattr(function, "type_params", ())
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults or args.kw_defaults
            or any(arg.annotation or arg.type_comment for arg in args.args)):
        raise UnsupportedFormulaSource("annotations and non-simple parameters unsupported")
    names = [arg.arg for arg in args.args]
    if len(set(names)) != len(names) or any(not name.isidentifier() for name in names):
        raise UnsupportedFormulaSource("distinct bound parameters required")
    defined = set(names)
    pending = [(tree, 0)]
    node_count = 0
    while pending:
        item, depth = pending.pop()
        node_count += 1
        if node_count > 1024 or depth > MAX_DEPTH:
            raise UnsupportedFormulaSource("complete source AST resource bound")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(item))
    statements = function.body
    docstring = None
    if statements and type(statements[0]) is ast.Expr and type(statements[0].value) is ast.Constant and type(statements[0].value.value) is str:
        docstring = statements[0].value.value
        if len(docstring) > 8192:
            raise UnsupportedFormulaSource("docstring scaffold bound")
        statements = statements[1:]
    scaffolding = {"decorators": [ast.unparse(item) for item in function.decorator_list],
        "docstring": docstring, "semantic_status": "opaque source scaffold; not learned or executed"}
    lines = source_bytes.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    rows = []

    def bounds(node):
        return offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset

    def emit(node, production, children, binding):
        if len(rows) >= MAX_NODES:
            raise UnsupportedFormulaSource("production node bound exceeded")
        start, stop = bounds(node)
        shell = bytearray(source_bytes[start:stop])
        for child in children:
            row = rows[child]
            for index in range(max(start, row["start_byte"]), min(stop, row["end_byte"])):
                if shell[index - start] not in (10, 9):
                    shell[index - start] = 32
        surface = bytes(shell).decode("utf-8").strip()
        index = len(rows)
        rows.append({"node_id": index, "children": children, "binding": binding,
            "start_byte": start, "end_byte": stop, "source_span_sha256": _sha(source_bytes[start:stop]),
            "shell": surface, "features": _surface_features(surface, len(children)), "teacher_production": production})
        return index

    def expr(node, depth=0):
        if depth > MAX_DEPTH:
            raise UnsupportedFormulaSource("expression depth bound exceeded")
        binding, children = {}, []
        if type(node) is ast.Name:
            if node.id not in defined:
                raise UnsupportedFormulaSource("unbound expression name")
            production, binding = "name", {"name": node.id}
        elif type(node) is ast.Constant and type(node.value) in (int, str, bool, type(None)):
            if type(node.value) is int and node.value.bit_length() > 64 or type(node.value) is str and len(node.value) > 128:
                raise UnsupportedFormulaSource("literal bound exceeded")
            production = {int: "integer", str: "string", bool: "boolean", type(None): "none"}[type(node.value)]
            binding = {"value": node.value}
        elif type(node) is ast.IfExp:
            production = "if_expr"
            children = [expr(node.test, depth + 1), expr(node.body, depth + 1), expr(node.orelse, depth + 1)]
        elif type(node) is ast.BinOp and type(node.op) in _BINARY:
            production = _BINARY[type(node.op)]
            children = [expr(node.left, depth + 1), expr(node.right, depth + 1)]
        elif type(node) is ast.UnaryOp and type(node.op) in _UNARY:
            production = _UNARY[type(node.op)]
            children = [expr(node.operand, depth + 1)]
        elif type(node) is ast.Compare and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
            production = _COMPARE[type(node.ops[0])]
            children = [expr(node.left, depth + 1), expr(node.comparators[0], depth + 1)]
        elif type(node) is ast.BoolOp and type(node.op) in _BOOL and 2 <= len(node.values) <= 4:
            production = _BOOL[type(node.op)]
            children = [expr(child, depth + 1) for child in node.values]
        elif type(node) is ast.Call and not node.keywords:
            if type(node.func) is ast.Name and 1 <= len(node.args) <= 3:
                if node.func.id in defined:
                    raise UnsupportedFormulaSource("callable parameter or local unsupported")
                production, binding = "call", {"callee": node.func.id}
                children = [expr(arg, depth + 1) for arg in node.args]
            elif type(node.func) is ast.Attribute and node.func.attr in _METHODS:
                production = node.func.attr
                if len(node.args) != (2 if production == "replace" else 0):
                    raise UnsupportedFormulaSource("method arity unsupported")
                children = [expr(node.func.value, depth + 1), *(expr(arg, depth + 1) for arg in node.args)]
            else:
                raise UnsupportedFormulaSource("call shape unsupported")
        else:
            raise UnsupportedFormulaSource("expression outside learned grammar: " + type(node).__name__)
        return emit(node, production, children, binding)

    def block(items, environment, *, terminal_required):
        nonlocal defined
        saved = defined
        defined = set(environment)
        roots = []
        terminated = False
        try:
            for statement in items:
                if terminated:
                    raise UnsupportedFormulaSource("unreachable statements after unconditional return")
                if type(statement) is ast.Assign and len(statement.targets) == 1 and type(statement.targets[0]) is ast.Name:
                    name = statement.targets[0].id
                    if statement.type_comment or name in defined:
                        raise UnsupportedFormulaSource("only fresh unannotated local assignment supported")
                    children = [expr(statement.value)]
                    roots.append(emit(statement, "assign", children, {"target": name}))
                    defined.add(name)
                elif type(statement) is ast.Return and statement.value is not None:
                    roots.append(emit(statement, "return", [expr(statement.value)], {}))
                    terminated = True
                elif type(statement) is ast.If:
                    # Keep the previous explicit error-guard syntax as a syntax-only
                    # candidate. The pure typed projector independently rejects it.
                    raised = statement.body[0] if len(statement.body) == 1 else None
                    if type(raised) is ast.Raise and not statement.orelse:
                        if (raised.cause is not None or type(raised.exc) is not ast.Call
                                or type(raised.exc.func) is not ast.Name or raised.exc.func.id != "ValueError"
                                or raised.exc.keywords or len(raised.exc.args) > 1 or "ValueError" in defined
                                or any(type(arg) is not ast.Constant or type(arg.value) is not str or len(arg.value) > 128 for arg in raised.exc.args)):
                            raise UnsupportedFormulaSource("only explicit reviewed-error guard shape supported")
                        roots.append(emit(statement, "if_raise", [expr(statement.test)],
                            {"message": raised.exc.args[0].value if raised.exc.args else None}))
                    else:
                        condition = expr(statement.test)
                        then_roots, then_terminal = block(statement.body, defined, terminal_required=True)
                        else_roots, else_terminal = block(statement.orelse, defined, terminal_required=bool(statement.orelse))
                        roots.append(emit(statement, "if_else", [condition, *then_roots, *else_roots],
                            {"body_count": len(then_roots), "else_count": len(else_roots)}))
                        terminated = then_terminal and else_terminal
                else:
                    raise UnsupportedFormulaSource("statement outside learned grammar: " + type(statement).__name__)
            if terminal_required and not terminated:
                raise UnsupportedFormulaSource("every supported block must end in a value return or total conditional")
            return roots, terminated
        finally:
            defined = saved

    roots, _ = block(statements, defined, terminal_required=True)
    return {"schema": SCHEMA, "source_sha256": _sha(source_bytes), "function": function.name,
        "parameters": names, "roots": roots, "nodes": rows, "scaffolding": scaffolding,
        "source_ast": ast.dump(tree, include_attributes=False), "assumptions": [
            "topology, names, literal values and external callee bindings are supplied by exact source parsing",
            "learned heads select productions; no source execution or inferred security specification",
            "native type/semantic obligations remain independently checked"]}


def compose_candidate(observed, productions):
    """Build a distinct candidate AST exclusively from supplied productions."""
    if len(productions) != len(observed["nodes"]):
        raise ValueError("one learned production per source observation required")
    values = []
    for row, production in zip(observed["nodes"], productions):
        children = [values[index] for index in row["children"]]
        binding = row["binding"]
        arity = len(children)
        if production == "name" and arity == 0 and set(binding) == {"name"}:
            value = ast.Name(id=binding["name"], ctx=ast.Load())
        elif production in {"integer", "string", "boolean", "none"} and arity == 0 and set(binding) == {"value"}:
            if type(binding["value"]) is not {"integer": int, "string": str, "boolean": bool, "none": type(None)}[production]:
                raise ValueError("predicted literal production disagrees with source binding")
            value = ast.Constant(value=binding["value"])
        elif production == "if_expr" and arity == 3 and not binding:
            value = ast.IfExp(test=children[0], body=children[1], orelse=children[2])
        elif production == "if_else" and set(binding) == {"body_count", "else_count"}:
            count, other = binding["body_count"], binding["else_count"]
            if type(count) is not int or type(other) is not int or count < 1 or other < 0 or arity != 1 + count + other:
                raise ValueError("predicted conditional branch topology differs")
            value = ast.If(test=children[0], body=children[1:1+count], orelse=children[1+count:])
        elif production in _BINARY.values() and arity == 2 and not binding:
            value = ast.BinOp(left=children[0], op=next(cls() for cls, name in _BINARY.items() if name == production), right=children[1])
        elif production in _UNARY.values() and arity == 1 and not binding:
            value = ast.UnaryOp(op=next(cls() for cls, name in _UNARY.items() if name == production), operand=children[0])
        elif production in _COMPARE.values() and arity == 2 and not binding:
            value = ast.Compare(left=children[0], ops=[next(cls() for cls, name in _COMPARE.items() if name == production)], comparators=[children[1]])
        elif production in _BOOL.values() and 2 <= arity <= 4 and not binding:
            value = ast.BoolOp(op=next(cls() for cls, name in _BOOL.items() if name == production), values=children)
        elif production == "call" and 1 <= arity <= 3 and set(binding) == {"callee"}:
            value = ast.Call(func=ast.Name(id=binding["callee"], ctx=ast.Load()), args=children, keywords=[])
        elif production in _METHODS and arity == (3 if production == "replace" else 1) and not binding:
            value = ast.Call(func=ast.Attribute(value=children[0], attr=production, ctx=ast.Load()), args=children[1:], keywords=[])
        elif production == "assign" and arity == 1 and set(binding) == {"target"}:
            value = ast.Assign(targets=[ast.Name(id=binding["target"], ctx=ast.Store())], value=children[0])
        elif production == "return" and arity == 1 and not binding:
            value = ast.Return(value=children[0])
        elif production == "if_raise" and arity == 1 and set(binding) == {"message"}:
            value = ast.If(test=children[0], body=[ast.Raise(exc=ast.Call(func=ast.Name(id="ValueError", ctx=ast.Load()),
                args=[] if binding["message"] is None else [ast.Constant(value=binding["message"])], keywords=[]), cause=None)], orelse=[])
        else:
            raise ValueError("predicted production violates source binder/arity constraints")
        values.append(value)
    scaffolding = observed["scaffolding"]
    docstring = [] if scaffolding["docstring"] is None else [ast.Expr(value=ast.Constant(value=scaffolding["docstring"]))]
    function = ast.FunctionDef(name=observed["function"], args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg=name) for name in observed["parameters"]], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=[*docstring, *(values[index] for index in observed["roots"])],
        decorator_list=[ast.parse(value, mode="eval").body for value in scaffolding["decorators"]], returns=None, type_comment=None)
    tree = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    try:
        source = ast.unparse(tree).encode()
        roundtrip = ast.parse(source)
    except (ValueError, TypeError, SyntaxError, AttributeError) as exc:
        raise ValueError("predicted syntax is not a complete program") from exc
    if ast.dump(roundtrip, include_attributes=False) != observed["source_ast"]:
        raise ValueError("learned candidate differs from independently parsed source syntax")
    return source, {"schema": "security-learned-production-tree@2", "function": observed["function"],
        "parameters": observed["parameters"], "roots": observed["roots"], "scaffolding": scaffolding,
        "nodes": [{"id": row["node_id"], "production": production, "children": row["children"],
                   "binding": row["binding"], "source_span_sha256": row["source_span_sha256"]}
                  for row, production in zip(observed["nodes"], productions)]}


def source_shape(source_bytes):
    """Alpha/literal-normalized whole-program split identity; never model input."""
    tree = ast.parse(source_bytes)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.name = "function"
        elif isinstance(node, ast.arg):
            node.arg = "parameter"
        elif isinstance(node, ast.Name):
            node.id = "identifier"
        elif isinstance(node, ast.Constant):
            node.value = {int: 0, str: "literal", bool: False, type(None): None}.get(type(node.value), "unsupported-literal")
    return _sha(ast.dump(tree, include_attributes=False).encode())


def feasible_productions(row: dict) -> tuple[str, ...]:
    """Generic binder/arity constraints, without source labels or operator text.

    Syntax topology and exact lexical bindings are already explicit deterministic
    observations. This function never reads the shell, features, teacher label,
    source AST, or desired candidate. Ambiguous operators remain neural choices.
    """
    binding, arity = row["binding"], len(row["children"])
    keys = set(binding)
    allowed = set()
    if keys == {"name"} and arity == 0:
        allowed.add("name")
    elif keys == {"value"} and arity == 0:
        production = {int: "integer", str: "string", bool: "boolean", type(None): "none"}.get(type(binding["value"]))
        if production is not None:
            allowed.add(production)
    elif keys == {"callee"} and 1 <= arity <= 3:
        allowed.add("call")
    elif keys == {"target"} and arity == 1:
        allowed.add("assign")
    elif keys == {"message"} and arity == 1:
        allowed.add("if_raise")
    elif keys == {"body_count", "else_count"}:
        body, other = binding["body_count"], binding["else_count"]
        if type(body) is int and type(other) is int and body >= 1 and other >= 0 and arity == 1 + body + other:
            allowed.add("if_else")
    elif not binding:
        if arity == 1:
            allowed.update(_UNARY.values())
            allowed.update(_METHODS - {"replace"})
            allowed.add("return")
        if arity == 2:
            allowed.update(_BINARY.values())
            allowed.update(_COMPARE.values())
        if 2 <= arity <= 4:
            allowed.update(_BOOL.values())
        if arity == 3:
            allowed.update(("replace", "if_expr"))
    return tuple(production for production in PRODUCTIONS if production in allowed)
