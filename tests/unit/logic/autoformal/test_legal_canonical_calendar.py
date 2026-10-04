"""Gregorian deadlines are explicit absolute dates, never guessed durations."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_canonical_calendar as calendar
from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as previous
from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emitters
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR


def candidate(literal="before 2000-03-01", *, conditions=(), exceptions=(), modality="O", identifier="calendar:fixture"):
    text = "Authored calendar fixture " + identifier + "."
    return {"candidate_id": identifier, "source_text": text,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "canonical_ir": {"rules": [{
            "modality": modality, "actor": "agency", "action": "retain", "object": "record",
            "conditions": list(conditions), "exceptions": list(exceptions), "temporal": [literal] if literal else []}]}}


def interpreted(row):
    value = calendar.interpretation_skeleton(row)
    for declaration in value["formulas"]:
        declaration.update(activation_scope="all_conditions_at_evaluation_origin", exception_scope="activation_time_waiver")
        for binding in declaration["conditions"] + declaration["exceptions"]:
            binding["expression"] = {"op": "atom", "predicate": {"name": "qualifier", "arguments": [binding["source_text"]]}}
        if declaration["temporal"]:
            temporal = declaration["temporal"]
            if temporal["source_text"].startswith("before "):
                temporal.update(temporal_kind="before_calendar_date", calendar="proleptic_gregorian",
                    ordinal_epoch="0001-01-01", ordinal_epoch_value=1, time_domain="discrete_nat_days",
                    origin="caller_supplied_evaluation_date_ordinal", lower_inclusive=True, upper_inclusive=False,
                    expired_deadline_policy="empty_witness_interval", **calendar.parse_calendar_literal(temporal["source_text"]))
            else:
                # This independent fixture has an authored within10days meaning.
                temporal.update(temporal_kind="within_duration", quantity=10, unit="day", time_domain="discrete_nat",
                    origin="caller_supplied_evaluation_time", lower_inclusive=True, upper_inclusive=True)
    return value


@pytest.mark.parametrize("literal,ordinal", [("before 0001-01-01", 1), ("before 1900-02-28", 693654),
    ("before 1900-03-01", 693655), ("before 2000-02-28", 730178), ("before 2000-02-29", 730179),
    ("before 2000-03-01", 730180), ("before 2024-02-29", 738945), ("before 9999-12-31", 3652059)])
def test_explicit_known_gregorian_ordinals_and_leap_centuries(literal, ordinal):
    assert calendar.parse_calendar_literal(literal) == {"date": literal[7:], "date_ordinal": ordinal}


@pytest.mark.parametrize("literal", ["before 1900-02-29", "before 2100-02-29", "before 2001-02-29",
    "before 0000-01-01", "before 10000-01-01", "before 2000-13-01", "before 2000-04-31",
    "before 2000-2-29", "before 2000-03-01T00:00Z", "before tomorrow", "on or before 2000-03-01"])
def test_invalid_dates_and_unsupported_calendar_syntax_fail_closed(literal):
    with pytest.raises(ValueError):
        calendar.interpretation_skeleton(candidate(literal))


@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_calendar_all_facets_and_native_mapping_preserved(modality):
    row = candidate(conditions=("requested",), exceptions=("emergency",), modality=modality)
    sidecar = interpreted(row)
    snapshot = deepcopy((row, sidecar))
    result = calendar.prepare_canonical_qualified(row, sidecar)
    assert (row, sidecar) == snapshot
    assert result["original_canonical_ir"] == row["canonical_ir"]
    assert previous.reconstruct_canonical(result["native_projection"], result["reversible_mapping"]) == row["canonical_ir"]
    assert result["source_ref"]["content_sha256"] == row["source_sha256"]
    assert result["lowering_details"]["calendar_interpretations"][0]["date_ordinal"] == 730180
    assert "u < 730180" in result["lean_body"] and "origin + 730180" not in result["lean_body"]
    assert "1 ≤ origin" in result["lean_body"]
    assert '"deontic:' + modality + '"' in result["lean_body"]
    assert result["source_semantics_verified"] is result["source_text_inference_executed"] is result["admitted"] is False
    assert result["lowering_details"]["event_occurrences_attested"] is False
    assert result == calendar.prepare_canonical_qualified(row, sidecar)


def test_calendar_skeleton_supplies_no_semantic_or_date_choices():
    row = candidate()
    sidecar = calendar.interpretation_skeleton(row)
    temporal = sidecar["formulas"][0]["temporal"]
    assert temporal["source_text"] == "before 2000-03-01"
    assert all(value is None for key, value in temporal.items() if key not in ("source_text", "source_index"))
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, sidecar)


@pytest.mark.parametrize("field,bad", [("date", "2000-03-02"), ("date_ordinal", 730181),
    ("date_ordinal", 730180.0), ("calendar", "julian"), ("ordinal_epoch", "1970-01-01"),
    ("ordinal_epoch_value", True), ("time_domain", "real_seconds"), ("upper_inclusive", True),
    ("lower_inclusive", False), ("origin", "inferred_trigger_date"),
    ("expired_deadline_policy", "restart_clock"), ("temporal_kind", "within_duration")])
def test_calendar_contract_is_closed_exact_and_not_a_duration(field, bad):
    row = candidate()
    sidecar = interpreted(row)
    sidecar["formulas"][0]["temporal"][field] = bad
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, sidecar)


@pytest.mark.parametrize("mutation", ["drop_date", "extra_date", "borrow_source", "shift_index", "extra_field",
    "per_tick", "missing_guard", "missing_exception", "wrong_native_hash", "wrong_mapping_hash"])
def test_exact_candidate_and_exhaustive_interpretation_bindings(mutation):
    row = candidate(conditions=("requested",), exceptions=("emergency",))
    sidecar = interpreted(row)
    declaration = sidecar["formulas"][0]
    if mutation == "drop_date": declaration["temporal"] = None
    elif mutation == "extra_date": row["canonical_ir"]["rules"][0]["temporal"].append("before 2000-03-02")
    elif mutation == "borrow_source":
        row["source_text"] += "different"
        row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
    elif mutation == "shift_index": declaration["temporal"]["source_index"] = 0
    elif mutation == "extra_field": declaration["temporal"]["timezone"] = "UTC"
    elif mutation == "per_tick": declaration["exception_scope"] = "per_tick_exemption"
    elif mutation == "missing_guard": declaration["conditions"] = []
    elif mutation == "missing_exception": declaration["exceptions"] = []
    elif mutation == "wrong_native_hash": declaration["original_formula_sha256"] = "a" * 64
    elif mutation == "wrong_mapping_hash": sidecar["mapping_sha256"] = "a" * 64
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, sidecar)


def test_noncalendar_routing_does_not_invent_missing_temporal_or_change_old_results():
    for literal in ("", "within 10 days"):
        row = candidate(literal)
        declaration = interpreted(row)
        assert calendar.interpretation_skeleton(row) == previous.interpretation_skeleton(row)
        assert calendar.prepare_canonical_qualified(row, declaration) == previous.prepare_canonical_qualified(row, declaration)


def test_mixed_calendar_duration_and_instantaneous_rules_preserve_native_routes():
    row = candidate()
    row["canonical_ir"] = CanonicalRoundTripIR.from_dict({"rules": [
        candidate()["canonical_ir"]["rules"][0], candidate("within 10 days")["canonical_ir"]["rules"][0],
        candidate("")["canonical_ir"]["rules"][0]]}).to_dict()
    result = calendar.prepare_canonical_qualified(row, interpreted(row))
    assert len(result["native_projection"]["payload"]["formulas"]) == 3
    assert len(result["lowering_details"]["calendar_interpretations"]) == 1
    assert previous.reconstruct_canonical(result["native_projection"], result["reversible_mapping"]) == row["canonical_ir"]
    assert "u < 730180" in result["lean_body"] and "origin + 10" in result["lean_body"]


def test_literal_conflict_across_calendar_and_duration_rules_rejected():
    row = candidate(conditions=("requested",))
    duration = candidate("within 10 days", conditions=("requested",))["canonical_ir"]["rules"][0]
    row["canonical_ir"] = CanonicalRoundTripIR.from_dict({"rules": [row["canonical_ir"]["rules"][0], duration]}).to_dict()
    sidecar = interpreted(row)
    sidecar["formulas"][1]["conditions"][0]["expression"]["predicate"]["name"] = "conflicting"
    with pytest.raises(ValueError, match="conflicting_interpretations"):
        calendar.prepare_canonical_qualified(row, sidecar)


def test_gate_blocks_whole_batch_without_calendar_interpretation():
    row = candidate()
    preparation = gate.prepare_qualified_legal([{"candidate": row, "interpretation": None}], toolchain="leanprover/lean4:v4.34.1")
    assert preparation.to_dict()["status"] == "blocked"
    assert all(not name.endswith(".lean") for name, _ in preparation.files)


def test_gate_replay_detects_omitted_import_or_interpretation_change():
    row = candidate()
    preparation = gate.prepare_qualified_legal([{"candidate": row, "interpretation": interpreted(row)}], toolchain="leanprover/lean4:v4.34.1")
    gate.validate_preparation(preparation)
    forged = replace(preparation, files=tuple((name, body) for name, body in preparation.files if name != "LegalCalendar.lean"))
    with pytest.raises(ValueError, match="coverage changed"):
        gate.validate_preparation(forged)


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
    parts = [emitters.PRELUDE, TOY]
    for name, literal in (("March", "before 2000-03-01"), ("Leap", "before 2000-02-29"), ("Omitted", "")):
        row = candidate(literal)
        parts.append("namespace " + name + "\n" + calendar.prepare_canonical_qualified(row, interpreted(row))["lean_body"] + "\nend " + name)
    parts.append('''
-- These independently written constants distinguish leap day from March1.
example : (730179 : Nat) + 1 = 730180 := by decide
-- Leap-day occurrence is before March1, with evaluation origin on February28.
example : March.qualifiedLegalFormula_0 (toy (fun _ t => t = 730179)) 730178 := by
  exact ⟨by decide, 730179, by decide, by decide, rfl⟩
-- The same occurrence is not strictly before the leap-day deadline itself.
example : ¬ Leap.qualifiedLegalFormula_0 (toy (fun _ t => t = 730179)) 730178 := by
  intro h
  obtain ⟨_, u, _, upper, value⟩ := h
  have eq : u = 730179 := value
  subst u
  exact (Nat.lt_irrefl 730179) upper
-- Strict boundary excludes March1 even if that is the only occurrence.
example : ¬ March.qualifiedLegalFormula_0 (toy (fun _ t => t = 730180)) 730178 := by
  intro h
  obtain ⟨_, u, _, upper, value⟩ := h
  have eq : u = 730180 := value
  subst u
  exact (Nat.lt_irrefl 730180) upper
-- Origin is caller-supplied; an earlier occurrence cannot satisfy a later origin.
example : ¬ March.qualifiedLegalFormula_0 (toy (fun _ t => t = 730178)) 730179 := by
  intro h
  obtain ⟨_, u, lower, _, value⟩ := h
  have eq : u = 730178 := value
  subst u
  exact (by decide : ¬ (730179 ≤ 730178)) lower
-- At the deadline origin there are no interval witnesses, even if the atom is true.
example : ¬ March.qualifiedLegalFormula_0 (toy (fun _ _ => True)) 730180 := by
  intro h
  obtain ⟨_, u, lower, upper, _⟩ := h
  exact (Nat.not_lt_of_ge lower) upper
-- Omitting the date can reverse the formula's truth in the same interpretation.
example : Omitted.qualifiedLegalFormula_0 (toy (fun _ _ => True)) 730180 := by
  trivial
-- Ordinal zero is not an evaluation date in the declared day1 epoch.
example : ¬ March.qualifiedLegalFormula_0 (toy (fun _ _ => True)) 0 := by
  intro h
  exact (by decide : ¬ (1 ≤ 0)) h.1
''')
    return "\n".join(parts)


def run_lake(tmp_path, source):
    executable = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable: pytest.skip("set explicit installed Lake executable")
    (tmp_path / "lakefile.toml").write_text('name = "calendar_witness"\nversion = "0.1.0"\n[[lean_lib]]\nname = "legal"\nroots = ["CalendarWitness"]\n')
    (tmp_path / "CalendarWitness.lean").write_text(source)
    return subprocess.run([str(Path(executable).resolve()), "build", "legal"], cwd=tmp_path,
                          text=True, capture_output=True, timeout=60)


def test_real_lake_gregorian_boundary_origin_and_omitted_date_countermodels(tmp_path):
    result = run_lake(tmp_path, semantic_source())
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_lake_rejects_false_inclusive_deadline_claim(tmp_path):
    source = semantic_source() + '''
example : March.qualifiedLegalFormula_0 (toy (fun _ _ => True)) 730180 := by
  exact ⟨by decide, 730180, by decide, by decide, trivial⟩
'''
    result = run_lake(tmp_path, source)
    assert result.returncode != 0
    assert "error:" in result.stdout + result.stderr


def test_real_calendar_gate_builds_exact_legal_and_covers_mixed_candidates(tmp_path):
    executable = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable: pytest.skip("set explicit installed Lake executable")
    rows = [candidate(identifier="calendar:calendar"), candidate("within 10 days", identifier="calendar:duration"),
            candidate("", identifier="calendar:instant")]
    receipt = gate.build_qualified_legal([{"candidate": row, "interpretation": interpreted(row)} for row in rows],
        toolchain="leanprover/lean4:v4.34.1", lake_executable=executable, output_directory=tmp_path / "build").to_dict()
    assert receipt["build_passed"] and receipt["manifest_coverage_passed"]
    assert receipt["command"][-2:] == ["build", "legal"]
    assert len(receipt["compiled_modules"]) == 5
    assert receipt["all_logic_families_supported"] is False
    assert {row["profile"] for row in receipt["candidates"]} == {calendar.PROFILE, "canonical-explicit-qualified/v1"}
