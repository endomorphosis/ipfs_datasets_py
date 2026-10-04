"""Native restart, corruption and atomic publication checks for the AST store."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    SourceProvenance,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_TABLES,
    DuckDBASTStore,
    DuckDBASTStoreIntegrityError,
    InvalidationRow,
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor


def projection(
    source="def increment(n):\n    return n + 1\n",
    *,
    path="example.py",
    revision="r1",
    at=1.0,
):
    record = PythonASTExtractor().extract_from_source(
        source, path=path, repository_id="repository:test", revision=revision
    )
    return project_ast_record(record, created_at=at)


@pytest.fixture
def database(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    path = tmp_path / "ast.duckdb"
    connection = duckdb.connect(str(path), config={"threads": "1"})
    yield duckdb, path, connection
    connection.close()


def test_restart_exact_reads_without_catalog_hydration(database):
    duckdb, path, connection = database
    store = DuckDBASTStore(connection=connection)
    first, second = projection(), projection(path="second.py", at=2.0)
    store.apply_batch((first, second))
    connection.close()
    with duckdb.connect(str(path), config={"threads": "1"}) as reopened:
        reader = DuckDBASTStore(connection=reopened)
        assert not reader._by_blob
        assert reader.stats()["size"] == 2
        assert reader.get(first.blob_id) == first
        assert reader.get_by_ast_cid(second.ast_cid) == second
        assert reader.get_by_file_id(first.source_file.file_id) == first
        assert not reader._by_blob  # Reads do not accumulate the catalog in RAM.
        assert reader.get("blob:absent") is None


def test_actual_fresh_process_reads_committed_projection(database):
    _, path, connection = database
    expected = projection()
    DuckDBASTStore(connection=connection).put_projection(expected)
    connection.close()
    script = """
import json, sys, duckdb
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
with duckdb.connect(sys.argv[1], config={'threads': '1'}) as connection:
    store = DuckDBASTStore(connection=connection)
    row = store.get(sys.argv[2])
    print(json.dumps({'ast_cid': row.ast_cid, 'symbol': row.symbols[0].name,
                      'size': store.stats()['size'], 'resident': len(store._by_blob)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), expected.blob_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "ast_cid": expected.ast_cid,
        "symbol": "increment",
        "size": 1,
        "resident": 0,
    }


def test_failure_evidence_and_invalidation_survive_reopen(database):
    duckdb, path, connection = database
    store = DuckDBASTStore(connection=connection)
    failed = store.put_parse_failure(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(b"def ???"),
            path="broken.py",
            repository_id="repository:test",
            revision="r1",
        ),
        language="python",
        message="invalid syntax",
        span=SourceSpan(0, 7, 1, 0, 1, 7),
        created_at=1.0,
    )
    good = store.put_projection(projection(path="good.py"))
    invalidated = store.invalidate(
        blob_id=good.blob_id, reason="source_changed", created_at=3.0
    )
    connection.close()
    with duckdb.connect(str(path), config={"threads": "1"}) as reopened:
        reader = DuckDBASTStore(connection=reopened)
        assert reader.get(failed.blob_id) == failed
        assert reader.query_parse_failures(path="broken.py") == failed.diagnostics
        assert reader.query_diagnostics(blob_id=failed.blob_id) == failed.diagnostics
        assert reader.query_parse_failures(path="missing.py") == ()
        assert reader.get(good.blob_id) is None
        assert reader.get_by_file_id(good.source_file.file_id) is None
        assert reader.list_invalidations(blob_id=good.blob_id) == (invalidated,)
        assert reader.stats()["size"] == 1
        assert reader.stats()["invalidation_count"] == 2


@pytest.mark.parametrize("scope", ["blob_id", "file_id", "revision_id"])
def test_scoped_invalidation_matches_memory_and_durable_modes(database, scope):
    duckdb, path, connection = database
    first = projection()
    unrelated = projection(path="other.py", revision="r2")
    for store in (DuckDBASTStore(), DuckDBASTStore(connection=connection)):
        store.apply_batch((first, unrelated))
        selector = {
            "blob_id": first.blob_id,
            "file_id": first.source_file.file_id,
            "revision_id": first.source_revision.revision_id,
        }[scope]
        store.invalidate(**{scope: selector})
        assert store.get(first.blob_id) is None
        assert store.get(unrelated.blob_id) == unrelated
    connection.close()
    with duckdb.connect(str(path)) as reopened:
        reader = DuckDBASTStore(connection=reopened)
        assert reader.get(first.blob_id) is None
        assert reader.get(unrelated.blob_id) == unrelated


def test_replacement_after_restart_keeps_one_active_file(database):
    duckdb, path, connection = database
    old = projection()
    DuckDBASTStore(connection=connection).put_projection(old)
    connection.close()
    new = projection("def increment(n):\n    return n + 2\n", at=2.0)
    with duckdb.connect(str(path)) as reopened:
        store = DuckDBASTStore(connection=reopened)
        store.put_projection(new)
        assert store.get(old.blob_id) is None
        assert store.get_by_file_id(new.source_file.file_id) == new
        assert (
            store.list_invalidations(blob_id=old.blob_id)[0].reason == "blob_replaced"
        )
        assert store.stats()["size"] == 1
        assert reopened.execute(
            "SELECT count(DISTINCT blob_id) FROM symbols"
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE symbols SET name='forged'",
        "DELETE FROM symbols",
        "UPDATE ast_blobs SET ast_cid='forged'",
        "UPDATE ast_blobs SET payload_json='{}'",
        "UPDATE source_files SET source_cid='forged'",
        "UPDATE source_revisions SET revision='forged'",
        "UPDATE ast_nodes SET end_byte=end_byte+1",
        "UPDATE ast_blobs SET parse_status='partial'",
    ],
)
def test_corrupt_persisted_projection_fails_closed_even_after_a_hit(database, mutation):
    _, _, connection = database
    store = DuckDBASTStore(connection=connection)
    expected = store.put_projection(projection())
    assert store.get(expected.blob_id) == expected
    connection.execute(mutation)
    with pytest.raises(DuckDBASTStoreIntegrityError):
        store.get(expected.blob_id)


def test_supplied_projection_cannot_forge_relational_facts(database):
    _, _, connection = database
    store = DuckDBASTStore(connection=connection)
    row = projection()
    forged = replace(row, symbols=(replace(row.symbols[0], name="forged"),))
    with pytest.raises(DuckDBASTStoreIntegrityError):
        store.put_projection(forged)
    assert store.stats()["size"] == 0


def test_atomic_batch_rolls_back_replacement_and_audit_rows_on_sql_failure(
    database, monkeypatch
):
    _, _, connection = database
    store = DuckDBASTStore(connection=connection)
    old = store.put_projection(projection())
    changed = projection("def increment(n):\n    return n + 2\n", at=2.0)
    other = projection(path="other.py")
    before = store.stats()
    persist = store._persist_projection

    def fail_on_second(row):
        persist(row)
        if row.blob_id == other.blob_id:
            raise RuntimeError("simulated writer failure")

    monkeypatch.setattr(store, "_persist_projection", fail_on_second)
    with pytest.raises(RuntimeError, match="simulated"):
        store.apply_batch((changed, other))
    assert store.stats() == before
    assert store.get(old.blob_id) == old
    assert store.get(changed.blob_id) is None
    assert store.get(other.blob_id) is None
    assert store.list_invalidations() == ()
    assert not store._by_blob
    assert DuckDBASTStore(connection=connection).get(old.blob_id) == old


def test_atomic_memory_batch_restores_prior_state_on_failure(monkeypatch):
    store = DuckDBASTStore()
    old = store.put_projection(projection())
    changed = projection("def increment(n):\n    return n + 2\n", at=2.0)
    invalidate = InvalidationRow(
        "inv:test", None, None, "r2", "manual", "tester", "", 4.0
    )
    original = store._apply_invalidation

    def fail_after_mutation(row):
        original(row)
        if row.invalidation_id == invalidate.invalidation_id:
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(store, "_apply_invalidation", fail_after_mutation)
    before = store.stats()
    with pytest.raises(RuntimeError, match="simulated"):
        store.apply_batch((changed,), (invalidate,))
    assert store.stats() == before
    assert store.get(old.blob_id) is old
    assert store.get(changed.blob_id) is None
    assert store.list_invalidations() == ()


def test_native_batch_and_reopen_preserve_revision_publication(database):
    duckdb, path, connection = database
    store = DuckDBASTStore(connection=connection)
    old = store.put_projection(projection())
    successors = (
        projection(revision="r2"),
        projection(path="second.py", revision="r2"),
    )
    invalidation = InvalidationRow(
        "inv:revision",
        None,
        None,
        old.source_revision.revision_id,
        "revision_superseded",
        "ingest",
        "r2 published",
        2.0,
    )
    assert store.apply_batch(successors, (invalidation,)) == (
        successors,
        (invalidation,),
    )
    connection.close()
    with duckdb.connect(str(path)) as reopened:
        reader = DuckDBASTStore(connection=reopened)
        assert reader.get(old.blob_id) is None
        assert tuple(reader.get(row.blob_id) for row in successors) == successors
        assert reader.list_invalidations() == (invalidation,)


def test_clear_is_durable(database):
    duckdb, path, connection = database
    store = DuckDBASTStore(connection=connection)
    row = store.put_projection(projection())
    store.invalidate(blob_id=row.blob_id)
    store.clear()
    assert all(
        connection.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (0,)
        for table in ASTS_CATALOG_TABLES
    )
    connection.close()
    with duckdb.connect(str(path)) as reopened:
        reader = DuckDBASTStore(connection=reopened)
        assert reader.stats()["size"] == 0
        assert reader.list_invalidations() == ()


@pytest.mark.parametrize(
    "source, options, code",
    [
        ("def unfinished(", {}, "python.parse_error"),
        (b"\xff", {}, "python.invalid_encoding"),
        (
            "def valid():\n    return 1\n",
            {"max_source_bytes": 4},
            "python.resource_limit",
        ),
    ],
)
def test_native_frontend_failure_is_not_success_and_survives_reopen(
    database, source, options, code
):
    duckdb, path, connection = database
    record = PythonASTExtractor(**options).extract_from_source(
        source, path="broken.py", repository_id="repository:test", revision="r1"
    )
    expected = DuckDBASTStore(connection=connection).put(record, created_at=1.0)
    assert expected.ast_blob.parse_status == "failed"
    assert expected.ast_blob.parse_error
    assert expected.diagnostics[0].code == code
    assert expected.diagnostics[0].is_parse_failure
    connection.close()
    with duckdb.connect(str(path)) as reopened:
        store = DuckDBASTStore(connection=reopened)
        assert store.get(expected.blob_id) == expected
        assert store.query_parse_failures(path="broken.py") == expected.diagnostics


def test_eight_small_files_fit_bounded_native_transaction(database):
    """Per-row conflict updates previously exhausted 128MB for this 65KB AST."""
    _, _, connection = database
    connection.execute("SET memory_limit='64MB'")
    store = DuckDBASTStore(connection=connection)

    def units(delta):
        return tuple(
            projection(
                "\n".join(
                    f"def f{j}(n: int) -> int:\n    return n + {i * 4 + j + delta}\n"
                    for j in range(4)
                ),
                path=f"unit_{i}.py",
            )
            for i in range(8)
        )

    original = units(1)
    assert sum(len(row.ast_blob.payload_json.encode()) for row in original) < 128 * 1024
    for batch in (original, original, units(2)):
        # Exercise cold append, same-CID rewrite, and replacement under the
        # native buffer budget. One atomic transaction covers all eight files.
        assert store.apply_batch(batch)[0] == batch
        assert store.stats()["size"] == 8
        assert tuple(store.get(row.blob_id) for row in batch) == batch
    assert len(store.list_invalidations()) == 8
    assert all(store.get(row.blob_id) is None for row in original)
