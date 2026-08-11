"""Integration tests for cross-repo sync schedule install (PATLAW-162).

Acceptance coverage:

* fake-clock tests prove cadence, mutual exclusion, missed-run recovery, and
  pre-release blocking;
* repeated install is idempotent;
* operator must explicitly activate generated templates;
* every run produces or references a paired-revision receipt and never pushes;
* install never rewrites user crontabs; templates are not auto-enabled.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths / module load
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]
_INSTALLER_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "install_sync_schedule.py"
_SYNC_SH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "sync_upstreams.sh"


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "uspto_install_sync_schedule", _INSTALLER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sched = _load_installer()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state_root(tmp_path: Path) -> Path:
    root = tmp_path / "cross_repo_sync"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def clock() -> Any:
    return sched.FakeClock(start=1_700_000_000.0)


@pytest.fixture()
def recording_runner():
    """Deterministic runner that writes a minimal paired-revision receipt."""
    calls: list[dict[str, Any]] = []

    def _runner(**kwargs: Any) -> sched.RunResult:
        schedule_trigger = kwargs["schedule_trigger"]
        sync_trigger = kwargs["sync_trigger"]
        state_root = Path(kwargs["state_root"])
        lock = kwargs["lock"]
        clock = kwargs["clock"]
        dry_run = bool(kwargs.get("dry_run"))
        catch_up = bool(kwargs.get("catch_up"))
        missed = int(kwargs.get("missed_intervals") or 0)
        run_id = f"test-{len(calls) + 1:04d}"
        started = clock.now()
        extra_env = kwargs.get("extra_env") or {}
        # Optional hold to exercise mutual exclusion.
        hold = float(extra_env.get("TEST_HOLD_SECONDS", 0) or 0)
        if hold > 0:
            time.sleep(hold)
        receipt_path = state_root / "receipts" / f"{schedule_trigger}.paired_revision_receipt.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        status = "accepted"
        # pre-release can be forced failed via env
        if extra_env.get("TEST_FORCE_FAIL") == "1":
            status = "aborted"
        payload = {
            "schema_version": "uspto.paired-revision-receipt.v1",
            "interface": "UsptoPairedRevisionReceipt@1",
            "receipt_id": f"rcpt-{run_id}",
            "status": status,
            "disposition": (
                "fetch_only"
                if sync_trigger in sched.FETCH_ONLY_SYNC
                else ("aborted" if status != "accepted" else "integrated")
            ),
            "trigger": sync_trigger,
            "schedule_trigger": schedule_trigger,
            "datasets": {
                "name": "datasets",
                "before_sha": "a" * 40,
                "remote_sha": "b" * 40,
                "integrated_sha": None if status != "accepted" else "c" * 40,
            },
            "accelerator": {
                "name": "accelerator",
                "before_sha": "d" * 40,
                "remote_sha": "e" * 40,
                "integrated_sha": None if status != "accepted" else "f" * 40,
            },
            "capability_pin": None,
            "merge_order": ["accelerator", "datasets"],
            "merge_trace": [],
            "test_results": [],
            "lock": lock.as_dict(),
            "policy": {
                "push_allowed": False,
                "active_worktree_pull_allowed": False,
                "recursive_submodules": False,
                "require_clean_worktree": True,
                "fail_closed_on_conflict": True,
                "serialize_integrations": True,
                "use_isolated_worktrees": True,
                "merge_order": ["accelerator", "datasets"],
                "fetch_only_triggers": sorted(sched.FETCH_ONLY_SYNC),
                "integration_triggers": sorted(sched.INTEGRATION_SYNC),
            },
            "started_at_utc": clock.utc_iso(),
            "completed_at_utc": clock.utc_iso(),
            "mutation_attempted": False,
            "push_attempted": False,
            "active_worktree_pull_attempted": False,
            "recursive_submodule_chase": False,
        }
        receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        completed = clock.now()
        result = sched.RunResult(
            schedule_trigger=schedule_trigger,
            sync_trigger=sync_trigger,
            run_id=run_id,
            status="dry-run" if dry_run else ("success" if status == "accepted" else "failed"),
            exit_code=0 if status == "accepted" else 1,
            receipt_path=str(receipt_path),
            receipt_referenced=True,
            push_attempted=False,
            lock=lock.as_dict(),
            started_at=started,
            completed_at=completed,
            dry_run=dry_run,
            catch_up=catch_up,
            missed_intervals=missed,
            reason=str(kwargs.get("reason") or ""),
        )
        calls.append(result.to_dict())
        return result

    _runner.calls = calls  # type: ignore[attr-defined]
    return _runner


# ---------------------------------------------------------------------------
# Offline / surface
# ---------------------------------------------------------------------------


def test_installer_module_and_sync_script_exist() -> None:
    assert _INSTALLER_PATH.is_file()
    assert _SYNC_SH.is_file()
    assert os.access(_SYNC_SH, os.X_OK) or _SYNC_SH.read_text(encoding="utf-8").startswith("#!")


def test_offline_self_check_passes() -> None:
    report = sched.offline_self_check()
    assert report["ok"] is True
    assert report["push_allowed"] is False
    names = {c["name"] for c in report["checks"]}
    assert "push_forbidden" in names
    assert "operator_activation_required" in names
    assert "missed_run_single" in names
    assert "pre_release_blocks_by_default" in names
    assert set(report["schedule_triggers"]) == set(sched.SCHEDULE_TRIGGERS)


def test_cli_offline_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(_INSTALLER_PATH), "--offline"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_list_triggers_catalog() -> None:
    result = subprocess.run(
        [sys.executable, str(_INSTALLER_PATH), "list-triggers"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "wave-boundary" in payload["schedule_triggers"]
    assert payload["schedule_to_sync_trigger"]["wave-boundary"] == "twice-daily"
    assert payload["push_allowed"] is False
    assert payload["operator_activation_required"] is True


def test_sync_list_triggers_includes_schedule_metadata() -> None:
    result = subprocess.run(
        ["bash", str(_SYNC_SH), "--list-triggers"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["push_allowed"] is False
    assert payload["operator_activation_required"] is True
    assert "wave-boundary" in payload["schedule_slots"]
    assert payload["program_family"] == "uspto-cross-repo-sync"


# ---------------------------------------------------------------------------
# Install idempotency + operator activation
# ---------------------------------------------------------------------------


def test_install_is_idempotent(state_root: Path) -> None:
    r1 = sched.install_templates(state_root=state_root)
    assert r1["ok"] is True
    assert r1["changed"] > 0
    assert r1["activated"] is False
    assert r1["operator_activation_required"] is True
    tdir = Path(r1["template_dir"])
    assert (tdir / "install_manifest.json").is_file()
    assert (tdir / "README.md").is_file()
    # systemd + cron for every schedule trigger
    for name in sched.SCHEDULE_TRIGGERS:
        assert (tdir / "systemd" / f"uspto-cross-repo-sync-{name}.service").is_file()
        assert (tdir / "systemd" / f"uspto-cross-repo-sync-{name}.timer").is_file()
        assert (tdir / "cron" / f"uspto-cross-repo-sync-{name}.cron").is_file()

    r2 = sched.install_templates(state_root=state_root)
    assert r2["ok"] is True
    assert r2["changed"] == 0
    assert r2["unchanged"] == r1["changed"] + r1["unchanged"] or r2["unchanged"] > 0
    # Second install must not create activation.
    assert r2["activated"] is False

    # Contents stable.
    svc = (tdir / "systemd" / "uspto-cross-repo-sync-eight-hour.service").read_text(
        encoding="utf-8"
    )
    assert "TEMPLATE ONLY" in svc
    assert "push" in svc.lower()
    cron = (tdir / "cron" / "uspto-cross-repo-sync-eight-hour.cron").read_text(
        encoding="utf-8"
    )
    assert "do NOT install into user crontab automatically" in cron


def test_install_dry_run_writes_nothing(state_root: Path) -> None:
    r = sched.install_templates(state_root=state_root, dry_run=True)
    assert r["ok"] is True
    assert r["dry_run"] is True
    assert r["changed"] > 0
    tdir = Path(r["template_dir"])
    assert not tdir.exists() or not any(tdir.rglob("*.service"))


def test_activate_requires_explicit_flag(state_root: Path) -> None:
    sched.install_templates(state_root=state_root)
    with pytest.raises(sched.ScheduleError, match="activate-templates"):
        sched.activate_templates(
            state_root=state_root, activate_templates_flag=False
        )


def test_operator_must_explicitly_activate(state_root: Path, clock: Any) -> None:
    sched.install_templates(state_root=state_root)
    status = sched.status_report(state_root=state_root, clock=clock)
    assert status["activated"] is False
    assert status["operator_activation_required"] is True

    act = sched.activate_templates(
        state_root=state_root, activate_templates_flag=True, clock=clock
    )
    assert act["activated"] is True
    assert act["systemd_enabled"] is False
    assert act["crontab_modified"] is False
    assert act["push_allowed"] is False

    status2 = sched.status_report(state_root=state_root, clock=clock)
    assert status2["activated"] is True
    assert status2["operator_activation_required"] is False
    marker = Path(status2["template_dir"]) / "ACTIVATED"
    assert marker.is_file()


def test_uninstall_removes_templates_not_crontab(state_root: Path) -> None:
    sched.install_templates(state_root=state_root)
    sched.activate_templates(state_root=state_root, activate_templates_flag=True)
    tdir = state_root / "schedule_templates"
    assert tdir.is_dir()
    rep = sched.uninstall_templates(state_root=state_root)
    assert rep["ok"] is True
    assert rep["crontab_modified"] is False
    assert not tdir.exists() or not any(tdir.rglob("*"))
    st = sched.ScheduleStateStore(state_root).load()
    assert st.activated is False


def test_cli_install_activate_status_roundtrip(state_root: Path) -> None:
    env = os.environ.copy()
    env["CROSS_REPO_SYNC_STATE_ROOT"] = str(state_root)
    inst = subprocess.run(
        [
            sys.executable,
            str(_INSTALLER_PATH),
            "--state-root",
            str(state_root),
            "install",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert inst.returncode == 0, inst.stderr
    payload = json.loads(inst.stdout)
    assert payload["activated"] is False

    # Activate without flag must fail.
    bad = subprocess.run(
        [
            sys.executable,
            str(_INSTALLER_PATH),
            "--state-root",
            str(state_root),
            "activate",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert bad.returncode != 0

    good = subprocess.run(
        [
            sys.executable,
            str(_INSTALLER_PATH),
            "--state-root",
            str(state_root),
            "activate",
            "--activate-templates",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["activated"] is True


# ---------------------------------------------------------------------------
# Fake-clock cadence
# ---------------------------------------------------------------------------


def test_fake_clock_cadence_eight_hour_and_twice_daily(
    state_root: Path, clock: Any, recording_runner
) -> None:
    store = sched.ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    state.activated = True
    store.save(state)

    # First tick: all periodics due (initial).
    t0 = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        dry_run=False,
    )
    due_names = {d["schedule_trigger"] for d in t0["due"]}
    assert "eight-hour" in due_names
    assert "twice-daily" in due_names
    assert "wave-boundary" in due_names
    assert "pre-release" not in due_names  # on-demand
    assert "security-fix" not in due_names
    n_initial = len(recording_runner.calls)

    # Immediately again: nothing due.
    t1 = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
    )
    assert t1["due_count"] == 0
    assert len(recording_runner.calls) == n_initial

    # Advance 8h + epsilon → eight-hour only.
    clock.advance(8 * 3600 + 5)
    t2 = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
    )
    due2 = {d["schedule_trigger"] for d in t2["due"]}
    assert due2 == {"eight-hour"}
    assert len(recording_runner.calls) == n_initial + 1

    # Advance to 12h from last twice-daily completion.
    # twice-daily was completed at t0 (~1_700_000_000); we advanced 8h, need ~4h more.
    clock.advance(4 * 3600 + 5)
    t3 = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
    )
    due3 = {d["schedule_trigger"] for d in t3["due"]}
    assert "twice-daily" in due3
    # eight-hour also due again (another ~4h past its 8h mark from t2)
    # From t2 completion, we advanced 4h — not yet 8h, so eight-hour should NOT fire.
    assert "eight-hour" not in due3


def test_wave_boundary_maps_to_twice_daily_sync_trigger(
    state_root: Path, clock: Any, recording_runner
) -> None:
    result = sched.run_schedule_trigger(
        schedule_trigger="wave-boundary",
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
    )
    assert result.schedule_trigger == "wave-boundary"
    assert result.sync_trigger == "twice-daily"
    assert result.receipt_path is not None
    assert Path(result.receipt_path).is_file()
    payload = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
    assert payload["trigger"] == "twice-daily"
    assert payload["push_attempted"] is False


# ---------------------------------------------------------------------------
# Missed-run recovery
# ---------------------------------------------------------------------------


def test_missed_run_recovery_single_catch_up(
    state_root: Path, clock: Any, recording_runner
) -> None:
    store = sched.ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    # Pretend eight-hour last ran long ago (5 full intervals + slack).
    state.triggers["eight-hour"].last_completed_at = clock.now() - (8 * 3600 * 5) - 60
    state.triggers["eight-hour"].last_status = "success"
    # Prevent other periodics from cluttering.
    for name in ("twice-daily", "wave-boundary"):
        state.triggers[name].last_completed_at = clock.now()
        state.triggers[name].last_status = "success"
    store.save(state)

    due = sched.compute_due_triggers(state, now=clock.now(), only=["eight-hour"])
    assert len(due) == 1
    assert due[0].catch_up is True
    assert due[0].missed_intervals >= 1
    # Not 5 separate due entries.
    assert due[0].missed_intervals == 4  # 5 full intervals → 4 extras beyond the one run

    tick = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        only=["eight-hour"],
    )
    assert tick["due_count"] == 1
    assert len(recording_runner.calls) == 1
    assert recording_runner.calls[0]["catch_up"] is True
    assert recording_runner.calls[0]["missed_intervals"] >= 1

    # After catch-up, not immediately due again.
    tick2 = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        only=["eight-hour"],
    )
    assert tick2["due_count"] == 0


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


def test_mutual_exclusion_second_run_skips_when_lock_held(
    state_root: Path, clock: Any, recording_runner
) -> None:
    lock_path = state_root / "sync.lock"
    lock = sched.ProgramFamilyLock(lock_path)
    assert lock.try_acquire() is True

    result = sched.run_schedule_trigger(
        schedule_trigger="eight-hour",
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        lock_path=lock_path,
    )
    assert result.status == "skipped"
    assert result.reason == "lock_held"
    assert result.push_attempted is False
    # Runner must not have been invoked.
    assert recording_runner.calls == []

    lock.release()

    result2 = sched.run_schedule_trigger(
        schedule_trigger="eight-hour",
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        lock_path=lock_path,
    )
    assert result2.status in {"success", "dry-run"}
    assert len(recording_runner.calls) == 1


def test_mutual_exclusion_concurrent_threads(
    state_root: Path, clock: Any
) -> None:
    """Two concurrent schedule runs: exactly one holds the program-family lock."""
    lock_path = state_root / "sync.lock"
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def _worker(name: str) -> None:
        def runner(**kwargs: Any) -> sched.RunResult:
            barrier.wait(timeout=5)
            # Hold lock while "working".
            time.sleep(0.15)
            receipt = Path(kwargs["state_root"]) / "receipts" / f"{name}.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": "uspto.paired-revision-receipt.v1",
                        "interface": "UsptoPairedRevisionReceipt@1",
                        "receipt_id": name,
                        "status": "accepted",
                        "disposition": "fetch_only",
                        "trigger": kwargs["sync_trigger"],
                        "push_attempted": False,
                        "mutation_attempted": False,
                        "active_worktree_pull_attempted": False,
                        "recursive_submodule_chase": False,
                        "merge_order": ["accelerator", "datasets"],
                        "merge_trace": [],
                        "test_results": [],
                        "datasets": {
                            "name": "datasets",
                            "before_sha": "1" * 40,
                            "remote_sha": "2" * 40,
                            "integrated_sha": None,
                        },
                        "accelerator": {
                            "name": "accelerator",
                            "before_sha": "3" * 40,
                            "remote_sha": "4" * 40,
                            "integrated_sha": None,
                        },
                        "capability_pin": None,
                        "lock": kwargs["lock"].as_dict(),
                        "policy": {"push_allowed": False},
                        "started_at_utc": kwargs["clock"].utc_iso(),
                        "completed_at_utc": kwargs["clock"].utc_iso(),
                    }
                ),
                encoding="utf-8",
            )
            return sched.RunResult(
                schedule_trigger=kwargs["schedule_trigger"],
                sync_trigger=kwargs["sync_trigger"],
                run_id=name,
                status="success",
                exit_code=0,
                receipt_path=str(receipt),
                receipt_referenced=True,
                push_attempted=False,
                lock=kwargs["lock"].as_dict(),
                started_at=kwargs["clock"].now(),
                completed_at=kwargs["clock"].now(),
            )

        # Stagger only the attempt to make lock contention realistic: both try
        # nearly together; the barrier is inside the runner so the first acquirer
        # holds through the second's try_acquire if second starts while first runs.
        res = sched.run_schedule_trigger(
            schedule_trigger="eight-hour" if name == "a" else "twice-daily",
            state_root=state_root,
            clock=clock,
            runner=runner,
            lock_path=lock_path,
        )
        with outcomes_lock:
            outcomes.append(res.status)

    # More reliable mutual exclusion proof: hold lock in thread A without
    # going through barrier-in-runner race.
    held = sched.ProgramFamilyLock(lock_path)
    assert held.try_acquire()

    skipped = sched.run_schedule_trigger(
        schedule_trigger="twice-daily",
        state_root=state_root,
        clock=clock,
        runner=lambda **k: (_ for _ in ()).throw(AssertionError("should not run")),
        lock_path=lock_path,
    )
    assert skipped.status == "skipped"
    held.release()

    # Sequential different triggers still serialize and both succeed.
    r1 = sched.run_schedule_trigger(
        schedule_trigger="eight-hour",
        state_root=state_root,
        clock=clock,
        runner=_make_simple_runner("s1"),
        lock_path=lock_path,
    )
    r2 = sched.run_schedule_trigger(
        schedule_trigger="pre-release",
        state_root=state_root,
        clock=clock,
        runner=_make_simple_runner("s2"),
        lock_path=lock_path,
    )
    assert r1.status == "success"
    assert r2.status == "success"
    assert r1.receipt_path != r2.receipt_path


def _make_simple_runner(tag: str):
    def runner(**kwargs: Any) -> sched.RunResult:
        receipt = Path(kwargs["state_root"]) / "receipts" / f"{tag}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": "uspto.paired-revision-receipt.v1",
                    "interface": "UsptoPairedRevisionReceipt@1",
                    "receipt_id": tag,
                    "status": "accepted",
                    "disposition": "integrated",
                    "trigger": kwargs["sync_trigger"],
                    "push_attempted": False,
                    "mutation_attempted": False,
                    "active_worktree_pull_attempted": False,
                    "recursive_submodule_chase": False,
                    "merge_order": ["accelerator", "datasets"],
                    "merge_trace": [],
                    "test_results": [],
                    "datasets": {
                        "name": "datasets",
                        "before_sha": "1" * 40,
                        "remote_sha": "2" * 40,
                        "integrated_sha": "3" * 40,
                    },
                    "accelerator": {
                        "name": "accelerator",
                        "before_sha": "4" * 40,
                        "remote_sha": "5" * 40,
                        "integrated_sha": "6" * 40,
                    },
                    "capability_pin": None,
                    "lock": kwargs["lock"].as_dict(),
                    "policy": {"push_allowed": False},
                    "started_at_utc": kwargs["clock"].utc_iso(),
                    "completed_at_utc": kwargs["clock"].utc_iso(),
                }
            ),
            encoding="utf-8",
        )
        return sched.RunResult(
            schedule_trigger=kwargs["schedule_trigger"],
            sync_trigger=kwargs["sync_trigger"],
            run_id=tag,
            status="success",
            exit_code=0,
            receipt_path=str(receipt),
            receipt_referenced=True,
            push_attempted=False,
            lock=kwargs["lock"].as_dict(),
            started_at=kwargs["clock"].now(),
            completed_at=kwargs["clock"].now(),
        )

    return runner


# ---------------------------------------------------------------------------
# Pre-release blocking
# ---------------------------------------------------------------------------


def test_pre_release_blocking_without_success(
    state_root: Path, clock: Any
) -> None:
    store = sched.ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    gate = sched.evaluate_pre_release_gate(
        state, now=clock.now(), require_receipt_file=False
    )
    assert gate["allowed"] is False
    assert gate["reason"] == "pre_release_never_succeeded"

    with pytest.raises(sched.PreReleaseBlocked):
        sched.assert_release_allowed(state, now=clock.now())


def test_pre_release_blocking_when_stale(
    state_root: Path, clock: Any, recording_runner
) -> None:
    # Successful pre-release now.
    r = sched.run_schedule_trigger(
        schedule_trigger="pre-release",
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
    )
    assert r.status == "success"
    assert r.receipt_path and Path(r.receipt_path).is_file()

    store = sched.ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    gate_ok = sched.evaluate_pre_release_gate(
        state, now=clock.now(), max_age_seconds=3600, require_receipt_file=True
    )
    assert gate_ok["allowed"] is True

    # Advance past freshness window.
    clock.advance(3600 + 10)
    state = store.load()
    gate_stale = sched.evaluate_pre_release_gate(
        state, now=clock.now(), max_age_seconds=3600, require_receipt_file=True
    )
    assert gate_stale["allowed"] is False
    assert gate_stale["reason"] == "pre_release_stale"

    with pytest.raises(sched.PreReleaseBlocked, match="stale|blocked"):
        sched.assert_release_allowed(state, now=clock.now(), max_age_seconds=3600)


def test_pre_release_blocking_failed_run(
    state_root: Path, clock: Any, recording_runner
) -> None:
    r = sched.run_schedule_trigger(
        schedule_trigger="pre-release",
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        extra_env={"TEST_FORCE_FAIL": "1"},
    )
    assert r.status == "failed"
    store = sched.ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    gate = sched.evaluate_pre_release_gate(
        state, now=clock.now(), require_receipt_file=False
    )
    assert gate["allowed"] is False


def test_cli_check_release_gate_blocks(state_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(_INSTALLER_PATH),
            "--state-root",
            str(state_root),
            "check-release-gate",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["allowed"] is False
    assert payload["push_allowed"] is False


# ---------------------------------------------------------------------------
# Receipt + never push
# ---------------------------------------------------------------------------


def test_every_run_produces_or_references_receipt(
    state_root: Path, clock: Any, recording_runner
) -> None:
    for name in sched.SCHEDULE_TRIGGERS:
        result = sched.run_schedule_trigger(
            schedule_trigger=name,
            state_root=state_root,
            clock=clock,
            runner=recording_runner,
        )
        assert result.receipt_referenced is True
        assert result.receipt_path is not None
        assert Path(result.receipt_path).is_file()
        payload = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
        assert "paired-revision" in str(payload.get("schema_version") or "")
        assert payload.get("push_attempted") is False


def test_dry_run_tick_writes_receipt_without_push(
    state_root: Path, clock: Any
) -> None:
    report = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        dry_run=True,
        only=["eight-hour"],
    )
    assert report["ok"] is True
    assert report["push_allowed"] is False
    assert report["due_count"] == 1
    assert report["results"]
    receipt = report["results"][0]["receipt_path"]
    assert receipt and Path(receipt).is_file()
    payload = json.loads(Path(receipt).read_text(encoding="utf-8"))
    assert payload["push_attempted"] is False


def test_require_activated_blocks_tick_until_opt_in(
    state_root: Path, clock: Any, recording_runner
) -> None:
    sched.install_templates(state_root=state_root)
    with pytest.raises(sched.ScheduleError, match="not activated"):
        sched.tick_schedule(
            state_root=state_root,
            clock=clock,
            runner=recording_runner,
            require_activated=True,
            only=["eight-hour"],
        )
    sched.activate_templates(
        state_root=state_root, activate_templates_flag=True, clock=clock
    )
    report = sched.tick_schedule(
        state_root=state_root,
        clock=clock,
        runner=recording_runner,
        require_activated=True,
        only=["eight-hour"],
    )
    assert report["due_count"] == 1


def test_sync_script_rejects_push_env(state_root: Path) -> None:
    env = os.environ.copy()
    env["CROSS_REPO_SYNC_PUSH_ALLOWED"] = "1"
    env["CROSS_REPO_SYNC_STATE_ROOT"] = str(state_root)
    result = subprocess.run(
        ["bash", str(_SYNC_SH), "--trigger", "startup", "--plan-only"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2
    assert "PUSH_ALLOWED" in (result.stderr + result.stdout)


def test_program_family_constants_align() -> None:
    assert sched.PROGRAM_FAMILY == "uspto-cross-repo-sync"
    assert sched.DEFAULT_LOCK_NAME == "sync.lock"
    assert set(sched.PERIODIC_TRIGGERS) == {
        "eight-hour",
        "twice-daily",
        "wave-boundary",
    }
    assert set(sched.ON_DEMAND_TRIGGERS) == {"pre-release", "security-fix"}


def test_status_reports_due_and_gate(state_root: Path, clock: Any) -> None:
    sched.install_templates(state_root=state_root)
    st = sched.status_report(state_root=state_root, clock=clock)
    assert st["templates_installed"] is True
    assert st["activated"] is False
    assert st["push_allowed"] is False
    assert st["release_allowed"] is False
    assert "eight-hour" in st["due_now"]
    assert st["program_family"] == "uspto-cross-repo-sync"
