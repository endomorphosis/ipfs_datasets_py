"""Fixed authored A/B composition; no Lean executable or model is invoked."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_full_norm_consequences_v1 as composition
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.syntax_core import ast, signatures


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def request(label):
    """Use existing public typed AST constructors, retaining the authored roles."""
    obj = signatures.LogicSort("Object")
    next_id = iter(range(100))

    def nid():
        return "fixture:node:" + str(next(next_id))

    def atom(name, *args):
        return ast.mk_predicate(nid(), name, [ast.mk_variable(nid(), arg, obj) for arg in args])

    def permission(body):
        return ast.mk_extension(nid(), family="tdfol", profile="tdfol_default",
            features=("legacy.permission", "legacy.classic_letter"),
            payload_schema="legacy.deontic/v1",
            payload={"kind": "permission", "letter": "P", "resolution": "deontic",
                     "schema_version": "legacy.deontic/v1"}, children=(body,))

    actions = ast.mk_or(nid(), atom("Assign", "r", "d"), atom("Transfer", "r", "d"))
    approval = atom("Approve", "s", "r")
    root = (ast.mk_implies(nid(), permission(actions), approval) if label == "A"
            else permission(ast.mk_implies(nid(), actions, approval)))
    for name in reversed(("r", "d", "s")):
        root = ast.mk_forall(nid(), [ast.Binder(name, obj)], root)
    roles = [("Assign", ["recipient", "duties"]), ("Transfer", ["recipient", "duties"]),
             ("Approve", ["approver", "recipient"])]
    signature = signatures.LogicSignature("fixture:signature", family="tdfol",
        profile="tdfol_default", sorts=(obj,), symbols=tuple(
            signatures.declare_predicate(name, (obj, obj)) for name, _ in roles))
    return {"schema": relational.REQUEST_SCHEMA, "interpretation_status": "authored_unreviewed_declaration",
        "expression": ast.TypedExpression("fixture:expression", root, signature).to_dict(),
        "argument_roles": [{"symbol": name, "roles": labels} for name, labels in roles],
        "source_binding": None}


@pytest.fixture(scope="module")
def original():
    raw = {label: wire(request(label)) for label in ("A", "B")}
    reports = {label: relational.prepare_relational_norm_v1(raw[label],
        expected_request_sha256=sha(raw[label])) for label in ("A", "B")}
    return reports, raw


def compose(reports, raw, **overrides):
    arguments = {"expected_request_sha256": {label: sha(raw[label]) for label in ("A", "B")},
        "expected_report_sha256": {label: relational.relational_norm_report_sha256(reports[label])
                                    for label in ("A", "B")}}
    arguments.update(overrides)
    return composition.prepare_full_norm_consequences_v1(reports, raw, **arguments)


@pytest.fixture
def forbid_composition(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid input reached conditional-source emission")
    monkeypatch.setattr(composition, "_joint_source", forbidden)


def test_exact_retained_source_and_conditional_metadata(original):
    reports, raw = original
    before = deepcopy(reports)
    result = compose(reports, raw)
    fixture = Path(__file__).parent / "fixtures/legal_full_norm_consequences_v1"
    golden = (fixture / "LegalFullNorms.lean").read_bytes()
    provenance = json.loads((fixture / "provenance.json").read_text())
    assert sha(golden) == provenance["historical_golden"]["sha256"] == \
        "30e70c9ea780e0bc5f2e3a17be9ad21447dbaf42e102e47e74c5fb99a9c755ba"
    assert result["lean_source"].encode() == golden
    assert result["lean_source_sha256"] == sha(golden) and result["lean_source_bytes"] == 3503
    assert reports == before
    assert result["conditional_theorems"] == ["LegalFullNorms.CandidateA.norm_instance",
        "LegalFullNorms.CandidateA.approval_from_permission", "LegalFullNorms.CandidateB.modal_instance"]
    assert result["rendering"]["shared_interpretation_prelude_instances"] == 1
    for label in ("A", "B"):
        item = result["rendering"]["emitted_body_slices"][label]
        assert golden[item["byte_start"]:item["byte_end"]] == reports[label]["lean_body"].encode()
        assert item["sha256"] == sha(reports[label]["lean_body"].encode())
    assert result["assumptions"] and all(flag is False for flag in result["authority"].values())
    assert result["selected_interpretation"] is result["governing_definition_use"] is None
    for key in ("training_mask", "evaluation_gold_mask", "human_reviews", "signatures_constructed", "admissions"):
        assert type(result[key]) is int and result[key] == 0
    for key in ("source_translation_performed", "current_source_or_definition_replay_performed",
                "kernel_compilation_performed", "native_build_executed", "proof_checked",
                "model_executed", "training_executed"):
        assert result[key] is False


@pytest.mark.parametrize("kind,label", [("request", "A"), ("request", "B"), ("report", "A"), ("report", "B")])
def test_independent_pins_are_required(original, forbid_composition, kind, label):
    reports, raw = original
    pins = {item: sha(raw[item]) if kind == "request" else relational.relational_norm_report_sha256(reports[item])
            for item in ("A", "B")}
    pins[label] = "0" * 64
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        compose(reports, raw, **{"expected_" + kind + "_sha256": pins})


@pytest.mark.parametrize("mutation", ["lean_body", "unknown_field", "producer_pin"])
def test_resealed_report_still_requires_full_owner_replay(original, forbid_composition, mutation):
    reports, raw = deepcopy(original)
    if mutation == "lean_body":
        reports["A"]["lean_body"] += "\naxiom injected : False\n"
    elif mutation == "unknown_field":
        reports["A"]["unexpected"] = "unadmitted field"
    else:
        reports["A"]["producer_pins"][next(iter(reports["A"]["producer_pins"]))] = "0" * 64
    with pytest.raises(ValueError, match="authoritative replay"):
        compose(reports, raw)


def test_unknown_request_fields_are_rejected(original, forbid_composition):
    reports, raw = deepcopy(original)
    value = json.loads(raw["A"])
    value["unexpected"] = True
    raw["A"] = wire(value)
    with pytest.raises(ValueError, match="closed exact fields"):
        compose(reports, raw)


@pytest.mark.parametrize("mutation", ["modal_placement", "argument_order", "authority"])
def test_semantic_changes_are_refused_before_composition(original, forbid_composition, mutation):
    reports, raw = deepcopy(original)
    if mutation == "modal_placement":
        reports["A"] = deepcopy(reports["B"])
        raw["A"] = raw["B"]
    elif mutation == "argument_order":
        core = reports["A"]["native_ast"]["formula"]["formula"]["formula"]
        core["right"]["arguments"].reverse()
    else:
        reports["A"]["authority"]["accepted"] = True
    with pytest.raises(ValueError):
        compose(reports, raw)


def test_closed_candidate_mapping_and_ordinary_inputs(original, forbid_composition):
    reports, raw = original
    with pytest.raises(ValueError, match="exact A/B"):
        composition.prepare_full_norm_consequences_v1(reports | {"C": reports["A"]}, raw,
            expected_request_sha256={}, expected_report_sha256={})
