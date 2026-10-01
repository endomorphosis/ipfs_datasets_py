"""Gate-policy unit tests with an explicit fake issuer, not Lake evidence.

The real native issuer owns live execution and formula-lowering tests. These
unit tests isolate per-projection accounting, exact floors and fail-closed
training handoff; no fake receipt is published as an actual Lake result.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract as api

NAMED = [
    {"requirement_id": name, "family_id": family, "profile": profile}
    for name, family, profile in (
        ("FOL", "first_order", "first_order"), ("DFOL", "deontic", "deontic_first_order"),
        ("TFOL", "temporal", "temporal_first_order"), ("TDFOL", "tdfol", "deontic_temporal_first_order"),
        ("CEC", "event_calculus", "cognitive_event_calculus"),
        ("DCEC", "dcec", "deontic_cognitive_event_calculus"),
        ("frame_logic", "frame_logic", "flogic"), ("propositional", "propositional", "propositional"))]


class _FakeExecution:
    """Local dependency double; never passed to the actual native verifier."""
    def __init__(self, report):
        self.digest = api._sha(report)
        self.valid = True
        self.rows = [{"projection_id": row["projection_id"], "logic_family": row["logic_family"],
            "profile": row["profile"], "payload_sha256": api._sha(row["payload"]),
            "source_digest": report["source_digest"], "parser_status": "passed",
            "lake_status": "passed", "semantic_lowering_supported": True} for row in report["projections"]]


@pytest.fixture(autouse=True)
def fake_native_dependencies(monkeypatch):
    def validate(report):
        assert report["fixture_scope"] == "policy_accounting_unit_test_not_native_formula_evidence"
    def verify(execution, report):
        if (type(execution) is not _FakeExecution or not execution.valid or execution.digest != api._sha(report)):
            raise ValueError("issuer requires exact live execution; JSON and schema receipts rejected")
        return {"per_projection": deepcopy(execution.rows)}
    monkeypatch.setattr(api, "_validate_report", validate)
    monkeypatch.setattr(api, "_verify_execution", verify)
    monkeypatch.setattr(api, "_formula_floor", lambda: deepcopy(NAMED))


def _report(domain="security_ir", *, identity="one", floors=None):
    policy = api.domain_projection_policy(domain)
    rows = floors if floors is not None else policy["minimum_batch_floor"]
    targets = []
    for index, floor in enumerate(rows):
        name = (domain + "/native_formula/" + floor["requirement_id"] + "/v3" if domain == "legal_ir"
                else domain + "/fixture/" + str(index))
        target = {"projection_id": name, "logic_family": floor["family_id"], "profile": floor["profile"],
            "payload": {"unit_fixture": index}, "ready_for_training": True}
        target["target_sha256"] = api._sha(target)
        targets.append(target)
    return {"domain_id": domain, "source_digest": api._sha(identity),
        "requested_families": policy["family_inventory"], "projections": targets,
        "fixture_scope": "policy_accounting_unit_test_not_native_formula_evidence"}


def _reviews(report):
    emitted = {row["logic_family"] for row in report["projections"]}
    return [{"family_id": family, "source_digest": report["source_digest"],
        "disposition": "inapplicable", "reason": "Authored policy fixture declares no model for this family.",
        "evidence_refs": ["unit-fixture:closed-model-scope"]}
        for family in api.domain_projection_policy(report["domain_id"])["family_inventory"] if family not in emitted]


def _observe(report, execution=None, reviews=None):
    return api.validate_projection_report(report,
        lake_execution=execution if execution is not None else _FakeExecution(report),
        applicability_review=_reviews(report) if reviews is None else reviews)


@pytest.mark.parametrize("domain", api.native.DOMAINS)
def test_catalog_and_floor_are_domain_owned_complete_and_copy_safe(domain):
    policy = api.domain_projection_policy(domain)
    assert len(policy["family_inventory"]) == 40
    assert not policy["narrow_request_can_complete"]
    assert not policy["inapplicability_can_waive_minimum_batch_floor"]
    if domain == "legal_ir": assert policy["minimum_batch_floor"] == NAMED
    else: assert {"requirement_id": "TLA+", "family_id": "transition_system", "profile": "tla_plus"} in policy["minimum_batch_floor"]
    policy["minimum_batch_floor"].clear()
    assert api.domain_projection_policy(domain)["minimum_batch_floor"]


@pytest.mark.parametrize("domain", api.native.DOMAINS)
def test_complete_gate_accounting_does_not_grant_semantic_qualification(domain):
    report = _report(domain)
    result = api.require_projection_training_batch([_observe(report)], domain_id=domain, target_reports=[report])
    assert result["strict_training_allowed"] and result["modality_floor_satisfied"]
    assert result["optimization_input_binding_checked"]
    assert all(result[key] is False for key in api._FALSE)


def test_each_projection_is_checked_even_when_another_in_same_family_passes():
    report = _report()
    duplicate = deepcopy(report["projections"][0])
    duplicate["projection_id"] += "/second"
    report["projections"].append(duplicate)
    execution = _FakeExecution(report)
    execution.rows.pop()
    observation = _observe(report, execution)
    assert not observation.to_dict()["all_emitted_projections_validated"]
    with pytest.raises(api.ProjectionValidationError) as caught:
        api.require_projection_training_batch([observation], domain_id="security_ir")
    assert caught.value.to_dict()["modality_floor_satisfied"]
    assert not caught.value.to_dict()["strict_training_allowed"]


@pytest.mark.parametrize("field,value,reason", [
    ("parser_status", "not_run", "native_parser_not_passed"),
    ("parser_status", None, "native_parser_not_passed"),
    ("lake_status", "failed", "actual_Lake_build_not_passed"),
    ("semantic_lowering_supported", False, "semantic_lowering_unsupported_or_partial"),
    ("semantic_lowering_supported", 1, "semantic_lowering_unsupported_or_partial"),
    ("payload_sha256", "0" * 64, "live_projection_binding_differs"),
    ("source_digest", "0" * 64, "live_projection_binding_differs"),
    ("logic_family", "first_order", "live_projection_binding_differs"),
    ("profile", "invented", "live_projection_binding_differs"),
])
def test_missing_parser_lake_or_exact_binding_blocks(field, value, reason):
    report = _report()
    execution = _FakeExecution(report)
    execution.rows[0][field] = value
    result = _observe(report, execution).to_dict()
    assert not result["source_projection_gate_passed"]
    assert reason in result["projection_observations"][0]["blocking_reasons"]


@pytest.mark.parametrize("execution", [None, {"lake_ok": True, "parser_status": "passed"}, object()])
def test_detached_success_flags_and_generic_objects_cannot_pass(execution):
    report = _report()
    result = api.validate_projection_report(report, lake_execution=execution,
        applicability_review=_reviews(report)).to_dict()
    assert not result["source_projection_gate_passed"] and not result["live_execution_verified"]


def test_narrow_selection_does_not_remove_coverage_requirement():
    report = _report()
    report["requested_families"] = sorted({row["logic_family"] for row in report["projections"]})
    result = _observe(report).to_dict()
    assert not result["source_projection_gate_passed"]
    assert any(row["reason"] == "narrowed_request_cannot_satisfy_complete_catalog_policy" for row in result["family_blockers"])


def test_missing_unrelated_family_is_needs_evidence_until_explicit_review():
    report = _report()
    missing_review = _reviews(report).pop()
    result = _observe(report, reviews=[row for row in _reviews(report) if row != missing_review]).to_dict()
    family = next(row for row in result["family_inventory"] if row["family_id"] == missing_review["family_id"])
    assert family["disposition"] == "needs_evidence" and not result["source_projection_gate_passed"]


def test_present_projection_cannot_be_declared_inapplicable():
    report = _report()
    review = {"family_id": "program", "source_digest": report["source_digest"],
        "disposition": "inapplicable", "reason": "Would erase an actual emitted target.", "evidence_refs": ["test"]}
    result = _observe(report, reviews=_reviews(report) + [review]).to_dict()
    assert not result["source_projection_gate_passed"]
    assert any(row["reason"] == "inapplicability_cannot_waive_existing_projection" for row in result["family_blockers"])


def test_source_inapplicability_cannot_waive_minimum_modality_floor():
    report = _report()
    report["projections"] = [row for row in report["projections"] if row["logic_family"] != "temporal"]
    observation = _observe(report)
    assert observation.to_dict()["source_projection_gate_passed"]
    result = api.evaluate_projection_training_batch([observation], domain_id="security_ir")
    assert not result["strict_training_allowed"]
    assert [row["requirement_id"] for row in result["required_floor"] if not row["satisfied"]] == ["temporal"]


def test_modality_floor_may_be_distributed_across_distinct_sources():
    floor = api.domain_projection_policy("security_ir")["minimum_batch_floor"]
    first = _report(identity="one", floors=floor[:2])
    second = _report(identity="two", floors=floor[2:])
    result = api.require_projection_training_batch([_observe(first), _observe(second)], domain_id="security_ir")
    assert result["strict_training_allowed"]


def test_named_legal_route_requires_exact_target_identity_not_profile_label():
    report = _report("legal_ir")
    report["projections"][1]["projection_id"] = "legal_ir/generic/deontic_formula"
    result = api.evaluate_projection_training_batch([_observe(report)], domain_id="legal_ir")
    assert not result["strict_training_allowed"]
    assert [row["requirement_id"] for row in result["required_floor"] if not row["satisfied"]] == ["DFOL"]


@pytest.mark.parametrize("change", ["source", "no_refs", "extra", "duplicate"])
def test_applicability_reviews_are_bounded_source_bound_and_closed(change):
    report = _report()
    reviews = _reviews(report)
    if change == "source": reviews[0]["source_digest"] = "0" * 64
    elif change == "no_refs": reviews[0]["evidence_refs"] = []
    elif change == "extra": reviews[0]["grant"] = True
    else: reviews.append(deepcopy(reviews[0]))
    with pytest.raises(ValueError): _observe(report, reviews=reviews)


def test_saved_or_reconstructed_policy_observation_cannot_open_training():
    observation = _observe(_report())
    for forged in (observation.to_dict(), api.ProjectionValidationObservation(observation._bytes)):
        with pytest.raises(ValueError, match="issued live"):
            api.require_projection_training_batch([forged], domain_id="security_ir")


def test_live_execution_is_reverified_at_training_handoff():
    report = _report()
    execution = _FakeExecution(report)
    observation = _observe(report, execution)
    execution.valid = False
    with pytest.raises(api.ProjectionValidationError):
        api.require_projection_training_batch([observation], domain_id="security_ir")


def test_optimization_inputs_cannot_change_after_live_validation():
    report = _report()
    observation = _observe(report)
    report["projections"][0]["payload"]["mutated"] = True
    with pytest.raises(ValueError, match="optimization targets differ"):
        api.require_projection_training_batch([observation], domain_id="security_ir", target_reports=[report])
    assert "mutated" not in observation.native_report()["projections"][0]["payload"]


def test_observation_returns_copies_and_rejects_duplicate_sources():
    report = _report()
    observation = _observe(report)
    result = observation.to_dict(); result["source_projection_gate_passed"] = False
    assert observation.to_dict()["source_projection_gate_passed"]
    with pytest.raises(FrozenInstanceError): observation._bytes = b"{}"
    with pytest.raises(ValueError, match="unique source"):
        api.evaluate_projection_training_batch([observation, observation], domain_id="security_ir")


def test_source_report_and_batch_byte_limits_fail_closed(monkeypatch):
    report = _report()
    observation = _observe(report)
    monkeypatch.setattr(api, "MAX_BATCH_BYTES", 1)
    with pytest.raises(ValueError, match="batch exceeds byte bound"):
        api.require_projection_training_batch([observation], domain_id="security_ir")
    monkeypatch.setattr(api, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError, match="report exceeds byte bound"):
        _observe(report)


def test_mixed_domain_and_policy_source_drift_reject(monkeypatch):
    observation = _observe(_report())
    with pytest.raises(ValueError, match="domain or policy drift"):
        api.require_projection_training_batch([observation], domain_id="intent_ir")
    monkeypatch.setattr(api, "_SOURCE_SHA", "0" * 64)
    with pytest.raises(ValueError, match="policy source changed"):
        api.require_projection_training_batch([observation], domain_id="security_ir")
