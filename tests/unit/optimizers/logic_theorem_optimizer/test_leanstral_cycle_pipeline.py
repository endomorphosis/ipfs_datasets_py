"""Revision-bound one-cycle-lag Leanstral guidance pipeline tests."""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from ipfs_datasets_py.logic.modal.leanstral_audit_worker import (
    LeanstralCycleGuidanceRequest,
    LeanstralCycleGuidanceResult,
    LeanstralCycleLineage,
    LeanstralCyclePipeline,
    LeanstralCyclePipelineConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    build_leanstral_cycle_guidance_request,
    leanstral_cycle_input_revision,
    leanstral_cycle_proof_lineage,
    run_leanstral_cycle_pipeline_boundary,
)


def lineage(**changes: str) -> LeanstralCycleLineage:
    values = {
        "schema_version": "guidance-schema-a",
        "model": "Leanstral-8B-a",
        "source_revision": "source-a",
        "state_revision": "state-a",
        "proof_lineage": "proof-a",
    }
    values.update(changes)
    return LeanstralCycleLineage(**values)


def request(cycle: int, **lineage_changes: str) -> LeanstralCycleGuidanceRequest:
    return LeanstralCycleGuidanceRequest.from_payload(
        {
            "cycle": cycle,
            "proof_obligation_ids": [f"proof-{cycle}"],
            "rows": [{"id": cycle}],
        },
        cycle=cycle,
        lineage=lineage(**lineage_changes),
    )


def accepted_result(
    item: LeanstralCycleGuidanceRequest,
    *,
    guidance: object | None = None,
) -> LeanstralCycleGuidanceResult:
    return LeanstralCycleGuidanceResult.for_request(
        item,
        {"updates": [item.cycle]} if guidance is None else guidance,
        verified=True,
        verified_by=("lean-kernel", "modal-bridge"),
    )


def test_request_freezes_state_and_input_revision() -> None:
    payload = {
        "proof_route_status": {"valid_count": 1},
        "rows": [{"id": "row-a", "values": [1, 2]}],
    }
    item = LeanstralCycleGuidanceRequest.from_payload(
        payload,
        cycle=1,
        lineage=lineage(),
    )
    original_id = item.request_id

    payload["rows"][0]["values"].append(99)
    decoded = item.payload()
    decoded["rows"][0]["values"].append(100)

    assert item.payload()["rows"][0]["values"] == [1, 2]
    assert item.request_id == original_id
    assert item.to_dict()["input_digest"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.cycle = 9  # type: ignore[misc]


def test_verified_previous_cycle_is_single_use_and_only_then_promoted() -> None:
    promoted: list[object] = []
    pipeline = LeanstralCyclePipeline(lambda item: accepted_result(item))
    try:
        assert pipeline.enqueue(request(1)).enqueued
        assert pipeline.wait_until_idle(1.0)

        decision = pipeline.promote_previous(
            current_cycle=2,
            expected_lineage=lineage(),
            promote=promoted.append,
        )

        assert decision.consumed
        assert decision.status == "consumed_previous_cycle"
        assert decision.guidance == {"updates": [1]}
        assert promoted == [{"updates": [1]}]
        assert not pipeline.consume_previous(
            current_cycle=2,
            expected_lineage=lineage(),
        ).consumed
    finally:
        pipeline.close()


def test_slow_inference_never_blocks_warm_trainer_and_late_result_is_stale() -> None:
    started = threading.Event()
    release = threading.Event()
    promoted: list[object] = []

    def slow_evaluate(item: LeanstralCycleGuidanceRequest) -> LeanstralCycleGuidanceResult:
        if item.cycle == 1:
            started.set()
            assert release.wait(2.0)
        return accepted_result(item)

    pipeline = LeanstralCyclePipeline(
        slow_evaluate,
        config=LeanstralCyclePipelineConfig(queue_capacity=2),
    )
    try:
        before = time.monotonic()
        assert pipeline.enqueue(request(1)).status == "enqueued"
        assert time.monotonic() - before < 0.1
        assert started.wait(1.0)

        # This represents the warm trainer completing cycle two while cycle one
        # inference remains in flight.  Both poll and next enqueue are zero-wait.
        before = time.monotonic()
        report = run_leanstral_cycle_pipeline_boundary(
            pipeline=pipeline,
            request=request(2),
            promote=promoted.append,
        )
        assert time.monotonic() - before < 0.1
        assert report["consumption"]["status"] == "late_previous_cycle"
        assert report["enqueue"]["enqueued"] is True
        assert promoted == []

        release.set()
        assert pipeline.wait_until_idle(1.0)

        # At boundary three only cycle two is eligible.  The now-complete cycle
        # one result is stale and cannot be used as a substitute.
        report = run_leanstral_cycle_pipeline_boundary(
            pipeline=pipeline,
            request=request(3),
            promote=promoted.append,
        )
        assert report["consumption"]["consumed"] is True
        assert promoted == [{"updates": [2]}]
        assert any(
            item["reason"] == "stale_late_result" and item["cycle"] == 1
            for item in pipeline.diagnostics
        )
    finally:
        release.set()
        pipeline.close()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schema_version", "guidance-schema-b"),
        ("model", "Other-Model"),
        ("source_revision", "source-b"),
        ("state_revision", "state-b"),
        ("proof_lineage", "proof-b"),
    ],
)
def test_each_result_lineage_axis_is_required(
    field: str,
    replacement: str,
) -> None:
    def mismatched(item: LeanstralCycleGuidanceRequest) -> LeanstralCycleGuidanceResult:
        result = accepted_result(item)
        return dataclasses.replace(
            result,
            lineage=dataclasses.replace(item.lineage, **{field: replacement}),
        )

    promoted: list[object] = []
    pipeline = LeanstralCyclePipeline(mismatched)
    try:
        pipeline.enqueue(request(1))
        assert pipeline.wait_until_idle(1.0)
        decision = pipeline.promote_previous(
            current_cycle=2,
            expected_lineage=lineage(),
            promote=promoted.append,
        )
        assert not decision.consumed
        assert decision.status == "lineage_mismatch"
        assert decision.mismatch_fields == (field,)
        assert promoted == []
    finally:
        pipeline.close()


@pytest.mark.parametrize(
    "forge",
    ["unverified", "missing_verifier", "request_id", "input_digest", "error"],
)
def test_untrusted_results_never_reach_state_or_todo_callbacks(forge: str) -> None:
    def evaluator(item: LeanstralCycleGuidanceRequest) -> LeanstralCycleGuidanceResult:
        result = accepted_result(item)
        if forge == "unverified":
            return dataclasses.replace(result, verified=False)
        if forge == "missing_verifier":
            return dataclasses.replace(result, verified_by=())
        if forge == "request_id":
            return dataclasses.replace(result, request_id="forged-request")
        if forge == "input_digest":
            return dataclasses.replace(result, input_digest="forged-digest")
        return dataclasses.replace(result, error="verification failed")

    state_mutations: list[object] = []
    codex_todos: list[object] = []
    pipeline = LeanstralCyclePipeline(evaluator)
    try:
        pipeline.enqueue(request(1))
        assert pipeline.wait_until_idle(1.0)

        def promote(value: object) -> None:
            state_mutations.append(value)
            codex_todos.append(value)

        decision = pipeline.promote_previous(
            current_cycle=2,
            expected_lineage=lineage(),
            promote=promote,
        )
        assert not decision.consumed
        assert state_mutations == []
        assert codex_todos == []
        if forge in {"request_id", "input_digest"}:
            assert decision.status == "lineage_mismatch"
        elif forge == "error":
            assert decision.status == "inference_failed"
        else:
            assert decision.status == "unverified_result"
    finally:
        pipeline.close()


def test_string_verified_flag_and_string_verifier_fail_closed() -> None:
    def evaluator(item: LeanstralCycleGuidanceRequest) -> dict[str, object]:
        result = accepted_result(item).to_dict()
        result["verified"] = "true"
        result["verified_by"] = "lean-kernel"
        return result

    promoted: list[object] = []
    pipeline = LeanstralCyclePipeline(evaluator)
    try:
        pipeline.enqueue(request(1))
        assert pipeline.wait_until_idle(1.0)
        decision = pipeline.promote_previous(
            current_cycle=2,
            expected_lineage=lineage(),
            promote=promoted.append,
        )
        assert decision.status == "unverified_result"
        assert not decision.consumed
        assert promoted == []
    finally:
        pipeline.close()


def test_bounded_synchronous_debug_mode_times_out_then_result_remains_pollable() -> None:
    release = threading.Event()

    def slow(item: LeanstralCycleGuidanceRequest) -> LeanstralCycleGuidanceResult:
        assert release.wait(2.0)
        return accepted_result(item)

    pipeline = LeanstralCyclePipeline(
        slow,
        config=LeanstralCyclePipelineConfig(
            queue_capacity=1,
            synchronous=True,
            synchronous_timeout_seconds=0.04,
        ),
    )
    try:
        before = time.monotonic()
        enqueue = pipeline.enqueue(request(1))
        elapsed = time.monotonic() - before
        assert enqueue.status == "synchronous_timeout"
        assert 0.025 <= elapsed < 0.25

        release.set()
        assert pipeline.wait_until_idle(1.0)
        decision = pipeline.consume_previous(
            current_cycle=2,
            expected_lineage=lineage(),
        )
        assert decision.consumed
    finally:
        release.set()
        pipeline.close()


def test_runner_request_builder_binds_state_source_and_proof_revisions() -> None:
    state = ModalAutoencoderTrainingState(
        legal_ir_view_logits={"deontic": 0.25},
        proof_feedback_version_fingerprint="lean-toolchain-a",
    )
    payload = {
        "packets": [
            {
                "evidence_hashes": {"proof_route_hash": "proof-route-a"},
                "proof_obligation_ids": ["obligation-a"],
                "source": {"sample_id": "sample-a"},
            }
        ]
    }
    item = build_leanstral_cycle_guidance_request(
        cycle=4,
        state=state,
        input_payload=payload,
        model="Leanstral-8B",
    )

    assert item.lineage.source_revision == leanstral_cycle_input_revision(payload)
    assert item.lineage.proof_lineage == leanstral_cycle_proof_lineage(payload)
    assert item.lineage.state_revision == state.state_identity(
        metric_lineage="legal-ir-daemon-metrics-v2"
    )
    assert item.lineage.model == "Leanstral-8B"

    payload["packets"][0]["proof_obligation_ids"].append("obligation-b")
    assert item.lineage.source_revision != leanstral_cycle_input_revision(payload)
    assert item.lineage.proof_lineage != leanstral_cycle_proof_lineage(payload)


def test_queue_pressure_skips_without_waiting_or_replacing_revision() -> None:
    release = threading.Event()

    def blocked(item: LeanstralCycleGuidanceRequest) -> LeanstralCycleGuidanceResult:
        assert release.wait(2.0)
        return accepted_result(item)

    pipeline = LeanstralCyclePipeline(
        blocked,
        config=LeanstralCyclePipelineConfig(queue_capacity=1),
    )
    try:
        assert pipeline.enqueue(request(1)).enqueued
        before = time.monotonic()
        rejected = pipeline.enqueue(request(2))
        assert time.monotonic() - before < 0.1
        assert not rejected.enqueued
        assert rejected.status == "queue_full"
        assert pipeline.request_for_cycle(2) is None
    finally:
        release.set()
        pipeline.close()
