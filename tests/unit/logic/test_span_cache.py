"""Sealed span cache skips compiles and unseals dependents when terms change."""
from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.autoformal_span_cache import build_span_cache_package, flush_span_cache
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, terms_from_rule
from ipfs_datasets_py.logic.autoformal.supervisor_loop import recensus_open_todos


def _rule() -> dict:
    return {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"}


def _agreed(span_id: str = "s1") -> dict:
    return {
        "agrees": True,
        "decompiled": "Agency must make records available.",
        "id": span_id,
        "legal_id": "usc:us:5:552",
        "reason": "",
        "rule": _rule(),
        "skipped": False,
        "source_span_id": span_id,
        "text": "Each agency shall make records available.",
    }


def _gap(span_id: str = "g1") -> dict:
    return {
        "agrees": False,
        "id": span_id,
        "legal_id": "usc:us:18:1001",
        "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
        "skipped": False,
        "source_span_id": span_id,
        "text": "Whoever shall be imprisoned.",
    }


def test_sparse_progress_uploads_only_new_sealed_or_gap_rows(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.enqueue(
        [{"source_span_id": "pending", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"}]
    )
    cache.claim_batch("compile-a", limit=1)
    assert cache.sparse_progress_delta()["delta_count"] == 0
    cache.apply_census(
        {"rows": [_agreed("s1"), _gap("g1")]},
        code_identity="sha256:test",
    )
    delta = cache.sparse_progress_delta()
    assert delta["delta_count"] == 2
    assert {row["source_span_id"] for row in delta["rows"]} == {"s1", "g1"}
    assert all("claim_token" not in row for row in delta["rows"])
    path = tmp_path / "compile-a-sparse.parquet"
    written = cache.write_sparse_progress_parquet(
        path, delta["rows"], agent_id="compile-a", update_id="sparse-1"
    )
    assert written["jsonl_written"] is False
    assert written["admitted"] is False
    cache.mark_progress_published(delta["fingerprints"])
    assert cache.sparse_progress_delta()["delta_count"] == 0
    with pytest.raises(Exception, match="full resume checkpoint"):
        cache.write_sparse_progress_parquet(
            tmp_path / "resume-checkpoint.parquet",
            delta["rows"],
            agent_id="compile-a",
            update_id="sparse-1",
        )
    cache.close()


def test_sparse_observation_history_survives_4000_shards_and_restart(tmp_path):
    import json

    database = tmp_path / "cache.duckdb"
    cache = SpanCache(database)
    legacy = [f"autoformal/uscode/checkpoints/agent/sparse-{i:05}.parquet" for i in range(4000)]
    # Simulate the persisted pre-migration catalog, then open it with the new schema.
    cache._set_meta("applied_sparse_checkpoints", json.dumps(legacy))
    cache._set_meta("sparse_checkpoint_paths_migrated", "0")
    cache.close()
    cache = SpanCache(database)
    next_path = "autoformal/uscode/checkpoints/agent/sparse-04000.parquet"
    cache.remember_sparse_checkpoint(next_path)
    cache.remember_sparse_checkpoint(next_path)
    cache.close()
    cache = SpanCache(database)
    try:
        unseen = [f"later-{i}" for i in range(32)]
        assert len(cache.applied_sparse_checkpoints()) == 4001
        assert cache.unapplied_sparse_checkpoints([*legacy, next_path, *unseen], limit=16) == unseen[:16]
        assert cache.unapplied_sparse_checkpoints([unseen[0], unseen[0]], limit=16) == unseen[:1]
    finally:
        cache.close()


def test_sparse_status_file_retry_is_immutable_across_enqueue_ticks(tmp_path):
    cache = SpanCache(tmp_path / "cache.duckdb")
    try:
        cache.apply_census({"rows": [_gap()]}, code_identity="test-code")
        rows = cache.sparse_progress_delta()["rows"]
        path = tmp_path / "sparse.parquet"
        cache.write_sparse_progress_parquet(path, rows, agent_id="machine", update_id="stable")
        before = path.read_bytes()
        inode = path.stat().st_ino
        cache.save_checkpoint(documents=1000, parquet="laws.parquet")
        cache.write_sparse_progress_parquet(path, rows, agent_id="machine", update_id="stable")
        assert path.read_bytes() == before and path.stat().st_ino == inode
        changed = [{**rows[0], "reason": "different observation"}]
        with pytest.raises(Exception, match="immutable sparse checkpoint conflicts"):
            cache.write_sparse_progress_parquet(path, changed, agent_id="machine", update_id="stable")
        assert path.read_bytes() == before and path.stat().st_ino == inode
        assert not list(tmp_path.glob(".sparse-progress-*"))
    finally:
        cache.close()


def test_sparse_history_migration_rolls_back_partial_insert_and_retries(tmp_path, monkeypatch):
    import duckdb
    import json

    path = tmp_path / "cache.duckdb"
    cache = SpanCache(path)
    cache._set_meta("applied_sparse_checkpoints", json.dumps(["one.parquet", "two.parquet"]))
    cache._set_meta("sparse_checkpoint_paths_migrated", "0")
    cache.close()
    connection = duckdb.connect(str(path))

    class InterruptedMigration:
        def __getattr__(self, name):
            return getattr(connection, name)

        def executemany(self, statement, values):
            assert "applied_sparse_checkpoint" in statement
            connection.execute(statement, values[0])
            raise OSError("migration interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(duckdb, "connect", lambda *args, **kwargs: InterruptedMigration())
        with pytest.raises(OSError, match="migration interrupted"):
            SpanCache(path)
    try:
        assert connection.execute("SELECT count(*) FROM applied_sparse_checkpoint").fetchone()[0] == 0
        assert connection.execute("SELECT value FROM cache_meta WHERE key='sparse_checkpoint_paths_migrated'").fetchone()[0] == "0"
    finally:
        connection.close()
    cache = SpanCache(path)
    try:
        assert cache.applied_sparse_checkpoints() == ["one.parquet", "two.parquet"]
        assert cache._meta("sparse_checkpoint_paths_migrated") == "1"
    finally:
        cache.close()


def test_sparse_quarantine_is_bound_to_expected_dataset_and_never_means_applied(tmp_path):
    cache = SpanCache(tmp_path / "cache.duckdb")
    try:
        cache.register_agent("reader", dataset_id="dataset-a")
        cache.quarantine_sparse_checkpoint("foreign.parquet", expected_dataset_id="dataset-a",
                                           reason="dataset_mismatch", evidence={"content_sha256": "abc"})
        assert cache.applied_sparse_checkpoints() == []
        assert cache.unapplied_sparse_checkpoints(["foreign.parquet"]) == []
        assert cache.quarantined_sparse_checkpoint_count() == 1
        cache.register_agent("reader", dataset_id="dataset-b")
        assert cache.unapplied_sparse_checkpoints(["foreign.parquet"]) == ["foreign.parquet"]
        assert cache.quarantined_sparse_checkpoint_count() == 0
        assert cache.applied_sparse_checkpoints() == []
    finally:
        cache.close()


def test_resume_parquet_carries_board_seals_and_agent(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.save_checkpoint(documents=12, parquet="/data/laws.parquet")
    cache.register_agent("agent-a", dataset_id="justicedao/ipfs_uscode", role="compile")
    cache.enqueue(
        [
            {"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
            {"source_span_id": "s2", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
        ]
    )
    cache.claim_batch("agent-a", limit=1)
    cache.apply_census(
        {"rows": [_agreed("s1")]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
        code_identity="sha256:test",
    )
    path = tmp_path / "resume-checkpoint.parquet"
    written = cache.write_resume_parquet(path)
    assert path.suffix == ".parquet"
    assert written["jsonl_written"] is False
    assert not (tmp_path / "resume-checkpoint.json").exists()
    summary = cache.resume_summary(path)
    assert summary["documents"] == 12
    assert summary["kinds"].get("meta") == 1
    assert summary["kinds"].get("agent") == 1
    assert summary["kinds"].get("board", 0) >= 1
    assert summary["kinds"].get("seal", 0) >= 1
    assert summary["kinds"].get("span") == 2
    assert summary["admitted"] is False
    other = SpanCache(tmp_path / "other.duckdb")
    other.register_agent("agent-b", dataset_id="justicedao/ipfs_uscode", role="compile")
    other.enqueue(
        [{"source_span_id": "s9", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"}]
    )
    assert other.claim_batch("agent-b", limit=5)[0]["source_span_id"] == "s9"
    assert other.release_stale_claims("agent-a") == 0
    assert other.release_stale_claims("agent-b") == 1
    other.close()
    cache.close()


def test_remote_checkpoint_is_advisory_without_unsealing_local(tmp_path: Path) -> None:
    writer = SpanCache(tmp_path / "writer.duckdb")
    writer.register_agent("agent-b", dataset_id="justicedao/ipfs_uscode")
    writer.enqueue(
        [
            {"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
            {"source_span_id": "s2", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
        ]
    )
    writer.apply_census(
        {"rows": [_agreed("s1"), _gap("s2")]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
        code_identity="sha256:remote",
    )
    remote = tmp_path / "remote.parquet"
    writer.write_resume_parquet(remote)
    reader = SpanCache(tmp_path / "reader.duckdb")
    reader.register_agent("control-plane", dataset_id="justicedao/ipfs_uscode")
    reader.enqueue(
        [
            {"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
            {"source_span_id": "s2", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
            {"source_span_id": "s3", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"},
        ]
    )
    reader.apply_census(
        {"rows": [_agreed("s3")]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
        code_identity="sha256:local",
    )
    before = _local_tables(reader)
    merged = reader.upsert_remote_resume(remote, agent_id="control-plane")
    assert merged["sealed"] == merged["gaps"] == merged["claimed"] == 0
    assert merged["advisory_only"] is True
    assert merged["source_matched_status_counts"] == {"gap": 1, "sealed": 1}
    assert merged["admitted"] is False
    assert merged["formalized"] is False
    assert _local_tables(reader) == before
    pending = {item["source_span_id"] for item in reader.pending(limit=10)}
    assert pending == {"s1", "s2"}
    assert reader.skip_compile("s1") is None
    assert reader.stats()["sealed"] == 1
    calls = []
    reader.process_pending(lambda text: calls.append(text) or {"compiler_status": "abstain"})
    assert len(calls) == 2
    writer.close()
    reader.close()


def _local_tables(cache, *, include_agents=False):
    tables = ["span_cache", "sealed_terms", "span_terms", "compiler_snapshot",
              "cache_meta", "lean_statutes", "lean_terms", "task_board"]
    if include_agents:
        tables.append("agent_lease")
    return {table: cache._db.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
            for table in tables}


@pytest.fixture
def remote_resume(tmp_path):
    writer = SpanCache(tmp_path / "remote.duckdb")
    reader = SpanCache(tmp_path / "local.duckdb")
    dataset = "justicedao/ipfs_uscode"
    writer.register_agent("remote-a", dataset_id=dataset)
    writer.register_agent("remote-b", dataset_id=dataset)
    reader.register_agent("control-plane", dataset_id=dataset)
    spans = [_agreed("s1"), _agreed("s2"), _gap("g1"), _agreed("c1")]
    writer.enqueue(spans)
    reader.enqueue(spans)
    writer.apply_census({"rows": spans[:3]}, code_identity="sha256:foreign-compiler")
    assert writer.claim_batch("remote-a", limit=1)[0]["source_span_id"] == "c1"
    reader._db.execute("UPDATE span_cache SET status = 'claimed', claim_worker = 'local-worker', "
                       "claim_token = 'local-token' WHERE source_span_id = 's2'")
    reader.refresh_task_board()
    path = tmp_path / "remote.parquet"
    writer.write_resume_parquet(path)
    try:
        yield writer, reader, path
    finally:
        writer.close()
        reader.close()


def _rewrite_resume(path, destination, transform):
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pq.read_table(path)
    rows = transform(table.to_pylist())
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), destination)
    return destination


def test_remote_shared_terms_multiple_agents_and_claims_remain_advisory(remote_resume):
    writer, reader, path = remote_resume
    # A normal checkpoint repeats each shared term for both agreeing spans.
    assert writer._db.execute("SELECT count(*) FROM span_terms").fetchone()[0] > writer._db.execute(
        "SELECT count(*) FROM sealed_terms").fetchone()[0]
    before = _local_tables(reader)
    result = reader.upsert_remote_resume(path, agent_id="control-plane")
    assert result["source_matched_status_counts"] == {"claimed": 1, "gap": 1, "sealed": 2}
    assert result["sealed"] == result["gaps"] == result["claimed"] == 0
    assert result["agents_imported"] == 2
    assert _local_tables(reader) == before
    assert reader.skip_compile("s1") is None
    assert {row[0] for row in reader._db.execute("SELECT agent_id FROM agent_lease").fetchall()} == {
        "control-plane", "remote-a", "remote-b"}
    assert reader._db.execute("SELECT count(*) FROM agent_lease WHERE admitted OR formalized").fetchone()[0] == 0
    after = _local_tables(reader, include_agents=True)
    repeated = reader.upsert_remote_resume(path, agent_id="control-plane")
    assert repeated == {**result, "agents_imported": 0}
    assert _local_tables(reader, include_agents=True) == after


@pytest.mark.parametrize("source_hash", ["", None, "0" * 64])
def test_remote_missing_or_foreign_source_hash_is_not_an_observation(remote_resume, tmp_path, source_hash):
    _, reader, path = remote_resume
    def alter(rows):
        return [{**row, "source_sha256": source_hash} if row["record_kind"] == "span" else row
                for row in rows]
    changed = _rewrite_resume(path, tmp_path / "changed.parquet", alter)
    before = _local_tables(reader)
    result = reader.upsert_remote_resume(changed, agent_id="control-plane")
    assert result["source_matched_status_counts"] == {}
    assert _local_tables(reader) == before


@pytest.mark.parametrize("metadata", ["foreign", "missing", "duplicate"])
def test_remote_dataset_must_match_one_local_dataset_record(remote_resume, tmp_path, metadata):
    _, reader, path = remote_resume
    def alter(rows):
        if metadata == "missing":
            return [row for row in rows if row["record_kind"] != "meta"]
        if metadata == "duplicate":
            return rows + [next(row for row in rows if row["record_kind"] == "meta")]
        return [{**row, "dataset_id": "other-dataset"} if row["record_kind"] == "meta" else row
                for row in rows]
    changed = _rewrite_resume(path, tmp_path / "changed.parquet", alter)
    before = _local_tables(reader, include_agents=True)
    result = reader.upsert_remote_resume(changed, agent_id="control-plane")
    assert result["dataset_matched"] is False
    assert result["source_matched_status_counts"] == {} and result["agents_imported"] == 0
    assert _local_tables(reader, include_agents=True) == before


def test_remote_agent_rows_are_distinct_compatible_and_preserve_existing(remote_resume, tmp_path):
    _, reader, path = remote_resume
    def alter(rows):
        agent = next(row for row in rows if row["record_kind"] == "agent")
        return rows + [agent, {**agent, "agent_id": "foreign", "dataset_id": "other"},
                       {**agent, "agent_id": "control-plane", "heartbeat": "different"}]
    changed = _rewrite_resume(path, tmp_path / "changed.parquet", alter)
    local_agent = reader._db.execute("SELECT * FROM agent_lease WHERE agent_id = 'control-plane'").fetchone()
    result = reader.upsert_remote_resume(changed, agent_id="control-plane")
    assert result["agents_imported"] == 2
    assert reader._db.execute("SELECT * FROM agent_lease WHERE agent_id = 'control-plane'").fetchone() == local_agent
    assert reader._db.execute("SELECT count(*) FROM agent_lease WHERE agent_id = 'foreign'").fetchone()[0] == 0


def test_conflicting_new_remote_agents_roll_back(remote_resume, tmp_path):
    _, reader, path = remote_resume
    def alter(rows):
        agent = next(row for row in rows if row["record_kind"] == "agent")
        return rows + [{**agent, "heartbeat": "conflicting"}]
    changed = _rewrite_resume(path, tmp_path / "changed.parquet", alter)
    before = _local_tables(reader, include_agents=True)
    with pytest.raises(Exception, match="conflicting remote agent"):
        reader.upsert_remote_resume(changed, agent_id="control-plane")
    assert _local_tables(reader, include_agents=True) == before
    assert reader.upsert_remote_resume(path, agent_id="control-plane")["agents_imported"] == 2


def test_remote_import_rolls_back_when_later_statement_fails(remote_resume):
    _, reader, path = remote_resume
    before = _local_tables(reader, include_agents=True)
    real = reader._db
    class FailAfterInsert:
        def execute(self, sql, *args):
            if sql == "DROP TABLE remote_resume_agents":
                assert real.execute("SELECT count(*) FROM agent_lease").fetchone()[0] == 3
                raise RuntimeError("injected failure after agent insertion")
            return real.execute(sql, *args)
    reader._db = FailAfterInsert()
    try:
        with pytest.raises(RuntimeError, match="after agent insertion"):
            reader.upsert_remote_resume(path, agent_id="control-plane")
    finally:
        reader._db = real
    assert _local_tables(reader, include_agents=True) == before
    assert reader.upsert_remote_resume(path, agent_id="control-plane")["agents_imported"] == 2


@pytest.mark.parametrize("raw_rule", ["", "not-json", "[]"])
def test_incomplete_old_imported_compile_payload_is_requeued_on_access(tmp_path, raw_rule):
    cache = SpanCache(tmp_path / "cache.duckdb")
    try:
        cache.enqueue([_agreed()])
        cache._db.execute("UPDATE span_cache SET status = 'sealed', sealed = TRUE, rule_json = ?", [raw_rule])
        assert cache.skip_compile("s1") is None
        row = cache._db.execute("SELECT status, sealed, rule_json, reason, admitted, formalized FROM span_cache").fetchone()
        assert row == ("unsealed", False, raw_rule, "incomplete_compile_cache", False, False)
        assert cache.pending()[0]["source_span_id"] == "s1"
    finally:
        cache.close()


def test_valid_empty_local_compile_payload_preserves_existing_cache_contract(tmp_path):
    cache = SpanCache(tmp_path / "cache.duckdb")
    try:
        cache.apply_census({"rows": [{**_agreed(), "rule": {}}]})
        before = _local_tables(cache)
        cached = cache.skip_compile("s1")
        assert cached["rule"] == {} and cached["agrees"] is True
        assert cached["admitted"] is False and cached["formalized"] is False
        assert _local_tables(cache) == before
    finally:
        cache.close()


def test_checkpoint_resumes_after_the_last_committed_document(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.save_checkpoint(documents=4608, parquet="/data/laws.parquet")
    point = cache.checkpoint()
    assert point["documents"] == 4608
    assert point["parquet"] == "/data/laws.parquet"
    assert point["admitted"] is False
    cache.enqueue(
        [{"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"}]
    )
    claimed = cache.claim_batch("control-plane", limit=1)
    assert claimed[0]["source_span_id"] == "s1"
    assert cache.release_stale_claims() == 1
    assert cache.pending(limit=5)[0]["source_span_id"] == "s1"
    cache.close()


def test_claim_batch_is_exclusive_until_completed(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.enqueue(
        [
            {"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
            {"source_span_id": "s2", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
        ]
    )
    first = cache.claim_batch("control-plane", limit=10)
    assert {item["source_span_id"] for item in first} == {"s1", "s2"}
    assert cache.claim_batch("control-plane", limit=10) == []
    done = cache.complete_claimed(
        [
            {
                "agrees": True,
                "decompiled": "Agency must make records available.",
                "legal_id": "usc:us:5:552",
                "rule": {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"},
                "source_span_id": "s1",
                "text": "Each agency shall make records available.",
            },
            {
                "agrees": False,
                "decompiled": "",
                "legal_id": "usc:us:18:1001",
                "reason": "no_parser_elements",
                "source_span_id": "s2",
                "text": "Whoever shall be imprisoned.",
            },
        ],
        code_identity="sha256:test",
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    assert done["sealed"] == 1
    assert done["gaps"] == 1
    assert done["admitted"] is False
    assert cache.skip_compile("s1", source_text="Each agency shall make records available.") is not None
    cache.close()


def test_terms_from_rule_name_actor_action_object() -> None:
    terms = terms_from_rule(_rule(), decompiled="Agency must make records available.")
    kinds = {item["kind"] for item in terms}
    assert {"modality", "actor", "action", "object", "decompiled"} <= kinds


def test_seal_skips_compile_and_unseals_when_parser_hash_changes(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    parser = "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    hashes = {parser: "aaa"}
    first = cache.apply_census({"rows": [_agreed(), _gap()]}, path_hashes=hashes)
    assert first["sealed"] == 1
    assert first["gaps"] == 1
    assert first["admitted"] is False
    cached = cache.skip_compile("s1", source_text="Each agency shall make records available.")
    assert cached is not None
    assert cached["skipped_compile"] is True
    assert cached["agrees"] is True
    changed = cache.unseal_changed({parser: "bbb"})
    assert changed["unsealed"] == 1
    assert "s1" in changed["unsealed_ids"]
    assert cache.skip_compile("s1", source_text="Each agency shall make records available.") is None
    cache.close()


def test_process_pending_skips_sealed_and_compiles_unsealed(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    parser = "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    cache.apply_census({"rows": [_agreed("s1")]}, path_hashes={parser: "aaa"})
    cache.enqueue([{"source_span_id": "s2", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"}])
    calls = []

    def compile_one(text: str):
        calls.append(text)
        return {
            "compiler_status": "compiled",
            "decompiled": "Clerk must keep a journal.",
            "reason": "",
            "rule": {"modality": "obligation", "actor": "Clerk", "action": "keep", "object": "journal"},
        }

    receipt = cache.process_pending(compile_one, path_hashes={parser: "aaa"})
    assert receipt["processed"] == 1
    assert len(calls) == 1
    assert cache.stats()["sealed"] == 2
    cache.close()


def test_loop_uses_sealed_cache_on_recensus(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.apply_census(
        {"rows": [_agreed()]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    compile_calls = {"n": 0}

    def compile_one(text: str):
        compile_calls["n"] += 1
        return {"compiler_status": "abstain", "reason": "penalty", "decompiled": ""}

    prior = {
        "population": {
            "tasks": [
                {
                    "source_span_id": "s1",
                    "source_text": "Each agency shall make records available.",
                    "legal_id": "usc:us:5:552",
                },
                {
                    "source_span_id": "g1",
                    "source_text": "Whoever shall be imprisoned.",
                    "legal_id": "usc:us:18:1001",
                },
            ]
        }
    }
    tick = recensus_open_todos(prior, compile_one, span_cache=cache)
    assert compile_calls["n"] == 1
    by_id = {row["source_span_id"]: row for row in tick["agreement"]["rows"]}
    assert by_id["s1"]["agrees"] is True
    assert by_id["s1"].get("skipped_compile") is True
    assert by_id["g1"]["agrees"] is False
    cache.close()


def test_supervisor_loop_emits_cache_progress(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import run_supervisor_loop

    cache = SpanCache(tmp_path / "cache.duckdb")
    lines: list[str] = []
    receipt = run_supervisor_loop(
        lambda: {"rows": [_agreed(), _gap()]},
        ingest=lambda *a, **k: {"task_count": 1},
        max_rounds=1,
        board_path=tmp_path / "loop.todo.md",
        log=lines.append,
        span_cache=cache,
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
        code_identity="sha256:test",
    )
    joined = "\n".join(lines)
    assert "CACHE round=1" in joined
    assert "STATUTE legal_id=" in joined
    assert "TERM kind=" in joined
    assert receipt["span_cache"]["sealed_total"] == 1
    assert receipt["admitted"] is False
    cache.close()


def test_flush_writes_parquet_not_jsonl(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.apply_census(
        {"rows": [_agreed()]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    package = build_span_cache_package(cache.sealed_rows(), tmp_path / "pkg")
    assert package["jsonl_written"] is False
    assert package["row_count"] == 1
    assert (tmp_path / "pkg" / "sealed-spans.parquet").is_file()
    assert not list((tmp_path / "pkg").glob("*.jsonl"))
    flushed = flush_span_cache(cache.sealed_rows(), tmp_path / "pkg2", dry_run=True)
    assert flushed["dry_run"] is True
    assert flushed["uploaded"] is False
    assert flushed["remote_write_contacted"] is False
    cache.close()
