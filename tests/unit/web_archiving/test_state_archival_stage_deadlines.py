from __future__ import annotations

import asyncio
import threading
import time

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
    FetchResult,
)


def _watchdog_release(event: threading.Event, seconds: float = 3.0) -> threading.Timer:
    """Keep a regression from leaving a deliberately blocking test hung."""

    timer = threading.Timer(seconds, event.set)
    timer.daemon = True
    timer.start()
    return timer


@pytest.mark.parametrize("blocked_stage", ["wayback"])
def test_singleton_blocking_archive_stage_has_hard_deadline(
    monkeypatch: pytest.MonkeyPatch,
    blocked_stage: str,
) -> None:
    target_url = f"https://codes.example.gov/{blocked_stage}/missing"
    entered = threading.Event()
    release = threading.Event()
    stage_order: list[str] = []
    backoffs: list[tuple[str, str, str]] = []

    async def _wayback(url: str):
        del url
        stage_order.append("wayback")
        if blocked_stage == "wayback":
            entered.set()
            release.wait()
        return None

    async def _archive_is(url: str):
        del url
        stage_order.append("archive_is")
        entered.set()
        release.wait()
        return None

    client = ArchivalFetchClient(
        request_timeout_seconds=30,
        enable_common_crawl=False,
        enable_direct=False,
        enable_archive_is=blocked_stage == "archive_is",
    )
    monkeypatch.setenv("LEGAL_SCRAPER_ARCHIVAL_STAGE_TIMEOUT_SECONDS", "0.1")
    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_WAYBACK", raising=False)
    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_ARCHIVE_IS", raising=False)
    monkeypatch.setattr(client, "_is_stage_backed_off", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        client,
        "_mark_stage_backoff",
        lambda stage, *, reason, url: backoffs.append((stage, reason, url)),
    )
    monkeypatch.setattr(client, "_fetch_from_wayback", _wayback)
    monkeypatch.setattr(client, "_fetch_from_archive_is", _archive_is)

    watchdog = _watchdog_release(release)
    started_at = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="Unable to fetch URL"):
            asyncio.run(
                client.fetch_with_fallback(
                    target_url,
                    enable_common_crawl=False,
                    enable_archive_is=blocked_stage == "archive_is",
                )
            )
    finally:
        elapsed = time.monotonic() - started_at
        release.set()
        watchdog.cancel()

    assert entered.is_set()
    assert elapsed < 1.0
    assert stage_order == (
        ["wayback"]
        if blocked_stage == "wayback"
        else ["wayback", "archive_is"]
    )
    assert len(backoffs) == 1
    assert backoffs[0][0] == blocked_stage
    assert backoffs[0][2] == target_url
    assert "hard stage deadline" in backoffs[0][1]


def test_archive_is_is_not_called_by_parser_authorizing_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ArchivalFetchClient(
        enable_common_crawl=False,
        enable_direct=False,
        enable_wayback=False,
        enable_archive_is=True,
    )

    async def _forbid(_url: str):
        raise AssertionError("archive.is must remain outside fresh acquisition")

    monkeypatch.setattr(client, "_fetch_from_archive_is", _forbid)
    with pytest.raises(RuntimeError, match="Unable to fetch URL"):
        asyncio.run(
            client.fetch_with_fallback(
                "https://codes.example.gov/archive-is-disabled",
                enable_common_crawl=False,
                enable_archive_is=True,
            )
        )


def test_plural_residual_timeout_retains_aligned_sibling_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successful_url = "https://codes.example.gov/title/1"
    blocked_url = "https://codes.example.gov/title/2"
    entered = threading.Event()
    release = threading.Event()
    callbacks: list[tuple[str, bytes, str]] = []

    def _direct(url: str):
        if url != successful_url:
            return None
        return FetchResult(
            url=url,
            content=b"retained official sibling",
            source="direct",
            fetched_at="2026-08-25T00:00:00+00:00",
            status_code=200,
        )

    async def _blocking_wayback(url: str):
        assert url == blocked_url
        entered.set()
        release.wait()
        return None

    def _callback(url: str, result: FetchResult) -> None:
        callbacks.append((url, bytes(result.content), result.source))

    client = ArchivalFetchClient(
        request_timeout_seconds=30,
        content_validator=lambda payload: bool(payload),
        enable_common_crawl=False,
        enable_direct=True,
        enable_archive_is=False,
    )
    monkeypatch.setenv("LEGAL_SCRAPER_RESIDUAL_FALLBACK_TIMEOUT_SECONDS", "1")
    # The plural residual deadline must win while the real stage integration is
    # blocked inside its own worker loop.
    monkeypatch.setenv("LEGAL_SCRAPER_ARCHIVAL_STAGE_TIMEOUT_SECONDS", "60")
    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_WAYBACK", raising=False)
    monkeypatch.setattr(client, "_fetch_direct", _direct)
    monkeypatch.setattr(client, "_fetch_from_wayback", _blocking_wayback)
    monkeypatch.setattr(client, "_is_stage_backed_off", lambda *_args, **_kwargs: False)

    watchdog = _watchdog_release(release)
    started_at = time.monotonic()
    try:
        result = asyncio.run(
            client.fetch_many_with_fallback(
                [successful_url, blocked_url],
                enable_common_crawl=False,
                enable_archive_is=False,
                max_concurrency=2,
                prefer_direct=True,
                result_callback=_callback,
            )
        )
    finally:
        elapsed = time.monotonic() - started_at
        release.set()
        watchdog.cancel()

    assert entered.is_set()
    assert elapsed < 2.0
    assert len(result.results) == 2
    assert result.results[0] is not None
    assert result.results[0].content == b"retained official sibling"
    assert result.results[1] is None
    assert result.errors[0] is None
    assert result.errors[1] == (
        "TimeoutError: residual archival fallback exceeded 1s"
    )
    assert callbacks == [
        (successful_url, b"retained official sibling", "direct")
    ]
    assert result.stats["direct_initial_requests"] == 2
    assert result.stats["direct_initial_successes"] == 1
    assert result.stats["fallback_requests"] == 1
    assert result.stats["residual_fallback_timeout_seconds"] == 1
    assert result.stats["successful_pages"] == 1
    assert result.stats["failed_pages"] == 1
