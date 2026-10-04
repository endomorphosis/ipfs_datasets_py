"""All post-generation routes retain source gates, authority limits and candidates."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline_v3 as api
from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline_v2 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_source_fidelity as ui


def cases():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_declared_source_v1/cases.py"
    spec = importlib.util.spec_from_file_location("ui_declared_pipeline_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def report(rows, domain="ui_ux_ir"):
    return {"domain_id": domain, "dimension": 384, "model_inference_executed": False, "rows": [
        {"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
         "candidate_ir": deepcopy(row["candidate"]), "candidate_origin": row.get("candidate_origin", "test_fixture"),
         "generated_tokens": ["opaque", row["id"]], "target_access": False, "teacher_forcing": False,
         "model_inference_executed": False, **api.FALSE} for row in rows], **api.FALSE}


def sources(rows):
    return [{key: row[key] for key in ("id", "source_text")} for row in rows]


def component():
    return {"id": "compact", "source_text": "Component approve has role button. Its privacy sensitivity is high "
        "and its presentation classification is interactive.", "candidate": {"kind": "ui_component", "document": {
        "component_id": "approve", "role": "button", "privacy_sensitivity": "high", "presentation_classification": "interactive"}}}


def test_full_source_pipeline_keeps_all_candidates_and_reasons_without_neural_claim():
    fixtures = cases()
    original = report(fixtures)
    before = deepcopy(original)
    result = api.audit_candidates(original, sources(fixtures))
    assert original == before and len(result["rows"]) == 11
    assert sum(row["eligible_for_family_preparation"] for row in result["rows"]) == 3
    for input_row, output in zip(before["rows"], result["rows"]):
        assert output["candidate_ir"] == input_row["candidate_ir"]
        assert output["generated_tokens"] == input_row["generated_tokens"]
        assert not output["model_inference_executed"]
        assert all(output[key] is False for key in api.FALSE)
        assert output["candidate_audit"]["pipeline_route"] == "explicit_ui_document"
    first = result["rows"][0]["candidate_audit"]
    assert first["source_fidelity"]["source_agreement"]
    assert len(first["family_projection"]["report"]["requested_families"]) == 40
    assert len(first["missing_context_requirements"]) == 36
    assert not result["neural_rich_document_generation_verified"]
    assert not result["training_token_limit_changed"]
    assert result["rows"][3]["candidate_audit"]["status"] == "projection_invalid_or_missing_context"
    assert "unknown or extra" in result["rows"][3]["candidate_audit"]["family_projection"]["reason"]


def test_compact_ui_unchanged_outputs_report_and_two_family_floor():
    fixture = component()
    original = report([fixture])
    old = previous.audit_candidates(original, sources([fixture]))
    result = api.audit_candidates(original, sources([fixture]))
    row = result["rows"][0]
    checked = row["candidate_audit"]
    actual = deepcopy(row)
    actual["candidate_audit"].pop("pipeline_route")
    actual["candidate_audit"].pop("missing_context_requirements")
    assert actual == old["rows"][0]
    assert checked["pipeline_route"] == "unchanged_compact_v2"
    assert len(checked["missing_context_requirements"]) == 38
    assert checked["family_projection"]["audit"]["available_families"] == ["first_order", "frame_logic"]


def test_compact_intent_still_delegates_to_original_source_gate():
    fixture = {"id": "intent", "source_text": "The librarian must catalog the packet.",
        "candidate": {"kind": "intent_rich_ast", "document": {"kind": "atom", "actor": "librarian",
            "action": "catalog", "object": "packet", "modality": "permitted"}}}
    original = report([fixture], domain="intent_ir")
    old = previous.audit_candidates(original, sources([fixture]))
    new = api.audit_candidates(original, sources([fixture]))
    new["rows"][0]["candidate_audit"].pop("pipeline_route")
    assert new["rows"] == old["rows"]
    assert not new["rows"][0]["eligible_for_family_preparation"]


def test_inference_finishes_before_any_source_or_interpretation_parsing(monkeypatch):
    fixture = cases()[0]
    calls = []
    original_audit = ui.audit_candidate
    def infer(rows, **options):
        assert calls == [] and options == {"weight_ablation": "zero_head"}
        assert set(rows[0]) == {"id", "source_text", "embedding"}
        calls.append("generation")
        return report([fixture])
    def audit(text, candidate):
        assert calls[0] == "generation"
        calls.append("audit")
        return original_audit(text, candidate)
    monkeypatch.setattr(ui, "audit_candidate", audit)
    rows = [{**sources([fixture])[0], "embedding": [0.01] * 384}]
    result = api.infer_and_audit(SimpleNamespace(infer=infer), rows, weight_ablation="zero_head")
    assert result["rows"][0]["eligible_for_family_preparation"]
    assert calls == ["generation", "audit", "audit"]


def test_no_raw_candidate_promotion_after_native_rejection():
    fixture = cases()[0]
    original = report([fixture])
    original["rows"][0].update(candidate_ir=None, raw_candidate_ir=deepcopy(fixture["candidate"]))
    result = api.audit_candidates(original, sources([fixture]))
    row = result["rows"][0]
    assert row["candidate_ir"] is None and row["raw_candidate_ir"] == fixture["candidate"]
    assert row["candidate_audit"]["status"] == "native_generation_rejected"
    assert row["candidate_audit"]["family_projection"] is None
    assert not row["eligible_for_family_preparation"]


def test_existing_guard_route_blocker_is_not_relabelled_as_projection_success():
    fixture = cases()[0]
    source = json.loads(fixture["source_text"])
    source["interpretations"]["event"] = None
    fixture["source_text"] = json.dumps(source)
    result = api.audit_candidates(report([fixture]), sources([fixture]))
    row = result["rows"][0]
    assert not row["eligible_for_family_preparation"]
    assert row["candidate_audit"]["family_projection"]["status"] == "projected_candidate_with_blocked_behavior"
    old_ec = next(p for p in row["candidate_audit"]["family_projection"]["report"]["projections"]
                  if p["projection_id"] == "ui_ux_ir:event_calculus")
    assert not old_ec["ready_for_training"]


@pytest.mark.parametrize("flag", tuple(api.FALSE))
def test_authority_cannot_be_attached_to_inference_before_audit(flag, monkeypatch):
    fixture = cases()[0]
    original = report([fixture])
    original["rows"][0][flag] = True
    called = []
    monkeypatch.setattr(ui, "audit_candidate", lambda *a: called.append(a))
    with pytest.raises(ValueError, match="authority"):
        api.audit_candidates(original, sources([fixture]))
    assert not called


@pytest.mark.parametrize("extra", ["target", "candidate_ir", "interpretations", "context", "expected_document"])
def test_no_teacher_targets_or_declaration_side_channels_in_inference(extra):
    fixture = cases()[0]
    rows = [{**sources([fixture])[0], "embedding": [0.01] * 384, extra: {}}]
    with pytest.raises(ValueError, match="closed target-free"):
        api.infer_and_audit(SimpleNamespace(infer=lambda *a: pytest.fail("must reject before inference")), rows)


def test_stale_hash_rejected_before_source_audit(monkeypatch):
    fixture = cases()[0]
    original = report([fixture])
    original["rows"][0]["source_sha256"] = "0" * 64
    monkeypatch.setattr(ui, "audit_candidate", lambda *a: pytest.fail("must reject before source audit"))
    with pytest.raises(ValueError, match="hash mismatch"):
        api.audit_candidates(original, sources([fixture]))


def test_failed_compact_projection_keeps_original_row_instead_of_crashing(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v3 as compact_projection
    fixture = component()
    monkeypatch.setattr(compact_projection, "qualify_source_candidate", lambda *a, **k: {
        "status": "invalid_or_missing_context", "report": None, "reason": "missing explicit context"})
    original = report([fixture])
    result = api.audit_candidates(original, sources([fixture]))
    row = result["rows"][0]
    assert row["candidate_ir"] == fixture["candidate"]
    assert row["candidate_audit"]["status"] == "projection_invalid_or_missing_context"
    assert row["candidate_audit"]["family_projection"]["report"] is None
    assert not row["eligible_for_family_preparation"]


def test_full_intent_source_routes_without_permission_becoming_intention():
    from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_coverage_384 as intent
    text = "Assume the ledger is open. The clerk intends to review the ledger."
    fixture = {"id": "native-intent", "source_text": text, "candidate": intent.source_target(text),
               "candidate_origin": "authored_declared_source_fixture_not_model_output"}
    original = report([fixture], domain="intent_ir")
    result = api.audit_candidates(original, sources([fixture]))
    row = result["rows"][0]
    assert row["candidate_ir"] == original["rows"][0]["candidate_ir"]
    assert row["candidate_audit"]["pipeline_route"] == "explicit_intent_document"
    assert row["candidate_audit"]["source_fidelity"]["status"] == "source_agreement"
    assert row["eligible_for_family_preparation"]
    assert len(row["candidate_audit"]["family_projection"]["report"]["requested_families"]) == 40
    wrong = deepcopy(fixture)
    wrong["candidate"]["document"]["statements"][1]["modality"] = "permitted"
    failed = api.audit_candidates(report([wrong], domain="intent_ir"), sources([wrong]))
    assert not failed["rows"][0]["eligible_for_family_preparation"]
    assert failed["rows"][0]["candidate_audit"]["status"] == "source_disagreement"


def test_compact_batch_does_not_copy_complete_panel_for_each_row(monkeypatch):
    fixtures = [{**component(), "id": "compact:" + str(i)} for i in range(32)]
    original = report(fixtures)
    copied_panel_rows = []
    def counted_copy(value):
        if type(value) is dict and type(value.get("rows")) is list:
            copied_panel_rows.append(len(value["rows"]))
        return deepcopy(value)
    def compact_audit(value, source_rows, **options):
        assert len(value["rows"]) == len(source_rows) == len(fixtures)
        copied = deepcopy(value)
        for row in copied["rows"]:
            row.update(eligible_for_family_preparation=False, candidate_audit={
                "status": "source_unsupported", "family_projection": None})
        return copied
    monkeypatch.setattr(api, "deepcopy", counted_copy)
    monkeypatch.setattr(previous, "audit_candidates", compact_audit)
    output = api.audit_candidates(original, sources(fixtures))
    assert len(output["rows"]) == len(fixtures)
    assert sum(copied_panel_rows) <= 2 * len(fixtures)
    assert [row["candidate_ir"] for row in output["rows"]] == [row["candidate"] for row in fixtures]


def test_mixed_panel_batches_old_route_once_and_preserves_order_and_rejections(monkeypatch):
    correct = component()
    wrong = deepcopy(correct)
    wrong["id"] = "compact-wrong"
    wrong["candidate"]["document"]["role"] = "textbox"
    declared = cases()
    fixtures = [correct, declared[0], wrong, declared[3]]
    old_owner = previous.audit_candidates
    old = old_owner(report([correct, wrong]), sources([correct, wrong]))
    calls = []
    def old_batch(value, rows, **options):
        calls.append([row["id"] for row in rows])
        return old_owner(value, rows, **options)
    monkeypatch.setattr(previous, "audit_candidates", old_batch)
    result = api.audit_candidates(report(fixtures), sources(fixtures))
    assert calls == [["compact", "compact-wrong"]]
    assert [row["id"] for row in result["rows"]] == [row["id"] for row in fixtures]
    assert [row["eligible_for_family_preparation"] for row in result["rows"]] == [True, True, False, False]
    for index, expected in zip((0, 2), old["rows"]):
        actual = deepcopy(result["rows"][index])
        actual["candidate_audit"].pop("pipeline_route")
        actual["candidate_audit"].pop("missing_context_requirements", None)
        assert actual == expected
    assert [row["candidate_ir"] for row in result["rows"]] == [row["candidate"] for row in fixtures]
