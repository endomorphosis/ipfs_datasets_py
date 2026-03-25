from __future__ import annotations

import sys
import types

import pytest

from ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine import (
    _resolve_credentials,
    _build_payload,
    get_cloudflare_browser_rendering_crawl,
    start_cloudflare_browser_rendering_crawl,
    wait_for_cloudflare_browser_rendering_crawl,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_build_payload_omits_zero_depth() -> None:
    payload = _build_payload(
        url="https://example.com",
        limit=1,
        depth=0,
        formats=["markdown", "html"],
        render=False,
        source="all",
    )

    assert payload["limit"] == 1
    assert "depth" not in payload
    assert payload["formats"] == ["markdown", "html"]


def test_resolve_credentials_falls_back_to_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    from ipfs_datasets_py.processors.web_archiving import cloudflare_browser_rendering_engine as engine

    class _Vault:
        def get(self, name: str) -> str | None:
            mapping = {
                "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID": "vault-acct",
                "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN": "vault-token",
            }
            return mapping.get(name)

    monkeypatch.setattr(engine, "_first_env", lambda *names: None)
    monkeypatch.setattr(engine, "_first_vault", lambda *names: _Vault().get(names[1]) if len(names) > 1 else None)
    monkeypatch.setattr(engine, "_first_keyring", lambda *names: None)

    account_id, api_token = _resolve_credentials()

    assert account_id == "vault-acct"
    assert api_token == "vault-token"


def test_resolve_credentials_falls_back_to_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    from ipfs_datasets_py.processors.web_archiving import cloudflare_browser_rendering_engine as engine

    monkeypatch.setattr(engine, "_first_env", lambda *names: None)
    monkeypatch.setattr(engine, "_first_vault", lambda *names: None)
    monkeypatch.setattr(
        engine,
        "_first_keyring",
        lambda *names: "keyring-acct" if "ACCOUNT_ID" in names[0] else "keyring-token",
    )

    account_id, api_token = _resolve_credentials()

    assert account_id == "keyring-acct"
    assert api_token == "keyring-token"


@pytest.mark.anyio
async def test_start_cloudflare_browser_rendering_crawl_returns_api_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_requests = types.SimpleNamespace(
        post=lambda *args, **kwargs: _FakeResponse(
            403,
            {
                "success": False,
                "errors": [{"code": 10000, "message": "Authentication error"}],
            },
        )
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    result = await start_cloudflare_browser_rendering_crawl(
        "https://example.com",
        account_id="acct",
        api_token="token",
    )

    assert result["status"] == "error"
    assert result["http_status"] == 403
    assert result["error"] == "10000: Authentication error"


@pytest.mark.anyio
async def test_start_cloudflare_browser_rendering_crawl_retries_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            _FakeResponse(
                429,
                {
                    "success": False,
                    "errors": [{"code": 2001, "message": "Rate limit exceeded"}],
                },
                headers={"retry-after": "7"},
            ),
            _FakeResponse(
                200,
                {
                    "success": True,
                    "result": "job-123",
                },
            ),
        ]
    )
    fake_requests = types.SimpleNamespace(post=lambda *args, **kwargs: next(responses))
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    from ipfs_datasets_py.processors.web_archiving import cloudflare_browser_rendering_engine as engine

    sleeps: list[float] = []

    async def _no_sleep(_: float) -> None:
        sleeps.append(_)
        return None

    monkeypatch.setattr(engine.anyio, "sleep", _no_sleep)

    result = await start_cloudflare_browser_rendering_crawl(
        "https://example.com",
        account_id="acct",
        api_token="token",
    )

    assert result["status"] == "success"
    assert result["job_id"] == "job-123"
    assert sleeps == [7.0]


@pytest.mark.anyio
async def test_start_cloudflare_browser_rendering_crawl_returns_rate_limit_schedule_when_wait_too_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_requests = types.SimpleNamespace(
        post=lambda *args, **kwargs: _FakeResponse(
            429,
            {
                "success": False,
                "errors": [{"code": 2001, "message": "Rate limit exceeded"}],
            },
            headers={
                "retry-after": "3600",
                "cf-ray": "test-ray-create",
                "cf-auditlog-id": "audit-create",
                "api-version": "2026-03-11",
            },
        )
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    result = await start_cloudflare_browser_rendering_crawl(
        "https://example.com",
        account_id="acct",
        api_token="token",
        max_rate_limit_wait_seconds=30,
    )

    assert result["status"] == "rate_limited"
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 3600.0
    assert result["wait_budget_exhausted"] is True
    assert result["rate_limit_diagnostics"]["error_code"] == "2001"
    assert result["rate_limit_diagnostics"]["cf_ray"] == "test-ray-create"
    assert result["rate_limit_diagnostics"]["cf_auditlog_id"] == "audit-create"
    assert result["rate_limit_diagnostics"]["operation"] == "create_crawl"


@pytest.mark.anyio
async def test_get_cloudflare_browser_rendering_crawl_returns_job_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_requests = types.SimpleNamespace(
        get=lambda *args, **kwargs: _FakeResponse(
            200,
            {
                "success": True,
                "result": {
                    "id": "job-123",
                    "status": "completed",
                    "records": [{"url": "https://example.com", "status": "completed"}],
                },
            },
        )
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    result = await get_cloudflare_browser_rendering_crawl(
        "job-123",
        account_id="acct",
        api_token="token",
    )

    assert result["status"] == "success"
    assert result["job_id"] == "job-123"
    assert result["job"]["status"] == "completed"


@pytest.mark.anyio
async def test_wait_for_cloudflare_browser_rendering_crawl_retries_transient_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            _FakeResponse(
                404,
                {
                    "success": False,
                    "errors": [{"code": 1001, "message": "Crawl job not found"}],
                },
            ),
            _FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "id": "job-123",
                        "status": "completed",
                        "records": [
                            {"url": "https://example.com", "status": "completed"}
                        ],
                    },
                },
            ),
            _FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "id": "job-123",
                        "status": "completed",
                        "records": [
                            {"url": "https://example.com", "status": "completed"}
                        ],
                    },
                },
            ),
        ]
    )

    fake_requests = types.SimpleNamespace(get=lambda *args, **kwargs: next(responses))
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    from ipfs_datasets_py.processors.web_archiving import cloudflare_browser_rendering_engine as engine

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(engine.anyio, "sleep", _no_sleep)

    result = await wait_for_cloudflare_browser_rendering_crawl(
        "job-123",
        account_id="acct",
        api_token="token",
        timeout_seconds=10,
        poll_interval_seconds=0,
        max_rate_limit_wait_seconds=10,
    )

    assert result["status"] == "success"
    assert result["job_id"] == "job-123"
    assert result["records"] == [{"url": "https://example.com", "status": "completed"}]


@pytest.mark.anyio
async def test_wait_for_cloudflare_browser_rendering_crawl_retries_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            _FakeResponse(
                429,
                {
                    "success": False,
                    "errors": [{"code": 2001, "message": "Rate limit exceeded"}],
                },
                headers={"retry-after": "5"},
            ),
            _FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "id": "job-123",
                        "status": "completed",
                        "records": [
                            {"url": "https://example.com", "status": "completed"}
                        ],
                    },
                },
            ),
            _FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "id": "job-123",
                        "status": "completed",
                        "records": [
                            {"url": "https://example.com", "status": "completed"}
                        ],
                    },
                },
            ),
        ]
    )

    fake_requests = types.SimpleNamespace(get=lambda *args, **kwargs: next(responses))
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    from ipfs_datasets_py.processors.web_archiving import cloudflare_browser_rendering_engine as engine

    sleeps: list[float] = []

    async def _no_sleep(_: float) -> None:
        sleeps.append(_)
        return None

    monkeypatch.setattr(engine.anyio, "sleep", _no_sleep)

    result = await wait_for_cloudflare_browser_rendering_crawl(
        "job-123",
        account_id="acct",
        api_token="token",
        timeout_seconds=10,
        poll_interval_seconds=0,
        max_rate_limit_wait_seconds=10,
    )

    assert result["status"] == "success"
    assert result["job_id"] == "job-123"
    assert sleeps == [5.0]


@pytest.mark.anyio
async def test_wait_for_cloudflare_browser_rendering_crawl_returns_rate_limit_schedule_when_wait_too_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_requests = types.SimpleNamespace(
        get=lambda *args, **kwargs: _FakeResponse(
            429,
            {
                "success": False,
                "errors": [{"code": 2001, "message": "Rate limit exceeded"}],
            },
            headers={
                "retry-after": "600",
                "cf-ray": "test-ray-poll",
                "cf-auditlog-id": "audit-poll",
            },
        )
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    result = await wait_for_cloudflare_browser_rendering_crawl(
        "job-123",
        account_id="acct",
        api_token="token",
        timeout_seconds=30,
        max_rate_limit_wait_seconds=15,
    )

    assert result["status"] == "rate_limited"
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 600.0
    assert result["wait_budget_exhausted"] is True
    assert result["rate_limit_diagnostics"]["cf_ray"] == "test-ray-poll"
    assert result["rate_limit_diagnostics"]["cf_auditlog_id"] == "audit-poll"
    assert result["rate_limit_diagnostics"]["operation"] == "get_crawl"
