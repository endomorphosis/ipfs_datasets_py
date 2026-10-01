"""The public context bridge retains candidates and executes native projectors."""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import projection_inputs as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as native
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from tests.fixtures.logic.source_reconstruction_v3 import rows
from tests.unit.logic.security_ir import test_code_logic_projection as code_models
from tests.unit.logic.formalization.autoencoder import test_native_intent_guarded_lean as guarded_fixture
from tests.unit.logic.formalization.autoencoder.test_family_training_v2 import policy


def sample(domain):
    return deepcopy(rows(domain, "train")[0])


def unit_for(text):
    cid = canonical_identity({"fixture": "explicit fixed polarity, authored context"},
        domain="authored-test", schema_version="v1").cid
    body = canonical_identity({"body": text}, domain="cvefixes-security-ir/code-body",
        schema_version="cvefixes-code-body/v1").cid
    return CodeUnit(source_cids=(cid,), parent_cids=(cid,), config_cid=cid,
        unit_kind="function", language="Python", path="fixture.py", polarity="fixed",
        payload={"body_sha256": hashlib.sha256(text.encode()).hexdigest(), "body_cid": body})


def prepare(domain, row, inputs=None):
    context = None if inputs is None else bind_context(domain, row["target"], row["source_text"], inputs)
    return api.prepare_source_inputs(domain, row["target"], row["source_text"], context=context)


def test_rich_intent_without_context_reuses_native_grammar_and_preserves_candidate():
    row = sample("intent_ir"); saved = deepcopy(row)
    source = prepare("intent_ir", row)
    report = native.prepare_family_training_targets_v7("intent_ir", **source)
    assert row == saved and source["document"] == row["target"]["document"]
    assert {p["logic_family"] for p in report["projections"]} >= {"dcec", "tdfol", "higher_order", "deontic"}
    assert not report["source_semantics_verified"]


def test_rich_prediction_cannot_be_replaced_by_context():
    row = sample("intent_ir")
    row["target"]["document"]["action"] = "erase"
    with pytest.raises(ValueError, match="differs from exact source"):
        prepare("intent_ir", row, {})


def test_rich_and_native_context_namespaces_cannot_be_conflated():
    row = sample("intent_ir")
    with pytest.raises(ValueError, match="distinct and exclusive"):
        prepare("intent_ir", row, {"rich_slot_context": {}, "projection_context": {}})
    with pytest.raises(ValueError, match="unknown Intent"):
        prepare("intent_ir", row, {"context": {}})


def test_explicit_intent_temporal_context_reaches_native_modal_owners():
    row = sample("intent_ir")
    source = prepare("intent_ir", row, {"projection_context": {"modal": {
        "temporal_bindings": [{"statement_id": "goal:0", "operator": "eventually", "evidence_ref": "source"}]}}})
    report = native.prepare_family_training_targets_v7("intent_ir", requested_families=["dcec", "tdfol"], **source)
    assert source["document"].document_id
    dcec = next(p for p in report["projections"] if p["logic_family"] == "dcec")
    assert dcec["payload"]["payload"]["formulas"][0]["temporal_scope"]["operator"] == "eventually"


def guarded_row():
    document, context, effects = guarded_fixture.fixture()
    text = "Authored procedure: publish only when ready; all declared outcomes complete the report."
    source = replace(document.sources[0], content_sha256=hashlib.sha256(text.encode()).hexdigest())
    document = replace(document, sources=(source,))
    document, context, effects = guarded_fixture.rebind(document, context, effects)
    return {"target": document.to_dict(), "source_text": text}, {
        "projection_context": context, "guarded_effect_bindings": effects}


def test_guarded_intent_closes_state_workflow_and_effect_contract_gap():
    row, inputs = guarded_row()
    source = prepare("intent_ir", row, inputs)
    report = native.prepare_family_training_targets_v7("intent_ir",
        requested_families=["program", "temporal", "transition_system"], **source)
    projections = [p for p in report["projections"] if p["projection_id"].startswith("intent_ir/guarded/")]
    assert len(projections) == 4 and all(p["ready_for_training"] for p in projections)
    assert all(p["payload"]["effect_checks"][0]["passed"] for p in projections)
    assert not report["source_semantics_verified"]


def test_false_guarded_effect_remains_a_counterexample():
    row, inputs = guarded_row()
    inputs["projection_context"]["state"]["workflow"]["action_updates"][0]["outcomes"][0]["values"]["complete"] = False
    report = native.prepare_family_training_targets_v7("intent_ir",
        requested_families=["program", "temporal", "transition_system"], **prepare("intent_ir", row, inputs))
    projections = [p for p in report["projections"] if p["projection_id"].startswith("intent_ir/guarded/")]
    assert len(projections) == 4 and all(not p["ready_for_training"] for p in projections)
    assert not projections[0]["payload"]["effect_checks"][0]["passed"]


def test_guarded_source_hash_cannot_borrow_another_instruction():
    row, inputs = guarded_row()
    row["source_text"] += " Changed."
    with pytest.raises(ValueError, match="source hash differs"):
        prepare("intent_ir", row, inputs)


def security_inputs(row):
    unit = unit_for(row["source_text"])
    source = api.security_source_ref(unit, row["source_text"])
    evidence = code_models.evidence(source)
    selected = []
    from ipfs_datasets_py.logic.security_ir.code_logic_projection import _kind
    for item in evidence:
        kind = _kind(item.document)
        if kind not in {"program", "contract"}:
            document = item.document
            if kind == "transition":
                document = replace(document, document_id="", predicates=tuple(p for p in document.predicates if p.predicate_id != "pred:safe"))
            selected.append({"kind": kind, "document": document.to_dict()})
    return {"code_unit": unit.to_dict(), "typed_inputs": selected,
        "supplemental_inputs": [{"kind": "authorization", "document": policy(source).to_dict()}]}


def test_security_broad_projection_requires_explicit_polarity_and_body_record():
    row = sample("security_ir")
    with pytest.raises(ValueError, match="explicit CodeUnit"):
        prepare("security_ir", row)


def test_security_context_runs_existing_program_tla_temporal_heap_and_policy_owners():
    row = sample("security_ir"); inputs = security_inputs(row)
    original = deepcopy(row); declared = deepcopy(inputs)
    source = prepare("security_ir", row, inputs)
    report = native.prepare_family_training_targets_v7("security_ir", **source)
    ready = {p["logic_family"] for p in report["projections"] if p["ready_for_training"]}
    assert {"program", "transition_system", "temporal", "separation_logic", "hyperproperty", "authorization"} <= ready
    assert any(p["profile"] == "tla_plus" for p in report["projections"])
    assert row == original and inputs == declared
    program = source["typed_inputs"][0].document
    assert program.sources[0].ref_id == source["code_unit"].cid
    assert program.metadata["distributed_candidate_source_join"]["polarity_inferred"] is False
    assert not report["source_semantics_verified"]


def test_security_wrong_prediction_cannot_use_correct_context_as_repair():
    row = sample("security_ir"); inputs = security_inputs(row)
    row["target"]["document"]["operator"] = ">"
    with pytest.raises(ValueError, match="candidate source binding failed"):
        prepare("security_ir", row, inputs)


def test_security_supplied_program_cannot_replace_the_checked_candidate():
    row = sample("security_ir"); inputs = security_inputs(row)
    source = api.security_source_ref(inputs["code_unit"], row["source_text"])
    inputs["typed_inputs"].append({"kind": "program", "document": code_models.program(source).to_dict()})
    with pytest.raises(ValueError, match="cannot replace"):
        prepare("security_ir", row, inputs)


def test_security_foreign_model_source_is_rejected_before_projection():
    row = sample("security_ir"); inputs = security_inputs(row)
    inputs["typed_inputs"][0]["document"]["predicates"][0]["source_ref_ids"] = ["foreign"]
    with pytest.raises(ValueError):
        prepare("security_ir", row, inputs)


def test_security_body_mutation_cannot_reuse_a_codeunit():
    row = sample("security_ir"); inputs = security_inputs(row)
    row["source_text"] += "\n"
    with pytest.raises(ValueError, match="SHA differs"):
        prepare("security_ir", row, inputs)


def test_security_context_class_names_are_not_executable():
    row = sample("security_ir"); inputs = security_inputs(row)
    inputs["supplemental_inputs"] = [{"kind": "os.system", "document": {}}]
    with pytest.raises(ValueError, match="applicable native model"):
        prepare("security_ir", row, inputs)


def test_explicit_formulas_reach_real_family_parsers_without_becoming_source_truth():
    row = sample("intent_ir")
    inputs = {"formula_inputs": [
        {"requirement_id": "FOL", "formula": "forall x. Person(x) -> Reports(x)"},
        {"requirement_id": "DCEC", "formula": "O(K(Officer,Happens(Submit,Time)))"}]}
    report = native.prepare_family_training_targets_v7("intent_ir", **prepare("intent_ir", row, inputs))
    values = [p for p in report["projections"] if "/native_formula/" in p["projection_id"]]
    assert len(values) == 2 and all(p["ready_for_training"] for p in values)
    assert not report["source_text_to_native_formula_inference"]


@pytest.mark.parametrize("field", ["source_sha256", "candidate_sha256", "domain_id", "context_sha256", "qualified"])
def test_stale_or_authority_forged_context_fails(field):
    row = sample("intent_ir")
    context = bind_context("intent_ir", row["target"], row["source_text"], {})
    context[field] = True if field == "qualified" else "wrong"
    with pytest.raises(ValueError, match="context"):
        api.prepare_source_inputs("intent_ir", row["target"], row["source_text"], context=context)


def test_unknown_model_fields_cannot_be_silently_dropped():
    row = sample("security_ir"); inputs = security_inputs(row)
    inputs["typed_inputs"][0]["document"]["ignored_malicious_field"] = True
    with pytest.raises(ValueError):
        prepare("security_ir", row, inputs)


def test_full_security_candidate_preserves_declaration_and_requires_matching_source():
    from ipfs_datasets_py.logic.security_ir.model import SecurityIR, SecuritySource
    row = sample("security_ir"); inputs = security_inputs(row)
    row["target"] = SecurityIR("security:explicit-model", sources=(SecuritySource(
        "code", "urn:authored:explicit-code", content_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest()),)).to_dict()
    saved = deepcopy(row["target"])
    source = prepare("security_ir", row, inputs)
    report = native.prepare_family_training_targets_v7("security_ir", **source)
    assert row["target"] == saved and source["code_unit"].to_dict() == inputs["code_unit"]
    assert report["ready_for_training"] and not report["source_semantics_verified"]
    row["target"]["sources"][0]["content_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="exact code source hash"):
        prepare("security_ir", row, inputs)


def test_duplicate_native_models_and_formula_requirements_are_rejected():
    row = sample("security_ir"); inputs = security_inputs(row)
    inputs["typed_inputs"].append(deepcopy(inputs["typed_inputs"][0]))
    with pytest.raises(ValueError, match="unique"):
        prepare("security_ir", row, inputs)
    row = sample("intent_ir")
    formula = {"requirement_id": "FOL", "formula": "Person(Alice)"}
    with pytest.raises(ValueError, match="duplicate native formula"):
        prepare("intent_ir", row, {"formula_inputs": [formula, deepcopy(formula)]})
