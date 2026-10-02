"""Native UI temporal semantics preserve known prefix, unknown future and norms."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_temporal_logic as owner
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_bounded_event_calculus as ec
from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_source_fidelity as source_wire
from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as adapter


def fixture():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_modal_logic_v1/temporal_cases.py"
    spec = importlib.util.spec_from_file_location("ui_temporal_unit_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def data(row, requirement="TFOL"):
    source = json.loads(row["source_text"])
    native = {"kind": "document", "document": row["candidate"]["document"]}
    options = source_wire._bound_options(row["source_text"], native, source["interpretations"])
    prepared = ec.prepare_payload(row["source_text"], native, **options)
    key = "temporal" if requirement == "TFOL" else "tdfol"
    return owner.prepare_payload(row["source_text"], row["candidate"], ec_payload=prepared,
        descriptor=row["candidate"]["logic"][key], requirement_id=requirement)


def changed(mutate):
    row = fixture().make_case()
    mutate(row["candidate"])
    source = json.loads(row["source_text"])
    source["candidate"] = deepcopy(row["candidate"])
    row["source_text"] = json.dumps(source, sort_keys=True, separators=(",", ":"))
    return row


@pytest.mark.parametrize("requirement", ["TFOL", "TDFOL"])
def test_exact_native_operators_and_UI_state_values_lower_without_asserting_truth(requirement):
    row = fixture().make_case()
    before = deepcopy(row)
    payload = data(row, requirement)
    assert row == before and payload["candidate"] == row["candidate"]
    assert payload["known_state_indices"] == [payload["states"].index(s) for s in ("open", "open", "closed", "closed")]
    assert payload["known_state_step_count"] == 4
    assert payload["origin"] == 10 and payload["resolution"] == 2
    assert payload["clock"]["unit"] == "logical_tick" and payload["clock"]["epoch"] == "explicit-fixture-epoch"
    assert payload["time_semantics"]["unobserved_future"] == "arbitrary_extension_over_declared_control_states"
    for record in payload["formulas"]:
        assert record["native_parse_print_parse_exact"] and record["operator_counts"]["temporal"] > 0
        assert bool(record["operator_counts"]["deontic"]) == (requirement == "TDFOL")
        assert record["referenced_state_symbols"]
    code = owner._lean(payload)
    assert "namespace UITemporalEC" in code and "theorem successor_inertia" in code
    assert "(uiTemporalKnownStates[step]?).getD (future step)" in code
    assert "UITemporalEC.holdsAt (uiTemporalStateIdentity (uiTemporalStateAt future 2)) (uiTemporalPhysicalTick 2) = some true := by\n  change UITemporalEC.holdsAt \"closed\" 14 = some true\n  decide" in code
    assert "some (decide (uiTemporalStateAt future 2 = .s0)) := by\n  change UITemporalEC.holdsAt" in code
    assert "uiTemporalStateAt future 4 = future 4 := by rfl" in code
    assert "uiTemporalStateAt future 5 = future 5 := by rfl" in code
    assert "uiTemporalPhysicalTick 3 = 16 := by decide" in code
    assert "alwaysTime" in code and "eventuallyTime" in code
    if requirement == "TDFOL":
        assert all('i.modal "deontic:' + op + '"' in code for op in ("O", "P", "F"))
    assert all(payload[key] is False for key in ("source_semantics_verified", "event_authenticity_verified",
        "formula_truth_proven", "actor_duties_inferred", "actual_runtime_execution", "admitted", "qualified"))


def test_temporal_until_and_boolean_operators_keep_native_scope():
    left, right = owner.state_symbol("open"), owner.state_symbol("closed")
    text = "((not UIState(" + left + ")) U (UIState(" + right + ") or UIState(" + left + ")))"
    row = changed(lambda c: c["logic"]["temporal"].update(formulas=[{"formula_id": "until", "formula": text}]))
    payload = data(row)
    code = owner._lean(payload)
    assert "untilTime" in code and "¬" in code and "∨" in code
    assert payload["formulas"][0]["operator_counts"]["deontic"] == 0


@pytest.mark.parametrize("index", range(3, 8))
def test_source_and_semantics_negative_fixtures_fail_closed(index):
    row = fixture().cases()[index]
    with pytest.raises(ValueError, match=row["expected_reason"]):
        adapter.prepare_family_targets(row["source_text"], row["candidate"])


@pytest.mark.parametrize("mutate,reason", [
    (lambda d: d["time_semantics"].update(known_state_steps="unknown_is_false"), "arbitrary-continuation"),
    (lambda d: d.update(deontic_semantics="norms_proven_true"), "state-norm parameter"),
    (lambda d: d["state_bindings"].append(deepcopy(d["state_bindings"][0])), "duplicate state"),
    (lambda d: d["state_bindings"][0].update(symbol="ui_state:alias"), "preserve exact"),
    (lambda d: d["formulas"].append(deepcopy(d["formulas"][0])), "unique formula"),
    (lambda d: d.update(formulas=[]), "one to eight"),
    (lambda d: d.update(extra="ignored"), "complete explicit"),
    (lambda d: d["formulas"][0].update(formula="UIState(" + owner.state_symbol("open") + ")"), "actual operators"),
    (lambda d: d["formulas"][0].update(formula="G(UIState(Unbound))"), "ground UI state"),
])
def test_strict_descriptor_semantics_and_native_operator_bindings(mutate, reason):
    row = changed(lambda c: mutate(c["logic"]["temporal"]))
    with pytest.raises(ValueError, match=reason): data(row)


def test_unused_explicit_binding_cannot_be_silently_discarded():
    row = changed(lambda c: c["logic"]["temporal"]["formulas"].pop())
    with pytest.raises(ValueError, match="all supplied state bindings"): data(row)


def test_complete_ec_payload_must_replay_including_known_future_boundary():
    row = fixture().make_case()
    payload = data(row)
    wrong = deepcopy(payload["ec_payload"])
    wrong["fluent_values"][2] = ["open"]
    with pytest.raises(ValueError, match="complete bounded EC replay"):
        owner.prepare_payload(row["source_text"], row["candidate"], ec_payload=wrong,
            descriptor=row["candidate"]["logic"]["temporal"], requirement_id="TFOL")


def test_source_only_formula_never_becomes_candidate_coverage():
    row = fixture().make_case()
    payload = data(row)
    row["candidate"]["logic"]["temporal"]["formulas"][0]["formula"] = "X(UIState(" + owner.state_symbol("open") + "))"
    with pytest.raises(ValueError, match="source/candidate logic"):
        owner.prepare_payload(row["source_text"], row["candidate"], ec_payload=payload["ec_payload"],
            descriptor=row["candidate"]["logic"]["temporal"], requirement_id="TFOL")


def test_detached_owned_projection_fails_without_semantic_fallback():
    with pytest.raises(ValueError, match="exact complete"):
        owner.emit_projection({"projection_id": owner.PROJECTION_IDS["TFOL"], "logic_family": "temporal",
                               "profile": owner.PROFILES["TFOL"]})
    with pytest.raises(NotImplementedError): owner.emit_projection({"projection_id": "unrelated"})


def test_report_emitter_replays_whole_source_and_keeps_all_old_EC_rows():
    row = fixture().make_case()
    prepared = adapter.prepare_family_targets(row["source_text"], row["candidate"])
    report = prepared["report"]
    assert len(report["requested_families"]) == 40 and not report["all_requested_families_available"]
    assert {p["projection_id"] for p in report["base_ui_report"]["projections"]} <= {
        p["projection_id"] for p in report["projections"]}
    for target in report["projections"]:
        if target["projection_id"] not in owner.PROJECTION_IDS.values(): continue
        code, lowering = owner.emit_projection(target, report=report)
        assert "uiTemporalStateAt" in code and lowering["capability_floor_eligible"] is True
        assert lowering["formula_truth_proven"] is False
    broken = deepcopy(report)
    broken["declared_logic_source_binding"]["candidate"]["logic"]["temporal"]["formulas"][0]["formula"] = "different"
    broken["report_sha256"] = owner.digest({k: v for k, v in broken.items() if k != "report_sha256"})
    target = next(p for p in broken["projections"] if p["projection_id"] == owner.PROJECTION_IDS["TFOL"])
    with pytest.raises(ValueError): owner.emit_projection(target, report=broken)


def test_unknown_interpretation_body_fields_are_not_ignored_by_direct_owner():
    row = fixture().make_case()
    source = json.loads(row["source_text"])
    source["interpretations"]["ignored_policy"] = {"semantics": "unmodeled"}
    row["source_text"] = json.dumps(source, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="complete explicit UI logic interpretation bodies"):
        data(row)


def test_free_future_EC_bridge_goals_reduce_to_closed_facts_before_decide():
    payload = data(fixture().make_case())
    code = owner._lean(payload)
    blocks = [block for block in code.split("example (future : Nat → UITemporalState) : ")[1:]
              if block.startswith("UITemporalEC.holdsAt")]
    assert len(blocks) == len(payload["known_state_indices"]) * (len(payload["states"]) + 1)
    for block in blocks:
        statement, proof = block.split(":= by", 1)
        assert "future" in statement
        lines = proof.splitlines()
        assert lines[1].startswith("  change UITemporalEC.holdsAt ")
        assert "future" not in lines[1] and "uiTemporalState" not in lines[1]
        assert lines[2] == "  decide"
    assert 'change UITemporalEC.holdsAt "open" 14 = some false\n  decide' in code
    assert 'change UITemporalEC.holdsAt "closed" 14 = some true\n  decide' in code
    assert "uiTemporalStateAt future 4 = future 4 := by rfl" in code
