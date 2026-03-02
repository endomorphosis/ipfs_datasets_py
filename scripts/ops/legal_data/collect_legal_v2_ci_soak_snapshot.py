#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DayStatus:
    day: str
    run_count: int
    success_count: int
    blocker_count: int
    is_green: bool


def _parse_iso_day(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.date().isoformat()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fetch_workflow_runs(owner: str, repo: str, workflow: str, per_page: int, token: str | None) -> Dict[str, Any]:
    url = (
        f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/runs"
        f"?per_page={per_page}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "legal-v2-ci-soak-snapshot",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:
        raise SystemExit(f"GitHub API HTTP error: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise SystemExit(f"GitHub API URL error: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to decode GitHub API JSON: {exc}") from exc


def _build_day_statuses(workflow_runs: Iterable[Dict[str, Any]]) -> List[DayStatus]:
    per_day: Dict[str, Dict[str, int]] = {}
    for run in workflow_runs:
        if str(run.get("status") or "") != "completed":
            continue
        day = _parse_iso_day(str(run.get("created_at") or ""))
        if not day:
            continue
        conclusion = str(run.get("conclusion") or "")
        bucket = per_day.setdefault(day, {"run_count": 0, "success_count": 0, "blocker_count": 0})
        bucket["run_count"] += 1
        if conclusion == "success":
            bucket["success_count"] += 1
        else:
            bucket["blocker_count"] += 1

    out: List[DayStatus] = []
    for day in sorted(per_day.keys(), reverse=True):
        bucket = per_day[day]
        is_green = bucket["success_count"] >= 1 and bucket["blocker_count"] == 0
        out.append(
            DayStatus(
                day=day,
                run_count=bucket["run_count"],
                success_count=bucket["success_count"],
                blocker_count=bucket["blocker_count"],
                is_green=is_green,
            )
        )
    return out


def _compute_consecutive_green_streak(day_statuses: List[DayStatus], as_of_day: str) -> int:
    lookup = {item.day: item for item in day_statuses}
    streak = 0
    cursor = date.fromisoformat(as_of_day)
    while True:
        key = cursor.isoformat()
        item = lookup.get(key)
        if item is None or not item.is_green:
            break
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def _render_markdown(summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Legal V2 CI Soak Summary")
    lines.append("")
    lines.append(f"- as_of_day: `{summary['as_of_day']}`")
    lines.append(f"- consecutive_green_days: `{summary['consecutive_green_days']}`")
    lines.append(f"- target_days: `{summary['target_days']}`")
    lines.append(f"- target_met: `{str(summary['target_met']).lower()}`")
    lines.append(f"- total_runs_fetched: `{summary['total_runs_fetched']}`")
    lines.append("")

    latest = summary.get("latest_run") or {}
    if latest:
        lines.append("## Latest Run")
        lines.append("")
        lines.append(f"- conclusion: `{latest.get('conclusion', '')}`")
        lines.append(f"- created_at: `{latest.get('created_at', '')}`")
        lines.append(f"- url: `{latest.get('html_url', '')}`")
        lines.append("")

    lines.append("## Per-Day Status")
    lines.append("")
    per_day = summary.get("per_day") or []
    if not per_day:
        lines.append("- none")
    else:
        for item in per_day:
            lines.append(
                "- "
                f"`{item['day']}` "
                f"runs={item['run_count']} "
                f"success={item['success_count']} "
                f"blockers={item['blocker_count']} "
                f"green={str(item['is_green']).lower()}"
            )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    today_utc = datetime.now(timezone.utc).date().isoformat()

    ap = argparse.ArgumentParser(description="Collect Legal V2 CI soak snapshot and compute consecutive green streak")
    ap.add_argument("--owner", default="endomorphosis")
    ap.add_argument("--repo", default="ipfs_datasets_py")
    ap.add_argument("--workflow", default="legal-v2-reasoner-ci.yml")
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--target-days", type=int, default=7)
    ap.add_argument("--as-of-day", default=today_utc)
    ap.add_argument("--token-env", default="GITHUB_TOKEN")
    ap.add_argument("--input-runs-json", default="")
    ap.add_argument("--raw-output", required=True)
    ap.add_argument("--summary-output", required=True)
    ap.add_argument("--markdown-output", required=True)
    args = ap.parse_args()

    raw_output = Path(args.raw_output)
    summary_output = Path(args.summary_output)
    markdown_output = Path(args.markdown_output)

    if args.input_runs_json:
        payload = json.loads(Path(args.input_runs_json).read_text(encoding="utf-8"))
    else:
        token = None
        if args.token_env:
            import os

            token = os.environ.get(args.token_env) or None
        payload = _fetch_workflow_runs(
            owner=args.owner,
            repo=args.repo,
            workflow=args.workflow,
            per_page=args.per_page,
            token=token,
        )

    _write_json(raw_output, payload)

    workflow_runs = list(payload.get("workflow_runs") or [])
    day_statuses = _build_day_statuses(workflow_runs)
    streak = _compute_consecutive_green_streak(day_statuses, args.as_of_day)

    latest_run = workflow_runs[0] if workflow_runs else {}
    summary: Dict[str, Any] = {
        "owner": args.owner,
        "repo": args.repo,
        "workflow": args.workflow,
        "as_of_day": args.as_of_day,
        "target_days": args.target_days,
        "consecutive_green_days": streak,
        "target_met": streak >= args.target_days,
        "total_runs_fetched": len(workflow_runs),
        "latest_run": {
            "conclusion": latest_run.get("conclusion"),
            "created_at": latest_run.get("created_at"),
            "html_url": latest_run.get("html_url"),
        }
        if latest_run
        else {},
        "per_day": [
            {
                "day": item.day,
                "run_count": item.run_count,
                "success_count": item.success_count,
                "blocker_count": item.blocker_count,
                "is_green": item.is_green,
            }
            for item in day_statuses
        ],
    }

    _write_json(summary_output, summary)
    _write_text(markdown_output, _render_markdown(summary))

    print(f"raw_output={raw_output}")
    print(f"summary_output={summary_output}")
    print(f"markdown_output={markdown_output}")
    print(f"consecutive_green_days={streak}")
    print(f"target_met={str(summary['target_met']).lower()}")


if __name__ == "__main__":
    main()
