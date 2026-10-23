#!/usr/bin/env python3
"""Shared helpers for new-country official gazette collectors."""
from __future__ import annotations

import logging
import os
import re
import time
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ROOT,
    DEFAULT_UA,
    base_record,
    ensure_dirs,
    existing_ids,
    html_to_text,
    http_get,
    iso_date,
    log_failure,
    slug_id,
    split_articles,
    utcnow,
    write_instrument,
    write_summary,
)
import archive_fallbacks as af

log = logging.getLogger("world_lib")

MIN_TEXT = 80
MAX_PDF = 35 * 1024 * 1024


def setup_log(cc: str, name: str | None = None) -> None:
    ensure_dirs(cc)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / cc / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def pdf_to_text(raw: bytes) -> str:
    """Extract text via pdftotext. Tries qpdf --decrypt first for copy-restricted
    digital PDFs (still not OCR — image-only scans stay empty)."""
    if not raw:
        return ""
    if raw[:4] != b"%PDF":
        idx = raw.find(b"%PDF")
        if idx < 0 or idx > 8192:
            return ""
        raw = raw[idx:]
    try:
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            src = dpath / "in.pdf"
            src.write_bytes(raw)
            candidates = [src]
            dec = dpath / "dec.pdf"
            try:
                q = subprocess.run(
                    ["qpdf", "--decrypt", str(src), str(dec)],
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
                if q.returncode == 0 and dec.exists() and dec.stat().st_size > 1000:
                    candidates.insert(0, dec)
            except Exception:
                pass
            best = ""
            for cand in candidates:
                for args in (
                    ["pdftotext", "-layout", "-enc", "UTF-8", str(cand), "-"],
                    ["pdftotext", "-raw", "-enc", "UTF-8", str(cand), "-"],
                ):
                    proc = subprocess.run(
                        args, check=False, capture_output=True, timeout=180
                    )
                    if proc.returncode == 0 and proc.stdout:
                        text = proc.stdout.decode("utf-8", "replace").strip()
                        # Ignore form-feed-only / tiny junk from image-only pages
                        if len(text) > len(best):
                            best = text
                if len(best) >= 150:
                    break
            return best
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def split_custom(text: str, law_id: str, source_url: str, date: Optional[str], pattern: Optional[re.Pattern]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if not pattern:
        return docs
    # Normalize bidi + eastern digits so Arabic/Persian article markers match
    try:
        from pdf_extract_lib import normalize_rtl_text
        work = normalize_rtl_text(text or "")
    except Exception:
        work = text or ""
    matches = list(pattern.finditer(work))
    if len(matches) < 2:
        return docs if len(docs) >= 2 else []
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(work)
        chunk = work[start:end].strip()
        if len(chunk) < 20:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-zA-Z0-9\u0400-\u04FF\u0530-\u058F\u0600-\u06FF-]+", "-", num.lower()).strip("-")[:80]
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else docs


def live_get(url: str, *, ua: str = DEFAULT_UA, timeout: tuple = (12, 25), verify: bool = True, retries: int = 2):
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    last = None
    headers = {"User-Agent": ua, "Accept": "application/pdf, text/html, application/xml, */*"}
    for attempt in range(1, retries + 1):
        try:
            time.sleep(0.2)
            resp = requests.get(url, timeout=timeout, headers=headers, verify=verify, allow_redirects=True)
            return resp
        except Exception as exc:
            last = exc
            if verify and ("SSL" in type(exc).__name__ or "SSL" in str(exc)):
                try:
                    resp = requests.get(url, timeout=timeout, headers=headers, verify=False, allow_redirects=True)
                    return resp
                except Exception as exc2:
                    last = exc2
            time.sleep(min(8, 1.5 * attempt))
    raise RuntimeError(f"live_get failed {url}: {last}")


def fetch_official(
    url: str,
    *,
    ua: str = DEFAULT_UA,
    verify: bool = True,
    wayback: bool = True,
    wayback_ts: Optional[str] = None,
    min_text: int = MIN_TEXT,
) -> dict:
    """Live official URL first; Wayback of the same official URL on failure. No WAF bypass."""
    out = {
        "status": "error",
        "text": "",
        "content": b"",
        "source_url": url,
        "method": "",
        "content_type": "",
        "error": "",
    }
    body = b""
    ctype = ""
    skip_live = os.environ.get("SKIP_LIVE", "0") not in ("0", "false", "False", "")
    try:
        if skip_live:
            raise RuntimeError("skip_live")
        r = live_get(url, ua=ua, verify=verify)
        body = r.content or b""
        ctype = r.headers.get("content-type") or ""
        if r.status_code == 200 and body:
            is_pdf = (
                body[:4] == b"%PDF"
                or (0 <= body.find(b"%PDF") <= 64)
                or "pdf" in ctype.lower()
            )
            if is_pdf:
                text = pdf_to_text(body)
                if len(text) >= min_text:
                    out.update(status="success", text=text, content=body, method="http_pdf", content_type=ctype)
                    return out
            text = ""
            if "html" in ctype.lower() or "xml" in ctype.lower() or "json" in ctype.lower() or body[:1] in (b"<", b"{", b"["):
                raw = body.decode(r.encoding or "utf-8", "replace")
                if af.is_challenge(raw, r.status_code):
                    out["error"] = "challenge_or_shell"
                else:
                    text = html_to_text(raw) if "<" in raw[:500] else raw
                    if len(text) >= min_text and not af.is_spa_shell(raw, text):
                        out.update(status="success", text=text, content=body, method="http_html", content_type=ctype)
                        return out
                    if len(text) < min_text:
                        out["error"] = "short_or_spa"
            elif body[:4] == b"%PDF" or (0 <= body.find(b"%PDF") <= 64):
                # Keep bytes so callers (OCR) can work without a second download
                pdf_body = body if body[:4] == b"%PDF" else body[body.find(b"%PDF"):]
                out["error"] = "pdf_extract_failed"
                out["content"] = pdf_body
                out["content_type"] = ctype or "application/pdf"
            elif len(body) > min_text:
                try:
                    text = body.decode("utf-8", "replace")
                    if text.lstrip().startswith("%PDF") or "endobj" in text[:200]:
                        out["error"] = "raw_pdf_bytes"
                    elif len(text) >= min_text:
                        out.update(status="success", text=text, content=body, method="http_text", content_type=ctype)
                        return out
                except Exception:
                    pass
        else:
            out["error"] = f"http_{getattr(r, 'status_code', '?')}"
    except Exception as exc:
        out["error"] = f"live:{exc}"

    if wayback:
        try:
            w = af.get_wayback_content(url, timestamp=wayback_ts)
            if w.get("status") == "success":
                raw_b = w.get("content") or b""
                raw_t = w.get("text") or ""
                pdf_bytes = b""
                if isinstance(raw_b, (bytes, bytearray)) and raw_b:
                    if raw_b[:4] == b"%PDF":
                        pdf_bytes = bytes(raw_b)
                    else:
                        _idx = raw_b.find(b"%PDF", 0, 8192)
                        if _idx >= 0:
                            pdf_bytes = bytes(raw_b[_idx:])
                if not pdf_bytes and raw_t:
                    enc = raw_t.encode("latin-1", "replace")
                    if enc[:4] == b"%PDF":
                        pdf_bytes = enc
                    else:
                        _idx = enc.find(b"%PDF", 0, 8192)
                        if _idx >= 0:
                            pdf_bytes = enc[_idx:]
                if pdf_bytes or (isinstance(raw_b, bytes) and (w.get("content_type") or "").lower().find("pdf") >= 0):
                    if not pdf_bytes and isinstance(raw_b, bytes):
                        pdf_bytes = raw_b
                    text = pdf_to_text(pdf_bytes)
                    if len(text) >= min_text and not text.lstrip().startswith("%PDF"):
                        out.update(
                            status="success",
                            text=text,
                            content=pdf_bytes,
                            method="wayback_pdf",
                            source_url=w.get("wayback_url") or w.get("url") or url,
                            content_type="application/pdf",
                        )
                        return out
                    # Keep PDF bytes so callers (OCR) can work without a second download
                    out["error"] = (out.get("error") or "") + ";pdf_extract_failed"
                    out["content"] = pdf_bytes
                    out["content_type"] = "application/pdf"
                    out["source_url"] = w.get("wayback_url") or w.get("url") or url
                    return out
                if not raw_t and isinstance(raw_b, bytes):
                    raw_t = raw_b.decode("utf-8", "replace")
                if raw_t.lstrip().startswith("%PDF") or "endobj" in raw_t[:400] or "startxref" in raw_t[:800]:
                    out["error"] = (out.get("error") or "") + ";raw_pdf_bytes"
                    return out
                text = html_to_text(raw_t) if "<" in (raw_t[:400] or "") else raw_t
                if len(text) >= min_text and not af.is_challenge(raw_t, 200):
                    out.update(
                        status="success",
                        text=text,
                        content=raw_b if isinstance(raw_b, bytes) else raw_t.encode("utf-8", "replace"),
                        method="wayback_html",
                        source_url=w.get("url") or url,
                        content_type=w.get("content_type") or "text/html",
                    )
                    return out
                out["error"] = (out.get("error") or "") + ";wayback_short"
            else:
                out["error"] = (out.get("error") or "") + f";wayback:{w.get('error')}"
        except Exception as exc:
            out["error"] = (out.get("error") or "") + f";wayback:{exc}"
    return out



def best_cdx_pdf_timestamp(url: str) -> Optional[str]:
    """Pick a CDX snapshot timestamp that looks like a real PDF (status 200)."""
    try:
        # Prefer exact URL match via prefix of the path
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        host = (parts.hostname or "").replace("www.", "")
        path = parts.path or "/"
        # try a few URL variants
        candidates = []
        for u in (url, url.replace("https://", "http://"), url.replace("http://", "https://")):
            u2 = u.replace(":80/", "/")
            for h in cdx_urls(u2, limit=20, match_type="exact"):
                candidates.append(h)
            # also prefix on host+path
        prefix = f"{host}{path}".lstrip("/")
        if prefix:
            for h in cdx_urls(prefix, limit=30, match_type="prefix",
                              extra_filters=["mimetype:application/pdf"]):
                candidates.append(h)
            for h in cdx_urls("www." + prefix, limit=30, match_type="prefix",
                              extra_filters=["mimetype:application/pdf"]):
                candidates.append(h)
        best = None
        for h in candidates:
            ts = h.get("timestamp") or ""
            sc = str(h.get("statuscode") or h.get("status") or "")
            mt = (h.get("mimetype") or "").lower()
            orig = (h.get("original") or "").lower()
            if not ts:
                continue
            if sc and sc not in ("200", "226", "-"):
                continue
            score = 0
            if "pdf" in mt or orig.endswith(".pdf"):
                score += 2
            if sc == "200":
                score += 1
            if best is None or score > best[0] or (score == best[0] and ts > best[1]):
                best = (score, ts)
        return best[1] if best else None
    except Exception as exc:
        log.info("best_cdx_pdf_timestamp fail %s: %s", url[:80], exc)
        return None


def fetch_official_prefer_pdf(
    url: str,
    *,
    ua: str = DEFAULT_UA,
    verify: bool = True,
    min_text: int = MIN_TEXT,
    wayback_ts: Optional[str] = None,
) -> dict:
    """Live first; on failure, Wayback with CDX PDF timestamp when available."""
    got = fetch_official(url, ua=ua, verify=verify, wayback=True, wayback_ts=wayback_ts, min_text=min_text)
    if got.get("status") == "success" and not (got.get("text") or "").lstrip().startswith("%PDF"):
        # reject obvious HTML shells mistaken for success when URL is a PDF
        if url.lower().endswith(".pdf") and got.get("method") == "wayback_html":
            pass  # try timestamped below
        else:
            return got
    ts = wayback_ts or best_cdx_pdf_timestamp(url)
    if ts:
        got2 = fetch_official(url, ua=ua, verify=verify, wayback=True, wayback_ts=ts, min_text=min_text)
        if got2.get("status") == "success":
            return got2
        # try http variant with same ts
        alt = url.replace("https://", "http://") if url.startswith("https://") else url.replace("http://", "https://")
        got3 = fetch_official(alt, ua=ua, verify=verify, wayback=True, wayback_ts=ts, min_text=min_text)
        if got3.get("status") == "success":
            return got3
    return got

def first_title(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) >= 12 and not s.lower().startswith("just a moment"):
            return s[:240]
    return fallback[:240]


def save_instrument(
    *,
    cc: str,
    country: str,
    language: str,
    ident: str,
    title: str,
    text: str,
    source_url: str,
    source_type: str,
    license_text: str,
    collector: str,
    date: Optional[str] = None,
    article_re: Optional[re.Pattern] = None,
    extra_meta: Optional[dict] = None,
) -> bool:
    if not text or len(text) < MIN_TEXT:
        return False
    rid = slug_id(cc, ident)
    docs = split_custom(text, rid, source_url, date, article_re)
    rec = base_record(
        cc=cc,
        country=country,
        language=language,
        ident=ident,
        title=title or first_title(text, ident),
        text=text,
        source_url=source_url,
        source_type=source_type,
        license_text=license_text,
        collector=collector,
        date=iso_date(date) or date,
        documents=docs,
        extra_meta=extra_meta,
    )
    write_instrument(cc, rec)
    return True


def cdx_urls(host_or_url: str, *, limit: int = 200, match_type: str = "prefix", extra_filters=None) -> list[dict]:
    try:
        hits = af.search_wayback_machine(
            host_or_url,
            limit=limit,
            match_type=match_type,
            collapse="urlkey",
            extra_filters=extra_filters,
        )
    except Exception as exc:
        log.info("cdx err %s: %s", host_or_url, exc)
        return []
    return hits or []


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except Exception:
        return default
