"""EAAEF-132: privacy-safe analytical telemetry never grants authority."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.ducklake.external_agent_telemetry import (
    TELEMETRY_SCHEMA,
    TelemetryAuthorityError,
    TelemetryPrivacyError,
    TelemetryRecord,
    project_telemetry,
)


def test_project_identities_counts_and_durations() -> None:
    record = project_telemetry(
        {
            "run_id": "run-1",
            "task_id": "EAAEF-132",
            "fence_id": "fence-1",
            "attempt_id": "attempt-1",
            "counts": {"events": 4, "retries": 1},
            "durations": {"wall_ms": 12},
        }
    )
    assert isinstance(record, TelemetryRecord)
    assert TELEMETRY_SCHEMA.endswith("@1")
    assert record.as_mapping()["schema"] == TELEMETRY_SCHEMA
    assert record.run_id == "run-1"
    assert record.task_id == "EAAEF-132"
    assert record.fence_id == "fence-1"
    assert record.counts["events"] == 4
    assert record.durations["wall_ms"] == 12
    assert set(record.identities) <= {
        "run_id",
        "task_id",
        "attempt_id",
        "fence_id",
        "fence_token",
        "event_id",
        "artifact_cid",
        "epoch_id",
    }
    assert record.grants_current_authority is False
    payload = record.as_mapping()
    assert payload["grants_current_authority"] is False
    with pytest.raises(FrozenInstanceError):
        record.run_id = "mutated"  # type: ignore[misc]


def test_rejects_secrets_transcripts_and_hidden_thoughts() -> None:
    base = {
        "run_id": "run-1",
        "task_id": "EAAEF-132",
        "fence_id": "fence-1",
        "counts": {},
        "durations": {},
    }
    with pytest.raises(TelemetryPrivacyError, match="secret"):
        project_telemetry({**base, "api_key": "k"})
    with pytest.raises(TelemetryPrivacyError, match="transcript"):
        project_telemetry({**base, "transcript_body": "hello"})
    with pytest.raises(TelemetryPrivacyError, match="chain-of-thought"):
        project_telemetry({**base, "thinking": "hidden"})
    with pytest.raises(TelemetryPrivacyError, match="transcript"):
        project_telemetry({**base, "prompt": "raw prompt text"})


def test_telemetry_never_grants_authority() -> None:
    record = project_telemetry(
        {
            "run_id": "run-1",
            "task_id": "EAAEF-132",
            "fence_id": "fence-1",
            "counts": {"n": 1},
            "durations": {"ms": 2},
        }
    )
    for method in (
        record.grant_claim,
        record.grant_lease,
        record.grant_fence,
        record.grant_merge_authority,
    ):
        with pytest.raises(TelemetryAuthorityError, match="cannot"):
            method("task-1")
    with pytest.raises(TelemetryAuthorityError):
        project_telemetry(
            {
                "run_id": "run-1",
                "task_id": "EAAEF-132",
                "fence_id": "fence-1",
                "counts": {},
                "durations": {},
                "grants_current_authority": True,
            }
        )
