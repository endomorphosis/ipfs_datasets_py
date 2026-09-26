"""Offline full-row export contracts using real Parquet and local DuckDB I/O.

Producer vectors are explicitly injected codec fixtures. These tests execute no
model, parser/compiler, native worker, network service, publication or Lake.
"""
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_corpus_export as export
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as importer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inventory_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_partitions as partitions_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as index
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_embedding_receipt_set import _case
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_inventory import (
    _build, _release, _row,
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _forbidden(*args, **kwargs):
    pytest.fail("source export must not run a model, compiler, process or network client")


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    monkeypatch.setattr(modal_autoencoder.AdaptiveModalAutoencoder, "__init__", _forbidden)
    monkeypatch.setattr(TypedDeonticCanonicalCompiler, "compile", _forbidden)


@dataclass
class SourceCase:
    inventory: object
    release: object
    resolver: object
    kwargs: dict
    originals: list
    source_root: Path


def _plain(root, *, shards=None, wrapper_change=None, with_partitions=False):
    shards = shards or [[_row(1), _row(2)], [_row(3)]]
    fixture = _release(root, shards, wrapper_change=wrapper_change)
    inventory = _build(fixture)
    kwargs = {}
    if with_partitions:
        kwargs["partitions"] = partitions_codec.build_source_partitions(
            inventory, policy=index.SplitPolicy("offline-source-export-v1"))
    return SourceCase(inventory, fixture.release, fixture.resolve, kwargs,
                      [row for shard in shards for row in shard], root)


def _campaign(root):
    a = _row(1, text="  § 1. Café\nrecords.\t")
    alias = {**a, "entry_cid": _row(2)["entry_cid"], "document_index": 2}
    rows = [a, alias, _row(3), _row(4), _row(5),
            _row(6, admission_status="excluded", text="Excluded exact text.\n")]
    case = _case(root, rows=rows, groups=[[0, 2], [3]],
                 statuses={2: "token_limit_exceeded", 3: "missing_input"},
                 policy=index.SplitPolicy("export-source-roles-v1", train=2500,
                                          validation=2500, canary=2500, holdout=2500))
    inventory = case.partitions.inventory
    metadata = inventory.to_dict()["release"]
    manifest = root / "release" / "manifest.json"
    release = importer.load_uscode_release({"path": str(manifest), **metadata["manifest"]},
        repo_id=metadata["repo_id"], revision=metadata["revision"],
        limits=importer.USCodeImportLimits(**metadata["import_limits"]))
    paths = {metadata["manifest"]["sha256"]: manifest}
    for position, artifact in enumerate(release.corpus_shards):
        paths[artifact.sha256] = root / "release" / f"source-{position:06d}.parquet"
    def resolver(ref):
        path = paths[ref["sha256"]]
        assert path.stat().st_size == ref["bytes"]
        return path
    kwargs = {"partitions": case.partitions, "receipt_set": case.build(),
              "receipt_resolver": case.receipt_resolver,
              "source_resolver": case.source_resolver}
    return SourceCase(inventory, release, resolver, kwargs, rows, root)


def _export(case, destination, **changes):
    kwargs = {**case.kwargs, **changes}
    return export.export_uscode_source_rows(case.inventory, destination,
        release=case.release, resolver=case.resolver, **kwargs)


def _verify(report, **kwargs):
    return export.verify_uscode_source_export(report["output_directory"],
        expected_manifest_sha256=report["manifest_artifact"]["sha256"], **kwargs)


def _rows(report):
    root = Path(report["output_directory"])
    return [row for shard in report["row_shards"]
            for batch in pq.ParquetFile(root / shard["relative_path"]).iter_batches(batch_size=2)
            for row in batch.to_pylist()]


def _manifest(report):
    return json.loads(Path(report["manifest_artifact"]["path"]).read_bytes())


def _reseal(report, manifest):
    path = Path(report["manifest_artifact"]["path"])
    raw = _json(manifest)
    path.write_bytes(raw)
    return {**report, "manifest_artifact": {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}}


def _assert_no_authority(report):
    qualification = report["qualification"]
    for name in ("admitted", "formalized", "source_authority_authenticated",
                 "global_holdout_verified"):
        assert qualification[name] is False


def test_all_physical_rows_keep_exact_text_aliases_exclusions_and_producer_dispositions(tmp_path):
    case = _campaign(tmp_path / "source")
    report = _export(case, tmp_path / "package", batch_size=1,
                     limits=export.CorpusExportLimits(max_rows_per_file=2))
    assert report["row_count"] == 6
    assert [item["row_count"] for item in report["row_shards"]] == [2, 2, 2]
    rows = _rows(report)
    assert [row["text"] for row in rows] == [row["text"] for row in case.originals]
    assert [row["entry_cid"] for row in rows] == [row["entry_cid"] for row in case.originals]
    assert len({row["source_row_id"] for row in rows}) == 6
    assert rows[0]["input_id"] == rows[1]["input_id"]
    assert rows[0]["eligible_alias_count"] == rows[1]["eligible_alias_count"] == 2
    assert [row["embedding_status"] for row in rows] == [
        "embedded", "embedded", "token_limit_exceeded", "missing_input", "unattempted", "source_ineligible"]
    assert rows[0]["embedding_receipt_sha256"] == rows[1]["embedding_receipt_sha256"]
    assert rows[0]["embedding_result_index"] == rows[1]["embedding_result_index"] == 0
    assert rows[-1]["source_status"] == "retrieval_disposition_excluded"
    assert rows[-1]["source_eligible"] is False
    assert rows[-1]["embedding_receipt_sha256"] is rows[-1]["embedding_result_index"] is None
    for row, original in zip(rows, case.originals, strict=True):
        assert json.loads(row["record_json"]) == original
        assert _sha(row["record_json"].encode()) == row["record_sha256"]
        assert _sha(row["text"].encode()) == row["text_sha256"]
        assert len(row["text"].encode()) == row["text_bytes"]
        assert "embedding_vector" not in row and "vector" not in row
        assert row["admitted"] is row["formalized"] is False
        assert row["formalization_status"] == "not_observed"
    expected_splits = [item["split"] for item in case.kwargs["partitions"].to_dict()["rows"]]
    assert [row["split"] for row in rows] == expected_splits
    assert _verify(report)["coverage"] == report["coverage"]
    _assert_no_authority(report)


def test_duckdb_queries_cover_every_row_and_preserve_protected_splits(tmp_path):
    case = _plain(tmp_path / "source", shards=[[_row(i) for i in range(1, 41)]], with_partitions=True)
    report = _export(case, tmp_path / "package", batch_size=3,
                     limits=export.CorpusExportLimits(max_rows_per_file=7))
    paths = [str(Path(report["output_directory"]) / row["relative_path"]) for row in report["row_shards"]]
    with duckdb.connect(":memory:", config={"threads": 1}) as connection:
        connection.read_parquet(paths).create_view("source_rows")
        assert connection.execute("SELECT count(*), count(DISTINCT source_row_id) FROM source_rows").fetchone() == (40, 40)
        counts = dict(connection.execute("SELECT split, count(*) FROM source_rows GROUP BY split").fetchall())
        expected = case.kwargs["partitions"].partition_counts
        assert counts == {key: value for key, value in expected.items() if value}
        assert connection.execute("SELECT count(*) FROM source_rows WHERE text IS NULL OR record_json IS NULL").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM source_rows WHERE embedding_status != 'unavailable'").fetchone() == (0,)
    assert sum(counts.values()) == 40


def test_raw_invalid_and_global_duplicate_rows_remain_recoverable_without_invented_text(tmp_path):
    first = _row(1)
    duplicate = {**_row(2), "entry_cid": first["entry_cid"]}
    def corrupt(shard, wrappers):
        if shard == 1:
            wrappers[-1]["record_sha256"] = "f" * 64
    case = _plain(tmp_path / "source", shards=[[first], [duplicate, _row(3)]], wrapper_change=corrupt)
    report = _export(case, tmp_path / "package", batch_size=1)
    rows = _rows(report)
    assert [row["source_status"] for row in rows] == ["duplicate_entry_cid", "duplicate_entry_cid", "record_hash_mismatch"]
    assert [row["duplicate_entry_cid"] for row in rows] == [True, True, False]
    assert [row["text"] for row in rows[:2]] == [first["text"], duplicate["text"]]
    assert rows[2]["text"] is rows[2]["record_json"] is rows[2]["record_sha256"] is None
    assert rows[2]["wrapper_verified"] is False
    assert all(row["embedding_status"] == "source_ineligible" for row in rows)
    assert all(row["split"] is row["group_id"] is None for row in rows)
    for artifact in case.release.corpus_shards:
        packed = Path(report["output_directory"]) / "source/corpus" / artifact.relative_path
        assert packed.read_bytes() == case.resolver(artifact.reference).read_bytes()
    assert _verify(report)["row_count"] == 3


def test_verified_empty_text_and_excluded_connector_keep_their_source_groups(tmp_path):
    rows = [_row(1, text="Same text."),
            _row(2, legal_id="usc:us:5:1", section="1", admission_status="excluded", text="bÉta text."),
            _row(3, text="  BÉTA  text. "), _row(4, text="")]
    case = _plain(tmp_path / "source", shards=[rows], with_partitions=True)
    report = _export(case, tmp_path / "package")
    actual = _rows(report)
    assert len({row["group_id"] for row in actual[:3]}) == 1
    assert actual[1]["source_status"] == "retrieval_disposition_excluded"
    assert actual[3]["source_status"] == "missing_text"
    assert actual[3]["text"] == "" and actual[3]["text_bytes"] == 0
    assert actual[3]["text_sha256"] == _sha(b"")
    assert _verify(report)["row_count"] == 4


def test_package_verifies_after_all_original_paths_are_removed(tmp_path):
    case = _campaign(tmp_path / "original")
    report = _export(case, tmp_path / "package")
    shutil.rmtree(case.source_root)
    moved = tmp_path / "moved"
    Path(report["output_directory"]).rename(moved)
    verified = export.verify_uscode_source_export(moved,
        expected_manifest_sha256=report["manifest_artifact"]["sha256"])
    assert verified["row_count"] == 6
    assert verified["coverage"] == report["coverage"]
    assert _rows(verified) == _rows({**report, "output_directory": str(moved)})
    _assert_no_authority(verified)


def test_two_same_config_exports_are_byte_identical_and_batches_do_not_change_rows(tmp_path):
    case = _campaign(tmp_path / "source")
    a = _export(case, tmp_path / "first", batch_size=2)
    b = _export(case, tmp_path / "second", batch_size=2)
    assert _manifest(a) == _manifest(b)
    assert a["manifest_artifact"]["sha256"] == b["manifest_artifact"]["sha256"]
    for item in _manifest(a)["files"]:
        assert (Path(a["output_directory"]) / item["relative_path"]).read_bytes() == (Path(b["output_directory"]) / item["relative_path"]).read_bytes()
    c = _export(case, tmp_path / "third", batch_size=1)
    assert _rows(c) == _rows(a)


@pytest.mark.parametrize("field,value", [
    ("max_rows", True), ("max_rows", 0), ("max_rows", 65537),
    ("max_files", 4097), ("max_file_bytes", 256 * 1024**2 + 1),
    ("max_total_bytes", 512 * 1024**2 + 1), ("max_manifest_bytes", 4 * 1024**2 + 1),
    ("max_batch_bytes", 16 * 1024**2 + 1), ("max_rows_per_file", 4097),
    ("max_row_group_bytes", 32 * 1024**2 + 1),
    ("max_parquet_uncompressed_bytes", 256 * 1024**2 + 1),
    ("max_namespace_entries", 8193),
    ("max_directories", 1025), ("max_path_bytes", 513), ("max_path_depth", 9),
])
def test_limits_only_tighten_strict_integer_bounds(field, value):
    with pytest.raises((export.CorpusExportError, ValueError)):
        export.CorpusExportLimits(**{field: value})


@pytest.mark.parametrize("field,value", [("max_rows", 2), ("max_files", 1),
    ("max_file_bytes", 1), ("max_total_bytes", 1), ("max_manifest_bytes", 1), ("max_batch_bytes", 1)])
def test_over_budget_export_never_publishes_complete_manifest(tmp_path, field, value):
    case = _plain(tmp_path / "source")
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        _export(case, destination, limits=export.CorpusExportLimits(**{field: value}))
    assert not (destination / "source-export.json").exists()


@pytest.mark.parametrize("batch_size", [True, 0, 257, 1.5])
def test_invalid_batch_size_cannot_start_an_export(tmp_path, batch_size):
    case = _plain(tmp_path / "source")
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        _export(case, destination, batch_size=batch_size)
    assert not (destination / "source-export.json").exists()


def test_existing_output_is_never_overwritten(tmp_path):
    case = _plain(tmp_path / "source")
    destination = tmp_path / "package"
    destination.mkdir()
    sentinel = destination / "keep"
    sentinel.write_bytes(b"untouched")
    with pytest.raises((export.CorpusExportError, FileExistsError, ValueError)):
        _export(case, destination)
    assert list(destination.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"untouched"


@pytest.mark.parametrize("kind", ["root_alias", "extra_file", "extra_directory", "symlink", "missing_file", "corrupt_file"])
def test_verifier_rejects_nonexact_or_aliased_package_namespace(tmp_path, kind):
    case = _plain(tmp_path / "source")
    report = _export(case, tmp_path / "package")
    root = Path(report["output_directory"])
    target = root / report["row_shards"][0]["relative_path"]
    if kind == "root_alias":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        report = {**report, "output_directory": str(alias)}
    elif kind == "extra_file":
        (root / "extra").write_bytes(b"unlisted")
    elif kind == "extra_directory":
        (root / "unlisted").mkdir()
    elif kind == "symlink":
        outside = tmp_path / "outside"
        target.rename(outside)
        target.symlink_to(outside)
    elif kind == "missing_file":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises((export.CorpusExportError, ValueError, OSError)):
        _verify(report)


@pytest.mark.parametrize("field,value", [("text", "forged text"), ("split", "holdout"),
    ("source_status", "missing_text"), ("embedding_status", "embedded"),
    ("row_index", 99), ("eligible_alias_count", 99)])
def test_resealed_parquet_content_cannot_override_exact_source_derivation(tmp_path, field, value):
    case = _plain(tmp_path / "source", with_partitions=True)
    report = _export(case, tmp_path / "package")
    manifest = _manifest(report)
    shard = report["row_shards"][0]
    path = Path(report["output_directory"]) / shard["relative_path"]
    table = pq.read_table(path)
    rows = table.to_pylist()
    if rows[0][field] == value:
        value = "train" if field == "split" else "different"
    rows[0][field] = value
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path, compression="zstd")
    raw = path.read_bytes()
    for item in manifest["files"]:
        if item["relative_path"] == shard["relative_path"]:
            item.update(sha256=_sha(raw), bytes=len(raw))
    with pytest.raises((export.CorpusExportError, ValueError)):
        _verify(_reseal(report, manifest))


def test_reordered_physical_rows_fail_even_when_parquet_descriptor_is_resealed(tmp_path):
    case = _plain(tmp_path / "source")
    report = _export(case, tmp_path / "package")
    manifest = _manifest(report)
    path = Path(report["output_directory"]) / report["row_shards"][0]["relative_path"]
    table = pq.read_table(path)
    pq.write_table(pa.Table.from_pylist(table.to_pylist()[::-1], schema=table.schema), path)
    raw = path.read_bytes()
    for item in manifest["files"]:
        if item["relative_path"] == report["row_shards"][0]["relative_path"]:
            item.update(sha256=_sha(raw), bytes=len(raw))
    with pytest.raises((export.CorpusExportError, ValueError)):
        _verify(_reseal(report, manifest))


@pytest.mark.parametrize("which", ["partition", "receipt_set"])
def test_foreign_roots_fail_without_exporting_any_complete_result(tmp_path, which):
    case = _campaign(tmp_path / "source")
    foreign = _case(tmp_path / "foreign", rows=[_row(i) for i in (11, 12, 13)])
    kwargs = ({"partitions": foreign.partitions} if which == "partition"
              else {"receipt_set": foreign.build()})
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        _export(case, destination, **kwargs)
    assert not (destination / "source-export.json").exists()


@pytest.mark.parametrize("change", ["omitted", "added", "digest", "size", "relative_path"])
def test_self_consistent_inventory_cannot_change_the_exact_release_shard_universe(tmp_path, change):
    case = _plain(tmp_path / "source")
    data = case.inventory.to_dict()
    if change == "omitted":
        data["shards"].pop()
    elif change == "added":
        other = _plain(tmp_path / "extra", shards=[[_row(99)]])
        shard = other.inventory.to_dict()["shards"][0]
        shard["artifact"]["relative_path"] = "data/corpus/part-000002.parquet"
        data["shards"].append(shard)
    elif change == "digest":
        data["shards"][0]["artifact"]["sha256"] = "f" * 64
    elif change == "size":
        data["shards"][0]["artifact"]["bytes"] += 1
    else:
        data["shards"][-1]["artifact"]["relative_path"] = "data/corpus/part-000009.parquet"
    # This must be accepted by the metadata codec so the export exercises its
    # stronger full-release binding, rather than merely malformed JSON handling.
    forged = inventory_codec.USCodeSourceInventory(importer._json(data), case.inventory.limits)
    assert forged.sha256 != case.inventory.sha256
    reads = []
    def resolver(ref):
        reads.append(ref["sha256"])
        return case.resolver(ref)
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        export.export_uscode_source_rows(forged, destination, release=case.release, resolver=resolver)
    assert not (set(reads) & {item.sha256 for item in case.release.corpus_shards})
    assert not (destination / "source-export.json").exists()


def test_later_source_resolution_cannot_hide_changed_earlier_source_bytes(tmp_path):
    case = _plain(tmp_path / "source")
    first, second = case.release.corpus_shards
    changed = False
    def resolver(ref):
        nonlocal changed
        path = case.resolver(ref)
        if ref["sha256"] == second.sha256 and not changed:
            changed = True
            old = case.resolver(first.reference)
            old.write_bytes(old.read_bytes() + b"concurrent-change")
        return path
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        export.export_uscode_source_rows(case.inventory, destination,
            release=case.release, resolver=resolver)
    assert changed
    assert not (destination / "source-export.json").exists()


def test_wrong_expected_manifest_digest_and_tighter_reopen_bounds_reject(tmp_path):
    case = _plain(tmp_path / "source")
    report = _export(case, tmp_path / "package")
    with pytest.raises((export.CorpusExportError, ValueError)):
        export.verify_uscode_source_export(report["output_directory"], expected_manifest_sha256="f" * 64)
    with pytest.raises((export.CorpusExportError, ValueError)):
        _verify(report, limits=export.CorpusExportLimits(max_rows=2))


@pytest.mark.parametrize("change", ["authority", "coverage", "unknown_field", "float_bytes", "schema_boolean"])
def test_resealed_manifest_cannot_change_closed_types_coverage_or_authority(tmp_path, change):
    case = _plain(tmp_path / "source")
    report = _export(case, tmp_path / "package")
    manifest = _manifest(report)
    if change == "authority":
        manifest["qualification"]["admitted"] = True
    elif change == "coverage":
        manifest["coverage"]["physical_row_count"] -= 1
    elif change == "unknown_field":
        manifest["unexpected_control_instruction"] = "ignored is unsafe"
    elif change == "schema_boolean":
        manifest["row_schema"][0]["nullable"] = int(manifest["row_schema"][0]["nullable"])
    else:
        manifest["files"][0]["bytes"] = float(manifest["files"][0]["bytes"])
    with pytest.raises((export.CorpusExportError, ValueError)):
        _verify(_reseal(report, manifest))


@pytest.mark.parametrize("kind", ["missing_leaf", "changed_leaf", "changed_nonmissing_text"])
def test_complete_receipt_closure_is_required_before_a_source_package_can_complete(tmp_path, kind):
    case = _campaign(tmp_path / "source")
    receipt = case.kwargs["receipt_set"]
    leaf_ref = receipt.to_dict()["members"][0]["artifact"]
    path = Path(case.kwargs["receipt_resolver"](leaf_ref))
    if kind == "missing_leaf":
        path.unlink()
    elif kind == "changed_leaf":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        raw = case.originals[0]["text"].encode()
        text_path = Path(case.kwargs["source_resolver"]({"sha256": _sha(raw), "bytes": len(raw)}))
        text_path.write_bytes(raw + b" changed")
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        _export(case, destination)
    assert not (destination / "source-export.json").exists()


def test_symlinked_original_source_is_rejected_without_following_alias(tmp_path):
    case = _plain(tmp_path / "source")
    shard = case.release.corpus_shards[0]
    path = case.resolver(shard.reference)
    moved = tmp_path / "moved-source"
    path.rename(moved)
    path.symlink_to(moved)
    destination = tmp_path / "package"
    with pytest.raises((export.CorpusExportError, ValueError)):
        _export(case, destination)
    assert not (destination / "source-export.json").exists()


def test_writer_interruption_retains_partial_evidence_without_complete_manifest(tmp_path, monkeypatch):
    case = _plain(tmp_path / "source")
    real = pq.ParquetWriter
    writes = []
    class InterruptedWriter:
        def __init__(self, *args, **kwargs):
            self.writer = real(*args, **kwargs)
        def write_table(self, table, *args, **kwargs):
            writes.append(table.num_rows)
            if len(writes) == 2:
                raise RuntimeError("injected second-batch interruption")
            return self.writer.write_table(table, *args, **kwargs)
        def close(self):
            return self.writer.close()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()
    monkeypatch.setattr(pq, "ParquetWriter", InterruptedWriter)
    destination = tmp_path / "package"
    with pytest.raises((RuntimeError, export.CorpusExportError), match="interruption|export|write"):
        _export(case, destination, batch_size=1)
    assert len(writes) == 2
    assert destination.exists()
    assert not (destination / "source-export.json").exists()


def test_each_completed_file_is_synced_before_its_immediate_parent_directory(tmp_path, monkeypatch):
    case = _plain(tmp_path / "source")
    real_sync = os.fsync
    events = []
    def observe(fd):
        info = os.fstat(fd)
        events.append(("directory" if stat.S_ISDIR(info.st_mode) else "file",
                       info.st_dev, info.st_ino))
        return real_sync(fd)
    monkeypatch.setattr(os, "fsync", observe)
    report = _export(case, tmp_path / "package", batch_size=1)
    root = Path(report["output_directory"])
    files = [root / item["relative_path"] for item in _manifest(report)["files"]]
    files.append(root / "source-export.json")
    assert any(len(path.relative_to(root).parts) > 3 for path in files)
    for path in files:
        file_info, parent_info = path.stat(), path.parent.stat()
        event = ("file", file_info.st_dev, file_info.st_ino)
        position = events.index(event)
        assert events[position + 1] == ("directory", parent_info.st_dev, parent_info.st_ino)
    assert _verify(report)["row_count"] == 3


@pytest.mark.parametrize("artifact", ["nested_source", "completion_manifest"])
@pytest.mark.parametrize("stage", ["file", "parent"])
def test_sync_failure_closes_both_descriptors_and_leaves_no_completion_marker(tmp_path, monkeypatch, artifact, stage):
    case = _plain(tmp_path / "source")
    destination = tmp_path / "package"
    wanted = ("source/corpus/" + case.release.corpus_shards[0].relative_path
              if artifact == "nested_source" else "source-export.json")
    original_init, real_sync = export._Output.__init__, os.fsync
    captured, failed = {}, []
    def remember(self, root_fd, relative, budget):
        original_init(self, root_fd, relative, budget)
        if relative == wanted:
            captured.update(file=self._stream.fileno(), parent=self._parent_fd,
                            stream=self._stream, output=self)
    def fail_selected_sync(fd):
        if captured and fd == captured[stage] and not failed:
            assert (destination / wanted).is_file()
            failed.append(stage)
            raise OSError(errno.EIO, "injected durability sync failure")
        return real_sync(fd)
    monkeypatch.setattr(export._Output, "__init__", remember)
    monkeypatch.setattr(os, "fsync", fail_selected_sync)
    with pytest.raises(export.CorpusExportError, match="durability sync failure"):
        _export(case, destination, batch_size=1)
    assert failed == [stage]
    assert captured["stream"].closed and captured["output"].closed
    for name in ("file", "parent"):
        with pytest.raises(OSError) as error:
            os.fstat(captured[name])
        assert error.value.errno == errno.EBADF
    assert destination.is_dir()
    assert not (destination / "source-export.json").exists()
