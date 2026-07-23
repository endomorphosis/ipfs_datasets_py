"""Gmail credential and OAuth helpers for legal-data email workflows."""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


KEYRING_SERVICE = "complaint-generator.gmail"
IPFS_VAULT_SECRET_PREFIX = "gmail-app-password"
GMAIL_IMAP_SCOPE = "https://mail.google.com/"
DEFAULT_TOKEN_ROOT = Path.home() / ".config" / "complaint-generator" / "gmail_oauth"


def _slugify(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in str(value or "").strip().lower()).strip("-") or "gmail"


def _load_keyring():
    try:
        import keyring  # type: ignore
    except Exception:
        return None
    return keyring


def _load_ipfs_secrets_vault():
    try:
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault  # type: ignore
        return SecretsVault
    except Exception:
        return None


def _vault_secret_name(gmail_user: str) -> str:
    cleaned = str(gmail_user or "").strip().lower()
    return f"{IPFS_VAULT_SECRET_PREFIX}:{cleaned}"


def read_password_from_keyring(gmail_user: str) -> str:
    keyring = _load_keyring()
    if keyring is None or not gmail_user:
        return ""
    try:
        return str(keyring.get_password(KEYRING_SERVICE, gmail_user) or "").strip()
    except Exception:
        return ""


def read_password_from_ipfs_secrets_vault(gmail_user: str) -> str:
    SecretsVault = _load_ipfs_secrets_vault()
    if SecretsVault is None or not gmail_user:
        return ""
    try:
        vault = SecretsVault()
        return str(vault.get(_vault_secret_name(gmail_user)) or "").strip()
    except Exception:
        return ""


def save_password_to_keyring(gmail_user: str, gmail_app_password: str, parser: argparse.ArgumentParser) -> None:
    keyring = _load_keyring()
    if keyring is None:
        parser.error("keyring support is not available. Install the 'keyring' package to use --save-to-keyring.")
    try:
        keyring.set_password(KEYRING_SERVICE, gmail_user, gmail_app_password)
    except Exception as exc:
        parser.error(f"failed to save Gmail app password to keyring: {exc}")


def save_password_to_ipfs_secrets_vault(
    gmail_user: str,
    gmail_app_password: str,
    parser: argparse.ArgumentParser,
) -> None:
    SecretsVault = _load_ipfs_secrets_vault()
    if SecretsVault is None:
        parser.error(
            "ipfs_datasets_py SecretsVault support is not available. Install py-ucan and ensure "
            "ipfs_datasets_py is importable to use --save-to-ipfs-secrets-vault."
        )
    try:
        vault = SecretsVault()
        vault.set(_vault_secret_name(gmail_user), gmail_app_password)
    except Exception as exc:
        parser.error(f"failed to save Gmail app password to the ipfs_datasets_py secrets vault: {exc}")


def resolve_gmail_credentials(
    *,
    gmail_user: str,
    gmail_app_password: str,
    prompt_for_credentials: bool,
    use_keyring: bool,
    save_to_keyring_flag: bool,
    use_ipfs_secrets_vault: bool,
    save_to_ipfs_secrets_vault_flag: bool,
    parser: argparse.ArgumentParser,
) -> tuple[str, str]:
    resolved_user = str(gmail_user or "").strip()
    resolved_password = str(gmail_app_password or "").strip()
    can_prompt = bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stderr, "isatty", lambda: False)())

    if use_ipfs_secrets_vault and resolved_user and not resolved_password:
        resolved_password = read_password_from_ipfs_secrets_vault(resolved_user)
    if use_keyring and resolved_user and not resolved_password:
        resolved_password = read_password_from_keyring(resolved_user)

    if prompt_for_credentials or ((not resolved_user or not resolved_password) and can_prompt):
        if not resolved_user:
            resolved_user = input("Gmail address: ").strip()
        if use_ipfs_secrets_vault and resolved_user and not resolved_password:
            resolved_password = read_password_from_ipfs_secrets_vault(resolved_user)
        if use_keyring and resolved_user and not resolved_password:
            resolved_password = read_password_from_keyring(resolved_user)
        if not resolved_password:
            resolved_password = getpass.getpass("Gmail app password: ").strip()

    if not resolved_user or not resolved_password:
        parser.error(
            "Gmail credentials are required. Use --prompt-for-credentials, "
            "--use-keyring, --use-ipfs-secrets-vault, set GMAIL_USER/GMAIL_APP_PASSWORD, "
            "or pass --gmail-user and --gmail-app-password."
        )

    if save_to_ipfs_secrets_vault_flag:
        save_password_to_ipfs_secrets_vault(resolved_user, resolved_password, parser)
    if save_to_keyring_flag:
        save_password_to_keyring(resolved_user, resolved_password, parser)
    return resolved_user, resolved_password


def default_token_cache_path(gmail_user: str) -> Path:
    return DEFAULT_TOKEN_ROOT / f"{_slugify(gmail_user)}.json"


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


def _build_auth_url(profile: dict[str, Any], *, redirect_uri: str, state: str, login_hint: str = "") -> str:
    params = {
        "client_id": profile["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_IMAP_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
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
    gmail_user: str,
    token_cache_path: str | Path | None = None,
    open_browser: bool = True,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    profile = load_client_profile(client_secrets_path)
    result: dict[str, Any] = {}
    finished = threading.Event()
    state = secrets.token_urlsafe(24)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
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
                b"<html><body><h1>Gmail OAuth complete</h1><p>You can return to the terminal.</p></body></html>"
            )
            finished.set()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    redirect_uri = _loopback_redirect_uri(profile, server.server_port)
    auth_url = _build_auth_url(profile, redirect_uri=redirect_uri, state=state, login_hint=gmail_user)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(auth_url)
    print(f"Open this URL to authorize Gmail access:\n{auth_url}")

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
    cache_path = Path(token_cache_path).expanduser().resolve() if token_cache_path else default_token_cache_path(gmail_user)
    save_cached_token(cache_path, token_payload)
    return token_payload


def resolve_gmail_oauth_access_token(
    *,
    gmail_user: str,
    client_secrets_path: str,
    token_cache_path: str | Path | None = None,
    open_browser: bool = True,
) -> tuple[str, dict[str, Any]]:
    profile = load_client_profile(client_secrets_path)
    cache_path = Path(token_cache_path).expanduser().resolve() if token_cache_path else default_token_cache_path(gmail_user)
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
        gmail_user=gmail_user,
        token_cache_path=cache_path,
        open_browser=open_browser,
    )
    return str(issued["access_token"]), issued


def build_xoauth2_bytes(gmail_user: str, access_token: str) -> bytes:
    return f"user={gmail_user}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")


__all__ = [
    "DEFAULT_TOKEN_ROOT",
    "GMAIL_IMAP_SCOPE",
    "IPFS_VAULT_SECRET_PREFIX",
    "KEYRING_SERVICE",
    "build_xoauth2_bytes",
    "default_token_cache_path",
    "load_cached_token",
    "read_password_from_ipfs_secrets_vault",
    "read_password_from_keyring",
    "resolve_gmail_credentials",
    "resolve_gmail_oauth_access_token",
    "run_local_server_oauth_flow",
    "save_cached_token",
    "save_password_to_ipfs_secrets_vault",
    "save_password_to_keyring",
    "token_is_usable",
]
