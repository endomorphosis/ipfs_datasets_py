"""Tiny isolated native source storage; no model, source DB, listener or upload.

Native DuckLake is real here. Failure proxies interrupt the current process at
transaction/response boundaries; they do not claim OS-kill recovery coverage.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.duckdb_control import source_corpus_catalog as catalog
from ipfs_datasets_py.duckdb_control.source_corpus_binding import SourceCorpusBinding
from ipfs_datasets_py.ducklake import source_corpus as lake
from tests.unit.huggingface.test_source_corpus_release import _fixture, _ids
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_corpus_export import offline_only


def _forbidden(*args, **kwargs):
    pytest.fail("native source sink must not open the historical catalog")


@pytest.fixture(autouse=True)
def no_source_database(monkeypatch):
    monkeypatch.setattr(catalog.SourceCorpusCatalog, "__init__", _forbidden)


@pytest.fixture
def fixture(tmp_path):
    return _fixture(tmp_path / "input")


def _root(package):
    return Path(package.report["output_directory"])


def _source(version):
    return {key: value for key, value in version.items() if key != "package_directory"}


def _files(root):
    return {str(path.relative_to(root)): (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in root.rglob("*") if path.is_file()}


def _read(sink, version_id, limit=2):
    rows, after = [], -1
    for _ in range(100):
        page = sink.read_rows(version_id, after_ordinal=after, limit=limit)
        assert page["row_count"] == len(page["rows"]) <= limit
        rows.extend(page["rows"])
        if page["complete"]:
            assert page["next_after_ordinal"] is None
            return rows
        assert page["rows"] and page["next_after_ordinal"] > after
        after = page["next_after_ordinal"]
    pytest.fail("native source pagination did not terminate")


def _counts(sink):
    return {table: sink._connection.execute("SELECT count(*) FROM corpus." + table).fetchone()[0]
            for table in ("releases", "versions", "operations", "rows")}


def test_actual_native_rows_snapshot_replay_reopen_and_source_independence(tmp_path, fixture):
    package, version = fixture
    original = _files(_root(package))
    expected = [{"ordinal": i, **row} for i, row in enumerate(package.expected)]
    with SourceCorpusBinding(version, _root(package)) as binding:
        with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
            receipt = sink.materialize_version("import", binding)
            assert receipt == sink.lookup("import", binding.source_version) == sink.materialize_version("import", binding)
            assert receipt["snapshot_id"] == sink._connection.execute("SELECT id FROM corpus.last_committed_snapshot()").fetchone()[0]
            assert receipt["source_rows_verified"] is True
            assert receipt["source_package_currently_verified"] is False
            assert all(value is False for value in receipt["qualification"].values())
            assert receipt["source_version"] == _source(version)
            assert _read(sink, version["version_id"]) == expected
            assert _counts(sink) == {"releases": 1, "versions": 1, "operations": 1, "rows": len(expected)}
            identity = sink.identity
            identity["runtime"]["duckdb"] = "modified-detached-copy"
            assert sink.identity["runtime"]["duckdb"] == "1.5.5"
    assert _files(_root(package)) == original
    assert list((tmp_path / "lake/data").rglob("*.parquet"))
    shutil.rmtree(package.original_root)
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake") as reopened:
        assert reopened.lookup("import", _source(version)) == receipt
        assert _read(reopened, version["version_id"]) == expected


def test_new_operation_and_language_version_reuse_exact_physical_release(tmp_path, fixture):
    package, version = fixture
    translated_label = deepcopy(version)
    translated_label["dataset"]["source_language"] = "declared-only"
    _ids(translated_label)
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            first = sink.materialize_version("first", binding)
            second = sink.materialize_version("second", binding)
        with SourceCorpusBinding(translated_label, _root(package)) as binding:
            third = sink.materialize_version("third", binding)
        assert first["snapshot_id"] < second["snapshot_id"] < third["snapshot_id"]
        assert _counts(sink) == {"releases": 1, "versions": 2, "operations": 3, "rows": len(package.expected)}
        assert third["qualification"]["language_verified"] is False


def test_same_operation_changed_binding_rejects_without_snapshot(tmp_path, fixture):
    package, version = fixture
    changed = deepcopy(version)
    changed["dataset"]["namespace"] = "other"
    _ids(changed)
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            first = sink.materialize_version("same", binding)
        with SourceCorpusBinding(changed, _root(package)) as binding:
            with pytest.raises(lake.SourceCorpusLakeError, match="conflicts"):
                sink.materialize_version("same", binding)
        assert sink._connection.execute("SELECT id FROM corpus.last_committed_snapshot()").fetchone() == (first["snapshot_id"],)


@pytest.mark.parametrize("statement", [
    "DELETE FROM corpus.operations",
    "UPDATE corpus.operations SET request_json='{}'",
    "UPDATE corpus.operations SET commit_key='wrong'",
    "INSERT INTO corpus.operations SELECT * FROM corpus.operations",
    "DELETE FROM corpus.versions",
    "UPDATE corpus.versions SET version_json='{}'",
    "UPDATE corpus.releases SET summary_json='{}'",
    "DELETE FROM corpus.rows WHERE ordinal=0",
    "UPDATE corpus.rows SET ordinal=ordinal+1",
    "UPDATE corpus.rows SET text='altered' WHERE ordinal=0",
    "UPDATE corpus.rows SET admitted=true WHERE ordinal=0",
    "INSERT INTO corpus.rows SELECT * FROM corpus.rows WHERE ordinal=0",
])
def test_marker_version_or_physical_row_corruption_rejects_current_lookup(tmp_path, fixture, statement):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            sink.materialize_version("import", binding)
        sink._connection.execute(statement)
        with pytest.raises(ValueError):
            sink.lookup("import", _source(version))


@pytest.mark.parametrize("field", ["limit", "max_bytes", "after_ordinal"])
def test_page_boolean_bounds_rejected(tmp_path, field):
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with pytest.raises(lake.SourceCorpusLakeError, match="bounds"):
            sink.read_rows("unknown", **{field: True})


def test_page_byte_limit_exhaustion_and_missing_version(tmp_path, fixture):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            sink.materialize_version("import", binding)
        with pytest.raises(lake.SourceCorpusLakeError, match="byte bound"):
            sink.read_rows(version["version_id"], max_bytes=2)
        assert sink.read_rows(version["version_id"], after_ordinal=len(package.expected) - 1) == {
            "version_id": version["version_id"], "rows": [], "row_count": 0, "complete": True, "next_after_ordinal": None}
        with pytest.raises(lake.SourceCorpusLakeError, match="not committed"):
            sink.read_rows("missing")


@pytest.mark.parametrize("ordinal,after,limit", [(0, -1, 2), (2, 1, 2), (5, 3, 2)])
def test_missing_first_boundary_or_final_page_ordinal_fails(tmp_path, fixture, ordinal, after, limit):
    package, version = fixture
    assert len(package.expected) == 6
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            sink.materialize_version("import", binding)
        sink._connection.execute("DELETE FROM corpus.rows WHERE ordinal=?", [ordinal])
        with pytest.raises(lake.SourceCorpusLakeError, match="ordinal|missing"):
            sink.read_rows(version["version_id"], after_ordinal=after, limit=limit)


def test_existing_version_accepts_new_operation_at_version_cap(tmp_path, fixture, monkeypatch):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            sink.materialize_version("first", binding)
            monkeypatch.setattr(lake, "MAX_VERSIONS", 1)
            assert sink.materialize_version("second", binding)["operation_id"] == "second"
            assert _counts(sink)["versions"] == 1


def test_source_package_containing_sink_rejected_before_row_mutation(tmp_path, fixture):
    package, version = fixture
    with SourceCorpusBinding(version, _root(package)) as binding:
        with lake.IsolatedNativeSourceCorpus(_root(package) / "lake", create=True) as sink:
            with pytest.raises(lake.SourceCorpusLakeError, match="overlap"):
                sink.materialize_version("import", binding)
            assert _counts(sink) == dict.fromkeys(("releases", "versions", "operations", "rows"), 0)


class _Proxy:
    def __init__(self, connection, *, fail_before=False, fail_after=False):
        self.connection, self.fail_before, self.fail_after = connection, fail_before, fail_after

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, statement, *args):
        if self.fail_before and statement.startswith("CALL corpus.set_commit_message"):
            raise RuntimeError("injected before commit")
        result = self.connection.execute(statement, *args)
        if self.fail_after and statement == "COMMIT":
            raise RuntimeError("injected lost commit response")
        return result


def test_insert_flush_row_and_byte_bounds_preserve_exact_digest(tmp_path, fixture, monkeypatch):
    package, version = fixture
    monkeypatch.setattr(lake, "MAX_INSERT_ROWS", 2)
    batches = []
    class ObserveBatches(_Proxy):
        def register(self, name, table):
            assert name == "_verified_source_batch"
            assert 0 < table.num_rows <= 2
            assert table.nbytes <= lake.MAX_ROW_BYTES
            assert len(lake._json(table.to_pylist()).encode()) <= lake.MAX_ROW_BYTES
            batches.append(table.num_rows)
            return self.connection.register(name, table)
    with SourceCorpusBinding(version, _root(package)) as binding:
        with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
            native = sink._connection
            sink._connection = ObserveBatches(native)
            receipt = sink.materialize_version("import", binding)
            sink._connection = native
            assert batches == [2, 2, 2]
            assert receipt["row_digest"] == version["row_digest"]
            assert sink.lookup("import", binding.source_version) == receipt
            assert _read(sink, version["version_id"]) == [
                {"ordinal": ordinal, **row} for ordinal, row in enumerate(package.expected)]
            assert sink.identity["max_insert_rows"] == 2
            assert sink.identity["max_insert_batch_bytes"] == lake.MAX_ROW_BYTES


@pytest.mark.parametrize("phase", ["before", "after"])
def test_transaction_or_response_failure_reconciles_after_owner_reopen(tmp_path, fixture, phase):
    package, version = fixture
    with SourceCorpusBinding(version, _root(package)) as binding:
        with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
            native = sink._connection
            sink._connection = _Proxy(native, fail_before=phase == "before", fail_after=phase == "after")
            with pytest.raises(RuntimeError, match="injected"):
                sink.materialize_version("import", binding)
            sink._connection = native
            if phase == "before":
                assert _counts(sink) == dict.fromkeys(("releases", "versions", "operations", "rows"), 0)
        with lake.IsolatedNativeSourceCorpus(tmp_path / "lake") as reopened:
            observed = reopened.lookup("import", binding.source_version)
            assert (observed is None) is (phase == "before")
            final = reopened.materialize_version("import", binding)
            assert reopened.lookup("import", binding.source_version) == final
            if observed:
                assert observed == final
            assert _counts(reopened)["rows"] == len(package.expected)
            assert _counts(reopened)["operations"] == 1


def test_source_nonrow_mutation_during_insert_rolls_back(tmp_path, fixture, monkeypatch):
    package, version = fixture
    with SourceCorpusBinding(version, _root(package)) as binding:
        with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
            original = sink._insert_rows
            def changed(*args):
                original(*args)
                (_root(package) / "README.md").write_text("changed fixture source")
            monkeypatch.setattr(sink, "_insert_rows", changed)
            with pytest.raises(ValueError):
                sink.materialize_version("import", binding)
            assert _counts(sink) == dict.fromkeys(("releases", "versions", "operations", "rows"), 0)


def test_arrow_insert_failure_rolls_back_uncommitted_rows(tmp_path, fixture):
    package, version = fixture
    with SourceCorpusBinding(version, _root(package)) as binding:
        with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
            native = sink._connection
            class InsertThenFail(_Proxy):
                def execute(self, statement, *args):
                    result = self.connection.execute(statement, *args)
                    if statement == "INSERT INTO corpus.rows SELECT * FROM _verified_source_batch":
                        assert self.connection.execute("SELECT count(*) FROM corpus.rows").fetchone()[0] > 0
                        raise RuntimeError("injected after actual Arrow insert")
                    return result
            sink._connection = InsertThenFail(native)
            with pytest.raises(RuntimeError, match="actual Arrow insert"):
                sink.materialize_version("import", binding)
            sink._connection = native
            assert _counts(sink) == dict.fromkeys(("releases", "versions", "operations", "rows"), 0)


def test_fake_or_closed_source_binding_rejected(tmp_path, fixture):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with pytest.raises(lake.SourceCorpusLakeError, match="exact source binding"):
            sink.materialize_version("import", object())
        binding = SourceCorpusBinding(version, _root(package))
        with pytest.raises(ValueError):
            sink.materialize_version("import", binding)
        with binding:
            pass
        with pytest.raises(ValueError):
            sink.materialize_version("import", binding)


def test_storage_cap_and_reopen_identity_are_explicit(tmp_path, fixture):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True, max_storage_bytes=4 * 1024**2) as sink:
        with SourceCorpusBinding(version, _root(package)) as binding:
            with pytest.raises(lake.SourceCorpusLakeError, match="reserve"):
                sink.materialize_version("import", binding)
        assert _counts(sink) == dict.fromkeys(("releases", "versions", "operations", "rows"), 0)
    with pytest.raises(lake.SourceCorpusLakeError, match="descriptor/runtime"):
        lake.IsolatedNativeSourceCorpus(tmp_path / "lake")
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", max_storage_bytes=4 * 1024**2):
        pass


@pytest.mark.parametrize("flags", [
    {"production": True}, {"production": 1}, {"create": 1},
    {"max_storage_bytes": True}, {"max_storage_bytes": 0}, {"max_storage_bytes": lake.MAX_STORAGE_BYTES + 1},
])
def test_invalid_native_flags_reject_before_directory_creation(tmp_path, flags):
    with pytest.raises(lake.SourceCorpusLakeError):
        lake.IsolatedNativeSourceCorpus(tmp_path / "lake", **flags)
    assert not (tmp_path / "lake").exists()


def test_second_owner_path_alias_and_foreign_process_fail_closed(tmp_path, fixture, monkeypatch):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        with pytest.raises(BlockingIOError):
            lake.IsolatedNativeSourceCorpus(tmp_path / "lake")
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path / "lake", target_is_directory=True)
        with pytest.raises(lake.SourceCorpusLakeError, match="aliased"):
            lake.IsolatedNativeSourceCorpus(alias)
        with monkeypatch.context() as patch:
            patch.setattr(lake.os, "getpid", lambda: sink._pid + 1)
            with pytest.raises(lake.SourceCorpusLakeError, match="inherited"):
                sink.lookup("missing", _source(version))
            with pytest.raises(lake.SourceCorpusLakeError, match="inherited"):
                sink.close()


@pytest.mark.parametrize("mutation", ["root", "catalog", "data", "descriptor", "hardlink", "extra_table"])
def test_native_namespace_changes_reject(tmp_path, fixture, mutation):
    package, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        moved = None
        if mutation in {"root", "catalog", "data"}:
            path = {"root": sink.root, "catalog": sink._catalog, "data": sink._data}[mutation]
            moved = path.with_name(path.name + ".old")
            path.rename(moved)
            if mutation == "catalog":
                path.write_bytes(b"replacement")
            else:
                path.mkdir()
        elif mutation == "descriptor":
            sink._descriptor.write_text("{}")
        elif mutation == "hardlink":
            outside = tmp_path / "outside"
            outside.write_bytes(b"fixture")
            os.link(outside, sink.root / "linked")
        else:
            sink._connection.execute("CREATE TABLE corpus.extra (value INTEGER)")
        try:
            with pytest.raises((ValueError, OSError)):
                sink.lookup("missing", _source(version))
        finally:
            # Restore only this fixture's substituted pathname before closing
            # the native handle; the changed namespace was already rejected.
            if moved is not None:
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                moved.rename(path)


def test_runtime_loader_failure_cannot_create_success_descriptor(tmp_path, monkeypatch):
    def bad_runtime():
        raise lake.history.HistoryError("injected extension digest mismatch")
    monkeypatch.setattr(lake.history, "_native_connection", bad_runtime)
    with pytest.raises(lake.history.HistoryError, match="digest"):
        lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True)
    assert not (tmp_path / "lake/source.json").exists()


def test_extension_identity_change_denies_next_boundary(tmp_path, fixture, monkeypatch):
    _, version = fixture
    with lake.IsolatedNativeSourceCorpus(tmp_path / "lake", create=True) as sink:
        original = lake._signature
        extension = next(iter(sink._extension_signatures))
        def changed(path):
            value = original(path)
            return (*value[:-1], value[-1] + 1) if str(path) == extension else value
        monkeypatch.setattr(lake, "_signature", changed)
        with pytest.raises(lake.SourceCorpusLakeError, match="extension changed"):
            sink.lookup("missing", _source(version))
