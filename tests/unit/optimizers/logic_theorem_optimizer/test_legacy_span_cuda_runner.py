"""Owner queue recovery and evidence boundaries without CUDA or network."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("legacy_span_cuda_runner_test", ROOT / "scripts/ops/legal_ir/run_legacy_span_cuda.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def source(text="The agency shall retain records.", span_id="fixture-span"):
    return {"source_span_id": span_id, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text": text, "legal_id": "usc:us:1:1", "source_parent": {"revision": "a" * 40},
            "progress_parent": {"revision": "b" * 40}, "admitted": False, "formalized": False}


def receipt(row, batch_id):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_cuda import LEGACY_SHA256
    observation = {**row, "status": "diagnostic_observed", "compiler": {"compiler_status": "compiled", "roundtrip": True,
                    "decompiled": row["text"], "admitted": False, "formalized": False},
                   "raw_decoder": {"cosine_similarity": 0.9, "reconstruction_loss": 0.1},
                   "safety_projected_decoder": {"cosine_similarity": 1.0, "reconstruction_loss": 0.0},
                   "learned_formula_generation": False, "semantic_qualified": False}
    return {"schema_version": "legacy-span-cuda-diagnostic/v1", "mode": "legacy_mock_diagnostic",
            "rows": [observation], "producer_source": {"sha256": "c" * 64},
            "checkpoint": {"sha256": LEGACY_SHA256}, "sample_count": 1, "requested_span_count": 1,
            "raw_evaluation": {"sample_count": 1, "legal_ir_target_count": 1,
                               "cosine_similarity": 0.9, "reconstruction_loss": 0.1},
            "campaign": {"batch_id": batch_id}, "training_executed": False,
            "admitted": False, "formalized": False, "semantic_qualified": False}


@pytest.fixture
def queue(tmp_path):
    for name in ("receipts", "outbox"):
        (tmp_path / name).mkdir()
    db = runner.open_queue(tmp_path / "queue.duckdb")
    yield db, tmp_path
    db.close()


def test_enqueue_replay_deduplicates_and_conflict_rolls_back_cursor(queue):
    db, _ = queue
    row = source()
    runner.enqueue(db, {"rows": [row, row], "next_section": 1})
    runner.enqueue(db, {"rows": [row], "next_section": 1})
    assert db.execute("SELECT count(*) FROM work").fetchone()[0] == 1
    assert runner.meta(db, "section_cursor") == 1
    conflict = {**row, "text": "Different text, deliberately retaining the old digest."}
    fresh = source("The agency shall publish reports.", "another-span")
    with pytest.raises(ValueError, match="source identity conflict"):
        runner.enqueue(db, {"rows": [fresh, conflict], "next_section": 2})
    assert db.execute("SELECT count(*) FROM work").fetchone()[0] == 1
    assert runner.meta(db, "section_cursor") == 1


def test_interrupted_batch_requeues_without_losing_attempt_count(queue):
    db, runtime = queue
    row = source()
    runner.enqueue(db, {"rows": [row], "next_section": 1})
    first_id, rows = runner.select_batch(db, 4)
    assert rows == [row]
    runner.recover(db, runtime, "fixture-agent")
    assert db.execute("SELECT status,attempts,batch_id FROM work").fetchone() == ("pending", 1, None)
    assert db.execute("SELECT status FROM batches WHERE id=?", [first_id]).fetchone()[0] == "interrupted"
    second_id, retry = runner.select_batch(db, 4)
    assert retry == [row] and second_id != first_id
    assert db.execute("SELECT attempts FROM work").fetchone()[0] == 2


def test_resumed_work_is_not_starved_by_fresh_intake(queue):
    db, runtime = queue
    original = source()
    runner.enqueue(db, {"rows": [original], "next_section": 1})
    runner.select_batch(db, 1)
    runner.recover(db, runtime, "fixture-agent")
    fresh = [source(f"The officer shall retain record {i}.", f"fresh-{i}") for i in range(8)]
    runner.enqueue(db, {"rows": fresh, "next_section": 2})
    _, retried = runner.select_batch(db, 1)
    assert retried == [original]


def test_oversized_input_is_durably_deferred_without_truncation(queue):
    db, _ = queue
    oversized = source("The agency shall retain " + "record " * 3000, "oversized-span")
    normal = source()
    runner.enqueue(db, {"rows": [oversized, normal], "next_section": 2})
    saved, status, error = db.execute("SELECT payload,status,error FROM work WHERE status='deferred_input_bounds'").fetchone()
    assert json.loads(saved)["text"] == oversized["text"]
    assert "without truncation" in error
    assert runner.meta(db, "section_cursor") == 2
    _, rows = runner.select_batch(db, 8)
    assert rows == [normal]
    assert runner.select_batch(db, 8) is None


def test_unicode_batch_byte_limit_leaves_unselected_rows_pending(queue):
    db, _ = queue
    rows = [source("🙂" * 15990 + f"{index:02d}", f"unicode-span-{index}") for index in range(20)]
    runner.enqueue(db, {"rows": rows, "next_section": 20})
    _, selected = runner.select_batch(db, 32)
    assert 0 < len(selected) < len(rows)
    assert sum(len(row["text"].encode()) for row in selected) <= 1024 * 1024
    assert db.execute("SELECT count(*) FROM work WHERE status='pending'").fetchone()[0] == len(rows) - len(selected)


def test_replaying_compacted_completion_does_not_requeue_or_require_evicted_text(queue):
    db, _ = queue
    row = source()
    runner.enqueue(db, {"rows": [row], "next_section": 1})
    compact = {key: row[key] for key in ("source_span_id", "source_sha256", "legal_id")}
    compact["payload_evicted"] = True
    db.execute("UPDATE work SET status='done',payload=?", [json.dumps(compact)])
    runner.enqueue(db, {"rows": [row], "next_section": 2})
    assert db.execute("SELECT status,payload FROM work").fetchone() == ("done", json.dumps(compact))
    assert runner.meta(db, "section_cursor") == 2
    assert runner.select_batch(db, 8) is None
    with pytest.raises(ValueError, match="source identity conflict"):
        runner.enqueue(db, {"rows": [{**row, "legal_id": "usc:us:1:2"}], "next_section": 3})
    assert runner.meta(db, "section_cursor") == 2


def test_completed_eviction_retries_payload_compaction_and_preserves_unpublished(queue):
    db, _ = queue
    rows = [source(span_id="published"), source(span_id="unpublished"), source(span_id="verified-only")]
    runner.enqueue(db, {"rows": rows, "next_section": 3})
    db.execute("CREATE TABLE legacy_span_evictions (batch_id VARCHAR, status VARCHAR)")
    for batch_id, state, eviction in (("published", "published", "evicted"),
                                       ("unpublished", "staged", "evicted"),
                                       ("verified-only", "published", "verified")):
        db.execute("INSERT INTO batches VALUES (?, '[]', ?, NULL, NULL, NULL)", [batch_id, state])
        db.execute("INSERT INTO legacy_span_evictions VALUES (?,?)", [batch_id, eviction])
        for work_id, payload in db.execute("SELECT id,payload FROM work").fetchall():
            if json.loads(payload)["source_span_id"] == batch_id:
                db.execute("UPDATE work SET status='done',batch_id=? WHERE id=?", [batch_id, work_id])
    runner.compact_published_payloads(db)
    runner.compact_published_payloads(db)
    observed = {json.loads(payload)["source_span_id"]: json.loads(payload)
                for payload, in db.execute("SELECT payload FROM work").fetchall()}
    assert observed["published"] == {key: rows[0][key] for key in ("source_span_id", "source_sha256", "legal_id")} | {"payload_evicted": True}
    assert observed["unpublished"] == rows[1]
    assert observed["verified-only"] == rows[2]
    assert set(state for state, in db.execute("SELECT status FROM work").fetchall()) == {"done"}


def test_environment_keeps_dataset_transport_online_and_model_resolution_offline(monkeypatch):
    values = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "0"}
    monkeypatch.setattr(runner.os, "environ", values)
    runner.environment()
    assert values["HF_HUB_OFFLINE"] == "0"
    assert values["TRANSFORMERS_OFFLINE"] == "1"
    assert values["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] == "0"
    assert values["IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS"] == "0"
    assert values["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] == "1"


def test_vector_metrics_do_not_become_text_metrics_or_admission():
    original = receipt(source(), "batch-fixture")
    converted = runner.exchange_rows(original)[0]
    assert converted["autoencoder_text"] == ""
    assert converted["learned_formula_generation"] is False
    assert all(converted[key] is None for key in ("cosine_similarity", "cross_entropy_loss", "reconstruction_loss"))
    assert converted["autoencoder_observation"]["raw_decoder"]["cosine_similarity"] == 0.9
    assert converted["autoencoder_observation"]["safety_projected_decoder"]["cosine_similarity"] == 1.0
    assert converted["compiler_result"]["roundtrip"] is True
    assert converted["decompiled"] == original["rows"][0]["compiler"]["decompiled"]
    assert converted["comparison"]["agrees"] is False
    assert converted["comparison"]["capture"]["learned_text_unavailable"] is True
    assert converted["admitted"] is False and converted["formalized"] is False


def test_census_retains_compiler_output_but_reports_missing_learned_text():
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import exchange_from_compiled
    result = exchange_from_compiled(runner.exchange_rows(receipt(source(), "batch-fixture")),
                                   agent_id="fixture-agent", model_identity="legacy-fixture")
    census = result["census_rows"][0]
    assert census["compiler_roundtrip"] is True
    assert census["autoencoder_text"] == ""
    assert census["reason"] == "inference_still_failing"
    assert census["agrees"] is False
    assert all(census[key] is None for key in ("cosine_similarity", "cross_entropy_loss", "reconstruction_loss"))
    assert census["admitted"] is False and census["formalized"] is False
    assert result["goal_rows"] and all(row["enqueued"] is False for row in result["goal_rows"])
    retained = json.loads(census["input_json"])
    assert retained["autoencoder_observation"]["raw_decoder"]["cosine_similarity"] == 0.9


def test_sample_preparation_error_does_not_claim_learned_execution():
    captured = receipt(source(), "batch-fixture")
    captured["rows"][0].update(status="sample_preparation_error", raw_decoder=None,
                               safety_projected_decoder=None, error_type="ValueError")
    captured["sample_count"] = 0
    captured["raw_evaluation"] = {"sample_count": 0, "legal_ir_target_count": 0}
    converted = runner.exchange_rows(captured)[0]
    assert converted["learned_autoencoder_execution"] is False
    assert converted["autoencoder_observation"]["status"] == "sample_preparation_error"
    assert converted["compiler_result"]["compiler_status"] == "compiled"
    assert converted["admitted"] is False and converted["formalized"] is False


@pytest.mark.parametrize("change", ["text", "source_sha256", "legal_id", "duplicate_rows"])
def test_recovery_refuses_a_receipt_bound_to_different_source(queue, monkeypatch, change):
    db, runtime = queue
    row = source()
    runner.enqueue(db, {"rows": [row], "next_section": 1})
    batch_id, _ = runner.select_batch(db, 1)
    captured = receipt(row, batch_id)
    if change == "duplicate_rows":
        captured["rows"].append(copy.deepcopy(captured["rows"][0]))
    elif change == "source_sha256":
        captured["rows"][0][change] = "d" * 64
    else:
        captured["rows"][0][change] = "changed"
    runner.atomic(runtime / "receipts" / (batch_id + ".json"), captured)
    # Recovery must reject before publication/staging; this hook makes any
    # accidental restage a directly visible test failure rather than disk I/O.
    monkeypatch.setattr(runner, "stage", lambda *a, **kw: pytest.fail("mismatched receipt reached staging"))
    with pytest.raises(ValueError, match="identity|source|receipt"):
        runner.recover(db, runtime, "fixture-agent")
    assert db.execute("SELECT status FROM work").fetchone()[0] == "running"


@pytest.mark.parametrize("changed", ["checkpoint", "batch", "mode", "admitted", "formalized", "training_executed", "semantic_qualified", "row_authority"])
def test_receipt_validation_rejects_wrong_checkpoint_batch_or_authority(queue, changed):
    db, _ = queue
    row = source()
    runner.enqueue(db, {"rows": [row], "next_section": 1})
    batch_id, _ = runner.select_batch(db, 1)
    captured = receipt(row, batch_id)
    runner.validate_receipt(db, batch_id, captured)
    if changed == "checkpoint":
        captured["checkpoint"]["sha256"] = "d" * 64
    elif changed == "batch":
        captured["campaign"]["batch_id"] = "another-batch"
    elif changed == "mode":
        captured["mode"] = "semantic_qualified"
    elif changed == "row_authority":
        captured["rows"][0]["admitted"] = True
    else:
        captured[changed] = True
    with pytest.raises(ValueError, match="identity|authority"):
        runner.validate_receipt(db, batch_id, captured)


def test_per_sample_evaluation_does_not_repeat_other_rows_vectors():
    captured = receipt(source(), "batch-fixture")
    captured["rows"][0]["sample_id"] = "sample-a"
    second = receipt(source("The agency shall publish reports.", "second-span"), "batch-fixture")["rows"][0]
    second["sample_id"] = "sample-b"
    captured["rows"].append(second)
    captured["raw_evaluation"].update(decoded_embeddings={"sample-a": [1.0], "sample-b": [2.0]},
                                      losses_by_sample={"sample-a": 0.1, "sample-b": 0.2},
                                      legal_ir_losses={"deontic": 0.3})
    exports = runner.exchange_rows(captured)
    exported = exports[0]
    assert exported["raw_sample_evaluation"] == {"decoded_embeddings": [1.0], "losses_by_sample": 0.1}
    assert exports[1]["raw_sample_evaluation"] == {"decoded_embeddings": [2.0], "losses_by_sample": 0.2}
    assert "decoded_embeddings" not in exported["raw_batch_metrics"]
    assert "raw_batch_evaluation" not in exported
    assert exported["raw_batch_summary"]["legal_ir_losses"] == {"deontic": 0.3}
    assert "raw_batch_summary" not in exports[1]


def test_publication_failure_retains_durable_staged_batch_for_retry(queue, monkeypatch):
    db, _ = queue
    from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
    db.execute("INSERT INTO batches VALUES ('b1','[]','staged','manifest.json',NULL,'digest')")
    calls = []
    def publish(path, *, upload, api=None):
        calls.append((path, upload))
        return {"uploaded": False, "error": "TemporaryNetworkFailure"}
    monkeypatch.setattr(exchange, "publish_exchange_manifest", publish)
    runner.publish_pending(db, True)
    assert calls == [("manifest.json", True)]
    assert db.execute("SELECT status,publication FROM batches").fetchone() == ("staged", None)
    monkeypatch.setattr(exchange, "publish_exchange_manifest", lambda *a, **kw: {"uploaded": True, "commit_sha": "e" * 40})
    runner.publish_pending(db, True)
    assert db.execute("SELECT status FROM batches").fetchone()[0] == "published"


@pytest.mark.parametrize("header,delay", [("120", 120), ("1", 60), (None, 300), ("not-numeric", 300)])
def test_hub_rate_limit_persists_backoff_and_skips_all_network_until_retry(queue, monkeypatch, header, delay):
    db, runtime = queue
    import huggingface_hub
    from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_publication as publication
    db.execute("INSERT INTO batches VALUES ('b1','[]','staged','manifest.json',NULL,'digest')")
    now, calls = [1000.0], []

    class RateLimit(Exception):
        response = SimpleNamespace(status_code=429, headers={} if header is None else {"Retry-After": header})

    class API:
        def __init__(self):
            calls.append("create_api")
        def repo_info(self, **kwargs):
            calls.append("repo_info")
            raise RateLimit("test rate limit without a real request")

    def publish(path, *, upload, api):
        assert path == "manifest.json" and upload is True
        try:
            api.repo_info(repo_id="fixture-repository")
        except RateLimit:
            # Match the real exporter, which retains errors as a retry receipt.
            return {"uploaded": False, "error": "RateLimit"}
        pytest.fail("expected injected rate limit")

    def cleanup(*args, **kwargs):
        calls.append("cleanup_network")
        return []

    monkeypatch.setattr(runner.time, "time", lambda: now[0])
    monkeypatch.setattr(huggingface_hub, "HfApi", API)
    monkeypatch.setattr(exchange, "publish_exchange_manifest", publish)
    monkeypatch.setattr(publication, "cleanup_published_batches", cleanup)
    runner.publish_pending(db, True, runtime)
    assert calls == ["create_api", "repo_info"]
    assert runner.meta(db, "publication_retry_after") == 1000 + delay
    assert db.execute("SELECT status,publication FROM batches").fetchone() == ("staged", None)
    observed = runner.status(db, runtime, phase="publication_deferred")
    assert observed["publication_retry_after"] == 1000 + delay

    # Reopen the durable owner database to verify that restart does not bypass
    # the cooldown or even construct a Hub API client.
    db.close()
    reopened = runner.open_queue(runtime / "queue.duckdb")
    try:
        now[0] = 1000 + delay - 1
        runner.publish_pending(reopened, True, runtime)
        assert calls == ["create_api", "repo_info"]
        assert reopened.execute("SELECT status FROM batches").fetchone()[0] == "staged"
        now[0] = 1000 + delay
        runner.publish_pending(reopened, True, runtime)
        assert calls == ["create_api", "repo_info", "create_api", "repo_info"]
        assert runner.meta(reopened, "publication_retry_after") == now[0] + delay
    finally:
        reopened.close()


def test_cleanup_verification_rate_limit_uses_the_same_persisted_backoff(queue, monkeypatch):
    db, runtime = queue
    import huggingface_hub
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_publication as publication
    calls = []
    class RateLimit(Exception):
        response = SimpleNamespace(status_code=429, headers={"Retry-After": "90"})
    class API:
        def __init__(self):
            calls.append("create_api")
        def repo_info(self, **kwargs):
            calls.append("cleanup_repo_info")
            raise RateLimit("test cleanup rate limit")
    def cleanup(db, runtime, *, api):
        api.repo_info(repo_id="fixture-repository")
        pytest.fail("rate limit must prevent cleanup")
    monkeypatch.setattr(huggingface_hub, "HfApi", API)
    monkeypatch.setattr(publication, "cleanup_published_batches", cleanup)
    monkeypatch.setattr(runner.time, "time", lambda: 1000.0)
    runner.publish_pending(db, True, runtime)
    assert calls == ["create_api", "cleanup_repo_info"]
    assert runner.meta(db, "publication_retry_after") == 1090.0
    runner.publish_pending(db, True, runtime)
    assert calls == ["create_api", "cleanup_repo_info"]


def test_engine_prefetches_one_cpu_batch_before_waiting_for_current_gpu(tmp_path, monkeypatch):
    """Exercise controller ordering with deferred futures, never launching workers."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake
    rows = [source(span_id="span-a"), source("The agency shall publish reports.", "span-b")]
    events = []

    class Future:
        def __init__(self, callback):
            self.callback = callback
        def result(self):
            return self.callback()

    class Executor:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def submit(self, function, *args):
            if function is runner._gpu_ready:
                return Future(lambda: {"source": {"sha256": "c" * 64}, "pid": 1, "cuda": {}})
            if function is runner._compile:
                events.append(("cpu_submit", args[0]["source_span_id"]))
                return Future(lambda: {})
            assert function is runner._gpu_evaluate
            events.append(("gpu_submit", args[0][0]["source_span_id"]))
            def completed():
                events.append(("gpu_result", args[0][0]["source_span_id"]))
                return receipt(args[0][0], "replaced-by-engine")
            return Future(completed)

    def stage(db, runtime, batch_id, captured, agent):
        runner.validate_receipt(db, batch_id, captured)
        db.execute("UPDATE batches SET status='staged' WHERE id=?", [batch_id])
        db.execute("UPDATE work SET status='done' WHERE batch_id=?", [batch_id])
        events.append(("staged", captured["rows"][0]["source_span_id"], captured["campaign"]["cpu_cuda_overlap"]))

    monkeypatch.setattr(runner, "STOP", False)
    monkeypatch.setattr(runner, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(runner, "remote_progress", lambda: {"sha256": "d" * 64, "revision": "e" * 40})
    monkeypatch.setattr(runner, "download_progress", lambda *args: tmp_path / "fake-progress.parquet")
    monkeypatch.setattr(runner, "publish_pending", lambda *args: None)
    monkeypatch.setattr(runner, "stage", stage)
    monkeypatch.setattr(runner, "digest_file", lambda *args: runner.RUNNER_SHA256)
    monkeypatch.setattr(intake, "prepare_progress_index", lambda *args, **kwargs: SimpleNamespace(table="fixture_index"))
    monkeypatch.setattr(intake, "iter_joined_section_batches", lambda *args, **kwargs: iter([
        {"rows": rows, "next_section": 2, "counts": {"matched_count": 2}}]))
    monkeypatch.setattr(intake, "progress_coverage", lambda *args: {"fixture": True})
    args = SimpleNamespace(runtime_directory=tmp_path, checkpoint=tmp_path / "fake-checkpoint.json",
        source_parquet=tmp_path / "fake-laws.parquet", agent_id="fixture-agent", batch_size=1,
        compiler_workers=2, bridge_workers=1, publish_only=False, max_batches=2,
        storage_bytes=100_000_000, poll_seconds=1, upload=False)
    assert runner.engine(args) == 0
    gpu_order = [event[1] for event in events if event[0] == "gpu_submit"]
    assert len(gpu_order) == 2
    assert events.index(("cpu_submit", gpu_order[1])) < events.index(("gpu_result", gpu_order[0]))
    assert events.index(("gpu_result", gpu_order[0])) < events.index(("gpu_submit", gpu_order[1]))
    assert ("staged", gpu_order[0], True) in events
    assert ("staged", gpu_order[1], False) in events


def test_publish_only_retries_existing_outbox_without_input_download_or_model(tmp_path, monkeypatch):
    db = runner.open_queue(tmp_path / "campaign.duckdb")
    db.execute("INSERT INTO batches VALUES ('b1','[]','staged','manifest.json',NULL,'digest')")
    db.close()
    calls = []
    def forbidden(*args, **kwargs):
        pytest.fail("publication-only route attempted model execution or source retrieval")
    def publish(db, upload, runtime):
        calls.append((upload, runtime))
        db.execute("UPDATE batches SET status='published' WHERE status='staged'")
    monkeypatch.setattr(runner, "ProcessPoolExecutor", forbidden)
    monkeypatch.setattr(runner, "remote_progress", forbidden)
    monkeypatch.setattr(runner, "download_progress", forbidden)
    monkeypatch.setattr(runner, "publish_pending", publish)
    args = runner.arguments(["--runtime-directory", str(tmp_path), "--publish-only", "--upload"])
    assert runner.engine(args) == 0
    assert calls and all(value == (True, tmp_path) for value in calls)
    assert json.loads((tmp_path / "status.json").read_text())["phase"] == "publication_completed"
