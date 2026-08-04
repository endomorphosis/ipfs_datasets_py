#!/usr/bin/env python3
"""Content-free production freshness and release observability (PATLAW-163).

Aggregates operator-safe health signals into a machine-readable report:

* authority freshness / current-through watermarks and source gaps/conflicts
* matter polling lag
* evaluated index roots and age
* private-boundary / isolation incidents (counts only)
* filing-handoff state counts
* Hub commit / Dataset Viewer verification
* paired-repository sync age
* merge-queue depth and supervisor drained / completed state

Overall states distinguished (acceptance taxonomy):

* ``healthy``   — mandatory receipts present; signals within budgets
* ``stale``     — one or more freshness/age budgets exceeded (non-blocking kinds)
* ``degraded``  — partial non-mandatory failures or malformed optional evidence
* ``blocked``   — missing mandatory receipt or a hard block (mandatory conflict,
                  isolation incident, hub/viewer failure, readiness false)
* ``active``    — live work in supervisors, queues, polls, or sync
* ``drained``   — no remaining work; shards may be stopped without being unhealthy
* ``completed`` — drained plus completion receipt and all mandatory evidence OK

Policy (never weakened):

* Task / backlog counts alone never imply legal or production readiness.
* Output is content-free: safe IDs, digests, counts, and timestamps only.
* Tenant / nonexistence safe: no matter bodies, private text, or cross-tenant
  enumeration that would confirm existence beyond opaque digests and counts.
* Stopped drained shards are not falsely marked unhealthy.
* Missing mandatory receipts always block readiness.

Usage
-----
    python scripts/ops/patent_legal_intelligence/production_status.py \\
        --evidence-root /path/to/production_evidence --json

    # Optional supervisor state root (same layout as status.py):
    python scripts/ops/patent_legal_intelligence/production_status.py \\
        --evidence-root ... --state-root ... --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent-legal.production-status.v1"
INTERFACE: Final = "PatentLegalProductionStatus@1"
TASK_ID: Final = "PATLAW-163"
GOAL_ID: Final = "PATLAW-G192"
PROGRAM_ID: Final = "patent-legal-intelligence"

# Mandatory receipt kinds that must be present for readiness.
MANDATORY_RECEIPT_KINDS: Final[tuple[str, ...]] = (
    "authority_freshness",
    "index_evaluation",
    "filing_handoff",
    "hub_verification",
    "paired_revision_sync",
    "isolation_status",
)

# Relative paths under the evidence root (convention).
RECEIPT_PATHS: Final[Mapping[str, str]] = {
    "authority_freshness": "authority/freshness.json",
    "authority_readiness": "authority/readiness.json",
    "index_evaluation": "indexes/evaluation_receipt.json",
    "matter_polling": "matters/polling.json",
    "isolation_status": "isolation/status.json",
    "filing_handoff": "filing/handoff_status.json",
    "hub_verification": "hub/verification_receipt.json",
    "paired_revision_sync": "sync/paired_revision_receipt.json",
    "completion": "completion/receipt.json",
}

# Default age budgets (seconds). Overridable via evidence thresholds.json.
DEFAULT_THRESHOLDS: Final[Mapping[str, int]] = {
    "authority_max_age_seconds": 7 * 24 * 3600,
    "index_max_age_seconds": 14 * 24 * 3600,
    "matter_poll_max_lag_seconds": 24 * 3600,
    "sync_pair_max_age_seconds": 24 * 3600,
    "hub_max_age_seconds": 30 * 24 * 3600,
    "supervisor_heartbeat_max_age_seconds": 120,
}

# Overall states (acceptance taxonomy).
OVERALL_STATES: Final[frozenset[str]] = frozenset(
    {
        "healthy",
        "stale",
        "degraded",
        "blocked",
        "active",
        "drained",
        "completed",
    }
)

# Severity for combining component signals into overall (higher wins first).
_STATE_RANK: Final[Mapping[str, int]] = {
    "blocked": 100,
    "stale": 80,
    "degraded": 60,
    "active": 40,
    "drained": 20,
    "completed": 10,
    "healthy": 0,
    "unknown": 50,
    "missing": 100,
    "unhealthy": 90,
}

# Content-free policy markers (must never appear in operator output).
_FORBIDDEN_CONTENT_MARKERS: Final = frozenset(
    {
        "secret_document_body",
        "private extracted_text",
        "authorization: bearer",
        "x-api-key:",
        "api_key=",
        "-----begin ",
        "payment_card",
        "mfa_secret",
        "session_cookie",
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
        "private_text",
        "claim_text",
        "prompt",
    }
)

_SECRET_TEXT_RE = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|bearer|token)\s*[:=]\s*[^\s,;\"']+"
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{16,128}$", re.IGNORECASE)
_SHA40_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)

MAX_REASON_LEN: Final = 240


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OverallState(str, Enum):
    """Production observability overall state (acceptance taxonomy)."""

    HEALTHY = "healthy"
    STALE = "stale"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    ACTIVE = "active"
    DRAINED = "drained"
    COMPLETED = "completed"


class ComponentState(str, Enum):
    """Per-component state projection."""

    HEALTHY = "healthy"
    STALE = "stale"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    ACTIVE = "active"
    DRAINED = "drained"
    COMPLETED = "completed"
    MISSING = "missing"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Time / JSON / redaction
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


def default_state_root() -> Path:
    state_base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state_base / "ipfs_accelerate_py" / "patent-legal-intelligence-v1"


def default_evidence_root() -> Path:
    env = os.environ.get("PATLAW_PRODUCTION_EVIDENCE_ROOT") or os.environ.get(
        "PATLAW_PRODUCTION_STATE_ROOT"
    )
    if env:
        return Path(env).expanduser()
    state_base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state_base / "ipfs_accelerate_py" / "patent-legal-intelligence-v1" / "production"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def sanitize_text(value: Any) -> str:
    text = _SECRET_TEXT_RE.sub(r"\1=[REDACTED]", str(value or ""))
    if len(text) > MAX_REASON_LEN:
        text = text[:MAX_REASON_LEN] + "…"
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
                redact_mapping(v)
                if isinstance(v, Mapping)
                else sanitize_text(v)
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
            raise ValueError(f"production status is not content-free: found {marker!r}")


def sha256_hex(material: str | bytes) -> str:
    if isinstance(material, str):
        material = material.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def safe_digest(value: Any) -> str | None:
    """Return a hex digest string if value looks like one; else None."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.startswith("sha256:"):
        text = text[7:]
    if _DIGEST_RE.match(text) or _SHA40_RE.match(text):
        return text
    return None


def safe_id(value: Any, *, max_len: int = 128) -> str:
    """Return a short operator-safe identifier (no whitespace bodies)."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Reject multi-line or long free text that could be private content.
    if "\n" in text or "\r" in text:
        return sha256_hex(text)[:32]
    if len(text) > max_len:
        return sha256_hex(text)[:32]
    return sanitize_text(text)[:max_len]


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _worse(a: str, b: str) -> str:
    return a if _STATE_RANK.get(a, 0) >= _STATE_RANK.get(b, 0) else b


# ---------------------------------------------------------------------------
# Thresholds / receipt loading
# ---------------------------------------------------------------------------


def load_thresholds(evidence_root: Path) -> dict[str, int]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    payload = load_json(evidence_root / "thresholds.json")
    if not payload:
        return thresholds
    for key in DEFAULT_THRESHOLDS:
        if key in payload:
            try:
                thresholds[key] = int(payload[key])
            except (TypeError, ValueError):
                continue
    return thresholds


def receipt_path(evidence_root: Path, kind: str) -> Path:
    rel = RECEIPT_PATHS.get(kind, f"receipts/{kind}.json")
    return evidence_root / rel


def load_receipt(
    evidence_root: Path, kind: str
) -> tuple[dict[str, Any] | None, str]:
    """Load a receipt; returns (payload_or_None, presence).

    presence: present | missing | unreadable
    """
    path = receipt_path(evidence_root, kind)
    if not path.is_file():
        return None, "missing"
    payload = load_json(path)
    if payload is None:
        return None, "unreadable"
    return payload, "present"


# ---------------------------------------------------------------------------
# Component evaluators (content-free projections)
# ---------------------------------------------------------------------------


def evaluate_authority_freshness(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
    thresholds: Mapping[str, int],
    now: datetime,
) -> dict[str, Any]:
    """Project authority freshness / current-through watermarks."""
    reasons: list[str] = []
    if presence != "present" or payload is None:
        return {
            "kind": "authority_freshness",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": True,
            "ready": False,
            "current_through": None,
            "evaluated_at": None,
            "age_seconds": None,
            "source_counts": {},
            "mandatory_block_count": 0,
            "gap_count": 0,
            "conflict_count": 0,
            "snapshot_digest": None,
            "reasons": ["mandatory authority freshness receipt missing"],
        }

    # Accept either FreshnessManifest shape or a production projection.
    current_through = (
        payload.get("current_through")
        or payload.get("as_of")
        or payload.get("current_through_utc")
    )
    evaluated_at = (
        payload.get("evaluated_at")
        or payload.get("generated_at")
        or payload.get("observed_at")
    )
    age = age_seconds(evaluated_at, now=now)
    if age is None and current_through is not None:
        # Date-only as_of: treat as midnight UTC.
        ct = str(current_through)
        if len(ct) == 10 and ct[4] == "-":
            age = age_seconds(f"{ct}T00:00:00Z", now=now)

    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    status_counts: dict[str, int] = {}
    mandatory_blocks = 0
    gap_count = 0
    conflict_count = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "unknown").strip().lower()
        status_counts[status] = status_counts.get(status, 0) + 1
        is_mandatory = bool(entry.get("is_mandatory") or entry.get("mandatory"))
        if status in {"missing", "stale", "conflict"} and is_mandatory:
            mandatory_blocks += 1
        if status in {"missing", "unknown"}:
            gap_count += 1
        if status == "conflict":
            conflict_count += 1

    # Explicit aggregate counters (preferred over raw entry expansion).
    if "mandatory_block_count" in payload:
        mandatory_blocks = _int_or_zero(payload.get("mandatory_block_count"))
    if "gap_count" in payload:
        gap_count = _int_or_zero(payload.get("gap_count"))
    if "conflict_count" in payload:
        conflict_count = _int_or_zero(payload.get("conflict_count"))
    if isinstance(payload.get("source_counts"), Mapping):
        for k, v in payload["source_counts"].items():
            status_counts[str(k)] = _int_or_zero(v)

    ready_flag = payload.get("authoritative_ready")
    if ready_flag is None and isinstance(payload.get("readiness"), Mapping):
        ready_flag = payload["readiness"].get("ready")
    if ready_flag is None:
        ready_flag = mandatory_blocks == 0

    snapshot_digest = (
        safe_digest(payload.get("snapshot_digest"))
        or safe_digest(payload.get("snapshot_cid"))
        or safe_digest(payload.get("receipt_digest_sha256"))
    )
    schedule_id = safe_id(payload.get("schedule_id") or payload.get("receipt_id"))

    max_age = int(thresholds.get("authority_max_age_seconds") or 0)
    state = ComponentState.HEALTHY.value
    if mandatory_blocks > 0 or ready_flag is False:
        state = ComponentState.BLOCKED.value
        reasons.append(
            f"authority not authoritative-ready "
            f"(mandatory_blocks={mandatory_blocks})"
        )
    elif age is not None and max_age > 0 and age > max_age:
        state = ComponentState.STALE.value
        reasons.append(f"authority freshness age {age:.0f}s exceeds {max_age}s")
    elif gap_count > 0 or conflict_count > 0:
        state = ComponentState.DEGRADED.value
        reasons.append(
            f"non-blocking source gaps/conflicts "
            f"(gaps={gap_count}, conflicts={conflict_count})"
        )

    return {
        "kind": "authority_freshness",
        "state": state,
        "present": True,
        "mandatory": True,
        "ready": bool(ready_flag) and state != ComponentState.BLOCKED.value,
        "current_through": safe_id(current_through, max_len=32) or None,
        "evaluated_at": safe_id(evaluated_at, max_len=40) or None,
        "age_seconds": round(age, 1) if age is not None else None,
        "source_counts": dict(sorted(status_counts.items())),
        "mandatory_block_count": mandatory_blocks,
        "gap_count": gap_count,
        "conflict_count": conflict_count,
        "snapshot_digest": snapshot_digest,
        "schedule_id": schedule_id,
        "reasons": reasons,
    }


def evaluate_index_evaluation(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
    thresholds: Mapping[str, int],
    now: datetime,
) -> dict[str, Any]:
    if presence != "present" or payload is None:
        return {
            "kind": "index_evaluation",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": True,
            "ready": False,
            "snapshot_cid": None,
            "qrels_cid": None,
            "index_root_count": 0,
            "evaluated_at": None,
            "age_seconds": None,
            "metric_digest": None,
            "thresholds_passed": None,
            "reasons": ["mandatory index evaluation receipt missing"],
        }

    evaluated_at = (
        payload.get("evaluated_at")
        or payload.get("generated_at")
        or payload.get("completed_at_utc")
    )
    age = age_seconds(evaluated_at, now=now)
    index_cids = payload.get("index_cids") if isinstance(payload.get("index_cids"), Mapping) else {}
    index_roots = payload.get("index_roots") if isinstance(payload.get("index_roots"), list) else []
    root_count = len(index_cids) if index_cids else len(index_roots)
    if "index_root_count" in payload:
        root_count = _int_or_zero(payload.get("index_root_count"))

    snapshot_cid = safe_digest(payload.get("snapshot_cid")) or safe_id(
        payload.get("snapshot_cid"), max_len=64
    )
    qrels_cid = safe_digest(payload.get("qrels_cid")) or safe_id(
        payload.get("qrels_cid"), max_len=64
    )
    metric_digest = (
        safe_digest(payload.get("metric_digest"))
        or safe_digest(payload.get("receipt_digest_sha256"))
        or safe_digest(payload.get("metrics_digest"))
    )
    thresholds_passed = payload.get("thresholds_passed")
    if thresholds_passed is None:
        status = str(payload.get("status") or payload.get("result") or "").lower()
        if status in {"pass", "passed", "ok", "success", "accepted"}:
            thresholds_passed = True
        elif status in {"fail", "failed", "error", "blocked"}:
            thresholds_passed = False

    max_age = int(thresholds.get("index_max_age_seconds") or 0)
    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    if thresholds_passed is False:
        state = ComponentState.BLOCKED.value
        reasons.append("index evaluation thresholds failed")
    elif root_count == 0 and not snapshot_cid:
        state = ComponentState.DEGRADED.value
        reasons.append("index evaluation receipt has no index roots/snapshot")
    elif age is not None and max_age > 0 and age > max_age:
        state = ComponentState.STALE.value
        reasons.append(f"index evaluation age {age:.0f}s exceeds {max_age}s")

    return {
        "kind": "index_evaluation",
        "state": state,
        "present": True,
        "mandatory": True,
        "ready": state not in {ComponentState.BLOCKED.value, ComponentState.MISSING.value},
        "snapshot_cid": snapshot_cid or None,
        "qrels_cid": qrels_cid or None,
        "index_root_count": root_count,
        "evaluated_at": safe_id(evaluated_at, max_len=40) or None,
        "age_seconds": round(age, 1) if age is not None else None,
        "metric_digest": metric_digest,
        "thresholds_passed": thresholds_passed,
        "reasons": reasons,
    }


def evaluate_matter_polling(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
    thresholds: Mapping[str, int],
    now: datetime,
) -> dict[str, Any]:
    """Matter polling lag — counts only; tenant/nonexistence safe."""
    if presence != "present" or payload is None:
        # Optional for readiness, but useful for freshness.
        return {
            "kind": "matter_polling",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": False,
            "ready": True,
            "last_poll_at": None,
            "lag_seconds": None,
            "matter_count": 0,
            "active_poll_count": 0,
            "reasons": ["matter polling receipt absent"],
        }

    last_poll_at = (
        payload.get("last_poll_at")
        or payload.get("last_heartbeat_utc")
        or payload.get("observed_at")
    )
    lag = _float_or_none(payload.get("lag_seconds"))
    if lag is None:
        lag = age_seconds(last_poll_at, now=now)

    matter_count = _int_or_zero(
        payload.get("matter_count")
        or payload.get("tracked_matter_count")
        or payload.get("count")
    )
    active = _int_or_zero(
        payload.get("active_poll_count") or payload.get("running_count")
    )
    max_lag = int(thresholds.get("matter_poll_max_lag_seconds") or 0)
    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    if active > 0:
        state = ComponentState.ACTIVE.value
    elif lag is not None and max_lag > 0 and lag > max_lag:
        state = ComponentState.STALE.value
        reasons.append(f"matter polling lag {lag:.0f}s exceeds {max_lag}s")

    return {
        "kind": "matter_polling",
        "state": state,
        "present": True,
        "mandatory": False,
        "ready": True,
        "last_poll_at": safe_id(last_poll_at, max_len=40) or None,
        "lag_seconds": round(lag, 1) if lag is not None else None,
        "matter_count": matter_count,
        "active_poll_count": active,
        "reasons": reasons,
    }


def evaluate_isolation(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
) -> dict[str, Any]:
    if presence != "present" or payload is None:
        return {
            "kind": "isolation_status",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": True,
            "ready": False,
            "open_incident_count": 0,
            "denied_provider_call_count": 0,
            "denied_result_count": 0,
            "receipt_digest": None,
            "reasons": ["mandatory isolation status receipt missing"],
        }

    open_incidents = _int_or_zero(
        payload.get("open_incident_count")
        or payload.get("incident_count")
        or payload.get("open_incidents")
    )
    denied_calls = _int_or_zero(payload.get("denied_provider_call_count"))
    denied_results = _int_or_zero(
        payload.get("denied_result_count") or payload.get("leaked_result_count")
    )
    # Public-path isolation OK requires zero denied on public evaluation path
    # when explicitly claimed; open incidents always block.
    public_path_ok = payload.get("public_path_isolation_ok")
    if public_path_ok is None:
        public_path_ok = open_incidents == 0

    receipt_digest = (
        safe_digest(payload.get("receipt_digest"))
        or safe_digest(payload.get("receipt_digest_sha256"))
    )
    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    if open_incidents > 0 or public_path_ok is False:
        state = ComponentState.BLOCKED.value
        reasons.append(
            f"isolation blocked (open_incidents={open_incidents}, "
            f"public_path_ok={public_path_ok})"
        )
    elif denied_calls > 0 or denied_results > 0:
        # Counts may be expected on private-path probes; treat as degraded signal
        # only when status explicitly marks isolation_degraded.
        if payload.get("isolation_degraded") is True:
            state = ComponentState.DEGRADED.value
            reasons.append(
                f"isolation degraded (denied_calls={denied_calls}, "
                f"denied_results={denied_results})"
            )

    return {
        "kind": "isolation_status",
        "state": state,
        "present": True,
        "mandatory": True,
        "ready": state != ComponentState.BLOCKED.value,
        "open_incident_count": open_incidents,
        "denied_provider_call_count": denied_calls,
        "denied_result_count": denied_results,
        "public_path_isolation_ok": bool(public_path_ok),
        "receipt_digest": receipt_digest,
        "reasons": reasons,
    }


def evaluate_filing_handoff(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
) -> dict[str, Any]:
    if presence != "present" or payload is None:
        return {
            "kind": "filing_handoff",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": True,
            "ready": False,
            "state_counts": {},
            "conflicting_count": 0,
            "incomplete_count": 0,
            "verified_count": 0,
            "receipt_digest": None,
            "reasons": ["mandatory filing handoff status receipt missing"],
        }

    counts: dict[str, int] = {}
    raw_counts = payload.get("state_counts") or payload.get("counts") or {}
    if isinstance(raw_counts, Mapping):
        for k, v in raw_counts.items():
            counts[str(k).lower()] = _int_or_zero(v)
    # Flat fields
    for key in (
        "approved",
        "submitted",
        "reconciled",
        "verified",
        "conflicting",
        "incomplete",
        "exported",
        "receipt_verified",
    ):
        if key in payload and key not in counts:
            counts[key] = _int_or_zero(payload.get(key))

    conflicting = counts.get("conflicting", 0) + _int_or_zero(
        payload.get("conflicting_count")
    )
    incomplete = counts.get("incomplete", 0) + _int_or_zero(
        payload.get("incomplete_count")
    )
    verified = (
        counts.get("verified", 0)
        + counts.get("receipt_verified", 0)
        + counts.get("reconciled", 0)
        + _int_or_zero(payload.get("verified_count"))
    )
    active = _int_or_zero(payload.get("active_handoff_count")) + counts.get(
        "exported", 0
    ) + counts.get("submitted", 0) + counts.get("approved", 0)

    receipt_digest = (
        safe_digest(payload.get("receipt_digest"))
        or safe_digest(payload.get("receipt_digest_sha256"))
    )
    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    if conflicting > 0:
        state = ComponentState.BLOCKED.value
        reasons.append(f"filing handoff has {conflicting} conflicting case(s)")
    elif incomplete > 0 and verified == 0 and active == 0:
        state = ComponentState.DEGRADED.value
        reasons.append(f"filing handoff has {incomplete} incomplete case(s)")
    elif active > 0 and verified == 0:
        state = ComponentState.ACTIVE.value
    elif incomplete > 0:
        state = ComponentState.DEGRADED.value
        reasons.append(f"filing handoff incomplete_count={incomplete}")

    return {
        "kind": "filing_handoff",
        "state": state,
        "present": True,
        "mandatory": True,
        "ready": state != ComponentState.BLOCKED.value,
        "state_counts": dict(sorted(counts.items())),
        "conflicting_count": conflicting,
        "incomplete_count": incomplete,
        "verified_count": verified,
        "receipt_digest": receipt_digest,
        "reasons": reasons,
    }


def evaluate_hub_verification(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
    thresholds: Mapping[str, int],
    now: datetime,
) -> dict[str, Any]:
    if presence != "present" or payload is None:
        return {
            "kind": "hub_verification",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": True,
            "ready": False,
            "hub_commit_count": 0,
            "viewer_ok": None,
            "verified_at": None,
            "age_seconds": None,
            "release_cid": None,
            "receipt_digest": None,
            "reasons": ["mandatory hub verification receipt missing"],
        }

    verified_at = (
        payload.get("verified_at")
        or payload.get("completed_at_utc")
        or payload.get("generated_at")
    )
    age = age_seconds(verified_at, now=now)
    viewer_ok = payload.get("viewer_ok")
    if viewer_ok is None and isinstance(payload.get("viewer"), Mapping):
        viewer_ok = payload["viewer"].get("ok")
    status = str(payload.get("status") or "").lower()
    if viewer_ok is None and status in {"pass", "passed", "ok", "success", "accepted"}:
        viewer_ok = True
    if viewer_ok is None and status in {"fail", "failed", "blocked", "error"}:
        viewer_ok = False

    repos = payload.get("repositories") if isinstance(payload.get("repositories"), Mapping) else {}
    hub_commits = payload.get("hub_commits") if isinstance(payload.get("hub_commits"), Mapping) else {}
    commit_count = len(repos) or len(hub_commits) or _int_or_zero(
        payload.get("hub_commit_count")
    )
    # Collect safe commit digests only (no repo names with private content).
    commit_digests: list[str] = []
    for source in (hub_commits, repos):
        if not isinstance(source, Mapping):
            continue
        for v in source.values():
            if isinstance(v, Mapping):
                d = safe_digest(v.get("commit_sha") or v.get("sha") or v.get("hub_sha"))
            else:
                d = safe_digest(v)
            if d:
                commit_digests.append(d)
    commit_digests = sorted(set(commit_digests))[:16]

    release_cid = (
        safe_digest(payload.get("release_cid"))
        or safe_id(payload.get("release_cid"), max_len=64)
    )
    receipt_digest = (
        safe_digest(payload.get("receipt_digest"))
        or safe_digest(payload.get("receipt_digest_sha256"))
    )
    max_age = int(thresholds.get("hub_max_age_seconds") or 0)
    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    if viewer_ok is False or status in {"fail", "failed", "blocked", "error"}:
        state = ComponentState.BLOCKED.value
        reasons.append("hub verification or viewer contracts failed")
    elif commit_count == 0 and not release_cid:
        state = ComponentState.DEGRADED.value
        reasons.append("hub verification has no commit/release binding")
    elif age is not None and max_age > 0 and age > max_age:
        state = ComponentState.STALE.value
        reasons.append(f"hub verification age {age:.0f}s exceeds {max_age}s")

    return {
        "kind": "hub_verification",
        "state": state,
        "present": True,
        "mandatory": True,
        "ready": state not in {ComponentState.BLOCKED.value, ComponentState.MISSING.value},
        "hub_commit_count": commit_count or len(commit_digests),
        "hub_commit_digests": commit_digests,
        "viewer_ok": viewer_ok,
        "verified_at": safe_id(verified_at, max_len=40) or None,
        "age_seconds": round(age, 1) if age is not None else None,
        "release_cid": release_cid or None,
        "receipt_digest": receipt_digest,
        "reasons": reasons,
    }


def evaluate_paired_sync(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
    thresholds: Mapping[str, int],
    now: datetime,
) -> dict[str, Any]:
    if presence != "present" or payload is None:
        return {
            "kind": "paired_revision_sync",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": True,
            "ready": False,
            "status": None,
            "trigger": None,
            "pair_age_seconds": None,
            "datasets_sha": None,
            "accelerator_sha": None,
            "receipt_digest": None,
            "reasons": ["mandatory paired-revision sync receipt missing"],
        }

    status = str(payload.get("status") or "").lower()
    trigger = safe_id(payload.get("trigger") or payload.get("schedule_trigger"))
    completed_at = (
        payload.get("completed_at_utc")
        or payload.get("completed_at")
        or payload.get("generated_at")
    )
    age = age_seconds(completed_at, now=now)

    def _repo_sha(key: str) -> str | None:
        block = payload.get(key)
        if isinstance(block, Mapping):
            return (
                safe_digest(block.get("integrated_sha"))
                or safe_digest(block.get("remote_sha"))
                or safe_digest(block.get("sha"))
            )
        return safe_digest(payload.get(f"{key}_sha"))

    datasets_sha = _repo_sha("datasets")
    accelerator_sha = _repo_sha("accelerator")
    receipt_digest = (
        safe_digest(payload.get("receipt_digest_sha256"))
        or safe_digest(payload.get("receipt_digest"))
    )
    max_age = int(thresholds.get("sync_pair_max_age_seconds") or 0)
    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    if status in {"aborted", "rejected", "quarantined", "failed", "error"}:
        state = ComponentState.BLOCKED.value
        reasons.append(f"paired sync status={status or 'unknown'}")
    elif status in {"running", "in_progress", "active"}:
        state = ComponentState.ACTIVE.value
    elif age is not None and max_age > 0 and age > max_age:
        state = ComponentState.STALE.value
        reasons.append(f"sync pair age {age:.0f}s exceeds {max_age}s")
    elif status and status not in {"accepted", "success", "ok", "passed", "dry-run"}:
        state = ComponentState.DEGRADED.value
        reasons.append(f"paired sync unexpected status={status}")

    return {
        "kind": "paired_revision_sync",
        "state": state,
        "present": True,
        "mandatory": True,
        "ready": state not in {ComponentState.BLOCKED.value, ComponentState.MISSING.value},
        "status": status or None,
        "trigger": trigger or None,
        "pair_age_seconds": round(age, 1) if age is not None else None,
        "datasets_sha": datasets_sha,
        "accelerator_sha": accelerator_sha,
        "receipt_digest": receipt_digest,
        "push_attempted": bool(payload.get("push_attempted")) if "push_attempted" in payload else False,
        "reasons": reasons,
    }


def evaluate_completion(
    payload: Mapping[str, Any] | None,
    *,
    presence: str,
) -> dict[str, Any]:
    if presence != "present" or payload is None:
        return {
            "kind": "completion",
            "state": ComponentState.MISSING.value,
            "present": False,
            "mandatory": False,
            "ready": True,
            "status": None,
            "receipt_digest": None,
            "reasons": [],
        }
    status = str(payload.get("status") or payload.get("result") or "").lower()
    digest = (
        safe_digest(payload.get("receipt_digest"))
        or safe_digest(payload.get("receipt_digest_sha256"))
    )
    ok = status in {"completed", "complete", "merged", "accepted", "pass", "passed", "ok"}
    return {
        "kind": "completion",
        "state": ComponentState.COMPLETED.value if ok else ComponentState.DEGRADED.value,
        "present": True,
        "mandatory": False,
        "ready": ok,
        "status": status or None,
        "receipt_digest": digest,
        "reasons": [] if ok else [f"completion receipt status={status or 'unknown'}"],
    }


# ---------------------------------------------------------------------------
# Supervisor / merge queue (content-free)
# ---------------------------------------------------------------------------


def _read_pid(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip().split()[0]
        pid = int(value)
    except (OSError, IndexError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def evaluate_supervisor_shard(
    *,
    shard: int,
    state_root: Path,
    heartbeat_limit: int,
    now: datetime,
) -> dict[str, Any]:
    """Project one supervisor shard into a content-free production signal.

    Stopped drained shards (no ready/blocked/active work, PIDs down) are
    reported as ``drained`` — never as falsely unhealthy.
    """
    shard_root = state_root / "shards" / str(shard)
    state_dir = shard_root / "state"
    prefix = f"patlaw_shard_{shard}"
    outer_pid_path = shard_root / "supervisor.pid"
    managed_pid_path = state_dir / f"{prefix}_managed_daemon.pid"
    status_path = state_dir / f"{prefix}_supervisor_status.json"
    task_path = state_dir / f"{prefix}_task_state.json"
    incident_path = state_dir / "implementation-protected-path-incident.json"

    # Allow a compact production projection file written by tests/operators.
    projection = load_json(shard_root / "production_projection.json")

    outer_pid = _read_pid(outer_pid_path)
    managed_pid = _read_pid(managed_pid_path)
    outer_alive = _pid_alive(outer_pid)
    managed_alive = _pid_alive(managed_pid)
    status = load_json(status_path) or {}
    task = load_json(task_path) or {}
    if projection:
        # Projection overrides filesystem when present (fixture-friendly).
        outer_alive = bool(projection.get("outer_alive", outer_alive))
        managed_alive = bool(projection.get("managed_alive", managed_alive))
        status = {
            **status,
            **{k: projection[k] for k in projection if k not in {"outer_alive", "managed_alive"}},
        }
        task = {**task, **{k: projection[k] for k in ("active_task_id", "ready_count", "blocked_count", "completed_count", "selection_idle_reason", "implementation_in_progress") if k in projection}}

    payloads = (task, status)
    active_task = ""
    for p in payloads:
        for key in ("active_task_id",):
            v = str(p.get(key) or "").strip()
            if v:
                active_task = safe_id(v, max_len=64)
                break
        if active_task:
            break
    implementation_in_progress = any(
        p.get("implementation_in_progress") is True for p in payloads
    )
    ready_count = 0
    blocked_count = 0
    completed_count = 0
    waiting_count = 0
    for p in payloads:
        for key, slot in (
            ("eligible_ready_count", "ready"),
            ("selectable_ready_count", "ready"),
            ("ready_count", "ready"),
            ("blocked_count", "blocked"),
            ("completed_count", "completed"),
            ("waiting_count", "waiting"),
        ):
            if key in p and p.get(key) is not None:
                try:
                    val = int(p[key])
                except (TypeError, ValueError):
                    continue
                if slot == "ready":
                    ready_count = val
                elif slot == "blocked":
                    blocked_count = val
                elif slot == "completed":
                    completed_count = val
                elif slot == "waiting":
                    waiting_count = val

    idle_reason = ""
    for p in payloads:
        idle_reason = str(p.get("selection_idle_reason") or p.get("idle_reason") or "").strip()
        if idle_reason:
            break
    idle_reason = safe_id(idle_reason, max_len=80)

    heartbeat_value = ""
    for p in (status, task):
        for key in ("updated_at", "heartbeat_at", "observed_at", "last_progress_at"):
            v = str(p.get(key) or "").strip()
            if v:
                heartbeat_value = v
                break
        if heartbeat_value:
            break
    heartbeat_age = age_seconds(heartbeat_value, now=now)
    if heartbeat_age is None and projection and "heartbeat_age_seconds" in projection:
        heartbeat_age = _float_or_none(projection.get("heartbeat_age_seconds"))

    protected_incident = incident_path.exists() or bool(
        projection and projection.get("protected_path_incident")
    )

    drained = bool(
        not active_task
        and not implementation_in_progress
        and ready_count == 0
        and blocked_count == 0
        and waiting_count == 0
        and (
            idle_reason in {"", "no_shard_selectable_ready_tasks", "drained", "completed"}
            or completed_count > 0
            or not (outer_alive or managed_alive)
        )
    )
    stopped = not outer_alive and not managed_alive

    reasons: list[str] = []
    state = ComponentState.HEALTHY.value
    residual_work = bool(
        active_task
        or implementation_in_progress
        or ready_count > 0
        or waiting_count > 0
        or blocked_count > 0
    )

    if protected_incident:
        state = ComponentState.BLOCKED.value
        reasons.append("protected-path incident latched")
    elif blocked_count > 0 and not stopped:
        state = ComponentState.BLOCKED.value
        reasons.append(f"task projection blocked_count={blocked_count}")
    elif stopped and residual_work:
        # Stopped with residual work is a problem (not merely active).
        state = ComponentState.BLOCKED.value
        reasons.append("supervisor stopped with residual ready/waiting/blocked work")
    elif active_task or implementation_in_progress or ready_count > 0:
        state = ComponentState.ACTIVE.value
    elif drained and stopped:
        # Acceptance: stopped drained shards are not falsely unhealthy.
        state = ComponentState.DRAINED.value
    elif drained and (outer_alive or managed_alive):
        state = ComponentState.DRAINED.value
    elif (
        (outer_alive or managed_alive)
        and heartbeat_age is not None
        and heartbeat_limit > 0
        and heartbeat_age > heartbeat_limit
    ):
        state = ComponentState.STALE.value
        reasons.append(
            f"supervisor heartbeat stale ({heartbeat_age:.0f}s > {heartbeat_limit}s)"
        )
    elif not status and not task and not projection and not stopped:
        state = ComponentState.DEGRADED.value
        reasons.append("supervisor status projection missing")

    return {
        "shard": shard,
        "state": state,
        "outer_alive": outer_alive,
        "managed_alive": managed_alive,
        "stopped": stopped,
        "drained": drained,
        "active_task_id": active_task or None,
        "ready_count": ready_count,
        "waiting_count": waiting_count,
        "blocked_count": blocked_count,
        "completed_count": completed_count,
        "selection_idle_reason": idle_reason or None,
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "protected_path_incident": bool(protected_incident),
        "reasons": reasons,
    }


def evaluate_merge_queue(state_root: Path) -> dict[str, Any]:
    queue_dir = state_root / "merge_queue"
    counts: dict[str, int] = {}
    task_id_count = 0
    malformed = 0
    if not queue_dir.is_dir():
        return {
            "exists": False,
            "depth": 0,
            "counts": {},
            "task_id_count": 0,
            "malformed_json": 0,
            "state": ComponentState.DRAINED.value,
        }
    depth = 0
    for path in sorted(queue_dir.rglob("*.json"))[:500]:
        depth += 1
        payload = load_json(path)
        if payload is None:
            malformed += 1
            continue
        status = str(payload.get("status") or payload.get("state") or "").strip().lower()
        if status:
            counts[status] = counts.get(status, 0) + 1
        task_id = str(
            payload.get("canonical_task_id")
            or payload.get("task_id")
            or payload.get("source_task_id")
            or ""
        ).strip()
        if task_id.startswith("PATLAW-"):
            task_id_count += 1
    state = ComponentState.DRAINED.value if depth == 0 else ComponentState.ACTIVE.value
    if malformed:
        state = _worse(state, ComponentState.DEGRADED.value)
    return {
        "exists": True,
        "depth": depth,
        "counts": dict(sorted(counts.items())),
        "task_id_count": task_id_count,
        "malformed_json": malformed,
        "state": state,
    }


def evaluate_supervisor_board(
    state_root: Path | None,
    *,
    thresholds: Mapping[str, int],
    now: datetime,
    shard_count: int = 4,
) -> dict[str, Any]:
    if state_root is None or not Path(state_root).exists():
        return {
            "present": False,
            "state": ComponentState.MISSING.value,
            "shard_count": 0,
            "shards": [],
            "merge_queue": {
                "exists": False,
                "depth": 0,
                "counts": {},
                "task_id_count": 0,
                "malformed_json": 0,
                "state": ComponentState.MISSING.value,
            },
            "drained": False,
            "active": False,
            "reasons": ["supervisor state root absent"],
        }

    root = Path(state_root)
    # Allow explicit shard_count override via board projection.
    board_proj = load_json(root / "production_board.json") or {}
    if "shard_count" in board_proj:
        try:
            shard_count = int(board_proj["shard_count"])
        except (TypeError, ValueError):
            pass

    heartbeat_limit = int(
        thresholds.get("supervisor_heartbeat_max_age_seconds")
        or DEFAULT_THRESHOLDS["supervisor_heartbeat_max_age_seconds"]
    )
    shards = [
        evaluate_supervisor_shard(
            shard=i,
            state_root=root,
            heartbeat_limit=heartbeat_limit,
            now=now,
        )
        for i in range(shard_count)
    ]
    queue = evaluate_merge_queue(root)

    reasons: list[str] = []
    any_blocked = any(s["state"] == ComponentState.BLOCKED.value for s in shards)
    any_active = any(s["state"] == ComponentState.ACTIVE.value for s in shards) or (
        queue.get("state") == ComponentState.ACTIVE.value
    )
    any_stale = any(s["state"] == ComponentState.STALE.value for s in shards)
    any_degraded = any(s["state"] == ComponentState.DEGRADED.value for s in shards)
    all_drained = bool(shards) and all(
        s["state"] == ComponentState.DRAINED.value
        or (s.get("drained") and s["state"] not in {ComponentState.BLOCKED.value, ComponentState.ACTIVE.value})
        for s in shards
    ) and queue.get("depth", 0) == 0

    if any_blocked:
        state = ComponentState.BLOCKED.value
        reasons.append("one or more supervisor shards blocked")
    elif any_active:
        state = ComponentState.ACTIVE.value
    elif any_stale:
        state = ComponentState.STALE.value
        reasons.append("one or more supervisor shards stale")
    elif any_degraded:
        state = ComponentState.DEGRADED.value
    elif all_drained:
        state = ComponentState.DRAINED.value
    elif not shards:
        state = ComponentState.MISSING.value
        reasons.append("no supervisor shards observed")
    else:
        state = ComponentState.HEALTHY.value

    for s in shards:
        reasons.extend(f"shard {s['shard']}: {r}" for r in s.get("reasons") or [])

    return {
        "present": True,
        "state": state,
        "shard_count": len(shards),
        "shards": shards,
        "merge_queue": queue,
        "drained": all_drained,
        "active": any_active,
        "reasons": reasons[:32],
    }


# ---------------------------------------------------------------------------
# Overall aggregation
# ---------------------------------------------------------------------------


def _component_reasons(components: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for name, comp in components.items():
        for reason in comp.get("reasons") or []:
            out.append(f"{name}: {reason}")
    return out


def classify_overall(
    *,
    components: Mapping[str, Mapping[str, Any]],
    supervisor: Mapping[str, Any],
    missing_mandatory: Sequence[str],
    completion: Mapping[str, Any],
) -> tuple[str, bool, list[str]]:
    """Return (overall_state, readiness, reasons).

    Readiness is False when any mandatory receipt is missing or any mandatory
    component reports blocked/missing.
    """
    reasons: list[str] = []
    if missing_mandatory:
        reasons.append(
            "missing mandatory receipts: " + ", ".join(sorted(missing_mandatory))
        )

    mandatory_blocked = False
    any_stale = False
    any_degraded = False
    any_active = bool(supervisor.get("active"))
    for name, comp in components.items():
        state = str(comp.get("state") or "")
        mandatory = bool(comp.get("mandatory"))
        if mandatory and state in {
            ComponentState.MISSING.value,
            ComponentState.BLOCKED.value,
        }:
            mandatory_blocked = True
        if state == ComponentState.STALE.value:
            any_stale = True
        if state == ComponentState.DEGRADED.value:
            any_degraded = True
        if state == ComponentState.ACTIVE.value:
            any_active = True
        if state == ComponentState.BLOCKED.value:
            # non-mandatory block still elevates
            if not mandatory:
                any_degraded = True

    if supervisor.get("state") == ComponentState.BLOCKED.value:
        mandatory_blocked = True
    if supervisor.get("state") == ComponentState.STALE.value:
        any_stale = True
    if supervisor.get("state") == ComponentState.DEGRADED.value:
        any_degraded = True
    if supervisor.get("state") == ComponentState.ACTIVE.value:
        any_active = True

    reasons.extend(_component_reasons(components)[:24])
    for r in supervisor.get("reasons") or []:
        reasons.append(f"supervisor: {r}")

    readiness = not missing_mandatory and not mandatory_blocked
    # Completion alone never forces readiness if mandatory evidence is missing.
    completion_ok = (
        completion.get("present")
        and completion.get("state") == ComponentState.COMPLETED.value
    )
    drained = bool(supervisor.get("drained")) and not any_active

    if not readiness:
        overall = OverallState.BLOCKED.value
    elif any_stale and not any_active:
        # Freshness budgets exceeded; still not ready for "healthy".
        overall = OverallState.STALE.value
        # Stale does not by itself clear readiness if mandatory components ok.
    elif any_degraded and not any_active:
        overall = OverallState.DEGRADED.value
    elif any_active:
        overall = OverallState.ACTIVE.value
    elif drained and completion_ok and readiness:
        overall = OverallState.COMPLETED.value
    elif drained and readiness:
        overall = OverallState.DRAINED.value
    elif drained and not readiness:
        # Should have been caught by readiness, but keep explicit.
        overall = OverallState.BLOCKED.value
    else:
        overall = OverallState.HEALTHY.value

    # Cap reasons list; keep unique order.
    seen: set[str] = set()
    compact: list[str] = []
    for r in reasons:
        text = sanitize_text(r)
        if text and text not in seen:
            seen.add(text)
            compact.append(text)
        if len(compact) >= 40:
            break
    return overall, readiness, compact


def build_production_status(
    *,
    evidence_root: Path,
    state_root: Path | None = None,
    now: datetime | None = None,
    shard_count: int = 4,
    include_supervisor: bool = True,
) -> dict[str, Any]:
    """Build a content-free production freshness / release observability report."""
    clock = now or datetime.now(timezone.utc)
    evidence_root = Path(evidence_root)
    thresholds = load_thresholds(evidence_root)

    components: dict[str, dict[str, Any]] = {}

    # Mandatory + optional receipts.
    auth_payload, auth_presence = load_receipt(evidence_root, "authority_freshness")
    # Merge optional readiness file into authority evaluation if present.
    ready_payload, ready_presence = load_receipt(evidence_root, "authority_readiness")
    if auth_payload is not None and ready_presence == "present" and ready_payload:
        merged = dict(auth_payload)
        merged["readiness"] = ready_payload
        if "ready" in ready_payload and "authoritative_ready" not in merged:
            merged["authoritative_ready"] = ready_payload.get("ready")
        auth_payload = merged
    components["authority_freshness"] = evaluate_authority_freshness(
        auth_payload, presence=auth_presence, thresholds=thresholds, now=clock
    )

    idx_payload, idx_presence = load_receipt(evidence_root, "index_evaluation")
    components["index_evaluation"] = evaluate_index_evaluation(
        idx_payload, presence=idx_presence, thresholds=thresholds, now=clock
    )

    poll_payload, poll_presence = load_receipt(evidence_root, "matter_polling")
    components["matter_polling"] = evaluate_matter_polling(
        poll_payload, presence=poll_presence, thresholds=thresholds, now=clock
    )

    iso_payload, iso_presence = load_receipt(evidence_root, "isolation_status")
    components["isolation_status"] = evaluate_isolation(
        iso_payload, presence=iso_presence
    )

    filing_payload, filing_presence = load_receipt(evidence_root, "filing_handoff")
    components["filing_handoff"] = evaluate_filing_handoff(
        filing_payload, presence=filing_presence
    )

    hub_payload, hub_presence = load_receipt(evidence_root, "hub_verification")
    components["hub_verification"] = evaluate_hub_verification(
        hub_payload, presence=hub_presence, thresholds=thresholds, now=clock
    )

    sync_payload, sync_presence = load_receipt(evidence_root, "paired_revision_sync")
    components["paired_revision_sync"] = evaluate_paired_sync(
        sync_payload, presence=sync_presence, thresholds=thresholds, now=clock
    )

    completion_payload, completion_presence = load_receipt(evidence_root, "completion")
    completion = evaluate_completion(
        completion_payload, presence=completion_presence
    )
    components["completion"] = completion

    missing_mandatory = [
        kind
        for kind in MANDATORY_RECEIPT_KINDS
        if not components.get(kind, {}).get("present")
    ]

    if include_supervisor:
        supervisor = evaluate_supervisor_board(
            state_root,
            thresholds=thresholds,
            now=clock,
            shard_count=shard_count,
        )
    else:
        # Supervisor omitted: do not force drained/active; overall may be healthy.
        supervisor = {
            "present": False,
            "state": ComponentState.HEALTHY.value,
            "shard_count": 0,
            "shards": [],
            "merge_queue": {
                "exists": False,
                "depth": 0,
                "counts": {},
                "task_id_count": 0,
                "malformed_json": 0,
                "state": ComponentState.DRAINED.value,
            },
            "drained": False,
            "active": False,
            "reasons": [],
        }

    overall, readiness, reasons = classify_overall(
        components=components,
        supervisor=supervisor,
        missing_mandatory=missing_mandatory,
        completion=completion,
    )

    # Watermark summary (safe fields only).
    watermarks = {
        "authority_current_through": components["authority_freshness"].get(
            "current_through"
        ),
        "authority_age_seconds": components["authority_freshness"].get("age_seconds"),
        "index_age_seconds": components["index_evaluation"].get("age_seconds"),
        "matter_poll_lag_seconds": components["matter_polling"].get("lag_seconds"),
        "sync_pair_age_seconds": components["paired_revision_sync"].get(
            "pair_age_seconds"
        ),
        "hub_age_seconds": components["hub_verification"].get("age_seconds"),
    }

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "as_of": clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_state": overall,
        "readiness": readiness,
        "readiness_blocked": not readiness,
        "missing_mandatory_receipts": list(missing_mandatory),
        "mandatory_receipt_kinds": list(MANDATORY_RECEIPT_KINDS),
        "watermarks": watermarks,
        "components": components,
        "supervisor": supervisor,
        "thresholds": dict(sorted(thresholds.items())),
        "evidence_root": str(evidence_root),
        "state_root": str(state_root) if state_root else None,
        "reasons": reasons,
        "states_distinguished": sorted(OVERALL_STATES),
    }

    # Self-digest for receipt binding (excludes digest field).
    body = {k: v for k, v in report.items() if k != "report_digest_sha256"}
    report["report_digest_sha256"] = sha256_hex(canonical_json(body))

    # Fail closed on content leakage.
    assert_content_free(report)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_human(report: Mapping[str, Any]) -> None:
    print(
        f"PATLAW production status: {str(report.get('overall_state')).upper()} "
        f"readiness={'yes' if report.get('readiness') else 'NO'} "
        f"@ {report.get('as_of')}"
    )
    missing = report.get("missing_mandatory_receipts") or []
    if missing:
        print(f"missing mandatory: {', '.join(missing)}")
    wm = report.get("watermarks") or {}
    print(
        "watermarks: "
        f"authority_through={wm.get('authority_current_through') or '-'} "
        f"auth_age={wm.get('authority_age_seconds') if wm.get('authority_age_seconds') is not None else '-'}s "
        f"index_age={wm.get('index_age_seconds') if wm.get('index_age_seconds') is not None else '-'}s "
        f"poll_lag={wm.get('matter_poll_lag_seconds') if wm.get('matter_poll_lag_seconds') is not None else '-'}s "
        f"sync_age={wm.get('sync_pair_age_seconds') if wm.get('sync_pair_age_seconds') is not None else '-'}s "
        f"hub_age={wm.get('hub_age_seconds') if wm.get('hub_age_seconds') is not None else '-'}s"
    )
    for name, comp in (report.get("components") or {}).items():
        print(
            f"  {name}: {comp.get('state')} "
            f"present={comp.get('present')} ready={comp.get('ready')}"
        )
        for reason in comp.get("reasons") or []:
            print(f"    - {reason}")
    sup = report.get("supervisor") or {}
    print(
        f"supervisor: state={sup.get('state')} drained={sup.get('drained')} "
        f"active={sup.get('active')} shards={sup.get('shard_count')}"
    )
    for shard in sup.get("shards") or []:
        print(
            f"  shard {shard.get('shard')}: {shard.get('state')} "
            f"stopped={shard.get('stopped')} drained={shard.get('drained')} "
            f"ready={shard.get('ready_count')} blocked={shard.get('blocked_count')} "
            f"active={shard.get('active_task_id') or '-'}"
        )
        for reason in shard.get("reasons") or []:
            print(f"    - {reason}")
    for reason in report.get("reasons") or []:
        print(f"REASON: {reason}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=None,
        help="Root containing content-free production receipts",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Supervisor/merge-queue state root (optional)",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=4,
        help="Supervisor shard count when projecting state-root (default 4)",
    )
    parser.add_argument(
        "--no-supervisor",
        action="store_true",
        help="Skip supervisor/merge-queue projection",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = Path(
        os.environ.get("PATLAW_PRODUCTION_EVIDENCE_ROOT")
        or os.environ.get("PATLAW_PRODUCTION_STATE_ROOT")
        or args.evidence_root
        or default_evidence_root()
    ).expanduser()
    state_env = os.environ.get("PATLAW_STATE_ROOT")
    state_root: Path | None
    if args.state_root is not None:
        state_root = Path(args.state_root).expanduser()
    elif state_env:
        state_root = Path(state_env).expanduser()
    else:
        # Prefer sibling supervisor state under default layout when present.
        candidate = default_state_root()
        state_root = candidate if candidate.exists() else None

    report = build_production_status(
        evidence_root=evidence,
        state_root=None if args.no_supervisor else state_root,
        shard_count=max(0, int(args.shard_count)),
        include_supervisor=not args.no_supervisor,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)

    # Exit codes: 0 ready+healthy/drained/completed/active; 1 blocked; 2 stale/degraded.
    overall = report.get("overall_state")
    if not report.get("readiness") or overall == OverallState.BLOCKED.value:
        return 1
    if overall in {OverallState.STALE.value, OverallState.DEGRADED.value}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
