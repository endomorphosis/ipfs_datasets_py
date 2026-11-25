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


_EFFECTIVE_DATE = "2000-02-29"
_EFFECTIVE_ORDINAL = 730179
_EFFECTIVE_LITERAL = "effective from " + _EFFECTIVE_DATE
_DEADLINE_LITERAL = "before 2000-03-01"
_EFFECTIVE_NORM = 'Norm: "agency" must "retain" "record".'
_EFFECTIVE_TEMPORAL = 'Temporal: effective from 2000-02-29; "before 2000-03-01".'
_EFFECTIVE_SOURCE = _EFFECTIVE_NORM + " " + _EFFECTIVE_TEMPORAL
_EFFECTIVE_QUALIFIED_SOURCE = (
    _EFFECTIVE_NORM + ' Conditions: "requested". Exceptions: "emergency". ' + _EFFECTIVE_TEMPORAL
)


def effective_calendar_candidate(source=_EFFECTIVE_SOURCE):
    return calendar.candidate_from_effective_date_prose(source, candidate_id="calendar:effective")


def interpreted_effective_calendar(row):
    sidecar = interpreted(row)
    for declaration in sidecar["formulas"]:
        effective = declaration["effective_from"]
        if effective is not None:
            assert effective["source_text"] == _EFFECTIVE_LITERAL
            effective.update(
                date=_EFFECTIVE_DATE,
                date_ordinal=_EFFECTIVE_ORDINAL,
                placement="activation_at_evaluation_origin_before_modality",
                lower_inclusive=True,
            )
    return sidecar


def test_effective_calendar_preserves_typed_source_and_both_canonical_qualifiers():
    row = effective_calendar_candidate(_EFFECTIVE_QUALIFIED_SOURCE)
    skeleton = calendar.interpretation_skeleton(row)
    assert skeleton["schema"] == calendar.EFFECTIVE_INTERPRETATION_SCHEMA
    declaration = skeleton["formulas"][0]
    assert declaration["effective_from"] == {
        "source_index": 2,
        "canonical_temporal_index": 1,
        "source_text": _EFFECTIVE_LITERAL,
        "date": None,
        "date_ordinal": None,
        "placement": None,
        "lower_inclusive": None,
    }
    assert declaration["temporal"]["source_index"] == 1
    assert declaration["temporal"]["source_text"] == _DEADLINE_LITERAL

    sidecar = interpreted_effective_calendar(row)
    incomplete = deepcopy(sidecar)
    incomplete["formulas"][0]["effective_from"] = declaration["effective_from"]
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, incomplete)

    snapshot = deepcopy((row, sidecar))
    result = calendar.prepare_canonical_qualified(row, sidecar)
    assert (row, sidecar) == snapshot
    assert result == calendar.prepare_canonical_qualified(row, sidecar)
    assert result["schema"] == calendar.EFFECTIVE_SCHEMA
    typed = result["typed_source_ir"]
    assert typed == {
        "schema": "legal-surface-ir-with-effective-dates/v1",
        "statements": [{
            "kind": "norm",
            "modality": "O",
            "actor": "agency",
            "action": "retain",
            "object": "record",
            "scope": [],
            "conditions": ["requested"],
            "exceptions": ["emergency"],
            "temporal": [{"effective_from": _EFFECTIVE_DATE}, _DEADLINE_LITERAL],
        }],
    }
    assert result["source_ref"]["content_sha256"] == hashlib.sha256(
        _EFFECTIVE_QUALIFIED_SOURCE.encode()
    ).hexdigest()
    typed_sha256 = calendar.digest(typed)
    assert skeleton["typed_source_ir_sha256"] == typed_sha256
    assert result["typed_source_ir_sha256"] == typed_sha256
    assert skeleton["canonical_to_source_statement_index"] == [0]
    assert result["canonical_to_source_statement_index"] == [0]
    assert result["original_canonical_ir"] == row["canonical_ir"]
    rule, = row["canonical_ir"]["rules"]
    assert rule["conditions"] == ["requested"]
    assert rule["exceptions"] == ["emergency"]
    assert rule["temporal"] == [_DEADLINE_LITERAL, _EFFECTIVE_LITERAL]
    projection = result["native_projection"]
    formula, = projection["payload"]["formulas"]
    assert formula["conditions"] == ["requested", _DEADLINE_LITERAL, _EFFECTIVE_LITERAL]
    assert formula["exceptions"] == ["emergency"]
    assert previous.reconstruct_canonical(projection, result["reversible_mapping"]) == row["canonical_ir"]
    qualified = result["qualified_projection"]
    assert qualified["profile"] == calendar.EFFECTIVE_PROFILE
    assert qualified["payload"]["typed_source_ir"] == typed
    assert qualified["payload"]["typed_source_ir_sha256"] == typed_sha256
    assert qualified["payload"]["canonical_to_source_statement_index"] == [0]
    lowering = result["lowering_details"]
    assert lowering["effective_interpretations"] == [{
        "source_index": 2,
        "canonical_temporal_index": 1,
        "source_text": _EFFECTIVE_LITERAL,
        "date": _EFFECTIVE_DATE,
        "date_ordinal": _EFFECTIVE_ORDINAL,
        "placement": "activation_at_evaluation_origin_before_modality",
        "lower_inclusive": True,
        "formula_index": 0,
        "native_condition_index": 2,
        "source_statement_index": 0,
    }]
    deadline, = lowering["calendar_interpretations"]
    assert deadline["formula_index"] == 0
    assert deadline["native_condition_index"] == 1
    assert deadline["canonical_temporal_index"] == 0
    assert deadline["date_ordinal"] == 730180
    assert deadline["interval"] == "origin_inclusive_deadline_exclusive"
    assert result["source_semantics_verified"] is result["source_text_inference_executed"] is result["admitted"] is False


def test_effective_calendar_replays_source_order_independently_of_canonical_order():
    first = _EFFECTIVE_NORM.replace('"agency"', '"zeta"') + " Temporal: effective from 2000-02-29."
    second = _EFFECTIVE_SOURCE
    row = effective_calendar_candidate(first + "\n" + second)
    sidecar = interpreted_effective_calendar(row)
    result = calendar.prepare_canonical_qualified(row, sidecar)
    assert [statement["actor"] for statement in result["typed_source_ir"]["statements"]] == ["zeta", "agency"]
    assert [rule["actor"] for rule in row["canonical_ir"]["rules"]] == ["agency", "zeta"]
    assert sidecar["canonical_to_source_statement_index"] == [1, 0]
    assert result["canonical_to_source_statement_index"] == [1, 0]
    assert result["typed_source_ir"]["statements"][0]["temporal"] == [{"effective_from": _EFFECTIVE_DATE}]
    starts = result["lowering_details"]["effective_interpretations"]
    assert [start["source_statement_index"] for start in starts] == [1, 0]
    only_deadline, = result["lowering_details"]["calendar_interpretations"]
    assert only_deadline["formula_index"] == 0
    sidecar["canonical_to_source_statement_index"] = [0, 1]
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, sidecar)


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("date", "2000-02-28", id="date"),
        pytest.param("date_ordinal", 730178, id="ordinal"),
        pytest.param("date_ordinal", 730179.0, id="ordinal-type"),
        pytest.param("source_index", 1, id="native-deadline-index"),
        pytest.param("canonical_temporal_index", 0, id="canonical-deadline-index"),
        pytest.param("source_text", _DEADLINE_LITERAL, id="source-literal"),
        pytest.param("placement", "inside_modality", id="placement"),
        pytest.param("lower_inclusive", False, id="exclusive-start"),
    ],
)
def test_effective_calendar_interpretation_refuses_start_drift(field, value):
    row = effective_calendar_candidate(_EFFECTIVE_QUALIFIED_SOURCE)
    sidecar = interpreted_effective_calendar(row)
    sidecar["formulas"][0]["effective_from"][field] = value
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, sidecar)


def test_effective_calendar_rejects_repinned_source_canonical_and_condition_drift():
    row = effective_calendar_candidate(_EFFECTIVE_QUALIFIED_SOURCE)
    sidecar = interpreted_effective_calendar(row)
    different_source = deepcopy(row)
    different_source["source_text"] = row["source_text"].replace(_EFFECTIVE_DATE, "2000-02-28")
    different_source["source_sha256"] = hashlib.sha256(different_source["source_text"].encode()).hexdigest()
    with pytest.raises(ValueError):
        calendar.interpretation_skeleton(different_source)

    different_canonical = deepcopy(row)
    different_canonical["canonical_ir"]["rules"][0]["conditions"] = ["other request"]
    with pytest.raises(ValueError):
        calendar.interpretation_skeleton(different_canonical)

    omitted_start = deepcopy(row)
    omitted_start["canonical_ir"]["rules"][0]["temporal"] = [_DEADLINE_LITERAL]
    with pytest.raises(ValueError):
        calendar.interpretation_skeleton(omitted_start)

    different_typed_wire = deepcopy(sidecar)
    different_typed_wire["typed_source_ir_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, different_typed_wire)

    different_condition = deepcopy(sidecar)
    different_condition["formulas"][0]["conditions"][0]["source_text"] = "other request"
    with pytest.raises(ValueError):
        calendar.prepare_canonical_qualified(row, different_condition)


@pytest.mark.parametrize(
    "clauses",
    [
        pytest.param('Temporal: "effective from 2000-02-29".', id="opaque-start"),
        pytest.param('Conditions: "effective from 2000-02-29". ' + _EFFECTIVE_TEMPORAL, id="opaque-condition"),
        pytest.param('Exceptions: "effective from 2000-02-29". ' + _EFFECTIVE_TEMPORAL, id="opaque-exception"),
        pytest.param("Temporal: effective from 1900-02-29.", id="invalid-leap-day"),
        pytest.param("Temporal: effective from next Tuesday.", id="inferred-date"),
        pytest.param('Temporal: effective from 2000-02-29; "within 10 days".', id="relative-window"),
        pytest.param('Temporal: effective from 2000-02-29; "before tomorrow".', id="relative-deadline"),
        pytest.param('Temporal: effective from 2000-02-29; "on or before 2000-03-01".', id="unsupported-calendar"),
        pytest.param('Scope: "federal". ' + _EFFECTIVE_TEMPORAL, id="omitted-scope"),
    ],
)
def test_effective_calendar_refuses_unsupported_source_qualifiers(clauses):
    with pytest.raises(ValueError):
        effective_calendar_candidate(_EFFECTIVE_NORM + " " + clauses)


def test_effective_calendar_rejects_source_over_existing_byte_bound():
    source = _EFFECTIVE_SOURCE + (" " * previous.MAX_SOURCE_BYTES)
    with pytest.raises(ValueError):
        effective_calendar_candidate(source)


def test_effective_calendar_gate_replays_mixed_profiles_and_requires_complete_input():
    effective = effective_calendar_candidate()
    legacy = candidate()
    rows = [
        {"candidate": effective, "interpretation": interpreted_effective_calendar(effective)},
        {"candidate": legacy, "interpretation": interpreted(legacy)},
    ]
    toolchain = "leanprover/lean4:v4.34.1"
    preparation = gate.prepare_qualified_legal(rows, toolchain=toolchain)
    manifest = preparation.to_dict()
    assert manifest["status"] == "prepared"
    assert manifest["backend_executed"] is False
    assert {row["profile"] for row in manifest["candidates"]} == {calendar.EFFECTIVE_PROFILE, calendar.PROFILE}
    assert "deontic/" + calendar.EFFECTIVE_PROFILE in manifest["supported_family_profiles"]
    bridge_pins = calendar.prepare_canonical_qualified(effective, rows[0]["interpretation"])["producer_pins"]
    logic = Path(calendar.__file__).resolve().parents[1]
    typed_replay_paths = {
        str((logic / relative).resolve())
        for relative in (
            "legal_ir/extended_compiler.py",
            "legal_ir/extended_contracts.py",
            "legal_ir/extended_decompiler.py",
            "TDFOL/compiler_repairs.py",
        )
    }
    assert typed_replay_paths <= bridge_pins.keys()
    for path, digest in bridge_pins.items():
        assert manifest["producer_pins"][path] == digest

    legacy_preparation = gate.prepare_qualified_legal(rows[1:], toolchain=toolchain)
    legacy_manifest = legacy_preparation.to_dict()
    assert legacy_manifest["status"] == "prepared"
    assert legacy_manifest["producer_pins"] == gate._IMPORTED_PINS
    assert typed_replay_paths.isdisjoint(legacy_manifest["producer_pins"])
    assert {row["module"] for row in manifest["candidates"]} == {
        "LegalCalendar.Candidate0000", "LegalCalendar.Candidate0001"
    }
    gate.validate_preparation(preparation)

    incomplete_files = replace(
        preparation,
        files=tuple((name, body) for name, body in preparation.files if name != "LegalCalendar/Candidate0000.lean"),
    )
    with pytest.raises(ValueError, match="coverage changed"):
        gate.validate_preparation(incomplete_files)

    incomplete_rows = deepcopy(rows)
    incomplete_rows[0]["interpretation"]["formulas"][0]["effective_from"] = None
    blocked = gate.prepare_qualified_legal(incomplete_rows, toolchain=toolchain)
    assert blocked.to_dict()["status"] == "blocked"
    assert all(not name.endswith(".lean") for name, _ in blocked.files)
    gate.validate_preparation(blocked)


_EFFECTIVE_LEAN_WITNESSES = '''
def toyDayBack (p : String → Nat → Prop) : Interpretation Unit Unit :=
  { toy p with modal := fun _ _ _ body t => body (t - 1) }

def toyDayForward (p : String → Nat → Prop) : Interpretation Unit Unit :=
  { toy p with modal := fun _ _ _ body t => body (t + 1) }

example : EffectiveCalendar.effectiveFromActive_0 730179 := by unfold EffectiveCalendar.effectiveFromActive_0; decide
example : ¬ EffectiveCalendar.effectiveFromActive_0 730178 := by unfold EffectiveCalendar.effectiveFromActive_0; decide
example : ¬ EffectiveCalendar.effectiveFromActive_0 0 := by unfold EffectiveCalendar.effectiveFromActive_0; decide

-- The caller origin activates the rule on February 29.
example : EffectiveCalendar.qualifiedLegalFormula_0 (toy (fun _ t => t = 730179)) 730179 := by
  refine ⟨by decide, ?_⟩
  intro _
  exact ⟨by decide, 730179, by decide, by decide, rfl⟩

-- An active rule requires a witness strictly before March 1.
example : ¬ EffectiveCalendar.qualifiedLegalFormula_0 (toy (fun _ _ => True)) 730180 := by
  intro h
  have active : EffectiveCalendar.effectiveFromActive_0 730180 := by unfold EffectiveCalendar.effectiveFromActive_0; decide
  obtain ⟨_, u, lower, upper, _⟩ := h.2 active
  exact (Nat.not_lt_of_ge lower) upper

-- Before the start, shifting the modality forward cannot activate the outer rule.
example : EffectiveCalendar.qualifiedLegalFormula_0 (toyDayForward (fun _ _ => False)) 730178 := by
  refine ⟨by decide, ?_⟩
  intro h
  exact False.elim ((by decide : ¬ (730179 ≤ 730178)) h.2)

-- With an active caller origin, a shifted modality still needs its payload.
example : ¬ EffectiveCalendar.qualifiedLegalFormula_0 (toyDayBack (fun _ _ => False)) 730179 := by
  intro h
  have active : EffectiveCalendar.effectiveFromActive_0 730179 := by unfold EffectiveCalendar.effectiveFromActive_0; decide
  obtain ⟨_, _, _, _, value⟩ := h.2 active
  exact value

-- Its inner interval uses the shifted origin; the old witness bounds are preserved.
example : EffectiveCalendar.qualifiedLegalFormula_0 (toyDayBack (fun _ t => t = 730178)) 730179 := by
  refine ⟨by decide, ?_⟩
  intro _
  exact ⟨by decide, 730178, by decide, by decide, rfl⟩

example : ¬ EffectiveCalendar.qualifiedLegalFormula_0 (toy (fun _ _ => True)) 0 := by
  intro h
  exact (by decide : ¬ (1 ≤ 0)) h.1
'''

_EFFECTIVE_FALSE_CLAIM = '''
-- FalseEffectiveDateClaim
theorem falseEffectiveDateClaim : EffectiveCalendar.effectiveFromActive_0 730178 := by unfold EffectiveCalendar.effectiveFromActive_0; decide
'''


def effective_semantic_source():
    row = effective_calendar_candidate()
    body = calendar.prepare_canonical_qualified(row, interpreted_effective_calendar(row))["lean_body"]
    return "\n".join([
        emitters.PRELUDE,
        TOY,
        "namespace EffectiveCalendar\n" + body + "\nend EffectiveCalendar",
        _EFFECTIVE_LEAN_WITNESSES,
    ])


def effective_semantic_false_claim_source():
    return effective_semantic_source() + _EFFECTIVE_FALSE_CLAIM


def test_real_lake_effective_date_inclusive_start_and_outer_modal_guard(tmp_path):
    result = run_lake(tmp_path, effective_semantic_source())
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_lake_refuses_false_effective_date_at_preceding_ordinal(tmp_path):
    source = effective_semantic_false_claim_source()
    claim_line = next(
        number for number, line in enumerate(source.splitlines(), 1)
        if line.startswith("theorem falseEffectiveDateClaim ")
    )
    result = run_lake(tmp_path, source)
    diagnostics = result.stdout + result.stderr
    assert result.returncode != 0
    assert "error:" in diagnostics
    assert f"CalendarWitness.lean:{claim_line}:" in diagnostics
