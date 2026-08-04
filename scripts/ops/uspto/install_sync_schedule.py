#!/usr/bin/env python3
"""PATLAW-162: Install recurring fetch, integration, and release triggers.

Idempotent **template generation** for systemd timers/units and cron fragments
covering:

* ``eight-hour`` — periodic fetch-only (every 8 hours)
* ``twice-daily`` — periodic isolated-worktree integration (every 12 hours)
* ``wave-boundary`` — wave-boundary integration slot (default 24 hours;
  maps to the ``twice-daily`` sync trigger)
* ``pre-release`` — on-demand release-gate integration (blocking)
* ``security-fix`` — on-demand security-fix integration

Hard policy (fail-closed):

* Templates are written under a state root; they are **never** enabled in
  systemd or installed into a user crontab without an explicit
  ``--activate-templates`` (operator opt-in).
* Repeated ``install`` is content-idempotent.
* All scheduled runs serialize through one **program-family** lock shared with
  ``sync_upstreams.sh`` / the integrator (never overlap).
* Missed-run recovery fires **at most one** catch-up per trigger regardless of
  how many intervals were skipped (fake-clock testable).
* Pre-release blocking: a release gate is refused when no accepted pre-release
  paired-revision receipt is present within the configured freshness window.
* Every schedule run produces or **references** a paired-revision receipt and
  **never pushes**.

CLI surface::

    install_sync_schedule.py install [--dry-run] [--template-dir DIR]
    install_sync_schedule.py activate --activate-templates
    install_sync_schedule.py uninstall
    install_sync_schedule.py status
    install_sync_schedule.py tick [--dry-run]          # schedule engine step
    install_sync_schedule.py check-release-gate
    install_sync_schedule.py list-triggers
    install_sync_schedule.py --offline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Protocol

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uspto.cross-repo-sync-schedule.v1"
INTERFACE: Final = "UsptoCrossRepoSyncSchedule@1"
PROGRAM_FAMILY: Final = "uspto-cross-repo-sync"
INSTALL_MANIFEST_NAME: Final = "install_manifest.json"
SCHEDULE_STATE_NAME: Final = "schedule_state.json"
ACTIVATION_MARKER_NAME: Final = "ACTIVATED"
RUN_LOG_DIR_NAME: Final = "runs"
DEFAULT_LOCK_NAME: Final = "sync.lock"
DEFAULT_PRE_RELEASE_MAX_AGE_SECONDS: Final = 24 * 3600

# Schedule slot names (operator-facing). Wave-boundary is schedule-level and
# maps onto an existing sync trigger so integrator/checker contracts stay stable.
SCHEDULE_TRIGGERS: Final = (
    "eight-hour",
    "twice-daily",
    "wave-boundary",
    "pre-release",
    "security-fix",
)

# Sync-script triggers that install may invoke (subset of PATLAW-080/161).
SYNC_TRIGGERS: Final = (
    "startup",
    "eight-hour",
    "twice-daily",
    "pre-release",
    "security-fix",
)

FETCH_ONLY_SYNC: Final = frozenset({"startup", "eight-hour"})
INTEGRATION_SYNC: Final = frozenset({"twice-daily", "pre-release", "security-fix"})

# Map schedule slot → sync_upstreams.sh --trigger value.
SCHEDULE_TO_SYNC_TRIGGER: Final = {
    "eight-hour": "eight-hour",
    "twice-daily": "twice-daily",
    "wave-boundary": "twice-daily",  # wave boundary reuses integration path
    "pre-release": "pre-release",
    "security-fix": "security-fix",
}

# Cadence: None means on-demand (no automatic tick due).
DEFAULT_INTERVALS_SECONDS: Final = {
    "eight-hour": 8 * 3600,
    "twice-daily": 12 * 3600,
    "wave-boundary": 24 * 3600,
    "pre-release": None,
    "security-fix": None,
}

ON_DEMAND_TRIGGERS: Final = frozenset({"pre-release", "security-fix"})
PERIODIC_TRIGGERS: Final = frozenset(
    t for t in SCHEDULE_TRIGGERS if t not in ON_DEMAND_TRIGGERS
)

POLICY: Final = {
    "push_allowed": False,
    "operator_activation_required": True,
    "edit_user_crontab": False,
    "enable_systemd_without_opt_in": False,
    "serialize_via_program_family_lock": True,
    "program_family": PROGRAM_FAMILY,
    "missed_run_recovery": "single_catch_up",
    "pre_release_blocks_release": True,
    "paired_revision_receipt_required": True,
}

UTC_TS_RE: Final = __import__("re").compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_DEFAULT_SYNC_SH: Final = _REPO_ROOT / "scripts" / "ops" / "uspto" / "sync_upstreams.sh"


class ScheduleError(RuntimeError):
    """Fail-closed schedule / install policy violation."""


class PreReleaseBlocked(ScheduleError):
    """Release gate refused: pre-release receipt missing or stale."""


# ---------------------------------------------------------------------------
# Clocks (injectable for fake-clock tests)
# ---------------------------------------------------------------------------


class Clock(Protocol):
    def now(self) -> float:
        """Unix epoch seconds (UTC)."""
        ...

    def utc_iso(self) -> str:
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def utc_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeClock:
    """Controllable wall clock for cadence / missed-run / blocking tests."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = float(start)
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> float:
        with self._lock:
            self._now += float(seconds)
            return self._now

    def set(self, epoch: float) -> None:
        with self._lock:
            self._now = float(epoch)

    def utc_iso(self) -> str:
        return datetime.fromtimestamp(self.now(), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )


# ---------------------------------------------------------------------------
# Paths / JSON helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def atomic_write_text(path: Path, text: str, *, mode: int = 0o644) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_state_root() -> Path:
    home = os.environ.get("HOME") or os.environ.get("TMPDIR") or "/tmp"
    xdg = os.environ.get("XDG_STATE_HOME") or str(Path(home) / ".local" / "state")
    return (
        Path(xdg)
        / "ipfs_accelerate_py"
        / "uspto_submission_assurance"
        / "cross_repo_sync"
    )


def resolve_state_root(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("CROSS_REPO_SYNC_STATE_ROOT")
    if env:
        return Path(env)
    return default_state_root()


def program_family_lock_path(state_root: Path) -> Path:
    """Single lock shared with sync_upstreams.sh / integrate_upstreams.py."""
    env = os.environ.get("CROSS_REPO_SYNC_LOCK_PATH")
    if env:
        return Path(env)
    return Path(state_root) / DEFAULT_LOCK_NAME


# ---------------------------------------------------------------------------
# Program-family lock (mutual exclusion across all schedule + sync runs)
# ---------------------------------------------------------------------------


class ProgramFamilyLock:
    """Fail-closed serialization lock for the entire cross-repo sync family."""

    def __init__(
        self,
        path: Path,
        *,
        dry_run: bool = False,
        identity: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.dry_run = dry_run
        self.identity = identity or f"schedule-pid-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.method = "none"
        self.acquired = False
        self._fd: int | None = None
        self._lock_dir: Path | None = None

    def try_acquire(self) -> bool:
        if self.dry_run:
            self.method = "dry-run"
            self.acquired = True
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl

            self._fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(self._fd)
                self._fd = None
                return False
            try:
                os.ftruncate(self._fd, 0)
                os.lseek(self._fd, 0, os.SEEK_SET)
            except OSError:
                pass
            os.write(self._fd, f"{self.identity}\n".encode("utf-8"))
            try:
                os.fsync(self._fd)
            except OSError:
                pass
            self.method = "flock"
            self.acquired = True
            return True
        except ImportError:
            pass
        except OSError:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None

        lock_dir = Path(f"{self.path}.d")
        try:
            lock_dir.mkdir(exist_ok=False)
        except FileExistsError:
            return False
        (lock_dir / "pid").write_text(f"{self.identity}\n", encoding="utf-8")
        self._lock_dir = lock_dir
        self.method = "mkdir"
        self.acquired = True
        return True

    def release(self) -> None:
        if self.method == "flock" and self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._lock_dir is not None:
            try:
                shutil.rmtree(self._lock_dir, ignore_errors=True)
            except OSError:
                pass
            self._lock_dir = None
        self.acquired = False
        self.method = "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "identity": self.identity,
            "method": self.method,
            "acquired": self.acquired,
            "program_family": PROGRAM_FAMILY,
        }

    def __enter__(self) -> ProgramFamilyLock:
        if not self.try_acquire():
            raise ScheduleError(
                f"program-family lock held: {self.path} (mutual exclusion)"
            )
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Schedule state
# ---------------------------------------------------------------------------


@dataclass
class TriggerRuntime:
    last_due_at: float | None = None
    last_started_at: float | None = None
    last_completed_at: float | None = None
    last_status: str | None = None  # success | failed | skipped | blocked | dry-run
    last_receipt_path: str | None = None
    last_run_id: str | None = None
    consecutive_misses_recovered: int = 0
    run_count: int = 0
    success_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TriggerRuntime:
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            last_due_at=_as_float_or_none(data.get("last_due_at")),
            last_started_at=_as_float_or_none(data.get("last_started_at")),
            last_completed_at=_as_float_or_none(data.get("last_completed_at")),
            last_status=_as_str_or_none(data.get("last_status")),
            last_receipt_path=_as_str_or_none(data.get("last_receipt_path")),
            last_run_id=_as_str_or_none(data.get("last_run_id")),
            consecutive_misses_recovered=int(
                data.get("consecutive_misses_recovered") or 0
            ),
            run_count=int(data.get("run_count") or 0),
            success_count=int(data.get("success_count") or 0),
        )


def _as_float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass
class ScheduleState:
    schema_version: str = SCHEMA_VERSION
    interface: str = INTERFACE
    program_family: str = PROGRAM_FAMILY
    activated: bool = False
    activated_at_utc: str | None = None
    intervals: dict[str, int | None] = field(
        default_factory=lambda: dict(DEFAULT_INTERVALS_SECONDS)
    )
    triggers: dict[str, TriggerRuntime] = field(default_factory=dict)
    last_tick_at: float | None = None
    last_receipt_path: str | None = None  # most recent paired receipt reference
    release_blocked: bool = False
    release_block_reason: str | None = None
    updated_at_utc: str | None = None

    def ensure_triggers(self) -> None:
        for name in SCHEDULE_TRIGGERS:
            if name not in self.triggers:
                self.triggers[name] = TriggerRuntime()
            if name not in self.intervals:
                self.intervals[name] = DEFAULT_INTERVALS_SECONDS.get(name)

    def to_dict(self) -> dict[str, Any]:
        self.ensure_triggers()
        return {
            "schema_version": self.schema_version,
            "interface": self.interface,
            "program_family": self.program_family,
            "activated": self.activated,
            "activated_at_utc": self.activated_at_utc,
            "intervals": {
                k: self.intervals.get(k) for k in SCHEDULE_TRIGGERS
            },
            "triggers": {
                k: self.triggers[k].to_dict() for k in SCHEDULE_TRIGGERS
            },
            "last_tick_at": self.last_tick_at,
            "last_receipt_path": self.last_receipt_path,
            "release_blocked": self.release_blocked,
            "release_block_reason": self.release_block_reason,
            "updated_at_utc": self.updated_at_utc,
            "policy": dict(POLICY),
            "schedule_to_sync_trigger": dict(SCHEDULE_TO_SYNC_TRIGGER),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScheduleState:
        intervals_raw = data.get("intervals") if isinstance(data.get("intervals"), Mapping) else {}
        intervals: dict[str, int | None] = dict(DEFAULT_INTERVALS_SECONDS)
        if isinstance(intervals_raw, Mapping):
            for k, v in intervals_raw.items():
                if k in SCHEDULE_TRIGGERS:
                    if v is None:
                        intervals[str(k)] = None
                    else:
                        try:
                            intervals[str(k)] = int(v)
                        except (TypeError, ValueError):
                            pass
        triggers_raw = data.get("triggers") if isinstance(data.get("triggers"), Mapping) else {}
        triggers: dict[str, TriggerRuntime] = {}
        if isinstance(triggers_raw, Mapping):
            for k, v in triggers_raw.items():
                if k in SCHEDULE_TRIGGERS:
                    triggers[str(k)] = TriggerRuntime.from_dict(
                        v if isinstance(v, Mapping) else None
                    )
        st = cls(
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
            interface=str(data.get("interface") or INTERFACE),
            program_family=str(data.get("program_family") or PROGRAM_FAMILY),
            activated=bool(data.get("activated")),
            activated_at_utc=_as_str_or_none(data.get("activated_at_utc")),
            intervals=intervals,
            triggers=triggers,
            last_tick_at=_as_float_or_none(data.get("last_tick_at")),
            last_receipt_path=_as_str_or_none(data.get("last_receipt_path")),
            release_blocked=bool(data.get("release_blocked")),
            release_block_reason=_as_str_or_none(data.get("release_block_reason")),
            updated_at_utc=_as_str_or_none(data.get("updated_at_utc")),
        )
        st.ensure_triggers()
        return st


class ScheduleStateStore:
    def __init__(self, state_root: Path, *, clock: Clock | None = None) -> None:
        self.state_root = Path(state_root)
        self.path = self.state_root / SCHEDULE_STATE_NAME
        self.clock = clock or SystemClock()

    def load(self) -> ScheduleState:
        if not self.path.is_file():
            st = ScheduleState()
            st.ensure_triggers()
            return st
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ScheduleError(f"schedule state root must be object: {self.path}")
        return ScheduleState.from_dict(data)

    def save(self, state: ScheduleState) -> None:
        state.ensure_triggers()
        state.updated_at_utc = self.clock.utc_iso()
        atomic_write_text(self.path, json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Due / missed-run logic (fake-clock testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DueDecision:
    schedule_trigger: str
    sync_trigger: str
    due_at: float
    missed_intervals: int
    catch_up: bool
    reason: str


def compute_due_triggers(
    state: ScheduleState,
    *,
    now: float,
    only: Sequence[str] | None = None,
    force: Sequence[str] | None = None,
) -> list[DueDecision]:
    """Return due schedule slots.

    Missed-run recovery: when multiple intervals have elapsed since
    ``last_completed_at``, emit a **single** catch-up decision (not one per
    missed interval). On-demand triggers are due only when ``force`` names them.
    """
    state.ensure_triggers()
    force_set = set(force or ())
    only_set = set(only) if only is not None else None
    decisions: list[DueDecision] = []

    for name in SCHEDULE_TRIGGERS:
        if only_set is not None and name not in only_set:
            continue
        sync_trigger = SCHEDULE_TO_SYNC_TRIGGER[name]
        interval = state.intervals.get(name)
        tr = state.triggers[name]

        if name in force_set:
            decisions.append(
                DueDecision(
                    schedule_trigger=name,
                    sync_trigger=sync_trigger,
                    due_at=now,
                    missed_intervals=0,
                    catch_up=False,
                    reason="forced",
                )
            )
            continue

        if interval is None:
            # On-demand: never auto-due.
            continue

        interval_f = float(interval)
        if interval_f <= 0:
            continue

        anchor = tr.last_completed_at
        if anchor is None:
            # Never run: due immediately at first tick (cadence start).
            decisions.append(
                DueDecision(
                    schedule_trigger=name,
                    sync_trigger=sync_trigger,
                    due_at=now,
                    missed_intervals=0,
                    catch_up=False,
                    reason="initial",
                )
            )
            continue

        elapsed = now - float(anchor)
        if elapsed < interval_f:
            continue

        # Number of full intervals that would have fired (excluding the catch-up
        # we are about to run once). At least 1 when due.
        full = int(elapsed // interval_f)
        missed_extra = max(0, full - 1)
        decisions.append(
            DueDecision(
                schedule_trigger=name,
                sync_trigger=sync_trigger,
                due_at=now,
                missed_intervals=missed_extra,
                catch_up=missed_extra > 0,
                reason="catch_up" if missed_extra > 0 else "interval",
            )
        )

    # Deterministic order: periodic first (by schedule name), then on-demand force.
    order = {n: i for i, n in enumerate(SCHEDULE_TRIGGERS)}
    decisions.sort(key=lambda d: order.get(d.schedule_trigger, 999))
    return decisions


def next_due_at(state: ScheduleState, schedule_trigger: str, *, now: float) -> float | None:
    state.ensure_triggers()
    interval = state.intervals.get(schedule_trigger)
    if interval is None:
        return None
    tr = state.triggers[schedule_trigger]
    if tr.last_completed_at is None:
        return now
    return float(tr.last_completed_at) + float(interval)


# ---------------------------------------------------------------------------
# Pre-release blocking
# ---------------------------------------------------------------------------


def evaluate_pre_release_gate(
    state: ScheduleState,
    *,
    now: float,
    max_age_seconds: float = DEFAULT_PRE_RELEASE_MAX_AGE_SECONDS,
    require_receipt_file: bool = True,
) -> dict[str, Any]:
    """Return gate evaluation. ``allowed`` is False when release must block."""
    state.ensure_triggers()
    tr = state.triggers["pre-release"]
    receipt = tr.last_receipt_path or state.last_receipt_path
    result: dict[str, Any] = {
        "allowed": False,
        "reason": "pre_release_never_succeeded",
        "last_success_at": tr.last_completed_at if tr.last_status == "success" else None,
        "last_receipt_path": receipt,
        "max_age_seconds": float(max_age_seconds),
        "now": now,
        "status": tr.last_status,
    }

    if tr.last_status != "success" or tr.last_completed_at is None:
        result["reason"] = "pre_release_never_succeeded"
        return result

    age = now - float(tr.last_completed_at)
    result["age_seconds"] = age
    if age > float(max_age_seconds):
        result["reason"] = "pre_release_stale"
        return result

    if require_receipt_file:
        if not receipt or not Path(receipt).is_file():
            result["reason"] = "pre_release_receipt_missing"
            return result
        # Light validation: file should look like a paired-revision receipt.
        try:
            payload = json.loads(Path(receipt).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result["reason"] = "pre_release_receipt_unreadable"
            return result
        if not isinstance(payload, dict):
            result["reason"] = "pre_release_receipt_invalid"
            return result
        schema = str(payload.get("schema_version") or "")
        if "paired-revision" not in schema and payload.get("trigger") != "pre-release":
            # Accept either schema marker or explicit pre-release trigger binding.
            if payload.get("push_attempted") is not False and "push_attempted" in payload:
                result["reason"] = "pre_release_receipt_invalid"
                return result
        if payload.get("push_attempted") is True:
            result["reason"] = "pre_release_receipt_pushed"
            return result
        if str(payload.get("status") or "") not in {"accepted", "aborted", "rejected", "quarantined"}:
            # Still allow aborted receipts only for gate if status is accepted.
            pass
        if str(payload.get("status") or "") != "accepted":
            result["reason"] = "pre_release_not_accepted"
            return result
        if payload.get("trigger") not in (None, "pre-release"):
            # Prefer pre-release binding when present.
            if payload.get("trigger") != "pre-release":
                result["reason"] = "pre_release_trigger_mismatch"
                return result

    result["allowed"] = True
    result["reason"] = "ok"
    return result


def assert_release_allowed(
    state: ScheduleState,
    *,
    now: float,
    max_age_seconds: float = DEFAULT_PRE_RELEASE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    gate = evaluate_pre_release_gate(
        state, now=now, max_age_seconds=max_age_seconds, require_receipt_file=True
    )
    if not gate["allowed"]:
        raise PreReleaseBlocked(
            f"release blocked: {gate['reason']} "
            f"(max_age_seconds={max_age_seconds})"
        )
    return gate


# ---------------------------------------------------------------------------
# Template generation (systemd + cron) — never auto-enabled
# ---------------------------------------------------------------------------


UNIT_PREFIX: Final = "uspto-cross-repo-sync"


def _sync_command_line(
    *,
    sync_sh: Path,
    schedule_trigger: str,
    state_root: Path,
    python_bin: str = "python3",
) -> str:
    sync_trigger = SCHEDULE_TO_SYNC_TRIGGER[schedule_trigger]
    # Schedule runner wraps the shell script so lock/receipt bookkeeping stays
    # in this module when invoked from timers; timers call install_sync_schedule.
    installer = Path(__file__).resolve()
    return (
        f"{python_bin} {installer} run-trigger "
        f"--schedule-trigger {schedule_trigger} "
        f"--sync-trigger {sync_trigger} "
        f"--state-root {state_root} "
        f"--sync-sh {sync_sh}"
    )


def render_systemd_service(
    schedule_trigger: str,
    *,
    sync_sh: Path,
    state_root: Path,
    description: str | None = None,
) -> str:
    desc = description or f"USPTO cross-repo sync ({schedule_trigger})"
    cmd = _sync_command_line(
        sync_sh=sync_sh, schedule_trigger=schedule_trigger, state_root=state_root
    )
    return f"""# Generated by install_sync_schedule.py (PATLAW-162)
# TEMPLATE ONLY — not enabled until operator runs:
#   install_sync_schedule.py activate --activate-templates
# Program family: {PROGRAM_FAMILY}
# Never push. Never edit user crontabs from install.

[Unit]
Description={desc}
Documentation=file://{Path(__file__).resolve()}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=CROSS_REPO_SYNC_STATE_ROOT={state_root}
Environment=CROSS_REPO_SYNC_LOCK_PATH={state_root / DEFAULT_LOCK_NAME}
Environment=CROSS_REPO_SYNC_SCHEDULE_TRIGGER={schedule_trigger}
Environment=CROSS_REPO_SYNC_PUSH_ALLOWED=0
ExecStart={cmd}
Nice=10

[Install]
WantedBy=multi-user.target
"""


def render_systemd_timer(
    schedule_trigger: str,
    *,
    interval_seconds: int | None,
    persistent: bool = True,
) -> str:
    if interval_seconds is None:
        on_calendar = "# OnCalendar= (on-demand; start via systemctl start ….service)"
        on_unit = "# OnUnitActiveSec="
        accuracy = "AccuracySec=1min"
    elif interval_seconds == 8 * 3600:
        on_calendar = "OnCalendar=*-*-* 00/8:00:00"
        on_unit = "OnUnitActiveSec=8h"
        accuracy = "AccuracySec=5min"
    elif interval_seconds == 12 * 3600:
        on_calendar = "OnCalendar=*-*-* 00,12:00:00"
        on_unit = "OnUnitActiveSec=12h"
        accuracy = "AccuracySec=5min"
    elif interval_seconds == 24 * 3600:
        on_calendar = "OnCalendar=*-*-* 06:00:00"
        on_unit = "OnUnitActiveSec=24h"
        accuracy = "AccuracySec=5min"
    else:
        hours = max(1, int(interval_seconds // 3600))
        on_calendar = f"OnCalendar=*-*-* 00/{hours}:00:00"
        on_unit = f"OnUnitActiveSec={interval_seconds}s"
        accuracy = "AccuracySec=5min"

    unit_name = f"{UNIT_PREFIX}-{schedule_trigger}.service"
    persistent_line = "Persistent=true" if persistent and interval_seconds else "Persistent=false"
    return f"""# Generated by install_sync_schedule.py (PATLAW-162)
# TEMPLATE ONLY — operator must activate explicitly.
# Missed-run recovery: Persistent=true + single catch-up in schedule engine.

[Unit]
Description=Timer for {UNIT_PREFIX}-{schedule_trigger}
Requires={unit_name}

[Timer]
{on_calendar}
{on_unit}
{persistent_line}
{accuracy}
Unit={unit_name}

[Install]
WantedBy=timers.target
"""


def render_cron_fragment(
    schedule_trigger: str,
    *,
    sync_sh: Path,
    state_root: Path,
    interval_seconds: int | None,
) -> str:
    cmd = _sync_command_line(
        sync_sh=sync_sh, schedule_trigger=schedule_trigger, state_root=state_root
    )
    if interval_seconds is None:
        schedule = f"# on-demand {schedule_trigger}: no automatic cron line"
        body = f"# {cmd}"
    elif interval_seconds == 8 * 3600:
        schedule = "0 */8 * * *"
        body = cmd
    elif interval_seconds == 12 * 3600:
        schedule = "0 0,12 * * *"
        body = cmd
    elif interval_seconds == 24 * 3600:
        schedule = "0 6 * * *"
        body = cmd
    else:
        hours = max(1, int(interval_seconds // 3600))
        schedule = f"0 */{hours} * * *"
        body = cmd
    return f"""# Generated by install_sync_schedule.py (PATLAW-162)
# TEMPLATE ONLY — do NOT install into user crontab automatically.
# Operator must copy/enable explicitly after activate --activate-templates.
# Program family lock: {state_root / DEFAULT_LOCK_NAME}
# push_allowed=false

{schedule} {body}
"""


def render_activation_readme(state_root: Path) -> str:
    return f"""# USPTO cross-repo sync schedule templates (PATLAW-162)

These files are **templates only**.

## Policy

* Install is idempotent and never enables systemd timers or rewrites crontabs.
* Operator must run:

      python3 scripts/ops/uspto/install_sync_schedule.py activate --activate-templates \\
        --state-root {state_root}

* Then **manually** enable units or install cron fragments if desired:

      # example (operator-owned machine):
      # cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
      # systemctl --user daemon-reload
      # systemctl --user enable --now uspto-cross-repo-sync-eight-hour.timer

* All triggers share one program-family lock (`sync.lock`) — mutual exclusion.
* Every run produces or references a paired-revision receipt; **never pushes**.

## Triggers

| Schedule slot   | Cadence     | Sync trigger  | Mode        |
|-----------------|-------------|---------------|-------------|
| eight-hour      | 8 hours     | eight-hour    | fetch-only  |
| twice-daily     | 12 hours    | twice-daily   | integration |
| wave-boundary   | 24 hours    | twice-daily   | integration |
| pre-release     | on-demand   | pre-release   | integration |
| security-fix    | on-demand   | security-fix  | integration |
"""


@dataclass
class GeneratedTemplate:
    relative_path: str
    content: str

    @property
    def digest(self) -> str:
        return sha256_text(self.content)


def generate_templates(
    *,
    state_root: Path,
    sync_sh: Path | None = None,
    intervals: Mapping[str, int | None] | None = None,
) -> list[GeneratedTemplate]:
    sync = Path(sync_sh) if sync_sh else _DEFAULT_SYNC_SH
    iv = dict(DEFAULT_INTERVALS_SECONDS)
    if intervals:
        iv.update({k: intervals[k] for k in intervals if k in SCHEDULE_TRIGGERS})

    out: list[GeneratedTemplate] = []
    out.append(
        GeneratedTemplate(
            relative_path="README.md",
            content=render_activation_readme(state_root),
        )
    )
    for name in SCHEDULE_TRIGGERS:
        interval = iv.get(name)
        out.append(
            GeneratedTemplate(
                relative_path=f"systemd/{UNIT_PREFIX}-{name}.service",
                content=render_systemd_service(
                    name, sync_sh=sync, state_root=state_root
                ),
            )
        )
        out.append(
            GeneratedTemplate(
                relative_path=f"systemd/{UNIT_PREFIX}-{name}.timer",
                content=render_systemd_timer(name, interval_seconds=interval),
            )
        )
        out.append(
            GeneratedTemplate(
                relative_path=f"cron/{UNIT_PREFIX}-{name}.cron",
                content=render_cron_fragment(
                    name,
                    sync_sh=sync,
                    state_root=state_root,
                    interval_seconds=interval,
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Install / activate / uninstall / status
# ---------------------------------------------------------------------------


def template_dir_for(state_root: Path, explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("CROSS_REPO_SYNC_TEMPLATE_DIR")
    if env:
        return Path(env)
    return Path(state_root) / "schedule_templates"


def install_templates(
    *,
    state_root: Path,
    template_dir: Path | None = None,
    sync_sh: Path | None = None,
    dry_run: bool = False,
    intervals: Mapping[str, int | None] | None = None,
) -> dict[str, Any]:
    """Write (or plan) templates. Never activates. Idempotent on content."""
    state_root = Path(state_root)
    tdir = template_dir_for(state_root, template_dir)
    templates = generate_templates(
        state_root=state_root, sync_sh=sync_sh, intervals=intervals
    )
    file_records: list[dict[str, Any]] = []
    changed = 0
    unchanged = 0
    planned: list[str] = []

    for tmpl in templates:
        dest = tdir / tmpl.relative_path
        digest = tmpl.digest
        exists = dest.is_file()
        same = False
        if exists:
            try:
                same = sha256_text(dest.read_text(encoding="utf-8")) == digest
            except OSError:
                same = False
        action = "unchanged" if same else ("create" if not exists else "update")
        if action == "unchanged":
            unchanged += 1
        else:
            changed += 1
            planned.append(tmpl.relative_path)
            if not dry_run:
                atomic_write_text(dest, tmpl.content)
        file_records.append(
            {
                "path": str(dest),
                "relative_path": tmpl.relative_path,
                "digest": digest,
                "action": action,
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "program_family": PROGRAM_FAMILY,
        "state_root": str(state_root),
        "template_dir": str(tdir),
        "generated_at_utc": utc_now_iso(),
        "dry_run": dry_run,
        "activated": False,
        "operator_activation_required": True,
        "push_allowed": False,
        "edit_user_crontab": False,
        "files": file_records,
        "schedule_triggers": list(SCHEDULE_TRIGGERS),
        "policy": dict(POLICY),
        "changed": changed,
        "unchanged": unchanged,
        "idempotent": changed == 0 and unchanged == len(templates),
    }

    # Preserve activation flag if already activated.
    store = ScheduleStateStore(state_root)
    state = store.load()
    if state.activated:
        manifest["activated"] = True

    if not dry_run:
        atomic_write_text(
            tdir / INSTALL_MANIFEST_NAME,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        # Ensure schedule state exists without activating.
        store.save(state)

    report = {
        "ok": True,
        "action": "install",
        "dry_run": dry_run,
        "template_dir": str(tdir),
        "state_root": str(state_root),
        "changed": changed,
        "unchanged": unchanged,
        "planned_writes": planned,
        "activated": bool(state.activated),
        "operator_activation_required": not bool(state.activated),
        "push_allowed": False,
        "manifest": manifest if dry_run else None,
        "manifest_path": str(tdir / INSTALL_MANIFEST_NAME) if not dry_run else None,
    }
    return report


def activate_templates(
    *,
    state_root: Path,
    template_dir: Path | None = None,
    activate_templates_flag: bool = False,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Mark templates as operator-activated. Does **not** enable systemd/cron."""
    if not activate_templates_flag:
        raise ScheduleError(
            "refusing to activate: pass --activate-templates for explicit operator opt-in"
        )
    clock = clock or SystemClock()
    state_root = Path(state_root)
    tdir = template_dir_for(state_root, template_dir)
    if not tdir.is_dir():
        raise ScheduleError(
            f"templates not installed at {tdir}; run install first"
        )
    marker = tdir / ACTIVATION_MARKER_NAME
    atomic_write_text(
        marker,
        json.dumps(
            {
                "activated": True,
                "activated_at_utc": clock.utc_iso(),
                "program_family": PROGRAM_FAMILY,
                "note": (
                    "Templates activated for operator use. systemd/cron still "
                    "require manual enable; this tool never rewrites user crontabs."
                ),
                "push_allowed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    store = ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    state.activated = True
    state.activated_at_utc = clock.utc_iso()
    store.save(state)

    # Update install manifest if present.
    manifest_path = tdir / INSTALL_MANIFEST_NAME
    if manifest_path.is_file():
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(man, dict):
                man["activated"] = True
                man["activated_at_utc"] = state.activated_at_utc
                atomic_write_text(
                    manifest_path, json.dumps(man, indent=2, sort_keys=True) + "\n"
                )
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "ok": True,
        "action": "activate",
        "activated": True,
        "activated_at_utc": state.activated_at_utc,
        "template_dir": str(tdir),
        "marker": str(marker),
        "systemd_enabled": False,
        "crontab_modified": False,
        "push_allowed": False,
        "note": "Operator must still manually enable timers/cron if desired.",
    }


def uninstall_templates(
    *,
    state_root: Path,
    template_dir: Path | None = None,
    dry_run: bool = False,
    keep_state: bool = True,
) -> dict[str, Any]:
    """Remove generated templates and activation marker. Never touches real crontabs."""
    state_root = Path(state_root)
    tdir = template_dir_for(state_root, template_dir)
    removed: list[str] = []
    if tdir.is_dir():
        for p in sorted(tdir.rglob("*"), reverse=True):
            removed.append(str(p))
            if not dry_run:
                if p.is_file() or p.is_symlink():
                    try:
                        p.unlink()
                    except OSError:
                        pass
                elif p.is_dir():
                    try:
                        p.rmdir()
                    except OSError:
                        pass
        if not dry_run:
            try:
                tdir.rmdir()
            except OSError:
                pass

    store = ScheduleStateStore(state_root)
    if not keep_state and not dry_run:
        sp = store.path
        if sp.is_file():
            sp.unlink()
            removed.append(str(sp))
    else:
        state = store.load()
        state.activated = False
        state.activated_at_utc = None
        if not dry_run:
            store.save(state)

    return {
        "ok": True,
        "action": "uninstall",
        "dry_run": dry_run,
        "template_dir": str(tdir),
        "removed_count": len(removed),
        "removed": removed[:200],
        "crontab_modified": False,
        "systemd_disabled": False,
        "note": "Only generated templates removed; system crontabs untouched.",
    }


def status_report(
    *,
    state_root: Path,
    template_dir: Path | None = None,
    clock: Clock | None = None,
    pre_release_max_age: float = DEFAULT_PRE_RELEASE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    clock = clock or SystemClock()
    state_root = Path(state_root)
    tdir = template_dir_for(state_root, template_dir)
    store = ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    now = clock.now()
    gate = evaluate_pre_release_gate(
        state, now=now, max_age_seconds=pre_release_max_age, require_receipt_file=False
    )
    # When receipt path exists, re-check strictly for status detail.
    if state.triggers.get("pre-release") and state.triggers["pre-release"].last_receipt_path:
        gate = evaluate_pre_release_gate(
            state, now=now, max_age_seconds=pre_release_max_age, require_receipt_file=True
        )

    templates_present = (tdir / INSTALL_MANIFEST_NAME).is_file() or tdir.is_dir()
    activation_marker = (tdir / ACTIVATION_MARKER_NAME).is_file()

    due = compute_due_triggers(state, now=now)
    next_dues = {
        name: next_due_at(state, name, now=now) for name in PERIODIC_TRIGGERS
    }

    lock_path = program_family_lock_path(state_root)
    lock_held = False
    if lock_path.is_file() or Path(f"{lock_path}.d").exists():
        probe = ProgramFamilyLock(lock_path)
        if not probe.try_acquire():
            lock_held = True
        else:
            probe.release()

    return {
        "ok": True,
        "action": "status",
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "program_family": PROGRAM_FAMILY,
        "state_root": str(state_root),
        "template_dir": str(tdir),
        "templates_installed": templates_present,
        "activated": bool(state.activated or activation_marker),
        "activation_marker": activation_marker,
        "operator_activation_required": not bool(state.activated or activation_marker),
        "lock_path": str(lock_path),
        "lock_held": lock_held,
        "push_allowed": False,
        "last_receipt_path": state.last_receipt_path,
        "pre_release_gate": gate,
        "release_allowed": bool(gate.get("allowed")),
        "due_now": [d.schedule_trigger for d in due],
        "next_due_at": next_dues,
        "intervals": {k: state.intervals.get(k) for k in SCHEDULE_TRIGGERS},
        "triggers": {k: state.triggers[k].to_dict() for k in SCHEDULE_TRIGGERS},
        "policy": dict(POLICY),
        "now": now,
        "now_utc": clock.utc_iso(),
    }


# ---------------------------------------------------------------------------
# Run trigger (invokes sync_upstreams.sh under program-family lock)
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    schedule_trigger: str
    sync_trigger: str
    run_id: str
    status: str
    exit_code: int
    receipt_path: str | None
    receipt_referenced: bool
    push_attempted: bool
    lock: dict[str, Any]
    started_at: float
    completed_at: float
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False
    catch_up: bool = False
    missed_intervals: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SyncRunner = Callable[..., RunResult]


def default_receipt_path(state_root: Path, schedule_trigger: str) -> Path:
    return Path(state_root) / "receipts" / f"{schedule_trigger}.paired_revision_receipt.json"


def _synthetic_receipt(
    *,
    sync_trigger: str,
    schedule_trigger: str,
    run_id: str,
    status: str = "accepted",
    disposition: str = "fetch_only",
    lock: Mapping[str, Any] | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    clock = clock or SystemClock()
    ts = clock.utc_iso()
    return {
        "schema_version": "uspto.paired-revision-receipt.v1",
        "interface": "UsptoPairedRevisionReceipt@1",
        "receipt_id": f"sched-{run_id}",
        "status": status,
        "disposition": disposition,
        "trigger": sync_trigger,
        "schedule_trigger": schedule_trigger,
        "datasets": {
            "name": "datasets",
            "before_sha": "0" * 40,
            "remote_sha": "0" * 40,
            "integrated_sha": None,
        },
        "accelerator": {
            "name": "accelerator",
            "before_sha": "0" * 40,
            "remote_sha": "0" * 40,
            "integrated_sha": None,
        },
        "capability_pin": None,
        "merge_order": ["accelerator", "datasets"],
        "merge_trace": [],
        "test_results": [],
        "lock": dict(lock or {"path": "", "identity": run_id, "method": "none", "acquired": False}),
        "policy": {
            "push_allowed": False,
            "active_worktree_pull_allowed": False,
            "recursive_submodules": False,
            "require_clean_worktree": True,
            "fail_closed_on_conflict": True,
            "serialize_integrations": True,
            "use_isolated_worktrees": True,
            "merge_order": ["accelerator", "datasets"],
            "fetch_only_triggers": sorted(FETCH_ONLY_SYNC),
            "integration_triggers": sorted(INTEGRATION_SYNC),
        },
        "started_at_utc": ts,
        "completed_at_utc": ts,
        "mutation_attempted": False,
        "push_attempted": False,
        "active_worktree_pull_attempted": False,
        "recursive_submodule_chase": False,
        "notes": [
            f"schedule_trigger={schedule_trigger}",
            "produced_or_referenced_by=install_sync_schedule",
        ],
    }


def invoke_sync_upstreams(
    *,
    schedule_trigger: str,
    sync_trigger: str,
    state_root: Path,
    sync_sh: Path,
    lock: ProgramFamilyLock,
    clock: Clock,
    dry_run: bool = False,
    skip_fetch: bool = True,
    python_bin: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    catch_up: bool = False,
    missed_intervals: int = 0,
    reason: str = "",
    timeout: float | None = 600.0,
) -> RunResult:
    """Invoke sync_upstreams.sh (or dry-run synthetic receipt). Lock must be held."""
    run_id = uuid.uuid4().hex[:12]
    started = clock.now()
    receipt_path = default_receipt_path(state_root, schedule_trigger)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        # Dry-run never shells out; still produces a receipt reference artifact.
        payload = _synthetic_receipt(
            sync_trigger=sync_trigger,
            schedule_trigger=schedule_trigger,
            run_id=run_id,
            status="accepted",
            disposition="fetch_only" if sync_trigger in FETCH_ONLY_SYNC else "integrated",
            lock=lock.as_dict(),
            clock=clock,
        )
        atomic_write_text(receipt_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return RunResult(
            schedule_trigger=schedule_trigger,
            sync_trigger=sync_trigger,
            run_id=run_id,
            status="dry-run",
            exit_code=0,
            receipt_path=str(receipt_path),
            receipt_referenced=True,
            push_attempted=False,
            lock=lock.as_dict(),
            started_at=started,
            completed_at=clock.now(),
            dry_run=True,
            catch_up=catch_up,
            missed_intervals=missed_intervals,
            reason=reason or "dry-run",
        )

    if not Path(sync_sh).is_file():
        # Fall back to synthetic aborted receipt so every run still references one.
        payload = _synthetic_receipt(
            sync_trigger=sync_trigger,
            schedule_trigger=schedule_trigger,
            run_id=run_id,
            status="aborted",
            disposition="aborted",
            lock=lock.as_dict(),
            clock=clock,
        )
        atomic_write_text(receipt_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return RunResult(
            schedule_trigger=schedule_trigger,
            sync_trigger=sync_trigger,
            run_id=run_id,
            status="failed",
            exit_code=2,
            receipt_path=str(receipt_path),
            receipt_referenced=True,
            push_attempted=False,
            lock=lock.as_dict(),
            started_at=started,
            completed_at=clock.now(),
            stderr=f"sync script missing: {sync_sh}",
            catch_up=catch_up,
            missed_intervals=missed_intervals,
            reason="sync_missing",
        )

    env = os.environ.copy()
    env["CROSS_REPO_SYNC_STATE_ROOT"] = str(state_root)
    env["CROSS_REPO_SYNC_LOCK_PATH"] = str(lock.path)
    env["CROSS_REPO_SYNC_SCHEDULE_TRIGGER"] = schedule_trigger
    env["CROSS_REPO_SYNC_PUSH_ALLOWED"] = "0"
    env["CROSS_REPO_INTEGRATE_OUTPUT_PATH"] = str(receipt_path)
    # Fetch-only checker still writes compatibility manifest; integration writes receipt.
    if sync_trigger in FETCH_ONLY_SYNC:
        env["CROSS_REPO_SYNC_OUTPUT_PATH"] = str(
            Path(state_root) / "receipts" / f"{schedule_trigger}.compatibility_manifest.json"
        )
    else:
        env["CROSS_REPO_SYNC_OUTPUT_PATH"] = str(receipt_path)
    if python_bin:
        env["CROSS_REPO_SYNC_PYTHON"] = python_bin
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})

    cmd = [
        "bash",
        str(sync_sh),
        "--trigger",
        sync_trigger,
        "--state-root",
        str(state_root),
        "--lock-path",
        str(lock.path),
        "--output",
        env["CROSS_REPO_SYNC_OUTPUT_PATH"],
    ]
    if skip_fetch:
        cmd.append("--skip-fetch")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=timeout,
        )
        rc = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = 124
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = f"timeout after {timeout}s"
    except OSError as exc:
        rc = 2
        stdout = ""
        stderr = str(exc)

    # Prefer integrator receipt; else reference/create paired receipt binder.
    out_path = Path(env["CROSS_REPO_SYNC_OUTPUT_PATH"])
    referenced = False
    final_receipt: Path | None = None
    if out_path.is_file():
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and (
            "paired-revision" in str(payload.get("schema_version") or "")
            or payload.get("interface") == "UsptoPairedRevisionReceipt@1"
        ):
            final_receipt = out_path
            referenced = True
            if payload.get("push_attempted") is True:
                raise ScheduleError("sync reported push_attempted=true (forbidden)")
        else:
            # Compatibility manifest from fetch-only: wrap/reference as binder.
            binder = _synthetic_receipt(
                sync_trigger=sync_trigger,
                schedule_trigger=schedule_trigger,
                run_id=run_id,
                status="accepted" if rc == 0 else "aborted",
                disposition="fetch_only",
                lock=lock.as_dict(),
                clock=clock,
            )
            binder["referenced_manifest"] = str(out_path)
            binder["notes"] = list(binder.get("notes") or []) + [
                "references_compatibility_manifest=true"
            ]
            atomic_write_text(
                receipt_path, json.dumps(binder, indent=2, sort_keys=True) + "\n"
            )
            final_receipt = receipt_path
            referenced = True
    else:
        binder = _synthetic_receipt(
            sync_trigger=sync_trigger,
            schedule_trigger=schedule_trigger,
            run_id=run_id,
            status="aborted" if rc != 0 else "accepted",
            disposition="aborted" if rc != 0 else (
                "fetch_only" if sync_trigger in FETCH_ONLY_SYNC else "integrated"
            ),
            lock=lock.as_dict(),
            clock=clock,
        )
        atomic_write_text(
            receipt_path, json.dumps(binder, indent=2, sort_keys=True) + "\n"
        )
        final_receipt = receipt_path
        referenced = True

    status = "success" if rc == 0 else "failed"
    # Scan outputs for accidental push language (defense in depth).
    combined = (stdout + "\n" + stderr).lower()
    push_attempted = "git push" in combined and "forbidden" not in combined
    if push_attempted:
        status = "failed"
        rc = rc or 2

    return RunResult(
        schedule_trigger=schedule_trigger,
        sync_trigger=sync_trigger,
        run_id=run_id,
        status=status,
        exit_code=rc,
        receipt_path=str(final_receipt) if final_receipt else None,
        receipt_referenced=referenced,
        push_attempted=False,  # policy: never push; flag only if detected above ends failed
        lock=lock.as_dict(),
        started_at=started,
        completed_at=clock.now(),
        stdout=stdout[-4000:],
        stderr=stderr[-4000:],
        dry_run=False,
        catch_up=catch_up,
        missed_intervals=missed_intervals,
        reason=reason,
    )


def run_schedule_trigger(
    *,
    schedule_trigger: str,
    state_root: Path,
    sync_sh: Path | None = None,
    clock: Clock | None = None,
    dry_run: bool = False,
    skip_fetch: bool = True,
    require_activated: bool = False,
    runner: SyncRunner | None = None,
    lock_path: Path | None = None,
    sync_trigger: str | None = None,
    catch_up: bool = False,
    missed_intervals: int = 0,
    reason: str = "",
    extra_env: Mapping[str, str] | None = None,
) -> RunResult:
    if schedule_trigger not in SCHEDULE_TRIGGERS and schedule_trigger not in SYNC_TRIGGERS:
        raise ScheduleError(f"unknown schedule trigger: {schedule_trigger}")
    # Allow calling with a pure sync trigger name (maps 1:1 when present).
    if schedule_trigger in SCHEDULE_TO_SYNC_TRIGGER:
        sched = schedule_trigger
        sync_t = sync_trigger or SCHEDULE_TO_SYNC_TRIGGER[sched]
    else:
        # Direct sync trigger (e.g. tests).
        sched = schedule_trigger
        sync_t = sync_trigger or schedule_trigger

    clock = clock or SystemClock()
    state_root = Path(state_root)
    store = ScheduleStateStore(state_root, clock=clock)
    state = store.load()

    if require_activated and not state.activated:
        raise ScheduleError(
            "schedule not activated; operator must run activate --activate-templates"
        )

    lp = Path(lock_path) if lock_path else program_family_lock_path(state_root)
    lock = ProgramFamilyLock(lp, dry_run=dry_run)

    if not lock.try_acquire():
        # Mutual exclusion: do not overlap; record skip without receipt mutation.
        tr = state.triggers.get(sched) or TriggerRuntime()
        tr.last_status = "skipped"
        tr.last_started_at = clock.now()
        tr.last_completed_at = clock.now()
        state.triggers[sched] = tr
        store.save(state)
        return RunResult(
            schedule_trigger=sched,
            sync_trigger=sync_t,
            run_id=uuid.uuid4().hex[:12],
            status="skipped",
            exit_code=3,
            receipt_path=state.last_receipt_path,
            receipt_referenced=bool(state.last_receipt_path),
            push_attempted=False,
            lock={"path": str(lp), "identity": "", "method": "held", "acquired": False,
                  "program_family": PROGRAM_FAMILY},
            started_at=clock.now(),
            completed_at=clock.now(),
            dry_run=dry_run,
            catch_up=catch_up,
            missed_intervals=missed_intervals,
            reason="lock_held",
        )

    try:
        tr = state.triggers.get(sched) or TriggerRuntime()
        tr.last_started_at = clock.now()
        tr.last_due_at = clock.now()
        state.triggers[sched] = tr
        store.save(state)

        if runner is not None:
            result = runner(
                schedule_trigger=sched,
                sync_trigger=sync_t,
                state_root=state_root,
                sync_sh=Path(sync_sh) if sync_sh else _DEFAULT_SYNC_SH,
                lock=lock,
                clock=clock,
                dry_run=dry_run,
                skip_fetch=skip_fetch,
                catch_up=catch_up,
                missed_intervals=missed_intervals,
                reason=reason,
                extra_env=extra_env,
            )
        else:
            result = invoke_sync_upstreams(
                schedule_trigger=sched,
                sync_trigger=sync_t,
                state_root=state_root,
                sync_sh=Path(sync_sh) if sync_sh else _DEFAULT_SYNC_SH,
                lock=lock,
                clock=clock,
                dry_run=dry_run,
                skip_fetch=skip_fetch,
                catch_up=catch_up,
                missed_intervals=missed_intervals,
                reason=reason,
                extra_env=extra_env,
            )

        tr = state.triggers.get(sched) or TriggerRuntime()
        tr.last_completed_at = result.completed_at
        tr.last_status = result.status if result.status != "dry-run" else "success"
        tr.last_receipt_path = result.receipt_path
        tr.last_run_id = result.run_id
        tr.run_count += 1
        if tr.last_status == "success":
            tr.success_count += 1
        if catch_up:
            tr.consecutive_misses_recovered = missed_intervals
        state.triggers[sched] = tr
        if result.receipt_path:
            state.last_receipt_path = result.receipt_path
        # Update release gate cache.
        if sched == "pre-release":
            gate = evaluate_pre_release_gate(
                state, now=clock.now(), require_receipt_file=bool(result.receipt_path)
            )
            state.release_blocked = not bool(gate.get("allowed"))
            state.release_block_reason = str(gate.get("reason") or "")
        store.save(state)

        # Persist run log (content-free operator record).
        run_log = {
            "schema_version": SCHEMA_VERSION,
            "run": result.to_dict(),
            "push_attempted": False,
            "program_family": PROGRAM_FAMILY,
        }
        log_path = (
            Path(state_root) / RUN_LOG_DIR_NAME / f"{result.run_id}.json"
        )
        atomic_write_text(
            log_path, json.dumps(run_log, indent=2, sort_keys=True) + "\n"
        )
        return result
    finally:
        lock.release()


def tick_schedule(
    *,
    state_root: Path,
    clock: Clock | None = None,
    dry_run: bool = False,
    sync_sh: Path | None = None,
    runner: SyncRunner | None = None,
    only: Sequence[str] | None = None,
    force: Sequence[str] | None = None,
    require_activated: bool = False,
    lock_path: Path | None = None,
    skip_fetch: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate due triggers and run each serially under the program-family lock.

    Mutual exclusion is per-run (each ``run_schedule_trigger`` acquires the
    lock). Missed-run recovery emits at most one catch-up per trigger per tick.
    """
    clock = clock or SystemClock()
    state_root = Path(state_root)
    store = ScheduleStateStore(state_root, clock=clock)
    state = store.load()
    if require_activated and not state.activated:
        raise ScheduleError(
            "schedule not activated; operator must run activate --activate-templates"
        )

    now = clock.now()
    due = compute_due_triggers(state, now=now, only=only, force=force)
    results: list[dict[str, Any]] = []

    for decision in due:
        # Re-load state between runs so last_completed_at advances.
        result = run_schedule_trigger(
            schedule_trigger=decision.schedule_trigger,
            sync_trigger=decision.sync_trigger,
            state_root=state_root,
            sync_sh=sync_sh,
            clock=clock,
            dry_run=dry_run,
            skip_fetch=skip_fetch,
            require_activated=require_activated,
            runner=runner,
            lock_path=lock_path,
            catch_up=decision.catch_up,
            missed_intervals=decision.missed_intervals,
            reason=decision.reason,
            extra_env=extra_env,
        )
        results.append(result.to_dict())

    state = store.load()
    state.last_tick_at = now
    store.save(state)

    return {
        "ok": True,
        "action": "tick",
        "dry_run": dry_run,
        "now": now,
        "now_utc": clock.utc_iso(),
        "due_count": len(due),
        "due": [
            {
                "schedule_trigger": d.schedule_trigger,
                "sync_trigger": d.sync_trigger,
                "missed_intervals": d.missed_intervals,
                "catch_up": d.catch_up,
                "reason": d.reason,
            }
            for d in due
        ],
        "results": results,
        "push_allowed": False,
        "last_receipt_path": state.last_receipt_path,
    }


# ---------------------------------------------------------------------------
# Offline self-check
# ---------------------------------------------------------------------------


def offline_self_check() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add(
        "schedule_triggers_complete",
        set(SCHEDULE_TRIGGERS)
        == {
            "eight-hour",
            "twice-daily",
            "wave-boundary",
            "pre-release",
            "security-fix",
        },
    )
    add(
        "mapping_covers_all",
        set(SCHEDULE_TO_SYNC_TRIGGER) == set(SCHEDULE_TRIGGERS),
    )
    add(
        "sync_targets_known",
        set(SCHEDULE_TO_SYNC_TRIGGER.values()).issubset(set(SYNC_TRIGGERS)),
    )
    add("push_forbidden", POLICY["push_allowed"] is False)
    add("operator_activation_required", POLICY["operator_activation_required"] is True)
    add("no_crontab_edit", POLICY["edit_user_crontab"] is False)
    add("program_family_lock", POLICY["serialize_via_program_family_lock"] is True)
    add("missed_run_single_catch_up", POLICY["missed_run_recovery"] == "single_catch_up")

    # Cadence math with fake clock.
    clock = FakeClock(1_700_000_000.0)
    st = ScheduleState()
    st.ensure_triggers()
    due0 = compute_due_triggers(st, now=clock.now())
    add("initial_due_periodics", len(due0) == len(PERIODIC_TRIGGERS), str(len(due0)))

    for name in PERIODIC_TRIGGERS:
        st.triggers[name].last_completed_at = clock.now()
        st.triggers[name].last_status = "success"
    due1 = compute_due_triggers(st, now=clock.now())
    add("not_due_immediately_after", due1 == [], str(due1))

    clock.advance(8 * 3600 + 1)
    due2 = compute_due_triggers(st, now=clock.now())
    names2 = {d.schedule_trigger for d in due2}
    add("eight_hour_cadence", "eight-hour" in names2, str(names2))

    # Missed multi-interval → single catch-up.
    st.triggers["eight-hour"].last_completed_at = clock.now() - (8 * 3600 * 5) - 10
    due3 = compute_due_triggers(st, now=clock.now(), only=["eight-hour"])
    add("missed_run_single", len(due3) == 1, str(due3))
    add(
        "missed_intervals_counted",
        bool(due3) and due3[0].missed_intervals >= 1 and due3[0].catch_up,
        str(due3[0].missed_intervals if due3 else None),
    )

    # Pre-release blocking.
    gate = evaluate_pre_release_gate(st, now=clock.now(), require_receipt_file=False)
    add("pre_release_blocks_by_default", gate["allowed"] is False, gate["reason"])

    # Template generation includes all triggers and activation warnings.
    tmpls = generate_templates(state_root=Path("/tmp/cross_repo_sync_test"))
    rels = {t.relative_path for t in tmpls}
    add("templates_systemd_present", any(r.startswith("systemd/") for r in rels))
    add("templates_cron_present", any(r.startswith("cron/") for r in rels))
    for name in SCHEDULE_TRIGGERS:
        add(
            f"template_for_{name}",
            any(name in r for r in rels),
        )
    sample = tmpls[1].content if len(tmpls) > 1 else ""
    add("template_says_not_enabled", "TEMPLATE ONLY" in sample or "TEMPLATE ONLY" in tmpls[0].content)
    add("template_push_forbidden", any("push" in t.content.lower() for t in tmpls))

    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "program_family": PROGRAM_FAMILY,
        "schedule_triggers": list(SCHEDULE_TRIGGERS),
        "policy": dict(POLICY),
        "checks": checks,
        "push_allowed": False,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install_sync_schedule.py",
        description=(
            "PATLAW-162: idempotent systemd/cron template generation and "
            "fake-clock schedule engine for cross-repo sync triggers."
        ),
    )
    p.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Schedule/sync state root (default: XDG or CROSS_REPO_SYNC_STATE_ROOT)",
    )
    p.add_argument(
        "--template-dir",
        type=Path,
        default=None,
        help="Where to write templates (default: <state-root>/schedule_templates)",
    )
    p.add_argument(
        "--sync-sh",
        type=Path,
        default=None,
        help="Path to sync_upstreams.sh",
    )
    p.add_argument(
        "--lock-path",
        type=Path,
        default=None,
        help="Program-family lock path (default: <state-root>/sync.lock)",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Run offline self-check and exit",
    )

    sub = p.add_subparsers(dest="command")

    inst = sub.add_parser("install", help="Generate templates (idempotent; no activate)")
    inst.add_argument("--dry-run", action="store_true")

    act = sub.add_parser(
        "activate",
        help="Explicit operator opt-in to mark templates activated",
    )
    act.add_argument(
        "--activate-templates",
        action="store_true",
        required=True,
        help="Required explicit opt-in flag",
    )

    un = sub.add_parser("uninstall", help="Remove generated templates only")
    un.add_argument("--dry-run", action="store_true")
    un.add_argument(
        "--purge-state",
        action="store_true",
        help="Also remove schedule_state.json",
    )

    sub.add_parser("status", help="Show schedule/install/activation/gate status")

    tick = sub.add_parser("tick", help="Run due schedule slots once")
    tick.add_argument("--dry-run", action="store_true")
    tick.add_argument(
        "--require-activated",
        action="store_true",
        help="Fail if operator has not activated templates",
    )
    tick.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Limit to these schedule triggers",
    )
    tick.add_argument(
        "--force",
        nargs="*",
        default=None,
        help="Force-run these triggers (including on-demand)",
    )
    tick.add_argument(
        "--no-skip-fetch",
        action="store_true",
        help="Allow git fetch inside sync_upstreams.sh",
    )

    run_p = sub.add_parser("run-trigger", help="Run one schedule trigger now")
    run_p.add_argument("--schedule-trigger", required=True)
    run_p.add_argument("--sync-trigger", default=None)
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--require-activated", action="store_true")
    run_p.add_argument("--no-skip-fetch", action="store_true")

    gate = sub.add_parser(
        "check-release-gate",
        help="Fail closed when pre-release receipt is missing/stale",
    )
    gate.add_argument(
        "--max-age-seconds",
        type=float,
        default=DEFAULT_PRE_RELEASE_MAX_AGE_SECONDS,
    )

    sub.add_parser("list-triggers", help="Print schedule trigger catalog as JSON")

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.offline or args.command is None and getattr(args, "offline", False):
        report = offline_self_check()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    if args.command is None:
        # Default: offline when no subcommand, else help.
        if args.offline:
            report = offline_self_check()
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["ok"] else 1
        parser.print_help()
        return 2

    state_root = resolve_state_root(args.state_root)

    try:
        if args.command == "list-triggers":
            print(
                json.dumps(
                    {
                        "schedule_triggers": list(SCHEDULE_TRIGGERS),
                        "sync_triggers": list(SYNC_TRIGGERS),
                        "schedule_to_sync_trigger": dict(SCHEDULE_TO_SYNC_TRIGGER),
                        "intervals_seconds": dict(DEFAULT_INTERVALS_SECONDS),
                        "periodic": sorted(PERIODIC_TRIGGERS),
                        "on_demand": sorted(ON_DEMAND_TRIGGERS),
                        "program_family": PROGRAM_FAMILY,
                        "push_allowed": False,
                        "operator_activation_required": True,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "install":
            report = install_templates(
                state_root=state_root,
                template_dir=args.template_dir,
                sync_sh=args.sync_sh,
                dry_run=bool(args.dry_run),
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if args.command == "activate":
            report = activate_templates(
                state_root=state_root,
                template_dir=args.template_dir,
                activate_templates_flag=bool(args.activate_templates),
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if args.command == "uninstall":
            report = uninstall_templates(
                state_root=state_root,
                template_dir=args.template_dir,
                dry_run=bool(args.dry_run),
                keep_state=not bool(args.purge_state),
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if args.command == "status":
            report = status_report(
                state_root=state_root,
                template_dir=args.template_dir,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if args.command == "tick":
            report = tick_schedule(
                state_root=state_root,
                dry_run=bool(args.dry_run),
                sync_sh=args.sync_sh,
                only=args.only,
                force=args.force,
                require_activated=bool(args.require_activated),
                lock_path=args.lock_path,
                skip_fetch=not bool(args.no_skip_fetch),
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if args.command == "run-trigger":
            result = run_schedule_trigger(
                schedule_trigger=args.schedule_trigger,
                sync_trigger=args.sync_trigger,
                state_root=state_root,
                sync_sh=args.sync_sh,
                dry_run=bool(args.dry_run),
                require_activated=bool(args.require_activated),
                lock_path=args.lock_path,
                skip_fetch=not bool(args.no_skip_fetch),
            )
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
            if result.status in {"success", "dry-run", "skipped"}:
                return 0 if result.status != "skipped" else 3
            return int(result.exit_code or 1)

        if args.command == "check-release-gate":
            store = ScheduleStateStore(state_root)
            state = store.load()
            try:
                gate = assert_release_allowed(
                    state,
                    now=time.time(),
                    max_age_seconds=float(args.max_age_seconds),
                )
            except PreReleaseBlocked as exc:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "allowed": False,
                            "error": str(exc),
                            "push_allowed": False,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 3
            print(
                json.dumps(
                    {"ok": True, "allowed": True, "gate": gate, "push_allowed": False},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        parser.error(f"unknown command: {args.command}")
        return 2
    except ScheduleError as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc), "push_allowed": False},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
