"""Focused contracts for semantic round-trip dynamic scheduling."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip_scheduler import (
    DEFAULT_CONFIG_PATH,
    SchedulerPreparationError,
    build_bundle_supervisor_command,
    build_taskboard_bundle_index,
    load_scheduler_config,
    probe_provider_capacity,
    validate_taskboard_for_dynamic_scheduler,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, validate_cid
from ipfs_accelerate_py.agent_supervisor.artifact_store import (
    read_bundle_index_artifact,
)
from ipfs_accelerate_py.agent_supervisor.resource_scheduler import (
    HostResourceSnapshot,
    LaneResourceRequirements,
    PROOF_RESOURCE_CLASSES,
    ResourcePolicy,
    ResourceScheduler,
)
from ipfs_accelerate_py.agent_supervisor.objective_graph import (
    build_bundle_task_payloads,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    parse_task_file,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TASKBOARD = (
    REPO_ROOT
    / "docs"
    / "implementation"
    / "plans"
    / "semantic_roundtrip_compiler.taskboard.todo.md"
)


def test_current_board_compiles_to_one_queryable_bundle_per_task(
    tmp_path: Path,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    index_path = tmp_path / "bundles" / "index.json"

    expected = build_taskboard_bundle_index(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD,
        bundle_index_path=index_path,
        task_prefix=config["task_prefix"],
        provider_id=config["provider"]["provider_id"],
    )
    stored = read_bundle_index_artifact(index_path)

    assert len(expected["bundles"]) == 20
    assert len(stored["bundles"]) == 20
    assert expected["source_todo_raw_cid"] == cid_for_bytes(TASKBOARD.read_bytes())
    assert (
        validate_cid(expected["source_todo_raw_cid"], codecs=("raw",))
        == expected["source_todo_raw_cid"]
    )
    assert index_path.with_suffix(".duckdb").is_file()
    assert all(
        bundle["shard_path"]
        == "docs/implementation/plans/semantic_roundtrip_compiler.taskboard.todo.md"
        for bundle in stored["bundles"].values()
    )

    model_tasks = [
        task
        for bundle in stored["bundles"].values()
        for task in bundle["tasks"]
        if task["resource_class"] == "llm-proof-draft"
    ]
    assert model_tasks
    assert all(task["resource_stage"] == "inference" for task in model_tasks)
    assert all(task["provider_id"] == "leanstral-local" for task in model_tasks)
    assert all(task["requires_provider"] is True for task in model_tasks)
    tasks_by_id = {
        task["task_id"]: task
        for bundle in stored["bundles"].values()
        for task in bundle["tasks"]
    }
    assert tasks_by_id["SRT-002"]["dependency_task_cids"] == [
        tasks_by_id["SRT-001"]["canonical_task_cid"]
    ]
    assert tasks_by_id["SRT-003"]["dependency_task_cids"] == [
        tasks_by_id["SRT-002"]["canonical_task_cid"]
    ]
    assert stored["task_dependency_graph"]["edges"]


def test_dependency_schedule_admits_the_second_wave_after_srt_002_and_srt_020(
    tmp_path: Path,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    index_path = tmp_path / "bundles" / "index.json"
    build_taskboard_bundle_index(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD,
        bundle_index_path=index_path,
        task_prefix=config["task_prefix"],
        provider_id=config["provider"]["provider_id"],
    )

    payloads = build_bundle_task_payloads(index_path)
    claimable_task_ids = {
        task_id
        for payload in payloads
        if payload["claimable"]
        for task_id in payload["execution_slice_task_ids"]
    }
    by_task_id = {
        task["task_id"]: (payload, task)
        for payload in payloads
        for task in payload["tasks"]
    }

    assert claimable_task_ids == {"SRT-003", "SRT-004", "SRT-005", "SRT-006"}
    assert by_task_id["SRT-002"][1]["status"] == "completed"
    assert by_task_id["SRT-020"][1]["status"] == "completed"
    assert by_task_id["SRT-002"][1]["claimable"] is False
    assert by_task_id["SRT-020"][1]["claimable"] is False
    assert by_task_id["SRT-003"][1]["blocking_task_cids"] == []
    assert by_task_id["SRT-007"][1]["claimable"] is False
    assert set(by_task_id["SRT-007"][1]["blocking_task_cids"]) == {
        by_task_id[task_id][1]["canonical_task_cid"]
        for task_id in ("SRT-003", "SRT-004", "SRT-005", "SRT-006")
    }


def test_custom_resource_class_is_rejected_before_index_write(
    tmp_path: Path,
) -> None:
    board = tmp_path / "invalid.todo.md"
    board.write_text(
        """# Board

## SRT-999 Invalid resource

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: result.txt
- Validation: test -f result.txt
- Board namespace: test
- Bundle: test/invalid
- Parallel lane: invalid
- Resource class: model-leanstral-one-slot
- Predicted files: result.txt
- Acceptance: rejected
""",
        encoding="utf-8",
    )

    tasks = parse_task_file(board, "## SRT-")
    with pytest.raises(SchedulerPreparationError, match="unsupported resource class"):
        validate_taskboard_for_dynamic_scheduler(tasks)


def test_provider_probe_binds_exact_model_and_one_slot() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 2
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "build_info": "test-build",
                "default_generation_settings": {"n_ctx": 8192},
            }, 3
        return {
            "data": [
                {
                    "id": config["model_id"],
                    "capabilities": ["completion"],
                    "meta": {"n_ctx": 8192},
                }
            ]
        }, 3

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert payload["probe_errors"] == []
    assert provider["healthy"] is True
    assert provider["max_concurrency"] == 1
    assert provider["active_requests"] == 0
    assert provider["model_ids"] == [config["model_id"]]
    assert provider["reported_total_slots"] == 1
    assert provider["context_window_tokens"] == 8192
    assert (
        validate_cid(payload["provider_capacity_cid"], codecs=("dag-json",))
        == payload["provider_capacity_cid"]
    )


def test_provider_probe_fails_closed_on_model_identity_mismatch() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": "different/model",
                "default_generation_settings": {"n_ctx": 8192},
            }, 1
        return {"data": [{"id": "different/model"}]}, 1

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert provider["healthy"] is False
    assert "configured_model_not_served" in payload["probe_errors"]
    assert "props_model_alias_mismatch" in payload["probe_errors"]
    assert provider["max_concurrency"] == 1


def test_resource_scheduler_admits_only_one_leanstral_lane() -> None:
    # The provider reservation layer must independently enforce the physical
    # slot. DynamicBundleScheduler adds an earlier adaptive inference-stage
    # ceiling from the same telemetry, which may report ``stage_concurrency``
    # before this provider-specific fallback is reached.
    scheduler = ResourceScheduler(ResourcePolicy(max_lanes=4))
    host = HostResourceSnapshot(
        observed_at_ms=1,
        cpu_percent=10,
        memory_percent=10,
        disk_percent=10,
        memory_available_bytes=8_000_000_000,
        disk_available_bytes=8_000_000_000,
        active_workers=0,
        worker_limit=4,
        available_worker_capacity=4,
        capabilities=("cpu",),
        resource_classes=PROOF_RESOURCE_CLASSES,
    )
    lanes = [
        LaneResourceRequirements(
            lane_id=f"model-{index}",
            stage="inference",
            resource_class="llm-proof-draft",
            provider_id="leanstral-local",
            requires_provider=True,
        )
        for index in (1, 2)
    ]

    schedule = scheduler.schedule(
        lanes,
        host=host,
        providers={
            "leanstral-local": {
                "healthy": True,
                "max_concurrency": 1,
                "active_requests": 0,
            }
        },
    )

    assert schedule.admitted_lane_ids == ("model-1",)
    assert schedule.decisions[0].admitted is True
    assert schedule.decisions[1].admitted is False
    assert "provider_concurrency" in schedule.decisions[1].reasons


def test_adaptive_inference_stage_uses_same_one_slot_ceiling() -> None:
    scheduler = ResourceScheduler(
        ResourcePolicy(max_lanes=4, adaptive_enabled=True)
    )
    host = HostResourceSnapshot(
        observed_at_ms=1,
        cpu_percent=10,
        memory_percent=10,
        disk_percent=10,
        memory_available_bytes=8_000_000_000,
        disk_available_bytes=8_000_000_000,
        active_workers=0,
        worker_limit=4,
        available_worker_capacity=4,
        capabilities=("cpu",),
        resource_classes=PROOF_RESOURCE_CLASSES,
    )
    lanes = [
        LaneResourceRequirements(
            lane_id=f"adaptive-model-{index}",
            stage="inference",
            resource_class="llm-proof-draft",
            provider_id="leanstral-local",
            requires_provider=True,
        )
        for index in (1, 2)
    ]

    schedule = scheduler.schedule(
        lanes,
        host=host,
        providers={
            "leanstral-local": {
                "healthy": True,
                "max_concurrency": 1,
                "active_requests": 0,
            }
        },
    )

    assert schedule.admitted_lane_ids == ("adaptive-model-1",)
    assert "stage_concurrency" in schedule.decisions[1].reasons


def test_launch_command_uses_dynamic_scheduler_without_unsafe_once(
    tmp_path: Path,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    preparation = {
        "repo_root": str(REPO_ROOT),
        "runtime_root": str(tmp_path),
        "bundle_index_path": str(tmp_path / "bundles" / "index.json"),
        "provider_capacity_path": str(tmp_path / "provider_capacity.json"),
    }

    command = build_bundle_supervisor_command(
        preparation,
        config,
        implement=True,
        max_lanes=4,
        start=True,
    )

    assert command[1:3] == [
        "-m",
        "ipfs_accelerate_py.agent_supervisor.bundle_supervisor",
    ]
    assert "--start" in command
    assert "--implement" in command
    assert "--provider-capacity-path" in command
    assert command[command.index("--max-lanes") + 1] == "4"
    assert command[command.index("--task-prefix") + 1] == "## SRT-"
    assert "--once" not in command
