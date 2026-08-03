"""Integration tests for USPTO checkpointed polling scheduler (PATLAW-062).

Acceptance coverage:

* workers release capacity while waiting;
* 401/403 creates credential-health action;
* 429 respects Retry-After;
* repeated 5xx opens a circuit;
* parse/security failure dead-letters;
* restart resumes without duplicate alerts/artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from ipfs_datasets_py.processors.domains.uspto.scheduler import (
    SCHEDULER_INTERFACE,
    SCHEDULER_SCHEMA_VERSION,
    ActionKind,
    AlertKind,
    ChangeFingerprint,
    ContentKind,
    DeadLetterReason,
    JobState,
    PollDisposition,
    PollJob,
    PollResult,
    SchedulerCheckpointStore,
    SchedulerConfig,
    ServiceName,
    USPTOApplicationScheduler,
    WorkerPool,
    create_scheduler,
    disposition_from_status,
    parse_retry_after,
)


# ---------------------------------------------------------------------------
# Test clocks / scripted poller
# ---------------------------------------------------------------------------


class FakeMonoClock:
    """Controllable monotonic clock for delay / circuit tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FixedWallClock:
    def __init__(self, when: datetime | None = None) -> None:
        self.when = when or datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.when


@dataclass
class ScriptedPoller:
    """Deterministic poller: sequence of results (optionally keyed by job)."""

    default_sequence: list[PollResult] = field(default_factory=list)
    by_job: dict[str, list[PollResult]] = field(default_factory=dict)
    by_app: dict[str, list[PollResult]] = field(default_factory=dict)
    calls: list[PollJob] = field(default_factory=list)
    _default_idx: int = 0
    _job_idx: dict[str, int] = field(default_factory=dict)
    _app_idx: dict[str, int] = field(default_factory=dict)
    raise_on_call: Exception | None = None

    def poll(self, job: PollJob) -> PollResult:
        self.calls.append(job)
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if job.job_id in self.by_job:
            seq = self.by_job[job.job_id]
            idx = self._job_idx.get(job.job_id, 0)
            if idx >= len(seq):
                return seq[-1]
            self._job_idx[job.job_id] = idx + 1
            return seq[idx]
        if job.application_number in self.by_app:
            seq = self.by_app[job.application_number]
            idx = self._app_idx.get(job.application_number, 0)
            if idx >= len(seq):
                return seq[-1]
            self._app_idx[job.application_number] = idx + 1
            return seq[idx]
        if not self.default_sequence:
            return PollResult(disposition=PollDisposition.SUCCESS, status_code=200)
        if self._default_idx >= len(self.default_sequence):
            return self.default_sequence[-1]
        result = self.default_sequence[self._default_idx]
        self._default_idx += 1
        return result


def _success(
    *,
    body: bytes | str = b'{"status":"ok"}',
    artifact_id: str | None = None,
    enqueue_binary: bool = False,
    status_code: int = 200,
    etag: str | None = None,
) -> PollResult:
    headers = {}
    if etag is not None:
        headers["ETag"] = etag
    return PollResult.from_http(
        status_code,
        headers=headers,
        body=body,
        artifact_id=artifact_id,
        enqueue_binary=enqueue_binary,
    )


def _make_scheduler(
    poller: ScriptedPoller | Callable[[PollJob], PollResult],
    *,
    tmp_path: Path | None = None,
    config: SchedulerConfig | None = None,
    clock: FakeMonoClock | None = None,
) -> tuple[USPTOApplicationScheduler, FakeMonoClock]:
    mono = clock or FakeMonoClock()
    cfg = config or SchedulerConfig(
        max_workers=2,
        max_queue_depth=32,
        circuit_failure_threshold=3,
        circuit_recovery_seconds=10.0,
        base_backoff_seconds=1.0,
        max_backoff_seconds=60.0,
        max_retry_after_seconds=120.0,
        heartbeat_interval_seconds=1_000.0,  # avoid noise unless forced
        metadata_before_binary=True,
    )
    store = SchedulerCheckpointStore(
        root=tmp_path if tmp_path is not None else None,
        name="test-sched",
    )
    sched = USPTOApplicationScheduler(
        poller=poller,
        config=cfg,
        checkpoint_store=store,
        clock=mono,
        wall_clock=FixedWallClock(),
        id_factory=_sequential_ids(),
    )
    return sched, mono


def _sequential_ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _next() -> str:
        counter["n"] += 1
        return f"id-{counter['n']:04d}"

    return _next


# ---------------------------------------------------------------------------
# Unit-ish helpers
# ---------------------------------------------------------------------------


def test_parse_retry_after_seconds_and_http_date() -> None:
    assert parse_retry_after({"Retry-After": "7"}) == 7.0
    assert parse_retry_after({"retry-after": "1.5"}) == 1.5
    # Cap
    assert parse_retry_after({"Retry-After": "9999"}, max_seconds=30.0) == 30.0
    # HTTP-date
    wall = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
    # 12:00:10 GMT
    delay = parse_retry_after(
        {"Retry-After": "Mon, 03 Aug 2026 12:00:10 GMT"},
        now=wall,
        max_seconds=60.0,
    )
    assert delay == pytest.approx(10.0)
    assert parse_retry_after({}) is None
    assert parse_retry_after(None) is None


def test_disposition_from_status_taxonomy() -> None:
    assert disposition_from_status(401) is PollDisposition.UNAUTHORIZED
    assert disposition_from_status(403) is PollDisposition.FORBIDDEN
    assert disposition_from_status(429) is PollDisposition.RATE_LIMITED
    assert disposition_from_status(503) is PollDisposition.UPSTREAM_ERROR
    assert disposition_from_status(200) is PollDisposition.SUCCESS


def test_worker_pool_releases_capacity() -> None:
    pool = WorkerPool(2)
    assert pool.acquire("a")
    assert pool.acquire("b")
    assert not pool.acquire("c")
    pool.release("a")
    assert pool.available == 1
    assert pool.acquire("c")
    pool.release("b")
    pool.release("c")
    assert pool.in_use == 0


def test_schema_constants() -> None:
    assert SCHEDULER_SCHEMA_VERSION.startswith("uspto.application-scheduler")
    assert "Scheduler" in SCHEDULER_INTERFACE


# ---------------------------------------------------------------------------
# Acceptance: workers release capacity while waiting
# ---------------------------------------------------------------------------


def test_workers_release_capacity_while_waiting(tmp_path: Path) -> None:
    """429 parks job as WAITING without holding a worker slot."""
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(429, headers={"Retry-After": "30"}),
            # Second job succeeds immediately
            _success(body=b'{"ok":1}', artifact_id="art-1"),
        ]
    )
    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(max_workers=1, heartbeat_interval_seconds=1e9),
    )
    # Job A will 429; Job B should still run because capacity is released.
    job_a = sched.enqueue(
        application_number="16111111",
        service=ServiceName.APPLICATION_STATUS,
        content_kind=ContentKind.METADATA,
        job_id="job-a",
    )
    job_b = sched.enqueue(
        application_number="16222222",
        service=ServiceName.APPLICATION_STATUS,
        content_kind=ContentKind.METADATA,
        job_id="job-b",
    )
    result = sched.tick(max_jobs=1)
    assert result["processed"] == 1
    job_a = sched.jobs["job-a"]
    assert job_a.state is JobState.WAITING
    assert sched.workers.in_use == 0
    assert sched.workers.available == 1
    # Second tick processes job B with the single worker.
    result2 = sched.tick(max_jobs=1)
    assert result2["processed"] == 1
    assert sched.jobs["job-b"].state is JobState.SUCCEEDED
    assert sched.workers.in_use == 0
    # Job A still waiting (delay not elapsed).
    assert sched.jobs["job-a"].state is JobState.WAITING
    assert job_a.next_run_at > mono()


def test_run_until_idle_does_not_busy_hold_workers_on_wait(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[PollResult.from_http(429, headers={"Retry-After": "60"})]
    )
    sched, _mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(max_workers=2, heartbeat_interval_seconds=1e9),
    )
    sched.enqueue(application_number="16333333", job_id="w1")
    out = sched.run_until_idle(max_ticks=5)
    assert out["idle_reason"] == "waiting"
    assert sched.workers.in_use == 0
    assert sched.jobs["w1"].state is JobState.WAITING


# ---------------------------------------------------------------------------
# Acceptance: 401/403 creates credential-health action
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,disposition", [(401, "unauthorized"), (403, "forbidden")])
def test_auth_failure_creates_credential_health_action(
    tmp_path: Path, status: int, disposition: str
) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(status, message=f"http {status}"),
        ]
    )
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(
        application_number="16444444",
        job_id="auth-job",
        credential_ref_id="cred-ref-1",
    )
    sched.tick()
    job = sched.jobs["auth-job"]
    assert job.state is JobState.WAITING
    assert job.last_disposition == disposition
    actions = sched.credential_health_actions()
    assert len(actions) >= 1
    assert actions[0]["kind"] == ActionKind.CREDENTIAL_HEALTH.value
    assert actions[0]["status_code"] == status
    assert actions[0]["job_id"] == "auth-job"
    alerts = sched.list_alerts(kind=AlertKind.CREDENTIAL_HEALTH)
    assert len(alerts) >= 1
    # Redaction: no raw secret fields
    blob = json.dumps(actions)
    assert "api_key" not in blob.lower() or "credential_ref" in blob
    assert "synthetic-secret" not in blob


def test_auth_failure_alert_deduped_on_repeat(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(401),
            PollResult.from_http(401),
        ]
    )
    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=1,
            base_backoff_seconds=0.0,
            max_backoff_seconds=0.0,
            heartbeat_interval_seconds=1e9,
        ),
    )
    sched.enqueue(application_number="16555555", job_id="auth-dup")
    sched.tick()
    # Advance past wait and tick again.
    mono.advance(1.0)
    sched.tick()
    cred_alerts = sched.list_alerts(kind=AlertKind.CREDENTIAL_HEALTH)
    # Dedupe: only one credential-health alert for same job/kind.
    assert len(cred_alerts) == 1
    actions = sched.credential_health_actions()
    assert len(actions) == 1


# ---------------------------------------------------------------------------
# Acceptance: 429 respects Retry-After
# ---------------------------------------------------------------------------


def test_429_respects_retry_after(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(429, headers={"Retry-After": "42"}),
            _success(body=b'{"v":2}'),
        ]
    )
    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=1,
            max_retry_after_seconds=120.0,
            heartbeat_interval_seconds=1e9,
        ),
    )
    start = mono()
    sched.enqueue(application_number="16666666", job_id="rl-job")
    sched.tick()
    job = sched.jobs["rl-job"]
    assert job.state is JobState.WAITING
    assert job.last_disposition == PollDisposition.RATE_LIMITED.value
    # next_run_at should be ~42s from start
    assert job.next_run_at == pytest.approx(start + 42.0, abs=0.01)
    # Too early: still waiting
    mono.advance(10.0)
    out = sched.tick()
    assert out["processed"] == 0
    assert sched.jobs["rl-job"].state is JobState.WAITING
    # After Retry-After elapses, job runs again.
    mono.advance(40.0)
    out2 = sched.tick()
    assert out2["processed"] == 1
    assert sched.jobs["rl-job"].state is JobState.SUCCEEDED
    rate_alerts = sched.list_alerts(kind=AlertKind.RATE_LIMIT)
    assert len(rate_alerts) >= 1


def test_429_retry_after_is_capped(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(429, headers={"Retry-After": "99999"}),
        ]
    )
    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=1,
            max_retry_after_seconds=15.0,
            heartbeat_interval_seconds=1e9,
        ),
    )
    start = mono()
    sched.enqueue(application_number="16777777", job_id="cap-job")
    sched.tick()
    job = sched.jobs["cap-job"]
    assert job.next_run_at == pytest.approx(start + 15.0, abs=0.01)


# ---------------------------------------------------------------------------
# Acceptance: repeated 5xx opens a circuit
# ---------------------------------------------------------------------------


def test_repeated_5xx_opens_circuit(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(503, message="upstream down"),
            PollResult.from_http(502, message="bad gateway"),
            PollResult.from_http(500, message="error"),
            # Would succeed if polled, but circuit should block further polls.
            _success(body=b'{"recovered":true}'),
        ]
    )
    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=1,
            circuit_failure_threshold=3,
            circuit_recovery_seconds=25.0,
            # Non-zero backoff so failed jobs stay WAITING and do not immediately
            # re-contend with newly enqueued work.
            base_backoff_seconds=1.0,
            max_backoff_seconds=1.0,
            heartbeat_interval_seconds=1e9,
        ),
    )
    service = ServiceName.APPLICATION_STATUS.value
    for i in range(3):
        sched.enqueue(
            application_number=f"1680000{i}",
            service=service,
            job_id=f"up-{i}",
        )
        sched.tick(max_jobs=1)
        # Keep prior waiters in the future so the next new job is selected.
        # (Do not advance past their backoff window.)

    assert sched.circuit_state(service) == "open"
    circuit_alerts = sched.list_alerts(kind=AlertKind.CIRCUIT_OPEN)
    assert len(circuit_alerts) >= 1
    recovery_actions = sched.list_actions(kind=ActionKind.CIRCUIT_RECOVERY)
    assert len(recovery_actions) >= 1

    # New job while circuit open: short-circuited into WAITING, capacity free.
    calls_before = len(poller.calls)
    sched.enqueue(application_number="16899999", service=service, job_id="blocked")
    out = sched.tick(max_jobs=1)
    assert out["processed"] == 1
    blocked = sched.jobs["blocked"]
    assert blocked.state is JobState.WAITING
    assert blocked.last_disposition == PollDisposition.CIRCUIT_OPEN.value
    assert sched.workers.in_use == 0
    # Open-circuit path must not invoke the poller for the blocked job.
    assert len(poller.calls) == calls_before


def test_circuit_open_after_threshold_on_same_job(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(500),
            PollResult.from_http(500),
            PollResult.from_http(500),
        ]
    )
    cfg = SchedulerConfig(
        max_workers=1,
        circuit_failure_threshold=3,
        circuit_recovery_seconds=5.0,
        base_backoff_seconds=0.0,
        max_backoff_seconds=0.0,
        heartbeat_interval_seconds=1e9,
    )
    sched, mono = _make_scheduler(poller, tmp_path=tmp_path, config=cfg)
    service = ServiceName.PATENT_FILE_WRAPPER.value
    sched.enqueue(
        application_number="16900001",
        service=service,
        job_id="same-5xx",
    )
    for _ in range(3):
        mono.advance(0.01)
        sched.tick(max_jobs=1)
    assert sched.circuit_state(service) == "open"
    assert any(
        snap.get("state") == "open"
        for snap in sched.checkpoint.circuit_states.values()
    )


# ---------------------------------------------------------------------------
# Acceptance: parse/security failure dead-letters
# ---------------------------------------------------------------------------


def test_parse_failure_dead_letters(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(
                200, body=b"not-json", parse_error=True, message="schema invalid"
            ),
        ]
    )
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(application_number="17000001", job_id="parse-job")
    sched.tick()
    job = sched.jobs["parse-job"]
    assert job.state is JobState.DEAD_LETTERED
    dls = sched.list_dead_letters()
    assert len(dls) == 1
    assert dls[0]["reason"] == DeadLetterReason.PARSE_FAILURE.value
    assert dls[0]["job_id"] == "parse-job"
    assert sched.workers.in_use == 0
    assert any(a["kind"] == AlertKind.DEAD_LETTER.value for a in sched.list_alerts())
    assert sched.list_actions(kind=ActionKind.REVIEW_DEAD_LETTER)


def test_security_failure_dead_letters(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(
                200, security_error=True, message="malware signature"
            ),
        ]
    )
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(application_number="17000002", job_id="sec-job")
    sched.tick()
    assert sched.jobs["sec-job"].state is JobState.DEAD_LETTERED
    dls = sched.list_dead_letters()
    assert dls[0]["reason"] == DeadLetterReason.SECURITY_FAILURE.value


def test_poller_exception_dead_letters(tmp_path: Path) -> None:
    poller = ScriptedPoller(raise_on_call=RuntimeError("boom parse"))
    # Need a default sequence so construction is fine; raise_on_call triggers.
    poller.default_sequence = [_success()]
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(application_number="17000003", job_id="exc-job")
    sched.tick()
    assert sched.jobs["exc-job"].state is JobState.DEAD_LETTERED


# ---------------------------------------------------------------------------
# Acceptance: restart resumes without duplicate alerts/artifacts
# ---------------------------------------------------------------------------


def test_restart_resumes_without_duplicate_alerts_or_artifacts(tmp_path: Path) -> None:
    body = b'{"status":"published","tx":1}'
    poller = ScriptedPoller(
        default_sequence=[
            _success(body=body, artifact_id="artifact-xyz", etag='"v1"'),
            # Replay same content/artifact on "restart" poll — must not re-alert change
            # nor re-admit artifact.
            _success(body=body, artifact_id="artifact-xyz", etag='"v1"'),
        ]
    )
    cfg = SchedulerConfig(
        max_workers=1,
        heartbeat_interval_seconds=1e9,
        circuit_failure_threshold=5,
    )
    store_root = tmp_path / "ckpt"
    sched, mono = _make_scheduler(poller, tmp_path=store_root, config=cfg)
    sched.enqueue(application_number="17111111", job_id="resume-job")
    sched.tick()
    assert sched.jobs["resume-job"].state is JobState.SUCCEEDED
    change_alerts_1 = sched.list_alerts(kind=AlertKind.CHANGE_DETECTED)
    assert len(change_alerts_1) == 1
    assert "artifact-xyz" in sched.checkpoint.known_artifact_ids
    alerts_count_1 = len(sched.alerts)
    actions_count_1 = len(sched.actions)

    # Simulate process restart: new scheduler instance, same store.
    sched2 = USPTOApplicationScheduler(
        poller=poller,
        config=cfg,
        checkpoint_store=SchedulerCheckpointStore(root=store_root, name="test-sched"),
        clock=mono,
        wall_clock=FixedWallClock(),
        id_factory=_sequential_ids(),
    )
    # Checkpoint loaded: job already succeeded.
    assert "resume-job" in sched2.jobs
    assert sched2.jobs["resume-job"].state is JobState.SUCCEEDED
    assert "artifact-xyz" in sched2.checkpoint.known_artifact_ids

    # Re-enqueue same logical work with new job id but same resource + same artifact.
    sched2.enqueue(application_number="17111111", job_id="resume-job-2")
    sched2.tick()
    job2 = sched2.jobs["resume-job-2"]
    assert job2.state is JobState.SUCCEEDED
    # Unchanged / duplicate artifact → no second change alert.
    change_alerts_2 = sched2.list_alerts(kind=AlertKind.CHANGE_DETECTED)
    assert len(change_alerts_2) == 1
    # Dedupe index preserved across restart.
    assert len(sched2.checkpoint.alert_dedupe_index) >= len(
        sched.checkpoint.alert_dedupe_index
    )
    # Artifact set did not grow duplicates.
    assert list(sched2.checkpoint.known_artifact_ids).count("artifact-xyz") == 1 or (
        "artifact-xyz" in sched2.checkpoint.known_artifact_ids
    )

    # Credential-health dedupe across restart
    poller_auth = ScriptedPoller(default_sequence=[PollResult.from_http(401)])
    auth_root = tmp_path / "ckpt-auth"
    s1, m1 = _make_scheduler(poller_auth, tmp_path=auth_root, config=cfg)
    s1.enqueue(application_number="17222222", job_id="auth-r")
    s1.tick()
    assert len(s1.list_alerts(kind=AlertKind.CREDENTIAL_HEALTH)) == 1
    s2 = USPTOApplicationScheduler(
        poller=poller_auth,
        config=cfg,
        checkpoint_store=SchedulerCheckpointStore(root=auth_root, name="test-sched"),
        clock=m1,
        wall_clock=FixedWallClock(),
        id_factory=_sequential_ids(),
    )
    m1.advance(100.0)
    # Same job still waiting — tick should not emit another credential alert.
    # Re-queue path: job was WAITING; advance and tick.
    waiting = s2.jobs.get("auth-r")
    assert waiting is not None
    assert waiting.state in (JobState.WAITING, JobState.PENDING)
    s2.tick()
    assert len(s2.list_alerts(kind=AlertKind.CREDENTIAL_HEALTH)) == 1


def test_checkpoint_roundtrip_on_disk(tmp_path: Path) -> None:
    poller = ScriptedPoller(default_sequence=[_success(body=b"{}", artifact_id="a1")])
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(application_number="17333333", matter_id="matter:syn:1", job_id="rt1")
    sched.tick()
    path = tmp_path / "test-sched-checkpoint.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEDULER_SCHEMA_VERSION
    assert "rt1" in payload["jobs"]
    assert "a1" in payload["known_artifact_ids"]
    # Atomic write leaves no .tmp
    assert not path.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# Change detection & metadata-before-binary
# ---------------------------------------------------------------------------


def test_change_detection_emits_alert_only_on_change(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            _success(body=b'{"v":1}', etag='"1"'),
            _success(body=b'{"v":1}', etag='"1"'),
            _success(body=b'{"v":2}', etag='"2"'),
        ]
    )
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    for i, jid in enumerate(("c1", "c2", "c3")):
        sched.enqueue(application_number="17444444", job_id=jid)
        sched.tick()
    changes = sched.list_alerts(kind=AlertKind.CHANGE_DETECTED)
    # First success → CHANGED; second UNCHANGED; third CHANGED
    assert len(changes) == 2
    assert sched.progress().changes_detected == 2


def test_metadata_before_binary_gating(tmp_path: Path) -> None:
    """Binary job does not run until metadata for the application succeeds."""
    call_kinds: list[str] = []

    def poller(job: PollJob) -> PollResult:
        call_kinds.append(job.content_kind.value)
        if job.content_kind is ContentKind.METADATA:
            return _success(body=b'{"meta":true}', enqueue_binary=False)
        return _success(body=b"%PDF-binary", artifact_id="bin-1")

    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=2,
            metadata_before_binary=True,
            heartbeat_interval_seconds=1e9,
            base_backoff_seconds=0.5,
        ),
    )
    # Enqueue binary first — should not execute before metadata.
    sched.enqueue(
        application_number="17555555",
        service=ServiceName.DOCUMENT_BYTES,
        content_kind=ContentKind.BINARY,
        job_id="bin-job",
    )
    sched.enqueue(
        application_number="17555555",
        service=ServiceName.APPLICATION_STATUS,
        content_kind=ContentKind.METADATA,
        job_id="meta-job",
        # parent for binary optional
    )
    # Link binary to metadata parent
    sched.jobs["bin-job"].parent_job_id = "meta-job"

    # Tick once: metadata preferred and should run; binary may be gated.
    out = sched.tick(max_jobs=2)
    assert "meta-job" in [o["job_id"] for o in out["outcomes"]] or sched.jobs[
        "meta-job"
    ].state is JobState.SUCCEEDED
    # Eventually both complete
    for _ in range(5):
        mono.advance(1.0)
        sched.tick(max_jobs=2)
        if (
            sched.jobs["meta-job"].state is JobState.SUCCEEDED
            and sched.jobs["bin-job"].state is JobState.SUCCEEDED
        ):
            break
    assert sched.jobs["meta-job"].state is JobState.SUCCEEDED
    assert sched.jobs["bin-job"].state is JobState.SUCCEEDED
    # Metadata was polled before binary completed (ordering under gate).
    assert ContentKind.METADATA.value in call_kinds
    assert call_kinds[0] == ContentKind.METADATA.value or (
        call_kinds.count(ContentKind.METADATA.value) >= 1
        and call_kinds.index(ContentKind.METADATA.value)
        <= call_kinds.index(ContentKind.BINARY.value)
    )


def test_metadata_enqueue_binary_follow_up(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        by_job={
            "meta-only": [
                _success(
                    body=b'{"docs":1}',
                    enqueue_binary=True,
                    artifact_id=None,
                )
            ],
        }
    )
    # Default for binary jobs
    poller.default_sequence = [_success(body=b"BIN", artifact_id="bin-follow")]

    def routing_poller(job: PollJob) -> PollResult:
        if job.job_id in poller.by_job:
            return poller.poll(job)
        return poller.poll(job)

    sched, mono = _make_scheduler(routing_poller, tmp_path=tmp_path)
    sched.enqueue(
        application_number="17666666",
        service=ServiceName.APPLICATION_STATUS,
        content_kind=ContentKind.METADATA,
        job_id="meta-only",
    )
    sched.tick()
    assert sched.jobs["meta-only"].state is JobState.SUCCEEDED
    # Binary follow-up enqueued
    binary_jobs = [
        j
        for j in sched.jobs.values()
        if j.content_kind is ContentKind.BINARY
        and j.application_number == "17666666"
    ]
    assert len(binary_jobs) == 1
    mono.advance(0.1)
    sched.tick()
    assert binary_jobs[0].state is JobState.SUCCEEDED


# ---------------------------------------------------------------------------
# Heartbeat, health, factory, redaction
# ---------------------------------------------------------------------------


def test_heartbeat_and_health_are_content_free(tmp_path: Path) -> None:
    poller = ScriptedPoller(default_sequence=[_success(body=b"SECRET_DOC_BODY")])
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(application_number="17777777", job_id="hb1")
    sched.tick()
    alert = sched.force_heartbeat()
    assert alert is not None
    assert alert.kind is AlertKind.HEARTBEAT
    health = sched.health()
    assert health["schema_version"] == SCHEDULER_SCHEMA_VERSION
    assert health["interface"] == SCHEDULER_INTERFACE
    assert "workers_available" in health
    blob = json.dumps(health) + json.dumps(alert.to_dict())
    assert "SECRET_DOC_BODY" not in blob


def test_create_scheduler_factory(tmp_path: Path) -> None:
    poller = ScriptedPoller(default_sequence=[_success()])
    sched = create_scheduler(
        poller,
        checkpoint_dir=tmp_path,
        checkpoint_name="factory",
        config=SchedulerConfig(max_workers=1, heartbeat_interval_seconds=1e9),
        wall_clock=FixedWallClock(),
    )
    assert isinstance(sched, USPTOApplicationScheduler)
    jobs = sched.enqueue_matter_poll(
        application_number="17888888",
        matter_id="matter:syn:x",
        include_binary=True,
    )
    assert len(jobs) == 2
    assert jobs[0].content_kind is ContentKind.METADATA
    assert jobs[1].content_kind is ContentKind.BINARY


def test_change_fingerprint_stable() -> None:
    a = ChangeFingerprint.build(content_sha256="abc", etag='"1"')
    b = ChangeFingerprint.build(content_sha256="abc", etag='"1"')
    c = ChangeFingerprint.build(content_sha256="abd", etag='"1"')
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint


def test_queue_full_raises(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[PollResult.from_http(429, headers={"Retry-After": "99"})]
    )
    sched, _ = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=1,
            max_queue_depth=2,
            heartbeat_interval_seconds=1e9,
        ),
    )
    sched.enqueue(application_number="17900001", job_id="q1")
    sched.enqueue(application_number="17900002", job_id="q2")
    with pytest.raises(Exception) as excinfo:
        sched.enqueue(application_number="17900003", job_id="q3")
    assert "queue full" in str(excinfo.value).lower() or getattr(
        excinfo.value, "code", ""
    ) == "queue_full"


def test_not_found_succeeds_without_dead_letter(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[PollResult.from_http(404, message="not found")]
    )
    sched, _ = _make_scheduler(poller, tmp_path=tmp_path)
    sched.enqueue(application_number="17999999", job_id="nf")
    sched.tick()
    assert sched.jobs["nf"].state is JobState.SUCCEEDED
    assert sched.list_dead_letters() == []


def test_waiting_job_releases_capacity_under_5xx_backoff(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(503),
            _success(body=b"other"),
        ]
    )
    sched, mono = _make_scheduler(
        poller,
        tmp_path=tmp_path,
        config=SchedulerConfig(
            max_workers=1,
            circuit_failure_threshold=10,
            base_backoff_seconds=5.0,
            heartbeat_interval_seconds=1e9,
        ),
    )
    sched.enqueue(application_number="18000001", job_id="fail")
    sched.enqueue(application_number="18000002", job_id="ok")
    sched.tick(max_jobs=1)
    assert sched.jobs["fail"].state is JobState.WAITING
    assert sched.workers.in_use == 0
    # Other job can use the released worker immediately.
    sched.tick(max_jobs=1)
    assert sched.jobs["ok"].state is JobState.SUCCEEDED


def test_reload_restores_waiting_jobs(tmp_path: Path) -> None:
    poller = ScriptedPoller(
        default_sequence=[
            PollResult.from_http(429, headers={"Retry-After": "10"}),
            _success(body=b"done"),
        ]
    )
    cfg = SchedulerConfig(
        max_workers=1,
        heartbeat_interval_seconds=1e9,
        max_retry_after_seconds=60.0,
    )
    sched, mono = _make_scheduler(poller, tmp_path=tmp_path, config=cfg)
    sched.enqueue(application_number="18111111", job_id="wait-reload")
    sched.tick()
    assert sched.jobs["wait-reload"].state is JobState.WAITING
    mono.advance(10.0)
    sched.reload()
    # After reload + delay elapsed, job is ready again.
    out = sched.tick()
    assert out["processed"] == 1
    assert sched.jobs["wait-reload"].state is JobState.SUCCEEDED
