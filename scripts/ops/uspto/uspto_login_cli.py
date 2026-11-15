#!/usr/bin/env python3
"""USPTO Patent Center login CLI (password + OTP/TOTP via refs or prompts).

Examples
--------
  # Prefer env refs (never put secrets on the command line):
  export USPTO_USERNAME='you@example.com'
  export USPTO_PASSWORD='...'
  export USPTO_TOTP_SECRET='BASE32...'   # optional authenticator seed

  python3 scripts/ops/uspto/uspto_login_cli.py login --otp-mode totp
  python3 scripts/ops/uspto/uspto_login_cli.py status
  python3 scripts/ops/uspto/uspto_login_cli.py logout

  # One-shot OTP code (not stored):
  python3 scripts/ops/uspto/uspto_login_cli.py login --otp-mode code --otp-code 123456

  # Interactive prompts for anything missing:
  python3 scripts/ops/uspto/uspto_login_cli.py login --otp-mode prompt

  # Prefer when Playwright password login is blocked: sign in via Snap Firefox,
  # then import cookies (no password/OTP re-entry):
  python3 scripts/ops/uspto/uspto_login_cli.py import-firefox

Secrets never appear in JSON output. Session storage_state is mode 0600 under
the portfolio state root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (  # noqa: E402
    LoginError,
    import_session_from_cdp,
    import_session_from_firefox,
    load_session_status,
    login_patent_center,
    logout_session,
    sanitize_tool_arguments,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (  # noqa: E402
    default_state_root,
)


def _state(args: argparse.Namespace) -> Path:
    if getattr(args, "state_root", None):
        return Path(args.state_root).expanduser().resolve()
    return default_state_root()


def _cmd_import_cdp(args: argparse.Namespace) -> int:
    """Capture storage_state from an already-signed-in Chrome (no password/OTP)."""
    result = import_session_from_cdp(
        cdp_url=str(args.cdp_url),
        state_root=_state(args),
        session_name=str(args.session_name),
        username_hint=str(args.username_hint or ""),
        bind_patent_center=not bool(args.no_bind_patent_center),
        timeout_seconds=float(args.timeout_seconds),
    )
    stream = sys.stdout if result.get("ok") else sys.stderr
    print(json.dumps(result, indent=2), file=stream)
    return 0 if result.get("ok") else 2


def _cmd_import_firefox(args: argparse.Namespace) -> int:
    """Copy live Snap/desktop Firefox USPTO cookies into operator storage_state."""
    result = import_session_from_firefox(
        state_root=_state(args),
        session_name=str(args.session_name),
        username_hint=str(args.username_hint or ""),
        profile_cookie_db=str(args.cookie_db) if getattr(args, "cookie_db", "") else None,
        verify=not bool(args.no_verify),
        timeout_seconds=float(args.timeout_seconds),
    )
    stream = sys.stdout if result.get("ok") else sys.stderr
    # Never dump cookie values; result already omits them.
    print(json.dumps(result, indent=2), file=stream)
    return 0 if result.get("ok") else 2


def _cmd_login(args: argparse.Namespace) -> int:
    try:
        # headless: CLI --headless forces True; --headed forces False; else auto (DISPLAY).
        if bool(getattr(args, "headed", False)):
            headless: bool | None = False
        elif bool(getattr(args, "headless", False)):
            headless = True
        else:
            headless = None
        result = login_patent_center(
            username_ref=str(args.username_ref),
            password_ref=str(args.password_ref),
            otp_mode=str(args.otp_mode),
            otp_ref=str(args.otp_ref or ""),
            totp_secret_ref=str(args.totp_secret_ref),
            otp_code=str(args.otp_code or ""),
            otp_file=str(getattr(args, "otp_file", "") or "") or None,
            otp_wait_seconds=float(getattr(args, "otp_wait_seconds", 90.0) or 90.0),
            state_root=_state(args),
            session_name=str(args.session_name),
            headless=headless,
            browser=str(getattr(args, "browser", "chromium") or "chromium"),
            timeout_seconds=float(args.timeout_seconds),
            allow_prompt=not bool(args.no_prompt),
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 1
    except LoginError as exc:
        print(
            json.dumps({"ok": False, "code": exc.code, "message": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2


def _cmd_status(args: argparse.Namespace) -> int:
    status = load_session_status(_state(args), name=str(args.session_name))
    print(json.dumps(status.to_dict(), indent=2))
    return 0 if status.present else 1


def _cmd_logout(args: argparse.Namespace) -> int:
    print(json.dumps(logout_session(_state(args), name=str(args.session_name)), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uspto_login_cli",
        description=(
            "Patent Center login helper using credential refs / prompts. "
            "Never prints passwords, OTP secrets, or raw cookies."
        ),
    )
    p.add_argument(
        "--state-root",
        default="",
        help="Portfolio state root (default XDG patent_portfolio/operator-default)",
    )
    p.add_argument("--session-name", default="patent_center")
    sub = p.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Login and save Playwright storage_state")
    login.add_argument(
        "--username-ref",
        default="env:USPTO_USERNAME",
        help="Username ref (default env:USPTO_USERNAME) or prompt if missing",
    )
    login.add_argument(
        "--password-ref",
        default="env:USPTO_PASSWORD",
        help="Password ref (default env:USPTO_PASSWORD) or prompt if missing",
    )
    login.add_argument(
        "--otp-mode",
        choices=("prompt", "totp", "code", "file", "none"),
        default="prompt",
        help=(
            "MFA source: prompt | totp | code (argv/ref, else wait on file) | "
            "file (wait on --otp-file after password — best for fresh chat OTPs) | none"
        ),
    )
    login.add_argument(
        "--totp-secret-ref",
        default="env:USPTO_TOTP_SECRET",
        help="TOTP seed ref when --otp-mode totp",
    )
    login.add_argument(
        "--otp-ref",
        default="",
        help="Optional ref for one-shot OTP when --otp-mode code",
    )
    login.add_argument(
        "--otp-code",
        default="",
        help="One-shot OTP code (not stored). Prefer --otp-mode file for chat-driven OTPs.",
    )
    login.add_argument(
        "--otp-file",
        default="/tmp/uspto_otp_now.txt",
        help="When MFA is ready, poll this file for a 6-digit code (default /tmp/uspto_otp_now.txt)",
    )
    login.add_argument(
        "--otp-wait-seconds",
        type=float,
        default=90.0,
        help="How long to wait for --otp-file after password (default 90)",
    )
    login.add_argument(
        "--headless",
        action="store_true",
        help="Force headless browser (often rejected by Okta; prefer XRDP headed)",
    )
    login.add_argument(
        "--headed",
        action="store_true",
        help="Force headed browser on $DISPLAY (XRDP :10 / ssh -Y). Default when DISPLAY set.",
    )
    login.add_argument(
        "--browser",
        choices=("chromium", "firefox"),
        default="chromium",
        help="Playwright engine (firefox closer to successful operator XRDP login)",
    )
    login.add_argument("--timeout-seconds", type=float, default=180.0)
    login.add_argument(
        "--no-prompt",
        action="store_true",
        help="Fail instead of prompting when a secret ref is missing",
    )
    login.set_defaults(func=_cmd_login)

    st = sub.add_parser("status", help="Show whether a local session file exists")
    st.set_defaults(func=_cmd_status)

    lo = sub.add_parser("logout", help="Delete local session storage_state")
    lo.set_defaults(func=_cmd_logout)

    imp = sub.add_parser(
        "import-cdp",
        help=(
            "Import session from already-logged-in Chrome via CDP "
            "(skip password/OTP; use when headless Okta locks)"
        ),
    )
    imp.add_argument(
        "--cdp-url",
        default="http://127.0.0.1:9222",
        help="Chrome remote debugging URL (default http://127.0.0.1:9222)",
    )
    imp.add_argument(
        "--username-hint",
        default="",
        help="Optional username hint stored in session meta (not a secret)",
    )
    imp.add_argument(
        "--no-bind-patent-center",
        action="store_true",
        help="Skip Patent Center SSO navigation after import",
    )
    imp.add_argument("--timeout-seconds", type=float, default=120.0)
    imp.set_defaults(func=_cmd_import_cdp)

    ff = sub.add_parser(
        "import-firefox",
        help=(
            "Import session from Snap/desktop Firefox cookies.sqlite "
            "(sign in via real Firefox first; skip Playwright password/OTP)"
        ),
    )
    ff.add_argument(
        "--cookie-db",
        default="",
        help="Optional path to cookies.sqlite (default: newest Firefox profile)",
    )
    ff.add_argument(
        "--username-hint",
        default="",
        help="Optional username hint for session meta (not a secret)",
    )
    ff.add_argument(
        "--no-verify",
        action="store_true",
        help="Only copy cookies; do not open Playwright to verify Patent Center",
    )
    ff.add_argument("--timeout-seconds", type=float, default=90.0)
    ff.set_defaults(func=_cmd_import_firefox)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Never echo raw args that might contain secrets into debug logs.
    _ = sanitize_tool_arguments(vars(args))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
