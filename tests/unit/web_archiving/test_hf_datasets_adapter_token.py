from __future__ import annotations

import importlib
import types

import duckdb
import pytest

from ipfs_datasets_py.processors.web_archiving.common_crawl_search_engine.ccindex import (
    hf_datasets_adapter,
)
from ipfs_datasets_py.processors.web_archiving.common_crawl_search_engine.ccindex.hf_datasets_adapter import (
    configure_duckdb_huggingface_auth,
    huggingface_authorization_headers,
    resolve_huggingface_token,
)

_TOKEN_ENV_NAMES = (
    "IPFS_DATASETS_PY_HF_API_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "HUGGINGFACE_API_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_API_KEY",
    "HF_TOKEN",
    "HF_API_TOKEN",
)
_UNIT_TOKEN = "hf_unit_test_token_should_not_leak"


def _clear_hf_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _TOKEN_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _stub_hub_token(monkeypatch: pytest.MonkeyPatch, token: str | None) -> None:
    real_import = importlib.import_module

    def _import(name: str, package: str | None = None):
        if name == "huggingface_hub":
            return types.SimpleNamespace(get_token=lambda: token)
        return real_import(name, package)

    monkeypatch.setattr(hf_datasets_adapter.importlib, "import_module", _import)


def test_resolve_huggingface_token_prefers_explicit_over_env_and_hub(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_from_env")
    _stub_hub_token(monkeypatch, "hf_from_hub")
    assert resolve_huggingface_token("hf_explicit") == "hf_explicit"


def test_resolve_huggingface_token_uses_env_before_hub_login(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    monkeypatch.setenv("HUGGINGFACE_HUB_TOKEN", "hf_from_hub_env")
    _stub_hub_token(monkeypatch, "hf_from_cached_login")
    assert resolve_huggingface_token() == "hf_from_hub_env"


def test_resolve_huggingface_token_uses_cached_hub_login(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    _stub_hub_token(monkeypatch, "hf_from_cached_login")
    assert resolve_huggingface_token() == "hf_from_cached_login"
    assert huggingface_authorization_headers() == {
        "Authorization": "Bearer hf_from_cached_login"
    }


def test_resolve_huggingface_token_empty_when_unavailable(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    _stub_hub_token(monkeypatch, None)
    assert resolve_huggingface_token() == ""
    assert huggingface_authorization_headers() == {}


def test_configure_duckdb_huggingface_auth_creates_redacted_secret(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", _UNIT_TOKEN)
    _stub_hub_token(monkeypatch, None)
    connection = duckdb.connect(":memory:")
    assert configure_duckdb_huggingface_auth(connection) is True
    rows = connection.execute("SELECT name, type FROM duckdb_secrets()").fetchall()
    assert any(name == "ipfs_datasets_huggingface" and kind == "huggingface" for name, kind in rows)
    dumped = str(connection.execute("SELECT * FROM duckdb_secrets()").fetchall())
    assert _UNIT_TOKEN not in dumped


def test_configure_duckdb_huggingface_auth_skips_without_token(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    _stub_hub_token(monkeypatch, None)
    connection = duckdb.connect(":memory:")
    assert configure_duckdb_huggingface_auth(connection) is False
    assert connection.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0] == 0
