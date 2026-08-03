#!/usr/bin/env python3
"""USPTO submission-assurance operator status, stall detection, and recovery.

PATLAW-073: content-free health metrics and idempotent, audited recovery.

Operator-visible phases (mutually prioritized in :func:`classify_operator_phase`):

* ``waiting`` — delayed/gated work; workers released
* ``bounded_backoff`` — rate-limit / auth / circuit wait with a finite delay
* ``active_progress`` — running work or fresh heartbeat/tick
* ``stalled`` — claimed work or open queue without fresh progress
* ``policy_incident`` — security/privacy dead-letter or open credential incident
* ``completed_merge`` — no open work/incidents; optional merge receipt present

Recovery **never** deletes dead letters, alerts, fingerprints, known artifact
ids, or audit evidence, and **never** surfaces document bodies or secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final

STATUS_SCHEMA_VERSION: Final = "uspto.operator-status.v1"
STATUS_INTERFACE: Final = "UsptoOperatorStatus@1"
RECOVERY_AUDIT_SCHEMA_VERSION: Final = "uspto.recovery-audit.v1"
DEFAULT_STALL_SECONDS: Final = 600.0
DEFAULT_HEARTBEAT_STALE_SECONDS: Final = 300.0
DEFAULT_CHECKPOINT_NAME: Final = "scheduler"
MAX_AUDIT_MESSAGE: Final = 512

# Substrings that must never appear in operator-facing status/recovery output.
# Note: legitimate enum values such as content_kind=document_bytes are allowed;
# these markers target leaked payloads / credential material only.
_FORBIDDEN_CONTENT_MARKERS: Final = frozenset(
    {
        "secret_document_body",
        "private extracted_text",
        "authorization: bearer",
        "x-api-key:",
        "api_key=",
        "-----begin ",
    }
)

_SECRET_KEY_FRAGMENTS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
        "session",
        "mfa",
        "x-api-key",
        "document_body",
        "document_bytes",
        "extracted_text",
        "raw_body",
    }
)

_SECRET_TEXT_RE = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|bearer|token)\s*[:=]\s*[^\s,;\"']+"
)

# Job dispositions that indicate bounded backoff (finite delay, workers free).
_BACKOFF_DISPOSITIONS: Final = frozenset(
    {
        "rate_limited",
        "unauthorized",
        "forbidden",
        "upstream_error",
        "transport_error",
        "circuit_open",
    }
)

# Dead-letter / action kinds that raise a policy incident.
_POLICY_DEAD_LETTER_REASONS: Final = frozenset(
    {
        "security_failure",
        "parse_failure",  # schema drift / corrupt document treated as policy review
    }
)
_POLICY_ACTION_KINDS: Final = frozenset(
    {
        "credential_health",
        "review_dead_letter",
    }
)


class OperatorPhase(str, Enum):
    """Operator-distinguishable runtime phase (acceptance taxonomy)."""

    WAITING = "waiting"
    BOUNDED_BACKOFF = "bounded_backoff"
    ACTIVE_PROGRESS = "active_progress"
    STALLED = "stalled"
    POLICY_INCIDENT = "policy_incident"
    COMPLETED_MERGE = "completed_merge"


class RecoveryKind(str, Enum):
    """Idempotent recovery operations documented in the runbook."""

    AUTH_EXPIRY = "auth_expiry"
    RATE_BACKOFF = "rate_backoff"
    OUTAGE = "outage"
    SCHEMA_DRIFT = "schema_drift"
    CORRUPT_DOCUMENT = "corrupt_document"
    PRIVATE_POLICY_INCIDENT = "private_policy_incident"
    DEAD_LETTER = "dead_letter"
    STALE_CHECKPOINT = "stale_checkpoint"
    REPLAY = "replay"
    KEY_ROTATION = "key_rotation"
    SAFE_RESUME = "safe_resume"


# ---------------------------------------------------------------------------
# Time / paths / redaction
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(value: Any, *, now: datetime | None = None) -> float | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    clock = now or datetime.now(timezone.utc)
    return max(0.0, (clock - parsed).total_seconds())


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def default_checkpoint_root() -> Path:
    state_base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state_base / "ipfs_accelerate_py" / "uspto_submission_assurance" / "scheduler"


def default_audit_root() -> Path:
    state_base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state_base / "ipfs_accelerate_py" / "uspto_submission_assurance" / "recovery_audit"


def sanitize_text(value: Any) -> str:
    text = _SECRET_TEXT_RE.sub(r"\1=[REDACTED]", str(value or ""))
    if len(text) > MAX_AUDIT_MESSAGE:
        text = text[:MAX_AUDIT_MESSAGE] + "…"
    return text


def redact_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop secret/document keys; sanitize remaining string values."""
    if not payload:
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        key_s = str(key)
        lowered = key_s.lower().replace("-", "_")
        if any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS):
            out[key_s] = "[REDACTED]"
            continue
        if isinstance(value, Mapping):
            out[key_s] = redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            out[key_s] = [
                redact_mapping(v) if isinstance(v, Mapping) else sanitize_text(v)
                if isinstance(v, str)
                else v
                for v in value
            ]
        elif isinstance(value, str):
            out[key_s] = sanitize_text(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key_s] = value
        else:
            out[key_s] = sanitize_text(value)
    return out


def assert_content_free(payload: Any) -> None:
    """Raise ValueError if payload embeds forbidden document/secret markers."""
    blob = json.dumps(payload, sort_keys=True, default=str).lower()
    for marker in _FORBIDDEN_CONTENT_MARKERS:
        if marker in blob:
            raise ValueError(f"operator payload is not content-free: found {marker!r}")


def sha256_hex(material: str | bytes) -> str:
    if isinstance(material, str):
        material = material.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def new_id(prefix: str = "rec") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Checkpoint load / health projection
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def resolve_checkpoint_path(
    checkpoint_dir: Path | str | None = None,
    *,
    name: str = DEFAULT_CHECKPOINT_NAME,
) -> Path | None:
    if checkpoint_dir is None:
        root = default_checkpoint_root()
    else:
        root = Path(checkpoint_dir)
    if root.is_file():
        return root
    candidate = root / f"{name}-checkpoint.json"
    if candidate.is_file():
        return candidate
    # Accept bare directory with any *-checkpoint.json
    if root.is_dir():
        matches = sorted(root.glob("*-checkpoint.json"))
        if matches:
            return matches[0]
    return candidate if root else None


def load_checkpoint(
    checkpoint_dir: Path | str | None = None,
    *,
    name: str = DEFAULT_CHECKPOINT_NAME,
) -> dict[str, Any] | None:
    path = resolve_checkpoint_path(checkpoint_dir, name=name)
    if path is None or not path.is_file():
        return None
    return load_json(path)


def job_counts(checkpoint: Mapping[str, Any]) -> dict[str, int]:
    jobs = checkpoint.get("jobs") or {}
    if not isinstance(jobs, Mapping):
        return {}
    counts: dict[str, int] = {}
    for job in jobs.values():
        if not isinstance(job, Mapping):
            continue
        state = str(job.get("state") or "unknown").lower()
        counts[state] = counts.get(state, 0) + 1
    return counts


def open_actions(checkpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    actions = checkpoint.get("actions") or []
    out: list[dict[str, Any]] = []
    if not isinstance(actions, list):
        return out
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        if action.get("resolved"):
            continue
        out.append(redact_mapping(dict(action)))
    return out


def dead_letters(checkpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = checkpoint.get("dead_letters") or []
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, Mapping):
            continue
        # Never project job_snapshot bodies — drop snapshot entirely for status.
        slim = {k: v for k, v in item.items() if k != "job_snapshot"}
        out.append(redact_mapping(slim))
    return out


def circuit_summary(checkpoint: Mapping[str, Any]) -> dict[str, str]:
    raw = checkpoint.get("circuit_states") or {}
    summary: dict[str, str] = {}
    if not isinstance(raw, Mapping):
        return summary
    for service, state in raw.items():
        if isinstance(state, Mapping):
            summary[str(service)] = str(state.get("state") or state.get("status") or "unknown")
        else:
            summary[str(service)] = str(state)
    return summary


def waiting_job_summaries(checkpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    jobs = checkpoint.get("jobs") or {}
    out: list[dict[str, Any]] = []
    if not isinstance(jobs, Mapping):
        return out
    for job in jobs.values():
        if not isinstance(job, Mapping):
            continue
        state = str(job.get("state") or "").lower()
        if state not in {"waiting", "pending", "running"}:
            continue
        disposition = str(job.get("last_disposition") or "").lower()
        out.append(
            {
                "application_number": job.get("application_number"),
                "content_kind": job.get("content_kind"),
                "job_id": job.get("job_id"),
                "last_disposition": disposition or None,
                "last_status_code": job.get("last_status_code"),
                "service": job.get("service"),
                "state": state,
            }
        )
    return out


def progress_dict(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    progress = checkpoint.get("progress") or {}
    if not isinstance(progress, Mapping):
        return {}
    allowed = {
        "alerts_emitted",
        "changes_detected",
        "circuits_open",
        "jobs_completed",
        "jobs_dead_lettered",
        "jobs_enqueued",
        "jobs_running",
        "jobs_waiting",
        "last_heartbeat_utc",
        "last_tick_utc",
        "schema_version",
        "ticks",
        "workers_available",
        "workers_in_use",
    }
    return {k: progress[k] for k in sorted(allowed) if k in progress}


# ---------------------------------------------------------------------------
# Phase classification / stall detection
# ---------------------------------------------------------------------------


def has_policy_incident(checkpoint: Mapping[str, Any]) -> bool:
    for dl in dead_letters(checkpoint):
        reason = str(dl.get("reason") or "").lower()
        if reason in _POLICY_DEAD_LETTER_REASONS or reason == "security_failure":
            return True
        if reason == "security_failure" or "policy" in reason or "privacy" in reason:
            return True
        error_code = str(dl.get("error_code") or "").lower()
        if "security" in error_code or "policy" in error_code or "privacy" in error_code:
            return True
    for action in open_actions(checkpoint):
        kind = str(action.get("kind") or "").lower()
        if kind in _POLICY_ACTION_KINDS:
            # credential_health is a policy/auth incident for operators
            if kind == "credential_health":
                return True
            # review_dead_letter for security is policy
            if kind == "review_dead_letter":
                # correlated by dead letter reasons — already covered above;
                # still flag open DL reviews as incidents when any DL exists.
                return True
    labels_blob = json.dumps(list(checkpoint.get("alerts") or []), default=str).lower()
    if "policy" in labels_blob and "incident" in labels_blob:
        return True
    return False


def has_bounded_backoff(checkpoint: Mapping[str, Any]) -> bool:
    jobs = checkpoint.get("jobs") or {}
    if not isinstance(jobs, Mapping):
        return False
    circuits = circuit_summary(checkpoint)
    if any(state.lower() == "open" for state in circuits.values()):
        return True
    for job in jobs.values():
        if not isinstance(job, Mapping):
            continue
        if str(job.get("state") or "").lower() != "waiting":
            continue
        disposition = str(job.get("last_disposition") or "").lower()
        if disposition in _BACKOFF_DISPOSITIONS:
            return True
        status = job.get("last_status_code")
        if status in (401, 403, 429) or (isinstance(status, int) and 500 <= status <= 599):
            return True
    return False


def has_waiting_work(checkpoint: Mapping[str, Any]) -> bool:
    counts = job_counts(checkpoint)
    return counts.get("waiting", 0) > 0 or counts.get("pending", 0) > 0


def has_active_running(checkpoint: Mapping[str, Any]) -> bool:
    counts = job_counts(checkpoint)
    progress = progress_dict(checkpoint)
    if counts.get("running", 0) > 0:
        return True
    if int(progress.get("workers_in_use") or 0) > 0:
        return True
    return False


def is_completed(checkpoint: Mapping[str, Any], *, merge_receipt: Mapping[str, Any] | None = None) -> bool:
    counts = job_counts(checkpoint)
    open_work = (
        counts.get("pending", 0)
        + counts.get("waiting", 0)
        + counts.get("running", 0)
    )
    if open_work > 0:
        return False
    if open_actions(checkpoint):
        return False
    # Dead letters mean review residual — not completed merge unless all DL
    # have been acknowledged via merge receipt override.
    if dead_letters(checkpoint) and not (merge_receipt and merge_receipt.get("accepted_with_dead_letters")):
        # Still allow completed when all jobs succeeded and no open actions;
        # dead letters block "completed_merge" unless merge receipt says so.
        if counts.get("dead_lettered", 0) > 0 or dead_letters(checkpoint):
            return False
    if merge_receipt is not None:
        status = str(merge_receipt.get("status") or merge_receipt.get("state") or "").lower()
        if status in {"merged", "complete", "completed", "success", "succeeded"}:
            return True
        if merge_receipt.get("merged") is True:
            return True
    # No open work and all terminal jobs succeeded (or empty scheduler).
    total = sum(counts.values())
    if total == 0:
        return True
    succeeded = counts.get("succeeded", 0) + counts.get("cancelled", 0)
    return succeeded == total


def detect_stall(
    checkpoint: Mapping[str, Any],
    *,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    heartbeat_stale_seconds: float = DEFAULT_HEARTBEAT_STALE_SECONDS,
    now: datetime | None = None,
    mono_now: float | None = None,
) -> dict[str, Any]:
    """Return stall diagnosis without document content.

    Stall criteria (any):
    * running jobs whose ``updated_at_utc`` exceeds *stall_seconds*
    * open pending/waiting work with heartbeat/tick older than *heartbeat_stale_seconds*
    * workers_in_use > 0 but tick/heartbeat stale
    * waiting job whose next_run_at is far in the past (stuck waiter) when mono_now given
    """
    clock = now or datetime.now(timezone.utc)
    progress = progress_dict(checkpoint)
    jobs = checkpoint.get("jobs") or {}
    stalled_jobs: list[str] = []
    reasons: list[str] = []

    hb_age = age_seconds(progress.get("last_heartbeat_utc"), now=clock)
    tick_age = age_seconds(progress.get("last_tick_utc"), now=clock)

    if isinstance(jobs, Mapping):
        for jid, job in jobs.items():
            if not isinstance(job, Mapping):
                continue
            state = str(job.get("state") or "").lower()
            updated_age = age_seconds(job.get("updated_at_utc"), now=clock)
            if state == "running" and updated_age is not None and updated_age > stall_seconds:
                stalled_jobs.append(str(job.get("job_id") or jid))
                reasons.append("running_job_stale_update")
            if (
                state == "waiting"
                and mono_now is not None
                and job.get("next_run_at") is not None
            ):
                try:
                    next_run = float(job["next_run_at"])
                except (TypeError, ValueError):
                    next_run = None
                # next_run_at uses monotonic clock; if it is absurdly behind mono_now
                # and still waiting without disposition progress, flag after stall window.
                if next_run is not None and (mono_now - next_run) > stall_seconds:
                    # only flag if still waiting long after schedule
                    if updated_age is not None and updated_age > stall_seconds:
                        stalled_jobs.append(str(job.get("job_id") or jid))
                        reasons.append("waiting_job_overdue")

    open_work = has_waiting_work(checkpoint) or has_active_running(checkpoint)
    workers_in_use = int(progress.get("workers_in_use") or 0)

    if open_work:
        if hb_age is not None and hb_age > heartbeat_stale_seconds and tick_age is not None and tick_age > heartbeat_stale_seconds:
            reasons.append("heartbeat_and_tick_stale_with_open_work")
        elif tick_age is not None and tick_age > stall_seconds:
            reasons.append("tick_stale_with_open_work")
        elif hb_age is not None and hb_age > stall_seconds and workers_in_use > 0:
            reasons.append("heartbeat_stale_with_workers_held")

    stalled = bool(stalled_jobs) or any(
        r in reasons
        for r in (
            "heartbeat_and_tick_stale_with_open_work",
            "tick_stale_with_open_work",
            "heartbeat_stale_with_workers_held",
            "running_job_stale_update",
            "waiting_job_overdue",
        )
    )
    # Fresh empty scheduler is not stalled.
    if not open_work and not stalled_jobs:
        stalled = False
        reasons = [r for r in reasons if "stale" not in r or open_work]

    return {
        "heartbeat_age_seconds": hb_age,
        "reasons": sorted(set(reasons)),
        "stalled": stalled,
        "stalled_job_ids": sorted(set(stalled_jobs)),
        "tick_age_seconds": tick_age,
    }


def classify_operator_phase(
    checkpoint: Mapping[str, Any] | None,
    *,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    heartbeat_stale_seconds: float = DEFAULT_HEARTBEAT_STALE_SECONDS,
    merge_receipt: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    mono_now: float | None = None,
) -> dict[str, Any]:
    """Classify the dominant operator phase for a checkpoint snapshot."""
    if checkpoint is None:
        return {
            "phase": OperatorPhase.STALLED.value,
            "reasons": ["checkpoint_missing"],
            "stall": {"stalled": True, "reasons": ["checkpoint_missing"], "stalled_job_ids": []},
            "schema_version": STATUS_SCHEMA_VERSION,
        }

    stall = detect_stall(
        checkpoint,
        stall_seconds=stall_seconds,
        heartbeat_stale_seconds=heartbeat_stale_seconds,
        now=now,
        mono_now=mono_now,
    )
    policy = has_policy_incident(checkpoint)
    backoff = has_bounded_backoff(checkpoint)
    waiting = has_waiting_work(checkpoint)
    active = has_active_running(checkpoint)
    completed = is_completed(checkpoint, merge_receipt=merge_receipt)

    # Priority: policy > stalled > active > backoff > waiting > completed
    if policy:
        phase = OperatorPhase.POLICY_INCIDENT
        reasons = ["open_policy_or_security_incident"]
    elif stall["stalled"]:
        phase = OperatorPhase.STALLED
        reasons = list(stall["reasons"]) or ["stall_detected"]
    elif active:
        phase = OperatorPhase.ACTIVE_PROGRESS
        reasons = ["jobs_running_or_workers_in_use"]
    elif backoff:
        phase = OperatorPhase.BOUNDED_BACKOFF
        reasons = ["bounded_delay_or_open_circuit"]
    elif waiting:
        phase = OperatorPhase.WAITING
        reasons = ["delayed_or_gated_work"]
    elif completed:
        phase = OperatorPhase.COMPLETED_MERGE
        reasons = ["no_open_work_or_merge_receipt"]
    else:
        # Residual open dead letters without policy classification, etc.
        phase = OperatorPhase.WAITING
        reasons = ["residual_state"]

    return {
        "phase": phase.value,
        "reasons": reasons,
        "stall": stall,
        "schema_version": STATUS_SCHEMA_VERSION,
        "flags": {
            "active": active,
            "backoff": backoff,
            "completed": completed,
            "policy_incident": policy,
            "stalled": bool(stall["stalled"]),
            "waiting": waiting,
        },
    }


def build_status_report(
    checkpoint: Mapping[str, Any] | None,
    *,
    checkpoint_path: Path | str | None = None,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    heartbeat_stale_seconds: float = DEFAULT_HEARTBEAT_STALE_SECONDS,
    merge_receipt: Mapping[str, Any] | None = None,
    merge_receipt_path: Path | str | None = None,
    now: datetime | None = None,
    mono_now: float | None = None,
) -> dict[str, Any]:
    """Content-free operator status report."""
    if merge_receipt is None and merge_receipt_path is not None:
        merge_receipt = load_json(Path(merge_receipt_path))

    classification = classify_operator_phase(
        checkpoint,
        stall_seconds=stall_seconds,
        heartbeat_stale_seconds=heartbeat_stale_seconds,
        merge_receipt=merge_receipt,
        now=now,
        mono_now=mono_now,
    )

    if checkpoint is None:
        report = {
            "checkpoint_path": str(checkpoint_path or ""),
            "classification": classification,
            "exists": False,
            "generated_at_utc": utc_now(),
            "interface": STATUS_INTERFACE,
            "phase": classification["phase"],
            "schema_version": STATUS_SCHEMA_VERSION,
        }
        assert_content_free(report)
        return report

    counts = job_counts(checkpoint)
    report = {
        "actions_open": open_actions(checkpoint),
        "actions_open_count": len(open_actions(checkpoint)),
        "checkpoint_path": str(checkpoint_path or ""),
        "circuit_states": circuit_summary(checkpoint),
        "classification": classification,
        "dead_letters": dead_letters(checkpoint),
        "dead_letters_count": len(dead_letters(checkpoint)),
        "exists": True,
        "generated_at_utc": utc_now(),
        "interface": STATUS_INTERFACE,
        "job_counts": counts,
        "jobs_open_summary": waiting_job_summaries(checkpoint),
        "known_artifact_count": len(list(checkpoint.get("known_artifact_ids") or [])),
        "merge_receipt": redact_mapping(merge_receipt) if merge_receipt else None,
        "phase": classification["phase"],
        "progress": progress_dict(checkpoint),
        "schema_version": STATUS_SCHEMA_VERSION,
        "scheduler_schema_version": str(checkpoint.get("schema_version") or ""),
    }
    assert_content_free(report)
    return report


# ---------------------------------------------------------------------------
# Recovery (idempotent, audited, evidence-preserving)
# ---------------------------------------------------------------------------


def _audit_path(audit_dir: Path, recovery_id: str) -> Path:
    return audit_dir / f"{recovery_id}.json"


def _audit_compare_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Stable fields used for idempotent audit equality (ignore volatile timestamps)."""
    keys = (
        "actions_taken",
        "dry_run",
        "evidence_fingerprint_after",
        "evidence_fingerprint_before",
        "evidence_preserved",
        "kind",
        "note",
        "operator_id",
        "recovery_id",
        "requeued_job_ids",
        "schema_version",
    )
    return {k: record.get(k) for k in keys}


def write_audit_record(
    audit_dir: Path | str,
    record: Mapping[str, Any],
) -> Path:
    """Atomically write a recovery audit record. Never overwrites different content."""
    root = Path(audit_dir)
    root.mkdir(parents=True, exist_ok=True)
    recovery_id = str(record.get("recovery_id") or new_id("rec"))
    path = _audit_path(root, recovery_id)
    payload = redact_mapping(dict(record))
    payload.setdefault("schema_version", RECOVERY_AUDIT_SCHEMA_VERSION)
    payload["recovery_id"] = recovery_id
    assert_content_free(payload)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), indent=2) + "\n"
    if path.is_file():
        existing_payload = load_json(path) or {}
        # Idempotent when the recovery plan matches; timestamps may differ on replay.
        if _audit_compare_payload(existing_payload) == _audit_compare_payload(payload):
            return path
        raise ValueError(f"audit record already exists with different content: {path}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_audit_records(audit_dir: Path | str) -> list[dict[str, Any]]:
    root = Path(audit_dir)
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("rec_*.json")):
        payload = load_json(path)
        if payload is not None:
            records.append(payload)
    return records


def _evidence_fingerprint(checkpoint: Mapping[str, Any]) -> str:
    """Stable digest over evidence that recovery must preserve."""
    material = {
        "alert_ids": [
            a.get("alert_id")
            for a in (checkpoint.get("alerts") or [])
            if isinstance(a, Mapping)
        ],
        "dead_letter_ids": [
            d.get("dead_letter_id")
            for d in (checkpoint.get("dead_letters") or [])
            if isinstance(d, Mapping)
        ],
        "fingerprints": dict(checkpoint.get("fingerprints") or {}),
        "known_artifact_ids": sorted(str(x) for x in (checkpoint.get("known_artifact_ids") or [])),
    }
    return sha256_hex(json.dumps(material, sort_keys=True, separators=(",", ":")))


def evidence_preserved(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> bool:
    """True iff dead letters, alerts, fingerprints, and artifact ids were not deleted."""
    def _ids(key: str, id_field: str) -> set[str]:
        items = before.get(key) or []
        if not isinstance(items, list):
            return set()
        return {
            str(item.get(id_field))
            for item in items
            if isinstance(item, Mapping) and item.get(id_field)
        }

    before_dl = _ids("dead_letters", "dead_letter_id")
    after_dl = {
        str(item.get("dead_letter_id"))
        for item in (after.get("dead_letters") or [])
        if isinstance(item, Mapping) and item.get("dead_letter_id")
    }
    if not before_dl.issubset(after_dl):
        return False

    before_alerts = _ids("alerts", "alert_id")
    after_alerts = {
        str(item.get("alert_id"))
        for item in (after.get("alerts") or [])
        if isinstance(item, Mapping) and item.get("alert_id")
    }
    if not before_alerts.issubset(after_alerts):
        return False

    before_fp = dict(before.get("fingerprints") or {})
    after_fp = dict(after.get("fingerprints") or {})
    for key, value in before_fp.items():
        if after_fp.get(key) != value:
            return False

    before_art = set(str(x) for x in (before.get("known_artifact_ids") or []))
    after_art = set(str(x) for x in (after.get("known_artifact_ids") or []))
    if not before_art.issubset(after_art):
        return False
    return True


def _clone_job_for_replay(
    job_snapshot: Mapping[str, Any],
    *,
    new_job_id: str,
    credential_ref_id: str | None = None,
) -> dict[str, Any]:
    """Build a content-free requeue payload from a dead-letter job snapshot."""
    kind = str(job_snapshot.get("content_kind") or "metadata")
    return {
        "application_number": str(job_snapshot.get("application_number") or ""),
        "content_kind": kind,
        "credential_ref_id": credential_ref_id
        if credential_ref_id is not None
        else job_snapshot.get("credential_ref_id"),
        "job_id": new_job_id,
        "labels": redact_mapping(dict(job_snapshot.get("labels") or {})),
        "matter_id": job_snapshot.get("matter_id"),
        "resource_id": job_snapshot.get("resource_id"),
        "service": str(job_snapshot.get("service") or "application_status"),
    }


def apply_recovery(
    kind: RecoveryKind | str,
    checkpoint: MutableMapping[str, Any] | Mapping[str, Any],
    *,
    audit_dir: Path | str,
    operator_id: str = "operator",
    job_id: str | None = None,
    dead_letter_id: str | None = None,
    new_credential_ref_id: str | None = None,
    recovery_id: str | None = None,
    note: str = "",
    mono_now: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply an idempotent recovery plan and append an audit record.

    Mutates a shallow-copied checkpoint mapping when *dry_run* is False and the
    caller passes a mutable mapping; always returns the post-recovery view.

    Invariants:
    * never deletes dead letters, alerts, fingerprints, or known_artifact_ids
    * never embeds document bodies or secrets in the result/audit
    * repeating the same *recovery_id* is a no-op when audit content matches
    """
    kind_v = kind.value if isinstance(kind, RecoveryKind) else str(kind)
    try:
        recovery_kind = RecoveryKind(kind_v)
    except ValueError as exc:
        raise ValueError(f"unknown recovery kind: {kind_v}") from exc

    rid = recovery_id or new_id("rec")
    # Idempotent short-circuit: identical recovery_id already audited.
    if not dry_run and recovery_id:
        existing_path = _audit_path(Path(audit_dir), rid)
        if existing_path.is_file():
            existing = load_json(existing_path)
            if existing is not None and str(existing.get("kind") or "") == recovery_kind.value:
                out = dict(existing)
                out["idempotent_replay"] = True
                out["checkpoint"] = {
                    "dead_letters_count": len(list(checkpoint.get("dead_letters") or [])),
                    "jobs_count": len(dict(checkpoint.get("jobs") or {})),
                    "known_artifact_count": len(list(checkpoint.get("known_artifact_ids") or [])),
                }
                assert_content_free(out)
                return out

    # Work on a deep-ish copy of top-level collections we may extend.
    ckpt: dict[str, Any] = {
        k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, Mapping) else v)
        for k, v in dict(checkpoint).items()
    }
    if "jobs" in ckpt and isinstance(ckpt["jobs"], Mapping):
        ckpt["jobs"] = {str(k): dict(v) if isinstance(v, Mapping) else v for k, v in ckpt["jobs"].items()}
    if "actions" in ckpt and isinstance(ckpt["actions"], list):
        ckpt["actions"] = [dict(a) if isinstance(a, Mapping) else a for a in ckpt["actions"]]
    if "dead_letters" in ckpt and isinstance(ckpt["dead_letters"], list):
        ckpt["dead_letters"] = [
            dict(d) if isinstance(d, Mapping) else d for d in ckpt["dead_letters"]
        ]
    if "alerts" in ckpt and isinstance(ckpt["alerts"], list):
        ckpt["alerts"] = [dict(a) if isinstance(a, Mapping) else a for a in ckpt["alerts"]]
    if "known_artifact_ids" in ckpt:
        ckpt["known_artifact_ids"] = list(ckpt["known_artifact_ids"] or [])
    if "fingerprints" in ckpt and isinstance(ckpt["fingerprints"], Mapping):
        ckpt["fingerprints"] = dict(ckpt["fingerprints"])

    before_fp = _evidence_fingerprint(ckpt)
    actions_taken: list[str] = []
    requeued: list[str] = []

    # --- kind-specific plans (evidence-preserving) ---
    if recovery_kind is RecoveryKind.AUTH_EXPIRY:
        actions_taken.append("record_credential_health_resolution")
        for action in ckpt.get("actions") or []:
            if not isinstance(action, Mapping):
                continue
            if action.get("resolved"):
                continue
            if str(action.get("kind") or "") != "credential_health":
                continue
            if job_id and action.get("job_id") != job_id:
                continue
            action["resolved"] = True
            action["labels"] = dict(action.get("labels") or {})
            action["labels"]["resolved_by_recovery"] = rid
            actions_taken.append(f"resolve_action:{action.get('action_id')}")
        # Re-arm waiting auth jobs for immediate retry without deleting history.
        for jid, job in list((ckpt.get("jobs") or {}).items()):
            if not isinstance(job, Mapping):
                continue
            if job_id and job.get("job_id") != job_id and jid != job_id:
                continue
            disp = str(job.get("last_disposition") or "")
            if disp in {"unauthorized", "forbidden"} or job.get("last_status_code") in (401, 403):
                job["state"] = "waiting"
                job["next_run_at"] = float(mono_now)
                job["updated_at_utc"] = utc_now()
                if new_credential_ref_id:
                    job["credential_ref_id"] = new_credential_ref_id
                requeued.append(str(job.get("job_id") or jid))
                actions_taken.append(f"rearm_job:{job.get('job_id') or jid}")

    elif recovery_kind is RecoveryKind.RATE_BACKOFF:
        # Bounded backoff is self-healing; audit only — do not force-skip Retry-After.
        actions_taken.append("honor_retry_after_no_force")
        waiting = [
            str(j.get("job_id"))
            for j in (ckpt.get("jobs") or {}).values()
            if isinstance(j, Mapping)
            and str(j.get("state") or "") == "waiting"
            and str(j.get("last_disposition") or "") == "rate_limited"
        ]
        actions_taken.append(f"observed_rate_limited_jobs:{len(waiting)}")

    elif recovery_kind is RecoveryKind.OUTAGE:
        actions_taken.append("await_circuit_recovery")
        open_circuits = [
            svc
            for svc, state in circuit_summary(ckpt).items()
            if str(state).lower() == "open"
        ]
        actions_taken.append(f"open_circuits:{','.join(open_circuits) or 'none'}")
        # Rearm waiting upstream jobs after operator confirms outage cleared —
        # only when explicitly targeting; still preserve evidence.
        if job_id:
            job = (ckpt.get("jobs") or {}).get(job_id)
            if isinstance(job, Mapping):
                job["state"] = "waiting"
                job["next_run_at"] = float(mono_now)
                job["updated_at_utc"] = utc_now()
                requeued.append(job_id)
                actions_taken.append(f"rearm_job:{job_id}")

    elif recovery_kind in (
        RecoveryKind.SCHEMA_DRIFT,
        RecoveryKind.CORRUPT_DOCUMENT,
        RecoveryKind.DEAD_LETTER,
    ):
        # Keep dead letter forever; optionally enqueue a fresh job clone.
        target_dl = None
        for dl in ckpt.get("dead_letters") or []:
            if not isinstance(dl, Mapping):
                continue
            if dead_letter_id and dl.get("dead_letter_id") != dead_letter_id:
                continue
            if job_id and dl.get("job_id") != job_id:
                continue
            if recovery_kind is RecoveryKind.SCHEMA_DRIFT and str(dl.get("reason")) != "parse_failure":
                continue
            if recovery_kind is RecoveryKind.CORRUPT_DOCUMENT and str(dl.get("reason")) not in {
                "parse_failure",
                "security_failure",
            }:
                continue
            target_dl = dl
            break
        if target_dl is not None:
            actions_taken.append(f"retain_dead_letter:{target_dl.get('dead_letter_id')}")
            snapshot = target_dl.get("job_snapshot") or {}
            if not isinstance(snapshot, Mapping):
                snapshot = {}
            # Prefer live job if present for fields.
            live = (ckpt.get("jobs") or {}).get(str(target_dl.get("job_id") or ""))
            base = live if isinstance(live, Mapping) else snapshot
            new_jid = f"replay_{sha256_hex(str(target_dl.get('dead_letter_id')))[:12]}"
            if new_jid not in (ckpt.get("jobs") or {}):
                clone = _clone_job_for_replay(
                    base,
                    new_job_id=new_jid,
                    credential_ref_id=new_credential_ref_id,
                )
                ckpt.setdefault("jobs", {})[new_jid] = {
                    **clone,
                    "attempt": 0,
                    "created_at_utc": utc_now(),
                    "emitted_alert_ids": [],
                    "known_artifact_ids": [],
                    "last_disposition": None,
                    "last_status_code": None,
                    "next_run_at": float(mono_now),
                    "state": "pending",
                    "updated_at_utc": utc_now(),
                }
                requeued.append(new_jid)
                actions_taken.append(f"enqueue_replay_job:{new_jid}")
            else:
                actions_taken.append(f"replay_job_exists:{new_jid}")
                requeued.append(new_jid)
            # Resolve matching review actions without deleting them.
            for action in ckpt.get("actions") or []:
                if not isinstance(action, Mapping):
                    continue
                if action.get("resolved"):
                    continue
                if str(action.get("kind") or "") != "review_dead_letter":
                    continue
                if action.get("job_id") and action.get("job_id") != target_dl.get("job_id"):
                    continue
                action["resolved"] = True
                action["labels"] = dict(action.get("labels") or {})
                action["labels"]["resolved_by_recovery"] = rid
                actions_taken.append(f"resolve_action:{action.get('action_id')}")
        else:
            actions_taken.append("no_matching_dead_letter")

    elif recovery_kind is RecoveryKind.PRIVATE_POLICY_INCIDENT:
        # Fail closed: quarantine posture — do not requeue binary content jobs.
        actions_taken.append("quarantine_no_public_sink")
        actions_taken.append("retain_all_evidence")
        for action in ckpt.get("actions") or []:
            if not isinstance(action, Mapping):
                continue
            if action.get("resolved"):
                continue
            kind_a = str(action.get("kind") or "")
            if kind_a in {"review_dead_letter", "credential_health"}:
                # Mark acknowledged for ops tracking; content stays quarantined.
                action["labels"] = dict(action.get("labels") or {})
                action["labels"]["policy_ack"] = rid
                action["labels"]["quarantined"] = "true"
                actions_taken.append(f"ack_policy_action:{action.get('action_id')}")
        # Explicitly do NOT requeue document_bytes jobs from security DLs.

    elif recovery_kind is RecoveryKind.STALE_CHECKPOINT:
        actions_taken.append("validate_checkpoint_schema")
        schema = str(ckpt.get("schema_version") or "")
        if not schema:
            actions_taken.append("checkpoint_missing_schema")
        else:
            actions_taken.append(f"checkpoint_schema:{schema}")
        actions_taken.append("reload_from_durable_store")

    elif recovery_kind is RecoveryKind.REPLAY:
        # Safe replay: re-enqueue from fingerprints / metadata_ready without
        # clearing alert_dedupe_index (prevents duplicate alerts).
        actions_taken.append("preserve_alert_dedupe_index")
        actions_taken.append("preserve_known_artifact_ids")
        targets: list[Mapping[str, Any]] = []
        for jid, job in (ckpt.get("jobs") or {}).items():
            if not isinstance(job, Mapping):
                continue
            if job_id and job.get("job_id") != job_id and jid != job_id:
                continue
            if str(job.get("state") or "") in {"succeeded", "cancelled"}:
                continue
            targets.append(job)
        if job_id and not targets:
            # Create from resource key if only fingerprints remain.
            actions_taken.append("no_live_job_for_replay")
        for job in targets:
            jid = str(job.get("job_id"))
            if str(job.get("state") or "") in {"dead_lettered"}:
                # Use dead-letter path; do not resurrect in place.
                actions_taken.append(f"skip_dead_lettered_in_place:{jid}")
                continue
            job["state"] = "pending"
            job["next_run_at"] = float(mono_now)
            job["updated_at_utc"] = utc_now()
            requeued.append(jid)
            actions_taken.append(f"replay_pending:{jid}")

    elif recovery_kind is RecoveryKind.KEY_ROTATION:
        if not new_credential_ref_id:
            raise ValueError("key_rotation requires new_credential_ref_id")
        # Store only opaque credential reference ids — never secret material.
        if any(frag in new_credential_ref_id.lower() for frag in ("bearer ", "eyj", "sk-")):
            raise ValueError("new_credential_ref_id looks like a secret; use an opaque ref id")
        actions_taken.append("rotate_credential_ref")
        for jid, job in (ckpt.get("jobs") or {}).items():
            if not isinstance(job, Mapping):
                continue
            if job_id and job.get("job_id") != job_id and jid != job_id:
                continue
            old = job.get("credential_ref_id")
            job["credential_ref_id"] = new_credential_ref_id
            job["updated_at_utc"] = utc_now()
            actions_taken.append(
                f"rotate_job:{job.get('job_id') or jid}:{(old or '')[:32]}->{new_credential_ref_id[:32]}"
            )
        for action in ckpt.get("actions") or []:
            if not isinstance(action, Mapping):
                continue
            if str(action.get("kind") or "") != "credential_health":
                continue
            if action.get("resolved"):
                continue
            action["resolved"] = True
            action["labels"] = dict(action.get("labels") or {})
            action["labels"]["rotated_to_ref"] = new_credential_ref_id
            action["labels"]["resolved_by_recovery"] = rid
            actions_taken.append(f"resolve_action:{action.get('action_id')}")

    elif recovery_kind is RecoveryKind.SAFE_RESUME:
        actions_taken.append("safe_resume")
        # Promote overdue waiters to pending; release any stuck running claims.
        for jid, job in (ckpt.get("jobs") or {}).items():
            if not isinstance(job, Mapping):
                continue
            state = str(job.get("state") or "")
            if state == "running":
                # Crash-safe: do not hold capacity across resume.
                job["state"] = "pending"
                job["next_run_at"] = float(mono_now)
                job["updated_at_utc"] = utc_now()
                requeued.append(str(job.get("job_id") or jid))
                actions_taken.append(f"release_running:{job.get('job_id') or jid}")
            elif state == "waiting":
                next_run = job.get("next_run_at")
                try:
                    due = float(next_run) <= float(mono_now)
                except (TypeError, ValueError):
                    due = True
                if due:
                    job["state"] = "pending"
                    job["updated_at_utc"] = utc_now()
                    requeued.append(str(job.get("job_id") or jid))
                    actions_taken.append(f"promote_waiting:{job.get('job_id') or jid}")

    after_fp = _evidence_fingerprint(ckpt)
    preserved = evidence_preserved(dict(checkpoint), ckpt)
    if not preserved:
        raise RuntimeError("recovery would delete evidence; refused")

    result = {
        "actions_taken": actions_taken,
        "dry_run": dry_run,
        "evidence_fingerprint_after": after_fp,
        "evidence_fingerprint_before": before_fp,
        "evidence_preserved": preserved,
        "kind": recovery_kind.value,
        "note": sanitize_text(note),
        "operator_id": sanitize_text(operator_id),
        "phase_after": classify_operator_phase(ckpt, mono_now=mono_now)["phase"],
        "recovery_id": rid,
        "requeued_job_ids": sorted(set(requeued)),
        "schema_version": RECOVERY_AUDIT_SCHEMA_VERSION,
        "timestamp_utc": utc_now(),
    }
    assert_content_free(result)

    if not dry_run:
        # Persist audit; if same recovery_id already recorded, require identical plan.
        write_audit_record(
            audit_dir,
            {
                **result,
                "checkpoint_evidence_fingerprint": before_fp,
            },
        )
        # Mutate caller's mapping if mutable.
        if isinstance(checkpoint, MutableMapping):
            checkpoint.clear()
            checkpoint.update(ckpt)

    result["checkpoint"] = {
        "dead_letters_count": len(ckpt.get("dead_letters") or []),
        "jobs_count": len(ckpt.get("jobs") or {}),
        "known_artifact_count": len(ckpt.get("known_artifact_ids") or []),
    }
    assert_content_free(result)
    return result


def recover_with_scheduler(
    kind: RecoveryKind | str,
    *,
    checkpoint_dir: Path | str,
    audit_dir: Path | str,
    checkpoint_name: str = DEFAULT_CHECKPOINT_NAME,
    operator_id: str = "operator",
    job_id: str | None = None,
    dead_letter_id: str | None = None,
    new_credential_ref_id: str | None = None,
    recovery_id: str | None = None,
    note: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Load durable checkpoint, apply recovery, optionally write checkpoint back."""
    path = resolve_checkpoint_path(checkpoint_dir, name=checkpoint_name)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"checkpoint not found under {checkpoint_dir}")
    preimage = load_json(path)
    if preimage is None:
        raise ValueError(f"unreadable checkpoint: {path}")
    ckpt: dict[str, Any] = json.loads(json.dumps(preimage))

    result = apply_recovery(
        kind,
        ckpt,
        audit_dir=audit_dir,
        operator_id=operator_id,
        job_id=job_id,
        dead_letter_id=dead_letter_id,
        new_credential_ref_id=new_credential_ref_id,
        recovery_id=recovery_id,
        note=note,
        dry_run=dry_run,
    )
    if not dry_run:
        if not evidence_preserved(preimage, ckpt):
            raise RuntimeError("recovery refused: would delete evidence on disk write")
        tmp = path.with_suffix(".tmp")
        body = json.dumps(ckpt, sort_keys=True, separators=(",", ":"))
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
        result["checkpoint_path"] = str(path)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/ops/uspto/status.py",
        description=(
            "Content-free USPTO submission-assurance operator status, "
            "stall detection, and idempotent recovery (PATLAW-073)."
        ),
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="Directory or file containing scheduler checkpoint JSON",
    )
    parser.add_argument(
        "--checkpoint-name",
        default=DEFAULT_CHECKPOINT_NAME,
        help=f"Checkpoint basename (default: {DEFAULT_CHECKPOINT_NAME})",
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=None,
        help="Directory for recovery audit records",
    )
    parser.add_argument(
        "--merge-receipt",
        type=Path,
        default=None,
        help="Optional merge receipt JSON (content-free) for completed_merge",
    )
    parser.add_argument(
        "--stall-seconds",
        type=float,
        default=DEFAULT_STALL_SECONDS,
        help=f"Stall threshold for running/open work (default: {DEFAULT_STALL_SECONDS})",
    )
    parser.add_argument(
        "--heartbeat-stale-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_STALE_SECONDS,
        help=f"Heartbeat/tick staleness threshold (default: {DEFAULT_HEARTBEAT_STALE_SECONDS})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default)",
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="Emit a short human-readable summary",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show operator phase and content-free health (default)")
    sub.add_parser("phases", help="List operator phase taxonomy")

    rec = sub.add_parser("recover", help="Apply an idempotent audited recovery operation")
    rec.add_argument(
        "--kind",
        required=True,
        choices=[k.value for k in RecoveryKind],
        help="Recovery operation kind",
    )
    rec.add_argument("--job-id", default=None)
    rec.add_argument("--dead-letter-id", default=None)
    rec.add_argument("--new-credential-ref-id", default=None)
    rec.add_argument("--operator-id", default="operator")
    rec.add_argument("--recovery-id", default=None, help="Stable id for idempotent audit")
    rec.add_argument("--note", default="")
    rec.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan recovery without writing audit or checkpoint",
    )

    sub.add_parser("audit", help="List recovery audit records (metadata only)")
    return parser


def _print_text_status(report: Mapping[str, Any]) -> None:
    phase = report.get("phase")
    print(f"phase: {phase}")
    print(f"interface: {report.get('interface')}")
    print(f"schema: {report.get('schema_version')}")
    print(f"checkpoint: {report.get('checkpoint_path') or '(none)'}")
    if not report.get("exists"):
        print("checkpoint_missing: true")
        return
    counts = report.get("job_counts") or {}
    print(f"jobs: {json.dumps(counts, sort_keys=True)}")
    print(f"actions_open: {report.get('actions_open_count')}")
    print(f"dead_letters: {report.get('dead_letters_count')}")
    circuits = report.get("circuit_states") or {}
    if circuits:
        print(f"circuits: {json.dumps(circuits, sort_keys=True)}")
    stall = (report.get("classification") or {}).get("stall") or {}
    print(f"stalled: {stall.get('stalled')}")
    if stall.get("reasons"):
        print(f"stall_reasons: {', '.join(stall['reasons'])}")
    reasons = (report.get("classification") or {}).get("reasons") or []
    if reasons:
        print(f"phase_reasons: {', '.join(reasons)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = args.command or "status"
    checkpoint_dir = args.checkpoint_dir
    audit_dir = args.audit_dir or default_audit_root()

    if command == "phases":
        payload = {
            "interface": STATUS_INTERFACE,
            "phases": [p.value for p in OperatorPhase],
            "recovery_kinds": [k.value for k in RecoveryKind],
            "schema_version": STATUS_SCHEMA_VERSION,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if command == "audit":
        records = load_audit_records(audit_dir)
        # Strip any accidental bulk fields; emit ids/kinds only summary + full redacted.
        slim = [
            {
                "evidence_preserved": r.get("evidence_preserved"),
                "kind": r.get("kind"),
                "operator_id": r.get("operator_id"),
                "phase_after": r.get("phase_after"),
                "recovery_id": r.get("recovery_id"),
                "requeued_job_ids": r.get("requeued_job_ids"),
                "timestamp_utc": r.get("timestamp_utc"),
            }
            for r in records
        ]
        assert_content_free(slim)
        print(json.dumps({"audit_dir": str(audit_dir), "records": slim}, indent=2, sort_keys=True))
        return 0

    if command == "recover":
        if checkpoint_dir is None:
            checkpoint_dir = default_checkpoint_root()
        try:
            result = recover_with_scheduler(
                args.kind,
                checkpoint_dir=checkpoint_dir,
                audit_dir=audit_dir,
                checkpoint_name=args.checkpoint_name,
                operator_id=args.operator_id,
                job_id=args.job_id,
                dead_letter_id=args.dead_letter_id,
                new_credential_ref_id=args.new_credential_ref_id,
                recovery_id=args.recovery_id,
                note=args.note,
                dry_run=bool(args.dry_run),
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            err = {"error": sanitize_text(exc), "ok": False}
            print(json.dumps(err, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        # Do not dump full checkpoint in CLI output.
        print(json.dumps({k: v for k, v in result.items() if k != "checkpoint"}, indent=2, sort_keys=True))
        return 0

    # status (default)
    path = resolve_checkpoint_path(checkpoint_dir, name=args.checkpoint_name)
    ckpt = load_checkpoint(checkpoint_dir, name=args.checkpoint_name)
    report = build_status_report(
        ckpt,
        checkpoint_path=path,
        stall_seconds=float(args.stall_seconds),
        heartbeat_stale_seconds=float(args.heartbeat_stale_seconds),
        merge_receipt_path=args.merge_receipt,
    )
    if args.text and not args.json:
        _print_text_status(report)
    else:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
