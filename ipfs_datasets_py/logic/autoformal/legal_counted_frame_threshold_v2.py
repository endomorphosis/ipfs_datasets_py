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


PARAMETRIC_EXPANDED_CAPACITY_PROFILE = "counted-nat-expanded-capacity/v1"


def _parametric_capacity(capacity_profile):
    if capacity_profile is None:
        return dict(max_nodes=4096, max_depth=32, max_bytes=131072,
                    max_json_depth=64, max_json_items=20000)
    _need(type(capacity_profile) is str and capacity_profile == PARAMETRIC_EXPANDED_CAPACITY_PROFILE,
          "explicit recognized parametric capacity profile required")
    return dict(max_nodes=1024, max_depth=128, max_bytes=1048576,
                max_json_depth=256, max_json_items=65536)


def _parametric_capacity_owner():
    # Reuse the existing bounded JSON owner, rather than another codec.
    from . import legal_native_ast_preservation as preservation
    path = _SELF_PATH.with_name("legal_native_ast_preservation.py")
    _need(type(getattr(preservation, "__file__", None)) is str
          and Path(preservation.__file__).absolute() == path
          and hashlib.sha256(path.read_bytes()).hexdigest() == preservation._SELF_PIN,
          "exact existing bounded preservation JSON owner required")
    return preservation


def _parametric_wire(base, value, maximum=None, *, capacity_profile=None):
    if capacity_profile is None:
        return (base._compact_wire(value) if maximum is None
                else base._compact_wire(value, maximum))
    capacities = _parametric_capacity(capacity_profile)
    maximum = capacities["max_bytes"] if maximum is None else maximum
    _need(type(maximum) is int and 0 < maximum <= capacities["max_bytes"],
          "bounded selected parametric JSON byte capacity required")
    return _parametric_capacity_owner()._wire(value, maximum,
        max_json_depth=capacities["max_json_depth"])


def _parametric_read_json(base, raw, maximum, *, capacity_profile=None):
    if capacity_profile is None:
        return base._read_json(raw, maximum, "threshold report")
    capacities = _parametric_capacity(capacity_profile)
    _need(type(maximum) is int and 0 < maximum <= capacities["max_bytes"],
          "bounded selected parametric JSON byte capacity required")
    return _parametric_capacity_owner()._parse(raw, maximum,
        max_json_depth=capacities["max_json_depth"])


def _parametric_capture(base, value, *, capacity_profile=None):
    if capacity_profile is None:
        return base._compact_capture(value)
    capacities = _parametric_capacity(capacity_profile)
    raw = _parametric_wire(base, value, capacities["max_bytes"], capacity_profile=capacity_profile)
    return _parametric_read_json(base, raw, capacities["max_bytes"], capacity_profile=capacity_profile)


def _parametric_owners(base, capacity_profile):
    owners = _owners(base)
    if capacity_profile is None:
        return owners
    _parametric_capacity(capacity_profile)
    preservation = _parametric_capacity_owner()
    pins = dict(owners[-1])
    pins[str(_SELF_PATH.with_name("legal_native_ast_preservation.py"))] = preservation._SELF_PIN
    return (*owners[:-1], pins)


def _parametric_fence(base, pins, capacity_profile):
    if capacity_profile is None:
        return _fence(base, pins)
    _need(_base() is base and _parametric_owners(base, capacity_profile)[-1] == pins,
          "expanded parametric operation sources changed")


def _parametric_budget(maximum, *, max_nodes=4096, max_depth=32, max_bytes=131072,
                       max_json_depth=64, max_json_items=20000, capacity_profile=None):
    """Preflight existing preservation capacities before any expansion/import.

    This accepts a semantic Nat, not a new small semantic threshold panel.
    The expanded representation still costs O(n**2); finite node/depth/byte
    capacities can refuse an otherwise meaningful threshold without truncation.
    The byte estimate bounds the fixed ASCII names/metadata used below.
    """
    if capacity_profile is not None:
        _need(all(type(value) is int for value in (max_nodes, max_depth, max_bytes, max_json_depth, max_json_items))
              and (max_nodes, max_depth, max_bytes, max_json_depth, max_json_items)
              == (4096, 32, 131072, 64, 20000),
              "selected capacity profile owns its exact finite bounds")
        capacities = _parametric_capacity(capacity_profile)
        max_nodes, max_depth, max_bytes, max_json_depth, max_json_items = (
            capacities[key] for key in ("max_nodes", "max_depth", "max_bytes", "max_json_depth", "max_json_items"))
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
    result = dict(maximum=maximum, object_variables=objects, equality_pairs=pairs,
                ast_nodes=nodes, ast_depth=depth, expression_bytes_upper_bound=estimated_bytes,
                json_depth_upper_bound=json_depth, json_items_upper_bound=json_items)
    if capacity_profile is not None:
        result["capacity_profile"] = capacity_profile
    return result


def _parametric_declaration(base, maximum, *, capacity_profile=None):
    _parametric_budget(maximum, capacity_profile=capacity_profile)
    request = base._declaration()
    request.update(schema=PARAMETRIC_REQUEST_SCHEMA, maximum=maximum,
                   object_variables=["x" + str(i) for i in range(maximum + 1)])
    if capacity_profile is not None:
        request["capacity_profile"] = capacity_profile
    return request


def _parametric_parse(base, request_raw, expected_request_sha256):
    request = base._compact_parse(request_raw, expected_request_sha256, "parametric threshold request")
    _need(type(request) is dict, "closed parametric threshold request required")
    capacity_profile = request.get("capacity_profile")
    _parametric_budget(request.get("maximum"), capacity_profile=capacity_profile)
    expected = _parametric_declaration(base, request["maximum"], capacity_profile=capacity_profile)
    base._keys(request, expected, "parametric threshold request")
    _need(base._compact_wire(request) == base._compact_wire(expected),
          "unsupported or altered parametric threshold declaration")
    return request


def _parametric_expression(ast, signatures, maximum, *, capacity_profile=None):
    _parametric_budget(maximum, capacity_profile=capacity_profile)
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


def _parametric_lean_body(maximum, *, capacity_profile=None):
    """Specialize the same sorted counting expansion; this is not a proof."""
    _parametric_budget(maximum, capacity_profile=capacity_profile)
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


def authored_counted_threshold_request_v3(maximum, *, capacity_profile=None):
    """Explicit authored Nat declaration, subject to unchanged capacities."""
    _parametric_budget(maximum, capacity_profile=capacity_profile)
    base = _base()
    request = _parametric_declaration(base, maximum, capacity_profile=capacity_profile)
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
    return _parametric_budget(request.get("maximum"), capacity_profile=request.get("capacity_profile"))

def prepare_counted_threshold_v3(request_raw, *, expected_request_sha256):
    """Opt-in expanded Nat threshold; actual proof execution remains separate."""
    _parametric_request_preflight(request_raw, expected_request_sha256)
    base = _base()
    request = _parametric_parse(base, request_raw, expected_request_sha256)
    capacity_profile = request.get("capacity_profile")
    capacities = _parametric_capacity(capacity_profile)
    budget = _parametric_budget(request["maximum"], capacity_profile=capacity_profile)
    def wire(value, maximum=None):
        return _parametric_wire(base, value, maximum, capacity_profile=capacity_profile)
    ast, signatures, algebra, contracts, fol, before = _parametric_owners(base, capacity_profile)
    try:
        expression, pairs = _parametric_expression(ast, signatures, request["maximum"], capacity_profile=capacity_profile)
        _need(expression.is_formula and not expression.root.free_variable_names(),
              "closed typed threshold formula required")
        mapping, binders = _ledger(expression)
        _need(len(wire(expression.to_dict(), capacities["max_bytes"])) <= budget["expression_bytes_upper_bound"],
              "complete parametric expression exceeds conservative byte preflight")
        syntax = base._grouped_syntax(expression.signature, fol)
        canonical = syntax.print(expression)
        limits = contracts.ParseLimits(max_input_bytes=(16384 if capacity_profile is None else 1048576),
            max_tokens=(2048 if capacity_profile is None else 8192),
            max_depth=(64 if capacity_profile is None else 128),
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
        lean_body = _parametric_lean_body(maximum, capacity_profile=capacity_profile)
        report = dict(schema=PARAMETRIC_SCHEMA, profile=PARAMETRIC_PROFILE,
            status="authored_unreviewed_parametric_counted_threshold_prepared",
            request=request, request_raw_utf8=request_raw.decode("utf-8"),
            request_sha256=expected_request_sha256, maximum=maximum,
            typed_expression=expression.to_dict(), typed_expression_content_digest=expression.content_digest,
            typed_expression_sha256=hashlib.sha256(wire(expression.to_dict())).hexdigest(),
            frame=request["frame"], membership=request["membership"], distinctness=request["distinctness"],
            identity_pairs=[list(pair) for pair in pairs], structural_mapping=mapping,
            binder_ledger=binders, counts=counts, canonical_fol=canonical,
            canonical_fol_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            signature_context=context, signature_context_sha256=hashlib.sha256(wire(context)).hexdigest(),
            signature_context_role="authored_syntactic_context_permission_unreviewed",
            fol_receipt=dict(notation=fol.CANONICAL_FOL_NOTATION_ID,
                notation_version=fol.CANONICAL_FOL_NOTATION_VERSION,
                printer="CanonicalFOLPrinter_with_explicit_binary_AND_OR_grouping",
                binary_connective_grouping_preserved=True,
                first_parse_status=first.status.value, second_parse_status=second.status.value,
                original_to_first_alpha_equivalent=True, first_to_second_alpha_equivalent=True,
                original_to_second_alpha_equivalent=True, canonical_print_stable=True,
                parse_limits=limits.to_dict(),
                first_root_sha256=hashlib.sha256(wire(first.root.to_dict())).hexdigest(),
                second_root_sha256=hashlib.sha256(wire(second.root.to_dict())).hexdigest()),
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
        if capacity_profile is not None:
            report["capacity_profile"] = capacity_profile
        raw = wire(report)
        result = _parametric_capture(base, report, capacity_profile=capacity_profile)
        _need(wire(result) == raw, "threshold report changed during serialization")
        return result
    finally:
        _parametric_fence(base, before, capacity_profile)


def validate_counted_threshold_v3(report, request_raw, *, expected_request_sha256,
                                expected_report_sha256):
    """Compare a pinned report against complete original-request regeneration."""
    budget = _parametric_request_preflight(request_raw, expected_request_sha256)
    capacity_profile = budget.get("capacity_profile")
    base = _base()
    def wire(value):
        return _parametric_wire(base, value, capacity_profile=capacity_profile)
    _parametric_parse(base, request_raw, expected_request_sha256)
    base._digest(expected_report_sha256, "threshold report")
    if type(report) is bytes:
        captured = _parametric_capture(base, _parametric_read_json(base, report, base.MAX_REPORT_BYTES, capacity_profile=capacity_profile), capacity_profile=capacity_profile)
    else:
        captured = _parametric_capture(base, report, capacity_profile=capacity_profile)
    _need(type(captured) is dict, "ordinary threshold report or exact JSON bytes required")
    offered_raw = wire(captured)
    _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
          "threshold report SHA256 mismatch")
    regenerated = prepare_counted_threshold_v3(request_raw, expected_request_sha256=expected_request_sha256)
    _need(wire(regenerated) == offered_raw,
          "threshold report differs from complete original request replay")
    # Closing observations cover caller-owned dictionaries too; generated text
    # or an offered producer path never chooses another file or implementation.
    if type(report) is not bytes:
        _need(wire(report) == offered_raw, "offered threshold report changed during replay")
    _need(_base() is base, "threshold replay sources changed")
    return regenerated


__all__ += ["authored_counted_threshold_request_v3", "prepare_counted_threshold_v3",
            "validate_counted_threshold_v3"]


# Explicit positive-cardinality opt-in. All preceding v1/v2/v3 definitions stay exact.
QUANTITY_REQUEST_SCHEMA = "legal-counted-frame-quantity-request/v4"
QUANTITY_SCHEMA = "legal-counted-frame-quantity-report/v4"
QUANTITY_PROFILE = "authored-positive-lower-or-exact-enumeration-per-event-and-time/v4"
_QUANTITY_RELATIONAL_SHA = "e3fb0941e123672f4c280f282b0bce80937dab6cdc56ca607ffd5d3713ae9adf"
_QUANTITY_FIELDS = frozenset(("schema", "profile", "quantity", "threshold",
    "interpretation_status", "frame", "membership", "distinctness", "source_binding"))


def _quantity_budget(quantity, threshold, *, max_nodes=512, max_depth=48,
        max_bytes=131072, max_json_depth=64, max_json_items=20000):
    """Reject finite representation costs before syntax allocation or lazy imports."""
    _need(type(quantity) is str and quantity in ("at_least", "exactly"),
          "explicit at_least or exactly quantity required")
    _need(type(threshold) is int and threshold >= 0, "plain natural quantity threshold required")
    _need(all(type(v) is int and v > 0 for v in
          (max_nodes, max_depth, max_bytes, max_json_depth, max_json_items)),
          "positive existing quantity capacities required")
    _need(threshold <= max_nodes, "quantity expansion exceeds existing node capacity")
    n = threshold
    pairs = n * (n - 1) // 2
    if n == 0:
        nodes, depth = (12, 5) if quantity == "at_least" else (8, 5)
    else:
        leaves = n + pairs
        nodes = 6 * n + 5 * pairs + 1
        depth = n + 2 + leaves
        if quantity == "exactly":
            nodes += 4 * n + 6
            depth = n + 3 + max(leaves, n + 2)
    expression_bytes = 8192 + 512 * nodes
    json_depth, json_items = 2 * depth + 4, 128 * nodes + 4096
    _need(nodes <= max_nodes and depth <= max_depth and expression_bytes <= max_bytes
          and json_depth <= max_json_depth and json_items <= max_json_items,
          "quantity expansion exceeds existing AST/depth/byte/JSON capacity")
    return {"quantity": quantity, "threshold": n, "ast_nodes": nodes, "ast_depth": depth,
        "distinctness_pairs": pairs, "expression_bytes_upper_bound": expression_bytes,
        "json_depth_upper_bound": json_depth, "json_items_upper_bound": json_items}


def _quantity_declaration(base, quantity, threshold):
    _quantity_budget(quantity, threshold)
    original = base._declaration()
    return {"schema": QUANTITY_REQUEST_SCHEMA, "profile": QUANTITY_PROFILE,
        "quantity": quantity, "threshold": threshold,
        "interpretation_status": "authored_unreviewed_declaration",
        "frame": original["frame"], "membership": original["membership"],
        "distinctness": original["distinctness"], "source_binding": None}


def _quantity_request_preflight(request_raw, expected_request_sha256):
    """Authenticate closed quantity data before any project operation owner."""
    import json
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= 131072,
          "bounded complete quantity request bytes required")
    _need(type(expected_request_sha256) is str and len(expected_request_sha256) == 64
          and all(c in "0123456789abcdef" for c in expected_request_sha256)
          and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256,
          "independent quantity request SHA256 mismatch")
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate quantity request key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("nonfinite quantity request value")
    try:
        request = json.loads(request_raw.decode("utf-8"), object_pairs_hook=pairs,
                             parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free ordinary quantity JSON required") from error
    _need(type(request) is dict and set(request) == _QUANTITY_FIELDS
          and request["schema"] == QUANTITY_REQUEST_SCHEMA and request["profile"] == QUANTITY_PROFILE,
          "explicit closed quantity request profile required")
    _quantity_budget(request["quantity"], request["threshold"])
    return request


def _quantity_parse(base, request_raw, expected_request_sha256):
    request = _quantity_request_preflight(request_raw, expected_request_sha256)
    expected = _quantity_declaration(base, request["quantity"], request["threshold"])
    _need(base._compact_wire(request) == base._compact_wire(expected),
          "unsupported or altered quantity frame/membership/distinctness declaration")
    return request


def _quantity_expression(ast, signatures, quantity, threshold):
    """Construct the existing mixed TypedIR, with positive existential witnesses."""
    _quantity_budget(quantity, threshold)
    sorts = {name: signatures.LogicSort(name) for name in ("Object", "EventFrame", "TimeFrame")}
    serial = 0
    def nid():
        nonlocal serial
        serial += 1
        return "authored:counted-quantity:node:" + str(serial)
    def variable(name, sort="Object"):
        return ast.mk_variable(nid(), name, sorts[sort])
    def member(name):
        return ast.mk_predicate(nid(), "Member", (variable(name),
            variable("event", "EventFrame"), variable("time", "TimeFrame")))
    def equality(left, right):
        return ast.mk_equality(nid(), variable(left), variable(right))
    def fold(constructor, children):
        _need(bool(children), "nonempty quantity connective sequence required")
        result = children[0]
        for child in children[1:]:
            result = constructor(nid(), result, child)
        return result
    def quantify(constructor, name, sort, body):
        return constructor(nid(), (ast.Binder(name, sorts[sort]),), body)
    n = threshold
    if n == 0:
        if quantity == "at_least":
            body = ast.mk_implies(nid(), member("zeroWitness"), member("zeroWitness"))
        else:
            body = ast.mk_not(nid(), member("zeroWitness"))
        body = quantify(ast.mk_forall, "zeroWitness", "Object", body)
    else:
        names = ["x" + str(i) for i in range(n)]
        children = [member(name) for name in names]
        children += [ast.mk_not(nid(), equality(left, right))
                     for left, right in combinations(names, 2)]
        if quantity == "exactly":
            coverage = ast.mk_iff(nid(), member("candidate"),
                fold(ast.mk_or, [equality("candidate", name) for name in names]))
            children.append(quantify(ast.mk_forall, "candidate", "Object", coverage))
        body = fold(ast.mk_and, children)
        for name in reversed(names):
            body = quantify(ast.mk_exists, name, "Object", body)
    for name, sort in reversed((("event", "EventFrame"), ("time", "TimeFrame"))):
        body = quantify(ast.mk_forall, name, sort, body)
    signature = signatures.LogicSignature("authored:counted-quantity:signature",
        family="tdfol", profile="tdfol_default", sorts=tuple(sorts.values()),
        symbols=(signatures.declare_predicate("Member", (
            sorts["Object"], sorts["EventFrame"], sorts["TimeFrame"])),))
    return ast.TypedExpression("authored:counted-quantity:expression", body, signature)


def _quantity_owners(base):
    relational = importlib.import_module("ipfs_datasets_py.logic.autoformal.legal_relational_norm_v1")
    path = _SELF_PATH.with_name("legal_relational_norm_v1.py")
    _need(Path(relational.__file__).absolute() == path
          and hashlib.sha256(path.read_bytes()).hexdigest() == _QUANTITY_RELATIONAL_SHA,
          "exact existing mixed relational operation owner required")
    ast, signatures, emitter, pins = relational._mixed_owners()
    pins = dict(pins)
    pins[str(_SELF_PATH)] = _SELF_PIN
    pins[str(_SELF_PATH.with_name("legal_counted_frame_v1.py"))] = _BASE_SHA
    _need(_base() is base, "fixed counted operation owner changed")
    return relational, ast, signatures, emitter, pins


def _quantity_fence(base, pins):
    _need(_base() is base and _quantity_owners(base)[-1] == pins,
          "counted quantity operation producers changed")


def authored_counted_quantity_request_v4(quantity, threshold):
    """Declare at_least/exactly explicitly; infer no quantity from legal text."""
    _quantity_budget(quantity, threshold)
    base = _base()
    request = _quantity_declaration(base, quantity, threshold)
    raw = base._compact_wire(request, base.MAX_REQUEST_BYTES)
    _quantity_parse(base, raw, hashlib.sha256(raw).hexdigest())
    _need(_base() is base, "quantity construction sources changed")
    return request


def prepare_counted_quantity_v4(request_raw, *, expected_request_sha256):
    """Reuse the genuine mixed TypedIR validation and existing sorted emitter."""
    _quantity_request_preflight(request_raw, expected_request_sha256)
    base = _base()
    request = _quantity_parse(base, request_raw, expected_request_sha256)
    budget = _quantity_budget(request["quantity"], request["threshold"])
    relational, ast, signatures, emitter, pins = _quantity_owners(base)
    try:
        expression = _quantity_expression(ast, signatures, request["quantity"], request["threshold"])
        mixed_request = {"schema": relational.MIXED_REQUEST_SCHEMA,
            "profile": relational.MIXED_PROFILE,
            "interpretation_status": "authored_unreviewed_declaration",
            "expression": expression.to_dict(),
            "argument_roles": [{"symbol": "Member", "roles": ["object", "event", "time"]}],
            "source_binding": None}
        mixed_raw = base._compact_wire(mixed_request, base.MAX_REQUEST_BYTES)
        mixed_sha = hashlib.sha256(mixed_raw).hexdigest()
        _quantity_fence(base, pins)
        mixed = relational.prepare_mixed_relational_norm_v1(mixed_raw,
            expected_request_sha256=mixed_sha)
        _need(mixed["typed_expression"] == expression.to_dict()
              and mixed["counts"]["nodes"] == budget["ast_nodes"]
              and mixed["argument_roles"] == mixed_request["argument_roles"],
              "complete quantity typed source or mixed lowering changed")
        result = {"schema": QUANTITY_SCHEMA, "profile": QUANTITY_PROFILE,
            "status": "authored_unreviewed_counted_quantity_prepared",
            "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256,
            "quantity": request["quantity"], "threshold": request["threshold"],
            "frame": request["frame"], "membership": request["membership"],
            "distinctness": request["distinctness"], "budget": budget,
            "typed_expression": mixed["typed_expression"],
            "typed_expression_content_digest": mixed["typed_expression_content_digest"],
            "typed_expression_sha256": mixed["typed_expression_sha256"],
            "argument_roles": mixed["argument_roles"], "counts": mixed["counts"],
            "mixed_request_raw_utf8": mixed_raw.decode("utf-8"),
            "mixed_request_sha256": mixed_sha, "mixed_report": mixed,
            "mixed_report_sha256": relational.mixed_relational_norm_report_sha256(mixed),
            "lean_body": mixed["lean_body"],
            "lean_body_sha256": hashlib.sha256(mixed["lean_body"].encode("utf-8")).hexdigest(),
            "lowering_route": "existing_mixed_TypedIR_and_sorted_relational_emitter",
            "producer_pins": pins, "source_binding": None, "source_bound": False,
            "source_translation_performed": False, "native_TDFOL_route_used": False,
            "native_build_executed": False, "model_executed": False, "training_executed": False,
            "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(base.AUTHORITY),
            "assumptions": [
                "The caller explicitly selects a nonnegative lower bound or exact finite enumeration; no statutory meaning is inferred.",
                "Object/EventFrame/TimeFrame may be empty; membership is frame-local and identity, not occurrence multiplicity.",
                "Exactly uses explicit existential witnesses and full membership/range coverage, not an assumed AL-and-AM equivalence.",
                "Lean cardinality proofs and native compilation remain separate unexecuted obligations.",
                "Ambient modal Nat time is separate from authored TimeFrame; no temporal aggregation is asserted."]}
        detached = base._compact_capture(result)
        _need(base._compact_wire(detached) == base._compact_wire(result),
              "complete counted quantity report changed during serialization")
        return detached
    finally:
        _quantity_fence(base, pins)


def validate_counted_quantity_v4(report, request_raw, *, expected_request_sha256,
                                  expected_report_sha256):
    """Require complete original declaration replay, including genuine mixed output."""
    _quantity_request_preflight(request_raw, expected_request_sha256)
    base = _base()
    base._digest(expected_report_sha256, "counted quantity report")
    captured = (base._compact_capture(base._read_json(report, base.MAX_REPORT_BYTES, "quantity report"))
                if type(report) is bytes else base._compact_capture(report))
    offered = base._compact_wire(captured)
    _need(hashlib.sha256(offered).hexdigest() == expected_report_sha256,
          "counted quantity report SHA256 mismatch")
    regenerated = prepare_counted_quantity_v4(request_raw,
        expected_request_sha256=expected_request_sha256)
    _need(base._compact_wire(regenerated) == offered,
          "counted quantity report differs from complete original request replay")
    if type(report) is not bytes:
        _need(base._compact_wire(report) == offered, "offered quantity report changed during replay")
    _need(_base() is base, "quantity replay sources changed")
    return regenerated


__all__ += ["QUANTITY_REQUEST_SCHEMA", "QUANTITY_SCHEMA", "QUANTITY_PROFILE",
            "authored_counted_quantity_request_v4", "prepare_counted_quantity_v4",
            "validate_counted_quantity_v4"]


__all__ += ["PARAMETRIC_EXPANDED_CAPACITY_PROFILE"]
