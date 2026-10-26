"""Authored finite models qualify a strict fragment, without legal truth claims."""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as bridge
from ipfs_datasets_py.logic.syntax_core import ast, signatures


OBJECT = signatures.LogicSort("Object")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


class Builder:
    """Build fixtures with the existing AST, using distinct physical node IDs."""

    def __init__(self):
        self.count = 0

    def nid(self):
        self.count += 1
        return "fixture:node:" + str(self.count)

    def atom(self, name, *arguments):
        return ast.mk_predicate(self.nid(), name,
            [ast.mk_variable(self.nid(), argument, OBJECT) for argument in arguments])

    def modal(self, letter, body):
        kind = {"O": "obligation", "P": "permission", "F": "forbidden"}[letter]
        return ast.mk_extension(self.nid(), family="tdfol", profile="tdfol_default",
            features=("legacy." + kind, "legacy.classic_letter"),
            payload_schema="legacy.deontic/v1",
            payload={"kind": kind, "letter": letter, "resolution": "deontic",
                     "schema_version": "legacy.deontic/v1"}, children=(body,))

    def binary(self, kind, left, right):
        return {"and": ast.mk_and, "or": ast.mk_or, "implies": ast.mk_implies,
                "iff": ast.mk_iff}[kind](self.nid(), left, right)

    def quantify(self, body, binders):
        for name, kind in reversed(binders):
            body = (ast.mk_forall if kind == "forall" else ast.mk_exists)(
                self.nid(), [ast.Binder(name, OBJECT)], body)
        return body


def request_for(builder, body, declarations, binders):
    root = builder.quantify(body, binders)
    signature = signatures.LogicSignature("fixture:signature", family="tdfol",
        profile="tdfol_default", sorts=(OBJECT,),
        symbols=tuple(signatures.declare_predicate(name, (OBJECT,) * len(roles))
                      for name, roles in declarations))
    expression = ast.TypedExpression("fixture:expression", root, signature)
    return {"schema": bridge.REQUEST_SCHEMA,
            "interpretation_status": "authored_unreviewed_declaration",
            "expression": expression.to_dict(),
            "argument_roles": [{"symbol": name, "roles": list(roles)}
                               for name, roles in declarations], "source_binding": None}


def prepare(request):
    raw = wire(request)
    return bridge.prepare_relational_norm_v1(raw,
                expected_request_sha256=hashlib.sha256(raw).hexdigest())


def approval_request(*, sufficient=False, inner=False, operator="P", action_kind="or"):
    builder = Builder()
    action = builder.binary(action_kind, builder.atom("Assign", "actor", "recipient"),
                            builder.atom("Transfer", "actor", "recipient"))
    approval = builder.atom("Approved", "approver", "actor", "recipient")
    if inner:
        body = builder.modal(operator, builder.binary("implies", approval, action))
    elif sufficient:
        body = builder.binary("implies", approval, builder.modal(operator, action))
    else:
        body = builder.binary("implies", builder.modal(operator, action), approval)
    return request_for(builder, body,
        [("Assign", ("actor", "recipient")), ("Transfer", ("actor", "recipient")),
         ("Approved", ("approver", "actor", "recipient"))],
        [("actor", "forall"), ("recipient", "forall"), ("approver", "forall")])


def evaluate(node, atoms, *, domain=(0, 1), world=0, env=None, modal=None):
    """Finite fixture semantics: caller explicitly supplies atoms and O/P/F."""
    env = {} if env is None else env
    modal = (lambda operator, body, at: body(at)) if modal is None else modal
    kind = node["node_type"]
    if kind == "Predicate":
        args = tuple(env[argument["name"]] for argument in node["arguments"])
        return atoms(node["name"], args, world)
    if kind == "QuantifiedFormula":
        values = [evaluate(node["formula"], atoms, domain=domain, world=world,
                           env=env | {node["variable"]["name"]: value}, modal=modal)
                  for value in domain]
        return all(values) if node["quantifier"]["value"] == "∀" else any(values)
    if kind == "DeonticFormula":
        return modal(node["operator"]["value"], lambda at:
            evaluate(node["formula"], atoms, domain=domain, world=at, env=env, modal=modal), world)
    if kind == "UnaryFormula":
        return not evaluate(node["formula"], atoms, domain=domain, world=world, env=env, modal=modal)
    left = evaluate(node["left"], atoms, domain=domain, world=world, env=env, modal=modal)
    right = evaluate(node["right"], atoms, domain=domain, world=world, env=env, modal=modal)
    return {"∧": lambda: left and right, "∨": lambda: left or right,
            "→": lambda: not left or right, "↔": lambda: left == right}[node["operator"]["value"]]()


def test_full_public_replay_retains_existing_ast_ledger_and_no_authority():
    request = approval_request()
    before = deepcopy(request)
    report = prepare(request)
    raw = wire(request)
    regenerated = bridge.validate_relational_norm_v1(report, raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest(),
        expected_report_sha256=bridge.relational_norm_report_sha256(report))
    assert regenerated == report and request == before
    assert report["request"] == request and report["request_raw_utf8"].encode() == raw
    assert report["typed_expression"] == request["expression"]
    assert report["argument_roles"] == request["argument_roles"]
    assert len({row["typed_path"] for row in report["structural_mapping"]}) == len(report["structural_mapping"])
    assert report["native_fragment"]["exact_native_ast_roundtrip"]
    assert "def formula_0" in report["lean_body"]
    assert report["counts"] == {"nodes": 16, "quantifiers": 3, "modal_nodes": 1,
                                "predicate_occurrences": 3}
    assert not any(report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["source_binding"] is None and not report["source_bound"]
    assert not report["source_translation_performed"] and not report["native_build_executed"]
    assert report["human_reviews"] == report["signatures_constructed"] == report["admissions"] == 0


@pytest.mark.parametrize("approval,permitted", [(False, True), (True, False)])
def test_necessary_approval_and_sufficient_permission_have_explicit_countermodels(approval, permitted):
    necessary = prepare(approval_request())["native_ast"]
    sufficient = prepare(approval_request(sufficient=True))["native_ast"]
    atoms = lambda name, args, at: approval if name == "Approved" else name == "Assign"
    modal = lambda operator, body, at: permitted and body(at)
    assert evaluate(necessary, atoms, modal=modal) == (not permitted or approval)
    assert evaluate(sufficient, atoms, modal=modal) == (not approval or permitted)
    assert evaluate(necessary, atoms, modal=modal) != evaluate(sufficient, atoms, modal=modal)


def test_activation_outside_modality_differs_from_guard_inside_under_declared_two_world_model():
    outer = prepare(approval_request(sufficient=True))["native_ast"]
    inner = prepare(approval_request(inner=True))["native_ast"]
    # The guard is false at origin, true at selected modal world; actions false.
    atoms = lambda name, args, at: name == "Approved" and at == 1
    modal = lambda operator, body, at: body(1)
    assert evaluate(outer, atoms, modal=modal) is True
    assert evaluate(inner, atoms, modal=modal) is False


@pytest.mark.parametrize("selected", ["O", "P", "F"])
def test_o_p_f_are_independent_parameters_with_no_inserted_duality(selected):
    reports = {operator: prepare(approval_request(sufficient=True, operator=operator))
               for operator in ("O", "P", "F")}
    atoms = lambda name, args, at: True
    modal = lambda operator, body, at: operator == selected and body(at)
    assert {operator: evaluate(report["native_ast"], atoms, modal=modal)
            for operator, report in reports.items()} == {
                operator: operator == selected for operator in reports}
    assert len({report["native_formula"] for report in reports.values()}) == 3


def action_request(kind="or", *, separated=False, dropped=False):
    builder = Builder()
    assign = builder.atom("Assign", "actor", "recipient")
    declarations = [("Assign", ("actor", "recipient"))]
    if dropped:
        body = builder.modal("P", assign)
    else:
        transfer = builder.atom("Transfer", "actor", "recipient")
        declarations.append(("Transfer", ("actor", "recipient")))
        body = builder.binary(kind, builder.modal("P", assign), builder.modal("P", transfer)) if separated else \
            builder.modal("P", builder.binary(kind, assign, transfer))
    return request_for(builder, body, declarations, [("actor", "forall"), ("recipient", "forall")])


def test_action_disjunction_differs_from_conjunction_and_dropped_alternative():
    disjunction = prepare(action_request())["native_ast"]
    conjunction = prepare(action_request("and"))["native_ast"]
    dropped = prepare(action_request(dropped=True))["native_ast"]
    atoms = lambda name, args, at: name == "Transfer"
    assert evaluate(disjunction, atoms) is True
    assert evaluate(conjunction, atoms) is False
    assert evaluate(dropped, atoms) is False


def test_permission_of_disjunction_is_not_silently_distributed_under_arbitrary_modal_parameters():
    joint = prepare(action_request())["native_ast"]
    separate = prepare(action_request(separated=True))["native_ast"]
    # This authored parameter requires body at both worlds; no permission axiom
    # or claim that statutory permission has this semantics is being asserted.
    atoms = lambda name, args, at: (name, at) in {("Assign", 1), ("Transfer", 2)}
    modal = lambda operator, body, at: body(1) and body(2)
    assert evaluate(joint, atoms, modal=modal) is True
    assert evaluate(separate, atoms, modal=modal) is False


def role_request(*, swapped=False, reversed_direction=False):
    builder = Builder()
    guards = builder.binary("and", builder.atom("Actor", "actor"), builder.atom("Recipient", "recipient"))
    guards = builder.binary("and", guards, builder.atom("Origin", "origin"))
    guards = builder.binary("and", guards, builder.atom("Destination", "destination"))
    args = ["recipient", "actor"] if swapped else ["actor", "recipient"]
    args += ["destination", "origin"] if reversed_direction else ["origin", "destination"]
    body = builder.binary("implies", guards, builder.modal("P", builder.atom("Move", *args)))
    return request_for(builder, body,
        [("Actor", ("subject",)), ("Recipient", ("subject",)), ("Origin", ("subject",)),
         ("Destination", ("subject",)), ("Move", ("actor", "recipient", "origin", "destination"))],
        [(name, "forall") for name in ("actor", "recipient", "origin", "destination")])


@pytest.mark.parametrize("mutation", ["swapped", "reversed_direction"])
def test_actor_recipient_swaps_and_direction_reversal_change_structure_and_finite_truth(mutation):
    original = prepare(role_request())
    changed = prepare(role_request(**{mutation: True}))
    def atoms(name, args, at):
        if name == "Move": return args == (0, 1, 0, 1)
        return args == ((0,) if name in {"Actor", "Origin"} else (1,))
    assert original["native_ast"] != changed["native_ast"]
    assert evaluate(original["native_ast"], atoms) is True
    assert evaluate(changed["native_ast"], atoms) is False
    assert original["argument_roles"] == changed["argument_roles"]


def test_quantifier_order_is_preserved_and_detectable():
    def make(order):
        builder = Builder()
        return prepare(request_for(builder, builder.atom("Match", "actor", "recipient"),
            [("Match", ("actor", "recipient"))], order))
    forall_exists = make([("actor", "forall"), ("recipient", "exists")])
    exists_forall = make([("recipient", "exists"), ("actor", "forall")])
    atoms = lambda name, args, at: args[0] == args[1]
    assert evaluate(forall_exists["native_ast"], atoms) is True
    assert evaluate(exists_forall["native_ast"], atoms) is False


def test_boolean_not_iff_and_exact_binary_connectives_retain_finite_truth():
    builder = Builder()
    body = builder.binary("iff", builder.atom("Left", "actor"),
                          ast.mk_not(builder.nid(), builder.atom("Right", "actor")))
    report = prepare(request_for(builder, body, [("Left", ("subject",)), ("Right", ("subject",))],
                                 [("actor", "forall")]))
    for left, right in itertools.product((False, True), repeat=2):
        assert evaluate(report["native_ast"], lambda name, args, at: left if name == "Left" else right) == (left != right)


@pytest.mark.parametrize("field", ["native_ast", "lean_body", "structural_mapping", "argument_roles",
                                   "authority", "typed_expression", "source_binding", "counts"])
def test_repaired_report_hash_does_not_hide_mutation(field):
    request = approval_request()
    report = prepare(request)
    if field == "lean_body": report[field] += "\n-- altered"
    elif field == "native_ast": report[field]["variable"]["name"] = "other_actor"
    elif field == "authority": report[field]["accepted"] = True
    elif field == "argument_roles": report[field][0]["roles"].reverse()
    elif field == "structural_mapping": report[field].pop()
    elif field == "typed_expression": report[field]["expression_id"] = "fixture:substitute"
    elif field == "source_binding": report[field] = {"invented": True}
    else: report[field]["quantifiers"] += 1
    raw = wire(request)
    with pytest.raises(ValueError, match="authoritative replay"):
        bridge.validate_relational_norm_v1(report, raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(),
            expected_report_sha256=bridge.relational_norm_report_sha256(report))


def reseal_expression(request):
    request["expression"]["content_digest"] = ""
    request["expression"] = ast.TypedExpression.from_dict(request["expression"]).to_dict()
    return request


@pytest.mark.parametrize("mutation", ["free_variable", "duplicate_id", "metadata", "features",
    "wrong_modal_kind", "unknown_modal_payload", "unknown_extension", "unused_predicate",
    "predicate_binder_collision", "nary_connective", "multiple_binders", "shadowing"])
def test_resealed_requests_still_refuse_out_of_profile_declarations(mutation):
    request = approval_request()
    expression = request["expression"]
    root = expression["root"]
    implication = root["arguments"][0]["arguments"][0]["arguments"][0]
    modal = implication["arguments"][0]["extension"]
    action = modal["children"][0]
    if mutation == "free_variable": action["arguments"][0]["arguments"][0]["symbol"] = "unbound_actor"
    elif mutation == "duplicate_id": action["arguments"][1]["node_id"] = action["arguments"][0]["node_id"]
    elif mutation == "metadata": expression["metadata"] = {"approved": True}
    elif mutation == "features": expression["signature"]["features"] = ["invented.feature"]
    elif mutation == "wrong_modal_kind": modal["payload"]["kind"] = "obligation"
    elif mutation == "unknown_modal_payload": modal["payload"]["approved"] = True
    elif mutation == "unknown_extension": modal["payload_schema"] = "invented.modal/v1"
    elif mutation == "unused_predicate":
        expression["signature"]["symbols"].append(signatures.declare_predicate("Unused", (OBJECT,)).to_dict())
        request["argument_roles"].append({"symbol": "Unused", "roles": ["subject"]})
    elif mutation == "predicate_binder_collision":
        root["binders"][0]["name"] = "Assign"
        for term in action["arguments"][0]["arguments"] + action["arguments"][1]["arguments"] + implication["arguments"][1]["arguments"]:
            if term["symbol"] == "actor": term["symbol"] = "Assign"
    elif mutation == "nary_connective":
        duplicate = deepcopy(action["arguments"][0])
        duplicate["node_id"] = "fixture:extra:predicate"
        for index, term in enumerate(duplicate["arguments"]): term["node_id"] = "fixture:extra:term:" + str(index)
        action["arguments"].append(duplicate)
    elif mutation == "multiple_binders": root["binders"].append(ast.Binder("another", OBJECT).to_dict())
    else: root["arguments"][0]["binders"][0]["name"] = "actor"
    with pytest.raises(ValueError): prepare(reseal_expression(request))


@pytest.mark.parametrize("mutation", ["extra_request", "extra_expression", "extra_node", "extra_signature",
    "missing_field", "wrong_source", "wrong_status", "wrong_schema", "sort", "arity", "constant", "function",
    "equality", "true", "false", "unsafe_name", "reserved_name", "namespace_version"])
def test_closed_fields_schemas_sorts_and_unsupported_constructs_refuse(mutation):
    request = approval_request()
    expression = request["expression"]
    if mutation == "extra_request": request["extra"] = 1
    elif mutation == "extra_expression": expression["extra"] = 1
    elif mutation == "extra_node": expression["root"]["extra"] = 1
    elif mutation == "extra_signature": expression["signature"]["extra"] = 1
    elif mutation == "missing_field": del expression["root"]["metadata"]
    elif mutation == "wrong_source": request["source_binding"] = {"source": "invented"}
    elif mutation == "wrong_status": request["interpretation_status"] = "reviewed"
    elif mutation == "wrong_schema": request["schema"] = "other/v1"
    elif mutation == "sort": expression["signature"]["sorts"].append(signatures.LogicSort("Agent").to_dict())
    elif mutation == "arity": expression["signature"]["symbols"][0]["domain"].pop()
    elif mutation in {"constant", "function"}:
        declaration = signatures.declare_constant("Invented", OBJECT) if mutation == "constant" else \
            signatures.declare_function("Invented", (OBJECT,), OBJECT)
        expression["signature"]["symbols"].append(declaration.to_dict())
    elif mutation in {"equality", "true", "false"}:
        builder = Builder()
        node = {"true": ast.mk_true, "false": ast.mk_false}.get(mutation)
        expression["root"] = node("fixture:unsupported").to_dict() if node else ast.mk_equality(
            "fixture:unsupported", ast.mk_variable("fixture:left", "actor", OBJECT),
            ast.mk_variable("fixture:right", "actor", OBJECT)).to_dict()
    elif mutation in {"unsafe_name", "reserved_name"}:
        expression["root"]["binders"][0]["name"] = "actor'" if mutation == "unsafe_name" else "O"
    else: expression["family"]["version"] = "2.0.0"
    with pytest.raises(ValueError):
        if mutation in {"sort", "arity", "constant", "function", "equality", "true", "false",
                         "unsafe_name", "reserved_name", "namespace_version"}:
            request = reseal_expression(request)
        prepare(request)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "arity", "duplicate_labels", "unknown", "extra", "unsafe"])
def test_roles_are_complete_ordered_explicit_and_closed(mutation):
    request = approval_request()
    rows = request["argument_roles"]
    if mutation == "missing": rows.pop()
    elif mutation == "duplicate": rows[1] = deepcopy(rows[0])
    elif mutation == "arity": rows[0]["roles"].pop()
    elif mutation == "duplicate_labels": rows[0]["roles"] = ["actor", "actor"]
    elif mutation == "unknown": rows[0]["symbol"] = "Other"
    elif mutation == "extra": rows[0]["extra"] = 1
    else: rows[0]["roles"][0] = "not a role"
    with pytest.raises(ValueError): prepare(request)


@pytest.mark.parametrize("raw,expected", [
    (b'{"schema":1,"schema":2}', None), (b'{"outer":{"x":1,"x":2}}', None),
    (b'{"value":NaN}', None), (b'{"value":Infinity}', None), (b'\xff', None),
    (b'[]', None), (b'{}', None), (b'{}', "0" * 64), (b'{}', "NOT_A_HASH"),
    (b" " * (bridge.MAX_REQUEST_BYTES + 1), None),
], ids=[
    "duplicate-top-key", "duplicate-nested-key", "nan", "infinity", "invalid-utf8",
    "array", "empty-object", "wrong-pin", "malformed-pin", "request-byte-bound",
])
def test_preflight_rejections_happen_before_operation_owner_loading(monkeypatch, raw, expected):
    monkeypatch.setattr(bridge, "_owners", lambda: pytest.fail("owner loaded before rejected preflight"))
    with pytest.raises(ValueError):
        bridge.prepare_relational_norm_v1(raw,
            expected_request_sha256=expected or hashlib.sha256(raw).hexdigest())


def test_independent_request_and_report_identities_are_required():
    request = approval_request()
    report = prepare(request)
    raw = wire(request)
    with pytest.raises(ValueError, match="request SHA256"):
        bridge.prepare_relational_norm_v1(raw, expected_request_sha256="0" * 64)
    with pytest.raises(ValueError, match="report SHA256"):
        bridge.validate_relational_norm_v1(report, raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(), expected_report_sha256="0" * 64)


def test_report_hash_rejects_nonordinary_values_without_loading_owners(monkeypatch):
    monkeypatch.setattr(bridge, "_owners", lambda: pytest.fail("hashing imported owners"))
    for report in ({"object": object()}, {"nan": float("nan")}, {"tuple": ()}):
        with pytest.raises(ValueError): bridge.relational_norm_report_sha256(report)


def test_producer_change_during_native_lowering_is_rejected(monkeypatch, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_family_routes as routes

    original_bytes = Path(bridge.__file__).read_bytes()
    copied_owner = tmp_path / "legal_relational_norm_v1.py"
    copied_owner.write_bytes(original_bytes)
    monkeypatch.setattr(bridge, "__file__", str(copied_owner))
    monkeypatch.setattr(bridge, "_OWNER_PINS", None)
    original_route = routes.prepare_native_fragment
    completed_routes = []

    def mutate_after_lowering(**kwargs):
        result = original_route(**kwargs)
        completed_routes.append(result["exact_native_ast_roundtrip"])
        copied_owner.write_bytes(original_bytes + b"\n# changed during preparation\n")
        return result

    monkeypatch.setattr(routes, "prepare_native_fragment", mutate_after_lowering)
    with pytest.raises(ValueError, match="relational producer changed"):
        prepare(approval_request())
    assert completed_routes == [True]
    assert copied_owner.read_bytes() != original_bytes


# Mixed source sorts use an explicit projection profile. The retained packet
# supplies authored hypotheses, never a source-meaning or applicability verdict.
_MIXED_RETAINED_PACKET = (
    "docs/autoformalization/evidence/"
    "legal-ir-title10-7214-pending-compositions-20261024.json")
_MIXED_RETAINED_PACKET_SHA = (
    "dd72e2b92ed5a44a77acfb72dd27ca8614250878400db89742c0437438d59dda")
_MIXED_CORE_SHA = "fb7f9968f484c50fda15dbddddb1740bbe5bc0e45b7bd7a56a8e47fa9e192dac"


@pytest.fixture(scope="module")
def mixed_retained_reports(tmp_path_factory):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emit

    packet_path = Path(__file__).parents[4] / _MIXED_RETAINED_PACKET
    raw = packet_path.read_bytes()
    assert len(raw) == 662668 and hashlib.sha256(raw).hexdigest() == _MIXED_RETAINED_PACKET_SHA
    packet = json.loads(raw)
    assert packet["selected_interpretation"] is packet["governing_definition_use"] is None
    assert packet["training_mask"] == packet["evaluation_gold_mask"] == 0
    result, observations = [], []
    retained = tmp_path_factory.mktemp("mixed-retained-hypotheses", numbered=False)
    for index, alternative in enumerate(packet["alternatives"]):
        request = {"schema": bridge.MIXED_REQUEST_SCHEMA, "profile": bridge.MIXED_PROFILE,
            "interpretation_status": "authored_unreviewed_declaration",
            "expression": deepcopy(alternative["typed_expression"]),
            "argument_roles": deepcopy(alternative["argument_roles"]), "source_binding": None}
        request_raw = wire(request)
        report = bridge.prepare_mixed_relational_norm_v1(request_raw,
            expected_request_sha256=hashlib.sha256(request_raw).hexdigest())
        # Preserve each actual return from this source generation. The saved
        # reader can inspect complete bytes without importing this producer or
        # repeating a projection. These are authored, uncompiled observations.
        report_raw = wire(report)
        lean_raw = ("namespace MixedRetainedAlternative" + str(index) + "\n" + emit.PRELUDE
            + "\n" + report["lean_body"] + "\nend MixedRetainedAlternative" + str(index) + "\n").encode("utf-8")
        payloads = {"request": request_raw, "report": report_raw, "lean": lean_raw}
        files = {}
        for kind, body in payloads.items():
            name = "alternative-" + str(index) + (".lean" if kind == "lean" else "." + kind + ".json")
            destination = retained / name
            destination.write_bytes(body)
            assert destination.read_bytes() == body
            files[kind] = {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        observations.append({"alternative_id": alternative["alternative_id"], "ordinal": index,
            "files": files, "source_binding": None, "selected_interpretation": None,
            "governing_definition_use": None, "semantic_mask": 0, "consumer_mask": 0,
            "training_mask": 0, "evaluation_gold_mask": 0, "Lean_compiled": False})
        result.append({"alternative": alternative, "request": request,
            "request_raw": request_raw, "report": report})
    assert [row["alternative"]["alternative_id"] for row in result] == [
        "7214:cap_within_permission", "7214:cap_as_permission_guard"]
    (retained / "manifest.json").write_bytes(wire({
        "schema": "mixed-retained-projection-observations/v1",
        "original_packet": {"path": _MIXED_RETAINED_PACKET,
            "bytes": len(raw), "sha256": _MIXED_RETAINED_PACKET_SHA},
        "observations": observations, "backend_executed": False,
        "scope": "Actual authored preparation returns; no legal meaning or Lean execution."}))
    return result


def _mixed_at(value, pointer):
    for key in pointer.split("/")[1:]:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _mixed_typed_nodes(node, pointer="/root"):
    yield pointer, node
    for index, child in enumerate(node["arguments"]):
        yield from _mixed_typed_nodes(child, pointer + "/arguments/" + str(index))
    if node.get("extension") is not None:
        for index, child in enumerate(node["extension"]["children"]):
            yield from _mixed_typed_nodes(child, pointer + "/extension/children/" + str(index))


def _mixed_reseal_expression(request):
    expression = request["expression"]
    identity = {key: expression[key] for key in (
        "expression_id", "family", "interface", "profile", "root", "schema_version", "signature")}
    expression["content_digest"] = hashlib.sha256(json.dumps(identity, sort_keys=True,
        separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()
    return request


def _mixed_prepare(request):
    raw = wire(request)
    return bridge.prepare_mixed_relational_norm_v1(raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest())


def _mixed_typed_truth(node, domains, atoms, modal, environment=None, ambient=0):
    """Independent finite reading of the original syntax-kernel JSON."""
    environment = {} if environment is None else environment
    kind = node["kind"]
    if kind == "variable":
        sort, value = environment[node["symbol"]]
        assert sort == node["sort"]["name"]
        return value
    if kind == "predicate":
        return atoms(node["symbol"], tuple(_mixed_typed_truth(child, domains, atoms,
            modal, environment, ambient) for child in node["arguments"]), ambient)
    if kind == "equality":
        left, right = node["arguments"]
        assert left["sort"] == right["sort"]
        return _mixed_typed_truth(left, domains, atoms, modal, environment, ambient) == \
            _mixed_typed_truth(right, domains, atoms, modal, environment, ambient)
    if kind in {"forall", "exists"}:
        assert len(node["binders"]) == 1
        binder = node["binders"][0]
        sort = binder["sort"]["name"]
        values = (_mixed_typed_truth(node["arguments"][0], domains, atoms, modal,
            environment | {binder["name"]: (sort, value)}, ambient) for value in domains[sort])
        return all(values) if kind == "forall" else any(values)
    if kind == "extension":
        extension = node["extension"]
        assert extension["payload_schema"] == "legacy.deontic/v1" and len(extension["children"]) == 1
        return modal(extension["payload"]["letter"], lambda at: _mixed_typed_truth(
            extension["children"][0], domains, atoms, modal, environment, at), ambient)
    if kind in {"true", "false"}:
        return kind == "true"
    if kind == "not":
        return not _mixed_typed_truth(node["arguments"][0], domains, atoms, modal, environment, ambient)
    assert len(node["arguments"]) == 2
    left = _mixed_typed_truth(node["arguments"][0], domains, atoms, modal, environment, ambient)
    if kind == "implies" and not left:
        return True
    right = _mixed_typed_truth(node["arguments"][1], domains, atoms, modal, environment, ambient)
    if kind == "and": return left and right
    if kind == "or": return left or right
    if kind == "implies": return not left or right
    assert kind == "iff"
    return left == right


def _mixed_renderer_truth(node, domains, atoms, modal, environment=None, ambient=0):
    """Separate evaluator of the explicit renderer-only AST vocabulary."""
    environment = {} if environment is None else environment
    kind = node["node_type"]
    if kind == "Variable":
        sort, value = environment[node["name"]]
        assert sort == node["sort"]
        return value
    if kind == "AtomicFormula":
        return atoms(node["name"], tuple(_mixed_renderer_truth(child, domains, atoms,
            modal, environment, ambient) for child in node["arguments"]), ambient)
    if kind == "EqualityFormula":
        assert node["left"]["sort"] == node["right"]["sort"]
        return _mixed_renderer_truth(node["left"], domains, atoms, modal, environment, ambient) == \
            _mixed_renderer_truth(node["right"], domains, atoms, modal, environment, ambient)
    if kind == "QuantifiedFormula":
        variable = node["variable"]
        sort = variable["sort"]
        values = (_mixed_renderer_truth(node["formula"], domains, atoms, modal,
            environment | {variable["name"]: (sort, value)}, ambient) for value in domains[sort])
        quantifier = node["quantifier"]["value"]
        assert quantifier in {"∀", "∃"}
        return all(values) if quantifier == "∀" else any(values)
    if kind == "DeonticFormula":
        assert node["agent"] is node["context"] is None
        return modal(node["operator"]["value"], lambda at: _mixed_renderer_truth(
            node["formula"], domains, atoms, modal, environment, at), ambient)
    if kind == "UnaryFormula":
        assert node["operator"]["value"] == "¬"
        return not _mixed_renderer_truth(node["formula"], domains, atoms, modal, environment, ambient)
    assert kind == "BinaryFormula"
    operator = node["operator"]["value"]
    left = _mixed_renderer_truth(node["left"], domains, atoms, modal, environment, ambient)
    if operator == "→" and not left:
        return True
    right = _mixed_renderer_truth(node["right"], domains, atoms, modal, environment, ambient)
    if operator == "∧": return left and right
    if operator == "∨": return left or right
    if operator == "→": return not left or right
    assert operator == "↔"
    return left == right


def _mixed_atoms(amount, *, later_amount=None, seen=None):
    """One authored guard tuple; purposes stay uninterpreted fixture facts."""
    def atoms(name, values, ambient):
        if seen is not None:
            seen.append((name, values, ambient))
        if name in {"President", "CorpsEngineers", "DistrictColumbia"}:
            return values == (0,)
        if name in {"MayorOf", "DutiesOf"}:
            return values == (0, 0)
        if name == "Member":
            limit = amount if later_amount is None or ambient == 0 else later_amount
            return values[0] < limit
        assert name in {"Officer", "AssignedTo", "Detail", "PurposeAssistInDischarging"}
        return True
    return atoms


def _mixed_both_truths(row, domains, atoms, modal):
    original = _mixed_typed_truth(row["request"]["expression"]["root"], domains, atoms, modal)
    projected = _mixed_renderer_truth(row["report"]["renderer_ast"]["root"], domains, atoms, modal)
    assert original == projected
    return original


@pytest.mark.parametrize("alternative", [0, 1], ids=["cap-within-permission", "cap-as-guard"])
def test_mixed_retained_hypotheses_replay_full_sorted_structure_and_pending_authority(
        mixed_retained_reports, alternative):
    row = mixed_retained_reports[alternative]
    request, report, raw = row["request"], row["report"], row["request_raw"]
    before = deepcopy((request, report))
    checked = bridge.validate_mixed_relational_norm_v1(report, raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest(),
        expected_report_sha256=bridge.mixed_relational_norm_report_sha256(report))
    assert checked == report and (request, report) == before
    assert report["schema"] == bridge.MIXED_SCHEMA and report["profile"] == bridge.MIXED_PROFILE
    assert report["typed_expression"] == request["expression"]
    assert report["argument_roles"] == request["argument_roles"]
    assert report["counts"] == {"nodes": 98, "extension_payloads": 1, "quantifiers": 12,
        "modal_nodes": 1, "predicate_occurrences": 14, "equality_occurrences": 6}
    mappings = report["structural_mapping"]
    assert len(mappings) == 111 and len({item["typed_path"] for item in mappings}) == 111
    typed = dict(_mixed_typed_nodes(request["expression"]["root"]))
    core_rows = [item for item in mappings if item["kind"] not in {"binder", "legacy.deontic/v1"}]
    assert {item["typed_path"] for item in core_rows} == set(typed)
    for item in core_rows:
        assert item["node_id"] == typed[item["typed_path"]]["node_id"]
        assert item["sort"] == typed[item["typed_path"]]["sort"]["name"]
        assert _mixed_at(report["renderer_ast"], item["renderer_path"])
    binders = [item for item in mappings if item["kind"] == "binder"]
    assert len(binders) == 12
    assert [item["typed_sort"] for item in binders[:2]] == ["EventFrame", "TimeFrame"]
    assert all(item["typed_sort"] == item["renderer_sort"] for item in binders)
    roles = {item["symbol"]: item["roles"] for item in request["argument_roles"]}
    assert len(roles) == 10
    for item in core_rows:
        if item["kind"] == "predicate":
            assert item["argument_roles"] == roles[typed[item["typed_path"]]["symbol"]]
    core_path = row["alternative"]["original_cap_subtree"]["typed_path"]
    core = _mixed_at(request["expression"], core_path)
    assert hashlib.sha256(wire(core)).hexdigest() == _MIXED_CORE_SHA
    assert sum(item["typed_path"] == core_path or item["typed_path"].startswith(core_path + "/")
        for item in core_rows) == 47
    assert 'i.modal "deontic:P" [] none' in report["lean_body"]
    assert ' : Object,' in report["lean_body"] and ' : EventFrame,' in report["lean_body"]
    assert ' : TimeFrame,' in report["lean_body"]
    assert "[Inhabited" not in report["lean_body"] and "[Nonempty" not in report["lean_body"]
    assert report["source_binding"] is None
    assert report["native_ast"] is None and report["native_parser_roundtrip"] is False
    assert report["native_build_executed"] is report["source_bound"] is False
    assert all(value is False for value in report["authority"].values())
    for key in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0


@pytest.mark.parametrize("amount", [0, 3, 4])
def test_mixed_counting_and_permission_scope_keep_authored_finite_countermodels(
        mixed_retained_reports, amount):
    domains = {"Object": tuple(range(4)), "EventFrame": ("event",), "TimeFrame": ("slice",)}
    modal = lambda operator, body, ambient: operator == "P" and body(ambient)
    observed = [_mixed_both_truths(row, domains, _mixed_atoms(amount), modal)
        for row in mixed_retained_reports]
    assert observed == ([False, True] if amount == 4 else [True, True])


def test_mixed_authored_time_frame_is_independent_of_modal_nat_index(mixed_retained_reports):
    domains = {"Object": tuple(range(4)), "EventFrame": ("authored-event",),
        "TimeFrame": ("arbitrary-time-label",)}
    seen = []
    atoms = _mixed_atoms(3, later_amount=4, seen=seen)
    modal = lambda operator, body, ambient: operator == "P" and body(1)
    assert [_mixed_both_truths(row, domains, atoms, modal) for row in mixed_retained_reports] == [False, True]
    memberships = [row for row in seen if row[0] == "Member"]
    assert memberships and {row[1][1:] for row in memberships} == {
        ("authored-event", "arbitrary-time-label")}
    assert {row[2] for row in memberships} == {0, 1}


@pytest.mark.parametrize("empty_sort", ["Object", "EventFrame", "TimeFrame"])
def test_mixed_outer_universals_do_not_require_nonempty_source_carriers(
        mixed_retained_reports, empty_sort):
    domains = {"Object": (0,), "EventFrame": ("e",), "TimeFrame": ("t",)}
    domains[empty_sort] = ()
    modal = lambda operator, body, ambient: body(ambient)
    assert all(_mixed_both_truths(row, domains, _mixed_atoms(0), modal)
        for row in mixed_retained_reports)


def _mixed_shared_ast(root):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emit
    return {"schema": emit.SORTED_RELATIONAL_AST_SCHEMA,
        "profile": emit.SORTED_RELATIONAL_PROFILE, "root": root}


def _mixed_shared_identity():
    variable = {"node_type": "Variable", "name": "x", "sort": "Object"}
    return _mixed_shared_ast({"node_type": "QuantifiedFormula", "quantifier": {"value": "∀"},
        "variable": variable, "formula": {"node_type": "EqualityFormula",
            "left": deepcopy(variable), "right": deepcopy(variable)}})


def test_mixed_shared_renderer_retains_real_identity_and_empty_existential_semantics():
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emit
    identity = _mixed_shared_identity()
    lean, _ = emit.sorted_relational_document(identity, predicate_sorts={})
    assert " = " in lean and 'i.atom "Equals"' not in lean and 'i.atom "equality"' not in lean
    variable = {"node_type": "Variable", "name": "x", "sort": "Object"}
    existence = _mixed_shared_ast({"node_type": "QuantifiedFormula", "quantifier": {"value": "∃"},
        "variable": variable, "formula": {"node_type": "AtomicFormula", "name": "Witness",
            "arguments": [deepcopy(variable)]}})
    exists_lean, _ = emit.sorted_relational_document(existence, predicate_sorts={"Witness": ["Object"]})
    assert "∃" in exists_lean and 'i.atom "Witness"' in exists_lean
    domains = {"Object": (), "EventFrame": (), "TimeFrame": ()}
    truth = lambda name, values, ambient: True
    modal = lambda operator, body, ambient: body(ambient)
    assert _mixed_renderer_truth(identity["root"], domains, truth, modal) is True
    assert _mixed_renderer_truth(existence["root"], domains, truth, modal) is False
    # Cross-sort equality must refuse rather than become an uninterpreted atom.
    invalid = deepcopy(identity)
    invalid["root"]["formula"]["right"]["sort"] = "EventFrame"
    with pytest.raises(emit.UnsupportedNativeLean):
        emit.sorted_relational_document(invalid, predicate_sorts={})
    # Legacy Object-only callers retain their explicit rejection boundary.
    with pytest.raises(emit.UnsupportedNativeLean, match="sort"):
        emit.FormulaRenderer().formula({"node_type": "QuantifiedFormula", "quantifier": {"value": "∀"},
            "variable": {"node_type": "Variable", "name": "e", "sort": "EventFrame"},
            "formula": {"node_type": "AtomicFormula", "name": "Witness", "arguments": []}})


@pytest.mark.parametrize("damage", ["free_variable", "cross_sort_equality", "modal_payload",
    "duplicate_id", "metadata", "unknown_sort", "missing_role"])
def test_mixed_resealed_requests_cannot_hide_unsupported_typed_content(mixed_retained_reports, damage):
    request = deepcopy(mixed_retained_reports[0]["request"])
    nodes = list(_mixed_typed_nodes(request["expression"]["root"]))
    if damage == "free_variable":
        next(node for _, node in nodes if node["kind"] == "variable")["symbol"] = "unbound_sorted_name"
    elif damage == "cross_sort_equality":
        equality = next(node for _, node in nodes if node["kind"] == "equality")
        equality["arguments"][1]["symbol"] = "event"
        equality["arguments"][1]["sort"] = deepcopy(request["expression"]["signature"]["sorts"][2])
    elif damage == "modal_payload":
        next(node for _, node in nodes if node["kind"] == "extension")["extension"]["payload"]["approved"] = True
    elif damage == "duplicate_id":
        variables = [node for _, node in nodes if node["kind"] == "variable"]
        variables[1]["node_id"] = variables[0]["node_id"]
    elif damage == "metadata": request["expression"]["metadata"] = {"accepted": True}
    elif damage == "unknown_sort":
        request["expression"]["signature"]["sorts"].append(signatures.LogicSort("CivilDate").to_dict())
    else: request["argument_roles"].pop()
    with pytest.raises(ValueError):
        _mixed_prepare(_mixed_reseal_expression(request))


@pytest.mark.parametrize("damage", ["renderer_ast", "equality_count"])
def test_mixed_rehashed_report_cannot_replace_exact_projection(mixed_retained_reports, damage):
    row = mixed_retained_reports[0]
    report = deepcopy(row["report"])
    if damage == "renderer_ast":
        report["renderer_ast"] = deepcopy(mixed_retained_reports[1]["report"]["renderer_ast"])
    else: report["counts"]["equality_occurrences"] -= 1
    with pytest.raises(ValueError):
        bridge.validate_mixed_relational_norm_v1(report, row["request_raw"],
            expected_request_sha256=hashlib.sha256(row["request_raw"]).hexdigest(),
            expected_report_sha256=bridge.mixed_relational_norm_report_sha256(report))


def test_mixed_wrong_independent_request_pin_refuses_before_operation_imports(
        mixed_retained_reports, monkeypatch):
    def forbidden():
        pytest.fail("wrong independent mixed request pin loaded operation owners")
    monkeypatch.setattr(bridge, "_mixed_owners", forbidden)
    with pytest.raises(ValueError):
        bridge.prepare_mixed_relational_norm_v1(mixed_retained_reports[0]["request_raw"],
            expected_request_sha256="0" * 64)


@pytest.fixture(scope="module")
def mixed_installed_lean():
    """The separate native request must opt in before creating a project."""
    import os
    selected = os.environ.get("IPFS_DATASETS_MIXED_RELATIONAL_NATIVE_LEAN")
    if not selected:
        pytest.skip("set IPFS_DATASETS_MIXED_RELATIONAL_NATIVE_LEAN for separately admitted native checks")
    executable = Path(selected)
    expected = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lean")
    assert executable == executable.resolve(strict=True) == expected and not executable.is_symlink()
    raw = executable.read_bytes()
    assert raw.startswith(b"\x7fELF")
    assert hashlib.sha256(raw).hexdigest() == "79fb1d26fa5a39385d59fdc48a711a14b0710ca6480271acce99b4d177cea085"
    return executable


def test_mixed_installed_lean_compiles_both_retained_alternatives_and_empty_carrier_identity(
        mixed_installed_lean, mixed_retained_reports, tmp_path):
    from ipfs_datasets_py.logic.backends import process
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emit
    identity, _ = emit.sorted_relational_document(_mixed_shared_identity(), predicate_sorts={})
    empty_interpretation = """
def emptyInterpretation : Interpretation (SortedRelationalEntity Empty Empty Empty) Unit where
  agent := fun _ => ()
  cognitive := fun _ _ _ _ => False
  constant := fun _ => Sum.inl ()
  function := fun _ _ => Sum.inl ()
  atom := fun _ _ _ => False
  modal := fun _ _ _ _ _ => False
  frame := fun _ _ _ => False
  frameScalar := fun _ _ => Sum.inl ()
  member := fun _ _ => False
  subclass := fun _ _ => False

example : formula emptyInterpretation 0 := by
  intro x
  exact Empty.elim x

example {Object EventFrame TimeFrame : Type}
    (i : Interpretation (SortedRelationalEntity Object EventFrame TimeFrame) Unit)
    (t : Nat) : formula i t := by
  intro x
  rfl
"""
    text = "namespace MixedRelationalQualification\n" + emit.PRELUDE + "\n"
    for index, row in enumerate(mixed_retained_reports):
        text += "namespace Alternative" + str(index) + "\n" + row["report"]["lean_body"]
        text += "\nend Alternative" + str(index) + "\n"
    text += "namespace Identity\n" + identity + "\n" + empty_interpretation + "\nend Identity\n"
    text += "end MixedRelationalQualification\n"
    assert "sorry" not in text and "admit" not in text and "axiom" not in text
    source_name, output_name = "Mixed.lean", "Mixed.olean"
    (tmp_path / source_name).write_text(text, encoding="utf-8")
    binary_pin = {"path": str(mixed_installed_lean), "bytes": mixed_installed_lean.stat().st_size,
        "sha256": hashlib.sha256(mixed_installed_lean.read_bytes()).hexdigest()}
    (tmp_path / "binary-pin.json").write_text(json.dumps(binary_pin, sort_keys=True, indent=2))
    version = process.BoundedToolRunner().run(process.ToolRunRequest(
        argv=(str(mixed_installed_lean), "--version"), owned_process_observation=True,
        environment={"LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(timeout_seconds=10, cpu_seconds=10,
            resident_memory_bytes=512 * 1024**2, max_output_bytes=16384,
            max_input_bytes=1024, max_workspace_bytes=1024**2, max_output_files=1)))
    (tmp_path / "version-result.json").write_text(json.dumps(version.to_dict(), sort_keys=True, indent=2))
    assert version.ok and "4.34.1" in version.stdout and version.native_lifecycle.cleanup_confirmed
    request = process.ToolRunRequest(
        argv=(str(mixed_installed_lean), "-o", output_name, source_name),
        input_files={source_name: text}, output_paths=(source_name, output_name),
        owned_process_observation=True, environment={"LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(timeout_seconds=60, cpu_seconds=60,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=2 * 1024**2,
            max_input_bytes=8 * 1024**2, max_workspace_bytes=128 * 1024**2, max_output_files=2))
    run = process.BoundedToolRunner().run(request)
    observed = run.to_dict()
    # The common diagnostic JSON decodes binary outputs with replacement. Keep
    # exact object bytes and their digests separately for artifact custody.
    observed.pop("output_files")
    observed["captured_output_bytes"] = {name: {"bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest()} for name, body in run.output_files.items()}
    (tmp_path / "native-result.json").write_text(json.dumps(observed, sort_keys=True, indent=2))
    assert run.ok and run.returncode == 0, run.to_dict()
    assert run.runtime is process.ToolRuntime.NATIVE and type(run.pid) is int and run.pid > 0
    assert not (run.unavailable or run.timed_out or run.cancelled or run.resource_exhausted
        or run.output_truncated or run.workspace_limit_exceeded or run.error)
    assert run.workspace_cleaned and run.native_lifecycle.cleanup_confirmed
    assert run.output_files[source_name] == text.encode("utf-8") and run.output_files[output_name]
    assert hashlib.sha256(mixed_installed_lean.read_bytes()).hexdigest() == \
        "79fb1d26fa5a39385d59fdc48a711a14b0710ca6480271acce99b4d177cea085"
    # The owning attempt retains the original source, genuine object bytes and
    # process lifecycle; this is not a statutory or modal-axiom proof.
    (tmp_path / source_name).write_bytes(run.output_files[source_name])
    (tmp_path / output_name).write_bytes(run.output_files[output_name])
