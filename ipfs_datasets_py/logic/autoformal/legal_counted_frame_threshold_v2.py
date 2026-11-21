"""Three authored counting targets through the existing typed FOL owners.

This separate label factory preserves the fixed-three v1 source and codec.
It interprets no legal text, admits no training data, and adds no model, codec,
parser, semantic backend or Lean lowering. Requests declare a bound explicitly.
"""
from __future__ import annotations

import hashlib
import importlib
from itertools import combinations
from pathlib import Path

REQUEST_SCHEMA = "legal-counted-frame-threshold-request/v2"
SCHEMA = "legal-counted-frame-threshold-report/v2"
PROFILE = "authored-at-most-one-to-three-distinct-per-event-and-time/v2"
CONTEXT_SCHEMA = "legal-counted-frame-signature-context/v2"
_SELF_PATH = Path(__file__).absolute()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_BASE_SHA = "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"
_BASE_NAME = "ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1"


def _need(value, message):
    if not value:
        raise ValueError(message)


def _base():
    base = importlib.import_module(_BASE_NAME)
    path = _SELF_PATH.with_name("legal_counted_frame_v1.py")
    _need(type(getattr(base, "__file__", None)) is str
          and Path(base.__file__).absolute() == path,
          "canonical unchanged fixed-three owner required")
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == _BASE_SHA,
          "fixed-three source generation differs")
    _need(hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest() == _SELF_PIN,
          "threshold producer changed since import")
    return base


def _maximum(value):
    _need(type(value) is int and value in (1, 2, 3),
          "maximum must be a plain integer one, two or three")
    return value


def _declaration(base, maximum):
    maximum = _maximum(maximum)
    declaration = base._declaration()
    declaration.update(schema=REQUEST_SCHEMA, maximum=maximum,
                       object_variables=["x" + str(i) for i in range(maximum + 1)])
    return declaration


def _parse(base, request_raw, expected_request_sha256):
    request = base._compact_parse(request_raw, expected_request_sha256, "threshold request")
    _need(type(request) is dict, "closed threshold request required")
    _maximum(request.get("maximum"))
    expected = _declaration(base, request["maximum"])
    base._keys(request, expected, "threshold request")
    _need(base._compact_wire(request) == base._compact_wire(expected),
          "unsupported or altered threshold declaration")
    return request


def _owners(base):
    owners = base._owners()
    pins = dict(owners[-1])
    pins[str(_SELF_PATH)] = _SELF_PIN
    _need(_base() is base, "fixed-three operation owner changed")
    return (*owners[:-1], pins)


def _fence(base, pins):
    _need(_base() is base and _owners(base)[-1] == pins,
          "threshold operation sources changed")


def _expression(ast, signatures, maximum):
    """Compose existing constructors; TypedExpression performs elaboration."""
    sorts = {name: signatures.LogicSort(name)
             for name in ("Object", "EventFrame", "TimeFrame")}
    names = ["x" + str(i) for i in range(maximum + 1)]
    binders = [("event", "EventFrame"), ("time", "TimeFrame")]
    binders += [(name, "Object") for name in names]
    binder_sorts = dict(binders)
    serial = 0

    def nid():
        nonlocal serial
        serial += 1
        return "authored:counted-threshold:node:" + str(serial)

    def variable(name):
        return ast.mk_variable(nid(), name, sorts[binder_sorts[name]])

    def fold(constructor, children):
        result = children[0]
        for child in children[1:]:
            result = constructor(nid(), result, child)
        return result

    members = [ast.mk_predicate(nid(), "Member", (
        variable(name), variable("event"), variable("time"))) for name in names]
    pairs = list(combinations(names, 2))
    equalities = [ast.mk_equality(nid(), variable(left), variable(right))
                  for left, right in pairs]
    body = ast.mk_implies(nid(), fold(ast.mk_and, members), fold(ast.mk_or, equalities))
    for name, sort_name in reversed(binders):
        body = ast.mk_forall(nid(), (ast.Binder(name, sorts[sort_name]),), body)
    signature = signatures.LogicSignature("authored:counted-threshold:signature",
        family="first_order", profile="many_sorted", sorts=tuple(sorts.values()),
        symbols=(signatures.declare_predicate("Member", (
            sorts["Object"], sorts["EventFrame"], sorts["TimeFrame"])),))
    return ast.TypedExpression("authored:counted-threshold:expression", body, signature), pairs


def _ledger(expression):
    mapping, binders = [], []

    def visit(node, path):
        mapping.append(dict(typed_path=path, node_id=node.node_id,
                            kind=node.kind.value, sort=node.sort.name))
        binders.extend(dict(typed_path=path + "/binders/" + str(i),
                            variable=binder.name, sort=binder.sort.name)
                       for i, binder in enumerate(node.binders))
        for i, child in enumerate(node.arguments):
            visit(child, path + "/arguments/" + str(i))

    visit(expression.root, "/root")
    return mapping, binders


def _context(base):
    context = base._compact_context()
    context.pop("maximum")
    context.pop("object_variables")
    context["schema"] = CONTEXT_SCHEMA
    return context


def authored_counted_threshold_request_v2(maximum):
    """Declare an authored bound explicitly, without inferring it from text."""
    base = _base()
    request = _declaration(base, maximum)
    raw = base._compact_wire(request, base.MAX_REQUEST_BYTES)
    _parse(base, raw, hashlib.sha256(raw).hexdigest())
    _need(_base() is base, "threshold construction sources changed")
    return request


def prepare_counted_threshold_v2(request_raw, *, expected_request_sha256):
    """Build one of three typed targets and replay genuine canonical FOL."""
    base = _base()
    request = _parse(base, request_raw, expected_request_sha256)
    ast, signatures, algebra, contracts, fol, before = _owners(base)
    try:
        expression, pairs = _expression(ast, signatures, request["maximum"])
        _need(expression.is_formula and not expression.root.free_variable_names(),
              "closed typed threshold formula required")
        mapping, binders = _ledger(expression)
        syntax = base._grouped_syntax(expression.signature, fol)
        canonical = syntax.print(expression)
        limits = contracts.ParseLimits(max_input_bytes=16384, max_tokens=2048, max_depth=64,
            max_diagnostics=8, max_ambiguities=8, max_time_ms=1000, max_memory_bytes=8388608)
        first = syntax.parse_text(canonical, document_id="doc:counted-threshold:first",
                                  expression_id="expr:counted-threshold:first", limits=limits)
        _need(first.ok and first.root is not None and not first.errors,
              "threshold canonical FOL first parse failed")
        _need(algebra.alpha_equivalent(expression.root, first.root),
              "threshold original differs from canonical FOL first parse")
        printed = syntax.print(first.root)
        second = syntax.parse_text(printed, document_id="doc:counted-threshold:second",
                                   expression_id="expr:counted-threshold:second", limits=limits)
        _need(second.ok and second.root is not None and not second.errors,
              "threshold canonical FOL second parse failed")
        _need(printed == canonical and syntax.print(second.root) == canonical
              and algebra.alpha_equivalent(first.root, second.root)
              and algebra.alpha_equivalent(expression.root, second.root),
              "threshold original FOL print/reparse changed")
        kinds = [row["kind"] for row in mapping]
        maximum = request["maximum"]
        counts = dict(nodes=len(mapping), quantifiers=len(binders),
            membership_occurrences=kinds.count("predicate"),
            equality_occurrences=kinds.count("equality"), variable_occurrences=kinds.count("variable"))
        _need(counts == dict(nodes={1:17, 2:31, 3:49}[maximum], quantifiers=maximum+3,
            membership_occurrences=maximum+1, equality_occurrences=len(pairs),
            variable_occurrences=3*(maximum+1)+2*len(pairs)), "threshold shape changed")
        context = _context(base)
        authority = dict(base.AUTHORITY)
        authority["permitted_inference_context_verified"] = False
        authority["varied_reviewed_target_population_verified"] = False
        report = dict(schema=SCHEMA, profile=PROFILE,
            status="authored_unreviewed_counted_threshold_prepared",
            request=request, request_raw_utf8=request_raw.decode("utf-8"),
            request_sha256=expected_request_sha256, maximum=maximum,
            typed_expression=expression.to_dict(), typed_expression_content_digest=expression.content_digest,
            typed_expression_sha256=hashlib.sha256(base._compact_wire(expression.to_dict())).hexdigest(),
            frame=request["frame"], membership=request["membership"], distinctness=request["distinctness"],
            identity_pairs=[list(pair) for pair in pairs], structural_mapping=mapping,
            binder_ledger=binders, counts=counts, canonical_fol=canonical,
            canonical_fol_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            signature_context=context, signature_context_sha256=hashlib.sha256(base._compact_wire(context)).hexdigest(),
            signature_context_role="authored_syntactic_context_permission_unreviewed",
            fol_receipt=dict(notation=fol.CANONICAL_FOL_NOTATION_ID,
                notation_version=fol.CANONICAL_FOL_NOTATION_VERSION,
                printer="CanonicalFOLPrinter_with_explicit_binary_AND_OR_grouping",
                binary_connective_grouping_preserved=True,
                first_parse_status=first.status.value, second_parse_status=second.status.value,
                original_to_first_alpha_equivalent=True, first_to_second_alpha_equivalent=True,
                original_to_second_alpha_equivalent=True, canonical_print_stable=True,
                parse_limits=limits.to_dict(),
                first_root_sha256=hashlib.sha256(base._compact_wire(first.root.to_dict())).hexdigest(),
                second_root_sha256=hashlib.sha256(base._compact_wire(second.root.to_dict())).hexdigest()),
            producer_pins=before, lowering_route="existing_typed_FOL_no_native_lowering",
            source_binding=None, source_bound=False, source_translation_performed=False,
            native_TDFOL_route_used=False, native_build_executed=False, model_executed=False,
            training_executed=False, codec_compatibility_verified=False,
            human_reviews=0, signatures_constructed=0, admissions=0, graph_admissions=0,
            training_mask=0, evaluation_gold_mask=0, authority=authority,
            assumptions=[
                "The caller explicitly declares one authored maximum; no limit or meaning is inferred from legal text.",
                "Built-in object identity counts distinct members independently for each event/time pair, without occurrence multiplicity.",
                "The carriers are arbitrary sorts; time has no order, duration, calendar or cumulative interpretation.",
                "This produces three synthetic typed targets, not reviewed statutory examples or a source-separated learning population.",
                "The common signature context omits the cap and cap-derived variable list; independent inference-context permission remains unprovided.",
                "Existing v1 codec, checkpoints, numerical profiles and Lean qualification retain their own exact source generations.",
                "No target tokens, generation route, trainer, encoder, graph admission, native lowering or new Lean artifact is supplied.",
            ])
        raw = base._compact_wire(report)
        result = base._compact_capture(report)
        _need(base._compact_wire(result) == raw, "threshold report changed during serialization")
        return result
    finally:
        _fence(base, before)


def counted_threshold_report_sha256(report):
    """Hash bounded ordinary report data; a hash alone grants no validation."""
    base = _base()
    raw = base._compact_wire(report)
    _need(_base() is base, "threshold hash sources changed")
    return hashlib.sha256(raw).hexdigest()


def validate_counted_threshold_v2(report, request_raw, *, expected_request_sha256,
                                expected_report_sha256):
    """Compare a pinned report against complete original-request regeneration."""
    base = _base()
    _parse(base, request_raw, expected_request_sha256)
    base._digest(expected_report_sha256, "threshold report")
    if type(report) is bytes:
        captured = base._compact_capture(base._read_json(report, base.MAX_REPORT_BYTES, "threshold report"))
    else:
        captured = base._compact_capture(report)
    _need(type(captured) is dict, "ordinary threshold report or exact JSON bytes required")
    offered_raw = base._compact_wire(captured)
    _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
          "threshold report SHA256 mismatch")
    regenerated = prepare_counted_threshold_v2(request_raw, expected_request_sha256=expected_request_sha256)
    _need(base._compact_wire(regenerated) == offered_raw,
          "threshold report differs from complete original request replay")
    # Closing observations cover caller-owned dictionaries too; generated text
    # or an offered producer path never chooses another file or implementation.
    if type(report) is not bytes:
        _need(base._compact_wire(report) == offered_raw, "offered threshold report changed during replay")
    _need(_base() is base, "threshold replay sources changed")
    return regenerated


__all__ = ["authored_counted_threshold_request_v2", "prepare_counted_threshold_v2",
           "counted_threshold_report_sha256", "validate_counted_threshold_v2"]


# Explicit opt-in; all existing v1/v2 constructors, schemas and outputs retain
# their original contracts. New source pins are regenerated, never retagged.
PARAMETRIC_REQUEST_SCHEMA = "legal-counted-frame-threshold-request/v3"
PARAMETRIC_SCHEMA = "legal-counted-frame-threshold-report/v3"
PARAMETRIC_PROFILE = "authored-at-most-nat-distinct-per-event-and-time/v3"


def _parametric_budget(maximum, *, max_nodes=4096, max_depth=32, max_bytes=131072,
                       max_json_depth=64, max_json_items=20000):
    """Preflight existing preservation capacities before any expansion/import.

    This accepts a semantic Nat, not a new small semantic threshold panel.
    The expanded representation still costs O(n**2); finite node/depth/byte
    capacities can refuse an otherwise meaningful threshold without truncation.
    The byte estimate bounds the fixed ASCII names/metadata used below.
    """
    _need(type(maximum) is int and maximum >= 0, "plain natural threshold required")
    _need(all(type(v) is int and v > 0 for v in (max_nodes, max_depth, max_bytes, max_json_depth, max_json_items)),
          "positive existing capacity bounds required")
    objects = maximum + 1
    pairs = maximum * objects // 2
    nodes = 9 if maximum == 0 else 2 * maximum * maximum + 8 * maximum + 7
    depth = 5 if maximum == 0 else max(objects + pairs + 3, 2 * objects + 3)
    estimated_bytes = 8192 + 512 * nodes
    json_depth = 2 * depth + 4
    json_items = 128 * nodes + 4096
    _need(nodes <= max_nodes and depth <= max_depth and estimated_bytes <= max_bytes
          and json_depth <= max_json_depth and json_items <= max_json_items,
          "parametric threshold exceeds existing AST/depth/byte capacity")
    return dict(maximum=maximum, object_variables=objects, equality_pairs=pairs,
                ast_nodes=nodes, ast_depth=depth, expression_bytes_upper_bound=estimated_bytes,
                json_depth_upper_bound=json_depth, json_items_upper_bound=json_items)


def _parametric_declaration(base, maximum):
    _parametric_budget(maximum)
    request = base._declaration()
    request.update(schema=PARAMETRIC_REQUEST_SCHEMA, maximum=maximum,
                   object_variables=["x" + str(i) for i in range(maximum + 1)])
    return request


def _parametric_parse(base, request_raw, expected_request_sha256):
    request = base._compact_parse(request_raw, expected_request_sha256, "parametric threshold request")
    _need(type(request) is dict, "closed parametric threshold request required")
    _parametric_budget(request.get("maximum"))
    expected = _parametric_declaration(base, request["maximum"])
    base._keys(request, expected, "parametric threshold request")
    _need(base._compact_wire(request) == base._compact_wire(expected),
          "unsupported or altered parametric threshold declaration")
    return request


def _parametric_expression(ast, signatures, maximum):
    _parametric_budget(maximum)
    if maximum:
        return _expression(ast, signatures, maximum)
    sorts = {name: signatures.LogicSort(name) for name in ("Object", "EventFrame", "TimeFrame")}
    serial = 0
    def nid():
        nonlocal serial
        serial += 1
        return "authored:counted-threshold:node:" + str(serial)
    binders = [("event", "EventFrame"), ("time", "TimeFrame"), ("x0", "Object")]
    membership = ast.mk_predicate(nid(), "Member", tuple(
        ast.mk_variable(nid(), name, sorts[sort])
        for name, sort in (("x0", "Object"), ("event", "EventFrame"), ("time", "TimeFrame"))))
    body = ast.mk_implies(nid(), membership, ast.mk_false(nid()))
    for name, sort in reversed(binders):
        body = ast.mk_forall(nid(), (ast.Binder(name, sorts[sort]),), body)
    signature = signatures.LogicSignature("authored:counted-threshold:signature",
        family="first_order", profile="many_sorted", sorts=tuple(sorts.values()),
        symbols=(signatures.declare_predicate("Member", (
            sorts["Object"], sorts["EventFrame"], sorts["TimeFrame"])),))
    return ast.TypedExpression("authored:counted-threshold:expression", body, signature), []


def _parametric_lean_body(maximum):
    """Specialize the same sorted counting expansion; this is not a proof."""
    _parametric_budget(maximum)
    names = ["x" + str(i) for i in range(maximum + 1)]
    def fold(items, operator):
        if not items:
            return "False"
        value = items[0]
        for item in items[1:]:
            value = "(" + value + " " + operator + " " + item + ")"
        return value
    members = ["member " + name + " event time" for name in names]
    equalities = [left + " = " + right for left, right in combinations(names, 2)]
    return ("set_option autoImplicit false\n\ndef countedAtMostThreshold {Object EventFrame TimeFrame : Type}\n"
        "    (member : Object → EventFrame → TimeFrame → Prop) : Prop :=\n"
        "  ∀ (event : EventFrame) (time : TimeFrame) (" + " ".join(names) + " : Object),\n    "
        + fold(members, "∧") + " → " + fold(equalities, "∨") + "\n")


def authored_counted_threshold_request_v3(maximum):
    """Explicit authored Nat declaration, subject to unchanged capacities."""
    _parametric_budget(maximum)
    base = _base()
    request = _parametric_declaration(base, maximum)
    raw = base._compact_wire(request, base.MAX_REQUEST_BYTES)
    _parametric_parse(base, raw, hashlib.sha256(raw).hexdigest())
    _need(_base() is base, "parametric construction sources changed")
    return request



def _parametric_request_preflight(request_raw, expected_request_sha256):
    """Authenticate bounded raw Nat input before importing the base owner."""
    import json
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= 131072,
          "bounded complete parametric request bytes required")
    _need(type(expected_request_sha256) is str
          and len(expected_request_sha256) == 64
          and all(c in "0123456789abcdef" for c in expected_request_sha256)
          and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
          "independent parametric request SHA256 mismatch")
    def pairs(items):
        value = {}
        for key, item in items:
            _need(key not in value, "duplicate parametric request key")
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError("nonfinite parametric request value")
    try:
        request = json.loads(request_raw.decode("utf-8"), object_pairs_hook=pairs,
                             parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded ordinary parametric request JSON required") from error
    _need(type(request) is dict and request.get("schema") == PARAMETRIC_REQUEST_SCHEMA,
          "explicit parametric request schema required")
    return _parametric_budget(request.get("maximum"))

def prepare_counted_threshold_v3(request_raw, *, expected_request_sha256):
    """Opt-in expanded Nat threshold; actual proof execution remains separate."""
    _parametric_request_preflight(request_raw, expected_request_sha256)
    base = _base()
    request = _parametric_parse(base, request_raw, expected_request_sha256)
    budget = _parametric_budget(request["maximum"])
    ast, signatures, algebra, contracts, fol, before = _owners(base)
    try:
        expression, pairs = _parametric_expression(ast, signatures, request["maximum"])
        _need(expression.is_formula and not expression.root.free_variable_names(),
              "closed typed threshold formula required")
        mapping, binders = _ledger(expression)
        _need(len(base._compact_wire(expression.to_dict(), base.MAX_REQUEST_BYTES)) <= budget["expression_bytes_upper_bound"],
              "complete parametric expression exceeds conservative byte preflight")
        syntax = base._grouped_syntax(expression.signature, fol)
        canonical = syntax.print(expression)
        limits = contracts.ParseLimits(max_input_bytes=16384, max_tokens=2048, max_depth=64,
            max_diagnostics=8, max_ambiguities=8, max_time_ms=1000, max_memory_bytes=8388608)
        first = syntax.parse_text(canonical, document_id="doc:counted-threshold:first",
                                  expression_id="expr:counted-threshold:first", limits=limits)
        _need(first.ok and first.root is not None and not first.errors,
              "threshold canonical FOL first parse failed")
        _need(algebra.alpha_equivalent(expression.root, first.root),
              "threshold original differs from canonical FOL first parse")
        printed = syntax.print(first.root)
        second = syntax.parse_text(printed, document_id="doc:counted-threshold:second",
                                   expression_id="expr:counted-threshold:second", limits=limits)
        _need(second.ok and second.root is not None and not second.errors,
              "threshold canonical FOL second parse failed")
        _need(printed == canonical and syntax.print(second.root) == canonical
              and algebra.alpha_equivalent(first.root, second.root)
              and algebra.alpha_equivalent(expression.root, second.root),
              "threshold original FOL print/reparse changed")
        kinds = [row["kind"] for row in mapping]
        maximum = request["maximum"]
        counts = dict(nodes=len(mapping), quantifiers=len(binders),
            membership_occurrences=kinds.count("predicate"),
            equality_occurrences=kinds.count("equality"), variable_occurrences=kinds.count("variable"))
        _need(counts == dict(nodes=budget["ast_nodes"], quantifiers=maximum+3,
            membership_occurrences=maximum+1, equality_occurrences=len(pairs),
            variable_occurrences=3*(maximum+1)+2*len(pairs)), "threshold shape changed")
        context = _context(base)
        authority = dict(base.AUTHORITY)
        authority["permitted_inference_context_verified"] = False
        authority["varied_reviewed_target_population_verified"] = False
        lean_body = _parametric_lean_body(maximum)
        report = dict(schema=PARAMETRIC_SCHEMA, profile=PARAMETRIC_PROFILE,
            status="authored_unreviewed_parametric_counted_threshold_prepared",
            request=request, request_raw_utf8=request_raw.decode("utf-8"),
            request_sha256=expected_request_sha256, maximum=maximum,
            typed_expression=expression.to_dict(), typed_expression_content_digest=expression.content_digest,
            typed_expression_sha256=hashlib.sha256(base._compact_wire(expression.to_dict())).hexdigest(),
            frame=request["frame"], membership=request["membership"], distinctness=request["distinctness"],
            identity_pairs=[list(pair) for pair in pairs], structural_mapping=mapping,
            binder_ledger=binders, counts=counts, canonical_fol=canonical,
            canonical_fol_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            signature_context=context, signature_context_sha256=hashlib.sha256(base._compact_wire(context)).hexdigest(),
            signature_context_role="authored_syntactic_context_permission_unreviewed",
            fol_receipt=dict(notation=fol.CANONICAL_FOL_NOTATION_ID,
                notation_version=fol.CANONICAL_FOL_NOTATION_VERSION,
                printer="CanonicalFOLPrinter_with_explicit_binary_AND_OR_grouping",
                binary_connective_grouping_preserved=True,
                first_parse_status=first.status.value, second_parse_status=second.status.value,
                original_to_first_alpha_equivalent=True, first_to_second_alpha_equivalent=True,
                original_to_second_alpha_equivalent=True, canonical_print_stable=True,
                parse_limits=limits.to_dict(),
                first_root_sha256=hashlib.sha256(base._compact_wire(first.root.to_dict())).hexdigest(),
                second_root_sha256=hashlib.sha256(base._compact_wire(second.root.to_dict())).hexdigest()),
            producer_pins=before, lowering_route="existing_typed_FOL_to_parametric_threshold_Lean_text",
            lean_body=lean_body, lean_body_sha256=hashlib.sha256(lean_body.encode()).hexdigest(),
            parametric_budget=budget,
            source_binding=None, source_bound=False, source_translation_performed=False,
            native_TDFOL_route_used=False, native_build_executed=False, model_executed=False,
            training_executed=False, codec_compatibility_verified=False,
            human_reviews=0, signatures_constructed=0, admissions=0, graph_admissions=0,
            training_mask=0, evaluation_gold_mask=0, authority=authority,
            assumptions=[
                "The caller explicitly declares one authored maximum; no limit or meaning is inferred from legal text.",
                "Built-in object identity counts distinct members independently for each event/time pair, without occurrence multiplicity.",
                "The carriers are arbitrary sorts; time has no order, duration, calendar or cumulative interpretation.",
                "This produces an authored Nat threshold, not a reviewed statutory example or source-separated learning population.",
                "The common signature context omits the cap and cap-derived variable list; independent inference-context permission remains unprovided.",
                "Existing v1 codec, checkpoints, numerical profiles and Lean qualification retain their own exact source generations.",
                "Expanded AST cost is quadratic; finite existing capacities can refuse without changing mathematical counting semantics.",
                "Lean text is generated but unexecuted; no native proof, legal meaning or model qualification is supplied.",
            ])
        raw = base._compact_wire(report)
        result = base._compact_capture(report)
        _need(base._compact_wire(result) == raw, "threshold report changed during serialization")
        return result
    finally:
        _fence(base, before)


def validate_counted_threshold_v3(report, request_raw, *, expected_request_sha256,
                                expected_report_sha256):
    """Compare a pinned report against complete original-request regeneration."""
    _parametric_request_preflight(request_raw, expected_request_sha256)
    base = _base()
    _parametric_parse(base, request_raw, expected_request_sha256)
    base._digest(expected_report_sha256, "threshold report")
    if type(report) is bytes:
        captured = base._compact_capture(base._read_json(report, base.MAX_REPORT_BYTES, "threshold report"))
    else:
        captured = base._compact_capture(report)
    _need(type(captured) is dict, "ordinary threshold report or exact JSON bytes required")
    offered_raw = base._compact_wire(captured)
    _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
          "threshold report SHA256 mismatch")
    regenerated = prepare_counted_threshold_v3(request_raw, expected_request_sha256=expected_request_sha256)
    _need(base._compact_wire(regenerated) == offered_raw,
          "threshold report differs from complete original request replay")
    # Closing observations cover caller-owned dictionaries too; generated text
    # or an offered producer path never chooses another file or implementation.
    if type(report) is not bytes:
        _need(base._compact_wire(report) == offered_raw, "offered threshold report changed during replay")
    _need(_base() is base, "threshold replay sources changed")
    return regenerated


__all__ += ["authored_counted_threshold_request_v3", "prepare_counted_threshold_v3",
            "validate_counted_threshold_v3"]
