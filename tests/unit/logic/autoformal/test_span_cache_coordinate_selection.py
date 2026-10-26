"""Selected source occurrences retain complete context without importing extras."""
from copy import deepcopy
import json

import pytest

from ipfs_datasets_py.logic.autoformal.span_cache import (
    SpanCache, SpanCacheError, SpanCacheTextLimits,
    validate_source_coordinate_rows, write_fresh_source_coordinate_cache,
)
from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
    inventory_uscode_documents, inventory_uscode_source_coordinates,
    uscode_source_coordinates_sha256,
)


def prepared(text="  Ω agency shall act.\r\nCafé may file!\tThe officer must report.  "):
    documents = [{"entry_cid": "fixture-source", "legal_id": "usc:10:1", "title": "10",
                  "section": "1", "text": text, "raw_metadata": {"z": "last", "a": "first"}}]
    report = inventory_uscode_source_coordinates(documents, query="fixture", release_id="fixture-release")
    pin = uscode_source_coordinates_sha256(report)
    spans = inventory_uscode_documents(documents, query="fixture", release_id="fixture-release")["spans"]
    return documents, report, pin, spans


def enqueue(cache, data, selected=None):
    documents, report, pin, _ = data
    return cache.enqueue_source_coordinates(report, documents, expected_report_sha256=pin,
        query="fixture", release_id="fixture-release", selected_span_ids=selected)


def snapshot(cache):
    return {name: cache._db.execute(f"SELECT * FROM {name} ORDER BY ALL").fetchall()
            for name in ("span_cache", "cache_meta", "sealed_terms", "span_terms")}


@pytest.fixture
def owner(tmp_path):
    cache = SpanCache(tmp_path / "selected.duckdb")
    try:
        yield cache
    finally:
        cache.close()


def test_selected_middle_occurrence_keeps_full_report_and_original_ordinal(owner):
    data = prepared()
    assert len(data[3]) == 3
    selected = [data[3][1]["source_span_id"]]
    assert enqueue(owner, data, selected) == 1
    exported = owner.export_source_coordinates(data[2], source_span_ids=selected)
    assert exported["report"] == data[1]
    assert exported["report"]["documents"][0]["source_text"] == data[0][0]["text"]
    assert validate_source_coordinate_rows(exported["report"], exported["rows"],
        expected_report_sha256=data[2]) == [1]
    assert [row["source_span_id"] for row in owner.pending()] == selected
    assert all(value is False for value in json.loads(exported["rows"][0]["source_provenance_json"])["authority"].values())


def test_subset_retry_then_second_subset_stores_one_report_without_extra_spans(owner):
    data = prepared()
    first, second = [data[3][1]["source_span_id"]], [data[3][2]["source_span_id"]]
    assert enqueue(owner, data, first) == 1
    before = snapshot(owner)
    assert enqueue(owner, data, first) == 0
    assert snapshot(owner) == before
    assert enqueue(owner, data, second) == 1
    assert {row["source_span_id"] for row in owner.pending()} == set(first + second)
    assert owner._db.execute("SELECT count(*) FROM cache_meta WHERE key LIKE 'source_coordinates:report:%'").fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["empty", "duplicate", "unknown", "string", "bool", "many"])
def test_invalid_selection_refuses_without_any_persistent_mutation(owner, kind):
    data = prepared()
    span_id = data[3][0]["source_span_id"]
    choices = {"empty": [], "duplicate": [span_id, span_id], "unknown": ["absent"],
               "string": span_id, "bool": [True], "many": [f"s-{i}" for i in range(513)]}
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        enqueue(owner, data, choices[kind])
    assert snapshot(owner) == before


def test_selected_legacy_conflict_rolls_back_other_fresh_rows_and_metadata(owner):
    data = prepared()
    owner.enqueue([data[3][2]])
    before = snapshot(owner)
    with pytest.raises(SpanCacheError, match="no backfill"):
        enqueue(owner, data, [data[3][0]["source_span_id"], data[3][2]["source_span_id"]])
    assert snapshot(owner) == before


@pytest.mark.parametrize("mutation", ["ordinal", "text", "legal_id", "pin", "authority", "extra", "duplicate"])
def test_portable_rows_reject_resealed_or_substituted_occurrences(owner, mutation):
    data = prepared()
    selected = [data[3][1]["source_span_id"]]
    enqueue(owner, data, selected)
    exported = owner.export_source_coordinates(data[2], source_span_ids=selected)
    rows = deepcopy(exported["rows"])
    ref = json.loads(rows[0]["source_provenance_json"])
    if mutation == "ordinal": ref["span_index"] = 0
    if mutation == "pin": ref["report_sha256"] = "0" * 64
    if mutation == "authority": ref["authority"]["admitted"] = True
    if mutation == "extra": ref["invented"] = False
    if mutation == "text": rows[0]["text"] += " changed"
    if mutation == "legal_id": rows[0]["legal_id"] = "usc:10:2"
    rows[0]["source_provenance_json"] = json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if mutation == "duplicate": rows.append(deepcopy(rows[0]))
    with pytest.raises(SpanCacheError):
        validate_source_coordinate_rows(exported["report"], rows, expected_report_sha256=data[2])


def test_unselected_row_cannot_be_exported_with_inferred_coordinates(owner):
    data = prepared()
    enqueue(owner, data, [data[3][1]["source_span_id"]])
    with pytest.raises(SpanCacheError, match="no backfill"):
        owner.export_source_coordinates(data[2], source_span_ids=[data[3][0]["source_span_id"]])


def test_fresh_catalog_replay_on_another_path_enqueues_only_selected_rows(tmp_path, owner):
    data = prepared()
    selected = [data[3][2]["source_span_id"]]
    enqueue(owner, data, selected)
    exported = owner.export_source_coordinates(data[2], source_span_ids=selected)
    target = tmp_path / "another-machine.duckdb"
    receipt = write_fresh_source_coordinate_cache(target, exported["report"], data[0],
        expected_report_sha256=data[2], query="fixture", release_id="fixture-release", selected_span_ids=selected)
    assert receipt == {"spans_enqueued": 1, "stats": {"sealed": 0, "gaps": 0, "pending": 1, "terms": 0}}
    other = SpanCache(target)
    try:
        assert other.read_source_coordinate_report(data[2]) == data[1]
        assert other.export_source_coordinates(data[2], source_span_ids=selected) == exported
        assert [row["source_span_id"] for row in other.pending()] == selected
    finally:
        other.close()
    assert not list(tmp_path.glob(".uscode-raw-ingest-*"))


def test_independent_stale_pin_and_existing_target_refuse_before_publication(tmp_path):
    data = prepared()
    target = tmp_path / "fresh.duckdb"
    with pytest.raises(ValueError):
        write_fresh_source_coordinate_cache(target, data[1], data[0], expected_report_sha256="0" * 64,
            query="fixture", release_id="fixture-release", selected_span_ids=[data[3][0]["source_span_id"]])
    assert not target.exists() and not list(tmp_path.glob(".uscode-raw-ingest-*"))
    target.write_bytes(b"foreign")
    before = target.stat()
    with pytest.raises(ValueError, match="fresh catalog"):
        write_fresh_source_coordinate_cache(target, data[1], data[0], expected_report_sha256=data[2],
            query="fixture", release_id="fixture-release")
    assert target.read_bytes() == b"foreign"
    after = target.stat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)


def test_only_selected_text_is_charged_to_cache_limits_after_complete_replay(tmp_path):
    data = prepared("The agency shall keep " + "x" * 64 + ". May file.")
    cache = SpanCache(tmp_path / "text-limits.duckdb", text_limits=SpanCacheTextLimits(max_text_bytes=24))
    try:
        assert len(data[3]) == 2
        assert enqueue(cache, data, [data[3][1]["source_span_id"]]) == 1
        assert cache.read_source_coordinate_report(data[2]) == data[1]
    finally:
        cache.close()


def test_metadata_failure_rolls_back_selected_rows_and_report(owner, monkeypatch):
    data = prepared()
    before = snapshot(owner)
    def fail(*args, **kwargs):
        raise RuntimeError("injected metadata failure")
    monkeypatch.setattr(owner, "_set_meta", fail)
    with pytest.raises(RuntimeError, match="injected metadata failure"):
        enqueue(owner, data, [data[3][1]["source_span_id"]])
    assert snapshot(owner) == before
