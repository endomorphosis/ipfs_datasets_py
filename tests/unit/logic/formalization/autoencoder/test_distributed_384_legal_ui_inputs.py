"""Candidate-preserving joins exercise real native parser/model owners."""
from copy import deepcopy
from dataclasses import fields
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import legal_ui_inputs as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as family
from ipfs_datasets_py.logic.formalization.autoencoder.ui_training_inputs import prepare_ui_training_row
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIComponent
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.authored_semantic_projection_panel import FORMULAS
from tests.fixtures.logic.source_reconstruction_v3 import rows
from tests.unit.logic.formalization.autoencoder.test_ui_training_inputs import native_row
from tests.unit.logic.formalization.autoencoder.test_family_training_v2 import policy
from tests.unit.logic.formalization.autoencoder.test_family_training_v7 import declaration


def sample(domain):
    row = rows(domain, "train")[0]
    return deepcopy(row["target"]), row["source_text"]


def ui_sample():
    row = native_row()
    row["behavior"]["transitions"][0].pop("timeout_ms")
    component = prepare_ui_training_row(row).document.component_graph.components[0]
    target = {"kind": "ui_component", "document": UIComponent(**{
        field.name: getattr(component, field.name) for field in fields(UIComponent)}).to_dict()}
    return target, "Authored declaration: the delete button requests confirmed deletion.", row


def prepare(domain, target, text, inputs=None):
    context = None if inputs is None else bind_context(domain, target, text, inputs)
    return api.prepare_source_inputs(domain, target, text, context=context)


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
def test_no_context_retains_only_actual_candidate_projection(domain):
    target, text = sample(domain)
    original = deepcopy(target)
    source = prepare(domain, target, text)
    report = family.prepare_family_training_targets_v7(domain, **source)
    assert target == original
    expected = "deontic" if domain == "legal_ir" else "frame_logic"
    assert {p["logic_family"] for p in report["projections"]} == {expected}
    assert report["source_text_to_native_formula_inference"] is False
    assert report["structural_readiness_is_qualification"] is False
    if domain == "legal_ir":
        assert source["document"].to_dict() == target


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
def test_eight_native_formula_fragments_reach_real_parser_and_keep_source(domain):
    target, text = sample(domain)
    inputs = {"formula_inputs": [{"requirement_id": key, "formula": value} for key, value in FORMULAS.items()]}
    source = prepare(domain, target, text, inputs)
    report = family.prepare_family_training_targets_v7(domain, **source)
    formulas = [p for p in report["projections"] if "/native_formula/" in p["projection_id"]]
    assert len(formulas) == 8
    assert {p["logic_family"] for p in formulas} == {"first_order", "deontic", "temporal", "tdfol",
        "event_calculus", "dcec", "frame_logic", "propositional"}
    assert all(p["ready_for_training"] for p in formulas)
    assert all(item.source_ref.content_sha256 == hashlib.sha256(text.encode()).hexdigest()
               for item in source["formula_inputs"])
    family.validate_family_training_report_v7(report, **source)
    assert inputs["formula_inputs"][0] == {"requirement_id": "FOL", "formula": FORMULAS["FOL"]}


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
@pytest.mark.parametrize("part", ["candidate", "source", "domain", "authority"])
def test_context_cannot_be_rebound_or_promoted(domain, part):
    target, text = sample(domain)
    context = bind_context(domain, target, text, {})
    if part == "candidate":
        context["candidate_sha256"] = "0" * 64
    elif part == "source":
        text += " changed"
    elif part == "domain":
        context["domain_id"] = "intent_ir"
    else:
        context["qualified"] = True
    with pytest.raises(ValueError, match="differs"):
        api.prepare_source_inputs(domain, target, text, context=context)


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
@pytest.mark.parametrize("bad", [
    {"document": {}}, {"source_text": "replacement"}, {"requested_families": ["deontic"]},
    {"formula_inputs": [{"requirement_id": "FOL", "formula": "P(x)", "source_ref": {}}]},
    {"formula_inputs": [{"requirement_id": "DFOL", "formula": "Reports(x)"}]},
    {"formula_inputs": [{"requirement_id": "FOL", "formula": "P(x)"}] * 2},
    {"supplemental_inputs": [{"kind": "__import__", "document": {}}]},
    {"supplemental_inputs": [{"kind": "authorization", "document": {}, "class": "arbitrary"}]},
])
def test_unknown_or_mislabelled_context_never_substitutes_native_candidate(domain, bad):
    target, text = sample(domain)
    with pytest.raises((ValueError, TypeError)):
        prepare(domain, target, text, bad)


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
def test_authorization_native_owner_requires_exact_source_reference(domain):
    target, text = sample(domain)
    base = prepare(domain, target, text)
    reference = family.supplemental_source_ref(domain, **base)
    document = policy(reference).to_dict()
    context = {"supplemental_inputs": [{"kind": "authorization", "document": document}]}
    source = prepare(domain, target, text, context)
    report = family.prepare_family_training_targets_v7(domain, **source)
    assert any(p["logic_family"] == "authorization" and p["ready_for_training"] for p in report["projections"])
    changed = deepcopy(context)
    changed["supplemental_inputs"][0]["document"]["sources"][0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepare(domain, target, text, changed)
    changed = deepcopy(context)
    changed["supplemental_inputs"][0]["document"]["ignored"] = True
    with pytest.raises(ValueError):
        prepare(domain, target, text, changed)


def test_matched_ui_context_reuses_native_behavior_event_temporal_and_state_views():
    target, text, row = ui_sample()
    source = prepare("ui_ux_ir", target, text, {"ui_training_row": row})
    report = family.prepare_family_training_targets_v7("ui_ux_ir", **source)
    families = {p["logic_family"] for p in report["projections"]}
    assert {"frame_logic", "event_calculus", "tdfol", "dcec", "transition_system", "temporal"} <= families
    assert any(p["profile"] == "tla_plus" for p in report["projections"])
    expected = prepare_ui_training_row(row).document
    assert source["document"] == expected
    row["dom_aria"]["title"] = "changed"
    assert source["document"] == expected


@pytest.mark.parametrize("part", ["role", "source_ref_ids", "program_binding_ids", "purpose"])
def test_ui_identity_alone_does_not_allow_different_candidate_semantics(part):
    target, text, row = ui_sample()
    target["document"][part] = [] if part.endswith("_ids") else ("textbox" if part == "role" else "Different purpose")
    with pytest.raises(ValueError, match="differs from exact decoded candidate"):
        prepare("ui_ux_ir", target, text, {"ui_training_row": row})


def test_unrelated_ui_row_cannot_supply_missing_candidate_context():
    target, text = sample("ui_ux_ir")
    with pytest.raises(ValueError, match="unique candidate component"):
        prepare("ui_ux_ir", target, text, {"ui_training_row": native_row()})


def test_request_correlated_ui_confirmation_uses_existing_qualified_native_lowering():
    target, text, row = ui_sample()
    source = prepare("ui_ux_ir", target, text, {"ui_training_row": row})
    original = family.previous.prepare_family_training_targets_v6("ui_ux_ir", **source)
    reference = family.supplemental_source_ref("ui_ux_ir", **source)
    formula = next(p for p in original["projections"] if p["projection_id"] == "ui_ux_ir:tdfol")
    value = declaration("ui_ux_ir", formula, reference).to_dict()
    context = {"ui_training_row": row, "ui_confirmation_inputs": [value]}
    joined = prepare("ui_ux_ir", target, text, context)
    report = family.prepare_family_training_targets_v7("ui_ux_ir", **joined)
    assert report["ui_confirmation_inputs"] == [value]
    assert len(report["superseded_v7_qualifier_observations"]) == 1
    assert report["superseded_v7_qualifier_observations"][0]["projection_id"] == "ui_ux_ir:tdfol"
    family.validate_family_training_report_v7(report, **joined)
    changed = deepcopy(context)
    changed["ui_confirmation_inputs"][0]["source_ref"]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source differs"):
        prepare("ui_ux_ir", target, text, changed)


def test_legal_opaque_qualifiers_cannot_be_replaced_by_unrelated_modal_document():
    target, text = sample("legal_ir")
    with pytest.raises(ValueError, match="closed legal_ir"):
        prepare("legal_ir", target, text, {"legal_qualifier_inputs": []})
