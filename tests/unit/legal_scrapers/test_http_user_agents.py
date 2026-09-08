"""Canonical fetch User-Agent constants stay in one module."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.http_user_agents import (
    CURLRC_USER_AGENT_LINE,
    DEFAULT_USER_AGENT,
    PAYWALL_RETRY_USER_AGENT,
    PAYWALL_RETRY_USER_AGENT_SECONDARY,
    USER_AGENT_RETRY_SEQUENCE,
    curl_user_agent_args,
    curlrc_text,
    headers_with_user_agent,
    looks_paywalled_or_empty,
    user_agent_retry_sequence,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_user_agent_literals_live_only_in_http_user_agents_module() -> None:
    assert DEFAULT_USER_AGENT == "OpenAI File Downloader, XaiImageApiFetch/1.0"
    assert PAYWALL_RETRY_USER_AGENT.startswith("Claude-User")
    assert "ChatGPT-User/1.0" in PAYWALL_RETRY_USER_AGENT_SECONDARY
    assert USER_AGENT_RETRY_SEQUENCE == (
        DEFAULT_USER_AGENT,
        PAYWALL_RETRY_USER_AGENT,
        PAYWALL_RETRY_USER_AGENT_SECONDARY,
    )


def test_curl_dash_a_and_curlrc_line_use_the_default_constant() -> None:
    assert curl_user_agent_args() == ("-A", DEFAULT_USER_AGENT)
    assert CURLRC_USER_AGENT_LINE == f'user-agent = "{DEFAULT_USER_AGENT}"'
    curlrc = (REPO_ROOT / ".curlrc").read_text(encoding="utf-8")
    assert curlrc == curlrc_text()
    assert DEFAULT_USER_AGENT in curlrc


def test_paywalled_or_empty_detection_and_retry_order() -> None:
    assert looks_paywalled_or_empty(b"", status_code=200)
    assert looks_paywalled_or_empty(b"<html>fortiweb blocked</html>", status_code=403)
    assert looks_paywalled_or_empty(
        b"<html>cookiesrequired</html>",
        status_code=200,
    )
    assert not looks_paywalled_or_empty(
        b"<!DOCTYPE html><html><body>Mississippi Legislature</body></html>",
        status_code=200,
    )
    assert user_agent_retry_sequence() == USER_AGENT_RETRY_SEQUENCE
    assert user_agent_retry_sequence(DEFAULT_USER_AGENT)[0] == DEFAULT_USER_AGENT
    preferred = user_agent_retry_sequence("campaign-ua/1.0")
    assert preferred[0] == "campaign-ua/1.0"
    assert preferred[1:] == USER_AGENT_RETRY_SEQUENCE


def test_archival_fetch_retries_paywall_with_canonical_user_agents() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
        ArchivalFetchClient,
        _HttpResponse,
    )

    seen: list[str] = []
    bodies = {
        DEFAULT_USER_AGENT: _HttpResponse(403, b"<html>fortiweb</html>"),
        PAYWALL_RETRY_USER_AGENT: _HttpResponse(403, b"<html>access denied</html>"),
        PAYWALL_RETRY_USER_AGENT_SECONDARY: _HttpResponse(
            200,
            b"<!DOCTYPE html><html><body>New Hampshire Statutes table of contents nhtoc/nhtoc-</body></html>",
        ),
    }

    client = ArchivalFetchClient(
        enable_insecure_direct=False,
        enable_wayback=False,
        enable_archive_is=False,
        enable_common_crawl=False,
        content_validator=lambda payload: b"<html" in payload.lower(),
    )

    def _fake_request(url, *, timeout, verify, headers):
        agent = headers["User-Agent"]
        seen.append(agent)
        return bodies[agent]

    client._request_with_retries = _fake_request  # type: ignore[method-assign]
    result = client._fetch_direct("https://gc.nh.gov/rsa/html/NHTOC.htm")
    assert result is not None
    assert result.status_code == 200
    assert seen == list(USER_AGENT_RETRY_SEQUENCE)


def test_headers_with_user_agent_overwrite_existing_key() -> None:
    merged = headers_with_user_agent(
        {"Accept": "text/html", "user-agent": "old"},
        DEFAULT_USER_AGENT,
    )
    assert merged["user-agent"] == DEFAULT_USER_AGENT
    assert merged["Accept"] == "text/html"
