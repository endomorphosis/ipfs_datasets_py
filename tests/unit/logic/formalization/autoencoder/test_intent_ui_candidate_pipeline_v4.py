"""Compound UI logic is post-generation evidence, not native-decoder repair."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline_v4 as api
from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline_v3 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as owner


def fixture():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_modal_logic_v1/temporal_cases.py"
    spec = importlib.util.spec_from_file_location("compound_UI_pipeline_test_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compact(identity="old", *, wrong=False):
    return {"id": identity, "source_text": "Component approve has role button. Its privacy sensitivity is high "
        "and its presentation classification is interactive.", "candidate": {"kind": "ui_component", "document": {
        "component_id": "approve", "role": "textbox" if wrong else "button", "privacy_sensitivity": "high",
        "presentation_classification": "interactive"}}}


def report(rows, domain="ui_ux_ir"):
    return {"domain_id": domain, "dimension": 384, "model_inference_executed": False, "rows": [
        {"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
         "candidate_ir": deepcopy(row["candidate"]), "generated_tokens": ["preserved", row["id"]],
         "target_access": False, "teacher_forcing": False, "model_inference_executed": False,
         "candidate_origin": row.get("candidate_origin", "authored_fixture"), **api.FALSE} for row in rows], **api.FALSE}


def sources(rows):
    return [{key: row[key] for key in ("id", "source_text")} for row in rows]


def test_mixed_order_and_one_prior_batch_preserve_original_results(monkeypatch):
    old_rows = [compact("old-good"), compact("old-bad", wrong=True)]
    new_rows = fixture().cases()
    rows = [old_rows[0], new_rows[0], old_rows[1], new_rows[-1]]
    expected_old = previous.audit_candidates(report(old_rows), sources(old_rows))["rows"]
    original = report(rows)
    before = deepcopy(original)
    calls = []
    old_function = previous.audit_candidates
    def delegated(value, source_rows, **options):
        calls.append([row["id"] for row in value["rows"]])
        return old_function(value, source_rows, **options)
    monkeypatch.setattr(previous, "audit_candidates", delegated)
    result = api.audit_candidates(original, sources(rows))
    assert original == before and calls == [["old-good", "old-bad"]]
    assert [row["id"] for row in result["rows"]] == [row["id"] for row in rows]
    assert [row["eligible_for_family_preparation"] for row in result["rows"]] == [True, True, False, False]
    assert result["rows"][0] == expected_old[0] and result["rows"][2] == expected_old[1]
    for actual, expected in zip(result["rows"], before["rows"]):
        assert actual["candidate_ir"] == expected["candidate_ir"]
        assert actual["generated_tokens"] == expected["generated_tokens"]
    compound = result["rows"][1]
    assert compound["candidate_audit"]["pipeline_route"] == "explicit_compound_UI_logic"
    assert not compound["current_learned_decoder_compatible"]
    assert not compound["eligible_for_training"] and not compound["strict_training_allowed"]
    assert not compound["training_token_limit_changed"]
    assert len(compound["candidate_audit"]["family_projection"]["report"]["requested_families"]) == 40


def test_source_only_modal_declaration_cannot_be_added_to_plain_document_prediction():
    row = fixture().make_case()
    row["candidate"] = {"kind": "document", "document": row["candidate"]["document"]}
    result = api.audit_candidates(report([row]), sources([row]))
    output = result["rows"][0]
    assert output["candidate_ir"] == row["candidate"]
    assert output["candidate_audit"]["pipeline_route"] == "explicit_compound_UI_logic"
    assert output["candidate_audit"]["family_projection"] is None
    assert not output["eligible_for_family_preparation"]


def test_native_rejected_raw_compound_remains_rejected_without_preparation(monkeypatch):
    row = fixture().make_case()
    original = report([row])
    original["rows"][0].update(candidate_ir=None, raw_candidate_ir=deepcopy(row["candidate"]))
    monkeypatch.setattr(owner, "prepare_family_targets", lambda *a, **k: pytest.fail("raw candidate must not be promoted"))
    result = api.audit_candidates(original, sources([row]))
    output = result["rows"][0]
    assert output["candidate_ir"] is None and output["raw_candidate_ir"] == row["candidate"]
    audit = output["candidate_audit"]
    assert audit["status"] == "native_generation_rejected" and audit["source_fidelity"]["source_agreement"]
    assert audit["family_projection"] is None and audit["raw_output_audited_after_native_rejection"]
    assert not output["eligible_for_family_preparation"]


def test_semantic_projection_error_keeps_source_agreement_and_original_negative():
    row = fixture().cases()[4]
    result = api.audit_candidates(report([row]), sources([row]))
    output = result["rows"][0]
    assert output["candidate_ir"] == row["candidate"]
    assert output["candidate_audit"]["source_fidelity"]["source_agreement"]
    assert output["candidate_audit"]["status"] == "projection_invalid_or_missing_context"
    assert row["expected_reason"] in output["candidate_audit"]["family_projection"]["reason"]
    assert not output["eligible_for_family_preparation"]


def test_inference_finishes_before_any_source_schema_or_owner_inspection(monkeypatch):
    row = fixture().make_case()
    calls = []
    routing = api._compound
    old_audit = owner.audit_candidate
    def infer(values, **options):
        assert calls == [] and options == {"weight_ablation": "zero_head"}
        assert set(values[0]) == {"id", "source_text", "embedding"}
        calls.append("infer")
        return report([row])
    def route(*args):
        assert calls == ["infer"]
        calls.append("route")
        return routing(*args)
    def audit(*args):
        assert calls[:2] == ["infer", "route"]
        calls.append("audit")
        return old_audit(*args)
    monkeypatch.setattr(api, "_compound", route)
    monkeypatch.setattr(owner, "audit_candidate", audit)
    values = [{**sources([row])[0], "embedding": [0.01] * 384}]
    result = api.infer_and_audit(SimpleNamespace(infer=infer), values, weight_ablation="zero_head")
    assert result["rows"][0]["eligible_for_family_preparation"]
    assert calls == ["infer", "route", "audit", "audit"]


@pytest.mark.parametrize("key", ["target", "candidate_ir", "logic", "source_reference", "context"])
def test_inference_rejects_target_or_context_side_channels(key):
    row = fixture().make_case()
    values = [{**sources([row])[0], "embedding": [0.01] * 384, key: {}}]
    with pytest.raises(ValueError, match="closed target-free"):
        api.infer_and_audit(SimpleNamespace(infer=lambda *a, **k: pytest.fail("must reject first")), values)


@pytest.mark.parametrize("flag", tuple(api.FALSE))
def test_inference_authority_or_training_flags_cannot_bypass_gates(flag, monkeypatch):
    row = fixture().make_case()
    original = report([row])
    original["rows"][0][flag] = True
    monkeypatch.setattr(owner, "audit_candidate", lambda *a: pytest.fail("must reject before source audit"))
    with pytest.raises(ValueError, match="authority"):
        api.audit_candidates(original, sources([row]))


def test_source_bounds_and_hash_remain_required_before_audit():
    row = fixture().make_case()
    original = report([row])
    original["rows"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        api.audit_candidates(original, sources([row]))
    row["source_text"] = "x" * 65537
    with pytest.raises(ValueError, match="bounded source"):
        api.audit_candidates(report([row]), sources([row]))


def test_intent_rows_all_delegate_once_without_new_UI_route(monkeypatch):
    row = {"id": "intent", "source_text": "The librarian must catalog the packet.", "candidate": {
        "kind": "intent_rich_ast", "document": {"kind": "atom", "actor": "librarian", "action": "catalog",
            "object": "packet", "modality": "permitted"}}}
    original = report([row], domain="intent_ir")
    expected = previous.audit_candidates(original, sources([row]))["rows"]
    calls = []
    function = previous.audit_candidates
    def delegate(*args, **kwargs):
        calls.append(True)
        return function(*args, **kwargs)
    monkeypatch.setattr(previous, "audit_candidates", delegate)
    result = api.audit_candidates(original, sources([row]))
    assert calls == [True] and result["rows"] == expected
