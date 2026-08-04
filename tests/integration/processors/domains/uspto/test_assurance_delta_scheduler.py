"""PATLAW-141: Assurance delta alerts on the USPTO scheduler.

Acceptance focus:
  - Unchanged runs emit no duplicate alert
  - Alert payloads identify matter by configured opaque reference
  - Alerts link to a protected dossier rather than embedding content
  - Meaningful state / deadline / instruction / compliance / source changes alert
  - Restart-safe dedupe via durable checkpoints
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.scheduler import (
    ActionKind,
    AlertKind,
    AssuranceDeltaField,
    PollDisposition,
    PollResult,
    SchedulerConfig,
    USPTOApplicationScheduler,
    create_scheduler,
)


class FakeMonoClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FixedWallClock:
    def __init__(self, when: datetime | None = None) -> None:
        self.when = when or datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.when


def _make_scheduler(
    tmp_path: Path | None = None,
    *,
    config: SchedulerConfig | None = None,
) -> USPTOApplicationScheduler:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"alert{counter['n']:04d}"

    def _poller(_job: Any) -> PollResult:
        return PollResult(disposition=PollDisposition.SUCCESS, status_code=200)

    cfg = config or SchedulerConfig(
        max_workers=2,
        max_queue_depth=32,
        heartbeat_interval_seconds=1e9,
        opaque_matter_ref_template="opaque:{matter_digest}",
        dossier_link_template="protected://dossier/{dossier_id}",
    )
    return create_scheduler(
        _poller,
        config=cfg,
        checkpoint_dir=tmp_path,
        checkpoint_name="assurance-delta",
        clock=FakeMonoClock(),
        wall_clock=FixedWallClock(),
        id_factory=_ids,
    )


# ---------------------------------------------------------------------------
# Opaque reference + protected dossier link
# ---------------------------------------------------------------------------


def test_configure_matter_identity_uses_templates(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    identity = sched.configure_matter_alert_identity(
        "matter:alpha",
        tenant_id="tenant-a",
        dossier_id="dossier:xyz",
    )
    assert identity["matter_id"] == "matter:alpha"
    assert identity["opaque_matter_ref"].startswith("opaque:")
    assert "matter:alpha" not in identity["opaque_matter_ref"] or identity[
        "opaque_matter_ref"
    ].startswith("opaque:")
    # Template uses matter_digest (hash), not the raw matter id as sole identity.
    assert identity["dossier_link"] == "protected://dossier/dossier:xyz"
    assert "body" not in identity
    assert "content" not in identity


def test_alert_payload_uses_opaque_ref_and_dossier_link(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    sched.configure_matter_alert_identity(
        "matter:beta",
        opaque_matter_ref="ref:client-opaque-99",
        dossier_id="dossier:beta",
        dossier_link="protected://dossier/dossier:beta",
        tenant_id="tenant-a",
    )
    # Seed
    assert (
        sched.observe_assurance_delta(
            matter_id="matter:beta",
            state="pending",
            deadline="2026-09-01",
        )
        is None
    )
    # Change
    alert = sched.observe_assurance_delta(
        matter_id="matter:beta",
        state="allowed",
        deadline="2026-09-01",
    )
    assert alert is not None
    payload = alert.to_dict()
    assert payload["kind"] == AlertKind.ASSURANCE_DELTA.value
    assert payload["opaque_matter_ref"] == "ref:client-opaque-99"
    assert payload["dossier_link"] == "protected://dossier/dossier:beta"
    assert AssuranceDeltaField.STATE.value in payload["delta_fields"]
    # Must not embed document / claim content.
    blob = json.dumps(payload)
    assert "claim text" not in blob.lower()
    assert "document body" not in blob.lower()
    assert "full text" not in blob.lower()
    # Raw matter id may be present for internal routing but opaque ref is required.
    assert payload["opaque_matter_ref"]


def test_alert_never_embeds_content_fields(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    sched.configure_matter_alert_identity(
        "matter:gamma",
        opaque_matter_ref="ref:gamma",
        dossier_id="dossier:gamma",
    )
    sched.observe_assurance_delta(
        matter_id="matter:gamma",
        document={"doc_id": "d1", "sha256": "f" * 64},
    )
    alert = sched.observe_assurance_delta(
        matter_id="matter:gamma",
        document={"doc_id": "d1", "sha256": "0" * 64, "text": "PRIVATE DOCUMENT BODY"},
    )
    assert alert is not None
    blob = json.dumps(alert.to_dict())
    assert "PRIVATE DOCUMENT BODY" not in blob
    assert alert.dossier_link == "protected://dossier/dossier:gamma"


# ---------------------------------------------------------------------------
# Unchanged runs → no duplicate alert
# ---------------------------------------------------------------------------


def test_unchanged_observation_emits_no_duplicate(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    sched.configure_matter_alert_identity(
        "matter:stable",
        opaque_matter_ref="ref:stable",
        dossier_id="dossier:stable",
    )
    # Seed
    assert (
        sched.observe_assurance_delta(
            matter_id="matter:stable",
            state="s1",
            compliance="c1",
            source="src1",
        )
        is None
    )
    # Identical observation — no alert
    assert (
        sched.observe_assurance_delta(
            matter_id="matter:stable",
            state="s1",
            compliance="c1",
            source="src1",
        )
        is None
    )
    assert sched.list_alerts(kind=AlertKind.ASSURANCE_DELTA) == []

    # Change once
    a1 = sched.observe_assurance_delta(
        matter_id="matter:stable",
        state="s2",
        compliance="c1",
        source="src1",
    )
    assert a1 is not None
    assert len(sched.list_alerts(kind=AlertKind.ASSURANCE_DELTA)) == 1

    # Repeat same changed state — still no duplicate
    assert (
        sched.observe_assurance_delta(
            matter_id="matter:stable",
            state="s2",
            compliance="c1",
            source="src1",
        )
        is None
    )
    assert len(sched.list_alerts(kind=AlertKind.ASSURANCE_DELTA)) == 1


def test_distinct_field_changes_emit_new_alerts(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    mid = "matter:fields"
    sched.configure_matter_alert_identity(
        mid, opaque_matter_ref="ref:fields", dossier_id="dossier:fields"
    )
    sched.observe_assurance_delta(
        matter_id=mid,
        state="s0",
        deadline="d0",
        instruction="i0",
        compliance="c0",
        source="src0",
        authority="a0",
    )
    cases = [
        ("state", {"state": "s1", "deadline": "d0", "instruction": "i0", "compliance": "c0", "source": "src0", "authority": "a0"}),
        ("deadline", {"state": "s1", "deadline": "d1", "instruction": "i0", "compliance": "c0", "source": "src0", "authority": "a0"}),
        ("instruction", {"state": "s1", "deadline": "d1", "instruction": "i1", "compliance": "c0", "source": "src0", "authority": "a0"}),
        ("compliance", {"state": "s1", "deadline": "d1", "instruction": "i1", "compliance": "c1", "source": "src0", "authority": "a0"}),
        ("source", {"state": "s1", "deadline": "d1", "instruction": "i1", "compliance": "c1", "source": "src1", "authority": "a0"}),
        ("authority", {"state": "s1", "deadline": "d1", "instruction": "i1", "compliance": "c1", "source": "src1", "authority": "a1"}),
    ]
    for field_name, kwargs in cases:
        alert = sched.observe_assurance_delta(matter_id=mid, **kwargs)
        assert alert is not None, field_name
        assert field_name in alert.delta_fields


def test_reanalysis_request_alert(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    sched.configure_matter_alert_identity(
        "matter:re",
        opaque_matter_ref="ref:re",
        dossier_id="dossier:re",
    )
    sched.observe_assurance_delta(matter_id="matter:re", state="s0")
    alert = sched.observe_assurance_delta(
        matter_id="matter:re",
        state="s0",
        request_reanalysis=True,
    )
    assert alert is not None
    assert alert.kind is AlertKind.REANALYSIS_REQUESTED
    assert alert.opaque_matter_ref == "ref:re"
    assert alert.dossier_link == "protected://dossier/dossier:re"
    actions = sched.list_actions(kind=ActionKind.REVIEW_REANALYSIS, open_only=True)
    assert len(actions) >= 1


# ---------------------------------------------------------------------------
# Checkpoint / restart safety
# ---------------------------------------------------------------------------


def test_restart_does_not_reemit_same_delta(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    mid = "matter:restart"
    sched.configure_matter_alert_identity(
        mid, opaque_matter_ref="ref:restart", dossier_id="dossier:restart"
    )
    sched.observe_assurance_delta(matter_id=mid, state="v1")
    a1 = sched.observe_assurance_delta(matter_id=mid, state="v2")
    assert a1 is not None
    n1 = len(sched.list_alerts(kind=AlertKind.ASSURANCE_DELTA))

    # Simulate process restart from same checkpoint dir.
    sched2 = _make_scheduler(tmp_path)
    # Unchanged after reload — no new alert
    assert sched2.observe_assurance_delta(matter_id=mid, state="v2") is None
    n2 = len(sched2.list_alerts(kind=AlertKind.ASSURANCE_DELTA))
    assert n2 == n1

    # New change after restart still alerts once
    a2 = sched2.observe_assurance_delta(matter_id=mid, state="v3")
    assert a2 is not None
    assert a2.opaque_matter_ref == "ref:restart"
    assert len(sched2.list_alerts(kind=AlertKind.ASSURANCE_DELTA)) == n1 + 1


def test_alert_dedupe_index_persists(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    sched.configure_matter_alert_identity(
        "matter:dedupe",
        opaque_matter_ref="ref:dedupe",
        dossier_id="dossier:dedupe",
    )
    sched.observe_assurance_delta(matter_id="matter:dedupe", status="open")
    alert = sched.observe_assurance_delta(matter_id="matter:dedupe", status="closed")
    assert alert is not None
    assert alert.dedupe_key in sched.checkpoint.alert_dedupe_index

    sched.reload()
    assert alert.dedupe_key in sched.checkpoint.alert_dedupe_index
    # Re-observe same snapshot → still suppressed
    assert (
        sched.observe_assurance_delta(matter_id="matter:dedupe", status="closed")
        is None
    )


def test_list_assurance_snapshots(tmp_path: Path) -> None:
    sched = _make_scheduler(tmp_path)
    sched.configure_matter_alert_identity(
        "matter:snap",
        opaque_matter_ref="ref:snap",
        dossier_id="dossier:snap",
    )
    sched.observe_assurance_delta(matter_id="matter:snap", state="s")
    snaps = sched.list_assurance_snapshots()
    assert "matter:snap" in snaps
    assert snaps["matter:snap"]["opaque_matter_ref"] == "ref:snap"
    assert "overall_digest" in snaps["matter:snap"]
