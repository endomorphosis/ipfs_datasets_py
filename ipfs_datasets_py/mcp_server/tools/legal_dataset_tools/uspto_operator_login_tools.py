"""Operator-only USPTO login MCP tools (password/OTP via refs — never returned).

This is a **separate** surface from the read-only PATLAW-061 USPTO MCP tools.
It intentionally does **not** expand ``READ_ONLY_TOOL_NAMES``.

Tools accept credential *references* (``env:USPTO_PASSWORD``) or one-shot OTP
codes for a single login. Responses never include passwords, TOTP seeds, OTP
codes, or raw cookies — only session presence / username hints / paths.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Mapping

logger = logging.getLogger(__name__)

OPERATOR_LOGIN_INTERFACE: Final = "USPTOOperatorLoginMCP@1"
OPERATOR_LOGIN_SCHEMA: Final = "uspto-operator-login-mcp/v1"

OPERATOR_LOGIN_TOOL_NAMES: Final[tuple[str, ...]] = (
    "uspto_operator_login",
    "uspto_operator_session_status",
    "uspto_operator_logout",
)

# Still never offered even on the operator surface.
OPERATOR_FORBIDDEN: Final[frozenset[str]] = frozenset(
    {
        "sign",
        "pay",
        "file",
        "submit",
        "return_password",
        "return_cookies",
        "return_totp_secret",
    }
)

OPERATOR_TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "uspto_operator_login": {
        "name": "uspto_operator_login",
        "interface": OPERATOR_LOGIN_INTERFACE,
        "schema": OPERATOR_LOGIN_SCHEMA,
        "read_only": False,
        "operator_only": True,
        "description": (
            "Log into Patent Center using username/password refs and OTP "
            "(prompt/totp/code). Saves a local Playwright session (mode 0600). "
            "Never returns secrets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "username_ref": {
                    "type": "string",
                    "default": "env:USPTO_USERNAME",
                    "description": "Username reference (env:VAR or file:/path).",
                },
                "password_ref": {
                    "type": "string",
                    "default": "env:USPTO_PASSWORD",
                    "description": "Password reference (env:VAR or file:/path).",
                },
                "otp_mode": {
                    "type": "string",
                    "enum": ["prompt", "totp", "code", "none"],
                    "default": "totp",
                    "description": "MFA mode. MCP defaults to totp/code (no TTY prompt).",
                },
                "totp_secret_ref": {
                    "type": "string",
                    "default": "env:USPTO_TOTP_SECRET",
                    "description": "TOTP seed ref when otp_mode=totp.",
                },
                "otp_code": {
                    "type": "string",
                    "description": "One-shot OTP when otp_mode=code (not stored).",
                },
                "otp_ref": {
                    "type": "string",
                    "description": "Optional ref for one-shot OTP code.",
                },
                "session_name": {
                    "type": "string",
                    "default": "patent_center",
                },
                "state_root": {
                    "type": "string",
                    "description": "Optional portfolio state root override.",
                },
                "headless": {
                    "type": "boolean",
                    "default": True,
                },
                "timeout_seconds": {
                    "type": "number",
                    "default": 180,
                },
            },
        },
        "returns": {
            "ok": "boolean",
            "logged_in": "boolean",
            "session_path": "string",
            "username_hint": "string",
            "message": "string",
        },
    },
    "uspto_operator_session_status": {
        "name": "uspto_operator_session_status",
        "interface": OPERATOR_LOGIN_INTERFACE,
        "schema": OPERATOR_LOGIN_SCHEMA,
        "read_only": True,
        "operator_only": True,
        "description": "Report whether a local Patent Center session file exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_name": {"type": "string", "default": "patent_center"},
                "state_root": {"type": "string"},
            },
        },
        "returns": {"present": "boolean", "logged_in_hint": "boolean"},
    },
    "uspto_operator_logout": {
        "name": "uspto_operator_logout",
        "interface": OPERATOR_LOGIN_INTERFACE,
        "schema": OPERATOR_LOGIN_SCHEMA,
        "read_only": False,
        "operator_only": True,
        "description": "Delete the local Patent Center session storage_state file.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_name": {"type": "string", "default": "patent_center"},
                "state_root": {"type": "string"},
            },
        },
        "returns": {"ok": "boolean", "removed": "array"},
    },
}


def _state_root(value: Any):
    from pathlib import Path

    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        default_state_root,
    )

    text = str(value or "").strip()
    if not text:
        return default_state_root()
    return Path(text).expanduser().resolve()


def uspto_operator_login(
    username_ref: str = "env:USPTO_USERNAME",
    password_ref: str = "env:USPTO_PASSWORD",
    otp_mode: str = "totp",
    totp_secret_ref: str = "env:USPTO_TOTP_SECRET",
    otp_code: str = "",
    otp_ref: str = "",
    session_name: str = "patent_center",
    state_root: str = "",
    headless: bool = True,
    timeout_seconds: float = 180.0,
    **_: Any,
) -> dict[str, Any]:
    """MCP entry: login using refs; never echo secrets."""
    from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
        LoginError,
        login_patent_center,
    )

    mode = str(otp_mode or "totp").strip().lower()
    # MCP has no reliable TTY — refuse prompt unless caller overrides to code/totp.
    allow_prompt = mode == "prompt"
    try:
        result = login_patent_center(
            username_ref=str(username_ref or "env:USPTO_USERNAME"),
            password_ref=str(password_ref or "env:USPTO_PASSWORD"),
            otp_mode=mode,
            otp_ref=str(otp_ref or ""),
            totp_secret_ref=str(totp_secret_ref or "env:USPTO_TOTP_SECRET"),
            otp_code=str(otp_code or ""),
            state_root=_state_root(state_root),
            session_name=str(session_name or "patent_center"),
            headless=bool(headless),
            timeout_seconds=float(timeout_seconds or 180.0),
            allow_prompt=allow_prompt,
        )
        return {"envelope": "uspto-operator-login-response/v1", **result.to_dict()}
    except LoginError as exc:
        logger.info("uspto_operator_login failed code=%s", exc.code)
        return {
            "envelope": "uspto-operator-login-response/v1",
            "ok": False,
            "code": exc.code,
            "message": str(exc),
        }


def uspto_operator_session_status(
    session_name: str = "patent_center",
    state_root: str = "",
    **_: Any,
) -> dict[str, Any]:
    from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
        load_session_status,
    )

    status = load_session_status(
        _state_root(state_root), name=str(session_name or "patent_center")
    )
    return {"envelope": "uspto-operator-login-response/v1", **status.to_dict()}


def uspto_operator_logout(
    session_name: str = "patent_center",
    state_root: str = "",
    **_: Any,
) -> dict[str, Any]:
    from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
        logout_session,
    )

    result = logout_session(
        _state_root(state_root), name=str(session_name or "patent_center")
    )
    return {"envelope": "uspto-operator-login-response/v1", **result}


def list_uspto_operator_login_tools() -> list[dict[str, Any]]:
    return [dict(OPERATOR_TOOL_SCHEMAS[name]) for name in OPERATOR_LOGIN_TOOL_NAMES]


def get_uspto_operator_login_handlers() -> Mapping[str, Any]:
    return {
        "uspto_operator_login": uspto_operator_login,
        "uspto_operator_session_status": uspto_operator_session_status,
        "uspto_operator_logout": uspto_operator_logout,
    }


def register_uspto_operator_login_tools(tool_registry: Any) -> int:
    """Register operator login tools if the registry supports register_tool(fn)."""
    handlers = get_uspto_operator_login_handlers()
    count = 0
    for name, fn in handlers.items():
        try:
            if hasattr(tool_registry, "register_tool"):
                tool_registry.register_tool(fn)
            elif hasattr(tool_registry, "register"):
                tool_registry.register(name, fn)
            else:
                continue
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to register %s: %s", name, type(exc).__name__)
    logger.info("Registered %d USPTO operator login tools", count)
    return count


__all__ = [
    "OPERATOR_FORBIDDEN",
    "OPERATOR_LOGIN_INTERFACE",
    "OPERATOR_LOGIN_SCHEMA",
    "OPERATOR_LOGIN_TOOL_NAMES",
    "OPERATOR_TOOL_SCHEMAS",
    "get_uspto_operator_login_handlers",
    "list_uspto_operator_login_tools",
    "register_uspto_operator_login_tools",
    "uspto_operator_login",
    "uspto_operator_logout",
    "uspto_operator_session_status",
]
