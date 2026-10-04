"""Exact coverage diagnosis without training, subprocesses or Lake authority.

Most tests use real preparation. The one internally consistent success-shaped
receipt is explicitly inert test data, never an executed or verified Lake run.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_coverage_frontier as subject
from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_contract_384 as intent
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v3 as ui
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as ui_event
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v7 as native
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar


@pytest.fixture(scope="module")
def intent_packet():
    ast = {"kind": "atom", "actor": "agent", "action": "inspect", "object": "Cache.py", "modality": "required"}
    return intent.prepare_family_targets(rich_grammar.ast_to_text(ast), {"kind": "intent_rich_ast", "document": ast})


@pytest.fixture(scope="module")
def prepared(intent_packet):
    return native.prepare_native_family_lean(intent_packet["report"], source_inputs=intent_packet["source_inputs"])


def rows_by(result, key, id_key):
    return {row[id_key]: row for row in result[key]}


def test_missing_catalog_floor_and_native_evidence_are_separate(intent_packet):
    report = intent_packet["report"]
    before = deepcopy(report)
    result = subject.diagnose_family_coverage(report)
    assert report == before
    assert result["canonical_family_count"] == 40 and result["full_request_scope"]
    assert len(result["missing_catalog_families"]) == 30
    assert result["missing_catalog_families"] == result["unreviewed_applicability_families"]
    floors = rows_by(result, "floor_requirement_diagnostics", "requirement_id")
    assert floors["first_order"]["status"] == floors["intention_agency"]["status"] == "floor_requirement_absent"
    assert floors["program"]["status"] == "native_evidence_not_supplied"
    assert all(row["status"] == "native_evidence_not_supplied" for row in result["projection_diagnostics"])
    assert any("ASSUMPTION" in text for text in floors["first_order"]["next_required_evidence"])
    assert any("unique matching" in text for text in floors["intention_agency"]["next_required_evidence"])
    assert all(result[key] is False for key in subject.FALSE)
    assert result["native_report_sha256"] == subject._sha(report)
    assert result["source_digest"] == report["source_digest"]
    assert result["policy_sha256"] == subject.policy.domain_projection_policy("intent_ir")["policy_sha256"]


def test_real_preparation_is_not_Lake_and_vacuous_contract_is_ineligible(intent_packet, prepared):
    result = subject.diagnose_family_coverage(intent_packet["report"], native_receipt=prepared)
    floors = rows_by(result, "floor_requirement_diagnostics", "requirement_id")
    assert floors["program"]["status"] == "emitted_but_floor_ineligible"
    assert floors["deontic"]["status"] == "native_stage_incomplete"
    projection = rows_by(result, "projection_diagnostics", "projection_id")["intent-route/action-hoare/v1"]
    assert projection["recorded_floor_eligible"] is False
    assert projection["recorded_floor_reason"] == "vacuous_contract_without_meaningful_postcondition"
    assert projection["status"] == "Lake_not_reported_passed"
    assert not result["native_receipt_binding"]["consistent_Lake_command_recorded"]
    assert all(result[key] is False for key in subject.FALSE)


def test_named_operator_fragments_do_not_alias_broad_family_membership(intent_packet):
    result = subject.diagnose_family_coverage(intent_packet["report"])
    fragments = rows_by(result, "named_fragment_evidence", "requirement_id")
    dfol, = fragments["DFOL"]["records"]
    assert dfol["required_operator_pattern_recorded"]
    assert dfol["native_formula_parse_replayed"]
    assert dfol["recorded_operator_counts"]["deontic"] == 1
    assert dfol["recorded_operator_counts"]["temporal"] == 0
    for name in ("TDFOL", "DCEC"):
        assert fragments[name]["status"] == "named_fragment_not_supplied"
        assert fragments[name]["other_same_family_projection_ids"]
    assert fragments["FOL"]["status"] == "named_fragment_not_supplied"


def test_explicit_inapplicability_review_does_not_remove_catalog_gap_or_floor(intent_packet):
    report = intent_packet["report"]
    review = [{"family_id": "first_order", "source_digest": report["source_digest"],
        "disposition": "inapplicable", "reason": "Fixture source contains a normative goal, no asserted assumption.",
        "evidence_refs": ["fixture:exact-declared-norm"]}]
    result = subject.diagnose_family_coverage(report, applicability_review=review)
    assert "first_order" in result["missing_catalog_families"]
    assert "first_order" not in result["unreviewed_applicability_families"]
    floor = rows_by(result, "floor_requirement_diagnostics", "requirement_id")["first_order"]
    assert floor["status"] == "floor_requirement_absent" and floor["inapplicability_review_cannot_waive_requirement"]
    assert not result["strict_training_allowed"]


def test_conflicting_review_is_visible_without_waiving_emitted_projection(intent_packet):
    report = intent_packet["report"]
    review = [{"family_id": "deontic", "source_digest": report["source_digest"],
        "disposition": "inapplicable", "reason": "Deliberately inconsistent authored diagnostic review.",
        "evidence_refs": ["fixture:negative-review"]}]
    result = subject.diagnose_family_coverage(report, applicability_review=review)
    row = rows_by(result, "family_inventory", "family_id")["deontic"]
    assert row["review_conflicts_with_emitted_projection"] and row["projection_ids"]
    assert row["applicability"] == "applicable_projection_emitted"


@pytest.mark.parametrize("mutate", [
    lambda r: r["per_projection"].pop(),
    lambda r: r["per_projection"].append(deepcopy(r["per_projection"][0])),
    lambda r: r["per_projection"].__setitem__(1, deepcopy(r["per_projection"][0])),
    lambda r: r.update(report_sha256="0" * 64),
    lambda r: r.update(source_digest="0" * 64),
    lambda r: r.update(domain_id="ui_ux_ir"),
    lambda r: r["per_projection"][0].update(logic_family="invented"),
    lambda r: r["per_projection"][0].update(payload_sha256="0" * 64),
    lambda r: r["per_projection"][0].update(target_sha256="0" * 64),
    lambda r: r["per_projection"][0].update(profile="invented"),
    lambda r: r.update(requested_families=r["requested_families"][:-1]),
])
def test_omitted_duplicate_unrelated_and_tampered_receipts_rejected(intent_packet, prepared, mutate):
    receipt = deepcopy(prepared)
    mutate(receipt)
    with pytest.raises(ValueError): subject.diagnose_family_coverage(intent_packet["report"], native_receipt=receipt)


@pytest.mark.parametrize("location,key", [("report", "qualified"), ("receipt", "admitted"),
    ("projection", "source_semantics_verified"), ("lowering", "proof_authority")])
def test_authority_flags_are_rejected(intent_packet, prepared, location, key):
    report, receipt = deepcopy(intent_packet["report"]), deepcopy(prepared)
    place = {"report": report, "receipt": receipt, "projection": receipt["per_projection"][0],
        "lowering": receipt["per_projection"][0]["lowering"]}[location]
    place[key] = True
    with pytest.raises(ValueError, match="authority"):
        subject.diagnose_family_coverage(report, native_receipt=receipt)


def test_older_receipt_without_optional_row_hashes_is_only_diagnostic(intent_packet, prepared):
    receipt = deepcopy(prepared)
    for row in receipt["per_projection"]:
        for key in ("profile", "source_digest", "payload_sha256", "target_sha256"):
            row.pop(key, None)
    result = subject.diagnose_family_coverage(intent_packet["report"], native_receipt=receipt)
    assert all(not row["receipt_projection_binding_fields"] for row in result["projection_diagnostics"])
    assert all(result[key] is False for key in subject.FALSE)


def test_inert_success_shaped_fixture_never_becomes_runtime_authority(intent_packet, prepared):
    # This is a claim-shaped dependency fixture, not a command execution.
    receipt = deepcopy(prepared)
    receipt["fixture_scope"] = "inert_synthetic_success_record_not_Lake_execution"
    receipt["execution"] = {"command": ["/synthetic/never-executed/lake", "build", "IntentIR"],
        "status": "passed", "backend_executed": True, "returncode": 0,
        "timed_out": False, "output_truncated": False, "workspace_limit_exceeded": False}
    for row in receipt["per_projection"]:
        if row["semantic_lowering_supported"]: row["lake_status"] = "passed"
    result = subject.diagnose_family_coverage(intent_packet["report"], native_receipt=receipt)
    assert any(row["status"] == "recorded_native_success_unverified" for row in result["projection_diagnostics"])
    assert result["native_receipt_binding"]["consistent_Lake_command_recorded"]
    assert all(result[key] is False for key in subject.FALSE)
    receipt.pop("execution")
    with pytest.raises(ValueError, match="explicit build command"):
        subject.diagnose_family_coverage(intent_packet["report"], native_receipt=receipt)


@pytest.mark.parametrize("parser,lowering,status", [("failed", True, "native_parser_not_passed"),
    ("blocked", False, "semantic_lowering_missing")])
def test_failed_parser_and_unlowered_rows_are_distinct(intent_packet, prepared, parser, lowering, status):
    receipt = deepcopy(prepared)
    row = receipt["per_projection"][0]
    row.update(parser_status=parser, semantic_lowering_supported=lowering, lake_status="not_run")
    if not lowering: row["lowering"] = None
    result = subject.diagnose_family_coverage(intent_packet["report"], native_receipt=receipt)
    observed = rows_by(result, "projection_diagnostics", "projection_id")[row["projection_id"]]
    assert observed["status"] == status


def test_ui_component_has_no_invented_events_cognition_or_temporal_state():
    target = {"kind": "ui_component", "document": {"component_id": "approve_toggle", "role": "button",
        "privacy_sensitivity": "low", "presentation_classification": "static"}}
    source = "Component approve_toggle has role button. Its privacy sensitivity is low and its presentation classification is static."
    packet = ui.prepare_family_targets(source, target)
    result = subject.diagnose_family_coverage(packet["report"])
    assert len(result["missing_catalog_families"]) == 38
    floors = rows_by(result, "floor_requirement_diagnostics", "requirement_id")
    for name in ("event_calculus", "tdfol", "dcec", "temporal", "transition_system", "TLA+"):
        assert floors[name]["status"] == "floor_requirement_absent"
    assert any("clock" in text for text in floors["event_calculus"]["next_required_evidence"])
    assert any("cognitive" in text for text in floors["dcec"]["next_required_evidence"])
    assert all(result[key] is False for key in subject.FALSE)


def test_custom_ui_bounded_event_report_is_accepted_without_named_CEC_alias():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_bounded_event_v1/cases.py"
    spec = importlib.util.spec_from_file_location("coverage_frontier_ui_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case = module.cases()[0]
    packet = ui_event.prepare_family_targets(case["source_text"], case["candidate"], **case["options"])
    result = subject.diagnose_family_coverage(packet["report"])
    assert result["report_schema"] == "ui-bounded-event-family-training-targets/v1"
    assert len(result["missing_catalog_families"]) == 36
    named = rows_by(result, "named_fragment_evidence", "requirement_id")
    assert named["CEC"]["status"] == "named_fragment_not_supplied"
    assert named["CEC"]["other_same_family_projection_ids"]
    assert all(result[key] is False for key in subject.FALSE)


@pytest.mark.parametrize("mutate", [lambda r:r["projections"].pop(),
    lambda r:r["projections"].append(deepcopy(r["projections"][0])),
    lambda r:r.update(source_digest="0"*64)])
def test_tampered_native_report_rejected(intent_packet, mutate):
    report = deepcopy(intent_packet["report"])
    mutate(report)
    with pytest.raises(ValueError): subject.diagnose_family_coverage(report)


def test_diagnostics_are_fresh_copy_and_do_not_invoke_live_verifier(intent_packet, prepared, monkeypatch):
    monkeypatch.setattr(subject.policy, "_verify_execution", lambda *a, **k: pytest.fail("diagnostic must not authenticate/reissue execution"))
    original = deepcopy(prepared)
    result = subject.diagnose_family_coverage(intent_packet["report"], native_receipt=prepared)
    result["family_inventory"].clear()
    result["requested_families"].clear()
    assert prepared == original
    assert len(subject.diagnose_family_coverage(intent_packet["report"])["family_inventory"]) == 40


def test_narrow_request_remains_incomplete_without_narrowing_floor():
    ast = {"kind": "if", "guard": {"subject": "Cache.py", "property": "ready", "negated": False},
        "body": {"kind": "atom", "actor": "agent", "action": "inspect", "object": "Cache.py", "modality": "required"}}
    packet = intent.prepare_family_targets(rich_grammar.ast_to_text(ast),
        {"kind": "intent_rich_ast", "document": ast}, requested_families=["deontic"])
    result = subject.diagnose_family_coverage(packet["report"])
    assert not result["full_request_scope"] and len(result["unrequested_catalog_families"]) == 39
    assert len(result["family_inventory"]) == 40
    assert [r["requirement_id"] for r in result["floor_requirement_diagnostics"]] == [
        r["requirement_id"] for r in subject.policy.domain_projection_policy("intent_ir")["minimum_batch_floor"]]


@pytest.mark.parametrize("mutate", [lambda p:p["operator_counts"].update(temporal=1),
    lambda p:p["native_ast"].update(operator={"enum":"DeonticOperator","value":"F"})])
def test_coherently_rehashed_named_formula_counts_or_AST_rejected(intent_packet, mutate):
    report = deepcopy(intent_packet["report"])
    row = next(r for r in report["projections"] if r["projection_id"] == "intent_ir/native_formula/DFOL/v3")
    mutate(row["payload"])
    row["target_sha256"] = subject._sha({k:v for k,v in row.items() if k != "target_sha256"})
    report["report_sha256"] = subject._sha({k:v for k,v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="native parser replay"):
        subject.diagnose_family_coverage(report)
