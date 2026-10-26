#!/usr/bin/env python3
"""Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent).

Does not import the full ipfs_datasets_py package. Matches:
  search_wayback_machine / get_wayback_content (wayback_machine_engine.py)
  Common Crawl CDX at https://index.commoncrawl.org/
  archive.is newest lookup
Brave Search is skipped when no API key is present.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger("archive_fallbacks")

WAYBACK_CDX = os.environ.get("WAYBACK_CDX", "https://web.archive.org/cdx/search/cdx")   # tip+30o 23:2x PT Oct 1: port 80 to web.archive.org times out; https OK
WAYBACK_WEB = os.environ.get("WAYBACK_WEB", "https://web.archive.org/web")
CC_COLLINFO = "https://index.commoncrawl.org/collinfo.json"
CC_DATA = "https://data.commoncrawl.org"
CC_DATA_HOSTS = (
    "https://data.commoncrawl.org",
    "https://commoncrawl.s3.amazonaws.com",
)
ARCHIVE_IS_NEWEST = "https://archive.is/newest/"
ARCHIVE_PH_NEWEST = "https://archive.ph/newest/"

UA = (
    "legal-corpora-collector/1.0 "
    "(research archive of official national gazettes; polite; "
    "contact via local operator)"
)

CHALLENGE_RE = re.compile(
    r"just\s+a\s+moment|cf-browser-verification|cloudflare|enable\s+javascript|"
    r"you\s+need\s+to\s+enable\s+javascript|tspd_|bobcmn|attention\s+required|"
    r"checking\s+your\s+browser|please\s+wait\s+while\s+we\s+verify|"
    r"request\s+rejected|access\s+denied",
    re.I,
)
SPA_SHELL_RE = re.compile(
    r"<app-root[\s>]|ng-version=|outsystems-ui|data-block=\"MainContent\"|"
    r"id=\"outsystems\"|window\.__INITIAL_STATE__\s*=\s*\{\s*\}",
    re.I,
)

_session: Optional[requests.Session] = None
_cc_indexes: Optional[list[str]] = None
_cc_dead: set[str] = set()
_last_wayback = 0.0
_last_cc = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "*/*"})
        ad = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _session = s
    return _session


def _sleep_wayback(delay: float = 1.0) -> None:
    global _last_wayback
    now = time.time()
    wait = delay - (now - _last_wayback)
    if wait > 0:
        time.sleep(wait)
    _last_wayback = time.time()


def _sleep_cc(delay: float = 0.35) -> None:
    global _last_cc
    now = time.time()
    wait = delay - (now - _last_cc)
    if wait > 0:
        time.sleep(wait)
    _last_cc = time.time()


def has_brave_key() -> bool:
    return bool(
        (os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    )


def is_challenge(html: str, status: int = 200) -> bool:
    if status in (401, 403, 429, 503):
        return True
    if not html:
        return False
    head = html[:8000]
    if CHALLENGE_RE.search(head):
        return True
    if SPA_SHELL_RE.search(head) and len(html) < 8000:
        return True
    return False


def is_spa_shell(html: str, text: str) -> bool:
    if not html:
        return False
    if SPA_SHELL_RE.search(html[:12000]) and len(text or "") < 400:
        return True
    return False


# --- Wayback ---

CDX_PAGE = 200  # large single-shot limits (2000+) 504 on web.archive.org


def _parse_cdx_json(data: Any, mime_prefix: Optional[str] = None) -> tuple[list[dict], Optional[str]]:
    """Parse Wayback CDX JSON, including showResumeKey trailer."""
    if not isinstance(data, list) or len(data) <= 1:
        return [], None
    resume = None
    rows = data
    # Trailer: ..., [], ["resumeKey"]
    if len(data) >= 3 and data[-2] == [] and isinstance(data[-1], list) and data[-1]:
        resume = str(data[-1][0]) if data[-1][0] else None
        rows = data[:-2]
    headers = rows[0] if rows else []
    out: list[dict] = []
    for row in rows[1:]:
        if not row:
            continue
        rec = dict(zip(headers, row)) if headers and isinstance(headers[0], str) else {}
        if not rec and isinstance(row, list) and len(row) >= 5:
            rec = {
                "urlkey": row[0],
                "timestamp": row[1],
                "original": row[2],
                "mimetype": row[3],
                "statuscode": row[4],
                "digest": row[5] if len(row) > 5 else "",
                "length": row[6] if len(row) > 6 else "0",
            }
        orig = rec.get("original") or rec.get("url") or ""
        ts = rec.get("timestamp") or ""
        mime = rec.get("mimetype") or ""
        if mime_prefix and mime and not mime.lower().startswith(mime_prefix.lower()) and mime not in (
            "application/pdf",
            "application/xml",
            "text/xml",
            "application/xhtml+xml",
            "text/html",
            "application/json",
        ):
            continue
        if not orig or not ts:
            continue
        rec["wayback_url"] = f"{WAYBACK_WEB}/{ts}id_/{orig}"
        rec["source"] = "wayback"
        out.append(rec)
    return out, resume


def _wayback_cdx_page(
    url: str,
    *,
    limit: int,
    collapse: str,
    filter_status: str,
    from_date: Optional[str],
    to_date: Optional[str],
    match_type: Optional[str],
    extra_filters: Optional[list[str]],
    resume_key: Optional[str],
    mime_prefix: Optional[str],
    page_size: int,
) -> tuple[list[dict], Optional[str]]:
    items: list[tuple[str, Any]] = [
        ("url", url),
        ("output", "json"),
        ("fl", "urlkey,timestamp,original,mimetype,statuscode,digest,length"),
        ("limit", int(page_size)),
        ("showResumeKey", "true"),
    ]
    if collapse:
        items.append(("collapse", collapse))
    if from_date:
        items.append(("from", from_date))
    if to_date:
        items.append(("to", to_date))
    if match_type:
        items.append(("matchType", match_type))
    if filter_status:
        items.append(("filter", f"statuscode:{filter_status}"))
    for flt in extra_filters or []:
        items.append(("filter", flt))
    if resume_key:
        items.append(("resumeKey", resume_key))
    _sleep_wayback(1.0)
    last_err = None
    for attempt, psz in enumerate((page_size, 120, 80), 1):
        if attempt > 1:
            items = [(k, psz if k == "limit" else v) for k, v in items]
            _sleep_wayback(1.5)
        try:
            r = session().get(WAYBACK_CDX, params=items, timeout=(20, 90))
        except requests.RequestException as exc:
            last_err = exc
            log.warning("wayback cdx fail %s: %s", url, exc)
            continue
        if r.status_code in (502, 503, 504) or not r.content:
            last_err = f"http_{r.status_code}"
            log.info("wayback cdx HTTP %s for %s (page_size=%s)", r.status_code, url, psz)
            continue
        if r.status_code != 200:
            log.info("wayback cdx HTTP %s for %s", r.status_code, url)
            return [], None
        try:
            data = r.json()
        except Exception:
            return [], None
        return _parse_cdx_json(data, mime_prefix=mime_prefix)
    log.info("wayback cdx gave up %s last=%s", url, last_err)
    return [], None


def search_wayback_machine(
    url: str,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    collapse: str = "urlkey",
    filter_status: str = "200",
    match_type: Optional[str] = None,
    mime_prefix: Optional[str] = None,
    extra_filters: Optional[list[str]] = None,
) -> list[dict]:
    """CDX search with resumeKey pagination (single-shot limit>=2000 504s)."""
    target = max(1, int(limit))
    page_size = CDX_PAGE if target > CDX_PAGE else target
    out: list[dict] = []
    seen = set()
    resume: Optional[str] = None
    empty = 0
    while len(out) < target:
        need = min(page_size, target - len(out))
        batch, resume = _wayback_cdx_page(
            url,
            limit=need,
            collapse=collapse,
            filter_status=filter_status,
            from_date=from_date,
            to_date=to_date,
            match_type=match_type,
            extra_filters=extra_filters,
            resume_key=resume,
            mime_prefix=mime_prefix,
            page_size=need,
        )
        added = 0
        for rec in batch:
            key = (rec.get("original"), rec.get("timestamp"), rec.get("digest"))
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            added += 1
        if added == 0:
            empty += 1
            if empty >= 2 or not resume:
                break
        else:
            empty = 0
        if not resume:
            break
        log.info("wayback cdx %s page n=%s total=%s/%s", url, added, len(out), target)
    return out[:target]


def get_wayback_content(url: str, timestamp: Optional[str] = None) -> dict:
    """Fetch a snapshot; id_ modifier skips Wayback chrome. No CDX search."""
    if timestamp:
        wb = f"{WAYBACK_WEB}/{timestamp}id_/{url}"
    else:
        wb = f"{WAYBACK_WEB}/2id_/{url}"
    r = None
    last_err = None
    for attempt in range(1, 5):
        _sleep_wayback(1.2 if attempt == 1 else min(20.0, 2.5 * attempt))
        try:
            r = session().get(wb, timeout=(20, 90), allow_redirects=True)
        except requests.RequestException as exc:
            last_err = str(exc)
            log.info("wayback replay fail %s: %s", url, exc)
            continue
        if r.status_code in (403, 429, 503, 502, 504) and attempt < 4:
            log.info("wayback replay HTTP %s %s attempt=%s", r.status_code, url, attempt)
            continue
        break
    if r is None:
        return {"status": "error", "error": last_err or "no_response", "url": url}
    cap_ts = timestamp or ""
    m = re.search(r"/web/(\d{14})", r.url or "")
    if m:
        cap_ts = m.group(1)
    ctype = r.headers.get("content-type") or ""
    body = r.content or b""
    text = ""
    if "html" in ctype or "xml" in ctype or "text/" in ctype or not ctype:
        enc = r.encoding or "utf-8"
        try:
            text = body.decode(enc, "replace")
        except Exception:
            text = body.decode("utf-8", "replace")
    if r.status_code != 200 or not body:
        return {
            "status": "error",
            "error": f"http_{r.status_code}",
            "http_status": r.status_code,
            "wayback_url": r.url,
            "original_url": url,
        }
    if text and is_challenge(text, r.status_code):
        return {
            "status": "error",
            "error": "challenge_or_shell",
            "http_status": r.status_code,
            "wayback_url": r.url,
            "original_url": url,
            "content": text[:2000],
        }
    return {
        "status": "success",
        "content": body,
        "text": text,
        "content_type": ctype,
        "wayback_url": r.url,
        "capture_timestamp": cap_ts,
        "original_url": url,
        "http_status": r.status_code,
        "method": "wayback",
    }


# --- Common Crawl ---

def cc_indexes(n: int = 6) -> list[str]:
    global _cc_indexes
    if _cc_indexes is None:
        try:
            r = session().get(CC_COLLINFO, timeout=30)
            cols = r.json() if r.status_code == 200 else []
            ids = []
            for c in cols:
                cid = c.get("id") or ""
                cdx = c.get("cdx-api") or c.get("cdx_api") or ""
                if cid:
                    ids.append(cdx or f"https://index.commoncrawl.org/{cid}-index")
            # collinfo is newest-first. Do not drop crawls that 404 a
            # specific URL (that means "no captures", not a dead index).
            _cc_indexes = ids or [
                "https://index.commoncrawl.org/CC-MAIN-2025-18-index",
                "https://index.commoncrawl.org/CC-MAIN-2024-33-index",
            ]
        except Exception as exc:
            log.warning("cc collinfo: %s", exc)
            _cc_indexes = [
                "https://index.commoncrawl.org/CC-MAIN-2026-34-index",
                "https://index.commoncrawl.org/CC-MAIN-2026-30-index",
                "https://index.commoncrawl.org/CC-MAIN-2026-25-index",
                "https://index.commoncrawl.org/CC-MAIN-2024-33-index",
            ]
    return _cc_indexes[:n]


def search_common_crawl(url: str, *, limit: int = 80, indexes: Optional[list[str]] = None) -> list[dict]:
    """Query public CC CDX (https://index.commoncrawl.org/).

    Prefer S3 cluster.idx+CDXJ harvest (harvest_thin_s3_cc / *_cc_urls.jsonl)
    over this HTTP index — it often returns 0 hits or stalls. Short timeouts;
    never blocks on cdx_toolkit.

    Do not send filter=status:200 — on some shards that returns a false
    404 "No Captures found". Filter status client-side instead.
    HTTP 404 with that message means no hits in this crawl, not a dead index.
    """
    out = []
    seen = set()
    empty = 0
    for idx in (indexes or cc_indexes(int(os.environ.get('CC_INDEX_N', '4') or 4))):
        if idx in _cc_dead:
            continue
        params = {
            "url": url,
            "output": "json",
            "limit": str(limit),
        }
        _sleep_cc(0.3)
        try:
            r = session().get(idx, params=params, timeout=(8, 15))
        except requests.RequestException as exc:
            log.info("cc cdx %s fail %s", idx, exc)
            continue
        if r.status_code == 404:
            msg = (r.text or "")[:80]
            log.info("cc cdx no-captures %s %s", idx.split("/")[-1], msg)
            empty += 1
            if empty >= 8 and not out:
                continue
            continue
        if r.status_code in (410,):
            _cc_dead.add(idx)
            log.info("cc cdx dead HTTP %s %s", r.status_code, idx.split("/")[-1])
            continue
        if r.status_code != 200 or not r.content:
            log.info("cc cdx HTTP %s %s", r.status_code, idx.split("/")[-1])
            continue
        for line in r.text.splitlines():
            line = line.strip()
            if not line or line[0] not in "{[":
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            orig = rec.get("url") or rec.get("original") or ""
            st = str(rec.get("status") or rec.get("statuscode") or "200")
            if st and st not in ("200", "201", "206"):
                continue
            key = (orig, rec.get("filename"), rec.get("offset"))
            if not orig or key in seen:
                continue
            seen.add(key)
            rec["original"] = orig
            rec["source"] = "common_crawl"
            rec["cc_index"] = idx
            out.append(rec)
        if out:
            log.info("cc cdx %s hits=%s", idx.split("/")[-1], len(out))
        if len(out) >= limit or out:
            break
    return out[:limit]


def _parse_warc_http(raw: bytes) -> tuple[int, str, bytes]:
    data = raw
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception:
            try:
                data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
            except Exception:
                pass
    # WARC record: headers, then HTTP payload
    split = data.split(b"\r\n\r\n", 1)
    if len(split) < 2:
        return 0, "", data
    warc_headers, rest = split
    if rest.startswith(b"HTTP/") or rest.startswith(b"http/"):
        http_split = rest.split(b"\r\n\r\n", 1)
        http_head = http_split[0].decode("latin-1", "replace")
        body = http_split[1] if len(http_split) > 1 else b""
        m = re.search(r"HTTP/\d\.\d\s+(\d{3})", http_head)
        status = int(m.group(1)) if m else 0
        cm = re.search(r"Content-Type:\s*([^\r\n]+)", http_head, re.I)
        ctype = cm.group(1).strip() if cm else ""
        return status, ctype, body
    return 0, "", rest


def fetch_common_crawl_warc(rec: dict, max_bytes: int = 4_000_000) -> dict:
    """Range-GET a WARC record from data.commoncrawl.org (S3 mirror fallback).

    Retries 403/429/5xx with short backoff. Does not use index.commoncrawl.org
    or cdx_toolkit. API stable for ingest_cc_ts_wb / ingest_cc_warc_fast.
    """
    fn = rec.get("filename") or rec.get("warc_filename") or ""
    try:
        off = int(rec.get("offset") or rec.get("warc_offset") or 0)
        ln = int(rec.get("length") or rec.get("warc_length") or 0)
    except Exception:
        return {"status": "error", "error": "bad_pointer"}
    if not fn or ln <= 0:
        return {"status": "error", "error": "missing_pointer"}
    ln = min(ln, max_bytes)
    if str(fn).startswith("http"):
        candidates = [fn]
    else:
        path = fn.lstrip("/")
        candidates = [f"{h}/{path}" for h in CC_DATA_HOSTS]
    headers_base = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; legal-corpora-collector/1.0; "
            "+https://commoncrawl.org; research)"
        ),
        "Accept": "*/*",
    }
    last_err = "no_attempt"
    body_raw = b""
    used_url = ""
    for url in candidates:
        for attempt in range(3):
            _sleep_cc(0.2 if attempt == 0 else min(8.0, 1.5 * (2 ** attempt)))
            try:
                r = session().get(
                    url,
                    headers={**headers_base, "Range": f"bytes={off}-{off + ln - 1}"},
                    timeout=(12, 60),
                )
            except requests.RequestException as exc:
                last_err = str(exc)
                continue
            if r.status_code in (403, 429, 500, 502, 503):
                last_err = f"http_{r.status_code}"
                continue
            if r.status_code not in (200, 206) or not r.content:
                last_err = f"http_{r.status_code}"
                break
            body_raw = r.content
            used_url = url
            break
        if body_raw:
            break
    if not body_raw:
        return {"status": "error", "error": last_err or "empty"}
    # Prefer warcio when available; fall back to lightweight parse
    status, ctype, body = 0, "", b""
    try:
        from warcio.archiveiterator import ArchiveIterator
        for warc_rec in ArchiveIterator(io.BytesIO(body_raw)):
            if warc_rec.rec_type != "response":
                continue
            payload = warc_rec.content_stream().read()
            http_headers = warc_rec.http_headers
            if http_headers is not None:
                try:
                    status = int(http_headers.get_statuscode() or 0)
                except Exception:
                    status = 0
                ctype = http_headers.get_header("Content-Type") or ""
            body = payload
            break
        if not body:
            status, ctype, body = _parse_warc_http(body_raw)
    except Exception:
        status, ctype, body = _parse_warc_http(body_raw)
    text = ""
    if body and (
        "html" in (ctype or "")
        or "xml" in (ctype or "")
        or "text/" in (ctype or "")
        or not ctype
    ):
        text = body.decode("utf-8", "replace")
    orig = rec.get("original") or rec.get("url") or ""
    if text and is_challenge(text, status or 200):
        return {"status": "error", "error": "challenge_or_shell", "original_url": orig}
    return {
        "status": "success",
        "content": body,
        "text": text,
        "content_type": ctype,
        "original_url": orig,
        "http_status": status or 200,
        "method": "common_crawl",
        "cc_record": {
            "filename": fn,
            "offset": off,
            "length": ln,
            "timestamp": rec.get("timestamp"),
            "fetch_url": used_url,
        },
    }


# --- archive.is ---

def get_archive_is_content(url: str) -> dict:
    for base in (ARCHIVE_IS_NEWEST, ARCHIVE_PH_NEWEST):
        try:
            r = session().get(base + url, timeout=(8, 15), allow_redirects=True)
        except requests.RequestException as exc:
            log.info("archive.is %s", exc)
            continue
        if r.status_code != 200 or not r.content:
            continue
        if "archive." not in (r.url or ""):
            continue
        text = r.text or ""
        if is_challenge(text, r.status_code):
            continue
        return {
            "status": "success",
            "content": r.content,
            "text": text,
            "content_type": r.headers.get("content-type") or "text/html",
            "archive_url": r.url,
            "original_url": url,
            "http_status": r.status_code,
            "method": "archive_is",
        }
    return {"status": "error", "error": "no_archive_is_snapshot", "original_url": url}


# --- Direct HTTP last ---

def get_http(url: str) -> dict:
    try:
        r = session().get(url, timeout=(20, 60), allow_redirects=True)
    except requests.RequestException as exc:
        return {"status": "error", "error": str(exc), "original_url": url}
    text = ""
    ctype = r.headers.get("content-type") or ""
    body = r.content or b""
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype):
        text = body.decode(r.encoding or "utf-8", "replace")
    if r.status_code != 200 or not body:
        return {"status": "error", "error": f"http_{r.status_code}", "http_status": r.status_code}
    if text and is_challenge(text, r.status_code):
        return {"status": "error", "error": "challenge_or_shell", "http_status": r.status_code}
    return {
        "status": "success",
        "content": body,
        "text": text,
        "content_type": ctype,
        "original_url": url,
        "http_status": r.status_code,
        "method": "http",
        "final_url": r.url,
    }


# --- Fetch ladder (serial + parallel race) ---
# Order (2026-09-15):
#   PARALLEL_LADDER race: WARC/slice pointer + Wayback CDX/replay + archive.is newest
#   First successful non-empty body wins; losers abandoned.
#   Then (serial, only on race miss): live HTTP/bs4 → optional Playwright (allowlist).
# Cloudflare Browser Rendering / IPWB only when creds/local usable (skipped otherwise).

_last_archive_is = 0.0
_archive_is_submit_count = 0
_ARCHIVE_IS_SUBMIT_CAP = int(os.environ.get("ARCHIVE_IS_SUBMIT_CAP", "3") or 3)

# Default Playwright allowlist: known JS-heavy Easy/Hard gazette portals
_DEFAULT_PLAYWRIGHT_HOSTS = (
    "gacetaoficialdebolivia.gob.bo",
    "eqanun.az",
    "e-qanun.az",
    "iort.gov.tn",
    "dotic.ir",
    "paragraf.rs",
    "pravno-informacioni-sistem.rs",
)


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) in ("1", "true", "True", "yes", "YES", "on", "ON")


def _sleep_archive_is(delay: float = 2.0) -> None:
    global _last_archive_is
    now = time.time()
    wait = delay - (now - _last_archive_is)
    if wait > 0:
        time.sleep(wait)
    _last_archive_is = time.time()


def has_cloudflare_creds() -> bool:
    """Cloudflare Browser Rendering only when API key present."""
    tok = (
        os.environ.get("CLOUDFLARE_API_TOKEN")
        or os.environ.get("CF_API_TOKEN")
        or os.environ.get("CLOUDFLARE_BROWSER_RENDERING_TOKEN")
        or ""
    ).strip()
    acct = (
        os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        or os.environ.get("CF_ACCOUNT_ID")
        or ""
    ).strip()
    return bool(tok and acct)


def has_ipwb_local() -> bool:
    """IPWB only if local package already usable — never install/start from tip."""
    if not _env_truthy("TRY_IPWB", "0"):
        return False
    try:
        import ipwb  # noqa: F401
        return True
    except Exception:
        return False


def playwright_host_ok(url: str) -> bool:
    raw = (os.environ.get("PLAYWRIGHT_HOSTS") or "").strip()
    hosts = [h.strip().lower() for h in raw.split(",") if h.strip()] if raw else list(_DEFAULT_PLAYWRIGHT_HOSTS)
    try:
        host = (urlparse(url).hostname or "").lower().lstrip(".")
    except Exception:
        return False
    if not host:
        return False
    for h in hosts:
        if host == h or host.endswith("." + h):
            return True
    return False


def _body_nonempty(res: Optional[dict], min_text: int = 0) -> bool:
    if not res or res.get("status") != "success":
        return False
    text = res.get("text") or ""
    content = res.get("content") or b""
    if isinstance(content, (bytes, bytearray)) and len(content) >= 64:
        if content[:4] == b"%PDF" or b"%PDF" in content[:8192]:
            return True
        if len(text) >= max(min_text, 1) or len(content) >= max(min_text, 256):
            return True
    if len(text) >= max(min_text, 1):
        return True
    return False


def get_wayback_cdx_then_replay(url: str, timestamp: Optional[str] = None, min_text: int = 0) -> dict:
    """Wayback: use given ts, else CDX newest then id_ replay. Honors global Wayback delay."""
    ts = timestamp
    if not ts and not _env_truthy("SKIP_WAYBACK_CDX", "0"):
        try:
            hits = search_wayback_machine(url, limit=3, collapse="digest")
            if hits:
                ts = hits[0].get("timestamp") or None
        except Exception as exc:
            log.info("wayback cdx search fail %s: %s", url[:80], exc)
    res = get_wayback_content(url, timestamp=ts)
    if _body_nonempty(res, min_text=min_text):
        res["method"] = "wayback_cdx_replay" if ts and not timestamp else (res.get("method") or "wayback")
        if ts:
            res["capture_timestamp"] = res.get("capture_timestamp") or ts
        return res
    return res if res else {"status": "error", "error": "wayback_empty", "original_url": url}


def submit_archive_is(url: str, *, wait: bool = False, timeout: int = 45) -> dict:
    """Sparse archive.is submit (rate-limited + session cap). Prefer newest lookup first."""
    global _archive_is_submit_count
    if _archive_is_submit_count >= _ARCHIVE_IS_SUBMIT_CAP:
        return {"status": "error", "error": "archive_is_submit_cap", "original_url": url}
    if not _env_truthy("ARCHIVE_IS_SUBMIT_ON_MISS", "0"):
        return {"status": "error", "error": "archive_is_submit_disabled", "original_url": url}
    _sleep_archive_is(float(os.environ.get("ARCHIVE_IS_SUBMIT_DELAY", "5") or 5))
    _archive_is_submit_count += 1
    try:
        r = session().post(
            "https://archive.is/submit/",
            data={"url": url, "anyway": "1"},
            timeout=(10, timeout),
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {"status": "error", "error": f"archive_is_submit:{exc}", "original_url": url}
    if "archive." in (r.url or "") and r.url and "submit" not in (r.url or ""):
        text = r.text or ""
        if not is_challenge(text, r.status_code):
            return {
                "status": "success",
                "content": r.content or b"",
                "text": text,
                "content_type": r.headers.get("content-type") or "text/html",
                "archive_url": r.url,
                "original_url": url,
                "method": "archive_is_submit",
                "http_status": r.status_code,
            }
    # Non-blocking: return pending; caller may re-hit newest later
    if not wait:
        return {"status": "error", "error": "archive_is_submit_pending", "original_url": url, "http_status": r.status_code}
    time.sleep(3)
    return get_archive_is_content(url)


def get_archive_is_content_ladder(url: str, *, submit_on_miss: Optional[bool] = None) -> dict:
    """archive.is newest (+ optional sparse submit). Always rate-limited."""
    _sleep_archive_is(float(os.environ.get("ARCHIVE_IS_DELAY", "2") or 2))
    res = get_archive_is_content(url)
    if _body_nonempty(res):
        return res
    do_submit = (
        submit_on_miss
        if submit_on_miss is not None
        else _env_truthy("ARCHIVE_IS_SUBMIT_ON_MISS", "0")
    )
    if do_submit:
        sub = submit_archive_is(url, wait=_env_truthy("ARCHIVE_IS_SUBMIT_WAIT", "0"))
        if _body_nonempty(sub):
            return sub
        # One more newest lookup after submit
        _sleep_archive_is(2.0)
        res2 = get_archive_is_content(url)
        if _body_nonempty(res2):
            res2["method"] = "archive_is_after_submit"
            return res2
        return sub if sub.get("error") else res
    return res


def get_http_bs4(url: str) -> dict:
    """Live HTTP with BeautifulSoup text extraction when available."""
    res = get_http(url)
    if res.get("status") != "success":
        return res
    text = res.get("text") or ""
    ctype = (res.get("content_type") or "").lower()
    if "html" in ctype or (text[:200].lstrip().startswith("<")):
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            extracted = " ".join(soup.get_text(" ", strip=True).split())
            if len(extracted) > len(text) * 0.05 and len(extracted) >= 80:
                res = dict(res)
                res["text"] = extracted
                res["method"] = "http_bs4"
        except Exception as exc:
            log.info("bs4 extract skip %s: %s", url[:60], exc)
    return res


def get_playwright_content(url: str, *, timeout_ms: int = 45000) -> dict:
    """Optional Playwright for allowlisted JS portals. Skip if package/browser missing."""
    if not playwright_host_ok(url):
        return {"status": "error", "error": "playwright_host_not_allowlisted", "original_url": url}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"status": "error", "error": f"playwright_unavailable:{exc}", "original_url": url}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                page.wait_for_timeout(1500)
                html = page.content() or ""
                content = html.encode("utf-8", "replace")
            finally:
                browser.close()
    except Exception as exc:
        return {"status": "error", "error": f"playwright:{exc}", "original_url": url}
    if not html or is_challenge(html, 200):
        return {"status": "error", "error": "playwright_challenge_or_empty", "original_url": url}
    text = html
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
    except Exception:
        pass
    return {
        "status": "success",
        "content": content,
        "text": text,
        "content_type": "text/html",
        "original_url": url,
        "method": "playwright",
        "http_status": 200,
    }


def _race_fetch_one(name: str, fn, winner_event: "threading.Event") -> tuple[str, dict]:
    if winner_event.is_set():
        return name, {"status": "error", "error": "abandoned_after_winner"}
    try:
        res = fn()
    except Exception as exc:
        return name, {"status": "error", "error": f"{name}:{exc}"}
    return name, res if isinstance(res, dict) else {"status": "error", "error": f"{name}:bad_result"}


def parse_parallel_ladder_sources() -> list[str]:
    """Parse PARALLEL_LADDER env into ordered source names.

    PARALLEL_LADDER=1 / true / all → full five-way race.
    PARALLEL_LADDER=0 / false / serial → empty (caller uses serial path).
    PARALLEL_LADDER=warc,wayback,archive_is,live,playwright → explicit set.
    """
    raw = (os.environ.get("PARALLEL_LADDER", "1") or "1").strip()
    low = raw.lower()
    if low in ("0", "false", "no", "off", "serial"):
        return []
    all5 = ["warc", "wayback", "archive_is", "live", "playwright"]
    if low in ("1", "true", "yes", "on", "all", "full"):
        return all5
    parts = [x.strip().lower().replace("-", "_") for x in raw.split(",") if x.strip()]
    alias = {
        "ais": "archive_is",
        "archiveis": "archive_is",
        "ia": "wayback",
        "wb": "wayback",
        "http": "live",
        "http_live": "live",
        "bs4": "live",
        "pw": "playwright",
        "cc": "warc",
        "common_crawl": "warc",
    }
    out: list[str] = []
    for p in parts:
        name = alias.get(p, p)
        if name in all5 and name not in out:
            out.append(name)
    return out or all5


_playwright_jobs_this_process = 0
_playwright_lock = None


def _get_playwright_lock():
    global _playwright_lock
    if _playwright_lock is None:
        import threading
        _playwright_lock = threading.Lock()
    return _playwright_lock


def _mem_avail_gi() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return 99.0


def _playwright_soft_ok() -> bool:
    """≤1 Playwright per country job (process); box ≤2 via PLAYWRIGHT_BOX_MAX; Mem≥6Gi."""
    global _playwright_jobs_this_process
    if _mem_avail_gi() < float(os.environ.get("PLAYWRIGHT_MIN_MEM_GI", "6") or 6):
        return False
    per_job = int(os.environ.get("PLAYWRIGHT_PER_JOB", "1") or 1)
    if _playwright_jobs_this_process >= per_job:
        return False
    # Soft box-wide cap via lockfile count (best-effort, no kill)
    box_max = int(os.environ.get("PLAYWRIGHT_BOX_MAX", "2") or 2)
    lock_dir = os.environ.get("PLAYWRIGHT_LOCK_DIR", "/tmp/legal_scrapers_pw_locks")
    try:
        os.makedirs(lock_dir, exist_ok=True)
        active = 0
        for entry in os.listdir(lock_dir):
            if not entry.endswith(".pw"):
                continue
            path = os.path.join(lock_dir, entry)
            try:
                pid = int(entry.split("_", 1)[0])
                os.kill(pid, 0)
                active += 1
            except ProcessLookupError:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            except (ValueError, PermissionError, OSError):
                active += 1  # fail closed for unknown/foreign lock
        if active >= box_max:
            return False
    except Exception:
        pass
    return True


def _playwright_acquire_slot() -> Optional[str]:
    """Create a lockfile slot; return path or None."""
    global _playwright_jobs_this_process
    if not _playwright_soft_ok():
        return None
    with _get_playwright_lock():
        if not _playwright_soft_ok():
            return None
        lock_dir = os.environ.get("PLAYWRIGHT_LOCK_DIR", "/tmp/legal_scrapers_pw_locks")
        os.makedirs(lock_dir, exist_ok=True)
        path = os.path.join(lock_dir, f"{os.getpid()}_{int(time.time() * 1000)}.pw")
        try:
            with open(path, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            return None
        _playwright_jobs_this_process += 1
        return path


def _playwright_release_slot(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except Exception:
        pass


def fetch_ladder_parallel_race(
    url: str,
    *,
    cc_record: Optional[dict] = None,
    wayback_ts: Optional[str] = None,
    min_text: int = 150,
    sources: Optional[list[str]] = None,
    try_cc: bool = True,
    try_wayback: bool = True,
    try_archive_is: bool = True,
    try_http: bool = True,
    try_playwright: bool = True,
) -> dict:
    """Five-way race: WARC ∥ Wayback ∥ archive.is ∥ live ∥ Playwright.

    First successful non-empty body wins; losers abandoned (cancel futures best-effort).
    Soft caps: ≤1 Playwright/job, box ≤2, skip PW if MemAvail<6Gi.
    archive.is submit_on_miss stays sparse (newest lookup races; submit not in race).
    Shared global Wayback delay via get_wayback_*.
    """
    import concurrent.futures
    import threading

    errors: list[str] = []
    winner_event = threading.Event()
    srcs = sources if sources is not None else parse_parallel_ladder_sources()
    if not srcs:
        return {"status": "error", "error": "no_parallel_sources", "original_url": url, "ladder": "parallel_race"}

    def _warc_job() -> dict:
        if winner_event.is_set():
            return {"status": "error", "error": "abandoned_after_winner"}
        recs: list[dict] = []
        if cc_record and (cc_record.get("filename") or cc_record.get("warc_filename")):
            recs = [cc_record]
        elif try_cc and _env_truthy("LADDER_CC_SEARCH", "0"):
            try:
                recs = search_common_crawl(url, limit=2)
            except Exception as exc:
                return {"status": "error", "error": f"common_crawl_search:{exc}"}
        if not recs:
            return {"status": "error", "error": "no_warc_pointer"}
        last = {"status": "error", "error": "warc_miss"}
        for rec in recs:
            if winner_event.is_set():
                return {"status": "error", "error": "abandoned_after_winner"}
            last = fetch_common_crawl_warc(rec)
            if _body_nonempty(last, min_text=0):
                last = dict(last)
                last["method"] = last.get("method") or "common_crawl_warc"
                return last
        return last

    def _wb_job() -> dict:
        if winner_event.is_set():
            return {"status": "error", "error": "abandoned_after_winner"}
        return get_wayback_cdx_then_replay(url, timestamp=wayback_ts, min_text=0)

    def _ais_job() -> dict:
        if winner_event.is_set():
            return {"status": "error", "error": "abandoned_after_winner"}
        # Newest lookup only in race; submit_on_miss stays sparse / out-of-race
        return get_archive_is_content_ladder(url, submit_on_miss=False)

    def _live_job() -> dict:
        if winner_event.is_set():
            return {"status": "error", "error": "abandoned_after_winner"}
        res = get_http_bs4(url)
        if res.get("status") == "success":
            raw = res.get("text") or ""
            if is_challenge(raw, res.get("http_status") or 200) or is_spa_shell(raw, raw):
                return {"status": "error", "error": "live_challenge_or_spa", "original_url": url}
        return res

    def _pw_job() -> dict:
        if winner_event.is_set():
            return {"status": "error", "error": "abandoned_after_winner"}
        if not playwright_host_ok(url):
            return {"status": "error", "error": "playwright_host_not_allowlisted", "original_url": url}
        slot = _playwright_acquire_slot()
        if not slot:
            return {"status": "error", "error": "playwright_soft_cap", "original_url": url}
        try:
            if winner_event.is_set():
                return {"status": "error", "error": "abandoned_after_winner"}
            return get_playwright_content(url)
        finally:
            _playwright_release_slot(slot)

    tasks: list[tuple[str, Any]] = []
    if "warc" in srcs and (try_cc or (cc_record and (cc_record.get("filename") or cc_record.get("warc_filename")))):
        tasks.append(("warc", _warc_job))
    if "wayback" in srcs and try_wayback and not _env_truthy("SKIP_WAYBACK", "0"):
        tasks.append(("wayback", _wb_job))
    if "archive_is" in srcs and try_archive_is and _env_truthy("TRY_ARCHIVE_IS", "1"):
        tasks.append(("archive_is", _ais_job))
    if "live" in srcs and try_http:
        tasks.append(("live", _live_job))
    # Playwright: include in race when listed; TRY_PLAYWRIGHT default 1 if listed in PARALLEL_LADDER
    pw_wanted = "playwright" in srcs and (
        try_playwright or _env_truthy("TRY_PLAYWRIGHT", "1" if "playwright" in srcs else "0")
    )
    if pw_wanted:
        tasks.append(("playwright", _pw_job))

    if not tasks:
        return {"status": "error", "error": "no_race_tasks", "original_url": url, "ladder": "parallel_race", "sources": srcs}

    winner: Optional[dict] = None
    max_workers = min(5, len(tasks))
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ladder")
    futs = {ex.submit(_race_fetch_one, name, fn, winner_event): name for name, fn in tasks}
    try:
        for fut in concurrent.futures.as_completed(
            futs, timeout=float(os.environ.get("LADDER_RACE_TIMEOUT", "90") or 90)
        ):
            name = futs[fut]
            try:
                _n, res = fut.result()
            except Exception as exc:
                errors.append(f"{name}:{exc}")
                continue
            if _body_nonempty(res, min_text=0):
                winner_event.set()
                winner = dict(res)
                winner["ladder"] = "parallel_race"
                winner["ladder_winner"] = name
                winner["ladder_sources"] = srcs
                winner["method"] = winner.get("method") or name
                for other in futs:
                    if other is not fut and not other.done():
                        other.cancel()
                break
            errors.append(f"{name}:{res.get('error') or 'empty'}")
    except concurrent.futures.TimeoutError:
        errors.append("race_timeout")
        winner_event.set()
        for other in futs:
            if not other.done():
                other.cancel()
    finally:
        # Critical: do not wait for in-flight losers. They see winner_event where possible;
        # already-blocked HTTP calls are abandoned and finish in background.
        ex.shutdown(wait=False, cancel_futures=True)

    if winner and _body_nonempty(winner, min_text=min_text if min_text else 0):
        winner["ladder_errors"] = errors
        return winner
    if winner and _body_nonempty(winner, min_text=0):
        winner["ladder_errors"] = errors
        winner["warning"] = "below_min_text"
        return winner
    return {
        "status": "error",
        "error": "; ".join(errors) or "parallel_race_miss",
        "original_url": url,
        "ladder": "parallel_race",
        "ladder_sources": srcs,
        "ladder_errors": errors,
    }



def fetch_ladder(
    url: str,
    *,
    cc_record: Optional[dict] = None,
    wayback_ts: Optional[str] = None,
    min_text: int = 150,
    try_cc: Optional[bool] = None,
    try_wayback: Optional[bool] = None,
    try_archive_is: Optional[bool] = None,
    try_http: Optional[bool] = None,
    try_playwright: Optional[bool] = None,
    parallel: Optional[bool] = None,
    sources: Optional[list[str]] = None,
) -> dict:
    """Unified fetch ladder for tip climb.

    PARALLEL_LADDER default = warc,wayback,archive_is,live,playwright (five-way race).
    First good body wins. Soft-cap Playwright; sparse archive.is submit (newest races).
    PARALLEL_LADDER=0 → serial: WARC → Wayback → archive.is → live → Playwright.
    Skips: Cloudflare unless creds; IPWB unless local+TRY_IPWB; Brave without key.
    """
    if try_cc is None:
        try_cc = True
    if try_wayback is None:
        try_wayback = not _env_truthy("SKIP_WAYBACK", "0")
    if try_archive_is is None:
        try_archive_is = _env_truthy("TRY_ARCHIVE_IS", "1")
    srcs = sources if sources is not None else parse_parallel_ladder_sources()
    if try_http is None:
        # Listing live in PARALLEL_LADDER opts into live race even if SKIP_LIVE=1
        if "live" in srcs:
            try_http = not _env_truthy("LADDER_SKIP_LIVE", "0")
        else:
            try_http = not _env_truthy("SKIP_LIVE", "0")
    if try_playwright is None:
        # If playwright listed in PARALLEL_LADDER, default on unless TRY_PLAYWRIGHT=0
        if "playwright" in srcs:
            try_playwright = _env_truthy("TRY_PLAYWRIGHT", "1")
        else:
            try_playwright = _env_truthy("TRY_PLAYWRIGHT", "0")
    if parallel is None:
        parallel = bool(srcs)

    errors: list[str] = []
    steps: list[str] = []

    if parallel and srcs:
        steps.append("parallel_race:" + ",".join(srcs))
        res = fetch_ladder_parallel_race(
            url,
            cc_record=cc_record,
            wayback_ts=wayback_ts,
            min_text=min_text,
            sources=srcs,
            try_cc=try_cc,
            try_wayback=try_wayback,
            try_archive_is=try_archive_is,
            try_http=try_http,
            try_playwright=try_playwright,
        )
        if _body_nonempty(res, min_text=0):
            res = dict(res)
            res["ladder_steps"] = steps
            return res
        errors.append(f"race:{res.get('error')}")
        # Sparse submit only after race miss (not inside race)
        if try_archive_is and _env_truthy("ARCHIVE_IS_SUBMIT_ON_MISS", "0"):
            steps.append("archive_is_submit")
            sub = submit_archive_is(url, wait=_env_truthy("ARCHIVE_IS_SUBMIT_WAIT", "0"))
            if _body_nonempty(sub, min_text=0):
                sub = dict(sub)
                sub["ladder"] = "after_race_submit"
                sub["ladder_steps"] = steps
                return sub
            errors.append(f"archive_is_submit:{sub.get('error')}")
    else:
        # Serial fallback
        if try_cc or (cc_record and (cc_record.get("filename") or cc_record.get("warc_filename"))):
            steps.append("warc")
            cc_recs: list[dict] = []
            if cc_record and (cc_record.get("filename") or cc_record.get("warc_filename")):
                cc_recs = [cc_record]
            elif try_cc and _env_truthy("LADDER_CC_SEARCH", "0"):
                try:
                    cc_recs = search_common_crawl(url, limit=4)
                except Exception as exc:
                    errors.append(f"common_crawl:{exc}")
            for rec in cc_recs:
                res = fetch_common_crawl_warc(rec)
                if _body_nonempty(res, min_text=0):
                    res = dict(res)
                    res["method"] = res.get("method") or "common_crawl_warc"
                    res["ladder"] = "serial"
                    res["ladder_steps"] = steps
                    return res
                errors.append(f"common_crawl:{res.get('error')}")
        if try_wayback:
            steps.append("wayback")
            res = get_wayback_cdx_then_replay(url, timestamp=wayback_ts, min_text=0)
            if _body_nonempty(res, min_text=0):
                res = dict(res)
                res["ladder"] = "serial"
                res["ladder_steps"] = steps
                return res
            errors.append(f"wayback:{res.get('error')}")
        if try_archive_is:
            steps.append("archive_is")
            res = get_archive_is_content_ladder(url)
            if _body_nonempty(res, min_text=0):
                res = dict(res)
                res["ladder"] = "serial"
                res["ladder_steps"] = steps
                return res
            errors.append(f"archive_is:{res.get('error')}")
        if try_http:
            steps.append("live_http")
            res = get_http_bs4(url)
            if _body_nonempty(res, min_text=0):
                raw = res.get("text") or ""
                if not is_challenge(raw, res.get("http_status") or 200):
                    res = dict(res)
                    res["ladder"] = "serial"
                    res["ladder_steps"] = steps
                    return res
            errors.append(f"http:{res.get('error') or 'empty'}")
        if try_playwright and playwright_host_ok(url):
            steps.append("playwright")
            if _playwright_soft_ok():
                slot = _playwright_acquire_slot()
                try:
                    res = get_playwright_content(url)
                finally:
                    _playwright_release_slot(slot)
                if _body_nonempty(res, min_text=0):
                    res = dict(res)
                    res["ladder"] = "serial"
                    res["ladder_steps"] = steps
                    return res
                errors.append(f"playwright:{res.get('error')}")
            else:
                errors.append("playwright:soft_cap")

    if has_cloudflare_creds() and _env_truthy("TRY_CLOUDFLARE", "0"):
        errors.append("cloudflare:no_sync_tip_impl")
    if has_ipwb_local():
        errors.append("ipwb:not_wired_in_tip_ladder")

    return {
        "status": "error",
        "error": "; ".join(errors) or "ladder_all_failed",
        "original_url": url,
        "ladder": "parallel" if (parallel and srcs) else "serial",
        "ladder_steps": steps,
        "ladder_errors": errors,
    }



def fetch_with_fallbacks(
    url: str,
    *,
    cc_record: Optional[dict] = None,
    wayback_ts: Optional[str] = None,
    try_archive_is: bool = False,
    try_http: bool = True,
    try_cc: bool = True,
) -> dict:
    """Back-compat wrapper → fetch_ladder.

    Historical default was serial WARC→Wayback→(optional archive.is)→HTTP.
    When PARALLEL_LADDER=1 (default for new tip paths), races archive sources first.
    Pass try_archive_is=True or set TRY_ARCHIVE_IS=1 to include archive.is.
    """
    # Preserve prior call-site semantics for try_archive_is default False unless env set
    ais = try_archive_is or _env_truthy("TRY_ARCHIVE_IS", "0")
    return fetch_ladder(
        url,
        cc_record=cc_record,
        wayback_ts=wayback_ts,
        try_cc=try_cc,
        try_archive_is=ais,
        try_http=try_http,
        # Back-compat callers stay serial unless env explicitly opts into race.
        parallel=bool(parse_parallel_ladder_sources()) if "PARALLEL_LADDER" in os.environ else False,
    )
