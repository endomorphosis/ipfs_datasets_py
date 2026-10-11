"""Historical identity and lossless within-section cursor regression tests."""
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_pages as pages


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _span(text, *, section="1", ordinal=0, cid="bafy-fixture"):
    binding = {"canonical_citation": f"1 U.S.C. {section}", "entry_cid": cid,
               "legal_id": f"usc:us:1:{section}", "ordinal": ordinal,
               "query": "ipfs_uscode", "release_id": intake.DEFAULT_RELEASE_ID,
               "release_point": "", "schema_version": "uscode-sparse-autoformal-span-v1",
               "section": section, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
               "title": "1", "unit_id": f"usc:us:1:{section}"}
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"record_kind": "span", "dataset_id": "", "source_span_id": "uscode-span-" + digest,
            "source_sha256": binding["text_sha256"], "legal_id": binding["legal_id"]}


def _progress(path, spans=()):
    meta = {"record_kind": "meta", "dataset_id": intake.SOURCE_REPOSITORY,
            "source_span_id": "", "source_sha256": "", "legal_id": ""}
    schema = pa.schema([(k, pa.string()) for k in meta])
    pq.write_table(pa.Table.from_pylist([meta, *spans], schema=schema), path)
    return path


def _laws(path, texts):
    rows = [{"ipfs_cid": "bafy-fixture", "title_number": "1", "section_number": str(i + 1),
             "text": text, "normalized_citation": f"1 U.S.C. {i + 1}"}
            for i, text in enumerate(texts)]
    schema = pa.schema([(k, pa.string()) for k in (
        "ipfs_cid", "title_number", "section_number", "text", "normalized_citation")])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return path


@pytest.fixture
def connection():
    connection = duckdb.connect(":memory:")
    connection.execute("SET threads=1")
    yield connection
    connection.close()


def _index(connection, path):
    return intake.prepare_progress_index(connection, path, expected_sha256=_sha(path),
                                         repository_revision="a" * 40)


def _pages(index, laws, **kwargs):
    return list(pages.iter_joined_span_pages(index, laws, expected_laws_sha256=_sha(laws), **kwargs))


def _rows(items):
    return [row for item in items for row in item["candidate_rows"]]


NEW_FIELDS = {"source_section_span_ordinal", "source_text_origin", "raw_source_text_present"}


def test_small_paged_candidates_equal_original_iterator_exactly(connection, tmp_path):
    texts = ["  The agency\n shall retain café files.\tThe officer must publish résumé reports! ",
             "The clerk may retain records? The actor shall preserve evidence."]
    laws = _laws(tmp_path / "laws.parquet", texts)
    targets = [_span("The agency shall retain café files."),
               {**_span("The officer must publish résumé reports!", ordinal=1), "source_sha256": "b" * 64},
               {**_span("The clerk may retain records?", section="2", ordinal=2), "legal_id": "usc:us:1:999"}]
    index = _index(connection, _progress(tmp_path / "progress.parquet", targets))
    original = list(intake.iter_joined_section_batches(index, laws, expected_laws_sha256=_sha(laws),
                    section_batch_size=1, include_candidates=True))
    paged = _pages(index, laws, max_page_spans=1)
    assert [{k:v for k,v in row.items() if k not in NEW_FIELDS} for row in _rows(paged)] == _rows(original)
    assert [row["source_join_disposition"] for row in _rows(paged)] == [
        "matched", "source_hash_mismatch", "legal_id_mismatch", "unlisted_source"]
    assert [(p["next_section"], p["next_span"]) for p in paged] == [(0,1),(1,0),(1,1),(2,0)]
    assert all(row["source_text_origin"] == "normalized_source_text" and row["raw_source_text_present"]
               for row in _rows(paged))
    assert paged[-1]["done"] and all(not p["done"] for p in paged[:-1])
    assert all(not p["training_executed"] and not p["inference_executed"] and not p["proof_authority"]
               for p in paged)


def test_section_exceeding_old_span_bound_pages_without_all_candidate_dictionaries(connection, tmp_path, monkeypatch):
    sentences = [f"The agency shall retain file {i}." for i in range(9001)]
    laws = _laws(tmp_path / "laws.parquet", [" ".join(sentences)])
    targets = [_span(sentences[i], ordinal=i) for i in [0,1023,1024,8192,9000]]
    index = _index(connection, _progress(tmp_path / "progress.parquet", targets))
    with pytest.raises(intake.SpanIntakeError, match="span or byte bound"):
        list(intake.iter_joined_section_batches(index, laws, expected_laws_sha256=_sha(laws),
                                               section_batch_size=1))
    # A call to the original inventory would eagerly create all 9,001 source
    # dictionaries. The pager needs only its bounded normalized sentence list.
    from ipfs_datasets_py.logic.autoformal import uscode_ingest
    monkeypatch.setattr(uscode_ingest, "inventory_uscode_documents",
                        lambda *a, **k: pytest.fail("eager section inventory called"))
    result = _pages(index, laws, max_page_spans=257)
    rows = _rows(result)
    assert len(rows) == 9001
    assert max(len(p["candidate_rows"]) for p in result) == 257
    assert [r["text"] for r in rows] == sentences
    assert [r["historical_span_ordinal"] for r in rows] == list(range(9001))
    assert sum(p["counts"]["matched_count"] for p in result) == 5
    assert sum(p["counts"]["unlisted_source_count"] for p in result) == 8996
    assert result[-1]["next_section"] == 1 and result[-1]["next_span"] == 0


def test_resume_inside_section_and_across_64_document_boundary(connection, tmp_path):
    sentences = [[f"The agency shall retain file {i}.", f"The officer shall publish report {i}."]
                 for i in range(66)]
    laws = _laws(tmp_path / "laws.parquet", [" ".join(s) for s in sentences])
    expected = [_span(text, section=str(i + 1), ordinal=(i % 64) * 2 + j)
                for i, pair in enumerate(sentences) for j, text in enumerate(pair)]
    index = _index(connection, _progress(tmp_path / "progress.parquet", expected))
    full = _rows(_pages(index, laws, max_page_spans=1))
    for section, span in [(0,1),(63,1),(64,0),(64,1),(65,1)]:
        resumed = _pages(index, laws, start_section=section, start_span=span, max_page_spans=7)
        assert _rows(resumed) == full[section * 2 + span:]
        assert resumed[-1]["done"]
    assert full[128]["historical_span_ordinal"] == 0
    assert full[128]["historical_document_batch_index"] == 1


def test_null_metadata_and_legacy_citation_fallback_preserve_exact_group_ordinals(connection, tmp_path):
    texts = [f"The officer shall retain file {i}." for i in range(66)]
    texts[63] = "  \t\n"
    laws = _laws(tmp_path / "laws.parquet", texts)
    table = pq.read_table(laws)
    rows = table.to_pylist()
    metadata = {k:None for k in table.column_names}
    rows.insert(62, metadata)
    rows.append(metadata)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), laws)
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    original = list(intake.iter_joined_section_batches(index, laws, expected_laws_sha256=_sha(laws),
                    section_batch_size=1, include_candidates=True))
    paged = _pages(index, laws, max_page_spans=1)
    full = _rows(paged)
    assert [{k:v for k,v in row.items() if k not in NEW_FIELDS} for row in full] == _rows(original)
    fallback = [r for r in full if not r["raw_source_text_present"]]
    assert [r["text"] for r in fallback] == ["1 U.S.C.", "64"]
    assert all(r["source_text_origin"] == "legacy_citation_fallback" for r in fallback)
    assert [r["historical_span_ordinal"] for r in fallback] == [63,64]
    after = next(r for r in full if r["section"] == "65")
    assert after["historical_document_batch_index"] == 1 and after["historical_span_ordinal"] == 0
    assert sum(p["counts"]["empty_section_count"] for p in paged) == 2
    assert sum(p["counts"]["legacy_citation_fallback_candidate_count"] for p in paged) == 2
    resumed = _pages(index, laws, start_section=64, start_span=1, max_page_spans=8)
    assert _rows(resumed) == full[64:]
    assert sum(p["counts"]["empty_section_count"] for p in resumed) == 1


@pytest.mark.parametrize("kwargs,message", [
    ({"start_section":-1},"nonnegative"), ({"start_span":-1},"nonnegative"),
    ({"start_span":True},"nonnegative"), ({"start_section":2},"beyond"),
    ({"start_section":1,"start_span":1},"completed source cursor"),
    ({"start_span":2},"beyond the section sentence count"),
    ({"max_page_spans":0},"positive"), ({"max_page_bytes":False},"positive"),
    ({"source_revision":"main"},"complete commit SHA")])
def test_invalid_cursor_and_bounds_fail_before_delivery(connection, tmp_path, kwargs, message):
    laws = _laws(tmp_path / "laws.parquet", ["First sentence. Second sentence."])
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    with pytest.raises(intake.SpanIntakeError, match=message):
        _pages(index, laws, **kwargs)


def test_nonzero_empty_metadata_cursor_is_invalid(connection, tmp_path):
    laws = _laws(tmp_path / "laws.parquet", ["First sentence."])
    table = pq.read_table(laws);rows = table.to_pylist();rows[0]["ipfs_cid"] = ""
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), laws)
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    with pytest.raises(intake.SpanIntakeError, match="empty section cursor"):
        _pages(index, laws, start_span=1)


def test_byte_pages_are_complete_and_bounded(connection, tmp_path):
    sentences = [f"The officer shall retain café file {i}." for i in range(12)]
    laws = _laws(tmp_path / "laws.parquet", [" ".join(sentences)])
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    one = _pages(index, laws, max_page_spans=1)
    limit = max(len(json.dumps(p["candidate_rows"], ensure_ascii=True, separators=(",", ":")).encode())
                for p in one) + 100
    result = _pages(index, laws, max_page_spans=12, max_page_bytes=limit)
    assert len(result) == 12
    assert [r["text"] for r in _rows(result)] == sentences
    assert all(len(json.dumps(p["candidate_rows"], ensure_ascii=True, separators=(",", ":")).encode())
               <= limit for p in result)


def test_oversized_candidate_refuses_before_hydration_and_retry_keeps_cursor(connection, tmp_path):
    text = "The agency shall retain " + "é" * 2000 + " files."
    laws = _laws(tmp_path / "laws.parquet", [text])
    index = _index(connection, _progress(tmp_path / "progress.parquet", [_span(text)]))
    with pytest.raises(intake.SpanIntakeError, match="individual source candidate"):
        _pages(index, laws, max_page_bytes=1024)
    assert intake.progress_coverage(index)["matched_source_span_count"] == 0
    retried = _pages(index, laws, max_page_bytes=32768)
    assert _rows(retried)[0]["text"] == text
    assert retried[-1]["next_section"] == 1


def test_oversized_later_candidate_does_not_advance_over_it(connection, tmp_path):
    sentences = ["The agency shall retain files.", "The agency shall preserve " + "record " * 1000 + "."]
    laws = _laws(tmp_path / "laws.parquet", [" ".join(sentences)])
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    iterator = pages.iter_joined_span_pages(index, laws, expected_laws_sha256=_sha(laws),
                                          max_page_spans=1, max_page_bytes=4096)
    first = next(iterator)
    assert first["next_section"] == 0 and first["next_span"] == 1
    # The prior page is available for durable commit. Refusal never reports a
    # cursor past the failed candidate; replaying that durable cursor is safe.
    with pytest.raises(intake.SpanIntakeError, match="individual source candidate"):
        next(iterator)
    retried = _pages(index, laws, start_span=first["next_span"],
                     max_page_spans=1, max_page_bytes=32768)
    assert [r["text"] for r in _rows(retried)] == sentences[1:]


@pytest.mark.parametrize("changed", ["source", "progress"])
def test_changed_input_blocks_next_page(connection, tmp_path, changed):
    laws = _laws(tmp_path / "laws.parquet", ["First sentence. Second sentence."])
    progress = _progress(tmp_path / "progress.parquet")
    index = _index(connection, progress)
    iterator = pages.iter_joined_span_pages(index, laws, expected_laws_sha256=_sha(laws), max_page_spans=1)
    assert next(iterator)["next_span"] == 1
    with (laws if changed == "source" else progress).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(intake.SpanIntakeError, match="changed during intake"):
        next(iterator)


def test_final_cursor_empty_file_hash_and_section_validation(connection, tmp_path):
    laws = _laws(tmp_path / "laws.parquet", [])
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    final = _pages(index, laws)
    assert len(final) == 1 and final[0]["done"] and final[0]["candidate_rows"] == []
    with pytest.raises(intake.SpanIntakeError, match="SHA-256 differs"):
        list(pages.iter_joined_span_pages(index, laws, expected_laws_sha256="f" * 64))
    large = _laws(tmp_path / "large.parquet", ["The agency shall preserve records."])
    with pytest.raises(intake.SpanIntakeError, match="complete-text byte bound"):
        _pages(index, large, max_section_bytes=4)
    table = pq.read_table(large);rows = table.to_pylist();rows[0]["text"] = None
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), large)
    with pytest.raises(intake.SpanIntakeError, match="text is not a string"):
        _pages(index, large)


def test_fallback_text_is_bounded_before_sentence_materialization(connection, tmp_path):
    laws = _laws(tmp_path / "laws.parquet", [""])
    table = pq.read_table(laws);rows = table.to_pylist()
    rows[0]["normalized_citation"] = "very large citation " * 1000
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), laws)
    index = _index(connection, _progress(tmp_path / "progress.parquet"))
    with pytest.raises(intake.SpanIntakeError, match="fallback text exceeds"):
        _pages(index, laws, max_section_bytes=64)
