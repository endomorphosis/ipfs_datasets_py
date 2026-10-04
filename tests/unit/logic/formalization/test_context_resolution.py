"""Context suggestions and provisional assumptions never become source truth."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.formalization import context_resolution as context


def span(key, text, *, document=None, revision="r1", partition="train", start=0, end=None):
    ref = SourceRef(ref_id="ref:" + (document or key), source_uri="fixture://" + (document or key),
        source_id=document or key, source_revision=revision, content_sha256=hashlib.sha256(text.encode()).hexdigest())
    return context.ContextSpan.from_source(source_ref=ref,
        span=SourceSpan(key, ref.ref_id, start, len(text.encode()) if end is None else end),
        source_text=text, partition=partition)


def slots():
    return [{"slot_id": "origin", "question": "deadline begins receipt notice", "sort": "temporal_anchor",
        "projection_ids": ["deontic", "temporal"]}]


def corpus():
    text = "The deadline begins upon receipt. Publish within ten days."
    split = text.index("Publish")
    return context.BoundedContextIndex([
        span("previous", text, document="section", end=split),
        span("selected", text, document="section", start=split),
        span("definition", "Receipt means service of notice."),
        span("clock", "Deadline days use a discrete clock."),
        span("holdout", "The deadline begins upon receipt of notice.", partition="holdout")],
        edges=[{"source_span_id": "selected", "target_span_id": "definition", "relation": "definition"},
            {"source_span_id": "definition", "target_span_id": "clock", "relation": "citation"},
            {"source_span_id": "selected", "target_span_id": "holdout", "relation": "supports"}], revision="fixture-index-r1")


def test_neighbors_bm25_and_two_hop_graph_are_candidates_with_source_evidence():
    index = corpus()
    report = context.prepare_context_bundle(index, source_span_id="selected", slots=slots())
    assert context.validate_context_bundle(report, index=index)
    candidates = {r["span_id"]: r for r in report["slots"][0]["candidates"]}
    assert set(candidates) == {"previous", "definition", "clock"}
    assert any(r["method"] == "neighbor" for r in candidates["previous"]["retrieval"])
    assert any(r["method"] == "bm25" for r in candidates["definition"]["retrieval"])
    graph = next(r for r in candidates["clock"]["retrieval"] if r["method"] == "explicit_graph")
    assert len(graph["path"]) == 2
    assert report["source_resolved_slot_count"] == 0
    assert all(report[k] is False for k in context.AUTHORITY)
    assert report["slots"][0]["status"] == "unresolved"


def test_provisional_values_do_not_fill_source_slots_and_are_removable():
    index = corpus()
    report = context.prepare_context_bundle(index, source_span_id="selected", slots=slots(),
        fixtures=[{"slot_id": "origin", "value": {"trigger": "authored_notice_received"},
            "rationale": "Temporary interpretation to exercise the projection."}])
    assert report["fixture_slot_count"] == 1
    assert report["slots"][0]["status"] == "provisional"
    assert report["slots"][0]["assumption"]["source_backed"] is False
    assert report["source_resolved_slot_count"] == 0
    original = context.prepare_context_bundle(index, source_span_id="selected", slots=slots())
    assert original["selected_source"] == report["selected_source"]
    assert original["bundle_sha256"] != report["bundle_sha256"]


def test_two_projections_share_one_slot_and_context_artifacts_are_deduplicated():
    declared = slots() + [{**slots()[0], "slot_id": "clock", "sort": "temporal_model"}]
    report = context.prepare_context_bundle(corpus(), source_span_id="selected", slots=declared)
    assert len(report["slots"][0]["projection_ids"]) == 2
    assert len(report["artifacts"]) == 3
    assert report["telemetry"]["unique_context_bytes"] == sum(len(r["text"].encode()) for r in report["artifacts"].values())


def test_global_byte_budget_is_reported_without_claiming_resolution():
    report = context.prepare_context_bundle(corpus(), source_span_id="selected", slots=slots(),
        limits=context.ContextLimits(max_context_bytes=10))
    assert report["telemetry"]["unique_context_bytes"] <= 10
    assert "context_byte_limit" in report["diagnostics"]
    assert report["status"] == "incomplete"


def test_no_parent_invented_for_isolated_fixture():
    index = context.BoundedContextIndex([span("selected", "Publish within ten days.")], revision="r1")
    report = context.prepare_context_bundle(index, source_span_id="selected", slots=slots())
    assert report["slots"][0]["candidates"] == []
    assert report["slots"][0]["source_resolved"] is False


@pytest.mark.parametrize("change", ["text", "authority", "assumption", "path", "slot"])
def test_rehashed_tamper_fails_replay(change):
    index = corpus()
    report = context.prepare_context_bundle(index, source_span_id="selected", slots=slots())
    if change == "text":
        next(iter(report["artifacts"].values()))["text"] = "Invented context."
    elif change == "authority":
        report["admitted"] = True
    elif change == "assumption":
        report["slots"][0]["assumption"] = {"source_backed": True}
    elif change == "path":
        report["slots"][0]["candidates"][0]["retrieval"] = []
    else:
        report["slots"][0]["source_resolved"] = True
    report["bundle_sha256"] = context.context_digest({k: v for k, v in report.items() if k != "bundle_sha256"})
    with pytest.raises(ValueError, match="differs_from_index_replay"):
        context.validate_context_bundle(report, index=index)


def test_span_checks_exact_raw_bytes_unicode_and_source_hash():
    text = "é receipt"
    with pytest.raises(ValueError, match="span_splits_unicode"):
        span("s", text, start=1)
    valid = span("s", text)
    assert valid.to_dict()["text"] == text
    ref = SourceRef.from_dict(valid.to_dict()["source_ref"])
    source_span = SourceSpan.from_dict(valid.to_dict()["span"])
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        context.ContextSpan.from_source(source_ref=ref, span=source_span, source_text=text + "!", partition="train")
    with pytest.raises(TypeError, match="from_source"):
        context.ContextSpan(valid._json)


def test_revisions_cannot_mix_and_missing_graph_endpoints_are_rejected():
    with pytest.raises(ValueError, match="mixed_document_revisions"):
        context.BoundedContextIndex([span("a", "old", document="doc"), span("b", "new", document="doc", revision="r2")], revision="index-r2")
    with pytest.raises(ValueError, match="dangling_context_edge"):
        context.BoundedContextIndex([span("a", "text")], revision="r1", edges=[
            {"source_span_id": "a", "target_span_id": "absent", "relation": "citation"}])


def test_deadline_reports_partial_work(monkeypatch):
    ticks = iter([0.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr(context, "monotonic", lambda: next(ticks, 10.0))
    report = context.prepare_context_bundle(corpus(), source_span_id="selected", slots=slots())
    assert "deadline_exhausted" in report["diagnostics"]
    assert report["telemetry"]["bm25_queries"] == 0


def test_partition_isolation_holds_at_every_graph_hop():
    index = context.BoundedContextIndex([span("s", "alpha"), span("h", "middle", partition="holdout"),
        span("t", "unrelated")], revision="r1", edges=[
            {"source_span_id": "s", "target_span_id": "h", "relation": "citation"},
            {"source_span_id": "h", "target_span_id": "t", "relation": "citation"}])
    report = context.prepare_context_bundle(index, source_span_id="s", slots=slots())
    assert report["artifacts"] == {}


def test_detached_outputs_do_not_mutate_index():
    index = corpus()
    original = index.to_dict()
    changed = index.to_dict()
    changed["spans"]["selected"]["text"] = "changed"
    assert index.to_dict() == original


def test_source_drift_invalidates_preparation_and_replay(monkeypatch):
    index = corpus()
    bundle = context.prepare_context_bundle(index, source_span_id="selected", slots=slots())
    monkeypatch.setitem(context._PRODUCER_PINS, "processors/retrieval.py", "0" * 64)
    with pytest.raises(ValueError, match="producer_changed_since_import"):
        context.prepare_context_bundle(index, source_span_id="selected", slots=slots())
    with pytest.raises(ValueError, match="producer_changed_since_import"):
        context.validate_context_bundle(bundle, index=index)
