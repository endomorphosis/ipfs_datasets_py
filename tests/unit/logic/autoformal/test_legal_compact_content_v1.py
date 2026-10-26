"""Compact prediction syntax and exact archival identity; no semantic admission.

Actual A/B literals are unchanged strict requests copied from the retained
current-pilot fixture custody. Other declarations are explicitly authored.
Only named tests call public relational preparation; pure integrity seams never
replace the authoritative relational expression validator or lowering.
"""
from copy import deepcopy
import hashlib
import inspect
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as compact
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.syntax_core import ast, signatures


OBJECT = signatures.LogicSort("Object")

ACTUAL_RAW = {"A": b'{"argument_roles":[{"roles":["recipient","duties"],"symbol":"Assign"},{"roles":["recipient","duties"],"symbol":"Transfer"},{"roles":["approver","recipient"],"symbol":"Approve"}],"expression":{"content_digest":"5783bcc42e86631eb1eb99445ce9c3120ba35deabd7caa6c7f69529afdcc9a8d","expression_id":"partial-7213-A","family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"interface":"TypedExpression@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"root":{"arguments":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"extension":{"children":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-A-2","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"r"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-A-3","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"d"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"partial-A-1","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Assign"},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-A-5","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"r"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-A-6","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"d"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"partial-A-4","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Transfer"}],"binders":[],"kind":"or","metadata":{},"node_id":"partial-A-0","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":["legacy.classic_letter","legacy.permission"],"interface":"LogicExtensionNode@1","metadata":{},"node_id":"partial-A-11:ext","payload":{"kind":"permission","letter":"P","resolution":"deontic","schema_version":"legacy.deontic/v1"},"payload_schema":"legacy.deontic/v1","profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-extension-node/v1"},"kind":"extension","metadata":{},"node_id":"partial-A-11","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-A-8","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"s"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-A-9","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"r"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"partial-A-7","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Approve"}],"binders":[],"kind":"implies","metadata":{},"node_id":"partial-A-10","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"s","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"partial-A-12","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"d","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"partial-A-13","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"r","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"partial-A-14","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},"schema_version":"syntax-typed-expression/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","signature_id":"partial-7213-A","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Assign","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Transfer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Approve","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}},"interpretation_status":"authored_unreviewed_declaration","schema":"legal-relational-norm-request/v1","source_binding":null}',
              "B": b'{"argument_roles":[{"roles":["recipient","duties"],"symbol":"Assign"},{"roles":["recipient","duties"],"symbol":"Transfer"},{"roles":["approver","recipient"],"symbol":"Approve"}],"expression":{"content_digest":"b3eb24ad94c5fcb597a2c4194a7936aace26532ec3761788b3e31f86dc3b6876","expression_id":"partial-7213-B","family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"interface":"TypedExpression@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"root":{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"extension":{"children":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-B-2","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"r"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-B-3","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"d"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"partial-B-1","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Assign"},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-B-5","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"r"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-B-6","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"d"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"partial-B-4","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Transfer"}],"binders":[],"kind":"or","metadata":{},"node_id":"partial-B-0","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-B-8","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"s"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"partial-B-9","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"r"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"partial-B-7","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Approve"}],"binders":[],"kind":"implies","metadata":{},"node_id":"partial-B-10","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":["legacy.classic_letter","legacy.permission"],"interface":"LogicExtensionNode@1","metadata":{},"node_id":"partial-B-11:ext","payload":{"kind":"permission","letter":"P","resolution":"deontic","schema_version":"legacy.deontic/v1"},"payload_schema":"legacy.deontic/v1","profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-extension-node/v1"},"kind":"extension","metadata":{},"node_id":"partial-B-11","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"s","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"partial-B-12","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"d","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"partial-B-13","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"r","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"partial-B-14","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},"schema_version":"syntax-typed-expression/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","signature_id":"partial-7213-B","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Assign","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Transfer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Approve","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}},"interpretation_status":"authored_unreviewed_declaration","schema":"legal-relational-norm-request/v1","source_binding":null}'}

ACTUAL_SHA = {
    "A": "cf1e3793e56ce0a0fb39ff36827adb422b12ca1efd2abc22876de0365449e15a",
    "B": "ce41fe317a2a8bf8f9f1fea3aeb8c5cf0dafeedb6f09ed4a96dcba3e8475708f",
}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def actual(label="A"):
    return json.loads(ACTUAL_RAW[label])


def project(request):
    raw = wire(request)
    return compact.project_request_v1(raw, expected_request_sha256=sha(raw))


def decode(content, context):
    c, x = wire(content), wire(context)
    return compact.decode_prediction_v1(c, x, expected_content_sha256=sha(c),
                                         expected_context_sha256=sha(x))


def restore(projection, *, content=None, context=None, identity=None, original=None):
    c = wire(projection["content"] if content is None else content)
    x = wire(projection["context"] if context is None else context)
    i = wire(projection["identity_sidecar"] if identity is None else identity)
    return compact.reconstruct_request_v1(c, x, i,
        expected_content_sha256=sha(c), expected_context_sha256=sha(x),
        expected_identity_sha256=sha(i),
        expected_original_request_sha256=(projection["original_request_sha256"]
                                          if original is None else original))


def public_prepare(request):
    raw = wire(request)
    return relational.prepare_relational_norm_v1(raw, expected_request_sha256=sha(raw))


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["normalization"]["semantic_normalization"] is False
    assert report["normalization"]["permitted_inference_context_verified"] is False
    if "request" in report:
        assert report["request"]["source_binding"] is None
        assert report["request"]["interpretation_status"] == "authored_unreviewed_declaration"


def nodes(expression):
    result = []
    def visit(node):
        result.append(node)
        for child in node["arguments"]:
            visit(child)
        for child in node.get("extension", {}).get("children", []):
            visit(child)
    visit(expression["root"])
    return result


def compact_nodes(content):
    result = []
    def visit(tree):
        result.append(tree)
        if tree[0] == "predicate":
            for child in tree[2]: visit(child)
        elif tree[0] in {"forall", "exists", "extension"}:
            visit(tree[2])
        elif tree[0] in {"and", "or", "implies", "iff"}:
            visit(tree[1]); visit(tree[2])
        elif tree[0] == "not":
            visit(tree[1])
    visit(content["tree"])
    return result


def topology(request):
    """Independent identity/alpha comparison, never supplied to the decoder.

    Keeps every constructor, sort, symbol, ordered role/argument and modal
    payload. Only archival IDs/digest and binder spelling are normalized.
    The comparison value is deliberately not an admissible serialized AST.
    """
    value = deepcopy(request)
    expression = value["expression"]
    expression.pop("content_digest", None)
    expression["expression_id"] = "identity"
    expression["signature"]["signature_id"] = "identity"
    count = 0
    def visit(node, environment):
        nonlocal count
        node["node_id"] = "identity"
        if node["kind"] in {"forall", "exists"}:
            environment = dict(environment)
            name = node["binders"][0]["name"]
            replacement = "binder" + str(count)
            count += 1
            environment[name] = replacement
            node["binders"][0]["name"] = replacement
        if node["kind"] == "variable":
            node["symbol"] = environment[node["symbol"]]
        for child in node["arguments"]: visit(child, environment)
        if "extension" in node:
            node["extension"]["node_id"] = "identity"
            for child in node["extension"]["children"]: visit(child, environment)
    visit(expression["root"], {})
    return value


def resign(request):
    request = deepcopy(request)
    request["expression"].pop("content_digest", None)
    request["expression"] = ast.TypedExpression.from_dict(request["expression"]).to_dict()
    return request


class Builder:
    def __init__(self): self.count = 0
    def nid(self):
        self.count += 1
        return "authored-compact:" + str(self.count)
    def atom(self, name, *names):
        return ast.mk_predicate(self.nid(), name,
            [ast.mk_variable(self.nid(), value, OBJECT) for value in names])
    def binary(self, kind, left, right):
        return {"and": ast.mk_and, "or": ast.mk_or,
                "implies": ast.mk_implies, "iff": ast.mk_iff}[kind](self.nid(), left, right)
    def modal(self, letter, child):
        kind = {"O": "obligation", "P": "permission", "F": "forbidden"}[letter]
        return ast.mk_extension(self.nid(), family="tdfol", profile="tdfol_default",
            features=("legacy." + kind, "legacy.classic_letter"),
            payload_schema="legacy.deontic/v1",
            payload={"kind": kind, "letter": letter, "resolution": "deontic",
                     "schema_version": "legacy.deontic/v1"}, children=(child,))


def authored(builder, body, declarations, binders=(("x", "forall"),)):
    for name, quantifier in reversed(binders):
        body = (ast.mk_forall if quantifier == "forall" else ast.mk_exists)(
            builder.nid(), (ast.Binder(name, OBJECT),), body)
    signature = signatures.LogicSignature("authored-compact-signature", family="tdfol",
        profile="tdfol_default", sorts=(OBJECT,),
        symbols=tuple(signatures.declare_predicate(name, (OBJECT,) * len(roles))
                      for name, roles in declarations))
    expression = ast.TypedExpression("authored-compact-expression", body, signature)
    return {"schema": "legal-relational-norm-request/v1",
            "interpretation_status": "authored_unreviewed_declaration",
            "source_binding": None, "expression": expression.to_dict(),
            "argument_roles": [{"symbol": name, "roles": list(roles)}
                               for name, roles in declarations]}


def unary_definition(disjunction=True):
    """Short-name authored AST analogue, not actual definition qualification."""
    b = Builder()
    if disjunction:
        body = b.binary("iff", b.atom("Defined", "x"),
                        b.binary("or", b.atom("Commissioned", "x"), b.atom("Warrant", "x")))
        names = ("Defined", "Commissioned", "Warrant")
    else:
        body = b.binary("iff", b.atom("Defined", "x"), b.atom("OpaqueBody", "x"))
        names = ("Defined", "OpaqueBody")
    return authored(b, body, [(name, ("subject",)) for name in names])


def unary_request(name="Eligible"):
    b = Builder()
    return authored(b, b.atom(name, "x"), [(name, ("subject",))])


@pytest.mark.parametrize("label", ["A", "B"])
def test_actual_public_owner_projection_prediction_and_exact_archival_replay(label):
    """Genuine public relational preparation, no compiler/backend execution."""
    raw = ACTUAL_RAW[label]
    assert len(raw) == 7254 and sha(raw) == ACTUAL_SHA[label]
    request = actual(label)
    before = deepcopy(request)
    projection = compact.project_request_v1(raw, expected_request_sha256=ACTUAL_SHA[label])
    restored = restore(projection)
    prediction = decode(projection["content"], projection["context"])
    original_owner = public_prepare(request)
    restored_owner = public_prepare(restored["request"])
    assert restored["request"] == request == before
    assert restored["typed_expression"] == request["expression"]
    assert restored_owner["typed_expression"] == original_owner["typed_expression"]
    assert restored_owner["native_ast"] == original_owner["native_ast"]
    assert restored_owner["argument_roles"] == request["argument_roles"]
    assert topology(prediction["request"]) == topology(request)
    assert prediction["request"] != request
    assert prediction["identity_mode"] == "generated" and restored["identity_mode"] == "restored"
    assert projection["counts"] == prediction["counts"] == restored["counts"] == {
        "nodes": 15, "quantifiers": 3, "modal_nodes": 1, "predicate_occurrences": 3}
    assert projection["original_request_raw_sha256"] == ACTUAL_SHA[label]
    assert projection["original_request_sha256"] == sha(wire(request))
    assert len(projection["identity_sidecar"]["node_ids"]) == 15
    assert projection["identity_sidecar"]["binder_names"] == ["r", "d", "s"]
    for report in (projection, restored, prediction): no_authority(report)
    if label == "A":
        replay = relational.validate_relational_norm_v1(original_owner, wire(request),
            expected_request_sha256=sha(wire(request)),
            expected_report_sha256=relational.relational_norm_report_sha256(original_owner))
        assert replay == original_owner


def test_actual_context_prepared_without_target_and_scope_alternative_decoded_as_new_candidate():
    a, b = project(actual("A")), project(actual("B"))
    signature, roles = wire(actual()["expression"]["signature"]), wire(actual()["argument_roles"])
    independent_context = compact.prepare_context_v1(signature, roles,
        expected_signature_sha256=sha(signature), expected_argument_roles_sha256=sha(roles))
    assert independent_context == a["context"] == b["context"]
    assert "signature_id" not in independent_context["signature"]
    assert set(independent_context) == {"schema", "signature", "argument_roles"}
    assert a["content"] != b["content"]
    assert [row["roles"] for row in independent_context["argument_roles"]] == [
        ["recipient", "duties"], ["recipient", "duties"], ["approver", "recipient"]]
    candidate = decode(b["content"], a["context"])
    assert topology(candidate["request"]) == topology(actual("B"))
    assert topology(candidate["request"]) != topology(actual("A"))
    assert set(inspect.signature(compact.decode_prediction_v1).parameters) == {
        "content_raw", "context_raw", "expected_content_sha256", "expected_context_sha256"}
    no_authority(candidate)


@pytest.mark.parametrize("change", ["connective", "ordered_arguments"])
def test_target_free_valid_prediction_changes_are_retained_without_target_repair(change):
    p = project(actual())
    content = deepcopy(p["content"])
    if change == "connective":
        next(row for row in compact_nodes(content) if row[0] == "or")[0] = "and"
    else:
        atom = next(row for row in compact_nodes(content) if row[0] == "predicate" and row[1] == 2)
        atom[2].reverse()
    report = decode(content, p["context"])
    assert report["content"] == content and content != p["content"]
    assert topology(report["request"]) != topology(actual())
    assert report["context"]["argument_roles"] == actual()["argument_roles"]
    no_authority(report)


@pytest.mark.parametrize("disjunction", [False, True])
def test_public_short_named_unary_iff_body_is_only_an_authored_ast_fragment(disjunction):
    request = unary_definition(disjunction)
    p = project(request)
    original = public_prepare(request)
    restored = public_prepare(restore(p)["request"])
    assert original["native_ast"] == restored["native_ast"]
    assert topology(decode(p["content"], p["context"])["request"]) == topology(request)
    assert p["counts"] == {"nodes": 9 if disjunction else 6, "quantifiers": 1, "modal_nodes": 0,
                           "predicate_occurrences": 3 if disjunction else 2}
    no_authority(p)


@pytest.mark.parametrize("letter", ["O", "P", "F"])
def test_authored_modal_letters_existential_not_and_binary_structure_are_preserved(letter):
    b = Builder()
    body = b.modal(letter, ast.mk_not(b.nid(), b.atom("Eligible", "x")))
    request = authored(b, body, [("Eligible", ("subject",))], (("x", "exists"),))
    p = project(request)
    decoded = decode(p["content"], p["context"])
    assert p["content"]["tree"][0] == "exists"
    assert next(row for row in compact_nodes(p["content"]) if row[0] == "extension")[1] == letter
    assert topology(decoded["request"]) == topology(request)
    assert restore(p)["request"] == request
    no_authority(decoded)


def test_alpha_and_archival_id_changes_do_not_enter_prediction_content():
    original = actual()
    changed = deepcopy(original)
    expression = changed["expression"]
    expression["expression_id"] = "authored-new-expression"
    expression["signature"]["signature_id"] = "authored-new-signature"
    renamed = {"r": "recipient", "d": "duties", "s": "approver"}
    for index, node in enumerate(nodes(expression)):
        node["node_id"] = "authored-new-node:" + str(index)
        if node["kind"] == "variable": node["symbol"] = renamed[node["symbol"]]
        for binder in node["binders"]: binder["name"] = renamed[binder["name"]]
        if "extension" in node: node["extension"]["node_id"] = "authored-new-extension"
    changed = resign(changed)
    a, b = project(original), project(changed)
    assert a["content"] == b["content"] and a["context"] == b["context"]
    assert a["identity_sidecar"] != b["identity_sidecar"]
    assert restore(b)["request"] == changed
    assert decode(a["content"], a["context"])["request"] == decode(b["content"], b["context"])["request"]


def test_whitespace_raw_commitments_and_canonical_original_identity_are_distinct():
    request = actual()
    pretty = json.dumps(request, indent=2, ensure_ascii=False).encode()
    p = compact.project_request_v1(pretty, expected_request_sha256=sha(pretty))
    assert p["original_request_raw_sha256"] == sha(pretty)
    assert p["original_request_sha256"] == sha(wire(request)) != sha(pretty)
    c, x = json.dumps(p["content"], indent=2).encode(), json.dumps(p["context"], indent=2).encode()
    report = compact.decode_prediction_v1(c, x, expected_content_sha256=sha(c), expected_context_sha256=sha(x))
    assert report["content_sha256"] == compact.compact_content_sha256(p["content"])
    assert report["input_raw_sha256"] == {"content": sha(c), "context": sha(x)}
    assert restore(p)["request"] == request
    with pytest.raises(ValueError): restore(p, original=sha(pretty))


def test_role_ledger_reauthoring_is_new_context_not_an_automatic_semantic_refusal():
    p = project(actual())
    context = deepcopy(p["context"])
    context["argument_roles"][2]["roles"].reverse()
    raw, c = wire(context), wire(p["content"])
    with pytest.raises(ValueError):
        compact.decode_prediction_v1(c, raw, expected_content_sha256=sha(c),
                                     expected_context_sha256=sha(wire(p["context"])))
    authored_candidate = decode(p["content"], context)
    assert authored_candidate["request"]["argument_roles"] == context["argument_roles"]
    assert authored_candidate["typed_expression"] != actual()["expression"]
    no_authority(authored_candidate)
    with pytest.raises(ValueError): restore(p, context=context)


@pytest.mark.parametrize("mutation", ["free", "boolean", "negative", "noncanonical", "repeated", "capture"])
def test_lexical_binder_references_and_global_preorder_are_checked(mutation):
    p = project(actual())
    content = deepcopy(p["content"])
    rows = compact_nodes(content)
    if mutation in {"free", "boolean", "negative"}:
        next(row for row in rows if row[0] == "variable")[1] = {"free": 99, "boolean": True, "negative": -1}[mutation]
    elif mutation == "noncanonical": content["tree"][1] = 1
    elif mutation == "repeated":
        [row for row in rows if row[0] == "forall"][1][1] = 0
    else:
        # Binder0 exists globally but its left-branch scope has ended.
        content["tree"] = ["and",
            ["forall", 0, ["predicate", 0, [["variable", 0], ["variable", 0]]]],
            ["forall", 1, ["and",
                ["predicate", 1, [["variable", 1], ["variable", 1]]],
                ["predicate", 2, [["variable", 1], ["variable", 0]]]]]]
    with pytest.raises(ValueError): decode(content, p["context"])


@pytest.mark.parametrize("mutation", ["unknown", "boolean", "arity", "formula_argument", "unused"])
def test_predicate_references_exact_arity_variable_arguments_and_complete_use(mutation):
    p = project(actual())
    content = deepcopy(p["content"])
    atom = next(row for row in compact_nodes(content) if row[0] == "predicate")
    if mutation == "unknown": atom[1] = 99
    elif mutation == "boolean": atom[1] = False
    elif mutation == "arity": atom[2].pop()
    elif mutation == "formula_argument": atom[2][0] = ["not", ["variable", 0]]
    else:
        next(row for row in compact_nodes(content) if row[0] == "predicate" and row[1] == 1)[1] = 0
    with pytest.raises(ValueError): decode(content, p["context"])


@pytest.mark.parametrize("tag", ["constant", "function", "equals", "always", "cardinality", "unknown"])
def test_unsupported_constructor_is_refused_without_repair(tag):
    p = project(actual())
    content = deepcopy(p["content"])
    next(row for row in compact_nodes(content) if row[0] == "or")[0] = tag
    with pytest.raises(ValueError): decode(content, p["context"])


@pytest.mark.parametrize("mutation", ["letter", "modal_arity", "binary_arity", "unary_arity", "schema", "extra", "provenance", "authority"])
def test_exact_content_schema_shape_and_no_provenance_or_authority_intake(mutation):
    p = project(actual())
    content = deepcopy(p["content"])
    if mutation == "letter": next(row for row in compact_nodes(content) if row[0] == "extension")[1] = "G"
    elif mutation == "modal_arity": next(row for row in compact_nodes(content) if row[0] == "extension").append([])
    elif mutation == "binary_arity": next(row for row in compact_nodes(content) if row[0] == "or").pop()
    elif mutation == "unary_arity": content["tree"] = ["not", content["tree"], content["tree"]]
    elif mutation == "schema": content["schema"] = "legal-relational-compact-content/v2"
    else: content[{"extra": "unexpected", "provenance": "source_binding", "authority": "training_mask"}[mutation]] = 1
    with pytest.raises(ValueError): decode(content, p["context"])


@pytest.mark.parametrize("mutation", ["profile", "version", "sort", "function", "metadata", "features", "roles", "signature_id", "expression", "schema"])
def test_context_strict_signature_and_closed_identity_free_fields(mutation):
    p = project(actual())
    context = deepcopy(p["context"])
    sig = context["signature"]
    if mutation == "profile": sig["profile"]["value"] = "unrecognized"
    elif mutation == "version": sig["profile"]["version"] = "2.0.0"
    elif mutation == "sort": sig["symbols"][0]["domain"][0] = deepcopy(sig["sorts"][0])
    elif mutation == "function": sig["symbols"][0]["kind"] = "function"
    elif mutation == "metadata": sig["metadata"] = {"accepted": True}
    elif mutation == "features": sig["features"] = ["new-feature"]
    elif mutation == "roles": context["argument_roles"][0]["roles"] = ["recipient"]
    elif mutation == "signature_id": sig["signature_id"] = "not-content"
    elif mutation == "expression": context["expression"] = actual()["expression"]
    else: context["schema"] += "-unknown"
    with pytest.raises((ValueError, TypeError)): decode(p["content"], context)


def test_predicate_keyed_role_rows_may_reorder_with_explicit_new_context_identity():
    p = project(actual())
    context = deepcopy(p["context"])
    context["argument_roles"].reverse()
    changed = decode(p["content"], context)
    original = decode(p["content"], p["context"])
    assert changed["request"]["argument_roles"] == context["argument_roles"]
    assert topology(changed["request"])["expression"] == topology(original["request"])["expression"]
    assert changed["context_sha256"] != original["context_sha256"]
    no_authority(changed)
    with pytest.raises(ValueError): restore(p, context=context)


@pytest.mark.parametrize("mutation", ["expression_id", "signature_id", "node_id", "node_reorder", "missing_node", "extra_node", "missing_extension", "extra_extension", "extension_duplicate", "missing_binder", "extra_binder", "binder_reorder", "shadow", "predicate_collision", "content_hash", "context_hash", "expression_hash", "original_hash", "schema", "authority"])
def test_resealed_identity_damage_cannot_change_independently_pinned_original(mutation):
    p = project(actual())
    identity = deepcopy(p["identity_sidecar"])
    if mutation in {"expression_id", "signature_id"}: identity[mutation] += "-changed"
    elif mutation == "node_id": identity["node_ids"][0] += "-changed"
    elif mutation == "node_reorder": identity["node_ids"][0:2] = reversed(identity["node_ids"][0:2])
    elif mutation == "missing_node": identity["node_ids"].pop()
    elif mutation == "extra_node": identity["node_ids"].append("extra-node")
    elif mutation == "missing_extension": identity["extension_ids"].clear()
    elif mutation == "extra_extension": identity["extension_ids"].append("extra-extension")
    elif mutation == "extension_duplicate": identity["extension_ids"][0] = identity["node_ids"][0]
    elif mutation == "missing_binder": identity["binder_names"].pop()
    elif mutation == "extra_binder": identity["binder_names"].append("extra")
    elif mutation == "binder_reorder": identity["binder_names"][0:2] = reversed(identity["binder_names"][0:2])
    elif mutation == "shadow": identity["binder_names"][1] = identity["binder_names"][0]
    elif mutation == "predicate_collision": identity["binder_names"][0] = "Assign"
    elif mutation in {"content_hash", "context_hash", "expression_hash", "original_hash"}:
        identity[{"content_hash": "content_sha256", "context_hash": "context_sha256",
                  "expression_hash": "original_expression_sha256", "original_hash": "original_request_sha256"}[mutation]] = "0" * 64
    elif mutation == "schema": identity["schema"] += "-unknown"
    else: identity["evaluation_gold_mask"] = 1
    # restore() recomputes the changed raw sidecar hash; original pin stays fixed.
    with pytest.raises((ValueError, TypeError)): restore(p, identity=identity)


def test_cross_alternative_sidecar_and_resealed_original_claim_are_refused():
    a, b = project(actual("A")), project(actual("B"))
    with pytest.raises(ValueError): restore(a, identity=b["identity_sidecar"])
    forged = deepcopy(a["identity_sidecar"])
    forged["original_request_sha256"] = "1" * 64
    with pytest.raises(ValueError): restore(a, identity=forged, original="1" * 64)


@pytest.mark.parametrize("location", ["content", "context", "identity", "request"])
def test_duplicate_json_keys_are_refused_at_each_wire_entry(location):
    p = project(actual())
    if location == "request":
        raw = b'{"schema":"legal-relational-norm-request/v1",' + ACTUAL_RAW["A"][1:]
        with pytest.raises(ValueError): compact.project_request_v1(raw, expected_request_sha256=sha(raw))
    else:
        value = p["identity_sidecar"] if location == "identity" else p[location]
        raw = b'{"schema":' + wire(value["schema"]) + b',' + wire(value)[1:]
        c, x, i = wire(p["content"]), wire(p["context"]), wire(p["identity_sidecar"])
        if location == "content": c = raw
        elif location == "context": x = raw
        else: i = raw
        with pytest.raises(ValueError):
            compact.reconstruct_request_v1(c, x, i,
                expected_content_sha256=sha(c), expected_context_sha256=sha(x),
                expected_identity_sha256=sha(i), expected_original_request_sha256=p["original_request_sha256"])


@pytest.mark.parametrize("raw", [b'\xff', b'{', b'{"tree":NaN}', b'{"tree":Infinity}', b'{"tree":1.0}', b'{"tree":9223372036854775808}'])
def test_invalid_utf8_json_numbers_and_large_integers_refused(raw):
    p = project(actual())
    x = wire(p["context"])
    with pytest.raises(ValueError): compact.decode_prediction_v1(raw, x,
        expected_content_sha256=sha(raw), expected_context_sha256=sha(x))


@pytest.mark.parametrize("raw", [None, "{}", bytearray(b"{}"), b""])
def test_exact_nonempty_bytes_required(raw):
    with pytest.raises(ValueError): compact.project_request_v1(raw, expected_request_sha256=sha(b"{}"))


@pytest.mark.parametrize("pin", ["0" * 64, "A" * 64, "short", None])
def test_independent_raw_hash_pin_required(pin):
    with pytest.raises(ValueError): compact.project_request_v1(ACTUAL_RAW["A"], expected_request_sha256=pin)


def test_real_content_byte_boundary_and_oversize_intakes():
    p = project(actual())
    c, x, i = wire(p["content"]), wire(p["context"]), wire(p["identity_sidecar"])
    padded = c + b" " * (compact.MAX_CONTENT_BYTES - len(c))
    accepted = compact.decode_prediction_v1(padded, x,
        expected_content_sha256=sha(padded), expected_context_sha256=sha(x))
    assert accepted["content"] == p["content"]
    for location, raw, limit in (("content", c, compact.MAX_CONTENT_BYTES),
                                 ("context", x, compact.MAX_CONTEXT_BYTES),
                                 ("identity", i, compact.MAX_IDENTITY_BYTES),
                                 ("request", ACTUAL_RAW["A"], compact.MAX_REQUEST_BYTES)):
        oversized = raw + b" " * (limit + 1 - len(raw))
        if location == "request":
            with pytest.raises(ValueError): compact.project_request_v1(oversized, expected_request_sha256=sha(oversized))
        else:
            values = {"content": c, "context": x, "identity": i}
            values[location] = oversized
            with pytest.raises(ValueError):
                compact.reconstruct_request_v1(values["content"], values["context"], values["identity"],
                    expected_content_sha256=sha(values["content"]), expected_context_sha256=sha(values["context"]),
                    expected_identity_sha256=sha(values["identity"]),
                    expected_original_request_sha256=p["original_request_sha256"])


def balanced(rows):
    while len(rows) > 1:
        rows = [["and", rows[i], rows[i + 1]] for i in range(0, len(rows), 2)]
    return rows[0]


def test_real_512_node_boundary_and_513_node_refusal():
    p = project(unary_request())
    #128*(not+predicate+variable)+127binary+1quantifier=512 actual AST nodes.
    content = {"schema": compact.CONTENT_SCHEMA, "tree": ["forall", 0, balanced([
        ["not", ["predicate", 0, [["variable", 0]]]] for _ in range(128)])]}
    report = decode(content, p["context"])
    assert report["counts"]["nodes"] == 512
    assert report["counts"]["predicate_occurrences"] == 128
    content["tree"][2] = ["not", content["tree"][2]]
    with pytest.raises(ValueError): decode(content, p["context"])


def test_ast_depth_and_ordinary_json_depth_and_item_caps_refuse_without_truncation():
    p = project(unary_request())
    tree = ["predicate", 0, [["variable", 0]]]
    for _ in range(50): tree = ["not", tree]
    with pytest.raises(ValueError): decode({"schema": compact.CONTENT_SCHEMA, "tree": ["forall", 0, tree]}, p["context"])
    nested = 0
    for _ in range(98): nested = [nested]
    with pytest.raises(ValueError): compact.compact_content_sha256(nested)
    with pytest.raises(ValueError): compact.compact_content_sha256([None] * 100001)


@pytest.mark.parametrize("value", [1.0, float("nan"), {1: "key"}, {"nul": "\x00"}, {"surrogate": "\ud800"}])
def test_public_hash_helpers_accept_only_bounded_ordinary_json(value):
    with pytest.raises(ValueError): compact.compact_content_sha256(value)


def test_public_hash_helper_cycle_and_repeated_string_budget_are_bounded_before_serialization(monkeypatch):
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError): compact.compact_content_sha256(cyclic)
    #Only16KiB of string storage, referenced64times; a >1MiB serialization
    #must be rejected by cumulative byte admission before complete dumps.
    payload = ["x" * 16384] * 64
    def forbidden_dumps(*args, **kwargs):
        raise AssertionError("full serialization happened before byte refusal")
    #Labelled JSON serializer seam; authoritative AST/lowering untouched.
    monkeypatch.setattr(compact.json, "dumps", forbidden_dumps)
    with pytest.raises(ValueError, match="byte bound"): compact.compact_content_sha256(payload)


def test_escaped_and_nonascii_canonical_byte_budget_matches_independent_wire():
    value = {"quotes": '\\"\n\t\x01', "unicode": "é漢🙂"}
    assert compact.compact_content_sha256(value) == sha(wire(value))
    size = len(wire(value))
    #Labelled pure byte-accounting seam, no owner qualification credit.
    assert compact._wire(value, size) == wire(value)
    with pytest.raises(ValueError): compact._wire(value, size - 1)


def test_actual_65_character_definition_predicate_remains_unsupported_not_silently_renamed():
    #Exact retained B definition's predicate name; this authored unary request
    #only exercises its existing strict-name boundary, not actual definition IR.
    name = "D22ec21af4fa1f658c1a5fc4e008abd407fb4ed50549d7b5b410dce52e88ddf55"
    assert len(name) == 65
    with pytest.raises(ValueError): project(unary_request(name))


def test_public_decoder_generates_fresh_binder_names_despite_predicate_collisions():
    names = ["CompactBinder0", "CompactBinder0_0"]
    b = Builder()
    request = authored(b, b.binary("and", *(b.atom(name, "x") for name in names)),
                       [(name, ("subject",)) for name in names])
    p = project(request)
    report = decode(p["content"], p["context"])
    binder = report["typed_expression"]["root"]["binders"][0]["name"]
    assert binder not in names and len(binder) <= 64
    assert topology(report["request"]) == topology(request)


def test_public_decode_accepts_64_predicate_collision_catalog_without_name_overflow():
    #A valid catalog covers every growing-x name through64characters, plus
    #the normal nonce candidate. All64declared predicates genuinely occur.
    base = "CompactBinder0"
    names = [base + "x" * n for n in range(65 - len(base))]
    names += ["CompactBinder0_" + str(n) for n in range(64 - len(names))]
    assert len(names) == len(set(names)) == 64 and max(map(len, names)) == 64
    b = Builder()
    #Build an independent context directly; no target is provided to decoding.
    signature = signatures.LogicSignature("collision-catalog", family="tdfol", profile="tdfol_default",
        sorts=(OBJECT,), symbols=tuple(signatures.declare_predicate(name, (OBJECT,)) for name in names))
    sig, roles = wire(signature.to_dict()), wire([{"symbol": name, "roles": ["subject"]} for name in names])
    context = compact.prepare_context_v1(sig, roles, expected_signature_sha256=sha(sig),
                                         expected_argument_roles_sha256=sha(roles))
    content = {"schema": compact.CONTENT_SCHEMA, "tree": ["forall", 0,
        balanced([["predicate", index, [["variable", 0]]] for index in range(64)])]}
    report = decode(content, context)
    assert report["counts"]["predicate_occurrences"] == 64
    binder = report["typed_expression"]["root"]["binders"][0]["name"]
    assert binder not in names and len(binder) <= 64
    no_authority(report)


def test_returned_values_detach_from_inputs_and_prior_report_mutations():
    request = actual()
    before = deepcopy(request)
    p = project(request)
    original = deepcopy(p)
    decoded = decode(p["content"], p["context"])
    decoded["request"]["expression"]["root"]["node_id"] = "changed-output"
    decoded["context"]["argument_roles"][0]["roles"].reverse()
    assert request == before and p == original
    p["authority"]["accepted"] = True
    p["training_mask"] = 1
    fresh = project(request)
    assert fresh == original
    no_authority(fresh)


@pytest.mark.parametrize("operation", ["project", "decode", "restore", "context"])
def test_producer_pin_change_is_refused_by_real_source_fence_integrity_seam(operation, monkeypatch):
    p = project(actual())
    monkeypatch.setattr(compact, "_SELF_SHA", "0" * 64)
    with pytest.raises(ValueError, match="producer changed"):
        if operation == "project": project(actual())
        elif operation == "decode": decode(p["content"], p["context"])
        elif operation == "restore": restore(p)
        else:
            signature, roles = wire(actual()["expression"]["signature"]), wire(actual()["argument_roles"])
            compact.prepare_context_v1(signature, roles, expected_signature_sha256=sha(signature),
                                       expected_argument_roles_sha256=sha(roles))


@pytest.mark.parametrize("operation", ["project", "decode", "restore"])
def test_final_report_serialization_precedes_real_source_closeout_integrity_seam(operation, monkeypatch):
    p = project(actual())
    detach = compact._detach
    seen = []
    def changing_detach(value, maximum):
        result = detach(value, maximum)
        if isinstance(value, dict) and value.get("schema") in {
                compact.PROJECT_SCHEMA, compact.DECODE_SCHEMA, compact.RECONSTRUCT_SCHEMA}:
            seen.append(value["schema"])
            monkeypatch.setattr(compact, "_SELF_SHA", "0" * 64)
        return result
    #Only the new module's final report serializer is instrumented; all real
    #authoritative owner hooks and final source checks remain intact.
    monkeypatch.setattr(compact, "_detach", changing_detach)
    with pytest.raises(ValueError, match="producer changed"):
        if operation == "project": project(actual())
        elif operation == "decode": decode(p["content"], p["context"])
        else: restore(p)
    assert len(seen) == 1
