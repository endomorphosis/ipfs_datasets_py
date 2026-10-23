#!/usr/bin/env python3
"""Robust fetch helper for the Italy pilot.

The egress proxy drops/refuses connections intermittently (observed
2026-10-14: identical hosts alternating 200 / connect-timeout within
minutes). fetch() retries connect/read failures with backoff and caps
response size so slow-drip servers cannot hang a run. Pacing: callers
sleep between requests to the same host.
"""
import time

import requests

UA = "ipfs_datasets_py world-municipal pilot (open legal data research)"


def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def fetch(session, url, *, binary=False, max_bytes=4_000_000,
          timeout=(15, 30), tries=6, backoff=5.0, deadline=300.0):
    """GET with retries on transient errors. Returns (status, final_url, bytes).

    Retries: connection errors, timeouts, 5xx. 4xx returned as-is.
    A wall-clock deadline bounds the whole call — tarpitting servers
    that stall every read must not hold a run hostage (observed
    2026-10-14 on comune.* hosts). Raises the last exception after
    all tries / at the deadline.
    """
    import sys as _sys

    last = None
    t_start = time.time()
    for attempt in range(tries):
        try:
            with session.get(url, timeout=timeout, stream=True) as r:
                if r.status_code >= 500:
                    last = RuntimeError(f"HTTP {r.status_code} for {url}")
                    raise last
                chunks, total = [], 0
                for chunk in r.iter_content(65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= max_bytes:
                        break
                body = b"".join(chunks)
                return r.status_code, r.url, body
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError, RuntimeError) as e:
            last = e
            print(f"    fetch try {attempt + 1}/{tries} failed "
                  f"({type(e).__name__}) {url[:80]}", file=_sys.stderr,
                  flush=True)
            if attempt + 1 < tries and time.time() - t_start < deadline:
                time.sleep(backoff * (attempt + 1))
            if time.time() - t_start >= deadline:
                break
    raise last  # type: ignore[misc]
