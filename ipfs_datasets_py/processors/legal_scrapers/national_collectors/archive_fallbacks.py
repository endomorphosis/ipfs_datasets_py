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

WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_WEB = "https://web.archive.org/web"
CC_COLLINFO = "https://index.commoncrawl.org/collinfo.json"
CC_DATA = "https://data.commoncrawl.org"
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

    Do not send filter=status:200 — on some shards that returns a false
    404 "No Captures found". Filter status client-side instead.
    HTTP 404 with that message means no hits in this crawl, not a dead index.
    """
    out = []
    seen = set()
    empty = 0
    for idx in (indexes or cc_indexes(12)):
        if idx in _cc_dead:
            continue
        params = {
            "url": url,
            "output": "json",
            "limit": str(limit),
        }
        _sleep_cc(0.3)
        try:
            r = session().get(idx, params=params, timeout=(12, 25))
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
    fn = rec.get("filename") or rec.get("warc_filename") or ""
    try:
        off = int(rec.get("offset") or rec.get("warc_offset") or 0)
        ln = int(rec.get("length") or rec.get("warc_length") or 0)
    except Exception:
        return {"status": "error", "error": "bad_pointer"}
    if not fn or ln <= 0:
        return {"status": "error", "error": "missing_pointer"}
    ln = min(ln, max_bytes)
    url = fn if str(fn).startswith("http") else f"{CC_DATA}/{fn.lstrip('/')}"
    _sleep_cc(0.25)
    try:
        r = session().get(
            url,
            headers={"Range": f"bytes={off}-{off + ln - 1}"},
            timeout=(20, 90),
        )
    except requests.RequestException as exc:
        return {"status": "error", "error": str(exc)}
    if r.status_code not in (200, 206) or not r.content:
        return {"status": "error", "error": f"http_{r.status_code}"}
    status, ctype, body = _parse_warc_http(r.content)
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


def fetch_with_fallbacks(
    url: str,
    *,
    cc_record: Optional[dict] = None,
    wayback_ts: Optional[str] = None,
    try_archive_is: bool = False,
    try_http: bool = True,
    try_cc: bool = True,
) -> dict:
    """Prefer archives: CC WARC -> Wayback replay -> archive.is -> direct HTTP.

    Brave Search skipped (no API key in this environment).
    Playwright is attempted by the caller when this returns a SPA shell.
    Does not run Wayback CDX search; Wayback is replay only.
    """
    errors = []
    cc_recs: list[dict] = []
    if cc_record and (cc_record.get("filename") or cc_record.get("warc_filename")):
        cc_recs = [cc_record]
    elif try_cc:
        try:
            cc_recs = search_common_crawl(url, limit=4)
        except Exception as exc:
            errors.append(f"common_crawl:{exc}")
            cc_recs = []
    for rec in cc_recs:
        res = fetch_common_crawl_warc(rec)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            return res
        errors.append(f"common_crawl:{res.get('error')}")
    if wayback_ts or url:
        res = get_wayback_content(url, timestamp=wayback_ts)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            return res
        errors.append(f"wayback:{res.get('error')}")
    if try_archive_is:
        res = get_archive_is_content(url)
        if res.get("status") == "success":
            return res
        errors.append(f"archive_is:{res.get('error')}")
    if try_http:
        res = get_http(url)
        if res.get("status") == "success":
            return res
        errors.append(f"http:{res.get('error')}")
    return {"status": "error", "error": "; ".join(errors) or "all_failed", "original_url": url}
