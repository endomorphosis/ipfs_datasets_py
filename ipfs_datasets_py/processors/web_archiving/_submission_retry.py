"""Finite submission retries and cooperative per-endpoint pacing.

The caller's budget includes queueing and retry delays. HTTP connection/read
inactivity timeouts are capped by its remaining budget; no background request
thread survives cancellation of the submission coroutine.
"""
import asyncio
from email.utils import parsedate_to_datetime
import math
from threading import Lock
from time import monotonic, time

_sleep = asyncio.sleep


class SubmissionTimeout(TimeoutError):
    pass


def submission_deadline(timeout):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a finite positive number")
    seconds = float(timeout)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be a finite positive number")
    return monotonic() + seconds


def remaining(deadline):
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise SubmissionTimeout("archive submission timeout budget exhausted")
    return seconds


def _retry_after(headers):
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(str(value)).timestamp() - time()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


async def _delay(seconds, deadline):
    budget = remaining(deadline)
    if seconds >= budget:
        raise SubmissionTimeout("archive retry delay exceeds remaining timeout budget")
    if seconds > 0:
        await _sleep(seconds)
    remaining(deadline)


class SubmissionGate:
    """Serialize request starts across event loops without a blocking lock wait."""
    def __init__(self):
        self._lock = Lock()
        self._last_started = -math.inf

    async def send(self, request, *, deadline, interval):
        while not self._lock.acquire(blocking=False):
            await _delay(min(0.05, remaining(deadline) / 2), deadline)
        try:
            await _delay(max(0.0, self._last_started + interval - monotonic()), deadline)
            self._last_started = monotonic()
            response = request(min(30.0, remaining(deadline)))
            try:
                remaining(deadline)
            except SubmissionTimeout:
                response.close()
                raise
            return response
        finally:
            self._lock.release()


async def submit_with_retry(request, *, gate, deadline, attempts, interval):
    import requests
    transient = {429, 500, 502, 503, 504}
    for attempt in range(attempts):
        response = None
        try:
            response = await gate.send(request, deadline=deadline, interval=interval)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if response is not None and response.status_code not in transient:
                raise
            if attempt + 1 == attempts:
                raise
            delay = _retry_after(getattr(response, "headers", {}) or {}) if response is not None else None
            await _delay(delay if delay is not None else min(30.0, 2.0 ** (attempt + 1)), deadline)
        finally:
            if response is not None and response.status_code >= 400:
                response.close()
