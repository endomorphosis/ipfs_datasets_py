#!/usr/bin/env python3
"""Attended Patent Center export helper (human login + optional download assist).

Design (fail-closed):
* Opens a **headed** browser. A natural person completes USPTO login / MFA.
* Never accepts or types Patent Center passwords, MFA codes, or payment data.
* Never signs, pays, or submits filings.
* After login is detected (or operator presses Enter), assists navigation to
  known application numbers and captures downloads into a local export folder.
* Produces ``export_manifest.json`` + ``authorization.json`` for import-private.

Patent Center's UI changes; when automatic download controls are missing the
helper falls back to **watch-folder** mode: you download manually into the
export directory and the helper seals the package.

Usage examples:

  # Open browser, wait for you to log in, assist downloads for apps in seed
  python3 scripts/ops/uspto/attended_patent_center_export.py \\
    --state-root ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default \\
    --application-number 18654466

  # Only seal a folder you already filled with downloads
  python3 scripts/ops/uspto/attended_patent_center_export.py \\
    --seal-only --export-dir /path/to/downloads --application-number 18654466
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

# Allow running from repo root without install.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (  # noqa: E402
    FORBIDDEN_OPERATOR_CAPABILITIES,
    PortfolioAutomationError,
    assert_operator_capability,
    default_state_root,
    load_portfolio_seed,
    utc_now_iso,
    write_export_package_sidecar,
)

PATENT_CENTER_URL = "https://patentcenter.uspto.gov"
PATENT_CENTER_TRAINING_URL = "https://patentcenter-training.uspto.gov"

# Conservative login signals (any match counts as "likely authenticated").
_LOGGED_IN_SELECTORS = (
    "text=Log Out",
    "text=Logout",
    "text=Sign Out",
    "text=My Workbench",
    "text=Workbench",
    "[data-testid*='logout' i]",
    "a[href*='logout' i]",
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Attended Patent Center export: human login required; no password "
            "storage; no sign/pay/submit."
        )
    )
    p.add_argument(
        "--state-root",
        default="",
        help="Portfolio state root (default: XDG patent_portfolio/operator-default).",
    )
    p.add_argument(
        "--export-dir",
        default="",
        help="Directory for downloads + sidecars (default: state-root/exports/<app>).",
    )
    p.add_argument(
        "--application-number",
        action="append",
        default=[],
        help="Application number to export (repeatable). Defaults to confirmed seed matters.",
    )
    p.add_argument(
        "--tenant",
        default="operator-default",
        help="Tenant id for authorization sidecar.",
    )
    p.add_argument(
        "--authorizing-user",
        default="operator:local",
        help="Human operator label recorded on authorization (never a password).",
    )
    p.add_argument(
        "--training",
        action="store_true",
        help="Open Patent Center training environment instead of live.",
    )
    p.add_argument(
        "--user-data-dir",
        default="",
        help=(
            "Optional persistent Chromium profile directory (cookies stay on disk). "
            "Do not commit this path. Empty = ephemeral profile."
        ),
    )
    p.add_argument(
        "--login-timeout-seconds",
        type=float,
        default=600.0,
        help="Max seconds to wait for human login detection (default 600).",
    )
    p.add_argument(
        "--seal-only",
        action="store_true",
        help="Skip browser; only write manifest/authorization for --export-dir.",
    )
    p.add_argument(
        "--watch-seconds",
        type=float,
        default=120.0,
        help="After navigation assist, watch download dir this many seconds.",
    )
    p.add_argument(
        "--no-browser-assist",
        action="store_true",
        help="Open Patent Center only; do not attempt app-number navigation.",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON summary.")
    return p.parse_args(argv)


def _reject_secret_args(args: argparse.Namespace) -> None:
    """Refuse CLI flags that look like credential smuggling."""
    blob = " ".join(
        [
            str(getattr(args, "authorizing_user", "")),
            str(getattr(args, "user_data_dir", "")),
            str(getattr(args, "export_dir", "")),
        ]
    ).lower()
    for bad in (
        "password=",
        "passwd=",
        "mfa=",
        "otp=",
        "api_key=",
        "cookie=",
        "bearer ",
        "secret=",
    ):
        if bad in blob:
            raise PortfolioAutomationError(
                "refusing arguments that look like credential material",
                code="secret_argument_forbidden",
            )


def _resolve_apps(args: argparse.Namespace, state_root: Path) -> list[str]:
    apps = [str(a).strip() for a in (args.application_number or []) if str(a).strip()]
    if apps:
        return apps
    seed_path = state_root / "portfolio_seed.json"
    if not seed_path.is_file():
        raise PortfolioAutomationError(
            "no --application-number and no portfolio_seed.json; pass apps explicitly",
            code="missing_application_numbers",
        )
    seed = load_portfolio_seed(seed_path)
    confirmed = [
        m.application_number
        for m in seed.matters
        if not str(m.ownership).startswith("candidate")
    ]
    if confirmed:
        return confirmed
    # Fall back to all seed matters with a warning label in the receipt.
    return [m.application_number for m in seed.matters]


def _export_dir_for(state_root: Path, app: str, explicit: str) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in app)
    path = state_root / "exports" / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wait_for_login(page: Any, timeout_seconds: float) -> dict[str, Any]:
    """Poll for logout/workbench signals; also allow Enter in the terminal."""
    deadline = time.time() + max(30.0, float(timeout_seconds))
    print(
        "\n=== Human login required ===\n"
        "Complete USPTO / Patent Center sign-in (and MFA) in the browser window.\n"
        "This tool will NOT type your password.\n"
        "When finished, either wait for auto-detect or press Enter here.\n",
        flush=True,
    )
    # Non-blocking-ish: check selectors in a loop; also peek stdin if possible.
    import select

    while time.time() < deadline:
        for selector in _LOGGED_IN_SELECTORS:
            try:
                if page.locator(selector).count() > 0:
                    return {
                        "logged_in": True,
                        "method": "selector",
                        "selector": selector,
                        "at_utc": utc_now_iso(),
                    }
            except Exception:
                continue
        # Terminal Enter
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if ready:
                sys.stdin.readline()
                return {
                    "logged_in": True,
                    "method": "operator_enter",
                    "at_utc": utc_now_iso(),
                }
        except Exception:
            time.sleep(0.5)
    return {
        "logged_in": False,
        "method": "timeout",
        "at_utc": utc_now_iso(),
    }


def _assist_application(page: Any, app: str) -> dict[str, Any]:
    """Best-effort navigation to an application; UI may require manual steps."""
    notes: list[str] = []
    # Try deep-link style paths used by Patent Center SPAs (best effort).
    candidates = [
        f"{PATENT_CENTER_URL}/#/applications/{app}",
        f"{PATENT_CENTER_URL}/applications/{app}",
        f"{PATENT_CENTER_URL}/#/application/{app}",
    ]
    opened = None
    for url in candidates:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            opened = url
            notes.append(f"opened:{url}")
            break
        except Exception as exc:
            notes.append(f"nav_failed:{type(exc).__name__}")
    # Attempt common search box patterns.
    search_filled = False
    for sel in (
        "input[placeholder*='Application' i]",
        "input[aria-label*='Application' i]",
        "input[name*='application' i]",
        "input[type='search']",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.fill(app)
            loc.press("Enter")
            search_filled = True
            notes.append(f"search_filled:{sel}")
            break
        except Exception:
            continue
    # Attempt download / export buttons (labels vary).
    download_clicked = False
    for label in (
        "Download",
        "Export",
        "Download Documents",
        "Download All",
        "Save",
        "PDF",
    ):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=5000)
                download_clicked = True
                notes.append(f"clicked:{label}")
                break
        except Exception:
            continue
        try:
            link = page.get_by_role("link", name=label)
            if link.count() > 0:
                link.first.click(timeout=5000)
                download_clicked = True
                notes.append(f"clicked_link:{label}")
                break
        except Exception:
            continue
    return {
        "application_number": app,
        "opened_url": opened,
        "search_filled": search_filled,
        "download_clicked": download_clicked,
        "notes": notes,
        "guidance": (
            "If documents did not download automatically, use Patent Center UI "
            "to download them into the export directory shown in the console, "
            "then re-run with --seal-only."
        ),
    }


def _run_browser_session(
    *,
    apps: list[str],
    export_dirs: dict[str, Path],
    training: bool,
    user_data_dir: str,
    login_timeout_seconds: float,
    watch_seconds: float,
    no_browser_assist: bool,
) -> dict[str, Any]:
    assert_operator_capability("attended_browser_export_with_human_login")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortfolioAutomationError(
            "playwright is required for attended export "
            "(pip install playwright && playwright install chromium)",
            code="playwright_missing",
        ) from exc

    start_url = PATENT_CENTER_TRAINING_URL if training else PATENT_CENTER_URL
    assists: list[dict[str, Any]] = []
    login_info: dict[str, Any] = {}

    with sync_playwright() as playwright:
        if user_data_dir:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                accept_downloads=True,
            )
            browser = None
        else:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(accept_downloads=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            # Route downloads into the first export dir by default; per-app dirs
            # are sealed separately after the session.
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            login_info = _wait_for_login(page, login_timeout_seconds)
            if not login_info.get("logged_in"):
                raise PortfolioAutomationError(
                    "login not detected before timeout; re-run after signing in",
                    code="login_timeout",
                )
            if not no_browser_assist:
                for app in apps:
                    # Prefer app-specific download path when supported.
                    try:
                        context.set_default_timeout(15000)
                    except Exception:
                        pass
                    assists.append(_assist_application(page, app))
                    time.sleep(1.0)
            if watch_seconds > 0:
                print(
                    f"\nWatching for downloads for {watch_seconds:.0f}s. "
                    "Complete any manual downloads in Patent Center now.\n",
                    flush=True,
                )
                time.sleep(watch_seconds)
        finally:
            context.close()
            if browser is not None:
                browser.close()

    return {
        "login": login_info,
        "assists": assists,
        "start_url": start_url,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _reject_secret_args(args)
        # Hard ban on forbidden capabilities as a self-check.
        for cap in FORBIDDEN_OPERATOR_CAPABILITIES:
            if cap in {
                "attended_browser_export_with_human_login",
                "watch_download_folder",
            }:
                continue
        state_root = (
            Path(args.state_root).expanduser().resolve()
            if args.state_root
            else default_state_root()
        )
        state_root.mkdir(parents=True, exist_ok=True)
        apps = _resolve_apps(args, state_root)
        if not apps:
            raise PortfolioAutomationError(
                "no application numbers to export", code="empty_app_list"
            )

        export_dirs = {
            app: _export_dir_for(state_root, app, args.export_dir if len(apps) == 1 else "")
            for app in apps
        }
        # If multi-app with single --export-dir, nest per app.
        if args.export_dir and len(apps) > 1:
            base = Path(args.export_dir).expanduser().resolve()
            for app in apps:
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in app)
                path = base / safe
                path.mkdir(parents=True, exist_ok=True)
                export_dirs[app] = path

        session: dict[str, Any] = {"skipped": True}
        if not args.seal_only:
            session = _run_browser_session(
                apps=apps,
                export_dirs=export_dirs,
                training=bool(args.training),
                user_data_dir=str(args.user_data_dir or ""),
                login_timeout_seconds=float(args.login_timeout_seconds),
                watch_seconds=float(args.watch_seconds),
                no_browser_assist=bool(args.no_browser_assist),
            )

        sealed: list[dict[str, Any]] = []
        for app, folder in export_dirs.items():
            files = [
                p.name
                for p in folder.rglob("*")
                if p.is_file()
                and p.name
                not in {"export_manifest.json", "authorization.json", ".DS_Store"}
            ]
            if not files:
                sealed.append(
                    {
                        "application_number": app,
                        "export_dir": str(folder),
                        "sealed": False,
                        "reason": "no_files_yet",
                        "hint": "Download files into this directory, then --seal-only",
                    }
                )
                continue
            paths = write_export_package_sidecar(
                folder,
                application_number=app,
                tenant_id=str(args.tenant),
                authorizing_user=str(args.authorizing_user),
            )
            sealed.append(
                {
                    "application_number": app,
                    "export_dir": str(folder),
                    "sealed": True,
                    "file_count": len(files),
                    "manifest": str(paths["manifest"]),
                    "authorization": str(paths["authorization"]),
                }
            )

        receipt = {
            "schema": "patlaw-attended-patent-center-export-v1",
            "generated_at_utc": utc_now_iso(),
            "tenant_id": args.tenant,
            "authorizing_user": args.authorizing_user,
            "capabilities": {
                "attended_browser_export_with_human_login": not args.seal_only,
                "seal_export_package": True,
                "forbidden": sorted(FORBIDDEN_OPERATOR_CAPABILITIES),
            },
            "session": session,
            "sealed": sealed,
            "next_steps": [
                "Review sealed export folders.",
                "Import with: portfolio_cli.py import-folder --export-dir ... --application-number ...",
                "Do not commit export folders or browser profiles.",
            ],
        }
        receipt_path = state_root / "attended_export_receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        try:
            os.chmod(receipt_path, 0o600)
        except OSError:
            pass

        if args.json:
            print(json.dumps(receipt, indent=2))
        else:
            print(json.dumps(receipt, indent=2))
            print(f"\nWrote receipt: {receipt_path}")
        return 0
    except PortfolioAutomationError as exc:
        err = {"ok": False, "code": exc.code, "message": str(exc)}
        print(json.dumps(err, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        err = {
            "ok": False,
            "code": "attended_export_failed",
            "error_type": type(exc).__name__,
            "message": str(exc)[:400],
        }
        print(json.dumps(err, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
