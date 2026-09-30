"""Exact progress-to-source joins; no inference, network, or live catalog access."""
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _span(text, *, section="1", cid="bafy-fixture", release_id=intake.DEFAULT_RELEASE_ID, ordinal=0):
    # Independent reproduction of the historical ingest's identity, deliberately
    # not a call to the new helper or inventory implementation under test.
    identity = {"canonical_citation": f"1 U.S.C. {section}", "entry_cid": cid,
                "legal_id": f"usc:us:1:{section}", "ordinal": ordinal,
                "query": "ipfs_uscode", "release_id": release_id,
                "release_point": "", "schema_version": "uscode-sparse-autoformal-span-v1",
                "section": section, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "title": "1", "unit_id": f"usc:us:1:{section}"}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return {"record_kind": "span", "dataset_id": "", "source_span_id": "uscode-span-" + digest,
            "source_sha256": identity["text_sha256"], "legal_id": identity["legal_id"],
            "status": "roundtrip_ok", "sealed": True, "admitted": True, "formalized": True}


def _progress(path, spans, *, dataset="justicedao/ipfs_uscode", extra=()):
    meta = {"record_kind": "meta", "dataset_id": dataset,
            "source_span_id": "", "source_sha256": "", "legal_id": "",
            "status": "", "sealed": False, "admitted": False, "formalized": False}
    schema = pa.schema([(name, pa.string()) for name in (
        "record_kind", "dataset_id", "source_span_id", "source_sha256", "legal_id", "status")]
        + [(name, pa.bool_()) for name in ("sealed", "admitted", "formalized")])
    pq.write_table(pa.Table.from_pylist([meta, *spans, *extra], schema=schema), path)
    return path


def _laws(path, texts):
    rows = [{"ipfs_cid": "bafy-fixture", "title_number": "1", "section_number": str(i + 1),
             "text": text, "normalized_citation": f"1 U.S.C. {i + 1}"} for i, text in enumerate(texts)]
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


@pytest.fixture
def connection():
    connection = duckdb.connect(":memory:")
    connection.execute("SET threads=1")
    yield connection
    connection.close()


def _index(connection, path):
    return intake.prepare_progress_index(connection, path, expected_sha256=_sha(path), repository_revision="a" * 40)


def _batches(index, path, **kwargs):
    return list(intake.iter_joined_section_batches(index, path, expected_laws_sha256=_sha(path), **kwargs))


def test_exact_join_ignores_imported_status_and_excludes_nonspan_rows(connection, tmp_path):
    text = "The agency shall retain records."
    source = _span(text)
    # A board row deliberately contains an invalid hash: only spans are eligible.
    board = {**source, "record_kind": "board", "source_sha256": "not-a-source-hash"}
    progress = _progress(tmp_path / "progress.parquet", [source], extra=[board])
    laws = _laws(tmp_path / "laws.parquet", [text])
    index = _index(connection, progress)
    batch = _batches(index, laws)[0]
    assert len(batch["rows"]) == 1
    actual = batch["rows"][0]
    assert (actual["source_span_id"], actual["text"], actual["source_sha256"]) == (
        source["source_span_id"], text, source["source_sha256"])
    assert actual["admitted"] is False and actual["formalized"] is False
    assert actual["source_authority_authenticated"] is False
    assert "status" not in actual and "sealed" not in actual
    assert actual["source_parent"]["sha256"] == _sha(laws)
    assert actual["progress_parent"]["revision"] == "a" * 40
    assert intake.progress_coverage(index)["ignored_nonspan_row_count"] == 2
    assert intake.progress_coverage(index)["matched_source_span_count"] == 1


def test_duplicate_ledger_identities_collapse_but_conflicts_fail(connection, tmp_path):
    source = _span("The agency shall retain records.")
    path = _progress(tmp_path / "progress.parquet", [source, {**source, "status": "gap"}])
    index = _index(connection, path)
    assert index.stats["unique_span_count"] == 1
    assert index.stats["duplicate_span_count"] == 1
    conflict = _progress(tmp_path / "conflict.parquet", [source, {**source, "source_sha256": "b" * 64}])
    with pytest.raises(intake.SpanIntakeError, match="conflicting identities"):
        _index(connection, conflict)


@pytest.mark.parametrize("changed,reason", [({"source_sha256": "b" * 64}, "source_hash_mismatch"),
                                           ({"legal_id": "usc:us:1:999"}, "legal_id_mismatch")])
def test_identity_hash_and_citation_mismatch_are_not_invented(connection, tmp_path, changed, reason):
    text = "The agency shall retain records."
    progress = _progress(tmp_path / "progress.parquet", [{**_span(text), **changed}])
    laws = _laws(tmp_path / "laws.parquet", [text])
    index = _index(connection, progress)
    batch = _batches(index, laws)[0]
    assert batch["rows"] == []
    assert batch["counts"][reason + "_count"] == 1
    assert batch["unmatched_examples"][0]["reason"] == reason
    assert intake.progress_coverage(index)["unmatched_progress_span_count"] == 1


def test_unlisted_sentences_remain_unmatched(connection, tmp_path):
    text = "The agency shall retain records."
    progress = _progress(tmp_path / "progress.parquet", [_span(text, release_id="another-release")])
    laws = _laws(tmp_path / "laws.parquet", [text])
    batch = _batches(_index(connection, progress), laws)[0]
    assert batch["rows"] == []
    assert batch["counts"]["unlisted_source_count"] == 1


def test_same_legal_id_and_text_do_not_borrow_another_source_cid_identity(connection, tmp_path):
    text = "The agency shall retain records."
    progress = _progress(tmp_path / "progress.parquet", [_span(text, cid="bafy-other-original-source")])
    laws = _laws(tmp_path / "laws.parquet", [text])
    batch = _batches(_index(connection, progress), laws)[0]
    assert batch["rows"] == []
    assert batch["counts"]["unlisted_source_count"] == 1


def test_section_cursor_is_replayable_and_does_not_skip_first_uncommitted_batch(connection, tmp_path):
    texts = [f"The officer shall retain file {i}." for i in range(3)]
    progress = _progress(tmp_path / "progress.parquet", [_span(text, section=str(i + 1), ordinal=i) for i, text in enumerate(texts)])
    laws = _laws(tmp_path / "laws.parquet", texts)
    index = _index(connection, progress)
    initial = _batches(index, laws, section_batch_size=1)
    replay = _batches(index, laws, start_section=1, section_batch_size=1)
    assert sum(len(b["rows"]) for b in initial) == len(texts)
    assert [b["next_section"] for b in initial] == [1, 2, 3]
    assert [b["next_section"] for b in replay] == [2, 3]
    assert [b["rows"] for b in replay] == [b["rows"] for b in initial[1:]]
    assert replay[-1]["done"] is True
    final = _batches(index, laws, start_section=3)[0]
    assert final["done"] and final["rows"] == [] and final["next_section"] == 3
    with pytest.raises(intake.SpanIntakeError, match="beyond"):
        _batches(index, laws, start_section=4)


def test_file_hash_dataset_and_source_bounds_fail_closed(connection, tmp_path):
    text = "The agency shall retain records."
    progress = _progress(tmp_path / "progress.parquet", [_span(text)])
    with pytest.raises(intake.SpanIntakeError, match="SHA-256 differs"):
        intake.prepare_progress_index(connection, progress, expected_sha256="c" * 64, repository_revision="a" * 40)
    foreign = _progress(tmp_path / "foreign.parquet", [_span(text)], dataset="another/corpus")
    with pytest.raises(intake.SpanIntakeError, match="U.S. Code dataset"):
        _index(connection, foreign)
    index = _index(connection, progress)
    laws = _laws(tmp_path / "laws.parquet", [text])
    with pytest.raises(intake.SpanIntakeError, match="complete-text byte bound"):
        _batches(index, laws, max_section_bytes=8)
    with pytest.raises(intake.SpanIntakeError, match="span or byte bound"):
        _batches(index, laws, max_batch_bytes=8)


def test_changed_verified_source_does_not_yield_later_batch(connection, tmp_path):
    texts = ["The agency shall retain records.", "The agency shall publish reports."]
    progress = _progress(tmp_path / "progress.parquet", [_span(text, section=str(i + 1), ordinal=i) for i, text in enumerate(texts)])
    laws = _laws(tmp_path / "laws.parquet", texts)
    iterator = intake.iter_joined_section_batches(_index(connection, progress), laws,
                                                expected_laws_sha256=_sha(laws), section_batch_size=1)
    assert next(iterator)["next_section"] == 1
    # An append keeps the already-open Arrow reader viable but changes identity.
    with laws.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(intake.SpanIntakeError, match="changed during intake"):
        next(iterator)


def test_full_text_is_not_truncated_to_historical_cache_limit(connection, tmp_path):
    text = "The agency shall retain " + "large " * 6000 + "record."
    source = _span(text)
    truncated = {**source, "source_sha256": hashlib.sha256(text[:32768].encode()).hexdigest()}
    progress = _progress(tmp_path / "progress.parquet", [truncated])
    laws = _laws(tmp_path / "laws.parquet", [text])
    result = _batches(_index(connection, progress), laws)[0]
    assert len(text) > 32768
    assert result["rows"] == []
    assert result["counts"]["source_hash_mismatch_count"] == 1


@pytest.mark.parametrize("batch_size,start", [(1, 0), (7, 17), (16, 64), (13, 65)])
def test_historical_64_document_ordinals_survive_output_batches_and_resume(connection, tmp_path, batch_size, start):
    # Each section contains two sentences, so the ordinal must count spans,
    # not documents. The second historical group restarts at document 64.
    sentences = [[f"The officer shall retain record {i}.",
                  f"The agency shall publish report {i}."] for i in range(70)]
    expected = [_span(text, section=str(i + 1), ordinal=(i % 64) * 2 + j)
                for i, pair in enumerate(sentences) for j, text in enumerate(pair)]
    laws = _laws(tmp_path / "laws.parquet", [" ".join(pair) for pair in sentences])
    progress = _progress(tmp_path / "progress.parquet", expected)
    batches = _batches(_index(connection, progress), laws,
                       section_batch_size=batch_size, start_section=start)
    rows = [row for batch in batches for row in batch["rows"]]
    assert [row["source_span_id"] for row in rows] == [row["source_span_id"] for row in expected[start * 2:]]
    assert sum(batch["counts"]["unlisted_source_count"] for batch in batches) == 0
    assert rows[0]["historical_span_ordinal"] == (start % 64) * 2
    assert rows[-1]["historical_document_batch_index"] == 1
    assert all(row["identity_reconstruction"] == "historical-64-document-ordinal/v1" for row in rows)
    assert all(row["historical_document_batch_size"] == 64 for row in rows)
    assert all(row["admitted"] is False and row["formalized"] is False for row in rows)


def test_historical_groups_count_valid_documents_not_raw_rows(connection, tmp_path):
    texts = [f"The officer shall retain record {i}." for i in range(68)]
    laws = _laws(tmp_path / "laws.parquet", texts)
    source_rows = pq.read_table(laws).to_pylist()
    source_rows[4]["ipfs_cid"] = ""
    source_rows[23]["ipfs_cid"] = ""
    pq.write_table(pa.Table.from_pylist(source_rows), laws)
    expected = []
    for i, row in enumerate(source_rows):
        if row["ipfs_cid"] and row["text"]:
            expected.append(_span(texts[i], section=str(i + 1), ordinal=len(expected) % 64))
    progress = _progress(tmp_path / "progress.parquet", expected)
    index = _index(connection, progress)
    batches = _batches(index, laws, section_batch_size=9)
    rows = [row for batch in batches for row in batch["rows"]]
    assert [row["source_span_id"] for row in rows] == [row["source_span_id"] for row in expected]
    assert sum(batch["counts"]["empty_section_count"] for batch in batches) == 2
    replay = _batches(index, laws, section_batch_size=5, start_section=66)
    replay_rows = [row for batch in replay for row in batch["rows"]]
    assert replay_rows == rows[-2:]
    assert replay_rows[0]["historical_span_ordinal"] == 0
    assert replay_rows[0]["historical_document_batch_index"] == 1


@pytest.mark.parametrize("batch_size", [1, 8])
def test_null_metadata_rows_do_not_shift_identity_groups_or_block_completion(connection, tmp_path, batch_size):
    texts = [f"The agency shall retain file {i}." for i in range(66)]
    laws = _laws(tmp_path / "laws.parquet", texts)
    table = pq.read_table(laws)
    source_rows = table.to_pylist()
    metadata = {name: None for name in table.column_names}
    # One null row immediately before the 64th valid document, followed by
    # nine trailing null metadata rows as in the pinned original source.
    source_rows = [*source_rows[:63], metadata, *source_rows[63:], *([metadata] * 9)]
    pq.write_table(pa.Table.from_pylist(source_rows, schema=table.schema), laws)
    expected = [_span(text, section=str(i + 1), ordinal=i % 64) for i, text in enumerate(texts)]
    progress = _progress(tmp_path / "progress.parquet", expected)
    index = _index(connection, progress)
    batches = _batches(index, laws, section_batch_size=batch_size)
    rows = [row for batch in batches for row in batch["rows"]]
    assert [row["source_span_id"] for row in rows] == [row["source_span_id"] for row in expected]
    assert sum(batch["counts"]["empty_section_count"] for batch in batches) == 10
    assert batches[-1]["done"] and batches[-1]["rows"] == []
    assert batches[-1]["next_section"] == len(source_rows)
    replay = _batches(index, laws, section_batch_size=batch_size, start_section=65)
    replay_rows = [row for batch in replay for row in batch["rows"]]
    assert replay_rows == rows[-2:]
    assert replay_rows[0]["historical_span_ordinal"] == 0
    assert replay_rows[0]["historical_document_batch_index"] == 1
    assert sum(batch["counts"]["empty_section_count"] for batch in replay) == 9


def test_null_text_with_a_real_source_cid_still_fails_closed(connection, tmp_path):
    text = "The agency shall retain records."
    laws = _laws(tmp_path / "laws.parquet", [text])
    table = pq.read_table(laws)
    rows = table.to_pylist()
    rows[0]["text"] = None
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), laws)
    progress = _progress(tmp_path / "progress.parquet", [_span(text)])
    with pytest.raises(intake.SpanIntakeError, match="text is not a string"):
        _batches(_index(connection, progress), laws)
