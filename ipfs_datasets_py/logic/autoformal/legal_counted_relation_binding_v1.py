"""Explicit conditional actor/frame relation binding over the existing cap3 owner.

Ordinary import is standard-library-only. The original fixed-count, threshold,
codec, native and numerical contracts are unchanged. Existing pinned base
operations provide JSON, typed syntax and canonical FOL; no kernel, finite
interpreter, Lean proof or general renderer is copied here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MAX_REQUEST_BYTES = 131072
MAX_REPORT_BYTES = 1048576
_BASE_SHA = "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _need(value, message):
    if not value:
        raise ValueError(message)


def _relation_binding_base():
    # Loading the stdlib-only base does not load its syntax operation owners.
    from . import legal_counted_frame_v1 as base
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "relation binding consumer source changed since import")
    _need(hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest() == _BASE_SHA
          and base._SELF_PIN == _BASE_SHA,
          "independently pinned original counted base source differs")
    return base


def _digest(value, label):
    return _relation_binding_base()._digest(value, label)


def _keys(value, expected, label):
    return _relation_binding_base()._keys(value, expected, label)


def _read_json(raw, maximum, label):
    return _relation_binding_base()._read_json(raw, maximum, label)


def _parse(raw, expected):
    return _relation_binding_base()._parse(raw, expected)


def _compact_wire(value, maximum=MAX_REPORT_BYTES):
    return _relation_binding_base()._compact_wire(value, maximum)


def _compact_capture(value, maximum=MAX_REPORT_BYTES):
    return _relation_binding_base()._compact_capture(value, maximum)


def _original_counted_request():
    return _relation_binding_base().authored_counted_frame_request()


def _prepare_original_counted_frame(raw, *, expected_request_sha256):
    return _relation_binding_base().prepare_counted_frame(
        raw, expected_request_sha256=expected_request_sha256)


def _original_counted_report_sha256(report):
    return _relation_binding_base().counted_frame_report_sha256(report)


def _grouped_syntax(signature, fol):
    return _relation_binding_base()._grouped_syntax(signature, fol)


# Explicit pointwise relation coverage.  All preceding fixed/compact profiles
# remain unchanged in the pinned base. This consumer adds no modal/native execution.
RELATION_BINDING_REQUEST_SCHEMA = "legal-counted-relation-binding-request/v1"
RELATION_BINDING_SCHEMA = "legal-counted-relation-binding-report/v1"
RELATION_BINDING_PROFILE = "explicit-pointwise-actor-frame-subrelation-cap3/v1"
_RELATION_BINDING_SCOPE = {
    "quantification": "actor_event_time_local",
    "evaluation": "single_interpretation",
    "frame_binding": "same_event_and_time",
    "modal_transport": "none",
}
_RELATION_BINDING_DECLARATION = {
    "counted_symbol": "Member",
    "counted_argument_roles": ["object", "event", "time"],
    "target_symbol": "Detail",
    "target_argument_roles": ["actor", "object", "event", "time"],
    "direction": "target_implies_counted",
    "actor_variable": "actor", "object_variable": "object",
    "event_variable": "event", "time_variable": "time",
}
_RELATION_BINDING_COUNTS = {
    "nodes": 114, "quantifiers": 12, "predicate_occurrences": 10,
    "equality_occurrences": 12, "variable_occurrences": 59, "binder_rows": 12,
}


def _relation_binding_wire(value, maximum=MAX_REPORT_BYTES):
    """Reuse the bounded counted JSON encoder; no new serialization domain."""
    return _compact_wire(value, maximum)


def _relation_binding_owners():
    owners = _relation_binding_base()._owners()
    pins = dict(owners[-1])
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    return (*owners[:-1], pins)


def _relation_binding_pins(owners=None):
    current = dict(_relation_binding_base()._owners()[-1])
    current[str(Path(__file__).resolve())] = _SELF_PIN
    if owners is not None:
        _need(current == owners[-1], "counted relation binding producer closure changed")
    return current


def _relation_binding_fence(before, observed=()):
    _need(_relation_binding_pins() == before, "counted relation binding producers changed")
    for original, detached, token in observed:
        _need(_compact_wire(original) == token and _compact_wire(detached) == token,
              "counted relation binding original or detached input changed")


def _relation_binding_preflight_expression(value):
    """Bounded fixed-profile JSON eligibility, before lazy syntax imports.

    Genuine TypedExpression elaboration and complete expected-tree recognition
    remain mandatory later. This preflight does not lower or interpret an AST.
    """
    try:
        root = value["root"]
        for name, sort in (("actor", "Object"), ("event", "EventFrame"),
                           ("time", "TimeFrame")):
            _need(root["kind"] == "forall" and len(root["binders"]) == 1 and
                  root["binders"][0]["name"] == name and
                  root["binders"][0]["sort"]["name"] == sort and
                  len(root["arguments"]) == 1, "exact actor/event/time outer binders required")
            root = root["arguments"][0]
        _need(root["kind"] == "implies" and len(root["arguments"]) == 2,
              "whole pointwise implication required")
        premises = root["arguments"][0]
        _need(premises["kind"] == "and" and len(premises["arguments"]) == 2,
              "local cap and inclusion premises required")
        bridge = premises["arguments"][1]
        _need(bridge["kind"] == "forall" and len(bridge["binders"]) == 1 and
              bridge["binders"][0]["name"] == "object" and
              bridge["binders"][0]["sort"]["name"] == "Object" and
              len(bridge["arguments"]) == 1, "local object inclusion binder required")
        implication = bridge["arguments"][0]
        _need(implication["kind"] == "implies" and len(implication["arguments"]) == 2,
              "Detail-to-Member inclusion implication required")
        for predicate, symbol, arguments in (
            (implication["arguments"][0], "Detail", ("actor", "object", "event", "time")),
            (implication["arguments"][1], "Member", ("object", "event", "time"))):
            _need(predicate["kind"] == "predicate" and predicate["symbol"] == symbol and
                  len(predicate["arguments"]) == len(arguments) and
                  all(child["kind"] == "variable" and child["symbol"] == expected
                      for child, expected in zip(predicate["arguments"], arguments, strict=True)),
                  "exact typed Detail-to-Member direction and same-frame argument order required")
        remaining, quantifiers = 114, 0
        stack = [(value["root"], frozenset())]
        while stack:
            node, bound = stack.pop()
            remaining -= 1
            _need(remaining >= 0 and type(node) is dict and
                  node.get("kind") in {"forall", "implies", "and", "or", "predicate",
                                       "equality", "variable"} and node.get("extension") is None,
                  "bounded pure first-order relation conditional required")
            local = set(bound)
            if node["kind"] == "forall":
                quantifiers += 1
                _need(len(node["binders"]) == 1 and len(node["arguments"]) == 1,
                      "one binder per relation conditional quantifier required")
                local.add(node["binders"][0]["name"])
            if node["kind"] == "variable":
                _need(node["symbol"] in local, "relation conditional has an unbound frame or variable")
            stack.extend((child, frozenset(local)) for child in node.get("arguments", []))
        _need(remaining == 0 and quantifiers == 12, "exact 114-node/12-binder relation conditional required")
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError("complete fixed relation conditional JSON shape required") from error


def _relation_binding_parse(raw, expected):
    _digest(expected, "relation binding request")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          "bounded exact counted relation binding request bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected, "relation binding request byte pin differs")
    value = _read_json(raw, MAX_REQUEST_BYTES, "relation binding request")
    _keys(value, {"schema", "interpretation_status", "maximum", "distinctness", "scope",
                  "relation_binding", "source_binding", "counted_request_raw_utf8",
                  "expected_counted_request_sha256", "expected_counted_report_sha256",
                  "expression"}, "relation binding request")
    _need(value["schema"] == RELATION_BINDING_REQUEST_SCHEMA and
          value["interpretation_status"] == "authored_unreviewed_conditional_declaration",
          "explicit authored conditional relation binding required")
    _need(type(value["maximum"]) is int and value["maximum"] == 3 and
          value["distinctness"] == "builtin_object_identity",
          "exact integer three and builtin identity required")
    _need(_compact_wire(value["scope"]) == _compact_wire(_RELATION_BINDING_SCOPE),
          "exact pointwise single-interpretation same-frame scope required; no modal transport")
    _need(_compact_wire(value["relation_binding"]) == _compact_wire(_RELATION_BINDING_DECLARATION),
          "exact Detail-to-Member direction, arity, ordered roles and variables required")
    _need(value["source_binding"] is None, "source binding is unsupported for authored transport")
    _digest(value["expected_counted_request_sha256"], "embedded counted request")
    _digest(value["expected_counted_report_sha256"], "counted report")
    text = value["counted_request_raw_utf8"]
    _need(type(text) is str and 0 < len(text) <= MAX_REQUEST_BYTES,
          "bounded complete embedded counted raw request required")
    try:
        inner = text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("ordinary UTF8 embedded counted request required") from error
    _need(len(inner) <= MAX_REQUEST_BYTES and
          hashlib.sha256(inner).hexdigest() == value["expected_counted_request_sha256"],
          "independent embedded counted request byte pin differs")
    # Original pure preflight runs before any syntax operation owner loads.
    _parse(inner, value["expected_counted_request_sha256"])
    _need(type(value["expression"]) is dict, "explicit whole typed conditional expression required")
    _relation_binding_preflight_expression(value["expression"])
    _compact_capture(value, MAX_REQUEST_BYTES)
    return value, inner


def _relation_binding_expression(counted_report, ast, signatures):
    """Construct one closed mathematical schema, with no legal interpretation."""
    cap = ast.TypedExpression.from_dict(counted_report["typed_expression"])
    event_node, time_node = cap.root, cap.root.arguments[0]
    _need(event_node.kind.value == time_node.kind.value == "forall" and
          len(event_node.binders) == len(time_node.binders) == 1 and
          event_node.binders[0].name == "event" and time_node.binders[0].name == "time" and
          event_node.binders[0].sort.name == "EventFrame" and
          time_node.binders[0].sort.name == "TimeFrame", "original counted frame binders differ")
    core = time_node.arguments[0]
    sorts = {sort.name: sort for sort in cap.signature.sorts}
    sorts["Bool"] = signatures.BOOL_SORT
    object_sort = sorts["Object"]
    serial = 0
    projection, introduced = [], []

    def nid():
        nonlocal serial
        serial += 1
        return "authored:counted-relation-binding:node:" + str(serial)

    def variable(name, sort):
        return ast.mk_variable(nid(), name, sort)

    def clone_target(node):
        kind = node.kind.value
        children = tuple(clone_target(child) for child in node.arguments)
        if kind == "variable":
            result = variable(node.symbol, node.sort)
        elif kind == "predicate":
            _need(node.symbol == "Member" and len(children) == 3,
                  "original counted membership shape differs")
            actor = variable("actor", object_sort)
            introduced.append(actor.node_id)
            result = ast.mk_predicate(nid(), "Detail", (actor,) + children)
        elif kind == "equality":
            result = ast.mk_equality(nid(), *children)
        elif kind in {"and", "or", "implies"}:
            result = {"and": ast.mk_and, "or": ast.mk_or,
                      "implies": ast.mk_implies}[kind](nid(), *children)
        elif kind == "forall":
            result = ast.mk_forall(nid(), node.binders, children[0])
        else:
            raise ValueError("unsupported node in original fixed cap")
        projection.append({"original_node_id": node.node_id,
                           "target_node_id": result.node_id, "kind": kind})
        return result

    target = clone_target(core)
    detail = ast.mk_predicate(nid(), "Detail", (
        variable("actor", object_sort), variable("object", object_sort),
        variable("event", sorts["EventFrame"]), variable("time", sorts["TimeFrame"])))
    member = ast.mk_predicate(nid(), "Member", (
        variable("object", object_sort), variable("event", sorts["EventFrame"]),
        variable("time", sorts["TimeFrame"])))
    bridge = ast.mk_forall(nid(), (ast.Binder("object", object_sort),),
                          ast.mk_implies(nid(), detail, member))
    root = ast.mk_implies(nid(), ast.mk_and(nid(), core, bridge), target)
    for name, sort in reversed((("actor", object_sort), ("event", sorts["EventFrame"]),
                                ("time", sorts["TimeFrame"]))):
        root = ast.mk_forall(nid(), (ast.Binder(name, sort),), root)
    signature = signatures.LogicSignature("authored:counted-relation-binding:signature",
        family="first_order", profile="many_sorted", sorts=tuple(sorts.values()),
        symbols=(signatures.declare_predicate("Member", (object_sort, sorts["EventFrame"],
                    sorts["TimeFrame"])), signatures.declare_predicate("Detail", (
                    object_sort, object_sort, sorts["EventFrame"], sorts["TimeFrame"]))))
    expression = ast.TypedExpression("authored:counted-relation-binding:expression", root, signature)
    return expression, {"original_core": core.to_dict(),
        "original_frame_binders": [
            {"original_typed_path": "/root/binders/0", "node_id": event_node.node_id,
             "binder": event_node.binders[0].to_dict()},
            {"original_typed_path": "/root/arguments/0/binders/0", "node_id": time_node.node_id,
             "binder": time_node.binders[0].to_dict()}],
        "target_projection": projection, "introduced_actor_variable_node_ids": introduced}


def _relation_binding_inventory(expression):
    mapping, binders, seen = [], [], set()
    counts = {key: 0 for key in _RELATION_BINDING_COUNTS}

    def visit(node, path, bound):
        _need(node.node_id not in seen, "relation binding node IDs must be globally unique")
        seen.add(node.node_id)
        kind = node.kind.value
        _need(node.extension is None and not node.metadata and node.range is None,
              "unannotated pure first-order conditional required; no modal extension")
        mapping.append({"typed_path": path, "node_id": node.node_id,
                        "kind": kind, "sort": node.sort.name})
        counts["nodes"] += 1
        local = set(bound)
        for index, binder in enumerate(node.binders):
            binders.append({"typed_path": path + "/binders/" + str(index),
                            "variable": binder.name, "sort": binder.sort.name})
            local.add(binder.name)
        if kind in {"forall", "exists"}:
            counts["quantifiers"] += 1
        if kind == "predicate":
            counts["predicate_occurrences"] += 1
        if kind == "equality":
            counts["equality_occurrences"] += 1
        if kind == "variable":
            counts["variable_occurrences"] += 1
            _need(node.symbol in local, "relation binding contains an unbound variable")
        for index, child in enumerate(node.arguments):
            visit(child, path + "/arguments/" + str(index), frozenset(local))

    visit(expression.root, "/root", frozenset())
    counts["binder_rows"] = len(binders)
    _need(counts == _RELATION_BINDING_COUNTS and not expression.root.free_variable_names(),
          "exact closed 114-node/12-binder pointwise conditional required")
    return mapping, binders, counts


def _relation_binding_path(value, path):
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if type(value) is list else value[token]
    return value


def _relation_binding_finish(checks, primary):
    secondary = None
    for check in checks:
        try:
            check()
        except BaseException as error:
            if secondary is None:
                secondary = error
    if primary is None and secondary is not None:
        raise secondary


def authored_counted_relation_binding_request_v1():
    """Return one explicit authored fixture, never an inferred statutory target."""
    owners = _relation_binding_owners()
    before = _relation_binding_pins(owners)
    original = _original_counted_request()
    inner = _compact_wire(original, MAX_REQUEST_BYTES)
    original_pin = hashlib.sha256(inner).hexdigest()
    checked = _prepare_original_counted_frame(inner, expected_request_sha256=original_pin)
    report_pin = _original_counted_report_sha256(checked)
    expression, _ = _relation_binding_expression(checked, owners[0], owners[1])
    request = {"schema": RELATION_BINDING_REQUEST_SCHEMA,
        "interpretation_status": "authored_unreviewed_conditional_declaration",
        "maximum": 3, "distinctness": "builtin_object_identity",
        "scope": _compact_capture(_RELATION_BINDING_SCOPE),
        "relation_binding": _compact_capture(_RELATION_BINDING_DECLARATION),
        "source_binding": None, "counted_request_raw_utf8": inner.decode("utf-8"),
        "expected_counted_request_sha256": original_pin,
        "expected_counted_report_sha256": report_pin, "expression": expression.to_dict()}
    serialized = _relation_binding_wire(request, MAX_REQUEST_BYTES)
    result = _compact_capture(request, MAX_REQUEST_BYTES)
    _relation_binding_fence(before)
    _need(_compact_wire(request, MAX_REQUEST_BYTES) == serialized and
          _compact_wire(result, MAX_REQUEST_BYTES) == serialized,
          "authored relation binding request changed during final serialization")
    return result


def prepare_counted_relation_binding_v1(request_raw, *, expected_request_sha256):
    """Prepare an explicit conditional; do not apply it to source or modality."""
    request, inner_raw = _relation_binding_parse(request_raw, expected_request_sha256)
    token = _compact_wire(request, MAX_REQUEST_BYTES)
    detached = _compact_capture(request, MAX_REQUEST_BYTES)
    observed = ((request, detached, token),)
    owners = _relation_binding_owners()
    ast, signatures, algebra, contracts, fol, _ = owners
    before = _relation_binding_pins(owners)
    original_report = detached_report = None
    original_report_wire = None
    report = result = serialized = None
    primary = None

    def fence():
        _relation_binding_fence(before, observed)
        # Direct checks follow the last genuine source-owner callback.
        _need(_compact_wire(request, MAX_REQUEST_BYTES) == token and
              _compact_wire(detached, MAX_REQUEST_BYTES) == token,
              "parsed or detached relation binding request changed")
        if original_report_wire is not None:
            _need(_compact_wire(original_report) == original_report_wire and
                  _compact_wire(detached_report) == original_report_wire,
                  "retained original counted report changed")

    def output_fence():
        if serialized is not None:
            _need(_compact_wire(report) == serialized and _compact_wire(result) == serialized,
                  "counted relation binding output changed after serialization")

    try:
        fence()
        original_report = _prepare_original_counted_frame(inner_raw,
            expected_request_sha256=detached["expected_counted_request_sha256"])
        original_report_wire = _compact_wire(original_report)
        _need(hashlib.sha256(original_report_wire).hexdigest() ==
              detached["expected_counted_report_sha256"], "independent counted report pin differs")
        detached_report = _compact_capture(original_report)
        fence()
        expected, lineage = _relation_binding_expression(detached_report, ast, signatures)
        expected_wire = _compact_wire(expected.to_dict(), MAX_REQUEST_BYTES)
        fence()
        expression = ast.TypedExpression.from_dict(detached["expression"])
        expression_wire = _compact_wire(expression.to_dict(), MAX_REQUEST_BYTES)
        _need(expression_wire == _compact_wire(detached["expression"], MAX_REQUEST_BYTES) and
              expression_wire == expected_wire,
              "whole typed relation binding conditional differs from exact pointwise profile")
        fence()
        mapping, binders, counts = _relation_binding_inventory(expression)
        typed = expression.to_dict()
        outer = "/root/arguments/0/arguments/0/arguments/0"
        cap_path, bridge_path, target_path = (outer + "/arguments/0/arguments/0",
            outer + "/arguments/0/arguments/1", outer + "/arguments/1")
        core = _relation_binding_path(typed, cap_path)
        _need(_compact_wire(core) == _compact_wire(lineage["original_core"]),
              "original 47-node counted core changed in conditional")
        syntax = _grouped_syntax(expression.signature, fol)
        canonical = syntax.print(expression)
        fence()
        limits = contracts.ParseLimits(max_input_bytes=16384, max_tokens=2048, max_depth=64,
            max_diagnostics=8, max_ambiguities=8, max_time_ms=1000, max_memory_bytes=8388608)
        first = syntax.parse_text(canonical, document_id="doc:counted-relation-binding:first",
            expression_id="expr:counted-relation-binding:first", limits=limits)
        _need(first.ok and first.root is not None and not first.errors and
              algebra.alpha_equivalent(expression.root, first.root),
              "pointwise conditional canonical FOL first parse differs")
        fence()
        printed = syntax.print(first.root)
        second = syntax.parse_text(printed, document_id="doc:counted-relation-binding:second",
            expression_id="expr:counted-relation-binding:second", limits=limits)
        _need(second.ok and second.root is not None and not second.errors and
              printed == canonical and syntax.print(second.root) == canonical and
              algebra.alpha_equivalent(expression.root, second.root) and
              algebra.alpha_equivalent(first.root, second.root),
              "pointwise conditional FOL print/reparse changed")
        fence()
        original_root = detached_report["typed_expression"]["root"]
        report = {"schema": RELATION_BINDING_SCHEMA, "profile": RELATION_BINDING_PROFILE,
            "status": "authored_unreviewed_pointwise_conditional_prepared",
            "request": detached, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256,
            "typed_expression": typed, "typed_expression_content_digest": expression.content_digest,
            "typed_expression_sha256": hashlib.sha256(expression_wire).hexdigest(),
            "counts": counts, "structural_mapping": mapping, "binder_ledger": binders,
            "argument_roles": [{"symbol": "Member", "roles": ["object", "event", "time"]},
                               {"symbol": "Detail", "roles": ["actor", "object", "event", "time"]}],
            "original_counted_report": detached_report,
            "cap_lineage": {"original_nodes": 49, "retained_core_nodes": 47,
                "original_counted_request_sha256": detached["expected_counted_request_sha256"],
                "original_counted_report_sha256": detached["expected_counted_report_sha256"],
                "original_root_sha256": hashlib.sha256(_compact_wire(original_root)).hexdigest(),
                "retained_core_sha256": hashlib.sha256(_compact_wire(core)).hexdigest(),
                "source_core_original_typed_path": "/root/arguments/0/arguments/0",
                "source_core_conditional_typed_path": cap_path,
                "original_frame_binders": lineage["original_frame_binders"],
                "composed_frame_binders": [row for row in binders if row["variable"] in {"event", "time"}],
                "frame_variable_renamings": [],
                "target_projection": lineage["target_projection"],
                "introduced_actor_variable_node_ids": lineage["introduced_actor_variable_node_ids"]},
            "premises": [{"name": "hMemberBound", "typed_path": cap_path,
                          "status": "explicit_local_conditional_assumption"},
                         {"name": "hCoverage", "typed_path": bridge_path,
                          "status": "caller_declared_Detail_implies_Member_unreviewed"}],
            "conclusion": {"typed_path": target_path, "scope": "same_actor_event_time_only",
                           "status": "conditional_target_not_applied_to_source"},
            "theorem_reuse": {"name": "CountedProofs.subrelation_preserves_bound",
                "proof_source_sha256": "21f90cc1f0e61f52667c871ea2528dd03666dd8137ca459efe11b871e35b12c2",
                "counted_definition_sha256": "a04b69890be5ab7da8bccaa206b377623ce39a5ebde1f5bbeb92e4e02d7c0cf3",
                "historical_qualification_sha256": "b3b3c3ae948ac4c38ec81b6d814743a41237d7223ed79f64bdeb9f420afcc086",
                "role": "existing_theorem_reference_and_instantiation_data_only",
                "localization": {"member_prime": "lambda x ignored_event ignored_time: Member(x,event,time)",
                    "smaller_prime": "lambda x ignored_event ignored_time: Detail(actor,x,event,time)",
                    "outer_variables": ["actor", "event", "time"],
                    "conclusion_specialization": ["event", "time"]},
                "proof_replayed": False, "kernel_application_checked": False,
                "new_Lean_source_generated": False},
            "canonical_fol": canonical,
            "canonical_fol_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "fol_receipt": {"notation": fol.CANONICAL_FOL_NOTATION_ID,
                "notation_version": fol.CANONICAL_FOL_NOTATION_VERSION,
                "binary_connective_grouping_preserved": True,
                "first_parse_status": first.status.value, "second_parse_status": second.status.value,
                "original_to_first_alpha_equivalent": True, "original_to_second_alpha_equivalent": True,
                "first_to_second_alpha_equivalent": True, "canonical_print_stable": True,
                "parse_limits": limits.to_dict()},
            "producer_pins": dict(before), "source_binding": None,
            "source_bound": False, "source_translation_performed": False,
            "native_TDFOL_route_used": False, "native_build_executed": False,
            "model_executed": False, "training_executed": False,
            "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
            "graph_admissions": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": dict(_relation_binding_base().AUTHORITY),
            "assumptions": [
                "The local Member bound and Detail-to-Member coverage are conditional premises, not statutory facts.",
                "All actor/object/event/time arguments are explicit and evaluated in one interpretation at the same frame.",
                "The reverse Member-to-Detail direction alone cannot establish a Detail bound.",
                "No global other-frame, cross-actor, modal O/P/F, world-access, rigidity or monotonicity transport is supplied.",
                "The existing subrelation theorem is referenced through constant-frame localization data; no new proof application is kernel checked.",
                "No legal meaning, source/cache correspondence, governing definition, review, learned target or corpus admission is selected.",
                "Existing fixed/threshold/codec and native profiles remain separate; this target does not acquire their compatibility by relabeling."]}
        serialized = _relation_binding_wire(report)
        result = _compact_capture(report)
        _need(_compact_wire(result) == serialized, "relation binding detached result differs")
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        _relation_binding_finish((fence, output_fence), primary)


def counted_relation_binding_report_sha256(report):
    return hashlib.sha256(_relation_binding_wire(report)).hexdigest()


def validate_counted_relation_binding_v1(report, request_raw, *,
        expected_request_sha256, expected_report_sha256):
    """Replay the complete explicit profile; grant no source or proof authority."""
    _digest(expected_report_sha256, "relation binding report")
    offered = _relation_binding_wire(report)
    _need(hashlib.sha256(offered).hexdigest() == expected_report_sha256,
          "independent relation binding report pin differs")
    _need(type(report) is dict and report.get("schema") == RELATION_BINDING_SCHEMA and
          report.get("profile") == RELATION_BINDING_PROFILE, "explicit relation binding profile required")
    captured = _compact_capture(report)
    regenerated = result = serialized = None
    primary = None

    def input_fence():
        _need(_compact_wire(report) == offered and _compact_wire(captured) == offered,
              "offered relation binding report changed during complete replay")

    def output_fence():
        if serialized is not None:
            _need(_compact_wire(regenerated) == serialized and _compact_wire(result) == serialized,
                  "validated relation binding result changed after final replay")

    try:
        input_fence()
        regenerated = prepare_counted_relation_binding_v1(request_raw,
            expected_request_sha256=expected_request_sha256)
        serialized = _relation_binding_wire(regenerated)
        _need(offered == serialized, "counted relation binding report differs from full original replay")
        result = _compact_capture(regenerated)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        _relation_binding_finish((lambda: _relation_binding_pins(), input_fence, output_fence), primary)
