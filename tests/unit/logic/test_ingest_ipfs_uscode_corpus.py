"""Corpus enqueue budgets use a fake executor, without workers or data access."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def test_sparse_flush_skips_claims_and_does_not_upload_the_full_checkpoint(tmp_path, monkeypatch):
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    )
    spec = importlib.util.spec_from_file_location("uscode_sparse_checkpoint_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.enqueue([{"source_span_id": "pending", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"}])
    cache.claim_batch("compile-a", limit=1)
    calls = []

    class Api:
        def create_repo(self, *args, **kwargs):
            calls.append("create")

        def upload_file(self, **kwargs):
            calls.append(kwargs["path_in_repo"])

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: Api())
    skipped = module._flush_checkpoint(cache, tmp_path / "out", upload=True, agent_id="compile-a")
    assert skipped["uploaded"] is False
    assert skipped["skipped"] == "no_durable_change"
    assert skipped["full_checkpoint_uploaded"] is False
    assert calls == []
    cache.apply_census(
        {"rows": [{
            "agrees": True, "decompiled": "Agency must make records available.",
            "legal_id": "usc:us:5:552", "source_span_id": "s1",
            "text": "Each agency shall make records available.",
        }]},
        code_identity="sha256:test",
    )
    uploaded = module._flush_checkpoint(cache, tmp_path / "out", upload=True, agent_id="compile-a")
    assert uploaded["uploaded"] is True
    assert uploaded["delta_count"] == 1
    assert uploaded["full_checkpoint_uploaded"] is False
    assert calls[1].startswith("autoformal/uscode/checkpoints/compile-a/sparse-")
    assert "resume-checkpoint.parquet" not in calls[1]
    again = module._flush_checkpoint(cache, tmp_path / "out", upload=True, agent_id="compile-a")
    assert again["skipped"] == "no_durable_change"
    assert len(calls) == 2
    cache.close()


def test_poll_reads_other_machines_deltas_once(tmp_path, monkeypatch):
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    )
    spec = importlib.util.spec_from_file_location("uscode_sparse_poll_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    writer = SpanCache(tmp_path / "writer.duckdb")
    writer._set_meta("dataset_id", "justicedao/ipfs_uscode")
    writer.apply_census(
        {"rows": [{
            "agrees": False, "legal_id": "usc:us:18:1001", "reason": "compiler_abstain:penalty",
            "source_span_id": "g1", "text": "Whoever shall be imprisoned.",
        }]},
        code_identity="sha256:test",
    )
    delta = writer.sparse_progress_delta()
    remote = tmp_path / "remote.parquet"
    writer.write_sparse_progress_parquet(remote, delta["rows"], agent_id="compile-b", update_id="sparse-b")
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
    spec = importlib.util.spec_from_file_location("uscode_enqueue_budget_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    budget_module = importlib.import_module("ipfs_datasets_py.logic.autoformal.worker_budget")
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
    result = module.enqueue_corpus(
        FakeCache(), parquet, limit=130, release_id="test-release", resume=True,
        upload=False, upload_dir=tmp_path / "not-written",
    )
    assert capacities == [2]
    assert chunks == [1] * 64 + [2] * 33
    assert shutdowns == [(True, False)]
    assert enqueued == [{"source_span_id": f"document-{number}"} for number in range(130)]
    assert checkpoints == [
        {"documents": count, "parquet": str(parquet.resolve())}
        for count in (512, 576, 578)
    ]
    assert flushed == [(tmp_path / "not-written", False)]
    assert result == {
        "admitted": False, "documents": 578, "formalized": False,
        "resumed_from": 448, "spans_enqueued": 130,
    }
    output = capsys.readouterr().out
    assert "parse_workers=2 parse_task_budget=1" in output
    assert "parse_workers=2 parse_task_budget=2" in output
    assert not list(tmp_path.iterdir())
