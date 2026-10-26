"""Submission regressions with real response semantics and no external network."""
from __future__ import annotations

import asyncio
from email.utils import formatdate
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from ipfs_datasets_py.processors.web_archiving import _submission_retry as retry
from ipfs_datasets_py.processors.web_archiving import archive_is_engine as archive_is
from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine as wayback


class Clock:
    now = 0.0

    def __init__(self):
        self.sleeps = []

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(retry, "monotonic", lambda: value.now)
    monkeypatch.setattr(retry, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(retry, "_sleep", value.sleep)
    monkeypatch.setattr(archive_is, "_SUBMIT_GATE", retry.SubmissionGate())
    monkeypatch.setattr(wayback, "_WAYBACK_SUBMIT_GATE", retry.SubmissionGate())
    return value


def response(status=200, *, url="https://archive.is/abcde", text="", headers=None):
    value = requests.Response()
    value.status_code = status
    value.url = url
    value._content = text.encode()
    value._content_consumed = True
    value.headers.update(headers or {})
    value.close = Mock(wraps=value.close)
    return value


def transport(monkeypatch, method, outcomes, clock):
    pending = iter(outcomes)
    calls = []

    def request(url, **kwargs):
        calls.append((clock.now, url, kwargs))
        result = next(pending)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(requests, method, request)
    return calls


def test_archive_is_honors_retry_after_and_endpoint_pacing(monkeypatch, clock):
    replies = [response(429, headers={"Retry-After": "12"}), response()]
    calls = transport(monkeypatch, "post", replies, clock)
    result = asyncio.run(archive_is.archive_to_archive_is("https://example.org", timeout=20))
    assert result["status"] == "success"
    assert [call[0] for call in calls] == [0, 12]
    assert [call[2]["timeout"] for call in calls] == [20, 8]
    assert calls[0][2]["data"]["url"] == "https://example.org"
    for reply in replies:
        reply.close.assert_called_once()


def test_wayback_transient_network_and_server_failures_then_success(monkeypatch, clock):
    calls = transport(monkeypatch, "get", [
        requests.ConnectionError("offline fixture"), response(503), response(),
    ], clock)
    result = asyncio.run(wayback.archive_to_wayback("https://example.org", timeout=7))
    assert result["status"] == "success"
    assert [call[0] for call in calls] == [0, 2, 6]
    assert [call[2]["timeout"] for call in calls] == [7, 5, 1]


@pytest.mark.parametrize("engine,method,limit", [
    (archive_is.archive_to_archive_is, "post", 4),
    (wayback.archive_to_wayback, "get", 3),
])
def test_submission_attempts_are_finite(monkeypatch, clock, engine, method, limit):
    calls = transport(monkeypatch, method, [response(503) for _ in range(limit)], clock)
    result = asyncio.run(engine("https://example.org", timeout=100))
    assert result["status"] == "error"
    assert len(calls) == limit


@pytest.mark.parametrize("engine,method", [
    (archive_is.archive_to_archive_is, "post"),
    (wayback.archive_to_wayback, "get"),
])
def test_permanent_http_rejection_is_not_retried(monkeypatch, clock, engine, method):
    reply = response(403)
    calls = transport(monkeypatch, method, [reply], clock)
    assert asyncio.run(engine("https://example.org", timeout=20))["status"] == "error"
    assert len(calls) == 1
    assert clock.sleeps == []
    reply.close.assert_called_once()


def test_retry_after_larger_than_budget_cannot_start_another_request(monkeypatch, clock):
    calls = transport(monkeypatch, "get", [response(429, headers={"Retry-After": "120"})], clock)
    result = asyncio.run(wayback.archive_to_wayback("https://example.org", timeout=3))
    assert result["status"] == "timeout"
    assert len(calls) == 1
    assert clock.sleeps == []


def test_http_date_retry_after_is_respected(monkeypatch, clock):
    calls = transport(monkeypatch, "get", [
        response(429, headers={"Retry-After": formatdate(1_700_000_006, usegmt=True)}),
        response(),
    ], clock)
    assert asyncio.run(wayback.archive_to_wayback("https://example.org", timeout=8))["status"] == "success"
    assert [call[0] for call in calls] == [0, 6]


def test_endpoint_queueing_consumes_callers_budget_across_event_loops(monkeypatch, clock):
    calls = transport(monkeypatch, "post", [response()], clock)
    assert asyncio.run(archive_is.archive_to_archive_is("https://example.org", timeout=1))["status"] == "success"
    assert asyncio.run(archive_is.archive_to_archive_is("https://example.org/next", timeout=1))["status"] == "timeout"
    assert len(calls) == 1


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, "3"])
def test_invalid_timeout_never_submits(monkeypatch, clock, timeout):
    calls = transport(monkeypatch, "get", [], clock)
    assert asyncio.run(wayback.archive_to_wayback("https://example.org", timeout=timeout))["status"] == "error"
    assert calls == []


def test_unknown_archive_response_does_not_invent_success(monkeypatch, clock):
    transport(monkeypatch, "post", [response(url="https://archive.is/submit/", text="unexpected page")], clock)
    result = asyncio.run(archive_is.archive_to_archive_is("https://example.org", timeout=2))
    assert result["status"] == "error"
    assert "archive_url" not in result


def test_installed_internetarchive_does_not_skip_real_submission(monkeypatch, clock):
    monkeypatch.setitem(sys.modules, "internetarchive", SimpleNamespace())
    calls = transport(monkeypatch, "get", [response(403)], clock)
    assert asyncio.run(wayback.archive_to_wayback("https://example.org", timeout=0.5))["status"] == "error"
    assert len(calls) == 1
    assert calls[0][2]["timeout"] == 0.5


def test_completion_poll_receives_only_remaining_submission_budget(monkeypatch, clock):
    submitted = response(url="https://archive.is/submit/", text='{"submitid":"job1"}')
    processing = response(404)

    def post(*args, **kwargs):
        clock.now += 2
        return submitted

    monkeypatch.setattr(requests, "post", post)
    calls = transport(monkeypatch, "get", [processing], clock)
    result = asyncio.run(archive_is.archive_to_archive_is("https://example.org", timeout=3))
    assert result["status"] == "timeout"
    assert len(calls) == 1
    assert calls[0][2]["timeout"] == 1
    assert clock.sleeps == [1]
    assert clock.now == 3
    submitted.close.assert_called_once()
    processing.close.assert_called_once()


def test_completion_poll_closes_success_response(monkeypatch, clock):
    submitted = response(url="https://archive.is/submit/", text='{"submitid":"job1"}')
    completed = response()
    transport(monkeypatch, "post", [submitted], clock)
    transport(monkeypatch, "get", [completed], clock)
    assert asyncio.run(archive_is.archive_to_archive_is("https://example.org", timeout=3))["status"] == "success"
    submitted.close.assert_called_once()
    completed.close.assert_called_once()


def test_late_response_cannot_report_success(monkeypatch, clock):
    def get(*args, **kwargs):
        clock.now += 2
        return response()

    monkeypatch.setattr(requests, "get", get)
    assert asyncio.run(wayback.archive_to_wayback("https://example.org", timeout=1))["status"] == "timeout"


def test_cancelled_pacing_releases_submission_gate(monkeypatch, clock):
    async def scenario():
        gate = retry.SubmissionGate()
        gate._last_started = clock.now
        sleeping = asyncio.Event()

        async def sleep(seconds):
            sleeping.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(retry, "_sleep", sleep)
        task = asyncio.create_task(gate.send(lambda budget: response(), deadline=10, interval=2))
        await sleeping.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = await gate.send(lambda budget: response(), deadline=10, interval=0)
        assert result.status_code == 200

    asyncio.run(scenario())


def test_cancelled_retry_closes_response_without_more_requests(monkeypatch, clock):
    reply = response(429, headers={"Retry-After": "1"})
    calls = transport(monkeypatch, "get", [reply], clock)

    async def scenario():
        sleeping = asyncio.Event()

        async def sleep(seconds):
            sleeping.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(retry, "_sleep", sleep)
        task = asyncio.create_task(wayback.archive_to_wayback("https://example.org", timeout=10))
        await sleeping.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(calls) == 1
    reply.close.assert_called_once()


def test_public_and_mcp_shims_preserve_timeout_forwarding(monkeypatch, clock):
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import archive_to_wayback
    from ipfs_datasets_py.web_archiving.archive_is_engine import archive_to_archive_is

    calls = transport(monkeypatch, "get", [response()], clock)
    assert asyncio.run(archive_to_wayback("https://example.org", timeout=0.25))["status"] == "success"
    assert calls[0][2]["timeout"] == 0.25
    assert archive_to_archive_is is archive_is.archive_to_archive_is
