"""Unit coverage for continuously batched Leanstral audit inference."""

from __future__ import annotations

import json
from types import SimpleNamespace

from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditConfig,
    LeanstralAuditRequest,
    LeanstralAuditRunner,
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralAuditWorkItem,
)
from ipfs_datasets_py.logic.modal.leanstral_audit_worker import (
    LeanstralBatchScheduler,
    LeanstralBatchSchedulerConfig,
)
from ipfs_datasets_py.utils import anyio_compat


def _work(
    request_id: str,
    family: str,
    *,
    template: str = "modal_operator_preserved",
    model: str = "Leanstral",
    failure_branch: bool = False,
) -> SimpleNamespace:
    evidence = {"cluster": {"semantic_family": family}}
    if failure_branch:
        evidence["failure_subgoal"] = {
            "logic_family": family,
            "theorem_template": template,
        }
    request = SimpleNamespace(
        request_id=request_id,
        evidence=evidence,
        prompt={"template": template},
        model={"model": model, "provider": "leanstral_local"},
    )
    return SimpleNamespace(work_key=f"work-{request_id}", request=request)


def _audit_request(index: int) -> LeanstralAuditRequest:
    return LeanstralAuditRequest.build(
        evidence={"cluster": {"semantic_family": "deontic"}},
        prompt={"template": "modal_operator_preserved", "index": index},
        model={
            "model": "Leanstral",
            "provider": "leanstral_local",
            "vibe_agent": "lean",
        },
        proof_obligation_ids=[f"obl-{index}"],
    )


def _response(request: LeanstralAuditRequest) -> str:
    return json.dumps(
        {
            "abstention_reason": "insufficient evidence",
            "affected_ir_families": ["deontic"],
            "classification": "abstain",
            "confidence": 0.0,
            "counterexample": None,
            "drafted_logic_candidates": [],
            "missing_semantic_rule": {},
            "proof_obligation_ids": list(request.proof_obligation_ids),
            "proposed_compiler_surface": [],
            "request_cache_key": request.cache_key,
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        },
        sort_keys=True,
    )


def _audit_work_item(request: LeanstralAuditRequest, index: int) -> LeanstralAuditWorkItem:
    return LeanstralAuditWorkItem(
        work_key=f"work-{index}",
        request=request,
        evidence_ids=(f"evidence-{index}",),
        compiler_commit="commit-a",
        semantic_signature="deontic:test",
        state_hashes=("state-a",),
        source_record_hashes=(f"record-{index}",),
    )


def test_scheduler_groups_every_inference_compatibility_axis() -> None:
    scheduler = LeanstralBatchScheduler(
        LeanstralBatchSchedulerConfig(max_batch_size=8, token_budget_bucket_size=256)
    )
    scheduler.enqueue(
        _work("a", "deontic"),
        token_budget=1700,
        deadline_monotonic=101.2,
        now=100.0,
    )
    scheduler.enqueue(
        _work("b", "deontic"),
        token_budget=1701,
        deadline_monotonic=102.2,
        now=100.0,
    )
    scheduler.enqueue(
        _work("c", "temporal"),
        token_budget=1700,
        deadline_monotonic=101.2,
        now=100.0,
    )
    scheduler.enqueue(
        _work("d", "deontic", template="exception_scope_preserved"),
        token_budget=1700,
        deadline_monotonic=101.2,
        now=100.0,
    )

    batches = scheduler.drain(force=True, now=100.0)

    assert sorted(batch.request_ids for batch in batches) == [("a",), ("b",), ("c",), ("d",)]
    assert {batch.key.logic_family for batch in batches} == {"deontic", "temporal"}
    assert {batch.key.token_budget_bucket for batch in batches} == {1792}


def test_scheduler_coalesces_audit_and_failure_branch_with_matching_axes() -> None:
    scheduler = LeanstralBatchScheduler(LeanstralBatchSchedulerConfig(max_batch_size=8))
    scheduler.enqueue(
        _work("audit", "deontic"),
        prompt_kind="failure_branch",
        deadline_monotonic=200.4,
        now=200.0,
    )
    scheduler.enqueue(
        _work("failure", "deontic", failure_branch=True),
        deadline_monotonic=200.4,
        now=200.0,
    )

    batch = scheduler.pop_ready_batch(force=True, now=200.0)

    assert batch is not None
    assert batch.request_ids == ("audit", "failure")
    assert batch.key.prompt_kind == "failure_branch"


def test_scheduler_is_bounded_and_round_robins_logic_families() -> None:
    scheduler = LeanstralBatchScheduler(LeanstralBatchSchedulerConfig(max_batch_size=2))
    for index in range(4):
        scheduler.enqueue(
            _work(f"d-{index}", "deontic"), deadline_monotonic=10.5, now=10.0
        )
    for index in range(2):
        scheduler.enqueue(
            _work(f"t-{index}", "temporal"), deadline_monotonic=10.5, now=10.0
        )

    batches = scheduler.drain(force=True, now=10.0)

    assert [batch.key.logic_family for batch in batches] == [
        "deontic",
        "temporal",
        "deontic",
    ]
    assert [len(batch.items) for batch in batches] == [2, 2, 2]


def test_scheduler_flushes_partial_batches_on_wait_and_deadline() -> None:
    scheduler = LeanstralBatchScheduler(
        LeanstralBatchSchedulerConfig(
            min_batch_size=4,
            max_batch_size=8,
            max_wait_seconds=0.5,
            deadline_guard_seconds=0.1,
        )
    )
    scheduler.enqueue(_work("wait", "deontic"), deadline_monotonic=20.0, now=10.0)
    assert scheduler.pop_ready_batch(now=10.49) is None
    waited = scheduler.pop_ready_batch(now=10.5)
    assert waited is not None and waited.formation_reason == "max_wait"

    scheduler.enqueue(_work("deadline", "temporal"), deadline_monotonic=11.0, now=10.6)
    urgent = scheduler.pop_ready_batch(now=10.91)
    assert urgent is not None and urgent.formation_reason == "deadline"


def test_scheduler_async_wait_continuously_flushes_and_close_drains() -> None:
    scheduler = LeanstralBatchScheduler(
        LeanstralBatchSchedulerConfig(
            min_batch_size=4,
            max_batch_size=8,
            max_wait_seconds=0.01,
        )
    )
    scheduler.enqueue(_work("aged", "deontic"), deadline_monotonic=10**9)
    aged = anyio_compat.run_with_backend(scheduler.wait_for_batch())
    assert aged is not None and aged.formation_reason == "max_wait"

    scheduler.enqueue(_work("close-flush", "temporal"), deadline_monotonic=10**9)
    scheduler.close()
    closed = anyio_compat.run_with_backend(scheduler.wait_for_batch())
    assert closed is not None and closed.formation_reason == "forced"
    assert anyio_compat.run_with_backend(scheduler.wait_for_batch()) is None


def test_scheduler_cancellation_and_expiry_are_per_item() -> None:
    scheduler = LeanstralBatchScheduler(LeanstralBatchSchedulerConfig(max_batch_size=8))
    scheduler.enqueue(_work("keep", "deontic"), deadline_monotonic=30.0, now=20.0)
    scheduler.enqueue(_work("cancel", "deontic"), deadline_monotonic=30.0, now=20.0)
    scheduler.enqueue(_work("expire", "deontic"), deadline_monotonic=20.1, now=20.0)
    assert scheduler.cancel("cancel")

    batch = scheduler.pop_ready_batch(force=True, now=20.2)
    terminal = scheduler.take_terminal_items()

    assert batch is not None and batch.request_ids == ("keep",)
    assert [(item.request_id, reason) for item, reason in terminal] == [
        ("cancel", "caller_cancelled"),
        ("expire", "deadline_expired"),
    ]
    telemetry = scheduler.telemetry_snapshot()
    assert telemetry["cancelled_count"] == 1
    assert telemetry["deadline_expired_count"] == 1


def test_scheduler_batch_ids_and_output_order_are_deterministic() -> None:
    def form() -> tuple[str, tuple[str, ...]]:
        scheduler = LeanstralBatchScheduler(LeanstralBatchSchedulerConfig(max_batch_size=8))
        for request_id in ("r-2", "r-1"):
            scheduler.enqueue(
                _work(request_id, "deontic"), deadline_monotonic=41.0, now=40.0
            )
        batch = scheduler.pop_ready_batch(force=True, now=40.0)
        assert batch is not None
        return batch.batch_id, batch.request_ids

    assert form() == form()
    assert form()[1] == ("r-2", "r-1")


def test_mesh_batch_responses_are_reassociated_by_request_id() -> None:
    requests = [_audit_request(1), _audit_request(2)]

    def reversed_batch(prompts: list[str], **kwargs: object) -> list[str]:
        del prompts, kwargs
        return [_response(requests[1]), _response(requests[0])]

    runner = LeanstralAuditRunner(
        LeanstralAuditConfig(enabled=True, cache_writes_enabled=False),
        llm_generate_batch=reversed_batch,
    )

    results = runner.run_initial_batch(requests, use_mesh=True)

    assert [result.request.request_id for result in results] == [
        requests[0].request_id,
        requests[1].request_id,
    ]
    assert [result.response.request_id for result in results if result.response] == [
        requests[0].request_id,
        requests[1].request_id,
    ]
    assert all(result.validation.accepted for result in results)
    assert all(
        "batch_response_reassociated_by_request_id" in result.repair_reasons
        for result in results
    )


def test_missing_batch_output_fails_only_that_item_for_individual_retry() -> None:
    requests = [_audit_request(1), _audit_request(2)]
    calls: list[dict[str, object]] = []

    def direct_batch(prompts: list[str], **kwargs: object) -> list[str]:
        calls.append(dict(kwargs))
        return [_response(requests[0])]

    runner = LeanstralAuditRunner(
        LeanstralAuditConfig(enabled=True, cache_writes_enabled=False),
        llm_generate_batch=direct_batch,
    )

    results = runner.run_initial_batch(requests, use_mesh=False)

    assert results[0].validation.accepted
    assert not results[1].validation.accepted
    assert "batch_response_missing" in results[1].repair_reasons
    assert results[0].request.request_id == requests[0].request_id
    assert results[1].request.request_id == requests[1].request_id
    assert calls[0]["use_mesh"] is False


def test_worker_repairs_only_invalid_batch_item() -> None:
    requests = [_audit_request(1), _audit_request(2)]
    call_sizes: list[int] = []

    def generate_batch(prompts: list[str], **kwargs: object) -> list[str]:
        del kwargs
        call_sizes.append(len(prompts))
        if len(prompts) == 2:
            return [_response(requests[0]), "not json"]
        return [_response(requests[1])]

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            batch_size=2,
            max_retries=0,
            validation_repair_retries=1,
        ),
        llm_generate_batch=generate_batch,
    )
    results = anyio_compat.run_with_backend(
        worker._run_items_batch(
            [_audit_work_item(requests[0], 1), _audit_work_item(requests[1], 2)]
        )
    )

    assert [result.status for result in results] == ["accepted", "accepted"]
    assert call_sizes == [2, 1]
    assert results[0].generation_attempts == 1
    assert results[1].generation_attempts == 2
    assert results[1].attempts == 2


def test_batch_telemetry_is_source_free_and_reports_efficiency() -> None:
    scheduler = LeanstralBatchScheduler(LeanstralBatchSchedulerConfig(max_batch_size=2))
    scheduler.enqueue(_work("one", "deontic"), deadline_monotonic=51.0, now=50.0)
    scheduler.enqueue(_work("two", "deontic"), deadline_monotonic=51.0, now=50.0)
    scheduler.pop_ready_batch(now=50.0)

    telemetry = scheduler.telemetry_snapshot()

    assert telemetry["formed_batch_count"] == 1
    assert telemetry["dispatched_item_count"] == 2
    assert telemetry["average_batch_size"] == 2.0
    assert telemetry["family_dispatch_counts"] == {"deontic": 2}
    assert "one" not in json.dumps(telemetry)
