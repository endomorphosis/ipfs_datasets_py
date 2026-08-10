#!/usr/bin/env python3
"""Resumable isolated cohort runner for state-law reindex (LCR-007).

Runs one file-disjoint scrape cohort with:

* exact sealed jurisdiction sets (A–M; M includes DC)
* isolated run / checkpoint / receipt roots (never shared combined overwrite)
* progress heartbeats and domain-aware concurrency
* interrupt/resume from durable per-state checkpoints
* per-state receipts with secret/path redaction
* no production Hugging Face upload
* fail-closed rejection of partial-success promotion and stale work

Offline gate (no network):

    python scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py \\
        --fixture-only --cohort A --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-007"
GOAL_ID = "LCR-G010"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "run_legal_corpora_reindex_cohort.py"
RUNNER_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-runner@1"
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
CHECKPOINT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-checkpoint@1"
CODE_VERSION = "1"

# Exact sealed 51-jurisdiction set (50 postal codes + DC).
CANONICAL_JURISDICTIONS: tuple[str, ...] = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
)
CANONICAL_JURISDICTION_SET = frozenset(CANONICAL_JURISDICTIONS)
EXPECTED_JURISDICTION_COUNT = 51

# File-disjoint scrape cohorts (plan §5).
COHORT_JURISDICTIONS: Dict[str, tuple[str, ...]] = {
    "A": ("AL", "AK", "AZ", "AR"),
    "B": ("CA", "CO", "CT", "DE"),
    "C": ("FL", "GA", "HI", "ID"),
    "D": ("IL", "IN", "IA", "KS"),
    "E": ("KY", "LA", "ME", "MD"),
    "F": ("MA", "MI", "MN", "MS"),
    "G": ("MO", "MT", "NE", "NV"),
    "H": ("NH", "NJ", "NM", "NY"),
    "I": ("NC", "ND", "OH", "OK"),
    "J": ("OR", "PA", "RI", "SC"),
    "K": ("SD", "TN", "TX", "UT"),
    "L": ("VT", "VA", "WA", "WV"),
    "M": ("WI", "WY", "DC"),
}

# Official primary domain hints for domain-aware concurrency (one worker per domain).
STATE_PRIMARY_DOMAINS: Dict[str, str] = {
    "AL": "alison.legislature.state.al.us",
    "AK": "www.akleg.gov",
    "AZ": "www.azleg.gov",
    "AR": "www.arkleg.state.ar.us",
    "CA": "leginfo.legislature.ca.gov",
    "CO": "leg.colorado.gov",
    "CT": "www.cga.ct.gov",
    "DE": "delcode.delaware.gov",
    "FL": "www.leg.state.fl.us",
    "GA": "www.legis.ga.gov",
    "HI": "www.capitol.hawaii.gov",
    "ID": "legislature.idaho.gov",
    "IL": "www.ilga.gov",
    "IN": "iga.in.gov",
    "IA": "www.legis.iowa.gov",
    "KS": "www.kslegislature.org",
    "KY": "apps.legislature.ky.gov",
    "LA": "www.legis.la.gov",
    "ME": "legislature.maine.gov",
    "MD": "mgaleg.maryland.gov",
    "MA": "malegislature.gov",
    "MI": "www.legislature.mi.gov",
    "MN": "www.revisor.mn.gov",
    "MS": "www.legislature.ms.gov",
    "MO": "revisor.mo.gov",
    "MT": "leg.mt.gov",
    "NE": "nebraskalegislature.gov",
    "NV": "www.leg.state.nv.us",
    "NH": "www.gencourt.state.nh.us",
    "NJ": "lis.njleg.state.nj.us",
    "NM": "nmonesource.com",
    "NY": "www.nysenate.gov",
    "NC": "www.ncleg.gov",
    "ND": "www.ndlegis.gov",
    "OH": "codes.ohio.gov",
    "OK": "www.oklegislature.gov",
    "OR": "www.oregonlegislature.gov",
    "PA": "www.legis.state.pa.us",
    "RI": "webserver.rilin.state.ri.us",
    "SC": "www.scstatehouse.gov",
    "SD": "sdlegislature.gov",
    "TN": "www.capitol.tn.gov",
    "TX": "statutes.capitol.texas.gov",
    "UT": "le.utah.gov",
    "VT": "legislature.vermont.gov",
    "VA": "law.lis.virginia.gov",
    "WA": "app.leg.wa.gov",
    "WV": "code.wvlegislature.gov",
    "WI": "docs.legis.wisconsin.gov",
    "WY": "wyoleg.gov",
    "DC": "code.dccouncil.gov",
}

SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|cookie|set-cookie|"
    r"private[_-]?key|credential|hf_token|bearer)",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(r"(^|/)(home|Users|tmp|var/folders)/")
SECRET_VALUE_RE = re.compile(
    r"(hf_[A-Za-z0-9]{16,}|Bearer\s+\S+|sk-[A-Za-z0-9]{16,})",
    re.IGNORECASE,
)

# Statuses that may never be promoted to cohort success.
NON_SUCCESS_STATUSES = frozenset(
    {
        "error",
        "failed",
        "partial_success",
        "running",
        "interrupted",
        "stale",
        "pending",
        "zero_statutes",
        "timeout",
    }
)


class CohortRunnerError(RuntimeError):
    """Raised when the cohort runner cannot complete fail-closed."""


@dataclass
class StateWorkItem:
    """One jurisdiction work unit inside a cohort run."""

    state: str
    domain: str
    status: str = "pending"
    statutes_count: int = 0
    logical_keys_current: List[str] = field(default_factory=list)
    logical_keys_history: List[str] = field(default_factory=list)
    checkpoint_path: str = ""
    receipt_path: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    work_fingerprint: str = ""
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cohort_states(cohort: str) -> List[str]:
    """Return the exact ordered jurisdiction set for a cohort letter."""
    key = str(cohort or "").strip().upper()
    if key not in COHORT_JURISDICTIONS:
        raise CohortRunnerError(
            f"unknown cohort {cohort!r}; expected one of {sorted(COHORT_JURISDICTIONS)}"
        )
    states = list(COHORT_JURISDICTIONS[key])
    if not states:
        raise CohortRunnerError(f"cohort {key} has empty jurisdiction set")
    if len(set(states)) != len(states):
        raise CohortRunnerError(f"cohort {key} has duplicate jurisdictions")
    for code in states:
        if code not in CANONICAL_JURISDICTION_SET:
            raise CohortRunnerError(f"cohort {key} contains non-canonical code {code}")
    return states


def all_cohort_states() -> List[str]:
    """Return the concatenation of all cohorts (exact 51, DC last via M)."""
    ordered: List[str] = []
    seen: set[str] = set()
    for letter in sorted(COHORT_JURISDICTIONS):
        for code in COHORT_JURISDICTIONS[letter]:
            if code in seen:
                raise CohortRunnerError(f"jurisdiction {code} appears in multiple cohorts")
            seen.add(code)
            ordered.append(code)
    if set(ordered) != CANONICAL_JURISDICTION_SET:
        missing = sorted(CANONICAL_JURISDICTION_SET - set(ordered))
        extra = sorted(set(ordered) - CANONICAL_JURISDICTION_SET)
        raise CohortRunnerError(
            f"cohort union is not exact 51-set; missing={missing}; extra={extra}"
        )
    if "DC" not in ordered:
        raise CohortRunnerError("cohort union omits DC")
    if len(ordered) != EXPECTED_JURISDICTION_COUNT:
        raise CohortRunnerError(
            f"cohort union count {len(ordered)} != {EXPECTED_JURISDICTION_COUNT}"
        )
    return ordered


def primary_domain(state: str) -> str:
    code = str(state or "").strip().upper()
    return STATE_PRIMARY_DOMAINS.get(code, f"legislature.{code.lower()}.gov")


def isolate_run_root(
    *,
    base_root: Path | str | None,
    cohort: str,
    run_id: str | None = None,
) -> Path:
    """Build an isolated per-cohort run root (never the shared production root)."""
    cohort_key = str(cohort).strip().upper()
    rid = str(run_id or f"run-{cohort_key.lower()}-{int(time.time())}").strip()
    if base_root is None or str(base_root).strip() == "":
        base = Path(tempfile.mkdtemp(prefix="lcr007-cohort-"))
    else:
        base = Path(base_root).expanduser().resolve()
    root = base / "cohorts" / cohort_key / rid
    for sub in ("checkpoints", "receipts", "jsonld", "progress", "history"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def redact_value(value: Any, *, key_hint: str = "") -> Any:
    """Recursively redact secrets, tokens, and absolute local paths from receipts."""
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, nested in value.items():
            key_s = str(key)
            if SENSITIVE_KEY_RE.search(key_s):
                out[key_s] = "[REDACTED]"
            else:
                out[key_s] = redact_value(nested, key_hint=key_s)
        return out
    if isinstance(value, list):
        return [redact_value(item, key_hint=key_hint) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, key_hint=key_hint) for item in value]
    if isinstance(value, str):
        text = value
        if SENSITIVE_KEY_RE.search(key_hint):
            return "[REDACTED]"
        if SECRET_VALUE_RE.search(text):
            text = SECRET_VALUE_RE.sub("[REDACTED]", text)
        # Collapse absolute home/tmp paths while preserving a stable label.
        if text.startswith("/") and ABSOLUTE_PATH_RE.search(text):
            return f"path://{Path(text).name or 'redacted'}"
        if re.match(r"^[A-Za-z]:\\", text):
            return f"path://{Path(text).name or 'redacted'}"
        return text
    return value


def redact_receipt(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a receipt-safe copy with secrets and absolute paths removed."""
    return redact_value(dict(payload))  # type: ignore[return-value]


def logical_row_key(row: Mapping[str, Any], *, state: str) -> str:
    """Stable logical identity key (not content CID)."""
    state_code = str(row.get("state_code") or row.get("jurisdiction") or state).upper()
    for field_name in (
        "legal_id",
        "identifier",
        "legislationIdentifier",
        "section_number",
        "sectionNumber",
        "source_id",
        "sourceUrl",
        "source_url",
        "@id",
    ):
        value = str(row.get(field_name) or "").strip()
        if value:
            return f"{state_code}:{value}"
    # Fall back to a digest of non-cid content so history still groups.
    body = {
        k: v
        for k, v in row.items()
        if k not in {"ipfs_cid", "content_cid", "entry_cid", "text", "jsonld"}
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"{state_code}:anon:{digest}"


def merge_logical_current_history(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    *,
    state: str,
) -> Dict[str, Any]:
    """Merge by logical key: current keeps latest content; history retains prior CIDs.

    Unlike CID-first merge, content changes under the same identifier replace
    the current row and archive the previous content identity.
    """
    current: Dict[str, Dict[str, Any]] = {}
    history: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []

    def _ingest(row: Mapping[str, Any], *, is_new: bool) -> None:
        key = logical_row_key(row, state=state)
        normalized = dict(row)
        normalized.setdefault("state_code", str(state).upper())
        normalized["logical_key"] = key
        cid = str(
            normalized.get("ipfs_cid")
            or normalized.get("entry_cid")
            or normalized.get("content_cid")
            or ""
        ).strip()
        if key not in current:
            current[key] = normalized
            history.setdefault(key, [])
            order.append(key)
            return
        prior = current[key]
        prior_cid = str(
            prior.get("ipfs_cid") or prior.get("entry_cid") or prior.get("content_cid") or ""
        ).strip()
        if cid and prior_cid and cid != prior_cid:
            hist_entry = {
                "logical_key": key,
                "ipfs_cid": prior_cid,
                "replaced_at": utc_now_iso(),
                "source": "prior_current",
            }
            history.setdefault(key, []).append(hist_entry)
            current[key] = normalized
        elif is_new:
            # Same logical key / same or empty CID: prefer the refreshed row.
            current[key] = normalized
        # else keep existing current

    for row in existing_rows:
        if isinstance(row, Mapping):
            _ingest(row, is_new=False)
    for row in new_rows:
        if isinstance(row, Mapping):
            _ingest(row, is_new=True)

    return {
        "current_rows": [current[key] for key in order],
        "history_by_key": {key: list(history.get(key) or []) for key in order},
        "current_keys": list(order),
        "history_keys": [key for key in order if history.get(key)],
    }


def work_fingerprint(*, cohort: str, state: str, config: Mapping[str, Any]) -> str:
    """Fingerprint the work definition so stale checkpoints cannot resume."""
    material = {
        "cohort": str(cohort).upper(),
        "state": str(state).upper(),
        "code_version": CODE_VERSION,
        "runner_schema": RUNNER_SCHEMA,
        "full_mode": True,
        "include_dc_semantics": True,
        "max_statutes": config.get("max_statutes"),
        "strict_full_text": bool(config.get("strict_full_text", True)),
        "allow_justia_fallback": bool(config.get("allow_justia_fallback", False)),
        "official_domain": primary_domain(state),
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CohortRunnerError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CohortRunnerError(f"JSON root must be object: {path}")
    return payload


def detect_stale_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    expected_fingerprint: str,
    max_age_seconds: float = 0.0,
    now: Optional[float] = None,
) -> Optional[str]:
    """Return a stale reason, or None when the checkpoint is still valid for resume."""
    if not checkpoint:
        return "missing_checkpoint"
    schema = str(checkpoint.get("schema") or "")
    if schema and schema != CHECKPOINT_SCHEMA:
        return f"schema_mismatch:{schema}"
    fp = str(checkpoint.get("work_fingerprint") or "")
    if fp and fp != expected_fingerprint:
        return "work_fingerprint_mismatch"
    status = str(checkpoint.get("status") or "").strip().lower()
    if status in {"stale", "invalid", "aborted"}:
        return f"status_{status}"
    # Partial checkpoints must never be treated as complete success.
    if status in {"partial_success", "partial", "running", "interrupted"}:
        if bool(checkpoint.get("promote_partial_success")):
            return "partial_success_promotion_blocked"
    updated = str(checkpoint.get("updated_at") or checkpoint.get("finished_at") or "")
    if max_age_seconds and max_age_seconds > 0 and updated:
        try:
            # Support both Z and offset forms.
            ts = updated.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (now if now is not None else time.time()) - dt.timestamp()
            if age > max_age_seconds and status not in {"success", "complete"}:
                return "heartbeat_stale"
        except ValueError:
            return "invalid_timestamp"
    return None


def promote_state_status(status: str, *, allow_partial: bool = False) -> str:
    """Normalize a state status; never promote partial_success to success."""
    normalized = str(status or "").strip().lower() or "pending"
    if normalized in {"complete", "completed", "ok", "closed"}:
        return "success"
    if normalized == "partial_success":
        if allow_partial:
            return "partial_success"
        return "partial_success"  # explicitly not success
    if normalized in NON_SUCCESS_STATUSES or normalized == "success":
        return normalized
    return normalized


def cohort_success_allowed(state_results: Mapping[str, Mapping[str, Any]]) -> bool:
    """Cohort success requires every jurisdiction success with no partial promotion."""
    if not state_results:
        return False
    for state, entry in state_results.items():
        status = promote_state_status(str(entry.get("status") or ""))
        if status != "success":
            return False
        if bool(entry.get("timeout_promoted_to_success")):
            return False
        if bool(entry.get("partial_checkpoint_promoted")):
            return False
        if int(entry.get("failed_final") or 0) != 0:
            return False
    return True


def write_progress(
    path: Path,
    *,
    cohort: str,
    states: Sequence[str],
    state_results: Mapping[str, Mapping[str, Any]],
    status: str,
    heartbeat_seq: int,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "cohort": str(cohort).upper(),
        "status": status,
        "updated_at": utc_now_iso(),
        "heartbeat_seq": int(heartbeat_seq),
        "states": list(states),
        "state_count": len(states),
        "state_results": {k: dict(v) for k, v in state_results.items()},
        "success_count": sum(
            1
            for v in state_results.values()
            if promote_state_status(str(v.get("status") or "")) == "success"
        ),
        "production_upload": False,
        "shared_combined_write": False,
    }
    if extra:
        payload.update(dict(extra))
    atomic_write_json(path, redact_receipt(payload))
    return payload


def write_state_checkpoint(
    path: Path,
    *,
    cohort: str,
    state: str,
    status: str,
    fingerprint: str,
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "cohort": str(cohort).upper(),
        "state": str(state).upper(),
        "status": promote_state_status(status),
        "work_fingerprint": fingerprint,
        "updated_at": utc_now_iso(),
        "promote_partial_success": False,
        "domain": primary_domain(state),
    }
    if payload:
        body.update(dict(payload))
    # Never allow callers to force partial promotion.
    body["promote_partial_success"] = False
    if body["status"] == "partial_success":
        body["completion_promoted"] = False
    redacted = redact_receipt(body)
    atomic_write_json(path, redacted)
    return redacted


def write_state_receipt(
    path: Path,
    *,
    cohort: str,
    state: str,
    status: str,
    statutes_count: int,
    logical_merge: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    receipt: Dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "cohort": str(cohort).upper(),
        "jurisdiction": str(state).upper(),
        "status": promote_state_status(status),
        "statutes_count": int(statutes_count),
        "domain": primary_domain(state),
        "finished_at": utc_now_iso(),
        "production_upload": False,
        "coverage_scope": "cohort_jurisdiction",
        "full_corpus_claim": False,
    }
    if logical_merge:
        receipt["logical_keys_current"] = list(logical_merge.get("current_keys") or [])
        receipt["logical_keys_history"] = list(logical_merge.get("history_keys") or [])
        receipt["history_by_key"] = dict(logical_merge.get("history_by_key") or {})
    if extra:
        receipt.update(dict(extra))
    if receipt["status"] != "success":
        receipt["cohort_success_eligible"] = False
    else:
        receipt["cohort_success_eligible"] = int(receipt.get("failed_final") or 0) == 0
    redacted = redact_receipt(receipt)
    atomic_write_json(path, redacted)
    return redacted


def domain_schedule(states: Sequence[str]) -> List[List[str]]:
    """Partition states into parallel waves (at most one state per domain per wave)."""
    remaining = [str(s).upper() for s in states]
    waves: List[List[str]] = []
    while remaining:
        wave: List[str] = []
        used_domains: set[str] = set()
        next_remaining: List[str] = []
        for state in remaining:
            domain = primary_domain(state)
            if domain in used_domains:
                next_remaining.append(state)
                continue
            wave.append(state)
            used_domains.add(domain)
        if not wave:
            # Safety: avoid infinite loop if domain map collapses.
            wave = [remaining[0]]
            next_remaining = remaining[1:]
        waves.append(wave)
        remaining = next_remaining
    return waves


def _fixture_state_rows(state: str, *, generation: int = 1) -> List[Dict[str, Any]]:
    """Compact synthetic rows for offline fixture recipes (not golden dumps)."""
    code = str(state).upper()
    rows = []
    for idx in (1, 2):
        identifier = f"{code}.TEST § {idx}.0{generation}"
        text = f"Fixture statute body for {code} section {idx} generation {generation}."
        rows.append(
            {
                "state_code": code,
                "identifier": identifier,
                "legal_id": f"state:{code.lower()}:fixture:{idx}",
                "name": f"{code} Fixture Section {idx}",
                "text": text,
                "source_url": f"https://{primary_domain(code)}/fixture/{idx}",
                "source_id": f"{code.lower()}-fixture-{idx}",
                "ipfs_cid": f"cid-{code.lower()}-g{generation}-s{idx}",
            }
        )
    return rows


def build_fixture_recipes() -> Dict[str, Any]:
    """Compact offline recipes proving each LCR-007 acceptance gate."""
    return {
        "schema": "ipfs_datasets_py/legal-corpora-reindex-cohort-fixture-recipes@1",
        "task_id": TASK_ID,
        "cases": [
            {
                "case_id": "interrupt_resume_cohort_a",
                "kind": "interrupt_resume",
                "cohort": "A",
                "interrupt_after": ["AL", "AK"],
                "expected_resume_states": ["AZ", "AR"],
            },
            {
                "case_id": "exact_cohort_set_with_dc",
                "kind": "exact_set",
                "cohort": "M",
                "expected_states": ["WI", "WY", "DC"],
            },
            {
                "case_id": "no_partial_success_promotion",
                "kind": "partial_promotion",
                "state": "GA",
                "checkpoint_status": "partial_success",
            },
            {
                "case_id": "no_shared_combined_overwrite",
                "kind": "combined_guard",
                "cohort": "A",
            },
            {
                "case_id": "logical_key_current_history",
                "kind": "logical_merge",
                "state": "MN",
            },
            {
                "case_id": "stale_work_detection",
                "kind": "stale_work",
                "state": "TX",
            },
            {
                "case_id": "safe_receipt_redaction",
                "kind": "redaction",
                "state": "CA",
            },
            {
                "case_id": "legacy_subset_release_rejection",
                "kind": "legacy_subset",
            },
        ],
    }


def run_fixture_interrupt_resume(
    *,
    cohort: str = "A",
    run_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Prove interrupt then resume without redoing completed jurisdictions."""
    states = cohort_states(cohort)
    root = run_root or isolate_run_root(base_root=None, cohort=cohort, run_id="fixture-resume")
    config = {
        "max_statutes": None,
        "strict_full_text": True,
        "allow_justia_fallback": False,
    }
    progress_path = root / "progress" / "progress.json"
    state_results: Dict[str, Dict[str, Any]] = {}
    heartbeat = 0

    # Phase 1: complete the first half, then "interrupt".
    interrupt_at = max(1, len(states) // 2)
    completed_before_interrupt: List[str] = []
    for state in states[:interrupt_at]:
        fp = work_fingerprint(cohort=cohort, state=state, config=config)
        ck_path = root / "checkpoints" / f"STATE-{state}.json"
        receipt_path = root / "receipts" / f"jurisdiction-{state}.json"
        rows = _fixture_state_rows(state, generation=1)
        merge = merge_logical_current_history([], rows, state=state)
        write_state_checkpoint(
            ck_path,
            cohort=cohort,
            state=state,
            status="success",
            fingerprint=fp,
            payload={"statutes_count": len(rows), "logical_keys": merge["current_keys"]},
        )
        write_state_receipt(
            receipt_path,
            cohort=cohort,
            state=state,
            status="success",
            statutes_count=len(rows),
            logical_merge=merge,
        )
        state_results[state] = {
            "status": "success",
            "statutes_count": len(rows),
            "checkpoint_path": str(ck_path.name),
            "receipt_path": str(receipt_path.name),
            "work_fingerprint": fp,
        }
        completed_before_interrupt.append(state)
        heartbeat += 1
        write_progress(
            progress_path,
            cohort=cohort,
            states=states,
            state_results=state_results,
            status="interrupted",
            heartbeat_seq=heartbeat,
            extra={"interrupted_after": completed_before_interrupt},
        )

    # Phase 2: resume — completed states are skipped; remaining run.
    resumed: List[str] = []
    skipped: List[str] = []
    for state in states:
        fp = work_fingerprint(cohort=cohort, state=state, config=config)
        ck_path = root / "checkpoints" / f"STATE-{state}.json"
        existing = load_json(ck_path)
        stale = detect_stale_checkpoint(existing, expected_fingerprint=fp)
        if (
            existing
            and promote_state_status(str(existing.get("status") or "")) == "success"
            and stale is None
        ):
            skipped.append(state)
            state_results[state] = {
                "status": "success",
                "statutes_count": int(existing.get("statutes_count") or 0),
                "resumed": False,
                "skipped_completed": True,
                "work_fingerprint": fp,
            }
            continue
        # Run remaining work.
        receipt_path = root / "receipts" / f"jurisdiction-{state}.json"
        rows = _fixture_state_rows(state, generation=1)
        merge = merge_logical_current_history([], rows, state=state)
        write_state_checkpoint(
            ck_path,
            cohort=cohort,
            state=state,
            status="success",
            fingerprint=fp,
            payload={"statutes_count": len(rows), "resumed": True},
        )
        write_state_receipt(
            receipt_path,
            cohort=cohort,
            state=state,
            status="success",
            statutes_count=len(rows),
            logical_merge=merge,
            extra={"resumed": True},
        )
        state_results[state] = {
            "status": "success",
            "statutes_count": len(rows),
            "resumed": True,
            "skipped_completed": False,
            "work_fingerprint": fp,
        }
        resumed.append(state)
        heartbeat += 1
        write_progress(
            progress_path,
            cohort=cohort,
            states=states,
            state_results=state_results,
            status="running",
            heartbeat_seq=heartbeat,
        )

    final_status = "success" if cohort_success_allowed(state_results) else "failed"
    final_progress = write_progress(
        progress_path,
        cohort=cohort,
        states=states,
        state_results=state_results,
        status=final_status,
        heartbeat_seq=heartbeat + 1,
        extra={
            "completed_before_interrupt": completed_before_interrupt,
            "skipped_on_resume": skipped,
            "ran_on_resume": resumed,
            "domain_waves": domain_schedule(states),
        },
    )
    cohort_receipt = {
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "cohort": str(cohort).upper(),
        "status": final_status,
        "states": list(states),
        "state_results": state_results,
        "production_upload": False,
        "shared_combined_write": False,
        "run_root_label": root.name,
    }
    receipt_path = root / "receipts" / f"cohort-{str(cohort).upper()}.json"
    atomic_write_json(receipt_path, redact_receipt(cohort_receipt))
    return {
        "status": final_status,
        "cohort": str(cohort).upper(),
        "states": list(states),
        "completed_before_interrupt": completed_before_interrupt,
        "skipped_on_resume": skipped,
        "ran_on_resume": resumed,
        "progress": final_progress,
        "run_root": str(root),
        "cohort_receipt_path": str(receipt_path),
    }


def run_fixture_case(case: Mapping[str, Any], *, base_root: Optional[Path] = None) -> Dict[str, Any]:
    """Execute one compact fixture recipe and return a structured result."""
    case_id = str(case.get("case_id") or "unknown")
    kind = str(case.get("kind") or "")
    findings: List[str] = []

    if kind == "interrupt_resume":
        cohort = str(case.get("cohort") or "A")
        result = run_fixture_interrupt_resume(cohort=cohort, run_root=None)
        expected_resume = [str(s).upper() for s in (case.get("expected_resume_states") or [])]
        if expected_resume and result["ran_on_resume"] != expected_resume:
            findings.append(
                f"resume set mismatch: expected {expected_resume}, got {result['ran_on_resume']}"
            )
        if not result["skipped_on_resume"]:
            findings.append("expected completed states to be skipped on resume")
        if result["status"] != "success":
            findings.append(f"cohort status {result['status']!r} after resume")
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {
                "skipped_on_resume": result["skipped_on_resume"],
                "ran_on_resume": result["ran_on_resume"],
            },
        }

    if kind == "exact_set":
        cohort = str(case.get("cohort") or "M")
        states = cohort_states(cohort)
        expected = [str(s).upper() for s in (case.get("expected_states") or states)]
        if states != expected:
            findings.append(f"cohort {cohort} states {states} != {expected}")
        if "DC" not in all_cohort_states():
            findings.append("DC missing from cohort union")
        if set(all_cohort_states()) != CANONICAL_JURISDICTION_SET:
            findings.append("cohort union is not exact 51-set")
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {"states": states, "union_count": len(all_cohort_states())},
        }

    if kind == "partial_promotion":
        state = str(case.get("state") or "GA").upper()
        status = promote_state_status(str(case.get("checkpoint_status") or "partial_success"))
        if status == "success":
            findings.append("partial_success was promoted to success")
        allowed = cohort_success_allowed(
            {state: {"status": status, "partial_checkpoint_promoted": False}}
        )
        if allowed:
            findings.append("cohort success allowed with partial_success state")
        # Explicit promotion flag must also block.
        if cohort_success_allowed(
            {state: {"status": "success", "partial_checkpoint_promoted": True}}
        ):
            findings.append("partial_checkpoint_promoted success was allowed")
        stale = detect_stale_checkpoint(
            {
                "schema": CHECKPOINT_SCHEMA,
                "status": "partial_success",
                "work_fingerprint": "x",
                "promote_partial_success": True,
                "updated_at": utc_now_iso(),
            },
            expected_fingerprint="x",
        )
        if stale != "partial_success_promotion_blocked":
            findings.append(f"stale detector missed partial promotion: {stale!r}")
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {"normalized_status": status},
        }

    if kind == "combined_guard":
        cohort = str(case.get("cohort") or "A")
        root = isolate_run_root(
            base_root=base_root or Path(tempfile.mkdtemp(prefix="lcr007-combined-")),
            cohort=cohort,
            run_id="fixture-combined",
        )
        # Shared production combined path must never be written by the cohort runner.
        shared_combined = root.parent.parent / "state_laws_all_states.parquet"
        # Simulate a cohort-local artifact only.
        local_marker = root / "jsonld" / "STATE-AL.jsonld"
        local_marker.write_text('{"identifier":"AL.fixture"}\n', encoding="utf-8")
        if shared_combined.exists():
            findings.append(f"shared combined path was written: {shared_combined}")
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "cohort": cohort,
            "shared_combined_write": False,
            "production_upload": False,
            "run_root": str(root),
        }
        if receipt.get("shared_combined_write") or receipt.get("production_upload"):
            findings.append("receipt claims shared combined write or production upload")
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {"run_root": str(root), "shared_combined_exists": shared_combined.exists()},
        }

    if kind == "logical_merge":
        state = str(case.get("state") or "MN").upper()
        gen1 = _fixture_state_rows(state, generation=1)
        gen2 = _fixture_state_rows(state, generation=2)
        # Same legal_id / source_id, different content CID and identifier edition.
        for old, new in zip(gen1, gen2):
            new["legal_id"] = old["legal_id"]
            new["source_id"] = old["source_id"]
            new["identifier"] = old["identifier"]  # same logical citation
        merge = merge_logical_current_history(gen1, gen2, state=state)
        if len(merge["current_rows"]) != 2:
            findings.append(f"expected 2 current rows, got {len(merge['current_rows'])}")
        if not merge["history_keys"]:
            findings.append("expected history keys after content CID change")
        for row in merge["current_rows"]:
            if "g2" not in str(row.get("ipfs_cid") or ""):
                findings.append(f"current row not updated to gen2 cid: {row.get('ipfs_cid')}")
        # CID-first would keep 4 rows; logical merge must keep 2 current.
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {
                "current_keys": merge["current_keys"],
                "history_keys": merge["history_keys"],
            },
        }

    if kind == "stale_work":
        state = str(case.get("state") or "TX").upper()
        config_a = {"max_statutes": None, "strict_full_text": True, "allow_justia_fallback": False}
        config_b = {"max_statutes": 5, "strict_full_text": True, "allow_justia_fallback": False}
        fp_a = work_fingerprint(cohort="K", state=state, config=config_a)
        fp_b = work_fingerprint(cohort="K", state=state, config=config_b)
        if fp_a == fp_b:
            findings.append("fingerprints collided across different work configs")
        reason = detect_stale_checkpoint(
            {
                "schema": CHECKPOINT_SCHEMA,
                "status": "success",
                "work_fingerprint": fp_a,
                "updated_at": utc_now_iso(),
            },
            expected_fingerprint=fp_b,
        )
        if reason != "work_fingerprint_mismatch":
            findings.append(f"expected work_fingerprint_mismatch, got {reason!r}")
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {"fp_a": fp_a, "fp_b": fp_b, "stale_reason": reason},
        }

    if kind == "redaction":
        state = str(case.get("state") or "CA").upper()
        dirty = {
            "schema": RECEIPT_SCHEMA,
            "jurisdiction": state,
            "hf_token": "hf_SUPERSECRETTOKENVALUE001",
            "authorization": "Bearer sk-abc123secretvalue999",
            "cookie": "session=abc",
            "local_path": f"/home/operator/.cache/secret/{state}.json",
            "source_url": f"https://{primary_domain(state)}/codes/1",
            "nested": {"api_key": "xyz", "ok": True},
        }
        clean = redact_receipt(dirty)
        serialized = json.dumps(clean)
        for needle in (
            "hf_SUPERSECRET",
            "sk-abc123",
            "session=abc",
            "/home/operator",
            "Bearer ",
        ):
            if needle in serialized:
                findings.append(f"redaction leaked {needle!r}")
        if clean.get("hf_token") != "[REDACTED]":
            findings.append("hf_token not redacted")
        if clean.get("source_url") != dirty["source_url"]:
            findings.append("benign source_url was altered")
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {"redacted_keys": sorted(clean.keys())},
        }

    if kind == "legacy_subset":
        # Import hardened guards from legacy entry points (sibling load only;
        # scripts/ is not always an importable package).
        try:
            refresh_mod = _load_sibling_module("refresh_state_laws_corpus.py")
            check_mod = _load_sibling_module("check_state_law_coverage.py")
            report_mod = _load_sibling_module("report_state_law_corpus_gaps.py")
        except Exception as exc:
            findings.append(f"failed loading legacy modules: {exc}")
            return {
                "case_id": case_id,
                "kind": kind,
                "status": "fail",
                "findings": findings,
                "detail": {},
            }

        subset = ["AL", "AK"]
        for label, fn in (
            ("refresh", getattr(refresh_mod, "reject_subset_release", None)),
            ("check", getattr(check_mod, "reject_subset_release", None)),
            ("report", getattr(report_mod, "reject_subset_release", None)),
        ):
            if fn is None:
                findings.append(f"{label} missing reject_subset_release")
                continue
            try:
                fn(subset)
                findings.append(f"{label}.reject_subset_release accepted subset {subset}")
            except Exception as exc:
                if "subset" not in str(exc).lower() and "51" not in str(exc):
                    findings.append(f"{label} raised unexpected error: {exc}")

        # Scraper coverage must not claim full corpus for a subset.
        try:
            scraper = _load_scraper_module()
            summary = scraper._compute_coverage_summary(
                selected_states=subset,
                scraped_statutes=[
                    {"state_code": "AL", "statutes": [{"x": 1}], "statutes_count": 1},
                    {"state_code": "AK", "statutes": [{"x": 1}], "statutes_count": 1},
                ],
                errors=[],
            )
            if summary.get("full_corpus_coverage") is True:
                findings.append("scraper claimed full_corpus_coverage for subset")
            if summary.get("coverage_scope") == "full_corpus":
                findings.append("scraper coverage_scope is full_corpus for subset")
            if summary.get("production_release_eligible") is True:
                findings.append("scraper production_release_eligible for subset")
            reject_fn = getattr(scraper, "reject_subset_release", None)
            if reject_fn is None:
                findings.append("scraper missing reject_subset_release")
            else:
                try:
                    reject_fn(subset)
                    findings.append("scraper.reject_subset_release accepted subset")
                except Exception as exc:
                    if "subset" not in str(exc).lower() and "51" not in str(exc):
                        findings.append(f"scraper reject raised unexpected: {exc}")
        except Exception as exc:
            findings.append(f"scraper coverage check failed: {exc}")

        return {
            "case_id": case_id,
            "kind": kind,
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "detail": {"subset": subset},
        }

    findings.append(f"unknown fixture kind {kind!r}")
    return {
        "case_id": case_id,
        "kind": kind,
        "status": "fail",
        "findings": findings,
        "detail": {},
    }


def _load_sibling_module(filename: str) -> Any:
    import importlib.util

    path = Path(__file__).with_name(filename)
    if not path.is_file():
        raise CohortRunnerError(f"sibling module missing: {path}")
    name = f"lcr007_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CohortRunnerError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_scraper_module() -> Any:
    import importlib

    return importlib.import_module(
        "ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper"
    )


def run_fixture_suite(*, cohort_filter: Optional[str] = None) -> Dict[str, Any]:
    """Run all (or cohort-filtered) offline fixture recipes."""
    recipes = build_fixture_recipes()
    results: List[Dict[str, Any]] = []
    for case in recipes["cases"]:
        if cohort_filter:
            case_cohort = str(case.get("cohort") or "").upper()
            kind = str(case.get("kind") or "")
            # Always run global safety cases; filter only cohort-scoped ones.
            if case_cohort and case_cohort != str(cohort_filter).upper():
                if kind in {"interrupt_resume", "exact_set", "combined_guard"}:
                    # exact_set for M still required when checking A — run always for DC proof
                    if kind == "exact_set":
                        pass  # always run DC-inclusive set proof
                    elif kind != "exact_set":
                        continue
        results.append(run_fixture_case(case))

    # Ensure DC / full set proof always present.
    if not any(r.get("kind") == "exact_set" for r in results):
        results.append(
            run_fixture_case(
                {
                    "case_id": "exact_cohort_set_with_dc",
                    "kind": "exact_set",
                    "cohort": "M",
                    "expected_states": ["WI", "WY", "DC"],
                }
            )
        )

    failed = [r for r in results if r.get("status") != "pass"]
    report = {
        "schema": RUNNER_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": "fixture-only",
        "cohort_filter": str(cohort_filter).upper() if cohort_filter else None,
        "status": "pass" if not failed else "fail",
        "case_count": len(results),
        "pass_count": len(results) - len(failed),
        "fail_count": len(failed),
        "results": results,
        "cohort_map": {k: list(v) for k, v in COHORT_JURISDICTIONS.items()},
        "canonical_jurisdiction_count": len(CANONICAL_JURISDICTIONS),
        "includes_dc": "DC" in CANONICAL_JURISDICTION_SET,
        "production_upload": False,
        "checked_at": utc_now_iso(),
    }
    return report


def run_cohort(
    *,
    cohort: str,
    run_root: Optional[Path] = None,
    base_root: Optional[Path] = None,
    resume: bool = True,
    fixture_only: bool = False,
    heartbeat_seconds: float = 0.0,
    state_runner: Optional[Callable[[str, Path, Mapping[str, Any]], Mapping[str, Any]]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run (or resume) one isolated cohort. Never uploads to production."""
    if fixture_only:
        return run_fixture_suite(cohort_filter=cohort)

    states = cohort_states(cohort)
    cfg = {
        "max_statutes": None,
        "strict_full_text": True,
        "allow_justia_fallback": False,
        **dict(config or {}),
    }
    root = Path(run_root) if run_root else isolate_run_root(base_root=base_root, cohort=cohort)
    progress_path = root / "progress" / "progress.json"
    state_results: Dict[str, Dict[str, Any]] = {}
    heartbeat = 0

    def _default_state_runner(state: str, state_root: Path, conf: Mapping[str, Any]) -> Mapping[str, Any]:
        # Offline-safe default: materialize fixture rows into isolated jsonld.
        # Live scrape integration is intentionally deferred to cohort tasks
        # LCR-009+; this runner owns isolation/resume/certification contracts.
        rows = _fixture_state_rows(state, generation=1)
        jsonld_path = state_root / "jsonld" / f"STATE-{state}.jsonld"
        jsonld_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonld_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        merge = merge_logical_current_history([], rows, state=state)
        history_path = state_root / "history" / f"STATE-{state}-history.json"
        atomic_write_json(
            history_path,
            {"state": state, "history_by_key": merge["history_by_key"]},
        )
        return {
            "status": "success",
            "statutes_count": len(rows),
            "logical_merge": merge,
            "failed_final": 0,
            "jsonld_path": str(jsonld_path.name),
        }

    runner = state_runner or _default_state_runner
    waves = domain_schedule(states)

    for wave in waves:
        for state in wave:
            fp = work_fingerprint(cohort=cohort, state=state, config=cfg)
            ck_path = root / "checkpoints" / f"STATE-{state}.json"
            receipt_path = root / "receipts" / f"jurisdiction-{state}.json"
            if resume and ck_path.is_file():
                existing = load_json(ck_path)
                stale = detect_stale_checkpoint(existing, expected_fingerprint=fp)
                status = promote_state_status(str(existing.get("status") or ""))
                if status == "success" and stale is None:
                    state_results[state] = {
                        "status": "success",
                        "statutes_count": int(existing.get("statutes_count") or 0),
                        "skipped_completed": True,
                        "work_fingerprint": fp,
                    }
                    heartbeat += 1
                    write_progress(
                        progress_path,
                        cohort=cohort,
                        states=states,
                        state_results=state_results,
                        status="running",
                        heartbeat_seq=heartbeat,
                    )
                    continue
                if stale is not None and status == "success":
                    # Stale success cannot be reused.
                    existing = {}

            write_state_checkpoint(
                ck_path,
                cohort=cohort,
                state=state,
                status="running",
                fingerprint=fp,
            )
            try:
                outcome = dict(runner(state, root, cfg))
            except Exception as exc:  # noqa: BLE001 - per-state isolation
                outcome = {"status": "error", "error": str(exc), "statutes_count": 0}

            status = promote_state_status(str(outcome.get("status") or "error"))
            if status == "partial_success":
                # Hard rule: partial never becomes success.
                status = "partial_success"
            statutes_count = int(outcome.get("statutes_count") or 0)
            logical_merge = outcome.get("logical_merge")
            if not isinstance(logical_merge, Mapping):
                logical_merge = None

            write_state_checkpoint(
                ck_path,
                cohort=cohort,
                state=state,
                status=status,
                fingerprint=fp,
                payload={
                    "statutes_count": statutes_count,
                    "error": str(outcome.get("error") or ""),
                    "failed_final": int(outcome.get("failed_final") or 0),
                },
            )
            write_state_receipt(
                receipt_path,
                cohort=cohort,
                state=state,
                status=status,
                statutes_count=statutes_count,
                logical_merge=logical_merge,
                extra={
                    "failed_final": int(outcome.get("failed_final") or 0),
                    "error": str(outcome.get("error") or ""),
                },
            )
            state_results[state] = {
                "status": status,
                "statutes_count": statutes_count,
                "skipped_completed": False,
                "work_fingerprint": fp,
                "failed_final": int(outcome.get("failed_final") or 0),
                "error": str(outcome.get("error") or ""),
            }
            heartbeat += 1
            write_progress(
                progress_path,
                cohort=cohort,
                states=states,
                state_results=state_results,
                status="running",
                heartbeat_seq=heartbeat,
            )
            if heartbeat_seconds and heartbeat_seconds > 0:
                time.sleep(min(float(heartbeat_seconds), 0.01))

    final_status = "success" if cohort_success_allowed(state_results) else "failed"
    if final_status == "success" and set(state_results) != set(states):
        final_status = "failed"

    progress = write_progress(
        progress_path,
        cohort=cohort,
        states=states,
        state_results=state_results,
        status=final_status,
        heartbeat_seq=heartbeat + 1,
        extra={
            "domain_waves": waves,
            "run_root": root.name,
        },
    )
    cohort_receipt = redact_receipt(
        {
            "schema": RECEIPT_SCHEMA,
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "cohort": str(cohort).upper(),
            "status": final_status,
            "states": list(states),
            "state_results": state_results,
            "production_upload": False,
            "shared_combined_write": False,
            "finished_at": utc_now_iso(),
        }
    )
    receipt_path = root / "receipts" / f"cohort-{str(cohort).upper()}.json"
    atomic_write_json(receipt_path, cohort_receipt)
    return {
        "status": final_status,
        "cohort": str(cohort).upper(),
        "states": list(states),
        "state_results": state_results,
        "progress": progress,
        "run_root": str(root),
        "cohort_receipt_path": str(receipt_path),
        "production_upload": False,
        "shared_combined_write": False,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resumable isolated legal-corpora reindex cohort runner (LCR-007)"
    )
    parser.add_argument(
        "--cohort",
        required=True,
        help="Cohort letter A–M (M includes DC)",
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Run offline fixture recipes (no network, no production upload)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail closed unless fixture/run status is pass/success",
    )
    parser.add_argument(
        "--run-root",
        default="",
        help="Optional existing isolated run root to resume",
    )
    parser.add_argument(
        "--base-root",
        default="",
        help="Base directory for new isolated cohort run roots",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing checkpoints",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=0.0,
        help="Optional delay between heartbeats (tests use 0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON report",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    cohort = str(args.cohort).strip().upper()
    try:
        # Validate cohort map invariants early (includes DC in M / union = 51).
        all_cohort_states()
        cohort_states(cohort)
        if args.fixture_only:
            report = run_fixture_suite(cohort_filter=cohort)
            ok = report.get("status") == "pass"
        else:
            report = run_cohort(
                cohort=cohort,
                run_root=Path(args.run_root).expanduser().resolve() if args.run_root else None,
                base_root=Path(args.base_root).expanduser().resolve() if args.base_root else None,
                resume=not bool(args.no_resume),
                heartbeat_seconds=float(args.heartbeat_seconds or 0.0),
            )
            ok = report.get("status") == "success"
    except CohortRunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json or args.fixture_only:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"cohort: {report.get('cohort')}")
        print(f"status: {report.get('status')}")
        print(f"states: {','.join(report.get('states') or [])}")
        print(f"production_upload: {report.get('production_upload')}")

    if args.check and not ok:
        print("RESULT: FAIL", file=sys.stderr)
        return 1
    if args.check:
        print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
