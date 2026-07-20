from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION,
    InvalidEvaluationArtifactError,
    LegalIREvaluationArtifact,
    LegalIREvaluationCache,
    LegalIREvaluationCacheKey,
)


def _key(**updates: str) -> LegalIREvaluationCacheKey:
    values = {
        "sample_hash": "sample-sha",
        "compiler_commit": "compiler-sha",
        "state_hash": "state-sha",
        "metric_schema": "metric-v1",
        "config_hash": "config-sha",
    }
    values.update(updates)
    return LegalIREvaluationCacheKey(**values)


def _artifact(
    key: LegalIREvaluationCacheKey,
    *,
    seconds: float = 0.25,
) -> LegalIREvaluationArtifact:
    return LegalIREvaluationArtifact(
        key=key,
        compiler_artifact={"modal_ir": {"formula_count": 2}, "tokens": ["shall"]},
        embedding=(0.25, 0.75),
        metrics={"cross_entropy_loss": 0.1},
        per_view_metrics={"deontic": {"valid": True}},
        metadata={"profile": "bounded"},
        compilation_seconds=seconds,
        embedding_seconds=0.05,
        metric_seconds=0.02,
    )


def test_key_contains_every_invalidation_dimension_and_is_deterministic() -> None:
    first = LegalIREvaluationCacheKey.for_sample(
        {"sample_id": "s1", "text": "A person shall report."},
        compiler_commit="commit-a",
        state_hash="state-a",
        metric_schema="metric-a",
        configuration={"guided": False, "dimensions": 8},
    )
    repeated = LegalIREvaluationCacheKey.for_sample(
        {"text": "A person shall report.", "sample_id": "s1"},
        compiler_commit="commit-a",
        state_hash="state-a",
        metric_schema="metric-a",
        configuration={"dimensions": 8, "guided": False},
    )
    assert first == repeated
    assert first.digest == repeated.digest

    changed = [
        _key(sample_hash="other"),
        _key(compiler_commit="other"),
        _key(state_hash="other"),
        _key(metric_schema="other"),
        _key(config_hash="other"),
    ]
    assert len({item.digest for item in changed}) == len(changed)
    assert all(item.digest != _key().digest for item in changed)


def test_artifact_is_deeply_immutable_and_rejects_unsafe_numbers() -> None:
    artifact = _artifact(_key())
    with pytest.raises(TypeError):
        artifact.compiler_artifact["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        artifact.compiler_artifact["modal_ir"]["formula_count"] = 3  # type: ignore[index]
    assert isinstance(artifact.compiler_artifact["tokens"], tuple)

    with pytest.raises(InvalidEvaluationArtifactError):
        LegalIREvaluationArtifact(
            key=_key(),
            compiler_artifact={},
            embedding=(float("nan"),),
        )


def test_persistent_role_reuse_reports_avoided_work_and_saved_time(tmp_path) -> None:
    key = _key()
    cache = LegalIREvaluationCache(tmp_path)
    calls = 0

    def compute() -> LegalIREvaluationArtifact:
        nonlocal calls
        calls += 1
        return _artifact(key)

    baseline = cache.get_or_compute(key, compute, role="baseline")
    guided = cache.get_or_compute(key, compute, role="guided")
    cache.clear_memory()
    validation = cache.get_or_compute(key, compute, role="validation")

    assert calls == 1
    assert baseline == guided == validation
    summary = cache.summary()
    assert summary["computations"] == 1
    assert summary["avoided_recompilations"] == 2
    assert summary["memory_hits"] == 1
    assert summary["disk_hits"] == 1
    assert summary["saved_wall_time_seconds"] == pytest.approx(
        2 * baseline.computation_seconds
    )
    assert summary["role_hits"] == {"guided": 1, "validation": 1}

    fresh_process_cache = LegalIREvaluationCache(tmp_path)
    assert fresh_process_cache.get(key, role="per_view.deontic") == baseline
    assert fresh_process_cache.summary()["disk_hits"] == 1


def test_concurrent_callers_single_flight_one_computation(tmp_path) -> None:
    key = _key()
    cache = LegalIREvaluationCache(tmp_path)
    calls = 0
    calls_lock = threading.Lock()
    started = threading.Event()

    def compute() -> LegalIREvaluationArtifact:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        time.sleep(0.08)
        return _artifact(key)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(cache.get_or_compute, key, compute, role=f"view-{index}")
            for index in range(8)
        ]
        assert started.wait(timeout=1.0)
        artifacts = [future.result(timeout=2.0) for future in futures]

    assert calls == 1
    assert all(artifact == artifacts[0] for artifact in artifacts)
    summary = cache.summary()
    assert summary["computations"] == 1
    assert summary["coalesced_waiters"] == 7
    assert summary["avoided_recompilations"] == 7


def test_independent_cache_instances_coalesce_through_process_lock(tmp_path) -> None:
    key = _key()
    caches = [LegalIREvaluationCache(tmp_path), LegalIREvaluationCache(tmp_path)]
    calls = 0
    calls_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def invoke(cache: LegalIREvaluationCache) -> LegalIREvaluationArtifact:
        def compute() -> LegalIREvaluationArtifact:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)
            return _artifact(key)

        barrier.wait(timeout=1.0)
        return cache.get_or_compute(key, compute, role="validation")

    with ThreadPoolExecutor(max_workers=2) as executor:
        artifacts = list(executor.map(invoke, caches))

    assert calls == 1
    assert artifacts[0] == artifacts[1]
    assert sum(cache.summary()["process_coalesced_hits"] for cache in caches) == 1


def test_corrupt_and_stale_entries_fail_closed_then_are_replaced(tmp_path) -> None:
    key = _key()
    cache = LegalIREvaluationCache(tmp_path)
    cache.put(_artifact(key))
    path = cache.entry_path(key)

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["artifact"]["metrics"]["cross_entropy_loss"] = 999.0
    path.write_text(json.dumps(envelope), encoding="utf-8")
    cache.clear_memory()
    assert cache.get(key) is None
    assert cache.summary()["corrupt_entries"] == 1

    recomputed = cache.get_or_compute(key, lambda: _artifact(key, seconds=0.5))
    assert recomputed.metrics["cross_entropy_loss"] == pytest.approx(0.1)

    stale = json.loads(path.read_text(encoding="utf-8"))
    stale["schema_version"] = "old-schema"
    path.write_text(json.dumps(stale), encoding="utf-8")
    cache.clear_memory()
    assert cache.get(key) is None
    assert cache.summary()["stale_entries"] == 1
    assert LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION != "old-schema"


def test_failed_computation_is_not_cached_or_left_in_flight(tmp_path) -> None:
    key = _key()
    cache = LegalIREvaluationCache(tmp_path)

    with pytest.raises(RuntimeError, match="compiler failed"):
        cache.get_or_compute(
            key,
            lambda: (_ for _ in ()).throw(RuntimeError("compiler failed")),
        )

    recovered = cache.get_or_compute(key, lambda: _artifact(key))
    assert recovered.key == key
    assert cache.summary()["computations"] == 1


def test_runner_metric_roles_reuse_the_typed_sample_artifact(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        uscode_modal_daemon_runner as runner,
    )

    monkeypatch.setattr(runner, "_read_metric_disk_cache", lambda *_args: None)
    monkeypatch.setattr(runner, "_write_metric_disk_cache", lambda *_args: None)

    class Codec:
        config = SimpleNamespace(parser_backend="test")

        def __init__(self) -> None:
            self.calls = 0

        def encode(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                decoded_modal_text="report obligation",
                frame_candidates=["frame"],
                kg_triples=[],
                losses={
                    "cosine_similarity": 0.9,
                    "cross_entropy_loss": 0.1,
                    "symbolic_validity_penalty": 0.0,
                },
                metadata={"llm_call_count": 0, "legal_ir_view_families": ["deontic"]},
                modal_ir=SimpleNamespace(formulas=["formula"]),
            )

    sample = SimpleNamespace(
        sample_id="sample-1",
        text="A person shall report.",
        citation="1 USC 1",
        source="unit-test",
        embedding_vector=[0.2, 0.8],
        embedding_model="test",
        title="Title 1",
        section="1",
    )
    cache = LegalIREvaluationCache(tmp_path)
    codec = Codec()
    common = {
        "evaluation_cache": cache,
        "compiler_commit": "compiler-a",
        "state_hash": "state-a",
        "metric_schema": "metric-a",
        "sample_timeout_seconds": 0.0,
    }

    train = runner.compiler_ir_metric_block(
        [sample], codec, evaluation_role="baseline_train", **common
    )
    validation = runner.compiler_ir_metric_block(
        [sample], codec, evaluation_role="baseline_validation", **common
    )

    assert codec.calls == 1
    assert train["cross_entropy_loss"] == validation["cross_entropy_loss"]
    assert validation["evaluation_artifact_cache"]["avoided_recompilations"] >= 1
    assert validation["evaluation_artifact_cache"]["role_hits"] == {
        "baseline_validation": 1
    }
