"""External-gate retention for the datasets implementation supervisor."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ipfs_datasets_py.optimizers.todo_daemon.external_resolution import (
    OBSERVATION_FILENAME,
    RECEIPT_FILENAME,
    closed_lineage_match,
    correct_completion_claims,
    resolve_external_frontier,
    truncated_spent_phase,
    waiting_official_release,
)
from ipfs_datasets_py.optimizers.todo_daemon.implementation_daemon import PortalTaskState
from ipfs_datasets_py.optimizers.todo_daemon.implementation_supervisor import (
    PortalImplementationSupervisor,
    PortalSupervisorConfig,
)
from ipfs_datasets_py.optimizers.todo_daemon.supervisor_loop import SupervisorLoop
from ipfs_datasets_py.optimizers.todo_daemon.supervisor_runtime import SupervisedChild

_CONTRACTS = ["JLR-016", "JLR-017", "JLR-024", "JLR-035"]


def _attempt(content: str, *, sample_index: int | None = None) -> dict:
    attempt = {
        "status": "RETURNED",
        "http_status": 200,
        "candidate_error": "length",
        "response": {"choices": [{"finish_reason": "length", "message": {"content": content}}]},
    }
    if sample_index is not None:
        attempt["sample_index"] = sample_index
    return attempt


def _truncated(content: str = "the proof is still open") -> dict:
    return {
        "status": "NO_CONFIRMED_WINNER",
        "winner": None,
        "completion_authority": False,
        "proof_authority": False,
        "promoted": False,
        "full_campaign_complete": False,
        "local_inference_calls": 2,
        "limits": {"max_calls": 2},
        "attempts": [_attempt(content), _attempt(content + " more")],
    }


def _release() -> dict:
    return {
        "status": "WAITING_RELEASE",
        "reason": "official_full_cohort_file_unavailable",
        "model_calls": 0,
        "completion_authority": False,
        "proof_authority": False,
        "full_campaign_complete": False,
    }


def _lineage(contracts: list[str] | None = None, *, baseline: list[str] | None = None) -> dict:
    published = list(contracts or _CONTRACTS)
    return {
        "published_contracts": published,
        "baseline_contracts": list(baseline if baseline is not None else published),
    }


def _frontier() -> dict:
    return {
        "tasks": [
            {"task_id": "JLR-022", "status": "planned", "lineage": _lineage()},
            {"task_id": "JLR-024", "status": "pending", "phase_result": _truncated()},
            {"task_id": "JLR-035", "status": "pending", "phase_result": _release()},
        ],
        "blocked_task_ids": ["JLR-024", "JLR-035"],
        "dependency_ready": ["JLR-022"],
        "incidents": [
            {"kind": "gate_fixed_point", "task": "JLR-024"},
            {"kind": "planned_work_blocked_frontier", "task": "JLR-035"},
        ],
    }


def _supervisor(tmp_path: Path) -> PortalImplementationSupervisor:
    return PortalImplementationSupervisor(
        PortalSupervisorConfig(
            todo_path=tmp_path / "todo.md",
            state_path=tmp_path / "state.json",
            strategy_path=tmp_path / "strategy.json",
            events_path=tmp_path / "events.jsonl",
            state_dir=tmp_path,
            repo_root=tmp_path,
        )
    )


def _stale_state(path: Path, task_id: str = "JLR-024") -> None:
    PortalTaskState(
        heartbeat_at="2020-01-01T00:00:00+00:00",
        last_progress_at="2020-01-01T00:00:00+00:00",
        active_task_id=task_id,
        ready_count=1,
        ready_task_ids=[task_id],
    ).save(path)


def _events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_truncated_phase_is_retained_without_completion() -> None:
    receipt = resolve_external_frontier(
        {
            "tasks": [{"task_id": "JLR-024", "status": "pending", "phase_result": _truncated()}],
            "active_task_id": "JLR-024",
        }
    )

    assert receipt["retained"] is True
    assert receipt["reason"] == "truncated_phase_retained"
    assert receipt["completion_authority"] is False
    assert receipt["work_complete"] is False
    assert receipt["board_mutations"] == []
    assert receipt["provider_calls"] is False
    assert receipt["decisions"] == [
        {
            "task_id": "JLR-024",
            "status": "pending",
            "board_mutation": False,
            "completion_authority": False,
            "provider_calls": False,
            "action": "retain_truncated_phase",
            "reason": (
                "both bounded calls returned finish_reason length and no closed proof; "
                "retain the spent phase, do not spend another call, and do not grant completion"
            ),
        }
    ]


def test_closed_lineage_and_official_release_share_one_frontier() -> None:
    receipt = resolve_external_frontier(_frontier())
    actions = {item["task_id"]: item["action"] for item in receipt["decisions"]}

    assert receipt["retained"] is True
    assert receipt["reason"] == "retained_external_frontier"
    assert receipt["completion_authority"] is False
    assert receipt["work_complete"] is False
    assert actions == {
        "JLR-022": "retain_closed_lineage",
        "JLR-024": "retain_truncated_phase",
        "JLR-035": "retain_official_release",
    }


def test_drifted_contract_set_stays_reviewable() -> None:
    observation = _frontier()
    observation["tasks"][0]["lineage"] = _lineage(baseline=[*_CONTRACTS, "JLR-022"])
    receipt = resolve_external_frontier(observation)

    assert closed_lineage_match("JLR-022", observation["tasks"][0]["lineage"]) is False
    assert receipt["retained"] is False
    assert receipt["decisions"][0]["action"] == "review_execution_contract"
    assert receipt["decisions"][0]["completion_authority"] is False


def test_boolean_lineage_flag_is_not_enough() -> None:
    receipt = resolve_external_frontier(
        {
            "tasks": [{"task_id": "JLR-022", "status": "planned", "lineage": {"closed_lineage": True}}],
            "dependency_ready": ["JLR-022"],
        }
    )

    assert receipt["retained"] is False
    assert receipt["decisions"][0]["action"] == "review_execution_contract"


def test_completion_claim_on_the_release_stays_reviewable() -> None:
    observation = _frontier()
    observation["tasks"][2]["phase_result"]["completion_authority"] = True
    receipt = resolve_external_frontier(observation)

    assert waiting_official_release(observation["tasks"][2]["phase_result"]) is False
    assert receipt["retained"] is False
    assert receipt["completion_authority"] is False
    assert receipt["decisions"][2]["action"] == "review_open_task"


def test_closed_proof_text_is_not_a_truncated_phase() -> None:
    fenced = "```json\n{\"proof\": \"by exact\"}\n```"
    document = _truncated()
    document["attempts"][0]["response"]["choices"][0]["message"]["content"] = fenced

    assert truncated_spent_phase(document) is False
    assert truncated_spent_phase({**_truncated(), "limits": {"max_calls": True}}) is False
    sampled = _truncated()
    sampled["attempts"][1]["sample_index"] = 0
    assert truncated_spent_phase(sampled) is False


def test_release_reason_alone_is_not_retained() -> None:
    assert waiting_official_release({"reason": "official_full_cohort_file_unavailable"}) is False
    called = _release()
    called["model_calls"] = 1
    assert waiting_official_release(called) is False


def test_other_incident_keeps_the_frontier_reviewable() -> None:
    observation = _frontier()
    observation["incidents"].append({"kind": "worker_failed", "task": "JLR-024"})
    receipt = resolve_external_frontier(observation)

    assert receipt["retained"] is False
    assert receipt["completion_authority"] is False


def test_completion_claims_are_cleared_and_never_granted() -> None:
    document = {
        "completion_authority": True,
        "work_complete": True,
        "subgoals": [{"completion_authority": "yes"}],
        "board_mutations": [],
        "decisions": [
            {
                "action": "task_status_complete",
                "completion_authority": False,
                "board_mutation": False,
            }
        ],
    }
    corrected, count = correct_completion_claims(document)
    allowed, allowed_count = correct_completion_claims(
        {
            "completion_authority": False,
            "work_complete": True,
            "subgoals": [],
            "board_mutations": [],
            "decisions": [
                {
                    "action": "task_status_complete",
                    "completion_authority": False,
                    "board_mutation": False,
                }
            ],
        }
    )

    assert count == 3
    assert corrected["completion_authority"] is False
    assert corrected["work_complete"] is False
    assert corrected["subgoals"][0]["completion_authority"] is False
    assert allowed_count == 0
    assert allowed["work_complete"] is True
    assert "completion_authority" not in correct_completion_claims({"status": "pending"})[0]


def test_supervisor_retains_a_stale_external_frontier_without_recycling(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    _stale_state(supervisor.config.state_path)
    observation_path = tmp_path / OBSERVATION_FILENAME
    observation = _frontier()
    observation_path.write_text(json.dumps(observation), encoding="utf-8")
    before = observation_path.read_bytes()

    first = supervisor.run_once()
    second = supervisor.run_once()
    receipt = json.loads((tmp_path / RECEIPT_FILENAME).read_text(encoding="utf-8"))
    kinds = [item["type"] for item in _events(supervisor.config.events_path)]

    assert first["stuck"] is False
    assert first["retained"] is True
    assert first["reason"] == "retained_external_frontier"
    assert first["completion_authority"] is False
    assert first["work_complete"] is False
    assert second == first
    assert receipt["retained"] is True
    assert receipt["completion_authority"] is False
    assert receipt["board_mutations"] == []
    assert receipt["provider_calls"] is False
    assert not supervisor.config.strategy_path.exists()
    assert observation_path.read_bytes() == before
    assert kinds.count("external_resolution") == 1


def test_supervisor_still_recycles_a_reviewable_claim(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    _stale_state(supervisor.config.state_path)
    observation = _frontier()
    observation["tasks"][2]["phase_result"]["completion_authority"] = True
    observation_path = tmp_path / OBSERVATION_FILENAME
    observation_path.write_text(json.dumps(observation), encoding="utf-8")

    result = supervisor.run_once()
    receipt = json.loads((tmp_path / RECEIPT_FILENAME).read_text(encoding="utf-8"))

    assert result["stuck"] is True
    assert "heartbeat stale" in result["reason"]
    assert result["completion_authority"] is False
    assert receipt["retained"] is False
    assert supervisor.config.strategy_path.exists()
    assert json.loads(observation_path.read_text(encoding="utf-8"))["tasks"][2]["phase_result"][
        "completion_authority"
    ] is True


def test_log_stall_and_merge_failure_stay_stuck(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    log_path = tmp_path / "implementation.log"
    log_path.write_text("started\n", encoding="utf-8")
    os.utime(log_path, (time.time() - 900, time.time() - 900))
    PortalTaskState(
        heartbeat_at="2020-01-01T00:00:00+00:00",
        last_progress_at="2020-01-01T00:00:00+00:00",
        active_task_id="JLR-024",
        ready_count=1,
        implementation_in_progress=True,
        active_log_path=str(log_path),
    ).save(supervisor.config.state_path)
    (tmp_path / OBSERVATION_FILENAME).write_text(json.dumps(_frontier()), encoding="utf-8")

    stalled = supervisor.run_once()

    assert stalled["stuck"] is True
    assert "implementation log stalled" in stalled["reason"]
    assert supervisor.config.strategy_path.exists()

    supervisor.config.strategy_path.unlink()
    PortalTaskState(
        heartbeat_at="2020-01-01T00:00:00+00:00",
        last_progress_at="2020-01-01T00:00:00+00:00",
        active_task_id="JLR-024",
        ready_count=1,
        last_implementation_task_id="JLR-024",
        last_implementation_commit="abc",
        last_merge_returncode=1,
        last_merge_error="conflict",
    ).save(supervisor.config.state_path)

    merged = supervisor.run_once()

    assert merged["stuck"] is True
    assert "unresolved merge failure" in merged["reason"]


def test_symlink_observation_and_receipt_are_left_untouched(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    _stale_state(supervisor.config.state_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    observation_target = outside / "observation.json"
    receipt_target = outside / "receipt.json"
    observation_target.write_text(json.dumps(_frontier()), encoding="utf-8")
    receipt_target.write_text(
        json.dumps({"completion_authority": True, "work_complete": True}),
        encoding="utf-8",
    )
    os.symlink(observation_target, tmp_path / OBSERVATION_FILENAME)
    os.symlink(receipt_target, tmp_path / RECEIPT_FILENAME)

    result = supervisor.run_once()

    assert result["stuck"] is True
    assert json.loads(observation_target.read_text(encoding="utf-8"))["tasks"][0]["task_id"] == "JLR-022"
    assert json.loads(receipt_target.read_text(encoding="utf-8"))["completion_authority"] is True
    assert supervisor.config.strategy_path.exists()


def _child(tmp_path: Path) -> SupervisedChild:
    return SupervisedChild(
        pid=1,
        command=("python",),
        log_path=tmp_path / "child.log",
        child_pid_path=tmp_path / "child.pid",
    )


def _loop(supervisor: PortalImplementationSupervisor) -> SupervisorLoop:
    return SupervisorLoop(
        supervisor.build_supervisor_loop_config(),
        watchdog_hook=supervisor._supervisor_loop_watchdog_decision,
        external_frontier_preempt=supervisor._external_frontier_preempt,
    )


def test_forever_loop_keeps_a_stale_retained_frontier(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.config.until_complete = True
    state = PortalTaskState(
        heartbeat_at="2020-01-01T00:00:00+00:00",
        last_progress_at="2020-01-01T00:00:00+00:00",
        active_task_id="JLR-024",
        ready_count=1,
        ready_task_ids=["JLR-024"],
        task_count=3,
        completed_count=3,
    )
    state.save(supervisor.config.state_path)
    (tmp_path / OBSERVATION_FILENAME).write_text(json.dumps(_frontier()), encoding="utf-8")

    once = supervisor.run_once()
    decision = _loop(supervisor).watchdog_decision(_child(tmp_path))

    assert once["retained"] is True
    assert once["reason"] == "retained_external_frontier"
    assert once["completion_authority"] is False
    assert once["work_complete"] is False
    assert "complete" not in once
    assert decision.action == "continue"
    assert decision.reason == "retained_external_frontier"
    assert decision.detail["external_frontier_retained"] is True
    assert decision.detail["completion_authority"] is False
    assert decision.detail["work_complete"] is False
    assert not supervisor.config.strategy_path.exists()


def test_forever_loop_still_recycles_a_stale_reviewable_heartbeat(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    _stale_state(supervisor.config.state_path)
    decision = _loop(supervisor).watchdog_decision(_child(tmp_path))

    assert decision.action == "recycle"
    assert decision.reason == "stale_heartbeat"
    assert not supervisor.config.strategy_path.exists()


def test_forever_loop_still_recycles_a_log_stall_on_a_retained_frontier(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    log_path = tmp_path / "implementation.log"
    log_path.write_text("started\n", encoding="utf-8")
    os.utime(log_path, (time.time() - 900, time.time() - 900))
    now = datetime.now(timezone.utc).isoformat()
    PortalTaskState(
        heartbeat_at=now,
        last_progress_at=now,
        active_task_id="JLR-024",
        ready_count=1,
        implementation_in_progress=True,
        active_log_path=str(log_path),
    ).save(supervisor.config.state_path)
    (tmp_path / OBSERVATION_FILENAME).write_text(json.dumps(_frontier()), encoding="utf-8")

    decision = _loop(supervisor).watchdog_decision(_child(tmp_path))

    assert decision.action == "recycle"
    assert "implementation log stalled" in decision.reason
    assert decision.detail.get("external_frontier_retained") is not True
    assert supervisor.config.strategy_path.exists()


def test_owned_phase_files_are_retained_without_a_hand_written_observation(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    _stale_state(supervisor.config.state_path)
    phase_dir = tmp_path / "external_phases"
    phase_dir.mkdir()
    (phase_dir / "JLR-022.json").write_text(
        json.dumps({"task_id": "JLR-022", "status": "planned", "lineage": _lineage()}),
        encoding="utf-8",
    )
    (phase_dir / "JLR-024.json").write_text(
        json.dumps({"task_id": "JLR-024", "status": "pending", "phase_result": _truncated()}),
        encoding="utf-8",
    )
    (phase_dir / "JLR-035.json").write_text(
        json.dumps({"task_id": "JLR-035", "status": "pending", "phase_result": _release()}),
        encoding="utf-8",
    )

    result = supervisor.run_once()
    receipt = json.loads((tmp_path / RECEIPT_FILENAME).read_text(encoding="utf-8"))

    assert result["retained"] is True
    assert result["reason"] == "retained_external_frontier"
    assert result["completion_authority"] is False
    assert result["work_complete"] is False
    assert receipt["completion_authority"] is False
    assert receipt["provider_calls"] is False
    assert not (tmp_path / OBSERVATION_FILENAME).exists()
    assert not supervisor.config.strategy_path.exists()


def test_a_reviewable_phase_file_keeps_the_frontier_open(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    _stale_state(supervisor.config.state_path)
    phase_dir = tmp_path / "external_phases"
    phase_dir.mkdir()
    (phase_dir / "JLR-024.json").write_text(
        json.dumps({"task_id": "JLR-024", "status": "pending", "phase_result": _truncated()}),
        encoding="utf-8",
    )
    (phase_dir / "JLR-099.json").write_text(
        json.dumps({"status": "completed", "completion_authority": True}),
        encoding="utf-8",
    )

    result = supervisor.run_once()
    receipt = json.loads((tmp_path / RECEIPT_FILENAME).read_text(encoding="utf-8"))

    assert result["stuck"] is True
    assert receipt["retained"] is False
    assert receipt["work_complete"] is False
    assert receipt["completion_authority"] is False


def test_daemon_records_one_external_phase_without_completing_the_task(tmp_path: Path) -> None:
    from ipfs_datasets_py.optimizers.todo_daemon.implementation_daemon import (
        PortalImplementationDaemon,
        PortalTask,
    )

    daemon = PortalImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
    )
    log_dir = tmp_path / "implementation_logs"
    log_dir.mkdir()
    phase = _truncated()
    phase["task_id"] = "JLR-024"
    log_path = log_dir / "jlr-024-attempt-1.log"
    log_path.write_text("EXTERNAL_PHASE " + json.dumps(phase) + "\n", encoding="utf-8")
    task = PortalTask(
        task_id="JLR-024",
        title="spent phase",
        status="ready",
        completion="manual",
        priority="P2",
        track="ops",
    )

    code = daemon._apply_external_phase(task, log_path, 0)
    stored = json.loads((tmp_path / "external_phases" / "JLR-024.json").read_text(encoding="utf-8"))

    assert code == 75
    assert stored["completion_authority"] is False
    assert stored["status"] == "pending"
    assert daemon._owned_external_phase("JLR-024")["task_id"] == "JLR-024"

    claimed = dict(phase)
    claimed["completion_authority"] = True
    claim_log = log_dir / "claim.log"
    claim_log.write_text("EXTERNAL_PHASE " + json.dumps(claimed) + "\n", encoding="utf-8")
    claim_task = PortalTask(
        task_id="JLR-099",
        title="claim",
        status="ready",
        completion="manual",
        priority="P2",
        track="ops",
    )
    assert daemon._apply_external_phase(claim_task, claim_log, 0) == 0
    assert not (tmp_path / "external_phases" / "JLR-099.json").exists()

    outside = tmp_path / "outside.log"
    outside.write_text("EXTERNAL_PHASE " + json.dumps(phase) + "\n", encoding="utf-8")
    assert daemon._apply_external_phase(task, outside, 0) == 0

    doubled = log_dir / "doubled.log"
    doubled.write_text(
        "EXTERNAL_PHASE " + json.dumps(phase) + "\nEXTERNAL_PHASE " + json.dumps(phase) + "\n",
        encoding="utf-8",
    )
    assert daemon._capture_external_phase(task, doubled) is None


def test_existing_receipt_claim_is_cleared_without_an_observation(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    PortalTaskState().save(supervisor.config.state_path)
    receipt_path = tmp_path / RECEIPT_FILENAME
    receipt_path.write_text(
        json.dumps(
            {
                "completion_authority": True,
                "work_complete": True,
                "subgoals": [{"name": "still open"}],
                "board_mutations": [],
                "decisions": [],
            }
        ),
        encoding="utf-8",
    )

    result = supervisor.run_once()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["stuck"] is False
    assert "retained" not in result
    assert receipt["completion_authority"] is False
    assert receipt["work_complete"] is False
    assert [item["type"] for item in _events(supervisor.config.events_path)] == [
        "completion_claim_cleared",
        "supervisor_check",
    ]
