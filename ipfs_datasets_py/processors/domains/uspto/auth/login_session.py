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


def _click_first(page: Any, selectors: tuple[str, ...]) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = loc.count()
            for i in range(min(count, 6)):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        el.click()
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


def _fill_okta_identifier(page: Any, username: str) -> None:
    el = _visible_input(
        page,
        (
            "input[name='identifier']",
            "input[autocomplete='username']",
            "input[type='email']",
            "input[type='text']",
        ),
    )
    if el is None:
        raise LoginError("Okta username/identifier field not found", code="identifier_field_missing")
    el.fill(username)
    if not _click_first(
        page,
        (
            "input[type='submit']",
            "button[type='submit']",
            "input[value='Next']",
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "input[type='submit'][value*='Sign']",
        ),
    ):
        el.press("Enter")


def _fill_password(page: Any, password: str) -> None:
    # Okta password is often step 2.
    deadline = time.time() + 30
    el = None
    while time.time() < deadline and el is None:
        el = _visible_input(
            page,
            (
                "input[type='password']",
                "input[name='credentials.passcode']",
                "input[name='password']",
                "input[autocomplete='current-password']",
            ),
        )
        if el is None:
            page.wait_for_timeout(500)
    if el is None:
        raise LoginError("password field not found after identifier step", code="password_field_missing")
    el.fill(password)
    if not _click_first(
        page,
        (
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Verify')",
            "button:has-text('Sign In')",
            "button:has-text('Log In')",
            "button:has-text('Next')",
        ),
    ):
        el.press("Enter")


def _fill_otp(page: Any, code: str) -> None:
    code = re.sub(r"\s+", "", str(code or ""))
    if not code:
        raise LoginError("OTP code is empty", code="empty_otp")
    deadline = time.time() + 45
    el = None
    while time.time() < deadline and el is None:
        el = _visible_input(
            page,
            (
                "input[name='credentials.passcode']",
                "input[autocomplete='one-time-code']",
                "input[name*='otp' i]",
                "input[name*='code' i]",
                "input[inputmode='numeric']",
                "input[type='tel']",
                "input[type='text']",
            ),
        )
        # Prefer passcode/otp-named fields over generic text if both exist.
        named = _visible_input(
            page,
            (
                "input[name='credentials.passcode']",
                "input[autocomplete='one-time-code']",
                "input[name*='otp' i]",
                "input[name*='code' i]",
            ),
        )
        if named is not None:
            el = named
        if el is None:
            page.wait_for_timeout(500)
    if el is None:
        raise LoginError("OTP field not found", code="otp_field_missing")
    el.fill(code)
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


def login_patent_center(
    *,
    username_ref: str = "env:USPTO_USERNAME",
    password_ref: str = "env:USPTO_PASSWORD",
    otp_mode: str = "prompt",
    otp_ref: str = "",
    totp_secret_ref: str = "env:USPTO_TOTP_SECRET",
    otp_code: str = "",
    state_root: Path | None = None,
    session_name: str = DEFAULT_SESSION_NAME,
    headless: bool = False,
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
        ``code`` — use one-shot ``otp_code`` or ``otp_ref``
        ``none`` — password-only (if account has no MFA)
    """
    started = utc_now_iso()
    mode = str(otp_mode or "prompt").strip().lower()
    if mode not in {"prompt", "totp", "code", "none"}:
        raise LoginError(f"unsupported otp_mode: {mode}", code="invalid_otp_mode")

    username = resolve_secret_ref(
        username_ref, prompt_label="USPTO username", allow_prompt=allow_prompt
    )
    password = resolve_secret_ref(
        password_ref, prompt_label="USPTO password", allow_prompt=allow_prompt
    )
    hint = _username_hint(username)

    def _resolve_otp() -> str:
        if otp_provider is not None:
            return re.sub(r"\s+", "", str(otp_provider() or ""))
        if mode == "none":
            return ""
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
            if allow_prompt:
                return re.sub(r"\s+", "", getpass.getpass("USPTO OTP code: ").strip())
            raise LoginError("otp_mode=code requires otp_code or otp_ref", code="missing_otp")
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
        browser = playwright.chromium.launch(headless=bool(headless))
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(min(60_000, int(timeout_seconds * 1000)))
        try:
            # MyUSPTO home redirects into Okta authorize (identifier → password → MFA).
            page.goto(login_url, wait_until="domcontentloaded", timeout=90_000)
            # Wait for Okta host; home may bounce through my.uspto.gov first.
            deadline = time.time() + 60
            while time.time() < deadline:
                url = page.url or ""
                if "auth.uspto.gov" in url:
                    break
                if "my.uspto.gov" in url:
                    _click_first(
                        page,
                        (
                            "a:has-text('Sign in')",
                            "a:has-text('Sign In')",
                            "button:has-text('Sign in')",
                            "text=Sign in",
                        ),
                    )
                page.wait_for_timeout(500)
            try:
                page.wait_for_selector(
                    "input[name='identifier'], input[autocomplete='username']",
                    timeout=45_000,
                    state="visible",
                )
            except Exception as exc:
                raise LoginError(
                    "Okta username/identifier field not found",
                    code="identifier_field_missing",
                ) from exc

            _fill_okta_identifier(page, username)
            try:
                page.wait_for_selector(
                    "input[type='password'], input[name='credentials.passcode']",
                    timeout=45_000,
                    state="visible",
                )
            except Exception as exc:
                raise LoginError(
                    "password field not found after identifier step",
                    code="password_field_missing",
                ) from exc
            # If the first post-identifier field is already OTP (rare), skip password fill path.
            if _visible_input(page, ("input[type='password']",)) is not None:
                _fill_password(page, password)
                page.wait_for_timeout(1200)

            if mode != "none":
                # Detect MFA page or always attempt when mode requests OTP.
                body = ""
                try:
                    body = (page.content() or "").lower()
                except Exception:
                    body = ""
                needs_otp = any(
                    k in body
                    for k in (
                        "one-time",
                        "verification code",
                        "google authenticator",
                        "okta verify",
                        "enter code",
                        "passcode",
                        "security code",
                    )
                )
                if (
                    _visible_input(
                        page,
                        (
                            "input[name='credentials.passcode']",
                            "input[autocomplete='one-time-code']",
                        ),
                    )
                    is not None
                ):
                    needs_otp = True
                if needs_otp or mode in {"prompt", "totp", "code"}:
                    code = _resolve_otp()
                    _fill_otp(page, code)

            # Wait for redirect off Okta authorize
            deadline = time.time() + max(40.0, float(timeout_seconds) - 40.0)
            while time.time() < deadline:
                url = page.url or ""
                if "auth.uspto.gov" not in url and "uspto.gov" in url:
                    break
                page.wait_for_timeout(750)

            # Touch Patent Center so its cookies/storage are included when possible.
            try:
                page.goto(
                    PATENT_CENTER_LOGIN_URL,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_timeout(2000)
            except Exception:
                pass

            storage = context.storage_state()
            cookie_count = len(storage.get("cookies") or []) if isinstance(storage, dict) else 0
            logged_in = _looks_logged_in(page, storage=storage) and cookie_count > 0
            if cookie_count == 0:
                logged_in = False
                message = "login_failed_empty_session_cookies"
            elif logged_in:
                message = "login_succeeded_session_saved"
            else:
                message = (
                    f"session_has_{cookie_count}_cookies_but_login_unconfirmed"
                )

            _write_session(
                storage,
                state_root=state_root,
                name=session_name,
                username_hint=hint,
                logged_in=logged_in,
            )
            if not logged_in and cookie_count == 0:
                raise LoginError(
                    "USPTO login did not produce session cookies "
                    "(check credentials/OTP; Okta multi-step may have failed)",
                    code="empty_session",
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
