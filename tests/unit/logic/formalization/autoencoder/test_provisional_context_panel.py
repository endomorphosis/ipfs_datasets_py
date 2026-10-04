"""Explicit companion premises never rewrite the unresolved source controls."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import provisional_context_panel as panel
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as lake
from ipfs_datasets_py.logic.formalization.autoencoder import projection_context_audit as audit
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v5 as policy


@pytest.fixture(scope="module")
def cases():
    return {domain: panel.prepare_companion(domain) for domain in panel.DOMAINS}


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_original_is_exact_negative_and_companion_has_new_identity(cases, domain):
    case = cases[domain]
    fixture = case["fixture"]
    assert fixture["original_source_id"] == domain + ":pair:0:2:0"
    assert fixture["companion_source_id"] != fixture["original_source_id"]
    assert fixture["companion_source_digest"] != fixture["original_source_digest"]
    assert fixture["original_input_payload_sha256"] == panel._digest(fixture["original_input_payload"])
    assert fixture["companion_input_payload_sha256"] == panel._digest(fixture["companion_input_payload"])
    assert fixture["original_report_sha256"] == case["original_report"]["report_sha256"]
    assert fixture["assumptions_sha256"] == panel._digest(fixture["assumptions"])
    assert fixture["fixture_sha256"] == panel._digest({k: v for k, v in fixture.items() if k != "fixture_sha256"})
    original = lake.prepare_native_family_lean(case["original_report"], source_inputs=case["original_source_inputs"])
    assert {p["projection_id"]: p["reason"] for p in original["per_projection"] if not p["semantic_lowering_supported"]} == audit.BLOCKERS[domain]


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_companions_cover_every_lowering_but_issue_no_lake_authority(cases, domain):
    case = cases[domain]
    prepared = lake.prepare_native_family_lean(case["report"], source_inputs=case["source_inputs"])
    assert all(p["semantic_lowering_supported"] for p in prepared["per_projection"])
    assert prepared["backend_executed"] is False
    assert all(p["lake_status"] == "not_run" and p["admitted"] is False for p in prepared["per_projection"])
    assert {p["projection_id"] for p in prepared["per_projection"]} == {p["projection_id"] for p in case["report"]["projections"]}
    assert len(case["report"]["projections"]) == len(case["original_report"]["projections"]) == (11 if domain == "legal_ir" else 16)
    assert len(case["report"]["requested_families"]) == len(case["report"]["family_inventory"]) == 40
    assert {domain + "/native_formula/" + name + "/v3" for name in audit.FORMULAS} <= {p["projection_id"] for p in prepared["per_projection"]}


def test_legal_provisional_origin_is_abstract_and_temporal_view_is_not_a_fact(cases):
    case = cases["legal_ir"]
    fixture = case["fixture"]
    assert fixture["original_input_payload"]["source_text"] == "custodian must publish record within 10 days."
    assert fixture["assumptions"]["deadline_origin"] == "caller_supplied_evaluation_origin"
    assert fixture["assumptions"]["concrete_origin_or_event_trace_supplied"] is False
    relation = fixture["legal_auxiliary_view_relation"]
    assert relation["independent_event_fact"] is relation["typed_AST_containment_verified"] is False
    assert relation["norm_projection_id"] in {p["projection_id"] for p in case["report"]["projections"]}
    assert relation["body_projection_id"] in {p["projection_id"] for p in case["report"]["projections"]}
    assert len(fixture["explicit_interpretations"]) == 2
    for declaration in fixture["explicit_interpretations"]:
        formula, = declaration["formulas"]
        assert formula["conditions"] == formula["exceptions"] == []
        assert formula["temporal"]["source_index"] == 0
        assert formula["temporal"]["origin"] == "caller_supplied_evaluation_time"
        assert formula["temporal"]["quantity"] == 10


def test_ui_fixture_preserves_activation_without_inventing_invocation(cases):
    case = cases["ui_ux_ir"]
    old = case["fixture"]["original_input_payload"]["ui_training_row"]
    new = case["source_inputs"]["ui_training_row"]
    assert new["events"] == old["events"]
    assert [e["kind"] for e in new["events"]] == ["activate"]
    assert new["bindings"] == old["bindings"]
    assert new["behavior"] == old["behavior"]
    assert new["provenance"]["group_id"] == old["provenance"]["group_id"]
    assert new["provenance"]["split"] == old["provenance"]["split"]
    assert case["fixture"]["assumptions"]["request_token_trace_supplied"] is False
    declarations = case["fixture"]["explicit_interpretations"][0]["formulas"]
    assert len(declarations) == 3
    assert [d["max_age_ticks"] for d in declarations[:2]] == [10, 10]
    assert declarations[-1]["kind"] == "atomic_UI_norm"


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_interpretations_do_not_waive_floors_or_reviews(cases, domain):
    case = cases[domain]
    observation = policy.validate_projection_report(case["report"])
    batch = policy.evaluate_projection_training_batch([observation], domain_id=domain)
    assert batch["strict_training_allowed"] is False
    assert observation.to_dict()["family_blockers"]
    assert all(case["fixture"][field] is False for field in panel.FALSE)
    assert case["fixture"]["capability_floor_credit_from_interpretations"] is False
    prepared = lake.prepare_native_family_lean(case["report"], source_inputs=case["source_inputs"])
    interpreted = [p for p in prepared["per_projection"] if "/explicit-legal-interpretation/" in p["projection_id"]
                   or "/request-token-confirmation/" in p["projection_id"]]
    assert len(interpreted) == len(audit.BLOCKERS[domain])
    assert all(p["lowering"]["capability_floor_eligible"] is False for p in interpreted)


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_missing_interpretations_cannot_replay_supported_report(cases, domain):
    case = cases[domain]
    inputs = dict(case["source_inputs"])
    inputs.pop("legal_qualifier_inputs" if domain == "legal_ir" else "ui_confirmation_inputs")
    with pytest.raises(ValueError):
        lake.prepare_native_family_lean(case["report"], source_inputs=inputs)


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_changed_source_cannot_reuse_companion(cases, domain):
    case = cases[domain]
    inputs = dict(case["source_inputs"])
    if domain == "legal_ir":
        inputs["source_text"] += " another premise"
    else:
        inputs["ui_training_row"] = deepcopy(inputs["ui_training_row"])
        inputs["ui_training_row"]["bindings"][0]["confirmation_class"] = "double_confirm"
    with pytest.raises(ValueError):
        lake.prepare_native_family_lean(case["report"], source_inputs=inputs)


def test_mutating_returned_case_does_not_change_original_fixture(cases):
    case = panel.prepare_companion("ui_ux_ir")
    case["source_inputs"]["ui_training_row"]["events"].clear()
    assert len(cases["ui_ux_ir"]["original_source_inputs"]["ui_training_row"]["events"]) == 1
    assert len(panel.prepare_companion("ui_ux_ir")["source_inputs"]["ui_training_row"]["events"]) == 1


def test_unknown_domain_fails_closed():
    with pytest.raises(ValueError, match="closed Legal/UI"):
        panel.prepare_companion("security_ir")


def test_smoke_counts_failed_executions_separately_from_success():
    from scripts.ops.autoencoder.smoke_provisional_context_fixtures import _lake_counts
    assert _lake_counts([{"backend_executed": True, "status": "passed"},
        {"backend_executed": True, "status": "failed"},
        {"backend_executed": False, "status": "unavailable"},
        {"backend_executed": False, "status": "passed"}]) == {
            "actual_lake_build_count": 2, "successful_lake_build_count": 1}


def test_smoke_refuses_script_tool_before_native_execution(tmp_path):
    from scripts.ops.autoencoder.smoke_provisional_context_fixtures import _tool_pins
    fake = tmp_path / "lake"
    fake.write_text("#!/bin/sh\nprintf fake\n")
    fake.chmod(0o755)
    (tmp_path / "lean").write_bytes(b"\x7fELF" + b"test")
    with pytest.raises(ValueError, match="native executable required"):
        _tool_pins(str(fake), None, None)
