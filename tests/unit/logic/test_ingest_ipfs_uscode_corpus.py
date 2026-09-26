"""Corpus enqueue budgets use a fake executor, without workers or data access."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


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
        assert agent_id == "control-plane"
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
