"""Explicit interpretations are narrow source joins, never inferred law labels."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.formalization.autoencoder import native_qualified_lean as q


def source():
    return SourceRef("source:fixture", "urn:authored:qualified", "fixture:qualified", "v1",
        hashlib.sha256(b"Authored explicit interpretation fixture.").hexdigest())


def legal_case(*, family="deontic", kind="within_duration", emergency=False):
    src = source()
    quantity = 10 if kind == "within_duration" else 20
    text = "within 10 days" if kind == "within_duration" else "for at least 20 days"
    op = {"family": family, "system": "D", "symbol": "O", "label": "obligation"}
    if family == "temporal":
        op.update(system="LTL", symbol="F" if kind == "within_duration" else "G",
                  label="eventually" if kind == "within_duration" else "always")
    formula = {"conditions": [text], "exceptions": ["emergency"] if emergency else [],
        "formula_id": "norm:one", "metadata": {}, "operator": op,
        "predicate": {"name": "submit" if kind == "within_duration" else "retain",
            "arguments": ["agency", "record"], "role": "clause"},
        "provenance": {"source_id": src.source_id, "start_char": 0, "end_char": 42, "citation": None}}
    row = {"projection_id": "legal-ir/modal-family/" + family + "/v3", "source_digest": "a" * 64,
        "logic_family": family, "profile": "modal_ir_" + family + "_structural",
        "payload": {"schema": "modal-ir-family-partition/v3", "partition": family,
            "document_id": src.source_id, "formulas": [formula]}}
    declaration = {"formula_index": 0, "original_formula_sha256": q.digest(formula),
        "kind": "bounded_temporal_qualification", "temporal": {"source_text": text,
            "temporal_kind": kind, "quantity": quantity, "unit": "day", "time_domain": "discrete_nat",
            "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True},
        "exception_scope": "activation_time_waiver", "exceptions": [{"source_text": "emergency",
            "predicate": {"name": "emergency", "arguments": []}}] if emergency else []}
    return row, evidence(row, [declaration]), src


def evidence(row, declarations):
    return {"schema": q.EVIDENCE_SCHEMA, "source_ref": source().to_dict(),
        "original_projection_id": row["projection_id"], "original_source_digest": row["source_digest"],
        "original_payload_sha256": q.digest(row["payload"]),
        "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": declarations}


def ui_case():
    src = source()
    formulas = [{"operator": op, "proposition": proposition, "strength": "strict", "source_ref_ids": [src.ref_id]}
        for op, proposition in (("obligation", "confirm(publish) before invoke(publish)"),
            ("prohibition", "invoke(publish) before confirm(publish)"), ("prohibition", "weaken_norm(publish)"))]
    row = {"projection_id": "ui_ux_ir:tdfol", "source_digest": "b" * 64, "logic_family": "tdfol",
        "profile": "ui-tdfol-compilation/v1", "payload": {"formulas": formulas}}
    declarations = []
    for index, formula in enumerate(formulas):
        item = {"formula_index": index, "original_formula_sha256": q.digest(formula), "kind": "atomic_UI_norm"}
        if index < 2:
            item.update(kind="UI_confirmation_policy", action_id="publish",
                policy="every_invocation_has_strict_prior_confirmation" if index == 0 else "unconfirmed_invocation",
                time_domain="discrete_nat", window_origin="caller_supplied_evaluation_time", strict_before=True,
                correlation="action_id_only", freshness_modeled=False, token_consumption_modeled=False,
                cancellation_modeled=False)
        declarations.append(item)
    return row, evidence(row, declarations), src


def prepare(case):
    row, value, src = case
    return q.prepare_qualified_payload(row, q.ExplicitProjectionInterpretation.from_dict(value), expected_source_ref=src)


@pytest.mark.parametrize("case", [legal_case(), legal_case(kind="minimum_duration"),
    legal_case(family="temporal"), legal_case(family="temporal", kind="minimum_duration"),
    legal_case(emergency=True), ui_case()])
def test_explicit_qualified_source_bound_roundtrip_without_authority(case):
    original = (deepcopy(case[0]), deepcopy(case[1]), case[2])
    row = prepare(case)
    code, details = q.emit_projection(row)
    assert case == original
    assert "qualifiedFormula_0" in code
    assert details["capability_floor_eligible"] is False
    assert details["source_semantics_verified"] is False
    assert details["source_text_inference_executed"] is False
    assert details["admitted"] is False
    assert row["payload"]["original"]["payload"] == case[0]["payload"]


def test_missing_explicit_evidence_does_not_change_old_before_blocker():
    row, _, _ = ui_case()
    with pytest.raises(NotImplementedError):
        q.emit_projection(row)
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_lean
    with pytest.raises(old.UnsupportedNativeLean, match="before_requires"):
        native_ui_lean.emit_projection(row)


def test_immutable_bytes_copy_safety_and_exact_source_join():
    row, value, src = legal_case()
    owned = q.ExplicitProjectionInterpretation.from_dict(value)
    original_hash = owned.sha256
    value["formulas"].clear()
    view = owned.to_dict(); view["source_ref"]["source_id"] = "changed"
    assert owned.sha256 == original_hash
    q.prepare_qualified_payload(row, owned, expected_source_ref=src)
    wrong = SourceRef(src.ref_id, src.source_uri, src.source_id, src.source_revision, "c" * 64)
    with pytest.raises(ValueError, match="source_ref_differs"):
        q.prepare_qualified_payload(row, owned, expected_source_ref=wrong)


@pytest.mark.parametrize("case", [legal_case(), ui_case()])
def test_whole_source_reference_and_native_record_references_keep_distinct_scopes(case):
    row, value, src = case
    whole_source = SourceRef("source:entire-declaration", src.source_uri, "whole-source-envelope", src.source_revision,
        src.content_sha256)
    value["source_ref"] = whole_source.to_dict()
    result = q.prepare_qualified_payload(row, q.ExplicitProjectionInterpretation.from_dict(value), expected_source_ref=whole_source)
    code, _ = q.emit_projection(result)
    assert result["payload"]["original"]["payload"] == row["payload"]
    assert "originalFormulaProvenance_0" in code


def test_inconsistent_native_document_and_formula_source_fail_closed():
    case = legal_case()
    case[0]["payload"]["formulas"][0]["provenance"]["source_id"] = "unrelated-native-document"
    case[1]["original_payload_sha256"] = q.digest(case[0]["payload"])
    case[1]["formulas"][0]["original_formula_sha256"] = q.digest(case[0]["payload"]["formulas"][0])
    with pytest.raises(ValueError, match="formula_source_differs"):
        prepare(case)


def test_nested_unknown_fields_and_uninterpreted_metadata_rejected():
    case = legal_case()
    case[1]["formulas"][0]["temporal"]["business_days"] = True
    with pytest.raises(ValueError, match="closed_temporal"):
        prepare(case)
    case = legal_case()
    case[0]["payload"]["formulas"][0]["metadata"]["another_scope"] = "unknown"
    case[1]["original_payload_sha256"] = q.digest(case[0]["payload"])
    case[1]["formulas"][0]["original_formula_sha256"] = q.digest(case[0]["payload"]["formulas"][0])
    with pytest.raises(ValueError, match="uninterpreted_ModalIR_metadata"):
        prepare(case)


@pytest.mark.parametrize("field,value", [("quantity", 20), ("quantity", True), ("quantity", 0),
    ("unit", "hour"), ("temporal_kind", "minimum_duration"), ("origin", "inferred_contract_signing"),
    ("time_domain", "wall_clock"), ("lower_inclusive", False), ("upper_inclusive", False)])
def test_deadline_cannot_be_reinterpreted_as_another_literal_or_implicit_clock(field, value):
    case = legal_case()
    case[1]["formulas"][0]["temporal"][field] = value
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("mutation", ["missing", "extra", "formula_hash", "source_hash", "projection_id", "unknown_field"])
def test_exhaustive_ordered_binding_fails_closed(mutation):
    row, value, src = ui_case()
    if mutation == "missing": value["formulas"].pop()
    elif mutation == "extra": value["formulas"].append(deepcopy(value["formulas"][0]))
    elif mutation == "formula_hash": value["formulas"][0]["original_formula_sha256"] = "c" * 64
    elif mutation == "source_hash": value["original_source_digest"] = "c" * 64
    elif mutation == "projection_id": value["original_projection_id"] += ":other"
    else: value["unknown"] = True
    with pytest.raises(ValueError):
        prepare((row, value, src))


def test_qualifiers_cannot_be_dropped_even_with_fresh_digest():
    case = legal_case(emergency=True)
    case[1]["formulas"][0]["exceptions"] = []
    with pytest.raises(ValueError, match="exhaustive_exception"):
        prepare(case)
    case = legal_case()
    case[0]["payload"]["formulas"][0]["conditions"].append("if requested")
    case[1]["original_payload_sha256"] = q.digest(case[0]["payload"])
    case[1]["formulas"][0]["original_formula_sha256"] = q.digest(case[0]["payload"]["formulas"][0])
    with pytest.raises(ValueError, match="condition_coverage"):
        prepare(case)


@pytest.mark.parametrize("field,value", [("freshness_modeled", True), ("token_consumption_modeled", True),
    ("cancellation_modeled", True), ("strict_before", False), ("correlation", "request_nonce"),
    ("policy", "existential_confirmation"), ("action_id", "other")])
def test_UI_does_not_invent_richer_authorization_or_change_action(field, value):
    case = ui_case(); case[1]["formulas"][0][field] = value
    with pytest.raises(ValueError):
        prepare(case)


def test_rehashing_tampered_payload_does_not_override_typed_interpretation():
    row = prepare(legal_case())
    row["payload"]["interpretation"]["formulas"][0]["temporal"]["quantity"] = 20
    row["payload"]["interpretation_sha256"] = q.digest(row["payload"]["interpretation"])
    with pytest.raises(ValueError, match="literal_kind_quantity"):
        q.emit_projection(row)


def test_qualified_interpretation_Lean_semantics_on_declared_toy_clock(tmp_path):
    lake = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not lake:
        pytest.skip("set explicit local Lake path for native build")
    blocks = [old.PRELUDE, '''
def toy (p : String → Nat → Prop) : Interpretation Unit Unit where
  agent := fun _ => ()
  cognitive := fun _ _ body => body
  constant := fun _ => ()
  function := fun _ _ => ()
  atom := fun name _ t => p name t
  modal := fun _ _ _ body => body
  frame := fun _ _ _ => False
  frameScalar := fun _ _ => ()
  member := fun _ _ => False
  subclass := fun _ _ => False
''']
    cases = [("Deadline", legal_case()), ("Minimum", legal_case(kind="minimum_duration")),
        ("Emergency", legal_case(emergency=True)), ("UI", ui_case())]
    for name, case in cases:
        blocks.extend(["namespace " + name, q.emit_projection(prepare(case))[0], "end " + name])
    blocks.append('''
-- These are clock/operator checks under an expressly transparent toy modal
-- interpretation. They do not prove an actual legal or UI obligation.
example : Deadline.qualifiedFormula_0 (toy (fun _ t => t = 10)) 0 := by
  exact ⟨10, by decide, by decide, rfl⟩
example : ¬ Deadline.qualifiedFormula_0 (toy (fun _ t => t = 11)) 0 := by
  rintro ⟨u, _, upper, rfl⟩
  exact (by decide : ¬ (11 ≤ 0 + 10)) upper
example : ¬ Minimum.qualifiedFormula_0 (toy (fun _ t => t < 20)) 0 := by
  intro h
  exact (by decide : ¬ (20 < 20)) (h 20 (by decide) (by decide))
example : Minimum.qualifiedFormula_0 (toy (fun _ t => t ≤ 20)) 0 := by
  intro u _ upper
  exact upper
example : Emergency.qualifiedFormula_0 (toy (fun name _ => name = "emergency")) 0 := by
  intro noEmergency
  exact False.elim (noEmergency rfl)
example : UI.qualifiedFormula_0 (toy (fun name t =>
    (name = "confirm" ∧ t = 5) ∨ (name = "invoke" ∧ t = 6))) 0 := by
  intro u _ occurrence
  have hu : u = 6 := by simpa [toy] using occurrence
  subst u
  exact ⟨5, by decide, by decide, Or.inl ⟨rfl, rfl⟩⟩
example : ¬ UI.qualifiedFormula_0 (toy (fun name t =>
    (name = "confirm" ∨ name = "invoke") ∧ t = 6)) 0 := by
  intro h
  obtain ⟨v, _, before, confirm⟩ := h 6 (by decide) ⟨Or.inr rfl, rfl⟩
  have hv : v = 6 := confirm.2
  subst v
  exact (by decide : ¬ (6 < 6)) before
''')
    (tmp_path / "lakefile.toml").write_text('name = "QualifiedNative"\nversion = "0.1.0"\n[[lean_lib]]\nname = "QualifiedNative"\n')
    (tmp_path / "QualifiedNative.lean").write_text("\n".join(blocks))
    result = subprocess.run([str(Path(lake).resolve()), "build", "QualifiedNative"], cwd=tmp_path,
        text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
