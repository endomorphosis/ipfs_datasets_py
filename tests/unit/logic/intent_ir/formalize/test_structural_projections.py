"""Native structural projections preserve declaration data without proof claims."""
from dataclasses import replace
import copy
import json

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import structural_projections as subject
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import (
    make_projection, source_ir_sha256, validate_projection,
)
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir


@pytest.fixture
def document():
    return frame_to_intent_ir(
        {"actor": "agent", "action": "read", "object": "report", "modality": "required"},
        instruction="agent must read report.")


def _settings(*families, **extra):
    return {"structural": {"requested_families": list(families), **extra}}


def test_native_frontends_execute_and_exactly_preserve_declarations(document, monkeypatch):
    from ipfs_datasets_py.logic.parsers import flogic, rules

    calls = []
    for module, name in ((flogic, "parse_print_parse_flogic"),
                         (rules, "parse_print_parse_rules"), (rules, "lower_to_chc")):
        original = getattr(module, name)
        def observe(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, observe)
    reports = subject.project_structural_families(document)
    assert calls == ["parse_print_parse_flogic", "parse_print_parse_rules", "lower_to_chc"]
    assert [row["family_id"] for row in reports] == list(subject.DEFAULT_FAMILIES)
    for row in reports:
        assert row["status"] == "projected" and not row["unsupported"]
        assert row["semantics"] == "reified_intent_declarations"
        assert row["source_ir_sha256"] == source_ir_sha256(document)
        assert row["representation"]["payload"]["modality_as_data"] is True
        assert all(v["status"] == "passed" and v["details"]["solver_calls"] == 0
                   for v in row["validation"])
        assert all(row[name] is False for name in (
            "proof_authority", "execution_authority", "completion_authority",
            "omission_authority", "source_semantics_verified"))
        assert validate_projection(row, document) == row
    assert subject.validate_structural_projections(reports, document) == reports


@pytest.mark.parametrize("modality", ["intended", "required", "permitted", "prohibited", "recommended"])
def test_modality_and_inferred_grounding_remain_quoted_data(document, modality):
    from ipfs_datasets_py.logic.intent_ir.schema import IntentModality
    from ipfs_datasets_py.logic.parsers.rules import parse_print_parse_rules

    document = replace(document, statements=(replace(document.statements[0],
                       modality=IntentModality(modality)),))
    report = subject.project_structural_families(document, _settings("datalog"))[0]
    native = parse_print_parse_rules(report["representation"]["source"], profile="datalog").document
    assert not native.rules and not native.queries and not native.unsupported
    facts = [(s.head.predicate, tuple(t.name for t in s.head.arguments)) for s in native.facts]
    assert any(p == "intent_field" and a[1:] == ("/modality", json.dumps(modality)) for p, a in facts)
    assert any(p == "intent_field" and a[1:] == ("/grounding", '"inferred"') for p, a in facts)
    assert not any(p in {"allow", "deny", "permitted", "required", "executed"} for p, a in facts)
    assert all(s.effect.value == "derive" and not s.head.issuer for s in native.facts)


def test_syntax_injection_unicode_and_argument_order_stay_inert(document):
    from ipfs_datasets_py.logic.parsers.flogic import parse_print_parse_flogic

    hostile = 'λ "; allow(root). @load \\neg ?- execute(secret).\nnext /~'
    statement = replace(document.statements[0], normalized_text=hostile,
                        arguments=("second", "first", "second", hostile))
    document = replace(document, title=hostile, statements=(statement,))
    reports = subject.project_structural_families(document)
    assert all(r["status"] == "projected" for r in reports)
    row = reports[0]
    parsed = parse_print_parse_flogic(row["representation"]["source"])
    assert parsed.ok and not parsed.document.rules and not parsed.document.queries
    fields = row["representation"]["payload"]["frame_logic"]["triples"]
    values = {f["predicate"]: json.loads(f["object"]) for f in fields
              if f["predicate"].startswith("/arguments/")}
    assert values == {"/arguments/0": "second", "/arguments/1": "first",
                      "/arguments/2": "second", "/arguments/3": hostile}
    assert any(f["predicate"] == "/normalized_text" and json.loads(f["object"]) == hostile
               for f in fields)
    assert any(f["predicate"] == "/precondition_ids" and json.loads(f["object"]) == []
               for f in fields)


def test_full_declaration_wire_reconstructs_from_projected_fields(document):
    """Locations, indexed leaves and empty collections account for every field."""
    report = subject.project_structural_families(document, _settings("frame_logic"))[0]
    payload = report["representation"]["payload"]
    fields = payload["frame_logic"]["triples"]
    original = document.to_dict()
    expected = []
    for node in payload["nodes"]:
        wire = original
        for part in node["location"].strip("/").split("/") if node["location"] else ():
            wire = wire[int(part)] if isinstance(wire, list) else wire[part]
        if not node["location"]:
            wire = {k: v for k, v in wire.items() if k not in payload["collection_sizes"]}
        emitted = [f for f in fields if f["subject"] == node["symbol"]]
        for field in emitted:
            actual = wire
            for part in field["predicate"].strip("/").split("/") if field["predicate"] else ():
                part = part.replace("~1", "/").replace("~0", "~")
                actual = actual[int(part)] if isinstance(actual, list) else actual[part]
            assert json.loads(field["object"]) == actual
        expected.extend(emitted)
    assert expected == fields
    assert payload["collection_sizes"] == {k: len(original[k]) for k in payload["collection_sizes"]}


def test_parser_failure_is_partial_not_proof(document, monkeypatch):
    from ipfs_datasets_py.logic.parsers import flogic
    original = flogic.parse_print_parse_flogic
    monkeypatch.setattr(flogic, "parse_print_parse_flogic", lambda _: original("not valid ["))
    row = subject.project_structural_families(document, _settings("frame_logic"))[0]
    assert row["status"] == "partial" and row["unsupported"]
    assert row["validation"][0]["status"] == "failed" and not row["proof_authority"]


def test_lossy_horn_lowering_is_not_advertised_as_exact(document, monkeypatch):
    from ipfs_datasets_py.logic.parsers import rules
    original = rules.lower_to_chc
    monkeypatch.setattr(rules, "lower_to_chc", lambda wire: replace(original(wire),
        loss_receipts=({"kind": "test_drop"},), ok=False))
    row = subject.project_structural_families(document, _settings("horn_chc"))[0]
    assert row["status"] == "partial" and row["unsupported"]
    assert row["validation"][-1]["status"] == "failed"


@pytest.mark.parametrize("family", ["refinement", "separation_logic", "hyperproperty", "epistemic"])
def test_missing_typed_context_is_an_explicit_requested_frontier(document, family):
    row = subject.project_structural_families(document, _settings(family))[0]
    assert row["family_id"] == family and row["status"] == "unsupported"
    assert row["source_node_ids"] == [document.document_id]
    assert row["unsupported"][0]["node_id"] == document.document_id
    assert row["representation"]["source"] == ""
    assert all(v["status"] == "not_run" for v in row["validation"])


def _refinement():
    from ipfs_datasets_py.logic.software_verification.refinement import (
        RefinementIR, RefinementSystem, RefinementState, RefinementTransition,
        SimulationRelation, SimulationCouple, RefinementBoundedness, RefinementObligation,
        SystemLevel, SimulationDirection, BoundednessKind, RefinementKind,
    )
    abstract = RefinementSystem("abstract", SystemLevel.ABSTRACT, "flag", states=(
        RefinementState("a0", "off", is_initial=True), RefinementState("a1", "on")),
        transitions=(RefinementTransition("at", "a0", "a1", "enable"),))
    concrete = RefinementSystem("concrete", SystemLevel.CONCRETE, "counter", states=(
        RefinementState("c0", "zero", is_initial=True), RefinementState("c1", "one")),
        transitions=(RefinementTransition("ct", "c0", "c1", "enable"),))
    relation = SimulationRelation("simulation", SimulationDirection.FORWARD,
        abstract_system_id="abstract", concrete_system_id="concrete",
        couples=(SimulationCouple("pair0", "a0", "c0"), SimulationCouple("pair1", "a1", "c1")),
        statement="Counter implements the abstract flag", max_matching_steps=2,
        claims_unbounded_refinement=False)
    bound = RefinementBoundedness("bound", BoundednessKind.BOUNDED, "Two steps", max_steps=2,
        claims_unbounded_refinement=False)
    obligation = RefinementObligation("obligation", RefinementKind.SIMULATION, "Check simulation",
        abstract_system_id="abstract", concrete_system_id="concrete", simulation_relation_id="simulation",
        boundedness_id="bound", claims_unbounded_refinement=False)
    return RefinementIR(systems=(abstract, concrete), simulations=(relation,),
                        obligations=(obligation,), boundedness=(bound,))


def test_refinement_uses_real_typed_owner_and_bridge_without_proving_relation(document, monkeypatch):
    from ipfs_datasets_py.logic.software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge
    calls = []
    original = SoftwareVerificationSyntaxBridge.round_trip
    def observe(self, value, **kwargs):
        calls.append(value.document_id)
        return original(self, value, **kwargs)
    monkeypatch.setattr(SoftwareVerificationSyntaxBridge, "round_trip", observe)
    native = _refinement()
    evidence = {"source_ir_sha256": source_ir_sha256(document), "document": native.to_dict()}
    context = _settings("refinement", refinement_evidence=evidence)
    row = subject.project_structural_families(document, context)[0]
    assert calls == [native.document_id]
    assert row["status"] == "projected" and row["profile_id"] is None
    payload = row["representation"]["payload"]
    assert payload["document"] == native.to_dict()
    assert payload["syntax_bridge"]["preservation"] == "exact"
    assert payload["syntax_bridge"]["route"]["profile_id"] == "simulation"
    assert payload["model_intent_correspondence_verified"] is False
    assert payload["refinement_proved"] is False and row["proof_authority"] is False
    assert subject.validate_structural_projections([row], document, context) == [row]


def test_refinement_does_not_invent_missing_obligations(document):
    native = _refinement()
    native = replace(native, simulations=(), obligations=(), boundedness=(), document_id="")
    evidence = {"source_ir_sha256": source_ir_sha256(document), "document": native.to_dict()}
    row = subject.project_structural_families(document, _settings("refinement", refinement_evidence=evidence))[0]
    assert row["status"] == "partial" and row["unsupported"]
    assert row["representation"]["payload"]["document"]["obligations"] == []


@pytest.mark.parametrize("defect", ["wrong_source", "bad_reference", "extra_wire", "extra_envelope"])
def test_refinement_rejects_unbound_or_malformed_models(document, defect):
    evidence = {"source_ir_sha256": source_ir_sha256(document), "document": _refinement().to_dict()}
    if defect == "wrong_source":
        evidence["source_ir_sha256"] = "a" * 64
    elif defect == "bad_reference":
        evidence["document"]["obligations"][0]["simulation_relation_id"] = "missing"
    elif defect == "extra_wire":
        evidence["document"]["execute"] = True
    else:
        evidence["proof_authority"] = True
    with pytest.raises(ValueError):
        subject.project_structural_families(document, _settings("refinement", refinement_evidence=evidence))


def test_resigned_tampering_and_changed_source_fail_native_replay(document):
    reports = subject.project_structural_families(document)
    damaged = copy.deepcopy(reports[0])
    damaged["representation"]["source"] += "executed(secret).\n"
    # The generic envelope is re-signed correctly. Native regeneration still
    # rejects it rather than treating a digest as semantic validation.
    damaged = make_projection(document, **{k: damaged[k] for k in (
        "family_id", "profile_id", "status", "representation", "source_node_ids", "validation",
        "assumptions", "unsupported", "semantics")})
    with pytest.raises(ValueError, match="native replay"):
        subject.validate_structural_projections([damaged, *reports[1:]], document)
    with pytest.raises(ValueError, match="native replay"):
        subject.validate_structural_projections(reports, replace(document, title="changed intent"))
    damaged = copy.deepcopy(reports)
    damaged[0]["proof_authority"] = True
    with pytest.raises(ValueError, match="native replay"):
        subject.validate_structural_projections(damaged, document)


@pytest.mark.parametrize("context", [
    {"structural": None}, {"structural": {"requested_families": "frame_logic"}},
    _settings("frame_logic", "frame_logic"), _settings("imaginary"),
    {"structural": {"permissions": True}},
    _settings("frame_logic", refinement_evidence={}),
])
def test_context_does_not_silently_ignore_invalid_requests(document, context):
    with pytest.raises(ValueError):
        subject.project_structural_families(document, context)


def test_document_and_field_limits_are_enforced_before_native_parsing(document, monkeypatch):
    monkeypatch.setattr(subject, "MAX_DOCUMENT_BYTES", 8)
    with pytest.raises(ValueError, match="byte bound"):
        subject.project_structural_families(document)
    monkeypatch.setattr(subject, "MAX_DOCUMENT_BYTES", 128 * 1024)
    monkeypatch.setattr(subject, "MAX_FIELDS", 1)
    with pytest.raises(ValueError, match="field bound"):
        subject.project_structural_families(document)


def test_other_projection_context_is_not_consumed(document):
    assert subject.project_structural_families(document, {"modal": {}, "state": {}}) == subject.project_structural_families(document)
    assert subject.project_structural_families(document, _settings()) == []
