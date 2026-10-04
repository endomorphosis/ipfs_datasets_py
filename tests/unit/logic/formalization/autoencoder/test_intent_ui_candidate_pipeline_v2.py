"""Wrong UI declarations cannot become family-eligible just by compiling."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder import ui_candidate_fidelity as fidelity
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v3 as projection


SOURCE = ("Component approve_toggle has role button. Its privacy sensitivity is high "
          "and its presentation classification is interactive.")


def candidate(**changes):
    return {"kind": "ui_component", "document": {
        "component_id": "approve_toggle", "role": "button", "privacy_sensitivity": "high",
        "presentation_classification": "interactive", **changes}}


def report(*candidates, source=SOURCE):
    return {"domain_id": "ui_ux_ir", "dimension": 384, "rows": [
        {"id": str(i), "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
         "candidate_ir": deepcopy(value), "generated_tokens": ["preserved", str(i)],
         "target_access": False, "teacher_forcing": False, **api.FALSE}
        for i, value in enumerate(candidates)], **api.FALSE}


def sources(n=1, source=SOURCE):
    return [{"id": str(i), "source_text": source} for i in range(n)]


def test_real_source_agreement_then_v3_projection_remains_partial():
    original = report(candidate())
    before = deepcopy(original)
    result = api.audit_candidates(original, sources())
    row = result["rows"][0]
    checked = row["candidate_audit"]
    assert original == before and row["candidate_ir"] == before["rows"][0]["candidate_ir"]
    assert row["generated_tokens"] == ["preserved", "0"]
    assert row["eligible_for_family_preparation"] is True
    assert checked["status"] == "source_agreement" and checked["projection_executed"]
    assert checked["source_fidelity"]["status"] == "source_agreement"
    assert checked["family_projection"]["status"] == "projected_candidate"
    families = checked["family_projection"]["report"]
    assert len(families["requested_families"]) == 40
    assert families["all_requested_families_available"] is False
    assert result["family_preparation_requires_bounded_source_agreement"]
    assert result["candidate_audit_dispositions"] == {"source_agreement": 1}
    assert all(owner[key] is False for owner in (result, row, checked) for key in api.FALSE)


@pytest.mark.parametrize("changes", [
    {"component_id": "export_panel"}, {"role": "textbox"},
    {"privacy_sensitivity": "low"}, {"presentation_classification": "static"},
])
def test_wrong_but_native_valid_ui_is_blocked_before_projection(monkeypatch, changes):
    calls = []
    monkeypatch.setattr(projection, "qualify_source_candidate", lambda *a, **k: calls.append(a))
    original = report(candidate(**changes))
    result = api.audit_candidates(original, sources())
    row = result["rows"][0]
    assert calls == [] and row["candidate_ir"] == original["rows"][0]["candidate_ir"]
    assert row["candidate_audit"]["status"] == "source_disagreement"
    assert row["candidate_audit"]["family_projection"] is None
    assert not row["eligible_for_family_preparation"]
    assert row["status"] == "blocked_candidate_source_disagreement"
    assert row["candidate_audit"]["source_fidelity"]["differences"]


@pytest.mark.parametrize("source", [SOURCE + " Except when an administrator intervenes.",
    "Show a private button.", SOURCE.replace("high", "high unless approved")])
def test_unsupported_source_is_not_a_successful_projection(monkeypatch, source):
    calls = []
    monkeypatch.setattr(projection, "qualify_source_candidate", lambda *a, **k: calls.append(a))
    result = api.audit_candidates(report(candidate(), source=source), sources(source=source))
    assert not calls and not result["rows"][0]["eligible_for_family_preparation"]
    assert result["candidate_audit_dispositions"] == {"source_unsupported": 1}


def test_invalid_candidate_and_wrong_candidate_do_not_hide_successful_sibling():
    original = report(None, candidate(role="textbox"), candidate())
    result = api.audit_candidates(original, sources(3))
    assert len(result["rows"]) == 3
    assert [r["eligible_for_family_preparation"] for r in result["rows"]] == [False, False, True]
    assert result["candidate_audit_dispositions"] == {
        "native_invalid": 1, "source_disagreement": 1, "source_agreement": 1}
    assert [r["candidate_ir"] for r in result["rows"]] == [r["candidate_ir"] for r in original["rows"]]


def test_matching_source_does_not_override_projection_failure(monkeypatch):
    monkeypatch.setattr(projection, "qualify_source_candidate", lambda *a, **k: {
        "status": "invalid_or_missing_context", "reason": "missing component graph context"})
    result = api.audit_candidates(report(candidate()), sources())
    row = result["rows"][0]
    assert row["candidate_audit"]["source_fidelity"]["status"] == "source_agreement"
    assert row["candidate_audit"]["status"] == "projection_invalid_or_missing_context"
    assert not row["eligible_for_family_preparation"]


def test_model_finishes_before_source_parser_runs(monkeypatch):
    calls = []
    rows = [{**sources()[0], "embedding": [0.01] * 384}]

    def infer(values, **options):
        assert values == rows and options == {"weight_ablation": "zero_head"}
        assert set(values[0]) == {"id", "source_text", "embedding"}
        calls.append("model")
        return report(candidate(role="textbox"))

    def audit(text, value):
        assert calls == ["model"]
        calls.append("audit")
        assert text == SOURCE and value == candidate(role="textbox")
        return {"status": "source_disagreement", "test_harness": "sequence_observer_only"}

    monkeypatch.setattr(fidelity, "audit_ui_candidate", audit)
    result = api.infer_and_audit(SimpleNamespace(infer=infer), rows, weight_ablation="zero_head")
    assert calls == ["model", "audit"] and not result["rows"][0]["eligible_for_family_preparation"]


@pytest.mark.parametrize("field", ["target", "source_reference", "candidate_ir", "extra"])
def test_inference_does_not_accept_targets_or_source_references(field):
    calls = []
    rows = [{**sources()[0], "embedding": [0.01] * 384, field: candidate()}]
    with pytest.raises(ValueError, match="closed target-free"):
        api.infer_and_audit(SimpleNamespace(infer=lambda *a, **k: calls.append(a)), rows)
    assert not calls


@pytest.mark.parametrize("field", tuple(api.FALSE))
def test_positive_authority_is_rejected_before_source_audit(monkeypatch, field):
    calls = []
    original = report(candidate())
    original["rows"][0][field] = True
    monkeypatch.setattr(fidelity, "audit_ui_candidate", lambda *a: calls.append(a))
    with pytest.raises(ValueError, match="authority"):
        api.audit_candidates(original, sources())
    assert not calls and original["rows"][0][field] is True


def test_source_hash_mismatch_is_rejected_before_any_source_or_projection_call(monkeypatch):
    calls = []
    original = report(candidate())
    original["rows"][0]["source_sha256"] = "0" * 64
    monkeypatch.setattr(fidelity, "audit_ui_candidate", lambda *a: calls.append(a))
    with pytest.raises(ValueError, match="hash mismatch"):
        api.audit_candidates(original, sources())
    assert not calls


def test_raw_output_retained_for_diagnosis_never_overrides_native_rejection(monkeypatch):
    original = report(None)
    original["rows"][0]["raw_candidate_ir"] = candidate()
    calls = []
    monkeypatch.setattr(projection, "qualify_source_candidate", lambda *a, **k: calls.append(a))
    result = api.audit_candidates(original, sources())
    row = result["rows"][0]
    assert not calls and not row["eligible_for_family_preparation"]
    assert row["candidate_ir"] is None and row["raw_candidate_ir"] == candidate()
    audit = row["candidate_audit"]
    assert audit["status"] == "native_generation_rejected"
    assert audit["source_fidelity"]["candidate"] == candidate()
    assert audit["source_fidelity"]["status"] == "source_agreement"
    assert audit["raw_output_audited_after_native_rejection"] is True
    assert audit["native_candidate_available"] is False


def test_intent_disagreement_remains_blocked():
    text = "The librarian must catalog the packet."
    original = report({"kind": "intent_rich_ast", "document": {
        "kind": "atom", "actor": "librarian", "action": "catalog", "object": "packet",
        "modality": "permitted"}}, source=text)
    original["domain_id"] = "intent_ir"
    result = api.audit_candidates(original, sources(source=text))
    assert result["candidate_audit_dispositions"] == {"source_disagreement": 1}
    assert not result["rows"][0]["eligible_for_family_preparation"]


def test_matching_conditional_intent_preserves_guard_and_adds_actual_deontic_route():
    text = "If Cache.py is ready, agent must inspect Cache.py."
    target = {"kind": "intent_rich_ast", "document": {"kind": "if",
        "guard": {"subject": "Cache.py", "property": "ready", "negated": False},
        "body": {"kind": "atom", "actor": "agent", "action": "inspect", "object": "Cache.py",
                 "modality": "required"}}}
    original = report(target, source=text)
    original["domain_id"] = "intent_ir"
    result = api.audit_candidates(original, sources(source=text))
    row = result["rows"][0]
    assert row["eligible_for_family_preparation"] and row["candidate_ir"] == target
    checked = row["candidate_audit"]["family_projection"]
    assert checked["status"] == "projected_candidate"
    families = checked["report"]
    assert len(families["requested_families"]) == 40
    assert "deontic" in {p["logic_family"] for p in families["projections"] if p["ready_for_training"]}
    assert not families["all_requested_families_available"]
    assert all(row[key] is False for key in api.FALSE)
