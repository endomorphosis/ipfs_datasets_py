"""Source-bound reversible lowering; compiler witnesses are not legal gold labels."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as bridge
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emitters
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR


def candidate(*, modality="O", conditions=("requested",), exceptions=("emergency",),
              temporal=("within 10 days",), action="retain", text="Authored caller interpretation fixture."):
    rule = {"modality": modality, "actor": "agency", "action": action, "object": "record",
            "conditions": list(conditions), "exceptions": list(exceptions), "temporal": list(temporal)}
    return {"candidate_id": "candidate:fixture", "source_text": text,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "canonical_ir": CanonicalRoundTripIR.from_dict({"rules": [rule]}).to_dict()}


def atom(name):
    return {"op": "atom", "predicate": {"name": name, "arguments": []}}


def declared(row, *, kind="within_duration", quantity=10, unit="day", scope="activation_time_waiver"):
    """An authored test convention, not a parser or source-semantics oracle."""
    value = bridge.interpretation_skeleton(row)
    for formula in value["formulas"]:
        formula["activation_scope"] = "all_conditions_at_evaluation_origin"
        formula["exception_scope"] = scope
        for entry in formula["conditions"] + formula["exceptions"]:
            entry["expression"] = atom(entry["source_text"])
        if formula["temporal"] is not None:
            formula["temporal"].update(temporal_kind=kind, quantity=quantity, unit=unit,
                time_domain="discrete_nat", origin="caller_supplied_evaluation_time",
                lower_inclusive=True, upper_inclusive=True)
    return value


@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_all_canonical_facets_are_retained_and_source_join_is_full(modality):
    row = candidate(modality=modality, text="Source α: full text, not merely a decoded span.")
    sidecar = declared(row)
    before = deepcopy((row, sidecar))
    result = bridge.prepare_canonical_qualified(row, sidecar)
    assert (row, sidecar) == before
    assert result["original_canonical_ir"] == row["canonical_ir"]
    assert result["canonical_ir_sha256"] == bridge.digest(row["canonical_ir"])
    assert result["interpretation_sha256"] == bridge.digest(sidecar)
    assert bridge.reconstruct_canonical(result["native_projection"], result["reversible_mapping"]) == row["canonical_ir"]
    native = result["native_projection"]["payload"]["formulas"][0]
    assert native["conditions"] == ["requested", "within 10 days"]
    assert native["exceptions"] == ["emergency"]
    assert native["operator"]["symbol"] == modality
    assert native["provenance"] == {"source_id": row["candidate_id"], "start_char": 0,
                                    "end_char": len(row["source_text"]), "citation": None}
    assert result["source_ref"]["content_sha256"] == row["source_sha256"]
    assert result["source_ref"]["review_status"] == "unreviewed"
    assert result["lowering_details"]["source_semantics_verified"] is False
    assert result["lowering_details"]["canonical_facets_preserved"] is True
    assert result["source_text_inference_executed"] is result["admitted"] is False
    assert '"deontic:' + modality + '"' in result["lean_body"]
    assert result == bridge.prepare_canonical_qualified(row, sidecar)
    result["original_canonical_ir"]["rules"].clear()
    assert row["canonical_ir"] == before[0]["canonical_ir"]


@pytest.mark.parametrize("qualified", [False, True])
def test_skeleton_never_supplies_semantic_choices(qualified):
    row = candidate() if qualified else candidate(conditions=(), exceptions=(), temporal=())
    sidecar = bridge.interpretation_skeleton(row)
    declaration = sidecar["formulas"][0]
    assert declaration["activation_scope"] is declaration["exception_scope"] is None
    if qualified:
        assert declaration["conditions"][0]["expression"] is None
        assert declaration["temporal"]["quantity"] is None
        assert declaration["temporal"]["origin"] is None
    with pytest.raises(ValueError, match="activation_scope"):
        bridge.prepare_canonical_qualified(row, sidecar)


def test_unqualified_profile_is_explicit_and_does_not_claim_old_equivalence():
    row = candidate(conditions=(), exceptions=(), temporal=())
    result = bridge.prepare_canonical_qualified(row, declared(row))
    assert 'some "explicit-clock:instantaneous"' in result["lean_body"]
    assert result["lowering_details"]["old_unqualified_lowering_equivalence_verified"] is False


@pytest.mark.parametrize("field", ["candidate_id", "candidate_sha256", "source_sha256", "canonical_ir_sha256", "mapping_sha256"])
def test_every_candidate_identity_binding_is_required(field):
    row = candidate()
    sidecar = declared(row)
    sidecar[field] = "foreign" if field == "candidate_id" else "f" * 64
    with pytest.raises(ValueError, match="binding differs"):
        bridge.prepare_canonical_qualified(row, sidecar)


def test_same_canonical_rule_cannot_borrow_another_source_sidecar():
    row = candidate()
    other = candidate(text="A different complete source with the same hypothetical canonical rule.")
    with pytest.raises(ValueError, match="binding differs"):
        bridge.prepare_canonical_qualified(other, declared(row))


@pytest.mark.parametrize("mutation", ["source", "hash", "extra_candidate", "extra_sidecar", "extra_formula",
    "missing_condition", "missing_exception", "missing_temporal", "wrong_temporal_index", "reordered_rules",
    "duplicate_condition", "unknown_modality", "open_action", "too_many_rules", "too_many_guards",
    "too_many_exceptions", "source_bound", "nonlist_qualifiers"])
def test_closed_bounded_exact_input_and_exhaustive_declarations(mutation):
    row = candidate()
    sidecar = declared(row)
    rule = row["canonical_ir"]["rules"][0]
    if mutation == "source": row["source_text"] += "changed"
    elif mutation == "hash": row["source_sha256"] = "a" * 64
    elif mutation == "extra_candidate": row["ignored"] = True
    elif mutation == "extra_sidecar": sidecar["source_semantics_verified"] = True
    elif mutation == "extra_formula": sidecar["formulas"][0]["default"] = True
    elif mutation == "missing_condition": sidecar["formulas"][0]["conditions"] = []
    elif mutation == "missing_exception": sidecar["formulas"][0]["exceptions"] = []
    elif mutation == "missing_temporal": sidecar["formulas"][0]["temporal"] = None
    elif mutation == "wrong_temporal_index": sidecar["formulas"][0]["temporal"]["source_index"] = 0
    elif mutation == "reordered_rules":
        second = dict(rule, actor="aaaa")
        row["canonical_ir"]["rules"] = [rule, second]
    elif mutation == "duplicate_condition": rule["conditions"].append("requested")
    elif mutation == "unknown_modality": rule["modality"] = "G"
    elif mutation == "open_action": rule["action"] = "retain record"
    elif mutation == "too_many_rules": row["canonical_ir"]["rules"] *= 65
    elif mutation == "too_many_guards": rule["conditions"] = [f"g{n:02d}" for n in range(16)]
    elif mutation == "too_many_exceptions": rule["exceptions"] = [f"e{n:02d}" for n in range(9)]
    elif mutation == "source_bound":
        row["source_text"] = "a" * (bridge.MAX_SOURCE_BYTES + 1)
        row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
    elif mutation == "nonlist_qualifiers": rule["conditions"] = tuple(rule["conditions"])
    with pytest.raises(ValueError):
        bridge.prepare_canonical_qualified(row, sidecar)


@pytest.mark.parametrize("literal", ["before 2030-01-01", "after January 1", "within 10 business days", "within 0 days"])
def test_calendar_and_unsupported_clocks_fail_closed(literal):
    with pytest.raises(ValueError, match="duration"):
        bridge.interpretation_skeleton(candidate(temporal=(literal,)))


def test_multiple_temporal_atoms_never_partially_compile():
    with pytest.raises(ValueError, match="at most one"):
        bridge.interpretation_skeleton(candidate(temporal=("within 10 days", "for at least 20 days")))


def test_temporal_like_condition_cannot_be_moved_to_temporal_even_with_native_binding():
    row = candidate(conditions=("within 10 days",), temporal=(), exceptions=())
    value = bridge.interpretation_skeleton(row)
    value["formulas"][0].update(activation_scope="all_conditions_at_evaluation_origin",
        exception_scope="activation_time_waiver", conditions=[], temporal={
            "source_index": 0, "source_text": "within 10 days", "temporal_kind": "within_duration",
            "quantity": 10, "unit": "day", "time_domain": "discrete_nat",
            "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True})
    with pytest.raises(ValueError, match="activation condition cannot become temporal"):
        bridge.prepare_canonical_qualified(row, value)


def test_same_literal_conflicting_condition_and_exception_bindings_rejected():
    row = candidate(conditions=("emergency",), exceptions=("emergency",))
    value = declared(row)
    value["formulas"][0]["exceptions"][0]["expression"] = atom("notEmergency")
    with pytest.raises(ValueError, match="conflicting_interpretations"):
        bridge.prepare_canonical_qualified(row, value)


def test_compound_expression_is_caller_supplied_and_retained():
    row = candidate()
    value = declared(row)
    expression = {"op": "all", "operands": [atom("requested"),
        {"op": "not", "operand": atom("withdrawn")},
        {"op": "any", "operands": [atom("authorized"), atom("urgent")]}]}
    value["formulas"][0]["conditions"][0]["expression"] = expression
    result = bridge.prepare_canonical_qualified(row, value)
    assert result["interpretation"]["formulas"][0]["conditions"][0]["expression"] == expression
    assert all(symbol in result["lean_body"] for symbol in ("∧", "∨", "¬"))


@pytest.mark.parametrize("field,bad", [("quantity", True), ("quantity", 11), ("unit", "hour"),
    ("origin", "trigger_inferred_from_source"), ("time_domain", "real"), ("upper_inclusive", False)])
def test_clock_claims_must_exactly_match_explicit_supported_literal(field, bad):
    row = candidate()
    value = declared(row)
    value["formulas"][0]["temporal"][field] = bad
    with pytest.raises(ValueError):
        bridge.prepare_canonical_qualified(row, value)


def test_multirule_mapping_is_ordered_and_qualifier_facets_are_reversible():
    row = candidate()
    other = candidate(modality="P", conditions=(), exceptions=(), temporal=(), action="submit")["canonical_ir"]["rules"][0]
    row["canonical_ir"] = CanonicalRoundTripIR.from_dict({"rules": row["canonical_ir"]["rules"] + [other]}).to_dict()
    result = bridge.prepare_canonical_qualified(row, declared(row))
    assert bridge.reconstruct_canonical(result["native_projection"], result["reversible_mapping"]) == row["canonical_ir"]
    tampered = deepcopy(result["reversible_mapping"])
    tampered["rules"].reverse()
    with pytest.raises(ValueError, match="ordered formula"):
        bridge.reconstruct_canonical(result["native_projection"], tampered)
    tampered = deepcopy(result["reversible_mapping"])
    nonempty = next(item for item in tampered["rules"] if item["qualifier_origins"])
    nonempty["qualifier_origins"].pop()
    with pytest.raises(ValueError, match="accounting"):
        bridge.reconstruct_canonical(result["native_projection"], tampered)


def test_producer_change_since_import_fails_closed(monkeypatch):
    monkeypatch.setattr(bridge, "_IMPORTED_PINS", {})
    with pytest.raises(ValueError, match="producer changed"):
        bridge.interpretation_skeleton(candidate())


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


def semantic_source():
    # Independently authored countermodels distinguish dropped guards, dropped
    # deadlines, and moved exception scope. Transparent toy modality is an
    # explicit interpretation, never an axiom that obligations imply compliance.
    definitions = []
    cases = [
        ("Guarded", candidate(exceptions=(), temporal=()), {}),
        ("DroppedGuard", candidate(conditions=(), exceptions=(), temporal=()), {}),
        ("Deadline", candidate(conditions=(), exceptions=()), {}),
        ("Waiver", candidate(conditions=(), temporal=("for at least 20 days",)), {"kind": "minimum_duration", "quantity": 20}),
        ("Tick", candidate(conditions=(), temporal=("for at least 20 days",)), {"kind": "minimum_duration", "quantity": 20, "scope": "per_tick_exemption"}),
    ]
    for name, row, choices in cases:
        code = bridge.prepare_canonical_qualified(row, declared(row, **choices))["lean_body"]
        definitions.append("namespace " + name + "\n" + code + "\nend " + name)
    return emitters.PRELUDE + TOY + "\n".join(definitions) + '''
-- A false activation guard makes the conditional vacuous; dropping it changes meaning.
example : Guarded.qualifiedLegalFormula_0 (toy (fun _ _ => False)) 0 := by
  intro h
  exact False.elim h
example : ¬ DroppedGuard.qualifiedLegalFormula_0 (toy (fun _ _ => False)) 0 := by
  intro h
  exact h
-- A witness at the closed upper bound is valid, despite no occurrence at the origin.
example : Deadline.qualifiedLegalFormula_0 (toy (fun _ t => t = 10)) 0 := by
  exact ⟨10, by decide, by decide, rfl⟩
example : ¬ DroppedGuard.qualifiedLegalFormula_0 (toy (fun _ t => t = 10)) 0 := by
  change ¬ (0 = 10)
  decide
-- A witness one tick later cannot satisfy the original deadline.
example : ¬ Deadline.qualifiedLegalFormula_0 (toy (fun _ t => t = 11)) 0 := by
  intro h
  obtain ⟨u, _, upper, value⟩ := h
  have eq : u = 11 := value
  subst u
  exact (by decide : ¬ (11 ≤ 0 + 10)) upper
-- Emergency only at the origin waives the whole activation, but not later ticks.
example : Waiver.qualifiedLegalFormula_0 (toy (fun name t => name = "emergency" ∧ t = 0)) 0 := by
  intro h
  exact False.elim (h ⟨rfl, rfl⟩)
example : ¬ Tick.qualifiedLegalFormula_0 (toy (fun name t => name = "emergency" ∧ t = 0)) 0 := by
  intro h
  have value := h 1 (by decide) (by decide) (by simp [toy])
  simpa [toy] using value
-- Emergency only at tick 5 exempts precisely that tick under the other declaration.
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
'''


def run_lake(tmp_path, source):
    executable = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set explicit installed Lake executable")
    (tmp_path / "lakefile.toml").write_text('name = "bridge_witness"\nversion = "0.1.0"\n[[lean_lib]]\nname = "legal"\nroots = ["BridgeWitness"]\n')
    (tmp_path / "BridgeWitness.lean").write_text(source)
    return subprocess.run([str(Path(executable).resolve()), "build", "legal"], cwd=tmp_path,
                          text=True, capture_output=True, timeout=60)


def test_real_lake_guard_deadline_and_exception_countermodels(tmp_path):
    result = run_lake(tmp_path, semantic_source())
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_lake_rejects_false_guarded_compliance_claim(tmp_path):
    source = semantic_source() + '''
example : Guarded.qualifiedLegalFormula_0 (toy (fun name _ => name = "requested")) 0 := by
  intro _
  change ("retain" : String) = "requested"
  decide
'''
    result = run_lake(tmp_path, source)
    assert result.returncode != 0
    assert "error:" in result.stdout + result.stderr
