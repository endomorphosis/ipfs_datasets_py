#!/usr/bin/env python3
"""Maintain a legal-scraper coverage todo board for daemon/supervisor loops.

This script bridges three workflows:
1) Scraper daemon execution (`run_legal_scraper_daemon.py`)
2) Supervisor health/heartbeat monitoring (`watch_legal_scraper_daemon.py`)
3) Coverage/gap remediation backlog management (JSON + markdown todo board)

The backlog is designed so both humans and automated supervisors can use it:
- machine-readable `*.json` for agent loops and dashboards
- markdown task board for daily operations and handoffs
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


STATUS_TO_MARK = {
    "needed": " ",
    "in-progress": "~",
    "blocked": "!",
    "complete": "x",
}

STATUS_ORDER = {
    "needed": 0,
    "in-progress": 1,
    "blocked": 2,
    "complete": 3,
}

_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)")
_LOG_STATE_RE = re.compile(r"base_scraper\.([A-Z]{2})\]")
_LOG_STATE_START_RE = re.compile(r"Scraping\s+\d+\s+codes\s+for\s+", flags=re.IGNORECASE)
_LOG_SCRAPED_STATUTES_RE = re.compile(r"Scraped\s+(\d+)\s+statutes\s+from\s+", flags=re.IGNORECASE)
_LOG_STATUTES_SOFAR_RE = re.compile(r"statutes_so_far=(\d+)", flags=re.IGNORECASE)
_LOG_STATUTES_EQ_RE = re.compile(r"\bstatutes=(\d+)\b", flags=re.IGNORECASE)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_iso_to_epoch(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return float(parsed.timestamp())
    except Exception:
        return None


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _uniq(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in items:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _normalize_states(items: Iterable[Any]) -> List[str]:
    states: List[str] = []
    for raw in items:
        value = str(raw or "").strip().upper()
        if len(value) == 2 and value.isalpha():
            states.append(value)
    return _uniq(states)


def _task_id_with_states(prefix: str, states: Iterable[str]) -> str:
    state_list = _normalize_states(states)
    digest = hashlib.sha1(",".join(state_list).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}" if state_list else prefix


def _default_backlog_payload() -> Dict[str, Any]:
    return {
        "schema": "ipfs_datasets_py.legal_scraper.todo.v1",
        "generated_at": utc_now(),
        "goal": {
            "target_coverage_ratio": 1.0,
            "objective": "Drive legal corpus coverage and quality toward 100% with daemon + supervisor loops.",
        },
        "tasks": [],
        "metrics": {},
        "history": [],
    }


def _ensure_backlog_shape(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        payload = _default_backlog_payload()
    payload.setdefault("schema", "ipfs_datasets_py.legal_scraper.todo.v1")
    payload.setdefault("generated_at", utc_now())
    payload.setdefault("goal", _default_backlog_payload()["goal"])
    payload.setdefault("tasks", [])
    payload.setdefault("metrics", {})
    payload.setdefault("history", [])
    if not isinstance(payload.get("tasks"), list):
        payload["tasks"] = []
    return payload


def _seed_core_tasks(backlog: Dict[str, Any], *, reopen_complete: bool) -> None:
    seeds: List[Dict[str, Any]] = [
        {
            "task_id": "fix:broken-legacy-federal-wrapper-imports",
            "title": "Fix broken legal scraper script wrappers for US Code and Federal Register imports.",
            "status": "needed",
            "priority": 10,
            "category": "code_fix",
            "source": "seed",
            "evidence": [
                "scripts/scrapers/legal/us_code_scraper.py imports missing module path",
                "scripts/scrapers/legal/federal_register_scraper.py imports missing module path",
            ],
            "commands": [
                "python3 scripts/scrapers/legal/us_code_scraper.py",
                "python3 scripts/scrapers/legal/federal_register_scraper.py",
            ],
        },
        {
            "task_id": "fix:async-blocking-sleeps",
            "title": "Replace blocking time.sleep calls in async legal scrapers with await asyncio.sleep.",
            "status": "needed",
            "priority": 15,
            "category": "code_fix",
            "source": "seed",
            "evidence": [
                "state_laws_scraper.py, recap_archive_scraper.py, federal_register_scraper.py use blocking sleeps in async loops",
            ],
            "commands": [
                "python3 -m pytest tests/unit/legal_scrapers -q",
            ],
        },
        {
            "task_id": "fix:state-jsonld-synthetic-filler-policy",
            "title": "Prevent synthetic filler rows from polluting production state-laws corpus quality paths.",
            "status": "needed",
            "priority": 20,
            "category": "normalization",
            "source": "seed",
            "evidence": [
                "refresh_state_jsonld_quality.py emits generated-filler + example.invalid rows",
            ],
            "commands": [
                "python3 scripts/ops/legal_data/report_state_law_page_gaps.py --json",
            ],
        },
        {
            "task_id": "fix:municipal-placeholder-and-fallback-stubs",
            "title": "Replace municipal placeholder scraper outputs and implement fallback stub methods.",
            "status": "needed",
            "priority": 22,
            "category": "code_fix",
            "source": "seed",
            "evidence": [
                "municipal_laws_scraper.py returns placeholder ordinance rows",
                "municipal_scraper_engine.py has TODO stubs for most fallback methods",
            ],
            "commands": [
                "python3 scripts/ops/legal_data/refresh_municipal_laws_corpus.py --help",
            ],
        },
        {
            "task_id": "fix:common-crawl-path-preflight-and-env",
            "title": "Harden Common Crawl path preflight and environment defaults before admin-rules crawling.",
            "status": "needed",
            "priority": 25,
            "category": "infra",
            "source": "seed",
            "evidence": [
                "state_admin page gap artifacts show repeated /storage/ccindex_parquet missing-root failures",
            ],
            "commands": [
                "python3 scripts/ops/legal_data/run_legal_scraper_daemon.py --preflight-only --full-corpus",
            ],
        },
    ]
    for task in seeds:
        _upsert_task(backlog, task, reopen_complete=reopen_complete)


def _task_map(backlog: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for task in backlog.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if task_id:
            out[task_id] = task
    return out


def _normalize_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"needed", "in-progress", "blocked", "complete"}:
        return text
    return "needed"


def _upsert_task(
    backlog: Dict[str, Any],
    task: Dict[str, Any],
    *,
    reopen_complete: bool,
) -> Dict[str, Any]:
    tasks = backlog.setdefault("tasks", [])
    existing = _task_map(backlog).get(str(task.get("task_id") or "").strip())
    now = utc_now()

    if existing is None:
        new_task = {
            "task_id": str(task.get("task_id") or f"task-{len(tasks) + 1}").strip(),
            "title": str(task.get("title") or "").strip(),
            "status": _normalize_status(task.get("status")),
            "priority": _safe_int(task.get("priority"), 50),
            "category": str(task.get("category") or "coverage").strip() or "coverage",
            "source": str(task.get("source") or "supervisor").strip() or "supervisor",
            "states": _normalize_states(task.get("states") or []),
            "evidence": _uniq(str(x) for x in list(task.get("evidence") or [])),
            "commands": _uniq(str(x) for x in list(task.get("commands") or [])),
            "notes": _uniq(str(x) for x in list(task.get("notes") or [])),
            "llm_rewrite_plan": task.get("llm_rewrite_plan"),
            "created_at": now,
            "updated_at": now,
        }
        tasks.append(new_task)
        return new_task

    if str(task.get("title") or "").strip():
        existing["title"] = str(task.get("title")).strip()
    if str(task.get("category") or "").strip():
        existing["category"] = str(task.get("category")).strip()
    if str(task.get("source") or "").strip():
        existing["source"] = str(task.get("source")).strip()
    existing["priority"] = min(_safe_int(existing.get("priority"), 50), _safe_int(task.get("priority"), 50))

    incoming_status = _normalize_status(task.get("status"))
    existing_status = _normalize_status(existing.get("status"))
    if incoming_status == "complete":
        existing["status"] = "complete"
    elif existing_status == "complete":
        if reopen_complete:
            existing["status"] = incoming_status
            notes = list(existing.get("notes") or [])
            notes.append(f"Reopened at {now} because new evidence was detected.")
            existing["notes"] = _uniq(notes)
    else:
        # Keep the most urgent state when both are non-complete.
        existing_rank = STATUS_ORDER.get(existing_status, 99)
        incoming_rank = STATUS_ORDER.get(incoming_status, 99)
        if incoming_rank < existing_rank:
            existing["status"] = incoming_status

    existing["states"] = _uniq(list(existing.get("states") or []) + _normalize_states(task.get("states") or []))
    existing["evidence"] = _uniq(list(existing.get("evidence") or []) + [str(x) for x in list(task.get("evidence") or [])])
    existing["commands"] = _uniq(list(existing.get("commands") or []) + [str(x) for x in list(task.get("commands") or [])])
    existing["notes"] = _uniq(list(existing.get("notes") or []) + [str(x) for x in list(task.get("notes") or [])])

    if task.get("llm_rewrite_plan"):
        existing["llm_rewrite_plan"] = task.get("llm_rewrite_plan")

    existing["updated_at"] = now
    return existing


def _update_history(backlog: Dict[str, Any], event: str, payload: Dict[str, Any]) -> None:
    history = backlog.setdefault("history", [])
    row = {
        "at": utc_now(),
        "event": event,
        "payload": payload,
    }
    history.append(row)
    if len(history) > 500:
        del history[:-500]


def _extract_weak_states(section: Any) -> List[str]:
    if isinstance(section, list):
        out: List[str] = []
        for item in section:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                state = item.get("state") or item.get("state_code")
                if state:
                    out.append(str(state))
        return _normalize_states(out)
    return []


def _ingest_retry_manifest(backlog: Dict[str, Any], path: Path, *, reopen_complete: bool) -> Dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {"found": False}

    status = str(payload.get("status") or "").strip().lower()
    phases = list(payload.get("retry_phases") or [])
    retry_states = _normalize_states(payload.get("retry_states") or [])
    output: Dict[str, Any] = {
        "found": True,
        "status": status,
        "retry_phase_count": len(phases),
        "retry_states": retry_states,
    }

    if status == "complete":
        for task in backlog.get("tasks", []):
            if not isinstance(task, dict):
                continue
            if str(task.get("source") or "") != "retry_manifest":
                continue
            task["status"] = "complete"
            task["updated_at"] = utc_now()
        _update_history(backlog, "retry_manifest_complete", {"path": str(path)})
        return output

    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase_name = str(phase.get("phase") or "").strip() or "unknown_phase"
        corpus = str(phase.get("corpus") or "state_laws").strip()
        states = _normalize_states(phase.get("states") or [])
        reason = str(phase.get("reason") or "").strip()
        args = [str(x) for x in list(phase.get("recommended_args") or []) if str(x).strip()]
        command = "python3 scripts/ops/legal_data/run_legal_scraper_daemon.py " + " ".join(args)
        task = {
            "task_id": _task_id_with_states(f"retry:{phase_name}:{corpus}", states),
            "title": f"Recover {phase_name} coverage gaps for {corpus} ({', '.join(states) if states else 'all states'}).",
            "status": "needed",
            "priority": 18 if phase_name == "state_refresh" else 20,
            "category": "coverage",
            "source": "retry_manifest",
            "states": states,
            "evidence": [reason, f"retry_manifest={path}"],
            "commands": [command],
        }
        _upsert_task(backlog, task, reopen_complete=reopen_complete)

    _update_history(
        backlog,
        "retry_manifest_ingested",
        {
            "path": str(path),
            "retry_phase_count": len(phases),
            "retry_states": retry_states,
        },
    )
    return output


def _ingest_state_law_page_gap_report(backlog: Dict[str, Any], path: Path, *, reopen_complete: bool) -> Dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {"found": False}

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    weak_states = _extract_weak_states(summary.get("weak_states")) or _extract_weak_states(payload.get("weak_states"))
    output: Dict[str, Any] = {
        "found": True,
        "weak_states": weak_states,
        "rows_total": _safe_int(summary.get("rows_total"), 0),
        "real_total": _safe_int(summary.get("real_total"), 0),
        "synthetic_total": _safe_int(summary.get("synthetic_total"), 0),
        "avg_real_ratio": _safe_float(summary.get("avg_real_ratio"), 0.0),
    }

    weak_rows = payload.get("weak_states") if isinstance(payload.get("weak_states"), list) else []
    weak_by_state: Dict[str, Dict[str, Any]] = {}
    for row in weak_rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("state") or "").strip().upper()
        if code:
            weak_by_state[code] = row

    for state in weak_states:
        row = weak_by_state.get(state, {})
        real_ratio = _safe_float(row.get("real_ratio"), -1.0)
        task = {
            "task_id": f"gap:state_laws:{state}",
            "title": f"Raise state-laws real-row coverage for {state}.",
            "status": "needed",
            "priority": 12,
            "category": "coverage",
            "source": "state_law_page_gap_report",
            "states": [state],
            "evidence": [
                f"weak_state={state}",
                f"real_ratio={real_ratio:.3f}" if real_ratio >= 0 else "real_ratio=unknown",
                f"gap_report={path}",
            ],
            "commands": [
                f"python3 scripts/ops/legal_data/refresh_state_laws_corpus.py --states {state} --scrape --strict-full-text",
                f"python3 scripts/ops/legal_data/run_all_state_legal_corpora_agentic.py --states {state} --corpora laws --max-cycles 1 --stop-on-target-score",
            ],
        }
        _upsert_task(backlog, task, reopen_complete=reopen_complete)

    _update_history(
        backlog,
        "state_law_page_gap_report_ingested",
        {
            "path": str(path),
            "weak_states": weak_states,
            "rows_total": output["rows_total"],
        },
    )
    return output


def _ingest_state_admin_page_gap_report(backlog: Dict[str, Any], path: Path, *, reopen_complete: bool) -> Dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {"found": False}

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    weak_states = _extract_weak_states(summary.get("weak_states")) or _extract_weak_states(payload.get("weak_states"))
    output: Dict[str, Any] = {
        "found": True,
        "weak_states": weak_states,
        "pages_total": _safe_int(summary.get("pages_total"), 0),
        "non_substantive_pages_total": _safe_int(summary.get("non_substantive_pages_total"), 0),
        "blocked_pages_total": _safe_int(summary.get("blocked_pages_total"), 0),
        "candidate_substantive_pages_total": _safe_int(summary.get("candidate_substantive_pages_total"), 0),
    }

    for state in weak_states:
        task = {
            "task_id": f"gap:state_admin_rules:{state}",
            "title": f"Recover substantive admin-rule coverage for {state}.",
            "status": "needed",
            "priority": 11,
            "category": "coverage",
            "source": "state_admin_page_gap_report",
            "states": [state],
            "evidence": [
                f"weak_state={state}",
                f"gap_report={path}",
            ],
            "commands": [
                f"python3 scripts/ops/legal_data/run_all_state_legal_corpora_agentic.py --states {state} --corpora admin --max-cycles 1 --full-corpus-mode",
            ],
        }
        _upsert_task(backlog, task, reopen_complete=reopen_complete)

    if output["blocked_pages_total"] > 0:
        _upsert_task(
            backlog,
            {
                "task_id": "infra:admin-rules-blocked-pages",
                "title": "Resolve blocked admin-rule fetch paths (cert/rate-limit/challenge/download/ccindex path issues).",
                "status": "needed",
                "priority": 14,
                "category": "infra",
                "source": "state_admin_page_gap_report",
                "evidence": [
                    f"blocked_pages_total={output['blocked_pages_total']}",
                    f"gap_report={path}",
                ],
                "commands": [
                    "python3 scripts/ops/legal_data/run_legal_scraper_daemon.py --preflight-only --preflight-probe-hf --full-corpus",
                ],
            },
            reopen_complete=reopen_complete,
        )

    _update_history(
        backlog,
        "state_admin_page_gap_report_ingested",
        {
            "path": str(path),
            "weak_states": weak_states,
            "blocked_pages_total": output["blocked_pages_total"],
        },
    )
    return output


def _ingest_state_admin_deep_summary(backlog: Dict[str, Any], path: Path, *, reopen_complete: bool) -> Dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {"found": False}
    states = payload.get("states") if isinstance(payload.get("states"), list) else []
    gap_states: List[str] = []
    categories: Dict[str, int] = {}
    for row in states:
        if not isinstance(row, dict):
            continue
        category = str(row.get("gap_category") or "").strip()
        state = str(row.get("state_code") or "").strip().upper()
        if category:
            categories[category] = categories.get(category, 0) + 1
        if category and category != "has_substantive_signal" and state:
            gap_states.append(state)
    gap_states = _normalize_states(gap_states)

    for state in gap_states:
        _upsert_task(
            backlog,
            {
                "task_id": f"deepgap:state_admin_rules:{state}",
                "title": f"Close deep admin-rules gap category for {state}.",
                "status": "needed",
                "priority": 13,
                "category": "coverage",
                "source": "state_admin_deep_summary",
                "states": [state],
                "evidence": [f"deep_summary={path}"],
                "commands": [
                    f"python3 scripts/ops/legal_data/run_all_state_legal_corpora_agentic.py --states {state} --corpora admin --max-cycles 2 --full-corpus-mode",
                ],
            },
            reopen_complete=reopen_complete,
        )

    output = {
        "found": True,
        "states_total": len(states),
        "gap_states": gap_states,
        "categories": categories,
    }
    _update_history(
        backlog,
        "state_admin_deep_summary_ingested",
        {
            "path": str(path),
            "gap_states": gap_states,
            "categories": categories,
        },
    )
    return output


def _run_watch_script(log_path: Path, phase_path: Path, pid: Optional[int]) -> Dict[str, Any]:
    script = Path(__file__).resolve().parent / "watch_legal_scraper_daemon.py"
    if not script.exists():
        return {"status": "missing_watch_script"}
    cmd = [
        sys.executable,
        str(script),
        "--log",
        str(log_path),
        "--phase-json",
        str(phase_path),
        "--json",
    ]
    if pid:
        cmd.extend(["--pid", str(pid)])
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "status": "watch_failed",
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip(),
        }
    try:
        payload = json.loads(proc.stdout)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"status": "watch_invalid_json", "stdout": proc.stdout[:500]}


def _extract_flag_value(tokens: List[str], flag: str) -> str:
    for index, token in enumerate(tokens):
        if token == flag and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return ""


def _norm_path(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return str(Path(value).expanduser())


def _list_legal_scraper_daemons() -> List[Dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except Exception:
        return []
    this_pid = os.getpid()
    daemons: List[Dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, args = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except Exception:
            continue
        # Ignore the current supervisor/watch process and other wrappers that
        # may mention run_legal_scraper_daemon.py only as an argument string.
        if pid == this_pid:
            continue
        if "legal_scraper_todo_supervisor.py" in args:
            continue
        if "watch_legal_scraper_daemon.py" in args:
            continue
        if "rg -n" in args and "run_legal_scraper_daemon.py" in args:
            continue
        if "grep" in args and "run_legal_scraper_daemon.py" in args:
            continue
        if "run_legal_scraper_daemon.py" in args or "processors.legal_scrapers.legal_scraper_daemon" in args:
            try:
                tokens = shlex.split(args)
            except Exception:
                tokens = args.split()
            output_dir = _extract_flag_value(tokens, "--output-dir")
            states = _extract_flag_value(tokens, "--states")
            daemons.append(
                {
                    "pid": pid,
                    "args": args,
                    "output_dir": _norm_path(output_dir),
                    "states": _normalize_states(states.split(",")) if states else [],
                    "include_dc": "--include-dc" in tokens,
                }
            )
    return sorted(daemons, key=lambda row: int(row.get("pid") or 0))


def _find_legal_scraper_daemon_pids() -> List[int]:
    return [int(row.get("pid") or 0) for row in _list_legal_scraper_daemons() if int(row.get("pid") or 0) > 0]


def _find_legal_scraper_daemon_pid() -> Optional[int]:
    pids = _find_legal_scraper_daemon_pids()
    return pids[0] if pids else None


def _latest_phase_path(output_dir: Path, phase_filename: str) -> Optional[Path]:
    cycles_dir = output_dir / "cycles"
    cycle_dirs = sorted(cycles_dir.glob("cycle_*"), reverse=True) if cycles_dir.exists() else []
    for cycle_dir in cycle_dirs:
        phase_path = cycle_dir / phase_filename
        if phase_path.exists():
            return phase_path
    fallback = output_dir / phase_filename
    if fallback.exists():
        return fallback
    return None


def _parse_log_timestamp_epoch(line: str) -> Optional[float]:
    match = _LOG_TS_RE.match(line)
    if not match:
        return None
    text = match.group(1)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return float(parsed.timestamp())


def _read_tail_text(path: Path, *, max_bytes: int = 4_000_000) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return ""
            seek_to = max(0, size - max(1024, int(max_bytes)))
            handle.seek(seek_to, os.SEEK_SET)
            data = handle.read()
    except Exception:
        return ""
    text = data.decode("utf-8", errors="ignore")
    if seek_to > 0:
        newline = text.find("\n")
        if newline >= 0:
            text = text[newline + 1 :]
    return text


def _compute_samples_rate_per_minute(samples: List[Tuple[float, int]], *, now: float, window_seconds: float) -> Optional[float]:
    if len(samples) < 2:
        return None
    window_start = now - max(60.0, float(window_seconds))
    filtered = [item for item in samples if item[0] >= window_start]
    if len(filtered) < 2:
        return None
    filtered.sort(key=lambda item: item[0])
    first_ts, first_count = filtered[0]
    last_ts, _ = filtered[-1]
    max_count = max(count for _, count in filtered)
    delta = max(0, int(max_count) - int(first_count))
    span_seconds = max(1.0, float(last_ts - first_ts))
    return round((float(delta) * 60.0) / span_seconds, 4)


def _load_state_refresh_progress_payload(output_dir: Path, phase_path: Optional[Path]) -> Tuple[Dict[str, Any], Optional[Path]]:
    cycle_dir = phase_path.parent if phase_path is not None else (output_dir / "cycles")
    if not cycle_dir.exists():
        return {}, None
    progress_path = cycle_dir / "state_laws_refresh" / "state_refresh_progress.json"
    if not progress_path.exists():
        return {}, None
    return _read_json(progress_path), progress_path


def _collect_state_rate_analytics(
    *,
    shard_name: str,
    states: List[str],
    log_path: Path,
    output_dir: Path,
    phase_path: Optional[Path],
    now_epoch: float,
    rate_window_seconds: float,
    state_stall_seconds: float,
) -> Dict[str, Any]:
    progress_payload, progress_path = _load_state_refresh_progress_payload(output_dir, phase_path)
    progress_state_results = progress_payload.get("state_results") if isinstance(progress_payload.get("state_results"), dict) else {}
    progress_started_epoch = _safe_iso_to_epoch(progress_payload.get("started_at"))
    completed_states = {
        str(code).upper()
        for code, row in progress_state_results.items()
        if isinstance(row, dict)
        and str(row.get("status") or "").strip().lower() in {"success", "error", "zero_statutes"}
    }
    signal_mode = "live_progress" if progress_path else "log_only"

    log_data: Dict[str, Dict[str, Any]] = {}
    tail_text = _read_tail_text(log_path)
    for line in tail_text.splitlines():
        match = _LOG_STATE_RE.search(line)
        if not match:
            continue
        ts_epoch = _parse_log_timestamp_epoch(line)
        # When live progress tracking is active, ignore stale log lines from
        # earlier daemon generations so restart loops do not inherit old
        # stalled-state signals.
        if (
            signal_mode == "live_progress"
            and progress_started_epoch is not None
            and ts_epoch is not None
            and ts_epoch < (progress_started_epoch - 1.0)
        ):
            continue
        state = str(match.group(1) or "").upper().strip()
        if not state:
            continue
        row = log_data.setdefault(
            state,
            {
                "started": False,
                "line_count": 0,
                "scraped_event_count": 0,
                "scraped_event_max": 0,
                "last_seen_epoch": None,
                "last_progress_epoch": None,
                "max_counter": 0,
                "samples": [],
            },
        )
        row["line_count"] = int(row.get("line_count", 0)) + 1
        if ts_epoch is not None:
            prev_seen = row.get("last_seen_epoch")
            if prev_seen is None or ts_epoch >= float(prev_seen):
                row["last_seen_epoch"] = float(ts_epoch)
        if _LOG_STATE_START_RE.search(line):
            row["started"] = True

        counter: Optional[int] = None
        so_far_match = _LOG_STATUTES_SOFAR_RE.search(line)
        if so_far_match:
            counter = _safe_int(so_far_match.group(1), 0)
        else:
            eq_match = _LOG_STATUTES_EQ_RE.search(line)
            if eq_match:
                counter = _safe_int(eq_match.group(1), 0)

        if counter is not None:
            row["max_counter"] = max(int(row.get("max_counter", 0)), int(counter))
            if ts_epoch is not None:
                samples = list(row.get("samples") or [])
                samples.append((float(ts_epoch), int(counter)))
                if len(samples) > 256:
                    samples = samples[-256:]
                row["samples"] = samples
                prev_progress = row.get("last_progress_epoch")
                if prev_progress is None or ts_epoch >= float(prev_progress):
                    row["last_progress_epoch"] = float(ts_epoch)

        scraped_match = _LOG_SCRAPED_STATUTES_RE.search(line)
        if scraped_match:
            row["scraped_event_count"] = int(row.get("scraped_event_count", 0)) + 1
            row["scraped_event_max"] = max(int(row.get("scraped_event_max", 0)), _safe_int(scraped_match.group(1), 0))

    all_states = _normalize_states(states) or sorted(log_data.keys())
    state_rows: List[Dict[str, Any]] = []
    started_states: List[str] = []
    completed_from_progress: List[str] = []
    inflight_states: List[str] = []
    stalled_states: List[Dict[str, Any]] = []
    high_confidence_stalled_states: List[Dict[str, Any]] = []
    low_confidence_inactive_state_count = 0

    for state in all_states:
        row = log_data.get(state, {})
        is_completed = state in completed_states
        started = bool(row.get("started")) or (int(row.get("line_count", 0)) > 0) or is_completed
        if started:
            started_states.append(state)
        if is_completed:
            completed_from_progress.append(state)
        is_inflight = started and (not is_completed)
        if is_inflight:
            inflight_states.append(state)

        last_seen_epoch = row.get("last_seen_epoch")
        last_progress_epoch = row.get("last_progress_epoch")
        last_seen_age = (
            max(0.0, now_epoch - float(last_seen_epoch))
            if last_seen_epoch is not None
            else -1.0
        )
        last_progress_age = (
            max(0.0, now_epoch - float(last_progress_epoch))
            if last_progress_epoch is not None
            else -1.0
        )
        samples = list(row.get("samples") or [])
        rate_per_minute = _compute_samples_rate_per_minute(
            samples,
            now=now_epoch,
            window_seconds=rate_window_seconds,
        )
        scraped_event_count = _safe_int(row.get("scraped_event_count"), 0)
        max_counter = _safe_int(row.get("max_counter"), 0)

        likely_stalled = (
            is_inflight
            and last_seen_age >= state_stall_seconds
            and (last_progress_age < 0 or last_progress_age >= state_stall_seconds)
        )
        confidence = "low"
        reason = ""
        if likely_stalled:
            if signal_mode == "live_progress":
                confidence = "high"
                reason = "no_recent_log_or_progress_for_inflight_state"
            elif scraped_event_count <= 0 and max_counter <= 0:
                confidence = "medium"
                reason = "started_state_without_progress_signals_for_stall_window"
            else:
                confidence = "low"
                reason = "inflight_state_inactive_but_completion_status_unknown_without_live_progress"

        state_entry = {
            "state": state,
            "started": started,
            "completed": is_completed,
            "inflight": is_inflight,
            "line_count": _safe_int(row.get("line_count"), 0),
            "scraped_event_count": scraped_event_count,
            "max_counter": max_counter,
            "last_seen_age_seconds": round(last_seen_age, 1) if last_seen_age >= 0 else -1.0,
            "last_progress_age_seconds": round(last_progress_age, 1) if last_progress_age >= 0 else -1.0,
            "rate_counter_per_minute": rate_per_minute,
            "likely_stalled": bool(likely_stalled),
            "stall_confidence": confidence if likely_stalled else "",
            "stall_reason": reason if likely_stalled else "",
        }
        state_rows.append(state_entry)

        if likely_stalled:
            stalled_row = {
                "state": state,
                "shard": shard_name,
                "confidence": confidence,
                "reason": reason,
                "last_seen_age_seconds": round(last_seen_age, 1) if last_seen_age >= 0 else -1.0,
                "last_progress_age_seconds": round(last_progress_age, 1) if last_progress_age >= 0 else -1.0,
                "rate_counter_per_minute": rate_per_minute,
                "scraped_event_count": scraped_event_count,
                "max_counter": max_counter,
            }
            if confidence in {"high", "medium"}:
                stalled_states.append(stalled_row)
                if confidence == "high":
                    high_confidence_stalled_states.append(stalled_row)
            else:
                low_confidence_inactive_state_count += 1

    stalled_states.sort(
        key=lambda row: (
            0 if str(row.get("confidence")) == "high" else 1,
            -_safe_float(row.get("last_progress_age_seconds"), -1.0),
            -_safe_float(row.get("last_seen_age_seconds"), -1.0),
            str(row.get("state") or ""),
        )
    )

    return {
        "signal_mode": signal_mode,
        "rate_window_seconds": max(60.0, float(rate_window_seconds)),
        "state_stall_seconds": max(300.0, float(state_stall_seconds)),
        "progress_path": str(progress_path) if progress_path else "",
        "states_total": len(all_states),
        "states_started_count": len(started_states),
        "states_completed_count": len(completed_from_progress),
        "states_inflight_count": len(inflight_states),
        "stalled_state_count": len(stalled_states),
        "high_confidence_stalled_state_count": len(high_confidence_stalled_states),
        "low_confidence_inactive_state_count": int(low_confidence_inactive_state_count),
        "started_states": started_states,
        "completed_states": completed_from_progress,
        "inflight_states": inflight_states,
        "stalled_states": stalled_states,
        "states": state_rows,
    }


def _collect_parallel_watch_payload(
    *,
    parallel_run_dir: Path,
    parallel_output_glob: str,
    phase_filename: str,
    stale_after_seconds: float,
    state_stall_seconds: float,
    state_rate_window_seconds: float,
) -> Dict[str, Any]:
    run_dir = parallel_run_dir.expanduser().resolve()
    if not run_dir.exists():
        return {
            "mode": "parallel",
            "status": "missing_parallel_run_dir",
            "parallel_run_dir": str(run_dir),
            "shards": [],
            "shard_count": 0,
            "healthy_shard_count": 0,
            "stale_shard_count": 0,
            "dead_shard_count": 0,
            "missing_phase_shard_count": 0,
            "daemon_pids": [],
            "pid_alive": False,
            "heartbeat_age_seconds": -1.0,
            "stalled_state_count": 0,
            "high_confidence_stalled_state_count": 0,
            "stalled_states": [],
        }

    daemon_rows = _list_legal_scraper_daemons()
    daemon_by_output = {
        str(row.get("output_dir") or "").strip(): row
        for row in daemon_rows
        if str(row.get("output_dir") or "").strip()
    }
    now = time.time()
    shards: List[Dict[str, Any]] = []
    max_age = -1.0
    stalled_states: List[Dict[str, Any]] = []
    high_confidence_stalled_count = 0
    low_confidence_inactive_state_count = 0

    for output_dir in sorted(run_dir.glob(parallel_output_glob)):
        if not output_dir.is_dir():
            continue
        shard_name = output_dir.parent.name if output_dir.name == "output" else output_dir.name
        phase_path = _latest_phase_path(output_dir, phase_filename)
        phase_payload = _read_json(phase_path) if phase_path else {}
        resume = phase_payload.get("_resume_context") if isinstance(phase_payload.get("_resume_context"), dict) else {}
        states = _normalize_states(resume.get("states") or [])
        updated_at = str(phase_payload.get("updated_at") or "")
        phase_status = str(phase_payload.get("status") or "")
        heartbeat_count = (
            _safe_int(phase_payload.get("heartbeat_count"), 0)
            if "heartbeat_count" in phase_payload
            else None
        )

        heartbeat_age = None
        if phase_path and phase_path.exists():
            try:
                heartbeat_age = max(0.0, now - float(phase_path.stat().st_mtime))
            except Exception:
                heartbeat_age = None
        if heartbeat_age is None:
            updated_epoch = _safe_iso_to_epoch(updated_at)
            if updated_epoch is not None:
                heartbeat_age = max(0.0, now - updated_epoch)
        if heartbeat_age is not None:
            max_age = max(max_age, float(heartbeat_age))

        output_key = _norm_path(str(output_dir))
        daemon_row = daemon_by_output.get(output_key, {})
        shard_pid = _safe_int(daemon_row.get("pid"), 0) or None
        pid_alive = _pid_alive(shard_pid) if shard_pid else None

        if not phase_path:
            shard_status = "missing_phase"
        elif shard_pid and pid_alive is False:
            shard_status = "dead_pid"
        elif heartbeat_age is not None and heartbeat_age > stale_after_seconds:
            shard_status = "stale"
        elif phase_status.lower() in {"success", "complete"}:
            shard_status = "complete"
        elif phase_status:
            shard_status = "running"
        else:
            shard_status = "unknown"

        shards.append(
            {
                "shard": shard_name,
                "output_dir": str(output_dir.resolve()),
                "phase_path": str(phase_path) if phase_path else "",
                "phase_status": phase_status,
                "status": shard_status,
                "heartbeat_count": heartbeat_count,
                "heartbeat_age_seconds": round(float(heartbeat_age), 1) if heartbeat_age is not None else -1.0,
                "updated_at": updated_at,
                "pid": shard_pid,
                "pid_alive": pid_alive,
                "states": states,
            }
        )
        state_rate_analytics = _collect_state_rate_analytics(
            shard_name=shard_name,
            states=states,
            log_path=run_dir / "logs" / f"{shard_name}.log",
            output_dir=output_dir,
            phase_path=phase_path,
            now_epoch=now,
            rate_window_seconds=max(60.0, float(state_rate_window_seconds)),
            state_stall_seconds=max(300.0, float(state_stall_seconds)),
        )
        shards[-1]["state_rate_analytics"] = state_rate_analytics
        low_confidence_inactive_state_count += _safe_int(
            state_rate_analytics.get("low_confidence_inactive_state_count"),
            0,
        )
        for stalled in list(state_rate_analytics.get("stalled_states") or []):
            if not isinstance(stalled, dict):
                continue
            stalled_states.append(stalled)
            if str(stalled.get("confidence") or "") == "high":
                high_confidence_stalled_count += 1

    stale_shards = [row for row in shards if str(row.get("status")) == "stale"]
    dead_shards = [row for row in shards if str(row.get("status")) == "dead_pid"]
    missing_phase_shards = [row for row in shards if str(row.get("status")) == "missing_phase"]
    healthy_shards = [
        row
        for row in shards
        if str(row.get("status")) in {"running", "complete"}
        and _safe_float(row.get("heartbeat_age_seconds"), -1.0) <= stale_after_seconds
    ]
    daemon_pids = [int(row.get("pid")) for row in shards if int(row.get("pid") or 0) > 0]

    if not shards:
        status = "no_shards"
    elif missing_phase_shards or dead_shards:
        status = "degraded"
    elif stale_shards:
        status = "stale"
    else:
        status = "ok"

    return {
        "mode": "parallel",
        "status": status,
        "parallel_run_dir": str(run_dir),
        "phase_status": "running" if healthy_shards else status,
        "heartbeat_age_seconds": round(max_age, 1) if max_age >= 0 else -1.0,
        "pid_alive": bool(daemon_pids) and all(_pid_alive(pid) for pid in daemon_pids),
        "pid": None,
        "daemon_pids": daemon_pids,
        "shards": shards,
        "shard_count": len(shards),
        "healthy_shard_count": len(healthy_shards),
        "stale_shard_count": len(stale_shards),
        "dead_shard_count": len(dead_shards),
        "missing_phase_shard_count": len(missing_phase_shards),
        "stalled_state_count": len(stalled_states),
        "high_confidence_stalled_state_count": int(high_confidence_stalled_count),
        "low_confidence_inactive_state_count": int(low_confidence_inactive_state_count),
        "stalled_states": stalled_states[:80],
    }


def _collect_watch_payload(args: argparse.Namespace) -> Dict[str, Any]:
    stale_after_seconds = max(1.0, float(args.stale_heartbeat_seconds))
    parallel_run_dir_text = str(getattr(args, "parallel_run_dir", "") or "").strip()
    if parallel_run_dir_text:
        return _collect_parallel_watch_payload(
            parallel_run_dir=Path(parallel_run_dir_text),
            parallel_output_glob=str(getattr(args, "parallel_output_glob", "shard*/output") or "shard*/output"),
            phase_filename=str(getattr(args, "parallel_phase_filename", "state_refresh_phase.json") or "state_refresh_phase.json"),
            stale_after_seconds=stale_after_seconds,
            state_stall_seconds=max(300.0, float(getattr(args, "state_stall_seconds", 3600.0))),
            state_rate_window_seconds=max(60.0, float(getattr(args, "state_rate_window_seconds", 1800.0))),
        )

    daemon_log_path = Path(args.daemon_log_path).expanduser().resolve()
    daemon_phase_path = Path(args.daemon_phase_json_path).expanduser().resolve()
    daemon_pid = _find_legal_scraper_daemon_pid()
    return _run_watch_script(daemon_log_path, daemon_phase_path, daemon_pid)


def _terminate_pid(pid: int, *, grace_seconds: float = 10.0) -> Dict[str, Any]:
    payload = {"pid": pid, "terminated": False, "signal": ""}
    try:
        os.kill(pid, signal.SIGTERM)
        payload["signal"] = "SIGTERM"
    except Exception as exc:
        payload["error"] = f"sigterm_failed: {exc}"
        return payload
    deadline = time.time() + max(0.0, grace_seconds)
    while time.time() < deadline:
        if not _pid_alive(pid):
            payload["terminated"] = True
            return payload
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
        payload["signal"] = "SIGKILL"
    except Exception as exc:
        payload["error"] = f"sigkill_failed: {exc}"
        return payload
    payload["terminated"] = not _pid_alive(pid)
    return payload


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _mark_task_complete(task: Dict[str, Any], *, note: str) -> None:
    if _normalize_status(task.get("status")) == "complete":
        return
    task["status"] = "complete"
    task["updated_at"] = utc_now()
    notes = list(task.get("notes") or [])
    if note:
        notes.append(note)
    task["notes"] = _uniq(str(item) for item in notes)


def _complete_watch_tasks_with_prefix(
    backlog: Dict[str, Any],
    *,
    prefix: str,
    active_task_ids: set[str],
    note: str,
) -> None:
    tasks = backlog.get("tasks")
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("source") or "") != "watch_status":
            continue
        task_id = str(task.get("task_id") or "").strip()
        if not task_id.startswith(prefix):
            continue
        if task_id in active_task_ids:
            continue
        _mark_task_complete(task, note=note)


def _complete_watch_task_if_inactive(
    backlog: Dict[str, Any],
    *,
    task_id: str,
    active: bool,
    note: str,
) -> None:
    if active:
        return
    task = _task_map(backlog).get(task_id)
    if isinstance(task, dict):
        _mark_task_complete(task, note=note)


def _ingest_watch_status(
    backlog: Dict[str, Any],
    watch_payload: Dict[str, Any],
    *,
    stale_after_seconds: float,
    reopen_complete: bool,
) -> Dict[str, Any]:
    mode = str(watch_payload.get("mode") or "single").strip().lower()
    if mode == "parallel":
        status = str(watch_payload.get("status") or "")
        shard_count = _safe_int(watch_payload.get("shard_count"), 0)
        healthy_count = _safe_int(watch_payload.get("healthy_shard_count"), 0)
        stale_count = _safe_int(watch_payload.get("stale_shard_count"), 0)
        dead_count = _safe_int(watch_payload.get("dead_shard_count"), 0)
        missing_phase_count = _safe_int(watch_payload.get("missing_phase_shard_count"), 0)
        stalled_state_count = _safe_int(watch_payload.get("stalled_state_count"), 0)
        high_conf_stalled_state_count = _safe_int(watch_payload.get("high_confidence_stalled_state_count"), 0)
        low_conf_inactive_state_count = _safe_int(watch_payload.get("low_confidence_inactive_state_count"), 0)
        heartbeat_age = _safe_float(watch_payload.get("heartbeat_age_seconds"), -1.0)
        shards = list(watch_payload.get("shards") or [])
        stalled_states = list(watch_payload.get("stalled_states") or [])
        daemon_pids = [int(pid) for pid in list(watch_payload.get("daemon_pids") or []) if _safe_int(pid, 0) > 0]
        active_stale_shard_task_ids: set[str] = set()
        active_dead_shard_task_ids: set[str] = set()
        active_missing_phase_task_ids: set[str] = set()
        active_state_stall_task_ids: set[str] = set()
        parallel_run_not_detected_active = status in {"missing_parallel_run_dir", "no_shards"}

        for shard in shards:
            if not isinstance(shard, dict):
                continue
            shard_name = str(shard.get("shard") or "unknown")
            shard_status = str(shard.get("status") or "")
            shard_states = _normalize_states(shard.get("states") or [])
            shard_age = _safe_float(shard.get("heartbeat_age_seconds"), -1.0)
            shard_phase_status = str(shard.get("phase_status") or "")
            if shard_status == "stale":
                task_id = f"ops:stale-daemon-heartbeat:{shard_name}"
                active_stale_shard_task_ids.add(task_id)
                _upsert_task(
                    backlog,
                    {
                        "task_id": task_id,
                        "title": f"Resolve stale legal-scraper heartbeat for {shard_name}.",
                        "status": "blocked",
                        "priority": 7,
                        "category": "ops",
                        "source": "watch_status",
                        "states": shard_states,
                        "evidence": [
                            f"shard={shard_name}",
                            f"heartbeat_age_seconds={shard_age:.1f}",
                            f"phase_status={shard_phase_status}",
                            f"phase_path={shard.get('phase_path')}",
                        ],
                    },
                    reopen_complete=reopen_complete,
                )
            elif shard_status == "dead_pid":
                task_id = f"ops:daemon-pid-dead:{shard_name}"
                active_dead_shard_task_ids.add(task_id)
                _upsert_task(
                    backlog,
                    {
                        "task_id": task_id,
                        "title": f"Restart dead legal-scraper shard daemon for {shard_name}.",
                        "status": "blocked",
                        "priority": 8,
                        "category": "ops",
                        "source": "watch_status",
                        "states": shard_states,
                        "evidence": [
                            f"shard={shard_name}",
                            f"pid={shard.get('pid')}",
                            "pid_alive=false",
                        ],
                    },
                    reopen_complete=reopen_complete,
                )
            elif shard_status == "missing_phase":
                task_id = f"ops:missing-phase:{shard_name}"
                active_missing_phase_task_ids.add(task_id)
                _upsert_task(
                    backlog,
                    {
                        "task_id": task_id,
                        "title": f"Restore phase checkpoint emission for {shard_name}.",
                        "status": "blocked",
                        "priority": 8,
                        "category": "ops",
                        "source": "watch_status",
                        "states": shard_states,
                        "evidence": [
                            f"shard={shard_name}",
                            f"output_dir={shard.get('output_dir')}",
                            "phase checkpoint missing",
                        ],
                    },
                    reopen_complete=reopen_complete,
                )

        for stalled in stalled_states[:80]:
            if not isinstance(stalled, dict):
                continue
            state = str(stalled.get("state") or "").strip().upper()
            shard_name = str(stalled.get("shard") or "unknown").strip() or "unknown"
            if len(state) != 2:
                continue
            confidence = str(stalled.get("confidence") or "").strip().lower()
            if confidence not in {"high", "medium"}:
                continue
            reason = str(stalled.get("reason") or "").strip()
            last_seen_age = _safe_float(stalled.get("last_seen_age_seconds"), -1.0)
            last_progress_age = _safe_float(stalled.get("last_progress_age_seconds"), -1.0)
            rate = stalled.get("rate_counter_per_minute")
            task_id = f"ops:state-likely-stalled:{shard_name}:{state}"
            active_state_stall_task_ids.add(task_id)
            _upsert_task(
                backlog,
                {
                    "task_id": task_id,
                    "title": f"Investigate likely stalled scraper activity for {state} on {shard_name}.",
                    "status": "blocked",
                    "priority": 6 if confidence == "high" else 7,
                    "category": "ops",
                    "source": "watch_status",
                    "states": [state],
                    "evidence": [
                        f"shard={shard_name}",
                        f"confidence={confidence}",
                        f"reason={reason}",
                        f"last_seen_age_seconds={last_seen_age:.1f}",
                        f"last_progress_age_seconds={last_progress_age:.1f}",
                        f"rate_counter_per_minute={rate}",
                        f"scraped_event_count={_safe_int(stalled.get('scraped_event_count'), 0)}",
                        f"max_counter={_safe_int(stalled.get('max_counter'), 0)}",
                    ],
                },
                reopen_complete=reopen_complete,
            )

        if parallel_run_not_detected_active:
            _upsert_task(
                backlog,
                {
                    "task_id": "ops:parallel-run-not-detected",
                    "title": "Parallel legal-scraper run directory is missing or has no shard outputs.",
                    "status": "blocked",
                    "priority": 8,
                    "category": "ops",
                    "source": "watch_status",
                    "evidence": [
                        f"status={status}",
                        f"parallel_run_dir={watch_payload.get('parallel_run_dir')}",
                    ],
                },
                reopen_complete=reopen_complete,
            )

        _complete_watch_tasks_with_prefix(
            backlog,
            prefix="ops:stale-daemon-heartbeat:",
            active_task_ids=active_stale_shard_task_ids,
            note="Auto-resolved: shard heartbeat no longer stale in latest watch status.",
        )
        _complete_watch_tasks_with_prefix(
            backlog,
            prefix="ops:daemon-pid-dead:",
            active_task_ids=active_dead_shard_task_ids,
            note="Auto-resolved: shard daemon PID is healthy in latest watch status.",
        )
        _complete_watch_tasks_with_prefix(
            backlog,
            prefix="ops:missing-phase:",
            active_task_ids=active_missing_phase_task_ids,
            note="Auto-resolved: shard phase checkpoint is present in latest watch status.",
        )
        _complete_watch_tasks_with_prefix(
            backlog,
            prefix="ops:state-likely-stalled:",
            active_task_ids=active_state_stall_task_ids,
            note="Auto-resolved: state is no longer marked stalled in latest watch status.",
        )
        _complete_watch_task_if_inactive(
            backlog,
            task_id="ops:parallel-run-not-detected",
            active=parallel_run_not_detected_active,
            note="Auto-resolved: parallel run directory and shard outputs are now detected.",
        )

        return {
            "mode": "parallel",
            "status": status,
            "phase_status": str(watch_payload.get("phase_status") or ""),
            "heartbeat_age_seconds": heartbeat_age,
            "pid_alive": bool(watch_payload.get("pid_alive")),
            "pid": None,
            "daemon_pids": daemon_pids,
            "shard_count": shard_count,
            "healthy_shard_count": healthy_count,
            "stale_shard_count": stale_count,
            "dead_shard_count": dead_count,
            "missing_phase_shard_count": missing_phase_count,
            "stalled_state_count": stalled_state_count,
            "high_confidence_stalled_state_count": high_conf_stalled_state_count,
            "low_confidence_inactive_state_count": low_conf_inactive_state_count,
            "stalled_states": stalled_states,
            "parallel_run_dir": str(watch_payload.get("parallel_run_dir") or ""),
            "shards": shards,
        }

    status = str(watch_payload.get("status") or "")
    phase_status = str(watch_payload.get("phase_status") or "")
    heartbeat_age = _safe_float(watch_payload.get("heartbeat_age_seconds"), -1.0)
    pid_alive = bool(watch_payload.get("pid_alive"))
    daemon_pid = _safe_int(watch_payload.get("pid"), 0)

    output = {
        "mode": "single",
        "status": status,
        "phase_status": phase_status,
        "heartbeat_age_seconds": heartbeat_age,
        "pid_alive": pid_alive,
        "pid": daemon_pid or None,
    }

    if status == "missing_log":
        _upsert_task(
            backlog,
            {
                "task_id": "ops:missing-daemon-log",
                "title": "Restore daemon logging path so supervisor can monitor progress.",
                "status": "blocked",
                "priority": 8,
                "category": "ops",
                "source": "watch_status",
                "evidence": ["watch_legal_scraper_daemon reported missing_log"],
            },
            reopen_complete=reopen_complete,
        )

    if heartbeat_age >= 0 and heartbeat_age > stale_after_seconds:
        _upsert_task(
            backlog,
            {
                "task_id": "ops:stale-daemon-heartbeat",
                "title": "Resolve stale legal-scraper heartbeat (daemon appears stalled).",
                "status": "blocked",
                "priority": 7,
                "category": "ops",
                "source": "watch_status",
                "evidence": [
                    f"heartbeat_age_seconds={heartbeat_age:.1f}",
                    f"stale_after_seconds={stale_after_seconds:.1f}",
                    f"phase_status={phase_status}",
                ],
                "commands": [
                    "python3 scripts/ops/legal_data/watch_legal_scraper_daemon.py --log ~/.ipfs_datasets/legal_scraper_daemon/daemon.log --phase-json ~/.ipfs_datasets/legal_scraper_daemon/state_refresh_phase.json --json",
                ],
            },
            reopen_complete=reopen_complete,
        )

    if daemon_pid and not pid_alive:
        _upsert_task(
            backlog,
            {
                "task_id": "ops:daemon-pid-dead",
                "title": "Daemon PID is no longer alive; restart or recover from checkpoint.",
                "status": "blocked",
                "priority": 9,
                "category": "ops",
                "source": "watch_status",
                "evidence": [f"daemon_pid={daemon_pid}", "pid_alive=false"],
            },
            reopen_complete=reopen_complete,
        )

    return output


def _extract_json_object(text: str) -> Dict[str, Any]:
    candidates: List[str] = []
    fenced = re.findall(r"```json\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    candidates.extend(fenced)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _llm_rewrite_prompt(task: Dict[str, Any], coverage_metrics: Dict[str, Any]) -> str:
    title = str(task.get("title") or "").strip()
    category = str(task.get("category") or "").strip()
    states = ", ".join(_normalize_states(task.get("states") or [])) or "none"
    evidence = "\n".join(f"- {item}" for item in list(task.get("evidence") or [])[:12])
    commands = "\n".join(f"- {item}" for item in list(task.get("commands") or [])[:8])
    metrics_text = json.dumps(coverage_metrics, indent=2, sort_keys=True)
    return f"""
You are a legal-data scraper supervisor generating a concrete code-rewrite plan.

Task:
- title: {title}
- category: {category}
- states: {states}

Evidence:
{evidence or "- none"}

Existing commands:
{commands or "- none"}

Coverage metrics snapshot:
{metrics_text}

Return STRICT JSON only with this shape:
{{
  "summary": "one-paragraph plan",
  "files": [
    {{"path": "relative/path.py", "change": "what to edit and why"}}
  ],
  "tests": ["exact test commands"],
  "commands": ["exact run commands for daemon/supervisor remediation"],
  "risk_notes": ["short risk bullets"]
}}
"""


def _maybe_generate_llm_rewrite_plans(
    backlog: Dict[str, Any],
    *,
    limit: int,
    provider: str,
    model: str,
    max_tokens: int,
) -> Dict[str, Any]:
    if limit <= 0:
        return {"enabled": False, "planned": 0, "errors": []}
    try:
        from ipfs_datasets_py import llm_router  # type: ignore
    except Exception as exc:
        return {"enabled": True, "planned": 0, "errors": [f"llm_router_unavailable: {exc}"]}

    tasks = [task for task in backlog.get("tasks", []) if isinstance(task, dict)]
    candidates = [
        task
        for task in tasks
        if _normalize_status(task.get("status")) != "complete"
        and not isinstance(task.get("llm_rewrite_plan"), dict)
    ]
    candidates.sort(key=lambda item: (_safe_int(item.get("priority"), 99), STATUS_ORDER.get(_normalize_status(item.get("status")), 99)))
    selected = candidates[:limit]
    planned = 0
    errors: List[str] = []

    metrics = backlog.get("metrics") if isinstance(backlog.get("metrics"), dict) else {}
    for task in selected:
        prompt = _llm_rewrite_prompt(task, metrics)
        try:
            kwargs: Dict[str, Any] = {"max_new_tokens": max(128, int(max_tokens))}
            response = llm_router.generate_text(
                prompt,
                provider=(provider or None),
                model_name=(model or None),
                **kwargs,
            )
            parsed = _extract_json_object(str(response or ""))
            if not parsed:
                raise RuntimeError("router returned non-JSON rewrite plan")
            task["llm_rewrite_plan"] = parsed
            notes = list(task.get("notes") or [])
            notes.append(f"llm_rewrite_plan_generated_at={utc_now()}")
            task["notes"] = _uniq(notes)
            task["updated_at"] = utc_now()
            planned += 1
        except Exception as exc:
            errors.append(f"{task.get('task_id')}: {exc}")

    if planned > 0:
        _update_history(backlog, "llm_rewrite_plans_generated", {"count": planned})
    return {"enabled": True, "planned": planned, "errors": errors}


def _backlog_counts(backlog: Dict[str, Any]) -> Dict[str, int]:
    counts = {"needed": 0, "in-progress": 0, "blocked": 0, "complete": 0}
    for task in backlog.get("tasks", []):
        if not isinstance(task, dict):
            continue
        status = _normalize_status(task.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _task_sort_key(task: Dict[str, Any]) -> Tuple[int, int, str]:
    status = _normalize_status(task.get("status"))
    priority = _safe_int(task.get("priority"), 50)
    title = str(task.get("title") or "")
    return (STATUS_ORDER.get(status, 99), priority, title.lower())


def _render_markdown(backlog: Dict[str, Any]) -> str:
    counts = _backlog_counts(backlog)
    metrics = backlog.get("metrics") if isinstance(backlog.get("metrics"), dict) else {}
    lines: List[str] = []
    lines.append("# Legal Scraper Coverage Task Board")
    lines.append("")
    lines.append(f"Updated: {utc_now()}")
    lines.append("")
    lines.append("## Goal")
    lines.append("- Reach and sustain 100% legal corpus coverage and high normalization quality before publish.")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- Task counts: `{json.dumps(counts, sort_keys=True)}`")
    if metrics:
        lines.append(f"- Metrics: `{json.dumps(metrics, sort_keys=True)}`")
    lines.append("")
    lines.append("## Tasks")
    tasks = [task for task in backlog.get("tasks", []) if isinstance(task, dict)]
    tasks.sort(key=_task_sort_key)
    for index, task in enumerate(tasks, start=1):
        status = _normalize_status(task.get("status"))
        mark = STATUS_TO_MARK.get(status, " ")
        title = str(task.get("title") or "").strip()
        task_id = str(task.get("task_id") or f"task-{index}")
        priority = _safe_int(task.get("priority"), 50)
        source = str(task.get("source") or "supervisor").strip()
        states = ",".join(_normalize_states(task.get("states") or []))
        lines.append(
            f"- [{mark}] Task checkbox-{index}: {title} "
            f"<!-- id:{task_id} priority:{priority} source:{source} states:{states} -->"
        )
        evidence = list(task.get("evidence") or [])
        if evidence:
            lines.append(f"  evidence: {evidence[0]}")
        commands = list(task.get("commands") or [])
        if commands:
            lines.append(f"  command: `{commands[0]}`")
        if isinstance(task.get("llm_rewrite_plan"), dict):
            lines.append("  llm_rewrite_plan: ready")
    lines.append("")
    return "\n".join(lines)


def _auto_resolve_report_path(explicit: str, glob_pattern: str, output_dir: Path) -> Optional[Path]:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        return candidate if candidate.exists() else None
    candidates = sorted(output_dir.glob(glob_pattern), reverse=True)
    return candidates[0] if candidates else None


def _collect_metrics(
    retry: Dict[str, Any],
    law_gaps: Dict[str, Any],
    admin_page_gaps: Dict[str, Any],
    admin_deep: Dict[str, Any],
    watch_status: Dict[str, Any],
) -> Dict[str, Any]:
    daemon_pids = [int(pid) for pid in list(watch_status.get("daemon_pids") or []) if _safe_int(pid, 0) > 0]
    return {
        "retry_phase_count": _safe_int(retry.get("retry_phase_count"), 0),
        "retry_state_count": len(_normalize_states(retry.get("retry_states") or [])),
        "state_law_weak_state_count": len(_normalize_states(law_gaps.get("weak_states") or [])),
        "state_law_avg_real_ratio": round(_safe_float(law_gaps.get("avg_real_ratio"), 0.0), 4),
        "state_law_rows_total": _safe_int(law_gaps.get("rows_total"), 0),
        "state_law_real_total": _safe_int(law_gaps.get("real_total"), 0),
        "state_law_synthetic_total": _safe_int(law_gaps.get("synthetic_total"), 0),
        "admin_weak_state_count": len(_normalize_states(admin_page_gaps.get("weak_states") or [])),
        "admin_blocked_pages_total": _safe_int(admin_page_gaps.get("blocked_pages_total"), 0),
        "admin_candidate_substantive_pages_total": _safe_int(admin_page_gaps.get("candidate_substantive_pages_total"), 0),
        "admin_deep_gap_state_count": len(_normalize_states(admin_deep.get("gap_states") or [])),
        "daemon_status": str(watch_status.get("status") or ""),
        "daemon_mode": str(watch_status.get("mode") or "single"),
        "daemon_phase_status": str(watch_status.get("phase_status") or ""),
        "daemon_heartbeat_age_seconds": _safe_float(watch_status.get("heartbeat_age_seconds"), -1.0),
        "daemon_pid_alive": bool(watch_status.get("pid_alive")),
        "daemon_pid_count": len(daemon_pids),
        "parallel_shard_count": _safe_int(watch_status.get("shard_count"), 0),
        "parallel_healthy_shard_count": _safe_int(watch_status.get("healthy_shard_count"), 0),
        "parallel_stale_shard_count": _safe_int(watch_status.get("stale_shard_count"), 0),
        "parallel_dead_shard_count": _safe_int(watch_status.get("dead_shard_count"), 0),
        "parallel_missing_phase_shard_count": _safe_int(watch_status.get("missing_phase_shard_count"), 0),
        "parallel_stalled_state_count": _safe_int(watch_status.get("stalled_state_count"), 0),
        "parallel_high_confidence_stalled_state_count": _safe_int(watch_status.get("high_confidence_stalled_state_count"), 0),
        "parallel_low_confidence_inactive_state_count": _safe_int(watch_status.get("low_confidence_inactive_state_count"), 0),
    }


def update_backlog_once(args: argparse.Namespace) -> Dict[str, Any]:
    backlog_path = Path(args.backlog_json).expanduser().resolve()
    markdown_path = Path(args.backlog_markdown).expanduser().resolve()
    status_path = Path(args.status_json).expanduser().resolve()
    daemon_output_dir = Path(args.daemon_output_dir).expanduser().resolve()

    retry_path = _auto_resolve_report_path(args.retry_manifest_path, "latest_full_corpus_retry.json", daemon_output_dir)
    law_gap_path = _auto_resolve_report_path(args.state_law_page_gap_report_path, "state_law_page_gap_report*.json", REPO_ROOT / "artifacts")
    admin_gap_path = _auto_resolve_report_path(
        args.state_admin_page_gap_report_path,
        "state_admin_rules/state_admin_webarch_page_gap_report_pagequal_*.json",
        REPO_ROOT / "artifacts",
    )
    admin_deep_path = _auto_resolve_report_path(
        args.state_admin_deep_summary_path,
        "state_admin_rules/webarch_gap_audit_agentic_deep_*/summary.json",
        REPO_ROOT / "artifacts",
    )

    payload = _ensure_backlog_shape(_read_json(backlog_path))
    _seed_core_tasks(payload, reopen_complete=bool(args.reopen_complete_tasks))

    retry = _ingest_retry_manifest(payload, retry_path, reopen_complete=bool(args.reopen_complete_tasks)) if retry_path else {"found": False}
    law_gaps = (
        _ingest_state_law_page_gap_report(payload, law_gap_path, reopen_complete=bool(args.reopen_complete_tasks))
        if law_gap_path
        else {"found": False}
    )
    admin_page_gaps = (
        _ingest_state_admin_page_gap_report(payload, admin_gap_path, reopen_complete=bool(args.reopen_complete_tasks))
        if admin_gap_path
        else {"found": False}
    )
    admin_deep = (
        _ingest_state_admin_deep_summary(payload, admin_deep_path, reopen_complete=bool(args.reopen_complete_tasks))
        if admin_deep_path
        else {"found": False}
    )

    watch_payload = _collect_watch_payload(args)
    watch_status = _ingest_watch_status(
        payload,
        watch_payload,
        stale_after_seconds=float(args.stale_heartbeat_seconds),
        reopen_complete=bool(args.reopen_complete_tasks),
    )

    payload["metrics"] = _collect_metrics(retry, law_gaps, admin_page_gaps, admin_deep, watch_status)

    llm_plans = _maybe_generate_llm_rewrite_plans(
        payload,
        limit=max(0, int(args.llm_rewrite_limit)),
        provider=str(args.llm_provider or "").strip(),
        model=str(args.llm_model or "").strip(),
        max_tokens=max(128, int(args.llm_max_tokens)),
    )

    payload["generated_at"] = utc_now()
    payload["task_counts"] = _backlog_counts(payload)

    _write_json(backlog_path, payload)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")

    status_payload = {
        "schema": "ipfs_datasets_py.legal_scraper.todo_supervisor.status.v1",
        "generated_at": utc_now(),
        "backlog_json": str(backlog_path),
        "backlog_markdown": str(markdown_path),
        "retry_manifest_path": str(retry_path) if retry_path else "",
        "state_law_page_gap_report_path": str(law_gap_path) if law_gap_path else "",
        "state_admin_page_gap_report_path": str(admin_gap_path) if admin_gap_path else "",
        "state_admin_deep_summary_path": str(admin_deep_path) if admin_deep_path else "",
        "watch": watch_status,
        "metrics": payload.get("metrics", {}),
        "task_counts": payload.get("task_counts", {}),
        "llm_rewrite_plans": llm_plans,
    }
    _write_json(status_path, status_payload)
    return status_payload


def _spawn_daemon_command(command: str, *, cwd: Path, log_path: Path) -> Dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=str(cwd),
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    return {"pid": proc.pid, "command": command}


def supervise_loop(args: argparse.Namespace) -> int:
    interval_seconds = max(1.0, float(args.interval_seconds))
    max_iterations = max(0, int(args.max_iterations))
    daemon_command = str(args.daemon_command or "").strip()
    launched_pid: Optional[int] = None

    iteration = 0
    while True:
        iteration += 1

        running_pids = _find_legal_scraper_daemon_pids()
        running_pid = running_pids[0] if running_pids else None
        is_parallel_mode = bool(str(getattr(args, "parallel_run_dir", "") or "").strip())
        if running_pid is None and daemon_command and bool(args.start_daemon_if_missing) and not is_parallel_mode:
            launch = _spawn_daemon_command(
                daemon_command,
                cwd=REPO_ROOT,
                log_path=Path(args.supervisor_log_path).expanduser().resolve(),
            )
            launched_pid = _safe_int(launch.get("pid"), 0) or None
            time.sleep(2.0)
            running_pid = _find_legal_scraper_daemon_pid()

        status_payload = update_backlog_once(args)
        metrics = status_payload.get("metrics") if isinstance(status_payload.get("metrics"), dict) else {}
        stale_age = _safe_float(metrics.get("daemon_heartbeat_age_seconds"), -1.0)
        stale_cutoff = max(1.0, float(args.stale_heartbeat_seconds))
        daemon_mode = str(metrics.get("daemon_mode") or "single").strip().lower()

        if (
            running_pid
            and stale_age >= 0
            and stale_age > stale_cutoff
            and daemon_command
            and bool(args.restart_stale_daemon)
            and daemon_mode != "parallel"
        ):
            _terminate_pid(running_pid, grace_seconds=max(1.0, float(args.stop_grace_seconds)))
            launch = _spawn_daemon_command(
                daemon_command,
                cwd=REPO_ROOT,
                log_path=Path(args.supervisor_log_path).expanduser().resolve(),
            )
            launched_pid = _safe_int(launch.get("pid"), 0) or None
            status_payload = update_backlog_once(args)

        if args.json:
            print(json.dumps({"iteration": iteration, "status": status_payload}, sort_keys=True))
        else:
            counts = status_payload.get("task_counts") if isinstance(status_payload.get("task_counts"), dict) else {}
            print(
                f"[legal_scraper_todo_supervisor] iteration={iteration} "
                f"task_counts={json.dumps(counts, sort_keys=True)} "
                f"daemon_mode={metrics.get('daemon_mode')} "
                f"shards={metrics.get('parallel_shard_count')} "
                f"heartbeat_age={metrics.get('daemon_heartbeat_age_seconds')} "
                f"daemon_pid_alive={metrics.get('daemon_pid_alive')}"
            )

        if max_iterations and iteration >= max_iterations:
            break
        time.sleep(interval_seconds)

    if launched_pid and not _pid_alive(launched_pid):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    default_daemon_dir = str(Path.home() / ".ipfs_datasets" / "legal_scraper_daemon")
    default_supervisor_dir = str(Path.home() / ".ipfs_datasets" / "legal_scraper_supervisor")

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--daemon-output-dir", default=default_daemon_dir, help="Directory with legal scraper daemon artifacts.")
        p.add_argument(
            "--parallel-run-dir",
            default="",
            help="Optional parallel run directory; when set, monitor shard outputs under this directory instead of a single daemon log.",
        )
        p.add_argument(
            "--parallel-output-glob",
            default="shard*/output",
            help="Glob under --parallel-run-dir that resolves shard output directories.",
        )
        p.add_argument(
            "--parallel-phase-filename",
            default="state_refresh_phase.json",
            help="Phase filename to resolve under each shard cycle directory.",
        )
        p.add_argument("--backlog-json", default=f"{default_supervisor_dir}/legal_scraper_todo.json")
        p.add_argument("--backlog-markdown", default=f"{default_supervisor_dir}/legal_scraper_todo.md")
        p.add_argument("--status-json", default=f"{default_supervisor_dir}/legal_scraper_todo_supervisor.status.json")
        p.add_argument("--retry-manifest-path", default="", help="Override retry-manifest path.")
        p.add_argument("--state-law-page-gap-report-path", default="", help="Override state-law page-gap report path.")
        p.add_argument("--state-admin-page-gap-report-path", default="", help="Override admin page-gap report path.")
        p.add_argument("--state-admin-deep-summary-path", default="", help="Override deep admin gap summary path.")
        p.add_argument("--daemon-log-path", default=f"{default_daemon_dir}/daemon.log")
        p.add_argument("--daemon-phase-json-path", default=f"{default_daemon_dir}/state_refresh_phase.json")
        p.add_argument("--stale-heartbeat-seconds", type=float, default=180.0)
        p.add_argument(
            "--state-stall-seconds",
            type=float,
            default=3600.0,
            help="Likely-stall threshold (seconds) for per-state rate/activity analytics.",
        )
        p.add_argument(
            "--state-rate-window-seconds",
            type=float,
            default=1800.0,
            help="Window (seconds) used when estimating per-state progress rates from log counters.",
        )
        p.add_argument("--reopen-complete-tasks", action="store_true", help="Allow ingestion to reopen completed tasks when gaps reappear.")
        p.add_argument("--llm-provider", default="", help="Optional llm_router provider override.")
        p.add_argument("--llm-model", default="", help="Optional llm_router model override.")
        p.add_argument("--llm-max-tokens", type=int, default=800, help="Max token budget for llm_router rewrite-plan generation.")
        p.add_argument("--llm-rewrite-limit", type=int, default=0, help="Generate rewrite plans for up to N open tasks per pass.")
        p.add_argument("--json", action="store_true")

    update = sub.add_parser("update", help="Run one backlog update pass from daemon + coverage artifacts.")
    add_common_args(update)

    supervise = sub.add_parser("supervise", help="Continuously monitor and refresh the backlog in a supervisor loop.")
    add_common_args(supervise)
    supervise.add_argument("--interval-seconds", type=float, default=60.0)
    supervise.add_argument("--max-iterations", type=int, default=0, help="0 means run forever.")
    supervise.add_argument("--daemon-command", default="", help="Optional daemon command to launch when missing, via `bash -lc`.")
    supervise.add_argument("--start-daemon-if-missing", action="store_true")
    supervise.add_argument("--restart-stale-daemon", action="store_true")
    supervise.add_argument("--stop-grace-seconds", type=float, default=10.0)
    supervise.add_argument("--supervisor-log-path", default=f"{default_supervisor_dir}/supervisor.log")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "update":
        payload = update_backlog_once(args)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "supervise":
        return supervise_loop(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
