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
