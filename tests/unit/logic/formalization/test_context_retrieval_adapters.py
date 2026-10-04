"""Pinned context joins, including a real offline sparse GraphRAG BM25 query."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.context_resolution import (
    ContextSpan, BoundedContextIndex, prepare_context_bundle, validate_context_bundle, context_digest)
from ipfs_datasets_py.logic.formalization.context_retrieval_adapters import PinnedSparseContextRetriever
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

REPO = "justicedao/open-us-law-sparse-graphrag"
REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"


def span(text="FOIA agency records", *, identity="span:a", partition="train", start=0, end=None):
    end = len(text.encode()) if end is None else end
    ref = SourceRef(ref_id="source:" + identity, source_uri="fixture:" + identity,
        source_id=identity, source_revision=REVISION, content_sha256=hashlib.sha256(text.encode()).hexdigest())
    location = SourceSpan(span_id=identity, source_ref_id=ref.ref_id, start_byte=start, end_byte=end)
    return ContextSpan.from_source(source_ref=ref, span=location, source_text=text, partition=partition)


def response(text="FOIA agency records", *, entry="entry-a", query="foia", score=1.0):
    # Explicit result double for integrity boundary tests, not remote execution.
    return {"mode": "bm25", "query": query,
        "results": [{"entry_cid": entry, "score": score, "text": text}],
        "fetch_trace": {"repo_id": REPO, "revision": REVISION, "route_justified": True,
            "verification_state": "verified", "files": []},
        "complete": True, "stop_reason": None, "limits": {"max_bytes": 1000000}, "usage": {"bytes": 100}}


def adapter(result, *, spans=None, bindings=None, calls=None):
    def searcher(query, **kwargs):
        if calls is not None:
            calls.append((query, kwargs))
        return deepcopy(result)
    return PinnedSparseContextRetriever(searcher=searcher, spans=spans or [span()],
        entry_bindings=bindings or [{"entry_cid": "entry-a", "span_id": "span:a"}], repo_id=REPO, revision=REVISION)


def test_raw_unicode_and_whitespace_are_not_normalized():
    text = "Policy:\n  confirmation\u00a0expires after ５ ticks.\n"
    start, end = text.encode().index(b"  confirmation"), len(text.encode()) - 1
    selected = span(text, start=start, end=end)
    result = adapter(response(text), spans=[selected]).search("foia", partition="train").to_dict()
    candidate = result["candidates"][0]
    assert candidate["raw_source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert candidate["text"] == text.encode()[start:end].decode()
    assert candidate["span"]["start_byte"] == start


@pytest.mark.parametrize("mutation", ("body", "revision", "repo", "query", "mode", "route", "unverified", "missing_text", "score"))
def test_mismatched_hydrated_evidence_is_refused(mutation):
    value = response()
    if mutation == "body":
        value["results"][0]["text"] += " "
    elif mutation in {"revision", "repo"}:
        value["fetch_trace"]["revision" if mutation == "revision" else "repo_id"] = "0" * 40
    elif mutation in {"query", "mode"}:
        value[mutation] = "changed"
    elif mutation == "route":
        value["fetch_trace"]["route_justified"] = False
    elif mutation == "unverified":
        value["fetch_trace"]["verification_state"] = "unverified"
    elif mutation == "missing_text":
        value["results"][0].pop("text")
    else:
        value["results"][0]["score"] = True
    with pytest.raises(ValueError):
        adapter(value).search("foia", partition="train")


def test_remote_results_cannot_fabricate_new_context_spans():
    result = adapter(response(entry="not-registered")).search("foia", partition="train").to_dict()
    assert result["status"] == "unresolved"
    assert result["candidates"] == []
    assert result["exclusions"][0]["reason"] == "entry_not_bound_to_existing_context_inventory"


def test_partition_filter_preserves_holdout_boundary():
    result = adapter(response(), spans=[span(partition="test")]).search("foia", partition="train").to_dict()
    assert result["candidates"] == []
    assert result["exclusions"][0]["reason"] == "partition_excluded"


def test_candidate_bounds_do_not_masquerade_as_backend_completion():
    result = adapter(response()).search("foia", partition="train", max_bytes=1).to_dict()
    assert result["status"] == "partial"
    assert result["backend_complete"] is True
    assert result["candidate_bytes"] == 0
    assert result["exclusions"][0]["reason"] == "returned_context_top_k_or_byte_bound"
    value = response()
    value.update(complete=False, stop_reason="max_bytes")
    result = adapter(value).search("foia", partition="train").to_dict()
    assert result["status"] == "partial"
    assert result["backend_complete"] is False
    assert result["backend_stop_reason"] == "max_bytes"


def test_exact_search_handoff_and_detached_results():
    calls = []
    observed = adapter(response(), calls=calls).search("foia", partition="train", top_k=2)
    assert calls == [("foia", {"top_k": 2, "hydrate": True, "include_content": True})]
    assert observed.ranked_span_ids() == (("span:a", 1.0),)
    changed = observed.to_dict()
    changed["candidates"][0]["text"] = "changed"
    assert observed.to_dict()["candidates"][0]["text"] == "FOIA agency records"
    for field in ("proof_authority", "source_semantics_verified", "slots_filled", "qualified", "admitted", "enqueued"):
        assert observed.to_dict()[field] is False


def test_top_k_applies_after_one_entry_maps_to_multiple_spans():
    text = "FOIA agency records"
    spans = [span(text, identity="span:a", start=0, end=4), span(text, identity="span:b", start=5)]
    bindings = [{"entry_cid": "entry-a", "span_id": item.to_dict()["span"]["span_id"]} for item in spans]
    result = adapter(response(), spans=spans, bindings=bindings).search("foia", partition="train", top_k=1).to_dict()
    assert len(result["candidates"]) == 1
    assert result["status"] == "partial"


def test_invalid_inventory_and_mutable_corpus_revision_are_rejected():
    with pytest.raises(ValueError, match="immutable"):
        PinnedSparseContextRetriever(searcher=lambda **kwargs: {}, spans=[span()],
            entry_bindings=[{"entry_cid": "entry-a", "span_id": "span:a"}], repo_id=REPO, revision="main")
    with pytest.raises(ValueError, match="existing context span"):
        adapter(response(), bindings=[{"entry_cid": "entry-a", "span_id": "missing"}])
    with pytest.raises(ValueError, match="duplicate"):
        adapter(response(), bindings=[{"entry_cid": "entry-a", "span_id": "span:a"}] * 2)


def test_real_offline_sparse_graphrag_bm25_and_exact_context_join(tmp_path):
    # Reuse the repository's miniature Parquet release builder, then execute
    # the actual public query client with LocalRootTransport. No result double,
    # HTTP transport, vector encoder, downloaded index or weights is involved.
    fixture_path = Path(__file__).resolve().parents[4] / "tests/unit/processors/legal_data/test_open_us_law_query.py"
    spec = importlib.util.spec_from_file_location("context_sparse_offline_release_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    client = fixture._client(tmp_path)
    search = PinnedSparseContextRetriever(searcher=client.bm25_search, spans=[span()],
        entry_bindings=[{"entry_cid": "entry-a", "span_id": "span:a"}], repo_id=REPO, revision=REVISION)
    result = search.search("foia", partition="train", top_k=3).to_dict()
    assert result["status"] == "candidates"
    assert result["candidates"][0]["span_id"] == "span:a"
    assert result["candidates"][0]["text"] == "FOIA agency records"
    paths = [row["relative_path"] for row in result["fetch_trace"]["files"]]
    assert any("bm25/postings" in path for path in paths)
    assert any("corpus" in path for path in paths)
    assert not any("vectors" in path for path in paths)
    assert result["fetch_trace"]["verification_state"] == "verified"
    assert result["backend_complete"] is True
    assert result["slots_filled"] is result["admitted"] is False
    selected = span("Interpret an agency requirement.", identity="span:anchor")
    index = BoundedContextIndex([selected, span()], revision=REVISION)
    bundle = prepare_context_bundle(index, source_span_id="span:anchor", slots=[{
        "slot_id": "definition", "question": "foia", "sort": "definition", "projection_ids": ["legal:example"]}],
        sparse_observations=[result])
    assert validate_context_bundle(bundle, index=index) is True
    assert bundle["source_resolved_slot_count"] == 0
    assert bundle["external_index_partition_isolation_verified"] is False
    assert any(e["method"] == "pinned_sparse_bm25" for e in bundle["slots"][0]["candidates"][0]["retrieval"])


@pytest.mark.parametrize("field", ("text", "source_ref", "span", "partition", "span_id", "excerpt_sha256"))
def test_rehashed_sparse_tampering_is_rejected_by_context_index(field):
    result = adapter(response()).search("foia", partition="train").to_dict()
    hit = result["candidates"][0]
    if field == "source_ref":
        hit[field]["content_sha256"] = "0" * 64
    elif field == "span":
        hit[field]["start_byte"] = 1
    else:
        hit[field] = "changed"
    result["report_sha256"] = context_digest({k: v for k, v in result.items() if k != "report_sha256"})
    index = BoundedContextIndex([span("Interpret agency requirements.", identity="span:anchor"), span()], revision=REVISION)
    with pytest.raises(ValueError):
        prepare_context_bundle(index, source_span_id="span:anchor", slots=[{
            "slot_id": "definition", "question": "foia", "sort": "definition", "projection_ids": ["legal:example"]}],
            sparse_observations=[result])
