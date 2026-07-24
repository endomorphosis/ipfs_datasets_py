from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from benchmarks.logic_pipeline import runner
from benchmarks.logic_pipeline.adapters import StageAdapter
from benchmarks.logic_pipeline.capabilities import (
    HSSLEV0724C07,
    ResourceClass,
    ResourceLeaseError,
    ResourceLeaseReceipt,
    ResourceLeaseRequest,
    ResourceLeaseTimeout,
    ResourcePolicy,
    ResourceScheduler,
    run_bounded_process_group,
)
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    FailureCode,
    OutcomeStatus,
    Split,
    StageName,
)


SHA_MANIFEST = hashlib.sha256(b"resource-bound-cases").hexdigest()
SHA_ENVIRONMENT = hashlib.sha256(b"pinned-resource-environment").hexdigest()


def _case(case_id: str = "resource-case") -> runner.AblationCase:
    return runner.AblationCase.create(
        case_id,
        {"case_id": case_id, "text": "bounded resource input"},
        split=Split.PILOT,
    )


def _adapters() -> dict[StageName, StageAdapter]:
    return {
        stage: StageAdapter(
            stage,
            handler=lambda request, current=stage: {
                "case_id": request.case_id,
                "stage": current.value,
            },
        )
        for stage in StageName
    }


def test_resource_evidence_and_policy_are_strict() -> None:
    assert callable(HSSLEV0724C07)
    assert "queue delay" in HSSLEV0724C07()
    policy = ResourcePolicy(
        max_workers=4,
        max_memory_bytes=1024,
        max_model_instances=1,
        max_model_workers=2,
        max_solver_processes=2,
        max_kernel_workers=1,
        max_validation_workers=1,
        queue_timeout_seconds=1,
        cancellation_grace_seconds=0.1,
    )
    assert policy.to_dict()["max_model_instances"] == 1
    assert ResourcePolicy.from_dict(policy.to_dict()) == policy
    with pytest.raises(ValueError, match="max_model_instances"):
        ResourcePolicy(max_model_instances=0)
    with pytest.raises(ValueError, match="model_identity"):
        ResourceLeaseRequest("model-work", ResourceClass.MODEL)
    with pytest.raises(ValueError, match="only for the model"):
        ResourceLeaseRequest(
            "kernel-work",
            ResourceClass.KERNEL,
            model_identity="leanstral-119b",
        )


def test_model_identity_is_shared_and_second_large_instance_is_bounded() -> None:
    scheduler = ResourceScheduler(
        ResourcePolicy(
            max_workers=3,
            max_memory_bytes=1024,
            max_model_instances=1,
            max_model_workers=3,
            max_solver_processes=1,
            max_kernel_workers=1,
            max_validation_workers=1,
            queue_timeout_seconds=0.05,
            cancellation_grace_seconds=0.05,
        )
    )
    first = scheduler.acquire(
        ResourceLeaseRequest(
            "symai-work",
            ResourceClass.MODEL,
            model_identity="leanstral-119b",
        )
    )
    second = scheduler.acquire(
        ResourceLeaseRequest(
            "leanstral-work",
            ResourceClass.MODEL,
            model_identity="leanstral-119b",
        )
    )
    assert scheduler.active_model_identities == ("leanstral-119b",)
    assert not first.shared_model_instance
    assert second.shared_model_instance

    with pytest.raises(ResourceLeaseTimeout):
        scheduler.acquire(
            ResourceLeaseRequest(
                "foreign-model-work",
                ResourceClass.MODEL,
                model_identity="different-119b",
                timeout_seconds=0.02,
            )
        )
    second.release()
    first.release()
    assert ResourceLeaseReceipt.from_dict(
        scheduler.receipts[0].to_dict()
    ) == scheduler.receipts[0]
    assert scheduler.active_model_identities == ()
    assert scheduler.loaded_model_identities == ("leanstral-119b",)
    assert [item.shared_model_instance for item in scheduler.receipts] == [
        True,
        False,
    ]
    with pytest.raises(ResourceLeaseError, match="twice"):
        first.release()


def test_oversubscription_queues_and_records_delay_without_cross_lane_borrowing() -> None:
    scheduler = ResourceScheduler(
        ResourcePolicy(
            max_workers=2,
            max_memory_bytes=4096,
            max_model_instances=1,
            max_model_workers=1,
            max_solver_processes=1,
            max_kernel_workers=1,
            max_validation_workers=1,
            queue_timeout_seconds=1,
            cancellation_grace_seconds=0.05,
        )
    )
    solver = scheduler.acquire(
        ResourceLeaseRequest("solver-one", ResourceClass.SOLVER)
    )
    kernel = scheduler.acquire(
        ResourceLeaseRequest("kernel-one", ResourceClass.KERNEL)
    )
    assert solver.request.resource_class is ResourceClass.SOLVER
    assert kernel.request.resource_class is ResourceClass.KERNEL
    kernel.release()

    acquired: list[object] = []

    def wait_for_solver() -> None:
        lease = scheduler.acquire(
            ResourceLeaseRequest(
                "solver-two",
                ResourceClass.SOLVER,
                timeout_seconds=0.5,
            )
        )
        acquired.append(lease)
        lease.release()

    thread = threading.Thread(target=wait_for_solver)
    thread.start()
    time.sleep(0.04)
    solver.release()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert len(acquired) == 1
    delayed = next(
        item for item in scheduler.receipts if item.owner_id == "solver-two"
    )
    assert delayed.queue_delay_ms >= 20
    assert delayed.outcome == "released"


def test_cancellation_wakes_queued_lease_and_releases_active_capacity() -> None:
    scheduler = ResourceScheduler(
        ResourcePolicy(
            max_workers=1,
            max_solver_processes=1,
            queue_timeout_seconds=1,
            cancellation_grace_seconds=0.05,
        )
    )
    active = scheduler.acquire(
        ResourceLeaseRequest("active-solver", ResourceClass.SOLVER)
    )
    outcome: list[type[BaseException]] = []

    def blocked() -> None:
        try:
            scheduler.acquire(
                ResourceLeaseRequest("cancelled-solver", ResourceClass.SOLVER)
            )
        except BaseException as exc:  # retained for the assertion below
            outcome.append(type(exc))

    thread = threading.Thread(target=blocked)
    thread.start()
    time.sleep(0.02)
    scheduler.cancel("cancelled-solver")
    thread.join(timeout=1)
    active.release()

    from benchmarks.logic_pipeline.capabilities import ResourceLeaseCancelled

    assert outcome == [ResourceLeaseCancelled]
    assert not scheduler.active_model_identities


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_solver_process_group_timeout_terminates_and_reaps_children() -> None:
    script = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True);time.sleep(30)"
    )
    result = run_bounded_process_group(
        (sys.executable, "-c", script),
        timeout_seconds=0.1,
        cancellation_grace_seconds=0.1,
    )

    assert result.timed_out
    assert result.process_group_reaped
    child_pid = int(result.stdout.strip().splitlines()[0])
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        stat = Path(f"/proc/{child_pid}/stat")
        try:
            state = stat.read_text(encoding="utf-8").split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        time.sleep(0.01)
    else:
        pytest.fail("solver child survived process-group cancellation")


def test_bounded_process_receives_binary_stdin_without_a_shell() -> None:
    payload = b"(check-sat)\\n"
    result = run_bounded_process_group(
        (
            sys.executable,
            "-c",
            "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ),
        timeout_seconds=1,
        input_bytes=payload,
    )

    assert result.returncode == 0
    assert result.stdout == payload.decode("utf-8")
    assert not result.timed_out
    assert result.process_group_reaped


def test_ablation_acquires_each_stage_lane_and_enforces_zero_solver_cap(
    tmp_path: Path,
) -> None:
    bounded = runner.ResourceLimits(
        max_workers=1,
        case_timeout_seconds=1,
        max_memory_bytes=64 * 1024 * 1024,
        max_model_calls_per_case=2,
        max_solver_processes_per_case=1,
    )
    plan = runner.build_ablation_plan(
        "resource-lanes",
        (_case(),),
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=72,
        variant_ids=("A4",),
        cache_modes=(CacheMode.COLD,),
        limits=bounded,
        environment_sha256=SHA_ENVIRONMENT,
    )
    scheduler = ResourceScheduler(ResourcePolicy.from_resource_limits(bounded))
    execution = runner.execute_ablation(
        plan,
        _adapters(),
        output_root=tmp_path / "lanes",
        resume=False,
        resource_scheduler=scheduler,
    )

    assert execution.results[0].status is OutcomeStatus.NOT_VERIFIED
    assert tuple(
        item.resource_class for item in execution.resource_receipts
    ) == (
        ResourceClass.CPU,
        ResourceClass.CPU,
        ResourceClass.MODEL,
        ResourceClass.SOLVER,
        ResourceClass.MODEL,
        ResourceClass.KERNEL,
    )
    assert all(item.queue_delay_ms >= 0 for item in execution.resource_receipts)
    model_receipts = [
        item
        for item in execution.resource_receipts
        if item.resource_class is ResourceClass.MODEL
    ]
    assert [item.shared_model_instance for item in model_receipts] == [
        False,
        True,
    ]

    no_solver = runner.ResourceLimits(
        max_workers=1,
        case_timeout_seconds=0.05,
        max_memory_bytes=64 * 1024 * 1024,
        max_model_calls_per_case=2,
        max_solver_processes_per_case=0,
    )
    blocked_plan = runner.build_ablation_plan(
        "resource-no-solver",
        (_case("blocked-solver"),),
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=73,
        variant_ids=("A2",),
        cache_modes=(CacheMode.COLD,),
        limits=no_solver,
        environment_sha256=SHA_ENVIRONMENT,
    )
    blocked = runner.execute_ablation(
        blocked_plan,
        _adapters(),
        output_root=tmp_path / "blocked",
        resume=False,
    )
    assert blocked.results[0].status is OutcomeStatus.INFRASTRUCTURE_FAILURE
    assert (
        blocked.results[0].failure_code
        is FailureCode.RESOURCE_LEASE_CANCELLATION
    )
