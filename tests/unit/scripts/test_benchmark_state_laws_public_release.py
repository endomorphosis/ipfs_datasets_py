"""Current-contract tests for the immutable LCR-044 public benchmark."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    canonical_no_self_field_digest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
for _name in tuple(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)
public = importlib.import_module("scripts.ops.legal_data.check_state_laws_public_release")
bench = importlib.import_module("scripts.ops.legal_data.benchmark_state_laws_public_release")


PREVIOUS = public.PREVIOUS_PUBLIC_PIN
PUBLIC = "3" * 40
STAGING = "2" * 40
CANDIDATE_DIGEST = "a" * 64
RELEASE_DIGEST = "b" * 64


def _query_canaries() -> dict:
    return {
        name: {"passed": True}
        for name in ("bm25", "vector", "hybrid", "graph", "filters", "cache")
    } | {"jurisdictions": list(public.SORTED_JURISDICTIONS)}


def _public_canary() -> dict:
    key_digest = "f" * 64
    receipt = {
        "schema": public.CANONICAL_CANARY_SCHEMA,
        "receipt_kind": public.CANONICAL_CANARY_KIND,
        "task_id": public.TASK_ID,
        "goal_id": public.GOAL_ID,
        "program_id": public.PROGRAM_ID,
        "producer": public.PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": public.DEFAULT_DATASET_REPO,
        "public_revision": PUBLIC,
        "public_sha": PUBLIC,
        "previous_public_pin": PREVIOUS,
        "staging_revision": STAGING,
        "final_manifest_digest": CANDIDATE_DIGEST,
        "release_manifest_digest": RELEASE_DIGEST,
        "plan_digest": "c" * 64,
        "policy_proof_digest": "d" * 64,
        "publication_receipt_digest": "e" * 64,
        "downloaded": [
            {"relative_path": "manifest.json", "sha256": "1" * 64, "size_bytes": 1}
        ],
        "downloaded_bytes": 1,
        "downloaded_file_count": 1,
        "exact_descriptor_match": True,
        "viewer": {
            "passed": True,
            "dataset_viewer_api_passed": True,
            "default_config": public.DEFAULT_CONFIG_NAME,
            "ia_only": False,
            "jurisdictions": list(public.SORTED_JURISDICTIONS),
        },
        "key_sets": {
            "passed": True,
            "canonical_keys_sha256": key_digest,
            "families": {
                name: key_digest
                for name in ("embeddings", "bm25", "vectors", "graph", "adjacency")
            },
        },
        "query_canaries": _query_canaries(),
        "jurisdictions": list(public.SORTED_JURISDICTIONS),
        "jurisdiction_count": 51,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = receipt["content_digest"] = digest
    return public.check_canonical_public_canary_receipt(receipt)


def _measurements() -> dict:
    return {
        "cold": {"bytes": 1, "shards": 1, "latency_ms": 1.0, "cache_hits": 0},
        "warm": {"bytes": 0, "shards": 1, "latency_ms": 1.0, "cache_hits": 1},
        "warm_cache_hit_ratio": 1.0,
        "recall": {"dense_at_k": 1.0, "fused_at_k": 1.0},
        "jurisdiction_skew": 0.0,
        "jurisdictions": list(bench.SORTED_JURISDICTIONS),
        "local_ordered_cids_sha256": "2" * 64,
        "public_ordered_cids_sha256": "2" * 64,
        "local_explanations_sha256": "3" * 64,
        "public_explanations_sha256": "3" * 64,
        "route_justified": True,
        "complete_family_downloaded": False,
        "repair_tasks": [],
    }


def _receipt() -> dict:
    return bench.build_canonical_public_benchmark_receipt(
        public_canary=_public_canary(), measurements=_measurements()
    )


def test_identity_help_and_read_only_source() -> None:
    assert bench.TASK_ID == "LCR-044"
    assert bench.main(["--help"]) == 0
    source = Path(bench.__file__).read_text(encoding="utf-8")
    for forbidden in ("HfApi", "upload_folder", "authorize_and_mutate"):
        assert forbidden not in source


def test_benchmark_binds_pin_budgets_recall_and_ordered_parity() -> None:
    receipt = _receipt()
    assert bench.check_canonical_public_benchmark_receipt(receipt) == receipt
    assert receipt["public_revision"] == PUBLIC
    assert receipt["public_canary_digest"] == _public_canary()["canonical_digest"]
    assert receipt["cold"]["bytes"] == 1
    assert receipt["warm_cache_hit_ratio"] == 1.0
    assert receipt["route_justified"] is True
    assert receipt["complete_family_downloaded"] is False


def test_budget_regression_fails_without_adjusting_receipt() -> None:
    measured = _measurements()
    measured["cold"]["bytes"] = int(bench.BENCHMARK_BUDGETS["max_bytes"]) + 1
    with pytest.raises(bench.PublicBenchmarkBudgetError):
        bench.build_canonical_public_benchmark_receipt(
            public_canary=_public_canary(), measurements=measured
        )


def test_recall_regression_produces_repair_task() -> None:
    measured = _measurements()
    measured["recall"]["dense_at_k"] = bench.DENSE_RECALL_GATE - 0.01
    with pytest.raises(bench.PublicBenchmarkRegressionError) as raised:
        bench.validate_canonical_benchmark_measurements(measured)
    assert raised.value.repair_task["receipt_adjusted"] is False


def test_cid_drift_or_complete_family_download_fails_closed() -> None:
    measured = _measurements()
    measured["public_ordered_cids_sha256"] = "4" * 64
    with pytest.raises(bench.PublicBenchmarkParityError):
        bench.validate_canonical_benchmark_measurements(measured)
    measured = _measurements()
    measured["complete_family_downloaded"] = True
    with pytest.raises(bench.PublicBenchmarkParityError):
        bench.validate_canonical_benchmark_measurements(measured)


def test_receipt_tampering_fails_closed() -> None:
    changed = copy.deepcopy(_receipt())
    changed["warm"]["latency_ms"] = 2.0
    with pytest.raises(bench.PublicBenchmarkError, match="digest mismatch"):
        bench.check_canonical_public_benchmark_receipt(changed)


def test_injected_runner_is_pin_bound() -> None:
    calls: list[tuple[str, str]] = []

    def runner(repo_id: str, revision: str) -> dict:
        calls.append((repo_id, revision))
        return _measurements()

    receipt = bench.run_canonical_public_benchmark(
        public_canary=_public_canary(), benchmark_runner=runner
    )
    assert receipt["status"] == "passed"
    assert calls == [(bench.DEFAULT_DATASET_REPO, PUBLIC)]


def test_check_cli_is_read_only(tmp_path: Path) -> None:
    target = tmp_path / "benchmark.json"
    target.write_text(json.dumps(_receipt()), encoding="utf-8")
    before = target.read_bytes()
    assert bench.main(["--check", "--benchmark-report", str(target)]) == 0
    assert target.read_bytes() == before
    assert bench.main(
        ["--check", "--benchmark-report", str(target), "--write-report"]
    ) != 0
