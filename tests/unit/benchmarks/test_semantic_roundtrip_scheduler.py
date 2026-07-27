"""Focused contracts for semantic round-trip dynamic scheduling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmarks.bench_semantic_roundtrip_compositions as composition_report
import benchmarks.semantic_roundtrip_scheduler as scheduler_module
from benchmarks.semantic_roundtrip_scheduler import (
    DEFAULT_CONFIG_PATH,
    SRT014_REPORT_RELATIVE_PATH,
    SchedulerPreparationError,
    build_bundle_supervisor_command,
    build_taskboard_bundle_index,
    evaluate_srt014_downstream_gate,
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
    assert stored["srt014_downstream_gate"]["status"] == "pending"
    assert stored["srt014_downstream_gate"]["launch_authorized"] is False
    for task_id in ("SRT-015", "SRT-016", "SRT-017", "SRT-018", "SRT-019"):
        assert tasks_by_id[task_id]["is_schedulable"] is False
        assert tasks_by_id[task_id]["preflight_blocked"] is True


def _write_gate_report(repo_root: Path) -> Path:
    path = repo_root / SRT014_REPORT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    deterministic_ids = [f"arm-{index:02d}" for index in range(4)]
    model_ids = [f"arm-{index:02d}" for index in range(4, 30)]
    deterministic_records = []
    model_records = []
    for index, arm_id in enumerate([*deterministic_ids, *model_ids]):
        record = {
            "coordinate_key": f"case-{index % 5}:0:{arm_id}",
            "case_id": f"case-{index % 5}",
            "repeat_index": 0,
            "arm_id": arm_id,
            "status": "failed",
            "failure": {
                "code": "empty_l2" if index % 2 else "blank_t1",
                "stage": "realization" if index % 2 else "construction",
            },
            "gates": {
                "source_copy_exclusion": index % 3 != 0,
                "polarity_preservation": index % 3 != 1,
                "full_coverage": False,
                "selection_eligible": False,
            },
        }
        (
            deterministic_records
            if arm_id in deterministic_ids
            else model_records
        ).append(record)
    path.write_text(
        json.dumps(
            {
                "report_cid": "bafyreifakereport",
                "preregistration": {
                    "deterministic_cell_ids": deterministic_ids,
                    "model_backed_cell_ids": model_ids,
                },
                "execution": {
                    "deterministic": {"records": deterministic_records},
                    "model_backed": {"records": model_records},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("validated", "status", "authorized", "representative"),
    (
        (
            {
                "status": "valid",
                "report_cid": "bafyreifakereport",
                "selection_outcome": "selected",
                "winner_arm_id": "arm-07",
                "co_winner_arm_ids": ["arm-07"],
                "bounded_tie": False,
            },
            "authorized",
            True,
            "arm-07",
        ),
        (
            {
                "status": "valid",
                "report_cid": "bafyreifakereport",
                "selection_outcome": "exact_tie",
                "winner_arm_id": None,
                "co_winner_arm_ids": ["arm-19", "arm-03"],
                "bounded_tie": True,
            },
            "authorized",
            True,
            "arm-03",
        ),
        (
            {
                "status": "valid",
                "report_cid": "bafyreifakereport",
                "selection_outcome": "no_eligible_composition",
                "winner_arm_id": None,
                "co_winner_arm_ids": [],
                "bounded_tie": False,
            },
            "remediation_required",
            False,
            None,
        ),
    ),
)
def test_srt014_gate_handles_every_valid_selection_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validated: dict[str, object],
    status: str,
    authorized: bool,
    representative: str | None,
) -> None:
    _write_gate_report(tmp_path)
    fixture = (
        tmp_path / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
    )
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(
        composition_report,
        "validate_composition_report",
        lambda *_args, **_kwargs: validated,
    )

    gate = evaluate_srt014_downstream_gate(tmp_path)

    assert gate["status"] == status
    assert gate["launch_authorized"] is authorized
    assert gate["implementation_representative_arm_id"] == representative
    assert validate_cid(gate["gate_cid"], codecs=("dag-json",)) == gate["gate_cid"]
    if validated["selection_outcome"] == "exact_tie":
        assert gate["selection_basis"] == "srt015_bounded_tie_policy"
        assert gate["tie_bound"] == 30
    if validated["selection_outcome"] == "no_eligible_composition":
        remediation = gate["remediation"]
        assert remediation["classification"] == (
            "all_preregistered_arms_failed_selection_eligibility"
        )
        assert remediation["arm_count"] == 30
        assert remediation["eligible_arm_count"] == 0
        assert remediation["systemic_gate_ids"] == ["full_coverage"]
        assert remediation["terminal_failure_reason_counts"] == {
            "blank_t1": 15,
            "empty_l2": 15,
        }
        assert remediation["srt015_must_remain_fenced"] is True
        assert remediation["frozen_protocol_must_not_change"] is True
        assert remediation["recommended_task_inputs"][-1] == {
            "task_kind": "execute_replacement_full_matrix",
            "protocol_action": "preserve_frozen_protocol",
            "artifact_action": "new_immutable_run_namespace_and_report",
            "requires_all_prior_remediation_receipts": True,
        }


def test_invalid_or_unbounded_srt014_evidence_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gate_report(tmp_path)
    monkeypatch.setattr(
        composition_report,
        "validate_composition_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("forged co-winner set")
        ),
    )

    gate = evaluate_srt014_downstream_gate(tmp_path)

    assert gate["status"] == "invalid"
    assert gate["launch_authorized"] is False
    assert gate["selectable_arm_ids"] == []
    assert "srt014_report_validation_failed" in gate["reason_codes"]


def test_authorized_gate_keeps_srt015_and_descendants_schedulable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    gate = {
        "status": "authorized",
        "launch_authorized": True,
        "gate_cid": "bafyreiauthorized",
        "reason_codes": ["srt014_unique_full_coverage_winner"],
    }
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_srt014_downstream_gate",
        lambda _repo_root: gate,
    )

    index = build_taskboard_bundle_index(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD,
        bundle_index_path=tmp_path / "bundles" / "index.json",
        task_prefix=config["task_prefix"],
        provider_id=config["provider"]["provider_id"],
    )
    tasks_by_id = {
        task["task_id"]: task
        for bundle in index["bundles"].values()
        for task in bundle["tasks"]
    }

    for task_id in ("SRT-015", "SRT-016", "SRT-017", "SRT-018", "SRT-019"):
        assert tasks_by_id[task_id]["is_schedulable"] is True
        assert "preflight_blocked" not in tasks_by_id[task_id]
        assert tasks_by_id[task_id]["srt014_downstream_gate_cid"] == gate["gate_cid"]


def test_completed_srt014_cannot_make_srt015_claimable_without_report(
    tmp_path: Path,
) -> None:
    board = tmp_path / "gate.todo.md"
    board.write_text(
        """# Gate board

## SRT-014 Completed benchmark

- Status: completed
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json
- Validation: true
- Board namespace: gate-test
- Bundle: gate/benchmark
- Parallel lane: benchmark
- Resource class: cpu-small
- Predicted files: docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json
- Acceptance: terminal measurement

## SRT-015 Canonical design

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-014
- Outputs: canonical.txt
- Validation: test -f canonical.txt
- Board namespace: gate-test
- Bundle: gate/design
- Parallel lane: design
- Resource class: cpu-small
- Predicted files: canonical.txt
- Acceptance: consume only selectable evidence
""",
        encoding="utf-8",
    )
    index_path = tmp_path / "bundles" / "index.json"

    index = build_taskboard_bundle_index(
        repo_root=tmp_path,
        taskboard_path=board,
        bundle_index_path=index_path,
    )
    payloads = build_bundle_task_payloads(index_path)
    tasks = {
        task["task_id"]: task
        for bundle in index["bundles"].values()
        for task in bundle["tasks"]
    }

    assert index["srt014_downstream_gate"]["status"] == "pending"
    assert tasks["SRT-014"]["status"] == "completed"
    assert tasks["SRT-015"]["is_schedulable"] is False
    assert not any(
        "SRT-015" in payload["execution_slice_task_ids"]
        and payload["claimable"]
        for payload in payloads
    )


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
        if url.endswith("/slots"):
            return [{"id": 0, "is_processing": False}], 2
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
    assert provider["available_concurrency"] == 1
    assert provider["observed_slot_count"] == 1
    assert provider["slot_ids"] == [0]
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
        if url.endswith("/slots"):
            return [{"id": 0, "is_processing": False}], 1
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


def test_provider_probe_observes_busy_llama_cpp_slot() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]
    observed_timeouts: list[float] = []

    def fake_http_json(url: str, timeout: float):
        observed_timeouts.append(timeout)
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            return [{"id": 0, "is_processing": True, "id_task": 17}], 4
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "default_generation_settings": {"n_ctx": 8192},
            }, 2
        return {"data": [{"id": config["model_id"]}]}, 2

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert payload["probe_errors"] == []
    assert provider["healthy"] is True
    assert provider["active_requests"] == 1
    assert provider["available_concurrency"] == 0
    assert provider["observed_slot_count"] == 1
    assert observed_timeouts == [5.0, 5.0, 5.0, 5.0]


def test_provider_probe_reserves_capacity_when_slots_are_unavailable() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            raise TimeoutError("bounded slots timeout")
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "default_generation_settings": {"n_ctx": 8192},
            }, 1
        return {"data": [{"id": config["model_id"]}]}, 1

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert provider["healthy"] is False
    assert provider["active_requests"] == 1
    assert provider["available_concurrency"] == 0
    assert provider["observed_slot_count"] == -1
    assert any(
        error.startswith("slots_probe:TimeoutError:")
        for error in payload["probe_errors"]
    )


@pytest.mark.parametrize(
    "slots",
    (
        [{"id": 0}],
        [{"id": 0, "is_processing": "false"}],
        [],
    ),
)
def test_provider_probe_rejects_ambiguous_slot_occupancy(
    slots: object,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            return slots, 1
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "default_generation_settings": {"n_ctx": 8192},
            }, 1
        return {"data": [{"id": config["model_id"]}]}, 1

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert provider["healthy"] is False
    assert provider["active_requests"] == 1
    assert provider["available_concurrency"] == 0
    assert any(
        error.startswith("slots_probe:SchedulerPreparationError:")
        for error in payload["probe_errors"]
    )


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
    assert {
        "stage_concurrency",
        "provider_concurrency",
    } & set(schedule.decisions[1].reasons)


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
