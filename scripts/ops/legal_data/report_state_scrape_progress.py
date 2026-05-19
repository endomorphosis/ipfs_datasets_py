#!/usr/bin/env python3
"""Report per-state legal scraper progress and completeness.

This script resolves a parallel legal-scraper run directory and emits a
state-by-state report with the strongest available signal, in this order:

1) strict final completeness from finished ``state_refresh_phase.json`` payloads
2) live callback progress from ``state_refresh_progress.json`` artifacts
3) fallback progress inferred from shard logs

Use this to answer:
- How far each state has progressed during an active run
- Which states are strictly complete/incomplete once a shard finishes
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


_STATE_LINE_RE = re.compile(r"base_scraper\.([A-Z]{2})\]")
_START_RE = re.compile(r"Scraping\s+\d+\s+codes\s+for\s+", re.IGNORECASE)
_SCRAPED_RE = re.compile(r"Scraped\s+(\d+)\s+statutes\s+from\s+", re.IGNORECASE)
_STATUTES_SO_FAR_RE = re.compile(r"statutes_so_far=(\d+)", re.IGNORECASE)
_STATUTES_EQ_RE = re.compile(r"\bstatutes=(\d+)\b", re.IGNORECASE)
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_states(value: Any) -> List[str]:
    if isinstance(value, str):
        raw = [item.strip().upper() for item in value.split(",")]
    elif isinstance(value, Sequence):
        raw = [str(item).strip().upper() for item in value]
    else:
        raw = []
    out: List[str] = []
    seen = set()
    for item in raw:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _resolve_run_dir(arg_value: str) -> Path:
    if arg_value.strip():
        return Path(arg_value).expanduser().resolve()
    latest_ptr = Path.home() / ".ipfs_datasets" / "legal_scraper_parallel" / "LATEST_RUN_DIR"
    if not latest_ptr.exists():
        raise FileNotFoundError(f"missing latest run pointer: {latest_ptr}")
    resolved = latest_ptr.read_text(encoding="utf-8").strip()
    if not resolved:
        raise RuntimeError(f"empty latest run pointer: {latest_ptr}")
    return Path(resolved).expanduser().resolve()


def _latest_phase_path(output_dir: Path) -> Optional[Path]:
    cycles_dir = output_dir / "cycles"
    if not cycles_dir.exists():
        return None
    cycle_dirs = sorted(cycles_dir.glob("cycle_*"), reverse=True)
    for cycle_dir in cycle_dirs:
        phase = cycle_dir / "state_refresh_phase.json"
        if phase.exists():
            return phase
    fallback = output_dir / "state_refresh_phase.json"
    return fallback if fallback.exists() else None


def _parse_shard_states(run_dir: Path) -> Dict[str, List[str]]:
    shards_path = run_dir / "meta" / "shards.json"
    payload = _read_json(shards_path)
    out: Dict[str, List[str]] = {}
    for shard, raw_states in payload.items():
        out[str(shard)] = _normalize_states(raw_states)
    return out


def _states_from_phase_or_default(
    phase_payload: Mapping[str, Any],
    default_states: Sequence[str],
) -> List[str]:
    resume = phase_payload.get("_resume_context")
    if isinstance(resume, dict):
        states = _normalize_states(resume.get("states"))
        if states:
            return states
    return list(default_states)


def _collect_log_progress(log_path: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not log_path.exists():
        return out
    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            sm = _STATE_LINE_RE.search(line)
            if not sm:
                continue
            state = sm.group(1)
            row = out.setdefault(
                state,
                {
                    "started": False,
                    "scraped_event": False,
                    "scraped_event_count": 0,
                    "latest_statutes_so_far": 0,
                    "latest_scraped_statutes": 0,
                    "last_log_at": "",
                },
            )
            if _START_RE.search(line):
                row["started"] = True
            scraped = _SCRAPED_RE.search(line)
            if scraped:
                row["scraped_event"] = True
                row["scraped_event_count"] = int(row["scraped_event_count"]) + 1
                row["latest_scraped_statutes"] = max(int(row["latest_scraped_statutes"]), _safe_int(scraped.group(1), 0))
            so_far = _STATUTES_SO_FAR_RE.search(line)
            if so_far:
                row["latest_statutes_so_far"] = max(int(row["latest_statutes_so_far"]), _safe_int(so_far.group(1), 0))
            eq_statutes = _STATUTES_EQ_RE.search(line)
            if eq_statutes:
                row["latest_statutes_so_far"] = max(int(row["latest_statutes_so_far"]), _safe_int(eq_statutes.group(1), 0))
            tsm = _TS_RE.search(line)
            if tsm:
                row["last_log_at"] = tsm.group(1)
    return out


def _build_final_state_rows(
    *,
    states: Sequence[str],
    shard: str,
    phase_payload: Mapping[str, Any],
    phase_path: Path,
) -> List[Dict[str, Any]]:
    scrape = phase_payload.get("scrape")
    build = phase_payload.get("build")
    scrape_meta = scrape.get("metadata") if isinstance(scrape, dict) else {}
    coverage = scrape_meta.get("coverage_summary") if isinstance(scrape_meta, dict) else {}
    coverage_gaps = set(_normalize_states(coverage.get("coverage_gap_states") if isinstance(coverage, dict) else []))
    zero_states = set(_normalize_states(coverage.get("zero_statute_states") if isinstance(coverage, dict) else []))
    error_states = set(_normalize_states(coverage.get("error_states") if isinstance(coverage, dict) else []))
    missing_states = set(_normalize_states(coverage.get("missing_states") if isinstance(coverage, dict) else []))

    missing_jsonld = set(_normalize_states(build.get("missing_jsonld_states") if isinstance(build, dict) else []))
    state_reports: Dict[str, Dict[str, Any]] = {}
    if isinstance(build, dict):
        for row in list(build.get("state_reports") or []):
            if not isinstance(row, dict):
                continue
            code = str(row.get("state") or "").strip().upper()
            if code:
                state_reports[code] = row

    out: List[Dict[str, Any]] = []
    for state in states:
        report = state_reports.get(state, {})
        scraped_row_count = _safe_int(report.get("scraped_row_count"), 0)
        merged_row_count = _safe_int(report.get("merged_row_count"), 0)
        jsonld_exists = bool(report.get("jsonld_exists")) if report else False
        reasons: List[str] = []
        if state in coverage_gaps:
            reasons.append("coverage_gap_state")
        if state in zero_states:
            reasons.append("zero_statutes")
        if state in error_states:
            reasons.append("error_state")
        if state in missing_states:
            reasons.append("missing_state")
        if state in missing_jsonld:
            reasons.append("missing_jsonld")
        if not jsonld_exists:
            reasons.append("jsonld_not_written")
        if scraped_row_count <= 0:
            reasons.append("scraped_row_count_zero")
        if merged_row_count <= 0:
            reasons.append("merged_row_count_zero")

        strict_complete = len(reasons) == 0
        out.append(
            {
                "state": state,
                "shard": shard,
                "signal_mode": "final_phase",
                "phase_path": str(phase_path),
                "status": "complete" if strict_complete else "incomplete",
                "strict_complete": strict_complete,
                "scraped_row_count": scraped_row_count,
                "merged_row_count": merged_row_count,
                "jsonld_exists": jsonld_exists,
                "reasons": reasons,
            }
        )
    return out


def _build_live_progress_rows(
    *,
    states: Sequence[str],
    shard: str,
    phase_path: Path,
    progress_payload: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    results = progress_payload.get("state_results")
    state_results = results if isinstance(results, dict) else {}
    out: List[Dict[str, Any]] = []
    for state in states:
        row = state_results.get(state) if isinstance(state_results.get(state), dict) else {}
        status = str(row.get("status") or "")
        statutes_count = _safe_int(row.get("statutes_count"), 0)
        provisional_complete = status == "success" and statutes_count > 0
        if state not in state_results:
            status = "pending"
        out.append(
            {
                "state": state,
                "shard": shard,
                "signal_mode": "live_progress",
                "phase_path": str(phase_path),
                "status": status,
                "strict_complete": None,
                "provisional_complete": provisional_complete,
                "statutes_count": statutes_count,
                "completed_at": str(row.get("completed_at") or ""),
                "error": str(row.get("error") or ""),
            }
        )
    return out


def _build_log_rows(
    *,
    states: Sequence[str],
    shard: str,
    phase_path: Path,
    log_progress: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for state in states:
        lp = log_progress.get(state) if isinstance(log_progress.get(state), dict) else {}
        started = bool(lp.get("started"))
        scraped_event = bool(lp.get("scraped_event"))
        status = "not_started"
        if started:
            status = "started"
        if scraped_event:
            status = "scraped_event_seen"
        out.append(
            {
                "state": state,
                "shard": shard,
                "signal_mode": "log_fallback",
                "phase_path": str(phase_path),
                "status": status,
                "strict_complete": None,
                "started": started,
                "scraped_event": scraped_event,
                "scraped_event_count": _safe_int(lp.get("scraped_event_count"), 0),
                "latest_statutes_so_far": _safe_int(lp.get("latest_statutes_so_far"), 0),
                "latest_scraped_statutes": _safe_int(lp.get("latest_scraped_statutes"), 0),
                "last_log_at": str(lp.get("last_log_at") or ""),
            }
        )
    return out


def _collect_rows_for_shard(
    *,
    run_dir: Path,
    shard: str,
    default_states: Sequence[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    output_dir = run_dir / shard / "output"
    log_path = run_dir / "logs" / f"{shard}.log"
    phase_path = _latest_phase_path(output_dir)
    if phase_path is None:
        rows = _build_log_rows(
            states=list(default_states),
            shard=shard,
            phase_path=output_dir / "state_refresh_phase.json",
            log_progress=_collect_log_progress(log_path),
        )
        return rows, {"shard": shard, "phase_status": "missing_phase", "signal_mode": "log_fallback"}

    phase_payload = _read_json(phase_path)
    states = _states_from_phase_or_default(phase_payload, default_states)
    phase_status = str(phase_payload.get("status") or "")

    # Finished phase payloads include scrape/build result blocks.
    if isinstance(phase_payload.get("build"), dict) or isinstance(phase_payload.get("scrape"), dict):
        rows = _build_final_state_rows(
            states=states,
            shard=shard,
            phase_payload=phase_payload,
            phase_path=phase_path,
        )
        return rows, {
            "shard": shard,
            "phase_status": phase_status,
            "signal_mode": "final_phase",
            "heartbeat_count": _safe_int(phase_payload.get("heartbeat_count"), 0),
            "updated_at": str(phase_payload.get("updated_at") or ""),
        }

    cycle_dir = phase_path.parent
    progress_path = cycle_dir / "state_laws_refresh" / "state_refresh_progress.json"
    progress_payload = _read_json(progress_path)
    if progress_payload:
        rows = _build_live_progress_rows(
            states=states,
            shard=shard,
            phase_path=phase_path,
            progress_payload=progress_payload,
        )
        return rows, {
            "shard": shard,
            "phase_status": phase_status,
            "signal_mode": "live_progress",
            "progress_path": str(progress_path),
            "heartbeat_count": _safe_int(phase_payload.get("heartbeat_count"), 0),
            "updated_at": str(phase_payload.get("updated_at") or ""),
        }

    rows = _build_log_rows(
        states=states,
        shard=shard,
        phase_path=phase_path,
        log_progress=_collect_log_progress(log_path),
    )
    return rows, {
        "shard": shard,
        "phase_status": phase_status,
        "signal_mode": "log_fallback",
        "heartbeat_count": _safe_int(phase_payload.get("heartbeat_count"), 0),
        "updated_at": str(phase_payload.get("updated_at") or ""),
    }


def _summarize(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    started_count = 0
    scraped_event_count = 0
    strict_complete_count = 0
    strict_incomplete_count = 0
    strict_unknown_count = 0
    provisional_complete_count = 0

    for row in rows:
        status = str(row.get("status") or "")
        if status in {"started", "scraped_event_seen", "success", "complete", "incomplete"}:
            started_count += 1
        if status == "scraped_event_seen":
            scraped_event_count += 1

        strict = row.get("strict_complete")
        if strict is True:
            strict_complete_count += 1
        elif strict is False:
            strict_incomplete_count += 1
        else:
            strict_unknown_count += 1

        if bool(row.get("provisional_complete")):
            provisional_complete_count += 1

    strict_evaluable = strict_complete_count + strict_incomplete_count
    return {
        "states_total": total,
        "started_count": started_count,
        "started_pct": round((100.0 * started_count / total), 1) if total else 0.0,
        "scraped_event_count": scraped_event_count,
        "strict_complete_count": strict_complete_count,
        "strict_incomplete_count": strict_incomplete_count,
        "strict_unknown_count": strict_unknown_count,
        "strict_evaluable_count": strict_evaluable,
        "strict_complete_pct": (
            round((100.0 * strict_complete_count / strict_evaluable), 1) if strict_evaluable else None
        ),
        "provisional_complete_count": provisional_complete_count,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report per-state legal scraper progress and completeness.")
    p.add_argument(
        "--parallel-run-dir",
        default="",
        help="Parallel run directory; defaults to ~/.ipfs_datasets/legal_scraper_parallel/LATEST_RUN_DIR",
    )
    p.add_argument("--output-json", default="", help="Optional output JSON file path.")
    p.add_argument("--json", action="store_true", help="Print JSON payload.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = _resolve_run_dir(str(args.parallel_run_dir or ""))
    shard_map = _parse_shard_states(run_dir)

    rows: List[Dict[str, Any]] = []
    shard_summaries: List[Dict[str, Any]] = []
    for shard in sorted(shard_map.keys()):
        shard_rows, shard_summary = _collect_rows_for_shard(
            run_dir=run_dir,
            shard=shard,
            default_states=shard_map.get(shard, []),
        )
        rows.extend(shard_rows)
        shard_summaries.append(shard_summary)

    rows_sorted = sorted(rows, key=lambda row: (str(row.get("shard") or ""), str(row.get("state") or "")))
    payload = {
        "run_dir": str(run_dir),
        "summary": _summarize(rows_sorted),
        "shards": shard_summaries,
        "states": rows_sorted,
    }

    if str(args.output_json or "").strip():
        out_path = Path(str(args.output_json)).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = payload["summary"]
        print(f"run_dir: {run_dir}")
        print(
            "states_total={states_total} started={started_count} ({started_pct}%) strict_complete={strict_complete_count} "
            "strict_incomplete={strict_incomplete_count} strict_unknown={strict_unknown_count}".format(**summary)
        )
        if summary.get("strict_complete_pct") is not None:
            print(
                f"strict_complete_pct={summary['strict_complete_pct']}% "
                f"(of {summary['strict_evaluable_count']} evaluable states)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
