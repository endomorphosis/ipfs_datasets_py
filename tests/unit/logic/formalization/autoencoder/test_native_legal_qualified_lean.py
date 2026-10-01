"""Legal qualifiers keep exact source joins and distinguish exception scopes."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.formalization.autoencoder import native_legal_qualified_lean as q


def atom(name, *args):
    return {"op": "atom", "predicate": {"name": name, "arguments": list(args)}}


def legal_case(*, family="deontic", kind="within_duration", scope="activation_time_waiver",
               guarded=True, emergency=True, operator=None):
    text = "Authored explicit conditional Legal interpretation fixture."
    source = SourceRef("source:fixture", "urn:authored:legal-qualified", "fixture:qualified", "v1",
        hashlib.sha256(text.encode()).hexdigest())
    conditions = ["if requested"] if guarded else []
    declarations = [{"source_index": 0, "source_text": "if requested", "expression": atom("requested")}] if guarded else []
    temporal = None
    if kind:
        literal = "within 10 days" if kind == "within_duration" else "for at least 20 days"
        temporal = {"source_index": len(conditions), "source_text": literal, "temporal_kind": kind,
            "quantity": 10 if kind == "within_duration" else 20, "unit": "day", "time_domain": "discrete_nat",
            "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True}
        conditions.append(literal)
    op = {"family": family, "system": "D", "symbol": "O", "label": "obligation"}
    if family == "temporal":
        op.update(system="LTL", symbol="F" if kind == "within_duration" else "G",
                  label="eventually" if kind == "within_duration" else "always")
    if operator:
        op.update(symbol=operator, label={"O":"obligation", "P":"permission", "F":"prohibition"}[operator])
    formula = {"conditions": conditions, "exceptions": ["emergency"] if emergency else [], "formula_id": "norm:one",
        "metadata": {}, "operator": op,
        "predicate": {"name": "submit" if kind == "within_duration" else "retain", "arguments": ["agency", "record"], "role": "clause"},
        "provenance": {"source_id": source.source_id, "start_char": 0, "end_char": len(text), "citation": None}}
    row = {"projection_id": "legal-ir/modal-family/"+family+"/v3", "source_digest": "a"*64,
        "logic_family": family, "profile": "modal_ir_"+family+"_structural",
        "payload": {"schema":"modal-ir-family-partition/v3", "document_id":source.source_id, "partition":family,"formulas":[formula]}}
    value = {"schema":q.EVIDENCE_SCHEMA,"source_ref":source.to_dict(),"original_projection_id":row["projection_id"],
        "original_source_digest":row["source_digest"],"original_payload_sha256":q.digest(row["payload"]),
        "declaration_scope":"caller_supplied_interpretation_not_source_translation", "formulas":[{
            "formula_index":0,"original_formula_sha256":q.digest(formula),"kind":"activation_guarded_legal_rule",
            "activation_scope":"all_conditions_at_evaluation_origin", "conditions":declarations, "temporal":temporal,
            "exception_scope":scope, "exceptions":[{"source_index":0,"source_text":"emergency","expression":atom("emergency")}] if emergency else []}]}
    return row, value, source


def rehash(case):
    row, value, _ = case
    value["original_payload_sha256"] = q.digest(row["payload"])
    for formula, declaration in zip(row["payload"]["formulas"],value["formulas"]):
        declaration["original_formula_sha256"] = q.digest(formula)
    return case


def prepare(case):
    row, value, source = case
    return q.prepare_qualified_payload(row, q.LegalQualifierInterpretation.from_dict(value), expected_source_ref=source)


@pytest.mark.parametrize("family,kind,scope,guarded,emergency", [
    ("deontic", None, "activation_time_waiver", True, True),
    ("deontic", None, "activation_time_waiver", False, True),
    ("deontic", "within_duration", "activation_time_waiver", True, True),
    ("temporal", "within_duration", "activation_time_waiver", True, True),
    ("deontic", "minimum_duration", "per_tick_exemption", True, True),
    ("temporal", "minimum_duration", "per_tick_exemption", True, True),
])
def test_broader_qualifiers_preserve_originals_and_no_authority(family,kind,scope,guarded,emergency):
    case = legal_case(family=family,kind=kind,scope=scope,guarded=guarded,emergency=emergency)
    before = (deepcopy(case[0]), deepcopy(case[1]), case[2])
    result = prepare(case)
    code, details = q.emit_projection(result)
    assert case == before
    assert result["payload"]["original"]["payload"] == case[0]["payload"]
    assert "qualifiedLegalFormula_0" in code
    for key in ("capability_floor_eligible", "source_semantics_verified", "source_text_inference_executed", "admitted"):
        assert details[key] is False


@pytest.mark.parametrize("operator", ["O", "P", "F"])
def test_deontic_operator_is_preserved(operator):
    code, _ = q.emit_projection(prepare(legal_case(kind=None,operator=operator)))
    assert '"deontic:'+operator+'"' in code


def test_compound_activation_and_exception_expressions_are_retained():
    case = legal_case()
    compound = {"op":"all", "operands":[atom("requested"),{"op":"not","operand":atom("withdrawn")},
        {"op":"any","operands":[atom("authorized"),atom("urgent")]}]}
    case[1]["formulas"][0]["conditions"][0]["expression"] = compound
    row = prepare(case)
    code, _ = q.emit_projection(row)
    assert "∧" in code and "∨" in code and "¬" in code
    assert row["payload"]["interpretation"]["formulas"][0]["conditions"][0]["expression"] == compound


def test_immutable_copy_safe_and_whole_source_join():
    row,value,source = legal_case()
    evidence = q.LegalQualifierInterpretation.from_dict(value)
    original_sha = evidence.sha256
    value["formulas"].clear(); evidence.to_dict()["source_ref"]["source_id"] = "changed"
    assert evidence.sha256 == original_sha
    q.prepare_qualified_payload(row,evidence,expected_source_ref=source)
    foreign = SourceRef(source.ref_id,source.source_uri,source.source_id,source.source_revision,"b"*64)
    with pytest.raises(ValueError,match="source_ref_differs"):
        q.prepare_qualified_payload(row,evidence,expected_source_ref=foreign)


@pytest.mark.parametrize("mutation", ["missing_condition", "missing_exception", "duplicate_condition", "condition_order",
    "temporal_overlap", "unknown_field", "wrong_hash", "wrong_source", "metadata", "wrong_native_family",
    "wrong_symbol", "same_literal_conflict"])
def test_complete_qualifier_coverage_and_exact_native_bindings(mutation):
    case = legal_case()
    formula = case[0]["payload"]["formulas"][0]; declaration = case[1]["formulas"][0]
    if mutation == "missing_condition": declaration["conditions"] = []
    elif mutation == "missing_exception": declaration["exceptions"] = []
    elif mutation == "duplicate_condition": declaration["conditions"] *= 2
    elif mutation == "condition_order": declaration["conditions"][0]["source_index"] = 1
    elif mutation == "temporal_overlap": declaration["temporal"]["source_index"] = 0
    elif mutation == "unknown_field": declaration["conditions"][0]["inferred"] = True
    elif mutation == "wrong_hash": declaration["original_formula_sha256"] = "b"*64
    elif mutation == "wrong_source": formula["provenance"]["source_id"] = "foreign"; rehash(case)
    elif mutation == "metadata": formula["metadata"] = {"silent_scope":"unknown"}; rehash(case)
    elif mutation == "wrong_native_family": formula["operator"]["family"] = "temporal"; rehash(case)
    elif mutation == "wrong_symbol": formula["operator"]["label"] = "permission"; rehash(case)
    else:
        formula["exceptions"] = ["if requested"]
        declaration["exceptions"][0]["source_text"] = "if requested"
        rehash(case)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("kind,emergency", [("within_duration",True),(None,True),("minimum_duration",False)])
def test_per_tick_exemption_never_means_deadline_extension_or_unbounded_suspension(kind,emergency):
    with pytest.raises(ValueError,match="per_tick_exemption_requires"):
        prepare(legal_case(kind=kind,scope="per_tick_exemption",emergency=emergency))


@pytest.mark.parametrize("field,value", [("quantity",True),("quantity",0),("unit","business_day"),
    ("time_domain","real_clock"),("origin","execution_trace"),("upper_inclusive",False),("source_index",True)])
def test_clock_and_exact_duration_are_explicit(field,value):
    case = legal_case(); case[1]["formulas"][0]["temporal"][field] = value
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize("expression", [{"op":"all","operands":[]},{"op":"true"},
    {"op":"atom","predicate":{"name":"p","arguments":[],"truth":True}},
    {"op":"not","operand":{"op":"execute","code":"anything"}}])
def test_opaque_or_vacuous_expression_syntax_rejected(expression):
    case = legal_case();case[1]["formulas"][0]["conditions"][0]["expression"] = expression
    with pytest.raises(ValueError): prepare(case)


def test_expression_depth_is_bounded():
    expression = atom("p")
    for _ in range(10): expression={"op":"not","operand":expression}
    case=legal_case();case[1]["formulas"][0]["conditions"][0]["expression"]=expression
    with pytest.raises(ValueError,match="bounded_typed"):prepare(case)


def test_original_opaque_projection_does_not_silently_gain_semantics():
    row,_,_=legal_case()
    with pytest.raises(NotImplementedError):q.emit_projection(row)
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters_v4 import emit_projection
    with pytest.raises(ValueError): emit_projection(row)


def test_duration_literal_cannot_be_hidden_as_an_activation_atom():
    case=legal_case(guarded=False,emergency=False)
    case[1]["formulas"][0]["temporal"]=None
    case[1]["formulas"][0]["conditions"]=[{"source_index":0,"source_text":"within 10 days","expression":atom("deadline")}]
    with pytest.raises(ValueError,match="duration_literal_cannot"):
        prepare(case)


def test_tampered_rehashed_interpretation_cannot_change_original_literal():
    row=prepare(legal_case());row["payload"]["interpretation"]["formulas"][0]["temporal"]["quantity"]=99
    row["payload"]["interpretation_sha256"] = q.digest(row["payload"]["interpretation"])
    with pytest.raises(ValueError,match="temporal_literal"):q.emit_projection(row)


def test_new_payload_cannot_claim_admission_or_floor():
    row=prepare(legal_case());row["payload"]["admitted"]=True
    with pytest.raises(ValueError,match="cannot_assert"):q.emit_projection(row)


TOY = '''
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
'''


def lean_source():
    blocks = [old.PRELUDE, TOY]
    for name,case in [("Deadline",legal_case(emergency=False)),("Instant",legal_case(kind=None,emergency=False)),
        ("Waiver",legal_case(kind="minimum_duration",guarded=False)),
        ("Tick",legal_case(kind="minimum_duration",guarded=False,scope="per_tick_exemption"))]:
        blocks.extend(["namespace "+name,q.emit_projection(prepare(case))[0],"end "+name])
    compound=legal_case(kind=None,emergency=False)
    compound[1]["formulas"][0]["conditions"][0]["expression"]={"op":"all","operands":[atom("requested"),
        {"op":"not","operand":atom("withdrawn")},{"op":"any","operands":[atom("authorized"),atom("urgent")]}]}
    blocks.extend(["namespace Compound",q.emit_projection(prepare(compound))[0],"end Compound"])
    blocks.append('''
-- These are semantic scope checks under a transparent toy modal interpretation.
-- They assert no law, corpus translation, event or real-world compliance.
example : Deadline.qualifiedLegalFormula_0 (toy (fun name t => name = "requested" ∨ t = 10)) 0 := by
  intro _
  exact ⟨10, by decide, by decide, Or.inr rfl⟩
example : ¬ Deadline.qualifiedLegalFormula_0 (toy (fun name t => name = "requested" ∨ t = 11)) 0 := by
  intro h
  obtain ⟨u, _, upper, value⟩ := h (Or.inl rfl)
  have eq : u = 11 := by simpa [toy] using value
  subst u
  exact (by decide : ¬ (11 ≤ 0 + 10)) upper
example : Instant.qualifiedLegalFormula_0 (toy (fun _ _ => False)) 0 := by
  intro h
  exact False.elim h
example : ¬ Instant.qualifiedLegalFormula_0 (toy (fun name _ => name = "requested")) 0 := by
  intro h
  have impossible := h rfl
  exact (by decide : ¬ ("retain" = "requested")) impossible
example : Compound.qualifiedLegalFormula_0 (toy (fun name _ =>
    name = "requested" ∨ name = "urgent" ∨ name = "retain")) 0 := by
  simp [Compound.qualifiedLegalFormula_0, toy]
example : ¬ Compound.qualifiedLegalFormula_0 (toy (fun name _ =>
    name = "requested" ∨ name = "urgent")) 0 := by
  simp [Compound.qualifiedLegalFormula_0, toy]
-- An emergency only at tick 5 exempts that tick, not the whole interval.
example : Tick.qualifiedLegalFormula_0 (toy (fun name t =>
    (name = "emergency" ∧ t = 5) ∨ (name = "retain" ∧ t ≠ 5))) 0 := by
  intro u _ _ noEmergency
  apply Or.inr
  refine ⟨rfl, ?_⟩
  intro eq
  exact noEmergency (Or.inl ⟨rfl, eq⟩)
example : ¬ Waiver.qualifiedLegalFormula_0 (toy (fun name t =>
    (name = "emergency" ∧ t = 5) ∨ (name = "retain" ∧ t ≠ 5))) 0 := by
  intro h
  have noEmergency : ¬ (("emergency" = "emergency" ∧ 0 = 5) ∨ ("emergency" = "retain" ∧ 0 ≠ 5)) := by decide
  have value := h noEmergency 5 (by decide) (by decide)
  simpa [toy] using value
-- Conversely activation waiver can waive the full body, unlike per-tick exemption.
example : Waiver.qualifiedLegalFormula_0 (toy (fun name t => name = "emergency" ∧ t = 0)) 0 := by
  intro h
  exact False.elim (h ⟨rfl, rfl⟩)
example : ¬ Tick.qualifiedLegalFormula_0 (toy (fun name t => name = "emergency" ∧ t = 0)) 0 := by
  intro h
  have value := h 1 (by decide) (by decide) (by simp [toy])
  simpa [toy] using value
''')
    return "\n".join(blocks)


def run_lake(tmp_path, source):
    lake=os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not lake: pytest.skip("set explicit installed Lake executable")
    (tmp_path/"lakefile.toml").write_text('name = "LegalIR"\nversion = "0.1.0"\n[[lean_lib]]\nname = "LegalIR"\n')
    (tmp_path/"LegalIR.lean").write_text(source)
    return subprocess.run([str(Path(lake).resolve()),"build","LegalIR"],cwd=tmp_path,text=True,capture_output=True,timeout=60)


def test_real_lake_conditional_and_exception_scope_semantics(tmp_path):
    result=run_lake(tmp_path,lean_source())
    assert result.returncode==0,result.stdout+result.stderr


def test_real_lake_rejects_false_activation_compliance_claim(tmp_path):
    source=lean_source()+'''\nexample : Instant.qualifiedLegalFormula_0 (toy (fun name _ => name = "requested")) 0 := by
  intro _
  change ("retain" : String) = "requested"
  decide
'''
    result=run_lake(tmp_path,source)
    assert result.returncode!=0
    assert "error:" in result.stdout+result.stderr
