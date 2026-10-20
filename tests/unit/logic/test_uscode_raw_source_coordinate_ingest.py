"""Opt-in local physical-row custody; these fixtures establish no legal meaning."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest


@pytest.fixture
def cli():
    source = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    spec = importlib.util.spec_from_file_location("uscode_raw_source_cli_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(number=0, *, text="  The café shall keep records.\r\n\tIt may publish them.  "):
    return {"ipfs_cid": f" cid-{number} ", "title_number": " 5 ",
            "section_number": str(550 + number), "title_name": " Government ",
            "law_name": " Records ", "source_url": " https://fixture.invalid/ ",
            "text": text, "citation_text": f"5 U.S.C. {550 + number}",
            "normalized_citation": f" 5 U.S.C. {550 + number} "}


def _parquet(tmp_path, rows=None):
    # The owned test cohort must provide Arrow; absence is not a passing skip.
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "laws.parquet"
    pq.write_table(pa.Table.from_pylist(rows if rows is not None else [_row()]),
                   path, row_group_size=2)
    return path


def _pins(path, *, limit=1, offset=0):
    return {"source_revision": "1" * 40, "source_path_in_repo": "uscode_parquet/laws.parquet",
            "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "expected_bytes": path.stat().st_size, "limit": limit,
            "offset": offset, "release_id": "fixture-release-no-legal-authority"}


def _capture(path, **changes):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
        capture_uscode_source_documents_from_parquet,
    )
    return capture_uscode_source_documents_from_parquet(path, **{**_pins(path), **changes})


def _argv(path, cache, **changes):
    values = {**_pins(path), **changes}
    return ["--source-ingest-profile", "raw-coordinates-v1", "--parquet", str(path),
            "--cache", str(cache), "--limit", str(values["limit"]),
            "--source-row-offset", str(values["offset"]),
            "--source-revision", values["source_revision"],
            "--source-path-in-repo", values["source_path_in_repo"],
            "--expected-source-sha256", values["expected_sha256"],
            "--expected-source-bytes", str(values["expected_bytes"]),
            "--source-release-id", values["release_id"], "--enqueue-only", "--no-resume"]


def test_raw_capture_preserves_unicode_whitespace_and_physical_row_witness(tmp_path):
    rows = [_row(index) for index in range(5)]
    path = _parquet(tmp_path, rows)
    result = _capture(path, offset=1, limit=3)
    assert len(result["documents"]) == 3
    for ordinal, document in enumerate(result["documents"], 1):
        assert document["text"] == rows[ordinal]["text"]
        assert document["entry_cid"] == f"cid-{ordinal}"
        assert document["raw_row_metadata"]["ipfs_cid"] == rows[ordinal]["ipfs_cid"]
        witness = document["source_witness"]
        assert witness["physical_row_ordinal"] == ordinal
        assert witness["source_file_sha256"] == _pins(path)["expected_sha256"]
        assert witness["source_revision"] == "1" * 40
        assert witness["source_path_in_repo"] == "uscode_parquet/laws.parquet"
        row_bytes = json.dumps(rows[ordinal], ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode()
        assert witness["selected_row_sha256"] == hashlib.sha256(row_bytes).hexdigest()
        assert witness["raw_text_sha256"] == hashlib.sha256(document["text"].encode()).hexdigest()
        assert witness["parquet_file_byte_mapping_verified"] is False
        assert witness["repository_revision_authenticated"] is False
    assert result["legal_meaning_verified"] is False


def test_default_record_and_cli_document_cleaning_remain_unchanged(tmp_path, cli):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import USCodeParquetRecord
    path = _parquet(tmp_path)
    assert USCodeParquetRecord.from_row(_row()).text == _row()["text"].strip()
    assert USCodeParquetRecord.from_row(_row(text=" ")).text == "Records"
    legacy = list(cli._documents(path, limit=1, skip=0))[0]
    assert legacy["text"] == _row()["text"].strip()
    assert "source_witness" not in legacy
    assert legacy["release_id"] == ""


@pytest.mark.parametrize("changes", [
    {"expected_sha256": "0" * 64}, {"expected_bytes": 12},
    {"source_revision": "main"}, {"source_revision": "A" * 40},
    {"source_path_in_repo": "../laws.parquet"}, {"source_path_in_repo": "/laws.parquet"},
    {"source_path_in_repo": "uscode_parquet//laws.parquet"},
    {"source_path_in_repo": "x/\ud800.parquet"},
    {"limit": 0}, {"limit": 129}, {"limit": True}, {"offset": -1},
    {"release_id": ""},
])
def test_invalid_source_pins_and_bounds_refuse(tmp_path, changes):
    path = _parquet(tmp_path)
    with pytest.raises((ValueError, UnicodeError)):
        _capture(path, **changes)


def test_raw_capture_requires_complete_selection_and_never_falls_back_to_citation(tmp_path):
    path = _parquet(tmp_path, [_row(text=" ")])
    with pytest.raises(ValueError, match="no fallback"):
        _capture(path)
    with pytest.raises(ValueError, match="complete physical row selection"):
        _capture(path, limit=2)


def test_source_symlink_and_fifo_are_refused_without_blocking(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
        capture_uscode_source_documents_from_parquet,
    )
    path = _parquet(tmp_path)
    # Kernel FD links exercise O_NOFOLLOW without creating aliases in evidence.
    with path.open("rb") as source:
        link = Path("/proc") / str(os.getpid()) / "fd" / str(source.fileno())
        assert link.is_symlink()
        with pytest.raises(OSError):
            capture_uscode_source_documents_from_parquet(link, **_pins(path))

    # A real anonymous pipe tests fstat refusal without a named FIFO in evidence.
    read_fd, write_fd = os.pipe()
    sentinel = tmp_path / "anonymous-pipe-source"
    original_open, seen = os.open, []
    try:
        os.set_blocking(read_fd, False)
        assert stat.S_ISFIFO(os.fstat(read_fd).st_mode)
        def open_pipe(source, flags, *args, **kwargs):
            if Path(source) == sentinel:
                assert flags & os.O_NONBLOCK
                assert flags & os.O_NOFOLLOW
                seen.append(flags)
                return os.dup(read_fd)
            return original_open(source, flags, *args, **kwargs)
        monkeypatch.setattr(os, "open", open_pipe)
        with pytest.raises(ValueError, match="regular file"):
            capture_uscode_source_documents_from_parquet(sentinel, **_pins(path))
        assert len(seen) == 1
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_source_replacement_during_arrow_decode_is_refused(tmp_path, monkeypatch):
    import pyarrow.parquet as pq

    path = _parquet(tmp_path)
    original = pq.ParquetFile

    def replace_after_open(*args, **kwargs):
        result = original(*args, **kwargs)
        other = tmp_path / "replacement"
        other.write_bytes(path.read_bytes())
        os.replace(other, path)
        return result

    monkeypatch.setattr(pq, "ParquetFile", replace_after_open)
    with pytest.raises(ValueError, match="changed during raw-row capture"):
        _capture(path)


def test_single_row_text_bound_is_enforced_on_complete_raw_text(tmp_path):
    path = _parquet(tmp_path, [_row(text="x" * (1024 * 1024 + 1))])
    with pytest.raises(ValueError, match="text exceeds byte bound"):
        _capture(path)


@pytest.mark.parametrize("extra", [
    ["--resume"], ["--upload"], ["--claim-profile", "fenced-v1"],
    ["--compile-workers", "1"], ["--batch", "1"], ["--quack-gaps"],
    ["--release-id", "different-legacy-release"],
])
def test_raw_cli_rejects_resume_compile_network_and_fenced_options(tmp_path, cli, extra):
    path = _parquet(tmp_path)
    destination = tmp_path / "new.duckdb"
    with pytest.raises(SystemExit) as raised:
        cli.main([*_argv(path, destination), *extra])
    assert raised.value.code == 2
    assert not destination.exists()


def test_raw_pin_flags_require_explicit_profile(tmp_path, cli):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--cache", str(tmp_path / "absent"), "--source-revision", "1" * 40])
    assert raised.value.code == 2


def test_raw_cli_persists_complete_replay_and_uses_existing_full_population_ids(
    tmp_path, cli, monkeypatch, capsys,
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import inventory_uscode_documents

    # Identical text at two physical occurrences must remain two observations.
    rows = [_row(), _row()]
    path = _parquet(tmp_path, rows)
    destination = tmp_path / "new.duckdb"
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy remote/compiler path entered")
    for name in ("enqueue_corpus", "_poll_remote_checkpoint", "drain"):
        monkeypatch.setattr(cli, name, forbidden)
    assert cli.main(_argv(path, destination, limit=2)) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["documents"] == 2
    assert receipt["spans_enqueued"] == 4
    assert receipt["source_authority_authenticated"] is False
    assert receipt["training_authorized"] is False
    documents = _capture(path, limit=2)["documents"]
    expected = inventory_uscode_documents(documents, query="ipfs_uscode",
                                         release_id=_pins(path)["release_id"])
    cache = SpanCache(destination)
    try:
        report = cache.read_source_coordinate_report(receipt["source_coordinates_report_sha256"])
        assert [item["source_span_id"] for item in report["spans"]] == [
            item["source_span_id"] for item in expected["spans"]]
        assert [item["source_metadata"]["source_witness"]["physical_row_ordinal"]
                for item in report["documents"]] == [0, 1]
        assert [item["source_text"] for item in report["documents"]] == [row["text"] for row in rows]
        assert cache.stats()["pending"] == 4
        assert all(item["source_provenance_json"] for item in cache.pending(limit=4))
    finally:
        cache.close()
    assert not list(tmp_path.glob(".uscode-raw-ingest-*"))


@pytest.mark.parametrize("kind", ["regular", "symlink", "legacy_catalog"])
def test_existing_catalog_is_never_opened_backfilled_or_overwritten(tmp_path, cli, kind):
    path = _parquet(tmp_path)
    destination = tmp_path / "existing.duckdb"
    source_handle = None
    if kind == "legacy_catalog":
        from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache
        cache = SpanCache(destination)
        cache.enqueue([{"source_span_id": "legacy", "text": "Keep records.", "legal_id": "usc:us:5:1"}])
        cache.close()
    elif kind == "symlink":
        other = tmp_path / "foreign"
        other.write_bytes(b"foreign")
        source_handle = other.open("rb")
        destination = Path("/proc") / str(os.getpid()) / "fd" / str(source_handle.fileno())
    else:
        destination.write_bytes(b"foreign-not-a-database")
    try:
        if kind == "symlink":
            assert destination.is_symlink()
        before = destination.read_bytes()
        info = destination.lstat()
        with pytest.raises(ValueError, match="fresh catalog"):
            cli.main(_argv(path, destination))
        assert destination.read_bytes() == before
        after = destination.lstat()
        assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    finally:
        if source_handle is not None:
            source_handle.close()


def test_orphan_wal_prevents_fresh_catalog_publication(tmp_path, cli):
    path = _parquet(tmp_path)
    destination = tmp_path / "new.duckdb"
    wal = tmp_path / "new.duckdb.wal"
    wal.write_bytes(b"foreign-recovery-state")
    with pytest.raises(ValueError, match="no WAL"):
        cli.main(_argv(path, destination))
    assert not destination.exists()
    assert wal.read_bytes() == b"foreign-recovery-state"
    assert not list(tmp_path.glob(".uscode-raw-ingest-*"))


def test_invalid_source_leaves_no_catalog_or_staging(tmp_path, cli):
    path = _parquet(tmp_path)
    destination = tmp_path / "new.duckdb"
    with pytest.raises(ValueError, match="SHA256"):
        cli.main(_argv(path, destination, expected_sha256="0" * 64))
    assert not destination.exists()
    assert not list(tmp_path.glob(".uscode-raw-ingest-*"))


def test_replay_tampering_is_refused_before_catalog_creation(tmp_path, cli, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import uscode_ingest
    path = _parquet(tmp_path)
    destination = tmp_path / "new.duckdb"
    original = uscode_ingest.inventory_uscode_source_coordinates
    def corrupted(*args, **kwargs):
        report = original(*args, **kwargs)
        report["spans"][0]["source_char_start"] += 1
        return report
    monkeypatch.setattr(uscode_ingest, "inventory_uscode_source_coordinates", corrupted)
    # The validator replays the same owner; sabotage only the producer call.
    calls = 0
    def first_only(*args, **kwargs):
        nonlocal calls
        calls += 1
        return corrupted(*args, **kwargs) if calls == 1 else original(*args, **kwargs)
    monkeypatch.setattr(uscode_ingest, "inventory_uscode_source_coordinates", first_only)
    with pytest.raises(ValueError, match="replay differs"):
        cli.main(_argv(path, destination))
    assert not destination.exists()
    assert not list(tmp_path.glob(".uscode-raw-ingest-*"))


def test_racing_destination_publication_never_overwrites_foreign_bytes(tmp_path, cli, monkeypatch):
    path = _parquet(tmp_path)
    destination = tmp_path / "new.duckdb"
    original = os.link
    def competing_link(source, target, **kwargs):
        destination.write_bytes(b"concurrent-writer")
        return original(source, target, **kwargs)
    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(FileExistsError):
        cli.main(_argv(path, destination))
    assert destination.read_bytes() == b"concurrent-writer"
    assert not list(tmp_path.glob(".uscode-raw-ingest-*"))
