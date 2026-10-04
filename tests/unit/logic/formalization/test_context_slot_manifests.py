"""Structured context declarations are data, never discovered legal truth."""
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.formalization.context_resolution import ContextSpan, BoundedContextIndex, prepare_context_bundle, context_digest
from ipfs_datasets_py.logic.formalization import context_slot_manifests as manifests


def reference(key, text):
    return SourceRef("ref:" + key, "fixture://" + key, key, "v1", hashlib.sha256(text.encode()).hexdigest())


def setup(values=(10,), *, mutate=None, prose=False):
    text = "Publish the record within ten days."
    ref = reference("selected", text)
    spans = [ContextSpan.from_source(source_ref=ref, source_text=text, partition="fixture",
        span=SourceSpan("selected", ref.ref_id, 0, len(text.encode())))]
    edges = []
    slots = [{"slot_id": "clock", "question": "deadline clock model", "sort": "temporal_model", "projection_ids": ["deontic", "temporal"]}]
    for number, value in enumerate(values):
        payload = {"schema": manifests.MANIFEST_SCHEMA, "selected_source_ref": ref.to_dict(),
            "scope_note": "An explicit authored declaration for this fixture.",
            "slots": [{k: v for k, v in slots[0].items() if k != "question"} | {"value": {"quantity": value}}]}
        if mutate:
            mutate(payload)
        body = "A nearby passage with no structured policy." if prose else json.dumps(payload, ensure_ascii=False)
        key = "policy" + str(number)
        support = reference(key, body)
        spans.append(ContextSpan.from_source(source_ref=support, source_text=body, partition="fixture",
            span=SourceSpan(key, support.ref_id, 0, len(body.encode()))))
        edges.append({"source_span_id": "selected", "target_span_id": key, "relation": "policy"})
    index = BoundedContextIndex(spans, edges=edges, revision="fixture-v1")
    bundle = prepare_context_bundle(index, source_span_id="selected", slots=slots)
    return index, bundle


def test_exact_structured_value_has_byte_exact_citations_and_no_authority():
    index, bundle = setup()
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    assert report["status"] == "declared_values_available"
    assert report["proposals"][0]["value"] == {"quantity": 10}
    citation = report["proposals"][0]["citations"][0]
    assert citation["end_byte"] - citation["start_byte"] == len(citation["quote"].encode())
    assert report["source_resolved_slot_count"] == 0
    assert report["admitted"] is report["qualified"] is report["ranking_selects_values"] is False


def test_conflicts_are_preserved_instead_of_highest_rank_winning():
    index, bundle = setup((10, 20))
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    assert report["status"] == "conflict"
    assert report["proposals"] == []
    assert {a["value"]["quantity"] for a in report["conflicts"][0]["alternatives"]} == {10, 20}
    with pytest.raises(ValueError, match="complete_unambiguous"):
        manifests.bind_manifest_proposals(report, bundle=bundle, index=index,
            reviewer_record={"reviewer_id": "fixture", "review_method": "caller_declaration", "rationale": "Authored test."})


def test_same_value_keeps_all_citations():
    index, bundle = setup((10, 10))
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    assert len(report["proposals"]) == 1
    assert len(report["proposals"][0]["citations"]) == 2


@pytest.mark.parametrize("change", ["foreign_ref", "sort", "projection", "duplicate_slot", "unknown_field"])
def test_foreign_or_malformed_manifests_cannot_supply_a_value(change):
    def mutate(value):
        if change == "foreign_ref":
            value["selected_source_ref"]["ref_id"] = "ref:foreign_same_text"
        elif change == "sort":
            value["slots"][0]["sort"] = "scope"
        elif change == "projection":
            value["slots"][0]["projection_ids"] = ["unrelated"]
        elif change == "duplicate_slot":
            value["slots"].append(value["slots"][0].copy())
        else:
            value["source_semantics_verified"] = True
    index, bundle = setup(mutate=mutate)
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    assert report["status"] == "incomplete"
    assert report["missing_slots"] == ["clock"]
    assert report["diagnostics"]


def test_free_text_has_no_implicit_policy_decoder():
    index, bundle = setup(prose=True)
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    assert report["status"] == "incomplete"
    assert report["parsed_manifest_count"] == 0


def test_rehashed_proposals_do_not_bypass_bundle_replay():
    index, bundle = setup()
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    report["proposals"][0]["value"]["quantity"] = 999
    report["proposal_sha256"] = context_digest({k: v for k, v in report.items() if k != "proposal_sha256"})
    with pytest.raises(ValueError, match="differ_from_replay"):
        manifests.bind_manifest_proposals(report, bundle=bundle, index=index,
            reviewer_record={"reviewer_id": "fixture", "review_method": "caller_declaration", "rationale": "Authored test."})


def test_duplicate_json_keys_are_not_silently_overwritten():
    with pytest.raises(ValueError, match="duplicate_manifest_key"):
        manifests._decode('{"quantity":10,"quantity":20}')


def test_producer_drift_is_rejected(monkeypatch):
    index, bundle = setup()
    monkeypatch.setattr(manifests, "_SOURCE_SHA", "0" * 64)
    with pytest.raises(ValueError, match="producer_changed_since_import"):
        manifests.prepare_manifest_binding_proposals(bundle, index=index)


def test_values_can_be_bound_with_exact_quotes_but_not_semantic_authority():
    index, bundle = setup()
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    bindings = manifests.bind_manifest_proposals(report, bundle=bundle, index=index,
        reviewer_record={"reviewer_id": "authored-fixture", "review_method": "machine_review_declared",
            "rationale": "Exact structured fixture only."})
    record, = [binding.to_dict() for binding in bindings]
    assert record["value"] == {"quantity": 10}
    assert record["mode"] == "source_cited_declaration"
    assert record["source_evidence_cited"] is True
    assert record["source_binding_verified"] is record["reviewer_authenticated"] is record["qualified"] is False


def test_manifests_larger_than_the_quote_limit_are_not_immediately_bindable():
    def mutate(value):
        value["scope_note"] = "s" * 2000
        value["slots"][0]["value"] = {"large": "v" * 2000}
    index, bundle = setup(mutate=mutate)
    report = manifests.prepare_manifest_binding_proposals(bundle, index=index)
    assert report["status"] == "incomplete"
    assert report["diagnostics"][0]["reason"] == "manifest_text_byte_limit"
