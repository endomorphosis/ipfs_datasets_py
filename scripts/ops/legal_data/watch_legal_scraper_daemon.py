#!/usr/bin/env python3
"""Summarize a long-running legal scraper daemon from its log/checkpoint files."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any


STATE_START_RE = re.compile(r"\.([A-Z]{2})\] Scraping \d+ codes? for ([^\n]+)")
CODE_START_RE = re.compile(r"\.([A-Z]{2})\] Scraping (.+?)\.\.\.")
SCRAPED_RE = re.compile(r"\.([A-Z]{2})\] Scraped (\d+) statutes from (.+)")
INCREMENTAL_RE = re.compile(r"\[state_laws_refresh\] incremental_publish state=([A-Z]{2}) stage=([a-z_]+)")
KRS_PROGRESS_RE = re.compile(
    r"Kentucky KRS (?P<event>chapter start|chapter discovered sections|section progress|chapter done): (?P<detail>.*)"
)
KEY_VALUE_RE = re.compile(r"(\w+)=([^=]+?)(?=\s+\w+=|$)")


def _tail_text(path: Path, *, bytes_to_read: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        try:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - bytes_to_read), os.SEEK_SET)
        except OSError:
            handle.seek(0)
        return handle.read().decode("utf-8", errors="replace")


def _parse_kv_detail(detail: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for match in KEY_VALUE_RE.finditer(str(detail or "")):
        parsed[match.group(1)] = " ".join(match.group(2).strip().split())
    return parsed


def _pid_alive(pid: int | None) -> bool | None:
    if not pid:
        return None
    return Path(f"/proc/{pid}").exists()


def summarize(log_path: Path, *, phase_path: Path | None = None, pid: int | None = None, tail_bytes: int = 1_000_000) -> dict[str, Any]:
    text = _tail_text(log_path, bytes_to_read=max(4096, int(tail_bytes)))
    lines = [line for line in text.splitlines() if line.strip()]
    latest: dict[str, Any] = {}
    state_counts: dict[str, int] = {}
    incremental: dict[str, str] = {}
    current_state = ""
    current_code = ""

    for line in lines:
        match = STATE_START_RE.search(line)
        if match:
            current_state = match.group(1)
            latest["state_start"] = {"state": current_state, "state_name": match.group(2), "line": line}
        match = CODE_START_RE.search(line)
        if match:
            current_state = match.group(1)
            current_code = match.group(2)
            latest["code_start"] = {"state": current_state, "code": current_code, "line": line}
        match = SCRAPED_RE.search(line)
        if match:
            state = match.group(1)
            count = int(match.group(2))
            state_counts[state] = count
            latest["scraped"] = {"state": state, "count": count, "code": match.group(3), "line": line}
        match = INCREMENTAL_RE.search(line)
        if match:
            incremental[match.group(1)] = match.group(2)
            latest["incremental_publish"] = {
                "state": match.group(1),
                "stage": match.group(2),
                "line": line,
            }
        match = KRS_PROGRESS_RE.search(line)
        if match:
            detail = _parse_kv_detail(match.group("detail"))
            current_state = "KY"
            latest["kentucky_krs"] = {
                "event": match.group("event"),
                "detail": detail,
                "line": line,
            }

    phase: dict[str, Any] = {}
    if phase_path and phase_path.exists():
        try:
            phase = json.loads(phase_path.read_text(encoding="utf-8"))
        except Exception as exc:
            phase = {"error": str(exc)}

    now = time.time()
    log_mtime = log_path.stat().st_mtime if log_path.exists() else 0.0
    phase_mtime = phase_path.stat().st_mtime if phase_path and phase_path.exists() else 0.0
    heartbeat_age = max(0.0, now - phase_mtime) if phase_mtime else None
    log_age = max(0.0, now - log_mtime) if log_mtime else None

    return {
        "status": "ok" if log_path.exists() else "missing_log",
        "pid": pid,
        "pid_alive": _pid_alive(pid),
        "log_path": str(log_path),
        "phase_path": str(phase_path) if phase_path else "",
        "log_age_seconds": round(log_age, 1) if log_age is not None else None,
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "phase_status": phase.get("status"),
        "phase_message": phase.get("message"),
        "phase_heartbeat_count": phase.get("heartbeat_count"),
        "current_state": current_state,
        "current_code": current_code,
        "latest": latest,
        "state_counts": state_counts,
        "incremental_publish": incremental,
        "tail_line_count": len(lines),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="Daemon log path")
    parser.add_argument("--phase-json", default="", help="Optional state_refresh_phase.json path")
    parser.add_argument("--pid", type=int, default=0, help="Optional daemon PID")
    parser.add_argument("--tail-bytes", type=int, default=1_000_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = summarize(
        Path(args.log),
        phase_path=Path(args.phase_json) if args.phase_json else None,
        pid=int(args.pid or 0) or None,
        tail_bytes=int(args.tail_bytes),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
        krs = latest.get("kentucky_krs") if isinstance(latest.get("kentucky_krs"), dict) else {}
        print(
            "status={status} pid_alive={pid_alive} phase={phase_status} "
            "heartbeat_age={heartbeat_age_seconds}s log_age={log_age_seconds}s".format(**payload)
        )
        if krs:
            print(f"kentucky_krs event={krs.get('event')} detail={krs.get('detail')}")
        elif latest.get("scraped"):
            print(f"scraped={latest.get('scraped')}")
        elif latest.get("code_start"):
            print(f"code_start={latest.get('code_start')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
