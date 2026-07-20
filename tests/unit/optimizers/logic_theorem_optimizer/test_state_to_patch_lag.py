"""Regression tests for correlated state-to-compiler-patch lag accounting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ipfs_datasets_py.logic.modal.introspection_metrics import (
    STATE_TO_COMPILER_PATCH_LIFECYCLE_SCHEMA_VERSION,
    IntrospectionMetricSchemaError,
    StateToCompilerPatchLifecycle,
    StateToCompilerPatchMilestone,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_reporting import (
    STATE_TO_COMPILER_PATCH_LAG_REPORT_SCHEMA_VERSION,
    build_modal_supervisor_health_report,
    state_to_compiler_patch_lag,
)


STAGES = (
    "state_snapshot",
    "audit",
    "todo",
    "claimed_worktree",
    "validated_patch",
    "merged_commit",
    "observed_next_cycle",
)


def _timestamp(base: datetime, seconds: int) -> str:
    return (base + timedelta(seconds=seconds)).isoformat()


def _path(
    path_id: str,
    *,
    base: datetime,
    offsets: tuple[int, ...],
    cycles: tuple[int, ...],
) -> dict:
    payload = {
        "schema_version": STATE_TO_COMPILER_PATCH_LIFECYCLE_SCHEMA_VERSION,
        "path_id": path_id,
    }
    for index, stage in enumerate(STAGES):
        if index >= len(offsets):
            payload[stage] = None
            continue
        payload[stage] = {
            "timestamp": _timestamp(base, offsets[index]),
            "cycle_id": cycles[index],
            "version_id": f"{path_id}-{stage}-v1",
        }
    return payload


def test_lifecycle_round_trip_preserves_explicit_timestamps_cycles_and_versions() -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    raw = _path(
        "path-complete",
        base=base,
        offsets=(0, 10, 20, 30, 40, 50, 70),
        cycles=(4, 4, 4, 4, 4, 4, 5),
    )

    lifecycle = StateToCompilerPatchLifecycle.from_mapping(raw)
    restored = StateToCompilerPatchLifecycle.from_mapping(lifecycle.to_dict())

    assert restored == lifecycle
    assert restored.complete is True
    assert restored.censored is False
    assert restored.censored_at_stage is None
    assert restored.state_snapshot.timestamp == "2026-07-20T00:00:00+00:00"
    assert restored.merged_commit is not None
    assert restored.merged_commit.version_id == "path-complete-merged_commit-v1"
    assert restored.observed_next_cycle is not None
    assert restored.observed_next_cycle.cycle_id == 5


def test_lifecycle_accepts_event_records_and_marks_first_missing_stage_censored() -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    raw = {
        "path_id": "path-events",
        "events": [
            {
                "stage": stage,
                "timestamp_utc": _timestamp(base, index * 5),
                "cycle": 9,
                "version_id": f"event-{index}",
            }
            for index, stage in enumerate(STAGES[:3])
        ],
    }

    lifecycle = StateToCompilerPatchLifecycle.from_mapping(raw)

    assert lifecycle.complete is False
    assert lifecycle.censored is True
    assert lifecycle.censored_at_stage == "claimed_worktree"
    assert lifecycle.to_dict()["claimed_worktree"] is None


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda raw: raw["audit"].update(
                timestamp="2026-07-19T23:59:59+00:00"
            ),
            "precedes",
        ),
        (
            lambda raw: raw["audit"].update(cycle_id=3),
            "precedes",
        ),
        (
            lambda raw: raw["observed_next_cycle"].update(cycle_id=4),
            "must be later",
        ),
        (
            lambda raw: raw["state_snapshot"].update(
                timestamp="2026-07-20T00:00:00"
            ),
            "UTC offset",
        ),
        (
            lambda raw: raw.update(todo=None),
            "present after missing",
        ),
    ],
)
def test_lifecycle_rejects_unordered_ambiguous_or_noncontiguous_evidence(
    mutate, message: str
) -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    raw = _path(
        "path-invalid",
        base=base,
        offsets=(0, 10, 20, 30, 40, 50, 70),
        cycles=(4, 4, 4, 4, 4, 4, 5),
    )
    mutate(raw)

    with pytest.raises(IntrospectionMetricSchemaError, match=message):
        StateToCompilerPatchLifecycle.from_mapping(raw)


def test_report_computes_completed_wall_clock_cycle_and_queue_stage_percentiles() -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    paths = [
        _path(
            "fast",
            base=base,
            offsets=(0, 60, 120, 180, 300, 420, 600),
            cycles=(10, 10, 10, 10, 11, 11, 12),
        ),
        _path(
            "slow",
            base=base,
            offsets=(0, 120, 240, 360, 600, 840, 1200),
            cycles=(20, 20, 21, 21, 22, 22, 24),
        ),
        _path(
            "waiting",
            base=base,
            offsets=(0, 30, 90),
            cycles=(30, 30, 30),
        ),
    ]

    report = state_to_compiler_patch_lag(
        {"state_to_compiler_patch_paths": paths}
    )

    assert report["schema_version"] == STATE_TO_COMPILER_PATCH_LAG_REPORT_SCHEMA_VERSION
    assert report["status"] == "censored"
    assert report["path_count"] == 3
    assert report["valid_path_count"] == 3
    assert report["complete_path_count"] == 2
    assert report["censored_path_count"] == 1
    assert report["completion_rate"] == pytest.approx(2 / 3)

    wall_clock = report["wall_clock_lag_seconds"]
    assert wall_clock == {
        "unit": "seconds",
        "observed_count": 2,
        "censored_count": 1,
        "sample_count": 3,
        "minimum": 600.0,
        "p50": 900.0,
        "p90": 1140.0,
        "p95": 1170.0,
        "p99": 1194.0,
        "maximum": 1200.0,
    }
    cycle_lag = report["cycle_lag"]
    assert cycle_lag["observed_count"] == 2
    assert cycle_lag["censored_count"] == 1
    assert cycle_lag["p50"] == 3.0
    assert cycle_lag["p95"] == 3.9

    snapshot_to_audit = report["queue_stage_lag_seconds"][
        "state_snapshot_to_audit"
    ]
    assert snapshot_to_audit["observed_count"] == 3
    assert snapshot_to_audit["p50"] == 60.0
    claim_wait = report["queue_stage_lag_seconds"]["todo_to_claimed_worktree"]
    assert claim_wait["observed_count"] == 2
    assert claim_wait["censored_count"] == 1
    assert report["censored_by_stage"]["claimed_worktree"] == 1

    assert report["version_paths"][0]["versions"]["state_snapshot"] == (
        "fast-state_snapshot-v1"
    )
    assert report["version_paths"][2]["versions"]["merged_commit"] is None


def test_incomplete_path_has_no_fabricated_end_to_end_numeric_lag() -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    waiting = _path(
        "waiting",
        base=base,
        offsets=(0, 30, 60, 90),
        cycles=(7, 7, 7, 7),
    )

    report = state_to_compiler_patch_lag(lifecycle_paths=[waiting])

    assert report["complete_path_count"] == 0
    assert report["censored_path_count"] == 1
    assert report["wall_clock_lag_seconds"]["observed_count"] == 0
    assert report["wall_clock_lag_seconds"]["censored_count"] == 1
    assert report["wall_clock_lag_seconds"]["minimum"] is None
    assert report["wall_clock_lag_seconds"]["p50"] is None
    assert report["wall_clock_lag_seconds"]["maximum"] is None
    assert report["cycle_lag"]["p95"] is None
    assert "lag" not in report


def test_incompatible_legacy_counters_are_ignored_instead_of_subtracted() -> None:
    report = state_to_compiler_patch_lag(
        {
            "latest_autoencoder_state_telemetry": {
                "applied_todo_count": 21,
                "generalizable_entry_count": 8,
            },
            "program_synthesis_completed_count": 4,
            "latest_queue_counts": {"completed": 99},
        },
        state_update_count=100,
        compiler_patch_count=2,
    )

    assert report["status"] == "no_data"
    assert report["path_count"] == 0
    assert report["legacy_counter_inputs_ignored"] is True
    assert report["wall_clock_lag_seconds"]["p50"] is None
    assert report["cycle_lag"]["p50"] is None
    assert "state_update_count" not in report
    assert "compiler_patch_count" not in report
    assert "lag" not in report


def test_invalid_paths_fail_closed_and_are_counted_as_censored() -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    valid = _path(
        "duplicate",
        base=base,
        offsets=(0, 10, 20, 30, 40, 50, 70),
        cycles=(1, 1, 1, 1, 1, 1, 2),
    )
    malformed = {"path_id": "missing-snapshot", "audit": valid["audit"]}

    report = state_to_compiler_patch_lag(
        lifecycle_paths=[valid, valid, malformed, "not-a-record"]
    )

    assert report["path_count"] == 4
    assert report["valid_path_count"] == 1
    assert report["complete_path_count"] == 1
    assert report["invalid_path_count"] == 3
    assert report["censored_path_count"] == 3
    assert report["wall_clock_lag_seconds"]["observed_count"] == 1
    assert report["wall_clock_lag_seconds"]["censored_count"] == 3
    assert len(report["invalid_paths"]) == 3


def test_supervisor_health_report_embeds_correlated_lag_report() -> None:
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    path = _path(
        "health",
        base=base,
        offsets=(0, 10, 20, 30, 40, 50, 70),
        cycles=(1, 1, 1, 1, 1, 1, 2),
    )

    health = build_modal_supervisor_health_report(
        {
            "cycles": 2,
            "state_to_compiler_patch_lifecycles": [path],
        }
    ).to_dict()

    lag = health["state_to_compiler_patch_lag"]
    assert lag["status"] == "complete"
    assert lag["wall_clock_lag_seconds"]["p50"] == 70.0
    assert lag["cycle_lag"]["p50"] == 1.0


def test_milestone_rejects_empty_version_and_negative_cycle() -> None:
    with pytest.raises(IntrospectionMetricSchemaError, match="version_id"):
        StateToCompilerPatchMilestone(
            timestamp="2026-07-20T00:00:00Z",
            cycle_id=0,
            version_id="",
        )
    with pytest.raises(IntrospectionMetricSchemaError, match="cycle_id"):
        StateToCompilerPatchMilestone(
            timestamp="2026-07-20T00:00:00Z",
            cycle_id=-1,
            version_id="state-v1",
        )
