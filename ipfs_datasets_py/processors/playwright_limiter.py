"""Shared Playwright concurrency limiter.

This module caps concurrent browser launches across async scraping paths so
large admin-rules runs do not fan out into hundreds of Playwright driver
processes at once.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator


logger = logging.getLogger(__name__)

_PLAYWRIGHT_LIMIT_ENV = "IPFS_DATASETS_PY_PLAYWRIGHT_MAX_CONCURRENT_BROWSERS"
_DEFAULT_PLAYWRIGHT_LIMIT = 6

_semaphore: asyncio.Semaphore | None = None
_semaphore_loop_id: int | None = None
_semaphore_limit: int | None = None


def get_playwright_browser_limit() -> int:
    raw_limit = os.getenv(_PLAYWRIGHT_LIMIT_ENV, str(_DEFAULT_PLAYWRIGHT_LIMIT)).strip()
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s=%r; using default %d",
            _PLAYWRIGHT_LIMIT_ENV,
            raw_limit,
            _DEFAULT_PLAYWRIGHT_LIMIT,
        )
        return _DEFAULT_PLAYWRIGHT_LIMIT
    if limit <= 0:
        return 1
    return limit


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_limit, _semaphore_loop_id

    limit = get_playwright_browser_limit()
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    if (
        _semaphore is None
        or _semaphore_loop_id != loop_id
        or _semaphore_limit != limit
    ):
        _semaphore = asyncio.Semaphore(limit)
        _semaphore_loop_id = loop_id
        _semaphore_limit = limit
    return _semaphore


@asynccontextmanager
async def acquire_playwright_slot() -> AsyncIterator[None]:
    semaphore = _get_semaphore()
    await semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()