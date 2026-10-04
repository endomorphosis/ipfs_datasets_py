"""Fresh bounded SQL snapshots retain scalar AST integrity and active fences."""
import pytest

from ipfs_datasets_py.logic.software_contracts import duckdb_ast_store as owner
from ipfs_datasets_py.logic.software_contracts.ast_ir import SourceProvenance, SourceSpan
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor


def projection(name="first", *, revision="r1", at=1.0):
    record = PythonASTExtractor().extract_from_source(
        f"def {name}(value):\n    return value + 1\n", path=name + ".py",
        repository_id="repository:batch-read", revision=revision)
    return owner.project_ast_record(record, created_at=at)


class ObservedConnection:
    def __init__(self, connection):
        self.connection, self.statements = connection, []

    def execute(self, statement, *args):
        self.statements.append(statement)
        return self.connection.execute(statement, *args)


@pytest.fixture
def store(tmp_path):
    import duckdb
    connection = duckdb.connect(str(tmp_path / "ast.duckdb"), config={"threads": "1"})
    observed = ObservedConnection(connection)
    try:
        yield owner.DuckDBASTStore(connection=observed), observed
    finally:
        connection.close()


def test_batch_matches_scalar_requests_and_reduces_sql(store):
    index, connection = store
    rows = [projection(f"function_{number}", revision=f"r{number % 3}", at=number + 1.)
            for number in range(31)]
    index.apply_batch(rows)
    keys = [row.ast_cid for row in rows]
    connection.statements.clear()
    scalar = tuple(index.get_by_ast_cid(key) for key in keys)
    scalar_selects = sum(sql.startswith("SELECT ") for sql in connection.statements)
    connection.statements.clear()
    batch = index.get_many_by_ast_cid(keys)
    assert batch == scalar == tuple(rows)
    assert scalar_selects == 13 * len(rows)
    assert sum(sql.startswith("SELECT ") for sql in connection.statements) == 13
    assert connection.statements.count("BEGIN TRANSACTION") == 1
    assert connection.statements.count("COMMIT") == 1
    assert not index._by_blob
    before = index.stats()
    assert index.get_many_by_ast_cid([keys[1], "ast:missing", keys[1]]) == (rows[1], None, rows[1])
    assert index.stats()["lookups"] == before["lookups"] + 3
    assert index.stats()["misses"] == before["misses"] + 1


def test_memory_mode_and_empty_batches_preserve_scalar_behavior():
    index = owner.DuckDBASTStore()
    row = index.put_projection(projection())
    assert index.get_many_by_ast_cid([row.ast_cid, "missing", row.ast_cid]) == (row, None, row)
    assert index.get_many_by_ast_cid([]) == ()
    index.require_active_identities([])
    index.require_active_identities([row])
    index.invalidate(blob_id=row.blob_id)
    assert index.get_many_by_ast_cid([row.ast_cid]) == (None,)
    with pytest.raises(owner.DuckDBASTStoreIntegrityError, match="no longer active"):
        index.require_active_identities([row])


def test_parse_failure_intrinsic_rows_are_fully_reverified(store):
    index, connection = store
    good = index.put_projection(projection())
    failed = index.put_parse_failure(provenance=SourceProvenance(
        source_cid=cid_for_bytes(b"def ???"), path="broken.py", repository_id="repository:batch-read",
        revision="r1"), language="python", message="invalid syntax",
        span=SourceSpan(0, 7, 1, 0, 1, 7), created_at=1.)
    assert index.get_many_by_ast_cid([good.ast_cid, failed.ast_cid]) == (good, failed)
    index.require_active_identities([good, failed])
    connection.execute("DELETE FROM invalidations WHERE blob_id=?", [failed.blob_id])
    with pytest.raises(owner.DuckDBASTStoreIntegrityError):
        index.get_many_by_ast_cid([good.ast_cid, failed.ast_cid])


@pytest.mark.parametrize("mutation", [
    "UPDATE symbols SET name='forged'", "DELETE FROM symbols",
    "UPDATE ast_blobs SET payload_json='{}'", "UPDATE source_files SET source_cid='forged'",
    "UPDATE source_revisions SET revision='forged'", "UPDATE ast_nodes SET end_byte=end_byte+1",
    "UPDATE ast_blobs SET parse_status='partial'", "UPDATE source_revisions SET created_at='nan'",
])
def test_batch_rechecks_tampered_rows_after_successful_read(store, mutation):
    index, connection = store
    row = index.put_projection(projection())
    assert index.get_many_by_ast_cid([row.ast_cid]) == (row,)
    connection.execute(mutation)
    with pytest.raises(owner.DuckDBASTStoreIntegrityError):
        index.get_many_by_ast_cid([row.ast_cid])
    with pytest.raises(owner.DuckDBASTStoreIntegrityError):
        index.get_by_ast_cid(row.ast_cid)


@pytest.mark.parametrize("mutation", ["invalidation", "replacement", "payload", "file", "revision"])
def test_fresh_identity_fence_detects_changes_after_batch_read(store, mutation):
    index, connection = store
    first, other = projection(), projection("other", at=2.)
    index.apply_batch([first, other])
    loaded = index.get_many_by_ast_cid([first.ast_cid, other.ast_cid])
    index.require_active_identities(loaded)
    if mutation == "invalidation":
        index.invalidate(blob_id=first.blob_id)
    elif mutation == "replacement":
        record = PythonASTExtractor().extract_from_source("def first(value):\n    return value + 2\n",
            path="first.py", repository_id="repository:batch-read", revision="r1")
        index.put(record, created_at=3.)
    elif mutation == "payload":
        connection.execute("UPDATE ast_blobs SET payload_json='{}' WHERE blob_id=?", [first.blob_id])
    elif mutation == "file":
        connection.execute("UPDATE source_files SET source_cid='forged' WHERE file_id=?", [first.source_file.file_id])
    else:
        connection.execute("UPDATE source_revisions SET revision='forged' WHERE revision_id=?",
                           [first.source_revision.revision_id])
    with pytest.raises(owner.DuckDBASTStoreIntegrityError):
        index.require_active_identities(loaded)


@pytest.mark.parametrize("bound", ["rows", "payload"])
def test_aggregate_overflow_requires_split_without_loading_scalar_tuple(store, monkeypatch, bound):
    index, connection = store
    rows = [projection("first"), projection("other")]
    index.apply_batch(rows)
    if bound == "rows":
        monkeypatch.setattr(owner, "MAX_QUERY_ROWS", max(max(row.table_row_counts().values()) for row in rows))
    else:
        monkeypatch.setattr(owner, "MAX_BATCH_PAYLOAD_BYTES", max(len(row.ast_blob.payload_json.encode()) for row in rows))
    with monkeypatch.context() as limited:
        limited.setattr(index, '_load', lambda *_: pytest.fail('oversized batch loaded scalar tuple'))
        with pytest.raises(owner.DuckDBASTBatchReadLimitError, match='split'):
            index.get_many_by_ast_cid([row.ast_cid for row in rows])
    assert 'ROLLBACK' in connection.statements
    assert tuple(index.get_many_by_ast_cid([row.ast_cid])[0] for row in rows) == tuple(rows)
    for row in rows:
        index.require_active_identities([row])
    if bound == 'payload':
        with pytest.raises(owner.DuckDBASTBatchReadLimitError, match='split'):
            index.require_active_identities(rows)


def test_memory_mode_aggregate_budget_and_duplicate_keys(store, monkeypatch):
    index = owner.DuckDBASTStore()
    rows = [index.put_projection(projection(name)) for name in ('first', 'other')]
    monkeypatch.setattr(owner, 'MAX_BATCH_PAYLOAD_BYTES',
        max(len(row.ast_blob.payload_json.encode()) for row in rows))
    with pytest.raises(owner.DuckDBASTBatchReadLimitError, match='split'):
        index.get_many_by_ast_cid([row.ast_cid for row in rows])
    with pytest.raises(owner.DuckDBASTBatchReadLimitError, match='split'):
        index.require_active_identities(rows)
    for row in rows:
        assert index.get_many_by_ast_cid([row.ast_cid] * 32) == (row,) * 32
        index.require_active_identities([row] * 32)


def test_single_projection_preserves_scalar_payload_limit_even_above_batch_threshold(store, monkeypatch):
    index, _ = store
    row = index.put_projection(projection())
    monkeypatch.setattr(owner, 'MAX_BATCH_PAYLOAD_BYTES', 1)
    assert index.get_many_by_ast_cid([row.ast_cid, row.ast_cid]) == (row, row)
    index.require_active_identities([row, row])
    monkeypatch.setattr(owner, 'MAX_STORED_PAYLOAD_BYTES', 1)
    with pytest.raises(owner.DuckDBASTStoreIntegrityError, match='byte bound'):
        index.get_many_by_ast_cid([row.ast_cid])


def test_nested_read_limit_exception_does_not_capture_failed_batch_frames(store, monkeypatch):
    index, _ = store
    rows = [projection('first'), projection('other')]
    index.apply_batch(rows)
    monkeypatch.setattr(owner, 'MAX_BATCH_PAYLOAD_BYTES', 1)
    with pytest.raises(owner.DuckDBASTBatchReadLimitError) as failure:
        index.get_many_by_ast_cid([row.ast_cid for row in rows])
    assert failure.value.__context__ is None


def test_scalar_row_bound_is_preserved_after_batch_fallback(store, monkeypatch):
    index, _ = store
    row = index.put_projection(projection())
    monkeypatch.setattr(owner, "MAX_QUERY_ROWS", 1)
    with pytest.raises(owner.DuckDBASTStoreError, match="query row bound"):
        index.get_many_by_ast_cid([row.ast_cid])
    with pytest.raises(owner.DuckDBASTStoreError, match="query row bound"):
        index.get_by_ast_cid(row.ast_cid)


def test_callback_cancellation_rolls_back_read_and_keeps_owner_usable(store):
    index, connection = store
    row = index.put_projection(projection())
    calls = []
    def cancel():
        calls.append(True)
        if len(calls) == 6:
            raise TimeoutError("caller observation deadline")
    connection.statements.clear()
    with pytest.raises(TimeoutError, match="observation deadline"):
        index.get_many_by_ast_cid([row.ast_cid], checkpoint=cancel)
    assert "ROLLBACK" in connection.statements
    assert index.get_by_ast_cid(row.ast_cid) == row
    assert not index._by_blob


def test_bounds_and_projection_type_reject_before_sql(store):
    index, connection = store
    connection.statements.clear()
    for keys in (["x"] * 33, "x", [None]):
        with pytest.raises((owner.DuckDBASTStoreError, TypeError, ValueError)):
            index.get_many_by_ast_cid(keys)
    with pytest.raises(owner.DuckDBASTStoreError):
        index.get_many_by_ast_cid([], checkpoint=7)
    with pytest.raises(owner.DuckDBASTStoreError):
        index.require_active_identities([None])
    assert not connection.statements


def test_nested_transaction_rejection_does_not_issue_callers_rollback(store):
    index, connection = store
    row = index.put_projection(projection())
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.statements.clear()
        with pytest.raises(Exception, match="transaction"):
            index.get_many_by_ast_cid([row.ast_cid])
        # DuckDB aborts a transaction on nested BEGIN. The caller still owns
        # its rollback; the store must not issue one for a transaction it did
        # not start, matching the original scalar transaction contract.
        assert "ROLLBACK" not in connection.statements
    finally:
        connection.execute("ROLLBACK")


def test_batch_snapshot_and_later_fence_detect_concurrent_owner_invalidation(tmp_path):
    import duckdb
    path = str(tmp_path / "shared.duckdb")
    with duckdb.connect(path, config={"threads": "1"}) as connection:
        first = owner.DuckDBASTStore(connection=connection)
        expected = first.put_projection(projection())
        with duckdb.connect(path, config={"threads": "1"}) as writer:
            second = owner.DuckDBASTStore(connection=writer)
            calls = []
            def concurrent_invalidation():
                calls.append(True)
                # First query fixes the read snapshot; before the next query
                # a separate owner commits a complete active invalidation.
                if len(calls) == 3:
                    second.invalidate(blob_id=expected.blob_id)
            captured = first.get_many_by_ast_cid([expected.ast_cid], checkpoint=concurrent_invalidation)
            assert captured == (expected,)
            with pytest.raises(owner.DuckDBASTStoreIntegrityError, match="no longer active"):
                first.require_active_identities(captured)
            assert first.get_many_by_ast_cid([expected.ast_cid]) == (None,)
