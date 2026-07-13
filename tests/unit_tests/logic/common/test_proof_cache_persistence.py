"""Persistence coverage for the unified proof cache."""

import json
import time

from ipfs_datasets_py.logic.common.proof_cache import ProofCache


def test_persistent_cache_survives_restart(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    first = ProofCache(
        maxsize=10,
        ttl=300,
        enable_persistence=True,
        persistence_path=str(path),
    )
    first.set("registry-1", {"accepted": True}, prover_name="lean")

    second = ProofCache(
        maxsize=10,
        ttl=300,
        enable_persistence=True,
        persistence_path=str(path),
    )

    assert second.get("registry-1", prover_name="lean") == {"accepted": True}
    assert second.get_stats()["persistence_loads"] == 1


def test_persistent_cache_ignores_corrupt_file(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    path.write_text("{not-json", encoding="utf-8")

    cache = ProofCache(
        enable_persistence=True,
        persistence_path=str(path),
    )

    assert cache.get("missing", prover_name="lean") is None
    assert cache.get_stats()["persistence_errors"] == 1


def test_persistent_cache_drops_expired_entries(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    first = ProofCache(
        ttl=1,
        enable_persistence=True,
        persistence_path=str(path),
    )
    first.set("registry-1", {"accepted": True}, prover_name="lean")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][0]["timestamp"] = time.time() - 5
    path.write_text(json.dumps(payload), encoding="utf-8")

    second = ProofCache(
        ttl=1,
        enable_persistence=True,
        persistence_path=str(path),
    )

    assert second.get("registry-1", prover_name="lean") is None
    assert second.get_stats()["persistence_loads"] == 0


def test_persistent_cache_skips_non_json_result_without_losing_memory_entry(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    cache = ProofCache(
        enable_persistence=True,
        persistence_path=str(path),
    )
    result = {"object": object()}

    cache.set("registry-1", result, prover_name="lean")

    assert cache.get("registry-1", prover_name="lean") is result
    assert json.loads(path.read_text(encoding="utf-8"))["entries"] == []
    assert cache.get_stats()["persistence_skipped_results"] == 1


def test_stale_parallel_cache_instances_merge_entries(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    first = ProofCache(enable_persistence=True, persistence_path=str(path))
    second = ProofCache(enable_persistence=True, persistence_path=str(path))

    first.set("registry-1", {"accepted": True}, prover_name="lean")
    second.set("registry-2", {"accepted": True}, prover_name="lean")
    restored = ProofCache(enable_persistence=True, persistence_path=str(path))

    assert restored.get("registry-1", prover_name="lean") == {"accepted": True}
    assert restored.get("registry-2", prover_name="lean") == {"accepted": True}


def test_clear_replaces_persistent_snapshot(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    cache = ProofCache(enable_persistence=True, persistence_path=str(path))
    cache.set("registry-1", {"accepted": True}, prover_name="lean")

    cache.clear()
    restored = ProofCache(enable_persistence=True, persistence_path=str(path))

    assert restored.get("registry-1", prover_name="lean") is None
