"""One authored counting expansion over existing many-sorted typed FOL.

This fixed profile counts distinct objects per explicitly declared event/time
pair. Equality is built-in object identity. It does not interpret statutory
text, choose a time scale, invoke native TDFOL, or execute generated Lean text.
Only bounded duplicate-free requests are admitted before lazy syntax imports.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

REQUEST_SCHEMA = "legal-counted-frame-request/v1"
SCHEMA = "legal-counted-frame-report/v1"
PROFILE = "authored-at-most-three-distinct-per-event-and-time/v1"
MAX_REQUEST_BYTES = 131072
MAX_REPORT_BYTES = 1048576
MAX_NODES = 49
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
_PAIRS = (("x0", "x1"), ("x0", "x2"), ("x0", "x3"),
          ("x1", "x2"), ("x1", "x3"), ("x2", "x3"))
_BINDERS = (("event", "EventFrame"), ("time", "TimeFrame"),
            ("x0", "Object"), ("x1", "Object"),
            ("x2", "Object"), ("x3", "Object"))
AUTHORITY = dict.fromkeys((
    "source_bound", "source_semantics_verified", "legal_roles_verified",
    "counting_frame_verified", "object_identity_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_gold_qualified",
    "evaluation_gold_qualified", "Lean_admitted", "proof_authority",
    "backend_executed", "model_executed", "training_executed",
), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _keys(value, expected, label):
    _need(type(value) is dict and set(value) == set(expected),
          "closed exact fields required: " + label)


def _text(value, label, maximum=256):
    _need(type(value) is str and 0 < len(value) <= maximum and
          not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value),
          "bounded ordinary text required: " + label)


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value, maximum):
    remaining = 20000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 64, "bounded ordinary JSON required")
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


def _read_json(raw, maximum, label):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum,
          "bounded exact " + label + " bytes required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free UTF8 JSON required") from error
    _wire(value, maximum)
    return value


def _declaration():
    return {
        "schema": REQUEST_SCHEMA,
        "interpretation_status": "authored_unreviewed_declaration",
        "maximum": 3,
        "distinctness": "builtin_object_identity",
        "frame": {
            "policy": "per_event_and_time",
            "event": {"variable": "event", "sort": "EventFrame"},
            "time": {"variable": "time", "sort": "TimeFrame",
                     "semantics": "arbitrary_index_without_order"},
        },
        "membership": {"symbol": "Member", "argument_roles": ["object", "event", "time"]},
        "object_variables": ["x0", "x1", "x2", "x3"],
        "source_binding": None,
    }


def _preflight_expression(expression):
    """Close all serialized fields without invoking an operation owner."""
    _keys(expression, {"content_digest", "expression_id", "family", "interface",
        "metadata", "profile", "root", "schema_version", "signature"}, "TypedExpression")
    _text(expression["expression_id"], "expression ID")
    _digest(expression["content_digest"], "typed content")
    _need(type(expression["metadata"]) is dict and not expression["metadata"],
          "expression metadata unsupported")

    def identity(value):
        _keys(value, {"interface", "namespace", "schema_version", "value", "version"}, "identity")
        for label, item in value.items():
            _text(item, "identity " + label)

    def sort(value):
        _keys(value, {"arguments", "kind", "name", "schema_version"}, "sort")
        _need(type(value["arguments"]) is list and not value["arguments"],
              "only atomic or built-in Bool sorts supported")
        for label in ("kind", "name", "schema_version"):
            _text(value[label], "sort " + label)

    identity(expression["family"])
    identity(expression["profile"])
    for label in ("interface", "schema_version"):
        _text(expression[label], "expression " + label)
    signature = expression["signature"]
    _keys(signature, {"family", "features", "interface", "metadata", "profile",
        "schema_version", "signature_id", "sorts", "symbols"}, "signature")
    identity(signature["family"])
    identity(signature["profile"])
    for label in ("interface", "schema_version", "signature_id"):
        _text(signature[label], "signature " + label)
    _need(type(signature["metadata"]) is dict and not signature["metadata"] and
          type(signature["features"]) is list and not signature["features"],
          "signature metadata/features unsupported")
    _need(type(signature["sorts"]) is list and len(signature["sorts"]) == 4 and
          type(signature["symbols"]) is list and len(signature["symbols"]) == 1,
          "exact four-sort one-predicate signature required")
    for item in signature["sorts"]:
        sort(item)
    symbol = signature["symbols"][0]
    _keys(symbol, {"domain", "kind", "metadata", "name", "range", "schema_version"}, "symbol")
    _need(type(symbol["domain"]) is list and len(symbol["domain"]) == 3 and
          type(symbol["metadata"]) is dict and not symbol["metadata"],
          "exact ternary unannotated membership predicate required")
    for label in ("kind", "name", "schema_version"):
        _text(symbol[label], "symbol " + label)
    for item in symbol["domain"]:
        sort(item)
    sort(symbol["range"])
    seen = set()

    def node(value, depth):
        _keys(value, {"arguments", "binders", "kind", "metadata", "node_id",
                      "schema_version", "sort", "symbol"}, "node")
        _need(depth <= 32 and len(seen) < MAX_NODES, "fixed AST node/depth bound exceeded")
        _text(value["node_id"], "node ID")
        _need(value["node_id"] not in seen, "node IDs must be globally unique")
        seen.add(value["node_id"])
        _need(type(value["kind"]) is str and value["kind"] in {
            "variable", "predicate", "equality", "and", "or", "implies", "forall"},
            "unsupported counted-frame node kind")
        _need(type(value["metadata"]) is dict and not value["metadata"] and
              type(value["symbol"]) is str, "unannotated exact node required")
        _text(value["schema_version"], "node schema")
        sort(value["sort"])
        _need(type(value["arguments"]) is list and len(value["arguments"]) <= 3 and
              type(value["binders"]) is list and len(value["binders"]) <= 1,
              "bounded node arguments and single binder required")
        for binder in value["binders"]:
            _keys(binder, {"name", "schema_version", "sort"}, "binder")
            _text(binder["name"], "binder name")
            _text(binder["schema_version"], "binder schema")
            sort(binder["sort"])
        for child in value["arguments"]:
            node(child, depth + 1)

    node(expression["root"], 0)
    _need(len(seen) == MAX_NODES, "exact 49-node counting expansion required")


def _parse(request_raw, expected_request_sha256):
    _digest(expected_request_sha256, "request")
    _need(type(request_raw) is bytes and len(request_raw) <= MAX_REQUEST_BYTES,
          "bounded exact request bytes required")
    _need(hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
          "request SHA256 mismatch")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "request")
    fixed = _declaration()
    _keys(request, set(fixed) | {"expression"}, "request")
    _need(type(request["maximum"]) is int and request["maximum"] == 3,
          "maximum must be the exact integer three")
    for key, expected in fixed.items():
        _need(_wire(request[key], MAX_REQUEST_BYTES) == _wire(expected, MAX_REQUEST_BYTES),
              "unsupported or altered counted-frame declaration: " + key)
    _preflight_expression(request["expression"])
    return request


def _owners():
    from .. import parsers, syntax_core
    from ..families import namespaces
    from ..syntax_core import algebra, ast, contracts, diagnostics, lexer, registry, signatures
    from ..parsers import fol

    global _OWNER_PINS
    modules = (parsers, syntax_core, namespaces, algebra, ast, contracts,
               diagnostics, lexer, registry, signatures, fol)
    pins = {str(Path(module.__file__).resolve()):
            hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules}
    self_path = str(Path(__file__).resolve())
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "counted-frame producer changed since import")
    pins[self_path] = _SELF_PIN
    if _OWNER_PINS is None:
        _OWNER_PINS = dict(pins)
    _need(_OWNER_PINS == pins, "counted-frame operation owner changed since first use")
    return ast, signatures, algebra, contracts, fol, dict(pins)


def _fixed_expression(ast, signatures, *, expression_id="authored:counted-frame:expression",
                      signature_id="authored:counted-frame:signature"):
    sorts = {name: signatures.LogicSort(name) for name in ("Object", "EventFrame", "TimeFrame")}
    serial = 0

    def nid():
        nonlocal serial
        serial += 1
        return "authored:counted-frame:node:" + str(serial)

    def variable(name):
        sort_name = dict(_BINDERS)[name]
        return ast.mk_variable(nid(), name, sorts[sort_name])

    def fold(constructor, nodes):
        result = nodes[0]
        for child in nodes[1:]:
            result = constructor(nid(), result, child)
        return result

    members = [ast.mk_predicate(nid(), "Member", (
        variable(name), variable("event"), variable("time")))
        for name in ("x0", "x1", "x2", "x3")]
    identities = [ast.mk_equality(nid(), variable(left), variable(right)) for left, right in _PAIRS]
    body = ast.mk_implies(nid(), fold(ast.mk_and, members), fold(ast.mk_or, identities))
    for name, sort_name in reversed(_BINDERS):
        body = ast.mk_forall(nid(), (ast.Binder(name, sorts[sort_name]),), body)
    signature = signatures.LogicSignature(signature_id, family="first_order", profile="many_sorted",
        sorts=tuple(sorts.values()), symbols=(signatures.declare_predicate("Member", (
            sorts["Object"], sorts["EventFrame"], sorts["TimeFrame"])),))
    return ast.TypedExpression(expression_id, body, signature)


def authored_counted_frame_request():
    """Construct one authored fixture declaration; this is not a statutory target."""
    ast, signatures, _, _, _, before = _owners()
    request = _declaration()
    request["expression"] = _fixed_expression(ast, signatures).to_dict()
    _parse(_wire(request, MAX_REQUEST_BYTES), hashlib.sha256(_wire(request, MAX_REQUEST_BYTES)).hexdigest())
    _need(_owners()[-1] == before, "counted-frame owners changed during construction")
    return request


def _recognize(request, ast, signatures):
    original = request["expression"]
    try:
        expression = ast.TypedExpression.from_dict(original)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise ValueError("valid exact TypedExpression required") from error
    _need(_wire(expression.to_dict(), MAX_REQUEST_BYTES) == _wire(original, MAX_REQUEST_BYTES),
          "TypedExpression must survive exact serialized reconstruction")
    expected = _fixed_expression(ast, signatures, expression_id=expression.expression_id,
                                 signature_id=expression.signature.signature_id)
    _need(expression.is_formula and not expression.metadata and expression.range is None and
          expression.family == expected.family and expression.profile == expected.profile,
          "exact unannotated first_order/many_sorted expression required")
    _need(_wire(expression.signature.to_dict(), MAX_REQUEST_BYTES) ==
          _wire(expected.signature.to_dict(), MAX_REQUEST_BYTES),
          "exact fixed many-sorted membership signature required")
    mapping, binders = [], []

    def visit(node, reference, path):
        _need(node.kind is reference.kind and node.symbol == reference.symbol and
              node.sort == reference.sort and node.binders == reference.binders and
              len(node.arguments) == len(reference.arguments) and not node.metadata and
              node.range is None and node.extension is None,
              "fixed counted-frame expansion differs at " + path)
        mapping.append({"typed_path": path, "node_id": node.node_id,
                        "kind": node.kind.value, "sort": node.sort.name})
        for index, binder in enumerate(node.binders):
            binders.append({"typed_path": path + "/binders/" + str(index),
                            "variable": binder.name, "sort": binder.sort.name})
        for index, (child, expected_child) in enumerate(zip(node.arguments, reference.arguments, strict=True)):
            visit(child, expected_child, path + "/arguments/" + str(index))

    visit(expression.root, expected.root, "/root")
    _need(len(mapping) == MAX_NODES and not expression.root.free_variable_names(),
          "closed exact counting expansion required")
    return expression, mapping, binders


def _lean_body():
    # Fixed names and a recognized fixed AST prevent identifier/text injection.
    return """set_option autoImplicit false

def countedAtMostThree {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop) : Prop :=
  ∀ (event : EventFrame) (time : TimeFrame)
    (x0 x1 x2 x3 : Object),
    (((member x0 event time ∧ member x1 event time) ∧
      member x2 event time) ∧ member x3 event time) →
    (((((x0 = x1 ∨ x0 = x2) ∨ x0 = x3) ∨ x1 = x2) ∨
      x1 = x3) ∨ x2 = x3)
"""


def _grouped_syntax(signature, fol):
    # The shared printer omits same-precedence AND/OR parentheses, and its
    # parser reads the resulting chains as n-ary nodes. Tighten grouping only
    # for this already recognized binary profile; retain the original printer
    # for all operators, terms, names, binders and grammar decisions.
    class BinaryGroupingPrinter(fol.CanonicalFOLPrinter):
        def _print_node(self, node, parent_prec):
            if node.kind.value in {"and", "or"}:
                return "(" + super()._print_node(node, 0) + ")"
            return super()._print_node(node, parent_prec)

    syntax = fol.CanonicalFOLSyntax(signature)
    syntax.printer = syntax.parser.printer = BinaryGroupingPrinter()
    return syntax


def prepare_counted_frame(request_raw, *, expected_request_sha256):
    """Prepare the fixed authored declaration; execute no backend or model."""
    request = _parse(request_raw, expected_request_sha256)
    ast, signatures, algebra, contracts, fol, before = _owners()
    expression, mapping, binders = _recognize(request, ast, signatures)
    syntax = _grouped_syntax(expression.signature, fol)
    canonical = syntax.print(expression)
    limits = contracts.ParseLimits(max_input_bytes=16384, max_tokens=2048, max_depth=64,
        max_diagnostics=8, max_ambiguities=8, max_time_ms=1000, max_memory_bytes=8388608)
    first = syntax.parse_text(canonical, document_id="doc:counted-frame:first",
                              expression_id="expr:counted-frame:first", limits=limits)
    _need(first.ok and first.root is not None and not first.errors,
          "canonical FOL first parse failed")
    _need(algebra.alpha_equivalent(expression.root, first.root),
          "original typed tree differs from canonical FOL first parse")
    printed = syntax.print(first.root)
    second = syntax.parse_text(printed, document_id="doc:counted-frame:second",
                               expression_id="expr:counted-frame:second", limits=limits)
    _need(second.ok and second.root is not None and not second.errors,
          "canonical FOL second parse failed")
    _need(printed == canonical and syntax.print(second.root) == canonical and
          algebra.alpha_equivalent(first.root, second.root) and
          algebra.alpha_equivalent(expression.root, second.root),
          "canonical FOL print/reparse differs from original typed tree")
    lean_body = _lean_body()
    report = {
        "schema": SCHEMA, "profile": PROFILE,
        "status": "authored_unreviewed_counted_frame_prepared",
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256,
        "typed_expression": expression.to_dict(),
        "typed_expression_content_digest": expression.content_digest,
        "typed_expression_sha256": hashlib.sha256(_wire(expression.to_dict(), MAX_REQUEST_BYTES)).hexdigest(),
        "frame": request["frame"], "membership": request["membership"],
        "distinctness": request["distinctness"], "maximum": 3,
        "identity_pairs": [list(pair) for pair in _PAIRS],
        "binder_ledger": binders, "structural_mapping": mapping,
        "counts": {"nodes": 49, "quantifiers": 6, "membership_occurrences": 4,
                   "equality_occurrences": 6, "variable_occurrences": 24},
        "canonical_fol": canonical,
        "canonical_fol_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "fol_receipt": {
            "notation": fol.CANONICAL_FOL_NOTATION_ID,
            "notation_version": fol.CANONICAL_FOL_NOTATION_VERSION,
            "printer": "CanonicalFOLPrinter_with_explicit_binary_AND_OR_grouping",
            "binary_connective_grouping_preserved": True,
            "first_parse_status": first.status.value, "second_parse_status": second.status.value,
            "original_to_first_alpha_equivalent": True,
            "first_to_second_alpha_equivalent": True,
            "original_to_second_alpha_equivalent": True,
            "canonical_print_stable": True, "parse_limits": limits.to_dict(),
            "first_root_sha256": hashlib.sha256(_wire(first.root.to_dict(), MAX_REQUEST_BYTES)).hexdigest(),
            "second_root_sha256": hashlib.sha256(_wire(second.root.to_dict(), MAX_REQUEST_BYTES)).hexdigest(),
        },
        "lowering_route": "recognized_typed_FOL_to_specialized_Lean_text",
        "lean_body": lean_body,
        "lean_body_sha256": hashlib.sha256(lean_body.encode("utf-8")).hexdigest(),
        "producer_pins": before,
        "source_binding": None, "source_bound": False, "source_translation_performed": False,
        "native_TDFOL_route_used": False, "native_build_executed": False,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "graph_admissions": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "authority": dict(AUTHORITY),
        "assumptions": [
            "Caller supplies an authored declaration, not an interpretation selected from statutory text.",
            "Membership is a relation on arbitrary Object, EventFrame and TimeFrame carriers.",
            "Each object is counted by built-in identity within the same event/time pair, without occurrence multiplicity.",
            "TimeFrame is an arbitrary index with no order, duration, simultaneity or calendar interpretation.",
            "No nonempty membership, temporal aggregation, deontic operator or source meaning is asserted.",
            "Canonical FOL preserves typed equality; the native TDFOL family route is not used.",
            "A local CanonicalFOLPrinter specialization retains explicit binary AND/OR grouping; original-to-parsed alpha checks remain exact.",
            "Generated Lean text has not been compiled or admitted; finite controls are separately authored illustrations.",
        ],
    }
    _wire(report, MAX_REPORT_BYTES)
    _need(_owners()[-1] == before, "counted-frame owners changed during preparation")
    return report


def counted_frame_report_sha256(report):
    """Hash complete ordinary report identity without loading operation owners."""
    return hashlib.sha256(_wire(report, MAX_REPORT_BYTES)).hexdigest()


def validate_counted_frame(report, request_raw, *, expected_request_sha256,
                           expected_report_sha256):
    """Require independently pinned report identity and complete public replay."""
    _digest(expected_report_sha256, "report")
    # Reject request fields/paths before lazy owners even when a report is offered.
    _parse(request_raw, expected_request_sha256)
    if type(report) is bytes:
        report = _read_json(report, MAX_REPORT_BYTES, "report")
    _need(type(report) is dict, "ordinary report object or exact JSON bytes required")
    _need(counted_frame_report_sha256(report) == expected_report_sha256,
          "report SHA256 mismatch")
    regenerated = prepare_counted_frame(request_raw, expected_request_sha256=expected_request_sha256)
    _need(_wire(report, MAX_REPORT_BYTES) == _wire(regenerated, MAX_REPORT_BYTES),
          "counted-frame report differs from complete authoritative replay")
    return regenerated
