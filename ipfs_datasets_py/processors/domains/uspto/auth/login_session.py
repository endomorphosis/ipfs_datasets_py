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
MYUSPTO_LOGIN_HINT: Final = "https://my.uspto.gov"

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


def _looks_logged_in(page: Any) -> bool:
    selectors = (
        "text=Log Out",
        "text=Logout",
        "text=Sign Out",
        "text=My Workbench",
        "text=Workbench",
        "a[href*='logout' i]",
    )
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    # Cookie heuristic after navigation
    try:
        url = page.url or ""
        if "patentcenter.uspto.gov" in url and "login" not in url.lower():
            return True
    except Exception:
        pass
    return False


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
    login_url: str = PATENT_CENTER_LOGIN_URL,
    timeout_seconds: float = 180.0,
    allow_prompt: bool = True,
    otp_provider: Callable[[], str] | None = None,
) -> LoginResult:
    """Log into Patent Center with username/password + OTP and save session.

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
            return str(otp_provider() or "").strip()
        if mode == "none":
            return ""
        if mode == "code":
            if otp_code.strip():
                return otp_code.strip()
            if otp_ref.strip():
                return resolve_secret_ref(
                    otp_ref, prompt_label="USPTO OTP", allow_prompt=allow_prompt
                )
            if allow_prompt:
                return getpass.getpass("USPTO OTP code: ").strip()
            raise LoginError("otp_mode=code requires otp_code or otp_ref", code="missing_otp")
        if mode == "totp":
            secret = resolve_secret_ref(
                totp_secret_ref,
                prompt_label="USPTO TOTP secret",
                allow_prompt=False,
            )
            return generate_totp(secret)
        # prompt
        if allow_prompt:
            return getpass.getpass("USPTO OTP / MFA code: ").strip()
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

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(headless))
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(min(60_000, int(timeout_seconds * 1000)))
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60_000)
            # Common username fields
            for sel in (
                "input[name='username']",
                "input[name='USER']",
                "input[id*='user' i]",
                "input[type='email']",
                "input[autocomplete='username']",
                "input[name='identifier']",
            ):
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        loc.fill(username)
                        break
                except Exception:
                    continue
            for sel in (
                "input[name='password']",
                "input[type='password']",
                "input[autocomplete='current-password']",
            ):
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        loc.fill(password)
                        break
                except Exception:
                    continue
            # Submit password form
            for sel in (
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Sign In')",
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "button:has-text('Continue')",
                "text=Sign in",
            ):
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        loc.click()
                        break
                except Exception:
                    continue

            # Wait briefly for MFA or landing
            page.wait_for_timeout(2000)

            if mode != "none":
                otp_selectors = (
                    "input[name*='otp' i]",
                    "input[name*='mfa' i]",
                    "input[name*='code' i]",
                    "input[autocomplete='one-time-code']",
                    "input[inputmode='numeric']",
                    "input[type='tel']",
                )
                needs_otp = False
                for sel in otp_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            needs_otp = True
                            break
                    except Exception:
                        continue
                # Also check page text
                try:
                    body = page.content().lower()
                    if any(
                        k in body
                        for k in (
                            "one-time",
                            "verification code",
                            "authentication code",
                            "mfa",
                            "passcode",
                        )
                    ):
                        needs_otp = True
                except Exception:
                    pass

                if needs_otp or mode in {"prompt", "totp", "code"}:
                    code = _resolve_otp()
                    if not code and mode != "none":
                        raise LoginError("OTP code is empty", code="empty_otp")
                    if code:
                        filled = False
                        for sel in otp_selectors:
                            try:
                                loc = page.locator(sel).first
                                if loc.count() > 0:
                                    loc.fill(code)
                                    filled = True
                                    break
                            except Exception:
                                continue
                        if filled:
                            for sel in (
                                "button[type='submit']",
                                "input[type='submit']",
                                "button:has-text('Verify')",
                                "button:has-text('Continue')",
                                "button:has-text('Submit')",
                            ):
                                try:
                                    loc = page.locator(sel).first
                                    if loc.count() > 0:
                                        loc.click()
                                        break
                                except Exception:
                                    continue

            # Allow redirects / workbench load
            deadline = time.time() + max(30.0, float(timeout_seconds) - 30.0)
            while time.time() < deadline:
                if _looks_logged_in(page):
                    logged_in = True
                    break
                page.wait_for_timeout(1000)
                # Try navigating to patent center home after auth
                try:
                    if "login" in (page.url or "").lower():
                        pass
                    elif "uspto.gov" in (page.url or ""):
                        page.goto(
                            PATENT_CENTER_LOGIN_URL,
                            wait_until="domcontentloaded",
                            timeout=30_000,
                        )
                except Exception:
                    pass

            storage = context.storage_state()
            _write_session(
                storage,
                state_root=state_root,
                name=session_name,
                username_hint=hint,
                logged_in=logged_in,
            )
            if logged_in:
                message = "login_succeeded_session_saved"
            else:
                message = (
                    "session_saved_but_login_not_confirmed; "
                    "complete MFA in headed mode or check credentials"
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
