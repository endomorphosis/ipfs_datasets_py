"""Bounded, reviewed HTTP header normalizer contracts and exact AST repairs.

This operator was developed using a public benchmark's input code.  Its tests
use separately authored programs; it contains no benchmark path or helper name.
It is deliberately a local contract, not a whole-program security theorem.
WSGI callback identity and receiver/property binding are explicit reviewed
assumptions.  AST witnesses constrain those assumptions but do not prove Python
dispatch, mutation, aliasing, or arbitrary user-defined ``__str__`` behavior.

No target code is imported or executed.  The only generated behavior is a
CR/LF/NUL guard after an already-existing, structurally recognized conversion.
The unchanged return expression runs on accepted inputs; invalid converted
strings raise ValueError.  Formal obligations describe precisely that guard.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass


OPERATOR_ID = "reviewed-http-header-control-guard@1"
CONTRACT_SCHEMA = "supervisor-http-header-local-contract@1"
FORBIDDEN_CODEPOINTS = (0, 10, 13)
PROOF_SCOPE = (
    "Given the reviewed WSGI role binding and unchanged ordinary Python string "
    "conversion, reject converted strings containing NUL, LF, or CR with "
    "ValueError and preserve the original normalization on other converted "
    "strings. Exact AST replay binds the guard template to source. This is not "
    "a whole-program taint, protocol-conformance, or security proof."
)
OPEN_FRONTIERS = (
    "dynamic_receiver_binding",
    "runtime_monkey_patching",
    "user_defined_string_conversion",
    "other_http_field_syntax",
    "additional_header_sources_unproved",
    "whole_program_security",
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(value: object) -> str:
    return "sha256:" + _sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _dump(value: ast.AST) -> str:
    return ast.dump(value, annotate_fields=True, include_attributes=False)


def _body(node: ast.FunctionDef) -> list[ast.stmt]:
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


@dataclass(frozen=True)
class WsgiHeaderProtocolContract:
    """Explicit caller-reviewed protocol roles, not inferred authority.

    The named formal callback is assumed to implement WSGI start_response and
    its second positional argument's property is assumed to denote the unique
    property declaration found in this source.  A nonempty review reference is
    required so artifacts cannot present a heuristic role as a proof.
    """

    review_ref: str
    callback_parameter: str = "start_response"

    def __post_init__(self) -> None:
        if not isinstance(self.review_ref, str) or not self.review_ref.strip() or len(self.review_ref) > 512:
            raise ValueError("a bounded protocol review reference is required")
        if not isinstance(self.callback_parameter, str) or not self.callback_parameter.isidentifier():
            raise ValueError("the reviewed callback parameter must be an identifier")


@dataclass(frozen=True)
class HeaderGuardEdit:
    symbol: str
    role: str
    start: int
    end: int
    before: str
    after: str
    converted_variable: str
    conversion_symbol: str
    before_ast_sha256: str
    after_ast_sha256: str


@dataclass(frozen=True)
class HeaderGuardCandidate:
    operator_id: str
    before_sha256: str
    after_sha256: str
    source: str
    edits: tuple[HeaderGuardEdit, ...]
    contract_cid: str
    contract: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HeaderContractAnalysis:
    status: str
    reason_codes: tuple[str, ...]
    source_sha256: str
    contracts: tuple[dict, ...] = ()
    candidate: HeaderGuardCandidate | None = None
    open_frontiers: tuple[str, ...] = OPEN_FRONTIERS

    def to_dict(self) -> dict:
        return asdict(self)


def _plain_args(node: ast.FunctionDef) -> tuple[str, ...] | None:
    args = node.args
    if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
        return None
    return tuple(arg.arg for arg in args.args)


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _top_bindings(tree: ast.Module) -> dict[str, list[ast.AST]]:
    result: dict[str, list[ast.AST]] = {}
    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.setdefault(node.name, []).append(node)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            result.setdefault(node.id, []).append(node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                result.setdefault(alias.asname or alias.name.split(".")[0], []).append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
    for statement in tree.body:
        visit(statement)
    return result


def _recognized_conversion(name: str, bindings: dict[str, list[ast.AST]]) -> bool:
    if name == "str":
        return name not in bindings
    candidates = bindings.get(name, [])
    if len(candidates) != 1 or not isinstance(candidates[0], ast.FunctionDef):
        return False
    node = candidates[0]
    args = _plain_args(node)
    if args is None or len(args) != 3 or node.decorator_list or len(node.args.defaults) != 2:
        return False
    if set(args) & {"str", "isinstance", "bytes", "bytearray"}:
        return False
    if any(name in bindings for name in ("str", "isinstance", "bytes", "bytearray")):
        return False
    if [_dump(default) for default in node.args.defaults] != ["Constant(value='utf8')", "Constant(value='strict')"]:
        return False
    value, encoding, errors = args
    expected = ast.parse(
        f"if isinstance({value}, (bytes, bytearray)):\n"
        f"    return str({value}, {encoding}, {errors})\n"
        f"return '' if {value} is None else str({value})\n"
    ).body
    return [_dump(item) for item in _body(node)] == [_dump(item) for item in expected]


def _guard(variable: str, indent: str) -> str:
    return (
        f"{indent}if '\\r' in {variable} or '\\n' in {variable} or '\\x00' in {variable}:\n"
        f"{indent}    raise ValueError('HTTP header contains a forbidden control character')\n"
    )


def _normalizer(node: ast.FunctionDef, role: str, bindings: dict[str, list[ast.AST]]) -> tuple[str, str, bool] | None:
    args = _plain_args(node)
    body = _body(node)
    if args is None or len(args) != 1 or node.args.defaults or node.decorator_list or len(body) not in (2, 3):
        return None
    assignment, returned = body[0], body[-1]
    if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
        return None
    variable = assignment.targets[0].id
    call = assignment.value
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
            or len(call.args) != 1 or call.keywords or not _is_name(call.args[0], args[0])
            or not _recognized_conversion(call.func.id, bindings)):
        return None
    if {args[0], variable} & {"ValueError", call.func.id}:
        return None
    if not isinstance(returned, ast.Return):
        return None
    expressions = [variable]
    if role == "field_name":
        expressions.extend(f"{variable}.{method}()" for method in ("title", "lower", "upper", "casefold"))
        expressions.extend(expression + ".replace('_', '-')" for expression in tuple(expressions))
    allowed = {_dump(ast.parse(expression, mode="eval").body) for expression in expressions}
    if _dump(returned.value) not in allowed:
        return None
    guarded = len(body) == 3
    if guarded and _dump(body[1]) != _dump(ast.parse(_guard(variable, "")).body[0]):
        return None
    return variable, call.func.id, guarded


def _projection_reaches_return(getter: ast.FunctionDef, receiver: str, store: str) -> bool:
    """Recognize a narrow items -> flattened pairs -> returned value flow.

    This rejects unused store reads and overwritten return variables. It is an
    AST reaching-definition witness, not a proof of dynamic Python dispatch.
    """
    def pair_target(node: ast.AST) -> tuple[str, str] | None:
        if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == 2 and all(isinstance(x, ast.Name) for x in node.elts):
            return node.elts[0].id, node.elts[1].id
        return None
    def expression(node: ast.AST, env: dict[str, str]) -> str | None:
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.List) and not node.elts:
            return "empty"
        if isinstance(node, ast.Call) and not node.keywords:
            if (_is_name(node.func, "list") and len(node.args) == 1):
                return expression(node.args[0], env)
            if (not node.args and isinstance(node.func, ast.Attribute) and node.func.attr == "items"
                    and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == store
                    and _is_name(node.func.value.value, receiver)):
                return "items"
        if isinstance(node, ast.ListComp) and all(not gen.is_async for gen in node.generators):
            first = node.generators[0]
            origin = expression(first.iter, env)
            if len(node.generators) == 1 and isinstance(first.target, ast.Name) and _is_name(node.elt, first.target.id):
                return origin
            target = pair_target(first.target)
            if target is None:
                return None
            if len(node.generators) == 2 and origin == "items":
                second = node.generators[1]
                if (isinstance(second.target, ast.Name) and _is_name(second.iter, target[1])
                        and pair_target(node.elt) == (target[0], second.target.id)):
                    return "pairs"
            if len(node.generators) == 1 and origin == "pairs" and isinstance(node.elt, ast.Tuple) and len(node.elt.elts) == 2:
                key, value = node.elt.elts
                while (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                       and value.func.attr in {"encode", "decode"} and not value.keywords
                       and all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in value.args)):
                    value = value.func.value
                if _is_name(key, target[0]) and _is_name(value, target[1]):
                    return "pairs"
        return None
    def statements(body: list[ast.stmt], env: dict[str, str]) -> dict[str, str]:
        env = dict(env)
        for statement in body:
            if isinstance(statement, ast.Assign):
                kind = expression(statement.value, env)
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        env.pop(target.id, None)
                        if kind is not None:
                            env[target.id] = kind
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                name = statement.target.id
                kind = expression(statement.value, env)
                if isinstance(statement.op, ast.Add) and kind == "pairs" and env.get(name) in {"empty", "pairs"}:
                    env[name] = "pairs"
                else:
                    env.pop(name, None)
            elif isinstance(statement, ast.If):
                yes = statements(statement.body, env)
                no = statements(statement.orelse, env)
                env = {key: value for key, value in yes.items() if no.get(key) == value}
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.attr not in {"append", "extend"}:
                    env.pop(call.func.value.id, None)
            elif not isinstance(statement, ast.Return):
                # Unsupported control flow may overwrite an alias; never carry
                # that alias through it as if the definition were unchanged.
                for node in ast.walk(statement):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                        env.pop(node.id, None)
        return env
    body = _body(getter)
    if any(isinstance(node, ast.Name) and node.id == "list" and isinstance(node.ctx, (ast.Store, ast.Del))
           for node in ast.walk(getter)):
        return False
    if not body or not isinstance(body[-1], ast.Return):
        return False
    if any(isinstance(node, ast.Return) for statement in body[:-1] for node in ast.walk(statement)):
        return False
    return expression(body[-1].value, statements(body[:-1], {})) == "pairs"


def _property_witnesses(tree: ast.Module, protocol: WsgiHeaderProtocolContract) -> tuple[list[dict], str | None]:
    """Observe explicit callback/property/store edges under reviewed roles."""
    sink_properties: set[str] = set()
    callbacks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        parameters = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        if protocol.callback_parameter not in parameters:
            continue
        if any(isinstance(item, ast.Name) and item.id == protocol.callback_parameter
               and isinstance(item.ctx, (ast.Store, ast.Del)) for item in ast.walk(node)):
            return [], "reviewed_callback_rebound"
        for call in ast.walk(node):
            if (isinstance(call, ast.Call) and _is_name(call.func, protocol.callback_parameter)
                    and len(call.args) >= 2 and not any(isinstance(arg, ast.Starred) for arg in call.args)
                    and isinstance(call.args[1], ast.Attribute)):
                sink_properties.add(call.args[1].attr)
                callbacks.append({"function": node.name, "line": call.lineno, "property": call.args[1].attr})
    if len(sink_properties) != 1:
        return [], "ambiguous_or_missing_reviewed_wsgi_sink"
    property_name = next(iter(sink_properties))
    getters = [
        (cls, node) for cls in tree.body if isinstance(cls, ast.ClassDef)
        for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == property_name
        and len(node.decorator_list) == 1 and _is_name(node.decorator_list[0], "property")
    ]
    if len(getters) != 1:
        return [], "ambiguous_or_missing_header_property"
    cls, getter = getters[0]
    if "property" in _top_bindings(ast.Module(body=cls.body, type_ignores=[])):
        return [], "shadowed_property_decorator"
    args = _plain_args(getter)
    if args is None or len(args) != 1 or args[0] == "list":
        return [], "unsupported_header_property_signature"
    receiver = args[0]
    stores = {
        node.func.value.attr for node in ast.walk(getter)
        if isinstance(node, ast.Call) and not node.args and not node.keywords
        and isinstance(node.func, ast.Attribute) and node.func.attr == "items"
        and isinstance(node.func.value, ast.Attribute) and _is_name(node.func.value.value, receiver)
    }
    if len(stores) != 1:
        return [], "ambiguous_or_missing_header_store_projection"
    store = next(iter(stores))
    if not _projection_reaches_return(getter, receiver, store):
        return [], "unproved_header_store_projection"
    pairs: set[tuple[str, str]] = set()
    setters = []
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        parameters = _plain_args(method)
        body = _body(method)
        if parameters is None or len(parameters) != 3 or len(body) != 1 or not isinstance(body[0], ast.Assign):
            continue
        statement = body[0]
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Subscript):
            continue
        target = statement.targets[0]
        if (not isinstance(target.value, ast.Attribute) or target.value.attr != store
                or not _is_name(target.value.value, parameters[0])):
            continue
        key = target.slice
        if not isinstance(statement.value, ast.List) or len(statement.value.elts) != 1:
            continue
        val = statement.value.elts[0]
        if not all(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and not call.keywords and len(call.args) == 1 for call in (key, val)):
            continue
        if not _is_name(key.args[0], parameters[1]) or not _is_name(val.args[0], parameters[2]):
            continue
        if key.func.id in parameters or val.func.id in parameters:
            return [], "shadowed_setter_normalizer"
        pairs.add((key.func.id, val.func.id))
        setters.append({"function": method.name, "line": statement.lineno})
    if len(pairs) != 1:
        return [], "ambiguous_or_missing_header_normalizer_pair"
    key, value = next(iter(pairs))
    if key == value:
        return [], "shared_header_normalizer_roles_unsupported"
    return [{"callback_parameter": protocol.callback_parameter, "callback_calls": callbacks,
             "flow_claim": "partial reaching-store projection; additional header sources unproved",
             "property_class": cls.name, "property_symbol": property_name,
             "property_line": getter.lineno, "store_attribute": store,
             "setters": setters, "field_name_normalizer": key,
             "field_value_normalizer": value}], None


def analyze_http_header_contracts(source: str, *, protocol: WsgiHeaderProtocolContract) -> HeaderContractAnalysis:
    """Produce a source-bound local repair, or an explicit unsupported result."""
    if type(source) is not str or type(protocol) is not WsgiHeaderProtocolContract:
        raise TypeError("source text and an explicit reviewed WSGI protocol are required")
    digest = _sha(source)
    def abstain(reason: str) -> HeaderContractAnalysis:
        return HeaderContractAnalysis("unsupported", (reason,), digest)
    if len(source.encode("utf-8")) > 2_000_000 or "\x00" in source or "\r" in source:
        return abstain("unsupported_source_encoding_or_size")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return abstain("invalid_python_source")
    bindings = _top_bindings(tree)
    if any(name in bindings for name in ("ValueError", "property", "list")):
        return abstain("shadowed_contract_builtin")
    witnesses, reason = _property_witnesses(tree, protocol)
    if reason:
        return abstain(reason)
    witness = witnesses[0]
    selected = []
    for role in ("field_name", "field_value"):
        symbol = witness[role + "_normalizer"]
        nodes = bindings.get(symbol, [])
        if len(nodes) != 1 or not isinstance(nodes[0], ast.FunctionDef):
            return abstain("ambiguous_normalizer_binding")
        node = nodes[0]
        shape = _normalizer(node, role, bindings)
        if shape is None:
            return abstain("unsupported_normalizer_or_conversion_shape")
        selected.append((role, node, *shape))
    protected = {"ValueError", "property", "list", "str", "bytes", "bytearray", "isinstance"}
    protected.update(node.name for _, node, *_ in selected)
    protected.update(conversion for _, _, _, conversion, _ in selected)
    for node in ast.walk(tree):
        if isinstance(node, ast.Global) and protected.intersection(node.names):
            return abstain("explicit_contract_binding_mutation")
        if (isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del))
                and isinstance(node.slice, ast.Constant) and node.slice.value in protected):
            if (_is_name(node.value, "__builtins__") or
                    isinstance(node.value, ast.Call) and _is_name(node.value.func, "globals")):
                return abstain("explicit_contract_binding_mutation")
    # Python's physical source lines are LF-delimited. str.splitlines() also
    # splits Unicode separators inside comments/strings and corrupts spans.
    parts = source.split("\n")
    lines = [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for role, node, variable, conversion, guarded in selected:
        if guarded:
            continue
        returned = _body(node)[-1]
        if (returned.lineno != returned.end_lineno or node.col_offset != 0
                or _body(node)[0].end_lineno >= returned.lineno):
            return abstain("unsupported_normalizer_source_span")
        indent_match = re.match(r"( +)return\b", lines[returned.lineno - 1])
        if indent_match is None:
            return abstain("unsupported_normalizer_indentation")
        start, end = offsets[node.lineno - 1], offsets[node.end_lineno]
        before = source[start:end]
        insertion = offsets[returned.lineno - 1] - start
        after = before[:insertion] + _guard(variable, indent_match.group(1)) + before[insertion:]
        after_node = ast.parse(after).body[0]
        expected_body = list(node.body)
        expected_body.insert(len(expected_body) - 1, ast.parse(_guard(variable, "")).body[0])
        expected = ast.FunctionDef(name=node.name, args=node.args, body=expected_body,
                                   decorator_list=node.decorator_list, returns=node.returns,
                                   type_comment=node.type_comment)
        if hasattr(node, "type_params"):
            expected.type_params = node.type_params
        if _dump(after_node) != _dump(expected):
            return abstain("after_ast_replay_mismatch")
        edits.append(HeaderGuardEdit(node.name, role, start, end, before, after, variable, conversion,
                                     _sha(_dump(node)), _sha(_dump(after_node))))
    contract = {
        "schema": CONTRACT_SCHEMA, "operator_id": OPERATOR_ID,
        "source_sha256": digest, "protocol": asdict(protocol),
        "normative_reference": "https://www.rfc-editor.org/rfc/rfc9110.html#section-5.5",
        "forbidden_codepoints": list(FORBIDDEN_CODEPOINTS), "error_type": "ValueError",
        "accepted_behavior": "unchanged original return expression after unchanged conversion",
        "proof_scope": PROOF_SCOPE, "witnesses": witnesses,
        "assumptions": ["reviewed_wsgi_callback_identity", "reviewed_unique_property_receiver_binding",
                        "ordinary_unmodified_python_builtins_and_helper_bindings",
                        "recognized_conversion_returns_an_ordinary_string"],
        "open_frontiers": list(OPEN_FRONTIERS),
        "normalizers": [{"role": role, "symbol": node.name, "conversion": conversion,
                         "ast_sha256": _sha(_dump(node)), "already_guarded": guarded}
                        for role, node, variable, conversion, guarded in selected],
        "proof_obligations": ["forbidden_converted_input_rejected", "accepted_normalization_preserved"],
    }
    contract_cid = _identity(contract)
    if not edits:
        return HeaderContractAnalysis("already_satisfied", (), digest, (contract,))
    after = source
    for edit in sorted(edits, key=lambda item: item.start, reverse=True):
        if after[edit.start:edit.end] != edit.before:
            raise ValueError("internal exact-preimage replay failure")
        after = after[:edit.start] + edit.after + after[edit.end:]
    candidate = HeaderGuardCandidate(OPERATOR_ID, digest, _sha(after), after, tuple(edits), contract_cid, contract)
    return HeaderContractAnalysis("candidate", (), digest, (contract,), candidate)


def verify_header_candidate(original: str, candidate: HeaderGuardCandidate) -> bool:
    """Independently rebuild and compare every byte, scope, witness and contract."""
    if type(candidate) is not HeaderGuardCandidate or type(original) is not str:
        return False
    try:
        protocol = WsgiHeaderProtocolContract(**candidate.contract["protocol"])
        result = analyze_http_header_contracts(original, protocol=protocol)
        return result.candidate is not None and result.candidate.to_dict() == candidate.to_dict()
    except (KeyError, TypeError, ValueError, SyntaxError):
        return False
