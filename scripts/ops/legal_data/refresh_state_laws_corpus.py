#!/usr/bin/env python3
"""Refresh the canonical state-laws corpus and publish merged HF artifacts.

The state-specific scrapers write one JSON-LD file per state. This command
turns those JSON-LD files into canonical CID-keyed parquet shards, optionally
merges already-published Hugging Face rows, and uploads the refreshed shards
back to the canonical JusticeDAO state-laws dataset.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import (
    get_canonical_legal_corpus,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (
    _resolve_hf_token,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    US_STATES,
    _write_state_jsonld_files,
    scrape_state_laws,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_obj
from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes


STATE_CODES_50: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

_CORPUS = get_canonical_legal_corpus("state_laws")
_COMPLETED_STATES_SCHEMA = "ipfs_datasets_py.state_laws_refresh.completed_states.v1"
_REGISTRY_RECORDABLE_STATE_STATUSES = {"success", "zero_statutes"}


def _complete_state_statuses() -> set[str]:
    """Return registry statuses that should skip future scrape retries.

    `zero_statutes` entries are recorded for observability, but by default they
    are *not* treated as complete for retry-skipping because they can indicate
    a transient scraper/source failure. Set
    `STATE_LAWS_REGISTRY_TREAT_ZERO_AS_COMPLETE=1` to restore the legacy
    behavior.
    """

    statuses = {"success"}
    if str(os.getenv("STATE_LAWS_REGISTRY_TREAT_ZERO_AS_COMPLETE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        statuses.add("zero_statutes")
    return statuses


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_completed_states_registry_path() -> Path:
    env_override = str(os.getenv("STATE_LAWS_COMPLETED_STATES_REGISTRY_PATH", "") or "").strip()
    if env_override:
        return Path(env_override).expanduser().resolve()
    canonical_root = Path(_CORPUS.default_local_root()).expanduser().resolve()
    return canonical_root / "state_laws_completed_states.json"


def _uses_shared_completed_registry(output_root: Path) -> bool:
    try:
        resolved_output = Path(output_root).expanduser().resolve()
    except Exception:
        return False
    canonical_root = Path(_CORPUS.default_local_root()).expanduser().resolve()
    if resolved_output == canonical_root:
        return True
    parts = {part.lower() for part in resolved_output.parts}
    if "legal_scraper_parallel" in parts and resolved_output.name.lower() == "output":
        return True
    return False


def _default_completed_states_registry_path(output_root: Path) -> Path:
    # Use a shared registry for canonical corpus output roots and daemon shard
    # outputs, but keep ad-hoc/custom output roots isolated.
    if _uses_shared_completed_registry(output_root):
        return _canonical_completed_states_registry_path()
    return Path(output_root).expanduser().resolve() / "state_laws_completed_states.json"


def _default_completed_states_baseline_path() -> Path:
    env_override = str(os.getenv("STATE_LAWS_COMPLETED_STATES_BASELINE_PATH", "") or "").strip()
    if env_override:
        return Path(env_override).expanduser().resolve()
    return Path(__file__).resolve().with_name("state_laws_completed_states.baseline.json")


def _empty_completed_states_registry() -> Dict[str, Any]:
    return {
        "schema": _COMPLETED_STATES_SCHEMA,
        "updated_at": "",
        "states": {},
    }


def _normalize_completed_states_registry(payload: Any) -> Dict[str, Any]:
    normalized = _empty_completed_states_registry()
    if not isinstance(payload, Mapping):
        return normalized

    allowed_states = set(US_STATES)
    raw_states = payload.get("states")
    if not isinstance(raw_states, Mapping):
        raw_states = {}

    normalized_states: Dict[str, Dict[str, Any]] = {}
    for raw_code, raw_entry in raw_states.items():
        state_code = str(raw_code or "").strip().upper()
        if not state_code or state_code not in allowed_states:
            continue
        if not isinstance(raw_entry, Mapping):
            continue
        status = str(raw_entry.get("status") or "").strip().lower()
        if status not in _REGISTRY_RECORDABLE_STATE_STATUSES:
            continue
        entry: Dict[str, Any] = {"status": status}
        completed_at = str(raw_entry.get("completed_at") or "").strip()
        if completed_at:
            entry["completed_at"] = completed_at
        first_completed_at = str(raw_entry.get("first_completed_at") or "").strip()
        if first_completed_at:
            entry["first_completed_at"] = first_completed_at
        updated_at = str(raw_entry.get("updated_at") or "").strip()
        if updated_at:
            entry["updated_at"] = updated_at
        try:
            statutes_count = int(raw_entry.get("statutes_count") or 0)
        except Exception:
            statutes_count = 0
        entry["statutes_count"] = statutes_count
        for key in ("output_root", "source_progress_path"):
            value = str(raw_entry.get(key) or "").strip()
            if value:
                entry[key] = value
        for key in ("completion_mode", "timeout_classification", "timeout_signal_kind", "timeout_original_error"):
            value = str(raw_entry.get(key) or "").strip()
            if value:
                entry[key] = value
        timeout_work_remaining = raw_entry.get("timeout_work_remaining")
        if isinstance(timeout_work_remaining, bool):
            entry["timeout_work_remaining"] = timeout_work_remaining
        timeout_promoted = raw_entry.get("timeout_promoted_to_success")
        if isinstance(timeout_promoted, bool):
            entry["timeout_promoted_to_success"] = timeout_promoted
        normalized_states[state_code] = entry

    normalized["states"] = dict(sorted(normalized_states.items()))
    normalized["updated_at"] = str(payload.get("updated_at") or "").strip()
    return normalized


def _load_completed_states_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_completed_states_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_completed_states_registry()
    return _normalize_completed_states_registry(payload)


def _write_completed_states_registry(path: Path, registry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_completed_states_registry(registry)
    normalized["updated_at"] = _utc_now_iso()
    path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _merge_completed_states_registries(
    *,
    base_registry: Mapping[str, Any],
    overlay_registry: Mapping[str, Any],
) -> Dict[str, Any]:
    base = _normalize_completed_states_registry(base_registry)
    overlay = _normalize_completed_states_registry(overlay_registry)
    merged = _empty_completed_states_registry()

    base_states = base.get("states") if isinstance(base.get("states"), Mapping) else {}
    overlay_states = overlay.get("states") if isinstance(overlay.get("states"), Mapping) else {}
    states_map: Dict[str, Dict[str, Any]] = {}
    for state_code, entry in base_states.items():
        if isinstance(entry, Mapping):
            states_map[str(state_code)] = dict(entry)
    for state_code, entry in overlay_states.items():
        if isinstance(entry, Mapping):
            states_map[str(state_code)] = dict(entry)

    merged["states"] = dict(sorted(states_map.items()))
    merged["updated_at"] = str(overlay.get("updated_at") or base.get("updated_at") or "").strip()
    return merged


def _completed_states_to_skip(states: Sequence[str], registry: Mapping[str, Any]) -> List[str]:
    complete_statuses = _complete_state_statuses()
    entries = registry.get("states")
    if not isinstance(entries, Mapping):
        return []
    skipped: List[str] = []
    for state in states:
        entry = entries.get(state)
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status in complete_statuses:
            skipped.append(state)
    return skipped


def _completed_states_missing_canonical_jsonld(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
) -> List[str]:
    missing: List[str] = []
    for state in states:
        state_code = str(state or "").strip().upper()
        if not state_code:
            continue
        state_jsonld = Path(jsonld_dir).expanduser().resolve() / f"STATE-{state_code}.jsonld"
        if not state_jsonld.exists():
            missing.append(state_code)
    return missing


def _prefill_state_results_from_registry(
    *,
    states: Sequence[str],
    registry: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    complete_statuses = _complete_state_statuses()
    entries = registry.get("states")
    if not isinstance(entries, Mapping):
        return {}
    prefilled: Dict[str, Dict[str, Any]] = {}
    for state in states:
        entry = entries.get(state)
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status not in complete_statuses:
            continue
        try:
            statutes_count = int(entry.get("statutes_count") or 0)
        except Exception:
            statutes_count = 0
        prefilled[state] = {
            "state_code": state,
            "status": status,
            "statutes_count": statutes_count,
            "completed_at": str(entry.get("completed_at") or ""),
            "skip_reason": "already_completed_registry",
        }
        for key in ("completion_mode", "timeout_classification", "timeout_signal_kind", "timeout_original_error"):
            value = str(entry.get(key) or "").strip()
            if value:
                prefilled[state][key] = value
        if isinstance(entry.get("timeout_work_remaining"), bool):
            prefilled[state]["timeout_work_remaining"] = bool(entry.get("timeout_work_remaining"))
        if isinstance(entry.get("timeout_promoted_to_success"), bool):
            prefilled[state]["timeout_promoted_to_success"] = bool(entry.get("timeout_promoted_to_success"))
    return prefilled


def _merge_completed_states_registry(
    *,
    existing_registry: Mapping[str, Any],
    state_results: Mapping[str, Any],
    output_root: Path,
    progress_path: Path,
) -> Dict[str, Any]:
    merged = _normalize_completed_states_registry(existing_registry)
    states_map = dict(merged.get("states") or {})
    now = _utc_now_iso()
    for state_code, raw_entry in state_results.items():
        code = str(state_code or "").strip().upper()
        if code not in US_STATES or not isinstance(raw_entry, Mapping):
            continue
        status = str(raw_entry.get("status") or "").strip().lower()
        if status not in _REGISTRY_RECORDABLE_STATE_STATUSES:
            continue
        prior = states_map.get(code) if isinstance(states_map.get(code), Mapping) else {}
        try:
            statutes_count = int(raw_entry.get("statutes_count") or 0)
        except Exception:
            statutes_count = 0
        completed_at = str(raw_entry.get("completed_at") or "").strip() or now
        entry: Dict[str, Any] = {
            "status": status,
            "statutes_count": statutes_count,
            "completed_at": completed_at,
            "first_completed_at": str(prior.get("first_completed_at") or completed_at),
            "updated_at": now,
            "output_root": str(output_root),
            "source_progress_path": str(progress_path),
        }
        for key in ("completion_mode", "timeout_classification", "timeout_signal_kind", "timeout_original_error"):
            value = str(raw_entry.get(key) or "").strip()
            if value:
                entry[key] = value
        timeout_work_remaining = raw_entry.get("timeout_work_remaining")
        if isinstance(timeout_work_remaining, bool):
            entry["timeout_work_remaining"] = timeout_work_remaining
        timeout_promoted = raw_entry.get("timeout_promoted_to_success")
        if isinstance(timeout_promoted, bool):
            entry["timeout_promoted_to_success"] = timeout_promoted
        states_map[code] = entry
    merged["states"] = dict(sorted(states_map.items()))
    merged["updated_at"] = now
    return merged


def _reconcile_state_results_from_partial_checkpoints(
    *,
    progress_state: Dict[str, Any],
    checkpoint_dir: Path,
) -> Dict[str, Any]:
    """Promote terminal checkpoint-complete states that timed out in callback flow.

    Some long-running state scrapes can exceed the callback timeout envelope yet
    finish shortly after in their worker thread, leaving a final
    `STATE-XX-partial.json` with stage `...complete` and larger statute counts.
    This reconciliation pass converts those stale timeout/error rows into
    success so completed states are not retried forever.
    """

    results = progress_state.get("state_results")
    if not isinstance(results, dict):
        results = {}
        progress_state["state_results"] = results

    reconciled_states: List[Dict[str, Any]] = []
    checked_state_count = 0
    checkpoint_root = Path(checkpoint_dir).expanduser().resolve()
    checkpoint_states: set[str] = set()
    try:
        for checkpoint_path in checkpoint_root.glob("STATE-*-partial.json"):
            stem = str(checkpoint_path.stem or "")
            if not stem.startswith("STATE-") or not stem.endswith("-partial"):
                continue
            state_code = stem[len("STATE-") : -len("-partial")].strip().upper()
            if state_code:
                checkpoint_states.add(state_code)
    except Exception:
        checkpoint_states = set()

    candidate_states: List[str] = []
    seen_states: set[str] = set()
    for state_code in list(results.keys()) + sorted(checkpoint_states):
        state = str(state_code or "").strip().upper()
        if not state or state in seen_states:
            continue
        seen_states.add(state)
        candidate_states.append(state)

    for state_code in candidate_states:
        entry = results.get(state_code)
        if entry is None:
            entry = {
                "state_code": state_code,
                "state_name": US_STATES.get(state_code, state_code),
                "status": "missing",
                "statutes_count": 0,
            }
            results[state_code] = entry
        if not isinstance(entry, dict):
            continue
        checked_state_count += 1
        status = str(entry.get("status") or "").strip().lower()
        if status not in {"error", "zero_statutes", "running", "started", "missing", ""}:
            continue

        checkpoint_path = checkpoint_root / f"STATE-{str(state_code or '').upper()}-partial.json"
        if not checkpoint_path.exists():
            continue
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, Mapping):
            continue

        stage_label = str(payload.get("stage_label") or "").strip()
        stage_label_lower = stage_label.lower()
        progress = payload.get("progress") if isinstance(payload.get("progress"), Mapping) else {}
        try:
            checkpoint_statutes_count = int(payload.get("statutes_count") or len(list(payload.get("statutes") or [])))
        except Exception:
            checkpoint_statutes_count = 0
        try:
            prior_count = int(entry.get("statutes_count") or 0)
        except Exception:
            prior_count = 0

        try:
            codes_completed = int(progress.get("codes_completed") or payload.get("codes_completed") or 0)
        except Exception:
            codes_completed = 0
        try:
            codes_total = int(progress.get("codes_total") or payload.get("codes_total") or 0)
        except Exception:
            codes_total = 0

        checkpoint_complete = bool(
            checkpoint_statutes_count > 0
            and (
                stage_label_lower == "complete"
                or stage_label_lower.endswith(":complete")
                or stage_label_lower.startswith("scrape_all:complete")
                or (codes_total > 0 and codes_completed >= codes_total)
            )
        )
        if not checkpoint_complete:
            continue
        if checkpoint_statutes_count < prior_count:
            continue

        entry["status"] = "success"
        entry["statutes_count"] = int(checkpoint_statutes_count)
        entry["completion_mode"] = "checkpoint_reconciled_complete"
        entry["checkpoint_reconciled"] = True
        entry["checkpoint_path"] = str(checkpoint_path)
        entry["checkpoint_stage_label"] = stage_label
        if str(payload.get("updated_at") or "").strip():
            entry["checkpoint_updated_at"] = str(payload.get("updated_at") or "").strip()
        if "error" in entry:
            entry["timeout_original_error"] = str(entry.get("error") or "")
            entry.pop("error", None)
        reconciled_states.append(
            {
                "state": str(state_code).upper(),
                "prior_status": status,
                "prior_statutes_count": prior_count,
                "checkpoint_statutes_count": checkpoint_statutes_count,
                "checkpoint_stage_label": stage_label,
            }
        )

    return {
        "reconciled_states": reconciled_states,
        "checked_state_count": checked_state_count,
        "reconciled_count": len(reconciled_states),
    }


def _eligible_timeout_recovery_states(
    *,
    states: Sequence[str],
    progress_state: Mapping[str, Any],
) -> List[str]:
    """Return timeout error states that should be retried with larger budgets."""

    state_results = progress_state.get("state_results")
    if not isinstance(state_results, Mapping):
        return []

    candidates: List[str] = []
    for state_code in states:
        entry = state_results.get(state_code)
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status != "error":
            continue

        timeout_classification = str(entry.get("timeout_classification") or "").strip().lower()
        if not timeout_classification and isinstance(entry.get("timeout_diagnostics"), Mapping):
            timeout_classification = str(
                (entry.get("timeout_diagnostics") or {}).get("classification") or ""
            ).strip().lower()
        if not timeout_classification.startswith("timeout_"):
            continue

        timeout_work_remaining = entry.get("timeout_work_remaining")
        if not isinstance(timeout_work_remaining, bool) and isinstance(entry.get("timeout_diagnostics"), Mapping):
            timeout_work_remaining = (entry.get("timeout_diagnostics") or {}).get("work_remaining")
        if timeout_work_remaining is False:
            # Already classified as timeout with no remaining work.
            continue

        candidates.append(str(state_code).upper())

    deduped: List[str] = []
    seen = set()
    for state_code in candidates:
        if state_code in seen:
            continue
        deduped.append(state_code)
        seen.add(state_code)
    return deduped


def _normalize_states(value: str, *, include_dc: bool = False) -> List[str]:
    raw = str(value or "all").strip()
    if not raw or raw.lower() == "all":
        states = list(STATE_CODES_50)
        if include_dc:
            states.append("DC")
        return states

    states: List[str] = []
    for item in raw.split(","):
        code = item.strip().upper()
        if not code:
            continue
        if code not in US_STATES:
            raise ValueError(f"Unknown state code: {code}")
        if code == "DC" and not include_dc:
            raise ValueError("DC requested but --include-dc was not set")
        states.append(code)

    deduped: List[str] = []
    seen = set()
    for state in states:
        if state not in seen:
            deduped.append(state)
            seen.add(state)
    return deduped


def _coerce_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _first_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_cid_for_obj(payload: Mapping[str, Any]) -> str:
    try:
        return cid_for_obj(dict(payload))
    except Exception:
        digest = hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()
        return f"sha256:{digest}"


def jsonld_payload_to_canonical_row(payload: Mapping[str, Any], *, state_code: str) -> Dict[str, Any]:
    """Convert one state-law JSON-LD object into the canonical parquet schema."""
    state = str(state_code or payload.get("stateCode") or payload.get("state_code") or "").strip().upper()
    identifier = _first_text(
        payload,
        ("identifier", "legislationIdentifier", "sectionNumber", "source_id", "@id"),
    )
    name = _first_text(payload, ("name", "sectionName", "title", "description"))
    text = _first_text(payload, ("text", "articleBody", "description"))
    source_url = _first_text(payload, ("sourceUrl", "url", "sameAs"))
    source_id = _first_text(payload, ("@id", "source_id")) or identifier or source_url

    row_without_cid = {
        "state_code": state,
        "source_id": source_id,
        "identifier": identifier,
        "name": name,
        "text": text,
        "source_url": source_url,
        "jsonld": json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
        "legislation_type": _first_text(payload, ("legislationType", "@type")),
        "legislation_jurisdiction": _first_text(payload, ("legislationJurisdiction",)),
    }
    return {
        "ipfs_cid": _safe_cid_for_obj(row_without_cid),
        **row_without_cid,
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    for field in ("ipfs_cid", "source_id", "identifier", "source_url"):
        value = str(row.get(field) or "").strip()
        if value:
            return (field, value)
    return ("row", json.dumps(dict(row), ensure_ascii=True, sort_keys=True, default=str))


def merge_canonical_rows(existing_rows: Sequence[Mapping[str, Any]], new_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Merge rows by stable identity, preferring the refreshed scraped row."""
    merged: Dict[tuple[str, ...], Dict[str, Any]] = {}
    order: List[tuple[str, ...]] = []
    for row in list(existing_rows) + list(new_rows):
        normalized = dict(row)
        key = _row_key(normalized)
        if key not in merged:
            order.append(key)
        merged[key] = normalized
    return [merged[key] for key in order]


def _normalize_rows_for_parquet(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return [{"_empty": True}]
    fields: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return [{field: row.get(field) for field in fields} for row in rows]


def _read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    import pyarrow.parquet as pq

    return [dict(row) for row in pq.read_table(path).to_pylist()]


def _write_parquet_rows(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(rows)), path, compression="snappy")


def _iter_jsonld_payloads(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def _download_existing_hf_state_parquet(
    *,
    repo_id: str,
    state_code: str,
    token: Optional[str],
    cache_dir: Path,
    repo_files: Optional[set[str]] = None,
) -> Path | None:
    remote_path = f"{_CORPUS.parquet_dir_name}/{_CORPUS.state_parquet_filename(state_code)}"
    if repo_files is not None and remote_path not in repo_files:
        return None
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return None
    try:
        downloaded = hf_hub_download(
            repo_id=repo_id,
            repo_type="dataset",
            filename=remote_path,
            token=token,
            cache_dir=str(cache_dir),
        )
    except Exception:
        return None
    return Path(downloaded)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hf_state_repo_path(state_code: str) -> str:
    return f"{_CORPUS.parquet_dir_name}/{_CORPUS.state_parquet_filename(state_code)}"


def _publish_state_parquet_file(
    *,
    state_code: str,
    state_parquet_path: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    commit_message: str,
) -> Dict[str, Any]:
    from huggingface_hub import HfApi

    if not state_parquet_path.exists():
        return {
            "status": "skipped",
            "state": state_code,
            "reason": "missing_local_state_parquet",
            "local_path": str(state_parquet_path),
        }

    api = HfApi(token=token)
    if create_repo:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

    repo_path = _hf_state_repo_path(state_code)
    try:
        upload_info = api.upload_file(
            path_or_fileobj=str(state_parquet_path),
            path_in_repo=repo_path,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=commit_message,
        )
    except Exception as exc:
        msg = str(exc)
        if "no files have been modified" in msg.lower() or "nothing to commit" in msg.lower() or "empty commit" in msg.lower():
            upload_info = "no_change_already_current"
        else:
            raise

    return {
        "status": "success",
        "state": state_code,
        "repo_id": repo_id,
        "repo_path": repo_path,
        "local_path": str(state_parquet_path),
        "local_sha256": _file_sha256(state_parquet_path),
        "upload_commit": str(upload_info),
    }


def _sync_stale_local_state_shards_to_hf(
    *,
    states: Sequence[str],
    parquet_dir: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    commit_message: str,
) -> Dict[str, Any]:
    """Upload local state shards whose bytes differ from the HF shard.

    This is intentionally content-hash based instead of relying on mtimes:
    Hugging Face download caches and git metadata do not provide a simple,
    stable remote mtime for every shard, while hash mismatch tells us the
    remote is stale relative to local content.
    """
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        return {"status": "error", "error": str(exc), "states": list(states), "uploaded": []}

    api = HfApi(token=token)
    if create_repo:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

    try:
        repo_files = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset"))
    except Exception:
        repo_files = set()

    uploaded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    hf_cache_dir = Path.home() / ".cache" / "state_laws_hf_merge"
    for state in states:
        local_path = parquet_dir / _CORPUS.state_parquet_filename(state)
        if not local_path.exists():
            skipped.append({"state": state, "reason": "missing_local_state_parquet"})
            continue

        local_hash = _file_sha256(local_path)
        repo_path = _hf_state_repo_path(state)
        remote_hash = ""
        remote_path = _download_existing_hf_state_parquet(
            repo_id=repo_id,
            state_code=state,
            token=token,
            cache_dir=hf_cache_dir,
            repo_files=repo_files,
        )
        if remote_path is not None and remote_path.exists():
            try:
                remote_hash = _file_sha256(remote_path)
            except Exception:
                remote_hash = ""

        if repo_path in repo_files and remote_hash == local_hash:
            skipped.append({"state": state, "reason": "remote_already_current", "sha256": local_hash})
            continue

        uploaded.append(
            _publish_state_parquet_file(
                state_code=state,
                state_parquet_path=local_path,
                repo_id=repo_id,
                token=token,
                create_repo=False,
                commit_message=f"{commit_message} ({state} stale shard sync)",
            )
        )

    return {
        "status": "success",
        "states": list(states),
        "uploaded": uploaded,
        "uploaded_count": len(uploaded),
        "skipped": skipped,
        "skipped_count": len(skipped),
    }


def _build_and_sync_stale_local_state_shards_to_hf(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
    parquet_dir: Path,
    merge_existing_local: bool,
    merge_hf_existing: bool,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    commit_message: str,
) -> Dict[str, Any]:
    uploaded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for index, state in enumerate(states, start=1):
        print(
            f"[state_laws_refresh] startup_stale_sync state={state} index={index}/{len(states)}",
            flush=True,
        )
        try:
            state_jsonld_path = jsonld_dir / f"STATE-{state}.jsonld"
            state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state)
            if state_jsonld_path.exists():
                build_state_laws_parquet_artifacts(
                    states=[state],
                    jsonld_dir=jsonld_dir,
                    parquet_dir=parquet_dir,
                    merge_existing_local=merge_existing_local,
                    merge_hf_existing=merge_hf_existing,
                    repo_id=repo_id,
                    token=token,
                )
            if not state_parquet_path.exists():
                skipped.append({"state": state, "reason": "no_local_jsonld_or_parquet"})
                continue

            sync = _sync_stale_local_state_shards_to_hf(
                states=[state],
                parquet_dir=parquet_dir,
                repo_id=repo_id,
                token=token,
                create_repo=create_repo and index == 1,
                commit_message=commit_message,
            )
            uploaded.extend(sync.get("uploaded") or [])
            skipped.extend(sync.get("skipped") or [])
        except Exception as exc:
            errors.append({"state": state, "error": str(exc)})

    return {
        "status": "success" if not errors else "partial_success",
        "states": list(states),
        "uploaded": uploaded,
        "uploaded_count": len(uploaded),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "errors": errors,
        "error_count": len(errors),
    }


def build_state_laws_parquet_artifacts(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
    parquet_dir: Path,
    merge_existing_local: bool = True,
    merge_hf_existing: bool = False,
    repo_id: str = _CORPUS.hf_dataset_id,
    token: Optional[str] = None,
    hf_cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build per-state and combined parquet files from state-law JSON-LD."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    hf_cache_dir = hf_cache_dir or (Path.home() / ".cache" / "state_laws_hf_merge")
    repo_files: Optional[set[str]] = None

    if merge_hf_existing:
        try:
            from huggingface_hub import HfApi

            repo_files = set(HfApi(token=token).list_repo_files(repo_id=repo_id, repo_type="dataset"))
        except Exception:
            repo_files = set()

    state_reports: List[Dict[str, Any]] = []
    combined_rows: List[Dict[str, Any]] = []
    missing_jsonld: List[str] = []

    for state in states:
        state_jsonld_path = jsonld_dir / f"STATE-{state}.jsonld"
        if not state_jsonld_path.exists():
            missing_jsonld.append(state)
            new_rows: List[Dict[str, Any]] = []
        else:
            new_rows = [
                jsonld_payload_to_canonical_row(payload, state_code=state)
                for payload in _iter_jsonld_payloads(state_jsonld_path)
            ]

        state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state)
        existing_rows: List[Dict[str, Any]] = []
        if merge_hf_existing:
            remote_path = _download_existing_hf_state_parquet(
                repo_id=repo_id,
                state_code=state,
                token=token,
                cache_dir=hf_cache_dir,
                repo_files=repo_files,
            )
            if remote_path is not None:
                existing_rows.extend(_read_parquet_rows(remote_path))
        if merge_existing_local:
            existing_rows.extend(_read_parquet_rows(state_parquet_path))

        merged_rows = merge_canonical_rows(existing_rows, new_rows)
        if merged_rows:
            _write_parquet_rows(merged_rows, state_parquet_path)
        combined_rows.extend(merged_rows)
        state_reports.append(
            {
                "state": state,
                "jsonld_path": str(state_jsonld_path),
                "parquet_path": str(state_parquet_path),
                "scraped_row_count": len(new_rows),
                "existing_row_count": len(existing_rows),
                "merged_row_count": len(merged_rows),
                "jsonld_exists": state_jsonld_path.exists(),
            }
        )

    combined_rows = merge_canonical_rows([], combined_rows)
    combined_path = parquet_dir / _CORPUS.combined_parquet_filename
    if combined_rows:
        _write_parquet_rows(combined_rows, combined_path)

    manifest = {
        "status": "success",
        "corpus_key": _CORPUS.key,
        "repo_id": repo_id,
        "states": list(states),
        "state_count": len(states),
        "missing_jsonld_states": missing_jsonld,
        "parquet_dir": str(parquet_dir),
        "combined_parquet_path": str(combined_path),
        "combined_row_count": len(combined_rows),
        "merge_existing_local": bool(merge_existing_local),
        "merge_hf_existing": bool(merge_hf_existing),
        "state_reports": state_reports,
    }
    manifest_path = parquet_dir / "state_laws_refresh_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _publish_parquet_dir(
    *,
    parquet_dir: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    verify: bool,
    commit_message: str,
) -> Dict[str, Any]:
    from scripts.repair.publish_parquet_to_hf import publish

    return publish(
        local_dir=parquet_dir,
        repo_id=repo_id,
        commit_message=commit_message,
        create_repo=create_repo,
        token=token,
        path_in_repo=_CORPUS.parquet_dir_name,
        allow_patterns=["*.parquet", "*.json", "*.md"],
        do_verify=verify,
        cid_column=_CORPUS.cid_field,
    )


def _run_full_corpus_guard_audit(*, states: Sequence[str]) -> Dict[str, Any]:
    """Run the static full-corpus truncation audit before uncapped scrapes."""
    script_path = Path(__file__).with_name("audit_state_scraper_full_corpus_guards.py")
    spec = importlib.util.spec_from_file_location("audit_state_scraper_full_corpus_guards", script_path)
    if spec is None or spec.loader is None:
        return {
            "status": "fail",
            "states_checked": 0,
            "missing_states": list(states),
            "error_count": 1,
            "warning_count": 0,
            "findings": [{"severity": "error", "detail": f"unable_to_load_audit:{script_path}"}],
        }

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    repo_root = Path(__file__).resolve().parents[3]
    scraper_root = repo_root / "ipfs_datasets_py" / "processors" / "legal_scrapers" / "state_scrapers"
    findings: List[Any] = []
    missing: List[str] = []
    for state in states:
        state_code = str(state).upper()
        module_name = module.STATE_MODULES.get(state_code)
        if not module_name:
            missing.append(state_code)
            continue
        path = scraper_root / f"{module_name}.py"
        if not path.exists():
            missing.append(state_code)
            continue
        findings.extend(module.audit_file(state=state_code, path=path, repo_root=repo_root))

    error_count = sum(1 for item in findings if str(getattr(item, "severity", "")) == "error")
    warning_count = sum(1 for item in findings if str(getattr(item, "severity", "")) == "warning")
    return {
        "status": "fail" if error_count or warning_count or missing else "pass",
        "states_checked": len(states) - len(missing),
        "missing_states": missing,
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in findings],
    }


async def refresh_state_laws_corpus(args: argparse.Namespace) -> Dict[str, Any]:
    requested_states = _normalize_states(args.states, include_dc=bool(args.include_dc))
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else _CORPUS.default_local_root()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve() if args.jsonld_dir else _CORPUS.jsonld_dir(str(output_root))
    parquet_dir = Path(args.parquet_dir).expanduser().resolve() if args.parquet_dir else _CORPUS.parquet_dir(str(output_root))
    repo_id = str(args.repo_id or _CORPUS.hf_dataset_id).strip()
    completed_registry_raw = str(getattr(args, "completed_states_registry", "") or "").strip()
    completed_states_registry_path = (
        Path(completed_registry_raw).expanduser().resolve()
        if completed_registry_raw
        else _default_completed_states_registry_path(output_root)
    )
    completed_baseline_raw = str(getattr(args, "completed_states_baseline", "") or "").strip()
    completed_states_baseline_path = (
        Path(completed_baseline_raw).expanduser().resolve()
        if completed_baseline_raw
        else _default_completed_states_baseline_path()
    )
    skip_completed_states = bool(getattr(args, "skip_completed_states", True))
    persist_completed_states_registry = bool(getattr(args, "persist_completed_states_registry", True))
    if hasattr(args, "load_completed_states_baseline"):
        load_completed_states_baseline = bool(getattr(args, "load_completed_states_baseline", True))
    elif completed_baseline_raw:
        load_completed_states_baseline = True
    else:
        load_completed_states_baseline = _uses_shared_completed_registry(output_root)
    completed_states_registry = _load_completed_states_registry(completed_states_registry_path)
    baseline_registry = (
        _load_completed_states_registry(completed_states_baseline_path)
        if load_completed_states_baseline and completed_states_baseline_path.exists()
        else _empty_completed_states_registry()
    )
    completed_states_registry = _merge_completed_states_registries(
        base_registry=baseline_registry,
        overlay_registry=completed_states_registry,
    )
    skipped_completed_states = (
        _completed_states_to_skip(requested_states, completed_states_registry)
        if skip_completed_states
        else []
    )
    reopened_missing_canonical_states = _completed_states_missing_canonical_jsonld(
        states=skipped_completed_states,
        jsonld_dir=jsonld_dir,
    )
    if reopened_missing_canonical_states:
        reopened_set = set(reopened_missing_canonical_states)
        skipped_completed_states = [
            state for state in skipped_completed_states if state not in reopened_set
        ]
    states = [state for state in requested_states if state not in set(skipped_completed_states)]
    needs_hf_token = bool(args.merge_hf_existing or args.publish_to_hf or args.verify)
    hf_token = (
        _resolve_hf_token(str(args.hf_token or "").strip() or None)
        if needs_hf_token
        else (str(args.hf_token or "").strip() or None)
    )

    plan = {
        "requested_states": requested_states,
        "requested_state_count": len(requested_states),
        "states": states,
        "state_count": len(states),
        "skipped_completed_states": skipped_completed_states,
        "skipped_completed_count": len(skipped_completed_states),
        "reopened_missing_canonical_states": reopened_missing_canonical_states,
        "reopened_missing_canonical_count": len(reopened_missing_canonical_states),
        "skip_completed_states": skip_completed_states,
        "completed_states_registry_path": str(completed_states_registry_path),
        "completed_states_baseline_path": str(completed_states_baseline_path),
        "load_completed_states_baseline": load_completed_states_baseline,
        "persist_completed_states_registry": persist_completed_states_registry,
        "scrape": bool(args.scrape),
        "jsonld_dir": str(jsonld_dir),
        "parquet_dir": str(parquet_dir),
        "repo_id": repo_id,
        "publish_to_hf": bool(args.publish_to_hf),
        "merge_hf_existing": bool(args.merge_hf_existing),
    }
    if args.dry_run:
        return {"status": "dry_run", "plan": plan}

    startup_sync_result: Dict[str, Any] | None = None
    publish_to_hf = bool(args.publish_to_hf)
    startup_stale_sync = bool(getattr(args, "startup_stale_sync", bool(args.scrape)))
    incremental_state_publish = bool(getattr(args, "incremental_state_publish", bool(args.scrape)))

    progress_path = output_root / "state_refresh_progress.json"
    prefilled_state_results = _prefill_state_results_from_registry(
        states=skipped_completed_states,
        registry=completed_states_registry,
    )
    progress_state: Dict[str, Any] = {
        "schema": "ipfs_datasets_py.state_laws_refresh.progress.v1",
        "status": "running",
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "states": requested_states,
        "active_states": states,
        "states_total": len(requested_states),
        "active_states_total": len(states),
        "skipped_completed_states": skipped_completed_states,
        "state_results": prefilled_state_results,
        "states_completed": [],
        "completed_count": 0,
        "success_count": 0,
        "error_count": 0,
        "zero_statute_count": 0,
    }

    def _recompute_progress_counts() -> None:
        results = progress_state.get("state_results") if isinstance(progress_state.get("state_results"), dict) else {}
        completed_states = [state for state in requested_states if state in results]
        success_count = 0
        error_count = 0
        zero_statute_count = 0
        for state in completed_states:
            entry = results.get(state) if isinstance(results.get(state), dict) else {}
            status = str(entry.get("status") or "").strip().lower()
            if status == "success":
                success_count += 1
            elif status == "error":
                error_count += 1
            elif status == "zero_statutes":
                zero_statute_count += 1
        progress_state["states_completed"] = completed_states
        progress_state["completed_count"] = len(completed_states)
        progress_state["success_count"] = success_count
        progress_state["error_count"] = error_count
        progress_state["zero_statute_count"] = zero_statute_count
        progress_state["updated_at"] = _utc_now_iso()

    def _write_progress_state() -> None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps(progress_state, indent=2, sort_keys=True, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _write_completed_states_registry_snapshot() -> None:
        nonlocal completed_states_registry
        if not persist_completed_states_registry:
            return
        state_results = progress_state.get("state_results")
        if not isinstance(state_results, Mapping):
            return
        completed_states_registry = _merge_completed_states_registry(
            existing_registry=completed_states_registry,
            state_results=state_results,
            output_root=output_root,
            progress_path=progress_path,
        )
        _write_completed_states_registry(completed_states_registry_path, completed_states_registry)

    _recompute_progress_counts()
    _write_progress_state()
    _write_completed_states_registry_snapshot()

    if publish_to_hf and startup_stale_sync:
        # Reconcile stale HF state shards before the long scrape starts, but do
        # it one state at a time so a large local corpus does not have to be
        # loaded into a combined in-memory table.
        startup_sync_result = _build_and_sync_stale_local_state_shards_to_hf(
            states=requested_states,
            jsonld_dir=jsonld_dir,
            parquet_dir=parquet_dir,
            merge_existing_local=not bool(args.no_merge_existing_local),
            merge_hf_existing=bool(args.merge_hf_existing),
            repo_id=repo_id,
            token=hf_token,
            create_repo=bool(args.create_repo),
            commit_message=str(args.commit_message or "Refresh canonical state laws corpus"),
        )

    incremental_publish_results: List[Dict[str, Any]] = []
    incremental_publish_lock = asyncio.Lock()
    progress_heartbeat_seconds = max(10.0, float(getattr(args, "progress_heartbeat_seconds", 60.0)))
    try:
        _run_max_statutes_cap = int(getattr(args, "max_statutes", 0) or 0)
    except Exception:
        _run_max_statutes_cap = 0
    bounded_probe_run = _run_max_statutes_cap > 0

    async def _progress_heartbeat_loop(stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=progress_heartbeat_seconds)
                break
            except asyncio.TimeoutError:
                pass
            except Exception:
                break
            progress_state["status"] = "running"
            _recompute_progress_counts()
            _write_progress_state()

    async def _on_state_complete(state_result: Dict[str, Any]) -> None:
        async with incremental_publish_lock:
            state_code = str((state_result or {}).get("state_code") or "").strip().upper()
            statute_data = (state_result or {}).get("statute_data") or {}
            if state_code:
                statutes_count = int((state_result or {}).get("statutes_count") or 0)
                if statutes_count <= 0 and isinstance(statute_data, dict):
                    statutes_count = len(list(statute_data.get("statutes") or []))
                error_text = str((state_result or {}).get("error") or "").strip()
                timeout_diagnostics_raw = (state_result or {}).get("timeout_diagnostics")
                timeout_diagnostics = (
                    dict(timeout_diagnostics_raw)
                    if isinstance(timeout_diagnostics_raw, Mapping)
                    else {}
                )
                timeout_classification = str(timeout_diagnostics.get("classification") or "").strip()
                timeout_signal_kind = str(timeout_diagnostics.get("signal_kind") or "").strip()
                timeout_work_remaining_value = timeout_diagnostics.get("work_remaining")
                timeout_work_remaining = (
                    timeout_work_remaining_value
                    if isinstance(timeout_work_remaining_value, bool)
                    else None
                )
                low_quality = bool((state_result or {}).get("low_quality"))
                timed_out = bool(timeout_diagnostics.get("timed_out")) or ("timed out" in error_text.lower())
                no_remaining_work_signal = timeout_classification in {
                    "timeout_with_no_detectable_remaining_work",
                    "timeout_without_progress_signal_no_remaining_work",
                }
                timeout_promoted_to_success = bool(
                    error_text
                    and timed_out
                    and (not bounded_probe_run)
                    and (not low_quality)
                    and timeout_work_remaining is False
                    and (statutes_count > 0 or no_remaining_work_signal)
                )
                state_status = "error" if error_text else ("zero_statutes" if statutes_count <= 0 else "success")
                if timeout_promoted_to_success:
                    state_status = "success"
                state_name = str((state_result or {}).get("state_name") or (statute_data.get("state_name") if isinstance(statute_data, dict) else "") or "").strip()
                state_entry = {
                    "state_code": state_code,
                    "state_name": state_name,
                    "status": state_status,
                    "statutes_count": statutes_count,
                    "completed_at": _utc_now_iso(),
                }
                if timeout_diagnostics:
                    state_entry["timeout_diagnostics"] = timeout_diagnostics
                if timeout_classification:
                    state_entry["timeout_classification"] = timeout_classification
                if timeout_signal_kind:
                    state_entry["timeout_signal_kind"] = timeout_signal_kind
                if timeout_work_remaining is not None:
                    state_entry["timeout_work_remaining"] = timeout_work_remaining
                if timeout_promoted_to_success:
                    state_entry["completion_mode"] = "timeout_no_remaining_work"
                    state_entry["timeout_promoted_to_success"] = True
                    state_entry["timeout_original_error"] = error_text
                elif error_text:
                    state_entry["error"] = error_text
                results = progress_state.setdefault("state_results", {})
                if isinstance(results, dict):
                    existing_entry = results.get(state_code)
                    if isinstance(existing_entry, Mapping):
                        existing_status = str(existing_entry.get("status") or "").strip().lower()
                        try:
                            existing_count = int(existing_entry.get("statutes_count") or 0)
                        except Exception:
                            existing_count = 0

                        # Never downgrade a previously successful state to error.
                        if existing_status == "success" and state_status != "success":
                            state_entry = dict(existing_entry)
                            state_entry["retry_result_disposition"] = "kept_prior_success"
                            state_entry["last_retry_completed_at"] = _utc_now_iso()
                        else:
                            # Preserve the best observed statute count across retries.
                            if existing_count > int(state_entry.get("statutes_count") or 0):
                                state_entry["statutes_count"] = existing_count
                            # Keep prior timeout diagnostics when the new attempt
                            # has a weaker payload.
                            for key in (
                                "timeout_diagnostics",
                                "timeout_classification",
                                "timeout_signal_kind",
                                "timeout_work_remaining",
                                "timeout_original_error",
                            ):
                                if key not in state_entry and key in existing_entry:
                                    state_entry[key] = existing_entry.get(key)
                    results[state_code] = state_entry
                _recompute_progress_counts()
                _write_progress_state()
                _write_completed_states_registry_snapshot()

            if not publish_to_hf or not incremental_state_publish:
                return
            if not state_code or not isinstance(statute_data, dict):
                return
            jsonld_dir.mkdir(parents=True, exist_ok=True)
            written_paths = _write_state_jsonld_files([statute_data], jsonld_dir)
            state_jsonld_path = jsonld_dir / f"STATE-{state_code}.jsonld"
            if not state_jsonld_path.exists():
                incremental_publish_results.append(
                    {"status": "skipped", "state": state_code, "reason": "missing_state_jsonld_after_scrape"}
                )
                return
            print(f"[state_laws_refresh] incremental_publish state={state_code} stage=build", flush=True)
            build = build_state_laws_parquet_artifacts(
                states=[state_code],
                jsonld_dir=jsonld_dir,
                parquet_dir=parquet_dir,
                merge_existing_local=not bool(args.no_merge_existing_local),
                merge_hf_existing=bool(args.merge_hf_existing),
                repo_id=repo_id,
                token=hf_token,
            )
            state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state_code)
            try:
                print(f"[state_laws_refresh] incremental_publish state={state_code} stage=upload", flush=True)
                publish = _publish_state_parquet_file(
                    state_code=state_code,
                    state_parquet_path=state_parquet_path,
                    repo_id=repo_id,
                    token=hf_token,
                    create_repo=bool(args.create_repo),
                    commit_message=f"{str(args.commit_message or 'Refresh canonical state laws corpus')} ({state_code})",
                )
                incremental_publish_results.append(
                    {
                        "status": "success",
                        "state": state_code,
                        "jsonld_paths": written_paths,
                        "build": build,
                        "publish": publish,
                    }
                )
                state_result_entry = progress_state.get("state_results", {}).get(state_code) if isinstance(progress_state.get("state_results"), dict) else None
                if isinstance(state_result_entry, dict):
                    state_result_entry["incremental_publish_status"] = "success"
                    state_result_entry["incremental_publish_at"] = _utc_now_iso()
                    _recompute_progress_counts()
                    _write_progress_state()
                    _write_completed_states_registry_snapshot()
                print(f"[state_laws_refresh] incremental_publish state={state_code} stage=done", flush=True)
            except Exception as exc:
                incremental_publish_results.append(
                    {
                        "status": "error",
                        "state": state_code,
                        "jsonld_paths": written_paths,
                        "build": build,
                        "error": str(exc),
                    }
                )
                state_result_entry = progress_state.get("state_results", {}).get(state_code) if isinstance(progress_state.get("state_results"), dict) else None
                if isinstance(state_result_entry, dict):
                    state_result_entry["incremental_publish_status"] = "error"
                    state_result_entry["incremental_publish_error"] = str(exc)
                    state_result_entry["incremental_publish_at"] = _utc_now_iso()
                    _recompute_progress_counts()
                    _write_progress_state()
                    _write_completed_states_registry_snapshot()

    scrape_result: Dict[str, Any] | None = None
    full_corpus_guard_audit: Dict[str, Any] | None = None
    checkpoint_reconciliation: Dict[str, Any] | None = None
    timeout_recovery_history: List[Dict[str, Any]] = []
    scrape_max_statutes_for_run: Optional[int] = None
    progress_heartbeat_stop: asyncio.Event | None = None
    progress_heartbeat_task: asyncio.Task[Any] | None = None
    if args.scrape:
        if not states:
            scrape_result = {
                "status": "skipped",
                "reason": "all_requested_states_already_completed",
                "requested_states": requested_states,
                "skipped_completed_states": skipped_completed_states,
            }
        else:
            scrape_max_statutes = int(args.max_statutes) if int(args.max_statutes or 0) > 0 else None
            scrape_max_statutes_for_run = scrape_max_statutes
            if scrape_max_statutes is None and not bool(getattr(args, "skip_full_corpus_guard_audit", False)):
                full_corpus_guard_audit = _run_full_corpus_guard_audit(states=states)
                if str(full_corpus_guard_audit.get("status")) != "pass":
                    return {
                        "status": "failed_preflight",
                        "reason": "full_corpus_guard_audit_failed",
                        "plan": plan,
                        "full_corpus_guard_audit": full_corpus_guard_audit,
                    }
            previous_full_corpus_env = os.environ.get("STATE_SCRAPER_FULL_CORPUS")
            previous_checkpoint_dir_env = os.environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR")
            os.environ["STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR"] = str(output_root / "partial_checkpoints")
            if scrape_max_statutes is None:
                # Several state scrapers intentionally keep normal probes bounded
                # unless this flag is set.  Treat an uncapped refresh as an
                # explicit full-corpus scrape so the daemon cannot silently publish
                # sample-sized state shards.
                os.environ["STATE_SCRAPER_FULL_CORPUS"] = "1"
            progress_heartbeat_stop = asyncio.Event()
            progress_heartbeat_task = asyncio.create_task(_progress_heartbeat_loop(progress_heartbeat_stop))
            try:
                scrape_result = await scrape_state_laws(
                    states=states,
                    legal_areas=None,
                    output_format="json",
                    include_metadata=True,
                    rate_limit_delay=float(args.rate_limit_delay),
                    max_statutes=scrape_max_statutes,
                    use_state_specific_scrapers=True,
                    allow_justia_fallback=bool(args.allow_justia_fallback),
                    output_dir=str(output_root),
                    write_jsonld=True,
                    strict_full_text=bool(args.strict_full_text),
                    min_full_text_chars=int(args.min_full_text_chars),
                    hydrate_statute_text=not bool(args.no_hydrate_statute_text),
                    parallel_workers=int(args.parallel_workers),
                    per_state_retry_attempts=int(args.per_state_retry_attempts),
                    retry_zero_statute_states=True,
                    per_state_timeout_seconds=float(args.per_state_timeout_seconds),
                    state_completion_callback=_on_state_complete,
                    retain_state_data=not bool(publish_to_hf and incremental_state_publish),
                )
            finally:
                if progress_heartbeat_stop is not None:
                    progress_heartbeat_stop.set()
                if progress_heartbeat_task is not None:
                    try:
                        await progress_heartbeat_task
                    except Exception:
                        pass
                if scrape_max_statutes is None:
                    if previous_full_corpus_env is None:
                        os.environ.pop("STATE_SCRAPER_FULL_CORPUS", None)
                    else:
                        os.environ["STATE_SCRAPER_FULL_CORPUS"] = previous_full_corpus_env
                if previous_checkpoint_dir_env is None:
                    os.environ.pop("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", None)
                else:
                    os.environ["STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR"] = previous_checkpoint_dir_env

    if args.scrape:
        checkpoint_reconciliation = _reconcile_state_results_from_partial_checkpoints(
            progress_state=progress_state,
            checkpoint_dir=output_root / "partial_checkpoints",
        )
        _recompute_progress_counts()
        _write_progress_state()
        _write_completed_states_registry_snapshot()

        timeout_recovery_rounds = max(0, int(getattr(args, "timeout_recovery_rounds", 0) or 0))
        timeout_recovery_multiplier = max(1.0, float(getattr(args, "timeout_recovery_timeout_multiplier", 1.5) or 1.5))
        timeout_recovery_timeout_cap = max(0.0, float(getattr(args, "timeout_recovery_timeout_cap_seconds", 0.0) or 0.0))
        timeout_recovery_retry_attempts = max(
            int(args.per_state_retry_attempts or 0),
            int(getattr(args, "timeout_recovery_retry_attempts", 0) or 0),
        )
        timeout_recovery_parallel_workers = int(getattr(args, "timeout_recovery_parallel_workers", 0) or 0)
        if timeout_recovery_parallel_workers <= 0:
            timeout_recovery_parallel_workers = max(1, int(args.parallel_workers or 1))

        base_timeout_seconds = max(0.0, float(args.per_state_timeout_seconds or 0.0))
        for round_idx in range(timeout_recovery_rounds):
            retry_states = _eligible_timeout_recovery_states(
                states=states,
                progress_state=progress_state,
            )
            if not retry_states:
                break

            round_timeout_seconds = base_timeout_seconds
            if round_idx >= 0:
                round_timeout_seconds = base_timeout_seconds * (timeout_recovery_multiplier ** float(round_idx + 1))
            if timeout_recovery_timeout_cap > 0:
                round_timeout_seconds = min(round_timeout_seconds, timeout_recovery_timeout_cap)
            round_timeout_seconds = max(base_timeout_seconds, round_timeout_seconds)

            round_started_at = _utc_now_iso()
            round_result = await scrape_state_laws(
                states=retry_states,
                legal_areas=None,
                output_format="json",
                include_metadata=True,
                rate_limit_delay=float(args.rate_limit_delay),
                max_statutes=scrape_max_statutes_for_run,
                use_state_specific_scrapers=True,
                allow_justia_fallback=bool(args.allow_justia_fallback),
                output_dir=str(output_root),
                write_jsonld=True,
                strict_full_text=bool(args.strict_full_text),
                min_full_text_chars=int(args.min_full_text_chars),
                hydrate_statute_text=not bool(args.no_hydrate_statute_text),
                parallel_workers=int(timeout_recovery_parallel_workers),
                per_state_retry_attempts=int(timeout_recovery_retry_attempts),
                retry_zero_statute_states=True,
                per_state_timeout_seconds=float(round_timeout_seconds),
                state_completion_callback=_on_state_complete,
                retain_state_data=not bool(publish_to_hf and incremental_state_publish),
            )

            round_reconciliation = _reconcile_state_results_from_partial_checkpoints(
                progress_state=progress_state,
                checkpoint_dir=output_root / "partial_checkpoints",
            )
            _recompute_progress_counts()
            _write_progress_state()
            _write_completed_states_registry_snapshot()

            timeout_recovery_history.append(
                {
                    "round": int(round_idx + 1),
                    "started_at": round_started_at,
                    "finished_at": _utc_now_iso(),
                    "states": list(retry_states),
                    "state_count": len(retry_states),
                    "per_state_timeout_seconds": float(round_timeout_seconds),
                    "parallel_workers": int(timeout_recovery_parallel_workers),
                    "per_state_retry_attempts": int(timeout_recovery_retry_attempts),
                    "scrape_status": str((round_result or {}).get("status") or ""),
                    "round_reconciliation": round_reconciliation,
                }
            )

    build_result = build_state_laws_parquet_artifacts(
        states=requested_states,
        jsonld_dir=jsonld_dir,
        parquet_dir=parquet_dir,
        merge_existing_local=not bool(args.no_merge_existing_local),
        merge_hf_existing=bool(args.merge_hf_existing),
        repo_id=repo_id,
        token=hf_token,
    )

    scrape_gaps = []
    if isinstance(scrape_result, dict):
        metadata = scrape_result.get("metadata") or {}
        coverage = metadata.get("coverage_summary") or {}
        scrape_gaps = list(coverage.get("coverage_gap_states") or [])
    build_gaps = list(build_result.get("missing_jsonld_states") or [])
    is_complete = not scrape_gaps and not build_gaps

    publish_result: Dict[str, Any] | None = None
    if args.publish_to_hf and (is_complete or bool(args.allow_incomplete_publish)):
        publish_result = _publish_parquet_dir(
            parquet_dir=parquet_dir,
            repo_id=repo_id,
            token=hf_token,
            create_repo=bool(args.create_repo),
            verify=bool(args.verify),
            commit_message=str(args.commit_message or "Refresh canonical state laws corpus"),
        )
    elif args.publish_to_hf:
        publish_result = {
            "status": "skipped",
            "reason": "final_combined_publish_waits_for_complete_corpus",
            "detail": "Per-state startup sync and incremental completed-state publishes do not require complete all-state coverage.",
        }

    progress_state["status"] = "success" if is_complete else "partial_success"
    progress_state["finished_at"] = _utc_now_iso()
    progress_state["scrape_gap_states"] = list(scrape_gaps)
    progress_state["build_gap_states"] = list(build_gaps)
    progress_state["is_complete"] = bool(is_complete)
    _recompute_progress_counts()
    _write_progress_state()
    _write_completed_states_registry_snapshot()

    completed_registry_states = (
        completed_states_registry.get("states")
        if isinstance(completed_states_registry.get("states"), Mapping)
        else {}
    )

    return {
        "status": "success" if is_complete else "partial_success",
        "plan": plan,
        "scrape": scrape_result,
        "build": build_result,
        "startup_sync": startup_sync_result,
        "full_corpus_guard_audit": full_corpus_guard_audit,
        "checkpoint_reconciliation": checkpoint_reconciliation,
        "timeout_recovery": {
            "enabled": bool(args.scrape and int(getattr(args, "timeout_recovery_rounds", 0) or 0) > 0),
            "round_count": len(timeout_recovery_history),
            "rounds": timeout_recovery_history,
        },
        "progress_path": str(progress_path),
        "incremental_state_publish": {
            "enabled": bool(publish_to_hf and incremental_state_publish),
            "results": incremental_publish_results,
            "success_count": sum(1 for item in incremental_publish_results if str(item.get("status")) == "success"),
            "error_count": sum(1 for item in incremental_publish_results if str(item.get("status")) == "error"),
        },
        "publish": publish_result,
        "scrape_gap_states": scrape_gaps,
        "build_gap_states": build_gaps,
        "completed_states_registry": {
            "path": str(completed_states_registry_path),
            "persisted": bool(persist_completed_states_registry),
            "completed_state_count": len(completed_registry_states),
            "skipped_completed_states": skipped_completed_states,
            "baseline_path": str(completed_states_baseline_path),
            "baseline_loaded": bool(load_completed_states_baseline and completed_states_baseline_path.exists()),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh and publish the canonical state-laws corpus")
    parser.add_argument("--states", default="all", help="Comma-separated state codes, or all")
    parser.add_argument("--include-dc", action="store_true", help="Include District of Columbia when --states=all")
    parser.add_argument("--output-root", default="", help="Corpus output root; defaults to ~/.ipfs_datasets/state_laws")
    parser.add_argument("--jsonld-dir", default="", help="Override source JSON-LD directory")
    parser.add_argument("--parquet-dir", default="", help="Override destination parquet directory")
    parser.add_argument("--scrape", action="store_true", help="Run state scrapers before building parquet")
    parser.add_argument("--max-statutes", type=int, default=0, help="Optional cap across the scrape run; 0 means all")
    parser.add_argument("--rate-limit-delay", type=float, default=1.0)
    parser.add_argument("--parallel-workers", type=int, default=4)
    parser.add_argument("--per-state-retry-attempts", type=int, default=1)
    parser.add_argument("--per-state-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--timeout-recovery-rounds",
        type=int,
        default=0,
        help="After the main scrape pass, retry timeout-error states for this many additional rounds.",
    )
    parser.add_argument(
        "--timeout-recovery-timeout-multiplier",
        type=float,
        default=1.5,
        help="Per recovery round timeout multiplier applied to --per-state-timeout-seconds.",
    )
    parser.add_argument(
        "--timeout-recovery-timeout-cap-seconds",
        type=float,
        default=0.0,
        help="Optional cap for recovery round per-state timeout; 0 disables cap.",
    )
    parser.add_argument(
        "--timeout-recovery-retry-attempts",
        type=int,
        default=2,
        help="Per-state retry attempts used during timeout-recovery rounds.",
    )
    parser.add_argument(
        "--timeout-recovery-parallel-workers",
        type=int,
        default=0,
        help="Parallel workers for timeout-recovery rounds; 0 uses --parallel-workers.",
    )
    parser.add_argument("--strict-full-text", action="store_true")
    parser.add_argument("--min-full-text-chars", type=int, default=300)
    parser.add_argument("--no-hydrate-statute-text", action="store_true")
    parser.add_argument("--progress-heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("--allow-justia-fallback", action="store_true")
    parser.add_argument("--no-merge-existing-local", action="store_true")
    parser.add_argument("--merge-hf-existing", action="store_true", help="Download and merge existing HF state parquet shards")
    parser.add_argument("--publish-to-hf", action="store_true")
    parser.add_argument(
        "--completed-states-registry",
        default="",
        help="Path to persistent completed-state registry JSON (default: ~/.ipfs_datasets/state_laws/state_laws_completed_states.json).",
    )
    parser.add_argument(
        "--completed-states-baseline",
        default="",
        help="Path to repo-tracked completed-state baseline JSON (default: scripts/ops/legal_data/state_laws_completed_states.baseline.json).",
    )
    parser.add_argument(
        "--no-load-completed-states-baseline",
        dest="load_completed_states_baseline",
        action="store_false",
        default=True,
        help="Do not load repo-tracked completed-state baseline before evaluating skips.",
    )
    parser.add_argument(
        "--no-skip-completed-states",
        dest="skip_completed_states",
        action="store_false",
        default=True,
        help="Do not skip states already marked complete in the completed-state registry.",
    )
    parser.add_argument(
        "--no-persist-completed-states-registry",
        dest="persist_completed_states_registry",
        action="store_false",
        default=True,
        help="Do not update the completed-state registry for this run.",
    )
    parser.add_argument(
        "--no-startup-stale-sync",
        dest="startup_stale_sync",
        action="store_false",
        default=True,
        help="Disable startup upload of local state shards that differ from Hugging Face.",
    )
    parser.add_argument(
        "--no-incremental-state-publish",
        dest="incremental_state_publish",
        action="store_false",
        default=True,
        help="Disable per-state HF upload as each state finishes scraping.",
    )
    parser.add_argument("--allow-incomplete-publish", action="store_true")
    parser.add_argument(
        "--skip-full-corpus-guard-audit",
        action="store_true",
        help="Skip the static full-corpus truncation audit before an uncapped scrape.",
    )
    parser.add_argument("--repo-id", default=_CORPUS.hf_dataset_id)
    parser.add_argument("--hf-token", default="")
    parser.add_argument("--create-repo", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--commit-message", default="Refresh canonical state laws corpus")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(refresh_state_laws_corpus(args))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Status: {result.get('status')}")
        plan = result.get("plan") or {}
        print(f"States: {plan.get('state_count')} ({','.join(plan.get('states') or [])})")
        print(f"JSON-LD: {plan.get('jsonld_dir')}")
        print(f"Parquet: {plan.get('parquet_dir')}")
        build = result.get("build") or {}
        if build:
            print(f"Combined rows: {build.get('combined_row_count')}")
            print(f"Missing JSON-LD states: {','.join(build.get('missing_jsonld_states') or []) or 'None'}")
        if result.get("publish"):
            print(f"Publish: {(result.get('publish') or {}).get('upload_commit')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
