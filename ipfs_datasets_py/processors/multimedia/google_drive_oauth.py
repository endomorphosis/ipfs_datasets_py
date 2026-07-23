#!/usr/bin/env python3
"""Minimal Google Drive OAuth helpers for Drive API read/download access."""

from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DEFAULT_TOKEN_ROOT = Path.home() / ".config" / "hacc" / "google_drive_oauth"


def _slugify(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in str(value or "").strip().lower()).strip("-") or "drive"


def default_token_cache_path(account_hint: str) -> Path:
    return DEFAULT_TOKEN_ROOT / f"{_slugify(account_hint)}.json"


def load_client_profile(client_secrets_path: str) -> dict[str, Any]:
    payload = json.loads(Path(client_secrets_path).expanduser().resolve().read_text(encoding="utf-8"))
    profile = payload.get("installed") or payload.get("web") or {}
    if not profile:
        raise ValueError("Client secrets JSON must contain an 'installed' or 'web' section.")
    return {
        "client_id": str(profile.get("client_id") or ""),
        "client_secret": str(profile.get("client_secret") or ""),
        "auth_uri": str(profile.get("auth_uri") or "https://accounts.google.com/o/oauth2/v2/auth"),
        "token_uri": str(profile.get("token_uri") or "https://oauth2.googleapis.com/token"),
        "redirect_uris": list(profile.get("redirect_uris") or []),
    }


def load_cached_token(path: str | Path) -> dict[str, Any]:
    token_path = Path(path).expanduser().resolve()
    if not token_path.exists():
        return {}
    return json.loads(token_path.read_text(encoding="utf-8"))


def save_cached_token(path: str | Path, token_payload: dict[str, Any]) -> None:
    token_path = Path(path).expanduser().resolve()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token_payload, indent=2, sort_keys=True), encoding="utf-8")


def token_is_usable(token_payload: dict[str, Any], *, skew_seconds: int = 60) -> bool:
    access_token = str(token_payload.get("access_token") or "")
    expires_at = float(token_payload.get("expires_at") or 0)
    return bool(access_token and expires_at and expires_at > (time.time() + skew_seconds))


def _token_payload_with_expiry(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in:
        result["expires_at"] = time.time() + expires_in
    return result


def refresh_access_token(profile: dict[str, Any], refresh_token: str) -> dict[str, Any]:
    response = requests.post(
        profile["token_uri"],
        data={
            "client_id": profile["client_id"],
            "client_secret": profile["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    refreshed = _token_payload_with_expiry(dict(response.json()))
    refreshed["refresh_token"] = refresh_token
    return refreshed


def _loopback_redirect_uri(profile: dict[str, Any], port: int) -> str:
    for value in list(profile.get("redirect_uris") or []):
        if value.startswith("http://127.0.0.1") or value.startswith("http://localhost"):
            parsed = urlparse(value)
            host = parsed.hostname or "127.0.0.1"
            return f"http://{host}:{port}"
    return f"http://127.0.0.1:{port}"


def _build_auth_url(profile: dict[str, Any], *, redirect_uri: str, state: str, account_hint: str = "") -> str:
    params = {
        "client_id": profile["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if account_hint:
        params["login_hint"] = account_hint
    return f"{profile['auth_uri']}?{urlencode(params)}"


def _exchange_code_for_token(profile: dict[str, Any], *, code: str, redirect_uri: str) -> dict[str, Any]:
    response = requests.post(
        profile["token_uri"],
        data={
            "code": code,
            "client_id": profile["client_id"],
            "client_secret": profile["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    return _token_payload_with_expiry(dict(response.json()))


def run_local_server_oauth_flow(
    *,
    client_secrets_path: str,
    account_hint: str,
    token_cache_path: str | Path | None = None,
    open_browser: bool = True,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    profile = load_client_profile(client_secrets_path)
    result: dict[str, Any] = {}
    finished = threading.Event()
    state = secrets.token_urlsafe(24)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            result["state"] = str(query.get("state", [""])[0])
            result["code"] = str(query.get("code", [""])[0])
            result["error"] = str(query.get("error", [""])[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Google Drive OAuth complete</h1><p>You can return to the terminal.</p></body></html>"
            )
            finished.set()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    redirect_uri = _loopback_redirect_uri(profile, server.server_port)
    auth_url = _build_auth_url(profile, redirect_uri=redirect_uri, state=state, account_hint=account_hint)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(auth_url)
    print(f"Open this URL to authorize Google Drive access:\n{auth_url}")

    if not finished.wait(timeout_seconds):
        server.server_close()
        raise TimeoutError("Timed out waiting for the Google OAuth callback.")
    server.server_close()

    if result.get("state") != state:
        raise RuntimeError("OAuth state mismatch. Try the login flow again.")
    if result.get("error"):
        raise RuntimeError(f"Google OAuth returned an error: {result['error']}")
    code = str(result.get("code") or "")
    if not code:
        raise RuntimeError("Google OAuth did not return an authorization code.")

    token_payload = _exchange_code_for_token(profile, code=code, redirect_uri=redirect_uri)
    cache_path = Path(token_cache_path).expanduser().resolve() if token_cache_path else default_token_cache_path(account_hint)
    save_cached_token(cache_path, token_payload)
    return token_payload


def resolve_drive_oauth_access_token(
    *,
    account_hint: str,
    client_secrets_path: str,
    token_cache_path: str | Path | None = None,
    open_browser: bool = True,
) -> tuple[str, dict[str, Any]]:
    profile = load_client_profile(client_secrets_path)
    cache_path = Path(token_cache_path).expanduser().resolve() if token_cache_path else default_token_cache_path(account_hint)
    token_payload = load_cached_token(cache_path)

    if token_is_usable(token_payload):
        return str(token_payload["access_token"]), token_payload

    refresh_token = str(token_payload.get("refresh_token") or "")
    if refresh_token:
        refreshed = refresh_access_token(profile, refresh_token)
        save_cached_token(cache_path, refreshed)
        return str(refreshed["access_token"]), refreshed

    issued = run_local_server_oauth_flow(
        client_secrets_path=client_secrets_path,
        account_hint=account_hint,
        token_cache_path=cache_path,
        open_browser=open_browser,
    )
    return str(issued["access_token"]), issued
