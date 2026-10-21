"""Exact authored source coordinates through one private native cache owner.

No parser, model, solver, worker process, network client or publisher runs.
These fixtures establish transport and custody, not statutory correctness.
"""
from copy import deepcopy
import hashlib
import json
import threading

import pytest

from ipfs_datasets_py.logic.autoformal import span_cache as cache_module
from ipfs_datasets_py.logic.autoformal import uscode_ingest as ingest
from ipfs_datasets_py.logic.autoformal.span_cache import (
    SpanCache, SpanCacheError, SpanCacheTextLimits,
)
from ipfs_datasets_py.logic.autoformal.span_cache_claims import SpanClaimError


QUERY = "fixture:exact-supplied-source"
RELEASE = "fixture-release"
REVISION = "a" * 40


def document(text=" \tΩ agency shall act.\r\nCafé may file!  ", section="1"):
    return {"legal_id": f"usc:10:{section}", "title": "10", "section": section,
            "text": text, "entry_cid": f"fixture-document-{section}"}


def case(documents=None):
    documents = [document()] if documents is None else documents
    report = ingest.inventory_uscode_source_coordinates(
        documents, query=QUERY, release_id=RELEASE)
    pin = ingest.uscode_source_coordinates_sha256(report)
    legacy = ingest.inventory_uscode_documents(
        documents, query=QUERY, release_id=RELEASE)
    return documents, report, pin, legacy["spans"]


def enqueue(cache, prepared):
    documents, report, pin, _ = prepared
    return cache.enqueue_source_coordinates(
        report, documents, expected_report_sha256=pin,
        query=QUERY, release_id=RELEASE)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def reseal(report):
    report.pop("source_coordinates_sha256")
    report["source_coordinates_sha256"] = digest(wire(report))
    return report


def snapshot(cache):
    return {name: cache._db.execute(f"SELECT * FROM {name} ORDER BY ALL").fetchall()
            for name in ("span_cache", "cache_meta", "sealed_terms", "span_terms")}


def reference(cache, span):
    value = cache._source_coordinate_provenance(
        span["source_span_id"], span["text"], span["legal_id"])
    return json.loads(value["source_provenance_json"]) if value else None


def report_key(pin):
    return cache_module.SOURCE_COORDINATE_REPORT_PREFIX + pin


def binding_key(cache, span_id):
    rows = cache._db.execute("SELECT key,value FROM cache_meta ORDER BY key").fetchall()
    return next(key for key, value in rows
                if key.startswith(cache_module.SOURCE_COORDINATE_BINDING_PREFIX)
                and json.loads(value)["source_span_id"] == span_id)


@pytest.fixture
def owner(tmp_path):
    cache = SpanCache(tmp_path / "coordinates.duckdb")
    cache._db.execute("SET threads=1")
    try:
        yield cache
    finally:
        if not cache._claim_owner_closed:
            cache.close()


def test_exact_unicode_source_report_and_normalized_span_references(owner):
    prepared = case([document(" \tΩ\u00a0agency shall\r\nact.\r\nCafé may file!  ")])
    documents, report, pin, spans = prepared
    assert enqueue(owner, prepared) == 2
    assert owner.read_source_coordinate_report(pin) == report
    raw = documents[0]["text"]
    for index, span in enumerate(spans):
        ref = reference(owner, span)
        assert ref["schema"] == "span-cache-source-coordinate-reference/v1"
        assert ref["report_sha256"] == pin and ref["span_index"] == index
        assert ref["source_span_id"] == span["source_span_id"]
        assert ref["source_sha256"] == digest(span["text"])
        assert ref["legal_id_sha256"] == digest(span["legal_id"])
        coordinates = ref["coordinates"]
        expected = report["spans"][index]
        assert raw[coordinates["source_char_start"]:coordinates["source_char_end"]] == expected["source_text"]
        selected = raw.encode("utf-8")[coordinates["source_utf8_byte_start"]:coordinates["source_utf8_byte_end"]]
        assert selected.decode("utf-8") == expected["source_text"]
        assert "text" not in coordinates and "source_text" not in coordinates
        assert all(value is False for value in ref["authority"].values())
        assert ref["coordinate_origin"]["parquet_file_byte_mapping_verified"] is False
    assert spans[0]["text"] != report["spans"][0]["source_text"]


def test_full_report_stored_once_without_another_catalog_or_table(owner):
    prepared = case()
    tables = owner._db.execute("SHOW TABLES").fetchall()
    enqueue(owner, prepared)
    assert owner._db.execute("SHOW TABLES").fetchall() == tables
    rows = owner._db.execute("SELECT key,value FROM cache_meta ORDER BY key").fetchall()
    reports = [(key, json.loads(value)) for key, value in rows
               if key.startswith(cache_module.SOURCE_COORDINATE_REPORT_PREFIX)]
    bindings = [(key, json.loads(value)) for key, value in rows
                if key.startswith(cache_module.SOURCE_COORDINATE_BINDING_PREFIX)]
    assert reports == [(report_key(prepared[2]), prepared[1])]
    assert len(bindings) == len(prepared[3]) == 2
    assert all("source_text" not in value and "text" not in value for _, value in bindings)


def test_reopen_preserves_report_and_optional_pending_and_claim_fields(tmp_path):
    prepared = case()
    path = tmp_path / "durable.duckdb"
    cache = SpanCache(path)
    cache._db.execute("SET threads=1")
    try:
        enqueue(cache, prepared)
        original = {row["source_span_id"]: row["source_provenance_json"]
                    for row in cache.pending()}
    finally:
        cache.close()
    cache = SpanCache(path)
    cache._db.execute("SET threads=1")
    try:
        assert cache.read_source_coordinate_report(prepared[2]) == prepared[1]
        assert {row["source_span_id"]: row["source_provenance_json"]
                for row in cache.pending()} == original
        claims = cache.claim_batch("fixture-worker")
        assert {row["source_span_id"]: row["source_provenance_json"]
                for row in claims} == original
    finally:
        cache.close()


def test_exact_retry_is_idempotent_and_does_not_rewrite_metadata(owner):
    prepared = case()
    assert enqueue(owner, prepared) == 2
    before = snapshot(owner)
    assert enqueue(owner, prepared) == 0
    assert snapshot(owner) == before


def test_existing_legacy_row_cannot_be_backfilled_from_new_coordinate_report(owner):
    prepared = case([document("Agency shall act.")])
    owner.enqueue(prepared[3])
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        enqueue(owner, prepared)
    assert snapshot(owner) == before
    assert "source_provenance_json" not in owner.pending()[0]


def test_different_raw_occurrence_cannot_replace_same_normalized_span_identity(owner):
    first = case([document("Agency shall act.")])
    second = case([document(" \r\nAgency\tshall act. ")])
    assert first[3][0]["source_span_id"] == second[3][0]["source_span_id"]
    assert first[2] != second[2]
    enqueue(owner, first)
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        enqueue(owner, second)
    assert snapshot(owner) == before
    assert owner.read_source_coordinate_report(first[2]) == first[1]


def test_mixed_fresh_and_conflicting_legacy_population_is_wholly_atomic(owner):
    prepared = case([document("Agency shall act."), document("Officer may file.", "2")])
    owner.enqueue([prepared[3][1]])
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        enqueue(owner, prepared)
    assert snapshot(owner) == before


def test_stale_independent_pin_refuses_before_database_mutation(owner):
    prepared = case()
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        owner.enqueue_source_coordinates(
            prepared[1], prepared[0], expected_report_sha256="0" * 64,
            query=QUERY, release_id=RELEASE)
    assert snapshot(owner) == before


@pytest.mark.parametrize("field", ["source_char_end", "source_utf8_byte_end"])
def test_self_resealed_wrong_coordinate_cannot_pass_exact_source_replay(owner, field):
    documents, report, _, spans = case()
    report["spans"][0][field] -= 1
    reseal(report)
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        enqueue(owner, (documents, report, ingest.uscode_source_coordinates_sha256(report), spans))
    assert snapshot(owner) == before


def test_changed_current_text_cannot_inherit_historical_coordinate_metadata(owner):
    prepared = case([document("Agency shall act.")])
    enqueue(owner, prepared)
    span = prepared[3][0]
    replacement = "Agency may act."
    owner._db.execute("UPDATE span_cache SET source_text=?,source_sha256=? WHERE source_span_id=?",
                      [replacement, digest(replacement), span["source_span_id"]])
    assert "source_provenance_json" not in owner.pending()[0]
    assert "source_provenance_json" not in owner.claim_batch("changed-worker")[0]
    assert owner.read_source_coordinate_report(prepared[2]) == prepared[1]


def test_changed_report_metadata_cannot_satisfy_its_stored_pin(owner):
    prepared = case()
    enqueue(owner, prepared)
    changed = deepcopy(prepared[1])
    changed["documents"][0]["source_text"] += " changed"
    owner._set_meta(report_key(prepared[2]), wire(changed))
    with pytest.raises(SpanCacheError):
        owner.read_source_coordinate_report(prepared[2])
    with pytest.raises(SpanCacheError):
        owner.pending()
    damaged = snapshot(owner)
    with pytest.raises(SpanCacheError):
        owner.claim_batch("must-not-claim-corrupt-provenance")
    assert snapshot(owner) == damaged


def test_changed_span_binding_cannot_silently_select_another_occurrence(owner):
    prepared = case()
    enqueue(owner, prepared)
    key = binding_key(owner, prepared[3][0]["source_span_id"])
    changed = json.loads(owner._meta(key))
    changed["span_index"] = 1
    owner._set_meta(key, wire(changed))
    with pytest.raises(SpanCacheError):
        owner.pending()


def test_missing_report_is_not_silently_treated_as_legacy_absence(owner):
    prepared = case()
    enqueue(owner, prepared)
    owner._db.execute("DELETE FROM cache_meta WHERE key=?", [report_key(prepared[2])])
    with pytest.raises(SpanCacheError):
        owner.pending()


def test_legacy_pending_and_claim_shapes_stay_unchanged_without_metadata(owner):
    owner.enqueue([{"source_span_id": "legacy", "legal_id": "fixture:legacy", "text": "Legacy source."}])
    assert owner.pending() == [{"source_span_id": "legacy", "legal_id": "fixture:legacy",
                                "text": "Legacy source.", "status": "pending", "reason": ""}]
    claim = owner.claim_batch("legacy-worker")[0]
    assert set(claim) == {"source_span_id", "legal_id", "text", "claim_worker", "claim_token"}


@pytest.mark.parametrize("agrees", [True, False], ids=["sealed", "gap"])
def test_same_source_seal_or_gap_preserves_coordinate_provenance(owner, agrees):
    prepared = case([document("Agency shall act.")])
    enqueue(owner, prepared)
    span = prepared[3][0]
    original = reference(owner, span)
    claim = owner.claim_batch("fixture-worker")[0]
    result = owner.complete_claimed([{**claim, "agrees": agrees, "decompiled": "Authored fixture.",
        "rule": {"modality": "O", "actor": "agency", "action": "act"},
        "reason": "" if agrees else "fixture_gap"}], code_identity="fixture:no-compiler")
    assert result["sealed"] == int(agrees) and result["gaps"] == int(not agrees)
    assert reference(owner, span) == original
    assert owner.read_source_coordinate_report(prepared[2]) == prepared[1]


@pytest.mark.parametrize("operation", ["enqueue", "read"])
def test_closed_native_owner_refuses_coordinate_operations(owner, operation):
    prepared = case()
    enqueue(owner, prepared)
    owner.close()
    with pytest.raises(SpanCacheError):
        if operation == "enqueue":
            enqueue(owner, prepared)
        else:
            owner.read_source_coordinate_report(prepared[2])


def test_foreign_thread_refuses_both_operations_without_native_connection_access(owner):
    prepared = case()
    enqueue(owner, prepared)
    before = snapshot(owner)
    errors = []
    def foreign():
        for operation in (lambda: enqueue(owner, prepared),
                          lambda: owner.read_source_coordinate_report(prepared[2])):
            try:
                operation()
            except BaseException as error:
                errors.append(error)
    thread = threading.Thread(target=foreign)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(errors) == 2 and all(isinstance(error, SpanCacheError) for error in errors)
    assert snapshot(owner) == before


def test_live_fenced_source_transports_reference_without_expanding_closed_claim(owner):
    prepared = case([document("Agency shall act.")])
    enqueue(owner, prepared)
    span = prepared[3][0]
    clock = [1000.0]
    control = owner.fenced_claims(clock=lambda: clock[0])
    control.bind_sources_fenced("fixture-bind", [{
        "source_span_id": span["source_span_id"], "source_revision": REVISION,
        "source_sha256": digest(span["text"]), "expected_binding": None}])
    claim = control.claim_batch_fenced("fixture-claim", "fixture-worker",
        [span["source_span_id"]], lease_seconds=20)["claims"][0]
    assert "source_provenance_json" not in claim
    observed = control.read_claim_source_fenced(claim)
    assert json.loads(observed["source_provenance_json"]) == reference(owner, span)
    assert observed["text"] == span["text"] and observed["claim"] == claim
    assert all(observed[key] is False for key in ("qualified", "admitted", "formalized", "roundtrip_ok"))
    clock[0] = claim["expires_at"]
    with pytest.raises(SpanClaimError):
        control.read_claim_source_fenced(claim)


def test_persistence_failure_rolls_back_fresh_rows_report_and_bindings(owner, monkeypatch):
    prepared = case()
    before = snapshot(owner)
    original = owner._set_meta
    visited = []
    def interrupt(key, value):
        visited.append(key)
        original(key, value)
        if key.startswith(cache_module.SOURCE_COORDINATE_BINDING_PREFIX):
            raise RuntimeError("injected coordinate persistence failure")
    monkeypatch.setattr(owner, "_set_meta", interrupt)
    with pytest.raises(RuntimeError, match="injected coordinate persistence"):
        enqueue(owner, prepared)
    assert any(key.startswith(cache_module.SOURCE_COORDINATE_REPORT_PREFIX) for key in visited)
    assert snapshot(owner) == before


def test_cache_text_limit_refuses_all_rows_before_coordinate_metadata_persistence(tmp_path):
    cache = SpanCache(tmp_path / "bounded.duckdb",
                      text_limits=SpanCacheTextLimits(max_text_bytes=8))
    cache._db.execute("SET threads=1")
    try:
        prepared = case()
        before = snapshot(cache)
        with pytest.raises(SpanCacheError):
            enqueue(cache, prepared)
        assert snapshot(cache) == before
    finally:
        cache.close()


def test_changed_supplied_document_metadata_refuses_without_persisting_report(owner):
    documents, report, pin, _ = case()
    substituted = deepcopy(documents)
    substituted[0]["entry_cid"] = "different-source-observation"
    before = snapshot(owner)
    with pytest.raises(SpanCacheError):
        owner.enqueue_source_coordinates(report, substituted, expected_report_sha256=pin,
            query=QUERY, release_id=RELEASE)
    assert snapshot(owner) == before


# Pure loader controls exercise the existing bytes API without constructing a
# SpanCache owner, opening a database, or calling model/provider/process code.
def coordinate_loader_payload(report):
    return json.dumps(report, ensure_ascii=False, sort_keys=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def test_coordinate_loader_unicode_complete_population_and_metadata_order():
    supplied = document(" \tΩ\u00a0agency shall\r\nact.\r\nCafé may file!  ")
    supplied["entry_cid"] = {"zeta": 7, "alpha": {"right": 2, "left": 1}}
    _, report, pin, spans = case([supplied, document("Unselected officer may file.", "2")])
    raw = coordinate_loader_payload(report)
    assert hashlib.sha256(raw).hexdigest() != pin
    loaded = cache_module.load_source_coordinate_report(raw, expected_report_sha256=pin)
    assert loaded == report and len(loaded["documents"]) == 2 and len(loaded["spans"]) == len(spans)
    metadata = loaded["documents"][0]["source_metadata"]["entry_cid"]
    assert list(metadata) == ["zeta", "alpha"] and list(metadata["alpha"]) == ["right", "left"]
    for occurrence in loaded["spans"]:
        source = loaded["documents"][occurrence["input_document_ordinal"]]["source_text"]
        assert source[occurrence["source_char_start"]:occurrence["source_char_end"]] == occurrence["source_text"]
        assert source.encode()[occurrence["source_utf8_byte_start"]:occurrence["source_utf8_byte_end"]].decode() == occurrence["source_text"]
    assert loaded["authority"] and all(flag is False for flag in loaded["authority"].values())
    loaded["documents"][0]["source_text"] = "changed returned object"
    assert cache_module.load_source_coordinate_report(raw, expected_report_sha256=pin) == report


@pytest.mark.parametrize("shape", ["text", "bytearray", "memoryview", "subclass", "none"],
    ids=["text", "bytearray", "memoryview", "bytes-subclass", "none"])
def test_coordinate_loader_requires_exact_bytes(shape):
    _, report, pin, _ = case()
    raw = coordinate_loader_payload(report)
    class BytesSubclass(bytes):
        pass
    invalid = {"text": raw.decode(), "bytearray": bytearray(raw), "memoryview": memoryview(raw),
               "subclass": BytesSubclass(raw), "none": None}[shape]
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(invalid, expected_report_sha256=pin)


@pytest.mark.parametrize("damage", ["utf8", "duplicate", "nonfinite", "depth"],
    ids=["invalid-utf8", "duplicate-json-key", "nonfinite-json", "excess-depth"])
def test_coordinate_loader_refuses_malformed_json(damage):
    _, report, pin, _ = case()
    raw = {"utf8": b"\xff", "duplicate": b'{"schema":"first",' + coordinate_loader_payload(report)[1:],
           "nonfinite": b'{"value":NaN}', "depth": b"["*65 + b"0" + b"]"*65}[damage]
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(raw, expected_report_sha256=pin)


@pytest.mark.parametrize("damage", ["uppercase", "boolean", "artifact", "stale"],
    ids=["uppercase-pin", "boolean-pin", "artifact-not-report-pin", "stale-report-pin"])
def test_coordinate_loader_requires_independent_canonical_report_pin(damage):
    _, report, pin, _ = case()
    raw = coordinate_loader_payload(report)
    alternative = {"uppercase": pin.upper(), "boolean": True,
        "artifact": hashlib.sha256(raw).hexdigest(), "stale": "0"*64}[damage]
    assert hashlib.sha256(raw).hexdigest() != pin
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(raw, expected_report_sha256=alternative)


@pytest.mark.parametrize("damage", ["zero", "negative", "boolean", "float", "text", "none", "increase"],
    ids=["zero", "negative", "boolean", "float", "text", "none", "raised-cap"])
def test_coordinate_loader_bound_is_exact_positive_and_lower_only(damage):
    _, report, pin, _ = case()
    raw = coordinate_loader_payload(report)
    bound = {"zero": 0, "negative": -1, "boolean": True, "float": 1.5, "text": "1024", "none": None,
             "increase": cache_module.MAX_SOURCE_COORDINATE_REPORT_BYTES + 1}[damage]
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(raw, expected_report_sha256=pin, max_bytes=bound)


def test_coordinate_loader_checks_raw_byte_bound_before_decode(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("over-budget loader input reached JSON decoding")
    monkeypatch.setattr(cache_module, "_coordinate_load", forbidden)
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(b"\xff"*9, expected_report_sha256="a"*64, max_bytes=8)


@pytest.mark.parametrize("field", ["source_char_end", "source_utf8_byte_end"],
    ids=["character-geometry", "utf8-geometry"])
def test_coordinate_loader_recommitted_geometry_requires_full_replay(field):
    _, report, _, _ = case()
    report["spans"][0][field] -= 1
    reseal(report)
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(coordinate_loader_payload(report),
            expected_report_sha256=ingest.uscode_source_coordinates_sha256(report))


def test_coordinate_loader_recommitted_authority_is_never_promoted():
    _, report, _, _ = case()
    report["authority"][next(iter(report["authority"]))] = True
    reseal(report)
    with pytest.raises(SpanCacheError):
        cache_module.load_source_coordinate_report(coordinate_loader_payload(report),
            expected_report_sha256=ingest.uscode_source_coordinates_sha256(report))
