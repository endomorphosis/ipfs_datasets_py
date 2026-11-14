"""Patent Center / MyUSPTO operator login session helper.

Design
------
* Username, password, and OTP are accepted only as:
  - opaque refs (``env:VAR``, ``file:/path``), or
  - interactive prompts (CLI), or
  - one-shot OTP code for a single login attempt (never persisted).
* TOTP secrets (if used) are resolved the same way and never written to
  session files, receipts, logs, or MCP responses.
* Playwright storage_state is stored under the operator state root at mode 0600.
* No sign / pay / file / submit capability is exposed.

This is an **operator** surface for private export automation. It does not
replace the public ODP API-key path.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final, Mapping
from urllib.parse import urlparse

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    default_state_root,
    utc_now_iso,
)

LOGIN_SCHEMA: Final = "patlaw-uspto-login-session-v1"
DEFAULT_SESSION_NAME: Final = "patent_center"
PATENT_CENTER_LOGIN_URL: Final = "https://patentcenter.uspto.gov"
MYUSPTO_HOME_URL: Final = "https://my.uspto.gov/home"
# USPTO uses Okta at auth.uspto.gov; starting at MyUSPTO home triggers the authorize flow.
DEFAULT_LOGIN_ENTRY_URL: Final = MYUSPTO_HOME_URL
# Match a current Chromium build; stale Chrome/120 UA is a common headless tell.
_OPERATOR_USER_AGENT: Final = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
_OPERATOR_FIREFOX_UA: Final = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)


def _resolve_headless(headless: bool | None) -> bool:
    """Prefer headed when a real DISPLAY exists (XRDP / ssh -Y / local X).

    Headless Chromium is frequently rejected by Okta with E0000004
    (\"username or password are incorrect\") even when the same password
    works in real Firefox — confirmed operator path: XRDP + Firefox.
    """
    if headless is not None:
        return bool(headless)
    display = (os.environ.get("DISPLAY") or "").strip()
    # Headed only when we have an X server (e.g. :10 for xrdp).
    return not bool(display)


def _launch_operator_browser(
    playwright: Any,
    *,
    headless: bool | None = True,
    browser: str = "chromium",
) -> Any:
    """Launch Chromium or Firefox with reduced automation fingerprints for Okta.

    ``browser``: ``chromium`` (default) or ``firefox``. Firefox is closer to the
    operator's successful XRDP path; use when headless Chromium gets E0000004.
    """
    use_headless = _resolve_headless(headless)
    engine = (browser or "chromium").strip().lower()
    print(
        f"LOGIN_DIAG browser={engine} headless={use_headless} "
        f"DISPLAY={os.environ.get('DISPLAY')!r}",
        flush=True,
    )
    if engine == "firefox":
        # Playwright Firefox; no Chromium-only args.
        return playwright.firefox.launch(headless=use_headless)

    launch_kwargs: dict[str, Any] = {
        "headless": use_headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    # Prefer a system Chromium when present (closer to operator Chrome).
    for candidate in (
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ):
        if Path(candidate).is_file() or Path(candidate).is_symlink():
            launch_kwargs["executable_path"] = candidate
            break
    try:
        return playwright.chromium.launch(**launch_kwargs)
    except Exception:
        launch_kwargs.pop("executable_path", None)
        return playwright.chromium.launch(**launch_kwargs)


def _new_operator_context(
    browser: Any, *, browser_engine: str = "chromium", **kwargs: Any
) -> Any:
    """Browser context defaults used for MyUSPTO / Patent Center operator sessions."""
    engine = (browser_engine or "chromium").strip().lower()
    ua = _OPERATOR_FIREFOX_UA if engine == "firefox" else _OPERATOR_USER_AGENT
    opts: dict[str, Any] = {
        "user_agent": ua,
        "viewport": {"width": 1366, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "color_scheme": "light",
    }
    opts.update(kwargs)
    context = browser.new_context(**opts)
    if engine != "firefox":
        try:
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
        except Exception:
            pass
    return context


FORBIDDEN_LOGIN_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "return_password",
        "return_otp_secret",
        "return_raw_cookies",
        "sign",
        "pay",
        "file",
        "submit",
        "bypass_mfa_without_code",
    }
)

_REF_RE = re.compile(r"\A(env|file):(.+)\Z", re.DOTALL)
_SECRET_ECHO_KEYS = frozenset(
    {
        "password",
        "passwd",
        "otp",
        "totp",
        "mfa",
        "secret",
        "cookie",
        "cookies",
        "authorization",
        "token",
        "api_key",
    }
)


class LoginError(RuntimeError):
    def __init__(self, message: str, *, code: str = "login_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def _scrub(text: str) -> str:
    out = str(text or "")
    # Never leave obvious secret assignments in messages.
    out = re.sub(
        r"(?i)(password|passwd|otp|totp|secret|cookie|token|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        out,
    )
    return out[:400]


def resolve_secret_ref(
    ref: str,
    *,
    prompt_label: str | None = None,
    allow_prompt: bool = False,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve ``env:NAME``, ``file:/path``, bare env name, or interactive prompt.

    Bare values that look like refs are resolved; raw secrets may be passed only
    when *ref* does not match a scheme (discouraged — prefer env refs).
    """
    text = str(ref or "").strip()
    envmap = environ if environ is not None else os.environ

    if not text:
        if allow_prompt and prompt_label:
            return getpass.getpass(f"{prompt_label}: ")
        raise LoginError("secret reference is empty", code="empty_secret_ref")

    match = _REF_RE.match(text)
    if match:
        scheme, name = match.group(1), match.group(2)
        if scheme == "env":
            value = envmap.get(name, "")
            if not value:
                raise LoginError(
                    f"environment variable {name!r} is not set",
                    code="env_secret_missing",
                )
            return value
        if scheme == "file":
            path = Path(name).expanduser()
            if not path.is_file():
                raise LoginError("secret file is missing", code="file_secret_missing")
            value = path.read_text(encoding="utf-8").strip()
            if not value:
                raise LoginError("secret file is empty", code="file_secret_empty")
            return value

    # Bare ENV var name convention: all-caps with underscores.
    if re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", text) and text in envmap:
        return str(envmap[text])

    # Literal value (operator-provided one-shot). Discouraged for passwords.
    return text


def generate_totp(secret: str, *, digits: int = 6, period: int = 30, for_time: float | None = None) -> str:
    """RFC 6238 TOTP (SHA-1) without external dependencies."""
    raw = str(secret or "").strip().replace(" ", "").upper()
    if not raw:
        raise LoginError("TOTP secret is empty", code="empty_totp_secret")
    # Pad base32
    pad = "=" * ((8 - len(raw) % 8) % 8)
    try:
        key = base64.b32decode(raw + pad, casefold=True)
    except Exception as exc:  # noqa: BLE001
        raise LoginError("TOTP secret is not valid base32", code="invalid_totp_secret") from exc
    counter = int((time.time() if for_time is None else for_time) // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = code_int % (10**digits)
    return f"{code:0{digits}d}"


def session_dir(state_root: Path | None = None) -> Path:
    root = Path(state_root) if state_root else default_state_root()
    path = root / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def session_path(state_root: Path | None = None, *, name: str = DEFAULT_SESSION_NAME) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_") or DEFAULT_SESSION_NAME
    return session_dir(state_root) / f"{safe}.storage_state.json"


def session_meta_path(state_root: Path | None = None, *, name: str = DEFAULT_SESSION_NAME) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_") or DEFAULT_SESSION_NAME
    return session_dir(state_root) / f"{safe}.meta.json"


@dataclass(frozen=True)
class SessionStatus:
    schema: str
    session_name: str
    present: bool
    logged_in_hint: bool
    path: str
    updated_at_utc: str | None
    username_hint: str | None
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "session_name": self.session_name,
            "present": self.present,
            "logged_in_hint": self.logged_in_hint,
            "path": self.path,
            "updated_at_utc": self.updated_at_utc,
            "username_hint": self.username_hint,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class LoginResult:
    schema: str
    ok: bool
    session_name: str
    session_path: str
    username_hint: str | None
    otp_mode: str
    logged_in: bool
    message: str
    started_at_utc: str
    finished_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        # Intentionally no password, otp, cookies, or storage_state body.
        return {
            "schema": self.schema,
            "ok": self.ok,
            "session_name": self.session_name,
            "session_path": self.session_path,
            "username_hint": self.username_hint,
            "otp_mode": self.otp_mode,
            "logged_in": self.logged_in,
            "message": self.message,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
        }


def _username_hint(username: str) -> str:
    text = str(username or "").strip()
    if not text:
        return ""
    if "@" in text:
        local, _, domain = text.partition("@")
        return (local[:2] + "***@" + domain) if local else "***@" + domain
    if len(text) <= 2:
        return "*" * len(text)
    return text[:2] + "***"


def load_session_status(
    state_root: Path | None = None, *, name: str = DEFAULT_SESSION_NAME
) -> SessionStatus:
    path = session_path(state_root, name=name)
    meta_path = session_meta_path(state_root, name=name)
    notes: list[str] = []
    updated = None
    username_hint = None
    present = path.is_file()
    logged_in_hint = False
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, Mapping):
                updated = str(meta.get("updated_at_utc") or "") or None
                username_hint = str(meta.get("username_hint") or "") or None
                logged_in_hint = bool(meta.get("logged_in"))
        except (OSError, json.JSONDecodeError):
            notes.append("meta_unreadable")
    if present:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") if isinstance(data, Mapping) else None
            if isinstance(cookies, list) and cookies:
                logged_in_hint = logged_in_hint or True
                notes.append(f"cookie_count={len(cookies)}")
            else:
                notes.append("storage_state_empty_cookies")
        except (OSError, json.JSONDecodeError):
            notes.append("storage_state_unreadable")
            present = False
    else:
        notes.append("no_session_file")
    return SessionStatus(
        schema=LOGIN_SCHEMA,
        session_name=name,
        present=present,
        logged_in_hint=bool(logged_in_hint and present),
        path=str(path),
        updated_at_utc=updated,
        username_hint=username_hint,
        notes=tuple(notes),
    )


def logout_session(
    state_root: Path | None = None, *, name: str = DEFAULT_SESSION_NAME
) -> dict[str, Any]:
    path = session_path(state_root, name=name)
    meta = session_meta_path(state_root, name=name)
    removed = []
    for p in (path, meta):
        if p.is_file():
            p.unlink()
            removed.append(p.name)
    return {
        "schema": LOGIN_SCHEMA,
        "ok": True,
        "session_name": name,
        "removed": removed,
        "at_utc": utc_now_iso(),
    }


def import_session_from_cdp(
    *,
    cdp_url: str = "http://127.0.0.1:9222",
    state_root: Path | None = None,
    session_name: str = DEFAULT_SESSION_NAME,
    username_hint: str = "",
    bind_patent_center: bool = True,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Import cookies from an already-logged-in Chrome via CDP and save storage_state.

    Operator flow (avoids headless Okta password lockouts)::

      1. On a machine with a display, start Chrome with remote debugging, e.g.::
           google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/uspto-chrome-profile
      2. Sign in to MyUSPTO / Patent Center (authenticator MFA) in that window.
      3. Run: uspto_login_cli.py import-cdp --cdp-url http://127.0.0.1:9222

    Never re-enters password/OTP. Never clicks reset/unlock.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return {"ok": False, "code": "playwright_missing", "message": str(exc)}

    root = state_root or default_state_root()
    path = session_path(root, name=session_name)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=int(timeout_seconds * 1000))
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "code": "cdp_connect_failed",
                "message": (
                    f"Could not connect to Chrome CDP at {cdp_url}: {exc}. "
                    "Start Chrome with --remote-debugging-port=9222 after signing in."
                ),
            }
        try:
            # Prefer an existing context (operator Chrome profile).
            contexts = list(browser.contexts or [])
            if not contexts:
                return {
                    "ok": False,
                    "code": "cdp_no_context",
                    "message": "CDP connected but no browser contexts found",
                }
            context = contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(min(45_000, int(timeout_seconds * 1000)))
            pc_ok = False
            if bind_patent_center:
                try:
                    pc_ok = _bind_patent_center_sso(page, context, attempts=4)
                except Exception:
                    pc_ok = False
            storage = context.storage_state()
            cookies = storage.get("cookies") if isinstance(storage, dict) else []
            cookie_count = len(cookies or [])
            domains = sorted(
                {
                    str(c.get("domain") or "")
                    for c in (cookies or [])
                    if isinstance(c, dict)
                }
            )
            has_pc = any("patentcenter" in d for d in domains)
            has_my = any("my.uspto" in d or d.endswith("uspto.gov") for d in domains)
            logged_in = bool(pc_ok or (has_pc and cookie_count > 0))
            if cookie_count == 0:
                logged_in = False
                message = "cdp_session_empty_cookies"
            elif pc_ok:
                message = "cdp_import_patent_center_ok"
            elif has_pc:
                message = "cdp_import_has_patentcenter_cookies"
                logged_in = True
            elif has_my:
                message = "cdp_import_myuspto_only"
                logged_in = False
            else:
                message = "cdp_import_no_uspto_cookies"
                logged_in = False
            hint = username_hint or "cdp-import"
            _write_session(
                storage,
                state_root=root,
                name=session_name,
                username_hint=hint,
                logged_in=logged_in,
            )
            return {
                "schema": LOGIN_SCHEMA,
                "ok": logged_in,
                "code": "ok" if logged_in else "session_incomplete",
                "message": message,
                "session_name": session_name,
                "session_path": str(path),
                "cookie_count": cookie_count,
                "domains": domains,
                "patent_center_sso": pc_ok,
                "at_utc": utc_now_iso(),
            }
        finally:
            # Do not close the operator's Chrome — only disconnect.
            try:
                browser.close()
            except Exception:
                pass


def _firefox_profile_cookie_dbs() -> list[Path]:
    """Candidate Snap / desktop Firefox profile cookie databases (newest first)."""
    roots = [
        Path.home() / "snap/firefox/common/.mozilla/firefox",
        Path.home() / ".mozilla/firefox",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(root.rglob("cookies.sqlite"))
    return sorted(
        {p.resolve() for p in found if p.is_file()},
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _copy_sqlite_for_read(src: Path) -> Path:
    """Copy a possibly-live SQLite DB (and WAL/SHM) into a temp file for safe reads."""
    import shutil
    import tempfile

    td = Path(tempfile.mkdtemp(prefix="uspto_ff_cookies_"))
    dst = td / src.name
    shutil.copy2(src, dst)
    for suf in ("-wal", "-shm"):
        side = Path(str(src) + suf)
        if side.is_file():
            try:
                shutil.copy2(side, Path(str(dst) + suf))
            except OSError:
                pass
    return dst


def _moz_samesite(value: Any) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "Lax"
    # Firefox: 0=none, 1=lax, 2=strict (3 sometimes = unspecified)
    return {0: "None", 1: "Lax", 2: "Strict", 3: "Lax"}.get(code, "Lax")


def export_firefox_uspto_cookies(profile_cookie_db: Path | None = None) -> list[dict[str, Any]]:
    """Read USPTO/Okta/Patent Center cookies from a Firefox cookies.sqlite.

    Never returns cookie *values* in logs — callers must not print values.
    """
    import sqlite3

    dbs = [profile_cookie_db] if profile_cookie_db else _firefox_profile_cookie_dbs()
    if not dbs:
        return []
    best: list[dict[str, Any]] = []
    best_score = -1
    for db in dbs:
        try:
            copy = _copy_sqlite_for_read(Path(db))
            con = sqlite3.connect(str(copy))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT host, name, value, path, expiry, isSecure, isHttpOnly, sameSite
                FROM moz_cookies
                WHERE host LIKE '%uspto%'
                   OR host LIKE '%okta%'
                   OR host LIKE '%patent%'
                ORDER BY host, name
                """
            ).fetchall()
            con.close()
        except Exception:
            continue
        cookies: list[dict[str, Any]] = []
        for row in rows:
            exp = int(row["expiry"] or 0)
            if exp > 10_000_000_000:
                exp //= 1000
            same = _moz_samesite(row["sameSite"])
            secure = bool(row["isSecure"])
            if same == "None" and not secure:
                secure = True
            cookies.append(
                {
                    "name": row["name"],
                    "value": row["value"] or "",
                    "domain": row["host"],
                    "path": row["path"] or "/",
                    "expires": exp if exp > 0 else -1,
                    "httpOnly": bool(row["isHttpOnly"]),
                    "secure": secure,
                    "sameSite": same,
                }
            )
        names = {c["name"] for c in cookies}
        domains = {c["domain"] for c in cookies}
        score = 0
        if "MyUSPTOToken" in names:
            score += 10
        if "OktaAccessToken" in names or "OktaRefreshToken" in names:
            score += 20
        if any("patentcenter" in d for d in domains):
            score += 30
        if any(c["name"] == "userLoggedIn" for c in cookies):
            score += 50
        score += min(len(cookies), 20)
        if score > best_score:
            best_score = score
            best = cookies
    return best


def import_session_from_firefox(
    *,
    state_root: Path | None = None,
    session_name: str = DEFAULT_SESSION_NAME,
    username_hint: str = "",
    profile_cookie_db: str | Path | None = None,
    verify: bool = True,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Import a live Snap/desktop Firefox USPTO session into Playwright storage_state.

    Operator flow (preferred when Playwright password login is blocked by Okta)::

      1. Sign in to MyUSPTO + Patent Center in Snap Firefox (XRDP is fine).
      2. Run: uspto_login_cli.py import-firefox
      3. Run export-ui / portfolio commands using the saved session.

    Does **not** type username/password/OTP. Copies cookies only.
    """
    root = state_root or default_state_root()
    path = session_path(root, name=session_name)
    db_path = Path(profile_cookie_db).expanduser() if profile_cookie_db else None
    cookies = export_firefox_uspto_cookies(db_path)
    if not cookies:
        return {
            "schema": LOGIN_SCHEMA,
            "ok": False,
            "code": "firefox_no_uspto_cookies",
            "message": (
                "No USPTO cookies found in Firefox profiles. "
                "Sign in via Snap Firefox first, then re-run import-firefox."
            ),
            "session_name": session_name,
            "at_utc": utc_now_iso(),
        }

    names = sorted({c["name"] for c in cookies})
    domains = sorted({str(c.get("domain") or "") for c in cookies})
    has_pc = any("patentcenter" in d for d in domains)
    has_okta = any(n.startswith("Okta") for n in names)
    has_my = "MyUSPTOToken" in names
    token_left: int | None = None
    try:
        import base64

        tok = next(c["value"] for c in cookies if c["name"] == "MyUSPTOToken")
        payload = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
        token_left = int(payload.get("exp") or 0) - int(time.time())
        if not username_hint and payload.get("sub"):
            username_hint = _username_hint(str(payload["sub"]))
    except Exception:
        pass

    storage: dict[str, Any] = {"cookies": cookies, "origins": []}
    pc_ok = False
    message = "firefox_cookies_copied"

    if verify:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return {"ok": False, "code": "playwright_missing", "message": str(exc)}

        display = (os.environ.get("DISPLAY") or "").strip()
        if not display and Path("/tmp/.X11-unix/X10").exists():
            os.environ["DISPLAY"] = ":10.0"
            os.environ.setdefault("XAUTHORITY", str(Path.home() / ".Xauthority"))

        with sync_playwright() as playwright:
            # Prefer Firefox engine; fall back to chromium if unavailable.
            try:
                browser = _launch_operator_browser(
                    playwright, headless=None, browser="firefox"
                )
                engine = "firefox"
            except Exception:
                browser = _launch_operator_browser(
                    playwright, headless=None, browser="chromium"
                )
                engine = "chromium"
            try:
                context = _new_operator_context(browser, browser_engine=engine)
                for cookie in cookies:
                    try:
                        context.add_cookies([cookie])
                    except Exception:
                        continue
                page = context.new_page()
                page.set_default_timeout(min(45_000, int(timeout_seconds * 1000)))
                try:
                    page.goto(
                        PATENT_CENTER_LOGIN_URL + "/",
                        wait_until="domcontentloaded",
                        timeout=45_000,
                    )
                    page.wait_for_timeout(800)
                except Exception:
                    pass
                try:
                    pc_ok = _pc_user_logged_in(page)
                except Exception:
                    pc_ok = False
                if not pc_ok:
                    try:
                        pc_ok = _bind_patent_center_sso(page, context, attempts=3)
                    except Exception:
                        pc_ok = False
                storage = context.storage_state()
                cookies2 = storage.get("cookies") if isinstance(storage, dict) else []
                if isinstance(cookies2, list) and cookies2:
                    domains = sorted(
                        {
                            str(c.get("domain") or "")
                            for c in cookies2
                            if isinstance(c, dict)
                        }
                    )
                    names = sorted(
                        {
                            str(c.get("name") or "")
                            for c in cookies2
                            if isinstance(c, dict)
                        }
                    )
                    has_pc = any("patentcenter" in d for d in domains)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        message = (
            "firefox_import_patent_center_ok"
            if pc_ok
            else "firefox_import_cookies_saved_unverified_pc"
        )
    else:
        message = "firefox_cookies_saved_no_verify"

    # When verify runs, trust only the live Patent Center auth check — cookie
    # presence alone is not enough (Okta access tokens expire in ~30 minutes).
    if verify:
        logged_in = bool(pc_ok)
        if not pc_ok:
            message = (
                "firefox_import_cookies_saved_but_pc_not_logged_in"
                if has_pc or has_my or has_okta
                else "firefox_import_incomplete_no_patentcenter"
            )
    else:
        logged_in = bool((has_pc and has_okta) or (has_pc and has_my))

    cookie_count = len(storage.get("cookies") or []) if isinstance(storage, dict) else 0
    hint = username_hint or "firefox-import"
    _write_session(
        storage,
        state_root=root,
        name=session_name,
        username_hint=hint,
        logged_in=logged_in,
    )
    return {
        "schema": LOGIN_SCHEMA,
        "ok": logged_in,
        "code": "ok" if logged_in else "session_incomplete",
        "message": message,
        "session_name": session_name,
        "session_path": str(path),
        "cookie_count": cookie_count,
        "domains": domains,
        "cookie_names": names,
        "patent_center_sso": pc_ok,
        "myuspto_token_left_seconds": token_left,
        "at_utc": utc_now_iso(),
    }


def _write_session(
    storage_state: Mapping[str, Any],
    *,
    state_root: Path | None,
    name: str,
    username_hint: str,
    logged_in: bool,
) -> Path:
    path = session_path(state_root, name=name)
    meta = session_meta_path(state_root, name=name)
    # Never embed secrets into storage_state on disk beyond browser cookies.
    path.write_text(json.dumps(storage_state, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    meta.write_text(
        json.dumps(
            {
                "schema": LOGIN_SCHEMA,
                "session_name": name,
                "updated_at_utc": utc_now_iso(),
                "username_hint": username_hint,
                "logged_in": logged_in,
                "cookie_count": len(storage_state.get("cookies") or [])
                if isinstance(storage_state, Mapping)
                else 0,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(meta, 0o600)
    return path


def _visible_input(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = loc.count()
            for i in range(min(count, 6)):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        return el
                except Exception:
                    continue
        except Exception:
            continue
    return None


# Never click recovery / account-reset surfaces during automated sign-in.
_FORBIDDEN_CLICK_TEXT: Final[tuple[str, ...]] = (
    "forgot password",
    "reset password",
    "reset your password",
    "change password",
    "unlock account",
    "unlock your account",
    "create a uspto.gov account",
    "create account",
    "help",
    "back to sign in",
    "cancel",
)


def _element_text_blob(el: Any) -> str:
    parts: list[str] = []
    for attr in ("inner_text",):
        try:
            parts.append(str(el.inner_text() or ""))
        except Exception:
            pass
    for name in ("aria-label", "title", "value", "name", "href", "data-se"):
        try:
            parts.append(str(el.get_attribute(name) or ""))
        except Exception:
            pass
    return " ".join(parts).lower()


def _is_forbidden_click_target(el: Any) -> bool:
    blob = _element_text_blob(el)
    if not blob.strip():
        return False
    return any(bad in blob for bad in _FORBIDDEN_CLICK_TEXT)


def _click_first(page: Any, selectors: tuple[str, ...], *, timeout_ms: int = 1_200) -> bool:
    """Click first visible match that is not a password-reset / unlock control.

    Uses a short per-click timeout so MFA chooser loops cannot stall for the
    full page default (30s) on each selector.
    """
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = loc.count()
            for i in range(min(count, 8)):
                el = loc.nth(i)
                try:
                    if not el.is_visible(timeout=400):
                        continue
                    if _is_forbidden_click_target(el):
                        continue
                    el.click(timeout=max(200, int(timeout_ms)))
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _looks_logged_in(page: Any, *, storage: Mapping[str, Any] | None = None) -> bool:
    cookies = []
    if isinstance(storage, Mapping):
        cookies = list(storage.get("cookies") or [])
    # Require real session cookies for success — empty storage_state is a false positive.
    if cookies:
        domains = " ".join(str(c.get("domain") or "") for c in cookies if isinstance(c, dict))
        if "uspto.gov" in domains or "okta" in domains.lower():
            return True
    selectors = (
        "text=Log Out",
        "text=Logout",
        "text=Sign Out",
        "text=My Workbench",
        "text=Workbench",
        "a[href*='logout' i]",
        "text=MyUSPTO",
    )
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0 and "auth.uspto.gov" not in (page.url or ""):
                # Prefer cookie evidence; UI alone is weak without cookies.
                if cookies:
                    return True
        except Exception:
            continue
    try:
        url = page.url or ""
        if cookies and "my.uspto.gov" in url and "auth.uspto.gov" not in url:
            return True
        if cookies and "patentcenter.uspto.gov" in url and "auth.uspto.gov" not in url:
            return True
    except Exception:
        pass
    return False


def _type_into(el: Any, text: str, *, delay_ms: int = 12) -> None:
    """Type into Okta-controlled inputs without desyncing React/Okta state.

    Prefer Playwright fill / press_sequentially. Avoid assigning ``node.value``
    directly — that often leaves Okta's model empty so Verify submits wrong
    credentials and surfaces as ``bad_credentials``.
    """
    value = str(text or "")
    el.click(timeout=5_000)
    try:
        el.fill("")
    except Exception:
        try:
            el.press("Control+a")
            el.press("Backspace")
        except Exception:
            pass
    typed_ok = False
    # fill is accurate for long passwords and updates React controlled inputs.
    try:
        el.fill(value)
        typed_ok = True
    except Exception:
        typed_ok = False
    if not typed_ok:
        try:
            el.press_sequentially(value, delay=max(0, int(delay_ms)))
            typed_ok = True
        except Exception:
            try:
                el.type(value, delay=max(0, int(delay_ms)))
                typed_ok = True
            except Exception:
                pass
    # Length-only check (never log the secret). Retry once via sequential keys.
    try:
        got = el.input_value() or ""
        if len(got) != len(value):
            print(
                f"LOGIN_DIAG field_len_mismatch got={len(got)} expected={len(value)}",
                flush=True,
            )
            try:
                el.fill("")
            except Exception:
                pass
            try:
                el.press_sequentially(value, delay=max(8, int(delay_ms)))
            except Exception:
                try:
                    el.fill(value)
                except Exception:
                    pass
            got2 = el.input_value() or ""
            print(
                f"LOGIN_DIAG field_len_after_retry got={len(got2)} expected={len(value)}",
                flush=True,
            )
        else:
            print(f"LOGIN_DIAG field_len_ok len={len(got)}", flush=True)
    except Exception:
        pass


def _okta_body_lower(page: Any) -> str:
    try:
        return (page.inner_text("body") or "").lower()
    except Exception:
        return ""


def _page_says_account_locked(page: Any) -> bool:
    """True when Okta body indicates an active lock / too-many-attempts block.

    Do **not** match bare \"Unlock account\" nav links — those appear on healthy
    sign-in pages and caused false ``account_locked`` stops.
    """
    body = _okta_body_lower(page)
    needles = (
        "account is locked",
        "account locked",
        "your account has been locked",
        "your account is locked",
        "too many attempts",
        "too many failed",
        "maximum number of failed",
        "temporarily locked",
        "locked due to too many",
        "account is temporarily unavailable",
        "this account has been locked",
    )
    return any(n in body for n in needles)


def _page_says_bad_credentials(page: Any) -> bool:
    """True for the generic Okta credential error.

    Note: when the account is locked, Okta often still shows
    \"Username or password are incorrect\" rather than an explicit lock banner.
    Prefer :func:`_raise_if_okta_auth_rejected` so operators get lock guidance.
    """
    body = _okta_body_lower(page)
    needles = (
        "username or password are incorrect",
        "unable to sign in",
        "unable to sign-in",
        "authentication failed",
        "we found some errors",
    )
    return any(n in body for n in needles)


def _raise_if_okta_auth_rejected(page: Any, *, step: str) -> None:
    """Raise a typed LoginError for lock vs credential rejection.

    Policy: never auto-retry from here. Locked accounts need operator unlock
    (browser). Generic \"incorrect password\" is frequently a lock in disguise
    after repeated headless attempts — surface that so automation stops.
    """
    if _page_says_account_locked(page):
        raise LoginError(
            f"Okta reports account locked at {step}. "
            "Unlock in a normal browser, then re-run login once. "
            "Do not auto-retry (deepens lock).",
            code="account_locked",
        )
    if _page_says_bad_credentials(page):
        # Same UI text is commonly returned while locked; treat as stop signal.
        # Okta IDX returns HTTP 401 + E0000004 for both wrong password AND many
        # lockout cases (not only E0000011 "User Locked"). A successful
        # laptop Firefox login while headless fails usually means lock/rate
        # limit or risk policy — not a bad fill of credentials.passcode.
        raise LoginError(
            f"Okta rejected sign-in at {step} "
            "(\"username or password are incorrect\" / E0000004). "
            "Automation did reach Okta IDX challenge/answer with a full "
            "password field. If the same password works in Firefox/Chrome, "
            "treat this as account lock, rate-limit, or risk policy — "
            "unlock/wait on a real browser, then retry once. "
            "Do not hammer automated login.",
            code="bad_credentials_or_locked",
        )


def _fill_okta_identifier(page: Any, username: str) -> None:
    # Never use bare input[type=text] — MyUSPTO marketing page has a newsletter email box.
    el = _visible_input(
        page,
        (
            "input[name='identifier']",
            "input[autocomplete='username']",
            "input[id*='input' i][name='identifier']",
        ),
    )
    if el is None:
        raise LoginError("Okta username/identifier field not found", code="identifier_field_missing")
    _type_into(el, username, delay_ms=8)
    if not _click_first(
        page,
        (
            "input[type='submit'][value='Next']",
            "input[type='submit'][value*='Next' i]",
            "input.button-primary[type='submit']",
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Next')",
            "button:has-text('Continue')",
        ),
    ):
        el.press("Enter")
    # Brief settle for Okta SPA transition (keep short for OTP window).
    page.wait_for_timeout(400)
    _raise_if_okta_auth_rejected(page, step="identifier")


def _fill_password(page: Any, password: str) -> None:
    """Step 2 only: enter account password. Never click forgot/reset/unlock.

    Intended Okta path:
      identifier (email) → password field → Verify/Sign In → MFA OTP
    """
    deadline = time.time() + 20
    el = None
    while time.time() < deadline and el is None:
        # Only the Okta "password factor" tile — never generic "Password" text
        # (that matched Forgot password / Reset password and must not be clicked).
        _click_first(
            page,
            (
                "div[data-se='okta_password']",
                "[data-se='okta_password']",
                "div[data-se='okta_password'] a",
                "a[data-se='okta_password']",
            ),
        )
        el = _visible_input(
            page,
            (
                "input[type='password']",
                "input[autocomplete='current-password']",
                "input[name='password']",
                # Okta sometimes labels the password box credentials.passcode
                # (type=password). Prefer type=password above.
                "input[type='password'][name='credentials.passcode']",
            ),
        )
        if el is None:
            _raise_if_okta_auth_rejected(page, step="password_field_wait")
            page.wait_for_timeout(150)
    if el is None:
        raise LoginError("password field not found after identifier step", code="password_field_missing")
    _type_into(el, password, delay_ms=12)
    # Let Okta settle controlled-input state before Verify.
    page.wait_for_timeout(250)
    if not _click_first(
        page,
        (
            "input[type='submit'][value='Verify']",
            "input[type='submit'][value='Sign In']",
            "input[type='submit'][value='Sign in']",
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Verify')",
            "button:has-text('Sign In')",
            "button:has-text('Sign in')",
            "button:has-text('Log In')",
            # Deliberately NOT clicking generic "Next" after password when Verify exists.
        ),
    ):
        el.press("Enter")
    # Wait longer for SPA error vs MFA transition (avoid false early fail).
    page.wait_for_timeout(900)
    _raise_if_okta_auth_rejected(page, step="password")


def _wait_otp_code_from_file(path: Path, *, timeout_seconds: float = 90.0) -> str:
    """Poll a local file for a fresh OTP once MFA is visible (minimal pre-OTP work)."""
    deadline = time.time() + max(5.0, float(timeout_seconds))
    path = Path(path).expanduser()
    # Clear stale codes so we don't consume an old OTP.
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
    print(
        f"AWAITING_OTP file={path} (write a 6-digit code, e.g. echo 123456 > {path})",
        flush=True,
    )
    last_mtime = None
    while time.time() < deadline:
        try:
            if path.is_file():
                st = path.stat()
                if last_mtime is None or st.st_mtime != last_mtime:
                    last_mtime = st.st_mtime
                    code = re.sub(r"\s+", "", path.read_text(encoding="utf-8").strip())
                    if re.fullmatch(r"\d{6}", code):
                        print("OTP_RECEIVED", flush=True)
                        return code
        except OSError:
            pass
        time.sleep(0.25)
    raise LoginError(
        f"timed out waiting for OTP in {path}",
        code="otp_wait_timeout",
    )


def _leave_email_mfa_path(page: Any) -> bool:
    """If Okta landed on email challenge (reset-style), switch authenticator.

    Login MFA for this operator account is authenticator-app / TOTP — not email.
    Email verify is treated as the wrong path (password-reset style).
    """
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        body = ""
    on_email = any(
        k in body
        for k in (
            "verify with your email",
            "verification email",
            "send me an email",
            "we sent you a verification email",
            "get a verification email",
            "email authenticator",
        )
    )
    if not on_email:
        return False
    print("LOGIN_DIAG mfa_leave_email_path", flush=True)
    # Prefer the explicit "something else" chooser; never "Send again" / email.
    clicked = _click_first(
        page,
        (
            "a:has-text('Verify with something else')",
            "button:has-text('Verify with something else')",
            "div[role='link']:has-text('Verify with something else')",
            "a:has-text('something else')",
            "button:has-text('something else')",
            "a:has-text('Select another')",
            "button:has-text('Select another')",
            "a:has-text('Choose another')",
            "button:has-text('Choose another')",
            # Never: Send again / email / Back to sign in / password reset.
        ),
        timeout_ms=1_200,
    )
    if clicked:
        page.wait_for_timeout(400)
    return True


def _select_otp_authenticator(page: Any) -> None:
    """Pick login MFA *authenticator app / TOTP code entry* only.

    Never select email MFA (that path is for password-reset style recovery).
    Never click forgot / reset / unlock.
    """
    _leave_email_mfa_path(page)

    # Authenticator-app tiles only (data-se is precise).
    _click_first(
        page,
        (
            "div[data-se='google_otp']",
            "div[data-se='okta_verify-totp']",
            "[data-se='google_otp']",
            "[data-se='okta_verify-totp']",
            "div[data-se='okta_verify'] a",
            "div[data-se='okta_verify']",
            "[data-se='okta_verify']",
            # Some Okta builds use phone_number only for SMS — skip email/sms.
        ),
        timeout_ms=800,
    )
    # Explicit authenticator labels — no Email tiles.
    _click_first(
        page,
        (
            "div[role='link']:has-text('Google Authenticator')",
            "a:has-text('Google Authenticator')",
            "div[role='button']:has-text('Google Authenticator')",
            "div[role='link']:has-text('Okta Verify')",
            "a:has-text('Okta Verify')",
            "div[role='button']:has-text('Okta Verify')",
            "div[role='link']:has-text('Authenticator')",
            "a:has-text('Authenticator app')",
            "div[role='link']:has-text('Enter a code')",
            "a:has-text('Enter a code')",
            "button:has-text('Enter a code')",
            "div[role='link']:has-text('Enter code')",
            "a:has-text('Enter code from app')",
        ),
        timeout_ms=800,
    )
    # If still on email after chooser, try leave again once.
    _leave_email_mfa_path(page)
    _click_first(
        page,
        (
            "div[data-se='google_otp']",
            "div[data-se='okta_verify-totp']",
            "div[role='link']:has-text('Google Authenticator')",
            "a:has-text('Google Authenticator')",
            "div[role='link']:has-text('Okta Verify')",
            "a:has-text('Okta Verify')",
            "div[role='link']:has-text('Enter a code')",
            "a:has-text('Enter a code')",
        ),
        timeout_ms=800,
    )


def _fill_otp(page: Any, code: str) -> None:
    code = re.sub(r"\s+", "", str(code or ""))
    if not code:
        raise LoginError("OTP code is empty", code="empty_otp")
    _select_otp_authenticator(page)
    deadline = time.time() + 25
    el = None
    while time.time() < deadline and el is None:
        _select_otp_authenticator(page)
        named = _visible_input(
            page,
            (
                "input[name='credentials.passcode']",
                "input[autocomplete='one-time-code']",
                "input[name*='otp' i]",
                "input[name*='code' i]",
                "input[inputmode='numeric']",
            ),
        )
        # Avoid generic text that might be username; prefer tel/numeric.
        el = named or _visible_input(page, ("input[type='tel']",))
        if el is None:
            page.wait_for_timeout(120)
    if el is None:
        # Best-effort diagnostics for operator debugging (no secrets).
        try:
            Path("/tmp/uspto_otp_field_missing.png")
            page.screenshot(path="/tmp/uspto_otp_field_missing.png", full_page=True)
            body = re.sub(r"\S+@\S+", "[email]", (page.inner_text("body") or "")[:2000])
            Path("/tmp/uspto_otp_field_missing_body.txt").write_text(body, encoding="utf-8")
            Path("/tmp/uspto_otp_field_missing_url.txt").write_text(
                (page.url or "") + "\n", encoding="utf-8"
            )
        except Exception:
            pass
        raise LoginError("OTP field not found", code="otp_field_missing")
    _type_into(el, code, delay_ms=10)
    if not _click_first(
        page,
        (
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Verify')",
            "button:has-text('Continue')",
            "button:has-text('Submit')",
        ),
    ):
        el.press("Enter")


def _pc_user_logged_in(page: Any) -> bool:
    """True when Patent Center reports userLoggedIn via public auth check."""
    try:
        rid = str(int(time.time() * 1000) % 10_000_000)
        resp = page.request.get(
            f"{PATENT_CENTER_LOGIN_URL}/manage/public/auth/check?rid={rid}"
        )
        text = (resp.text() or "").replace(" ", "")
        return '"userLoggedIn":true' in text
    except Exception:
        return False


def _bind_patent_center_sso(page: Any, context: Any, *, attempts: int = 6) -> bool:
    """Hydrate Patent Center cookies/tokens from an authenticated MyUSPTO browser.

    Must never click password-reset / unlock surfaces. Only navigates PC / MyUSPTO
    and optional "Sign in" that continues SSO.
    """
    for attempt in range(max(1, attempts)):
        print(f"LOGIN_STEP patent_center_sso_attempt={attempt + 1}", flush=True)
        if _pc_user_logged_in(page):
            return True
        # Visit MyUSPTO home first so Okta session is sticky, then Patent Center.
        try:
            page.goto(MYUSPTO_HOME_URL, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(600)
        except Exception:
            pass
        try:
            page.goto(
                PATENT_CENTER_LOGIN_URL + "/",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            page.wait_for_timeout(1200)
        except Exception:
            pass
        # If PC shows a sign-in CTA, click only exact sign-in (never unlock/reset).
        _click_first(
            page,
            (
                "a.btn:has-text('Sign in')",
                "a:has-text('Sign in with USPTO.gov')",
                "button:has-text('Sign in')",
                "a:has-text('Sign in')",
            ),
        )
        # Allow Okta redirect + callback.
        deadline = time.time() + 20
        while time.time() < deadline:
            if _pc_user_logged_in(page):
                return True
            url = page.url or ""
            if "auth.uspto.gov" in url:
                # Session may auto-complete without interaction.
                page.wait_for_timeout(500)
                continue
            page.wait_for_timeout(400)
        # Hard reload PC root once per attempt.
        try:
            page.goto(
                PATENT_CENTER_LOGIN_URL + "/",
                wait_until="networkidle",
                timeout=60_000,
            )
        except Exception:
            pass
        if _pc_user_logged_in(page):
            return True
    return _pc_user_logged_in(page)


def upgrade_session_for_patent_center(
    *,
    state_root: Path | None = None,
    session_name: str = DEFAULT_SESSION_NAME,
    headless: bool = True,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Upgrade an existing MyUSPTO storage_state into Patent Center SSO.

    Does not re-enter password/OTP. Uses cookies already on disk.
    """
    root = state_root or default_state_root()
    path = session_path(root, name=session_name)
    if not path.is_file():
        return {
            "ok": False,
            "code": "no_session",
            "message": "no storage_state to upgrade; run login first",
        }
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return {"ok": False, "code": "playwright_missing", "message": str(exc)}

    with sync_playwright() as playwright:
        browser = _launch_operator_browser(playwright, headless=headless)
        context = _new_operator_context(browser, storage_state=str(path))
        page = context.new_page()
        page.set_default_timeout(min(45_000, int(timeout_seconds * 1000)))
        try:
            ok = _bind_patent_center_sso(page, context, attempts=6)
            storage = context.storage_state()
            cookies = storage.get("cookies") if isinstance(storage, dict) else []
            cookie_count = len(cookies or [])
            domains = sorted(
                {
                    str(c.get("domain") or "")
                    for c in (cookies or [])
                    if isinstance(c, dict)
                }
            )
            meta = session_meta_path(root, name=session_name)
            hint = None
            if meta.is_file():
                try:
                    hint = json.loads(meta.read_text(encoding="utf-8")).get(
                        "username_hint"
                    )
                except (OSError, json.JSONDecodeError):
                    hint = None
            _write_session(
                storage,
                state_root=root,
                name=session_name,
                username_hint=str(hint or ""),
                logged_in=bool(ok),
            )
            return {
                "ok": bool(ok),
                "code": "ok" if ok else "patent_center_sso_incomplete",
                "message": (
                    "patent_center_userLoggedIn"
                    if ok
                    else "could_not_set_userLoggedIn"
                ),
                "cookie_count": cookie_count,
                "domains": domains,
                "session_path": str(path),
            }
        finally:
            context.close()
            browser.close()


def login_patent_center(
    *,
    username_ref: str = "env:USPTO_USERNAME",
    password_ref: str = "env:USPTO_PASSWORD",
    otp_mode: str = "prompt",
    otp_ref: str = "",
    totp_secret_ref: str = "env:USPTO_TOTP_SECRET",
    otp_code: str = "",
    otp_file: str | Path | None = None,
    otp_wait_seconds: float = 90.0,
    state_root: Path | None = None,
    session_name: str = DEFAULT_SESSION_NAME,
    headless: bool | None = None,
    browser: str = "chromium",
    login_url: str = DEFAULT_LOGIN_ENTRY_URL,
    timeout_seconds: float = 180.0,
    allow_prompt: bool = True,
    otp_provider: Callable[[], str] | None = None,
) -> LoginResult:
    """Log into USPTO Okta (MyUSPTO) then bind session for Patent Center.

    Parameters
    ----------
    otp_mode:
        ``prompt`` — ask operator for current OTP
        ``totp`` — generate from ``totp_secret_ref``
        ``code`` — use one-shot ``otp_code`` / ``otp_ref``, else wait on ``otp_file``
        ``file`` — always wait on ``otp_file`` after password (best for chat OTP)
        ``none`` — password-only (if account has no MFA)
    headless:
        ``None`` (default) — headed when ``DISPLAY`` is set (XRDP/ssh -Y), else headless.
        Prefer headed: headless Chromium is often rejected by Okta with E0000004.
    browser:
        ``chromium`` (default) or ``firefox``. Firefox is closer to the operator
        path that succeeds on XRDP.
    """
    started = utc_now_iso()
    mode = str(otp_mode or "prompt").strip().lower()
    if mode not in {"prompt", "totp", "code", "file", "none"}:
        raise LoginError(f"unsupported otp_mode: {mode}", code="invalid_otp_mode")

    username = resolve_secret_ref(
        username_ref, prompt_label="USPTO username", allow_prompt=allow_prompt
    )
    password = resolve_secret_ref(
        password_ref, prompt_label="USPTO password", allow_prompt=allow_prompt
    )
    hint = _username_hint(username)
    otp_path = Path(
        otp_file
        or os.environ.get("USPTO_OTP_FILE")
        or "/tmp/uspto_otp_now.txt"
    ).expanduser()

    def _resolve_otp() -> str:
        if otp_provider is not None:
            return re.sub(r"\s+", "", str(otp_provider() or ""))
        if mode == "none":
            return ""
        if mode == "file":
            return _wait_otp_code_from_file(otp_path, timeout_seconds=otp_wait_seconds)
        if mode == "code":
            if otp_code.strip():
                return re.sub(r"\s+", "", otp_code.strip())
            if otp_ref.strip():
                return re.sub(
                    r"\s+",
                    "",
                    resolve_secret_ref(
                        otp_ref, prompt_label="USPTO OTP", allow_prompt=allow_prompt
                    ),
                )
            # No pre-supplied code: wait on file so operator can race a fresh OTP.
            return _wait_otp_code_from_file(otp_path, timeout_seconds=otp_wait_seconds)
        if mode == "totp":
            secret = resolve_secret_ref(
                totp_secret_ref,
                prompt_label="USPTO TOTP secret",
                allow_prompt=False,
            )
            return generate_totp(secret)
        if allow_prompt:
            return re.sub(r"\s+", "", getpass.getpass("USPTO OTP / MFA code: ").strip())
        raise LoginError("otp_mode=prompt requires an interactive terminal", code="prompt_unavailable")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise LoginError(
            "playwright is required (pip install playwright && playwright install chromium)",
            code="playwright_missing",
        ) from exc

    logged_in = False
    message = "login_incomplete"
    path = session_path(state_root, name=session_name)
    cookie_count = 0

    with sync_playwright() as playwright:
        browser_engine = (browser or "chromium").strip().lower()
        browser = _launch_operator_browser(
            playwright, headless=headless, browser=browser_engine
        )
        context = _new_operator_context(browser, browser_engine=browser_engine)
        page = context.new_page()
        page.set_default_timeout(min(30_000, int(timeout_seconds * 1000)))
        try:
            # /home triggers Okta authorize faster than marketing landing page.
            page.goto(login_url, wait_until="domcontentloaded", timeout=45_000)
            deadline = time.time() + 25
            while time.time() < deadline:
                url = page.url or ""
                if "auth.uspto.gov" in url:
                    break
                if "my.uspto.gov" in url and "/home" not in url:
                    _click_first(
                        page,
                        (
                            "a.user-link:has-text('Sign in')",
                            "a.btn:has-text('Sign in')",
                            "a:has-text('Log in with your USPTO.gov account')",
                            "a:has-text('Sign in')",
                        ),
                    )
                page.wait_for_timeout(100)
            try:
                page.wait_for_selector(
                    "input[name='identifier'], input[autocomplete='username']",
                    timeout=25_000,
                    state="visible",
                )
            except Exception as exc:
                raise LoginError(
                    "Okta username/identifier field not found",
                    code="identifier_field_missing",
                ) from exc

            print("LOGIN_STEP identifier", flush=True)
            _fill_okta_identifier(page, username)
            print("LOGIN_STEP password", flush=True)
            # Password step (or authenticator select → password).
            try:
                page.wait_for_selector(
                    "input[type='password'], input[name='credentials.passcode'], "
                    "div[data-se='okta_password'], [data-se='okta_password']",
                    timeout=20_000,
                    state="visible",
                )
            except Exception as exc:
                try:
                    _raise_if_okta_auth_rejected(page, step="password_field_wait")
                except LoginError:
                    raise
                raise LoginError(
                    "password field not found after identifier step",
                    code="password_field_missing",
                ) from exc
            if _visible_input(page, ("input[type='password']", "input[autocomplete='current-password']")) is not None:
                _fill_password(page, password)
            elif _visible_input(page, ("input[name='credentials.passcode']",)) is not None:
                # Some Okta builds label password as credentials.passcode.
                _fill_password(page, password)
            else:
                _fill_password(page, password)

            if mode != "none":
                print("LOGIN_STEP mfa", flush=True)
                # Prefer authenticator chooser → code field ASAP.
                # For file-mode chat OTPs: start waiting immediately so the operator
                # can race a code while we keep probing the MFA UI.
                needs_otp = mode in {"prompt", "totp", "code", "file"}
                field_ready = False
                try:
                    body0 = (page.inner_text("body") or "")
                    print(
                        "LOGIN_DIAG mfa_body="
                        + re.sub(r"\s+", " ", body0)[:220],
                        flush=True,
                    )
                except Exception:
                    pass
                _select_otp_authenticator(page)
                # Race: begin OTP file wait in parallel conceptually by starting
                # resolve as soon as we see MFA chrome (not only after field ready).
                mfa_deadline = time.time() + 8
                while time.time() < mfa_deadline:
                    if "auth.uspto.gov" not in (page.url or ""):
                        needs_otp = False
                        break
                    _select_otp_authenticator(page)
                    if (
                        _visible_input(
                            page,
                            (
                                "input[name='credentials.passcode']",
                                "input[autocomplete='one-time-code']",
                                "input[name*='otp' i]",
                                "input[inputmode='numeric']",
                                "input[type='tel']",
                            ),
                        )
                        is not None
                    ):
                        field_ready = True
                        needs_otp = True
                        break
                    try:
                        body = (page.inner_text("body") or "").lower()
                    except Exception:
                        body = ""
                    if any(
                        k in body
                        for k in (
                            "one-time",
                            "verification code",
                            "google authenticator",
                            "okta verify",
                            "enter code",
                            "security code",
                            "authenticator app",
                            "verify with",
                            "select an authenticator",
                            "send me an email",
                            "verification email",
                            "email authenticator",
                            "enter a code",
                        )
                    ):
                        needs_otp = True
                        # Do not wait the full deadline once MFA UI is clear —
                        # race to AWAITING_OTP for chat-driven codes.
                        if mode in {"file", "code", "prompt"}:
                            break
                    page.wait_for_timeout(100)
                if needs_otp and "auth.uspto.gov" in (page.url or ""):
                    if not field_ready:
                        print("LOGIN_STEP mfa_waiting_for_field", flush=True)
                    code = _resolve_otp()
                    _fill_otp(page, code)

            # Wait for redirect off Okta authorize into MyUSPTO callback/home.
            print("LOGIN_STEP post_okta", flush=True)
            deadline = time.time() + min(35.0, max(15.0, float(timeout_seconds) - 20.0))
            while time.time() < deadline:
                url = page.url or ""
                if "auth.uspto.gov" not in url and "uspto.gov" in url:
                    break
                page.wait_for_timeout(200)

            # Bind Patent Center SSO while the browser still holds Okta/MyUSPTO cookies.
            print("LOGIN_STEP patent_center_sso", flush=True)
            pc_ok = _bind_patent_center_sso(page, context)

            storage = context.storage_state()
            cookie_count = len(storage.get("cookies") or []) if isinstance(storage, dict) else 0
            domains = {
                str(c.get("domain") or "")
                for c in (storage.get("cookies") or [])
                if isinstance(c, dict)
            }
            has_pc_cookie = any("patentcenter" in d for d in domains)
            logged_in = bool(pc_ok or (has_pc_cookie and cookie_count > 0))
            if cookie_count == 0:
                logged_in = False
                message = "login_failed_empty_session_cookies"
            elif pc_ok:
                message = "login_succeeded_session_saved"
            elif has_pc_cookie:
                message = "session_has_patentcenter_cookies_unconfirmed_userLoggedIn"
                logged_in = True  # export can retry SSO with cookies
            else:
                # MyUSPTO-only cookies are not enough for private PC export.
                logged_in = False
                message = (
                    f"myuspto_only_session_cookies={cookie_count};"
                    "patent_center_sso_incomplete"
                )

            _write_session(
                storage,
                state_root=state_root,
                name=session_name,
                username_hint=hint,
                logged_in=logged_in,
            )
            if not logged_in:
                raise LoginError(
                    "USPTO login did not complete Patent Center SSO "
                    f"({message}). MyUSPTO may be signed in, but export needs "
                    "patentcenter cookies / userLoggedIn.",
                    code="patent_center_sso_incomplete",
                )
        except LoginError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LoginError(_scrub(str(exc)), code="login_failed") from exc
        finally:
            context.close()
            browser.close()

    return LoginResult(
        schema=LOGIN_SCHEMA,
        ok=logged_in,
        session_name=session_name,
        session_path=str(path),
        username_hint=hint,
        otp_mode=mode,
        logged_in=logged_in,
        message=message,
        started_at_utc=started,
        finished_at_utc=utc_now_iso(),
    )


def sanitize_tool_arguments(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop secret-bearing keys from a mapping for MCP/CLI JSON echoes."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        key_l = str(key).lower()
        if key_l in _SECRET_ECHO_KEYS or any(s in key_l for s in _SECRET_ECHO_KEYS):
            out[str(key)] = "<redacted>"
            continue
        if isinstance(value, Mapping):
            out[str(key)] = sanitize_tool_arguments(value)
        else:
            out[str(key)] = value
    return out


__all__ = [
    "FORBIDDEN_LOGIN_CAPABILITIES",
    "LOGIN_SCHEMA",
    "LoginError",
    "LoginResult",
    "SessionStatus",
    "generate_totp",
    "load_session_status",
    "login_patent_center",
    "logout_session",
    "resolve_secret_ref",
    "sanitize_tool_arguments",
    "session_path",
]
