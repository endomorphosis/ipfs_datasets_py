"""Corpus enqueue budgets use a fake executor, without workers or data access."""

from __future__ import annotations

import importlib
import importlib.util
import hashlib
from pathlib import Path

import pytest


def test_sparse_flush_skips_claims_and_does_not_upload_the_full_checkpoint(
    tmp_path, monkeypatch
):
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "uscode_sparse_checkpoint_under_test", script
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.enqueue(
        [
            {
                "source_span_id": "pending",
                "text": "The clerk shall keep a journal.",
                "legal_id": "usc:us:1:1",
            }
        ]
    )
    cache.claim_batch("compile-a", limit=1)
    calls = []

    class Api:
        def create_repo(self, *args, **kwargs):
            calls.append("create")

        def upload_file(self, **kwargs):
            calls.append(kwargs["path_in_repo"])

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: Api())
    skipped = module._flush_checkpoint(
        cache, tmp_path / "out", upload=True, agent_id="compile-a"
    )
    assert skipped["uploaded"] is False
    assert skipped["skipped"] == "no_durable_change"
    assert skipped["full_checkpoint_uploaded"] is False
    assert calls == []
    cache.apply_census(
        {
            "rows": [
                {
                    "agrees": True,
                    "decompiled": "Agency must make records available.",
                    "legal_id": "usc:us:5:552",
                    "source_span_id": "s1",
                    "text": "Each agency shall make records available.",
                }
            ]
        },
        code_identity="sha256:test",
    )
    uploaded = module._flush_checkpoint(
        cache, tmp_path / "out", upload=True, agent_id="compile-a"
    )
    assert uploaded["uploaded"] is True
    assert uploaded["delta_count"] == 1
    assert uploaded["full_checkpoint_uploaded"] is False
    assert calls[1].startswith("autoformal/uscode/checkpoints/compile-a/sparse-")
    assert "resume-checkpoint.parquet" not in calls[1]
    again = module._flush_checkpoint(
        cache, tmp_path / "out", upload=True, agent_id="compile-a"
    )
    assert again["skipped"] == "no_durable_change"
    assert len(calls) == 2
    cache.close()


def test_poll_reads_other_machines_deltas_once(tmp_path, monkeypatch):
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "uscode_sparse_poll_under_test", script
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    writer = SpanCache(tmp_path / "writer.duckdb")
    writer._set_meta("dataset_id", "justicedao/ipfs_uscode")
    writer.apply_census(
        {
            "rows": [
                {
                    "agrees": False,
                    "legal_id": "usc:us:18:1001",
                    "reason": "compiler_abstain:penalty",
                    "source_span_id": "g1",
                    "text": "Whoever shall be imprisoned.",
                }
            ]
        },
        code_identity="sha256:test",
    )
    delta = writer.sparse_progress_delta()
    remote = tmp_path / "remote.parquet"
    writer.write_sparse_progress_parquet(
        remote, delta["rows"], agent_id="compile-b", update_id="sparse-b"
    )
    reader = SpanCache(tmp_path / "reader.duckdb")
    reader._set_meta("dataset_id", "justicedao/ipfs_uscode")
    reader.register_agent("compile-a", dataset_id="justicedao/ipfs_uscode")
    downloaded = []

    class Api:
        def list_repo_files(self, repo_id, repo_type):
            assert repo_id == "justicedao/uscode-autoformal-span-cache"
            return [
                "autoformal/uscode/resume-checkpoint.parquet",
                "autoformal/uscode/checkpoints/compile-a/sparse-own.parquet",
                "autoformal/uscode/checkpoints/compile-b/sparse-b.parquet",
            ]

    def download(repo_id, filename, repo_type):
        downloaded.append(filename)
        return str(remote)

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: Api())
    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    first = module._poll_remote_checkpoint(reader, agent_id="compile-a")
    assert first["changed"] is True
    assert first["full_checkpoint_downloaded"] is False
    assert downloaded == ["autoformal/uscode/checkpoints/compile-b/sparse-b.parquet"]
    second = module._poll_remote_checkpoint(reader, agent_id="compile-a")
    assert second["changed"] is False
    assert downloaded == ["autoformal/uscode/checkpoints/compile-b/sparse-b.parquet"]
    writer.close()
    reader.close()


def test_enqueue_pool_capacity_respects_worker_budget_and_preserves_resume(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "uscode_enqueue_budget_under_test", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    budget_module = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.worker_budget"
    )
    budgets = iter((2, 1, 8, 2))
    monkeypatch.setattr(budget_module, "worker_budget", lambda: next(budgets))
    monkeypatch.setattr(module.os, "cpu_count", lambda: 128)
    parquet = tmp_path / "not-opened.parquet"
    chunks: list[int] = []
    capacities: list[int] = []
    shutdowns: list[tuple[bool, bool]] = []
    checkpoints: list[dict] = []
    enqueued: list[dict] = []
    flushed: list[tuple[Path, bool]] = []

    class FakeExecutor:
        def __init__(self, *, max_workers):
            capacities.append(max_workers)

        def map(self, function, rows, *, chunksize):
            rows = list(rows)
            assert chunksize == 1
            chunks.append(len(rows))
            return [function(row) for row in rows]

        def shutdown(self, *, wait, cancel_futures):
            shutdowns.append((wait, cancel_futures))

    class FakeCache:
        def checkpoint(self):
            return {"documents": 448, "parquet": str(parquet.resolve())}

        def enqueue(self, rows):
            enqueued.extend(rows)
            return len(rows)

        def save_checkpoint(self, **values):
            checkpoints.append(values)

        def stats(self):
            return {"pending": len(enqueued)}

    def documents(path, *, limit, skip):
        assert path == parquet and limit == 130 and skip == 448
        return [{"entry_cid": f"document-{number}"} for number in range(130)]

    def parse_document(document):
        assert document["release_id"] == "test-release"
        return [{"source_span_id": document["entry_cid"]}]

    def flush_checkpoint(cache, destination, *, upload, agent_id):
        assert isinstance(cache, FakeCache)
        assert agent_id.startswith("compile-")
        flushed.append((destination, upload))
        return {"uploaded": False}

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(module, "_documents", documents)
    monkeypatch.setattr(module, "_parse_document", parse_document)
    monkeypatch.setattr(module, "_flush_checkpoint", flush_checkpoint)
    monkeypatch.setattr(
        module, "_poll_remote_checkpoint", lambda *args, **kwargs: {"changed": False}
    )
    result = module.enqueue_corpus(
        FakeCache(),
        parquet,
        limit=130,
        release_id="test-release",
        resume=True,
        upload=False,
        upload_dir=tmp_path / "not-written",
    )
    assert capacities == [2]
    assert chunks == [1] * 64 + [2] * 33
    assert shutdowns == [(True, False)]
    assert enqueued == [
        {"source_span_id": f"document-{number}"} for number in range(130)
    ]
    assert checkpoints == [
        {"documents": count, "parquet": str(parquet.resolve())}
        for count in (512, 576, 578)
    ]
    assert flushed == [(tmp_path / "not-written", False)]
    assert result == {
        "admitted": False,
        "documents": 578,
        "formalized": False,
        "resumed_from": 448,
        "spans_enqueued": 130,
    }
    output = capsys.readouterr().out
    assert "parse_workers=2 parse_task_budget=1" in output
    assert "parse_workers=2 parse_task_budget=2" in output
    assert not list(tmp_path.iterdir())


def _ingest_module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "uscode_exchange_ingest_under_test", script
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkpoint_identity_is_unique_per_cache_and_stable_after_reopen(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    monkeypatch.setattr("socket.gethostname", lambda: "same-machine.local")
    first = SpanCache(tmp_path / "a.duckdb")
    second = SpanCache(tmp_path / "b.duckdb")
    try:
        first._set_meta("agent_id", "compile-same-machine")
        # A crash can retain the new UUID before the old hostname-only ID is replaced.
        first._set_meta("checkpoint_instance_uuid", "a" * 32)
        first_id = module._checkpoint_agent_id(first)
        second_id = module._checkpoint_agent_id(second)
        assert first_id != second_id and len(first_id) <= 48 and len(second_id) <= 48
        assert first_id.endswith("-" + "a" * 32)
        assert first._meta("legacy_checkpoint_agent_id") == "compile-same-machine"
    finally:
        first.close()
        second.close()
    first = SpanCache(tmp_path / "a.duckdb")
    try:
        assert module._checkpoint_agent_id(first) == first_id
    finally:
        first.close()


def test_sparse_upload_failure_retries_identical_retained_file_after_enqueue_advances(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.apply_census(
        {
            "rows": [
                {
                    "source_span_id": "gap",
                    "text": "A source sentence.",
                    "agrees": False,
                    "reason": "abstained",
                }
            ]
        }
    )
    uploads = []

    class Api:
        def create_repo(self, *args, **kwargs):
            pass

        def upload_file(self, **kwargs):
            path = Path(kwargs["path_or_fileobj"])
            uploads.append(
                (kwargs["path_in_repo"], path.read_bytes(), path.stat().st_ino)
            )
            if len(uploads) == 1:
                raise ConnectionError("retryable test failure")

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: Api())
    try:
        first = module._flush_checkpoint(
            cache, tmp_path / "out", upload=True, agent_id="test-machine"
        )
        assert first["uploaded"] is False and first["error"] == "ConnectionError"
        assert cache.published_progress_fingerprints() == {}
        cache.save_checkpoint(documents=999, parquet="laws.parquet")
        second = module._flush_checkpoint(
            cache, tmp_path / "out", upload=True, agent_id="test-machine"
        )
        assert second["uploaded"] is True
        assert first["update_id"] == second["update_id"]
        assert uploads[0] == uploads[1]
        assert cache.sparse_progress_delta()["rows"] == []
    finally:
        cache.close()


@pytest.mark.parametrize("foreign_count", [1, 17])
def test_fresh_checkpoint_poll_matches_dataset_and_foreign_shards_are_not_consumed(
    tmp_path, monkeypatch, foreign_count
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    writer = SpanCache(tmp_path / "writer.duckdb")
    reader = SpanCache(tmp_path / "reader.duckdb")
    source = {"source_span_id": "span-1", "text": "An unsupported source sentence."}
    writer.apply_census({"rows": [{**source, "agrees": False, "reason": "abstained"}]})
    reader.enqueue([source])
    pending_before = reader.pending()
    delta = writer.sparse_progress_delta()
    own = "autoformal/uscode/checkpoints/reader/own.parquet"
    foreign_paths = [
        f"autoformal/uscode/checkpoints/other/foreign-{i}.parquet"
        for i in range(foreign_count)
    ]
    matched_path = "autoformal/uscode/checkpoints/other/matched.parquet"
    foreign = tmp_path / "foreign.parquet"
    matched = tmp_path / "matched.parquet"
    writer.register_agent("writer", dataset_id="another-dataset")
    writer.write_sparse_progress_parquet(
        foreign, delta["rows"], agent_id="writer", update_id="foreign"
    )
    writer.register_agent("writer", dataset_id="justicedao/ipfs_uscode")
    writer.write_sparse_progress_parquet(
        matched, delta["rows"], agent_id="writer", update_id="matched"
    )

    class Api:
        def list_repo_files(self, *args, **kwargs):
            return [own, *foreign_paths, matched_path]

    downloaded = []

    def download(repo_id, filename, repo_type):
        downloaded.append(filename)
        return str(foreign if filename in foreign_paths else matched)

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: Api())
    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    try:
        result = module._poll_remote_checkpoint(reader, agent_id="reader")
        assert reader._meta("dataset_id") == "justicedao/ipfs_uscode"
        assert result["advisory_only"] is True
        observations = {row["path_in_repo"]: row for row in result["observations"]}
        if foreign_count > 16:
            assert result["delta_count"] == 0 and result["dataset_mismatch_count"] == 16
            # A completed first polling window must not starve the compatible shard.
            reader.close()
            reader = SpanCache(tmp_path / "reader.duckdb")
            result = module._poll_remote_checkpoint(reader, agent_id="reader")
            observations.update(
                {row["path_in_repo"]: row for row in result["observations"]}
            )
        assert result["delta_count"] == 1 and result["dataset_mismatch_count"] == 1
        assert observations[matched_path]["source_matched_status_counts"] == {"gap": 1}
        assert observations[foreign_paths[0]]["dataset_matched"] is False
        assert reader.applied_sparse_checkpoints() == [matched_path]
        assert reader.quarantined_sparse_checkpoint_count() == foreign_count
        assert reader.pending() == pending_before
        assert reader.stats()["sealed"] == reader.stats()["gaps"] == 0
        again = module._poll_remote_checkpoint(reader, agent_id="reader")
        assert again["changed"] is False and again["delta_count"] == 0
        assert downloaded == [*foreign_paths, matched_path]
    finally:
        writer.close()
        reader.close()


@pytest.mark.parametrize("decoded", ["A long decoded clause. " * 80, ""])
def test_compile_worker_preserves_complete_observations_and_input_identity(
    monkeypatch, decoded
):
    module = _ingest_module()
    autoformal = importlib.import_module("ipfs_datasets_py.logic.autoformal")
    reports = importlib.import_module("ipfs_datasets_py.logic.autoformal.repair_report")
    source = "A source sentence distinct from the decoded clause. " * 50
    capture = {
        "decoded_text": decoded,
        "codec_observation": {
            "modal_ir": {"formulas": list(range(12))},
            "full_decoded_text": decoded,
            "raw_losses": {"real_metric": 0.25},
        },
        "cosine_similarity": None,
        "formulas": [],
    }
    compiler = {
        "compiler_status": "abstained",
        "reason": "unsupported_semantics",
        "decompiled": "",
        "diagnostic_details": {"complete": "x" * 900},
    }
    calls = []

    def capture_one(text, *, include_full_evidence):
        assert text == source and include_full_evidence is True
        return capture

    def compile_one(session, text, span_id):
        calls.append((text, span_id))
        return compiler

    monkeypatch.setattr(autoformal, "AutoformalSession", lambda: object())
    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    monkeypatch.setattr(reports, "codec_capture", capture_one)
    monkeypatch.setattr(reports, "repair_report", lambda **kwargs: {"admitted": False})
    item = {
        "text": source,
        "source_span_id": "span-1",
        "legal_id": "usc:us:5:552",
        "release_id": "release-test",
        "entry_cid": "source-cid",
    }
    result = module._compile_claimed(item)
    assert result["autoencoder_capture"] == capture
    assert result["compiler_result"] == compiler
    assert result["autoencoder_text"] == decoded
    assert calls == [(decoded or source, "span-1")]
    assert result["compiler_input"] == (decoded or source)
    assert result["compiler_input_mode"] == (
        "decoded" if decoded else "source_fallback"
    )
    assert result["source_text_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert result["source_provenance"] == {
        "entry_cid": "source-cid",
        "release_id": "release-test",
    }
    assert result["learned_autoencoder_execution"] is False
    assert result["model_identity"] == "deterministic-modal-codec:no-learned-checkpoint"
    assert result["cosine_similarity"] is None
    assert result["agrees"] is False


def _isolate_drain(monkeypatch, module, events):
    agreement = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.span_agreement"
    )
    weights = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.autoencoder_weight_store"
    )

    class Executor:
        def __init__(self, *, max_workers, initializer):
            assert max_workers == 1

        def map(self, function, rows, *, chunksize):
            return [function(row) for row in rows]

        def shutdown(self, *, wait, cancel_futures):
            events.append("shutdown")

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", Executor)
    monkeypatch.setattr(
        module,
        "_compile_claimed",
        lambda row: {
            **row,
            "agrees": False,
            "reason": "unsupported_semantics",
            "repair": {},
            "census": {},
        },
    )
    monkeypatch.setattr(
        agreement, "annotate_compiled_batch", lambda rows, **kwargs: rows
    )
    monkeypatch.setattr(
        agreement,
        "consensus_summary",
        lambda rows: {
            "agreement_rate": 0,
            "encoded": len(rows),
            "agree": 0,
            "disagree": len(rows),
            "unscored": 0,
        },
    )
    monkeypatch.setattr(weights, "record_consensus", lambda *args: None)


def test_catalog_completion_follows_durable_exchange_and_upload_failure_keeps_evidence(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    events = []
    _isolate_drain(monkeypatch, module, events)
    cache = SpanCache(tmp_path / "cache.duckdb")
    manifest = tmp_path / "retained-manifest.json"
    cache.enqueue(
        [{"source_span_id": "gap-1", "text": "The statute remains unsupported."}]
    )
    complete = cache.complete_claimed

    def stage(rows, *args, **kwargs):
        assert [row["source_span_id"] for row in rows] == ["gap-1"]
        manifest.write_text('{"evidence":"durable"}')
        events.append("stage")
        return {"census_rows": 1, "goal_rows": 1, "manifests": [str(manifest)]}

    def complete_after_stage(rows, **kwargs):
        assert manifest.read_text() == '{"evidence":"durable"}'
        events.append("complete")
        return complete(rows, **kwargs)

    def retry(*args, **kwargs):
        events.append("retry")
        return {
            "uploaded": 0,
            "failed": int(manifest.exists()),
            "pending": int(manifest.exists()),
        }

    monkeypatch.setattr(module, "_stage_exchange_batch", stage)
    monkeypatch.setattr(module, "_retry_exchange_outbox", retry)
    monkeypatch.setattr(cache, "complete_claimed", complete_after_stage)
    try:
        result = module.drain(
            cache,
            batch=1,
            path_hashes={},
            code_identity="test-code",
            upload=True,
            upload_dir=tmp_path / "out",
            compile_workers=1,
        )
        assert events.index("stage") < events.index("complete")
        assert events[0] == "retry" and events[-2:] == ["retry", "shutdown"]
        assert cache.stats()["gaps"] == 1
        assert manifest.exists() and result["exchange_upload_failures"] == 1
        assert result["census_rows"] == result["goal_rows"] == result["processed"] == 1
        assert result["goals_enqueued"] is False and result["admitted"] is False
    finally:
        cache.close()


def test_stage_failure_releases_claim_without_completing_catalog(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    events = []
    _isolate_drain(monkeypatch, module, events)
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.enqueue(
        [{"source_span_id": "gap-1", "text": "The statute remains unsupported."}]
    )

    def fail_stage(*args, **kwargs):
        raise OSError("outbox write failed")

    def never_complete(*args, **kwargs):
        pytest.fail("catalog completed before a durable census/goal export")

    monkeypatch.setattr(module, "_stage_exchange_batch", fail_stage)
    monkeypatch.setattr(module, "_retry_exchange_outbox", lambda *args, **kwargs: {})
    monkeypatch.setattr(cache, "complete_claimed", never_complete)
    try:
        with pytest.raises(OSError, match="outbox write failed"):
            module.drain(
                cache,
                batch=1,
                path_hashes={},
                code_identity="test-code",
                upload=False,
                upload_dir=tmp_path / "out",
                compile_workers=1,
            )
        pending = cache.pending()
        assert [(row["source_span_id"], row["status"]) for row in pending] == [
            ("gap-1", "pending")
        ]
        assert cache.stats()["gaps"] == 0
        assert events == ["shutdown"]
    finally:
        cache.close()


def test_restart_retries_outbox_without_recompiling_completed_spans(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    exchange = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.span_cache_exchange"
    )
    events = []
    _isolate_drain(monkeypatch, module, events)
    cache = SpanCache(tmp_path / "cache.duckdb")
    manifest = tmp_path / "retained.manifest.json"
    manifest.write_text("{}")
    pending = [manifest]

    def publish(path, *, upload):
        assert path == manifest and upload is True
        events.append("upload")
        pending.clear()
        return {"uploaded": True}

    def no_compile(*args, **kwargs):
        pytest.fail("restart should only replay durable manifests")

    monkeypatch.setattr(
        exchange,
        "pending_exchange_manifests",
        lambda root: list(pending),
        raising=False,
    )
    monkeypatch.setattr(exchange, "publish_exchange_manifest", publish, raising=False)
    monkeypatch.setattr(module, "_compile_claimed", no_compile)
    try:
        result = module.drain(
            cache,
            batch=1,
            path_hashes={},
            code_identity="test-code",
            upload=True,
            upload_dir=tmp_path / "out",
            compile_workers=1,
        )
        assert events == ["upload", "shutdown"]
        assert result["processed"] == 0 and result["exchange_uploads"] == 1
        assert result["goals_enqueued"] is False
    finally:
        cache.close()


def test_outbox_inventory_failure_still_shuts_down_compile_workers(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    module = _ingest_module()
    events = []
    _isolate_drain(monkeypatch, module, events)
    cache = SpanCache(tmp_path / "cache.duckdb")
    calls = []

    def retry(*args, **kwargs):
        calls.append(True)
        if len(calls) > 1:
            raise OSError("outbox directory unreadable")
        return {}

    monkeypatch.setattr(module, "_retry_exchange_outbox", retry)
    try:
        with pytest.raises(OSError, match="outbox directory unreadable"):
            module.drain(
                cache,
                batch=1,
                path_hashes={},
                code_identity="test-code",
                upload=True,
                upload_dir=tmp_path / "out",
                compile_workers=1,
            )
        assert events == ["shutdown"]
    finally:
        cache.close()


def test_stage_batches_are_bounded_and_include_producer_binding(tmp_path, monkeypatch):
    module = _ingest_module()
    exchange = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.span_cache_exchange"
    )
    observed = []

    def publish(rows, root, **kwargs):
        assert kwargs["upload"] is False
        assert (
            kwargs["model_identity"]
            == "deterministic-modal-codec:no-learned-checkpoint"
        )
        observed.extend(rows)
        assert len(rows) <= 64
        path = root / f"manifest-{len(observed)}.json"
        path.write_text("{}")
        return {
            "manifest": {"path": str(path)},
            "census_rows": len(rows),
            "goal_rows": len(rows),
        }

    monkeypatch.setattr(exchange, "publish_compiled_exchange", publish)
    rows = [{"source_span_id": str(i), "text": "source"} for i in range(130)]
    result = module._stage_exchange_batch(
        rows,
        tmp_path,
        agent_id="machine",
        release_id="release",
        code_identity="code",
        path_hashes={"compiler.py": "hash"},
    )
    assert result["census_rows"] == result["goal_rows"] == 130
    assert len(result["manifests"]) == 3
    assert all(
        row["compiler_path_hashes"] == {"compiler.py": "hash"}
        and row["code_identity"] == "code"
        and row["release_id"] == "release"
        for row in observed
    )
    assert all("compiler_path_hashes" not in row for row in rows)


def test_stage_full_captures_partition_by_bytes_without_truncating_evidence(
    tmp_path, monkeypatch
):
    module = _ingest_module()
    exchange = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.span_cache_exchange"
    )
    monkeypatch.setattr(module, "EXCHANGE_INPUT_BATCH_BYTES", 900)
    publications = []

    def publish(rows, root, **kwargs):
        publications.append(rows)
        path = root / f"part-{len(publications)}.json"
        path.write_text("{}")
        return {
            "manifest": {"path": str(path)},
            "census_rows": len(rows),
            "goal_rows": 0,
        }

    monkeypatch.setattr(exchange, "publish_compiled_exchange", publish)
    rows = [
        {
            "source_span_id": str(i),
            "text": "source",
            "autoencoder_capture": {
                "raw_losses": {"measured": 0.25},
                "modal_ir": "x" * 450,
            },
        }
        for i in range(3)
    ]
    result = module._stage_exchange_batch(
        rows, tmp_path, agent_id="a", release_id="r", code_identity="c", path_hashes={}
    )
    assert len(publications) == 3 and result["census_rows"] == 3
    emitted = [row for batch in publications for row in batch]
    assert [row["source_span_id"] for row in emitted] == ["0", "1", "2"]
    assert [row["autoencoder_capture"] for row in emitted] == [
        row["autoencoder_capture"] for row in rows
    ]


def test_stage_rejects_single_capture_over_byte_limit_without_publishing(
    tmp_path, monkeypatch
):
    module = _ingest_module()
    exchange = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.span_cache_exchange"
    )
    monkeypatch.setattr(module, "EXCHANGE_INPUT_BATCH_BYTES", 900)

    def no_publish(*args, **kwargs):
        pytest.fail("oversize evidence cannot be silently truncated or staged")

    monkeypatch.setattr(exchange, "publish_compiled_exchange", no_publish)
    with pytest.raises(ValueError, match="one census capture exceeds"):
        module._stage_exchange_batch(
            [{"source_span_id": "a", "autoencoder_capture": {"modal_ir": "x" * 1000}}],
            tmp_path,
            agent_id="a",
            release_id="r",
            code_identity="c",
            path_hashes={},
        )
    assert not list(tmp_path.iterdir())


def test_training_requests_at_256_spans_are_deferred_without_local_training(
    tmp_path, monkeypatch
):
    module = _ingest_module()
    agreement = importlib.import_module(
        "ipfs_datasets_py.logic.autoformal.span_agreement"
    )
    events = []
    _isolate_drain(monkeypatch, module, events)
    rows = [
        {"source_span_id": str(i), "text": "source", "census": {"train": True}}
        for i in range(256)
    ]
    completions = []

    class Cache:
        def claim_batch(self, *args, **kwargs):
            return [] if completions else rows

        def complete_claimed(self, completed, **kwargs):
            completions.append(completed)
            return {"sealed_total": 0, "gap_total": len(completed)}

        def stats(self):
            return {"sealed": 0, "gaps": 256, "pending": 0, "terms": 0}

    def never_train(*args, **kwargs):
        pytest.fail(
            "ingestion must export training work rather than executing or publishing a model"
        )

    monkeypatch.setattr(agreement, "train_until_canary_improves", never_train)
    monkeypatch.setattr(
        module, "_compile_claimed", lambda row: {**row, "agrees": False}
    )
    monkeypatch.setattr(
        module,
        "_stage_exchange_batch",
        lambda rows, *args, **kwargs: {
            "census_rows": len(rows),
            "goal_rows": len(rows),
        },
    )
    monkeypatch.setattr(module, "_retry_exchange_outbox", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "_poll_remote_checkpoint", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "_flush_checkpoint", lambda *args, **kwargs: {})
    result = module.drain(
        Cache(),
        batch=256,
        path_hashes={},
        code_identity="code",
        upload=False,
        upload_dir=tmp_path,
        compile_workers=1,
    )
    assert len(completions) == 1 and len(completions[0]) == 256
    assert result["training_executed"] is False
    assert result["training_deferred_to_dataset"] is True
    assert result["census_rows"] == result["goal_rows"] == 256


def test_actual_durable_outbox_replays_on_restart_with_no_compile_work(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import (
        load_exchange_bundle,
        pending_exchange_manifests,
    )
    from types import SimpleNamespace

    module = _ingest_module()
    events = []
    _isolate_drain(monkeypatch, module, events)
    destination = tmp_path / "out" / "exchange"
    row = {
        "source_span_id": "retained",
        "text": "The agency shall retain records.",
        "autoencoder_text": "The agency shall retain records.",
        "agrees": False,
        "reason": "compiler_abstain",
        "comparison": {"agrees": True, "capture": {}},
        "cosine_similarity": 0.9,
        "cross_entropy_loss": 0.4,
        "reconstruction_loss": 0.1,
    }
    staged = module._stage_exchange_batch(
        [row],
        destination,
        agent_id="machine",
        release_id="r",
        code_identity="code",
        path_hashes={},
    )
    manifest = Path(staged["manifests"][0])
    bundle = load_exchange_bundle(manifest)
    assert len(bundle["census_rows"]) == len(bundle["repair_packets"]) == 1
    assert pending_exchange_manifests(destination) == [manifest]
    commits = []

    class Api:
        def repo_info(self, **kwargs):
            return SimpleNamespace(sha="a" * 40)

        def get_paths_info(self, *args, **kwargs):
            return []

        def create_commit(self, **kwargs):
            commits.append(kwargs)
            return SimpleNamespace(oid="b" * 40)

    def no_compile(*args, **kwargs):
        pytest.fail("replaying a completed outbox must not recompile source")

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: Api())
    monkeypatch.setattr(module, "_compile_claimed", no_compile)
    cache = SpanCache(tmp_path / "cache.duckdb")
    try:
        result = module.drain(
            cache,
            batch=1,
            path_hashes={},
            code_identity="code",
            upload=True,
            upload_dir=destination.parent,
            compile_workers=1,
        )
        assert result["processed"] == 0 and result["exchange_uploads"] == 1
        assert len(commits) == 1 and len(commits[0]["operations"]) == 3
        assert pending_exchange_manifests(destination) == []
    finally:
        cache.close()
