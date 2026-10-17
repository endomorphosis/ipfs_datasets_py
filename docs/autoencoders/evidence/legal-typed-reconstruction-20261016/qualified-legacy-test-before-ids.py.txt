"""Authored finite models qualify a strict fragment, without legal truth claims."""
from copy import deepcopy
import hashlib
import itertools
import json

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
