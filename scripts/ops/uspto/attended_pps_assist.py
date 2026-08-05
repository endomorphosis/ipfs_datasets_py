#!/usr/bin/env python3
"""Attended Patent Public Search (PPS) assist — open browser + show checklist.

Opens the public PPS web app for **human** interactive verification of prior-art
queries. Prints the checklist queries so the operator can paste/run them.

Hard rules
----------
* Never automates search submission, result scraping, or login on PPS.
* Never claims PPS is a public API.
* Never asserts novelty/patentability.
* Optional Playwright open is view-only navigation to the PPS landing URL.

Usage:
  python3 scripts/ops/uspto/attended_pps_assist.py \\
    --run-dir ~/.local/state/.../prior_art/18654466/run-… \\
    --watch-seconds 300
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (  # noqa: E402
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (  # noqa: E402
    PPS_DISCLAIMER,
    PPS_PUBLIC_URL,
    build_pps_verification_checklist,
    persist_pps_checklist,
)

# Labels we refuse to auto-click if anything ever tried to automate PPS.
_FORBIDDEN_PPS_CLICKS = frozenset(
    {
        "search",
        "submit",
        "sign in",
        "login",
        "log in",
        "export",
        "download all",
    }
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Attended PPS assist: open Patent Public Search landing page and "
            "print verification checklist. Never scrapes or auto-searches."
        )
    )
    p.add_argument("--state-root", default="")
    p.add_argument("--application-number", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--run-dir", default="")
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Print checklist only (do not open Playwright)",
    )
    p.add_argument("--headless", action="store_true")
    p.add_argument(
        "--watch-seconds",
        type=float,
        default=300.0,
        help="Seconds to keep browser open for human work (default 300)",
    )
    p.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def _resolve_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir:
        return Path(args.run_dir).expanduser().resolve()
    state = (
        Path(args.state_root).expanduser().resolve()
        if args.state_root
        else default_state_root()
    )
    if args.run_id and args.application_number:
        return (
            state
            / "prior_art"
            / str(args.application_number).strip()
            / str(args.run_id).strip()
        )
    raise PortfolioAutomationError(
        "pass --run-dir or --run-id + --application-number",
        code="missing_run_dir",
    )


def _load_or_build_checklist(run_dir: Path, application_number: str) -> dict[str, Any]:
    checklist_path = run_dir / "pps_verification_checklist.json"
    if checklist_path.is_file():
        return json.loads(checklist_path.read_text(encoding="utf-8"))
    plan_path = run_dir / "prior_art_plan.json"
    if not plan_path.is_file():
        raise PortfolioAutomationError(
            f"missing plan and checklist in {run_dir}",
            code="plan_missing",
        )
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        PriorArtSearchPlan,
    )

    plan = PriorArtSearchPlan.from_dict(
        json.loads(plan_path.read_text(encoding="utf-8"))
    )
    checklist = build_pps_verification_checklist(
        plan,
        application_number=application_number,
        run_id=run_dir.name,
    )
    persist_pps_checklist(checklist, run_dir)
    return checklist


def _open_pps_browser(*, headless: bool, watch_seconds: float) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortfolioAutomationError(
            "playwright required (pip install playwright && playwright install chromium)",
            code="playwright_missing",
        ) from exc

    if not headless and not os.environ.get("DISPLAY"):
        headless = True

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(headless))
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        # View-only: navigate to landing URL. Do not fill search boxes or click Search.
        page.goto(PPS_PUBLIC_URL, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.evaluate(
                """() => {
                  if (document.getElementById('patlaw-pps-banner')) return;
                  const d = document.createElement('div');
                  d.id = 'patlaw-pps-banner';
                  d.textContent = 'PATLAW PPS ASSIST: YOU run searches interactively. Automation will not search or scrape results.';
                  Object.assign(d.style, {
                    position: 'fixed', top: '0', left: '0', right: '0', zIndex: '2147483647',
                    background: '#1f4b7a', color: '#fff', padding: '10px 16px',
                    font: '600 14px/1.3 system-ui,sans-serif', textAlign: 'center'
                  });
                  document.body.appendChild(d);
                  document.body.style.paddingTop = '42px';
                }"""
            )
        except Exception:
            pass
        # Hold for human work; never automate search.
        deadline = time.time() + max(0.0, float(watch_seconds))
        while time.time() < deadline:
            time.sleep(1.0)
            if page.is_closed():
                break
        final_url = page.url
        browser.close()
    return {
        "opened_url": PPS_PUBLIC_URL,
        "final_url": final_url,
        "watch_seconds": watch_seconds,
        "automated_search": False,
        "scraped_results": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run_dir = _resolve_run_dir(args)
        if not run_dir.is_dir():
            raise PortfolioAutomationError(
                f"run_dir not found: {run_dir}", code="run_not_found"
            )
        checklist = _load_or_build_checklist(
            run_dir, str(args.application_number or "")
        )
        browser_info: dict[str, Any] | None = None
        if not args.no_browser:
            browser_info = _open_pps_browser(
                headless=bool(args.headless),
                watch_seconds=float(args.watch_seconds),
            )

        # Operator-facing summary of queries to run by hand
        pending = [
            {
                "query_id": it.get("query_id"),
                "pps_hint": it.get("pps_hint") or it.get("query_text"),
                "status": it.get("status"),
            }
            for it in (checklist.get("items") or [])
            if it.get("status") == "pending"
        ]
        result = {
            "ok": True,
            "action": "attended_pps_assist",
            "run_dir": str(run_dir),
            "pps_url": checklist.get("pps_url") or PPS_PUBLIC_URL,
            "item_count": checklist.get("item_count"),
            "pending_count": len(pending),
            "pending_queries": pending[:30],
            "browser": browser_info,
            "instructions": checklist.get("instructions")
            or [
                f"Open {PPS_PUBLIC_URL}",
                "Paste each pps_hint into PPS interactively",
                "Record results via portfolio_cli prior-art pps-record",
            ],
            "forbidden_auto_clicks": sorted(_FORBIDDEN_PPS_CLICKS),
            "disclaimer": PPS_DISCLAIMER,
            "generated_at_utc": utc_now_iso(),
        }
        # Also write a session note under the run
        note_path = run_dir / "pps_assist_session.json"
        note_path.write_text(
            json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
        )
        try:
            os.chmod(note_path, 0o600)
        except OSError:
            pass
        result["session_note"] = str(note_path)

        if args.json or True:
            print(json.dumps(result, indent=2, default=str))
        return 0
    except PortfolioAutomationError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": getattr(exc, "code", None),
                    "message": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
