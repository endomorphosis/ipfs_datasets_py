#!/usr/bin/env python3
"""Attended Patent Center filing *assist* with hard barriers.

Opens Patent Center with a saved login session (or interactive login), navigates
view-only surfaces, prints a filing checklist, and watches a local folder for
post-submit receipt downloads.

NEVER clicks or automates:
  Sign / Certify / Pay / Submit / charge / final filing.

Usage:
  python3 scripts/ops/uspto/attended_filing_assist.py \\
    --application-number 18654466 \\
    --package-dir /path/to/local/package \\
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

from ipfs_datasets_py.processors.domains.uspto.filing_assist import (  # noqa: E402
    FORBIDDEN_FILING_ASSIST_CAPABILITIES,
    HARD_BARRIER_CLICK_LABELS,
    assert_click_allowed,
    assert_filing_assist_capability,
    build_filing_checklist,
    is_hard_barrier_label,
    prepare_receipt_inbox,
    write_filing_checklist,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (  # noqa: E402
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

PATENT_CENTER_URL = "https://patentcenter.uspto.gov"
PATENT_CENTER_TRAINING_URL = "https://patentcenter-training.uspto.gov"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Attended Patent Center filing assist: navigate + checklist + "
            "receipt watch. Never signs, pays, or submits."
        )
    )
    p.add_argument("--state-root", default="")
    p.add_argument("--application-number", default="")
    p.add_argument(
        "--package-dir",
        default="",
        help="Local package folder to bind into checklist digest",
    )
    p.add_argument("--package-digest", default="")
    p.add_argument("--metadata-dir", default="")
    p.add_argument("--training", action="store_true")
    p.add_argument("--session-name", default="patent_center")
    p.add_argument("--no-saved-session", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument(
        "--watch-seconds",
        type=float,
        default=300.0,
        help="Seconds to keep browser open / watch receipt downloads (default 300)",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Only write checklist + prepare receipt folder (no Playwright)",
    )
    p.add_argument(
        "--navigate",
        choices=("home", "workbench", "new-submission", "application", "none"),
        default="home",
        help="Safe navigation target after login (default home)",
    )
    p.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def _safe_nav_url(base: str, navigate: str, app: str) -> str | None:
    if navigate == "none":
        return None
    if navigate == "home":
        return base + "/"
    if navigate == "workbench":
        return base + "/workbench"
    if navigate == "new-submission":
        return base + "/new-submission"
    if navigate == "application":
        if not app:
            raise PortfolioAutomationError(
                "navigate=application requires --application-number",
                code="missing_application_number",
            )
        return f"{base}/applications/{app}"
    return base + "/"


def _guard_click_label(label: str) -> None:
    """Raise if label is a hard barrier (sign/pay/submit)."""
    try:
        assert_click_allowed(label)
    except Exception as exc:
        raise PortfolioAutomationError(
            f"refusing automated click on hard-barrier control: {label!r}",
            code="hard_barrier_click_refused",
        ) from exc


def _inject_banner(page: Any) -> None:
    try:
        page.evaluate(
            """() => {
              if (document.getElementById('patlaw-hard-barrier-banner')) return;
              const d = document.createElement('div');
              d.id = 'patlaw-hard-barrier-banner';
              d.textContent = 'PATLAW ASSIST: YOU must Sign / Pay / Submit. Automation will not click those controls.';
              Object.assign(d.style, {
                position: 'fixed', top: '0', left: '0', right: '0', zIndex: '2147483647',
                background: '#7a1f1f', color: '#fff', padding: '10px 16px',
                font: '600 14px/1.3 system-ui,sans-serif', textAlign: 'center'
              });
              document.body.appendChild(d);
              document.body.style.paddingTop = '42px';
            }"""
        )
    except Exception:
        pass


def _run_browser(
    *,
    start_url: str,
    nav_url: str | None,
    state_root: Path,
    session_name: str,
    use_saved_session: bool,
    headless: bool,
    receipt_dir: Path,
    watch_seconds: float,
) -> dict[str, Any]:
    assert_filing_assist_capability("attended_filing_assist_with_hard_barrier")
    assert_filing_assist_capability("navigate_patent_center_view_only")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortfolioAutomationError(
            "playwright required (pip install playwright && playwright install chromium)",
            code="playwright_missing",
        ) from exc

    if not headless and not os.environ.get("DISPLAY"):
        headless = True

    storage_state_path = None
    if use_saved_session:
        try:
            from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
                load_session_status,
                session_path,
            )

            status = load_session_status(state_root, name=session_name)
            path = session_path(state_root, name=session_name)
            if status.present and path.is_file():
                storage_state_path = str(path)
        except Exception:
            storage_state_path = None

    if headless and not storage_state_path:
        raise PortfolioAutomationError(
            "headless filing assist requires a saved login session "
            "(run portfolio_cli login first)",
            code="headless_requires_session",
        )

    downloads: list[str] = []
    blocked_clicks: list[str] = []
    receipt_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(headless))
        context_kwargs: dict[str, Any] = {
            "accept_downloads": True,
            "user_agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1440, "height": 900},
        }
        if storage_state_path:
            context_kwargs["storage_state"] = storage_state_path
        context = browser.new_context(**context_kwargs)

        def _on_download(download: Any) -> None:
            try:
                name = download.suggested_filename or f"receipt-{int(time.time())}"
                # Never auto-name into payment instrument patterns; just save.
                target = receipt_dir / name
                if target.exists():
                    target = receipt_dir / f"{target.stem}-{int(time.time())}{target.suffix}"
                download.save_as(str(target))
                downloads.append(str(target))
            except Exception:
                pass

        page = context.new_page()
        page.on("download", _on_download)

        # Intercept navigations that look like payment-processor handoff only for
        # logging; we do not block human-driven payment (human may navigate).
        page.goto(start_url, wait_until="domcontentloaded", timeout=90_000)
        _inject_banner(page)

        if nav_url:
            try:
                page.goto(nav_url, wait_until="domcontentloaded", timeout=90_000)
                _inject_banner(page)
            except Exception as exc:
                blocked_clicks.append(f"nav_error:{type(exc).__name__}")

        # Attempt only SAFE navigation link clicks if present (never hard barrier).
        for label in ("Workbench", "Existing submissions", "Home"):
            if is_hard_barrier_label(label):
                continue
            try:
                _guard_click_label(label)
                loc = page.get_by_text(label, exact=False)
                if loc.count() and loc.first.is_visible():
                    # Do not click if the expanded accessible name includes barrier words
                    text = loc.first.inner_text(timeout=1000)[:80]
                    if is_hard_barrier_label(text):
                        blocked_clicks.append(text)
                        continue
                    # Skip automatic click of Workbench etc. in headless to avoid
                    # accidental deep workflows — only when headed for human follow-along.
                    if not headless:
                        loc.first.click(timeout=3000)
                        _inject_banner(page)
                        page.wait_for_timeout(1000)
            except Exception:
                continue

        print(
            "\n=== HARD BARRIER ACTIVE ===\n"
            "Automation will NOT click Sign / Pay / Submit.\n"
            "Complete those actions yourself in the browser window.\n"
            f"Save receipts into: {receipt_dir}\n"
            f"Watching for {watch_seconds:.0f}s…\n",
            flush=True,
        )

        # Periodically re-inject banner; capture any download events.
        deadline = time.time() + max(5.0, float(watch_seconds))
        while time.time() < deadline:
            try:
                _inject_banner(page)
            except Exception:
                pass
            # Self-check: if page text suggests we are on payment/sign step, warn only.
            try:
                body = page.inner_text("body")[:2000].lower()
                for barrier in ("certify", "pay fees", "submit application", "sign in to pay"):
                    if barrier in body and barrier not in blocked_clicks:
                        blocked_clicks.append(f"page_contains:{barrier}")
            except Exception:
                pass
            time.sleep(2.0)

        # Persist session cookies if we had a session path (upgrade SSO only)
        if storage_state_path:
            try:
                context.storage_state(path=storage_state_path)
            except Exception:
                pass
        context.close()
        browser.close()

    return {
        "start_url": start_url,
        "nav_url": nav_url,
        "used_saved_session": bool(storage_state_path),
        "headless": bool(headless),
        "downloads": downloads,
        "hard_barrier_labels": list(HARD_BARRIER_CLICK_LABELS),
        "blocked_or_observed": blocked_clicks[:40],
        "receipt_dir": str(receipt_dir),
        "forbidden_capabilities": sorted(FORBIDDEN_FILING_ASSIST_CAPABILITIES),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        state = (
            Path(args.state_root).expanduser().resolve()
            if args.state_root
            else default_state_root()
        )
        state.mkdir(parents=True, exist_ok=True)
        app = str(args.application_number or "").strip()
        package_dir = Path(args.package_dir).expanduser() if args.package_dir else None
        metadata_dir = Path(args.metadata_dir).expanduser() if args.metadata_dir else None

        checklist = build_filing_checklist(
            application_number=app,
            package_dir=package_dir,
            package_digest=str(args.package_digest or ""),
            training=bool(args.training),
            metadata_dir=metadata_dir,
            state_root=state,
        )
        if app:
            receipt_dir = prepare_receipt_inbox(
                application_number=app, state_root=state
            )
        else:
            receipt_dir = state / "post_submit_receipts" / "_unscoped"
            receipt_dir.mkdir(parents=True, exist_ok=True)
            checklist.post_submit_receipt_dir = str(receipt_dir)

        checklist_path = write_filing_checklist(
            checklist,
            (receipt_dir / "filing_checklist.json")
            if receipt_dir
            else state / "filing_checklist.json",
        )

        session_info: dict[str, Any] = {"skipped": True}
        if not args.no_browser:
            base = PATENT_CENTER_TRAINING_URL if args.training else PATENT_CENTER_URL
            nav = _safe_nav_url(base, str(args.navigate), app)
            session_info = _run_browser(
                start_url=base + "/",
                nav_url=nav,
                state_root=state,
                session_name=str(args.session_name or "patent_center"),
                use_saved_session=not bool(args.no_saved_session),
                headless=bool(args.headless),
                receipt_dir=receipt_dir,
                watch_seconds=float(args.watch_seconds),
            )

        receipt = {
            "schema": "patlaw-attended-filing-assist-v1",
            "generated_at_utc": utc_now_iso(),
            "checklist_path": str(checklist_path),
            "checklist": checklist.to_dict(),
            "session": session_info,
            "next_steps": [
                "Complete Sign / Pay / Submit yourself in Patent Center.",
                f"Save EAR + payment receipts into {receipt_dir}.",
                "Run: portfolio_cli.py watch-receipts --application-number "
                + (app or "<app>"),
                "Optionally record UserSubmissionAssertion on PatentCenterHandoff "
                "with the package digest.",
            ],
        }
        out = state / "filing_assist_receipt.json"
        out.write_text(json.dumps(receipt, indent=2, default=str) + "\n")
        try:
            out.chmod(0o600)
        except OSError:
            pass
        if args.json or True:
            print(json.dumps({**receipt, "receipt_path": str(out)}, indent=2, default=str))
        return 0
    except PortfolioAutomationError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "code": exc.code}, indent=2))
        return 2
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}:{exc}"},
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
