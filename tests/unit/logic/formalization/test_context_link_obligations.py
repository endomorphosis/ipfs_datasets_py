from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.formalization.context_resolution import (
    ContextSpan, BoundedContextIndex, prepare_context_bundle, context_digest)
from ipfs_datasets_py.logic.formalization.context_link_obligations import (
    prepare_context_link_obligation, validate_context_link_obligation)


def inputs():
    text = "Deadline starts on receipt. Publish within ten days."
    ref = SourceRef("ref:fixture", "fixture://context", "fixture", "v1", hashlib.sha256(text.encode()).hexdigest())
    split = text.index("Publish")
    spans = [ContextSpan.from_source(source_ref=ref, span=SourceSpan(key, ref.ref_id, start, end),
        source_text=text, partition="authored") for key, start, end in [
            ("neighbor", 0, split), ("selected", split, len(text))]]
    index = BoundedContextIndex(spans, revision="v1")
    bundle = prepare_context_bundle(index, source_span_id="selected", slots=[{
        "slot_id": "origin", "question": "deadline receipt", "sort": "temporal_anchor", "projection_ids": ["O", "T"]}],
        fixtures=[{"slot_id": "origin", "value": {"trigger": "fixture_receipt"}, "rationale": "Provisional."}])
    return index, bundle


def obligation(index, bundle, **kwargs):
    return prepare_context_link_obligation(bundle, index=index, slot_id="origin", candidate_span_id="neighbor",
        proposed_binding={"trigger": "notice_receipt"}, relation="deadline_trigger", **kwargs)


def test_native_tactician_plan_retains_sources_assumptions_and_blocks_untyped_hammer():
    index, bundle = inputs()
    report = obligation(index, bundle)
    assert validate_context_link_obligation(report, bundle=bundle, index=index)
    assert report["tactician_plan_type"] == "ProofSearchPlan"
    assert report["projection_ids"] == ["O", "T"]
    assert len(report["assumptions"]) == 2
    assert all(a["discharged"] is False for a in report["assumptions"])
    assert report["hammer_handoff"]["execution_ready"] is False
    assert report["hammer_handoff"]["premises_registered"] == 0
    assert report["supervisor_importable"] is report["enqueued"] is report["source_resolved"] is False
    assert report["candidate_source"]["text"].startswith("Deadline starts")


def test_missing_candidate_and_unknown_relation_are_not_accepted():
    index, bundle = inputs()
    with pytest.raises(ValueError, match="retrieved_candidate"):
        prepare_context_link_obligation(bundle, index=index, slot_id="origin", candidate_span_id="unseen",
            proposed_binding="receipt", relation="deadline_trigger")
    with pytest.raises(ValueError, match="unsupported_context_link_relation"):
        prepare_context_link_obligation(bundle, index=index, slot_id="origin", candidate_span_id="neighbor",
            proposed_binding="receipt", relation="automatically_proves")


@pytest.mark.parametrize("key", ["admitted", "source_resolved", "enqueued", "supervisor_importable", "assumptions", "tactician_plan"])
def test_rehashed_plan_authority_or_context_tampering_is_rejected(key):
    index, bundle = inputs()
    report = obligation(index, bundle)
    report[key] = [] if key == "assumptions" else {} if key == "tactician_plan" else True
    report["obligation_sha256"] = context_digest({k: v for k, v in report.items() if k != "obligation_sha256"})
    with pytest.raises(ValueError, match="differs_from_replay"):
        validate_context_link_obligation(report, bundle=bundle, index=index)


def test_tampered_retrieval_cannot_become_a_link_plan():
    index, bundle = inputs()
    bundle["slots"][0]["source_resolved"] = True
    with pytest.raises(ValueError, match="differs_from_index_replay"):
        obligation(index, bundle)
