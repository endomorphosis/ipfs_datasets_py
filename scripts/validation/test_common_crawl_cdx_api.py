#!/usr/bin/env python3
"""Focused Common Crawl CDX (pywb-style) API diagnostic.

This script follows the pywb CDX Server API parameter conventions:
- url (required)
- matchType=exact|prefix|host|domain
- output=json
- filter=status:200
- limit

It targets Common Crawl's public CDX endpoints:
  https://index.commoncrawl.org/<CC-MAIN-YYYY-NN>-index

It is meant to answer: are Common Crawl failures due to our code, or due to
network reachability / upstream issues?

Usage:
  python scripts/validation/test_common_crawl_cdx_api.py --url https://library.municode.com/wa/seattle

Optional:
  --index CC-MAIN-2025-50 (skip collinfo discovery)
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


_PROXIES: Optional[Dict[str, str]] = None
_USER_AGENT: str = "ipfs-datasets-cdx-diagnostic/1.0"


DEFAULT_FALLBACK_INDEXES = [
    "CC-MAIN-2025-50",
    "CC-MAIN-2025-46",
    "CC-MAIN-2025-42",
    "CC-MAIN-2025-38",
    "CC-MAIN-2025-33",
    "CC-MAIN-2024-52",
    "CC-MAIN-2024-46",
]


def _detect_local_tor_socks_url() -> str:
    """Return a likely local Tor SOCKS URL.

    Prefers ports that are reachable on localhost:
    - 9050: typical Tor daemon
    - 9150: typical Tor Browser

    Returns a socks5h URL (proxy DNS) even if the port probe fails.
    """
    for port in (9050, 9150):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.35):
                return f"socks5h://127.0.0.1:{port}"
        except Exception:
            continue
    return "socks5h://127.0.0.1:9050"


@dataclass
class CDXProbeResult:
    ok: bool
    index: str
    matchType: str
    query_url: str
    error: Optional[str] = None
    record: Optional[Dict[str, Any]] = None


def _get_indexes(timeout: float) -> List[str]:
    return _get_indexes_from("https://index.commoncrawl.org/collinfo.json", timeout)


def _get_indexes_from(collinfo_url: str, timeout: float) -> List[str]:
    try:
        r = requests.get(
            collinfo_url,
            timeout=min(timeout, 10.0),
            headers={"User-Agent": _USER_AGENT},
            proxies=_PROXIES,
        )
        r.raise_for_status()
        data = r.json()
        ids = [d.get("id") for d in (data or []) if d.get("id")]
        return ids[:10]
    except Exception:
        return DEFAULT_FALLBACK_INDEXES


def probe_index(
    index_id: str,
    url: str,
    timeout: float,
    match_type: str,
    limit: int = 1,
    cdx_base_url: str = "https://index.commoncrawl.org",
) -> CDXProbeResult:
    base = (cdx_base_url or "https://index.commoncrawl.org").rstrip("/")
    endpoint = f"{base}/{index_id}-index"

    params = {
        "url": url,
        "matchType": match_type,
        "output": "json",
        "limit": limit,
        # Common Crawl CDX API accepts `status:200` (the older pywb-style `==status:200` returns HTTP 404).
        "filter": "status:200",
    }

    try:
        resp = requests.get(
            endpoint,
            params=params,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            proxies=_PROXIES,
        )
        resp.raise_for_status()
        text = resp.text or ""
        first = text.splitlines()[0].strip() if text else ""
        if not first:
            return CDXProbeResult(ok=False, index=index_id, matchType=match_type, query_url=url, error="no results")
        rec = json.loads(first)
        return CDXProbeResult(ok=True, index=index_id, matchType=match_type, query_url=url, record=rec)
    except Exception as e:
        return CDXProbeResult(ok=False, index=index_id, matchType=match_type, query_url=url, error=str(e))


def main() -> int:
    global _USER_AGENT

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="URL to query")
    ap.add_argument("--timeout", type=float, default=6.0)
    ap.add_argument("--index", default=None, help="Specific CC-MAIN index id to use (optional)")
    ap.add_argument("--cdx-base-url", default="https://index.commoncrawl.org", help="Base URL for the CC CDX service (proxy/mirror)")
    ap.add_argument("--collinfo-url", default="https://index.commoncrawl.org/collinfo.json", help="URL for collinfo.json (proxy/mirror)")
    ap.add_argument("--proxy", default=None, help="Optional HTTP(S) proxy URL (e.g. http://127.0.0.1:3128 or http://user:pass@host:3128)")
    ap.add_argument("--tor", action="store_true", help="Route requests through local Tor (SOCKS on 9050/9150). Requires PySocks.")
    ap.add_argument(
        "--user-agent",
        default=_USER_AGENT,
        help="User-Agent to send to Common Crawl services (recommended to be descriptive).",
    )
    args = ap.parse_args()
    _USER_AGENT = (args.user_agent or _USER_AGENT).strip() or _USER_AGENT

    global _PROXIES
    _PROXIES = None
    proxy = args.proxy
    if args.tor and not proxy:
        proxy = _detect_local_tor_socks_url()

    if proxy:
        p = proxy.strip()
        _PROXIES = {"http": p, "https": p}
        if p.lower().startswith("socks"):
            try:
                import socks  # type: ignore
            except Exception as e:
                print(json.dumps({
                    "error": "SOCKS proxy configured but PySocks is not installed. Install requests[socks] or pysocks.",
                    "detail": str(e),
                }, indent=2))
                return 3

    url = args.url.strip()

    # First, a quick collinfo reachability check (helps diagnose ISP/network blocks).
    collinfo_ok = False
    collinfo_error: Optional[str] = None
    try:
        r = requests.get(
            args.collinfo_url,
            timeout=min(args.timeout, 10.0),
            headers={"User-Agent": _USER_AGENT},
            proxies=_PROXIES,
        )
        collinfo_ok = 200 <= r.status_code < 300
    except Exception as e:
        collinfo_error = str(e)

    indexes = [args.index] if args.index else _get_indexes_from(args.collinfo_url, args.timeout)

    # Probe exact first, then prefix on host root.
    from urllib.parse import urlparse

    parsed = urlparse(url)
    prefix = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else url

    start = time.time()
    results: List[CDXProbeResult] = []

    for idx in indexes[:6]:
        results.append(probe_index(idx, url, args.timeout, match_type="exact", cdx_base_url=args.cdx_base_url))
        results.append(probe_index(idx, prefix, args.timeout, match_type="prefix", cdx_base_url=args.cdx_base_url))

        # Stop early if we got at least one hit.
        if any(r.ok for r in results[-2:]):
            break

    elapsed = time.time() - start

    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]

    print(json.dumps(
        {
            "input_url": url,
            "timeout": args.timeout,
            "cdx_base_url": args.cdx_base_url,
            "collinfo_url": args.collinfo_url,
            "collinfo_ok": collinfo_ok,
            "collinfo_error": collinfo_error,
            "proxy": proxy,
            "tor": bool(args.tor),
            "user_agent": _USER_AGENT,
            "indexes_tried": [r.index for r in results],
            "ok_count": len(ok),
            "fail_count": len(bad),
            "elapsed_s": round(elapsed, 3),
            "first_ok": ok[0].record if ok else None,
            "first_error": bad[0].error if bad else None,
        },
        indent=2,
    ))

    # Exit code: 0 if any success, 2 if all failed.
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
