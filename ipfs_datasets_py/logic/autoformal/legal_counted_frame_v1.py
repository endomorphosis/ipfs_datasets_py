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


# This additive archival transport has its own grammar.  It neither widens the
# Object/Bool compact-content profile nor migrates a numerical checkpoint.
COMPACT_CONTENT_SCHEMA = "legal-counted-compact-content/v1"
COMPACT_CONTEXT_SCHEMA = "legal-counted-compact-context/v1"
COMPACT_IDENTITY_SCHEMA = "legal-counted-compact-identity/v1"
COMPACT_PROJECTION_SCHEMA = "legal-counted-compact-projection/v1"
COMPACT_PREDICTION_SCHEMA = "legal-counted-compact-prediction/v1"
COMPACT_RECONSTRUCTION_SCHEMA = "legal-counted-compact-reconstruction/v1"
COMPACT_CODEC_SCHEMA = "legal-counted-compact-token-codec/v1"
COMPACT_ENCODING_SCHEMA = "legal-counted-compact-token-encoding/v1"
COMPACT_CANDIDATE_SCHEMA = "legal-counted-compact-token-candidate/v1"
COMPACT_PROFILE = "authored-at-most-three-many-sorted-compact/v1"
MAX_COMPACT_SEQUENCE_TOKENS = 512
COMPACT_PAD_ID, COMPACT_BOS_ID, COMPACT_EOS_ID = 0, 1, 2
_COMPACT_COUNTS = {"nodes": 49, "quantifiers": 6, "membership_occurrences": 4,
                   "equality_occurrences": 6, "variable_occurrences": 24}
_COMPACT_AUTHORITY = {**AUTHORITY, **dict.fromkeys((
    "training_qualified", "checkpoint_compatibility_verified",
    "permitted_inference_context_verified", "source_encoder_verified",
), False)}
_COMPACT_LIMITATIONS = [
    "Only the existing fixed authored counted frame is represented; no general many-sorted or numerical decoder profile is introduced.",
    "Projection context is target-derived declaration data, not independently permitted source-only model input.",
    "Canonical request reconstruction preserves complete original identities; original transport whitespace is not reconstructed.",
    "Lexical transport and genuine typed replay supply finite engineering evidence, not source meaning, training, convergence, checkpoint compatibility or Lean admission.",
    "Named source fences do not attest executed bytecode, an interpreter/third-party closure or a hermetic runtime.",
]


def _compact_capture(value, maximum=MAX_REPORT_BYTES):
    """Detach bounded ordinary JSON before allocating complete serialized text."""
    remaining, budget, active = 20000, maximum, set()

    def charge(size):
        nonlocal budget
        budget -= size
        _need(budget >= 0, "complete counted compact byte bound exceeded")

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 64, "counted compact item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active, "cyclic counted compact JSON refused")
            _need(len(item) <= remaining, "counted compact population bound exceeded")
            active.add(id(item))
            charge(2 + max(0, len(item) - 1))
            try:
                if type(item) is dict:
                    result = {}
                    for key, child in item.items():
                        _need(type(key) is str, "ordinary counted compact string keys required")
                        charge(1)
                        result[visit(key, depth + 1)] = visit(child, depth + 1)
                    return result
                return [visit(child, depth + 1) for child in item]
            finally:
                active.remove(id(item))
        if type(item) is str:
            _need(len(item) <= maximum, "bounded counted compact text required")
            charge(2)
            for character in item:
                code = ord(character)
                _need(code != 0 and not 0xD800 <= code <= 0xDFFF,
                      "ordinary non-NUL scalar UTF8 required")
                if character in '\"\\\b\f\n\r\t':
                    charge(2)
                elif code < 32:
                    charge(6)
                else:
                    charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded counted compact plain integer required")
            charge(len(str(item)))
        else:
            raise ValueError("ordinary counted compact JSON without floats required")
        return item

    return visit(value, 0)


def _compact_wire(value, maximum=MAX_REPORT_BYTES):
    captured = _compact_capture(value, maximum)
    raw = json.dumps(captured, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= maximum, "complete counted compact JSON bound exceeded")
    return raw


def _compact_hash(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_compact_wire(value, maximum)).hexdigest()


def _compact_parse(raw, expected, label):
    _digest(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          "bounded exact counted compact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, label + " raw SHA256 mismatch")
    return _compact_capture(_read_json(raw, MAX_REQUEST_BYTES, label), MAX_REQUEST_BYTES)


def _compact_context():
    declaration = _declaration()
    return {
        "schema": COMPACT_CONTEXT_SCHEMA,
        "sorts": ["Object", "EventFrame", "TimeFrame"],
        "predicate": {"name": "Member", "domain": ["Object", "EventFrame", "TimeFrame"],
                      "range": "Bool"},
        **{key: declaration[key] for key in (
            "frame", "membership", "distinctness", "maximum", "object_variables")},
    }


def _compact_fixed_content():
    def variable(index):
        return ["variable", index]

    def fold(kind, items):
        result = items[0]
        for item in items[1:]:
            result = [kind, result, item]
        return result

    membership = [["predicate", 0, [variable(index), variable(0), variable(1)]]
                  for index in range(2, 6)]
    names = {name: index for index, (name, _) in enumerate(_BINDERS)}
    equalities = [["equality", variable(names[left]), variable(names[right])]
                  for left, right in _PAIRS]
    tree = ["implies", fold("and", membership), fold("or", equalities)]
    for index in reversed(range(len(_BINDERS))):
        tree = ["forall", index, _BINDERS[index][1], tree]
    return {"schema": COMPACT_CONTENT_SCHEMA, "tree": tree}


def _compact_checked_inputs(content_raw, context_raw, expected_content_sha256,
                            expected_context_sha256):
    content = _compact_parse(content_raw, expected_content_sha256, "content")
    context = _compact_parse(context_raw, expected_context_sha256, "context")
    _need(_compact_wire(content) == _compact_wire(_compact_fixed_content()),
          "exact closed many-sorted counted content required")
    _need(_compact_wire(context) == _compact_wire(_compact_context()),
          "exact counted frame, signature and ordered-role context required")
    return content, context


def _compact_fence(before, observed=()):
    for original, detached, token in observed:
        _need(_compact_wire(original) == token and _compact_wire(detached) == token,
              "counted compact caller or captured input changed")
    _need(_owners()[-1] == before, "counted compact producers changed")


def _compact_finish(report, before, observed=()):
    _compact_fence(before, observed)
    result = _compact_capture(report)
    _compact_wire(result)
    _compact_fence(before, observed)
    return result


def _compact_base(schema, before):
    return {"schema": schema, "profile": COMPACT_PROFILE,
            "producer_pins": dict(before), "authority": dict(_COMPACT_AUTHORITY),
            "training_mask": 0, "evaluation_gold_mask": 0,
            "checkpoint_compatibility_verified": False,
            "limitations": list(_COMPACT_LIMITATIONS)}


def _compact_project_tree(root):
    node_ids, binder_names = [], []

    def walk(node, bound):
        node_ids.append(node["node_id"])
        kind = node["kind"]
        if kind == "variable":
            _need(node["symbol"] in bound, "counted compact variable must be lexically bound")
            return [kind, bound[node["symbol"]]]
        if kind == "predicate":
            return [kind, 0, [walk(child, bound) for child in node["arguments"]]]
        if kind == "forall":
            binder = node["binders"][0]
            index = len(binder_names)
            binder_names.append(binder["name"])
            return [kind, index, binder["sort"]["name"],
                    walk(node["arguments"][0], {**bound, binder["name"]: index})]
        return [kind, *(walk(child, bound) for child in node["arguments"])]

    return {"schema": COMPACT_CONTENT_SCHEMA, "tree": walk(root, {})}, node_ids, binder_names


def _compact_identity(request, content, context, raw_sha):
    expression = request["expression"]
    _, node_ids, binder_names = _compact_project_tree(expression["root"])
    return {"schema": COMPACT_IDENTITY_SCHEMA,
            "expression_id": expression["expression_id"],
            "signature_id": expression["signature"]["signature_id"],
            "node_ids": node_ids, "binder_names": binder_names,
            "content_sha256": _compact_hash(content), "context_sha256": _compact_hash(context),
            "original_request_sha256": raw_sha,
            "original_request_canonical_sha256": _compact_hash(request),
            "original_expression_sha256": _compact_hash(expression)}


def project_counted_frame_request_v1(request_raw, *, expected_request_sha256):
    """Project the fixed authored frame; target-derived context stays a label."""
    request = _parse(request_raw, expected_request_sha256)
    owners = _owners()
    before = owners[-1]
    checked = prepare_counted_frame(request_raw, expected_request_sha256=expected_request_sha256)
    _compact_fence(before)
    _need(_compact_wire(checked["request"]) == _compact_wire(request),
          "public counted preparation changed its original request")
    _need(_compact_wire(checked["counts"]) == _compact_wire(_COMPACT_COUNTS) and
          checked["producer_pins"] == before,
          "public counted preparation changed counts or producer identities")
    content, _, _ = _compact_project_tree(checked["typed_expression"]["root"])
    context = _compact_context()
    _need(_compact_wire(content) == _compact_wire(_compact_fixed_content()),
          "public counted preparation differs from fixed compact content")
    identity = _compact_identity(request, content, context, expected_request_sha256)
    restored, _, restored_checked = _compact_prediction(content, context, owners, before, identity)
    _need(_compact_wire(restored) == _compact_wire(request) and
          _compact_wire(restored_checked["typed_expression"]) ==
          _compact_wire(checked["typed_expression"]),
          "counted compact projection is not an exact archival inverse")
    result = _compact_base(COMPACT_PROJECTION_SCHEMA, before)
    result.update(status="authored_counted_content_projected_unreviewed", content=content,
        context=context, identity_sidecar=identity,
        content_sha256=identity["content_sha256"], context_sha256=identity["context_sha256"],
        identity_sha256=_compact_hash(identity), original_request_sha256=expected_request_sha256,
        original_request_canonical_sha256=identity["original_request_canonical_sha256"],
        original_expression_sha256=identity["original_expression_sha256"],
        counted_report=checked, counts=dict(_COMPACT_COUNTS),
        context_origin="target_derived_authored_declaration",
        roundtrip_receipt={"canonical_request_exact": True, "typed_expression_exact": True,
            "node_identity_exact": True, "original_transport_whitespace_restored": False})
    return _compact_finish(result, before)


def validate_counted_frame_projection_v1(report, request_raw, *, expected_report_sha256,
                                         expected_request_sha256):
    """Independently pin the whole projection and repeat original public replay."""
    _digest(expected_report_sha256, "counted compact projection")
    _parse(request_raw, expected_request_sha256)
    original = report
    if type(report) is bytes:
        report = _read_json(report, MAX_REPORT_BYTES, "counted compact projection")
    captured = _compact_capture(report)
    token = _compact_wire(captured)
    _need(hashlib.sha256(token).hexdigest() == expected_report_sha256,
          "counted compact projection SHA256 mismatch")
    observed = () if type(original) is bytes else ((original, captured, token),)
    before = _owners()[-1]
    _compact_fence(before, observed)
    regenerated = project_counted_frame_request_v1(request_raw,
        expected_request_sha256=expected_request_sha256)
    _compact_fence(before, observed)
    _need(token == _compact_wire(regenerated), "counted compact projection differs from public replay")
    return _compact_finish(regenerated, before, observed)


def _compact_materialize(owners, identity=None, seed=None):
    ast, signatures = owners[:2]
    seed = seed or _compact_hash({"content": _compact_fixed_content(), "context": _compact_context()})
    expression = _fixed_expression(ast, signatures,
        expression_id=identity["expression_id"] if identity else "counted-compact-expression:" + seed,
        signature_id=identity["signature_id"] if identity else "counted-compact-signature:" + seed).to_dict()
    serial = 0

    def identify(node):
        nonlocal serial
        node["node_id"] = identity["node_ids"][serial] if identity else "counted-compact-node:" + seed + ":" + str(serial)
        serial += 1
        for child in node["arguments"]:
            identify(child)

    identify(expression["root"])
    _need(serial == MAX_NODES, "complete counted compact node population required")
    # Existing TypedExpression recomputes its own digest after identity changes.
    expression.pop("content_digest")
    expression = ast.TypedExpression.from_dict(expression).to_dict()
    return {**_declaration(), "expression": expression}


def _compact_prediction(content, context, owners, before, identity=None):
    request = _compact_materialize(owners, identity)
    raw = _compact_wire(request, MAX_REQUEST_BYTES)
    checked = prepare_counted_frame(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())
    _compact_fence(before)
    _need(_compact_wire(checked["counts"]) == _compact_wire(_COMPACT_COUNTS) and
          checked["producer_pins"] == before and
          _compact_wire(checked["request"]) == raw,
          "public counted decoding changed request, counts or producer identities")
    projected, _, _ = _compact_project_tree(checked["typed_expression"]["root"])
    _need(_compact_wire(projected) == _compact_wire(content) and
          _compact_wire(context) == _compact_wire(_compact_context()),
          "decoded typed frame differs from complete compact inputs")
    return request, raw, checked


def decode_counted_frame_content_v1(content_raw, context_raw, *, expected_content_sha256,
                                   expected_context_sha256):
    """Decode this fixed content/context without a target, source or sidecar."""
    content, context = _compact_checked_inputs(content_raw, context_raw,
        expected_content_sha256, expected_context_sha256)
    owners = _owners()
    before = owners[-1]
    request, raw, checked = _compact_prediction(content, context, owners, before)
    result = _compact_base(COMPACT_PREDICTION_SCHEMA, before)
    result.update(status="authored_counted_content_decoded_unreviewed", request=request,
        request_sha256=hashlib.sha256(raw).hexdigest(), counted_report=checked,
        content_sha256=_compact_hash(content), context_sha256=_compact_hash(context),
        content_raw_sha256=expected_content_sha256, context_raw_sha256=expected_context_sha256,
        counts=dict(_COMPACT_COUNTS), identity_mode="generated")
    return _compact_finish(result, before)


def reconstruct_counted_frame_request_v1(content_raw, context_raw, identity_raw,
                                         original_request_raw, *, expected_content_sha256,
                                         expected_context_sha256, expected_identity_sha256,
                                         expected_original_request_sha256):
    """Restore exact canonical original identities against independent raw input."""
    content, context = _compact_checked_inputs(content_raw, context_raw,
        expected_content_sha256, expected_context_sha256)
    identity = _compact_parse(identity_raw, expected_identity_sha256, "identity")
    original = _parse(original_request_raw, expected_original_request_sha256)
    _keys(identity, {"schema", "expression_id", "signature_id", "node_ids", "binder_names",
        "content_sha256", "context_sha256", "original_request_sha256",
        "original_request_canonical_sha256", "original_expression_sha256"}, "counted compact identity")
    _need(identity["schema"] == COMPACT_IDENTITY_SCHEMA, "counted compact identity schema differs")
    _need(_compact_wire(identity) == _compact_wire(
        _compact_identity(original, content, context, expected_original_request_sha256)),
        "identity sidecar differs from independently pinned complete original request")
    owners = _owners()
    before = owners[-1]
    original_checked = prepare_counted_frame(original_request_raw,
        expected_request_sha256=expected_original_request_sha256)
    _compact_fence(before)
    request, raw, checked = _compact_prediction(content, context, owners, before, identity)
    _need(_compact_wire(request) == _compact_wire(original) and
          _compact_wire(checked["typed_expression"]) == _compact_wire(original_checked["typed_expression"]),
          "counted compact archival reconstruction is not exact")
    result = _compact_base(COMPACT_RECONSTRUCTION_SCHEMA, before)
    result.update(status="authored_counted_request_reconstructed_unreviewed", request=request,
        request_sha256=hashlib.sha256(raw).hexdigest(), counted_report=checked,
        original_request_sha256=expected_original_request_sha256,
        original_request_canonical_sha256=_compact_hash(original),
        content_sha256=_compact_hash(content), context_sha256=_compact_hash(context),
        identity_sha256=_compact_hash(identity), counts=dict(_COMPACT_COUNTS), identity_mode="restored")
    result.update(content_raw_sha256=expected_content_sha256,
        context_raw_sha256=expected_context_sha256, identity_raw_sha256=expected_identity_sha256)
    return _compact_finish(result, before)


def _compact_fixed_codec():
    literals = ("schema", "tree", COMPACT_CONTENT_SCHEMA, "variable", "predicate",
                "equality", "forall", "and", "or", "implies", "Object", "EventFrame", "TimeFrame")
    lexical = {json.dumps(value, ensure_ascii=False) for value in literals}
    lexical.update("{}[],:")
    lexical.update(str(index) for index in range(6))
    vocabulary = ["<pad>", "<bos>", "<eos>", *sorted(lexical)]
    return {"schema": COMPACT_CODEC_SCHEMA, "profile": COMPACT_PROFILE,
        "format": "fixed-json-lexical-counted-content/v1",
        "content_schema": COMPACT_CONTENT_SCHEMA, "context_schema": COMPACT_CONTEXT_SCHEMA,
        "vocabulary": vocabulary, "vocabulary_size": len(vocabulary),
        "pad_id": COMPACT_PAD_ID, "bos_id": COMPACT_BOS_ID, "eos_id": COMPACT_EOS_ID,
        "max_sequence_tokens": MAX_COMPACT_SEQUENCE_TOKENS,
        "integer_min": 0, "integer_max": 5, "max_nodes": 49, "max_binders": 6,
        "checkpoint_compatibility_verified": False, "numerical_head_compatible": False}


def build_counted_frame_token_codec_v1():
    """Publish a fixed counted-only lexical codec; use no model or checkpoint."""
    _compact_self_fence()
    result = _compact_capture(_compact_fixed_codec())
    _compact_wire(result)
    _compact_self_fence()
    return result


def _compact_self_fence():
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "counted compact producer changed since import")


def counted_frame_token_codec_sha256(codec):
    """Hash only the complete exact counted codec, never a legacy codec alias."""
    _compact_self_fence()
    captured = _compact_capture(codec)
    token = _compact_wire(captured)
    _need(token == _compact_wire(_compact_fixed_codec()), "exact counted compact codec required")
    _need(_compact_wire(codec) == token, "counted compact codec changed during hashing")
    _compact_self_fence()
    return hashlib.sha256(token).hexdigest()


def _compact_codec(codec, expected):
    _digest(expected, "counted compact codec")
    captured = _compact_capture(codec)
    token = _compact_wire(captured)
    _need(hashlib.sha256(token).hexdigest() == expected and
          token == _compact_wire(_compact_fixed_codec()), "independent exact counted codec SHA256 differs")
    return captured, (codec, captured, token)


def _compact_lexical(content):
    raw = _compact_wire(content, MAX_REQUEST_BYTES).decode("utf-8")
    lexical = re.findall(r'"[^"\\\x00-\x1f]*"|[0-5]|[{}\[\],:]', raw)
    _need("".join(lexical) == raw, "complete counted compact lexical coverage differs")
    return lexical


def _compact_ids(generated_ids):
    _need(type(generated_ids) is list and 2 <= len(generated_ids) <= MAX_COMPACT_SEQUENCE_TOKENS,
          "complete counted token ID list within512 required; no truncation")
    vocabulary_size = len(_compact_fixed_codec()["vocabulary"])
    _need(all(type(item) is int and 0 <= item < vocabulary_size
              for item in generated_ids), "plain in-range counted token integers required")
    captured = list(generated_ids)
    _need(captured[0] == COMPACT_BOS_ID and captured[-1] == COMPACT_EOS_ID and
          all(item >= 3 for item in captured[1:-1]),
          "single BOS and terminal EOS without PAD/interior specials required")
    return captured, (generated_ids, captured, _compact_wire(captured))


def encode_counted_frame_tokens_v1(content_raw, context_raw, *, expected_content_sha256,
                                   expected_context_sha256, codec, expected_codec_sha256):
    """Encode complete fixed counted content after genuine typed preparation."""
    content, context = _compact_checked_inputs(content_raw, context_raw,
        expected_content_sha256, expected_context_sha256)
    fixed, observed = _compact_codec(codec, expected_codec_sha256)
    before = _owners()[-1]
    _compact_fence(before, (observed,))
    prediction = decode_counted_frame_content_v1(content_raw, context_raw,
        expected_content_sha256=expected_content_sha256, expected_context_sha256=expected_context_sha256)
    _compact_fence(before, (observed,))
    lexical = _compact_lexical(content)
    indices = {token: index for index, token in enumerate(fixed["vocabulary"])}
    _need(all(token in indices for token in lexical), "counted content outside fixed vocabulary")
    ids, _ = _compact_ids([COMPACT_BOS_ID, *(indices[token] for token in lexical), COMPACT_EOS_ID])
    result = _compact_base(COMPACT_ENCODING_SCHEMA, before)
    result.update(status="encoded_unreviewed_counted_content", target_ids=ids,
        lexical_tokens=lexical, lexical_token_count=len(lexical), total_token_count=len(ids),
        canonical_content_raw_utf8=_compact_wire(content).decode("utf-8"),
        content_sha256=_compact_hash(content), context_sha256=_compact_hash(context),
        codec_sha256=expected_codec_sha256, prediction=prediction, counts=dict(_COMPACT_COUNTS))
    result.update(content_raw_sha256=expected_content_sha256,
        context_raw_sha256=expected_context_sha256)
    return _compact_finish(result, before, (observed,))


def decode_counted_frame_tokens_v1(generated_ids, context_raw, *, expected_context_sha256,
                                   codec, expected_codec_sha256):
    """Decode one complete lexical sequence, without original identities/target."""
    fixed, codec_observed = _compact_codec(codec, expected_codec_sha256)
    ids, ids_observed = _compact_ids(generated_ids)
    observed = (codec_observed, ids_observed)
    raw = "".join(fixed["vocabulary"][index] for index in ids[1:-1]).encode("utf-8")
    content_sha = hashlib.sha256(raw).hexdigest()
    content, context = _compact_checked_inputs(raw, context_raw, content_sha, expected_context_sha256)
    _need(_compact_wire(content) == raw, "canonical counted token JSON required; no aliases")
    _need([fixed["vocabulary"][index] for index in ids[1:-1]] == _compact_lexical(content),
          "counted token lexical segmentation differs")
    before = _owners()[-1]
    _compact_fence(before, observed)
    prediction = decode_counted_frame_content_v1(raw, context_raw,
        expected_content_sha256=content_sha, expected_context_sha256=expected_context_sha256)
    _compact_fence(before, observed)
    result = _compact_base(COMPACT_CANDIDATE_SCHEMA, before)
    result.update(status="valid_candidate", generated_ids=ids,
        canonical_content_raw_utf8=raw.decode("utf-8"), content_sha256=content_sha,
        context_sha256=_compact_hash(context), codec_sha256=expected_codec_sha256,
        prediction=prediction, counts=dict(_COMPACT_COUNTS),
        framing={"bos_present": True, "eos_terminal": True, "token_ids_valid": True,
                 "interior_special_tokens": False, "terminated": True})
    result["context_raw_sha256"] = expected_context_sha256
    return _compact_finish(result, before, observed)
