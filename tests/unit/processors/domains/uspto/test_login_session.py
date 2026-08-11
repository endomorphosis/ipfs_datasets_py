"""Unit tests for USPTO operator login session helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
    LoginError,
    generate_totp,
    load_session_status,
    logout_session,
    resolve_secret_ref,
    sanitize_tool_arguments,
    session_path,
)


def test_totp_rfc6238_vector() -> None:
    # RFC 6238 Appendix B test vector (SHA-1, 6 digits, period 30).
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
    assert generate_totp(secret, for_time=59) == "287082"
    assert generate_totp(secret, for_time=1111111109) == "081804"


def test_resolve_secret_ref_env() -> None:
    env = {"USPTO_USERNAME": "alice@example.com"}
    assert resolve_secret_ref("env:USPTO_USERNAME", environ=env) == "alice@example.com"
    assert resolve_secret_ref("USPTO_USERNAME", environ=env) == "alice@example.com"
    with pytest.raises(LoginError):
        resolve_secret_ref("env:MISSING", environ=env, allow_prompt=False)


def test_resolve_secret_ref_file(tmp_path: Path) -> None:
    p = tmp_path / "secret.txt"
    p.write_text("s3cret-value\n", encoding="utf-8")
    assert resolve_secret_ref(f"file:{p}", allow_prompt=False) == "s3cret-value"


def test_sanitize_never_echoes_secrets() -> None:
    cleaned = sanitize_tool_arguments(
        {
            "username_ref": "env:USPTO_USERNAME",
            "password": "nope",
            "otp_code": "123456",
            "nested": {"api_key": "x", "ok": True},
        }
    )
    assert cleaned["password"] == "<redacted>"
    assert cleaned["otp_code"] == "<redacted>"
    assert cleaned["nested"]["api_key"] == "<redacted>"
    assert cleaned["nested"]["ok"] is True
    assert cleaned["username_ref"] == "env:USPTO_USERNAME"


def test_session_status_and_logout(tmp_path: Path) -> None:
    path = session_path(tmp_path, name="patent_center")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cookies": [{"name": "x", "value": "y"}], "origins": []})
    )
    status = load_session_status(tmp_path, name="patent_center")
    assert status.present is True
    assert status.logged_in_hint is True
    out = logout_session(tmp_path, name="patent_center")
    assert out["ok"] is True
    assert not path.is_file()
    status2 = load_session_status(tmp_path, name="patent_center")
    assert status2.present is False


def test_operator_mcp_handlers_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
        uspto_operator_login_tools as tools,
    )

    # Point default state to tmp via explicit state_root.
    result = tools.uspto_operator_session_status(
        session_name="patent_center",
        state_root=str(tmp_path),
    )
    assert result["present"] is False
    assert "password" not in json.dumps(result).lower() or "<redacted>" in json.dumps(
        result
    )
    listed = tools.list_uspto_operator_login_tools()
    assert {t["name"] for t in listed} == set(tools.OPERATOR_LOGIN_TOOL_NAMES)
    # Ensure read-only USPTO surface still forbids login name collision docs
    assert "uspto_operator_login" in tools.OPERATOR_LOGIN_TOOL_NAMES
