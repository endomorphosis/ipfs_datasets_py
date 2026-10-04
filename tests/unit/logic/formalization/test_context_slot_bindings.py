from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan, SourceReviewStatus
from ipfs_datasets_py.logic.formalization.context_resolution import (
    ContextSpan, BoundedContextIndex, prepare_context_bundle, context_digest)
from ipfs_datasets_py.logic.formalization import context_slot_bindings as bindings


def inputs(*, revision="v1", review_status=SourceReviewStatus.UNREVIEWED):
    text = "Résumé.\nDeadline starts on receipt of notice.\nPublish within ten days."
    ref = SourceRef("ref:fixture", "fixture://context", "fixture", revision,
        hashlib.sha256(text.encode()).hexdigest(), review_status=review_status)
    raw = text.encode()
    split = raw.index(b"Publish")
    context_start = raw.index(b"Deadline")
    spans = [ContextSpan.from_source(source_ref=ref, span=SourceSpan(key, ref.ref_id, start, end),
        source_text=text, partition="authored") for key, start, end in [
            ("neighbor", context_start, split), ("selected", split, len(raw))]]
    index = BoundedContextIndex(spans, revision=revision)
    slots = [{"slot_id": "origin", "question": "deadline receipt", "sort": "temporal_anchor", "projection_ids": ["O", "T"]},
        {"slot_id": "clock", "question": "time days", "sort": "temporal_model", "projection_ids": ["O", "T"]}]
    fixtures = [{"slot_id": "origin", "value": {"trigger": "fixture_placeholder"}, "rationale": "Explicit provisional trigger."},
        {"slot_id": "clock", "value": {"clock": "nat_days"}, "rationale": "Explicit provisional clock."}]
    bundle = prepare_context_bundle(index, source_span_id="selected", slots=slots, fixtures=fixtures)
    citation = {"span_id": "neighbor", "start_byte": context_start,
        "end_byte": split - 1, "quote": "Deadline starts on receipt of notice."}
    return index, bundle, citation


def cited(index, bundle, citation, **overrides):
    kwargs = {"slot_id": "origin", "mode": "source_cited_declaration", "value": {"trigger": "notice_receipt"},
        "citations": [citation], "scope_review": {"relation": "deadline_trigger",
            "governing_scope": "Caller declares this authored context to govern the selected sentence.",
            "alternatives_disposition": "Calendar and business-day alternatives remain unverified."},
        "reviewer_record": {"reviewer_id": "fixture-author", "review_method": "caller_declaration",
            "rationale": "Exact quote supports the proposed trigger; fidelity is not established."}}
    kwargs.update(overrides)
    return bindings.prepare_context_binding(bundle, index=index, **kwargs)


def test_cited_declaration_preserves_exact_quote_source_and_undischarged_assumptions():
    index, bundle, citation = inputs()
    declaration = cited(index, bundle, citation)
    assert bindings.validate_context_binding(declaration, bundle=bundle, index=index)
    report = declaration.to_dict()
    assert report["projection_ids"] == ["O", "T"]
    assert report["bundle_sha256"] == bundle["bundle_sha256"]
    assert report["index_sha256"] == index.index_sha256
    evidence, = report["citation_bindings"]
    assert evidence["citation"] == citation
    assert evidence["quote_sha256"] == hashlib.sha256(citation["quote"].encode()).hexdigest()
    assert evidence["source_ref"]["review_status"] == "unreviewed"
    assert [r["status"] for r in report["fixture_assumptions"]] == ["superseded_not_discharged", "retained_not_discharged"]
    assert not any(r["discharged"] for r in report["fixture_assumptions"])
    assert report["interpretation_assumption"]["discharged"] is False
    assert all(report[key] is False for key in bindings._FALSE)
    assert report["source_evidence_cited"] is True


def test_fixture_binding_requires_existing_exact_value_and_carries_no_review():
    index, bundle, _ = inputs()
    value = bundle["slots"][0]["assumption"]["value"]
    declaration = bindings.prepare_context_binding(bundle, index=index, slot_id="origin", mode="fixture_assumption", value=value)
    assert bindings.validate_context_binding(declaration, bundle=bundle, index=index)
    assert declaration.to_dict()["citation_bindings"] == []
    assert declaration.to_dict()["source_evidence_cited"] is False
    with pytest.raises(ValueError, match="fixture_binding_differs"):
        bindings.prepare_context_binding(bundle, index=index, slot_id="origin", mode="fixture_assumption", value={"trigger": "different"})
    with pytest.raises(ValueError, match="cannot_claim_source_review"):
        bindings.prepare_context_binding(bundle, index=index, slot_id="origin", mode="fixture_assumption", value=value,
            reviewer_record={"reviewer_id": "claimed"})


def test_declaration_and_all_nested_views_are_immutable():
    index, bundle, citation = inputs()
    declaration = cited(index, bundle, citation)
    digest = declaration.sha256
    view = declaration.to_dict()
    view["value"]["trigger"] = "changed"
    view["citation_bindings"][0]["source_ref"]["review_status"] = "human_reviewed"
    citation["quote"] = "changed"
    assert declaration.sha256 == digest
    assert declaration.to_dict()["value"] == {"trigger": "notice_receipt"}
    with pytest.raises(FrozenInstanceError):
        declaration._bytes = b"{}"
    assert bindings.ContextBindingDeclaration.from_dict(declaration.to_dict()).sha256 == digest


@pytest.mark.parametrize("change,reason", [
    ({"quote": "Deadline starts on receipt of NOTICE."}, "quote_differs"),
    ({"start_byte": 0}, "outside_candidate"),
    ({"end_byte": 10000}, "outside_candidate"),
    ({"start_byte": True}, "outside_candidate"),
    ({"span_id": "selected"}, "retrieved_candidate"),
    ({"span_id": "invented"}, "retrieved_candidate"),
    ({"source_review_status": "human_reviewed"}, "closed_context_citation"),
])
def test_wrong_quotes_foreign_spans_and_review_injection_fail(change, reason):
    index, bundle, citation = inputs()
    citation.update(change)
    with pytest.raises(ValueError, match=reason):
        cited(index, bundle, citation)


@pytest.mark.parametrize("overrides,reason", [
    ({"citations": []}, "requires_quotes"),
    ({"scope_review": None}, "closed_context_scope_review"),
    ({"reviewer_record": None}, "closed_declared_reviewer"),
    ({"slot_id": "absent"}, "selected_context_slot"),
    ({"mode": "verified_source_truth"}, "unsupported_context_binding_mode"),
    ({"value": None}, "binding_value_required"),
    ({"value": "x" * 5000}, "binding_byte_limit"),
])
def test_incomplete_or_unbounded_declarations_fail(overrides, reason):
    index, bundle, citation = inputs()
    with pytest.raises(ValueError, match=reason):
        cited(index, bundle, citation, **overrides)


def test_duplicate_quotes_and_undeclared_scope_fail():
    index, bundle, citation = inputs()
    with pytest.raises(ValueError, match="duplicate_context_citation"):
        cited(index, bundle, citation, citations=[citation, deepcopy(citation)])
    with pytest.raises(ValueError, match="unsupported_context_scope_relation"):
        cited(index, bundle, citation, scope_review={"relation": "automatically_proves",
            "governing_scope": "Adjacent", "alternatives_disposition": "None declared"})


@pytest.mark.parametrize("status", [SourceReviewStatus.HUMAN_REVIEWED, SourceReviewStatus.TRUSTED_FIXTURE])
def test_reviewed_source_status_does_not_supply_semantic_authority(status):
    index, bundle, citation = inputs(review_status=status)
    report = cited(index, bundle, citation).to_dict()
    assert report["citation_bindings"][0]["source_ref"]["review_status"] == status.value
    assert report["citation_bindings"][0]["source_review_is_semantic_authority"] is False
    assert all(report[key] is False for key in bindings._FALSE)


def test_different_source_revision_or_tampered_bundle_fails_replay():
    index, bundle, citation = inputs()
    declaration = cited(index, bundle, citation)
    fresh_index, fresh_bundle, _ = inputs(revision="v2")
    with pytest.raises(ValueError, match="differs_from_source_replay"):
        bindings.validate_context_binding(declaration, bundle=fresh_bundle, index=fresh_index)
    bundle["slots"][0]["source_resolved"] = True
    bundle["bundle_sha256"] = context_digest({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    with pytest.raises(ValueError, match="differs_from_index_replay"):
        bindings.validate_context_binding(declaration, bundle=bundle, index=index)


@pytest.mark.parametrize("field,value", [("projection_ids", ["unrelated"]), ("fixture_assumptions", []),
    ("citation_bindings", []), ("producer_pins", {}), ("index_sha256", "0" * 64)])
def test_rehashed_source_or_assumption_tampering_fails_exact_replay(field, value):
    index, bundle, citation = inputs()
    report = cited(index, bundle, citation).to_dict()
    report[field] = value
    candidate = bindings.ContextBindingDeclaration.from_dict(report)
    with pytest.raises(ValueError, match="differs_from_source_replay"):
        bindings.validate_context_binding(candidate, bundle=bundle, index=index)


def test_authority_claim_and_producer_drift_are_rejected(monkeypatch):
    index, bundle, citation = inputs()
    report = cited(index, bundle, citation).to_dict()
    report["source_semantics_verified"] = True
    with pytest.raises(ValueError, match="cannot_grant_authority"):
        bindings.ContextBindingDeclaration.from_dict(report)
    monkeypatch.setattr(bindings, "_SOURCE_SHA", "0" * 64)
    with pytest.raises(ValueError, match="producer_changed_since_import"):
        cited(index, bundle, citation)


def test_multibyte_quote_boundaries_are_checked_in_bytes():
    text = "Réception déclenche le délai.\nPublish."
    ref = SourceRef("ref:unicode", "fixture://unicode", "unicode", "v1", hashlib.sha256(text.encode()).hexdigest())
    raw = text.encode()
    split = raw.index(b"Publish")
    rows = [ContextSpan.from_source(source_ref=ref, span=SourceSpan(key, ref.ref_id, start, end),
        source_text=text, partition="authored") for key, start, end in [("neighbor", 0, split), ("selected", split, len(raw))]]
    index = BoundedContextIndex(rows, revision="v1")
    bundle = prepare_context_bundle(index, source_span_id="selected", slots=[{
        "slot_id": "origin", "question": "réception", "sort": "temporal_anchor", "projection_ids": ["O"]}])
    citation = {"span_id": "neighbor", "start_byte": 0, "end_byte": split - 1, "quote": text.splitlines()[0]}
    assert bindings.validate_context_binding(cited(index, bundle, citation), bundle=bundle, index=index)
    citation.update(start_byte=2, quote="invalid partial character")
    with pytest.raises(ValueError, match="quote_splits_unicode"):
        cited(index, bundle, citation)


@pytest.mark.parametrize("value,reason", [
    ({1: "silently normalized key"}, "string_context_binding_json_keys"),
    (("silently normalized tuple",), "closed_inert_context_binding_json"),
    ({"quantity": float("nan")}, "bounded_inert_context_binding_json"),
    ([0] * 5000, "context_binding_json_shape_limit"),
])
def test_non_json_or_unbounded_value_shape_is_rejected_before_serialization(value, reason):
    index, bundle, citation = inputs()
    with pytest.raises(ValueError, match=reason):
        cited(index, bundle, citation, value=value)
