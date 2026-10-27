"""Strict authored relational declarations using existing typed and native ASTs.

This variables-only fragment does not translate statutory text. O/P/F remain
independent interpretation parameters. Native Lean text generation is separate
from execution, meaning review, graph admission and training eligibility.
Operation owners load only after bounded independently hashed request parsing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

REQUEST_SCHEMA = "legal-relational-norm-request/v1"
SCHEMA = "legal-relational-norm-report/v1"
PROFILE = "authored-object-relational-deontic/v1"
MAX_REQUEST_BYTES = 524288
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_NODES = 512
MAX_DEPTH = 48
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_ROLE = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_WORDS = {"and", "or", "not", "implies", "iff", "xor", "forall", "exists",
          "always", "eventually", "next", "until", "since", "weak_until",
          "weakuntil", "release"}
_LETTERS = {"O", "P", "F", "G", "X", "U", "S", "W", "R"}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_gold_qualified",
    "evaluation_gold_qualified", "Lean_admitted", "proof_authority",
    "backend_executed", "model_executed", "training_executed",
), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _keys(value, expected, label):
    _need(type(value) is dict and set(value) == set(expected),
          "closed exact fields required: " + label)


def _wire(value, maximum):
    remaining = 100000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 96, "bounded ordinary JSON required")
        if type(item) is dict:
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= maximum,
                  "bounded UTF8 strings required")
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
        else:
            raise ValueError("ordinary finite JSON required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _parse(request_raw, expected_request_sha256):
    _digest(expected_request_sha256, "request")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES,
          "bounded exact request bytes required")
    _need(hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
          "request SHA256 mismatch")
    try:
        value = json.loads(request_raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free UTF8 JSON required") from error
    _wire(value, MAX_REQUEST_BYTES)
    _keys(value, {"schema", "interpretation_status", "expression", "argument_roles",
                  "source_binding"}, "request")
    _need(value["schema"] == REQUEST_SCHEMA and
          value["interpretation_status"] == "authored_unreviewed_declaration",
          "authored unreviewed request schema required")
    _need(value["source_binding"] is None,
          "source binding unsupported: authored fragment is not a statutory interpretation")
    _need(type(value["expression"]) is dict and type(value["argument_roles"]) is list,
          "serialized TypedExpression and ordered role ledger required")
    return value


def _owners():
    # Deliberately no syntax/native imports at public-module import time.
    from ..syntax_core import ast, contracts, signatures
    from ..families import namespaces
    from ..parsers import legacy_modal
    from ..TDFOL import tdfol_core
    from ..intent_ir.formalize import modal_projections
    from . import legal_family_routes

    global _OWNER_PINS
    modules = (ast, contracts, signatures, namespaces, legacy_modal,
               tdfol_core, modal_projections, legal_family_routes)
    pins = {str(Path(module.__file__).resolve()):
            hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules}
    self_path = str(Path(__file__).resolve())
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "relational producer changed since import")
    pins[self_path] = _SELF_PIN
    pins.update(legal_family_routes.producer_pins())
    if _OWNER_PINS is None:
        _OWNER_PINS = pins
    _need(_OWNER_PINS == pins, "relational owner changed since first preparation")
    return ast, signatures, tdfol_core, modal_projections, legal_family_routes, dict(pins)


def _safe_name(value):
    _need(type(value) is str and _NAME.fullmatch(value) is not None and
          value not in _LETTERS and value.lower() not in _WORDS,
          "ambiguous or unsafe native identifier")


def _strict_expression(request, ast, signatures):
    original = request["expression"]
    try:
        expression = ast.TypedExpression.from_dict(original)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise ValueError("valid exact TypedExpression required") from error
    _need(_wire(expression.to_dict(), MAX_REQUEST_BYTES) ==
          _wire(original, MAX_REQUEST_BYTES),
          "TypedExpression must survive exact serialized reconstruction")
    _need(expression.is_formula and expression.family.value == "tdfol" and
          expression.profile.value == "tdfol_default",
          "exact tdfol/tdfol_default formula required")
    _need(all(identity.version == "1.0.0" for identity in (
        expression.family, expression.profile, expression.signature.family, expression.signature.profile)),
        "exact existing namespace identity versions required")
    _need(not expression.metadata and expression.range is None,
          "expression metadata/ranges unsupported")
    signature = expression.signature
    _need(not signature.metadata and not signature.features,
          "signature metadata/features unsupported")
    object_sort = signatures.LogicSort("Object")
    _need(set(signature.sorts) == {signatures.BOOL_SORT, object_sort} and
          len(signature.sorts) == 2, "only Bool and atomic Object sorts supported")
    _need(0 < len(signature.symbols) <= 64, "bounded nonempty predicate signature required")
    predicates = {}
    for symbol in signature.symbols:
        _safe_name(symbol.name)
        _need(symbol.kind is signatures.SymbolKind.PREDICATE and
              1 <= symbol.arity <= 8 and symbol.range == signatures.BOOL_SORT and
              all(sort == object_sort for sort in symbol.domain) and
              not symbol.metadata, "only bounded Object predicates supported")
        predicates[symbol.name] = symbol.arity

    roles = request["argument_roles"]
    _need(len(roles) == len(predicates), "roles must cover every declared predicate")
    role_symbols = set()
    for row in roles:
        _keys(row, {"symbol", "roles"}, "argument role row")
        name, labels = row["symbol"], row["roles"]
        _need(type(name) is str and name in predicates and name not in role_symbols,
              "unique declared predicate role row required")
        _need(type(labels) is list and len(labels) == predicates[name] and
              all(type(label) is str and _ROLE.fullmatch(label) is not None for label in labels) and
              len(set(labels)) == len(labels), "ordered distinct bounded argument roles required")
        role_symbols.add(name)
    return expression, predicates


def _lower(expression, predicates, ast, native):
    seen_ids, seen_binders, used_predicates = set(), set(), set()
    mapping = []
    counters = {"nodes": 0, "quantifiers": 0, "modal_nodes": 0, "predicate_occurrences": 0}
    modal_kinds = {"O": "obligation", "P": "permission", "F": "forbidden"}
    operators = {"and": native.LogicOperator.AND, "or": native.LogicOperator.OR,
                 "implies": native.LogicOperator.IMPLIES, "iff": native.LogicOperator.IFF}
    object_sort = next(sort for sort in expression.signature.sorts if sort.name == "Object")

    def identity(node_id):
        _need(node_id not in seen_ids, "node and extension IDs must be globally unique")
        seen_ids.add(node_id)

    def visit(node, path, native_path, bound, depth):
        counters["nodes"] += 1
        _need(counters["nodes"] <= MAX_NODES and depth <= MAX_DEPTH,
              "relational AST node/depth bound exceeded")
        identity(node.node_id)
        _need(not node.metadata and node.range is None,
              "node metadata/ranges unsupported")
        _need(isinstance(node.kind, ast.NodeKind), "open node kinds unsupported")
        kind = node.kind.value
        mapping.append({"typed_path": path, "native_path": native_path,
                        "node_id": node.node_id, "kind": kind})
        if kind == "variable":
            _safe_name(node.symbol)
            _need(node.symbol in bound and node.sort == object_sort,
                  "only explicitly bound Object variables supported")
            return native.Variable(node.symbol, sort=None)
        _need(node.is_formula, "constants/functions/other terms unsupported")
        if kind == "predicate":
            _need(node.symbol in predicates and len(node.arguments) == predicates[node.symbol] and
                  all(child.kind is ast.NodeKind.VARIABLE for child in node.arguments),
                  "predicate requires ordered bound-variable arguments of exact arity")
            used_predicates.add(node.symbol)
            counters["predicate_occurrences"] += 1
            return native.Predicate(node.symbol, tuple(visit(child, path + "/arguments/" + str(index),
                native_path + "/arguments/" + str(index), bound, depth + 1)
                for index, child in enumerate(node.arguments)))
        if kind in operators:
            _need(len(node.arguments) == 2, "exactly binary connective required")
            return native.BinaryFormula(operators[kind],
                visit(node.arguments[0], path + "/arguments/0", native_path + "/left", bound, depth + 1),
                visit(node.arguments[1], path + "/arguments/1", native_path + "/right", bound, depth + 1))
        if kind == "not":
            return native.UnaryFormula(native.LogicOperator.NOT,
                visit(node.arguments[0], path + "/arguments/0", native_path + "/formula", bound, depth + 1))
        if kind in {"forall", "exists"}:
            _need(len(node.binders) == 1, "exactly one binder per quantifier required")
            binder = node.binders[0]
            _safe_name(binder.name)
            _need(binder.sort == object_sort and binder.name not in bound and
                  binder.name not in seen_binders and binder.name not in predicates,
                  "Object binders must be globally distinct, nonshadowing and separate from predicate names")
            seen_binders.add(binder.name)
            counters["quantifiers"] += 1
            mapping.append({"typed_path": path + "/binders/0", "native_path": native_path + "/variable",
                            "binder_name": binder.name, "kind": "binder", "typed_sort": "Object",
                            "native_sort": None})
            return native.QuantifiedFormula(native.Quantifier.FORALL if kind == "forall" else native.Quantifier.EXISTS,
                native.Variable(binder.name, sort=None),
                visit(node.arguments[0], path + "/arguments/0", native_path + "/formula",
                      bound | {binder.name}, depth + 1))
        if kind == "extension":
            extension = node.extension
            _need(extension is not None and not node.binders and not node.arguments and not node.symbol,
                  "unannotated modal extension required")
            identity(extension.node_id)
            _need(extension.family.value == "tdfol" and extension.profile.value == "tdfol_default" and
                  extension.family.version == extension.profile.version == "1.0.0" and
                  extension.payload_schema == "legacy.deontic/v1" and
                  not extension.metadata and extension.range is None and len(extension.children) == 1 and
                  extension.children[0].is_formula,
                  "exact existing legacy deontic extension required")
            payload = dict(extension.payload)
            _keys(payload, {"kind", "letter", "resolution", "schema_version"}, "deontic payload")
            letter = payload["letter"]
            _need(type(letter) is str and letter in modal_kinds and
                  payload == {"kind": modal_kinds[letter], "letter": letter,
                              "resolution": "deontic", "schema_version": "legacy.deontic/v1"} and
                  set(extension.features) == {"legacy." + modal_kinds[letter], "legacy.classic_letter"} and
                  node.sort.name == "Bool", "exact O/P/F payload and features required")
            counters["modal_nodes"] += 1
            mapping.append({"typed_path": path + "/extension", "native_path": native_path,
                            "node_id": extension.node_id, "kind": "legacy.deontic/v1", "operator": letter})
            return native.DeonticFormula(native.DeonticOperator(letter),
                visit(extension.children[0], path + "/extension/children/0", native_path + "/formula",
                      bound, depth + 1), agent=None, context=None)
        raise ValueError("unsupported relational node: " + kind)

    root = visit(expression.root, "/root", "", frozenset(), 0)
    _need(used_predicates == set(predicates), "every declared predicate must be used")
    _need(counters["quantifiers"] > 0 and not root.get_free_variables(),
          "closed explicitly quantified relational formula required")
    return root, mapping, counters


def prepare_relational_norm_v1(request_raw, *, expected_request_sha256):
    """Prepare an unreviewed authored fragment; execute no native backend."""
    request = _parse(request_raw, expected_request_sha256)
    ast, signatures, native, snapshots, routes, pins = _owners()
    expression, predicates = _strict_expression(request, ast, signatures)
    root, mapping, counters = _lower(expression, predicates, ast, native)
    formula = root.to_string()
    native_ast = snapshots._ast(root)
    receipt = routes.prepare_native_fragment(family="deontic_fol", formula=formula,
                                             expected_ast=native_ast)
    _need(receipt["producer_pins"].items() <= pins.items(), "native producer pin mismatch")
    report = {
        "schema": SCHEMA, "profile": PROFILE,
        "status": "authored_unreviewed_relational_fragment_prepared",
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256, "typed_expression": expression.to_dict(),
        "typed_expression_content_digest": expression.content_digest,
        "typed_expression_sha256": hashlib.sha256(_wire(expression.to_dict(), MAX_REQUEST_BYTES)).hexdigest(),
        "argument_roles": request["argument_roles"], "structural_mapping": mapping,
        "counts": counters, "native_formula": formula, "native_ast": native_ast,
        "native_fragment": receipt, "lean_body": receipt["lean_body"],
        "producer_pins": pins, "source_binding": None,
        "source_bound": False, "source_translation_performed": False,
        "native_build_executed": False, "human_reviews": 0,
        "signatures_constructed": 0, "admissions": 0,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "authority": dict(AUTHORITY),
        "assumptions": [
            "Caller declares predicate identities and ordered argument roles; no statutory meaning is selected.",
            "All relation arguments are explicitly bound variables over one arbitrary Object carrier; finite fixtures declare their own domains.",
            "O/P/F are separate interpretation parameters; no duality, distributivity or legal modal axioms are asserted.",
            "Finite authored countermodels qualify structural distinctions only, not general legal equivalence.",
            "Generated Lean text has not been compiled or admitted by this operation.",
        ],
    }
    _wire(report, MAX_REPORT_BYTES)
    _need(_owners()[-1] == pins, "relational producer changed during preparation")
    return report


def relational_norm_report_sha256(report):
    """Hash the complete ordinary report without importing operation owners."""
    return hashlib.sha256(_wire(report, MAX_REPORT_BYTES)).hexdigest()


def validate_relational_norm_v1(report, request_raw, *, expected_request_sha256,
                                expected_report_sha256):
    """Require independent report identity and complete authoritative replay."""
    _digest(expected_report_sha256, "report")
    _need(relational_norm_report_sha256(report) == expected_report_sha256,
          "report SHA256 mismatch")
    regenerated = prepare_relational_norm_v1(request_raw,
                        expected_request_sha256=expected_request_sha256)
    _need(_wire(report, MAX_REPORT_BYTES) == _wire(regenerated, MAX_REPORT_BYTES),
          "relational report differs from complete authoritative replay")
    return regenerated


# This explicit mixed profile does not widen the native Object-only contract.
# Its renderer record is not a serialized TDFOL node or native parser receipt.
MIXED_REQUEST_SCHEMA = "legal-mixed-relational-norm-request/v1"
MIXED_SCHEMA = "legal-mixed-relational-norm-report/v1"
MIXED_PROFILE = "authored-many-sorted-relational-deontic/v1"
_MIXED_SORTS = ("Object", "EventFrame", "TimeFrame")
_MIXED_OWNER_PINS = None


def _mixed_parse(request_raw, expected_request_sha256):
    _digest(expected_request_sha256, "mixed relational request")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES,
          "bounded exact mixed request bytes required")
    _need(hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
          "mixed request SHA256 mismatch")
    try:
        request = json.loads(request_raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free ordinary mixed request JSON required") from error
    _wire(request, MAX_REQUEST_BYTES)
    _keys(request, {"schema", "profile", "interpretation_status", "expression",
                    "argument_roles", "source_binding"}, "mixed request")
    _need(request["schema"] == MIXED_REQUEST_SCHEMA and request["profile"] == MIXED_PROFILE
          and request["interpretation_status"] == "authored_unreviewed_declaration"
          and request["source_binding"] is None,
          "explicit unreviewed mixed profile with null source binding required")
    _need(type(request["expression"]) is dict and type(request["argument_roles"]) is list,
          "mixed TypedExpression and ordered roles required")
    return request


def _mixed_owners():
    # The typed kernel is authoritative here. No native TDFOL parser can
    # represent these additional sorts and builtin equality losslessly.
    from ..syntax_core import ast, contracts, signatures
    from ..families import namespaces
    from ..formalization.autoencoder import native_family_lean_emitters as emitter
    global _MIXED_OWNER_PINS
    modules = (ast, contracts, signatures, namespaces, emitter)
    pins = {str(Path(module.__file__).resolve()):
            hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in modules}
    self_path = str(Path(__file__).resolve())
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "mixed relational producer changed since import")
    pins[self_path] = _SELF_PIN
    if _MIXED_OWNER_PINS is None:
        _MIXED_OWNER_PINS = dict(pins)
    _need(_MIXED_OWNER_PINS == pins, "mixed relational owners changed since first use")
    return ast, signatures, emitter, dict(pins)


def _mixed_strict_expression(request, ast, signatures):
    original = request["expression"]
    try:
        expression = ast.TypedExpression.from_dict(original)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise ValueError("valid exact mixed TypedExpression required") from error
    _need(_wire(expression.to_dict(), MAX_REQUEST_BYTES) == _wire(original, MAX_REQUEST_BYTES),
          "mixed TypedExpression must survive exact serialized reconstruction")
    _need(expression.is_formula and expression.family.value == "tdfol"
          and expression.profile.value == "tdfol_default"
          and not expression.metadata and expression.range is None,
          "unannotated tdfol/tdfol_default mixed formula required")
    _need(all(identity.version == "1.0.0" for identity in (
        expression.family, expression.profile, expression.signature.family, expression.signature.profile)),
        "exact existing mixed namespace versions required")
    signature = expression.signature
    _need(not signature.metadata and not signature.features,
          "mixed signature metadata/features unsupported")
    expected_sorts = {signatures.BOOL_SORT, *(signatures.LogicSort(name) for name in _MIXED_SORTS)}
    _need(set(signature.sorts) == expected_sorts and len(signature.sorts) == 4,
          "exact Bool/Object/EventFrame/TimeFrame sorts required")
    _need(0 < len(signature.symbols) <= 64, "bounded nonempty mixed predicate signature required")
    predicates = {}
    for symbol in signature.symbols:
        _safe_name(symbol.name)
        _need(symbol.kind is signatures.SymbolKind.PREDICATE and 1 <= symbol.arity <= 8
              and symbol.range == signatures.BOOL_SORT and not symbol.metadata
              and all(sort == signatures.LogicSort(sort.name) and sort.name in _MIXED_SORTS
                      for sort in symbol.domain),
              "only variables-only mixed predicate domains supported")
        predicates[symbol.name] = [sort.name for sort in symbol.domain]
    rows, roles = request["argument_roles"], {}
    _need(len(rows) == len(predicates), "mixed roles must cover every declared predicate")
    for row in rows:
        _keys(row, {"symbol", "roles"}, "mixed argument role row")
        name, labels = row["symbol"], row["roles"]
        _need(type(name) is str and name in predicates and name not in roles,
              "unique declared mixed predicate role row required")
        _need(type(labels) is list and len(labels) == len(predicates[name])
              and all(type(label) is str and _ROLE.fullmatch(label) is not None for label in labels)
              and len(set(labels)) == len(labels),
              "ordered distinct bounded mixed argument roles required")
        roles[name] = list(labels)
    return expression, predicates, roles


def _mixed_lower(expression, predicates, roles, ast, emitter):
    seen_ids, binders, used = set(), set(), set()
    mapping = []
    counts = {"nodes": 0, "extension_payloads": 0, "quantifiers": 0, "modal_nodes": 0,
              "predicate_occurrences": 0, "equality_occurrences": 0}
    binary = {"and": "∧", "or": "∨", "implies": "→", "iff": "↔"}
    modal_kinds = {"O": "obligation", "P": "permission", "F": "forbidden"}

    def identity(node_id):
        _need(node_id not in seen_ids, "mixed node and extension IDs must be globally unique")
        seen_ids.add(node_id)

    def visit(node, typed_path, renderer_path, bound, depth):
        counts["nodes"] += 1
        _need(counts["nodes"] <= MAX_NODES and depth <= MAX_DEPTH,
              "mixed relational AST node/depth bound exceeded")
        identity(node.node_id)
        _need(not node.metadata and node.range is None and isinstance(node.kind, ast.NodeKind),
              "mixed node metadata/ranges/open kinds unsupported")
        kind = node.kind.value
        mapping_row = {"typed_path": typed_path, "renderer_path": renderer_path,
            "node_id": node.node_id, "kind": kind, "sort": node.sort.name}
        mapping.append(mapping_row)
        if kind == "variable":
            _safe_name(node.symbol)
            _need(node.symbol in bound and node.sort.name == bound[node.symbol]
                  and node.sort.name in _MIXED_SORTS,
                  "explicitly bound same-sort mixed variable required")
            return {"node_type": "Variable", "name": node.symbol, "sort": node.sort.name}
        _need(node.is_formula, "mixed constants/functions/other terms unsupported")
        if kind == "predicate":
            _need(node.symbol in predicates and len(node.arguments) == len(predicates[node.symbol])
                  and all(child.kind is ast.NodeKind.VARIABLE for child in node.arguments)
                  and [child.sort.name for child in node.arguments] == predicates[node.symbol],
                  "mixed predicate requires exact ordered sorted variable arguments")
            used.add(node.symbol)
            counts["predicate_occurrences"] += 1
            mapping_row.update(argument_roles=list(roles[node.symbol]),
                               argument_sorts=list(predicates[node.symbol]))
            return {"node_type": "AtomicFormula", "name": node.symbol,
                "arguments": [visit(child, typed_path + "/arguments/" + str(index),
                    renderer_path + "/arguments/" + str(index), bound, depth + 1)
                    for index, child in enumerate(node.arguments)]}
        if kind == "equality":
            _need(len(node.arguments) == 2
                  and all(child.kind is ast.NodeKind.VARIABLE for child in node.arguments)
                  and node.arguments[0].sort == node.arguments[1].sort
                  and node.arguments[0].sort.name in _MIXED_SORTS,
                  "builtin mixed equality requires two same-sort bound variables")
            counts["equality_occurrences"] += 1
            return {"node_type": "EqualityFormula",
                "left": visit(node.arguments[0], typed_path + "/arguments/0",
                              renderer_path + "/left", bound, depth + 1),
                "right": visit(node.arguments[1], typed_path + "/arguments/1",
                               renderer_path + "/right", bound, depth + 1)}
        if kind in binary:
            _need(len(node.arguments) == 2, "exactly binary mixed connective required")
            return {"node_type": "BinaryFormula", "operator": {"value": binary[kind]},
                "left": visit(node.arguments[0], typed_path + "/arguments/0",
                              renderer_path + "/left", bound, depth + 1),
                "right": visit(node.arguments[1], typed_path + "/arguments/1",
                               renderer_path + "/right", bound, depth + 1)}
        if kind == "not":
            return {"node_type": "UnaryFormula", "operator": {"value": "¬"},
                "formula": visit(node.arguments[0], typed_path + "/arguments/0",
                                 renderer_path + "/formula", bound, depth + 1)}
        if kind in {"forall", "exists"}:
            _need(len(node.binders) == 1, "exactly one mixed binder per quantifier required")
            binder = node.binders[0]
            _safe_name(binder.name)
            _need(binder.sort.name in _MIXED_SORTS and binder.name not in bound
                  and binder.name not in binders and binder.name not in predicates,
                  "globally distinct nonshadowing mixed binders required")
            binders.add(binder.name)
            counts["quantifiers"] += 1
            mapping.append({"typed_path": typed_path + "/binders/0",
                "renderer_path": renderer_path + "/variable", "binder_name": binder.name,
                "kind": "binder", "typed_sort": binder.sort.name, "renderer_sort": binder.sort.name})
            return {"node_type": "QuantifiedFormula",
                "quantifier": {"value": "∀" if kind == "forall" else "∃"},
                "variable": {"node_type": "Variable", "name": binder.name, "sort": binder.sort.name},
                "formula": visit(node.arguments[0], typed_path + "/arguments/0",
                    renderer_path + "/formula", {**bound, binder.name: binder.sort.name}, depth + 1)}
        if kind == "extension":
            extension = node.extension
            _need(extension is not None and not node.binders and not node.arguments and not node.symbol,
                  "closed mixed modal extension required")
            identity(extension.node_id)
            _need(extension.family.value == "tdfol" and extension.profile.value == "tdfol_default"
                  and extension.family.version == extension.profile.version == "1.0.0"
                  and extension.payload_schema == "legacy.deontic/v1"
                  and not extension.metadata and extension.range is None
                  and len(extension.children) == 1 and extension.children[0].is_formula,
                  "exact legacy mixed deontic extension required")
            payload = dict(extension.payload)
            _keys(payload, {"kind", "letter", "resolution", "schema_version"}, "mixed deontic payload")
            letter = payload["letter"]
            _need(type(letter) is str and letter in modal_kinds
                  and payload == {"kind": modal_kinds[letter], "letter": letter,
                      "resolution": "deontic", "schema_version": "legacy.deontic/v1"}
                  and set(extension.features) == {"legacy." + modal_kinds[letter], "legacy.classic_letter"},
                  "exact O/P/F mixed payload and features required")
            counts["extension_payloads"] += 1
            counts["modal_nodes"] += 1
            mapping.append({"typed_path": typed_path + "/extension", "renderer_path": renderer_path,
                "node_id": extension.node_id, "kind": "legacy.deontic/v1", "operator": letter, "sort": "Bool"})
            return {"node_type": "DeonticFormula", "operator": {"value": letter},
                "agent": None, "context": None,
                "formula": visit(extension.children[0], typed_path + "/extension/children/0",
                                 renderer_path + "/formula", bound, depth + 1)}
        raise ValueError("unsupported mixed relational node: " + kind)

    root = visit(expression.root, "/root", "/root", {}, 0)
    _need(used == set(predicates), "every declared mixed predicate must be used")
    _need(counts["quantifiers"] > 0 and not expression.root.free_variable_names(),
          "closed explicitly quantified mixed formula required")
    return {"schema": emitter.SORTED_RELATIONAL_AST_SCHEMA,
            "profile": emitter.SORTED_RELATIONAL_PROFILE, "root": root}, mapping, counts


def _mixed_callbacks(ast, emitter):
    callbacks = (_mixed_parse, _mixed_owners, _mixed_strict_expression, _mixed_lower,
        _mixed_callbacks, prepare_mixed_relational_norm_v1,
        ast.TypedExpression.from_dict, ast.TypedExpression.to_dict, ast.elaborate,
        emitter.sorted_relational_document, emitter._sorted_relational_wire,
        emitter.SortedFormulaRenderer.formula, emitter.SortedFormulaRenderer.term,
        emitter.SortedFormulaRenderer._raw_variable, emitter.SortedFormulaRenderer._variable,
        emitter.FormulaRenderer.formula, emitter.FormulaRenderer.term,
        emitter.FormulaRenderer.step, emitter.FormulaRenderer.signature, _wire)
    return tuple((getattr(function, "__func__", function),
                  getattr(function, "__code__", None), id(getattr(function, "__defaults__", None)),
                  id(getattr(function, "__kwdefaults__", None))) for function in callbacks)


def prepare_mixed_relational_norm_v1(request_raw, *, expected_request_sha256):
    """Lower one strict authored mixed formula; execute no native backend."""
    request = _mixed_parse(request_raw, expected_request_sha256)
    original_wire = _wire(request, MAX_REQUEST_BYTES)
    ast, signatures, emitter, pins = _mixed_owners()
    callbacks = _mixed_callbacks(ast, emitter)
    policy = (MIXED_REQUEST_SCHEMA, MIXED_SCHEMA, MIXED_PROFILE, _MIXED_SORTS,
              MAX_REQUEST_BYTES, MAX_REPORT_BYTES, MAX_NODES, MAX_DEPTH,
              emitter.SORTED_RELATIONAL_AST_SCHEMA, emitter.SORTED_RELATIONAL_PROFILE,
              emitter.SORTED_RELATIONAL_CARRIER, emitter.SORTED_RELATIONAL_SORTS)
    authority = dict(AUTHORITY)
    _need(authority and all(value is False for value in authority.values()),
          "mixed preparation cannot confer authority")

    def fence():
        _need(_wire(request, MAX_REQUEST_BYTES) == original_wire,
              "mixed parsed request changed during lowering")
        _need(_mixed_owners()[-1] == pins and _mixed_callbacks(ast, emitter) == callbacks,
              "mixed source or lowering callbacks changed")
        _need(AUTHORITY == authority and all(value is False for value in AUTHORITY.values()),
              "mixed authority policy changed")
        _need(policy == (MIXED_REQUEST_SCHEMA, MIXED_SCHEMA, MIXED_PROFILE, _MIXED_SORTS,
              MAX_REQUEST_BYTES, MAX_REPORT_BYTES, MAX_NODES, MAX_DEPTH,
              emitter.SORTED_RELATIONAL_AST_SCHEMA, emitter.SORTED_RELATIONAL_PROFILE,
              emitter.SORTED_RELATIONAL_CARRIER, emitter.SORTED_RELATIONAL_SORTS),
              "mixed lowering profile policy changed")

    fence()
    expression, predicates, roles = _mixed_strict_expression(request, ast, signatures)
    typed_wire = _wire(expression.to_dict(), MAX_REQUEST_BYTES)
    renderer_ast, mapping, counts = _mixed_lower(expression, predicates, roles, ast, emitter)
    renderer_wire = _wire(renderer_ast, MAX_REQUEST_BYTES)
    fence()
    lean_body, details = emitter.sorted_relational_document(renderer_ast, predicate_sorts=predicates)
    _need(_wire(renderer_ast, MAX_REQUEST_BYTES) == renderer_wire
          and _wire(expression.to_dict(), MAX_REQUEST_BYTES) == typed_wire,
          "mixed typed or renderer tree changed during emission")
    fence()
    result = {"schema": MIXED_SCHEMA, "profile": MIXED_PROFILE,
        "status": "authored_unreviewed_mixed_relational_fragment_prepared",
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256,
        "typed_expression": expression.to_dict(),
        "typed_expression_content_digest": expression.content_digest,
        "typed_expression_sha256": hashlib.sha256(typed_wire).hexdigest(),
        "argument_roles": request["argument_roles"], "predicate_sorts": predicates,
        "structural_mapping": mapping, "counts": counts,
        "renderer_ast": renderer_ast, "renderer_ast_sha256": hashlib.sha256(renderer_wire).hexdigest(),
        "lean_body": lean_body, "lowering_details": details, "producer_pins": pins,
        "source_binding": None, "source_bound": False, "source_translation_performed": False,
        "native_ast": None, "native_parser_roundtrip": False, "native_build_executed": False,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "selected_interpretation": None, "governing_definition_use": None,
        "authority": dict(authority),
        "assumptions": list(details["assumptions"]) + [
            "The exact authored typed expression and ordered roles are retained; no statutory meaning or applicability is selected.",
            "The renderer record is not a native TDFOL AST and is not admitted to any existing native dispatch profile.",
            "Generated Lean text requires separate actual compilation and review before any corpus use.",
        ]}
    serialized = _wire(result, MAX_REPORT_BYTES)
    fence()
    _need(_wire(result, MAX_REPORT_BYTES) == serialized,
          "mixed relational report changed after serialization")
    return json.loads(serialized)


def mixed_relational_norm_report_sha256(report):
    """Hash the complete bounded mixed report with the existing JSON recipe."""
    return relational_norm_report_sha256(report)


def validate_mixed_relational_norm_v1(report, request_raw, *, expected_request_sha256,
                                     expected_report_sha256):
    """Require an independent complete report pin and authoritative regeneration."""
    _digest(expected_report_sha256, "mixed report")
    original = _wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(original).hexdigest() == expected_report_sha256,
          "mixed report SHA256 mismatch")
    regenerated = prepare_mixed_relational_norm_v1(request_raw,
        expected_request_sha256=expected_request_sha256)
    _need(_wire(report, MAX_REPORT_BYTES) == original
          and _wire(regenerated, MAX_REPORT_BYTES) == original,
          "mixed report differs from complete authoritative replay")
    return regenerated


# Focused inventory of caller-supplied candidate ASTs. It is not a corpus census
# and it does not add a graph exporter or a mixed native parser.
INTERFACE_REQUEST_SCHEMA = "legal-candidate-ir-interface-request/v1"
INTERFACE_REPORT_SCHEMA = "legal-candidate-ir-interface-report/v1"
INTERFACE_DISPOSITIONS = ("representable", "unsupported", "ambiguous")
INTERFACE_CODECS = ("object_relational", "mixed_relational", "native_unary_preservation")
INTERFACE_MAX_CANDIDATES = 8
INTERFACE_MAX_BYTES = 2 * 1024 * 1024
_INVENTORY_MAX_NODES = 8192
_INVENTORY_MAX_DEPTH = 96
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_OBJECT_CONSTRUCTORS = ("variable", "predicate", "not", "and", "or", "implies", "iff",
                        "forall", "exists", "extension")
_MIXED_CONSTRUCTORS = _OBJECT_CONSTRUCTORS + ("equality",)
_NATIVE_CONSTRUCTORS = ("Predicate", "Variable", "UnaryFormula", "BinaryFormula",
                        "QuantifiedFormula")
_RECORD_FIELDS = {
    "candidate_id", "codec", "disposition", "reason", "payload_sha256", "payload_bytes",
    "payload_raw_utf8", "candidate_ast_sha256", "candidate_ast_kind", "content_digest",
    "ordered_constructors", "ordered_binders", "argument_roles", "roles_present",
    "roles_dropped", "replacement_ast", "codec_projection_sha256",
    "projection_replaces_candidate", "admitted", "formalized", "legal_acceptance",
}


def _json_copy(value):
    return json.loads(_wire(value, INTERFACE_MAX_BYTES))


def _reserved_identifier(name):
    return _NAME.fullmatch(name) is not None and (name in _LETTERS or name.lower() in _WORDS)


def _walk_typed(node, constructors, binders, names, depth=0):
    _need(depth <= _INVENTORY_MAX_DEPTH and len(constructors) < _INVENTORY_MAX_NODES,
          "candidate constructor inventory bound exceeded")
    if type(node) is not dict:
        return
    kind = node.get("kind")
    if type(kind) is str:
        constructors.append(kind)
        if kind in {"predicate", "variable", "constant", "application"} and type(node.get("symbol")) is str:
            names.append(node["symbol"])
        if kind in {"forall", "exists", "let"} and type(node.get("binders")) is list:
            for binder in node["binders"]:
                if type(binder) is not dict or type(binder.get("name")) is not str:
                    continue
                sort = binder.get("sort")
                sort_name = sort.get("name") if type(sort) is dict and type(sort.get("name")) is str else None
                binders.append({"name": binder["name"], "sort": sort_name})
                names.append(binder["name"])
    if type(node.get("arguments")) is list:
        for child in node["arguments"]:
            _walk_typed(child, constructors, binders, names, depth + 1)
    extension = node.get("extension")
    if type(extension) is dict and type(extension.get("children")) is list:
        for child in extension["children"]:
            _walk_typed(child, constructors, binders, names, depth + 1)


def _walk_native(node, constructors, binders, depth=0):
    _need(depth <= _INVENTORY_MAX_DEPTH and len(constructors) < _INVENTORY_MAX_NODES,
          "candidate constructor inventory bound exceeded")
    if type(node) is not dict:
        return
    kind = node.get("node_type")
    if type(kind) is str:
        constructors.append(kind)
    if kind == "QuantifiedFormula" and type(node.get("variable")) is dict:
        variable = node["variable"]
        if type(variable.get("name")) is str:
            sort = variable.get("sort")
            binders.append({"name": variable["name"], "sort": sort if type(sort) is str or sort is None else None})
    for key in ("variable", "formula", "left", "right"):
        if key in node:
            _walk_native(node[key], constructors, binders, depth + 1)
    if type(node.get("arguments")) is list:
        for child in node["arguments"]:
            _walk_native(child, constructors, binders, depth + 1)


def _native_formula_ast_conflict(fragment):
    """True when formula and AST are each complete and disagree. Neither replaces the other."""
    ast_value = fragment.get("native_ast")
    formula, family = fragment.get("formula"), fragment.get("family")
    if type(ast_value) is not dict or type(formula) is not str or family not in {"fol", "tdfol"}:
        return False
    from . import legal_native_ast_preservation as native
    try:
        native._typed_ast(ast_value)
    except ValueError:
        return False
    try:
        from . import family_qualification
        from ..intent_ir.formalize.modal_projections import _ast
        parsed_ast = _ast(family_qualification._strict_tdfol(formula)[0])
    except (ValueError, TypeError, KeyError, RecursionError, AttributeError, IndexError):
        return False
    return _wire(parsed_ast, INTERFACE_MAX_BYTES) != _wire(ast_value, INTERFACE_MAX_BYTES)


def _interface_record(candidate_id, codec, disposition, reason, payload_text, payload_sha,
                      ast_sha, ast_kind, content_digest, constructors, binders, roles,
                      projection):
    _need(disposition in INTERFACE_DISPOSITIONS, "unknown candidate disposition")
    record = {
        "candidate_id": candidate_id, "codec": codec, "disposition": disposition, "reason": reason,
        "payload_sha256": payload_sha, "payload_bytes": len(payload_text.encode("utf-8")),
        "payload_raw_utf8": payload_text, "candidate_ast_sha256": ast_sha,
        "candidate_ast_kind": ast_kind, "content_digest": content_digest,
        "ordered_constructors": constructors, "ordered_binders": binders,
        "argument_roles": roles, "roles_present": roles is not None, "roles_dropped": False,
        "replacement_ast": None, "codec_projection_sha256": projection,
        "projection_replaces_candidate": False, "admitted": False, "formalized": False,
        "legal_acceptance": False,
    }
    _keys(record, _RECORD_FIELDS, "candidate interface record")
    _need(record["roles_dropped"] is False and record["replacement_ast"] is None
          and record["projection_replaces_candidate"] is False and record["legal_acceptance"] is False
          and record["admitted"] is False and record["formalized"] is False,
          "candidate inventory cannot accept, drop roles, or replace an AST")
    return record


def _codec_projection_budget():
    from . import legal_native_ast_preservation as native
    from ..formalization.autoencoder import native_family_lean_emitters as emitter
    return {
        "schema": "legal-candidate-codec-projection-budget/v1",
        "interface_schema": INTERFACE_REQUEST_SCHEMA,
        "report_schema": INTERFACE_REPORT_SCHEMA,
        "max_candidates": INTERFACE_MAX_CANDIDATES,
        "max_request_bytes": INTERFACE_MAX_BYTES,
        "dispositions": list(INTERFACE_DISPOSITIONS),
        "corpus_census_executed": False,
        "training_mask": 0, "evaluation_gold_mask": 0, "source_binding": None,
        "logic_family_compatibility": {
            "object_relational": ["tdfol"],
            "mixed_relational": ["tdfol"],
            "native_unary_preservation": ["fol", "tdfol"],
        },
        "object_relational": {
            "request_schema": REQUEST_SCHEMA, "report_schema": SCHEMA, "profile": PROFILE,
            "logic_family": "tdfol", "logic_profile": "tdfol_default",
            "modal_extension": "legacy.deontic/v1", "native_family": "deontic_fol",
            "graph_projection": "not_registered",
            "max_request_bytes": MAX_REQUEST_BYTES, "max_report_bytes": MAX_REPORT_BYTES,
            "max_nodes": MAX_NODES, "max_depth": MAX_DEPTH,
            "predicate_arity_bounds": [1, 8], "max_predicates": 64,
            "supported_constructors": list(_OBJECT_CONSTRUCTORS),
            "output": "native_ast_and_lean_body",
        },
        "mixed_relational": {
            "request_schema": MIXED_REQUEST_SCHEMA, "report_schema": MIXED_SCHEMA,
            "profile": MIXED_PROFILE, "logic_family": "tdfol", "logic_profile": "tdfol_default",
            "modal_extension": "legacy.deontic/v1", "sorts": list(_MIXED_SORTS),
            "renderer_schema": emitter.SORTED_RELATIONAL_AST_SCHEMA,
            "renderer_profile": emitter.SORTED_RELATIONAL_PROFILE,
            "native_ast": None, "native_parser": "not_registered", "graph_projection": "not_registered",
            "max_request_bytes": MAX_REQUEST_BYTES, "max_report_bytes": MAX_REPORT_BYTES,
            "max_nodes": MAX_NODES, "max_depth": MAX_DEPTH,
            "predicate_arity_bounds": [1, 8], "max_predicates": 64,
            "supported_constructors": list(_MIXED_CONSTRUCTORS),
            "output": "sorted_relational_renderer_ast_and_lean_body",
        },
        "native_unary_preservation": {
            "schema": native.SCHEMA, "profile": native.PROFILE, "input_schema": native.INPUT_SCHEMA,
            "fragment_schema": "legal-native-family-route/v1", "project_root": native.PROJECT_ROOT,
            "families": ["fol", "tdfol"], "graph_projection": "not_registered",
            "max_record_bytes": native.MAX_RECORD_BYTES,
            "max_fragment_bytes": native.MAX_FRAGMENT_BYTES,
            "max_project_bytes": native.MAX_PROJECT_BYTES,
            "max_preparation_bytes": native.MAX_PREPARATION_BYTES,
            "max_files": native.MAX_FILES, "max_modules": native.MAX_MODULES,
            "max_theorems": native.MAX_THEOREMS, "max_ast_nodes": native.MAX_AST_NODES,
            "max_ast_depth": native.MAX_AST_DEPTH,
            "supported_constructors": list(_NATIVE_CONSTRUCTORS),
            "operators": ["¬", "∧", "∨", "→", "↔"], "quantifiers": ["∀"],
            "output": "seven_file_preservation_project",
        },
        "missing_interface_recipe": {
            "schema": "legal-candidate-ir-missing-interface-recipe/v1",
            "gap": "semantic_graph_projection_and_mixed_native_tdfol_parser",
            "implemented": False, "replacement_ast_created": False,
            "existing_qualified_codecs_preserved": True,
            "reason": "Mixed Object/EventFrame/TimeFrame equality has no lossless native TDFOL parser, and none of these codecs registers a semantic graph projection.",
            "steps": [
                "Keep each caller candidate AST and ordered role ledger byte-identical.",
                "Do not synthesize a native AST, graph record, or replacement typed expression.",
                "Leave graph admission and a mixed native parser to their existing owners under a separate qualification.",
            ],
        },
    }


def _interface_result(records):
    first, seen = [], set()
    ordered = []
    for record in records:
        ordered.append({
            "candidate_id": record["candidate_id"], "codec": record["codec"],
            "disposition": record["disposition"],
            "ordered_constructors": record["ordered_constructors"],
            "ordered_binders": record["ordered_binders"],
            "argument_roles": record["argument_roles"],
        })
        for kind in record["ordered_constructors"]:
            if kind not in seen:
                seen.add(kind)
                first.append(kind)
    return {
        "candidate_records": records,
        "constructor_vocab_census": {
            "schema": "legal-candidate-constructor-vocab-census/v1",
            "corpus_census_executed": False,
            "ordered_by_candidate": ordered,
            "first_seen_constructors": first,
            "supported_constructors": {
                "object_relational": list(_OBJECT_CONSTRUCTORS),
                "mixed_relational": list(_MIXED_CONSTRUCTORS),
                "native_unary_preservation": list(_NATIVE_CONSTRUCTORS),
            },
        },
        "codec_projection_budget": _codec_projection_budget(),
        "unresolved_questions": [
            {"question_id": "candidate_selection", "status": "unanswered",
             "candidate_ids": [record["candidate_id"] for record in records],
             "detail": "Inventory order is the caller order. No candidate is selected, admitted, or given legal meaning."},
            {"question_id": "governing_definition", "status": "unanswered",
             "detail": "No governing definition, edition, or source binding is supplied."},
            {"question_id": "legal_meaning", "status": "unanswered",
             "detail": "Constructor, binder, and role inventory is not legal acceptance."},
            {"question_id": "semantic_graph", "status": "unanswered",
             "detail": "No semantic graph projection is registered for these codecs."},
            {"question_id": "mixed_native_parser", "status": "unanswered",
             "detail": "Mixed sorts have no lossless native TDFOL parser in the qualified codecs."},
            {"question_id": "training_gold", "status": "unanswered",
             "detail": "Training and evaluation gold masks remain zero."},
        ],
        "reuse_owners": [
            {"path": "ipfs_datasets_py/logic/autoformal/legal_relational_norm_v1.py",
             "symbol": "prepare_relational_norm_v1"},
            {"path": "ipfs_datasets_py/logic/autoformal/legal_relational_norm_v1.py",
             "symbol": "prepare_mixed_relational_norm_v1"},
            {"path": "ipfs_datasets_py/logic/autoformal/legal_native_ast_preservation.py",
             "symbol": "prepare_native_ast_preservation"},
            {"path": "ipfs_datasets_py/logic/formalization/autoencoder/native_family_lean_emitters.py",
             "symbol": "sorted_relational_document"},
        ],
    }


def _classify_relational(codec, payload, payload_raw, payload_text, payload_sha, candidate_id):
    expression = payload.get("expression")
    _need(type(expression) is dict and type(expression.get("root")) is dict,
          "complete candidate typed AST required")
    constructors, binders, names = [], [], []
    _walk_typed(expression["root"], constructors, binders, names)
    roles = payload.get("argument_roles")
    retained_roles = _json_copy(roles) if type(roles) is list else None
    ast_sha = hashlib.sha256(_wire(expression, MAX_REQUEST_BYTES)).hexdigest()
    digest = expression.get("content_digest") if type(expression.get("content_digest")) is str else None
    if any(_reserved_identifier(name) for name in names):
        return _interface_record(candidate_id, codec, "ambiguous", "reserved_identifier",
            payload_text, payload_sha, ast_sha, "typed_expression", digest, constructors, binders,
            retained_roles, None)
    try:
        if codec == "object_relational":
            prepared = prepare_relational_norm_v1(payload_raw, expected_request_sha256=payload_sha)
            projection_value = prepared["native_ast"]
        else:
            prepared = prepare_mixed_relational_norm_v1(payload_raw, expected_request_sha256=payload_sha)
            projection_value = prepared["renderer_ast"]
    except ValueError:
        return _interface_record(candidate_id, codec, "unsupported", "qualified_codec_refuses",
            payload_text, payload_sha, ast_sha, "typed_expression", digest, constructors, binders,
            retained_roles, None)
    if codec == "mixed_relational":
        _need(prepared["native_ast"] is None, "mixed codec must not invent a native AST")
    _need(_wire(prepared["typed_expression"], MAX_REQUEST_BYTES) == _wire(expression, MAX_REQUEST_BYTES),
          "qualified codec replaced the candidate AST")
    _need(prepared["argument_roles"] == retained_roles, "qualified codec dropped or reordered roles")
    projection = hashlib.sha256(_wire(projection_value, MAX_REPORT_BYTES)).hexdigest()
    _need(projection != ast_sha, "codec projection must stay distinct from the candidate AST")
    return _interface_record(candidate_id, codec, "representable", "qualified_codec_accepts_original",
        payload_text, payload_sha, ast_sha, "typed_expression", digest, constructors, binders,
        retained_roles, projection)


def _classify_native(payload, payload_raw, payload_text, payload_sha, candidate_id, toolchain):
    from . import legal_native_ast_preservation as native
    _need(type(toolchain) is str and native._TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    ast_value = payload.get("native_ast")
    _need(type(ast_value) is dict, "complete candidate native AST required")
    constructors, binders = [], []
    _walk_native(ast_value, constructors, binders)
    ast_sha = hashlib.sha256(_wire(ast_value, native.MAX_RECORD_BYTES)).hexdigest()
    if _native_formula_ast_conflict(payload):
        return _interface_record(candidate_id, "native_unary_preservation", "ambiguous",
            "formula_ast_conflict", payload_text, payload_sha, ast_sha, "native_ast", None,
            constructors, binders, None, None)
    try:
        prepared = native.prepare_native_ast_preservation(
            payload_raw, expected_fragment_file_sha256=payload_sha, toolchain=toolchain)
    except ValueError:
        return _interface_record(candidate_id, "native_unary_preservation", "unsupported",
            "qualified_codec_refuses", payload_text, payload_sha, ast_sha, "native_ast", None,
            constructors, binders, None, None)
    _need(hashlib.sha256(_wire(payload["native_ast"], native.MAX_RECORD_BYTES)).hexdigest() == ast_sha,
          "qualified codec replaced the candidate AST")
    projection = native.preparation_sha256(prepared)
    _need(projection != ast_sha, "preservation projection must stay distinct from the candidate AST")
    return _interface_record(candidate_id, "native_unary_preservation", "representable",
        "qualified_codec_accepts_original", payload_text, payload_sha, ast_sha, "native_ast", None,
        constructors, binders, None, projection)


def _interface_one(candidate, seen_ids):
    _keys(candidate, {"candidate_id", "codec", "payload_raw_utf8", "payload_sha256", "toolchain"},
          "candidate interface row")
    candidate_id, codec = candidate["candidate_id"], candidate["codec"]
    _need(type(candidate_id) is str and _CANDIDATE_ID.fullmatch(candidate_id) is not None
          and candidate_id not in seen_ids, "unique focused candidate id required")
    seen_ids.add(candidate_id)
    _need(codec in INTERFACE_CODECS, "unknown candidate codec")
    payload_text = candidate["payload_raw_utf8"]
    _need(type(payload_text) is str and payload_text and "\x00" not in payload_text,
          "exact candidate payload text required")
    try:
        payload_raw = payload_text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("exact candidate payload UTF-8 required") from error
    _digest(candidate["payload_sha256"], "candidate payload")
    _need(hashlib.sha256(payload_raw).hexdigest() == candidate["payload_sha256"],
          "candidate payload SHA256 mismatch")
    _need(0 < len(payload_raw) <= INTERFACE_MAX_BYTES, "bounded candidate payload required")
    try:
        payload = json.loads(payload_raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free candidate payload JSON required") from error
    _wire(payload, INTERFACE_MAX_BYTES)
    _need(type(payload) is dict, "candidate payload object required")
    if codec == "native_unary_preservation":
        return _classify_native(payload, payload_raw, payload_text, candidate["payload_sha256"],
            candidate_id, candidate["toolchain"])
    _need(candidate["toolchain"] is None, "toolchain is only part of the native preservation codec")
    return _classify_relational(codec, payload, payload_raw, payload_text, candidate["payload_sha256"],
        candidate_id)


def prepare_candidate_ir_interface_v1(request_raw, *, expected_request_sha256):
    """Inventory caller-supplied candidate ASTs. Execute no corpus census or compiler."""
    _digest(expected_request_sha256, "candidate interface request")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= INTERFACE_MAX_BYTES,
          "bounded candidate interface request required")
    _need(hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
          "candidate interface request SHA256 mismatch")
    try:
        request = json.loads(request_raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free candidate interface JSON required") from error
    _wire(request, INTERFACE_MAX_BYTES)
    _keys(request, {"schema", "candidates"}, "candidate interface request")
    _need(request["schema"] == INTERFACE_REQUEST_SCHEMA, "candidate interface schema required")
    candidates = request["candidates"]
    _need(type(candidates) is list and 1 <= len(candidates) <= INTERFACE_MAX_CANDIDATES,
          "focused candidate inventory bound exceeded")
    records, seen_ids = [], set()
    for candidate in candidates:
        records.append(_interface_one(candidate, seen_ids))
    result = _interface_result(records)
    _need(set(result) == {
        "candidate_records", "constructor_vocab_census", "codec_projection_budget",
        "unresolved_questions", "reuse_owners"}, "closed candidate interface result required")
    return json.loads(_wire(result, MAX_REPORT_BYTES))


def candidate_ir_interface_sha256(report):
    """Hash the complete inventory without loading a codec."""
    _keys(report, {"candidate_records", "constructor_vocab_census", "codec_projection_budget",
                   "unresolved_questions", "reuse_owners"}, "candidate interface report")
    return hashlib.sha256(_wire(report, MAX_REPORT_BYTES)).hexdigest()


def validate_candidate_ir_interface_v1(report, request_raw, *, expected_request_sha256,
                                       expected_report_sha256):
    """Require an independent inventory pin and complete regeneration."""
    _digest(expected_report_sha256, "candidate interface report")
    _need(candidate_ir_interface_sha256(report) == expected_report_sha256,
          "candidate interface report SHA256 mismatch")
    original = _wire(report, MAX_REPORT_BYTES)
    regenerated = prepare_candidate_ir_interface_v1(
        request_raw, expected_request_sha256=expected_request_sha256)
    _need(_wire(regenerated, MAX_REPORT_BYTES) == original,
          "candidate interface report differs from complete regeneration")
    return regenerated
