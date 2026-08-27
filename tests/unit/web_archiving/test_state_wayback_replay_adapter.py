from __future__ import annotations

import hashlib
import sys
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
)
from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine


def _capture_discovery(official_url: str) -> dict[str, str]:
    query_url, _variant_count = wayback_machine_engine._wayback_inventory_query_url(
        official_url,
        limit=100,
        exact_originals=[official_url],
    )
    return {
        "wayback_cdx_query_url": query_url,
        "wayback_cdx_response_sha256": "a" * 64,
        "wayback_cdx_fetched_at": "2026-08-24T01:02:04+00:00",
    }


@pytest.mark.anyio
async def test_exact_wayback_replay_bypasses_redirecting_client_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/section-1"
    timestamp = "20260824010203"
    identity_url = (
        f"https://web.archive.org/web/{timestamp}id_/{official_url}"
    )
    observed: dict[str, object] = {}

    class _Client:
        def __init__(self):
            raise AssertionError("exact replay must bypass the client library")

    fake_wayback = ModuleType("wayback")
    fake_wayback.WaybackClient = _Client
    monkeypatch.setitem(sys.modules, "wayback", fake_wayback)

    async def _direct(url: str, timestamp: str, closest: bool):
        observed.update(url=url, timestamp=timestamp, closest=closest)
        return {
            "status": "success",
            "wayback_url": identity_url,
            "replay_modifier": "id_",
        }

    monkeypatch.setattr(wayback_machine_engine, "_get_wayback_content_direct", _direct)

    result = await wayback_machine_engine.get_wayback_content(
        official_url,
        timestamp=timestamp,
        closest=False,
    )

    assert observed == {
        "url": official_url,
        "timestamp": timestamp,
        "closest": False,
    }
    assert result["status"] == "success"
    assert result["wayback_url"] == identity_url
    assert result["replay_modifier"] == "id_"


@pytest.mark.anyio
async def test_direct_wayback_replay_preserves_raw_pdf_bytes_and_identity_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/title.pdf"
    timestamp = "20260824010203"
    identity_url = (
        f"https://web.archive.org/web/{timestamp}id_/{official_url}"
    )
    body = b"%PDF-1.7\nraw archived title bytes\n%%EOF"
    observed: dict[str, object] = {}

    class _Response:
        status_code = 200
        content = body
        url = identity_url

        def __init__(self) -> None:
            self.headers = {"content-type": "application/pdf"}

        @staticmethod
        def raise_for_status() -> None:
            return None

    def _get(url: str, **kwargs):
        observed.update(url=url, **kwargs)
        return _Response()

    monkeypatch.setattr("requests.get", _get)

    result = await wayback_machine_engine._get_wayback_content_direct(
        official_url,
        timestamp=timestamp,
        closest=False,
    )

    assert observed == {
        "url": identity_url,
        "timeout": 30,
        "allow_redirects": False,
    }
    assert result["status"] == "success"
    assert result["content"] == body
    assert result["content_type"] == "application/pdf"
    assert result["capture_timestamp"] == timestamp
    assert result["wayback_url"] == identity_url
    assert result["replay_modifier"] == "id_"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "final_url",
    [
        "",
        "http://web.archive.org/web/20260824010203id_/https://example.gov/code?a=1&b=%2F",
        "https://www.web.archive.org/web/20260824010203id_/https://example.gov/code?a=1&b=%2F",
        "https://web.archive.org:443/web/20260824010203id_/https://example.gov/code?a=1&b=%2F",
        "https://user@web.archive.org/web/20260824010203id_/https://example.gov/code?a=1&b=%2F",
        "https://web.archive.org/prefix/web/20260824010203id_/https://example.gov/code?a=1&b=%2F",
        "https://web.archive.org/web/20260824010203/https://example.gov/code?a=1&b=%2F",
        "https://web.archive.org/web/20260824010203if_/https://example.gov/code?a=1&b=%2F",
        "https://web.archive.org/web/20260825010203id_/https://example.gov/code?a=1&b=%2F",
        "https://web.archive.org/web/20260824010203id_/https://example.gov/code?b=%2F&a=1",
        "https://web.archive.org/web/20260824010203id_/https://example.gov/code?a=1&b=%2f",
        "https://web.archive.org/web/20260824010203id_/https://example.gov/code?a=1&b=%2F#",
    ],
)
async def test_direct_exact_replay_rejects_final_locator_drift(
    monkeypatch: pytest.MonkeyPatch,
    final_url: str,
) -> None:
    official_url = "https://example.gov/code?a=1&b=%2F"

    class _Response:
        status_code = 200
        content = b"archived body"
        url = final_url

        def __init__(self) -> None:
            self.headers = {"content-type": "text/html"}

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: _Response())
    result = await wayback_machine_engine._get_wayback_content_direct(
        official_url,
        timestamp="20260824010203",
        closest=False,
    )

    assert result["status"] == "error"


@pytest.mark.anyio
async def test_direct_exact_replay_rejects_redirect_status_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _Response:
        status_code = 302
        content = b""
        url = "https://web.archive.org/web/20260824010203id_/https://example.gov/code"

        def __init__(self) -> None:
            self.headers = {"location": "https://example.invalid/"}

    def _get(url: str, **kwargs):
        observed.update(url=url, **kwargs)
        return _Response()

    monkeypatch.setattr("requests.get", _get)
    result = await wayback_machine_engine._get_wayback_content_direct(
        "https://example.gov/code",
        timestamp="20260824010203",
        closest=False,
    )

    assert result["status"] == "error"
    assert result["response_status"] == 302
    assert observed["allow_redirects"] is False


@pytest.mark.anyio
async def test_explicit_wayback_replay_keeps_official_and_archive_locators_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/section-1"
    archive_url = (
        "https://web.archive.org/web/20260824010203/"
        "https://example.gov/code/section-1"
    )
    identity_url = (
        "https://web.archive.org/web/20260824010203id_/"
        "https://example.gov/code/section-1"
    )
    body = b"<html><body>Official archived section text.</body></html>"

    async def _get_content(*, url: str, timestamp: str, closest: bool):
        assert url == official_url
        assert timestamp == "20260824010203"
        assert closest is False
        return {
            "status": "success",
            "response_status": 200,
            "content": body,
            "original_url": official_url,
            "capture_timestamp": timestamp,
            "wayback_url": identity_url,
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )

    result = await ArchivalFetchClient(
        content_validator=lambda payload: payload == body
    ).fetch_wayback_replay(archive_url)

    assert result is not None
    assert result.url == official_url
    assert result.archive_url == identity_url
    assert result.archive_timestamp == "20260824010203"
    assert result.source == "wayback"
    assert result.content_sha256 == hashlib.sha256(body).hexdigest()


@pytest.mark.anyio
async def test_exact_capture_batch_preserves_percent_encoded_official_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/Chapter%201.xml"
    timestamp = "20260824010203"
    archive_url = (
        f"https://web.archive.org/web/{timestamp}id_/{official_url}"
    )
    body = b"<?xml version='1.0'?><Chapter><Name>1</Name></Chapter>"
    observed: dict[str, object] = {}

    async def _get_content(*, url: str, timestamp: str, closest: bool):
        observed.update(url=url, timestamp=timestamp, closest=closest)
        return {
            "status": "success",
            "response_status": 200,
            "content": body,
            "original_url": official_url,
            "capture_timestamp": timestamp,
            "wayback_url": archive_url.replace("20260824010203/", "20260824010203id_/"),
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )
    client = ArchivalFetchClient(content_validator=lambda payload: payload == body)
    outcome = await client.fetch_wayback_captures(
        [
            (
                official_url,
                {
                    "original_url": official_url,
                    "status_code": 200,
                    "timestamp": timestamp,
                    "wayback_url": archive_url,
                    **_capture_discovery(official_url),
                },
            )
        ],
        max_concurrency=1,
    )

    assert observed == {
        "url": official_url,
        "timestamp": timestamp,
        "closest": False,
    }
    assert outcome.errors == [None]
    assert outcome.results[0] is not None
    assert outcome.results[0].content == body
    assert outcome.stats["replay_calls"] == 1
    assert outcome.stats["successful_pages"] == 1


@pytest.mark.anyio
async def test_exact_capture_batch_rejects_percent_decoded_path_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/title/section.xml"
    timestamp = "20260824010203"
    archive_url = (
        f"https://web.archive.org/web/{timestamp}id_/"
        "https://example.gov/code/title%2Fsection.xml"
    )

    async def _forbid(*_args, **_kwargs):
        raise AssertionError("encoded path alias must fail before replay")

    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))
    monkeypatch.setattr(client, "fetch_wayback_replay", _forbid)
    outcome = await client.fetch_wayback_captures(
        [
            (
                official_url,
                {
                    "original_url": official_url,
                    "status_code": 200,
                    "timestamp": timestamp,
                    "wayback_url": archive_url,
                    **_capture_discovery(official_url),
                },
            )
        ]
    )

    assert outcome.results == [None]
    assert outcome.stats["replay_calls"] == 0
    assert "not bound to the exact capture" in str(outcome.errors[0])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "archived_original",
    [
        "https://example.gov/code?b=2&a=1",
        "https://example.gov/code?a=1+2&b=2",
        "https://example.gov/code?a=1&b=2/",
        "https://example.gov/code?a=1&b=%32",
    ],
)
async def test_exact_capture_batch_rejects_raw_query_aliases_before_replay(
    monkeypatch: pytest.MonkeyPatch,
    archived_original: str,
) -> None:
    official_url = "https://example.gov/code?a=1&b=2"
    timestamp = "20260824010203"

    async def _forbid(*_args, **_kwargs):
        raise AssertionError("query alias must fail before replay")

    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))
    monkeypatch.setattr(client, "fetch_wayback_replay", _forbid)
    outcome = await client.fetch_wayback_captures(
        [
            (
                official_url,
                {
                    "original_url": archived_original,
                    "status_code": 200,
                    "timestamp": timestamp,
                    "wayback_url": (
                        f"https://web.archive.org/web/{timestamp}id_/"
                        f"{archived_original}"
                    ),
                },
            )
        ]
    )

    assert outcome.results == [None]
    assert outcome.stats["replay_calls"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "archive_url",
    [
        "http://web.archive.org/web/20260824010203id_/https://example.gov/code",
        "https://www.web.archive.org/web/20260824010203id_/https://example.gov/code",
        "https://web.archive.org:443/web/20260824010203id_/https://example.gov/code",
        "https://user@web.archive.org/web/20260824010203id_/https://example.gov/code",
        "https://web.archive.org/prefix/web/20260824010203id_/https://example.gov/code",
        "https://web.archive.org/web/20260824010203id_/https://example.gov/code#",
    ],
)
async def test_state_replay_rejects_noncanonical_initial_archive_locator(
    monkeypatch: pytest.MonkeyPatch,
    archive_url: str,
) -> None:
    async def _forbid(**_kwargs):
        raise AssertionError("invalid initial replay must fail before transport")

    monkeypatch.setattr(wayback_machine_engine, "get_wayback_content", _forbid)
    result = await ArchivalFetchClient(
        content_validator=lambda payload: bool(payload)
    ).fetch_wayback_replay(archive_url)

    assert result is None


@pytest.mark.anyio
async def test_explicit_wayback_replay_rejects_capture_timestamp_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_url = (
        "https://web.archive.org/web/20260824010203/"
        "https://example.gov/code/section-1"
    )

    async def _get_content(**_kwargs):
        return {
            "status": "success",
            "response_status": 200,
            "content": b"archived body",
            "original_url": "https://example.gov/code/section-1",
            "capture_timestamp": "20260825010203",
            "wayback_url": archive_url,
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )

    result = await ArchivalFetchClient(
        content_validator=lambda payload: bool(payload)
    ).fetch_wayback_replay(archive_url)

    assert result is None


@pytest.mark.anyio
async def test_explicit_wayback_replay_rejects_archive_locator_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/section-1"
    archive_url = (
        "https://web.archive.org/web/20260824010203/"
        f"{official_url}"
    )

    async def _get_content(**_kwargs):
        return {
            "status": "success",
            "response_status": 200,
            "content": b"archived body",
            "original_url": official_url,
            "capture_timestamp": "20260824010203",
            "wayback_url": (
                "https://web.archive.org/web/20260824010203id_/"
                "https://example.gov/code/section-2"
            ),
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )

    result = await ArchivalFetchClient(
        content_validator=lambda payload: bool(payload)
    ).fetch_wayback_replay(archive_url)

    assert result is None


@pytest.mark.anyio
async def test_explicit_wayback_replay_rejects_non_200_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_url = (
        "https://web.archive.org/web/20260824010203/"
        "https://example.gov/code/section-1"
    )

    async def _get_content(**_kwargs):
        return {
            "status": "success",
            "response_status": 404,
            "content": b"archived not-found body",
            "original_url": "https://example.gov/code/section-1",
            "capture_timestamp": "20260824010203",
            "wayback_url": archive_url.replace("20260824010203/", "20260824010203id_/"),
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )

    result = await ArchivalFetchClient(
        content_validator=lambda payload: bool(payload)
    ).fetch_wayback_replay(archive_url)

    assert result is None


@pytest.mark.anyio
async def test_exact_capture_batch_retries_transient_429_status_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/section-1"
    timestamp = "20260824010203"
    archive_url = (
        f"https://web.archive.org/web/{timestamp}id_/{official_url}"
    )
    body = b"<html><body>Official archived section text.</body></html>"
    content_calls = 0

    async def _get_content(**_kwargs):
        nonlocal content_calls
        content_calls += 1
        if content_calls == 1:
            return {
                "status": "error",
                "response_status": 429,
                "error": "HTTP 429 Too Many Requests",
            }
        return {
            "status": "success",
            "response_status": 200,
            "content": body,
            "original_url": official_url,
            "capture_timestamp": timestamp,
            "wayback_url": archive_url,
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )
    client = ArchivalFetchClient(content_validator=lambda payload: payload == body)
    outcome = await client.fetch_wayback_captures(
        [
            (
                official_url,
                {
                    "original_url": official_url,
                    "status_code": 200,
                    "timestamp": timestamp,
                    "wayback_url": archive_url,
                    **_capture_discovery(official_url),
                },
            )
        ],
        replay_attempts=2,
    )

    assert content_calls == 2
    assert outcome.results[0] is not None
    assert outcome.stats["transient_first_pass_failures"] == 1
    assert outcome.stats["replay_retry_pages"] == 1
    assert outcome.stats["replay_retry_successes"] == 1


@pytest.mark.anyio
async def test_exact_pdf_capture_rejects_wrong_html_body_at_caller_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/section-1"
    timestamp = "20260824010203"
    archive_url = (
        f"https://web.archive.org/web/{timestamp}id_/{official_url}"
    )
    content_calls = 0

    async def _get_content(**_kwargs):
        nonlocal content_calls
        content_calls += 1
        return {
            "status": "success",
            "response_status": 200,
            "content": b"<html><body>archive navigation scaffold</body></html>",
            "original_url": official_url,
            "capture_timestamp": timestamp,
            "wayback_url": archive_url,
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )
    client = ArchivalFetchClient(
        content_validator=lambda payload: payload.startswith(b"%PDF-")
    )
    outcome = await client.fetch_wayback_captures(
        [
            (
                official_url,
                {
                    "original_url": official_url,
                    "status_code": 200,
                    "timestamp": timestamp,
                    "wayback_url": archive_url,
                    **_capture_discovery(official_url),
                },
            )
        ],
        replay_attempts=2,
    )

    assert content_calls == 1
    assert outcome.results == [None]
    assert outcome.stats["transient_first_pass_failures"] == 0
    assert outcome.stats["semantic_first_pass_failures"] == 1
    assert outcome.stats["replay_retry_calls"] == 0


@pytest.mark.anyio
async def test_wayback_fallback_skips_non_200_cdx_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://example.gov/code/section-1"
    content_fetches = 0

    async def _inventory(urls, **_kwargs):
        assert list(urls) == [official_url]
        return {
            "status": "success",
            "captures_by_url": {
                official_url: {
                    "original_url": official_url,
                    "timestamp": "20260824010203",
                    "status_code": "404",
                    "wayback_url": (
                        "https://web.archive.org/web/20260824010203id_/"
                        f"{official_url}"
                    ),
                }
            },
        }

    async def _get_content(**_kwargs):
        nonlocal content_fetches
        content_fetches += 1
        return {
            "status": "success",
            "response_status": 200,
            "content": b"should not be fetched",
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_capture_inventory",
        _inventory,
    )
    monkeypatch.setattr(
        wayback_machine_engine,
        "get_wayback_content",
        _get_content,
    )

    result = await ArchivalFetchClient(
        content_validator=lambda payload: bool(payload)
    )._fetch_from_wayback(official_url)

    assert result is None
    assert content_fetches == 0


@pytest.mark.anyio
async def test_new_hampshire_and_oklahoma_replay_helpers_use_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
        NewHampshireScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import (
        OklahomaScraper,
    )

    archive_url = (
        "https://web.archive.org/web/20260824010203/"
        "https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm"
    )
    calls: list[str] = []

    async def _shared_replay(url: str, **_kwargs) -> bytes:
        calls.append(url)
        return b"<html>Archived statute text.</html>"

    new_hampshire = NewHampshireScraper("NH", "New Hampshire")
    oklahoma = OklahomaScraper("OK", "Oklahoma")
    monkeypatch.setattr(
        new_hampshire,
        "_fetch_wayback_replay_parser_input",
        _shared_replay,
    )
    monkeypatch.setattr(
        oklahoma,
        "_fetch_wayback_replay_parser_input",
        _shared_replay,
    )

    assert "Archived statute" in await new_hampshire._request_archival_source_text_direct(
        archive_url,
        timeout=9,
    )
    assert "Archived statute" in await oklahoma._request_wayback_text(
        archive_url,
        headers={"User-Agent": "test"},
        timeout=9,
    )
    assert calls == [archive_url, archive_url]
