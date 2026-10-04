"""Source audits preserve target-free generation, candidates and failed rows."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline as api
from ipfs_datasets_py.logic.formalization.autoencoder import intent_candidate_fidelity as intent


INTENT_SOURCE = "The librarian must catalog the packet."
UI_SOURCE = "Present the interactive submit button with restricted privacy."
_DEFAULT = object()


def intent_candidate(**changes):
    return {"kind": "intent_rich_ast", "document": {
        "kind": "atom", "actor": "librarian", "action": "catalog",
        "object": "packet", "modality": "required", **changes}}


def ui_candidate(**changes):
    return {"kind": "ui_component", "document": {
        "component_id": "submit", "role": "button", "privacy_sensitivity": "restricted",
        "presentation_classification": "interactive", **changes}}


def source_rows(text=INTENT_SOURCE, identity="sample-0"):
    return [{"id": identity, "source_text": text}]


def inference_row(text=INTENT_SOURCE, candidate=_DEFAULT, identity="sample-0"):
    return {"id": identity, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "candidate_ir": intent_candidate() if candidate is _DEFAULT else deepcopy(candidate),
        "target_access": False, "teacher_forcing": False, "status": "unqualified_candidate",
        "generated_tokens": ["original", "tokens"], "ended": True, **api.FALSE}


def inference_report(domain="intent_ir", rows=None):
    return {"schema": "test-runtime-report/v1", "domain_id": domain, "dimension": 384,
        "checkpoint_sha256": "a" * 64, "weight_ablation": None,
        "rows": [inference_row()] if rows is None else rows, **api.FALSE}


def test_actual_intent_audit_preserves_original_report_and_generation_metadata():
    report, sources = inference_report(), source_rows()
    before, original_sources = deepcopy(report), deepcopy(sources)
    result = api.audit_candidates(report, sources)
    assert report == before and sources == original_sources
    assert result is not report and result["rows"] is not report["rows"]
    row = result["rows"][0]
    assert row["candidate_ir"] == before["rows"][0]["candidate_ir"]
    assert row["generated_tokens"] == ["original", "tokens"] and row["ended"] is True
    assert row["candidate_audit"]["candidate"] == row["candidate_ir"]
    assert row["candidate_audit"]["source_text"] == INTENT_SOURCE
    assert row["candidate_audit"]["status"] == "source_agreement"
    assert row["eligible_for_family_preparation"] is True
    assert row["status"] == "unqualified_audited_candidate"
    assert result["candidate_audit_dispositions"] == {"source_agreement": 1}
    assert result["checkpoint_sha256"] == before["checkpoint_sha256"]
    assert result["source_contracts_checked"] and result["inference_finished_before_source_audit"]
    assert not result["candidate_rewritten"] and not row["candidate_rewritten"]
    assert all(not owner[key] for owner in (result, row) for key in api.FALSE)


@pytest.mark.parametrize("change", [
    "source_text", "hash", "source_id", "report_id", "duplicate_source_id",
    "duplicate_report_id", "missing_row", "extra_row", "nonstring_report_id",
])
def test_exact_source_identity_and_hash_binding_required_before_any_audit(monkeypatch, change):
    report, sources, observed = inference_report(), source_rows(), []
    if change == "source_text":
        sources[0]["source_text"] += " "
    elif change == "hash":
        report["rows"][0]["source_sha256"] = "0" * 64
    elif change == "source_id":
        sources[0]["id"] = "different"
    elif change == "report_id":
        report["rows"][0]["id"] = "different"
    elif change == "duplicate_source_id":
        sources.append(deepcopy(sources[0]))
    elif change == "duplicate_report_id":
        sources.append({"id": "sample-1", "source_text": INTENT_SOURCE})
        report["rows"].append(deepcopy(report["rows"][0]))
    elif change == "missing_row":
        report["rows"] = []
    elif change == "extra_row":
        report["rows"].append(inference_row(identity="extra"))
    else:
        report["rows"][0]["id"] = 0
    before = deepcopy(report)
    monkeypatch.setattr(intent, "audit_intent_candidate", lambda *args: observed.append(args))
    with pytest.raises(ValueError, match="source|identity|count"):
        api.audit_candidates(report, sources)
    assert observed == [] and report == before


@pytest.mark.parametrize("field", ["target", "embedding", "candidate_ir", "source_reference"])
def test_source_audit_rows_exclude_targets_and_other_payloads(field):
    sources = source_rows()
    sources[0][field] = intent_candidate()
    with pytest.raises(ValueError, match="closed source audit row"):
        api.audit_candidates(inference_report(), sources)


@pytest.mark.parametrize("field", ["target", "candidate_ir", "source_reference", "extra"])
def test_target_free_inference_rows_reject_extra_data_before_runtime(field):
    called = []
    rows = [{**source_rows()[0], "embedding": [0.1] * 384, field: intent_candidate()}]
    runtime = SimpleNamespace(infer=lambda rows, **options: called.append(rows))
    with pytest.raises(ValueError, match="closed target-free inference rows"):
        api.infer_and_audit(runtime, rows)
    assert not called


@pytest.mark.parametrize("field", ["target_access", "teacher_forcing"])
@pytest.mark.parametrize("value", [True, None, 0, "false", "missing"])
def test_explicit_false_target_free_evidence_required(field, value):
    report = inference_report()
    if value == "missing":
        del report["rows"][0][field]
    else:
        report["rows"][0][field] = value
    with pytest.raises(ValueError, match="target-free generation evidence"):
        api.audit_candidates(report, source_rows())


@pytest.mark.parametrize("owner", ["report", "row"])
@pytest.mark.parametrize("field", tuple(api.FALSE))
def test_all_declared_authority_claims_rejected_instead_of_silently_cleared(owner, field):
    report = inference_report()
    (report if owner == "report" else report["rows"][0])[field] = True
    before = deepcopy(report)
    with pytest.raises(ValueError, match="proof authority"):
        api.audit_candidates(report, source_rows())
    assert report == before


@pytest.mark.parametrize("value", [8, 384.0, "384", True, None])
def test_exact_384_dimension_required(value):
    report = inference_report()
    report["dimension"] = value
    with pytest.raises(ValueError, match="384-dimensional"):
        api.audit_candidates(report, source_rows())


def test_runtime_finishes_before_source_reference_is_computed(monkeypatch):
    calls, rows = [], [{**source_rows()[0], "embedding": [0.1] * 384}]
    expected = deepcopy(rows)

    def infer(supplied, **options):
        assert supplied == expected
        assert options == {"weight_ablation": "zero_head"}
        assert all(set(row) == {"id", "source_text", "embedding"} for row in supplied)
        calls.append("runtime_finished")
        return inference_report()

    def audit(source, candidate):
        assert calls == ["runtime_finished"]
        assert source == INTENT_SOURCE and candidate == intent_candidate()
        calls.append("source_audit")
        return {"status": "source_agreement", "exact": True}

    monkeypatch.setattr(intent, "audit_intent_candidate", audit)
    result = api.infer_and_audit(SimpleNamespace(infer=infer), rows, weight_ablation="zero_head")
    assert calls == ["runtime_finished", "source_audit"]
    assert rows == expected
    assert result["rows"][0]["eligible_for_family_preparation"]


def test_ablation_input_mutation_and_output_order_do_not_change_caller_rows_or_source_join():
    second_text = "The inspector may seal the report."
    second_candidate = intent_candidate(actor="inspector", action="seal", object="report", modality="permitted")
    rows = [{**source_rows()[0], "embedding": [0.1] * 384},
        {"id": "sample-1", "source_text": second_text, "embedding": [0.2] * 384}]
    before = deepcopy(rows)
    observed = []

    def infer(supplied, **options):
        observed.append(options)
        assert supplied == before
        supplied.reverse()
        supplied[0]["embedding"][0] = 9.0
        result = inference_report(rows=[
            inference_row(second_text, second_candidate, "sample-1"), inference_row()])
        result["weight_ablation"] = options["weight_ablation"]
        return result

    result = api.infer_and_audit(SimpleNamespace(infer=infer), rows, weight_ablation="shuffle_embeddings")
    assert observed == [{"weight_ablation": "shuffle_embeddings"}] and rows == before
    assert result["weight_ablation"] == "shuffle_embeddings"
    assert [row["id"] for row in result["rows"]] == ["sample-1", "sample-0"]
    assert [row["candidate_audit"]["source_text"] for row in result["rows"]] == [second_text, INTENT_SOURCE]
    assert all(row["candidate_audit"]["exact"] for row in result["rows"])


@pytest.mark.parametrize("failure", ["disagreement", "unsupported_source", "invalid", "none"])
def test_one_failed_candidate_remains_in_denominator_without_suppressing_exact_sibling(failure):
    failed_source = INTENT_SOURCE
    candidate = intent_candidate(action="release")
    disposition = "source_disagreement"
    if failure == "unsupported_source":
        failed_source = "The librarian must catalog the résumé."
        candidate, disposition = intent_candidate(), "source_unsupported"
    elif failure == "invalid":
        candidate, disposition = intent_candidate(), "native_invalid"
        del candidate["document"]["action"]
    elif failure == "none":
        candidate, disposition = None, "native_invalid"
    report = inference_report(rows=[inference_row(failed_source, candidate, "failed"), inference_row()])
    before = deepcopy(report)
    sources = [{"id": "failed", "source_text": failed_source}, *source_rows()]
    result = api.audit_candidates(report, sources)
    failed, correct = result["rows"]
    assert len(result["rows"]) == 2 and report == before
    assert failed["candidate_ir"] == candidate
    assert not failed["eligible_for_family_preparation"]
    assert failed["candidate_audit"]["status"] == disposition
    assert failed["status"] == "blocked_candidate_" + disposition
    assert correct["eligible_for_family_preparation"] and correct["candidate_audit"]["exact"]
    assert result["candidate_audit_dispositions"] == {disposition: 1, "source_agreement": 1}
    assert failed["continue_planning"] and correct["continue_planning"]


def test_actual_ui_v2_declarations_preserve_candidate_classifications_and_complete_inventory():
    candidate = ui_candidate(purpose="Explicit purpose retained without a predicate.")
    report = inference_report("ui_ux_ir", [inference_row(UI_SOURCE, candidate)])
    before = deepcopy(report)
    result = api.audit_candidates(report, source_rows(UI_SOURCE))
    assert report == before
    row = result["rows"][0]
    checked = row["candidate_audit"]
    audit, native_report = checked["audit"], checked["report"]
    assert checked["status"] == "projected_candidate"
    assert audit["schema"] == "source-ui-component-qualification/v2"
    assert audit["candidate"] == row["candidate_ir"] == candidate
    assert audit["source_sha256"] == row["source_sha256"]
    assert {item["predicate"] for item in audit["declarations"]} == {
        "UIComponent", "UIRole", "UIPrivacy", "UIPresentation"}
    symbols = {(item["category"], item["value"]) for item in audit["symbol_table"]}
    assert ("privacy", "restricted") in symbols and ("presentation", "interactive") in symbols
    assert audit["available_families"] == ["first_order", "frame_logic"]
    assert len(audit["requested_families"]) == len(native_report["family_inventory"]) == 40
    assert len(audit["missing_requested_families"]) == 38
    fields = {item["path"]: item for item in audit["field_accounting"]["component_fields"]}
    assert fields["/document/purpose"]["disposition"] == "retained_uninterpreted"
    assert fields["/document/privacy_sensitivity"]["disposition"] == "explicit_classification_projected"
    assert fields["/document/presentation_classification"]["disposition"] == "explicit_classification_projected"
    assert audit["source_fidelity_check_required"] and not audit["source_semantics_verified"]
    assert {"privacy_policy", "presentation_behavior", "authorization"} <= set(audit["unprojected_facets"])
    assert all(not owner[key] for owner in (result, row) for key in api.FALSE)
    assert not native_report["all_requested_families_available"]


@pytest.mark.parametrize("candidate", [None, ui_candidate(privacy_sensitivity="interactive")])
def test_ui_invalid_none_or_classification_keeps_valid_sibling(candidate):
    sources = [*source_rows(UI_SOURCE, "bad"), *source_rows(UI_SOURCE, "good")]
    report = inference_report("ui_ux_ir", [inference_row(UI_SOURCE, candidate, "bad"),
        inference_row(UI_SOURCE, ui_candidate(), "good")])
    result = api.audit_candidates(report, sources)
    bad, good = result["rows"]
    assert bad["candidate_ir"] == candidate
    assert bad["candidate_audit"]["status"] == "invalid_or_missing_context"
    assert not bad["eligible_for_family_preparation"] and good["eligible_for_family_preparation"]
    assert result["candidate_audit_dispositions"] == {"invalid_or_missing_context": 1, "projected_candidate": 1}


def test_ui_requested_subset_passes_explicitly_through_v2_and_remains_partial():
    result = api.audit_candidates(inference_report("ui_ux_ir", [inference_row(UI_SOURCE, ui_candidate())]),
        source_rows(UI_SOURCE), requested_families=("frame_logic", "dcec"))
    checked = result["rows"][0]["candidate_audit"]
    assert set(checked["report"]["requested_families"]) == {"frame_logic", "dcec"}
    assert checked["audit"]["available_families"] == ["frame_logic"]
    assert checked["audit"]["missing_requested_families"] == ["dcec"]
    assert not checked["report"]["all_requested_families_available"]


def test_intent_diagnostic_does_not_pretend_to_run_requested_projections():
    with pytest.raises(ValueError, match="does not run family projection"):
        api.audit_candidates(inference_report(), source_rows(), requested_families=("dcec",))
