"""Contracts for independent, snapshot-safe LegalIR family evaluation."""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    LegalIREvaluationArtifact,
    LegalIREvaluationCacheKey,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    FamilyShardResult,
    FamilySnapshotMismatchError,
    IncompleteFamilyEvaluationError,
    LegalIRFamilyEvaluator,
    SharedEvaluationArtifacts,
    aggregate_family_results,
    canonical_legal_ir_evaluation_family,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import (
    EvaluationSnapshot,
)


def snapshot(sequence: int = 4) -> EvaluationSnapshot:
    return EvaluationSnapshot.from_state_json(
        {"weight": 0.25},
        sequence=sequence,
        compiler_version="compiler-a",
        holdout_version="holdout-a",
        schema_version="metrics-a",
    )


def callbacks(callback):
    return {family: callback for family in LEGAL_IR_EVALUATION_FAMILIES}


def successful_results(item: EvaluationSnapshot) -> dict[str, FamilyShardResult]:
    return {
        family: FamilyShardResult(
            family=family,
            sequence=item.sequence,
            versions=item.versions,
            metrics={"score": (index + 1) / 10.0},
        )
        for index, family in enumerate(LEGAL_IR_EVALUATION_FAMILIES)
    }


def test_required_semantic_family_set_and_aliases_are_stable() -> None:
    assert LEGAL_IR_EVALUATION_FAMILIES == (
        "deontic",
        "frame_logic",
        "tdfol",
        "knowledge_graphs",
        "cec",
        "external_provers",
        "decompiler",
        "temporal",
        "provenance",
    )
    assert canonical_legal_ir_evaluation_family("TDFOL") == "tdfol"
    assert canonical_legal_ir_evaluation_family("kg") == "knowledge_graphs"
    with pytest.raises(ValueError, match="unsupported"):
        canonical_legal_ir_evaluation_family("unowned")


def test_all_shards_run_independently_over_the_same_immutable_artifacts() -> None:
    item = snapshot()
    source = {"compiled": {"operators": ["O"]}}
    shared = SharedEvaluationArtifacts.for_snapshot(item, [source])
    source["compiled"]["operators"].append("MUTATED")
    barrier = threading.Barrier(len(LEGAL_IR_EVALUATION_FAMILIES))
    artifact_ids: list[int] = []
    thread_ids: set[int] = set()
    lock = threading.Lock()

    def evaluate(request):
        with lock:
            artifact_ids.append(id(request.shared_artifacts))
            thread_ids.add(threading.get_ident())
        barrier.wait(timeout=2.0)
        assert request.artifacts[0]["compiled"]["operators"] == ("O",)
        with pytest.raises(TypeError):
            request.artifacts[0]["new"] = True
        return {"score": 1.0, "family": request.family}

    evaluator = LegalIRFamilyEvaluator(callbacks(evaluate), max_retries=0)
    result = evaluator.evaluate(item, shared)

    assert result.succeeded
    assert result.complete and result.matching_snapshot
    assert tuple(result.results) == LEGAL_IR_EVALUATION_FAMILIES
    assert len(set(artifact_ids)) == 1
    assert len(thread_ids) == len(LEGAL_IR_EVALUATION_FAMILIES)
    assert result.macro_score == 1.0


def test_cached_artifacts_must_match_the_snapshot_before_callbacks_run() -> None:
    item = snapshot()
    matching_key = LegalIREvaluationCacheKey(
        sample_hash="sample-a",
        compiler_commit=item.versions.compiler_version,
        state_hash=item.versions.state_version,
        metric_schema=item.versions.schema_version,
        config_hash="config-a",
    )
    artifact = LegalIREvaluationArtifact(
        key=matching_key,
        compiler_artifact={"formula": "O(pay)"},
    )
    shared = SharedEvaluationArtifacts.for_snapshot(item, [artifact])
    assert shared.artifact_count == 1
    assert len(shared.digest) == 64

    stale = dataclasses.replace(
        artifact,
        key=dataclasses.replace(matching_key, compiler_commit="compiler-stale"),
    )
    with pytest.raises(ValueError, match="compiler_version"):
        SharedEvaluationArtifacts.for_snapshot(item, [stale])


def test_only_failed_shard_is_retried_and_budget_is_bounded() -> None:
    item = snapshot()
    attempts = {family: 0 for family in LEGAL_IR_EVALUATION_FAMILIES}

    def evaluate(request):
        attempts[request.family] += 1
        if request.family == "cec" and request.attempt < 3:
            raise TimeoutError("temporary prover saturation")
        return {"score": 0.8}

    evaluator = LegalIRFamilyEvaluator(callbacks(evaluate), max_retries=2)
    result = evaluator.evaluate(item)

    assert result.succeeded
    assert attempts["cec"] == 3
    assert all(
        count == 1 for family, count in attempts.items() if family != "cec"
    )
    assert result.results["cec"].attempt_count == 3
    assert len(result.results["cec"].attempt_errors) == 2
    assert evaluator.summary()["shard_retries"] == 2
    assert evaluator.summary()["shard_attempts"] == 11


def test_exhausted_failure_is_preserved_and_disables_macro_score() -> None:
    item = snapshot()
    attempts = {family: 0 for family in LEGAL_IR_EVALUATION_FAMILIES}

    def evaluate(request):
        attempts[request.family] += 1
        if request.family == "provenance":
            raise RuntimeError("receipt graph unavailable")
        return {"score": 0.9}

    evaluator = LegalIRFamilyEvaluator(callbacks(evaluate), max_retries=1)
    result = evaluator.evaluate(item)
    report = result.to_dict()

    assert not result.succeeded
    assert result.failed_families == ("provenance",)
    assert result.failures == {"provenance": "RuntimeError: receipt graph unavailable"}
    assert result.macro_score is None
    assert report["macro_score"] is None
    assert report["macro_score_available"] is False
    assert report["family_results"]["provenance"]["status"] == "failed"
    assert report["family_results"]["deontic"]["status"] == "succeeded"
    assert attempts["provenance"] == 2
    assert all(
        count == 1 for family, count in attempts.items() if family != "provenance"
    )
    assert evaluator.summary()["retry_budget_exhausted"] == 1


def test_explicit_non_retryable_failure_does_not_spend_retry_budget() -> None:
    item = snapshot()
    calls = 0

    def evaluate(request):
        nonlocal calls
        calls += 1
        if request.family == "external_provers":
            return FamilyShardResult(
                family=request.family,
                sequence=request.sequence,
                versions=request.versions,
                error="unsupported translation",
                retryable=False,
            )
        return {"score": 1.0}

    evaluator = LegalIRFamilyEvaluator(callbacks(evaluate), max_retries=8)
    result = evaluator.evaluate(item)

    assert result.failed_families == ("external_provers",)
    assert result.results["external_provers"].attempt_count == 1
    assert calls == len(LEGAL_IR_EVALUATION_FAMILIES)
    assert evaluator.summary()["shard_retries"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": 99},
        {"versions": "compiler_version"},
        {"versions": "holdout_version"},
        {"versions": "schema_version"},
        {"versions": "state_version"},
    ],
)
def test_mistagged_callback_evidence_fails_closed_without_retry(change) -> None:
    item = snapshot()
    calls = 0

    def evaluate(request):
        nonlocal calls
        calls += 1
        sequence = change.get("sequence", request.sequence)
        versions = request.versions
        field = change.get("versions")
        if field:
            versions = dataclasses.replace(versions, **{field: f"wrong-{field}"})
        return FamilyShardResult(
            family=request.family,
            sequence=sequence,
            versions=versions,
            metrics={"score": 1.0},
        )

    evaluator = LegalIRFamilyEvaluator(callbacks(evaluate), max_retries=3)
    result = evaluator.evaluate(item)

    assert not result.succeeded
    assert all(
        shard.error.startswith("result_identity_mismatch:")
        for shard in result.results.values()
    )
    assert calls == len(LEGAL_IR_EVALUATION_FAMILIES)
    assert evaluator.summary()["shard_retries"] == 0


def test_aggregate_rejects_incomplete_duplicate_and_mixed_snapshot_evidence() -> None:
    item = snapshot()
    results = successful_results(item)
    missing = dict(results)
    missing.pop("temporal")
    with pytest.raises(IncompleteFamilyEvaluationError, match="temporal"):
        aggregate_family_results(item, missing)

    with pytest.raises(IncompleteFamilyEvaluationError, match="duplicate"):
        aggregate_family_results(
            item,
            [*results.values(), results["deontic"]],
        )

    other = snapshot(sequence=5)
    mixed = dict(results)
    mixed["temporal"] = dataclasses.replace(
        mixed["temporal"], sequence=other.sequence, versions=other.versions
    )
    with pytest.raises(FamilySnapshotMismatchError, match="temporal"):
        aggregate_family_results(item, mixed)


def test_callback_forms_and_snapshot_result_adapter_are_supported() -> None:
    item = snapshot()
    seen: set[str] = set()

    def dispatch(family, callback_snapshot, artifacts):
        assert callback_snapshot is item
        assert artifacts.versions == item.versions
        seen.add(family)
        return {"score": 0.5}

    result = LegalIRFamilyEvaluator(dispatch, max_retries=0).evaluate(item)

    assert result.succeeded
    assert seen == set(LEGAL_IR_EVALUATION_FAMILIES)
    assert result.macro_score == 0.5


def test_constructor_requires_complete_family_coverage_and_valid_bounds() -> None:
    with pytest.raises(ValueError, match="missing"):
        LegalIRFamilyEvaluator({"deontic": lambda request: {}})
    with pytest.raises(ValueError, match="max_retries"):
        LegalIRFamilyEvaluator(lambda request: {}, max_retries=-1)
    with pytest.raises(ValueError, match="max_workers"):
        LegalIRFamilyEvaluator(lambda request: {}, max_workers=0)


def test_family_metrics_and_serialized_results_are_immutable_copies() -> None:
    item = snapshot()
    metrics = {"score": 0.75, "nested": {"values": [1, 2]}}

    def evaluate(request):
        return metrics

    result = LegalIRFamilyEvaluator(evaluate, max_retries=0).evaluate(item)
    metrics["nested"]["values"].append(3)

    assert result.results["deontic"].metrics["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        result.results["deontic"].metrics["new"] = 1
    assert result.to_dict()["family_results"]["deontic"]["metrics"]["nested"] == {
        "values": [1, 2]
    }


def test_max_workers_bounds_concurrency_without_changing_completeness() -> None:
    item = snapshot()
    active = 0
    maximum = 0
    lock = threading.Lock()

    def evaluate(request):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"score": 1.0}

    result = LegalIRFamilyEvaluator(
        evaluate, max_retries=0, max_workers=2
    ).evaluate(item)

    assert result.succeeded
    assert maximum == 2

