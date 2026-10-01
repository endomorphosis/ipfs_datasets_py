"""The diagnostic reproduces blockers without granting training authority."""
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import projection_context_audit as audit
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as lake
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as fixtures


@pytest.fixture(scope="module")
def observation():
    return audit.audit_default_projection_context()


def rehash(report):
    report["report_sha256"] = audit._digest({k: v for k, v in report.items() if k != "report_sha256"})


def test_three_blockers_are_two_authored_sources_with_every_projection(observation):
    report = observation.to_dict()
    assert report["counts"] == {"sources": 2, "projections": 27, "supported_preparations": 24,
        "semantic_blockers": 3, "source_grouped_review_items": 2, "supplied_formula_cases": 16,
        "Lake_executions": 0, "SANY_executions": 0}
    for source in report["sources"]:
        assert source["parent_corpus"].startswith("absent_authored_fixture")
        assert source["semantic_blockers"] == audit.BLOCKERS[source["domain_id"]]
        assert len(source["target_report"]["family_inventory"]) == 40
        assert len(source["target_report"]["requested_families"]) == 40
        assert {r["projection_id"] for r in source["target_report"]["projections"]} == {
            r["projection_id"] for r in source["native_preparation"]["per_projection"]}
        assert source["native_preparation"]["source_replay_passed"] is True


def test_retains_exact_legal_qualifier_and_original_ui_policy(observation):
    legal, ui = observation.to_dict()["sources"]
    assert legal["construction"] == "authored_ModalIRDocument_NLP_parser_not_run"
    assert legal["NLP_parser_defect"].startswith("not_tested")
    assert all(f["conditions"] == ["within 10 days"] for f in legal["input_payload"]["document"]["formulas"])
    raw = legal["input_payload"]["source_text"].encode()
    span = legal["evidence_locations"][0]
    assert raw[span["start_byte"]:span["end_byte"]].decode() == span["text"]
    binding = ui["input_payload"]["ui_training_row"]["bindings"][0]
    assert binding["confirmation_class"] == "confirm"
    assert binding["idempotency"] == "non_idempotent"
    assert [e["kind"] for e in ui["input_payload"]["ui_training_row"]["events"]] == ["activate"]
    assert "neither invocation nor completion" in ui["diagnosis"]["finding"]


def test_native_preparation_and_work_items_do_not_grant_authority(observation):
    report = observation.to_dict()
    for field in audit.FALSE:
        assert report[field] is False
    for source in report["sources"]:
        assert source["policy_without_execution"]["source_projection_gate_passed"] is False
        assert source["policy_without_execution"]["live_execution_verified"] is False
        assert source["policy_without_execution"]["family_blockers"]
        assert source["native_preparation"]["backend_executed"] is False
        assert all(r["lake_status"] != "passed" for r in source["native_preparation"]["per_projection"])
    for work in report["work_items"]:
        assert work["schema"] == audit.WORK_SCHEMA
        assert work["not_a_supervisor_task"] is True
        assert work["supervisor_importable"] is work["enqueued"] is False
    assert len(report["work_items"][0]["projection_ids"]) == 2


def test_report_copies_are_detached_and_validated_by_fresh_replay(observation):
    modified = observation.to_dict()
    modified["sources"][0]["input_payload"]["source_text"] = "changed"
    assert observation.to_dict()["sources"][0]["input_payload"]["source_text"] != "changed"
    with pytest.raises(FrozenInstanceError):
        observation._bytes = b"{}"
    assert audit.validate_projection_context_audit(observation.to_dict()).to_dict() == observation.to_dict()


@pytest.mark.parametrize("change", ("source", "projection", "authority", "work", "producer"))
def test_rehashed_tampering_cannot_survive_fresh_replay(observation, change):
    report = observation.to_dict()
    if change == "source":
        report["sources"][0]["input_payload"]["source_text"] += " extra"
    elif change == "projection":
        report["sources"][1]["native_preparation"]["per_projection"].pop()
    elif change == "authority":
        report["qualified"] = True
    elif change == "work":
        report["work_items"][0]["missing_semantic_slots"] = []
    else:
        report["producer_pins"][next(iter(report["producer_pins"]))] = "0" * 64
    rehash(report)
    with pytest.raises(ValueError, match="fresh source/code replay"):
        audit.validate_projection_context_audit(report)


def test_changed_fixture_producer_fails_closed(monkeypatch):
    monkeypatch.setattr(audit, "FIXTURE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="fixture producer changed"):
        audit.audit_default_projection_context()


def test_changed_audit_implementation_pin_fails_closed(monkeypatch):
    monkeypatch.setattr(audit, "_SOURCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="implementation changed since import"):
        audit.audit_default_projection_context()


def test_changed_source_does_not_inherit_old_diagnosis(monkeypatch):
    original = fixtures.source_inputs
    def changed(row):
        inputs = original(row)
        if row["domain_id"] == "legal_ir":
            inputs["source_text"] = "custodian must publish record within 12 days."
        return inputs
    monkeypatch.setattr(fixtures, "source_inputs", changed)
    with pytest.raises(ValueError, match="producer source or executed code changed"):
        audit.audit_default_projection_context()


def test_changed_blocker_inventory_fails_closed(monkeypatch):
    original = lake.prepare_native_family_lean
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        report["per_projection"][0]["semantic_lowering_supported"] = False
        report["per_projection"][0]["reason"] = "new_blocker"
        return report
    monkeypatch.setattr(lake, "prepare_native_family_lean", changed)
    with pytest.raises(ValueError, match="producer source or executed code changed"):
        audit.audit_default_projection_context()


def test_changed_source_payload_fails_before_diagnosis():
    row = fixtures.rows("legal_ir", "train")[0]
    inputs = fixtures.source_inputs(row)
    inputs["source_text"] = "custodian must publish record within 12 days."
    with pytest.raises(ValueError, match="fixture text changed"):
        audit._source_record("legal_ir", row, inputs)


def test_cli_never_replaces_existing_evidence(tmp_path):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[5] / "scripts/ops/autoencoder/audit_default_projection_context.py"
    spec = importlib.util.spec_from_file_location("context_audit_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "existing.json"
    output.write_text("retained evidence")
    with pytest.raises(ValueError, match="fresh path"):
        module.main(["--output", str(output)])
    assert output.read_text() == "retained evidence"


def test_semantic_ids_and_pins_do_not_depend_on_absolute_workspace(observation):
    report = observation.to_dict()
    assert all(path.startswith("ipfs_datasets_py/") and not path.startswith("/") for path in report["producer_pins"])
    for work in report["work_items"]:
        identity = {key: work[key] for key in ("schema", "source_id", "input_payload_sha256", "source_digest",
                                              "projection_ids", "missing_semantic_slots")}
        assert work["work_id"] == "context-review:" + audit._digest(identity)
    assert report["report_sha256"] == audit._digest({k: v for k, v in report.items() if k != "report_sha256"})
