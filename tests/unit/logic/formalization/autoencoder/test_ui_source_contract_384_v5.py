"""Bounded explicit EC effects, signed unknowns, clocks and exact replay."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v4 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_bounded_event_calculus as owner


def cases():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_bounded_event_v1/cases.py"
    spec = importlib.util.spec_from_file_location("bounded_ui_ec_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def prepare(row): return subject.prepare_family_targets(row["source_text"], row["candidate"], **row["options"])


def payload(result): return next(p["payload"] for p in result["report"]["projections"] if p["projection_id"] == owner.PROJECTION_ID)


@pytest.mark.parametrize("index,values", [(0, [["open"]]*4), (1, [["open"], ["open"], ["closed"], ["closed"]]),
    (2, [["open"]]*3)])
def test_signed_occurrences_effects_and_inertia_are_exact(index, values):
    row = cases()[index]
    result = prepare(row)
    data = payload(result)
    assert data["fluent_values"] == values
    assert data["origin"] == 10 and data["resolution"] == 2
    assert data["clock"]["unit"] == "logical_tick" and data["clock"]["epoch"] == "explicit-fixture-epoch"
    assert len(data["effect_table"]) == len(data["occurrences"]) * 2
    assert len(result["report"]["requested_families"]) == 40
    assert result["audit"]["available_families"] == ["event_calculus", "first_order", "frame_logic", "transition_system"]
    assert len(result["audit"]["missing_requested_families"]) == 36
    assert subject.validate_prepared(result, row["source_text"], row["candidate"], **row["options"])


def test_full_original_failure_is_archived_and_only_exact_ec_row_replaced():
    row = cases()[0]
    base = previous.prepare_family_targets(row["source_text"], row["candidate"],
        **{k:v for k,v in row["options"].items() if k != "event_interpretation"})
    result = prepare(row)
    old = next(p for p in base["report"]["projections"] if p["projection_id"] == "ui_ux_ir:event_calculus")
    archived, = result["report"]["superseded_bounded_event_observations"]
    assert all(archived[k] == v for k,v in old.items())
    assert archived["original_row_sha256"] == owner.digest(old)
    assert archived["active_for_training"] is False
    assert archived["replacement_projection_id"] == owner.PROJECTION_ID
    assert not any(p["projection_id"] == old["projection_id"] for p in result["report"]["projections"])
    assert len(base["report"]["projections"]) == len(result["report"]["projections"])
    assert result["report"]["frontier"] == base["report"]["frontier"]


def test_no_event_declaration_returns_v4_identically():
    row = cases()[0]
    options = {k:v for k,v in row["options"].items() if k != "event_interpretation"}
    assert subject.prepare_family_targets(row["source_text"], row["candidate"], **options) == previous.prepare_family_targets(
        row["source_text"], row["candidate"], **options)


@pytest.mark.parametrize("index,reason", [(3,"unknown or extra"), (4,"false guard or wrong source"),
    (5,"false guard or wrong source"), (6,"self-loop"), (7,"one explicit clock"), (8,"clock semantics")])
def test_unsupported_or_contradictory_prefixes_stay_blocked(index, reason):
    row = cases()[index]
    with pytest.raises(ValueError, match=reason): prepare(row)
    failure = subject.qualify_source_candidate(row["source_text"], row["candidate"], **row["options"])
    assert failure["status"] == "invalid_or_missing_context"
    assert failure["candidate"] == row["candidate"] and failure["admitted"] is False


def test_native_operator_roles_time_binding_polarity_and_effect_laws_are_present():
    data = payload(prepare(cases()[1]))
    formulas = data["native_ec_formulas"]
    assert all(r["parse_print_parse_exact"] for r in formulas)
    assert all(r["native_constant_sort"] == "Object" for r in formulas)
    assert any(r["formula"].startswith("forall t:Time.") and "initiates(" in r["formula"] for r in formulas)
    assert any(r["formula"].startswith("forall t:Time.") and "terminates(" in r["formula"] for r in formulas)
    assert any(r["formula"].startswith("not happens(") for r in formulas)
    assert any(r["formula"].startswith("not holds_at(") for r in formulas)
    with pytest.raises(ValueError, match="AST/operator/argument/Time"):
        owner._parsed("happens(e_test, 10)", ["ec", "happens", ["constant", "different"], ["time",10]])


def test_new_ec_and_preserved_guard_emitters_require_complete_report_replay():
    result = prepare(cases()[1])
    for row in result["report"]["projections"]:
        if not row["projection_id"].startswith(owner.guards.PREFIX): continue
        source, check = owner.emit_projection(row, report=result["report"])
        if row["projection_id"] == owner.PROJECTION_ID:
            assert "successor_inertia" in source and "= none := by decide" in source
            assert check["capability_floor_eligible"] is True
            assert check["event_authenticity_verified"] is False
            assert {"Happens","HoldsAt","Initiates","Terminates"} <= set(check["operators"])
        else:
            assert check["preserved_v4_report_sha256"] == result["report"]["v4_report_sha256"]
            assert check["preserved_payload_sha256"] == owner.digest(row["payload"])
    row = next(p for p in result["report"]["projections"] if p["projection_id"] == owner.PROJECTION_ID)
    with pytest.raises(ValueError, match="exact live"): owner.emit_projection(row)


def change(row, mutate):
    row = deepcopy(row)
    declaration = row["options"]["event_interpretation"].to_dict()
    mutate(declaration)
    # Exercise the semantic guard with an internally consistent native trace;
    # stale trace identities are already rejected by TraceIR itself.
    trace = dict(declaration["trace"])
    trace.pop("trace_id", None)
    declaration["trace"] = owner.trace.TraceIR.from_dict(trace).to_dict()
    row["options"]["event_interpretation"] = subject.UIBoundedECInterpretation.from_dict(declaration)
    return row


@pytest.mark.parametrize("mutate,reason", [
    (lambda d:d.update(origin=True), "explicit nonnegative"),
    (lambda d:d["policy"].update(effect_timing="same_tick"), "complete explicit"),
    (lambda d:d.update(candidate_sha256="0"*64), "binding differs"),
    (lambda d:d.update(initial_true_fluents=["closed"]), "initial fluents differ"),
    (lambda d:d.update(origin=12), "exact origin"),
    (lambda d:d["trace"]["clocks"][0].update(epoch=""), "nonempty clock epoch"),
])
def test_caller_policy_initial_values_and_exact_source_join_are_required(mutate, reason):
    with pytest.raises(ValueError, match=reason): prepare(change(cases()[0], mutate))


def test_rehashed_modified_trace_values_do_not_override_source_replay():
    result = prepare(cases()[1])
    report = deepcopy(result["report"])
    row = next(p for p in report["projections"] if p["projection_id"] == owner.PROJECTION_ID)
    row["payload"]["fluent_values"][2] = ["open"]
    row["target_sha256"] = owner.digest({k:v for k,v in row.items() if k != "target_sha256"})
    report["report_sha256"] = owner.digest({k:v for k,v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="complete bounded EC source replay"):
        owner.emit_projection(row, report=report)


def test_unknowns_are_not_materialized_as_false_native_facts_outside_prefix():
    data = payload(prepare(cases()[1]))
    occurrences = [r for r in data["native_ec_formulas"] if "happens(" in r["formula"]]
    holds = [r for r in data["native_ec_formulas"] if r["formula"].startswith(("holds_at(", "not holds_at("))]
    assert all(", 16)" not in r["formula"] for r in occurrences)
    assert any(", 16)" in r["formula"] for r in holds)
    assert all(", 18)" not in r["formula"] for r in holds)


def test_rehashed_archived_failure_tamper_is_rejected_on_exact_replay():
    result = prepare(cases()[0])
    report = deepcopy(result["report"])
    report["superseded_bounded_event_observations"][0]["validation"] = []
    report["report_sha256"] = owner.digest({k:v for k,v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="complete bounded EC source replay"):
        subject.validate_family_training_report(report, **result["source_inputs"])
